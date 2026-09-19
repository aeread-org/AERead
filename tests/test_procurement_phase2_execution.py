import asyncio
import copy
import json
from types import SimpleNamespace
import pytest
from aeread.shared_runner.task.execution import ProviderFailure, ProviderResult
from aeread_families.procurement_allocation.phase2_budget import (
    Phase2BudgetedProvider,
    CampaignBudgetExceeded,
)
from aeread_families.procurement_allocation.phase2_campaign import (
    analyze,
    pilot_gate,
    power_sensitivity,
    offline_screen,
)
from aeread_families.procurement_allocation.phase2_worlds import (
    build_world,
    CATEGORIES,
    CONFIRMATORY_SEEDS,
    PILOT_SEEDS,
)
from aeread_families.procurement_allocation.phase2_runner import PROMPTS
from aeread_families.procurement_allocation.phase2_policies import choose_action
from aeread_families.procurement_allocation.strategy_scaffold import (
    GLM_PARASAIL_CANDIDATE,
)
from tests.test_procurement_phase2 import fixture_contribution


def request():
    r = GLM_PARASAIL_CANDIDATE.route
    return SimpleNamespace(
        model=r.model,
        revision=r.revision,
        provider_metadata={"route_provider": r.route_provider},
        provider_call_id="fixture",
        instructions="buyer",
        input_text="observe",
        output_schema={},
        messages=None,
        tools=None,
        max_output_tokens=10,
        request_sha256="a" * 64,
    )


class Script:
    def __init__(self, errors=()):
        self.errors = list(errors)
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(
            cost_usd=0.0001,
            resolved_model=request.revision,
            input_tokens=10,
            output_tokens=10,
        )


def rate_limit():
    return ProviderFailure(
        "rate_limit", "fixture HTTP 429", retryable=True, status_code=429
    )


def test_fresh_phase2_ceiling_and_pre_dispatch_reservation(tmp_path):
    script = Script()
    p = Phase2BudgetedProvider(script, tmp_path, baseline=0.449999)
    with pytest.raises(CampaignBudgetExceeded):
        asyncio.run(p.complete(request()))
    assert script.calls == 0
    p = Phase2BudgetedProvider(script, tmp_path)
    assert p.spent == 0 and p.ceiling == 0.45
    asyncio.run(p.complete(request()))
    assert p.spent == pytest.approx(0.0001)
    with pytest.raises(RuntimeError):
        Phase2BudgetedProvider(script, tmp_path)


def test_retry_reserves_unknown_429_charge_and_cannot_change_request(tmp_path):
    p = Phase2BudgetedProvider(Script([rate_limit()]), tmp_path)
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(p.complete(request()))
    assert error.value.retry_after_seconds == 60 and p.spent > 0
    reservation = p.spent
    asyncio.run(p.complete(request()))
    assert p.spent == pytest.approx(reservation + 0.0001)
    assert json.loads(p.calls[0].read_text())["cost_usd"] is None


def test_ambiguous_failure_stops_further_dispatch(tmp_path):
    script = Script([TimeoutError("fixture")])
    p = Phase2BudgetedProvider(script, tmp_path)
    with pytest.raises(TimeoutError):
        asyncio.run(p.complete(request()))
    assert p.stopped and p.spent > 0
    with pytest.raises(CampaignBudgetExceeded):
        asyncio.run(p.complete(request()))
    assert script.calls == 1


def panel(seeds=CONFIRMATORY_SEEDS):
    rows = []
    worlds = [build_world(i)["case_id"] for i in range(8)]
    for i, w in enumerate(worlds):
        for s in seeds:
            for arm in PROMPTS:
                bound = 0 if i >= 6 else 100
                regret = 0 if i >= 6 else (20 if arm == "control" else 10)
                rows.append(
                    dict(
                        world_id=w,
                        category=CATEGORIES[i],
                        environment_seed=s,
                        arm=arm,
                        status="completed",
                        receipt_replayed=True,
                        decision="defer" if i >= 6 else "award",
                        termination_reason="deferred" if i >= 6 else "submitted",
                        feasible=True,
                        feasible_award=i < 6,
                        upper_bound_usd=bound,
                        regret_to_upper_bound_usd=regret,
                        contribution_margin_usd=bound - regret,
                        violations=[],
                    )
                )
    return rows, worlds


def test_fixed_world_cluster_analysis_and_missingness():
    rows, worlds = panel()
    r = analyze(rows, worlds)
    assert r["delta_usd"] == -7.5 and r["support"] and len(r["per_world"]) == 8
    assert not analyze(rows[:-1], worlds)["fully_replayed"]
    assert not analyze(rows + [rows[0]], worlds)["fully_replayed"]
    rows[1]["violations"] = ["fixture_invalid_award"]
    rows[1]["feasible"] = False
    assert not analyze(rows, worlds)["support"]


