"""The ex-ante endpoint: stated odds vs the odds the landlord's reply leaves, on a recorded cell."""

import pytest

from aeread_families.housing import lemons, price_endpoint

# World 100002, true_cost arm, as the Gemini 3.8 Flash pilot recorded it
# (runs/housing_lemons_price_pilot_v1_gemini38_flash, 2026-09-27): four signings and
# twelve inspections at $25. Tenant 5 never inspected listing 3 and offered $2,200
# against a $2,625 ask; the landlord accepted at once. Tenant 0 inspected listing 0,
# saw a lemon, and signed it at $2,100.
RECORDED = {
    "tenant_net_total": -185.98,
    "inspection_count": 12,
    "tenant_inspection_spend": {"tenant_0": 50.0, "tenant_1": 75.0, "tenant_2": 25.0,
                                "tenant_3": 50.0, "tenant_4": 50.0, "tenant_5": 50.0},
    "commit_decisions": [
        {"decision": "sign", "expected_value": 2311.11, "informed": True, "listing_id": 1,
         "quality": "sound", "rent": 1934.0, "round_index": 0, "tenant_id": 2},
        {"decision": "sign", "expected_value": 1627.78, "informed": True, "listing_id": 2,
         "quality": "sound", "rent": 1541.0, "round_index": 1, "tenant_id": 3},
        {"decision": "sign", "expected_value": 2266.96, "informed": False, "listing_id": 3,
         "quality": "lemon", "rent": 2200.0, "round_index": 1, "tenant_id": 5},
        {"decision": "sign", "expected_value": 2183.17, "informed": True, "listing_id": 0,
         "quality": "lemon", "rent": 2100.0, "round_index": 2, "tenant_id": 0},
    ],
}


def test_the_recorded_cell_reconciles_and_prices_the_reply_leak():
    cell = price_endpoint.score_cell(RECORDED, world_seed=100002, arm="true_cost")
    assert abs(cell["residual"]) < 1e-6  # the parts sum to the realized net payoff
    assert cell["parts"]["inspection_spend"] == -300.0
    # Tenant 5's blind bet: worth +66.96 at the stated 50% odds, a certain lemon once
    # the reply is read ($2,200 is below any sound listing's floor), so worth -433.04.
    blind = next(row for row in cell["decisions"] if not row["informed"])
    assert blind["lemon_probability_stated"] == 0.5
    assert blind["worth_it_stated"] is True and blind["worth_it_response"] is False
    assert blind["reply_revealed_lemon"] is True
    assert blind["expected_value_response"] == pytest.approx(2766.96 - 1000.0)
    assert cell["reply_leak_expected_loss"] == pytest.approx(500.0)
    assert cell["net_expected_stated_odds"] == pytest.approx(314.02)
    assert cell["net_expected_response_odds"] == pytest.approx(-185.98)
    assert (cell["signed_blind"], cell["signed_blind_after_revealing_reply"]) == (1, 1)
    # Tenant 0 knew listing 0 was a lemon and still gained $83: an informed decision,
    # not a failure, and it carries no reply leak.
    informed_lemon = next(row for row in cell["decisions"] if row["tenant_id"] == 0)
    assert informed_lemon["informed"] and informed_lemon["quality"] == "lemon"
    assert not informed_lemon["reply_revealed_lemon"]


def test_the_pooled_landlord_never_reveals_a_lemon():
    # The same recorded decisions under the pooled arm: its landlord reserves on the
    # sound-equivalent cost, so no hold can sit below a sound listing's floor and
    # nothing is revealed, whatever rent the decision carries.
    cell = price_endpoint.score_cell(RECORDED, world_seed=100002, arm="pooled")
    assert cell["signed_blind_after_revealing_reply"] == 0
    assert cell["reply_leak_expected_loss"] == 0.0
    assert cell["net_expected_stated_odds"] == cell["net_expected_response_odds"]


def test_floor_is_the_lowest_rent_a_sound_landlord_takes():
    world = lemons.make_lemons_world(6, 4, 100002, 0.6, landlord_reservation="true_cost")
    for listing in range(4):
        floor = price_endpoint.sound_floor(world, listing)
        assert world.sound_costs[listing] <= floor <= world.ask[listing]
        assert floor - world.sound_costs[listing] <= 25.0 + 1e-9  # cost plus the margin
        # A lemon's own cost sits a full loss below, so its landlord accepts far less.
        if world.quality[listing] == lemons.LEMON:
            assert world.costs[listing] + 25.0 < floor


def _cell(seed, arm, replicate, realized):
    value = float(realized)
    return {"world_seed": seed, "arm": arm, "replicate_index": replicate, "net_realized": value,
            "net_expected_stated_odds": value, "net_expected_response_odds": value}


def test_replicate_noise_reads_sigma_against_the_world_signal():
    # True contrast per world: +100 in world 1, -100 in world 2 (signal sd about 141);
    # replicate noise of +/-10 on the true_cost cells only, so the contrast moves +/-10.
    cells = []
    for seed, base in ((1, 100.0), (2, -100.0)):
        for replicate, noise in ((0, 10.0), (1, -10.0)):
            cells += [_cell(seed, "true_cost", replicate, base + noise), _cell(seed, "pooled", replicate, 0.0)]
    noise = price_endpoint.replicate_noise(cells)
    contrast = noise["contrast"]["net_realized"]
    assert contrast["replicate_sd_of_contrast"] == pytest.approx(14.14, abs=0.01)  # sqrt(200)
    assert contrast["world_sd_of_true_contrast"] == pytest.approx(141.42, abs=0.5)
    assert contrast["sigma2_over_world_signal"] < 0.02  # the signal swamps the noise
    assert noise["cells_with_replicates"] == 4 and noise["cells_with_identical_replicates"] == 2  # pooled repeat exactly


def test_replicate_noise_is_absent_without_replicates():
    assert price_endpoint.replicate_noise([_cell(1, "true_cost", 0, 1.0), _cell(1, "pooled", 0, 2.0)]) is None


def test_pooling_runs_relabels_replicates_past_each_runs_own():
    first = [_cell(1, "true_cost", 0, 1.0), _cell(1, "pooled", 0, 0.0)]
    second = [_cell(1, "true_cost", r, 2.0 + r) for r in (0, 1)] + [_cell(1, "pooled", r, 0.0) for r in (0, 1)]
    pooled = price_endpoint.pool_cells([first, second])
    assert sorted({c["replicate_index"] for c in pooled}) == [0, 1, 2]
    assert [c["net_realized"] for c in pooled if c["arm"] == "true_cost" and c["replicate_index"] == 2] == [3.0]
    assert first[0]["replicate_index"] == 0  # the inputs are not mutated
