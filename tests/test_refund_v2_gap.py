"""The Refund V2.1 gap analysis: one part per unresolved cell, judged against the answer key."""

from __future__ import annotations

import collections
import csv
import json

import pytest

from aeread_families.refund import v2_gap as gap


def _step(i, phase, seat, action, valid=True, code=None):
    return {"step_index": i, "phase_id": phase, "seat_id": seat, "action": action,
            "outcome": {"valid": valid, "failure_code": code, "status": "succeeded" if valid else "agent_action_failure"}}


def _opening(case_id="refund_v2.1n.missing_evidence.000003"):
    return [
        _step(0, "customer_message", "customer", {"decision": "state_request", "reveal_fields": []}),
        _step(1, "intake_request", "intake", {"decision": "request_facts", "requested_fields": ["condition", "issue_type", "evidence_provided"]}),
        _step(2, "customer_facts", "customer", {"decision": "provide_info", "reveal_fields": ["condition", "issue_type", "evidence_provided"]}),
    ]


def _result(case_id, policy="0.0", transaction="1.0"):
    return {"case_id": case_id, "policy_compliance": policy, "transaction_correctness": transaction}


def test_a_premature_denial_the_key_agrees_with_is_procedure_not_outcome() -> None:
    case = "refund_v2.1n.missing_evidence.000003"
    steps = _opening() + [_step(3, "policy_response", "policy", {"decision": "deny", "amount": 0, "method": None},
                                valid=False, code="decision_before_required_facts")]
    out = gap.analyse_cell(_result(case), steps, ("missing_proposal", "invalid_fact_request", "required_facts_missing"))
    assert out["component"] == "decided_before_required_facts" and out["parts"]["decided_before_required_facts"] == -100.0
    assert out["classes"] == ["right_outcome_skipped_procedure"] and out["right_outcome"]
    assert out["at"] == {"step_index": 3, "phase_id": "policy_response", "seat_id": "policy"}
    assert "return_received" in out["note"]


def test_a_repeated_fact_request_ends_the_case_without_a_decision() -> None:
    case = "refund_v2.1n.full_refund.000001"
    steps = _opening() + [_step(3, "policy_response", "policy", {"decision": "request_facts", "requested_fields": ["condition"]},
                                valid=False, code="repeated_fact")]
    out = gap.analyse_cell(_result(case), steps, ("missing_proposal", "invalid_fact_request"))
    assert out["component"] == "re_requested_known_fact" and out["classes"] == ["no_decision_reached"] and not out["right_outcome"]


def test_a_correct_denial_with_method_null_is_format_and_a_wrong_denial_is_outcome() -> None:
    deny = lambda method: _opening() + [
        _step(3, "policy_response", "policy", {"decision": "request_facts", "requested_fields": ["return_received"]}),
        _step(4, "customer_facts", "customer", {"decision": "provide_info", "reveal_fields": ["return_received"]}),
        _step(5, "policy_response", "policy", {"decision": "deny", "amount": 0, "method": method})]
    fmt = gap.analyse_cell(_result("refund_v2.1n.conflicting_claim.000002"), deny(None), ("policy_terms_mismatch",))
    assert fmt["component"] == "denial_method_null" and fmt["right_outcome"] and fmt["at"]["step_index"] == 5
    wrong = gap.analyse_cell(_result("refund_v2.1n.full_refund.000002", transaction="0.0"), deny(None),
                             ("transaction_not_exactly_once", "policy_terms_mismatch"))
    assert wrong["component"] == "wrong_decision" and wrong["classes"] == ["wrong_outcome"]


def test_a_rejected_step_without_the_published_reason_is_refused() -> None:
    steps = _opening() + [_step(3, "policy_response", "policy", {"decision": "deny"}, valid=False, code="decision_before_required_facts")]
    with pytest.raises(ValueError):
        gap.analyse_cell(_result("refund_v2.1n.missing_evidence.000003"), steps, ())


@pytest.mark.parametrize("label,bundle", gap.MODELS)
def test_published_parts_sum_to_the_published_pass_rate_and_name_real_steps(label: str, bundle: str) -> None:
    report = json.loads((gap.OUT / "reports" / f"gap_decomposition_{label}.json").read_text())
    with (gap.EVIDENCE / bundle / "tables" / "refund_results_by_scenario.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    resolved = 100.0 * sum(r["policy_compliance"] == "1.0" and r["transaction_correctness"] == "1.0" for r in rows) / len(rows)
    assert report["realized"]["difference"] == pytest.approx(resolved - 100.0)  # six cases x 20 cells: case mean = cell mean
    assert sum(c["difference"] for c in report["components"]) == pytest.approx(report["realized"]["difference"])
    table = [json.loads(line) for line in (gap.OUT / report["contributions"]["table"]).read_text().splitlines()]
    assert len(table) == sum(1 for r in rows if not (r["policy_compliance"] == "1.0" and r["transaction_correctness"] == "1.0"))
    steps = collections.defaultdict(dict)
    for line in (gap.EVIDENCE / bundle / "trajectories" / "sanitized.jsonl").read_text().splitlines():
        s = json.loads(line)
        steps[s["source_receipt_sha256"]][s["step_index"]] = (s["phase_id"], s["seat_id"])
    for row in table:
        assert steps[row["receipt_sha256"]][row["step_index"]] == (row["phase_id"], row["seat_id"])
