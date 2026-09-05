"""Shared-runner setup for live tau3.retail model episodes."""
from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
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
from aeread.shared_runner.task.execution import TokenPricing
from aeread.shared_runner.task.tools import ToolRuntime

from .environment import PLUGIN_ID, SCORER_ID, Tau3RetailPlugin, family_manifest
from .harness import Tau3RetailJsonHarness
from .tau2_bridge import Tau2Bridge
from .tools import RetailToolSession, build_tool_bindings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROVIDER = "arena"
MODEL = "glm-5p2"
REVISION = "glm-5p2"
ROUTE_PROVIDER = "Arena"
QUANTIZATION = "not_reported"
PRICING = TokenPricing(
    input_per_million=0.0,
    cached_input_per_million=0.0,
    output_per_million=0.0,
    pricing_id="arena_2026-09-05_glm5p2_response_reported_cost",
)
ASSISTANT_PROMPT_ID = "tau3_retail_assistant_json_v1"
USER_PROMPT_ID = "tau3_retail_user_sim_json_v1"
ASSISTANT_PROMPT = """You are the retail support assistant. Follow the policy and
tool definitions supplied in the context. Return only the required JSON object.
Use kind=tool_calls with one or more calls when a tool is needed. Use kind=reply with
a customer-facing response only when no tool call is needed. Never invent tool results.
Never claim that an account or order was found unless the corresponding tool result is
present. Keep customer-facing replies under 80 words and do not repeat known details.
"""
USER_PROMPT = """You are the simulated retail customer. Follow the user scenario and
simulation guidelines supplied in the observation. Return only a kind=reply JSON object.
Use the exact upstream stop markers when the scenario and guidelines require stopping.
Keep each reply under 40 words and do not repeat details already established.
"""


def assistant_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["reply", "tool_calls"]},
            "text": {"type": ["string", "null"]},
            "calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "arguments": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["id", "name", "arguments"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["kind", "text", "calls"],
        "additionalProperties": False,
    }


def user_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["reply"]},
            "text": {"type": "string"},
        },
        "required": ["kind", "text"],
        "additionalProperties": False,
    }


@dataclass(frozen=True, slots=True)
class Tau3RetailLiveSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]
    tool_runtime_factories: Mapping[str, Callable[[Any], ToolRuntime]]


def load_case(case_id: str) -> CaseManifest:
    path = REPOSITORY_ROOT / "cases" / "tau3_retail" / "base" / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pin(component_id: str, kind: str, path: Path, *, version: str) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )


def _profile(
    *,
    seat: str,
    prompt_id: str,
    prompt: str,
    output_schema: Mapping[str, Any],
    tools: tuple[str, ...],
    seed: int,
    max_output_tokens: int,
    max_cost_usd: float,
) -> AgentProfile:
    profile_id = f"tau3_retail_{seat}_glm5p2_arena_v1"
    return AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": profile_id,
            "model": {
                "provider": PROVIDER,
                "model": MODEL,
                "revision": REVISION,
                "base_url": "https://api.preview.arena.ai/v1",
            },
            "harness": {
                "id": Tau3RetailJsonHarness.id,
                "version": Tau3RetailJsonHarness.version,
                "config": {
                    "pricing_id": PRICING.pricing_id,
                    "pricing_sha256": PRICING.content_sha256(),
                    "output_schema": output_schema,
                    "max_rounds": 12 if seat == "assistant" else 1,
                    "provider_metadata": {
                        "catalog_model_id": MODEL,
                        "provider_cost_status": "response_reported",
                    },
                },
            },
            "prompt": {
                "prompt_id": prompt_id,
                "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread_families.tau3_retail.harness",
                "version": "1.0.0",
            },
            "tools": list(tools),
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_low_v1",
                "effort": "low",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": max_output_tokens,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 100,
                "timeout_seconds": 180.0,
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


