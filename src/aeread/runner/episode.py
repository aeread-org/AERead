"""Family-neutral episode scheduler.

The runner owns the phase schedule, the decision order, and the evidence; the
environment plugin owns every economic meaning. This module never imports a
concrete family and never branches on a family identifier.

One phase is applied as one deterministic batch:

    freeze observations -> collect actions -> parse -> legality -> one step

Observations for every active slot are frozen from the same pre-phase state
before any action is requested, so a simultaneous phase cannot give an earlier
seat a first-mover advantage. Slots are visited in ``order_key`` order so the
evidence sequence is reproducible; ``order_key`` is compared as a string, so a
plugin with ten or more slots in one phase must zero-pad it to keep the order
it intends.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ..sdk.v1 import (
    ActionBundle,
    AgentRequest,
    BundleValidationError,
    CallAttemptStart,
    CallAttemptToken,
    DecisionSlot,
    EventIdentity,
    FamilyOutcome,
    ObservationEnvelope,
    PhaseGraph,
    PhaseSpec,
    ProviderCallFailure,
    ProviderCallResult,
    TerminalResult,
    ToolInvocationFailure,
    ToolInvocationResult,
    ToolInvocationStart,
    ToolInvocationToken,
    content_sha256,
    validate_action_bundle,
)


class EpisodeError(RuntimeError):
    """The episode cannot proceed without violating an execution invariant."""


class UnknownPhase(EpisodeError):
    """The environment named a phase that its own graph does not declare."""


SlotVerdict = Literal["applied", "malformed", "illegal"]

#: What a phase may declare should happen to a seat whose action was not
#: admitted. `pass` leaves the seat out of this phase's batch; `forfeit` also
#: records the seat as having forfeited. `PhaseSpec.invalid_action_policy` is a
#: free string in the record, so the runner checks it here rather than letting a
#: typo silently choose the milder outcome.
INVALID_ACTION_POLICIES = frozenset({"pass", "forfeit"})


@dataclass(frozen=True)
class SlotOutcome:
    """What the runner recorded for one decision slot in one phase."""

    slot_id: str
    seat_id: str
    verdict: SlotVerdict
    reason: str | None = None


@dataclass(frozen=True)
class PhaseOutcome:
    """What the runner recorded for one phase instance.

    ``forfeited_seat_ids`` names the seats that forfeited *in this phase*; the
    episode-level total lives on :class:`EpisodeResult`.
    """

    phase_id: str
    slots: tuple[SlotOutcome, ...]
    applied_slot_ids: tuple[str, ...]
    forfeited_seat_ids: tuple[str, ...]


@dataclass(frozen=True)
class EpisodeResult:
    """The sealed result of one episode attempt."""

    status: Literal["terminal", "phase_budget_exhausted"]
    terminal: TerminalResult | None
    outcome: FamilyOutcome | None
    phases: tuple[PhaseOutcome, ...]
    final_state: Any
    forfeited_seat_ids: tuple[str, ...] = ()


@dataclass
class EventAttemptObserver:
    """Records provider calls and tool invocations before their side effects.

    Satisfies both ``AttemptObserver`` and ``ToolObserver``: an adapter that
    only talks to a model uses three methods, one that also calls tools uses
    six, and neither has to know which. Nothing may be left open — an adapter
    that starts a call or an invocation and never closes it fails the episode,
    because the log would otherwise claim a side effect whose outcome is
    unknown without saying so.
    """

    events: Any
    identity: EventIdentity
    logical_action_id: str
    seat_id: str
    _open: dict[str, CallAttemptStart] = field(default_factory=dict)
    _open_tools: dict[str, ToolInvocationStart] = field(default_factory=dict)

    def call_started(self, start: CallAttemptStart) -> CallAttemptToken:
        if start.call_attempt_id in self._open:
            raise EpisodeError(f"provider call {start.call_attempt_id!r} started twice")
        self.events.append(
            "provider_call_started",
            self.identity,
            f"seat:{self.seat_id}",
            {
                "logical_action_id": self.logical_action_id,
                "call_attempt_id": start.call_attempt_id,
                "ordinal": start.ordinal,
                "provider": start.provider,
                "model": start.model,
                "request_sha256": start.request_sha256,
                "retry_reason": start.retry_reason,
            },
        )
        token = CallAttemptToken(call_attempt_id=start.call_attempt_id)
        self._open[start.call_attempt_id] = start
        return token

    def call_succeeded(
        self, token: CallAttemptToken, result: ProviderCallResult
    ) -> None:
        self._close(token, "provider_call_succeeded", result)

    def call_failed(
        self, token: CallAttemptToken, failure: ProviderCallFailure
    ) -> None:
        self._close(token, "provider_call_failed", failure)

    def _close(self, token: CallAttemptToken, event_type: str, record: Any) -> None:
        if token.call_attempt_id not in self._open:
            raise EpisodeError(
                f"terminal event for unstarted call {token.call_attempt_id!r}"
            )
        del self._open[token.call_attempt_id]
        self.events.append(
            event_type,
            self.identity,
            f"seat:{self.seat_id}",
            {
                "logical_action_id": self.logical_action_id,
                "call_attempt_id": token.call_attempt_id,
                "record": record.model_dump(mode="python"),
            },
        )

    # -- tools (additive; an adapter without tools never calls these) --

    def tool_started(self, start: ToolInvocationStart) -> ToolInvocationToken:
        if start.invocation_id in self._open_tools:
            raise EpisodeError(
                f"tool invocation {start.invocation_id!r} started twice"
            )
        if start.logical_action_id != self.logical_action_id:
            raise EpisodeError(
                f"tool invocation {start.invocation_id!r} names logical action "
                f"{start.logical_action_id!r} while filling "
                f"{self.logical_action_id!r}"
            )
        self.events.append(
            "tool_invocation_started",
            self.identity,
            f"seat:{self.seat_id}",
            {
                "logical_action_id": self.logical_action_id,
                "invocation_id": start.invocation_id,
                "ordinal": start.ordinal,
                "tool_id": start.tool_id,
                "tool_version": start.tool_version,
                "effect": start.effect,
                "arguments_sha256": start.arguments_sha256,
            },
        )
        token = ToolInvocationToken(invocation_id=start.invocation_id)
        self._open_tools[start.invocation_id] = start
        return token

    def tool_succeeded(
        self, token: ToolInvocationToken, result: ToolInvocationResult
    ) -> None:
        self._close_tool(token, "tool_invocation_succeeded", result)

    def tool_failed(
        self, token: ToolInvocationToken, failure: ToolInvocationFailure
    ) -> None:
        self._close_tool(token, "tool_invocation_failed", failure)

    def _close_tool(
        self, token: ToolInvocationToken, event_type: str, record: Any
    ) -> None:
        start = self._open_tools.pop(token.invocation_id, None)
        if start is None:
            raise EpisodeError(
                f"terminal event for unstarted tool invocation "
                f"{token.invocation_id!r}"
            )
        if start.effect == "mutating" and record.state_changed is None:
            # A call declared as able to change the world must say whether it
            # did. Silence here would leave a verifier comparing final state
            # unable to tell this apart from a read.
            raise EpisodeError(
                f"tool invocation {token.invocation_id!r} declared "
                f"effect='mutating' but its outcome does not say whether "
                f"state changed"
            )
        self.events.append(
            event_type,
            self.identity,
            f"seat:{self.seat_id}",
            {
                "logical_action_id": self.logical_action_id,
                "invocation_id": token.invocation_id,
                "tool_id": start.tool_id,
                "effect": start.effect,
                "record": record.model_dump(mode="python"),
            },
        )

    def unclosed_call_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._open))

    def unclosed_tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._open_tools))


RequestFactory = Callable[[DecisionSlot, ObservationEnvelope], AgentRequest]


def _phase_by_id(graph: PhaseGraph, phase_id: str) -> PhaseSpec:
    for phase in graph.phases:
        if phase.phase_id == phase_id:
            return phase
    raise UnknownPhase(f"phase graph does not declare {phase_id!r}")


def _logical_action_id(phase_index: int, phase_id: str, slot_id: str) -> str:
    return f"la-{phase_index:04d}-{phase_id}-{slot_id}"


def _ordered_slots(
    slots: Sequence[DecisionSlot], phase: PhaseSpec
) -> tuple[DecisionSlot, ...]:
    """Deterministic slot order, with the phase's own declarations enforced.

    A duplicate slot id would collide in the evidence log, and more slots than
    the phase declares means the plugin contradicts its own `PhaseSpec`. Both
    are plugin defects, so they fail the episode instead of being repaired.
    """

    if phase.invalid_action_policy not in INVALID_ACTION_POLICIES:
        raise EpisodeError(
            f"phase {phase.phase_id!r} declares an unknown invalid_action_policy "
            f"{phase.invalid_action_policy!r}; expected one of "
            f"{sorted(INVALID_ACTION_POLICIES)}"
        )
    ordered = tuple(sorted(slots, key=lambda slot: (slot.order_key, slot.slot_id)))
    slot_ids = [slot.slot_id for slot in ordered]
    if len(slot_ids) != len(set(slot_ids)):
        raise EpisodeError(
            f"phase {phase.phase_id!r} returned duplicate slot ids: {slot_ids}"
        )
    if len(ordered) > phase.max_logical_actions:
        raise EpisodeError(
            f"phase {phase.phase_id!r} returned {len(ordered)} slots but declares "
            f"max_logical_actions={phase.max_logical_actions}"
        )
    return ordered


async def run_episode(
    *,
    environment: Any,
    case: Any,
    cell: Any,
    adapters: Mapping[str, Any],
    events: Any,
    identity: EventIdentity,
    request_factory: RequestFactory,
    max_phases: int = 64,
) -> EpisodeResult:
    """Run one episode attempt to termination or the declared phase budget.

    ``adapters`` maps a seat id to an object satisfying ``AgentAdapter``. The
    environment selects which seats act; a slot for an unseated id is a plan
    defect and fails the episode rather than being silently skipped.
    """

    if max_phases < 1:
        raise EpisodeError("max_phases must be at least 1")

    # Opened before the environment is asked for anything, so an attempt that
    # dies inside initial_state or phase_graph still leaves a record that it
    # was made.
    events.append("episode_started", identity, "public", {"max_phases": max_phases})

    state = environment.initial_state(case, cell)
    graph = environment.phase_graph(case)
    phase_id: str | None = graph.initial_phase_id
    phases: list[PhaseOutcome] = []
    forfeited: set[str] = set()

    events.append(
        "episode_environment_ready",
        identity,
        "public",
        {"initial_phase_id": graph.initial_phase_id},
    )

    for phase_index in range(max_phases):
        terminal = environment.terminal(case, state)
        if terminal is not None:
            return _finalize(
                environment, case, events, identity, terminal, phases, state, forfeited
            )
        if phase_id is None:
            raise EpisodeError(
                "environment declared no next phase without reaching a terminal state"
            )

        phase = _phase_by_id(graph, phase_id)
        slots = _ordered_slots(environment.decision_slots(case, state, phase), phase)
        events.append(
            "phase_started",
            identity,
            "public",
            {
                "phase_index": phase_index,
                "phase_id": phase.phase_id,
                "mode": phase.mode,
                "slot_ids": [slot.slot_id for slot in slots],
            },
        )

        # Freeze every observation against the same pre-phase state before any
        # action is requested: this is what makes a simultaneous phase fair.
        frozen: list[tuple[DecisionSlot, ObservationEnvelope]] = [
            (slot, environment.observe(case, state, phase, slot)) for slot in slots
        ]

        bundles: dict[str, ActionBundle] = {}
        slot_outcomes: list[SlotOutcome] = []
        forfeited_here: set[str] = set()
        for slot, observation in frozen:
            outcome, bundle = await _run_slot(
                environment=environment,
                case=case,
                state=state,
                phase=phase,
                slot=slot,
                observation=observation,
                adapters=adapters,
                events=events,
                identity=identity,
                request_factory=request_factory,
                logical_action_id=_logical_action_id(
                    phase_index, phase.phase_id, slot.slot_id
                ),
            )
            slot_outcomes.append(outcome)
            if bundle is not None:
                bundles[slot.slot_id] = bundle
            elif phase.invalid_action_policy == "forfeit":
                forfeited_here.add(slot.seat_id)
                forfeited.add(slot.seat_id)

        transition = environment.step(case, state, phase, bundles)
        state = transition.state
        applied = tuple(sorted(bundles))
        phase_outcome = PhaseOutcome(
            phase_id=phase.phase_id,
            slots=tuple(slot_outcomes),
            applied_slot_ids=applied,
            forfeited_seat_ids=tuple(sorted(forfeited_here)),
        )
        phases.append(phase_outcome)
        events.append(
            "phase_applied",
            identity,
            "public",
            {
                "phase_index": phase_index,
                "phase_id": phase.phase_id,
                "applied_slot_ids": list(applied),
                "verdicts": [
                    {
                        "slot_id": item.slot_id,
                        "seat_id": item.seat_id,
                        "verdict": item.verdict,
                        "reason": item.reason,
                    }
                    for item in slot_outcomes
                ],
                "next_phase_id": transition.next_phase_id,
                "evidence": dict(transition.evidence),
            },
        )
        phase_id = transition.next_phase_id

    terminal = environment.terminal(case, state)
    if terminal is not None:
        return _finalize(
            environment, case, events, identity, terminal, phases, state, forfeited
        )

    events.append(
        "episode_phase_budget_exhausted",
        identity,
        "public",
        {"max_phases": max_phases},
    )
    return EpisodeResult(
        status="phase_budget_exhausted",
        terminal=None,
        outcome=None,
        phases=tuple(phases),
        final_state=state,
        forfeited_seat_ids=tuple(sorted(forfeited)),
    )


async def _run_slot(
    *,
    environment: Any,
    case: Any,
    state: Any,
    phase: PhaseSpec,
    slot: DecisionSlot,
    observation: ObservationEnvelope,
    adapters: Mapping[str, Any],
    events: Any,
    identity: EventIdentity,
    request_factory: RequestFactory,
    logical_action_id: str,
) -> tuple[SlotOutcome, ActionBundle | None]:
    """Request, parse, and admit one logical action. Never mutates state."""

    adapter = adapters.get(slot.seat_id)
    if adapter is None:
        raise EpisodeError(f"no adapter assigned for seat {slot.seat_id!r}")
    if observation.slot_id != slot.slot_id:
        raise EpisodeError(
            f"environment returned an observation for slot "
            f"{observation.slot_id!r} while filling slot {slot.slot_id!r}"
        )

    request = request_factory(slot, observation)
    # Write before the side effect: the attempt exists in the log even if the
    # process dies inside the adapter.
    events.append(
        "logical_action_started",
        identity,
        f"seat:{slot.seat_id}",
        {
            "logical_action_id": logical_action_id,
            "phase_id": phase.phase_id,
            "slot_id": slot.slot_id,
            "seat_id": slot.seat_id,
            "observation_sha256": content_sha256(observation),
        },
    )
    observer = EventAttemptObserver(
        events=events,
        identity=identity,
        logical_action_id=logical_action_id,
        seat_id=slot.seat_id,
    )
    response = await adapter.act(request, attempts=observer)
    unclosed = observer.unclosed_call_ids()
    if unclosed:
        raise EpisodeError(
            f"adapter left provider calls unterminated: {list(unclosed)}"
        )
    unclosed_tools = observer.unclosed_tool_ids()
    if unclosed_tools:
        raise EpisodeError(
            f"adapter left tool invocations unterminated: {list(unclosed_tools)}"
        )

    parsed = environment.parse_action(case, state, phase, slot, response)
    if parsed.status != "ok" or parsed.bundle is None:
        return (
            _record_verdict(
                events,
                identity,
                logical_action_id,
                slot,
                "malformed",
                parsed.error_code,
                phase.invalid_action_policy,
            ),
            None,
        )

    if parsed.bundle.slot_id != slot.slot_id:
        # The parser is handed the slot it is filling, so a mismatch here is the
        # plugin ignoring its own argument, not anything the agent said.
        raise EpisodeError(
            f"parser returned a bundle for slot {parsed.bundle.slot_id!r} "
            f"while filling slot {slot.slot_id!r}"
        )

    # The slot declares which channels exist, how many actions each accepts, and
    # who may act. A parser can carry agent-chosen identifiers into a bundle — a
    # tenant naming someone else's hold, say — so failing this check is the agent
    # acting outside the offered decision surface, not a plugin defect.
    try:
        validate_action_bundle(parsed.bundle, slot)
    except BundleValidationError as error:
        return (
            _record_verdict(
                events,
                identity,
                logical_action_id,
                slot,
                "illegal",
                str(error),
                phase.invalid_action_policy,
            ),
            None,
        )

    legality = environment.legal(case, state, phase, parsed.bundle)
    if legality.status != "legal":
        return (
            _record_verdict(
                events,
                identity,
                logical_action_id,
                slot,
                "illegal",
                "; ".join(legality.reasons) or None,
                phase.invalid_action_policy,
            ),
            None,
        )

    return (
        _record_verdict(
            events, identity, logical_action_id, slot, "applied", None, None
        ),
        parsed.bundle,
    )


def _record_verdict(
    events: Any,
    identity: EventIdentity,
    logical_action_id: str,
    slot: DecisionSlot,
    verdict: SlotVerdict,
    reason: str | None,
    invalid_action_policy: str | None,
) -> SlotOutcome:
    events.append(
        "logical_action_resolved",
        identity,
        f"seat:{slot.seat_id}",
        {
            "logical_action_id": logical_action_id,
            "slot_id": slot.slot_id,
            "seat_id": slot.seat_id,
            "verdict": verdict,
            "reason": reason,
            "invalid_action_policy": invalid_action_policy,
        },
    )
    return SlotOutcome(
        slot_id=slot.slot_id, seat_id=slot.seat_id, verdict=verdict, reason=reason
    )


def _finalize(
    environment: Any,
    case: Any,
    events: Any,
    identity: EventIdentity,
    terminal: TerminalResult,
    phases: Sequence[PhaseOutcome],
    state: Any,
    forfeited: Sequence[str],
) -> EpisodeResult:
    outcome = environment.outcome(case, terminal)
    events.append(
        "episode_terminal",
        identity,
        "public",
        {
            "reason": terminal.reason,
            "terminal_reason": outcome.terminal_reason,
            "utility_by_seat": dict(outcome.utility_by_seat),
        },
    )
    return EpisodeResult(
        status="terminal",
        terminal=terminal,
        outcome=outcome,
        phases=tuple(phases),
        final_state=state,
        forfeited_seat_ids=tuple(sorted(forfeited)),
    )


__all__ = [
    "EpisodeError",
    "EpisodeResult",
    "EventAttemptObserver",
    "PhaseOutcome",
    "SlotOutcome",
    "UnknownPhase",
    "run_episode",
]
