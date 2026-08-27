"""Typed RFQ scoring must reject invented bounds without discarding legal losses."""
import dataclasses

import pytest

from aeread import procurement_rfq_env as rfq
from aeread.shared_runner.procurement_measurement import (
    procurement_measurement_leaf,
    procurement_score_support,
    score_procurement_outcome,
)
from aeread.shared_runner.procurement_rfq import ProcurementRFQPlugin, build_procurement_rfq_smoke


def _case_and_outcome():
    setup = build_procurement_rfq_smoke()
    case = ProcurementRFQPlugin().validate_payload(setup.plan.cases[0].payload)
    baseline = rfq.run_scripted_rfq_baseline(
        case["world"], max_contacts=case["max_contacts"], contact_cost=case["contact_cost"],
        disclosure_anchor=case["disclosure_anchor"],
    )
    return case, {
        **dataclasses.asdict(baseline), "valid": True,
        "baseline_total": baseline.buyer_surplus,
        "oracle_total": baseline.buyer_surplus_upper_bound,
        "within_case_score": baseline.buyer_surplus_score,
        "bound_semantics": "full_information_terms_relaxation",
    }


def test_procurement_has_typed_objective_reference_and_native_currency():
    case, outcome = _case_and_outcome()
    leaf = procurement_measurement_leaf(case)
    assert leaf.estimand.estimand_id == "buyer_surplus"
    assert leaf.verifier.verifier_family == "objective_reference"
    assert leaf.verifier.reference.reference_kind == "objective_upper_bound"
    score = score_procurement_outcome(case, outcome, evidence_refs=("event_0001",))
    assert score.status == "ok"
    assert score.primary.value == pytest.approx(728.6)
    assert score.primary.unit == "synthetic_currency"
    assert score.reference_values["optimum_upper_bound"].value == pytest.approx(796.0)
    assert score.metrics["comparison_baseline_gap"].value == pytest.approx(0.0)
    assert score.evidence_refs == ("event_0001",)


@pytest.mark.parametrize("field,value", [
    ("oracle_total", 900.0), ("buyer_surplus_upper_bound", 900.0),
    ("baseline_total", 999.0), ("buyer_surplus", 1e6),
    ("supplier_margin", -100.0), ("contact_cost_total", 0.0),
    ("within_case_score", float("nan")), ("buyer_surplus_score", 1.0),
    ("approval_granted", False), ("disclosed_rfq_count", 99),
    ("contacted_supplier_ids", [2, 2]),
])
def test_procurement_scorer_rejects_inconsistent_economics_or_reference(field, value):
    case, outcome = _case_and_outcome()
    score = score_procurement_outcome(case, {**outcome, field: value})
    assert score.status == "invalid_measurement"
    assert score.primary is None
    assert score.validity.reasons


def test_procurement_preserves_legal_negative_contact_cost_outcome():
    case, outcome = _case_and_outcome()
    loss = {**outcome, "executed": False, "approval_granted": False,
            "spend": 0.0, "production_cost": 0.0, "supplier_margin": 0.0,
            "contacted_supplier_ids": [2], "contact_cost_total": 5.0,
            "buyer_surplus": -5.0, "social_welfare": -5.0,
            "within_case_score": -5.0 / 796.0, "buyer_surplus_score": -5.0 / 796.0}
    score = score_procurement_outcome(case, loss)
    assert score.status == "ok"
    assert score.primary.value == -5.0
    assert score.metrics["within_case_score"].value < 0
    lower, upper = procurement_score_support(case)
    assert lower == pytest.approx(-25.0 / 796.0)
    assert upper == 1.0
