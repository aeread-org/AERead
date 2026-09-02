"""Build and run the interactive procurement-allocation family."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import aeread.shared_runner.execution as execution_module
from aeread.shared_runner.execution import (
    CellExecution,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
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
from aeread_families.procurement_grounding.runner import OpenRouterRoute

from .environment import (
    PLUGIN_ID,
    SCORER_ID,
    ProcurementAllocationPlugin,
    family_manifest,
    procurement_allocation_measurement_leaf,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_PATH = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "dev"
    / "quality_speed_margin.json"
)

PROMPT = """You are the EasyCircuit procurement buyer. Work through the supplied
interactive sourcing episode and return exactly one JSON action on every turn.

Marketplace listings and verbal supplier claims are provisional. A final award is
eligible only when each referenced supplier has an unexpired formal offer, a verified
sample, and the exact required variant. Information requests, quotes, counters, and
samples consume action, time, and monetary budgets.

Allowed actions:
- inquire: supplier_id, fields, message
- request_quote: supplier_id, message
- counter_offer: supplier_id, offer_id, proposal, message
- request_sample: supplier_id, message
- submit_award: award_lines containing offer_id and quantity
- defer: reason

Use the conversation naturally to confirm specifications, quality, shipping, MOQ,
lead time, and return/refund terms. Negotiate only against a formal offer. Optimize
buyer contribution margin from completed on-time kits after landed cost, quality loss,
return recovery, financing, information cost, and shortfall penalties. Do not treat a
displayed listing price or verbal statement as a binding offer.
"""


@dataclass(frozen=True, slots=True)
class ProcurementAllocationSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]


class SequenceResponseProvider:
    """Provider fixture that serves one declared response per buyer turn."""

    def __init__(self, responses: Sequence[str]) -> None:
        if not responses:
            raise ValueError("responses must be non-empty")
        self._responses = tuple(str(response) for response in responses)
        self._cursor = 0
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        if self._cursor >= len(self._responses):
            raise RuntimeError("response script exhausted before episode termination")
        ordinal = self._cursor
        output = self._responses[ordinal]
        self._cursor += 1
        return ProviderResult(
            response_id=f"procurement_sequence_{ordinal}",
            requested_model=request.model,
            resolved_model=request.revision or request.model,
            output_text=output,
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"fixture": True, "ordinal": ordinal, "output_text": output},
        )

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._responses)


def finalize_procurement_allocation_execution(
    *, setup: ProcurementAllocationSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_procurement_allocation_failure(
    *,
    setup: ProcurementAllocationSetup,
    cell_id: str,
    evidence_root: Path | str,
    error: BaseException,
) -> EvaluationReceipt:
    return finalize_family_failure(
        setup=setup,
        cell_id=cell_id,
        evidence_root=evidence_root,
        error=error,
        leaf_builder=procurement_allocation_measurement_leaf,
    )


def replay_procurement_allocation_receipt(
    *,
    setup: ProcurementAllocationSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)


def _exact_object(
    properties: Mapping[str, Any], required: Sequence[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties if required is None else required),
        "additionalProperties": False,
    }


def procurement_action_output_schema() -> dict[str, Any]:
    text = {"type": "string"}
    nullable_number = {"type": ["number", "null"]}
    nullable_integer = {"type": ["integer", "null"]}
    nullable_text = {"type": ["string", "null"]}
    # Keep one strict root object. LangChain's OpenAI adapter cannot convert a
    # root-level JSON Schema ``oneOf`` into provider-native structured output.
    # Every action-specific field is therefore required but nullable; the
    # family parser removes null fields before applying its exact action shape.
    return _exact_object(
        {
            "action": {
                "type": "string",
                "enum": [
                    "inquire",
                    "request_quote",
                    "request_sample",
                    "counter_offer",
                    "submit_award",
                    "defer",
                ],
            },
            "supplier_id": nullable_text,
            "message": nullable_text,
            "fields": {
                "type": ["array", "null"],
                "items": text,
            },
            "offer_id": nullable_text,
            "proposal": {
                "type": ["object", "null"],
                "properties": {
                    "unit_price_usd": nullable_number,
                    "moq": nullable_integer,
                    "payment_terms_days": nullable_integer,
                    "refund_window_days": nullable_integer,
                    "return_freight_payer": nullable_text,
                },
                "required": [
                    "unit_price_usd",
                    "moq",
                    "payment_terms_days",
                    "refund_window_days",
                    "return_freight_payer",
                ],
                "additionalProperties": False,
            },
            "award_lines": {
                "type": ["array", "null"],
                "items": _exact_object(
                    {"offer_id": text, "quantity": {"type": "integer"}}
                ),
            },
            "reason": nullable_text,
        }
    )


def load_case(path: Path | str = CASE_PATH) -> CaseManifest:
    case = CaseManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
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
) -> ProcurementAllocationSetup:
    case = load_case(case_path)
    family = family_manifest()
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": "procurement_allocation_dev_sample_v1",
            "estimand": "fixed_interactive_procurement_case",
            "target": "quality_speed_margin_allocation",
            "selection": "fixed_curated",
            "seeds": [1],
            "replicates": 1,
            "cluster_level": "procurement_world",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": "procurement_allocation_dev_block",
            "kind": "self_play",
            "subject_seats": ["buyer"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "procurement_allocation_analysis_v1",
            "estimands": ["buyer_contribution_margin"],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "procurement_world",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": "procurement_allocation_dev_v1",
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
            "profile_id": "procurement_allocation_buyer_fixture_v1",
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
                    "output_schema": procurement_action_output_schema(),
                },
            },
            "prompt": {
                "prompt_id": "procurement_allocation_prompt_v1",
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
                "max_output_tokens": 1800,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 10,
                "timeout_seconds": 60.0,
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
            "run_spec_id": "procurement_allocation_dev_run_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"buyer": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, ProcurementAllocationPlugin())
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
    environment_path = Path(__file__).with_name("environment.py")
    execution_path = Path(execution_module.__file__)
    pins = (
        _pin(PLUGIN_ID, "family_plugin", environment_path),
        _pin(SCORER_ID, "scorer", environment_path),
        _pin("procurement_full_information_upper_bound_v1", "reference", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin("aeread.shared_runner.execution", "runtime", execution_path, version="0.1.0"),
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
    return ProcurementAllocationSetup(
        plan=plan,
        registry=registry,
        prompt_sources={"procurement_allocation_prompt_v1": PROMPT},
        pricing={"fake-model": zero_pricing},
        case=case,
        harnesses=default_harnesses(),
    )


def build_openrouter_setup(
    route: OpenRouterRoute,
    *,
    seed: int,
    case_path: Path | str = CASE_PATH,
    max_output_tokens: int = 1800,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.1,
    harness: Any | None = None,
) -> ProcurementAllocationSetup:
    if seed < 0:
        raise ValueError("seed must be non-negative")
    if max_cost_usd <= 0:
        raise ValueError("max_cost_usd must be positive")
    template = build_offline_setup(case_path=case_path)
    resolved_harness = harness or MinimalChatHarness()
    runtime = (
        "aeread.shared_runner.execution"
        if resolved_harness.id == "minimal_chat"
        else "aeread.shared_runner.open_harnesses"
    )
    profile_id = f"{route.profile_id}_procurement_allocation"
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
                "config": {
                    "pricing_id": route.pricing.pricing_id,
                    "pricing_sha256": route.pricing.content_sha256(),
                    "output_schema": procurement_action_output_schema(),
                    "provider_metadata": {
                        "route_provider": route.route_provider,
                        "quantization": route.quantization,
                        "canonical_model": route.revision,
                        "max_prompt_price_per_million": route.max_prompt_price_per_million,
                        "max_completion_price_per_million": route.max_completion_price_per_million,
                    },
                },
            },
            "prompt": {
                "prompt_id": "procurement_allocation_prompt_v1",
                "sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
            },
            "runtime": {"kind": "python", "implementation": runtime, "version": "0.1.0"},
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
                "temperature": 0.0 if route.temperature_supported else None,
                "max_output_tokens": max_output_tokens,
                "seed": seed,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 10,
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
            "run_spec_id": f"procurement_allocation_openrouter_{profile_id}",
            "suite_id": template.plan.suite.suite_id,
            "evaluation_block_ids": [block.block_id for block in template.plan.evaluation_blocks],
            "agent_profile_ids": [profile_id],
            "seat_assignments": {"buyer": profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    harness_registry = HarnessRegistry()
    for item in default_harnesses().values():
        harness_registry.register(item)
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
    pins.extend(
        [
            _pin(resolved_harness.id, "harness", harness_source, version=resolved_harness.version),
            _pin(runtime, "runtime", harness_source, version="0.1.0"),
        ]
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
    return ProcurementAllocationSetup(
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


async def run_fixture_script(
    responses: Sequence[str],
    *,
    evidence_root: Path | str,
    episode_attempt_ordinal: int = 0,
) -> tuple[ProcurementAllocationSetup, CellExecution, SequenceResponseProvider]:
    setup = build_offline_setup()
    provider = SequenceResponseProvider(responses)
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers={"fake": provider},
        pricing=setup.pricing,
        episode_attempt_ordinal=episode_attempt_ordinal,
        harnesses=setup.harnesses,
    )
    return setup, execution, provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=int, default=0)
    arguments = parser.parse_args(argv)
    raw = json.loads(arguments.script.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw or any(not isinstance(item, dict) for item in raw):
        raise ValueError("script must be a non-empty JSON array of action objects")
    responses = [canonical_json_bytes(item).decode("utf-8") for item in raw]
    setup, execution, provider = asyncio.run(
        run_fixture_script(
            responses,
            evidence_root=arguments.output,
            episode_attempt_ordinal=arguments.attempt,
        )
    )
    receipt = finalize_procurement_allocation_execution(setup=setup, execution=execution)
    summary = {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "receipt_status": receipt.status,
        "receipt_sha256": receipt.receipt_sha256,
        "script_exhausted": provider.exhausted,
        "total_cost_usd": execution.total_cost_usd,
        "evidence_dir": str(execution.evidence.root),
    }
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


__all__ = [
    "CASE_PATH",
    "PROMPT",
    "ProcurementAllocationSetup",
    "SequenceResponseProvider",
    "build_offline_setup",
    "build_openrouter_setup",
    "finalize_procurement_allocation_execution",
    "finalize_procurement_allocation_failure",
    "load_case",
    "main",
    "procurement_action_output_schema",
    "replay_procurement_allocation_receipt",
    "run_fixture_script",
]
