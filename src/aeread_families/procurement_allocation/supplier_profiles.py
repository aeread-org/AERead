"""Supplier profiles drawn from a declared market, and the case built on them.

Draft for the hidden-information redesign (P-D-09, P-D-10). The repeated-sourcing
worlds told the buyer the answer through supplier names and never let the
cheaper supplier be bad. Here every supplier has a hidden type, good or bad,
drawn from a prior the buyer is told. What the buyer sees is a marketplace
profile of the kind Alibaba shows (star breakdown, order count, on-time record
over protected orders, years on the platform, badges, response time), simulated
order by order from the hidden type. Nothing else about the type reaches the
buyer: ids are neutral codes and both suppliers make the same claims.

Because the profile is generated from a stated model, the probability that a
supplier is bad given its profile is exact (:func:`posterior_bad`), and so is the
best policy on the buyer's information (:func:`solve`), a dynamic programme over
beliefs. A decision can then be graded by what the buyer could have known at the
time, not only by the oracle that sees the type.

The case: one component, two suppliers (an established incumbent and a cheaper
challenger), ``periods`` purchase periods. Each period the buyer may test one
supplier's sample (``sample_units`` units, defects observed) and then buys the
period's lot from one supplier. A delivered lot shows which kind the supplier is
(declared), so buying is also a test; a sample is a noisy test before buying. A defective unit costs a kit's revenue.

Not modelled here, stated so nobody reads it in: days and deadlines (a sample is
assumed to fit the period), budgets, negotiation, capacity, and supplier
reactions. Those stay in the environment; this module fixes the information
structure the environment would be given.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

# ---------------------------------------------------------------------------
# The declared market. Every number here is told to the buyer (see
# market_facts_text), so the buyer-information reference is fair.
# ---------------------------------------------------------------------------

MARKET: dict[str, Any] = {
    "prior_bad": {"established": 0.05, "new": 0.30},
    "years": {"established": (5, 12), "new": (0, 2)},
    # mean orders per year on the platform; the count itself says nothing about type
    "orders_per_year": {"established": 18.0, "new": 6.0},
    "type": {
        "good": {"defect_rate": 0.01, "on_time": 0.97, "problem_order": 0.05},
        "bad": {"defect_rate": 0.30, "on_time": 0.85, "problem_order": 0.45},
    },
    "review_rate": 0.35,
    # star distribution of a genuine review, 5..1, by whether the order had a problem.
    # Ratings are inflated: a problem order still earns five stars 30% of the time.
    "stars_ok": (0.86, 0.12, 0.015, 0.005, 0.0),
    "stars_problem": (0.30, 0.25, 0.20, 0.15, 0.10),
    # a bad supplier buys fake five-star reviews with this probability, Poisson mean
    "brushing": {"probability": 0.25, "mean_fake": 6.0},
    "protected_share": 0.6,  # share of orders under order protection; on-time is shown over these
    "badges": {  # probability of each badge by type; Gold is a paid membership
        "gold": {"good": 0.6, "bad": 0.6},
        "verified": {"good": 0.5, "bad": 0.35},
    },
    "response_hours": (1, 2, 4, 8, 24),  # drawn uniformly, unrelated to type
}

STARS = (5, 4, 3, 2, 1)


@dataclass(frozen=True)
class Profile:
    """What the buyer sees on a supplier's page. Counts, not only averages, so
    a careful reader can tell four five-star reviews from four hundred."""

    supplier_id: str
    years_on_platform: int
    orders: int
    star_counts: tuple[int, int, int, int, int]  # 5..1
    protected_orders: int
    on_time_protected: int
    gold: bool
    verified: bool
    response_hours: int
    segment: str  # established or new, read off years; stated for the reader

    @property
    def reviews(self) -> int:
        return sum(self.star_counts)

    @property
    def rating(self) -> float | None:
        if not self.reviews:
            return None
        return round(sum(s * n for s, n in zip(STARS, self.star_counts)) / self.reviews, 1)

    def text(self) -> str:
        r = f"{self.rating:.1f} stars from {self.reviews} reviews" if self.reviews else "no reviews yet"
        breakdown = " · ".join(f"{s}★ {n}" for s, n in zip(STARS, self.star_counts))
        on_time = (
            f"{self.on_time_protected}/{self.protected_orders} protected orders on time"
            if self.protected_orders
            else "no protected orders yet"
        )
        badges = ", ".join(b for b, on in (("Gold", self.gold), ("Verified", self.verified)) if on) or "no badges"
        return (
            f"{self.supplier_id}: {self.years_on_platform} year{'' if self.years_on_platform == 1 else 's'} on the platform, {self.orders} orders; "
            f"{r} ({breakdown}); {on_time}; {badges}; replies within {self.response_hours}h"
        )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _poisson(rng: random.Random, mean: float) -> int:
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _order_mean(years: int, segment: str, market: Mapping[str, Any]) -> float:
    return market["orders_per_year"][segment] * max(years, 0.5)


def _star_probs(kind: str, market: Mapping[str, Any] = MARKET) -> tuple[float, ...]:
    problem = market["type"][kind]["problem_order"]
    return tuple((1 - problem) * a + problem * b for a, b in zip(market["stars_ok"], market["stars_problem"]))


def draw_profile(
    rng: random.Random, *, supplier_id: str, segment: str, kind: str, market: Mapping[str, Any] = MARKET
) -> Profile:
    """Simulate a supplier's public record order by order from its hidden type."""
    lo, hi = market["years"][segment]
    years = rng.randint(lo, hi)
    genuine = _poisson(rng, _order_mean(years, segment, market))
    probs = _star_probs(kind, market)
    counts = [0] * 5
    for _ in range(genuine):
        if rng.random() < market["review_rate"]:
            counts[rng.choices(range(5), weights=probs)[0]] += 1
    fake = 0
    if kind == "bad" and rng.random() < market["brushing"]["probability"]:
        fake = _poisson(rng, market["brushing"]["mean_fake"])
    counts[0] += fake  # a brushed review comes with a brushed order, never a protected one
    orders = genuine + fake
    protected = sum(rng.random() < market["protected_share"] for _ in range(genuine))
    on_time = sum(rng.random() < market["type"][kind]["on_time"] for _ in range(protected))
    return Profile(
        supplier_id=supplier_id,
        years_on_platform=years,
        orders=orders,
        star_counts=tuple(counts),  # type: ignore[arg-type]
        protected_orders=protected,
        on_time_protected=on_time,
        gold=rng.random() < market["badges"]["gold"][kind],
        verified=rng.random() < market["badges"]["verified"][kind],
        response_hours=rng.choice(market["response_hours"]),
        segment=segment,
    )


