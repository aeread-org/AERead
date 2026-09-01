"""Versioned V1/V2 power, EPC, land, service, and loan negotiation plugins."""

from __future__ import annotations

import copy
import dataclasses
import json
from typing import Any, Mapping

from aeread.shared_runner.execution import CanonicalResponse
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .cashflow import ProjectFacts
from .contracts import (
    AgreementTerms,
    ContractOffer,
    ContractSignature,
    EpcAgreement,
    ExecutedAgreement,
    LandAgreement,
    LoanAgreement,
    PowerAgreement,
    ServiceAgreement,
    apply_executed_amendment,
    execute_offer,
    make_offer,
)
from .measurement import DataCenterDevelopmentScorer
from .stack_cashflow import simulate_development_stack


FAMILY_ID = "datacenter_development_v1"
SCORER_ID = "datacenter_development_score_set_v1"

SCOPE_CONFIG = {
    "v1": {
        "family_version": "1.1.0",
        "plugin_id": "datacenter_development_environment_v1",
        "sequence": ("power", "epc", "service", "loan"),
    },
    "v2": {
        "family_version": "2.0.0",
        "plugin_id": "datacenter_development_environment_v2",
        "sequence": (
            "land",
            "power",
            "epc",
            "service",
            "land_amendment",
            "loan",
        ),
    },
}

COUNTERPART_BY_KEY = {
    "land": "landowner",
    "land_amendment": "landowner",
    "power": "utility",
    "epc": "contractor",
    "service": "customer",
    "loan": "lender",
}
AGREEMENT_TYPE_BY_KEY = {
    **{key: key for key in ("land", "power", "epc", "service", "loan")},
    "land_amendment": "land",
}
TERM_PARSER_BY_TYPE = {
    "land": LandAgreement.from_dict,
    "power": PowerAgreement.from_dict,
    "epc": EpcAgreement.from_dict,
    "service": ServiceAgreement.from_dict,
    "loan": LoanAgreement.from_dict,
}


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _exact(value: Any, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    if set(value) != fields:
        raise ValueError(
            f"{path} fields differ: missing={sorted(fields - set(value))}, "
            f"unexpected={sorted(set(value) - fields)}"
        )
    return value


def _positive(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _terms(agreement_key: str, value: Any) -> AgreementTerms:
    agreement_type = AGREEMENT_TYPE_BY_KEY[agreement_key]
    return TERM_PARSER_BY_TYPE[agreement_type](value)


def _term_values(terms: AgreementTerms) -> dict[str, Any]:
    return dataclasses.asdict(terms)


def terms_acceptable(terms: AgreementTerms, policy: Mapping[str, Any]) -> bool:
    values = _term_values(terms)
    for field, minimum in policy["minimums"].items():
        if field not in values or values[field] < minimum:
            return False
    for field, maximum in policy["maximums"].items():
        if field not in values or values[field] > maximum:
            return False
    required = set(policy["required_conditions"])
    return required.issubset(set(values.get("conditions_precedent", ())))


def _phase_id(agreement_key: str, kind: str) -> str:
    if kind == "offer":
        return f"{agreement_key}_developer_offer"
    if kind == "response":
        return f"{agreement_key}_{COUNTERPART_BY_KEY[agreement_key]}_response"
    if kind == "commit":
        return f"{agreement_key}_developer_commit"
    raise ValueError(f"unknown phase kind: {kind}")


def phase_ids(scope_version: str) -> tuple[str, ...]:
    sequence = SCOPE_CONFIG[scope_version]["sequence"]
    return tuple(
        _phase_id(key, kind)
        for key in sequence
        for kind in ("offer", "response", "commit")
    )


def stack_family_manifest(scope_version: str) -> FamilyManifest:
    config = SCOPE_CONFIG[scope_version]
    roles = {"developer": {"testable": True, "scripted_policies": ["scripted"]}}
    for counterpart in sorted(
        {COUNTERPART_BY_KEY[key] for key in config["sequence"]}
    ):
        roles[counterpart] = {
            "testable": False,
            "scripted_policies": ["controlled"],
        }
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": config["family_version"],
                "plugin_id": config["plugin_id"],
            },
            "environment": {
                "topology": f"sequential_datacenter_agreement_stack_{scope_version}",
                "phase_specs": list(phase_ids(scope_version)),
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": roles,
            "measurement": {
                "primary_estimand": "developer_equity_npv",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "comparison_baseline": f"datacenter_scripted_developer_{scope_version}_baseline",
                "outcome_support": "case_specific_cents",
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "reference_provider_ids": [
                    "datacenter_measurement_validity_v1",
                    "datacenter_measurement_references_v1",
                ],
            },
        }
    )


