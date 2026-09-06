"""Tests for the govsim scripted harness and offline replayer (spec section 5).

Per-test skip, never module-level (triage Finding 7: a module-level skip --
this module's own convention before that fix, and still
``tests/test_tau3_retail_replay.py``'s -- suppresses collection of every
test in the file, including the bridge-INDEPENDENT ones below (JSON
round-tripping, recorded-response ordering, mismatch reporting, harness
behavior), hiding a regression in any of those behind a missing-checkout
skip instead of running and failing it). Pure, provider-free structural
tests run everywhere; tests that drive a genuine episode through the REAL
kernel scheduler (``aeread.shared_runner.task.scheduler.run_episode``, via
``PluginRegistry``/``ScriptedGovsimHarness`` -- never the ad hoc
``_drive_episode`` loop ``tests/test_govsim_measurement.py`` uses for its
own goldens) run for real against the pinned bridge and are individually
skipped, never faked, otherwise.

Two full episodes are driven through the real scheduler here (spec's
"drive at least 2 full episodes"): the checked-in
``govsim.fishing.sustainable.0`` case (QC Gate 2's "successful" golden --
runs the complete 12-round horizon) and ``govsim.fishing.greedy.0`` (the
"valid-but-poor" golden -- collapses well before the horizon). Both are
replayed offline from a recorded, plain-JSON decision log with zero policy
evaluation and zero network calls, and reproduce state and every scored
leaf byte-identically -- a stronger guarantee than ``tau3_retail`` gets
(that family's replay only matches in *content*, never byte-for-byte, because
every appended message carries a fresh wall-clock timestamp; govsim's state
carries no such field -- see ``replay.py``'s module docstring).
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
import pytest

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import EpisodeResult, SchedulerContractError, run_episode
from aeread_families.govsim import measurement as m
from aeread_families.govsim.environment import (
    DISCUSS_PHASE,
    HARVEST_PHASE,
    REFLECT_PHASE,
    GovsimPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.govsim.govsim_bridge import (
    GovsimBridge,
    GovsimBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.govsim.harness import ScriptedGovsimHarness
from aeread_families.govsim.replay import (
    RecordedDecision,
    RecordedEpisode,
    RecordedResponseSource,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    record_episode,
    replay_and_verify,
    replay_episode,
    score_replayed_episode,
)

CASES_DIR = Path("cases/govsim/v1")


def _find_upstream_root() -> Path | None:
    """Locate the pinned upstream checkout, or report it missing -- never a
    module-level skip (triage Finding 7: a module-level skip here would
    suppress every bridge-INDEPENDENT test below too -- JSON round-tripping,
    recorded-response ordering, mismatch reporting, and harness behavior --
    hiding a regression in any of those instead of running and failing it).
    Mirrors ``tests/test_govsim_measurement.py``'s identical per-test-skip
    convention.
    """
    candidate = os.environ.get(
        "AEREAD_GOVSIM_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-govsim",
    )
    root = Path(candidate)
    marker = root / "simulation" / "scenarios" / "common" / "environment" / "concurrent_env.py"
    return root if marker.is_file() else None


UPSTREAM_ROOT = _find_upstream_root()

if UPSTREAM_ROOT is not None:
    try:
        BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
    except GovsimBridgeUnavailableError as error:
        BRIDGE_PYTHON = None
        _BRIDGE_SKIP_REASON = str(error)
    else:
        _BRIDGE_SKIP_REASON = ""
else:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = "pinned upstream govsim checkout not found"


def _bridge() -> GovsimBridge:
    if UPSTREAM_ROOT is None or BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )


@pytest.fixture(scope="module")
def bridge() -> GovsimBridge:
    return _bridge()


# ---------------------------------------------------------------------------
# Episode-driving helpers (bridge-gated tests only).
# ---------------------------------------------------------------------------


def _case(case_id: str) -> CaseManifest:
    path = CASES_DIR / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    num_agents = int(case.payload["env_cfg"]["num_agents"])
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_govsim_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_govsim_replay",
        suite_version="0.1.0",
        block_id="block_govsim_replay",
        sampling_plan_id="sampling_govsim_replay",
        analysis_plan_id="analysis_govsim_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_govsim_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {f"persona_{i}": "scripted_persona" for i in range(num_agents)}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _resolved_plugin(bridge_instance: GovsimBridge) -> Any:
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge_instance)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    return registry.resolve_manifest(family_manifest())


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _baseline_values(terminal: Mapping[str, Any], *, max_num_rounds: int) -> dict[str, float]:
    """The three comparative quantities computed from one episode's own
    terminal state -- exactly what a caller must supply to
    ``GovsimScorer``'s comparative scorers (``measurement.py`` never
    re-runs a baseline episode itself). Mirrors
    ``tests/test_govsim_measurement.py``'s identically-named helper."""
    survival_months = min(float(terminal["num_round"]), float(max_num_rounds))
    total_harvest = float(sum(terminal["collected_resource"].values()))
    gini = m._vendored_gini(
        np.array(list(terminal["collected_resource"].values()), dtype=float)
    )
    return {
        "survival_months": survival_months,
        "total_harvest": total_harvest,
        "gini": gini,
    }


