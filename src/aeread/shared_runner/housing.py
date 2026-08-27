"""Executable Housing V1 bridge and one-cell R4 admission fixture.

The economic state machine remains owned by :mod:`aeread.housing_env`.  This
module translates its contact/respond/commit contract into the generic shared
runner hooks, keeps tenant and landlord observations private, and supplies a
deterministic controlled-landlord provider.
"""
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

from aeread import housing_env as hz

from .execution import (
    CanonicalResponse,
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


HOUSING_CONTACT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["offer", "pass"]},
        "listing_id": {"type": ["integer", "null"]},
        "rent": {"type": ["number", "null"]},
    },
    "required": ["decision", "listing_id", "rent"],
    "additionalProperties": False,
}

HOUSING_RESPOND_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["accept", "counter", "reject_all"]},
        "offer_id": {"type": ["string", "null"]},
        "counter_rent": {"type": ["number", "null"]},
    },
    "required": ["decision", "offer_id", "counter_rent"],
    "additionalProperties": False,
}

HOUSING_COMMIT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["sign", "walk", "pass"]},
        "hold_id": {"type": ["string", "null"]},
    },
    "required": ["decision", "hold_id"],
    "additionalProperties": False,
}

HOUSING_TENANT_PROMPT = """You are one tenant in a scarce housing market.
Use only your private observation and the public board. Other tenants' values and
landlords' reservation costs are private. Return exactly one JSON object for the
declared action schema. In housing_contact_v1, either offer one open listing at a
rent you can justify or pass. In housing_commit_v1, sign or walk only the exact
immutable hold_id shown in active_hold; pass when no hold exists. Do not add
markdown or explanation."""

HOUSING_LANDLORD_PROMPT = """You are a deterministic controlled landlord.
Respond only to offers in your private inbox and create at most one binding hold.
Return exactly one JSON object for housing_respond_v1."""


def _seat_index(seat_id: str, prefix: str) -> int:
    marker = prefix + "_"
    if not isinstance(seat_id, str) or not seat_id.startswith(marker):
        raise ValueError(f"invalid {prefix} seat id: {seat_id!r}")
    suffix = seat_id[len(marker) :]
    if not suffix.isdigit():
        raise ValueError(f"invalid {prefix} seat id: {seat_id!r}")
    return int(suffix)


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _snapshot_market(market: hz.HousingMarket) -> dict[str, Any]:
    return {
        "round_index": market.round_index,
        "phase": market.phase,
        "pairs": [list(pair) for pair in market.pairs],
        "signed_rents": [
            {"tenant_id": tenant_id, "rent": rent}
            for tenant_id, rent in sorted(market.signed_rent.items())
        ],
        "taken_listing_ids": sorted(market._taken),
        "matched_tenant_ids": sorted(market._matched),
        "offers": [
            {
                "listing_id": listing_id,
                "items": [dataclasses.asdict(offer) for offer in offers],
            }
            for listing_id, offers in sorted(market._offers.items())
        ],
        "holds": [dataclasses.asdict(hold) for _, hold in sorted(market._holds.items())],
        "rejected": [
            {"tenant_id": tenant_id, "listing_ids": sorted(listing_ids)}
            for tenant_id, listing_ids in sorted(market.rejected.items())
        ],
        "wasted_contacts": market.wasted_contacts,
    }


def _restore_market(family_case: Mapping[str, Any], state: Mapping[str, Any]) -> hz.HousingMarket:
    market = hz.HousingMarket(family_case["world"], rounds=family_case["rounds"])
    market.round_index = int(state["round_index"])
    market.phase = str(state["phase"])
    market.pairs = [tuple(pair) for pair in state["pairs"]]
    market.signed_rent = {
        int(item["tenant_id"]): float(item["rent"])
        for item in state["signed_rents"]
    }
    market._taken = {int(value) for value in state["taken_listing_ids"]}
    market._matched = {int(value) for value in state["matched_tenant_ids"]}
    market._offers = {
        int(item["listing_id"]): tuple(hz.Offer(**dict(offer)) for offer in item["items"])
        for item in state["offers"]
    }
    market._holds = {
        int(item["tenant_id"]): hz.Hold(**dict(item)) for item in state["holds"]
    }
    market.rejected = {
        int(item["tenant_id"]): {int(value) for value in item["listing_ids"]}
        for item in state["rejected"]
    }
    market.wasted_contacts = int(state["wasted_contacts"])
    return market


