"""The integrator posts a playbook and a menu; the client negotiates the item best for itself.

The three offers the case began from, as integrator playbooks over the same
world and economics (:mod:`.risk_allocation`):

- **coordination**: the client buys the hardware from the vendors at cost and pays
  it at signing; the integrator coordinates for a fee and carries nothing;
- **managed**: the integrator procures at cost and manages delivery for a fee,
  warranting compatibility (the fix);
- **turnkey**: one all-in price, the integrator warrants compatibility and delay,
  payment held back until delivery.

Each playbook comes with three negotiable options, clauses the client may add or
drop (:data:`OPTIONS`), and its menu prices every combination: eight items, the
base first.

Which playbook an integrator posts, and how it prices each menu item, is a
declared policy of this module (:func:`playbook_of`, :func:`threshold`) that no
brief states. The client knows the world, the prior over integrator types, and
its own two outside options: a rival turnkey offer, or managing the deployment
itself (its own team, every risk its own, nobody pre-staging).

The client may accept a menu item at its current price, counter one with a price
(the integrator signs if the price clears its price for that item this round, and
otherwise answers with that price, which becomes the item's current price), or
walk to an outside option. After each refused counter the integrator breaks off
with the world's probability and the client loses the round cost.

The reference (:class:`MenuSolver`) is the best play of a client who knows the
policy: it reads the integrator's costs off the menu and best-responds exactly.
Decision regret is graded against it, so it includes what not knowing how this
market prices costs a client; what the model is told is the same for every model.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from . import risk_allocation as ra

Package = ra.Package
BASES: dict[str, Package] = {
    "coordination": Package("none", "client", "excluded", "at_signing"),
    "managed": Package("fix", "client", "excluded", "at_signing"),
    "turnkey": Package("fix_and_delay", "client", "excluded", "on_delivery"),
}
# each option: (name shown to the client, clause, value it sets)
OPTIONS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "coordination": (("standby cover", "readiness", "integrator"), ("incident cover", "consequential", "included"),
                     ("compatibility fix", "warranty", "fix")),
    "managed": (("incident cover", "consequential", "included"), ("holdback until delivery", "deposit", "on_delivery"),
                ("delay damages", "warranty", "fix_and_delay")),
    "turnkey": (("standby cover", "readiness", "integrator"), ("incident cover", "consequential", "included"),
                ("deposit at signing", "deposit", "at_signing")),
}


def _items(playbook: str) -> tuple[Package, ...]:
    """Every combination of the playbook's options, base first, in bit order."""
    out = []
    for mask in range(1 << len(OPTIONS[playbook])):
        pkg = BASES[playbook]
        for bit, (_, clause, value) in enumerate(OPTIONS[playbook]):
            if mask >> bit & 1:
                pkg = replace(pkg, **{clause: value})
        out.append(pkg)
    return tuple(out)


PLAYBOOKS: dict[str, tuple[Package, ...]] = {p: _items(p) for p in BASES}
LABELS = ("A", "B", "C", "D", "E", "F", "G", "H")
OUTSIDE = ("turnkey", "self_manage")

# ---------------------------------------------------------------------------
# The integrator's policy. Declared here; stated in no brief.


def playbook_of(it: ra.IntegratorType) -> str:
    """An integrator that carries risk dearly coordinates; one that carries it and pre-stages
    cheaply sells turnkey; the rest manage delivery."""
    if it.risk_charge >= 1.0:
        return "coordination"
    return "turnkey" if it.test_cost <= 40.0 else "managed"


ADDON_MARKUP = {"incident": 0.6, "standby": 0.5, "deposit": 0.6, "warranty": 0.5}  # of the expected cost the option moves
ADDON_DECAY = (1.0, 0.5, 0.0)  # the markup's share by round: the list, then each answer


def extra(playbook: str, pkg: Package, w: ra.World) -> float:
    """The list markup on an item's options: for each clause that differs from the playbook's base,
    a share of the expected cost it moves (a deposit at signing, which saves the integrator
    financing, is priced so that little of the saving shows at list)."""
    base = BASES[playbook]
    r, t = w.risks, w.terms
    x = 0.0
    if pkg.consequential != base.consequential:
        x += ADDON_MARKUP["incident"] * r.incident * r.incident_loss
    if pkg.readiness != base.readiness:
        x += ADDON_MARKUP["standby"] * r.unready * r.standby
    if pkg.deposit != base.deposit:
        x += ADDON_MARKUP["deposit"] * t.integrator_capital_rate * t.deposit_share * t.hardware * t.deposit_weeks / 52.0
    if pkg.warranty != base.warranty:
        x += ADDON_MARKUP["warranty"] * r.defect_without_test * abs(ra._bear(pkg, w) - ra._bear(base, w))
    return x


