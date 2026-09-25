"""Integrator and client negotiating who carries which risk: the economics and the reference.

Draft for the integrator-client case that replaces the joint-venture scope. A
client commissions an integrator to deliver a GPU cluster into the client's own
facility. What they negotiate is not only the price but the contract: which party
pays when each risk event happens. Every risk has a declared distribution that
both parties know, and the integrator's competence is public; nothing about
quality is hidden. What is private is what it costs the *integrator* to carry
each risk, and the only way the client learns it is by asking the integrator to
price alternatives.

Three things make one contract better than another for both parties together,
and all three are in the world data:

- **Control.** A compatibility defect is less likely if the integrator pre-stages
  the cluster, and it does so only if the contract makes it pay for defects
  (the warranty). A readiness delay is the client's facility; an integrator made
  to carry it adds a contingency because it cannot control it.
- **Risk charge.** Each party pays a charge on the expected contingent losses it
  carries (covenant pressure, insurance). A loss belongs with the party whose
  charge is lower. The client's charge is declared; the integrator's is private.
- **Capital.** A hardware deposit at signing saves the integrator financing and
  costs the client financing plus exposure to the integrator's insolvency.

So a clause can create value (it moves a risk to the cheaper bearer or buys a
pre-staging test), or only move money (then its price is its cost to the other
side), or destroy value (demanding a risk the integrator cannot control). Price
never changes the joint value; it only divides it.

The integrator's conduct is declared: it signs any package at its own cost of
that package plus its floor margin plus an ask premium that falls each round; a
proposal below that is answered with the price at which it would sign the same
package this round; after each refusal it may break off (probability ``beta``).
The client's outside option is a turnkey contract at a known all-in cost.

Because every cost is an exact expectation over declared events, the client's
best play on its own information is a small dynamic programme over which private
integrator types are still consistent with the prices seen (:func:`solve`). A
decision is graded by what the client could have known at the time, not by the
hidden type, and no random draw enters the score.

Stated simplifications: expectations stand in for realised outcomes (grading is
ex ante); the four risk events are independent; one delay cost per week; the
integrator's pre-staging choice is its best response to the contract; liquidated
damages are uncapped. Not modelled: the integrator seat (the same facts, next),
multi-party projects, renegotiation after signing.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

# Money is in $ thousands throughout.

# ---------------------------------------------------------------------------
# Contract terms. A package is one level of each.

TERMS: dict[str, tuple[str, ...]] = {
    "warranty": ("none", "fix", "fix_and_delay"),  # who pays a compatibility defect
    "readiness": ("client", "integrator"),  # who pays standby if the facility is not ready
    "consequential": ("excluded", "included"),  # who pays a post-handover incident's losses
    "deposit": ("at_signing", "on_delivery"),  # half the hardware paid at signing, or on delivery
}


@dataclass(frozen=True, order=True)
class Package:
    warranty: str
    readiness: str
    consequential: str
    deposit: str

    def label(self) -> str:
        return f"{self.warranty}/{self.readiness}/{self.consequential}/{self.deposit}"


PACKAGES: tuple[Package, ...] = tuple(Package(*levels) for levels in itertools.product(*TERMS.values()))
OPENING = Package("none", "client", "excluded", "at_signing")  # the integrator's own proposal: every risk on the client
EVERY_PROTECTION = Package("fix_and_delay", "integrator", "included", "on_delivery")


# ---------------------------------------------------------------------------
# The world. Everything here except `integrator` is told to the client.


@dataclass(frozen=True)
class Risks:
    defect_without_test: float  # compatibility defect probability if the integrator does not pre-stage
    defect_with_test: float
    defect_fix: float  # $k to fix
    defect_weeks: float  # go-live delay
    unready: float  # facility-not-ready probability (the client's facility)
    standby: float  # $k integrator crew and staging while waiting
    unready_weeks: float
    incident: float  # post-handover incident probability in the warranty year
    incident_loss: float  # $k the client loses (idle cluster, credits to its own customers)


@dataclass(frozen=True)
class Client:
    delay_per_week: float  # $k revenue lost per week of late go-live
    risk_charge: float  # extra cost per $ of expected contingent loss carried
    capital_rate: float  # annual cost of capital
    insolvency: float  # probability the integrator fails while holding the deposit (deposit lost)
    turnkey_all_in: float  # $k: the outside option, a turnkey contract with every risk priced in


@dataclass(frozen=True)
class Terms:
    hardware: float  # $k, passed through at cost
    services: float  # $k, the integrator's own delivery cost
    deposit_share: float  # of hardware, if paid at signing
    deposit_weeks: float  # between signing and delivery
    delay_damages_per_week: float  # $k, under "fix_and_delay"
    uncontrolled_contingency: float  # the integrator's surcharge on expected standby it cannot control
    integrator_capital_rate: float
    floor_margin: float  # $k over its own cost
    ask_premium: tuple[float, ...]  # above the floor: the opening, then each client round
    breakoff: float  # probability the integrator breaks off after a refused proposal
    round_cost: float  # $k the client loses for each refused proposal (a week of team time and site holding)


@dataclass(frozen=True)
class IntegratorType:
    """Private to the integrator. The client knows only the declared prior."""

    test_cost: float  # $k to pre-stage and burn in the cluster before shipping
    risk_charge: float


TYPE_PRIOR: tuple[tuple[IntegratorType, float], ...] = tuple(
    (IntegratorType(t, c), 1.0 / 6.0) for t in (40.0, 120.0, 200.0) for c in (0.3, 1.2)
)


@dataclass(frozen=True)
class World:
    risks: Risks
    client: Client
    terms: Terms
    prior: tuple[tuple[IntegratorType, float], ...] = TYPE_PRIOR

    @property
    def rounds(self) -> int:
        return len(self.terms.ask_premium) - 1


# ---------------------------------------------------------------------------
# Expected costs. Exact: each event is a Bernoulli with a declared probability.


def _deposit(w: World) -> float:
    return w.terms.deposit_share * w.terms.hardware


def _bear(pkg: Package, w: World) -> float:
    """What the integrator pays per compatibility defect under this package."""
    r, t = w.risks, w.terms
    return (r.defect_fix if pkg.warranty != "none" else 0.0) + (t.delay_damages_per_week * r.defect_weeks if pkg.warranty == "fix_and_delay" else 0.0)


def pre_stages(pkg: Package, w: World, it: IntegratorType) -> bool:
    """The integrator's best response: pre-stage when the defects it would avoid cost it more than the test."""
    avoided = (w.risks.defect_without_test - w.risks.defect_with_test) * (1.0 + it.risk_charge) * _bear(pkg, w)
    return avoided > it.test_cost


