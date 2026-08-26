from __future__ import annotations

import asyncio

from aeread.shared_runner.execution import execute_plan_cell
from aeread.shared_runner.housing import (
    HOUSING_COMMIT_OUTPUT_SCHEMA,
    HOUSING_CONTACT_OUTPUT_SCHEMA,
    HOUSING_RESPOND_OUTPUT_SCHEMA,
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    HousingV1Plugin,
    build_housing_smoke,
)
from aeread.shared_runner.resolver import canonical_json_bytes


DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPSEEK_REVISION = "deepseek/deepseek-v4-flash-20260731"


def _case_payload() -> dict:
    return {
        "world_kind": "bid",
        "world_seed": 41001,
        "num_tenants": 2,
        "num_listings": 1,
        "rounds": 1,
        "common_weight": 0.6,
    }


def test_housing_plugin_observations_preserve_private_types() -> None:
    plugin = HousingV1Plugin()
    family_case = plugin.validate_payload(_case_payload())
    state = plugin.initial_state(family_case, run=None)
    phase_by_id = {phase.phase_id: phase for phase in plugin.phases(family_case)}

    tenant = plugin.observe(
        family_case, state, "tenant_0", phase_by_id["contact"]
    )
    assert tenant["private_values"] == family_case["world"].values[0]
    assert "costs" not in tenant
    assert "all_values" not in tenant

    landlord = plugin.observe(
        family_case, state, "landlord_0", phase_by_id["respond"]
    )
    assert landlord["private_cost"] == family_case["world"].costs[0]
    assert "values" not in landlord
    assert "all_values" not in landlord


def test_housing_smoke_seals_phase_schemas_bounds_and_controlled_landlords() -> None:
    setup = build_housing_smoke(
        tenant_provider="openrouter",
        tenant_model=DEEPSEEK_MODEL,
        tenant_revision=DEEPSEEK_REVISION,
    )

    assert len(setup.plan.cases) == 1
    case = setup.plan.cases[0]
    assert [(seat.id, seat.role) for seat in case.seats] == [
        ("tenant_0", "tenant"),
        ("tenant_1", "tenant"),
        ("landlord_0", "landlord"),
    ]
    assert case.episode.max_logical_actions == 5

    family = setup.plan.families[0]
    assert family.family.id == "housing_v1"
    assert family.measurement.optimum_lower_bound == "housing_feasible_zero_v1"
    assert family.measurement.comparison_baseline == "housing_adaptive_v1"
    assert family.measurement.optimum_upper_bound == "housing_exact_assignment_v1"
    assert family.measurement.optimum_upper_bound_kind == "full_information_relaxation"

    profiles = {profile.profile_id: profile for profile in setup.plan.agent_profiles}
    tenant = profiles["housing_deepseek_tenant_v1"]
    assert tenant.model.provider == "openrouter"
    assert tenant.model.revision == DEEPSEEK_REVISION
    assert tenant.retry_policy.max_action_attempts == 2
    assert tenant.retry_policy.retryable_conditions == ("length",)
    assert canonical_json_bytes(
        tenant.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(
        {
            "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA,
            "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA,
        }
    )
    assert tenant.harness.config["provider_metadata"]["route_provider"] == "DeepInfra"

    landlord = profiles["housing_scripted_landlord_v1"]
    assert landlord.model.provider == "housing_scripted_landlord"
    assert canonical_json_bytes(
        landlord.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(
        {"housing_respond_v1": HOUSING_RESPOND_OUTPUT_SCHEMA}
    )
    assert setup.plan.cells[0].profile_by_seat == {
        "tenant_0": "housing_deepseek_tenant_v1",
        "tenant_1": "housing_deepseek_tenant_v1",
        "landlord_0": "housing_scripted_landlord_v1",
    }


def test_provider_free_housing_cell_executes_all_three_phases_and_exact_bounds(
    tmp_path,
) -> None:
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

    result = execution.episode_result
    assert [phase.phase_id for phase in result.phase_instances] == [
        "contact",
        "respond",
        "commit",
    ]
    assert result.logical_action_count == 5
    assert result.outcome["valid"] is True
    assert result.outcome["feasible_floor"] == 0.0
    assert result.outcome["social_welfare"] <= result.outcome["oracle_total"] + 1e-9
    assert result.outcome["baseline_total"] <= result.outcome["oracle_total"] + 1e-9
    assert result.outcome["bound_semantics"] == "full_information_allocation_relaxation"
    assert len(result.outcome["assignment_pairs"]) == 1
    assert execution.total_cost_usd == 0.0
    execution.evidence.audit_reconciliation()
