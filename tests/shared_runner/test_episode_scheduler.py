"""Behaviour of the family-neutral episode scheduler.

These tests drive the scheduler with a scripted two-seat environment, so they
assert what the runner does — order, freezing, evidence, and admission — rather
than how it is written.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from aeread.runner.episode import EpisodeError, run_episode
from aeread.runner.event_store import ArtifactStore, EventStore
from aeread.sdk.v1 import (
    ActionBundle,
    ActionChannel,
    ActionEnvelope,
    CanonicalResponse,
    DecisionSlot,
    EventIdentity,
    FamilyOutcome,
    LegalityResult,
    ObservationEnvelope,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    TerminalResult,
    TransitionResult,
)


IDENTITY = EventIdentity(
    run_plan_id="plan-1",
    cell_id="cell-1",
    episode_id="episode-1",
    episode_attempt_id="attempt-1",
)


def _slot(slot_id: str, seat_id: str, order_key: str) -> DecisionSlot:
    return DecisionSlot(
        slot_id=slot_id,
        seat_id=seat_id,
        channels=(
            ActionChannel(
                channel_id="main",
                recipient_seat_ids=(),
                action_schema_ref="schema://action",
            ),
        ),
        observation_schema_ref="schema://observation",
        response_schema_ref="schema://response",
        order_key=order_key,
    )


def _bundle(slot_id: str, seat_id: str, payload: Mapping[str, object]) -> ActionBundle:
    return ActionBundle(
        slot_id=slot_id,
        actions=(
            ActionEnvelope(
                action_id=f"{slot_id}-a0",
                slot_id=slot_id,
                channel_id="main",
                actor_seat_id=seat_id,
                sequence_index=0,
                payload=dict(payload),
            ),
        ),
    )


@dataclass
class ScriptedEnvironment:
    """Two seats bid for two rounds, then the market settles.

    The environment records the state it was asked to observe, so a test can
    prove the runner froze observations before applying anything.
    """

    rounds: int = 2
    max_slots: int = 2
    reject: str | None = None  # "malformed" | "illegal" for seat_b
    invalid_action_policy: str = "pass"
    observed_states: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    stepped_bundles: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def initial_state(self, case: Any, cell: Any) -> dict[str, Any]:
        return {"round": 0, "bids": {}}

    def phase_graph(self, case: Any) -> PhaseGraph:
        return PhaseGraph(
            initial_phase_id="bid",
            phases=(
                PhaseSpec(
                    phase_id="bid",
                    actor_selector="all",
                    mode="simultaneous",
                    observation_schema_by_role={},
                    action_schema_by_role={},
                    max_logical_actions=self.max_slots,
                    invalid_action_policy=self.invalid_action_policy,
                    next_phases=("bid",),
                ),
            ),
        )

    def decision_slots(
        self, case: Any, state: Mapping[str, Any], phase: PhaseSpec
    ) -> Sequence[DecisionSlot]:
        # Deliberately returned out of order: the runner must sort them.
        return (
            _slot("slot-b", "seat_b", order_key="20"),
            _slot("slot-a", "seat_a", order_key="10"),
        )

    def observe(
        self,
        case: Any,
        state: Mapping[str, Any],
        phase: PhaseSpec,
        slot: DecisionSlot,
    ) -> ObservationEnvelope:
        self.observed_states.append((slot.slot_id, dict(state)))
        return ObservationEnvelope(
            schema_ref="schema://observation",
            slot_id=slot.slot_id,
            visible_payload={"round": state["round"], "bids": dict(state["bids"])},
            public_event_refs=(),
            private_event_refs=(),
        )

    def parse_action(
        self,
        case: Any,
        state: Mapping[str, Any],
        phase: PhaseSpec,
        slot: DecisionSlot,
        response: CanonicalResponse,
    ) -> ParseResult:
        if self.reject == "malformed" and slot.seat_id == "seat_b":
            return ParseResult(status="malformed", error_code="unparsable_bid")
        return ParseResult(
            status="ok", bundle=_bundle(slot.slot_id, slot.seat_id, {"bid": 1})
        )

    def legal(
        self,
        case: Any,
        state: Mapping[str, Any],
        phase: PhaseSpec,
        bundle: ActionBundle,
    ) -> LegalityResult:
        if self.reject == "illegal" and bundle.slot_id == "slot-b":
            return LegalityResult(status="illegal", reasons=("bid_below_reserve",))
        return LegalityResult(status="legal")

    def step(
        self,
        case: Any,
        state: Mapping[str, Any],
        phase: PhaseSpec,
        bundles: Mapping[str, ActionBundle],
    ) -> TransitionResult:
        self.stepped_bundles.append((phase.phase_id, tuple(sorted(bundles))))
        bids = dict(state["bids"])
        for slot_id, bundle in bundles.items():
            bids[bundle.actions[0].actor_seat_id] = bundle.actions[0].payload["bid"]
        next_round = state["round"] + 1
        return TransitionResult(
            state={"round": next_round, "bids": bids},
            next_phase_id="bid" if next_round < self.rounds else None,
            evidence={"applied": len(bundles)},
        )

    def terminal(
        self, case: Any, state: Mapping[str, Any]
    ) -> TerminalResult | None:
        if state["round"] >= self.rounds:
            return TerminalResult(
                status="terminal", reason="rounds_exhausted", final_state=dict(state)
            )
        return None

    def outcome(self, case: Any, terminal: TerminalResult) -> FamilyOutcome:
        return FamilyOutcome(
            terminal_reason=terminal.reason,
            payload=dict(terminal.final_state),
            utility_by_seat={"seat_a": 1.0, "seat_b": 0.0},
        )


@dataclass
class RecordingAdapter:
    """Answers every request and reports the order it was asked in."""

    seat_id: str
    calls: list[str] = field(default_factory=list)

    async def act(self, request: Any, *, attempts: Any) -> CanonicalResponse:
        self.calls.append(request.slot.slot_id)
        return CanonicalResponse(content="bid 1", finish_reason="stop")


def _request_factory(slot: DecisionSlot, observation: ObservationEnvelope) -> Any:
    """A minimal stand-in for the plan-resolved AgentRequest.

    The scheduler only needs an object it can hand to the adapter; binding a
    fully resolved profile is the resolver's job and is covered by the planning
    suite.
    """

    @dataclass(frozen=True)
    class _Request:
        slot: DecisionSlot
        observation: ObservationEnvelope

    return _Request(slot=slot, observation=observation)


def _open_events(tmp_path: Path) -> EventStore:
    tmp_path.mkdir(parents=True, exist_ok=True)
    artifacts = ArtifactStore.open(
        tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
    )
    return EventStore.open(
        tmp_path / "events.jsonl", artifacts=artifacts, identity=IDENTITY
    )


def _run(environment: ScriptedEnvironment, events: EventStore, **kwargs: Any) -> Any:
    adapters = {
        "seat_a": RecordingAdapter("seat_a"),
        "seat_b": RecordingAdapter("seat_b"),
    }
    result = asyncio.run(
        run_episode(
            environment=environment,
            case={},
            cell=None,
            adapters=adapters,
            events=events,
            identity=IDENTITY,
            request_factory=_request_factory,
            **kwargs,
        )
    )
    return result, adapters


def test_episode_runs_every_phase_and_reaches_the_family_terminal(tmp_path: Path) -> None:
    environment = ScriptedEnvironment(rounds=2)
    result, _ = _run(environment, _open_events(tmp_path))

    assert result.status == "terminal"
    assert result.terminal is not None and result.terminal.reason == "rounds_exhausted"
    assert result.outcome is not None
    assert result.outcome.utility_by_seat["seat_a"] == 1.0
    assert len(result.phases) == 2
    assert environment.stepped_bundles == [
        ("bid", ("slot-a", "slot-b")),
        ("bid", ("slot-a", "slot-b")),
    ]


def test_slots_are_visited_in_declared_order_not_returned_order(tmp_path: Path) -> None:
    environment = ScriptedEnvironment(rounds=1)
    _, adapters = _run(environment, _open_events(tmp_path))

    # The environment returned slot-b first; order_key puts slot-a first.
    assert [slot_id for slot_id, _ in environment.observed_states] == [
        "slot-a",
        "slot-b",
    ]
    assert adapters["seat_a"].calls == ["slot-a"]
    assert adapters["seat_b"].calls == ["slot-b"]


def test_simultaneous_observations_are_frozen_before_any_action_applies(
    tmp_path: Path,
) -> None:
    environment = ScriptedEnvironment(rounds=2)
    _run(environment, _open_events(tmp_path))

    first_round = [state for _, state in environment.observed_states[:2]]
    assert first_round[0] == first_round[1] == {"round": 0, "bids": {}}
    second_round = [state for _, state in environment.observed_states[2:]]
    assert second_round[0] == second_round[1]
    assert second_round[0]["round"] == 1
    # Both seats saw the same pre-phase state, including each other's absence.
    assert second_round[0]["bids"] == {"seat_a": 1, "seat_b": 1}


def test_malformed_action_is_a_typed_pass_and_never_reaches_step(
    tmp_path: Path,
) -> None:
    environment = ScriptedEnvironment(rounds=1, reject="malformed")
    result, _ = _run(environment, _open_events(tmp_path))

    verdicts = {slot.slot_id: slot.verdict for slot in result.phases[0].slots}
    assert verdicts == {"slot-a": "applied", "slot-b": "malformed"}
    assert environment.stepped_bundles == [("bid", ("slot-a",))]
    assert result.phases[0].forfeited_seat_ids == ()


def test_illegal_action_is_recorded_separately_from_a_parse_failure(
    tmp_path: Path,
) -> None:
    environment = ScriptedEnvironment(rounds=1, reject="illegal")
    result, _ = _run(environment, _open_events(tmp_path))

    slot_b = next(slot for slot in result.phases[0].slots if slot.slot_id == "slot-b")
    assert slot_b.verdict == "illegal"
    assert slot_b.reason == "bid_below_reserve"
    assert environment.stepped_bundles == [("bid", ("slot-a",))]


def test_evidence_records_the_attempt_before_the_adapter_answers(
    tmp_path: Path,
) -> None:
    events = _open_events(tmp_path)
    _run(ScriptedEnvironment(rounds=1), events)

    log = [(event.event_type, event.payload) for event in events.snapshot().events]
    types = [event_type for event_type, _ in log]
    assert types[0] == "episode_started"
    assert types[-1] == "episode_terminal"
    started = types.index("logical_action_started")
    resolved = types.index("logical_action_resolved")
    assert started < resolved, "the attempt must exist in the log before its verdict"
    assert "phase_started" in types and "phase_applied" in types


def test_phase_budget_stops_a_nonterminating_environment(tmp_path: Path) -> None:
    environment = ScriptedEnvironment(rounds=99)
    result, _ = _run(environment, _open_events(tmp_path), max_phases=3)

    assert result.status == "phase_budget_exhausted"
    assert result.outcome is None
    assert len(result.phases) == 3


def test_duplicate_slot_ids_fail_the_episode(tmp_path: Path) -> None:
    class DuplicateSlots(ScriptedEnvironment):
        def decision_slots(self, case, state, phase):  # type: ignore[no-untyped-def]
            return (_slot("dup", "seat_a", "10"), _slot("dup", "seat_b", "20"))

    with pytest.raises(EpisodeError, match="duplicate slot ids"):
        _run(DuplicateSlots(rounds=1), _open_events(tmp_path))


def test_more_slots_than_the_phase_declares_fail_the_episode(tmp_path: Path) -> None:
    with pytest.raises(EpisodeError, match="max_logical_actions"):
        _run(ScriptedEnvironment(rounds=1, max_slots=1), _open_events(tmp_path))


def test_a_slot_without_an_assigned_adapter_fails_the_episode(tmp_path: Path) -> None:
    class UnseatedSlot(ScriptedEnvironment):
        def decision_slots(self, case, state, phase):  # type: ignore[no-untyped-def]
            return (_slot("slot-x", "seat_missing", "10"),)

    with pytest.raises(EpisodeError, match="no adapter assigned"):
        _run(UnseatedSlot(rounds=1), _open_events(tmp_path))


def test_observation_for_the_wrong_slot_fails_the_episode(tmp_path: Path) -> None:
    class MisroutedObservation(ScriptedEnvironment):
        def observe(self, case, state, phase, slot):  # type: ignore[no-untyped-def]
            return ObservationEnvelope(
                schema_ref="schema://observation",
                slot_id="somewhere-else",
                visible_payload={},
                public_event_refs=(),
                private_event_refs=(),
            )

    with pytest.raises(EpisodeError, match="observation for slot"):
        _run(MisroutedObservation(rounds=1), _open_events(tmp_path))


def test_bundle_for_the_wrong_slot_fails_the_episode(tmp_path: Path) -> None:
    class MisroutedBundle(ScriptedEnvironment):
        def parse_action(self, case, state, phase, slot, response):  # type: ignore[no-untyped-def]
            return ParseResult(
                status="ok", bundle=_bundle("somewhere-else", slot.seat_id, {"bid": 1})
            )

    with pytest.raises(EpisodeError, match="bundle for slot"):
        _run(MisroutedBundle(rounds=1), _open_events(tmp_path))


def test_an_environment_that_neither_terminates_nor_advances_fails_loudly(
    tmp_path: Path,
) -> None:
    class Stalled(ScriptedEnvironment):
        def step(self, case, state, phase, bundles):  # type: ignore[no-untyped-def]
            return TransitionResult(state=dict(state), next_phase_id=None)

    with pytest.raises(EpisodeError, match="no next phase"):
        _run(Stalled(rounds=99), _open_events(tmp_path))


def test_unknown_next_phase_fails_the_episode(tmp_path: Path) -> None:
    class BadNextPhase(ScriptedEnvironment):
        def step(self, case, state, phase, bundles):  # type: ignore[no-untyped-def]
            return TransitionResult(state=dict(state), next_phase_id="nowhere")

    with pytest.raises(EpisodeError, match="does not declare"):
        _run(BadNextPhase(rounds=99), _open_events(tmp_path))


# ---------------------------------------------------------------------------
# Gaps found by an independent review of the first scheduler commit: the
# attempt observer, the forfeit path, per-action evidence ordering, and the
# edges an environment is allowed to have.
# ---------------------------------------------------------------------------


def _call_start(logical_action_id: str, ordinal: int = 1) -> Any:
    from aeread.sdk.v1 import CallAttemptStart

    return CallAttemptStart(
        call_attempt_id=f"{logical_action_id}-c{ordinal}",
        logical_action_id=logical_action_id,
        ordinal=ordinal,
        request_sha256="a" * 64,
        provider="test-provider",
        model="test-model",
        timeout_seconds=30.0,
        output_token_limit=256,
    )


def _call_result() -> Any:
    from aeread.sdk.v1 import ProviderCallResult

    return ProviderCallResult(
        provider_request_id="req-1",
        finish_reason="stop",
        input_tokens=64,
        output_tokens=8,
    )


@dataclass
class ObservingAdapter:
    """Registers one provider call per action, the way a real adapter must."""

    seat_id: str
    leave_open: bool = False
    start_twice: bool = False

    async def act(self, request: Any, *, attempts: Any) -> CanonicalResponse:
        start = _call_start(request.slot.slot_id)
        token = attempts.call_started(start)
        if self.start_twice:
            attempts.call_started(start)
        if not self.leave_open:
            attempts.call_succeeded(token, _call_result())
        return CanonicalResponse(content="bid 1", finish_reason="stop")


def _run_with(adapters: Mapping[str, Any], environment: Any, events: EventStore) -> Any:
    return asyncio.run(
        run_episode(
            environment=environment,
            case={},
            cell=None,
            adapters=adapters,
            events=events,
            identity=IDENTITY,
            request_factory=_request_factory,
            max_phases=8,
        )
    )


def test_provider_calls_are_recorded_around_the_adapter(tmp_path: Path) -> None:
    events = _open_events(tmp_path)
    adapters = {
        "seat_a": ObservingAdapter("seat_a"),
        "seat_b": ObservingAdapter("seat_b"),
    }
    _run_with(adapters, ScriptedEnvironment(rounds=1), events)

    log = [(event.event_type, event.payload) for event in events.snapshot().events]
    types = [event_type for event_type, _ in log]
    assert types.count("provider_call_started") == 2
    assert types.count("provider_call_succeeded") == 2
    # Each call is opened before the action it belongs to is resolved.
    for index, (event_type, payload) in enumerate(log):
        if event_type == "provider_call_started":
            later = [t for t, p in log[index:] if t == "logical_action_resolved"]
            assert later, "a provider call was recorded after its action resolved"


def test_an_adapter_that_leaves_a_call_open_fails_the_episode(tmp_path: Path) -> None:
    adapters = {
        "seat_a": ObservingAdapter("seat_a", leave_open=True),
        "seat_b": ObservingAdapter("seat_b"),
    }
    with pytest.raises(EpisodeError, match="unterminated"):
        _run_with(adapters, ScriptedEnvironment(rounds=1), _open_events(tmp_path))


def test_starting_the_same_provider_call_twice_fails_the_episode(
    tmp_path: Path,
) -> None:
    adapters = {
        "seat_a": ObservingAdapter("seat_a", start_twice=True),
        "seat_b": ObservingAdapter("seat_b"),
    }
    with pytest.raises(EpisodeError, match="started twice"):
        _run_with(adapters, ScriptedEnvironment(rounds=1), _open_events(tmp_path))


def test_forfeit_policy_records_the_seat_for_the_phase_and_the_episode(
    tmp_path: Path,
) -> None:
    environment = ScriptedEnvironment(
        rounds=2, reject="malformed", invalid_action_policy="forfeit"
    )
    result, _ = _run(environment, _open_events(tmp_path))

    assert result.phases[0].forfeited_seat_ids == ("seat_b",)
    assert result.forfeited_seat_ids == ("seat_b",)
    # A passing policy on the same failure records no forfeit at all.
    passing, _ = _run(
        ScriptedEnvironment(rounds=1, reject="malformed"), _open_events(tmp_path / "b")
    )
    assert passing.phases[0].forfeited_seat_ids == ()
    assert passing.forfeited_seat_ids == ()


def test_an_unknown_invalid_action_policy_fails_the_episode(tmp_path: Path) -> None:
    environment = ScriptedEnvironment(rounds=1, invalid_action_policy="Forfeit")
    with pytest.raises(EpisodeError, match="unknown invalid_action_policy"):
        _run(environment, _open_events(tmp_path))


def test_every_action_is_recorded_before_its_own_verdict(tmp_path: Path) -> None:
    """Per logical action, not merely the first one in the log."""

    events = _open_events(tmp_path)
    _run(ScriptedEnvironment(rounds=2), events)

    opened: dict[str, int] = {}
    for event in events.snapshot().events:
        if event.event_type == "logical_action_started":
            assert event.payload is not None
            opened[event.payload["logical_action_id"]] = event.sequence
        elif event.event_type == "logical_action_resolved":
            assert event.payload is not None
            action_id = event.payload["logical_action_id"]
            assert action_id in opened, f"{action_id} resolved without being started"
            assert opened.pop(action_id) < event.sequence
    assert not opened, f"actions started but never resolved: {sorted(opened)}"


def test_a_bundle_outside_the_slots_channels_is_illegal_not_applied(
    tmp_path: Path,
) -> None:
    """A parser may carry agent-chosen identifiers into a bundle."""

    class OffChannel(ScriptedEnvironment):
        def parse_action(self, case, state, phase, slot, response):  # type: ignore[no-untyped-def]
            bundle = ActionBundle(
                slot_id=slot.slot_id,
                actions=(
                    ActionEnvelope(
                        action_id=f"{slot.slot_id}-a0",
                        slot_id=slot.slot_id,
                        channel_id="a-channel-the-slot-never-offered",
                        actor_seat_id=slot.seat_id,
                        sequence_index=0,
                        payload={"bid": 1},
                    ),
                ),
            )
            return ParseResult(status="ok", bundle=bundle)

    environment = OffChannel(rounds=1)
    result, _ = _run(environment, _open_events(tmp_path))

    verdicts = {slot.slot_id: slot.verdict for slot in result.phases[0].slots}
    assert set(verdicts.values()) == {"illegal"}
    reasons = [slot.reason for slot in result.phases[0].slots]
    assert all("undeclared channel" in (reason or "") for reason in reasons)
    assert environment.stepped_bundles == [("bid", ())]


def test_a_phase_may_request_no_decisions_at_all(tmp_path: Path) -> None:
    class Bookkeeping(ScriptedEnvironment):
        def decision_slots(self, case, state, phase):  # type: ignore[no-untyped-def]
            return ()

    environment = Bookkeeping(rounds=1)
    result, _ = _run(environment, _open_events(tmp_path))

    assert result.status == "terminal"
    assert result.phases[0].slots == ()
    assert environment.stepped_bundles == [("bid", ())]


def test_an_episode_terminal_from_its_initial_state_runs_no_phase(
    tmp_path: Path,
) -> None:
    environment = ScriptedEnvironment(rounds=0)
    result, _ = _run(environment, _open_events(tmp_path))

    assert result.status == "terminal"
    assert result.phases == ()
    assert environment.stepped_bundles == []


def test_a_nonpositive_phase_budget_is_refused(tmp_path: Path) -> None:
    with pytest.raises(EpisodeError, match="max_phases"):
        _run(ScriptedEnvironment(rounds=1), _open_events(tmp_path), max_phases=0)


def test_one_seat_may_hold_two_slots_in_a_phase(tmp_path: Path) -> None:
    class DoubleDuty(ScriptedEnvironment):
        def decision_slots(self, case, state, phase):  # type: ignore[no-untyped-def]
            return (
                _slot("slot-1", "seat_a", "10"),
                _slot("slot-2", "seat_a", "20"),
            )

    environment = DoubleDuty(rounds=1)
    adapters = {"seat_a": RecordingAdapter("seat_a")}
    result = _run_with(adapters, environment, _open_events(tmp_path))

    assert adapters["seat_a"].calls == ["slot-1", "slot-2"]
    assert environment.stepped_bundles == [("bid", ("slot-1", "slot-2"))]
    assert result.status == "terminal"
