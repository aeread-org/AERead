"""Multi-round housing market: contact -> respond -> commit.

Step-wise state machine so a scripted policy and an LLM driver drive it the same
way. Only the final allocation is scored, so the oracle is unchanged by the
multi-round structure.
"""
from __future__ import annotations

from aeread import housing_env as hz


def _market(seed=1, tenants=3, listings=2, rounds=4):
    return hz.HousingMarket(hz.make_bid_world(tenants, listings, seed=seed), rounds=rounds)


def test_offers_reach_only_the_addressed_landlord():
    m = _market()
    inbox = m.submit_offers({0: (0, m.world.ask[0] + 10), 1: (1, m.world.ask[1] + 10)})
    assert [t for t, _ in inbox[0]] == [0]
    assert [t for t, _ in inbox[1]] == [1]


def test_landlord_may_accept_at_most_one_offer_per_round():
    m = _market()
    m.submit_offers({0: (0, m.world.ask[0] + 10), 1: (0, m.world.ask[0] + 20)})
    with __import__("pytest").raises(ValueError):
        m.submit_responses({0: {0: ("accept", None), 1: ("accept", None)}})


def test_signing_matches_the_tenant_and_removes_the_listing():
    m = _market()
    rent = m.world.ask[0] + 10
    m.submit_offers({0: (0, rent)})
    m.submit_responses({0: {0: ("accept", None)}})
    m.submit_commits({0: ("sign", 0, rent)})
    assert (0, 0) in m.pairs
    assert 0 not in m.open_listings()
    assert 0 not in m.unmatched_tenants()


def test_walking_leaves_the_listing_open_for_others():
    m = _market()
    rent = m.world.ask[0] + 10
    m.submit_offers({0: (0, rent)})
    m.submit_responses({0: {0: ("accept", None)}})
    m.submit_commits({0: ("walk",)})
    assert m.pairs == []
    assert 0 in m.open_listings()
    assert 0 in m.unmatched_tenants()


def test_a_counter_is_what_the_tenant_may_sign_at():
    m = _market()
    ask = m.world.ask[0]
    m.submit_offers({0: (0, ask + 10)})
    m.submit_responses({0: {0: ("counter", ask + 60)}})
    m.submit_commits({0: ("sign", 0, ask + 60)})
    assert (0, 0) in m.pairs
    assert m.signed_rent[0] == ask + 60


def test_board_marks_leased_listings():
    m = _market()
    rent = m.world.ask[0] + 10
    m.submit_offers({0: (0, rent)})
    m.submit_responses({0: {0: ("accept", None)}})
    m.submit_commits({0: ("sign", 0, rent)})
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


def test_scored_result_uses_the_same_oracle_as_the_one_shot_market():
    w = hz.make_bid_world(6, 4, seed=3)
    result = hz.run_scripted_market(w, rounds=4, strategy="adaptive")
    optimum = hz.assignment_oracle(w.surplus)
    assert 0.0 <= result.total <= optimum.total + 1e-9


def test_adaptive_beats_naive_over_seeds():
    """The multi-round design must reward re-targeting after a rejection."""
    adaptive = naive = 0.0
    for seed in range(40):
        w = hz.make_bid_world(6, 4, seed=seed)
        opt = hz.assignment_oracle(w.surplus)
        if opt.total <= 0:
            continue
        adaptive += hz.run_scripted_market(w, 4, "adaptive").total / opt.total
        naive += hz.run_scripted_market(w, 4, "naive").total / opt.total
    assert adaptive > naive