def defect_probability(pkg: Package, w: World, it: IntegratorType) -> float:
    return w.risks.defect_with_test if pre_stages(pkg, w, it) else w.risks.defect_without_test


def integrator_cost(pkg: Package, w: World, it: IntegratorType) -> float:
    r, t = w.risks, w.terms
    p = defect_probability(pkg, w, it)
    contingent = p * _bear(pkg, w)
    if pkg.readiness == "integrator":
        contingent += r.unready * r.standby
    if pkg.consequential == "included":
        contingent += r.incident * r.incident_loss
    cost = t.hardware + t.services + (it.test_cost if pre_stages(pkg, w, it) else 0.0) + (1.0 + it.risk_charge) * contingent
    if pkg.readiness == "integrator":
        cost += t.uncontrolled_contingency * r.unready * r.standby
    if pkg.deposit == "at_signing":
        cost -= t.integrator_capital_rate * _deposit(w) * t.deposit_weeks / 52.0
    return cost


def client_cost(pkg: Package, w: World, it: IntegratorType) -> float:
    """The client's expected cost of a package apart from its price. It depends on the
    integrator's type only through whether the integrator pre-stages."""
    r, c, t = w.risks, w.client, w.terms
    p = defect_probability(pkg, w, it)
    contingent = p * r.defect_weeks * c.delay_per_week + r.unready * r.unready_weeks * c.delay_per_week
    if pkg.warranty == "none":
        contingent += p * r.defect_fix
    if pkg.warranty == "fix_and_delay":
        contingent -= p * t.delay_damages_per_week * r.defect_weeks
    if pkg.readiness == "client":
        contingent += r.unready * r.standby
    if pkg.consequential == "excluded":
        contingent += r.incident * r.incident_loss
    cost = (1.0 + c.risk_charge) * contingent
    if pkg.deposit == "at_signing":
        cost += c.capital_rate * _deposit(w) * t.deposit_weeks / 52.0 + (1.0 + c.risk_charge) * c.insolvency * _deposit(w)
    return cost


