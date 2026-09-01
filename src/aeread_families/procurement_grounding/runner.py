"""Build and run the procurement-grounding case through AERead's shared runner."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.execution as execution_module
from aeread.shared_runner.execution import CellExecution, TokenPricing, execute_plan_cell
from aeread.shared_runner.family_evaluation import (
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.harness import MinimalChatHarness, default_harnesses
from aeread.shared_runner.receipts import EvaluationReceipt
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.resolver import (
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
from aeread.shared_runner.smoke import FixedResponseProvider

from .environment import (
    PLUGIN_ID,
    SCORER_ID,
    ProcurementGroundingPlugin,
    family_manifest,
    procurement_measurement_leaf,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_PATH = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_grounding_v1"
    / "dev"
    / "procurement_grounding_231_projects.json"
)

PROMPT = """You are the procurement analyst for EasyCircuit. Causal Orchid is pilot
evidence, not the company scope. Read the supplied frozen sourcing evidence and return
only one JSON object, with no markdown or surrounding explanation.

Use exactly these top-level fields:
- readiness_decision: string
- scope: string
- source_counts: object containing every metric_id shown in source_coverage
- priority_families: exactly three objects in descending priority_score order, each
  containing family_id, project_count, accepted_suppliers, priority_score, priority_band
- supplier_distribution: object containing top_search_card_supplier,
  top_search_card_unique_skus, top_search_card_candidate_slots,
  largest_outreach_assignment_supplier, largest_outreach_assigned_skus
- evidence_interpretations: booleans for candidate_slots_are_unique_listings,
  displayed_prices_are_verified_quotes, post_buyer_reply_is_structured_quote,
  raw_captures_are_normalized_suppliers, project_boms_are_production_truth
- procurement_controls: object containing accepted_suppliers_target,
  shortlist_structure, and variant_gates keyed by the three priority family IDs
- next_steps: an array of machine-readable action identifiers

