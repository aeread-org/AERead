"""Pack v2 for the lemons price case with outside demand (v15): v14's admission, then a headroom screen.

    PYTHONPATH=src python -m aeread_families.housing.price_pack_v2 --write [--processes 4]
    PYTHONPATH=src python -m aeread_families.housing.price_pack_v2 --check

Declared in ``docs/families/housing/price_confirmatory_v15_plan.md``, Section 2, before this module existed:

- **Structure.** ``lemons_design.seat_admission``, v14's rule: seat 0's favourite and a second listing are worth
  more than their asks if sound. The stratum (is the favourite a lemon) is read afterwards from the seed's own draw.
- **Headroom screen.** Both landlord arms are played offline by ``inspect_then_sign`` and by the best-informed
  tenant (``price_best_informed``, knowledge ``pricing``, which notice v5 states), each scored under measure v2
  (``price_reply_posterior``). A world is admitted only if its full-information ceiling is above $0 in both arms and
  the best-informed tenant's net less ``inspect_then_sign``'s, averaged over the two arms, is at least
  :data:`HEADROOM_MIN`. A failing seed is logged with its numbers and fills no quota.
- **Streams.** Main from 500,000 (200 favourite-lemon, 60 favourite-sound); holdout from 520,000 (30 and 10) with
  outside demand at 0.3 a round (``price_outside_demand_holdout``), screened and played at that rate; development from
  540,000 for the profile probes and the variance pilot (Sections 7 and 8). The plan names the development stream's
  start, not its size; this module takes 20 worlds, 15 and 5, the main pack's proportions.
- **Near duplicates.** No two admitted worlds may give seat 0 views within :data:`NEAR_DUPLICATE_USD` on every
  listing's ask, value if sound and sound floor, after sorting the listings (``near_duplicates``).

Every seed scanned is logged in ``tables/scan.jsonl``; ``tables/controls.jsonl`` holds, for every admitted world and arm, the ceiling,
the four scripted controls and the best-informed tenant under all three measures. Nothing here is hashed into a
Housing plan.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons, lemons_design, price_bargaining, price_best_informed, price_controls, price_outside_demand
from aeread_families.housing import price_outside_demand_holdout as holdout
from aeread_families.housing import price_reference
from aeread_families.housing import price_reply_posterior as posterior

PACK_ID = "housing_lemons_price_pack_v2"
SCHEMA_VERSION = "aeread.housing_price_pack/2"
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evidence/housing" / PACK_ID
ARMS = ("true_cost", "pooled")
HEADROOM_MIN = 25.0
NEAR_DUPLICATE_USD = 10.0
MAX_SCAN = 20_000
MEASURES = ("net_realized", "primary_v1", "primary_v2")
KNOWLEDGE = "pricing"


@dataclass(frozen=True)
class Stream:
    name: str
    seed_start: int
    quotas: tuple[tuple[str, int], ...]
    rate: float


STREAMS = (
    Stream("main", 500_000, ((lemons_design.STRATA[0], 200), (lemons_design.STRATA[1], 60)), price_outside_demand.RATE),
    Stream("holdout", 520_000, ((lemons_design.STRATA[0], 30), (lemons_design.STRATA[1], 10)), holdout.RATE),
    Stream("development", 540_000, ((lemons_design.STRATA[0], 15), (lemons_design.STRATA[1], 5)), price_outside_demand.RATE),
)
BY_NAME = {s.name: s for s in STREAMS}


# ---------------------------------------------------------------------------
# Playing one world offline at a stream's rate.


class BestInformedAtRate(price_best_informed.Tenant):
    """``price_best_informed.Tenant`` planning with outside demand at ``rate``; at v14's rate it is the original."""

    def __init__(self, knowledge: str, rate: float) -> None:
        super().__init__(knowledge)
        self.rate = rate

    def _end(self, r, open_, quality, answer, bid) -> float:
        if self.rate == price_best_informed.RATE:
            return super()._end(r, open_, quality, answer, bid)
        if r + 1 >= price_best_informed.ROUNDS:
            return 0.0
        key = ("end", r, open_, quality, answer, bid)
        if key not in self._memo:
            at_risk = [l for l in range(self.n) if open_[l] and l != bid]
            total = 0.0
            for taken in itertools.product((False, True), repeat=len(at_risk)):
                gone = {l for l, t in zip(at_risk, taken) if t}
                chance = self.rate ** len(gone) * (1.0 - self.rate) ** (len(at_risk) - len(gone))
                total += chance * self._start(r + 1, tuple(o and l not in gone for l, o in enumerate(open_)), quality, answer)
            self._memo[key] = total
        return self._memo[key]


