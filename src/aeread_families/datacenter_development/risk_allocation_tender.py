"""A tender: one client, several integrators bidding at once, every contract term negotiable.

The full-terms case (:mod:`.risk_allocation_contracts`) seats the client against one
integrator and its posted list. Here three integrators bid for the same delivery, one bid
each: its playbook's standard contract at its opening price. Each is a separate firm with
its own private type (what pre-staging costs it and what carrying risk costs it), drawn
independently from the declared prior, and the contracts module's pricing policy prices
every contract on its playbook's menu for that type. Managing the deployment itself is
the client's only walk-away.

The client negotiates with any of them in the same turn. A turn is an accept of one
standing offer, a walk, or a set of moves, at most one per bidder: a counter (a contract
and a price) or a request for the price of a contract. A bidder that would sign at the
client's figure confirms it, and the confirmed price becomes a standing offer. Otherwise
it answers with its own price for that contract at its current round, which becomes a
standing offer; the refusal costs the client a week of team time, the bidder breaks off
with the world's probability (its offers withdrawn) and its round advances. After a
bidder's answer at its last round only its standing offers remain, and after the last
turn the client may only accept or walk.

Only managed and turnkey firms bid. A coordination firm's standard fee is the same for
every type, so its one bid would leave its costs unknown; the reference below is exact
because every bid reveals its firm's type to a client who knows the policy, and a world
is admitted only when it does (:func:`identified`).

The reference (:class:`TenderSolver`) plays on the client's own information: the pricing
policy and the prior, from which each bid reveals its firm's type. With the types known,
every refused proposal to a bidder has the same effect but for the standing offer it
leaves, so the best one asks the price of the contract cheapest for the client at that
round, and every confirmed counter is dominated by countering that contract at its
threshold. A bidder's state is its round, whether it is still bidding and the lowest
total cost among its standing offers; the programme over the bidders' states is small
and exact.
"""

from __future__ import annotations

import itertools
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

import numpy as np

from . import risk_allocation as ra
from . import risk_allocation_contracts as rc
from .risk_allocation_menu import self_manage_cost

PLAYBOOKS = ("managed", "turnkey")
BIDDER_IDS = ("B1", "B2", "B3")
COMPOSITIONS = (("managed", "turnkey", "turnkey"), ("managed", "managed", "turnkey"))
OUTSIDE = "self_manage"


# ---------------------------------------------------------------------------
# One bidder as the contracts module prices it.


@dataclass(frozen=True)
class BidderWorld(rc.CWorld):
    """A bidder's playbook in this world: any type of the declared prior, and self-management the only walk-away."""

    @property
    def types(self) -> tuple[ra.IntegratorType, ...]:
        return tuple(t for t, _ in self.w.prior)

    def outside_cost(self, which: str) -> float:
        if which != OUTSIDE:
            raise ValueError("the tender's only walk-away is managing the deployment")
        return self_manage_cost(self.w, self.x.team)

    @property
    def best_outside(self) -> tuple[str, float]:
        return OUTSIDE, self.outside_cost(OUTSIDE)


@lru_cache(maxsize=512)
def _pricing(key: str) -> rc.ContractSolver:
    d = json.loads(key)
    return rc.ContractSolver(BidderWorld(ra.world_from_dict(d["world"]), rc.Extras(**d["extras"]), d["playbook"]))


def pricing(world: Mapping[str, Any], extras: Mapping[str, Any], playbook: str) -> rc.ContractSolver:
    """The contracts module's tables for one playbook in this world, over every type of the prior."""
    return _pricing(json.dumps({"world": world, "extras": dict(extras), "playbook": playbook}, sort_keys=True))


@dataclass(frozen=True)
class Bidder:
    id: str
    playbook: str
    type: ra.IntegratorType


def tender_from(payload: Mapping[str, Any]) -> tuple[ra.World, rc.Extras, tuple[Bidder, ...]]:
    w = ra.world_from_dict(payload["world"])
    bidders = tuple(Bidder(BIDDER_IDS[i], b["playbook"], ra.IntegratorType(**b["integrator_type"])) for i, b in enumerate(payload["bidders"]))
    return w, rc.Extras(float(payload["extras"]["team"]), float(payload["extras"]["site_prep"])), bidders


