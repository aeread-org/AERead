from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.risk_gate_campaign as campaign_module
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.policy_baselines import (
    PublicObservationPolicyProvider,
)
from aeread_families.procurement_allocation.risk_gate_campaign import (
    BOOTSTRAP_RESAMPLES,
    CAMPAIGN_ID,
    CASH_PROMPT,
    CONDITIONS,
    INFERENCE_SEEDS,
    JOINT_PROMPT,
    PROMPTS,
    TEMPORAL_PROMPT,
    V1_CAMPAIGN_ID,
    V2_CAMPAIGN_ID,
    V3_CAMPAIGN_ID,
    build_plan,
    build_risk_gate_comparison,
    publish_risk_gate_campaign,
    run_admission_canary,
)
from aeread_families.procurement_allocation.risk_gate_case_matrix import CASE_SLUGS
from aeread_families.procurement_allocation.runner import SequenceResponseProvider
from aeread_families.procurement_allocation.confirmatory_campaign import (
    INFERENCE_SEEDS as CONFIRMATORY_INFERENCE_SEEDS,
)
from aeread_families.procurement_allocation.strategy_scaffold import (
    PARASAIL_INFERENCE_SEEDS,
    STRATEGY_PROMPT,
)


def _write_canary(root: Path, *, condition: str) -> None:
    prompt = PROMPTS[condition]
    value = {
        "schema_version": "aeread.provider_admission_canary/0.4",
        "campaign_id": CAMPAIGN_ID,
        "condition": condition,
        "status": "admitted",
        "scored": False,
        "prompt_id": prompt["prompt_id"],
        "prompt_sha256": hashlib.sha256(prompt["prompt"].encode()).hexdigest(),
        "model": "z-ai/glm-5.3-flash",
        "revision": "z-ai/glm-5.3-flash-20260826",
        "route_provider": "Parasail",
        "resolved_model": "z-ai/glm-5.3-flash-20260826",
        "cost_usd": 0.001,
        "cost_accounting": "exact",
        "output_contract_status": "valid_structured_action",
        "structured_action": "defer",
    }
    value["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    path = root / "canaries" / f"{condition}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _condition_values(*, condition: str, stratum: str, favorable: bool) -> tuple[bool, int, float, str]:
    if not favorable:
        margin = 4.0 if condition == "joint" else 5.0
        return True, 18, margin, "award"
    if condition == "v4":
        return False, 0, 5.0, "defer"
    if condition == "temporal":
        return True, 18, 9.0 if stratum == "sample_timing" else 6.0, "award"
    if condition == "cash":
        return True, 18, 6.0 if stratum == "sample_timing" else 9.0, "award"
    return True, 20, 10.0, "award"


def _write_arm_summary(
    root: Path,
    *,
    name: str,
    plan: dict,
    favorable: bool,
) -> None:
    surface, condition = name.split("_", 1)
    rows = []
    for pair in plan["world_pairs"]:
        feasible, kits, margin, decision = _condition_values(
            condition=condition,
            stratum=pair["stratum"],
            favorable=favorable,
        )
        for seed in plan["inference_seeds"]:
            row = {
                "case_id": pair[f"{surface}_case_id"],
                "case_content_sha256": pair[f"{surface}_case_content_sha256"],
                "inference_seed": seed,
                "status": "completed",
                "decision": decision,
                "termination_reason": "submitted" if decision == "award" else "deferred",
                "feasible": feasible,
                "completed_kits": kits,
                "contribution_margin_usd": margin,
                "upper_bound_usd": 20.0,
                "regret_to_upper_bound_usd": 20.0 - margin,
                "violations": [] if feasible else ["synthetic_failure"],
                "elapsed_environment_days": 4,
                "action_count": 5,
                "action_trace": [{"ordinal": 1, "action": "request_quote"}],
                "elapsed_seconds": 1.0,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "cost_usd": 0.001,
                "cost_accounting": "exact",
                "provider_call_count": 5,
                "runner_retry_count": 0,
                "retry_condition_counts": {},
                "resolved_models": ["z-ai/glm-5.3-flash-20260826"],
                "receipt_sha256": "a" * 64,
                "receipt_replayed": True,
                "replay_level": "provider_response",
            }
            row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            rows.append(row)
    artifact = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": plan["arms"][name],
        "preflight": {
            "candidate_id": "glm53_flash_parasail",
            "model": "z-ai/glm-5.3-flash",
            "revision": "z-ai/glm-5.3-flash-20260826",
            "route_provider": "Parasail",
        },
        "summary": {
            "planned_trajectory_count": len(rows),
            "row_count": len(rows),
            "unattempted_trajectory_count": 0,
            "completed_trajectory_count": len(rows),
            "operational_failure_count": 0,
            "total_cost_usd": len(rows) * 0.001,
            "cost_accounting": "exact",
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    path = root / "arms" / name / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(artifact) + b"\n")


def _synthetic_campaign(tmp_path: Path, *, favorable: bool) -> tuple[Path, dict]:
    root = tmp_path / "runs" / "procurement_allocation" / CAMPAIGN_ID / "attempt_001"
    plan = build_plan()
    root.mkdir(parents=True)
    (root / "campaign_plan.json").write_bytes(canonical_json_bytes(plan) + b"\n")
    for name in plan["arm_execution_order"]:
        _write_arm_summary(root, name=name, plan=plan, favorable=favorable)
    for condition in CONDITIONS:
        _write_canary(root, condition=condition)
    return root, plan


def test_risk_gate_plan_freezes_factorial_distribution_and_budget() -> None:
    plan = build_plan()

    assert plan["freeze_status"] == "adaptive_mechanism_plan_frozen_before_live_execution"
    assert len({V1_CAMPAIGN_ID, V2_CAMPAIGN_ID, V3_CAMPAIGN_ID, CAMPAIGN_ID}) == 4
    assert plan["lineage"]["supersedes_campaign_id"] == V3_CAMPAIGN_ID
    assert plan["lineage"]["scientific_contract"] == "unchanged_from_v1_v2_and_v3"
    assert plan["planned_trajectory_count"] == 144
    assert plan["independent_world_count"] == 6
    assert plan["stratum_world_counts"] == {"landed_cash": 3, "sample_timing": 3}
    assert plan["inference_seeds"] == list(INFERENCE_SEEDS)
    assert plan["inference_seeds"] == [279557369, 2094119875, 262950145]
    assert len(set(INFERENCE_SEEDS)) == 3
    assert set(INFERENCE_SEEDS).isdisjoint(
        {*PARASAIL_INFERENCE_SEEDS, *CONFIRMATORY_INFERENCE_SEEDS}
    )
    assert set(plan["prompt_factorial"]) == set(CONDITIONS)
    assert plan["prompt_factorial"]["joint"]["temporal_gate"] is True
    assert plan["prompt_factorial"]["joint"]["cash_gate"] is True
    assert plan["conservative_scored_cost_ceiling_usd"] == pytest.approx(2.16)
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(2.24)
    assert plan["hard_scored_cost_ceiling_usd"] == pytest.approx(2.88)
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(2.96)
    assert plan["analysis"]["status"] == "adaptive_exploratory_not_confirmatory"
    assert plan["analysis"]["no_early_efficacy_stopping"] is True
    # Plan identity, not a seal. The seal is the campaign_plan.json inside the
    # published bundle, which digests its own content and is verified by
    # tests/test_procurement_sealed_plan_digests.py without reference to source.
    # This literal moved when the environment gained check_award, listing-level
    # verbal bias, and a relaxed action-budget range; the sealed value it
    # superseded is recorded in design_review defect 19.
    assert plan["plan_sha256"] == (
        "79000523c8b8e5e7295f8715a0369cf4ab7e8a2dc95bb1c6c696788bf2e8dfde"
    )
    assert all(arm["planned_trajectory_count"] == 18 for arm in plan["arms"].values())
    assert all(
        arm["max_cost_usd_per_trajectory"] == pytest.approx(0.02)
        for arm in plan["arms"].values()
    )
    assert all(
        arm["retry_policy"]["retry_base_seconds"] == pytest.approx(15.0)
        for arm in plan["arms"].values()
    )
    assert all(
        arm["retry_policy"]["max_action_attempts"] == 4
        for arm in plan["arms"].values()
    )


def test_risk_gate_prompts_are_additive_and_do_not_use_supplier_identity() -> None:
    assert TEMPORAL_PROMPT == STRATEGY_PROMPT + campaign_module.TEMPORAL_GATE
    assert CASH_PROMPT == STRATEGY_PROMPT + campaign_module.CASH_GATE
    assert JOINT_PROMPT == STRATEGY_PROMPT + campaign_module.TEMPORAL_GATE + campaign_module.CASH_GATE
    assert "never infer speed from a supplier name or" in TEMPORAL_PROMPT
    assert "quantity * (unit_price_usd + shipping_per_unit_usd)" in CASH_PROMPT


def test_risk_gate_plan_rejects_parent_or_prompt_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(campaign_module, "STRATEGY_PROMPT", STRATEGY_PROMPT + " drift")
    with pytest.raises(ValueError, match="frozen V4 prompt changed"):
        campaign_module.build_plan()


def test_risk_gate_canaries_bind_each_prompt(tmp_path: Path) -> None:
    for condition in CONDITIONS:
        provider = SequenceResponseProvider(
            (json.dumps({"action": "defer", "reason": "test canary"}),)
        )
        canary = asyncio.run(
            run_admission_canary(
                path=tmp_path / f"{condition}.json",
                condition=condition,
                provider_factory=lambda: provider,
            )
        )
        assert canary["status"] == "admitted"
        assert canary["scored"] is False
        assert canary["cost_accounting"] == "exact"
        assert canary["output_contract_status"] == "valid_structured_action"
        assert provider.requests[0].instructions == PROMPTS[condition]["prompt"]
        assert "private_terms" not in provider.requests[0].input_text


def test_risk_gate_canary_admits_malformed_output_without_selecting_on_behavior(
    tmp_path: Path,
) -> None:
    provider = SequenceResponseProvider(('{"action":',))

    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "v4.json",
            condition="v4",
            provider_factory=lambda: provider,
        )
    )

    assert canary["status"] == "admitted"
    assert canary["output_contract_status"] == "malformed_json"
    assert canary["structured_action"] is None
    assert canary["cost_accounting"] == "exact"
    assert canary["provider_call_count"] == 1
    assert canary["runner_retry_count"] == 0


