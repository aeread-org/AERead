"""Offline replayer for tau3.retail episodes (spec section 9).

Given a RECORDED trajectory -- the ordered raw provider responses that
already produced one completed ``EpisodeResult`` -- rebuild the episode
purely from that record and the pinned case, through the same
``Tau3RetailPlugin``/scheduler machinery, with zero further model calls,
and reproduce the final database and the deterministic score. This is what
makes any later claim auditable (spec section 9's "Replay =" guarantee):

    rebuild initial_state from the pinned upstream data, fold the recorded
    parsed actions through step() (whose in-state tool re-execution
    regenerates all tool results deterministically), assert every state
    hash and the terminal outcome, recompute leaf 1 from replayed state +
    gold replay, reproduce leaf 2 from item 8.

``Tau3RetailPlugin.step()`` already re-executes every recorded tool call
through the upstream bridge and hard-fails
(``SchedulerContractError: "tool replay result differs..."``) on any
divergence -- see
``tests/test_tau3_retail_environment.py::test_step_rejects_a_harness_tool_replay_mismatch``.
This module adds the outer bookkeeping around that guarantee:

* serializing/deserializing the recorded trajectory itself (so a replay can
  genuinely be driven from a plain JSON record, not a live in-memory
  object -- ``RecordedEpisode.to_json``/``from_json``);
* re-running ``run_episode`` against that record with a response source
  that makes no model call and executes no tool (the recorded response
  already carries every tool result -- ``step()`` alone re-verifies them);
* comparing every phase-instance state hash, the terminal record, and the
  outcome against the original run (``compare_episode_results``);
* recomputing both measurement leaves the same way ``measurement.py``'s own
  scorers do: leaf 1 delegated to upstream's own evaluator through
  ``Tau2Bridge.evaluate_env`` (never a locally hand-written DB-equality
  check), leaf 2 from already-recorded judge verdicts (never a new judge
  call -- see ``measurement.score_nl_assertions``'s own docstring for why
  that path is deliberately provider-free).

No tool body, database mutation, or scoring rule is reimplemented here:
every comparison either reuses ``Tau3RetailPlugin.step()``'s own tool
re-execution or ``measurement.py``'s own scorers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode

from .measurement import Tau3RetailScorer
from .tau2_bridge import Tau2Bridge


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Distinct from a tool-level divergence caught by ``Tau3RetailPlugin.step()``
    itself (which surfaces as ``SchedulerContractError`` from inside
    ``run_episode`` and is allowed to propagate unmodified -- that *is* the
    replay guarantee firing). This error covers replay-harness-level
    problems: a case/record mismatch, a phase/seat ordering mismatch
    against the record, or an unconsumed tail of recorded decisions.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern already
    used by ``tests/test_tau3_retail_measurement.py``'s ``_load_case`` and
    ``environment.py``'s own ``_plain`` helper, so a ``RecordedEpisode``
    built from a live, scheduler-frozen ``EpisodeResult`` (whose
    ``MappingProxyType``/tuple containers are not JSON-serializable as-is)
    is guaranteed to be a plain, ``json.dumps``-able structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw provider-shaped payload
    ``LogicalActionRecord.response`` already carries for a completed
    action -- for an assistant turn this already includes
    ``tool_executions`` (harness-recorded results and post-call DB hashes),
    so replay never needs to execute a tool itself; ``step()`` re-executes
    each one independently and cross-checks.
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

    Unlike ``ScriptedTau3RetailHarness`` (which drives ``ToolRuntime`` to
    *produce* fresh tool evidence for a live provider-free run), this
    response source makes no tool call at all: every recorded response
    already carries ``tool_executions`` from the original run, and
    ``Tau3RetailPlugin.step()`` alone re-executes and cross-checks them
    against the pinned upstream bridge. This is what makes replay "zero
    model calls, zero re-derivation of tool results ahead of time" while
    still being fully verified.
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
        # to_json/from_json) -- copy.deepcopy cannot copy a mappingproxy
        # (CPython raises "cannot pickle 'mappingproxy' object"), so detach
        # through the same plain-JSON conversion RecordedDecision.to_dict()
        # already uses, which handles both shapes uniformly.
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

    Rebuilds ``initial_state`` from the pinned case/cell (exactly as a live
    run would) and folds the recorded decisions through the real scheduler.
    Every tool call the record contains is independently re-executed and
    verified by ``Tau3RetailPlugin.step()`` against the pinned upstream
    bridge -- a divergence there raises ``SchedulerContractError`` and is
    left to propagate unmodified; that *is* the replay guarantee. This
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


def _strip_message_timestamps(value: Any) -> Any:
    """Drop timestamps when comparing legacy records made before stabilization.

    The live bridge now canonicalizes upstream-generated message timestamps to
    ``None``, so new runs are byte-replayable. This projection remains for
    previously recorded trajectories that contain wall-clock timestamps.
    """
    if isinstance(value, Mapping):
        return {
            key: _strip_message_timestamps(item)
            for key, item in value.items()
            if key != "timestamp"
        }
    if isinstance(value, (list, tuple)):
        return [_strip_message_timestamps(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class StateComparison:
    """Component-level agreement between an original run and its replay.

    Every field is a typed, explicit boolean plus the values that produced
    it -- callers get a specific mismatch, not a single collapsed verdict.

    Raw byte agreement and timestamp-independent semantic agreement remain
    separate so legacy trajectories are diagnosable. New bridge-generated
    trajectories are expected to satisfy both.
    """

    phase_instance_count_matches: bool
    state_hashes_match: bool
    mismatched_phase_instance_ids: tuple[str, ...]
    terminal_matches: bool
    outcome_matches: bool
    final_state_matches: bool
    final_state_content_matches: bool
    original_final_db_sha256: str | None
    replayed_final_db_sha256: str | None

    @property
    def matches(self) -> bool:
        """The semantic replay guarantee: DB, terminal, outcome, and message
        content agree. Legacy timestamp drift remains visible separately via
        ``state_hashes_match`` and ``final_state_matches``."""
        return (
            self.phase_instance_count_matches
            and self.terminal_matches
            and self.outcome_matches
            and self.final_state_content_matches
            and self.original_final_db_sha256 is not None
            and self.original_final_db_sha256 == self.replayed_final_db_sha256
        )


def compare_episode_results(
    original: EpisodeResult, replayed: EpisodeResult
) -> StateComparison:
    """Compare a live run and its offline replay, component by component.

    Never raises on a mismatch: returns a typed report so callers (tests,
    the parity harness) can assert on exactly what diverged.
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

    original_db_hash = (
        original.final_state.get("db_hash")
        if isinstance(original.final_state, Mapping)
        else None
    )
    replayed_db_hash = (
        replayed.final_state.get("db_hash")
        if isinstance(replayed.final_state, Mapping)
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
        final_state_content_matches=canonical_json_bytes(
            _strip_message_timestamps(original.final_state)
        )
        == canonical_json_bytes(_strip_message_timestamps(replayed.final_state)),
        original_final_db_sha256=original_db_hash,
        replayed_final_db_sha256=replayed_db_hash,
    )


