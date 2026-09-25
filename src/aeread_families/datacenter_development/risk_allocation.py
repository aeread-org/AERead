"""Integrator and client negotiating who carries which risk: the economics and the reference.

The case that replaces the joint-venture scope. A client commissions an
integrator to deliver a GPU cluster into the client's own facility. What they
negotiate is not only the price but the contract: which party pays when each
risk event happens. Every risk has a declared distribution that both parties
know, and the integrator's competence is public; nothing about quality is
hidden. What is private is what it costs each party to carry risk, and the only
way to learn the other side's cost is to ask it to price a contract.

Three things make one contract better than another for both parties together,
and all three are in the world data:

- **Control.** A compatibility defect is less likely if the integrator pre-stages
  the cluster, and it does so only if the contract makes it pay for defects
  (the warranty). A readiness delay is the client's facility; an integrator made
  to carry it adds a contingency because it cannot control it.
- **Risk charge.** Each party pays a charge on the expected contingent losses it
  carries (covenant pressure, insurance). A loss belongs with the party whose
  charge is lower.
- **Capital.** A hardware deposit at signing saves the integrator financing and
  costs the client financing plus exposure to the integrator's insolvency.

So a clause can create value, only move money (then its price is its cost to the
other side), or destroy value. Price never changes the joint value; it only
divides it.

Two seats play the same world (:class:`Game`):

- **client seat**: the model is the client; the scripted integrator's pre-staging
  cost and risk charge are private (:data:`INTEGRATOR_PRIOR`). The integrator
  opens with its own proposal and signs any package at its cost plus a floor
  margin plus an ask premium that falls each round.
- **integrator seat**: the model is the integrator and writes the proposal; the
  scripted client's risk charge is private (:data:`CLIENT_PRIOR`). The client
  signs any package whose price plus its expected cost of the risks it carries
  is at most its turnkey option less a demanded saving that falls each round.

In both, a proposal the counterpart will not sign is answered with the price at
which it would sign that same package this round, and after each refusal it may
break off. Because every cost is an exact expectation over declared events, the
best play on the model's own information is a small dynamic programme over the
counterpart types still consistent with the prices seen (:class:`Solver`). A
decision is graded by what the model could have known at the time, and no
random draw enters the score.

Stated simplifications: expectations stand in for realised outcomes (grading is
ex ante); the four risk events are independent; one delay cost per week; the
integrator's pre-staging is its best response to the contract, and the scripted
client knows it; liquidated damages are uncapped; counterparts price honestly
by a declared rule.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from dataclasses import asdict, dataclass, replace
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

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


PACKAGES: tuple[Package, ...] = tuple(Package(*levels) for levels in itertools.product(*TERMS.values()))
OPENING = Package("none", "client", "excluded", "at_signing")  # the integrator's own proposal: every risk on the client
EVERY_PROTECTION = Package("fix_and_delay", "integrator", "included", "on_delivery")


# ---------------------------------------------------------------------------
# The world. Public to both seats except the two private types.


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
    risk_charge: float  # extra cost per $ of expected contingent loss carried; private in the integrator seat
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
    floor_margin: float  # $k over its own cost; also what walking away earns the integrator
    ask_premium: tuple[float, ...]  # the counterpart's premium: the opening, then each round
    breakoff: float  # probability the counterpart breaks off after a refused proposal
    round_cost: float  # $k the proposer loses for each refused proposal (a week of team time)


@dataclass(frozen=True)
class IntegratorType:
    """Private to the integrator. The client knows only the declared prior."""

    test_cost: float  # $k to pre-stage and burn in the cluster before shipping
    risk_charge: float


INTEGRATOR_PRIOR: tuple[tuple[IntegratorType, float], ...] = tuple(
    (IntegratorType(t, c), 1.0 / 6.0) for t in (40.0, 120.0, 200.0) for c in (0.3, 1.2)
)
CLIENT_PRIOR: tuple[tuple[float, float], ...] = tuple((c, 1.0 / 3.0) for c in (0.15, 0.75, 1.55))


@dataclass(frozen=True)
class World:
    risks: Risks
    client: Client
    terms: Terms
    prior: tuple[tuple[IntegratorType, float], ...] = INTEGRATOR_PRIOR
    client_prior: tuple[tuple[float, float], ...] = CLIENT_PRIOR

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


def client_cost(pkg: Package, w: World, it: IntegratorType, charge: float | None = None) -> float:
    """The client's expected cost of a package apart from its price, at its risk charge
    (the world's unless given). It depends on the integrator's type only through
    whether the integrator pre-stages."""
    r, c, t = w.risks, w.client, w.terms
    charge = c.risk_charge if charge is None else charge
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
    cost = (1.0 + charge) * contingent
    if pkg.deposit == "at_signing":
        cost += c.capital_rate * _deposit(w) * t.deposit_weeks / 52.0 + (1.0 + charge) * c.insolvency * _deposit(w)
    return cost


def joint_cost(pkg: Package, w: World, it: IntegratorType, charge: float | None = None) -> float:
    return integrator_cost(pkg, w, it) + client_cost(pkg, w, it, charge)


def efficient_package(w: World, it: IntegratorType, charge: float | None = None) -> Package:
    return min(PACKAGES, key=lambda p: (round(joint_cost(p, w, it, charge), 6), p != OPENING, p))


def floor_price(pkg: Package, w: World, it: IntegratorType) -> float:
    return integrator_cost(pkg, w, it) + w.terms.floor_margin


def ask_price(pkg: Package, w: World, it: IntegratorType, round_: int) -> float:
    """The price at which the scripted integrator signs this package in this round (0 = its opening)."""
    return floor_price(pkg, w, it) + w.terms.ask_premium[round_]


def opening_price(w: World, it: IntegratorType) -> float:
    return ask_price(OPENING, w, it, 0)


def client_bid(pkg: Package, w: World, it: IntegratorType, charge: float, round_: int) -> float:
    """The highest price at which the scripted client signs this package in this round."""
    return w.client.turnkey_all_in - client_cost(pkg, w, it, charge) - w.terms.ask_premium[round_]


# ---------------------------------------------------------------------------
# The two seats. A Game states, for the seat the model plays, who the
# counterpart may be, when it signs, and what a signed contract costs the model
# (the integrator's cost is its negated profit, so both seats minimise).

PRICE_IT = "price_it"  # propose a package without committing to a price: ask the counterpart for its price
SEATS = ("client", "integrator")


class Game:
    def __init__(self, w: World, seat: str, own: IntegratorType | None = None) -> None:
        if seat not in SEATS:
            raise ValueError(f"unknown seat {seat!r}")
        if seat == "integrator" and own is None:
            raise ValueError("the integrator seat needs the integrator's own type")
        self.w, self.seat, self.own = w, seat, own

    @property
    def prior(self) -> tuple[tuple[Any, float], ...]:
        return self.w.prior if self.seat == "client" else self.w.client_prior

    def threshold(self, pkg: Package, other: Any, round_: int) -> float:
        if self.seat == "client":
            return ask_price(pkg, self.w, other, round_)
        return client_bid(pkg, self.w, self.own, other, round_)

    def signs(self, price: float, threshold: float) -> bool:
        return price >= threshold - 1e-6 if self.seat == "client" else price <= threshold + 1e-6

    def signed_cost(self, pkg: Package, price: float, other: Any) -> float:
        if self.seat == "client":
            return price + client_cost(pkg, self.w, other)
        return integrator_cost(pkg, self.w, self.own) - price

    @property
    def outside(self) -> float:
        return self.w.client.turnkey_all_in if self.seat == "client" else -self.w.terms.floor_margin

    def opening(self, other: Any) -> tuple[Package, float] | None:
        return (OPENING, opening_price(self.w, other)) if self.seat == "client" else None

    def shift(self, counter: float, from_round: int, to_round: int) -> float:
        """The counterpart's threshold for the same package in another round."""
        prem = self.w.terms.ask_premium
        return counter - prem[from_round] + prem[to_round] if self.seat == "client" else counter + prem[from_round] - prem[to_round]

    def joint(self, pkg: Package, other: Any) -> float:
        if self.seat == "client":
            return joint_cost(pkg, self.w, other)
        return joint_cost(pkg, self.w, self.own, other)


def _key(x: float) -> float:
    return round(x, 6)


# ---------------------------------------------------------------------------
# The reference: the model's best play on its own information.
#
# State at the model's move in round t (1..rounds): the set of counterpart types
# still consistent with every price seen, and the standing offer (a package and
# the price at which the counterpart has said it would sign it), if any. The
# model may accept the standing offer, walk to its outside option, or propose a
# package at a price. A proposal the counterpart signs ends the negotiation;
# otherwise it breaks off with probability beta or answers with its price for
# that package this round, which becomes the standing offer and narrows the
# types. After the last round's answer the model can only accept it or walk.
#
# Only the thresholds of consistent types are worth proposing at (between two,
# the same types sign at a worse price), plus PRICE_IT, which no type signs.


@dataclass(frozen=True)
class Action:
    kind: str  # accept | walk | propose
    package: Package | None = None
    price: float | str | None = None  # a number, or PRICE_IT

    def label(self) -> str:
        if self.kind != "propose":
            return self.kind
        price = "ask for its price" if self.price == PRICE_IT else f"at {self.price:,.1f}"
        return f"propose {self.package.label()} {price}"


class Solver:
    """Exact expected cost to the model of the best play, memoised on (round, types)."""

    def __init__(self, game: Game) -> None:
        self.game, self.w = game, game.w
        self.types = tuple(t for t, _ in game.prior)
        self.weight = {t: p for t, p in game.prior}
        self._best: dict[tuple[int, frozenset], tuple[float, Action]] = {}

    def _mean(self, types: frozenset, f: Callable[[Any], float]) -> float:
        z = math.fsum(self.weight[t] for t in types)
        return math.fsum(self.weight[t] * f(t) for t in types) / z

    def accept_value(self, types: frozenset, standing: tuple[Package, float]) -> float:
        pkg, price = standing
        return self._mean(types, lambda t: self.game.signed_cost(pkg, price, t))

    def _prices(self, types: frozenset, pkg: Package, round_: int) -> list[float | str]:
        return [PRICE_IT, *sorted({_key(self.game.threshold(pkg, t, round_)) for t in types})]

    def proposal_value(self, round_: int, types: frozenset, pkg: Package, price: float | str) -> float:
        g, w = self.game, self.w
        # math.fsum, not sum(): Python 3.12 changed float sum() to compensated summation,
        # and a derived number must not depend on the interpreter (DC-T-05, DC-T-09).
        z = math.fsum(self.weight[t] for t in types)
        terms: list[float] = []
        refused: dict[float, list[Any]] = {}
        for t in types:
            thr = _key(g.threshold(pkg, t, round_))
            if price != PRICE_IT and g.signs(price, thr):
                terms.append(self.weight[t] * g.signed_cost(pkg, price, t))
            else:
                refused.setdefault(thr, []).append(t)
        for thr, group in refused.items():
            grp = frozenset(group)
            mass = math.fsum(self.weight[t] for t in grp)
            if round_ < w.rounds:
                after = self.value(round_ + 1, grp, (pkg, thr))
            else:
                after = min(g.outside, self.accept_value(grp, (pkg, thr)))
            terms.append(mass * (w.terms.round_cost + w.terms.breakoff * g.outside + (1.0 - w.terms.breakoff) * after))
        return math.fsum(terms) / z

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

    def q_values(self, round_: int, types: frozenset, standing: tuple[Package, float] | None, final: bool = False) -> dict[Action, float]:
        """Expected cost of each action available here, each followed by the best play."""
        q = {Action("walk"): self.game.outside}
        if standing is not None:
            q[Action("accept")] = self.accept_value(types, standing)
        if not final:
            for pkg in PACKAGES:
                for price in self._prices(types, pkg, round_):
                    q[Action("propose", pkg, price)] = self.proposal_value(round_, types, pkg, price)
        return q

    def value(self, round_: int, types: frozenset, standing: tuple[Package, float] | None) -> float:
        options = [self.game.outside, self.best_proposal(round_, types)[0]]
        if standing is not None:
            options.append(self.accept_value(types, standing))
        return min(options)

    def initial_types(self, opening: float | None) -> frozenset:
        if self.game.seat == "client":
            return frozenset(t for t in self.types if abs(opening_price(self.w, t) - opening) < 1e-6)
        return frozenset(self.types)


def _best_of(q: Mapping[Action, float]) -> Action:
    return min(q, key=lambda a: (_key(q[a]), a.kind != "accept", a.kind != "walk"))


# ---------------------------------------------------------------------------
# What the model sees at a decision, and playing a policy in expectation.


@dataclass(frozen=True)
class Seen:
    round: int
    opening_price: float | None  # the integrator's opening, in the client seat
    standing: tuple[Package, float] | None
    history: tuple[dict[str, Any], ...]  # each refused proposal: round, package, price, counter
    final: bool  # the standing offer is the last round's answer: accept or walk


Policy = Callable[[Seen], Action]


def start(game: Game, other: Any) -> Seen:
    opening = game.opening(other)
    return Seen(1, opening[1] if opening else None, opening, (), False)


def advance(game: Game, seen: Seen, action: Action, other: Any) -> tuple[str, Seen | None, float | None]:
    """The counterpart's answer to a proposal, before any break-off: ('signed', None, cost)
    or ('refused', next Seen, None)."""
    thr = game.threshold(action.package, other, seen.round)
    if action.price != PRICE_IT and game.signs(action.price, thr):
        return "signed", None, game.signed_cost(action.package, action.price, other)
    step = {"round": seen.round, "package": action.package, "price": action.price, "counter": thr}
    last = seen.round == game.w.rounds
    return "refused", Seen(seen.round if last else seen.round + 1, seen.opening_price, (action.package, thr), seen.history + (step,), last), None


def expected_cost(game: Game, other: Any, policy: Policy) -> float:
    w = game.w

    def go(seen: Seen) -> float:
        act = policy(seen)
        if act.kind == "walk":
            return game.outside
        if act.kind == "accept":
            if seen.standing is None:
                raise ValueError("nothing to accept")
            return game.signed_cost(seen.standing[0], seen.standing[1], other)
        if seen.final:
            raise ValueError("after the last round's answer the model can only accept or walk")
        result, nxt, cost = advance(game, seen, act, other)
        if result == "signed":
            return cost
        return w.terms.round_cost + w.terms.breakoff * game.outside + (1.0 - w.terms.breakoff) * go(nxt)

    return go(start(game, other))


def consistent_types(s: Solver, seen: Seen) -> frozenset:
    types = s.initial_types(seen.opening_price)
    for h in seen.history:
        types = frozenset(t for t in types if abs(s.game.threshold(h["package"], t, h["round"]) - h["counter"]) < 1e-6)
    return types


def reference_policy(game: Game) -> Policy:
    s = Solver(game)

    def act(seen: Seen) -> Action:
        return _best_of(s.q_values(seen.round, consistent_types(s, seen), seen.standing, seen.final))

    return act


def decision_regret(game: Game, seen: Seen, action: Action, solver: Solver | None = None) -> float:
    """What this action gives up against the best one, in expected cost to the model, on its own information."""
    s = solver or Solver(game)
    types = consistent_types(s, seen)
    q = s.q_values(seen.round, types, seen.standing, seen.final)
    if action not in q:
        if action.kind != "propose" or seen.final:
            raise ValueError(f"{action.label()} is not available here")
        q[action] = s.proposal_value(seen.round, types, action.package, action.price)
    return q[action] - min(q.values())


def prior_expected(game: Game, policy: Policy) -> float:
    """A policy's expected cost to the model over the declared prior on the counterpart."""
    return math.fsum(p * expected_cost(game, t, policy) for t, p in game.prior)


def solve(game: Game, other: Any) -> dict[str, Any]:
    """The reference at the start: its expected cost and first action, given what the model sees."""
    s = Solver(game)
    seen = start(game, other)
    types = s.initial_types(seen.opening_price)
    q = s.q_values(1, types, seen.standing)
    best = _best_of(q)
    return {"expected_cost": q[best], "first_action": best, "q": q, "types": types, "seen": seen}


# ---------------------------------------------------------------------------
# Rules that do not negotiate the risk allocation. Each is right somewhere.
#
# They are competent at price: after one answer they propose exactly the price
# the answer implies for the next round, so a rule loses only for the
# allocation it chose or the pace it kept, never for arithmetic.


def prior_best_package(game: Game) -> Package:
    """The package with the lowest expected joint cost under the prior: the best a party can do without asking."""
    return min(PACKAGES, key=lambda p: (_key(math.fsum(q * game.joint(p, t) for t, q in game.prior)), p))


def _price_then_sign(game: Game, pkg: Package) -> Policy:
    def act(seen: Seen) -> Action:
        if seen.final:
            return Action("accept")
        if not seen.history:
            return Action("propose", pkg, PRICE_IT)
        h = seen.history[-1]
        return Action("propose", pkg, game.shift(h["counter"], h["round"], seen.round))

    return act


def _sign_now(game: Game) -> Policy:
    """Propose the prior-best package at once, at the price every consistent type signs."""
    s = Solver(game)

    def act(seen: Seen) -> Action:
        if seen.history:
            return Action("accept")
        pkg = prior_best_package(game)
        thresholds = [_key(game.threshold(pkg, t, seen.round)) for t in consistent_types(s, seen)]
        return Action("propose", pkg, max(thresholds) if game.seat == "client" else min(thresholds))

    return act


def rules(game: Game) -> dict[str, Policy]:
    take_counter = lambda seen: Action("accept") if seen.history else Action("propose", prior_best_package(game), PRICE_IT)  # noqa: E731
    walk = lambda seen: Action("walk")  # noqa: E731
    if game.seat == "client":
        return {
            "accept_the_opening": lambda seen: Action("accept"),
            "walk_to_turnkey": walk,  # also "defensive terms are a red flag"
            "take_the_first_counter": take_counter,
            "haggle_price_only": _price_then_sign(game, OPENING),
            "demand_every_protection": _price_then_sign(game, EVERY_PROTECTION),
            "sign_the_prior_best_now": _sign_now(game),
        }
    return {
        "decline_to_bid": walk,
        "take_the_first_counter": take_counter,
        "defend_the_opening_terms": _price_then_sign(game, OPENING),
        "concede_every_protection": _price_then_sign(game, EVERY_PROTECTION),
        "sign_the_prior_best_now": _sign_now(game),
    }


def first_move_kind(a: Action) -> str:
    if a.kind in ("accept", "walk"):
        return a.kind
    if a.price == PRICE_IT:
        return "price_opening" if a.package == OPENING else "price_alternative"
    return "sign_at_a_price"


# ---------------------------------------------------------------------------
# The pack: cells, each rewarding a different way of negotiating the allocation.
#
# Cells are defined on the client seat. A world's public facts are drawn from
# its cell's ranges and the integrator's type from the declared prior; the
# client's risk charge is one of CLIENT_PRIOR's values, so the same world can be
# played from the integrator seat with the client's charge private. A world is
# admitted only if the client seat's intended first move beats every other kind
# of first move by MARGIN in expectation, and every rule named as a loser gives
# up at least LOSER_MARGIN. Where the right contract depends on the hidden type,
# a twin with the same public facts and a type whose efficient contract differs
# is added: before any price is seen a good negotiator opens the same way in both.
# The integrator seat is reported on every world, not admitted on.

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
    delay_per_week=(90.0, 130.0), capital_rate=(0.05, 0.07), insolvency=(0.0, 0.015),
    breakoff=(0.05, 0.12), turnkey_offset=(300.0, 900.0),
)

