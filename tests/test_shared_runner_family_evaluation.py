from __future__ import annotations

import asyncio
import dataclasses

import pytest

from aeread.shared_runner import (
    FamilyScoreSet,
    MetricValue,
    ScoreEnvelope,
    ValidityReport,
    canonical_json_bytes,
    verify_evaluation_receipt,
)
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
    finalize_housing_execution,
    replay_housing_receipt,
)


def _install_multileaf_scorer(
    setup,
    *,
    diagnostic_valid: bool,
    diagnostic_is_admission: bool,
) -> None:
    plugin = setup.registry.resolve_manifest(setup.plan.families[0])
    original_builder = plugin.build_scorer

    def build_scorer(case):
        original_scorer = original_builder(case)

        def score(outcome, *, evidence_refs=()):
            primary = original_scorer(outcome, evidence_refs=evidence_refs)
            estimand = dataclasses.replace(
                primary.leaf.estimand,
                estimand_id="housing_secondary_welfare",
            )
            objective_scope = dataclasses.replace(
                primary.leaf.verifier.objective_scope,
                objective_id=estimand.estimand_id,
            )
            verifier = dataclasses.replace(
                primary.leaf.verifier,
                objective_scope=objective_scope,
            )
            diagnostic_leaf = dataclasses.replace(
                primary.leaf,
                leaf_id="housing_secondary_welfare_leaf",
                estimand=estimand,
                verifier=verifier,
            )
            if diagnostic_valid:
                diagnostic = dataclasses.replace(
                    primary,
                    leaf=diagnostic_leaf,
                    primary=MetricValue(
                        primary.primary.value,
                        primary.primary.unit,
                        {"test_fixture": True},
                    ),
                )
            else:
                diagnostic = ScoreEnvelope(
                    status="invalid_measurement",
                    leaf=diagnostic_leaf,
                    primary=None,
                    metrics={},
                    reference_values={},
                    validity=ValidityReport(
                        "invalid", ("secondary measurement unavailable",)
                    ),
                    evidence_refs=tuple(evidence_refs),
                )
            admission_leaf_ids = (primary.leaf.leaf_id,)
            if diagnostic_is_admission:
                admission_leaf_ids += (diagnostic_leaf.leaf_id,)
            return FamilyScoreSet(
                primary_leaf_id=primary.leaf.leaf_id,
                scores=(diagnostic, primary),
                admission_leaf_ids=admission_leaf_ids,
            )

        return score

    plugin.build_scorer = build_scorer


@pytest.mark.parametrize(
    (
        "diagnostic_valid",
        "diagnostic_is_admission",
        "expected_status",
        "expected_inclusion",
    ),
    (
        (True, True, "ok", "included"),
        (False, False, "ok", "included"),
        (False, True, "invalid_measurement", "excluded"),
    ),
)
def test_family_finalizer_seals_and_replays_explicit_multileaf_admission(
    tmp_path,
    diagnostic_valid: bool,
    diagnostic_is_admission: bool,
    expected_status: str,
    expected_inclusion: str,
) -> None:
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    _install_multileaf_scorer(
        setup,
        diagnostic_valid=diagnostic_valid,
        diagnostic_is_admission=diagnostic_is_admission,
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )

    receipt = finalize_housing_execution(setup=setup, execution=execution)

    verify_evaluation_receipt(receipt)
    assert receipt.status == expected_status
    assert receipt.inclusion_status == expected_inclusion
    assert len(receipt.scores) == 2
    assert receipt.scores[0].leaf.leaf_id == receipt.primary_leaf_id
    assert receipt.scores[1].status == (
        "ok" if diagnostic_valid else "invalid_measurement"
    )
    assert (receipt.failure is None) == (expected_status == "ok")

    score_event = next(
        event
        for event in execution.evidence.read_events()
        if event.event_type == "score_recorded"
    )
    score_payload = execution.evidence.read_event_payload(score_event)
    assert "scores" in score_payload
    assert "score" not in score_payload

    replayed = replay_housing_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=tmp_path,
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)

    audited = audit_family_receipt(
        setup=setup,
        receipt_path=execution.evidence.root / "evaluation_receipt.json",
    )
    assert audited["receipt_sha256"] == receipt.receipt_sha256


def test_audit_and_replay_tolerate_kernel_pin_drift_but_not_family_drift(tmp_path) -> None:
    from aeread.shared_runner.run.resolver import plan_with_pins
    from aeread.shared_runner.task.evaluation import receipt_implementation_drift

    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    receipt_path = execution.evidence.root / "evaluation_receipt.json"

    def current(target, **changes):
        pins = tuple(
            dataclasses.replace(pin, **changes) if pin == target else pin
            for pin in setup.plan.implementation_pins
        )
        return dataclasses.replace(setup, plan=plan_with_pins(setup.plan, pins))

    harness = next(pin for pin in setup.plan.implementation_pins if pin.kind == "harness")
    kernel_moved = current(harness, sha256="a" * 64)
    assert kernel_moved.plan.run_plan_id != setup.plan.run_plan_id

    audited = audit_family_receipt(setup=kernel_moved, receipt_path=receipt_path)
    assert audited["receipt_sha256"] == receipt.receipt_sha256
    assert receipt_implementation_drift(kernel_moved.plan, audited) == (
        f"implementation_drift:{harness.component_id}",
    )
    assert receipt_implementation_drift(setup.plan, audited) == ()
    replayed = replay_housing_receipt(
        setup=kernel_moved, receipt=receipt, evidence_root=tmp_path
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)

    scorer = next(pin for pin in setup.plan.implementation_pins if pin.kind == "scorer")
    family_moved = current(scorer, sha256="b" * 64)
    with pytest.raises(ValueError, match="plan_implementation_pins"):
        audit_family_receipt(setup=family_moved, receipt_path=receipt_path)
    with pytest.raises(ValueError, match="does not belong"):
        replay_housing_receipt(setup=family_moved, receipt=receipt, evidence_root=tmp_path)
