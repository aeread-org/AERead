"""Offline replayer for ``collusion`` episodes (spec section 5's "offline
replay" test plan; pattern: ``tau3_retail/replay.py``).

Given a RECORDED trajectory -- the ordered raw provider responses that
already produced one completed ``EpisodeResult`` -- rebuild the episode
purely from that record and the pinned case, through the same
``CollusionPlugin``/scheduler machinery, with zero further model calls
(zero provider calls at all: this family has never had one, spec section
1), and reproduce the final state and the four measurement leaves exactly:

    rebuild ``initial_state`` from the pinned case, fold the recorded
    per-round price submissions through ``step()`` (whose demand/profit
    transition is pure closed-form arithmetic, spec section 2.1), assert
    every phase-instance state hash and the terminal outcome, recompute all
    four leaves from the replayed outcome via ``measurement.py``'s own
    ``CollusionScorer`` (spec section 5).

Unlike ``tau3_retail``'s replayer, ``CollusionPlugin.step()`` never
delegates to an upstream bridge and never re-executes a tool -- there is
nothing here to independently re-verify a recorded response against (spec
section 3: "AERead owns everything executable"). The replay guarantee this
module provides is instead that folding the exact same recorded price
sequence through the same pure transition function reproduces the *entire*
frozen state byte-for-byte, not merely its economically meaningful content:
``environment.py``'s state carries no wall-clock timestamp or other
non-reproducible field (contrast ``tau3_retail.replay``'s own
``_strip_message_timestamps``, whose docstring explains why tau3's own raw
state can never match itself byte-for-byte across two runs of one
trajectory -- that source of noise does not exist here), so a genuine
replay's raw, sealed state hashes are expected to match the original run's
exactly, not merely their derived content.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import ScoreEnvelope
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode

from .measurement import CollusionScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Covers replay-harness-level problems only: a case/record mismatch, a
    phase/seat ordering mismatch against the record, or an unconsumed tail
    of recorded decisions. A genuine transition-level divergence would
    surface from ``run_episode`` itself as a ``SchedulerContractError`` (the
    scheduler's own pre/post state-hash contract, ``scheduler.py``'s
    ``_content_hash``) and is left to propagate unmodified.
    """


