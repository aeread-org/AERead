"""Offline replayer for ``aucarena`` episodes (spec section 6, milestone 3).

Given a RECORDED trajectory -- the ordered raw scripted responses that
already produced one completed ``EpisodeResult`` -- rebuild the episode
purely from that record and the pinned case, through the same
``AucArenaPlugin``/scheduler machinery, with zero further policy calls, and
reproduce the final state and the four declared leaves' scores. This is what
makes any later claim auditable: rebuild ``initial_state`` from the pinned
case, fold the recorded raw responses through ``step()`` (whose vendored
functions are pure), assert the terminal outcome and state match the
original run byte-for-byte, then recompute every leaf from the replayed
state with ``measurement.py``'s own scorers -- never a locally re-derived
comparison.

Unlike ``tau3_retail.replay`` (which needs a second, independent
``Tau2Bridge``/upstream checkout to prove replay does not merely echo an
in-memory object, and which documents that its own state hashes never
match themselves because every appended message is freshly timestamped by
upstream), this family has no external process to bridge to and no
wall-clock content anywhere in its state: every field of ``initial_state``
and every mutation ``step()`` makes is a pure function of the pinned case
payload, the cell's ``world_seed``, and the recorded responses. Replay
therefore reproduces the final state **byte-identically**, not merely in
content -- the property ``docs/aucarena_adapter_spec.md`` section 6 calls
"exact by construction, not by fixture luck," proven here rather than
merely asserted.

No rule, legality check, or scoring decision is reimplemented here: every
comparison either reuses the real kernel scheduler (``run_episode``) or
``measurement.py``'s own scorers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import ScoreEnvelope
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import DecisionRequest, EpisodeResult, run_episode

from .measurement import AucArenaScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Covers replay-harness-level problems only: a case/record mismatch, a
    phase/seat ordering mismatch against the record, or an unconsumed tail
    of recorded decisions. This family's ``step()`` never independently
    re-verifies a recorded value against a fresh computation the way
    ``Tau3RetailPlugin.step()`` re-executes tool calls (there is nothing
    external to re-execute); a tampered recorded response instead simply
    replays into a genuinely different (but still self-consistent) episode,
    which ``compare_episode_results``/``assert_replay_matches`` catch as an
    explicit, typed mismatch rather than an exception -- see
    ``tests/test_aucarena_replay.py``'s mutation test.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern already
    used by ``environment.py``'s own ``_plain`` helper, so a
    ``RecordedEpisode`` built from a live, scheduler-frozen ``EpisodeResult``
    (whose ``MappingProxyType``/tuple containers are not JSON-serializable
    as-is) is guaranteed to be a plain, ``json.dumps``-able structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw scripted text
    ``LogicalActionRecord.response`` already carries for a completed action
    -- a plain string (or ``""`` for a rule seat's ignored response), never
    anything richer, since this family's decision slots carry no tool calls.
    """

    phase_id: str
    seat_id: str
    response: Any

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
    in the order the scheduler itself requested them -- nothing about
    legality, hammer determination, or scoring is captured here; replay
    regenerates all of that independently through ``step()``.
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
    """Serve a fixed, recorded sequence of raw responses -- no policy call at all.

    Unlike ``ScriptedAucArenaHarness`` (which calls a live policy function to
    *produce* a fresh response), this response source only ever plays back
    what was already recorded, in order, and raises ``ReplayError`` the
    moment the replayed episode's own request ordering disagrees with the
    record.
    """

    def __init__(self, decisions: Sequence[RecordedDecision]) -> None:
        self._decisions = tuple(decisions)
        self._cursor = 0

    async def __call__(self, request: DecisionRequest) -> Any:
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
        return decision.response

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
    """Re-run one recorded episode with zero further policy calls.

    Rebuilds ``initial_state`` from the pinned case/cell (exactly as a live
    run would) and folds the recorded raw responses through the real
    scheduler (``run_episode``). Raises ``ReplayError`` for replay-harness-
    level problems (wrong case, ordering mismatch, unconsumed record) --
    never for a disagreement in the *content* of the replayed episode, which
    is instead surfaced explicitly by ``compare_episode_results``.
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


def _action_classifications(instance: Any) -> dict[str, tuple[Any, ...]]:
    """One seat_id -> (valid, parse.ok, legality.legal-or-None) per recorded
    action in a phase instance.

    ``pre_state_sha256``/``post_state_sha256`` are hashes of the auction's
    numeric *state* only; a tamper that changes an action's validity
    classification without changing any state (e.g. a legal withdraw
    replayed as a malformed response, both "zero mutation" for ``step()``)
    leaves both hashes byte-identical -- see
    ``docs/aucarena_codex_triage.md`` Finding 3. This is compared
    separately so that class of tamper cannot hide behind an unchanged
    state hash.
    """
    return {
        action.seat_id: (
            action.envelope.valid,
            action.parse.ok,
            action.legality.legal if action.legality is not None else None,
        )
        for action in instance.actions
    }


@dataclass(frozen=True, slots=True)
class StateComparison:
    """Component-level agreement between an original run and its replay.

    Every field is a typed, explicit boolean -- callers get a specific
    mismatch, not a single collapsed verdict. Unlike ``tau3_retail``'s own
    comparator (which must separate byte-exact from content-only agreement
    because of upstream's per-message timestamping,
    ``tau3_retail.replay._strip_message_timestamps``), this family's state
    carries no wall-clock content anywhere, so ``final_state_matches`` is
    the one, unqualified, byte-exact replay guarantee -- proven, not merely
    claimed, by ``tests/test_aucarena_replay.py``.
    """

    phase_instance_count_matches: bool
    mismatched_phase_instance_ids: tuple[str, ...]
    mismatched_action_classification_ids: tuple[str, ...]
    terminal_matches: bool
    outcome_matches: bool
    final_state_matches: bool

    @property
    def matches(self) -> bool:
        return (
            self.phase_instance_count_matches
            and not self.mismatched_phase_instance_ids
            and not self.mismatched_action_classification_ids
            and self.terminal_matches
            and self.outcome_matches
            and self.final_state_matches
        )


def compare_episode_results(
    original: EpisodeResult, replayed: EpisodeResult
) -> StateComparison:
    """Compare a live run and its offline replay, component by component.

    Never raises on a mismatch: returns a typed report so callers (tests,
    a future parity harness) can assert on exactly what diverged.
    """
    original_instances = {
        instance.phase_instance_id: instance for instance in original.phase_instances
    }
    replayed_instances = {
        instance.phase_instance_id: instance for instance in replayed.phase_instances
    }
    count_matches = len(original.phase_instances) == len(replayed.phase_instances)
    mismatched_ids: list[str] = []
    mismatched_classification_ids: list[str] = []
    shared_ids = sorted(set(original_instances) & set(replayed_instances))
    for phase_instance_id in shared_ids:
        left = original_instances[phase_instance_id]
        right = replayed_instances[phase_instance_id]
        if (
            left.pre_state_sha256 != right.pre_state_sha256
            or left.post_state_sha256 != right.post_state_sha256
        ):
            mismatched_ids.append(phase_instance_id)
        if _action_classifications(left) != _action_classifications(right):
            mismatched_classification_ids.append(phase_instance_id)
    only_in_original = sorted(set(original_instances) - set(replayed_instances))
    only_in_replayed = sorted(set(replayed_instances) - set(original_instances))
    mismatched_ids.extend(only_in_original)
    mismatched_ids.extend(only_in_replayed)

    return StateComparison(
        phase_instance_count_matches=count_matches,
        mismatched_phase_instance_ids=tuple(sorted(set(mismatched_ids))),
        mismatched_action_classification_ids=tuple(
            sorted(set(mismatched_classification_ids))
        ),
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
    if comparison.mismatched_action_classification_ids:
        reasons.append(
            "action validity/legality classification differs despite an "
            f"unchanged state hash: {comparison.mismatched_action_classification_ids!r}"
        )
    if comparison.mismatched_phase_instance_ids:
        reasons.append(
            "phase instance state hash differs: "
            f"{comparison.mismatched_phase_instance_ids!r}"
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
    """All four declared leaves recomputed from a replayed episode."""

    budget_invariant: ScoreEnvelope
    bid_legality: ScoreEnvelope
    hammer_rule: ScoreEnvelope
    profit_vs_field: ScoreEnvelope

    def to_tuple(self) -> tuple[ScoreEnvelope, ...]:
        return (
            self.budget_invariant,
            self.bid_legality,
            self.hammer_rule,
            self.profit_vs_field,
        )


def score_replayed_episode(
    *, scorer: AucArenaScorer, replayed: EpisodeResult
) -> ReplayScoreResult:
    """Recompute all four declared leaves from a replayed episode's own state.

    Delegates entirely to ``measurement.py``'s own scorer methods -- never a
    locally hand-written re-derivation -- the same scorer instance
    ``AucArenaPlugin.build_scorer`` returns for a live run.
    """
    return ReplayScoreResult(
        budget_invariant=scorer.score_budget_invariant(result=replayed),
        bid_legality=scorer.score_bid_legality(result=replayed),
        hammer_rule=scorer.score_hammer_rule(result=replayed),
        profit_vs_field=scorer.score_profit_vs_field(result=replayed),
    )


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
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
    scorer: AucArenaScorer,
    recorded: RecordedEpisode,
    original: EpisodeResult | None = None,
) -> ReplayReport:
    """End-to-end: replay a recorded episode, compare it, and re-score it.

    ``original`` is optional -- when supplied (e.g. immediately after a live
    provider-free run), ``comparison`` reports full state-hash-level
    agreement; when absent (e.g. a genuinely offline replay from a
    previously-written record, with no original run in memory), replay still
    runs and re-scores, and ``comparison`` is ``None`` -- an explicit, typed
    "not comparable" rather than a fabricated match.
    """
    replayed = await replay_episode(cell=cell, case=case, plugin=plugin, recorded=recorded)
    comparison = (
        compare_episode_results(original, replayed) if original is not None else None
    )
    scores = score_replayed_episode(scorer=scorer, replayed=replayed)
    return ReplayReport(
        case_id=case.case_id, replayed=replayed, comparison=comparison, scores=scores
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
