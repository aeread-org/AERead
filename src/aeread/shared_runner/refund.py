"""Refund V1 shared-runner bridge.

This module maps the refund negotiation environment onto the generic scheduler:
a scripted customer and tested support agent alternate between customer disclosure
and support response, and the terminal outcome reports customer, support-agent,
and joint utility.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

from aeread import gemini_llm
from aeread import refund_env as rf

from .execution import (
    ArenaChatClient,
    CanonicalResponse,
    OpenAIResponsesClient,
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from .harness import default_harnesses
from .registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from .resolver import (
    ImplementationPin,
    RunPlan,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
)
from .scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult
from .schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)


CUSTOMER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "enum": ["state_request", "provide_info", "counter", "accept_offer", "reject_offer"]
        },
        "message": {"type": "string"},
        "requested_amount": {"type": ["number", "null"]},
        "reveal_fields": {
            "type": "array",
            "items": {"enum": list(rf.CUSTOMER_REVEAL_FIELDS)},
        },
    },
    "required": ["decision", "message", "requested_amount", "reveal_fields"],
    "additionalProperties": False,
}


SUPPORT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "enum": ["ask_info", "offer", "approve_direct", "request_return", "escalate", "deny"]
        },
        "message": {"type": "string"},
        "refund_amount": {"type": ["number", "null"]},
        "refund_method": {
            "type": ["string", "null"],
            "enum": [
                "original_payment",
                "pending_original_payment",
                "original_payment_after_review",
                "none",
                None,
            ],
        },
        "requires_human_review": {"type": ["boolean", "null"]},
        "requested_info": {
            "type": "array",
            "items": {"enum": list(rf.CUSTOMER_REVEAL_FIELDS)},
        },
    },
    "required": [
        "decision",
        "message",
        "refund_amount",
        "refund_method",
        "requires_human_review",
        "requested_info",
    ],
    "additionalProperties": False,
}


CUSTOMER_PROMPT = """You are the customer in a refund negotiation.
Use only your private truth, the public order, and the conversation so far.
Reveal information gradually when it helps your request. Do not reveal fields
you were not asked about unless doing so helps resolve the case. Return exactly
one JSON object matching the declared schema, with no markdown."""


SUPPORT_PROMPT = """You are the support agent in a refund negotiation.
Apply the refund policy, but remember that some customer facts are private until
the customer reveals them. Ask for missing facts when needed, make a negotiated
offer when useful, or finish with approve_direct, request_return, escalate, or
deny. Return exactly one JSON object matching the declared schema, with no
markdown."""


class GeminiProviderClient:
    """Shared-runner provider client backed by the repo's Gemini REST adapter."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "gemini":
            raise ProviderFailure(
                "provider_contract",
                f"Gemini adapter received provider {request.provider!r}",
                retryable=False,
            )
        try:
            result = await asyncio.to_thread(
                gemini_llm.call_gemini,
                request.instructions,
                request.input_text,
                request.model,
                request.max_output_tokens,
                0.0 if request.temperature is None else request.temperature,
                request.request_sha256,
            )
        except RuntimeError as error:
            raise ProviderFailure("provider_rejected", str(error), retryable=False) from error
        usage = result.usage or {}
        return ProviderResult(
            response_id=f"gemini:{request.provider_call_id}",
            requested_model=request.model,
            resolved_model=result.model_version or request.model,
            output_text=result.text,
            finish_reason="stop",
            input_tokens=int(usage.get("input_tokens") or 0),
            cached_input_tokens=int(usage.get("cached_input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=None,
            raw_response={
                "text": result.text,
                "cached": result.cached,
                "usage": usage,
                "model_version": result.model_version,
            },
        )


class FixedRefundProvider:
    """Deterministic provider fixture that still crosses the API response boundary."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try:
            payload = json.loads(request.input_text)
        except json.JSONDecodeError as error:
            raise ProviderFailure("provider_contract", str(error), retryable=False) from error
        phase_id = payload.get("phase_id")
        observation = payload.get("observation")
        if not isinstance(observation, Mapping):
            raise ProviderFailure(
                "provider_contract", "refund fixture received no observation", retryable=False
            )
        if phase_id == "customer_message":
            output = self._customer_response(observation)
        elif phase_id == "support_response":
            output = self._support_response(observation)
        else:
            output = {"decision": "deny", "message": "Unknown phase.", "refund_amount": 0.0}
        text = json.dumps(output, sort_keys=True)
        return ProviderResult(
            response_id=f"fixed_refund:{request.provider_call_id}",
            requested_model=request.model,
            resolved_model=request.revision or request.model,
            output_text=text,
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"fixture": True, "output": output},
        )

    @staticmethod
    def _customer_response(observation: Mapping[str, Any]) -> dict[str, Any]:
        pending_offer = observation.get("pending_offer")
        if isinstance(pending_offer, Mapping):
            return {
                "decision": "accept_offer",
                "message": "I accept that resolution.",
                "requested_amount": observation["public_order"]["requested_amount"],
                "reveal_fields": [],
            }
        requested = observation.get("requested_info")
        if not isinstance(requested, list):
            requested = []
        reveal_fields = list(
            dict.fromkeys(
                field for field in requested if field in rf.CUSTOMER_REVEAL_FIELDS
            )
        )[:3]
        if not reveal_fields:
            return {
                "decision": "state_request",
                "message": "I would like help resolving my refund request.",
                "requested_amount": observation["public_order"]["requested_amount"],
                "reveal_fields": [],
            }
        return {
            "decision": "provide_info",
            "message": "Here is the information you requested.",
            "requested_amount": observation["public_order"]["requested_amount"],
            "reveal_fields": reveal_fields,
        }

    @staticmethod
    def _support_response(observation: Mapping[str, Any]) -> dict[str, Any]:
        revealed = observation.get("revealed_customer_fields")
        if not isinstance(revealed, Mapping):
            revealed = {}
        missing = [field for field in rf.CUSTOMER_REVEAL_FIELDS if field not in revealed]
        if missing:
            return {
                "decision": "ask_info",
                "message": "Please provide the product condition, issue, evidence, usage, and return status.",
                "refund_amount": None,
                "refund_method": None,
                "requires_human_review": None,
                "requested_info": missing,
            }
        public_order = observation["public_order"]
        case = rf.RefundCase(
            case_id="fixed_refund_runtime",
            world_seed=0,
            customer=rf.CustomerProfile(**dict(public_order["customer"])),
            product=rf.ProductRecord(**{**dict(public_order["product"]), **dict(revealed)}),
            requested_amount=float(public_order["requested_amount"]),
        )
        decision = rf.evaluate_refund(case)
        return {
            "decision": decision.decision,
            "message": "I resolved the request under the refund policy.",
            "refund_amount": decision.refund_amount,
            "refund_method": decision.refund_method,
            "requires_human_review": decision.requires_human_review,
            "requested_info": [],
        }


class ScriptedRefundCustomerProvider:
    """Deterministic controlled counterpart for support-agent evaluations."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "scripted":
            raise ProviderFailure(
                "provider_contract",
                f"scripted customer received provider {request.provider!r}",
                retryable=False,
            )
        try:
            payload = json.loads(request.input_text)
        except json.JSONDecodeError as error:
            raise ProviderFailure("provider_contract", str(error), retryable=False) from error
        if payload.get("phase_id") != "customer_message":
            raise ProviderFailure(
                "provider_contract",
                "scripted customer received a non-customer phase",
                retryable=False,
            )
        observation = payload.get("observation")
        if not isinstance(observation, Mapping):
            raise ProviderFailure(
                "provider_contract", "scripted customer received no observation", retryable=False
            )
        output = FixedRefundProvider._customer_response(observation)
        return ProviderResult(
            response_id=f"scripted_refund_customer:{request.provider_call_id}",
            requested_model=request.model,
            resolved_model=request.revision or request.model,
            output_text=json.dumps(output, sort_keys=True),
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"fixture": True, "output": output},
        )


def _case_from_payload(payload: Mapping[str, Any]) -> rf.RefundCase:
    order = payload["public_order"]
    private = payload["private_customer_truth"]
    customer = rf.CustomerProfile(**dict(order["customer"]))
    product_payload = {**dict(order["product"]), **dict(private)}
    product = rf.ProductRecord(**product_payload)
    return rf.RefundCase(
        case_id=str(payload.get("case_id", "runtime_refund_case")),
        world_seed=int(payload.get("world_seed", 0)),
        customer=customer,
        product=product,
        requested_amount=float(order["requested_amount"]),
    )


def _json_from_response(response: Any) -> dict[str, Any] | None:
    if isinstance(response, CanonicalResponse):
        text = response.text
    elif isinstance(response, str):
        text = response
    elif isinstance(response, Mapping):
        return dict(response)
    else:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return dict(value) if isinstance(value, Mapping) else None


class RefundV1Plugin:
    """Two-seat refund negotiation plugin for the shared scheduler."""

    def validate_payload(self, payload: Mapping[str, Any]) -> rf.RefundCase:
        if not isinstance(payload, Mapping):
            raise ValueError("refund payload must be a mapping")
        return _case_from_payload(payload)

    def initial_state(self, case: rf.RefundCase, run: Any) -> dict[str, Any]:
        return rf.initial_negotiation_state(case)

    def phases(self, case: rf.RefundCase) -> tuple[PhaseSpec, ...]:
        return (
            PhaseSpec(
                phase_id="customer_message",
                actor_selector="customer_only",
                mode="single",
                observation_schema_by_role={"customer": "refund_customer_observation_v1"},
                action_schema_by_role={"customer": "refund_customer_message_v1"},
                max_logical_actions=4,
                invalid_action_policy="family_defined",
                next_phases=("support_response",),
            ),
            PhaseSpec(
                phase_id="support_response",
                actor_selector="support_agent_only",
                mode="single",
                observation_schema_by_role={"support_agent": "refund_support_observation_v1"},
                action_schema_by_role={"support_agent": "refund_support_action_v1"},
                max_logical_actions=4,
                invalid_action_policy="family_defined",
                next_phases=("customer_message",),
            ),
        )

    def eligible_actors(self, case, state, phase) -> tuple[str, ...]:
        if state["phase"] == "customer_message":
            return ("customer",)
        if state["phase"] == "support_response":
            return ("support_agent",)
        raise ValueError(f"no actors for phase {state['phase']!r}")

    def observe(self, case: rf.RefundCase, state, seat, phase):
        if seat == "customer":
            return rf.customer_observation(case, state)
        if seat == "support_agent":
            return rf.support_observation(case, state)
        raise ValueError(f"unknown seat {seat!r}")

    def parse_action(self, case, state, seat, phase, response):
        value = _json_from_response(response)
        if value is None:
            return ParseResult.failure("malformed_json")
        if seat == "customer":
            if not isinstance(value.get("message"), str):
                return ParseResult.failure("missing_customer_message")
            if value.get("decision") not in {
                "state_request",
                "provide_info",
                "counter",
                "accept_offer",
                "reject_offer",
            }:
                return ParseResult.failure("invalid_customer_decision")
            reveal_fields = value.get("reveal_fields")
            if not isinstance(reveal_fields, list):
                return ParseResult.failure("invalid_reveal_fields")
            return ParseResult.success(value)
        if value.get("decision") not in {
            "ask_info",
            "offer",
            "approve_direct",
            "request_return",
            "escalate",
            "deny",
        }:
            return ParseResult.failure("invalid_support_decision")
        if not isinstance(value.get("message"), str):
            return ParseResult.failure("missing_support_message")
        return ParseResult.success(value)

    def legal(self, case, state, seat, phase, action):
        return LegalityResult.legal_action()

    def step(self, case: rf.RefundCase, state, phase, actions):
        envelope = next(iter(actions.values()))
        if not envelope.valid:
            final = rf.RefundDecision(
                decision="deny",
                refund_amount=0.0,
                refund_method="none",
                automatic_threshold=0.0,
                maximum_refund_limit=0.0,
                requires_human_review=False,
                reason_codes=("invalid_llm_action",),
            )
            next_state = dict(state)
            next_state["final_decision"] = asdict(final)
            next_state["done"] = True
            next_state["phase"] = "finished"
            return TransitionResult(state=next_state, next_phase_id=None)
        if phase.phase_id == "customer_message":
            next_state = rf.apply_customer_action(case, state, envelope.action)
            next_phase = None if next_state["done"] else "support_response"
        else:
            next_state = rf.apply_support_action(case, state, envelope.action)
            next_phase = None if next_state["done"] else "customer_message"
        return TransitionResult(state=next_state, next_phase_id=next_phase)

    def terminal(self, case: rf.RefundCase, state):
        return rf.terminal_outcome(case, state)

    def outcome(self, case: rf.RefundCase, terminal):
        return dict(terminal)

    def build_scorer(self, case):
        return lambda outcome: outcome

    def build_reference_providers(self, case):
        return ()

    def generator(self):
        return None


def _pin(
    component_id: str,
    kind: str,
    *,
    source_sha256: str,
    version: str = "1.0.0",
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": source_sha256,
        }
    )


