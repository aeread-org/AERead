from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner import (
    DesignObservation,
    EstimandSpec,
    EvaluationReceipt,
    EvidenceSeal,
    EvidenceStore,
    LossAnalysisTables,
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
    build_trajectory_record,
    canonical_json_bytes,
    episode_id_for_cell,
    export_loss_analysis_dataset,
    project_evidence_events,
    project_loss_analysis_tables,
    research_tables,
    resolve_run_plan,
    seal_evaluation_receipt,
    write_evaluation_receipt,
    write_run_plan,
)
from aeread.shared_runner.research import main as export_tables_main
from aeread.shared_runner.smoke import build_single_offer_smoke


def _plan():
    return build_single_offer_smoke(
        provider="fake",
        model="fake-model",
        revision="fixed-v1",
    ).plan


def _score(plan, *, passed: bool = True) -> ScoreEnvelope:
    pin = next(
        (
            pin
            for pin in plan.implementation_pins
            if pin.component_id == "single_offer_scorer_v1"
        ),
        next(pin for pin in plan.implementation_pins if pin.kind == "scorer"),
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
        primary=MetricValue(float(passed), "binary"),
        metrics={"passed": MetricValue(float(passed), "binary")},
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


def _housing_plan():
    # Reuse the resolver's two-seat authoring fixture so this projection test
    # exercises a genuinely sealed multi-profile plan.
    from tests.test_shared_runner_resolver import _inputs

    return resolve_run_plan(**_inputs())


def _loss_evidence(plan, tmp_path: Path) -> EvidenceStore:
    cell = plan.cells[0]
    episode_id = episode_id_for_cell(cell)
    ticks = iter(range(30))
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=episode_id,
        episode_attempt_id="attempt_loss_001",
        clock=lambda: f"2026-08-31T00:00:{next(ticks):02d}Z",
    )
    evidence.append_event(
        "phase_instance_started",
        {"phase": {"phase_id": "contact"}},
        phase_instance_id="phase_contact_001",
    )
    evidence.append_event(
        "logical_action_started",
        {"profile_id": cell.profile_by_seat["tenant_0"], "request": {"seat_id": "tenant_0"}},
        phase_instance_id="phase_contact_001",
        logical_action_id="action_tenant_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "action_attempt_started",
        {"ordinal": 0, "retry_reason": None},
        phase_instance_id="phase_contact_001",
        logical_action_id="action_tenant_001",
        action_attempt_id="attempt_tenant_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "provider_call_started",
        {
            "request": {
                "provider": "openai",
                "model": "test-model",
                "instructions": "Find a valid listing.",
                "input_text": "contact landlord",
                "messages": [{"role": "user", "content": "contact landlord"}],
            }
        },
        phase_instance_id="phase_contact_001",
        logical_action_id="action_tenant_001",
        action_attempt_id="attempt_tenant_001",
        provider_call_id="call_tenant_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "provider_call_succeeded",
        {
            "provider_result": {
                "requested_model": "test-model",
                "resolved_model": "test-model-2026-08-01",
                "output_text": "CONTACT listing_1",
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 10,
            },
            "cost_usd": 0.01,
        },
        phase_instance_id="phase_contact_001",
        logical_action_id="action_tenant_001",
        action_attempt_id="attempt_tenant_001",
        provider_call_id="call_tenant_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "action_attempt_succeeded",
        {},
        phase_instance_id="phase_contact_001",
        logical_action_id="action_tenant_001",
        action_attempt_id="attempt_tenant_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "logical_action_succeeded",
        {},
        phase_instance_id="phase_contact_001",
        logical_action_id="action_tenant_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "logical_action_started",
        {
            "profile_id": cell.profile_by_seat["landlord_0"],
            "request": {"seat_id": "landlord_0"},
        },
        phase_instance_id="phase_contact_001",
        logical_action_id="action_landlord_001",
        visibility="seat:landlord_0",
    )
    evidence.append_event(
        "action_attempt_started",
        {"ordinal": 1, "retry_reason": "rate_limit"},
        phase_instance_id="phase_contact_001",
        logical_action_id="action_landlord_001",
        action_attempt_id="attempt_landlord_002",
        visibility="seat:landlord_0",
    )
    evidence.append_event(
        "provider_call_started",
        {
            "request": {
                "provider": "aeread",
                "model": "fixed_landlord_v1",
                "instructions": "Respond to the tenant.",
                "input_text": "retry response",
                "messages": None,
            }
        },
        phase_instance_id="phase_contact_001",
        logical_action_id="action_landlord_001",
        action_attempt_id="attempt_landlord_002",
        provider_call_id="call_landlord_001",
        visibility="seat:landlord_0",
    )
    evidence.append_event(
        "provider_call_failed",
        {
            "failure_condition": "rate_limit",
            "message": "retry budget exhausted",
            "cost_usd": 0.0,
        },
        phase_instance_id="phase_contact_001",
        logical_action_id="action_landlord_001",
        action_attempt_id="attempt_landlord_002",
        provider_call_id="call_landlord_001",
    )
    evidence.append_event(
        "action_attempt_failed",
        {"failure_condition": "rate_limit"},
        phase_instance_id="phase_contact_001",
        logical_action_id="action_landlord_001",
        action_attempt_id="attempt_landlord_002",
    )
    evidence.append_event(
        "logical_action_failed",
        {"failure_condition": "rate_limit"},
        phase_instance_id="phase_contact_001",
        logical_action_id="action_landlord_001",
    )
    evidence.append_event(
        "tool_invocation_started",
        {"tool_id": "listing_lookup", "arguments": {"listing_id": "listing_1"}},
        phase_instance_id="phase_contact_001",
        action_attempt_id="attempt_tenant_001",
        tool_invocation_id="tool_lookup_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "tool_invocation_succeeded",
        {"result": {"available": True}},
        phase_instance_id="phase_contact_001",
        action_attempt_id="attempt_tenant_001",
        tool_invocation_id="tool_lookup_001",
        visibility="seat:tenant_0",
    )
    evidence.append_event(
        "transition_applied",
        {"phase_id": "contact", "post_state_sha256": "a" * 64},
        phase_instance_id="phase_contact_001",
    )
    evidence.seal()
    return evidence


