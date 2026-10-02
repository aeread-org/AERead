"""Outside demand: one deciding tenant, four landlords, departures the world fixes."""

import asyncio
import dataclasses
import json

import pytest

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons, price_campaign
from aeread_families.housing import price_outside_demand as od
from aeread_families.housing.price_bargaining import LANDLORD_MARGIN, landlord_responses

CONFIGS = price_campaign.DEFAULT_CONTRACT.parent
CAMPAIGNS = (
    "housing_lemons_price_pilot_v10_glm53_flash_parasail_outside_w60",
    "housing_lemons_price_pilot_v10_deepseek_v4_flash_parasail_outside_w60",
    "housing_lemons_price_pilot_v9_glm53_flash_deepinfra_outside_w60",
    "housing_lemons_price_pilot_v9_deepseek_v4_flash_deepinfra_outside_w60",
    "housing_lemons_price_pilot_v8_glm53_flash_deepinfra_outside_w60",
    "housing_lemons_price_pilot_v8_deepseek_v4_flash_deepinfra_outside_w60",
)
SEEDS = range(100000, 100060)


def _world(seed, arm="true_cost"):
    return lemons.make_lemons_world(
        6, 4, seed, 0.6, lemon_share=0.5, lemon_loss=1000.0, inspection_cost=25.0,
        landlord_reservation=arm,
    )


def test_schedule_is_fixed_by_the_world_shared_by_both_arms_and_blind_to_quality():
    wanted = {"sound": [], "lemon": []}
    for seed in SEEDS:
        true_cost, pooled = _world(seed, "true_cost"), _world(seed, "pooled")
        schedule = od.schedule(true_cost.ask, 3)
        assert schedule == od.schedule(pooled.ask, 3) == od.schedule(true_cost.ask, 3)
        for round_row in schedule:
            for listing_id, taken in enumerate(round_row):
                quality = "lemon" if true_cost.quality[listing_id] == lemons.LEMON else "sound"
                wanted[quality].append(taken)
    # 360 draws per quality at the declared rate of 0.5: four standard errors is 0.105.
    for quality, draws in wanted.items():
        assert len(draws) == 360
        assert abs(sum(draws) / len(draws) - od.RATE) < 0.105, quality
    # The rule never sees quality, a value or a reservation: only the asks, listing and round.
    assert od.wanted([1000.0, 2000.0, 3000.0, 4000.0], 2, 1) == od.wanted([1000, 2000, 3000, 4000], 2, 1)


def _observation(market, tenant_id):
    return json.loads(json.dumps(market.tenant_observation(tenant_id), default=dataclasses.asdict))


def test_an_outside_seat_bids_zero_on_its_own_listing_only_when_wanted_and_signs_what_it_holds():
    seed = next(s for s in SEEDS if any(od.schedule(_world(s).ask, 1)[0]) and not all(od.schedule(_world(s).ask, 1)[0]))
    world = _world(seed)
    market = hz.HousingMarket(world, rounds=3)
    market.submit_inspections({})
    wanted_now = od.schedule(world.ask, 1)[0]
    for seat in od.OUTSIDE_SEATS:
        observation = _observation(market, seat)
        assert od.outside_demand_action(observation, "inspect") == {"decision": "pass", "listing_id": None}
        action = od.outside_demand_action(observation, "contact")
        listing_id = od.listing_for_seat(seat)
        if listing_id is not None and wanted_now[listing_id]:
            assert action == {"decision": "offer", "listing_id": listing_id, "rent": od.OPENING_OFFER}
        else:
            assert action["decision"] == "pass"
        assert od.outside_demand_action(observation, "commit")["decision"] == "pass"
    assert od.listing_for_seat(5) is None


