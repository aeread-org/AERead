"""Refund V1.3 shared-runner bridge.

This module maps the refund negotiation environment onto the generic scheduler.
The customer may be either a controlled script or an LLM, and alternates with an
LLM support agent through disclosure, decision, confirmation, and execution.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

from aeread import gemini_llm
from aeread.refund_v1 import environment as rf
from aeread.refund_v1 import measurement as refund_measurement

from .task.execution import (
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
from .model_call.harness import default_harnesses
from .quality import (
    FamilyContribution,
    HumanQCApproval,
    QCCoverage,
    QCEvidenceRef,
    ResourceLimits,
)
from .registry import HarnessRegistry, PluginRegistry, ProviderCapabilities, family_contribution_sha256
from .run.resolver import (
    ImplementationPin,
    RunPlan,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
)
from .task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult
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

CONTROLLED_CUSTOMER_SCRIPTS = ("minimal", "cooperative", "resistant")
REFUND_EVALUATION_KINDS = (
    "controlled_support",
    "controlled_customer",
    "cross_play",
    "same_model_self_play",
)
SCRIPTED_SUPPORT_PROVIDER = "scripted_support"


CUSTOMER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "enum": ["state_request", "provide_info", "counter", "accept_offer", "reject_offer", "confirm_resolution", "push_back", "reject_and_escalate", "abandon"]
        },
        "message": {"type": "string"},
        "requested_amount": {"type": ["number", "null"]},
        "offer_id": {"type": ["string", "null"]},
        "target": {"type": ["string", "null"]},
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
            "enum": ["ask_info", "verify_identity", "request_evidence", "request_facts", "offer", "propose", "counter", "hold", "approve_direct", "execute_refund", "request_return", "escalate", "deny"]
        },
        "message": {"type": "string"},
        "offer_id": {"type": ["string", "null"]},
        "remedy_id": {"type": ["string", "null"]},
        "supersedes_offer_id": {"type": ["string", "null"]},
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
        "credit_amount": {"type": ["number", "null"]},
        "service_action": {
            "type": ["string", "null"],
            "enum": ["none", "paid_repair", "expedited_review", None],
        },
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
one JSON object matching the declared schema, with no markdown. When a pending
offer is shown, reply only to that offer ID. Do not invent remedies or disclose
unrequested private facts."""


