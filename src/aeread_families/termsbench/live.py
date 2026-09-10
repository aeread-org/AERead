"""Shared-runner setup for live TERMS-Bench episodes (#92).

Two seats. `agent` is the model under test and is the only seat with a
profile. `counterpart` is **not a model**: it is this family's own seeded
kernel, declared to the plan as a scripted seat
(`RunSpec.scripted_seats`, `docs/kernel_scripted_seats_design.md`) and
answered by `TermsBenchPlugin.scripted_response`. The scoping note
(`docs/families/termsbench/campaign_scoping.md`) records why neither of the
two workarounds -- a harness that answers without a model call, or a live
profile playing both sides -- was acceptable; the scripted seat is the
capability that note asked for.

What a model decides here: one negotiation move per `agent_turn`,
`{"decision": "offer", "price": p, "message": m}` or `{"decision":
"accept"|"reject", "message": m}`. The harness passes the model's answer
through unchanged, a JSON object as the object and anything else wrapped
as `{"raw_text": ...}`. It does not validate the move, because a malformed
or illegal move is a *measured* outcome in this family -- `parse_action`
rejects it, `_step_agent` records `malformed_action_schema` and terminates
the episode with `agreement_violation`, and `protocol_compliance` is the
admission leaf -- and a harness that re-prompted, or that typed a finished
answer as a route fault, would be scoring its own patience (TB-D-02: the
1.0 harness did the latter and aborted the v1 pilot). This is also the
kernel's own stance: the OpenRouter client keeps a completed, billable
non-JSON answer on the normal response path for the family to classify.
The only condition raised inside an attempt is an empty response, which is
a route fault and not an answer.

The route seal, retry policy and reasoning declaration follow econevals'
measured configuration on the same GLM-5.3-Flash/Parasail route
(`docs/families/econevals/incidents.md`): a reasoning token cap with no
effort declared, because the pair is rejected by the route (#133) and an
uncapped route reasons for ~12k characters before answering.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.model_call.harness import (
    AttemptContext,
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
    RunPlan,
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
from aeread.shared_runner.task.execution import (
    POST_ADMISSION_REJECTION,
    ProviderFailure,
    TokenPricing,
    ToolFailure,
)

from .environment import (
    AGENT_PHASE,
    PLUGIN_ID,
    SCORER_ID,
    TermsBenchPlugin,
    family_manifest,
)
from .measurement import (
    FEASIBLE_AGREEMENT_ESTIMAND_ID,
    NO_DEAL_AGREEMENT_ESTIMAND_ID,
    PROTOCOL_COMPLIANCE_ESTIMAND_ID,
    SURPLUS_EFFICIENCY_ESTIMAND_ID,
    declared_reference_implementations,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = REPOSITORY_ROOT / "cases" / "termsbench" / "pilot"

AGENT_SEAT = "agent"
COUNTERPART_SEAT = "counterpart"

PROVIDER = "openrouter"
MODEL = "z-ai/glm-5.3-flash"
REVISION = "z-ai/glm-5.3-flash-20260826"
ROUTE_PROVIDER = "Parasail"
QUANTIZATION = "fp8"
MAX_PROMPT_PRICE_PER_MILLION = "0.15"
MAX_COMPLETION_PRICE_PER_MILLION = "0.50"

MAX_ACTION_ATTEMPTS = 10
RETRYABLE_CONDITIONS = (
    "rate_limit",
    "provider_5xx",
    "timeout",
    "length",
    "empty_response",
    POST_ADMISSION_REJECTION,
)
PRICING = TokenPricing(
    input_per_million=0.15,
    cached_input_per_million=0.03,
    output_per_million=0.50,
    pricing_id="openrouter_2026-09-03_glm53_flash_parasail",
)

# One model call per logical action. The harness never re-prompts on a
# malformed move (see the module docstring), so a larger budget here would
# only be spent on empty responses, which the retry policy already covers.
MAX_ROUNDS = 1

# Two measured reasoning conditions on this route, not one preference.
#
# Probed 2026-09-10 with one call each on the canary observation
# (`docs/families/termsbench/campaign_scoping.md`): declaring
# `reasoning.max_tokens` at all collapses reasoning to ~13 tokens / 40
# characters *whatever the budget* -- 1,500 and 8,000 behave identically --
# and `reasoning.effort: "low"` does the same (13 tokens). Declaring nothing
# yields ~260 reasoning tokens of real deliberation on the same prompt. The
# cap is a switch, not a budget, which is the sharper form of what econevals
# recorded; an effort cannot be declared beside a cap either way (#133).
#
# So a family that wants a deliberating model on this route must declare no
# reasoning block, and one that wants a fast model declares either. Both are
# legitimate conditions and each is a campaign identity of its own.
REASONING_SUPPRESSED_V1: dict[str, object] = {
    "condition_id": "reasoning_capped_1500_v1",
    "effort": None,
    "token_budget": 1500,
    "rationale_visibility": "hidden",
}
REASONING_UNCONSTRAINED_V1: dict[str, object] = {
    "condition_id": "reasoning_unconstrained_v1",
    "effort": None,
    "token_budget": None,
    "rationale_visibility": "hidden",
}
# The default keeps pilot v2's identity readable in one name; a campaign
# names the condition it froze rather than inheriting whatever this is.
REASONING_DECLARATION = REASONING_SUPPRESSED_V1
MAX_OUTPUT_TOKENS = 4000
# With no reasoning block the route emits its rationale into the same
# completion budget, so a deliberating campaign needs headroom the
# suppressed one does not.
MAX_OUTPUT_TOKENS_UNCONSTRAINED = 12000

PROMPT_ID = "termsbench_negotiation_json_v1"
PROMPT = """You are negotiating the price of a single item with one counterpart
over a fixed number of alternating rounds. The observation tells you your
role (buyer or seller), your private reservation value r_a -- the most a
buyer will pay, or the least a seller will accept -- the allowed price
bounds, the horizon, the current round, every offer made so far by each
side, and the transcript of messages. You never learn the counterpart's
reservation value. If no agreement is reached within the horizon, the
negotiation ends with no deal and both sides receive nothing.