# ---------------------------------------------------------------------------
# Exact posterior
# ---------------------------------------------------------------------------


def _log_binom(n: int, k: int, p: float) -> float:
    if k < 0 or k > n:
        return -math.inf
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def _log_record(profile: "Profile", kind: str, market: Mapping[str, Any]) -> float:
    """log P(orders, star counts, protected, on time | years, type). A bad
    supplier may have brushed f orders, each with a five-star review and never
    protected; the likelihood sums over f."""
    probs = _star_probs(kind, market)
    mean = _order_mean(profile.years_on_platform, profile.segment, market)
    c = profile.star_counts

    def given_fake(f: int) -> float:
        g = profile.orders - f
        if g < 0 or c[0] < f or profile.protected_orders > g:
            return -math.inf
        genuine_counts = (c[0] - f, *c[1:])
        total = sum(genuine_counts)
        out = -mean + g * math.log(mean) - math.lgamma(g + 1)  # genuine orders ~ Poisson
        out += _log_binom(g, total, market["review_rate"])
        if out == -math.inf:
            return out
        out += math.lgamma(total + 1)
        for n, p in zip(genuine_counts, probs):
            if n:
                if p <= 0:
                    return -math.inf
                out += n * math.log(p) - math.lgamma(n + 1)
        out += _log_binom(g, profile.protected_orders, market["protected_share"])
        out += _log_binom(profile.protected_orders, profile.on_time_protected, market["type"][kind]["on_time"])
        return out

    if kind == "good":
        return given_fake(0)
    b, fm = market["brushing"]["probability"], market["brushing"]["mean_fake"]
    terms = [math.log1p(-b) + given_fake(0)]
    # f = 0 happens either without brushing or with brushing that drew zero fakes
    terms.append(math.log(b) - fm + given_fake(0))
    for f in range(1, min(c[0], profile.orders) + 1):
        terms.append(math.log(b) + (-fm + f * math.log(fm) - math.lgamma(f + 1)) + given_fake(f))
    top = max(terms)
    return top + math.log(sum(math.exp(x - top) for x in terms)) if top > -math.inf else top