def _pricing_for(provider: str, model: str) -> TokenPricing:
    if provider in {"fake", "gemini", "scripted"}:
        return TokenPricing(0.0, 0.0, 0.0, f"{provider}_refund_zero_cost_v1")
    if provider == "arena":
        return TokenPricing(
            0.0, 0.0, 0.0, f"arena_refund_unpriced_{model.replace('/', '-')}"
        )
    if provider == "openai":
        return TokenPricing(
            input_per_million=0.05,
            cached_input_per_million=0.005,
            output_per_million=0.40,
            pricing_id=f"openai_refund_default_{model}",
        )
    if provider == "openrouter":
        return TokenPricing(
            input_per_million=0.08,
            cached_input_per_million=0.016,
            output_per_million=0.18,
            pricing_id=f"openrouter_refund_default_{model.replace('/', '-')}",
        )
    raise ValueError(f"unsupported refund provider: {provider!r}")


def _profile(
    *,
    profile_id: str,
    role: str,
    provider: str,
    model: str,
    revision: str,
    prompt_id: str,
    prompt: str,
    output_schema: Mapping[str, Any],
    max_logical_actions: int,
    max_output_tokens: int = 512,
) -> AgentProfile:
    pricing = _pricing_for(provider, model)
    harness_config: dict[str, Any] = {
        "pricing_id": pricing.pricing_id,
        "pricing_sha256": pricing.content_sha256(),
        "output_schema": dict(output_schema),
    }
    if provider == "openrouter":
        harness_config["provider_metadata"] = {
            "route_provider": "DeepInfra",
            "quantization": "fp8",
            "canonical_model": revision,
            "max_prompt_price_per_million": "0.08",
            "max_completion_price_per_million": "0.18",
        }
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": profile_id,
            "model": {
                "provider": provider,
                "model": model,
                "revision": revision,
                "base_url": (
                    "https://api.openai.com/v1"
                    if provider == "openai"
                    else (
                        "https://openrouter.ai/api/v1"
                        if provider == "openrouter"
                        else (
                            "https://api.preview.arena.ai/v1"
                            if provider == "arena"
                            else None
                        )
                    )
                ),
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": harness_config},
            "prompt": {
                "prompt_id": prompt_id,
                "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": f"{role}_reasoning_default_v1",
                "effort": "low" if provider in {"openai", "openrouter"} else None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": max_output_tokens,
                "seed": 1001 if provider == "openrouter" else None,
                "top_p": 1.0 if provider == "openrouter" else None,
            },
            "budgets": {
                "max_logical_actions": max_logical_actions,
                "timeout_seconds": 90.0 if provider == "gemini" else 30.0,
                "max_cost_usd": None if provider in {"fake", "gemini", "arena"} else 0.01,
            },
            "retry_policy": {
                "max_action_attempts": 2,
                "retryable_conditions": ["length", "empty_response"],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def _load_case(case_id: str | None) -> CaseManifest:
    cases = rf.curated_case_manifests()
    selected = cases[0] if case_id is None else None
    if case_id is not None:
        selected = next((case for case in cases if case["case_id"] == case_id), None)
    if selected is None:
        known = ", ".join(case["case_id"] for case in cases)
        raise ValueError(f"unknown refund case {case_id!r}; known cases: {known}")
    return CaseManifest.from_dict(selected)


def _load_cases(
    *, case_id: str | None = None, world_seeds: tuple[int, ...] | None = None
) -> tuple[CaseManifest, ...]:
    if world_seeds is not None:
        return tuple(
            CaseManifest.from_dict(case)
            for case in rf.generated_case_manifests(world_seeds)
        )
    return (_load_case(case_id),)


def build_refund_run(
    *,
    provider: str,
    customer_model: str,
    customer_revision: str,
    support_model: str,
    support_revision: str,
    case_id: str | None = None,
    world_seeds: tuple[int, ...] | None = None,
    support_max_output_tokens: int | None = None,
    support_reasoning_effort: str | None = None,
) -> tuple[RunPlan, PluginRegistry, Mapping[str, str], Mapping[str, TokenPricing]]:
    cases = _load_cases(case_id=case_id, world_seeds=world_seeds)
    generated_panel = world_seeds is not None
    raw_family = rf.family_manifest()
    if generated_panel:
        raw_family["generator"]["generator_id"] = "refund_seeded_generator_v1"
    family = FamilyManifest.from_dict(raw_family)
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": (
                "refund_seeded_sample_v1"
                if generated_panel
                else "refund_curated_sample_v1"
            ),
            "estimand": (
                "generated_refund_case_population"
                if generated_panel
                else "fixed_refund_case"
            ),
            "target": (
                "refund_seeded_generator_v1"
                if generated_panel
                else "refund_curated_pilot"
            ),
            "selection": "seeded_simple_random" if generated_panel else "fixed_curated",
            "seeds": [0] if generated_panel else [case.world_seed for case in cases],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": ["world_seed"],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": "refund_customer_support_llm_block",
            "kind": "controlled",
            "subject_seats": ["support_agent"],
            "controlled_profiles": {"customer": "refund_customer_profile_v1"},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "refund_joint_utility_analysis_v1",
            "estimands": ["joint_utility", "customer_utility", "support_agent_utility"],
            "group_by": ["family_id", "subject_role"],
            "missingness": "report_separately",
            "resampling_unit": "cluster_id",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": ["report_reason_codes"],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": (
                "refund_seeded_experiment_v1"
                if generated_panel
                else "refund_curated_smoke_v1"
            ),
            "version": "1.0.0",
            "family_ids": [rf.FAMILY_ID],
            "case_ids": [case.case_id for case in cases],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    scripted_customer_model = "refund-scripted-customer-v1"
    customer_profile = _profile(
        profile_id="refund_customer_profile_v1",
        role="customer",
        provider="scripted",
        model=scripted_customer_model,
        revision="1.0.0",
        prompt_id="refund_customer_prompt_v1",
        prompt=CUSTOMER_PROMPT,
        output_schema=CUSTOMER_OUTPUT_SCHEMA,
        max_logical_actions=4,
    )
    support_profile = _profile(
        profile_id="refund_support_profile_v1",
        role="support_agent",
        provider=provider,
        model=support_model,
        revision=support_revision,
        prompt_id="refund_support_prompt_v1",
        prompt=SUPPORT_PROMPT,
        output_schema=SUPPORT_OUTPUT_SCHEMA,
        max_logical_actions=4,
        max_output_tokens=(
            support_max_output_tokens
            if support_max_output_tokens is not None
            else (4096 if provider == "arena" else 512)
        ),
    )
    if support_reasoning_effort is not None:
        support_profile = replace(
            support_profile,
            reasoning=replace(
                support_profile.reasoning,
                condition_id=f"support_reasoning_{support_reasoning_effort}_v1",
                effort=support_reasoning_effort,
            ),
        )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": (
                "refund_seeded_experiment_run_v1"
                if generated_panel
                else "refund_curated_smoke_run_v1"
            ),
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [
                customer_profile.profile_id,
                support_profile.profile_id,
            ],
            "seat_assignments": {
                "customer": customer_profile.profile_id,
                "support_agent": support_profile.profile_id,
            },
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    plugin = RefundV1Plugin()
    registry = PluginRegistry()
    registry.register(family, plugin)
    refund_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    env_source_sha256 = hashlib.sha256(Path(rf.__file__).read_bytes()).hexdigest()
    execution_source_sha256 = hashlib.sha256(
        Path(__file__).with_name("execution.py").read_bytes()
    ).hexdigest()
    generator_id = "refund_seeded_generator_v1" if generated_panel else "refund_curated_generator_v1"
    pins = (
        _pin("aeread.refund_v1", "family_plugin", source_sha256=refund_source_sha256),
        _pin("refund_operation_exact_match_v1", "scorer", source_sha256=env_source_sha256),
        _pin("refund_policy_oracle_v1", "reference", source_sha256=env_source_sha256),
        _pin("refund_oracle_policy_v1", "reference", source_sha256=env_source_sha256),
        _pin(generator_id, "generator", source_sha256=env_source_sha256),
        _pin("minimal_chat", "harness", source_sha256=execution_source_sha256, version="1.0"),
        _pin(
            "aeread.shared_runner.execution",
            "runtime",
            source_sha256=execution_source_sha256,
            version="0.1.0",
        ),
    )
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
    provider_capabilities = {
        provider: ProviderCapabilities(
            native_tools=False,
            structured_output=False,
            seed=provider == "openrouter",
            system_prompt=True,
            reasoning_budget=False,
            reasoning_token_report=False,
            max_context_tokens=None,
        ),
        "scripted": ProviderCapabilities(
            native_tools=False,
            structured_output=False,
            seed=False,
            system_prompt=True,
            reasoning_budget=False,
            reasoning_token_report=False,
            max_context_tokens=None,
        ),
    }
    plan = resolve_run_plan(
        families=(family,),
        cases=cases,
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(customer_profile, support_profile),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities=provider_capabilities,
    )
    pricing = {
        scripted_customer_model: _pricing_for("scripted", scripted_customer_model),
        support_model: _pricing_for(provider, support_model),
    }
    return (
        plan,
        registry,
        {
            "refund_customer_prompt_v1": CUSTOMER_PROMPT,
            "refund_support_prompt_v1": SUPPORT_PROMPT,
        },
        pricing,
    )


