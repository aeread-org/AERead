"""Tests for the D11 scripted frozen-seller counterpart (deterministic, zero LLM calls)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402
from aeread import exchange_counterpart_frozen as fz  # noqa: E402

CONFIG_PATH = ROOT / "configs" / "exchange_economy" / "bundle_under_budget_trip3.json"


def _world():
    return ex.make_world_from_config(ex.load_experiment_config(CONFIG_PATH))


def _transcript(round_index):
    return ex.RoundTranscript(round_index, 1, "proposal", {}, "final")


def _sale_mechanism(world, seller_id, price, quantity=1):
    component, _ = fz.seller_component_and_cost(world, seller_id)
    return ex.CompiledMechanism(
        proposer_id=1, label="sale", summary="unit sale",
        transfers=[
            ex.Transfer(from_agent=seller_id, to_agent=1, resource=component, quantity=quantity),
            ex.Transfer(from_agent=1, to_agent=seller_id,
                        resource=world.bundle_utility.money_resource, quantity=price),
        ],
        consenting_agents=[1, seller_id], confidence=1.0,
    )


def test_seller_detection_and_costs():
    world = _world()
    assert fz.bundle_seller_ids(world) == [2, 3, 4, 5, 6, 7]
    component, cost = fz.seller_component_and_cost(world, 2)
    assert component == 1
    assert cost == world.preferences[1][0]
    with pytest.raises(ValueError):
        fz.seller_component_and_cost(world, 1)  # the buyer holds no component


def test_concession_schedule_decays_to_floor_and_never_below_cost():
    world = _world()
    params = fz.FrozenSellerParams()
    _, cost = fz.seller_component_and_cost(world, 2)

    asks = [fz.seller_ask(world, 2, t, params) for t in range(1, 31)]
    assert all(a >= b for a, b in zip(asks, asks[1:]))  # monotone concession
    assert asks[0] == pytest.approx(cost * (1 + params.margin_start), abs=0.01)
    assert asks[-1] == pytest.approx(cost * (1 + params.margin_floor), abs=0.02)  # converged to floor
    assert all(a > cost for a in asks)  # never below reservation cost


def test_consent_rule_accepts_at_ask_and_refuses_below_margin():
    world = _world()
    params = fz.FrozenSellerParams()
    seller = 2
    _, cost = fz.seller_component_and_cost(world, seller)

    for t in (1, 3, 10):
        ask = fz.seller_ask(world, seller, t, params)
        accept, delta, required = fz.seller_accepts(
            world, seller, _sale_mechanism(world, seller, ask), t, params)
        assert accept, f"round {t}: ask price must satisfy the seller's own rule"
        assert delta == pytest.approx(ask - cost)

        just_below = required + cost - 0.5  # price giving delta slightly under required gain
        accept_low, _, _ = fz.seller_accepts(
            world, seller, _sale_mechanism(world, seller, just_below), t, params)
        assert not accept_low


def test_consent_rule_never_accepts_negative_delta():
    world = _world()
    seller = 2
    _, cost = fz.seller_component_and_cost(world, seller)
    accept, delta, _ = fz.seller_accepts(
        world, seller, _sale_mechanism(world, seller, cost - 5.0), 50,  # late round, floor margin
        fz.FrozenSellerParams(margin_floor=0.0))
    assert delta < 0
    assert not accept


def test_early_round_demands_more_than_late_round():
    world = _world()
    seller = 6
    params = fz.FrozenSellerParams()
    _, cost = fz.seller_component_and_cost(world, seller)
    mid_price = cost * 1.15  # above floor margin, below opening margin

    accept_early, _, _ = fz.seller_accepts(world, seller, _sale_mechanism(world, seller, mid_price), 1, params)
    accept_late, _, _ = fz.seller_accepts(world, seller, _sale_mechanism(world, seller, mid_price), 8, params)
    assert not accept_early
    assert accept_late


def test_policy_overrides_are_scripted_and_json_parseable():
    world = _world()
    policy = fz.FrozenSellerCounterpartPolicy()
    transcript = _transcript(2)

    response = policy.respond_text(world, 3, transcript, [])
    assert "PUBLIC ACTION" in response
    assert str(fz.seller_ask(world, 3, 2)) in response
    assert policy.call_records == []  # zero LLM calls for seller roles

    texts = policy.response_texts(world, [2, 3], transcript, [])
    assert set(texts) == {2, 3}

    ask = fz.seller_ask(world, 4, 2)
    acceptance = policy.private_acceptance_text(
        world, 4, transcript, _sale_mechanism(world, 4, ask), [])
    parsed = json.loads(acceptance)
    assert parsed["approve"] is True
    assert parsed["claimed_delta_sign"] == "positive"

    refusal = policy.private_acceptance_text(
        world, 4, transcript, _sale_mechanism(world, 4, 1.0), [])
    assert json.loads(refusal)["approve"] is False
    assert policy.call_records == []


def test_scripted_acceptance_survives_enforce_private_acceptance():
    world = _world()
    policy = fz.FrozenSellerCounterpartPolicy()
    transcript = _transcript(1)
    seller = 2
    ask = fz.seller_ask(world, seller, 1)
    mechanism = _sale_mechanism(world, seller, ask)

    # the buyer is also debited (it pays money), so both debited agents need texts
    texts = {
        seller: policy.private_acceptance_text(world, seller, transcript, mechanism, []),
        1: '{"claimed_delta_sign": "positive", "counterpart_transfers_present": true, '
           '"same_bundle_authorized": true, "approve": true, "reason": "buyer accepts"}',
    }
    verified, audits = ex.enforce_private_acceptance(mechanism, texts, world=world)
    assert verified.transfers == mechanism.transfers  # consent upheld, nothing trimmed
    seller_audit = next(a for a in audits if a.agent_id == seller)
    assert seller_audit.approve is True


def test_panel_floor_asks_stay_within_budget():
    """Non-degeneracy: at floor margins the min-cost sellers still fit the budget."""
    world = _world()
    params = fz.FrozenSellerParams()
    oracle = ex.solve_bundle_min_cost(world)
    late_round = 50
    total_floor_ask = sum(
        fz.seller_ask(world, seller, late_round, params)
        for seller in oracle.assignment.values()
    )
    assert total_floor_ask <= world.bundle_utility.budget


def test_role_prompt_contains_contract_but_forbids_leaking_cost():
    world = _world()
    prompt = fz.frozen_seller_role_prompt(world, 2)
    _, cost = fz.seller_component_and_cost(world, 2)
    assert str(cost) in prompt  # the model must know its own private value
    assert "NEVER" in prompt
    assert "utility delta" in prompt.lower() or "delta" in prompt  # forced own-delta computation
    assert "Do not coordinate" in prompt
