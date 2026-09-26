"""Integrator and client both played by models: the two-sided risk-allocation negotiation.

The one-sided case (:mod:`.risk_allocation`) seats one model against a scripted
counterpart that prices by a declared rule, which is what makes each move's
regret exact. With a model on both sides there is no declared rule to best-respond
to, so this module grades only what is exact without one: the outcome, against
both parties' true private costs.

Same world, same economics, same private information: the client knows its own
risk charge and the prior over the integrator's type; the integrator knows its
own type and the prior over the client's charge. Moves alternate, the integrator
first, up to ``2 * (rounds + 1)`` moves (six in every generated world), which is
the one-sided game's shape: the integrator opens, each side answers, and the
client's last move can only accept or walk. A move is one of

- propose a full package with a price: a standing offer the other side may accept;
- propose a package with price null: ask the other side to price it;
- accept the other side's standing offer;
- walk away: both take their outside options.

A proposal that is not accepted costs its proposer the world's round cost, and
after it the negotiation breaks off with the world's break-off probability, decided
by a draw stored in the case, so every pairing meets the same luck in the same world.

Grading (:func:`grade_two_sided`), in $ thousands, full information:

- ``joint_value_lost``: the surplus the best outcome for the two true types makes
  available (the efficient package, or no deal when no package beats both outside
  options) less the surplus realised, round costs included. Zero is the best any
  pair could do; it splits exactly into allocation, no-deal and delay losses.
- each side's surplus over its outside option, and whether a signed deal left a side
  below it (an individual-rationality violation).

No per-move regret is computed: it would need a model of the other model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from . import risk_allocation as ra

SEATS = ("integrator", "client")  # the order of play: the integrator opens
FIRST = "integrator"


def other(seat: str) -> str:
    return "client" if seat == "integrator" else "integrator"


def max_moves(w: ra.World) -> int:
    return 2 * (w.rounds + 1)


def premium_index(seat: str, own_move: int, w: ra.World) -> int:
    """Which ask premium a scripted seat applies on its own k-th move: the integrator
    opens at the opening premium, the client's first answer uses round 1's."""
    return min(own_move - 1 if seat == "integrator" else own_move, w.rounds)


def initial_state(w: ra.World) -> dict[str, Any]:
    return {
        "move": 1,
        "moves": max_moves(w),
        "to_move": FIRST,
        "standing": None,  # the other side's priced proposal the mover may accept
        "request": None,  # a package the other side asked the mover to price
        "history": [],
        "round_costs": {"client": 0.0, "integrator": 0.0},
        "finished": False,
        "termination": None,
        "signed": None,
        "invalid": None,
        "invalid_by": None,
        "walked_by": None,
    }


def is_final(state: Mapping[str, Any]) -> bool:
    return state["move"] >= state["moves"]


def allowed(state: Mapping[str, Any]) -> list[str]:
    acts = [] if is_final(state) else ["propose"]
    if state["standing"] is not None:
        acts.append("accept")
    return acts + ["walk"]


def own_moves(state: Mapping[str, Any], seat: str) -> int:
    """How many moves this seat has made."""
    return sum(1 for h in state["history"] if h["by"] == seat)


# ---------------------------------------------------------------------------
# Scripted players, for controls and dry runs. They act on the state, with the
# private information the seat they play would have (the rule player also knows
# whether the integrator would pre-stage, as the one-sided scripted client does).


def rule_move(state: Mapping[str, Any], w: ra.World, it: ra.IntegratorType) -> dict[str, Any]:
    """The one-sided counterparts' declared pricing rules, playing each other: sign at the
    rule's price or better, otherwise quote it on the same package. Neither changes the package."""
    seat = state["to_move"]
    k = own_moves(state, seat) + 1
    idx = premium_index(seat, k, w)
    charge = w.client.risk_charge

    def threshold(pkg: ra.Package) -> float:
        return ra.ask_price(pkg, w, it, idx) if seat == "integrator" else ra.client_bid(pkg, w, it, charge, idx)

    st, req = state["standing"], state["request"]
    if st is not None:
        pkg = ra.Package(**st["package"])
        thr = threshold(pkg)
        good = st["price"] >= thr - 1e-6 if seat == "integrator" else st["price"] <= thr + 1e-6
        if good:
            return {"action": "accept", "package": None, "price": None, "reason": "rule"}
        if is_final(state):
            return {"action": "walk", "package": None, "price": None, "reason": "rule"}
        return {"action": "propose", "package": pkg.as_dict(), "price": round(thr, 3), "reason": "rule"}
    if is_final(state):
        return {"action": "walk", "package": None, "price": None, "reason": "rule"}
    pkg = ra.Package(**req["package"]) if req is not None else ra.OPENING
    return {"action": "propose", "package": pkg.as_dict(), "price": round(threshold(pkg), 3), "reason": "rule"}


