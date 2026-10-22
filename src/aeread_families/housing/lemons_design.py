"""Quality-blind admission and a declared stratum for the next lemons identity (HL-D-03).

The sealed lemons packs draw each world's quality from its seed and then admit the
world only if the inverted ordering holds on that draw (``sign_anything < pass <
inspect_then_sign``). Whether it holds depends on which listing is the lemon, and a
popular favourite that is a lemon is the draw that fails it, so the admitted worlds
under-represent a lemon favourite exactly where many tenants share it. The stratum
the pack then reports, "is the favourite a lemon", is confounded with competition.

This module separates the two. A world's *structure* (values, asks, costs) comes
from the seed; the *stratum* is declared, and the lemon set is drawn conditional
on it. A seed is admitted only if the same rule passes under **both** strata, so
admission cannot depend on which quality the favourite got, every admitted world
appears in both strata, and the stratum contrast is paired within the world, which
removes the world-to-world variance that dominated the price pilot.

It builds worlds through ``lemons.LemonsWorld`` and leaves ``lemons.py`` alone: a
plan's implementation digests hash that file's bytes, so editing it would move the
run-plan id of every sealed lemons identity (HL-T-04). Nothing here is wired to a
live contract; a new identity must declare it, with its own QC profile.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import random
from typing import Any, Mapping, Sequence

from aeread_families.housing import environment as hz

from . import lemons

STRATA = ("favourite_is_lemon", "favourite_is_sound")
#: New lemons identities use three rounds (owner ruling 2026-09-25).
DEFAULT_ROUNDS = 3


def favourite_votes(world: lemons.LemonsWorld) -> dict[int, int]:
    """First-choice counts by value-if-sound gain; ties go to the lowest listing id."""
    votes: dict[int, int] = {}
    for tenant in range(world.num_tenants):
        gains = [world.values_if_sound[tenant][l] - world.ask[l] for l in range(world.num_listings)]
        best = max(range(world.num_listings), key=lambda l: (gains[l], -l))
        votes[best] = votes.get(best, 0) + 1
    return votes


def favourite_listing(world: lemons.LemonsWorld) -> int:
    """The listing most tenants rank first; ties go to the lowest listing id.

    The same rule as ``lemons_campaign.favourite_listing``, restated here so this
    module does not import the campaign driver.
    """
    votes = favourite_votes(world)
    return max(votes, key=lambda l: (votes[l], -l))


def with_quality(world: lemons.LemonsWorld, quality: Sequence[int]) -> lemons.LemonsWorld:
    """The same structure with another lemon set.

    Values, costs and quality follow ``lemons.make_lemons_world`` exactly: a lemon is
    worth ``lemon_loss`` less to every tenant and costs its landlord that much less.
    """
    quality = tuple(quality)
    if len(quality) != world.num_listings or not set(quality) <= {lemons.SOUND, lemons.LEMON}:
        raise ValueError("quality must give SOUND or LEMON for every listing")
    loss = world.lemon_loss
    values = [
        [round(v - loss, 2) if quality[l] == lemons.LEMON else v for l, v in enumerate(row)]
        for row in world.values_if_sound
    ]
    costs = [
        round(max(0.0, c - loss), 2) if quality[l] == lemons.LEMON else c
        for l, c in enumerate(world.sound_costs)
    ]
    return dataclasses.replace(world, values=values, costs=costs, quality=quality)


def _draw_lemons(structure: lemons.LemonsWorld, seed: int, stratum: str) -> tuple[int, ...]:
    if stratum not in STRATA:
        raise ValueError(f"stratum must be one of {STRATA}")
    count = lemons.lemon_count_for(structure.num_listings, structure.lemon_share)
    favourite = favourite_listing(structure)
    others = [l for l in range(structure.num_listings) if l != favourite]
    # The stream is keyed by the stratum too, so the two draws are independent, and it
    # does not reuse the legacy stream (seed * 15485863 + 101), so no seed's legacy
    # world is silently reproduced under a stratum label.
    rng = random.Random(seed * 15485863 + 303 + 7 * STRATA.index(stratum))
    if stratum == STRATA[0]:
        chosen = {favourite, *rng.sample(others, count - 1)} if count >= 1 else set()
    else:
        chosen = set(rng.sample(others, count))
    if len(chosen) != count:
        raise ValueError("a stratum needs room for its lemons: lemon_count must fit the other listings")
    return tuple(lemons.LEMON if l in chosen else lemons.SOUND for l in range(structure.num_listings))


def make_stratified_world(
    seed: int,
    stratum: str,
    *,
    num_tenants: int = 6,
    num_listings: int = 4,
    common_weight: float = 0.6,
    lemon_share: float = lemons.DEFAULT_LEMON_SHARE,
    lemon_loss: float = lemons.DEFAULT_LEMON_LOSS,
    inspection_cost: float = lemons.DEFAULT_INSPECTION_COST,
    landlord_reservation: str = "true_cost",
) -> lemons.LemonsWorld:
    """The seed's structure with its lemons drawn conditional on the declared stratum."""
    structure = lemons.make_lemons_world(
        num_tenants, num_listings, seed, common_weight, lemon_share=lemon_share,
        lemon_loss=lemon_loss, inspection_cost=inspection_cost,
        landlord_reservation=landlord_reservation,
    )
    return with_quality(structure, _draw_lemons(structure, seed, stratum))


