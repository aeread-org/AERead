"""Shared family execution finalization, state replay, and portable receipts.

Extracted from the validated Housing receipt path so native families share the
same evidence and inclusion boundary. Economic scoring stays in each plugin.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .execution import CellExecution, EvidenceStore, TokenPricing
from .measurement import (
    FamilyScoreSet,
    ImplementationRef as MeasurementImplementationRef,
    MeasurementLeafSpec,
    ScoreEnvelope,
    normalize_family_score_set,
)
from .registry import PluginRegistry
from .resolver import RunPlan, canonical_json_bytes, verify_run_plan
from .receipts import (
    EvaluationFailure,
    EvaluationReceipt,
    read_evaluation_receipt,
    seal_evaluation_receipt,
    verify_evaluation_receipt,
    write_evaluation_receipt,
)
from .scheduler import ActionEnvelope, LegalityResult, ParseResult, PhaseSpec


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


def _observability_limits(plan: RunPlan, cell: Any) -> tuple[str, ...]:
    profile_by_id = {profile.profile_id: profile for profile in plan.agent_profiles}
    assigned_profiles = tuple(
        profile_by_id[profile_id]
        for profile_id in sorted(set(cell.profile_by_seat.values()))
    )
    if any(profile.model.base_url is not None for profile in assigned_profiles):
        return ("provider_internal_reasoning_not_fully_observable",)
    return ()


def replay_family_state(
    *, plugin: Any, family_case: Mapping[str, Any], evidence: EvidenceStore
) -> tuple[Mapping[str, Any], Any]:
    events = evidence.read_events()
    phase_by_id = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, run=None)
    phase_events = tuple(
        event for event in events if event.event_type == "phase_instance_started"
    )
    if not phase_events:
        raise ValueError("family replay contains no phase boundaries")

    for phase_event in phase_events:
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

        starts = tuple(
            event
            for event in events
            if event.event_type == "logical_action_started"
            and event.phase_instance_id == phase_event.phase_instance_id
        )
        actions: dict[str, ActionEnvelope] = {}
        for start in starts:
            start_payload = evidence.read_event_payload(start)
            request = (
                start_payload.get("request")
                if isinstance(start_payload, Mapping)
                else None
            )
            if not isinstance(request, Mapping):
                raise ValueError("family replay action request is malformed")
            seat_id = request.get("seat_id")
            if not isinstance(seat_id, str) or seat_id in actions:
                raise ValueError("family replay action seat identity is invalid")
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
            valid = parsed.ok and legality is not None and legality.legal
            actions[seat_id] = ActionEnvelope(
                seat_id=seat_id,
                valid=valid,
                action=parsed.action if valid else None,
                parse=parsed,
                legality=legality,
            )
        if tuple(sorted(actions)) != tuple(sorted(eligible)):
            raise ValueError("family replay action set does not match eligible actors")

        transition_events = tuple(
            event
            for event in events
            if event.event_type == "transition_applied"
            and event.phase_instance_id == phase_event.phase_instance_id
        )
        if len(transition_events) != 1:
            raise ValueError("family replay phase lacks one transition")
        transition_payload = evidence.read_event_payload(transition_events[0])
        if not isinstance(transition_payload, Mapping):
            raise ValueError("family replay transition is malformed")
        replayed = plugin.step(family_case, state, phase, actions)
        if canonical_json_bytes(
            transition_payload.get("transition")
        ) != canonical_json_bytes(replayed):
            raise ValueError("family replay transition differs from sealed evidence")
        post_state_sha256 = hashlib.sha256(
            canonical_json_bytes(replayed.state)
        ).hexdigest()
        if transition_payload.get("post_state_sha256") != post_state_sha256:
            raise ValueError("family replay post-state hash mismatch")
        state = replayed.state

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
    outcome = plugin.outcome(family_case, terminal)
    if not isinstance(outcome_payload, Mapping) or canonical_json_bytes(
        outcome_payload.get("outcome")
    ) != canonical_json_bytes(outcome):
        raise ValueError("family replay family outcome differs from sealed evidence")
    return outcome, outcome_events[0]


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
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)

    execution.evidence.audit_reconciliation()
    recorded_outcome, outcome_event = replay_family_state(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
    )
    if canonical_json_bytes(recorded_outcome) != canonical_json_bytes(
        execution.episode_result.outcome
    ):
        raise ValueError("execution outcome does not match the event log")

    score_set = normalize_family_score_set(
        plugin.build_scorer(family_case)(
            recorded_outcome,
            evidence_refs=(outcome_event.event_id,),
        )
    )
    execution.evidence.append_event(
        "score_recorded",
        _score_event_payload(score_set, outcome_event_id=outcome_event.event_id),
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
    attempt_root = Path(evidence_root) / setup.plan.run_plan_id / cell.cell_id
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
    if (
        receipt.run_plan_id != setup.plan.run_plan_id
        or receipt.run_plan_sha256 != setup.plan.plan_sha256
    ):
        raise ValueError("receipt does not belong to the family RunPlan")
    cell = next(
        (item for item in setup.plan.cells if item.cell_id == receipt.cell_id),
        None,
    )
    if cell is None or cell.case_sha256 != receipt.case_sha256:
        raise ValueError("receipt cell/case identity does not match the family plan")
    evidence_path = (
        Path(evidence_root)
        / receipt.run_plan_id
        / receipt.cell_id
        / receipt.episode_attempt_id
    )
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
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    replayed_outcome, outcome_event = replay_family_state(
        plugin=plugin,
        family_case=family_case,
        evidence=evidence,
    )
    replayed_score_set = normalize_family_score_set(
        plugin.build_scorer(family_case)(
            replayed_outcome,
            evidence_refs=(outcome_event.event_id,),
        )
    )
    if canonical_json_bytes(score_payload) != canonical_json_bytes(
        _score_event_payload(
            replayed_score_set, outcome_event_id=outcome_event.event_id
        )
    ):
        raise ValueError("recorded family score does not replay deterministically")
    if canonical_json_bytes(receipt.scores) != canonical_json_bytes(
        replayed_score_set.scores
    ):
        raise ValueError("receipt family score does not replay deterministically")
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
    expected = {
        "run_plan_id": setup.plan.run_plan_id,
        "run_plan_sha256": setup.plan.plan_sha256,
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
        "plan_implementation_pins": setup.plan.implementation_pins,
        "observability_limits": _observability_limits(setup.plan, cell),
    }
    for key, value in expected.items():
        if canonical_json_bytes(receipt.get(key)) != canonical_json_bytes(value):
            raise ValueError(f"receipt {key} does not match the sealed plan")
    root = receipt_path.parent
    if (
        root.name != receipt.get("episode_attempt_id")
        or root.parent.name != cell.cell_id
        or root.parent.parent.name != setup.plan.run_plan_id
    ):
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
        plugin = setup.registry.resolve_manifest(family)
        family_case = plugin.validate_payload(case.payload)
        outcome, outcome_event = replay_family_state(
            plugin=plugin, family_case=family_case, evidence=evidence
        )
        score_set = normalize_family_score_set(
            plugin.build_scorer(family_case)(
                outcome, evidence_refs=(outcome_event.event_id,)
            )
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
                    score_set, outcome_event_id=outcome_event.event_id
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