def joint_cost(pkg: Package, w: World, it: IntegratorType) -> float:
    return integrator_cost(pkg, w, it) + client_cost(pkg, w, it)


def efficient_package(w: World, it: IntegratorType) -> Package:
    return min(PACKAGES, key=lambda p: (round(joint_cost(p, w, it), 6), p != OPENING, p))


def floor_price(pkg: Package, w: World, it: IntegratorType) -> float:
    return integrator_cost(pkg, w, it) + w.terms.floor_margin


def ask_price(pkg: Package, w: World, it: IntegratorType, round_: int) -> float:
    """The price at which the integrator signs this package in this round (0 = its opening)."""
    return floor_price(pkg, w, it) + w.terms.ask_premium[round_]


def opening_price(w: World, it: IntegratorType) -> float:
    return ask_price(OPENING, w, it, 0)


# ---------------------------------------------------------------------------
# The reference: the client's best play on its own information.
#
# State at the client's move in round t (1..rounds): the set of integrator types
# still consistent with every price seen, and the standing offer (a package and
# the price at which the integrator has said it would sign it). The client may
# accept the standing offer, walk to the turnkey option, or propose a package at
# a price. A proposal at or above the integrator's ask is signed; below it the
# integrator breaks off with probability beta or counters with its ask for that
# package this round, which becomes the standing offer and narrows the types.
# After the last round's counter the client can only accept it or walk.
#
# Only the asks of consistent types are worth proposing at (anything between two
# asks is signed by the same types at a higher price), plus a price below every
# ask, which is a pure request to price the package.

LOWBALL = "price_it"


@dataclass(frozen=True)
class Action:
    kind: str  # accept | walk | propose
    package: Package | None = None
    price: float | str | None = None  # a number, or LOWBALL

    def label(self) -> str:
        if self.kind != "propose":
            return self.kind
        price = "ask for its price" if self.price == LOWBALL else f"at {self.price:,.0f}"
        return f"propose {self.package.label()} {price}"


def _key(x: float) -> float:
    return round(x, 6)


class Solver:
    """Exact expected client cost of the best play, memoised on (round, types)."""

    def __init__(self, w: World) -> None:
        self.w = w
        self.types = tuple(t for t, _ in w.prior)
        self.weight = {t: p for t, p in w.prior}
        self._best: dict[tuple[int, frozenset], tuple[float, Action]] = {}

    def _mean(self, types: frozenset, f: Callable[[IntegratorType], float]) -> float:
        z = sum(self.weight[t] for t in types)
        return sum(self.weight[t] * f(t) for t in types) / z

    def accept_value(self, types: frozenset, standing: tuple[Package, float]) -> float:
        pkg, price = standing
        return price + self._mean(types, lambda t: client_cost(pkg, self.w, t))

    def _prices(self, types: frozenset, pkg: Package, round_: int) -> list[float | str]:
        return [LOWBALL, *sorted({_key(ask_price(pkg, self.w, t, round_)) for t in types})]

    def proposal_value(self, round_: int, types: frozenset, pkg: Package, price: float | str) -> float:
        w, z = self.w, sum(self.weight[t] for t in types)
        total = 0.0
        refused: dict[float, list[IntegratorType]] = {}
        for t in types:
            ask = _key(ask_price(pkg, w, t, round_))
            if price != LOWBALL and price >= ask - 1e-9:
                total += self.weight[t] * (price + client_cost(pkg, w, t))
            else:
                refused.setdefault(ask, []).append(t)
        for ask, group in refused.items():
            g = frozenset(group)
            mass = sum(self.weight[t] for t in g)
            if round_ < w.rounds:
                after = self.value(round_ + 1, g, (pkg, ask))
            else:
                after = min(w.client.turnkey_all_in, self.accept_value(g, (pkg, ask)))
            total += mass * (w.terms.round_cost + w.terms.breakoff * w.client.turnkey_all_in + (1.0 - w.terms.breakoff) * after)
        return total / z

    def best_proposal(self, round_: int, types: frozenset) -> tuple[float, Action]:
        key = (round_, types)
        if key not in self._best:
            best: tuple[float, Action] | None = None
            for pkg in PACKAGES:
                for price in self._prices(types, pkg, round_):
                    v = self.proposal_value(round_, types, pkg, price)
                    if best is None or v < best[0] - 1e-9:
                        best = (v, Action("propose", pkg, price))
            self._best[key] = best
        return self._best[key]

    def q_values(self, round_: int, types: frozenset, standing: tuple[Package, float]) -> dict[Action, float]:
        """Expected client cost of each first action here, each followed by the best play."""
        q = {Action("walk"): self.w.client.turnkey_all_in, Action("accept"): self.accept_value(types, standing)}
        for pkg in PACKAGES:
            for price in self._prices(types, pkg, round_):
                q[Action("propose", pkg, price)] = self.proposal_value(round_, types, pkg, price)
        return q

    def value(self, round_: int, types: frozenset, standing: tuple[Package, float]) -> float:
        return min(self.w.client.turnkey_all_in, self.accept_value(types, standing), self.best_proposal(round_, types)[0])

    def opening_types(self, observed_opening: float) -> frozenset:
        return frozenset(t for t in self.types if abs(opening_price(self.w, t) - observed_opening) < 1e-6)