SUPPORT_PROMPT = """You are the support agent in a refund negotiation.
Apply the refund policy, but remember that some customer facts are private until
the customer reveals them. Request at most three relevant facts at a time. When
the observation includes authorized_remedies, use request_facts, then propose a
listed remedy with a unique offer_id and remedy_id. Use counter only after a
push-back and include supersedes_offer_id for the rejected offer. Never propose
a remedy before its required facts are disclosed. Execute only the accepted,
current direct-refund offer exactly once, using its offer_id; never execute a
rejected, superseded, or unconfirmed offer. For legacy observations without
authorized_remedies, use the legacy policy actions. Return exactly one JSON
object matching the declared schema, with no markdown."""


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
    def _customer_response(
        observation: Mapping[str, Any], mode: str = "minimal"
    ) -> dict[str, Any]:
        pending_confirmation = observation.get("pending_confirmation")
        if isinstance(pending_confirmation, Mapping):
            return {
                "decision": "confirm_resolution",
                "message": "I confirm this refund resolution.",
                "requested_amount": observation["public_order"]["requested_amount"],
                "reveal_fields": [],
            }
        pending_offer = observation.get("pending_offer")
        if isinstance(pending_offer, Mapping):
            offer_id = observation.get("pending_offer_id")
            reaction = next(
                (
                    rule.get("response", {})
                    for rule in observation.get("customer_reaction_rules", ())
                    if isinstance(rule, Mapping)
                    and rule.get("on_remedy_id") == pending_offer.get("remedy_id")
                ),
                observation.get("customer_default_response", {"kind": "accept"}),
            )
            if isinstance(reaction, Mapping) and reaction.get("kind") == "push_back":
                return {
                    "decision": "push_back",
                    "message": "I would like the authorized alternative remedy instead.",
                    "requested_amount": observation["public_order"]["requested_amount"],
                    "offer_id": offer_id,
                    "target": reaction.get("target"),
                    "reveal_fields": [],
                }
            return {
                "decision": "accept_offer",
                "message": "I accept that resolution.",
                "requested_amount": observation["public_order"]["requested_amount"],
                "offer_id": offer_id,
                "target": None,
                "reveal_fields": [],
            }
        requested = observation.get("requested_info")
        if not isinstance(requested, list):
            requested = []
        reveal_fields = list(
            dict.fromkeys(
                field for field in requested if field in rf.CUSTOMER_REVEAL_FIELDS
            )
        )[:1 if mode == "resistant" else 3]
        if mode == "cooperative" and not reveal_fields:
            private_truth = observation.get("private_truth", {})
            reveal_fields = [
                field
                for field in ("issue_type", "condition", "evidence_provided")
                if field in private_truth
            ][:3]
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
        remedies = observation.get("authorized_remedies")
        if isinstance(remedies, list) and remedies:
            revealed = observation.get("revealed_customer_fields", {})
            required = list(
                dict.fromkeys(
                    fact
                    for remedy in remedies
                    if isinstance(remedy, Mapping)
                    for fact in remedy.get("required_fact_ids", ())
                )
            )
            missing = [fact for fact in required if fact not in revealed]
            if missing:
                return {
                    "decision": "request_facts",
                    "message": "Please provide the facts needed to assess this request.",
                    "requested_info": missing[:3],
                }
            accepted_offer_id = observation.get("accepted_offer_id")
            if isinstance(accepted_offer_id, str):
                return {
                    "decision": "execute_refund",
                    "message": "I executed the accepted refund exactly once.",
                    "offer_id": accepted_offer_id,
                    "requested_info": [],
                }
            history = observation.get("offer_history", [])
            rejected_id = observation.get("last_rejected_offer_id")
            offer_number = len(history) + 1 if isinstance(history, list) else 1
            if isinstance(rejected_id, str):
                remedy = next(
                    (
                        item for item in remedies
                        if isinstance(item, Mapping)
                        and item.get("remedy_id") in {"full_refund_cash", "alternate_remedy"}
                    ),
                    remedies[-1],
                )
                return {
                    "decision": "counter",
                    "message": "I can offer this authorized alternative remedy.",
                    "offer_id": f"offer_{offer_number}",
                    "remedy_id": remedy["remedy_id"],
                    "supersedes_offer_id": rejected_id,
                    "requested_info": [],
                }
            remedy = remedies[0]
            if remedy.get("decision") in {"deny", "escalate", "request_return"}:
                return {
                    "decision": remedy["decision"],
                    "message": "I resolved the request under the authorized policy.",
                    "remedy_id": remedy["remedy_id"],
                    "requested_info": [],
                }
            return {
                "decision": "propose",
                "message": "I can offer this authorized remedy.",
                "offer_id": f"offer_{offer_number}",
                "remedy_id": remedy["remedy_id"],
                "requested_info": [],
            }
        confirmed_refund = observation.get("confirmed_refund")
        if isinstance(confirmed_refund, Mapping):
            return {
                "decision": "execute_refund",
                "message": "I executed the confirmed refund exactly once.",
                "refund_amount": confirmed_refund["refund_amount"],
                "refund_method": confirmed_refund["refund_method"],
                "requires_human_review": False,
                "requested_info": [],
                "credit_amount": confirmed_refund.get("credit_amount", 0.0),
                "service_action": confirmed_refund.get("service_action", "none"),
            }
        revealed = observation.get("revealed_customer_fields")
        if not isinstance(revealed, Mapping):
            revealed = {}
        category = observation.get("public_order", {}).get("product", {}).get("category")
        relevant = {
            "perishable_goods": (
                "issue_type", "evidence_provided", "evidence_quality",
                "verified_identity", "payout_account_matches",
            ),
            "consumer_electronics": ("condition", "issue_type", "return_received", "verified_identity", "payout_account_matches"),
            "software": ("issue_type", "activated", "usage_minutes", "subscription_days_used", "verified_identity", "payout_account_matches"),
            "apparel": ("condition", "issue_type", "return_received", "verified_identity", "payout_account_matches"),
        }.get(category, rf.CUSTOMER_REVEAL_FIELDS[:3])
        missing = [field for field in relevant if field not in revealed]
        if missing:
            return {
                "decision": "ask_info",
                "message": "Please provide the facts relevant to this product and refund claim.",
                "refund_amount": None,
                "refund_method": None,
                "requires_human_review": None,
                "requested_info": missing,
            }
        public_order = observation["public_order"]
        customer_fields = {field.name for field in dataclasses.fields(rf.CustomerProfile)}
        customer = rf.CustomerProfile(
            **{
                **dict(public_order["customer"]),
                **{key: value for key, value in revealed.items() if key in customer_fields},
            }
        )
        case = rf.RefundCase(
            case_id="fixed_refund_runtime",
            world_seed=0,
            customer=customer,
            product=rf.ProductRecord(
                **{
                    **dict(public_order["product"]),
                    **{key: value for key, value in revealed.items() if key in {field.name for field in dataclasses.fields(rf.ProductRecord)}},
                }
            ),
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
            "credit_amount": decision.credit_amount,
            "service_action": decision.service_action,
        }


