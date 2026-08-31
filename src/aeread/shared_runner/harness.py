"""Agent-harness ports: the only doors a harness has onto the world.

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

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Protocol

from .execution import (
    CanonicalResponse,
    EvidenceIntegrityError,
    EvidenceStore,
    ProviderClient,
    ProviderFailure,
    ProviderRequest,
    MinimalChatExecutor,
    ProviderResult,
    TokenPricing,
    ToolFailure,
    ToolInvocationRecord,
    _stable_id,
)
from .resolver import canonical_json_bytes
from .schemas import AgentProfile
from .tools import ToolContractError, ToolRuntime


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
class ProviderCapabilities:
    native_tools: bool
    structured_output: bool
    seed: bool
    system_prompt: bool
    reasoning_budget: bool
    reasoning_token_report: bool
    max_context_tokens: int | None


@dataclass(frozen=True, slots=True)
class HarnessRequirements:
    provider: frozenset[str]
    tools: Literal["none", "declared", "any"]
    memory: frozenset[str]
    owns_retries: bool
    owns_tools: bool
    replayable: bool
    blocking: bool
    spawns_subagents: bool


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
        self._round = 0
        self.last_result: ProviderResult | None = None

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
            timeout_seconds=self._profile.budgets.timeout_seconds,
            request_sha256="",
            max_cost_usd=self._profile.budgets.max_cost_usd,
            output_schema=self._profile.harness.config.get("output_schema"),
            provider_metadata=self._profile.harness.config.get("provider_metadata"),
            seed=self._profile.sampling.seed,
            messages=messages if response_mode == "native_tools" else None,
            tools=tools if response_mode == "native_tools" and tools else None,
        ).with_computed_hash()

        if self._emit_events:
            self._evidence.append_event(
                "provider_call_started",
                {"request": request, "round": round_ordinal},
                phase_instance_id=self._phase_instance_id,
                logical_action_id=self._logical_action_id,
                action_attempt_id=self._action_attempt_id,
                provider_call_id=provider_call_id,
                visibility=self._visibility,
            )
        result = await self._provider.complete(request)
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
        if self._emit_events:
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
        family_reconciliation: (
            Callable[[str, Any, ToolInvocationRecord], Mapping[str, Any]] | None
        ) = None,
    ) -> None:
        self._runtime = runtime
        self._attempt_id = attempt_id
        self._action_attempt_id = action_attempt_id
        self._max_invocations = max_invocations
        self._family_reconciliation = family_reconciliation
        self._invocations = 0

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
        over_budget = (
            self._max_invocations is not None
            and self._invocations >= self._max_invocations
        )
        if not declared or over_budget:
            rejection_condition = "undeclared_tool" if not declared else "tool_budget_exceeded"
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
        return ToolExecutionEnvelope(
            result=result,
            invocation_record=record,
            family_reconciliation=reconciliation,
        )



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
    ) -> None:
        self._harnesses = dict(harnesses)
        super().__init__(
            evidence=evidence,
            profiles=profiles,
            prompt_sources=prompt_sources,
            providers=providers,
            pricing=pricing,
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

    async def _obtain_result(
        self,
        *,
        provider: ProviderClient,
        request: ProviderRequest,
        profile: AgentProfile,
        decision: Any,
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
        )
        context = _KernelAttemptContext(
            attempt_id=request.provider_call_id,
            seed=profile.sampling.seed or 0,
            budget=BudgetView(
                rounds_left=1,
                tokens_left=profile.sampling.max_output_tokens,
                cost_left=profile.budgets.max_cost_usd,
            ),
            model=port,
            tools=None,
            evidence=self.evidence,
        )
        await harness.act(decision, context)
        result = port.last_result
        if result is None:
            raise ProviderFailure(
                "harness_contract",
                f"harness {self._harness_key(profile)!r} returned without a model call",
                retryable=False,
            )
        return result


__all__ = [
    "AttemptContext",
    "BudgetView",
    "CanonicalMessage",
    "ClaimedToolCall",
    "FailureCondition",
    "Harness",
    "HarnessOutput",
    "HarnessRequirements",
    "KernelModelPort",
    "KernelToolPort",
    "ModelPort",
    "ModelTurn",
    "NativeToolCall",
    "ProviderCapabilities",
    "ToolExecutionEnvelope",
    "ToolPort",
    "ToolSchema",
    "AttemptExecutor",
    "MinimalChatHarness",
    "default_harnesses",
]