def solve(w: World, truth: IntegratorType) -> dict[str, Any]:
    """The reference at the start: its expected cost and first action, given the opening the client saw."""
    s = Solver(w)
    opening = opening_price(w, truth)
    types = s.opening_types(opening)
    q = s.q_values(1, types, (OPENING, opening))
    best = min(q, key=lambda a: (_key(q[a]), a.kind != "accept", a.kind != "walk"))
    return {"expected_cost": q[best], "first_action": best, "q": q, "types": types, "opening_price": opening}


# ---------------------------------------------------------------------------
# Playing a policy against the scripted integrator, in expectation.
#
# A policy sees what the client sees (:class:`Seen`) and returns an Action.
# Break-off is the only chance event, so a policy's expected cost is exact.


@dataclass(frozen=True)
class Seen:
    round: int
    opening_price: float
    standing: tuple[Package, float]
    history: tuple[dict[str, Any], ...]  # each refused proposal: round, package, price, counter
    final: bool  # the standing offer is the last round's counter: accept or walk


Policy = Callable[[Seen], Action]


def expected_cost(w: World, truth: IntegratorType, policy: Policy) -> float:
    opening = opening_price(w, truth)

    def go(round_: int, standing: tuple[Package, float], history: tuple[dict[str, Any], ...], final: bool) -> float:
        act = policy(Seen(round_, opening, standing, history, final))
        if act.kind == "walk":
            return w.client.turnkey_all_in
        if act.kind == "accept":
            return standing[1] + client_cost(standing[0], w, truth)
        if final:
            raise ValueError("after the last round's counter the client can only accept or walk")
        ask = ask_price(act.package, w, truth, round_)
        if act.price != LOWBALL and act.price >= ask - 1e-6:
            return act.price + client_cost(act.package, w, truth)
        step = history + ({"round": round_, "package": act.package, "price": act.price, "counter": ask},)
        last = round_ == w.rounds
        after = go(round_ if last else round_ + 1, (act.package, ask), step, last)
        return w.terms.round_cost + w.terms.breakoff * w.client.turnkey_all_in + (1.0 - w.terms.breakoff) * after

    return go(1, (OPENING, opening), (), False)


def consistent_types(s: Solver, seen: Seen) -> frozenset:
    types = s.opening_types(seen.opening_price)
    for h in seen.history:
        types = frozenset(t for t in types if abs(ask_price(h["package"], s.w, t, h["round"]) - h["counter"]) < 1e-6)
    return types


def reference_policy(w: World) -> Policy:
    s = Solver(w)

    def act(seen: Seen) -> Action:
        types = consistent_types(s, seen)
        if seen.final:
            q = {Action("walk"): w.client.turnkey_all_in, Action("accept"): s.accept_value(types, seen.standing)}
        else:
            q = s.q_values(seen.round, types, seen.standing)
        return min(q, key=lambda a: (_key(q[a]), a.kind != "accept", a.kind != "walk"))

    return act


def decision_regret(w: World, seen: Seen, action: Action) -> float:
    """What this action gives up against the best one, in expected client cost, on the client's information."""
    s = Solver(w)
    types = consistent_types(s, seen)
    if seen.final:
        q = {Action("walk"): w.client.turnkey_all_in, Action("accept"): s.accept_value(types, seen.standing)}
        return q[action] - min(q.values())
    q = s.q_values(seen.round, types, seen.standing)
    if action not in q:  # a price that is not one of the consistent asks: value it directly
        q[action] = s.proposal_value(seen.round, types, action.package, action.price)
    return q[action] - min(q.values())