def _outcome_sha256(outcome: Mapping[str, Any]) -> str:
    """The one digest function both the seal (:func:`record_episode`) and
    the verification (:func:`replay_and_verify`) use, so "the same outcome"
    always means "the same hash of the canonical JSON bytes" in exactly one
    place.
    """
    return hashlib.sha256(canonical_json_bytes(outcome)).hexdigest()


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern
    ``tau3_retail.replay``'s own ``_plain`` and ``environment.py``'s own
    ``_plain`` already use, so a ``RecordedEpisode`` built from a live,
    scheduler-frozen ``EpisodeResult`` (whose ``MappingProxyType``/tuple
    containers are not JSON-serializable as-is) is guaranteed to be a
    plain, ``json.dumps``-able structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw
    response (spec section 3's ``{"price": <float>}`` action shape, or any
    other response shape ``parse_action`` accepts)."""

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
    """The complete, plain-JSON-serializable ordered decision log for one episode.

    Three identity/integrity fields beyond ``case_id`` and ``decisions``
    (found missing in review):

    * ``case_content_sha256`` -- the exact case content this recording was
      produced against (``CaseManifest.content_sha256``), not merely its
      ``case_id``. A ``case_id`` alone survives a content edit (same id,
      different demand/cost/ceiling parameters, a recomputed but still
      valid manifest digest) -- ``replay_episode`` rejects a mismatch on
      either field, not just ``case_id`` (collusion codex triage, Finding
      4: "replay identity is bound only to case ID").
    * ``cell_id`` -- the resolved run cell (``PlanCell.cell_id``:
      case x block x seed x repetition execution unit, ``resolver.py``)
      this recording was produced under. ``case_content_sha256`` alone
      proves the case's own economics are unchanged, but says nothing about
      *which cell* produced the recording -- a recording could otherwise be
      replayed unnoticed under a different, merely case-compatible cell
      (collusion codex triage, Finding 4's own "run-cell identity" half;
      independent second-pass review, ``docs/collusion_fix_
      verification.md``: "no test exercises replay under a different
      compatible cell").
    * ``expected_final_outcome_sha256`` -- a seal over the *original* run's
      own terminal outcome, captured once at record time. A genuinely
      offline replay (no ``original`` ``EpisodeResult`` held in memory to
      compare against) has nothing else to verify a tampered recording
      against; without this seal, ``ReplayReport.status`` could only ever
      report "match" when there is no comparison to make, not a real
      verification (collusion codex triage, Finding 3: "unverified offline
      replay reports match").
    """

    case_id: str
    case_content_sha256: str
    cell_id: str
    decisions: tuple[RecordedDecision, ...]
    expected_final_outcome_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_content_sha256": self.case_content_sha256,
            "cell_id": self.cell_id,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "expected_final_outcome_sha256": self.expected_final_outcome_sha256,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string -- a genuinely portable, on-disk record."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecordedEpisode":
        return cls(
            case_id=value["case_id"],
            case_content_sha256=value["case_content_sha256"],
            cell_id=value["cell_id"],
            decisions=tuple(
                RecordedDecision.from_dict(decision) for decision in value["decisions"]
            ),
            expected_final_outcome_sha256=value["expected_final_outcome_sha256"],
        )

    @classmethod
    def from_json(cls, text: str) -> "RecordedEpisode":
        return cls.from_dict(json.loads(text))


def record_episode(
    result: EpisodeResult, *, case: CaseManifest, cell: PlanCell
) -> RecordedEpisode:
    """Extract the ordered decision log from one already-completed
    ``EpisodeResult``, sealed against the exact case and run cell it was
    produced under.

    Pulls exactly the raw ``LogicalActionRecord.response`` for every
    logical action, in the order the scheduler requested them (spec
    section 3's phase graph: both seats per round, ``firm_a`` then
    ``firm_b``) -- nothing about the transition or scoring is captured
    here; replay regenerates all of that independently through ``step()``.
    ``case`` binds this recording to ``case.content_sha256`` (not merely
    ``case.case_id``), ``cell`` binds it to ``cell.cell_id`` (not merely a
    case-compatible cell), and ``result.outcome`` is sealed as
    ``expected_final_outcome_sha256`` -- all three read back by
    ``replay_episode``/``replay_and_verify`` (see ``RecordedEpisode``'s own
    docstring; collusion codex triage findings 3 and 4).
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
    return RecordedEpisode(
        case_id=result.case_id,
        case_content_sha256=case.content_sha256,
        cell_id=cell.cell_id,
        decisions=tuple(decisions),
        expected_final_outcome_sha256=_outcome_sha256(result.outcome),
    )


class RecordedResponseSource:
    """Serve a fixed, recorded sequence of raw responses -- no model, no
    policy, no evidence store: genuinely zero further computation beyond
    replaying the exact recorded values in order.
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
    """Re-run one recorded episode with zero model calls and zero policy
    re-evaluation.

    Rebuilds ``initial_state`` from the pinned case/cell (exactly as the
    original run did) and folds the recorded decisions through the real
    scheduler. Raises ``ReplayError`` only for replay-harness-level problems
    (wrong case, changed case content, ordering mismatch, unconsumed
    record); a genuine transition-level contract violation would instead
    surface unmodified from ``run_episode`` itself (module docstring).

    Checks ``case_id``, ``case_content_sha256``, *and* ``cell_id`` -- a
    case_id match alone does not prove the case's own economics are
    unchanged, and a matching case (id and content both) does not prove
    the *run cell* is the one this recording was produced under (collusion
    codex triage, Finding 4: same case_id, different demand/cost
    parameters, a recomputed but still valid manifest digest, would
    otherwise pass the case_id check alone and replay the old decisions
    against the wrong economics; a recording made under one cell replayed
    under a different, merely case-compatible cell would otherwise pass
    both case checks and be silently accepted).
    """
    if recorded.case_id != case.case_id:
        raise ReplayError(
            f"recorded episode is for case {recorded.case_id!r}, not {case.case_id!r}"
        )
    if recorded.case_content_sha256 != case.content_sha256:
        raise ReplayError(
            f"recorded episode's case content digest {recorded.case_content_sha256!r} "
            f"does not match case {case.case_id!r}'s current content digest "
            f"{case.content_sha256!r} -- the case content changed since this "
            "episode was recorded"
        )
    if recorded.cell_id != cell.cell_id:
        raise ReplayError(
            f"recorded episode was produced under cell {recorded.cell_id!r}, "
            f"not the supplied cell {cell.cell_id!r} -- replaying a recording "
            "under a different run cell is rejected even when the case matches"
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
    mismatch, not a single collapsed verdict. Unlike ``tau3_retail.replay``'s
    identically named class, this family's state carries no non-reproducible
    field (module docstring), so ``final_state_matches`` genuinely is the
    raw, byte-exact comparison *and* the semantic replay guarantee at once --
    there is no separate "content-only" fallback to fall back to.
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


def score_replayed_episode(
    *,
    scorer: CollusionScorer,
    replayed: EpisodeResult,
    baseline_profit_by_seat: Mapping[str, float] | None = None,
) -> dict[str, ScoreEnvelope]:
    """Recompute every declared leaf from a replayed episode's own outcome.

    Never re-derives ``baseline_profit_by_seat`` here -- the caller supplies
    the same named baseline value the original run used (spec section 2,
    leaf 4); this function only re-applies ``CollusionScorer.score_all`` to
    the replayed (not the original) trajectory.
    """
    if not isinstance(replayed.outcome, Mapping):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped outcome"
        )
    return scorer.score_all(
        replayed.outcome, baseline_profit_by_seat=baseline_profit_by_seat
    )


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode.

    ``digest_verified`` closes a gap found in review (collusion codex
    triage, Finding 3): when ``comparison`` is ``None`` (a genuinely
    offline replay, no ``original`` ``EpisodeResult`` held in memory),
    ``status`` used to report "match" unconditionally -- a tampered
    recording replayed with no ``original`` around to catch it would still
    be reported as verified. ``digest_verified`` instead compares the
    freshly replayed outcome's own ``final_outcome_sha256`` against
    ``RecordedEpisode.expected_final_outcome_sha256`` -- a seal captured
    from the *original* run at record time (:func:`record_episode`) -- so a
    tampered recording is caught even with no live ``original`` to compare
    against.
    """

    case_id: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    scores: Mapping[str, ScoreEnvelope]
    final_outcome_sha256: str
    digest_verified: bool

    @property
    def status(self) -> str:
        if not self.digest_verified:
            return "mismatch"
        if self.comparison is not None and not self.comparison.matches:
            return "mismatch"
        return "match"


async def replay_and_verify(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    scorer: CollusionScorer,
    recorded: RecordedEpisode,
    original: EpisodeResult | None = None,
    baseline_profit_by_seat: Mapping[str, float] | None = None,
) -> ReplayReport:
    """End-to-end: replay a recorded episode, compare it, and re-score it.

    ``original`` is optional -- when supplied (e.g. immediately after a
    live provider-free harness run), ``comparison`` reports full state-hash-
    level agreement; when absent (e.g. a genuinely offline replay from a
    previously-written record, with no original run in memory), replay
    still runs and re-scores, and ``comparison`` is ``None`` -- an explicit,
    typed "not comparable" rather than a fabricated match. Either way,
    ``recorded.expected_final_outcome_sha256`` (sealed at record time) is
    always checked against the freshly replayed outcome, so ``status`` can
    report a genuine "mismatch" even with ``comparison is None`` (found in
    review: an offline replay of a tampered recording must not be reported
    as "match" just because there was nothing live to compare against --
    collusion codex triage, Finding 3).
    """
    replayed = await replay_episode(cell=cell, case=case, plugin=plugin, recorded=recorded)
    comparison = (
        compare_episode_results(original, replayed) if original is not None else None
    )
    scores = score_replayed_episode(
        scorer=scorer,
        replayed=replayed,
        baseline_profit_by_seat=baseline_profit_by_seat,
    )
    final_outcome_sha256 = _outcome_sha256(replayed.outcome)
    digest_verified = final_outcome_sha256 == recorded.expected_final_outcome_sha256
    return ReplayReport(
        case_id=case.case_id,
        replayed=replayed,
        comparison=comparison,
        scores=scores,
        final_outcome_sha256=final_outcome_sha256,
        digest_verified=digest_verified,
    )


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
