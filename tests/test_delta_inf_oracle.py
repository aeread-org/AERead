"""TDD for the continuous Delta_inf oracle pieces (TERMS-Bench Eq.4 alignment).

realized_welfare: the true welfare gain that materializes under rational consent (every involved
party weakly gains, else the trade is rejected -> 0). best_mutually_ir_gain_2x2: the oracle ceiling
-- the best mutually-IR welfare gain for a 2-agent, 2-good economy (a1 holds good0, a2 holds good1).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import delta_inf_oracle as do  # noqa: E402


def test_realized_welfare_mutually_ir_positive():
    values = [[1, 8], [9, 1]]
    holdings = [[10, 0], [0, 10]]
    transfers = [(0, 1, 0, 5), (1, 0, 1, 5)]  # mutually-IR swap
    assert do.realized_welfare(values, holdings, 0, transfers) > 0


def test_realized_welfare_rejected_trade_is_zero():
    # counterparty (a1, index 1) loses its highly valued good -> rejects -> nothing materializes
    values = [[1, 9], [1, 9]]
    holdings = [[10, 0], [0, 10]]
    transfers = [(1, 0, 1, 5), (0, 1, 0, 5)]
    assert do.realized_welfare(values, holdings, 0, transfers) == 0.0


def test_oracle_positive_and_dominates_a_concrete_swap():
    values = [[1, 8], [9, 1]]
    holdings = [[10, 0], [0, 10]]
    g = do.best_mutually_ir_gain_2x2(values, holdings)
    assert g > 0
    concrete = do.realized_welfare(values, holdings, 0, [(0, 1, 0, 5), (1, 0, 1, 5)])
    assert g >= concrete - 1e-6   # the oracle is at least as good as any specific mutually-IR trade


def test_oracle_zero_when_no_gains_from_trade():
    # each already holds exactly the good it values; no IR trade improves welfare
    values = [[9, 0], [0, 9]]
    holdings = [[10, 0], [0, 10]]
    assert do.best_mutually_ir_gain_2x2(values, holdings) < 0.5


def test_info_constrained_oracle_positive_with_gains():
    # a1 values the good a2 holds -> prior-only Bayes-optimal trade has positive expected welfare
    g = do.bayes_optimal_prior_welfare([1, 8], [[10, 0], [0, 10]], 0, 9, grid=24)
    assert g > 0


def test_info_constrained_oracle_zero_when_a1_wont_trade():
    # a1 values its own good highly and the other at 0 -> no self-IR trade -> ~0 expected welfare
    g = do.bayes_optimal_prior_welfare([9, 0], [[10, 0], [0, 10]], 0, 9, grid=24)
    assert g < 0.5


def test_info_constrained_never_exceeds_full_info_oracle_in_expectation():
    # the prior-only ceiling cannot beat knowing the realized type (averaged over the prior)
    values_a1 = [1, 8]
    holdings = [[10, 0], [0, 10]]
    ic = do.bayes_optimal_prior_welfare(values_a1, holdings, 0, 9, grid=24)
    full = sum(do.best_mutually_ir_gain_2x2([values_a1, [b0, b1]], holdings)
               for b0 in range(10) for b1 in range(10)) / 100.0
    assert ic <= full + 1e-6
