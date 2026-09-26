"""The playbook menu with every contract term the case can model exactly.

The menu case (:mod:`.risk_allocation_menu`) negotiates four clauses, each on or off.
This module adds the terms an integration contract negotiates besides those, with
their levels, and what each does to who pays when things go wrong. Every cost is an
expectation over the same four independent events (a compatibility defect, the
facility late, a post-handover incident, the integrator failing while it holds an
unprotected deposit), enumerated outcome by outcome, so a cap on the total is exact:

- **warranty**: none, fix, or fix and delay damages;
- **damages**: the delay-damages rate under fix and delay, $50k, $100k or $200k a week;
- **liability cap**: uncapped, $1,500k or $500k on everything the integrator pays in one
  delivery (fix, damages, standby, incident); past it the client bears the rest;
- **readiness**: who pays standby if the facility is late. An integrator that carries it
  prepares the client's site whenever that is cheaper for it, which cuts the chance of a
  late facility to :data:`SITE_PREP_EFFECT` of what it would be;
- **consequential**: who carries a post-handover incident's loss;
- **deposit**: none, 25% or 50% of the hardware paid at signing;
- **escrow**: the deposit held in escrow until delivery: safe if the integrator fails, for
  a fee, and no financing benefit to the integrator;
- **burn-in**: a week's acceptance burn-in before handover, which halves the chance of an
  incident, costs the client a week of revenue and the integrator a crew.

The integrator best-responds to a contract: it pre-stages and prepares the site exactly
when that lowers its own expected cost, cap included. Uncapped, with a 50% deposit or
none and no escrow or burn-in, every cost equals the one-sided economics
(:mod:`.risk_allocation`); the tests check it.

Three playbooks post a base contract and make some terms negotiable
(:data:`NEGOTIABLE`); every combination is on the menu, from 64 to 360 contracts. The
list prices the base and each single change. The client may accept a standing offer,
counter any contract on the menu with a price, ask its price, or walk. How the
integrator picks its playbook and prices a contract is a policy declared here and
stated in no brief. The reference (:class:`ContractSolver`) is exact: it knows the
policy and the prior over the integrator's type, not the type.
"""

from __future__ import annotations

import itertools
import json
import math
import random
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from typing import Any

import numpy as np

from . import risk_allocation as ra
from .risk_allocation_menu import playbook_of, self_manage_cost

# ---------------------------------------------------------------------------
# Contracts.

LEVELS: dict[str, tuple[Any, ...]] = {
    "warranty": ("none", "fix", "fix_and_delay"),
    "damages": ("50", "100", "200"),  # strings: Gemini's structured output takes string enums only (DC-T-19)
    "liability_cap": ("uncapped", "1500", "500"),
    "readiness": ("client", "integrator"),
    "consequential": ("excluded", "included"),
    "deposit": ("none", "25%", "50%"),
    "escrow": (False, True),
    "burn_in": (False, True),
}
TERMS = tuple(LEVELS)
DEPOSIT_SHARE = {"none": 0.0, "25%": 0.25, "50%": 0.5}
CAP = {"uncapped": math.inf, "1500": 1500.0, "500": 500.0}
SITE_PREP_EFFECT = 0.4  # the late-facility chance after site preparation, as a share of the chance without it
BURN_IN_WEEKS = 1.0
BURN_IN_CREW = 40.0  # $k, the integrator's
BURN_IN_INCIDENT_FACTOR = 0.5
ESCROW_FEE = 10.0  # $k, the client's


@dataclass(frozen=True, order=True)
class Contract:
    warranty: str
    damages: str
    liability_cap: str
    readiness: str
    consequential: str
    deposit: str
    escrow: bool
    burn_in: bool

    def normal(self) -> "Contract":
        """One contract per economic meaning: a damages rate only under fix and delay, escrow only with a deposit."""
        c = self
        if c.warranty != "fix_and_delay" and c.damages != "100":
            c = replace(c, damages="100")
        if c.deposit == "none" and c.escrow:
            c = replace(c, escrow=False)
        return c

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def label(self) -> str:
        w = self.warranty + (f" @{self.damages}/wk" if self.warranty == "fix_and_delay" else "")
        dep = "no deposit" if self.deposit == "none" else f"deposit {self.deposit}{' in escrow' if self.escrow else ''}"
        return (f"{w}, cap {self.liability_cap}, readiness {self.readiness}, consequential {self.consequential}, {dep}"
                f"{', burn-in' if self.burn_in else ''}")


def contract_from(terms: Mapping[str, Any], base: Contract) -> Contract:
    """A contract from the base and a mapping of terms; a term missing or null keeps the base's level."""
    changes = {}
    for k, v in terms.items():
        if k not in LEVELS:
            raise ValueError(f"unknown term {k!r}")
        if v is None:
            continue
        if isinstance(v, bool) != isinstance(LEVELS[k][0], bool) or v not in LEVELS[k]:
            raise ValueError(f"{k} must be one of {list(LEVELS[k])}")
        changes[k] = v
    return replace(base, **changes).normal()


# ---------------------------------------------------------------------------
# The economics, outcome by outcome.


@dataclass(frozen=True)
class Extras:
    team: float  # the client's own team cost if it self-manages, $k
    site_prep: float  # what preparing the client's site costs the integrator, $k (public)


def _probabilities(c: Contract, w: ra.World, pre: bool, prep: bool) -> tuple[float, float, float, float]:
    r = w.risks
    return (
        r.defect_with_test if pre else r.defect_without_test,
        r.unready * (SITE_PREP_EFFECT if prep else 1.0),
        r.incident * (BURN_IN_INCIDENT_FACTOR if c.burn_in else 1.0),
        w.client.insolvency if (c.deposit != "none" and not c.escrow) else 0.0,
    )