def opening_price(s: rc.ContractSolver, t: int) -> float:
    return round(float(s.th[0][s.index[rc.BASES[s.cw.playbook]], t]), 6)


def consistent_types(s: rc.ContractSolver, price: float) -> list[int]:
    """The types whose opening bid would be this price."""
    return [k for k in range(len(s.types)) if abs(opening_price(s, k) - price) < 1e-6]


def identified(s: rc.ContractSolver, t: int) -> bool:
    """Whether the bid tells a client who knows the policy everything about this firm that matters: every type that
    would bid the same prices every contract, in every round, as this one does, and costs the client the same."""
    return all(np.allclose(s.cc[:, k], s.cc[:, t], rtol=0.0, atol=1e-9)
               and all(np.array_equal(s.th[r][:, k], s.th[r][:, t]) for r in range(s.rounds + 1))
               for k in consistent_types(s, opening_price(s, t)))


# ---------------------------------------------------------------------------
# The client's information states and the exact programme.


def _key(x: float) -> float:
    return math.inf if math.isinf(x) else round(float(x), 6)


@dataclass(frozen=True)
class BState:
    round: int  # the round its next answer would be at, 1..rounds; rounds + 1 once it has answered at its last
    alive: bool
    best: float  # the lowest total cost to the client among its standing offers: price plus the client's own cost


@dataclass(frozen=True)
class TState:
    turn: int  # 1..rounds; rounds + 1 when only accept or walk remain
    bidders: tuple[BState, ...]


@dataclass(frozen=True)
class Move:
    bidder: int
    contract: rc.Contract
    price: float | None  # all in; None asks the price


@dataclass(frozen=True)
class TAction:
    kind: str  # accept | negotiate | walk
    bidder: int | None = None  # accept: whose offer
    contract: rc.Contract | None = None  # accept: the offer's contract
    price: float | None = None  # accept: the offer's all-in price
    moves: tuple[Move, ...] = ()

    def label(self) -> str:
        if self.kind == "walk":
            return "walk to self-management"
        if self.kind == "accept" and self.contract is None:
            return f"accept {BIDDER_IDS[self.bidder]}'s standing offer with the lowest total"
        if self.kind == "accept":
            return f"accept {BIDDER_IDS[self.bidder]}'s [{self.contract.label()}] at {self.price:,.1f} all in"
        return "; ".join(f"{BIDDER_IDS[m.bidder]}: " + ("ask the price of" if m.price is None else "counter")
                         + f" [{m.contract.label()}]" + ("" if m.price is None else f" at {m.price:,.1f} all in") for m in self.moves)


