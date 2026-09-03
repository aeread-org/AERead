from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.glm_holdout_transfer_campaign as campaign_module
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.glm_holdout_transfer_campaign import (
    BOOTSTRAP_RESAMPLES,
    CAMPAIGN_ID,
    HARD_TOTAL_COST_CEILING_USD,
    SPEC,
    build_comparison,
    build_plan,
    publish_campaign,
    run_admission_canary,
)
from aeread_families.procurement_allocation.qwen_holdout_campaign import INFERENCE_SEEDS
from aeread_families.procurement_allocation.qwen_holdout_case_matrix import (
    CASE_SLUGS,
    OPAQUE_PATHS,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _split_action(slug: str) -> list[dict]:
    path = next(path for path in OPAQUE_PATHS if path.stem == slug)
    suppliers = json.loads(path.read_text())["payload"]["suppliers"]
    by_component: dict[str, list[str]] = {}
    for supplier in suppliers:
        by_component.setdefault(supplier["component"], []).append(
            supplier["supplier_id"]
        )
    split_ids = next(values for values in by_component.values() if len(values) > 1)
    return [
        {
            "action": "submit_award",
            "ordinal": 9,
            "status": "succeeded",
            "award_lines": [
                {"offer_id": f"offer_{split_ids[0]}_v1", "quantity": 10},
                {"offer_id": f"offer_{split_ids[1]}_v1", "quantity": 10},
            ],
        }
    ]


def _write_synthetic_run(root: Path, *, favorable: bool) -> None:
    plan = build_plan()
    _write_json(root / "campaign_plan.json", plan)
    canary = {
        "schema_version": "aeread.provider_admission_canary/0.4",
        "campaign_id": CAMPAIGN_ID,
        "status": "admitted",
        "scored": False,
        "request_sha256": "a" * 64,
        "model": SPEC.candidate.route.model,
        "revision": SPEC.candidate.route.revision,
        "route_provider": SPEC.candidate.route.route_provider,
        "resolved_model": SPEC.candidate.route.revision,
        "cost_usd": 0.001,
        "cost_accounting": "exact",
        "provider_call_count": 1,
        "runner_retry_count": 0,
        "retry_condition_counts": {},
    }
    canary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(canary)
    ).hexdigest()
    _write_json(root / "admission_canary.json", canary)

    parent = json.loads(campaign_module.PARENT_TREATMENT_PATH.read_text())
    rows = []
    favorable_slugs = set(CASE_SLUGS[:2]) if favorable else set()
    for source in parent["rows"]:
        row = dict(source)
        slug = str(row["case_id"]).rsplit(".", 1)[-1]
        row["resolved_models"] = [SPEC.candidate.route.revision]
        row["cost_usd"] = 0.001
        row["cost_accounting"] = "exact"
        row["provider_call_count"] = 5
        row["runner_retry_count"] = 0
        row["retry_condition_counts"] = {}
        if slug in favorable_slugs:
            row.update(
                {
                    "decision": "award",
                    "termination_reason": "submitted",
                    "feasible": True,
                    "completed_kits": 20,
                    "contribution_margin_usd": float(row["upper_bound_usd"]) - 1.0,
                    "regret_to_upper_bound_usd": 1.0,
                    "violations": [],
                    "action_count": 9,
                    "action_trace": _split_action(slug),
                }
            )
        row.pop("result_sha256", None)
        row["result_sha256"] = hashlib.sha256(
            canonical_json_bytes(row)
        ).hexdigest()
        rows.append(row)
    feasible_count = sum(row["feasible"] is True for row in rows)
    summary = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": plan["scored_plan"],
        "preflight": {
            "candidate_id": SPEC.candidate.candidate_id,
            "model": SPEC.candidate.route.model,
            "revision": SPEC.candidate.route.revision,
            "route_provider": SPEC.candidate.route.route_provider,
            "quantization": SPEC.candidate.route.quantization,
        },
        "summary": {
            "planned_trajectory_count": len(rows),
            "row_count": len(rows),
            "unattempted_trajectory_count": 0,
            "completed_trajectory_count": len(rows),
            "operational_failure_count": 0,
            "total_cost_usd": len(rows) * 0.001,
            "cost_accounting": "exact",
            "feasible_count": feasible_count,
            "violation_counts": {},
            "median_elapsed_seconds": 1.0,
            "provider_call_count": len(rows) * 5,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    summary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(summary)
    ).hexdigest()
    _write_json(root / "scored" / "summary.json", summary)