def outcomes(c: Contract, w: ra.World, pre: bool, prep: bool) -> list[tuple[float, float, float, tuple[bool, bool, bool, bool]]]:
    """(probability, the client's loss, what the integrator pays, (defect, late, incident, failure)) for each outcome.
    The client's loss is every real loss less what the integrator pays it, so damages above the loss are a gain."""
    r, cl, t = w.risks, w.client, w.terms
    pd, pu, pi, pn = _probabilities(c, w, pre, prep)
    fix, defect_delay, damages = r.defect_fix, r.defect_weeks * cl.delay_per_week, int(c.damages) * r.defect_weeks
    late_delay, loss = r.unready_weeks * cl.delay_per_week, r.incident_loss
    deposit = DEPOSIT_SHARE[c.deposit] * t.hardware
    cap = CAP[c.liability_cap]
    out = []
    for d, u, i, n in itertools.product((False, True), repeat=4):
        p = (pd if d else 1 - pd) * (pu if u else 1 - pu) * (pi if i else 1 - pi) * (pn if n else 1 - pn)
        if p == 0.0:
            continue
        real = (fix + defect_delay if d else 0.0) + (r.standby + late_delay if u else 0.0) + (loss if i else 0.0) + (deposit if n else 0.0)
        owed = 0.0
        if d:
            owed += (fix if c.warranty != "none" else 0.0) + (damages if c.warranty == "fix_and_delay" else 0.0)
        if u and c.readiness == "integrator":
            owed += r.standby
        if i and c.consequential == "included":
            owed += loss
        paid = min(owed, cap)
        out.append((p, real - paid, paid, (d, u, i, n)))
    return out


def _integrator_expected(c: Contract, w: ra.World, it: ra.IntegratorType, x: Extras, pre: bool, prep: bool) -> float:
    r, t = w.risks, w.terms
    paid = math.fsum(p * pay for p, _, pay, _ in outcomes(c, w, pre, prep))
    cost = t.hardware + t.services + (it.test_cost if pre else 0.0) + (x.site_prep if prep else 0.0) + (BURN_IN_CREW if c.burn_in else 0.0)
    cost += (1.0 + it.risk_charge) * paid
    if c.readiness == "integrator":
        cost += t.uncontrolled_contingency * r.unready * (SITE_PREP_EFFECT if prep else 1.0) * r.standby
    if c.deposit != "none" and not c.escrow:
        cost -= t.integrator_capital_rate * DEPOSIT_SHARE[c.deposit] * t.hardware * t.deposit_weeks / 52.0
    return cost


def best_response(c: Contract, w: ra.World, it: ra.IntegratorType, x: Extras) -> tuple[bool, bool, float]:
    """(pre-stages, prepares the site, its expected cost): each done exactly when it lowers the integrator's cost."""
    options = [(pre, prep) for pre in (False, True) for prep in ((False, True) if c.readiness == "integrator" else (False,))]
    return min(((pre, prep, _integrator_expected(c, w, it, x, pre, prep)) for pre, prep in options), key=lambda z: (round(z[2], 9), z[0], z[1]))


def integrator_cost(c: Contract, w: ra.World, it: ra.IntegratorType, x: Extras) -> float:
    return best_response(c, w, it, x)[2]


def floor_price(c: Contract, w: ra.World, it: ra.IntegratorType, x: Extras) -> float:
    return integrator_cost(c, w, it, x) + w.terms.floor_margin


def client_cost(c: Contract, w: ra.World, it: ra.IntegratorType, x: Extras, charge: float | None = None) -> float:
    """The client's expected cost apart from the price: the losses it carries at its risk charge, deposit
    financing, the escrow fee and a burn-in week's revenue."""
    cl, t = w.client, w.terms
    charge = cl.risk_charge if charge is None else charge
    pre, prep, _ = best_response(c, w, it, x)
    cost = (1.0 + charge) * math.fsum(p * lost for p, lost, _, _ in outcomes(c, w, pre, prep))
    if c.deposit != "none":
        cost += cl.capital_rate * DEPOSIT_SHARE[c.deposit] * t.hardware * t.deposit_weeks / 52.0
    if c.escrow:
        cost += ESCROW_FEE
    if c.burn_in:
        cost += BURN_IN_WEEKS * cl.delay_per_week
    return cost


# ---------------------------------------------------------------------------
# Playbooks: a base contract and the terms each makes negotiable.

BASES: dict[str, Contract] = {
    "coordination": Contract("none", "100", "uncapped", "client", "excluded", "50%", False, False),
    "managed": Contract("fix", "100", "1500", "client", "excluded", "50%", False, False),
    "turnkey": Contract("fix_and_delay", "100", "uncapped", "client", "excluded", "none", False, False),
}
NEGOTIABLE: dict[str, dict[str, tuple[Any, ...]]] = {
    "coordination": {"warranty": ("none", "fix"), "liability_cap": ("uncapped", "1500"), "readiness": ("client", "integrator"),
                     "consequential": ("excluded", "included"), "escrow": (False, True), "burn_in": (False, True)},
    "managed": {"warranty": ("fix", "fix_and_delay"), "damages": ("100", "50", "200"), "liability_cap": ("1500", "uncapped", "500"),
                "consequential": ("excluded", "included"), "deposit": ("50%", "25%", "none"), "escrow": (False, True), "burn_in": (False, True)},
    "turnkey": {"damages": ("100", "50", "200"), "liability_cap": ("uncapped", "1500", "500"), "readiness": ("client", "integrator"),
                "consequential": ("excluded", "included"), "deposit": ("none", "25%", "50%"), "escrow": (False, True), "burn_in": (False, True)},
}
PLAYBOOKS = tuple(BASES)