@dataclass(frozen=True, slots=True)
class LiveRun:
    """One completed live episode, its cell, and its sealed evidence generation."""

    case: CaseManifest
    cell: PlanCell
    result: EpisodeResult
    evidence: EvidenceStore
    harness: ScriptedGovsimHarness


def _run_live(bridge_instance: GovsimBridge, tmp_path: Path, case_id: str, *, suffix: str) -> LiveRun:
    """Drive one complete episode through the REAL kernel scheduler.

    Unlike ``tests/test_govsim_measurement.py``'s ``_drive_episode`` (which
    calls ``GovsimPlugin``'s hooks directly, bypassing the scheduler's own
    budget checks, envelope construction, and state hashing entirely), this
    goes through ``aeread.shared_runner.task.scheduler.run_episode`` with a
    ``PluginRegistry``-resolved plugin and ``ScriptedGovsimHarness`` as the
    ``response_source`` -- the same code path a live model-backed run would
    use.
    """
    case = _case(case_id)
    cell = _cell(case, suffix=suffix)
    resolved_plugin = _resolved_plugin(bridge_instance)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_govsim_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_govsim_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedGovsimHarness(
        policy_assignment=case.payload["policy_assignment"], evidence=evidence
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    evidence.seal()
    return LiveRun(case=case, cell=cell, result=result, evidence=evidence, harness=harness)


@pytest.fixture(scope="module")
def live_sustainable(bridge: GovsimBridge, tmp_path_factory: pytest.TempPathFactory) -> LiveRun:
    tmp_path = tmp_path_factory.mktemp("govsim_replay_sustainable")
    return _run_live(bridge, tmp_path, "govsim.fishing.sustainable.0", suffix="sustainable")


@pytest.fixture(scope="module")
def live_greedy(bridge: GovsimBridge, tmp_path_factory: pytest.TempPathFactory) -> LiveRun:
    tmp_path = tmp_path_factory.mktemp("govsim_replay_greedy")
    return _run_live(bridge, tmp_path, "govsim.fishing.greedy.0", suffix="greedy")


# ---------------------------------------------------------------------------
# Pure, no bridge: ScriptedGovsimHarness in isolation.
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, phase_id: str, seat_id: str, observation: Mapping[str, Any]) -> None:
        self.phase_id = phase_id
        self.seat_id = seat_id
        self.observation = observation


class _FakeDecisionRequest:
    def __init__(self, phase_id: str, phase_instance_id: str) -> None:
        self.phase_id = phase_id
        self.phase_instance_id = phase_instance_id


class _FakeEnvelope:
    def __init__(self, valid: bool) -> None:
        self.valid = valid


class _FakeRecord:
    def __init__(
        self,
        *,
        phase_id: str,
        phase_instance_id: str,
        seat_id: str,
        response: Mapping[str, Any],
        valid: bool,
        logical_action_id: str,
    ) -> None:
        self.request = _FakeDecisionRequest(phase_id, phase_instance_id)
        self.seat_id = seat_id
        self.response = response
        self.envelope = _FakeEnvelope(valid)
        self.logical_action_id = logical_action_id


def test_scripted_harness_computes_the_assigned_policys_quantity_for_harvest() -> None:
    harness = ScriptedGovsimHarness(policy_assignment={"persona_0": "sustainable_v1"})
    request = _FakeRequest(
        HARVEST_PHASE,
        "persona_0",
        {"sustainability_threshold": 7, "resource_in_pool": 40, "num_round": 0},
    )
    response = asyncio.run(harness(request))
    assert response == {"quantity": 7}
    assert harness.requests == [request]


