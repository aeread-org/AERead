"""The reachable reference for the outside-demand price pilot."""

from __future__ import annotations

import pytest

from aeread_families.housing import lemons, price_outside_demand, price_reference as pr

ARMS = ("true_cost", "pooled")


def test_offline_market_reproduces_the_sealed_scripted_reference() -> None:
    # Seat 0's net in the sealed provider-free run of the v10 contract
    # (runs/reference/scripted_inspect_then_sign_outside_demand). All 120 cells
    # matched when the module was written; four worlds are pinned here.
    sealed = {100000: 190.92, 100001: -25.0, 100002: -50.0, 100003: 421.82}
    for seed, net in sealed.items():
        for arm in ARMS:
            assert pr.seat_net(pr.run_world(seed, arm, lemons.inspect_then_sign_action)) == net


def test_lowball_tenant_signs_only_verified_listings_at_the_landlord_target() -> None:
    for seed in range(100000, 100020):
        for arm in ARMS:
            market = pr.run_world(seed, arm, pr.inspect_lowball_action)
            leased = dict(market.pairs)
            if pr.FOCAL_SEAT not in leased:
                continue
            listing = leased[pr.FOCAL_SEAT]
            assert listing in market.inspected[pr.FOCAL_SEAT]
            world = market.world
            reservation = world.reservation_cost(listing)
            target = round(max(reservation, min(float(world.ask[listing]), reservation + 25.0)), 2)
            assert market.signed_rent[pr.FOCAL_SEAT] == target


def test_leaky_landlord_gap_is_the_inspection_fee() -> None:
    # Against the leaky landlord a verified lemon at its own floor is worth what a sound
    # listing at its floor is, so the reference loses only the fee in these worlds.
    for seed in (100000, 100001, 100002, 100003):
        market = pr.run_world(seed, "true_cost", pr.inspect_lowball_action)
        assert pr.seat_net(market) == pytest.approx(pr.ceiling(seed, "true_cost") - 25.0)


def test_reference_summary_on_the_development_worlds() -> None:
    result = pr.reference(range(100000, 100060), ARMS, "inspect_lowball")
    assert result["net_mean"] == 336.83
    assert result["ceiling_mean"] == 407.85
    assert result["by_arm"]["true_cost"]["share_of_ceiling"] > result["by_arm"]["pooled"]["share_of_ceiling"]
    assert pr.reference(range(100000, 100060), ARMS, "inspect_then_sign")["net_mean"] == 240.61


def test_outside_seats_follow_the_declared_rule() -> None:
    assert pr._act(3, pr.inspect_lowball_action, {"tenant_id": 3, "board": []}, "inspect") == \
        price_outside_demand.outside_demand_action({"tenant_id": 3, "board": []}, "inspect")