CELLS: dict[str, dict[str, Any]] = {
    "keep_their_terms": {
        "lesson": "the integrator's defensive proposal is already the efficient contract; negotiate the price, not the terms",
        "client_charge": 0.15,
        "ranges": dict(defect_without_test=(0.08, 0.12), defect_with_test=(0.06, 0.08), insolvency=(0.0, 0.008)),
        "first": {"price_it"},
        "losers": ("accept_the_opening", "walk_to_turnkey", "demand_every_protection", "sign_the_prior_best_now"),
    },
    "price_the_alternatives": {
        "lesson": "which risks to move depends on what the integrator charges to carry them; ask it to price the alternative first",
        "client_charge": 0.75,
        "ranges": dict(breakoff=(0.03, 0.08)),
        "first": {"price_alternative"},
        "losers": ("haggle_price_only", "take_the_first_counter", "sign_the_prior_best_now"),
        "twins": True,
    },
    "shift_the_tail": {
        "lesson": "the client cannot carry the incident tail as cheaply as any integrator can; move it and the delay risk across",
        "client_charge": 1.55,
        "ranges": {},
        "first": {"price_alternative"},
        "losers": ("accept_the_opening", "haggle_price_only", "take_the_first_counter"),
    },
    "better_contract_or_walk": {
        "lesson": "on the integrator's terms the deal loses to turnkey; only a better allocation beats walking away",
        "client_charge": 0.75,
        "ranges": dict(breakoff=(0.03, 0.08), turnkey_offset=(-170.0, -60.0)),
        "first": {"price_alternative"},
        "losers": ("walk_to_turnkey", "haggle_price_only", "accept_the_opening"),
        "twins": True,
    },
    "walk_away": {
        "lesson": "no allocation of these risks beats the turnkey offer; walk before spending a round",
        "client_charge": 0.75,
        "ranges": dict(turnkey_offset=(-700.0, -450.0)),
        "first": {"walk"},
        "losers": ("haggle_price_only", "demand_every_protection", "take_the_first_counter"),
    },
    "close_now": {
        "lesson": "the integrator is likely to walk after a refusal and the deal is worth far more than turnkey; sign now",
        "client_charge": 1.55,
        "ranges": dict(breakoff=(0.35, 0.5), turnkey_offset=(1000.0, 1400.0)),
        "first": {"sign_at_a_price"},
        "losers": ("haggle_price_only", "take_the_first_counter", "demand_every_protection"),
    },
}


