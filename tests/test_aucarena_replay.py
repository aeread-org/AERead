"""Tests for the ``aucarena`` offline replayer (replay.py, spec section 6).

Unlike ``tests/test_tau3_retail_replay.py`` (which gates its live/replay
tests on a pinned upstream Python interpreter that may not be provisioned),
every test in this module runs unconditionally: this family has no external
process to bridge to at all (``docs/aucarena_adapter_spec.md`` section 3,
"Not delegated, and why that's safe here") -- the pinned item data is
materialized into the case payload at import time, and every rule the
environment applies is a vendored pure function. There is nothing to skip.

Three kinds of coverage:

1. **Structural**, no scheduler involved: ``RecordedEpisode``/
   ``RecordedDecision`` round-trip through plain JSON;
   ``RecordedResponseSource`` enforces ordering and reports exhaustion;
   ``compare_episode_results`` reports specific component mismatches, not
   one collapsed boolean.
2. **Live + replay, every golden** (spec section 6: "Every golden's episode
   record replays offline... to the identical terminal state and leaf
   results with no upstream import and no network call"): each of the five
   QC Gate-2 goldens is run once for real through the kernel scheduler with
   the shipped, evidence-sealing harness, recorded, JSON-round-tripped, and
   replayed through a second, independent ``AucArenaPlugin`` instance with
   zero further policy calls -- reproducing the final state
   **byte-identically** (this family's own advantage over tau3_retail: no
   bridge, no wall-clock timestamps anywhere in state) and every declared
   leaf's score byte-identically.
3. **Mutation**: proves both guarantees are not vacuous, and does so by
   observing this family's actual (not assumed) dynamics. Because
   eligibility for a auction's *next* round is itself state-derived (the
   current highest bidder and each seat's withdraw flag, both set by the
   very bid values under test), corrupting any well-formed, still-legal
   recorded bid from the one seat whose response actually carries
   information ("agent" -- "rule" seats' raw responses are accepted but
   never inspected) does not quietly drift into a different terminal state:
   it changes which seat the scheduler must request next, which
   ``RecordedResponseSource`` catches (wrapped as
   ``SchedulerContractError`` by the kernel scheduler itself) before the
   replayed episode can even complete. ``compare_episode_results``'s own
   comparison logic is proven separately, and independently, not to be
   vacuous with a synthetic (scheduler-free) fixture.
"""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import canonical_json_bytes
from aeread.shared_runner.scheduler import (
    EpisodeResult,
    SchedulerContractError,
    run_episode,
)
from aeread_families.aucarena.environment import (
    AucArenaPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.aucarena.harness import ScriptedAucArenaHarness
from aeread_families.aucarena.measurement import build_scorer
from aeread_families.aucarena.replay import (
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

from tests.test_aucarena_environment import (
    _always_withdraw_policy,
    _case,
    _cell,
    _illegal_150_policy,
    _malformed_text_policy,
    _min_markup_policy,
)

GOLDEN_POLICIES = {
    "successful": _min_markup_policy,
    "valid_but_poor": _always_withdraw_policy,
    "invalid_unauthorized": _illegal_150_policy,
    "malformed_operational": _malformed_text_policy,
    "degenerate_reference": _always_withdraw_policy,
}


def _run_live(golden_name: str, tmp_path: Path) -> tuple[EpisodeResult, dict]:
    """Run one golden for real through the kernel scheduler, sealed evidence
    included, and return both the ``EpisodeResult`` and its validated
    ``family_case`` (needed to build the scorer)."""
    case = _case(golden_name)
    plugin = AucArenaPlugin()
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)
    cell = _cell(case)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{golden_name}",
        run_plan_id=f"runplan_aucarena_replay_{golden_name}",
        cell_id=cell.cell_id,
        episode_id=f"episode_aucarena_replay_{golden_name}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedAucArenaHarness(GOLDEN_POLICIES[golden_name], evidence=evidence)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved, response_source=harness)
    )
    evidence.verify_chain()
    return result, family_case


def _independent_replay_setup():
    """A second, independent plugin/registry -- never the one that produced
    the original run -- to drive the replay, mirroring
    ``tests/test_tau3_retail_replay.py``'s use of a second ``Tau2Bridge``."""
    plugin = AucArenaPlugin()
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    return registry.resolve_manifest(family_manifest())


