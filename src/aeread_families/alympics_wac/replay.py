"""Offline replayer for alympics.wac episodes (spec section 5's "Replay" bullet).

Given a RECORDED trajectory -- the ordered raw per-seat bid responses that
already produced one completed ``EpisodeResult`` -- rebuild the episode
purely from that record and the pinned case, through the same
``AlympicsWacPlugin``/scheduler machinery, with zero further provider calls,
and reproduce the final state and the four declared leaves. This mirrors
``tau3_retail.replay`` (the pattern this module follows), adapted to this
family's simpler, tool-free boundary:

* there is no ``ToolRuntime`` to re-execute and cross-check (this family's
  ``family_manifest`` declares ``needs_tools: False``) -- settlement is
  re-derived purely by ``AlympicsWacPlugin.step`` calling
  ``environment._delegate_round`` again with the recorded bids, exactly as a
  live run would;
* there is no known source of non-determinism analogous to tau3_retail's
  per-message wall-clock ``timestamp`` field (this family's state carries no
  timestamps at all -- ``environment.py``'s ``initial_state``/``step``
  never stamp anything with wall-clock time). ``StateComparison`` here is
  therefore simpler than tau3_retail's: a replayed episode's ``final_state``
  is expected to be **byte-identical** to the original run's, not merely
  content-equivalent modulo a documented field -- and the test suite pins
  that as a checked fact, not an assumption (see
  ``tests/test_alympics_wac_replay.py``).

No settlement rule, tool body, or scoring rule is reimplemented here: every
comparison either replays through ``AlympicsWacPlugin.step`` (itself a thin
wrapper over ``environment._delegate_round``, which is itself a direct,
unmodified call into upstream's own ``_get_salary``/``_check_winner``/
``_round_settlement``) or ``measurement.py``'s own scorers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from .measurement import AlympicsWacScorer
from aeread.shared_runner.measurement import ScoreEnvelope


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Distinct from a divergence inside upstream's own settlement mechanics
    (which this family never expects at replay time -- unlike
    ``tau3_retail``, there is no independent tool-level oracle re-executed
    *during* replay itself; see this module's docstring and the "Known
    limits" note on tampering detection in
    ``docs/alympics_adapter_status.md``). This error covers replay-harness-
    level problems only: a case/record mismatch, a phase/seat ordering
    mismatch against the record, or an unconsumed tail of recorded
    decisions.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern
    ``tau3_retail.replay``'s own ``_plain`` and ``environment.py``'s own
    ``_plain`` already use, so a ``RecordedEpisode`` built from a live,
    scheduler-frozen ``EpisodeResult`` (whose ``MappingProxyType``/tuple
    containers are not JSON-serializable as-is) is guaranteed to be a plain,
    ``json.dumps``-able structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw ``{"bid": <int>}`` payload
    ``LogicalActionRecord.response`` already carries for a completed action
    -- ``AlympicsWacPlugin.parse_action``/``step`` re-derive everything else
    (legality, settlement, termination) from it independently, so replay
    never needs anything more than this.
    """

    phase_id: str
    seat_id: str
    response: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "seat_id": self.seat_id,
            "response": _plain(self.response),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecordedDecision":
        return cls(
            phase_id=value["phase_id"],
            seat_id=value["seat_id"],
            response=value["response"],
        )


