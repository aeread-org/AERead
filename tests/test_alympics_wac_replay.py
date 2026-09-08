"""Tests for the alympics.wac offline replayer (replay.py, spec section 5's
"Replay" test-plan bullet).

Follows the same skip convention as ``tests/test_alympics_wac_environment.py``
and ``tests/test_alympics_wac_harness.py``: pure, structural tests
(``RecordedDecision``/``RecordedEpisode`` round-tripping, ordering
enforcement, comparison reporting) run everywhere; tests that actually
replay a full episode against the pinned upstream checkout run for real
when it is present, and are skipped (never faked) otherwise.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import SchedulerContractError, run_episode
from aeread_families.alympics_wac.cases import SEAT_ORDER
from aeread_families.alympics_wac.environment import AlympicsWacPlugin
from aeread_families.alympics_wac.harness import (
    ScriptedAlympicsWacHarness,
    baseline_policy_assignment,
)
from aeread_families.alympics_wac.replay import (
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


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ALYMPICS_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-alympics",
    )
    root = Path(candidate)
    marker = root / "src" / "waterAllocation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream Alympics checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/alympics_wac/base")


def _case(name: str) -> CaseManifest:
    path = CASES_DIR / f"alympics.wac.{name}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_alympics_wac_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_alympics_wac_replay",
        suite_version="0.1.0",
        block_id="block_alympics_wac_replay",
        sampling_plan_id="sampling_alympics_wac_replay",
        analysis_plan_id="analysis_alympics_wac_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_alympics_wac_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {
                seat: f"scripted_{policy}"
                for seat, policy in case.payload["grid_cell"]["policy_assignment"].items()
            }
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Path, *, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_alympics_wac_replay_{suffix}",
        cell_id=f"cell_alympics_wac_replay_{suffix}",
        episode_id=f"episode_alympics_wac_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )


def _run_live(case: CaseManifest, tmp_path: Path, *, suffix: str):
    cell = _cell(case, suffix=suffix)
    plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    evidence = _evidence(tmp_path, suffix=suffix)
    policy_assignment = dict(case.payload["grid_cell"]["policy_assignment"])
    harness = ScriptedAlympicsWacHarness(policy_assignment=policy_assignment, evidence=evidence)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    evidence.seal()
    return cell, plugin, result, policy_assignment


# ---------------------------------------------------------------------------
# Pure, no upstream: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(phase_id="bid", seat_id="alex", response={"bid": 24})
    episode = RecordedEpisode(case_id="alympics.wac.reference_baseline", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "bid"
    assert restored.decisions[0].seat_id == "alex"
    assert restored.decisions[0].response == {"bid": 24}


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (RecordedDecision(phase_id="bid", seat_id="alex", response={"bid": 24}),)
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "bid"
        seat_id = "alex"

    response = asyncio.run(source(_Request()))
    assert response == {"bid": 24}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (RecordedDecision(phase_id="bid", seat_id="bob", response={"bid": 27}),)
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "bid"
        seat_id = "alex"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "rounds_exhausted", "round_id": 20},
        outcome={"termination_reason": "rounds_exhausted"},
        final_state={"players": {}, "round_log": ()},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "all_seats_eliminated", "round_id": 4},
        outcome={"termination_reason": "rounds_exhausted"},
        final_state={"players": {}, "round_log": ()},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


def test_replay_case_mismatch_raises_a_typed_replay_error_without_running_anything() -> None:
    decisions = (RecordedDecision(phase_id="bid", seat_id="alex", response={"bid": 24}),)
    wrong_case = RecordedEpisode(case_id="alympics.wac.does_not_exist", decisions=decisions)
    case = _case("reference_baseline")
    cell = _cell(case, suffix="mismatch_pure")
    plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=plugin, recorded=wrong_case)
        )


# ---------------------------------------------------------------------------
# Upstream-gated: genuine offline replay of a live, fully-scripted episode.
# ---------------------------------------------------------------------------


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run_byte_identically(
    tmp_path: Path,
) -> None:
    case = _case("reference_baseline")
    cell, original_plugin, original, _ = _run_live(case, tmp_path, suffix="live")

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id
    assert len(recorded.decisions) == original.logical_action_count

    # A second, independent plugin -- not the one that produced the
    # original run -- drives the replay.
    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    # Unlike tau3_retail (whose per-message wall-clock timestamp never
    # survives two independent runs identically), this family's state
    # carries no such field: the replayed state is expected to be exactly
    # byte-identical to the original, not merely content-equivalent.
    assert comparison.final_state_matches is True
    assert comparison.state_hashes_match is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )
    assert replayed.terminal["reason"] == "rounds_exhausted"
    assert_replay_matches(comparison)  # never raises


def test_replay_reproduces_a_mid_game_elimination_episode_byte_identically(
    tmp_path: Path,
) -> None:
    case = _case("mixed_policies_a")
    cell, original_plugin, original, _ = _run_live(case, tmp_path, suffix="mixed_live")
    recorded = RecordedEpisode.from_json(record_episode(original).to_json())

    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.final_state_matches is True
    assert replayed.final_state["eliminated_order"] == original.final_state["eliminated_order"]


def test_replay_raises_when_recorded_decisions_run_out_early(tmp_path: Path) -> None:
    case = _case("reference_baseline")
    cell, _plugin, original, _ = _run_live(case, tmp_path, suffix="truncated")
    recorded = record_episode(original)
    truncated = RecordedEpisode(
        case_id=recorded.case_id, decisions=recorded.decisions[:-1]
    )

    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    # The missing decision is discovered *inside* the response_source
    # callback, mid-episode -- the scheduler itself wraps any response-
    # source exception as SchedulerContractError (scheduler.py's
    # `_request_action`), so the ReplayError this module raises surfaces
    # here as that exception's cause, not directly.
    with pytest.raises(SchedulerContractError, match="exhausted"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=truncated)
        )


def test_replay_detects_a_tampered_bid_only_via_comparison_against_the_original(
    tmp_path: Path,
) -> None:
    """Known, honest limit (see docs/alympics_adapter_status.md): unlike
    tau3_retail's tool-level re-execution, replay_episode itself has no
    independent oracle to catch a tampered recorded bid -- it faithfully
    replays whatever the record says and settles it exactly like a live
    run would. The only place a tamper becomes visible is
    ``compare_episode_results`` against the original run."""
    case = _case("reference_baseline")
    cell, _plugin, original, _ = _run_live(case, tmp_path, suffix="tamper")
    recorded = record_episode(original)

    tampered_decisions = list(recorded.decisions)
    first = tampered_decisions[0]
    assert first.response["bid"] != 999
    tampered_decisions[0] = RecordedDecision(
        phase_id=first.phase_id, seat_id=first.seat_id, response={"bid": 999}
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=tampered)
    )

    # replay_episode itself never raised -- the tamper only surfaces here.
    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is False
    assert comparison.final_state_matches is False
    with pytest.raises(ReplayError, match="final state differs"):
        assert_replay_matches(comparison)


def test_replayed_episode_recomputes_all_four_leaves_using_a_replayed_baseline(
    tmp_path: Path,
) -> None:
    case = _case("mixed_policies_a")
    cell, plugin, original, policy_assignment = _run_live(
        case, tmp_path, suffix="score_actual"
    )
    recorded = record_episode(original)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=plugin, recorded=recorded)
    )

    focal_seat = "alex"
    baseline_assignment = baseline_policy_assignment(policy_assignment, focal_seat=focal_seat)
    baseline_evidence = _evidence(tmp_path, suffix="score_baseline")
    baseline_harness = ScriptedAlympicsWacHarness(
        policy_assignment=baseline_assignment, evidence=baseline_evidence
    )
    baseline_cell = _cell(case, suffix="score_baseline")
    baseline_original = asyncio.run(
        run_episode(
            cell=baseline_cell, case=case, plugin=plugin, response_source=baseline_harness
        )
    )
    baseline_recorded = record_episode(baseline_original)
    baseline_replayed = asyncio.run(
        replay_episode(
            cell=baseline_cell, case=case, plugin=plugin, recorded=baseline_recorded
        )
    )

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    upstream_module = plugin._require_upstream()

    scores = score_replayed_episode(
        scorer=scorer,
        upstream_module=upstream_module,
        focal_seat=focal_seat,
        replayed=replayed,
        baseline_final_players=baseline_replayed.final_state["players"],
        baseline_round_log=baseline_replayed.final_state["round_log"],
    )

    assert scores.bid_legality.status == "ok"
    assert scores.settlement_exactness.status == "ok"
    assert scores.terminal_wealth.status == "ok"
    assert scores.survival.status == "ok"
    # alex ("aggressive") is the sole round-15 survivor in the actual run;
    # under baseline "proportional" (holding the rest of the panel fixed)
    # its own outcome is expected to differ -- never asserted as "better",
    # per P01's baseline_only verdict (spec section 6).
    actual_wealth = replayed.final_state["players"][focal_seat]["balance"]
    baseline_wealth = baseline_replayed.final_state["players"][focal_seat]["balance"]
    assert scores.terminal_wealth.primary.value == actual_wealth - baseline_wealth


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    case = _case("reference_baseline")
    cell, plugin, original, policy_assignment = _run_live(case, tmp_path, suffix="e2e")
    recorded = record_episode(original)

    focal_seat = "alex"
    # reference_baseline is already all-"proportional", so the baseline run
    # for its own focal seat is the identical policy assignment -- the
    # comparative delta is expected to be exactly zero.
    baseline_assignment = baseline_policy_assignment(policy_assignment, focal_seat=focal_seat)
    assert baseline_assignment == policy_assignment
    baseline_evidence = _evidence(tmp_path, suffix="e2e_baseline")
    baseline_harness = ScriptedAlympicsWacHarness(
        policy_assignment=baseline_assignment, evidence=baseline_evidence
    )
    baseline_cell = _cell(case, suffix="e2e_baseline")
    baseline_original = asyncio.run(
        run_episode(
            cell=baseline_cell, case=case, plugin=plugin, response_source=baseline_harness
        )
    )

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    upstream_module = plugin._require_upstream()

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=plugin,
            scorer=scorer,
            upstream_module=upstream_module,
            focal_seat=focal_seat,
            recorded=recorded,
            baseline_final_players=baseline_original.final_state["players"],
            baseline_round_log=baseline_original.final_state["round_log"],
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.terminal_wealth.status == "ok"
    assert report.scores.terminal_wealth.primary.value == 0.0
    assert report.scores.survival.status == "ok"
    assert report.scores.survival.primary.value == 0.0


def test_replay_and_verify_with_no_original_in_memory_never_fabricates_a_match(
    tmp_path: Path,
) -> None:
    """Codex triage finding 5: this module's own docstring names
    ``original=None`` as a real, intended mode -- "a genuinely offline
    replay from a previously-written record, with no original run in
    memory" -- but ``ReplayReport.status`` used to collapse that ``None``
    comparison (nothing was ever compared) into the exact same string,
    ``"match"``, a genuinely verified state-hash-level agreement would
    produce. This exercises exactly that documented, intended usage (never
    passing ``original``, the way a real offline-replay operator would)
    through the real production ``replay_and_verify`` function."""
    case = _case("reference_baseline")
    cell, plugin, original, policy_assignment = _run_live(case, tmp_path, suffix="no_original")
    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text, mirroring a real
    # "loaded from disk, no original run in memory" operator flow.
    recorded = RecordedEpisode.from_json(recorded.to_json())

    focal_seat = "alex"
    baseline_assignment = baseline_policy_assignment(policy_assignment, focal_seat=focal_seat)
    baseline_evidence = _evidence(tmp_path, suffix="no_original_baseline")
    baseline_harness = ScriptedAlympicsWacHarness(
        policy_assignment=baseline_assignment, evidence=baseline_evidence
    )
    baseline_cell = _cell(case, suffix="no_original_baseline")
    baseline_original = asyncio.run(
        run_episode(
            cell=baseline_cell, case=case, plugin=plugin, response_source=baseline_harness
        )
    )

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    upstream_module = plugin._require_upstream()

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=plugin,
            scorer=scorer,
            upstream_module=upstream_module,
            focal_seat=focal_seat,
            recorded=recorded,
            baseline_final_players=baseline_original.final_state["players"],
            baseline_round_log=baseline_original.final_state["round_log"],
            # `original` deliberately omitted -- the documented "no original
            # run in memory" offline-replay mode.
        )
    )

    assert report.comparison is None
    assert report.status != "match"
    assert report.status == "not_compared"
    # Re-scoring the replayed episode from its own state still works --
    # only the *comparison* is unavailable, never the scoring.
    assert report.scores.terminal_wealth.status == "ok"
