"""Tests for the termsbench offline replayer (replay.py, spec sections 3.1, 5).

Self-contained (mirrors ``tests/test_tau3_retail_replay.py``'s own
convention of not importing another test module's helpers): builds its own
cell/harness/evidence around the same two real pilot cases exercised by
``tests/test_termsbench_harness.py``, then replays what those live runs
produced with **zero random draws and zero provider calls**.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    PlanCell,
    RunPlan,
    canonical_json_bytes,
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
from aeread.shared_runner.task.execution import CanonicalResponse, CellExecution, EvidenceStore
from aeread.shared_runner.task.scheduler import SchedulerContractError, run_episode
from aeread_families.termsbench import cases as tb_cases
from aeread_families.termsbench import environment as tb_environment
from aeread_families.termsbench import measurement as m
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

OVERLAP_PILOT_DIR = Path("cases/termsbench_overlap/pilot")
NODEAL_PILOT_DIR = Path("cases/termsbench_nodeal/pilot")
OVERLAP_CASE_ID = "termsbench.overlap.candid.overlap.1000001"
NODEAL_CASE_ID = "termsbench.nodeal.candid.nodeal.1010011"


def _case(pilot_dir: Path, case_id: str) -> CaseManifest:
    path = pilot_dir / f"{case_id}.json"
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
    case = _case(OVERLAP_PILOT_DIR, OVERLAP_CASE_ID)
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
    plugin = register_plugin(registry, regime="overlap")
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    evidence.seal()
    return case, cell, plugin, evidence, result


def _run_live_nodeal(tmp_path: Path, *, suffix: str):
    case = _case(NODEAL_PILOT_DIR, NODEAL_CASE_ID)
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
    plugin = register_plugin(registry, regime="nodeal")
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    evidence.seal()
    return case, cell, plugin, evidence, result


def _run_live_overlap_immediate_accept(tmp_path: Path, *, suffix: str, price: float):
    """A one-round overlap deal: the agent opens at ``price`` and the
    counterpart accepts it immediately (``u_accept=0.0`` forces acceptance
    for any positive acceptance probability). Gives an independently
    hand-derivable ``final_price`` (the agent's own scripted offer),
    unlike ``_run_live_overlap``'s multi-round "moving closer" scenario."""
    case = _case(OVERLAP_PILOT_DIR, OVERLAP_CASE_ID)
    cell = _cell(case, suffix=suffix)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_termsbench_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_termsbench_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    script = [{"decision": "offer", "price": price, "message": "opening"}]
    draws = {1: {"u_accept": 0.0, "opening_noise": 0.0, "sentiment_noise": 0.0}}
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, counterpart_draws_by_round=draws, evidence=evidence
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry, regime="overlap")
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    evidence.seal()
    return case, cell, plugin, evidence, result


def _run_live_overlap_agreement_violation(tmp_path: Path, *, suffix: str):
    """Golden 3's scenario (spec section 4) replayed through the evidence
    store: an unauthorized Accept with no counterpart offer observed yet --
    a critical protocol violation (``invalid_action``), unlike every other
    replay fixture in this file."""
    case = _case(OVERLAP_PILOT_DIR, OVERLAP_CASE_ID)
    cell = _cell(case, suffix=suffix)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_termsbench_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_termsbench_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    script = [{"decision": "accept", "price": None, "message": "premature"}]
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, evidence=evidence
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry, regime="overlap")
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    evidence.seal()
    return case, cell, plugin, evidence, result


def _scorer_for(case: CaseManifest):
    plugin = TermsBenchPlugin(regime=case.payload["regime"])
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
    replay_plugin = register_plugin(registry, regime="overlap")

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


