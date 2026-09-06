"""Shared-runner setup for live econevals period-loop episodes.

Mirrors ``tau3_retail.live``'s role for a family whose phase graph is a
single self-looping period phase (``environment.PERIOD_PHASE``) with one
seat, rather than a two-phase user/assistant alternation. One live model
call produces one period's ordered tool-call burst; the harness executes
every call through the kernel ``ToolRuntime`` and returns the
``{"tool_calls", "tool_executions"}`` action shape
``EconevalsPlugin.parse_action`` requires, so ``step`` can independently
re-derive each result from its own FSM state.

Route: the matrix ruling pins these campaigns to OpenRouter GLM 5.3 Flash
on Parasail (fp8), the same pinned route the procurement family uses --
NOT the Arena ``glm-5p2`` route accepted for the tau3 pipeline proof only.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.model_call.harness import (
    AttemptContext,
    CanonicalMessage,
    ClaimedToolCall,
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
    ProviderFailure,
    TokenPricing,
    ToolFailure,
)
from aeread.shared_runner.task.tools import ToolRuntime

from .cases import MAX_LLM_QUERIES_PER_PERIOD
from .econevals_bridge import EconevalsBridge
from .environment import (
    PERIOD_PHASE,
    PLUGIN_ID,
    SCORER_ID,
    SEAT_ID,
    TRACK_TOOLS,
    EconevalsPlugin,
    family_manifest,
)
from .measurement import declared_reference_implementations
from .tools import EconevalsToolSession, build_tool_bindings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = REPOSITORY_ROOT / "cases" / "econevals"

PROVIDER = "openrouter"
MODEL = "z-ai/glm-5.3-flash"
REVISION = "z-ai/glm-5.3-flash-20260826"
ROUTE_PROVIDER = "Parasail"
QUANTIZATION = "fp8"
# The adapter refuses any route whose advertised price exceeds these caps, so
# a silent reroute to a pricier backend fails closed instead of billing.
MAX_ACTION_ATTEMPTS = 10
# "length" and "empty_response" are the kernel's own typed response
# conditions; declaring them lets the executor retry a truncated or empty
# turn one layer below the harness's corrective rounds.
RETRYABLE_CONDITIONS = (
    "rate_limit",
    "provider_5xx",
    "timeout",
    "length",
    "empty_response",
)
MAX_PROMPT_PRICE_PER_MILLION = "0.15"
MAX_COMPLETION_PRICE_PER_MILLION = "0.50"
PRICING = TokenPricing(
    input_per_million=0.15,
    cached_input_per_million=0.03,
    output_per_million=0.50,
    pricing_id="openrouter_2026-09-03_glm53_flash_parasail",
)

PROMPT_ID = "econevals_period_json_v1"
PROMPT = """You are running one period of an economic decision task. The observation
names the track, the read-only tools you may call, and the single submit tool that ends
the period. Return only the required JSON object: an ordered list of tool calls whose
LAST call is the submit tool. Use tool names exactly as given in the observation's
read_only_tools and submit_tool fields -- do not invent or abbreviate a name. Call
read-only tools first to gather what you need, then submit your decision for this
period. Never invent tool results.
"""


def route_metadata() -> dict[str, str]:
    """The exact sealed route the OpenRouter adapter requires -- these five
    fields and no others, or it refuses the call as a provider_contract
    failure."""
    return {
        "route_provider": ROUTE_PROVIDER,
        "quantization": QUANTIZATION,
        "canonical_model": REVISION,
        "max_prompt_price_per_million": MAX_PROMPT_PRICE_PER_MILLION,
        "max_completion_price_per_million": MAX_COMPLETION_PRICE_PER_MILLION,
    }


def period_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
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
            }
        },
        "required": ["calls"],
        "additionalProperties": False,
    }


class EconevalsJsonHarness:
    """One live model call per period; every claimed call is really executed.

    The response's ``calls`` list is executed in order through the kernel
    ``ToolRuntime`` against this episode's ``EconevalsToolSession``. The
    ``tool_executions`` this returns are therefore the SAME dispatches
    ``environment.step`` re-derives independently -- the harness never
    hand-writes a result. After the burst, the session advances one period
    (``tools.advance_period``), exactly as the scripted harness does, so the
    next period's ``get_previous_*``/``get_attempt_number`` responses already
    reflect the attempt just submitted.
    """

    id = "econevals_json"
    version = "1.0"
    requires = HarnessRequirements(
        provider=frozenset({"structured_output"}),
        tools="declared",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=False,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )

    def __init__(self, *, session: EconevalsToolSession, family_case: Mapping[str, Any]) -> None:
        self.session = session
        self.family_case = family_case

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

    @staticmethod
    def _decode(text: str) -> tuple[Mapping[str, Any] | None, str]:
        """Decode a period response, reporting failure instead of raising.

        A malformed or truncated response is correctable -- nothing has been
        executed when it arrives -- so it feeds the corrective round loop
        rather than killing the episode outright.
        """
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None, "return one complete JSON object and nothing else"
        if not isinstance(value, Mapping):
            return None, "the response must be a JSON object"
        return value, ""

    @staticmethod
    def _validate_burst(
        calls: Any, *, submit_tool: str
    ) -> tuple[tuple[dict[str, Any], ...] | None, str]:
        """Check a whole period's calls before executing any of them.

        Returns ``(normalized_calls, "")`` or ``(None, reason)``. Validating
        the burst as a unit matters: a period half-executed and then rejected
        would leave tool effects the environment never scored.
        """
        if not isinstance(calls, list) or not calls:
            return None, "return a non-empty calls list"
        if len(calls) > MAX_LLM_QUERIES_PER_PERIOD + 1:
            return None, (
                f"use at most {MAX_LLM_QUERIES_PER_PERIOD + 1} calls in one period"
            )
        normalized: list[dict[str, Any]] = []
        for index, call in enumerate(calls):
            if not isinstance(call, Mapping):
                return None, f"call {index} must be an object"
            call_id = call.get("id")
            name = call.get("name")
            arguments = call.get("arguments")
            if not isinstance(call_id, str) or not call_id:
                return None, f"call {index} needs a non-empty string id"
            if not isinstance(name, str) or not name:
                return None, f"call {index} needs a tool name"
            if not isinstance(arguments, Mapping):
                return None, f"call {index} needs an arguments object"
            is_last = index == len(calls) - 1
            if is_last and name != submit_tool:
                return None, (
                    f"the last call of the period must be {submit_tool!r}, "
                    f"got {name!r}"
                )
            if not is_last and name == submit_tool:
                return None, (
                    f"{submit_tool!r} ends the period, so it must be the last call"
                )
            normalized.append({"id": call_id, "name": name, "arguments": arguments})
        return tuple(normalized), ""

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        if request.phase_id != PERIOD_PHASE or request.seat_id != SEAT_ID:
            raise ProviderFailure(
                "harness_contract",
                f"unsupported econevals phase {request.phase_id!r}/seat {request.seat_id!r}",
                retryable=False,
            )
        if ctx.tools is None:
            raise ToolFailure(
                "tools_not_admitted",
                "econevals period requires its declared tool runtime",
                retryable=False,
            )
        track = self.family_case["track"]
        submit_tool = TRACK_TOOLS[track]["submit_tool"]
        read_only = tuple(TRACK_TOOLS[track]["read_only"])

        messages = (self._request_message(request),)
        rounds_used = 0
        normalized_calls: tuple[dict[str, Any], ...] | None = None
        turn = None
        while rounds_used < max(1, ctx.budget.rounds_left):
            turn = await ctx.model.complete(
                messages=messages, response_mode="json_dialect"
            )
            rounds_used += 1
            if not (turn.text or "").strip():
                # An empty turn is a typed PROVIDER condition, not a malformed
                # answer: there is nothing to give feedback about, and the
                # executor's retry policy already lists empty_response. Raising
                # it here hands the retry to the layer that owns it instead of
                # spending a corrective round on silence.
                raise ProviderFailure(
                    "empty_response",
                    "econevals period returned an empty response",
                    retryable=True,
                )
            value, reason = self._decode(turn.text or "")
            if value is not None:
                normalized_calls, reason = self._validate_burst(
                    value.get("calls"), submit_tool=submit_tool
                )
                if normalized_calls is not None:
                    break
            elif getattr(turn, "truncated", False):
                # Say so explicitly: a bare "invalid JSON" sends the next
                # round chasing syntax when the real problem is length.
                reason = (
                    "your previous response was cut off by the output limit; "
                    "return fewer, shorter calls in one complete JSON object"
                )
            # Correctable: nothing has been executed yet, so hand back the
            # exact violation and the legal tool names rather than failing the
            # episode on a first malformed burst.
            messages = messages + (
                CanonicalMessage(
                    role="user",
                    content=canonical_json_bytes(
                        {
                            "error": reason,
                            "read_only_tools": list(read_only),
                            "submit_tool": submit_tool,
                        }
                    ).decode("utf-8"),
                ),
            )
        if normalized_calls is None:
            raise ProviderFailure(
                "malformed_structured_output",
                f"econevals period was still malformed after {rounds_used} rounds",
                retryable=False,
            )

        tool_calls: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        claimed: list[ClaimedToolCall] = []
        for index, call in enumerate(normalized_calls):
            envelope = await ctx.tools.invoke(
                tool_id=call["name"],
                arguments=call["arguments"],
                source_provider_call_id=turn.provider_call_id,
                source_call_index=index,
            )
            plain_arguments = json.loads(canonical_json_bytes(call["arguments"]))
            plain_result = json.loads(canonical_json_bytes(envelope.result))
            tool_calls.append(
                {"id": call["id"], "name": call["name"], "arguments": plain_arguments}
            )
            executions.append(
                {
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "arguments": plain_arguments,
                    "result": plain_result,
                    "invocation_record_id": envelope.invocation_record.tool_invocation_id,
                }
            )
            claimed.append(
                ClaimedToolCall(
                    tool_id=call["name"],
                    source_provider_call_id=turn.provider_call_id,
                    source_call_index=index,
                )
            )

        # Mirror the post-period advance `step` applies, so the next period's
        # read-only responses reflect this period's submitted attempt.
        self.session.advance_period(self.family_case)
        return HarnessOutput(
            action={"tool_calls": tool_calls, "tool_executions": executions},
            claimed_tool_calls=tuple(claimed),
            rounds_used=rounds_used,
            notes={},
        )


@dataclass(frozen=True)
class EconevalsLiveSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]
    tool_runtime_factories: Mapping[str, Any]


def load_case(case_id: str) -> CaseManifest:
    split = _split_for(case_id)
    path = CASES_DIR / split / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _split_for(case_id: str) -> str:
    # econevals.<track>.basic.<seed> -> <track>_basic
    parts = case_id.split(".")
    if len(parts) != 4 or parts[0] != "econevals" or parts[2] != "basic":
        raise ValueError(f"unrecognized econevals case id: {case_id!r}")
    return f"{parts[1]}_basic"


def _pin(
    identifier: str, kind: str, path: Path, *, version: str
) -> ImplementationPin:
    return ImplementationPin(
        component_id=identifier,
        kind=kind,
        version=version,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _measurement_pins() -> tuple[ImplementationPin, ...]:
    """Pin every implementation the declared leaves cite, family-wide.

    Derived from the leaf builders, never hand-typed: the receipt refuses to
    seal unless each cited implementation (upstream's own solver digests, the
    validity-domain predicate) is pinned with the same version and content
    digest, which is what makes "this score came from upstream's solver"
    checkable rather than asserted. The set is family-wide rather than
    per-case because the resolver requires exactly the manifest's declared
    reference providers.
    """
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
    case_id: str,
    tools: tuple[str, ...],
    max_periods: int,
    max_cost_usd: float,
    seed: int,
) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": "econevals_agent_glm53_flash_parasail_v1",
            "model": {
                "provider": PROVIDER,
                "model": MODEL,
                "revision": REVISION,
                "base_url": "https://openrouter.ai/api/v1",
            },
            "harness": {
                "id": EconevalsJsonHarness.id,
                "version": EconevalsJsonHarness.version,
                "config": {
                    "pricing_id": PRICING.pricing_id,
                    "pricing_sha256": PRICING.content_sha256(),
                    "output_schema": period_output_schema(),
                    "max_rounds": 5,
                    # Backoff is opt-in: with no retry_backoff declared the
                    # executor returns without sleeping, so ten attempts fire
                    # back-to-back into the same burst and buy nothing. That
                    # is exactly what killed attempt 010 in two minutes.
                    # Base 5s doubling (capped at 30s) spreads ten attempts
                    # over several minutes, which is the housing d78a1bc8
                    # lesson applied here.
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
                "implementation": "aeread_families.econevals.live",
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
                # A procurement period names six read-only tools and then
                # submits a full purchase plan; 900 truncated that mid-JSON
                # on the first live attempt (decode failed at char 910).
                "max_output_tokens": 2400,
                # Declared, not None: the OpenRouter adapter refuses a
                # diagnostic run whose seed is not stated, because an
                # undeclared seed makes a re-run unfalsifiable.
                "seed": seed,
                "top_p": None,
            },
            "budgets": {
                # Equal to the case's pinned max_steps; see build_live_setup.
                "max_logical_actions": max_periods,
                "timeout_seconds": 180.0,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                # Do the arithmetic the housing V19 postmortem says to do at
                # design time. This family makes ONE call per period and 100
                # periods per case, so a six-case panel is ~600 sequential
                # calls; a single unretried 429 anywhere kills the whole run,
                # which is what tau3's one-attempt policy did here. Parasail
                # serves GLM 5.3 Flash from a shared upstream pool that
                # rate-limits in bursts, so attempts are set high enough that
                # a burst has to persist across all of them to lose a case.
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
    bridge: EconevalsBridge,
    seed: int,
    max_trajectory_cost_usd: float,
) -> EconevalsLiveSetup:
    case = load_case(case_id)
    family = family_manifest()
    plugin = EconevalsPlugin(bridge=bridge)
    family_case = plugin.validate_payload(case.payload)
    track = family_case["track"]
    tool_names = tuple(
        sorted(
            (*TRACK_TOOLS[track]["read_only"], TRACK_TOOLS[track]["submit_tool"])
        )
    )
    session = EconevalsToolSession(plugin.initial_state(family_case, None))
    harness = EconevalsJsonHarness(session=session, family_case=family_case)
    # The period ceiling is the case's OWN pinned ``max_steps`` -- the value the
    # environment terminates on as ``max_periods``. It is deliberately not a
    # separate pilot knob: the profile budget is a hard contract error when
    # exceeded (SchedulerContractError), not a clean termination, so any
    # smaller number here would turn a finished episode into a failed one.
    profile = _profile(
        case_id=case_id,
        tools=tool_names,
        max_periods=int(family_case["pins"]["max_steps"]),
        max_cost_usd=max_trajectory_cost_usd,
        seed=seed,
    )
    suffix = case_id.replace(".", "_")
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"econevals_pilot_{suffix}",
            "estimand": "fixed_econevals_pilot_case",
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
            "block_id": f"econevals_pilot_block_{suffix}",
            "kind": "self_play",
            "subject_seats": [SEAT_ID],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "econevals_pilot_analysis_v1",
            "estimands": ["econevals_headroom_capture"],
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
            "suite_id": f"econevals_pilot_suite_{suffix}",
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
            "run_spec_id": f"econevals_pilot_run_{suffix}",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {SEAT_ID: profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, plugin)
    harness_registry = HarnessRegistry()
    harness_registry.register(harness)
    environment_path = Path(inspect.getfile(EconevalsPlugin))
    live_path = Path(inspect.getfile(EconevalsJsonHarness))
    measurement_path = environment_path.with_name("measurement.py")
    pins = (
        *_measurement_pins(),
        _pin(PLUGIN_ID, "family_plugin", environment_path, version="0.1.0"),
        _pin(SCORER_ID, "scorer", measurement_path, version="0.1.0"),
        _pin(EconevalsJsonHarness.id, "harness", live_path, version="1.0"),
        _pin(
            "aeread_families.econevals.live",
            "runtime",
            live_path,
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
        tool_bindings={profile.profile_id: frozenset(tool_names)},
    )

    def runtime_factory(evidence: Any) -> ToolRuntime:
        return ToolRuntime(evidence, build_tool_bindings(plugin, family_case, session))

    return EconevalsLiveSetup(
        plan=plan,
        registry=registry,
        prompt_sources={PROMPT_ID: PROMPT},
        pricing={MODEL: PRICING},
        case=case,
        harnesses={
            **default_harnesses(),
            f"{harness.id}/{harness.version}": harness,
        },
        tool_runtime_factories={profile.profile_id: runtime_factory},
    )


__all__ = [
    "MODEL",
    "PRICING",
    "PROMPT",
    "PROMPT_ID",
    "PROVIDER",
    "QUANTIZATION",
    "REVISION",
    "ROUTE_PROVIDER",
    "EconevalsJsonHarness",
    "EconevalsLiveSetup",
    "build_live_setup",
    "load_case",
    "period_output_schema",
    "route_metadata",
]
