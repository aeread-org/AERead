"""``aeread publish-trajectories``: add the kernel trajectory grain to a bundle.

Adds ``trajectories/sanitized.jsonl`` (one row per logical action, schema
``aeread.sanitized_trajectory_row/0.1``) to an already-published
``aeread.publication_manifest/0.1`` bundle and re-seals its manifest. Every
attempt directory is a sealed evidence store holding ``evaluation_receipt.json``;
each receipt must already be published by the bundle, so the grain can never
widen what the bundle claims. This is a QC §4 mechanical correction: the
earlier manifest stays in history and no reported number changes.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .publication import (
    add_publication_artifact,
    sanitized_trajectory_jsonl,
    sanitized_trajectory_rows,
)

GRAIN = "trajectories/sanitized.jsonl"


def published_receipt_digests(bundle: Path) -> frozenset[str]:
    """Every receipt digest a bundle's reports mention."""

    digests: set[str] = set()
    for report in sorted((bundle / "reports").glob("*.json")):
        digests.update(re.findall(r"[0-9a-f]{64}", report.read_text()))
    return frozenset(digests)


def publish_trajectory_grain(
    bundle: Path, attempt_dirs: Sequence[Path]
) -> tuple[int, dict[str, Any]]:
    """Project ``attempt_dirs`` into the bundle's grain; return (rows, manifest)."""

    from ..task.execution import EvidenceStore

    published = published_receipt_digests(bundle)
    rows: list[dict[str, Any]] = []
    order: dict[str, tuple[str, str, str]] = {}
    for attempt_dir in attempt_dirs:
        receipt = json.loads((attempt_dir / "evaluation_receipt.json").read_bytes())
        if receipt["receipt_sha256"] not in published:
            raise ValueError(f"receipt not published by this bundle: {attempt_dir}")
        order[receipt["receipt_sha256"]] = (
            receipt["cell_id"],
            receipt["case_id"],
            receipt["episode_attempt_id"],
        )
        rows.extend(sanitized_trajectory_rows(EvidenceStore.audit_existing(attempt_dir), receipt))
    rows.sort(key=lambda row: (order[row["source_receipt_sha256"]], row["step_index"]))
    manifest = add_publication_artifact(bundle, GRAIN, sanitized_trajectory_jsonl(rows))
    return len(rows), manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aeread publish-trajectories",
        description="add the kernel trajectory grain to a published bundle and re-seal its manifest",
    )
    parser.add_argument("bundle", type=Path, help="evidence/<campaign_id> bundle root")
    parser.add_argument(
        "attempt_dirs",
        nargs="+",
        type=Path,
        help="sealed attempt directories (each holds evaluation_receipt.json)",
    )
    args = parser.parse_args(argv)
    try:
        count, manifest = publish_trajectory_grain(args.bundle, args.attempt_dirs)
    except ValueError as error:
        parser.exit(1, f"aeread publish-trajectories: {error}\n")
    print(
        f"{count} rows from {len(args.attempt_dirs)} receipts -> {args.bundle / GRAIN}; "
        f"manifest_sha256={manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