def test_pilot_does_not_reward_always_defer_or_claim_unobserved_variance():
    rows, worlds = panel(PILOT_SEEDS)
    assert pilot_gate(rows, worlds)["passed"]
    for r in rows:
        r.update(decision="defer", feasible_award=False, contribution_margin_usd=0)
    assert not pilot_gate(rows, worlds)["passed"]
    assert pilot_gate(rows, worlds)["within_world_variance"] is None
    p = power_sensitivity()
    assert (
        0.63 < p["power_at_d_095"] < 0.65 and 1.15 < p["d_for_80_percent_power"] < 1.17
    )


def test_screen_measures_all_worlds_without_zero_bound_division():
    s = offline_screen()
    assert s["passed"] and len(s["worlds"]) == 8 and s["live_calls"] == 0
    assert all(w["relative_policy_spread"] >= 0.15 for w in s["worlds"][:6])
    assert all(w["relative_policy_spread"] is None for w in s["worlds"][6:])


class PolicyProvider:
    async def complete(self, request):
        observation = json.loads(request.input_text)["observation"]
        action = choose_action(observation)
        return ProviderResult(
            response_id="fixture_response",
            requested_model=request.model,
            resolved_model=request.revision,
            output_text=json.dumps(action),
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"test_only": True},
        )


def test_full_campaign_gates_64_replayed_rows_and_one_freeze(tmp_path, monkeypatch):
    from aeread_families.procurement_allocation import phase2_execution as execution
    from aeread_families.procurement_allocation.phase2_admission import source_pins

    # Only the reviewer/admission fixture is substituted. All 64 trajectories,
    # budgets, gates, row audits, receipts and inference use production code.
    admission = tmp_path / "admission"
    admission.mkdir()
    c = fixture_contribution(admission)
    screen = offline_screen()
    (admission / "offline_screen.json").write_text(json.dumps(screen))
    (admission / "provider_free_conformance.json").write_text(
        json.dumps(
            {"passed": True, "test_only": True, "implementation_pins": source_pins()}
        )
    )
    # Refresh the fixture's content-addressed evidence after setting the test log.
    from dataclasses import replace
    import hashlib
    from aeread.shared_runner.registry import family_contribution_sha256

    ref = replace(
        c.provider_free_evidence,
        sha256=hashlib.sha256(
            (admission / c.provider_free_evidence.path).read_bytes()
        ).hexdigest(),
    )
    c = replace(c, provider_free_evidence=ref)
    c = replace(
        c,
        human_qc_approval=replace(
            c.human_qc_approval, contribution_sha256=family_contribution_sha256(c)
        ),
    )
    monkeypatch.setattr(execution, "load_contribution", lambda root: c)
    root = tmp_path / "runs" / "phase2"
    result = asyncio.run(
        execution.run_campaign(
            root,
            admission,
            provider_factory=PolicyProvider,
            preflight=lambda candidate: {"test_only": True},
        )
    )
    from aeread_families.procurement_allocation.phase2_campaign import (
        BASELINE_SETTLED_USD,
    )

    assert result["status"] == "completed"
    assert result["accounted_cost_usd"] == pytest.approx(
        BASELINE_SETTLED_USD, abs=1e-12
    )
    assert result["known_settled_cost_usd"] == 0
    assert result["combined_known_settled_cost_usd"] == BASELINE_SETTLED_USD
    rows = json.loads((root / "confirmatory" / "report.json").read_text())["rows"]
    assert len(rows) == 48 and all(r["receipt_replayed"] for r in rows)
    assert len(json.loads((root / "pilot" / "report.json").read_text())["rows"]) == 16
    assert len(list((root / "gates").glob("*confirmatory_freeze.json"))) == 1
    assert (
        result["comparison"]["delta_usd"] == 0 and not result["comparison"]["support"]
    )
    with pytest.raises(RuntimeError, match="already initialized"):
        asyncio.run(
            execution.run_campaign(
                root, admission, provider_factory=PolicyProvider, preflight=lambda c: {}
            )
        )


def test_live_row_preserves_unknown_retry_billing(tmp_path, monkeypatch):
    from aeread_families.procurement_allocation.phase2_execution import run_row

    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    delegate = PolicyProvider()

    class First429:
        calls = 0

        async def complete(self, request):
            self.calls += 1
            if self.calls == 1:
                raise rate_limit()
            return await delegate.complete(request)

    admission = tmp_path / "admission"
    admission.mkdir()
    contribution = fixture_contribution(admission)
    root = tmp_path / "run"
    provider = Phase2BudgetedProvider(First429(), root)
    row = asyncio.run(
        run_row(
            root,
            "pilot",
            build_world(6),
            CATEGORIES[6],
            52001,
            "control",
            provider,
            contribution,
            admission,
        )
    )
    assert row["status"] == "completed" and row["receipt_replayed"]
    assert row["cost_usd"] is None and row["known_cost_usd"] == 0
    assert row["unresolved_reserved_cost_usd"] > 0 and row["runner_retry_count"] == 1
    assert delays == [60]
