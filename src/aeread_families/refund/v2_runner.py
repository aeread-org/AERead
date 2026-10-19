"""Refund V2.1 family adapter for AERead's shared runner.

This module is deliberately the execution boundary for V2.1.  It produces a
real RunPlan, executes PlanCells through execute_plan_cell, and finalizes each
attempt with the kernel's sealed EvidenceStore and EvaluationReceipt path.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.task.execution import (
    ArenaChatClient,
    CellExecution,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.task.evaluation import (
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    RunPlan,
    case_content_sha256,
    canonical_json_bytes,
    resolve_run_plan,
)
from aeread.shared_runner.run.publication import atomic_publish
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult
from aeread.shared_runner.quality import FamilyContribution, HumanQCApproval, QCCoverage, QCEvidenceRef, ResourceLimits

from . import v2_measurement as measurement
from .v2_environment import RefundV2Case, RefundV2State, build_1n_panel, verify_1n_trajectory


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROMPT_IDS = {
    "customer": "refund_v21_customer_prompt",
    "intake": "refund_v21_intake_prompt",
    "policy": "refund_v21_policy_prompt",
    "payments": "refund_v21_payments_prompt",
}
PROMPTS = {
    "customer": """You are the customer. State the request first. Reveal only facts explicitly requested by the intake or policy agent, and only from your private facts. Confirm a proposed positive refund by proposal_id. Return one JSON object and no markdown.""",
    "intake": """You are the intake agent. Route the refund request by requesting no more than three relevant fact IDs at a time. Do not reveal or invent private facts. Return one JSON object and no markdown.""",
    "policy": """You are the policy agent. Decide only from the public case, policy, and facts already revealed. Request missing facts before deciding. Apply the written policy to derive the refund amount and payment method; do not assume access to hidden authorization fields. For an eligible positive case, propose the policy-calculated amount to original_payment; otherwise deny with amount 0 and method none. Return one JSON object and no markdown.""",
    "payments": """You are the payments executor. Execute exactly one currently confirmed authorized refund, or record no mutation for a denial. Return one JSON object and no markdown.""",
}

CUSTOMER_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["state_request", "provide_info", "confirm_resolution"]}, "message": {"type": "string"}, "reveal_fields": {"type": "array", "items": {"type": "string"}}, "proposal_id": {"type": ["string", "null"]}}, "required": ["decision", "message", "reveal_fields"], "additionalProperties": False}
INTAKE_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["request_facts"]}, "requested_fields": {"type": "array", "items": {"type": "string"}}, "message": {"type": "string"}}, "required": ["decision", "requested_fields"], "additionalProperties": False}
POLICY_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["request_facts", "approve_direct", "deny"]}, "requested_fields": {"type": "array", "items": {"type": "string"}}, "proposal_id": {"type": ["string", "null"]}, "amount": {"type": "number"}, "method": {"type": ["string", "null"]}, "message": {"type": "string"}}, "required": ["decision", "requested_fields", "amount", "method"], "additionalProperties": False}
PAYMENTS_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["execute_refund", "no_mutation"]}, "proposal_id": {"type": ["string", "null"]}}, "required": ["decision"], "additionalProperties": False}


def _json_response(response: Any) -> Mapping[str, Any] | None:
    text = getattr(response, "text", response)
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _state(value: Mapping[str, Any]) -> RefundV2State:
    fields = {}
    for field in RefundV2State.__dataclass_fields__:
        item = value.get(field)
        if isinstance(item, tuple):
            item = list(item)
        if field in {"handoffs", "proposals", "transactions", "transcript", "invalid_fact_requests"} and isinstance(item, list):
            item = [dict(entry) if isinstance(entry, Mapping) else entry for entry in item]
        fields[field] = item
    return RefundV2State(**fields)


class RefundV21Plugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> RefundV2Case:
        case = payload.get("case")
        if not isinstance(case, Mapping):
            raise ValueError("refund V2 payload has no case")
        return RefundV2Case(**dict(case))

    def initial_state(self, case: RefundV2Case, run: Any) -> dict[str, Any]:
        del run
        return asdict(RefundV2State(phase="customer_message", active_agent="customer"))

    def phases(self, case: RefundV2Case) -> tuple[PhaseSpec, ...]:
        del case
        schemas = {"customer": "refund_v21_customer_action", "intake": "refund_v21_intake_action", "policy": "refund_v21_policy_action", "payments": "refund_v21_payments_action"}
        observations = {role: "refund_v21_observation" for role in schemas}
        return (
            PhaseSpec("customer_message", "customer_only", "single", observations, schemas, 3, "family_defined", ("intake_request",)),
            PhaseSpec("intake_request", "intake_only", "single", observations, schemas, 3, "family_defined", ("customer_facts",)),
            PhaseSpec("customer_facts", "customer_only", "single", observations, schemas, 10, "family_defined", ("policy_response",)),
            PhaseSpec("policy_response", "policy_only", "single", observations, schemas, 10, "family_defined", ("customer_facts", "customer_confirmation", "payments_execute")),
            PhaseSpec("customer_confirmation", "customer_only", "single", observations, schemas, 2, "family_defined", ("payments_execute",)),
            PhaseSpec("payments_execute", "payments_only", "single", observations, schemas, 2, "family_defined", ()),
        )

    def eligible_actors(self, case: RefundV2Case, state: Mapping[str, Any], phase: PhaseSpec) -> tuple[str, ...]:
        del case, state
        return {"customer_message": ("customer",), "intake_request": ("intake",), "customer_facts": ("customer",), "policy_response": ("policy",), "customer_confirmation": ("customer",), "payments_execute": ("payments",)}[phase.phase_id]

    def observe(self, case: RefundV2Case, state: Mapping[str, Any], seat: str, phase: PhaseSpec) -> Mapping[str, Any]:
        visible = {"product_category": case.product_category, "price": case.price, "days_since_delivery": case.days_since_delivery, "public_claim": case.public_claim, "policy_summary": case.policy_summary, "revealed_facts": dict(state["revealed_facts"]), "required_fact_ids": list(case.required_facts), "requested_fact_ids": list(state.get("pending_requested", []))}
        if seat == "customer":
            visible["private_facts"] = dict(case.private_facts)
            visible["pending_proposal"] = state["proposals"][-1] if state["proposals"] else None
        elif seat == "payments":
            visible["confirmed_proposal"] = state["proposals"][-1] if state["proposals"] and state["confirmations"] else None
        visible["phase_id"] = phase.phase_id
        return visible

    def parse_action(self, case: RefundV2Case, state: Mapping[str, Any], seat: str, phase: PhaseSpec, response: Any) -> ParseResult:
        del case, state, phase
        value = _json_response(response)
        if value is None:
            return ParseResult.failure("malformed_json")
        if seat == "customer" and value.get("decision") in {"state_request", "provide_info", "confirm_resolution"} and isinstance(value.get("reveal_fields"), list):
            return ParseResult.success(dict(value))
        if seat == "intake" and value.get("decision") == "request_facts" and isinstance(value.get("requested_fields"), list):
            return ParseResult.success(dict(value))
        if seat == "policy" and value.get("decision") in {"request_facts", "approve_direct", "deny"} and isinstance(value.get("requested_fields"), list):
            return ParseResult.success(dict(value))
        if seat == "payments" and value.get("decision") in {"execute_refund", "no_mutation"}:
            return ParseResult.success(dict(value))
        return ParseResult.failure("invalid_action")

    def legal(self, case: RefundV2Case, state: Mapping[str, Any], seat: str, phase: PhaseSpec, action: Mapping[str, Any]) -> LegalityResult:
        if seat == "intake" or (seat == "policy" and action.get("decision") == "request_facts"):
            fields = action.get("requested_fields", [])
            if len(fields) > 3:
                return LegalityResult.illegal("too_many_fact_requests")
            if any(field not in case.required_facts for field in fields):
                return LegalityResult.illegal("unknown_fact")
            if any(field in state["revealed_facts"] for field in fields):
                return LegalityResult.illegal("repeated_fact")
        if seat == "customer" and phase.phase_id == "customer_facts":
            if any(field not in state.get("pending_requested", []) for field in action.get("reveal_fields", [])):
                return LegalityResult.illegal("customer_disclosed_unrequested_fact")
        if seat == "policy" and action.get("decision") in {"approve_direct", "deny"} and set(case.required_facts) - set(state["revealed_facts"]):
            return LegalityResult.illegal("decision_before_required_facts")
        return LegalityResult.legal_action()

    def step(self, case: RefundV2Case, state: Mapping[str, Any], phase: PhaseSpec, actions: Mapping[str, Any]) -> TransitionResult:
        next_state = {key: value for key, value in state.items()}
        envelope = next(iter(actions.values()))
        if not envelope.valid:
            next_state["invalid_fact_requests"] = list(next_state["invalid_fact_requests"]) + [envelope.legality.reason if envelope.legality else envelope.parse.error_code]
            next_state["done"] = True
            next_state["phase"] = "finished"
            return TransitionResult(next_state, None)
        action = dict(envelope.action)
        if phase.phase_id == "customer_message":
            next_state["transcript"] = list(next_state["transcript"]) + [{"speaker": "customer", "message": action.get("message", ""), "revealed_fields": []}]
            return TransitionResult(next_state, "intake_request")
        if phase.phase_id == "intake_request":
            requested = list(action.get("requested_fields", []))[:3]
            next_state["pending_requested"] = requested
            next_state["transcript"] = list(next_state["transcript"]) + [{"speaker": "intake", "message": action.get("message", ""), "requested_fields": requested}]
            next_state["handoffs"] = list(next_state["handoffs"]) + [{"from": "intake", "to": "policy", "facts": []}]
            return TransitionResult(next_state, "customer_facts")
        if phase.phase_id == "customer_facts":
            fields = [field for field in action.get("reveal_fields", []) if field in next_state["pending_requested"]]
            next_state["revealed_facts"] = {**next_state["revealed_facts"], **{field: case.private_facts[field] for field in fields}}
            next_state["transcript"] = list(next_state["transcript"]) + [{"speaker": "customer", "message": action.get("message", ""), "revealed_fields": fields}]
            next_state["handoffs"] = list(next_state["handoffs"]) + [{"from": "customer", "to": "policy", "facts": fields}]
            next_state["pending_requested"] = []
            return TransitionResult(next_state, "policy_response")
        if phase.phase_id == "policy_response":
            if action.get("decision") == "request_facts":
                requested = list(action.get("requested_fields", []))[:3]
                next_state["pending_requested"] = requested
                next_state["transcript"] = list(next_state["transcript"]) + [{"speaker": "policy", "message": action.get("message", ""), "requested_fields": requested}]
                return TransitionResult(next_state, "customer_facts")
            proposal = {"proposal_id": str(action.get("proposal_id") or "proposal_1"), "agent": "policy", "decision": action["decision"], "amount": float(action.get("amount", 0.0)), "method": action.get("method")}
            next_state["proposals"] = list(next_state["proposals"]) + [proposal]
            next_state["transcript"] = list(next_state["transcript"]) + [{"speaker": "policy", "message": action.get("message", ""), "proposal_id": proposal["proposal_id"]}]
            next_state["handoffs"] = list(next_state["handoffs"]) + [{"from": "policy", "to": "payments", "proposal_id": proposal["proposal_id"]}]
            return TransitionResult(next_state, "customer_confirmation")
        if phase.phase_id == "customer_confirmation":
            proposal_id = str(next_state["proposals"][-1]["proposal_id"])
            if action.get("decision") != "confirm_resolution" or action.get("proposal_id") not in {None, proposal_id}:
                next_state["invalid_fact_requests"] = list(next_state["invalid_fact_requests"]) + ["missing_customer_confirmation"]
            else:
                next_state["confirmations"] = list(next_state["confirmations"]) + [proposal_id]
            next_state["transcript"] = list(next_state["transcript"]) + [{"speaker": "customer", "message": action.get("message", ""), "revealed_fields": [], "proposal_id": proposal_id}]
            return TransitionResult(next_state, "payments_execute")
        proposal = next_state["proposals"][-1]
        confirmed = str(proposal["proposal_id"]) in next_state["confirmations"]
        decision = action.get("decision")
        if proposal["amount"] > 0 and confirmed and decision == "execute_refund":
            next_state["transactions"] = list(next_state["transactions"]) + [{"agent": "payments", "proposal_id": proposal["proposal_id"], "amount": proposal["amount"], "method": proposal["method"]}]
        next_state["transcript"] = list(next_state["transcript"]) + [{"speaker": "payments", "message": "Refund mutation executed." if next_state["transactions"] else "No payment mutation required."}]
        next_state["done"] = True
        next_state["phase"] = "finished"
        return TransitionResult(next_state, None)

    def terminal(self, case: RefundV2Case, state: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if not state.get("done"):
            return None
        return dict(state)

    def outcome(self, case: RefundV2Case, terminal: Mapping[str, Any]) -> Mapping[str, Any]:
        checked = verify_1n_trajectory(case, _state(terminal))
        return asdict(checked)

    def build_scorer(self, case: RefundV2Case) -> measurement.RefundV21Scorer:
        return measurement.build_scorer(case)

    def build_reference_providers(self, case: RefundV2Case) -> tuple[Any, ...]:
        del case
        return ()

    def generator(self) -> None:
        return None


class ScriptedV21Provider:
    def __init__(self, role: str):
        self.role = role

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try:
            payload = json.loads(request.input_text)
        except json.JSONDecodeError as error:
            raise ProviderFailure("provider_contract", str(error), retryable=False) from error
        observation = payload.get("observation") or {}
        phase = payload.get("phase_id")
        if self.role == "customer":
            if phase == "customer_message":
                result = {"decision": "state_request", "message": "I need help with this refund request.", "reveal_fields": []}
            elif phase == "customer_facts":
                result = {"decision": "provide_info", "message": "Here are the requested facts.", "reveal_fields": list(observation.get("requested_fact_ids", []))}
            else:
                proposal = observation.get("pending_proposal") or {}
                result = {"decision": "confirm_resolution", "message": "I confirm the resolution.", "proposal_id": proposal.get("proposal_id"), "reveal_fields": []}
        elif self.role == "intake":
            available = [field for field in observation.get("required_fact_ids", []) if field not in observation.get("revealed_facts", {})]
            result = {"decision": "request_facts", "requested_fields": available[:3], "message": "I will collect the minimum relevant facts."}
        elif self.role == "policy":
            missing = [field for field in observation.get("required_fact_ids", []) if field not in observation.get("revealed_facts", {})]
            if missing:
                result = {"decision": "request_facts", "requested_fields": missing[:3], "message": "Please provide the missing facts.", "amount": 0.0, "method": None}
            else:
                facts = observation.get("revealed_facts") or {}
                category = observation.get("product_category")
                eligible = (
                    category == "apparel"
                    and observation.get("days_since_delivery", 0) <= 30
                    and facts.get("issue_type") == "defective"
                    and facts.get("return_received") is True
                )
                if category == "software":
                    eligible = (
                        observation.get("days_since_delivery", 0) <= 30
                        and facts.get("issue_type") == "service_quality"
                        and facts.get("condition") in {"intact", "lightly_used"}
                        and facts.get("return_received") is True
                        and facts.get("evidence_provided") is True
                    )
                amount = float(observation.get("price", 0.0))
                if category == "software":
                    amount *= 0.75
                result = {"decision": "approve_direct" if eligible else "deny", "requested_fields": [], "proposal_id": "proposal_1", "amount": amount if eligible else 0.0, "method": "original_payment" if eligible else "none", "message": "I recorded the policy resolution."}
        else:
            proposal = observation.get("confirmed_proposal") or {}
            result = {"decision": "execute_refund" if proposal.get("amount", 0) > 0 else "no_mutation", "proposal_id": proposal.get("proposal_id")}
        return ProviderResult(f"refund_v21_scripted:{request.provider_call_id}", request.model, request.revision or request.model, json.dumps(result, sort_keys=True), "stop", 0, 0, 0, 0.0, {"fixture": True})


class ScriptedV21Multiplexer:
    """Dispatch the fixed counterpart by the scheduler's declared role."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try:
            payload = json.loads(request.input_text)
        except json.JSONDecodeError as error:
            raise ProviderFailure("provider_contract", str(error), retryable=False) from error
        role = str(payload.get("role", ""))
        return await ScriptedV21Provider(role).complete(request)