def _play_round(market, focal_offer=None, focal_commit="walk"):
    """One round with the outside seats on policy and seat 0 doing what the test says."""
    market.submit_inspections({})
    offers = {}
    for seat in od.OUTSIDE_SEATS:
        if seat in market.unmatched_tenants():
            action = od.outside_demand_action(_observation(market, seat), "contact")
            if action["decision"] == "offer":
                offers[seat] = (action["listing_id"], action["rent"])
    if focal_offer is not None:
        offers[0] = focal_offer
    contact = market.submit_offers(offers)
    responses, _ = landlord_responses(market, contact.inbox)
    response = market.submit_responses(responses)
    commits = {}
    for tenant_id, hold in response.holds.items():
        if tenant_id == 0:
            commits[tenant_id] = (focal_commit, hold.hold_id)
        else:
            action = od.outside_demand_action(_observation(market, tenant_id), "commit")
            commits[tenant_id] = (action["decision"], action["hold_id"])
    market.submit_commits(commits)
    return response.holds


def test_a_wanted_listing_is_taken_at_the_landlords_own_price_unless_the_focal_seat_bid_on_it():
    seed = next(s for s in SEEDS if any(od.schedule(_world(s).ask, 1)[0]))
    for arm in ("true_cost", "pooled"):
        world = _world(seed, arm)
        wanted_now = od.schedule(world.ask, 1)[0]
        target = wanted_now.index(True)

        # Seat 0 stays away: every wanted listing goes, at the landlord's counter, and no other.
        market = hz.HousingMarket(world, rounds=3)
        _play_round(market)
        taken = {listing_id: tenant_id for tenant_id, listing_id in market.pairs}
        assert sorted(taken) == [l for l, w in enumerate(wanted_now) if w]
        for listing_id, tenant_id in taken.items():
            assert tenant_id == listing_id + 1
            floor = world.reservation_cost(listing_id)
            expected = round(max(floor, min(world.ask[listing_id], floor + LANDLORD_MARGIN)), 2)
            assert market.signed_rent[tenant_id] == pytest.approx(expected)

        # Seat 0 bids on one wanted listing and walks: that listing survives the round.
        market = hz.HousingMarket(world, rounds=3)
        holds = _play_round(market, focal_offer=(target, 1.0), focal_commit="walk")
        assert holds[0].listing_id == target
        assert target not in {listing_id for _tenant, listing_id in market.pairs}
        assert target + 1 in market.unmatched_tenants()

        # Seat 0 bids and signs: it has the listing and the outside seat does not.
        market = hz.HousingMarket(world, rounds=3)
        _play_round(market, focal_offer=(target, 1.0), focal_commit="sign")
        assert (0, target) in market.pairs


def test_provider_free_cells_take_only_what_the_schedule_says(tmp_path):
    contract = price_campaign.load_contract(CONFIGS / f"{CAMPAIGNS[1]}.json")
    summary = asyncio.run(price_campaign.run(contract, tmp_path, live=False, only_worlds=(100000, 100003)))
    assert summary["completed_cells"] == 6 and summary["operational_failures"] == 0
    paired = {}
    for path in sorted((tmp_path / "preflight").glob("world_*__*.json")):
        row = json.loads(path.read_text())
        if "world_seed" not in row or row.get("status") != "completed":
            continue
        world = _world(row["world_seed"], row["arm"])
        schedule = od.schedule(world.ask, 3)
        outside = [d for d in row["outcome_facts"]["commit_decisions"] if d["tenant_id"] != 0]
        for decision in outside:
            assert decision["decision"] == "sign"
            assert decision["listing_id"] == decision["tenant_id"] - 1
            assert schedule[decision["round_index"]][decision["listing_id"]]
        paired.setdefault(row["world_seed"], {})[row["arm"]] = sorted(
            (d["round_index"], d["listing_id"]) for d in outside
        )
    # The scripted focal seat plays the same in both arms here, so the departures match exactly.
    assert all(arms["true_cost"] == arms["pooled"] for arms in paired.values())
    calls = [json.loads(line) for line in (tmp_path / "seat_calls.jsonl").read_text().splitlines()]
    assert {row["role"] for row in calls} == {"focal", "rival"}
    assert {row["requested_model"] for row in calls if row["role"] == "rival"} == {od.MODEL}
    assert all("instructions_sha256" in row for row in calls if row["role"] == "focal")
    assert not any("instructions_sha256" in row for row in calls if row["role"] == "rival")