def _kinds(first: Mapping[Action, float]) -> dict[str, float]:
    best: dict[str, float] = {}
    for a, v in first.items():
        k = first_move_kind(a)
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
        delay_per_week=_round(u["delay_per_week"], 5), risk_charge=CELLS[cell]["client_charge"],
        capital_rate=_round(u["capital_rate"], 0.005), insolvency=_round(u["insolvency"], 0.001), turnkey_all_in=0.0,
    )
    w = World(risks, client, terms)
    some = w.prior[0][0]  # the opening package's floor and client cost do not depend on the integrator's type
    price_only = floor_price(OPENING, w, some) + client_cost(OPENING, w, some)
    return replace(w, client=replace(client, turnkey_all_in=_round(price_only + u["turnkey_offset"], 10)))


def seat_view(w: World, seat: str, integrator: IntegratorType) -> dict[str, Any]:
    """The reference's first move and each rule's regret for one seat of a world."""
    game = Game(w, "client") if seat == "client" else Game(w, "integrator", integrator)
    other = integrator if seat == "client" else w.client.risk_charge
    ref = solve(game, other)
    ref_cost = prior_expected(game, reference_policy(game))
    return {
        "reference": ref,
        "reference_prior_cost": ref_cost,
        "first_move_values": _kinds(ref["q"]) if seat == "client" else {first_move_kind(a): v for a, v in sorted(ref["q"].items(), key=lambda kv: -kv[1])},
        "rule_regret": {name: prior_expected(game, rule) - ref_cost for name, rule in rules(game).items()},
    }


