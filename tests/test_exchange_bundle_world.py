"""Tests for the bundle-under-budget env core (Leontief buyer + reservation-cost sellers)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402

CONFIG_PATH = (
    ROOT / "cases" / "exchange_v1" / "specialized" / "bundle_under_budget_trip3.json"
)


def _config():
    return ex.load_experiment_config(CONFIG_PATH)


def _world():
    return ex.make_world_from_config(_config())


def _buy_all_mechanism(world, prices):
    """Buy one unit of each required component from its cheapest seller at the given price map."""
    spec = world.bundle_utility
    oracle = ex.solve_bundle_min_cost(world)
    transfers = []
    for component, seller in oracle.assignment.items():
        transfers.append(ex.Transfer(from_agent=seller, to_agent=spec.buyer_agent,
                                     resource=component, quantity=1))
        transfers.append(ex.Transfer(from_agent=spec.buyer_agent, to_agent=seller,
                                     resource=spec.money_resource, quantity=prices[component]))
    return ex.CompiledMechanism(
        proposer_id=spec.buyer_agent, label="buy_bundle", summary="buy all components",
        transfers=transfers,
        consenting_agents=[spec.buyer_agent, *oracle.assignment.values()],
        confidence=1.0,
    ), oracle


def test_config_round_trips_bundle_spec_and_seller_layout():
    config = _config()
    assert config.world_type == "bundle_under_budget"
    spec = config.bundle_spec
    assert spec.buyer_agent == 1
    assert spec.required_components == [1, 2, 3]
    assert spec.bundle_value == 120.0
    assert spec.budget == 100.0
    layout = config.seller_layout
    assert layout.component_by_seller == {2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3}
    assert layout.seller_cost_range == (20.0, 30.0)


def test_builder_endowments_match_spec():
    world = _world()
    spec = world.bundle_utility
    money = spec.money_resource - 1
    # buyer: budget units of money, no components
    assert world.allocation[0][money] == spec.budget
    assert all(world.allocation[0][c - 1] == 0 for c in spec.required_components)
    # each seller holds only its component; cost within range; money valued 1.0 by all
    for seller_id, component in _config().seller_layout.component_by_seller.items():
        row = world.allocation[seller_id - 1]
        assert row[component - 1] == 10
        assert sum(row) == 10
        cost = world.preferences[seller_id - 1][component - 1]
        assert 20.0 <= cost <= 30.0
    assert all(world.preferences[i][money] == 1.0 for i in range(world.num_agents))
    assert world.money_good_index == money


def test_builder_is_deterministic_per_seed():
    assert _world().preferences == _world().preferences


def test_leontief_buyer_utility_all_or_nothing():
    world = _world()
    spec = world.bundle_utility
    assert world.utility(1) == pytest.approx(spec.budget)  # money only, no bundle

    row = world.allocation[0][:]
    row[0], row[1] = 1, 1  # two of three components: still nothing
    assert ex.agent_utility_for_bundle_row(world, 0, row) == pytest.approx(spec.budget)

    row[2] = 1  # final component completes the bundle: jump by exactly V
    assert ex.agent_utility_for_bundle_row(world, 0, row) == pytest.approx(spec.budget + spec.bundle_value)


def test_seller_utility_is_quasi_linear_reservation_cost():
    world = _world()
    cost = world.preferences[1][0]  # seller a2 holds component 1
    above, below = cost + 1.0, cost - 1.0
    for price, sign in ((above, 1), (below, -1)):
        mechanism = ex.CompiledMechanism(
            proposer_id=2, label="sale", summary="one unit",
            transfers=[
                ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1),
                ex.Transfer(from_agent=1, to_agent=2, resource=4, quantity=price),
            ],
            consenting_agents=[1, 2], confidence=1.0,
        )
        delta = ex.utility_delta_for_mechanism(world, mechanism, 2)
        assert delta == pytest.approx(sign * 1.0)


def test_complete_within_budget_bundle_scores_v_minus_spend():
    world = _world()
    spec = world.bundle_utility
    oracle_prices = {c: 30.0 for c in spec.required_components}  # above every cost in [20, 30]
    mechanism, oracle = _buy_all_mechanism(world, oracle_prices)
    initial = world.copy_allocation()

    event = ex.apply_compiled_mechanism(world, mechanism)
    assert event.applied is True
    assert event.individually_rational is True
    spend = sum(oracle_prices.values())
    assert event.agent_deltas[1] == pytest.approx(spec.bundle_value - spend)
    for component, seller in oracle.assignment.items():
        cost = world.preferences[seller - 1][component - 1]
        assert event.agent_deltas[seller] == pytest.approx(30.0 - cost)

    metrics = ex.summarize_bundle_episode(initial, world)
    assert metrics.bundle_completed is True
    assert metrics.spend == pytest.approx(spend)
    assert metrics.over_budget is False
    assert metrics.stranded_spend == 0.0
    assert metrics.welfare_gain == pytest.approx(spec.bundle_value - oracle.min_cost)
    assert metrics.welfare_ratio == pytest.approx(1.0)


def test_incomplete_bundle_scores_zero_and_strands_spend():
    world = _world()
    spec = world.bundle_utility
    mechanism = ex.CompiledMechanism(
        proposer_id=1, label="partial", summary="two of three",
        transfers=[
            ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1),
            ex.Transfer(from_agent=1, to_agent=2, resource=4, quantity=30.0),
            ex.Transfer(from_agent=4, to_agent=1, resource=2, quantity=1),
            ex.Transfer(from_agent=1, to_agent=4, resource=4, quantity=30.0),
        ],
        consenting_agents=[1, 2, 4], confidence=1.0,
    )
    initial = world.copy_allocation()
    event = ex.apply_compiled_mechanism(world, mechanism)
    assert event.applied is True
    assert event.agent_deltas[1] == pytest.approx(-60.0)  # components contribute nothing

    metrics = ex.summarize_bundle_episode(initial, world)
    assert metrics.bundle_completed is False
    assert metrics.stranded_spend == pytest.approx(60.0)
    assert metrics.over_budget is False


def test_min_cost_oracle_picks_cheapest_seller_per_component():
    world = _world()
    oracle = ex.solve_bundle_min_cost(world)
    for component, chosen in oracle.assignment.items():
        chosen_cost = world.preferences[chosen - 1][component - 1]
        rivals = [
            world.preferences[i][component - 1]
            for i in range(1, world.num_agents)
            if world.allocation[i][component - 1] >= 1
        ]
        assert chosen_cost == min(rivals)
    assert oracle.feasible_within_budget is True
    assert oracle.optimal_welfare_gain == pytest.approx(
        world.bundle_utility.bundle_value - oracle.min_cost)
    assert oracle.optimal_welfare_gain > 0


def test_builder_rejects_invalid_value_budget_cost_ordering():
    config = _config()

    bad_value = ex.replace(config, bundle_spec=ex.replace(config.bundle_spec, bundle_value=90.0))
    with pytest.raises(ValueError, match="must exceed budget"):
        ex.make_world_from_config(bad_value)

    bad_budget = ex.replace(config, bundle_spec=ex.replace(config.bundle_spec, budget=50.0, bundle_value=120.0))
    with pytest.raises(ValueError, match="min-cost"):
        ex.make_world_from_config(bad_budget)


def test_social_optimum_moves_bundle_to_buyer():
    world = _world()
    spec = world.bundle_utility
    optimum = ex.social_optimum(world)
    for component in spec.required_components:
        assert optimum[0][component - 1] >= 1
    gain = ex.total_welfare(world, optimum) - ex.total_welfare(world)
    assert gain == pytest.approx(ex.solve_bundle_min_cost(world).optimal_welfare_gain)
    assert ex.greedy_social_optimum(world) == optimum
