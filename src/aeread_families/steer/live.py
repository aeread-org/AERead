"""Shared-runner setup for live STEER model episodes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aeread.shared_runner.run.adapter_campaign import BASE_URL, MODEL, PROVIDER, REVISION
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, resolve_run_plan
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

from . import cases as steer_cases
from .environment import SteerPlugin, family_manifest, register_plugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROMPT_ID = "steer_glm5p2_arena_prompt_v1"
PROMPT = """Answer the economics multiple-choice question in the observation.
Return only a JSON object with one integer field, option_id. option_id is the
zero-based index of the best answer. Do not include prose or another field."""
PRICING = TokenPricing(0.0, 0.0, 0.0, "arena_2026-09-06_glm5p2_reported_cost")
MAX_OUTPUT_TOKENS = 4096


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"option_id": {"type": "integer", "minimum": 0}},
        "required": ["option_id"],
        "additionalProperties": False,
    }


def load_case(case_id: str) -> CaseManifest:
    parts = case_id.split(".", 2)
    if len(parts) != 3 or parts[0] != "steer":
        raise ValueError(f"invalid STEER case id: {case_id}")
    element, question_id = parts[1], parts[2]
    branch = steer_cases.BRANCH_BY_ELEMENT[element]
    path = REPOSITORY_ROOT / "cases" / "steer" / branch / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pin(component_id: str, kind: str, version: str, digest: str) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {"component_id": component_id, "kind": kind, "version": version, "sha256": digest}
    )


def build_live_setup(
    *, case_id: str, data_root: Path, seed: int = 300, max_cost_usd: float = 0.03
) -> SimpleNamespace:
    case = load_case(case_id)
    family = family_manifest()
    registry = PluginRegistry()
    register_plugin(registry, plugin=SteerPlugin(steer_data_root=data_root))
    suffix = hashlib.sha256(case_id.encode()).hexdigest()[:10]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"steer_live_sampling_{suffix}",
            "estimand": "steer_answer_key",
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
            "block_id": f"steer_live_block_{suffix}",
            "kind": "self_play",
            "subject_seats": ["agent"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"steer_live_analysis_{suffix}",
            "estimands": ["steer_answer_key"],
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
            "suite_id": f"steer_live_suite_{suffix}",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": "steer_glm5p2_arena_v6",
            "model": {
                "provider": PROVIDER,
                "model": MODEL,
                "revision": REVISION,
                "base_url": BASE_URL,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": PRICING.pricing_id,
                    "pricing_sha256": PRICING.content_sha256(),
                    "output_schema": output_schema(),
                    "provider_metadata": {
                        "catalog_model_id": MODEL,
                        "provider_cost_status": "response_reported",
                    },
                },
            },
            "prompt": {"prompt_id": PROMPT_ID, "sha256": hashlib.sha256(PROMPT.encode()).hexdigest()},
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.task.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_disabled_v1",
                "effort": "none",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 1,
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
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"steer_live_run_{suffix}",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"agent": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    src = REPOSITORY_ROOT / "src" / "aeread_families" / "steer"
    environment = (src / "environment.py").read_bytes()
    measurement = (src / "measurement.py").read_bytes()
    bridge = (src / "steer_bridge_driver.py").read_bytes()
    execution_path = REPOSITORY_ROOT / "src" / "aeread" / "shared_runner" / "task" / "execution.py"
    execution_digest = hashlib.sha256(execution_path.read_bytes()).hexdigest()
    pins = (
        _pin(family.family.plugin_id, "family_plugin", family.family.version, hashlib.sha256(environment).hexdigest()),
        _pin(family.scoring.scorer_id, "scorer", family.family.version, hashlib.sha256(environment + measurement).hexdigest()),
        _pin(family.scoring.oracle_id, "reference", family.family.version, hashlib.sha256(bridge).hexdigest()),
        _pin("minimal_chat", "harness", "1.0", execution_digest),
        _pin("aeread.shared_runner.task.execution", "runtime", "0.1.0", execution_digest),
    )
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
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
    )
    return SimpleNamespace(
        plan=plan,
        registry=registry,
        prompt_sources={PROMPT_ID: PROMPT},
        pricing={MODEL: PRICING},
        case=case,
    )
