"""Controlled opponents cover cost; evaluated agents may still make losses."""
from __future__ import annotations

import asyncio
import dataclasses
import json
from argparse import Namespace

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ProviderFailure, ProviderRequest, execute_plan_cell
from aeread_families.housing import environment as hz
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider, HousingScriptedTenantProvider, _run_cli,
    build_housing_smoke, finalize_housing_execution, replay_housing_receipt,
)


def request(*, cost=90, ask=100, rents=(20,), version="2.0.0"):
    return ProviderRequest(
        provider_call_id="test", provider="housing_scripted_landlord", base_url=None,
        model=f"housing_scripted_landlord_v{version[0]}", revision=version,
        instructions="", input_text=json.dumps({"phase_id": "respond", "observation": {
            "private_cost": cost, "listing": {"rent_asked": ask},
            "inbox": [{"tenant_id": i, "offer_id": f"offer_{i}", "rent": rent}
                      for i, rent in enumerate(rents)]}}),
        temperature=0, top_p=1, max_output_tokens=512, reasoning_effort=None,
        timeout_seconds=5, request_sha256="",
    ).with_computed_hash()


def output(req):
    return json.loads(asyncio.run(HousingScriptedLandlordProvider().complete(req)).output_text)


@pytest.mark.parametrize("cost,ask,offer,expected", [
    (90, 100, 20, 90), (120, 100, 20, 120), (60, 100, 50, 75),
    (90.009, 100, 0, 90.009), (0.01, 0, 0, 0.01),
])
def test_counter_covers_cost_without_lowering_a_profitable_midpoint(cost, ask, offer, expected):
    action = output(request(cost=cost, ask=ask, rents=(offer,)))
    assert action == {"decision": "counter", "offer_id": "offer_0", "counter_rent": expected}
    assert action["counter_rent"] >= cost


def test_legacy_midpoint_remains_explicitly_available():
    assert output(request(version="1.0.0"))["counter_rent"] == 60
    assert output(request())["counter_rent"] == 90


@pytest.mark.parametrize("rents,winner", [((90,), "offer_0"), ((100, 110, 110), "offer_1")])
def test_acceptance_at_cost_and_highest_offer_tie_break_are_preserved(rents, winner):
    assert output(request(rents=rents)) == {"decision": "accept", "offer_id": winner, "counter_rent": None}


def test_empty_inbox_rejects_and_bad_model_revision_cannot_silently_select_legacy():
    assert output(request(rents=())) == {"decision": "reject_all", "offer_id": None, "counter_rent": None}
    with pytest.raises(ProviderFailure, match="model/revision"):
        output(dataclasses.replace(request(), revision="1.0.0"))
    with pytest.raises(ValueError, match="policy"):
        hz.scripted_landlord_counter_rent(20, 100, 90, policy_version="unknown")


@pytest.mark.parametrize("version,landlord_payoff", [("1.0.0", -30), ("2.0.0", 0)])
def test_signed_counter_reproduces_then_fixes_actual_economic_defect(version, landlord_payoff):
    listing = hz.Listing(0, 100, 1, 1, 10, 2, 5)
    market = hz.HousingMarket(hz.BidWorld([listing], [[100]], [90], [100]), rounds=1)
    inbox = market.submit_offers({0: (0, 20)}).inbox
    responses = hz.scripted_landlord_responses(market, inbox, policy_version=version)
    hold = market.submit_responses(responses).holds[0]
    market.submit_commits({0: ("sign", hold.hold_id)})
    assert market.economics().landlord_payoffs[0] == landlord_payoff
    assert ("landlord:0" in market.economics().ir_violations) == (version == "1.0.0")


def test_v2_does_not_guard_or_rewrite_a_tenant_signing_above_value():
    listing = hz.Listing(0, 100, 1, 1, 10, 2, 5)
    market = hz.HousingMarket(hz.BidWorld([listing], [[80]], [90], [100]), rounds=1)
    inbox = market.submit_offers({0: (0, 20)}).inbox
    hold = market.submit_responses(hz.scripted_landlord_responses(market, inbox, policy_version="2.0.0")).holds[0]
    market.submit_commits({0: ("sign", hold.hold_id)})
    assert market.economics().tenant_payoffs[0] == -10
    assert market.economics().ir_violations == ("tenant:0",)


def test_generated_adversarial_offers_never_produce_a_losing_v2_landlord():
    # Exercise the full contact/respond/commit mechanism, including cost boundaries.
    for seed in range(200):
        world = hz.make_bid_world(6, 4, seed=seed, common_weight=.85)
        market = hz.HousingMarket(world, rounds=2)
        while not market.finished:
            offers = {}
            for tenant in market.unmatched_tenants():
                listing = market.open_listings()[tenant % len(market.open_listings())]
                cost = world.costs[listing]
                rent = (0, cost / 2, max(0, cost - .01), cost, cost + 1)[(seed + tenant) % 5]
                offers[tenant] = (listing, rent)
            inbox = market.submit_offers(offers).inbox
            response = market.submit_responses(hz.scripted_landlord_responses(market, inbox, policy_version="2.0.0"))
            assert all(h.rent >= world.costs[h.listing_id] for h in response.holds.values())
            market.submit_commits({t: ("sign", h.hold_id) for t, h in response.holds.items()})
        assert all(payoff >= 0 for payoff in market.economics().landlord_payoffs.values())


def test_v2_plan_declares_the_actual_policy_and_replays_a_forced_low_offer(tmp_path):
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant", tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0", landlord_model="housing_scripted_landlord_v2", landlord_revision="2.0.0",
    )
    profile = next(p for p in setup.plan.agent_profiles if p.profile_id == "housing_scripted_landlord_v2")
    assert profile.model.revision == "2.0.0"
    assert set(setup.plan.cells[0].profile_by_seat.values()) == {"housing_scripted_landlord_v2", "housing_scripted_tenant_v1"}
    assert b'housing_scripted_landlord_v2' in canonical_json_bytes(setup.plan.families[0])

    class LowOfferTenant(HousingScriptedTenantProvider):
        async def complete(self, req):
            result = await super().complete(req)
            action = json.loads(result.output_text)
            if action["decision"] == "offer":
                result = dataclasses.replace(result, output_text=json.dumps({**action, "rent": 0}))
            return result

    execution = asyncio.run(execute_plan_cell(
        plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry,
        evidence_root=tmp_path, prompt_sources=setup.prompt_sources,
        providers={"housing_scripted_tenant": LowOfferTenant(),
                   "housing_scripted_landlord": HousingScriptedLandlordProvider()},
        pricing=setup.pricing, harnesses=setup.harnesses,
    ))
    assert len(execution.episode_result.outcome["signed_rents"]) == 1
    assert all(v >= 0 for v in execution.episode_result.outcome["landlord_payoffs"].values())
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    replayed = replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path)
    assert canonical_json_bytes(replayed.scores) == canonical_json_bytes(receipt.scores)


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_cli_exposes_policy_version_and_defaults_to_v2(tmp_path, version):
    args = Namespace(provider="scripted", model=None, revision=None, world_seed=41001,
                     tenants=2, listings=1, rounds=1, attempt=0, run_root=tmp_path)
    if version == "1.0.0":
        args.scripted_landlord_version = version
    result = asyncio.run(_run_cli(args))
    assert result["scripted_landlord_version"] == version
    assert result["measurement_status"] == "ok"
