"""Quality-blind admission and a declared stratum (HL-D-03): the generator, the gate, the sweep."""

import pytest

from aeread_families.housing import lemons, lemons_campaign, lemons_design

SEEDS = range(200000, 200060)


@pytest.mark.parametrize("arm", sorted(lemons.LANDLORD_RESERVATIONS))
def test_with_quality_rebuilds_the_legacy_world_exactly(arm):
    for seed in SEEDS:
        world = lemons.make_lemons_world(6, 4, seed, 0.6, landlord_reservation=arm)
        assert lemons_design.with_quality(world, world.quality) == world


def test_favourite_rule_matches_the_campaign_driver():
    for seed in SEEDS:
        world = lemons.make_lemons_world(6, 4, seed, 0.6)
        assert lemons_design.favourite_listing(world) == lemons_campaign.favourite_listing(world)
        assert lemons_design.stratum_of(world) == lemons_campaign.world_stratum(world)


def test_a_declared_stratum_fixes_the_favourites_quality_and_nothing_else():
    differing = 0
    for seed in SEEDS:
        worlds = {s: lemons_design.make_stratified_world(seed, s) for s in lemons_design.STRATA}
        lemon_fav, sound_fav = worlds["favourite_is_lemon"], worlds["favourite_is_sound"]
        for stratum, world in worlds.items():
            assert lemons_design.stratum_of(world) == stratum
            assert world.lemon_count == lemons.lemon_count_for(4, 0.5)
            # A lemon is worth the loss less and costs its landlord that much less.
            for l in world.lemon_ids:
                assert world.values[0][l] == round(world.values_if_sound[0][l] - world.lemon_loss, 2)
                assert world.costs[l] == round(max(0.0, world.sound_costs[l] - world.lemon_loss), 2)
        # One structure, two quality draws: the strata differ only in which listings are lemons.
        assert lemon_fav.values_if_sound == sound_fav.values_if_sound
        assert lemon_fav.ask == sound_fav.ask and lemon_fav.sound_costs == sound_fav.sound_costs
        differing += lemon_fav.quality != sound_fav.quality
        # Deterministic.
        assert lemons_design.make_stratified_world(seed, "favourite_is_lemon") == lemon_fav
    assert differing == len(SEEDS)


def test_the_gate_admits_only_seeds_that_pass_under_both_strata():
    mixed = 0
    for seed in SEEDS:
        row = lemons_design.admission(seed)
        failures = row["failed_requirements_by_stratum"]
        assert row["admitted"] == (not any(failures.values()))
        mixed += sum(bool(v) for v in failures.values()) == 1
        for stratum in lemons_design.STRATA:
            world = lemons_design.make_stratified_world(seed, stratum)
            facts = lemons.lemons_world_facts(world, lemons_design.DEFAULT_ROUNDS)
            assert lemons.admission_failures(facts) == failures[stratum]
    # The reason the gate exists: some structures pass under one draw and fail under
    # the other, and the legacy gate would have kept whichever draw the seed made.
    assert mixed > 0


def test_pack_walks_the_stream_and_every_world_has_both_strata():
    pack = lemons_design.select_pack(200000, 8)
    assert len(pack["world_seeds"]) == 8 and pack["world_seeds"] == sorted(pack["world_seeds"])
    assert all(row["admitted"] for row in pack["scanned"] if row["world_seed"] in pack["world_seeds"])
    for seed in pack["world_seeds"]:
        assert {lemons_design.stratum_of(lemons_design.make_stratified_world(seed, s))
                for s in lemons_design.STRATA} == set(lemons_design.STRATA)


def test_the_sweep_reports_the_legacy_bias_the_blind_gate_removes():
    report = lemons_design.bias_sweep(list(range(200000, 200120)))
    bands = report["by_favourite_popularity"]
    assert set(bands) == {"1-2", "3-4", "5-6"}
    assert all(b["blind_favourite_lemon_after_admission"] in (0.5, None) for b in bands.values())
    # Where a favourite is shared by most tenants, admission removes lemon favourites.
    crowded = bands["5-6"]
    assert crowded["legacy_favourite_lemon_after_admission"] < crowded["legacy_favourite_lemon_before_admission"]
    assert report["blind_admitted"] > 0
