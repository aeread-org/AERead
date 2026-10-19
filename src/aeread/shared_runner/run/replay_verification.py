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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..task.evaluation import EvaluationSetup, audit_family_receipt
from .publication import MANIFEST_FILENAME, episode_key
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


def _published_episodes(bundle: Path) -> dict[str, dict[str, str]]:
    """Episodes the bundle names in its trajectory grain, by receipt digest."""

    path = bundle / GRAIN
    episodes: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return episodes
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        digest = row.get("source_receipt_sha256")
        if isinstance(digest, str):
            episodes[digest] = {name: row.get(name) for name in _IDENTITY_FIELDS}
    return episodes


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
    ``evidence_missing`` when the bundle's trajectory grain names an episode
    whose receipt is not under ``run_root``. ``verified`` at the top level is
    true only when at least one row was checked and every row verified.

    Coverage is ``every_published_episode`` when the bundle carries the
    kernel trajectory grain, which lists its episodes; without it only the
    receipts found under ``run_root`` can be checked, and the report says so
    (``receipts_found_under_run_root``).
    """

    bundle = Path(bundle_root)
    root = Path(run_root)
    if not (bundle / MANIFEST_FILENAME).is_file():
        raise ValueError(f"no {MANIFEST_FILENAME} in {bundle}")
    if not root.is_dir():
        raise ValueError(f"run root is not a directory: {root}")
    published = published_receipt_digests(bundle)
    expected = _published_episodes(bundle)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for receipt_path in sorted(root.rglob(RECEIPT_FILENAME)):
        try:
            receipt = json.loads(receipt_path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        digest = receipt.get("receipt_sha256") if isinstance(receipt, Mapping) else None
        if not isinstance(digest, str) or digest not in published:
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
        rows.append(_row(digest, audited, status=VERIFIED, scored=bool(audited.get("scores"))))
    for digest, identity in sorted(expected.items()):
        if digest not in seen:
            rows.append(_row(digest, identity, status=EVIDENCE_MISSING))

    rows.sort(key=lambda row: (row["episode_key"] or "", row["source_receipt_sha256"]))
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in (VERIFIED, DIFFERS, EVIDENCE_MISSING)
    }
    manifest = json.loads((bundle / MANIFEST_FILENAME).read_bytes())
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "publication_id": manifest.get("publication_id") if isinstance(manifest, Mapping) else None,
        "manifest_sha256": manifest.get("manifest_sha256") if isinstance(manifest, Mapping) else None,
        "coverage": (
            "every_published_episode" if expected else "receipts_found_under_run_root"
        ),
        "counts": counts,
        "scored_rows_verified": sum(
            row["status"] == VERIFIED and bool(row["scored"]) for row in rows
        ),
        "duplicate_receipt_copies_ignored": duplicates,
        "verified": counts[VERIFIED] > 0
        and counts[DIFFERS] == 0
        and counts[EVIDENCE_MISSING] == 0,
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
        f"manifest_sha256={report['manifest_sha256']}"
    )
    for row in report["rows"]:
        if row["status"] != VERIFIED:
            print(f"  {row['status']}: {row['source_receipt_sha256']} {row['reason'] or ''}".rstrip())
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