def stratum_of(world: lemons.LemonsWorld) -> str:
    return STRATA[0] if world.quality[favourite_listing(world)] == lemons.LEMON else STRATA[1]


def admission(
    seed: int,
    *,
    rounds: int = DEFAULT_ROUNDS,
    rule: Mapping[str, float] = lemons.DEFAULT_ADMISSION_RULE,
    **world_kwargs: Any,
) -> dict[str, Any]:
    """Admit a seed only if the rule passes under every stratum's draw."""
    failures: dict[str, list[str]] = {}
    for stratum in STRATA:
        world = make_stratified_world(seed, stratum, **world_kwargs)
        failures[stratum] = lemons.admission_failures(lemons.lemons_world_facts(world, rounds), rule)
    structure = lemons.make_lemons_world(
        world_kwargs.get("num_tenants", 6), world_kwargs.get("num_listings", 4), seed,
        world_kwargs.get("common_weight", 0.6),
    )
    votes = favourite_votes(structure)
    favourite = max(votes, key=lambda l: (votes[l], -l))
    return {
        "world_seed": seed,
        "admitted": not any(failures.values()),
        "failed_requirements_by_stratum": failures,
        "favourite_listing_id": favourite,
        "favourite_votes": votes[favourite],
    }


def select_pack(seed_start: int, worlds: int, **kwargs: Any) -> dict[str, Any]:
    """Walk the seed stream until ``worlds`` seeds are admitted. Each is used in both strata."""
    admitted: list[int] = []
    scanned: list[dict[str, Any]] = []
    seed = seed_start
    while len(admitted) < worlds:
        row = admission(seed, **kwargs)
        scanned.append(row)
        if row["admitted"]:
            admitted.append(seed)
        seed += 1
        if seed - seed_start > 10_000:
            raise ValueError("the seed stream did not fill the pack within 10000 seeds")
    return {"world_seeds": admitted, "strata": list(STRATA), "scanned": scanned}


def legacy_admission(seed: int, *, rounds: int = DEFAULT_ROUNDS, **world_kwargs: Any) -> dict[str, Any]:
    """The sealed rule: quality from the seed, admission on that draw."""
    world = lemons.make_lemons_world(
        world_kwargs.get("num_tenants", 6), world_kwargs.get("num_listings", 4), seed,
        world_kwargs.get("common_weight", 0.6),
    )
    failures = lemons.admission_failures(lemons.lemons_world_facts(world, rounds))
    votes = favourite_votes(world)
    favourite = max(votes, key=lambda l: (votes[l], -l))
    return {
        "world_seed": seed, "admitted": not failures, "favourite_votes": votes[favourite],
        "favourite_is_lemon": world.quality[favourite] == lemons.LEMON,
    }


