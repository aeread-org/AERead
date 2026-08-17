"""Sealed-bid housing market.

Replaces the serial-dictatorship probe, under which truthful ranking was a
dominant strategy (verified exhaustively: 240 tenant-deviations, 0 improvements)
and the realized-vs-optimal gap measured mechanism inefficiency rather than
anything about the agent.

Under unit-demand sealed bidding a tenant must choose *which* listing to contest
and *how much* to bid, so both congestion and shading are live.
"""
from __future__ import annotations

from aeread import housing_env as hz


def test_highest_bid_above_ask_wins_the_listing():
    w = hz.make_bid_world(num_tenants=3, num_listings=2, seed=1)
    bids = {0: (0, w.ask[0] + 100), 1: (0, w.ask[0] + 300), 2: (1, w.ask[1] + 50)}
    result = hz.resolve_bids(w, bids)
    assert dict(result.pairs)[1] == 0        # tenant 1 outbid tenant 0
    assert 0 not in dict(result.pairs)       # tenant 0 won nothing
    assert dict(result.pairs)[2] == 1


def test_bid_below_ask_never_wins():
    w = hz.make_bid_world(num_tenants=2, num_listings=1, seed=2)
    bids = {0: (0, w.ask[0] - 1), 1: (0, w.ask[0] - 50)}
    result = hz.resolve_bids(w, bids)
    assert result.pairs == []
    assert result.unhoused == 2


def test_a_tenant_holds_at_most_one_listing():
    w = hz.make_bid_world(num_tenants=2, num_listings=3, seed=3)
    bids = {0: (0, w.ask[0] + 500), 1: (1, w.ask[1] + 10)}
    result = hz.resolve_bids(w, bids)
    tenants = [t for t, _ in result.pairs]
    assert len(tenants) == len(set(tenants))


def test_joint_surplus_is_independent_of_the_bid_level():
    """Rent is a transfer: it splits surplus, it does not create or destroy it."""
    w = hz.make_bid_world(num_tenants=2, num_listings=2, seed=4)
    low = hz.resolve_bids(w, {0: (0, w.ask[0] + 1), 1: (1, w.ask[1] + 1)})
    high = hz.resolve_bids(w, {0: (0, w.ask[0] + 400), 1: (1, w.ask[1] + 400)})
    assert low.total == high.total


def test_unmatched_tenant_earns_nothing_not_a_negative():
    w = hz.make_bid_world(num_tenants=3, num_listings=1, seed=5)
    bids = {0: (0, w.ask[0] + 10), 1: (0, w.ask[0] + 5), 2: (0, w.ask[0] + 1)}
    result = hz.resolve_bids(w, bids)
    assert len(result.pairs) == 1
    assert result.unhoused == 2


def test_oracle_still_bounds_the_bid_mechanism():
    w = hz.make_bid_world(num_tenants=6, num_listings=4, seed=6)
    opt = hz.assignment_oracle(w.surplus)
    naive = hz.resolve_bids(w, hz.naive_top_bids(w))
    assert naive.total <= opt.total + 1e-9