def log_likelihood(profile: "Profile", kind: str, market: Mapping[str, Any] = MARKET) -> float:
    """log P(profile | type, years). Years and reply time do not depend on type."""
    out = _log_record(profile, kind, market)
    for badge in ("gold", "verified"):
        p = market["badges"][badge][kind]
        out += math.log(p if getattr(profile, badge) else 1 - p)
    return out


def posterior_bad(profile: Profile, market: Mapping[str, Any] = MARKET) -> float:
    prior = market["prior_bad"][profile.segment]
    lb = math.log(prior) + log_likelihood(profile, "bad", market)
    lg = math.log1p(-prior) + log_likelihood(profile, "good", market)
    top = max(lb, lg)
    return math.exp(lb - top) / (math.exp(lb - top) + math.exp(lg - top))


# ---------------------------------------------------------------------------
# The case and its references
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Economics:
    periods: int = 4
    lot_units: int = 20
    revenue_per_unit: float = 10.0  # a defective display loses the kit
    sample_units: int = 10
    sample_cost: float = 9.0
    incumbent_price: float = 1.40
    challenger_price: float = 1.00


@lru_cache(maxsize=None)
def _pmf(units: int, rate: float) -> tuple[float, ...]:
    return tuple(math.exp(_log_binom(units, k, rate)) for k in range(units + 1))


def _update(b: float, units: int, defects: int, market: Mapping[str, Any]) -> float:
    pb = b * _pmf(units, market["type"]["bad"]["defect_rate"])[defects]
    pg = (1 - b) * _pmf(units, market["type"]["good"]["defect_rate"])[defects]
    return pb / (pb + pg) if pb + pg > 0 else b


def _defect_dist(b: float, units: int, market: Mapping[str, Any]) -> list[tuple[int, float]]:
    bad, good = _pmf(units, market["type"]["bad"]["defect_rate"]), _pmf(units, market["type"]["good"]["defect_rate"])
    return [(k, p) for k in range(units + 1) if (p := b * bad[k] + (1 - b) * good[k]) > 1e-12]


# A state is (periods left, belief incumbent bad, belief challenger bad, sampled incumbent, sampled challenger).
# A decision is (sample: None|"I"|"C", choose), where choose(bI, bC, sample_defects)
# names the supplier to buy from; sample_defects is None when nothing was sampled.
Policy = Callable[[int, float, float, bool, bool], tuple[str | None, Callable[[float, float, int | None], str]]]


