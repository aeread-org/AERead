from dataclasses import asdict

from aeread_families.refund.v2_4_cases import SCENARIOS, build_marketplace_v24_panel
from aeread_families.refund.v2_4_reference import resolve_policy
from aeread_families.refund.v2_4_scoring import score_proposal


def test_v24_has_twelve_scenarios_and_paired_variants():
    cases = build_marketplace_v24_panel(7)
    assert len(SCENARIOS) == 12
    assert len(cases) == 24
    for scenario in SCENARIOS:
        members = [case for case in cases if case.scenario == scenario]
        assert len(members) == 2
        assert members[0].pair_id == members[1].pair_id
        assert members[0].changed_fact_ids == members[1].changed_fact_ids
        changed = {key for key in set(members[0].facts) | set(members[1].facts) if members[0].facts.get(key) != members[1].facts.get(key)}
        assert changed == set(members[0].changed_fact_ids)


def test_v24_reference_resolves_every_case():
    for case in build_marketplace_v24_panel(7):
        outcome = resolve_policy(case)
        assert outcome.required_fact_ids
        assert set(outcome.required_fact_ids) <= set(case.facts)


def test_alias_is_contract_failure_not_policy_failure():
    case = next(case for case in build_marketplace_v24_panel(7) if case.variant == "core_component")
    expected = asdict(resolve_policy(case))
    proposal = {**expected, "remedy": "refund", "workflow": "refund", "payment_mutation": "refund", "reason_code": "different_label"}
    scored = score_proposal(case, proposal, revealed_fact_ids=expected["required_fact_ids"], transaction_count=1)
    assert scored.policy_semantic_score == 1.0
    assert scored.workflow_score == 1.0
    assert scored.payment_score == 1.0
    assert scored.contract_score == 0.0
    assert "contract_noncanonical_workflow" in scored.taxonomy


def test_true_policy_error_is_not_hidden_by_normalization():
    case = next(case for case in build_marketplace_v24_panel(7) if case.variant == "identity_conflict")
    expected = asdict(resolve_policy(case))
    proposal = {**expected, "eligibility": "eligible", "remedy": "full_refund", "workflow": "execute_refund", "amount": case.item_net_price + case.allocated_tax, "payment_mutation": "execute", "return_shipping_payer": "seller"}
    scored = score_proposal(case, proposal, revealed_fact_ids=expected["required_fact_ids"], transaction_count=1)
    assert scored.policy_semantic_score == 0.0
    assert "policy_eligibility_boundary_error" in scored.taxonomy
    assert "policy_remedy_selection_error" in scored.taxonomy
