"""The agreement negotiation as a shared-runner environment.

Two seats, two phases that alternate: ``integrator_move`` then ``client_move``
(:mod:`.agreement`). A seat sees its own brief, the agreement as it stands clause
by clause with the latest tracked change on each, the price on the table, every
move so far with its note, and what it may do now. The world's hidden types stay
in the payload. One action shape:

    {"action": "redline", "clauses": {<clause>: <position> or null, ...}, "price": <all-in $k>, "note": "..."}
    {"action": "sign", "clauses": null, "price": null, "note": "..."}
    {"action": "walk", "clauses": null, "price": null, "note": "..."}

A clause left null stands as it is. A position outside a clause's fixed list is a
parse failure of that move: the first slice has no free drafting.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult

from . import agreement as ag
from . import risk_allocation_contracts as rc
from .agreement_measurement import REFERENCE_IMPLEMENTATION_ID, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID, AgreementScorer
from .risk_allocation_environment import _thaw

FAMILY_ID = "datacenter_agreement_v1"
FAMILY_VERSION = "0.1.0"
PLUGIN_ID = "datacenter_agreement_environment_v1"
PHASE_OF = {"integrator": "integrator_move", "client": "client_move"}
SEAT_OF = {v: k for k, v in PHASE_OF.items()}
OBSERVATION_SCHEMA = "datacenter_agreement_observation_v1"
ACTION_SCHEMA = "datacenter_agreement_action_v1"
VISIBILITY_POLICY = "datacenter_agreement_own_costs_private_v1"
TERMINATIONS = ("signed", "walked", "invalid_action")
PAYLOAD_FIELDS = {"world", "integrator_type", "extras"}
BRIEF_FIELD = "brief_version"  # optional; absent means the v1 brief, so every earlier case is unchanged


def _world(payload: Mapping[str, Any]):
    return rc.world_from({k: payload[k] for k in PAYLOAD_FIELDS})
NOTE_LIMIT = 400


def _position_schema(levels: tuple[Any, ...]) -> dict[str, Any]:
    if isinstance(levels[0], bool):
        return {"type": ["boolean", "null"]}
    return {"type": ["string", "null"], "enum": [*levels, None]}


#: Every field required and nullable, no other fields: the shape strict structured output takes.
STRICT_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["action", "clauses", "price", "note"],
    "properties": {
        "action": {"type": "string", "enum": list(ag.ACTIONS)},
        "clauses": {"type": ["object", "null"], "additionalProperties": False, "required": list(ag.TERMS),
                    "properties": {k: _position_schema(rc.LEVELS[k]) for k in ag.TERMS}},
        "price": {"type": ["number", "null"]},
        "note": {"type": ["string", "null"]},
    },
}


def agreement_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict({
        "spec_version": FamilyManifest.SPEC_VERSION,
        "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
        "environment": {"topology": "two_seat_alternating_redlines_v1", "phase_specs": [PHASE_OF[s] for s in ag.SEATS],
                        "needs_tools": False, "needs_sandbox": False},
        "roles": {seat: {"testable": True, "scripted_policies": sorted(ag.POLICIES)} for seat in ag.SEATS},
        "measurement": {"primary_estimand": "joint_value_lost", "measurement_kind": "property_or_answer", "direction": "minimize",
                        "comparison_baseline": "full_information_best_agreement", "outcome_support": "nonnegative_real"},
        "scoring": {"scorer_id": SCORER_IMPLEMENTATION_ID, "reference_provider_ids": [VALIDITY_IMPLEMENTATION_ID, REFERENCE_IMPLEMENTATION_ID]},
    })


def parse_move(response: Any) -> ParseResult:
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
    if not isinstance(value, Mapping) or value.get("action") not in ag.ACTIONS:
        return ParseResult.failure("unknown_action")
    note = value.get("note")
    note = None if note is None else str(note)[:NOTE_LIMIT]
    if value["action"] != "redline":
        clauses = value.get("clauses")
        if (clauses is not None and any(v is not None for v in clauses.values())) or value.get("price") is not None:
            return ParseResult.failure("terms_on_a_move_that_is_not_a_redline")
        return ParseResult.success({"action": value["action"], "clauses": None, "price": None, "note": note})
    raw = value.get("clauses") or {}
    if not isinstance(raw, Mapping) or not set(raw) <= set(ag.TERMS):
        return ParseResult.failure("unknown_clause")
    clauses = {}
    for k in ag.TERMS:
        v = raw.get(k)
        if v is not None and (isinstance(v, bool) != isinstance(rc.LEVELS[k][0], bool) or v not in rc.LEVELS[k]):
            return ParseResult.failure("position_off_the_list")
        clauses[k] = v
    price = value.get("price")
    if price is None or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return ParseResult.failure("bad_price")
    return ParseResult.success({"action": "redline", "clauses": clauses, "price": float(price), "note": note})


def _history_for(state: Mapping[str, Any], seat: str) -> list[dict[str, Any]]:
    out = []
    for h in state["history"]:
        row = {"move": h["move"], "by": "you" if h["by"] == seat else h["by"], "action": h["action"]}
        if h["action"] == "redline":
            row["changes"] = h["changes"] or "none: the clauses stand, only the price moved"
            row["price"] = h["price"]
        if h.get("note"):
            row["note"] = h["note"]
        out.append(row)
    return out


class AgreementPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) - {BRIEF_FIELD} != PAYLOAD_FIELDS:
            raise ValueError(f"payload fields must be {sorted(PAYLOAD_FIELDS)}, with an optional {BRIEF_FIELD!r}")
        if payload.get(BRIEF_FIELD, "v1") not in ag.BRIEFS or payload.get(BRIEF_FIELD) == "v1":
            raise ValueError(f"{BRIEF_FIELD} must be one of {ag.BRIEFS[1:]} when present; leave it out for v1")
        cw, it = _world(payload)
        if it not in cw.types:
            raise ValueError("the integrator's type is not one the client's brief names")
        if cw.w.client.risk_charge not in {c for c, _ in cw.w.client_prior}:
            raise ValueError("the client's risk charge is not in the declared prior")
        return _thaw(payload)

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del run
        return ag.initial_state(_world(family_case)[0])

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        del family_case
        return tuple(
            PhaseSpec(PHASE_OF[seat], seat, "single", {seat: OBSERVATION_SCHEMA}, {seat: ACTION_SCHEMA}, ag.MOVES // 2, "family_defined",
                      (PHASE_OF[ag.other(seat)],))
            for seat in ag.SEATS
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state
        return (SEAT_OF[phase.phase_id],)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del phase
        cw, it = _world(family_case)
        st = state["standing"]
        return {
            "seat": seat,
            "brief": ag.brief(cw, seat, it if seat == "integrator" else None, family_case.get(BRIEF_FIELD, "v1")),
            "move": state["move"], "moves": state["moves"],
            "your_moves_left": sum(1 for m in range(state["move"], state["moves"] + 1) if (m % 2 == 1) == (seat == ag.FIRST)),
            "final": ag.is_final(state),
            "agreement": ag.document(state, seat),
            "on_the_table": None if st is None else {"by": "you" if st["by"] == seat else st["by"], "price": st["price"],
                                                     "meaning": "its author would sign the agreement as it stands at this all-in price"},
            "history": _history_for(state, seat),
            "allowed_actions": ag.allowed(state),
        }

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del family_case, state, seat, phase
        return parse_move(response)

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del family_case, phase
        if state["finished"]:
            return LegalityResult.illegal("negotiation_over")
        if seat != state["to_move"]:
            return LegalityResult.illegal("not_your_move")
        if action["action"] == "sign" and (state["standing"] is None or state["standing"]["by"] == seat):
            return LegalityResult.illegal("nothing_to_sign")
        if action["action"] == "redline" and ag.is_final(state):
            return LegalityResult.illegal("final_answer_only")
        return LegalityResult.legal_action()

    def step(self, family_case, state, phase, actions) -> TransitionResult:
        seat = SEAT_OF[phase.phase_id]
        envelope = actions[seat]
        cur = json.loads(json.dumps(_thaw(state)))
        if not envelope.valid:
            reason = envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
            cur.update(finished=True, termination="invalid_action", invalid=reason, invalid_by=seat)
            return TransitionResult(cur, None, {"termination": "invalid_action", "invalid": reason, "invalid_by": seat})
        new = ag.apply(cur, _thaw(envelope.action), _world(family_case)[0])
        return TransitionResult(new, None if new["finished"] else PHASE_OF[new["to_move"]],
                                {"termination": new["termination"], "move": cur["move"], "by": seat})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return json.loads(json.dumps(_thaw(state))) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        cw, it = _world(family_case)
        return {"termination": terminal["termination"], "signed": terminal["signed"], "invalid": terminal.get("invalid"),
                "invalid_by": terminal.get("invalid_by"), "grade": ag.grade(cw, it, terminal)}

    def build_scorer(self, family_case) -> AgreementScorer:
        return AgreementScorer(family_case)

    def build_reference_providers(self, family_case):
        del family_case
        return ()

    def generator(self, family_case=None):
        del family_case
        return None


__all__ = ["ACTION_SCHEMA", "AgreementPlugin", "FAMILY_ID", "FAMILY_VERSION", "PHASE_OF", "PLUGIN_ID", "STRICT_ACTION_SCHEMA",
           "agreement_family_manifest", "parse_move"]
