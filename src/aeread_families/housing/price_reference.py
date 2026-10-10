"""A reachable reference for the outside-demand price pilot, and the ceiling it is read against.

The full-information ceiling (seat 0 signs its best listing at that landlord's lowest
acceptable rent and pays no inspection) is not reachable: quality is hidden, an
inspection costs $25 and reveals one listing a round, and an open listing seat 0 did not
bid on leaves with probability one half each round. A model's share of that ceiling
therefore mixes what the model missed with what nobody could have had.

This module drives the same market offline (the environment's transitions, the price
landlord, the outside-demand seats) with a scripted seat 0 and reports what a simple,
strong tenant reaches. It is validated by replaying the sealed scripted reference run cell
for cell before it is trusted with a new policy.

``inspect_lowball_action`` uses only what notice v2 gives a tenant; it is not told how
landlords price. Each round it inspects its favourite unverified listing, offers $0 on the
best listing it has verified, and signs any counter whose known value covers it. A $0
offer is always countered at the landlord's own target, so a verified listing is signed at
the lowest rent that landlord accepts. Under the leaky landlord that includes a verified
lemon: its landlord's target is its own cost plus $25, which leaves the tenant the same
surplus as a sound listing at its floor. Under the pooled landlord a lemon is countered at
a sound listing's price, its known value does not cover it, and the tenant moves on.

Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import argparse
import json
import statistics
from typing import Any, Callable, Mapping, Sequence

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons, price_bargaining, price_outside_demand

Policy = Callable[[Mapping[str, Any], str], dict[str, Any]]

FOCAL_SEAT = price_outside_demand.FOCAL_SEAT
LOWBALL_OFFER = 0.0


def _known_value(observation: Mapping[str, Any], listing_id: int, known: Mapping[int, str]) -> float:
    value = float(observation["private_values_if_sound"][listing_id])
    if known.get(listing_id) == lemons.QUALITY_LABEL[lemons.LEMON]:
        value -= float(observation["lemon_loss"])
    return value


def inspect_lowball_action(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    """Inspect the favourite, offer $0 on the best verified listing, sign what its value covers."""
    known = lemons._inspection_lookup(observation)
    open_rows = lemons._open_candidates(observation)
    sound = lemons.QUALITY_LABEL[lemons.SOUND]

    def gain(row: Mapping[str, Any]) -> float:
        return lemons._gain_if_sound(observation, row)

    if phase_id == "inspect":
        if any(known.get(row["listing_id"]) == sound for row in open_rows):
            return lemons._pass(phase_id)
        unknown = [row for row in open_rows if row["listing_id"] not in known and gain(row) > 0]
        if not unknown:
            return lemons._pass(phase_id)
        chosen = max(unknown, key=lambda row: (gain(row), -int(row["listing_id"])))
        return {"decision": "inspect", "listing_id": chosen["listing_id"]}
    if phase_id == "contact":
        verified = [row for row in open_rows if row["listing_id"] in known]
        if not verified:
            return lemons._pass(phase_id)
        # A verified sound listing first; a verified lemon only to hear its landlord's price.
        chosen = max(verified, key=lambda row: (known[row["listing_id"]] == sound, gain(row)))
        return {"decision": "offer", "listing_id": chosen["listing_id"], "rent": LOWBALL_OFFER}
    if phase_id == "commit":
        hold = lemons._hold_view(observation)
        if not hold:
            return lemons._pass(phase_id)
        listing_id = int(hold["listing_id"])
        sign = listing_id in known and _known_value(observation, listing_id, known) >= float(hold["rent"])
        return {"decision": "sign" if sign else "walk", "hold_id": hold["hold_id"]}
    raise ValueError(f"unknown phase: {phase_id}")


POLICIES: dict[str, Policy] = {
    "inspect_then_sign": lemons.inspect_then_sign_action,
    "inspect_lowball": inspect_lowball_action,
}


def make_world(seed: int, arm: str) -> lemons.LemonsWorld:
    return lemons.make_lemons_world(
        6, 4, int(seed), 0.6, lemon_share=0.5, lemon_loss=1000.0,
        inspection_cost=25.0, landlord_reservation=arm,
    )


def _act(seat: int, focal: Policy, observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    if seat == FOCAL_SEAT:
        return focal(observation, phase_id)
    return price_outside_demand.outside_demand_action(observation, phase_id)


def run_world(seed: int, arm: str, focal: Policy, rounds: int = price_outside_demand.ROUNDS) -> hz.HousingMarket:
    """One world through the market: ``focal`` at seat 0, outside demand at seats 1 to 5."""
    market = hz.HousingMarket(make_world(seed, arm), rounds=rounds)
    while not market.finished:
        inspections = {}
        for seat in market.unmatched_tenants():
            action = _act(seat, focal, market.tenant_observation(seat), "inspect")
            if action["decision"] == "inspect":
                inspections[seat] = action["listing_id"]
        market.submit_inspections(inspections)
        offers = {}
        for seat in market.unmatched_tenants():
            action = _act(seat, focal, market.tenant_observation(seat), "contact")
            if action["decision"] == "offer":
                offers[seat] = (action["listing_id"], action["rent"])
        contact = market.submit_offers(offers)
        responses, _ = price_bargaining.landlord_responses(market, contact.inbox)
        holds = market.submit_responses(responses).holds
        commits = {}
        for seat in holds:
            action = _act(seat, focal, market.tenant_observation(seat), "commit")
            if action["decision"] in {"sign", "walk"}:
                commits[seat] = (action["decision"], action["hold_id"])
        market.submit_commits(commits)
    return market


def seat_net(market: hz.HousingMarket, seat: int = FOCAL_SEAT) -> float:
    """Seat ``seat``'s realized payoff: true value less rent for its lease, less its inspections."""
    world = market.world
    leased = dict(market.pairs)
    net = -float(market.inspection_spend[seat])
    if seat in leased:
        net += float(world.values[seat][leased[seat]]) - float(market.signed_rent[seat])
    return round(net, 2)


