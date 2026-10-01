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


def test_workers_share_one_run_root_by_disjoint_world_ranges(tmp_path):
    contract = dict(price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT), world_seeds=[100000, 100001, 100002, 100003])
    first = asyncio.run(price_campaign.run(contract, tmp_path, live=False, only_worlds=(100000, 100002)))
    second = asyncio.run(price_campaign.run(contract, tmp_path, live=False, only_worlds=(100002, 100004)))
    assert first["planned_cells"] == second["planned_cells"] == 4
    assert (tmp_path / "preflight/summary_100000_100002.json").exists()
    assert (tmp_path / "preflight/summary_100002_100004.json").exists()
    assert not (tmp_path / "preflight/summary.json").exists()  # only a whole-panel process writes it
    # A process that covers everything reads the workers' cells instead of rerunning them.
    whole = asyncio.run(price_campaign.run(contract, tmp_path, live=False))
    assert whole["completed_cells"] == whole["planned_cells"] == 8


def test_seat_router_sends_rival_seats_to_the_rival_model_at_temperature_zero(tmp_path):
    import dataclasses

    from aeread.shared_runner.task.execution import ProviderRequest, ProviderResult

    contract = price_campaign.load_contract(
        price_campaign.DEFAULT_CONTRACT.parent / "housing_lemons_price_pilot_v6_glm53_flash_rivals_g31lite_w60.json"
    )
    model, route = price_campaign.ROUTES["google_gemini_31_flash_lite"]
    seen = []

    class Stub:
        async def complete(self, request):
            seen.append(request)
            return ProviderResult(
                response_id="r", requested_model=request.model, resolved_model=request.revision, output_text="{}",
                finish_reason="stop", input_tokens=1, cached_input_tokens=0, output_tokens=1, cost_usd=0.001,
                raw_response={},
            )

    router = price_campaign.SeatRouterClient(
        Stub(), Stub(), rival_block=contract["rivals"],
        rewrite=price_campaign.llm_rival_rewrite(model, route, contract["rivals"]),
        log_path=tmp_path / "seat_calls.jsonl",
    )
    base = ProviderRequest(
        provider_call_id="c", provider="openrouter", base_url="https://openrouter.ai/api/v1",
        model="z-ai/glm-5.3-flash", revision="z-ai/glm-5.3-flash-20260826", instructions="", input_text="",
        temperature=1.0, top_p=1.0, max_output_tokens=4096, reasoning_effort="low", timeout_seconds=120.0,
        request_sha256="x", max_cost_usd=0.3, output_schema={}, provider_metadata={"route_provider": "Parasail"},
        seed=1, messages=None, tools=None, reasoning_token_budget=None,
    )
    for seat in range(6):
        request = dataclasses.replace(base, provider_call_id=f"c{seat}", input_text=json.dumps({"observation": {"tenant_id": seat}}))
        asyncio.run(router.complete(request))
    assert [r.model for r in seen] == ["z-ai/glm-5.3-flash"] + [model] * 5
    assert [r.temperature for r in seen] == [1.0] + [0.0] * 5
    assert {r.provider_metadata["route_provider"] for r in seen[1:]} == {"Google"}
    logged = [json.loads(line) for line in (tmp_path / "seat_calls.jsonl").read_text().splitlines()]
    assert [row["role"] for row in logged] == ["focal"] + ["rival"] * 5
    changed = dict(contract, rivals=dict(contract["rivals"], temperature=1.0))
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="rival seats drifted"):
        price_campaign.load_contract(path)


