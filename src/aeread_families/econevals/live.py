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
    POST_ADMISSION_REJECTION,
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


@dataclass(frozen=True)
class RouteSpec:
    """One pinned serving of one model: the five-field seal, the price book
    and the structured-output dialect that endpoint accepts."""

    model: str
    revision: str
    route_provider: str
    quantization: str
    max_prompt_price_per_million: str
    max_completion_price_per_million: str
    pricing: TokenPricing
    profile_suffix: str
    output_schema_dialect: str = "permissive"


GLM53_FLASH_PARASAIL = RouteSpec(
    model="z-ai/glm-5.3-flash",
    revision="z-ai/glm-5.3-flash-20260826",
    route_provider="Parasail",
    quantization="fp8",
    max_prompt_price_per_million="0.15",
    max_completion_price_per_million="0.50",
    pricing=TokenPricing(
        input_per_million=0.15,
        cached_input_per_million=0.03,
        output_per_million=0.50,
        pricing_id="openrouter_2026-09-03_glm53_flash_parasail",
    ),
    profile_suffix="glm53_flash_parasail",
)

# The only agent from the EconEvals paper this route can serve: Claude 3.5
# Sonnet and Gemini 1.5 Pro list no live endpoints at all. `2024-08-06` is
# the first snapshot with structured outputs, which this harness requires.
GPT4O_20240806_OPENAI = RouteSpec(
    model="openai/gpt-4o-2024-08-06",
    revision="openai/gpt-4o-2024-08-06",
    route_provider="OpenAI",
    quantization="unknown",
    max_prompt_price_per_million="2.50",
    max_completion_price_per_million="10.00",
    pricing=TokenPricing(
        input_per_million=2.50,
        cached_input_per_million=1.25,
        output_per_million=10.00,
        pricing_id="openrouter_2026-09-10_gpt4o_20240806_openai",
    ),
    profile_suffix="gpt4o_20240806",
    output_schema_dialect="strict",
)

ROUTE = GLM53_FLASH_PARASAIL
MODEL = ROUTE.model
REVISION = ROUTE.revision
ROUTE_PROVIDER = ROUTE.route_provider
QUANTIZATION = ROUTE.quantization
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
    # "length" is back, now that the doubling is bounded (#131: capped at
    # 8x the declared budget and half the context window). It is needed:
    # the executor labels a response that is BOTH truncated and empty as
    # "length", and this model occasionally spends its whole output budget
    # on reasoning and emits nothing -- at 2,400, at 6,000 and again at
    # 12,000, since it expands to fill whatever it is given. Headroom does
    # not fix that; a retry does.
    "length",
    "empty_response",
    # A rejection that arrives after this route has already answered cannot
    # mean the route does not exist. Parasail returned a spurious 404 twice
    # during this family's first light, killing a panel mid-run each time. A
    # FIRST-call rejection is untyped by this and still fails fast.
    POST_ADMISSION_REJECTION,
)
MAX_PROMPT_PRICE_PER_MILLION = ROUTE.max_prompt_price_per_million
MAX_COMPLETION_PRICE_PER_MILLION = ROUTE.max_completion_price_per_million
PRICING = ROUTE.pricing

PROMPT_ID = "econevals_period_json_v1"
PROMPT = """You are running one period of an economic decision task. The observation
names the track, the read-only tools you may call, and the single submit tool that ends
the period. Return only the required JSON object: an ordered list of tool calls whose
LAST call is the submit tool. Use tool names exactly as given in the observation's
read_only_tools and submit_tool fields -- do not invent or abbreviate a name. Call
read-only tools first to gather what you need, then submit your decision for this
period. Never invent tool results.
"""


