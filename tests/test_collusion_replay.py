"""Tests for the collusion offline replayer (``replay.py``, spec section 5's
"offline replay" test plan; pattern: ``tau3_retail.replay``).

Follows ``test_collusion_measurement.py``'s own module-scoped-fixture
convention: the one expensive 300-round harness-driven episode this file
needs (spec section 5's milestone note: "at least 2 full episodes through
the REAL shared-runner path" -- the first of the two lives in
``test_collusion_harness.py``) is run **once**, reused by every test that
needs an original run to replay against, rather than re-run per test.

Structural tests (record/replay plumbing, comparator behaviour) run against
short, cheap episodes; only the byte-identical-reproduction test needs the
real, full 300-round trajectory.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import dataclasses
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    PlanCell,
    RunPlan,
    case_content_sha256,
    resolve_run_plan,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.evaluation import FamilyScoringInput, finalize_family_execution
from aeread.shared_runner.task.execution import CanonicalResponse, CellExecution, EvidenceStore
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode
from aeread_families.collusion import cases as collusion_cases
from aeread_families.collusion import environment as collusion_environment
from aeread_families.collusion import measurement as m
from aeread_families.collusion.environment import CollusionPlugin
from aeread_families.collusion.harness import (
    PolicyFn,
    ScriptedCollusionHarness,
    constant_policy,
    monopoly_play_policy,
    nash_play_policy,
    tit_for_tat_policy,
)
from aeread_families.collusion.replay import (
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

_SEATS = ("firm_a", "firm_b")


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_collusion_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_collusion_replay",
        suite_version="0.1.0",
        block_id="block_collusion_replay",
        sampling_plan_id="sampling_collusion_replay",
        analysis_plan_id="analysis_collusion_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_collusion_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"firm_a": "scripted_firm_a", "firm_b": "scripted_firm_b"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Any, *, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_collusion_replay_{suffix}",
        cell_id=f"cell_collusion_replay_{suffix}",
        episode_id=f"episode_collusion_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )


def _short_case(*, horizon: int = 5) -> CaseManifest:
    """A cheap, short-horizon real cell for structural (non-timing-sensitive) tests."""
    raw = collusion_cases.build_case("baseline-symmetric", 1.0, 0)
    raw = dict(raw)
    raw["payload"] = dict(raw["payload"])
    raw["payload"]["horizon"] = horizon
    raw["episode"] = dict(raw["episode"])
    raw["episode"]["max_logical_actions"] = horizon * collusion_cases.LOGICAL_ACTIONS_PER_ROUND
    raw["content_sha256"] = "0" * 64
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _run_with_harness(
    case: CaseManifest, *, tmp_path: Any, suffix: str, policy_by_seat: Mapping[str, Any]
):
    evidence = _evidence(tmp_path, suffix=suffix)
    harness = ScriptedCollusionHarness(policy_by_seat=policy_by_seat, evidence=evidence)
    cell = _cell(case, suffix=suffix)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=CollusionPlugin(), response_source=harness)
    )
    harness.seal()
    return cell, result


def _profit_report_window_mean(
    family_case: Mapping[str, Any], outcome: Mapping[str, Any], *, seat: str
) -> float:
    """One seat's own App. A.4 profit-reporting-window mean (periods
    251-300, ``measurement.PROFIT_REPORT_WINDOW_PERIODS``) -- mirrors
    ``measurement.py``'s own leaf-4 reduction (reused here, not
    reimplemented, only to compute a genuinely correct leaf-4 baseline
    value for a test, never to duplicate the scorer's own logic).
    """
    admitted = m._admitted_rounds(outcome["history"])
    window = m._window(
        admitted, horizon=family_case["horizon"], window_periods=m.PROFIT_REPORT_WINDOW_PERIODS
    )
    return m._mean([entry["profits"][seat] for entry in window])


# ---------------------------------------------------------------------------
# Pure, no scheduler: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id="price_round", seat_id="firm_a", response={"price": 1.5}
    )
    episode = RecordedEpisode(
        case_id="collusion.duopoly.baseline-symmetric.alpha1.seed0",
        case_content_sha256="a" * 64,
        cell_id="cell_collusion_replay_roundtrip",
        decisions=(decision,),
        expected_final_outcome_sha256="b" * 64,
    )

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert restored.case_content_sha256 == "a" * 64
    assert restored.cell_id == "cell_collusion_replay_roundtrip"
    assert restored.expected_final_outcome_sha256 == "b" * 64
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "price_round"
    assert restored.decisions[0].seat_id == "firm_a"
    assert restored.decisions[0].response == {"price": 1.5}


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id="price_round", seat_id="firm_a", response={"price": 1.5}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "price_round"
        seat_id = "firm_a"

    response = asyncio.run(source(_Request()))
    assert response == {"price": 1.5}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id="price_round", seat_id="firm_b", response={"price": 1.5}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "price_round"
        seat_id = "firm_a"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "max_periods"},
        outcome={"rounds_played": 300},
        final_state={"round": 300},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "legality_violation"},
        outcome={"rounds_played": 300},
        final_state={"round": 300},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


def test_replay_case_mismatch_raises_a_typed_replay_error_before_touching_the_scheduler() -> None:
    case = _short_case(horizon=1)
    mismatch_cell = _cell(case, suffix="mismatch")
    wrong = RecordedEpisode(
        case_id="collusion.duopoly.does-not-exist",
        case_content_sha256=case.content_sha256,
        cell_id=mismatch_cell.cell_id,
        decisions=(RecordedDecision(phase_id="price_round", seat_id="firm_a", response={"price": 1.0}),),
        expected_final_outcome_sha256="0" * 64,
    )
    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(
                cell=mismatch_cell, case=case, plugin=CollusionPlugin(), recorded=wrong
            )
        )


def test_replay_case_content_mismatch_raises_a_typed_replay_error_even_with_a_matching_case_id(
    tmp_path: Any,
) -> None:
    """The concrete failure scenario from the collusion codex triage's
    Finding 4: retain a matching ``case_id``, but let the case's own
    content digest have changed since this episode was recorded (e.g. the
    case's economics were rebuilt) -- ``replay_episode`` must reject this,
    not just a changed ``case_id``.
    """
    case = _short_case(horizon=1)
    cell, original = _run_with_harness(
        case,
        tmp_path=tmp_path,
        suffix="content_mismatch",
        policy_by_seat={
            "firm_a": constant_policy(case.payload["gold_reference"]["p_nash"]["firm_a"]),
            "firm_b": constant_policy(case.payload["gold_reference"]["p_nash"]["firm_b"]),
        },
    )
    recorded = record_episode(original, case=case, cell=cell)
    stale = RecordedEpisode(
        case_id=recorded.case_id,
        case_content_sha256="f" * 64,  # a case_id-matching but stale/changed digest.
        cell_id=recorded.cell_id,
        decisions=recorded.decisions,
        expected_final_outcome_sha256=recorded.expected_final_outcome_sha256,
    )
    with pytest.raises(ReplayError, match="content digest"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, plugin=CollusionPlugin(), recorded=stale
            )
        )


def test_replay_cell_identity_mismatch_raises_a_typed_replay_error_even_with_matching_case_content(
    tmp_path: Any,
) -> None:
    """The remaining half of the collusion codex triage's Finding 4: binding
    a recording to ``case_content_sha256`` (above) proves the *case*'s own
    economics are unchanged, but says nothing about *which run cell*
    (``PlanCell.cell_id`` -- the resolved case x block x seed x repetition
    execution unit, ``resolver.py``) produced the recording. A recording
    made under one cell must not be silently accepted for replay under a
    different, merely case-compatible cell (independent second-pass review,
    ``docs/collusion_fix_verification.md``: "no test exercises replay under
    a different compatible cell").
    """
    case = _short_case(horizon=1)
    cell, original = _run_with_harness(
        case,
        tmp_path=tmp_path,
        suffix="cell_identity_original",
        policy_by_seat={
            "firm_a": constant_policy(case.payload["gold_reference"]["p_nash"]["firm_a"]),
            "firm_b": constant_policy(case.payload["gold_reference"]["p_nash"]["firm_b"]),
        },
    )
    recorded = record_episode(original, case=case, cell=cell)
    different_cell = _cell(case, suffix="cell_identity_different")
    assert different_cell.cell_id != cell.cell_id

    with pytest.raises(ReplayError, match="cell"):
        asyncio.run(
            replay_episode(
                cell=different_cell, case=case, plugin=CollusionPlugin(), recorded=recorded
            )
        )


# ---------------------------------------------------------------------------
# Short-horizon, real-scheduler: tamper detection (replaces tau3's tool-replay
# cross-check, which has no analogue here -- collusion's step() never
# delegates to an upstream to re-verify against; the comparator itself must
# instead be proven to *detect* a genuine divergence, not just report "match"
# unconditionally).
# ---------------------------------------------------------------------------


def test_replay_of_a_tampered_recording_is_detected_as_a_divergence(tmp_path: Any) -> None:
    case = _short_case(horizon=5)
    p_monopoly = case.payload["gold_reference"]["p_monopoly"]

    cell, original = _run_with_harness(
        case,
        tmp_path=tmp_path,
        suffix="tamper_original",
        policy_by_seat={
            "firm_a": constant_policy(p_monopoly["firm_a"]),
            "firm_b": constant_policy(p_monopoly["firm_b"]),
        },
    )
    recorded = record_episode(original, case=case, cell=cell)

    tampered_decisions = list(recorded.decisions)
    for index, decision in enumerate(tampered_decisions):
        if decision.phase_id == "price_round" and decision.seat_id == "firm_a":
            tampered_decisions[index] = RecordedDecision(
                phase_id=decision.phase_id,
                seat_id=decision.seat_id,
                response={"price": decision.response["price"] + 0.01},
            )
            break
    tampered = RecordedEpisode(
        case_id=recorded.case_id,
        case_content_sha256=recorded.case_content_sha256,
        cell_id=recorded.cell_id,
        decisions=tuple(tampered_decisions),
        expected_final_outcome_sha256=recorded.expected_final_outcome_sha256,
    )

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=CollusionPlugin(), recorded=tampered)
    )
    comparison = compare_episode_results(original, replayed)

    assert comparison.state_hashes_match is False
    assert comparison.mismatched_phase_instance_ids  # at least the tampered round onward.
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="state hashes differ"):
        assert_replay_matches(comparison)


def test_offline_replay_of_a_tampered_recording_with_no_original_in_memory_reports_mismatch_not_a_fabricated_match(
    tmp_path: Any,
) -> None:
    """The concrete failure scenario from the collusion codex triage's
    Finding 3: edit one stored price, drop the in-memory ``original``, and
    replay purely from the (tampered) recording, through the real
    ``replay_and_verify`` entry point (not the raw ``compare_episode_
    results`` shortcut the sibling test above uses) -- ``status`` must not
    report "match" just because there is no live ``original`` to compare
    against; the sealed ``expected_final_outcome_sha256`` recorded
    alongside the (untampered) original episode must catch the divergence
    instead.
    """
    case = _short_case(horizon=5)
    p_monopoly = case.payload["gold_reference"]["p_monopoly"]

    cell, original = _run_with_harness(
        case,
        tmp_path=tmp_path,
        suffix="offline_tamper_original",
        policy_by_seat={
            "firm_a": constant_policy(p_monopoly["firm_a"]),
            "firm_b": constant_policy(p_monopoly["firm_b"]),
        },
    )
    recorded = record_episode(original, case=case, cell=cell)

    tampered_decisions = list(recorded.decisions)
    for index, decision in enumerate(tampered_decisions):
        if decision.phase_id == "price_round" and decision.seat_id == "firm_a":
            tampered_decisions[index] = RecordedDecision(
                phase_id=decision.phase_id,
                seat_id=decision.seat_id,
                response={"price": decision.response["price"] + 0.01},
            )
            break
    tampered = RecordedEpisode(
        case_id=recorded.case_id,
        case_content_sha256=recorded.case_content_sha256,
        cell_id=recorded.cell_id,
        decisions=tuple(tampered_decisions),
        expected_final_outcome_sha256=recorded.expected_final_outcome_sha256,
    )

    family_case = CollusionPlugin().validate_payload(case.payload)
    scorer = m.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=CollusionPlugin(),
            scorer=scorer,
            recorded=tampered,
            original=None,  # genuinely offline: nothing in memory to compare against.
            baseline_profit_by_seat=dict(p_monopoly),
        )
    )

    assert report.comparison is None
    assert report.digest_verified is False
    assert report.status == "mismatch"


def test_replay_without_an_original_reports_no_comparison_but_still_scores(tmp_path: Any) -> None:
    """Genuinely offline replay: no ``original`` in memory, only the recorded
    trajectory -- ``comparison`` must be an explicit ``None``, never a
    fabricated match."""
    case = _short_case(horizon=3)
    p_nash = case.payload["gold_reference"]["p_nash"]

    cell, original = _run_with_harness(
        case,
        tmp_path=tmp_path,
        suffix="offline_original",
        policy_by_seat={
            "firm_a": constant_policy(p_nash["firm_a"]),
            "firm_b": constant_policy(p_nash["firm_b"]),
        },
    )
    # A genuinely offline replay still resolves the *same* run cell it was
    # recorded under (e.g. re-resolved from the same run plan) -- it is not
    # a fabricated, unrelated cell (collusion codex triage, Finding 4).
    recorded = RecordedEpisode.from_json(
        record_episode(original, case=case, cell=cell).to_json()
    )
    family_case = CollusionPlugin().validate_payload(case.payload)
    scorer = m.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=CollusionPlugin(),
            scorer=scorer,
            recorded=recorded,
            original=None,
            baseline_profit_by_seat=dict(p_nash),
        )
    )

    assert report.comparison is None
    assert report.digest_verified is True
    assert report.status == "match"
    assert set(report.scores) == {
        m.PRICE_LEGALITY_LEAF_ID,
        m.DISTANCE_TO_NASH_LEAF_ID,
        m.DISTANCE_TO_MONOPOLY_LEAF_ID,
        m.LONG_RUN_PROFIT_LEAF_ID,
    }


# ---------------------------------------------------------------------------
# Full-episode, real-shared-runner-path coverage (the second of the >= 2
# full episodes; the first lives in test_collusion_harness.py). Module-scoped
# so the expensive 300-round run happens exactly once (mirrors
# test_collusion_measurement.py's own shared_nash_result convention).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shared_asymmetric_case() -> CaseManifest:
    raw = collusion_cases.build_case("asymmetric-quality", 10.0, 0)
    return CaseManifest.from_dict(raw)


@pytest.fixture(scope="module")
def shared_asymmetric_original(shared_asymmetric_case: CaseManifest, tmp_path_factory: Any):
    """One full 300-round episode, on a different real pilot cell than the
    harness file's own full episode, with a genuinely reactive policy
    (tit-for-tat) exercised end to end through the real scheduler.

    ``firm_a`` plays constant monopoly-play; ``firm_b`` opens tit-for-tat at
    its own Nash price (round 0 has no history yet), then mirrors
    ``firm_a``'s previous price every later round -- since ``firm_a`` never
    varies, ``firm_b`` converges to and stays at ``firm_a``'s monopoly price
    from round 1 onward, a deterministic, easily-asserted trajectory.
    """
    gold = shared_asymmetric_case.payload["gold_reference"]
    tmp_path = tmp_path_factory.mktemp("collusion_replay_asymmetric")
    cell, result = _run_with_harness(
        shared_asymmetric_case,
        tmp_path=tmp_path,
        suffix="asymmetric_full",
        policy_by_seat={
            "firm_a": monopoly_play_policy(gold["p_monopoly"]["firm_a"]),
            "firm_b": tit_for_tat_policy(
                seat_id="firm_b", opening_price=gold["p_nash"]["firm_b"]
            ),
        },
    )
    return cell, result


@pytest.fixture(scope="module")
def shared_asymmetric_same_opponent_baseline_profit(
    shared_asymmetric_case: CaseManifest, tmp_path_factory: Any
) -> dict[str, float]:
    """The economically correct leaf-4 baseline for
    ``shared_asymmetric_original``'s own trajectory.

    ``measurement.py``'s own ``BASELINE_POLICY_ID`` docstring: Nash-vs-Nash
    ``pi_nash`` is only a valid stand-in for the named baseline's realized
    profit when the *actual* opponent condition is also Nash. Here it is
    not -- ``shared_asymmetric_original`` is monopoly-play (firm_a) versus
    tit-for-tat (firm_b) -- so the correct baseline is each seat playing
    the named Nash-play policy against the *same* real opponent policy the
    live trajectory actually used, not against a Nash-playing opponent
    (collusion codex triage, Finding 2: "profit baseline uses the wrong
    opponent condition"). Computed by re-running the real scheduler twice
    (once per seat) through ``ScriptedCollusionHarness``/``run_episode`` --
    the production path, not an approximation -- swapping only the seat
    under test to Nash-play while keeping the *other* seat's real policy
    function unchanged.
    """
    gold = shared_asymmetric_case.payload["gold_reference"]
    p_nash = gold["p_nash"]
    p_monopoly = gold["p_monopoly"]
    tmp_path = tmp_path_factory.mktemp("collusion_replay_asymmetric_baseline")

    # firm_a's baseline: firm_a plays Nash, firm_b keeps its real policy
    # (tit-for-tat) -- the same opponent condition firm_a's live trajectory
    # actually faced.
    _cell_a, result_a = _run_with_harness(
        shared_asymmetric_case,
        tmp_path=tmp_path,
        suffix="asymmetric_baseline_firm_a",
        policy_by_seat={
            "firm_a": nash_play_policy(p_nash["firm_a"]),
            "firm_b": tit_for_tat_policy(seat_id="firm_b", opening_price=p_nash["firm_b"]),
        },
    )
    # firm_b's baseline: firm_b plays Nash, firm_a keeps its real policy
    # (persistent monopoly-play) -- the exact scenario the finding names.
    _cell_b, result_b = _run_with_harness(
        shared_asymmetric_case,
        tmp_path=tmp_path,
        suffix="asymmetric_baseline_firm_b",
        policy_by_seat={
            "firm_a": monopoly_play_policy(p_monopoly["firm_a"]),
            "firm_b": nash_play_policy(p_nash["firm_b"]),
        },
    )
    family_case = CollusionPlugin().validate_payload(shared_asymmetric_case.payload)
    return {
        "firm_a": _profit_report_window_mean(family_case, result_a.outcome, seat="firm_a"),
        "firm_b": _profit_report_window_mean(family_case, result_b.outcome, seat="firm_b"),
    }


def test_shared_full_episode_reaches_max_periods_with_the_expected_tit_for_tat_shape(
    shared_asymmetric_case: CaseManifest, shared_asymmetric_original: Any
) -> None:
    _cell, result = shared_asymmetric_original
    gold = shared_asymmetric_case.payload["gold_reference"]
    p_monopoly_a = gold["p_monopoly"]["firm_a"]
    p_nash_b = gold["p_nash"]["firm_b"]

    assert result.terminal["reason"] == "max_periods"
    assert result.outcome["rounds_played"] == 300
    history = result.outcome["history"]
    assert len(history) == 300
    assert all(entry["valid"] for entry in history)

    # Round 0: firm_b's tit-for-tat opening price, distinct from firm_a's.
    assert history[0]["prices"] == {"firm_a": p_monopoly_a, "firm_b": p_nash_b}
    # From round 1 on, firm_b mirrors firm_a's constant price exactly.
    for entry in history[1:]:
        assert entry["prices"] == {"firm_a": p_monopoly_a, "firm_b": p_monopoly_a}


def test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent(
    shared_asymmetric_case: CaseManifest,
    shared_asymmetric_same_opponent_baseline_profit: Mapping[str, float],
) -> None:
    """The concrete failure scenario from the collusion codex triage's
    Finding 2: firm_b is evaluated against firm_a's persistent
    monopoly-price policy; firm_b's correct leaf-4 baseline is firm_b
    playing Nash against that *same* monopoly-price opponent -- not
    Nash-vs-Nash ``pi_nash``. Proves the two are not interchangeable
    whenever the real opponent condition is not itself Nash (they need not
    differ in general, but do here, materially, for both seats).

    Scope note (independent second-pass review,
    ``docs/collusion_fix_verification.md``): this test and its sibling
    reproduction test below pin *this test file's own fixture* to the
    economically correct baseline and guard against it silently drifting
    back to the wrong one. Neither test exercises production's ability to
    reject a wrong baseline, because ``score_long_run_profit`` has none --
    it trusts the caller for provenance by design (``measurement.py``'s own
    docstring; ``docs/collusion_adapter_spec.md`` section 6's stated
    limit). A caller that mistakenly supplied ``gold_reference["pi_nash"]``
    here would still be accepted by production and would still produce a
    silently wrong delta; only this test file would (still) know the
    number was wrong.
    """
    gold_pi_nash = shared_asymmetric_case.payload["gold_reference"]["pi_nash"]
    correct = shared_asymmetric_same_opponent_baseline_profit
    for seat in _SEATS:
        assert abs(correct[seat] - gold_pi_nash[seat]) > 0.01 * abs(gold_pi_nash[seat])


def test_replay_and_verify_reproduces_state_and_score_byte_identically_with_zero_provider_calls(
    shared_asymmetric_case: CaseManifest,
    shared_asymmetric_original: Any,
    shared_asymmetric_same_opponent_baseline_profit: Mapping[str, float],
) -> None:
    cell, original = shared_asymmetric_original
    case = shared_asymmetric_case
    family_case = CollusionPlugin().validate_payload(case.payload)
    # The correct leaf-4 baseline for *this* trajectory (monopoly-play vs.
    # tit-for-tat) is each seat playing Nash against the same real opponent
    # it actually faced -- not gold["pi_nash"] (Nash-vs-Nash), which is only
    # a valid stand-in when the real opponent condition is also Nash
    # (found in review, collusion codex triage Finding 2; see
    # ``shared_asymmetric_same_opponent_baseline_profit``'s own docstring).
    baseline_profit_by_seat = dict(shared_asymmetric_same_opponent_baseline_profit)
    # Pin this test's own baseline to the correct, same-opponent-condition
    # value, not the wrong Nash-vs-Nash pi_nash this test used before the
    # fix (would fail this assertion, per the sibling proof test above).
    gold_pi_nash = family_case["gold_reference"]["pi_nash"]
    for seat in _SEATS:
        assert abs(baseline_profit_by_seat[seat] - gold_pi_nash[seat]) > 0.01 * abs(
            gold_pi_nash[seat]
        )

    recorded = record_episode(original, case=case, cell=cell)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent plugin instance -- not the one that produced the
    # original run -- drives the replay (RecordedResponseSource itself makes
    # zero model calls and invokes no policy function: module docstring).
    replay_plugin = CollusionPlugin()
    scorer = m.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=replay_plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
            baseline_profit_by_seat=baseline_profit_by_seat,
        )
    )

    assert report.status == "match"
    comparison = report.comparison
    assert comparison is not None
    assert comparison.phase_instance_count_matches is True
    assert comparison.state_hashes_match is True
    assert comparison.terminal_matches is True
    assert comparison.outcome_matches is True
    # Unlike tau3.retail's replay (whose raw state never matches itself
    # because of per-message wall-clock timestamping), collusion's state
    # carries no non-reproducible field at all, so the *raw* final state is
    # expected to be genuinely byte-identical, not merely content-equal.
    assert comparison.final_state_matches is True

    original_scores = scorer.score_all(
        original.outcome, baseline_profit_by_seat=baseline_profit_by_seat
    )
    replayed_scores = score_replayed_episode(
        scorer=scorer,
        replayed=report.replayed,
        baseline_profit_by_seat=baseline_profit_by_seat,
    )
    assert replayed_scores == original_scores == report.scores
    for leaf_id, score in report.scores.items():
        assert score.status == "ok", leaf_id


# ---------------------------------------------------------------------------
# Evidence-complete episode driving (kernel_scoring_contract_spec.md
# milestone 3): a response source that ALSO writes the full generic
# evidence trail ``task.evaluation.replay_family_scoring_input`` needs to
# replay, plus a real, ``resolve_run_plan``-resolved ``RunPlan`` -- both
# required to drive ``task.evaluation.finalize_family_execution`` for this
# family for the first time, and reused by
# ``tests/test_shared_runner_scoring_contract.py`` for its own
# paired-history fixtures.
# ---------------------------------------------------------------------------


class EvidenceRecordingCollusionHarness:
    """A ``run_episode`` response source that writes the full generic
    replay-required evidence trail (``logical_action_started``,
    ``action_attempt_succeeded``, ``action_parsed``,
    ``action_legality_checked``, ``logical_action_succeeded``,
    ``phase_instance_started``, ``transition_applied``,
    ``phase_instance_succeeded``, ``episode_terminated``,
    ``family_outcome_recorded``) -- exactly the event vocabulary
    ``aeread.shared_runner.task.execution.MinimalChatExecutor``/
    ``AttemptExecutor`` write for every LLM-harness-backed family's own
    evidence, reproduced here without any of that class's provider/retry/
    cost machinery, since every collusion pricing decision here is a plain
    scripted mapping, never a provider completion.

    ``ScriptedCollusionHarness`` (this file's own existing scripted
    response source, above) writes only its own convenience event
    (``collusion_price_submitted``) and has never produced evidence
    ``aeread.shared_runner.task.evaluation.replay_family_scoring_input`` can
    replay -- ``finalize_family_execution`` calls that replay internally, so
    this class is what makes driving THAT finalizer for this family possible
    at all. ``answer`` supplies the raw scripted decision for one request (a
    mapping shaped for ``CollusionPlugin.parse_action``'s own ``Mapping``
    branch, e.g. ``{"price": 1.5}`` or a deliberately malformed one); this
    class owns only the evidence-recording seam around it, mirroring
    ``AttemptExecutor``'s own event shapes field-for-field (and govsim's
    identically-motivated ``EvidenceRecordingGovsimHarness``).
    """

    def __init__(
        self, *, answer: Callable[[Any], Mapping[str, Any]], evidence: EvidenceStore
    ) -> None:
        self._answer = answer
        self._evidence = evidence

    async def __call__(self, request: Any) -> dict[str, Any]:
        response = dict(self._answer(request))
        self._evidence.append_event(
            "logical_action_started",
            {"request": request},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        # A CanonicalResponse-shaped placeholder purely for replay provenance
        # (``LogicalActionRecord.response``): ``CollusionPlugin.parse_action``
        # never reads it (the scheduler hands it the raw ``response`` mapping
        # returned above, unchanged -- see ``ScriptedCollusionHarness``'s
        # identical contract), and replay itself reconstructs ``parse``/
        # ``legality`` directly from the "action_parsed"/
        # "action_legality_checked" events below, never from this response.
        canonical = CanonicalResponse(
            text=json.dumps(response, sort_keys=True),
            finish_reason="stop",
            empty=False,
            truncated=False,
            provider_call_ids=(),
            tool_invocation_ids=(),
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            action=response,
        )
        self._evidence.append_event(
            "action_attempt_succeeded",
            {"canonical_response": canonical},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        return response

    def finalize_action(self, record: Any) -> None:
        envelope = record.envelope
        failure_code = None
        if not envelope.valid:
            failure_code = (
                envelope.parse.error_code
                if not envelope.parse.ok
                else envelope.legality.reason
            )
        self._evidence.append_event(
            "action_parsed",
            {"parse_result": envelope.parse},
            phase_instance_id=record.request.phase_instance_id,
            logical_action_id=record.logical_action_id,
            visibility=f"seat:{record.seat_id}",
        )
        if envelope.legality is not None:
            self._evidence.append_event(
                "action_legality_checked",
                {"legality_result": envelope.legality},
                phase_instance_id=record.request.phase_instance_id,
                logical_action_id=record.logical_action_id,
            )
        event_type = (
            "logical_action_succeeded"
            if envelope.valid
            else "logical_action_agent_action_failure"
        )
        self._evidence.append_event(
            event_type,
            {"valid": envelope.valid, "failure_code": failure_code},
            logical_action_id=record.logical_action_id,
        )

    def fail_logical_action(self, logical_action_id: str, *, failure_code: str) -> None:
        self._evidence.append_event(
            "logical_action_failed",
            {"failure_condition": failure_code},
            logical_action_id=logical_action_id,
        )

    def phase_started(
        self,
        *,
        phase_instance_id: str,
        phase: Any,
        eligible_actors: tuple[str, ...],
        pre_state_sha256: str,
    ) -> None:
        self._evidence.append_event(
            "phase_instance_started",
            {
                "phase": phase,
                "eligible_actors": eligible_actors,
                "pre_state_sha256": pre_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def transition_applied(
        self,
        *,
        phase_instance_id: str,
        phase: Any,
        transition: Any,
        post_state_sha256: str,
    ) -> None:
        self._evidence.append_event(
            "transition_applied",
            {
                "phase_id": phase.phase_id,
                "transition": transition,
                "post_state_sha256": post_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def phase_completed(self, *, phase_instance: Any) -> None:
        self._evidence.append_event(
            "phase_instance_succeeded",
            {
                "phase_id": phase_instance.phase_id,
                "post_state_sha256": phase_instance.post_state_sha256,
                "logical_action_ids": tuple(
                    action.logical_action_id for action in phase_instance.actions
                ),
            },
            phase_instance_id=phase_instance.phase_instance_id,
        )

    def episode_completed(self, *, episode_result: EpisodeResult) -> None:
        self._evidence.append_event(
            "episode_terminated",
            {
                "terminal": episode_result.terminal,
                "logical_action_count": episode_result.logical_action_count,
            },
        )
        self._evidence.append_event(
            "family_outcome_recorded",
            {"outcome": episode_result.outcome},
        )


def _policy_answer(policy_by_seat: Mapping[str, PolicyFn]) -> Callable[[Any], Mapping[str, Any]]:
    """An ``answer`` callable for ``EvidenceRecordingCollusionHarness`` that
    mirrors ``ScriptedCollusionHarness.__call__``'s exact per-seat policy
    dispatch, returning ``{"price": price}`` for whichever seat is asked."""

    def answer(request: Any) -> Mapping[str, Any]:
        policy = policy_by_seat[request.seat_id]
        return {"price": policy(request.observation)}

    return answer


def _malformed_first_round_answer(
    *, malformed_seat: str, other_policy: PolicyFn
) -> Callable[[Any], Mapping[str, Any]]:
    """An ``answer`` callable where ``malformed_seat`` always submits a
    price string with no extractable number (``CollusionPlugin.parse_action``'s
    ``Mapping`` branch fails it as ``"malformed_price"``) while every other
    seat plays ``other_policy`` normally. With no legality data to check for
    the malformed seat, ``CollusionPlugin.step`` classifies the round
    ``"retry_exhausted"`` (``environment.py``'s own docstring on that
    distinction) and the episode ends after round 0 -- deliberately
    constructed so this family's operational-failure gate
    (``measurement.OPERATIONAL_FAILURE_REASONS``) fires, which is the only
    way ``collusion_long_run_profit`` -- whose comparative delta is
    otherwise gated to the identical ``"baseline_profit_not_provided"``
    ``invalid_measurement`` reason on every fixture, since no baseline is
    ever reachable from a ``FamilyScoringInput`` alone -- can be shown
    capable of changing at all (ruling R9(b)'s sensitivity witness)."""

    def answer(request: Any) -> Mapping[str, Any]:
        if request.seat_id == malformed_seat:
            return {"price": "not-a-number"}
        return {"price": other_policy(request.observation)}

    return answer


@dataclass(frozen=True, slots=True)
class CollusionSetup:
    """A resolved, provider-free ``RunPlan`` for one collusion case.

    Unlike a real LLM-harness-backed family (housing, procurement_*,
    commercial_state_calibration), this family's real runtime never goes
    through ``execute_plan_cell``'s harness/provider stack at all -- every
    seat is answered directly through ``run_episode``'s ``response_source``
    (``ScriptedCollusionHarness``/``EvidenceRecordingCollusionHarness``
    above), matching govsim's identically-shaped ``GovsimSetup``. The
    declared ``minimal_chat`` harness and fixture provider below exist
    purely to satisfy ``resolve_run_plan``'s structural pin/capability
    checks and are never actually invoked.
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, Any]


_COLLUSION_FIXTURE_PROFILE_ID = "collusion_unused_fixture_profile_v1"
_COLLUSION_FIXTURE_PROVIDER_ID = "collusion_unused_fixture_provider"
_COLLUSION_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def _pin(
    component_id: str, kind: str, source_path: Path, *, version: str = "0.1.0"
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def build_collusion_setup(case: CaseManifest, *, suffix: str) -> CollusionSetup:
    """Resolve a real, one-cell ``RunPlan`` for ``case`` (spec section 5.3).

    Every seat shares one placeholder agent profile: this family's real
    runtime never invokes it (see ``CollusionSetup``'s own docstring), so
    the harness/provider it names exist only to satisfy
    ``resolve_run_plan``'s structural checks.
    """
    family = collusion_environment.family_manifest()
    seat_ids = [seat.id for seat in case.seats]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"collusion_{suffix}_sample_v1",
            "estimand": "fixed_collusion_case",
            "target": case.case_id,
            "selection": "fixed_curated",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"collusion_{suffix}_block",
            "kind": "self_play",
            "subject_seats": list(seat_ids),
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"collusion_{suffix}_analysis_v1",
            "estimands": [m.LONG_RUN_PROFIT_ESTIMAND_ID],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "world_seed",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"collusion_{suffix}_suite_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": _COLLUSION_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _COLLUSION_FIXTURE_PROVIDER_ID,
                "model": "collusion_unused_fixture_model_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {},
            },
            "prompt": {
                "prompt_id": f"collusion_{suffix}_prompt_v1",
                "sha256": hashlib.sha256(
                    b"collusion scripted pricing agent: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _COLLUSION_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "collusion_scripted_no_reasoning_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 64,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": case.episode.max_logical_actions,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.0,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"collusion_{suffix}_run_spec_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {seat_id: profile.profile_id for seat_id in seat_ids},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    registry = PluginRegistry()
    collusion_environment.register_plugin(registry)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_path = Path(collusion_environment.__file__)
    execution_path = Path(execution_module.__file__)
    measurement_path = Path(m.__file__)
    economics_path = environment_path.with_name("economics.py")
    # measurement.py declares each of its four leaves' validity-domain
    # predicate, reference implementation, and scorer implementation under
    # its own distinct component id (see environment.py's family_manifest()
    # docstring on scoring.reference_provider_ids); every one of those nine
    # must also be pinned here, or
    # EvaluationReceipt._validate_and_freeze_plan_pins rejects the sealed
    # receipt as missing implementations. The source file named for each id
    # below matches measurement.py's own ``_implementation(id, filename)``
    # call for that id exactly (``_file_sha256`` hashes a sibling file by
    # name), since the receipt's own implementation_refs carry that same
    # content hash.
    pins = (
        _pin(collusion_environment.PLUGIN_ID, "family_plugin", environment_path),
        _pin(collusion_environment.SCORER_ID, "scorer", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(_COLLUSION_FIXTURE_RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
        _pin(m.DOMAIN_PREDICATE_ID, "reference", environment_path),
        _pin(m.PRICE_LEGALITY_PREDICATE_ID, "reference", environment_path),
        _pin(m.PRICE_LEGALITY_SCORER_ID, "reference", measurement_path),
        _pin(m.NASH_PRICE_SOLVER_ID, "reference", economics_path),
        _pin(m.DISTANCE_TO_NASH_SCORER_ID, "reference", measurement_path),
        _pin(m.MONOPOLY_PRICE_SOLVER_ID, "reference", economics_path),
        _pin(m.DISTANCE_TO_MONOPOLY_SCORER_ID, "reference", measurement_path),
        _pin(m.NASH_PLAY_BASELINE_IMPLEMENTATION_ID, "reference", measurement_path),
        _pin(m.LONG_RUN_PROFIT_SCORER_ID, "reference", measurement_path),
    )
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            _COLLUSION_FIXTURE_PROVIDER_ID: ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
    )
    return CollusionSetup(plan=plan, registry=registry, prompt_sources={}, pricing={})


# ---------------------------------------------------------------------------
# finalize_family_execution (kernel_scoring_contract_spec.md milestone 3).
# ---------------------------------------------------------------------------


def test_finalize_wires_collusion_to_the_shared_family_finalizer(tmp_path: Any) -> None:
    """This family has never produced an ``EvaluationReceipt``.

    Every other already-migrated family has at least one test driving a
    real episode through ``task.evaluation.finalize_family_execution``
    (e.g. ``test_commercial_state_calibration.py``'s identically-purposed
    ``test_finalize_wires_commercial_state_to_the_shared_family_finalizer``);
    collusion had none, because its existing scripted response source
    (``ScriptedCollusionHarness``) writes only its own convenience event and
    has never produced evidence ``finalize_family_execution``'s internal
    ``replay_family_scoring_input`` call can replay --
    ``EvidenceRecordingCollusionHarness`` (this module, above) is what makes
    this reachable. Drives one small, real, provider-free episode end to end
    through the real finalizer and asserts a receipt comes back carrying
    every one of this family's four declared finalize-time leaves.

    ``collusion_long_run_profit`` (the primary and sole admission leaf) is
    asserted ``invalid_measurement`` here, not ``ok`` -- a documented,
    structural fact, not a fixture defect: ``CollusionScorer.__call__``
    always calls ``score_all`` with ``baseline_profit_by_seat=None``,
    because no comparison baseline is reachable from a
    ``FamilyScoringInput`` alone (this leaf's own docstring; the
    ``FamilyScorer`` protocol has no parameter for one). The receipt is
    therefore always ``inclusion_status="excluded"`` for this family when
    driven through the generic finalizer -- see
    ``docs/collusion_adapter_status.md``'s "Receipt" section.
    """
    case = _short_case(horizon=4)
    setup = build_collusion_setup(case, suffix="finalize_receipt")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_receipt",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    family_case = plugin.validate_payload(case.payload)
    gold = family_case["gold_reference"]
    harness = EvidenceRecordingCollusionHarness(
        answer=_policy_answer(
            {
                "firm_a": monopoly_play_policy(gold["p_monopoly"]["firm_a"]),
                "firm_b": nash_play_policy(gold["p_nash"]["firm_b"]),
            }
        ),
        evidence=evidence,
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    execution = CellExecution(
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id="attempt_1",
        episode_result=result,
        evidence=evidence,
        action_executions=(),
        total_cost_usd=0.0,
    )

    receipt = finalize_family_execution(setup=setup, execution=execution)

    assert receipt.status == "invalid_measurement"
    assert receipt.inclusion_status == "excluded"
    assert {score.leaf.leaf_id for score in receipt.scores} == {
        m.PRICE_LEGALITY_LEAF_ID,
        m.DISTANCE_TO_NASH_LEAF_ID,
        m.DISTANCE_TO_MONOPOLY_LEAF_ID,
        m.LONG_RUN_PROFIT_LEAF_ID,
    }
    assert receipt.primary_leaf_id == m.LONG_RUN_PROFIT_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1
    price_legality = next(
        score for score in receipt.scores if score.leaf.leaf_id == m.PRICE_LEGALITY_LEAF_ID
    )
    assert price_legality.status == "ok"
    assert price_legality.primary is not None
    assert price_legality.primary.value == 1.0
    long_run_profit = next(
        score for score in receipt.scores if score.leaf.leaf_id == m.LONG_RUN_PROFIT_LEAF_ID
    )
    assert long_run_profit.status == "invalid_measurement"
    assert long_run_profit.validity.reasons == ("baseline_profit_not_provided",)


def test_finalize_family_execution_rejects_a_collusion_scorer_that_forges_evidence_refs(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``evidence_refs`` provenance is enforced by the caller, not trusted
    from the callee (independent review, ``docs/collusion_migration_review.md``
    finding 4): ``CollusionScorer.__call__`` -- like every migrated family's
    own ``__call__`` (kernel_scoring_contract_spec.md section 2's call site)
    -- takes ``evidence_refs`` as an independent keyword argument and
    forwards it verbatim, trusting its caller for that value; nothing in
    ``measurement.py`` cross-checks it against ``scoring_input.evidence_refs``
    itself. ``task.evaluation.finalize_family_execution``
    (``_check_evidence_refs_are_scoring_input_verbatim``) is what makes
    ``scoring_input.evidence_refs`` authoritative: every real call already
    supplies the matching value (this file's own
    ``test_finalize_wires_collusion_to_the_shared_family_finalizer``), which
    is exactly why that check never previously fired for this family. This
    test forges a stale, non-matching ``evidence_refs`` tuple onto every
    returned score to prove the check actually rejects it, not merely that
    the happy path (where the two values already agree) passes.
    """
    real_call = m.CollusionScorer.__call__

    def _forging_call(
        self: m.CollusionScorer,
        scoring_input: FamilyScoringInput,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> Any:
        score_set = real_call(self, scoring_input, evidence_refs=evidence_refs)
        forged_refs = ("forged_evidence_ref_0",)
        assert forged_refs != scoring_input.evidence_refs
        return dataclasses.replace(
            score_set,
            scores=tuple(
                dataclasses.replace(score, evidence_refs=forged_refs)
                for score in score_set.scores
            ),
        )

    monkeypatch.setattr(m.CollusionScorer, "__call__", _forging_call)

    case = _short_case(horizon=4)
    setup = build_collusion_setup(case, suffix="finalize_forged_refs")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_forged_refs",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    family_case = plugin.validate_payload(case.payload)
    gold = family_case["gold_reference"]
    harness = EvidenceRecordingCollusionHarness(
        answer=_policy_answer(
            {
                "firm_a": monopoly_play_policy(gold["p_monopoly"]["firm_a"]),
                "firm_b": nash_play_policy(gold["p_nash"]["firm_b"]),
            }
        ),
        evidence=evidence,
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    execution = CellExecution(
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id="attempt_1",
        episode_result=result,
        evidence=evidence,
        action_executions=(),
        total_cost_usd=0.0,
    )

    with pytest.raises(ValueError, match="evidence_refs that disagree"):
        finalize_family_execution(setup=setup, execution=execution)
