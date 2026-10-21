"""Pay or test, version 3: the procurement environment with unanswered quotes and a source lookup.

Version 3 (``docs/families/procurement-allocation/pay_or_test_v3_plan.md``) changes what a buyer can do, so it is a
new plugin under a new family version rather than an edit: ``environment.py`` is hashed into every sealed procurement
plan and receipt, and is subclassed here, not touched. What changes, each declared in the case:

- **A newcomer may not answer a quote request.** Each request to a listing without a marketplace record is answered
  with the probability ``policy.newcomer_quote_answer_probability``; an unanswered request costs its fee and its day
  and shows nothing. Whether the k-th request to a listing is answered is a pure function of the case's
  ``interaction.reply_seed``, the listing and k, so a trajectory replays exactly. A listing with a record always
  answers. Samples are orders, not requests, and always arrive.
- **The buyer can look up a listing's source.** ``look_up_source`` reads the listing's business registration and
  returns the factory that makes its boards (``private_terms.source_factory``), for the fee and days the case states.
  Newcomers of one kind that share a source name the same factory; otherwise each names its own.
- **Inquiry and counter-offers are gone.** Under every version 2 world they could only lose: every seller claims what
  a good one would, and every quote is final. The buyer is not offered them, and an attempt is an unknown action.
- **The buyer sees only what can matter.** The cash budget, which never binds, and the financing terms, which are zero,
  are not shown. Shipping is folded into each listed price.

Everything else is version 1's code path: offers, samples, the award check and its evaluation, the full-information
bound (which assumes every quote is answered, so it stays an upper bound) and the outcome.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.measurement import ImplementationRef, MeasurementLeafSpec, ScoreEnvelope
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.evaluation import FamilyScoringInput
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import ParseResult, TransitionResult

from . import environment as v1
from .environment import (
    ProcurementAllocationPlugin,
    _exact_fields,
    _finite_number,
    _plain,
    _positive_int,
    _supplier_by_id,
    _text,
    _validate_payload,
    procurement_allocation_measurement_leaf,
    stated_listing,
)

FAMILY_ID = v1.FAMILY_ID
FAMILY_VERSION = "1.1.0"
PLUGIN_ID = "procurement_pay_or_test_v3_environment"
SCORER_ID = "procurement_pay_or_test_v3_contribution_margin_scorer"
ACTION_TYPES = frozenset({"request_quote", "request_sample", "look_up_source", "submit_award", "check_award", "defer"})
ACTION_FIELDS = {
    "request_quote": frozenset({"action", "supplier_id", "message"}),
    "request_sample": frozenset({"action", "supplier_id", "message"}),
    "look_up_source": frozenset({"action", "supplier_id"}),
    "submit_award": frozenset({"action", "award_lines"}),
    "check_award": frozenset({"action", "award_lines"}),
    "defer": frozenset({"action", "reason"}),
}
WIRE_ACTION_FIELDS = frozenset().union(*ACTION_FIELDS.values())
#: What version 1's validator requires for the actions version 3 does not offer. They are filled in for validation
#: only, with values under which a counter can never pay (every seller's floor is its quoted price), and never shown.
_INERT_INTERACTION = {"inquiry_days": 1, "inquiry_cost_usd": 0.0, "counter_days": 1, "counter_cost_usd": 0.0}
_INERT_POLICY = {"inquiry_fields": ["exact_variant"]}
#: What the buyer is not shown: terms that never bind or are zero in version 3.
_HIDDEN_OBJECTIVE = frozenset({"cash_budget_usd", "annual_financing_rate", "working_capital_horizon_days"})
V3_INTERACTION = frozenset({"reply_seed", "source_lookup_days", "source_lookup_cost_usd"})
V3_POLICY = frozenset({"newcomer_quote_answer_probability"})
SOURCE_FIELD = "source_factory"
_SOURCES = (Path(__file__), Path(v1.__file__))


def source_digest() -> str:
    """This module's bytes and the version 1 environment's, which it extends: one digest for both."""
    digest = hashlib.sha256()
    for path in _SOURCES:
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def quote_answered(seed: int, supplier_id: str, request_index: int, probability: float) -> bool:
    """Whether the ``request_index``-th quote request (0-based) to a listing is answered.

    A uniform draw from the case's seed, the listing and the request's ordinal, so the same trajectory always meets
    the same replies, and each request is an independent draw with the stated probability as the buyer sees it.
    """
    if probability >= 1.0:
        return True
    digest = hashlib.sha256(f"pay_or_test_v3_reply:{seed}:{supplier_id}:{request_index}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < probability


def _is_newcomer(supplier: Mapping[str, Any]) -> bool:
    return int(supplier["listing"]["marketplace_record"].get("orders_reported") or 0) == 0


def _split(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    """(version 1's view, version 3's interaction fields, its policy fields, each supplier's source factory)."""
    data = _plain(payload)
    interaction, policy = data.get("interaction"), data.get("policy")
    if not isinstance(interaction, dict) or not isinstance(policy, dict):
        raise ValueError("interaction and policy must be objects")
    for key in ("inquiry_days", "inquiry_cost_usd", "counter_days", "counter_cost_usd", "counter_feedback", "sample_noise"):
        if key in interaction:
            raise ValueError(f"interaction.{key} belongs to an action or mode version 3 does not offer")
    if "inquiry_fields" in policy:
        raise ValueError("policy.inquiry_fields belongs to an action version 3 does not offer")
    if not V3_INTERACTION <= set(interaction) or not V3_POLICY <= set(policy):
        raise ValueError("version 3 needs interaction.reply_seed, source lookup terms and the answer probability")
    v3_interaction = {key: interaction.pop(key) for key in V3_INTERACTION}
    v3_policy = {key: policy.pop(key) for key in V3_POLICY}
    interaction.update(_INERT_INTERACTION)
    policy.update(_INERT_POLICY)
    sources = {}
    for supplier in data.get("suppliers") or []:
        terms = supplier.get("private_terms") if isinstance(supplier, dict) else None
        if not isinstance(terms, dict) or SOURCE_FIELD not in terms:
            raise ValueError("every supplier's private terms must name its source_factory")
        sources[supplier.get("supplier_id")] = _text(terms.pop(SOURCE_FIELD), "private_terms.source_factory")
    return data, v3_interaction, v3_policy, sources


def version1_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The payload as version 1's code reads it: version 3's fields removed, the inert ones filled in."""
    return _split(payload)[0]


def validate_v3_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Version 1's validation on the payload with the inert fields filled in, then version 3's own fields."""
    view, v3_interaction, v3_policy, sources = _split(payload)
    validated = _validate_payload(view)
    _positive_int(v3_interaction["reply_seed"], "interaction.reply_seed")
    _positive_int(v3_interaction["source_lookup_days"] + 1, "interaction.source_lookup_days")  # zero days allowed
    _finite_number(v3_interaction["source_lookup_cost_usd"], "interaction.source_lookup_cost_usd", minimum=0.0)
    probability = _finite_number(v3_policy["newcomer_quote_answer_probability"],
                                 "policy.newcomer_quote_answer_probability", minimum=0.0)
    if not 0.0 < probability <= 1.0:
        raise ValueError("policy.newcomer_quote_answer_probability must lie in (0, 1]")
    for supplier in validated["suppliers"]:
        floor = supplier["private_terms"].get("negotiation", {}).get("floor_unit_price_usd")
        if floor is not None and float(floor) < float(supplier["private_terms"]["base_unit_price_usd"]) - 1e-9:
            raise ValueError("version 3 offers no counter, so a seller's floor must be its quoted price")
        supplier["private_terms"][SOURCE_FIELD] = sources[supplier["supplier_id"]]
    validated["interaction"].update(v3_interaction)
    validated["policy"].update(v3_policy)
    return validated


def public_policy(family_case: Mapping[str, Any]) -> dict[str, Any]:
    """The policy as the buyer reads it: version 1's inert inquiry list removed, the lookup's terms added."""
    policy = {k: v for k, v in _plain(family_case["policy"]).items() if k not in _INERT_POLICY}
    interaction = family_case["interaction"]
    process = dict(policy.get("process") or {})
    for key in ("inquiry_fee_usd", "inquiry_days", "counter_fee_usd", "counter_days"):
        process.pop(key, None)
    process.update({"source_lookup_fee_usd": interaction["source_lookup_cost_usd"],
                    "source_lookup_days": interaction["source_lookup_days"]})
    policy["process"] = process
    return policy


def family_manifest() -> FamilyManifest:
    """Version 1's manifest (``environment.family_manifest``) under version 3's identity and scorer."""
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
            "environment": {"topology": "interactive_supplier_qualification_and_award", "phase_specs": [v1.PHASE_ID],
                            "needs_tools": False, "needs_sandbox": False},
            "roles": {"buyer": {"testable": True, "scripted_policies": ["scripted"]}},
            "measurement": {
                "primary_estimand": "buyer_contribution_margin", "measurement_kind": "optimizable_outcome",
                "direction": "maximize", "optimum_lower_bound": "defer_value_usd",
                "optimum_upper_bound": "full_information_enumeration", "optimum_upper_bound_kind": "certified",
                "bound_status": "case_computed", "outcome_support": "real_valued_usd",
            },
            "scoring": {"scorer_id": SCORER_ID, "oracle_id": "procurement_full_information_upper_bound_v1"},
        }
    )