def _receipt_for_evidence(
    plan, evidence: EvidenceStore, *, passed: bool = True
) -> EvaluationReceipt:
    cell = next(item for item in plan.cells if item.cell_id == evidence.cell_id)
    score = _score(plan, passed=passed)
    profile_by_id = {profile.profile_id: profile for profile in plan.agent_profiles}
    profile_hashes = {
        seat: hashlib.sha256(canonical_json_bytes(profile_by_id[profile_id])).hexdigest()
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
            episode_id=evidence.episode_id,
            episode_attempt_id=evidence.episode_attempt_id,
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
            evidence=evidence.verify_seal(),
            primary_leaf_id=score.leaf.leaf_id,
            scores=(score,),
            failure=None,
            replay_level="state_and_score",
        )
    )


def test_loss_analysis_projection_attributes_seats_phases_and_rollups(tmp_path) -> None:
    plan = _housing_plan()
    evidence = _loss_evidence(plan, tmp_path)
    receipt = _receipt_for_evidence(plan, evidence)

    tables = project_loss_analysis_tables(
        plan, (receipt,), {receipt.episode_attempt_id: evidence}
    )

    assert isinstance(tables, LossAnalysisTables)
    run = tables.runs[0]
    task = next(row for row in tables.tasks if row.task_id == evidence.cell_id)
    assert run.tasks_expected == len(plan.cells)
    assert run.tasks_executed == 1
    assert run.tasks_passed == 1
    assert run.call_count == task.call_count == 2
    assert run.exception_count == task.exception_count == 1
    assert run.prompt_tokens == task.prompt_tokens == 100
    assert run.cached_tokens == task.cached_tokens == 20
    assert run.completion_tokens == task.completion_tokens == 10
    assert run.total_tokens == task.total_tokens == 110
    assert run.total_cost_usd == task.cost_usd == pytest.approx(0.01)
    assert run.latency_seconds == task.latency_seconds == pytest.approx(2.0)
    assert task.passed is True
    assert task.telemetry_complete is True

    first, second = tables.model_calls
    assert (first.seat_id, first.harness_phase, first.domain_phase_id) == (
        "tenant_0",
        "execution",
        "contact",
    )
    assert (second.seat_id, second.harness_phase, second.domain_phase_id) == (
        "landlord_0",
        "recovery",
        "contact",
    )
    assert second.exception_type == "rate_limit"
    evidence.close()


def test_loss_analysis_counts_completed_benchmark_failure(tmp_path) -> None:
    plan = _housing_plan()
    evidence = _loss_evidence(plan, tmp_path)
    receipt = _receipt_for_evidence(plan, evidence, passed=False)

    tables = project_loss_analysis_tables(
        plan, (receipt,), {receipt.episode_attempt_id: evidence}
    )

    assert tables.tasks[0].task_status == "completed"
    assert tables.tasks[0].passed is False
    assert tables.runs[0].tasks_passed == 0
    assert tables.runs[0].tasks_failed == 1
    evidence.close()


