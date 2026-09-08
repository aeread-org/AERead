"""Tests for the steer offline replayer (replay.py, docs/steer_adapter_spec.md
section 5, "Offline replay").

Structural tests (``RecordedDecision``/``RecordedEpisode`` round-tripping,
``RecordedResponseSource`` ordering/exhaustion, ``compare_episode_results``'s
synthetic-mismatch reporting, and the case-mismatch guard) need no built
corpus and run everywhere. The tests that actually replay a sealed episode
recorded through ``ScriptedSteerHarness`` need the flattened cache
milestone 1 built and are skipped, never faked, otherwise -- mirrors the
``_cache_root()`` skip convention already used by
``tests/test_steer_environment.py``/``tests/test_steer_goldens.py``.

Network is disabled and no bridge subprocess is spawned anywhere in this
module: ``SteerPlugin`` reads only the locally-cached flattened JSON,
never pandas.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.steer import cases as steer_cases
from aeread_families.steer.environment import SteerPlugin
from aeread_families.steer.harness import ScriptedSteerHarness
from aeread_families.steer.replay import (
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


def _cache_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_STEER_DATA_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/bridges/steer-data",
    )
    root = Path(candidate)
    marker = root / "transitivity" / "cases.jsonl"
    if not marker.is_file():
        pytest.skip(
            f"flattened cache not built yet at {root}; run "
            "src/aeread_families/steer/cases.py first",
            allow_module_level=True,
        )
    return root


CACHE_ROOT = _cache_root()
CASES_DIR = Path(__file__).resolve().parents[1] / "cases" / "steer"


def _first_admitted_row(element: str) -> dict:
    path = CACHE_ROOT / element / "cases.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        return json.loads(handle.readline())


def _case(element: str, question_id: str) -> CaseManifest:
    branch = steer_cases.BRANCH_BY_ELEMENT[element]
    path = CASES_DIR / branch / f"steer.{element}.{question_id}.json"
    if not path.is_file():
        pytest.skip(f"case file not built yet at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_steer_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_steer_replay",
        suite_version="0.1.0",
        block_id="block_steer_replay",
        sampling_plan_id="sampling_steer_replay",
        analysis_plan_id="analysis_steer_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_steer_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"agent": "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_original(case: CaseManifest, cell: PlanCell, respond_text: str, *, tmp_path: Path, suffix: str):
    """Run one live, sealed episode through the real harness/scheduler path."""
    plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_steer_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_steer_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedSteerHarness(evidence=evidence, script=[("answer_question", respond_text)])
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    evidence.seal()
    evidence.close()
    return plugin, result


# ---------------------------------------------------------------------------
# Pure, no cache: RecordedDecision/RecordedEpisode round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_a_plain_string_response_through_json() -> None:
    decision = RecordedDecision(
        phase_id="answer_question", seat_id="agent", response='{"option_id": 1}'
    )
    episode = RecordedEpisode(case_id="steer.transitivity.412_0", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "answer_question"
    assert restored.decisions[0].seat_id == "agent"
    assert restored.decisions[0].response == '{"option_id": 1}'


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(
            phase_id="answer_question", seat_id="agent", response='{"option_id": 0}'
        ),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "answer_question"
        seat_id = "agent"

    response = asyncio.run(source(_Request()))
    assert response == '{"option_id": 0}'
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(
            phase_id="answer_question", seat_id="agent", response='{"option_id": 0}'
        ),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "some_other_phase"
        seat_id = "agent"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "answered"},
        outcome={"termination_reason": "answered", "selected_option_id": 0},
        final_state={"termination": "answered", "selected_option_id": 0},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "error"},
        outcome={"termination_reason": "answered", "selected_option_id": 0},
        final_state={"termination": "answered", "selected_option_id": 0},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


def test_replay_case_mismatch_raises_a_typed_replay_error_before_touching_the_plugin() -> None:
    """The case-id guard fires before any plugin/scheduler call -- ``plugin``
    is never dereferenced, mirroring
    ``tests/test_tau3_retail_parity.py``'s identical "never touch the bridge
    for a failure that happens before it" convention."""
    fake_case = SimpleNamespace(case_id="steer.transitivity.999_0")
    wrong_recorded = RecordedEpisode(case_id="steer.transitivity.000_0", decisions=())

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=None, case=fake_case, plugin=None, recorded=wrong_recorded)
        )


