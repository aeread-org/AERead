"""End-to-end coverage for the negarena scripted harness and offline replayer
(spec section 5, milestone 3: "the tau3 ScriptedTau3RetailHarness/replay.py
pattern").

Unlike ``tests/test_negarena_environment.py`` (which drives
``NegarenaPlugin.parse_action``/``legal``/``step`` directly, a hand-wired
shortcut) and ``tests/test_negarena_parity.py`` (which reuses that same
hand-wired loop for its "adapter" side), every test in this module drives a
full episode through the REAL shared-runner scheduler
(``aeread.shared_runner.scheduler.run_episode``), via
``ScriptedNegarenaHarness`` as the response source, with a real
``EvidenceStore`` sealed at the end -- then proves an offline replay from
the recorded decision log alone reproduces the same state and the same
score, with zero further provider (model) calls.

Follows the same ``_bridge()``/skip convention as
``tests/test_negarena_environment.py``: bridge-dependent tests skip cleanly
when no provisioned bridge interpreter is available.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.negarena import parity
from aeread_families.negarena.cases import BLUE, RED
from aeread_families.negarena.environment import (
    BLUE_PHASE,
    RED_PHASE,
    NegarenaPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.negarena.harness import ScriptedNegarenaHarness
from aeread_families.negarena.negarena_bridge import NegarenaBridge
from aeread_families.negarena.replay import (
    RecordedEpisode,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    record_episode,
    replay_and_verify,
    replay_episode,
    score_replayed_episode,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = Path(
    os.environ.get(
        "AEREAD_NEGARENA_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-negarena",
    )
)

if not (UPSTREAM_ROOT / "negotiationarena").is_dir():
    pytest.skip(
        f"pinned upstream NegotiationArena checkout not found at {UPSTREAM_ROOT}",
        allow_module_level=True,
    )


def _bridge():
    from aeread_families.negarena.negarena_bridge import NegarenaBridgeUnavailableError

    try:
        return NegarenaBridge.discover(UPSTREAM_ROOT)
    except NegarenaBridgeUnavailableError as error:
        pytest.skip(f"upstream NegotiationArena Python interpreter unavailable: {error}")


@pytest.fixture(scope="module")
def bridge():
    return _bridge()


def _load_case(case_id: str, split: str) -> CaseManifest:
    path = REPO_ROOT / "cases" / "negarena" / split / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_negarena_harness_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_negarena_harness",
        suite_version="0.1.0",
        block_id="block_negarena_harness",
        sampling_plan_id="sampling_negarena_harness",
        analysis_plan_id="analysis_negarena_harness",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_negarena_harness_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {RED: "scripted_red", BLUE: "scripted_blue"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _script_from_transcript(
    transcript: parity.GoldenOneTranscript,
) -> list[tuple[str, str, dict[str, str]]]:
    """Turn a ``parity.GoldenOneTranscript`` into a scheduler-shaped script."""
    return [
        (RED_PHASE if seat_id == RED else BLUE_PHASE, seat_id, {"response": text})
        for seat_id, text in transcript.turns
    ]


def _run_live(bridge, tmp_path: Path, *, case: CaseManifest, transcript, suffix: str):
    cell = _cell(case, suffix=suffix)
    plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())

    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_negarena_harness_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_negarena_harness_{suffix}",
        episode_attempt_id="attempt_1",
    )
    scripted = ScriptedNegarenaHarness(
        evidence=evidence, script=_script_from_transcript(transcript)
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=scripted)
    )
    return cell, resolved_plugin, evidence, scripted, result


# ---------------------------------------------------------------------------
# Episode 1 -- buy_sell golden 1, through the real scheduler.
# ---------------------------------------------------------------------------


def test_buy_sell_golden_one_runs_end_to_end_through_the_real_scheduler(
    tmp_path: Path, bridge
) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    cell, resolved_plugin, evidence, scripted, result = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix="buy_sell"
    )

    assert scripted.exhausted is True
    assert result.logical_action_count == 8
    assert [instance.phase_id for instance in result.phase_instances] == [
        RED_PHASE,
        BLUE_PHASE,
        RED_PHASE,
        BLUE_PHASE,
        RED_PHASE,
        BLUE_PHASE,
        RED_PHASE,
        BLUE_PHASE,
    ]
    assert result.terminal["reason"] == "accepted"
    assert result.outcome["termination_reason"] == "accepted"

    scorer = resolved_plugin.build_scorer(family_case)
    red = scorer.score_seat_outcome(
        bridge=bridge,
        state=result.final_state,
        terminal=result.terminal,
        seat_id=RED,
        opponent_policy_id="scripted",
    )
    blue = scorer.score_seat_outcome(
        bridge=bridge,
        state=result.final_state,
        terminal=result.terminal,
        seat_id=BLUE,
        opponent_policy_id="scripted",
    )
    agreement = scorer.score_agreement_reached(terminal=result.terminal)
    assert red.status == "ok" and red.primary.value == 0.0
    assert blue.status == "ok" and blue.primary.value == 20.0
    assert agreement.status == "ok" and agreement.primary.value == 1.0

    # Sealed evidence: every served decision produced a durable event, and
    # the seal is stable (re-sealing an already-sealed store is idempotent
    # and verifiable) even after the store is closed and reopened.
    seal = evidence.seal()
    assert seal.event_count == result.logical_action_count
    evidence.close()
    reopened = EvidenceStore(
        evidence.root,
        run_plan_id=evidence.run_plan_id,
        cell_id=evidence.cell_id,
        episode_id=evidence.episode_id,
        episode_attempt_id=evidence.episode_attempt_id,
        resume=True,
    )
    try:
        reopened.verify_chain()
        assert reopened.verify_seal() == seal
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# Episode 2 -- ultimatum golden 1, through the real scheduler.
# ---------------------------------------------------------------------------


def test_ultimatum_golden_one_runs_end_to_end_through_the_real_scheduler(
    tmp_path: Path, bridge
) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = parity.build_ultimatum_golden_one(family_case)

    cell, resolved_plugin, evidence, scripted, result = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix="ultimatum"
    )

    assert scripted.exhausted is True
    assert result.logical_action_count == 2
    assert [instance.phase_id for instance in result.phase_instances] == [
        RED_PHASE,
        BLUE_PHASE,
    ]
    assert result.terminal["reason"] == "accepted"

    scorer = resolved_plugin.build_scorer(family_case)
    red = scorer.score_seat_outcome(
        bridge=bridge,
        state=result.final_state,
        terminal=result.terminal,
        seat_id=RED,
        opponent_policy_id="scripted",
    )
    blue = scorer.score_seat_outcome(
        bridge=bridge,
        state=result.final_state,
        terminal=result.terminal,
        seat_id=BLUE,
        opponent_policy_id="scripted",
    )
    assert red.status == "ok" and red.primary.value == 60.0
    assert blue.status == "ok" and blue.primary.value == 40.0

    seal = evidence.seal()
    assert seal.event_count == result.logical_action_count == len(evidence.read_events())


# ---------------------------------------------------------------------------
# Replay -- zero provider calls, byte-identical state + score.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case_id", "split", "build_transcript", "suffix"),
    [
        ("negarena.buy_sell.0", "buy_sell", parity.build_buy_sell_golden_one, "buy_sell"),
        ("negarena.ultimatum.0", "ultimatum", parity.build_ultimatum_golden_one, "ultimatum"),
    ],
)
def test_replay_reproduces_state_and_score_byte_identically(
    tmp_path: Path, bridge, case_id, split, build_transcript, suffix
) -> None:
    case = _load_case(case_id, split)
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = build_transcript(family_case)

    cell, resolved_plugin, evidence, scripted, original = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix=f"{suffix}_original"
    )
    assert scripted.exhausted is True

    recorded = record_episode(original, case=case, cell=cell)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent bridge/plugin -- not the one that produced the
    # original run -- drives the replay. No model/provider is ever involved
    # for either side; ``RecordedResponseSource`` makes no call at all.
    replay_bridge = NegarenaBridge.discover(UPSTREAM_ROOT)
    replay_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=replay_bridge)
    replay_registry = PluginRegistry()
    register_plugin(replay_registry, plugin=replay_plugin)
    resolved_replay_plugin = replay_registry.resolve_manifest(family_manifest())

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert_replay_matches(comparison)
    assert comparison.matches is True
    assert canonical_json_bytes(original.final_state) == canonical_json_bytes(
        replayed.final_state
    )
    assert canonical_json_bytes(original.terminal) == canonical_json_bytes(replayed.terminal)
    assert canonical_json_bytes(original.outcome) == canonical_json_bytes(replayed.outcome)

    scorer = resolved_plugin.build_scorer(family_case)
    original_scores = score_replayed_episode(bridge=bridge, scorer=scorer, replayed=original)
    replayed_scores = score_replayed_episode(
        bridge=replay_bridge, scorer=scorer, replayed=replayed
    )

    assert canonical_json_bytes(original_scores.red_outcome) == canonical_json_bytes(
        replayed_scores.red_outcome
    )
    assert canonical_json_bytes(original_scores.blue_outcome) == canonical_json_bytes(
        replayed_scores.blue_outcome
    )
    assert canonical_json_bytes(original_scores.agreement) == canonical_json_bytes(
        replayed_scores.agreement
    )


def test_replay_rejects_a_case_with_the_same_case_id_but_different_content(
    tmp_path: Path, bridge
) -> None:
    """docs/negarena_codex_triage.md Finding 2: a ``RecordedEpisode`` binds
    the case it was produced from by content hash, not just ``case_id`` --
    a case can be re-authored (different valuation, different upstream pin)
    while keeping the same ``case_id``. Drives ``replay_episode`` itself
    (the production replay entry point every other test in this module also
    calls), never a hand-wired shortcut around it."""
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    cell, resolved_plugin, evidence, scripted, original = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix="case_mismatch"
    )
    recorded = record_episode(original, case=case, cell=cell)

    # Same case_id, different content -- the "re-authored case" scenario the
    # finding describes.
    reauthored_case = dataclasses.replace(case, content_sha256="f" * 64)
    assert reauthored_case.case_id == case.case_id
    assert reauthored_case.content_sha256 != case.content_sha256

    # The cell's own case_sha256 is rewritten to match the re-authored case,
    # so the scheduler's own case/cell agreement check (_validate_cell_case)
    # would accept this (case, cell) pair on its own -- only replay_episode's
    # sealed-recording check can catch that it is not the original execution.
    reauthored_cell = dataclasses.replace(
        cell, case_sha256=reauthored_case.content_sha256
    )

    with pytest.raises(ReplayError, match="different case body"):
        asyncio.run(
            replay_episode(
                cell=reauthored_cell,
                case=reauthored_case,
                plugin=resolved_plugin,
                recorded=recorded,
            )
        )


def test_replay_rejects_a_cell_with_a_different_opponent_profile(
    tmp_path: Path, bridge
) -> None:
    """Same finding, the other half: a cell rebuilt with a different
    ``profile_by_seat`` (a different opponent) can still agree with the
    original ``case`` (same ``case_sha256``) while pairing the recorded seat
    against an opponent it never actually played. ``replay_episode`` must
    reject that too, not just a case-content mismatch."""
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    cell, resolved_plugin, evidence, scripted, original = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix="cell_mismatch"
    )
    recorded = record_episode(original, case=case, cell=cell)

    different_opponent_cell = dataclasses.replace(
        cell,
        profile_by_seat=MappingProxyType(
            {RED: "scripted_red", BLUE: "a_completely_different_opponent"}
        ),
    )
    # Still agrees with `case` on its own -- only the cell content itself
    # (profile_by_seat) differs from the one that produced the recording.
    assert different_opponent_cell.case_sha256 == cell.case_sha256

    with pytest.raises(ReplayError, match="different cell"):
        asyncio.run(
            replay_episode(
                cell=different_opponent_cell,
                case=case,
                plugin=resolved_plugin,
                recorded=recorded,
            )
        )


def test_record_episode_rejects_a_cell_that_did_not_produce_the_result(
    tmp_path: Path, bridge
) -> None:
    """docs/negarena_fix_verification.md Finding 2 (remaining gap):
    ``record_episode`` validated ``case.case_id == result.case_id`` but never
    ``cell.cell_id == result.cell_id`` -- a caller could seal a recording's
    ``cell_sha256`` from an entirely different cell than the one that
    actually produced ``result``. Neither record time nor replay time ever
    caught that on its own: replay only ever compares the sealed
    ``cell_sha256`` against whatever cell a *later* caller happens to supply,
    so a consistently-wrong cell supplied at both record and replay time
    would never be caught at all."""
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    cell, resolved_plugin, evidence, scripted, original = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix="record_cell_mismatch"
    )

    wrong_cell = dataclasses.replace(cell, cell_id=f"{cell.cell_id}_a_different_cell")
    assert wrong_cell.cell_id != original.cell_id

    with pytest.raises(ReplayError, match="does not match the episode's own cell"):
        record_episode(original, case=case, cell=wrong_cell)


def test_replay_and_verify_ties_replay_comparison_and_scoring_together(
    tmp_path: Path, bridge
) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    cell, resolved_plugin, evidence, scripted, original = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix="verify"
    )
    recorded = record_episode(original, case=case, cell=cell)
    scorer = resolved_plugin.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            bridge=bridge,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.comparison is not None and report.comparison.matches
    assert report.scores.red_outcome.primary.value == 0.0
    assert report.scores.blue_outcome.primary.value == 20.0
    assert report.scores.agreement.primary.value == 1.0

    # Without an ``original`` supplied, replay still runs and re-scores;
    # comparison is an explicit "not comparable", never a fabricated match
    # (docs/negarena_codex_triage.md Finding 4: no equality check ever ran
    # here, so ``status`` must not report "match" for it).
    report_no_original = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            bridge=bridge,
            scorer=scorer,
            recorded=recorded,
        )
    )
    assert report_no_original.comparison is None
    assert report_no_original.status == "not_compared"
    assert report_no_original.status != "match"


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    """Pure, no bridge/episode required (mirrors
    ``tau3_retail``'s identical structural test): ``RecordedResponseSource``
    itself refuses to serve a decision out of order rather than silently
    proceeding."""
    from aeread_families.negarena.replay import RecordedDecision, RecordedResponseSource

    decisions = (
        RecordedDecision(
            phase_id="blue_turn", seat_id="blue", response={"response": "x"}
        ),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "red_turn"
        seat_id = "red"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_replay_report_status_is_not_compared_when_no_comparison_was_made() -> None:
    """Pure, no bridge/episode required: ``ReplayReport.status`` must not
    report ``"match"`` for a comparison that never actually ran
    (docs/negarena_codex_triage.md Finding 4) -- a caller reading only
    ``status`` (never ``comparison`` itself) must be able to tell "verified
    identical" apart from "never compared"."""
    from aeread.shared_runner.scheduler import EpisodeResult
    from aeread_families.negarena.replay import ReplayReport, ReplayScoreResult

    fake_episode = EpisodeResult(
        episode_id="episode_x",
        cell_id="cell_x",
        case_id="case_x",
        family_id="negarena",
        final_state={},
        terminal={},
        outcome={},
        logical_action_count=0,
        phase_instances=(),
    )
    fake_scores = ReplayScoreResult(red_outcome=None, blue_outcome=None, agreement=None)

    report = ReplayReport(
        case_id="case_x", replayed=fake_episode, comparison=None, scores=fake_scores
    )
    assert report.status == "not_compared"
    assert report.status != "match"


def test_replay_of_a_reordered_recording_surfaces_as_a_scheduler_contract_error(
    tmp_path: Path, bridge
) -> None:
    """The same mismatch, this time surfacing through the real scheduler:
    ``run_episode`` wraps every ``response_source`` failure in
    ``SchedulerContractError`` (spec's own "left to propagate unmodified"
    only applies to hooks the family itself owns, not to the scheduler's
    generic response-source boundary) -- the underlying ``ReplayError``
    text is still present, never swallowed."""
    from aeread.shared_runner.scheduler import SchedulerContractError

    case = _load_case("negarena.buy_sell.0", "buy_sell")
    setup_plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = setup_plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    cell, resolved_plugin, evidence, scripted, original = _run_live(
        bridge, tmp_path, case=case, transcript=transcript, suffix="reorder"
    )
    recorded = record_episode(original, case=case, cell=cell)
    # Drop the first decision -- the replay must reject the resulting
    # phase/seat mismatch rather than silently proceed.
    tampered = RecordedEpisode(
        case_id=recorded.case_id,
        case_sha256=recorded.case_sha256,
        cell_sha256=recorded.cell_sha256,
        decisions=recorded.decisions[1:],
    )

    with pytest.raises(SchedulerContractError, match="does not match"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=tampered)
        )
