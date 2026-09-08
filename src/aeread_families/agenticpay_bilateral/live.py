"""Shared-runner setup for live AgenticPay bilateral episodes."""
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
from .agenticpay_bridge import AgenticpayBridge
from .environment import AgenticpayBilateralPlugin, family_manifest, register_plugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROMPT_ID = "agenticpay_glm5p2_arena_prompt_v1"
PROMPT = """Act as the active buyer or seller in AgenticPay using only the JSON
observation. Return one JSON object with one non-empty string field named message.
For price negotiation, include exactly one role-appropriate marker such as
`### BUYER_PRICE($100) ###` or `### SELLER_PRICE($100) ###`. Choose a price within
your private max/min bound and move toward agreement using the conversation history.
If contract_config is present, also state only feasible contract terms. Do not put
anything outside the JSON object."""
PRICING = TokenPricing(0.0, 0.0, 0.0, "arena_2026-09-06_glm5p2_reported_cost")
MAX_OUTPUT_TOKENS = 2048


class AgenticpayMessageHarness:
    id = "agenticpay_message"
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
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("AgenticPay message field must be non-empty text")
        return HarnessOutput(
            action={"message": message},
            claimed_tool_calls=(),
            rounds_used=1,
            notes={},
        )


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"message": {"type": "string", "minLength": 1}},
        "required": ["message"],
        "additionalProperties": False,
    }


def load_case(case_id: str) -> CaseManifest:
    parts = case_id.split(".")
    if len(parts) < 4 or parts[:2] != ["agenticpay", "bilateral"]:
        raise ValueError(f"invalid AgenticPay case id: {case_id}")
    split = parts[2]
    path = REPOSITORY_ROOT / "cases" / "agenticpay_bilateral" / split / f"{case_id}.json"
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
    plugin = AgenticpayBilateralPlugin(
        upstream_root=upstream_root,
        bridge=AgenticpayBridge.discover(upstream_root),
    )
    family_case = plugin.validate_payload(case.payload)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    suffix = hashlib.sha256(f"{case_id}:{sampling_seed}".encode()).hexdigest()[:10]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"agenticpay_live_sampling_{suffix}",
            "estimand": family.measurement.primary_estimand,
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
    profile_id = "agenticpay_glm5p2_arena_v1"
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"agenticpay_live_block_{suffix}",
            "kind": "controlled",
            "subject_seats": ["buyer"],
            "controlled_profiles": {"seller": profile_id},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"agenticpay_live_analysis_{suffix}",
            "estimands": [family.measurement.primary_estimand],
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
            "suite_id": f"agenticpay_live_suite_{suffix}",
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
                "id": AgenticpayMessageHarness.id,
                "version": AgenticpayMessageHarness.version,
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
            "run_spec_id": f"agenticpay_live_run_{suffix}",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"buyer": profile.profile_id, "seller": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    deal_leaf = measurement.build_deal_reached_leaf(family_case)
    surplus_leaf = measurement.build_surplus_share_leaf(family_case)
    contract_case = plugin.validate_payload(
        load_case("agenticpay.bilateral.realistic.s01_beauty_product").payload
    )
    contract_leaf = measurement.build_contract_legality_leaf(family_case)
    if contract_leaf is None:
        contract_leaf = measurement.build_contract_legality_leaf(contract_case)
    assert contract_leaf is not None
    reference_refs = {
        deal_leaf.estimand.validity_domain.predicate,
        deal_leaf.verifier.reference.implementation,
        deal_leaf.scorer,
        surplus_leaf.estimand.validity_domain.predicate,
        surplus_leaf.verifier.reference.implementation,
        surplus_leaf.scorer,
        contract_leaf.estimand.validity_domain.predicate,
        contract_leaf.verifier.reference.implementation,
        contract_leaf.scorer,
    }
    src = REPOSITORY_ROOT / "src" / "aeread_families" / "agenticpay_bilateral"
    environment_path = src / "environment.py"
    execution_path = REPOSITORY_ROOT / "src" / "aeread" / "shared_runner" / "task" / "execution.py"
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
            AgenticpayMessageHarness.id,
            "harness",
            AgenticpayMessageHarness.version,
            hashlib.sha256((src / "live.py").read_bytes()).hexdigest(),
        ),
        _pin(
            "aeread.shared_runner.task.execution",
            "runtime",
            "0.1.0",
            hashlib.sha256(execution_path.read_bytes()).hexdigest(),
        ),
    )
    harness_registry = HarnessRegistry()
    harnesses = {**default_harnesses(), "agenticpay_message/1.0": AgenticpayMessageHarness()}
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