class ScriptedRefundCustomerProvider:
    """Deterministic controlled counterpart for support-agent evaluations."""

    def __init__(self, mode: str = "minimal") -> None:
        if mode not in CONTROLLED_CUSTOMER_SCRIPTS:
            raise ValueError(f"unknown scripted customer mode: {mode!r}")
        self.mode = mode

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
        output = FixedRefundProvider._customer_response(observation, self.mode)
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


class ScriptedRefundSupportProvider:
    """Deterministic policy counterpart for customer-agent evaluations."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != SCRIPTED_SUPPORT_PROVIDER:
            raise ProviderFailure(
                "provider_contract",
                f"scripted support received provider {request.provider!r}",
                retryable=False,
            )
        try:
            payload = json.loads(request.input_text)
        except json.JSONDecodeError as error:
            raise ProviderFailure("provider_contract", str(error), retryable=False) from error
        if payload.get("phase_id") != "support_response":
            raise ProviderFailure(
                "provider_contract",
                "scripted support received a non-support phase",
                retryable=False,
            )
        observation = payload.get("observation")
        if not isinstance(observation, Mapping):
            raise ProviderFailure(
                "provider_contract", "scripted support received no observation", retryable=False
            )
        output = FixedRefundProvider._support_response(observation)
        return ProviderResult(
            response_id=f"scripted_refund_support:{request.provider_call_id}",
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
    if payload.get("schema_version") == "aeread.refund.negotiation-case/1.3.0":
        private_facts = payload.get("private_facts", ())
        private = {
            fact["fact_id"]: fact["truth"]
            for fact in private_facts
            if isinstance(fact, Mapping)
            and isinstance(fact.get("fact_id"), str)
            and "truth" in fact
        }
        disclosure = payload.get("disclosure_contract", {})
        customer_script = payload.get("customer_script", {})
        evaluation = payload.get("evaluation_contract", {})
        customer_values = {
            "customer_id": "refund_customer",
            "credit_score": 650,
            "loyalty_tier": "none",
            "years_active": 0,
            "prior_refunds_12m": 0,
            "chargebacks_12m": 0,
            **{
                key: value
                for key, value in dict(order.get("customer", {})).items()
                if key in {field.name for field in dataclasses.fields(rf.CustomerProfile)}
            },
            **{
                key: value
                for key, value in private.items()
                if key in {field.name for field in dataclasses.fields(rf.CustomerProfile)}
            },
        }
        product_values = {
            "product_id": f"product_{payload.get('case_id', 'refund')}",
            **dict(order["product"]),
            **{
                key: value
                for key, value in private.items()
                if key in {field.name for field in dataclasses.fields(rf.ProductRecord)}
            },
        }
        return rf.RefundCase(
            case_id=str(payload.get("case_id", "runtime_refund_case")),
            world_seed=int(payload.get("world_seed", 0)),
            customer=rf.CustomerProfile(**customer_values),
            product=rf.ProductRecord(**product_values),
            requested_amount=float(order["requested_amount"]),
            claim_text=str(order.get("claim_text", "I would like help resolving my refund request.")),
            required_information=tuple(disclosure.get("decision_critical_fact_ids", ())),
            authorized_remedies=tuple(payload.get("authorized_remedies", ())),
            accepted_remedy_ids=tuple(evaluation.get("accepted_remedy_ids", ())),
            customer_reaction_rules=tuple(customer_script.get("reaction_rules", ())),
            customer_default_response=customer_script.get("default_response"),
            max_negotiation_rounds=int(customer_script.get("max_negotiation_rounds", 1)),
            reference_minimum_negotiation_rounds=int(
                evaluation.get("reference_minimum_negotiation_rounds", 0)
            ),
            review_status="reviewed",
        )
    private = payload["private_customer_truth"]
    customer_fields = {field.name for field in dataclasses.fields(rf.CustomerProfile)}
    product_fields = {field.name for field in dataclasses.fields(rf.ProductRecord)}
    customer_values = {
        key: value for key, value in dict(order["customer"]).items() if key in customer_fields
    }
    customer_values.update(
        {key: value for key, value in dict(private).items() if key in customer_fields}
    )
    customer = rf.CustomerProfile(**customer_values)
    product_payload = {
        **dict(order["product"]),
        **{key: value for key, value in dict(private).items() if key in product_fields},
    }
    product = rf.ProductRecord(**product_payload)
    return rf.RefundCase(
        case_id=str(payload.get("case_id", "runtime_refund_case")),
        world_seed=int(payload.get("world_seed", 0)),
        customer=customer,
        product=product,
        requested_amount=float(order["requested_amount"]),
        scenario_id=str(payload.get("scenario_id", "honest")),
        claim_text=str(payload.get("claim_text", order.get("claim_text", "I would like help resolving my refund request."))),
        required_information=tuple(
            payload.get("evaluation_contract", {}).get("required_information", ())
        ),
        expected_resolution=payload.get("evaluation_contract", {}).get("expected_resolution"),
        accepted_resolutions=tuple(
            payload.get("evaluation_contract", {}).get("accepted_resolutions", ())
        ),
        review_status=str(
            payload.get("evaluation_contract", {}).get("review_status", "generated")
        ),
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
    """Two-seat Refund V1.3 negotiation plugin for the shared scheduler."""

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
                observation_schema_by_role={
                    "customer": "refund_customer_observation_v1",
                    "support_agent": "refund_support_observation_v1",
                },
                action_schema_by_role={
                    "customer": "refund_customer_message_v1",
                    "support_agent": "refund_support_action_v1",
                },
                max_logical_actions=5,
                invalid_action_policy="family_defined",
                next_phases=("support_response",),
            ),
            PhaseSpec(
                phase_id="support_response",
                actor_selector="support_agent_only",
                mode="single",
                observation_schema_by_role={
                    "customer": "refund_customer_observation_v1",
                    "support_agent": "refund_support_observation_v1",
                },
                action_schema_by_role={
                    "customer": "refund_customer_message_v1",
                    "support_agent": "refund_support_action_v1",
                },
                max_logical_actions=5,
                invalid_action_policy="family_defined",
                next_phases=("customer_message",),
            ),
        )

    def eligible_actors(self, case, state, phase) -> tuple[str, ...]:
        if phase.phase_id == "customer_message":
            return ("customer",)
        if phase.phase_id == "support_response":
            return ("support_agent",)
        raise ValueError(f"no actors for phase {phase.phase_id!r}")

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
                "confirm_resolution",
                "push_back",
                "reject_and_escalate",
                "abandon",
            }:
                return ParseResult.failure("invalid_customer_decision")
            reveal_fields = value.get("reveal_fields")
            if not isinstance(reveal_fields, list):
                return ParseResult.failure("invalid_reveal_fields")
            return ParseResult.success(value)
        if value.get("decision") not in {
            "ask_info",
            "verify_identity",
            "request_evidence",
            "request_facts",
            "offer",
            "propose",
            "counter",
            "hold",
            "approve_direct",
            "execute_refund",
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
        return refund_measurement.build_scorer(case)

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


def _measurement_pins(case: rf.RefundCase) -> tuple[ImplementationPin, ...]:
    implementations = {}
    for leaf in refund_measurement.build_measurement_leaves(case):
        for implementation, kind in (
            (leaf.estimand.validity_domain.predicate, "reference"),
            (leaf.verifier.reference.implementation, "reference"),
            (leaf.scorer, "scorer"),
        ):
            implementations.setdefault(
                implementation.implementation_id,
                _pin(
                    implementation.implementation_id,
                    kind,
                    source_sha256=implementation.content_sha256,
                    version=implementation.version,
                ),
            )
    return tuple(implementations[key] for key in sorted(implementations))


def _pricing_for(provider: str, model: str) -> TokenPricing:
    if provider in {"fake", "gemini", "scripted", SCRIPTED_SUPPORT_PROVIDER}:
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
                "implementation": "aeread.shared_runner.task.execution",
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
                "timeout_seconds": (
                    120.0 if provider == "arena" else 90.0 if provider == "gemini" else 30.0
                ),
                "max_cost_usd": (
                    None
                    if provider
                    in {"fake", "gemini", "arena", "scripted", SCRIPTED_SUPPORT_PROVIDER}
                    else 0.01
                ),
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
    if selected is None and case_id is not None:
        fixture_path = (
            Path(__file__).parents[3] / "cases" / "refund_v1" / "dev" / f"{case_id}.json"
        )
        if fixture_path.is_file():
            return CaseManifest.from_dict(json.loads(fixture_path.read_text()))
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
    support_provider: str | None = None,
    customer_model: str,
    customer_revision: str,
    support_model: str,
    support_revision: str,
    customer_provider: str = "scripted",
    customer_script: str = "minimal",
    evaluation_kind: str | None = None,
    case_id: str | None = None,
    world_seeds: tuple[int, ...] | None = None,
    support_max_output_tokens: int | None = None,
    support_reasoning_effort: str | None = None,
    customer_max_output_tokens: int | None = None,
    customer_reasoning_effort: str | None = None,
) -> tuple[RunPlan, PluginRegistry, Mapping[str, str], Mapping[str, TokenPricing]]:
    if customer_script not in CONTROLLED_CUSTOMER_SCRIPTS:
        raise ValueError(f"unknown scripted customer profile: {customer_script!r}")
    effective_support_provider = support_provider or provider
    if evaluation_kind is None:
        evaluation_kind = (
            "controlled_support" if customer_provider == "scripted" else "cross_play"
        )
    if evaluation_kind not in REFUND_EVALUATION_KINDS:
        raise ValueError(f"unknown refund evaluation kind: {evaluation_kind!r}")
    if evaluation_kind == "controlled_support" and customer_provider != "scripted":
        raise ValueError("controlled_support requires the scripted customer provider")
    if (
        evaluation_kind == "controlled_support"
        and effective_support_provider == SCRIPTED_SUPPORT_PROVIDER
    ):
        raise ValueError("controlled_support requires an active support provider")
    if evaluation_kind == "controlled_customer":
        if customer_provider == "scripted":
            raise ValueError("controlled_customer requires an active customer provider")
        if effective_support_provider != SCRIPTED_SUPPORT_PROVIDER:
            raise ValueError(
                "controlled_customer requires the scripted support provider"
            )
    if evaluation_kind in {"cross_play", "same_model_self_play"}:
        if customer_provider == "scripted":
            raise ValueError(f"{evaluation_kind} requires an active customer provider")
        if effective_support_provider == SCRIPTED_SUPPORT_PROVIDER:
            raise ValueError(f"{evaluation_kind} requires an active support provider")
    if evaluation_kind == "same_model_self_play" and (
        customer_provider != effective_support_provider
        or customer_model != support_model
        or customer_revision != support_revision
    ):
        raise ValueError(
            "same_model_self_play requires identical provider, model, and revision "
            "for both seats"
        )
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
    scripted_customer = evaluation_kind == "controlled_support"
    scripted_support = evaluation_kind == "controlled_customer"
    customer_profile_id = (
        (
            "refund_customer_profile_v1"
            if customer_script == "minimal"
            else f"refund_customer_{customer_script}_profile_v1_3"
        )
        if evaluation_kind in {"controlled_support", "cross_play"}
        else (
            "refund_customer_active_profile_v1_3"
            if evaluation_kind == "controlled_customer"
            else "refund_customer_self_play_profile_v1_3"
        )
    )
    support_profile_id = (
        "refund_support_scripted_profile_v1_3"
        if scripted_support
        else (
            "refund_support_self_play_profile_v1_3"
            if evaluation_kind == "same_model_self_play"
            else "refund_support_profile_v1"
        )
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": f"refund_{evaluation_kind}_block",
            "kind": (
                "controlled"
                if evaluation_kind in {"controlled_support", "controlled_customer"}
                else "self_play"
                if evaluation_kind == "same_model_self_play"
                else "cross_play"
            ),
            "subject_seats": (
                ["support_agent"]
                if evaluation_kind == "controlled_support"
                else ["customer"]
                if evaluation_kind == "controlled_customer"
                else ["customer", "support_agent"]
            ),
            "controlled_profiles": (
                {"customer": customer_profile_id}
                if evaluation_kind == "controlled_support"
                else {"support_agent": support_profile_id}
                if evaluation_kind == "controlled_customer"
                else {}
            ),
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "refund_joint_utility_analysis_v1_3",
            "estimands": ["joint_utility", "customer_utility", "support_agent_utility"],
            "group_by": ["family_id", "subject_role"],
            "missingness": "report_separately",
            "resampling_unit": "cluster_id",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [
                "report_reason_codes",
                "report_constraints_by_role",
                "report_customer_profile",
            ],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": (
                "refund_seeded_experiment_v1_3"
                if generated_panel
                else "refund_curated_smoke_v1_3"
            ),
            "version": "1.3.0",
            "family_ids": [rf.FAMILY_ID],
            "case_ids": [case.case_id for case in cases],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    scripted_customer_model = f"refund-scripted-customer-{customer_script}-v1-3"
    effective_customer_model = (
        scripted_customer_model if scripted_customer else customer_model
    )
    effective_customer_revision = "1.3.0" if scripted_customer else customer_revision
    effective_support_model = (
        "refund-scripted-support-policy-v1-3" if scripted_support else support_model
    )
    effective_support_revision = "1.3.0" if scripted_support else support_revision
    customer_profile = _profile(
        profile_id=customer_profile_id,
        role="customer",
        provider=customer_provider,
        model=effective_customer_model,
        revision=effective_customer_revision,
        prompt_id="refund_customer_prompt_v1",
        prompt=CUSTOMER_PROMPT,
        output_schema=CUSTOMER_OUTPUT_SCHEMA,
        max_logical_actions=5,
        max_output_tokens=(
            customer_max_output_tokens
            if customer_max_output_tokens is not None
            else (4096 if customer_provider == "arena" else 512)
        ),
    )
    support_profile = _profile(
        profile_id=support_profile_id,
        role="support_agent",
        provider=effective_support_provider,
        model=effective_support_model,
        revision=effective_support_revision,
        prompt_id="refund_support_prompt_v1",
        prompt=SUPPORT_PROMPT,
        output_schema=SUPPORT_OUTPUT_SCHEMA,
        max_logical_actions=5,
        max_output_tokens=(
            support_max_output_tokens
            if support_max_output_tokens is not None
            else (4096 if effective_support_provider == "arena" else 512)
        ),
    )
    if support_reasoning_effort is not None and not scripted_support:
        support_profile = replace(
            support_profile,
            reasoning=replace(
                support_profile.reasoning,
                condition_id=f"support_reasoning_{support_reasoning_effort}_v1",
                effort=support_reasoning_effort,
            ),
        )
    if customer_reasoning_effort is not None and not scripted_customer:
        customer_profile = replace(
            customer_profile,
            reasoning=replace(
                customer_profile.reasoning,
                condition_id=f"customer_reasoning_{customer_reasoning_effort}_v1",
                effort=customer_reasoning_effort,
            ),
        )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": (
                "refund_seeded_experiment_run_v1_3"
                if generated_panel
                else "refund_curated_smoke_run_v1_3"
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
    registry.register(
        family,
        plugin,
        contribution=_refund_contribution(),
        evidence_root=Path("cases/refund_v1"),
    )
    refund_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    env_source_sha256 = hashlib.sha256(Path(rf.__file__).read_bytes()).hexdigest()
    execution_source_sha256 = hashlib.sha256(
        Path(__file__).with_name("task").joinpath("execution.py").read_bytes()
    ).hexdigest()
    generator_id = "refund_seeded_generator_v1" if generated_panel else "refund_curated_generator_v1"
    measurement_pins = _measurement_pins(plugin.validate_payload(cases[0].payload))
    pins = (
        _pin("aeread.refund_v1", "family_plugin", source_sha256=refund_source_sha256),
        _pin(generator_id, "generator", source_sha256=env_source_sha256),
        _pin("minimal_chat", "harness", source_sha256=execution_source_sha256, version="1.0"),
        _pin(
            "aeread.shared_runner.task.execution",
            "runtime",
            source_sha256=execution_source_sha256,
            version="0.1.0",
        ),
    ) + measurement_pins
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
    provider_capabilities = {
        profile_provider: ProviderCapabilities(
            native_tools=False,
            structured_output=False,
            seed=profile_provider == "openrouter",
            system_prompt=True,
            reasoning_budget=False,
            reasoning_token_report=False,
            max_context_tokens=None,
        )
        for profile_provider in {effective_support_provider, customer_provider}
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
        effective_support_model: _pricing_for(
            effective_support_provider, effective_support_model
        )
    }
    customer_pricing = _pricing_for(customer_provider, effective_customer_model)
    existing_customer_pricing = pricing.get(effective_customer_model)
    if (
        existing_customer_pricing is not None
        and existing_customer_pricing != customer_pricing
    ):
        raise ValueError(
            "customer and support models with the same name must use identical pricing"
        )
    pricing[effective_customer_model] = customer_pricing
    return (
        plan,
        registry,
        {
            "refund_customer_prompt_v1": CUSTOMER_PROMPT,
            "refund_support_prompt_v1": SUPPORT_PROMPT,
        },
        pricing,
    )


def build_refund_controlled_profile_panel(
    **run_arguments: Any,
) -> Mapping[str, tuple[RunPlan, PluginRegistry, Mapping[str, str], Mapping[str, TokenPricing]]]:
    """Build the three frozen-counterpart runs used for support sensitivity."""
    panel = {}
    for customer_script in CONTROLLED_CUSTOMER_SCRIPTS:
        arguments = dict(run_arguments)
        arguments["customer_provider"] = "scripted"
        arguments["customer_script"] = customer_script
        arguments["evaluation_kind"] = "controlled_support"
        panel[customer_script] = build_refund_run(**arguments)
    return panel


def build_refund_controlled_customer_run(
    **run_arguments: Any,
) -> tuple[RunPlan, PluginRegistry, Mapping[str, str], Mapping[str, TokenPricing]]:
    """Build a customer-subject run against the deterministic support policy."""
    arguments = dict(run_arguments)
    arguments["support_provider"] = SCRIPTED_SUPPORT_PROVIDER
    arguments.setdefault("customer_provider", "arena")
    arguments["evaluation_kind"] = "controlled_customer"
    return build_refund_run(**arguments)


def build_refund_same_model_self_play_run(
    **run_arguments: Any,
) -> tuple[RunPlan, PluginRegistry, Mapping[str, str], Mapping[str, TokenPricing]]:
    """Build a self-play run with one identical model profile in both roles."""
    arguments = dict(run_arguments)
    arguments["customer_provider"] = arguments["provider"]
    arguments["support_provider"] = arguments["provider"]
    arguments["customer_model"] = arguments["support_model"]
    arguments["customer_revision"] = arguments["support_revision"]
    arguments["evaluation_kind"] = "same_model_self_play"
    return build_refund_run(**arguments)


def _defaults_for_provider(provider: str) -> tuple[str, str]:
    if provider == "scripted":
        return "refund-scripted-customer-minimal-v1-3", "1.3.0"
    if provider == SCRIPTED_SUPPORT_PROVIDER:
        return "refund-scripted-support-policy-v1-3", "1.3.0"
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


def _provider_client(provider: str, *, customer_script: str = "minimal"):
    if provider == "fake":
        return FixedRefundProvider()
    if provider == "scripted":
        return ScriptedRefundCustomerProvider(customer_script)
    if provider == SCRIPTED_SUPPORT_PROVIDER:
        return ScriptedRefundSupportProvider()
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


def _refund_contribution() -> FamilyContribution:
    evidence_root = Path("cases/refund_v1")
    coverage = QCCoverage(
        coverage_id="provider_free_validation",
        required_ids=("refund_v1",),
        observed_ids=("refund_v1",),
    )
    provider_evidence = QCEvidenceRef(
        artifact_type="provider_free_conformance",
        path="qc/provider_free.json",
        sha256=hashlib.sha256((evidence_root / "qc/provider_free.json").read_bytes()).hexdigest(),
        family_id=rf.FAMILY_ID,
        family_version="1.3.0",
        profile_id=rf.FAMILY_ID,
        coverage=(coverage,),
    )
    human_evidence = QCEvidenceRef(
        artifact_type="human_qc_approval",
        path="qc/human_qc.json",
        sha256=hashlib.sha256((evidence_root / "qc/human_qc.json").read_bytes()).hexdigest(),
        family_id=rf.FAMILY_ID,
        family_version="1.3.0",
        profile_id=rf.FAMILY_ID,
        coverage=(
            QCCoverage(
                coverage_id="human_qc",
                required_ids=("refund_v1",),
                observed_ids=("refund_v1",),
            ),
        ),
    )
    contribution = FamilyContribution(
        family_id=rf.FAMILY_ID,
        family_version="1.3.0",
        plugin_id="aeread.refund_v1",
        registry_namespace="contributed.refund_v1.1.3",
        action_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        observation_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        provider_free_evidence=provider_evidence,
        resource_limits=ResourceLimits(
            max_wall_seconds=120.0,
            max_logical_actions=10,
            max_provider_calls=10,
            max_input_tokens=200_000,
            max_output_tokens=100_000,
            max_cost_usd=100.0,
        ),
        human_qc_approval=HumanQCApproval(
            reviewer_id="refund-v1-maintainers",
            decision="approved",
            contribution_sha256="0" * 64,
            evidence=human_evidence,
        ),
    )
    digest = family_contribution_sha256(contribution)
    return replace(
        contribution,
        human_qc_approval=replace(
            contribution.human_qc_approval,
            contribution_sha256=digest,
        ),
    )


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    default_model, default_revision = _defaults_for_provider(arguments.provider)
    evaluation_kind = arguments.evaluation_kind
    customer_provider = arguments.customer_provider
    if evaluation_kind == "same_model_self_play" and customer_provider == "scripted":
        customer_provider = arguments.provider
    customer_default_model, customer_default_revision = _defaults_for_provider(customer_provider)
    shared_customer_model = (
        arguments.model
        if customer_provider == arguments.provider
        else None
    )
    customer_model = (
        arguments.customer_model or shared_customer_model or customer_default_model
    )
    support_model = arguments.support_model or arguments.model or default_model
    shared_customer_revision = (
        arguments.revision
        if customer_provider == arguments.provider
        else None
    )
    customer_revision = (
        arguments.customer_revision
        or shared_customer_revision
        or customer_default_revision
    )
    support_revision = arguments.support_revision or arguments.revision or default_revision
    if evaluation_kind == "same_model_self_play":
        customer_model = arguments.customer_model or support_model
        customer_revision = arguments.customer_revision or support_revision
    plan, registry, prompt_sources, pricing = build_refund_run(
        provider=arguments.provider,
        customer_model=customer_model,
        customer_revision=customer_revision,
        support_model=support_model,
        support_revision=support_revision,
        customer_provider=customer_provider,
        customer_script=arguments.customer_script,
        evaluation_kind=evaluation_kind,
        case_id=arguments.case_id,
        world_seeds=_parse_world_seeds(arguments.world_seeds),
        support_max_output_tokens=arguments.max_output_tokens,
        support_reasoning_effort=arguments.support_reasoning_effort,
        customer_max_output_tokens=arguments.customer_max_output_tokens,
        customer_reasoning_effort=arguments.customer_reasoning_effort,
    )
    provider_clients = {arguments.provider: _provider_client(arguments.provider)}
    provider_clients.setdefault(
        customer_provider,
        _provider_client(
            customer_provider, customer_script=arguments.customer_script
        ),
    )
    executions = []
    for cell in plan.cells:
        execution = await execute_plan_cell(
            plan=plan,
            cell_id=cell.cell_id,
            registry=registry,
            evidence_root=arguments.output,
            prompt_sources=prompt_sources,
            providers=provider_clients,
            pricing=pricing,
            episode_attempt_ordinal=arguments.attempt,
        )
        case_manifest = next(
            case for case in plan.cases if case.case_id == execution.episode_result.case_id
        )
        scorer = RefundV1Plugin().build_scorer(
            RefundV1Plugin().validate_payload(case_manifest.payload)
        )
        executions.append((execution, scorer(execution.episode_result.outcome)))
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
                "measurement_scores": scores,
            }
            for execution, scores in sorted(
                executions, key=lambda item: item[0].episode_result.case_id
            )
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("fake", "gemini", "openai", "openrouter", "arena", SCRIPTED_SUPPORT_PROVIDER),
        default="fake",
        help="provider for the support-agent seat; scripted_support enables controlled-customer evaluation",
    )
    parser.add_argument(
        "--customer-provider",
        choices=("scripted", "fake", "gemini", "openai", "openrouter", "arena"),
        default="scripted",
        help="provider for the customer seat; scripted preserves controlled evaluation",
    )
    parser.add_argument(
        "--customer-script",
        choices=CONTROLLED_CUSTOMER_SCRIPTS,
        default="minimal",
        help="frozen customer behavior profile for controlled support-agent evaluation",
    )
    parser.add_argument(
        "--evaluation-kind",
        choices=REFUND_EVALUATION_KINDS,
        default=None,
        help="evaluation block; inferred from provider choices when omitted",
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
    parser.add_argument("--customer-max-output-tokens", type=int, default=None)
    parser.add_argument("--support-reasoning-effort", default=None)
    parser.add_argument("--customer-reasoning-effort", default=None)
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
    "CONTROLLED_CUSTOMER_SCRIPTS",
    "FixedRefundProvider",
    "GeminiProviderClient",
    "REFUND_EVALUATION_KINDS",
    "RefundV1Plugin",
    "ScriptedRefundCustomerProvider",
    "ScriptedRefundSupportProvider",
    "SCRIPTED_SUPPORT_PROVIDER",
    "SUPPORT_OUTPUT_SCHEMA",
    "SUPPORT_PROMPT",
    "build_refund_run",
    "build_refund_controlled_profile_panel",
    "build_refund_controlled_customer_run",
    "build_refund_same_model_self_play_run",
    "main",
]
