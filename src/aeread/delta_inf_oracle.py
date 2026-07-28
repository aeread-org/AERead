"""Continuous welfare oracle for the TERMS-Bench Eq.4 (Delta_unc + Delta_inf + Delta_ctrl) alignment.

realized_welfare gates a proposal on rational consent (it materializes only if every involved party
weakly gains, matching the discrete classifier's MUTUALLY_IR). best_mutually_ir_gain_2x2 is the
oracle ceiling for the probe's 2-agent, 2-good family (a1 holds good0, a2 holds good1): the maximum
total welfare gain over all mutually-IR swaps, by grid search over the two swap sizes.
"""
from __future__ import annotations

import math

from aeread import nonir_classifier as nc

EPS = 1e-9


def realized_welfare(values, holdings, proposer, transfers):
    """Total true welfare gain that materializes under rational consent (0 if any involved party
    is worse off and would reject)."""
    r = nc.classify_proposal(values, holdings, proposer, transfers)
    if r["category"] != "MUTUALLY_IR":
        return 0.0
    return r["self_delta"] + sum(r["counterparty_deltas"].values())


def _u(vals, bundle):
    return sum(v * math.sqrt(max(0.0, q)) for v, q in zip(vals, bundle))


def best_mutually_ir_gain_2x2(values, holdings, grid=80):
    """FULL-INFORMATION oracle ceiling pi-star: best mutually-IR welfare gain for a 2-agent 2-good
    economy where a1 holds good0 (qty Q0) and a2 holds good1 (qty Q1). Swap = a1 gives x of good0,
    a2 gives y of good1. NOTE: this ceiling embeds knowledge of the realized counterpart type, so
    the agent's gap to it includes the irreducible Delta_unc -- use bayes_optimal_prior_welfare to
    exclude that and measure only the addressable gap."""
    q0 = holdings[0][0]
    q1 = holdings[1][1]
    base0 = _u(values[0], holdings[0])
    base1 = _u(values[1], holdings[1])
    best = 0.0
    for i in range(grid + 1):
        x = q0 * i / grid
        for j in range(grid + 1):
            y = q1 * j / grid
            d0 = _u(values[0], [q0 - x, y]) - base0
            d1 = _u(values[1], [x, q1 - y]) - base1
            if d0 >= -EPS and d1 >= -EPS:
                best = max(best, d0 + d1)
    return best


def bayes_optimal_prior_welfare(values_a1, holdings, prior_lo=0, prior_hi=9, grid=40):
    """INFORMATION-CONSTRAINED oracle pi_post: the best EXPECTED consent-gated welfare any
    prior-only policy can achieve, when the proposer (a1) knows its own values + the prior over
    the counterpart's values but NOT the realized values. Excludes the irreducible value of
    information (Delta_unc) from the ceiling, leaving only what the agent could actually address.

    a1 picks a self-IR trade (x of good0 out, y of good1 in); a2 accepts iff its (random) delta is
    >= 0. Expectation is over the uniform-integer prior on a2's two values."""
    q0 = holdings[0][0]
    q1 = holdings[1][1]
    base0 = _u(values_a1, holdings[0])
    prior = [[b0, b1] for b0 in range(prior_lo, prior_hi + 1) for b1 in range(prior_lo, prior_hi + 1)]
    base_b = [_u(vb, holdings[1]) for vb in prior]
    best = 0.0
    for i in range(grid + 1):
        x = q0 * i / grid
        d0 = _u(values_a1, [q0 - x, 0.0])  # placeholder; recompute per y below
        for j in range(grid + 1):
            y = q1 * j / grid
            d0 = _u(values_a1, [q0 - x, y]) - base0
            if d0 < -EPS:            # a1 self-interested: never proposes a self-harming trade
                continue
            acc = 0.0
            for k, vb in enumerate(prior):
                d1 = _u(vb, [x, q1 - y]) - base_b[k]
                if d1 >= -EPS:       # a2 accepts iff individually rational
                    acc += d0 + d1
            best = max(best, acc / len(prior))
    return best