def _period_value(
    econ: Economics, market: Mapping[str, Any], buy: str, bI: float, bC: float,
    truth: Mapping[str, str] | None, cont: Callable[[float, float], float],
) -> float:
    """Expected value of buying one lot from `buy` and continuing. A delivered
    lot shows which kind the supplier is (declared to the buyer), so the belief
    about `buy` becomes 0 or 1. Chance comes from the beliefs (ex ante) or from
    the truth (realised)."""
    price = econ.incumbent_price if buy == "I" else econ.challenger_price
    b = bI if buy == "I" else bC
    chance_b = b if truth is None else (1.0 if truth[buy] == "bad" else 0.0)
    total = 0.0
    for kind, p, nb in (("bad", chance_b, 1.0), ("good", 1 - chance_b, 0.0)):
        if p <= 0:
            continue
        cost = econ.lot_units * (price + market["type"][kind]["defect_rate"] * econ.revenue_per_unit)
        total += p * (-cost + cont(nb if buy == "I" else bI, nb if buy == "C" else bC))
    return total


def _key(x: float) -> float:
    return round(x, 6)


def solve(econ: Economics, bI: float, bC: float, market: Mapping[str, Any] = MARKET) -> dict[str, Any]:
    """Best policy on the buyer's information: value, and the value of each
    first-period action, all ex ante (in expectation over the buyer's beliefs)."""
    first = _state_values(econ, bI, bC, False, False, market)
    best = max(first, key=first.get)
    return {"value": first[best], "first_action": best, "first_action_values": first}


def oracle_value(econ: Economics, truth: Mapping[str, str], market: Mapping[str, Any] = MARKET) -> float:
    """Full information: buy the better supplier every period, never sample."""
    best = -math.inf
    for x in ("I", "C"):
        price = econ.incumbent_price if x == "I" else econ.challenger_price
        d = market["type"][truth[x]]["defect_rate"]
        best = max(best, -econ.periods * econ.lot_units * (price + d * econ.revenue_per_unit))
    return best


# Simple rules a buyer might follow instead of judging. They see only what a
# rule-follower would: prices, star averages, sample defect counts, and a
# delivered lot that turned out bad (belief exactly 1). None reads the posterior.
def _rule(name: str, profiles: Mapping[str, Profile]) -> Policy:
    def stay_unless_revealed(prefer: str) -> Callable[[float, float, int | None], str]:
        other = "I" if prefer == "C" else "C"
        return lambda bi, bc, d: other if (bi if prefer == "I" else bc) >= 1.0 else prefer

    if name == "stay_with_incumbent":
        return lambda t, bi, bc, si, sc: (None, lambda a, c, d: "I")
    if name == "cheapest_blind":
        return lambda t, bi, bc, si, sc: (None, stay_unless_revealed("C"))
    if name == "sample_cheapest":
        def after_sample(bi: float, bc: float, d: int | None) -> str:
            return "C" if d is not None and d <= 1 else "I"

        def policy(t: int, bi: float, bc: float, si: bool, sc: bool):
            if not sc:
                return "C", after_sample
            # a passed sample led to buying the challenger, whose lot then showed its kind
            # (belief 0 or 1); a failed sample left it unbought. Keep it only if shown good.
            return None, (lambda a, c, d: "C" if c == 0.0 else "I")

        return policy
    if name == "higher_stars":
        ri, rc = profiles["I"].rating or 0.0, profiles["C"].rating or 0.0
        pick = "C" if rc >= ri else "I"
        return lambda t, bi, bc, si, sc: (None, stay_unless_revealed(pick))
    raise ValueError(name)


RULES = ("stay_with_incumbent", "cheapest_blind", "sample_cheapest", "higher_stars")


