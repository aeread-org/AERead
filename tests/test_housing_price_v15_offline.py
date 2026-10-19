"""The v15 offline modules: the 0.3 holdout, notice v5 and pack v2's screen (docs/families/housing/price_confirmatory_v15_plan.md).

What has to hold before any v15 world is admitted or any model reads the notice:

1. The holdout's market loop is v14's: with v14's outside demand it reproduces ``price_reference.run_world`` exactly,
   and at 0.3 its outside demand takes a subset of what 0.5 takes, from the same draw.
2. The best-informed tenant planning at a rate is the original at 0.5.
3. Notice v5 is notice v4 followed by the pricing paragraph, unchanged; the holdout's text differs only in the rate,
   and each states the rate its environment runs.
4. The screen admits exactly when both ceilings are positive and the averaged headroom reaches the declared margin,
   and the near-duplicate check finds a world against itself and nothing in distinct worlds that are far apart.
"""

from __future__ import annotations

from aeread_families.housing import lemons, price_best_informed, price_notice_v5, price_outside_demand, price_reference
from aeread_families.housing import price_outside_demand_holdout as holdout
from aeread_families.housing import price_pack_v2 as pack


def test_the_holdout_loop_with_v14_outside_demand_is_v14s_market() -> None:
    for seed in (300002, 300010, 500003):
        for arm in pack.ARMS:
            for policy in (price_reference.inspect_lowball_action, lemons.inspect_then_sign_action):
                a = price_reference.run_world(seed, arm, policy)
                b = holdout.run_with(seed, arm, policy, price_outside_demand.outside_demand_action)
                assert price_reference.seat_net(a) == price_reference.seat_net(b)
                assert dict(a.pairs) == dict(b.pairs) and a.signed_rent == b.signed_rent


def test_outside_demand_at_point_three_takes_a_subset_of_what_point_five_takes() -> None:
    asks = [1800.0, 2200.0, 2650.0, 3100.0]
    low = price_outside_demand.schedule(asks, 3, rate=holdout.RATE)
    high = price_outside_demand.schedule(asks, 3)
    assert all(not l or h for row_l, row_h in zip(low, high) for l, h in zip(row_l, row_h))
    assert sum(map(sum, low)) <= sum(map(sum, high))


def test_the_tenant_planning_at_v14s_rate_is_the_original() -> None:
    for seed in (500003, 500011):
        for arm in pack.ARMS:
            assert price_best_informed.play(seed, arm, "pricing")["net"] == pack.play(seed, arm, "best_informed", price_outside_demand.RATE)["net_realized"]


def test_notice_v5_is_v4_then_the_pricing_rule_and_the_holdout_text_states_its_rate() -> None:
    assert price_notice_v5.DISCLOSURE_V5 == price_outside_demand.DISCLOSURE_V4 + price_outside_demand.PRICING_RULE
    assert f"probability {price_outside_demand.RATE}," in price_notice_v5.DISCLOSURE_V5
    held = price_notice_v5.DISCLOSURE_V5_HOLDOUT
    assert f"probability {holdout.RATE}," in held and f"probability {price_outside_demand.RATE}," not in held
    assert held.replace(f"probability {holdout.RATE},", f"probability {price_outside_demand.RATE},") == price_notice_v5.DISCLOSURE_V5
    assert price_notice_v5.block_v5()["notice_version"] == 5
    assert price_notice_v5.block_v5(holdout_rate=True)["rate_per_round"] == holdout.RATE
    assert price_notice_v5.block_v5()["rate_per_round"] == price_outside_demand.RATE
    assert "focal_notice" not in holdout.block()
    pid, text = price_notice_v5.tenant_prompt()
    assert pid != price_outside_demand.DISCLOSURE_PROMPT_ID and text.endswith(price_notice_v5.DISCLOSURE_V5)


def test_the_screen_admits_on_ceilings_and_averaged_headroom() -> None:
    rows = [pack.screen((seed, "main")) for seed in range(500000, 500012)]
    for row in rows:
        if row["status"] in {"passed", "headroom"}:
            mean = sum(row["best_informed_v2"][a] - row["inspect_then_sign_v2"][a] for a in pack.ARMS) / len(pack.ARMS)
            assert abs(row["headroom"] - round(mean, 2)) < 1e-9
            assert (row["status"] == "passed") == (row["headroom"] >= pack.HEADROOM_MIN)
            assert all(c > 0.005 for c in row["ceiling"].values())
    assert {r["status"] for r in rows} >= {"passed", "headroom"}


def test_the_near_duplicate_check() -> None:
    view = pack.seat_view(500000)
    assert len(view) == 4 and view == tuple(sorted(view))
    assert pack.near_duplicates([500000, 500005], tolerance=10_000.0) == [(500000, 500005)]
    assert pack.near_duplicates([500000, 500005], tolerance=0.0) == []


def test_the_committed_pack_matches_its_declared_quotas_and_the_oracle_reaches_every_ceiling() -> None:
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "evidence/housing" / pack.PACK_ID
    committed = json.loads((root / "reports/pack.json").read_text())
    for stream in pack.STREAMS:
        block = committed["streams"][stream.name]
        assert {k: len(v) for k, v in block["by_stratum"].items()} == dict(stream.quotas)
        assert block["rate_per_round"] == stream.rate
        for seed in block["world_seeds"]:
            for arm in pack.ARMS:
                assert pack.oracle_net(seed, arm, stream.rate) == price_reference.ceiling(seed, arm), (stream.name, seed, arm)
    assert committed["near_duplicates"] == 0
    seeds = [s for b in committed["streams"].values() for s in b["world_seeds"]]
    assert len(seeds) == len(set(seeds)) == 320
