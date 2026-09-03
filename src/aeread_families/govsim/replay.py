"""Offline replayer for govsim episodes (spec section 5's "Replay").

Given a RECORDED trajectory -- the ordered raw scripted-policy responses
that already produced one completed ``EpisodeResult`` -- rebuild the episode
purely from that record and the pinned case, through the same
``GovsimPlugin``/scheduler machinery, with zero further policy evaluation
and zero network calls, and reproduce the final state and the deterministic
scores. This is the govsim analogue of ``tau3_retail``'s ``replay.py``
(spec section 5: "replays a recorded scripted-action sequence through the
bridge subprocess a second time, asserts every per-round
``resource_in_pool``/``collected_resource`` value and the terminal outcome
match the sealed episode record exactly, and recomputes all five leaves").

Unlike ``tau3_retail`` -- whose ``GovsimPlugin`` (sic; ``Tau3RetailPlugin``)
re-executes and cross-checks every recorded tool call against the pinned
upstream bridge inside ``step()`` itself -- ``GovsimPlugin.step()`` has no
external tool result to cross-check: every call already recomputes the
ENTIRE episode state from scratch by replaying ``reset(seed=...)`` plus the
full ordered action history through the real upstream ``ConcurrentEnv``
(``docs/govsim_adapter_spec.md`` section 7's "per-call stateless replay, not
raw state passing" design note). Replaying the exact same recorded
decisions therefore does not merely reproduce state *content*: because
nothing in this family's state ever carries a wall-clock timestamp or any
other run-to-run-varying field (unlike ``tau3_retail``'s per-message
``timestamp``, see that family's ``replay._strip_message_timestamps``),
two independent runs of the identical recorded decision sequence -- using
the SAME ``PlanCell`` so ``episode_id``/``phase_instance_id``/
``logical_action_id`` derivations line up too -- reproduce ``final_state``,
``terminal``, and ``outcome`` **byte-identically**, not merely
content-equivalently. ``StateComparison`` below is intentionally simpler
than ``tau3_retail``'s (no raw-vs-content split) because that stronger
guarantee genuinely holds here; this is a verified property of this
adapter, not an assumption -- see
``tests/test_govsim_replay.py::test_replay_from_a_json_round_tripped_record_reproduces_the_live_run``.

No upstream arithmetic, tool body, or scoring rule is reimplemented here:
every comparison either reuses ``GovsimPlugin.step()``'s own bridge-backed
recomputation or ``measurement.py``'s own scorers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from .measurement import GovsimScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Distinct from a genuine upstream failure surfaced through the normal
    ``operational_failure`` termination path (that is a valid, scoreable
    outcome, not a replay-harness problem). This error covers
    replay-harness-level problems only: a case/record mismatch, a
    phase/seat ordering mismatch against the record, or an unconsumed tail
    of recorded decisions.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    ``run_episode`` freezes every state/action value it hands back (see
    ``scheduler.py``'s ``_freeze``); a ``RecordedEpisode`` built from a live,
    scheduler-frozen ``EpisodeResult`` carries the same frozen containers,
    which are not directly ``json.dumps``-able -- round-tripping through
    ``canonical_json_bytes`` (the same pattern ``tau3_retail/replay.py``
    already uses) guarantees a plain, JSON-native structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw scripted-policy-shaped payload
    ``LogicalActionRecord.response`` already carries for a completed action
    (``{"quantity": int}`` for ``harvest``, ``{}`` for ``discuss``/
    ``reflect``) -- ``GovsimPlugin.step()`` alone re-derives the resulting
    state by replaying it through the pinned upstream bridge.
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
    in the order the scheduler requested them -- nothing about upstream
    state, scoring, or termination is captured here; replay regenerates all
    of that independently through ``GovsimPlugin.step()``/the pinned bridge.
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
    """Serve a fixed, recorded sequence of raw responses -- no policy evaluation.

    Unlike ``ScriptedGovsimHarness`` (which computes each response fresh
    from ``policies.py`` and the live observation), this response source
    never calls a policy function at all: every recorded response is
    replayed verbatim, in order, and ``GovsimPlugin.step()`` alone
    recomputes the resulting state by replaying the full action history
    through the pinned upstream bridge (spec section 7). This is what makes
    replay "zero policy evaluation, zero further bridge design decisions"
    while still being fully, independently reproduced.
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
        # to_json/from_json) -- detach through the same plain-JSON
        # conversion RecordedDecision.to_dict() already uses, which handles
        # both shapes uniformly.
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
    """Re-run one recorded episode with zero policy evaluation and zero network calls.

    Rebuilds ``initial_state`` from the pinned case/cell (exactly as a live
    run would) and folds the recorded decisions through the real scheduler.
    ``GovsimPlugin.step()`` alone recomputes every round's state by
    replaying the full action history through the pinned upstream bridge --
    a caught upstream assertion there still surfaces as the family's own
    typed ``operational_failure`` termination, never a crash; a genuine
    infrastructure failure (a broken bridge subprocess) still raises
    unmodified. This function raises ``ReplayError`` only for
    replay-harness-level problems (wrong case, ordering mismatch,
    unconsumed record).
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

    Deliberately simpler than ``tau3_retail``'s ``StateComparison`` (no
    raw-vs-content split): this family's state never carries a wall-clock
    timestamp or any other run-to-run-varying field, so -- given the SAME
    ``PlanCell`` for both runs -- the raw, byte-exact comparison IS the
    semantic replay guarantee here (see this module's own docstring).
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
    """All five declared leaves recomputed from a replayed episode's own state."""

    leaves: Mapping[str, Any]


def score_replayed_episode(
    *,
    scorer: GovsimScorer,
    replayed: EpisodeResult,
    baseline_survival_months: float,
    baseline_total_harvest: float,
    baseline_gini: float,
) -> ReplayScoreResult:
    """Recompute all five declared leaves from a replayed episode's own terminal state.

    Delegates entirely to ``GovsimScorer.score_all`` (measurement.py's own
    scoring path, never a locally hand-written check); the three
    comparative leaves' baseline values are supplied by the caller, exactly
    as ``measurement.py`` itself requires (it never re-runs a baseline
    episode -- see that module's own docstring).
    """
    if not isinstance(replayed.terminal, Mapping):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record"
        )
    terminal = _plain(replayed.terminal)
    leaves = scorer.score_all(
        terminal=terminal,
        baseline_survival_months=baseline_survival_months,
        baseline_total_harvest=baseline_total_harvest,
        baseline_gini=baseline_gini,
    )
    return ReplayScoreResult(leaves=leaves)


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    scores: ReplayScoreResult

    @property
    def status(self) -> str:
        """``"match"``/``"mismatch"`` iff an original run was actually
        compared against; ``"not_comparable"`` when ``comparison is None``
        (a genuinely offline replay with no original run in memory -- see
        ``replay_and_verify``'s own docstring). Never conflates "nothing
        was compared" with "compared and agreed": a caller checking
        ``status == "match"`` must not be able to mistake an uncompared
        replay for a verified one.
        """
        if self.comparison is None:
            return "not_comparable"
        return "match" if self.comparison.matches else "mismatch"


async def replay_and_verify(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    scorer: GovsimScorer,
    recorded: RecordedEpisode,
    baseline_survival_months: float,
    baseline_total_harvest: float,
    baseline_gini: float,
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
        replayed=replayed,
        baseline_survival_months=baseline_survival_months,
        baseline_total_harvest=baseline_total_harvest,
        baseline_gini=baseline_gini,
    )
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