def register_stack_plugin(
    registry: PluginRegistry,
    *,
    scope_version: str,
    plugin: "DataCenterStackPlugin | None" = None,
) -> "DataCenterStackPlugin":
    resolved = plugin or DataCenterStackPlugin(scope_version)
    registry.register(stack_family_manifest(scope_version), resolved)
    return resolved


def _make_offer(
    *,
    family_case: Mapping[str, Any],
    state: Mapping[str, Any],
    agreement_key: str,
    round_index: int,
    message: str,
    terms: AgreementTerms,
) -> ContractOffer:
    metadata: dict[str, Any] = {}
    if agreement_key == "land_amendment":
        prior = state["executed"].get("land")
        if prior is None:
            raise ValueError("land amendment requires an executed land agreement")
        metadata = {
            "supersedes_offer_id": prior["offer_id"],
            "amended_fields": family_case["scripted_developer"][
                "land_amendment_fields"
            ],
            "precedence_index": int(prior.get("precedence_index", 0)) + 1,
        }
    return make_offer(
        case_id=family_case["scenario_id"],
        agreement_type=AGREEMENT_TYPE_BY_KEY[agreement_key],
        proposer_seat_id="developer",
        round_index=round_index,
        message=message,
        terms=terms,
        **metadata,
    )


def _offer_from_dict(value: Mapping[str, Any]) -> ContractOffer:
    return make_offer(
        case_id=value["case_id"],
        agreement_type=value["agreement_type"],
        proposer_seat_id=value["proposer_seat_id"],
        round_index=value["round_index"],
        message=value["message"],
        terms=TERM_PARSER_BY_TYPE[value["agreement_type"]](value["terms"]),
        supersedes_offer_id=value.get("supersedes_offer_id"),
        amended_fields=value.get("amended_fields", ()),
        precedence_index=value.get("precedence_index", 0),
    )


def _executed_from_dict(value: Mapping[str, Any]) -> ExecutedAgreement:
    offer = _offer_from_dict({**value, "message": "replayed executed agreement"})
    return execute_offer(
        offer,
        tuple(ContractSignature(offer.offer_id, seat) for seat in value["signed_by"]),
        required_signers=value["signed_by"],
    )


def _baseline_stack(
    family_case: Mapping[str, Any], scope_version: str
) -> tuple[dict[str, ExecutedAgreement], Any]:
    state = {"executed": {}}
    executed: dict[str, ExecutedAgreement] = {}
    for agreement_key in SCOPE_CONFIG[scope_version]["sequence"]:
        terms = _terms(
            agreement_key,
            family_case["scripted_developer"][f"{agreement_key}_terms"],
        )
        offer = _make_offer(
            family_case=family_case,
            state=state,
            agreement_key=agreement_key,
            round_index=0,
            message=f"validated {agreement_key} baseline",
            terms=terms,
        )
        counterpart = COUNTERPART_BY_KEY[agreement_key]
        agreement = execute_offer(
            offer,
            (
                ContractSignature(offer.offer_id, "developer"),
                ContractSignature(offer.offer_id, counterpart),
            ),
            required_signers=("developer", counterpart),
        )
        if agreement_key == "land_amendment":
            apply_executed_amendment(executed["land"], agreement)
        executed[agreement_key] = agreement
        state["executed"][agreement_key] = _plain(agreement)
    land_key = "land_amendment" if "land_amendment" in executed else "land"
    outcome = simulate_development_stack(
        ProjectFacts.from_dict(family_case["project_facts"]),
        service_agreement=executed["service"],
        loan_agreement=executed["loan"],
        power_agreement=executed["power"],
        epc_agreement=executed["epc"],
        land_agreement=executed.get(land_key),
    )
    return executed, outcome