def register_plugin(registry: PluginRegistry, *, plugin: "PayOrTestV3Plugin | None" = None) -> "PayOrTestV3Plugin":
    resolved = plugin or PayOrTestV3Plugin()
    registry.register_trusted(family_manifest(), resolved)
    return resolved


def measurement_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Version 1's leaf, bound to this module's bytes as well as version 1's, under version 3's scorer id."""
    leaf = procurement_allocation_measurement_leaf(family_case)
    digest = source_digest()
    domain = replace(leaf.estimand.validity_domain, predicate=ImplementationRef(SCORER_ID, "1.0.0", digest))
    verifier = leaf.verifier
    reference = replace(verifier.reference, implementation=replace(verifier.reference.implementation, content_sha256=digest))
    scope = replace(
        verifier.objective_scope, validity_domain=domain,
        information_set=("buyer-visible listings and acquired offers, samples and source records; reference relaxes "
                         "supplier-term information and assumes every quote is answered while charging required actions"),
        feasible_set=("unexpired formal offers with verified samples, exact variants and MOQ/capacity/order-step "
                      "compliance, and minimum service"),
    )
    return replace(leaf, estimand=replace(leaf.estimand, validity_domain=domain),
                   verifier=replace(verifier, reference=reference, objective_scope=scope),
                   scorer=ImplementationRef(SCORER_ID, "1.0.0", digest))


@dataclass(frozen=True, slots=True)
class PayOrTestV3Scorer:
    family_case: Mapping[str, Any]

    def __call__(self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()) -> ScoreEnvelope:
        scored = v1.ProcurementAllocationMeasurementScorer(self.family_case)(scoring_input, evidence_refs=evidence_refs)
        leaf = measurement_leaf(self.family_case)
        return ScoreEnvelope(status=scored.status, leaf=leaf, primary=scored.primary, metrics=scored.metrics,
                             reference_values=scored.reference_values, validity=scored.validity,
                             evidence_refs=scored.evidence_refs)


class PayOrTestV3Plugin(ProcurementAllocationPlugin):
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = validate_v3_payload(payload)
        upper = v1.solve_full_information_upper_bound(data)
        if upper.contribution_margin_usd <= data["objective"]["defer_value_usd"]:
            raise ValueError("development case requires a positive ordering upper bound")
        return data

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        state = super().initial_state(family_case, run)
        state.update({"quote_requests": {}, "unanswered_quotes": {}, "source_records": {}})
        return state

    def observe(self, family_case: Mapping[str, Any], state: Mapping[str, Any], seat: str, phase: Any) -> dict[str, Any]:
        del seat, phase
        return {
            "objective": {k: v for k, v in _plain(family_case["objective"]).items() if k not in _HIDDEN_OBJECTIVE},
            "policy": public_policy(family_case),
            "supplier_listings": [
                {"supplier_id": s["supplier_id"], "component": s["component"], "listing": stated_listing(s)}
                for s in family_case["suppliers"]
            ],
            "actions_left": family_case["interaction"]["max_actions"] - state["actions_used"],
            "elapsed_days": state["elapsed_days"],
            "information_cost_usd": state["information_cost_usd"],
            "conversation": _plain(state["conversation"]),
            "formal_offers": _plain(state["offers"]),
            "unanswered_quote_requests": _plain(state["unanswered_quotes"]),
            "verified_samples": _plain(state["quality_evidence"]),
            "source_records": _plain(state["source_records"]),
            "award_checks": _plain(state["award_checks"]),
        }

    def parse_action(self, family_case: Mapping[str, Any], state: Mapping[str, Any], seat: str, phase: Any,
                     response: Any) -> ParseResult:
        # Read the response exactly as version 1 does, then project it onto version 3's actions.
        raw: Any
        if isinstance(response, CanonicalResponse):
            raw = response.action if isinstance(response.action, Mapping) else None
            if raw is None:
                try:
                    raw = json.loads(response.text)
                except (TypeError, json.JSONDecodeError):
                    return ParseResult.failure("malformed_json")
        elif isinstance(response, str):
            try:
                raw = json.loads(response)
            except (TypeError, json.JSONDecodeError):
                return ParseResult.failure("malformed_json")
        elif isinstance(response, Mapping):
            raw = response
        else:
            return ParseResult.failure("noncanonical_response")
        raw = _plain(raw)
        if not isinstance(raw, dict) or raw.get("action") not in ACTION_TYPES:
            return ParseResult.failure("unknown_procurement_action")
        if set(raw) - WIRE_ACTION_FIELDS - v1.WIRE_ACTION_FIELDS:
            return ParseResult.failure("malformed_procurement_action")
        if raw["action"] == "look_up_source":
            projected = {k: v for k, v in raw.items() if k in ACTION_FIELDS["look_up_source"]}
            try:
                data = _exact_fields(projected, set(ACTION_FIELDS["look_up_source"]), "action")
                _text(data["supplier_id"], "action.supplier_id")
            except ValueError:
                return ParseResult.failure("malformed_procurement_action")
            if data["supplier_id"] not in _supplier_by_id(family_case):
                return ParseResult.failure("unknown_supplier")
            return ParseResult.success(data)
        # Fields of version 1's other actions (a strict superset object may carry them as nulls) are dropped first.
        projected = {k: v for k, v in raw.items() if k in ACTION_FIELDS[raw["action"]]}
        return super().parse_action(family_case, state, seat, phase, projected)

    def legal(self, family_case: Mapping[str, Any], state: Mapping[str, Any], seat: str, phase: Any,
              action: Mapping[str, Any]) -> Any:
        return super().legal(family_case, state, seat, phase, action)

    def step(self, family_case: Mapping[str, Any], state: Mapping[str, Any], phase: Any, actions: Mapping[str, Any]) -> Any:
        envelope = actions["buyer"]
        if not envelope.valid or state["done"]:
            return super().step(family_case, state, phase, actions)
        action = _plain(envelope.action)
        kind = action["action"]
        interaction, policy = family_case["interaction"], family_case["policy"]
        if kind == "look_up_source":
            next_state = _plain(state)
            next_state["actions_used"] += 1
            next_state["elapsed_days"] += int(interaction["source_lookup_days"])
            next_state["information_cost_usd"] = round(next_state["information_cost_usd"]
                                                       + float(interaction["source_lookup_cost_usd"]), 8)
            supplier = _supplier_by_id(family_case)[action["supplier_id"]]
            factory = supplier["private_terms"][SOURCE_FIELD]
            next_state["source_records"][action["supplier_id"]] = {"source_factory": factory,
                                                                   "day": next_state["elapsed_days"]}
            next_state["conversation"].append({"role": "registry", "supplier_id": action["supplier_id"],
                                               "content": f"Registered source of {action['supplier_id']}: {factory}."})
            return TransitionResult(state=next_state, next_phase_id=None if self._spent(family_case, next_state) else v1.PHASE_ID,
                                    consequences={"action": kind, "source_factory": factory})
        if kind == "request_quote":
            supplier = _supplier_by_id(family_case)[action["supplier_id"]]
            requests = dict(state.get("quote_requests") or {})
            index = int(requests.get(action["supplier_id"], 0))
            answered = not _is_newcomer(supplier) or quote_answered(
                int(interaction["reply_seed"]), action["supplier_id"], index,
                float(policy["newcomer_quote_answer_probability"]))
            if not answered:
                next_state = _plain(state)
                next_state["actions_used"] += 1
                next_state["elapsed_days"] += interaction["quote_days"]
                next_state["information_cost_usd"] = round(next_state["information_cost_usd"]
                                                           + interaction["quote_cost_usd"], 8)
                next_state["quote_requests"][action["supplier_id"]] = index + 1
                next_state["unanswered_quotes"][action["supplier_id"]] = (
                    int(next_state["unanswered_quotes"].get(action["supplier_id"], 0)) + 1)
                next_state["conversation"].extend([
                    {"role": "buyer", "content": action["message"]},
                    {"role": "supplier", "supplier_id": action["supplier_id"], "content": "(no reply)"},
                ])
                return TransitionResult(state=next_state,
                                        next_phase_id=None if self._spent(family_case, next_state) else v1.PHASE_ID,
                                        consequences={"action": kind, "answered": False})
            result = super().step(family_case, state, phase, actions)
            result.state["quote_requests"][action["supplier_id"]] = index + 1
            return result
        return super().step(family_case, state, phase, actions)

    @staticmethod
    def _spent(family_case: Mapping[str, Any], state: dict[str, Any]) -> bool:
        """Version 1's budget rule: the episode ends when the action budget is spent."""
        if state["actions_used"] >= int(family_case["interaction"]["max_actions"]):
            state["done"] = True
            state["termination_reason"] = "interaction_budget_exhausted"
            return True
        return False

    def build_scorer(self, family_case: Mapping[str, Any]) -> PayOrTestV3Scorer:
        return PayOrTestV3Scorer(family_case)


def action_output_schema() -> dict[str, Any]:
    """One strict root object, as version 1's (``runner.procurement_action_output_schema``), with version 3's actions."""
    nullable_text = {"type": ["string", "null"]}
    line = {"type": "object", "properties": {"offer_id": {"type": "string"}, "quantity": {"type": "integer"}},
            "required": ["offer_id", "quantity"], "additionalProperties": False}
    properties = {
        "action": {"type": "string", "enum": sorted(ACTION_TYPES)},
        "supplier_id": nullable_text,
        "message": nullable_text,
        "award_lines": {"type": ["array", "null"], "items": line},
        "reason": nullable_text,
    }
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


__all__ = [
    "ACTION_TYPES", "FAMILY_ID", "FAMILY_VERSION", "PLUGIN_ID", "SCORER_ID", "SOURCE_FIELD", "PayOrTestV3Plugin",
    "PayOrTestV3Scorer", "action_output_schema", "family_manifest", "measurement_leaf", "public_policy",
    "quote_answered", "register_plugin", "source_digest", "validate_v3_payload", "version1_view",
]
