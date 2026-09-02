"""Offline replayer for agenticpay.bilateral episodes (spec section 5).

Given a RECORDED trajectory -- the ordered raw responses
``ScriptedAgenticpayBilateralHarness`` already served for one completed
``EpisodeResult`` -- rebuild the episode purely from that record and the pinned case,
through the same ``AgenticpayBilateralPlugin``/scheduler machinery, with zero further
scripted-policy calls, and reproduce the final state and both measurement leaves. This
is the same guarantee ``tau3_retail.replay`` provides for its own family, adapted to one
real structural difference: this family has no tool-call surface at all (``tools.py``:
none), so there is no ``Tau3RetailPlugin.step()``-style tool re-execution/cross-check to
lean on. What plays that role here is upstream's own bridge call: the seller phase's
``step()`` calls ``AgenticpayBridge.replay_round`` for real on every replayed round too
(never skipped, never mocked) -- ``replay_round`` reconstructs upstream's environment
from scratch and replays its own ordered history, so a genuine divergence from the
original run would surface as a different ``info``/terminal payload, not as an
exception the way a tampered tau3.retail tool result raises
``SchedulerContractError``.

Unlike ``tau3_retail.replay`` (whose ``step()`` re-stamps a fresh wall-clock
``timestamp`` on every message it appends, forcing a content-only, not byte-exact,
comparison -- see that module's ``_strip_message_timestamps``), nothing in this
family's pinned upstream checkout or bridge driver introduces wall-clock time,
randomness, or any other per-call nondeterminism (verified directly: no
``datetime``/``time.time``/``random``/``uuid`` in ``agenticpay/core.py``, the pinned
``single_buyer_product_seller`` env files, or this adapter's own bridge/bridge-driver
modules). So this replayer asserts genuinely byte-identical final state, not merely
content-equal state -- a real, checkable strengthening of the same class of guarantee
tau3_retail's replay makes, not a difference of intent.

Scoring recomputation is also simpler than tau3_retail's own: every leaf this family
declares (``measurement.py``'s four scorers) is a pure function of
``EpisodeResult.terminal``/``round_trace``, already fully determined by upstream's own
``step()`` result -- unlike tau3.retail's DB-equivalence leaf, which needs a fresh
``Tau2Bridge.evaluate_env`` call against the replayed final database. So
``score_replayed_episode`` below takes only a ``AgenticpayBilateralScorer`` and the
replayed ``EpisodeResult``; it makes no bridge call of its own.

No price/contract extraction, legality check, or scoring formula is reimplemented
here: every comparison either reuses the scheduler's own sealed
``EpisodeResult``/``PhaseInstance`` hashes (produced by the real, bridge-backed
``AgenticpayBilateralPlugin.step()``) or ``measurement.py``'s own scorers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from .measurement import AgenticpayBilateralScorer


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Distinct from a genuine domain divergence the bridge itself would surface as a
    different terminal/outcome payload (compared explicitly by
    ``compare_episode_results``/``assert_replay_matches`` below, never swallowed).
    This error covers replay-harness-level problems only: a case/record mismatch, a
    phase/seat ordering mismatch against the record, or an unconsumed tail of recorded
    decisions.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern already used by
    ``environment.py``'s own ``_plain`` helper and ``tau3_retail.replay``'s identical
    helper, so a ``RecordedEpisode`` built from a live, scheduler-frozen
    ``EpisodeResult`` (whose ``MappingProxyType``/tuple containers are not
    JSON-serializable as-is) is guaranteed to be a plain, ``json.dumps``-able structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw ``{"message": <str>}`` payload
    ``LogicalActionRecord.response`` already carries for a completed action --
    replay never needs to re-derive it, only re-feed it.
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
    """The complete, plain-JSON-serializable ordered decision log for one episode.

    ``case_sha256`` binds this record to the exact case content it was captured
    against, not merely its ``case_id`` string (second-review Codex finding 3): a
    case manifest with the same ``case_id`` but tampered constructor kwargs (e.g.
    different reservation prices) hashes to a different ``content_sha256``, and
    ``replay_episode`` refuses to replay a record against a case whose content it
    was never captured against, even when the ``case_id`` strings coincide.
    """

    case_id: str
    case_sha256: str
    decisions: tuple[RecordedDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_sha256": self.case_sha256,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }

    def to_json(self) -> str:
        """Serialize to a JSON string -- a genuinely portable, on-disk record."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecordedEpisode":
        return cls(
            case_id=value["case_id"],
            case_sha256=value["case_sha256"],
            decisions=tuple(
                RecordedDecision.from_dict(decision) for decision in value["decisions"]
            ),
        )

    @classmethod
    def from_json(cls, text: str) -> "RecordedEpisode":
        return cls.from_dict(json.loads(text))


def record_episode(result: EpisodeResult, *, case: CaseManifest) -> RecordedEpisode:
    """Extract the ordered decision log from one already-completed ``EpisodeResult``.

    Pulls exactly the raw ``LogicalActionRecord.response`` for every action, in the
    order the scheduler requested them -- nothing about the bridge call, scoring, or
    state is captured here; replay regenerates all of that independently through
    ``step()``. ``case`` is the exact ``CaseManifest`` this episode was run against
    (the scheduler's own ``run_episode`` already validated ``result.case_id ==
    case.case_id`` before producing ``result``); its ``content_sha256`` is stamped
    onto the record so ``replay_episode`` can later reject a case whose content
    differs, not just one whose ``case_id`` string differs (second-review Codex
    finding 3).
    """
    if case.case_id != result.case_id:
        raise ReplayError(
            f"record_episode's case argument is {case.case_id!r}, but result.case_id "
            f"is {result.case_id!r}"
        )
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
        case_id=result.case_id, case_sha256=case.content_sha256, decisions=tuple(decisions)
    )