def _phase_consequences(result: hz.PhaseResult) -> dict[str, Any]:
    return {
        "phase": result.phase,
        "verdicts": [
            dataclasses.asdict(verdict)
            for _, verdict in sorted(result.verdicts.items(), key=lambda item: str(item[0]))
        ],
        "inbox": [
            {
                "listing_id": listing_id,
                "offers": [dataclasses.asdict(offer) for offer in offers],
            }
            for listing_id, offers in sorted(result.inbox.items())
        ],
        "holds": [
            dataclasses.asdict(hold) for _, hold in sorted(result.holds.items())
        ],
    }


class HousingV1Plugin:
    """Strict Housing V1 adapter for the generic family-plugin boundary."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("housing payload must be a mapping")
        expected = {
            "world_kind",
            "world_seed",
            "num_tenants",
            "num_listings",
            "rounds",
            "common_weight",
        }
        if set(payload) != expected:
            raise ValueError("housing payload fields are incomplete or unexpected")
        if payload["world_kind"] != "bid":
            raise ValueError("only the pinned bid world is supported")
        integers: dict[str, int] = {}
        for field, minimum in (
            ("world_seed", 0),
            ("num_tenants", 1),
            ("num_listings", 1),
            ("rounds", 1),
        ):
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field} must be an integer >= {minimum}")
            integers[field] = value
        common_weight = payload["common_weight"]
        if not _finite_number(common_weight) or not 0.0 <= float(common_weight) <= 1.0:
            raise ValueError("common_weight must be between zero and one")
        world = hz.make_bid_world(
            integers["num_tenants"],
            integers["num_listings"],
            seed=integers["world_seed"],
            common_weight=float(common_weight),
        )
        return {**integers, "common_weight": float(common_weight), "world": world}

    def initial_state(self, case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        return _snapshot_market(hz.HousingMarket(case["world"], rounds=case["rounds"]))

    def phases(self, case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        tenant_budget = case["num_tenants"] * case["rounds"]
        landlord_budget = case["num_listings"] * case["rounds"]
        return (
            PhaseSpec(
                phase_id="contact",
                actor_selector="unmatched_tenants",
                mode="simultaneous",
                observation_schema_by_role={"tenant": "housing_tenant_contact_observation_v1"},
                action_schema_by_role={"tenant": "housing_contact_v1"},
                max_logical_actions=tenant_budget,
                invalid_action_policy="family_defined",
                next_phases=("respond",),
            ),
            PhaseSpec(
                phase_id="respond",
                actor_selector="open_landlords",
                mode="simultaneous",
                observation_schema_by_role={"landlord": "housing_landlord_respond_observation_v1"},
                action_schema_by_role={"landlord": "housing_respond_v1"},
                max_logical_actions=landlord_budget,
                invalid_action_policy="family_defined",
                next_phases=("commit",),
            ),
            PhaseSpec(
                phase_id="commit",
                actor_selector="unmatched_tenants",
                mode="simultaneous",
                observation_schema_by_role={"tenant": "housing_tenant_commit_observation_v1"},
                action_schema_by_role={"tenant": "housing_commit_v1"},
                max_logical_actions=tenant_budget,
                invalid_action_policy="family_defined",
                next_phases=("contact",),
            ),
        )

    def eligible_actors(self, case, state, phase) -> tuple[str, ...]:
        market = _restore_market(case, state)
        if phase.phase_id in {"contact", "commit"}:
            return tuple(f"tenant_{tenant_id}" for tenant_id in market.unmatched_tenants())
        if phase.phase_id == "respond":
            return tuple(f"landlord_{listing_id}" for listing_id in market.open_listings())
        raise ValueError(f"unknown housing phase: {phase.phase_id!r}")

    def observe(self, case, state, seat, phase) -> dict[str, Any]:
        market = _restore_market(case, state)
        if phase.phase_id in {"contact", "commit"}:
            return market.tenant_observation(_seat_index(seat, "tenant"))
        if phase.phase_id == "respond":
            return market.landlord_observation(_seat_index(seat, "landlord"))
        raise ValueError(f"unknown housing phase: {phase.phase_id!r}")

    def parse_action(self, case, state, seat, phase, response) -> ParseResult:
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        if not isinstance(value, dict):
            return ParseResult.failure("malformed_action")

        if phase.phase_id == "contact":
            if set(value) != {"decision", "listing_id", "rent"}:
                return ParseResult.failure("malformed_contact")
            if value["decision"] == "pass" and value["listing_id"] is None and value["rent"] is None:
                return ParseResult.success({"decision": "pass"})
            if (
                value["decision"] == "offer"
                and isinstance(value["listing_id"], int)
                and not isinstance(value["listing_id"], bool)
                and _finite_number(value["rent"])
            ):
                return ParseResult.success(
                    {
                        "decision": "offer",
                        "listing_id": value["listing_id"],
                        "rent": float(value["rent"]),
                    }
                )
            return ParseResult.failure("malformed_contact")

        if phase.phase_id == "respond":
            if set(value) != {"decision", "offer_id", "counter_rent"}:
                return ParseResult.failure("malformed_response")
            decision = value["decision"]
            if decision == "reject_all" and value["offer_id"] is None and value["counter_rent"] is None:
                return ParseResult.success({"decision": "reject_all"})
            if decision == "accept" and isinstance(value["offer_id"], str) and value["counter_rent"] is None:
                return ParseResult.success(
                    {"decision": "accept", "offer_id": value["offer_id"]}
                )
            if (
                decision == "counter"
                and isinstance(value["offer_id"], str)
                and _finite_number(value["counter_rent"])
            ):
                return ParseResult.success(
                    {
                        "decision": "counter",
                        "offer_id": value["offer_id"],
                        "counter_rent": float(value["counter_rent"]),
                    }
                )
            return ParseResult.failure("malformed_response")

        if phase.phase_id == "commit":
            if set(value) != {"decision", "hold_id"}:
                return ParseResult.failure("malformed_commit")
            if value["decision"] == "pass" and value["hold_id"] is None:
                return ParseResult.success({"decision": "pass"})
            if value["decision"] in {"sign", "walk"} and isinstance(value["hold_id"], str):
                return ParseResult.success(
                    {"decision": value["decision"], "hold_id": value["hold_id"]}
                )
            return ParseResult.failure("malformed_commit")

        return ParseResult.failure("unknown_phase")

    def legal(self, case, state, seat, phase, action) -> LegalityResult:
        market = _restore_market(case, state)
        decision = action["decision"]
        if decision in {"pass", "reject_all"}:
            return LegalityResult.legal_action()
        if phase.phase_id == "contact":
            tenant_id = _seat_index(seat, "tenant")
            if tenant_id not in market.unmatched_tenants():
                return LegalityResult.illegal("unavailable_tenant")
            if action["listing_id"] not in market.open_listings():
                return LegalityResult.illegal("unavailable_listing")
            if action["rent"] < 0:
                return LegalityResult.illegal("invalid_rent")
            return LegalityResult.legal_action()
        if phase.phase_id == "respond":
            listing_id = _seat_index(seat, "landlord")
            offer_ids = {
                offer.offer_id for offer in market._offers.get(listing_id, ())
            }
            if action["offer_id"] not in offer_ids:
                return LegalityResult.illegal("unknown_offer")
            if decision == "counter" and action["counter_rent"] < 0:
                return LegalityResult.illegal("invalid_rent")
            return LegalityResult.legal_action()
        if phase.phase_id == "commit":
            tenant_id = _seat_index(seat, "tenant")
            hold = market.active_holds().get(tenant_id)
            if hold is None or hold.hold_id != action["hold_id"]:
                return LegalityResult.illegal("unknown_hold")
            return LegalityResult.legal_action()
        return LegalityResult.illegal("unknown_phase")

    def step(self, case, state, phase, actions) -> TransitionResult:
        market = _restore_market(case, state)
        if phase.phase_id == "contact":
            offers: dict[int, tuple[int, float]] = {}
            for seat_id, envelope in actions.items():
                if envelope.valid and envelope.action["decision"] == "offer":
                    offers[_seat_index(seat_id, "tenant")] = (
                        envelope.action["listing_id"],
                        envelope.action["rent"],
                    )
            result = market.submit_offers(offers)
            next_phase = "respond"
        elif phase.phase_id == "respond":
            responses: dict[int, dict[int, tuple[str, float | None]]] = {}
            for seat_id, envelope in actions.items():
                if not envelope.valid:
                    continue
                listing_id = _seat_index(seat_id, "landlord")
                inbox = market._offers.get(listing_id, ())
                action = envelope.action
                if action["decision"] == "reject_all":
                    responses[listing_id] = {
                        offer.tenant_id: ("reject", None) for offer in inbox
                    }
                    continue
                chosen = next(
                    offer for offer in inbox if offer.offer_id == action["offer_id"]
                )
                per_listing = {
                    offer.tenant_id: ("reject", None) for offer in inbox
                }
                if action["decision"] == "accept":
                    per_listing[chosen.tenant_id] = ("accept", None)
                else:
                    per_listing[chosen.tenant_id] = (
                        "counter",
                        action["counter_rent"],
                    )
                responses[listing_id] = per_listing
            result = market.submit_responses(responses)
            next_phase = "commit"
        elif phase.phase_id == "commit":
            commits: dict[int, tuple[str, str]] = {}
            for seat_id, envelope in actions.items():
                if envelope.valid and envelope.action["decision"] in {"sign", "walk"}:
                    commits[_seat_index(seat_id, "tenant")] = (
                        envelope.action["decision"],
                        envelope.action["hold_id"],
                    )
            result = market.submit_commits(commits)
            next_phase = "contact"
        else:
            raise ValueError(f"unknown housing phase: {phase.phase_id!r}")
        return TransitionResult(
            state=_snapshot_market(market),
            next_phase_id=next_phase,
            consequences=_phase_consequences(result),
        )

    def terminal(self, case, state) -> dict[str, Any] | None:
        market = _restore_market(case, state)
        if not market.finished:
            return None
        economics = market.economics()
        oracle = hz.assignment_oracle(market.world.surplus)
        baseline = hz.run_scripted_market(
            market.world,
            rounds=case["rounds"],
            strategy="adaptive",
        )
        score = (
            economics.social_welfare / oracle.total if oracle.total > 0 else None
        )
        return {
            "reason": "deadline" if market.round_index >= market.rounds else "allocation",
            "assignment_pairs": [list(pair) for pair in economics.assignment.pairs],
            "signed_rents": [
                {"tenant_id": tenant_id, "rent": rent}
                for tenant_id, rent in sorted(economics.signed_rents.items())
            ],
            "tenant_payoffs": {
                f"tenant_{tenant_id}": payoff
                for tenant_id, payoff in sorted(economics.tenant_payoffs.items())
            },
            "landlord_payoffs": {
                f"landlord_{listing_id}": payoff
                for listing_id, payoff in sorted(economics.landlord_payoffs.items())
            },
            "social_welfare": economics.social_welfare,
            "feasible_floor": 0.0,
            "baseline_total": baseline.total,
            "oracle_total": oracle.total,
            "within_case_score": score,
            "ir_violations": list(economics.ir_violations),
            "wasted_contacts": market.wasted_contacts,
            "bound_semantics": "full_information_allocation_relaxation",
        }

    def outcome(self, case, terminal) -> dict[str, Any]:
        return {"valid": True, **dict(terminal)}

    def build_scorer(self, case):
        return lambda outcome: outcome["social_welfare"]

    def build_reference_providers(self, case):
        return (
            "housing_feasible_zero_v1",
            "housing_adaptive_v1",
            "housing_exact_assignment_v1",
        )

    def generator(self):
        return hz.make_bid_world


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


class HousingScriptedTenantProvider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "housing_scripted_tenant":
            raise ProviderFailure(
                "provider_contract", "wrong scripted tenant provider", retryable=False
            )
        payload = json.loads(request.input_text)
        observation = payload["observation"]
        if payload["phase_id"] == "contact":
            values = observation["private_values"]
            candidates = [
                row for row in observation["board"] if row["status"] == "OPEN"
            ]
            viable = [
                row
                for row in candidates
                if values[row["listing_id"]] > row["rent_asked"]
            ]
            if not viable:
                output = {"decision": "pass", "listing_id": None, "rent": None}
            else:
                chosen = max(
                    viable,
                    key=lambda row: values[row["listing_id"]] - row["rent_asked"],
                )
                listing_id = chosen["listing_id"]
                output = {
                    "decision": "offer",
                    "listing_id": listing_id,
                    "rent": min(values[listing_id], chosen["rent_asked"] + 1.0),
                }
        elif payload["phase_id"] == "commit":
            hold = observation.get("active_hold")
            if not hold:
                output = {"decision": "pass", "hold_id": None}
            else:
                listing_id = hold["listing_id"]
                decision = (
                    "sign"
                    if hold["rent"] <= observation["private_values"][listing_id]
                    else "walk"
                )
                output = {"decision": decision, "hold_id": hold["hold_id"]}
        else:
            raise ProviderFailure(
                "provider_contract", "scripted tenant received wrong phase", retryable=False
            )
        return _scripted_result(request, output)


class HousingScriptedLandlordProvider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "housing_scripted_landlord":
            raise ProviderFailure(
                "provider_contract", "wrong scripted landlord provider", retryable=False
            )
        payload = json.loads(request.input_text)
        if payload["phase_id"] != "respond":
            raise ProviderFailure(
                "provider_contract", "scripted landlord received wrong phase", retryable=False
            )
        observation = payload["observation"]
        inbox = observation["inbox"]
        if not inbox:
            output = {
                "decision": "reject_all",
                "offer_id": None,
                "counter_rent": None,
            }
        else:
            viable = [
                offer for offer in inbox if offer["rent"] >= observation["private_cost"]
            ]
            if viable:
                chosen = max(viable, key=lambda offer: (offer["rent"], -offer["tenant_id"]))
                output = {
                    "decision": "accept",
                    "offer_id": chosen["offer_id"],
                    "counter_rent": None,
                }
            else:
                chosen = max(inbox, key=lambda offer: (offer["rent"], -offer["tenant_id"]))
                output = {
                    "decision": "counter",
                    "offer_id": chosen["offer_id"],
                    "counter_rent": round(
                        (chosen["rent"] + observation["listing"]["rent_asked"]) / 2.0,
                        2,
                    ),
                }
        return _scripted_result(request, output)


@dataclass(frozen=True, slots=True)
class HousingSmokeSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]


@dataclass(frozen=True, slots=True)
class OpenRouterRoutePin:
    """Exact OpenRouter endpoint identity and price ceiling sealed into a plan."""

    provider: str
    quantization: str
    canonical_model: str
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    pricing_id: str

    def __post_init__(self) -> None:
        for name in ("provider", "quantization", "canonical_model", "pricing_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        self.token_pricing()

    def token_pricing(self) -> TokenPricing:
        return TokenPricing(
            self.input_per_million,
            self.cached_input_per_million,
            self.output_per_million,
            self.pricing_id,
        )

    def provider_metadata(self) -> dict[str, str]:
        return {
            "route_provider": self.provider,
            "quantization": self.quantization,
            "canonical_model": self.canonical_model,
            "max_prompt_price_per_million": format(self.input_per_million, ".15g"),
            "max_completion_price_per_million": format(
                self.output_per_million, ".15g"
            ),
        }


DEEPINFRA_HOUSING_ROUTE = OpenRouterRoutePin(
    provider="DeepInfra",
    quantization="fp8",
    canonical_model="deepseek/deepseek-v4-flash-20260731",
    input_per_million=0.08,
    cached_input_per_million=0.016,
    output_per_million=0.18,
    pricing_id="openrouter_deepinfra_2026-08-26_deepseek-v4-flash-0731",
)


def _pin(component_id: str, kind: str, digest: str, version: str = "1.0.0") -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": digest,
        }
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
    world_seed: int,
    reasoning_condition_id: str = "reasoning_low_v1",
    reasoning_effort: str | None = "low",
    request_seed_base: int | None = None,
    max_output_tokens: int | None = None,
    timeout_seconds: float | None = None,
    openrouter_route: OpenRouterRoutePin = DEEPINFRA_HOUSING_ROUTE,
) -> AgentProfile:
    config: dict[str, Any] = {
        "pricing_id": pricing.pricing_id,
        "pricing_sha256": pricing.content_sha256(),
        "output_schema_by_action_schema": dict(output_schemas),
    }
    if provider == "openrouter":
        config["provider_metadata"] = openrouter_route.provider_metadata()
    if request_seed_base is not None:
        config["request_seed_source"] = "paired_cell_v1"
        config["request_seed_base"] = request_seed_base
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": profile_id,
            "model": {
                "provider": provider,
                "model": model,
                "revision": revision,
                "base_url": "https://openrouter.ai/api/v1" if provider == "openrouter" else None,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": config},
            "prompt": {
                "prompt_id": prompt_id,
                "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            },
            "runtime": {"kind": "python", "implementation": runtime, "version": "0.1.0"},
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": reasoning_condition_id,
                "effort": reasoning_effort,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "top_p": 1.0 if provider == "openrouter" else None,
                "max_output_tokens": (
                    max_output_tokens
                    if max_output_tokens is not None
                    else (512 if provider == "openrouter" else 256)
                ),
                "seed": (
                    world_seed
                    if provider == "openrouter" and request_seed_base is None
                    else None
                ),
            },
            "budgets": {
                "max_logical_actions": max_logical_actions,
                "timeout_seconds": (
                    timeout_seconds if timeout_seconds is not None else 30.0
                ),
                "max_cost_usd": 0.01 if provider == "openrouter" else 0.001,
            },
            "retry_policy": {
                "max_action_attempts": (
                    4
                    if provider == "openrouter" and request_seed_base is not None
                    else (2 if provider == "openrouter" else 1)
                ),
                "retryable_conditions": (
                    ["length", "rate_limit", "provider_5xx"]
                    if provider == "openrouter" and request_seed_base is not None
                    else (["length"] if provider == "openrouter" else [])
                ),
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def build_housing_smoke(
    *,
    tenant_provider: str,
    tenant_model: str,
    tenant_revision: str,
    world_seed: int = 41001,
    num_tenants: int = 2,
    num_listings: int = 1,
    rounds: int = 1,
    world_seeds: Sequence[int] | None = None,
    replicates: int = 1,
    reasoning_condition_id: str = "reasoning_low_v1",
    reasoning_effort: str | None = "low",
    inference_seed_base: int | None = None,
    openrouter_route: OpenRouterRoutePin = DEEPINFRA_HOUSING_ROUTE,
) -> HousingSmokeSetup:
    selected_world_seeds = (
        (world_seed,) if world_seeds is None else tuple(world_seeds)
    )
    if not selected_world_seeds:
        raise ValueError("world_seeds must not be empty")
    if len(set(selected_world_seeds)) != len(selected_world_seeds):
        raise ValueError("world_seeds must be unique")
    if replicates < 1:
        raise ValueError("replicates must be positive")
    experiment_mode = world_seeds is not None
    if experiment_mode and inference_seed_base is None:
        raise ValueError("experiment plans require inference_seed_base")
    if (
        tenant_provider == "openrouter"
        and tenant_revision != openrouter_route.canonical_model
    ):
        raise ValueError("tenant_revision must match the sealed OpenRouter route model")
    family = FamilyManifest.from_dict(
        {
            "spec_version": "aeread.family/0.1",
            "family": {"id": "housing_v1", "version": "1.0.0", "plugin_id": "aeread.housing_v1"},
            "environment": {
                "topology": "market_with_private_preferences",
                "phase_specs": ["contact", "respond", "commit"],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "tenant": {"testable": True, "scripted_policies": ["housing_scripted_tenant_v1"]},
                "landlord": {"testable": False, "scripted_policies": ["housing_scripted_landlord_v1"]},
            },
            "measurement": {
                "primary_estimand": "social_welfare",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "optimum_lower_bound": "housing_feasible_zero_v1",
                "comparison_baseline": "housing_adaptive_v1",
                "optimum_upper_bound": "housing_exact_assignment_v1",
                "optimum_upper_bound_kind": "full_information_relaxation",
                "bound_status": "bracketed",
                "outcome_support": "case_specific",
            },
            "scoring": {
                "scorer_id": "housing_outcome_v1",
                "oracle_id": "housing_exact_assignment_v1",
                "reference_provider_ids": ["housing_feasible_zero_v1", "housing_adaptive_v1"],
            },
            "generator": {
                "generator_id": "housing_generator_v1",
                "difficulty_knobs": ["market_tightness", "rounds", "common_weight"],
            },
        }
    )
    max_actions = rounds * (2 * num_tenants + num_listings)
    cases: list[CaseManifest] = []
    for index, case_world_seed in enumerate(selected_world_seeds, start=1):
        raw_case = {
            "spec_version": "aeread.case/0.1",
            "case_id": (
                "housing_v1__smoke__000001"
                if not experiment_mode
                else f"housing_v1__experiment__{index:06d}"
            ),
            "family_id": "housing_v1",
            "family_version": "1.0.0",
            "split": "smoke" if not experiment_mode else "evaluation",
            "world_seed": case_world_seed,
            "seats": [
                *[
                    {"id": f"tenant_{seat_index}", "role": "tenant"}
                    for seat_index in range(num_tenants)
                ],
                *[
                    {"id": f"landlord_{seat_index}", "role": "landlord"}
                    for seat_index in range(num_listings)
                ],
            ],
            "episode": {
                "max_logical_actions": max_actions,
                "termination": ["allocation", "deadline"],
            },
            "visibility_policy": "housing_private_preferences_v1",
            "payload": {
                "world_kind": "bid",
                "world_seed": case_world_seed,
                "num_tenants": num_tenants,
                "num_listings": num_listings,
                "rounds": rounds,
                "common_weight": 0.6,
            },
            "provenance": {
                "generator_id": "housing_generator_v1",
                "generator_version": "1.0.0",
                "review_status": "curated" if not experiment_mode else "generated",
            },
            "content_sha256": "0" * 64,
        }
        raw_case["content_sha256"] = case_content_sha256(raw_case)
        cases.append(CaseManifest.from_dict(raw_case))
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": (
                "housing_smoke_sample_v1"
                if not experiment_mode
                else f"housing_{reasoning_condition_id}_sample_v1"
            ),
            "estimand": (
                "fixed_housing_smoke_case"
                if not experiment_mode
                else "generated_housing_case_population"
            ),
            "target": "housing_generator_v1",
            "selection": "fixed_curated" if not experiment_mode else "seeded_simple_random",
            "seeds": [
                selected_world_seeds[0]
                if inference_seed_base is None
                else inference_seed_base
            ],
            "replicates": replicates,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": ["world_seed"],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel" if not experiment_mode else "sampled_panel",
        }
    )
    tenant_profile_id = (
        (
            "housing_deepseek_tenant_v1"
            if not experiment_mode
            else f"housing_deepseek_tenant_{reasoning_condition_id}"
        )
        if tenant_provider == "openrouter"
        else "housing_scripted_tenant_v1"
    )
    tenant_pricing = (
        openrouter_route.token_pricing()
        if tenant_provider == "openrouter"
        else TokenPricing(0.0, 0.0, 0.0, "housing_scripted_tenant_zero_cost_v1")
    )
    landlord_pricing = TokenPricing(0.0, 0.0, 0.0, "housing_scripted_landlord_zero_cost_v1")
    tenant_profile = _profile(
        profile_id=tenant_profile_id,
        provider=tenant_provider,
        model=tenant_model,
        revision=tenant_revision,
        prompt_id="housing_tenant_v1",
        prompt=HOUSING_TENANT_PROMPT,
        output_schemas={
            "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA,
            "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA,
        },
        pricing=tenant_pricing,
        max_logical_actions=2 * num_tenants * rounds,
        runtime="aeread.shared_runner.execution" if tenant_provider == "openrouter" else "aeread.shared_runner.housing",
        world_seed=selected_world_seeds[0],
        reasoning_condition_id=reasoning_condition_id,
        reasoning_effort=reasoning_effort,
        request_seed_base=inference_seed_base,
        max_output_tokens=(
            4096 if tenant_provider == "openrouter" and experiment_mode else None
        ),
        timeout_seconds=(
            120.0 if tenant_provider == "openrouter" and experiment_mode else None
        ),
        openrouter_route=openrouter_route,
    )
    landlord_profile = _profile(
        profile_id="housing_scripted_landlord_v1",
        provider="housing_scripted_landlord",
        model="housing_scripted_landlord_v1",
        revision="1.0.0",
        prompt_id="housing_landlord_v1",
        prompt=HOUSING_LANDLORD_PROMPT,
        output_schemas={"housing_respond_v1": HOUSING_RESPOND_OUTPUT_SCHEMA},
        pricing=landlord_pricing,
        max_logical_actions=num_listings * rounds,
        runtime="aeread.shared_runner.housing",
        world_seed=selected_world_seeds[0],
        reasoning_condition_id="scripted_no_reasoning_v1",
        reasoning_effort=None,
    )
    tenant_seats = [f"tenant_{index}" for index in range(num_tenants)]
    landlord_seats = [f"landlord_{index}" for index in range(num_listings)]
    block = EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": (
                "housing_controlled_landlords_smoke"
                if not experiment_mode
                else "housing_controlled_landlords_experiment"
            ),
            "kind": "controlled",
            "subject_seats": tenant_seats,
            "controlled_profiles": {
                seat: "housing_scripted_landlord_v1" for seat in landlord_seats
            },
            "repetitions": 1,
            "seed_policy": "fixed" if not experiment_mode else "paired",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": (
                "housing_smoke_analysis_v1"
                if not experiment_mode
                else "housing_reasoning_paired_analysis_v1"
            ),
            "estimands": (
                ["social_welfare", "tenant_payoff", "landlord_payoff"]
                if not experiment_mode
                else [
                    "within_case_score",
                    "social_welfare",
                    "tenant_payoff",
                    "landlord_payoff",
                ]
            ),
            "group_by": ["family_id", "subject_role"],
            "missingness": "report_separately",
            "resampling_unit": "cluster_id",
            "uncertainty": "none" if not experiment_mode else "cluster_bootstrap_95",
            "multiplicity": "none",
            "sensitivity": (
                ["report_ir_violations"]
                if not experiment_mode
                else [
                    "report_ir_violations",
                    "report_operational_missingness",
                    "worst_case_score_bounds",
                ]
            ),
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": (
                "housing_smoke_v1"
                if not experiment_mode
                else f"housing_{reasoning_condition_id}_experiment_v1"
            ),
            "version": "1.0.0",
            "family_ids": ["housing_v1"],
            "case_ids": [case.case_id for case in cases],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    assignments = {
        **{seat: tenant_profile_id for seat in tenant_seats},
        **{seat: "housing_scripted_landlord_v1" for seat in landlord_seats},
    }
    run_spec = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": (
                "housing_smoke_run_v1"
                if not experiment_mode
                else f"housing_{reasoning_condition_id}_run_v1"
            ),
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [tenant_profile_id, "housing_scripted_landlord_v1"],
            "seat_assignments": assignments,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    plugin = HousingV1Plugin()
    registry = PluginRegistry()
    registry.register(family, plugin)
    housing_source = Path(hz.__file__).read_bytes()
    bridge_source = Path(__file__).read_bytes()
    execution_source = Path(__file__).with_name("execution.py").read_bytes()
    housing_digest = hashlib.sha256(housing_source).hexdigest()
    bridge_digest = hashlib.sha256(bridge_source).hexdigest()
    combined_digest = hashlib.sha256(housing_source + bridge_source).hexdigest()
    execution_digest = hashlib.sha256(execution_source).hexdigest()
    pins = [
        _pin("aeread.housing_v1", "family_plugin", combined_digest),
        _pin("housing_outcome_v1", "scorer", combined_digest),
        _pin("housing_exact_assignment_v1", "reference", housing_digest),
        _pin("housing_feasible_zero_v1", "reference", bridge_digest),
        _pin("housing_adaptive_v1", "reference", housing_digest),
        _pin("housing_generator_v1", "generator", housing_digest),
        _pin("minimal_chat", "harness", execution_digest, version="1.0"),
        _pin("aeread.shared_runner.housing", "runtime", bridge_digest, version="0.1.0"),
    ]
    if tenant_provider == "openrouter":
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
        agent_profiles=(tenant_profile, landlord_profile),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
    )
    return HousingSmokeSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            "housing_tenant_v1": HOUSING_TENANT_PROMPT,
            "housing_landlord_v1": HOUSING_LANDLORD_PROMPT,
        },
        pricing={
            tenant_model: tenant_pricing,
            "housing_scripted_landlord_v1": landlord_pricing,
        },
    )


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.provider == "openrouter":
        tenant_provider = "openrouter"
        tenant_model = arguments.model or "deepseek/deepseek-v4-flash-0731"
        tenant_revision = arguments.revision or "deepseek/deepseek-v4-flash-20260731"
        tenant_client = OpenRouterChatClient()
    else:
        tenant_provider = "housing_scripted_tenant"
        tenant_model = "housing_scripted_tenant_v1"
        tenant_revision = "1.0.0"
        tenant_client = HousingScriptedTenantProvider()
    setup = build_housing_smoke(
        tenant_provider=tenant_provider,
        tenant_model=tenant_model,
        tenant_revision=tenant_revision,
        world_seed=arguments.world_seed,
        num_tenants=arguments.tenants,
        num_listings=arguments.listings,
        rounds=arguments.rounds,
    )
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=arguments.output,
        prompt_sources=setup.prompt_sources,
        providers={
            tenant_provider: tenant_client,
            "housing_scripted_landlord": HousingScriptedLandlordProvider(),
        },
        pricing=setup.pricing,
        episode_attempt_ordinal=arguments.attempt,
    )
    return {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "logical_action_count": execution.episode_result.logical_action_count,
        "total_cost_usd": execution.total_cost_usd,
        "evidence_dir": str(execution.evidence.root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("scripted", "openrouter"), default="scripted")
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument("--world-seed", type=int, default=41001)
    parser.add_argument("--tenants", type=int, default=2)
    parser.add_argument("--listings", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    print(canonical_json_bytes(asyncio.run(_run_cli(arguments))).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HOUSING_COMMIT_OUTPUT_SCHEMA",
    "HOUSING_CONTACT_OUTPUT_SCHEMA",
    "HOUSING_RESPOND_OUTPUT_SCHEMA",
    "HousingScriptedLandlordProvider",
    "HousingScriptedTenantProvider",
    "HousingSmokeSetup",
    "HousingV1Plugin",
    "OpenRouterRoutePin",
    "DEEPINFRA_HOUSING_ROUTE",
    "build_housing_smoke",
    "main",
]