class TenderSolver:
    """Exact dynamic programme over the client's information states once the bids have revealed the types."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.w, self.x, self.bidders = tender_from(payload)
        self.rounds = self.w.rounds
        self.kappa, self.beta = self.w.terms.round_cost, self.w.terms.breakoff
        self.out = self_manage_cost(self.w, self.x.team)
        self.pricing = [pricing(payload["world"], payload["extras"], b.playbook) for b in self.bidders]
        self.t = [s.type_index(b.type) for s, b in zip(self.pricing, self.bidders)]
        self.th = [[s.th[r][:, t] for r in range(self.rounds + 1)] for s, t in zip(self.pricing, self.t)]
        self.cc = [s.cc[:, t] for s, t in zip(self.pricing, self.t)]
        self.total = [[s.total[r][:, t] for r in range(self.rounds + 1)] for s, t in zip(self.pricing, self.t)]
        self.cheapest = [[int(np.argmin(np.round(tot[r], 6))) for r in range(self.rounds + 1)] for tot in self.total]
        self.base = [s.index[rc.BASES[b.playbook]] for s, b in zip(self.pricing, self.bidders)]
        self._memo: dict[TState, float] = {}

    # the pieces

    def menu(self, j: int) -> tuple[rc.Contract, ...]:
        return self.pricing[j].menu

    def index(self, j: int, c: rc.Contract) -> int | None:
        return self.pricing[j].index.get(c.normal())

    def bid(self, j: int) -> float:
        return round(float(self.th[j][0][self.base[j]]), 6)

    def start(self) -> TState:
        return TState(1, tuple(BState(1, True, _key(self.bid(j) + self.cc[j][self.base[j]])) for j in range(len(self.bidders))))

    def floor_best(self, j: int) -> tuple[rc.Contract, float]:
        """Bidder j's contract cheapest for the client at its last-round price, and that cost."""
        ci = self.cheapest[j][self.rounds]
        return self.menu(j)[ci], float(self.total[j][self.rounds][ci])

    def best_attainable(self) -> tuple[str, float]:
        """The lowest cost any bidder's floor or walking gives: the best-bidder diagnostic's target."""
        best = min(((BIDDER_IDS[j], self.floor_best(j)[1]) for j in range(len(self.bidders))), key=lambda z: (round(z[1], 6), z[0]))
        return best if best[1] < self.out else (OUTSIDE, self.out)

    def effect(self, j: int, b: BState, contract: rc.Contract, price: float | None) -> tuple[bool, BState, float | None]:
        """(refused, the bidder's state after it if it does not break off, the price it states or confirms)."""
        ci = self.index(j, contract)
        if ci is None:
            return True, BState(b.round + 1, True, b.best), None
        thr = round(float(self.th[j][b.round][ci]), 6)  # the price as the bidder states it, so states match the episode's to the last digit
        if price is not None and price >= thr - 1e-6:
            return False, replace(b, best=min(b.best, _key(price + self.cc[j][ci]))), price
        return True, BState(b.round + 1, True, min(b.best, _key(thr + self.cc[j][ci]))), thr

    def open(self, s: TState, j: int) -> bool:
        b = s.bidders[j]
        return b.alive and b.round <= self.rounds and s.turn <= self.rounds

    # values

    def q_moves(self, s: TState, moves: Sequence[Move]) -> float:
        states, refused = list(s.bidders), []
        for m in moves:
            ref, states[m.bidder], _ = self.effect(m.bidder, s.bidders[m.bidder], m.contract, m.price)
            if ref:
                refused.append(m.bidder)
        parts = [self.kappa * len(refused)]
        for gone in itertools.product((False, True), repeat=len(refused)):
            p, after = 1.0, list(states)
            for j, g in zip(refused, gone):
                p *= self.beta if g else 1.0 - self.beta
                if g:
                    after[j] = BState(after[j].round, False, math.inf)
            if p > 0.0:
                parts.append(p * self.value(TState(s.turn + 1, tuple(after))))
        return math.fsum(parts)

    def q(self, s: TState, a: TAction) -> float:
        if a.kind == "walk":
            return self.out
        if a.kind == "accept":
            return a.price + float(self.cc[a.bidder][self.index(a.bidder, a.contract)])
        if s.turn > self.rounds or not a.moves:
            raise ValueError("no moves after the last turn, and a turn of moves needs at least one")
        return self.q_moves(s, a.moves)

    def plans(self, s: TState) -> list[tuple[Move, ...]]:
        """Every set of moves the reference weighs: for each bidder still open, nothing, a counter of the contract cheapest
        for the client at its threshold this round, or a request for that contract's price."""
        options = []
        for j, b in enumerate(s.bidders):
            opts: list[Move | None] = [None]
            if self.open(s, j):
                c = self.menu(j)[self.cheapest[j][b.round]]
                opts += [Move(j, c, round(float(self.th[j][b.round][self.cheapest[j][b.round]]), 6)), Move(j, c, None)]
            options.append(opts)
        return [tuple(m for m in combo if m is not None) for combo in itertools.product(*options) if any(m is not None for m in combo)]

    def value(self, s: TState) -> float:
        if s in self._memo:
            return self._memo[s]
        v = min([self.out, *(b.best for b in s.bidders if b.alive)])
        if s.turn <= self.rounds:
            v = min([v, *(self.q_moves(s, p) for p in self.plans(s))])
        self._memo[s] = v
        return v

    def candidates(self, s: TState) -> list[TAction]:
        acts = [TAction("walk")]
        for j, b in enumerate(s.bidders):
            if b.alive and not math.isinf(b.best):
                acts.append(self.best_offer(s, j))
        return acts + [TAction("negotiate", moves=p) for p in self.plans(s)]

    def best_offer(self, s: TState, j: int) -> TAction:
        """An accept of bidder j's standing offer with the lowest total; the offer is found by its cost, and the
        environment names it (a state keeps only the lowest total)."""
        return TAction("accept", j, None, None)

    def best(self, s: TState) -> TAction:
        scored = []
        for i, a in enumerate(self.candidates(s)):
            v = self.out if a.kind == "walk" else s.bidders[a.bidder].best if a.kind == "accept" else self.q_moves(s, a.moves)
            scored.append((round(v, 6), i, a))
        return min(scored, key=lambda z: (z[0], z[1]))[2]

    def regret(self, s: TState, a: TAction) -> float:
        return max(0.0, self.q(s, a) - self.value(s))


    def only(self, j: int) -> TState:
        """The opening with every bidder but j gone: what negotiating with j alone is worth."""
        s = self.start()
        return TState(s.turn, tuple(b if k == j else BState(b.round, False, math.inf) for k, b in enumerate(s.bidders)))


