"""TDD for the non-IR proposal classifier.

Given a proposed trade and the TRUE (hidden) values + holdings, attribute why it is non-IR to a
single MECE cause: INFEASIBLE (H5/H6), SELF_NON_IR (H2; concavity_flip flags H7),
COUNTERPARTY_NON_IR (would be rejected -> H1/H3/H9), or MUTUALLY_IR (a good proposal). Utility is
the exchange-economy concave-separable form u = sum v*sqrt(x).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import nonir_classifier as nc  # noqa: E402


def test_mutually_ir_swap():
    # a0 holds good0 (values it 1, wants good1=8); a1 holds good1 (values it 1, wants good0=9)
    values = [[1, 8], [9, 1]]
    holdings = [[10, 0], [0, 10]]
    transfers = [(0, 1, 0, 5), (1, 0, 1, 5)]  # swap 5 of good0 for 5 of good1
    r = nc.classify_proposal(values, holdings, 0, transfers)
    assert r["category"] == "MUTUALLY_IR"
    assert r["self_delta"] > 0 and r["counterparty_non_ir"] == []


def test_self_non_ir():
    # a0 gives away its valued good and receives nothing useful
    values = [[5, 0], [0, 5]]
    holdings = [[10, 0], [0, 10]]
    transfers = [(0, 1, 0, 5)]  # a0 just hands over good0 it values at 5
    r = nc.classify_proposal(values, holdings, 0, transfers)
    assert r["category"] == "SELF_NON_IR"
    assert r["self_delta"] < 0


def test_counterparty_non_ir():
    # a0 takes a1's valued good and gives a1 something a1 doesn't want
    values = [[1, 9], [1, 9]]            # both value good1 highly
    holdings = [[10, 0], [0, 10]]
    transfers = [(1, 0, 1, 5), (0, 1, 0, 5)]  # a1 gives up good1(values 9), gets good0(values 1)
    r = nc.classify_proposal(values, holdings, 0, transfers)
    assert r["category"] == "COUNTERPARTY_NON_IR"
    assert 1 in r["counterparty_non_ir"]


def test_infeasible_overdraft():
    values = [[1, 8], [9, 1]]
    holdings = [[3, 0], [0, 10]]
    transfers = [(0, 1, 0, 5)]  # a0 only holds 3 of good0 but transfers 5
    r = nc.classify_proposal(values, holdings, 0, transfers)
    assert r["category"] == "INFEASIBLE"
    assert r["feasible"] is False


def test_concavity_flip_is_self_non_ir():
    # linear-IR (+3) but concave-non-IR for the proposer (diminishing returns on abundant good0)
    values = [[1, 1], [1, 1]]
    holdings = [[16, 1], [4, 0]]
    transfers = [(1, 0, 0, 4), (0, 1, 1, 1)]  # a0 gets 4 of abundant good0, gives 1 of scarce good1
    r = nc.classify_proposal(values, holdings, 0, transfers)
    assert r["category"] == "SELF_NON_IR"
    assert r["concavity_flip"] is True