def build_live_setup(
    *,
    case_id: str,
    upstream_root: Path,
    bridge: Tau2Bridge,
    seed: int,
    max_trajectory_cost_usd: float = 0.05,
) -> Tau3RetailLiveSetup:
    case = load_case(case_id)
    family = family_manifest()
    tool_schema = bridge.fetch_tool_schema()
    tool_names = tuple(sorted(tool_schema["tools"]))
    raw_db = json.loads(
        (
            upstream_root
            / "data"
            / "tau2"
            / "domains"
            / "retail"
            / "db.json"
        ).read_text(encoding="utf-8")
    )
    session = RetailToolSession(bridge.normalize_db(raw_db))
    harness = Tau3RetailJsonHarness(bridge=bridge, session=session)
    assistant = _profile(
        seat="assistant",
        prompt_id=ASSISTANT_PROMPT_ID,
        prompt=ASSISTANT_PROMPT,
        output_schema=assistant_output_schema(),
        tools=tool_names,
        seed=seed,
        max_output_tokens=4096,
        max_cost_usd=max_trajectory_cost_usd,
    )
    user = _profile(
        seat="user",
        prompt_id=USER_PROMPT_ID,
        prompt=USER_PROMPT,
        output_schema=user_output_schema(),
        tools=(),
        seed=seed,
        max_output_tokens=4096,
        max_cost_usd=max_trajectory_cost_usd,
    )
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"tau3_retail_pipeline_{case_id.rsplit('.', 1)[-1]}",
            "estimand": "fixed_tau3_retail_pipeline_case",
            "target": case_id,
            "selection": "fixed_curated",
            "seeds": [seed],
            "replicates": 1,
            "cluster_level": "case",
            "cluster_id_fields": ["case_id"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"tau3_retail_pipeline_block_{case_id.rsplit('.', 1)[-1]}",
            "kind": "self_play",
            "subject_seats": ["assistant", "user"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "tau3_retail_pipeline_analysis_v1",
            "estimands": ["retail_task_reward"],
            "group_by": ["case_id"],
            "missingness": "report_separately",
            "resampling_unit": "case",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"tau3_retail_pipeline_suite_{case_id.rsplit('.', 1)[-1]}",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"tau3_retail_pipeline_run_{case_id.rsplit('.', 1)[-1]}",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [assistant.profile_id, user.profile_id],
            "seat_assignments": {
                "assistant": assistant.profile_id,
                "user": user.profile_id,
            },
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(
        family,
        Tau3RetailPlugin(upstream_root=upstream_root, bridge=bridge),
    )
    harness_registry = HarnessRegistry()
    harness_registry.register(harness)
    environment_path = Path(inspect.getfile(Tau3RetailPlugin))
    harness_path = Path(inspect.getfile(Tau3RetailJsonHarness))
    measurement_path = environment_path.with_name("measurement.py")
    bridge_path = environment_path.with_name("tau2_bridge.py")
    pins = (
        _pin(PLUGIN_ID, "family_plugin", environment_path, version="0.1.0"),
        _pin(SCORER_ID, "scorer", measurement_path, version="0.1.0"),
        _pin(
            "tau3_retail_base_domain_predicate",
            "reference",
            environment_path,
            version="0.1.0",
        ),
        _pin(
            "tau3_retail_environment_evaluator_bridge",
            "reference",
            bridge_path,
            version="0.1.0",
        ),
        _pin(Tau3RetailJsonHarness.id, "harness", harness_path, version="1.0"),
        _pin(
            "aeread_families.tau3_retail.harness",
            "runtime",
            harness_path,
            version="1.0.0",
        ),
    )
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(assistant, user),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            PROVIDER: ProviderCapabilities(
                native_tools=False,
                structured_output=True,
                seed=False,
                system_prompt=True,
                reasoning_budget=True,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
        tool_bindings={assistant.profile_id: frozenset(tool_names)},
    )

    def runtime_factory(evidence: Any) -> ToolRuntime:
        return ToolRuntime(evidence, build_tool_bindings(bridge, session))

    return Tau3RetailLiveSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            ASSISTANT_PROMPT_ID: ASSISTANT_PROMPT,
            USER_PROMPT_ID: USER_PROMPT,
        },
        pricing={MODEL: PRICING},
        case=case,
        harnesses={
            **default_harnesses(),
            f"{harness.id}/{harness.version}": harness,
        },
        tool_runtime_factories={assistant.profile_id: runtime_factory},
    )


__all__ = [
    "ASSISTANT_PROMPT",
    "MODEL",
    "PRICING",
    "QUANTIZATION",
    "REVISION",
    "ROUTE_PROVIDER",
    "Tau3RetailLiveSetup",
    "assistant_output_schema",
    "build_live_setup",
    "load_case",
    "user_output_schema",
]
