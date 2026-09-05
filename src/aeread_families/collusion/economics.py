"""Pure closed-form economics for the repeated Bertrand-logit duopoly.

Every formula here is transcribed from Fish, Gonczarowski, and Shorrer,
*Algorithmic Collusion by Large Language Models* (arXiv 2404.00806v6),
section 2.1, per ``docs/collusion_adapter_spec.md``'s governing facts. The
two closed-form solvers (:func:`solve_nash`, :func:`solve_monopoly`) are
AERead's own deterministic bisection implementations -- never
``scipy.optimize`` -- chosen for bit-exact cross-version reproducibility
(spec section 1's build procedure: "run twice, require bit-identical output
before admission").

Both firms share one demand system, so a firm's own-price first-order
condition is coupled to the other firm's price only through the shared
logit denominator. For the symmetric baseline (``a_1 == a_2``, ``c_1 ==
c_2``) the two-firm fixed point collapses to the single-variable equation
the paper's own Appendix A.5 quotes; for the asymmetric-quality treatment
(Appendix A.2) the two firms' prices genuinely differ, so this module always
solves the general two-firm system and lets the symmetric case fall out as
a special case, rather than special-casing symmetry.
"""
from __future__ import annotations

import math
from typing import NamedTuple


class FirmSolution(NamedTuple):
    """One firm's price and profit at a solved equilibrium."""

    price: float
    profit: float


class SolverTrace(NamedTuple):
    """Deterministic solver parameters, frozen alongside the solved values.

    Recorded so ``gold_reference.solver`` documents exactly how many
    bisection/best-response steps produced the numbers -- a future solver
    change (more or fewer iterations) changes ``content_sha256`` rather than
    silently redefining gold values in place (spec section 1).
    """

    method: str
    outer_iterations: int
    inner_iterations: int
    bracket_lo: float
    bracket_hi: float


# Fixed iteration counts, never tolerance-based early stopping: a fixed
# number of pure floating-point operations is what "bit-identical across two
# runs" actually requires (spec section 1's build procedure). These values
# were chosen generously past the point of any further digit changing (see
# ``tests/test_collusion_cases.py``'s arithmetic-parity regression, which
# checks convergence to the paper's own quoted Appendix A.5 figures).
BISECTION_ITERATIONS = 200
BEST_RESPONSE_ITERATIONS = 80
# Expressed as a multiple of alpha so the bracket safely contains the
# equilibrium at every pilot cost_scale (1, 3.2, 10) -- prices and profits
# scale linearly in alpha (spec's governing facts), so one alpha-relative
# constant covers every cell.
BRACKET_HI_PER_ALPHA = 50.0


def market_shares(
    prices: tuple[float, float],
    a: tuple[float, float],
    a0: float,
    mu: float,
    alpha: float,
) -> tuple[float, float]:
    """Logit market shares (fractions of ``beta``) for both firms (spec 2.1)."""
    x1 = (a[0] - prices[0] / alpha) / mu
    x2 = (a[1] - prices[1] / alpha) / mu
    denominator = math.exp(x1) + math.exp(x2) + math.exp(a0 / mu)
    return math.exp(x1) / denominator, math.exp(x2) / denominator


def quantities(
    prices: tuple[float, float],
    a: tuple[float, float],
    a0: float,
    mu: float,
    beta: float,
    alpha: float,
) -> tuple[float, float]:
    """``q_i = beta * share_i`` for both firms (spec 2.1)."""
    share_1, share_2 = market_shares(prices, a, a0, mu, alpha)
    return beta * share_1, beta * share_2


def profits(
    prices: tuple[float, float],
    a: tuple[float, float],
    a0: float,
    mu: float,
    beta: float,
    alpha: float,
    c: tuple[float, float],
) -> tuple[float, float]:
    """``pi_i = (p_i - alpha * c_i) * q_i`` for both firms (spec 2.1)."""
    q1, q2 = quantities(prices, a, a0, mu, beta, alpha)
    return (prices[0] - alpha * c[0]) * q1, (prices[1] - alpha * c[1]) * q2