def test_replayed_episode_surplus_efficiency_matches_an_independently_derived_value(
    tmp_path: Path,
) -> None:
    """The test above only compares ``original_scores`` against
    ``replayed_scores`` -- a regression that made
    ``score_surplus_efficiency`` always return e.g. 0 would break both
    sides identically and stay green there (Codex review finding 6). This
    re-derives eq. 56 (``SE+_i = u_A(f_i) / Delta_i``) directly from the
    case's own numbers -- never by calling ``score_surplus_efficiency`` a
    second time -- and checks both sides against that independent value."""
    price = 165.0
    case, cell, plugin, evidence, original = _run_live_overlap_immediate_accept(
        tmp_path, suffix="indep_se", price=price
    )
    evidence.close()
    assert original.terminal["reason"] == "counterpart_accept"
    assert original.terminal["final_price"] == pytest.approx(price)

    recorded = record_episode(original)
    registry = PluginRegistry()
    replay_plugin = register_plugin(registry, regime="overlap")
    replayed = asyncio.run(replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded))

    scorer = _scorer_for(case)
    original_scores = score_replayed_episode(scorer=scorer, replayed=original)
    replayed_scores = score_replayed_episode(scorer=scorer, replayed=replayed)

    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    assert case.payload["agent"]["role"] == "buyer"
    expected_se = (r_a - price) / (r_a - r_b)  # eq. 56, u_A(f)=r_a-f for a buyer agent

    assert original_scores.surplus_efficiency.primary.value == pytest.approx(expected_se)
    assert replayed_scores.surplus_efficiency.primary.value == pytest.approx(expected_se)


def test_replayed_episode_protocol_compliance_matches_an_independently_derived_violation_flag(
    tmp_path: Path,
) -> None:
    """Companion to the surplus-efficiency test above, for leaf 4: a
    regression that made ``score_protocol_compliance`` ignore violations
    (e.g. always return 0) would break both ``original_scores`` and
    ``replayed_scores`` identically and stay green under an
    original-vs-replayed-only comparison (Codex review finding 6). Uses a
    scenario with a genuine critical violation (golden 3's unauthorized
    Accept) and re-derives eq. 66's 0/1 indicator directly from the
    outcome's own ``critical_violations`` dict -- never by calling
    ``score_protocol_compliance`` a second time."""
    case, cell, plugin, evidence, original = _run_live_overlap_agreement_violation(tmp_path, suffix="indep_cv")
    evidence.close()
    assert original.terminal["reason"] == "agreement_violation"
    assert original.terminal["critical_violations"]["invalid_action"] is True

    recorded = record_episode(original)
    registry = PluginRegistry()
    replay_plugin = register_plugin(registry, regime="overlap")
    replayed = asyncio.run(replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded))

    scorer = _scorer_for(case)
    original_scores = score_replayed_episode(scorer=scorer, replayed=original)
    replayed_scores = score_replayed_episode(scorer=scorer, replayed=replayed)

    expected_cv = 1.0 if any(original.outcome["critical_violations"].values()) else 0.0
    assert expected_cv == 1.0  # sanity: this scenario carries a genuine violation

    assert original_scores.protocol_compliance.primary.value == expected_cv
    assert replayed_scores.protocol_compliance.primary.value == expected_cv


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


def test_replay_and_verify_without_an_original_is_not_comparable_not_a_fabricated_match(
    tmp_path: Path,
) -> None:
    """Exercises the genuinely offline entrypoint itself (``replay_and_verify``
    with no ``original``), not a hand-built ``ReplayReport`` -- a previously
    recorded (or tampered) episode replayed with no in-memory
    ``EpisodeResult`` to diff against never had any original-vs-replayed
    comparison performed, so ``status`` must say so explicitly rather than
    reporting the same ``"match"`` a real, checked agreement would report
    (Codex review finding 3)."""
    case, cell, plugin, evidence, original = _run_live_nodeal(tmp_path, suffix="offline")
    evidence.close()
    recorded = record_episode(original)
    scorer = _scorer_for(case)

    registry = PluginRegistry()
    replay_plugin = register_plugin(registry, regime="nodeal")

    report = asyncio.run(
        replay_and_verify(cell=cell, case=case, plugin=replay_plugin, scorer=scorer, recorded=recorded)
    )

    assert report.comparison is None
    assert report.status == "not_comparable"
    assert report.status != "match"


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


