"""TERMS-Bench's counterpart as a kernel scripted seat (#92).

The counterpart is the family's own seeded kernel, not a model. With the
scripted-seat capability the plan declares it as such and the kernel asks the
plugin for its turn; these tests hold that path against the legacy harness
path, which computes the same turn inside a test double, and require the two
to agree exactly.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from types import MappingProxyType

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell  # noqa: F401 -- type of _cell
from aeread.shared_runner.task.execution import EvidenceStore, ScriptedSeatSource
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.termsbench.environment import TermsBenchPlugin, register_plugin
from aeread_families.termsbench.harness import ScriptedTermsBenchHarness
from tests.test_termsbench_replay import OVERLAP_CASE_ID, _case, _cell

POLICY = TermsBenchPlugin.COUNTERPART_POLICY_ID


def _script(case):
    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    return [
        {"decision": "offer", "price": r_b + 0.1 * (r_a - r_b), "message": "opening"},
        {"decision": "offer", "price": r_b + 0.4 * (r_a - r_b), "message": "moving closer"},
        {"decision": "accept", "price": None, "message": "deal"},
    ]


def _evidence(tmp_path: Path, cell: PlanCell, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_termsbench_scripted_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_termsbench_scripted_{suffix}",
        episode_attempt_id="attempt_1",
    )


def _legacy(tmp_path: Path):
    """Both seats served by the test double; the counterpart from pure seed."""
    case = _case(OVERLAP_CASE_ID)
    cell = _cell(case, suffix="legacy")
    evidence = _evidence(tmp_path, cell, "legacy")
    harness = ScriptedTermsBenchHarness(world_seed=case.world_seed, script=_script(case), evidence=evidence)
    plugin = register_plugin(PluginRegistry())
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    evidence.seal()
    return case, plugin, evidence, result


def _scripted(tmp_path: Path):
    """The agent served by the test double; the counterpart by the kernel's
    scripted seat, asking the plugin's hook."""
    case = _case(OVERLAP_CASE_ID)
    cell = dataclasses.replace(
        _cell(case, suffix="scripted"),
        profile_by_seat=MappingProxyType({"agent": "scripted_agent"}),
        scripted_seats=MappingProxyType({"counterpart": POLICY}),
    )
    evidence = _evidence(tmp_path, cell, "scripted")
    harness = ScriptedTermsBenchHarness(world_seed=case.world_seed, script=_script(case), evidence=evidence)
    plugin = register_plugin(PluginRegistry())
    source = ScriptedSeatSource(evidence=evidence, plugin=plugin, cell=cell)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness, scripted_source=source)
    )
    evidence.seal()
    return case, plugin, evidence, result


def test_the_scripted_seat_reproduces_the_legacy_counterpart_exactly(tmp_path: Path) -> None:
    case, plugin, _, legacy = _legacy(tmp_path / "legacy")
    _, _, evidence, scripted = _scripted(tmp_path / "scripted")
    # Same case, seed and agent script: the two paths must end in the same
    # state, byte for byte -- which is the whole claim of a scripted seat.
    assert scripted.final_state == legacy.final_state
    assert scripted.final_state["counterpart_offers"], "the counterpart actually spoke"


def test_the_counterpart_turn_is_sealed_as_scripted_and_never_as_a_provider_call(tmp_path: Path) -> None:
    _, _, evidence, result = _scripted(tmp_path)
    events = evidence.read_events()
    kinds = [e.event_type for e in events]
    assert "provider_call_started" not in kinds, "no provider was ever consulted in this provider-free run"
    scripted = [e for e in events if e.event_type == "scripted_action"]
    starts = {}
    counterpart_turns = 0
    for e in events:
        if e.event_type == "logical_action_started":
            payload = json.loads((evidence.root / e.payload_ref).read_text())
            starts.setdefault(payload["request"]["seat_id"], payload)
            counterpart_turns += payload["request"]["seat_id"] == "counterpart"
    assert counterpart_turns >= 1
    assert len(scripted) == counterpart_turns, "one sealed response per counterpart turn"
    assert starts["counterpart"]["source"] == "scripted_policy"
    assert starts["counterpart"]["policy_id"] == POLICY
    # The agent here is served by a bare test double that seals no executor
    # lifecycle events, so the only logical actions on record are the
    # counterpart's -- and nothing else may ever carry the scripted marker.
    assert all(
        payload.get("source") != "scripted_policy"
        for seat_id, payload in starts.items()
        if seat_id != "counterpart"
    )
    evidence.audit_reconciliation()
