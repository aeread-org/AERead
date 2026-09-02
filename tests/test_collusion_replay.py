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
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.collusion import cases as collusion_cases
from aeread_families.collusion import measurement as m
from aeread_families.collusion.environment import CollusionPlugin
from aeread_families.collusion.harness import (
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
        decisions=(decision,),
        expected_final_outcome_sha256="b" * 64,
    )

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert restored.case_content_sha256 == "a" * 64
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
    wrong = RecordedEpisode(
        case_id="collusion.duopoly.does-not-exist",
        case_content_sha256=case.content_sha256,
        decisions=(RecordedDecision(phase_id="price_round", seat_id="firm_a", response={"price": 1.0}),),
        expected_final_outcome_sha256="0" * 64,
    )
    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(
                cell=_cell(case, suffix="mismatch"), case=case, plugin=CollusionPlugin(), recorded=wrong
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
    recorded = record_episode(original, case=case)
    stale = RecordedEpisode(
        case_id=recorded.case_id,
        case_content_sha256="f" * 64,  # a case_id-matching but stale/changed digest.
        decisions=recorded.decisions,
        expected_final_outcome_sha256=recorded.expected_final_outcome_sha256,
    )
    with pytest.raises(ReplayError, match="content digest"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, plugin=CollusionPlugin(), recorded=stale
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
    recorded = record_episode(original, case=case)

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
    recorded = record_episode(original, case=case)

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

    _cell_unused, original = _run_with_harness(
        case,
        tmp_path=tmp_path,
        suffix="offline_original",
        policy_by_seat={
            "firm_a": constant_policy(p_nash["firm_a"]),
            "firm_b": constant_policy(p_nash["firm_b"]),
        },
    )
    recorded = RecordedEpisode.from_json(record_episode(original, case=case).to_json())
    family_case = CollusionPlugin().validate_payload(case.payload)
    scorer = m.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=_cell(case, suffix="offline_replay"),
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

    recorded = record_episode(original, case=case)
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