@dataclass(frozen=True, slots=True)
class RefundV21Setup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    harnesses: Mapping[str, Any]


def _pin(identifier: str, kind: str, path: Path, version: str = "1.0.0") -> ImplementationPin:
    return ImplementationPin.from_dict({"component_id": identifier, "kind": kind, "version": version, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})


def family_manifest() -> FamilyManifest:
    leaf_ids = [measurement.POLICY_LEAF_ID, measurement.TRANSACTION_LEAF_ID, measurement.COORDINATION_LEAF_ID, measurement.UTILITY_LEAF_ID]
    return FamilyManifest.from_dict({"spec_version": FamilyManifest.SPEC_VERSION, "family": {"id": "refund_v2", "version": "2.1.0", "plugin_id": "aeread.refund_v2"}, "environment": {"topology": "one_customer_many_service_agents", "phase_specs": ["customer_message", "intake_request", "customer_facts", "policy_response", "customer_confirmation", "payments_execute"], "needs_tools": False, "needs_sandbox": False}, "roles": {role: {"testable": role in {"customer", "intake", "policy"}, "scripted_policies": ["scripted"]} for role in ("customer", "intake", "policy", "payments")}, "measurement": {"primary_estimand": "refund_v21_policy_compliance", "measurement_kind": "property_or_answer", "direction": "none", "optimum_lower_bound": "0", "optimum_upper_bound": "1", "optimum_upper_bound_kind": "known", "bound_status": "family_defined", "outcome_support": "pass_fail", "leaves": [{"leaf_id": leaf_id, "scope": "finalize_time"} for leaf_id in leaf_ids], "primary_leaf_id": measurement.POLICY_LEAF_ID, "admission_leaf_ids": [measurement.POLICY_LEAF_ID, measurement.TRANSACTION_LEAF_ID]}, "scoring": {"scorer_id": "refund_v21_scorer", "reference_provider_ids": ["refund_v21_domain_predicate", "refund_v21_utility_verifier", "refund_v21_transaction_verifier", "refund_v21_coordination_verifier", "refund_v21_policy_verifier"]}, "generator": {"generator_id": "refund_v21_1n_panel_generator", "difficulty_knobs": ["scenario", "product_category", "world_seed", "required_facts"]}})