def _recorded(seed: int, arm: str, policy: Any, rate: float):
    return posterior.run_recorded(seed, arm, policy) if rate == price_outside_demand.RATE else holdout.run_recorded(seed, arm, policy)


def play(seed: int, arm: str, name: str, rate: float) -> dict[str, Any]:
    """One policy at seat 0 in one world and arm: every measure, as ``price_controls.control_cells`` records it."""
    tenant = BestInformedAtRate(KNOWLEDGE, rate) if name == "best_informed" else price_controls.CONTROLS[name]
    market, trajectory = _recorded(seed, arm, tenant, rate)
    scored = posterior.score_market(market, trajectory)
    if scored["net_realized"] != price_reference.seat_net(market):
        raise ValueError(f"accounting differs for {name} in {seed} {arm}")
    leased = dict(market.pairs).get(price_reference.FOCAL_SEAT)
    row = {**{m: scored[m] for m in MEASURES}, "signed": leased is not None, "signed_blind": len(scored["blind_signings"]),
           "inspections": len(market.inspected[price_reference.FOCAL_SEAT])}
    if name == "best_informed":
        row["plan_value"] = round(float(tenant.plan_value or 0.0), 2)
    return row


# ---------------------------------------------------------------------------
# The full-information tenant of the oracle run (plan Section 6), as tests/test_housing_price_oracle_run.py defines it.


def counter_target(world: lemons.LemonsWorld, listing_id: int) -> float:
    """The rent the price landlord answers a $0 offer with, from its own rule and observation."""
    observation = dict(
        hz.HousingMarket(world, rounds=1).landlord_observation(listing_id),
        inbox=[{"offer_id": "probe", "tenant_id": price_reference.FOCAL_SEAT, "rent": 0.0}],
    )
    action = price_bargaining.landlord_action(observation)
    return 0.0 if action["decision"] == "accept" else float(action["counter_rent"])