def evaluate(
    policy: Policy, econ: Economics, bI: float, bC: float,
    truth: Mapping[str, str] | None = None, market: Mapping[str, Any] = MARKET,
) -> float:
    """Value of a fixed policy, ex ante (truth None) or realised under a truth."""

    def V(t: int, bi: float, bc: float, si: bool, sc: bool) -> float:
        if t == 0:
            return 0.0
        sample, choose = policy(t, bi, bc, si, sc)
        nxt = lambda s_i, s_c: (lambda a, c: V(t - 1, a, c, s_i, s_c))
        if sample is None:
            return _period_value(econ, market, choose(bi, bc, None), bi, bc, truth, nxt(si, sc))
        b = bi if sample == "I" else bc
        chance_b = b if truth is None else (1.0 if truth[sample] == "bad" else 0.0)
        val = -econ.sample_cost
        for defects, p in _defect_dist(chance_b, econ.sample_units, market):
            nb = _update(b, econ.sample_units, defects, market)
            ni, nc = (nb, bc) if sample == "I" else (bi, nb)
            nsi, nsc = (True, sc) if sample == "I" else (si, True)
            val += p * _period_value(econ, market, choose(ni, nc, defects), ni, nc, truth, nxt(nsi, nsc))
        return val

    return V(econ.periods, bI, bC, False, False)


# ---------------------------------------------------------------------------
# The pack: a crossed design screened so each cell's intended action is best
# ---------------------------------------------------------------------------

CELLS: dict[str, dict[str, Any]] = {
    # the challenger's record is long and clean, and the saving is large: switch without testing
    "switch_on_record": {"segment": "established", "band": (0.0, 0.03), "discount": (0.25, 0.34), "intended": "buy_C"},
    # a thin record and a large saving: the test is worth its price
    "test_thin_record": {"segment": "new", "band": (0.15, 0.5), "discount": (0.25, 0.34), "intended": "sample_C"},
    # a thin record and a small saving: the test costs more than it can earn back
    "not_worth_testing": {"segment": "new", "band": (0.15, 0.5), "discount": (0.06, 0.10), "intended": "buy_I"},
    # the challenger outrates the incumbent but the record is implausible (fake-review signature)
    "stars_mislead": {"segment": "new", "band": (0.6, 1.0), "discount": (0.25, 0.34), "intended": "buy_I", "outrates": True},
}

MIN_MARGIN_USD = 1.0
#: A twin (same record, the other hidden type) is added only when the record
#: leaves real doubt; outside this band the type drawn with the record stands.
TWIN_BAND = (0.1, 0.9)  # the intended first action must beat every other by at least this, ex ante


def _neutral_id(rng: random.Random) -> str:
    return "supplier_" + "".join(rng.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(4))


def build_world(seed: int, cell: str, market: Mapping[str, Any] = MARKET, max_draws: int = 20000) -> dict[str, Any] | None:
    """Draw an incumbent and a challenger for `cell`, keeping the first draw
    whose challenger posterior falls in the cell's band and whose intended
    action is best by MIN_MARGIN_USD. Returns None if no draw qualifies."""
    spec = CELLS[cell]
    rng = random.Random(seed)
    for _ in range(max_draws):
        inc_kind = "bad" if rng.random() < market["prior_bad"]["established"] else "good"
        inc = draw_profile(rng, supplier_id=_neutral_id(rng), segment="established", kind=inc_kind, market=market)
        seg = spec["segment"]
        ch_kind = "bad" if rng.random() < market["prior_bad"][seg] else "good"
        ch = draw_profile(rng, supplier_id=_neutral_id(rng), segment=seg, kind=ch_kind, market=market)
        bI, bC = posterior_bad(inc, market), posterior_bad(ch, market)
        lo, hi = spec["band"]
        if not (lo <= bC <= hi) or bI > 0.05:
            continue
        if spec.get("outrates") and not ((ch.rating or 0) > (inc.rating or 0)):
            continue
        price = round(rng.uniform(1.30, 1.45), 3)
        disc = rng.uniform(*spec["discount"])
        econ = Economics(incumbent_price=price, challenger_price=round(price * (1 - disc), 3), sample_cost=round(rng.uniform(8.3, 10.9), 2))
        sol = solve(econ, bI, bC, market)
        vals = sorted(sol["first_action_values"].values(), reverse=True)
        if sol["first_action"] != spec["intended"] or vals[0] - vals[1] < MIN_MARGIN_USD:
            continue
        order = ["I", "C"]
        rng.shuffle(order)
        return {
            "seed": seed,
            "cell": cell,
            "economics": asdict(econ),
            "profiles_in_listing_order": {r: asdict(inc if r == "I" else ch) for r in order},
            "profile_text": {r: (inc if r == "I" else ch).text() for r in order},
            "hidden": {"I": inc_kind, "C": ch_kind},
            "posterior_bad": {"I": bI, "C": bC},
            "buyer_information_reference": sol,
            "_profiles": {"I": inc, "C": ch},
        }
    return None


