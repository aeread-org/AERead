"""Model-call harness ports: the only doors a harness has onto the world.

A harness never touches a provider client, a `ToolRuntime`, or the evidence
store directly.  It reaches the world through two brokered ports —
`ModelPort` and `ToolPort` — aggregated on an `AttemptContext`.  This module
defines the port protocols, the harness protocol they serve, and their
kernel-side implementations: `KernelModelPort` builds each `ProviderRequest`
from the profile, seals every provider call, and rejects an empty completion
before a harness ever sees it; `KernelToolPort` mints tool-invocation
identity deterministically from `(attempt_id, source_provider_call_id,
source_call_index)`, disposes an undeclared or over-budget dispatch as a
typed rejection before `ToolRuntime` ever sees it, and turns a bookkeeping
failure after a real tool effect into `outcome_unknown` evidence rather than
losing the effect's own exception.
"""
from __future__ import annotations

import asyncio
import json

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Protocol

from ..task.execution import (
    CanonicalResponse,
    EvidenceIntegrityError,
    EvidenceStore,
    ProviderClient,
    ProviderFailure,
    ProviderRequest,
    MinimalChatExecutor,
    ModelRound,
    PendingRound,
    ProviderResult,
    TokenPricing,
    ToolFailure,
    ToolInvocationRecord,
    _stable_id,
)
from ..registry import HarnessRequirements, ProviderCapabilities
from ..run.resolver import canonical_json_bytes
from ..schemas import AgentProfile
from ..task.tools import ToolContractError, ToolRuntime


# --- The native model protocol's data shapes (§6; wire fields land in stage 2) ---


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSchema:
    tool_id: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NativeToolCall:
    call_id: str
    tool_id: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """A model's reply: text, or an ordered tuple of tool calls — never both,
    never neither.  An empty result never reaches this far (§3 invariant 1);
    `ModelPort.complete` rejects it before constructing a `ModelTurn`."""

    text: str | None
    tool_calls: tuple[NativeToolCall, ...] = ()
    provider_call_id: str = ""
    """The kernel id of the provider call that produced this turn.

    A harness needs it to correlate a tool call back to the model output that
    requested it (`ToolPort.invoke(source_provider_call_id=...)`, §5.2), and it
    arrives through the port so a harness never reaches around it into the
    provider client to recover the id."""

    def __post_init__(self) -> None:
        if (self.text is not None) == bool(self.tool_calls):
            raise EvidenceIntegrityError(
                "ModelTurn must carry exactly one of text or tool_calls"
            )


class ModelPort(Protocol):
    async def complete(
        self,
        *,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSchema, ...] = (),
        response_mode: Literal["native_tools", "json_dialect", "text"],
        max_output_tokens: int | None = None,
    ) -> ModelTurn: ...


# --- The tool port (§5.2) ---


@dataclass(frozen=True, slots=True)
class ToolExecutionEnvelope:
    result: Any
    invocation_record: ToolInvocationRecord
    family_reconciliation: Mapping[str, Any]


class ToolPort(Protocol):
    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
        source_provider_call_id: str,
        source_call_index: int,
    ) -> ToolExecutionEnvelope: ...


# --- The attempt aggregate (§5.2) ---


@dataclass(frozen=True, slots=True)
class BudgetView:
    """Deterministic counters only — no live deadline, which would break
    replay (§9); the runtime enforces any wall-clock timeout externally."""

    rounds_left: int
    tokens_left: int | None
    cost_left: float | None

    def __post_init__(self) -> None:
        if self.rounds_left < 0:
            raise EvidenceIntegrityError("BudgetView.rounds_left cannot be negative")
        if self.tokens_left is not None and self.tokens_left < 0:
            raise EvidenceIntegrityError("BudgetView.tokens_left cannot be negative")
        if self.cost_left is not None and self.cost_left < 0:
            raise EvidenceIntegrityError("BudgetView.cost_left cannot be negative")


class AttemptContext(Protocol):
    attempt_id: str
    seed: int
    budget: BudgetView
    model: ModelPort
    tools: ToolPort | None
    subagents: Any | None  # SubagentPort, admitted only for a nested spec (§13.E, stage 11)

    def note(self, kind: str, payload: Mapping[str, Any]) -> None: ...


# --- The harness protocol (§5.1) ---


@dataclass(frozen=True, slots=True)
class ClaimedToolCall:
    tool_id: str
    source_provider_call_id: str
    source_call_index: int


@dataclass(frozen=True, slots=True)
class HarnessOutput:
    action: Mapping[str, Any]
    claimed_tool_calls: tuple[ClaimedToolCall, ...]
    rounds_used: int
    notes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FailureCondition:
    condition: str
    retryable: bool


