"""One-cell shared-runner smoke fixture for provider-free and live R1-R4 checks."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .execution import (
    CanonicalResponse,
    ClaudeCodePrintClient,
    OpenAIResponsesClient,
    OpenRouterChatClient,
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
from .scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)
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


SINGLE_OFFER_PROMPT = (
    "Return only one JSON object with one integer field named offer. "
    "Do not add markdown or explanation."
)
SINGLE_OFFER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"offer": {"type": "integer", "minimum": 0}},
    "required": ["offer"],
    "additionalProperties": False,
}


class SingleOfferPlugin:
    """Minimal family with one private observation and one economic action."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, int]:
        private_value = payload.get("private_value")
        if isinstance(private_value, bool) or not isinstance(private_value, int):
            raise ValueError("private_value must be an integer")
        return {"private_value": private_value}

    def initial_state(self, case, run):
        return {"private_value": case["private_value"], "offer": None, "done": False}

    def phases(self, case):
        return (
            PhaseSpec(
                phase_id="offer",
                actor_selector="buyer_only",
                mode="single",
                observation_schema_by_role={"buyer": "private_value_v1"},
                action_schema_by_role={"buyer": "offer_v1"},
                max_logical_actions=1,
                invalid_action_policy="reject",
                next_phases=(),
            ),
        )

    def eligible_actors(self, case, state, phase):
        return ("buyer",)

    def observe(self, case, state, seat, phase):
        return {"private_value": state["private_value"]}

    def parse_action(self, case, state, seat, phase, response):
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        offer = value.get("offer") if isinstance(value, dict) else None
        if isinstance(offer, bool) or not isinstance(offer, int):
            return ParseResult.failure("malformed_offer")
        return ParseResult.success({"offer": offer})

    def legal(self, case, state, seat, phase, action):
        if action["offer"] < 0:
            return LegalityResult.illegal("negative_offer")
        return LegalityResult.legal_action()

    def step(self, case, state, phase, actions):
        next_state = dict(state)
        next_state["offer"] = actions["buyer"].action["offer"]
        next_state["done"] = True
        return TransitionResult(state=next_state, next_phase_id=None)

    def terminal(self, case, state):
        return {"reason": "submitted", "offer": state["offer"]} if state["done"] else None

    def outcome(self, case, terminal):
        return {
            "valid": True,
            "reason": terminal["reason"],
            "offer": terminal["offer"],
        }

    def build_scorer(self, case):
        return lambda outcome: outcome

    def build_reference_providers(self, case):
        return ()

    def generator(self):
        return None


class FixedResponseProvider:
    """Zero-cost provider fixture that still crosses the R4 provider boundary."""

    def __init__(self, output_text: str) -> None:
        self.output_text = output_text

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(
            response_id="fixed_response_v1",
            requested_model=request.model,
            resolved_model=request.revision or request.model,
            output_text=self.output_text,
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"output_text": self.output_text, "fixture": True},
        )


@dataclass(frozen=True, slots=True)
class SmokeSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]


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


def _pricing_for(model: str) -> TokenPricing:
    if model == "fake-model":
        return TokenPricing(0.0, 0.0, 0.0, "fixed_response_zero_cost_v1")
    if model in {"gpt-5-nano", "gpt-5-nano-2025-08-07"}:
        return TokenPricing(
            input_per_million=0.05,
            cached_input_per_million=0.005,
            output_per_million=0.40,
            pricing_id="openai_standard_2026-08-26_gpt-5-nano",
        )
    if model == "claude-haiku-4-5-20251001":
        return TokenPricing(
            input_per_million=1.0,
            cached_input_per_million=0.10,
            output_per_million=5.0,
            pricing_id="anthropic_standard_2026-08-26_claude-haiku-4-5",
        )
    if model == "deepseek/deepseek-v4-flash-0731":
        return TokenPricing(
            input_per_million=0.08,
            cached_input_per_million=0.016,
            output_per_million=0.18,
            pricing_id="openrouter_deepinfra_2026-08-26_deepseek-v4-flash-0731",
        )
    raise ValueError(
        f"smoke fixture has no reviewed pricing pin for model {model!r}"
    )