def threshold(playbook: str, pkg: Package, w: ra.World, it: ra.IntegratorType, round_: int) -> float:
    """The all-in price at which this integrator signs this item in this round (0 = the list)."""
    return ra.floor_price(pkg, w, it) + w.terms.ask_premium[round_] + ADDON_DECAY[round_] * extra(playbook, pkg, w)


def list_prices(playbook: str, w: ra.World, it: ra.IntegratorType) -> tuple[float, ...]:
    return tuple(round(threshold(playbook, p, w, it, 0), 6) for p in PLAYBOOKS[playbook])


# ---------------------------------------------------------------------------
# The client's side.


def self_manage_cost(w: ra.World, team: float, charge: float | None = None) -> float:
    """Hardware at cost, the client's own team, every risk the client's own and no pre-staging."""
    r, c, t = w.risks, w.client, w.terms
    charge = c.risk_charge if charge is None else charge
    contingent = (r.defect_without_test * (r.defect_fix + r.defect_weeks * c.delay_per_week)
                  + r.unready * (r.standby + r.unready_weeks * c.delay_per_week) + r.incident * r.incident_loss)
    return t.hardware + team + (1.0 + charge) * contingent


@dataclass(frozen=True)
class MenuWorld:
    w: ra.World
    team: float  # the client's own team cost if it self-manages, $k
    playbook: str

    @property
    def items(self) -> tuple[Package, ...]:
        return PLAYBOOKS[self.playbook]

    def outside_cost(self, which: str) -> float:
        return self.w.client.turnkey_all_in if which == "turnkey" else self_manage_cost(self.w, self.team)

    @property
    def best_outside(self) -> tuple[str, float]:
        return min(((o, self.outside_cost(o)) for o in OUTSIDE), key=lambda x: (round(x[1], 6), x[0]))

    def consistent(self, listed: tuple[float, ...]) -> frozenset[ra.IntegratorType]:
        """The types a client who knows the policy cannot rule out after seeing the menu."""
        return frozenset(t for t, _ in self.w.prior if playbook_of(t) == self.playbook
                         and all(abs(threshold(self.playbook, p, self.w, t, 0) - x) < 1e-6 for p, x in zip(self.items, listed)))


@dataclass(frozen=True)
class MenuAction:
    kind: str  # accept | propose | walk
    item: int | None = None  # index into the menu
    price: float | None = None  # all-in, for propose
    outside: str | None = None  # for walk

    def label(self, labels: tuple[str, ...] = LABELS) -> str:
        if self.kind == "accept":
            return f"accept {labels[self.item]}"
        if self.kind == "walk":
            return f"walk to {self.outside}"
        return f"counter {labels[self.item]} at {self.price:,.1f} all in"


@dataclass(frozen=True)
class MenuState:
    round: int  # 1..rounds
    final: bool
    types: frozenset
    standing: tuple[float, ...]  # each item's current all-in price