def oracle_move(state: Mapping[str, Any], w: ra.World, it: ra.IntegratorType) -> dict[str, Any]:
    """Full information on both sides: the integrator proposes the efficient package at the
    price that splits the surplus equally, or walks when no deal beats both outside options;
    the client accepts. Its joint value lost is zero by construction, which checks the grader."""
    if state["to_move"] == "integrator":
        eff = ra.efficient_package(w, it)
        available = w.client.turnkey_all_in - w.terms.floor_margin - ra.joint_cost(eff, w, it)
        if available <= 1e-9:
            return {"action": "walk", "package": None, "price": None, "reason": "oracle"}
        price = ra.integrator_cost(eff, w, it) + w.terms.floor_margin + available / 2.0
        return {"action": "propose", "package": eff.as_dict(), "price": round(price, 6), "reason": "oracle"}
    return {"action": "accept" if state["standing"] is not None else "walk", "package": None, "price": None, "reason": "oracle"}


POLICIES = {"rule": rule_move, "oracle": oracle_move}


# ---------------------------------------------------------------------------
# The transition. `act` is a parsed, legal action of the seat to move.


def apply(state: Mapping[str, Any], act: Mapping[str, Any], w: ra.World, draws: list[float]) -> dict[str, Any]:
    new = {**state, "history": list(state["history"]), "round_costs": dict(state["round_costs"])}
    seat = state["to_move"]
    entry = {"move": state["move"], "by": seat, "action": act["action"], "package": act.get("package"), "price": act.get("price")}
    new["history"].append(entry)
    # the other side's pending proposal (priced or a price request) was not accepted: its proposer pays the round
    pending = state["standing"] or state["request"]
    if pending is not None and act["action"] != "accept":
        new["round_costs"][pending["by"]] += w.terms.round_cost
    if act["action"] == "walk":
        new.update(finished=True, termination="walked", walked_by=seat, standing=None, request=None)
        return new
    if act["action"] == "accept":
        st = state["standing"]
        new.update(finished=True, termination="signed", signed={"package": st["package"], "price": st["price"], "offered_by": st["by"], "move": state["move"]},
                   standing=None, request=None)
        return new
    offer = {"by": seat, "package": act["package"], "move": state["move"]}
    if act["price"] is None:
        new.update(standing=None, request=offer)
    else:
        new.update(standing={**offer, "price": act["price"]}, request=None)
    # a proposal is followed by the break-off risk (the integrator's opening is not: the client has not refused anything yet)
    if state["move"] > 1 and draws[state["move"] - 1] < w.terms.breakoff:
        new["round_costs"][seat] += w.terms.round_cost
        new.update(finished=True, termination="broke_off", standing=None, request=None)
        return new
    new.update(move=state["move"] + 1, to_move=other(seat))
    if new["move"] > new["moves"]:  # cannot happen: the final move may not propose
        new.update(finished=True, termination="out_of_moves")
    return new


# ---------------------------------------------------------------------------
# Grading.