def test_scripted_harness_answers_discuss_and_reflect_with_an_empty_object() -> None:
    harness = ScriptedGovsimHarness(policy_assignment={"persona_0": "sustainable_v1"})
    for phase_id in (DISCUSS_PHASE, REFLECT_PHASE):
        request = _FakeRequest(phase_id, "persona_0", {})
        assert asyncio.run(harness(request)) == {}


def test_scripted_harness_raises_for_an_unknown_phase() -> None:
    harness = ScriptedGovsimHarness(policy_assignment={"persona_0": "sustainable_v1"})
    request = _FakeRequest("mystery_phase", "persona_0", {})
    with pytest.raises(RuntimeError, match="no response for phase"):
        asyncio.run(harness(request))


def test_scripted_harness_finalize_action_appends_one_sealed_evidence_event(
    tmp_path: Path,
) -> None:
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_harness_unit",
        cell_id="cell_harness_unit",
        episode_id="episode_harness_unit",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedGovsimHarness(
        policy_assignment={"persona_0": "sustainable_v1"}, evidence=evidence
    )
    record = _FakeRecord(
        phase_id=HARVEST_PHASE,
        phase_instance_id="phase_instance_0",
        seat_id="persona_0",
        response={"quantity": 5},
        valid=True,
        logical_action_id="logical_action_0",
    )

    asyncio.run(harness.finalize_action(record))

    events = evidence.read_events()
    assert len(events) == 1
    assert events[0].event_type == "govsim_logical_action_completed"
    assert events[0].phase_instance_id == "phase_instance_0"
    assert events[0].logical_action_id == "logical_action_0"
    payload = evidence.read_event_payload(events[0])
    assert payload == {
        "phase_id": HARVEST_PHASE,
        "seat_id": "persona_0",
        "response": {"quantity": 5},
        "valid": True,
    }
    evidence.seal()
    evidence.close()


def test_scripted_harness_finalize_action_is_a_noop_without_an_evidence_store() -> None:
    harness = ScriptedGovsimHarness(policy_assignment={"persona_0": "sustainable_v1"})
    record = _FakeRecord(
        phase_id=HARVEST_PHASE,
        phase_instance_id="phase_instance_0",
        seat_id="persona_0",
        response={"quantity": 5},
        valid=True,
        logical_action_id="logical_action_0",
    )
    asyncio.run(harness.finalize_action(record))  # must not raise


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id=HARVEST_PHASE, seat_id="persona_0", response={"quantity": 7, "n": (1, 2)}
    )
    episode = RecordedEpisode(case_id="govsim.fishing.sustainable.0", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == HARVEST_PHASE
    assert restored.decisions[0].seat_id == "persona_0"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.decisions[0].response == {"quantity": 7, "n": [1, 2]}


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id=HARVEST_PHASE, seat_id="persona_0", response={"quantity": 3}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = HARVEST_PHASE
        seat_id = "persona_0"

    response = asyncio.run(source(_Request()))
    assert response == {"quantity": 3}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id=DISCUSS_PHASE, seat_id="persona_0", response={}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = HARVEST_PHASE
        seat_id = "persona_1"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "collapse_or_horizon", "num_round": 12},
        outcome={"termination_reason": "collapse_or_horizon"},
        final_state={"termination": "collapse_or_horizon"},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "collapse_or_horizon", "num_round": 3},
        outcome={"termination_reason": "collapse_or_horizon"},
        final_state={"termination": "collapse_or_horizon"},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Bridge-gated: at least 2 full episodes driven through the REAL scheduler,
# then replayed offline with zero policy evaluation and zero network calls.
# ---------------------------------------------------------------------------


def test_live_run_produces_sealed_evidence_that_verifies(live_sustainable: LiveRun) -> None:
    seal = live_sustainable.evidence.verify_seal()
    events = live_sustainable.evidence.read_events()
    total_actions = sum(len(instance.actions) for instance in live_sustainable.result.phase_instances)
    assert total_actions > 0
    assert len(events) == total_actions
    assert seal.event_count == len(events)
    assert all(event.event_type == "govsim_logical_action_completed" for event in events)