@lru_cache(maxsize=64)
def _solver_for(key: str) -> TenderSolver:
    return TenderSolver(json.loads(key))


def solver_for(payload: Mapping[str, Any]) -> TenderSolver:
    return _solver_for(json.dumps({k: payload[k] for k in ("world", "extras", "bidders")}, sort_keys=True))


# ---------------------------------------------------------------------------
# Lower controls. They see what the client sees and do not know the policy.

RULES = ("accept_the_lowest_bid", "haggle_the_lowest_bid", "every_protection_everywhere", "self_manage")


def lowest_bid(solver: TenderSolver) -> int:
    return min(range(len(solver.bidders)), key=lambda j: (solver.bid(j), j))


def rule_moves(name: str, solver: TenderSolver, turn: int, final: bool, offers: Sequence[Mapping[str, Any]], open_bidders: Sequence[int]) -> dict[str, Any]:
    """A rule's reply in the action schema's shape, with prices all in; ``offers`` are the standing offers
    ({id, bidder index, contract, price all in}) and ``open_bidders`` those it may still negotiate with."""
    low = lowest_bid(solver)
    def cheapest_offer(pool: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {"action": "accept", "offer": min(pool, key=lambda o: (o["price"], o["id"]))["id"], "moves": None}
    if name == "self_manage" or not offers:
        return {"action": "walk", "offer": None, "moves": None}
    if name == "accept_the_lowest_bid":
        return cheapest_offer([o for o in offers if o["bidder"] == low] or offers)
    if name == "haggle_the_lowest_bid":
        mine = [o for o in offers if o["bidder"] == low and rc.Contract(**o["contract"]) == rc.BASES[solver.bidders[low].playbook]]
        if final or not mine or low not in open_bidders:
            return cheapest_offer([o for o in offers if o["bidder"] == low] or offers)
        hw = solver.w.terms.hardware
        return {"action": "negotiate", "offer": None,
                "moves": [{"bidder": low, "contract": mine[0]["contract"], "price": round(hw + 0.5 * (mine[0]["price"] - hw), 3)}]}
    if name == "every_protection_everywhere":
        if turn == 1 and not final and open_bidders:
            return {"action": "negotiate", "offer": None,
                    "moves": [{"bidder": j, "contract": rc.most_protective(solver.bidders[j].playbook).as_dict(), "price": None} for j in open_bidders]}
        prot = [o for o in offers if rc.Contract(**o["contract"]) == rc.most_protective(solver.bidders[o["bidder"]].playbook)]
        return cheapest_offer(prot or offers)
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Worlds. A world type fixes the client's risk charge and the ranges it draws from; it
# labels coverage and is not a reported split. A world is admitted only when every bid
# reveals its firm's type, the best deal and walking are clearly apart, and taking a bid
# as it stands, the lowest or the best, loses to negotiating.

WORLD_TYPES: dict[str, dict[str, Any]] = {
    "risk_tolerant": {"client_charge": 0.15, "ranges": dict(team=(1300.0, 1700.0))},
    "moderate": {"client_charge": 0.75, "ranges": {}},
    "risk_averse": {"client_charge": 1.55, "ranges": dict(incident=(0.05, 0.08), incident_loss=(3000.0, 4000.0))},
    "fragile_bidders": {"client_charge": 0.75, "ranges": dict(breakoff=(0.2, 0.35))},
}
SITUATIONS = {
    "lowest_bidder_is_best": "the firm with the lowest bid is the one to negotiate with; the terms and the price are what is left to win",
    "another_bidder_is_best": "the lowest bid is not the best firm: negotiating only with it costs at least CHOICE_MARGIN more than the best play",
    "self_manage": "no firm's best contract beats managing the deployment yourself; walk",
}
WALK_MARGIN = 150.0  # the best deal and walking are at least this far apart, either way
CHOICE_MARGIN = 75.0  # taking a bid as it stands, or negotiating only with the lowest bidder where another is best, costs at least this much more
_RANGES = {k: v for k, v in rc._RANGES.items() if k != "turnkey_offset"}


def draw_tender(rng: random.Random, world_type: str) -> dict[str, Any]:
    """The payload's world, extras and bidders; the break-off draws are added by the pack."""
    spec = {**_RANGES, **WORLD_TYPES[world_type]["ranges"]}
    u = {k: rng.uniform(*v) for k, v in spec.items()}
    r2 = ra._round
    risks = ra.Risks(
        defect_without_test=r2(u["defect_without_test"], 0.01), defect_with_test=r2(u["defect_with_test"], 0.01),
        defect_fix=r2(u["defect_fix"], 10), defect_weeks=r2(u["defect_weeks"], 1), unready=r2(u["unready"], 0.01),
        standby=r2(u["standby"], 10), unready_weeks=r2(u["unready_weeks"], 1), incident=r2(u["incident"], 0.005),
        incident_loss=r2(u["incident_loss"], 100),
    )
    # the rival turnkey offer of the one-integrator cases is a bidder here; the field is kept at zero and never shown
    client = ra.Client(delay_per_week=r2(u["delay_per_week"], 5), risk_charge=WORLD_TYPES[world_type]["client_charge"],
                       capital_rate=r2(u["capital_rate"], 0.005), insolvency=r2(u["insolvency"], 0.001), turnkey_all_in=0.0)
    w = ra.World(risks, client, ra.Terms(**ra.FIXED_TERMS, breakoff=r2(u["breakoff"], 0.01)))
    composition = list(COMPOSITIONS[rng.randrange(len(COMPOSITIONS))])
    rng.shuffle(composition)
    types = [t for t, _ in w.prior]
    weights = [p for _, p in w.prior]
    bidders = []
    for playbook in composition:
        it = rng.choices(types, weights=weights)[0]
        bidders.append({"playbook": playbook, "integrator_type": {"test_cost": it.test_cost, "risk_charge": it.risk_charge}})
    return {"world": ra.world_to_dict(w), "extras": {"team": r2(u["team"], 10), "site_prep": r2(u["site_prep"], 5)}, "bidders": bidders}


def situation(payload: Mapping[str, Any]) -> str | None:
    """The situation a world is admitted under, or None when it is not admitted."""
    w, x, bidders = tender_from(payload)
    for b in bidders:
        s = pricing(payload["world"], payload["extras"], b.playbook)
        if not identified(s, s.type_index(b.type)):
            return None
    solver = solver_for(payload)
    start = solver.start()
    v = solver.value(start)
    deal = min(solver.floor_best(j)[1] for j in range(len(bidders)))
    if deal > solver.out + WALK_MARGIN:
        return "self_manage" if solver.best(start).kind == "walk" else None
    if deal > solver.out - WALK_MARGIN:
        return None
    opening = [b.best for b in start.bidders]
    low = lowest_bid(solver)
    if opening[low] - v < CHOICE_MARGIN or min(opening) - v < CHOICE_MARGIN:
        return None
    alone = solver.value(solver.only(low)) - v
    if alone < 0.5:
        return "lowest_bidder_is_best"
    if alone >= CHOICE_MARGIN:
        return "another_bidder_is_best"
    return None


def build_pack(quotas: Mapping[str, Mapping[str, int]], base_seed: int, max_draws: int = 20000) -> list[dict[str, Any]]:
    """Worlds per world type and situation, in a fixed order; each world type draws from its own seed range."""
    rows = []
    for wi, (world_type, want) in enumerate(quotas.items()):
        have = {k: 0 for k in want}
        seed, stop = base_seed + 100000 * wi, base_seed + 100000 * wi + max_draws
        while any(have[k] < want[k] for k in want) and seed < stop:
            payload = draw_tender(random.Random(seed), world_type)
            seed += 1
            sit = situation(payload)
            if sit is None or sit not in want or have[sit] >= want[sit]:
                continue
            have[sit] += 1
            rows.append({"slug": f"{world_type}__{sit}__{seed - 1}", "world_type": world_type, "situation": sit, "seed": seed - 1,
                         "lesson": SITUATIONS[sit], **payload})
        if any(have[k] < want[k] for k in want):
            raise RuntimeError(f"{world_type}: only {have} of {dict(want)} within {max_draws} draws")
    return rows


# ---------------------------------------------------------------------------
# What the client is told: the world, the terms, each firm's playbook and bid. Not the policy.

_PLAYBOOK_TEXT = {
    "managed": ("managed delivery: it procures the hardware at cost ({hw}) and manages the delivery for a fee. Its prices are fees; you pay the "
                "hardware on top."),
    "turnkey": "turnkey delivery: one all-in price including the hardware ({hw}). Its prices are all in.",
}


def show(playbook: str, w: ra.World, price_all_in: float) -> float:
    """A price in the playbook's own terms: the fee for managed delivery, else all in."""
    return round(price_all_in - w.terms.hardware, 3) if rc.fee_based(playbook) else round(price_all_in, 3)


def all_in(playbook: str, w: ra.World, shown: float) -> float:
    return shown + w.terms.hardware if rc.fee_based(playbook) else shown


def brief(payload: Mapping[str, Any]) -> str:
    """The client's brief, with every firm's bid."""
    w, x, bidders = tender_from(payload)
    solver = solver_for(payload)
    c, t = w.client, w.terms
    tests = sorted({i.test_cost for i, _ in w.prior})
    charges = sorted({i.risk_charge for i, _ in w.prior})
    lines = [
        f"You are the client. {len(bidders)} integrators are bidding to deliver a GPU cluster into your facility. Money is in $ thousands.",
        "",
        *ra._risk_lines(w, "client"),
        f"- Preparing your site costs an integrator {ra._k(x.site_prep)}; after it the chance your facility is late falls to "
        f"{ra._pct(round(w.risks.unready * rc.SITE_PREP_EFFECT, 6))}. Only an integrator that pays standby has a reason to do it.",
        "",
        "Contract terms:",
        *[f"- {rc._TERM_TEXT[k].format(weeks=t.deposit_weeks, fee=ra._k(rc.ESCROW_FEE), crew=ra._k(rc.BURN_IN_CREW))}" for k in rc.TERMS],
        "",
        "Your position:",
        f"- Each $1 of expected loss you carry costs you ${1 + c.risk_charge:.2f} (covenants and insurance).",
        f"- Your capital costs {ra._pct(c.capital_rate)} a year. There is a {ra._pct(c.insolvency)} chance the integrator you sign with fails before "
        "delivery; a deposit not in escrow is then lost.",
        f"- Your walk-away: manage the deployment yourself. Your own team would cost {ra._k(x.team)} besides the hardware; you would carry "
        "every risk yourself, pay every fix and every week of standby, and nobody would pre-stage the cluster or prepare the site.",
        "",
        f"The bidders are {len(bidders)} separate firms. For each, every $1 of expected payout it carries costs it $1 plus its own risk charge, "
        f"which is {' or '.join(f'{v:g}' for v in charges)}; pre-staging costs it {' or '.join(ra._k(v) for v in tests)} (every combination equally "
        "likely, drawn separately for each firm; not disclosed). Each pre-stages, and prepares your site, exactly when the contract makes that "
        "cheaper for it than not.",
    ]
    for j, b in enumerate(bidders):
        base, neg = rc.BASES[b.playbook], rc.NEGOTIABLE[b.playbook]
        fixed = [k for k in rc.TERMS if k not in neg]
        unit = "fee" if rc.fee_based(b.playbook) else "all-in price"
        lines += [
            "",
            f"{b.id}: {_PLAYBOOK_TEXT[b.playbook].format(hw=ra._k(t.hardware))}",
            f"- Its standard contract: {base.label()}.",
            "- Negotiable: " + "; ".join(f"{k} ({' | '.join(rc._level(v) for v in levels)})" for k, levels in neg.items()) + ". "
            f"Every combination of these is on its menu. Fixed: {', '.join(f'{k} {rc._level(getattr(base, k))}' for k in fixed) or 'nothing'}.",
            f"- Its bid ({unit}) for its standard contract: {ra._k(show(b.playbook, w, solver.bid(j)))} (offer {b.id}-O1).",
        ]
    lines += [
        "",
        f"You have {w.rounds} turns. In each you may accept any standing offer at its price, walk away to managing it yourself, or negotiate: "
        "send moves to any of the bidders at once, at most one to each: a counter (a contract on that firm's menu and a price in its own terms) "
        "or a request for its price for a contract. A firm that will sign at your figure confirms it, and your figure becomes a standing offer you "
        "can accept later. Otherwise it answers with its own price for that contract now, which becomes a standing offer. A contract off its menu "
        "is declined without a price. After the last turn you may only accept or walk.",
        f"After each counter or request a firm does not sign, it breaks off {ra._pct(t.breakoff)} of the time (its offers are withdrawn), and each "
        f"costs you {ra._k(t.round_cost)}.",
        "Your objective: the lowest expected total cost to you: what you pay, plus every expected loss you carry at your risk charge, plus deposit "
        "financing, the escrow fee and a burn-in week, plus the cost of each counter or request not signed; walking away costs you managing it "
        "yourself.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The episode's grade.


def action_of(d: Mapping[str, Any]) -> TAction:
    """A recorded decision as the solver's action: prices all in, bidders by index."""
    if d["kind"] == "walk":
        return TAction("walk")
    if d["kind"] == "accept":
        return TAction("accept", d["bidder"], rc.Contract(**d["contract"]), d["price"])
    return TAction("negotiate", moves=tuple(Move(m["bidder"], rc.Contract(**m["contract"]).normal(), m["price"]) for m in d["moves"]))


def step_state(solver: TenderSolver, s: TState, a: TAction, draws: Sequence[Sequence[float]]) -> tuple[TState, list[dict[str, Any]]]:
    """The state after a turn of moves, with each refused bidder's break-off decided by its stored draw for the round it
    answered at; and each move's outcome."""
    after, results = list(s.bidders), []
    for m in a.moves:
        b = s.bidders[m.bidder]
        refused, nb, stated = solver.effect(m.bidder, b, m.contract, m.price)
        gone = refused and draws[m.bidder][b.round - 1] < solver.beta
        after[m.bidder] = BState(nb.round, False, math.inf) if gone else nb
        results.append({"bidder": m.bidder, "refused": refused, "stated": stated, "broke_off": gone})
    return TState(s.turn + 1, tuple(after)), results


def grade(payload: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]], signed: Mapping[str, Any] | None, termination: str,
          refused: int) -> dict[str, Any]:
    """Decision regret against the reference, and what the client ended with."""
    solver = solver_for(payload)
    s = solver.start()
    per = []
    for d in decisions:
        a = action_of(d)
        per.append({"turn": s.turn, "action": d["kind"], "moves": len(a.moves), "label": a.label(), "regret": round(solver.regret(s, a), 6)})
        if a.kind != "negotiate":
            break
        s, _ = step_state(solver, s, a, payload["breakoff_draws"])
    target_name, target = solver.best_attainable()
    rounds_cost = refused * solver.kappa
    floors = [solver.floor_best(j)[1] for j in range(len(solver.bidders))]
    best_bidders = [BIDDER_IDS[j] for j, f in enumerate(floors) if f < min(floors) + 0.5]
    deal = min(floors) < solver.out
    split = {"bidder": 0.0, "contract": 0.0, "price": 0.0, "walk": 0.0, "refused_counters": rounds_cost}
    if signed is not None:
        j = signed["bidder"]
        c = rc.Contract(**signed["contract"])
        ci = solver.index(j, c)
        realised = signed["price"] + float(solver.cc[j][ci]) + rounds_cost
        last = float(solver.th[j][solver.rounds][ci])
        f_j = floors[j]
        split.update(bidder=f_j - target, contract=float(solver.total[j][solver.rounds][ci]) - f_j, price=signed["price"] - last)
        ties = [solver.menu(j)[i] for i in range(len(solver.menu(j))) if solver.total[j][solver.rounds][i] < f_j + 0.5]
        nearest = max(ties, key=lambda b: (sum(getattr(c, k) == getattr(b, k) for k in rc.TERMS), b == solver.floor_best(j)[0]))
        over_floor = signed["price"] - last
    else:
        j, c, nearest, over_floor = None, None, None, None
        realised = solver.out + rounds_cost
        split["walk"] = solver.out - target
    return {
        "valid": termination != "invalid_action",
        "termination": termination,
        "decision_regret": round(math.fsum(p["regret"] for p in per), 6),
        "decisions": per,
        "reference_expected_cost": round(solver.value(solver.start()), 3),
        "bidders": [{"id": BIDDER_IDS[k], "playbook": b.playbook, "bid": show(b.playbook, solver.w, solver.bid(k)),
                     "best_contract": solver.floor_best(k)[0].as_dict(), "best_contract_cost": round(floors[k], 3)} for k, b in enumerate(solver.bidders)],
        "best_bidders": best_bidders,
        "best_is_deal": deal,
        "signed_bidder": None if j is None else BIDDER_IDS[j],
        "signed_playbook": None if j is None else solver.bidders[j].playbook,
        "signed_best_bidder": j is not None and deal and BIDDER_IDS[j] in best_bidders,
        "signed_contract": None if c is None else c.as_dict(),
        "signed_best_contract": c is not None and deal and BIDDER_IDS[j] in best_bidders and split["contract"] < 0.5,
        "terms_off_best": None if c is None else [k for k in rc.TERMS if getattr(c, k) != getattr(nearest, k)],
        "price_over_floor": None if over_floor is None else round(over_floor, 3),
        "realised_cost": round(realised, 3),
        "best_attainable": target_name,
        "cost_over_best_attainable": round(realised - target, 3),
        "split": {k: round(v, 3) for k, v in split.items()},
        "refused_counters": refused,
    }


__all__ = ["BIDDER_IDS", "BState", "Bidder", "BidderWorld", "CHOICE_MARGIN", "COMPOSITIONS", "Move", "OUTSIDE", "PLAYBOOKS", "RULES", "SITUATIONS",
           "TAction", "TState", "TenderSolver", "WALK_MARGIN", "WORLD_TYPES", "action_of", "all_in", "brief", "build_pack", "consistent_types",
           "draw_tender", "grade", "identified", "lowest_bid", "opening_price", "pricing", "rule_moves", "show", "situation", "solver_for",
           "step_state", "tender_from"]