class RecordedResponseSource:
    """Serve a fixed, recorded sequence of raw responses -- no scripted policy, no bridge.

    Unlike ``ScriptedAgenticpayBilateralHarness`` (which serves a hand-authored script
    and seals fresh evidence for it), this response source makes no independent
    decision at all: every recorded response is replayed verbatim, in order, and
    ``AgenticpayBilateralPlugin.step()`` alone re-executes the real upstream bridge call
    for the seller phase of each round. This is what makes replay "zero further
    scripted-policy calls" while still exercising the real domain engine.
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
        # MappingProxyType/tuple containers (record_episode built straight from a live
        # EpisodeResult, never round-tripped through to_json/from_json) -- copy.deepcopy
        # cannot copy a mappingproxy, so detach through the same plain-JSON conversion
        # RecordedDecision.to_dict() already uses, which handles both shapes uniformly.
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
    """Re-run one recorded episode with zero further scripted-policy calls.

    Rebuilds ``initial_state`` from the pinned case/cell (exactly as the original run
    would) and folds the recorded decisions through the real scheduler. Every seller-
    phase round the record contains independently re-invokes the real upstream bridge
    call (``AgenticpayBilateralPlugin.step()``'s own ``AgenticpayBridge.replay_round``)
    -- a genuine domain divergence would surface in the replayed terminal/outcome, which
    ``compare_episode_results``/``assert_replay_matches`` check explicitly. This
    function raises ``ReplayError`` only for replay-harness-level problems (wrong case,
    tampered case content, ordering mismatch, unconsumed record).
    """
    if recorded.case_id != case.case_id:
        raise ReplayError(
            f"recorded episode is for case {recorded.case_id!r}, not {case.case_id!r}"
        )
    if recorded.case_sha256 != case.content_sha256:
        # Same case_id, different content (e.g. tampered reservation prices) --
        # second-review Codex finding 3: a record must bind to the exact case
        # content it was captured against, not just the case_id string.
        raise ReplayError(
            f"recorded episode was captured against case {case.case_id!r} content "
            f"{recorded.case_sha256!r}, but the case supplied for replay hashes to "
            f"{case.content_sha256!r} -- refusing to replay a record against "
            "different case content"
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

    Every field is a typed, explicit boolean -- callers get a specific mismatch, not a
    single collapsed verdict. Unlike ``tau3_retail.replay.StateComparison`` (which
    reports a raw, byte-exact family of fields separately from a content-only family,
    because upstream re-stamps a wall-clock timestamp on every message it replays),
    this family's pinned upstream introduces no such nondeterminism (see this module's
    docstring), so ``final_state_matches`` itself is expected to hold -- byte-identical,
    not merely content-equal -- for every episode this replayer runs.
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

    Never raises on a mismatch: returns a typed report so callers (tests, a future
    parity harness) can assert on exactly what diverged.
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
            "phase instance state hashes differ: "
            f"{comparison.mismatched_phase_instance_ids}"
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
    """Every leaf this case declares, recomputed from a replayed episode."""

    deal_reached: Any
    buyer_surplus_share: Any
    seller_surplus_share: Any
    contract_legality: Any | None


def score_replayed_episode(
    *, scorer: AgenticpayBilateralScorer, replayed: EpisodeResult
) -> ReplayScoreResult:
    """Recompute every declared leaf from a replayed episode's own terminal state.

    Every scorer in ``measurement.py`` is a pure function of ``terminal``/
    ``round_trace`` -- both already fully determined by the real, bridge-backed
    ``step()`` calls replay just re-ran -- so no bridge call is made here directly.
    """
    if not isinstance(replayed.terminal, Mapping):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record"
        )
    terminal = replayed.terminal
    contract_legality = None
    if scorer.contract_legality_leaf is not None:
        contract_legality = scorer.score_contract_legality(
            round_trace=terminal["round_trace"]
        )
    return ReplayScoreResult(
        deal_reached=scorer.score_deal_reached(terminal=terminal),
        buyer_surplus_share=scorer.score_buyer_surplus_share(terminal=terminal),
        seller_surplus_share=scorer.score_seller_surplus_share(terminal=terminal),
        contract_legality=contract_legality,
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
        """``"match"``/``"mismatch"`` when a real comparison was made, else
        ``"not_comparable"``.

        Second-review Codex finding 3: ``comparison is None`` means no comparison
        was ever made (no ``original`` run was supplied to ``replay_and_verify``)
        -- an explicit, typed "not comparable", never the same ``"match"`` a real,
        checked byte-identical comparison reports. Collapsing the two previously
        let a genuinely unverified replay report ``"match"`` with no comparison
        behind it.
        """
        if self.comparison is None:
            return "not_comparable"
        return "match" if self.comparison.matches else "mismatch"


async def replay_and_verify(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    scorer: AgenticpayBilateralScorer,
    recorded: RecordedEpisode,
    original: EpisodeResult | None = None,
) -> ReplayReport:
    """End-to-end: replay a recorded episode, compare it, and re-score it.

    ``original`` is optional -- when supplied (e.g. immediately after a live,
    provider-free run), ``comparison`` reports full state-hash-level agreement; when
    absent (e.g. a genuinely offline replay from a previously-written record, with no
    original run in memory), replay still runs and re-scores, and ``comparison`` is
    ``None`` -- an explicit, typed "not comparable" rather than a fabricated match.
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
