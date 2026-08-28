"""Predeclared procurement panels and strict live admission gates."""
import asyncio

import pytest

from aeread.shared_runner.procurement_experiment import (
    analyze_procurement_panel, derive_procurement_world_seeds, run_procurement_experiment,
    validate_live_admission,
)
from aeread.shared_runner.procurement_rfq import build_procurement_rfq_smoke


def test_seed_panel_is_stable_unique_and_admission_disjoint():
    panel = derive_procurement_world_seeds(master_seed=20260827, count=100)
    assert panel == derive_procurement_world_seeds(master_seed=20260827, count=100)
    assert len(set(panel)) == 100
    assert not set(panel) & set(derive_procurement_world_seeds(master_seed=20260827, count=3, admission=True))


def test_small_offline_panel_uses_real_receipts_but_is_not_live_evidence(tmp_path):
    result = asyncio.run(run_procurement_experiment(output_root=tmp_path, world_count=2, replicates=2, bootstrap_draws=100))
    assert result["mode"] == "offline"
    assert result["batch"]["included_count"] == 8
    assert result["analysis"]["status"] == "complete"
    assert result["analysis"]["analysis"]["mean_paired_difference"] == 0
    assert result["analysis"]["analysis"]["complete_pair_world_count"] == 2
    assert result["live_admission"] is False
    assert result["batch"]["known_cost_usd"] == 0


def test_live_sample_requires_admission_and_explicit_condition_budget(tmp_path):
    with pytest.raises(ValueError, match="conditions|effort"):
        asyncio.run(run_procurement_experiment(output_root=tmp_path, mode="sample", spend_limit_usd=10))
    with pytest.raises(ValueError, match="budget|spend"):
        asyncio.run(run_procurement_experiment(output_root=tmp_path, mode="sample", control_effort="low", treatment_effort="high"))
    with pytest.raises(ValueError, match="admission"):
        asyncio.run(run_procurement_experiment(output_root=tmp_path, mode="sample", control_effort="low", treatment_effort="high", spend_limit_usd=10, master_seed=20260828))


def test_declared_panel_does_not_erase_missing_worlds_or_accept_extra_replicates():
    setups = {c: build_procurement_rfq_smoke(world_seeds=(11, 12, 13), replicates=1, condition_id=c)
              for c in ("control", "treatment")}
    rows = [{"condition_id": c, "world_seed": w, "replicate_index": 0, "status": "completed", "within_case_score": .5}
            for c in setups for w in (11, 12)]
    result = analyze_procurement_panel(rows, setups=setups, bootstrap_draws=100)
    assert result["status"] == "deferred_incomplete_panel" and result["unattempted_count"] == 2
    assert result["planned_world_count"] == 3
    with pytest.raises(ValueError, match="outside|identity"):
        analyze_procurement_panel(rows + [{**rows[0], "replicate_index": 1}], setups=setups, bootstrap_draws=100)


def test_live_admission_rejects_scripted_or_incomplete_evidence():
    setups = {c: build_procurement_rfq_smoke(world_seeds=(11, 12, 13), replicates=1, condition_id=c)
              for c in ("control", "treatment")}
    with pytest.raises(ValueError, match="live|admission|Google"):
        validate_live_admission([], setups=setups)


def test_study_manifest_locks_analysis_settings_before_resume(tmp_path):
    asyncio.run(run_procurement_experiment(output_root=tmp_path, world_count=2, replicates=1, bootstrap_draws=100))
    with pytest.raises(ValueError, match="study manifest"):
        asyncio.run(run_procurement_experiment(output_root=tmp_path, world_count=2, replicates=1, bootstrap_draws=200))


def test_missingness_support_keeps_failed_world_in_denominator():
    from aeread.shared_runner.procurement_measurement import procurement_score_support
    from aeread.shared_runner.procurement_rfq import ProcurementRFQPlugin
    setups = {c: build_procurement_rfq_smoke(world_seeds=(11, 12, 13), replicates=1, condition_id=c)
              for c in ("control", "treatment")}
    rows = [{"condition_id": c, "world_seed": w, "replicate_index": 0, "status": "completed", "within_case_score": .5}
            for c in setups for w in (11, 12, 13)]
    rows[-1].update(status="operational_failure", within_case_score=None)
    result = analyze_procurement_panel(rows, setups=setups, bootstrap_draws=100)["analysis"]
    case = next(c for c in setups["control"].plan.cases if c.world_seed == 13)
    lower, _ = procurement_score_support(ProcurementRFQPlugin().validate_payload(case.payload))
    assert result["planned_world_count"] == 3 and result["complete_pair_world_count"] == 2
    assert result["missingness_difference_bounds"] == pytest.approx([(lower-.5)/3, .5/3])