def _case_manifest(case: RefundV2Case) -> CaseManifest:
    payload = {"case": asdict(case)}
    raw = {"spec_version": CaseManifest.SPEC_VERSION, "case_id": case.case_id, "family_id": "refund_v2", "family_version": "2.1.0", "split": "dev", "world_seed": case.world_seed, "seats": [{"id": role, "role": role} for role in ("customer", "intake", "policy", "payments")], "episode": {"max_logical_actions": 30, "termination": ["completed", "invalid_action"]}, "visibility_policy": "refund_v21_gradual_customer_disclosure", "payload": payload, "provenance": {"generator_id": "refund_v21_1n_panel_generator", "generator_version": "2.1.0", "review_status": "reviewed"}, "content_sha256": "0" * 64}
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _profile(role: str, provider: str, model: str, revision: str, *, output_schema: Mapping[str, Any], max_output_tokens: int, reasoning_effort: str | None = None) -> AgentProfile:
    pricing = TokenPricing(0.0, 0.0, 0.0, f"refund_v21_{provider}_zero_cost") if provider == "scripted" else TokenPricing(0.0, 0.0, 0.0, f"refund_v21_{provider}_{model}")
    prompt = PROMPTS[role]
    harness_config = {"pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": dict(output_schema)}
    if provider == "arena" and model.startswith("gpt-5.6"):
        harness_config["sampling_controls"] = {"temperature": "unavailable"}
    return AgentProfile.from_dict({"spec_version": AgentProfile.SPEC_VERSION, "profile_id": f"refund_v21_{role}_{provider}_{model.replace('/', '_')}", "model": {"provider": provider, "model": model, "revision": revision, "base_url": "https://api.preview.arena.ai/v1" if provider == "arena" else None}, "harness": {"id": "minimal_chat", "version": "1.0", "config": harness_config}, "prompt": {"prompt_id": PROMPT_IDS[role], "sha256": hashlib.sha256(prompt.encode()).hexdigest()}, "runtime": {"kind": "python", "implementation": "aeread.shared_runner.task.execution", "version": "0.1.0"}, "tools": [], "memory": {"mode": "disabled"}, "reasoning": {"condition_id": f"refund_v21_{role}_reasoning_{reasoning_effort or 'provider_default'}", "effort": reasoning_effort if provider == "arena" else None, "token_budget": None, "rationale_visibility": "hidden"}, "sampling": {"temperature": 0.0, "max_output_tokens": max_output_tokens, "seed": None, "top_p": None}, "budgets": {"max_logical_actions": 30, "timeout_seconds": 180.0 if provider == "arena" else 30.0, "max_cost_usd": None if provider in {"arena", "scripted"} else 0.01}, "retry_policy": {"max_action_attempts": 2, "retryable_conditions": ["empty_response", "length"], "session_mode": "restart", "sdk_retries": 0}})


