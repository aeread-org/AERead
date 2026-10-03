"""``aeread verify-replay``: recompute a published bundle's scores from its evidence.

A bundle's replay claim used to be a boolean the campaign computed while it
ran and the publisher copied into the bundle: across 30 bundles and 531
sealed rows nothing re-drove a published row through the environment and
recomputed its score (DC-T-01, the main Gate 2 blocker). The evidence lane
is reviewed by verification, and that review asks for replay.

This is that check, run by the reviewer rather than by the run that produced
the row. For every receipt the bundle publishes it finds the sealed attempt
under the run root, re-drives its recorded actions through the family
environment, recomputes the score, and compares it with the sealed receipt
the published row is bound to by digest. It makes no provider call and
writes nothing into the bundle or the run root.

The published bundle does not contain the run evidence (that is what its
privacy boundary excludes), so the run root is an input, and a published
episode whose evidence is not there is reported as ``evidence_missing``,
never as verified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..task.evaluation import EvaluationSetup, audit_family_receipt
from .publication import (
    MANIFEST_FILENAME,
    _sealed_manifest,
    bundle_artifact_digests,
    episode_key,
)
from .publish_trajectories import GRAIN, published_receipt_digests
from .resolver import canonical_json_bytes

REPORT_SCHEMA_VERSION = "aeread.bundle_replay_verification/0.1"
RECEIPT_FILENAME = "evaluation_receipt.json"

VERIFIED = "verified"
DIFFERS = "differs"
EVIDENCE_MISSING = "evidence_missing"

#: Builds the family's evaluation setup (sealed plan and trusted registry)
#: for one durable receipt. A plan is resolved from family source, so this is
#: the one family-owned part of the check.
ReplaySetupFactory = Callable[[Mapping[str, Any]], EvaluationSetup]

_IDENTITY_FIELDS = ("run_plan_id", "cell_id", "episode_attempt_id")
_PROJECTION_IDENTITY_FIELDS = (
    "run_plan_id",
    "run_plan_sha256",
    "cell_id",
    "case_id",
    "case_sha256",
    "episode_id",
    "episode_attempt_id",
    "primary_leaf_id",
)


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _identity_of(node: Mapping[str, Any]) -> dict[str, str] | None:
    values = {name: node.get(name) for name in _IDENTITY_FIELDS}
    if all(isinstance(value, str) and value for value in values.values()):
        return values  # type: ignore[return-value]
    return None


def _json_objects(value: Any):
    """Every JSON object in ``value``, nested ones included."""

    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_objects(child)


def _published_files(bundle: Path) -> list[str]:
    """Bundle-relative grain and receipts/ files; symlinks are never read."""

    paths = sorted((bundle / "trajectories").glob("*.jsonl"))
    paths += sorted((bundle / "receipts").glob("*.jsonl"))
    paths += sorted((bundle / "receipts").glob("*.json"))
    return [path.relative_to(bundle).as_posix() for path in paths if path.is_file() and not path.is_symlink()]


def _published_objects(bundle: Path, relatives: Sequence[str], malformed: list[str] | None = None):
    """Objects in the given files, with the bundle-relative file.

    A file that does not parse is recorded in ``malformed`` (when given) and
    skipped, never silently dropped.
    """

    for relative in relatives:
        path = bundle / relative
        try:
            text = path.read_text(encoding="utf-8")
            documents = (
                [json.loads(line) for line in text.splitlines() if line.strip()]
                if path.suffix == ".jsonl"
                else [json.loads(text)]
            )
        except (OSError, ValueError) as error:
            if malformed is not None:
                malformed.append(f"{relative}: does not parse as JSON ({type(error).__name__})")
            continue
        for document in documents:
            for node in _json_objects(document):
                yield relative, node


def _declared_receipts(
    manifest: Any, bundle: Path, readable_paths: Collection[str], malformed: list[str]
) -> tuple[dict[str, dict[str, str] | None], bool]:
    """Receipts the bundle declares it published, by digest, with identity if known.

    The union of the manifest's ``source_receipt_sha256s`` (top level or under
    ``source_bindings``; both layouts exist), its ``source_bindings``
    ``receipt_sha256s`` (the refund layout), and every ``source_receipt_sha256``
    in the trajectory grain and the receipts/ projections. ``receipt_sha256``
    in reports/ and tables/ is deliberately not read: those summaries also cite
    qualification and preflight receipts that are not published rows.

    Rows are read only from ``readable_paths``: the digest-checked sealed
    files when the manifest is ``sealed`` (so a file added after sealing
    cannot become the inventory), none when ``seal_only``, and every file
    when the bundle already failed the manifest check (for the report; that
    never passes). Anything malformed is
    appended to ``malformed``. Also returns whether a sealed grain declared
    at least one digest.
    """

    declared: dict[str, dict[str, str] | None] = {}
    grain_declared = False

    def add(digest: Any, identity: dict[str, str] | None) -> None:
        if digest not in declared or declared[digest] is None:
            declared[digest] = identity

    if isinstance(manifest, Mapping):
        bindings = manifest.get("source_bindings") if "source_bindings" in manifest else {}
        if not isinstance(bindings, Mapping):
            malformed.append("manifest source_bindings is not an object")
            bindings = {}
        for where, container, key in (
            ("manifest", manifest, "source_receipt_sha256s"),
            ("manifest source_bindings", bindings, "source_receipt_sha256s"),
            ("manifest source_bindings", bindings, "receipt_sha256s"),
        ):
            if key not in container:
                continue
            listed = container[key]
            if not isinstance(listed, list):
                malformed.append(f"{where} {key} is not a list")
                continue
            for index, digest in enumerate(listed):
                if _is_digest(digest):
                    add(digest, None)
                else:
                    malformed.append(f"{where} {key}[{index}] is not a sha256 digest: {digest!r}"[:160])
    if readable_paths:
        readable = [relative for relative in _published_files(bundle) if relative in readable_paths]
        for relative, node in _published_objects(bundle, readable, malformed):
            if "source_receipt_sha256" not in node:
                continue
            digest = node["source_receipt_sha256"]
            if not _is_digest(digest):
                malformed.append(f"{relative}: source_receipt_sha256 is not a sha256 digest: {digest!r}"[:160])
                continue
            add(digest, _identity_of(node))
            grain_declared = grain_declared or relative == GRAIN
    return declared, grain_declared


def _published_projections(
    bundle: Path, readable_paths: Collection[str], malformed: list[str]
) -> dict[str, list[tuple[str, Mapping[str, Any]]]]:
    """Every published projection row in the given receipts/ files, by digest.

    A projection is any object with a ``source_receipt_sha256``, whatever else
    it carries: a row without ``scores`` is still compared.
    """

    projections: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    receipts = [
        relative
        for relative in _published_files(bundle)
        if relative.startswith("receipts/") and relative in readable_paths
    ]
    for relative, node in _published_objects(bundle, receipts, malformed):
        if "source_receipt_sha256" not in node:
            continue
        digest = node["source_receipt_sha256"]
        if not _is_digest(digest):
            # Same wording as the inventory, so a sealed file is reported once.
            malformed.append(f"{relative}: source_receipt_sha256 is not a sha256 digest: {digest!r}"[:160])
            continue
        projections.setdefault(digest, []).append((relative, node))
    return projections


def _expected_primary_score(projection: Mapping[str, Any], audited: Mapping[str, Any]) -> Any:
    """The primary score the audited receipt gives the projection's primary leaf."""

    leaf_id = projection["primary_leaf_id"] if "primary_leaf_id" in projection else audited.get("primary_leaf_id")
    scores = audited.get("scores")
    for entry in scores if isinstance(scores, list) else []:
        leaf = entry.get("leaf") if isinstance(entry, Mapping) else None
        if isinstance(leaf, Mapping) and leaf.get("leaf_id") == leaf_id:
            primary = entry.get("primary")
            return primary.get("value") if isinstance(primary, Mapping) else None
    return None


