"""Negotiating into an agreement: two sides redline one services agreement clause by clause.

The design is ``docs/families/datacenter/agreement_case.md``. This module is its
first slice: both sides are players, and what is graded is the agreement they
reach, at both parties' true private costs. The scripted counterpart and the
per-turn loss against a best informed policy are not built yet.

The agreement has the eight clauses the full-terms case prices exactly
(:mod:`.risk_allocation_contracts`), each with its fixed positions, and an all-in
price. The integrator's standard draft is on the table. Moves alternate, the
integrator first, six in all, so each side has three and the client's last can
only sign or walk. A move is one of

- redline: set any clauses to another position (the rest stand as they are) and
  state the all-in price at which you would sign this version now; it becomes the
  version on the table;
- sign: sign the version the other side put on the table, at its price;
- walk: both take their outside options.

Each redline after the opening costs its author the world's round cost. A side may
attach one short note to a move, which the other side reads.

Every amount is in $ thousands, in expectation over the four events the clauses
cover. ``grade`` is exact and needs no model of either player:

- ``joint_value_lost``: the surplus the best of the 600 agreements makes available
  for the two true types (or no deal, when none beats both outside options) less
  the surplus realised, round costs included. It splits into allocation, no-deal
  and delay.
- each side's surplus over its outside option, and whether it signed below it.
- counts that need no judge: redlines that move only the price, and the joint
  value each side's clause changes added or destroyed.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from typing import Any

from . import risk_allocation as ra
from . import risk_allocation_contracts as rc

SEATS = ("integrator", "client")  # the order of play
FIRST = "integrator"
MOVES = 6
ACTIONS = ("redline", "sign", "walk")
TERMS = rc.TERMS
ALL_AGREEMENTS: tuple[rc.Contract, ...] = tuple(sorted({rc.Contract(*v).normal() for v in itertools.product(*rc.LEVELS.values())}))

#: The fixed wording of each position. A redline picks among these, so the reader
#: that turns the document into terms is exact.
WORDING: dict[str, dict[Any, str]] = {
    "warranty": {
        "none": "The Integrator gives no warranty against compatibility defects. The Client pays for any fix.",
        "fix": "The Integrator shall fix any compatibility defect at its own cost.",
        "fix_and_delay": "The Integrator shall fix any compatibility defect at its own cost and pay delay damages for each week a defect delays go-live.",
    },
    "damages": {
        "50": "Delay damages are $50k per week of defect delay.",
        "100": "Delay damages are $100k per week of defect delay.",
        "200": "Delay damages are $200k per week of defect delay.",
    },
    "liability_cap": {
        "uncapped": "The Integrator's liability under this Agreement is not capped.",
        "1500": "The Integrator's total liability for one delivery shall not exceed $1,500k.",
        "500": "The Integrator's total liability for one delivery shall not exceed $500k.",
    },
    "readiness": {
        "client": "If the Client's facility is not ready on the delivery date, the Client pays the Integrator's standby.",
        "integrator": "The Integrator bears its own standby if the Client's facility is not ready on the delivery date.",
    },
    "consequential": {
        "excluded": "The Integrator is not liable for losses from an incident after handover.",
        "included": "The Integrator is liable for the Client's losses from an incident in the first year after handover.",
    },
    "deposit": {
        "none": "No deposit is payable. The hardware is paid for on delivery.",
        "25%": "The Client pays a deposit of 25% of the hardware price at signing.",
        "50%": "The Client pays a deposit of 50% of the hardware price at signing.",
    },
    "escrow": {
        False: "Any deposit is paid to the Integrator directly.",
        True: "Any deposit is held in escrow until delivery.",
    },
    "burn_in": {
        False: "Handover takes place on delivery, without an acceptance burn-in.",
        True: "Handover follows a one-week acceptance burn-in run by the Integrator's crew.",
    },
}
HEADING = {"warranty": "Warranty", "damages": "Delay damages", "liability_cap": "Limitation of liability", "readiness": "Site readiness",
           "consequential": "Consequential loss", "deposit": "Deposit", "escrow": "Escrow", "burn_in": "Acceptance"}


def other(seat: str) -> str:
    return "client" if seat == "integrator" else "integrator"


def draft(cw: rc.CWorld) -> rc.Contract:
    """The integrator's standard paper for this world."""
    return rc.BASES[cw.playbook]


