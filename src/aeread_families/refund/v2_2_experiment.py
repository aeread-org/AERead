"""Run the provider-free Refund V2.2 N:1 conformance panel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from .v2_2_environment import build_n1_panel, run_scripted_n1


def run(*, world_seeds: tuple[int, ...], output: Path) -> dict:
    rows = []
    for seed in world_seeds:
        batch = build_n1_panel(seed)
        state, outcome = run_scripted_n1(batch)
        rows.append({
            "world_seed": seed,
            "batch_id": batch.batch_id,
            "batch_sha256": batch.content_sha256,
            "refund_budget": batch.refund_budget,
            "review_capacity": batch.review_capacity,
            "case_ids": [case.case_id for case in batch.cases],
            "selected_case_ids": list(outcome.selected_case_ids),
            "policy_compliant": outcome.policy_compliant,
            "allocation_score": outcome.allocation_score,
            "transaction_score": outcome.transaction_score,
            "coordination_score": outcome.coordination_score,
            "system_utility": outcome.system_utility,
            "verifier_reasons": list(outcome.verifier_reasons),
            "transaction_count": len(state.transactions),
            "budget_remaining": state.budget_remaining,
            "transcript_length": len(state.transcript),
        })
    summary = {
        "schema_version": "aeread.refund_v22_conformance_summary/0.1",
        "family_id": "refund_v2",
        "family_version": "2.2.0",
        "topology": "N:1",
        "evaluation_kind": "provider_free_scripted_conformance",
        "world_seeds": list(world_seeds),
        "planned_batches": len(rows),
        "customer_cases_per_batch": 3,
        "planned_customer_cases": len(rows) * 3,
        "metrics": {
            "policy_compliance": mean(float(row["policy_compliant"]) for row in rows) if rows else None,
            "allocation": mean(row["allocation_score"] for row in rows) if rows else None,
            "transaction": mean(row["transaction_score"] for row in rows) if rows else None,
            "coordination": mean(row["coordination_score"] for row in rows) if rows else None,
            "system_utility": mean(row["system_utility"] for row in rows) if rows else None,
        },
        "claim_boundary": "provider-free conformance of the declared N:1 cases; not a model comparison or population estimate",
        "batches": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "refund_v2_2_conformance_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-seeds", default="0,1,2,3,4,5")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seeds = tuple(int(item.strip()) for item in args.world_seeds.split(",") if item.strip())
    summary = run(world_seeds=seeds, output=args.output)
    print(json.dumps({"planned_batches": summary["planned_batches"], "planned_customer_cases": summary["planned_customer_cases"], "metrics": summary["metrics"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
