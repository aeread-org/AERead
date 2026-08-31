"""TDD for the optional money numeraire in the exchange economy.

Adds one good ("money") that is a transferable numeraire: linear utility (no sqrt), valued
equally by everyone, owned by everyone. The point is to test whether a money instrument lets
agents lubricate IR-preserving trades (side-payments) in the divisible economy. money_good_index
defaults to None, so the existing engine (and its 139 tests) is unchanged.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread.exchange_v1 import economy as ex  # noqa: E402


def test_money_good_is_linear_not_concave():
    prefs = [2.0, 1.0]   # good0 valued 2; money valued 1
    bundle = [4, 9]      # 4 of good0, 9 money
    # money linear: good0 concave 2*sqrt(4)=4, money 1*9=9 -> 13
    u = ex.utility_for_bundle(prefs, bundle, "concave_separable", money_good_index=1)
    assert abs(u - (2 * math.sqrt(4) + 9)) < 1e-9
    # without the money index, money is (wrongly) sqrt'd: 4 + 1*3 = 7
    u2 = ex.utility_for_bundle(prefs, bundle, "concave_separable")
    assert abs(u2 - (4 + 3)) < 1e-9


def test_money_transfer_is_welfare_neutral():
    w = ex.make_exchange_world(num_agents=4, num_resources=4, seed=1,
                               utility_mode="concave_separable", with_money=True)
    assert w.money_good_index == 4  # appended after the 4 goods
    base = ex.total_welfare(w)
    alloc = w.copy_allocation()
    mi = w.money_good_index
    alloc[0][mi] -= 5
    alloc[1][mi] += 5
    assert abs(ex.total_welfare(w, alloc) - base) < 1e-9  # equal linear value -> neutral


def test_side_payment_makes_an_otherwise_non_ir_trade_ir():
    # agent0 holds 4 of g0 but values it low (1); agent1 values g0 high (5); both hold money.
    alloc = [[4, 10], [0, 10]]
    prefs = [[1.0, 1.0], [5.0, 1.0]]
    w = ex.ExchangeWorld(allocation=alloc, preferences=prefs, utility_mode="concave_separable",
                         money_good_index=1, resource_names=["g0", "money"])
    # agent0 gives its 4 g0 to agent1; agent1 pays 6 money back
    after = [[0, 16], [4, 4]]
    assert w.utility(1, after) >= w.utility(1) - 1e-9   # agent0 weakly better
    assert w.utility(2, after) >= w.utility(2) - 1e-9   # agent1 weakly better
    # and total welfare strictly rose (the good moved to who values it more)
    assert ex.total_welfare(w, after) > ex.total_welfare(w) + 1e-9


def test_default_world_has_no_money_and_is_unchanged():
    w = ex.make_exchange_world(num_agents=5, num_resources=5, seed=7, utility_mode="concave_separable")
    assert w.money_good_index is None
    assert w.num_resources == 5
    assert abs(w.utility(1) - ex.utility_for_bundle(w.preferences[0], w.allocation[0],
                                                    "concave_separable")) < 1e-9