def initial_state(cw: rc.CWorld) -> dict[str, Any]:
    return {
        "move": 1, "moves": MOVES, "to_move": FIRST,
        "terms": draft(cw).as_dict(),  # the document as it stands
        "standing": None,  # {"by", "price", "move"}: the version on the table and the price its author would sign at
        "tracked": {},  # clause -> {"by", "move", "was"}: the latest change to each clause
        "history": [],
        "round_costs": {"client": 0.0, "integrator": 0.0},
        "finished": False, "termination": None, "signed": None, "invalid": None, "invalid_by": None, "walked_by": None,
    }


def is_final(state: Mapping[str, Any]) -> bool:
    return state["move"] >= state["moves"]


def allowed(state: Mapping[str, Any]) -> list[str]:
    acts = [] if is_final(state) else ["redline"]
    if state["standing"] is not None:
        acts.append("sign")
    return acts + ["walk"]


def apply(state: Mapping[str, Any], act: Mapping[str, Any], cw: rc.CWorld) -> dict[str, Any]:
    """The transition. ``act`` is a parsed, legal action of the seat to move."""
    new = {**state, "terms": dict(state["terms"]), "tracked": dict(state["tracked"]), "history": list(state["history"]),
           "round_costs": dict(state["round_costs"])}
    seat = state["to_move"]
    entry: dict[str, Any] = {"move": state["move"], "by": seat, "action": act["action"], "changes": {}, "price": None, "note": act.get("note")}
    if act["action"] == "walk":
        new["history"].append(entry)
        new.update(finished=True, termination="walked", walked_by=seat)
        return new
    if act["action"] == "sign":
        st = state["standing"]
        entry["price"] = st["price"]
        new["history"].append(entry)
        new.update(finished=True, termination="signed",
                   signed={"terms": dict(state["terms"]), "price": st["price"], "offered_by": st["by"], "move": state["move"]})
        return new
    before = rc.Contract(**state["terms"])
    after = rc.contract_from({k: v for k, v in act["clauses"].items() if v is not None}, before)
    for k in TERMS:
        if getattr(after, k) != getattr(before, k):
            entry["changes"][k] = {"was": getattr(before, k), "now": getattr(after, k)}
            new["tracked"][k] = {"by": seat, "move": state["move"], "was": getattr(before, k)}
    entry["price"] = act["price"]
    new["history"].append(entry)
    if state["move"] > 1:
        new["round_costs"][seat] += cw.w.terms.round_cost
    new.update(terms=after.as_dict(), standing={"by": seat, "price": act["price"], "move": state["move"]},
               move=state["move"] + 1, to_move=other(seat))
    return new


# ---------------------------------------------------------------------------
# What an agreement is worth, to each side and together.


def costs(cw: rc.CWorld, it: ra.IntegratorType, c: rc.Contract) -> tuple[float, float]:
    """(the integrator's expected cost, the client's expected cost apart from the price)."""
    return rc.integrator_cost(c, cw.w, it, cw.x), rc.client_cost(c, cw.w, it, cw.x)


def joint_cost(cw: rc.CWorld, it: ra.IntegratorType, c: rc.Contract) -> float:
    return math.fsum(costs(cw, it, c))


def best_agreement(cw: rc.CWorld, it: ra.IntegratorType) -> rc.Contract:
    d = draft(cw)
    return min(ALL_AGREEMENTS, key=lambda c: (round(joint_cost(cw, it, c), 6), c != d, c))


