"""Versioned price campaign, paired worlds, receipts and a bounded offline gate."""

import asyncio
import json

import pytest

from aeread_families.housing import price_campaign
from aeread_families.housing.runner import build_housing_smoke


def test_price_contract_and_plan_keep_arms_paired(tmp_path):
    contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT)
    setups = {arm: price_campaign.build_setup(contract, arm, live=True) for arm in contract["arms"]}
    for arm, setup in setups.items():
        assert {cell.world_seed for cell in setup.plan.cells} == set(contract["world_seeds"])
        assert len(setup.plan.cells) == 4
        assert all(case.payload["lemon_landlord"] == arm for case in setup.plan.cases)
        assert all(case.payload["landlord_policy"] == "housing_scripted_landlord_price_v1" for case in setup.plan.cases)
        assert setup.plan.families[0].scoring.scorer_id == "housing_lemons_price_outcome_v1"
        assert setup.plan.families[0].measurement.comparison_baseline == "housing_price_sign_anything_v1"
        assert {pin.component_id for pin in setup.plan.implementation_pins} >= {
            "housing_lemons_price_outcome_v1", "housing_price_sign_anything_v1",
            "housing_price_inspect_then_sign_v1",
        }
        tenant = next(profile for profile in setup.plan.agent_profiles if profile.model.provider == "openrouter")
        assert tenant.budgets.max_cost_usd == 0.3
        assert tenant.prompt.prompt_id == "housing_tenant_lemons_price_v1"
        assert tenant.model.revision == "google/gemini-3.8-flash-20260902"
    assert setups["true_cost"].plan.run_plan_id != setups["pooled"].plan.run_plan_id
    changed = dict(contract, total_cost_ceiling_usd=30.0)
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="cost cap drifted"):
        price_campaign.load_contract(path)
    with pytest.raises(ValueError, match="explicit reservation arm"):
        build_housing_smoke(
            tenant_provider="housing_scripted_tenant",
            tenant_model="housing_scripted_tenant_sign_anything_v1",
            tenant_revision="1.0.0", landlord_model="housing_scripted_landlord_price_v1",
            world_kind="lemons",
        )


def test_provider_free_price_cells_replay_and_report_selection(tmp_path):
    contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT)
    summary = asyncio.run(price_campaign.run(contract, tmp_path, live=False))
    assert summary["completed_cells"] == summary["planned_cells"] == 8
    assert summary["operational_failures"] == 0
    assert summary["cost_usd"] == 0.0
    assert summary["price_by_arm_quality"]["true_cost:sound"]["signed"] == 8
    assert summary["price_by_arm_quality"]["pooled:lemon"]["signed"] == 0
    result = json.loads((tmp_path / "preflight/world_100000__true_cost.json").read_text())
    assert result["status"] == "completed" and result["receipt_sha256"]
    assert len(result["price_rows"]) == 4
    assert all(row["world_seed"] == 100000 for row in result["price_rows"])
    # A resumed preflight reads immutable cell results instead of rerunning them.
    assert asyncio.run(price_campaign.run(contract, tmp_path, live=False)) == summary
