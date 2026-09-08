"""Shared-runner setup for live NegotiationArena model episodes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aeread.shared_runner.run.adapter_campaign import BASE_URL, MODEL, PROVIDER, REVISION
from aeread.shared_runner.model_call.harness import (
    CanonicalMessage,
    FailureCondition,
    HarnessOutput,
    default_harnesses,
)
from aeread.shared_runner.registry import (
    HarnessRegistry,
    HarnessRequirements,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    canonical_json_bytes,
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
from aeread.shared_runner.task.execution import ProviderFailure, TokenPricing

from . import measurement
from .cases import BLUE, RED
from .environment import NegarenaPlugin, family_manifest, register_plugin
from .negarena_bridge import NegarenaBridge

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROMPT_ID = "negarena_glm5p2_arena_prompt_v1"
PROMPT = """Act as the active NegotiationArena seat using only the JSON observation.
Return one JSON object with one string field named response. That string must contain
all required upstream tags: <message>, <player answer>, <newly proposed trade>,
<my resources>, and <reason>. Use player answer PROPOSAL, ACCEPT, or REJECT.
A proposal must look exactly like `Player RED Gives TOKEN: N | Player BLUE Gives
TOKEN: N`; use NONE when accepting or rejecting. Never offer resources a seat does
not own. For buy_sell also include <my goals> and <proposal count>; for ultimatum
also include <move>. Do not put anything outside the JSON object."""
PRICING = TokenPricing(0.0, 0.0, 0.0, "arena_2026-09-06_glm5p2_reported_cost")
MAX_OUTPUT_TOKENS = 4096


class NegarenaTextHarness:
    """Convert the provider's structured text into the adapter action mapping."""

    id = "negarena_text"
    version = "1.0"
    requires = HarnessRequirements(
        provider=frozenset(),
        tools="none",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=False,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )

    async def open_episode(self, episode: Any) -> None:
        return None

    async def close_episode(self, episode: Any) -> None:
        return None

    def classify_failure(self, exc: BaseException) -> FailureCondition:
        if isinstance(exc, ProviderFailure):
            return FailureCondition(exc.condition, retryable=exc.retryable)
        return FailureCondition("harness_error", retryable=False)

    def state_reader(self) -> Any:
        return None

    async def act(self, request: Any, ctx: Any) -> HarnessOutput:
        input_text = canonical_json_bytes(
            {
                "phase_id": request.phase_id,
                "seat_id": request.seat_id,
                "observation": request.observation,
            }
        ).decode("utf-8")
        turn = await ctx.model.complete(
            messages=(CanonicalMessage(role="user", content=input_text),),
            response_mode="text",
        )
        payload = json.loads(turn.text)
        response = payload.get("response")
        if not isinstance(response, str) or not response.strip():
            raise ValueError("NegotiationArena response field must be non-empty text")
        return HarnessOutput(
            action={"response": response},
            claimed_tool_calls=(),
            rounds_used=1,
            notes={},
        )


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"response": {"type": "string", "minLength": 1}},
        "required": ["response"],
        "additionalProperties": False,
    }


def load_case(case_id: str) -> CaseManifest:
    parts = case_id.split(".")
    if len(parts) != 3 or parts[0] != "negarena":
        raise ValueError(f"invalid NegotiationArena case id: {case_id}")
    path = REPOSITORY_ROOT / "cases" / "negarena" / parts[1] / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pin(component_id: str, kind: str, version: str, digest: str) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {"component_id": component_id, "kind": kind, "version": version, "sha256": digest}
    )


def build_live_setup(
    *,
    case_id: str,
    upstream_root: Path,
    sampling_seed: int = 300,
    max_cost_usd: float = 0.03,
) -> SimpleNamespace:
    case = load_case(case_id)
    family = family_manifest()
    plugin = NegarenaPlugin(
        upstream_root=upstream_root,
        bridge=NegarenaBridge.discover(upstream_root),
    )
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    suffix = hashlib.sha256(f"{case_id}:{sampling_seed}".encode()).hexdigest()[:10]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"negarena_live_sampling_{suffix}",
            "estimand": measurement.SEAT_OUTCOME_ESTIMAND_ID,
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
    profile_id = "negarena_glm5p2_arena_v1"
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"negarena_live_block_{suffix}",
            "kind": "controlled",
            "subject_seats": [RED],
            "controlled_profiles": {BLUE: profile_id},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"negarena_live_analysis_{suffix}",
            "estimands": [measurement.SEAT_OUTCOME_ESTIMAND_ID],
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
            "suite_id": f"negarena_live_suite_{suffix}",
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
                "id": NegarenaTextHarness.id,
                "version": NegarenaTextHarness.version,
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
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"negarena_live_run_{suffix}",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {RED: profile.profile_id, BLUE: profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    src = REPOSITORY_ROOT / "src" / "aeread_families" / "negarena"
    environment_path = src / "environment.py"
    execution_path = REPOSITORY_ROOT / "src" / "aeread" / "shared_runner" / "task" / "execution.py"
    harness_path = src / "live.py"
    reference_refs = {
        measurement.build_seat_outcome_leaf().estimand.validity_domain.predicate,
        measurement.build_seat_outcome_leaf().verifier.reference.implementation,
        measurement.build_seat_outcome_leaf().scorer,
        measurement.build_agreement_reached_leaf().verifier.reference.implementation,
        measurement.build_agreement_reached_leaf().scorer,
    }
    pins = (
        _pin(
            family.family.plugin_id,
            "family_plugin",
            family.family.version,
            hashlib.sha256(environment_path.read_bytes()).hexdigest(),
        ),
        _pin(
            family.scoring.scorer_id,
            "scorer",
            family.family.version,
            hashlib.sha256(environment_path.read_bytes()).hexdigest(),
        ),
        *tuple(
            _pin(ref.implementation_id, "reference", ref.version, ref.content_sha256)
            for ref in sorted(reference_refs, key=lambda item: item.implementation_id)
        ),
        _pin(
            NegarenaTextHarness.id,
            "harness",
            NegarenaTextHarness.version,
            hashlib.sha256(harness_path.read_bytes()).hexdigest(),
        ),
        _pin(
            "aeread.shared_runner.task.execution",
            "runtime",
            "0.1.0",
            hashlib.sha256(execution_path.read_bytes()).hexdigest(),
        ),
    )
    harness_registry = HarnessRegistry()
    harnesses = {**default_harnesses(), "negarena_text/1.0": NegarenaTextHarness()}
    for harness in harnesses.values():
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
        harnesses=harnesses,
        case=case,
    )