def admit(w: World, truth: IntegratorType, cell: str) -> dict[str, Any] | None:
    spec = CELLS[cell]
    view = seat_view(w, "client", truth)
    kinds = view["first_move_values"]
    intended = min(kinds[k] for k in spec["first"])
    others = [v for k, v in kinds.items() if k not in spec["first"] and not (k == "price_it" or (k.startswith("price_") and "price_it" in spec["first"]))]
    if min(others) - intended < MARGIN:
        return None
    if any(view["rule_regret"][name] < LOSER_MARGIN for name in spec["losers"]):
        return None
    return view


def build_world(seed: int, cell: str, max_draws: int = 4000) -> dict[str, Any] | None:
    rng = random.Random(seed)
    for _ in range(max_draws):
        w = draw_world(rng, cell)
        truth = rng.choices([t for t, _ in w.prior], [p for _, p in w.prior])[0]
        view = admit(w, truth, cell)
        if view is not None:
            return _summarise(w, truth, cell, seed, view)
    return None


def with_truth(row: Mapping[str, Any], w: World, truth: IntegratorType) -> dict[str, Any]:
    view = admit(w, truth, row["cell"])
    assert view is not None, "admission depends only on public facts and the prior"
    twin = _summarise(w, truth, row["cell"], row["seed"], view)
    twin["twin_of"] = row["slug"]
    twin["slug"] = row["slug"] + "_twin"
    return twin


