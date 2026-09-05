"""Frozen P0 contract for the multi-round housing market."""
from __future__ import annotations

import math

import pytest

from aeread_families.housing import environment as hz


def _market(seed=1, tenants=3, listings=2, rounds=4):
    return hz.HousingMarket(hz.make_bid_world(tenants, listings, seed=seed), rounds=rounds)


def _accepted_hold(market: hz.HousingMarket, tenant: int = 0, listing: int = 0):
    rent = market.world.ask[listing] + 10
    contact = market.submit_offers({tenant: (listing, rent)})
    response = market.submit_responses({listing: {tenant: ("accept", None)}})
    return contact, response.holds[tenant]


def test_contact_returns_typed_verdicts_and_routes_only_to_addressed_landlord():
    m = _market()
    result = m.submit_offers({0: (0, m.world.ask[0] + 10), 1: (1, m.world.ask[1] + 10)})
    assert result.phase == "contact"
    assert result.verdicts[0].outcome == "applied"
    assert [offer.tenant_id for offer in result.inbox[0]] == [0]
    assert [offer.tenant_id for offer in result.inbox[1]] == [1]


def test_contact_snapshot_cannot_be_mutated_through_the_returned_batch():
    m = _market()
    result = m.submit_offers({0: (0, m.world.ask[0] + 10)})
    assert isinstance(result.inbox[0], tuple)
    result.inbox.clear()
    assert len(m.landlord_observation(0)["inbox"]) == 1


def test_phase_order_is_strict_and_repeated_application_does_not_mutate_state():
    m = _market()
    with pytest.raises(hz.PhaseOrderError):
        m.submit_responses({})
    m.submit_offers({})
    with pytest.raises(hz.PhaseOrderError):
        m.submit_offers({})
    assert m.phase == "respond"
    assert m.round_index == 0


@pytest.mark.parametrize(
    "bad_action, reason",
    [
        ((99, 2000.0), "unknown_listing"),
        ((0, float("nan")), "invalid_rent"),
        ((0, float("inf")), "invalid_rent"),
        ((0, -1.0), "invalid_rent"),
        (None, "missing_action"),
    ],
)
def test_invalid_contact_becomes_typed_pass_without_an_offer(bad_action, reason):
    m = _market()
    result = m.submit_offers({0: bad_action})
    assert result.verdicts[0].outcome == "pass"
    assert result.verdicts[0].reason == reason
    assert result.inbox == {}


def test_response_cannot_create_a_hold_for_a_nonexistent_offer():
    m = _market()
    m.submit_offers({0: (0, m.world.ask[0] + 10)})
    result = m.submit_responses({0: {1: ("accept", None)}})
    assert result.holds == {}
    assert result.verdicts[0].outcome == "pass"
    assert result.verdicts[0].reason == "unknown_offer"


def test_landlord_has_one_binding_hold_capacity_for_accepts_and_counters():
    m = _market()
    m.submit_offers({0: (0, m.world.ask[0] + 10), 1: (0, m.world.ask[0] + 20)})
    result = m.submit_responses(
        {0: {0: ("accept", None), 1: ("counter", m.world.ask[0] + 30)}}
    )
    assert result.holds == {}
    assert result.verdicts[0].outcome == "pass"
    assert result.verdicts[0].reason == "hold_capacity_exceeded"


def test_hold_is_immutable_and_signing_uses_only_its_id_and_frozen_terms():
    m = _market()
    _, hold = _accepted_hold(m)
    assert isinstance(hold, hz.Hold)
    with pytest.raises(Exception):
        hold.rent = hold.rent + 500
    result = m.submit_commits({0: ("sign", hold.hold_id)})
    assert result.verdicts[0].outcome == "applied"
    assert m.pairs == [(0, 0)]
    assert m.signed_rent[0] == hold.rent


def test_resubmitting_listing_and_rent_cannot_change_a_binding_hold():
    m = _market()
    _, hold = _accepted_hold(m)
    result = m.submit_commits({0: ("sign", hold.listing_id, hold.rent + 500)})
    assert result.verdicts[0].outcome == "pass"
    assert result.verdicts[0].reason == "invalid_commit"
    assert m.pairs == []


def test_wrong_hold_reference_is_a_pass_and_the_hold_expires_at_commit_end():
    m = _market()
    _, hold = _accepted_hold(m)
    result = m.submit_commits({0: ("sign", hold.hold_id + "-tampered")})
    assert result.verdicts[0].outcome == "pass"
    assert result.verdicts[0].reason == "unknown_hold"
    assert m.active_holds() == {}
    assert m.phase == "contact"
    assert m.round_index == 1