@lru_cache(maxsize=None)
def contracts(playbook: str) -> tuple[Contract, ...]:
    """Every contract on a playbook's menu, one per economic meaning, the base first."""
    base, neg = BASES[playbook], NEGOTIABLE[playbook]
    seen: dict[Contract, None] = {base: None}
    for combo in itertools.product(*neg.values()):
        seen.setdefault(replace(base, **dict(zip(neg, combo))).normal(), None)
    return tuple(seen)


@lru_cache(maxsize=None)
def listed(playbook: str) -> tuple[Contract, ...]:
    """What the list prices: the base, then each change of one term (a damages rate brings fix and delay with it;
    escrow on a playbook without a deposit brings a 50% deposit)."""
    base, neg = BASES[playbook], NEGOTIABLE[playbook]
    out = [base]
    for k, levels in neg.items():
        for v in levels:
            c = replace(base, **{k: v})
            if k == "damages" and c.warranty != "fix_and_delay":
                c = replace(c, warranty="fix_and_delay")
            if k == "escrow" and v and c.deposit == "none":
                c = replace(c, deposit="50%")
            c = c.normal()
            if c not in out:
                out.append(c)
    return tuple(out)


def fee_based(playbook: str) -> bool:
    return playbook != "turnkey"


# ---------------------------------------------------------------------------
# The integrator's pricing policy. Declared here; stated in no brief.

MARKUP_UP = 0.4  # of the cost a change adds to the integrator, over that cost
KEEP_DOWN = 0.5  # of the saving a change gives the integrator, kept rather than passed on
DECAY = (1.0, 0.5, 0.0)  # the markup's share by round: the list, then each answer
PRICE_STEP = 0.1  # it quotes in $100 steps, rounding up, so every price shown is the price it signs at


def _quote(x):
    """Round a price up to the quoting step (arrays or floats)."""
    return np.ceil(np.asarray(x) / PRICE_STEP - 1e-6) * PRICE_STEP


def _markup(floor_c: float, floor_base: float) -> float:
    delta = floor_c - floor_base
    return MARKUP_UP * max(delta, 0.0) + KEEP_DOWN * max(-delta, 0.0)


def threshold(cw: "CWorld", c: Contract, it: ra.IntegratorType, round_: int) -> float:
    """The all-in price at which the integrator signs this contract in this round (0 = its list)."""
    f = floor_price(c, cw.w, it, cw.x)
    return float(_quote(f + cw.w.terms.ask_premium[round_] + DECAY[round_] * _markup(f, floor_price(BASES[cw.playbook], cw.w, it, cw.x))))


# ---------------------------------------------------------------------------
# One world as the client faces it.

OUTSIDE = ("turnkey", "self_manage")


@dataclass(frozen=True)
class CWorld:
    w: ra.World
    x: Extras
    playbook: str

    def outside_cost(self, which: str) -> float:
        return self.w.client.turnkey_all_in if which == "turnkey" else self_manage_cost(self.w, self.x.team)

    @property
    def best_outside(self) -> tuple[str, float]:
        return min(((o, self.outside_cost(o)) for o in OUTSIDE), key=lambda z: (round(z[1], 6), z[0]))

    @property
    def types(self) -> tuple[ra.IntegratorType, ...]:
        return tuple(t for t, _ in self.w.prior if playbook_of(t) == self.playbook)


def world_from(payload: Mapping[str, Any]) -> tuple[CWorld, ra.IntegratorType]:
    w = ra.world_from_dict(payload["world"])
    it = ra.IntegratorType(**payload["integrator_type"])
    return CWorld(w, Extras(float(payload["extras"]["team"]), float(payload["extras"]["site_prep"])), playbook_of(it)), it


# ---------------------------------------------------------------------------
# The informed client's exact best play.


@dataclass(frozen=True)
class CAction:
    kind: str  # accept | propose | walk; a proposal with price None asks for the price
    contract: Contract | None = None
    price: float | None = None  # all in
    outside: str | None = None

    def label(self) -> str:
        if self.kind == "accept":
            return f"accept [{self.contract.label()}]"
        if self.kind == "walk":
            return f"walk to {self.outside}"
        what = "ask the price of" if self.price is None else "counter"
        return f"{what} [{self.contract.label()}]" + ("" if self.price is None else f" at {self.price:,.1f} all in")


@dataclass(frozen=True)
class CState:
    round: int
    final: bool
    types: frozenset  # indices into the playbook's types consistent with every price seen
    standing: frozenset  # of (contract index, all-in price)