def grade(cw: rc.CWorld, it: ra.IntegratorType, state: Mapping[str, Any]) -> dict[str, Any]:
    """Every amount in $ thousands, at both parties' true private costs."""
    floor = cw.w.terms.floor_margin
    outside_name, outside = cw.best_outside
    no_deal = outside - floor
    best = best_agreement(cw, it)
    best_joint = joint_cost(cw, it, best)
    start_joint = joint_cost(cw, it, draft(cw))
    available = max(0.0, no_deal - best_joint)
    rcost = state["round_costs"]
    delay = math.fsum(rcost.values())
    signed = state["signed"]
    if signed is not None:
        c = rc.Contract(**signed["terms"])
        ic, cc = costs(cw, it, c)
        client_deal = outside - signed["price"] - cc
        integrator_deal = signed["price"] - ic - floor
        allocation_loss = ic + cc - min(best_joint, no_deal)
        no_deal_loss = 0.0
    else:
        c = None
        client_deal = integrator_deal = allocation_loss = 0.0
        no_deal_loss = available
    client_surplus, integrator_surplus = client_deal - rcost["client"], integrator_deal - rcost["integrator"]
    realized = client_surplus + integrator_surplus
    lost = available - realized
    lost = 0.0 if abs(lost) < 1e-9 else lost
    if abs(lost - (allocation_loss + no_deal_loss + delay)) > 1e-6:
        raise AssertionError("joint value lost does not split into its parts")
    # what each side's clause changes did to the pie, move by move
    edits = {s: {"redlines": 0, "price_only": 0, "clauses_changed": 0, "value_added": 0.0, "value_destroyed": 0.0} for s in SEATS}
    terms = draft(cw)
    for h in state["history"]:
        if h["action"] != "redline":
            continue
        e = edits[h["by"]]
        e["redlines"] += 1
        after = rc.contract_from({k: v["now"] for k, v in h["changes"].items()}, terms)
        if not h["changes"]:
            e["price_only"] += 1
        e["clauses_changed"] += len(h["changes"])
        delta = joint_cost(cw, it, terms) - joint_cost(cw, it, after)
        e["value_added" if delta > 0 else "value_destroyed"] += abs(delta)
        terms = after
    for e in edits.values():
        e["value_added"], e["value_destroyed"] = round(e["value_added"], 3), round(e["value_destroyed"], 3)
    return {
        "valid": state["termination"] != "invalid_action", "termination": state["termination"], "invalid": state.get("invalid"),
        "invalid_by": state.get("invalid_by"), "walked_by": state.get("walked_by"), "moves": len(state["history"]),
        "signed_agreement": None if c is None else c.label(), "signed_price": None if signed is None else round(signed["price"], 3),
        "offered_by": None if signed is None else signed["offered_by"],
        "best_agreement": best.label(), "draft": draft(cw).label(), "outside_option": outside_name,
        "available_surplus": round(available, 3), "left_on_the_table_by_the_draft": round(start_joint - min(best_joint, start_joint), 3),
        "joint_value_lost": round(lost, 6), "allocation_loss": round(allocation_loss, 6), "no_deal_loss": round(no_deal_loss, 6),
        "delay_loss": round(delay, 6), "client_surplus": round(client_surplus, 6), "integrator_surplus": round(integrator_surplus, 6),
        "client_ir_violation": bool(signed is not None and client_deal < -1e-6),
        "integrator_ir_violation": bool(signed is not None and integrator_deal < -1e-6),
        "client_share": round(client_surplus / realized, 6) if realized > 1e-9 else None,
        "best_agreement_signed": bool(c is not None and c == best),
        "clauses_from_best": None if c is None else sum(getattr(c, k) != getattr(best, k) for k in TERMS),
        "edits": edits,
    }


# ---------------------------------------------------------------------------
# Scripted pairs, for controls: they check the grader, they are not opponents.


def oracle_move(state: Mapping[str, Any], cw: rc.CWorld, it: ra.IntegratorType) -> dict[str, Any]:
    """Full information on both sides: the best agreement at an even split, signed at once; or no deal."""
    if state["to_move"] == "integrator":
        best = best_agreement(cw, it)
        ic, cc = costs(cw, it, best)
        available = cw.best_outside[1] - cw.w.terms.floor_margin - ic - cc
        if available <= 1e-9:
            return {"action": "walk", "clauses": None, "price": None, "note": "oracle"}
        now = draft(cw)
        clauses = {k: (getattr(best, k) if getattr(best, k) != getattr(now, k) else None) for k in TERMS}
        return {"action": "redline", "clauses": clauses, "price": round(ic + cw.w.terms.floor_margin + available / 2.0, 6), "note": "oracle"}
    return {"action": "sign" if state["standing"] is not None else "walk", "clauses": None, "price": None, "note": "oracle"}


