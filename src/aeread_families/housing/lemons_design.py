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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-start", type=int, default=200000)
    parser.add_argument("--seeds", type=int, default=300)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    args = parser.parse_args(argv)
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    print(json.dumps(bias_sweep(list(seeds), rounds=args.rounds), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
