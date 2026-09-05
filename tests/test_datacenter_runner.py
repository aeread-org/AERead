from __future__ import annotations

import asyncio

from aeread_families.datacenter_development.environment import (
    SERVICE_DEVELOPER_OFFER,
    DataCenterDevelopmentPlugin,
)
from aeread_families.datacenter_development.runner import (
    build_offline_setup,
    finalize_datacenter_execution,
    load_case,
    replay_datacenter_receipt,
    run_offline,
)


def test_case_is_hash_pinned_and_baseline_recomputes() -> None:
    case = load_case()
    validated = DataCenterDevelopmentPlugin().validate_payload(case.payload)

    assert case.family_id == "datacenter_development_v1"
    assert validated["baseline"] == {
        "developer_equity_npv_cents": -20_000,
        "lender_npv_cents": 0,
        "customer_npv_cents": 200_000,
        "total_project_npv_cents": 180_000,
    }


def test_developer_observation_excludes_counterparty_private_grounding() -> None:
    case = load_case()
    plugin = DataCenterDevelopmentPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = next(
        item
        for item in plugin.phases(family_case)
        if item.phase_id == SERVICE_DEVELOPER_OFFER
    )

    observation = plugin.observe(family_case, state, "developer", phase)
    serialized = repr(observation)

    assert "private_policy" not in serialized
    assert "customer_policy" not in serialized
    assert "lender_policy" not in serialized
    assert "scripted_developer" not in serialized
    assert "baseline" not in serialized
    assert "outside_option" not in serialized
    assert "customer_usage_kw_by_month" not in serialized
    assert "customer_value_cents_per_kw_month" not in serialized


def test_six_phase_run_seals_five_leaves_and_replays(tmp_path) -> None:
    setup, execution = asyncio.run(run_offline(evidence_root=tmp_path))

    assert execution.episode_result.logical_action_count == 6
    assert execution.total_cost_usd == 0.0
    assert execution.episode_result.outcome["project_completed"] is True
    assert execution.episode_result.outcome["binding_contract_integrity"] is True
    assert execution.episode_result.outcome["project_constraints_satisfied"] is True
    assert execution.episode_result.outcome["developer_equity_npv_cents"] == -20_000
    assert execution.episode_result.outcome["total_project_npv_cents"] == 180_000

    receipt = finalize_datacenter_execution(setup=setup, execution=execution)
    score_by_id = {item.leaf.leaf_id: item for item in receipt.scores}

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.primary_leaf_id == "developer_equity_npv"
    assert set(score_by_id) == {
        "developer_equity_npv",
        "binding_contract_integrity",
        "project_constraint_satisfaction",
        "negotiation_temporal_compliance",
        "total_project_npv",
    }
    assert score_by_id["binding_contract_integrity"].primary.value == 1.0
    assert score_by_id["project_constraint_satisfaction"].primary.value == 1.0
    assert score_by_id["negotiation_temporal_compliance"].primary.value == 1.0

    replayed = replay_datacenter_receipt(
        setup=setup, receipt=receipt, evidence_root=tmp_path
    )
    assert replayed == receipt


def test_offline_setup_resolves_controlled_counterparty_assignments() -> None:
    setup = build_offline_setup()
    cell = setup.plan.cells[0]

    assert cell.profile_by_seat == {
        "customer": "datacenter_scripted_customer_v1",
        "developer": "datacenter_scripted_developer_v1",
        "lender": "datacenter_scripted_lender_v1",
    }