class DataCenterStackPlugin:
    """Generic versioned phase graph for V1 and V2 agreement stacks."""

    def __init__(self, scope_version: str) -> None:
        if scope_version not in SCOPE_CONFIG:
            raise ValueError("scope_version must be v1 or v2")
        self.scope_version = scope_version
        self.sequence = tuple(SCOPE_CONFIG[scope_version]["sequence"])

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        _exact(
            data,
            {
                "scope_version",
                "scenario_id",
                "project_facts",
                "negotiation",
                "policies",
                "scripted_developer",
                "outside_option",
                "baseline",
            },
            "payload",
        )
        if data["scope_version"] != self.scope_version:
            raise ValueError("payload scope_version does not match the plugin")
        if not isinstance(data["scenario_id"], str) or not data["scenario_id"]:
            raise ValueError("scenario_id must be non-empty")
        ProjectFacts.from_dict(data["project_facts"])
        negotiation = _exact(data["negotiation"], {"max_rounds"}, "negotiation")
        rounds = _exact(
            negotiation["max_rounds"], set(self.sequence), "negotiation.max_rounds"
        )
        for key, value in rounds.items():
            _positive(value, f"negotiation.max_rounds.{key}")
        policies = _exact(data["policies"], set(self.sequence), "policies")
        for key, value in policies.items():
            policy = _exact(
                value,
                {"minimums", "maximums", "required_conditions", "counter_terms"},
                f"policies.{key}",
            )
            if not isinstance(policy["minimums"], dict) or not isinstance(
                policy["maximums"], dict
            ):
                raise ValueError("policy minimums and maximums must be objects")
            if not isinstance(policy["required_conditions"], list):
                raise ValueError("policy required_conditions must be an array")
            _terms(key, policy["counter_terms"])
        scripted_fields = {f"{key}_terms" for key in self.sequence}
        if self.scope_version == "v2":
            scripted_fields.add("land_amendment_fields")
        scripted = _exact(data["scripted_developer"], scripted_fields, "scripted_developer")
        for key in self.sequence:
            terms = _terms(key, scripted[f"{key}_terms"])
            if not terms_acceptable(terms, policies[key]):
                raise ValueError(f"scripted {key} terms are not acceptable")
        if self.scope_version == "v2":
            fields = scripted["land_amendment_fields"]
            if not isinstance(fields, list) or not fields:
                raise ValueError("land_amendment_fields must be non-empty")

        _, outcome = _baseline_stack(data, self.scope_version)
        expected = {
            "developer_equity_npv_cents": outcome.developer_equity_npv_cents,
            "lender_npv_cents": outcome.lender_npv_cents,
            "customer_npv_cents": outcome.customer_npv_cents,
            "total_project_npv_cents": outcome.total_project_npv_cents,
        }
        if data["baseline"] != expected:
            raise ValueError(f"payload.baseline differs from stack simulation: {expected}")
        return data

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del family_case, run
        return {
            "finished": False,
            "termination_reason": None,
            "rounds": {key: 0 for key in self.sequence},
            "offers": [],
            "latest_offer_id": {key: None for key in self.sequence},
            "accepted_offer_id": {key: None for key in self.sequence},
            "pending_counter_terms": {key: None for key in self.sequence},
            "executed": {},
            "public_history": [],
            "temporal_violations": [],
        }

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        phases: list[PhaseSpec] = []
        for index, key in enumerate(self.sequence):
            counterpart = COUNTERPART_BY_KEY[key]
            maximum = family_case["negotiation"]["max_rounds"][key]
            next_key = self.sequence[index + 1] if index + 1 < len(self.sequence) else None
            phases.extend(
                (
                    PhaseSpec(
                        _phase_id(key, "offer"),
                        "developer",
                        "single",
                        {"developer": "datacenter_stack_developer_v1"},
                        {"developer": f"datacenter_{key}_offer_v1"},
                        maximum,
                        "family_defined",
                        (_phase_id(key, "response"),),
                    ),
                    PhaseSpec(
                        _phase_id(key, "response"),
                        counterpart,
                        "single",
                        {counterpart: f"datacenter_{counterpart}_v1"},
                        {counterpart: f"datacenter_{key}_response_v1"},
                        maximum,
                        "family_defined",
                        (_phase_id(key, "offer"), _phase_id(key, "commit")),
                    ),
                    PhaseSpec(
                        _phase_id(key, "commit"),
                        "developer",
                        "single",
                        {"developer": "datacenter_stack_developer_v1"},
                        {"developer": f"datacenter_{key}_commit_v1"},
                        1,
                        "family_defined",
                        (() if next_key is None else (_phase_id(next_key, "offer"),)),
                    ),
                )
            )
        return tuple(phases)

    def _phase_key(self, phase_id: str) -> str:
        return next(
            key
            for key in sorted(self.sequence, key=len, reverse=True)
            if phase_id.startswith(f"{key}_")
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state
        key = self._phase_key(phase.phase_id)
        return (
            (COUNTERPART_BY_KEY[key],)
            if phase.phase_id.endswith("_response")
            else ("developer",)
        )

    @staticmethod
    def _public_facts(family_case: Mapping[str, Any]) -> dict[str, Any]:
        facts = _plain(family_case["project_facts"])
        for field in (
            "customer_usage_kw_by_month",
            "customer_value_cents_per_kw_month",
            "customer_discount_rate_bps_annual",
        ):
            facts.pop(field, None)
        return facts

    def _latest(self, state: Mapping[str, Any], key: str) -> dict[str, Any] | None:
        offer_id = state["latest_offer_id"][key]
        if offer_id is None:
            return None
        return next(_plain(item) for item in state["offers"] if item["offer_id"] == offer_id)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        key = self._phase_key(phase.phase_id)
        observation = {
            "scope_version": self.scope_version,
            "scenario_id": family_case["scenario_id"],
            "phase_id": phase.phase_id,
            "agreement_key": key,
            "project_facts": self._public_facts(family_case),
            "public_history": _plain(state["public_history"]),
            "latest_offer": self._latest(state, key),
            "executed_agreements": _plain(state["executed"]),
        }
        if seat == "developer":
            observation.update(
                {
                    "accepted_offer_id": state["accepted_offer_id"][key],
                    "pending_counter_terms": _plain(
                        state["pending_counter_terms"][key]
                    ),
                }
            )
        else:
            observation["private_policy"] = _plain(family_case["policies"][key])
            if seat == "customer":
                observation["private_demand"] = {
                    "usage_kw_by_month": _plain(
                        family_case["project_facts"]["customer_usage_kw_by_month"]
                    ),
                    "value_cents_per_kw_month": family_case["project_facts"][
                        "customer_value_cents_per_kw_month"
                    ],
                }
        return observation

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del family_case, state, seat
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        if not isinstance(value, dict):
            return ParseResult.failure("malformed_action")
        key = self._phase_key(phase.phase_id)
        try:
            if phase.phase_id.endswith("_offer"):
                _exact(value, {"decision", "message", "terms"}, "offer_action")
                if value["decision"] == "walk" and value["message"] is None and value["terms"] is None:
                    return ParseResult.success({"decision": "walk"})
                if value["decision"] != "offer" or not isinstance(value["message"], str) or not value["message"].strip():
                    raise ValueError("malformed offer")
                terms = _terms(key, value["terms"])
                return ParseResult.success({"decision": "offer", "message": value["message"], "terms": _plain(terms)})
            if phase.phase_id.endswith("_response"):
                _exact(value, {"decision", "offer_id", "message", "terms"}, "response_action")
                if value["decision"] in {"accept", "reject"} and isinstance(value["offer_id"], str) and value["terms"] is None:
                    return ParseResult.success({"decision": value["decision"], "offer_id": value["offer_id"], "message": value["message"]})
                if value["decision"] == "counter" and isinstance(value["offer_id"], str) and isinstance(value["message"], str):
                    terms = _terms(key, value["terms"])
                    return ParseResult.success({"decision": "counter", "offer_id": value["offer_id"], "message": value["message"], "terms": _plain(terms)})
                raise ValueError("malformed response")
            if phase.phase_id.endswith("_commit"):
                _exact(value, {"decision", "offer_id"}, "commit_action")
                if value["decision"] in {"sign", "walk"} and isinstance(value["offer_id"], str):
                    return ParseResult.success(dict(value))
        except (ValueError, TypeError):
            return ParseResult.failure("malformed_datacenter_stack_action")
        return ParseResult.failure("unknown_phase")

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del seat
        key = self._phase_key(phase.phase_id)
        if action["decision"] == "walk":
            return LegalityResult.legal_action()
        if phase.phase_id.endswith("_offer"):
            if state["rounds"][key] >= family_case["negotiation"]["max_rounds"][key]:
                return LegalityResult.illegal("round_limit_exhausted")
            return LegalityResult.legal_action()
        if phase.phase_id.endswith("_response"):
            if action["offer_id"] != state["latest_offer_id"][key]:
                return LegalityResult.illegal("stale_or_unknown_offer")
            if action["decision"] == "accept":
                offer = next(
                    _offer_from_dict(item)
                    for item in state["offers"]
                    if item["offer_id"] == action["offer_id"]
                )
                if not terms_acceptable(offer.terms, family_case["policies"][key]):
                    return LegalityResult.illegal("controlled_policy_rejects_offer")
            return LegalityResult.legal_action()
        if phase.phase_id.endswith("_commit"):
            if action["offer_id"] != state["accepted_offer_id"][key]:
                return LegalityResult.illegal("unaccepted_offer")
            return LegalityResult.legal_action()
        return LegalityResult.illegal("unknown_phase")

    def step(self, family_case, state, phase, actions) -> TransitionResult:
        next_state = _plain(state)
        key = self._phase_key(phase.phase_id)
        seat = self.eligible_actors(family_case, state, phase)[0]
        envelope = actions[seat]
        if not envelope.valid:
            code = envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
            next_state["finished"] = True
            next_state["termination_reason"] = "invalid_action"
            next_state["temporal_violations"].append(str(code))
            return TransitionResult(next_state, None, {"valid": False, "failure_code": code})
        action = envelope.action
        if action["decision"] in {"walk", "reject"}:
            next_state["finished"] = True
            next_state["termination_reason"] = f"{seat}_{action['decision']}"
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": action["decision"], "offer_id": action.get("offer_id")})
            return TransitionResult(next_state, None, {"valid": True, "decision": action["decision"]})
        if phase.phase_id.endswith("_offer"):
            offer = _make_offer(
                family_case=family_case,
                state=next_state,
                agreement_key=key,
                round_index=next_state["rounds"][key],
                message=action["message"],
                terms=_terms(key, action["terms"]),
            )
            next_state["rounds"][key] += 1
            next_state["offers"].append(_plain(offer))
            next_state["latest_offer_id"][key] = offer.offer_id
            next_state["pending_counter_terms"][key] = None
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": "offer", "offer_id": offer.offer_id, "terms": _plain(offer.terms), "message": offer.message, "supersedes_offer_id": offer.supersedes_offer_id, "amended_fields": list(offer.amended_fields)})
            return TransitionResult(next_state, _phase_id(key, "response"), {"valid": True, "offer_id": offer.offer_id})
        if phase.phase_id.endswith("_response"):
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": action["decision"], "offer_id": action["offer_id"], "message": action.get("message")})
            if action["decision"] == "accept":
                next_state["accepted_offer_id"][key] = action["offer_id"]
                next_phase = _phase_id(key, "commit")
            else:
                next_state["pending_counter_terms"][key] = _plain(action["terms"])
                if (
                    next_state["rounds"][key]
                    >= family_case["negotiation"]["max_rounds"][key]
                ):
                    next_state["finished"] = True
                    next_state["termination_reason"] = (
                        f"{key}_negotiation_rounds_exhausted"
                    )
                    next_phase = None
                else:
                    next_phase = _phase_id(key, "offer")
            return TransitionResult(next_state, next_phase, {"valid": True, "decision": action["decision"]})

        offer = next(
            _offer_from_dict(item)
            for item in next_state["offers"]
            if item["offer_id"] == action["offer_id"]
        )
        counterpart = COUNTERPART_BY_KEY[key]
        executed = execute_offer(
            offer,
            (
                ContractSignature(offer.offer_id, counterpart),
                ContractSignature(offer.offer_id, "developer"),
            ),
            required_signers=("developer", counterpart),
        )
        if key == "land_amendment":
            apply_executed_amendment(
                _executed_from_dict(next_state["executed"]["land"]), executed
            )
        next_state["executed"][key] = _plain(executed)
        next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": "sign", "offer_id": offer.offer_id})
        index = self.sequence.index(key)
        if index + 1 == len(self.sequence):
            next_state["finished"] = True
            next_state["termination_reason"] = "agreement_stack_executed"
            return TransitionResult(next_state, None, {"valid": True, "executed_offer_id": offer.offer_id})
        next_key = self.sequence[index + 1]
        return TransitionResult(next_state, _phase_id(next_key, "offer"), {"valid": True, "executed_offer_id": offer.offer_id})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return _plain(state) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        completed = all(key in terminal["executed"] for key in self.sequence)
        result = {
            "scope_version": self.scope_version,
            "project_completed": completed,
            "termination_reason": terminal["termination_reason"],
            "public_history": _plain(terminal["public_history"]),
            "temporal_violations": _plain(terminal["temporal_violations"]),
            "binding_contract_integrity": False,
            "project_constraints_satisfied": False,
            "amendment_precedence_valid": self.scope_version != "v2",
            "developer_equity_npv_cents": family_case["outside_option"]["developer_equity_npv_cents"],
            "lender_npv_cents": family_case["outside_option"]["lender_npv_cents"],
            "customer_npv_cents": family_case["outside_option"]["customer_npv_cents"],
            "total_project_npv_cents": family_case["outside_option"]["total_project_npv_cents"],
            "project_outcome": None,
        }
        if not completed:
            return result
        executed = {
            key: _executed_from_dict(value)
            for key, value in terminal["executed"].items()
        }
        amendment_valid = True
        if self.scope_version == "v2":
            apply_executed_amendment(executed["land"], executed["land_amendment"])
        land_key = "land_amendment" if self.scope_version == "v2" else "land"
        stack = simulate_development_stack(
            ProjectFacts.from_dict(family_case["project_facts"]),
            service_agreement=executed["service"],
            loan_agreement=executed["loan"],
            power_agreement=executed["power"],
            epc_agreement=executed["epc"],
            land_agreement=executed.get(land_key),
        )
        result.update(
            {
                "binding_contract_integrity": True,
                "project_constraints_satisfied": stack.negotiated_constraints_satisfied,
                "amendment_precedence_valid": amendment_valid,
                "developer_equity_npv_cents": stack.developer_equity_npv_cents,
                "lender_npv_cents": stack.lender_npv_cents,
                "customer_npv_cents": stack.customer_npv_cents,
                "total_project_npv_cents": stack.total_project_npv_cents,
                "project_outcome": _plain(stack),
            }
        )
        return result

    def build_scorer(self, family_case) -> DataCenterDevelopmentScorer:
        return DataCenterDevelopmentScorer(family_case)

    def build_reference_providers(self, family_case) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case=None) -> None:
        del family_case
        return None


__all__ = [
    "COUNTERPART_BY_KEY",
    "DataCenterStackPlugin",
    "FAMILY_ID",
    "SCORER_ID",
    "SCOPE_CONFIG",
    "phase_ids",
    "register_stack_plugin",
    "stack_family_manifest",
    "terms_acceptable",
]
