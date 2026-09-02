"""Offline replayer for econevals episodes (mirrors ``tau3_retail.replay``).

Given a RECORDED trajectory -- the ordered raw harness responses that
already produced one completed ``EpisodeResult`` -- rebuild the episode
purely from that record and the pinned case, through the same
``EconevalsPlugin``/scheduler machinery, with zero further model calls, and
reproduce the final state and both declared measurement leaves.

``EconevalsPlugin.step()`` already re-executes every recorded tool call
through ``dispatch_read_only``/``dispatch_submit`` (which delegate to the
pinned upstream bridge for the one terminating submit call per period) and
hard-fails (``RuntimeError``) on any divergence -- see
``tests/test_econevals_environment.py::test_step_rejects_a_harness_tool_replay_mismatch``.
This module adds the outer bookkeeping around that guarantee:

* serializing/deserializing the recorded trajectory itself (so a replay can
  genuinely be driven from a plain JSON record, not a live in-memory
  object -- ``RecordedEpisode.to_json``/``from_json``);
* re-running ``run_episode`` against that record with a response source
  that makes no model call and executes no tool itself (the recorded
  response already carries every tool result -- ``step()`` alone
  re-verifies them against a fresh bridge call);
* comparing every phase-instance state hash, the terminal record, and the
  outcome against the original run (``compare_episode_results``);
* recomputing both measurement leaves the same way ``measurement.py``'s own
  ``EconevalsScorer.score_terminal_state`` does -- reading the replayed
  episode's own final ``attempts`` list, never re-deriving a value from the
  bridge a second time (``measurement.py``'s scorers read already-produced
  evidence, they do not delegate to the bridge themselves; see that
  module's own docstring).

No tool body, bridge call, or scoring rule is reimplemented here: every
comparison either reuses ``EconevalsPlugin.step()``'s own tool
re-execution or ``measurement.py``'s own scorer.

Unlike tau3.retail's state (whose messages upstream re-timestamps on every
``model_validate``, forcing ``tau3_retail.replay`` to compare "content"
rather than raw bytes), econevals's FSM state
(``track``/``period``/``termination``/``notes``/``attempts``) is entirely
AERead's own, deterministic data with no wall-clock field anywhere --
``compare_episode_results`` below asserts genuinely BYTE-IDENTICAL final
state, not just content-equivalent state, and there is no
``_strip_message_timestamps``-style helper needed at all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import ScoreEnvelope
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from .measurement import EconevalsScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Distinct from a tool-level divergence caught by ``EconevalsPlugin.step()``
    itself (which surfaces as a ``RuntimeError``/``SchedulerContractError``
    from inside ``run_episode`` and is allowed to propagate unmodified --
    that *is* the replay guarantee firing). This error covers
    replay-harness-level problems: a case/record mismatch, a phase/seat
    ordering mismatch against the record, or an unconsumed tail of recorded
    decisions.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern already
    used by ``environment.py``'s own ``_plain`` helper and
    ``tau3_retail.replay``'s identically-named function, so a
    ``RecordedEpisode`` built from a live, scheduler-frozen
    ``EpisodeResult`` (whose ``MappingProxyType``/tuple containers are not
    JSON-serializable as-is) is guaranteed to be a plain, ``json.dumps``-able
    structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw harness-shaped payload
    ``LogicalActionRecord.response`` already carries for a completed
    action -- ``{"tool_calls", "tool_executions"}`` for econevals's one
    self-looping period phase -- so replay never needs to execute a tool
    itself; ``step()`` re-executes each one independently and cross-checks.
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
    in the order the scheduler requested them -- nothing about tool
    execution, scoring, or state is captured here; replay regenerates all
    of that independently through ``step()``.
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

    Unlike ``harness.ScriptedEconevalsHarness`` (which drives ``ToolRuntime``
    to *produce* fresh tool evidence for a live provider-free run), this
    response source makes no tool call at all: every recorded response
    already carries ``tool_executions`` from the original run, and
    ``EconevalsPlugin.step()`` alone re-executes and cross-checks them
    against the pinned upstream bridge. This is what makes replay "zero
    model calls" while still being fully verified.
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
        # MappingProxyType/tuple containers (record_episode built straight
        # from a live EpisodeResult, never round-tripped through
        # to_json/from_json) -- copy.deepcopy cannot copy a mappingproxy, so
        # detach through the same plain-JSON conversion
        # RecordedDecision.to_dict() already uses, which handles both
        # shapes uniformly.
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
    """Re-run one recorded episode with zero model calls.

    Rebuilds the FSM's ``initial_state`` from the pinned case/cell (exactly
    as a live run would) and folds the recorded decisions through the real
    scheduler. Every tool call the record contains is independently
    re-executed and verified by ``EconevalsPlugin.step()`` against the
    pinned upstream bridge -- a divergence there raises ``RuntimeError`` and
    is left to propagate unmodified; that *is* the replay guarantee. This
    function raises ``ReplayError`` only for replay-harness-level problems
    (wrong case, ordering mismatch, unconsumed record).
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

    Every field is a typed, explicit boolean plus the values that produced
    it -- callers get a specific mismatch, not a single collapsed verdict.
    Unlike ``tau3_retail.replay.StateComparison`` (whose raw state can never
    byte-match itself because of upstream message re-timestamping), every
    field here is expected to read ``True`` for a genuine econevals replay:
    this family's FSM state carries no wall-clock field anywhere, so replay
    reproduces the final state BYTE-IDENTICALLY, not merely content-
    equivalently.
    """

    phase_instance_count_matches: bool
    state_hashes_match: bool
    mismatched_phase_instance_ids: tuple[str, ...]
    terminal_matches: bool
    outcome_matches: bool
    final_state_matches: bool
    original_final_state_sha256: str | None
    replayed_final_state_sha256: str | None

    @property
    def matches(self) -> bool:
        return (
            self.phase_instance_count_matches
            and self.state_hashes_match
            and self.terminal_matches
            and self.outcome_matches
            and self.final_state_matches
            and self.original_final_state_sha256 is not None
            and self.original_final_state_sha256 == self.replayed_final_state_sha256
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

    original_hash = (
        original.phase_instances[-1].post_state_sha256
        if original.phase_instances
        else None
    )
    replayed_hash = (
        replayed.phase_instances[-1].post_state_sha256
        if replayed.phase_instances
        else None
    )

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
        original_final_state_sha256=original_hash,
        replayed_final_state_sha256=replayed_hash,
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
    if comparison.original_final_state_sha256 != comparison.replayed_final_state_sha256:
        reasons.append(
            "final state hash differs: "
            f"{comparison.original_final_state_sha256!r} != "
            f"{comparison.replayed_final_state_sha256!r}"
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
    """Both measurement leaves recomputed from a replayed episode."""

    gate: ScoreEnvelope
    objective: ScoreEnvelope | None


def score_replayed_episode(
    *, scorer: EconevalsScorer, replayed: EpisodeResult
) -> ReplayScoreResult:
    """Recompute both declared leaves from a replayed episode's own final state.

    Delegates entirely to ``EconevalsScorer.score_terminal_state`` -- the
    SAME scorer a live run's own ``build_scorer`` hook returns -- reading
    the replayed episode's own recorded ``attempts`` list; no bridge call
    happens here (``measurement.py``'s scorers never delegate to the
    bridge, see that module's own docstring).
    """
    if not isinstance(replayed.final_state, Mapping):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped final state"
        )
    gate, objective = scorer.score_terminal_state(_plain(replayed.final_state))
    return ReplayScoreResult(gate=gate, objective=objective)


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    scores: ReplayScoreResult
    final_state_sha256: str | None

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
    scorer: EconevalsScorer,
    recorded: RecordedEpisode,
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
    scores = score_replayed_episode(scorer=scorer, replayed=replayed)
    final_state_sha256 = (
        replayed.phase_instances[-1].post_state_sha256
        if replayed.phase_instances
        else None
    )
    return ReplayReport(
        case_id=case.case_id,
        replayed=replayed,
        comparison=comparison,
        scores=scores,
        final_state_sha256=final_state_sha256,
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
