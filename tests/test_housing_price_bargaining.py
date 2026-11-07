"""The exploratory price probe uses real holds and preserves quality visibility."""

from aeread_families.housing import lemons
from aeread_families.housing import price_bargaining as price


def test_fixed_landlord_cost_floor_and_pooled_quality_boundary():
    offer = {"offer_id": "o0", "tenant_id": 0, "rent": 900.0}
    observation = {
        "listing": {"rent_asked": 2000.0},
        "inbox": [offer],
        "private_cost": 950.0,
        "reservation_cost": 1950.0,
        "quality": "lemon",
    }
    pooled = price.landlord_action(observation)
    assert pooled == {"decision": "counter", "offer_id": "o0", "counter_rent": 1975.0}
    assert price.landlord_action({**observation, "quality": "sound", "private_cost": 1950.0}) == pooled
    true_cost = price.landlord_action({key: value for key, value in observation.items() if key != "reservation_cost"})
    assert true_cost["counter_rent"] == 975.0
    assert true_cost["counter_rent"] >= observation["private_cost"]


def test_tenant_bids_only_after_inspection_and_accepts_affordable_counter():
    observation = {
        "board": [{"listing_id": 0, "rent_asked": 2000.0, "status": "OPEN"}],
        "private_values_if_sound": [2150.0], "lemon_loss": 1000.0,
        "inspections": [], "rejected_listing_ids": [], "active_hold": None,
    }
    assert price.tenant_action(observation, "contact")["decision"] == "pass"
    assert price.tenant_action(observation, "inspect")["listing_id"] == 0
    observed = {**observation, "inspections": [{"listing_id": 0, "quality": "lemon"}]}
    assert price.tenant_action(observed, "contact") == {
        "decision": "offer", "listing_id": 0, "rent": 900.0,
    }
    held = {**observed, "active_hold": {"hold_id": "h0", "listing_id": 0, "rent": 975.0}}
    assert price.tenant_action(held, "commit") == {"decision": "sign", "hold_id": "h0"}
    assert price.tenant_action({**held, "active_hold": {**held["active_hold"], "rent": 1200.0}}, "commit")["decision"] == "walk"


def test_paired_worlds_report_prices_and_trade_selection():
    true_rows = [row for seed in range(100000, 100003) for row in price.run_world(seed)]
    pooled_rows = [row for seed in range(100000, 100003) for row in price.run_world(seed, landlord_reservation="pooled")]
    assert true_rows == [row for seed in range(100000, 100003) for row in price.run_world(seed)]
    assert [(row["world_seed"], row["listing_id"], row["quality"], row["ask"]) for row in true_rows] == [
        (row["world_seed"], row["listing_id"], row["quality"], row["ask"]) for row in pooled_rows
    ]
    true = price.summarize(true_rows)
    pooled = price.summarize(pooled_rows)
    assert true["lemon"]["signed"] == 6 and true["sound"]["signed"] == 6
    assert true["lemon"]["signed_via_counter"] == 6
    assert true["sound"]["signed_via_counter"] == 6
    assert true["sound_minus_lemon_discount_gap"] > 900.0
    assert pooled["lemon"]["signed"] == 0
    assert pooled["lemon"]["mean_signed_rent"] is None
    assert pooled["sound_minus_lemon_discount_gap"] is None
    for row in true_rows:
        if row["signed_rent"] is None:
            continue
        world = lemons.make_lemons_world(
            6, 4, row["world_seed"], 0.6, lemon_share=0.5,
            lemon_loss=1000.0, inspection_cost=25.0,
            landlord_reservation="true_cost",
        )
        listing_id = row["listing_id"]
        assert world.costs[listing_id] <= row["signed_rent"]
        assert row["signed_rent"] <= world.values[row["tenant_id"]][listing_id]