def test_risk_gate_canary_retries_rate_limit_with_v4_pacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []

    async def no_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(campaign_module.asyncio, "sleep", no_wait)

    class RetryThenAdmit:
        def __init__(self) -> None:
            self.calls = 0
            self.delegate = SequenceResponseProvider(
                (json.dumps({"action": "defer", "reason": "canary admitted"}),)
            )

        async def complete(self, request):
            self.calls += 1
            if self.calls == 1:
                raise ProviderFailure(
                    "rate_limit",
                    "synthetic throttle",
                    retryable=True,
                    status_code=429,
                )
            return await self.delegate.complete(request)

    provider = RetryThenAdmit()
    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "v4.json",
            condition="v4",
            provider_factory=lambda: provider,
        )
    )

    assert canary["status"] == "admitted"
    assert canary["provider_call_count"] == 2
    assert canary["runner_retry_count"] == 1
    assert canary["retry_condition_counts"] == {"rate_limit": 1}
    assert canary["cost_accounting"] == "exact"
    assert waits == [15.0]


def test_risk_gate_comparison_progresses_specialized_factorial_and_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root, _ = _synthetic_campaign(tmp_path, favorable=True)

    comparison = build_risk_gate_comparison(run_root=root)

    assert comparison["readiness"]["adaptive_evidence_qualified"] is True
    assert comparison["progression"]["status"] == "progress"
    assert all(comparison["progression"]["checks"].values())
    specialization = comparison["effects"]["specialization_diagnostics_nonbinding"]
    assert all(specialization.values())
    joint = comparison["effects"]["contrasts"]["joint_minus_v4"]["overall"]
    assert joint["regret_to_upper_bound_usd"]["world_cluster_mean"] == -5.0
    assert joint["feasible"]["world_cluster_mean"] == 1.0

    publication = tmp_path / "evidence" / CAMPAIGN_ID
    manifest = publish_risk_gate_campaign(
        run_root=root,
        publication_root=publication,
    )
    assert manifest["progression_status"] == "progress"
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(path.read_text() for path in publication.rglob("*.json"))
    assert "private_terms" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert TEMPORAL_PROMPT not in serialized
    assert CASH_PROMPT not in serialized