def _projection_difference(
    projections: Sequence[tuple[str, Mapping[str, Any]]], audited: Mapping[str, Any]
) -> str | None:
    """Why a published projection disagrees with the audited receipt, if it does."""

    for relative, projection in projections:
        for name in _PROJECTION_IDENTITY_FIELDS:
            if name in projection and (name not in audited or projection[name] != audited[name]):
                return f"published projection {relative} {name} differs from the receipt"
        if "scores" in projection and canonical_json_bytes(projection["scores"]) != canonical_json_bytes(
            audited.get("scores")
        ):
            return f"published projection {relative} scores differ from the recomputed scores"
        if "primary_score" in projection and canonical_json_bytes(
            projection["primary_score"]
        ) != canonical_json_bytes(_expected_primary_score(projection, audited)):
            return f"published projection {relative} primary_score differs from the recomputed primary score"
    return None


def _artifact_list(manifest: Mapping[str, Any]) -> tuple[dict[str, str] | None, str | None]:
    """The manifest's per-file digests as path -> sha256, or why they are malformed.

    Two layouts: a dict path -> digest (kernel) and a list of
    ``{path, sha256, size_bytes}`` objects (early kernel). ``None`` with no
    problem means the manifest carries no list.
    """

    if "artifacts" not in manifest:
        return None, None
    listed = manifest["artifacts"]
    if isinstance(listed, Mapping):
        pairs = list(listed.items())
    elif isinstance(listed, list):
        pairs = [
            (item.get("path"), item.get("sha256")) if isinstance(item, Mapping) else (None, None)
            for item in listed
        ]
    else:
        return None, f"artifacts is a {type(listed).__name__}, not a digest map or list"
    sealed: dict[str, str] = {}
    for path, digest in pairs:
        if not isinstance(path, str) or not path or not _is_digest(digest) or sealed.get(path, digest) != digest:
            return None, f"artifacts holds a malformed or duplicate entry: {path!r}"
        sealed[path] = digest
    return sealed, None