# The single declaration of the reasoning condition. It is a module constant
# rather than a literal inside ``build_live_setup`` because the campaign plan's
# route block and the admission canary both have to state the same condition,
# and when they were written out separately they drifted: the plan advertised
# ``reasoning_effort: "low"`` into published evidence while the panel executed
# with no effort and a 1,500-token cap, and the canary proved the route under
# "low" before the panel ran under something else. A route admitted under one
# reasoning condition does not attest a panel run under another.
#
# "minimal" was tried first and is not enough on its own. Attempt_013 sent
# ``reasoning_effort: "minimal"`` -- confirmed present in the sealed request,
# not assumed -- and the model still spent all 4,000 output tokens on reasoning
# and returned ``output_text=""`` with ``finish_reason="length"``. An effort is
# a hint the provider may honour; ``reasoning.max_tokens`` is a cap it must.
# Both cannot be declared together: OpenRouter returns 400 "Only one of
# \"reasoning.effort\" and \"reasoning.max_tokens\" can be specified" (#133),
# so the cap replaces the hint -- the right way round anyway, since the hint is
# the control that failed. 1,500 of 4,000 leaves 2,500 for the action itself,
# against a longest observed well-formed action burst under 400.
REASONING_DECLARATION: dict[str, object] = {
    # `reasoning.max_tokens: 1500` is declared because it works, and the
    # measurement is unambiguous. On `procurement.basic.0`, with the block
    # sent, the model produced a MEDIAN of 31 characters of reasoning and 100
    # of 100 calls finished `stop`. With no block sent -- same case, same
    # ceiling, same route -- the median is about 12,000 characters and the
    # case fails. Three consecutive attempts failed that case with the block
    # absent; no attempt has ever failed it with the block present.
    #
    # It is a suppressor, not a hard cap, and the distinction matters. The
    # same 1,500 declaration is present on every call of a
    # `scheduling.basic.1` failure whose reasoning still ran past 10,000
    # characters. Easy observations obey it by a wide margin; a hard one can
    # still overrun. That is why an earlier write-up here concluded the
    # control was "discarded" -- it was read off the one case that overruns,
    # and generalised to a route that mostly obeys it.
    #
    # An effort cannot be declared alongside it: OpenRouter 400s on the pair
    # (#133).
    "condition_id": "reasoning_capped_1500_v1",
    "effort": None,
    "token_budget": 1500,
    "rationale_visibility": "hidden",
}

REASONING_SUPPRESSED_V1 = REASONING_DECLARATION

# The other arm. Probed across families on this route (2026-09-10): a
# declared `reasoning.max_tokens` suppresses to ~13 reasoning tokens at ANY
# value -- 1,500 and 8,000 are indistinguishable -- and so does
# `reasoning.effort: "low"`; declaring no block yields ~260 on a short
# prompt. So the note above is right that this is a suppressor and not a
# cap, and the consequence is sharper than it reads: `panel_v10` measured a
# GLM 5.3 Flash that did not deliberate, and no number in it is a
# like-for-like against a paper whose agents reason freely.
#
# The unconstrained arm HAS been tried here and failed three times -- but at
# the 4,000-token ceiling below, which is the variable that makes the
# retry worth doing rather than a repeat. TERMS-Bench ran the same condition
# at 12,000 across 30 cases with no truncation and no malformed action.
REASONING_UNCONSTRAINED_V1: dict[str, object] = {
    "condition_id": "reasoning_unconstrained_v1",
    "effort": None,
    "token_budget": None,
    "rationale_visibility": "hidden",
}
MAX_OUTPUT_TOKENS_SUPPRESSED = 4000
MAX_OUTPUT_TOKENS_UNCONSTRAINED = 12000

def route_metadata(route: "RouteSpec" = None) -> dict[str, str]:
    """The exact sealed route the OpenRouter adapter requires -- these five
    fields and no others, or it refuses the call as a provider_contract
    failure."""
    route = route or ROUTE
    return {
        "route_provider": route.route_provider,
        "quantization": route.quantization,
        "canonical_model": route.revision,
        "max_prompt_price_per_million": route.max_prompt_price_per_million,
        "max_completion_price_per_million": route.max_completion_price_per_million,
    }


def _call_arguments(call: Mapping[str, Any], index: int) -> tuple[Mapping[str, Any] | None, str]:
    """The tool call's arguments, in either wire form.

    A permissive-dialect route sends `arguments` as an object. OpenAI's
    strict structured-output mode cannot express an open map -- every object
    must close and list every property -- so a strict-dialect route sends
    `arguments_json`, the same mapping JSON-encoded. The action space is
    identical; only the wire form differs, and which one a profile asked for
    is pinned in its `output_schema`.
    """
    arguments = call.get("arguments")
    if isinstance(arguments, Mapping):
        return arguments, ""
    encoded = call.get("arguments_json")
    if isinstance(encoded, str):
        try:
            decoded = json.loads(encoded)
        except json.JSONDecodeError:
            return None, f"call {index} has arguments_json that is not JSON"
        if not isinstance(decoded, Mapping):
            return None, f"call {index} needs arguments_json to encode an object"
        return decoded, ""
    return None, f"call {index} needs an arguments object"


