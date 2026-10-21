"""Independent branch goldens, not generated from the public compiler."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from aeread_families.refund.v2_5_branches import BranchSpec, public_inputs, spec_for
from aeread_families.refund.v2_5_policy import build_unified_panel, policy_required_fact_ids, render_policy_contract, resolve_policy
from aeread_families.refund.v2_5_runner import RefundV25Plugin, _scripted_intake_batch

OPTIONS = dict(include_policy_stress_extension=True, include_policy_frontier_extension=True,
               include_policy_frontier_hard_extension=True, include_operational_extension=True)
PUBLIC = public_inputs(100, 8)


@pytest.mark.parametrize("scenario,facts,workflow,basis,amount", [
    ("seller_fault_unverified_evidence", {"defect_evidence": "verified"}, "execute_refund", "R_SELLER_FAULT_VERIFIED", 108),
    ("seller_fault_unverified_evidence", {"defect_evidence": "inconclusive"}, "request_evidence", "R_SELLER_FAULT_UNVERIFIED", 0),
    ("missing_parts_partial_refund", {"evidence_status": "verified", "component_role": "core"}, "execute_refund", "R_MISSING_CORE", 108),
    ("multiple_missing_components", {"evidence_status": "verified", "core_component_missing": True}, "execute_refund", "R_CORE_PRECEDENCE", 108),
    ("late_defect_identity_conflict", {"inspection_stage": "post_return_warehouse", "order_serial": "A", "inspection_serial": "B"}, "identity_review", "R_IDENTITY_PRECEDENCE", 0),
    ("returnless_refund_high_value_exception", {"defect_evidence": "verified", "identity_risk": "high"}, "return_and_inspect", "R_RETURNLESS_RISK_EXCEPTION", 0),
    ("frontier_hard_authority_flip", {"serial_registry": "mismatch"}, "identity_review", "R_IDENTITY_HOLD", 0),
    ("frontier_hard_authority_flip", {"serial_registry": "match", "customer_evidence": "unverified"}, "seller_review", "R_EVIDENCE_CONFLICT_REVIEW", 0),
    ("frontier_hard_window_override", {"seller_fault_event": "verified_wrong_item"}, "execute_refund", "R_SELLER_FAULT_OVERRIDE", 108),
    ("frontier_hard_window_override", {"seller_fault_event": "none", "return_reason": "buyer_remorse", "return_request_day": 31}, "no_mutation", "R_FINAL_SALE_EXCLUSION", 0),
    ("policy_evidence_inconclusive", {"customer_evidence": "unverified"}, "seller_review", "R_EVIDENCE_CONFLICT_REVIEW", 0),
    ("frontier_hard_piecewise_tax", {"evidence_status": "unverified"}, "request_evidence", "R_DEFECT_VERIFICATION", 0),
    ("frontier_hard_refund_reconciliation", {"defect_evidence": "unverified"}, "request_evidence", "R_DEFECT_VERIFICATION", 0),
    ("frontier_hard_refund_reconciliation", {"defect_evidence": "verified", "settled_refund_cents": 10800}, "payment_review", "R_PAYMENT_HOLD", 0),
    ("frontier_hard_refund_reconciliation", {"defect_evidence": "verified", "settled_refund_cents": 10000}, "execute_refund", "R_VERIFIED_DEFECT_REFUND", 8),
    ("frontier_hard_override_liability", {"inspection_cause": "buyer_caused"}, "seller_review", "R_POST_RETURN_LIABILITY", 0),
    ("frontier_hard_override_liability", {"inspection_cause": "carrier_damage", "seller_fault_event": "verified_wrong_item", "original_defect_evidence": "verified"}, "execute_refund", "R_SELLER_FAULT_OVERRIDE", 108),
])
def test_independent_terminal_goldens(scenario, facts, workflow, basis, amount):
    spec = spec_for(scenario)
    assert spec.pending(facts, PUBLIC) == ()
    out = spec.resolve(facts, PUBLIC)
    assert (out["workflow"], out["policy_basis"], out["reason_code"], out["amount"]) == (workflow, basis, basis, amount)
    assert out["payment_mutation"] == ("execute" if amount else "none")
    roundtrip = BranchSpec.from_dict(json.loads(json.dumps(spec.to_dict())))
    assert roundtrip.resolve(facts, PUBLIC) == out


@pytest.mark.parametrize("scenario,facts,required", [
    ("missing_parts_partial_refund", {"component_role": "core"}, {"evidence_status"}),
    ("missing_parts_partial_refund", {"evidence_status": "verified", "component_role": "non_core"}, {"component_catalog_value", "category_cap_rate"}),
    ("policy_identity_followup", {"inspection_stage": "post_return_warehouse", "order_serial": "A", "inspection_serial": "A"}, {"defect_evidence"}),
    ("policy_payment_hold_precedence", {"chargeback_state": "none"}, {"defect_evidence"}),
    ("frontier_hard_refund_reconciliation", {"defect_evidence": "verified"}, {"settled_refund_cents"}),
    ("frontier_hard_authority_flip", {"customer_evidence": "unverified"}, {"serial_registry"}),
    ("frontier_hard_window_override", {"category_final_sale": True}, {"seller_fault_event"}),
    ("returnless_refund_high_value_exception", {"defect_evidence": "verified", "identity_risk": "low"}, {"returnless_threshold"}),
])
def test_independent_unresolved_branch_goldens(scenario, facts, required):
    spec = spec_for(scenario)
    assert set(spec.pending(facts, PUBLIC)) == required
    with pytest.raises(ValueError, match="decisive evidence"):
        spec.resolve(facts, PUBLIC)


@pytest.mark.parametrize("threshold,workflow", [(99.99, "return_and_inspect"), (100, "execute_refund"), (100.01, "execute_refund")])
def test_threshold_boundary_single_public_meaning(threshold, workflow):
    facts = {"defect_evidence": "verified", "identity_risk": "low", "returnless_threshold": threshold}
    spec = spec_for("returnless_refund_high_value_exception")
    assert spec.resolve(facts, PUBLIC)["workflow"] == workflow
    base = next(c for c in build_unified_panel(1) if c.interaction.scenario == spec.scenario)
    case = replace(base, interaction=replace(base.interaction, item_net_price=100, allocated_tax=8, facts=facts))
    assert resolve_policy(case).workflow == workflow
    contract = render_policy_contract(case)
    assert "item_net_price < returnless_threshold" not in contract
    assert "item_net_price ≤ returnless_threshold" in contract


def test_terminal_route_forbids_additional_policy_fact_requests():
    case = next(c for c in build_unified_panel(1, **OPTIONS) if c.interaction.scenario == "frontier_hard_authority_flip")
    plugin = RefundV25Plugin()
    state = {**plugin.initial_state(case, None), "revealed_facts": {"serial_registry": "mismatch"}}
    phase = next(p for p in plugin.phases(case) if p.phase_id == "policy_turn")
    result = plugin.legal(case, state, "policy", phase,
                          {"action": "request_facts", "requested_fact_ids": ["order_serial"]})
    assert not result.legal
    assert result.reason == "policy_overcollection_after_terminal_route"


def test_all_fact_masks_never_read_hidden_values():
    cases = build_unified_panel(202, **OPTIONS)
    for case in cases:
        ids = spec_for(case.interaction.scenario).fact_ids()
        for mask in range(1 << len(ids)):
            visible = {f: case.facts[f] for i, f in enumerate(ids) if mask & (1 << i)}
            corrupt = replace(case, interaction=replace(case.interaction, facts={f: "HIDDEN_SENTINEL" for f in case.interaction.facts}))
            assert policy_required_fact_ids(case, visible) == policy_required_fact_ids(corrupt, visible)


def test_intake_plan_is_value_blind_and_no_oracle_values_exposed():
    for case in build_unified_panel(202, **OPTIONS):
        plugin = RefundV25Plugin()
        state = plugin.initial_state(case, None)
        phase = next(p for p in plugin.phases(case) if p.phase_id == "intake_request")
        observation = plugin.observe(case, state, "intake", phase)
        batch = _scripted_intake_batch(observation)
        assert batch and set(batch) <= set(case.facts)
        assert plugin._intake_priority_ok(case, batch)
        assert "initial_fact_order" not in observation["routing_plan"]
        assert "reference_resolution" not in observation and "revealed_facts" not in observation


@pytest.mark.parametrize("cap,value", [(0.01, 1), (0.5, 9999), (1, 100)])
def test_independent_missing_core_completion_invariance(cap, value):
    case = next(c for c in build_unified_panel(1) if c.interaction.scenario == "missing_parts_partial_refund")
    visible = dict(component_role="core", evidence_status="verified")
    facts = {**visible, "category_cap_rate": cap, "component_catalog_value": value}
    changed = replace(case, interaction=replace(case.interaction, facts=facts))
    assert policy_required_fact_ids(changed, visible) == ()
    assert resolve_policy(changed).remedy == "full_refund"
    assert resolve_policy(changed).amount == round(case.interaction.item_net_price + case.interaction.allocated_tax, 2)
