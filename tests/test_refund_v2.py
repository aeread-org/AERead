from aeread.refund_v2.environment import (
    build_1n_case,
    run_1n_with_policy_proposal,
    run_scripted_1n,
)


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
