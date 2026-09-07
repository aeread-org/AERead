"""Add a sanitized trajectory grain to an already-published kernel-standard bundle.

Usage:
    python tools/publish_sanitized_trajectories.py <bundle_root> <attempt_dir>...

Each attempt directory is a sealed evidence store holding ``evaluation_receipt.json``.
Every receipt must already be published in the bundle (its digest must appear in the
bundle's reports), so the grain never widens what the bundle claims. Rows are written
to ``trajectories/sanitized.jsonl`` and the manifest is re-sealed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from aeread.shared_runner.run.publication import (
    add_publication_artifact,
    sanitized_trajectory_jsonl,
    sanitized_trajectory_rows,
)
from aeread.shared_runner.task.execution import EvidenceStore

GRAIN = "trajectories/sanitized.jsonl"


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    bundle = Path(argv[1])
    published = set()
    for report in (bundle / "reports").glob("*.json"):
        published.update(re.findall(r"[0-9a-f]{64}", report.read_text()))

    rows: list[dict] = []
    receipts: list[dict] = []
    for attempt_dir in map(Path, argv[2:]):
        receipt = json.loads((attempt_dir / "evaluation_receipt.json").read_bytes())
        if receipt["receipt_sha256"] not in published:
            raise SystemExit(f"receipt not published by this bundle: {attempt_dir}")
        receipts.append(receipt)
        evidence = EvidenceStore.audit_existing(attempt_dir)
        rows.extend(sanitized_trajectory_rows(evidence, receipt))

    order = {
        r["receipt_sha256"]: (r["cell_id"], r["case_id"], r["episode_attempt_id"])
        for r in receipts
    }
    rows.sort(key=lambda row: (order[row["source_receipt_sha256"]], row["step_index"]))
    manifest = add_publication_artifact(bundle, GRAIN, sanitized_trajectory_jsonl(rows))
    print(
        f"{len(rows)} rows from {len(receipts)} receipts -> {bundle / GRAIN}; "
        f"manifest_sha256={manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