class Harness(Protocol):
    id: str
    version: str
    requires: HarnessRequirements

    async def open_episode(self, episode: Any) -> None: ...
    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput: ...
    async def close_episode(self, episode: Any) -> None: ...
    def classify_failure(self, exc: BaseException) -> FailureCondition: ...
    def state_reader(self) -> Any: ...  # only if requires.memory != {"disabled"} (§10)


# --- The kernel-side ModelPort (§5.2, §3 invariant 1) ---


class KernelModelPort:
    """Builds each `ProviderRequest` from the profile, mints and seals the
    provider call, and rejects an empty completion as a typed failure before
    any harness constructs a `ModelTurn` from it.  The harness may only
    *lower* `max_output_tokens`; it may never widen it or touch sampling."""

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        provider: ProviderClient,
        pricing: TokenPricing,
        profile: AgentProfile,
        instructions: str,
        action_attempt_id: str,
        emit_events: bool = True,
        sealed_request: ProviderRequest | None = None,
        phase_instance_id: str | None = None,
        logical_action_id: str | None = None,
        visibility: str = "evaluator_only",
    ) -> None:
        self._evidence = evidence
        self._provider = provider
        self._pricing = pricing
        self._profile = profile
        self._instructions = instructions
        self._action_attempt_id = action_attempt_id
        self._phase_instance_id = phase_instance_id
        self._logical_action_id = logical_action_id
        self._visibility = visibility
        self._emit_events = emit_events
        self._sealed_request = sealed_request
        self._round = 0
        self.tool_calls_dispatched = 0
        """How many tool calls this port actually returned to the harness.

        The kernel's own count, used to reconcile the harness's claim: the
        harness reports what it believes it did, the kernel knows what it
        recorded, and a divergence is evidence rather than an exception."""
        self.last_result: ProviderResult | None = None
        self.rounds: list[ModelRound] = []
        """Every completed provider call, in order. All of them were billed."""
        self.pending_round: PendingRound | None = None
        """The call in flight, or the one that just failed, until the next round."""

    @property
    def cost_usd_total(self) -> float:
        return sum(entry.cost_usd for entry in self.rounds)

    async def complete(
        self,
        *,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSchema, ...] = (),
        response_mode: Literal["native_tools", "json_dialect", "text"],
        max_output_tokens: int | None = None,
    ) -> ModelTurn:
        ceiling = self._profile.sampling.max_output_tokens
        if max_output_tokens is not None and max_output_tokens > ceiling:
            raise EvidenceIntegrityError(
                "a harness may only lower max_output_tokens, never raise it"
            )
        effective_max_output_tokens = ceiling if max_output_tokens is None else max_output_tokens

        round_ordinal = self._round
        self._round += 1

        if self._sealed_request is not None and round_ordinal == 0:
            # The executor already sealed this request and emitted
            # provider_call_started for it.  Building a second one here would
            # send bytes the evidence never recorded, so replay would replay a
            # call that was never made.  Reuse the sealed request verbatim.
            request = self._sealed_request
            provider_call_id = request.provider_call_id
        else:
            provider_call_id = _stable_id(
                "provider_call",
                {"action_attempt_id": self._action_attempt_id, "round": round_ordinal},
            )
            input_text = canonical_json_bytes(
                {"messages": messages, "tools": tools, "response_mode": response_mode}
            ).decode("utf-8")
            request = ProviderRequest(
                provider_call_id=provider_call_id,
                provider=self._profile.model.provider,
                base_url=self._profile.model.base_url,
                model=self._profile.model.model,
                revision=self._profile.model.revision,
                instructions=self._instructions,
                input_text=input_text,
                temperature=_sampling_value(self._profile, "temperature"),
                top_p=_sampling_value(self._profile, "top_p"),
                max_output_tokens=effective_max_output_tokens,
                reasoning_effort=self._profile.reasoning.effort,
                reasoning_token_budget=self._profile.reasoning.token_budget,
                timeout_seconds=self._profile.budgets.timeout_seconds,
                request_sha256="",
                max_cost_usd=self._profile.budgets.max_cost_usd,
                output_schema=self._profile.harness.config.get("output_schema"),
                provider_metadata=self._profile.harness.config.get("provider_metadata"),
                seed=self._profile.sampling.seed,
                messages=messages if response_mode == "native_tools" else None,
                tools=tools if response_mode == "native_tools" and tools else None,
            ).with_computed_hash()

        # With emit_events=False the executor sealed round 0 and already wrote
        # its provider_call_started; the port owns every later round's opening
        # event and every round's terminal event, so no billed call is missing
        # from evidence.
        owns_opening = self._emit_events or round_ordinal > 0
        if owns_opening:
            self._evidence.append_event(
                "provider_call_started",
                {"request": request, "round": round_ordinal},
                phase_instance_id=self._phase_instance_id,
                logical_action_id=self._logical_action_id,
                action_attempt_id=self._action_attempt_id,
                provider_call_id=provider_call_id,
                visibility=self._visibility,
            )
        self.pending_round = PendingRound(
            round=round_ordinal,
            provider_call_id=provider_call_id,
            request=request,
            terminalized=False,
        )
        try:
            result = await self._provider.complete(request)
        except ProviderFailure as failure:
            outcome_unknown = failure.condition in {"timeout", "transport"}
            self._evidence.append_event(
                "provider_call_outcome_unknown" if outcome_unknown else "provider_call_failed",
                {
                    "failure_condition": failure.condition,
                    "message": str(failure),
                    "retryable": failure.retryable,
                    "status_code": failure.status_code,
                    "cost_usd": "unknown" if outcome_unknown else 0.0,
                    "round": round_ordinal,
                },
                phase_instance_id=self._phase_instance_id,
                logical_action_id=self._logical_action_id,
                action_attempt_id=self._action_attempt_id,
                provider_call_id=provider_call_id,
                visibility=self._visibility,
            )
            self.pending_round = PendingRound(
                round=round_ordinal,
                provider_call_id=provider_call_id,
                request=request,
                terminalized=True,
            )
            raise
        if not isinstance(result, ProviderResult):
            raise ProviderFailure(
                "provider_contract",
                "provider client did not return ProviderResult",
                retryable=False,
            )
        cost = (
            result.cost_usd
            if result.cost_usd is not None
            else self._pricing.cost(
                input_tokens=result.input_tokens,
                cached_input_tokens=result.cached_input_tokens,
                output_tokens=result.output_tokens,
            )
        )
        self._evidence.append_event(
            "provider_call_succeeded",
            {
                # The full raw_response is sealed as part of this artifact.
                "provider_result": result,
                "request_sha256": request.request_sha256,
                "pricing_id": self._pricing.pricing_id,
                "cost_usd": cost,
                "round": round_ordinal,
            },
            phase_instance_id=self._phase_instance_id,
            logical_action_id=self._logical_action_id,
            action_attempt_id=self._action_attempt_id,
            provider_call_id=provider_call_id,
            visibility=self._visibility,
        )
        self.pending_round = None
        self.rounds.append(
            ModelRound(
                round=round_ordinal,
                provider_call_id=provider_call_id,
                request=request,
                result=result,
                cost_usd=cost,
            )
        )
        self.last_result = result
        tool_calls = result.tool_calls or ()
        text = result.output_text.strip()
        if not text and not tool_calls:
            raise ProviderFailure(
                # "empty_response" is the condition name the kernel's retry
                # policy already matches (execution.py, retry_condition).  A
                # new name here would silently stop retrying for every profile
                # that declares the existing one in retryable_conditions.
                "empty_response",
                f"provider call {provider_call_id} returned an empty completion",
                retryable=True,
            )
        if text and tool_calls:
            # §6: a turn is text XOR calls. Both would leave the harness to
            # guess which the model meant, and the guess would be silent.
            raise ProviderFailure(
                "provider_contract",
                f"provider call {provider_call_id} returned both text and tool "
                "calls; a model turn must be one or the other",
                retryable=False,
            )
        self.tool_calls_dispatched += len(tool_calls)
        return ModelTurn(
            text=result.output_text if text else None,
            tool_calls=tool_calls,
            provider_call_id=provider_call_id,
        )


