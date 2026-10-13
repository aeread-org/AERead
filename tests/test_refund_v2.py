import json
import asyncio
from pathlib import Path

import pytest

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
from aeread_families.refund.v2_runner import RefundV21Plugin, build_refund_v21_run
from aeread_families.refund.v2_publication import publish_refund_v21
from aeread_families.refund.v2_2_environment import (
    build_n1_batch,
    build_n1_panel,
    run_scripted_n1,
    verify_n1_trajectory,
    derive_priority,
)
from aeread_families.refund.v2_2_experiment import run as run_v22_conformance
from aeread_families.refund.v2_2_runner import build_refund_v22_run, run as run_v22_runner
from aeread.shared_runner.task.execution import EvidenceStore


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
    assert report["completed_cases"] == 6
    run_plan = next(tmp_path.glob("runplan_*/run_plan.json"))
    assert run_plan.exists()
    receipts = list(tmp_path.glob("runplan_*/tasks/*/attempts/*/evaluation_receipt.json"))
    assert len(receipts) == 6
    audited = EvidenceStore.audit_existing(receipts[0].parent)
    audited.close()


def test_v21_plan_declares_all_shared_runner_seats() -> None:
    setup = build_refund_v21_run(world_seeds=(1,))
    assert len(setup.plan.cells) == 6
    assert set(setup.plan.cells[0].profile_by_seat) == {
        "customer",
        "intake",
        "policy",
        "payments",
    }
    block = setup.plan.evaluation_blocks[0]
    assert block.kind == "controlled"
    assert block.subject_seats == ("policy",)
    assert set(block.controlled_profiles) == {"customer", "intake", "payments"}


def test_v21_fixed_seed_panel_has_six_cells_per_seed() -> None:
    seeds = (0, 9, 17, 24, 27, 1, 4, 8, 15, 20, 2, 10, 14, 19, 28, 5, 7, 13, 16, 23)
    setup = build_refund_v21_run(world_seeds=seeds)
    assert len(setup.plan.cells) == 120
    assert {cell.world_seed for cell in setup.plan.cells} == set(seeds)


def test_v21_self_play_is_explicit() -> None:
    setup = build_refund_v21_run(
        world_seeds=(1,),
        active_agents=("customer", "intake", "policy"),
        evaluation_kind="self_play",
    )

    block = setup.plan.evaluation_blocks[0]
    assert block.kind == "self_play"
    assert block.controlled_profiles == {}


def test_v21_policy_observation_does_not_expose_authorized_resolution() -> None:
    setup = build_refund_v21_run(world_seeds=(1,))
    plugin = RefundV21Plugin()
    case = build_1n_case(1, scenario="full_refund")
    observation = plugin.observe(case, plugin.initial_state(case, None), "policy", plugin.phases(case)[3])
    assert "authorized_resolution" not in observation
    assert "scenario" not in observation
    assert "case_id" not in observation


def test_v21_publication_is_reproducible(tmp_path) -> None:
    report = run_v21_experiment((9,), tmp_path / "run")
    publication = tmp_path / "publication"
    result = publish_refund_v21(run_root=tmp_path / "run", publication_root=publication)
    assert result["receipt_count"] == report["completed_cases"]
    assert (publication / "receipts" / "projections.jsonl").exists()
    assert (publication / "tables" / "benchmark_results.csv").exists()
    assert (publication / "tables" / "refund_results_by_scenario.csv").exists()
    assert (publication / "reports" / "summary.json").exists()
    assert (publication / "reports" / "qualification.json").exists()
    assert (publication / "README.md").exists()
    assert (publication / "trajectories" / "sanitized.jsonl").exists()
    assert (publication / "publication_manifest.json").exists()
    assert not (publication / "trajectories" / "archive.jsonl").exists()
    repeated = publish_refund_v21(run_root=tmp_path / "run", publication_root=publication)
    assert repeated["manifest_sha256"] == result["manifest_sha256"]


def test_v21_publication_rejects_a_shared_analysis_and_publication_directory(tmp_path) -> None:
    run_v21_experiment((9,), tmp_path / "run")
    shared = tmp_path / "shared"
    with pytest.raises(ValueError, match="separate directories"):
        publish_refund_v21(
            run_root=tmp_path / "run",
            analysis_root=shared,
            publication_root=shared,
        )


def test_v22_n1_batch_has_shared_budget_and_three_customers() -> None:
    cases = build_n1_batch(11)

    assert len(cases) == 3
    assert {case.customer_id for case in cases} == {"customer_1", "customer_2", "customer_3"}
    assert sum(case.authorized_refund_amount for case in cases if case.eligible) > 120.0