@dataclass(frozen=True, slots=True)
class RecordedEpisode:
    """The complete, plain-JSON-serializable ordered decision log for one episode."""

    case_id: str
    decisions: tuple[RecordedDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }

    def to_json(self) -> str:
        """Serialize to a JSON string -- a genuinely portable, on-disk record."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecordedEpisode":
        return cls(
            case_id=value["case_id"],
            decisions=tuple(
                RecordedDecision.from_dict(decision) for decision in value["decisions"]
            ),
        )

    @classmethod
    def from_json(cls, text: str) -> "RecordedEpisode":
        return cls.from_dict(json.loads(text))


def record_episode(result: EpisodeResult) -> RecordedEpisode:
    """Extract the ordered decision log from one already-completed ``EpisodeResult``.

    Pulls exactly the raw ``LogicalActionRecord.response`` for every action,
    in the order the scheduler requested them -- nothing about settlement or
    scoring is captured here; replay regenerates all of that independently
    through ``step()``.
    """
    decisions: list[RecordedDecision] = []
    for instance in result.phase_instances:
        for action in instance.actions:
            decisions.append(
                RecordedDecision(
                    phase_id=instance.phase_id,
                    seat_id=action.seat_id,
                    response=action.response,
                )
            )
    return RecordedEpisode(case_id=result.case_id, decisions=tuple(decisions))


class RecordedResponseSource:
    """Serve a fixed, recorded sequence of raw responses -- no model call.

    Unlike ``ScriptedAlympicsWacHarness`` (which computes a fresh bid from
    each request's own observation), this response source makes no
    computation at all: it simply replays the exact ``{"bid": <int>}``
    payload each seat already produced, in order, and lets
    ``AlympicsWacPlugin.step`` re-derive every legality/settlement/
    termination consequence independently.
    """

    def __init__(self, decisions: Sequence[RecordedDecision]) -> None:
        self._decisions = tuple(decisions)
        self._cursor = 0

    async def __call__(self, request: Any) -> Any:
        if self._cursor >= len(self._decisions):
            raise ReplayError(
                "recorded episode exhausted before the replayed episode terminated"
            )
        decision = self._decisions[self._cursor]
        self._cursor += 1
        if request.phase_id != decision.phase_id or request.seat_id != decision.seat_id:
            raise ReplayError(
                "recorded decision order does not match the replayed request: "
                f"expected phase={decision.phase_id!r} seat={decision.seat_id!r}, "
                f"got phase={request.phase_id!r} seat={request.seat_id!r}"
            )
        # decision.response may still be the scheduler's own frozen
        # MappingProxyType (record_episode built straight from a live
        # EpisodeResult, never round-tripped through to_json/from_json) --
        # copy.deepcopy cannot copy a mappingproxy, so detach through the
        # same plain-JSON conversion RecordedDecision.to_dict() already
        # uses, which handles both shapes uniformly.
        return _plain(decision.response)

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._decisions)


async def replay_episode(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    recorded: RecordedEpisode,
) -> EpisodeResult:
    """Re-run one recorded episode with zero provider calls.

    Rebuilds ``initial_state`` from the pinned case/cell (exactly as a live
    run would) and folds the recorded per-seat bids through the real
    scheduler. This function raises ``ReplayError`` only for replay-
    harness-level problems (wrong case, ordering mismatch, unconsumed
    record); any divergence in upstream's own settlement mechanics would
    surface as whatever exception ``AlympicsWacPlugin.step``/
    ``environment._delegate_round`` themselves raise (unchanged, never
    caught here) -- there is no separate replay-time oracle to compare
    against, unlike ``tau3_retail``'s tool-level re-execution.
    """
    if recorded.case_id != case.case_id:
        raise ReplayError(
            f"recorded episode is for case {recorded.case_id!r}, not {case.case_id!r}"
        )
    response_source = RecordedResponseSource(recorded.decisions)
    result = await run_episode(
        cell=cell, case=case, plugin=plugin, response_source=response_source
    )
    if not response_source.exhausted:
        raise ReplayError(
            "replay terminated before every recorded decision was consumed"
        )
    return result


@dataclass(frozen=True, slots=True)
class StateComparison:
    """Component-level agreement between an original run and its replay.

    Every field is a typed, explicit boolean plus (for phase instances) the
    specific mismatched ids -- callers get a specific divergence, not one
    collapsed verdict.

    Unlike ``tau3_retail.replay.StateComparison`` (which must separate a
    raw, byte-exact check from a timestamp-independent "content" check,
    because tau3_retail's own state carries a per-message wall-clock
    timestamp that never survives two independent runs identically), this
    family's state carries no such field: ``final_state_matches`` is
    expected to be **exactly** true for two runs of the same case through
    the same policy assignment, and the replay test suite pins that as a
    checked fact.
    """

    phase_instance_count_matches: bool
    state_hashes_match: bool
    mismatched_phase_instance_ids: tuple[str, ...]
    terminal_matches: bool
    outcome_matches: bool
    final_state_matches: bool

    @property
    def matches(self) -> bool:
        return (
            self.phase_instance_count_matches
            and self.state_hashes_match
            and self.terminal_matches
            and self.outcome_matches
            and self.final_state_matches
        )


def compare_episode_results(
    original: EpisodeResult, replayed: EpisodeResult
) -> StateComparison:
    """Compare a live run and its offline replay, component by component.

    Never raises on a mismatch: returns a typed report so callers (tests,
    a parity harness) can assert on exactly what diverged.
    """
    original_instances = {
        instance.phase_instance_id: instance for instance in original.phase_instances
    }
    replayed_instances = {
        instance.phase_instance_id: instance for instance in replayed.phase_instances
    }
    count_matches = len(original.phase_instances) == len(replayed.phase_instances)
    mismatched_ids: list[str] = []
    shared_ids = sorted(set(original_instances) & set(replayed_instances))
    for phase_instance_id in shared_ids:
        left = original_instances[phase_instance_id]
        right = replayed_instances[phase_instance_id]
        if (
            left.pre_state_sha256 != right.pre_state_sha256
            or left.post_state_sha256 != right.post_state_sha256
        ):
            mismatched_ids.append(phase_instance_id)
    only_in_original = sorted(set(original_instances) - set(replayed_instances))
    only_in_replayed = sorted(set(replayed_instances) - set(original_instances))
    mismatched_ids.extend(only_in_original)
    mismatched_ids.extend(only_in_replayed)

    return StateComparison(
        phase_instance_count_matches=count_matches,
        state_hashes_match=not mismatched_ids,
        mismatched_phase_instance_ids=tuple(sorted(set(mismatched_ids))),
        terminal_matches=canonical_json_bytes(original.terminal)
        == canonical_json_bytes(replayed.terminal),
        outcome_matches=canonical_json_bytes(original.outcome)
        == canonical_json_bytes(replayed.outcome),
        final_state_matches=canonical_json_bytes(original.final_state)
        == canonical_json_bytes(replayed.final_state),
    )


def assert_replay_matches(comparison: StateComparison) -> None:
    """Raise ``ReplayError`` with a specific reason if any component diverged."""
    if comparison.matches:
        return
    reasons = []
    if not comparison.phase_instance_count_matches:
        reasons.append("phase instance count differs")
    if not comparison.state_hashes_match:
        reasons.append(
            f"phase instance state hashes differ: {comparison.mismatched_phase_instance_ids}"
        )
    if not comparison.terminal_matches:
        reasons.append("terminal record differs")
    if not comparison.outcome_matches:
        reasons.append("outcome differs")
    if not comparison.final_state_matches:
        reasons.append("final state differs")
    raise ReplayError("replay diverged from the original run: " + "; ".join(reasons))


@dataclass(frozen=True, slots=True)
class ReplayScoreResult:
    """All four declared leaves (spec section 2), recomputed from a replayed episode."""

    terminal_wealth: ScoreEnvelope
    survival: ScoreEnvelope
    bid_legality: ScoreEnvelope
    settlement_exactness: ScoreEnvelope


def score_replayed_episode(
    *,
    scorer: AlympicsWacScorer,
    upstream_module: Any,
    focal_seat: str,
    replayed: EpisodeResult,
    baseline_final_players: Mapping[str, Mapping[str, Any]],
    baseline_round_log: Sequence[Mapping[str, Any]],
    evidence_refs: tuple[str, ...] = (),
) -> ReplayScoreResult:
    """Recompute all four declared leaves from a replayed episode's own state.

    ``baseline_final_players``/``baseline_round_log`` come from a *second*,
    independently replayed episode (the same focal seat run under the named
    baseline policy, same supply schedule/opponent panel -- spec section
    2's comparative estimand); recomputing them here would silently
    reintroduce a live provider call or a hand-written baseline, neither of
    which this module ever does. ``upstream_module`` is leaf 4's shadow-
    recompute dependency (:func:`aeread_families.alympics_wac.environment.
    _delegate_round`'s own second parameter), obtained the same way
    ``environment.AlympicsWacPlugin._require_upstream`` already does for a
    live run.
    """
    if not isinstance(replayed.terminal, Mapping) or not isinstance(
        replayed.final_state, Mapping
    ):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record and final state"
        )
    actual_final_players = replayed.final_state["players"]
    actual_round_log = replayed.final_state["round_log"]
    actual_termination_reason = replayed.terminal["reason"]

    terminal_wealth = scorer.score_terminal_wealth(
        focal_seat=focal_seat,
        actual_final_players=actual_final_players,
        actual_round_log=actual_round_log,
        actual_termination_reason=actual_termination_reason,
        baseline_final_players=baseline_final_players,
        evidence_refs=evidence_refs,
    )
    survival = scorer.score_survival(
        focal_seat=focal_seat,
        actual_round_log=actual_round_log,
        actual_final_players=actual_final_players,
        actual_termination_reason=actual_termination_reason,
        baseline_round_log=baseline_round_log,
        baseline_final_players=baseline_final_players,
        evidence_refs=evidence_refs,
    )
    bid_legality = scorer.score_bid_legality(
        focal_seat=focal_seat,
        round_log=actual_round_log,
        termination_reason=actual_termination_reason,
        evidence_refs=evidence_refs,
    )
    settlement_exactness = scorer.score_settlement_exactness(
        focal_seat=focal_seat,
        upstream_module=upstream_module,
        round_log=actual_round_log,
        termination_reason=actual_termination_reason,
        evidence_refs=evidence_refs,
    )
    return ReplayScoreResult(
        terminal_wealth=terminal_wealth,
        survival=survival,
        bid_legality=bid_legality,
        settlement_exactness=settlement_exactness,
    )


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
    focal_seat: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    scores: ReplayScoreResult

    @property
    def status(self) -> str:
        if self.comparison is not None and not self.comparison.matches:
            return "mismatch"
        return "match"


async def replay_and_verify(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    scorer: AlympicsWacScorer,
    upstream_module: Any,
    focal_seat: str,
    recorded: RecordedEpisode,
    baseline_final_players: Mapping[str, Mapping[str, Any]],
    baseline_round_log: Sequence[Mapping[str, Any]],
    original: EpisodeResult | None = None,
) -> ReplayReport:
    """End-to-end: replay a recorded episode, compare it, and re-score it.

    ``original`` is optional -- when supplied (e.g. immediately after a live
    provider-free run), ``comparison`` reports full state-hash-level
    agreement; when absent (e.g. a genuinely offline replay from a
    previously-written record, with no original run in memory), replay
    still runs and re-scores, and ``comparison`` is ``None`` -- an explicit,
    typed "not comparable" rather than a fabricated match.
    """
    replayed = await replay_episode(cell=cell, case=case, plugin=plugin, recorded=recorded)
    comparison = (
        compare_episode_results(original, replayed) if original is not None else None
    )
    scores = score_replayed_episode(
        scorer=scorer,
        upstream_module=upstream_module,
        focal_seat=focal_seat,
        replayed=replayed,
        baseline_final_players=baseline_final_players,
        baseline_round_log=baseline_round_log,
    )
    return ReplayReport(
        case_id=case.case_id,
        focal_seat=focal_seat,
        replayed=replayed,
        comparison=comparison,
        scores=scores,
    )


__all__ = [
    "RecordedDecision",
    "RecordedEpisode",
    "RecordedResponseSource",
    "ReplayError",
    "ReplayReport",
    "ReplayScoreResult",
    "StateComparison",
    "assert_replay_matches",
    "compare_episode_results",
    "record_episode",
    "replay_and_verify",
    "replay_episode",
    "score_replayed_episode",
]