def full_information_tenant(world: lemons.LemonsWorld) -> price_reference.Policy:
    """Knows quality, never inspects, offers $0 in round 0 on the listing whose true value exceeds its landlord's
    counter target by most (if any does), and signs the counter."""
    surplus = {l: float(world.values[price_reference.FOCAL_SEAT][l]) - counter_target(world, l) for l in range(world.num_listings)}
    best = max(surplus, key=lambda l: (surplus[l], -l))
    choice = best if surplus[best] > 0 else None

    def act(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
        if phase_id == "contact" and choice is not None and int(observation["round_index"]) == 0:
            return {"decision": "offer", "listing_id": choice, "rent": 0.0}
        if phase_id == "commit":
            hold = lemons._hold_view(observation)
            if hold:
                return {"decision": "sign", "hold_id": hold["hold_id"]}
        return lemons._pass(phase_id)

    return act


def oracle_net(seed: int, arm: str, rate: float) -> float:
    """What the full-information tenant realizes in one world and arm, at the stream's rate."""
    policy = full_information_tenant(price_reference.make_world(seed, arm))
    run = price_reference.run_world if rate == price_outside_demand.RATE else holdout.run_world
    return price_reference.seat_net(run(seed, arm, policy))


# ---------------------------------------------------------------------------
# The screen and the scan.


def screen(job: tuple[int, str]) -> dict[str, Any]:
    """One seed's admission row: structure, then the ceilings, then the headroom, with every number it used."""
    seed, stream_name = job
    stream = BY_NAME[stream_name]
    structure = lemons_design.seat_admission(seed)
    row: dict[str, Any] = {"world_seed": seed, "stream": stream_name, "stratum": structure["stratum"],
                           "favourite_listing_id": structure["favourite_listing_id"], "favourite_gain": structure["favourite_gain"]}
    if not structure["admitted"]:
        return {**row, "status": "structure", "failed": structure["failed"]}
    row["ceiling"] = {arm: price_reference.ceiling(seed, arm) for arm in ARMS}
    if any(price_controls.zero_ceiling(c) for c in row["ceiling"].values()):
        return {**row, "status": "zero_ceiling"}
    row["best_informed_v2"] = {arm: play(seed, arm, "best_informed", stream.rate)["primary_v2"] for arm in ARMS}
    row["inspect_then_sign_v2"] = {arm: play(seed, arm, "inspect_then_sign", stream.rate)["primary_v2"] for arm in ARMS}
    row["headroom"] = round(math.fsum(row["best_informed_v2"][a] - row["inspect_then_sign_v2"][a] for a in ARMS) / len(ARMS), 2)
    return {**row, "status": "passed" if row["headroom"] >= HEADROOM_MIN else "headroom"}


def scan(stream: Stream, processes: int = 1, chunk: int = 64) -> dict[str, Any]:
    """Walk the stream's seeds in order; admit passing seeds until each stratum's quota is full."""
    quotas = dict(stream.quotas)
    chosen: dict[str, list[int]] = {s: [] for s in quotas}
    log: list[dict[str, Any]] = []
    seed = stream.seed_start
    pool = Pool(processes) if processes > 1 else None
    try:
        while any(len(chosen[s]) < quotas[s] for s in quotas):
            if seed - stream.seed_start >= MAX_SCAN:
                raise ValueError(f"{stream.name}: the seed stream did not fill the quotas within {MAX_SCAN} seeds")
            jobs = [(s, stream.name) for s in range(seed, seed + chunk)]
            rows = pool.map(screen, jobs, chunksize=1) if pool else [screen(j) for j in jobs]
            for row in rows:
                if not any(len(chosen[s]) < quotas[s] for s in quotas):
                    break  # computed beyond the last seed needed; not part of the scan
                if row["status"] == "passed":
                    if len(chosen[row["stratum"]]) < quotas[row["stratum"]]:
                        chosen[row["stratum"]].append(row["world_seed"])
                        row = {**row, "status": "admitted"}
                    else:
                        row = {**row, "status": "quota_full"}
                log.append(row)
            seed += chunk
    finally:
        if pool:
            pool.close()
    counts: dict[str, int] = {}
    for row in log:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"stream": stream.name, "seed_start": stream.seed_start, "seed_end": log[-1]["world_seed"], "scanned": len(log),
            "rate_per_round": stream.rate, "quotas": quotas, "status_counts": dict(sorted(counts.items())),
            "by_stratum": chosen, "world_seeds": sorted(s for v in chosen.values() for s in v), "log": log}


# ---------------------------------------------------------------------------
# Near duplicates and the controls of the admitted worlds.


def seat_view(seed: int) -> tuple[tuple[float, float, float], ...]:
    """Seat 0's view of a world: each listing's ask, value if sound and sound floor, sorted."""
    world = price_reference.make_world(seed, "pooled")  # in the pooled arm every landlord reserves at the sound cost
    rows = []
    for l in range(world.num_listings):
        ask = float(world.ask[l])
        reservation = world.reservation_cost(l)
        floor = round(max(reservation, min(ask, reservation + price_reference.price_bargaining.LANDLORD_MARGIN)), 2)
        rows.append((round(ask, 2), round(float(world.values_if_sound[0][l]), 2), floor))
    return tuple(sorted(rows))