def test_replay_from_a_json_round_tripped_record_reproduces_the_full_horizon_live_run(
    live_sustainable: LiveRun,
) -> None:
    recorded = record_episode(live_sustainable.result)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == live_sustainable.case.case_id

    # A second, independent GovsimBridge/plugin -- not the one that produced
    # the original run -- drives the replay.
    replay_bridge = GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )
    resolved_replay_plugin = _resolved_plugin(replay_bridge)

    replayed = asyncio.run(
        replay_episode(
            cell=live_sustainable.cell,
            case=live_sustainable.case,
            plugin=resolved_replay_plugin,
            recorded=recorded,
        )
    )

    comparison = compare_episode_results(live_sustainable.result, replayed)
    assert comparison.matches is True
    # Unlike tau3_retail (whose replay never matches the ORIGINAL raw state
    # byte-for-byte, only in content, because every appended message is
    # re-timestamped -- see that family's replay.py), govsim's state carries
    # no wall-clock field at all, so replay reproduces it byte-identically.
    assert comparison.state_hashes_match is True
    assert comparison.final_state_matches is True
    assert replayed.terminal["reason"] == "collapse_or_horizon"
    assert replayed.terminal["num_round"] == 12
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        live_sustainable.result.final_state
    )
    assert canonical_json_bytes(replayed.terminal) == canonical_json_bytes(
        live_sustainable.result.terminal
    )


def test_replay_reproduces_a_second_full_episode_that_collapses_early(
    live_greedy: LiveRun,
) -> None:
    recorded = record_episode(live_greedy.result)
    replay_bridge = GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )
    resolved_replay_plugin = _resolved_plugin(replay_bridge)

    replayed = asyncio.run(
        replay_episode(
            cell=live_greedy.cell,
            case=live_greedy.case,
            plugin=resolved_replay_plugin,
            recorded=recorded,
        )
    )

    comparison = compare_episode_results(live_greedy.result, replayed)
    assert comparison.matches is True
    assert replayed.terminal["num_round"] < 12  # collapsed well before the horizon
    assert replayed.terminal["resource_in_pool"] < 5


def test_replayed_episode_recomputes_all_five_leaves_matching_the_live_scores(
    live_sustainable: LiveRun,
) -> None:
    recorded = record_episode(live_sustainable.result)
    replay_bridge = GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )
    resolved_replay_plugin = _resolved_plugin(replay_bridge)
    replayed = asyncio.run(
        replay_episode(
            cell=live_sustainable.cell,
            case=live_sustainable.case,
            plugin=resolved_replay_plugin,
            recorded=recorded,
        )
    )

    scorer = m.build_scorer(dict(live_sustainable.case.payload))
    original_terminal = _plain(live_sustainable.result.terminal)
    baseline = _baseline_values(original_terminal, max_num_rounds=12)
    original_scores = scorer.score_all(
        terminal=original_terminal,
        baseline_survival_months=baseline["survival_months"],
        baseline_total_harvest=baseline["total_harvest"],
        baseline_gini=baseline["gini"],
    )

    replay_scores = score_replayed_episode(
        scorer=scorer,
        replayed=replayed,
        baseline_survival_months=baseline["survival_months"],
        baseline_total_harvest=baseline["total_harvest"],
        baseline_gini=baseline["gini"],
    )

    assert set(replay_scores.leaves) == set(original_scores)
    for estimand_id, original_envelope in original_scores.items():
        replay_envelope = replay_scores.leaves[estimand_id]
        assert replay_envelope.status == original_envelope.status
        if original_envelope.primary is None:
            assert replay_envelope.primary is None
        else:
            assert replay_envelope.primary.value == original_envelope.primary.value


def test_govsim_scorer_is_callable_through_the_real_finalizer_seam_on_a_live_outcome(
    live_sustainable: LiveRun,
) -> None:
    """The recorded-outcome seam, on a real episode's real recorded outcome.

    ``finalize_family_execution`` once executed
    ``plugin.build_scorer(family_case)(recorded_outcome, evidence_refs=...)``.
    It now passes a ``FamilyScoringInput`` and expects every declared leaf
    (issue #76), so that contract is ``__call__`` and this recorded-outcome
    path keeps its own name -- still exercised here on
    ``GovsimPlugin.outcome()``'s own output, produced by the REAL kernel
    scheduler (``run_episode``), never a synthetic dict.
    """
    scorer = m.build_scorer(dict(live_sustainable.case.payload))
    assert callable(scorer)

    score = scorer.score_recorded_outcome(
        live_sustainable.result.outcome, evidence_refs=("evt_outcome_0",)
    )

    assert score.status == "ok"
    assert score.leaf.leaf_id == m.SURVIVAL_MONTHS_LEAF_ID
    assert score.primary.value == 12.0  # full horizon, matches the golden above
    assert score.reference_values == {}
    assert "delta_vs_baseline" not in score.metrics
    assert score.evidence_refs == ("evt_outcome_0",)


