"""Shared-runner bridge for the native B2B procurement/RFQ case."""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread import exchange_procurement as procurement
from aeread import procurement_rfq_env as rfq
from aeread.procurement_rfq_cases import GENERATOR_ID, GENERATOR_VERSION, make_procurement_rfq_world

from .family_evaluation import finalize_family_execution
from .procurement_measurement import procurement_source_digests, score_procurement_outcome

from .execution import (
    CanonicalResponse,
    GeminiGenerateContentClient,
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from .registry import PluginRegistry
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


PROCUREMENT_RFQ_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["submit", "pass"]},
        "requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seller_id": {"type": "integer"},
                    "component": {"type": "string"},
                    "units": {"type": "integer"},
                    "disclosed_target_unit_price": {"type": ["number", "null"]},
                },
                "required": [
                    "seller_id",
                    "component",
                    "units",
                    "disclosed_target_unit_price",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["decision", "requests"],
    "additionalProperties": False,
}

PROCUREMENT_QUOTE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["quote", "no_bid"]},
        "request_id": {"type": "string"},
        "unit_price": {"type": ["number", "null"]},
        "max_units": {"type": ["integer", "null"]},
    },
    "required": ["decision", "request_id", "unit_price", "max_units"],
    "additionalProperties": False,
}

PROCUREMENT_NEGOTIATE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["counter", "pass"]},
        "counters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string"},
                    "units": {"type": "integer"},
                    "unit_price": {"type": "number"},
                },
                "required": ["quote_id", "units", "unit_price"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["decision", "counters"],
    "additionalProperties": False,
}

PROCUREMENT_COUNTER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["accept", "counter", "reject"]},
        "counter_id": {"type": "string"},
        "unit_price": {"type": ["number", "null"]},
    },
    "required": ["decision", "counter_id", "unit_price"],
    "additionalProperties": False,
}

PROCUREMENT_APPROVAL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["request", "pass"]},
        "selections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "offer_id": {"type": "string"},
                    "units": {"type": "integer"},
                },
                "required": ["offer_id", "units"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["decision", "selections"],
    "additionalProperties": False,
}

PROCUREMENT_AWARD_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["award", "walk"]},
        "approval_id": {"type": ["string", "null"]},
    },
    "required": ["decision", "approval_id"],
    "additionalProperties": False,
}


PROCUREMENT_BUYER_PROMPT = """You are the purchasing delegate for a time-sensitive
electronics production order. Follow the declared procurement mandate exactly. Search
selectively because every RFQ costs money. Do not disclose the budget or target price
unless doing so is worth the pricing consequence. Compare capacity, MOQ, lead time,
payment terms, and approval status; negotiate valid quotes; request approval for a
complete feasible award; and execute only the exact approved award. Return exactly one
JSON object for the current action schema, without markdown or explanation."""

PROCUREMENT_SUPPLIER_PROMPT = """You are a deterministic controlled supplier. Your
private unit cost must never be exposed to the buyer. Quote and respond only to your own
RFQ or counter, follow the pinned margin rule, and return exactly one JSON object for the
current action schema."""


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _seller_id(seat_id: str) -> int:
    prefix = "supplier_"
    if not isinstance(seat_id, str) or not seat_id.startswith(prefix):
        raise ValueError(f"invalid supplier seat: {seat_id!r}")
    suffix = seat_id[len(prefix) :]
    if not suffix.isdigit():
        raise ValueError(f"invalid supplier seat: {seat_id!r}")
    return int(suffix)


def _market(case: Mapping[str, Any], state: Mapping[str, Any]) -> rfq.ProcurementRFQMarket:
    return rfq.ProcurementRFQMarket.from_snapshot(
        case["world"],
        max_contacts=case["max_contacts"],
        contact_cost=case["contact_cost"],
        disclosure_anchor=case["disclosure_anchor"],
        snapshot=state,
    )


def _phase_result(result: rfq.PhaseResult | rfq.ApprovalDecision) -> dict[str, Any]:
    return dataclasses.asdict(result)


def _sequence(value: Any) -> Sequence[Any] | None:
    if isinstance(value, list):
        return value
    return None