class MenuSolver:
    """Exact best play for a client who knows the integrator's policy (not its type)."""

    def __init__(self, mw: MenuWorld) -> None:
        self.mw = mw
        self.w = mw.w
        self._weights = dict(self.w.prior)

    def _p(self, types: frozenset) -> dict[Any, float]:
        z = math.fsum(self._weights[t] for t in types)
        return {t: self._weights[t] / z for t in types}

    def client_total(self, k: int, price: float, t: ra.IntegratorType) -> float:
        return price + ra.client_cost(self.mw.items[k], self.w, t)

    def q(self, s: MenuState, a: MenuAction) -> float:
        mw, w = self.mw, self.w
        if a.kind == "walk":
            return mw.outside_cost(a.outside)
        p = self._p(s.types)
        if a.kind == "accept":
            return math.fsum(q * self.client_total(a.item, s.standing[a.item], t) for t, q in p.items())
        if s.final:
            raise ValueError("no counter after the last answer")
        k, price = a.item, a.price
        _, best_out = mw.best_outside
        total = []
        refusals: dict[float, list] = {}
        for t, q in p.items():
            thr = threshold(mw.playbook, mw.items[k], w, t, s.round)
            if price >= thr - 1e-6:
                total.append(q * self.client_total(k, price, t))
            else:
                refusals.setdefault(round(thr, 6), []).append(t)
        beta = w.terms.breakoff
        for answer, ts in refusals.items():
            q = math.fsum(p[t] for t in ts)
            standing = s.standing[:k] + (answer,) + s.standing[k + 1:]
            nxt = MenuState(s.round if s.round == w.rounds else s.round + 1, s.round == w.rounds, frozenset(ts), standing)
            total.append(q * (w.terms.round_cost + beta * best_out + (1.0 - beta) * self.value(nxt)))
        return math.fsum(total)

    def actions(self, s: MenuState) -> list[MenuAction]:
        acts = [MenuAction("accept", k) for k in range(len(self.mw.items))] + [MenuAction("walk", outside=o) for o in OUTSIDE]
        if not s.final:
            for k, pkg in enumerate(self.mw.items):
                prices = sorted({round(threshold(self.mw.playbook, pkg, self.w, t, s.round), 6) for t in s.types})
                acts += [MenuAction("propose", k, x) for x in prices]
                acts.append(MenuAction("propose", k, prices[0] - 1.0))  # a counter every type refuses: buys the next round
        return acts

    @lru_cache(maxsize=None)
    def value(self, s: MenuState) -> float:
        return min(self.q(s, a) for a in self.actions(s))

    def best(self, s: MenuState) -> MenuAction:
        scored = [(round(self.q(s, a), 6), i, a) for i, a in enumerate(self.actions(s))]
        return min(scored)[2]

    def regret(self, s: MenuState, a: MenuAction) -> float:
        return max(0.0, self.q(s, a) - self.value(s))


def start_state(mw: MenuWorld, it: ra.IntegratorType) -> MenuState:
    listed = list_prices(mw.playbook, mw.w, it)
    return MenuState(1, False, mw.consistent(listed), listed)


def best_item(mw: MenuWorld, it: ra.IntegratorType) -> tuple[int, float]:
    """The item cheapest for the client at the integrator's floor (the last round's price), and that cost."""
    last = mw.w.rounds
    costs = [threshold(mw.playbook, p, mw.w, it, last) + ra.client_cost(p, mw.w, it) for p in mw.items]
    k = min(range(len(costs)), key=lambda i: (round(costs[i], 6), i))
    return k, costs[k]


# ---------------------------------------------------------------------------
# Lower controls: rules a client might follow. Each sees only what a model sees.


def rule_action(name: str, mw: MenuWorld, s: MenuState) -> MenuAction:
    if name == "accept_the_first_item":
        return MenuAction("accept", 0)
    if name == "walk_to_turnkey":
        return MenuAction("walk", outside="turnkey")
    if name == "cheapest_all_in_price":  # ignores what each item leaves the client carrying
        return MenuAction("accept", min(range(len(s.standing)), key=lambda i: (s.standing[i], i)))
    if name == "haggle_the_base_item":  # counter the base item at half its markup over the hardware, then take the answer
        if s.final:
            return MenuAction("accept", 0)
        return MenuAction("propose", 0, round(mw.w.terms.hardware + 0.5 * (s.standing[0] - mw.w.terms.hardware), 3))
    raise KeyError(name)


RULES = ("accept_the_first_item", "cheapest_all_in_price", "haggle_the_base_item", "walk_to_turnkey")


# ---------------------------------------------------------------------------
# Worlds. Each cell states the lesson the reference must show for the world to be admitted.

CELLS: dict[str, dict[str, Any]] = {
    "cheapest_is_not_best": {"lesson": "the lowest price on the menu is not the cheapest item for this client once the risks it leaves are counted",
                             "client_charge": 0.75, "ranges": {}, "admit": "not_cheapest_price"},
    "buy_the_cover": {"lesson": "the incident cover is worth its markup to a client this averse to risk; take the item that includes it",
                      "client_charge": 1.55, "ranges": {}, "admit": "cover_best"},
    "haggle_the_list": {"lesson": "the list carries a premium the integrator gives up when countered; counter before signing",
                        "client_charge": 0.75, "ranges": dict(breakoff=(0.03, 0.06)), "admit": "counter_first"},
    "sign_now": {"lesson": "the integrator is likely to break off after a refusal and the deal is worth much more than the outside options; sign now",
                 "client_charge": 0.75, "ranges": dict(breakoff=(0.35, 0.5), turnkey_offset=(900.0, 1300.0), team=(1400.0, 1800.0)), "admit": "sign_first"},
    "take_the_rival_turnkey": {"lesson": "no item on this menu beats the rival turnkey offer; walk to it",
                               "client_charge": 0.75, "ranges": dict(turnkey_offset=(-400.0, -200.0)), "admit": "walk_turnkey"},
    "manage_it_yourself": {"lesson": "a capable own team and a low aversion to risk make self-managing cheapest; walk to it",
                           "client_charge": 0.15, "ranges": dict(team=(150.0, 250.0)), "admit": "walk_self"},
}
_RANGES = {**ra._COMMON, "team": (500.0, 900.0), "turnkey_offset": (150.0, 700.0)}


