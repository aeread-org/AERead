from __future__ import annotations

import hashlib

import pytest

from aeread.shared_runner import (
    DesignObservation,
    EstimandSpec,
    EvaluationReceipt,
    EvidenceSeal,
    EvidenceStore,
    MeasurementImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ResearchContractError,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
    audit_experimental_design,
    build_research_ledger,
    canonical_json_bytes,
    episode_id_for_cell,
    project_evidence_events,
    research_tables,
    seal_evaluation_receipt,
)
from aeread.shared_runner.smoke import build_single_offer_smoke


def _plan():
    return build_single_offer_smoke(
        provider="fake",
        model="fake-model",
        revision="fixed-v1",
    ).plan


def _score(plan) -> ScoreEnvelope:
    pin = next(
        pin
        for pin in plan.implementation_pins
        if pin.component_id == "single_offer_scorer_v1"
    )
    implementation = MeasurementImplementationRef(
        pin.component_id,
        pin.version,
        pin.sha256,
    )
    domain = ValidityDomainSpec(
        domain_id="single_offer_answer_domain",
        domain_version="1.0.0",
        schema_ref="single_offer_v1/answer/1",
        predicate=implementation,
    )
    estimand = EstimandSpec(
        estimand_id="submitted_offer_validity",
        estimand_version="1.0.0",
        input_scope="answer",
        direction="none",
        units="binary",
        validity_domain=domain,
    )
    leaf = MeasurementLeafSpec(
        leaf_id="single_offer_validity_leaf",
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="canonical_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="single_offer_answer_reference",
                reference_version="1.0.0",
                reference_kind="canonical_point",
                input_scope="answer",
                units="binary",
                source_sha256="b" * 64,
                implementation=implementation,
            ),
        ),
        scorer=implementation,
    )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "binary"),
        metrics={"passed": MetricValue(1.0, "binary")},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=("artifact_outcome",),
    )


def _receipt(plan, *, attempt_id: str = "attempt_000") -> EvaluationReceipt:
    cell = plan.cells[0]
    score = _score(plan)
    episode_id = episode_id_for_cell(cell)
    profile_by_id = {profile.profile_id: profile for profile in plan.agent_profiles}
    profile_hashes = {
        seat: hashlib.sha256(
            canonical_json_bytes(profile_by_id[profile_id])
        ).hexdigest()
        for seat, profile_id in cell.profile_by_seat.items()
    }
    return seal_evaluation_receipt(
        EvaluationReceipt(
            spec_version=EvaluationReceipt.SPEC_VERSION,
            receipt_sha256=None,
            status="ok",
            inclusion_status="included",
            run_plan_id=plan.run_plan_id,
            run_plan_sha256=plan.plan_sha256,
            cell_id=cell.cell_id,
            case_id=cell.case_id,
            case_sha256=cell.case_sha256,
            suite_id=cell.suite_id,
            suite_version=cell.suite_version,
            block_id=cell.block_id,
            sampling_plan_id=cell.sampling_plan_id,
            analysis_plan_id=cell.analysis_plan_id,
            episode_id=episode_id,
            episode_attempt_id=attempt_id,
            cluster_id=cell.cluster_id,
            cluster_level=cell.cluster_level,
            observations_per_cluster=cell.observations_per_cluster,
            parent_cluster_id=None,
            pair_id=cell.pair_id,
            paired_fields=cell.paired_fields,
            replicate_index=cell.replicate_index,
            panel_mode=cell.panel_mode,
            agent_profile_sha256_by_seat=profile_hashes,
            implementation_refs=(score.leaf.scorer,),
            plan_implementation_pins=plan.implementation_pins,
            evidence=EvidenceSeal(
                run_plan_id=plan.run_plan_id,
                cell_id=cell.cell_id,
                episode_id=episode_id,
                episode_attempt_id=attempt_id,
                event_count=12,
                artifact_count=4,
                event_root_sha256="e" * 64,
                artifact_root_sha256="f" * 64,
            ),
            primary_leaf_id=score.leaf.leaf_id,
            scores=(score,),
            failure=None,
            replay_level="state_and_score",
        )
    )