# ---------------------------------------------------------------------------
# finalize_family_execution (kernel_scoring_contract_spec.md milestone 3).
# ---------------------------------------------------------------------------


class EvidenceRecordingTermsBenchHarness:
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
    cost machinery (mirrors collusion's/govsim's identically-motivated
    ``EvidenceRecordingCollusionHarness``/``EvidenceRecordingGovsimHarness``).

    ``ScriptedTermsBenchHarness`` (this module's own existing scripted
    response source, imported above) already seals ITS OWN two evidence
    event types (``termsbench_agent_response``, ``termsbench_counterpart_draws``)
    when given an ``EvidenceStore`` -- but neither is
    ``phase_instance_started``/``logical_action_started``, the vocabulary
    ``task.evaluation._replay_family_trajectory`` actually reads, so a
    ``ScriptedTermsBenchHarness``-only run has never produced evidence
    ``finalize_family_execution`` (which calls that replayer internally) can
    replay. Rather than re-implement the agent-script cursor and the
    counterpart kernel's draw/resolve plumbing a second time, this class
    WRAPS one ``ScriptedTermsBenchHarness`` instance (with ``evidence=None``,
    so it never seals its own two event types) for response generation, and
    adds only the generic AttemptExecutor-shaped trail on top.
    """

    def __init__(
        self,
        *,
        world_seed: int,
        script: Sequence[Mapping[str, Any]],
        counterpart_draws_by_round: Mapping[int, Mapping[str, float]] | None = None,
        evidence: EvidenceStore,
    ) -> None:
        self._inner = ScriptedTermsBenchHarness(
            world_seed=world_seed,
            script=script,
            counterpart_draws_by_round=counterpart_draws_by_round,
            evidence=None,
        )
        self._evidence = evidence

    async def __call__(self, request: Any) -> dict[str, Any]:
        response = await self._inner(request)
        self._evidence.append_event(
            "logical_action_started",
            {"request": request},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        # A CanonicalResponse-shaped placeholder purely for replay provenance
        # (``LogicalActionRecord.response``): ``TermsBenchPlugin.parse_action``
        # never reads it -- the scheduler hands it the raw ``response`` dict
        # returned above, unchanged (same contract as ``ScriptedTermsBenchHarness``
        # itself) -- and replay reconstructs ``parse``/``legality`` directly
        # from the "action_parsed"/"action_legality_checked" events below,
        # never from this response.
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

    @property
    def exhausted(self) -> bool:
        return self._inner.exhausted

    def finalize_action(self, record: Any) -> None:
        envelope = record.envelope
        failure_code = None
        if not envelope.valid:
            failure_code = (
                envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
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
            "logical_action_succeeded" if envelope.valid else "logical_action_agent_action_failure"
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

    def episode_completed(self, *, episode_result: Any) -> None:
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


@dataclass(frozen=True, slots=True)
class TermsBenchSetup:
    """A resolved, provider-free ``RunPlan`` for one termsbench case.

    Like govsim/collusion, this family's real runtime never goes through
    ``execute_plan_cell``'s harness/provider stack at all -- every seat is
    answered directly through ``run_episode``'s ``response_source``
    (``ScriptedTermsBenchHarness``/``EvidenceRecordingTermsBenchHarness``
    above). The declared ``minimal_chat`` harness and fixture provider below
    exist purely to satisfy ``resolve_run_plan``'s structural pin/capability
    checks and are never actually invoked.
    """

    plan: RunPlan
    registry: PluginRegistry


_TERMSBENCH_FIXTURE_PROFILE_ID = "termsbench_unused_fixture_profile_v1"
_TERMSBENCH_FIXTURE_PROVIDER_ID = "termsbench_unused_fixture_provider"
_TERMSBENCH_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def _pin(component_id: str, kind: str, source_path: Path, *, version: str = "0.1.0") -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def build_termsbench_setup(case: CaseManifest, *, suffix: str, regime: str) -> TermsBenchSetup:
    """Resolve a real, one-cell ``RunPlan`` for ``case`` (spec section 5.3).

    Every seat shares one placeholder agent profile: this family's real
    runtime never invokes it (see ``TermsBenchSetup``'s own docstring), so
    the harness/provider it names exist only to satisfy
    ``resolve_run_plan``'s structural checks.
    """
    family = tb_environment.family_manifest(regime)
    seat_ids = [seat.id for seat in case.seats]
    primary_estimand = tb_environment.PRIMARY_ESTIMAND_BY_REGIME[regime]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"termsbench_{suffix}_sample_v1",
            "estimand": "fixed_termsbench_case",
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
            "block_id": f"termsbench_{suffix}_block",
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
            "analysis_plan_id": f"termsbench_{suffix}_analysis_v1",
            "estimands": [primary_estimand],
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
            "suite_id": f"termsbench_{suffix}_suite_v1",
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
            "profile_id": _TERMSBENCH_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _TERMSBENCH_FIXTURE_PROVIDER_ID,
                "model": "termsbench_unused_fixture_model_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": {}},
            "prompt": {
                "prompt_id": f"termsbench_{suffix}_prompt_v1",
                "sha256": hashlib.sha256(
                    b"termsbench scripted negotiation: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _TERMSBENCH_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "termsbench_scripted_no_reasoning_v1",
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
            "run_spec_id": f"termsbench_{suffix}_run_spec_v1",
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
    register_plugin(registry, regime=regime)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_path = Path(tb_environment.__file__)
    execution_path = Path(execution_module.__file__)
    measurement_path = Path(m.__file__)

    # measurement.py declares every leaf's validity-domain predicate and
    # scorer implementation under its own distinct component id (see
    # environment.py's family_manifest() docstring on
    # scoring.reference_provider_ids); every one of those must also be
    # pinned here, or EvaluationReceipt._validate_and_freeze_plan_pins
    # rejects the sealed receipt as missing implementations.
    if regime == "overlap":
        reference_pins = (
            _pin(m.DOMAIN_PREDICATE_ID, "reference", environment_path),
            _pin(m.SURPLUS_EFFICIENCY_SCORER_ID, "reference", measurement_path),
            _pin(m.FEASIBLE_AGREEMENT_SCORER_ID, "reference", measurement_path),
            _pin(m.PROTOCOL_COMPLIANCE_SCORER_ID, "reference", measurement_path),
        )
    else:
        reference_pins = (
            _pin(m.DOMAIN_PREDICATE_ID, "reference", environment_path),
            _pin(m.NO_DEAL_AGREEMENT_SCORER_ID, "reference", measurement_path),
            _pin(m.PROTOCOL_COMPLIANCE_SCORER_ID, "reference", measurement_path),
        )
    pins = (
        _pin(family.family.plugin_id, "family_plugin", environment_path),
        _pin(family.scoring.scorer_id, "scorer", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(_TERMSBENCH_FIXTURE_RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
    ) + reference_pins
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
            _TERMSBENCH_FIXTURE_PROVIDER_ID: ProviderCapabilities(
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
    return TermsBenchSetup(plan=plan, registry=registry)


def test_finalize_wires_termsbench_overlap_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """This family has never produced an ``EvaluationReceipt``.
    ``ScriptedTermsBenchHarness`` writes only its own two convenience events
    and never the generic evidence trail
    ``task.evaluation.replay_family_scoring_input`` needs to replay --
    ``EvidenceRecordingTermsBenchHarness`` (this module, above) is what makes
    this reachable. Drives one small, real, provider-free Overlap episode
    end to end through the real finalizer and asserts a receipt comes back
    carrying every one of ``termsbench.overlap``'s three declared leaves.

    Unlike collusion/govsim (whose primary leaf needs a comparison baseline
    that a single episode's ``FamilyScoringInput`` never carries, so their
    receipts are always ``invalid_measurement``/``excluded`` when driven
    through this generic finalizer), every termsbench leaf is computed
    purely from THIS episode's own outcome -- so this receipt is genuinely
    ``status="ok"``, ``inclusion_status="included"``.
    """
    case = CaseManifest.from_dict(tb_cases.build_case("candid", "overlap", 1000046))
    setup = build_termsbench_setup(case, suffix="finalize_overlap", regime="overlap")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_overlap",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    harness = EvidenceRecordingTermsBenchHarness(
        world_seed=case.world_seed,
        script=[{"decision": "offer", "price": 110.0, "message": "opening"}],
        counterpart_draws_by_round={1: {"u_accept": 0.10, "sentiment_noise": 0.0}},
        evidence=evidence,
    )
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
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
    assert {score.leaf.leaf_id for score in receipt.scores} == {
        m.SURPLUS_EFFICIENCY_LEAF_ID,
        m.FEASIBLE_AGREEMENT_LEAF_ID,
        m.PROTOCOL_COMPLIANCE_LEAF_ID,
    }
    assert receipt.primary_leaf_id == m.SURPLUS_EFFICIENCY_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1
    se = next(score for score in receipt.scores if score.leaf.leaf_id == m.SURPLUS_EFFICIENCY_LEAF_ID)
    assert se.status == "ok"
    assert se.primary.value > 0.0
    agr = next(score for score in receipt.scores if score.leaf.leaf_id == m.FEASIBLE_AGREEMENT_LEAF_ID)
    assert agr.status == "ok"
    assert agr.primary.value == 1.0


def test_finalize_wires_termsbench_nodeal_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """Companion to the overlap test above, for ``termsbench.nodeal``'s two
    declared leaves (FAGR-, CritViol%). Six lowball offers with a forced
    walk-away hazard reach ``counterpart_walk_away`` -- no bound price, so
    ``FAGR- == 0`` (no false agreement) -- exactly
    ``tests/test_termsbench_harness.py``'s own No-deal scenario, driven here
    through the real finalizer instead of scored directly."""
    case = CaseManifest.from_dict(tb_cases.build_case("candid", "nodeal", 1010011))
    setup = build_termsbench_setup(case, suffix="finalize_nodeal", regime="nodeal")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_nodeal",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    lowball = max(0.0, r_b - 90.0)
    assert lowball < r_a
    harness = EvidenceRecordingTermsBenchHarness(
        world_seed=case.world_seed,
        script=[{"decision": "offer", "price": lowball, "message": "lowball"}] * 6,
        counterpart_draws_by_round={round_k: {"u_accept": 0.999, "u_walkaway": 0.0} for round_k in range(1, 7)},
        evidence=evidence,
    )
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    assert result.terminal["reason"] == "counterpart_walk_away"
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
    assert {score.leaf.leaf_id for score in receipt.scores} == {
        m.NO_DEAL_AGREEMENT_LEAF_ID,
        m.PROTOCOL_COMPLIANCE_LEAF_ID,
    }
    assert receipt.primary_leaf_id == m.NO_DEAL_AGREEMENT_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1
    fagr = next(score for score in receipt.scores if score.leaf.leaf_id == m.NO_DEAL_AGREEMENT_LEAF_ID)
    assert fagr.status == "ok"
    assert fagr.primary.value == 0.0


def test_finalize_wires_termsbench_nodeal_false_agreement_as_a_legitimate_fagr_minus_one(
    tmp_path: Path,
) -> None:
    """Independent review finding F2: the receipt test above covers only a
    walk-away No-deal episode (``FAGR- == 0.0``). This is the other real
    branch of eq. 60 (Section F.2) through the SAME finalizer path: a
    No-deal-regime case (``Delta_i < 0``, no positive ZOPA) where a price is
    nonetheless bound -- a "false agreement," the wrong outcome for this
    regime, and eq. 60's ``FAGR- = 1`` case.

    Driven entirely through the real formulas, never a hand-constructed
    outcome: the counterpart's own IR gate
    (``kernel.acceptance_probability``'s ``delta_bar < 0.0`` hard return of
    0) guarantees the STOCHASTIC KERNEL itself never accepts an
    IR-violating offer, so the only way a real episode binds a price here
    is the scripted AGENT accepting the counterpart's own (real,
    kernel-computed) offer. ``counterpart_draws_by_round``'s ``u_accept``/
    ``u_walkaway`` overrides only force the counterpart's round-1 turn into
    its "offer" branch (mirroring
    ``test_termsbench_environment.py::test_price_bound_violation_is_flagged_but_does_not_terminate``'s
    identical technique) -- the counterpart's actual offer price is
    computed by ``kernel.resolve_counterpart_turn``'s real opening-price
    formula, never scripted. The agent's second turn then scripts
    ``accept``, binding that real price.

    The receipt must be ``status="ok"``/``inclusion_status="included"``
    with ``termsbench_no_deal_agreement_leaf.primary.value == 1.0`` as a
    legitimate, measured number -- never ``invalid_measurement`` and never
    excluded: ``_value_axis_validity`` gates only on
    ``malformed_action_schema`` (spec section 4 golden 4), and this episode
    has none; the bound price being individually irrational for the agent
    is exactly what makes it a false agreement, not a reason to discard the
    measurement. ``family_manifest("nodeal").measurement.direction ==
    "minimize"`` (confirmed below) -- and
    ``termsbench_no_deal_agreement_leaf.estimand.direction`` is the same
    ``"minimize"`` -- makes ``FAGR- == 1.0`` the WORSE value here (the
    maximum of the leaf's own 0/1 range) and ``FAGR- == 0.0`` (the walk-away
    companion test's value) the better one, the mirror image of AGR+'s
    ``"maximize"`` for Overlap.
    """
    case = CaseManifest.from_dict(tb_cases.build_case("candid", "nodeal", 1010011))
    setup = build_termsbench_setup(case, suffix="finalize_nodeal_false_agreement", regime="nodeal")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    assert family.measurement.direction == "minimize"

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_nodeal_false_agreement",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    # chi="agent_opens" for this pilot case: round 1 is the agent's own
    # opening offer; forcing the counterpart's round-1 turn away from
    # accept/walk-away (both draws pinned high) falls through to its real
    # "offer" branch (kernel.resolve_counterpart_turn, agent_offers
    # non-empty, counterpart_offers still empty -> the opening-price
    # formula) -- never a scripted or hand-picked price. The agent's own
    # second scripted turn then accepts that real counterpart price.
    assert case.payload["chi"] == "agent_opens"
    harness = EvidenceRecordingTermsBenchHarness(
        world_seed=case.world_seed,
        script=[
            {"decision": "offer", "price": 110.0, "message": "opening"},
            {"decision": "accept", "price": None, "message": "deal"},
        ],
        counterpart_draws_by_round={1: {"u_accept": 0.999, "u_walkaway": 0.999}},
        evidence=evidence,
    )
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    assert result.terminal["reason"] == "agent_accept"
    assert result.terminal["final_price"] is not None
    # The bound price is a real false agreement: individually irrational for
    # the agent (an IR critical violation), never a schema failure -- the
    # distinction that keeps this a valid measurement (spec section 4
    # golden 4's own rule: only malformed_action_schema invalidates leaves
    # 1-3, never a plain critical violation).
    assert result.outcome["critical_violations"]["individual_rationality"] is True
    assert result.outcome["malformed_action_schema"] is False

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
    assert {score.leaf.leaf_id for score in receipt.scores} == {
        m.NO_DEAL_AGREEMENT_LEAF_ID,
        m.PROTOCOL_COMPLIANCE_LEAF_ID,
    }
    assert receipt.primary_leaf_id == m.NO_DEAL_AGREEMENT_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1

    fagr = next(score for score in receipt.scores if score.leaf.leaf_id == m.NO_DEAL_AGREEMENT_LEAF_ID)
    assert fagr.status == "ok"
    assert fagr.primary is not None
    assert fagr.primary.value == 1.0
    assert fagr.leaf.estimand.direction == "minimize"
