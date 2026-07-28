"""Deterministic classifier: WHY is a proposed trade non-IR?

Given a proposed bundle of transfers plus the true (hidden) values and holdings, attribute the
proposal to one MECE cause, against the exchange-economy concave-separable utility u = sum v*sqrt(x):

  INFEASIBLE          -- overdraft / phantom goods (H5/H6: feasibility/grounding)
  SELF_NON_IR         -- proposer's own true delta < 0 (H2; concavity_flip flags H7)
  COUNTERPARTY_NON_IR -- some other involved party's delta < 0 -> they would reject (H1/H3/H9)
  MUTUALLY_IR         -- every involved party weakly gains (a good proposal)
  EMPTY               -- no transfers

surplus_share_proposer (fraction of the total positive delta the proposer keeps) flags greedy
splits among the MUTUALLY_IR proposals. Agent and good indices are 0-based.
"""
from __future__ import annotations

import math

EPS = 1e-9


def _u_concave(values, bundle):
    return sum(v * math.sqrt(max(0.0, x)) for v, x in zip(values, bundle))


def _u_linear(values, bundle):
    return sum(v * max(0.0, x) for v, x in zip(values, bundle))


def apply_transfers(holdings, transfers):
    alloc = [row[:] for row in holdings]
    feasible = True
    for (frm, to, g, q) in transfers:
        if q <= 0 or g < 0 or g >= len(alloc[0]):
            feasible = False
            continue
        if alloc[frm][g] - q < -EPS:        # overdraft (also catches phantom goods: holding 0)
            feasible = False
        alloc[frm][g] -= q
        alloc[to][g] += q
    return alloc, feasible


def classify_proposal(values, holdings, proposer, transfers):
    n = len(values)
    involved = set()
    for (frm, to, g, q) in transfers:
        involved.add(frm)
        involved.add(to)
    alloc, feasible = apply_transfers(holdings, transfers)

    deltas = {i: _u_concave(values[i], alloc[i]) - _u_concave(values[i], holdings[i]) for i in range(n)}
    self_delta = deltas[proposer]
    counterparty_non_ir = sorted(i for i in involved if i != proposer and deltas[i] < -EPS)

    lin_self = _u_linear(values[proposer], alloc[proposer]) - _u_linear(values[proposer], holdings[proposer])
    concavity_flip = bool(lin_self >= -EPS and self_delta < -EPS)

    if not transfers:
        category = "EMPTY"
    elif not feasible:
        category = "INFEASIBLE"
    elif self_delta < -EPS:
        category = "SELF_NON_IR"
    elif counterparty_non_ir:
        category = "COUNTERPARTY_NON_IR"
    else:
        category = "MUTUALLY_IR"

    total_pos = sum(d for d in deltas.values() if d > 0)
    surplus_share_proposer = (self_delta / total_pos) if total_pos > EPS else 0.0

    return {
        "category": category,
        "feasible": feasible,
        "self_delta": self_delta,
        "counterparty_deltas": {i: deltas[i] for i in involved if i != proposer},
        "counterparty_non_ir": counterparty_non_ir,
        "concavity_flip": concavity_flip,
        "surplus_share_proposer": surplus_share_proposer,
    }