def build_refund_v21_run(*, provider: str = "scripted", model: str = "refund-v21-scripted", revision: str = "2.1.0", world_seeds: tuple[int, ...] = (1,), active_agents: tuple[str, ...] = ("policy",), evaluation_kind: str = "controlled", max_output_tokens: int = 4096, reasoning_effort: str | None = None) -> RefundV21Setup:
    valid_agents = {"intake", "customer", "policy"}
    if not set(active_agents) <= valid_agents:
        raise ValueError(f"active_agents must be selected from {sorted(valid_agents)}")
    if evaluation_kind not in {"controlled", "self_play"}:
        raise ValueError("evaluation_kind must be 'controlled' or 'self_play'")
    if evaluation_kind == "controlled" and len(active_agents) != 1:
        raise ValueError("controlled evaluation requires exactly one active agent")
    cases = tuple(_case_manifest(case) for seed in world_seeds for case in build_1n_panel(seed))
    family = family_manifest()
    sampling = SamplingPlan.from_dict({"spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": "refund_v21_1n_seeded_panel", "estimand": "refund_v21_1n_panel", "target": "refund_v21_1n_panel_generator", "selection": "seeded_case_panel", "seeds": [0], "replicates": 1, "cluster_level": "world_seed", "cluster_id_fields": ["generator_version", "world_seed"], "paired_fields": ["world_seed"], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel"})
    profiles = []
    schemas = {"customer": CUSTOMER_SCHEMA, "intake": INTAKE_SCHEMA, "policy": POLICY_SCHEMA, "payments": PAYMENTS_SCHEMA}
    for role in ("customer", "intake", "policy"):
        chosen = provider if role in active_agents else "scripted"
        profiles.append(_profile(role, chosen, model if chosen == provider else f"refund-v21-scripted-{role}", revision if chosen == provider else "2.1.0", output_schema=schemas[role], max_output_tokens=max_output_tokens if chosen == provider else 512, reasoning_effort=reasoning_effort))
    profiles.append(_profile("payments", "scripted", "refund-v21-scripted-payments", "2.1.0", output_schema=PAYMENTS_SCHEMA, max_output_tokens=256))
    controlled_profiles = {
        role: next(profile.profile_id for profile in profiles if profile.profile_id.startswith(f"refund_v21_{role}_"))
        for role in ("customer", "intake", "policy", "payments")
        if role not in active_agents
    }
    block = EvaluationBlock.from_dict({"spec_version": EvaluationBlock.SPEC_VERSION, "block_id": f"refund_v21_1n_{evaluation_kind}_block", "kind": evaluation_kind, "subject_seats": list(active_agents), "controlled_profiles": controlled_profiles if evaluation_kind == "controlled" else {}, "repetitions": 1, "seed_policy": "fixed"})
    analysis = AnalysisPlan.from_dict({"spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "refund_v21_1n_analysis", "estimands": ["refund_v21_policy_compliance", "refund_v21_transaction", "refund_v21_coordination", "refund_v21_system_utility"], "group_by": ["family_id", "subject_role"], "missingness": "report_separately", "resampling_unit": "world_seed", "uncertainty": "none", "multiplicity": "none", "sensitivity": ["report_verifier_reasons", "report_active_agents"], "cross_family_scalar": "disabled"})
    suite = SuiteManifest.from_dict({"spec_version": SuiteManifest.SPEC_VERSION, "suite_id": "refund_v21_1n_suite", "version": "2.1.0", "family_ids": ["refund_v2"], "case_ids": [case.case_id for case in cases], "sampling_plan_id": sampling.sampling_plan_id, "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id})
    run_spec = RunSpec.from_dict({"spec_version": RunSpec.SPEC_VERSION, "run_spec_id": "refund_v21_1n_run", "suite_id": suite.suite_id, "evaluation_block_ids": [block.block_id], "agent_profile_ids": [profile.profile_id for profile in profiles], "seat_assignments": {role: next(profile.profile_id for profile in profiles if profile.profile_id.startswith(f"refund_v21_{role}_")) for role in ("customer", "intake", "policy", "payments")}, "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None})
    registry = PluginRegistry()
    contribution = _contribution()
    registry.register(family, RefundV21Plugin(), contribution=contribution, evidence_root=REPOSITORY_ROOT / "cases" / "refund_v2")
    execution_path = Path(execution_module.__file__)
    pins = [_pin("aeread.refund_v2", "family_plugin", Path(__file__)), _pin("refund_v21_1n_panel_generator", "generator", Path(__file__)), _pin("minimal_chat", "harness", execution_path, "1.0"), _pin("aeread.shared_runner.task.execution", "runtime", execution_path, "0.1.0")]
    for component, kind, path in (("refund_v21_domain_predicate", "reference", Path(__file__).with_name("v2_environment.py")), ("refund_v21_utility_verifier", "reference", Path(__file__).with_name("v2_environment.py")), ("refund_v21_transaction_verifier", "reference", Path(__file__).with_name("v2_environment.py")), ("refund_v21_coordination_verifier", "reference", Path(__file__).with_name("v2_environment.py")), ("refund_v21_policy_verifier", "reference", Path(__file__).with_name("v2_environment.py")), ("refund_v21_scorer", "scorer", Path(__file__).with_name("v2_measurement.py"))):
        pins.append(_pin(component, kind, path, "2.1.0"))
    harnesses = default_harnesses()
    from aeread.shared_runner.registry import HarnessRegistry
    harness_registry = HarnessRegistry()
    for harness in harnesses.values():
        harness_registry.register(harness)
    plan = resolve_run_plan(families=(family,), cases=cases, suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis, agent_profiles=tuple(profiles), run_spec=run_spec, registry=registry, implementation_pins=tuple(pins), harness_registry=harness_registry, provider_capabilities={provider: ProviderCapabilities(False, False, False, True, True, False, None), "scripted": ProviderCapabilities(False, False, False, True, False, False, None)})
    pricing = {
        profile.model.model: TokenPricing(
            0.0,
            0.0,
            0.0,
            "refund_v21_scripted_zero_cost"
            if profile.model.provider == "scripted"
            else f"refund_v21_{profile.model.provider}_{profile.model.model}",
        )
        for profile in profiles
    }
    return RefundV21Setup(
        plan,
        registry,
        {PROMPT_IDS[role]: prompt for role, prompt in PROMPTS.items()},
        pricing,
        harnesses,
    )


def _contribution() -> FamilyContribution:
    root = REPOSITORY_ROOT / "cases" / "refund_v2"
    provider = QCEvidenceRef("provider_free_conformance", "qc/provider_free.json", hashlib.sha256((root / "qc/provider_free.json").read_bytes()).hexdigest(), "refund_v2", "2.1.0", "refund_v2", (QCCoverage("provider_free_validation", ("refund_v2",), ("refund_v2",)),))
    human = QCEvidenceRef("human_qc_approval", "qc/human_qc.json", hashlib.sha256((root / "qc/human_qc.json").read_bytes()).hexdigest(), "refund_v2", "2.1.0", "refund_v2", (QCCoverage("human_qc", ("refund_v2",), ("refund_v2",)),))
    base = FamilyContribution("refund_v2", "2.1.0", "aeread.refund_v2", "contributed.refund_v2.2.1", {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, provider, ResourceLimits(120.0, 30, 60, 200000, 100000, 100.0), HumanQCApproval("refund-v2-maintainers", "approved", "0" * 64, human))
    from aeread.shared_runner.registry import family_contribution_sha256
    return replace(base, human_qc_approval=replace(base.human_qc_approval, contribution_sha256=family_contribution_sha256(base)))


def finalize_refund_v21_execution(*, setup: RefundV21Setup, execution: CellExecution):
    return finalize_family_execution(setup=setup, execution=execution)


def replay_refund_v21_receipt(*, setup: RefundV21Setup, receipt: Any, evidence_root: Path | str):
    return replay_family_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)


async def run(*, output: Path, provider: str = "scripted", model: str = "refund-v21-scripted", revision: str = "2.1.0", world_seeds: tuple[int, ...] = (1,), active_agents: tuple[str, ...] = ("policy",), evaluation_kind: str = "controlled", max_output_tokens: int = 4096, reasoning_effort: str | None = None) -> dict[str, Any]:
    setup = build_refund_v21_run(provider=provider, model=model, revision=revision, world_seeds=world_seeds, active_agents=active_agents, evaluation_kind=evaluation_kind, max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort)
    providers: dict[str, Any] = {"scripted": ScriptedV21Multiplexer()}
    if provider == "arena":
        providers[provider] = ArenaChatClient()
    receipts = []
    failures = []
    for cell in setup.plan.cells:
        try:
            execution = await execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=output, prompt_sources=setup.prompt_sources, providers=providers, pricing=setup.pricing, episode_attempt_ordinal=0, harnesses=setup.harnesses)
            receipt = finalize_refund_v21_execution(setup=setup, execution=execution)
            replay_family_receipt(setup=setup, receipt=receipt, evidence_root=output)
            receipts.append(receipt)
        except Exception as error:
            try:
                failure_receipt = finalize_family_failure(
                    setup=setup,
                    cell_id=cell.cell_id,
                    evidence_root=output,
                    error=error,
                    leaf_builder=lambda payload: measurement.build_measurement_leaves(
                        RefundV21Plugin().validate_payload(payload)
                    )[0],
                )
                receipts.append(failure_receipt)
            except Exception as receipt_error:
                exclusion = {
                    "schema_version": "aeread.refund_v21_operational_exclusion/0.1",
                    "run_plan_id": setup.plan.run_plan_id,
                    "cell_id": cell.cell_id,
                    "case_id": cell.case_id,
                    "inclusion_status": "excluded",
                    "failure_class": "receipt_finalization_failure",
                    "condition": type(receipt_error).__name__,
                }
                exclusion_path = output / setup.plan.run_plan_id / "operational_exclusions" / f"{cell.cell_id}.json"
                atomic_publish(exclusion_path, canonical_json_bytes(exclusion) + b"\n")
                failures.append(exclusion)
    return {
        "family_id": "refund_v2",
        "family_version": "2.1.0",
        "topology": "1:N",
        "run_plan_id": setup.plan.run_plan_id,
        "seeds": list(world_seeds),
        "scenarios": sorted({case.scenario for seed in world_seeds for case in build_1n_panel(seed)}),
        "planned_cells": len(setup.plan.cells),
        "planned_cases": len(setup.plan.cells),
        "completed_cells": len(receipts),
        "completed_cases": len(receipts),
        "operational_failures": len(failures),
        "receipts": [json.loads(canonical_json_bytes(receipt)) for receipt in receipts],
        "failures": failures,
        "evidence_root": str(output),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("scripted", "arena"), default="scripted")
    parser.add_argument("--model", default="refund-v21-scripted")
    parser.add_argument("--revision", default="2.1.0")
    parser.add_argument("--world-seeds", default="1")
    parser.add_argument("--active-agents", default="policy")
    parser.add_argument("--evaluation-kind", choices=("controlled", "self_play"), default="controlled")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    seeds = tuple(int(item) for item in args.world_seeds.split(",") if item.strip())
    active = tuple(item.strip() for item in args.active_agents.split(",") if item.strip())
    print(json.dumps(asyncio.run(run(output=args.output, provider=args.provider, model=args.model, revision=args.revision, world_seeds=seeds, active_agents=active, evaluation_kind=args.evaluation_kind, max_output_tokens=args.max_output_tokens, reasoning_effort=args.reasoning_effort)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