# ---------------------------------------------------------------------------
# Cache-gated: genuine offline replay of a live, harness-driven episode.
# ---------------------------------------------------------------------------


def test_replay_reproduces_golden_1_successful_state_and_score_byte_identically(
    tmp_path: Path,
) -> None:
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="golden1")
    respond_text = json.dumps({"option_id": row["correct_option_id"]})

    plugin, original = _run_original(case, cell, respond_text, tmp_path=tmp_path, suffix="golden1")
    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent plugin instance -- not the one that produced the
    # original run -- drives the replay.
    replay_plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    # The genuine byte-exact claim spec section 5 asks for -- stronger than
    # tau3.retail's own replay guarantee, since this family's state carries
    # no wall-clock timestamp (replay.py's module docstring).
    assert comparison.final_state_matches is True
    assert canonical_json_bytes(original.final_state) == canonical_json_bytes(
        replayed.final_state
    )
    assert replayed.terminal["reason"] == "answered"

    family_case = replay_plugin.validate_payload(case.payload)
    scorer = replay_plugin.build_scorer(family_case)
    replayed_score = score_replayed_episode(scorer=scorer, replayed=replayed)
    original_score = plugin.build_scorer(plugin.validate_payload(case.payload)).score(
        original.outcome
    )
    assert replayed_score.status == original_score.status == "ok"
    assert replayed_score.primary.value == original_score.primary.value == 1.0


def test_replay_reproduces_golden_2_valid_but_poor_state_and_score(tmp_path: Path) -> None:
    element = "plurality_voting"
    row = _first_admitted_row(element)
    wrong_option_id = (row["correct_option_id"] + 1) % len(row["options"])
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="golden2")
    respond_text = json.dumps({"option_id": wrong_option_id})

    plugin, original = _run_original(case, cell, respond_text, tmp_path=tmp_path, suffix="golden2")
    recorded = RecordedEpisode.from_json(record_episode(original).to_json())

    replay_plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True

    scorer = replay_plugin.build_scorer(replay_plugin.validate_payload(case.payload))
    replayed_score = score_replayed_episode(scorer=scorer, replayed=replayed)
    assert replayed_score.status == "ok"
    assert replayed_score.primary.value == 0.0


def test_replay_reproduces_golden_3_invalid_unauthorized_as_typed_invalidity(
    tmp_path: Path,
) -> None:
    element = "borda_count"
    row = _first_admitted_row(element)
    out_of_range_option_id = len(row["options"])
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="golden3")
    respond_text = json.dumps({"option_id": out_of_range_option_id})

    plugin, original = _run_original(case, cell, respond_text, tmp_path=tmp_path, suffix="golden3")
    recorded = RecordedEpisode.from_json(record_episode(original).to_json())

    replay_plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert replayed.outcome["failure_code"] == "option_id_out_of_range"

    scorer = replay_plugin.build_scorer(replay_plugin.validate_payload(case.payload))
    replayed_score = score_replayed_episode(scorer=scorer, replayed=replayed)
    assert replayed_score.status == "invalid_measurement"
    assert replayed_score.primary is None


def test_replay_reproduces_golden_4_malformed_operational_as_typed_invalidity(
    tmp_path: Path,
) -> None:
    element = "ir_mechanism"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="golden4")
    respond_text = "I believe the correct answer is the second option."

    plugin, original = _run_original(case, cell, respond_text, tmp_path=tmp_path, suffix="golden4")
    recorded = RecordedEpisode.from_json(record_episode(original).to_json())

    replay_plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert replayed.outcome["failure_code"] == "malformed_answer_json"

    scorer = replay_plugin.build_scorer(replay_plugin.validate_payload(case.payload))
    replayed_score = score_replayed_episode(scorer=scorer, replayed=replayed)
    assert replayed_score.status == "invalid_measurement"
    assert replayed_score.validity.reasons == ("malformed_answer_json",)


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="e2e")
    respond_text = json.dumps({"option_id": row["correct_option_id"]})

    plugin, original = _run_original(case, cell, respond_text, tmp_path=tmp_path, suffix="e2e")
    recorded = record_episode(original)
    scorer = plugin.build_scorer(plugin.validate_payload(case.payload))

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.score.primary.value == 1.0
    assert report.case_id == case.case_id


