"""Information-constrained achievable welfare (W_bayes) for the bundle-under-budget world.

Slice 2 of the oracle carve-out (bilateral exact_wbayes was slice 1). This replaces the
BundleCaseOracle's wstar_fallback with the settled mc_wbayes object:

    the best EXPECTED social welfare a buyer can realize knowing its own mandate
    (bundle_value, budget, required components) and the PRIOR over sellers' private
    reservation costs -- but NOT the realized costs -- when each seller accepts iff the
    offered price >= its realized cost (a rational IR-responder).

This is a single-agent Bayesian decision problem (a best response to rational IR-responders),
NOT a Bayesian-Nash fixed point -- so it is tractable, symbolic, and needs no LLM rollouts.
It mirrors delta_inf_oracle.bayes_optimal_prior_welfare (the bilateral backend), one dimension up.

Objective is SOCIAL welfare (benevolent buyer): welfare = bundle_value - sum(true costs of the
components actually acquired) when the bundle completes within budget, else 0. Prices are
welfare-neutral transfers, so the buyer's offers matter only through completion probability and
which seller is used. With >1 seller per component the buyer buys from the cheapest ACCEPTING
seller (benevolent selection); competition is handled by Monte Carlo rather than a closed form.

Selection assumption (spec, settled 2026-07-22): the buyer can route to the cheapest ACCEPTING
seller -- a competitive-procurement idealization. This yields the BEST-CASE achievable ceiling
(a larger denominator => conservative AER, i.e. it under-credits rather than over-credits). If the
real A2A mechanism does NOT let a buyer discover/route to the cheaper accepter, the faithful
alternative is a random accepter paying E[cost | accept] (a lower ceiling). Which applies is a
question about the market's actual affordances (pending the mechanism owner).

Returns (w_bayes, (lo, hi)) where the interval is the seeded bootstrap on the Monte-Carlo
denominator (the CI the aer_scorer propagates for TIER_MC).
"""
from __future__ import annotations

import random
from typing import Tuple


def _sellers_by_component(spec, layout, num_agents) -> dict:
    comps = [int(c) for c in spec.required_components]
    by_comp: dict[int, list[int]] = {c: [] for c in comps}
    for seller_id, comp in layout.component_by_seller.items():
        c = int(comp)
        if c in by_comp:
            by_comp[c].append(int(seller_id))
    for c in comps:
        if not by_comp[c]:
            raise ValueError(f"no seller holds required component {c}")
    return by_comp


