"""Drive the real housing_v1 plugin with the real episode scheduler.

The plugin's own suite calls its hooks by hand, in the order the author had in
mind. This module instead hands the plugin to `run_episode`, so the phase
schedule, the decision order, the frozen observations, and the evidence come
from the runner. It is the first test in which a family and the kernel meet.

The agents here are scripted: they read the observation the environment
actually produced and answer with the JSON the environment actually parses. No
provider is involved.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest

from aeread.families.housing_v1 import HousingV1EnvironmentPlugin
from aeread.families.housing_v1_records import HousingV1CellBinding
from aeread.runner.episode import run_episode
from aeread.runner.event_store import ArtifactStore, EventStore
from aeread.sdk.v1 import (
    CanonicalResponse,
    DecisionSlot,
    EventIdentity,
    ObservationEnvelope,
    content_sha256,
)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "housing_v1"
    / "e0_seed7_two_tenants_two_listings.json"
)

IDENTITY = EventIdentity(
    run_plan_id="plan-housing-e0",
    cell_id="housing-e0-cell-1",
    episode_id="episode-1",
    episode_attempt_id="attempt-1",
)


def _case_and_state() -> tuple[Any, Any, Any]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plugin = HousingV1EnvironmentPlugin()
    case = plugin.validate_case(raw)
    binding = HousingV1CellBinding(
        cell_id=IDENTITY.cell_id,
        case_id=raw["case_id"],
        case_sha256=raw["artifact_sha256"],
        world_seed=raw["provenance"]["seed"],
    )
    return plugin, case, binding


@dataclass
class ScriptedHousingAgent:
    """Answers each phase from the observation the environment handed it.

    Tenants offer the asking rent on the first open listing they can see;
    landlords accept the single best offer in their inbox; a tenant signs any
    hold it is given. The point is a legal, deterministic trajectory, not a
    good one.
    """

    seat_id: str
    seen_phases: list[str] = field(default_factory=list)

    async def act(self, request: Any, *, attempts: Any) -> CanonicalResponse:
        payload = dict(request.observation.visible_payload)
        phase = payload["phase"]
        self.seen_phases.append(phase)

        if phase == "contact":
            board = payload["public_board"]
            open_listings = [row for row in board if row["status"] == "OPEN"]
            if not open_listings:
                return CanonicalResponse(content="{}")
            listing = open_listings[0]
            answer = {
                "kind": "offer",
                "listing_id": listing["listing_id"],
                "rent": float(listing["rent_asked"]),
            }
        elif phase == "respond":
            inbox = payload["inbox"]
            decisions = [
                {
                    "offer_id": offer["offer_id"],
                    "decision": "accept" if index == 0 else "reject",
                    "counter_rent": None,
                }
                for index, offer in enumerate(inbox)
            ]
            answer = {"kind": "respond", "decisions": decisions}
        else:
            hold = payload["active_hold"]
            answer = {
                "kind": "commit",
                "decision": "sign",
                "hold_id": hold["hold_id"],
            }
        return CanonicalResponse(content=json.dumps(answer), finish_reason="stop")


def _request_factory(slot: DecisionSlot, observation: ObservationEnvelope) -> Any:
    @dataclass(frozen=True)
    class _Request:
        slot: DecisionSlot
        observation: ObservationEnvelope

    return _Request(slot=slot, observation=observation)


class ScriptedSeats(dict):
    """One scripted agent per seat, created the first time that seat acts.

    Seats cannot be enumerated up front: the plugin only reveals a phase's
    slots when the state is already in that phase, so asking for the commit
    seats while the state still says "contact" is a contract violation.
    """

    def __init__(self, factory: Any) -> None:
        super().__init__()
        self._factory = factory

    def get(self, seat_id: str, default: Any = None) -> Any:  # noqa: D102
        if seat_id not in self:
            self[seat_id] = self._factory(seat_id)
        return self[seat_id]


def _adapters() -> ScriptedSeats:
    return ScriptedSeats(ScriptedHousingAgent)


def _events(tmp_path: Path) -> EventStore:
    tmp_path.mkdir(parents=True, exist_ok=True)
    artifacts = ArtifactStore.open(
        tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
    )
    return EventStore.open(
        tmp_path / "events.jsonl", artifacts=artifacts, identity=IDENTITY
    )


def _run(tmp_path: Path, max_phases: int = 32) -> tuple[Any, EventStore, dict[str, Any]]:
    plugin, case, binding = _case_and_state()
    adapters = _adapters()
    events = _events(tmp_path)
    result = asyncio.run(
        run_episode(
            environment=plugin,
            case=case,
            cell=binding,
            adapters=adapters,
            events=events,
            identity=IDENTITY,
            request_factory=_request_factory,
            max_phases=max_phases,
        )
    )
    return result, events, adapters


def test_the_scheduler_drives_housing_to_a_family_terminal(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path)

    assert result.status == "terminal", result
    assert result.terminal is not None
    assert result.outcome is not None
    assert result.outcome.terminal_reason == result.terminal.reason


def test_every_declared_phase_runs_in_the_declared_order(tmp_path: Path) -> None:
    result, _, adapters = _run(tmp_path)

    phase_ids = [phase.phase_id for phase in result.phases]
    assert phase_ids[:3] == ["contact", "respond", "commit"]
    # Each seat only ever answered in phases where it holds a slot.
    for agent in adapters.values():
        assert agent.seen_phases, "a declared seat was never given a decision"


def test_actions_are_admitted_rather_than_rejected(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path)

    verdicts = [slot.verdict for phase in result.phases for slot in phase.slots]
    assert verdicts, "no decision was requested at all"
    bad = [
        (phase.phase_id, slot.slot_id, slot.verdict, slot.reason)
        for phase in result.phases
        for slot in phase.slots
        if slot.verdict != "applied"
    ]
    assert not bad, f"scripted legal play was rejected: {bad}"


def test_a_lease_is_signed_and_the_outcome_reports_per_seat_utility(
    tmp_path: Path,
) -> None:
    result, _, _ = _run(tmp_path)

    assert result.outcome is not None
    utility = dict(result.outcome.utility_by_seat)
    assert utility, "the family reported no per-seat utility"
    assert any(value != 0.0 for value in utility.values()), (
        "every seat scored zero, so no lease was signed on a legal trajectory"
    )


def test_the_evidence_log_carries_the_whole_episode(tmp_path: Path) -> None:
    _, events, _ = _run(tmp_path)

    log = events.snapshot().events
    types = [event.event_type for event in log]
    assert types[0] == "episode_started"
    assert types[-1] == "episode_terminal"
    assert types.count("phase_started") == types.count("phase_applied")
    started = [
        event
        for event in log
        if event.event_type == "logical_action_started"
    ]
    resolved = [
        event
        for event in log
        if event.event_type == "logical_action_resolved"
    ]
    assert len(started) == len(resolved) > 0
    # Every attempt is recorded before its verdict.
    for start, end in zip(started, resolved):
        assert start.sequence < end.sequence


def test_seat_private_evidence_is_labelled_for_that_seat_only(tmp_path: Path) -> None:
    _, events, _ = _run(tmp_path)

    for event in events.snapshot().events:
        if event.event_type in {"logical_action_started", "logical_action_resolved"}:
            assert event.visibility.startswith("seat:"), event.event_type
            assert event.payload is not None
            assert event.visibility == f"seat:{event.payload['seat_id']}"
        elif event.event_type.startswith("episode_") or event.event_type.startswith(
            "phase_"
        ):
            assert event.visibility == "public", event.event_type


def test_observations_within_a_phase_are_frozen_against_one_state(
    tmp_path: Path,
) -> None:
    """Two tenants contacting in the same round must not see each other's offer."""

    plugin, case, binding = _case_and_state()
    state = plugin.initial_state(case, binding)
    contact = plugin.phase_graph(case).phases[0]
    slots = plugin.decision_slots(case, state, contact)
    assert len(slots) >= 2, "the fixture needs at least two tenants to test freezing"

    observations = [plugin.observe(case, state, contact, slot) for slot in slots]
    boards = {
        content_sha256(observation.visible_payload["public_board"])
        for observation in observations
    }
    assert len(boards) == 1, "tenants saw different boards in one frozen phase"


def test_a_malformed_answer_is_a_typed_pass_not_an_episode_failure(
    tmp_path: Path,
) -> None:
    plugin, case, binding = _case_and_state()
    adapters = _adapters()

    class Babbling:
        async def act(self, request: Any, *, attempts: Any) -> CanonicalResponse:
            return CanonicalResponse(content="I would like the nicer flat, please.")

    # Seat the babbler in the first contact slot the environment will open.
    state = plugin.initial_state(case, binding)
    contact = plugin.phase_graph(case).phases[0]
    first_seat = plugin.decision_slots(case, state, contact)[0].seat_id
    adapters[first_seat] = Babbling()

    result = asyncio.run(
        run_episode(
            environment=plugin,
            case=case,
            cell=binding,
            adapters=adapters,
            events=_events(tmp_path),
            identity=IDENTITY,
            request_factory=_request_factory,
            max_phases=32,
        )
    )

    assert result.status == "terminal", "one bad seat must not abort the episode"
    malformed = [
        slot
        for phase in result.phases
        for slot in phase.slots
        if slot.verdict == "malformed"
    ]
    assert malformed, "the babbling seat was not recorded as malformed"
    assert all(slot.seat_id == first_seat for slot in malformed)
