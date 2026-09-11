"""Provider-free Refund V2.1 1:N panel experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .v2_environment import build_1n_panel, run_scripted_1n
from .v2_llm_experiment import _write_trajectory_evidence


def run(seeds: tuple[int, ...], output: Path) -> dict:
    rows = []
    for seed in seeds:
        for case in build_1n_panel(seed):
            state, outcome = run_scripted_1n(case)
            rows.append({
                "case_id": case.case_id,
                "world_seed": seed,
                "scenario": case.scenario,
                "positive": case.authorized_refund_amount > 0,
                "content_sha256": case.content_sha256,
                "transcript": state.transcript,
                "handoffs": state.handoffs,
                "proposals": state.proposals,
                "confirmations": state.confirmations,
                "transactions": state.transactions,
                "invalid_fact_requests": state.invalid_fact_requests,
                "outcome": {
                    "decision": outcome.decision,
                    "utility_score": outcome.utility_score,
                    "transaction_score": outcome.transaction_score,
                    "coordination_score": outcome.coordination_score,
                    "policy_compliant": outcome.policy_compliant,
                    "verifier_reasons": outcome.verifier_reasons,
                },
            })
    report = {
        "family_id": "refund_v2",
        "family_version": "2.1.0",
        "topology": "1:N",
        "seeds": seeds,
        "scenarios": sorted({row["scenario"] for row in rows}),
        "planned_cases": len(rows),
        "completed_cases": len(rows),
        "operational_failures": 0,
        "results": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_trajectory_evidence(output, rows)
    (output / "refund_v2_1n_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-seeds", default="1,2,3,4,5")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    seeds = tuple(int(item.strip()) for item in args.world_seeds.split(",") if item.strip())
    print(json.dumps(run(seeds, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
