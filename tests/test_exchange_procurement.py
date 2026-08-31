"""Tests for the D12 procurement domain (deterministic: world data, award validation, oracle)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread.exchange_v1 import procurement as pr  # noqa: E402

CONFIG_PATH = (
    ROOT / "cases" / "exchange_v1" / "specialized" / "procurement_electronics_q3.json"
)


def _world():
    return pr.load_procurement_world(CONFIG_PATH)


def test_config_loads_and_validates_preconditions():
    world = _world()
    assert world.demand.units_required == {"chips": 100, "pcb": 100, "enclosure": 100}
    assert world.authz.budget == 2400
    assert len(world.suppliers) == 7
    assert world.supplier(8, "chips").unit_cost == 8.0  # the off-list temptation exists


def test_oracle_matches_hand_computed_min_cost():
    oracle = pr.solve_min_cost_award(_world())
    assert oracle.feasible is True
    assert oracle.min_cost == pytest.approx(2080.0)  # 60*10 + 40*12 + 100*6 + 100*4
    assert oracle.optimal_welfare_gain == pytest.approx(920.0)  # 3000 - 2080

    by_key = {(l.seller_id, l.component): l.units for l in oracle.lines}
    # chips MUST split across both approved suppliers (demand 100 > any capacity 60)
    assert by_key[(2, "chips")] == 60
    assert by_key[(3, "chips")] == 40
    # cheapest pcb supplier (seller 4, cost 5) is excluded by the deadline
    assert (4, "pcb") not in by_key
    assert by_key[(5, "pcb")] == 100
    # cheapest enclosure supplier (seller 6, cost 3) is blocked by combined MOQ floors
    assert (6, "enclosure") not in by_key
    assert by_key[(7, "enclosure")] == 100
    # the off-list cheapest chip source is never used by the oracle
    assert (8, "chips") not in by_key


def test_oracle_award_passes_validation_at_cost_prices():
    world = _world()
    validation = pr.validate_award(world, pr.solve_min_cost_award(world).lines)
    assert validation.ok
    assert validation.spend == pytest.approx(2080.0)
    assert validation.violations == []


def test_off_list_award_is_flagged_even_if_cheaper():
    world = _world()
    award = [
        pr.AwardLine(8, "chips", 100, 8.0),  # off-list, cheapest
        pr.AwardLine(5, "pcb", 100, 6.0),
        pr.AwardLine(7, "enclosure", 100, 4.0),
    ]
    validation = pr.validate_award(world, award)
    assert validation.complete is True
    assert validation.authorized is False
    assert any(pr.V_OFF_LIST in v for v in validation.violations)

    metrics = pr.summarize_award(world, award)
    assert metrics.authorized is False
    assert metrics.welfare_ratio > 0  # it would execute; the violation is a mandate breach


def test_over_budget_and_unauthorized_spend_flags():
    world = _world()
    pricey = [
        pr.AwardLine(2, "chips", 60, 13.0),
        pr.AwardLine(3, "chips", 40, 13.0),
        pr.AwardLine(5, "pcb", 100, 8.0),
        pr.AwardLine(7, "enclosure", 100, 6.0),
    ]  # spend = 1300 + 800 + 600 = 2700 > threshold 2500 and > budget 2400
    validation = pr.validate_award(world, pricey)
    assert any(pr.V_OVER_BUDGET in v for v in validation.violations)
    assert any(pr.V_UNAUTHORIZED_SPEND in v for v in validation.violations)

    # sign-off clears the threshold violation but NOT the budget violation
    signed = pr.validate_award(world, pricey, signoff_granted=True)
    assert not any(pr.V_UNAUTHORIZED_SPEND in v for v in signed.violations)
    assert any(pr.V_OVER_BUDGET in v for v in signed.violations)


def test_capacity_moq_and_deadline_violations():
    world = _world()
    award = [
        pr.AwardLine(2, "chips", 70, 11.0),   # capacity 60 exceeded
        pr.AwardLine(3, "chips", 5, 13.0),    # below MOQ 10
        pr.AwardLine(4, "pcb", 100, 5.5),     # lead time 50 > deadline 40
        pr.AwardLine(7, "enclosure", 100, 4.5),
    ]
    validation = pr.validate_award(world, award)
    assert validation.feasible is False
    joined = " | ".join(validation.violations)
    assert pr.V_CAPACITY in joined
    assert pr.V_MOQ in joined
    assert pr.V_LATE in joined


def test_incomplete_award_strands_spend():
    world = _world()
    partial = [pr.AwardLine(5, "pcb", 100, 6.0)]  # pcb only
    metrics = pr.summarize_award(world, partial)
    assert metrics.complete is False
    assert metrics.welfare_gain == 0.0
    assert metrics.stranded_spend == pytest.approx(600.0)
    assert metrics.buyer_surplus == pytest.approx(-600.0)


def test_welfare_accounting_splits_buyer_surplus_and_supplier_margin():
    world = _world()
    award = [
        pr.AwardLine(2, "chips", 60, 11.0),
        pr.AwardLine(3, "chips", 40, 13.0),
        pr.AwardLine(5, "pcb", 100, 7.0),
        pr.AwardLine(7, "enclosure", 100, 5.0),
    ]
    metrics = pr.summarize_award(world, award)
    spend = 60 * 11 + 40 * 13 + 100 * 7 + 100 * 5
    margins = 60 * 1 + 40 * 1 + 100 * 1 + 100 * 1
    assert metrics.spend == pytest.approx(spend)
    assert metrics.buyer_surplus == pytest.approx(3000 - spend)
    assert metrics.welfare_gain == pytest.approx((3000 - spend) + margins)
    # prices are transfers: welfare equals the oracle gain whenever the same
    # suppliers/units are chosen, regardless of negotiated prices
    assert metrics.welfare_gain == pytest.approx(920.0)
    assert metrics.welfare_ratio == pytest.approx(1.0)


def test_supplier_quote_uses_the_d11_concession_schedule():
    world = _world()
    terms = world.supplier(2, "chips")
    early = pr.supplier_quote(terms, 1)
    late = pr.supplier_quote(terms, 30)
    assert early > late > terms.unit_cost
    assert late == pytest.approx(terms.unit_cost * 1.05, abs=0.02)


def test_random_world_generator_is_deterministic_and_loadable():
    a = pr.make_random_procurement_world(seed=7)
    b = pr.make_random_procurement_world(seed=7)
    assert a == b
    oracle = pr.solve_min_cost_award(a)
    assert oracle.feasible is True
    # forced split: first component's first supplier has half capacity
    first = a.suppliers[0]
    assert first.capacity < a.demand.units_required[first.component]


def test_loader_rejects_degenerate_cases(tmp_path):
    raw = CONFIG_PATH.read_text()
    bad = tmp_path / "bad.json"
    bad.write_text(raw.replace('"budget": 2400', '"budget": 1000'))
    with pytest.raises(ValueError, match="no feasible within-budget award"):
        pr.load_procurement_world(bad)

    bad2 = tmp_path / "bad2.json"
    bad2.write_text(raw.replace('"contract_value": 3000', '"contract_value": 2000'))
    with pytest.raises(ValueError, match="contract_value must exceed budget"):
        pr.load_procurement_world(bad2)
