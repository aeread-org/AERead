"""Tests for the kernel scoring-input re-execution contract.

Ruling R2 (kernel_scoring_contract_spec.md): ``replay_family_scoring_input``
produces a verified deterministic re-execution of the pinned case,
cross-checking every phase boundary, action, and terminal state against the
sealed evidence -- it is not a pure read-back. The live in-memory
``EpisodeResult`` is never read (the function cannot even accept one as a
parameter), and everything it returns must be deeply immutable.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from types import MappingProxyType
from typing import Any

import pytest

from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.evaluation import (
    FamilyScoringInput,
    SeatContext,
    replay_family_scoring_input,
    replay_family_state,
)
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
)


def _run_housing_episode(tmp_path):
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    cell = next(item for item in setup.plan.cells if item.cell_id == execution.cell_id)
    case = next(item for item in setup.plan.cases if item.case_id == cell.case_id)
    family = next(
        item for item in setup.plan.families if item.family.id == cell.family_id
    )
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    return setup, execution, plugin, family_case, cell


class RecordingPlugin:
    """Transparent wrapper recording every hook call made against the plugin.

    ``initial_state`` also records the exact ``cell`` it was called with (the
    pre-existing behaviour other tests here depend on). Every other hook --
    ``phases``, ``eligible_actors``, ``step``, ``terminal``, ``outcome``,
    ``build_scorer``, ``validate_payload``, and anything else the real plugin
    exposes -- is recorded by name through a generic ``__getattr__`` that
    wraps callables, so this is otherwise indistinguishable from the real
    plugin to the replay machinery.
    """

    def __init__(self, plugin) -> None:
        self._plugin = plugin
        self.calls: list[str] = []
        self.initial_state_runs: list[Any] = []

    def initial_state(self, family_case, cell):
        self.calls.append("initial_state")
        self.initial_state_runs.append(cell)
        return self._plugin.initial_state(family_case, cell)

    def __getattr__(self, name):
        attribute = getattr(self._plugin, name)
        if not callable(attribute):
            return attribute

        def _recording(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return attribute(*args, **kwargs)

        return _recording


def test_replay_family_scoring_input_reconstructs_phase_instances(tmp_path) -> None:
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)

    scoring_input = replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        seat_context=SeatContext((), {}),
        cell=cell,
    )

    assert isinstance(scoring_input, FamilyScoringInput)
    # The re-executed trajectory, cross-checked against sealed evidence at
    # every step, reproduces the live episode's phase instances exactly.
    assert canonical_json_bytes(scoring_input.phase_instances) == canonical_json_bytes(
        execution.episode_result.phase_instances
    )
    assert canonical_json_bytes(scoring_input.outcome) == canonical_json_bytes(
        execution.episode_result.outcome
    )
    assert len(scoring_input.phase_instances) > 0
    assert all(
        len(phase_instance.actions) > 0
        for phase_instance in scoring_input.phase_instances
    )

    # evidence_refs is deterministic, deduplicated, and every id is a real
    # sealed event.
    assert scoring_input.evidence_refs
    assert len(set(scoring_input.evidence_refs)) == len(scoring_input.evidence_refs)
    sealed_event_ids = {event.event_id for event in execution.evidence.read_events()}
    assert set(scoring_input.evidence_refs) <= sealed_event_ids

    # replay_family_state (the pre-existing caller) still works unchanged.
    outcome, outcome_event = replay_family_state(
        plugin=plugin, family_case=family_case, evidence=execution.evidence, cell=cell
    )
    assert canonical_json_bytes(outcome) == canonical_json_bytes(scoring_input.outcome)
    assert outcome_event.event_id in scoring_input.evidence_refs


def test_replay_family_scoring_input_has_no_episode_result_parameter() -> None:
    import inspect

    signature = inspect.signature(replay_family_scoring_input)
    assert "episode_result" not in signature.parameters
    assert set(signature.parameters) == {
        "plugin",
        "family_case",
        "evidence",
        "seat_context",
        "cell",
    }


def test_replay_passes_the_exact_plan_cell_to_initial_state(tmp_path) -> None:
    """#135 A1: certified replay must invoke ``initial_state`` with the
    exact executed ``PlanCell``, not a reconstruction of it."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    recording_plugin = RecordingPlugin(plugin)

    replay_family_scoring_input(
        plugin=recording_plugin,
        family_case=family_case,
        evidence=execution.evidence,
        seat_context=SeatContext((), {}),
        cell=cell,
    )

    assert len(recording_plugin.initial_state_runs) == 1
    assert recording_plugin.initial_state_runs[0] is cell


