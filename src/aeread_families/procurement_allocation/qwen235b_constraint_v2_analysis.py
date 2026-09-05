"""Digest-bound analysis and publication for the Qwen3 235B V2 constraint repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .case_matrix import CASE_VARIANCE_PATHS
from .model_campaign import publish_model_qualification
from .qwen_case_campaign import PAIRED_INFERENCE_SEEDS
from .qwen235b_constraint_campaign import (
    CAMPAIGN_ID as V1_CAMPAIGN_ID,
    SPEC as V1_SPEC,
    build_plan as build_v1_plan,
)
from .qwen235b_constraint_v2_campaign import (
    CAMPAIGN_ID as V2_CAMPAIGN_ID,
    SPEC as V2_SPEC,
    build_plan as build_v2_plan,
)
from .qwen235b_google_case_campaign import (
    CAMPAIGN_ID as CONTROL_CAMPAIGN_ID,
    QWEN235B_GOOGLE_CANDIDATE,
    build_plan as build_control_plan,
)
from .qwen235b_route_analysis import (
    METRICS,
    _cluster_interval,
    _first_action,
    _metric,
    _row_index,
    _verified_outer,
    _verified_summary,
)


def _paired(
    *, left: Mapping[str, Any], right: Mapping[str, Any], effect_name: str
) -> tuple[dict[str, Any], dict[str, bool]]:
    left_rows = _row_index(left)
    right_rows = _row_index(right)
    expected_keys = {
        (f"procurement_allocation_v1.dev.{path.stem}", seed)
        for path in CASE_VARIANCE_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    }
    all_keys = sorted(set(left_rows) | set(right_rows))
    feasibility_transitions: Counter[str] = Counter()
    first_action_transitions: Counter[str] = Counter()
    termination_transitions: Counter[str] = Counter()
    per_case_pairs: dict[str, list[dict[str, Any]]] = {}
    pairs: list[dict[str, Any]] = []
    completed_pair_count = 0
    content_match = True
    bounds_match = True
    for case_id, seed in all_keys:
        left_row = left_rows.get((case_id, seed))
        right_row = right_rows.get((case_id, seed))
        pair: dict[str, Any] = {"case_id": case_id, "inference_seed": seed}
        if left_row is not None and right_row is not None:
            content_match = content_match and (
                left_row.get("case_content_sha256")
                == right_row.get("case_content_sha256")
            )
            completed = (
                left_row.get("status") == right_row.get("status") == "completed"
                and left_row.get("receipt_replayed") is True
                and right_row.get("receipt_replayed") is True
            )
            if completed:
                completed_pair_count += 1
                bounds_match = bounds_match and (
                    float(left_row["upper_bound_usd"])
                    == float(right_row["upper_bound_usd"])
                )
                feasibility_transition = (
                    f"{'pass' if left_row.get('feasible') else 'fail'}_to_"
                    f"{'pass' if right_row.get('feasible') else 'fail'}"
                )
                first_action_transition = (
                    f"{_first_action(left_row)}_to_{_first_action(right_row)}"
                )
                termination_transition = (
                    f"{left_row.get('termination_reason')}_to_"
                    f"{right_row.get('termination_reason')}"
                )
                feasibility_transitions[feasibility_transition] += 1
                first_action_transitions[first_action_transition] += 1
                termination_transitions[termination_transition] += 1
                effects = {
                    metric: _metric(right_row, metric) - _metric(left_row, metric)
                    for metric in METRICS
                }
                pair.update(
                    {
                        "feasibility_transition": feasibility_transition,
                        "first_action_transition": first_action_transition,
                        "termination_transition": termination_transition,
                        effect_name: effects,
                    }
                )
        pairs.append(pair)
        per_case_pairs.setdefault(case_id, []).append(pair)

    per_case: dict[str, Any] = {}
    for case_id, case_pairs in sorted(per_case_pairs.items()):
        completed = [pair for pair in case_pairs if effect_name in pair]
        per_case[case_id] = {
            "pair_count": len(case_pairs),
            "completed_pair_count": len(completed),
            "mean_effects": {
                metric: statistics.fmean(
                    pair[effect_name][metric] for pair in completed
                )
                if completed
                else None
                for metric in METRICS
            },
        }
    aggregate: dict[str, Any] = {}
    for metric in METRICS:
        case_effects = [
            float(per_case[case_id]["mean_effects"][metric])
            for case_id in sorted(per_case)
        ]
        aggregate[metric] = {
            "case_cluster_mean": statistics.fmean(case_effects),
            "case_cluster_bootstrap_95_interval": _cluster_interval(case_effects),
        }
    return (
        {
            "completed_pair_count": completed_pair_count,
            "feasibility_transition_counts": dict(
                sorted(feasibility_transitions.items())
            ),
            "first_action_transition_counts": dict(
                sorted(first_action_transitions.items())
            ),
            "termination_transition_counts": dict(
                sorted(termination_transitions.items())
            ),
            "aggregate_effects": aggregate,
            "per_case": per_case,
            "pairs": pairs,
        },
        {
            "case_and_seed_identities_match": (
                set(left_rows) == set(right_rows) == expected_keys
            ),
            "case_content_digests_match": content_match,
            "all_pairs_completed_and_replayed": (
                completed_pair_count == len(expected_keys)
            ),
            "upper_bounds_match": bounds_match,
        },
    )


def build_v2_analysis(
    *, control_run_root: Path, v1_run_root: Path, v2_run_root: Path
) -> dict[str, Any]:
    control, control_file_sha = _verified_summary(
        control_run_root, campaign_id=CONTROL_CAMPAIGN_ID
    )
    v1, v1_file_sha = _verified_summary(v1_run_root, campaign_id=V1_CAMPAIGN_ID)
    v2, v2_file_sha = _verified_summary(v2_run_root, campaign_id=V2_CAMPAIGN_ID)
    control_outer, control_canary = _verified_outer(
        control_run_root,
        campaign_id=CONTROL_CAMPAIGN_ID,
        frozen_plan=build_control_plan(),
        candidate=QWEN235B_GOOGLE_CANDIDATE,
    )
    v1_outer, v1_canary = _verified_outer(
        v1_run_root,
        campaign_id=V1_CAMPAIGN_ID,
        frozen_plan=build_v1_plan(),
        candidate=QWEN235B_GOOGLE_CANDIDATE,
    )
    v2_outer, v2_canary = _verified_outer(
        v2_run_root,
        campaign_id=V2_CAMPAIGN_ID,
        frozen_plan=build_v2_plan(),
        candidate=QWEN235B_GOOGLE_CANDIDATE,
    )
    repair, repair_integrity = _paired(
        left=v1, right=v2, effect_name="effects_v2_minus_v1"
    )
    development, development_integrity = _paired(
        left=control, right=v2, effect_name="effects_v2_minus_control"
    )
    plans = (control["plan"], v1["plan"], v2["plan"])
    summaries = (control["summary"], v1["summary"], v2["summary"])
    canaries = (control_canary, v1_canary, v2_canary)
    integrity = {
        **{f"repair_{key}": value for key, value in repair_integrity.items()},
        **{
            f"development_{key}": value
            for key, value in development_integrity.items()
        },
        "inference_seeds_match": all(
            plan.get("inference_seeds") == list(PAIRED_INFERENCE_SEEDS)
            for plan in plans
        ),
        "harness_and_route_match": all(
            plan.get(field) == plans[0].get(field)
            for plan in plans[1:]
            for field in ("harness", "model", "revision", "provider", "quantization")
        ),
        "declared_prompts_bound": (
            plans[0].get("prompt") == build_control_plan()["scored_plan"]["prompt"]
            and plans[1].get("prompt") == build_v1_plan()["scored_plan"]["prompt"]
            and plans[2].get("prompt") == build_v2_plan()["scored_plan"]["prompt"]
        ),
        "all_execution_qualified": all(
            summary["readiness"]["execution_qualified"] is True
            for summary in summaries
        ),
        "outer_plans_match_execution_plans": (
            control_outer["scored_plan"]["plan_sha256"]
            == plans[0]["plan_sha256"]
            and v1_outer["scored_plan"]["plan_sha256"] == plans[1]["plan_sha256"]
            and v2_outer["scored_plan"]["plan_sha256"] == plans[2]["plan_sha256"]
        ),
        "cost_accounting_exact": (
            all(summary["cost_accounting"] == "exact" for summary in summaries)
            and all(canary["cost_accounting"] == "exact" for canary in canaries)
        ),
    }
    analysis: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_constraint_v2_analysis/0.1",
        "campaign_id": V2_CAMPAIGN_ID,
        "v1_campaign_id": V1_CAMPAIGN_ID,
        "control_campaign_id": CONTROL_CAMPAIGN_ID,
        "independent_case_count": len(CASE_VARIANCE_PATHS),
        "replicates_per_case_arm": len(PAIRED_INFERENCE_SEEDS),
        "primary_contract_recovery_v2_minus_v1": repair,
        "exploratory_development_v2_minus_control": development,
        "action_contract_diagnostics": {
            "control_malformed_procurement_action_count": control["summary"][
                "violation_counts"
            ].get("malformed_procurement_action", 0),
            "v1_malformed_procurement_action_count": v1["summary"][
                "violation_counts"
            ].get("malformed_procurement_action", 0),
            "v2_malformed_procurement_action_count": v2["summary"][
                "violation_counts"
            ].get("malformed_procurement_action", 0),
        },
        "operational_diagnostics": {
            label: {
                "scored_cost_usd": artifact["summary"]["total_cost_usd"],
                "canary_cost_usd": canary["cost_usd"],
                "median_elapsed_seconds": artifact["summary"][
                    "median_elapsed_seconds"
                ],
                "feasible_count": artifact["summary"]["feasible_count"],
                "violation_counts": artifact["summary"]["violation_counts"],
            }
            for label, artifact, canary in (
                ("control", control, control_canary),
                ("v1", v1, v1_canary),
                ("v2", v2, v2_canary),
            )
        },
        "integrity": integrity,
        "readiness": {"constraint_v2_analysis_qualified": all(integrity.values())},
        "source": {
            "control_summary_file_sha256": control_file_sha,
            "control_artifact_sha256": control["artifact_sha256"],
            "control_outer_plan_sha256": control_outer["plan_sha256"],
            "v1_summary_file_sha256": v1_file_sha,
            "v1_artifact_sha256": v1["artifact_sha256"],
            "v1_outer_plan_sha256": v1_outer["plan_sha256"],
            "v2_summary_file_sha256": v2_file_sha,
            "v2_artifact_sha256": v2["artifact_sha256"],
            "v2_outer_plan_sha256": v2_outer["plan_sha256"],
            "analysis_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "claim_scope": (
            "V2-minus-V1 is an adaptive action-contract recovery diagnostic; "
            "V2-minus-control economic effects are exploratory development evidence "
            "on six curated worlds and require held-out confirmation"
        ),
    }
    analysis["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(analysis)
    ).hexdigest()
    return analysis


def publish_campaign(
    *,
    control_run_root: Path,
    v1_run_root: Path,
    v2_run_root: Path,
    publication_root: Path,
) -> dict[str, Any]:
    analysis = build_v2_analysis(
        control_run_root=control_run_root,
        v1_run_root=v1_run_root,
        v2_run_root=v2_run_root,
    )
    if not analysis["readiness"]["constraint_v2_analysis_qualified"]:
        raise ValueError("constraint V2 analysis is not qualified")
    outer_plan, canary = _verified_outer(
        v2_run_root,
        campaign_id=V2_CAMPAIGN_ID,
        frozen_plan=build_v2_plan(),
        candidate=QWEN235B_GOOGLE_CANDIDATE,
    )
    published = publish_model_qualification(
        run_root=v2_run_root / "scored",
        publication_root=publication_root,
        supplemental_reports={
            "reports/admission_canary.json": canary,
            "reports/campaign_plan.json": outer_plan,
            "reports/constraint_v2_analysis.json": analysis,
        },
    )
    return published["manifest"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-run-root", type=Path, required=True)
    parser.add_argument("--v1-run-root", type=Path, required=True)
    parser.add_argument("--v2-run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.publish:
        if arguments.publication_root is None:
            parser.error("--publish requires --publication-root")
        value = publish_campaign(
            control_run_root=arguments.control_run_root,
            v1_run_root=arguments.v1_run_root,
            v2_run_root=arguments.v2_run_root,
            publication_root=arguments.publication_root,
        )
    else:
        value = build_v2_analysis(
            control_run_root=arguments.control_run_root,
            v1_run_root=arguments.v1_run_root,
            v2_run_root=arguments.v2_run_root,
        )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_v2_analysis", "publish_campaign"]
