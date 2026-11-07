"""Oracle validation of the v14 seat-0 pack: the reachable reference and the ceiling, world by world.

Every admitted world of the v14 confirmatory pack (260 main, 40 holdout) is played through the
offline market (``price_reference.run_world``: the environment, the price landlord, the
outside-demand seats) under both landlord arms by two tenants:

* ``price_reference.inspect_lowball``, the reachable reference the v14 contrasts subtract;
* a full-information tenant that knows every listing's quality, never inspects, offers $0 in
  round 0 on the listing whose true value exceeds its landlord's counter target by most, and
  signs the counter. It reads the target from the landlord's own rule
  (``price_bargaining.landlord_action``), not from ``price_reference.ceiling``, so the two meet
  only if the ceiling is what the market actually pays.

The published figures are the bundle's per-cell ``reference_net`` and ``ceiling``
(``evidence/housing/housing_lemons_price_confirmatory_v14/tables/cells.jsonl``) and the
main-pack means quoted in the case contract. The whole sweep is 3,600 offline market runs and
takes about a second, so it runs by default.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Mapping

import pytest

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons, lemons_design, price_bargaining, price_reference as pr

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "configs/housing_lemons_outside_demand_pack_v1.json"
CELLS_PATH = ROOT / "evidence/housing/housing_lemons_price_confirmatory_v14/tables/cells.jsonl"
ARMS = ("true_cost", "pooled")
PACK_SHA256 = "39ddf59f93940a22a414729eb6878b45f422592a6312b17a75ee2157a0e8a888"


def _pack() -> dict[str, list[int]]:
    committed = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    generated = lemons_design.confirmatory_pack()
    assert committed["sha256"] == generated["sha256"] == PACK_SHA256
    for scope in ("main", "holdout"):
        assert committed[scope]["world_seeds"] == generated[scope]["world_seeds"]
    return {scope: list(committed[scope]["world_seeds"]) for scope in ("main", "holdout")}


PACK = _pack()


def counter_target(world: lemons.LemonsWorld, listing_id: int) -> float:
    """The rent the price landlord answers a $0 offer with, from its own rule and observation."""
    observation = dict(
        hz.HousingMarket(world, rounds=1).landlord_observation(listing_id),
        inbox=[{"offer_id": "probe", "tenant_id": pr.FOCAL_SEAT, "rent": 0.0}],
    )
    action = price_bargaining.landlord_action(observation)
    return 0.0 if action["decision"] == "accept" else float(action["counter_rent"])


def oracle_choice(world: lemons.LemonsWorld) -> tuple[int, float] | None:
    """Seat 0's listing with the largest true value less counter target, if that is positive."""
    surplus = {
        listing: float(world.values[pr.FOCAL_SEAT][listing]) - counter_target(world, listing)
        for listing in range(world.num_listings)
    }
    best = max(surplus, key=lambda listing: (surplus[listing], -listing))
    return (best, counter_target(world, best)) if surplus[best] > 0 else None


