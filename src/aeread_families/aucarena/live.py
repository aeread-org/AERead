"""Shared-runner setup for live AucArena model episodes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aeread.shared_runner.adapter_campaign import BASE_URL, MODEL, PROVIDER, REVISION
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
from aeread.shared_runner.task.execution import ProviderResult, TokenPricing

from .environment import AucArenaPlugin, family_manifest, register_plugin
from . import measurement as aucarena_measurement

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROMPT_ID = "aucarena_glm5p2_arena_prompt_v1"
PROMPT = """You are the tested bidder in an ascending auction. Inspect the JSON
observation. Return only a JSON object with one integer field, bid_price. Bid at
least minimum_next_bid when affordable and useful; return -1 to withdraw. Never
exceed own_budget. Do not include prose or another field."""
PRICING = TokenPricing(0.0, 0.0, 0.0, "arena_2026-09-06_glm5p2_reported_cost")
MAX_OUTPUT_TOKENS = 4096
RULE_PROVIDER = "aucarena_rule"
RULE_MODEL = "rule"
RULE_PROFILE_ID = "aucarena_frozen_rule_v1"
RULE_PROMPT_ID = "aucarena_frozen_rule_prompt_v1"
RULE_PROMPT = "Return the fixed rule-bidder no-op response."
RULE_PRICING = TokenPricing(0.0, 0.0, 0.0, "aucarena_rule_zero_cost_v1")


class RuleNoopClient:
    """Local response for seats whose bids are computed inside the adapter."""

    async def complete(self, request: Any) -> ProviderResult:
        return ProviderResult(
            response_id=f"local_{request.provider_call_id}",
            requested_model=RULE_MODEL,
            resolved_model=RULE_MODEL,
            output_text='{"bid_price":-1}',
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"local_rule_noop": True},
        )


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"bid_price": {"type": "integer"}},
        "required": ["bid_price"],
        "additionalProperties": False,
    }


def load_case(case_id: str) -> CaseManifest:
    path = REPOSITORY_ROOT / "cases" / "aucarena" / "pilot" / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pin(component_id: str, kind: str, version: str, digest: str) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {"component_id": component_id, "kind": kind, "version": version, "sha256": digest}
    )


def build_live_setup(
    *, case_id: str, sampling_seed: int = 300, max_cost_usd: float = 0.03
) -> SimpleNamespace:
    case = load_case(case_id)
    family = family_manifest()
    registry = PluginRegistry()
    register_plugin(registry, plugin=AucArenaPlugin())
    suffix = hashlib.sha256(f"{case_id}:{sampling_seed}".encode()).hexdigest()[:10]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"aucarena_live_sampling_{suffix}",
            "estimand": "aucarena_profit_vs_field",
            "target": case_id,
            "selection": "fixed_curated",
            "seeds": [sampling_seed],
            "replicates": 1,
            "cluster_level": "case",
            "cluster_id_fields": ["case_id"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    profile_id = "aucarena_glm5p2_arena_v2"
    controlled_profiles = {
        seat.id: RULE_PROFILE_ID for seat in case.seats if seat.id != "agent"
    }
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"aucarena_live_block_{suffix}",
            "kind": "controlled" if controlled_profiles else "self_play",
            "subject_seats": ["agent"],
            "controlled_profiles": controlled_profiles,
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"aucarena_live_analysis_{suffix}",
            "estimands": ["aucarena_profit_vs_field"],
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
            "suite_id": f"aucarena_live_suite_{suffix}",
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
            "profile_id": profile_id,
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
            "prompt": {
                "prompt_id": PROMPT_ID,
                "sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            },
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
                "max_logical_actions": case.episode.max_logical_actions,
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
    rule_profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": RULE_PROFILE_ID,
            "model": {
                "provider": RULE_PROVIDER,
                "model": RULE_MODEL,
                "revision": "vendored-rule-v1",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": RULE_PRICING.pricing_id,
                    "pricing_sha256": RULE_PRICING.content_sha256(),
                    "output_schema": output_schema(),
                    "provider_metadata": {"provider_cost_status": "local_zero_cost"},
                },
            },
            "prompt": {
                "prompt_id": RULE_PROMPT_ID,
                "sha256": hashlib.sha256(RULE_PROMPT.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.task.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_unavailable_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "unavailable",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 16,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": case.episode.max_logical_actions,
                "timeout_seconds": 5.0,
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
    seat_assignments = {
        seat.id: (profile.profile_id if seat.id == "agent" else rule_profile.profile_id)
        for seat in case.seats
    }
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"aucarena_live_run_{suffix}",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id, rule_profile.profile_id],
            "seat_assignments": seat_assignments,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    src = REPOSITORY_ROOT / "src" / "aeread_families" / "aucarena"
    environment = (src / "environment.py").read_bytes()
    measurement = (src / "measurement.py").read_bytes()
    reference = (src / "_vendored_upstream.py").read_bytes()
    execution_path = REPOSITORY_ROOT / "src" / "aeread" / "shared_runner" / "task" / "execution.py"
    execution_digest = hashlib.sha256(execution_path.read_bytes()).hexdigest()
    pins = (
        _pin(
            family.family.plugin_id,
            "family_plugin",
            family.family.version,
            hashlib.sha256(environment).hexdigest(),
        ),
        _pin(
            family.scoring.scorer_id,
            "scorer",
            family.family.version,
            hashlib.sha256(environment + measurement + reference).hexdigest(),
        ),
        _pin("minimal_chat", "harness", "1.0", execution_digest),
        _pin("aeread.shared_runner.task.execution", "runtime", "0.1.0", execution_digest),
        _pin(
            aucarena_measurement.BASE_DOMAIN_PREDICATE_ID,
            "reference",
            family.family.version,
            hashlib.sha256(environment).hexdigest(),
        ),
        _pin(
            aucarena_measurement.BUDGET_INVARIANT_CHECK_ID,
            "reference",
            family.family.version,
            hashlib.sha256(reference).hexdigest(),
        ),
        _pin(
            aucarena_measurement.BUDGET_INVARIANT_SCORER_ID,
            "reference",
            family.family.version,
            hashlib.sha256(measurement).hexdigest(),
        ),
        _pin(
            aucarena_measurement.BID_LEGALITY_CHECK_ID,
            "reference",
            family.family.version,
            hashlib.sha256(reference).hexdigest(),
        ),
        _pin(
            aucarena_measurement.BID_LEGALITY_SCORER_ID,
            "reference",
            family.family.version,
            hashlib.sha256(measurement).hexdigest(),
        ),
        _pin(
            aucarena_measurement.HAMMER_RULE_CHECK_ID,
            "reference",
            family.family.version,
            hashlib.sha256(reference).hexdigest(),
        ),
        _pin(
            aucarena_measurement.HAMMER_RULE_SCORER_ID,
            "reference",
            family.family.version,
            hashlib.sha256(measurement).hexdigest(),
        ),
        _pin(
            aucarena_measurement.PROFIT_VS_FIELD_CHECK_ID,
            "reference",
            family.family.version,
            hashlib.sha256(measurement).hexdigest(),
        ),
        _pin(
            aucarena_measurement.PROFIT_VS_FIELD_SCORER_ID,
            "reference",
            family.family.version,
            hashlib.sha256(measurement).hexdigest(),
        ),
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
        agent_profiles=(profile, rule_profile),
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
            ),
            RULE_PROVIDER: ProviderCapabilities(
                native_tools=False,
                structured_output=True,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            ),
        },
    )
    return SimpleNamespace(
        plan=plan,
        registry=registry,
        prompt_sources={PROMPT_ID: PROMPT, RULE_PROMPT_ID: RULE_PROMPT},
        pricing={MODEL: PRICING, RULE_MODEL: RULE_PRICING},
        case=case,
    )