def draw_menu_world(rng: random.Random, cell: str, playbook: str) -> tuple[MenuWorld, ra.IntegratorType]:
    spec = {**_RANGES, **CELLS[cell]["ranges"]}
    u = {k: rng.uniform(*v) for k, v in spec.items()}
    r2 = ra._round
    risks = ra.Risks(
        defect_without_test=r2(u["defect_without_test"], 0.01), defect_with_test=r2(u["defect_with_test"], 0.01),
        defect_fix=r2(u["defect_fix"], 10), defect_weeks=r2(u["defect_weeks"], 1), unready=r2(u["unready"], 0.01),
        standby=r2(u["standby"], 10), unready_weeks=r2(u["unready_weeks"], 1), incident=r2(u["incident"], 0.005),
        incident_loss=r2(u["incident_loss"], 100),
    )
    terms = ra.Terms(**ra.FIXED_TERMS, breakoff=r2(u["breakoff"], 0.01))
    client = ra.Client(delay_per_week=r2(u["delay_per_week"], 5), risk_charge=CELLS[cell]["client_charge"],
                       capital_rate=r2(u["capital_rate"], 0.005), insolvency=r2(u["insolvency"], 0.001), turnkey_all_in=0.0)
    w = ra.World(risks, client, terms)
    types = [t for t, _ in w.prior if playbook_of(t) == playbook]
    it = types[rng.randrange(len(types))]
    mw = MenuWorld(w, r2(u["team"], 10), playbook)
    _, best = best_item(mw, it)
    w = replace(w, client=replace(client, turnkey_all_in=r2(best + u["turnkey_offset"], 10)))
    return MenuWorld(w, mw.team, playbook), it


def lesson_holds(cell: str, mw: MenuWorld, it: ra.IntegratorType) -> bool:
    s = start_state(mw, it)
    ref = MenuSolver(mw).best(s)
    k, best_cost = best_item(mw, it)
    out, out_cost = mw.best_outside
    rule = CELLS[cell]["admit"]
    deal = best_cost < out_cost - 25.0
    if rule == "not_cheapest_price":
        return deal and k != min(range(len(s.standing)), key=lambda i: (s.standing[i], i)) and ref.kind != "walk"
    if rule == "cover_best":
        return deal and mw.items[k].consequential != mw.items[0].consequential and ref.kind != "walk"
    if rule == "counter_first":
        return deal and ref.kind == "propose" and ref.price < s.standing[ref.item] - 1.0
    if rule == "sign_first":
        return deal and (ref.kind == "accept" or (ref.kind == "propose" and ref.price >= threshold(mw.playbook, mw.items[ref.item], mw.w, it, 1) - 1e-6))
    if rule == "walk_turnkey":
        return ref.kind == "walk" and ref.outside == "turnkey" and out == "turnkey"
    if rule == "walk_self":
        return ref.kind == "walk" and ref.outside == "self_manage" and out == "self_manage"
    raise KeyError(rule)


def build_menu_pack(seeds_per_cell: int, base_seed: int, max_draws: int = 4000) -> list[dict[str, Any]]:
    rows = []
    for ci, cell in enumerate(CELLS):
        for pi, playbook in enumerate(PLAYBOOKS):
            made, seed = 0, base_seed + 10000 * ci + 1000 * pi
            while made < seeds_per_cell and seed < base_seed + 10000 * ci + 1000 * pi + max_draws:
                mw, it = draw_menu_world(random.Random(seed), cell, playbook)
                seed += 1
                if not lesson_holds(cell, mw, it):
                    continue
                rows.append({"slug": f"{cell}__{playbook}__{seed - 1}", "cell": cell, "playbook": playbook, "seed": seed - 1,
                             "lesson": CELLS[cell]["lesson"], "world": ra.world_to_dict(mw.w), "team": mw.team,
                             "integrator_type": {"test_cost": it.test_cost, "risk_charge": it.risk_charge}})
                made += 1
    return rows


