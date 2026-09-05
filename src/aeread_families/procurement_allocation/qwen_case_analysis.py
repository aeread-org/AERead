"""Digest-bound Qwen versus GLM procurement case-panel analysis."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .case_matrix import CASE_VARIANCE_PATHS, REPOSITORY_ROOT
from .model_campaign import (
    CAMPAIGN_ID as GLM_BASELINE_CAMPAIGN_ID,
    publish_model_qualification,
)
from .qwen_case_campaign import (
    CAMPAIGN_ID,
    PAIRED_INFERENCE_SEEDS,
    QWEN_CANDIDATE,
    build_plan,
)


EXECUTION_COMMIT = "11434b27c26e2c449bb6b92c3798d0e096fe7787"
EXECUTION_MODULE_SHA256 = (
    "7364349de52069caeba2dfcc045e81a01e940607cc21a39f81bf586b1f6873af"
)
ADAPTER_MODULE_SHA256 = (
    "a9df085ebfd2c870a0c3ce58ff36b2468327a96ccf78beb8dc9b255961715600"
)
DEFAULT_BASELINE_RUN_ROOT = (
    REPOSITORY_ROOT
    / "runs"
    / "procurement_allocation"
    / GLM_BASELINE_CAMPAIGN_ID
    / "qualification_attempt_001"
)
METRICS = (
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "regret_to_upper_bound_usd",
)


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _verified_summary(root: Path, *, campaign_id: str) -> tuple[dict[str, Any], str]:
    path = root / "summary.json"
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


def _verified_outer_artifacts(run_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan_path = run_root / "campaign_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if canonical_json_bytes(plan) != canonical_json_bytes(build_plan()):
        raise ValueError("recorded Qwen campaign plan differs from the frozen plan")
    canary_path = run_root / "admission_canary.json"
    canary = json.loads(canary_path.read_text(encoding="utf-8"))
    recorded = canary.get("artifact_sha256")
    payload = {key: item for key, item in canary.items() if key != "artifact_sha256"}
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("admission canary digest mismatch")
    if (
        canary.get("campaign_id") != CAMPAIGN_ID
        or canary.get("status") != "admitted"
        or canary.get("scored") is not False
        or canary.get("model") != QWEN_CANDIDATE.route.model
        or canary.get("revision") != QWEN_CANDIDATE.route.revision
        or canary.get("route_provider") != QWEN_CANDIDATE.route.route_provider
        or canary.get("resolved_model") != QWEN_CANDIDATE.route.revision
        or canary.get("cost_accounting") != "exact"
    ):
        raise ValueError("admission canary identity or state mismatch")
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


def build_paired_comparison(
    *, baseline_run_root: Path, qwen_run_root: Path
) -> dict[str, Any]:
    baseline, baseline_file_sha = _verified_summary(
        baseline_run_root, campaign_id=GLM_BASELINE_CAMPAIGN_ID
    )
    qwen, qwen_file_sha = _verified_summary(
        qwen_run_root / "scored", campaign_id=CAMPAIGN_ID
    )
    outer_plan, canary = _verified_outer_artifacts(qwen_run_root)
    baseline_rows = _row_index(baseline)
    qwen_rows = _row_index(qwen)
    expected_keys = {
        (f"procurement_allocation_v1.dev.{path.stem}", seed)
        for path in CASE_VARIANCE_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    }
    all_keys = sorted(set(baseline_rows) | set(qwen_rows))
    transitions: Counter[str] = Counter()
    pairs: list[dict[str, Any]] = []
    per_case_pairs: dict[str, list[dict[str, Any]]] = {}
    completed_pair_count = 0
    content_match = True
    bounds_match = True
    for key in all_keys:
        case_id, seed = key
        left = baseline_rows.get(key)
        right = qwen_rows.get(key)
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
                transition = (
                    f"{'pass' if left.get('feasible') else 'fail'}_"
                    f"{'pass' if right.get('feasible') else 'fail'}"
                )
                transitions[transition] += 1
                pair["feasibility_transition"] = transition
                pair["glm"] = {metric: _metric(left, metric) for metric in METRICS}
                pair["qwen"] = {metric: _metric(right, metric) for metric in METRICS}
                pair["effects_qwen_minus_glm"] = {
                    metric: pair["qwen"][metric] - pair["glm"][metric]
                    for metric in METRICS
                }
        pairs.append(pair)
        per_case_pairs.setdefault(case_id, []).append(pair)

    per_case: dict[str, Any] = {}
    for case_id, case_pairs in sorted(per_case_pairs.items()):
        completed = [pair for pair in case_pairs if "effects_qwen_minus_glm" in pair]
        per_case[case_id] = {
            "pair_count": len(case_pairs),
            "completed_pair_count": len(completed),
            "mean_effects_qwen_minus_glm": {
                metric: statistics.fmean(
                    pair["effects_qwen_minus_glm"][metric] for pair in completed
                )
                if completed
                else None
                for metric in METRICS
            },
        }

    aggregate: dict[str, Any] = {}
    for metric in METRICS:
        case_effects = [
            float(per_case[case_id]["mean_effects_qwen_minus_glm"][metric])
            for case_id in sorted(per_case)
        ]
        aggregate[metric] = {
            "case_cluster_mean": statistics.fmean(case_effects),
            "case_cluster_bootstrap_95_interval": _cluster_interval(case_effects),
        }

    baseline_plan = baseline["plan"]
    qwen_plan = qwen["plan"]
    expected_count = len(expected_keys)
    integrity = {
        "case_and_seed_identities_match": (
            set(baseline_rows) == set(qwen_rows) == expected_keys
        ),
        "case_content_digests_match": content_match,
        "inference_seeds_match": (
            baseline_plan.get("inference_seeds")
            == qwen_plan.get("inference_seeds")
            == list(PAIRED_INFERENCE_SEEDS)
        ),
        "harness_match": baseline_plan.get("harness") == qwen_plan.get("harness"),
        "both_execution_qualified": (
            baseline["summary"]["readiness"]["execution_qualified"] is True
            and qwen["summary"]["readiness"]["execution_qualified"] is True
        ),
        "all_pairs_completed_and_replayed": completed_pair_count == expected_count,
        "upper_bounds_match": bounds_match,
        "qwen_route_matches_frozen_candidate": (
            qwen_plan.get("model") == QWEN_CANDIDATE.route.model
            and qwen_plan.get("revision") == QWEN_CANDIDATE.route.revision
            and qwen_plan.get("provider") == QWEN_CANDIDATE.route.route_provider
            and qwen_plan.get("quantization") == QWEN_CANDIDATE.route.quantization
        ),
        "qwen_outer_plan_matches_execution_plan": (
            outer_plan["scored_plan"]["plan_sha256"] == qwen_plan["plan_sha256"]
        ),
        "qwen_cost_accounting_exact": (
            qwen["summary"]["cost_accounting"] == "exact"
            and canary["cost_accounting"] == "exact"
        ),
    }
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_model_comparison/0.2",
        "campaign_id": CAMPAIGN_ID,
        "baseline_campaign_id": GLM_BASELINE_CAMPAIGN_ID,
        "independent_case_count": len(CASE_VARIANCE_PATHS),
        "replicates_per_case_model": len(PAIRED_INFERENCE_SEEDS),
        "completed_pair_count": completed_pair_count,
        "feasibility_transition_counts": dict(sorted(transitions.items())),
        "aggregate_effects_qwen_minus_glm": aggregate,
        "per_case": per_case,
        "pairs": pairs,
        "operational_diagnostics": {
            "glm": {
                "scored_cost_usd": baseline["summary"]["total_cost_usd"],
                "median_elapsed_seconds": baseline["summary"]["median_elapsed_seconds"],
                "feasible_count": baseline["summary"]["feasible_count"],
            },
            "qwen": {
                "scored_cost_usd": qwen["summary"]["total_cost_usd"],
                "canary_cost_usd": canary["cost_usd"],
                "total_cost_usd": qwen["summary"]["total_cost_usd"]
                + canary["cost_usd"],
                "median_elapsed_seconds": qwen["summary"]["median_elapsed_seconds"],
                "feasible_count": qwen["summary"]["feasible_count"],
                "malformed_json_count": qwen["summary"]["violation_counts"].get(
                    "malformed_json", 0
                ),
            },
        },
        "integrity": integrity,
        "readiness": {"paired_model_comparison_qualified": all(integrity.values())},
        "source": {
            "execution_commit": EXECUTION_COMMIT,
            "execution_module_sha256": EXECUTION_MODULE_SHA256,
            "adapter_module_sha256": ADAPTER_MODULE_SHA256,
            "baseline_summary_file_sha256": baseline_file_sha,
            "baseline_artifact_sha256": baseline["artifact_sha256"],
            "baseline_plan_sha256": baseline_plan["plan_sha256"],
            "qwen_summary_file_sha256": qwen_file_sha,
            "qwen_artifact_sha256": qwen["artifact_sha256"],
            "qwen_plan_sha256": qwen_plan["plan_sha256"],
            "qwen_outer_plan_sha256": outer_plan["plan_sha256"],
            "qwen_canary_artifact_sha256": canary["artifact_sha256"],
            "analysis_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "claim_scope": (
            "paired Qwen versus GLM diagnostic on six curated procurement worlds; "
            "world-cluster intervals describe this panel and are not population-level "
            "confidence intervals or a general model ranking"
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def publish_campaign(
    *, baseline_run_root: Path, qwen_run_root: Path, publication_root: Path
) -> dict[str, Any]:
    comparison = build_paired_comparison(
        baseline_run_root=baseline_run_root, qwen_run_root=qwen_run_root
    )
    if not comparison["readiness"]["paired_model_comparison_qualified"]:
        raise ValueError("paired Qwen comparison is not qualified")
    outer_plan, canary = _verified_outer_artifacts(qwen_run_root)
    published = publish_model_qualification(
        run_root=qwen_run_root / "scored",
        publication_root=publication_root,
        supplemental_reports={
            "reports/admission_canary.json": canary,
            "reports/campaign_plan.json": outer_plan,
            "reports/paired_model_comparison.json": comparison,
        },
    )
    return published["manifest"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-run-root", type=Path, default=DEFAULT_BASELINE_RUN_ROOT)
    parser.add_argument("--qwen-run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.publish:
        if arguments.publication_root is None:
            parser.error("--publish requires --publication-root")
        value = publish_campaign(
            baseline_run_root=arguments.baseline_run_root,
            qwen_run_root=arguments.qwen_run_root,
            publication_root=arguments.publication_root,
        )
    else:
        value = build_paired_comparison(
            baseline_run_root=arguments.baseline_run_root,
            qwen_run_root=arguments.qwen_run_root,
        )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_paired_comparison", "publish_campaign"]
