"""Shared-runner setup for live Alympics Water Allocation episodes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from aeread.shared_runner.run.adapter_campaign import AdapterCanarySpec

CANARY_SPEC = AdapterCanarySpec(
    family_id="alympics.wac",
    provider="arena",
    model="glm-5p2",
    revision="glm-5p2",
    base_url="https://api.preview.arena.ai/v1",
    route_provider="Arena",
    max_output_tokens=512,
    max_cost_usd=0.01,
)
BASE_URL = CANARY_SPEC.base_url
MODEL = CANARY_SPEC.model
PROVIDER = CANARY_SPEC.provider
REVISION = CANARY_SPEC.revision
ROUTE_PROVIDER = CANARY_SPEC.route_provider
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
from aeread.shared_runner.run.resolver import ImplementationPin, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.execution import ProviderFailure, ProviderResult, TokenPricing

from . import measurement
from .cases import SEAT_ORDER
from .environment import AlympicsWacPlugin, family_manifest, register_plugin
from .harness import POLICY_FUNCTIONS

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SUBJECT_SEAT = "alex"
PROMPT_ID = "alympics_wac_glm5p2_arena_prompt_v1"
PROMPT = """You are the focal bidder in a water-allocation game. Inspect only the
JSON observation. Return one JSON object with one integer field named bid. The bid
must be non-negative and must not exceed balance. Balance future rounds against
the current supply, requirement, health, drought counter, and public winner history.
Do not include prose or any other field."""
CONTROL_PROMPT_ID = "alympics_wac_frozen_policy_prompt_v1"
CONTROL_PROMPT = "Controlled seats use the case's deterministic local policy."
PRICING = TokenPricing(0.0, 0.0, 0.0, "arena_2026-09-06_glm5p2_reported_cost")
MAX_OUTPUT_TOKENS = 2048
CONTROL_PROVIDER = "alympics_wac_frozen"
CONTROL_MODEL = "case_policy"
CONTROL_PROFILE_ID = "alympics_wac_frozen_policy_v1"
CONTROL_PRICING = TokenPricing(0.0, 0.0, 0.0, "alympics_wac_frozen_zero_cost_v1")


class ControlledNoopClient:
    """Structural provider for seats whose actions the harness computes locally."""

    async def complete(self, request: Any) -> ProviderResult:
        return ProviderResult(
            response_id=f"local_{request.provider_call_id}", requested_model=CONTROL_MODEL,
            resolved_model=CONTROL_MODEL, output_text='{"bid":0}', finish_reason="stop",
            input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0,
            raw_response={"local_controlled_noop": True},
        )


class AlympicsBidHarness:
    """Call Arena for the focal seat and freeze all counterparts locally."""

    id = "alympics_wac_bid"
    version = "1.0"
    requires = HarnessRequirements(
        provider=frozenset(), tools="none", memory=frozenset({"disabled"}),
        owns_retries=False, owns_tools=False, replayable=True, blocking=False,
        spawns_subagents=False,
    )

    def __init__(self, policy_assignment: Mapping[str, str]) -> None:
        self.policy_assignment = dict(policy_assignment)

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
        if request.seat_id == SUBJECT_SEAT:
            input_text = canonical_json_bytes(
                {"phase_id": request.phase_id, "seat_id": request.seat_id,
                 "observation": request.observation}
            ).decode("utf-8")
            turn = await ctx.model.complete(
                messages=(CanonicalMessage(role="user", content=input_text),),
                response_mode="text",
            )
            payload = json.loads(turn.text)
            bid = payload.get("bid")
            if not isinstance(bid, int) or isinstance(bid, bool):
                raise ValueError("Alympics bid must be an integer")
        else:
            # The shared harness contract requires exactly one provider call
            # per action. This local zero-cost call is structural only; the
            # controlled action remains the case-authored deterministic bid.
            await ctx.model.complete(
                messages=(CanonicalMessage(role="user", content="return the local no-op"),),
                response_mode="text",
            )
            policy_id = self.policy_assignment[request.seat_id]
            bid = POLICY_FUNCTIONS[policy_id](request.observation)
        return HarnessOutput(action={"bid": bid}, claimed_tool_calls=(), rounds_used=1, notes={})


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"bid": {"type": "integer", "minimum": 0}},
        "required": ["bid"],
        "additionalProperties": False,
    }


def load_case(case_id: str) -> CaseManifest:
    path = REPOSITORY_ROOT / "cases" / "alympics_wac" / "base" / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pin(component_id: str, kind: str, version: str, digest: str) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {"component_id": component_id, "kind": kind, "version": version, "sha256": digest}
    )


def _profile(
    *, profile_id: str, provider: str, model: str, revision: str, prompt_id: str,
    pricing: TokenPricing, max_cost_usd: float, max_actions: int,
) -> AgentProfile:
    controlled = provider == CONTROL_PROVIDER
    return AgentProfile.from_dict({
        "spec_version": AgentProfile.SPEC_VERSION,
        "profile_id": profile_id,
        "model": {"provider": provider, "model": model, "revision": revision,
                  "base_url": None if controlled else BASE_URL},
        "harness": {"id": AlympicsBidHarness.id, "version": AlympicsBidHarness.version,
                    "config": {"pricing_id": pricing.pricing_id,
                               "pricing_sha256": pricing.content_sha256(),
                               "output_schema": output_schema(),
                               "provider_metadata": {"provider_cost_status":
                                   "local_zero_cost" if controlled else "response_reported"}}},
        "prompt": {"prompt_id": prompt_id,
                   "sha256": hashlib.sha256((CONTROL_PROMPT if controlled else PROMPT).encode()).hexdigest()},
        "runtime": {"kind": "python", "implementation": "aeread.shared_runner.task.execution",
                    "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"},
        "reasoning": {"condition_id": "reasoning_unavailable_v1" if controlled else "reasoning_disabled_v1",
                      "effort": None if controlled else "none", "token_budget": None,
                      "rationale_visibility": "unavailable" if controlled else "hidden"},
        "sampling": {"temperature": 0.0, "max_output_tokens": 16 if controlled else MAX_OUTPUT_TOKENS,
                     "seed": None, "top_p": None},
        "budgets": {"max_logical_actions": max_actions, "timeout_seconds": 180.0,
                    "max_cost_usd": max_cost_usd},
        "retry_policy": {"max_action_attempts": 1, "retryable_conditions": [],
                         "session_mode": "restart", "sdk_retries": 0},
    })


def build_live_setup(
    *, case_id: str, upstream_root: Path, sampling_seed: int = 300,
    max_cost_usd: float = 0.03,
) -> SimpleNamespace:
    case = load_case(case_id)
    family = family_manifest()
    plugin = AlympicsWacPlugin(upstream_root=upstream_root)
    family_case = plugin.validate_payload(case.payload)
    registry = PluginRegistry()
    register_plugin(registry, upstream_root=upstream_root)
    suffix = hashlib.sha256(f"{case_id}:{sampling_seed}".encode()).hexdigest()[:10]
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION,
        "sampling_plan_id": f"alympics_live_sampling_{suffix}",
        "estimand": family.measurement.primary_estimand, "target": case_id,
        "selection": "fixed_curated", "seeds": [sampling_seed], "replicates": 1,
        "cluster_level": "case", "cluster_id_fields": ["case_id"], "paired_fields": [],
        "replicate_level": "episode_attempt", "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({
        "spec_version": EvaluationBlock.SPEC_VERSION,
        "block_id": f"alympics_live_block_{suffix}", "kind": "controlled",
        "subject_seats": [SUBJECT_SEAT],
        "controlled_profiles": {seat: CONTROL_PROFILE_ID for seat in SEAT_ORDER if seat != SUBJECT_SEAT},
        "repetitions": 1, "seed_policy": "fixed",
    })
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION,
        "analysis_plan_id": f"alympics_live_analysis_{suffix}",
        "estimands": [family.measurement.primary_estimand], "group_by": ["case_id"],
        "missingness": "report_separately", "resampling_unit": "case",
        "uncertainty": "none", "multiplicity": "none", "sensitivity": [],
        "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": f"alympics_live_suite_{suffix}",
        "version": "1.0.0", "family_ids": [family.family.id], "case_ids": [case_id],
        "sampling_plan_id": sampling.sampling_plan_id, "evaluation_block_ids": [block.block_id],
        "analysis_plan_id": analysis.analysis_plan_id,
    })
    profile_id = "alympics_wac_glm5p2_arena_v1"
    profile = _profile(profile_id=profile_id, provider=PROVIDER, model=MODEL, revision=REVISION,
                       prompt_id=PROMPT_ID, pricing=PRICING, max_cost_usd=max_cost_usd,
                       max_actions=case.episode.max_logical_actions)
    controlled = _profile(profile_id=CONTROL_PROFILE_ID, provider=CONTROL_PROVIDER,
                          model=CONTROL_MODEL, revision="case-policy-v1",
                          prompt_id=CONTROL_PROMPT_ID, pricing=CONTROL_PRICING,
                          max_cost_usd=0.0, max_actions=case.episode.max_logical_actions)
    assignments = {seat: (profile_id if seat == SUBJECT_SEAT else CONTROL_PROFILE_ID) for seat in SEAT_ORDER}
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"alympics_live_run_{suffix}",
        "suite_id": suite.suite_id, "evaluation_block_ids": [block.block_id],
        "agent_profile_ids": [profile_id, CONTROL_PROFILE_ID], "seat_assignments": assignments,
        "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None,
    })
    scorer = plugin.build_scorer(family_case)
    leaves = scorer.leaves_for_focal_seat(SUBJECT_SEAT)
    refs = set()
    for leaf in leaves:
        refs.update((leaf.estimand.validity_domain.predicate,
                     leaf.verifier.reference.implementation, leaf.scorer))
    src = REPOSITORY_ROOT / "src" / "aeread_families" / "alympics_wac"
    environment_path = src / "environment.py"
    measurement_path = src / "measurement.py"
    execution_path = REPOSITORY_ROOT / "src" / "aeread" / "shared_runner" / "task" / "execution.py"
    pins = (
        _pin(family.family.plugin_id, "family_plugin", family.family.version,
             hashlib.sha256(environment_path.read_bytes()).hexdigest()),
        _pin(family.scoring.scorer_id, "scorer", family.family.version,
             hashlib.sha256(environment_path.read_bytes() + measurement_path.read_bytes()).hexdigest()),
        *tuple(_pin(ref.implementation_id, "reference", ref.version, ref.content_sha256)
               for ref in sorted(refs, key=lambda item: item.implementation_id)),
        _pin(AlympicsBidHarness.id, "harness", AlympicsBidHarness.version,
             hashlib.sha256((src / "live.py").read_bytes()).hexdigest()),
        _pin("aeread.shared_runner.task.execution", "runtime", "0.1.0",
             hashlib.sha256(execution_path.read_bytes()).hexdigest()),
    )
    harness = AlympicsBidHarness(family_case["grid_cell"]["policy_assignment"])
    harnesses = {**default_harnesses(), f"{harness.id}/{harness.version}": harness}
    harness_registry = HarnessRegistry()
    for item in harnesses.values():
        harness_registry.register(item)
    plan = resolve_run_plan(
        families=(family,), cases=(case,), suite=suite, sampling=sampling,
        evaluation_blocks=(block,), analysis=analysis, agent_profiles=(profile, controlled),
        run_spec=run_spec, registry=registry, implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            PROVIDER: ProviderCapabilities(native_tools=False, structured_output=True, seed=False,
                system_prompt=True, reasoning_budget=True, reasoning_token_report=False,
                max_context_tokens=None),
            CONTROL_PROVIDER: ProviderCapabilities(native_tools=False, structured_output=True,
                seed=False, system_prompt=True, reasoning_budget=False,
                reasoning_token_report=False, max_context_tokens=None),
        },
    )
    return SimpleNamespace(plan=plan, registry=registry,
        prompt_sources={PROMPT_ID: PROMPT, CONTROL_PROMPT_ID: CONTROL_PROMPT},
        pricing={MODEL: PRICING, CONTROL_MODEL: CONTROL_PRICING}, harnesses=harnesses, case=case)