def test_loss_analysis_preserves_unknown_call_telemetry_as_null(tmp_path) -> None:
    plan = _plan()
    cell = plan.cells[0]
    seat_id = next(iter(cell.profile_by_seat))
    episode_id = episode_id_for_cell(cell)
    evidence = EvidenceStore(
        tmp_path / "unknown_evidence",
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=episode_id,
        episode_attempt_id="attempt_unknown_001",
    )
    evidence.append_event(
        "provider_call_started",
        {"request": {"provider": "fake", "model": "fake-model"}},
        logical_action_id="action_unknown_001",
        action_attempt_id="attempt_unknown_001",
        provider_call_id="call_unknown_001",
        visibility=f"seat:{seat_id}",
    )
    evidence.append_event(
        "provider_call_outcome_unknown",
        {"failure_condition": "interrupted_during_provider_call"},
        logical_action_id="action_unknown_001",
        action_attempt_id="attempt_unknown_001",
        provider_call_id="call_unknown_001",
        visibility=f"seat:{seat_id}",
    )

    tables = project_loss_analysis_tables(
        plan, (), {evidence.episode_attempt_id: evidence}
    )

    call = tables.model_calls[0]
    task = tables.tasks[0]
    run = tables.runs[0]
    assert call.status == "outcome_unknown"
    assert call.exception_type == "interrupted_during_provider_call"
    assert call.prompt_tokens is None
    assert call.total_cost_usd is None
    assert call.telemetry_complete is False
    assert task.prompt_tokens is None
    assert task.cost_usd is None
    assert task.telemetry_complete is False
    assert run.prompt_tokens is None
    assert run.total_cost_usd is None
    assert run.telemetry_complete is False
    evidence.close()


def test_trajectory_extracts_messages_tools_outputs_and_errors(tmp_path) -> None:
    plan = _housing_plan()
    evidence = _loss_evidence(plan, tmp_path)
    receipt = _receipt_for_evidence(plan, evidence)

    trajectory = build_trajectory_record(evidence, receipt)
    by_type = {}
    for step in trajectory.steps:
        by_type.setdefault(step.event_type, []).append(step)

    started = by_type["provider_call_started"][0]
    assert started.messages == [{"role": "user", "content": "contact landlord"}]
    assert started.input["input_text"] == "contact landlord"
    assert by_type["provider_call_succeeded"][0].output == "CONTACT listing_1"
    assert by_type["tool_invocation_started"][0].tool_name == "listing_lookup"
    assert by_type["tool_invocation_started"][0].input == {"listing_id": "listing_1"}
    assert by_type["tool_invocation_succeeded"][0].output == {"available": True}
    assert by_type["provider_call_failed"][0].error == (
        "rate_limit: retry budget exhausted"
    )
    assert trajectory.passed is True
    assert trajectory.event_root_sha256 == receipt.evidence.event_root_sha256
    evidence.close()


def test_loss_analysis_export_writes_relational_and_trajectory_files(tmp_path) -> None:
    plan = _housing_plan()
    evidence = _loss_evidence(plan, tmp_path)
    receipt = _receipt_for_evidence(plan, evidence)
    output = tmp_path / "dataset"

    paths = export_loss_analysis_dataset(
        plan, (receipt,), {receipt.episode_attempt_id: evidence}, output
    )

    assert set(paths) == {
        "runs",
        "tasks",
        "model_calls",
        "trajectory_index",
        "trajectory_archive",
        "data_dictionary",
        "selected_trajectories",
    }
    with paths["runs"].open(newline="") as handle:
        run_rows = list(csv.DictReader(handle))
    with paths["tasks"].open(newline="") as handle:
        task_rows = list(csv.DictReader(handle))
    with paths["model_calls"].open(newline="") as handle:
        call_rows = list(csv.DictReader(handle))
    assert len(run_rows) == 1
    assert len(task_rows) == len(plan.cells)
    assert len(call_rows) == 2
    assert sum(int(row["call_count"]) for row in task_rows) == int(run_rows[0]["call_count"])
    assert sum(int(row["prompt_tokens"] or 0) for row in task_rows) == int(
        run_rows[0]["prompt_tokens"]
    )

    selected = output / "trajectories" / "selected" / (
        f"{plan.run_plan_id}__{evidence.cell_id}.json"
    )
    selected_payload = json.loads(selected.read_text())
    archive_rows = [json.loads(line) for line in paths["trajectory_archive"].read_text().splitlines()]
    assert archive_rows == [selected_payload]
    assert "Outcome-unknown calls" in paths["data_dictionary"].read_text()
    # Exact reruns are idempotent; a different export is never overwritten.
    assert export_loss_analysis_dataset(
        plan, (receipt,), {receipt.episode_attempt_id: evidence}, output
    ) == paths
    evidence.close()


def test_export_tables_cli_loads_and_reverifies_canonical_artifacts(
    tmp_path, capsys
) -> None:
    plan = _housing_plan()
    evidence = _loss_evidence(plan, tmp_path)
    receipt = _receipt_for_evidence(plan, evidence)
    plan_path = tmp_path / "run_plan.json"
    receipt_path = tmp_path / "receipt.json"
    write_run_plan(plan, plan_path)
    write_evaluation_receipt(receipt, receipt_path)
    evidence_path = evidence.root
    evidence.close()

    assert export_tables_main(
        [
            "--plan",
            str(plan_path),
            "--receipts",
            str(receipt_path),
            "--evidence-root",
            str(evidence_path),
            "--output-dir",
            str(tmp_path / "cli-export"),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert Path(output["runs"]).is_file()
    assert Path(output["trajectory_archive"]).is_file()