def near_duplicates(seeds: Sequence[int], tolerance: float = NEAR_DUPLICATE_USD) -> list[tuple[int, int]]:
    """Every pair of worlds whose seat-0 views lie within ``tolerance`` on every listing's every number."""
    views = {s: seat_view(s) for s in seeds}
    out = []
    for a, b in itertools.combinations(sorted(seeds), 2):
        if all(abs(x - y) <= tolerance for ra, rb in zip(views[a], views[b]) for x, y in zip(ra, rb)):
            out.append((a, b))
    return out


def controls(job: tuple[int, str]) -> list[dict[str, Any]]:
    seed, stream_name = job
    stream = BY_NAME[stream_name]
    rows = []
    for arm in ARMS:
        row: dict[str, Any] = {"world_seed": seed, "stream": stream_name, "arm": arm, "rate_per_round": stream.rate,
                               "ceiling": price_reference.ceiling(seed, arm)}
        for name in (*price_controls.CONTROLS, "best_informed"):
            row[name] = play(seed, arm, name, stream.rate)
        rows.append(row)
    return rows


def build(processes: int = 1) -> dict[str, Any]:
    scans = {s.name: scan(s, processes) for s in STREAMS}
    seeds = [w for s in scans.values() for w in s["world_seeds"]]
    if len(set(seeds)) != len(seeds):
        raise AssertionError("a world is in two streams")
    duplicates = near_duplicates(seeds)
    if duplicates:
        raise AssertionError(f"near-duplicate worlds: {duplicates[:5]}")
    jobs = [(w, name) for name, s in scans.items() for w in s["world_seeds"]]
    with Pool(processes) as pool:
        control_rows = [r for rows in pool.map(controls, jobs, chunksize=1) for r in rows]
    pack = {"pack_id": PACK_ID, "schema_version": SCHEMA_VERSION, "deciding_seat": lemons_design.DECIDING_SEAT,
            "plan": "docs/families/housing/price_confirmatory_v15_plan.md",
            "structure_rule": dict(lemons_design.SEAT_ADMISSION_RULE),
            "headroom_rule": {"min_usd": HEADROOM_MIN, "measure": posterior.MEASURE_ID, "reference": f"price_best_informed, knowledge {KNOWLEDGE}",
                              "control": "inspect_then_sign", "arms": list(ARMS), "averaged_over": "the two arms",
                              "zero_ceiling": "a world with a $0 ceiling in either arm is refused"},
            "near_duplicate_usd": NEAR_DUPLICATE_USD, "near_duplicates": len(duplicates),
            "streams": {name: {k: v for k, v in s.items() if k != "log"} for name, s in scans.items()}}
    pack["sha256"] = hashlib.sha256(json.dumps(pack, sort_keys=True).encode("utf-8")).hexdigest()
    return {"pack": pack, "scan": [r for s in scans.values() for r in s["log"]], "controls": control_rows}


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8")


def files(result: Mapping[str, Any]) -> dict[str, bytes]:
    return {"reports/pack.json": (json.dumps(result["pack"], indent=1, sort_keys=True) + "\n").encode("utf-8"),
            "tables/scan.jsonl": _jsonl(result["scan"]), "tables/controls.jsonl": _jsonl(result["controls"])}


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--processes", type=int, default=4)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)
    built = files(build(args.processes))
    if args.write:
        out.mkdir(parents=True, exist_ok=True)
        for name, data in built.items():
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(data)
        print(f"wrote {', '.join(built)} to {out}")
    if args.check:
        bad = [name for name, data in built.items() if not (out / name).exists() or (out / name).read_bytes() != data]
        print("check:", "ok" if not bad else f"differs: {bad}")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["ARMS", "BestInformedAtRate", "counter_target", "full_information_tenant", "oracle_net", "HEADROOM_MIN", "NEAR_DUPLICATE_USD", "PACK_ID", "STREAMS", "build", "controls",
           "near_duplicates", "play", "scan", "screen", "seat_view"]