def period_output_schema(dialect: str = "permissive") -> dict[str, Any]:
    if dialect == "strict":
        # OpenAI strict mode: every object closed, every property required,
        # so the open `arguments` map becomes a JSON-encoded string.
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
                            "arguments_json": {"type": "string"},
                        },
                        "required": ["id", "name", "arguments_json"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["calls"],
            "additionalProperties": False,
        }
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
            arguments, argument_error = _call_arguments(call, index)
            if not isinstance(call_id, str) or not call_id:
                return None, f"call {index} needs a non-empty string id"
            if not isinstance(name, str) or not name:
                return None, f"call {index} needs a tool name"
            if arguments is None:
                return None, argument_error
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

    @staticmethod
    def _validate_step(
        calls: Any, *, submit_tool: str
    ) -> tuple[tuple[dict[str, Any], ...] | None, bool, str]:
        """Validate one step's calls: read-only calls, or the terminating submit.

        Returns ``(normalized, submitted, reason)``. A step may issue any
        number of read-only calls, and may end with the submit call, which
        ends the period.

        The loop PERMITS multi-step exploration; it does not mandate it. An
        earlier version rejected a step that mixed read-only calls with the
        submit, which was stricter than ``parse_action`` -- the environment
        only requires the submit to be last. That extra rule fought the
        model: it wanted to gather and submit in one burst, was bounced with
        "look first, submit after", and in one period never converged within
        the round budget. What matters for fidelity is that results ARE fed
        back when the model splits its work, not that it is forced to.
        """
        if not isinstance(calls, list) or not calls:
            return None, False, "return a non-empty calls list"
        normalized: list[dict[str, Any]] = []
        submit_index: int | None = None
        for index, call in enumerate(calls):
            if not isinstance(call, Mapping):
                return None, False, f"call {index} must be an object"
            call_id = call.get("id")
            name = call.get("name")
            arguments, argument_error = _call_arguments(call, index)
            if not isinstance(call_id, str) or not call_id:
                return None, False, f"call {index} needs a non-empty string id"
            if not isinstance(name, str) or not name:
                return None, False, f"call {index} needs a tool name"
            if arguments is None:
                return None, False, argument_error
            if name == submit_tool:
                if submit_index is not None:
                    # Two submits in one step: the first would sit mid-list in
                    # the accumulated action and the environment would reject
                    # the whole period (submit_tool_must_be_the_final_call).
                    # Checking only the LAST occurrence let this through.
                    return None, False, (
                        f"call {submit_tool!r} exactly once, as the final call"
                    )
                submit_index = index
            normalized.append({"id": call_id, "name": name, "arguments": arguments})
        if submit_index is not None and submit_index != len(normalized) - 1:
            # The environment's own rule, and the only one worth enforcing
            # here: anything after the submit would never run.
            return None, False, (
                f"{submit_tool!r} ends the period, so it must be the last call"
            )
        return tuple(normalized), submit_index is not None, ""

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        """Run one period as an iterative tool loop, as upstream does.

        Upstream's own runner loops within a period
        (`run_procurement_experiment.py`: ``for i in range(max_queries)``),
        appending every tool result to the message list before the next call,
        so the agent SEES what it looked up before it decides. An earlier
        version of this harness took a single burst and executed it
        afterwards, which asked the model to submit blind to its own queries
        -- a strictly harder, differently shaped task, and the reason the
        first published panel scored gate=0.0 on five of six cases.

        The period ends when the model calls the track's submit tool. Every
        call across every step is accumulated into one action, read-only
        calls first and the submit last, which is the shape
        ``parse_action`` requires.
        """
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
        tool_calls: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        claimed: list[ClaimedToolCall] = []
        rounds_used = 0
        budget = max(1, ctx.budget.rounds_left)
        while rounds_used < budget:
            turn = await ctx.model.complete(
                messages=messages, response_mode="json_dialect"
            )
            rounds_used += 1
            if not (turn.text or "").strip():
                raise ProviderFailure(
                    "empty_response",
                    "econevals period returned an empty response",
                    retryable=True,
                )
            value, reason = self._decode(turn.text or "")
            step: tuple[dict[str, Any], ...] | None = None
            submitted = False
            if value is not None:
                step, submitted, reason = self._validate_step(
                    value.get("calls"), submit_tool=submit_tool
                )
            elif getattr(turn, "truncated", False):
                reason = (
                    "your previous response was cut off by the output limit; "
                    "return fewer, shorter calls in one complete JSON object"
                )
            if step is None:
                # Correctable: nothing in this step has been executed.
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
                continue
            if len(tool_calls) + len(step) > MAX_LLM_QUERIES_PER_PERIOD + 1:
                raise ProviderFailure(
                    "malformed_structured_output",
                    "econevals period exceeded its per-period query budget",
                    retryable=False,
                )

            results: list[dict[str, Any]] = []
            for offset, call in enumerate(step):
                envelope = await ctx.tools.invoke(
                    tool_id=call["name"],
                    arguments=call["arguments"],
                    source_provider_call_id=turn.provider_call_id,
                    source_call_index=offset,
                )
                plain_arguments = json.loads(canonical_json_bytes(call["arguments"]))
                plain_result = json.loads(canonical_json_bytes(envelope.result))
                tool_calls.append(
                    {
                        "id": call["id"],
                        "name": call["name"],
                        "arguments": plain_arguments,
                    }
                )
                executions.append(
                    {
                        "tool_call_id": call["id"],
                        "name": call["name"],
                        "arguments": plain_arguments,
                        "result": plain_result,
                        "invocation_record_id": (
                            envelope.invocation_record.tool_invocation_id
                        ),
                    }
                )
                claimed.append(
                    ClaimedToolCall(
                        tool_id=call["name"],
                        source_provider_call_id=turn.provider_call_id,
                        source_call_index=offset,
                    )
                )
                results.append(
                    {
                        "call_id": call["id"],
                        "name": call["name"],
                        "result": plain_result,
                    }
                )

            if submitted:
                self.session.advance_period(self.family_case)
                return HarnessOutput(
                    action={"tool_calls": tool_calls, "tool_executions": executions},
                    claimed_tool_calls=tuple(claimed),
                    rounds_used=rounds_used,
                    notes={},
                )
            # Feed the results back, which is the whole point of the loop.
            messages = messages + (
                CanonicalMessage(
                    role="user",
                    content=canonical_json_bytes(
                        {
                            "tool_results": results,
                            "reminder": (
                                f"call {submit_tool!r} on its own when you are "
                                "ready to end this period"
                            ),
                        }
                    ).decode("utf-8"),
                ),
            )
        raise ProviderFailure(
            "malformed_structured_output",
            f"econevals period did not submit within {rounds_used} steps",
            retryable=False,
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
    reasoning: Mapping[str, object] = REASONING_DECLARATION,
    max_output_tokens: int = MAX_OUTPUT_TOKENS_SUPPRESSED,
    route: "RouteSpec" = None,
) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            # The reasoning condition is part of the agent's identity.
            "profile_id": (
                "econevals_agent_glm53_flash_parasail_v1"
                if reasoning["condition_id"] == REASONING_SUPPRESSED_V1["condition_id"]
                and (route or ROUTE) is GLM53_FLASH_PARASAIL
                else f"econevals_agent_{(route or ROUTE).profile_suffix}_{reasoning['condition_id']}"
            ),
            "model": {
                "provider": PROVIDER,
                "model": (route or ROUTE).model,
                "revision": (route or ROUTE).revision,
                "base_url": "https://openrouter.ai/api/v1",
            },
            "harness": {
                "id": EconevalsJsonHarness.id,
                "version": EconevalsJsonHarness.version,
                "config": {
                    "pricing_id": (route or ROUTE).pricing.pricing_id,
                    "pricing_sha256": (route or ROUTE).pricing.content_sha256(),
                    "output_schema": period_output_schema((route or ROUTE).output_schema_dialect),
                    "max_rounds": 12,
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
                    "provider_metadata": route_metadata(route),
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
            "reasoning": dict(reasoning),
            "sampling": {
                "temperature": 0.0,
                # This budget covers REASONING plus the answer, not the
                # answer alone. GLM 5.3 Flash at low effort spent all 2,400
                # on reasoning and returned output_text="" with
                # finish_reason="length", ten attempts running, which reached
                # the environment as a null action (response_not_object) and
                # failed the case. 900 truncated a burst mid-JSON before
                # that. 6,000 leaves room for the thinking and a full
                # Normal calls finish at ~2,600 output tokens. Over-
                # provisioning does not help -- the model expanded to fill
                # 6,000 and then 12,000 and still emitted nothing on the
                # occasional deep-reasoning turn -- so the budget is modest
                # and truncation is handled by a bounded length retry
                # instead (#131).
                # 4,000, and the ceiling is no longer being treated as
                # a lever. Four values have now been run live -- 4,000, 6,000,
                # 12,000 and 24,000 -- and the failure survives all of them.
                #
                # 24,000 was sized from the calls that succeeded, which needed
                # 4,521-7,070 tokens. That reasoning was sound about the
                # successes and wrong about the failures, because the failures
                # scale with the ceiling too: at 24,000, ten of twenty-four
                # calls filled the entire budget and returned empty. The run
                # reached period 5 of 100 in an hour at $0.147, which
                # extrapolates past both the per-trajectory cap and any
                # tolerable wall time, and was stopped.
                #
                # So the v1 note was right and my two attempts to overturn it
                # were not: a large share of calls expand into whatever budget
                # they are given. Raising the ceiling buys a few more
                # successes and makes every failure proportionally more
                # expensive. 4,000 is kept because it is the cheapest way to
                # fail, not because it works.
                "max_output_tokens": max_output_tokens,
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
    reasoning: Mapping[str, object] = REASONING_DECLARATION,
    max_output_tokens: int = MAX_OUTPUT_TOKENS_SUPPRESSED,
    route: "RouteSpec" = None,
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
        route=route,
        reasoning=reasoning,
        max_output_tokens=max_output_tokens,
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
        pricing={(route or ROUTE).model: (route or ROUTE).pricing},
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