class ProcurementRFQPlugin:
    """Native procurement family with controlled suppliers and approval binding."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != {
            "world",
            "max_contacts",
            "contact_cost",
            "disclosure_anchor",
        }:
            raise ValueError("procurement RFQ payload fields are incomplete or unexpected")
        max_contacts = payload["max_contacts"]
        if isinstance(max_contacts, bool) or not isinstance(max_contacts, int) or max_contacts <= 0:
            raise ValueError("max_contacts must be a positive integer")
        if not _finite(payload["contact_cost"]) or float(payload["contact_cost"]) <= 0:
            raise ValueError("contact_cost must be positive")
        if (
            not _finite(payload["disclosure_anchor"])
            or not 0 < float(payload["disclosure_anchor"]) <= 1
        ):
            raise ValueError("disclosure_anchor must be in (0, 1]")
        world = rfq.world_from_payload(payload["world"])
        if max_contacts < len(world.demand.units_required):
            raise ValueError("max_contacts cannot cover the component set")
        return {
            "world": world,
            "max_contacts": max_contacts,
            "contact_cost": float(payload["contact_cost"]),
            "disclosure_anchor": float(payload["disclosure_anchor"]),
        }

    def initial_state(self, case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        return rfq.ProcurementRFQMarket(
            case["world"],
            max_contacts=case["max_contacts"],
            contact_cost=case["contact_cost"],
            disclosure_anchor=case["disclosure_anchor"],
        ).snapshot()

    def phases(self, case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        contacts = case["max_contacts"]
        return (
            PhaseSpec(
                "rfq",
                "buyer",
                "single",
                {"buyer": "procurement_buyer_rfq_observation_v1"},
                {"buyer": "procurement_rfq_v1"},
                1,
                "family_defined",
                ("quote",),
            ),
            PhaseSpec(
                "quote",
                "contacted_suppliers",
                "simultaneous",
                {"supplier": "procurement_supplier_quote_observation_v1"},
                {"supplier": "procurement_quote_v1"},
                contacts,
                "family_defined",
                ("negotiate",),
            ),
            PhaseSpec(
                "negotiate",
                "buyer",
                "single",
                {"buyer": "procurement_buyer_negotiate_observation_v1"},
                {"buyer": "procurement_negotiate_v1"},
                1,
                "family_defined",
                ("counter",),
            ),
            PhaseSpec(
                "counter",
                "countered_suppliers",
                "simultaneous",
                {"supplier": "procurement_supplier_counter_observation_v1"},
                {"supplier": "procurement_counter_v1"},
                contacts,
                "family_defined",
                ("approval",),
            ),
            PhaseSpec(
                "approval",
                "buyer",
                "single",
                {"buyer": "procurement_buyer_approval_observation_v1"},
                {"buyer": "procurement_approval_v1"},
                1,
                "family_defined",
                ("award",),
            ),
            PhaseSpec(
                "award",
                "buyer",
                "single",
                {"buyer": "procurement_buyer_award_observation_v1"},
                {"buyer": "procurement_award_v1"},
                1,
                "family_defined",
                (),
            ),
        )

    def eligible_actors(self, case, state, phase) -> tuple[str, ...]:
        market = _market(case, state)
        if phase.phase_id in {"rfq", "negotiate", "approval", "award"}:
            return ("buyer_0",)
        if phase.phase_id == "quote":
            return tuple(
                f"supplier_{seller_id}"
                for seller_id in sorted({item.seller_id for item in market.rfqs.values()})
            )
        if phase.phase_id == "counter":
            return tuple(
                f"supplier_{seller_id}"
                for seller_id in sorted({item.seller_id for item in market.counters.values()})
            )
        raise ValueError(f"unknown procurement phase: {phase.phase_id!r}")

    def observe(self, case, state, seat, phase) -> dict[str, Any]:
        market = _market(case, state)
        if seat == "buyer_0":
            return market.buyer_observation()
        return market.vendor_observation(_seller_id(seat))

    def parse_action(self, case, state, seat, phase, response) -> ParseResult:
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        if not isinstance(value, dict):
            return ParseResult.failure("malformed_action")

        phase_id = phase.phase_id
        if phase_id == "rfq":
            if set(value) != {"decision", "requests"} or _sequence(value["requests"]) is None:
                return ParseResult.failure("malformed_rfq")
            if value["decision"] == "pass" and value["requests"] == []:
                return ParseResult.success({"decision": "pass", "requests": []})
            requests = []
            for item in value["requests"]:
                if not isinstance(item, dict) or set(item) != {
                    "seller_id",
                    "component",
                    "units",
                    "disclosed_target_unit_price",
                }:
                    return ParseResult.failure("malformed_rfq")
                if (
                    not isinstance(item["seller_id"], int)
                    or isinstance(item["seller_id"], bool)
                    or not isinstance(item["component"], str)
                    or not isinstance(item["units"], int)
                    or isinstance(item["units"], bool)
                    or (
                        item["disclosed_target_unit_price"] is not None
                        and not _finite(item["disclosed_target_unit_price"])
                    )
                ):
                    return ParseResult.failure("malformed_rfq")
                requests.append(dict(item))
            if value["decision"] != "submit":
                return ParseResult.failure("malformed_rfq")
            return ParseResult.success({"decision": "submit", "requests": requests})

        if phase_id == "quote":
            if set(value) != {"decision", "request_id", "unit_price", "max_units"}:
                return ParseResult.failure("malformed_quote")
            if not isinstance(value["request_id"], str):
                return ParseResult.failure("malformed_quote")
            if value["decision"] == "no_bid" and value["unit_price"] is None and value["max_units"] is None:
                return ParseResult.success(dict(value))
            if (
                value["decision"] == "quote"
                and _finite(value["unit_price"])
                and isinstance(value["max_units"], int)
                and not isinstance(value["max_units"], bool)
            ):
                return ParseResult.success(dict(value))
            return ParseResult.failure("malformed_quote")

        if phase_id == "negotiate":
            if set(value) != {"decision", "counters"} or _sequence(value["counters"]) is None:
                return ParseResult.failure("malformed_negotiate")
            if value["decision"] == "pass" and value["counters"] == []:
                return ParseResult.success({"decision": "pass", "counters": []})
            counters = []
            for item in value["counters"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"quote_id", "units", "unit_price"}
                    or not isinstance(item["quote_id"], str)
                    or not isinstance(item["units"], int)
                    or isinstance(item["units"], bool)
                    or not _finite(item["unit_price"])
                ):
                    return ParseResult.failure("malformed_negotiate")
                counters.append(dict(item))
            if value["decision"] != "counter":
                return ParseResult.failure("malformed_negotiate")
            return ParseResult.success({"decision": "counter", "counters": counters})

        if phase_id == "counter":
            if set(value) != {"decision", "counter_id", "unit_price"} or not isinstance(
                value["counter_id"], str
            ):
                return ParseResult.failure("malformed_counter")
            if value["decision"] in {"accept", "reject"} and value["unit_price"] is None:
                return ParseResult.success(dict(value))
            if value["decision"] == "counter" and _finite(value["unit_price"]):
                return ParseResult.success(dict(value))
            return ParseResult.failure("malformed_counter")

        if phase_id == "approval":
            if set(value) != {"decision", "selections"} or _sequence(value["selections"]) is None:
                return ParseResult.failure("malformed_approval")
            if value["decision"] == "pass" and value["selections"] == []:
                return ParseResult.success({"decision": "pass", "selections": []})
            selections = []
            for item in value["selections"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"offer_id", "units"}
                    or not isinstance(item["offer_id"], str)
                    or not isinstance(item["units"], int)
                    or isinstance(item["units"], bool)
                ):
                    return ParseResult.failure("malformed_approval")
                selections.append(dict(item))
            if value["decision"] != "request":
                return ParseResult.failure("malformed_approval")
            return ParseResult.success({"decision": "request", "selections": selections})

        if phase_id == "award":
            if set(value) != {"decision", "approval_id"}:
                return ParseResult.failure("malformed_award")
            if value["decision"] == "walk" and value["approval_id"] is None:
                return ParseResult.success(dict(value))
            if value["decision"] == "award" and isinstance(value["approval_id"], str):
                return ParseResult.success(dict(value))
            return ParseResult.failure("malformed_award")
        return ParseResult.failure("unknown_phase")

    def legal(self, case, state, seat, phase, action) -> LegalityResult:
        market = _market(case, state)
        try:
            if phase.phase_id == "rfq":
                if action["decision"] == "pass":
                    return LegalityResult.legal_action()
                drafts = [rfq.RFQDraft(**dict(item)) for item in action["requests"]]
                result = market.submit_rfqs(drafts)
                return (
                    LegalityResult.legal_action()
                    if result.rejected == 0
                    else LegalityResult.illegal("invalid_rfq_request")
                )
            if phase.phase_id == "quote":
                seller_id = _seller_id(seat)
                result = market.submit_quotes(
                    {seller_id: rfq.VendorQuoteAction(**dict(action))}
                )
                return (
                    LegalityResult.legal_action()
                    if result.accepted == 1
                    else LegalityResult.illegal("invalid_vendor_quote")
                )
            if phase.phase_id == "negotiate":
                if action["decision"] == "pass":
                    return LegalityResult.legal_action()
                result = market.submit_counters(
                    [rfq.CounterDraft(**dict(item)) for item in action["counters"]]
                )
                return (
                    LegalityResult.legal_action()
                    if result.rejected == 0
                    else LegalityResult.illegal("invalid_buyer_counter")
                )
            if phase.phase_id == "counter":
                seller_id = _seller_id(seat)
                result = market.submit_counter_responses(
                    {seller_id: rfq.CounterResponseAction(**dict(action))}
                )
                return (
                    LegalityResult.legal_action()
                    if result.accepted == 1
                    else LegalityResult.illegal("invalid_counter_response")
                )
            if phase.phase_id == "approval":
                if action["decision"] == "pass":
                    return LegalityResult.legal_action()
                seen: set[str] = set()
                for item in action["selections"]:
                    offer = market.final_offers.get(item["offer_id"])
                    if (
                        offer is None
                        or item["offer_id"] in seen
                        or not offer.min_units <= item["units"] <= offer.max_units
                    ):
                        return LegalityResult.illegal("invalid_offer_selection")
                    seen.add(item["offer_id"])
                return LegalityResult.legal_action()
            if phase.phase_id == "award":
                if action["decision"] == "walk":
                    return LegalityResult.legal_action()
                if (
                    market.approval is None
                    or not market.approval.approved
                    or action["approval_id"] != market.approval.approval_id
                ):
                    return LegalityResult.illegal("award_without_approval")
                return LegalityResult.legal_action()
        except (KeyError, TypeError, ValueError):
            return LegalityResult.illegal("invalid_procurement_action")
        return LegalityResult.illegal("unknown_phase")

    def step(self, case, state, phase, actions) -> TransitionResult:
        market = _market(case, state)
        phase_id = phase.phase_id
        if phase_id == "rfq":
            envelope = actions.get("buyer_0")
            drafts = []
            if envelope and envelope.valid and envelope.action["decision"] == "submit":
                drafts = [rfq.RFQDraft(**dict(item)) for item in envelope.action["requests"]]
            result: rfq.PhaseResult | rfq.ApprovalDecision = market.submit_rfqs(drafts)
            next_phase = "quote"
        elif phase_id == "quote":
            responses = {
                _seller_id(seat_id): rfq.VendorQuoteAction(**dict(envelope.action))
                for seat_id, envelope in actions.items()
                if envelope.valid
            }
            result = market.submit_quotes(responses)
            next_phase = "negotiate"
        elif phase_id == "negotiate":
            envelope = actions.get("buyer_0")
            drafts = []
            if envelope and envelope.valid and envelope.action["decision"] == "counter":
                drafts = [rfq.CounterDraft(**dict(item)) for item in envelope.action["counters"]]
            result = market.submit_counters(drafts)
            next_phase = "counter"
        elif phase_id == "counter":
            responses = {
                _seller_id(seat_id): rfq.CounterResponseAction(**dict(envelope.action))
                for seat_id, envelope in actions.items()
                if envelope.valid
            }
            result = market.submit_counter_responses(responses)
            next_phase = "approval"
        elif phase_id == "approval":
            envelope = actions.get("buyer_0")
            selections = []
            if envelope and envelope.valid and envelope.action["decision"] == "request":
                selections = [
                    rfq.OfferSelection(**dict(item)) for item in envelope.action["selections"]
                ]
            result = market.submit_approval_request(selections)
            next_phase = "award"
        elif phase_id == "award":
            envelope = actions.get("buyer_0")
            approval_id = None
            if envelope and envelope.valid and envelope.action["decision"] == "award":
                approval_id = envelope.action["approval_id"]
            result = market.submit_award(approval_id)
            next_phase = None
        else:
            raise ValueError(f"unknown procurement phase: {phase_id!r}")
        return TransitionResult(
            state=market.snapshot(),
            next_phase_id=next_phase,
            consequences=_phase_result(result),
        )

    def terminal(self, case, state) -> dict[str, Any] | None:
        market = _market(case, state)
        if not market.finished:
            return None
        economics = market.economics()
        baseline = rfq.run_scripted_rfq_baseline(
            case["world"],
            max_contacts=case["max_contacts"],
            contact_cost=case["contact_cost"],
            disclosure_anchor=case["disclosure_anchor"],
        )
        return {
            **dataclasses.asdict(economics),
            "baseline_total": baseline.buyer_surplus,
            "oracle_total": economics.buyer_surplus_upper_bound,
            "within_case_score": economics.buyer_surplus_score,
            "bound_semantics": "full_information_terms_relaxation",
        }

    def outcome(self, case, terminal) -> dict[str, Any]:
        return {"valid": True, **dict(terminal)}

    def build_scorer(self, case):
        return lambda outcome, evidence_refs=(): score_procurement_outcome(
            case, outcome, evidence_refs=evidence_refs
        )

    def build_reference_providers(self, case):
        return (
            "procurement_rfq_no_action_v1",
            "procurement_rfq_visible_baseline_v1",
            "procurement_rfq_full_info_terms_v1",
        )

    def generator(self):
        return make_procurement_rfq_world


def _scripted_result(request: ProviderRequest, output: Mapping[str, Any]) -> ProviderResult:
    text = canonical_json_bytes(output).decode("utf-8")
    return ProviderResult(
        response_id=f"scripted_{request.provider_call_id}",
        requested_model=request.model,
        resolved_model=request.revision or request.model,
        output_text=text,
        finish_reason="stop",
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        raw_response={"fixture": True, "output_text": text},
    )


def _round_down_money(value: float) -> float:
    return math.floor(value * 100.0 + 1e-9) / 100.0


def _buyer_visible_selections(observation: Mapping[str, Any]) -> list[dict[str, Any]]:
    mandate = observation["mandate"]
    directory = {
        (item["seller_id"], item["component"]): item
        for item in observation["vendor_directory"]
    }
    offers = observation["final_offers"]
    suppliers = []
    offer_by_key = {}
    for offer in offers:
        public = directory[(offer["seller_id"], offer["component"])]
        suppliers.append(
            procurement.SupplierTerms(
                seller_id=offer["seller_id"],
                component=offer["component"],
                unit_cost=offer["unit_price"],
                capacity=offer["max_units"],
                lead_time_days=public["lead_time_days"],
                moq=offer["min_units"],
                payment_terms_days=public["payment_terms_days"],
            )
        )
        offer_by_key[(offer["seller_id"], offer["component"])] = offer
    visible_world = procurement.ProcurementWorld(
        name="visible_offer_selection",
        buyer_agent=1,
        suppliers=suppliers,
        demand=procurement.DemandSpec(
            units_required=dict(mandate["units_required"]),
            deadline_days=mandate["deadline_days"],
            contract_value=mandate["contract_value"],
        ),
        authz=procurement.AuthorizationSpec(
            budget=mandate["budget"],
            approved_vendors=list(mandate["approved_vendors"]),
            signoff_threshold=mandate["signoff_threshold"],
        ),
    )
    solution = procurement.solve_min_cost_award(visible_world)
    if not solution.feasible:
        return []
    return [
        {
            "offer_id": offer_by_key[(line.seller_id, line.component)]["offer_id"],
            "units": line.units,
        }
        for line in solution.lines
    ]


class ProcurementScriptedBuyerProvider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "procurement_scripted_buyer":
            raise ProviderFailure("provider_contract", "wrong scripted buyer provider", retryable=False)
        payload = json.loads(request.input_text)
        observation = payload["observation"]
        phase = payload["phase_id"]
        if phase == "rfq":
            mandate = observation["mandate"]
            eligible = [
                item
                for item in observation["vendor_directory"]
                if item["approved"] and item["lead_time_days"] <= mandate["deadline_days"]
            ]
            eligible.sort(key=lambda item: (item["component"], item["seller_id"]))
            output = {
                "decision": "submit",
                "requests": [
                    {
                        "seller_id": item["seller_id"],
                        "component": item["component"],
                        "units": mandate["units_required"][item["component"]],
                        "disclosed_target_unit_price": None,
                    }
                    for item in eligible[: mandate["max_contacts"]]
                ],
            }
        elif phase == "negotiate":
            output = {
                "decision": "counter",
                "counters": [
                    {
                        "quote_id": quote["quote_id"],
                        "units": quote["max_units"],
                        "unit_price": _round_down_money(quote["unit_price"] * 0.8),
                    }
                    for quote in observation["opening_quotes"]
                ],
            }
        elif phase == "approval":
            selections = _buyer_visible_selections(observation)
            output = {
                "decision": "request" if selections else "pass",
                "selections": selections,
            }
        elif phase == "award":
            approval = observation["approval"]
            output = {
                "decision": "award" if approval and approval["approved"] else "walk",
                "approval_id": approval["approval_id"] if approval and approval["approved"] else None,
            }
        else:
            raise ProviderFailure("provider_contract", "scripted buyer received wrong phase", retryable=False)
        return _scripted_result(request, output)


class ProcurementScriptedSupplierProvider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "procurement_scripted_supplier":
            raise ProviderFailure(
                "provider_contract", "wrong scripted supplier provider", retryable=False
            )
        payload = json.loads(request.input_text)
        observation = payload["observation"]
        phase = payload["phase_id"]
        private_cost = float(observation["private_unit_cost"])
        if phase == "quote":
            rfq_record = observation["rfq"]
            base = math.ceil(private_cost * 1.35 * 100.0 - 1e-9) / 100.0
            target = rfq_record["disclosed_target_unit_price"]
            price = base if target is None else max(base, target * 0.95)
            output = {
                "decision": "quote",
                "request_id": rfq_record["request_id"],
                "unit_price": math.ceil(price * 100.0 - 1e-9) / 100.0,
                "max_units": min(rfq_record["units"], observation["terms"]["capacity"]),
            }
        elif phase == "counter":
            counter = observation["buyer_counter"]
            opening = observation["own_opening_quote"]
            floor = math.ceil(private_cost * 1.05 * 100.0 - 1e-9) / 100.0
            if counter["unit_price"] >= floor:
                output = {
                    "decision": "accept",
                    "counter_id": counter["counter_id"],
                    "unit_price": None,
                }
            else:
                price = math.ceil(max(floor, (opening["unit_price"] + floor) / 2) * 100 - 1e-9) / 100
                output = {
                    "decision": "counter",
                    "counter_id": counter["counter_id"],
                    "unit_price": price,
                }
        else:
            raise ProviderFailure(
                "provider_contract", "scripted supplier received wrong phase", retryable=False
            )
        return _scripted_result(request, output)


@dataclass(frozen=True, slots=True)
class ProcurementRFQSmokeSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]


def _pin(component_id: str, kind: str, digest: str, *, version: str = "1.0.0") -> ImplementationPin:
    return ImplementationPin.from_dict(
        {"component_id": component_id, "kind": kind, "version": version, "sha256": digest}
    )


def _profile(
    *,
    profile_id: str,
    provider: str,
    model: str,
    revision: str,
    prompt_id: str,
    prompt: str,
    output_schemas: Mapping[str, Mapping[str, Any]],
    pricing: TokenPricing,
    max_logical_actions: int,
    runtime: str,
    reasoning_effort: str | None = None,
    condition_id: str | None = None,
    inference_seed_base: int | None = None,
) -> AgentProfile:
    live_provider = provider in {"openrouter", "google"}
    effort = reasoning_effort or ("low" if live_provider else "none")
    if provider == "google" and effort not in {"low", "medium", "high"}:
        raise ValueError("Gemini procurement thinking effort must be low, medium, or high")
    config: dict[str, Any] = {
        "pricing_id": pricing.pricing_id,
        "pricing_sha256": pricing.content_sha256(),
        "output_schema_by_action_schema": dict(output_schemas),
    }
    if inference_seed_base is not None:
        config["request_seed_source"] = "paired_cell_v1"
        config["request_seed_base"] = inference_seed_base
    if provider == "openrouter":
        config["provider_metadata"] = {
            "route_provider": "DeepInfra",
            "quantization": "fp8",
            "canonical_model": "deepseek/deepseek-v4-flash-20260731",
            "max_prompt_price_per_million": "0.08",
            "max_completion_price_per_million": "0.18",
        }
    elif provider == "google":
        config["provider_metadata"] = {
            "canonical_model": model,
            "catalog_version": revision,
            "thinking_level": effort,
            "max_input_price_per_million": "0.75",
            "max_cached_input_price_per_million": "0.075",
            "max_output_price_per_million": "3.75",
        }
    base_url = (
        "https://openrouter.ai/api/v1"
        if provider == "openrouter"
        else (
            "https://generativelanguage.googleapis.com/v1beta"
            if provider == "google"
            else None
        )
    )
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": profile_id,
            "model": {
                "provider": provider,
                "model": model,
                "revision": revision,
                "base_url": base_url,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": config,
            },
            "prompt": {"prompt_id": prompt_id, "sha256": hashlib.sha256(prompt.encode()).hexdigest()},
            "runtime": {
                "kind": "python",
                "implementation": runtime,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": condition_id or f"reasoning_{effort}_v1",
                "effort": effort,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "top_p": 1.0 if live_provider else None,
                "max_output_tokens": (
                    2048 if provider == "openrouter" else 4096 if provider == "google" else 512
                ),
                "seed": 0 if live_provider else None,
            },
            "budgets": {
                "max_logical_actions": max_logical_actions,
                "timeout_seconds": (
                    180.0 if provider == "openrouter" else 90.0 if provider == "google" else 30.0
                ),
                "max_cost_usd": (
                    0.01 if provider == "openrouter" else 0.02 if provider == "google" else 0.001
                ),
            },
            "retry_policy": {
                "max_action_attempts": 2 if live_provider else 1,
                "retryable_conditions": ["length"] if live_provider else [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def build_procurement_rfq_smoke(
    *,
    buyer_provider: str = "procurement_scripted_buyer",
    buyer_model: str = "procurement_scripted_buyer_v1",
    buyer_revision: str = "1.0.0",
    world_seeds: Sequence[int] | None = None,
    replicates: int = 1,
    reasoning_effort: str | None = None,
    condition_id: str | None = None,
    inference_seed_base: int = 0,
) -> ProcurementRFQSmokeSetup:
    generated = world_seeds is not None
    seeds = (0,) if world_seeds is None else tuple(world_seeds)
    if (not seeds or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("world seeds must be distinct nonnegative integers")
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        raise ValueError("replicates must be a positive integer")
    if isinstance(inference_seed_base, bool) or not isinstance(inference_seed_base, int) or inference_seed_base < 0:
        raise ValueError("inference seed base must be a nonnegative integer")
    effort = reasoning_effort or ("low" if buyer_provider in {"google", "openrouter"} else "none")
    condition_id = condition_id or f"reasoning_{effort}_v1"
    repository_root = Path(__file__).resolve().parents[3]
    config_path = repository_root / "configs" / "exchange_economy" / "procurement_electronics_q3.json"
    worlds = [make_procurement_rfq_world(seed=seed) for seed in seeds] if generated else [procurement.load_procurement_world(config_path)]
    max_contacts = 5
    contact_cost = 5.0
    disclosure_anchor = 0.95
    seller_ids = sorted({terms.seller_id for terms in worlds[0].suppliers})
    max_actions = 4 + 2 * max_contacts

    family = FamilyManifest.from_dict(
        {
            "spec_version": "aeread.family/0.1",
            "family": {
                "id": "procurement_rfq_v1",
                "version": "1.0.0",
                "plugin_id": "aeread.procurement_rfq_v1",
            },
            "environment": {
                "topology": "buyer_supplier_market_with_approval",
                "phase_specs": ["rfq", "quote", "negotiate", "counter", "approval", "award"],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "buyer": {
                    "testable": True,
                    "scripted_policies": ["procurement_scripted_buyer_v1"],
                },
                "supplier": {
                    "testable": False,
                    "scripted_policies": ["procurement_scripted_supplier_v1"],
                },
            },
            "measurement": {
                "primary_estimand": "buyer_surplus",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "optimum_lower_bound": "procurement_rfq_no_action_v1",
                "comparison_baseline": "procurement_rfq_visible_baseline_v1",
                "optimum_upper_bound": "procurement_rfq_full_info_terms_v1",
                "optimum_upper_bound_kind": "full_information_relaxation",
                "bound_status": "bracketed",
                "outcome_support": "case_specific",
            },
            "scoring": {
                "scorer_id": "procurement_rfq_outcome_v1",
                "oracle_id": "procurement_rfq_full_info_terms_v1",
                "reference_provider_ids": [
                    "procurement_rfq_no_action_v1",
                    "procurement_rfq_visible_baseline_v1",
                ],
            },
            "generator": {
                "generator_id": GENERATOR_ID,
                "difficulty_knobs": ["max_contacts", "contact_cost", "vendor_terms", "approval_policy"],
            },
        }
    )
    cases = []
    for seed, world in zip(seeds, worlds):
        raw_case = {
            "spec_version": "aeread.case/0.1",
            "case_id": f"procurement_rfq_v1__evaluation__{seed}" if generated else "procurement_rfq_v1__smoke__000001",
            "family_id": "procurement_rfq_v1",
            "family_version": "1.0.0",
            "split": "evaluation" if generated else "smoke",
            "world_seed": seed,
            "seats": [
                {"id": "buyer_0", "role": "buyer"},
                *[{"id": f"supplier_{seller_id}", "role": "supplier"} for seller_id in seller_ids],
            ],
            "episode": {
                "max_logical_actions": max_actions,
                "termination": ["purchase_order", "walk_away"],
            },
            "visibility_policy": "procurement_private_supplier_costs_v1",
            "payload": {
                "world": rfq.world_to_payload(world),
                "max_contacts": max_contacts,
                "contact_cost": contact_cost,
                "disclosure_anchor": disclosure_anchor,
            },
            "provenance": {
                "generator_id": GENERATOR_ID if generated else "procurement_electronics_q3_curated",
                "generator_version": GENERATOR_VERSION,
                "review_status": "generated" if generated else "curated",
            },
            "content_sha256": "0" * 64,
        }
        raw_case["content_sha256"] = case_content_sha256(raw_case)
        cases.append(CaseManifest.from_dict(raw_case))
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": "procurement_rfq_generated_sample_v1" if generated else "procurement_rfq_smoke_sample_v1",
            "estimand": "generated_procurement_rfq_population" if generated else "fixed_procurement_rfq_smoke_case",
            "target": GENERATOR_ID if generated else "procurement_electronics_q3_curated",
            "selection": "seeded_simple_random" if generated else "fixed_curated",
            "seeds": [inference_seed_base],
            "replicates": replicates,
            "cluster_level": "procurement_world",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": ["world_seed"],
            "replicate_level": "episode_attempt",
            "panel_mode": "sampled_panel" if generated else "fixed_panel",
        }
    )
    buyer_profile_id = {
        "openrouter": "procurement_deepseek_buyer_v1",
        "google": "procurement_gemini37_buyer_v1",
    }.get(buyer_provider, "procurement_scripted_buyer_v1")
    if generated:
        buyer_profile_id = f"{buyer_profile_id}_{condition_id}"
    if buyer_provider == "openrouter":
        buyer_pricing = TokenPricing(
            0.08,
            0.016,
            0.18,
            "openrouter_deepinfra_2026-08-26_deepseek-v4-flash-0731",
        )
    elif buyer_provider == "google":
        buyer_pricing = TokenPricing(
            0.75,
            0.075,
            3.75,
            "google_ai_studio_standard_2026-08-26_gemini-3.7-flash",
        )
    else:
        buyer_pricing = TokenPricing(
            0.0,
            0.0,
            0.0,
            "procurement_scripted_buyer_zero_cost_v1",
        )
    zero_supplier = TokenPricing(0.0, 0.0, 0.0, "procurement_scripted_supplier_zero_cost_v1")
    buyer_profile = _profile(
        profile_id=buyer_profile_id,
        provider=buyer_provider,
        model=buyer_model,
        revision=buyer_revision,
        prompt_id="procurement_buyer_v1",
        prompt=PROCUREMENT_BUYER_PROMPT,
        output_schemas={
            "procurement_rfq_v1": PROCUREMENT_RFQ_OUTPUT_SCHEMA,
            "procurement_negotiate_v1": PROCUREMENT_NEGOTIATE_OUTPUT_SCHEMA,
            "procurement_approval_v1": PROCUREMENT_APPROVAL_OUTPUT_SCHEMA,
            "procurement_award_v1": PROCUREMENT_AWARD_OUTPUT_SCHEMA,
        },
        pricing=buyer_pricing,
        max_logical_actions=4,
        reasoning_effort=effort,
        condition_id=condition_id,
        inference_seed_base=inference_seed_base if generated else None,
        runtime=(
            "aeread.shared_runner.execution"
            if buyer_provider in {"openrouter", "google"}
            else "aeread.shared_runner.procurement_rfq"
        ),
    )
    supplier_profile = _profile(
        profile_id="procurement_scripted_supplier_v1",
        provider="procurement_scripted_supplier",
        model="procurement_scripted_supplier_v1",
        revision="1.0.0",
        prompt_id="procurement_supplier_v1",
        prompt=PROCUREMENT_SUPPLIER_PROMPT,
        output_schemas={
            "procurement_quote_v1": PROCUREMENT_QUOTE_OUTPUT_SCHEMA,
            "procurement_counter_v1": PROCUREMENT_COUNTER_OUTPUT_SCHEMA,
        },
        pricing=zero_supplier,
        max_logical_actions=2 * max_contacts,
        runtime="aeread.shared_runner.procurement_rfq",
    )
    supplier_seats = [f"supplier_{seller_id}" for seller_id in seller_ids]
    block = EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": "procurement_controlled_suppliers_smoke",
            "kind": "controlled",
            "subject_seats": ["buyer_0"],
            "controlled_profiles": {
                seat: "procurement_scripted_supplier_v1" for seat in supplier_seats
            },
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "procurement_rfq_generated_analysis_v1" if generated else "procurement_rfq_smoke_analysis_v1",
            "estimands": [
                "buyer_surplus",
                "social_welfare",
                "supplier_margin",
                "disclosure_quote_uplift",
            ],
            "group_by": ["family_id", "subject_role"],
            "missingness": "report_separately",
            "resampling_unit": "cluster_id",
            "uncertainty": "cluster_bootstrap_95" if generated else "none",
            "multiplicity": "none",
            "sensitivity": ["report_approval_violations"],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": "procurement_rfq_generated_v1" if generated else "procurement_rfq_smoke_v1",
            "version": "1.0.0",
            "family_ids": ["procurement_rfq_v1"],
            "case_ids": [case.case_id for case in cases],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    assignments = {
        "buyer_0": buyer_profile_id,
        **{seat: "procurement_scripted_supplier_v1" for seat in supplier_seats},
    }
    run_spec = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": "procurement_rfq_smoke_run_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [
                buyer_profile_id,
                "procurement_scripted_supplier_v1",
            ],
            "seat_assignments": assignments,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    plugin = ProcurementRFQPlugin()
    registry = PluginRegistry()
    registry.register(family, plugin)
    execution_source = Path(__file__).with_name("execution.py").read_bytes()
    digests = procurement_source_digests()
    execution_digest = hashlib.sha256(execution_source).hexdigest()
    pins = [
        _pin("aeread.procurement_rfq_v1", "family_plugin", digests["combined"]),
        _pin("procurement_rfq_outcome_v1", "scorer", digests["combined"]),
        _pin("procurement_rfq_no_action_v1", "reference", digests["reference"]),
        _pin("procurement_rfq_visible_baseline_v1", "reference", digests["reference"]),
        _pin("procurement_rfq_full_info_terms_v1", "reference", digests["reference"]),
        _pin(GENERATOR_ID, "generator", digests["generator"]),
        _pin("minimal_chat", "harness", execution_digest, version="1.0"),
        _pin(
            "aeread.shared_runner.procurement_rfq",
            "runtime",
            digests["runtime"],
            version="0.1.0",
        ),
    ]
    if buyer_provider in {"openrouter", "google"}:
        pins.append(
            _pin(
                "aeread.shared_runner.execution",
                "runtime",
                execution_digest,
                version="0.1.0",
            )
        )
    plan = resolve_run_plan(
        families=(family,),
        cases=tuple(cases),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(buyer_profile, supplier_profile),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
    )
    return ProcurementRFQSmokeSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            "procurement_buyer_v1": PROCUREMENT_BUYER_PROMPT,
            "procurement_supplier_v1": PROCUREMENT_SUPPLIER_PROMPT,
        },
        pricing={
            buyer_model: buyer_pricing,
            "procurement_scripted_supplier_v1": zero_supplier,
        },
    )


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.provider == "openrouter":
        buyer_provider = "openrouter"
        buyer_model = arguments.model or "deepseek/deepseek-v4-flash-0731"
        buyer_revision = arguments.revision or "deepseek/deepseek-v4-flash-20260731"
        buyer_client = OpenRouterChatClient()
    elif arguments.provider == "gemini":
        buyer_provider = "google"
        buyer_model = arguments.model or "gemini-3.7-flash"
        buyer_revision = arguments.revision or "3.7-flash-08-2026"
        buyer_client = GeminiGenerateContentClient()
    else:
        buyer_provider = "procurement_scripted_buyer"
        buyer_model = "procurement_scripted_buyer_v1"
        buyer_revision = "1.0.0"
        buyer_client = ProcurementScriptedBuyerProvider()
    setup = build_procurement_rfq_smoke(
        buyer_provider=buyer_provider,
        buyer_model=buyer_model,
        buyer_revision=buyer_revision,
    )
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=arguments.output,
        prompt_sources=setup.prompt_sources,
        providers={
            buyer_provider: buyer_client,
            "procurement_scripted_supplier": ProcurementScriptedSupplierProvider(),
        },
        pricing=setup.pricing,
        episode_attempt_ordinal=arguments.attempt,
    )
    receipt = finalize_family_execution(setup=setup, execution=execution)
    return {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "logical_action_count": execution.episode_result.logical_action_count,
        "total_cost_usd": execution.total_cost_usd,
        "evidence_dir": str(execution.evidence.root),
        "receipt_path": str(execution.evidence.root / "evaluation_receipt.json"),
        "receipt_sha256": receipt.receipt_sha256,
        "inclusion_status": receipt.inclusion_status,
        "replay_level": receipt.replay_level,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("scripted", "openrouter", "gemini"),
        default="scripted",
    )
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    print(canonical_json_bytes(asyncio.run(_run_cli(arguments))).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROCUREMENT_APPROVAL_OUTPUT_SCHEMA",
    "PROCUREMENT_AWARD_OUTPUT_SCHEMA",
    "PROCUREMENT_COUNTER_OUTPUT_SCHEMA",
    "PROCUREMENT_NEGOTIATE_OUTPUT_SCHEMA",
    "PROCUREMENT_QUOTE_OUTPUT_SCHEMA",
    "PROCUREMENT_RFQ_OUTPUT_SCHEMA",
    "ProcurementRFQPlugin",
    "ProcurementRFQSmokeSetup",
    "ProcurementScriptedBuyerProvider",
    "ProcurementScriptedSupplierProvider",
    "build_procurement_rfq_smoke",
    "main",
]
