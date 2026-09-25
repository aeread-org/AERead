"""The risk-allocation negotiation as a shared-runner environment.

One phase, one seat. The model plays the client or the integrator
(:mod:`.risk_allocation`); the counterpart is scripted and answers inside
``step``. Every move is one of three actions, and a proposal is always the full
package with a price, which is the shape that parsed reliably on the stack
(re-sending the full package succeeded 9 of 10 times against 5 of 10 for
acceptance by reference):

    {"action": "propose", "package": {"warranty": ..., "readiness": ..., "consequential": ..., "deposit": ...},
     "price": <number, or null to ask the counterpart for its price>, "reason": "..."}
    {"action": "accept", "reason": "..."}   # the standing offer
    {"action": "walk", "reason": "..."}     # the outside option

The counterpart's private type lives in the payload and never in an
observation. Break-off after a refusal is decided by a uniform draw stored in
the case, so every model meets the same luck in the same world. The score is
decision regret on the model's own information (:func:`grade`), which the draw
does not enter.
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
from .risk_allocation_measurement import REFERENCE_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID, RiskAllocationScorer

FAMILY_ID = "datacenter_risk_allocation_v1"
FAMILY_VERSION = "0.1.0"
PLUGIN_ID = "datacenter_risk_allocation_environment_v1"
SCORER_ID = "datacenter_risk_allocation_decision_regret_v1"  # = risk_allocation_measurement.SCORER_IMPLEMENTATION_ID
PHASE_ID = "negotiate"
OBSERVATION_SCHEMA = "datacenter_risk_allocation_observation_v1"
ACTION_SCHEMA = "datacenter_risk_allocation_action_v1"
VISIBILITY_POLICY = "datacenter_risk_allocation_public_risks_private_counterpart_costs_v1"
TERMINATIONS = ("signed", "walked", "broke_off", "invalid_action")
PAYLOAD_FIELDS = {"seat", "world", "integrator_type", "breakoff_draws"}
# Opt-in: 2 lets a price request name an alternate package (the two-prices
# protocol). Absent means one package per request, so earlier cases are unchanged.
OPTIONAL_PAYLOAD_FIELDS = {"packages_per_request"}
ACTIONS = ("propose", "accept", "walk")

ACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action", "package", "price", "reason"],
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "package": {
            "type": ["object", "null"],
            "description": "the full package when proposing, else null",
            "properties": {k: {"type": "string", "enum": list(v)} for k, v in ra.TERMS.items()},
            "required": list(ra.TERMS),
        },
        "price": {"type": ["number", "null"], "description": "$ thousands; null asks the counterpart for its price"},
        "reason": {"type": "string", "description": "one or two sentences"},
    },
}


_PACKAGE_SCHEMA = {
    "type": ["object", "null"],
    "properties": {k: {"type": "string", "enum": list(v)} for k, v in ra.TERMS.items()},
    "required": list(ra.TERMS),
}
ACTION_JSON_SCHEMA_ALTERNATES: dict[str, Any] = {
    "type": "object",
    "required": ["action", "package", "price", "alternate", "reason"],
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "package": {**_PACKAGE_SCHEMA, "description": "the full package when proposing; when accepting one of two standing offers, the package you accept; else null"},
        "price": {"type": ["number", "null"], "description": "$ thousands; null asks the counterpart for its price"},
        "alternate": {**_PACKAGE_SCHEMA, "description": "only with price null: a second package to be priced in the same answer; else null"},
        "reason": {"type": "string", "description": "one or two sentences"},
    },
}


def _strict(schema: Mapping[str, Any]) -> dict[str, Any]:
    """The same action shape inside the strict JSON subset the kernel sends (every
    object closed and fully required; a nullable object as anyOf with null). The
    probe schemas above stay as they were sent."""
    package = {
        "type": "object",
        "additionalProperties": False,
        "required": list(ra.TERMS),
        "properties": {k: {"type": "string", "enum": list(v)} for k, v in ra.TERMS.items()},
    }
    props: dict[str, Any] = {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "package": {"anyOf": [package, {"type": "null"}]},
        "price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    }
    if "alternate" in schema["properties"]:
        props["alternate"] = {"anyOf": [package, {"type": "null"}]}
    props["reason"] = {"type": "string"}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


STRICT_ACTION_SCHEMA = _strict(ACTION_JSON_SCHEMA)
STRICT_ACTION_SCHEMA_ALTERNATES = _strict(ACTION_JSON_SCHEMA_ALTERNATES)


def alternates_of(payload: Mapping[str, Any]) -> bool:
    return payload.get("packages_per_request", 1) == 2


def risk_allocation_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
            "environment": {
                "topology": "single_seat_scripted_counterpart_v1",
                "phase_specs": [PHASE_ID],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {seat: {"testable": True, "scripted_policies": ["reference"]} for seat in ra.SEATS},
            "measurement": {
                "primary_estimand": "decision_regret_usd_thousands",
                "measurement_kind": "property_or_answer",
                "direction": "minimize",
                "comparison_baseline": "best_play_on_own_information",
                "outcome_support": "nonnegative_real",
            },
            "scoring": {"scorer_id": SCORER_ID, "reference_provider_ids": [VALIDITY_IMPLEMENTATION_ID, REFERENCE_IMPLEMENTATION_ID]},
        }
    )


# ---------------------------------------------------------------------------


def _thaw(value: Any) -> Any:
    """The scheduler freezes actions into read-only mappings and tuples; state stays plain JSON."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def game_of(payload: Mapping[str, Any]) -> tuple[ra.Game, Any]:
    """The seat's game and the counterpart's true type."""
    w = ra.world_from_dict(payload["world"])
    it = ra.IntegratorType(**payload["integrator_type"])
    alternates = alternates_of(payload)
    if payload["seat"] == "client":
        return ra.Game(w, "client", alternates=alternates), it
    return ra.Game(w, "integrator", it, alternates=alternates), w.client.risk_charge