def menu_world_from(payload: Mapping[str, Any]) -> tuple[MenuWorld, ra.IntegratorType]:
    w = ra.world_from_dict(payload["world"])
    it = ra.IntegratorType(**payload["integrator_type"])
    return MenuWorld(w, float(payload["team"]), playbook_of(it)), it


# ---------------------------------------------------------------------------
# What the client is told: the world, its options, the posted menu. Not the policy.

_PLAYBOOK_TEXT = {
    "coordination": ("Coordination service. You buy the hardware from the vendors at cost ({hw}, paid at signing); the integrator coordinates "
                     "the delivery for a fee. Prices below are the integrator's fee; you pay the hardware on top."),
    "managed": ("Managed delivery. The integrator procures the hardware at cost ({hw}) and manages the delivery for a fee, warranting "
                "compatibility (it pays the fix). Prices below are the integrator's fee; you pay the hardware on top."),
    "turnkey": ("Turnkey delivery. One all-in price including the hardware; the integrator warrants compatibility and pays delay "
                "damages, and payment is held until delivery. Prices below are all in."),
}


def fee_based(playbook: str) -> bool:
    return playbook != "turnkey"


def shown_price(mw: MenuWorld, all_in: float) -> float:
    """A price in the menu's own terms: the fee for a fee-based playbook, else all in."""
    return round(all_in - mw.w.terms.hardware, 3) if fee_based(mw.playbook) else round(all_in, 3)


def all_in_price(mw: MenuWorld, shown: float) -> float:
    return shown + mw.w.terms.hardware if fee_based(mw.playbook) else shown


def _item_line(playbook: str, label: str, pkg: Package) -> str:
    base = BASES[playbook]
    chosen = [name for name, clause, value in OPTIONS[playbook] if getattr(pkg, clause) == value and getattr(base, clause) != value]
    return (f"{label}: {' + '.join(chosen) if chosen else 'base, no options'} "
            f"(warranty {pkg.warranty}, readiness {pkg.readiness}, consequential {pkg.consequential}, deposit {pkg.deposit})")


_OPTION_TEXT = {
    "standby cover": "the integrator pays standby if your facility is late (readiness integrator)",
    "incident cover": "the integrator carries a post-handover incident's losses (consequential included)",
    "compatibility fix": "the integrator pays the fix of a compatibility defect (warranty fix)",
    "holdback until delivery": "the deposit is paid on delivery instead of at signing (deposit on_delivery)",
    "delay damages": "the integrator also pays delay damages for a defect (warranty fix_and_delay)",
    "deposit at signing": "you pay the deposit at signing instead of on delivery (deposit at_signing)",
}


def menu_brief(mw: MenuWorld, listed: tuple[float, ...]) -> str:
    w = mw.w
    c, t = w.client, w.terms
    tests = sorted({x.test_cost for x, _ in w.prior})
    charges = sorted({x.risk_charge for x, _ in w.prior})
    unit = "fee" if fee_based(mw.playbook) else "all-in price"
    return "\n".join([
        "You are the client. An integrator will deliver a GPU cluster into your facility. Money is in $ thousands.",
        f"Hardware {ra._k(t.hardware)} at cost.",
        "",
        *ra._risk_lines(w, "client"),
        "",
        *ra._term_lines(w, "client"),
        "",
        "Your position:",
        f"- Each $1 of expected loss you carry costs you ${1 + c.risk_charge:.2f} (covenants and insurance).",
        f"- Your capital costs {ra._pct(c.capital_rate)} a year. If you pay a deposit at signing, there is a {ra._pct(c.insolvency)} chance the integrator fails before delivery and it is lost.",
        f"- Outside option 1: a rival turnkey contract at {ra._k(c.turnkey_all_in)} all in, every risk priced in.",
        f"- Outside option 2: manage the deployment yourself. Your own team would cost {ra._k(mw.team)} besides the hardware; "
        "you would carry every risk yourself, pay every fix and every week of standby, and nobody would pre-stage the cluster.",
        "",
        "The integrator: each $1 of expected loss it carries costs it $1 plus its own risk charge, which is "
        f"{' or '.join(f'{x:g}' for x in charges)}; pre-staging costs it {' or '.join(ra._k(x) for x in tests)} "
        "(each combination equally likely; not disclosed). It pre-stages exactly when the contract makes that cheaper for it than not. "
        "It has posted one offer:",
        _PLAYBOOK_TEXT[mw.playbook].format(hw=ra._k(t.hardware)),
        "Options you can add to the base, each changing the price:",
        *[f"- {name}: {_OPTION_TEXT[name]}" for name, _, _ in OPTIONS[mw.playbook]],
        "Its menu prices every combination:",
        *[f"- {_item_line(mw.playbook, LABELS[i], p)}: {unit} {ra._k(shown_price(mw, x))}" for i, (p, x) in enumerate(zip(mw.items, listed))],
        "",
        f"You have {w.rounds} rounds. In each you may accept any item at its current price, walk away to either outside option, or counter "
        f"one item with a {unit}: if the integrator will sign at your figure it signs; otherwise it answers with its own {unit} for that item "
        "this round, which becomes that item's current price. After the last round's answer you may only accept or walk.",
        f"After each counter it refuses, the integrator breaks off {ra._pct(t.breakoff)} of the time (you then take an outside option), "
        f"and each refused counter costs you {ra._k(t.round_cost)}.",
        "Your objective: the lowest expected total cost to you: what you pay, plus every expected loss you carry at your risk charge, "
        "plus deposit financing and loss, plus the cost of refused counters; walking away costs you the outside option you choose.",
    ])


