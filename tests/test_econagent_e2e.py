"""End-to-end coverage for econagent_v1 through the REAL shared-runner path
(spec section 5's e2e bullet, built in milestone 3).

Every prior econagent test file (``test_econagent_environment.py``,
``test_econagent_measurement.py``, ``test_econagent_goldens.py``) drives an
episode by calling ``EconAgentV1Plugin``'s own hooks directly in a hand-
wired loop -- never through ``aeread.shared_runner.task.scheduler.run_episode``,
``PluginRegistry.resolve_manifest``, or a real ``PlanCell``. This module is
the first to run a genuine ``PluginRegistry``/``run_episode`` episode for
this family, using the provider-free ``ScriptedEconAgentHarness`` (spec
section 5, milestone 3) as the scheduler's ``ResponseSource`` -- proving the
family's ``PhaseSpec``/seat plumbing actually works end to end through the
real kernel machinery, not merely through its own plugin hooks called by
hand.

Follows the same ``_require_bridge()``/skip convention as every other
econagent test file: tests that actually run a scenario through the real
upstream bridge run for real when a provisioned bridge interpreter is
available, and are skipped (never faked) otherwise.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode
from aeread_families.econagent_v1 import cases
from aeread_families.econagent_v1.econagent_bridge import (
    EconAgentBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econagent_v1.environment import (
    AGENT_MONTH_PHASE,
    EconAgentV1Plugin,
    family_manifest,
    register_plugin,
)
from aeread_families.econagent_v1.harness import ScriptedEconAgentHarness


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ECONAGENT_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-econagent",
    )
    root = Path(candidate)
    if not (root / "config.yaml").is_file():
        pytest.skip(
            f"pinned upstream EconAgent checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except EconAgentBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _require_bridge() -> None:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")


def _case(case_id: str) -> CaseManifest:
    path = Path("cases/econagent_v1") / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    n_agents = case.payload["scenario"]["n_agents"]
    profile_by_seat = {
        f"agent_{index}": "econagent_v1_scripted_complex" for index in range(n_agents)
    }
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econagent_e2e_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econagent_e2e",
        suite_version="0.1.0",
        block_id="block_econagent_e2e",
        sampling_plan_id="sampling_econagent_e2e",
        analysis_plan_id="analysis_econagent_e2e",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econagent_e2e_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(profile_by_seat),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_through_scheduler(
    case: CaseManifest, cell: PlanCell
) -> tuple[EpisodeResult, ScriptedEconAgentHarness]:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    harness = ScriptedEconAgentHarness()
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    return result, harness


# ---------------------------------------------------------------------------
# Bridge-gated: run real episodes through the real scheduler.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id",
    ["econagent.pilot.small10x12.seed0", "econagent.pilot.small10x12.seed1"],
)
def test_full_pilot_episode_completes_through_the_real_scheduler(case_id: str) -> None:
    """Spec section 5: both world-seed variants run end to end through
    ``run_episode``/``PluginRegistry`` -- the real shared-runner path, not a
    hand-wired plugin-hook loop."""
    _require_bridge()
    case = _case(case_id)
    cell = _cell(case, suffix=case_id.rsplit(".", 1)[-1])

    result, harness = _run_through_scheduler(case, cell)

    n_agents = case.payload["scenario"]["n_agents"]
    episode_length = case.payload["scenario"]["episode_length"]

    assert result.case_id == case.case_id
    assert result.family_id == "econagent_v1"
    assert result.terminal["reason"] == "episode_length_reached"
    assert result.terminal["timestep"] == episode_length
    assert len(result.terminal["dense_log"]["PeriodicTax"]) == episode_length
    assert len(result.terminal["month_actions"]) == episode_length

    # One simultaneous phase instance per month, every agent seat acting in
    # each -- confirms the real PhaseSpec/scheduler dispatch, not merely
    # `EconAgentV1Plugin.step()` called directly.
    assert len(result.phase_instances) == episode_length
    for instance in result.phase_instances:
        assert instance.phase_id == AGENT_MONTH_PHASE
        assert instance.mode == "simultaneous"
        assert set(instance.eligible_actors) == {
            f"agent_{index}" for index in range(n_agents)
        }
        assert len(instance.actions) == n_agents

    assert result.logical_action_count == n_agents * episode_length
    assert harness.call_count == n_agents * episode_length

    outcome = result.outcome
    assert outcome["termination_reason"] == "episode_length_reached"
    assert set(outcome["final_inventory_coin"]) == {str(i) for i in range(n_agents)}


def test_two_pilot_scenarios_produce_independent_non_colliding_episodes() -> None:
    """The two seed variants of one shape are genuinely different episodes."""
    _require_bridge()
    case0 = _case("econagent.pilot.small10x12.seed0")
    case1 = _case("econagent.pilot.small10x12.seed1")
    result0, _harness0 = _run_through_scheduler(case0, _cell(case0, suffix="collision_seed0"))
    result1, _harness1 = _run_through_scheduler(case1, _cell(case1, suffix="collision_seed1"))

    assert result0.episode_id != result1.episode_id
    assert result0.terminal["final_agents"] != result1.terminal["final_agents"]


# ---------------------------------------------------------------------------
# Bridge-gated: import determinism (spec section 5, mirroring tau3 section 8 P1).
# ---------------------------------------------------------------------------


def test_all_three_scenario_manifests_round_trip_through_the_importer_byte_identically() -> None:
    """Running the importer twice, and against the committed case files,
    produces byte-identical output -- the importer has no hidden nondeterminism."""
    _require_bridge()
    first_pins, first_cases = cases.import_all_cases(UPSTREAM_ROOT)
    first_manifest = cases.build_scenario_manifest(first_cases)
    second_pins, second_cases = cases.import_all_cases(UPSTREAM_ROOT)
    second_manifest = cases.build_scenario_manifest(second_cases)

    assert set(first_cases) == {scenario["case_id"] for scenario in cases.SCENARIOS}
    assert set(first_cases) == set(second_cases)
    assert canonical_json_bytes(first_pins) == canonical_json_bytes(second_pins)
    for case_id in first_cases:
        assert canonical_json_bytes(first_cases[case_id]) == canonical_json_bytes(
            second_cases[case_id]
        )
    assert canonical_json_bytes(first_manifest) == canonical_json_bytes(second_manifest)

    # And matches what milestone 1 actually committed to cases/econagent_v1/ --
    # determinism against a *fresh* run, not merely internal self-consistency.
    for case_id in first_cases:
        on_disk = json.loads(
            (Path("cases/econagent_v1") / f"{case_id}.json").read_text(encoding="utf-8")
        )
        assert canonical_json_bytes(on_disk) == canonical_json_bytes(first_cases[case_id])
    on_disk_manifest = json.loads(
        (Path("cases/econagent_v1") / "scenario_manifest.json").read_text(encoding="utf-8")
    )
    assert canonical_json_bytes(on_disk_manifest) == canonical_json_bytes(first_manifest)