Return only a JSON object for your move this round:
- {"decision": "offer", "price": <number>, "message": "<one or two sentences>"}
  -- propose a price within the bounds; the message is shown to the
  counterpart.
- {"decision": "accept", "message": "<one or two sentences>"} -- accept the
  counterpart's most recent offer at that price. Do not include a price.
- {"decision": "reject", "message": "<one or two sentences>"} -- walk away
  and end the negotiation with no deal. Do not include a price.
"""


def route_metadata() -> dict[str, str]:
    """The five-field route seal the kernel requires: exactly these fields
    and no others."""
    return {
        "route_provider": ROUTE_PROVIDER,
        "quantization": QUANTIZATION,
        "canonical_model": REVISION,
        "max_prompt_price_per_million": MAX_PROMPT_PRICE_PER_MILLION,
        "max_completion_price_per_million": MAX_COMPLETION_PRICE_PER_MILLION,
    }


def agent_output_schema() -> dict[str, Any]:
    """The structured-output schema for the agent's move.

    Nothing is `required` and `price` is not conditioned on `decision`:
    the family's `parse_action` decides whether a price is required or
    forbidden for the chosen decision, and a schema that pre-empted it
    would move that judgment out of the measured family and into the
    profile.
    """
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["offer", "accept", "reject"]},
            "price": {"type": "number"},
            "message": {"type": "string"},
        },
        "additionalProperties": False,
    }


class TermsBenchJsonHarness:
    """One model call per agent turn; the answer is handed to the family
    unchanged.

    The counterpart phase is never routed here: the plan declares the seat
    as scripted and the kernel answers it from the plugin. A request for any
    other phase is a contract violation, not something to answer.

    1.1: a finished answer that is not a JSON object reaches the family as
    `{"raw_text": text}` and is measured there; 1.0 raised it as a route
    fault (TB-D-02).
    """

    id = "termsbench_json"
    version = "1.1"
    requires = HarnessRequirements(
        provider=frozenset({"structured_output"}),
        tools="none",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=True,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )

    async def open_episode(self, episode: Any) -> None:
        return None

    async def close_episode(self, episode: Any) -> None:
        return None

    def classify_failure(self, exc: BaseException) -> FailureCondition:
        if isinstance(exc, (ProviderFailure, ToolFailure)):
            return FailureCondition(exc.condition, retryable=exc.retryable)
        return FailureCondition("harness_error", retryable=False)

    def state_reader(self) -> Any:
        return None

    @staticmethod
    def _request_message(request: Any) -> CanonicalMessage:
        return CanonicalMessage(
            role="user",
            content=canonical_json_bytes(
                {
                    "phase_id": request.phase_id,
                    "seat_id": request.seat_id,
                    "role": request.role,
                    "observation_schema": request.observation_schema,
                    "action_schema": request.action_schema,
                    "observation": request.observation,
                }
            ).decode("utf-8"),
        )

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        if request.phase_id != AGENT_PHASE or request.seat_id != AGENT_SEAT:
            raise ProviderFailure(
                "harness_contract",
                f"termsbench harness asked for {request.seat_id!r} in phase "
                f"{request.phase_id!r}; only the agent seat is a model",
                retryable=False,
            )
        turn = await ctx.model.complete(
            messages=(self._request_message(request),),
            response_mode="json_dialect",
        )
        text = (turn.text or "").strip()
        if not text:
            raise ProviderFailure(
                "empty_response",
                "termsbench agent turn returned an empty response",
                retryable=True,
            )
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        # A finished answer that is not an object is the model's move, and
        # the family measures it: `parse_action` finds no decision,
        # `_step_agent` records `malformed_action_schema`. The sealed
        # provider result keeps the text and its finish reason.
        action = dict(value) if isinstance(value, Mapping) else {"raw_text": text}
        return HarnessOutput(
            action=action,
            claimed_tool_calls=(),
            rounds_used=1,
            notes={},
        )


@dataclass(frozen=True)
class TermsBenchLiveSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]
    tool_runtime_factories: Mapping[str, Any]


def load_case(case_id: str) -> CaseManifest:
    path = CASES_DIR / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pin(identifier: str, kind: str, path: Path, *, version: str) -> ImplementationPin:
    return ImplementationPin(
        component_id=identifier,
        kind=kind,
        version=version,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _measurement_pins() -> tuple[ImplementationPin, ...]:
    return tuple(
        ImplementationPin(
            component_id=reference.implementation_id,
            kind="reference",
            version=reference.version,
            sha256=reference.content_sha256,
        )
        for reference in declared_reference_implementations()
    )


def _profile(
    *,
    seed: int,
    max_logical_actions: int,
    max_cost_usd: float,
    reasoning: Mapping[str, object] = REASONING_DECLARATION,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            # The reasoning condition is part of the agent's identity: two
            # profiles differing only in it are two agents, not one agent
            # twice.
            "profile_id": (
                "termsbench_agent_glm53_flash_parasail_v1"
                if reasoning["condition_id"] == REASONING_SUPPRESSED_V1["condition_id"]
                else f"termsbench_agent_glm53_flash_parasail_{reasoning['condition_id']}"
            ),
            "model": {
                "provider": PROVIDER,
                "model": MODEL,
                "revision": REVISION,
                "base_url": "https://openrouter.ai/api/v1",
            },
            "harness": {
                "id": TermsBenchJsonHarness.id,
                "version": TermsBenchJsonHarness.version,
                "config": {
                    "pricing_id": PRICING.pricing_id,
                    "pricing_sha256": PRICING.content_sha256(),
                    "output_schema": agent_output_schema(),
                    "max_rounds": MAX_ROUNDS,
                    "retry_backoff": "exponential_jitter_v1",
                    "retry_base_seconds": 5.0,
                    "retry_after_max_seconds": 60.0,
                    "provider_metadata": route_metadata(),
                },
            },
            "prompt": {
                "prompt_id": PROMPT_ID,
                "sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread_families.termsbench.live",
                "version": "1.0.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": dict(reasoning),
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": max_output_tokens,
                "seed": seed,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": max_logical_actions,
                "timeout_seconds": 180.0,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                "max_action_attempts": MAX_ACTION_ATTEMPTS,
                "retryable_conditions": list(RETRYABLE_CONDITIONS),
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def build_live_setup(
    *,
    case_id: str,
    seed: int,
    max_trajectory_cost_usd: float,
    reasoning: Mapping[str, object] = REASONING_DECLARATION,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> TermsBenchLiveSetup:
    case = load_case(case_id)
    family = family_manifest()
    plugin = TermsBenchPlugin()
    plugin.validate_payload(case.payload)
    seat_ids = {seat.id for seat in case.seats}
    if seat_ids != {AGENT_SEAT, COUNTERPART_SEAT}:
        raise ValueError(
            f"termsbench case {case_id!r} declares seats {sorted(seat_ids)}; "
            f"the live setup expects exactly {[AGENT_SEAT, COUNTERPART_SEAT]}"
        )
    # The case's own episode budget bounds both seats' logical actions; the
    # agent seat can never need more than that, and a tighter profile
    # budget would end an episode the case says may continue.
    profile = _profile(
        seed=seed,
        max_logical_actions=case.episode.max_logical_actions,
        max_cost_usd=max_trajectory_cost_usd,
        reasoning=reasoning,
        max_output_tokens=max_output_tokens,
    )
    suffix = case_id.replace(".", "_")
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"termsbench_pilot_{suffix}",
            "estimand": "fixed_termsbench_pilot_case",
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
    # `controlled`: one subject seat against a control that is not under
    # test. The controlled identity is whatever fills the seat -- a profile
    # id for a model seat, a policy id for a scripted one -- so the control
    # here is the counterpart's policy id, and the resolver holds it against
    # `RunSpec.scripted_seats`.
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"termsbench_pilot_block_{suffix}",
            "kind": "controlled",
            "subject_seats": [AGENT_SEAT],
            "controlled_profiles": {COUNTERPART_SEAT: TermsBenchPlugin.COUNTERPART_POLICY_ID},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    # All four estimands, not only the primary: the leaves are
    # regime-dependent (Overlap emits surplus efficiency and feasible
    # agreement, No-deal emits no-deal agreement, both emit protocol
    # compliance), and a plan that only knew the primary would report the
    # No-deal half of the corpus as empty.
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "termsbench_pilot_analysis_v1",
            "estimands": [
                SURPLUS_EFFICIENCY_ESTIMAND_ID,
                FEASIBLE_AGREEMENT_ESTIMAND_ID,
                NO_DEAL_AGREEMENT_ESTIMAND_ID,
                PROTOCOL_COMPLIANCE_ESTIMAND_ID,
            ],
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
            "suite_id": f"termsbench_pilot_suite_{suffix}",
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
            "run_spec_id": f"termsbench_pilot_run_{suffix}",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {AGENT_SEAT: profile.profile_id},
            "scripted_seats": {COUNTERPART_SEAT: TermsBenchPlugin.COUNTERPART_POLICY_ID},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, plugin)
    harness = TermsBenchJsonHarness()
    harness_registry = HarnessRegistry()
    harness_registry.register(harness)
    environment_path = Path(inspect.getfile(TermsBenchPlugin))
    live_path = Path(inspect.getfile(TermsBenchJsonHarness))
    measurement_path = environment_path.with_name("measurement.py")
    pins = (
        *_measurement_pins(),
        _pin(PLUGIN_ID, "family_plugin", environment_path, version="0.1.0"),
        _pin(SCORER_ID, "scorer", measurement_path, version="0.1.0"),
        _pin(TermsBenchJsonHarness.id, "harness", live_path, version=TermsBenchJsonHarness.version),
        _pin("aeread_families.termsbench.live", "runtime", live_path, version="1.0.0"),
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
            PROVIDER: ProviderCapabilities(
                native_tools=False,
                structured_output=True,
                seed=True,
                system_prompt=True,
                reasoning_budget=True,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
        tool_bindings={},
    )
    return TermsBenchLiveSetup(
        plan=plan,
        registry=registry,
        prompt_sources={PROMPT_ID: PROMPT},
        pricing={MODEL: PRICING},
        case=case,
        harnesses={
            **default_harnesses(),
            f"{harness.id}/{harness.version}": harness,
        },
        tool_runtime_factories={},
    )


__all__ = [
    "AGENT_SEAT",
    "COUNTERPART_SEAT",
    "MAX_OUTPUT_TOKENS",
    "MAX_OUTPUT_TOKENS_UNCONSTRAINED",
    "MAX_ROUNDS",
    "MODEL",
    "PRICING",
    "PROMPT",
    "PROMPT_ID",
    "PROVIDER",
    "QUANTIZATION",
    "REASONING_DECLARATION",
    "REASONING_SUPPRESSED_V1",
    "REASONING_UNCONSTRAINED_V1",
    "REVISION",
    "ROUTE_PROVIDER",
    "TermsBenchJsonHarness",
    "TermsBenchLiveSetup",
    "agent_output_schema",
    "build_live_setup",
    "load_case",
    "route_metadata",
]