# --- The kernel-side ToolPort (§5.2) ---


class KernelToolPort:
    """Mints `tool_invocation_id` from `(attempt_id, source_provider_call_id,
    source_call_index)` so replay recomputes the identical id, emits
    `tool_dispatch_intended` for every call in source order, and disposes an
    undeclared tool or one past `max_invocations` as a typed
    `tool_dispatch_rejected` before `ToolRuntime` ever sees it — one terminal
    disposition per intent, never an orphaned invocation."""

    def __init__(
        self,
        *,
        runtime: ToolRuntime,
        attempt_id: str,
        action_attempt_id: str,
        max_invocations: int | None = None,
        granted_tools: frozenset[str] | None = None,
        family_reconciliation: (
            Callable[[str, Any, ToolInvocationRecord], Mapping[str, Any]] | None
        ) = None,
    ) -> None:
        self._runtime = runtime
        self._attempt_id = attempt_id
        self._action_attempt_id = action_attempt_id
        self._max_invocations = max_invocations
        # The family runtime may declare more tools than one profile is
        # granted; None means the port imposes no grant beyond the runtime's
        # declared set (direct family/test constructions), while the kernel
        # wiring passes the profile's declared tool ids.
        self._granted_tools = granted_tools
        self._family_reconciliation = family_reconciliation
        self._invocations = 0
        self.invocation_ids: list[str] = []
        """Every invocation this port recorded, in dispatch order.

        The attempt record needs them: without it a CanonicalResponse claims
        zero tool calls while the evidence stream shows two, and the two
        accounts of the same attempt disagree."""

    async def invoke(
        self,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
        source_provider_call_id: str,
        source_call_index: int,
    ) -> ToolExecutionEnvelope:
        tool_invocation_id = _stable_id(
            "tool_invocation",
            {
                "attempt_id": self._attempt_id,
                "source_provider_call_id": source_provider_call_id,
                "source_call_index": source_call_index,
            },
        )
        evidence = self._runtime.evidence
        evidence.append_event(
            "tool_dispatch_intended",
            {
                "tool_id": tool_id,
                "source_provider_call_id": source_provider_call_id,
                "source_call_index": source_call_index,
            },
            action_attempt_id=self._action_attempt_id,
            tool_invocation_id=tool_invocation_id,
        )

        try:
            self._runtime.definition(tool_id)
            declared = True
        except ToolContractError:
            declared = False
        granted = self._granted_tools is None or tool_id in self._granted_tools
        over_budget = (
            self._max_invocations is not None
            and self._invocations >= self._max_invocations
        )
        if not declared or not granted or over_budget:
            if not declared:
                rejection_condition = "undeclared_tool"
            elif not granted:
                rejection_condition = "tool_not_granted"
            else:
                rejection_condition = "tool_budget_exceeded"
            evidence.append_event(
                "tool_dispatch_rejected",
                {
                    "tool_id": tool_id,
                    "source_provider_call_id": source_provider_call_id,
                    "source_call_index": source_call_index,
                    "failure_condition": rejection_condition,
                },
                action_attempt_id=self._action_attempt_id,
                tool_invocation_id=tool_invocation_id,
            )
            raise ToolFailure(
                rejection_condition,
                f"tool dispatch rejected for {tool_id!r}: {rejection_condition}",
                retryable=False,
            )

        self._invocations += 1
        result, record = await self._runtime.invoke(
            action_attempt_id=self._action_attempt_id,
            tool_id=tool_id,
            arguments=arguments,
            tool_invocation_id=tool_invocation_id,
        )
        reconciliation = (
            {}
            if self._family_reconciliation is None
            else self._family_reconciliation(tool_id, result, record)
        )
        self.invocation_ids.append(tool_invocation_id)
        return ToolExecutionEnvelope(
            result=result,
            invocation_record=record,
            family_reconciliation=reconciliation,
        )




