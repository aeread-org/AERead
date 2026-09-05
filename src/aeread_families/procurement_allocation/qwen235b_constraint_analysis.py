"""Digest-bound Qwen3 235B constraint-treatment comparison and publication."""

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
    CAMPAIGN_ID as TREATMENT_CAMPAIGN_ID,
    PROMPT_ID as TREATMENT_PROMPT_ID,
    SPEC as TREATMENT_SPEC,
    TREATMENT_ID,
    build_plan as build_treatment_plan,
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


def build_paired_treatment_comparison(
    *, control_run_root: Path, treatment_run_root: Path
) -> dict[str, Any]:
    control, control_file_sha = _verified_summary(
        control_run_root, campaign_id=CONTROL_CAMPAIGN_ID
    )
    treatment, treatment_file_sha = _verified_summary(
        treatment_run_root, campaign_id=TREATMENT_CAMPAIGN_ID
    )
    control_outer, control_canary = _verified_outer(
        control_run_root,
        campaign_id=CONTROL_CAMPAIGN_ID,
        frozen_plan=build_control_plan(),
        candidate=QWEN235B_GOOGLE_CANDIDATE,
    )
    treatment_outer, treatment_canary = _verified_outer(
        treatment_run_root,
        campaign_id=TREATMENT_CAMPAIGN_ID,
        frozen_plan=build_treatment_plan(),
        candidate=QWEN235B_GOOGLE_CANDIDATE,
    )
    control_rows = _row_index(control)
    treatment_rows = _row_index(treatment)
    expected_keys = {
        (f"procurement_allocation_v1.dev.{path.stem}", seed)
        for path in CASE_VARIANCE_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    }
    all_keys = sorted(set(control_rows) | set(treatment_rows))
    feasibility_transitions: Counter[str] = Counter()
    first_action_transitions: Counter[str] = Counter()
    termination_transitions: Counter[str] = Counter()
    pairs: list[dict[str, Any]] = []
    per_case_pairs: dict[str, list[dict[str, Any]]] = {}
    completed_pair_count = 0
    content_match = True
    bounds_match = True
    for case_id, seed in all_keys:
        left = control_rows.get((case_id, seed))
        right = treatment_rows.get((case_id, seed))
        pair: dict[str, Any] = {"case_id": case_id, "inference_seed": seed}
        if left is not None and right is not None:
            content_match = content_match and (
                left.get("case_content_sha256") == right.get("case_content_sha256")
            )
            completed = (
                left.get("status") == right.get("status") == "completed"
                and left.get("receipt_replayed") is True
                and right.get("receipt_replayed") is True
            )
            if completed:
                completed_pair_count += 1
                bounds_match = bounds_match and (
                    float(left["upper_bound_usd"]) == float(right["upper_bound_usd"])
                )
                feasibility_transition = (
                    f"{'pass' if left.get('feasible') else 'fail'}_to_"
                    f"{'pass' if right.get('feasible') else 'fail'}"
                )
                first_action_transition = (
                    f"{_first_action(left)}_to_{_first_action(right)}"
                )
                termination_transition = (
                    f"{left.get('termination_reason')}_to_"
                    f"{right.get('termination_reason')}"
                )
                feasibility_transitions[feasibility_transition] += 1
                first_action_transitions[first_action_transition] += 1
                termination_transitions[termination_transition] += 1
                pair["feasibility_transition"] = feasibility_transition
                pair["first_action_transition"] = first_action_transition
                pair["termination_transition"] = termination_transition
                pair["control"] = {
                    metric: _metric(left, metric) for metric in METRICS
                }
                pair["treatment"] = {
                    metric: _metric(right, metric) for metric in METRICS
                }
                pair["effects_treatment_minus_control"] = {
                    metric: pair["treatment"][metric] - pair["control"][metric]
                    for metric in METRICS
                }
        pairs.append(pair)
        per_case_pairs.setdefault(case_id, []).append(pair)

    per_case: dict[str, Any] = {}
    for case_id, case_pairs in sorted(per_case_pairs.items()):
        completed = [
            pair for pair in case_pairs if "effects_treatment_minus_control" in pair
        ]
        per_case[case_id] = {
            "pair_count": len(case_pairs),
            "completed_pair_count": len(completed),
            "mean_effects_treatment_minus_control": {
                metric: statistics.fmean(
                    pair["effects_treatment_minus_control"][metric]
                    for pair in completed
                )
                if completed
                else None
                for metric in METRICS
            },
        }

    aggregate: dict[str, Any] = {}
    for metric in METRICS:
        case_effects = [
            float(per_case[case_id]["mean_effects_treatment_minus_control"][metric])
            for case_id in sorted(per_case)
        ]
        aggregate[metric] = {
            "case_cluster_mean": statistics.fmean(case_effects),
            "case_cluster_bootstrap_95_interval": _cluster_interval(case_effects),
        }

    control_plan = control["plan"]
    treatment_plan = treatment["plan"]
    expected_count = len(expected_keys)
    integrity = {
        "case_and_seed_identities_match": (
            set(control_rows) == set(treatment_rows) == expected_keys
        ),
        "case_content_digests_match": content_match,
        "inference_seeds_match": (
            control_plan.get("inference_seeds")
            == treatment_plan.get("inference_seeds")
            == list(PAIRED_INFERENCE_SEEDS)
        ),
        "harness_match": control_plan.get("harness") == treatment_plan.get("harness"),
        "same_checkpoint_route_and_quantization": all(
            control_plan.get(field) == treatment_plan.get(field)
            for field in ("model", "revision", "provider", "quantization")
        ),
        "declared_prompt_contrast_bound": (
            control_plan.get("prompt") == build_control_plan()["scored_plan"]["prompt"]
            and treatment_plan.get("prompt")
            == {
                "prompt_id": TREATMENT_PROMPT_ID,
                "sha256": hashlib.sha256(TREATMENT_SPEC.prompt.encode()).hexdigest(),
                "treatment_id": TREATMENT_ID,
            }
        ),
        "both_execution_qualified": (
            control["summary"]["readiness"]["execution_qualified"] is True
            and treatment["summary"]["readiness"]["execution_qualified"] is True
        ),
        "all_pairs_completed_and_replayed": completed_pair_count == expected_count,
        "upper_bounds_match": bounds_match,
        "outer_plans_match_execution_plans": (
            control_outer["scored_plan"]["plan_sha256"]
            == control_plan["plan_sha256"]
            and treatment_outer["scored_plan"]["plan_sha256"]
            == treatment_plan["plan_sha256"]
        ),
        "cost_accounting_exact": (
            control["summary"]["cost_accounting"] == "exact"
            and treatment["summary"]["cost_accounting"] == "exact"
            and control_canary["cost_accounting"] == "exact"
            and treatment_canary["cost_accounting"] == "exact"
        ),
    }
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_prompt_treatment_comparison/0.1",
        "campaign_id": TREATMENT_CAMPAIGN_ID,
        "control_campaign_id": CONTROL_CAMPAIGN_ID,
        "independent_case_count": len(CASE_VARIANCE_PATHS),
        "replicates_per_case_arm": len(PAIRED_INFERENCE_SEEDS),
        "completed_pair_count": completed_pair_count,
        "feasibility_transition_counts": dict(sorted(feasibility_transitions.items())),
        "first_action_transition_counts": dict(sorted(first_action_transitions.items())),
        "termination_transition_counts": dict(sorted(termination_transitions.items())),
        "aggregate_effects_treatment_minus_control": aggregate,
        "per_case": per_case,
        "pairs": pairs,
        "operational_diagnostics": {
            "control": {
                "scored_cost_usd": control["summary"]["total_cost_usd"],
                "canary_cost_usd": control_canary["cost_usd"],
                "median_elapsed_seconds": control["summary"]["median_elapsed_seconds"],
                "feasible_count": control["summary"]["feasible_count"],
                "violation_counts": control["summary"]["violation_counts"],
            },
            "treatment": {
                "scored_cost_usd": treatment["summary"]["total_cost_usd"],
                "canary_cost_usd": treatment_canary["cost_usd"],
                "median_elapsed_seconds": treatment["summary"]["median_elapsed_seconds"],
                "feasible_count": treatment["summary"]["feasible_count"],
                "violation_counts": treatment["summary"]["violation_counts"],
            },
        },
        "integrity": integrity,
        "readiness": {
            "paired_prompt_treatment_comparison_qualified": all(integrity.values())
        },
        "source": {
            "control_summary_file_sha256": control_file_sha,
            "control_artifact_sha256": control["artifact_sha256"],
            "control_plan_sha256": control_plan["plan_sha256"],
            "control_outer_plan_sha256": control_outer["plan_sha256"],
            "control_canary_artifact_sha256": control_canary["artifact_sha256"],
            "treatment_summary_file_sha256": treatment_file_sha,
            "treatment_artifact_sha256": treatment["artifact_sha256"],
            "treatment_plan_sha256": treatment_plan["plan_sha256"],
            "treatment_outer_plan_sha256": treatment_outer["plan_sha256"],
            "treatment_canary_artifact_sha256": treatment_canary["artifact_sha256"],
            "analysis_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "claim_scope": (
            "adaptive paired prompt-treatment diagnostic for one checkpoint and route "
            "on six curated procurement worlds; intervals describe this panel and are "
            "not population-level mechanism effects"
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def publish_campaign(
    *, control_run_root: Path, treatment_run_root: Path, publication_root: Path
) -> dict[str, Any]:
    comparison = build_paired_treatment_comparison(
        control_run_root=control_run_root, treatment_run_root=treatment_run_root
    )
    if not comparison["readiness"]["paired_prompt_treatment_comparison_qualified"]:
        raise ValueError("paired prompt-treatment comparison is not qualified")
    outer_plan, canary = _verified_outer(
        treatment_run_root,
        campaign_id=TREATMENT_CAMPAIGN_ID,
        frozen_plan=build_treatment_plan(),
        candidate=QWEN235B_GOOGLE_CANDIDATE,
    )
    published = publish_model_qualification(
        run_root=treatment_run_root / "scored",
        publication_root=publication_root,
        supplemental_reports={
            "reports/admission_canary.json": canary,
            "reports/campaign_plan.json": outer_plan,
            "reports/paired_prompt_treatment_comparison.json": comparison,
        },
    )
    return published["manifest"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-run-root", type=Path, required=True)
    parser.add_argument("--treatment-run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.publish:
        if arguments.publication_root is None:
            parser.error("--publish requires --publication-root")
        value = publish_campaign(
            control_run_root=arguments.control_run_root,
            treatment_run_root=arguments.treatment_run_root,
            publication_root=arguments.publication_root,
        )
    else:
        value = build_paired_treatment_comparison(
            control_run_root=arguments.control_run_root,
            treatment_run_root=arguments.treatment_run_root,
        )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_paired_treatment_comparison", "publish_campaign"]
