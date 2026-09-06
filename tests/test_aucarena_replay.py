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
import hashlib
from pathlib import Path
from typing import Any, Callable

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    CellExecution,
    EvidenceStore,
)
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    RunPlan,
    canonical_json_bytes,
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
from aeread.shared_runner.task.evaluation import finalize_family_execution
from aeread.shared_runner.task.scheduler import (
    EpisodeResult,
    SchedulerContractError,
    run_episode,
)
from aeread_families.aucarena import cases as ac_cases
from aeread_families.aucarena import environment as ac_environment
from aeread_families.aucarena import measurement as m
from aeread_families.aucarena.environment import (
    AucArenaPlugin,
    PLUGIN_ID,
    SCORER_ID,
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
    # (aeread.shared_runner.task.scheduler._request_action); the underlying
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


# ---------------------------------------------------------------------------
# Evidence-complete episode driving (kernel_scoring_contract_spec.md
# milestone 3): a response source that ALSO writes the full generic evidence
# trail ``task.evaluation.replay_family_scoring_input`` needs to replay, plus
# a real, ``resolve_run_plan``-resolved ``RunPlan`` -- both required to drive
# ``task.evaluation.finalize_family_execution`` for this family for the
# first time, and reused by ``tests/test_shared_runner_scoring_contract.py``
# for its own paired-history fixtures.
# ---------------------------------------------------------------------------


class EvidenceRecordingAucArenaHarness:
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
    cost machinery, since every aucarena decision is a plain scripted
    string, never a provider completion. Mirrors govsim's identically-named,
    identically-purposed ``EvidenceRecordingGovsimHarness``
    (``tests/test_govsim_replay.py``) field-for-field, except ``__call__``
    returns and records a raw string decision rather than a dict one:
    ``CanonicalResponse.action`` is a ``Mapping | None`` (that class's own
    docstring: "a harness-driven executor carries HarnessOutput.action
    here... A text harness (minimal_chat) leaves it None and a family keeps
    reading .text exactly as before") -- aucarena's raw text response is a
    ``minimal_chat``-shaped decision, not a harness-mediated mapping one, so
    this records ``text=response, action=None``, never ``action=response``.

    ``ScriptedAucArenaHarness`` (this family's existing scripted response
    source, ``harness.py``) writes only its own convenience event
    (``bid_decision_served``) and has never produced evidence
    ``aeread.shared_runner.task.evaluation.replay_family_scoring_input`` can
    replay -- ``finalize_family_execution`` calls that replay internally, so
    this class is what makes driving THAT finalizer for this family possible
    at all. ``answer`` supplies the raw scripted bid text for one request (a
    policy function keyed off the request itself); this class owns only the
    evidence-recording seam around it, mirroring ``AttemptExecutor``'s own
    event shapes field-for-field.
    """

    def __init__(self, *, answer: Callable[[Any], str], evidence: EvidenceStore) -> None:
        self._answer = answer
        self._evidence = evidence

    async def __call__(self, request: Any) -> str:
        response = self._answer(request)
        self._evidence.append_event(
            "logical_action_started",
            {"request": request},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        canonical = CanonicalResponse(
            text=response,
            finish_reason="stop",
            empty=False,
            truncated=False,
            provider_call_ids=(),
            tool_invocation_ids=(),
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            action=None,
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


def kernel_contract_fixture_case(*, world_seed: int = 0) -> CaseManifest:
    """A small, fast, fully-controlled single-item/two-seat aucarena case.

    Distinct from the checked-in five-golden pilot corpus: this fixture
    case exists only so ``tests/test_shared_runner_scoring_contract.py``'s
    paired-history fixtures and this module's own
    ``finalize_family_execution`` receipt test can drive real episodes
    quickly and deterministically, with full control over how many rounds
    each item takes to sell (``docs/aucarena_migration_plan.md``'s own
    constructibility finding: a seat jumping straight to the eventual
    hammer price in round 0 instead of via intermediate rounds is still
    legal). Never written to the on-disk corpus. ``payload.item_pool_sha256``
    is the real pinned constant (``cases.ITEM_POOL_SHA256``) even though this
    item is not drawn from the pinned pool -- ``validate_payload`` only
    checks the hash literally matches, never the item content against a
    loaded pool file.
    """
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": "aucarena.kernel_contract_fixture.single_item.0",
        "family_id": ac_cases.FAMILY_ID,
        "family_version": ac_cases.FAMILY_VERSION,
        "split": "dev",
        "world_seed": world_seed,
        "seats": [{"id": "agent", "role": "bidder"}, {"id": "field", "role": "bidder"}],
        "episode": {"max_logical_actions": 20, "termination": list(ac_cases.TERMINATION_REASONS)},
        "visibility_policy": "aucarena_full_observation_v1",
        "payload": {
            "enable_discount": False,
            "item_ids": [1],
            "item_pool_sha256": ac_cases.ITEM_POOL_SHA256,
            "items": [
                {"id": 1, "name": "Widget", "price": 1000, "desc": "d", "true_value": 5000}
            ],
            "min_markup_pct": 0.1,
            "world_seed": world_seed,
            "roster": [
                {"seat_id": "agent", "model_name": "scripted", "budget": 5000, "max_bid_cnt": 10},
                {"seat_id": "field", "model_name": "scripted", "budget": 5000, "max_bid_cnt": 10},
            ],
        },
        "provenance": {
            "generator_id": "aucarena_kernel_contract_fixture_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def short_path_answer(request: Any) -> str:
    """One round: ``agent`` jumps straight to the eventual hammer price,
    ``field`` withdraws immediately -- legal (``bid_sanity_check`` only
    requires clearing ``highest_bid + min_markup_pct * price``, not a fixed
    increment). Sold at ``1300`` in round 0."""
    if request.seat_id == "agent":
        return "1300"
    return "-1"


def long_path_answer(request: Any) -> str:
    """Three rounds to the SAME winner and SAME hammer price (``1300``) as
    ``short_path_answer`` -- round 0 both bid, round 1 ``agent`` alone raises
    to the final price, round 2 ``field`` alone withdraws (the round the
    hammer actually falls, since nobody contests further). Verified against
    the real scheduler before being wired in here (byte-identical outcome,
    genuinely differing ``phase_instances``)."""
    round_ = int(request.observation["bid_round"])
    if request.seat_id == "agent":
        if round_ == 0:
            return "1000"
        if round_ == 1:
            return "1300"
        raise RuntimeError(f"agent should not be asked in round {round_}")
    if round_ == 0:
        return "1100"
    if round_ == 2:
        return "-1"
    raise RuntimeError(f"field should not be asked in round {round_}")


def illegal_bid_answer(request: Any) -> str:
    """Same case as ``short_path_answer``/``long_path_answer`` (same-case
    witness pair for ``aucarena_bid_legality_leaf``): ``agent`` bids below
    the item's starting price (illegal, recorded and rejected, never
    applied -- golden 3's own scenario), ``field`` then wins uncontested at
    the item price in the same round."""
    if request.seat_id == "agent":
        return "500"
    return "1000"


@dataclasses.dataclass(frozen=True, slots=True)
class AucArenaSetup:
    """A resolved, provider-free ``RunPlan`` for one aucarena case.

    Unlike every LLM-harness-backed family's own setup (housing,
    procurement_*, commercial_state_calibration), this family's real
    runtime never goes through ``execute_plan_cell``'s harness/provider
    stack at all -- every seat is answered directly through
    ``run_episode``'s ``response_source``
    (``ScriptedAucArenaHarness``/``EvidenceRecordingAucArenaHarness``
    above), matching this module's own ``_run_live``. The declared
    ``minimal_chat`` harness and fixture provider below exist purely to
    satisfy ``resolve_run_plan``'s structural pin/capability checks and are
    never actually invoked.
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: dict[str, str]
    pricing: dict[str, Any]


_FIXTURE_PROFILE_ID = "aucarena_unused_fixture_profile_v1"
_FIXTURE_PROVIDER_ID = "aucarena_unused_fixture_provider"
_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


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


def build_aucarena_setup(case: CaseManifest, *, suffix: str) -> AucArenaSetup:
    """Resolve a real, one-cell ``RunPlan`` for ``case`` (spec section 5.3).

    Every bidder seat shares one placeholder agent profile: this family's
    real runtime never invokes it (see ``AucArenaSetup``'s own docstring),
    so the harness/provider it names exist only to satisfy
    ``resolve_run_plan``'s structural checks.
    """
    family = family_manifest()
    seat_ids = [seat.id for seat in case.seats]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"aucarena_{suffix}_sample_v1",
            "estimand": "fixed_aucarena_case",
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
            "block_id": f"aucarena_{suffix}_block",
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
            "analysis_plan_id": f"aucarena_{suffix}_analysis_v1",
            "estimands": [m.PROFIT_VS_FIELD_ESTIMAND_ID],
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
            "suite_id": f"aucarena_{suffix}_suite_v1",
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
            "profile_id": _FIXTURE_PROFILE_ID,
            "model": {
                "provider": _FIXTURE_PROVIDER_ID,
                "model": "aucarena_unused_fixture_model_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": {}},
            "prompt": {
                "prompt_id": f"aucarena_{suffix}_prompt_v1",
                "sha256": hashlib.sha256(
                    b"aucarena scripted bidder: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "aucarena_scripted_no_reasoning_v1",
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
            "run_spec_id": f"aucarena_{suffix}_run_spec_v1",
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
    register_plugin(registry)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_path = Path(ac_environment.__file__)
    execution_path = Path(execution_module.__file__)
    measurement_path = Path(m.__file__)
    vendored_path = environment_path.with_name("_vendored_upstream.py")
    pins = (
        _pin(PLUGIN_ID, "family_plugin", environment_path),
        _pin(SCORER_ID, "scorer", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(_FIXTURE_RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
        # measurement.py declares each leaf's validity-domain predicate,
        # verifier reference, and scorer implementation under its own
        # distinct component id (see environment.py's family_manifest()
        # docstring on scoring.reference_provider_ids); every one of those
        # nine must also be pinned here, or
        # EvaluationReceipt._validate_and_freeze_plan_pins rejects the
        # sealed receipt as missing implementations.
        _pin(m.BASE_DOMAIN_PREDICATE_ID, "reference", environment_path),
        _pin(m.BUDGET_INVARIANT_CHECK_ID, "reference", vendored_path),
        _pin(m.BUDGET_INVARIANT_SCORER_ID, "reference", measurement_path),
        _pin(m.BID_LEGALITY_CHECK_ID, "reference", vendored_path),
        _pin(m.BID_LEGALITY_SCORER_ID, "reference", measurement_path),
        _pin(m.HAMMER_RULE_CHECK_ID, "reference", vendored_path),
        _pin(m.HAMMER_RULE_SCORER_ID, "reference", measurement_path),
        _pin(m.PROFIT_VS_FIELD_CHECK_ID, "reference", measurement_path),
        _pin(m.PROFIT_VS_FIELD_SCORER_ID, "reference", measurement_path),
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
            _FIXTURE_PROVIDER_ID: ProviderCapabilities(
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
    return AucArenaSetup(plan=plan, registry=registry, prompt_sources={}, pricing={})


def test_finalize_wires_aucarena_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """This family has never produced an ``EvaluationReceipt``.

    Every other already-migrated family has at least one test driving a
    real episode through ``task.evaluation.finalize_family_execution`` (see
    ``tests/test_govsim_replay.py``'s identically-purposed
    ``test_finalize_wires_govsim_to_the_shared_family_finalizer``); aucarena
    had none, because its existing scripted response source
    (``ScriptedAucArenaHarness``) writes only its own convenience event and
    has never produced evidence ``finalize_family_execution``'s internal
    ``replay_family_scoring_input`` call can replay --
    ``EvidenceRecordingAucArenaHarness`` (this module, above) is what makes
    this reachable. Drives one small, real, provider-free episode (this
    module's own ``kernel_contract_fixture_case``, ``short_path_answer``)
    end to end through the real finalizer and asserts a receipt comes back
    carrying EXACTLY the declared finalize-time leaf ids and the declared
    primary_leaf_id -- not merely that a receipt came back.
    """
    case = kernel_contract_fixture_case(world_seed=0)
    setup = build_aucarena_setup(case, suffix="finalize_receipt")
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
    harness = EvidenceRecordingAucArenaHarness(answer=short_path_answer, evidence=evidence)
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

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    declared_leaf_ids = {
        m.BUDGET_INVARIANT_LEAF_ID,
        m.BID_LEGALITY_LEAF_ID,
        m.HAMMER_RULE_LEAF_ID,
        m.PROFIT_VS_FIELD_LEAF_ID,
    }
    assert {score.leaf.leaf_id for score in receipt.scores} == declared_leaf_ids
    assert receipt.primary_leaf_id == m.PROFIT_VS_FIELD_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1
    profit = next(
        score for score in receipt.scores if score.leaf.leaf_id == m.PROFIT_VS_FIELD_LEAF_ID
    )
    assert profit.status == "ok"
