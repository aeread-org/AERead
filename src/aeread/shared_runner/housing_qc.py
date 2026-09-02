"""Provider-free Housing V1 qualification primitives.

These functions exercise policies through the same multi-round market used by
live agents.  They intentionally avoid provider and harness concerns so case
configuration can be qualified before any model calls are purchased.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import random
from typing import Any, Sequence

from aeread.housing_v1 import environment as hz

from .resolver import canonical_json_bytes


def content_sha256(value: Any) -> str:
    """Return the shared runner's canonical content digest."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def brute_force_assignment(surplus: Sequence[Sequence[float]]) -> float:
    """Enumerate small rectangular assignments to independently check the oracle."""

    tenant_count = len(surplus)
    listing_count = len(surplus[0]) if tenant_count else 0
    best = 0.0
    for matched_count in range(1, min(tenant_count, listing_count) + 1):
        for tenants in itertools.combinations(range(tenant_count), matched_count):
            for listings in itertools.permutations(range(listing_count), matched_count):
                total = sum(
                    max(0.0, float(surplus[tenant][listing]))
                    for tenant, listing in zip(tenants, listings)
                )
                best = max(best, total)
    return round(best, 2)


def run_no_op(world: hz.BidWorld, *, rounds: int) -> float:
    market = hz.HousingMarket(world, rounds=rounds)
    while not market.finished:
        market.submit_offers({})
        market.submit_responses({})
        market.submit_commits({})
    return market.result().total


def run_random(world: hz.BidWorld, *, rounds: int, seed: int) -> float:
    """Run a reproducible legal random policy with the deterministic landlord."""

    rng = random.Random(seed)
    market = hz.HousingMarket(world, rounds=rounds)
    while not market.finished:
        offers: dict[int, tuple[int, float]] = {}
        for tenant in market.unmatched_tenants():
            candidates = [
                listing
                for listing in market.open_listings()
                if world.values[tenant][listing] >= world.ask[listing]
            ]
            if candidates and rng.random() >= 0.25:
                listing = rng.choice(candidates)
                offers[tenant] = (
                    listing,
                    round(
                        rng.uniform(world.ask[listing], world.values[tenant][listing]),
                        2,
                    ),
                )
        contact = market.submit_offers(offers)
        response = market.submit_responses(
            hz.scripted_landlord_responses(market, contact.inbox)
        )
        commits = {
            tenant: (
                (
                    "sign"
                    if hold.rent <= world.values[tenant][hold.listing_id]
                    else "walk"
                ),
                hold.hold_id,
            )
            for tenant, hold in response.holds.items()
        }
        market.submit_commits(commits)
    return market.result().total


def run_oracle_informed(world: hz.BidWorld, *, rounds: int) -> float:
    """Drive the active mechanism toward the assignment upper bound."""

    oracle = hz.assignment_oracle(world.surplus)
    target = {tenant: listing for tenant, listing in oracle.pairs}
    market = hz.HousingMarket(world, rounds=rounds)
    while not market.finished:
        offers = {
            tenant: (target[tenant], world.costs[target[tenant]])
            for tenant in market.unmatched_tenants()
            if tenant in target and target[tenant] in market.open_listings()
        }
        contact = market.submit_offers(offers)
        response = market.submit_responses(
            hz.scripted_landlord_responses(market, contact.inbox)
        )
        market.submit_commits(
            {tenant: ("sign", hold.hold_id) for tenant, hold in response.holds.items()}
        )
    return market.result().total


def _normalized(total: float, upper_bound: float) -> float | None:
    if upper_bound == 0.0:
        return None
    return round(total / upper_bound, 12)


def _validate_world_shape(world: hz.BidWorld, *, tenants: int, listings: int) -> None:
    if world.num_tenants != tenants or world.num_listings != listings:
        raise ValueError("Housing generator returned unexpected dimensions")
    if [listing.listing_id for listing in world.listings] != list(range(listings)):
        raise ValueError("Housing listing identities do not match their dimensions")
    if len(world.costs) != listings or len(world.ask) != listings:
        raise ValueError("Housing cost or ask vector has invalid dimensions")
    if len(world.values) != tenants or any(
        len(row) != listings for row in world.values
    ):
        raise ValueError("Housing value matrix is not rectangular")
    if any(len(row) != listings for row in world.surplus):
        raise ValueError("Housing surplus matrix is not rectangular")