def bundle_bayes_optimal_welfare(
    world,
    *,
    seed: int = 0,
    n_mc: int = 3000,
    offer_steps: int = 9,
    n_boot: int = 800,
) -> Tuple[float, Tuple[float, float]]:
    """Prior-expectation achievable social welfare for a bundle-under-budget world.

    Assumptions (raise otherwise -> caller degrades to wstar_fallback):
      * seller reservation costs are i.i.d. Uniform[lo, hi] with (lo, hi) = seller_cost_range;
      * the buyer posts one price per required component (a threshold offer); sellers of that
        component accept iff cost <= price; the buyer acquires from the cheapest accepter.
    Optimizes the per-component offer vector over a grid subject to sum(offers) <= budget.
    """
    spec = world.bundle_utility
    layout = world.seller_layout
    if spec is None or layout is None:
        raise ValueError("bundle_bayes requires a bundle_under_budget world with a seller layout")
    lo, hi = float(layout.seller_cost_range[0]), float(layout.seller_cost_range[1])
    if not (hi >= lo >= 0.0):
        raise ValueError(f"bad seller_cost_range {layout.seller_cost_range}")
    comps = [int(c) for c in spec.required_components]
    by_comp = _sellers_by_component(spec, layout, world.num_agents)
    budget = float(spec.budget)
    bundle_value = float(spec.bundle_value)

    rng = random.Random(seed)
    # Monte-Carlo cost profiles: per component, one cost per seller of that component.
    profiles = [
        {c: [lo + (hi - lo) * rng.random() for _ in by_comp[c]] for c in comps}
        for _ in range(n_mc)
    ]

    span = hi - lo if hi > lo else 1.0
    grid = [lo + span * k / (offer_steps - 1) for k in range(offer_steps)] if offer_steps > 1 else [hi]

    def welfare(offers: dict, prof: dict) -> float:
        spend = 0.0
        total_cost = 0.0
        for c in comps:
            p = offers[c]
            accepting = [cc for cc in prof[c] if cc <= p + 1e-12]
            if not accepting:
                return 0.0                     # component not acquired -> bundle incomplete
            total_cost += min(accepting)       # benevolent: cheapest accepting seller
            spend += p
        if spend > budget + 1e-9:
            return 0.0                         # mandate (budget) violation -> no completion
        return bundle_value - total_cost

    def mean_welfare(offers: dict) -> float:
        return sum(welfare(offers, p) for p in profiles) / len(profiles)

    # Optimize the offer vector. Budget couples the components, so full grid for small bundles;
    # coordinate ascent (from the highest budget-feasible equal offer) for larger ones.
    best_offers: dict
    if len(comps) <= 4 and offer_steps ** len(comps) <= 6000:
        best_offers, best_val = None, -1e18
        import itertools
        for combo in itertools.product(grid, repeat=len(comps)):
            if sum(combo) > budget + 1e-9:
                continue
            offers = dict(zip(comps, combo))
            v = mean_welfare(offers)
            if v > best_val:
                best_val, best_offers = v, offers
        if best_offers is None:                # nothing feasible within budget
            return 0.0, (0.0, 0.0)
    else:
        feasible = min(grid, key=lambda g: abs(g - min(hi, budget / len(comps))))
        best_offers = {c: feasible for c in comps}
        best_val = mean_welfare(best_offers)
        improved = True
        while improved:
            improved = False
            for c in comps:
                for g in grid:
                    cand = dict(best_offers)
                    cand[c] = g
                    if sum(cand.values()) > budget + 1e-9:
                        continue
                    v = mean_welfare(cand)
                    if v > best_val + 1e-9:
                        best_val, best_offers, improved = v, cand, True

    # Bootstrap CI on the denominator at the optimal offers (aer_scorer propagates this for TIER_MC).
    per = [welfare(best_offers, p) for p in profiles]
    boot = random.Random(seed + 1)
    n = len(per)
    means = sorted(sum(per[boot.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    ci = (means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))])
    return max(0.0, best_val), ci


def expected_wstar(world, *, seed: int = 0, n_mc: int = 3000) -> float:
    """Prior-expectation full-information ceiling E[W*] = bundle_value - E[sum of cheapest
    per-component costs]. Used only for the ordering invariant W_bayes <= E[W*] in tests."""
    spec = world.bundle_utility
    layout = world.seller_layout
    lo, hi = float(layout.seller_cost_range[0]), float(layout.seller_cost_range[1])
    comps = [int(c) for c in spec.required_components]
    by_comp = _sellers_by_component(spec, layout, world.num_agents)
    rng = random.Random(seed)
    total = 0.0
    for _ in range(n_mc):
        min_cost = sum(min(lo + (hi - lo) * rng.random() for _ in by_comp[c]) for c in comps)
        total += max(0.0, float(spec.bundle_value) - min_cost)   # full-info completes only if profitable
    return total / n_mc


def one_sided_wedge(world, *, seed: int = 0, n_mc: int = 3000,
                    n_boot: int = 400) -> dict:
    """Constrained wedge estimator enforcing the one-sided bound W_bayes <= E[W*].

    The true information wedge Delta_unc = E[W*] - W_bayes is nonnegative by
    definition; the unconstrained Monte-Carlo point estimate can come out
    nominally negative through sampling noise (a validation artifact, not
    evidence). This reports both: the raw draw (transparency) and the
    constrained estimate max(0, raw) with its one-sided CI, which is the
    number fairness claims should cite.
    """
    w_bayes, (lo, hi) = bundle_bayes_optimal_welfare(
        world, seed=seed, n_mc=n_mc, n_boot=n_boot)
    ew_star = expected_wstar(world, seed=seed, n_mc=n_mc)
    raw = ew_star - w_bayes
    return {
        "e_wstar": ew_star,
        "w_bayes": w_bayes,
        "w_bayes_ci": (lo, hi),
        "wedge_raw": raw,
        "wedge_constrained": max(0.0, raw),
        "wedge_upper_95": max(0.0, ew_star - lo),
        "note": "wedge_constrained enforces W_bayes <= E[W*]; cite it, not wedge_raw",
    }
