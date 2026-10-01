"""A same-state probe: does telling the tenant how to read a low hold change whether it signs?

The price panels showed tenants signing more as a hold sat further below the ask, in
the arm where only a lemon's landlord agrees to such a rent. The tenant was never told
that. This probe replays the commit-phase states those runs recorded, unchanged, with the
original instructions and with a disclosure appended, and counts how often the model signs.

It is a diagnostic, not evidence: it changes the one control a frozen identity would have
to declare (the prompt), so a result here can justify a new identity but is not itself a
measurement under one. Nothing is written into ``evidence/``.

A tenant that reads the disclosure correctly should walk from a hold more than $250 below
the ask on a listing it has not inspected, and keep signing every other hold. The probe
therefore reports sign rates in four groups so a model that simply turns suspicious of
everything shows up as such: blind holds below a sound listing's floor, blind holds at or
above it, informed holds, and the same blind holds under the ``pooled`` arm, where no hold
can be below the floor.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import glob
import json
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.task.execution import OpenRouterChatClient, ProviderRequest

from . import lemons
from .price_endpoint import sound_floor

#: What a sound listing's landlord can concede under the price rule: its cost sits at most
#: $250 under the ask and it counters at cost plus $25, so no sound hold is more than $225
#: below the ask. The explicit disclosure states the looser, true bound.
EXPLICIT = (
    "\nHow landlords in this market price. A landlord whose listing is sound keeps a margin: "
    "it never agrees to a rent more than $250 below the posted ask. A landlord whose listing "
    "is a lemon has a much lower cost, so it accepts or counters at rents far below the ask. "
    "A hold more than $250 below the ask on a listing you have not inspected therefore means "
    "the listing is a lemon, whatever the stated odds say. Holds within $250 of the ask say "
    "nothing about quality."
)
QUALITATIVE = (
    "\nA landlord's acceptance or counteroffer far below the posted ask can mean its costs "
    "are low, which can happen when its listing is a lemon."
)
VARIANTS: dict[str, str] = {"original": "", "qualitative": QUALITATIVE, "explicit": EXPLICIT}
DEEP = 250.0  # dollars below the ask


def _event_payload(base: Path, event: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads((base / event["payload_ref"]).read_text())


def collect_states(live_root: Path) -> list[dict[str, Any]]:
    """Every commit-phase request with a hold, from the completed cells of a run root."""
    states: list[dict[str, Any]] = []
    for path in sorted(live_root.glob("world_*__*.json")):
        row = json.loads(path.read_text())
        if row.get("status") != "completed":
            continue
        world = lemons.make_lemons_world(
            6, 4, int(row["world_seed"]), 0.6, lemon_share=0.5, lemon_loss=1000.0,
            inspection_cost=25.0, landlord_reservation=row["arm"],
        )
        attempts = glob.glob(str(path.with_name(path.stem + "_evidence") / "runplan_*/tasks/*/attempts/*/events.jsonl"))
        if len(attempts) != 1:
            continue
        base = Path(attempts[0]).parent
        seen: set[tuple[int, int]] = set()
        for line in Path(attempts[0]).read_text().splitlines():
            event = json.loads(line)
            if event["event_type"] != "provider_call_started":
                continue
            request = _event_payload(base, event)["request"]
            body = json.loads(request["input_text"])
            if body.get("phase_id") != "commit":
                continue
            observation = body["observation"]
            hold = observation.get("active_hold")
            key = (int(observation["tenant_id"]), int(observation["round_index"]))
            if not hold or key in seen:
                continue
            seen.add(key)
            listing = int(hold["listing_id"])
            informed = listing in {int(item["listing_id"]) for item in observation["inspections"]}
            rent = float(hold["rent"])
            states.append({
                "state_id": f"{path.stem}:t{key[0]}:r{key[1]}", "arm": row["arm"],
                "world_seed": int(row["world_seed"]), "informed": informed,
                "rent_below_ask": round(float(world.ask[listing]) - rent, 2),
                "below_floor": row["arm"] == "true_cost" and not informed
                and rent < sound_floor(world, listing) - 1e-6,
                "quality": "lemon" if world.quality[listing] == lemons.LEMON else "sound",
                "request": request,
            })
    return states


def choose(states: Sequence[Mapping[str, Any]], informed_sample: int, seed: int = 20261001) -> list[Mapping[str, Any]]:
    """All blind states, and a seeded sample of the informed ones as a collateral-damage check."""
    blind = [s for s in states if not s["informed"]]
    informed = sorted((s for s in states if s["informed"]), key=lambda s: s["state_id"])
    random.Random(seed).shuffle(informed)
    return blind + informed[:informed_sample]


def _request(state: Mapping[str, Any], variant: str, sample: int) -> ProviderRequest:
    names = {f.name for f in dataclasses.fields(ProviderRequest)}
    base = ProviderRequest(**{k: v for k, v in state["request"].items() if k in names})
    return dataclasses.replace(
        base, instructions=base.instructions + VARIANTS[variant], seed=(base.seed or 0) + 1000 * (sample + 1),
        max_cost_usd=0.05,
    )


def _decision(text: str) -> str | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value.get("decision") if isinstance(value, dict) else None


async def run_probe(
    states: Sequence[Mapping[str, Any]], client: Any, *, samples: int, concurrency: int,
    variants: Sequence[str] = tuple(VARIANTS), budget_usd: float = 2.0,
) -> list[dict[str, Any]]:
    gate = asyncio.Semaphore(concurrency)
    spent = 0.0
    results: list[dict[str, Any]] = []

    async def one(state: Mapping[str, Any], variant: str, sample: int) -> None:
        nonlocal spent
        if spent > budget_usd:
            results.append({"state_id": state["state_id"], "variant": variant, "sample": sample, "decision": None, "error": "budget"})
            return
        async with gate:
            try:
                result = await client.complete(_request(state, variant, sample))
                spent += float(result.cost_usd or 0.0)
                decision, error = _decision(result.output_text or ""), None if (result.output_text or "").strip() else "empty"
            except Exception as exc:  # a failed call is typed missingness, never a decision
                decision, error = None, getattr(exc, "condition", type(exc).__name__)
        results.append({"state_id": state["state_id"], "variant": variant, "sample": sample, "decision": decision, "error": error})

    await asyncio.gather(*(one(s, v, k) for s in states for v in variants for k in range(samples)))
    return results


def group_of(state: Mapping[str, Any]) -> str:
    if state["informed"]:
        return "informed hold"
    if state["arm"] == "pooled":
        return "blind hold, pooled arm"
    return "blind hold below the sound floor" if state["below_floor"] else "blind hold at or above the floor"


def summarize(states: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id = {s["state_id"]: s for s in states}
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for item in results:
        state = by_id[item["state_id"]]
        cell = table.setdefault(group_of(state), {}).setdefault(item["variant"], {"calls": 0, "signed": 0, "failed": 0})
        cell["calls"] += 1
        if item["decision"] is None:
            cell["failed"] += 1
        else:
            cell["signed"] += item["decision"] == "sign"
    for variants in table.values():
        for cell in variants.values():
            answered = cell["calls"] - cell["failed"]
            cell["sign_rate"] = round(cell["signed"] / answered, 3) if answered else None
    deep: dict[str, dict[str, Any]] = {}
    for item in results:
        state = by_id[item["state_id"]]
        if state["informed"] or state["arm"] != "true_cost" or item["decision"] is None:
            continue
        bucket = "deeper than $250" if state["rent_below_ask"] > DEEP else "within $250"
        cell = deep.setdefault(bucket, {}).setdefault(item["variant"], [0, 0])
        cell[0] += 1
        cell[1] += item["decision"] == "sign"
    return {
        "states": len(states),
        "groups": {name: sum(1 for s in states if group_of(s) == name) for name in table},
        "sign_rate_by_group_and_variant": table,
        "sign_rate_blind_true_cost_by_depth": {
            bucket: {v: {"calls": c[0], "sign_rate": round(c[1] / c[0], 3)} for v, c in variants.items()}
            for bucket, variants in deep.items()
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("live_root", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="where to write the probe JSON (not evidence/)")
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--informed-sample", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--budget-usd", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true", help="count states and calls, make none")
    args = parser.parse_args(argv)
    chosen = choose(collect_states(args.live_root), args.informed_sample)
    calls = len(chosen) * len(VARIANTS) * args.samples
    print(json.dumps({"states": len(chosen), "calls": calls,
                      "groups": {g: sum(1 for s in chosen if group_of(s) == g) for g in sorted({group_of(s) for s in chosen})}}))
    if args.dry_run:
        return 0
    results = asyncio.run(run_probe(chosen, OpenRouterChatClient(), samples=args.samples,
                                    concurrency=args.concurrency, budget_usd=args.budget_usd))
    report = {"schema_version": "aeread.housing_price_disclosure_probe/0.1", "status": "diagnostic_not_evidence",
              "variants": VARIANTS, "summary": summarize(chosen, results), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps(report["summary"], indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