class ContractSolver:
    """Exact dynamic programme over the client's information states.

    A state is the round, whether only accept or walk remain, the integrator types
    still consistent with every price seen, and the standing offers. The prices that
    matter are the types' thresholds, so a proposal is searched at each of them and as
    a price request. Once one type remains the value has a closed form
    (:meth:`_single`): every standing price is at least that type's threshold this
    round, so only walking, signing now at the cheapest threshold, or spending a
    refusal to sign next round remain.
    """

    def __init__(self, cw: CWorld) -> None:
        self.cw, w = cw, cw.w
        assert len(DECAY) == len(w.terms.ask_premium)
        self.menu = contracts(cw.playbook)
        self.index = {c: i for i, c in enumerate(self.menu)}
        self.types = cw.types
        prior = dict(w.prior)
        self.weight = [prior[t] for t in self.types]
        floor = np.array([[floor_price(c, w, t, cw.x) for t in self.types] for c in self.menu])
        self.cc = np.array([[client_cost(c, w, t, cw.x) for t in self.types] for c in self.menu])
        markup = MARKUP_UP * np.maximum(floor - floor[0], 0.0) + KEEP_DOWN * np.maximum(floor[0] - floor, 0.0)
        self.th = [_quote(floor + w.terms.ask_premium[r] + DECAY[r] * markup) for r in range(w.rounds + 1)]
        self.total = [self.th[r] + self.cc for r in range(w.rounds + 1)]
        self.out_name, self.out = cw.best_outside
        self.kappa, self.beta, self.rounds = w.terms.round_cost, w.terms.breakoff, w.rounds
        self._memo: dict[CState, float] = {}
        self._acc: dict[tuple[frozenset, frozenset], float] = {}
        self._f: dict[tuple[int, int], float] = {}

    # the pieces

    def type_index(self, it: ra.IntegratorType) -> int:
        return self.types.index(it)

    def _p(self, types: frozenset) -> dict[int, float]:
        z = math.fsum(self.weight[t] for t in types)
        return {t: self.weight[t] / z for t in sorted(types)}

    def _accept_value(self, types: frozenset, standing: frozenset) -> float:
        key = (types, standing)
        if key not in self._acc:
            p = self._p(types)
            self._acc[key] = min((math.fsum(q * (price + self.cc[ci, t]) for t, q in p.items()) for ci, price in standing), default=math.inf)
        return self._acc[key]

    def _single(self, t: int, round_: int) -> float:
        key = (t, round_)
        if key not in self._f:
            now = min(self.out, float(self.total[round_][:, t].min()))
            if round_ < self.rounds:
                now = min(now, self.kappa + self.beta * self.out + (1.0 - self.beta) * self._single(t, round_ + 1))
            self._f[key] = now
        return self._f[key]

    def _next(self, s: CState, types: frozenset, standing: frozenset) -> CState:
        last = s.round == self.rounds
        return CState(s.round if last else s.round + 1, last, types, standing)

    def answer(self, s: CState, ci: int, t: int) -> float:
        return round(float(self.th[s.round][ci, t]), 6)

    def after_answer(self, s: CState, contract: Contract, ans: float | None) -> CState:
        """The state after a proposal of this contract is answered with this all-in price (None: declined, off the menu).
        The client keeps the types whose price this round would have been the same."""
        ci = self.index.get(contract.normal())
        if ci is None:
            return self._next(s, s.types, s.standing)
        ans = round(ans, 6)
        types = frozenset(t for t in s.types if abs(self.answer(s, ci, t) - ans) < 1e-3)
        if not types:
            raise ValueError("an answer no consistent type would give")
        return self._next(s, types, frozenset({(k, v) for k, v in s.standing if k != ci} | {(ci, ans)}))

    def after_refusal(self, s: CState, contract: Contract, t_true: int) -> CState:
        """The state after the integrator of type t_true refuses a proposal of this contract."""
        ci = self.index.get(contract.normal())
        return self.after_answer(s, contract, None if ci is None else self.answer(s, ci, t_true))

    # values

    def q(self, s: CState, a: CAction) -> float:
        if a.kind == "walk":
            return self.cw.outside_cost(a.outside)
        p = self._p(s.types)
        if a.kind == "accept":
            ci = self.index[a.contract]
            price = dict(s.standing)[ci]
            return math.fsum(q * (price + self.cc[ci, t]) for t, q in p.items())
        if s.final:
            raise ValueError("no proposal after the last answer")
        refused_once = self.kappa + self.beta * self.out
        ci = self.index.get(a.contract.normal())
        if ci is None:
            return refused_once + (1.0 - self.beta) * self.value(self._next(s, s.types, s.standing))
        parts, groups = [], {}
        for t, q in p.items():
            thr = float(self.th[s.round][ci, t])
            if a.price is not None and a.price >= thr - 1e-6:
                parts.append(q * (a.price + self.cc[ci, t]))
            else:
                groups.setdefault(round(thr, 6), []).append(t)
        for ans, ts in groups.items():
            nxt = self._next(s, frozenset(ts), frozenset({(k, v) for k, v in s.standing if k != ci} | {(ci, ans)}))
            parts.append(math.fsum(p[t] for t in ts) * (refused_once + (1.0 - self.beta) * self.value(nxt)))
        return math.fsum(parts)

    def candidates(self, s: CState) -> list[CAction]:
        acts = [CAction("accept", self.menu[ci]) for ci, _ in sorted(s.standing)] + [CAction("walk", outside=o) for o in OUTSIDE]
        if not s.final:
            for ci, c in enumerate(self.menu):
                acts += [CAction("propose", c, x) for x in sorted({round(float(self.th[s.round][ci, t]), 6) for t in s.types})]
                acts.append(CAction("propose", c, None))
        return acts

    def value(self, s: CState) -> float:
        if s in self._memo:
            return self._memo[s]
        now = min(self.out, self._accept_value(s.types, s.standing))
        if s.final:
            v = now
        elif len(s.types) == 1:
            (t,) = s.types
            v = min(now, self._single(t, s.round))
        else:
            v = min(now, min(self.q(s, a) for a in self.candidates(s) if a.kind == "propose"))
        self._memo[s] = v
        return v

    def best(self, s: CState) -> CAction:
        return min(((round(self.q(s, a), 6), i, a) for i, a in enumerate(self.candidates(s))), key=lambda z: (z[0], z[1]))[2]

    def regret(self, s: CState, a: CAction) -> float:
        return max(0.0, self.q(s, a) - self.value(s))

    # the start

    def list_prices(self, it: ra.IntegratorType) -> tuple[tuple[int, float], ...]:
        t = self.type_index(it)
        return tuple((self.index[c], round(float(self.th[0][self.index[c], t]), 6)) for c in listed(self.cw.playbook))

    def start(self, it: ra.IntegratorType) -> CState:
        listing = self.list_prices(it)
        types = frozenset(k for k in range(len(self.types)) if all(abs(float(self.th[0][ci, k]) - x) < 1e-6 for ci, x in listing))
        return CState(1, False, types, frozenset(listing))

    def best_contract(self, it: ra.IntegratorType) -> tuple[Contract, float]:
        """The contract cheapest for the client at the integrator's last-round price, and that cost."""
        col = self.total[self.rounds][:, self.type_index(it)]
        ci = int(np.argmin(np.round(col, 6)))
        return self.menu[ci], float(col[ci])