def test_v22_panel_varies_budget_and_priorities_across_worlds() -> None:
    first = build_n1_panel(0)
    second = build_n1_panel(1)

    assert first.content_sha256 != second.content_sha256
    assert first.refund_budget != second.refund_budget
    assert [case.priority for case in first.cases] != [case.priority for case in second.cases]


def test_v22_priority_is_derived_from_declared_basis() -> None:
    panel = build_n1_panel(5)
    assert [case.priority_basis for case in panel.cases] == ["critical", "standard", "elevated"]
    assert [case.priority for case in panel.cases] == [derive_priority(case.priority_basis) for case in panel.cases]


def test_v22_scripted_n1_allocates_shared_budget_once() -> None:
    cases = build_n1_batch(12)
    state, outcome = run_scripted_n1(cases)

    assert outcome.policy_compliant is True
    assert outcome.allocation_score == 1.0
    assert outcome.transaction_score == 1.0
    assert len(state.transactions) == 1
    assert state.transactions[0]["customer_id"] == "customer_2"
    assert state.budget_remaining == 30.0


def test_v22_verifier_rejects_a_feasible_but_lower_priority_allocation() -> None:
    batch = build_n1_panel(0)
    state, _ = run_scripted_n1(batch)
    # The apparel refund is feasible on its own, but the declared objective
    # prioritizes the software claim in this world.
    apparel, software, _ = batch.cases
    state.decisions[apparel.case_id] = {
        "decision": "approve", "amount": apparel.authorized_refund_amount,
        "method": apparel.authorized_refund_method,
    }
    state.decisions[software.case_id] = {
        "decision": "deny_or_defer", "amount": 0.0, "method": "none",
    }
    state.transactions = [{
        "customer_id": apparel.customer_id, "case_id": apparel.case_id,
        "amount": apparel.authorized_refund_amount,
        "method": apparel.authorized_refund_method,
    }]
    state.budget_remaining = batch.refund_budget - apparel.authorized_refund_amount

    outcome = verify_n1_trajectory(batch, state)

    assert outcome.transaction_score == 1.0
    assert outcome.allocation_score == 0.0
    assert outcome.policy_compliant is False
    assert "allocation_policy_mismatch" in outcome.verifier_reasons


def test_v22_customer_information_is_revealed_in_two_requests() -> None:
    state, _ = run_scripted_n1(build_n1_batch(13))

    for case in build_n1_batch(13):
        messages = [
            message for message in state.transcript
            if message["speaker"] == "customer" and message["customer_id"] == case.customer_id
        ]
        assert messages[0]["revealed_fields"] == []
        assert messages[1]["revealed_fields"] == ["condition", "issue_type", "evidence_provided"]
        assert messages[2]["revealed_fields"] == ["return_received"]


def test_v22_conformance_experiment_writes_batch_summary(tmp_path) -> None:
    summary = run_v22_conformance(world_seeds=(0, 1), output=tmp_path)

    assert summary["topology"] == "N:1"
    assert summary["planned_batches"] == 2
    assert summary["planned_customer_cases"] == 6
    assert summary["metrics"]["allocation"] == 1.0
    assert (tmp_path / "refund_v2_2_conformance_summary.json").exists()


def test_v22_shared_runner_seals_a_controlled_policy_batch(tmp_path) -> None:
    setup = build_refund_v22_run(world_seeds=(0,))
    assert set(setup.plan.cells[0].profile_by_seat) == {
        "policy", "customer_1", "customer_2", "customer_3", "payments",
    }
    report = asyncio.run(run_v22_runner(output=tmp_path, world_seeds=(0,)))
    assert report["completed_batches"] == 1
    assert report["receipts"][0]["inclusion_status"] == "included"
    assert (tmp_path / f"{report['run_plan_id']}" / "run_plan.json").exists()


def test_committed_refund_kernel_trajectory_grains_use_terminal_action_statuses() -> None:
    allowed_statuses = {
        "succeeded",
        "failed",
        "outcome_unknown",
        "agent_action_failure",
    }
    trajectory_files = sorted(
        (REPOSITORY_ROOT / "evidence" / "refund").glob("*/trajectories/*.jsonl")
    )

    assert trajectory_files
    for trajectory_file in trajectory_files:
        for line_number, line in enumerate(trajectory_file.read_text(encoding="utf-8").splitlines(), 1):
            row = json.loads(line)
            if row.get("schema_version") != "aeread.sanitized_trajectory_row/0.1":
                continue
            assert row["outcome"]["status"] in allowed_statuses, (
                f"{trajectory_file}:{line_number} uses a non-terminal action status"
            )