def _rounds_budget(profile: AgentProfile) -> int:
    """How many model calls one attempt may make.

    A single-call harness needs exactly one; a tool loop needs at least three
    (ask, feed results back, reply), so hardcoding 1 meant a tool-using attempt
    could never finish through the executor -- it always hit rounds_exhausted
    on the round that fed the results back. The ceiling is declared per profile
    in `harness.config.max_rounds`, the same place output_schema and
    sampling_controls are declared, and defaults to 1 so an undeclared profile
    keeps exactly today's single-call behaviour.
    """

    declared = profile.harness.config.get("max_rounds")
    if declared is None:
        return 1
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        raise EvidenceIntegrityError(
            f"harness.config.max_rounds must be a positive integer, got {declared!r}"
        )
    return declared


def _sampling_value(profile: AgentProfile, control: str) -> float | None:
    """The sampling value to send, or None when the harness cannot apply it.

    A profile may declare `harness.config.sampling_controls.<control> =
    "unavailable"` for a runtime that cannot honour it -- the Claude Code CLI
    accepts no temperature, for instance.  Sending a value the harness silently
    ignores would record a control the run never actually applied.
    """

    controls = profile.harness.config.get("sampling_controls")
    if isinstance(controls, Mapping) and controls.get(control) == "unavailable":
        return None
    return getattr(profile.sampling, control)


class _KernelAttemptContext:
    """The `AttemptContext` a harness receives for one action attempt.

    It is a thin aggregate over the ports (§5.2): it owns no policy of its own,
    so a harness cannot acquire capability by reaching past it -- `tools` is
    `None` unless the profile declared tools, and `subagents` stays `None`
    until nested agents are admitted (§13.E, a later stage).
    """

    __slots__ = ("attempt_id", "seed", "budget", "model", "tools", "subagents", "_evidence")

    def __init__(
        self,
        *,
        attempt_id: str,
        seed: int,
        budget: BudgetView,
        model: ModelPort,
        tools: ToolPort | None,
        evidence: EvidenceStore,
    ) -> None:
        self.attempt_id = attempt_id
        self.seed = seed
        self.budget = budget
        self.model = model
        self.tools = tools
        self.subagents = None
        self._evidence = evidence

    def note(self, kind: str, payload: Mapping[str, Any]) -> None:
        """Record a harness-private diagnostic.

        Namespaced so harness notes can never be mistaken for kernel evidence.
        """

        self._evidence.append_event(
            "harness_note",
            {"kind": kind, "payload": payload},
            action_attempt_id=self.attempt_id,
        )