def test_replay_and_verify_end_to_end_returns_a_matching_report(
    live_greedy: LiveRun,
) -> None:
    recorded = record_episode(live_greedy.result)
    replay_bridge = GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )
    resolved_replay_plugin = _resolved_plugin(replay_bridge)
    original_terminal = _plain(live_greedy.result.terminal)
    baseline = _baseline_values(original_terminal, max_num_rounds=12)
    scorer = m.build_scorer(dict(live_greedy.case.payload))

    report = asyncio.run(
        replay_and_verify(
            cell=live_greedy.cell,
            case=live_greedy.case,
            plugin=resolved_replay_plugin,
            scorer=scorer,
            recorded=recorded,
            baseline_survival_months=baseline["survival_months"],
            baseline_total_harvest=baseline["total_harvest"],
            baseline_gini=baseline["gini"],
            original=live_greedy.result,
        )
    )

    assert report.status == "match"
    assert report.comparison is not None
    assert report.comparison.matches is True
    assert report.comparison.final_state_matches is True
    assert report.scores.leaves[m.NO_COLLAPSE_ESTIMAND_ID].status == "ok"
    assert report.scores.leaves[m.NO_COLLAPSE_ESTIMAND_ID].primary.value == 0.0


def test_replay_and_verify_reports_not_comparable_when_no_original_is_supplied(
    live_greedy: LiveRun,
) -> None:
    """Closes triage Finding 2: ``replay_and_verify(..., original=None)``
    (this module's own documented "genuinely offline replay... no original
    run in memory" case) sets ``comparison=None``. Before the fix,
    ``ReplayReport.status`` returned ``"match"`` for every
    ``comparison is None`` case -- indistinguishable from a genuine,
    verified state-hash match against a real original. A caller that reads
    ``status == "match"`` to mean "compared against an original and agreed"
    would silently accept an UNCOMPARED replay as if it had.
    """
    recorded = record_episode(live_greedy.result)
    replay_bridge = GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )
    resolved_replay_plugin = _resolved_plugin(replay_bridge)
    original_terminal = _plain(live_greedy.result.terminal)
    baseline = _baseline_values(original_terminal, max_num_rounds=12)
    scorer = m.build_scorer(dict(live_greedy.case.payload))

    report = asyncio.run(
        replay_and_verify(
            cell=live_greedy.cell,
            case=live_greedy.case,
            plugin=resolved_replay_plugin,
            scorer=scorer,
            recorded=recorded,
            baseline_survival_months=baseline["survival_months"],
            baseline_total_harvest=baseline["total_harvest"],
            baseline_gini=baseline["gini"],
            # original omitted: no terminal state, outcome, phase hashes, or
            # final state is compared with any original execution.
        )
    )

    assert report.comparison is None
    assert report.status == "not_comparable"
    assert report.status != "match"


def test_replay_case_mismatch_raises_a_typed_replay_error(live_greedy: LiveRun) -> None:
    recorded = record_episode(live_greedy.result)
    wrong_case = RecordedEpisode(
        case_id="govsim.fishing.greedy.999", decisions=recorded.decisions
    )
    replay_bridge = GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )
    resolved_replay_plugin = _resolved_plugin(replay_bridge)

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(
                cell=live_greedy.cell,
                case=live_greedy.case,
                plugin=resolved_replay_plugin,
                recorded=wrong_case,
            )
        )


