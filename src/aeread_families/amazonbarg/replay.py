"""Offline replayer for amazonbarg.bilateral episodes (spec section 3, milestone 3).

Given a RECORDED trajectory -- the ordered raw provider responses that
already produced one completed ``EpisodeResult`` -- rebuild the episode
purely from that record and the pinned case, through the same
``AmazonbargPlugin``/scheduler machinery, with zero further model calls, and
reproduce the final state and the delegated score. Mirrors
``tau3_retail/replay.py`` (spec: "milestone 3 is expected to cover the
scripted counterpart harness, parity, and replay ... mirroring
`tau3_retail`'s own `harness.py`/`parity.py`/`replay.py` split"), with one
structural simplification and one strengthened guarantee, both driven by a
real difference between the two benchmarks:

* **Simplification.** amazonbarg has no tool-calling surface at all (spec
  "Governing facts"), so unlike ``Tau3RetailPlugin.step()`` (which
  re-executes and cross-checks every recorded tool call against a live
  upstream bridge), ``AmazonbargPlugin.step()`` has nothing to re-execute --
  it is a pure function of the parsed reply text. Replay's guarantee here is
  therefore established externally, by this module's own
  ``compare_episode_results``, rather than by a built-in re-verification
  inside ``step()`` itself.
* **Strengthened guarantee.** ``tau3_retail``'s own replay only ever matches
  *content*, never the raw sealed state, because ``step()`` re-stamps a
  fresh wall-clock ``timestamp`` on every appended message (see that
  module's ``_strip_message_timestamps`` docstring for the full account).
  ``AmazonbargPlugin.step()`` stamps nothing -- every field it writes is a
  pure function of the parsed reply and the prior state -- so a genuine
  replay of the same recorded decisions reproduces the RAW, byte-exact final
  state, not merely its content. This is verified directly (never assumed)
  by ``tests/test_amazonbarg_replay.py``.

No tool body, database mutation, or scoring rule is reimplemented here:
scoring is recomputed by delegating to upstream's own ``eval.py:Metrics``
through ``measurement.compute_upstream_metrics`` (never a locally
hand-written legality/profit check), exactly as ``measurement.py``'s own
scorers already do for a live run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import ScoreEnvelope
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from . import measurement
from .measurement import AmazonbargScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Covers replay-harness-level problems only: a case/record mismatch, a
    phase/seat ordering mismatch against the record, or an unconsumed tail
    of recorded decisions. Unlike ``tau3_retail``'s own ``ReplayError``,
    there is no distinct tool-level divergence this leaves to propagate as
    a different exception type -- amazonbarg has no tool calls to diverge
    on (see module docstring).
    """


def _plain(value: Any) -> Any:
    """Detach the scheduler's frozen MappingProxyType/tuple containers.

    Mirrors ``tau3_retail/replay.py``'s own ``_plain`` helper: upstream's
    delegated ``Metrics`` and this module's own comparisons both need an
    ordinary, JSON-native structure, never the scheduler's frozen containers.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw ``{"content": "..."}`` payload
    ``LogicalActionRecord.response`` already carries for a completed action
    -- replay never re-derives or re-executes anything, it only re-serves
    this text through the same real ``parse_action``/``step`` hooks.
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
    in the order the scheduler requested them -- nothing about parsing,
    scoring, or state is captured here; replay regenerates all of that
    independently through the real ``AmazonbargPlugin`` hooks.
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
    """Serve a fixed, recorded sequence of raw responses -- no model calls.

    Unlike ``ScriptedAmazonbargHarness`` (which appends a fresh evidence
    event for each decision it *serves live*), this response source makes no
    evidence call at all -- it exists purely to drive the real scheduler
    through an already-recorded trajectory.
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
        # conversion RecordedDecision.to_dict() already uses.
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
    Raises ``ReplayError`` for a replay-harness-level problem (wrong case,
    ordering mismatch, unconsumed record) -- never silently truncates.
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
    Unlike ``tau3_retail``'s own ``StateComparison`` (which must keep a
    "raw, byte-exact" family of fields distinct from a "semantic,
    timestamp-independent" family, because ``step()`` re-stamps a fresh
    wall-clock timestamp on every message), ``AmazonbargPlugin.step()``
    stamps nothing, so ``final_state_matches`` here is expected to read
    ``True`` for a genuine replay -- see module docstring's "strengthened
    guarantee".
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
        """The full replay guarantee: state hashes, terminal, and outcome
        all agree -- byte-exact, not merely content-equivalent (see module
        docstring)."""
        return (
            self.phase_instance_count_matches
            and self.state_hashes_match
            and self.terminal_matches
            and self.outcome_matches
            and self.final_state_matches
            and self.original_final_state_sha256 is not None
            and self.original_final_state_sha256 == self.replayed_final_state_sha256
        )


def _final_state_sha256(result: EpisodeResult) -> str | None:
    """The scheduler's own sealed hash of the last phase instance's post-state.

    Exactly the same ``post_state_sha256`` the scheduler itself computed
    via its internal ``_content_hash`` right after the terminal transition
    (see ``scheduler.py``'s ``run_episode`` loop) -- never independently
    recomputed here.
    """
    if not result.phase_instances:
        return None
    return result.phase_instances[-1].post_state_sha256


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
        original_final_state_sha256=_final_state_sha256(original),
        replayed_final_state_sha256=_final_state_sha256(replayed),
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


def score_replayed_episode(
    *,
    upstream_root: Path,
    scorer: AmazonbargScorer,
    replayed: EpisodeResult,
    tested_seat: str,
) -> dict[str, ScoreEnvelope]:
    """Recompute all five declared leaves the same way ``measurement.py`` does.

    Delegates to upstream's own ``eval.py:Metrics`` through
    ``measurement.compute_upstream_metrics`` (never a locally hand-written
    legality/profit check) on the replayed episode's own recorded
    ``history`` -- never the original run's.
    """
    if not isinstance(replayed.terminal, Mapping) or not isinstance(
        replayed.final_state, Mapping
    ):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record and final state"
        )
    metrics_output = measurement.compute_upstream_metrics(
        upstream_root=upstream_root,
        family_case=scorer.family_case,
        history=_plain(replayed.final_state["history"]),
    )
    return scorer.score_all(metrics_output=metrics_output, tested_seat=tested_seat)


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    scores: Mapping[str, ScoreEnvelope]
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
    upstream_root: Path,
    scorer: AmazonbargScorer,
    recorded: RecordedEpisode,
    tested_seat: str,
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
        upstream_root=upstream_root,
        scorer=scorer,
        replayed=replayed,
        tested_seat=tested_seat,
    )
    return ReplayReport(
        case_id=case.case_id,
        replayed=replayed,
        comparison=comparison,
        scores=scores,
        final_state_sha256=_final_state_sha256(replayed),
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