class MinimalChatHarness:
    """`minimal_chat/1.0` expressed as a `Harness` over the ports.

    Exactly one model call, no tools, no memory -- the guarantee existing
    receipts already depend on.  It is the only harness `default_harnesses`
    registers, so a run never acquires tool capability by default.
    """

    id = "minimal_chat"
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

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        turn = await ctx.model.complete(
            messages=(CanonicalMessage(role="user", content=_request_input_text(request)),),
            response_mode="text",
        )
        return HarnessOutput(
            action=None,
            claimed_tool_calls=(),
            rounds_used=1,
            notes={},
        )


def _request_input_text(request: Any) -> str:
    """Render a DecisionRequest the way the kernel has always rendered it."""

    return canonical_json_bytes(
        {
            "phase_id": request.phase_id,
            "seat_id": request.seat_id,
            "role": request.role,
            "observation_schema": request.observation_schema,
            "action_schema": request.action_schema,
            "observation": request.observation,
        }
    ).decode("utf-8")


def default_harnesses() -> dict[str, Any]:
    """The harnesses the kernel registers when a caller supplies none.

    Only `minimal_chat/1.0`: it is the one harness whose guarantee (a single
    call, no tools, no memory) existing receipts depend on.  Tool-using
    harnesses must be registered explicitly, so a run can never acquire tool
    capability by default.
    """

    return {"minimal_chat/1.0": MinimalChatHarness()}


# --- native_tool_chat/1.0: native messages, plural tool calls (§6, §8) ---


@dataclass(frozen=True, slots=True)
class _MalformedRound:
    """A round whose decoded turn matched neither of the codec's two legal
    shapes -- typed and counted (§6), never an exception.  A singular
    `{"kind":"tool_call", ...}` object is the motivating case for
    `json_dialect/1.0`: the model's own malformed output must not raise the
    way a genuine provider or tool contract violation does."""

    raw_text: str
    reason: str


class _TurnCodec(Protocol):
    """What a turn codec owns at the wire boundary the shared engine drives:
    which `response_mode` it asks the model for, how the model's raw turn
    decodes into a `ModelTurn` (or a typed `_MalformedRound`), and how a
    dispatched tool's result becomes the next turn's message.  Everything
    else in the loop -- grouped dispatch in source order, the feedback turn,
    the round budget -- is common and lives once in `_run_tool_loop`;
    `json_dialect/1.0` reuses it with a codec of its own rather than a
    second loop.
    """

    response_mode: Literal["native_tools", "json_dialect"]

    def decode(self, turn: ModelTurn) -> "ModelTurn | _MalformedRound": ...

    def tool_result_message(
        self, *, call: NativeToolCall, envelope: ToolExecutionEnvelope
    ) -> CanonicalMessage: ...


@dataclass(frozen=True, slots=True)
class _NativeToolCodec:
    """The wire dialect a native-tool-calling provider already speaks: the
    port has already split `text` from `tool_calls` from the provider's own
    structured fields, so `decode` is the identity; a tool's result becomes a
    `role="tool"` message keyed by the model's own `call_id`, so the model
    can match the reply to the call it made."""

    response_mode: Literal["native_tools", "json_dialect"] = "native_tools"

    def decode(self, turn: ModelTurn) -> "ModelTurn | _MalformedRound":
        return turn

    def tool_result_message(
        self, *, call: NativeToolCall, envelope: ToolExecutionEnvelope
    ) -> CanonicalMessage:
        return CanonicalMessage(
            role="tool",
            content=canonical_json_bytes(envelope.result).decode("utf-8"),
            tool_call_id=call.call_id,
        )


