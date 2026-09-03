"""Offline replayer for negarena episodes (spec section 5, "tau3 replay.py
is the pattern").

Given a RECORDED trajectory -- the ordered raw scripted responses that
already drove one completed ``EpisodeResult`` through the real scheduler --
rebuild the episode purely from that record and the pinned case, through
the same ``NegarenaPlugin``/``run_episode`` machinery, with zero further
*provider* (model) calls, and reproduce the final state and both
deterministic measurement leaves:

    rebuild ``initial_state`` from the pinned case/cell (exactly as a live
    run would) and fold the recorded raw responses through
    ``NegarenaPlugin.parse_action``/``legal``/``step`` (unchanged -- this
    module reimplements none of them), assert every phase-instance state
    hash and the terminal/outcome record, then recompute leaf 1
    (``negarena_seat_outcome``, per seat) and leaf 2
    (``negarena_agreement_reached``) the same way ``measurement.py``'s own
    scorers already do (spec section 3: "settlement computation ...
    executed via the bridge, never reimplemented").

Unlike ``tau3_retail``'s replayer, negarena's own family state carries no
per-message wall-clock timestamp or any other cross-run non-determinism
(``environment.py``'s ``initial_state``/``step`` build only ``iteration``,
``termination``, ``last_trade``, ``last_answer``, and ``history`` -- all
pure functions of the scripted response text and the prior state, via the
bridge's own deterministic parser). So, unlike
``tau3_retail.replay.StateComparison`` (which must distinguish a raw,
byte-exact state-hash comparison from a timestamp-independent "content"
comparison), a negarena replay is expected to match byte-for-byte at every
level, including the raw per-phase-instance state hashes -- this module
reports that as one property, not two.

"Zero provider calls" means zero *model*/LLM calls: replay still calls
``NegarenaBridge`` (a subprocess delegate to the pinned upstream checkout's
own deterministic parser/admission-gate/settlement code, exactly like the
live run did) via the plugin's own ``parse_action``/``legal``/``build_scorer``
hooks and via ``score_replayed_episode``'s settlement re-scoring -- the same
sense in which ``tau3_retail.replay`` re-executes tool calls through its own
bridge during replay. Negarena never had a model provider anywhere in its
family plugin to begin with (every scripted response here is already
provider-free), so this guarantee is automatic rather than something this
module has to additionally enforce.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from .cases import BLUE, RED
from .measurement import NegarenaScorer
from .negarena_bridge import NegarenaBridge


class ReplayError(RuntimeError):
    """A recorded episode could not be replayed as an offline trajectory.

    Distinct from a bridge-detected divergence inside ``parse_action``/
    ``legal``/``step`` themselves (which would surface as whatever exception
    those hooks raise, wrapped by the scheduler's own
    ``SchedulerContractError``, and is left to propagate unmodified -- that
    *is* the replay guarantee firing). This error covers replay-harness-level
    problems: a case/record mismatch, a phase/seat ordering mismatch against
    the record, or an unconsumed tail of recorded decisions.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Round-trips through ``canonical_json_bytes``, the same pattern already
    used by ``tau3_retail/replay.py``'s identical helper, so a
    ``RecordedEpisode`` built from a live, scheduler-frozen
    ``EpisodeResult`` (whose ``MappingProxyType``/tuple containers are not
    JSON-serializable as-is) is guaranteed to be a plain, ``json.dumps``-able
    structure.
    """
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One sealed decision: which phase/seat it was for, and the raw response.

    ``response`` is exactly the raw scripted payload
    ``LogicalActionRecord.response`` already carries for a completed
    action (``{"response": "<tagged scripted text>"}``) -- replay serves it
    back verbatim; ``NegarenaPlugin.parse_action``/``legal``/``step`` alone
    re-derive everything else.
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


def _cell_sha256(cell: PlanCell) -> str:
    """Content hash of the *whole* ``PlanCell`` a recording was produced from.

    Covers profile/pairing identity (``profile_by_seat``), seeds
    (``world_seed``/``sampling_seed``/``replicate_index``), and every other
    cell field in one digest -- so replaying against a cell that differs in
    any of them (a different opponent profile, a different seed, a
    different replicate) is detectable even though the two cells may share
    the same ``cell_id``-irrelevant fields.
    """
    return hashlib.sha256(canonical_json_bytes(cell)).hexdigest()


@dataclass(frozen=True, slots=True)
class RecordedEpisode:
    """The complete, plain-JSON-serializable ordered decision log for one episode.

    ``case_sha256``/``cell_sha256`` bind this recording to the exact case
    content and cell (profile/pairing/seed) identity it was produced from --
    ``case_id`` string equality alone does not: a case can be re-authored
    (different valuation, different upstream pin) while keeping the same
    ``case_id``, and a cell can be rebuilt with a different opponent/seed
    while still satisfying ``_validate_cell_case``'s own case/cell agreement
    check (docs/negarena_codex_triage.md Finding 2). ``replay_episode``
    rejects a recording whose ``case_sha256``/``cell_sha256`` do not match
    the case/cell it is asked to replay against, rather than silently
    replaying a different execution's inputs and reporting new state/scores
    as if they were the original run's.
    """

    case_id: str
    case_sha256: str
    cell_sha256: str
    decisions: tuple[RecordedDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_sha256": self.case_sha256,
            "cell_sha256": self.cell_sha256,
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
            cell_sha256=value["cell_sha256"],
            decisions=tuple(
                RecordedDecision.from_dict(decision) for decision in value["decisions"]
            ),
        )

    @classmethod
    def from_json(cls, text: str) -> "RecordedEpisode":
        return cls.from_dict(json.loads(text))


def record_episode(
    result: EpisodeResult, *, case: CaseManifest, cell: PlanCell
) -> RecordedEpisode:
    """Extract the ordered decision log from one already-completed ``EpisodeResult``.

    Pulls exactly the raw ``LogicalActionRecord.response`` for every action,
    in the order the scheduler requested them -- nothing about parsing,
    legality, scoring, or state is captured here; replay regenerates all of
    that independently through ``run_episode``. ``case``/``cell`` must be the
    exact ones that produced ``result``: their content hashes are sealed into
    the recording so a later replay can detect a mismatched case or cell
    (Finding 2) rather than silently accepting one.
    """
    if case.case_id != result.case_id:
        raise ReplayError(
            f"case {case.case_id!r} does not match the episode's own case "
            f"{result.case_id!r}"
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
        case_id=result.case_id,
        case_sha256=case.content_sha256,
        cell_sha256=_cell_sha256(cell),
        decisions=tuple(decisions),
    )


class RecordedResponseSource:
    """Serve a fixed, recorded sequence of raw responses -- no model call.

    Unlike ``ScriptedNegarenaHarness`` (which is driven by a hand-authored
    script and records fresh evidence for each decision it serves), this
    response source makes no evidence call at all: it exists purely to feed
    the exact recorded text back through the real scheduler so
    ``NegarenaPlugin.parse_action``/``legal``/``step`` -- delegating to the
    bridge exactly as they did live -- re-derive the whole episode
    independently.
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
        # detach through the same plain-JSON conversion RecordedDecision.to_dict()
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
    A divergence inside ``NegarenaPlugin.parse_action``/``legal``/``step``
    (or a scheduler contract violation) is left to propagate unmodified.
    This function raises ``ReplayError`` only for replay-harness-level
    problems (wrong case, ordering mismatch, unconsumed record).
    """
    if recorded.case_id != case.case_id:
        raise ReplayError(
            f"recorded episode is for case {recorded.case_id!r}, not {case.case_id!r}"
        )
    if recorded.case_sha256 != case.content_sha256:
        raise ReplayError(
            f"recorded episode was produced from a different case body: "
            f"recorded case_sha256={recorded.case_sha256}, "
            f"supplied case_sha256={case.content_sha256} "
            f"(same case_id {case.case_id!r}, different content -- e.g. a "
            "changed valuation or upstream pin)"
        )
    if recorded.cell_sha256 != _cell_sha256(cell):
        raise ReplayError(
            f"recorded episode was produced from a different cell: "
            f"recorded cell_sha256={recorded.cell_sha256}, "
            f"supplied cell_sha256={_cell_sha256(cell)} "
            f"(cell_id {cell.cell_id!r} -- a different profile_by_seat/seed/"
            "replicate would still satisfy the scheduler's own case/cell "
            "agreement check but is not the original execution's cell)"
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

    Negarena's own family state carries no wall-clock timestamp or other
    cross-run non-determinism (module docstring), so -- unlike
    ``tau3_retail.replay.StateComparison`` -- there is no raw-vs-content
    split here: every field, including the raw per-phase-instance state
    hashes, is expected to match byte-for-byte on a genuine replay.
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
    a future parity/receipt harness) can assert on exactly what diverged.
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
            "phase-instance state hashes differ for: "
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
    """Both measurement leaves recomputed from a replayed episode.

    Leaf 1 (``negarena_seat_outcome``) is reported once per seat -- the
    estimand is "this seat's own realized value" (measurement.py's own
    docstring) -- leaf 2 (``negarena_agreement_reached``) once for the
    whole episode.
    """

    red_outcome: Any
    blue_outcome: Any
    agreement: Any


def score_replayed_episode(
    *,
    bridge: NegarenaBridge,
    scorer: NegarenaScorer,
    replayed: EpisodeResult,
    opponent_policy_id: str = "scripted",
) -> ReplayScoreResult:
    """Recompute both declared leaves from a replayed episode's own state.

    Never recomputes ``Trade.execute_trade``/``Valuation.value`` itself:
    delegates to the same ``NegarenaScorer.score_seat_outcome``/
    ``score_agreement_reached`` the live run's own scoring already uses
    (``measurement.py``), which in turn delegates settlement to
    ``NegarenaBridge.settle`` -- upstream's own ``after_game_ends()``,
    never reimplemented here.
    """
    if not isinstance(replayed.terminal, Mapping) or not isinstance(
        replayed.final_state, Mapping
    ):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record and final state"
        )
    red_outcome = scorer.score_seat_outcome(
        bridge=bridge,
        state=replayed.final_state,
        terminal=replayed.terminal,
        seat_id=RED,
        opponent_policy_id=opponent_policy_id,
    )
    blue_outcome = scorer.score_seat_outcome(
        bridge=bridge,
        state=replayed.final_state,
        terminal=replayed.terminal,
        seat_id=BLUE,
        opponent_policy_id=opponent_policy_id,
    )
    agreement = scorer.score_agreement_reached(terminal=replayed.terminal)
    return ReplayScoreResult(
        red_outcome=red_outcome, blue_outcome=blue_outcome, agreement=agreement
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
        """``"match"``/``"mismatch"`` only when a comparison was actually made.

        When ``original`` was never supplied to ``replay_and_verify``,
        ``comparison`` is ``None`` -- no equality check ever ran, so this
        must not report ``"match"`` for it: that would let downstream code
        reading only ``status`` (never ``comparison`` itself) count an
        uncompared episode as replay-verified
        (docs/negarena_codex_triage.md Finding 4). ``"not_compared"`` is
        reported instead, distinct from both real outcomes.
        """
        if self.comparison is None:
            return "not_compared"
        return "match" if self.comparison.matches else "mismatch"


async def replay_and_verify(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    bridge: NegarenaBridge,
    scorer: NegarenaScorer,
    recorded: RecordedEpisode,
    original: EpisodeResult | None = None,
    opponent_policy_id: str = "scripted",
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
        opponent_policy_id=opponent_policy_id,
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