# ---------------------------------------------------------------------------
# Rules that do not negotiate the risk allocation. Each is right somewhere.
#
# They are competent at price: after one counter they sign at the floor the
# counter implies (counter less this round's premium), so a rule loses only for
# the allocation it chose or the pace it kept, never for arithmetic.


def _floor_from_counter(w: World, seen: Seen) -> float:
    h = seen.history[-1]
    return h["counter"] - w.terms.ask_premium[h["round"]] + w.terms.ask_premium[seen.round]


def _price_then_sign(w: World, pick: Callable[[World], Package]) -> Policy:
    def act(seen: Seen) -> Action:
        if seen.final:
            return Action("accept")
        pkg = pick(w)
        if not seen.history:
            return Action("propose", pkg, LOWBALL)
        return Action("propose", pkg, _floor_from_counter(w, seen))

    return act


def prior_best_package(w: World) -> Package:
    """The package with the lowest expected joint cost under the prior: the best a party can do without asking."""
    return min(PACKAGES, key=lambda p: (_key(sum(q * joint_cost(p, w, t) for t, q in w.prior)), p))


def _sign_now(w: World) -> Policy:
    """Sign the prior-best package at once, at the highest price any consistent type could ask."""
    s = Solver(w)

    def act(seen: Seen) -> Action:
        if seen.final or seen.history:
            return Action("accept")
        pkg = prior_best_package(w)
        types = consistent_types(s, seen)
        return Action("propose", pkg, max(_key(ask_price(pkg, w, t, seen.round)) for t in types))

    return act


def rules(w: World) -> dict[str, Policy]:
    return {
        "accept_the_opening": lambda seen: Action("accept"),
        "walk_to_turnkey": lambda seen: Action("walk"),  # also "defensive terms are a red flag"
        "take_the_first_counter": lambda seen: Action("accept") if seen.history else Action("propose", prior_best_package(w), LOWBALL),
        "haggle_price_only": _price_then_sign(w, lambda _: OPENING),
        "demand_every_protection": _price_then_sign(w, lambda _: EVERY_PROTECTION),
        "sign_the_prior_best_now": _sign_now(w),
    }


def prior_expected(w: World, policy: Policy) -> float:
    """A policy's expected client cost over the declared prior on the integrator's type."""
    return sum(p * expected_cost(w, t, policy) for t, p in w.prior)


# ---------------------------------------------------------------------------
# The pack: cells, each rewarding a different way of negotiating the allocation.
#
# A world's public facts are drawn from its cell's ranges; the integrator's type
# is drawn from the declared prior. A world is admitted only if its intended
# first move beats every other kind of first move by MARGIN in expectation, and
# every rule named as a loser gives up at least LOSER_MARGIN. Where the right
# contract depends on the hidden type, a twin with the same public facts and a
# type whose efficient contract differs is added: before any price is seen a
# good negotiator opens the same way in both.

MARGIN = 10.0
LOSER_MARGIN = 25.0

FIXED_TERMS = dict(
    hardware=9600.0, services=600.0, deposit_share=0.5, deposit_weeks=13.0, delay_damages_per_week=100.0,
    uncontrolled_contingency=1.5, integrator_capital_rate=0.14, floor_margin=500.0, ask_premium=(400.0, 200.0, 0.0),
    round_cost=25.0,
)

# ranges drawn uniformly; turnkey_offset is added to the price-only deal (the opening package at its floor)
_COMMON = dict(
    defect_without_test=(0.25, 0.35), defect_with_test=(0.04, 0.08), defect_fix=(200.0, 300.0), defect_weeks=(3.0, 5.0),
    unready=(0.2, 0.3), standby=(150.0, 220.0), unready_weeks=(2.0, 4.0), incident=(0.04, 0.06), incident_loss=(2500.0, 3500.0),
    delay_per_week=(90.0, 130.0), risk_charge=(0.5, 0.9), capital_rate=(0.05, 0.07), insolvency=(0.0, 0.015),
    breakoff=(0.05, 0.12), turnkey_offset=(300.0, 900.0),
)

