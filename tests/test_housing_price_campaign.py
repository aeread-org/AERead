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


# Run-plan ids of the sealed v1 Gemini pilot (runs/housing_lemons_price_pilot_v1_*,
# 2026-09-27). A plan's implementation digests hash the bytes of runner.py,
# environment.py, lemons.py and price_bargaining.py, so editing any of them moves
# these ids and breaks replay of every sealed Housing identity (HL-T-04).
SEALED_V1_PLAN_IDS = {"true_cost": "runplan_e4c1e3fa9ff83e6c", "pooled": "runplan_2db0b54b7ff8b51d"}
V2_CONTRACTS = {
    "housing_lemons_price_pilot_v2_glm53_flash_deepinfra": {
        "model": "z-ai/glm-5.3-flash", "revision": "z-ai/glm-5.3-flash-20260826",
        "provider": "DeepInfra", "quantization": "fp4", "temperature": 1.0, "top_p": 1.0,
    },
    "housing_lemons_price_pilot_v2_glm53_flash_parasail": {
        "model": "z-ai/glm-5.3-flash", "revision": "z-ai/glm-5.3-flash-20260826",
        "provider": "Parasail", "quantization": "fp8", "temperature": 1.0, "top_p": 1.0,
    },
    "housing_lemons_price_pilot_v3_glm53_flash_parasail_k2": {
        "model": "z-ai/glm-5.3-flash", "revision": "z-ai/glm-5.3-flash-20260826",
        "provider": "Parasail", "quantization": "fp8", "temperature": 1.0, "top_p": 1.0, "replicates": 2,
    },
    "housing_lemons_price_pilot_v3_gpt56_luna_k2": {
        "model": "openai/gpt-5.6-luna", "revision": "openai/gpt-5.6-luna-20260709",
        "provider": "OpenAI", "quantization": "unknown", "temperature": None, "top_p": None, "replicates": 2,
    },
    "housing_lemons_price_pilot_v2_gpt56_luna": {
        "model": "openai/gpt-5.6-luna", "revision": "openai/gpt-5.6-luna-20260709",
        "provider": "OpenAI", "quantization": "unknown", "temperature": None, "top_p": None,
    },
}


def test_sealed_v1_plan_identity_survives_edits_to_this_module():
    contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT)
    for arm, sealed in SEALED_V1_PLAN_IDS.items():
        assert price_campaign.build_setup(contract, arm, live=True).plan.run_plan_id == sealed


class _RecordingProvider:
    """Stands in for the paid client: records each request, answers like the scripted tenant."""

    def __init__(self):
        self.requests = []

    async def complete(self, request):
        import dataclasses

        from aeread_families.housing.runner import HousingScriptedTenantProvider

        self.requests.append(request)
        return await HousingScriptedTenantProvider().complete(
            dataclasses.replace(
                request, provider="housing_scripted_tenant",
                model="housing_scripted_tenant_inspect_then_sign_v1", revision="1.0.0",
            )
        )


@pytest.mark.parametrize("campaign_id", sorted(V2_CONTRACTS))
def test_v2_identity_sends_exactly_its_declared_route_and_sampling(tmp_path, campaign_id):
    expected = V2_CONTRACTS[campaign_id]
    path = price_campaign.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json")
    contract = price_campaign.load_contract(path)
    assert contract["campaign_id"] == campaign_id
    assert contract["world_seeds"] == [100000, 100001, 100002, 100003]  # the v1 draws
    provider = _RecordingProvider()
    summary = asyncio.run(price_campaign.run(contract, tmp_path, live=True, provider=provider))
    cells = 8 * expected.get("replicates", 1)
    assert contract["replicates"] == expected.get("replicates", 1)
    assert summary["completed_cells"] == summary["planned_cells"] == cells
    assert summary["operational_failures"] == 0
    assert provider.requests
    for request in provider.requests:
        assert request.provider == "openrouter"
        assert (request.model, request.revision) == (expected["model"], expected["revision"])
        assert request.temperature == expected["temperature"]
        assert request.top_p == expected["top_p"]
        assert request.reasoning_effort == "low"
        assert request.provider_metadata["route_provider"] == expected["provider"]
        assert request.provider_metadata["quantization"] == expected["quantization"]
        assert request.seed is not None