def test_risk_gate_unfavorable_result_remains_eligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 100)
    root, _ = _synthetic_campaign(tmp_path, favorable=False)

    comparison = build_risk_gate_comparison(run_root=root)

    assert comparison["readiness"]["adaptive_evidence_qualified"] is True
    assert comparison["progression"]["status"] == "do_not_progress"
    assert comparison["progression"]["checks"]["joint_regret_improves_overall"] is False


def test_risk_gate_runner_checkpoints_each_arm_evenly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = CASE_VARIANCE_PATHS[0]
    slug = json.loads(path.read_text())["case_id"].rsplit(".", 1)[-1]
    monkeypatch.setattr(campaign_module, "CASE_SLUGS", (slug,))
    monkeypatch.setattr(campaign_module, "LABELED_PATHS", (path,))
    monkeypatch.setattr(campaign_module, "OPAQUE_PATHS", (path,))
    monkeypatch.setattr(campaign_module, "STRATA_BY_SLUG", {slug: "sample_timing"})
    monkeypatch.setattr(campaign_module, "INFERENCE_SEEDS", (11, 12))
    monkeypatch.setattr(campaign_module, "TRAJECTORIES_PER_ARM_PER_CHECKPOINT", 1)
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 100)

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(campaign_module.asyncio, "sleep", no_wait)

    root = tmp_path / "runs" / CAMPAIGN_ID / "checkpoint"
    provider_factory = lambda: PublicObservationPolicyProvider("displayed_price_greedy")
    preflight = lambda _candidate: {"route_verified": True}

    first = asyncio.run(
        campaign_module.run_risk_gate_campaign(
            run_root=root,
            provider_factory=provider_factory,
            preflight_fn=preflight,
        )
    )
    assert first["summary"]["completed_trajectory_count"] == 8
    assert first["summary"]["failure_free_checkpoint"] is True
    assert {
        arm["completed_trajectory_count"] for arm in first["arms"].values()
    } == {1}

    second = asyncio.run(
        campaign_module.run_risk_gate_campaign(
            run_root=root,
            resume=True,
            provider_factory=provider_factory,
            preflight_fn=preflight,
        )
    )
    assert second["summary"]["completed_trajectory_count"] == 16
    assert second["summary"]["execution_qualified"] is True
    assert second["comparison"]["readiness"]["adaptive_evidence_qualified"] is False
    assert all(
        value
        for key, value in second["comparison"]["integrity"].items()
        if key.endswith("_all_pairs_present")
    )


def test_risk_gate_bootstrap_configuration_is_nontrivial() -> None:
    assert BOOTSTRAP_RESAMPLES == 50_000