CELLS: dict[str, dict[str, Any]] = {
    "keep_their_terms": {
        "lesson": "the integrator's defensive proposal is already the efficient contract; negotiate the price, not the terms",
        "ranges": dict(defect_without_test=(0.08, 0.12), defect_with_test=(0.06, 0.08), risk_charge=(0.05, 0.25), insolvency=(0.0, 0.008)),
        "first": {"price_it"},
        "losers": ("accept_the_opening", "walk_to_turnkey", "demand_every_protection", "sign_the_prior_best_now"),
    },
    "price_the_alternatives": {
        "lesson": "which risks to move depends on what the integrator charges to carry them; ask it to price the alternative first",
        "ranges": dict(breakoff=(0.03, 0.08)),
        "first": {"price_alternative"},
        "losers": ("haggle_price_only", "take_the_first_counter", "sign_the_prior_best_now"),
        "twins": True,
    },
    "shift_the_tail": {
        "lesson": "the client cannot carry the incident tail as cheaply as any integrator can; move it and the delay risk across",
        "ranges": dict(risk_charge=(1.4, 1.7)),
        "first": {"price_alternative"},
        "losers": ("accept_the_opening", "haggle_price_only", "take_the_first_counter"),
    },
    "better_contract_or_walk": {
        "lesson": "on the integrator's terms the deal loses to turnkey; only a better allocation beats walking away",
        "ranges": dict(breakoff=(0.03, 0.08), turnkey_offset=(-170.0, -60.0)),
        "first": {"price_alternative"},
        "losers": ("walk_to_turnkey", "haggle_price_only", "accept_the_opening"),
        "twins": True,
    },
    "walk_away": {
        "lesson": "no allocation of these risks beats the turnkey offer; walk before spending a round",
        "ranges": dict(turnkey_offset=(-700.0, -450.0)),
        "first": {"walk"},
        "losers": ("haggle_price_only", "demand_every_protection", "take_the_first_counter"),
    },
    "close_now": {
        "lesson": "the integrator is likely to walk after a refusal and the deal is worth far more than turnkey; sign now",
        "ranges": dict(risk_charge=(1.4, 1.7), breakoff=(0.35, 0.5), turnkey_offset=(1000.0, 1400.0)),
        "first": {"sign_at_a_price"},
        "losers": ("haggle_price_only", "take_the_first_counter", "demand_every_protection"),
    },
}


def first_move_kind(w: World, types: frozenset, a: Action) -> str:
    if a.kind in ("accept", "walk"):
        return a.kind
    if a.price == LOWBALL:
        return "price_opening" if a.package == OPENING else "price_alternative"
    return "sign_at_a_price"


def _kinds(w: World, first: Mapping[Action, float], types: frozenset) -> dict[str, float]:
    best: dict[str, float] = {}
    for a, v in first.items():
        k = first_move_kind(w, types, a)
        best[k] = min(best.get(k, float("inf")), v)
    best["price_it"] = min(best["price_opening"], best["price_alternative"])
    return best


def _round(x: float, step: float) -> float:
    return round(round(x / step) * step, 6)


def draw_world(rng: random.Random, cell: str) -> World:
    spec = {**_COMMON, **CELLS[cell]["ranges"]}
    u = {k: rng.uniform(*v) for k, v in spec.items()}
    risks = Risks(
        defect_without_test=_round(u["defect_without_test"], 0.01), defect_with_test=_round(u["defect_with_test"], 0.01),
        defect_fix=_round(u["defect_fix"], 10), defect_weeks=_round(u["defect_weeks"], 1), unready=_round(u["unready"], 0.01),
        standby=_round(u["standby"], 10), unready_weeks=_round(u["unready_weeks"], 1), incident=_round(u["incident"], 0.005),
        incident_loss=_round(u["incident_loss"], 100),
    )
    terms = Terms(**FIXED_TERMS, breakoff=_round(u["breakoff"], 0.01))
    client = Client(
        delay_per_week=_round(u["delay_per_week"], 5), risk_charge=_round(u["risk_charge"], 0.05),
        capital_rate=_round(u["capital_rate"], 0.005), insolvency=_round(u["insolvency"], 0.001), turnkey_all_in=0.0,
    )
    w = World(risks, client, terms)
    price_only = floor_price(OPENING, w, w.prior[0][0]) + client_cost(OPENING, w, w.prior[0][0])  # type-free for the opening
    return replace(w, client=replace(client, turnkey_all_in=_round(price_only + u["turnkey_offset"], 10)))


