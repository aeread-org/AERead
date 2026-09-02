"""Tests for the termsbench offline replayer (replay.py, spec sections 3.1, 5).

Self-contained (mirrors ``tests/test_tau3_retail_replay.py``'s own
convention of not importing another test module's helpers): builds its own
cell/harness/evidence around the same two real pilot cases exercised by
``tests/test_termsbench_harness.py``, then replays what those live runs
produced with **zero random draws and zero provider calls**.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import SchedulerContractError, run_episode
from aeread_families.termsbench.environment import TermsBenchPlugin, register_plugin
from aeread_families.termsbench.harness import ScriptedTermsBenchHarness
from aeread_families.termsbench.measurement import build_scorer
from aeread_families.termsbench.replay import (
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

PILOT_DIR = Path("cases/termsbench/pilot")
OVERLAP_CASE_ID = "termsbench.candid.overlap.1000001"
NODEAL_CASE_ID = "termsbench.candid.nodeal.1010011"


def _case(case_id: str) -> CaseManifest:
    path = PILOT_DIR / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_termsbench_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_termsbench_replay",
        suite_version="0.1.0",
        block_id="block_termsbench_replay",
        sampling_plan_id="sampling_termsbench_replay",
        analysis_plan_id="analysis_termsbench_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_termsbench_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"agent": "scripted_agent", "counterpart": "termsbench_counterpart_kernel_v1"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_live_overlap(tmp_path: Path, *, suffix: str):
    case = _case(OVERLAP_CASE_ID)
    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    cell = _cell(case, suffix=suffix)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_termsbench_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_termsbench_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    script = [
        {"decision": "offer", "price": r_b + 0.1 * (r_a - r_b), "message": "opening"},
        {"decision": "offer", "price": r_b + 0.4 * (r_a - r_b), "message": "moving closer"},
        {"decision": "accept", "price": None, "message": "deal"},
    ]
    draws = {
        1: {"u_accept": 0.9999999, "u_walkaway": 0.9999999, "opening_noise": 0.0, "sentiment_noise": 0.0},
        2: {"u_accept": 0.9999999, "u_walkaway": 0.9999999, "price_noise": 0.0, "sentiment_noise": 0.0},
    }
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, counterpart_draws_by_round=draws, evidence=evidence
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    evidence.seal()
    return case, cell, plugin, evidence, result


def _run_live_nodeal(tmp_path: Path, *, suffix: str):
    case = _case(NODEAL_CASE_ID)
    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    cell = _cell(case, suffix=suffix)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_termsbench_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_termsbench_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    lowball = max(0.0, r_b - 90.0)
    assert lowball < r_a
    script = [{"decision": "offer", "price": lowball, "message": "lowball"}] * 6
    draws = {round_k: {"u_accept": 0.999, "u_walkaway": 0.0} for round_k in range(1, 7)}
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, counterpart_draws_by_round=draws, evidence=evidence
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    evidence.seal()
    return case, cell, plugin, evidence, result


def _scorer_for(case: CaseManifest):
    plugin = TermsBenchPlugin()
    family_case = plugin.validate_payload(case.payload)
    return build_scorer(family_case)


# ---------------------------------------------------------------------------
# Pure, no live run: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id="agent_turn",
        seat_id="agent",
        response={"decision": "offer", "price": 110.0, "message": "hi", "n": (1, 2)},
    )
    episode = RecordedEpisode(case_id="termsbench.candid.overlap.1000001", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "agent_turn"
    assert restored.decisions[0].seat_id == "agent"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.decisions[0].response == {
        "decision": "offer",
        "price": 110.0,
        "message": "hi",
        "n": [1, 2],
    }


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id="agent_turn", seat_id="agent", response={"decision": "reject"}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "agent_turn"
        seat_id = "agent"

    response = asyncio.run(source(_Request()))
    assert response == {"decision": "reject"}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(
            phase_id="counterpart_turn", seat_id="counterpart", response={"resolved": "accept"}
        ),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "agent_turn"
        seat_id = "agent"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "agent_reject"},
        outcome={"termination_reason": "agent_reject"},
        final_state={"round": 1},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "timeout"},
        outcome={"termination_reason": "agent_reject"},
        final_state={"round": 1},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Live + replay: genuine offline replay of a live, draws-consuming episode.
# ---------------------------------------------------------------------------


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_overlap_run(
    tmp_path: Path,
) -> None:
    case, cell, plugin, evidence, original = _run_live_overlap(tmp_path, suffix="live")
    evidence.close()

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent plugin instance -- not the one that produced the
    # original run -- drives the replay.
    registry = PluginRegistry()
    replay_plugin = register_plugin(registry)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.state_hashes_match is True
    assert comparison.final_state_matches is True
    assert replayed.terminal["reason"] == "agent_accept"
    # Termsbench state carries no wall-clock/timestamp field, so replay is
    # genuinely byte-identical, not merely content-equivalent.
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )


def test_replayed_episode_recomputes_every_leaf_the_same_way(tmp_path: Path) -> None:
    case, cell, plugin, evidence, original = _run_live_overlap(tmp_path, suffix="score")
    evidence.close()
    recorded = record_episode(original)

    replayed = asyncio.run(replay_episode(cell=cell, case=case, plugin=plugin, recorded=recorded))
    scorer = _scorer_for(case)

    original_scores = score_replayed_episode(scorer=scorer, replayed=original)
    replayed_scores = score_replayed_episode(scorer=scorer, replayed=replayed)

    assert replayed_scores.surplus_efficiency.primary.value == pytest.approx(
        original_scores.surplus_efficiency.primary.value
    )
    assert replayed_scores.feasible_agreement.primary.value == 1.0
    assert replayed_scores.no_deal_agreement is None
    assert replayed_scores.protocol_compliance.primary.value == pytest.approx(
        original_scores.protocol_compliance.primary.value
    )


def test_replay_and_verify_end_to_end_returns_a_matching_report_for_the_nodeal_case(
    tmp_path: Path,
) -> None:
    case, cell, plugin, evidence, original = _run_live_nodeal(tmp_path, suffix="e2e")
    evidence.close()
    recorded = record_episode(original)
    scorer = _scorer_for(case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell, case=case, plugin=plugin, scorer=scorer, recorded=recorded, original=original
        )
    )

    assert report.status == "match"
    assert report.replayed.terminal["reason"] == "counterpart_walk_away"
    assert report.scores.no_deal_agreement.primary.value == 0.0
    assert report.scores.surplus_efficiency is None
    assert report.scores.feasible_agreement is None


def test_sealed_evidence_draws_match_the_recorded_response_draws(tmp_path: Path) -> None:
    """Ties the two milestone-3 claims together: what the harness sealed
    into EvidenceStore per round is exactly what record_episode/replay later
    replays from -- not two independently-plausible but divergent stories."""
    case, cell, plugin, evidence, original = _run_live_overlap(tmp_path, suffix="tie")

    reopened = EvidenceStore.audit_existing(tmp_path / "evidence_tie")
    sealed_draws_by_round = {}
    for event in reopened.read_events():
        if event.event_type == "termsbench_counterpart_draws":
            payload = reopened.read_event_payload(event)
            sealed_draws_by_round[payload["round"]] = payload["draws"]

    recorded = record_episode(original)
    counterpart_decisions = [d for d in recorded.decisions if d.phase_id == "counterpart_turn"]
    assert len(counterpart_decisions) == len(sealed_draws_by_round) == 2
    for decision in counterpart_decisions:
        round_k = decision.response["round"]
        assert dict(decision.response["draws"]) == sealed_draws_by_round[round_k]


def test_replay_raises_when_a_recorded_counterpart_draw_is_tampered_with(tmp_path: Path) -> None:
    """The draws-level replay guarantee: step() itself catches this, and
    replay_episode must not swallow it."""
    case, cell, plugin, evidence, original = _run_live_overlap(tmp_path, suffix="tamper")
    evidence.close()
    recorded = record_episode(original)

    tampered_decisions = list(recorded.decisions)
    for index, decision in enumerate(tampered_decisions):
        if decision.phase_id == "counterpart_turn":
            response = dict(decision.response)
            draws = dict(response["draws"])
            draws["u_accept"] = 0.0  # force a claimed-vs-recomputed mismatch
            response["draws"] = draws
            tampered_decisions[index] = RecordedDecision(
                phase_id=decision.phase_id, seat_id=decision.seat_id, response=response
            )
            break
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    with pytest.raises(SchedulerContractError, match="replay mismatch"):
        asyncio.run(replay_episode(cell=cell, case=case, plugin=plugin, recorded=tampered))


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    case, cell, plugin, evidence, original = _run_live_overlap(tmp_path, suffix="mismatch")
    evidence.close()
    recorded = record_episode(original)
    wrong_case = RecordedEpisode(
        case_id="termsbench.candid.overlap.999999999", decisions=recorded.decisions
    )

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(replay_episode(cell=cell, case=case, plugin=plugin, recorded=wrong_case))


def test_replay_raises_when_the_record_is_truncated(tmp_path: Path) -> None:
    """Dropping the final (agent-accept) decision leaves the replayed episode
    needing one more action than the record supplies. ``RecordedResponseSource``
    raises ``ReplayError("... exhausted ...")`` for that extra request, but
    ``run_episode`` wraps every response-source exception in
    ``SchedulerContractError`` (mirrors how the same wrapping surfaces the
    tamper case above) -- so this is the observable exception here, not a
    bare ``ReplayError``."""
    case, cell, plugin, evidence, original = _run_live_overlap(tmp_path, suffix="truncated")
    evidence.close()
    recorded = record_episode(original)
    truncated = RecordedEpisode(case_id=recorded.case_id, decisions=recorded.decisions[:-1])

    with pytest.raises(SchedulerContractError, match="exhausted"):
        asyncio.run(replay_episode(cell=cell, case=case, plugin=plugin, recorded=truncated))