# ---------------------------------------------------------------------------
# Structural: no scheduler, no case, no plugin.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(phase_id="bid_round", seat_id="agent", response="1300")
    episode = RecordedEpisode(
        case_id="aucarena.pilot.successful_01", decisions=(decision,)
    )

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "bid_round"
    assert restored.decisions[0].seat_id == "agent"
    assert restored.decisions[0].response == "1300"


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (RecordedDecision(phase_id="bid_round", seat_id="agent", response="-1"),)
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "bid_round"
        seat_id = "agent"

    response = asyncio.run(source(_Request()))
    assert response == "-1"
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id="bid_round", seat_id="field_high", response=""),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "bid_round"
        seat_id = "agent"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "auction_complete"},
        outcome={"termination_reason": "auction_complete"},
        final_state={"cur_item_index": 4},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "max_steps"},
        outcome={"termination_reason": "auction_complete"},
        final_state={"cur_item_index": 4},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Live + replay: every golden, byte-identical state and score reproduction.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("golden_name", sorted(GOLDEN_POLICIES))
def test_replay_reproduces_every_golden_byte_identically(
    golden_name: str, tmp_path: Path
) -> None:
    original, family_case = _run_live(golden_name, tmp_path)
    case = _case(golden_name)
    cell = _cell(case)

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    replay_plugin = _independent_replay_setup()
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert_replay_matches(comparison)  # must not raise
    # This family's own advantage over tau3_retail (no bridge, no wall-clock
    # content anywhere in state): the raw, byte-exact state matches itself,
    # not merely its content.
    assert canonical_json_bytes(original.final_state) == canonical_json_bytes(
        replayed.final_state
    )

    scorer = build_scorer(family_case)
    original_scores = score_replayed_episode(scorer=scorer, replayed=original)
    replayed_scores = score_replayed_episode(scorer=scorer, replayed=replayed)
    assert canonical_json_bytes(original_scores.to_tuple()) == canonical_json_bytes(
        replayed_scores.to_tuple()
    )


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    original, family_case = _run_live("successful", tmp_path)
    case = _case("successful")
    cell = _cell(case)
    recorded = record_episode(original)
    replay_plugin = _independent_replay_setup()
    scorer = build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=replay_plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.hammer_rule.primary.value == 1.0
    assert report.scores.profit_vs_field.status == "ok"


def test_replay_and_verify_reproduces_the_invalid_measurement_status(
    tmp_path: Path,
) -> None:
    """Golden 5's empty comparator population must replay to the same
    ``invalid_measurement`` status, never silently scored as a zero."""
    original, family_case = _run_live("degenerate_reference", tmp_path)
    case = _case("degenerate_reference")
    cell = _cell(case)
    recorded = record_episode(original)
    replay_plugin = _independent_replay_setup()
    scorer = build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=replay_plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.profit_vs_field.status == "invalid_measurement"


def test_replay_without_an_original_run_still_replays_and_scores(tmp_path: Path) -> None:
    """A genuinely offline replay -- no original ``EpisodeResult`` in memory,
    only a previously-written record -- still replays and scores;
    ``comparison`` is an explicit ``None``, never a fabricated match."""
    original, family_case = _run_live("valid_but_poor", tmp_path)
    case = _case("valid_but_poor")
    cell = _cell(case)
    recorded_text = record_episode(original).to_json()

    # Simulate "offline": only the JSON text and the pinned case survive.
    recorded = RecordedEpisode.from_json(recorded_text)
    replay_plugin = _independent_replay_setup()
    scorer = build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell, case=case, plugin=replay_plugin, scorer=scorer, recorded=recorded
        )
    )

    assert report.comparison is None
    assert report.status == "match"  # no comparison to fail -> reports "match"
    assert report.scores.budget_invariant.primary.value == 1.0


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    original, _family_case = _run_live("successful", tmp_path)
    case = _case("successful")
    cell = _cell(case)
    recorded = record_episode(original)
    wrong_case = RecordedEpisode(
        case_id="aucarena.pilot.valid_but_poor_01", decisions=recorded.decisions
    )
    replay_plugin = _independent_replay_setup()

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=wrong_case)
        )


# ---------------------------------------------------------------------------
# Mutation: prove the byte-identical claim is falsifiable, not vacuous.
# ---------------------------------------------------------------------------