# ---------------------------------------------------------------------------
# The episode, driven by the environment, and its grade.


def answer(mw: MenuWorld, it: ra.IntegratorType, state: Mapping[str, Any], k: int, price: float) -> float:
    return threshold(mw.playbook, mw.items[k], mw.w, it, state["round"])


def grade_menu(mw: MenuWorld, it: ra.IntegratorType, decisions: list[dict[str, Any]], signed: Mapping[str, Any] | None,
               outside: str | None, termination: str, refused: int) -> dict[str, Any]:
    """Decision regret against the informed client, and what the client ended with at the true type."""
    solver = MenuSolver(mw)
    s = start_state(mw, it)
    per = []
    for d in decisions:
        a = MenuAction(d["kind"], d.get("item"), d.get("price"), d.get("outside"))
        per.append({"round": s.round, "final": s.final, "action": a.label(), "regret": round(solver.regret(s, a), 6)})
        if a.kind != "propose" or a.price >= threshold(mw.playbook, mw.items[a.item], mw.w, it, s.round) - 1e-6:
            break
        ans = round(threshold(mw.playbook, mw.items[a.item], mw.w, it, s.round), 6)
        types = frozenset(t for t in s.types if abs(threshold(mw.playbook, mw.items[a.item], mw.w, t, s.round) - ans) < 1e-6)
        standing = s.standing[:a.item] + (ans,) + s.standing[a.item + 1:]
        s = MenuState(s.round if s.round == mw.w.rounds else s.round + 1, s.round == mw.w.rounds, types, standing)
    k_best, best_cost = best_item(mw, it)
    out_name, out_cost = mw.best_outside
    rc = refused * mw.w.terms.round_cost
    if signed is not None:
        k = signed["item"]
        paid = signed["price"]
        realised = paid + ra.client_cost(mw.items[k], mw.w, it) + rc
        over_floor = paid - threshold(mw.playbook, mw.items[k], mw.w, it, mw.w.rounds)
    else:
        k = None
        realised = mw.outside_cost(outside if outside else out_name) + rc
        over_floor = None
    return {
        "valid": termination != "invalid_action",
        "termination": termination,
        "decision_regret": round(math.fsum(p["regret"] for p in per), 6),
        "decisions": per,
        "playbook": mw.playbook,
        "signed_item": None if k is None else LABELS[k],
        "best_item": LABELS[k_best],
        "best_is_deal": best_cost < out_cost,
        "best_outside": out_name,
        "signed_best_item": k is not None and k == k_best and best_cost < out_cost,
        "walked_to": outside,
        "price_over_floor": None if over_floor is None else round(over_floor, 3),
        "realised_cost": round(realised, 3),
        "cost_over_best_attainable": round(realised - min(best_cost, out_cost), 3),
        "refused_counters": refused,
    }


__all__ = [
    "BASES", "CELLS", "LABELS", "MenuAction", "MenuSolver", "MenuState", "MenuWorld", "OPTIONS", "OUTSIDE", "PLAYBOOKS", "RULES",
    "all_in_price", "best_item", "build_menu_pack", "draw_menu_world", "extra", "grade_menu", "lesson_holds", "list_prices",
    "menu_brief", "menu_world_from", "playbook_of", "rule_action", "self_manage_cost", "shown_price", "start_state", "threshold",
]
