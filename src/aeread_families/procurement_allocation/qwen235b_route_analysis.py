"""Digest-bound Qwen3 235B provider-route comparison and publication."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .case_matrix import CASE_VARIANCE_PATHS
from .model_campaign import publish_model_qualification
from .qwen_case_campaign import PAIRED_INFERENCE_SEEDS
from .qwen235b_case_campaign import (
    CAMPAIGN_ID as ATLAS_CAMPAIGN_ID,
    QWEN235B_CANDIDATE as ATLAS_CANDIDATE,
    build_plan as build_atlas_plan,
)
from .qwen235b_google_case_campaign import (
    CAMPAIGN_ID as GOOGLE_CAMPAIGN_ID,
    QWEN235B_GOOGLE_CANDIDATE as GOOGLE_CANDIDATE,
    build_plan as build_google_plan,
)


METRICS = (
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "regret_to_upper_bound_usd",
)


def _verified_summary(
    root: Path, *, campaign_id: str
) -> tuple[dict[str, Any], str]:
    path = root / "scored" / "summary.json"
    raw_bytes = path.read_bytes()
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise ValueError(f"qualification summary must be an object: {path}")
    recorded = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"qualification artifact digest mismatch: {path}")
    plan = value.get("plan")
    if not isinstance(plan, Mapping) or plan.get("campaign_id") != campaign_id:
        raise ValueError(f"qualification campaign identity mismatch: {path}")
    plan_recorded = plan.get("plan_sha256")
    plan_payload = {key: item for key, item in plan.items() if key != "plan_sha256"}
    if plan_recorded != hashlib.sha256(canonical_json_bytes(plan_payload)).hexdigest():
        raise ValueError(f"qualification plan digest mismatch: {path}")
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError("qualification rows must be an array")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("qualification row must be an object")
        row_recorded = row.get("result_sha256")
        row_payload = {key: item for key, item in row.items() if key != "result_sha256"}
        if row_recorded != hashlib.sha256(canonical_json_bytes(row_payload)).hexdigest():
            raise ValueError("qualification row digest mismatch")
    return value, hashlib.sha256(raw_bytes).hexdigest()


def _verified_outer(
    run_root: Path,
    *,
    campaign_id: str,
    frozen_plan: Mapping[str, Any],
    candidate: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = json.loads((run_root / "campaign_plan.json").read_text(encoding="utf-8"))
    if canonical_json_bytes(plan) != canonical_json_bytes(frozen_plan):
        raise ValueError(f"recorded outer plan differs from frozen plan: {campaign_id}")
    canary = json.loads(
        (run_root / "admission_canary.json").read_text(encoding="utf-8")
    )
    recorded = canary.get("artifact_sha256")
    payload = {key: item for key, item in canary.items() if key != "artifact_sha256"}
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"admission canary digest mismatch: {campaign_id}")
    if (
        canary.get("campaign_id") != campaign_id
        or canary.get("status") != "admitted"
        or canary.get("scored") is not False
        or canary.get("model") != candidate.route.model
        or canary.get("revision") != candidate.route.revision
        or canary.get("route_provider") != candidate.route.route_provider
        or canary.get("resolved_model") != candidate.route.revision
        or canary.get("cost_accounting") != "exact"
    ):
        raise ValueError(f"admission canary identity or state mismatch: {campaign_id}")
    return plan, canary


def _row_index(value: Mapping[str, Any]) -> dict[tuple[str, int], Mapping[str, Any]]:
    indexed: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in value["rows"]:
        key = (str(row["case_id"]), int(row["inference_seed"]))
        if key in indexed:
            raise ValueError(f"duplicate row identity: {key}")
        indexed[key] = row
    return indexed


def _metric(row: Mapping[str, Any], name: str) -> float:
    if name == "feasible":
        return 1.0 if row.get("feasible") is True else 0.0
    return float(row[name])


def _cluster_interval(case_effects: Sequence[float]) -> list[float]:
    if len(case_effects) != 6:
        raise ValueError("paired interval requires exactly six case clusters")
    means = sorted(
        statistics.fmean(case_effects[index] for index in sample)
        for sample in itertools.product(range(6), repeat=6)
    )
    return [
        means[int(0.025 * (len(means) - 1))],
        means[int(0.975 * (len(means) - 1))],
    ]


def _first_action(row: Mapping[str, Any]) -> str:
    trace = row.get("action_trace")
    if not isinstance(trace, list) or not trace or not isinstance(trace[0], Mapping):
        return "<missing>"
    action = trace[0].get("action")
    return action if isinstance(action, str) else "<missing>"


def build_paired_route_comparison(
    *, atlas_run_root: Path, google_run_root: Path
) -> dict[str, Any]:
    atlas, atlas_file_sha = _verified_summary(
        atlas_run_root, campaign_id=ATLAS_CAMPAIGN_ID
    )
    google, google_file_sha = _verified_summary(
        google_run_root, campaign_id=GOOGLE_CAMPAIGN_ID
    )
    atlas_outer, atlas_canary = _verified_outer(
        atlas_run_root,
        campaign_id=ATLAS_CAMPAIGN_ID,
        frozen_plan=build_atlas_plan(),
        candidate=ATLAS_CANDIDATE,
    )
    google_outer, google_canary = _verified_outer(
        google_run_root,
        campaign_id=GOOGLE_CAMPAIGN_ID,
        frozen_plan=build_google_plan(),
        candidate=GOOGLE_CANDIDATE,
    )
    atlas_rows = _row_index(atlas)
    google_rows = _row_index(google)
    expected_keys = {
        (f"procurement_allocation_v1.dev.{path.stem}", seed)
        for path in CASE_VARIANCE_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    }
    all_keys = sorted(set(atlas_rows) | set(google_rows))
    feasibility_transitions: Counter[str] = Counter()
    first_action_transitions: Counter[str] = Counter()
    termination_transitions: Counter[str] = Counter()
    pairs: list[dict[str, Any]] = []
    per_case_pairs: dict[str, list[dict[str, Any]]] = {}
    completed_pair_count = 0
    content_match = True
    bounds_match = True
    for case_id, seed in all_keys:
        left = atlas_rows.get((case_id, seed))
        right = google_rows.get((case_id, seed))
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
                pair["atlas"] = {metric: _metric(left, metric) for metric in METRICS}
                pair["google"] = {
                    metric: _metric(right, metric) for metric in METRICS
                }
                pair["effects_google_minus_atlas"] = {
                    metric: pair["google"][metric] - pair["atlas"][metric]
                    for metric in METRICS
                }
        pairs.append(pair)
        per_case_pairs.setdefault(case_id, []).append(pair)

    per_case: dict[str, Any] = {}
    for case_id, case_pairs in sorted(per_case_pairs.items()):
        completed = [
            pair for pair in case_pairs if "effects_google_minus_atlas" in pair
        ]
        per_case[case_id] = {
            "pair_count": len(case_pairs),
            "completed_pair_count": len(completed),
            "mean_effects_google_minus_atlas": {
                metric: statistics.fmean(
                    pair["effects_google_minus_atlas"][metric] for pair in completed
                )
                if completed
                else None
                for metric in METRICS
            },
        }

    aggregate: dict[str, Any] = {}
    for metric in METRICS:
        case_effects = [
            float(per_case[case_id]["mean_effects_google_minus_atlas"][metric])
            for case_id in sorted(per_case)
        ]
        aggregate[metric] = {
            "case_cluster_mean": statistics.fmean(case_effects),
            "case_cluster_bootstrap_95_interval": _cluster_interval(case_effects),
        }

    atlas_plan = atlas["plan"]
    google_plan = google["plan"]
    expected_count = len(expected_keys)
    integrity = {
        "case_and_seed_identities_match": (
            set(atlas_rows) == set(google_rows) == expected_keys
        ),
        "case_content_digests_match": content_match,
        "inference_seeds_match": (
            atlas_plan.get("inference_seeds")
            == google_plan.get("inference_seeds")
            == list(PAIRED_INFERENCE_SEEDS)
        ),
        "prompt_and_harness_match": (
            atlas_plan.get("prompt") == google_plan.get("prompt")
            and atlas_plan.get("harness") == google_plan.get("harness")
        ),
        "both_execution_qualified": (
            atlas["summary"]["readiness"]["execution_qualified"] is True
            and google["summary"]["readiness"]["execution_qualified"] is True
        ),
        "all_pairs_completed_and_replayed": completed_pair_count == expected_count,
        "upper_bounds_match": bounds_match,
        "same_checkpoint_and_revision": (
            atlas_plan.get("model") == google_plan.get("model")
            and atlas_plan.get("revision") == google_plan.get("revision")
        ),
        "declared_routes_match": (
            atlas_plan.get("provider") == ATLAS_CANDIDATE.route.route_provider
            and atlas_plan.get("quantization") == ATLAS_CANDIDATE.route.quantization
            and google_plan.get("provider") == GOOGLE_CANDIDATE.route.route_provider
            and google_plan.get("quantization") == GOOGLE_CANDIDATE.route.quantization
        ),
        "outer_plans_match_execution_plans": (
            atlas_outer["scored_plan"]["plan_sha256"] == atlas_plan["plan_sha256"]
            and google_outer["scored_plan"]["plan_sha256"]
            == google_plan["plan_sha256"]
        ),
        "cost_accounting_exact": (
            atlas["summary"]["cost_accounting"] == "exact"
            and google["summary"]["cost_accounting"] == "exact"
            and atlas_canary["cost_accounting"] == "exact"
            and google_canary["cost_accounting"] == "exact"
        ),
    }
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_provider_route_comparison/0.1",
        "campaign_id": GOOGLE_CAMPAIGN_ID,
        "baseline_campaign_id": ATLAS_CAMPAIGN_ID,
        "independent_case_count": len(CASE_VARIANCE_PATHS),
        "replicates_per_case_route": len(PAIRED_INFERENCE_SEEDS),
        "completed_pair_count": completed_pair_count,
        "feasibility_transition_counts": dict(sorted(feasibility_transitions.items())),
        "first_action_transition_counts": dict(sorted(first_action_transitions.items())),
        "termination_transition_counts": dict(sorted(termination_transitions.items())),
        "aggregate_effects_google_minus_atlas": aggregate,
        "per_case": per_case,
        "pairs": pairs,
        "operational_diagnostics": {
            "atlas": {
                "scored_cost_usd": atlas["summary"]["total_cost_usd"],
                "canary_cost_usd": atlas_canary["cost_usd"],
                "median_elapsed_seconds": atlas["summary"]["median_elapsed_seconds"],
                "feasible_count": atlas["summary"]["feasible_count"],
            },
            "google": {
                "scored_cost_usd": google["summary"]["total_cost_usd"],
                "canary_cost_usd": google_canary["cost_usd"],
                "median_elapsed_seconds": google["summary"]["median_elapsed_seconds"],
                "feasible_count": google["summary"]["feasible_count"],
            },
        },
        "integrity": integrity,
        "readiness": {
            "paired_provider_route_comparison_qualified": all(integrity.values())
        },
        "source": {
            "atlas_summary_file_sha256": atlas_file_sha,
            "atlas_artifact_sha256": atlas["artifact_sha256"],
            "atlas_plan_sha256": atlas_plan["plan_sha256"],
            "atlas_outer_plan_sha256": atlas_outer["plan_sha256"],
            "atlas_canary_artifact_sha256": atlas_canary["artifact_sha256"],
            "google_summary_file_sha256": google_file_sha,
            "google_artifact_sha256": google["artifact_sha256"],
            "google_plan_sha256": google_plan["plan_sha256"],
            "google_outer_plan_sha256": google_outer["plan_sha256"],
            "google_canary_artifact_sha256": google_canary["artifact_sha256"],
            "analysis_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "claim_scope": (
            "paired provider-route diagnostic for one checkpoint on six curated "
            "procurement worlds; route includes provider implementation and declared "
            "quantization, so effects are not a general provider or model ranking"
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def publish_campaign(
    *, atlas_run_root: Path, google_run_root: Path, publication_root: Path
) -> dict[str, Any]:
    comparison = build_paired_route_comparison(
        atlas_run_root=atlas_run_root, google_run_root=google_run_root
    )
    if not comparison["readiness"]["paired_provider_route_comparison_qualified"]:
        raise ValueError("paired provider-route comparison is not qualified")
    outer_plan, canary = _verified_outer(
        google_run_root,
        campaign_id=GOOGLE_CAMPAIGN_ID,
        frozen_plan=build_google_plan(),
        candidate=GOOGLE_CANDIDATE,
    )
    published = publish_model_qualification(
        run_root=google_run_root / "scored",
        publication_root=publication_root,
        supplemental_reports={
            "reports/admission_canary.json": canary,
            "reports/campaign_plan.json": outer_plan,
            "reports/paired_provider_route_comparison.json": comparison,
        },
    )
    return published["manifest"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas-run-root", type=Path, required=True)
    parser.add_argument("--google-run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.publish:
        if arguments.publication_root is None:
            parser.error("--publish requires --publication-root")
        value = publish_campaign(
            atlas_run_root=arguments.atlas_run_root,
            google_run_root=arguments.google_run_root,
            publication_root=arguments.publication_root,
        )
    else:
        value = build_paired_route_comparison(
            atlas_run_root=arguments.atlas_run_root,
            google_run_root=arguments.google_run_root,
        )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_paired_route_comparison", "publish_campaign"]