def bias_sweep(seeds: Sequence[int], *, rounds: int = DEFAULT_ROUNDS) -> dict[str, Any]:
    """P(the favourite is a lemon) among admitted worlds, by how many tenants share it."""
    legacy = [legacy_admission(seed, rounds=rounds) for seed in seeds]
    blind = [admission(seed, rounds=rounds) for seed in seeds]

    def band(votes: int) -> str:
        return "1-2" if votes <= 2 else ("3-4" if votes <= 4 else "5-6")

    table: dict[str, dict[str, Any]] = {}
    for label in ("1-2", "3-4", "5-6"):
        before = [r for r in legacy if band(r["favourite_votes"]) == label]
        after = [r for r in before if r["admitted"]]
        blind_admitted = [r for r in blind if band(r["favourite_votes"]) == label and r["admitted"]]
        table[label] = {
            "legacy_seeds": len(before),
            "legacy_favourite_lemon_before_admission": round(
                sum(r["favourite_is_lemon"] for r in before) / len(before), 3) if before else None,
            "legacy_admitted": len(after),
            "legacy_favourite_lemon_after_admission": round(
                sum(r["favourite_is_lemon"] for r in after) / len(after), 3) if after else None,
            "blind_admitted": len(blind_admitted),
            # Both strata of every admitted world are in the pack, so this is exact.
            "blind_favourite_lemon_after_admission": 0.5 if blind_admitted else None,
        }
    return {
        "seeds": len(seeds), "rounds": rounds,
        "legacy_admitted": sum(r["admitted"] for r in legacy),
        "blind_admitted": sum(r["admitted"] for r in blind),
        "by_favourite_popularity": table,
    }


# --- one deciding tenant: the outside-demand price case ---------------------------------------
#
# The outside-demand case has one deciding tenant, seat 0, so the favourite whose quality
# matters is seat 0's, not the one most of six tenants rank first; the two differ in 18 of
# the 60 development worlds (100000-100059). The runner builds a world from its seed alone,
# so a pack cannot declare a world's lemons the way ``make_stratified_world`` does without
# editing the runner and moving every sealed Housing plan id (HL-T-04). This pack keeps each
# seed's own lemon draw instead and makes admission blind to it: the rule reads only seat 0's
# values-if-sound and the asks. The draw is a separate stream from the structure, so among
# admitted seeds the favourite is a lemon with probability one half whatever the structure,
# and the stratum is a covariate fixed before anyone plays. Seeds are taken in order until
# each stratum's quota is full.

DECIDING_SEAT = 0
#: Structure-only admission. The favourite must be worth wanting if sound, and a second
#: listing must be, so inspecting and moving on is a real option when the favourite is a lemon.
SEAT_ADMISSION_RULE: dict[str, float] = {"favourite_gain_min": 0.0, "positive_gain_listings_min": 2}
PACK_SEED_START = 300_000
HOLDOUT_SEED_START = 400_000
PACK_QUOTAS: dict[str, int] = {STRATA[0]: 200, STRATA[1]: 60}
HOLDOUT_QUOTAS: dict[str, int] = {STRATA[0]: 30, STRATA[1]: 10}


def _seed_world(seed: int) -> lemons.LemonsWorld:
    """The world the runner builds from ``seed``: structure and the seed's own lemon draw."""
    return lemons.make_lemons_world(6, 4, seed, 0.6, lemon_share=0.5, lemon_loss=1000.0, inspection_cost=25.0)


def seat_gains(world: lemons.LemonsWorld, seat: int = DECIDING_SEAT) -> list[float]:
    return [round(world.values_if_sound[seat][l] - world.ask[l], 2) for l in range(world.num_listings)]


