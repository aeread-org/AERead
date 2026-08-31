"""Attribute-derived valuations with per-tenant weights.

The agent is given its own weight vector and the listing attributes, and must
compute what each listing is worth to it. Ground truth is known exactly, so
adherence to its own preference function is measurable.

Adherence is scored on the reported VALUATION, never on the choice: an agent that
values a listing correctly and then bids elsewhere to avoid competition is playing
well, not miscomputing.
"""
from __future__ import annotations

from aeread.housing_v1 import environment as hz


def test_each_tenant_gets_a_different_weight_vector():
    w = hz.make_attr_world(num_tenants=6, num_listings=4, seed=1)
    vectors = [tuple(round(x, 6) for x in w.weights[t]) for t in range(6)]
    assert len(set(vectors)) == 6


def test_weights_are_a_normalised_distribution():
    w = hz.make_attr_world(num_tenants=6, num_listings=4, seed=2)
    for t in range(6):
        assert abs(sum(w.weights[t]) - 1.0) < 1e-9
        assert all(x >= 0 for x in w.weights[t])


def test_value_is_reproducible_for_a_seed():
    a = hz.make_attr_world(6, 4, seed=3)
    b = hz.make_attr_world(6, 4, seed=3)
    assert a.values == b.values
    assert a.weights == b.weights


def test_public_asks_are_not_private_landlord_costs():
    w = hz.make_attr_world(6, 4, seed=3)
    assert any(ask != cost for ask, cost in zip(w.ask, w.costs))


def test_value_follows_the_weights_not_a_hidden_draw():
    """A tenant that only cares about campus distance must prefer the closer listing."""
    w = hz.make_attr_world(6, 4, seed=4)
    campus_only = [1.0, 0.0, 0.0, 0.0, 0.0]
    order = sorted(range(w.num_listings), key=lambda l: w.listings[l].minutes_to_campus)
    near, far = order[0], order[-1]
    v_near = hz.valuation(w, campus_only, near)
    v_far = hz.valuation(w, campus_only, far)
    assert v_near > v_far


def test_attribute_scores_match_the_documented_formulas():
    w = hz.make_attr_world(6, 4, seed=5)
    l = w.listings[0]
    s = hz.attribute_scores(l)
    assert abs(s["campus"] - (10 - l.minutes_to_campus / 5)) < 1e-9
    assert abs(s["safety"] - (10 - l.crime_index)) < 1e-9
    assert abs(s["groceries"] - (10 - l.minutes_to_groceries / 3)) < 1e-9
    assert abs(s["room"] - min(10.0, 2.5 * l.beds + 2.5 * l.baths)) < 1e-9


def test_perfect_report_scores_full_adherence():
    w = hz.make_attr_world(6, 4, seed=6)
    truth = {l: w.values[0][l] for l in range(w.num_listings)}
    a = hz.adherence(w, tenant=0, reported=truth)
    assert a["rank_agreement"] == 1.0
    assert a["mean_abs_error"] < 1e-6


def test_reversed_report_scores_zero_rank_agreement():
    w = hz.make_attr_world(6, 4, seed=7)
    order = sorted(range(w.num_listings), key=lambda l: w.values[0][l])
    reversed_map = {l: w.values[0][order[-1 - i]] for i, l in enumerate(order)}
    a = hz.adherence(w, tenant=0, reported=reversed_map)
    assert a["rank_agreement"] < 0.5


def test_adherence_ignores_a_constant_offset_in_ranking():
    """Getting the ordering right but the level wrong is a different error."""
    w = hz.make_attr_world(6, 4, seed=8)
    shifted = {l: w.values[0][l] + 500.0 for l in range(w.num_listings)}
    a = hz.adherence(w, tenant=0, reported=shifted)
    assert a["rank_agreement"] == 1.0
    assert a["mean_abs_error"] > 400.0


def test_attr_world_still_produces_a_scoreable_surplus_matrix():
    w = hz.make_attr_world(6, 4, seed=9)
    opt = hz.assignment_oracle(w.surplus)
    assert len(w.surplus) == 6 and len(w.surplus[0]) == 4
    assert opt.total >= 0.0
