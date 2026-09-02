"""Six-phase data-center service-and-loan negotiation environment."""

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

from .cashflow import ProjectFacts, simulate_project
from .contracts import (
    ContractOffer,
    ContractSignature,
    LoanAgreement,
    ServiceAgreement,
    execute_offer,
    make_offer,
)
from .measurement import DataCenterDevelopmentScorer


FAMILY_ID = "datacenter_development_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "datacenter_development_environment"
SCORER_ID = "datacenter_development_score_set_v1"

SERVICE_DEVELOPER_OFFER = "service_developer_offer"
SERVICE_CUSTOMER_RESPONSE = "service_customer_response"
SERVICE_DEVELOPER_COMMIT = "service_developer_commit"
LOAN_DEVELOPER_OFFER = "loan_developer_offer"
LOAN_LENDER_RESPONSE = "loan_lender_response"
LOAN_DEVELOPER_COMMIT = "loan_developer_commit"
PHASE_IDS = (
    SERVICE_DEVELOPER_OFFER,
    SERVICE_CUSTOMER_RESPONSE,
    SERVICE_DEVELOPER_COMMIT,
    LOAN_DEVELOPER_OFFER,
    LOAN_LENDER_RESPONSE,
    LOAN_DEVELOPER_COMMIT,
)


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


def _positive_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _terms_for(agreement_type: str, value: Any) -> ServiceAgreement | LoanAgreement:
    if agreement_type == "service":
        return ServiceAgreement.from_dict(value)
    if agreement_type == "loan":
        return LoanAgreement.from_dict(value)
    raise ValueError(f"unknown agreement type: {agreement_type}")


def _offer_from_state(value: Mapping[str, Any]) -> ContractOffer:
    terms = _terms_for(str(value["agreement_type"]), value["terms"])
    offer = make_offer(
        case_id=str(value["case_id"]),
        agreement_type=str(value["agreement_type"]),
        proposer_seat_id=str(value["proposer_seat_id"]),
        round_index=int(value["round_index"]),
        message=str(value["message"]),
        terms=terms,
    )
    if offer.offer_id != value["offer_id"]:
        raise ValueError("stored offer ID does not bind its written terms")
    return offer


def _find_offer(state: Mapping[str, Any], offer_id: str) -> ContractOffer:
    for raw in state["offers"]:
        if raw["offer_id"] == offer_id:
            return _offer_from_state(raw)
    raise ValueError(f"offer is absent from state: {offer_id}")


def _service_acceptable(terms: ServiceAgreement, policy: Mapping[str, Any]) -> bool:
    return (
        terms.committed_capacity_kw >= policy["minimum_capacity_kw"]
        and terms.monthly_capacity_charge_cents_per_kw
        <= policy["maximum_capacity_charge_cents_per_kw"]
        and terms.take_or_pay_bps <= policy["maximum_take_or_pay_bps"]
        and terms.credit_support_cents <= policy["maximum_credit_support_cents"]
        and terms.delay_damages_cents_per_month
        >= policy["minimum_delay_damages_cents_per_month"]
    )


def _loan_acceptable(
    terms: LoanAgreement,
    service: ServiceAgreement,
    policy: Mapping[str, Any],
) -> bool:
    return (
        terms.maximum_commitment_cents >= policy["minimum_commitment_cents"]
        and terms.advance_rate_bps <= policy["maximum_advance_rate_bps"]
        and terms.spread_bps >= policy["minimum_spread_bps"]
        and terms.minimum_dscr_bps >= policy["minimum_dscr_bps"]
        and terms.maximum_loan_to_cost_bps <= policy["maximum_loan_to_cost_bps"]
        and terms.maximum_loan_to_value_bps <= policy["maximum_loan_to_value_bps"]
        and terms.maturity_month <= policy["maximum_maturity_month"]
        and service.committed_capacity_kw >= terms.minimum_contracted_capacity_kw
        and service.take_or_pay_bps >= terms.minimum_take_or_pay_bps
        and service.credit_support_cents
        >= terms.minimum_customer_credit_support_cents
    )