def assert_replay_matches(comparison: StateComparison) -> None:
    """Raise ``ReplayError`` with a specific reason if any component diverged."""
    if comparison.matches:
        return
    reasons = []
    if not comparison.phase_instance_count_matches:
        reasons.append("phase instance count differs")
    if not comparison.final_state_content_matches:
        reasons.append("final state content (database + messages) differs")
    if comparison.original_final_db_sha256 != comparison.replayed_final_db_sha256:
        reasons.append(
            "final db hash differs: "
            f"{comparison.original_final_db_sha256!r} != {comparison.replayed_final_db_sha256!r}"
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

    db_state: Any
    nl_assertions: Any | None


def score_replayed_episode(
    *,
    bridge: Tau2Bridge,
    scorer: Tau3RetailScorer,
    replayed: EpisodeResult,
    diagnostics: Mapping[str, Any] | None = None,
    nl_verdicts: Sequence[Mapping[str, Any]] | None = None,
) -> ReplayScoreResult:
    """Recompute both declared leaves from a replayed episode's own state.

    Leaf 1 is recomputed by delegating to upstream's own evaluator via
    ``Tau2Bridge.evaluate_env`` (through ``scorer.score_db_state`` --
    never a locally hand-written DB-equality check); leaf 2, if the case
    declares it and ``nl_verdicts`` are supplied, is reproduced from those
    already-recorded verdicts and never by calling a judge (spec section
    9: "the recorded verdicts are the only reproducible form of the judge
    component").
    """
    if not isinstance(replayed.terminal, Mapping) or not isinstance(
        replayed.final_state, Mapping
    ):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record and final state"
        )
    db_state = scorer.score_db_state(
        bridge=bridge,
        # The scheduler freezes final_state into MappingProxyType/tuple
        # containers (see scheduler.py's _freeze); Tau2Bridge.evaluate_env
        # ships this straight to json.dumps in a subprocess call, so it must
        # be a plain, JSON-native structure first.
        messages=_plain(replayed.final_state["messages"]),
        termination_reason=replayed.terminal["reason"],
        diagnostics=diagnostics,
    )
    nl_assertions = None
    if nl_verdicts is not None and scorer.nl_assertions_leaf is not None:
        nl_assertions = scorer.score_nl_assertions(verdicts=nl_verdicts)
    return ReplayScoreResult(db_state=db_state, nl_assertions=nl_assertions)


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    scores: ReplayScoreResult
    final_db_sha256: str

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
    bridge: Tau2Bridge,
    scorer: Tau3RetailScorer,
    recorded: RecordedEpisode,
    original: EpisodeResult | None = None,
    diagnostics: Mapping[str, Any] | None = None,
    nl_verdicts: Sequence[Mapping[str, Any]] | None = None,
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
        bridge=bridge,
        scorer=scorer,
        replayed=replayed,
        diagnostics=diagnostics,
        nl_verdicts=nl_verdicts,
    )
    final_db_sha256 = replayed.terminal["db_hash"]
    return ReplayReport(
        case_id=case.case_id,
        replayed=replayed,
        comparison=comparison,
        scores=scores,
        final_db_sha256=final_db_sha256,
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
