from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.model_campaign import (
    CAMPAIGN_ID as GLM_BASELINE_CAMPAIGN_ID,
    planned_model_qualification,
    run_model_qualification,
)
from aeread_families.procurement_allocation.model_comparison import (
    CAMPAIGN_ID,
    MISTRAL_SMALL4_CANDIDATE,
    PAIRED_INFERENCE_SEEDS,
    build_admission_audit,
    build_paired_model_comparison,
    run_admission_canary,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider


def _write_summary(
    root: Path, *, campaign_id: str, margin_delta: float, mistral: bool
) -> None:
    rows = []
    for path in CASE_VARIANCE_PATHS:
        for seed in PAIRED_INFERENCE_SEEDS:
            row = {
                "case_id": f"procurement_allocation_v1.dev.{path.stem}",
                "case_content_sha256": hashlib.sha256(path.stem.encode()).hexdigest(),
                "inference_seed": seed,
                "status": "completed",
                "feasible": mistral,
                "completed_kits": 10 + margin_delta,
                "contribution_margin_usd": 20.0 + margin_delta,
                "upper_bound_usd": 30.0,
                "regret_to_upper_bound_usd": 10.0 - margin_delta,
                "receipt_replayed": True,
            }
            row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            rows.append(row)
    plan = {
        "campaign_id": campaign_id,
        "inference_seeds": list(PAIRED_INFERENCE_SEEDS),
        "harness": "minimal_chat/1.0 (fixed transport; not an estimand)",
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    artifact = {
        "plan": plan,
        "summary": {"readiness": {"execution_qualified": True}},
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    root.mkdir(parents=True)
    (root / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def _write_failed_attempt(root: Path, *, canary_cost: float) -> None:
    plan = {
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": "a" * 64,
    }
    row = {
        "case_id": "procurement_allocation_v1.dev.deadline_cost",
        "case_content_sha256": "b" * 64,
        "inference_seed": PAIRED_INFERENCE_SEEDS[0],
        "status": "operational_failure",
        "failure_type": "SchedulerContractError",
        "failure_condition": "empty_response",
        "failure_status_code": None,
        "failure_receipt_sha256": "c" * 64,
    }
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
    artifact = {
        "plan": plan,
        "summary": {
            "completed_trajectory_count": 0,
            "operational_failure_count": 1,
            "unattempted_trajectory_count": 17,
            "total_cost_usd": 0.0,
            "readiness": {"execution_qualified": False},
        },
        "rows": [row],
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    canary = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "status": "admitted",
        "request_sha256": "d" * 64,
        "resolved_model": "mistralai/mistral-small-2603",
        "finish_reason": "stop",
        "input_tokens": 100,
        "cached_input_tokens": 0,
        "output_tokens": 20,
        "cost_usd": canary_cost,
        "structured_action": "inquire",
        "scored": False,
    }
    canary["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(canary)).hexdigest()
    root.mkdir(parents=True)
    (root / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")
    (root / "admission_canary.json").write_bytes(canonical_json_bytes(canary) + b"\n")


def test_mistral_plan_uses_paired_cases_seeds_and_route() -> None:
    plan = planned_model_qualification(
        case_paths=CASE_VARIANCE_PATHS,
        inference_seeds=PAIRED_INFERENCE_SEEDS,
        max_parallel_cells=1,
        campaign_id=CAMPAIGN_ID,
        abort_on_operational_failure=True,
        candidate=MISTRAL_SMALL4_CANDIDATE,
    )

    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["model"] == "mistralai/mistral-small-2603"
    assert plan["revision"] == "mistralai/mistral-small-2603"
    assert plan["provider"] == "Mistral"
    assert plan["pricing_id"] == "openrouter_2026-08-31_mistral_small4_mistral"
    assert plan["planned_trajectory_count"] == 18
    assert plan["inference_seeds"] == list(PAIRED_INFERENCE_SEEDS)
    assert plan["abort_on_operational_failure"] is True
    assert plan["conservative_cost_ceiling_usd"] == 0.3024


def test_mistral_candidate_reaches_live_request_builder(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "provider-free route test"}),)
    )
    artifact = asyncio.run(
        run_model_qualification(
            run_root=tmp_path / "runs" / CAMPAIGN_ID / "attempt_001",
            case_paths=(CASE_VARIANCE_PATHS[0],),
            inference_seeds=(PAIRED_INFERENCE_SEEDS[0],),
            max_spend_usd=0.02,
            max_parallel_cells=1,
            campaign_id=CAMPAIGN_ID,
            candidate=MISTRAL_SMALL4_CANDIDATE,
            provider_factory=lambda: provider,
            preflight_fn=lambda candidate: {
                "candidate_id": candidate.candidate_id,
                "route_verified": True,
            },
        )
    )

    assert artifact["summary"]["readiness"]["execution_qualified"] is True
    assert provider.requests[0].model == "mistralai/mistral-small-2603"
    assert provider.requests[0].provider_metadata["route_provider"] == "Mistral"


def test_paired_comparison_recovers_mistral_minus_glm_effects(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    mistral = tmp_path / "mistral"
    _write_summary(
        baseline,
        campaign_id=GLM_BASELINE_CAMPAIGN_ID,
        margin_delta=0.0,
        mistral=False,
    )
    _write_summary(
        mistral,
        campaign_id=CAMPAIGN_ID,
        margin_delta=2.0,
        mistral=True,
    )

    result = build_paired_model_comparison(
        baseline_run_root=baseline, mistral_run_root=mistral
    )

    assert result["readiness"]["paired_model_comparison_qualified"] is True
    assert result["completed_pair_count"] == 18
    assert result["feasibility_transition_counts"] == {"fail_pass": 18}
    effects = result["aggregate_effects_mistral_minus_glm"]
    assert effects["contribution_margin_usd"]["case_cluster_mean"] == 2.0
    assert effects["contribution_margin_usd"]["case_cluster_bootstrap_95_interval"] == [
        2.0,
        2.0,
    ]
    assert effects["regret_to_upper_bound_usd"]["case_cluster_mean"] == -2.0


def test_admission_audit_preserves_repeated_failure_without_scoring(
    tmp_path: Path,
) -> None:
    roots = [
        tmp_path / "runs" / CAMPAIGN_ID / "qualification_attempt_001",
        tmp_path / "runs" / CAMPAIGN_ID / "qualification_attempt_002",
    ]
    _write_failed_attempt(roots[0], canary_cost=0.001)
    _write_failed_attempt(roots[1], canary_cost=0.002)

    audit = build_admission_audit(attempt_roots=roots)

    assert audit["finding"] == {
        "repeated_post_canary_failure": True,
        "route_eligible_for_scored_campaign": False,
        "model_comparison_allowed": False,
    }
    assert audit["failure_condition_counts"] == {"empty_response": 2}
    assert audit["reported_cost_usd"] == 0.003
    assert len(audit["attempts"]) == 2
    assert "contribution_margin_usd" not in canonical_json_bytes(audit).decode()


def test_mistral_canary_uses_declared_request_shape(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    provider = SequenceResponseProvider((json.dumps({"action": "defer"}),))

    result = asyncio.run(
        run_admission_canary(path=path, provider_factory=lambda: provider)
    )

    assert result["status"] == "admitted"
    assert result["campaign_id"] == CAMPAIGN_ID
    assert result["request_sha256"] == provider.requests[0].request_sha256
    assert provider.requests[0].model == "mistralai/mistral-small-2603"
    assert result["scored"] is False
    assert "raw_response" not in path.read_text()