@lru_cache(maxsize=64)
def _solver_for(key: str) -> ContractSolver:
    cw, _ = world_from(json.loads(key))
    return ContractSolver(cw)


def solver_for(payload: Mapping[str, Any]) -> ContractSolver:
    return _solver_for(json.dumps({k: payload[k] for k in ("world", "extras", "integrator_type")}, sort_keys=True))


# ---------------------------------------------------------------------------
# Lower controls.

RULES = ("accept_the_base", "cheapest_listed_price", "haggle_the_base", "every_protection", "walk_to_turnkey")


def most_protective(playbook: str) -> Contract:
    """The menu's contract that moves the most onto the integrator: the highest warranty and damages, no cap,
    standby and incidents on it, no unprotected deposit, a burn-in."""
    return max(contracts(playbook), key=lambda c: (c.warranty == "fix_and_delay", c.warranty != "none", int(c.damages) if c.warranty == "fix_and_delay" else 0,
                                                   CAP[c.liability_cap], c.readiness == "integrator",
                                                   c.consequential == "included", c.deposit == "none" or c.escrow, c.deposit == "none", c.burn_in))


def rule_action(name: str, solver: ContractSolver, s: CState) -> CAction:
    base = BASES[solver.cw.playbook]
    standing = {solver.menu[ci]: price for ci, price in s.standing}
    if name == "accept_the_base":
        return CAction("accept", base)
    if name == "walk_to_turnkey":
        return CAction("walk", outside="turnkey")
    if name == "cheapest_listed_price":
        return CAction("accept", min(standing, key=lambda c: (standing[c], c)))
    if name == "haggle_the_base":
        if s.final:
            return CAction("accept", base)
        hw = solver.cw.w.terms.hardware
        return CAction("propose", base, round(hw + 0.5 * (standing[base] - hw), 3))
    if name == "every_protection":
        c = most_protective(solver.cw.playbook)
        return CAction("accept", c) if c in standing else CAction("propose", c, None)
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Worlds: each admitted only when its lesson holds for the informed reference.

CELLS: dict[str, dict[str, Any]] = {
    "cheapest_is_not_best": {
        "lesson": "the lowest price on the list is not the cheapest contract for this client once the risks it leaves are counted",
        "client_charge": 0.75, "ranges": {}, "playbooks": PLAYBOOKS, "losers": ("cheapest_listed", "base", "every_protection")},
    "buy_the_cover": {
        "lesson": "incident cover is worth its price to a client this averse to risk",
        "client_charge": 1.55, "ranges": dict(incident=(0.05, 0.08)), "playbooks": PLAYBOOKS, "losers": ("cheapest_listed", "base")},
    "keep_the_liability": {
        "lesson": "a lower liability cap is cheaper but hands the tail back; keep the integrator's liability uncapped",
        "client_charge": 1.55, "ranges": dict(incident=(0.05, 0.08), incident_loss=(3000.0, 4000.0)), "playbooks": PLAYBOOKS,
        "losers": ("cheapest_listed", "base")},
    "take_the_cap": {
        "lesson": "this client carries risk more cheaply than the integrator; a cap lowers the price by more than the risk it hands back",
        "client_charge": 0.15, "ranges": dict(team=(1300.0, 1700.0)), "playbooks": ("managed", "turnkey"), "losers": ("base", "every_protection")},
    "just_enough_damages": {
        "lesson": "delay damages are worth buying only up to the rate that makes the integrator pre-stage",
        "client_charge": 0.15, "ranges": dict(team=(1300.0, 1700.0)), "playbooks": ("managed", "turnkey"), "losers": ("base", "every_protection")},
    "protect_the_deposit": {
        "lesson": "the integrator may fail before delivery; put the deposit in escrow or pay none up front",
        "client_charge": 0.75, "ranges": dict(insolvency=(0.03, 0.06)), "playbooks": PLAYBOOKS, "losers": ("cheapest_listed", "base")},
    "buy_the_burn_in": {
        "lesson": "an incident is likely and costly; a week's burn-in that halves its chance pays for itself",
        "client_charge": 1.55, "ranges": dict(incident=(0.08, 0.12), incident_loss=(3500.0, 4500.0)), "playbooks": PLAYBOOKS,
        "losers": ("cheapest_listed", "base")},
    "hand_over_readiness": {
        "lesson": "an integrator that carries readiness prepares the site; moving it across cuts the chance of a late facility",
        "client_charge": 0.75, "ranges": dict(unready=(0.3, 0.4), unready_weeks=(4.0, 6.0), site_prep=(20.0, 50.0)),
        "playbooks": ("coordination", "turnkey"), "losers": ("cheapest_listed", "base", "every_protection")},
    "raise_the_damages": {
        "lesson": "delay damages are insurance this client values above their price; take the highest rate",
        "client_charge": 1.55, "ranges": dict(defect_weeks=(4.0, 6.0)), "playbooks": ("managed", "turnkey"),
        "losers": ("cheapest_listed", "base", "every_protection")},
    "sign_now": {
        "lesson": "the integrator is likely to break off after a refusal and the deal is worth far more than walking; sign this round",
        "client_charge": 1.55, "ranges": dict(breakoff=(0.35, 0.5), turnkey_offset=(1000.0, 1400.0)), "playbooks": PLAYBOOKS,
        "losers": ("cheapest_listed", "base")},
    "walk_away": {
        "lesson": "no contract on this menu beats the better outside option; walk to it",
        "client_charge": 0.75, "ranges": dict(turnkey_offset=(-450.0, -200.0)), "playbooks": PLAYBOOKS, "losers": ()},
}
_RANGES = {**ra._COMMON, "team": (600.0, 1000.0), "turnkey_offset": (150.0, 700.0), "site_prep": (30.0, 90.0)}
WALK_MARGIN = 150.0  # the best deal and the better outside option are at least this far apart, either way
CHOICE_MARGIN = 75.0  # each shortcut a situation names costs the client at least this much more than the best contract