def _package(value: Any) -> ra.Package:
    if not isinstance(value, Mapping) or set(value) != set(ra.TERMS):
        raise ValueError("bad_package")
    for k, levels in ra.TERMS.items():
        if value[k] not in levels:
            raise ValueError("bad_package")
    return ra.Package(**{k: value[k] for k in ra.TERMS})


def _plain_offer(standing: tuple[ra.Package, float] | None) -> dict[str, Any] | None:
    return None if standing is None else {"package": standing[0].as_dict(), "price": round(standing[1], 3)}


def seen_of(payload: Mapping[str, Any], state: Mapping[str, Any], upto: int | None = None) -> ra.Seen:
    """What the model knew before its decision number `upto` (default: now), as the reference reads it."""
    game, other = game_of(payload)
    seen = ra.start(game, other)
    decisions = state["decisions"] if upto is None else state["decisions"][:upto]
    for d in decisions:
        a = _action(d["action"])
        if a.kind != "propose":
            break
        result, nxt, _ = ra.advance(game, seen, a, other)
        if result != "refused":
            break
        seen = nxt
    return seen


def _action(value: Mapping[str, Any]) -> ra.Action:
    if value["action"] == "accept" and value.get("package") is not None:
        return ra.Action("accept", package=_package(value["package"]))
    if value["action"] != "propose":
        return ra.Action(value["action"])
    price = ra.PRICE_IT if value["price"] is None else float(value["price"])
    alternate = value.get("alternate")
    return ra.Action("propose", _package(value["package"]), price, None if alternate is None else _package(alternate))


class RiskAllocationPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or not PAYLOAD_FIELDS <= set(payload) <= PAYLOAD_FIELDS | OPTIONAL_PAYLOAD_FIELDS:
            raise ValueError(f"payload fields must be {sorted(PAYLOAD_FIELDS)}, optionally {sorted(OPTIONAL_PAYLOAD_FIELDS)}")
        if "packages_per_request" in payload and payload["packages_per_request"] != 2:
            raise ValueError("packages_per_request is 2 when present; one package per request is the default")
        if payload["seat"] not in ra.SEATS:
            raise ValueError("unknown seat")
        w = ra.world_from_dict(payload["world"])
        it = ra.IntegratorType(**payload["integrator_type"])
        if it not in {t for t, _ in w.prior}:
            raise ValueError("the integrator's type is not in the declared prior")
        if w.client.risk_charge not in {c for c, _ in w.client_prior}:
            raise ValueError("the client's risk charge is not in the declared prior")
        draws = payload["breakoff_draws"]
        if len(draws) != w.rounds or not all(isinstance(u, float) and 0.0 <= u < 1.0 for u in draws):
            raise ValueError("one uniform break-off draw per round is required")
        return json.loads(json.dumps(payload))

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del run
        game, other = game_of(family_case)
        opening = game.opening(other)
        return {
            "round": 1,
            "final": False,
            "standing": _plain_offer(opening),
            "opening_price": None if opening is None else round(opening[1], 3),
            "history": [],
            "decisions": [],
            "finished": False,
            "termination": None,
            "signed": None,
            "invalid": None,
            **({"alternate_offer": None} if alternates_of(family_case) else {}),
        }

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        seat = family_case["seat"]
        rounds = ra.world_from_dict(family_case["world"]).rounds
        return (
            PhaseSpec(PHASE_ID, seat, "single", {seat: OBSERVATION_SCHEMA}, {seat: ACTION_SCHEMA}, rounds + 1, "family_defined", (PHASE_ID,)),
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del state, phase
        return (family_case["seat"],)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del phase
        game, _ = game_of(family_case)
        extra = {"alternate_offer": state["alternate_offer"]} if alternates_of(family_case) else {}
        return {
            **extra,
            "seat": seat,
            "brief": ra.brief_text(game, state["opening_price"]),
            "round": state["round"],
            "rounds": game.w.rounds,
            "final": state["final"],
            "standing_offer": state["standing"],
            "history": state["history"],
            "allowed_actions": ["accept", "walk"] if state["final"] else [a for a in ACTIONS if a != "accept" or state["standing"]],
        }

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del state, seat, phase
        alternates = alternates_of(family_case)
        if isinstance(response, CanonicalResponse):
            if response.truncated:
                # Cut off by the declared output limit: the reply never finished, so it is
                # typed on its own and the analysis counts it as missingness (DC-O-08).
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
        kind = value["action"]
        if kind not in ACTIONS:
            return ParseResult.failure("unknown_action")
        reason = value.get("reason")
        alt = value.get("alternate")
        if alt is not None and not alternates:
            return ParseResult.failure("alternate_not_offered")
        extra = {"alternate": None} if alternates else {}
        if kind != "propose":
            if alt is not None or value.get("price") is not None:
                return ParseResult.failure("terms_on_a_non_proposal")
            if value.get("package") is not None:
                if not (alternates and kind == "accept"):
                    return ParseResult.failure("terms_on_a_non_proposal")
                try:
                    chosen = _package(value["package"]).as_dict()
                except ValueError:
                    return ParseResult.failure("bad_package")
                return ParseResult.success({"action": "accept", "package": chosen, "price": None, **extra, "reason": reason})
            return ParseResult.success({"action": kind, "package": None, "price": None, **extra, "reason": reason})
        try:
            pkg = _package(value.get("package"))
        except ValueError:
            return ParseResult.failure("bad_package")
        price = value.get("price")
        if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0):
            return ParseResult.failure("bad_price")
        if alt is not None:
            if price is not None:
                return ParseResult.failure("alternate_needs_price_request")
            try:
                alt_pkg = _package(alt)
            except ValueError:
                return ParseResult.failure("bad_package")
            if alt_pkg == pkg:
                return ParseResult.failure("alternate_same_as_package")
            extra = {"alternate": alt_pkg.as_dict()}
        return ParseResult.success({"action": "propose", "package": pkg.as_dict(), "price": None if price is None else float(price), **extra, "reason": reason})

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del family_case, seat, phase
        if state["finished"]:
            return LegalityResult.illegal("negotiation_over")
        if action["action"] == "accept" and state["standing"] is None:
            return LegalityResult.illegal("nothing_to_accept")
        if action["action"] == "accept" and state.get("alternate_offer") is not None:
            offers = [state["standing"]["package"], state["alternate_offer"]["package"]]
            if action.get("package") is None:
                return LegalityResult.illegal("choose_an_offer")
            if dict(action["package"]) not in offers:
                return LegalityResult.illegal("no_such_offer")
        elif action["action"] == "accept" and action.get("package") is not None and dict(action["package"]) != state["standing"]["package"]:
            return LegalityResult.illegal("no_such_offer")
        if action["action"] == "propose" and state["final"]:
            return LegalityResult.illegal("final_answer_only")
        return LegalityResult.legal_action()

    def step(self, family_case, state, phase, actions) -> TransitionResult:
        del phase
        seat = family_case["seat"]
        envelope = actions[seat]
        new = json.loads(json.dumps(state))
        if not envelope.valid:
            reason = envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
            new.update(finished=True, termination="invalid_action", invalid=reason)
            return TransitionResult(new, None, {"termination": "invalid_action", "invalid": reason})
        act = _thaw(envelope.action)
        new["decisions"].append({"round": state["round"], "final": state["final"], "action": act})
        game, other = game_of(family_case)
        if act["action"] == "walk":
            new.update(finished=True, termination="walked")
        elif act["action"] == "accept":
            chosen = state["standing"]
            if act.get("package") is not None and state.get("alternate_offer") is not None and act["package"] == state["alternate_offer"]["package"]:
                chosen = state["alternate_offer"]
            new.update(finished=True, termination="signed", signed=chosen)
        else:
            a = _action(act)
            thr = game.threshold(a.package, other, state["round"])
            if a.price != ra.PRICE_IT and game.signs(a.price, thr):
                new.update(finished=True, termination="signed", signed={"package": a.package.as_dict(), "price": a.price})
            else:
                side = "or any higher price" if seat == "client" else "or any lower price"
                entry = {
                    "round": state["round"], "you_proposed": a.package.as_dict(), "your_price": act["price"],
                    "answer": f"would sign this package at {thr:,.1f} ({side}) in round {state['round']}",
                    "their_price": round(thr, 3),
                }
                alt_offer = None
                if a.alternate is not None:
                    alt = game.threshold(a.alternate, other, state["round"])
                    entry.update(alternate=a.alternate.as_dict(), alternate_answer=f"would sign the alternate at {alt:,.1f} ({side}) in round {state['round']}",
                                 their_alternate_price=round(alt, 3))
                    alt_offer = {"package": a.alternate.as_dict(), "price": round(alt, 3)}
                new["history"].append(entry)
                if family_case["breakoff_draws"][state["round"] - 1] < game.w.terms.breakoff:
                    new.update(finished=True, termination="broke_off")
                else:
                    new["standing"] = {"package": a.package.as_dict(), "price": round(thr, 3)}
                    if "alternate_offer" in new:
                        new["alternate_offer"] = alt_offer
                    if state["round"] == game.w.rounds:
                        new["final"] = True
                    else:
                        new["round"] = state["round"] + 1
        return TransitionResult(new, None if new["finished"] else PHASE_ID, {"termination": new["termination"]})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return json.loads(json.dumps(state)) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        return {"termination": terminal["termination"], "signed": terminal["signed"], "invalid": terminal.get("invalid"),
                "grade": grade(family_case, terminal)}

    # The kernel's remaining hooks: the scorer over `grade`, no external reference
    # provider (the reference is computed from the case), no generator at run time.
    def build_scorer(self, family_case) -> RiskAllocationScorer:
        return RiskAllocationScorer(family_case)

    def build_reference_providers(self, family_case):
        del family_case
        return ()

    def generator(self, family_case=None):
        del family_case
        return None