def admit(w: World, truth: IntegratorType, cell: str) -> dict[str, Any] | None:
    spec = CELLS[cell]
    ref = solve(w, truth)
    kinds = _kinds(w, ref["q"], ref["types"])
    intended = min(kinds[k] for k in spec["first"])
    others = [v for k, v in kinds.items() if k not in spec["first"] and not (k == "price_it" or (k.startswith("price_") and "price_it" in spec["first"]))]
    if min(others) - intended < MARGIN:
        return None
    policy = reference_policy(w)
    ref_cost = prior_expected(w, policy)
    regrets = {name: prior_expected(w, rule) - ref_cost for name, rule in rules(w).items()}
    if any(regrets[name] < LOSER_MARGIN for name in spec["losers"]):
        return None
    return {"reference": ref, "reference_prior_cost": ref_cost, "rule_regret": regrets, "first_move_values": kinds}


def build_world(seed: int, cell: str, max_draws: int = 4000) -> dict[str, Any] | None:
    rng = random.Random(seed)
    for _ in range(max_draws):
        w = draw_world(rng, cell)
        truth = rng.choices([t for t, _ in w.prior], [p for _, p in w.prior])[0]
        admitted = admit(w, truth, cell)
        if admitted is not None:
            return _summarise(w, truth, cell, seed, admitted)
    return None


def with_truth(row: Mapping[str, Any], w: World, truth: IntegratorType) -> dict[str, Any]:
    admitted = admit(w, truth, row["cell"])
    assert admitted is not None, "admission depends only on public facts and the prior"
    twin = _summarise(w, truth, row["cell"], row["seed"], admitted)
    twin["twin_of"] = row["slug"]
    twin["slug"] = row["slug"] + "_twin"
    return twin


def _summarise(w: World, truth: IntegratorType, cell: str, seed: int, admitted: Mapping[str, Any]) -> dict[str, Any]:
    ref = admitted["reference"]
    eff = efficient_package(w, truth)
    return {
        "slug": f"{cell}_{seed}",
        "cell": cell,
        "seed": seed,
        "lesson": CELLS[cell]["lesson"],
        "world": world_to_dict(w),
        "hidden_type": asdict(truth),
        "opening_price": ref["opening_price"],
        "reference_first_move": {"kind": first_move_kind(w, ref["types"], ref["first_action"]), "action": ref["first_action"].label()},
        "reference_expected_cost": ref["expected_cost"],
        "first_move_values": {k: round(v - ref["expected_cost"], 3) for k, v in sorted(admitted["first_move_values"].items())},
        "rule_regret_prior": {k: round(v, 3) for k, v in admitted["rule_regret"].items()},
        "efficient_package": eff.label(),
        "joint_saving_vs_opening": round(joint_cost(OPENING, w, truth) - joint_cost(eff, w, truth), 3),
    }


def build_pack(seeds_per_cell: int = 2, base_seed: int = 2460000) -> list[dict[str, Any]]:
    pack: list[dict[str, Any]] = []
    for ci, cell in enumerate(CELLS):
        made, seed = 0, base_seed + 1000 * ci
        while made < seeds_per_cell:
            row = build_world(seed, cell)
            seed += 1
            if row is None:
                continue
            pack.append(row)
            made += 1
            if CELLS[cell].get("twins"):
                w = world_from_dict(row["world"])
                truth = IntegratorType(**row["hidden_type"])
                other = next((t for t, _ in w.prior if efficient_package(w, t) != efficient_package(w, truth)), None)
                if other is not None:
                    pack.append(with_truth(row, w, other))
    return pack


def world_to_dict(w: World) -> dict[str, Any]:
    return {"risks": asdict(w.risks), "client": asdict(w.client), "terms": asdict(w.terms), "prior": [[asdict(t), p] for t, p in w.prior]}


def world_from_dict(d: Mapping[str, Any]) -> World:
    terms = dict(d["terms"])
    terms["ask_premium"] = tuple(terms["ask_premium"])
    return World(Risks(**d["risks"]), Client(**d["client"]), Terms(**terms), tuple((IntegratorType(**t), p) for t, p in d["prior"]))


# ---------------------------------------------------------------------------
# What the client is told. Every number the reference uses is here.


