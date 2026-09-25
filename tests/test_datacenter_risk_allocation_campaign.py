"""The risk-allocation case through the shared runner: plans resolve, receipts seal and replay.

The reference plays one cell per seat and protocol through ``execute_plan_cell``
with no network; each receipt must verify, replay to the same digest, and grade
zero decision regret. This is the path live campaigns take.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_campaign as rc


@pytest.mark.parametrize("arm", ["one_price_low", "two_prices_low"])
@pytest.mark.parametrize("seat", ra.SEATS)
def test_the_reference_seals_a_verified_replayable_zero_regret_receipt(tmp_path: Path, arm: str, seat: str) -> None:
    cases = rc._cases(rc.ARMS[arm]["pack"], seat)[:1]
    setup = rc.build_setup(arm, "reference", seat, cases)
    entry = {"arm": arm, "route_id": "reference", "seat": seat}
    record = asyncio.run(rc._run_cell(tmp_path, entry, setup, setup.plan.cells[0], rc.Spend(1.0), asyncio.Semaphore(1)))
    assert record["status"] == "ok", record
    assert record["grade"]["valid"] and record["grade"]["decision_regret"] == pytest.approx(0.0, abs=1e-6)
    receipts = list(tmp_path.rglob("evaluation_receipt.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["receipt_sha256"] == record["receipt_sha256"]


def test_live_plans_resolve_with_the_declared_limits() -> None:
    for arm, spec in rc.ARMS.items():
        for route in rc.ROUTES:
            setup = rc.build_setup(arm, route, "client", rc._cases(spec["pack"], "client")[:2])
            profile = setup.plan.agent_profiles[0]
            assert profile.sampling.max_output_tokens == spec["max_output_tokens"][route]
            assert profile.reasoning.effort == spec["reasoning_effort"]
            assert profile.budgets.timeout_seconds == spec["timeout_seconds"][route]


def test_the_system_prompt_keeps_the_accept_instruction_the_two_prices_probe_lost() -> None:
    for seat in ra.SEATS:
        assert "price is null" in rc.system_prompt(seat, False)
        assert "price is null" in rc.system_prompt(seat, True) and "alternate is null" in rc.system_prompt(seat, True)


def test_v1_profiles_keep_one_attempt_and_no_request_seed() -> None:
    setup = rc.build_setup("one_price_low", "glm53_flash", "client", rc._cases("risk_allocation_dev_v1", "client")[:1])
    profile = setup.plan.agent_profiles[0]
    assert profile.retry_policy.max_action_attempts == 1 and tuple(profile.retry_policy.retryable_conditions) == ()
    assert "request_seed_source" not in profile.harness.config and profile.profile_id.endswith("_v1")


@pytest.mark.parametrize("arm", ["one_price_low", "one_price_default"])
def test_v2_model_profiles_retry_provider_faults_with_backoff_and_share_a_request_seed(arm: str) -> None:
    for route in rc.ROUTES:
        setup = rc.build_setup(arm, route, "integrator", rc._cases(rc.EVAL_PACK, "integrator")[:2], rc.V2)
        profile = setup.plan.agent_profiles[0]
        assert profile.retry_policy.max_action_attempts == 4
        assert set(profile.retry_policy.retryable_conditions) == {"rate_limit", "provider_5xx", "transport", rc.POST_ADMISSION_REJECTION}
        assert "length" not in profile.retry_policy.retryable_conditions  # a cut-off reply is the model's, never retried
        assert profile.harness.config["retry_backoff"] == "exponential_jitter_v1"
        assert profile.harness.config["request_seed_source"] == "paired_cell_v1"
        assert sorted(c.replicate_index for c in setup.plan.cells) == [0, 0, 1, 1]


@pytest.mark.parametrize("seat", ra.SEATS)
def test_v2_scripted_controls_seal_valid_receipts_and_the_reference_scores_zero(tmp_path: Path, seat: str) -> None:
    for policy in rc.V2.controls[seat]:
        route = f"{rc.SCRIPTED}{policy}"
        setup = rc.build_setup(rc.CONTROLS_ARM, route, seat, rc._cases(rc.EVAL_PACK, seat)[:1], rc.V2)
        assert "scripted" in setup.plan.agent_profiles[0].profile_id
        entry = {"arm": rc.CONTROLS_ARM, "route_id": route, "seat": seat}
        record = asyncio.run(rc._run_cell(tmp_path / policy, entry, setup, setup.plan.cells[0], rc.Spend(1.0), asyncio.Semaphore(1), rc.V2))
        assert record["status"] == "ok" and record["grade"]["valid"], record
        assert record["cost_usd"] == 0.0 and record["provider_calls"] >= 1
        if policy == "reference":
            assert record["grade"]["decision_regret"] == pytest.approx(0.0, abs=1e-6)


def test_a_cells_cost_is_read_from_every_call_in_its_event_log(tmp_path: Path) -> None:
    """DC-T-13: a cell that fails after answered calls was billed for them."""
    attempt = tmp_path / "cell" / "attempt"
    (attempt / "artifacts").mkdir(parents=True)
    events = []
    for i, cost in enumerate((0.0125, 0.0031)):
        (attempt / "artifacts" / f"p{i}.json").write_text(json.dumps({"cost_usd": cost}))
        events.append({"event_type": "provider_call_succeeded", "payload_ref": f"artifacts/p{i}.json"})
    events += [{"event_type": "provider_call_outcome_unknown", "payload_ref": "artifacts/none"},
               {"event_type": "provider_call_failed", "payload_ref": "artifacts/none"}]
    (attempt / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    cost, answered, unknown = rc._events_cost(tmp_path / "cell")
    assert cost == pytest.approx(0.0156) and answered == 2 and unknown == 1


def test_the_eval_pack_shares_no_world_with_the_dev_pack() -> None:
    from aeread_families.datacenter_development import risk_allocation_pack as rp

    dev, _ = rp.load("risk_allocation_dev_v1")
    ev, cases = rp.load(rc.EVAL_PACK)
    assert not {w["seed"] for w in dev["worlds"]} & {w["seed"] for w in ev["worlds"]}
    assert len(ev["worlds"]) == 32 and len(cases) == 64


def _row(arm: str, route: str, world: str, rep: int, regret: float | None, *, twin_of: str | None = None, package: str = "p") -> dict:
    return {"arm": arm, "route_id": route, "seat": "client", "world": world, "twin_of": twin_of, "replicate_index": rep, "case_id": world,
            "valid": regret is not None, "invalid": None if regret is not None else "truncated_reply", "decision_regret": regret,
            "signed_package": package, "efficient_package": package, "switched_package": False, "first_move_regret": 0.0,
            "allocation_gap": 0.0, "termination": "signed"}


def test_the_model_contrast_pairs_on_world_and_replicate_and_drops_one_sided_pairs() -> None:
    from aeread_families.datacenter_development import risk_allocation_publication as pub

    rows = [
        _row("a", "gemini38_flash", "w1", 0, 100.0), _row("a", "glm53_flash", "w1", 0, 40.0),
        _row("a", "gemini38_flash", "w1", 1, 80.0), _row("a", "glm53_flash", "w1", 1, 80.5),
        _row("a", "gemini38_flash", "w2", 0, 10.0), _row("a", "glm53_flash", "w2", 0, None),  # GLM missing: no pair
        _row("a", "gemini38_flash", "t2", 0, 30.0, twin_of="w1"), _row("a", "glm53_flash", "t2", 0, 50.0, twin_of="w1"),
    ]
    out = pub.analysis(rows, ["a"], {"primary": "x"})
    c = out["model_contrast_glm53_flash_minus_gemini38_flash"]["a/client"]
    assert c["pairs"] == 3 and c["worlds"] == 1  # the twin clusters with w1; w2 has no pair
    assert c["mean_difference"] == pytest.approx((-60.0 + 0.5 + 20.0) / 3, abs=1e-3)
    assert (c["second_lower"], c["second_higher"], c["within_one"]) == (1, 1, 1)
    assert c["missing"]["glm53_flash"] == {"missing: truncated_reply": 1}
    rr = out["groups"]["a/gemini38_flash/client"]["run_to_run"]
    assert rr["worlds_with_both"] == 1 and rr["mean_abs_gap"] == pytest.approx(20.0)


def test_the_accounting_balances_and_qualifies_the_cost() -> None:
    from aeread_families.datacenter_development import risk_allocation_publication as pub

    plan = {"plans": [{"cells": [{}] * 3}]}
    records = [{"cell_key": "a", "status": "ok", "receipt_sha256": "1", "cost_usd": 0.01, "calls_outcome_unknown": 0},
               {"cell_key": "b", "status": "invalid_measurement", "receipt_sha256": "2", "cost_usd": 0.002, "calls_outcome_unknown": 1,
                "error": "ProviderFailure: transport"}]
    rows = [{"valid": True, "world": "w", "twin_of": None, "case_id": "c"}, {"valid": False, "world": "w", "twin_of": None, "case_id": "d"}]
    acc = pub.accounting(plan, records, rows)
    assert (acc["planned_cells"], acc["completed_cells"], acc["operational_failure_cells"], acc["not_attempted_cells"]) == (3, 1, 1, 1)
    assert acc["cost_qualifier"] == "lower_bound" and acc["total_cost_usd"] == pytest.approx(0.012) and acc["replay_verified"] is True
    assert not any(acc[k] for k in ("winner_claim_allowed", "inferential_model_ranking_allowed", "causal_condition_effect_allowed"))
