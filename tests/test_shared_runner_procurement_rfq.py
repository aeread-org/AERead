"""Shared-runner conformance tests for the native procurement RFQ family."""
from __future__ import annotations

import asyncio

from aeread.shared_runner.execution import execute_plan_cell
from aeread.shared_runner.procurement_rfq import (
    PROCUREMENT_APPROVAL_OUTPUT_SCHEMA,
    PROCUREMENT_AWARD_OUTPUT_SCHEMA,
    PROCUREMENT_COUNTER_OUTPUT_SCHEMA,
    PROCUREMENT_NEGOTIATE_OUTPUT_SCHEMA,
    PROCUREMENT_QUOTE_OUTPUT_SCHEMA,
    PROCUREMENT_RFQ_OUTPUT_SCHEMA,
    ProcurementRFQPlugin,
    ProcurementScriptedBuyerProvider,
    ProcurementScriptedSupplierProvider,
    build_procurement_rfq_smoke,
)
from aeread.shared_runner.resolver import canonical_json_bytes


DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPSEEK_REVISION = "deepseek/deepseek-v4-flash-20260731"


def test_procurement_plugin_declares_real_workflow_and_private_observations() -> None:
    setup = build_procurement_rfq_smoke()
    plugin = ProcurementRFQPlugin()
    case = setup.plan.cases[0]
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phases = plugin.phases(family_case)

    assert [phase.phase_id for phase in phases] == [
        "rfq",
        "quote",
        "negotiate",
        "counter",
        "approval",
        "award",
    ]
    buyer = plugin.observe(family_case, state, "buyer_0", phases[0])
    assert "unit_cost" not in str(buyer)
    assert buyer["mandate"]["budget"] == 2400.0
    assert buyer["mandate"]["max_contacts"] == 5


def test_procurement_smoke_seals_roles_schemas_and_typed_references() -> None:
    setup = build_procurement_rfq_smoke()
    plan = setup.plan
    case = plan.cases[0]

    assert [(seat.id, seat.role) for seat in case.seats] == [
        ("buyer_0", "buyer"),
        *[(f"supplier_{seller_id}", "supplier") for seller_id in range(2, 9)],
    ]
    assert case.episode.max_logical_actions == 14

    family = plan.families[0]
    assert family.family.id == "procurement_rfq_v1"
    assert family.measurement.primary_estimand == "buyer_surplus"
    assert family.measurement.optimum_lower_bound == "procurement_rfq_no_action_v1"
    assert family.measurement.comparison_baseline == "procurement_rfq_visible_baseline_v1"
    assert family.measurement.optimum_upper_bound == "procurement_rfq_full_info_terms_v1"
    assert family.measurement.optimum_upper_bound_kind == "full_information_relaxation"

    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    buyer = profiles["procurement_scripted_buyer_v1"]
    assert canonical_json_bytes(
        buyer.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(
        {
            "procurement_rfq_v1": PROCUREMENT_RFQ_OUTPUT_SCHEMA,
            "procurement_negotiate_v1": PROCUREMENT_NEGOTIATE_OUTPUT_SCHEMA,
            "procurement_approval_v1": PROCUREMENT_APPROVAL_OUTPUT_SCHEMA,
            "procurement_award_v1": PROCUREMENT_AWARD_OUTPUT_SCHEMA,
        }
    )
    supplier = profiles["procurement_scripted_supplier_v1"]
    assert canonical_json_bytes(
        supplier.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(
        {
            "procurement_quote_v1": PROCUREMENT_QUOTE_OUTPUT_SCHEMA,
            "procurement_counter_v1": PROCUREMENT_COUNTER_OUTPUT_SCHEMA,
        }
    )


def test_procurement_live_probe_seals_openrouter_buyer_and_controlled_suppliers() -> None:
    setup = build_procurement_rfq_smoke(
        buyer_provider="openrouter",
        buyer_model=DEEPSEEK_MODEL,
        buyer_revision=DEEPSEEK_REVISION,
    )

    profiles = {profile.profile_id: profile for profile in setup.plan.agent_profiles}
    buyer = profiles["procurement_deepseek_buyer_v1"]
    assert buyer.model.provider == "openrouter"
    assert buyer.model.model == DEEPSEEK_MODEL
    assert buyer.model.revision == DEEPSEEK_REVISION
    assert buyer.model.base_url == "https://openrouter.ai/api/v1"
    assert buyer.retry_policy.max_action_attempts == 2
    assert buyer.retry_policy.retryable_conditions == ("length",)
    assert buyer.harness.config["provider_metadata"]["route_provider"] == "DeepInfra"
    assert buyer.budgets.max_cost_usd == 0.01
    assert buyer.budgets.timeout_seconds == 90.0

    supplier = profiles["procurement_scripted_supplier_v1"]
    assert supplier.model.provider == "procurement_scripted_supplier"
    assert setup.plan.cells[0].profile_by_seat == {
        "buyer_0": "procurement_deepseek_buyer_v1",
        **{
            f"supplier_{seller_id}": "procurement_scripted_supplier_v1"
            for seller_id in range(2, 9)
        },
    }
    assert set(setup.pricing) == {DEEPSEEK_MODEL, "procurement_scripted_supplier_v1"}


def test_provider_free_procurement_cell_executes_and_reconciles_evidence(tmp_path) -> None:
    setup = build_procurement_rfq_smoke()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "procurement_scripted_buyer": ProcurementScriptedBuyerProvider(),
                "procurement_scripted_supplier": ProcurementScriptedSupplierProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )

    result = execution.episode_result
    assert [phase.phase_id for phase in result.phase_instances] == [
        "rfq",
        "quote",
        "negotiate",
        "counter",
        "approval",
        "award",
    ]
    assert result.logical_action_count == 14
    assert result.outcome["valid"] is True
    assert result.outcome["executed"] is True
    assert result.outcome["approval_granted"] is True
    assert result.outcome["buyer_surplus"] == result.outcome["baseline_total"]
    assert 0.0 < result.outcome["buyer_surplus"] < result.outcome["oracle_total"]
    assert result.outcome["disclosed_rfq_count"] == 0
    assert result.outcome["bound_semantics"] == "full_information_terms_relaxation"
    assert execution.total_cost_usd == 0.0
    execution.evidence.audit_reconciliation()
