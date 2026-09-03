from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.qwen_case_campaign import (
    PAIRED_INFERENCE_SEEDS,
)
from aeread_families.procurement_allocation.qwen235b_constraint_analysis import (
    build_paired_treatment_comparison,
    publish_campaign,
)
from aeread_families.procurement_allocation.qwen235b_constraint_campaign import (
    CAMPAIGN_ID as TREATMENT_CAMPAIGN_ID,
    build_plan as build_treatment_plan,
)
from aeread_families.procurement_allocation.qwen235b_google_case_campaign import (
    CAMPAIGN_ID as CONTROL_CAMPAIGN_ID,
    QWEN235B_GOOGLE_CANDIDATE,
    build_plan as build_control_plan,
)


def _row(
    *, path: Path, seed: int, feasible: bool, margin: float, action: str
) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    row: dict[str, object] = {
        "case_id": raw["case_id"],
        "case_content_sha256": raw["content_sha256"],
        "inference_seed": seed,
        "status": "completed",
        "decision": "award" if feasible else "failed",
        "termination_reason": "submitted" if feasible else "invalid_action",
        "feasible": feasible,
        "completed_kits": 10 if feasible else 0,
        "contribution_margin_usd": margin,
        "upper_bound_usd": 20.0,
        "regret_to_upper_bound_usd": 20.0 - margin,
        "violations": [] if feasible else ["malformed_procurement_action"],
        "elapsed_environment_days": 1,
        "action_count": 1,
        "action_trace": [{"ordinal": 1, "action": action}],
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
        "provider_call_count": 1,
        "runner_retry_count": 0,
        "retry_condition_counts": {},
    }
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
    return row


def _write_attempt(
    root: Path,
    *,
    outer_plan: dict,
    feasible: bool,
    margin: float,
    action: str,
) -> None:
    root.mkdir(parents=True)
    (root / "campaign_plan.json").write_bytes(
        canonical_json_bytes(outer_plan) + b"\n"
    )
    canary = {
        "schema_version": "aeread.provider_admission_canary/0.4",
        "campaign_id": outer_plan["campaign_id"],
        "status": "admitted",
        "scored": False,
        "model": QWEN235B_GOOGLE_CANDIDATE.route.model,
        "revision": QWEN235B_GOOGLE_CANDIDATE.route.revision,
        "route_provider": QWEN235B_GOOGLE_CANDIDATE.route.route_provider,
        "resolved_model": QWEN235B_GOOGLE_CANDIDATE.route.revision,
        "cost_usd": 0.0001,
        "cost_accounting": "exact",
    }
    canary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(canary)
    ).hexdigest()
    (root / "admission_canary.json").write_bytes(
        canonical_json_bytes(canary) + b"\n"
    )
    rows = [
        _row(path=path, seed=seed, feasible=feasible, margin=margin, action=action)
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
        "violation_counts": {} if feasible else {"malformed_procurement_action": 18},
        "readiness": {"execution_qualified": True},
    }
    artifact = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": outer_plan["scored_plan"],
        "preflight": {},
        "summary": summary,
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    scored = root / "scored"
    scored.mkdir()
    (scored / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path]:
    control = tmp_path / "runs" / CONTROL_CAMPAIGN_ID / "attempt_001"
    treatment = tmp_path / "runs" / TREATMENT_CAMPAIGN_ID / "attempt_001"
    _write_attempt(
        control,
        outer_plan=build_control_plan(),
        feasible=False,
        margin=8.0,
        action="inquire",
    )
    _write_attempt(
        treatment,
        outer_plan=build_treatment_plan(),
        feasible=True,
        margin=10.0,
        action="request_quote",
    )
    return control, treatment


def test_paired_treatment_comparison_uses_six_case_clusters(tmp_path: Path) -> None:
    control, treatment = _fixture_roots(tmp_path)

    result = build_paired_treatment_comparison(
        control_run_root=control, treatment_run_root=treatment
    )

    assert result["readiness"]["paired_prompt_treatment_comparison_qualified"] is True
    assert result["completed_pair_count"] == 18
    assert result["feasibility_transition_counts"] == {"fail_to_pass": 18}
    assert result["first_action_transition_counts"] == {
        "inquire_to_request_quote": 18
    }
    assert result["aggregate_effects_treatment_minus_control"]["feasible"] == {
        "case_cluster_mean": 1.0,
        "case_cluster_bootstrap_95_interval": [1.0, 1.0],
    }
    assert result["aggregate_effects_treatment_minus_control"][
        "contribution_margin_usd"
    ]["case_cluster_mean"] == 2.0
    assert all(result["integrity"].values())


def test_treatment_publisher_writes_digest_bound_sanitized_bundle(
    tmp_path: Path,
) -> None:
    control, treatment = _fixture_roots(tmp_path)
    publication_root = tmp_path / "evidence" / TREATMENT_CAMPAIGN_ID

    manifest = publish_campaign(
        control_run_root=control,
        treatment_run_root=treatment,
        publication_root=publication_root,
    )

    assert manifest["publication_id"] == TREATMENT_CAMPAIGN_ID
    comparison_path = (
        publication_root / "reports" / "paired_prompt_treatment_comparison.json"
    )
    assert comparison_path.is_file()
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert comparison["readiness"]["paired_prompt_treatment_comparison_qualified"]
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication_root / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(
        path.read_text() for path in publication_root.rglob("*.json")
    )
    assert "raw_response" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