def test_v2_contracts_refuse_drift(tmp_path):
    glm = json.loads(price_campaign.DEFAULT_CONTRACT.with_name(
        "housing_lemons_price_pilot_v2_glm53_flash_deepinfra.json").read_text())
    luna = json.loads(price_campaign.DEFAULT_CONTRACT.with_name(
        "housing_lemons_price_pilot_v2_gpt56_luna.json").read_text())
    stale = dict(glm, route=dict(glm["route"], quantization="fp8"))  # the sealed pin's quantization
    with_temperature = dict(luna, controls=dict(luna["controls"], temperature=1.0, top_p=1.0))
    over_budget = dict(luna, total_cost_ceiling_usd=3.0)
    for name, changed, message in (
        ("stale.json", stale, "claim or route drifted"),
        ("temperature.json", with_temperature, "execution controls drifted"),
        ("budget.json", over_budget, "cost cap drifted"),
    ):
        path = tmp_path / name
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match=message):
            price_campaign.load_contract(path)


def test_new_cells_carry_the_facts_the_endpoint_scores_from(tmp_path):
    from aeread_families.housing import price_endpoint

    contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT)
    asyncio.run(price_campaign.run(contract, tmp_path, live=False))
    row = json.loads((tmp_path / "preflight/world_100002__true_cost.json").read_text())
    assert set(row["outcome_facts"]) == set(price_endpoint.OUTCOME_FACTS)
    report = price_endpoint.score_run(tmp_path / "preflight")
    assert len(report["cells"]) == 8 and report["max_abs_residual"] < 1e-6
    # The scripted reference never signs blind, so the reply cannot have misled it.
    assert all(cell["signed_blind"] == 0 for cell in report["cells"])


def test_replicates_run_as_distinct_cells_with_their_own_seeds_and_files(tmp_path):
    campaign_id = "housing_lemons_price_pilot_v3_glm53_flash_parasail_k2"
    contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json"))
    provider = _RecordingProvider()
    asyncio.run(price_campaign.run(contract, tmp_path, live=True, provider=provider))
    files = sorted(path.name for path in (tmp_path / "live").glob("world_*__*.json"))
    assert len(files) == 16 and "world_100000__true_cost__r0.json" in files and "world_100000__true_cost__r1.json" in files
    rows = [json.loads((tmp_path / "live" / name).read_text()) for name in files]
    assert sorted({row["replicate_index"] for row in rows}) == [0, 1]
    assert len({row["cell_id"] for row in rows}) == 16
    # A replicate is a different draw, not a copy.
    first = json.loads((tmp_path / "live/world_100000__true_cost__r0.json").read_text())
    second = json.loads((tmp_path / "live/world_100000__true_cost__r1.json").read_text())
    assert first["cell_id"] != second["cell_id"] and first["receipt_sha256"] != second["receipt_sha256"]
    assert len({request.seed for request in provider.requests}) > 1


def test_k2_contract_refuses_one_replicate(tmp_path):
    path = price_campaign.DEFAULT_CONTRACT.with_name("housing_lemons_price_pilot_v3_gpt56_luna_k2.json")
    changed = dict(json.loads(path.read_text()), replicates=1)
    bad = tmp_path / "k1.json"
    bad.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="arms, replicates or rounds drifted"):
        price_campaign.load_contract(bad)


@pytest.mark.parametrize("campaign_id", [
    "housing_lemons_price_pilot_v4_glm53_flash_parasail_w60",
    "housing_lemons_price_pilot_v4_gpt56_luna_w60",
])
def test_sixty_world_panels_declare_their_seeds_and_run_the_same_wire_path(tmp_path, campaign_id):
    contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json"))
    assert contract["world_seeds"] == list(range(100000, 100060)) and contract["replicates"] == 1
    assert price_campaign.build_setup(contract, "true_cost", live=True).plan.cells.__len__() == 60
    # Two worlds through the live path with a recording stub; the other 58 are the same code.
    short = dict(contract, world_seeds=[100000, 100059])
    provider = _RecordingProvider()
    summary = asyncio.run(price_campaign.run(short, tmp_path, live=True, provider=provider))
    assert summary["completed_cells"] == summary["planned_cells"] == 4 and summary["operational_failures"] == 0
    assert {request.model for request in provider.requests} == {V2_CONTRACTS[
        "housing_lemons_price_pilot_v2_glm53_flash_parasail" if "glm" in campaign_id else "housing_lemons_price_pilot_v2_gpt56_luna"
    ]["model"]}


def test_every_world_in_the_sixty_panel_scores_without_a_degenerate_oracle():
    from aeread_families.housing import lemons
    for seed in range(100000, 100060):
        world = lemons.make_lemons_world(6, 4, seed, 0.6, landlord_reservation="true_cost")
        assert world.lemon_count == 2 and max(max(row) for row in world.surplus) > 0