def _public_project_facts(family_case: Mapping[str, Any]) -> dict[str, Any]:
    facts = _plain(family_case["project_facts"])
    for private_field in (
        "customer_usage_kw_by_month",
        "customer_value_cents_per_kw_month",
        "customer_discount_rate_bps_annual",
    ):
        facts.pop(private_field, None)
    return facts


def family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "sequential_project_agreement_negotiation",
                "phase_specs": list(PHASE_IDS),
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "developer": {"testable": True, "scripted_policies": ["scripted"]},
                "customer": {"testable": False, "scripted_policies": ["controlled"]},
                "lender": {"testable": False, "scripted_policies": ["controlled"]},
            },
            "measurement": {
                "primary_estimand": "developer_equity_npv",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "comparison_baseline": "datacenter_scripted_developer_baseline_v1",
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


def register_plugin(
    registry: PluginRegistry, *, plugin: "DataCenterDevelopmentPlugin | None" = None
) -> "DataCenterDevelopmentPlugin":
    resolved = plugin or DataCenterDevelopmentPlugin()
    registry.register_trusted(family_manifest(), resolved)
    return resolved


class DataCenterDevelopmentPlugin:
    """Family hooks for binding service and construction-loan negotiations."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        fields = {
            "scenario_id",
            "project_facts",
            "negotiation",
            "customer_policy",
            "lender_policy",
            "scripted_developer",
            "outside_option",
            "baseline",
        }
        _exact(data, fields, "payload")
        if not isinstance(data["scenario_id"], str) or not data["scenario_id"]:
            raise ValueError("payload.scenario_id must be non-empty")
        facts = ProjectFacts.from_dict(data["project_facts"])
        negotiation = _exact(
            data["negotiation"],
            {"max_service_rounds", "max_loan_rounds"},
            "payload.negotiation",
        )
        _positive_integer(negotiation["max_service_rounds"], "max_service_rounds")
        _positive_integer(negotiation["max_loan_rounds"], "max_loan_rounds")

        customer_fields = {
            "minimum_capacity_kw",
            "maximum_capacity_charge_cents_per_kw",
            "maximum_take_or_pay_bps",
            "maximum_credit_support_cents",
            "minimum_delay_damages_cents_per_month",
            "counter_terms",
        }
        lender_fields = {
            "minimum_commitment_cents",
            "maximum_advance_rate_bps",
            "minimum_spread_bps",
            "minimum_dscr_bps",
            "maximum_loan_to_cost_bps",
            "maximum_loan_to_value_bps",
            "maximum_maturity_month",
            "counter_terms",
        }
        customer_policy = _exact(data["customer_policy"], customer_fields, "customer_policy")
        lender_policy = _exact(data["lender_policy"], lender_fields, "lender_policy")
        scripted = _exact(
            data["scripted_developer"],
            {"service_terms", "loan_terms"},
            "scripted_developer",
        )
        service = ServiceAgreement.from_dict(scripted["service_terms"])
        loan = LoanAgreement.from_dict(scripted["loan_terms"])
        ServiceAgreement.from_dict(customer_policy["counter_terms"])
        LoanAgreement.from_dict(lender_policy["counter_terms"])
        if not _service_acceptable(service, customer_policy):
            raise ValueError("scripted service terms must be acceptable to the customer")
        if not _loan_acceptable(loan, service, lender_policy):
            raise ValueError("scripted loan terms must be acceptable to the lender")

        service_offer = make_offer(
            case_id=data["scenario_id"],
            agreement_type="service",
            proposer_seat_id="developer",
            round_index=0,
            message="validated baseline service offer",
            terms=service,
        )
        loan_offer = make_offer(
            case_id=data["scenario_id"],
            agreement_type="loan",
            proposer_seat_id="developer",
            round_index=0,
            message="validated baseline loan offer",
            terms=loan,
        )
        service_executed = execute_offer(
            service_offer,
            (
                ContractSignature(service_offer.offer_id, "developer"),
                ContractSignature(service_offer.offer_id, "customer"),
            ),
            required_signers=("developer", "customer"),
        )
        loan_executed = execute_offer(
            loan_offer,
            (
                ContractSignature(loan_offer.offer_id, "developer"),
                ContractSignature(loan_offer.offer_id, "lender"),
            ),
            required_signers=("developer", "lender"),
        )
        outcome = simulate_project(
            facts,
            service_agreement=service_executed,
            loan_agreement=loan_executed,
        )
        expected = {
            "developer_equity_npv_cents": outcome.developer_equity_npv_cents,
            "lender_npv_cents": outcome.lender_npv_cents,
            "customer_npv_cents": outcome.customer_npv_cents,
            "total_project_npv_cents": outcome.total_project_npv_cents,
        }
        if data["baseline"] != expected:
            raise ValueError(f"payload.baseline differs from simulation: {expected}")
        return data

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        del family_case, run
        return {
            "finished": False,
            "termination_reason": None,
            "service_round": 0,
            "loan_round": 0,
            "offers": [],
            "latest_service_offer_id": None,
            "latest_loan_offer_id": None,
            "service_accepted_offer_id": None,
            "loan_accepted_offer_id": None,
            "pending_service_counter_terms": None,
            "pending_loan_counter_terms": None,
            "executed_service": None,
            "executed_loan": None,
            "public_history": [],
            "temporal_violations": [],
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        service_rounds = family_case["negotiation"]["max_service_rounds"]
        loan_rounds = family_case["negotiation"]["max_loan_rounds"]
        return (
            PhaseSpec(SERVICE_DEVELOPER_OFFER, "developer", "single", {"developer": "datacenter_developer_v1"}, {"developer": "datacenter_service_offer_v1"}, service_rounds, "family_defined", (SERVICE_CUSTOMER_RESPONSE,)),
            PhaseSpec(SERVICE_CUSTOMER_RESPONSE, "customer", "single", {"customer": "datacenter_customer_v1"}, {"customer": "datacenter_service_response_v1"}, service_rounds, "family_defined", (SERVICE_DEVELOPER_OFFER, SERVICE_DEVELOPER_COMMIT)),
            PhaseSpec(SERVICE_DEVELOPER_COMMIT, "developer", "single", {"developer": "datacenter_developer_v1"}, {"developer": "datacenter_service_commit_v1"}, 1, "family_defined", (LOAN_DEVELOPER_OFFER,)),
            PhaseSpec(LOAN_DEVELOPER_OFFER, "developer", "single", {"developer": "datacenter_developer_v1"}, {"developer": "datacenter_loan_offer_v1"}, loan_rounds, "family_defined", (LOAN_LENDER_RESPONSE,)),
            PhaseSpec(LOAN_LENDER_RESPONSE, "lender", "single", {"lender": "datacenter_lender_v1"}, {"lender": "datacenter_loan_response_v1"}, loan_rounds, "family_defined", (LOAN_DEVELOPER_OFFER, LOAN_DEVELOPER_COMMIT)),
            PhaseSpec(LOAN_DEVELOPER_COMMIT, "developer", "single", {"developer": "datacenter_developer_v1"}, {"developer": "datacenter_loan_commit_v1"}, 1, "family_defined", ()),
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state
        if phase.phase_id in {SERVICE_DEVELOPER_OFFER, SERVICE_DEVELOPER_COMMIT, LOAN_DEVELOPER_OFFER, LOAN_DEVELOPER_COMMIT}:
            return ("developer",)
        if phase.phase_id == SERVICE_CUSTOMER_RESPONSE:
            return ("customer",)
        if phase.phase_id == LOAN_LENDER_RESPONSE:
            return ("lender",)
        raise ValueError(f"unknown phase: {phase.phase_id}")

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        common = {
            "scenario_id": family_case["scenario_id"],
            "phase_id": phase.phase_id,
            "project_facts": _public_project_facts(family_case),
            "public_history": _plain(state["public_history"]),
        }
        if seat == "developer":
            common.update(
                {
                    "latest_service_offer": self._latest(state, "service"),
                    "latest_loan_offer": self._latest(state, "loan"),
                    "service_accepted_offer_id": state["service_accepted_offer_id"],
                    "loan_accepted_offer_id": state["loan_accepted_offer_id"],
                    "pending_service_counter_terms": _plain(state["pending_service_counter_terms"]),
                    "pending_loan_counter_terms": _plain(state["pending_loan_counter_terms"]),
                    "executed_service": _plain(state["executed_service"]),
                }
            )
            return common
        if seat == "customer":
            common["latest_service_offer"] = self._latest(state, "service")
            common["private_policy"] = _plain(family_case["customer_policy"])
            common["private_demand"] = {
                "usage_kw_by_month": _plain(
                    family_case["project_facts"]["customer_usage_kw_by_month"]
                ),
                "value_cents_per_kw_month": family_case["project_facts"][
                    "customer_value_cents_per_kw_month"
                ],
                "discount_rate_bps_annual": family_case["project_facts"][
                    "customer_discount_rate_bps_annual"
                ],
            }
            return common
        if seat == "lender":
            common["latest_loan_offer"] = self._latest(state, "loan")
            common["executed_service"] = _plain(state["executed_service"])
            common["private_policy"] = _plain(family_case["lender_policy"])
            return common
        raise ValueError(f"unknown seat: {seat}")

    @staticmethod
    def _latest(state: Mapping[str, Any], agreement_type: str) -> dict[str, Any] | None:
        offer_id = state[f"latest_{agreement_type}_offer_id"]
        if offer_id is None:
            return None
        return next(_plain(item) for item in state["offers"] if item["offer_id"] == offer_id)

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
        try:
            if phase.phase_id in {SERVICE_DEVELOPER_OFFER, LOAN_DEVELOPER_OFFER}:
                _exact(value, {"decision", "message", "terms"}, "offer_action")
                if value["decision"] == "walk" and value["message"] is None and value["terms"] is None:
                    return ParseResult.success({"decision": "walk"})
                agreement_type = "service" if phase.phase_id == SERVICE_DEVELOPER_OFFER else "loan"
                if value["decision"] != "offer" or not isinstance(value["message"], str) or not value["message"].strip():
                    raise ValueError("malformed offer")
                terms = _terms_for(agreement_type, value["terms"])
                return ParseResult.success({"decision": "offer", "message": value["message"], "terms": _plain(terms)})
            if phase.phase_id in {SERVICE_CUSTOMER_RESPONSE, LOAN_LENDER_RESPONSE}:
                _exact(value, {"decision", "offer_id", "message", "terms"}, "response_action")
                if value["decision"] in {"accept", "reject"} and isinstance(value["offer_id"], str) and value["terms"] is None:
                    return ParseResult.success({"decision": value["decision"], "offer_id": value["offer_id"], "message": value["message"]})
                if value["decision"] == "counter" and isinstance(value["offer_id"], str) and isinstance(value["message"], str):
                    agreement_type = "service" if phase.phase_id == SERVICE_CUSTOMER_RESPONSE else "loan"
                    terms = _terms_for(agreement_type, value["terms"])
                    return ParseResult.success({"decision": "counter", "offer_id": value["offer_id"], "message": value["message"], "terms": _plain(terms)})
                raise ValueError("malformed response")
            if phase.phase_id in {SERVICE_DEVELOPER_COMMIT, LOAN_DEVELOPER_COMMIT}:
                _exact(value, {"decision", "offer_id"}, "commit_action")
                if value["decision"] in {"sign", "walk"} and isinstance(value["offer_id"], str):
                    return ParseResult.success(dict(value))
                raise ValueError("malformed commit")
        except (ValueError, TypeError):
            return ParseResult.failure("malformed_datacenter_action")
        return ParseResult.failure("unknown_phase")

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del seat
        decision = action["decision"]
        if decision == "walk":
            return LegalityResult.legal_action()
        if phase.phase_id in {SERVICE_DEVELOPER_OFFER, LOAN_DEVELOPER_OFFER}:
            agreement_type = "service" if phase.phase_id == SERVICE_DEVELOPER_OFFER else "loan"
            round_key = f"{agreement_type}_round"
            maximum = family_case["negotiation"][f"max_{agreement_type}_rounds"]
            if state[round_key] >= maximum:
                return LegalityResult.illegal("round_limit_exhausted")
            return LegalityResult.legal_action()
        if phase.phase_id in {SERVICE_CUSTOMER_RESPONSE, LOAN_LENDER_RESPONSE}:
            agreement_type = "service" if phase.phase_id == SERVICE_CUSTOMER_RESPONSE else "loan"
            if action["offer_id"] != state[f"latest_{agreement_type}_offer_id"]:
                return LegalityResult.illegal("stale_or_unknown_offer")
            offer = _find_offer(state, action["offer_id"])
            if decision == "accept":
                acceptable = (
                    _service_acceptable(offer.terms, family_case["customer_policy"])
                    if agreement_type == "service"
                    else _loan_acceptable(
                        offer.terms,
                        _terms_for("service", state["executed_service"]["terms"]),
                        family_case["lender_policy"],
                    )
                )
                if not acceptable:
                    return LegalityResult.illegal("controlled_policy_rejects_offer")
            return LegalityResult.legal_action()
        if phase.phase_id in {SERVICE_DEVELOPER_COMMIT, LOAN_DEVELOPER_COMMIT}:
            agreement_type = "service" if phase.phase_id == SERVICE_DEVELOPER_COMMIT else "loan"
            if action["offer_id"] != state[f"{agreement_type}_accepted_offer_id"]:
                return LegalityResult.illegal("unaccepted_offer")
            return LegalityResult.legal_action()
        return LegalityResult.illegal("unknown_phase")

    def step(self, family_case, state, phase, actions) -> TransitionResult:
        next_state = _plain(state)
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
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "decision": action["decision"], "offer_id": action.get("offer_id")})
            return TransitionResult(next_state, None, {"valid": True, "decision": action["decision"]})

        if phase.phase_id in {SERVICE_DEVELOPER_OFFER, LOAN_DEVELOPER_OFFER}:
            agreement_type = "service" if phase.phase_id == SERVICE_DEVELOPER_OFFER else "loan"
            round_key = f"{agreement_type}_round"
            offer = make_offer(
                case_id=family_case["scenario_id"], agreement_type=agreement_type,
                proposer_seat_id="developer", round_index=next_state[round_key],
                message=action["message"], terms=_terms_for(agreement_type, action["terms"]),
            )
            next_state[round_key] += 1
            next_state["offers"].append(_plain(offer))
            next_state[f"latest_{agreement_type}_offer_id"] = offer.offer_id
            next_state[f"pending_{agreement_type}_counter_terms"] = None
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "decision": "offer", "offer_id": offer.offer_id, "terms": _plain(offer.terms), "message": offer.message})
            next_phase = SERVICE_CUSTOMER_RESPONSE if agreement_type == "service" else LOAN_LENDER_RESPONSE
            return TransitionResult(next_state, next_phase, {"valid": True, "offer_id": offer.offer_id})

        if phase.phase_id in {SERVICE_CUSTOMER_RESPONSE, LOAN_LENDER_RESPONSE}:
            agreement_type = "service" if phase.phase_id == SERVICE_CUSTOMER_RESPONSE else "loan"
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "decision": action["decision"], "offer_id": action["offer_id"], "message": action.get("message")})
            if action["decision"] == "accept":
                next_state[f"{agreement_type}_accepted_offer_id"] = action["offer_id"]
                next_phase = SERVICE_DEVELOPER_COMMIT if agreement_type == "service" else LOAN_DEVELOPER_COMMIT
            else:
                next_state[f"pending_{agreement_type}_counter_terms"] = _plain(action["terms"])
                next_phase = SERVICE_DEVELOPER_OFFER if agreement_type == "service" else LOAN_DEVELOPER_OFFER
            return TransitionResult(next_state, next_phase, {"valid": True, "decision": action["decision"]})

        agreement_type = "service" if phase.phase_id == SERVICE_DEVELOPER_COMMIT else "loan"
        counterpart = "customer" if agreement_type == "service" else "lender"
        offer = _find_offer(next_state, action["offer_id"])
        executed = execute_offer(
            offer,
            (ContractSignature(offer.offer_id, counterpart), ContractSignature(offer.offer_id, "developer")),
            required_signers=("developer", counterpart),
        )
        next_state[f"executed_{agreement_type}"] = _plain(executed)
        next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "decision": "sign", "offer_id": offer.offer_id})
        if agreement_type == "service":
            return TransitionResult(next_state, LOAN_DEVELOPER_OFFER, {"valid": True, "executed_offer_id": offer.offer_id})
        next_state["finished"] = True
        next_state["termination_reason"] = "agreements_executed"
        return TransitionResult(next_state, None, {"valid": True, "executed_offer_id": offer.offer_id})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        if not state["finished"]:
            return None
        return _plain(state)

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        completed = terminal["executed_service"] is not None and terminal["executed_loan"] is not None
        result = {
            "project_completed": completed,
            "termination_reason": terminal["termination_reason"],
            "public_history": _plain(terminal["public_history"]),
            "temporal_violations": _plain(terminal["temporal_violations"]),
            "binding_contract_integrity": False,
            "project_constraints_satisfied": False,
            "developer_equity_npv_cents": family_case["outside_option"]["developer_equity_npv_cents"],
            "lender_npv_cents": family_case["outside_option"]["lender_npv_cents"],
            "customer_npv_cents": family_case["outside_option"]["customer_npv_cents"],
            "total_project_npv_cents": family_case["outside_option"]["total_project_npv_cents"],
            "project_outcome": None,
        }
        if not completed:
            return result
        service = _offer_from_state(terminal["executed_service"] | {"message": "executed service"})
        loan = _offer_from_state(terminal["executed_loan"] | {"message": "executed loan"})
        service_executed = execute_offer(service, (ContractSignature(service.offer_id, "customer"), ContractSignature(service.offer_id, "developer")), required_signers=("developer", "customer"))
        loan_executed = execute_offer(loan, (ContractSignature(loan.offer_id, "lender"), ContractSignature(loan.offer_id, "developer")), required_signers=("developer", "lender"))
        project = simulate_project(ProjectFacts.from_dict(family_case["project_facts"]), service_agreement=service_executed, loan_agreement=loan_executed)
        result.update(
            {
                "binding_contract_integrity": True,
                "project_constraints_satisfied": project.financing_succeeded and not project.defaulted,
                "developer_equity_npv_cents": project.developer_equity_npv_cents,
                "lender_npv_cents": project.lender_npv_cents,
                "customer_npv_cents": project.customer_npv_cents,
                "total_project_npv_cents": project.total_project_npv_cents,
                "project_outcome": _plain(project),
            }
        )
        return result

    def build_scorer(self, family_case: Mapping[str, Any]) -> DataCenterDevelopmentScorer:
        return DataCenterDevelopmentScorer(family_case)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any] | None = None) -> None:
        del family_case
        return None


__all__ = [
    "DataCenterDevelopmentPlugin",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "LOAN_DEVELOPER_COMMIT",
    "LOAN_DEVELOPER_OFFER",
    "LOAN_LENDER_RESPONSE",
    "PHASE_IDS",
    "PLUGIN_ID",
    "SCORER_ID",
    "SERVICE_CUSTOMER_RESPONSE",
    "SERVICE_DEVELOPER_COMMIT",
    "SERVICE_DEVELOPER_OFFER",
    "family_manifest",
    "register_plugin",
]