def _view_summary(view: Mapping[str, Any], ref_cost: float) -> dict[str, Any]:
    ref = view["reference"]
    return {
        "reference_first_move": {"kind": first_move_kind(ref["first_action"]), "action": ref["first_action"].label()},
        "reference_expected_cost": ref["expected_cost"],
        "rule_regret_prior": {k: round(v, 3) for k, v in view["rule_regret"].items()},
    }


def _summarise(w: World, truth: IntegratorType, cell: str, seed: int, client_view: Mapping[str, Any]) -> dict[str, Any]:
    ref = client_view["reference"]
    eff = efficient_package(w, truth)
    integrator_view = seat_view(w, "integrator", truth)
    return {
        "slug": f"{cell}_{seed}",
        "cell": cell,
        "seed": seed,
        "lesson": CELLS[cell]["lesson"],
        "world": world_to_dict(w),
        "hidden_type": asdict(truth),
        "opening_price": ref["seen"].opening_price,
        "reference_first_move": {"kind": first_move_kind(ref["first_action"]), "action": ref["first_action"].label()},
        "reference_expected_cost": ref["expected_cost"],
        "first_move_values": {k: round(v - ref["expected_cost"], 3) for k, v in sorted(client_view["first_move_values"].items())},
        "rule_regret_prior": {k: round(v, 3) for k, v in client_view["rule_regret"].items()},
        "efficient_package": eff.label(),
        "joint_saving_vs_opening": round(joint_cost(OPENING, w, truth) - joint_cost(eff, w, truth), 3),
        "integrator_seat": _view_summary(integrator_view, integrator_view["reference_prior_cost"]),
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
    return {
        "risks": asdict(w.risks), "client": asdict(w.client), "terms": asdict(w.terms),
        "prior": [[asdict(t), p] for t, p in w.prior], "client_prior": [[c, p] for c, p in w.client_prior],
    }


def world_from_dict(d: Mapping[str, Any]) -> World:
    terms = dict(d["terms"])
    terms["ask_premium"] = tuple(terms["ask_premium"])
    return World(
        Risks(**d["risks"]), Client(**d["client"]), Terms(**terms),
        tuple((IntegratorType(**t), p) for t, p in d["prior"]), tuple((float(c), p) for c, p in d["client_prior"]),
    )


# ---------------------------------------------------------------------------
# What each seat is told. Every number the reference uses is here.


def _k(x: float) -> str:
    return f"${x:,.0f}k" if abs(x - round(x)) < 0.05 else f"${x:,.1f}k"


def _pct(x: float) -> str:
    return f"{100 * x:g}%"


def _risk_lines(w: World, who: str) -> list[str]:
    r = w.risks
    you, them = ("you", "the integrator") if who == "client" else ("the client", "you")
    stager = "The integrator will pre-stage exactly when the contract makes that cheaper for it than not" if who == "client" else "You will pre-stage exactly when the contract makes that cheaper for you than not"
    return [
        "Risks (both parties know these):",
        f"- Compatibility defect: {_pct(r.defect_without_test)} likely, or {_pct(r.defect_with_test)} if {them} pre-stage{'s' if who == 'client' else ''} and burn{'s' if who == 'client' else ''} in the cluster first. "
        f"Fixing it costs {_k(r.defect_fix)} and delays go-live {r.defect_weeks:g} weeks. {stager}; it is not a separate term.",
        f"- {'Your' if who == 'client' else 'The client'}'s facility not ready: {_pct(r.unready)} likely; {r.unready_weeks:g} weeks' delay and {_k(r.standby)} of integrator standby.",
        f"- Post-handover incident in the first year: {_pct(r.incident)} likely; {you} would lose {_k(r.incident_loss)}.",
        f"- Each week of delay costs {you} {_k(w.client.delay_per_week)} of revenue.",
    ]


def _term_lines(w: World, who: str) -> list[str]:
    t = w.terms
    c, i = ("you", "it") if who == "client" else ("the client", "you")
    return [
        "Contract terms to settle, besides price:",
        f"- warranty: none ({c} pay{'s' if c != 'you' else ''} a defect) | fix ({i} pay{'s' if i != 'you' else ''} the fix) | fix_and_delay ({i} pay{'s' if i != 'you' else ''} the fix and {_k(t.delay_damages_per_week)} per week of defect delay)",
        f"- readiness: client ({c} pay{'s' if c != 'you' else ''} standby if the facility is late) | integrator ({i} do{'es' if i != 'you' else ''})",
        f"- consequential: excluded ({c} carr{'ies' if c != 'you' else 'y'} an incident's losses) | included ({i} do{'es' if i != 'you' else ''})",
        f"- deposit: at_signing ({_pct(t.deposit_share)} of hardware, {_k(t.deposit_share * t.hardware)}, paid {t.deposit_weeks:g} weeks before delivery) | on_delivery",
    ]


def _protocol_lines(w: World, who: str) -> list[str]:
    t = w.terms
    other = "it" if who == "client" else "the client"
    return [
        f"You have {w.rounds} rounds. In each you may accept the standing offer (if there is one), walk away, or propose a package and a price. "
        f"A proposal {other} will not sign is answered with {'its' if who == 'client' else 'the client'}'s price for that same package in that round, "
        "which becomes the standing offer. To ask for that price without committing, propose the package with price null. "
        "After the last round's answer you may only accept it or walk.",
        f"After each proposal {other} refuses, {other} breaks off {_pct(t.breakoff)} of the time. Each refused proposal also costs you {_k(t.round_cost)}.",
    ]


def brief_text(game: Game, opening: float | None = None) -> str:
    w = game.w
    r, c, t = w.risks, w.client, w.terms
    if game.seat == "client":
        tests = sorted({it.test_cost for it, _ in w.prior})
        charges = sorted({it.risk_charge for it, _ in w.prior})
        return "\n".join([
            "You are the client. An integrator will deliver a GPU cluster into your facility. Money is in $ thousands.",
            f"Hardware {_k(t.hardware)} at cost; the integrator's own delivery cost {_k(t.services)}.",
            "",
            *_risk_lines(w, "client"),
            "",
            *_term_lines(w, "client"),
            "",
            "Your position:",
            f"- Each $1 of expected loss you carry costs you ${1 + c.risk_charge:.2f} (covenants and insurance).",
            f"- Your capital costs {_pct(c.capital_rate)} a year. If you pay the deposit, there is a {_pct(c.insolvency)} chance the integrator fails before delivery and it is lost.",
            f"- Outside option: a turnkey contract at {_k(c.turnkey_all_in)} all in, every risk priced in.",
            "",
            "The integrator:",
            f"- Each $1 of expected loss it carries costs it $1 plus its own risk charge, which is {' or '.join(f'{x:g}' for x in charges)} (equally likely; not disclosed).",
            f"- Pre-staging costs it {' or '.join(_k(x) for x in tests)} (equally likely; not disclosed).",
            f"- It adds {_pct(t.uncontrolled_contingency)} of expected standby if it carries your facility's readiness, which it cannot control.",
            f"- Its capital costs {_pct(t.integrator_capital_rate)} a year, so a deposit at signing saves it financing.",
            f"- It signs any package at its expected cost of that package plus {_k(t.floor_margin)}, plus an ask premium: "
            + ", ".join(f"{_k(x)} in round {i}" for i, x in enumerate(t.ask_premium) if i) + f" (its opening carried {_k(t.ask_premium[0])}).",
            "",
            f"Its opening proposal: warranty none, readiness client, consequential excluded, deposit at_signing, at {_k(opening)}.",
            *_protocol_lines(w, "client"),
            "Your objective: the lowest expected total cost to you: the price, plus every expected loss you carry at your risk charge, "
            "plus deposit financing and loss, plus the cost of refused rounds; walking away costs you the turnkey price.",
        ])
    it = game.own
    charges = sorted({x for x, _ in w.client_prior})
    return "\n".join([
        "You are the integrator. You will deliver a GPU cluster into the client's facility. Money is in $ thousands.",
        f"Hardware {_k(t.hardware)} at cost; your own delivery cost {_k(t.services)}.",
        "",
        *_risk_lines(w, "integrator"),
        "",
        *_term_lines(w, "integrator"),
        "",
        "Your position:",
        f"- Pre-staging costs you {_k(it.test_cost)}.",
        f"- Each $1 of expected loss you carry costs you ${1 + it.risk_charge:.2f} (insurance and balance sheet).",
        f"- If you carry the client's facility readiness, which you cannot control, you add {_pct(t.uncontrolled_contingency)} of expected standby.",
        f"- Your capital costs {_pct(t.integrator_capital_rate)} a year, so a deposit at signing saves you financing.",
        f"- Outside option: other work that earns you {_k(t.floor_margin)}.",
        "",
        "The client:",
        f"- Each $1 of expected loss it carries costs it $1 plus its own risk charge, which is {' or '.join(f'{x:g}' for x in charges)} (equally likely; not disclosed).",
        f"- Its capital costs {_pct(c.capital_rate)} a year. If it pays the deposit, it puts a {_pct(c.insolvency)} chance on losing it to your insolvency.",
        f"- It has a turnkey offer at {_k(c.turnkey_all_in)} all in, every risk priced in.",
        "- It knows whether you would pre-stage under each package.",
        "- It signs any package whose price, plus every expected loss it carries at its risk charge, plus deposit financing and loss, "
        f"is at most its turnkey price less a saving it demands: "
        + ", ".join(f"{_k(x)} in round {i}" for i, x in enumerate(t.ask_premium) if i) + ".",
        "",
        "The client has asked for your proposal; there is no standing offer yet.",
        *_protocol_lines(w, "integrator"),
        "Your objective: the highest expected profit: the price, less your expected cost of the package (hardware, delivery, pre-staging if you do it, "
        "every expected loss you carry at your risk charge, the standby contingency, less deposit financing saved), less the cost of refused rounds; "
        "walking away earns your outside option.",
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
        seat = row["integrator_seat"]
        print(f"{row['slug']:37} client:{row['reference_first_move']['kind']:18} integrator:{seat['reference_first_move']['kind']:18} "
              + " ".join(f"{k[:9]}={v:.0f}" for k, v in seat["rule_regret_prior"].items()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