def test_replay_and_verify_with_no_original_is_still_scored_but_not_compared(
    tmp_path: Path,
) -> None:
    """A genuinely offline replay -- no live run in memory, only the record --
    still runs and re-scores; ``comparison`` is an explicit ``None``, never a
    fabricated match."""
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="offline")
    respond_text = json.dumps({"option_id": row["correct_option_id"]})

    plugin, original = _run_original(case, cell, respond_text, tmp_path=tmp_path, suffix="offline")
    recorded = RecordedEpisode.from_json(record_episode(original).to_json())
    scorer = plugin.build_scorer(plugin.validate_payload(case.payload))

    report = asyncio.run(
        replay_and_verify(cell=cell, case=case, plugin=plugin, scorer=scorer, recorded=recorded)
    )

    assert report.comparison is None
    # Finding 3 (docs/steer_codex_triage.md): a replay never compared against
    # a live run must never report "match" -- that is an authenticated claim
    # ("this replay agreed with a real original run"), not merely the
    # absence of a disagreement. "not_compared" is the explicit, typed
    # third state; see
    # test_replay_report_status_distinguishes_an_uncompared_replay_from_a_verified_match
    # below for the direct regression coverage.
    assert report.status == "not_compared"
    assert report.score.primary.value == 1.0


def test_replay_report_status_distinguishes_an_uncompared_replay_from_a_verified_match(
    tmp_path: Path,
) -> None:
    """Finding 3 (docs/steer_codex_triage.md): before this fix,
    ``ReplayReport.status`` returned ``"match"`` whenever ``comparison`` was
    ``None`` -- exactly the same value a genuinely-compared, genuinely
    matching replay reports. A caller that gates on ``status == "match"``
    (this family's own sibling ``tau3_retail.parity`` does exactly that)
    could not tell "verified against a live run" from "never compared at
    all." The two must never collapse to the same status.
    """
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="status_distinct")
    respond_text = json.dumps({"option_id": row["correct_option_id"]})

    plugin, original = _run_original(
        case, cell, respond_text, tmp_path=tmp_path, suffix="status_distinct"
    )
    recorded = record_episode(original)
    scorer = plugin.build_scorer(plugin.validate_payload(case.payload))

    compared_report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )
    uncompared_report = asyncio.run(
        replay_and_verify(cell=cell, case=case, plugin=plugin, scorer=scorer, recorded=recorded)
    )

    assert compared_report.comparison is not None
    assert compared_report.status == "match"
    assert uncompared_report.comparison is None
    assert uncompared_report.status == "not_compared"
    assert uncompared_report.status != compared_report.status


def test_replay_of_a_tampered_record_diverges_and_is_caught_by_comparison(
    tmp_path: Path,
) -> None:
    """A stated limit (docs/steer_adapter_status.md): unlike
    ``tau3_retail.replay`` (whose ``Tau3RetailPlugin.step()`` independently
    re-executes and cross-checks every recorded tool result against the
    pinned upstream bridge), nothing in ``replay_episode`` itself can detect
    that a *recorded response* was tampered with -- there is no tool call or
    upstream computation to re-verify against, only the row's own gold
    answer. The only thing that catches a tampered record is comparing the
    replay against a genuine ``original`` in memory."""
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="tamper")
    respond_text = json.dumps({"option_id": row["correct_option_id"]})

    plugin, original = _run_original(case, cell, respond_text, tmp_path=tmp_path, suffix="tamper")
    recorded = record_episode(original)

    wrong_option_id = (row["correct_option_id"] + 1) % len(row["options"])
    tampered = RecordedEpisode(
        case_id=recorded.case_id,
        decisions=(
            RecordedDecision(
                phase_id="answer_question",
                seat_id="agent",
                response=json.dumps({"option_id": wrong_option_id}),
            ),
        ),
    )

    replay_plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=tampered)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is False
    assert comparison.final_state_matches is False
    with pytest.raises(ReplayError, match="final state differs"):
        assert_replay_matches(comparison)
