"""Task finalization, family-state replay, and portable receipts.

Extracted from the validated Housing receipt path so native families share the
same evidence and inclusion boundary. Economic scoring stays in each plugin.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from .execution import CanonicalResponse, CellExecution, EvidenceStore, TokenPricing
from ..run.layout import RunLayout
from ..measurement import (
    FamilyScoreSet,
    ImplementationRef as MeasurementImplementationRef,
    MeasurementLeafSpec,
    ScoreEnvelope,
    normalize_family_score_set,
)
from ..registry import PluginRegistry
from ..run.resolver import (
    ImplementationPin,
    PlanResolutionError,
    RunPlan,
    canonical_json_bytes,
    plan_with_recorded_pins,
    verify_run_plan,
)
from .receipts import (
    EvaluationFailure,
    EvaluationReceipt,
    read_evaluation_receipt,
    seal_evaluation_receipt,
    verify_evaluation_receipt,
    write_evaluation_receipt,
)
from .scheduler import (
    ActionEnvelope,
    DecisionRequest,
    LegalityResult,
    LogicalActionRecord,
    ParseResult,
    PhaseInstance,
    PhaseSpec,
    TransitionResult,
    _freeze,
)


class EvaluationSetup(Protocol):
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]


def _receipt_implementations(
    score_set: FamilyScoreSet | ScoreEnvelope,
) -> tuple[MeasurementImplementationRef, ...]:
    normalized = normalize_family_score_set(score_set)
    implementations = {
        implementation
        for score in normalized.scores
        for implementation in (
            score.leaf.estimand.validity_domain.predicate,
            score.leaf.verifier.reference.implementation,
            score.leaf.scorer,
        )
    }
    return tuple(
        sorted(
            implementations,
            key=lambda item: (
                item.implementation_id,
                item.version,
                item.content_sha256,
            ),
        )
    )


def _score_event_payload(
    score_set: FamilyScoreSet, *, outcome_event_id: str
) -> Mapping[str, Any]:
    """Preserve the historical one-score event shape where possible."""

    if len(score_set.scores) == 1 and score_set.admission_leaf_ids == (
        score_set.primary_leaf_id,
    ):
        return {
            "primary_leaf_id": score_set.primary_leaf_id,
            "outcome_event_id": outcome_event_id,
            "score": score_set.scores[0],
        }
    return {
        "primary_leaf_id": score_set.primary_leaf_id,
        "admission_leaf_ids": score_set.admission_leaf_ids,
        "outcome_event_id": outcome_event_id,
        "scores": score_set.scores,
    }


def _score_admission(
    score_set: FamilyScoreSet,
) -> tuple[str, str, EvaluationFailure | None]:
    invalid_ids = score_set.invalid_admission_leaf_ids
    if not invalid_ids:
        return "ok", "included", None
    reasons = tuple(
        reason
        for score in score_set.scores
        if score.leaf.leaf_id in invalid_ids
        for reason in score.validity.reasons
    )
    detail = "; ".join(reasons) or "admission leaf measurement is invalid"
    return (
        "invalid_measurement",
        "excluded",
        EvaluationFailure(
            failure_class="oracle_or_scorer_failure",
            condition="invalid_family_measurement",
            message=f"invalid admission leaves: {', '.join(invalid_ids)}; {detail}",
        ),
    )


def _agent_profile_digests(plan: RunPlan, cell: Any) -> dict[str, str]:
    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    return {
        seat_id: hashlib.sha256(canonical_json_bytes(profiles[profile_id])).hexdigest()
        for seat_id, profile_id in sorted(cell.profile_by_seat.items())
    }


@dataclass(frozen=True, slots=True)
class SeatContext:
    """Which seats are the tested subjects, and which profile sits in each.

    Ruling R12 (kernel_scoring_contract_spec.md): populated by
    ``finalize_family_execution``, ``replay_family_receipt``, and
    ``audit_family_receipt`` from the plan's evaluation block
    (``EvaluationBlock.subject_seats``, matched to the executed cell by
    ``cell.block_id``) and the resolved cell's own ``profile_by_seat`` --
    never from the live episode, so ruling R2's guarantee still holds: this
    is plan/receipt data, not anything ``plugin.step``/``observe`` produced.

    The dataclass field itself defaults to an explicit empty
    ``SeatContext((), {})`` so a test that constructs ``FamilyScoringInput``
    directly (without naming this type) keeps working; every production
    finalize/replay/audit path always supplies the real one.
    """

    subject_seats: tuple[str, ...]
    profile_by_seat: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_seats", tuple(self.subject_seats))
        object.__setattr__(
            self, "profile_by_seat", MappingProxyType(dict(self.profile_by_seat))
        )


def _seat_context_for_cell(plan: RunPlan, cell: Any) -> SeatContext:
    """The ``SeatContext`` for one resolved cell, read from the plan alone.

    Ruling R12 rule 1: matches the evaluation block by ``cell.block_id`` --
    never the live episode -- and takes ``subject_seats`` from that block and
    ``profile_by_seat`` from the cell itself.

    Review finding F1: every subject seat must be a key of the cell's own
    ``profile_by_seat``. ``resolve_run_plan`` (run/resolver.py) is the first
    line of defense here -- it already requires ``block.subject_seats`` to
    be a subset of the case's seat ids, which must exactly equal
    ``run_spec.seat_assignments``' keys, which is exactly what becomes
    ``cell.profile_by_seat`` -- so a plan built the normal way can never
    reach this branch. This check exists for a plan/cell pair constructed
    or mutated directly (bypassing ``resolve_run_plan``), so a subject seat
    with no assigned profile never silently reaches the scorer.
    """

    block = next(
        (item for item in plan.evaluation_blocks if item.block_id == cell.block_id),
        None,
    )
    if block is None:
        raise ValueError("cell names an evaluation block absent from the plan")
    missing_profiles = sorted(set(block.subject_seats) - set(cell.profile_by_seat))
    if missing_profiles:
        raise ValueError(
            f"evaluation block {block.block_id!r} names subject seat(s) "
            f"{missing_profiles} with no assigned profile in cell "
            f"{cell.cell_id!r}: profile_by_seat carries {sorted(cell.profile_by_seat)}"
        )
    return SeatContext(
        subject_seats=block.subject_seats,
        profile_by_seat=cell.profile_by_seat,
    )


def _check_seat_context_seat_set(
    seat_context: SeatContext, recorded_agent_profile_digests: Mapping[str, str]
) -> None:
    """Ruling R12 rule 1: reject a seat context naming a different seat set
    than the receipt's recorded ``agent_profile_digests``.

    Named explicitly per the ruling, not merely for a clearer message: a
    receipt whose recorded seats genuinely disagree with the CURRENT plan's
    cell is normally caught earlier, transitively, by the run_plan_id/
    plan_sha256 identity check every caller performs first (``PlanCell.
    profile_by_seat`` is itself part of what makes ``plan_sha256``) --
    ``audit_family_receipt`` additionally already re-derives and compares
    the full digest mapping generically. For ``replay_family_receipt``,
    though, this is the ONLY guard against a durable evidence directory
    whose on-disk receipt was corrupted directly (bypassing the write-once
    API) to a self-consistent but wrong ``agent_profile_sha256_by_seat`` --
    see docs/kernel_r12_seat_context.md and the mutation test that proved
    this by disabling this exact check.
    """

    context_seats = set(seat_context.profile_by_seat)
    recorded_seats = set(recorded_agent_profile_digests)
    if context_seats != recorded_seats:
        raise ValueError(
            "seat context does not match the receipt: seat_context names "
            f"seats {sorted(context_seats)}, receipt agent_profile_digests "
            f"names seats {sorted(recorded_seats)}"
        )


def _observability_limits(plan: RunPlan, cell: Any) -> tuple[str, ...]:
    profile_by_id = {profile.profile_id: profile for profile in plan.agent_profiles}
    assigned_profiles = tuple(
        profile_by_id[profile_id]
        for profile_id in sorted(set(cell.profile_by_seat.values()))
    )
    if any(profile.model.base_url is not None for profile in assigned_profiles):
        return ("provider_internal_reasoning_not_fully_observable",)
    return ()


def _replay_family_trajectory(
    *, plugin: Any, family_case: Mapping[str, Any], evidence: EvidenceStore
) -> tuple[Mapping[str, Any], tuple[PhaseInstance, ...], Any, tuple[str, ...]]:
    """Re-execute the pinned case once, cross-checking every step against the seal.

    Ruling R2 (kernel_scoring_contract_spec.md): this is a verified
    deterministic re-execution, not a pure read-back of durable evidence --
    ``plugin.phases``, ``initial_state``, ``eligible_actors``, ``step``,
    ``terminal``, and ``outcome`` are all invoked live here and each result is
    cross-checked against the sealed payload at that boundary. The live
    in-memory ``EpisodeResult`` is never read (this function never receives
    one).

    Returns the frozen terminal outcome, the full phase trajectory produced
    by this re-execution, the event that recorded the outcome, and every
    sealed event id used to cross-check the above, deduplicated and ordered
    by first use. Any disagreement between the re-execution and the sealed
    evidence raises immediately -- there is no partial result to fall back
    to.
    """
    events = evidence.read_events()
    phase_by_id = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, run=None)
    phase_events = tuple(
        event for event in events if event.event_type == "phase_instance_started"
    )
    if not phase_events:
        raise ValueError("family replay contains no phase boundaries")

    used_event_ids: list[str] = []
    seen_event_ids: set[str] = set()

    def _use(used_event: Any) -> None:
        if used_event.event_id not in seen_event_ids:
            seen_event_ids.add(used_event.event_id)
            used_event_ids.append(used_event.event_id)

    phase_instances: list[PhaseInstance] = []
    for ordinal, phase_event in enumerate(phase_events):
        payload = evidence.read_event_payload(phase_event)
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("phase"), Mapping
        ):
            raise ValueError("family replay phase boundary is malformed")
        recorded_phase = PhaseSpec(**dict(payload["phase"]))
        phase = phase_by_id.get(recorded_phase.phase_id)
        if phase is None or canonical_json_bytes(
            recorded_phase
        ) != canonical_json_bytes(phase):
            raise ValueError("family replay phase specification changed")
        pre_state_sha256 = hashlib.sha256(canonical_json_bytes(state)).hexdigest()
        if payload.get("pre_state_sha256") != pre_state_sha256:
            raise ValueError("family replay pre-state hash mismatch")
        eligible = tuple(plugin.eligible_actors(family_case, state, phase))
        if tuple(payload.get("eligible_actors", ())) != eligible:
            raise ValueError("family replay eligible actors changed")
        _use(phase_event)

        starts = tuple(
            event
            for event in events
            if event.event_type == "logical_action_started"
            and event.phase_instance_id == phase_event.phase_instance_id
        )
        actions: dict[str, ActionEnvelope] = {}
        acted_seats: list[str] = []
        action_records: list[LogicalActionRecord] = []
        observations: dict[str, Any] = {}
        for start in starts:
            start_payload = evidence.read_event_payload(start)
            request_value = (
                start_payload.get("request")
                if isinstance(start_payload, Mapping)
                else None
            )
            if not isinstance(request_value, Mapping):
                raise ValueError("family replay action request is malformed")
            seat_id = request_value.get("seat_id")
            if not isinstance(seat_id, str) or seat_id in actions:
                raise ValueError("family replay action seat identity is invalid")
            request = DecisionRequest(**_freeze(dict(request_value)))
            observations[seat_id] = request.observation
            _use(start)
            parsed_events = tuple(
                event
                for event in events
                if event.event_type == "action_parsed"
                and event.logical_action_id == start.logical_action_id
            )
            if len(parsed_events) != 1:
                raise ValueError("family replay action lacks one parse result")
            parsed_payload = evidence.read_event_payload(parsed_events[0])
            parsed_value = (
                parsed_payload.get("parse_result")
                if isinstance(parsed_payload, Mapping)
                else None
            )
            if not isinstance(parsed_value, Mapping):
                raise ValueError("family replay parse result is malformed")
            parsed = ParseResult(**dict(parsed_value))
            _use(parsed_events[0])
            legality_events = tuple(
                event
                for event in events
                if event.event_type == "action_legality_checked"
                and event.logical_action_id == start.logical_action_id
            )
            legality: LegalityResult | None = None
            if legality_events:
                if len(legality_events) != 1:
                    raise ValueError("family replay has duplicate legality results")
                legality_payload = evidence.read_event_payload(legality_events[0])
                legality_value = (
                    legality_payload.get("legality_result")
                    if isinstance(legality_payload, Mapping)
                    else None
                )
                if not isinstance(legality_value, Mapping):
                    raise ValueError("family replay legality result is malformed")
                legality = LegalityResult(**dict(legality_value))
                _use(legality_events[0])
            valid = parsed.ok and legality is not None and legality.legal
            envelope = ActionEnvelope(
                seat_id=seat_id,
                valid=valid,
                action=parsed.action if valid else None,
                parse=parsed,
                legality=legality,
            )
            actions[seat_id] = envelope
            acted_seats.append(seat_id)

            succeeded_events = tuple(
                event
                for event in events
                if event.event_type == "action_attempt_succeeded"
                and event.logical_action_id == start.logical_action_id
            )
            if len(succeeded_events) != 1:
                raise ValueError("family replay action lacks one successful attempt")
            succeeded_payload = evidence.read_event_payload(succeeded_events[0])
            response_value = (
                succeeded_payload.get("canonical_response")
                if isinstance(succeeded_payload, Mapping)
                else None
            )
            if not isinstance(response_value, Mapping):
                raise ValueError("family replay action response is malformed")
            response = CanonicalResponse(**_freeze(dict(response_value)))
            _use(succeeded_events[0])

            action_records.append(
                LogicalActionRecord(
                    logical_action_id=start.logical_action_id,
                    seat_id=seat_id,
                    request=request,
                    response=response,
                    parse=parsed,
                    legality=legality,
                    envelope=envelope,
                )
            )
        if len(set(acted_seats)) != len(acted_seats):
            raise ValueError("family replay action seat identity is invalid")
        if set(acted_seats) - set(eligible):
            raise ValueError("family replay action set does not match eligible actors")

        transition_events = tuple(
            event
            for event in events
            if event.event_type == "transition_applied"
            and event.phase_instance_id == phase_event.phase_instance_id
        )
        mode = recorded_phase.mode
        if mode in ("single", "simultaneous"):
            # Production applies every eligible actor's action in one
            # transition (scheduler.py's ``if phase.mode in {"single",
            # "simultaneous"}`` branch), so replay must too.
            if tuple(sorted(acted_seats)) != tuple(sorted(eligible)):
                raise ValueError(
                    "family replay action set does not match eligible actors"
                )
            step_groups: tuple[tuple[str, ...], ...] = (tuple(acted_seats),)
        elif mode == "sequential":
            # kernel_contract_impl_review.md finding 2: production applies
            # one transition per actor for a sequential phase (scheduler.py's
            # ``else`` branch), and may stop before every eligible actor acts
            # if an earlier actor's transition already terminates the
            # episode or names the next phase. Replay must follow exactly
            # the sequence sealed evidence recorded, not assume every
            # eligible actor acted or that one transition covers them all.
            if set(acted_seats) - set(eligible):
                raise ValueError(
                    "family replay action set does not match eligible actors"
                )
            step_groups = tuple((seat_id,) for seat_id in acted_seats)
        else:
            raise ValueError(
                f"family replay encountered an unsupported phase mode: {mode!r}"
            )
        if len(transition_events) != len(step_groups):
            raise ValueError(
                "family replay phase does not have one transition per step"
            )

        transitions: list[TransitionResult] = []
        for transition_event, seat_group in zip(transition_events, step_groups):
            transition_payload = evidence.read_event_payload(transition_event)
            if not isinstance(transition_payload, Mapping):
                raise ValueError("family replay transition is malformed")
            step_actions = {seat_id: actions[seat_id] for seat_id in seat_group}
            replayed = plugin.step(family_case, state, phase, step_actions)
            if canonical_json_bytes(
                transition_payload.get("transition")
            ) != canonical_json_bytes(replayed):
                raise ValueError("family replay transition differs from sealed evidence")
            post_state_sha256 = hashlib.sha256(
                canonical_json_bytes(replayed.state)
            ).hexdigest()
            if transition_payload.get("post_state_sha256") != post_state_sha256:
                raise ValueError("family replay post-state hash mismatch")
            transition_value = transition_payload.get("transition")
            if not isinstance(transition_value, Mapping):
                raise ValueError("family replay transition is malformed")
            transitions.append(TransitionResult(**_freeze(dict(transition_value))))
            _use(transition_event)
            state = replayed.state

        # kernel_contract_impl_review.md finding 3: the phase's own
        # completion boundary (``phase_instance_succeeded``) was previously
        # never read by replay, so a boundary that omitted an actor or named
        # the wrong post-state hash was silently accepted. Cross-check it
        # like every other recorded boundary.
        succeeded_events = tuple(
            event
            for event in events
            if event.event_type == "phase_instance_succeeded"
            and event.phase_instance_id == phase_event.phase_instance_id
        )
        if len(succeeded_events) != 1:
            raise ValueError("family replay phase lacks one completion boundary")
        succeeded_payload = evidence.read_event_payload(succeeded_events[0])
        if not isinstance(succeeded_payload, Mapping):
            raise ValueError("family replay phase completion boundary is malformed")
        if succeeded_payload.get("phase_id") != recorded_phase.phase_id:
            raise ValueError(
                "family replay phase completion boundary names the wrong phase"
            )
        if succeeded_payload.get("post_state_sha256") != post_state_sha256:
            raise ValueError(
                "family replay phase completion boundary post-state hash mismatch"
            )
        expected_action_ids = tuple(record.logical_action_id for record in action_records)
        if tuple(succeeded_payload.get("logical_action_ids", ())) != expected_action_ids:
            raise ValueError(
                "family replay phase completion boundary action ids mismatch"
            )
        _use(succeeded_events[0])

        phase_instances.append(
            PhaseInstance(
                phase_instance_id=phase_event.phase_instance_id,
                phase_id=recorded_phase.phase_id,
                ordinal=ordinal,
                mode=recorded_phase.mode,
                eligible_actors=eligible,
                pre_state_sha256=pre_state_sha256,
                post_state_sha256=post_state_sha256,
                observations=_freeze(observations),
                actions=tuple(action_records),
                transitions=tuple(transitions),
            )
        )

    terminal_events = tuple(
        event for event in events if event.event_type == "episode_terminated"
    )
    outcome_events = tuple(
        event for event in events if event.event_type == "family_outcome_recorded"
    )
    if len(terminal_events) != 1 or len(outcome_events) != 1:
        raise ValueError("family replay lacks one terminal outcome boundary")
    terminal = plugin.terminal(family_case, state)
    terminal_payload = evidence.read_event_payload(terminal_events[0])
    outcome_payload = evidence.read_event_payload(outcome_events[0])
    if not isinstance(terminal_payload, Mapping) or canonical_json_bytes(
        terminal_payload.get("terminal")
    ) != canonical_json_bytes(terminal):
        raise ValueError("family replay terminal result differs from sealed evidence")
    _use(terminal_events[0])
    outcome = plugin.outcome(family_case, terminal)
    if not isinstance(outcome_payload, Mapping) or canonical_json_bytes(
        outcome_payload.get("outcome")
    ) != canonical_json_bytes(outcome):
        raise ValueError("family replay family outcome differs from sealed evidence")
    _use(outcome_events[0])
    return (
        _freeze(outcome),
        tuple(phase_instances),
        outcome_events[0],
        tuple(used_event_ids),
    )


def replay_family_state(
    *, plugin: Any, family_case: Mapping[str, Any], evidence: EvidenceStore
) -> tuple[Mapping[str, Any], Any]:
    outcome, _phase_instances, outcome_event, _evidence_refs = (
        _replay_family_trajectory(
            plugin=plugin, family_case=family_case, evidence=evidence
        )
    )
    return outcome, outcome_event


@dataclass(frozen=True, slots=True)
class FamilyScoringInput:
    """Scoring data produced by a verified deterministic re-execution.

    Ruling R2 (kernel_scoring_contract_spec.md): the fields below are NOT a
    pure read-back of durable evidence. They come from re-executing the
    pinned case deterministically and cross-checking every phase boundary,
    action, and terminal state against the sealed evidence as it goes (see
    ``_replay_family_trajectory``); a divergence between the re-execution and
    the seal fails finalization rather than returning a partial result. What
    the guarantee gives you: the live in-memory ``EpisodeResult`` is never
    read. The finalizer still compares its outcome against ``outcome`` below,
    but only to detect disagreement -- the score itself is computed from this
    re-execution, which is what the receipt asserts.

    Ruling R3: ``phase_instances[*].observations`` is not itself carried by
    durable evidence -- ``phase_instance_started`` seals only ``phase,
    eligible_actors, pre_state_sha256``, never per-seat observation content.
    ``observations`` here is populated as a deterministic function of the
    pre-state during the re-execution above. That is safe because the
    pre-state hash IS sealed and cross-checked at every phase boundary: an
    observation that differed from the sealed run would imply a pre-state
    hash mismatch, which fails re-execution before such an observation could
    ever be returned. A future family author must not read "observations"
    and assume it was transcribed verbatim from evidence.

    Ruling R12: ``seat_context`` carries which seats are the tested subjects
    and which profile sits in each, read from the plan's evaluation block
    and the resolved cell -- see ``SeatContext`` and ``_seat_context_for_cell``.
    It defaults to an empty ``SeatContext`` only so a test may construct this
    dataclass directly without naming that type; every production caller of
    :func:`replay_family_scoring_input` supplies the real one.
    """

    outcome: Mapping[str, Any]
    phase_instances: tuple[PhaseInstance, ...]
    evidence_refs: tuple[str, ...]
    seat_context: SeatContext = SeatContext((), {})


def replay_family_scoring_input(
    *,
    plugin: Any,
    family_case: Mapping[str, Any],
    evidence: EvidenceStore,
    seat_context: SeatContext,
) -> FamilyScoringInput:
    """Produce one family's scoring input by verified deterministic re-execution.

    Ruling R2: this re-executes the pinned case deterministically and
    cross-checks every phase boundary, action, and terminal state against the
    sealed evidence -- it is not a pure read-back. This signature takes no
    ``EpisodeResult`` parameter: the live episode is unreachable here by
    construction, so a caller cannot silently fall back to it when replay is
    incomplete. A disagreement between the re-execution and the sealed
    evidence raises rather than returning a partial result.

    Ruling R12: ``seat_context`` is a required keyword with no default --
    every production call site (``finalize_family_execution``,
    ``replay_family_receipt``, ``audit_family_receipt``) reads it from the
    plan via ``_seat_context_for_cell`` and must pass it explicitly, so a
    caller cannot silently omit seat context the way a default would allow.
    """
    outcome, phase_instances, _outcome_event, evidence_refs = (
        _replay_family_trajectory(
            plugin=plugin, family_case=family_case, evidence=evidence
        )
    )
    return FamilyScoringInput(
        outcome=outcome,
        phase_instances=phase_instances,
        evidence_refs=evidence_refs,
        seat_context=seat_context,
    )


class FamilyScorer(Protocol):
    """A family's scoring hook, called once per finalized episode.

    ``evidence_refs`` is always ``scoring_input.evidence_refs`` verbatim --
    it is threaded as a keyword for call-signature parity with families
    that do not otherwise need ``scoring_input``. A scorer may return a
    bare ``ScoreEnvelope``, a sequence of them, or an explicit
    ``FamilyScoreSet``; :func:`normalize_family_score_set` accepts all
    three.
    """

    def __call__(
        self,
        scoring_input: FamilyScoringInput,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope | Sequence[ScoreEnvelope] | FamilyScoreSet: ...


def _manifest_declares_leaf_policy(manifest: Any) -> bool:
    measurement = manifest.measurement
    return bool(measurement.leaves) and measurement.primary_leaf_id is not None


def _declared_deferred_leaf_ids(manifest: Any) -> tuple[str, ...]:
    """The manifest's declared, deferred (not finalize-time) leaf ids.

    kernel_contract_impl_review.md finding 12: a deferred leaf's declaration
    must survive onto the receipt as declared-and-deferred, not disappear
    the way an undeclared, silently-dropped leaf would. Empty when the
    family declares no leaf policy at all (per-family migration work, spec
    section 5, not yet done for any production manifest).
    """
    if not _manifest_declares_leaf_policy(manifest):
        return ()
    return tuple(
        sorted(leaf.leaf_id for leaf in manifest.measurement.leaves if leaf.scope == "deferred")
    )


def _declared_case_conditional_leaf_ids(manifest: Any) -> frozenset[str]:
    """The manifest's declared ``case_conditional`` leaf ids (ruling R13).

    Not restricted to ``finalize_time`` leaves: rule 4 lets a leaf be both
    ``case_conditional`` and ``deferred`` (declared-and-inapplicable on a
    case where it does not apply, declared-and-deferred otherwise), so a
    deferred, case-conditional leaf's id belongs here too. Empty when the
    family declares no leaf policy at all.
    """
    if not _manifest_declares_leaf_policy(manifest):
        return frozenset()
    return frozenset(
        leaf.leaf_id for leaf in manifest.measurement.leaves if leaf.case_conditional
    )


def _inapplicable_leaf_ids(plugin: Any, family_case: Mapping[str, Any]) -> frozenset[str]:
    """Ruling R13 rule 2: the plugin's optional case-conditional applicability hook.

    Applicability is decided by code over the validated case, not a
    predicate language in data: ``plugin.inapplicable_leaf_ids(family_case)``
    returns the ids of this execution's inapplicable, declared
    ``case_conditional`` leaves. A plugin that declares no
    ``case_conditional`` leaf need not define this hook at all -- the
    default is empty, following the same optional-hook pattern
    ``task/scheduler.py``'s ``close`` teardown hook uses (``getattr`` with a
    ``None`` default, called only when callable).

    R13 review finding 2: the hook's return value is validated here, not
    coerced -- ``frozenset(value)`` would silently turn a returned ``str``
    into a set of its individual characters, an ``int`` into a ``TypeError``
    a caller might not expect from THIS function, and any other iterable
    into a set whose members were never checked to be leaf ids at all. Only
    an actual ``frozenset`` or ``set``, every member a ``str``, is accepted;
    anything else raises here, naming the plugin and the offending type,
    rather than producing a confusing failure deeper in
    ``_enforce_declared_leaf_policy`` or the receipt.
    """
    hook = getattr(plugin, "inapplicable_leaf_ids", None)
    if not callable(hook):
        return frozenset()
    result = hook(family_case)
    plugin_id = type(plugin).__qualname__
    if not isinstance(result, (frozenset, set)):
        raise TypeError(
            f"plugin {plugin_id!r}'s inapplicable_leaf_ids hook must return a "
            f"frozenset or set of str, got {type(result).__name__}"
        )
    non_string_members = [item for item in result if not isinstance(item, str)]
    if non_string_members:
        raise TypeError(
            f"plugin {plugin_id!r}'s inapplicable_leaf_ids hook must return a "
            "frozenset or set of str, got a member of type "
            f"{type(non_string_members[0]).__name__}"
        )
    return frozenset(result)


def _enforce_subject_seat_primaries(
    score_set: FamilyScoreSet, manifest: Any, seat_context: SeatContext
) -> None:
    """Ruling R12 rule 2: a status "ok" ``subject_seat`` leaf may only claim
    the one true reduction over ``seat_context.subject_seats``.

    This is a contract violation the kernel raises on, not
    ``invalid_measurement`` -- reporting ``invalid_measurement`` for these
    same three cases (no subject seat, an ambiguous subject seat with no
    declared reduction, or a wrong value) is the scorer's own job (reasons
    ``no_subject_seat`` / ``ambiguous_subject_seat``); this check exists to
    catch a scorer that claims a scalar it may not claim, regardless of
    whatever the scorer itself believed. Applies to nothing when
    ``seat_scope`` is "cell" (the default).
    """
    leaf_policy_by_id = {leaf.leaf_id: leaf for leaf in manifest.measurement.leaves}
    subject_seats = seat_context.subject_seats
    for score in score_set.scores:
        leaf_policy = leaf_policy_by_id.get(score.leaf.leaf_id)
        if leaf_policy is None or leaf_policy.seat_scope != "subject_seat":
            continue
        if score.status != "ok":
            continue
        leaf_id = score.leaf.leaf_id
        if len(subject_seats) == 0:
            raise ValueError(
                f"leaf {leaf_id!r} is declared seat_scope=subject_seat and "
                "scored ok with no subject seat"
            )
        if len(subject_seats) == 1:
            subject = subject_seats[0]
            if subject not in score.utility_by_seat:
                raise ValueError(
                    f"leaf {leaf_id!r} scored ok for subject seat {subject!r} "
                    "but its utility_by_seat does not carry that seat"
                )
            subject_value = score.utility_by_seat[subject]
            if (
                score.primary is None
                or score.primary.value != subject_value.value
                or score.primary.unit != subject_value.unit
            ):
                raise ValueError(
                    f"leaf {leaf_id!r} scored ok for subject seat {subject!r} "
                    "but its primary does not equal utility_by_seat[subject]"
                )
            continue
        # Two or more subject seats (self-play): an "ok" envelope is only
        # permitted when the manifest declares which reduction over those
        # seats the family means. The kernel does not interpret the
        # reduction identifier itself -- it only requires it was declared
        # before a scalar is claimed.
        if leaf_policy.subject_reduction is None:
            raise ValueError(
                f"leaf {leaf_id!r} scored ok over {len(subject_seats)} subject "
                "seats without a declared subject_reduction"
            )


def _enforce_declared_leaf_policy(
    score_set: FamilyScoreSet,
    manifest: Any,
    seat_context: SeatContext,
    inapplicable_leaf_ids: frozenset[str],
) -> None:
    """The manifest is the source of truth for a family that declares one.

    kernel_contract_impl_review.md finding 5: nothing previously obtained or
    compared the manifest's leaf policy against what the scorer actually
    produced, so a scorer that silently dropped a declared leaf (or drifted
    on primary/admission) would still receipt. A family with no declared
    leaf policy is unconstrained here -- declaring one on the production
    manifest is per-family migration work (spec section 5, item 2), not
    performed by this kernel change for any of the five already-migrated
    families (spec ruling R4).

    Ruling R13: ``inapplicable_leaf_ids`` is ``I``, the plugin's
    ``inapplicable_leaf_ids(family_case)`` hook result for this execution
    (:func:`_inapplicable_leaf_ids`), computed once by the caller and
    threaded here (and separately into the receipt -- see
    ``finalize_family_execution``/``replay_family_receipt``/
    ``audit_family_receipt``). ``I`` may only name declared
    ``case_conditional`` leaves (an undeclared id in ``I`` is the plugin's
    own contract violation, independent of anything the scorer does or
    whether the manifest declares a leaf policy at all -- checked BEFORE
    the no-declared-policy early return below, review finding 1: a legacy
    family with no leaf policy declares zero case_conditional leaves, so
    ANY non-empty ``I`` from a hook it happens to define is already a
    violation, and must be caught here rather than silently reaching a
    receipt). Once a leaf policy is declared, three more failure modes get
    three more distinct messages: the scorer's returned set must be
    exactly the declared finalize-time leaves minus ``I`` -- an
    inapplicable leaf the scorer still returns, an applicable leaf the
    scorer omits, and an undeclared leaf the scorer invents are each named
    separately.
    """
    declared_case_conditional_ids = _declared_case_conditional_leaf_ids(manifest)
    undeclared_inapplicable = sorted(
        inapplicable_leaf_ids - declared_case_conditional_ids
    )
    if undeclared_inapplicable:
        raise ValueError(
            "plugin inapplicable_leaf_ids named a leaf that is not declared "
            f"case_conditional: {undeclared_inapplicable}"
        )
    if not _manifest_declares_leaf_policy(manifest):
        return
    declared = manifest.measurement.finalize_time_leaf_policy()
    produced_leaf_ids = tuple(score.leaf.leaf_id for score in score_set.scores)
    produced_leaf_id_set = set(produced_leaf_ids)
    # Ruling R13: the set the scorer must produce is the declared
    # finalize-time leaves minus I, not the raw declared set -- an
    # inapplicable leaf being correctly omitted is not a violation.
    expected_leaf_ids = set(declared.leaf_ids) - inapplicable_leaf_ids
    # Each branch below keeps the pre-R13 "does not match its declared
    # finalize-time leaf policy" phrase (kernel_contract_impl_review.md
    # finding 5's original wording, matched by name in
    # tests/test_shared_runner_family_scoring_policy_enforcement.py) AND
    # names the specific violation ruling R13 requires distinguished --
    # returning an inapplicable leaf, omitting an applicable one, and
    # returning an undeclared one are three different mistakes with three
    # different fixes, not one generic mismatch.
    returned_inapplicable = sorted(produced_leaf_id_set & inapplicable_leaf_ids)
    if returned_inapplicable:
        raise ValueError(
            "family scorer output does not match its declared finalize-time "
            f"leaf policy: returned an inapplicable leaf: {returned_inapplicable}"
        )
    omitted_applicable = sorted(expected_leaf_ids - produced_leaf_id_set)
    if omitted_applicable:
        raise ValueError(
            "family scorer output does not match its declared finalize-time "
            f"leaf policy: omitted an applicable leaf: {omitted_applicable}"
        )
    undeclared_returned = sorted(produced_leaf_id_set - expected_leaf_ids)
    if undeclared_returned:
        raise ValueError(
            "family scorer output does not match its declared finalize-time "
            f"leaf policy: returned an undeclared leaf: {undeclared_returned}"
        )
    if score_set.primary_leaf_id != declared.primary_leaf_id:
        raise ValueError(
            "family scorer primary_leaf_id does not match its declared leaf policy: "
            f"produced {score_set.primary_leaf_id!r}, declared {declared.primary_leaf_id!r}"
        )
    if score_set.admission_leaf_ids != declared.admission_leaf_ids:
        raise ValueError(
            "family scorer admission_leaf_ids does not match its declared leaf "
            f"policy: produced {score_set.admission_leaf_ids}, declared "
            f"{declared.admission_leaf_ids}"
        )
    _enforce_subject_seat_primaries(score_set, manifest, seat_context)


def _check_evidence_refs_are_scoring_input_verbatim(
    score_set: FamilyScoreSet, scoring_input: "FamilyScoringInput"
) -> None:
    """Every produced score's ``evidence_refs`` must be ``scoring_input.evidence_refs``.

    kernel_contract_impl_review.md finding 13: the spec states this as a rule
    a migrating agent must follow ("evidence_refs is always
    scoring_input.evidence_refs verbatim"), enforced only by convention. The
    finalizer always calls the scorer with that exact value, but nothing
    stops a scorer from fabricating a different one on the envelopes it
    returns; catch that here rather than silently sealing mismatched
    provenance.
    """
    mismatched = tuple(
        score.leaf.leaf_id
        for score in score_set.scores
        if score.evidence_refs != scoring_input.evidence_refs
    )
    if mismatched:
        raise ValueError(
            "family scorer returned evidence_refs that disagree with "
            f"scoring_input.evidence_refs for leaves: {mismatched}"
        )


def finalize_family_execution(
    *, setup: EvaluationSetup, execution: CellExecution
) -> EvaluationReceipt:
    """Score one completed family execution, seal evidence, and persist its receipt."""

    if not isinstance(execution, CellExecution):
        raise TypeError("execution must be a CellExecution")
    verify_run_plan(setup.plan)
    if execution.run_plan_id != setup.plan.run_plan_id:
        raise ValueError("execution does not belong to the family RunPlan")
    cell = next(
        (item for item in setup.plan.cells if item.cell_id == execution.cell_id),
        None,
    )
    if cell is None:
        raise ValueError("execution cell is absent from the family RunPlan")
    case = next(item for item in setup.plan.cases if item.case_id == cell.case_id)
    family = next(
        item for item in setup.plan.families if item.family.id == cell.family_id
    )
    # kernel_contract_impl_review.md finding 6: resolve through the registry's
    # own trusted registration, not the manifest the run-plan happens to
    # carry, so leaf policy is always read from the one manifest
    # PluginRegistry actually admitted for this plugin -- the same source the
    # scoring-contract protocol test trusts.
    registration = setup.registry.resolve_registration(
        family.family.id, family.family.version, family.family.plugin_id
    )
    plugin = registration.plugin
    family_case = plugin.validate_payload(case.payload)

    seat_context = _seat_context_for_cell(setup.plan, cell)
    execution.evidence.audit_reconciliation()
    scoring_input = replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        seat_context=seat_context,
    )
    if canonical_json_bytes(scoring_input.outcome) != canonical_json_bytes(
        execution.episode_result.outcome
    ):
        raise ValueError("execution outcome does not match the event log")

    score_set = normalize_family_score_set(
        plugin.build_scorer(family_case)(
            scoring_input,
            evidence_refs=scoring_input.evidence_refs,
        )
    )
    _check_evidence_refs_are_scoring_input_verbatim(score_set, scoring_input)
    # Ruling R13: the hook is called exactly once here, and its result is
    # threaded into both the enforcement check and the receipt below --
    # never recomputed a second time for either purpose.
    inapplicable_ids = _inapplicable_leaf_ids(plugin, family_case)
    _enforce_declared_leaf_policy(
        score_set, registration.manifest, seat_context, inapplicable_ids
    )
    # Inapplicability takes precedence over deferral (rule 4): a
    # case_conditional leaf that is also deferred is declared-and-deferred
    # only on a case where it applies; on a case where it does not, it is
    # declared-and-inapplicable instead, and the two receipt fields are
    # disjoint by construction here.
    deferred_leaf_ids = tuple(
        sorted(set(_declared_deferred_leaf_ids(registration.manifest)) - inapplicable_ids)
    )
    inapplicable_leaf_ids = tuple(sorted(inapplicable_ids))
    execution.evidence.append_event(
        "score_recorded",
        # _replay_family_trajectory always appends the outcome event last.
        _score_event_payload(
            score_set, outcome_event_id=scoring_input.evidence_refs[-1]
        ),
    )
    execution.evidence.audit_reconciliation()
    evidence_seal = execution.evidence.seal()

    receipt_status, inclusion_status, failure = _score_admission(score_set)
    receipt = seal_evaluation_receipt(
        EvaluationReceipt(
            spec_version=EvaluationReceipt.SPEC_VERSION,
            receipt_sha256=None,
            status=receipt_status,
            inclusion_status=inclusion_status,
            run_plan_id=setup.plan.run_plan_id,
            run_plan_sha256=setup.plan.plan_sha256,
            cell_id=cell.cell_id,
            case_id=case.case_id,
            case_sha256=case.content_sha256,
            suite_id=setup.plan.suite.suite_id,
            suite_version=setup.plan.suite.version,
            block_id=cell.block_id,
            sampling_plan_id=cell.sampling_plan_id,
            analysis_plan_id=cell.analysis_plan_id,
            episode_id=evidence_seal.episode_id,
            episode_attempt_id=execution.episode_attempt_id,
            cluster_id=cell.cluster_id,
            cluster_level=cell.cluster_level,
            observations_per_cluster=cell.observations_per_cluster,
            parent_cluster_id=None,
            pair_id=cell.pair_id,
            paired_fields=cell.paired_fields,
            replicate_index=cell.replicate_index,
            panel_mode=cell.panel_mode,
            agent_profile_sha256_by_seat=_agent_profile_digests(setup.plan, cell),
            implementation_refs=_receipt_implementations(score_set),
            plan_implementation_pins=setup.plan.implementation_pins,
            evidence=evidence_seal,
            primary_leaf_id=score_set.primary_leaf_id,
            scores=score_set.scores,
            deferred_leaf_ids=deferred_leaf_ids,
            inapplicable_leaf_ids=inapplicable_leaf_ids,
            failure=failure,
            observability_limits=_observability_limits(setup.plan, cell),
            replay_level="state_and_score",
        )
    )
    write_evaluation_receipt(
        receipt, execution.evidence.root / "evaluation_receipt.json"
    )
    return receipt


def finalize_family_failure(
    *,
    setup: EvaluationSetup,
    cell_id: str,
    evidence_root: str | Path,
    error: BaseException,
    leaf_builder: Callable[[Mapping[str, Any]], MeasurementLeafSpec],
) -> EvaluationReceipt:
    """Seal one reconciled failed attempt as a typed receipt exclusion."""

    verify_run_plan(setup.plan)
    cell = next((item for item in setup.plan.cells if item.cell_id == cell_id), None)
    if cell is None:
        raise ValueError("failure cell is absent from the family RunPlan")
    attempt_root = RunLayout(
        Path(evidence_root), setup.plan.run_plan_id
    ).resolve_attempts_dir(cell.cell_id)
    attempts = (
        sorted(path for path in attempt_root.iterdir() if path.is_dir())
        if attempt_root.is_dir()
        else []
    )
    if len(attempts) != 1:
        raise ValueError("family failure must resolve to exactly one episode attempt")
    evidence = EvidenceStore.audit_existing(attempts[0])
    failure_conditions: list[str] = []
    for event in evidence.read_events():
        if event.event_type not in {
            "provider_call_failed",
            "provider_call_outcome_unknown",
            "action_attempt_failed",
            "action_attempt_outcome_unknown",
        }:
            continue
        payload = evidence.read_event_payload(event)
        condition = (
            payload.get("failure_condition") if isinstance(payload, Mapping) else None
        )
        if isinstance(condition, str) and condition:
            failure_conditions.append(condition)
    retryable_conditions = {
        "length",
        "rate_limit",
        "provider_5xx",
        "timeout",
        "transport",
    }
    if any(condition in retryable_conditions for condition in failure_conditions):
        failure_class = "retryable_infrastructure"
    elif any(condition == "provider_contract" for condition in failure_conditions):
        failure_class = "integration_or_configuration"
    else:
        failure_class = "environment_failure"
    condition = (
        failure_conditions[-1] if failure_conditions else "family_execution_failure"
    )
    if not all(character.isalnum() or character in "_-" for character in condition):
        condition = "family_execution_failure"

    evidence_seal = evidence.seal()
    case = next(item for item in setup.plan.cases if item.case_id == cell.case_id)
    family = next(
        item for item in setup.plan.families if item.family.id == cell.family_id
    )
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    leaf = leaf_builder(family_case)
    receipt = seal_evaluation_receipt(
        EvaluationReceipt(
            spec_version=EvaluationReceipt.SPEC_VERSION,
            receipt_sha256=None,
            status="invalid_measurement",
            inclusion_status="excluded",
            run_plan_id=setup.plan.run_plan_id,
            run_plan_sha256=setup.plan.plan_sha256,
            cell_id=cell.cell_id,
            case_id=case.case_id,
            case_sha256=case.content_sha256,
            suite_id=setup.plan.suite.suite_id,
            suite_version=setup.plan.suite.version,
            block_id=cell.block_id,
            sampling_plan_id=cell.sampling_plan_id,
            analysis_plan_id=cell.analysis_plan_id,
            episode_id=evidence_seal.episode_id,
            episode_attempt_id=evidence_seal.episode_attempt_id,
            cluster_id=cell.cluster_id,
            cluster_level=cell.cluster_level,
            observations_per_cluster=cell.observations_per_cluster,
            parent_cluster_id=None,
            pair_id=cell.pair_id,
            paired_fields=cell.paired_fields,
            replicate_index=cell.replicate_index,
            panel_mode=cell.panel_mode,
            agent_profile_sha256_by_seat=_agent_profile_digests(setup.plan, cell),
            implementation_refs=(
                leaf.estimand.validity_domain.predicate,
                leaf.verifier.reference.implementation,
                leaf.scorer,
            ),
            plan_implementation_pins=setup.plan.implementation_pins,
            evidence=evidence_seal,
            primary_leaf_id=leaf.leaf_id,
            scores=(),
            failure=EvaluationFailure(
                failure_class=failure_class,
                condition=condition,
                message=str(error) or type(error).__name__,
            ),
            observability_limits=_observability_limits(setup.plan, cell),
            replay_level="none",
        )
    )
    write_evaluation_receipt(receipt, evidence.root / "evaluation_receipt.json")
    evidence.close()
    return receipt


def replay_family_receipt(
    *,
    setup: EvaluationSetup,
    receipt: EvaluationReceipt,
    evidence_root: str | Path,
) -> EvaluationReceipt:
    """Recompute the family score from sealed evidence without a provider call."""

    verify_run_plan(setup.plan)
    verify_evaluation_receipt(receipt)
    try:
        expected_plan, _drift = plan_with_recorded_pins(
            setup.plan, receipt.plan_implementation_pins
        )
    except PlanResolutionError as error:
        raise ValueError(
            "receipt does not belong to the family RunPlan: implementation pins differ"
        ) from error
    if (
        receipt.run_plan_id != expected_plan.run_plan_id
        or receipt.run_plan_sha256 != expected_plan.plan_sha256
    ):
        raise ValueError("receipt does not belong to the family RunPlan")
    cell = next(
        (item for item in setup.plan.cells if item.cell_id == receipt.cell_id),
        None,
    )
    if cell is None or cell.case_sha256 != receipt.case_sha256:
        raise ValueError("receipt cell/case identity does not match the family plan")
    seat_context = _seat_context_for_cell(setup.plan, cell)
    _check_seat_context_seat_set(seat_context, receipt.agent_profile_sha256_by_seat)
    evidence_path = RunLayout(
        Path(evidence_root), receipt.run_plan_id
    ).resolve_attempt_dir(receipt.cell_id, receipt.episode_attempt_id)
    evidence = EvidenceStore.audit_existing(evidence_path)
    if evidence.verify_seal() != receipt.evidence:
        raise ValueError("receipt evidence seal does not match durable evidence")
    receipt_path = evidence_path / "evaluation_receipt.json"
    if (
        not receipt_path.is_file()
        or receipt_path.read_bytes() != canonical_json_bytes(receipt) + b"\n"
    ):
        raise ValueError("durable family receipt bytes do not match")

    events = evidence.read_events()
    score_events = tuple(
        event for event in events if event.event_type == "score_recorded"
    )
    if len(score_events) != 1:
        raise ValueError("sealed family evidence has incomplete score boundaries")
    score_payload = evidence.read_event_payload(score_events[0])
    if not isinstance(score_payload, Mapping):
        raise ValueError("sealed family score evidence is malformed")
    case = next(item for item in setup.plan.cases if item.case_id == cell.case_id)
    family = next(
        item for item in setup.plan.families if item.family.id == cell.family_id
    )
    registration = setup.registry.resolve_registration(
        family.family.id, family.family.version, family.family.plugin_id
    )
    plugin = registration.plugin
    family_case = plugin.validate_payload(case.payload)
    scoring_input = replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=evidence,
        seat_context=seat_context,
    )
    replayed_score_set = normalize_family_score_set(
        plugin.build_scorer(family_case)(
            scoring_input,
            evidence_refs=scoring_input.evidence_refs,
        )
    )
    _check_evidence_refs_are_scoring_input_verbatim(replayed_score_set, scoring_input)
    # Ruling R13: same "exactly once, threaded to both" discipline as
    # finalize_family_execution.
    inapplicable_ids = _inapplicable_leaf_ids(plugin, family_case)
    _enforce_declared_leaf_policy(
        replayed_score_set, registration.manifest, seat_context, inapplicable_ids
    )
    if canonical_json_bytes(score_payload) != canonical_json_bytes(
        _score_event_payload(
            replayed_score_set, outcome_event_id=scoring_input.evidence_refs[-1]
        )
    ):
        raise ValueError("recorded family score does not replay deterministically")
    if canonical_json_bytes(receipt.scores) != canonical_json_bytes(
        replayed_score_set.scores
    ):
        raise ValueError("receipt family score does not replay deterministically")
    if receipt.deferred_leaf_ids != tuple(
        sorted(set(_declared_deferred_leaf_ids(registration.manifest)) - inapplicable_ids)
    ):
        raise ValueError("receipt deferred_leaf_ids does not match the declared policy")
    if receipt.inapplicable_leaf_ids != tuple(sorted(inapplicable_ids)):
        raise ValueError(
            "receipt inapplicable_leaf_ids does not match the declared policy"
        )
    expected_status, expected_inclusion, expected_failure = _score_admission(
        replayed_score_set
    )
    if (
        receipt.primary_leaf_id != replayed_score_set.primary_leaf_id
        or receipt.status != expected_status
        or receipt.inclusion_status != expected_inclusion
        or canonical_json_bytes(receipt.failure)
        != canonical_json_bytes(expected_failure)
        or canonical_json_bytes(receipt.implementation_refs)
        != canonical_json_bytes(_receipt_implementations(replayed_score_set))
    ):
        raise ValueError("receipt admission does not match the replayed score set")
    evidence.close()
    return receipt


def _recorded_pins(receipt: Mapping[str, Any]) -> tuple[ImplementationPin, ...]:
    value = receipt.get("plan_implementation_pins")
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("receipt plan_implementation_pins does not match the sealed plan")
    try:
        return tuple(ImplementationPin.from_dict(item) for item in value)
    except PlanResolutionError as error:
        raise ValueError(
            "receipt plan_implementation_pins does not match the sealed plan"
        ) from error


def _plan_recorded_by(plan: RunPlan, receipt: Mapping[str, Any]) -> RunPlan:
    """The plan identity ``receipt`` was sealed under, given the current plan.

    Family-owned pins must match the current code exactly; kernel-owned pins
    may have moved since sealing and are taken from the receipt so its
    ``run_plan_id`` still audits. See ``plan_with_recorded_pins``.
    """

    try:
        expected_plan, _drift = plan_with_recorded_pins(plan, _recorded_pins(receipt))
    except PlanResolutionError as error:
        raise ValueError(
            "receipt plan_implementation_pins does not match the sealed plan"
        ) from error
    return expected_plan


def receipt_implementation_drift(
    plan: RunPlan, receipt: Mapping[str, Any]
) -> tuple[str, ...]:
    """Name the kernel-owned components whose bytes moved since ``receipt`` sealed.

    Each entry is ``implementation_drift:<component_id>``. An empty tuple means
    the receipt was sealed under exactly the pins ``plan`` carries now. Family
    pin differences are not drift; they raise, because the receipt no longer
    audits against the family code that produced it.
    """

    try:
        _plan, drift = plan_with_recorded_pins(plan, _recorded_pins(receipt))
    except PlanResolutionError as error:
        raise ValueError(
            "receipt plan_implementation_pins does not match the sealed plan"
        ) from error
    return drift


def audit_family_receipt(
    *,
    setup: EvaluationSetup,
    receipt_path: str | Path,
) -> Mapping[str, Any]:
    """Audit durable JSON on resume, including state/score replay for completed cells.

    Operational exclusions are verified as exclusions, never assigned an economic
    score. This function performs no provider calls and writes no evidence.
    """
    verify_run_plan(setup.plan)
    receipt_path = Path(receipt_path)
    receipt = read_evaluation_receipt(receipt_path)
    cell = next(
        (c for c in setup.plan.cells if c.cell_id == receipt.get("cell_id")), None
    )
    if cell is None:
        raise ValueError("receipt cell is absent from the family plan")
    seat_context = _seat_context_for_cell(setup.plan, cell)
    _check_seat_context_seat_set(
        seat_context, receipt.get("agent_profile_sha256_by_seat") or {}
    )
    expected_plan = _plan_recorded_by(setup.plan, receipt)
    expected = {
        "run_plan_id": expected_plan.run_plan_id,
        "run_plan_sha256": expected_plan.plan_sha256,
        "case_id": cell.case_id,
        "case_sha256": cell.case_sha256,
        "suite_id": setup.plan.suite.suite_id,
        "suite_version": setup.plan.suite.version,
        "block_id": cell.block_id,
        "sampling_plan_id": cell.sampling_plan_id,
        "analysis_plan_id": cell.analysis_plan_id,
        "cluster_id": cell.cluster_id,
        "cluster_level": cell.cluster_level,
        "observations_per_cluster": cell.observations_per_cluster,
        "pair_id": cell.pair_id,
        "paired_fields": cell.paired_fields,
        "replicate_index": cell.replicate_index,
        "panel_mode": cell.panel_mode,
        "parent_cluster_id": None,
        "agent_profile_sha256_by_seat": _agent_profile_digests(setup.plan, cell),
        "plan_implementation_pins": expected_plan.implementation_pins,
        "observability_limits": _observability_limits(setup.plan, cell),
    }
    for key, value in expected.items():
        if canonical_json_bytes(receipt.get(key)) != canonical_json_bytes(value):
            raise ValueError(f"receipt {key} does not match the sealed plan")
    root = receipt_path.parent
    canonical_identity = (
        root.name == receipt.get("episode_attempt_id")
        and root.parent.name == "attempts"
        and root.parent.parent.name == cell.cell_id
        and root.parent.parent.parent.name == "tasks"
        and root.parent.parent.parent.parent.name == expected_plan.run_plan_id
    )
    legacy_identity = (
        root.name == receipt.get("episode_attempt_id")
        and root.parent.name == cell.cell_id
        and root.parent.parent.name == expected_plan.run_plan_id
    )
    if not canonical_identity and not legacy_identity:
        raise ValueError("receipt directory identity does not match the sealed plan")
    evidence = EvidenceStore.audit_existing(root)
    seal = evidence.verify_seal()
    if canonical_json_bytes(seal) != canonical_json_bytes(
        receipt.get("evidence")
    ) or seal.episode_id != receipt.get("episode_id"):
        raise ValueError("receipt evidence seal mismatch")
    if receipt.get("scores"):
        family = next(f for f in setup.plan.families if f.family.id == cell.family_id)
        case = next(c for c in setup.plan.cases if c.case_id == cell.case_id)
        registration = setup.registry.resolve_registration(
            family.family.id, family.family.version, family.family.plugin_id
        )
        plugin = registration.plugin
        family_case = plugin.validate_payload(case.payload)
        scoring_input = replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=evidence,
            seat_context=seat_context,
        )
        score_set = normalize_family_score_set(
            plugin.build_scorer(family_case)(
                scoring_input, evidence_refs=scoring_input.evidence_refs
            )
        )
        _check_evidence_refs_are_scoring_input_verbatim(score_set, scoring_input)
        # Ruling R13: same "exactly once, threaded to both" discipline as
        # finalize_family_execution/replay_family_receipt.
        inapplicable_ids = _inapplicable_leaf_ids(plugin, family_case)
        _enforce_declared_leaf_policy(
            score_set, registration.manifest, seat_context, inapplicable_ids
        )
        events = [e for e in evidence.read_events() if e.event_type == "score_recorded"]
        expected_status, expected_inclusion, expected_failure = _score_admission(
            score_set
        )
        if (
            len(events) != 1
            or canonical_json_bytes(evidence.read_event_payload(events[0]))
            != canonical_json_bytes(
                _score_event_payload(
                    score_set, outcome_event_id=scoring_input.evidence_refs[-1]
                )
            )
            or canonical_json_bytes(receipt["scores"])
            != canonical_json_bytes(score_set.scores)
        ):
            raise ValueError("receipt score does not replay deterministically")
        if (
            receipt.get("status") != expected_status
            or receipt.get("inclusion_status") != expected_inclusion
            or receipt.get("replay_level") != "state_and_score"
            or receipt.get("primary_leaf_id") != score_set.primary_leaf_id
            or canonical_json_bytes(receipt.get("implementation_refs"))
            != canonical_json_bytes(_receipt_implementations(score_set))
            or canonical_json_bytes(receipt.get("failure"))
            != canonical_json_bytes(expected_failure)
            or tuple(receipt.get("deferred_leaf_ids") or ())
            != tuple(
                sorted(
                    set(_declared_deferred_leaf_ids(registration.manifest))
                    - inapplicable_ids
                )
            )
            or tuple(receipt.get("inapplicable_leaf_ids") or ())
            != tuple(sorted(inapplicable_ids))
        ):
            raise ValueError("receipt admission does not match the replayed score")
    elif (
        receipt.get("status") != "invalid_measurement"
        or receipt.get("inclusion_status") != "excluded"
        or receipt.get("replay_level") != "none"
        or not isinstance(receipt.get("failure"), Mapping)
    ):
        raise ValueError("unscored receipt must be a typed operational exclusion")
    evidence.close()
    return receipt