def shortcuts(solver: "ContractSolver", s: CState) -> dict[str, Contract]:
    """The contracts a client that does not weigh the terms would reach for."""
    standing = {solver.menu[ci]: price for ci, price in s.standing}
    return {"cheapest_listed": min(standing, key=lambda c: (standing[c], c)), "base": BASES[solver.cw.playbook],
            "every_protection": most_protective(solver.cw.playbook)}


def draw_world(rng: random.Random, cell: str, playbook: str) -> tuple[CWorld, ra.IntegratorType]:
    spec = {**_RANGES, **CELLS[cell]["ranges"]}
    u = {k: rng.uniform(*v) for k, v in spec.items()}
    r2 = ra._round
    risks = ra.Risks(
        defect_without_test=r2(u["defect_without_test"], 0.01), defect_with_test=r2(u["defect_with_test"], 0.01),
        defect_fix=r2(u["defect_fix"], 10), defect_weeks=r2(u["defect_weeks"], 1), unready=r2(u["unready"], 0.01),
        standby=r2(u["standby"], 10), unready_weeks=r2(u["unready_weeks"], 1), incident=r2(u["incident"], 0.005),
        incident_loss=r2(u["incident_loss"], 100),
    )
    client = ra.Client(delay_per_week=r2(u["delay_per_week"], 5), risk_charge=CELLS[cell]["client_charge"],
                       capital_rate=r2(u["capital_rate"], 0.005), insolvency=r2(u["insolvency"], 0.001), turnkey_all_in=0.0)
    w = ra.World(risks, client, ra.Terms(**ra.FIXED_TERMS, breakoff=r2(u["breakoff"], 0.01)))
    types = [t for t, _ in w.prior if playbook_of(t) == playbook]
    it = types[rng.randrange(len(types))]
    cw = CWorld(w, Extras(r2(u["team"], 10), r2(u["site_prep"], 5)), playbook)
    _, best = ContractSolver(cw).best_contract(it)
    w = replace(w, client=replace(client, turnkey_all_in=r2(best + u["turnkey_offset"], 10)))
    return replace(cw, w=w), it


def lesson_holds(cell: str, cw: CWorld, it: ra.IntegratorType) -> bool:
    solver = ContractSolver(cw)
    s = solver.start(it)
    ref = solver.best(s)
    best, best_cost = solver.best_contract(it)
    out, out_cost = cw.best_outside
    if cell == "walk_away":
        return ref.kind == "walk" and ref.outside == out and best_cost > out_cost + WALK_MARGIN
    if ref.kind == "walk" or best_cost > out_cost - WALK_MARGIN:
        return False
    t = solver.type_index(it)
    last = solver.th[solver.rounds]
    cut = shortcuts(solver, s)
    if any(solver.total[solver.rounds][solver.index[cut[name]], t] - best_cost < CHOICE_MARGIN for name in CELLS[cell]["losers"]):
        return False
    cheapest = cut["cheapest_listed"]
    if cell == "cheapest_is_not_best":
        return True
    if cell == "buy_the_cover":
        return best.consequential == "included"
    if cell == "keep_the_liability":
        capped = [c for c in solver.menu if c.liability_cap != "uncapped" and replace(c, liability_cap="uncapped") == best]
        return best.liability_cap == "uncapped" and any(last[solver.index[c], t] < last[solver.index[best], t] - 1.0 for c in capped)
    if cell == "take_the_cap":
        uncapped = replace(best, liability_cap="uncapped")
        return best.liability_cap != "uncapped" and last[solver.index[uncapped], t] > last[solver.index[best], t] + 1.0
    if cell == "just_enough_damages":
        return best.warranty == "fix_and_delay" and int(best.damages) < 200 and best_response(best, cw.w, it, cw.x)[0]
    if cell == "protect_the_deposit":
        return (best.deposit == "none" or best.escrow) and cheapest.deposit != "none" and not cheapest.escrow
    if cell == "buy_the_burn_in":
        return best.burn_in
    if cell == "hand_over_readiness":
        return best.readiness == "integrator" and best_response(best, cw.w, it, cw.x)[1]
    if cell == "raise_the_damages":
        return best.warranty == "fix_and_delay" and best.damages == "200"
    if cell == "sign_now":  # the reference's first move is a counter this integrator signs
        return (ref.kind == "propose" and ref.price is not None
                and ref.price >= float(solver.th[s.round][solver.index[ref.contract], t]) - 1e-6)
    raise KeyError(cell)