def _capabilities_for(provider: str) -> ProviderCapabilities:
    """Declared capabilities for a smoke provider (§5.3).

    `minimal_chat/1.0` is the only harness this fixture ever admits and its
    `requires.provider` is empty, so none of these flags gates anything here;
    they are declared honestly (no unverified claim) rather than left
    unspecified.
    """

    return ProviderCapabilities(
        native_tools=False,
        structured_output=False,
        seed=provider == "openrouter",
        system_prompt=True,
        reasoning_budget=False,
        reasoning_token_report=False,
        max_context_tokens=None,
    )


def build_single_offer_smoke(
    *,
    provider: str,
    model: str,
    revision: str,
    provider_runtime: Mapping[str, str] | None = None,
) -> SmokeSetup:
    """Build and seal one fully pinned R1-R2 plan for the native smoke family."""
    family = FamilyManifest.from_dict(
        {
            "spec_version": "aeread.family/0.1",
            "family": {
                "id": "single_offer_v1",
                "version": "1.0.0",
                "plugin_id": "aeread.single_offer_v1",
            },
            "environment": {
                "topology": "single_private_decision",
                "phase_specs": ["offer"],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {"buyer": {"testable": True}},
            "measurement": {
                "primary_estimand": "submitted_offer_validity",
                "measurement_kind": "property_or_answer",
                "direction": "none",
            },
            "scoring": {"scorer_id": "single_offer_scorer_v1"},
            "generator": {
                "generator_id": "single_offer_generator_v1",
                "difficulty_knobs": [],
            },
        }
    )
    raw_case = {
        "spec_version": "aeread.case/0.1",
        "case_id": "single_offer_v1__smoke__000001",
        "family_id": "single_offer_v1",
        "family_version": "1.0.0",
        "split": "smoke",
        "world_seed": 71001,
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {"max_logical_actions": 1, "termination": ["submitted"]},
        "visibility_policy": "single_offer_private_v1",
        "payload": {"private_value": 11},
        "provenance": {
            "generator_id": "single_offer_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw_case["content_sha256"] = case_content_sha256(raw_case)
    case = CaseManifest.from_dict(raw_case)
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": "single_offer_smoke_sample_v1",
            "estimand": "fixed_smoke_case",
            "target": "single_offer_smoke_fixture",
            "selection": "fixed_curated",
            "seeds": [1],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": "single_offer_smoke_block",
            "kind": "self_play",
            "subject_seats": ["buyer"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "single_offer_smoke_analysis_v1",
            "estimands": ["submitted_offer_validity"],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "cluster_id",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": "single_offer_smoke_v1",
            "version": "1.0.0",
            "family_ids": ["single_offer_v1"],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    model_pricing = _pricing_for(model)
    harness_config: dict[str, Any] = {
        "pricing_id": model_pricing.pricing_id,
        "pricing_sha256": model_pricing.content_sha256(),
    }
    if provider == "claude_code":
        if not isinstance(provider_runtime, Mapping):
            raise ValueError("claude_code smoke requires pinned provider_runtime")
        harness_config.update(
            {
                "output_schema": SINGLE_OFFER_OUTPUT_SCHEMA,
                "provider_runtime": dict(provider_runtime),
                "sampling_controls": {
                    "temperature": "unavailable",
                    "max_output_tokens": "provider_model_default",
                },
            }
        )
    elif provider == "openrouter":
        harness_config.update(
            {
                "output_schema": SINGLE_OFFER_OUTPUT_SCHEMA,
                "provider_metadata": {
                    "route_provider": "DeepInfra",
                    "quantization": "fp8",
                    "canonical_model": "deepseek/deepseek-v4-flash-20260731",
                    "max_prompt_price_per_million": "0.08",
                    "max_completion_price_per_million": "0.18",
                },
            }
        )
    profile = AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": "subject_model_v1",
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
                        else None
                    )
                ),
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": harness_config,
            },
            "prompt": {
                "prompt_id": "single_offer_prompt_v1",
                "sha256": hashlib.sha256(SINGLE_OFFER_PROMPT.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_low_v1",
                "effort": "low",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": (
                    32_000
                    if provider == "claude_code"
                    else (512 if provider == "openrouter" else 80)
                ),
                "seed": 71001 if provider == "openrouter" else None,
                "top_p": 1.0 if provider == "openrouter" else None,
            },
            "budgets": {
                "max_logical_actions": 1,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.01 if provider == "claude_code" else 0.001,
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
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": "single_offer_smoke_run_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"buyer": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    plugin = SingleOfferPlugin()
    registry = PluginRegistry()
    registry.register(family, plugin)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
    smoke_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    execution_source_sha256 = hashlib.sha256(
        Path(__file__).with_name("execution.py").read_bytes()
    ).hexdigest()
    pins = (
        _pin(
            "aeread.single_offer_v1",
            "family_plugin",
            source_sha256=smoke_source_sha256,
        ),
        _pin(
            "single_offer_scorer_v1",
            "scorer",
            source_sha256=smoke_source_sha256,
        ),
        _pin(
            "single_offer_generator_v1",
            "generator",
            source_sha256=smoke_source_sha256,
        ),
        _pin(
            "minimal_chat",
            "harness",
            source_sha256=execution_source_sha256,
            version="1.0",
        ),
        _pin(
            "aeread.shared_runner.execution",
            "runtime",
            source_sha256=execution_source_sha256,
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
        provider_capabilities={provider: _capabilities_for(provider)},
    )
    return SmokeSetup(
        plan=plan,
        registry=registry,
        prompt_sources={"single_offer_prompt_v1": SINGLE_OFFER_PROMPT},
        pricing={model: model_pricing},
    )


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    provider_runtime = None
    if arguments.provider == "fake":
        model = arguments.model or "fake-model"
        revision = arguments.revision or "fixed-v1"
        provider_client = FixedResponseProvider(json.dumps({"offer": arguments.offer}))
    elif arguments.provider == "openai":
        model = arguments.model or "gpt-5-nano-2025-08-07"
        revision = arguments.revision or model
        provider_client = OpenAIResponsesClient()
    elif arguments.provider == "openrouter":
        model = arguments.model or "deepseek/deepseek-v4-flash-0731"
        revision = arguments.revision or "deepseek/deepseek-v4-flash-20260731"
        provider_client = OpenRouterChatClient()
    else:
        model = arguments.model or "claude-haiku-4-5-20251001"
        revision = arguments.revision or model
        provider_client = await ClaudeCodePrintClient.discover()
        provider_runtime = provider_client.runtime_metadata
    setup = build_single_offer_smoke(
        provider=arguments.provider,
        model=model,
        revision=revision,
        provider_runtime=provider_runtime,
    )
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=arguments.output,
        prompt_sources=setup.prompt_sources,
        providers={arguments.provider: provider_client},
        pricing=setup.pricing,
        episode_attempt_ordinal=arguments.attempt,
    )
    return {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "total_cost_usd": execution.total_cost_usd,
        "evidence_dir": str(execution.evidence.root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("fake", "openai", "openrouter", "claude_code"),
        default="fake",
    )
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument("--offer", type=int, default=7)
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    print(canonical_json_bytes(asyncio.run(_run_cli(arguments))).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "FixedResponseProvider",
    "SINGLE_OFFER_PROMPT",
    "SINGLE_OFFER_OUTPUT_SCHEMA",
    "SingleOfferPlugin",
    "SmokeSetup",
    "build_single_offer_smoke",
    "main",
]
