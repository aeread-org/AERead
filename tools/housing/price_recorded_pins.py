"""The implementation pins each published Housing price plan was sealed under, read from the sealed receipts.

    PYTHONPATH=src python tools/housing/price_recorded_pins.py --run-root DIR [--run-root DIR ...] [--check]

A v14 or v15 run plan pins the kernel's runtime modules by digest, so a kernel commit that touches them moves every
plan id (HL-T-11). Replay restores each receipt's own pins (``aeread_families.housing.price_replay``), and the receipt
carries them; the published bundles do not. This table records them per published plan so that a test can rebuild
every published plan from current source without the run roots. Every receipt under a ``--run-root`` (a campaign
directory holding ``live/``) is read; all receipts of one plan must agree on the plan digest and the pins, and the
table keeps only plans the published bundles name. ``--check`` compares with the committed table instead of writing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TABLE = Path(__file__).resolve().with_name("price_recorded_pins.json")
EVIDENCE = ROOT / "evidence" / "housing"
#: Each published bundle and the file in it that names its plans.
PUBLISHED = {
    "housing_lemons_price_confirmatory_v14": "tables/cells.jsonl",
    "housing_lemons_price_confirmatory_v14_gemini_fill": "tables/cells.jsonl",
    "housing_lemons_price_v15_confirmatory": "receipts/projections.jsonl",
    "housing_lemons_price_v15_glm_addendum": "receipts/projections.jsonl",
    "housing_lemons_price_v15_cli_addendum": "receipts/projections.jsonl",
}


def published_plans() -> dict[str, str]:
    """Each run_plan_id the published bundles name, with the bundle that names it."""
    plans: dict[str, str] = {}
    for bundle, name in PUBLISHED.items():
        for line in (EVIDENCE / bundle / name).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("run_plan_id"):
                plans.setdefault(row["run_plan_id"], bundle)
    return plans


def table(run_roots: list[Path]) -> dict[str, Any]:
    wanted = published_plans()
    found: dict[str, dict[str, Any]] = {}
    receipts = 0
    for run_root in run_roots:
        for path in sorted(run_root.glob("live/**/evaluation_receipt.json")):
            receipt = json.loads(path.read_text(encoding="utf-8"))
            plan_id = receipt["run_plan_id"]
            if plan_id not in wanted:
                continue
            receipts += 1
            entry = {"run_plan_sha256": receipt["run_plan_sha256"],
                     "plan_implementation_pins": receipt["plan_implementation_pins"]}
            if found.setdefault(plan_id, entry) != entry:
                raise ValueError(f"receipts of {plan_id} disagree on the plan digest or pins ({path})")
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise ValueError(f"no sealed receipt under the run roots for {missing}")
    return {"schema_version": "aeread.housing_price_recorded_pins/0.1",
            "source": "the sealed evaluation receipts of every published plan, one entry per plan",
            "receipts_read": receipts,
            "plans": {plan_id: {"bundle": wanted[plan_id], **found[plan_id]} for plan_id in sorted(found)}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-root", type=Path, action="append", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    payload = (json.dumps(table(args.run_root), indent=1, sort_keys=True) + "\n").encode("utf-8")
    if args.check:
        same = TABLE.read_bytes() == payload
        print("recorded pins match the sealed receipts" if same else "recorded pins differ from the sealed receipts")
        return 0 if same else 1
    TABLE.write_bytes(payload)
    print(f"wrote {TABLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
