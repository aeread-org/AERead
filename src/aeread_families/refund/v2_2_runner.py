"""Shared-runner adapter for the Refund V2.2 N:1 policy-seat pilot."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin, RunPlan, case_content_sha256, canonical_json_bytes, resolve_run_plan,
)
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, FamilyManifest, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.execution import ArenaChatClient, CellExecution, ProviderFailure, ProviderRequest, ProviderResult, TokenPricing, execute_plan_cell
from aeread.shared_runner.task.evaluation import finalize_family_execution, finalize_family_failure, replay_family_receipt
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult
from aeread.shared_runner.quality import FamilyContribution, HumanQCApproval, QCCoverage, QCEvidenceRef, ResourceLimits

from . import v2_2_measurement as measurement
from .v2_2_environment import RefundV22Batch, RefundV22Case, RefundV22State, build_n1_panel, verify_n1_trajectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROMPTS = {
    "policy": """You are the sole policy allocator for a shared refund batch. Request only the missing declared fact IDs for named customers, at most three facts per customer per request. Once all facts are disclosed, submit exactly one disposition for every customer. Approve only policy-eligible claims, with the policy-calculated amount and original_payment method; use deny_or_defer, 0, and none for all others. Respect the declared batch budget, execution capacity, and priority objective. Return one JSON object and no markdown.""",
    "customer": """You are a scripted customer counterpart. Reveal only the fact IDs requested for you. Confirm an approved refund; acknowledge any denial or deferral. Return one JSON object and no markdown.""",
    "payments": """You are the scripted payments executor. Execute the confirmed approved allocations exactly once and make no other mutation. Return one JSON object and no markdown.""",
}
POLICY_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["request_facts", "allocate"]}, "requested_by_customer": {"type": "object"}, "decisions": {"type": "array"}}, "required": ["decision"], "additionalProperties": False}
CUSTOMER_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["provide_info", "confirm", "acknowledge"]}, "reveal_fields": {"type": "array", "items": {"type": "string"}}}, "required": ["decision", "reveal_fields"], "additionalProperties": False}
PAYMENTS_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["execute_allocations"]}, "selected_customer_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["decision", "selected_customer_ids"], "additionalProperties": False}


def _json(response: Any) -> Mapping[str, Any] | None:
    try:
        value = json.loads(getattr(response, "text", response))
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _batch(payload: Mapping[str, Any]) -> RefundV22Batch:
    raw = payload.get("batch")
    if not isinstance(raw, Mapping):
        raise ValueError("Refund V2.2 payload has no batch")
    return RefundV22Batch(**{**dict(raw), "cases": tuple(RefundV22Case(**case) for case in raw["cases"])})


def _state(raw: Mapping[str, Any]) -> RefundV22State:
    values = {key: raw[key] for key in RefundV22State.__dataclass_fields__ if key in raw}
    for key in ("transactions", "transcript"):
        if isinstance(values.get(key), tuple):
            values[key] = [dict(item) if isinstance(item, Mapping) else item for item in values[key]]
    for key in ("revealed_facts", "decisions"):
        if isinstance(values.get(key), Mapping):
            values[key] = {str(item_key): dict(item) if isinstance(item, Mapping) else item for item_key, item in values[key].items()}
    if isinstance(values.get("invalid_requests"), tuple): values["invalid_requests"] = list(values["invalid_requests"])
    return RefundV22State(**values)


class RefundV22Plugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> RefundV22Batch:
        return _batch(payload)

    def initial_state(self, batch: RefundV22Batch, run: Any) -> dict[str, Any]:
        del run
        return {**asdict(RefundV22State(budget_remaining=batch.refund_budget)), "pending_requested": {}, "confirmations": []}

    def phases(self, batch: RefundV22Batch) -> tuple[PhaseSpec, ...]:
        del batch
        obs = {"policy": "refund_v22_observation", "customer": "refund_v22_customer_observation", "payments": "refund_v22_payments_observation"}
        actions = {"policy": "refund_v22_policy_action", "customer": "refund_v22_customer_action", "payments": "refund_v22_payments_action"}
        return (
            PhaseSpec("policy_request", "policy_only", "single", obs, actions, 3, "family_defined", ("customer_facts", "policy_allocate")),
            PhaseSpec("customer_facts", "customers", "simultaneous", obs, actions, 6, "family_defined", ("policy_request", "policy_allocate")),
            PhaseSpec("policy_allocate", "policy_only", "single", obs, actions, 1, "family_defined", ("customer_confirmation",)),
            PhaseSpec("customer_confirmation", "customers", "simultaneous", obs, actions, 3, "family_defined", ("payments_execute",)),
            PhaseSpec("payments_execute", "payments_only", "single", obs, actions, 1, "family_defined", ()),
        )

    def eligible_actors(self, batch: RefundV22Batch, state: Mapping[str, Any], phase: PhaseSpec) -> tuple[str, ...]:
        del batch, state
        if phase.phase_id in {"policy_request", "policy_allocate"}: return ("policy",)
        if phase.phase_id in {"customer_facts", "customer_confirmation"}: return ("customer_1", "customer_2", "customer_3")
        return ("payments",)

    def observe(self, batch: RefundV22Batch, state: Mapping[str, Any], seat: str, phase: PhaseSpec) -> Mapping[str, Any]:
        cases = {case.customer_id: case for case in batch.cases}
        if seat == "policy":
            return {"phase_id": phase.phase_id, "refund_budget": batch.refund_budget, "execution_capacity": batch.review_capacity, "customers": [{"customer_id": case.customer_id, "product_category": case.product_category, "price": case.price, "priority_basis": case.priority_basis, "priority": case.priority, "public_claim": case.public_claim, "policy_summary": case.policy_summary, "required_fact_ids": list(case.required_facts), "revealed_facts": state["revealed_facts"].get(case.customer_id, {})} for case in batch.cases]}
        if seat.startswith("customer_"):
            case = cases[seat]
            return {"phase_id": phase.phase_id, "customer_id": seat, "private_facts": dict(case.private_facts), "requested_fact_ids": state.get("pending_requested", {}).get(seat, []), "decision": state.get("decisions", {}).get(case.case_id)}
        return {"phase_id": phase.phase_id, "decisions": state.get("decisions", {}), "confirmations": state.get("confirmations", [])}

    def parse_action(self, batch: RefundV22Batch, state: Mapping[str, Any], seat: str, phase: PhaseSpec, response: Any) -> ParseResult:
        del batch, state, phase
        value = _json(response)
        if value is None: return ParseResult.failure("malformed_json")
        if seat == "policy" and value.get("decision") in {"request_facts", "allocate"}: return ParseResult.success(dict(value))
        if seat.startswith("customer_") and value.get("decision") in {"provide_info", "confirm", "acknowledge"} and isinstance(value.get("reveal_fields"), list): return ParseResult.success(dict(value))
        if seat == "payments" and value.get("decision") == "execute_allocations" and isinstance(value.get("selected_customer_ids"), list): return ParseResult.success(dict(value))
        return ParseResult.failure("invalid_action")

    def legal(self, batch: RefundV22Batch, state: Mapping[str, Any], seat: str, phase: PhaseSpec, action: Mapping[str, Any]) -> LegalityResult:
        cases = {case.customer_id: case for case in batch.cases}
        if seat == "policy" and phase.phase_id == "policy_request":
            requested = action.get("requested_by_customer", {})
            if action.get("decision") != "request_facts" or not isinstance(requested, Mapping) or not requested: return LegalityResult.illegal("missing_fact_request")
            for customer_id, fields in requested.items():
                if customer_id not in cases or not isinstance(fields, (list, tuple)) or not fields or len(fields) > 3: return LegalityResult.illegal("invalid_fact_batch")
                revealed = state["revealed_facts"].get(customer_id, {})
                if any(field not in cases[customer_id].required_facts or field in revealed for field in fields): return LegalityResult.illegal("unknown_or_repeated_fact")
        if seat.startswith("customer_") and phase.phase_id == "customer_facts":
            if action.get("decision") != "provide_info" or any(field not in state.get("pending_requested", {}).get(seat, []) for field in action["reveal_fields"]): return LegalityResult.illegal("customer_disclosed_unrequested_fact")
        if seat == "policy" and phase.phase_id == "policy_allocate":
            if action.get("decision") != "allocate" or any(set(case.required_facts) - set(state["revealed_facts"].get(case.customer_id, {})) for case in batch.cases): return LegalityResult.illegal("allocation_before_required_facts")
            decisions = action.get("decisions")
            if not isinstance(decisions, (list, tuple)) or {item.get("customer_id") for item in decisions if isinstance(item, Mapping)} != set(cases) or len(decisions) != len(cases): return LegalityResult.illegal("incomplete_batch_allocation")
        if seat == "payments":
            approved = [case.customer_id for case in batch.cases if state["decisions"].get(case.case_id, {}).get("decision") == "approve"]
            if list(action["selected_customer_ids"]) != approved or set(state.get("confirmations", ())) != set(approved): return LegalityResult.illegal("unconfirmed_or_mismatched_payment_batch")
        return LegalityResult.legal_action()

    def step(self, batch: RefundV22Batch, state: Mapping[str, Any], phase: PhaseSpec, actions: Mapping[str, Any]) -> TransitionResult:
        next_state = {key: value for key, value in state.items()}
        if any(not envelope.valid for envelope in actions.values()):
            next_state["invalid_requests"] = list(state["invalid_requests"]) + ["invalid_action"]
            next_state.update({"done": True, "phase": "finished"})
            return TransitionResult(next_state, None)
        if phase.phase_id == "policy_request":
            requested = dict(next(iter(actions.values())).action["requested_by_customer"])
            next_state["pending_requested"] = requested
            next_state["transcript"] = list(state["transcript"]) + [{"speaker": "policy", "message": "Requested bounded customer facts.", "requested_by_customer": requested}]
            return TransitionResult(next_state, "customer_facts")
        if phase.phase_id == "customer_facts":
            revealed = {key: dict(value) for key, value in state["revealed_facts"].items()}
            transcript = list(state["transcript"])
            for customer_id, envelope in actions.items():
                case = next(case for case in batch.cases if case.customer_id == customer_id)
                fields = list(envelope.action["reveal_fields"])
                revealed.setdefault(customer_id, {}).update({field: case.private_facts[field] for field in fields})
                transcript.append({"speaker": "customer", "customer_id": customer_id, "message": "Provided requested facts.", "revealed_fields": fields})
            next_state.update({"revealed_facts": revealed, "pending_requested": {}, "transcript": transcript})
            complete = all(set(case.required_facts) <= set(revealed.get(case.customer_id, {})) for case in batch.cases)
            return TransitionResult(next_state, "policy_allocate" if complete else "policy_request")
        if phase.phase_id == "policy_allocate":
            raw = next(iter(actions.values())).action["decisions"]
            by_customer = {item["customer_id"]: item for item in raw}
            decisions = {case.case_id: {"decision": by_customer[case.customer_id].get("decision"), "amount": float(by_customer[case.customer_id].get("amount", 0.0)), "method": by_customer[case.customer_id].get("method")} for case in batch.cases}
            next_state["decisions"] = decisions
            next_state["transcript"] = list(state["transcript"]) + [{"speaker": "policy", "message": "Recorded batch allocation."}]
            return TransitionResult(next_state, "customer_confirmation")
        if phase.phase_id == "customer_confirmation":
            approved = {case.customer_id for case in batch.cases if state["decisions"].get(case.case_id, {}).get("decision") == "approve"}
            next_state["confirmations"] = sorted(approved)
            next_state["transcript"] = list(state["transcript"]) + [{"speaker": "customer", "customer_id": customer_id, "message": "Confirmed or acknowledged disposition."} for customer_id in actions]
            return TransitionResult(next_state, "payments_execute")
        selected = next(iter(actions.values())).action["selected_customer_ids"]
        selected_set = set(selected)
        transactions = [{"customer_id": case.customer_id, "case_id": case.case_id, "amount": case.authorized_refund_amount, "method": case.authorized_refund_method} for case in batch.cases if case.customer_id in selected_set]
        next_state.update({"transactions": transactions, "budget_remaining": batch.refund_budget - sum(item["amount"] for item in transactions), "done": True, "phase": "finished"})
        return TransitionResult(next_state, None)

    def terminal(self, batch: RefundV22Batch, state: Mapping[str, Any]) -> Mapping[str, Any] | None:
        return dict(state) if state.get("done") else None

    def outcome(self, batch: RefundV22Batch, terminal: Mapping[str, Any]) -> Mapping[str, Any]:
        return asdict(verify_n1_trajectory(batch, _state(terminal)))

    def build_scorer(self, batch: RefundV22Batch): return measurement.build_scorer(batch)
    def build_reference_providers(self, batch: RefundV22Batch) -> tuple[Any, ...]: return ()
    def generator(self) -> None: return None


class ScriptedV22Provider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try: payload = json.loads(request.input_text)
        except json.JSONDecodeError as error: raise ProviderFailure("provider_contract", str(error), retryable=False) from error
        obs, role, phase = payload.get("observation", {}), payload.get("role"), payload.get("phase_id")
        if role == "policy":
            customers = obs["customers"]
            missing = {item["customer_id"]: [field for field in item["required_fact_ids"] if field not in item["revealed_facts"]][:3] for item in customers}
            missing = {key: value for key, value in missing.items() if value}
            if missing: result = {"decision": "request_facts", "requested_by_customer": missing}
            else:
                # Derive eligibility and terms strictly from the visible policy and
                # disclosed facts, then solve the declared two-slot budget problem.
                eligible = []
                for item in customers:
                    facts = item["revealed_facts"]
                    category = item["product_category"]
                    is_eligible = (
                        category == "apparel" and facts.get("issue_type") == "defective"
                        and facts.get("return_received") is True
                    ) or (
                        category == "software" and facts.get("issue_type") == "service_quality"
                        and facts.get("return_received") is True and facts.get("evidence_provided") is True
                    )
                    if is_eligible:
                        eligible.append((item, round(item["price"] * (0.75 if category == "software" else 1.0), 2)))
                from itertools import combinations
                choices = []
                for count in range(min(int(obs["execution_capacity"]), len(eligible)) + 1):
                    for choice in combinations(eligible, count):
                        cost = sum(amount for _, amount in choice)
                        if cost <= float(obs["refund_budget"]): choices.append((choice, cost))
                chosen, _ = max(choices, key=lambda pair: (sum(item["priority"] for item, _ in pair[0]), len(pair[0]), -pair[1], tuple(item["customer_id"] for item, _ in pair[0])))
                selected = {item["customer_id"]: amount for item, amount in chosen}
                result = {"decision": "allocate", "decisions": [{"customer_id": item["customer_id"], "decision": "approve" if item["customer_id"] in selected else "deny_or_defer", "amount": selected.get(item["customer_id"], 0.0), "method": "original_payment" if item["customer_id"] in selected else "none"} for item in customers]}
        elif role == "customer":
            result = {"decision": "provide_info" if phase == "customer_facts" else "confirm", "reveal_fields": list(obs.get("requested_fact_ids", []))}
        else:
            approved = [case_id for case_id, decision in obs.get("decisions", {}).items() if decision.get("decision") == "approve"]
            # Payments receives case IDs only internally; this converts their stable suffix to the public customer seat.
            result = {"decision": "execute_allocations", "selected_customer_ids": [f"customer_{case_id.rsplit('.', 1)[-1]}" for case_id in approved]}
        return ProviderResult(f"refund_v22_scripted:{request.provider_call_id}", request.model, request.revision or request.model, json.dumps(result), "stop", 0, 0, 0, 0.0, {"fixture": True})


@dataclass(frozen=True, slots=True)
class RefundV22Setup:
    plan: RunPlan; registry: PluginRegistry; prompt_sources: Mapping[str, str]; pricing: Mapping[str, TokenPricing]; harnesses: Mapping[str, Any]


def _contribution() -> FamilyContribution:
    root = REPOSITORY_ROOT / "cases" / "refund_v2_2"
    def evidence(kind: str, filename: str) -> QCEvidenceRef:
        return QCEvidenceRef(kind, f"qc/{filename}", hashlib.sha256((root / "qc" / filename).read_bytes()).hexdigest(), "refund_v2", "2.2.0", "refund_v2", (QCCoverage("provider_free_validation" if kind == "provider_free_conformance" else "human_qc", ("refund_v2",), ("refund_v2",)),))
    provider = evidence("provider_free_conformance", "provider_free.json")
    human = evidence("human_qc_approval", "human_qc.json")
    base = FamilyContribution("refund_v2", "2.2.0", "aeread.refund_v22", "contributed.refund_v2.2.0", {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, provider, ResourceLimits(120.0, 20, 60, 200000, 100000, 100.0), HumanQCApproval("refund-v2-maintainers", "approved", "0" * 64, human))
    from aeread.shared_runner.registry import family_contribution_sha256
    return replace(base, human_qc_approval=replace(base.human_qc_approval, contribution_sha256=family_contribution_sha256(base)))


def _profile(role: str, provider: str, model: str, schema: Mapping[str, Any]) -> AgentProfile:
    prompt = PROMPTS[role]
    pricing = TokenPricing(0, 0, 0, f"refund_v22_{provider}_{model}")
    return AgentProfile.from_dict({"spec_version": AgentProfile.SPEC_VERSION, "profile_id": f"refund_v22_{role}_{provider}_{model}", "model": {"provider": provider, "model": model, "revision": "2.2.0", "base_url": "https://api.preview.arena.ai/v1" if provider == "arena" else None}, "harness": {"id": "minimal_chat", "version": "1.0", "config": {"pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": schema}}, "prompt": {"prompt_id": f"refund_v22_{role}_prompt", "sha256": hashlib.sha256(prompt.encode()).hexdigest()}, "runtime": {"kind": "python", "implementation": "aeread.shared_runner.task.execution", "version": "0.1.0"}, "tools": [], "memory": {"mode": "disabled"}, "reasoning": {"condition_id": "refund_v22_default", "effort": None, "token_budget": None, "rationale_visibility": "hidden"}, "sampling": {"temperature": 0.0, "max_output_tokens": 4096, "seed": None, "top_p": None}, "budgets": {"max_logical_actions": 20, "timeout_seconds": 180.0 if provider == "arena" else 30.0, "max_cost_usd": None}, "retry_policy": {"max_action_attempts": 2, "retryable_conditions": ["empty_response"], "session_mode": "restart", "sdk_retries": 0}})


def build_refund_v22_run(*, provider: str = "scripted", model: str = "refund-v22-scripted", world_seeds: tuple[int, ...] = (0,)) -> RefundV22Setup:
    batches = tuple(build_n1_panel(seed) for seed in world_seeds)
    family = FamilyManifest.from_dict({"spec_version": FamilyManifest.SPEC_VERSION, "family": {"id": "refund_v2", "version": "2.2.0", "plugin_id": "aeread.refund_v22"}, "environment": {"topology": "many_customers_one_policy_agent", "phase_specs": ["policy_request", "customer_facts", "policy_allocate", "customer_confirmation", "payments_execute"], "needs_tools": False, "needs_sandbox": False}, "roles": {role: {"testable": role == "policy", "scripted_policies": ["scripted"]} for role in ("policy", "customer", "payments")}, "measurement": {"primary_estimand": "refund_v22_policy_compliance", "measurement_kind": "property_or_answer", "direction": "none", "optimum_lower_bound": "0", "optimum_upper_bound": "1", "optimum_upper_bound_kind": "known", "bound_status": "family_defined", "outcome_support": "pass_fail", "leaves": [{"leaf_id": leaf, "scope": "finalize_time"} for leaf in (measurement.POLICY_LEAF_ID, measurement.ALLOCATION_LEAF_ID, measurement.TRANSACTION_LEAF_ID, measurement.COORDINATION_LEAF_ID, measurement.UTILITY_LEAF_ID)], "primary_leaf_id": measurement.POLICY_LEAF_ID, "admission_leaf_ids": [measurement.POLICY_LEAF_ID, measurement.TRANSACTION_LEAF_ID]}, "scoring": {"scorer_id": "refund_v22_scorer", "reference_provider_ids": ["refund_v22_domain_predicate", "refund_v22_policy_compliance_verifier", "refund_v22_allocation_verifier", "refund_v22_transaction_verifier", "refund_v22_coordination_verifier", "refund_v22_system_utility_verifier"]}, "generator": {"generator_id": "refund_v22_n1_panel_generator", "difficulty_knobs": ["world_seed", "budget", "priority"]}})
    cases = []
    for batch in batches:
        raw = {"spec_version": CaseManifest.SPEC_VERSION, "case_id": batch.batch_id, "family_id": "refund_v2", "family_version": "2.2.0", "split": "dev", "world_seed": batch.world_seed, "seats": [{"id": "policy", "role": "policy"}, *[{"id": case.customer_id, "role": "customer"} for case in batch.cases], {"id": "payments", "role": "payments"}], "episode": {"max_logical_actions": 20, "termination": ["completed", "invalid_action"]}, "visibility_policy": "refund_v22_customer_scoped_gradual_disclosure", "payload": {"batch": asdict(batch)}, "provenance": {"generator_id": "refund_v22_n1_panel_generator", "generator_version": "2.2.0", "review_status": "reviewed"}, "content_sha256": "0" * 64}; raw["content_sha256"] = case_content_sha256(raw); cases.append(CaseManifest.from_dict(raw))
    profiles = (_profile("policy", provider, model, POLICY_SCHEMA), _profile("customer", "scripted", "refund-v22-scripted-customer", CUSTOMER_SCHEMA), _profile("payments", "scripted", "refund-v22-scripted-payments", PAYMENTS_SCHEMA))
    profile_by_role = {"policy": profiles[0].profile_id, "customer": profiles[1].profile_id, "payments": profiles[2].profile_id}
    sampling = SamplingPlan.from_dict({"spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": "refund_v22_n1_fixed_panel", "estimand": "refund_v22_n1", "target": "refund_v22_n1_panel_generator", "selection": "seeded_case_panel", "seeds": [0], "replicates": 1, "cluster_level": "world_seed", "cluster_id_fields": ["world_seed"], "paired_fields": ["world_seed"], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel"})
    block = EvaluationBlock.from_dict({"spec_version": EvaluationBlock.SPEC_VERSION, "block_id": "refund_v22_n1_controlled", "kind": "controlled", "subject_seats": ["policy"], "controlled_profiles": {"customer_1": profiles[1].profile_id, "customer_2": profiles[1].profile_id, "customer_3": profiles[1].profile_id, "payments": profiles[2].profile_id}, "repetitions": 1, "seed_policy": "fixed"})
    analysis = AnalysisPlan.from_dict({"spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "refund_v22_n1_analysis", "estimands": list(measurement.V22_ESTIMANDS), "group_by": ["family_id"], "missingness": "report_separately", "resampling_unit": "world_seed", "uncertainty": "none", "multiplicity": "none", "sensitivity": ["report_verifier_reasons"], "cross_family_scalar": "disabled"})
    suite = SuiteManifest.from_dict({"spec_version": SuiteManifest.SPEC_VERSION, "suite_id": "refund_v22_n1_suite", "version": "2.2.0", "family_ids": ["refund_v2"], "case_ids": [case.case_id for case in cases], "sampling_plan_id": sampling.sampling_plan_id, "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id})
    assignments = {"policy": profiles[0].profile_id, "customer_1": profiles[1].profile_id, "customer_2": profiles[1].profile_id, "customer_3": profiles[1].profile_id, "payments": profiles[2].profile_id}
    spec = RunSpec.from_dict({"spec_version": RunSpec.SPEC_VERSION, "run_spec_id": "refund_v22_n1_run", "suite_id": suite.suite_id, "evaluation_block_ids": [block.block_id], "agent_profile_ids": [profile.profile_id for profile in profiles], "seat_assignments": assignments, "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None})
    registry = PluginRegistry(); registry.register(family, RefundV22Plugin(), contribution=_contribution(), evidence_root=REPOSITORY_ROOT / "cases" / "refund_v2_2")
    harnesses = default_harnesses(); hr = HarnessRegistry(); [hr.register(harness) for harness in harnesses.values()]
    reference_path = Path(__file__).with_name("v2_2_environment.py")
    pin_specs = [("aeread.refund_v22", "family_plugin", Path(__file__), "2.2.0"), ("refund_v22_scorer", "scorer", Path(__file__).with_name("v2_2_measurement.py"), "2.2.0"), ("refund_v22_n1_panel_generator", "generator", reference_path, "2.2.0"), ("minimal_chat", "harness", Path(execution_module.__file__), "1.0"), ("aeread.shared_runner.task.execution", "runtime", Path(execution_module.__file__), "0.1.0")]
    pin_specs.extend((identifier, "reference", reference_path, "2.2.0") for identifier in ("refund_v22_domain_predicate", "refund_v22_policy_compliance_verifier", "refund_v22_allocation_verifier", "refund_v22_transaction_verifier", "refund_v22_coordination_verifier", "refund_v22_system_utility_verifier"))
    pins = tuple(ImplementationPin.from_dict({"component_id": ident, "kind": kind, "version": version, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}) for ident, kind, path, version in pin_specs)
    plan = resolve_run_plan(families=(family,), cases=tuple(cases), suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis, agent_profiles=profiles, run_spec=spec, registry=registry, implementation_pins=pins, harness_registry=hr, provider_capabilities={provider: ProviderCapabilities(False, False, False, True, True, False, None), "scripted": ProviderCapabilities(False, False, False, True, False, False, None)})
    pricing = {profile.model.model: TokenPricing(0, 0, 0, f"refund_v22_{profile.model.provider}_{profile.model.model}") for profile in profiles}
    return RefundV22Setup(plan, registry, {f"refund_v22_{role}_prompt": prompt for role, prompt in PROMPTS.items()}, pricing, harnesses)


async def run(*, output: Path, provider: str = "scripted", model: str = "refund-v22-scripted", world_seeds: tuple[int, ...] = (0,)) -> dict[str, Any]:
    setup = build_refund_v22_run(provider=provider, model=model, world_seeds=world_seeds); providers: dict[str, Any] = {"scripted": ScriptedV22Provider()}
    if provider == "arena": providers["arena"] = ArenaChatClient()
    receipts = []
    for cell in setup.plan.cells:
        execution = await execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=output, prompt_sources=setup.prompt_sources, providers=providers, pricing=setup.pricing, episode_attempt_ordinal=0, harnesses=setup.harnesses)
        receipt = finalize_family_execution(setup=setup, execution=execution); replay_family_receipt(setup=setup, receipt=receipt, evidence_root=output); receipts.append(receipt)
    return {"family_version": "2.2.0", "topology": "N:1", "run_plan_id": setup.plan.run_plan_id, "planned_batches": len(setup.plan.cells), "completed_batches": len(receipts), "receipts": [json.loads(canonical_json_bytes(receipt)) for receipt in receipts]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--provider", choices=("scripted", "arena"), default="scripted"); parser.add_argument("--model", default="refund-v22-scripted"); parser.add_argument("--world-seeds", default="0"); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    print(json.dumps(asyncio.run(run(output=args.output, provider=args.provider, model=args.model, world_seeds=tuple(int(item) for item in args.world_seeds.split(",") if item))), indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