def with_truth(world: Mapping[str, Any], challenger: str, market: Mapping[str, Any] = MARKET) -> dict[str, Any]:
    """A twin: the same public record, the challenger's hidden type set. Twins
    test updating: before any evidence a good judge acts the same in both."""
    econ = Economics(**world["economics"])
    truth = {"I": world["hidden"]["I"], "C": challenger}
    bI, bC = world["posterior_bad"]["I"], world["posterior_bad"]["C"]
    best = world["buyer_information_reference"]
    out = {k: v for k, v in world.items() if k != "_profiles"}
    out["hidden"] = truth
    out["oracle_value"] = oracle_value(econ, truth, market)
    optimal_policy = _optimal_policy(econ, market)
    out["realised"] = {"buyer_information_reference": evaluate(optimal_policy, econ, bI, bC, truth, market)}
    out["ex_ante_regret_usd"] = {}
    for rule in RULES:
        pol = _rule(rule, world["_profiles"])
        out["ex_ante_regret_usd"][rule] = round(best["value"] - evaluate(pol, econ, bI, bC, None, market), 2)
        out["realised"][rule] = evaluate(pol, econ, bI, bC, truth, market)
    return out


def _optimal_policy(econ: Economics, market: Mapping[str, Any]) -> Policy:
    """The solved policy as a Policy, re-deciding from the DP at every state."""

    def policy(t: int, bi: float, bc: float, si: bool, sc: bool):
        sub = Economics(**{**asdict(econ), "periods": t})
        vals = _state_values(sub, bi, bc, si, sc, market)
        act = max(vals, key=vals.get)
        if act.startswith("sample_"):
            who = act[-1]

            def choose(ni: float, nc: float, _defects: int | None = None) -> str:
                nsi, nsc = (True, sc) if who == "I" else (si, True)
                v = _state_values(sub, ni, nc, nsi, nsc, market, buy_only=True)
                return max(v, key=v.get)[-1]

            return who, choose
        return None, (lambda a, c, d, x=act[-1]: x)

    return policy


def _state_values(econ: Economics, bi: float, bc: float, si: bool, sc: bool, market, buy_only: bool = False) -> dict[str, float]:
    # Re-solve from this state: the first-period action values with the given sample flags.
    @lru_cache(maxsize=None)
    def V(t: int, a: float, c: float, s_i: bool, s_c: bool) -> float:
        if t == 0:
            return 0.0
        return max(Q(t, a, c, s_i, s_c).values())

    def cont(t: int, s_i: bool, s_c: bool):
        return lambda a, c: V(t - 1, _key(a), _key(c), s_i, s_c)

    def Q(t: int, a: float, c: float, s_i: bool, s_c: bool) -> dict[str, float]:
        out = {f"buy_{x}": _period_value(econ, market, x, a, c, None, cont(t, s_i, s_c)) for x in ("I", "C")}
        if buy_only:
            return out
        for who, done in (("I", s_i), ("C", s_c)):
            if done:
                continue
            b = a if who == "I" else c
            val = -econ.sample_cost
            for defects, p in _defect_dist(b, econ.sample_units, market):
                nb = _update(b, econ.sample_units, defects, market)
                ni, nc = (nb, c) if who == "I" else (a, nb)
                nsi, nsc = (True, s_c) if who == "I" else (s_i, True)
                val += p * max(_period_value(econ, market, x, ni, nc, None, cont(t, nsi, nsc)) for x in ("I", "C"))
            out[f"sample_{who}"] = val
        return out

    return Q(econ.periods, _key(bi), _key(bc), si, sc)