def _seal_check(manifest: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Which seal the manifest carries and whether it recomputes.

    A manifest carrying ``manifest_sha256`` is a kernel manifest whatever its
    schema_version says, so an edited schema cannot dodge the recompute. The
    family layouts self-seal over everything else.
    """

    if "manifest_sha256" in manifest:
        return "manifest_sha256", _sealed_manifest(manifest)["manifest_sha256"] == manifest["manifest_sha256"]
    for field in ("artifact_sha256", "publication_sha256"):
        if field in manifest:
            body = {key: value for key, value in manifest.items() if key != field}
            return field, hashlib.sha256(canonical_json_bytes(body)).hexdigest() == manifest[field]
    return None, False


def _symlinks(bundle: Path) -> list[str]:
    return sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_symlink() and not any(part.startswith(".") for part in path.relative_to(bundle).parts)
    )


def _manifest_check(bundle: Path, manifest: Any) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Is the bundle still what its manifest sealed? Also the digest-checked file set.

    Statuses: ``sealed`` (the seal recomputes and every sealed file matches),
    ``seal_only`` (a family layout that self-seals but lists no per-file
    digests, so the files themselves are not sealed), ``tampered`` and
    ``unchecked`` (no recognised seal). Files added after sealing are listed
    as unsealed and are not a failure; a sealed file that changed or
    vanished, a seal that does not recompute, or any symlink is. The second
    value is the path -> digest set the verdict may read inventory from, only
    when ``sealed``.
    """

    result: dict[str, Any] = {
        "status": "unchecked",
        "reason": None,
        "seal_field": None,
        "altered_or_missing_artifacts": [],
        "unsealed_artifacts": [],
        "symlinks": _symlinks(bundle),
    }
    if not isinstance(manifest, Mapping):
        result.update(status="tampered", reason="the manifest is not a JSON object")
        return result, None
    seal_field, seal_ok = _seal_check(manifest)
    result["seal_field"] = seal_field
    if seal_field is None:
        result["reason"] = "the manifest carries no recognised seal"
        return result, None
    sealed, malformed = _artifact_list(manifest)
    problems = []
    if not seal_ok:
        problems.append(f"{seal_field} does not recompute from the manifest")
    if malformed:
        problems.append(malformed)
    elif not isinstance(manifest.get("artifacts"), Mapping) and seal_field == "manifest_sha256":
        problems.append("kernel manifest without an artifact digest map")
    if result["symlinks"]:
        problems.append("symlinks in the bundle: " + ", ".join(result["symlinks"][:5]))
    if sealed is not None:
        current = bundle_artifact_digests(bundle)
        result["altered_or_missing_artifacts"] = sorted(
            path for path, digest in sealed.items() if current.get(path) != digest
        )
        result["unsealed_artifacts"] = sorted(set(current) - set(sealed))
        if result["altered_or_missing_artifacts"]:
            problems.append(
                f"{len(result['altered_or_missing_artifacts'])} sealed artifacts altered or missing: "
                + ", ".join(result["altered_or_missing_artifacts"][:5])
            )
    result["reason"] = "; ".join(problems) or None
    if problems:
        result["status"] = "tampered"
        return result, None
    result["status"] = "sealed" if sealed is not None else "seal_only"
    return result, sealed


def _row(
    receipt_sha256: str,
    identity: Mapping[str, Any],
    *,
    status: str,
    scored: bool | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    key = None
    if all(isinstance(identity.get(name), str) and identity.get(name) for name in _IDENTITY_FIELDS):
        key = episode_key(identity)
    return {
        "source_receipt_sha256": receipt_sha256,
        **{name: identity.get(name) for name in _IDENTITY_FIELDS},
        "episode_key": key,
        "status": status,
        "scored": scored,
        "reason": reason,
    }


def verify_bundle_replay(
    bundle_root: Path | str,
    run_root: Path | str,
    *,
    setup_for: ReplaySetupFactory,
) -> dict[str, Any]:
    """Re-drive every receipt a bundle publishes and report what replays.

    A row is ``verified`` when its sealed attempt is found under ``run_root``
    and :func:`audit_family_receipt` recomputes the same state and score from
    the sealed events; ``differs`` with the reason when it does not; and
    ``evidence_missing`` when the bundle declares a receipt (manifest list,
    grain or projection row) that is not under ``run_root``. A row also
    differs when a published projection of it carries other scores or
    identities than the recomputed receipt. ``verified`` at the top level is
    true only when at least one row verified, none differs or is missing, and
    the bundle declares what it published and its manifest is not ``tampered``
    (seal not recomputing, a sealed artifact altered or missing, a symlink; family
    layouts without an artifact list are ``seal_only``; a manifest with no
    recognised seal is ``unchecked`` and not verified), and nothing declared
    was malformed; otherwise ``verdict_reasons`` says why. The declared
    inventory reads manifest lists, plus grain and projection rows only from
    files the manifest sealed.

    Coverage is ``every_published_episode`` when a sealed trajectory grain
    declared receipts,
    ``declared_receipts`` when only the manifest or projections declare the
    set, and ``receipts_found_under_run_root`` when nothing is declared: then
    missing evidence cannot be detected and the run is never verified.
    """

    bundle = Path(bundle_root)
    root = Path(run_root)
    if not (bundle / MANIFEST_FILENAME).is_file():
        raise ValueError(f"no {MANIFEST_FILENAME} in {bundle}")
    if not root.is_dir():
        raise ValueError(f"run root is not a directory: {root}")
    try:
        manifest: Any = json.loads((bundle / MANIFEST_FILENAME).read_bytes())
    except ValueError:
        manifest = None
    manifest_check, sealed_paths = _manifest_check(bundle, manifest)
    malformed: list[str] = []
    if manifest_check["status"] == "sealed":
        readable: Collection[str] = sealed_paths or ()
    elif manifest_check["status"] == "seal_only":
        readable = ()
    else:
        readable = _published_files(bundle)
    declared, grain_declared = _declared_receipts(manifest, bundle, readable, malformed)
    # A symlinked bundle is tampered whatever it holds; none of it is read.
    no_symlinks = not manifest_check["symlinks"]
    published = published_receipt_digests(bundle) if no_symlinks else frozenset()
    # Comparison may read receipts/ of a seal_only bundle (never as inventory).
    if manifest_check["status"] == "seal_only":
        projection_files: Collection[str] = _published_files(bundle)
    else:
        projection_files = readable
    projections = _published_projections(bundle, projection_files, malformed) if no_symlinks else {}
    malformed[:] = list(dict.fromkeys(malformed))
    projections_checked = 0

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for receipt_path in sorted(root.rglob(RECEIPT_FILENAME)):
        try:
            receipt = json.loads(receipt_path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        digest = receipt.get("receipt_sha256") if isinstance(receipt, Mapping) else None
        if not isinstance(digest, str) or digest not in published and digest not in declared:
            continue
        if digest in seen:
            duplicates += 1
            continue
        seen.add(digest)
        try:
            audited = audit_family_receipt(
                setup=setup_for(receipt), receipt_path=receipt_path
            )
        except Exception as error:  # every failure to replay is a finding
            rows.append(
                _row(digest, receipt, status=DIFFERS, reason=f"{type(error).__name__}: {error}")
            )
            continue
        published_rows = projections.get(digest, [])
        projections_checked += len(published_rows)
        difference = _projection_difference(published_rows, audited)
        if difference:
            rows.append(_row(digest, audited, status=DIFFERS, reason=difference))
            continue
        rows.append(_row(digest, audited, status=VERIFIED, scored=bool(audited.get("scores"))))
    for digest, identity in sorted(declared.items()):
        if digest not in seen:
            rows.append(_row(digest, identity or {}, status=EVIDENCE_MISSING))

    rows.sort(key=lambda row: (row["episode_key"] or "", row["source_receipt_sha256"]))
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in (VERIFIED, DIFFERS, EVIDENCE_MISSING)
    }
    if grain_declared:
        coverage = "every_published_episode"
    elif declared:
        coverage = "declared_receipts"
    else:
        coverage = "receipts_found_under_run_root"
    reasons: list[str] = []
    if manifest_check["status"] in ("tampered", "unchecked"):
        reasons.append(f"manifest check failed ({manifest_check['status']}): {manifest_check['reason']}")
    if malformed:
        reasons.append(f"{len(malformed)} malformed declarations: " + "; ".join(malformed[:3]))
    if coverage == "receipts_found_under_run_root":
        reasons.append(
            "the bundle declares no receipt inventory (no manifest source_receipt_sha256s, "
            "no source_receipt_sha256 rows), so missing evidence cannot be detected"
        )
    if counts[EVIDENCE_MISSING]:
        reasons.append(f"{counts[EVIDENCE_MISSING]} published receipts have no evidence under the run root")
    if counts[DIFFERS]:
        reasons.append(f"{counts[DIFFERS]} rows differ")
    if not counts[VERIFIED] and not counts[DIFFERS] and not counts[EVIDENCE_MISSING]:
        reasons.append("no row was checked")
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "publication_id": manifest.get("publication_id") if isinstance(manifest, Mapping) else None,
        "manifest_sha256": manifest.get("manifest_sha256") if isinstance(manifest, Mapping) else None,
        "manifest": manifest_check,
        "coverage": coverage,
        "declared_receipts": len(declared),
        "malformed_declarations": malformed,
        "published_projections_checked": projections_checked,
        "counts": counts,
        "scored_rows_verified": sum(
            row["status"] == VERIFIED and bool(row["scored"]) for row in rows
        ),
        "duplicate_receipt_copies_ignored": duplicates,
        "verified": not reasons,
        "verdict_reasons": reasons,
        "rows": rows,
    }
    return report


def _load_factory(reference: str) -> ReplaySetupFactory:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("--setup must be MODULE:CALLABLE")
    factory = getattr(importlib.import_module(module_name), attribute, None)
    if not callable(factory):
        raise ValueError(f"--setup does not name a callable: {reference}")
    return factory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aeread verify-replay",
        description="recompute a published bundle's scores from its sealed run evidence",
    )
    parser.add_argument("bundle", type=Path, help="evidence/<family>/<publication_id> bundle root")
    parser.add_argument("--run-root", type=Path, required=True, help="local run root holding the sealed attempts")
    parser.add_argument(
        "--setup",
        required=True,
        metavar="MODULE:CALLABLE",
        help="family callable taking a durable receipt and returning its evaluation setup",
    )
    parser.add_argument("--json", type=Path, help="also write the full report here")
    args = parser.parse_args(argv)
    try:
        report = verify_bundle_replay(
            args.bundle, args.run_root, setup_for=_load_factory(args.setup)
        )
    except (ValueError, ImportError) as error:
        parser.exit(2, f"aeread verify-replay: {error}\n")
    if args.json is not None:
        args.json.write_bytes(canonical_json_bytes(report) + b"\n")
    counts = report["counts"]
    print(
        f"{report['publication_id']}: {counts[VERIFIED]} verified "
        f"({report['scored_rows_verified']} scored), {counts[DIFFERS]} differ, "
        f"{counts[EVIDENCE_MISSING]} evidence missing; coverage={report['coverage']}; "
        f"manifest={report['manifest']['status']}; "
        f"manifest_sha256={report['manifest_sha256']}"
    )
    for row in report["rows"]:
        if row["status"] != VERIFIED:
            print(f"  {row['status']}: {row['source_receipt_sha256']} {row['reason'] or ''}".rstrip())
    for reason in report["verdict_reasons"]:
        print(f"  not verified: {reason}")
    return 0 if report["verified"] else 1


__all__ = [
    "DIFFERS",
    "EVIDENCE_MISSING",
    "REPORT_SCHEMA_VERSION",
    "ReplaySetupFactory",
    "VERIFIED",
    "main",
    "verify_bundle_replay",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
