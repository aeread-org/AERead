"""Assignment-game oracle and world generator for the housing case.

The oracle is the transferable-utility assignment game: max-weight bipartite
matching on the surplus matrix. Deferred acceptance is deliberately not used --
DA assumes non-transferable utility, and rent here is negotiable.
"""
from __future__ import annotations

from aeread.housing_v1 import environment as hz


def test_oracle_picks_the_max_weight_pairing_not_the_greedy_one():
    # Greedy gives t0 its best (l0, 10) then t1 must take l1 (1) => 11.
    # Max-weight pairs t0->l1 (9) and t1->l0 (9) => 18.
    surplus = [
        [10.0, 9.0],
        [9.0, 1.0],
    ]
    result = hz.assignment_oracle(surplus)
    assert result.total == 18.0
    assert sorted(result.pairs) == [(0, 1), (1, 0)]


def test_oracle_never_assigns_a_negative_surplus_pair():
    surplus = [
        [5.0, -3.0],
        [-2.0, -1.0],
    ]
    result = hz.assignment_oracle(surplus)
    assert result.pairs == [(0, 0)]
    assert result.total == 5.0


def test_oracle_leaves_tenants_unhoused_when_listings_are_scarce():
    surplus = [[4.0], [3.0], [2.0]]  # 3 tenants, 1 listing
    result = hz.assignment_oracle(surplus)
    assert len(result.pairs) == 1
    assert result.pairs == [(0, 0)]
    assert result.unhoused == 2


def test_world_is_deterministic_for_a_seed():
    a = hz.make_housing_world(num_tenants=6, num_listings=4, seed=11)
    b = hz.make_housing_world(num_tenants=6, num_listings=4, seed=11)
    assert a.surplus == b.surplus
    assert a.listings == b.listings


def test_world_shape_matches_requested_market_size():
    w = hz.make_housing_world(num_tenants=6, num_listings=4, seed=3)
    assert len(w.surplus) == 6
    assert all(len(row) == 4 for row in w.surplus)
    assert len(w.listings) == 4


def test_tightness_forces_unhoused_tenants():
    w = hz.make_housing_world(num_tenants=6, num_listings=4, seed=3)
    result = hz.assignment_oracle(w.surplus)
    # At most M can be housed, so at least N-M are not.
    assert result.unhoused >= 2


def test_selfish_baseline_is_scored_against_the_same_oracle():
    w = hz.make_housing_world(num_tenants=6, num_listings=4, seed=7)
    rankings = hz.selfish_rankings(w)
    realized = hz.resolve(w, rankings)
    optimal = hz.assignment_oracle(w.surplus)
    assert 0.0 <= realized.total <= optimal.total


def test_resolve_gives_each_listing_to_at_most_one_tenant():
    w = hz.make_housing_world(num_tenants=6, num_listings=4, seed=5)
    # Every tenant demands listing 0 first.
    rankings = {t: [0, 1, 2, 3] for t in range(6)}
    realized = hz.resolve(w, rankings)
    listings_used = [l for _, l in realized.pairs]
    assert len(listings_used) == len(set(listings_used))
