"""mc_wbayes for the bundle-under-budget world (oracle carve-out slice 2).

Tests the information-constrained achievable computation directly on a stub world (only
bundle_utility + seller_layout + num_agents are read), plus the spec invariants.
"""
from __future__ import annotations

import types

from aeread import exchange_economy as ex  # noqa: E402  (conftest puts sprint/ on the path)
from aeread import bundle_bayes_oracle as bb  # noqa: E402


def _stub_world(required, sellers_by_component, cost_range, bundle_value, budget, num_agents):
    spec = ex.BundleUtilitySpec(
        buyer_agent=1,
        money_resource=len(required) + 1,
        required_components=list(required),
        bundle_value=bundle_value,
        budget=budget,
    )
    comp_by_seller = {s: comp for comp, sellers in sellers_by_component.items() for s in sellers}
    layout = ex.SellerLayoutConfig(component_by_seller=comp_by_seller, seller_cost_range=cost_range)
    return types.SimpleNamespace(bundle_utility=spec, seller_layout=layout, num_agents=num_agents)


TRIP3 = dict(required=[1, 2, 3], sellers_by_component={1: [2, 3], 2: [4, 5], 3: [6, 7]},
             cost_range=(20.0, 30.0), bundle_value=120.0, budget=100.0, num_agents=7)


def test_wbayes_is_nonnegative_and_bounded_by_expected_wstar():
    w = _stub_world(**TRIP3)
    wb, ci = bb.bundle_bayes_optimal_welfare(w, seed=1)
    ews = bb.expected_wstar(w, seed=2)
    assert wb >= 0.0
    assert wb <= ews + 1.0                       # W_bayes <= E[W*] (info-constrained <= full info)
    assert ci[0] <= wb + 2.0 <= ci[1] + 4.0      # CI brackets the point estimate (loose, MC noise)


def test_high_value_with_competition_has_a_tiny_information_gap():
    # V=120 >> max total cost (90) and two sellers per component: the buyer can guarantee
    # acquisition and competition recovers the min cost, so W_bayes ~= E[W*].
    w = _stub_world(**TRIP3)
    wb, _ = bb.bundle_bayes_optimal_welfare(w, seed=1)
    ews = bb.expected_wstar(w, seed=1)
    assert ews - wb < 3.0


def test_wbayes_detects_a_real_information_gap_without_competition():
    # 2 required components, ONE seller each, wide costs, tight value: the info-constrained
    # completion region is a rectangle, the profitable region a triangle -> a genuine gap.
    w = _stub_world(required=[1, 2], sellers_by_component={1: [2], 2: [3]},
                    cost_range=(0.0, 10.0), bundle_value=12.0, budget=20.0, num_agents=3)
    wb, _ = bb.bundle_bayes_optimal_welfare(w, seed=3)
    ews = bb.expected_wstar(w, seed=3)
    assert wb >= 0.0
    assert wb <= ews + 0.5
    assert ews - wb > 0.15                        # delta_unc > 0: information genuinely matters


def test_single_component_offer_threshold_matches_full_info():
    # With one component + one seller the optimal threshold offer replicates full-info
    # completion (complete iff cost <= value), so there is no information gap.
    w = _stub_world(required=[1], sellers_by_component={1: [2]},
                    cost_range=(0.0, 10.0), bundle_value=8.0, budget=10.0, num_agents=2)
    wb, _ = bb.bundle_bayes_optimal_welfare(w, seed=5)
    ews = bb.expected_wstar(w, seed=5)
    assert abs(wb - ews) < 0.4                    # ~equal (analytic optimum is p=value=8 -> 3.2)


def test_unsupported_world_raises_for_graceful_fallback():
    import pytest
    bad = types.SimpleNamespace(bundle_utility=None, seller_layout=None, num_agents=3)
    with pytest.raises(ValueError):
        bb.bundle_bayes_optimal_welfare(bad)


def test_expected_wstar_floors_value_destroying_completions():
    # Review Q1: with a small value vs wide costs, some draws have value < total cost. The
    # ceiling must floor those at 0 (a rational full-info buyer won't complete at a loss), so
    # E[W*] stays >= 0 and W_bayes stays within [0, E[W*]] (no negative ceiling, no over-credit).
    w = _stub_world(required=[1, 2], sellers_by_component={1: [2], 2: [3]},
                    cost_range=(0.0, 10.0), bundle_value=6.0, budget=20.0, num_agents=3)
    ews = bb.expected_wstar(w, seed=7)
    wb, _ = bb.bundle_bayes_optimal_welfare(w, seed=7)
    assert ews >= 0.0
    assert 0.0 <= wb <= ews + 0.3