def seat_favourite(world: lemons.LemonsWorld, seat: int = DECIDING_SEAT) -> int:
    """The listing ``seat`` gains most from if it is sound; ties go to the lowest listing id."""
    gains = seat_gains(world, seat)
    return max(range(world.num_listings), key=lambda l: (gains[l], -l))


def seat_stratum_of(world: lemons.LemonsWorld, seat: int = DECIDING_SEAT) -> str:
    return STRATA[0] if world.quality[seat_favourite(world, seat)] == lemons.LEMON else STRATA[1]


def seat_admission(seed: int, rule: Mapping[str, float] = SEAT_ADMISSION_RULE) -> dict[str, Any]:
    """Admit on seat 0's structure only; the stratum is read after, from the seed's own draw."""
    if set(rule) != set(SEAT_ADMISSION_RULE):
        raise ValueError("seat admission rule fields are incomplete or unexpected")
    world = _seed_world(seed)
    gains = seat_gains(world)
    favourite = seat_favourite(world)
    failures = []
    if gains[favourite] <= rule["favourite_gain_min"]:
        failures.append("favourite_gain_min")
    if sum(g > 0 for g in gains) < rule["positive_gain_listings_min"]:
        failures.append("positive_gain_listings_min")
    return {"world_seed": seed, "admitted": not failures, "failed": failures,
            "favourite_listing_id": favourite, "favourite_gain": gains[favourite],
            "stratum": seat_stratum_of(world)}


def select_seat_pack(seed_start: int, quotas: Mapping[str, int], *, max_scan: int = 20_000,
                     rule: Mapping[str, float] = SEAT_ADMISSION_RULE) -> dict[str, Any]:
    """Walk seeds from ``seed_start``; keep each admitted seed until its stratum's quota is full."""
    if set(quotas) != set(STRATA):
        raise ValueError(f"quotas must name every stratum: {STRATA}")
    chosen: dict[str, list[int]] = {stratum: [] for stratum in STRATA}
    scanned = admitted = 0
    seed = seed_start
    while any(len(chosen[s]) < quotas[s] for s in STRATA):
        if scanned >= max_scan:
            raise ValueError(f"the seed stream did not fill the quotas within {max_scan} seeds")
        row = seat_admission(seed, rule)
        scanned += 1
        if row["admitted"]:
            admitted += 1
            if len(chosen[row["stratum"]]) < quotas[row["stratum"]]:
                chosen[row["stratum"]].append(seed)
        seed += 1
    return {"seed_start": seed_start, "seed_end": seed - 1, "scanned": scanned, "admitted": admitted,
            "quotas": dict(quotas), "rule": dict(rule), "by_stratum": chosen,
            "world_seeds": sorted(s for seeds in chosen.values() for s in seeds)}


def confirmatory_pack() -> dict[str, Any]:
    """The pack and its holdout, from disjoint seed streams, with a digest to freeze."""
    pack = {"deciding_seat": DECIDING_SEAT, "stratum": "is seat 0's favourite (max value-if-sound minus ask) a lemon",
            "main": select_seat_pack(PACK_SEED_START, PACK_QUOTAS),
            "holdout": select_seat_pack(HOLDOUT_SEED_START, HOLDOUT_QUOTAS)}
    if pack["main"]["seed_end"] >= HOLDOUT_SEED_START:
        raise ValueError("the main pack ran into the holdout's seed stream")
    pack["sha256"] = hashlib.sha256(json.dumps(pack, sort_keys=True).encode("utf-8")).hexdigest()
    return pack


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-start", type=int, default=200000)
    parser.add_argument("--seeds", type=int, default=300)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--seat-pack", action="store_true", help="print the one-tenant confirmatory pack and holdout")
    args = parser.parse_args(argv)
    if args.seat_pack:
        print(json.dumps(confirmatory_pack(), indent=1, sort_keys=True))
        return 0
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    print(json.dumps(bias_sweep(list(seeds), rounds=args.rounds), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