def test_replay_rejects_cell_evidence_identity_mismatch_before_plugin_invocation(
    tmp_path,
) -> None:
    """#135 A1: a cell whose identity disagrees with the sealed evidence is
    rejected before any plugin hook runs or any event payload is read.

    The identity check reads the event list exactly once -- to reach the
    durable, hash-chained first event's ``cell_id`` (see the fix's comment in
    ``_replay_family_trajectory``) -- and nothing more: no plugin hook
    (recorded generically via ``RecordingPlugin``) and no per-event payload
    read (``read_event_payload``) happens on the rejection path.
    """
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    recording_plugin = RecordingPlugin(plugin)
    wrong = dataclasses.replace(cell, cell_id="wrong_cell")

    read_events_calls = 0
    read_event_payload_calls = 0
    original_read_events = execution.evidence.read_events
    original_read_event_payload = execution.evidence.read_event_payload

    def _counting_read_events() -> Any:
        nonlocal read_events_calls
        read_events_calls += 1
        return original_read_events()

    def _counting_read_event_payload(event: Any) -> Any:
        nonlocal read_event_payload_calls
        read_event_payload_calls += 1
        return original_read_event_payload(event)

    execution.evidence.read_events = _counting_read_events
    execution.evidence.read_event_payload = _counting_read_event_payload

    with pytest.raises(ValueError, match="replay cell identity does not match sealed evidence"):
        replay_family_scoring_input(
            plugin=recording_plugin,
            family_case=family_case,
            evidence=execution.evidence,
            seat_context=SeatContext((), {}),
            cell=wrong,
        )

    assert recording_plugin.calls == []
    assert recording_plugin.initial_state_runs == []
    # #135 A1 fix note: the identity check itself must read the durable event
    # list once to get a cell_id that a live attribute reassignment cannot
    # forge (see the adversarial test below); it must never read an
    # individual event's payload to do so.
    assert read_events_calls == 1
    assert read_event_payload_calls == 0


def test_replay_rejects_cell_identity_even_when_evidence_cell_id_agrees(
    tmp_path,
) -> None:
    """#135 A1 fix: ``evidence.cell_id`` is a plain assignable attribute
    (``EvidenceStore.__init__``'s ``self.cell_id = cell_id``), not durable
    evidence. A check that compares ``cell.cell_id`` against it is fooled the
    moment both sides are reassigned to the same wrong value -- which is
    exactly what this test does. Replay must still reject the mismatch by
    checking against the durable, hash-chained first event's ``cell_id``
    instead, which this in-memory reassignment cannot touch.
    """
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    execution.evidence.cell_id = "attacker_cell"
    attacker_cell = dataclasses.replace(cell, cell_id="attacker_cell")

    with pytest.raises(ValueError, match="replay cell identity does not match sealed evidence"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            seat_context=SeatContext((), {}),
            cell=attacker_cell,
        )


def test_replay_family_scoring_input_rejects_tampered_event_stream(tmp_path) -> None:
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)

    # A sanity replay succeeds before tampering.
    replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        seat_context=SeatContext((), {}),
        cell=cell,
    )

    events_path = execution.evidence.root / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    tampered_lines = []
    removed = False
    for line in lines:
        record = json.loads(line)
        if not removed and record.get("event_type") == "action_attempt_succeeded":
            removed = True
            continue
        tampered_lines.append(line)
    assert removed, "fixture must contain at least one action_attempt_succeeded event"
    events_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="successful attempt"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            seat_context=SeatContext((), {}),
            cell=cell,
        )


def test_replay_family_scoring_input_result_is_deeply_immutable(tmp_path) -> None:
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)

    scoring_input = replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        seat_context=SeatContext((), {}),
        cell=cell,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        scoring_input.outcome = {}

    assert isinstance(scoring_input.outcome, MappingProxyType)
    with pytest.raises(TypeError):
        scoring_input.outcome["tampered"] = True

    phase_instance = scoring_input.phase_instances[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        phase_instance.mode = "tampered"

    assert isinstance(phase_instance.observations, MappingProxyType)
    with pytest.raises(TypeError):
        phase_instance.observations["tampered"] = True

    with pytest.raises(TypeError):
        phase_instance.actions[0].request.observation["tampered"] = True  # type: ignore[index]

    with pytest.raises(dataclasses.FrozenInstanceError):
        phase_instance.actions = phase_instance.actions + ()  # type: ignore[misc]
