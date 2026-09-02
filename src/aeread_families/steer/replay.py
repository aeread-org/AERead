"""Offline replayer for steer episodes (docs/steer_adapter_spec.md section 5,
"Offline replay").

Given a RECORDED trajectory -- the ordered raw responses that already
produced one completed ``EpisodeResult`` -- rebuild the episode purely from
that record and the pinned, cached corpus row, through the same
``SteerPlugin``/scheduler machinery, with zero further provider calls, and
reproduce the final state and the deterministic score. Mirrors
``aeread_families.tau3_retail.replay``'s shape (``RecordedDecision`` /
``RecordedEpisode`` / ``RecordedResponseSource`` / ``replay_episode`` /
``compare_episode_results`` / ``score_replayed_episode`` /
``replay_and_verify``), but simpler in one load-bearing way: Mode A has no
tools to re-execute and ``SteerPlugin.step()`` never stamps a wall-clock
timestamp into anything it returns (unlike
``Tau3RetailPlugin.step()``'s upstream ``ParticipantMessageBase``
``default_factory=get_now()`` fields -- see
``tau3_retail.replay._strip_message_timestamps``'s docstring for that
family's non-determinism). So this replayer's ``StateComparison`` makes one
claim tau3.retail's own cannot: the RAW, byte-exact final state matches
itself across two independent runs of one trajectory, not just its content.

No state mutation or scoring rule is reimplemented here: every comparison
either reuses the scheduler's own frozen ``EpisodeResult`` fields or
``measurement.py``'s own ``SteerScorer.score``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import ScoreEnvelope
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from .measurement import SteerScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Covers replay-harness-level problems only: a case/record mismatch, a
    phase/seat ordering mismatch against the record, or an unconsumed tail
    of recorded decisions. There is no tool-level divergence to distinguish
    this from (unlike ``tau3_retail.replay.ReplayError``'s docstring, which
    carves out ``SchedulerContractError`` from ``Tau3RetailPlugin.step()``'s
    own tool re-execution) -- Mode A has no tool loop at all.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern
    ``tau3_retail.replay._plain`` already uses, so a ``RecordedEpisode``
    built from a live, scheduler-frozen ``EpisodeResult`` (whose
    ``MappingProxyType``/tuple containers are not JSON-serializable as-is,
    and whose ``response`` may be a plain string) is guaranteed to be a
    plain, ``json.dumps``-able structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw text ``LogicalActionRecord.response``
    already carries for the one logical action this family's single phase
    ever produces -- the same text ``ScriptedSteerHarness`` served.
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
    in the order the scheduler requested them -- nothing about scoring or
    state is captured here; replay regenerates all of that independently
    through ``run_episode``.
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
    """Serve a fixed, recorded sequence of raw responses -- no model, no tools.

    Unlike ``ScriptedSteerHarness`` (which records fresh evidence for a live
    provider-free run), this response source makes no evidence call at all:
    it exists purely to hand back exactly the text a recorded run already
    produced, so replay is "zero provider calls, zero re-derivation of
    anything ahead of time."
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
    run would -- ``SteerPlugin.initial_state`` reads only the locally-cached
    flattened JSON, never pandas or the bridge subprocess, and re-verifies
    ``source_sha256`` every time it does) and folds the recorded decisions
    through the real scheduler. Raises ``ReplayError`` only for
    replay-harness-level problems (wrong case, ordering mismatch, unconsumed
    record).
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

    Every field is a typed, explicit boolean -- callers get a specific
    mismatch, not a single collapsed verdict. Unlike
    ``tau3_retail.replay.StateComparison`` (which must separate a "raw,
    byte-exact" family of fields from a "semantic, timestamp-independent"
    family because ``Tau3RetailPlugin.step()`` re-timestamps every message
    it appends), this family's state carries no such non-determinism
    (``SteerPlugin.step()``'s state is exactly
    ``question_text``/``options``/``termination``/``selected_option_id``/
    ``failure_code`` -- nothing wall-clock-derived), so ``final_state_matches``
    here is the genuine, unqualified byte-exact claim.
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

    Never raises on a mismatch: returns a typed report so callers (tests)
    can assert on exactly what diverged.
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
            "phase instance state hashes differ for: "
            + ", ".join(comparison.mismatched_phase_instance_ids)
        )
    if not comparison.terminal_matches:
        reasons.append("terminal record differs")
    if not comparison.outcome_matches:
        reasons.append("outcome differs")
    if not comparison.final_state_matches:
        reasons.append("final state differs")
    raise ReplayError("replay diverged from the original run: " + "; ".join(reasons))


def score_replayed_episode(
    *, scorer: SteerScorer, replayed: EpisodeResult
) -> ScoreEnvelope:
    """Recompute the one declared leaf from a replayed episode's own outcome.

    Delegates entirely to ``SteerScorer.score`` -- the same scorer path
    ``docs/steer_adapter_spec.md``'s goldens and
    ``tests/test_steer_goldens.py`` already exercise for a live run -- never
    a locally hand-rolled equality check, and never re-derives legality
    itself.
    """
    if not isinstance(replayed.terminal, Mapping) or not isinstance(
        replayed.outcome, Mapping
    ):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record and outcome"
        )
    return scorer.score(replayed.outcome)


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    score: ScoreEnvelope

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
    scorer: SteerScorer,
    recorded: RecordedEpisode,
    original: EpisodeResult | None = None,
) -> ReplayReport:
    """End-to-end: replay a recorded episode, compare it, and re-score it.

    ``original`` is optional -- when supplied (e.g. immediately after a live
    provider-free run), ``comparison`` reports full state agreement; when
    absent (e.g. a genuinely offline replay from a previously-written
    record, with no original run in memory), replay still runs and
    re-scores, and ``comparison`` is ``None`` -- an explicit, typed "not
    comparable" rather than a fabricated match.
    """
    replayed = await replay_episode(cell=cell, case=case, plugin=plugin, recorded=recorded)
    comparison = (
        compare_episode_results(original, replayed) if original is not None else None
    )
    score = score_replayed_episode(scorer=scorer, replayed=replayed)
    return ReplayReport(case_id=case.case_id, replayed=replayed, comparison=comparison, score=score)


__all__ = [
    "RecordedDecision",
    "RecordedEpisode",
    "RecordedResponseSource",
    "ReplayError",
    "ReplayReport",
    "StateComparison",
    "assert_replay_matches",
    "compare_episode_results",
    "record_episode",
    "replay_and_verify",
    "replay_episode",
    "score_replayed_episode",
]