def full_information_tenant(world: lemons.LemonsWorld) -> pr.Policy:
    """Knows quality, never inspects, offers $0 on its best listing in round 0, signs the counter."""
    choice = oracle_choice(world)

    def act(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
        if phase_id == "contact" and choice is not None and int(observation["round_index"]) == 0:
            return {"decision": "offer", "listing_id": choice[0], "rent": 0.0}
        if phase_id == "commit":
            hold = lemons._hold_view(observation)
            if hold:
                return {"decision": "sign", "hold_id": hold["hold_id"]}
        return lemons._pass(phase_id)

    return act


def _snapshot(market: hz.HousingMarket) -> tuple[Any, ...]:
    seat = pr.FOCAL_SEAT
    return (pr.seat_net(market), sorted(market.pairs), market.signed_rent.get(seat),
            market.inspection_spend[seat], sorted(market.inspected[seat].items()),
            json.dumps(market.commit_decisions, sort_keys=True, default=str))


@pytest.fixture(scope="module")
def sweep() -> dict[tuple[int, str], dict[str, Any]]:
    cells = {}
    for seed in PACK["main"] + PACK["holdout"]:
        for arm in ARMS:
            first = pr.run_world(seed, arm, pr.inspect_lowball_action)
            second = pr.run_world(seed, arm, pr.inspect_lowball_action)
            world = pr.make_world(seed, arm)
            oracle = pr.run_world(seed, arm, full_information_tenant(world))
            cells[(seed, arm)] = {"reference": first, "reference_again": second, "oracle": oracle,
                                  "choice": oracle_choice(world), "ceiling": pr.ceiling(seed, arm)}
    return cells


def _main_mean(sweep: Mapping[tuple[int, str], Mapping[str, Any]], value, arms=ARMS) -> float:
    return round(statistics.fmean(
        statistics.fmean(value(sweep[(seed, arm)]) for arm in arms) for seed in PACK["main"]), 2)


def test_the_pack_is_the_v14_pack() -> None:
    assert (len(PACK["main"]), len(PACK["holdout"])) == (260, 40)
    assert not set(PACK["main"]) & set(PACK["holdout"])
    # No two worlds give seat 0 the same values, asks, costs and quality.
    views = set()
    for seed in PACK["main"] + PACK["holdout"]:
        world = pr.make_world(seed, "true_cost")
        views.add(json.dumps([world.values_if_sound[pr.FOCAL_SEAT], world.ask, list(world.sound_costs),
                              list(world.quality)]))
    assert len(views) == 300


def test_reference_is_deterministic_and_never_signs_blind(sweep) -> None:
    for key, cell in sweep.items():
        market = cell["reference"]
        assert _snapshot(market) == _snapshot(cell["reference_again"]), key
        leased = dict(market.pairs)
        if pr.FOCAL_SEAT in leased:
            assert leased[pr.FOCAL_SEAT] in market.inspected[pr.FOCAL_SEAT], key


def test_reference_reproduces_the_published_mean(sweep) -> None:
    assert _main_mean(sweep, lambda cell: pr.seat_net(cell["reference"])) == 291.67


def test_full_information_tenant_realizes_the_ceiling_in_every_cell(sweep) -> None:
    for key, cell in sweep.items():
        market = cell["oracle"]
        assert market.inspection_spend[pr.FOCAL_SEAT] == 0.0, key
        leased = dict(market.pairs)
        if cell["choice"] is None:
            assert pr.FOCAL_SEAT not in leased and cell["ceiling"] == 0.0, key
        else:
            listing, target = cell["choice"]
            assert leased.get(pr.FOCAL_SEAT) == listing, key
            assert market.signed_rent[pr.FOCAL_SEAT] == target, key
        assert pr.seat_net(market) == cell["ceiling"], key
        assert pr.seat_net(cell["reference"]) <= cell["ceiling"], key


def test_the_ceiling_check_fails_when_the_landlord_rule_moves(monkeypatch) -> None:
    # The counterexample that shows the check above can fail: a landlord asking cost plus $30
    # while the ceiling still assumes $25. ``ceiling`` binds its margin when it is defined.
    monkeypatch.setattr(price_bargaining, "LANDLORD_MARGIN", 30.0)
    off = sum(
        pr.seat_net(pr.run_world(seed, arm, full_information_tenant(pr.make_world(seed, arm)))) != pr.ceiling(seed, arm)
        for seed in PACK["main"] for arm in ARMS
    )
    assert off == 490


def test_ceiling_reproduces_the_published_means(sweep) -> None:
    oracle = lambda cell: pr.seat_net(cell["oracle"])  # noqa: E731
    assert _main_mean(sweep, oracle, ("true_cost",)) == 447.82
    assert _main_mean(sweep, oracle, ("pooled",)) == 292.40
    assert _main_mean(sweep, oracle) == 370.11


def test_offline_values_match_the_bundle_cell_for_cell(sweep) -> None:
    published: dict[tuple[int, str], tuple[float, float]] = {}
    for line in CELLS_PATH.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (int(row["world_seed"]), row["arm"])
        value = (row["reference_net"], row["ceiling"])
        assert published.setdefault(key, value) == value, key
    assert set(published) == set(sweep)
    for key, cell in sweep.items():
        assert (pr.seat_net(cell["reference"]), pr.seat_net(cell["oracle"])) == published[key], key