def draft_move(state: Mapping[str, Any], cw: rc.CWorld, it: ra.IntegratorType) -> dict[str, Any]:
    """The integrator's paper as it stands, at an even split of what it leaves; the client signs it. What nobody negotiating costs."""
    if state["to_move"] == "integrator":
        ic, cc = costs(cw, it, draft(cw))
        available = cw.best_outside[1] - cw.w.terms.floor_margin - ic - cc
        if available <= 1e-9:
            return {"action": "walk", "clauses": None, "price": None, "note": "draft"}
        return {"action": "redline", "clauses": {k: None for k in TERMS}, "price": round(ic + cw.w.terms.floor_margin + available / 2.0, 6), "note": "draft"}
    return {"action": "sign" if state["standing"] is not None else "walk", "clauses": None, "price": None, "note": "draft"}


POLICIES = {"oracle": oracle_move, "draft": draft_move}


# ---------------------------------------------------------------------------
# What each side reads: the document, and its brief.


def document(state: Mapping[str, Any], seat: str) -> list[dict[str, Any]]:
    """The agreement as it stands, clause by clause, with the latest tracked change on each."""
    out = []
    for i, k in enumerate(TERMS, start=1):
        pos = state["terms"][k]
        row: dict[str, Any] = {"clause": k, "number": i, "heading": HEADING[k], "position": pos, "text": WORDING[k][pos],
                               "positions": list(rc.LEVELS[k])}
        t = state["tracked"].get(k)
        if t is not None:
            row["tracked_change"] = {"by": "you" if t["by"] == seat else t["by"], "move": t["move"], "was": t["was"], "struck_text": WORDING[k][t["was"]]}
        out.append(row)
    return out


def _levels(k: str) -> str:
    return " | ".join(str(v).lower() if isinstance(v, bool) else str(v) for v in rc.LEVELS[k])


_MEANING = {
    "warranty": "who pays to fix a compatibility defect, and whether the integrator also pays delay damages for the weeks it costs",
    "damages": "the delay-damages rate in $k per week of defect delay; it has effect only under warranty fix_and_delay",
    "liability_cap": "the most the integrator pays the client in total for one delivery, across the fix, delay damages, standby and an incident's losses, in $k; past it the client bears the rest",
    "readiness": "who pays the integrator's standby if the client's facility is late. An integrator that pays it prepares the client's site whenever that is cheaper for it, which cuts the chance of a late facility",
    "consequential": "who carries the loss from an incident in the first year after handover",
    "deposit": "the share of the hardware price the client pays at signing, {weeks:g} weeks before delivery",
    "escrow": "whether a deposit is held in escrow: safe if the integrator fails, costing the client {fee}, and then the integrator cannot use the money. It has effect only with a deposit",
    "burn_in": "a one-week acceptance burn-in before handover: it halves the chance of an incident, delays go-live one week and costs the integrator a crew of {crew}",
}