def test_glm_transfer_plan_freezes_parent_controls_and_budget() -> None:
    plan = build_plan()
    scored = plan["scored_plan"]
    parent = json.loads(campaign_module.PARENT_TREATMENT_PATH.read_text())

    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["freeze_status"] == "frozen_before_live_execution"
    assert plan["matched_baseline_campaign_id"] == (
        "procurement_allocation_qwen3_235b_google_holdout_v1.treatment"
    )
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.30)
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(0.57)
    assert HARD_TOTAL_COST_CEILING_USD == pytest.approx(0.57)
    assert scored["planned_trajectory_count"] == 18
    assert scored["inference_seeds"] == list(INFERENCE_SEEDS)
    assert scored["cases"] == parent["plan"]["cases"]
    assert scored["prompt"] == parent["plan"]["prompt"]
    assert scored["harness"] == parent["plan"]["harness"]
    assert scored["retry_policy"] == parent["plan"]["retry_policy"]
    assert plan["lineage"]["comparison_contract"]["primary_outcome"] == (
        "feasible_purchase_award"
    )
    assert plan["plan_sha256"] == (
        "3fbba58ab765cde80740fc18a328d2ec0a548e8fd6c76dc17ce597fd5a6557f5"
    )


def test_glm_transfer_plan_rejects_prompt_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(campaign_module, "V2_PROMPT", campaign_module.V2_PROMPT + " drift")
    with pytest.raises(ValueError, match="frozen V2 prompt changed"):
        campaign_module.build_plan()


def test_glm_transfer_canary_uses_exact_model_route_prompt_and_cases(
    tmp_path: Path,
) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "test canary"}),)
    )

    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "canary.json",
            provider_factory=lambda: provider,
        )
    )

    request = provider.requests[0]
    assert canary["status"] == "admitted"
    assert canary["cost_accounting"] == "exact"
    assert request.model == SPEC.candidate.route.model
    assert request.revision == SPEC.candidate.route.revision
    assert request.provider_metadata["route_provider"] == "Parasail"
    assert request.instructions == campaign_module.V2_PROMPT
    assert "private_terms" not in request.input_text


def test_glm_transfer_signal_requires_two_independent_split_worlds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root = tmp_path / "runs" / CAMPAIGN_ID / "attempt_001"
    _write_synthetic_run(root, favorable=True)

    comparison = build_comparison(run_root=root)

    assert comparison["readiness"]["model_transfer_diagnostic_qualified"] is True
    assert (
        comparison["transfer_diagnostic"]["status"]
        == "model_route_transfer_signal_observed"
    )
    assert comparison["transfer_diagnostic"]["qwen_feasible_split_worlds"] == []
    assert set(comparison["transfer_diagnostic"]["glm_feasible_split_worlds"]) == set(
        CASE_SLUGS[:2]
    )
    assert comparison["diagnostics"]["glm"]["decision"][
        "split_award_attempt_count"
    ] == 6
    assert comparison["effects_glm_minus_qwen"]["feasible_award"][
        "world_cluster_mean"
    ] == pytest.approx(1 / 3)

    publication = tmp_path / "evidence" / CAMPAIGN_ID
    manifest = publish_campaign(run_root=root, publication_root=publication)
    assert "reports/model_transfer_analysis.json" in manifest["artifacts"]
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(path.read_text() for path in publication.rglob("*.json"))
    assert "private_terms" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert campaign_module.V2_PROMPT not in serialized


def test_null_glm_transfer_result_remains_integrity_qualified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root = tmp_path / "runs" / CAMPAIGN_ID / "attempt_001"
    _write_synthetic_run(root, favorable=False)

    comparison = build_comparison(run_root=root)

    assert comparison["readiness"]["model_transfer_diagnostic_qualified"] is True
    assert (
        comparison["transfer_diagnostic"]["status"]
        == "model_route_transfer_signal_not_observed"
    )
    assert comparison["transfer_diagnostic"]["glm_feasible_split_worlds"] == []


def test_glm_transfer_rejects_lower_runtime_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="below the frozen hard total ceiling"):
        asyncio.run(
            campaign_module.run_campaign(
                run_root=tmp_path / "runs" / CAMPAIGN_ID / "attempt_001",
                max_spend_usd=HARD_TOTAL_COST_CEILING_USD - 0.01,
            )
        )


def test_bootstrap_is_frozen_at_declared_resolution() -> None:
    assert BOOTSTRAP_RESAMPLES == 50_000