@dataclass(frozen=True, slots=True)
class _JsonDialectCodec:
    """The wire dialect for a provider with no native tool-calling: the model
    is asked (via `output_schema`) for ONE object, plural by construction --
    `{"kind":"tool_calls","calls":[{"id":...,"name":...,"arguments":{...}},
    ...]}` or `{"kind":"reply","text":"..."}`.  `KernelModelPort` always hands
    this codec a turn carrying the raw JSON as `text` (the provider adapter
    never populates its native `tool_calls` field for this response mode), so
    `decode` is where the plural shape actually becomes a `ModelTurn`'s text
    XOR calls -- or, for anything else (a singular `{"kind":"tool_call",
    ...}` included), a typed `_MalformedRound` rather than a guess."""

    response_mode: Literal["native_tools", "json_dialect"] = "json_dialect"

    def decode(self, turn: ModelTurn) -> "ModelTurn | _MalformedRound":
        raw_text = turn.text or ""
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return _MalformedRound(raw_text=raw_text, reason="invalid_json")
        if not isinstance(payload, Mapping):
            return _MalformedRound(raw_text=raw_text, reason="not_an_object")

        kind = payload.get("kind")
        if kind == "reply":
            text = payload.get("text")
            if not isinstance(text, str):
                return _MalformedRound(raw_text=raw_text, reason="reply_missing_text")
            return ModelTurn(text=text, tool_calls=(), provider_call_id=turn.provider_call_id)

        if kind == "tool_calls":
            calls = payload.get("calls")
            if not isinstance(calls, list) or not calls:
                return _MalformedRound(raw_text=raw_text, reason="tool_calls_missing_calls")
            decoded_calls: list[NativeToolCall] = []
            for entry in calls:
                if not isinstance(entry, Mapping):
                    return _MalformedRound(raw_text=raw_text, reason="tool_call_entry_not_an_object")
                call_id, tool_id, arguments = entry.get("id"), entry.get("name"), entry.get("arguments")
                if (
                    not isinstance(call_id, str)
                    or not isinstance(tool_id, str)
                    or not isinstance(arguments, Mapping)
                ):
                    return _MalformedRound(raw_text=raw_text, reason="tool_call_entry_malformed")
                decoded_calls.append(
                    NativeToolCall(call_id=call_id, tool_id=tool_id, arguments=arguments)
                )
            return ModelTurn(
                text=None,
                tool_calls=tuple(decoded_calls),
                provider_call_id=turn.provider_call_id,
            )

        # Every other shape -- a singular `{"kind":"tool_call", ...}` among
        # them -- is malformed by construction: §6 asks for the plural shape
        # ONLY, so there is no legal singular form to fall back to.
        return _MalformedRound(raw_text=raw_text, reason=f"unknown_kind:{kind!r}")

    def tool_result_message(
        self, *, call: NativeToolCall, envelope: ToolExecutionEnvelope
    ) -> CanonicalMessage:
        return CanonicalMessage(
            role="user",
            content=canonical_json_bytes(
                {"call_id": call.call_id, "result": envelope.result}
            ).decode("utf-8"),
        )


async def _run_tool_loop(request: Any, ctx: AttemptContext, *, codec: _TurnCodec) -> HarnessOutput:
    """The tool loop every turn codec shares (§6, §8): the calls of one model
    turn are dispatched together, in source order, under that turn's own
    `provider_call_id` -- one grouped environment hop, matching upstream
    tau2 -- the grouped results are fed back as the next turn's messages, and
    the loop stops at text or at the round budget.  Splitting a turn's calls
    across more than one hop would change `upstream_step_count` and, near
    `max_steps`, the score -- so this grouping is the one thing a codec may
    never touch.
    """

    messages: tuple[CanonicalMessage, ...] = (
        CanonicalMessage(role="user", content=_request_input_text(request)),
    )
    claimed: list[ClaimedToolCall] = []
    tool_executions: list[Mapping[str, Any]] = []
    rounds_used = 0

    while True:
        if rounds_used >= ctx.budget.rounds_left:
            raise ProviderFailure(
                "rounds_exhausted",
                f"the tool loop exceeded its round budget of {ctx.budget.rounds_left}",
                retryable=False,
            )
        turn = await ctx.model.complete(
            messages=messages, tools=(), response_mode=codec.response_mode
        )
        rounds_used += 1

        decoded = codec.decode(turn)
        if isinstance(decoded, _MalformedRound):
            # Typed and counted, never raised: the model's own malformed
            # output must not crash the attempt the way a genuine provider or
            # tool contract violation does (§6).  The loop stops here rather
            # than guessing a repair -- there is no legal singular fallback.
            ctx.note(
                "malformed_round",
                {"round": rounds_used - 1, "raw_text": decoded.raw_text, "reason": decoded.reason},
            )
            return HarnessOutput(
                action={"messages": list(messages), "tool_executions": tool_executions},
                claimed_tool_calls=tuple(claimed),
                rounds_used=rounds_used,
                notes={"malformed_rounds": 1},
            )
        turn = decoded

        if turn.text is not None:
            messages = messages + (CanonicalMessage(role="assistant", content=turn.text),)
            return HarnessOutput(
                action={"messages": list(messages), "tool_executions": tool_executions},
                claimed_tool_calls=tuple(claimed),
                rounds_used=rounds_used,
                notes={},
            )

        if ctx.tools is None:
            raise ToolFailure(
                "tools_not_admitted",
                "the model requested tool calls but no ToolPort was granted",
                retryable=False,
            )

        feedback: list[CanonicalMessage] = []
        for index, call in enumerate(turn.tool_calls):
            envelope = await ctx.tools.invoke(
                tool_id=call.tool_id,
                arguments=call.arguments,
                source_provider_call_id=turn.provider_call_id,
                source_call_index=index,
            )
            claimed.append(
                ClaimedToolCall(
                    tool_id=call.tool_id,
                    source_provider_call_id=turn.provider_call_id,
                    source_call_index=index,
                )
            )
            tool_executions.append(dict(envelope.family_reconciliation))
            feedback.append(codec.tool_result_message(call=call, envelope=envelope))
        messages = messages + tuple(feedback)