def grade_two_sided(w: ra.World, it: ra.IntegratorType, state: Mapping[str, Any]) -> dict[str, Any]:
    """Every amount in $ thousands, at both parties' true private costs."""
    t, c = w.terms, w.client
    no_deal = c.turnkey_all_in - t.floor_margin
    eff = ra.efficient_package(w, it)
    best_joint = ra.joint_cost(eff, w, it)
    available = max(0.0, no_deal - best_joint)
    rc = state["round_costs"]
    delay = math.fsum(rc.values())
    signed = state["signed"]
    if signed is not None:
        pkg = ra.Package(**signed["package"])
        jc = ra.joint_cost(pkg, w, it)
        client_deal = c.turnkey_all_in - signed["price"] - ra.client_cost(pkg, w, it)
        integrator_deal = signed["price"] - ra.integrator_cost(pkg, w, it) - t.floor_margin
        allocation_loss = jc - min(best_joint, no_deal)
        no_deal_loss = 0.0
    else:
        pkg = None
        client_deal = integrator_deal = 0.0
        allocation_loss = 0.0
        no_deal_loss = available
    client_surplus = client_deal - rc["client"]
    integrator_surplus = integrator_deal - rc["integrator"]
    realized = client_surplus + integrator_surplus
    lost = available - realized
    lost = 0.0 if abs(lost) < 1e-9 else lost  # the oracle's zero, not a float remainder
    check = allocation_loss + no_deal_loss + delay
    if abs(lost - check) > 1e-6:
        raise AssertionError(f"joint value lost {lost} does not split into its parts {check}")
    valid = state["termination"] != "invalid_action"
    proposed = [h for h in state["history"] if h["action"] == "propose"]
    return {
        "valid": valid,
        "termination": state["termination"],
        "invalid": state.get("invalid"),
        "invalid_by": state.get("invalid_by"),
        "walked_by": state.get("walked_by"),
        "moves": len(state["history"]),
        "signed_package": None if pkg is None else pkg.label(),
        "signed_price": None if signed is None else round(signed["price"], 3),
        "offered_by": None if signed is None else signed["offered_by"],
        "efficient_package": eff.label(),
        "available_surplus": round(available, 3),
        "joint_value_lost": round(lost, 6),
        "allocation_loss": round(allocation_loss, 6),
        "no_deal_loss": round(no_deal_loss, 6),
        "delay_loss": round(delay, 6),
        "client_surplus": round(client_surplus, 6),
        "integrator_surplus": round(integrator_surplus, 6),
        "client_ir_violation": bool(signed is not None and client_deal < -1e-6),
        "integrator_ir_violation": bool(signed is not None and integrator_deal < -1e-6),
        "client_share": round(client_surplus / realized, 6) if realized > 1e-9 else None,
        "efficient_contract_signed": bool(pkg is not None and pkg == eff),
        "packages_proposed": len({ra.Package(**h["package"]).label() for h in proposed}),
        "changed_package": bool(pkg is not None and proposed and ra.Package(**proposed[0]["package"]) != pkg),
    }


# ---------------------------------------------------------------------------
# What each seat is told: the one-sided briefs without the counterpart's pricing rule.


def _protocol(w: ra.World, seat: str) -> list[str]:
    t = w.terms
    them = "the client" if seat == "integrator" else "the integrator"
    mine = w.rounds + 1
    last = ("The last move of the negotiation is yours: you may then only accept a standing offer or walk."
            if seat == "client" else "The client has the last move, and may then only accept your standing offer or walk.")
    return [
        f"Moves alternate, the integrator first; you have {mine} moves. On each you may accept {them}'s standing offer (if there is one), "
        f"walk away, or propose a full package and a price, which becomes your standing offer for {them} to accept. "
        f"To ask {them} for its price for a package without committing, propose the package with price null. {last}",
        f"After each proposal that is not accepted the negotiation breaks off {ra._pct(t.breakoff)} of the time, and the proposer loses {ra._k(t.round_cost)}.",
    ]


