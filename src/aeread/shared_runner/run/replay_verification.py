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
import importlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..task.evaluation import EvaluationSetup, audit_family_receipt
from .publication import (
    KERNEL_MANIFEST_SCHEMA_VERSION,
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


def _published_objects(bundle: Path):
    """Objects in the grain and in receipts/, with the bundle-relative file."""

    paths = sorted((bundle / "trajectories").glob("*.jsonl"))
    paths += sorted((bundle / "receipts").glob("*.jsonl"))
    paths += sorted((bundle / "receipts").glob("*.json"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        documents = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if path.suffix == ".jsonl"
            else [json.loads(text)]
        )
        relative = path.relative_to(bundle).as_posix()
        for document in documents:
            for node in _json_objects(document):
                yield relative, node


def _declared_receipts(bundle: Path) -> dict[str, dict[str, str] | None]:
    """Receipts the bundle declares it published, by digest, with identity if known.

    The union of the manifest's ``source_receipt_sha256s`` (top level or under
    ``source_bindings``; both layouts exist), its ``source_bindings``
    ``receipt_sha256s`` (the refund layout), and every ``source_receipt_sha256``
    in the trajectory grain and the receipts/ projections. ``receipt_sha256``
    in reports/ and tables/ is deliberately not read: those summaries also cite
    qualification and preflight receipts that are not published rows.
    """

    declared: dict[str, dict[str, str] | None] = {}

    def add(digest: Any, identity: dict[str, str] | None) -> None:
        if _is_digest(digest) and (declared.get(digest) is None):
            declared[digest] = identity

    manifest = json.loads((bundle / MANIFEST_FILENAME).read_bytes())
    if isinstance(manifest, Mapping):
        bindings = manifest.get("source_bindings")
        bindings = bindings if isinstance(bindings, Mapping) else {}
        lists = (
            manifest.get("source_receipt_sha256s"),
            bindings.get("source_receipt_sha256s"),
            bindings.get("receipt_sha256s"),
        )
        for listed in lists:
            for digest in listed if isinstance(listed, list) else ():
                add(digest, None)
    for _relative, node in _published_objects(bundle):
        add(node.get("source_receipt_sha256"), _identity_of(node))
    return declared


def _published_projections(bundle: Path) -> dict[str, list[tuple[str, Mapping[str, Any]]]]:
    """Published projection rows (digest and scores) in receipts/, by digest."""

    projections: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for relative, node in _published_objects(bundle):
        digest = node.get("source_receipt_sha256")
        if relative.startswith("receipts/") and _is_digest(digest) and "scores" in node:
            projections.setdefault(digest, []).append((relative, node))
    return projections


def _projection_difference(
    projections: Sequence[tuple[str, Mapping[str, Any]]], audited: Mapping[str, Any]
) -> str | None:
    """Why a published projection disagrees with the audited receipt, if it does."""

    for relative, projection in projections:
        if canonical_json_bytes(projection["scores"]) != canonical_json_bytes(audited.get("scores")):
            return f"published projection {relative} scores differ from the recomputed scores"
        for name in ("run_plan_id", "cell_id", "episode_id", "episode_attempt_id"):
            if name in projection and projection[name] != audited.get(name):
                return f"published projection {relative} {name} differs from the receipt"
    return None


def _manifest_check(bundle: Path, manifest: Any) -> dict[str, Any]:
    """Is the bundle still what its manifest sealed?

    Only the kernel layout seals a digest per artifact; family-specific
    layouts are reported ``unchecked``, not failed. Files added after sealing
    (a README, qc/) are listed as unsealed and are not a failure; a sealed
    file that changed or vanished, or a seal that does not recompute, is.
    """

    result: dict[str, Any] = {
        "status": "unchecked",
        "reason": None,
        "altered_or_missing_artifacts": [],
        "unsealed_artifacts": [],
    }
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != KERNEL_MANIFEST_SCHEMA_VERSION:
        schema = manifest.get("schema_version") if isinstance(manifest, Mapping) else None
        result["reason"] = f"manifest schema {schema!r} is not {KERNEL_MANIFEST_SCHEMA_VERSION}"
        return result
    sealed = manifest.get("artifacts")
    if not isinstance(sealed, Mapping):
        result["reason"] = "manifest has no artifact digest list"
        return result
    current = bundle_artifact_digests(bundle)
    result["altered_or_missing_artifacts"] = sorted(
        path for path, digest in sealed.items() if current.get(path) != digest
    )
    result["unsealed_artifacts"] = sorted(set(current) - set(sealed))
    seal_ok = _sealed_manifest(manifest).get("manifest_sha256") == manifest.get("manifest_sha256")
    problems = []
    if not seal_ok:
        problems.append("manifest_sha256 does not recompute from the manifest")
    if result["altered_or_missing_artifacts"]:
        problems.append(
            f"{len(result['altered_or_missing_artifacts'])} sealed artifacts altered or missing: "
            + ", ".join(result["altered_or_missing_artifacts"][:5])
        )
    result["status"] = "tampered" if problems else "sealed"
    result["reason"] = "; ".join(problems) or None
    return result


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
    (seal not recomputing, or a sealed artifact altered or missing; family
    layouts without an artifact list are ``unchecked``); otherwise ``verdict_reasons`` says
    why.

    Coverage is ``every_published_episode`` with the trajectory grain,
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
    published = published_receipt_digests(bundle)
    declared = _declared_receipts(bundle)
    projections = _published_projections(bundle)
    has_grain = (bundle / GRAIN).is_file()
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
    manifest = json.loads((bundle / MANIFEST_FILENAME).read_bytes())
    if has_grain:
        coverage = "every_published_episode"
    elif declared:
        coverage = "declared_receipts"
    else:
        coverage = "receipts_found_under_run_root"
    manifest_check = _manifest_check(bundle, manifest)
    reasons: list[str] = []
    if manifest_check["status"] == "tampered":
        reasons.append(f"manifest check failed: {manifest_check['reason']}")
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