def test_research_ledger_preserves_complete_plan_grid_and_receipt_attempts() -> None:
    plan = _plan()

    empty = build_research_ledger(plan, ())
    assert empty.campaign.expected_cells == 1
    assert empty.campaign.receipted_cells == 0
    assert empty.campaign.not_started_cells == 1
    assert empty.campaign.coverage == 0.0
    assert empty.cells[0].status == "not_started"

    ledger = build_research_ledger(plan, (_receipt(plan),))
    assert ledger.campaign.expected_cells == 1
    assert ledger.campaign.receipted_cells == 1
    assert ledger.campaign.included_cells == 1
    assert ledger.campaign.excluded_cells == 0
    assert ledger.campaign.not_started_cells == 0
    assert ledger.campaign.coverage == 1.0
    assert ledger.cells[0].status == "included"
    assert ledger.cells[0].receipt_count == 1
    assert len(ledger.cells[0].repeat_equivalence_sha256) == 64
    assert ledger.attempts[0].primary_value == 1.0
    assert ledger.attempts[0].primary_unit == "binary"

    tables = research_tables(ledger)
    assert tuple(tables) == ("campaigns", "cells", "attempts")
    assert tables["campaigns"][0]["coverage"] == 1.0
    assert tables["cells"][0]["status"] == "included"


def test_research_ledger_rejects_multiple_included_attempts_for_one_cell() -> None:
    plan = _plan()
    with pytest.raises(ResearchContractError, match="multiple included receipts"):
        build_research_ledger(
            plan,
            (_receipt(plan, attempt_id="attempt_000"), _receipt(plan, attempt_id="attempt_001")),
        )


def test_operational_phase_projection_keeps_domain_phase_separate(tmp_path) -> None:
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_001",
        cell_id="cell_001",
        episode_id="episode_001",
        episode_attempt_id="attempt_001",
        clock=lambda: "2026-08-29T00:00:00Z",
    )
    evidence.append_event(
        "phase_instance_started",
        {"phase": {"phase_id": "contact"}},
        phase_instance_id="phase_001",
    )
    evidence.append_event(
        "logical_action_started",
        {"profile_id": "tenant_profile"},
        phase_instance_id="phase_001",
        logical_action_id="action_001",
    )
    evidence.append_event(
        "action_attempt_started",
        {"ordinal": 1, "retry_reason": "rate_limit"},
        phase_instance_id="phase_001",
        logical_action_id="action_001",
        action_attempt_id="action_attempt_001",
    )
    evidence.append_event(
        "transition_applied",
        {"phase_id": "contact", "post_state_sha256": "a" * 64},
        phase_instance_id="phase_001",
    )

    rows = project_evidence_events(evidence)
    by_type = {row.event_type: row for row in rows}
    assert by_type["phase_instance_started"].harness_phase == "planning"
    assert by_type["logical_action_started"].harness_phase == "execution"
    assert by_type["action_attempt_started"].harness_phase == "recovery"
    assert by_type["transition_applied"].harness_phase == "finalization"
    assert by_type["logical_action_started"].domain_phase_id == "contact"
    assert by_type["logical_action_started"].domain_phase_instance_id == "phase_001"
    evidence.close()


def _observation(identifier: str, cluster: str, **factors: str) -> DesignObservation:
    return DesignObservation(identifier, cluster, factors)


def test_design_audit_rejects_perfect_alias_and_missing_overlap() -> None:
    observations = (
        _observation("o1", "c1", harness="direct", budget="low"),
        _observation("o2", "c2", harness="planner", budget="high"),
    )
    audit = audit_experimental_design(
        observations,
        focal_factors=("harness", "budget"),
        nuisance_factors=(),
        minimum_clusters_per_level=1,
    )
    assert audit.status == "invalid"
    assert "perfect_alias" in {issue.code for issue in audit.issues}

    overlap = audit_experimental_design(
        observations,
        focal_factors=("harness",),
        nuisance_factors=("budget",),
        minimum_clusters_per_level=1,
    )
    assert "no_overlap" in {issue.code for issue in overlap.issues}


def test_design_audit_accepts_crossed_comparison() -> None:
    observations = (
        _observation("o1", "c1", harness="direct", budget="low"),
        _observation("o2", "c2", harness="planner", budget="low"),
        _observation("o3", "c3", harness="direct", budget="high"),
        _observation("o4", "c4", harness="planner", budget="high"),
    )
    audit = audit_experimental_design(
        observations,
        focal_factors=("harness",),
        nuisance_factors=("budget",),
        minimum_clusters_per_level=2,
    )
    assert audit.status == "valid"
    assert audit.issues == ()
