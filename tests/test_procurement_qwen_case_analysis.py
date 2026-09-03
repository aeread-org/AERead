from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.model_campaign import (
    CAMPAIGN_ID as GLM_BASELINE_CAMPAIGN_ID,
)
from aeread_families.procurement_allocation.qwen_case_analysis import (
    build_paired_comparison,
    publish_campaign,
)
from aeread_families.procurement_allocation.qwen_case_campaign import (
    CAMPAIGN_ID,
    PAIRED_INFERENCE_SEEDS,
    QWEN_CANDIDATE,
    build_plan,
)


def _row(
    *, path: Path, seed: int, feasible: bool, margin: float
) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    row: dict[str, object] = {
        "case_id": raw["case_id"],
        "case_content_sha256": raw["content_sha256"],
        "inference_seed": seed,
        "status": "completed",
        "decision": "award",
        "termination_reason": "submitted",
        "feasible": feasible,
        "completed_kits": 10 if feasible else 0,
        "contribution_margin_usd": margin,
        "upper_bound_usd": 20.0,
        "regret_to_upper_bound_usd": 20.0 - margin,
        "violations": [] if feasible else ["minimum_service_not_met"],
        "elapsed_environment_days": 4,
        "action_count": 4,
        "action_trace": [{"ordinal": 1, "action": "request_quote"}],
        "elapsed_seconds": 2.0,
        "input_tokens": 100,
        "cached_input_tokens": 0,
        "output_tokens": 20,
        "cost_usd": 0.001,
        "cost_accounting": "exact",
        "resolved_models": [],
        "receipt_sha256": "a" * 64,
        "receipt_replayed": True,
        "replay_level": "provider_response",
        "provider_call_count": 4,
        "runner_retry_count": 0,
        "retry_condition_counts": {},
    }
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
    return row


def _write_summary(
    root: Path, *, plan: dict, feasible: bool, margin: float
) -> None:
    rows = [
        _row(path=path, seed=seed, feasible=feasible, margin=margin)
        for path in CASE_VARIANCE_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    ]
    summary = {
        "planned_trajectory_count": 18,
        "completed_trajectory_count": 18,
        "operational_failure_count": 0,
        "total_cost_usd": 0.018,
        "cost_accounting": "exact",
        "median_elapsed_seconds": 2.0,
        "feasible_count": 18 if feasible else 0,
        "violation_counts": {} if feasible else {"minimum_service_not_met": 18},
        "readiness": {"execution_qualified": True},
    }
    artifact = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": plan,
        "preflight": {},
        "summary": summary,
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    root.mkdir(parents=True)
    (root / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path]:
    outer = build_plan()
    qwen_root = tmp_path / "runs" / CAMPAIGN_ID / "attempt_001"
    qwen_root.mkdir(parents=True)
    (qwen_root / "campaign_plan.json").write_bytes(
        canonical_json_bytes(outer) + b"\n"
    )
    canary = {
        "schema_version": "aeread.provider_admission_canary/0.4",
        "campaign_id": CAMPAIGN_ID,
        "status": "admitted",
        "scored": False,
        "model": QWEN_CANDIDATE.route.model,
        "revision": QWEN_CANDIDATE.route.revision,
        "route_provider": QWEN_CANDIDATE.route.route_provider,
        "resolved_model": QWEN_CANDIDATE.route.revision,
        "cost_usd": 0.0001,
        "cost_accounting": "exact",
    }
    canary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(canary)
    ).hexdigest()
    (qwen_root / "admission_canary.json").write_bytes(
        canonical_json_bytes(canary) + b"\n"
    )
    _write_summary(
        qwen_root / "scored", plan=outer["scored_plan"], feasible=False, margin=8.0
    )

    baseline_plan = {
        "campaign_id": GLM_BASELINE_CAMPAIGN_ID,
        "inference_seeds": list(PAIRED_INFERENCE_SEEDS),
        "harness": outer["scored_plan"]["harness"],
    }
    baseline_plan["plan_sha256"] = hashlib.sha256(
        canonical_json_bytes(baseline_plan)
    ).hexdigest()
    baseline_root = tmp_path / "runs" / GLM_BASELINE_CAMPAIGN_ID / "attempt_001"
    _write_summary(baseline_root, plan=baseline_plan, feasible=True, margin=10.0)
    return baseline_root, qwen_root


def test_qwen_paired_comparison_uses_six_case_clusters(tmp_path: Path) -> None:
    baseline_root, qwen_root = _fixture_roots(tmp_path)

    result = build_paired_comparison(
        baseline_run_root=baseline_root, qwen_run_root=qwen_root
    )

    assert result["readiness"]["paired_model_comparison_qualified"] is True
    assert result["completed_pair_count"] == 18
    assert result["feasibility_transition_counts"] == {"pass_fail": 18}
    assert result["aggregate_effects_qwen_minus_glm"]["feasible"] == {
        "case_cluster_mean": -1.0,
        "case_cluster_bootstrap_95_interval": [-1.0, -1.0],
    }
    assert result["aggregate_effects_qwen_minus_glm"][
        "contribution_margin_usd"
    ]["case_cluster_mean"] == -2.0
    assert result["independent_case_count"] == 6
    assert all(result["integrity"].values())


def test_qwen_publisher_writes_digest_bound_sanitized_bundle(tmp_path: Path) -> None:
    baseline_root, qwen_root = _fixture_roots(tmp_path)
    publication_root = tmp_path / "evidence" / CAMPAIGN_ID

    manifest = publish_campaign(
        baseline_run_root=baseline_root,
        qwen_run_root=qwen_root,
        publication_root=publication_root,
    )

    assert manifest["publication_id"] == CAMPAIGN_ID
    assert (publication_root / "reports" / "qualification.json").is_file()
    assert (publication_root / "reports" / "admission_canary.json").is_file()
    assert (publication_root / "reports" / "campaign_plan.json").is_file()
    comparison_path = publication_root / "reports" / "paired_model_comparison.json"
    assert comparison_path.is_file()
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert comparison["readiness"]["paired_model_comparison_qualified"] is True
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication_root / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(path.read_text() for path in publication_root.rglob("*.json"))
    assert "raw_response" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