def brief(w: ra.World, seat: str, own: ra.IntegratorType | None = None) -> str:
    """The seat's brief. The client's does not depend on the integrator's type, the integrator's
    not on the client's risk charge: each sees the other only as the declared prior."""
    r, c, t = w.risks, w.client, w.terms
    if seat == "client":
        tests = sorted({x.test_cost for x, _ in w.prior})
        charges = sorted({x.risk_charge for x, _ in w.prior})
        return "\n".join([
            "You are the client. An integrator will deliver a GPU cluster into your facility. Money is in $ thousands.",
            f"Hardware {ra._k(t.hardware)} at cost; the integrator's own delivery cost {ra._k(t.services)}.",
            "",
            *ra._risk_lines(w, "client"),
            "",
            *ra._term_lines(w, "client"),
            "",
            "Your position:",
            f"- Each $1 of expected loss you carry costs you ${1 + c.risk_charge:.2f} (covenants and insurance).",
            f"- Your capital costs {ra._pct(c.capital_rate)} a year. If you pay the deposit, there is a {ra._pct(c.insolvency)} chance the integrator fails before delivery and it is lost.",
            f"- Outside option: a turnkey contract at {ra._k(c.turnkey_all_in)} all in, every risk priced in.",
            "",
            "The integrator negotiates for itself: it wants the highest expected profit over its outside option, other work that earns it "
            f"{ra._k(t.floor_margin)}. What you know about its costs:",
            f"- Each $1 of expected loss it carries costs it $1 plus its own risk charge, which is {' or '.join(f'{x:g}' for x in charges)} (equally likely; not disclosed).",
            f"- Pre-staging costs it {' or '.join(ra._k(x) for x in tests)} (equally likely; not disclosed).",
            f"- It adds {ra._pct(t.uncontrolled_contingency)} of expected standby if it carries your facility's readiness, which it cannot control.",
            f"- Its capital costs {ra._pct(t.integrator_capital_rate)} a year, so a deposit at signing saves it financing.",
            "",
            *_protocol(w, "client"),
            "Your objective: the lowest expected total cost to you: the price, plus every expected loss you carry at your risk charge, "
            "plus deposit financing and loss, plus the cost of your proposals that are not accepted; walking away costs you the turnkey price.",
        ])
    charges = sorted({x for x, _ in w.client_prior})
    return "\n".join([
        "You are the integrator. You will deliver a GPU cluster into the client's facility. Money is in $ thousands.",
        f"Hardware {ra._k(t.hardware)} at cost; your own delivery cost {ra._k(t.services)}.",
        "",
        *ra._risk_lines(w, "integrator"),
        "",
        *ra._term_lines(w, "integrator"),
        "",
        "Your position:",
        f"- Pre-staging costs you {ra._k(own.test_cost)}.",
        f"- Each $1 of expected loss you carry costs you ${1 + own.risk_charge:.2f} (insurance and balance sheet).",
        f"- If you carry the client's facility readiness, which you cannot control, you add {ra._pct(t.uncontrolled_contingency)} of expected standby.",
        f"- Your capital costs {ra._pct(t.integrator_capital_rate)} a year, so a deposit at signing saves you financing.",
        f"- Outside option: other work that earns you {ra._k(t.floor_margin)}.",
        "",
        "The client negotiates for itself: it wants the lowest expected total cost, against a turnkey offer it holds at "
        f"{ra._k(c.turnkey_all_in)} all in, every risk priced in. What you know about its costs:",
        f"- Each $1 of expected loss it carries costs it $1 plus its own risk charge, which is {' or '.join(f'{x:g}' for x in charges)} (equally likely; not disclosed).",
        f"- Its capital costs {ra._pct(c.capital_rate)} a year. If it pays the deposit, it puts a {ra._pct(c.insolvency)} chance on losing it to your insolvency.",
        "- It knows whether you would pre-stage under each package.",
        "",
        *_protocol(w, "integrator"),
        "Your objective: the highest expected profit: the price, less your expected cost of the package (hardware, delivery, pre-staging if you do it, "
        "every expected loss you carry at your risk charge, the standby contingency, less deposit financing saved), less the cost of your proposals "
        "that are not accepted; walking away earns your outside option.",
    ])


__all__ = [
    "FIRST",
    "POLICIES",
    "SEATS",
    "allowed",
    "apply",
    "brief",
    "grade_two_sided",
    "initial_state",
    "is_final",
    "max_moves",
    "oracle_move",
    "other",
    "rule_move",
]