def _defaults_for_provider(provider: str) -> tuple[str, str]:
    if provider == "fake":
        return "refund-fixed-v1", "1.0.0"
    if provider == "gemini":
        return "gemini-3.5-flash", "gemini-3.5-flash"
    if provider == "openai":
        return "gpt-5-nano-2025-08-07", "gpt-5-nano-2025-08-07"
    if provider == "openrouter":
        return "deepseek/deepseek-v4-flash-0731", "deepseek/deepseek-v4-flash-20260731"
    if provider == "arena":
        return "claude-sonnet-4-6", "claude-sonnet-4-6"
    raise ValueError(f"unsupported provider: {provider!r}")


def _provider_client(provider: str):
    if provider == "fake":
        return FixedRefundProvider()
    if provider == "scripted":
        return ScriptedRefundCustomerProvider()
    if provider == "gemini":
        return GeminiProviderClient()
    if provider == "openai":
        return OpenAIResponsesClient()
    if provider == "openrouter":
        return OpenRouterChatClient()
    if provider == "arena":
        return ArenaChatClient()
    raise ValueError(f"unsupported provider: {provider!r}")


def _parse_world_seeds(raw: str | None) -> tuple[int, ...] | None:
    if raw is None:
        return None
    seeds: list[int] = []
    for chunk in raw.split(","):
        text = chunk.strip()
        if not text:
            continue
        seeds.append(int(text))
    if not seeds:
        raise ValueError("--world-seeds must contain at least one integer")
    if len(seeds) != len(set(seeds)):
        raise ValueError("--world-seeds must not contain duplicates")
    return tuple(seeds)


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    default_model, default_revision = _defaults_for_provider(arguments.provider)
    customer_model = arguments.customer_model or arguments.model or default_model
    support_model = arguments.support_model or arguments.model or default_model
    customer_revision = arguments.customer_revision or arguments.revision or default_revision
    support_revision = arguments.support_revision or arguments.revision or default_revision
    plan, registry, prompt_sources, pricing = build_refund_run(
        provider=arguments.provider,
        customer_model=customer_model,
        customer_revision=customer_revision,
        support_model=support_model,
        support_revision=support_revision,
        case_id=arguments.case_id,
        world_seeds=_parse_world_seeds(arguments.world_seeds),
        support_max_output_tokens=arguments.max_output_tokens,
    )
    provider_client = _provider_client(arguments.provider)
    executions = []
    for cell in plan.cells:
        execution = await execute_plan_cell(
            plan=plan,
            cell_id=cell.cell_id,
            registry=registry,
            evidence_root=arguments.output,
            prompt_sources=prompt_sources,
            providers={
                arguments.provider: provider_client,
                "scripted": ScriptedRefundCustomerProvider(),
            },
            pricing=pricing,
            episode_attempt_ordinal=arguments.attempt,
        )
        executions.append(execution)
    return {
        "run_plan_id": plan.run_plan_id,
        "cell_count": len(plan.cells),
        "results": [
            {
                "cell_id": execution.cell_id,
                "episode_attempt_id": execution.episode_attempt_id,
                "case_id": execution.episode_result.case_id,
                "outcome": execution.episode_result.outcome,
                "logical_action_count": execution.episode_result.logical_action_count,
                "total_cost_usd": execution.total_cost_usd,
                "evidence_dir": str(execution.evidence.root),
            }
            for execution in executions
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("fake", "gemini", "openai", "openrouter", "arena"),
        default="fake",
    )
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument("--customer-model")
    parser.add_argument("--customer-revision")
    parser.add_argument("--support-model")
    parser.add_argument("--support-revision")
    parser.add_argument("--case-id", default=None)
    parser.add_argument(
        "--world-seeds",
        default=None,
        help="comma-separated non-negative seeds for generated refund cases",
    )
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="tested support completion ceiling (Arena default: 4096)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--write-cases",
        action="store_true",
        help="regenerate cases/refund_v1 before running",
    )
    arguments = parser.parse_args(argv)
    if arguments.write_cases:
        rf.write_curated_cases(Path("cases/refund_v1"))
    print(canonical_json_bytes(asyncio.run(_run_cli(arguments))).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "CUSTOMER_OUTPUT_SCHEMA",
    "CUSTOMER_PROMPT",
    "FixedRefundProvider",
    "GeminiProviderClient",
    "RefundV1Plugin",
    "ScriptedRefundCustomerProvider",
    "SUPPORT_OUTPUT_SCHEMA",
    "SUPPORT_PROMPT",
    "build_refund_run",
    "main",
]
