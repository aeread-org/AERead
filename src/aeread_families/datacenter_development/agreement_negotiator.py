"""A scripted negotiator for the agreement case: it plays either seat on what that seat is told.

It uses only its seat's information: its own costs exactly, and the other side's as the declared
list of possible types with their odds. It never reads the other side's true type.

What it does on a move:

1. **Belief.** It starts from the declared odds and drops every type of the other side that would
   have lost money on an offer that side itself put on the table.
2. **Clauses.** It proposes the clause set that creates the most expected value for the two sides
   together, under that belief. This is where an agreement gets better than the draft.
3. **Price.** It asks for a share of the expected surplus: ``opening`` on its first proposal, and
   never less than ``final``. Between proposals it comes down by one step scaled by how far the
   other side came toward it since its last proposal, measured in what the other side's offers
   are worth to the script (``reciprocity`` 1), or by one step regardless (``reciprocity`` 0).
   A side that does not move gets nothing for waiting. It never asks more than the types it means
   to reach could sign without losing, and it picks the reach that is worth most to it.
4. **Sign, counter or walk.** It signs the offer on the table when that is worth at least what it
   expects from its next counter-offer after paying for the redline, or when it has no proposal
   left. It never signs below its own outside option, nor for less than the share ``least`` of the
   surplus it believes there is, and it walks when nothing left to it meets that. ``least`` is what
   makes a last-move ultimatum risky for the other side; it costs the pair a deal when it binds.

``STYLES`` names fixed settings: three that hold a line to different degrees; ``soft``, which gives way; and three
tactics a counterpart can use that change the right reply (``overreach``, ``price_only``, ``collapse``). ``drawn_style`` draws one from ``POPULATION`` from the world
and the seat alone, so a world always meets the same counterpart and a replay reproduces it, and
the other side is not told which. The style is declared in the plan, so a result against the
script says which script.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, Mapping

from . import agreement as ag
from . import risk_allocation as ra
from . import risk_allocation_contracts as rc


@dataclass(frozen=True)
class Style:
    opening: float  # share of expected surplus asked on the first proposal
    final: float  # share asked on the last proposal
    least: float = 0.0  # the smallest share of the surplus it believes there is that it will sign for
    reciprocity: float = 1.0  # 1: it comes down only as far as the other side came toward it; 0: one step a proposal regardless
    cover: float = 0.0  # the least belief mass a proposal must be signable by; 0 lets it pick the reach worth most to it
    accept_odds: float = 0.8  # how likely it takes its own next counter-offer to be signed, when weighing sign against counter
    past: bool = False  # True: an ask of 1 or more is priced past what any declared type of the other side could sign
    clauses: str = "best"  # "best": it proposes the clauses worth most; "standing": it never touches a clause and haggles the price only
    late: bool = False  # True: it holds its opening ask until its last proposal, then drops to ``final`` in one step


STYLES: dict[str, Style] = {
    "even": Style(opening=0.60, final=0.50, least=0.20),
    "firm": Style(opening=0.80, final=0.65, least=0.30),
    "hard": Style(opening=0.95, final=0.85, least=0.40, accept_odds=0.7),
    # gives way: it comes down on the clock whatever the other side does, signs whatever beats walking away,
    # and takes an offer on the table over a counter-offer it thinks unlikely to be signed
    "soft": Style(opening=0.55, final=0.25, least=0.0, reciprocity=0.0, accept_odds=0.4),
    # asks for more than there is: its first offers leave the other side worse off than walking away, and it comes
    # down on the clock to an offer worth signing. The right reply is to refuse the early ones.
    "overreach": Style(opening=1.30, final=0.70, least=0.20, reciprocity=0.0, past=True),
    # never touches a clause: it prices whatever clauses stand. The other side has to fix the clauses itself.
    "price_only": Style(opening=0.70, final=0.50, least=0.20, reciprocity=1.0, clauses="standing"),
    # holds a high ask until its last proposal, then gives most of it up, and signs anything that beats walking away.
    # Patience is what pays against it.
    "collapse": Style(opening=0.90, final=0.30, least=0.0, late=True),
}
NOMINAL = 5.0  # what a price-only script asks above its break-even when the clauses as they stand create nothing
DRAWN = "drawn"
#: What ``drawn_style`` draws from, uniformly and independently.
POPULATION = {"opening": (0.60, 0.90), "comes_down": (0.05, 0.30), "final_at_least": 0.45, "least": (0.10, 0.35), "reciprocity": (0.5, 1.0)}
EPS = 1e-6


def drawn_style(cw: rc.CWorld, seat: str) -> Style:
    """The counterpart this world has in this seat: a function of the world and the seat, nothing else."""
    rng = random.Random(int(hashlib.sha256(repr((cw, seat, "agreement_negotiator_population_v1")).encode("utf-8")).hexdigest(), 16))
    opening = rng.uniform(*POPULATION["opening"])
    final = max(POPULATION["final_at_least"], opening - rng.uniform(*POPULATION["comes_down"]))
    return Style(opening=round(opening, 3), final=round(final, 3), least=round(rng.uniform(*POPULATION["least"]), 3),
                 reciprocity=rng.choice(POPULATION["reciprocity"]))


@dataclass(frozen=True)
class Other:
    """One possible type of the other side, and how likely."""
    integrator: ra.IntegratorType | None  # set when the script is the client
    charge: float | None  # the client's risk charge, set when the script is the integrator
    p: float


@lru_cache(maxsize=4096)
def _outside(cw: rc.CWorld, charge: float) -> float:
    return replace(cw, w=replace(cw.w, client=replace(cw.w.client, risk_charge=charge))).best_outside[1]


@lru_cache(maxsize=200_000)
def _costs(cw: rc.CWorld, it: ra.IntegratorType, charge: float, c: rc.Contract) -> tuple[float, float]:
    return rc.integrator_cost(c, cw.w, it, cw.x), rc.client_cost(c, cw.w, it, cw.x, charge)


class Negotiator:
    def __init__(self, cw: rc.CWorld, seat: str, own: ra.IntegratorType | None, style: str | Style = "even") -> None:
        if seat not in ag.SEATS or (seat == "integrator") != (own is not None):
            raise ValueError("the integrator's script needs its own type; the client's must not have one")
        self.cw, self.seat, self.own = cw, seat, own
        self.style = style if isinstance(style, Style) else drawn_style(cw, seat) if style == DRAWN else STYLES[style]
        self._pies: dict[tuple[Other, ...], float] = {}
        self.floor = cw.w.terms.floor_margin
        self.round_cost = cw.w.terms.round_cost
        if seat == "integrator":
            self.prior = [Other(None, c, p) for c, p in cw.w.client_prior]
        else:
            types = cw.types
            weight = {t: p for t, p in cw.w.prior}
            total = math.fsum(weight[t] for t in types)
            self.prior = [Other(t, None, weight[t] / total) for t in types]

    # ---- what a signed agreement is worth to each side, for one possible type of the other ----
    def _pair(self, o: Other) -> tuple[ra.IntegratorType, float]:
        return (self.own, o.charge) if self.seat == "integrator" else (o.integrator, self.cw.w.client.risk_charge)

    def surplus(self, c: rc.Contract, price: float, o: Other) -> tuple[float, float]:
        """(mine, theirs) over each side's outside option."""
        it, charge = self._pair(o)
        ic, cc = _costs(self.cw, it, charge, c)
        integrator, client = price - ic - self.floor, _outside(self.cw, charge) - price - cc
        return (integrator, client) if self.seat == "integrator" else (client, integrator)

    def total(self, c: rc.Contract, o: Other) -> float:
        return math.fsum(self.surplus(c, 0.0, o))

    def mine(self, c: rc.Contract, price: float, belief: list[Other]) -> float:
        return math.fsum(o.p * self.surplus(c, price, o)[0] for o in belief)

    # ---- belief ----
    def belief(self, state: Mapping[str, Any]) -> list[Other]:
        """The declared odds, less every type that would have lost on an offer the other side made itself."""
        live = list(self.prior)
        terms = ag.draft(self.cw)
        for h in state["history"]:
            if h["action"] != "redline":
                continue
            terms = rc.contract_from({k: v["now"] for k, v in h["changes"].items()}, terms)
            if h["by"] != self.seat:
                kept = [o for o in live if self.surplus(terms, h["price"], o)[1] >= -EPS]
                live = kept or live  # an offer no declared type would make tells nothing; keep the belief
        mass = math.fsum(o.p for o in live)
        return [replace(o, p=o.p / mass) for o in live]

    # ---- proposing ----
    def pie(self, belief: list[Other]) -> float:
        """The surplus it believes there is: the most any one agreement makes in expectation."""
        key = tuple(belief)
        if key not in self._pies:
            self._pies[key] = max(0.0, max(math.fsum(o.p * self.total(c, o) for o in belief) for c in ag.ALL_AGREEMENTS))
        return self._pies[key]

    def _ask(self, state: Mapping[str, Any], belief: list[Other]) -> float:
        """The share it asks now: the opening, less one step for each proposal it made before, each step scaled by
        how far the other side came toward it in between (in shares of the pie, as the script values the offers)."""
        st = self.style
        mine = ag.MOVES // 2 if self.seat == ag.FIRST else ag.MOVES // 2 - 1
        step = 0.0 if mine <= 1 else (st.opening - st.final) / (mine - 1)
        if st.late:
            made = sum(1 for h in state["history"] if h["action"] == "redline" and h["by"] == self.seat)
            return st.final if made >= mine - 1 else st.opening
        pie = self.pie(belief)
        share, asked, theirs, moved = st.opening, False, None, None
        terms = ag.draft(self.cw)
        for h in state["history"]:
            if h["action"] != "redline":
                continue
            terms = rc.contract_from({k: v["now"] for k, v in h["changes"].items()}, terms)
            if h["by"] == self.seat:
                if asked:
                    share = max(st.final, share - step * self._credit(moved, step))
                asked, moved = True, None
            else:
                worth = self.mine(terms, h["price"], belief) / pie if pie > EPS else 0.0
                # its first offer counts as a full step when it clears ``least``; later ones by how much they improved
                moved = (1.0 if worth >= st.least - EPS else 0.0) * step if theirs is None else worth - theirs
                theirs = worth
        return max(st.final, share - step * self._credit(moved, step)) if asked else share

    def _credit(self, moved: float | None, step: float) -> float:
        """How much of one step the other side's movement earns: all of it at ``reciprocity`` 0."""
        earned = 0.0 if moved is None or step <= EPS else min(2.0, max(0.0, moved / step))
        return (1.0 - self.style.reciprocity) + self.style.reciprocity * earned

    def proposal(self, state: Mapping[str, Any], belief: list[Other]) -> tuple[rc.Contract, float, float] | None:
        """(clauses, price, what it is worth to me in expectation, counting a refusal as nothing), or None.

        It may not be worth pricing for every type of the other side: a type with little to gain can
        only be reached at a price that gives the rest away. So it considers reaching the types in
        order of how much they have to gain, and keeps the reach that is worth most to it."""
        d = ag.draft(self.cw)
        sign = 1.0 if self.seat == "integrator" else -1.0  # a higher price is better for the integrator
        share = self._ask(state, belief)
        best_offer: tuple[rc.Contract, float, float] | None = None
        gain = lambda o: max(self.total(c, o) for c in ag.ALL_AGREEMENTS)
        ranked = sorted(belief, key=lambda o: (-round(gain(o), 6), o.p))
        standing = rc.Contract(**state["terms"]) if self.style.clauses == "standing" else None
        for n in range(len(ranked) if self.style.past else 1, len(ranked) + 1):
            reach = ranked[:n]
            mass = math.fsum(o.p for o in reach)
            if mass < self.style.cover - EPS and n < len(ranked):
                continue
            inside = [replace(o, p=o.p / mass) for o in reach]
            c = standing or max(ag.ALL_AGREEMENTS, key=lambda k: (round(math.fsum(o.p * self.total(k, o) for o in inside), 6), k == d, k))
            expected = math.fsum(o.p * self.total(c, o) for o in inside)
            if expected <= EPS and standing is None:
                continue
            level = -sign * self.mine(c, 0.0, inside)  # the price at which I am level with walking away, in expectation
            cap = sign * min(self.surplus(c, 0.0, o)[1] * sign for o in reach) if sign > 0 else max(-self.surplus(c, 0.0, o)[1] for o in reach)
            price = level + sign * (share * expected if expected > EPS else NOMINAL)
            if self.style.past and share >= 1.0:
                # past what the keenest type of the other side could sign, by the part of the ask above everything
                keenest = max(self.surplus(c, 0.0, o)[1] for o in reach) if sign > 0 else min(-self.surplus(c, 0.0, o)[1] for o in reach)
                price = keenest + sign * ((share - 1.0) * expected + 5.0)
            elif expected > EPS:
                price = min(price, cap) if sign > 0 else max(price, cap)
            price = math.floor(price / 5.0) * 5.0 if sign > 0 else math.ceil(price / 5.0) * 5.0  # whole $5k, never past the cap
            worth = mass * self.mine(c, price, inside)
            if worth > EPS and (best_offer is None or worth > best_offer[2] + EPS):
                best_offer = (c, price, worth)
        return best_offer

    # ---- the move ----
    def move(self, state: Mapping[str, Any]) -> dict[str, Any]:
        if state["to_move"] != self.seat:
            raise ValueError("not this seat's move")
        belief = self.belief(state)
        standing = state["standing"]
        on_table = self.mine(rc.Contract(**state["terms"]), standing["price"], belief) if standing is not None and standing["by"] != self.seat else None
        can_redline = "redline" in ag.allowed(state)
        offer = self.proposal(state, belief) if can_redline else None
        fee = self.round_cost if state["move"] > 1 else 0.0
        counter = None if offer is None else self.style.accept_odds * offer[2] - fee
        enough = on_table is not None and on_table >= max(0.0, self.style.least * self.pie(belief)) - EPS
        if enough and (counter is None or on_table >= counter - EPS):
            return {"action": "sign", "clauses": None, "price": None, "note": None}
        if offer is not None and (counter > EPS or self.style.clauses == "standing"):  # a price-only script keeps haggling while it can
            best, price, _ = offer
            now = rc.Contract(**state["terms"])
            return {"action": "redline", "clauses": {k: (getattr(best, k) if getattr(best, k) != getattr(now, k) else None) for k in ag.TERMS},
                    "price": float(price), "note": None}
        return {"action": "walk", "clauses": None, "price": None, "note": None}


def negotiator_move(state: Mapping[str, Any], cw: rc.CWorld, it: ra.IntegratorType, style: str | Style = "even") -> dict[str, Any]:
    """The scripted move for the seat to move. ``it`` is passed to the integrator's script only."""
    seat = state["to_move"]
    return Negotiator(cw, seat, it if seat == "integrator" else None, style).move(state)


__all__ = ["DRAWN", "Negotiator", "POPULATION", "STYLES", "Style", "drawn_style", "negotiator_move"]
