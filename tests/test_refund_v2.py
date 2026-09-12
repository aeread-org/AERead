from aeread_families.refund.v2_environment import (
    AgentActivationConfig,
    build_1n_case,
    build_1n_panel,
    run_1n_with_policy_proposal,
    run_1n_with_role_actions,
    run_scripted_1n,
    validate_active_agents,
)
from aeread_families.refund.v2_experiment import run as run_v21_experiment
from aeread.shared_runner.task.execution import EvidenceStore


def test_1n_positive_path_requires_payments_agent_execution() -> None:
    state, outcome = run_scripted_1n(build_1n_case(1, positive=True))

    assert outcome.policy_compliant is True
    assert outcome.transaction_score == 1.0
    assert outcome.coordination_score == 1.0
    assert len(state.transactions) == 1
    assert state.transactions[0]["agent"] == "payments"


def test_1n_denial_path_has_no_transaction_mutation() -> None:
    state, outcome = run_scripted_1n(build_1n_case(2, positive=False))

    assert outcome.policy_compliant is True
    assert outcome.decision == "deny"
    assert outcome.transaction_score == 1.0
    assert state.transactions == []


def test_1n_case_hash_changes_with_world_seed() -> None:
    first = build_1n_case(1)
    second = build_1n_case(2)

    assert first.content_sha256 != second.content_sha256


def test_1n_incorrect_positive_terms_fail_transaction_verification() -> None:
    case = build_1n_case(3, positive=True)
    _, outcome = run_1n_with_policy_proposal(case, {
        "proposal_id": "proposal_bad",
        "decision": "approve_direct",
        "amount": case.authorized_refund_amount,
        "method": "store_credit",
        "reason": None,
    })

    assert outcome.policy_compliant is False
    assert outcome.transaction_score == 0.0
    assert "transaction_terms_mismatch" in outcome.verifier_reasons


def test_1n_denial_requires_explicit_none_method() -> None:
    case = build_1n_case(4, positive=False)
    _, outcome = run_1n_with_policy_proposal(case, {
        "proposal_id": "proposal_bad",
        "decision": "deny",
        "amount": 0.0,
        "method": None,
        "reason": case.denial_reason,
    })

    assert outcome.policy_compliant is False
    assert "policy_terms_mismatch" in outcome.verifier_reasons


def test_1n_scripted_customer_reveals_facts_in_bounded_turns() -> None:
    state, outcome = run_scripted_1n(build_1n_case(5, positive=True))

    customer_reveals = [
        message["revealed_fields"]
        for message in state.transcript
        if message["speaker"] == "customer"
    ]
    assert customer_reveals[0] == {}
    assert customer_reveals[1] == ["condition", "issue_type", "evidence_provided"]
    assert customer_reveals[2] == ["return_received"]
    assert outcome.policy_compliant is True


def test_1n_panel_covers_v21_scenarios_and_product_categories() -> None:
    panel = build_1n_panel(7)

    assert len(panel) == 6
    assert {case.scenario for case in panel} == {
        "full_refund",
        "liquid_damage_denial",
        "partial_software",
        "boundary_window",
        "conflicting_claim",
        "missing_evidence",
    }
    assert {case.product_category for case in panel} == {
        "apparel",
        "consumer_electronics",
        "software",
        "perishable_goods",
    }


def test_1n_scripted_partial_refund_executes_exact_amount() -> None:
    case = build_1n_panel(8)[2]
    state, outcome = run_scripted_1n(case)

    assert outcome.policy_compliant is True
    assert state.transactions == [{
        "agent": "payments",
        "proposal_id": "proposal_1",
        "amount": 90.0,
        "method": "original_payment",
    }]


def test_v21_active_seats_are_independently_selectable() -> None:
    assert validate_active_agents(("policy", "customer", "policy")) == ("policy", "customer")
    assert AgentActivationConfig(("intake", "customer", "policy")).active_agents == (
        "intake", "customer", "policy"
    )


def test_v21_customer_cannot_disclose_unrequested_facts() -> None:
    case = build_1n_case(10, positive=True)
    state, outcome = run_1n_with_role_actions(
        case,
        intake_action={"decision": "request_facts", "requested_fields": ["condition"]},
        initial_customer_action={"decision": "provide_info", "reveal_fields": ["condition", "issue_type"]},
        policy_turns=[{"decision": "deny", "amount": 0.0, "method": "none", "proposal_id": "proposal_bad"}],
        customer_actions=[],
    )

    assert "customer_disclosed_unrequested_fact" in state.invalid_fact_requests
    assert outcome.policy_compliant is False


def test_v21_experiment_writes_auditable_trajectory_evidence(tmp_path) -> None:
    report = run_v21_experiment((9,), tmp_path)

    assert report["planned_cases"] == 6
    assert (tmp_path / "evidence_manifest.json").exists()
    roots = sorted((tmp_path / "evidence" / "trajectories").iterdir())
    assert len(roots) == 6
    audited = EvidenceStore.audit_existing(roots[0])
    audited.close()