def brief_text(w: World, opening: float) -> str:
    r, c, t = w.risks, w.client, w.terms
    tests = sorted({it.test_cost for it, _ in w.prior})
    charges = sorted({it.risk_charge for it, _ in w.prior})
    k = lambda x: f"${x:,.0f}k" if abs(x - round(x)) < 0.05 else f"${x:,.1f}k"
    pct = lambda x: f"{100 * x:g}%"
    return "\n".join([
        "You are the client. An integrator will deliver a GPU cluster into your facility. Money is in $ thousands.",
        f"Hardware {k(t.hardware)} at cost; the integrator's own delivery cost {k(t.services)}.",
        "",
        "Risks (both parties know these):",
        f"- Compatibility defect: {pct(r.defect_without_test)} likely, or {pct(r.defect_with_test)} if the integrator pre-stages and burns in the cluster first. "
        f"Fixing it costs {k(r.defect_fix)} and delays go-live {r.defect_weeks:g} weeks. The integrator pre-stages only if the contract makes that cheaper for it.",
        f"- Your facility not ready: {pct(r.unready)} likely; {r.unready_weeks:g} weeks' delay and {k(r.standby)} of integrator standby.",
        f"- Post-handover incident in the first year: {pct(r.incident)} likely; you would lose {k(r.incident_loss)}.",
        f"- Each week of delay costs you {k(c.delay_per_week)} of revenue.",
        "",
        "Contract terms to settle, besides price:",
        f"- warranty: none (you pay a defect) | fix (it pays the fix) | fix_and_delay (it pays the fix and {k(t.delay_damages_per_week)} per week of defect delay)",
        "- readiness: client (you pay standby if your facility is late) | integrator (it does)",
        "- consequential: excluded (you carry an incident's losses) | included (it does)",
        f"- deposit: at_signing ({pct(t.deposit_share)} of hardware, {k(t.deposit_share * t.hardware)}, paid {t.deposit_weeks:g} weeks before delivery) | on_delivery",
        "",
        "Your position:",
        f"- Each $1 of expected loss you carry costs you ${1 + c.risk_charge:.2f} (covenants and insurance).",
        f"- Your capital costs {pct(c.capital_rate)} a year. If you pay the deposit, there is a {pct(c.insolvency)} chance the integrator fails before delivery and it is lost.",
        f"- Outside option: a turnkey contract at {k(c.turnkey_all_in)} all in, every risk priced in.",
        "",
        "The integrator:",
        f"- Each $1 of expected loss it carries costs it $1 plus its own risk charge, which is {' or '.join(f'{x:g}' for x in charges)} (equally likely; not disclosed).",
        f"- Pre-staging costs it {' or '.join(k(x) for x in tests)} (equally likely; not disclosed).",
        f"- It adds {pct(t.uncontrolled_contingency)} of expected standby if it carries your facility's readiness, which it cannot control.",
        f"- Its capital costs {pct(t.integrator_capital_rate)} a year, so a deposit at signing saves it financing.",
        f"- It signs any package at its expected cost of that package plus {k(t.floor_margin)}, plus an ask premium: "
        + ", ".join(f"{k(x)} in round {i}" for i, x in enumerate(t.ask_premium) if i) + f" (its opening carried {k(t.ask_premium[0])}).",
        "- A proposal below that is answered with the price at which it would sign that same package in that round.",
        f"- After each proposal it refuses, it breaks off {pct(t.breakoff)} of the time. Each refused proposal also costs you {k(t.round_cost)}.",
        "",
        f"Its opening proposal: warranty none, readiness client, consequential excluded, deposit at_signing, at {k(opening)}.",
        f"You have {w.rounds} rounds. In each you may accept the standing offer, walk to turnkey, or propose a package and a price. "
        "After the last round's answer you may only accept it or walk.",
        "Your objective: the lowest expected total cost to you: the price, plus every expected loss you carry at your risk charge, "
        "plus deposit financing and the cost of refused rounds.",
    ])


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds-per-cell", type=int, default=2)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args(argv)
    pack = build_pack(args.seeds_per_cell)
    text = json.dumps({"worlds": pack}, indent=2, sort_keys=True, default=str) + "\n"
    if args.out:
        open(args.out, "w").write(text)
    for row in pack:
        print(f"{row['slug']:34} {row['reference_first_move']['kind']:18} eff={row['efficient_package']:44} "
              + " ".join(f"{k[:10]}={v:.0f}" for k, v in row["rule_regret_prior"].items()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
