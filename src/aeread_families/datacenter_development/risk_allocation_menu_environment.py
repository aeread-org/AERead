"""The playbook-menu negotiation as a shared-runner environment.

One phase, one seat: the model is the client (:mod:`.risk_allocation_menu`). The
integrator is scripted: its private type fixes which playbook it posts and how it
prices each option (a policy the brief does not state), and it answers a counter
inside ``step``. A move is one of

    {"action": "accept", "item": "C", "price": null, "outside": null, "reason": "..."}
    {"action": "counter", "item": "C", "price": <in the menu's own terms>, "outside": null, "reason": "..."}
    {"action": "walk", "item": null, "price": null, "outside": "turnkey" | "self_manage", "reason": "..."}

Prices are in the menu's terms: the fee for a coordination or managed playbook, the
all-in price for turnkey. Break-off after a refused counter is decided by a draw
stored in the case, so every model meets the same luck in the same world. The score
is decision regret against a client who knows the integrator's policy.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult

from . import risk_allocation_menu as rm
from .risk_allocation_environment import _thaw
from .risk_allocation_menu_measurement import REFERENCE_IMPLEMENTATION_ID, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID, MenuScorer

FAMILY_ID = "datacenter_risk_allocation_menu_v1"
FAMILY_VERSION = "0.1.0"
PLUGIN_ID = "datacenter_risk_allocation_menu_environment_v1"
PHASE_ID = "negotiate_the_menu"
SEAT = "client"
OBSERVATION_SCHEMA = "datacenter_risk_allocation_menu_observation_v1"
ACTION_SCHEMA = "datacenter_risk_allocation_menu_action_v1"
VISIBILITY_POLICY = "datacenter_risk_allocation_menu_policy_and_integrator_costs_private_v1"
TERMINATIONS = ("signed", "walked", "broke_off", "invalid_action")
PAYLOAD_FIELDS = {"world", "integrator_type", "team", "breakoff_draws"}
ACTIONS = ("accept", "counter", "walk")

STRICT_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "item", "price", "outside", "reason"],
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "item": {"anyOf": [{"type": "string", "enum": list(rm.LABELS)}, {"type": "null"}]},
        "price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "outside": {"anyOf": [{"type": "string", "enum": list(rm.OUTSIDE)}, {"type": "null"}]},
        "reason": {"type": "string"},
    },
}


def menu_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict({
        "spec_version": FamilyManifest.SPEC_VERSION,
        "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
        "environment": {"topology": "single_seat_scripted_counterpart_v1", "phase_specs": [PHASE_ID], "needs_tools": False, "needs_sandbox": False},
        "roles": {SEAT: {"testable": True, "scripted_policies": ["reference", *rm.RULES]}},
        "measurement": {"primary_estimand": "decision_regret", "measurement_kind": "property_or_answer", "direction": "minimize",
                        "comparison_baseline": "best_play_of_a_client_who_knows_the_integrators_policy", "outcome_support": "nonnegative_real"},
        "scoring": {"scorer_id": SCORER_IMPLEMENTATION_ID, "reference_provider_ids": [VALIDITY_IMPLEMENTATION_ID, REFERENCE_IMPLEMENTATION_ID]},
    })


def world_of(payload: Mapping[str, Any]):
    return rm.menu_world_from(payload)


def parse_menu_move(response: Any) -> ParseResult:
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
    kind, item, price, outside, reason = value["action"], value.get("item"), value.get("price"), value.get("outside"), value.get("reason")
    if kind not in ACTIONS:
        return ParseResult.failure("unknown_action")
    if kind == "walk":
        if outside not in rm.OUTSIDE:
            return ParseResult.failure("walk_needs_an_outside_option")
        if item is not None or price is not None:
            return ParseResult.failure("terms_on_a_walk")
        return ParseResult.success({"action": "walk", "item": None, "price": None, "outside": outside, "reason": reason})
    if item not in rm.LABELS:
        return ParseResult.failure("unknown_item")
    if outside is not None:
        return ParseResult.failure("outside_on_a_deal")
    if kind == "accept":
        if price is not None:
            return ParseResult.failure("price_on_an_accept")
        return ParseResult.success({"action": "accept", "item": item, "price": None, "outside": None, "reason": reason})
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return ParseResult.failure("bad_price")
    return ParseResult.success({"action": "counter", "item": item, "price": float(price), "outside": None, "reason": reason})


class MenuPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != PAYLOAD_FIELDS:
            raise ValueError(f"payload fields must be {sorted(PAYLOAD_FIELDS)}")
        mw, it = world_of(payload)
        if it not in {t for t, _ in mw.w.prior}:
            raise ValueError("the integrator's type is not in the declared prior")
        draws = payload["breakoff_draws"]
        if len(draws) != mw.w.rounds or not all(isinstance(u, float) and 0.0 <= u < 1.0 for u in draws):
            raise ValueError("one uniform break-off draw per round is required")
        return _thaw(payload)

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del run
        mw, it = world_of(family_case)
        listed = list(rm.list_prices(mw.playbook, mw.w, it))
        return {"round": 1, "final": False, "listed": listed, "standing": listed, "history": [], "decisions": [],
                "refused": 0, "finished": False, "termination": None, "signed": None, "outside": None, "invalid": None}

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        mw, _ = world_of(family_case)
        return (PhaseSpec(PHASE_ID, SEAT, "single", {SEAT: OBSERVATION_SCHEMA}, {SEAT: ACTION_SCHEMA}, mw.w.rounds + 1, "family_defined", (PHASE_ID,)),)

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state, phase
        return (SEAT,)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del phase
        mw, _ = world_of(family_case)
        return {
            "seat": seat,
            "brief": rm.menu_brief(mw, tuple(state["listed"])),
            "round": state["round"],
            "rounds": mw.w.rounds,
            "final": state["final"],
            "price_terms": "fee, hardware on top" if rm.fee_based(mw.playbook) else "all in",
            "current_prices": {rm.LABELS[i]: rm.shown_price(mw, x) for i, x in enumerate(state["standing"])},
            "history": state["history"],
            "allowed_actions": ["accept", "walk"] if state["final"] else list(ACTIONS),
        }

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del family_case, state, seat, phase
        return parse_menu_move(response)

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del family_case, seat, phase
        if state["finished"]:
            return LegalityResult.illegal("negotiation_over")
        if action["action"] == "counter" and state["final"]:
            return LegalityResult.illegal("final_answer_only")
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
        mw, it = world_of(family_case)
        k = None if act["item"] is None else rm.LABELS.index(act["item"])
        all_in = None if act["price"] is None else rm.all_in_price(mw, act["price"])
        new["decisions"].append({"kind": {"counter": "propose"}.get(act["action"], act["action"]), "item": k, "price": all_in,
                                 "outside": act["outside"], "round": state["round"], "final": state["final"]})
        if act["action"] == "walk":
            new.update(finished=True, termination="walked", outside=act["outside"])
        elif act["action"] == "accept":
            new.update(finished=True, termination="signed", signed={"item": k, "price": state["standing"][k]})
        else:
            thr = rm.threshold(mw.playbook, mw.items[k], mw.w, it, state["round"])
            if all_in >= thr - 1e-6:
                new.update(finished=True, termination="signed", signed={"item": k, "price": all_in})
            else:
                new["refused"] += 1
                new["standing"][k] = round(thr, 6)
                new["history"].append({"round": state["round"], "item": act["item"], "your_price": act["price"],
                                       "answer": f"would sign {act['item']} at {rm.shown_price(mw, thr):,.1f} ({'fee' if rm.fee_based(mw.playbook) else 'all in'}) this round",
                                       "their_price": rm.shown_price(mw, thr)})
                if family_case["breakoff_draws"][state["round"] - 1] < mw.w.terms.breakoff:
                    new.update(finished=True, termination="broke_off")
                elif state["round"] == mw.w.rounds:
                    new["final"] = True
                else:
                    new["round"] = state["round"] + 1
        return TransitionResult(new, None if new["finished"] else PHASE_ID, {"termination": new["termination"]})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return json.loads(json.dumps(_thaw(state))) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        mw, it = world_of(family_case)
        g = rm.grade_menu(mw, it, terminal["decisions"], terminal["signed"], terminal["outside"], terminal["termination"], terminal["refused"])
        g["invalid"] = terminal.get("invalid")
        return {"termination": terminal["termination"], "signed": terminal["signed"], "invalid": terminal.get("invalid"), "grade": g}

    def build_scorer(self, family_case) -> MenuScorer:
        return MenuScorer(family_case)

    def build_reference_providers(self, family_case):
        del family_case
        return ()

    def generator(self, family_case=None):
        del family_case
        return None


__all__ = ["ACTION_SCHEMA", "FAMILY_ID", "FAMILY_VERSION", "MenuPlugin", "PHASE_ID", "PLUGIN_ID", "STRICT_ACTION_SCHEMA",
           "menu_family_manifest", "parse_menu_move", "world_of"]