def audit_bid_world(
    *,
    tenants: int,
    listings: int,
    rounds: int,
    common_weight: float,
    world_seed: int,
) -> dict[str, Any]:
    """Return deterministic QC facts for one seeded Housing world.

    The function raises on generator drift, invalid numeric state, oracle
    disagreement, mechanism-ceiling failure, or a baseline exceeding the verified
    upper bound. A zero upper bound is retained as typed degeneracy.
    """

    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (tenants, listings, rounds)
    ):
        raise ValueError(
            "Housing tenants, listings, and rounds must be positive integers"
        )
    if isinstance(world_seed, bool) or not isinstance(world_seed, int):
        raise ValueError("Housing world_seed must be an integer")
    if (
        isinstance(common_weight, bool)
        or not isinstance(common_weight, (int, float))
        or not math.isfinite(float(common_weight))
        or not 0.0 <= float(common_weight) <= 1.0
    ):
        raise ValueError("Housing common_weight must be finite and within [0, 1]")

    first = hz.make_bid_world(tenants, listings, world_seed, float(common_weight))
    second = hz.make_bid_world(tenants, listings, world_seed, float(common_weight))
    _validate_world_shape(first, tenants=tenants, listings=listings)
    _validate_world_shape(second, tenants=tenants, listings=listings)
    first_digest = content_sha256(first)
    if first_digest != content_sha256(second):
        raise ValueError(f"world regeneration drift for seed {world_seed}")

    numeric_values = [
        *itertools.chain.from_iterable(first.values),
        *first.costs,
        *first.ask,
        *itertools.chain.from_iterable(first.surplus),
    ]
    if not all(math.isfinite(float(value)) for value in numeric_values):
        raise ValueError(f"non-finite Housing values for seed {world_seed}")

    oracle_total = hz.assignment_oracle(first.surplus).total
    brute_force_total = brute_force_assignment(first.surplus)
    if not math.isclose(oracle_total, brute_force_total, abs_tol=1e-9):
        raise ValueError(f"assignment oracle disagrees for seed {world_seed}")

    no_op_total = run_no_op(first, rounds=rounds)
    random_total = run_random(first, rounds=rounds, seed=world_seed ^ 0x5A5A5A5A)
    naive_total = hz.run_scripted_market(first, rounds=rounds, strategy="naive").total
    adaptive_total = hz.run_scripted_market(
        first, rounds=rounds, strategy="adaptive"
    ).total
    oracle_informed_total = run_oracle_informed(first, rounds=rounds)
    if not math.isclose(oracle_total, oracle_informed_total, abs_tol=1e-9):
        raise ValueError(
            f"oracle-informed active policy missed oracle for seed {world_seed}"
        )
    policy_totals = (no_op_total, random_total, naive_total, adaptive_total)
    if any(total < -1e-9 or total > oracle_total + 1e-9 for total in policy_totals):
        raise ValueError(f"baseline fell outside verified bounds for seed {world_seed}")

    viable_favourites: list[int] = []
    for tenant in range(first.num_tenants):
        candidates = [
            listing
            for listing in range(first.num_listings)
            if first.values[tenant][listing] > first.ask[listing]
        ]
        if candidates:
            viable_favourites.append(
                max(
                    candidates,
                    key=lambda listing: first.values[tenant][listing]
                    - first.ask[listing],
                )
            )
    favourite_counts = [
        viable_favourites.count(listing) for listing in range(first.num_listings)
    ]
    positive_edges = sum(value > 0.0 for row in first.surplus for value in row)
    return {
        "world_seed": world_seed,
        "world_sha256": first_digest,
        "deterministic_regeneration": True,
        "finite_values": True,
        "valid_dimensions": True,
        "oracle_crosscheck_passed": True,
        "degenerate_upper_bound": oracle_total == 0.0,
        "oracle_total": oracle_total,
        "brute_force_oracle_total": brute_force_total,
        "no_op_total": no_op_total,
        "random_total": random_total,
        "naive_total": naive_total,
        "adaptive_total": adaptive_total,
        "oracle_informed_total": oracle_informed_total,
        "no_op_normalized": _normalized(no_op_total, oracle_total),
        "random_normalized": _normalized(random_total, oracle_total),
        "naive_normalized": _normalized(naive_total, oracle_total),
        "adaptive_normalized": _normalized(adaptive_total, oracle_total),
        "oracle_minus_naive": round(oracle_total - naive_total, 2),
        "oracle_minus_naive_normalized": (
            None
            if oracle_total == 0.0
            else round((oracle_total - naive_total) / oracle_total, 12)
        ),
        "adaptive_minus_naive": round(adaptive_total - naive_total, 2),
        "adaptive_minus_naive_normalized": (
            None
            if oracle_total == 0.0
            else round((adaptive_total - naive_total) / oracle_total, 12)
        ),
        "naive_is_beatable": oracle_total > naive_total + 1e-9,
        "adaptive_beats_naive": adaptive_total > naive_total + 1e-9,
        "positive_surplus_edges": positive_edges,
        "positive_surplus_density": round(positive_edges / (tenants * listings), 12),
        "viable_favourite_count": len(viable_favourites),
        "max_favourite_collision": max(favourite_counts, default=0),
        "max_favourite_share": round(max(favourite_counts, default=0) / tenants, 12),
        "market_tightness": round(tenants / listings, 12),
    }
