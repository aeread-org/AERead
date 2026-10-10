"""The best informed tenant: it plays the real market, reads what it is told, and is not beaten by the scripted rule."""

from __future__ import annotations

import statistics

from aeread_families.housing import price_best_informed as best
from aeread_families.housing import price_reference

SEEDS = range(300000, 300030)


def test_the_tenant_told_how_landlords_price_earns_more_than_the_scripted_rule_and_less_than_the_ceiling() -> None:
    cells = [(seed, arm) for seed in SEEDS for arm in best.ARMS]
    informed = statistics.fmean(best.play(seed, arm, "pricing")["net"] for seed, arm in cells)
    rule = statistics.fmean(
        price_reference.seat_net(price_reference.run_world(seed, arm, price_reference.inspect_lowball_action)) for seed, arm in cells)
    ceiling = statistics.fmean(price_reference.ceiling(seed, arm) for seed, arm in cells)
    assert rule < informed < ceiling


def test_an_answer_far_below_the_ask_proves_a_lemon_only_to_the_tenant_told_how_landlords_price() -> None:
    for knowledge, expected in (("pricing", 1.0), ("stated", 0.5)):
        tenant = best.Tenant(knowledge)
        tenant.n, tenant.lemon_count = 4, 2
        lemon, _ = tenant._beliefs(("?", "?", "?", "?"), ("L", "-", "-", "-"))
        assert lemon[0] == expected, knowledge
    told = best.Tenant("pricing")
    told.n, told.lemon_count = 4, 2
    lemon, low = told._beliefs(("?", "?", "?", "?"), ("N", "-", "-", "-"))
    assert abs(lemon[0] - 1.0 / 3.0) < 1e-12  # an ordinary answer is evidence of a sound listing
    assert 0.0 < low[1] < 0.5


def test_the_same_world_and_knowledge_give_the_same_play() -> None:
    assert best.play(300003, "pooled", "pricing") == best.play(300003, "pooled", "pricing")