def test_seat_router_backs_off_on_rival_rate_limit_and_never_retries_the_focal_seat(tmp_path, monkeypatch):
    import dataclasses

    from aeread.shared_runner.task.execution import ProviderFailure, ProviderRequest, ProviderResult

    contract = price_campaign.load_contract(
        price_campaign.DEFAULT_CONTRACT.parent / "housing_lemons_price_pilot_v6_glm53_flash_rivals_g31lite_w60.json"
    )
    model, route = price_campaign.ROUTES["google_gemini_31_flash_lite"]
    block = dict(contract["rivals"], backoff_seconds=0.0)
    calls = {"rival": 0, "focal": 0}

    class Flaky:
        def __init__(self, role, fail_first):
            self.role, self.left = role, fail_first

        async def complete(self, request):
            calls[self.role] += 1
            if self.left:
                self.left -= 1
                raise ProviderFailure("rate_limit", "429", retryable=True)
            return ProviderResult(
                response_id="r", requested_model=request.model, resolved_model=request.revision, output_text="{}",
                finish_reason="stop", input_tokens=1, cached_input_tokens=0, output_tokens=1, cost_usd=0.0, raw_response={},
            )

    base = ProviderRequest(
        provider_call_id="c", provider="openrouter", base_url="https://openrouter.ai/api/v1", model="m", revision="m",
        instructions="", input_text="", temperature=1.0, top_p=1.0, max_output_tokens=1, reasoning_effort="low",
        timeout_seconds=1.0, request_sha256="x", max_cost_usd=0.1, output_schema={}, provider_metadata={}, seed=1,
        messages=None, tools=None, reasoning_token_budget=None,
    )
    def req(seat):
        return dataclasses.replace(base, input_text=json.dumps({"observation": {"tenant_id": seat}}))
    router = price_campaign.SeatRouterClient(
        Flaky("focal", 1), Flaky("rival", 3), rival_block=block,
        rewrite=price_campaign.llm_rival_rewrite(model, route, block), log_path=tmp_path / "l.jsonl",
    )
    asyncio.run(router.complete(req(1)))
    assert calls["rival"] == 4
    with pytest.raises(ProviderFailure):
        asyncio.run(router.complete(req(0)))
    assert calls["focal"] == 1


def test_scripted_rivals_play_seats_one_to_five_and_the_plan_stays_one_profile(tmp_path):
    import dataclasses

    from aeread.shared_runner.task.execution import ProviderRequest, ProviderResult

    path = price_campaign.DEFAULT_CONTRACT.parent / "housing_lemons_price_pilot_v7_glm53_flash_rivals_inspect_w60.json"
    contract = price_campaign.load_contract(path)
    assert contract["rivals"]["kind"] == "scripted_tenant"
    setup = price_campaign.build_setup(contract, "true_cost", live=True)
    assert len([p for p in setup.plan.agent_profiles if p.model.provider == "openrouter"]) == 1
    changed = dict(contract, rivals=dict(contract["rivals"], model="housing_scripted_tenant_sign_anything_v1"))
    other = tmp_path / "changed.json"
    other.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="rival seats drifted"):
        price_campaign.load_contract(other)
    seen = []

    class Stub:
        def __init__(self, name):
            self.name = name

        async def complete(self, request):
            seen.append((self.name, request.provider, request.model))
            return ProviderResult(
                response_id="r", requested_model=request.model, resolved_model=request.revision, output_text="{}",
                finish_reason="stop", input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0, raw_response={},
            )

    router = price_campaign.SeatRouterClient(
        Stub("focal"), Stub("rival"), rival_block=contract["rivals"],
        rewrite=price_campaign.scripted_rival_rewrite(contract["rivals"]), log_path=tmp_path / "l.jsonl",
    )
    base = ProviderRequest(
        provider_call_id="c", provider="openrouter", base_url="u", model="z-ai/glm-5.3-flash", revision="r",
        instructions="", input_text="", temperature=1.0, top_p=1.0, max_output_tokens=1, reasoning_effort="low",
        timeout_seconds=1.0, request_sha256="x", max_cost_usd=0.1, output_schema={}, provider_metadata={}, seed=1,
        messages=None, tools=None, reasoning_token_budget=None,
    )
    for seat in (0, 3):
        asyncio.run(router.complete(dataclasses.replace(base, input_text=json.dumps({"observation": {"tenant_id": seat}}))))
    assert seen == [
        ("focal", "openrouter", "z-ai/glm-5.3-flash"),
        ("rival", "housing_scripted_tenant", "housing_scripted_tenant_inspect_then_sign_v1"),
    ]