def build_pack(seeds_per_cell: int = 2, base_seed: int = 2440000, market: Mapping[str, Any] = MARKET) -> list[dict[str, Any]]:
    worlds = []
    for ci, cell in enumerate(CELLS):
        found, seed = 0, base_seed + 1000 * ci
        while found < seeds_per_cell:
            w = build_world(seed, cell, market)
            seed += 1
            if w is None:
                continue
            found += 1
            worlds.append(with_truth(w, w["hidden"]["C"], market))
            if TWIN_BAND[0] < w["posterior_bad"]["C"] < TWIN_BAND[1]:
                flipped = "good" if w["hidden"]["C"] == "bad" else "bad"
                worlds.append({**with_truth(w, flipped, market), "twin_of": w["seed"]})
    return worlds


def _pct(ps: Sequence[float]) -> str:
    return "/".join(f"{p * 100:g}%" for p in ps)


def market_facts_text(market: Mapping[str, Any] = MARKET) -> str:
    """The declared market, as the buyer would be told it."""
    t = market["type"]
    return (
        f"About {market['prior_bad']['established']:.0%} of suppliers with {market['years']['established'][0]}+ years "
        f"on the platform, and {market['prior_bad']['new']:.0%} of those with {market['years']['new'][0]}-{market['years']['new'][1]} years, ship bad lots: a bad supplier's units are "
        f"defective {t['bad']['defect_rate']:.0%} of the time (a good one's {t['good']['defect_rate']:.0%}), it is on time "
        f"{t['bad']['on_time']:.0%} of the time (good {t['good']['on_time']:.0%}), and {t['bad']['problem_order']:.0%} of its "
        f"orders have a problem (good {t['good']['problem_order']:.0%}). About {market['review_rate']:.0%} of genuine orders get a "
        f"review. Genuine orders average {market['orders_per_year']['established']:.0f} a year for established suppliers and "
        f"{market['orders_per_year']['new']:.0f} a year for newer ones (a supplier under a year old counts as half a year). "
        f"Ratings run high: a review of an order without a problem gives 5/4/3/2/1 stars with probability "
        f"{_pct(market['stars_ok'])}, and of an order with a problem {_pct(market['stars_problem'])}. "
        f"{market['brushing']['probability']:.0%} of bad suppliers buy fake orders, on average "
        f"{market['brushing']['mean_fake']:.0f}, each with a five-star review; fake orders count in the order total but are "
        f"never protected. The on-time record counts only protected orders (about "
        f"{market['protected_share']:.0%} of orders). Gold is a paid membership held by "
        f"{market['badges']['gold']['good']:.0%} of suppliers of either kind; Verified checks the company, not the product "
        f"({market['badges']['verified']['good']:.0%} of good and {market['badges']['verified']['bad']:.0%} of bad suppliers "
        f"hold it). Reply speed says nothing about quality. A sample tests the units you ask for and shows their defects; a delivered lot shows which kind the supplier is."
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds-per-cell", type=int, default=2)
    ap.add_argument("--out", help="write the draft pack as JSON here")
    args = ap.parse_args(argv)
    pack = build_pack(args.seeds_per_cell)
    for w in pack:
        ref = w["buyer_information_reference"]
        print(f"{w['cell']:<18} seed {w['seed']} challenger {w['hidden']['C']:<4} P(bad)={w['posterior_bad']['C']:.2f} "
              f"best={ref['first_action']:<9} oracle-ref(realised)={w['oracle_value'] - w['realised']['buyer_information_reference']:6.1f}  "
              + " ".join(f"{r}={v:.1f}" for r, v in w["ex_ante_regret_usd"].items()))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump({"market": MARKET, "market_facts": market_facts_text(), "worlds": pack}, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