def test_walk_uses_hold_id_and_leaves_the_listing_open():
    m = _market()
    _, hold = _accepted_hold(m)
    m.submit_commits({0: ("walk", hold.hold_id)})
    assert m.pairs == []
    assert hold.listing_id in m.open_listings()
    assert hold.tenant_id in m.unmatched_tenants()


def test_public_board_and_private_observations_do_not_leak_reservation_costs():
    m = _market()
    assert any(not math.isclose(a, c) for a, c in zip(m.world.ask, m.world.costs))
    assert "orientation" in m.board()[0]
    assert all("cost" not in row and "reservation_cost" not in row for row in m.board())

    tenant = m.tenant_observation(0)
    assert tenant["private_values"] == m.world.values[0]
    assert "costs" not in tenant
    assert "all_values" not in tenant

    m.submit_offers({0: (0, m.world.ask[0] + 10), 1: (1, m.world.ask[1] + 10)})
    landlord = m.landlord_observation(0)
    assert landlord["private_cost"] == m.world.costs[0]
    assert {offer.listing_id for offer in landlord["inbox"]} == {0}
    assert all(offer.tenant_id != 1 for offer in landlord["inbox"])


def test_attribute_tenant_observation_exposes_weights_and_formula_not_derived_values():
    m = hz.HousingMarket(hz.make_attr_world(3, 2, seed=9), rounds=2)
    obs = m.tenant_observation(0)
    assert obs["private_weights"] == m.world.weights[0]
    assert obs["valuation_formula"]["attributes"] == hz.ATTRIBUTES
    assert "private_values" not in obs
    assert "values" not in obs


def test_terminal_economics_preserve_prices_payoffs_welfare_and_ir_violations():
    listing = hz.Listing(0, 100, 1, 1, 10, 2.0, 5)
    world = hz.BidWorld(
        listings=[listing], values=[[100.0]], costs=[120.0], ask=[100.0]
    )
    m = hz.HousingMarket(world, rounds=1)
    m.submit_offers({0: (0, 110.0)})
    response = m.submit_responses({0: {0: ("accept", None)}})
    m.submit_commits({0: ("sign", response.holds[0].hold_id)})

    economics = m.economics()
    assert economics.signed_rents == {0: 110.0}
    assert economics.tenant_payoffs == {0: -10.0}
    assert economics.landlord_payoffs == {0: -10.0}
    assert economics.social_welfare == -20.0
    assert set(economics.ir_violations) == {"tenant:0", "landlord:0"}
    assert sum(economics.tenant_payoffs.values()) + sum(economics.landlord_payoffs.values()) == economics.social_welfare


def test_board_marks_leased_listings():
    m = _market()
    _, hold = _accepted_hold(m)
    m.submit_commits({0: ("sign", hold.hold_id)})
    board = m.board()
    assert board[0]["status"] == "LEASED"
    assert board[1]["status"] == "OPEN"


def test_market_stops_after_the_round_budget():
    m = _market(rounds=2)
    for _ in range(2):
        m.submit_offers({})
        m.submit_responses({})
        m.submit_commits({})
    assert m.finished
    assert m.phase == "finished"


def test_scored_result_uses_the_same_oracle_as_the_one_shot_market():
    w = hz.make_bid_world(6, 4, seed=3)
    result = hz.run_scripted_market(w, rounds=4, strategy="adaptive")
    optimum = hz.assignment_oracle(w.surplus)
    assert result.total <= optimum.total + 1e-9


def test_scripted_strategies_are_distinct_and_oracle_bounded_over_seeds():
    """Both policies are diagnostics; corrected hold capacity need not rank them."""
    differences = []
    for seed in range(40):
        w = hz.make_bid_world(6, 4, seed=seed)
        opt = hz.assignment_oracle(w.surplus)
        if opt.total <= 0:
            continue
        adaptive = hz.run_scripted_market(w, 4, "adaptive")
        naive = hz.run_scripted_market(w, 4, "naive")
        assert 0.0 <= adaptive.total <= opt.total + 1e-9
        assert 0.0 <= naive.total <= opt.total + 1e-9
        differences.append(adaptive.total - naive.total)
    assert any(abs(difference) > 1e-9 for difference in differences)