def _bisect(f, lo: float, hi: float, iterations: int) -> float:
    """Fixed-iteration-count bisection; never a tolerance-based early exit."""
    f_lo = f(lo)
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if (f_lo <= 0) == (f_mid <= 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def solve_nash(
    a: tuple[float, float],
    a0: float,
    mu: float,
    beta: float,
    alpha: float,
    c: tuple[float, float],
) -> tuple[tuple[FirmSolution, FirmSolution], SolverTrace]:
    """Solve the Bertrand-Nash equilibrium via best-response bisection.

    Firm i's own-price first-order condition (verified this session by
    bisection, spec section "Governing facts"):
    ``p_i - alpha * c_i == alpha * mu / (1 - q_i / beta)``, where ``q_i``
    depends on both prices through the shared logit denominator. Iterating
    each firm's best response to a fixed opponent price converges to the
    unique symmetric solution when ``a_1 == a_2`` and ``c_1 == c_2``, and to
    the (generally asymmetric) two-firm solution otherwise.
    """
    lo, hi = 0.0, alpha * BRACKET_HI_PER_ALPHA
    price_1 = alpha * c[0]
    price_2 = alpha * c[1]
    for _ in range(BEST_RESPONSE_ITERATIONS):
        def firm_1_residual(candidate: float, _price_2: float = price_2) -> float:
            q1, _q2 = quantities((candidate, _price_2), a, a0, mu, beta, alpha)
            return (candidate - alpha * c[0]) - alpha * mu / (1 - q1 / beta)

        price_1 = _bisect(firm_1_residual, lo, hi, BISECTION_ITERATIONS)

        def firm_2_residual(candidate: float, _price_1: float = price_1) -> float:
            _q1, q2 = quantities((_price_1, candidate), a, a0, mu, beta, alpha)
            return (candidate - alpha * c[1]) - alpha * mu / (1 - q2 / beta)

        price_2 = _bisect(firm_2_residual, lo, hi, BISECTION_ITERATIONS)

    pi_1, pi_2 = profits((price_1, price_2), a, a0, mu, beta, alpha, c)
    trace = SolverTrace(
        method="best_response_bisection",
        outer_iterations=BEST_RESPONSE_ITERATIONS,
        inner_iterations=BISECTION_ITERATIONS,
        bracket_lo=lo,
        bracket_hi=hi,
    )
    return (FirmSolution(price_1, pi_1), FirmSolution(price_2, pi_2)), trace


def solve_monopoly(
    a: tuple[float, float],
    a0: float,
    mu: float,
    beta: float,
    alpha: float,
    c: tuple[float, float],
) -> tuple[tuple[FirmSolution, FirmSolution], SolverTrace]:
    """Solve the joint-profit-maximizing prices via best-response bisection.

    Joint first-order condition for firm i (derived from ``d(pi_1+pi_2)/
    dp_i = 0`` this session; verified by grid search over the total-profit
    surface before being trusted):
    ``p_i - alpha*c_i == (alpha*mu + (p_j - alpha*c_j)*(q_j/beta)) /
    (1 - q_i/beta)``. The symmetric baseline collapses this to ``p - alpha*c
    == alpha*mu / (1 - 2*q/beta)`` -- the paper's own quoted Appendix A.5
    monopoly figures.
    """
    lo, hi = 0.0, alpha * BRACKET_HI_PER_ALPHA
    price_1 = alpha * c[0]
    price_2 = alpha * c[1]
    for _ in range(BEST_RESPONSE_ITERATIONS):
        def firm_1_residual(candidate: float, _price_2: float = price_2) -> float:
            q1, q2 = quantities((candidate, _price_2), a, a0, mu, beta, alpha)
            spillover = alpha * mu + (_price_2 - alpha * c[1]) * (q2 / beta)
            return (candidate - alpha * c[0]) - spillover / (1 - q1 / beta)

        price_1 = _bisect(firm_1_residual, lo, hi, BISECTION_ITERATIONS)

        def firm_2_residual(candidate: float, _price_1: float = price_1) -> float:
            q1, q2 = quantities((_price_1, candidate), a, a0, mu, beta, alpha)
            spillover = alpha * mu + (_price_1 - alpha * c[0]) * (q1 / beta)
            return (candidate - alpha * c[1]) - spillover / (1 - q2 / beta)

        price_2 = _bisect(firm_2_residual, lo, hi, BISECTION_ITERATIONS)

    pi_1, pi_2 = profits((price_1, price_2), a, a0, mu, beta, alpha, c)
    trace = SolverTrace(
        method="best_response_bisection",
        outer_iterations=BEST_RESPONSE_ITERATIONS,
        inner_iterations=BISECTION_ITERATIONS,
        bracket_lo=lo,
        bracket_hi=hi,
    )
    return (FirmSolution(price_1, pi_1), FirmSolution(price_2, pi_2)), trace


__all__ = [
    "BEST_RESPONSE_ITERATIONS",
    "BISECTION_ITERATIONS",
    "BRACKET_HI_PER_ALPHA",
    "FirmSolution",
    "SolverTrace",
    "market_shares",
    "profits",
    "quantities",
    "solve_monopoly",
    "solve_nash",
]