def test_replay_of_a_tampered_response_diverges_from_the_original_and_is_caught_by_comparison(
    live_sustainable: LiveRun,
) -> None:
    """``GovsimPlugin.step()`` has no external tool result to cross-check
    against a recorded response (unlike ``tau3_retail``'s ``step()``, which
    raises ``SchedulerContractError`` itself on a tampered tool result --
    see ``replay.py``'s module docstring): every call simply recomputes
    state from whatever action history it is given. A tampered response
    therefore replays without raising, but produces a genuinely different
    trajectory -- caught here at the comparison layer, not inside
    ``step()``."""
    # Tamper the LAST harvest decision (final round) with a small +1 delta:
    # late enough that it cannot shorten the episode (there is no later
    # round to collapse before), and small enough not to deplete the pool
    # outright -- this isolates "the recorded content differs" from "the
    # replay ran a different number of rounds" (a distinct failure mode,
    # also a typed ReplayError, exercised structurally by
    # ``test_recorded_response_source_enforces_ordering_and_reports_exhaustion``
    # above).
    recorded = record_episode(live_sustainable.result)
    tampered_decisions = list(recorded.decisions)
    for index in range(len(tampered_decisions) - 1, -1, -1):
        decision = tampered_decisions[index]
        if decision.phase_id == HARVEST_PHASE and decision.response.get("quantity", 0) > 0:
            tampered_decisions[index] = RecordedDecision(
                phase_id=decision.phase_id,
                seat_id=decision.seat_id,
                response={"quantity": int(decision.response["quantity"]) + 1},
            )
            break
    else:
        raise AssertionError("no harvest decision with a positive quantity to tamper with")
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    replay_bridge = GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )
    resolved_replay_plugin = _resolved_plugin(replay_bridge)

    replayed = asyncio.run(
        replay_episode(
            cell=live_sustainable.cell,
            case=live_sustainable.case,
            plugin=resolved_replay_plugin,
            recorded=tampered,
        )
    )

    comparison = compare_episode_results(live_sustainable.result, replayed)
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="diverged from the original run"):
        assert_replay_matches(comparison)


async def _malformed_first_harvest_response(request: Any) -> dict[str, Any]:
    """Answers the very FIRST ``harvest``-phase request with a value
    ``GovsimPlugin.parse_action`` itself rejects (a negative ``quantity``).

    ``HARVEST_PHASE`` is the case's first phase (``environment.py``'s
    ``phases()``) and runs in ``"simultaneous"`` mode, so this is the first
    request ``run_episode`` ever issues -- no fallback branch for later
    requests is needed, because the scheduler raises
    ``SchedulerContractError`` from inside ``_request_action`` as soon as
    this one invalid response is processed, before any further seat is
    asked (see ``scheduler.py``'s ``invalid_action_policy == "reject"``
    check).
    """
    assert request.phase_id == HARVEST_PHASE
    return {"quantity": -1}


def test_a_malformed_first_harvest_response_aborts_the_real_scheduler_with_a_reject_policy(
    bridge: GovsimBridge,
) -> None:
    """Closes review finding W2: the QC Gate 2 "invalid-unauthorized" golden
    (``tests/test_govsim_measurement.py``'s
    ``test_golden_invalid_unauthorized_rejected_before_any_bridge_call_no_credit``)
    calls ``GovsimPlugin.legal()`` directly and never drives ``run_episode``
    -- and, because the real scheduler only ever requests an action from a
    seat ``plugin.eligible_actors()`` already names (``run_episode``'s own
    ``actors = _eligible_actors(...)`` loop), a request from a seat OUTSIDE
    that set is not a path the scheduler itself can ever take for this
    family; there is no legitimate way to reproduce that exact golden
    end-to-end through ``run_episode``.

    What IS reachable, and is this family's own govsim-specific proof of the
    ``invalid_action_policy="reject"`` contract (spec section 4's
    "no credit earned" claim, generically covered only by
    ``tests/test_shared_runner_scheduler.py`` otherwise): a legitimately
    -requested seat answers with a value ``parse_action`` itself rejects.
    ``HARVEST_PHASE``'s ``invalid_action_policy="reject"`` (environment.py's
    ``phases()``) must abort the WHOLE episode through the real scheduler,
    never silently continue or score a zero.
    """
    case = _case("govsim.fishing.sustainable.0")
    cell = _cell(case, suffix="malformed_first_harvest")
    resolved_plugin = _resolved_plugin(bridge)

    with pytest.raises(SchedulerContractError, match="invalid action"):
        asyncio.run(
            run_episode(
                cell=cell,
                case=case,
                plugin=resolved_plugin,
                response_source=_malformed_first_harvest_response,
            )
        )