class NativeToolChatHarness:
    """`native_tool_chat/1.0`: native messages, plural tool calls in one turn
    (§6).  It is the only harness whose reported claim is comparable to
    upstream tau2 -- every other tool-calling dialect must be labeled
    non-comparable.  `act` is a thin wrapper over the shared `_run_tool_loop`
    engine, coded with `_NativeToolCodec`.
    """

    id = "native_tool_chat"
    version = "1.0"
    requires = HarnessRequirements(
        provider=frozenset({"native_tools"}),
        tools="declared",
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
        if isinstance(exc, (ProviderFailure, ToolFailure)):
            return FailureCondition(exc.condition, retryable=exc.retryable)
        return FailureCondition("harness_error", retryable=False)

    def state_reader(self) -> Any:
        return None

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        return await _run_tool_loop(request, ctx, codec=_NativeToolCodec())


class JsonDialectHarness:
    """`json_dialect/1.0`: a single plural JSON object via `output_schema`
    (§6), for a provider with `structured_output` but no native tool-calling.
    It is a labeled non-comparable fallback -- only `native_tool_chat/1.0`
    may claim "same setup as upstream" -- and is a thin wrapper over the same
    shared `_run_tool_loop` engine, coded with `_JsonDialectCodec` rather than
    a second loop.
    """

    id = "json_dialect"
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

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        return await _run_tool_loop(request, ctx, codec=_JsonDialectCodec())


class AttemptExecutor(MinimalChatExecutor):
    """Runs each action attempt through a registered `Harness` (§5.1).

    It inherits the attempt lifecycle -- budgets, retries, the event order that
    existing receipts depend on, and the scheduler's duck-typed callbacks --
    and substitutes only what the harness owns: the model loop.  Subclassing
    rather than reimplementing keeps one lifecycle in the kernel; a second copy
    would drift from it silently.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        profiles: Any,
        prompt_sources: Mapping[str, str | bytes],
        providers: Mapping[str, ProviderClient],
        pricing: Mapping[str, TokenPricing],
        harnesses: Mapping[str, Any],
        tool_runtimes: Mapping[str, ToolRuntime] | None = None,
        request_seed_by_profile: Mapping[str, int] | None = None,
    ) -> None:
        self._harnesses = dict(harnesses)
        self._tool_runtimes = dict(tool_runtimes) if tool_runtimes else {}
        self._ports: dict[str, KernelModelPort] = {}
        self._pending_actions: dict[str, Mapping[str, Any] | None] = {}
        self._pending_tool_ids: dict[str, tuple[str, ...]] = {}
        super().__init__(
            evidence=evidence,
            profiles=profiles,
            prompt_sources=prompt_sources,
            providers=providers,
            pricing=pricing,
            request_seed_by_profile=request_seed_by_profile,
        )

    @staticmethod
    def _harness_key(profile: AgentProfile) -> str:
        return f"{profile.harness.id}/{profile.harness.version}"

    def _validate_profile(
        self, profile: AgentProfile, prompt_sources: Mapping[str, str | bytes]
    ) -> None:
        key = self._harness_key(profile)
        if key not in self._harnesses:
            raise EvidenceIntegrityError(f"no harness registered for {key!r}")
        super()._validate_profile(profile, prompt_sources)

    def _validate_harness_profile(self, profile: AgentProfile) -> None:
        """Validate the profile against the harness it actually names.

        The base class checks minimal_chat/1.0's own guarantees; inheriting
        those unchanged meant a tool-using profile was refused as "not
        minimal_chat/1.0" and no tool harness could reach production. Each
        harness declares what it accepts, so check against that instead.
        """

        harness = self._harnesses[self._harness_key(profile)]
        requires = harness.requires
        if profile.tools and requires.tools == "none":
            raise EvidenceIntegrityError(
                f"harness {self._harness_key(profile)!r} does not permit tools"
            )
        if profile.memory.mode not in requires.memory:
            raise EvidenceIntegrityError(
                f"harness {self._harness_key(profile)!r} does not permit memory "
                f"mode {profile.memory.mode!r}"
            )

    def _attempt_rounds(self, action_attempt_id: str) -> tuple[ModelRound, ...]:
        port = self._ports.get(action_attempt_id)
        return tuple(port.rounds) if port is not None else ()

    def _attempt_pending_round(self, action_attempt_id: str) -> PendingRound | None:
        port = self._ports.get(action_attempt_id)
        return port.pending_round if port is not None else None

    async def _obtain_result(
        self,
        *,
        provider: ProviderClient,
        request: ProviderRequest,
        profile: AgentProfile,
        decision: Any,
        action_attempt_id: str,
    ) -> ProviderResult:
        """Drive the registered harness through a brokered `ModelPort`.

        The port owns the provider call: it seals the request, rejects an empty
        completion as a typed failure before the harness sees it (§3 invariant
        1), and terminalizes every call.  The harness only decides what to ask.
        """

        harness = self._harnesses[self._harness_key(profile)]
        port = KernelModelPort(
            evidence=self.evidence,
            provider=provider,
            pricing=self._pricing[profile.model.model],
            profile=profile,
            instructions=self._prompt_text[profile.profile_id],
            action_attempt_id=request.provider_call_id,
            emit_events=False,
            sealed_request=request,
        )
        self._ports[action_attempt_id] = port
        tools_port: Any = None
        if profile.tools and harness.requires.tools != "none":
            # A live port is only ever handed to a harness whose profile
            # actually declared tools -- the guarantee
            # `test_attempt_context_exposes_no_tool_port_until_a_tools_harness_is_admitted`
            # pins for every harness that declares `requires.tools == "none"`.
            runtime = self._tool_runtimes.get(profile.profile_id)
            if runtime is None:
                raise EvidenceIntegrityError(
                    f"profile {profile.profile_id!r} declares tools but no "
                    "ToolRuntime is registered"
                )
            tools_port = KernelToolPort(
                runtime=runtime,
                attempt_id=action_attempt_id,
                action_attempt_id=action_attempt_id,
                granted_tools=frozenset(profile.tools),
            )
        context = _KernelAttemptContext(
            attempt_id=action_attempt_id,
            seed=profile.sampling.seed or 0,
            budget=BudgetView(
                rounds_left=_rounds_budget(profile),
                tokens_left=profile.sampling.max_output_tokens,
                cost_left=profile.budgets.max_cost_usd,
            ),
            model=port,
            tools=tools_port,
            evidence=self.evidence,
        )
        try:
            output = await asyncio.wait_for(
                harness.act(decision, context),
                timeout=profile.budgets.timeout_seconds,
            )
        except ProviderFailure as failure:
            # KernelModelPort rejects an empty completion before it reaches the
            # harness, but the provider call itself succeeded and may have been
            # billed. Hand the retained result back to MinimalChatExecutor so
            # its canonical response retry path records the usage and applies
            # the declared empty_response policy. Treating it as a provider
            # failure here would erase the successful call's tokens and cost.
            if (
                failure.condition == "empty_response"
                and port.last_result is not None
                and not port.last_result.output_text.strip()
                and not port.last_result.tool_calls
            ):
                return port.last_result
            raise
        except asyncio.TimeoutError as error:
            # The base executor bounds its single provider call this way; a
            # harness owns a loop, so the bound belongs around the whole act().
            # Without it a hung provider -- or a harness that never stops
            # looping -- blocks the episode forever.
            raise ProviderFailure(
                "timeout",
                f"harness {self._harness_key(profile)!r} exceeded "
                f"{profile.budgets.timeout_seconds}s",
                retryable=True,
            ) from error

        result = port.last_result
        if result is None:
            raise ProviderFailure(
                "harness_contract",
                f"harness {self._harness_key(profile)!r} returned without a model call",
                retryable=False,
            )

        # Reconcile the harness's claim against what the kernel actually
        # recorded.  The kernel's count is the truth; a mismatch is recorded,
        # never raised, because a lying or buggy harness must not be able to
        # abort an episode -- but it must not pass unnoticed either.
        claimed = len(output.claimed_tool_calls) if output is not None else 0
        if claimed != port.tool_calls_dispatched:
            self.evidence.append_event(
                "harness_claim_unreconciled",
                {
                    "harness": self._harness_key(profile),
                    "claimed_tool_calls": claimed,
                    "recorded_tool_calls": port.tool_calls_dispatched,
                },
                action_attempt_id=request.provider_call_id,
            )

        # Carried to the CanonicalResponse this attempt builds (§5.1): the
        # base executor's `_harness_action` hook reads it back by this same
        # `action_attempt_id` once the provider result above is accepted.
        self._pending_actions[action_attempt_id] = (
            output.action if output is not None else None
        )
        self._pending_tool_ids[action_attempt_id] = (
            tuple(tools_port.invocation_ids) if tools_port is not None else ()
        )
        return result

    def _harness_action(self, action_attempt_id: str) -> Mapping[str, Any] | None:
        return self._pending_actions.get(action_attempt_id)

    def _harness_tool_invocation_ids(self, action_attempt_id: str) -> tuple[str, ...]:
        return self._pending_tool_ids.get(action_attempt_id, ())


__all__ = [
    "AttemptContext",
    "BudgetView",
    "CanonicalMessage",
    "ClaimedToolCall",
    "FailureCondition",
    "Harness",
    "HarnessOutput",
    "HarnessRequirements",
    "JsonDialectHarness",
    "KernelModelPort",
    "KernelToolPort",
    "ModelPort",
    "ModelTurn",
    "NativeToolCall",
    "NativeToolChatHarness",
    "ProviderCapabilities",
    "ToolExecutionEnvelope",
    "ToolPort",
    "ToolSchema",
    "AttemptExecutor",
    "MinimalChatHarness",
    "default_harnesses",
]
