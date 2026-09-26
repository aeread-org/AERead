"""The full-terms playbook menu as a shared-runner environment.

One phase, one seat: the model is the client (:mod:`.risk_allocation_contracts`). The
integrator is scripted: its private type fixes which playbook it posts and how it
prices each contract on the menu (a policy no brief states), and it answers inside
``step``. A move is one of

    {"action": "accept",  "offer": "O3", "terms": null,    "price": null, "outside": null, "reason": "..."}
    {"action": "counter", "offer": null, "terms": {...},   "price": <in the playbook's terms>, "outside": null, "reason": "..."}
    {"action": "quote",   "offer": null, "terms": {...},   "price": null, "outside": null, "reason": "..."}
    {"action": "walk",    "offer": null, "terms": null,    "price": null, "outside": "turnkey" | "self_manage", "reason": "..."}

``terms`` names every term; a null keeps the base contract's level. A counter the
integrator will not sign, and every price request, is answered with its price for
that contract this round, which becomes a standing offer; a contract off its menu is
declined without a price. Either way the round is spent and break-off is decided by a
draw stored in the case, so every model meets the same luck in the same world.
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
from .risk_allocation_contracts_measurement import REFERENCE_IMPLEMENTATION_ID, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID, ContractsScorer
from .risk_allocation_environment import _thaw

FAMILY_ID = "datacenter_risk_allocation_contracts_v1"
FAMILY_VERSION = "0.1.0"
PLUGIN_ID = "datacenter_risk_allocation_contracts_environment_v1"
PHASE_ID = "negotiate_the_contract"
SEAT = "client"
OBSERVATION_SCHEMA = "datacenter_risk_allocation_contracts_observation_v1"
ACTION_SCHEMA = "datacenter_risk_allocation_contracts_action_v1"
VISIBILITY_POLICY = "datacenter_risk_allocation_contracts_policy_and_integrator_costs_private_v1"
TERMINATIONS = ("signed", "walked", "broke_off", "invalid_action")
PAYLOAD_FIELDS = {"world", "integrator_type", "extras", "breakoff_draws"}
ACTIONS = ("accept", "counter", "quote", "walk")


def _level_schema(levels: tuple[Any, ...]) -> dict[str, Any]:
    if isinstance(levels[0], bool):
        return {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
    return {"anyOf": [{"type": "string", "enum": list(levels)}, {"type": "null"}]}


TERMS_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": list(rc.TERMS),
    "properties": {k: _level_schema(v) for k, v in rc.LEVELS.items()},
}
STRICT_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "offer", "terms", "price", "outside", "reason"],
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "offer": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "terms": {"anyOf": [TERMS_SCHEMA, {"type": "null"}]},
        "price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "outside": {"anyOf": [{"type": "string", "enum": list(rc.OUTSIDE)}, {"type": "null"}]},
        "reason": {"type": "string"},
    },
}


def contracts_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict({
        "spec_version": FamilyManifest.SPEC_VERSION,
        "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
        "environment": {"topology": "single_seat_scripted_counterpart_v1", "phase_specs": [PHASE_ID], "needs_tools": False, "needs_sandbox": False},
        "roles": {SEAT: {"testable": True, "scripted_policies": ["reference", *rc.RULES]}},
        "measurement": {"primary_estimand": "decision_regret", "measurement_kind": "property_or_answer", "direction": "minimize",
                        "comparison_baseline": "best_play_of_a_client_who_knows_the_integrators_policy", "outcome_support": "nonnegative_real"},
        "scoring": {"scorer_id": SCORER_IMPLEMENTATION_ID, "reference_provider_ids": [VALIDITY_IMPLEMENTATION_ID, REFERENCE_IMPLEMENTATION_ID]},
    })


def world_of(payload: Mapping[str, Any]) -> tuple[rc.CWorld, Any]:
    return rc.world_from(payload)


def parse_contract_move(response: Any) -> ParseResult:
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
    kind, offer, terms, price, outside = (value.get(k) for k in ("action", "offer", "terms", "price", "outside"))
    reason = value.get("reason")
    if kind not in ACTIONS:
        return ParseResult.failure("unknown_action")
    move = {"action": kind, "offer": None, "terms": None, "price": None, "outside": None, "reason": reason}
    if kind == "walk":
        if outside not in rc.OUTSIDE:
            return ParseResult.failure("walk_needs_an_outside_option")
        if offer is not None or terms is not None or price is not None:
            return ParseResult.failure("terms_on_a_walk")
        return ParseResult.success({**move, "outside": outside})
    if outside is not None:
        return ParseResult.failure("outside_on_a_deal")
    if kind == "accept":
        if not isinstance(offer, str) or terms is not None or price is not None:
            return ParseResult.failure("accept_names_one_offer_only")
        return ParseResult.success({**move, "offer": offer})
    if offer is not None or not isinstance(terms, Mapping):
        return ParseResult.failure(f"{kind}_needs_terms")
    if set(terms) - set(rc.TERMS):
        return ParseResult.failure("unknown_term")
    for k, v in terms.items():
        levels = rc.LEVELS[k]
        if v is not None and (isinstance(v, bool) != isinstance(levels[0], bool) or v not in levels):
            return ParseResult.failure("bad_term_level")
    clean = {k: terms.get(k) for k in rc.TERMS}
    if kind == "quote":
        if price is not None:
            return ParseResult.failure("price_on_a_quote")
        return ParseResult.success({**move, "terms": clean})
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return ParseResult.failure("bad_price")
    return ParseResult.success({**move, "terms": clean, "price": float(price)})


def listing(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The list as standing offers: id, contract, all-in price."""
    solver = rc.solver_for(payload)
    _, it = world_of(payload)
    return [{"id": f"O{i + 1}", "contract": solver.menu[ci].as_dict(), "price": price} for i, (ci, price) in enumerate(solver.list_prices(it))]


class ContractsPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != PAYLOAD_FIELDS:
            raise ValueError(f"payload fields must be {sorted(PAYLOAD_FIELDS)}")
        cw, it = world_of(payload)
        if it not in {t for t, _ in cw.w.prior}:
            raise ValueError("the integrator's type is not in the declared prior")
        draws = payload["breakoff_draws"]
        if len(draws) != cw.w.rounds or not all(isinstance(u, float) and 0.0 <= u < 1.0 for u in draws):
            raise ValueError("one uniform break-off draw per round is required")
        return _thaw(payload)

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del run
        offers = listing(family_case)
        return {"round": 1, "final": False, "offers": offers, "next_offer": len(offers) + 1, "history": [], "decisions": [],
                "refused": 0, "declined": 0, "finished": False, "termination": None, "signed": None, "outside": None, "invalid": None}

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        cw, _ = world_of(family_case)
        return (PhaseSpec(PHASE_ID, SEAT, "single", {SEAT: OBSERVATION_SCHEMA}, {SEAT: ACTION_SCHEMA}, cw.w.rounds + 1, "family_defined", (PHASE_ID,)),)

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state, phase
        return (SEAT,)

    def _shown(self, cw: rc.CWorld, offers: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [{"id": o["id"], "terms": o["contract"], "price": rc.show(cw, o["price"])} for o in offers]

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del phase
        cw, _ = world_of(family_case)
        return {
            "seat": seat,
            "brief": rc.brief(cw, self._shown(cw, listing(family_case))),
            "round": state["round"],
            "rounds": cw.w.rounds,
            "final": state["final"],
            "price_terms": "fee, hardware on top" if rc.fee_based(cw.playbook) else "all in",
            "standing_offers": self._shown(cw, state["offers"]),
            "history": state["history"],
            "allowed_actions": ["accept", "walk"] if state["final"] else list(ACTIONS),
        }

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del family_case, state, seat, phase
        return parse_contract_move(response)

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del family_case, seat, phase
        if state["finished"]:
            return LegalityResult.illegal("negotiation_over")
        if action["action"] in ("counter", "quote") and state["final"]:
            return LegalityResult.illegal("final_answer_only")
        if action["action"] == "accept" and action["offer"] not in {o["id"] for o in state["offers"]}:
            return LegalityResult.illegal("no_such_offer")
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
        cw, it = world_of(family_case)
        solver = rc.solver_for(family_case)
        t = solver.type_index(it)
        base = rc.BASES[cw.playbook]
        if act["action"] == "walk":
            new["decisions"].append({"kind": "walk", "contract": None, "price": None, "outside": act["outside"], "round": state["round"], "final": state["final"]})
            new.update(finished=True, termination="walked", outside=act["outside"])
            return TransitionResult(new, None, {"termination": "walked"})
        if act["action"] == "accept":
            offer = next(o for o in state["offers"] if o["id"] == act["offer"])
            new["decisions"].append({"kind": "accept", "contract": offer["contract"], "price": None, "outside": None, "round": state["round"], "final": state["final"]})
            new.update(finished=True, termination="signed", signed={"offer": offer["id"], "contract": offer["contract"], "price": offer["price"]})
            return TransitionResult(new, None, {"termination": "signed"})
        contract = rc.contract_from(act["terms"], base)
        price = None if act["price"] is None else rc.all_in(cw, act["price"])
        new["decisions"].append({"kind": "propose", "contract": contract.as_dict(), "price": price, "outside": None, "round": state["round"], "final": state["final"]})
        ci = solver.index.get(contract)
        entry: dict[str, Any] = {"round": state["round"], "request": act["action"], "terms": contract.as_dict(), "your_price": act["price"]}
        if ci is None:
            new["declined"] += 1
            entry.update(answer="declined: that contract is not on its menu", their_price=None, offer=None)
        else:
            thr = float(solver.th[state["round"]][ci, t])
            if price is not None and price >= thr - 1e-6:
                new.update(finished=True, termination="signed", signed={"offer": None, "contract": contract.as_dict(), "price": price})
                return TransitionResult(new, None, {"termination": "signed"})
            ans = round(thr, 6)
            offer = next((o for o in new["offers"] if o["contract"] == contract.as_dict()), None)
            if offer is None:
                offer = {"id": f"O{new['next_offer']}", "contract": contract.as_dict(), "price": ans}
                new["offers"].append(offer)
                new["next_offer"] += 1
            offer["price"] = ans
            unit = "fee" if rc.fee_based(cw.playbook) else "all in"
            entry.update(answer=f"would sign at {rc.show(cw, ans):,.1f} ({unit}) this round, standing offer {offer['id']}",
                         their_price=rc.show(cw, ans), offer=offer["id"])
        new["refused"] += 1
        new["history"].append(entry)
        if family_case["breakoff_draws"][state["round"] - 1] < cw.w.terms.breakoff:
            new.update(finished=True, termination="broke_off")
        elif state["round"] == cw.w.rounds:
            new["final"] = True
        else:
            new["round"] = state["round"] + 1
        return TransitionResult(new, None if new["finished"] else PHASE_ID, {"termination": new["termination"]})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return json.loads(json.dumps(_thaw(state))) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        g = rc.grade(family_case, terminal["decisions"], terminal["signed"], terminal["outside"], terminal["termination"], terminal["refused"])
        g["invalid"] = terminal.get("invalid")
        g["declined_requests"] = terminal.get("declined", 0)
        return {"termination": terminal["termination"], "signed": terminal["signed"], "invalid": terminal.get("invalid"), "grade": g}

    def build_scorer(self, family_case) -> ContractsScorer:
        return ContractsScorer(family_case)

    def build_reference_providers(self, family_case):
        del family_case
        return ()

    def generator(self, family_case=None):
        del family_case
        return None


__all__ = ["ACTION_SCHEMA", "FAMILY_ID", "FAMILY_VERSION", "ContractsPlugin", "PHASE_ID", "PLUGIN_ID", "STRICT_ACTION_SCHEMA",
           "contracts_family_manifest", "listing", "parse_contract_move", "world_of"]