def build_pack(seeds_per_cell: int, base_seed: int, max_draws: int = 9000) -> list[dict[str, Any]]:
    rows = []
    for ci, cell in enumerate(CELLS):
        for pi, playbook in enumerate(PLAYBOOKS):
            if playbook not in CELLS[cell]["playbooks"]:
                continue
            made, seed = 0, base_seed + 100000 * ci + 10000 * pi  # disjoint seed ranges per situation and playbook
            stop = seed + max_draws
            while made < seeds_per_cell and seed < stop:
                cw, it = draw_world(random.Random(seed), cell, playbook)
                seed += 1
                if not lesson_holds(cell, cw, it):
                    continue
                rows.append({"slug": f"{cell}__{playbook}__{seed - 1}", "cell": cell, "playbook": playbook, "seed": seed - 1,
                             "lesson": CELLS[cell]["lesson"], "world": ra.world_to_dict(cw.w),
                             "extras": {"team": cw.x.team, "site_prep": cw.x.site_prep},
                             "integrator_type": {"test_cost": it.test_cost, "risk_charge": it.risk_charge}})
                made += 1
    return rows


# ---------------------------------------------------------------------------
# What the client is told: the world, the terms, the posted list. Not the policy.

_PLAYBOOK_TEXT = {
    "coordination": ("Coordination service. You buy the hardware from the vendors at cost ({hw}); the integrator coordinates the delivery "
                     "for a fee. Prices are the integrator's fee; you pay the hardware on top."),
    "managed": ("Managed delivery. The integrator procures the hardware at cost ({hw}) and manages the delivery for a fee. "
                "Prices are the integrator's fee; you pay the hardware on top."),
    "turnkey": "Turnkey delivery. One all-in price including the hardware ({hw}). Prices are all in.",
}
_TERM_TEXT = {
    "warranty": "warranty: none (you pay a defect's fix) | fix (the integrator pays the fix) | fix_and_delay (it pays the fix and delay damages per week of defect delay)",
    "damages": "damages: the delay-damages rate under fix_and_delay, 50 | 100 | 200 ($k a week of defect delay)",
    "liability_cap": ("liability_cap: uncapped | 1500 | 500: the most the integrator pays you in total for one delivery, across fix, delay damages, "
                      "standby and an incident's losses ($k); past it you bear the rest"),
    "readiness": ("readiness: client (you pay standby if your facility is late) | integrator (it does, and it then prepares your site whenever "
                  "that is cheaper for it, which cuts the chance of a late facility)"),
    "consequential": "consequential: excluded (you carry a post-handover incident's losses) | included (the integrator does)",
    "deposit": "deposit: none | 25% | 50% of the hardware, paid at signing {weeks:g} weeks before delivery",
    "escrow": ("escrow: false | true: the deposit is held in escrow until delivery, safe if the integrator fails; escrow costs you {fee}, "
               "and the integrator then cannot use the money"),
    "burn_in": ("burn_in: false | true: a one-week acceptance burn-in before handover; it halves the chance of an incident, "
                "delays go-live one week and costs the integrator a crew of {crew}"),
}


def show(cw: CWorld, price_all_in: float) -> float:
    """A price in the playbook's own terms: the fee for a fee-based playbook, else all in."""
    return round(price_all_in - cw.w.terms.hardware, 3) if fee_based(cw.playbook) else round(price_all_in, 3)


def all_in(cw: CWorld, shown: float) -> float:
    return shown + cw.w.terms.hardware if fee_based(cw.playbook) else shown


def _level(v: Any) -> str:
    return str(v).lower() if isinstance(v, bool) else str(v)