def brief(cw: rc.CWorld, seat: str, own: ra.IntegratorType | None = None) -> str:
    """The seat's brief: the facts both know, its own costs, the other side's only as declared odds."""
    w, x = cw.w, cw.x
    r, c, t = w.risks, w.client, w.terms
    tests = sorted({i.test_cost for i in cw.types})
    icharges = sorted({i.risk_charge for i in cw.types})
    ccharges = sorted({v for v, _ in w.client_prior})
    late_after = ra._pct(round(r.unready * rc.SITE_PREP_EFFECT, 6))
    common = [
        *ra._risk_lines(w, seat),
        f"- Preparing the client's site costs the integrator {ra._k(x.site_prep)}; after it the chance the facility is late falls to {late_after}.",
        f"- There is a {ra._pct(c.insolvency)} chance the integrator fails before delivery; a deposit not in escrow is then lost.",
        "",
        "The agreement has eight clauses. Each has fixed positions, and a redline moves a clause from one to another:",
        *[f"- {k} ({_levels(k)}): {_MEANING[k].format(weeks=t.deposit_weeks, fee=ra._k(rc.ESCROW_FEE), crew=ra._k(rc.BURN_IN_CREW))}" for k in TERMS],
        f"The price is all in, including the hardware ({ra._k(t.hardware)} at cost) and the integrator's own delivery cost ({ra._k(t.services)}).",
    ]
    protocol = [
        f"The integrator's standard draft is on the table. Moves alternate, the integrator first, {MOVES} in all: three each. On a move you may "
        "redline (set any clauses to other positions and state the all-in price at which you would sign that version now; it becomes the version "
        "on the table), sign the version the other side put on the table at its price, or walk away. The client has the last move and may then "
        "only sign or walk. You may add one short note, which the other side reads.",
        f"Each redline after the integrator's opening costs its author {ra._k(t.round_cost)}. If nothing is signed, both sides take their outside options.",
        "You negotiate many agreements like this one and are judged on your average result across them, in expectation over what can go wrong, "
        "not on how any one delivery turns out.",
    ]
    if seat == "client":
        return "\n".join([
            "You are the client. An integrator will deliver a GPU cluster into your facility. Money is in $ thousands.",
            "", *common, "",
            "Your position:",
            f"- Each $1 of expected loss you carry costs you ${1 + c.risk_charge:.2f} (covenants and insurance).",
            f"- Your capital costs {ra._pct(c.capital_rate)} a year, which is what a deposit costs you until delivery.",
            f"- Outside option 1: a rival turnkey contract at {ra._k(c.turnkey_all_in)} all in, every risk priced in.",
            f"- Outside option 2: manage the deployment yourself. Your own team would cost {ra._k(x.team)} besides the hardware; you would carry every "
            "risk yourself, pay every fix and every week of standby, and nobody would pre-stage the cluster or prepare the site.",
            "",
            "The integrator negotiates for itself: it wants the highest expected profit over other work that would earn it "
            f"{ra._k(t.floor_margin)}. What you know about its costs:",
            f"- Each $1 of expected payout it carries costs it $1 plus its own risk charge, which is {' or '.join(f'{v:g}' for v in icharges)} (equally likely; not disclosed).",
            f"- Pre-staging costs it {' or '.join(ra._k(v) for v in tests)} (equally likely; not disclosed). It pre-stages, and prepares your site, exactly when the agreement makes that cheaper for it than not.",
            f"- If it carries your facility's readiness it adds {ra._pct(t.uncontrolled_contingency)} of expected standby as a contingency.",
            f"- Its capital costs {ra._pct(t.integrator_capital_rate)} a year, so a deposit it can use saves it financing.",
            "", *protocol,
            "Your objective: the lowest expected total cost to you: the price, plus every expected loss you carry at your risk charge, plus deposit "
            "financing, the escrow fee and a burn-in week of revenue, plus the cost of your redlines; walking away costs you the better outside option.",
        ])
    return "\n".join([
        "You are the integrator. You will deliver a GPU cluster into the client's facility. Money is in $ thousands.",
        "", *common, "",
        "Your position:",
        f"- Pre-staging costs you {ra._k(own.test_cost)}.",
        f"- Each $1 of expected payout you carry costs you ${1 + own.risk_charge:.2f} (insurance and balance sheet).",
        f"- If you carry the client's facility readiness you add {ra._pct(t.uncontrolled_contingency)} of expected standby as a contingency.",
        f"- Your capital costs {ra._pct(t.integrator_capital_rate)} a year, so a deposit you can use saves you financing.",
        f"- Outside option: other work that earns you {ra._k(t.floor_margin)}.",
        "",
        "The client negotiates for itself: it wants the lowest expected total cost. What you know about it:",
        f"- Each $1 of expected loss it carries costs it $1 plus its own risk charge, which is {' or '.join(f'{v:g}' for v in ccharges)} (equally likely; not disclosed).",
        f"- Its capital costs {ra._pct(c.capital_rate)} a year.",
        f"- It holds a rival turnkey offer at {ra._k(c.turnkey_all_in)} all in, and could manage the deployment itself with a team costing {ra._k(x.team)} besides the hardware, carrying every risk.",
        "- It knows whether you would pre-stage and prepare its site under each agreement.",
        "", *protocol,
        "Your objective: the highest expected profit: the price, less your expected cost of the agreement (hardware, delivery, pre-staging and site "
        "preparation if you do them, the burn-in crew, every expected payout at your risk charge, the standby contingency, less deposit financing "
        "saved), less the cost of your redlines; walking away earns your outside option.",
    ])


__all__ = ["ACTIONS", "ALL_AGREEMENTS", "FIRST", "MOVES", "POLICIES", "SEATS", "TERMS", "WORDING", "allowed", "apply", "best_agreement",
           "brief", "costs", "document", "draft", "grade", "initial_state", "is_final", "joint_cost", "other"]