def test_tampering_a_mid_trajectory_bid_is_caught_immediately_not_silently_replayed(
    tmp_path: Path,
) -> None:
    """Empirically (not assumed): who is eligible for the *next* round is
    computed from the live auctioneer state (current highest bidder, each
    seat's withdraw flag) -- state that a real bid value itself determines.
    Corrupting even one well-formed, still-legal recorded bid from this
    family's one informative seat ("agent"; "rule" seats' raw responses are
    accepted but never inspected, so tampering theirs is a no-op) therefore
    does not degrade into a quietly-different terminal state the way it
    might in a simpler turn-taking family: it changes who the scheduler
    itself must ask next, which ``RecordedResponseSource`` catches against
    the recorded order before the replayed episode can complete at all.
    This is a stronger integrity property than a post-hoc state comparison
    would be, and it is proven here, not merely asserted."""
    original, _family_case = _run_live("successful", tmp_path)
    case = _case("successful")
    cell = _cell(case)
    recorded = record_episode(original)

    decisions = list(recorded.decisions)
    target_index = next(
        index
        for index, decision in enumerate(decisions)
        if decision.seat_id == "agent" and decision.response not in ("-1", "")
    )
    original_response = decisions[target_index].response
    tampered_bid = str(int(original_response) + 100)  # still well-formed, still legal
    decisions[target_index] = dataclasses.replace(
        decisions[target_index], response=tampered_bid
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(decisions))

    replay_plugin = _independent_replay_setup()
    with pytest.raises(SchedulerContractError, match="does not match the replayed request"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=tampered)
        )


def test_tampering_decision_order_is_caught_by_the_response_source_itself(
    tmp_path: Path,
) -> None:
    original, _family_case = _run_live("successful", tmp_path)
    case = _case("successful")
    cell = _cell(case)
    recorded = record_episode(original)
    assert len(recorded.decisions) >= 2

    # Swap two decisions -- the replayed request stream (still driven by the
    # real scheduler over the real state machine) will not ask for seats in
    # this new order, so RecordedResponseSource itself must catch this
    # before the episode reaches an inconsistent state. The scheduler wraps
    # any exception a response_source raises into SchedulerContractError
    # (aeread.shared_runner.scheduler._request_action); the underlying
    # ReplayError's own message survives inside it.
    decisions = list(recorded.decisions)
    decisions[0], decisions[1] = decisions[1], decisions[0]
    reordered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(decisions))

    replay_plugin = _independent_replay_setup()
    with pytest.raises(SchedulerContractError, match="does not match the replayed request"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=reordered)
        )


def test_tampering_a_legal_withdraw_into_a_malformed_response_is_caught_even_though_state_is_unchanged(
    tmp_path: Path,
) -> None:
    """``docs/aucarena_codex_triage.md`` Finding 3: golden 5
    (``degenerate_reference``, one seat, one item) legally withdraws
    (response ``"-1"``). Replaying that one recorded decision as a
    malformed string instead (``"uh, I'll think about it"`` -- golden 4's
    own malformed text) produces the *identical* downstream game state (no
    bid recorded either way, hammer falls, item unsold, profit/budget
    untouched), so ``pre_state_sha256``/``post_state_sha256`` agree and
    ``mismatched_phase_instance_ids`` alone would not catch it. This
    validity-classification tamper (``envelope.valid`` stays ``True`` in
    the original, becomes ``False`` in the replay) must still be reported
    as a mismatch, not silently accepted as a match."""
    original, _family_case = _run_live("degenerate_reference", tmp_path)
    case = _case("degenerate_reference")
    cell = _cell(case)
    recorded = record_episode(original)

    decisions = list(recorded.decisions)
    target_index = next(
        index for index, decision in enumerate(decisions) if decision.response == "-1"
    )
    decisions[target_index] = dataclasses.replace(
        decisions[target_index], response="uh, I'll think about it"
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(decisions))

    replay_plugin = _independent_replay_setup()
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=tampered)
    )

    # The state-only comparison really does agree, as claimed above -- this
    # tamper is caught in spite of that, not because the state hashes also
    # happened to disagree.
    comparison = compare_episode_results(original, replayed)
    assert comparison.mismatched_phase_instance_ids == ()
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True

    assert comparison.mismatched_action_classification_ids != ()
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="action validity/legality classification differs"):
        assert_replay_matches(comparison)


def test_compare_episode_results_would_report_a_genuine_divergence(
    tmp_path: Path,
) -> None:
    """``compare_episode_results``'s live-object comparison itself is not
    vacuous: feeding it two independently-produced, non-identical
    ``EpisodeResult`` objects for the *same* case (a live run and a fresh,
    unrelated live run of a different golden, standing in for "two
    independent computations that genuinely disagree") reports a concrete
    mismatch -- see also the synthetic, scheduler-free proof of this above
    (``test_compare_episode_results_reports_specific_mismatches_not_one_
    boolean``), which is what a live replay divergence would fall back to if
    this family's stricter ``RecordedResponseSource`` ordering check (proven
    immediately above) were ever weakened or bypassed."""
    original, _family_case = _run_live("successful", tmp_path)
    other, _other_family_case = _run_live("valid_but_poor", tmp_path)

    comparison = compare_episode_results(original, other)

    assert comparison.matches is False
    assert comparison.outcome_matches is False
    assert comparison.final_state_matches is False
    with pytest.raises(ReplayError, match="replay diverged"):
        assert_replay_matches(comparison)