Do not place an order, send a supplier message, turn displayed prices into landed-cost
claims, or count search/reply records as accepted suppliers. A readiness claim other
than defer_bulk_order is invalid for this frozen evidence state.
"""


@dataclass(frozen=True, slots=True)
class ProcurementGroundingSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]


def finalize_procurement_execution(
    *, setup: ProcurementGroundingSetup, execution: CellExecution
) -> EvaluationReceipt:
    """Seal and score one procurement execution through the shared receipt path."""

    return finalize_family_execution(setup=setup, execution=execution)


def finalize_procurement_failure(
    *,
    setup: ProcurementGroundingSetup,
    cell_id: str,
    evidence_root: Path | str,
    error: BaseException,
) -> EvaluationReceipt:
    """Persist an operational procurement failure as an excluded receipt."""

    return finalize_family_failure(
        setup=setup,
        cell_id=cell_id,
        evidence_root=evidence_root,
        error=error,
        leaf_builder=procurement_measurement_leaf,
    )


def replay_procurement_receipt(
    *,
    setup: ProcurementGroundingSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    """Recompute procurement state and score without another provider call."""

    return replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )


@dataclass(frozen=True, slots=True)
class OpenRouterRoute:
    """One immutable OpenRouter endpoint and its reviewed token prices."""

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


def procurement_report_output_schema(case: CaseManifest) -> dict[str, Any]:
    """Return the strict wire schema without exposing any oracle values."""
    oracle = case.payload["oracle"]

    def exact_object(properties: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": dict(properties),
            "required": list(properties),
            "additionalProperties": False,
        }

    # Keep the provider-facing schema inside the common strict-JSON subset.
    # The family parser below remains authoritative for non-negativity, exact
    # array lengths, non-empty strings, and uniqueness.
    integer = {"type": "integer"}
    nonempty_string = {"type": "string"}
    priority_row = exact_object(
        {
            "family_id": nonempty_string,
            "project_count": integer,
            "accepted_suppliers": integer,
            "priority_score": integer,
            "priority_band": nonempty_string,
        }
    )
    source_counts = exact_object(
        {key: integer for key in oracle["source_counts"]}
    )
    supplier_distribution = exact_object(
        {
            "top_search_card_supplier": nonempty_string,
            "top_search_card_unique_skus": integer,
            "top_search_card_candidate_slots": integer,
            "largest_outreach_assignment_supplier": nonempty_string,
            "largest_outreach_assigned_skus": integer,
        }
    )
    evidence_interpretations = exact_object(
        {key: {"type": "boolean"} for key in oracle["evidence_interpretations"]}
    )
    variant_gates = exact_object(
        {
            family_id: {
                "type": "array",
                "items": nonempty_string,
            }
            for family_id in oracle["variant_gates"]
        }
    )
    procurement_controls = exact_object(
        {
            "accepted_suppliers_target": integer,
            "shortlist_structure": nonempty_string,
            "variant_gates": variant_gates,
        }
    )
    return exact_object(
        {
            "readiness_decision": nonempty_string,
            "scope": nonempty_string,
            "source_counts": source_counts,
            "priority_families": {
                "type": "array",
                "items": priority_row,
            },
            "supplier_distribution": supplier_distribution,
            "evidence_interpretations": evidence_interpretations,
            "procurement_controls": procurement_controls,
            "next_steps": {
                "type": "array",
                "items": nonempty_string,
            },
        }
    )


def load_case(path: Path | str = CASE_PATH) -> CaseManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    case = CaseManifest.from_dict(raw)
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


def build_offline_setup(
    *, case_path: Path | str = CASE_PATH
) -> ProcurementGroundingSetup:
    """Resolve a one-cell, zero-cost plan for deterministic response testing."""
    case = load_case(case_path)
    family = family_manifest()
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": "procurement_grounding_dev_sample_v1",
            "estimand": "fixed_procurement_grounding_case",
            "target": "procurement_grounding_231_projects",
            "selection": "fixed_curated",
            "seeds": [1],
            "replicates": 1,
            "cluster_level": "source_snapshot",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": "procurement_grounding_dev_block",
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
            "analysis_plan_id": "procurement_grounding_analysis_v1",
            "estimands": ["procurement_grounding_accuracy"],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "source_snapshot",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": "procurement_grounding_dev_v1",
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
            "profile_id": "procurement_analyst_fixture_v1",
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
                "prompt_id": "procurement_grounding_prompt_v1",
                "sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.execution",
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
                "max_output_tokens": 6000,
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
            "run_spec_id": "procurement_grounding_dev_run_v1",
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
    registry.register(family, ProcurementGroundingPlugin())
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_path = Path(__file__).with_name("environment.py")
    execution_path = Path(execution_module.__file__)
    pins = (
        _pin(PLUGIN_ID, "family_plugin", environment_path),
        _pin(SCORER_ID, "scorer", environment_path),
        _pin("procurement_grounding_oracle_v1", "reference", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(
            "aeread.shared_runner.execution",
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
    return ProcurementGroundingSetup(
        plan=plan,
        registry=registry,
        prompt_sources={"procurement_grounding_prompt_v1": PROMPT},
        pricing={"fake-model": zero_pricing},
        case=case,
        harnesses=default_harnesses(),
    )


def build_openrouter_setup(
    route: OpenRouterRoute,
    *,
    seed: int,
    case_path: Path | str = CASE_PATH,
    max_output_tokens: int = 2500,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.01,
    harness: Any | None = None,
    harness_config: Mapping[str, Any] | None = None,
    runtime_implementation: str | None = None,
) -> ProcurementGroundingSetup:
    """Resolve the frozen procurement case against one exact OpenRouter route."""
    if seed < 0:
        raise ValueError("seed must be non-negative")
    if max_cost_usd <= 0:
        raise ValueError("max_cost_usd must be positive for a live route")

    template = build_offline_setup(case_path=case_path)
    resolved_harness = harness or MinimalChatHarness()
    resolved_runtime = runtime_implementation or (
        "aeread.shared_runner.execution"
        if resolved_harness.id == "minimal_chat"
        else "aeread.shared_runner.open_harnesses"
    )
    resolved_profile_id = route.profile_id
    if resolved_harness.id != "minimal_chat":
        resolved_profile_id = f"{route.profile_id}_{resolved_harness.id}"
    resolved_harness_config: dict[str, Any] = {
        "pricing_id": route.pricing.pricing_id,
        "pricing_sha256": route.pricing.content_sha256(),
        "output_schema": procurement_report_output_schema(template.case),
        "provider_metadata": {
            "route_provider": route.route_provider,
            "quantization": route.quantization,
            "canonical_model": route.revision,
            "max_prompt_price_per_million": route.max_prompt_price_per_million,
            "max_completion_price_per_million": route.max_completion_price_per_million,
        },
    }
    if harness_config is not None:
        resolved_harness_config.update(dict(harness_config))
    if not route.temperature_supported:
        resolved_harness_config["sampling_controls"] = {
            "temperature": "unavailable"
        }

    profile = AgentProfile.from_dict(
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
                "config": resolved_harness_config,
            },
            "prompt": {
                "prompt_id": "procurement_grounding_prompt_v1",
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
            "run_spec_id": f"procurement_grounding_openrouter_{resolved_profile_id}",
            "suite_id": template.plan.suite.suite_id,
            "evaluation_block_ids": [
                block.block_id for block in template.plan.evaluation_blocks
            ],
            "agent_profile_ids": [resolved_profile_id],
            "seat_assignments": {"analyst": resolved_profile_id},
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
    harness_source_path = (
        Path(execution_module.__file__)
        if resolved_harness.id == "minimal_chat"
        else Path(inspect.getfile(type(resolved_harness)))
    )
    pins.append(
        _pin(
            resolved_harness.id,
            "harness",
            harness_source_path,
            version=resolved_harness.version,
        )
    )
    runtime_source_path = (
        Path(execution_module.__file__)
        if resolved_runtime == "aeread.shared_runner.execution"
        else harness_source_path
    )
    pins.append(
        _pin(
            resolved_runtime,
            "runtime",
            runtime_source_path,
            version="0.1.0",
        )
    )
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
    return ProcurementGroundingSetup(
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
    episode_attempt_ordinal: int = 0,
):
    setup = build_offline_setup()
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=int, default=0)
    arguments = parser.parse_args(argv)
    response_text = arguments.response.read_text(encoding="utf-8")
    execution = asyncio.run(
        run_fixture_response(
            response_text,
            evidence_root=arguments.output,
            episode_attempt_ordinal=arguments.attempt,
        )
    )
    summary: dict[str, Any] = {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "total_cost_usd": execution.total_cost_usd,
        "evidence_dir": str(execution.evidence.root),
    }
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


__all__ = [
    "CASE_PATH",
    "PROMPT",
    "OpenRouterRoute",
    "ProcurementGroundingSetup",
    "build_offline_setup",
    "build_openrouter_setup",
    "load_case",
    "main",
    "procurement_report_output_schema",
    "run_fixture_response",
]
