"""Build and run one data-center development terms case through AERead."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import MinimalChatHarness, default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, RunPlan, resolve_run_plan
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.evaluation import (
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import (
    CellExecution,
    OpenRouterChatClient,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import EvaluationReceipt
from aeread_families.single_offer.runner import FixedResponseProvider

from .cases import load_cases
from .environment import (
    ESTIMAND_ID,
    FAMILY_ID,
    ORACLE_ID,
    PLUGIN_ID,
    SCORER_ID,
    DataCenterTermsPlugin,
    datacenter_terms_measurement_leaf,
    family_manifest,
    response_contract,
)


DEFAULT_CASE_SLUG = "full-stack-cutoff-001"
PROMPT = """You are a data-center development agreement-state analyst. Read the
supplied case evidence and return only one JSON object, with no markdown or
surrounding explanation.

The observation includes a response_contract. Use exactly its top-level fields:
case_id, states, amounts, actions, claims, evidence_ids, and
external_actions_attempted. Use every required state and amount key exactly once.
Choose only from the candidate labels and state vocabulary in the contract. Cite
opaque evidence IDs supporting the answer. Distinguish verbal alignment from
signed documents, proposals from authority to proceed, conditional financing from
committed capital, and redlines from contracted revenue. The case is report-only:
do not claim to contact, sign, fund, draw, book, or execute an external action.
"""


@dataclass(frozen=True, slots=True)
class DataCenterTermsSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class OpenRouterRoute:
    profile_id: str
    model: str
    revision: str
    route_provider: str
    quantization: str
    pricing: TokenPricing
    max_prompt_price_per_million: str
    max_completion_price_per_million: str
    reasoning_effort: str | None = "low"
    temperature_supported: bool = True


def _exact_object(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }


def datacenter_terms_output_schema(
    case: CaseManifest,
    *,
    unique_array_items: bool = False,
) -> dict[str, Any]:
    """Return the case-specific strict schema without revealing gold choices."""

    family_case = DataCenterTermsPlugin().validate_payload(case.payload)
    contract = response_contract(family_case)
    state_value = {"type": "string", "enum": contract["state_value_vocabulary"]}

    def candidate_string(values: list[str]) -> dict[str, Any]:
        return {"type": "string", "enum": values}

    def candidate_array(values: list[str]) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": "array",
            "items": candidate_string(values),
        }
        if unique_array_items:
            schema["uniqueItems"] = True
        return schema

    def string_array() -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": "array",
            "items": {"type": "string"},
        }
        if unique_array_items:
            schema["uniqueItems"] = True
        return schema

    return _exact_object(
        {
            "case_id": {"type": "string", "enum": [case.case_id]},
            "states": _exact_object(
                {key: state_value for key in contract["state_keys"]}
            ),
            "amounts": _exact_object(
                {key: {"type": "number"} for key in contract["amount_keys"]}
            ),
            "actions": candidate_array(contract["action_candidates"]),
            "claims": candidate_array(contract["claim_candidates"]),
            "evidence_ids": candidate_array(contract["evidence_ids"]),
            "external_actions_attempted": string_array(),
        }
    )


def datacenter_terms_indicator_output_schema(case: CaseManifest) -> dict[str, Any]:
    """Return a duplicate-free boolean classifier schema for candidate labels."""

    family_case = DataCenterTermsPlugin().validate_payload(case.payload)
    contract = response_contract(family_case)
    state_value = {"type": "string", "enum": contract["state_value_vocabulary"]}

    def indicator_map(values: list[str]) -> dict[str, Any]:
        return _exact_object({value: {"type": "boolean"} for value in values})

    return _exact_object(
        {
            "case_id": {"type": "string", "enum": [case.case_id]},
            "states": _exact_object(
                {key: state_value for key in contract["state_keys"]}
            ),
            "amounts": _exact_object(
                {key: {"type": "number"} for key in contract["amount_keys"]}
            ),
            "actions": indicator_map(contract["action_candidates"]),
            "claims": indicator_map(contract["claim_candidates"]),
            "evidence_ids": indicator_map(contract["evidence_ids"]),
            "external_actions_attempted": _exact_object(
                {"any": {"type": "boolean"}}
            ),
        }
    )


def _pin(
    component_id: str,
    kind: str,
    source_path: Path,
    *,
    version: str = "1.0.0",
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def _selected_case(case_slug: str) -> CaseManifest:
    return load_cases(case_slugs=(case_slug,))[0]


def _resolve_case(
    case_slug: str,
    case_manifest: CaseManifest | None,
) -> CaseManifest:
    case = case_manifest or _selected_case(case_slug)
    if case.family_id != FAMILY_ID or case.family_version != family_manifest().family.version:
        raise ValueError("data-center terms case family differs")
    public_case = case.payload.get("public_case")
    if not isinstance(public_case, Mapping) or public_case.get("case_id") != case.case_id:
        raise ValueError("data-center terms public case ID differs")
    if not case.case_id.endswith(f".{case_slug}"):
        raise ValueError("case_slug does not identify the supplied case")
    DataCenterTermsPlugin().validate_payload(case.payload)
    return case


def build_offline_setup(
    *,
    case_slug: str = DEFAULT_CASE_SLUG,
    case_manifest: CaseManifest | None = None,
) -> DataCenterTermsSetup:
    """Resolve one zero-cost case for deterministic fixture execution."""

    case = _resolve_case(case_slug, case_manifest)
    family = family_manifest()
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"datacenter_terms_{case_slug}_sample_v1",
            "estimand": "fixed_synthetic_datacenter_terms_case",
            "target": case_slug,
            "selection": "fixed_curated",
            "seeds": [1],
            "replicates": 1,
            "cluster_level": "synthetic_project",
            "cluster_id_fields": ["family_id"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": "datacenter_terms_pilot_block",
            "kind": "self_play",
            "subject_seats": ["analyst"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "datacenter_terms_diagnostic_analysis_v1",
            "estimands": [ESTIMAND_ID],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "synthetic_project",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": (
                [
                    "diagnostic_only_single_synthetic_project",
                    "historical_grounding_not_established",
                ]
                if case_manifest is None
                else [
                    "diagnostic_only_sanitized_source_grounded_case",
                    "original_source_provenance_not_publicly_reproducible",
                ]
            ),
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"datacenter_terms_{case_slug}_pilot_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    zero_pricing = TokenPricing(0.0, 0.0, 0.0, "fixed_response_zero_cost_v1")
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": "datacenter_terms_analyst_fixture_v1",
            "model": {
                "provider": "fake",
                "model": "fake-model",
                "revision": "fixed-v1",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": zero_pricing.pricing_id,
                    "pricing_sha256": zero_pricing.content_sha256(),
                },
            },
            "prompt": {
                "prompt_id": "datacenter_terms_prompt_v1",
                "sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.task.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_unspecified_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 2000,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 1,
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
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"datacenter_terms_{case_slug}_fixture_run_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"analyst": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    registry = PluginRegistry()
    registry.register_trusted(family, DataCenterTermsPlugin())
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
    environment_path = Path(__file__).with_name("environment.py")
    execution_path = Path(execution_module.__file__)
    pins = (
        _pin(PLUGIN_ID, "family_plugin", environment_path),
        _pin(SCORER_ID, "scorer", environment_path),
        _pin(ORACLE_ID, "reference", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(
            "aeread.shared_runner.task.execution",
            "runtime",
            execution_path,
            version="0.1.0",
        ),
    )
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            "fake": ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
    )
    return DataCenterTermsSetup(
        plan=plan,
        registry=registry,
        prompt_sources={"datacenter_terms_prompt_v1": PROMPT},
        pricing={"fake-model": zero_pricing},
        case=case,
        harnesses=default_harnesses(),
    )


def build_openrouter_setup(
    route: OpenRouterRoute,
    *,
    seed: int,
    case_slug: str = DEFAULT_CASE_SLUG,
    case_manifest: CaseManifest | None = None,
    max_output_tokens: int = 1400,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.02,
    harness: Any | None = None,
    harness_config: Mapping[str, Any] | None = None,
    runtime_implementation: str | None = None,
    unique_array_items: bool = False,
    indicator_maps: bool = False,
) -> DataCenterTermsSetup:
    """Resolve one exact OpenRouter route against the fixed pilot case."""

    if seed < 0:
        raise ValueError("seed must be non-negative")
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_cost_usd <= 0:
        raise ValueError("max_cost_usd must be positive for a live route")
    if indicator_maps and unique_array_items:
        raise ValueError("indicator maps and unique array items are exclusive")
    template = build_offline_setup(
        case_slug=case_slug,
        case_manifest=case_manifest,
    )
    resolved_harness = harness or MinimalChatHarness()
    resolved_runtime = runtime_implementation or (
        "aeread.shared_runner.task.execution"
        if resolved_harness.id == "minimal_chat"
        else "aeread.shared_runner.model_call.open_harnesses"
    )
    profile_id = route.profile_id
    if resolved_harness.id != "minimal_chat":
        profile_id = f"{route.profile_id}_{resolved_harness.id}"
    config: dict[str, Any] = {
        "pricing_id": route.pricing.pricing_id,
        "pricing_sha256": route.pricing.content_sha256(),
        "output_schema": (
            datacenter_terms_indicator_output_schema(template.case)
            if indicator_maps
            else datacenter_terms_output_schema(
                template.case,
                unique_array_items=unique_array_items,
            )
        ),
        "provider_metadata": {
            "route_provider": route.route_provider,
            "quantization": route.quantization,
            "canonical_model": route.revision,
            "max_prompt_price_per_million": route.max_prompt_price_per_million,
            "max_completion_price_per_million": route.max_completion_price_per_million,
        },
    }
    if harness_config is not None:
        config.update(dict(harness_config))
    if not route.temperature_supported:
        config["sampling_controls"] = {"temperature": "unavailable"}
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": profile_id,
            "model": {
                "provider": "openrouter",
                "model": route.model,
                "revision": route.revision,
                "base_url": "https://openrouter.ai/api/v1",
            },
            "harness": {
                "id": resolved_harness.id,
                "version": resolved_harness.version,
                "config": config,
            },
            "prompt": {
                "prompt_id": "datacenter_terms_prompt_v1",
                "sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
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
                "max_logical_actions": 1,
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
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"datacenter_terms_openrouter_{profile_id}",
            "suite_id": template.plan.suite.suite_id,
            "evaluation_block_ids": [
                block.block_id for block in template.plan.evaluation_blocks
            ],
            "agent_profile_ids": [profile_id],
            "seat_assignments": {"analyst": profile_id},
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
    pins = [
        pin
        for pin in template.plan.implementation_pins
        if pin.kind not in {"harness", "runtime"}
    ]
    harness_source = (
        Path(execution_module.__file__)
        if resolved_harness.id == "minimal_chat"
        else Path(inspect.getfile(type(resolved_harness)))
    )
    pins.append(
        _pin(
            resolved_harness.id,
            "harness",
            harness_source,
            version=resolved_harness.version,
        )
    )
    runtime_source = (
        Path(execution_module.__file__)
        if resolved_runtime == "aeread.shared_runner.task.execution"
        else harness_source
    )
    pins.append(_pin(resolved_runtime, "runtime", runtime_source, version="0.1.0"))
    plan = resolve_run_plan(
        families=template.plan.families,
        cases=template.plan.cases,
        suite=template.plan.suite,
        sampling=template.plan.sampling,
        evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=template.registry,
        implementation_pins=tuple(pins),
        harness_registry=harness_registry,
        provider_capabilities={
            "openrouter": ProviderCapabilities(
                native_tools=False,
                structured_output=True,
                seed=True,
                system_prompt=True,
                reasoning_budget=route.reasoning_effort is not None,
                reasoning_token_report=True,
                max_context_tokens=None,
            )
        },
    )
    return DataCenterTermsSetup(
        plan=plan,
        registry=template.registry,
        prompt_sources=template.prompt_sources,
        pricing={route.model: route.pricing},
        case=template.case,
        harnesses={
            **default_harnesses(),
            f"{resolved_harness.id}/{resolved_harness.version}": resolved_harness,
        },
    )


async def run_fixture_response(
    response_text: str,
    *,
    evidence_root: Path | str,
    case_slug: str = DEFAULT_CASE_SLUG,
    case_manifest: CaseManifest | None = None,
    episode_attempt_ordinal: int = 0,
) -> CellExecution:
    setup = build_offline_setup(
        case_slug=case_slug,
        case_manifest=case_manifest,
    )
    return await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers={"fake": FixedResponseProvider(response_text)},
        pricing=setup.pricing,
        episode_attempt_ordinal=episode_attempt_ordinal,
        harnesses=setup.harnesses,
    )


async def run_openrouter(
    route: OpenRouterRoute,
    *,
    evidence_root: Path | str,
    seed: int,
    case_slug: str = DEFAULT_CASE_SLUG,
    case_manifest: CaseManifest | None = None,
    episode_attempt_ordinal: int = 0,
    max_output_tokens: int = 1400,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.02,
    provider: Any | None = None,
    unique_array_items: bool = False,
    indicator_maps: bool = False,
) -> tuple[DataCenterTermsSetup, CellExecution]:
    """Execute one live harness-mediated analyst call without implicit retries."""

    setup = build_openrouter_setup(
        route,
        seed=seed,
        case_slug=case_slug,
        case_manifest=case_manifest,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
        unique_array_items=unique_array_items,
        indicator_maps=indicator_maps,
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


def finalize_datacenter_terms_execution(
    *, setup: DataCenterTermsSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_datacenter_terms_failure(
    *,
    setup: DataCenterTermsSetup,
    cell_id: str,
    evidence_root: Path | str,
    error: BaseException,
) -> EvaluationReceipt:
    return finalize_family_failure(
        setup=setup,
        cell_id=cell_id,
        evidence_root=evidence_root,
        error=error,
        leaf_builder=datacenter_terms_measurement_leaf,
    )


def replay_datacenter_terms_receipt(
    *,
    setup: DataCenterTermsSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=evidence_root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--run-root", "--output", dest="run_root", type=Path, required=True)
    parser.add_argument("--case", default=DEFAULT_CASE_SLUG)
    parser.add_argument("--attempt", type=int, default=0)
    arguments = parser.parse_args(argv)
    execution = asyncio.run(
        run_fixture_response(
            arguments.response.read_text(encoding="utf-8"),
            evidence_root=arguments.run_root,
            case_slug=arguments.case,
            episode_attempt_ordinal=arguments.attempt,
        )
    )
    summary = {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "total_cost_usd": execution.total_cost_usd,
        "evidence_dir": str(execution.evidence.root),
    }
    print(execution_module.canonical_json_bytes(summary).decode("utf-8"))
    return 0


__all__ = [
    "DEFAULT_CASE_SLUG",
    "PROMPT",
    "DataCenterTermsSetup",
    "OpenRouterRoute",
    "build_offline_setup",
    "build_openrouter_setup",
    "datacenter_terms_indicator_output_schema",
    "datacenter_terms_output_schema",
    "finalize_datacenter_terms_execution",
    "finalize_datacenter_terms_failure",
    "main",
    "replay_datacenter_terms_receipt",
    "run_fixture_response",
    "run_openrouter",
]
