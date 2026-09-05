"""Runnable provider-free V1/V2 data-center agreement-stack harness."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.task.execution import (
    CellExecution,
    OpenRouterChatClient,
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
from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.task.receipts import EvaluationReceipt
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    RunPlan,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)

from .measurement import implementation_refs, primary_measurement_leaf
from .stack_environment import (
    OPTIONAL_AGREEMENT_KEYS,
    COUNTERPART_BY_KEY,
    SCORER_ID,
    SCOPE_CONFIG,
    DataCenterStackPlugin,
    stack_family_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_PATH_BY_SCOPE = {
    "v1": REPOSITORY_ROOT
    / "cases"
    / "datacenter_development_v1"
    / "v1"
    / "power_epc_bankability_001.json",
    "v2": REPOSITORY_ROOT
    / "cases"
    / "datacenter_development_v1"
    / "v2"
    / "full_stack_amendment_001.json",
}
RUNTIME_ID = "aeread_families.datacenter_development.stack_runner"
DEVELOPER_PROMPT = """Negotiate the complete data-center agreement stack. Return
exactly one JSON action for the current phase. In an offer phase, return decision,
message, and every structured term. In a commit phase, copy accepted_offer_id exactly
into offer_id and either sign or walk. Never invent an offer ID. Only complete
structured terms and signatures over accepted offer IDs are binding. Respect explicit
amendment precedence.

All months are 1-based calendar indices within the project horizon; month 0 does not
exist. Amounts are integer cents and rates are integer basis points.