def brief(cw: CWorld, offers: list[Mapping[str, Any]]) -> str:
    """The client's brief. ``offers`` are the list's standing offers as the observation shows them."""
    w, x = cw.w, cw.x
    c, t = w.client, w.terms
    tests = sorted({i.test_cost for i, _ in w.prior})
    charges = sorted({i.risk_charge for i, _ in w.prior})
    unit = "fee" if fee_based(cw.playbook) else "all-in price"
    base, neg = BASES[cw.playbook], NEGOTIABLE[cw.playbook]
    fixed = [k for k in TERMS if k not in neg]
    return "\n".join([
        "You are the client. An integrator will deliver a GPU cluster into your facility. Money is in $ thousands.",
        "",
        *ra._risk_lines(w, "client"),
        f"- Preparing your site costs the integrator {ra._k(x.site_prep)}; after it the chance your facility is late falls to "
        f"{ra._pct(round(w.risks.unready * SITE_PREP_EFFECT, 6))}. Only an integrator that pays standby has a reason to do it.",
        "",
        "Contract terms:",
        *[f"- {_TERM_TEXT[k].format(weeks=t.deposit_weeks, fee=ra._k(ESCROW_FEE), crew=ra._k(BURN_IN_CREW))}" for k in TERMS],
        "",
        "Your position:",
        f"- Each $1 of expected loss you carry costs you ${1 + c.risk_charge:.2f} (covenants and insurance).",
        f"- Your capital costs {ra._pct(c.capital_rate)} a year. There is a {ra._pct(c.insolvency)} chance the integrator fails before delivery; "
        "a deposit not in escrow is then lost.",
        f"- Outside option 1: a rival turnkey contract at {ra._k(c.turnkey_all_in)} all in, every risk priced in.",
        f"- Outside option 2: manage the deployment yourself. Your own team would cost {ra._k(x.team)} besides the hardware; you would carry "
        "every risk yourself, pay every fix and every week of standby, and nobody would pre-stage the cluster or prepare the site.",
        "",
        "The integrator: each $1 of expected payout it carries costs it $1 plus its own risk charge, which is "
        f"{' or '.join(f'{v:g}' for v in charges)}; pre-staging costs it {' or '.join(ra._k(v) for v in tests)} "
        "(each combination equally likely; not disclosed). It pre-stages, and prepares your site, exactly when the contract makes that "
        "cheaper for it than not.",
        _PLAYBOOK_TEXT[cw.playbook].format(hw=ra._k(t.hardware)),
        f"Its base contract: {base.label()}.",
        "Negotiable on this playbook: " + "; ".join(f"{k} ({' | '.join(_level(v) for v in levels)})" for k, levels in neg.items()) + ". "
        f"Every combination of these is on its menu. Fixed: {', '.join(f'{k} {_level(getattr(base, k))}' for k in fixed) or 'nothing'}.",
        f"Its list prices the base and each single change ({unit}):",
        *[f"- {o['id']}: {Contract(**o['terms']).label()}: {ra._k(o['price'])}" for o in offers],
        "",
        f"You have {w.rounds} rounds. In each you may accept any standing offer at its price, walk away to either outside option, counter any "
        f"contract on the menu with a {unit}, or ask its price. If the integrator will sign at your figure it signs; otherwise it answers with "
        f"its own {unit} for that contract this round, which becomes a standing offer. A contract off its menu is declined without a price. "
        "After the last round's answer you may only accept or walk.",
        f"After each counter or request it does not sign, the integrator breaks off {ra._pct(t.breakoff)} of the time (you then take the better "
        f"outside option), and each costs you {ra._k(t.round_cost)}.",
        "Your objective: the lowest expected total cost to you: what you pay, plus every expected loss you carry at your risk charge, plus deposit "
        "financing, the escrow fee and a burn-in week, plus the cost of each counter or request not signed; walking away costs you the outside "
        "option you choose.",
    ])


# ---------------------------------------------------------------------------
# The episode's grade.


def action_of(d: Mapping[str, Any]) -> CAction:
    return CAction(d["kind"], None if d.get("contract") is None else Contract(**d["contract"]), d.get("price"), d.get("outside"))


def grade(payload: Mapping[str, Any], decisions: list[Mapping[str, Any]], signed: Mapping[str, Any] | None, outside: str | None,
          termination: str, refused: int) -> dict[str, Any]:
    """Decision regret against the informed client, and what the client ended with at the true type."""
    solver = solver_for(payload)
    cw, it = world_from(payload)
    t = solver.type_index(it)
    s = solver.start(it)
    per = []
    for d in decisions:
        a = action_of(d)
        per.append({"round": s.round, "final": s.final, "action": a.label(), "regret": round(solver.regret(s, a), 6)})
        if a.kind != "propose":
            break
        ci = solver.index.get(a.contract.normal())
        if ci is not None and a.price is not None and a.price >= float(solver.th[s.round][ci, t]) - 1e-6:
            break
        s = solver.after_refusal(s, a.contract, t)
    best, best_cost = solver.best_contract(it)
    out_name, out_cost = cw.best_outside
    rc = refused * cw.w.terms.round_cost
    if signed is not None:
        c = Contract(**signed["contract"])
        realised = signed["price"] + client_cost(c, cw.w, it, cw.x) + rc
        over_floor = signed["price"] - float(solver.th[solver.rounds][solver.index[c], t])
    else:
        c = None
        realised = cw.outside_cost(outside if outside else out_name) + rc
        over_floor = None
    deal = best_cost < out_cost
    col = solver.total[solver.rounds][:, t]
    ties = [solver.menu[i] for i in range(len(solver.menu)) if col[i] < best_cost + 0.5]  # economically the best, to $500
    nearest = None if c is None else max(ties, key=lambda b: (sum(getattr(c, k) == getattr(b, k) for k in TERMS), b == best))
    return {
        "valid": termination != "invalid_action",
        "termination": termination,
        "decision_regret": round(math.fsum(p["regret"] for p in per), 6),
        "decisions": per,
        "playbook": cw.playbook,
        "signed_contract": None if c is None else c.as_dict(),
        "best_contract": best.as_dict(),
        "best_is_deal": deal,
        "best_outside": out_name,
        "best_contract_ties": len(ties),
        "signed_best_contract": c is not None and c in ties and deal,
        "terms_matching_best": None if c is None else sum(getattr(c, k) == getattr(nearest, k) for k in TERMS),
        "terms_off_best": None if c is None else [k for k in TERMS if getattr(c, k) != getattr(nearest, k)],
        "walked_to": outside,
        "price_over_floor": None if over_floor is None else round(over_floor, 3),
        "realised_cost": round(realised, 3),
        "cost_over_best_attainable": round(realised - min(best_cost, out_cost), 3),
        "refused_counters": refused,
    }


__all__ = [
    "BASES", "CELLS", "CAction", "CState", "CWorld", "Contract", "ContractSolver", "Extras", "LEVELS", "NEGOTIABLE", "OUTSIDE", "PLAYBOOKS",
    "RULES", "TERMS", "action_of", "shortcuts", "all_in", "best_response", "brief", "build_pack", "client_cost", "contract_from", "contracts", "draw_world",
    "fee_based", "floor_price", "grade", "integrator_cost", "lesson_holds", "listed", "most_protective", "outcomes", "rule_action", "show", "solver_for",
    "threshold", "world_from",
]
