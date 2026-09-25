"""The lemons gap decomposition: an exact split of the payoff and typed decisions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aeread_families.housing import lemons_comparison as comparison
from aeread_families.housing import lemons_gap as gap

# One tenant (0) and three listings; listing 1 is a lemon (true value 1000 below its value if sound).
WORLD = SimpleNamespace(
    values=[[2000.0, 1500.0, 1800.0]],
    values_if_sound=[[2000.0, 2500.0, 1800.0]],
    ask=[1700.0, 1600.0, 1500.0],
    lemon_loss=1000.0,
    inspection_cost=25.0,
)


def _decision(listing, decision, informed, expected_value, rent, quality, round_index=0):
    return {"tenant_id": 0, "listing_id": listing, "decision": decision, "informed": informed,
            "expected_value": expected_value, "rent": rent, "quality": quality, "round_index": round_index}


@pytest.fixture(autouse=True)
def world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comparison, "_world", lambda seed: WORLD)


def test_components_sum_to_the_published_payoff() -> None:
    decisions = [
        _decision(0, "sign", True, 2000.0, 1700.0, "sound"),                  # informed: +300
        _decision(1, "sign", False, 2500.0 - 0.5 * 1000.0, 1650.0, "lemon"),  # blind, EV 2000 >= 1650, turns out lemon
    ]
    payoff = (2000.0 - 1700.0) + (1500.0 - 1650.0) - 2 * 25.0
    row = {"world_seed": 1, "commit_decisions": decisions, "inspection_count": 2, "tenant_net_payoff": payoff}
    result = gap.analyse_cell(row, {(0, "tenant_0"): {"decision": "inspect", "listing_id": 0}})
    assert result["parts"]["informed_leases"] == pytest.approx(300.0)
    assert result["parts"]["blind_good_bets"] == pytest.approx(350.0)
    assert result["parts"]["lemon_draws"] == pytest.approx(1500.0 - 2000.0)
    assert result["parts"]["inspection_spend"] == pytest.approx(-50.0)
    assert result["residual"] == pytest.approx(0.0)
    classes = {i["class"] for i in result["instances"]}
    assert classes == {"L5_good_blind_bet_turned_lemon", "A1_tenant_signed_above_own_value", "L4_signed_above_ask"}


def test_a_pass_is_not_an_inspection() -> None:
    blind = _decision(1, "sign", False, 2500.0 - 0.5 * 1000.0, 1600.0, "lemon")
    row = {"world_seed": 1, "commit_decisions": [blind], "inspection_count": 0, "tenant_net_payoff": 1500.0 - 1600.0}
    passed = gap.analyse_cell(row, {(0, "tenant_0"): {"decision": "pass"}})
    assert "L2_skipped_worthwhile_inspection" in {i["class"] for i in passed["instances"]}
    inspected_elsewhere = gap.analyse_cell(row, {(0, "tenant_0"): {"decision": "inspect", "listing_id": 2}})
    assert "L2_skipped_worthwhile_inspection" not in {i["class"] for i in inspected_elsewhere["instances"]}


def test_bad_bets_and_declined_holds() -> None:
    decisions = [
        _decision(1, "sign", False, 1500.0, 1600.0, "lemon"),   # EV 1500 < rent 1600: L1, and it was a lemon
        _decision(2, "walk", False, 1800.0, 1500.0, "sound"),   # walked from EV 1800 > rent 1500: L3
    ]
    payoff = 1500.0 - 1600.0
    row = {"world_seed": 1, "commit_decisions": decisions, "inspection_count": 0, "tenant_net_payoff": payoff}
    result = gap.analyse_cell(row, {})
    kinds = {i["class"]: i["amount"] for i in result["instances"]}
    assert kinds["L1_blind_sign_below_expected_value"] == pytest.approx(100.0)
    assert kinds["L3_declined_hold_worth_more"] == pytest.approx(300.0)
    assert result["parts"]["blind_bad_bets"] == pytest.approx(-100.0)
    assert result["parts"]["lemon_draws"] == pytest.approx(0.0)  # EV 1500 already priced the lemon at p = 1
    assert result["residual"] == pytest.approx(0.0)
