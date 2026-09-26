"""The tender as a shared-runner environment.

One phase, one seat: the model is the client (:mod:`.risk_allocation_tender`). Three
integrators bid, each a scripted firm whose private type fixes how it prices every
contract on its playbook's menu (a policy no brief states); they answer inside ``step``.
A move is one of

    {"action": "accept",    "offer": "B2-O3", "moves": null, "reason": "..."}
    {"action": "negotiate", "offer": null,    "moves": [{"bidder": "B1", "kind": "counter", "terms": {...}, "price": <its terms>},
                                                        {"bidder": "B3", "kind": "quote",   "terms": {...}, "price": null}], "reason": "..."}
    {"action": "walk",      "offer": null,    "moves": null, "reason": "..."}

A turn's moves go to different bidders and are answered together. A counter a firm would
sign at is confirmed: the client's figure becomes that firm's standing offer. Every other
counter, and every price request, is answered with the firm's own price for that contract
now, which becomes a standing offer; a contract off its menu is declined without a price.
Each of those refusals costs a week of team time and is followed by the firm's break-off
draw for the round it answered at, stored in the case so every model meets the same luck
in the same world. After the last turn only accept or walk remain.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult

from . import risk_allocation_contracts as rc
from . import risk_allocation_tender as rt
from .risk_allocation_contracts_environment import TERMS_SCHEMA
from .risk_allocation_environment import _thaw
from .risk_allocation_tender_measurement import REFERENCE_IMPLEMENTATION_ID, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID, TenderScorer

FAMILY_ID = "datacenter_risk_allocation_tender_v1"
FAMILY_VERSION = "0.1.0"
PLUGIN_ID = "datacenter_risk_allocation_tender_environment_v1"
PHASE_ID = "run_the_tender"
SEAT = "client"
OBSERVATION_SCHEMA = "datacenter_risk_allocation_tender_observation_v1"
ACTION_SCHEMA = "datacenter_risk_allocation_tender_action_v1"
VISIBILITY_POLICY = "datacenter_risk_allocation_tender_policy_and_bidder_costs_private_v1"
TERMINATIONS = ("signed", "walked", "invalid_action")
PAYLOAD_FIELDS = {"world", "extras", "bidders", "breakoff_draws"}
ACTIONS = ("accept", "negotiate", "walk")
MOVE_KINDS = ("counter", "quote")

MOVE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["bidder", "kind", "terms", "price"],
    "properties": {
        "bidder": {"type": "string", "enum": list(rt.BIDDER_IDS)},
        "kind": {"type": "string", "enum": list(MOVE_KINDS)},
        "terms": TERMS_SCHEMA,
        "price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    },
}
STRICT_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "offer", "moves", "reason"],
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "offer": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "moves": {"anyOf": [{"type": "array", "items": MOVE_SCHEMA}, {"type": "null"}]},
        "reason": {"type": "string"},
    },
}


def tender_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict({
        "spec_version": FamilyManifest.SPEC_VERSION,
        "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
        "environment": {"topology": "single_seat_scripted_counterparts_v1", "phase_specs": [PHASE_ID], "needs_tools": False, "needs_sandbox": False},
        "roles": {SEAT: {"testable": True, "scripted_policies": ["reference", *rt.RULES]}},
        "measurement": {"primary_estimand": "decision_regret", "measurement_kind": "property_or_answer", "direction": "minimize",
                        "comparison_baseline": "best_play_of_a_client_who_knows_the_bidders_pricing_policy", "outcome_support": "nonnegative_real"},
        "scoring": {"scorer_id": SCORER_IMPLEMENTATION_ID, "reference_provider_ids": [VALIDITY_IMPLEMENTATION_ID, REFERENCE_IMPLEMENTATION_ID]},
    })


def parse_tender_move(response: Any) -> ParseResult:
    if isinstance(response, CanonicalResponse):
        if response.truncated:
            return ParseResult.failure("truncated_reply")
        if response.action is not None:
            value: Any = response.action
        else:
            text = response.text or ""
            try:
                value = json.loads(text[text.index("{"): text.rindex("}") + 1])
            except ValueError:
                return ParseResult.failure("malformed_json")
    else:
        value = response
    if not isinstance(value, Mapping) or "action" not in value:
        return ParseResult.failure("malformed_action")
    kind, offer, moves = value.get("action"), value.get("offer"), value.get("moves")
    if kind not in ACTIONS:
        return ParseResult.failure("unknown_action")
    move = {"action": kind, "offer": None, "moves": None, "reason": value.get("reason")}
    if kind in ("walk", "accept") and moves not in (None, []):
        return ParseResult.failure(f"moves_on_{kind}")
    if kind == "walk":
        if offer is not None:
            return ParseResult.failure("offer_on_a_walk")
        return ParseResult.success(move)
    if kind == "accept":
        if not isinstance(offer, str):
            return ParseResult.failure("accept_names_one_offer")
        return ParseResult.success({**move, "offer": offer})
    if offer is not None:
        return ParseResult.failure("offer_on_negotiate")
    if not isinstance(moves, list) or not moves:
        return ParseResult.failure("negotiate_needs_moves")
    clean = []
    for m in moves:
        if not isinstance(m, Mapping) or m.get("bidder") not in rt.BIDDER_IDS or m.get("kind") not in MOVE_KINDS:
            return ParseResult.failure("malformed_move")
        terms, price = m.get("terms"), m.get("price")
        if not isinstance(terms, Mapping) or set(terms) - set(rc.TERMS):
            return ParseResult.failure("move_needs_terms")
        for k, v in terms.items():
            levels = rc.LEVELS[k]
            if v is not None and (isinstance(v, bool) != isinstance(levels[0], bool) or v not in levels):
                return ParseResult.failure("bad_term_level")
        if m["kind"] == "quote" and price is not None:
            return ParseResult.failure("price_on_a_quote")
        if m["kind"] == "counter" and (isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0):
            return ParseResult.failure("bad_price")
        clean.append({"bidder": m["bidder"], "kind": m["kind"], "terms": {k: terms.get(k) for k in rc.TERMS},
                      "price": None if price is None else float(price)})
    if len({m["bidder"] for m in clean}) != len(clean):
        return ParseResult.failure("two_moves_to_one_bidder")
    return ParseResult.success({**move, "moves": clean})


def _open(state: Mapping[str, Any], j: int, rounds: int) -> bool:
    b = state["bidders"][j]
    return b["alive"] and b["round"] <= rounds and not state["final"]


def _upsert(state: dict[str, Any], j: int, contract: rc.Contract, price: float) -> str:
    """Bidder j's standing offer for this contract: the lowest price it has stated or confirmed for it."""
    for o in state["offers"]:
        if o["bidder"] == j and o["contract"] == contract.as_dict():
            o["price"] = min(o["price"], price)
            return o["id"]
    oid = f"{rt.BIDDER_IDS[j]}-O{state['next_offer'][j]}"
    state["next_offer"][j] += 1
    state["offers"].append({"id": oid, "bidder": j, "contract": contract.as_dict(), "price": price})
    return oid


class TenderPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != PAYLOAD_FIELDS:
            raise ValueError(f"payload fields must be {sorted(PAYLOAD_FIELDS)}")
        w, _, bidders = rt.tender_from(payload)
        if len(bidders) != len(rt.BIDDER_IDS):
            raise ValueError(f"a tender has {len(rt.BIDDER_IDS)} bidders")
        prior = {t for t, _ in w.prior}
        for b in bidders:
            if b.playbook not in rt.PLAYBOOKS or b.type not in prior:
                raise ValueError("a bidder's playbook must be managed or turnkey and its type in the declared prior")
        draws = payload["breakoff_draws"]
        if len(draws) != len(bidders) or any(len(d) != w.rounds or not all(isinstance(u, float) and 0.0 <= u < 1.0 for u in d) for d in draws):
            raise ValueError("one uniform break-off draw per bidder per round is required")
        return _thaw(payload)

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del run
        solver = rt.solver_for(family_case)
        state = {"turn": 1, "final": False, "offers": [], "next_offer": [1] * len(solver.bidders),
                 "bidders": [{"round": 1, "alive": True} for _ in solver.bidders], "history": [], "decisions": [],
                 "refused": 0, "declined": 0, "finished": False, "termination": None, "signed": None, "invalid": None}
        for j, b in enumerate(solver.bidders):
            _upsert(state, j, rc.BASES[b.playbook], solver.bid(j))
        return state

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        w, _, _ = rt.tender_from(family_case)
        return (PhaseSpec(PHASE_ID, SEAT, "single", {SEAT: OBSERVATION_SCHEMA}, {SEAT: ACTION_SCHEMA}, w.rounds + 1, "family_defined", (PHASE_ID,)),)

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state, phase
        return (SEAT,)

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del family_case, state, seat, phase
        return parse_tender_move(response)

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del seat, phase
        if state["finished"]:
            return LegalityResult.illegal("tender_over")
        w, _, bidders = rt.tender_from(family_case)
        if action["action"] == "accept" and action["offer"] not in {o["id"] for o in state["offers"]}:
            return LegalityResult.illegal("no_such_offer")
        if action["action"] == "negotiate":
            if state["final"]:
                return LegalityResult.illegal("final_answer_only")
            for m in action["moves"]:
                j = rt.BIDDER_IDS.index(m["bidder"])
                if j >= len(bidders) or not _open(state, j, w.rounds):
                    return LegalityResult.illegal("bidder_not_negotiating")
        return LegalityResult.legal_action()

    def step(self, family_case, state, phase, actions) -> TransitionResult:
        del phase
        envelope = actions[SEAT]
        new = json.loads(json.dumps(_thaw(state)))
        if not envelope.valid:
            reason = envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
            new.update(finished=True, termination="invalid_action", invalid=reason)
            return TransitionResult(new, None, {"termination": "invalid_action", "invalid": reason})
        act = _thaw(envelope.action)
        solver = rt.solver_for(family_case)
        w = solver.w
        if act["action"] == "walk":
            new["decisions"].append({"turn": state["turn"], "kind": "walk"})
            new.update(finished=True, termination="walked")
            return TransitionResult(new, None, {"termination": "walked"})
        if act["action"] == "accept":
            offer = next(o for o in state["offers"] if o["id"] == act["offer"])
            new["decisions"].append({"turn": state["turn"], "kind": "accept", "bidder": offer["bidder"], "contract": offer["contract"], "price": offer["price"]})
            new.update(finished=True, termination="signed", signed={"offer": offer["id"], "bidder": offer["bidder"], "contract": offer["contract"], "price": offer["price"]})
            return TransitionResult(new, None, {"termination": "signed"})
        moves, entries = [], []
        for m in act["moves"]:
            j = rt.BIDDER_IDS.index(m["bidder"])
            playbook = solver.bidders[j].playbook
            contract = rc.contract_from(m["terms"], rc.BASES[playbook])
            price = None if m["price"] is None else rt.all_in(playbook, w, m["price"])
            moves.append({"bidder": j, "contract": contract.as_dict(), "price": price})
            b = new["bidders"][j]
            ci = solver.index(j, contract)
            entry: dict[str, Any] = {"bidder": m["bidder"], "request": m["kind"], "terms": contract.as_dict(), "your_price": m["price"]}
            if ci is not None and price is not None and price >= float(solver.th[j][b["round"]][ci]) - 1e-6:
                oid = _upsert(new, j, contract, price)
                entry.update(answer=f"confirms: will sign at your figure, standing offer {oid}", their_price=m["price"], offer=oid)
                entries.append(entry)
                continue
            new["refused"] += 1
            if ci is None:
                new["declined"] += 1
                entry.update(answer="declined: that contract is not on its menu", their_price=None, offer=None)
            else:
                ans = round(float(solver.th[j][b["round"]][ci]), 6)
                oid = _upsert(new, j, contract, ans)
                unit = "fee" if rc.fee_based(playbook) else "all in"
                entry.update(answer=f"would sign at {rt.show(playbook, w, ans):,.1f} ({unit}) now, standing offer {oid}",
                             their_price=rt.show(playbook, w, ans), offer=oid)
            if family_case["breakoff_draws"][j][b["round"] - 1] < w.terms.breakoff:
                b["alive"] = False
                new["offers"] = [o for o in new["offers"] if o["bidder"] != j]
                entry["broke_off"] = True
            b["round"] += 1
            entries.append(entry)
        new["decisions"].append({"turn": state["turn"], "kind": "negotiate", "moves": moves})
        new["history"].append({"turn": state["turn"], "moves": entries})
        new["turn"] = state["turn"] + 1
        new["final"] = new["turn"] > w.rounds
        return TransitionResult(new, PHASE_ID, {"termination": None})

    def _shown_offers(self, family_case, state) -> list[dict[str, Any]]:
        solver = rt.solver_for(family_case)
        return [{"id": o["id"], "bidder": rt.BIDDER_IDS[o["bidder"]], "terms": o["contract"],
                 "price": rt.show(solver.bidders[o["bidder"]].playbook, solver.w, o["price"])} for o in state["offers"]]

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del phase
        solver = rt.solver_for(family_case)
        w = solver.w
        status = lambda j: "broke off" if not state["bidders"][j]["alive"] else "bidding"  # noqa: E731
        return {
            "seat": seat,
            "brief": rt.brief(family_case),
            "turn": min(state["turn"], w.rounds),
            "turns": w.rounds,
            "final": state["final"],
            "bidders": [{"id": b.id, "playbook": b.playbook, "price_terms": "fee, hardware on top" if rc.fee_based(b.playbook) else "all in",
                         "status": status(j)} for j, b in enumerate(solver.bidders)],
            "standing_offers": self._shown_offers(family_case, state),
            "history": state["history"],
            "allowed_actions": ["accept", "walk"] if state["final"] else list(ACTIONS),
        }

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return json.loads(json.dumps(_thaw(state))) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        g = rt.grade(family_case, terminal["decisions"], terminal["signed"], terminal["termination"], terminal["refused"])
        g["invalid"] = terminal.get("invalid")
        g["declined_requests"] = terminal.get("declined", 0)
        return {"termination": terminal["termination"], "signed": terminal["signed"], "invalid": terminal.get("invalid"), "grade": g}

    def build_scorer(self, family_case) -> TenderScorer:
        return TenderScorer(family_case)

    def build_reference_providers(self, family_case):
        del family_case
        return ()

    def generator(self, family_case=None):
        del family_case
        return None


def solver_state(family_case: Mapping[str, Any], state: Mapping[str, Any]) -> rt.TState:
    """What a client who knows the policy knows now, read off the episode's state: each bidder's round, whether it is
    still bidding, and the lowest total among its standing offers."""
    solver = rt.solver_for(family_case)
    best = [math.inf] * len(solver.bidders)
    for o in state["offers"]:
        j = o["bidder"]
        ci = solver.index(j, rc.Contract(**o["contract"]))
        best[j] = min(best[j], rt._key(o["price"] + float(solver.cc[j][ci])))
    return rt.TState(state["turn"], tuple(rt.BState(b["round"], b["alive"], best[j] if b["alive"] else math.inf)
                                          for j, b in enumerate(state["bidders"])))


__all__ = ["ACTION_SCHEMA", "FAMILY_ID", "FAMILY_VERSION", "PHASE_ID", "PLUGIN_ID", "SEAT", "STRICT_ACTION_SCHEMA", "TERMINATIONS", "TenderPlugin",
           "VISIBILITY_POLICY", "parse_tender_move", "solver_state", "tender_family_manifest"]