# ---------------------------------------------------------------------------


def grade(payload: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    """Decision regret on the model's own information, and three diagnostics against the true types.

    Every amount is in $ thousands. An invalid action ends the episode and is
    typed missingness for the score; the decisions before it are still graded.

    - allocation_gap: joint value lost against the best outcome for the true types,
      the efficient package or no deal, whichever is better (0 when walking was
      right; the whole surplus when a deal existed and none was signed).
    - price_gap: in the client seat, what was paid above the integrator's floor for
      that package; in the integrator seat, what was left below the client's
      final bid.
    - refused_rounds: proposals refused, each costing the round cost and a break-off risk.
    """
    game, other = game_of(payload)
    solver = ra.Solver(game)
    per: list[dict[str, Any]] = []
    for i, d in enumerate(state["decisions"]):
        seen = seen_of(payload, state, upto=i)
        a = _action(d["action"])
        per.append({"round": d["round"], "final": d["final"], "action": a.label(), "regret": round(ra.decision_regret(game, seen, a, solver), 6)})
    w = game.w
    it = ra.IntegratorType(**payload["integrator_type"])
    eff = ra.efficient_package(w, it)
    best_joint = ra.joint_cost(eff, w, it)
    # With no deal the client pays turnkey and the integrator earns its margin elsewhere,
    # so a deal creates value only if its joint cost is below turnkey less that margin.
    no_deal = w.client.turnkey_all_in - w.terms.floor_margin
    surplus = no_deal - best_joint
    signed = state["signed"]
    if signed is not None:
        pkg = ra.Package(**signed["package"])
        allocation_gap = ra.joint_cost(pkg, w, it) - min(best_joint, no_deal)
        if game.seat == "client":
            price_gap = signed["price"] - ra.floor_price(pkg, w, it)
        else:
            price_gap = ra.client_bid(pkg, w, it, w.client.risk_charge, w.rounds) - signed["price"]
    else:
        allocation_gap = max(surplus, 0.0)
        price_gap = None
    proposed = [d["action"]["package"] for d in state["decisions"] if d["action"]["action"] == "propose"]
    first = ra.Package(**proposed[0]).label() if proposed else None
    return {
        "valid": state["termination"] != "invalid_action",
        "termination": state["termination"],
        "invalid": state.get("invalid"),
        "decision_regret": round(math.fsum(p["regret"] for p in per), 6),
        "decisions": per,
        "signed_package": None if signed is None else ra.Package(**signed["package"]).label(),
        "efficient_package": eff.label(),
        "deal_surplus": round(surplus, 3),
        "allocation_gap": round(allocation_gap, 3),
        "price_gap": None if price_gap is None else round(price_gap, 3),
        "refused_rounds": len(state["history"]),
        "first_proposed_package": first,
        "switched_package": bool(signed is not None and first is not None and ra.Package(**signed["package"]).label() != first),
    }


__all__ = [
    "ACTION_JSON_SCHEMA",
    "ACTION_JSON_SCHEMA_ALTERNATES",
    "STRICT_ACTION_SCHEMA",
    "STRICT_ACTION_SCHEMA_ALTERNATES",
    "alternates_of",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "PLUGIN_ID",
    "RiskAllocationPlugin",
    "game_of",
    "grade",
    "risk_allocation_family_manifest",
    "seen_of",
]