An amendment phase is optional. To amend, offer the complete revised terms, which must
differ from the executed agreement in at least one field. If the executed agreement
already suits the project, return decision "decline" with terms null, which advances to
the next agreement without amending. Re-proposing identical terms is not a valid
amendment."""
COUNTERPART_PROMPT = """Apply your private policy to the latest written offer. Return
exactly one JSON accept, counter, or reject action for the current phase. Always copy
latest_offer.offer_id exactly into offer_id; never use a placeholder or invent an ID.
For accept or reject, set terms to null. For counter, provide a non-empty message and
the complete structured counter terms. Enforce every private minimum, maximum, and
required condition."""


def _strict_schema_from_example(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        properties = {
            str(key): _strict_schema_from_example(item)
            for key, item in value.items()
        }
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError("strict schema examples cannot contain empty arrays")
        return {"type": "array", "items": _strict_schema_from_example(value[0])}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    raise ValueError(f"unsupported strict-schema example: {type(value).__name__}")


def stack_developer_output_schemas(case: CaseManifest) -> dict[str, Any]:
    """Return one strict schema per developer action schema in the case."""

    scope_version = str(case.payload["scope_version"])
    sequence = SCOPE_CONFIG[scope_version]["sequence"]
    schemas: dict[str, Any] = {}
    for key in sequence:
        terms = case.payload["scripted_developer"][f"{key}_terms"]
        term_schema = _strict_schema_from_example(terms)
        decisions = ["offer", "walk"]
        if key in OPTIONAL_AGREEMENT_KEYS:
            decisions.append("decline")
        schemas[f"datacenter_{key}_offer_v1"] = {
            "type": "object",
            "properties": {
                "decision": {"enum": decisions},
                "message": {"type": ["string", "null"]},
                "terms": {"anyOf": [term_schema, {"type": "null"}]},
            },
            "required": ["decision", "message", "terms"],
            "additionalProperties": False,
        }
        schemas[f"datacenter_{key}_commit_v1"] = {
            "type": "object",
            "properties": {
                "decision": {"enum": ["sign", "walk"]},
                "offer_id": {"type": "string"},
            },
            "required": ["decision", "offer_id"],
            "additionalProperties": False,
        }
    return schemas


def stack_counterparty_output_schemas(
    case: CaseManifest, seat_id: str
) -> dict[str, Any]:
    """Return strict response schemas for the agreements owned by one seat."""

    scope_version = str(case.payload["scope_version"])
    agreement_keys = tuple(
        key
        for key in SCOPE_CONFIG[scope_version]["sequence"]
        if COUNTERPART_BY_KEY[key] == seat_id
    )
    if not agreement_keys:
        raise ValueError(f"seat {seat_id!r} owns no {scope_version} agreements")
    schemas: dict[str, Any] = {}
    for key in agreement_keys:
        terms = case.payload["policies"][key]["counter_terms"]
        schemas[f"datacenter_{key}_response_v1"] = {
            "type": "object",
            "properties": {
                "decision": {"enum": ["accept", "counter", "reject"]},
                "offer_id": {"type": "string"},
                "message": {"type": ["string", "null"]},
                "terms": {
                    "anyOf": [
                        _strict_schema_from_example(terms),
                        {"type": "null"},
                    ]
                },
            },
            "required": ["decision", "offer_id", "message", "terms"],
            "additionalProperties": False,
        }
    return schemas


@dataclass(frozen=True, slots=True)
class DataCenterStackSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]
    scope_version: str


def load_stack_case(
    scope_version: str, path: Path | str | None = None
) -> CaseManifest:
    resolved_path = Path(path or CASE_PATH_BY_SCOPE[scope_version])
    case = CaseManifest.from_dict(json.loads(resolved_path.read_text(encoding="utf-8")))
    computed = case_content_sha256(case)
    if computed != case.content_sha256:
        raise ValueError(
            f"case content hash mismatch: declared {case.content_sha256}, computed {computed}"
        )
    return case


def _pin(
    component_id: str, kind: str, source_path: Path, *, version: str = "1.0.0"
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def _profile(
    *,
    profile_id: str,
    provider: str,
    model: str,
    prompt_id: str,
    prompt: str,
    pricing: TokenPricing,
    max_actions: int,
) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": profile_id,
            "model": {
                "provider": provider,
                "model": model,
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": pricing.pricing_id,
                    "pricing_sha256": pricing.content_sha256(),
                },
            },
            "prompt": {
                "prompt_id": prompt_id,
                "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "scripted_no_reasoning_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 1600,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": max_actions,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.0,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def _harness_registry_for(harness: Any) -> HarnessRegistry:
    registry = HarnessRegistry()
    for registered_harness in default_harnesses().values():
        registry.register(registered_harness)
    if harness.id != "minimal_chat":
        registry.register(harness)
    return registry


def build_stack_setup(
    scope_version: str, *, case_path: Path | str | None = None
) -> DataCenterStackSetup:
    if scope_version not in SCOPE_CONFIG:
        raise ValueError("scope_version must be v1 or v2")
    case = load_stack_case(scope_version, case_path)
    family = stack_family_manifest(scope_version)
    plugin = DataCenterStackPlugin(scope_version)
    family_case = plugin.validate_payload(case.payload)
    sequence = tuple(SCOPE_CONFIG[scope_version]["sequence"])
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"datacenter_development_{scope_version}_sample_v1",
            "estimand": f"fixed_datacenter_{scope_version}_agreement_stack",
            "target": case.provenance.generator_id,
            "selection": "fixed_curated",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    counterpart_seats = sorted({COUNTERPART_BY_KEY[key] for key in sequence})
    controlled_profiles = {
        seat: f"datacenter_{scope_version}_scripted_{seat}_v1"
        for seat in counterpart_seats
    }
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"datacenter_{scope_version}_controlled_counterparties_v1",
            "kind": "controlled",
            "subject_seats": ["developer"],
            "controlled_profiles": controlled_profiles,
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"datacenter_development_{scope_version}_analysis_v1",
            "estimands": [
                "developer_equity_npv",
                "binding_contract_integrity",
                "project_constraint_satisfaction",
                "negotiation_temporal_compliance",
                "total_project_npv",
            ],
            "group_by": ["family_id", "family_version"],
            "missingness": "report_separately",
            "resampling_unit": "world_seed",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"datacenter_development_{scope_version}_dev_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )

    pricing: dict[str, TokenPricing] = {}
    profiles: list[AgentProfile] = []
    developer_model = f"datacenter_{scope_version}_scripted_developer_v1"
    developer_pricing = TokenPricing(
        0.0, 0.0, 0.0, f"{developer_model}_zero_cost"
    )
    pricing[developer_model] = developer_pricing
    profiles.append(
        _profile(
            profile_id=developer_model,
            provider="datacenter_stack_scripted_developer",
            model=developer_model,
            prompt_id=f"datacenter_{scope_version}_developer_prompt_v1",
            prompt=DEVELOPER_PROMPT,
            pricing=developer_pricing,
            max_actions=sum(
                family_case["negotiation"]["max_rounds"][key]
                for key in sequence
            )
            + len(sequence),
        )
    )
    for seat in counterpart_seats:
        model = f"datacenter_{scope_version}_scripted_{seat}_v1"
        seat_pricing = TokenPricing(0.0, 0.0, 0.0, f"{model}_zero_cost")
        pricing[model] = seat_pricing
        profiles.append(
            _profile(
                profile_id=model,
                provider=f"datacenter_stack_scripted_{seat}",
                model=model,
                prompt_id=f"datacenter_{scope_version}_{seat}_prompt_v1",
                prompt=COUNTERPART_PROMPT,
                pricing=seat_pricing,
                max_actions=sum(
                    family_case["negotiation"]["max_rounds"][key]
                    for key in sequence
                    if COUNTERPART_BY_KEY[key] == seat
                ),
            )
        )
    profile_by_seat = {
        "developer": developer_model,
        **controlled_profiles,
    }
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"datacenter_development_{scope_version}_scripted_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id for profile in profiles],
            "seat_assignments": profile_by_seat,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, plugin)
    harness_registry = HarnessRegistry()
    harnesses = default_harnesses()
    for harness in harnesses.values():
        harness_registry.register(harness)

    environment_path = Path(__file__).with_name("stack_environment.py")
    measurement_path = Path(__file__).with_name("measurement.py")
    execution_path = Path(execution_module.__file__)
    measurement_digest = hashlib.sha256(measurement_path.read_bytes()).hexdigest()
    pins = [
        _pin(family.family.plugin_id, "family_plugin", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(RUNTIME_ID, "runtime", Path(__file__), version="0.1.0"),
    ]
    for implementation in implementation_refs():
        pins.append(
            ImplementationPin.from_dict(
                {
                    "component_id": implementation.implementation_id,
                    "kind": "scorer" if implementation.implementation_id == SCORER_ID else "reference",
                    "version": implementation.version,
                    "sha256": measurement_digest,
                }
            )
        )
    provider_ids = [
        "datacenter_stack_scripted_developer",
        *(f"datacenter_stack_scripted_{seat}" for seat in counterpart_seats),
    ]
    capabilities = {
        provider: ProviderCapabilities(
            native_tools=False,
            structured_output=False,
            seed=False,
            system_prompt=True,
            reasoning_budget=False,
            reasoning_token_report=False,
            max_context_tokens=None,
        )
        for provider in provider_ids
    }
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=tuple(profiles),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
        harness_registry=harness_registry,
        provider_capabilities=capabilities,
    )
    return DataCenterStackSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            f"datacenter_{scope_version}_developer_prompt_v1": DEVELOPER_PROMPT,
            **{
                f"datacenter_{scope_version}_{seat}_prompt_v1": COUNTERPART_PROMPT
                for seat in counterpart_seats
            },
        },
        pricing=pricing,
        case=case,
        harnesses=harnesses,
        scope_version=scope_version,
    )


def build_stack_openrouter_setup(
    scope_version: str,
    route: Any,
    *,
    seed: int,
    case_path: Path | str | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.02,
    harness: Any | None = None,
    harness_config: Mapping[str, Any] | None = None,
    runtime_implementation: str | None = None,
) -> DataCenterStackSetup:
    """Replace only the developer with one exact live OpenRouter route."""

    if seed < 0:
        raise ValueError("seed must be non-negative")
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_cost_usd <= 0:
        raise ValueError("max_cost_usd must be positive for a live route")

    template = build_stack_setup(scope_version, case_path=case_path)
    resolved_harness = harness or MinimalChatHarness()
    resolved_runtime = runtime_implementation or (
        "aeread.shared_runner.task.execution"
        if resolved_harness.id == "minimal_chat"
        else "aeread.shared_runner.model_call.open_harnesses"
    )
    resolved_profile_id = route.profile_id
    if resolved_harness.id != "minimal_chat":
        resolved_profile_id = f"{route.profile_id}_{resolved_harness.id}"

    live_config: dict[str, Any] = {
        "pricing_id": route.pricing.pricing_id,
        "pricing_sha256": route.pricing.content_sha256(),
        "output_schema_by_action_schema": stack_developer_output_schemas(
            template.case
        ),
        "provider_metadata": {
            "route_provider": route.route_provider,
            "quantization": route.quantization,
            "canonical_model": route.revision,
            "max_prompt_price_per_million": route.max_prompt_price_per_million,
            "max_completion_price_per_million": (
                route.max_completion_price_per_million
            ),
        },
    }
    if harness_config is not None:
        live_config.update(dict(harness_config))
    if not route.temperature_supported:
        live_config["sampling_controls"] = {"temperature": "unavailable"}

    sequence = tuple(SCOPE_CONFIG[scope_version]["sequence"])
    family_case = DataCenterStackPlugin(scope_version).validate_payload(
        template.case.payload
    )
    max_developer_actions = sum(
        family_case["negotiation"]["max_rounds"][key] for key in sequence
    ) + len(sequence)
    live_profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": resolved_profile_id,
            "model": {
                "provider": "openrouter",
                "model": route.model,
                "revision": route.revision,
                "base_url": "https://openrouter.ai/api/v1",
            },
            "harness": {
                "id": resolved_harness.id,
                "version": resolved_harness.version,
                "config": live_config,
            },
            "prompt": {
                "prompt_id": f"datacenter_{scope_version}_developer_prompt_v1",
                "sha256": hashlib.sha256(
                    DEVELOPER_PROMPT.encode("utf-8")
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": resolved_runtime,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": (
                    f"reasoning_{route.reasoning_effort}_v1"
                    if route.reasoning_effort is not None
                    else "reasoning_provider_default_v1"
                ),
                "effort": route.reasoning_effort,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": max_output_tokens,
                "seed": seed,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": max_developer_actions,
                "timeout_seconds": timeout_seconds,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )

    scripted_developer_id = template.plan.cells[0].profile_by_seat["developer"]
    controlled_profiles = tuple(
        profile
        for profile in template.plan.agent_profiles
        if profile.profile_id != scripted_developer_id
    )
    profiles = (live_profile, *controlled_profiles)
    seat_assignments = {
        **dict(template.plan.cells[0].profile_by_seat),
        "developer": resolved_profile_id,
    }
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": (
                f"datacenter_development_{scope_version}_openrouter_"
                f"{resolved_profile_id}"
            ),
            "suite_id": template.plan.suite.suite_id,
            "evaluation_block_ids": [
                block.block_id for block in template.plan.evaluation_blocks
            ],
            "agent_profile_ids": [profile.profile_id for profile in profiles],
            "seat_assignments": seat_assignments,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    harness_registry = HarnessRegistry()
    for registered_harness in default_harnesses().values():
        harness_registry.register(registered_harness)
    if resolved_harness.id != "minimal_chat":
        harness_registry.register(resolved_harness)

    pins = list(template.plan.implementation_pins)
    existing_pin_ids = {pin.component_id for pin in pins}
    harness_source_path = (
        Path(execution_module.__file__)
        if resolved_harness.id == "minimal_chat"
        else Path(inspect.getfile(type(resolved_harness)))
    )
    if resolved_harness.id not in existing_pin_ids:
        pins.append(
            _pin(
                resolved_harness.id,
                "harness",
                harness_source_path,
                version=resolved_harness.version,
            )
        )
        existing_pin_ids.add(resolved_harness.id)
    runtime_source_path = (
        Path(execution_module.__file__)
        if resolved_runtime == "aeread.shared_runner.task.execution"
        else harness_source_path
    )
    if resolved_runtime not in existing_pin_ids:
        pins.append(
            _pin(
                resolved_runtime,
                "runtime",
                runtime_source_path,
                version="0.1.0",
            )
        )

    counterpart_providers = {
        profile.model.provider
        for profile in controlled_profiles
    }
    provider_capabilities = {
        provider: ProviderCapabilities(
            native_tools=False,
            structured_output=False,
            seed=False,
            system_prompt=True,
            reasoning_budget=False,
            reasoning_token_report=False,
            max_context_tokens=None,
        )
        for provider in counterpart_providers
    }
    provider_capabilities["openrouter"] = ProviderCapabilities(
        native_tools=False,
        structured_output=True,
        seed=True,
        system_prompt=True,
        reasoning_budget=route.reasoning_effort is not None,
        reasoning_token_report=True,
        max_context_tokens=None,
    )
    plan = resolve_run_plan(
        families=template.plan.families,
        cases=template.plan.cases,
        suite=template.plan.suite,
        sampling=template.plan.sampling,
        evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis,
        agent_profiles=profiles,
        run_spec=run_spec,
        registry=template.registry,
        implementation_pins=tuple(pins),
        harness_registry=harness_registry,
        provider_capabilities=provider_capabilities,
    )
    return DataCenterStackSetup(
        plan=plan,
        registry=template.registry,
        prompt_sources=template.prompt_sources,
        pricing={
            route.model: route.pricing,
            **{
                profile.model.model: template.pricing[profile.model.model]
                for profile in controlled_profiles
            },
        },
        case=template.case,
        harnesses={
            **default_harnesses(),
            f"{resolved_harness.id}/{resolved_harness.version}": resolved_harness,
        },
        scope_version=scope_version,
    )


def build_stack_model_to_model_setup(
    scope_version: str,
    route: Any,
    *,
    seed: int,
    counterpart_route: Any | None = None,
    case_path: Path | str | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.02,
    harness: Any | None = None,
    harness_config: Mapping[str, Any] | None = None,
    runtime_implementation: str | None = None,
) -> DataCenterStackSetup:
    """Resolve a harness-mediated live model profile for every negotiating seat."""

    developer_setup = build_stack_openrouter_setup(
        scope_version,
        route,
        seed=seed,
        case_path=case_path,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
        harness=harness,
        harness_config=harness_config,
        runtime_implementation=runtime_implementation,
    )
    resolved_counterpart_route = counterpart_route or route
    resolved_harness = harness or MinimalChatHarness()
    resolved_runtime = runtime_implementation or (
        "aeread.shared_runner.task.execution"
        if resolved_harness.id == "minimal_chat"
        else "aeread.shared_runner.model_call.open_harnesses"
    )
    sequence = tuple(SCOPE_CONFIG[scope_version]["sequence"])
    counterpart_seats = tuple(
        sorted({COUNTERPART_BY_KEY[key] for key in sequence})
    )
    family_case = DataCenterStackPlugin(scope_version).validate_payload(
        developer_setup.case.payload
    )
    developer_profile_id = developer_setup.plan.cells[0].profile_by_seat[
        "developer"
    ]
    developer_profile = next(
        profile
        for profile in developer_setup.plan.agent_profiles
        if profile.profile_id == developer_profile_id
    )

    counterpart_profiles: list[AgentProfile] = []
    for seat_id in counterpart_seats:
        profile_id = (
            f"datacenter_{scope_version}_{seat_id}_"
            f"{resolved_counterpart_route.profile_id}"
        )
        if resolved_harness.id != "minimal_chat":
            profile_id = f"{profile_id}_{resolved_harness.id}"
        config: dict[str, Any] = {
            "pricing_id": resolved_counterpart_route.pricing.pricing_id,
            "pricing_sha256": (
                resolved_counterpart_route.pricing.content_sha256()
            ),
            "output_schema_by_action_schema": (
                stack_counterparty_output_schemas(
                    developer_setup.case, seat_id
                )
            ),
            "provider_metadata": {
                "route_provider": resolved_counterpart_route.route_provider,
                "quantization": resolved_counterpart_route.quantization,
                "canonical_model": resolved_counterpart_route.revision,
                "max_prompt_price_per_million": (
                    resolved_counterpart_route.max_prompt_price_per_million
                ),
                "max_completion_price_per_million": (
                    resolved_counterpart_route.max_completion_price_per_million
                ),
            },
        }
        if harness_config is not None:
            config.update(dict(harness_config))
        if not resolved_counterpart_route.temperature_supported:
            config["sampling_controls"] = {"temperature": "unavailable"}
        max_actions = sum(
            family_case["negotiation"]["max_rounds"][key]
            for key in sequence
            if COUNTERPART_BY_KEY[key] == seat_id
        )
        prompt_id = f"datacenter_{scope_version}_{seat_id}_prompt_v1"
        counterpart_profiles.append(
            AgentProfile.from_dict(
                {
                    "spec_version": AgentProfile.SPEC_VERSION,
                    "profile_id": profile_id,
                    "model": {
                        "provider": "openrouter",
                        "model": resolved_counterpart_route.model,
                        "revision": resolved_counterpart_route.revision,
                        "base_url": "https://openrouter.ai/api/v1",
                    },
                    "harness": {
                        "id": resolved_harness.id,
                        "version": resolved_harness.version,
                        "config": config,
                    },
                    "prompt": {
                        "prompt_id": prompt_id,
                        "sha256": hashlib.sha256(
                            COUNTERPART_PROMPT.encode("utf-8")
                        ).hexdigest(),
                    },
                    "runtime": {
                        "kind": "python",
                        "implementation": resolved_runtime,
                        "version": "0.1.0",
                    },
                    "tools": [],
                    "memory": {"mode": "disabled"},
                    "reasoning": {
                        "condition_id": (
                            "reasoning_"
                            f"{resolved_counterpart_route.reasoning_effort}_v1"
                            if resolved_counterpart_route.reasoning_effort
                            is not None
                            else "reasoning_provider_default_v1"
                        ),
                        "effort": (
                            resolved_counterpart_route.reasoning_effort
                        ),
                        "token_budget": None,
                        "rationale_visibility": "hidden",
                    },
                    "sampling": {
                        "temperature": 0.0,
                        "max_output_tokens": max_output_tokens,
                        "seed": seed,
                        "top_p": None,
                    },
                    "budgets": {
                        "max_logical_actions": max_actions,
                        "timeout_seconds": timeout_seconds,
                        "max_cost_usd": max_cost_usd,
                    },
                    "retry_policy": {
                        "max_action_attempts": 1,
                        "retryable_conditions": [],
                        "session_mode": "restart",
                        "sdk_retries": 0,
                    },
                }
            )
        )

    profiles = (developer_profile, *counterpart_profiles)
    profile_by_seat = {
        "developer": developer_profile.profile_id,
        **{
            seat_id: next(
                profile.profile_id
                for profile in counterpart_profiles
                if f"_{seat_id}_" in profile.profile_id
            )
            for seat_id in counterpart_seats
        },
    }
    same_route = all(
        getattr(route, field) == getattr(resolved_counterpart_route, field)
        for field in ("model", "revision", "route_provider", "quantization")
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": (
                f"datacenter_{scope_version}_model_to_model_"
                f"{resolved_harness.id}_v1"
            ),
            "kind": "self_play" if same_route else "cross_play",
            "subject_seats": [seat.id for seat in developer_setup.case.seats],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": (
                f"datacenter_development_{scope_version}_model_to_model_v1"
            ),
            "version": "1.0.0",
            "family_ids": [
                family.family.id for family in developer_setup.plan.families
            ],
            "case_ids": [developer_setup.case.case_id],
            "sampling_plan_id": (
                developer_setup.plan.sampling.sampling_plan_id
            ),
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": developer_setup.plan.analysis.analysis_plan_id,
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": (
                f"datacenter_development_{scope_version}_model_to_model_"
                f"{resolved_harness.id}_v1"
            ),
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id for profile in profiles],
            "seat_assignments": profile_by_seat,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    required_component_ids = {
        profile.harness.id for profile in profiles
    } | {
        profile.runtime.implementation for profile in profiles
    }
    for family in developer_setup.plan.families:
        required_component_ids.add(family.family.plugin_id)
        required_component_ids.add(family.scoring.scorer_id)
        required_component_ids.update(family.scoring.reference_provider_ids)
        if family.scoring.oracle_id is not None:
            required_component_ids.add(family.scoring.oracle_id)
        if family.generator is not None:
            required_component_ids.add(family.generator.generator_id)
    pins = tuple(
        pin
        for pin in developer_setup.plan.implementation_pins
        if pin.component_id in required_component_ids
    )
    plan = resolve_run_plan(
        families=developer_setup.plan.families,
        cases=developer_setup.plan.cases,
        suite=suite,
        sampling=developer_setup.plan.sampling,
        evaluation_blocks=(block,),
        analysis=developer_setup.plan.analysis,
        agent_profiles=profiles,
        run_spec=run_spec,
        registry=developer_setup.registry,
        implementation_pins=pins,
        harness_registry=(
            _harness_registry_for(resolved_harness)
        ),
        provider_capabilities={
            "openrouter": ProviderCapabilities(
                native_tools=False,
                structured_output=True,
                seed=True,
                system_prompt=True,
                reasoning_budget=(
                    route.reasoning_effort is not None
                    or resolved_counterpart_route.reasoning_effort is not None
                ),
                reasoning_token_report=True,
                max_context_tokens=None,
            )
        },
    )
    pricing = {route.model: route.pricing}
    if resolved_counterpart_route.model in pricing and (
        pricing[resolved_counterpart_route.model].content_sha256()
        != resolved_counterpart_route.pricing.content_sha256()
    ):
        raise ValueError("one model cannot resolve to two pricing records")
    pricing[resolved_counterpart_route.model] = (
        resolved_counterpart_route.pricing
    )
    return DataCenterStackSetup(
        plan=plan,
        registry=developer_setup.registry,
        prompt_sources=developer_setup.prompt_sources,
        pricing=pricing,
        case=developer_setup.case,
        harnesses={
            **default_harnesses(),
            f"{resolved_harness.id}/{resolved_harness.version}": (
                resolved_harness
            ),
        },
        scope_version=scope_version,
    )


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


class StackScriptedDeveloperProvider:
    def __init__(self, scripted_developer: Mapping[str, Any]) -> None:
        self._scripted = dict(scripted_developer)

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "datacenter_stack_scripted_developer":
            raise ProviderFailure("provider_contract", "wrong stack developer provider", retryable=False)
        payload = json.loads(request.input_text)
        phase = payload["phase_id"]
        observation = payload["observation"]
        key = observation["agreement_key"]
        if phase.endswith("_offer"):
            terms = observation.get("pending_counter_terms") or self._scripted[f"{key}_terms"]
            output = {"decision": "offer", "message": f"Written {key} proposal.", "terms": terms}
        elif phase.endswith("_commit"):
            output = {"decision": "sign", "offer_id": observation["accepted_offer_id"]}
        else:
            raise ProviderFailure("provider_contract", "developer received wrong stack phase", retryable=False)
        return _scripted_result(request, output)


class StackScriptedCounterpartyProvider:
    def __init__(self, seat_id: str) -> None:
        self._seat_id = seat_id

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        expected_provider = f"datacenter_stack_scripted_{self._seat_id}"
        if request.provider != expected_provider:
            raise ProviderFailure("provider_contract", "wrong stack counterparty provider", retryable=False)
        payload = json.loads(request.input_text)
        if not payload["phase_id"].endswith("_response"):
            raise ProviderFailure("provider_contract", "counterparty received wrong phase", retryable=False)
        observation = payload["observation"]
        offer = observation["latest_offer"]
        values = offer["terms"]
        policy = observation["private_policy"]
        acceptable = all(
            field in values and values[field] >= minimum
            for field, minimum in policy["minimums"].items()
        ) and all(
            field in values and values[field] <= maximum
            for field, maximum in policy["maximums"].items()
        ) and set(policy["required_conditions"]).issubset(
            set(values.get("conditions_precedent", ()))
        )
        output = (
            {"decision": "accept", "offer_id": offer["offer_id"], "message": f"{self._seat_id} accepts the written terms.", "terms": None}
            if acceptable
            else {"decision": "counter", "offer_id": offer["offer_id"], "message": policy.get("counter_message") or f"{self._seat_id} counterproposal.", "terms": policy["counter_terms"]}
        )
        return _scripted_result(request, output)


def _providers(setup: DataCenterStackSetup) -> Mapping[str, Any]:
    sequence = SCOPE_CONFIG[setup.scope_version]["sequence"]
    seats = sorted({COUNTERPART_BY_KEY[key] for key in sequence})
    return {
        "datacenter_stack_scripted_developer": StackScriptedDeveloperProvider(
            setup.case.payload["scripted_developer"]
        ),
        **{
            f"datacenter_stack_scripted_{seat}": StackScriptedCounterpartyProvider(seat)
            for seat in seats
        },
    }


async def run_stack_offline(
    scope_version: str,
    *,
    evidence_root: Path | str,
    episode_attempt_ordinal: int = 0,
    case_path: Path | str | None = None,
) -> tuple[DataCenterStackSetup, CellExecution]:
    setup = build_stack_setup(scope_version, case_path=case_path)
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers=_providers(setup),
        pricing=setup.pricing,
        episode_attempt_ordinal=episode_attempt_ordinal,
        harnesses=setup.harnesses,
    )
    return setup, execution


async def run_stack_openrouter(
    scope_version: str,
    route: Any,
    *,
    evidence_root: Path | str,
    seed: int,
    episode_attempt_ordinal: int = 0,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.02,
    harness: Any | None = None,
    harness_config: Mapping[str, Any] | None = None,
    runtime_implementation: str | None = None,
    provider: Any | None = None,
    case_path: Path | str | None = None,
) -> tuple[DataCenterStackSetup, CellExecution]:
    """Execute one live developer trajectory with scripted counterparties."""

    setup = build_stack_openrouter_setup(
        scope_version,
        route,
        seed=seed,
        case_path=case_path,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
        harness=harness,
        harness_config=harness_config,
        runtime_implementation=runtime_implementation,
    )
    providers = dict(_providers(setup))
    providers.pop("datacenter_stack_scripted_developer", None)
    providers["openrouter"] = provider or OpenRouterChatClient()
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers=providers,
        pricing=setup.pricing,
        episode_attempt_ordinal=episode_attempt_ordinal,
        harnesses=setup.harnesses,
    )
    return setup, execution


async def run_stack_model_to_model(
    scope_version: str,
    route: Any,
    *,
    evidence_root: Path | str,
    seed: int,
    counterpart_route: Any | None = None,
    episode_attempt_ordinal: int = 0,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.02,
    harness: Any | None = None,
    harness_config: Mapping[str, Any] | None = None,
    runtime_implementation: str | None = None,
    provider: Any | None = None,
    case_path: Path | str | None = None,
) -> tuple[DataCenterStackSetup, CellExecution]:
    """Execute one harness-mediated trajectory with live models in every seat."""

    setup = build_stack_model_to_model_setup(
        scope_version,
        route,
        seed=seed,
        case_path=case_path,
        counterpart_route=counterpart_route,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
        harness=harness,
        harness_config=harness_config,
        runtime_implementation=runtime_implementation,
    )
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers={"openrouter": provider or OpenRouterChatClient()},
        pricing=setup.pricing,
        episode_attempt_ordinal=episode_attempt_ordinal,
        harnesses=setup.harnesses,
    )
    return setup, execution


def finalize_stack_execution(
    *, setup: DataCenterStackSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_stack_failure(
    *,
    setup: DataCenterStackSetup,
    cell_id: str,
    evidence_root: Path | str,
    error: BaseException,
) -> EvaluationReceipt:
    return finalize_family_failure(
        setup=setup,
        cell_id=cell_id,
        evidence_root=evidence_root,
        error=error,
        leaf_builder=primary_measurement_leaf,
    )


def replay_stack_receipt(
    *,
    setup: DataCenterStackSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    setup, execution = await run_stack_offline(
        arguments.scope,
        evidence_root=arguments.run_root,
        episode_attempt_ordinal=arguments.attempt,
    )
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    replayed = replay_stack_receipt(
        setup=setup, receipt=receipt, evidence_root=arguments.run_root
    )
    return {
        "scope_version": arguments.scope,
        "family_version": setup.plan.families[0].family.version,
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "logical_action_count": execution.episode_result.logical_action_count,
        "outcome": execution.episode_result.outcome,
        "measurement_status": receipt.status,
        "inclusion_status": receipt.inclusion_status,
        "primary_leaf_id": receipt.primary_leaf_id,
        "scores": {
            item.leaf.leaf_id: item.primary.value if item.primary is not None else None
            for item in receipt.scores
        },
        "receipt_sha256": receipt.receipt_sha256,
        "replay_matches": replayed == receipt,
        "total_cost_usd": execution.total_cost_usd,
        "receipt_path": str((execution.evidence.root / "evaluation_receipt.json").resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("v1", "v2"), required=True)
    parser.add_argument(
        "--run-root", "--output", dest="run_root", type=Path, required=True
    )
    parser.add_argument("--attempt", type=int, default=0)
    arguments = parser.parse_args(argv)
    print(canonical_json_bytes(asyncio.run(_run_cli(arguments))).decode("utf-8"))
    return 0


__all__ = [
    "CASE_PATH_BY_SCOPE",
    "DataCenterStackSetup",
    "StackScriptedCounterpartyProvider",
    "StackScriptedDeveloperProvider",
    "build_stack_model_to_model_setup",
    "build_stack_openrouter_setup",
    "build_stack_setup",
    "finalize_stack_execution",
    "load_stack_case",
    "main",
    "replay_stack_receipt",
    "run_stack_offline",
    "run_stack_model_to_model",
    "run_stack_openrouter",
    "stack_counterparty_output_schemas",
    "stack_developer_output_schemas",
]
