"""The two-sided risk-allocation negotiation as a shared-runner environment.

Two seats, two phases that alternate: ``integrator_move`` then ``client_move``,
each one action by one seat (:mod:`.risk_allocation_two_sided`). A seat sees its
own brief (its own private cost, the other side's only as the declared prior),
the moves so far and what it may do now; the world's hidden types stay in the
payload. The action shape is the one-sided case's, one package per proposal:

    {"action": "propose", "package": {...}, "price": <number, or null to ask for the other side's price>, "reason": "..."}
    {"action": "accept", "package": null, "price": null, "reason": "..."}
    {"action": "walk", "package": null, "price": null, "reason": "..."}

The one-sided plugin and its receipts are untouched: this is its own family id,
plugin id and scorer.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult

from . import risk_allocation as ra
from . import risk_allocation_two_sided as ts
from .risk_allocation_environment import STRICT_ACTION_SCHEMA, _thaw
from .risk_allocation_two_sided_measurement import REFERENCE_IMPLEMENTATION_ID, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID, TwoSidedScorer

FAMILY_ID = "datacenter_risk_allocation_two_sided_v1"
FAMILY_VERSION = "0.1.0"
PLUGIN_ID = "datacenter_risk_allocation_two_sided_environment_v1"
PHASE_OF = {"integrator": "integrator_move", "client": "client_move"}
SEAT_OF = {v: k for k, v in PHASE_OF.items()}
OBSERVATION_SCHEMA = "datacenter_risk_allocation_two_sided_observation_v1"
ACTION_SCHEMA = "datacenter_risk_allocation_action_v1"  # the one-sided action shape, one package per proposal
VISIBILITY_POLICY = "datacenter_risk_allocation_two_sided_own_costs_private_v1"
TERMINATIONS = ("signed", "walked", "broke_off", "invalid_action")
PAYLOAD_FIELDS = {"world", "integrator_type", "breakoff_draws"}
ACTIONS = ("propose", "accept", "walk")
STRICT_ACTION_SCHEMA_TWO_SIDED = STRICT_ACTION_SCHEMA


def two_sided_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
            "environment": {
                "topology": "two_seat_alternating_offers_v1",
                "phase_specs": [PHASE_OF[s] for s in ts.SEATS],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {seat: {"testable": True, "scripted_policies": sorted(ts.POLICIES)} for seat in ts.SEATS},
            "measurement": {
                "primary_estimand": "joint_value_lost",
                "measurement_kind": "property_or_answer",
                "direction": "minimize",
                "comparison_baseline": "full_information_efficient_outcome",
                "outcome_support": "nonnegative_real",
            },
            "scoring": {"scorer_id": SCORER_IMPLEMENTATION_ID, "reference_provider_ids": [VALIDITY_IMPLEMENTATION_ID, REFERENCE_IMPLEMENTATION_ID]},
        }
    )


def world_and_type(payload: Mapping[str, Any]) -> tuple[ra.World, ra.IntegratorType]:
    return ra.world_from_dict(payload["world"]), ra.IntegratorType(**payload["integrator_type"])


def _package(value: Any) -> ra.Package:
    if not isinstance(value, Mapping) or set(value) != set(ra.TERMS):
        raise ValueError("bad_package")
    for k, levels in ra.TERMS.items():
        if value[k] not in levels:
            raise ValueError("bad_package")
    return ra.Package(**{k: value[k] for k in ra.TERMS})


def parse_move(response: Any) -> ParseResult:
    """A reply cut off by the output limit is typed on its own (missingness, DC-O-08);
    otherwise the one-sided checks, one package per proposal."""
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
    kind, reason = value["action"], value.get("reason")
    if kind not in ACTIONS:
        return ParseResult.failure("unknown_action")
    if value.get("alternate") is not None:
        return ParseResult.failure("alternate_not_offered")
    if kind != "propose":
        if value.get("package") is not None or value.get("price") is not None:
            return ParseResult.failure("terms_on_a_non_proposal")
        return ParseResult.success({"action": kind, "package": None, "price": None, "reason": reason})
    try:
        pkg = _package(value.get("package"))
    except ValueError:
        return ParseResult.failure("bad_package")
    price = value.get("price")
    if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0):
        return ParseResult.failure("bad_price")
    return ParseResult.success({"action": "propose", "package": pkg.as_dict(), "price": None if price is None else float(price), "reason": reason})


def _history_for(state: Mapping[str, Any], seat: str) -> list[dict[str, Any]]:
    """The moves so far as the seat reads them: who moved, what, at what price."""
    out = []
    for h in state["history"]:
        who = "you" if h["by"] == seat else h["by"]
        row = {"move": h["move"], "by": who, "action": h["action"]}
        if h["action"] == "propose":
            row["package"] = h["package"]
            row["price"] = h["price"]
            if h["price"] is None:
                row["note"] = "asked the other side to price this package"
        out.append(row)
    return out


class TwoSidedPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != PAYLOAD_FIELDS:
            raise ValueError(f"payload fields must be {sorted(PAYLOAD_FIELDS)}")
        w, it = world_and_type(payload)
        if it not in {t for t, _ in w.prior}:
            raise ValueError("the integrator's type is not in the declared prior")
        if w.client.risk_charge not in {c for c, _ in w.client_prior}:
            raise ValueError("the client's risk charge is not in the declared prior")
        draws = payload["breakoff_draws"]
        if len(draws) != ts.max_moves(w) or not all(isinstance(u, float) and 0.0 <= u < 1.0 for u in draws):
            raise ValueError("one uniform break-off draw per move is required")
        return _thaw(payload)

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del run
        w, _ = world_and_type(family_case)
        return ts.initial_state(w)

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        w, _ = world_and_type(family_case)
        per_seat = w.rounds + 1
        return tuple(
            PhaseSpec(PHASE_OF[seat], seat, "single", {seat: OBSERVATION_SCHEMA}, {seat: ACTION_SCHEMA}, per_seat, "family_defined",
                      (PHASE_OF[ts.other(seat)],))
            for seat in ts.SEATS
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state
        return (SEAT_OF[phase.phase_id],)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del phase
        w, it = world_and_type(family_case)
        st, req = state["standing"], state["request"]
        return {
            "seat": seat,
            "brief": ts.brief(w, seat, it if seat == "integrator" else None),
            "move": state["move"],
            "moves": state["moves"],
            "your_moves_left": sum(1 for m in range(state["move"], state["moves"] + 1) if (m % 2 == 1) == (seat == ts.FIRST)),
            "final": ts.is_final(state),
            "standing_offer": None if st is None else {"package": st["package"], "price": st["price"]},
            "price_request": None if req is None else {"package": req["package"]},
            "history": _history_for(state, seat),
            "allowed_actions": ts.allowed(state),
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
        if action["action"] == "accept" and state["standing"] is None:
            return LegalityResult.illegal("nothing_to_accept")
        if action["action"] == "propose" and ts.is_final(state):
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
        w, _ = world_and_type(family_case)
        new = ts.apply(cur, _thaw(envelope.action), w, list(family_case["breakoff_draws"]))
        return TransitionResult(new, None if new["finished"] else PHASE_OF[new["to_move"]], {"termination": new["termination"], "move": cur["move"], "by": seat})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return json.loads(json.dumps(_thaw(state))) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        w, it = world_and_type(family_case)
        return {"termination": terminal["termination"], "signed": terminal["signed"], "invalid": terminal.get("invalid"),
                "invalid_by": terminal.get("invalid_by"), "grade": ts.grade_two_sided(w, it, terminal)}

    def build_scorer(self, family_case) -> TwoSidedScorer:
        return TwoSidedScorer(family_case)

    def build_reference_providers(self, family_case):
        del family_case
        return ()

    def generator(self, family_case=None):
        del family_case
        return None


__all__ = [
    "ACTION_SCHEMA",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "PHASE_OF",
    "PLUGIN_ID",
    "STRICT_ACTION_SCHEMA_TWO_SIDED",
    "TwoSidedPlugin",
    "parse_move",
    "two_sided_family_manifest",
    "world_and_type",
]