def ceiling(seed: int, arm: str, margin: float = price_bargaining.LANDLORD_MARGIN) -> float:
    """Full information: seat 0's best listing at its landlord's lowest acceptable rent, no fee."""
    world = make_world(seed, arm)
    best = 0.0
    for listing_id in range(world.num_listings):
        reservation = world.reservation_cost(listing_id)
        floor = round(max(reservation, min(float(world.ask[listing_id]), reservation + margin)), 2)
        best = max(best, float(world.values[FOCAL_SEAT][listing_id]) - floor)
    return round(best, 2)


def reference(seeds: Sequence[int], arms: Sequence[str], policy_id: str) -> dict[str, Any]:
    policy = POLICIES[policy_id]
    cells = []
    for seed in seeds:
        for arm in arms:
            market = run_world(seed, arm, policy)
            cells.append({"world_seed": int(seed), "arm": arm, "net": seat_net(market),
                          "ceiling": ceiling(seed, arm),
                          "signed": FOCAL_SEAT in dict(market.pairs),
                          "inspections": round(market.inspection_spend[FOCAL_SEAT] / market.world.inspection_cost)})
    by_arm = {}
    for arm in arms:
        rows = [c for c in cells if c["arm"] == arm]
        net = statistics.fmean(c["net"] for c in rows)
        top = statistics.fmean(c["ceiling"] for c in rows)
        by_arm[arm] = {"cells": len(rows), "net_mean": round(net, 2), "ceiling_mean": round(top, 2),
                       "share_of_ceiling": round(net / top, 4) if top else None,
                       "within_5pct": sum(c["net"] >= 0.95 * c["ceiling"] for c in rows)}
    net = statistics.fmean(c["net"] for c in cells)
    top = statistics.fmean(c["ceiling"] for c in cells)
    return {"policy": policy_id, "worlds": len(seeds), "net_mean": round(net, 2),
            "ceiling_mean": round(top, 2), "share_of_ceiling": round(net / top, 4),
            "by_arm": by_arm, "cells": cells}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", choices=sorted(POLICIES), default="inspect_lowball")
    parser.add_argument("--first-seed", type=int, default=100000)
    parser.add_argument("--worlds", type=int, default=60)
    parser.add_argument("--cells", action="store_true", help="include per-cell rows")
    args = parser.parse_args(argv)
    seeds = range(args.first_seed, args.first_seed + args.worlds)
    result = reference(seeds, ("true_cost", "pooled"), args.policy)
    if not args.cells:
        result.pop("cells")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
