"""Offline replayer for termsbench episodes (spec sections 3.1 and 5).

Given a RECORDED trajectory -- the ordered raw response payloads that already
produced one completed ``EpisodeResult`` -- rebuild the episode purely from
that record and the pinned case, through the same ``TermsBenchPlugin`` /
scheduler machinery, with **zero further random draws**, and reproduce the
final state and every declared score. This is the family-specific instance of
the spec's own replay guarantee (section 3.1): "``step()`` re-executes the
same formula code on the recorded random draws (not re-sampling) so offline
replay is exact."

Unlike ``tau3_retail`` (whose replay guarantee is "re-executing a
deterministic tool is itself the replay check" -- there is a real upstream
bridge to re-invoke), termsbench's counterpart kernel is genuinely stochastic
*at generation time*: every counterpart logical action already carries the
raw random draws it consumed (``kernel.resolve_counterpart_turn``'s ``draws``
argument), sealed directly into that action's own recorded response by
``ScriptedTermsBenchHarness`` (and, durably, as an
``EvidenceStore.append_event`` per round -- see ``harness.py``). Replaying
means serving those exact recorded responses back through the real
scheduler with **no RNG in the loop at all**: ``TermsBenchPlugin.step()``'s
``_step_counterpart`` already re-invokes ``kernel.resolve_counterpart_turn``
on the sealed ``draws`` and hard-fails (``RuntimeError`` -> scheduler's own
``SchedulerContractError``, "counterpart replay mismatch") on any divergence
from what the recorded response claims -- this module adds only the outer
bookkeeping around that guarantee:

* serializing/deserializing the recorded trajectory itself, so a replay can
  genuinely be driven from plain JSON, not a live in-memory object
  (``RecordedEpisode.to_json``/``from_json``);
* re-running ``run_episode`` against that record with a response source that
  draws no random numbers and calls no model (``RecordedResponseSource``);
* comparing every phase-instance state hash, the terminal record, the
  outcome, and the final state against the original run
  (``compare_episode_results``) -- termsbench state carries no wall-clock or
  other non-deterministic field (unlike tau3_retail's per-message
  ``timestamp``), so this comparison is byte-exact, not merely
  content-equivalent;
* recomputing every declared leaf the same way ``measurement.py``'s own
  ``TermsBenchScorer`` does, from the replayed episode's own ``outcome`` dict
  -- never a locally re-derived formula.

No random number is drawn and no tool/model is called anywhere in this
module: every comparison either reuses ``TermsBenchPlugin.step()``'s own
draws-replay-and-verify or ``measurement.py``'s own scorers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode

from .measurement import TermsBenchScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Distinct from a draws-level divergence caught by
    ``TermsBenchPlugin.step()`` itself (which surfaces as
    ``SchedulerContractError`` from inside ``run_episode`` and is allowed to
    propagate unmodified -- that *is* the replay guarantee firing). This
    error covers replay-harness-level problems: a case/record mismatch, a
    phase/seat ordering mismatch against the record, or an unconsumed tail of
    recorded decisions.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern already
    used by ``tau3_retail.replay._plain`` and ``environment.py``'s own
    ``_plain`` helper, so a ``RecordedEpisode`` built from a live,
    scheduler-frozen ``EpisodeResult`` (whose ``MappingProxyType``/tuple
    containers are not JSON-serializable as-is) is guaranteed to be a plain,
    ``json.dumps``-able structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    For a counterpart turn, ``response`` already carries the raw ``draws``
    dict ``kernel.resolve_counterpart_turn`` consumed (see ``harness.py``'s
    ``ScriptedTermsBenchHarness._resolve_counterpart``) -- replay never needs
    to draw a fresh random number, only to re-execute the same formula on
    those sealed numbers, which ``step()`` already does independently.
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
    in the order the scheduler requested them -- nothing about the
    counterpart kernel, scoring, or state is recomputed here; replay
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
    """Serve a fixed, recorded sequence of raw responses -- no RNG, no model.

    Unlike ``ScriptedTermsBenchHarness`` (which draws fresh random numbers
    for every ``counterpart_turn`` request), this response source draws
    nothing at all: every recorded counterpart response already carries the
    ``draws`` it originally consumed, and ``TermsBenchPlugin.step()`` alone
    re-executes ``kernel.resolve_counterpart_turn`` on them and cross-checks.
    This is what makes replay "zero model calls, zero re-sampling" while
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
    """Re-run one recorded episode with zero random draws and zero model calls.

    Rebuilds ``initial_state`` from the pinned case/cell (exactly as a live
    run would) and folds the recorded decisions through the real scheduler.
    Every counterpart draw the record contains is independently re-executed
    and verified by ``TermsBenchPlugin.step()`` against
    ``kernel.resolve_counterpart_turn`` -- a divergence there raises
    ``SchedulerContractError`` and is left to propagate unmodified; that *is*
    the replay guarantee. This function raises ``ReplayError`` only for
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

    Every field is a typed, explicit boolean plus the identifiers that
    produced it -- callers get a specific mismatch, not a single collapsed
    verdict. Unlike ``tau3_retail.replay.StateComparison``, termsbench's
    state carries no wall-clock or other non-deterministic field (no
    messages, no per-call timestamping), so raw state equality and semantic
    (content) equality genuinely coincide here -- there is deliberately only
    one boolean per component rather than a raw/content pair.
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
            f"state hashes differ for {comparison.mismatched_phase_instance_ids!r}"
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
    """Every leaf this case declares, recomputed from a replayed episode.

    ``surplus_efficiency``/``feasible_agreement`` are populated only for an
    Overlap-regime case, ``no_deal_agreement`` only for a No-deal-regime
    case (mirroring ``TermsBenchScorer``'s own regime-conditional
    declaration, spec section 2); ``protocol_compliance`` is always present.
    """

    surplus_efficiency: Any | None
    feasible_agreement: Any | None
    no_deal_agreement: Any | None
    protocol_compliance: Any


def score_replayed_episode(
    *, scorer: TermsBenchScorer, replayed: EpisodeResult
) -> ReplayScoreResult:
    """Recompute every declared leaf from a replayed episode's own outcome.

    Every score is produced by ``measurement.py``'s own scorer functions
    (through ``TermsBenchScorer``), fed the replayed episode's own
    ``outcome`` dict -- never a locally hand-written re-derivation of the
    formulas already covered by ``measurement.py``'s own tests/goldens.
    """
    if not isinstance(replayed.outcome, Mapping):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped outcome"
        )
    outcome = replayed.outcome
    surplus_efficiency = (
        scorer.score_surplus_efficiency(outcome=outcome)
        if scorer.surplus_efficiency_leaf is not None
        else None
    )
    feasible_agreement = (
        scorer.score_feasible_agreement(outcome=outcome)
        if scorer.feasible_agreement_leaf is not None
        else None
    )
    no_deal_agreement = (
        scorer.score_no_deal_agreement(outcome=outcome)
        if scorer.no_deal_agreement_leaf is not None
        else None
    )
    protocol_compliance = scorer.score_protocol_compliance(outcome=outcome)
    return ReplayScoreResult(
        surplus_efficiency=surplus_efficiency,
        feasible_agreement=feasible_agreement,
        no_deal_agreement=no_deal_agreement,
        protocol_compliance=protocol_compliance,
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
        if self.comparison is None:
            # A genuinely offline replay (no original ``EpisodeResult`` in
            # memory) never performed any original-vs-replayed comparison --
            # an explicit, typed "not comparable", never a fabricated
            # "match" (Codex review finding 3).
            return "not_comparable"
        if not self.comparison.matches:
            return "mismatch"
        return "match"


async def replay_and_verify(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    scorer: TermsBenchScorer,
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