def test_router_tells_only_the_focal_seat_the_rule_and_logs_what_it_sent(tmp_path):
    from aeread.shared_runner.task.execution import ProviderRequest, ProviderResult

    contract = price_campaign.load_contract(CONFIGS / f"{CAMPAIGNS[0]}.json")
    spec = price_campaign.identity(contract)
    seen = []

    class Focal:
        async def complete(self, request):
            seen.append(request)
            return ProviderResult(
                response_id="r", requested_model=request.model, resolved_model=request.revision, output_text="{}",
                finish_reason="stop", input_tokens=1, cached_input_tokens=0, output_tokens=1, cost_usd=0.001,
                raw_response={},
            )

    router = price_campaign.make_seat_router(spec, contract, Focal(), tmp_path / "seat_calls.jsonl")
    observation = {"tenant_id": 0, "round_index": 0, "active_hold": None, "board": [
        {"listing_id": l, "rent_asked": 1000.0 + l, "status": "OPEN"} for l in range(4)
    ]}
    base = ProviderRequest(
        provider_call_id="c", provider="openrouter", base_url="https://openrouter.ai/api/v1",
        model="z-ai/glm-5.3-flash", revision="z-ai/glm-5.3-flash-20260826", instructions="PLAN PROMPT", input_text="",
        temperature=1.0, top_p=1.0, max_output_tokens=4096, reasoning_effort="low", timeout_seconds=120.0,
        request_sha256="x", max_cost_usd=0.3, output_schema={}, provider_metadata={"route_provider": "DeepInfra"},
        seed=1, messages=None, tools=None, reasoning_token_budget=None,
    )
    results = []
    for seat in range(6):
        body = {"observation": dict(observation, tenant_id=seat), "phase_id": "inspect"}
        request = dataclasses.replace(base, provider_call_id=f"c{seat}", input_text=json.dumps(body))
        results.append(asyncio.run(router.complete(request)))
    # Only seat 0 reached the paid client, and it carried the plan's prompt plus the notice.
    assert len(seen) == 1
    assert seen[0].instructions == "PLAN PROMPT" + od.FOCAL_NOTICE
    assert str(od.RATE) in od.FOCAL_NOTICE and "whether it is sound or a lemon" in od.FOCAL_NOTICE
    assert [r.requested_model for r in results[1:]] == [od.MODEL] * 5
    assert all(r.cost_usd == 0.0 for r in results[1:])
    logged = [json.loads(line) for line in (tmp_path / "seat_calls.jsonl").read_text().splitlines()]
    assert logged[0]["instructions_sha256"] == od.instructions_sha256(seen[0])
    assert contract["rivals"]["focal_notice"] == od.FOCAL_NOTICE
    assert contract["rivals"]["focal_notice_sha256"] == od.FOCAL_NOTICE_SHA256


@pytest.mark.parametrize("campaign_id", CAMPAIGNS)
def test_outside_demand_contracts_declare_the_rule_and_refuse_drift(tmp_path, campaign_id):
    contract = price_campaign.load_contract(CONFIGS / f"{campaign_id}.json")
    assert contract["rivals"] == od.block()
    assert contract["rivals"]["rate_per_round"] == 0.5 and contract["rivals"]["quality_dependence"] == "none"
    assert contract["world_seeds"] == list(SEEDS)
    assert contract["route"]["provider"] == ("Parasail" if "parasail" in campaign_id else "DeepInfra")
    setup = price_campaign.build_setup(contract, "pooled", live=True)
    assert len([p for p in setup.plan.agent_profiles if p.model.provider == "openrouter"]) == 1
    for field, value in (("rate_per_round", 0.3), ("focal_notice", "something else"), ("opening_offer_usd", 1.0)):
        path = tmp_path / f"{field}.json"
        path.write_text(json.dumps(dict(contract, rivals=dict(contract["rivals"], **{field: value}))))
        with pytest.raises(ValueError, match="rival seats drifted"):
            price_campaign.load_contract(path)