def test_live_admission_validates_each_condition_seed_and_native_call_identity():
    from aeread.shared_runner.execution import _paired_cell_request_seed
    setups = {f"reasoning_{effort}_v1": build_procurement_rfq_smoke(
        buyer_provider="google", buyer_model="gemini-3.7-flash", buyer_revision="3.7-flash-08-2026",
        world_seeds=(11, 12, 13), replicates=1, reasoning_effort=effort)
        for effort in ("low", "high")}
    rows = []
    for condition, setup in setups.items():
        for cell in setup.plan.cells:
            rows.append({"condition_id": condition, "world_seed": cell.world_seed, "replicate_index": 0,
                "status": "completed", "receipt_inclusion_status": "included", "replay_level": "state_and_score",
                "external_provider_call_count": 4, "external_fixture_call_count": 0,
                "unknown_cost_provider_call_count": 0,
                "request_seeds": [_paired_cell_request_seed(base_seed=0, world_seed=cell.world_seed, replicate_index=0)],
                "reasoning_efforts": [condition.split("_")[1]], "resolved_models": ["gemini-3.7-flash"]})
    validate_live_admission(rows, setups=setups)
    rows[0]["external_fixture_call_count"] = 1
    with pytest.raises(ValueError, match="scripted"):
        validate_live_admission(rows, setups=setups)


@pytest.mark.parametrize("master_seed", [None, 20260827])
def test_live_run_requires_fresh_explicit_panel_seed(tmp_path, master_seed):
    with pytest.raises(ValueError, match="fresh|seed"):
        asyncio.run(run_procurement_experiment(output_root=tmp_path, mode="sample",
            control_effort="low", treatment_effort="high", spend_limit_usd=10,
            master_seed=master_seed))


def test_deepseek_admission_uses_shared_batch_with_none_low_and_parasail(tmp_path, monkeypatch):
    import aeread.shared_runner.procurement_experiment as experiment
    captured = {}
    class FakeClient:
        pass
    async def fake_batch(**kwargs):
        captured.update(kwargs)
        return {"rows": [], "known_cost_usd": 0}
    monkeypatch.setattr(experiment, "OpenRouterChatClient", FakeClient, raising=False)
    monkeypatch.setattr(experiment, "run_family_batch", fake_batch)
    result = asyncio.run(run_procurement_experiment(output_root=tmp_path, provider="deepseek",
        mode="admission", master_seed=20260828, control_effort="none", treatment_effort="low",
        spend_limit_usd=5))
    assert set(captured["setups"]) == {"reasoning_none_v1", "reasoning_low_v1"}
    assert sum(len(s.plan.cells) for s in captured["setups"].values()) == 6
    for condition, setup in captured["setups"].items():
        buyer = next(p for p in setup.plan.agent_profiles if p.model.provider == "openrouter")
        assert buyer.model.model == "deepseek/deepseek-v4-flash-0731"
        assert buyer.harness.config["provider_metadata"]["route_provider"] == "Parasail"
        assert buyer.sampling.max_output_tokens == 8192
        assert buyer.budgets.timeout_seconds == 600
        assert buyer.budgets.max_cost_usd == .04
        assert isinstance(captured["providers_by_condition"][condition]["openrouter"], FakeClient)
    assert result["live_admission"] is False


def test_deepseek_admission_requires_verified_actual_route():
    from aeread.shared_runner.execution import _paired_cell_request_seed
    from aeread.shared_runner.housing import OpenRouterRoutePin
    route = OpenRouterRoutePin("Parasail", "fp8", "deepseek/deepseek-v4-flash-20260731", .14, .05, .28, "test_parasail")
    setups = {f"reasoning_{effort}_v1": build_procurement_rfq_smoke(
        buyer_provider="openrouter", buyer_model="deepseek/deepseek-v4-flash-0731",
        buyer_revision=route.canonical_model, world_seeds=(11, 12, 13), replicates=1,
        reasoning_effort=effort, openrouter_route=route) for effort in ("none", "low")}
    rows = [{"condition_id": condition, "world_seed": cell.world_seed, "replicate_index": 0,
        "status": "completed", "receipt_inclusion_status": "included", "replay_level": "state_and_score",
        "external_provider_call_count": 4, "external_fixture_call_count": 0,
        "unknown_cost_provider_call_count": 0,
        "request_seeds": [_paired_cell_request_seed(base_seed=0, world_seed=cell.world_seed, replicate_index=0)],
        "reasoning_efforts": [condition.split("_")[1]], "reasoning_tokens": 0,
        "resolved_models": [route.canonical_model], "route_providers": ["Parasail"],
        "route_verification_failures": 0}
        for condition, setup in setups.items() for cell in setup.plan.cells]
    validate_live_admission(rows, setups=setups)
    rows[0]["route_providers"] = ["another_provider"]
    with pytest.raises(ValueError, match="route"):
        validate_live_admission(rows, setups=setups)
