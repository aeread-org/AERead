"""The price pilot's ex-ante endpoint: was each signing worth it, and what did the landlord's reply say?

Realized net payoff mixes the tenant's decisions with the lemon draw, and in the
price condition it hides a second thing. The ``true_cost`` landlord reserves on a
lemon's own cost, so it agrees to a rent below the lowest rent a sound listing's
landlord would accept. A hold at such a rent proves the listing is a lemon, while
the tenant's stated odds (``(lemon_count - found) / (listings - inspected)``) do
not move. This module scores every commit decision twice:

* at the **stated odds**, exactly as ``lemons_gap`` does, which separates the
  tenant's decision from the lemon draw and sums to the realized net payoff;
* at the **response-conditioned odds**, where a hold below the sound listing's
  floor is a certain lemon. The difference is what reading the reply was worth.

The response-conditioned score is an evaluator's benchmark, not a claim about what
a tenant could infer: the floor is computed from the sound cost, which no tenant
sees. It prices the information the landlord's rule leaked.

Nothing here calls a provider. A cell is scored from its outcome (the
``commit_decisions`` the environment recorded), from a published row that carries
them, or from the sealed events of a run root.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import lemons, lemons_design
from .price_bargaining import LANDLORD_MARGIN

SCHEMA_VERSION = "aeread.housing_price_endpoint/0.1"
PARTS = ("informed_leases", "blind_good_bets", "blind_bad_bets", "lemon_draws", "inspection_spend")
OUTCOME_FACTS = ("commit_decisions", "inspection_count", "tenant_inspection_spend", "tenant_net_total")
TOLERANCE = 1e-6


def sound_floor(world: lemons.LemonsWorld, listing_id: int, margin: float = LANDLORD_MARGIN) -> float:
    """The lowest rent a sound listing's landlord agrees to under the price rule.

    ``price_bargaining.landlord_action`` counters at the reservation plus the
    margin, capped by the ask, and accepts any offer at or above that target. For
    a sound listing the reservation is its cost.
    """
    cost = float(world.sound_costs[listing_id])
    return round(max(cost, min(float(world.ask[listing_id]), cost + margin)), 2)


def score_decisions(
    world: lemons.LemonsWorld, decisions: Sequence[Mapping[str, Any]], margin: float = LANDLORD_MARGIN
) -> list[dict[str, Any]]:
    """One row per commit decision, scored at the stated and the response-conditioned odds."""
    loss = float(world.lemon_loss)
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        tenant, listing = int(decision["tenant_id"]), int(decision["listing_id"])
        rent, stated = float(decision["rent"]), float(decision["expected_value"])
        informed = bool(decision["informed"])
        sound_value = float(world.values_if_sound[tenant][listing])
        true_value = float(world.values[tenant][listing])
        floor = sound_floor(world, listing, margin)
        # Only the arm whose landlord reserves on a lemon's own cost can reveal one.
        revealed = (
            world.landlord_reservation == "true_cost" and not informed and rent < floor - TOLERANCE
        )
        # A lemon is certain once the hold is below what a sound listing would take.
        response = stated if informed else (sound_value - loss if revealed else stated)
        rows.append({
            "tenant_id": tenant, "listing_id": listing, "round_index": int(decision["round_index"]),
            "decision": decision["decision"], "informed": informed, "quality": decision["quality"],
            "rent": rent, "ask": float(world.ask[listing]), "sound_floor": floor,
            "rent_below_ask": round(float(world.ask[listing]) - rent, 2),
            "reply_revealed_lemon": revealed,
            "lemon_probability_stated": 0.0 if informed else round((sound_value - stated) / loss, 6),
            "expected_value_stated": stated, "expected_value_response": round(response, 2),
            "true_value": true_value,
            "worth_it_stated": stated >= rent, "worth_it_response": response >= rent,
        })
    return rows


def score_cell(
    outcome: Mapping[str, Any], *, world_seed: int, arm: str, margin: float = LANDLORD_MARGIN,
    replicate_index: int = 0,
) -> dict[str, Any]:
    """Score one cell. ``outcome`` needs the keys in ``OUTCOME_FACTS``."""
    world = lemons.make_lemons_world(
        6, 4, world_seed, 0.6, lemon_share=0.5, lemon_loss=1000.0,
        inspection_cost=25.0, landlord_reservation=arm,
    )
    rows = score_decisions(world, outcome["commit_decisions"], margin)
    parts = {name: 0.0 for name in PARTS}
    leak = 0.0
    for row in rows:
        if row["decision"] != "sign":
            continue
        surplus_true = row["true_value"] - row["rent"]
        if row["informed"]:
            parts["informed_leases"] += surplus_true
            continue
        key = "blind_good_bets" if row["expected_value_stated"] >= row["rent"] else "blind_bad_bets"
        parts[key] += row["expected_value_stated"] - row["rent"]
        parts["lemon_draws"] += row["true_value"] - row["expected_value_stated"]
        leak += row["expected_value_stated"] - row["expected_value_response"]
    spend = outcome["tenant_inspection_spend"]
    # The environment records spend per tenant seat; a flat number is accepted too.
    parts["inspection_spend"] = -float(sum(spend.values()) if isinstance(spend, Mapping) else spend)
    net = float(outcome["tenant_net_total"])
    residual = net - sum(parts.values())
    signed_blind = [r for r in rows if r["decision"] == "sign" and not r["informed"]]
    return {
        "world_seed": world_seed, "arm": arm, "replicate_index": replicate_index,
        # The favourite's quality, kept as a covariate: the panel is consecutive seeds with
        # no admission gate, so it is balanced only by chance (HL-D-03).
        "stratum": lemons_design.stratum_of(world),
        "net_realized": round(net, 2),
        "net_expected_stated_odds": round(net - parts["lemon_draws"], 2),
        "net_expected_response_odds": round(net - parts["lemon_draws"] - leak, 2),
        "parts": {key: round(value, 2) for key, value in parts.items()},
        "residual": round(residual, 6),
        "reply_leak_expected_loss": round(leak, 2),
        "signed_blind": len(signed_blind),
        "signed_blind_after_revealing_reply": sum(r["reply_revealed_lemon"] for r in signed_blind),
        "signed_informed": sum(r["decision"] == "sign" and r["informed"] for r in rows),
        "walked_revealing_reply": sum(r["reply_revealed_lemon"] and r["decision"] == "walk" for r in rows),
        "decisions": rows,
    }


def outcome_from_evidence_root(cell_evidence_root: Path) -> dict[str, Any]:
    """The family outcome sealed in a cell's event log (no provider, no replay)."""
    attempts = sorted(glob.glob(str(cell_evidence_root / "runplan_*/tasks/*/attempts/*/events.jsonl")))
    if len(attempts) != 1:
        raise ValueError(f"expected one attempt under {cell_evidence_root}, found {len(attempts)}")
    base = Path(attempts[0]).parent
    for line in Path(attempts[0]).read_text().splitlines():
        event = json.loads(line)
        if event["event_type"] == "family_outcome_recorded":
            return json.loads((base / event["payload_ref"]).read_text())["outcome"]
    raise ValueError("no family outcome in the event log")


METRICS = ("net_realized", "net_expected_stated_odds", "net_expected_response_odds")


def replicate_noise(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """How much a cell and the arm contrast move between replicates, against how much they move between worlds.

    Needs two or more replicates per (world, arm). The contrast is ``true_cost`` minus
    ``pooled`` within one world and replicate. Its variance across worlds is the
    variance of the world means less the replicate noise carried in them
    (``sigma2 / K``); the K rule in Miller (2024) then reads ``sigma2`` against that.
    """
    groups: dict[tuple[int, str], list[Mapping[str, Any]]] = {}
    for cell in cells:
        groups.setdefault((cell["world_seed"], cell["arm"]), []).append(cell)
    repeated = {key: rows for key, rows in groups.items() if len(rows) >= 2}
    if not repeated:
        return None
    out: dict[str, Any] = {
        "cells_with_replicates": len(repeated),
        "cells_with_identical_replicates": sum(
            len({row["net_realized"] for row in rows}) == 1 for rows in repeated.values()
        ),
        "within_cell_sd": {
            metric: round(math.sqrt(statistics.fmean(
                statistics.variance([row[metric] for row in rows]) for rows in repeated.values()
            )), 2)
            for metric in METRICS
        },
        "contrast": {},
    }
    worlds = sorted({seed for seed, _ in groups})
    for metric in METRICS:
        per_world: list[list[float]] = []
        for seed in worlds:
            true_cost = {r["replicate_index"]: r[metric] for r in groups.get((seed, "true_cost"), [])}
            pooled = {r["replicate_index"]: r[metric] for r in groups.get((seed, "pooled"), [])}
            shared = sorted(set(true_cost) & set(pooled))
            if len(shared) >= 2:
                per_world.append([true_cost[i] - pooled[i] for i in shared])
        if len(per_world) < 2:
            continue
        sigma2 = statistics.fmean(statistics.variance(values) for values in per_world)
        k = statistics.fmean(len(values) for values in per_world)
        world_means = [statistics.fmean(values) for values in per_world]
        signal = max(statistics.variance(world_means) - sigma2 / k, 0.0)
        out["contrast"][metric] = {
            "worlds": len(per_world), "replicates": round(k, 2),
            "replicate_sd_of_contrast": round(math.sqrt(sigma2), 2),
            "world_sd_of_true_contrast": round(math.sqrt(signal), 2),
            "sigma2_over_world_signal": round(sigma2 / signal, 2) if signal > 0 else None,
            "mean_contrast": round(statistics.fmean(world_means), 2),
            "sd_of_world_means": round(statistics.stdev(world_means), 2),
        }
    return out


def score_run(live_root: Path, margin: float = LANDLORD_MARGIN) -> dict[str, Any]:
    """Score every completed cell of a run root, and pair the two arms world by world and replicate."""
    cells: list[dict[str, Any]] = []
    for path in sorted(live_root.glob("world_*__*.json")):
        row = json.loads(path.read_text())
        if row.get("status") != "completed":
            continue
        facts = row.get("outcome_facts")
        outcome = facts if facts else outcome_from_evidence_root(
            path.with_name(path.stem + "_evidence")
        )
        cells.append(score_cell(
            outcome, world_seed=int(row["world_seed"]), arm=row["arm"], margin=margin,
            replicate_index=int(row.get("replicate_index", 0)),
        ))
    by_key: dict[tuple[int, int], dict[str, Mapping[str, Any]]] = {}
    for cell in cells:
        by_key.setdefault((cell["world_seed"], cell["replicate_index"]), {})[cell["arm"]] = cell
    paired = []
    for (seed, replicate), arms in sorted(by_key.items()):
        if {"true_cost", "pooled"} <= set(arms):
            true_cost, pooled = arms["true_cost"], arms["pooled"]
            paired.append({
                "world_seed": seed, "replicate_index": replicate,
                **{f"{key}_true_cost_minus_pooled": round(true_cost[key] - pooled[key], 2) for key in METRICS},
            })
    value_keys = [key for key in (paired[0] if paired else {}) if key not in ("world_seed", "replicate_index")]
    return {
        "schema_version": SCHEMA_VERSION,
        "cells": cells,
        "paired_arm_contrast": paired,
        "paired_mean": {key: round(statistics.fmean(row[key] for row in paired), 2) for key in value_keys},
        "replicate_noise": replicate_noise(cells),
        "max_abs_residual": max((abs(c["residual"]) for c in cells), default=0.0),
    }


def pool_cells(runs: Sequence[Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Several runs' scored cells as one set of replicates.

    Each run's replicate indices are shifted past the previous run's, so a world and arm
    scored in three runs carries replicates 0, 1 and 2. The caller asserts the runs share
    model, route, controls, worlds and arms; this only relabels.
    """
    pooled: list[dict[str, Any]] = []
    offset = 0
    for cells in runs:
        pooled += [{**cell, "replicate_index": cell["replicate_index"] + offset} for cell in cells]
        offset += 1 + max((cell["replicate_index"] for cell in cells), default=-1)
    return pooled


def score_pool(live_roots: Sequence[Path], margin: float = LANDLORD_MARGIN) -> dict[str, Any]:
    """An exploratory analysis over runs of the same design under different identities.

    Not part of any identity's evidence: it combines cells whose contracts each pin their own
    replicate count, so it is declared after the fact and labelled so.
    """
    reports = [score_run(root, margin) for root in live_roots]
    cells = pool_cells([report["cells"] for report in reports])
    by_key: dict[tuple[int, int], dict[str, Mapping[str, Any]]] = {}
    for cell in cells:
        by_key.setdefault((cell["world_seed"], cell["replicate_index"]), {})[cell["arm"]] = cell
    paired = [
        {"world_seed": seed, "replicate_index": rep,
         **{f"{k}_true_cost_minus_pooled": round(arms["true_cost"][k] - arms["pooled"][k], 2) for k in METRICS}}
        for (seed, rep), arms in sorted(by_key.items()) if {"true_cost", "pooled"} <= set(arms)
    ]
    keys = [k for k in (paired[0] if paired else {}) if k not in ("world_seed", "replicate_index")]
    return {
        "schema_version": SCHEMA_VERSION, "status": "exploratory_pool",
        "roots": [str(root) for root in live_roots], "cells": cells, "paired_arm_contrast": paired,
        "paired_mean": {k: round(statistics.fmean(row[k] for row in paired), 2) for k in keys},
        "replicate_noise": replicate_noise(cells),
        "max_abs_residual": max((abs(c["residual"]) for c in cells), default=0.0),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("live_root", type=Path, nargs="+",
                        help="a price pilot run root's live/ directory; several pool as replicates (exploratory)")
    parser.add_argument("--json", action="store_true", help="print the full report")
    args = parser.parse_args(argv)
    report = score_run(args.live_root[0]) if len(args.live_root) == 1 else score_pool(args.live_root)
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
        return 0
    print(f"{'world':>7} {'rep':>3} {'arm':9} {'realized':>9} {'stated-odds':>12} {'reply-odds':>11} {'leak':>7} blind(revealed)")
    for cell in report["cells"]:
        print(f"{cell['world_seed']:>7} {cell['replicate_index']:>3} {cell['arm']:9} {cell['net_realized']:>9.1f} "
              f"{cell['net_expected_stated_odds']:>12.1f} {cell['net_expected_response_odds']:>11.1f} "
              f"{cell['reply_leak_expected_loss']:>7.1f} {cell['signed_blind']}({cell['signed_blind_after_revealing_reply']})")
    print("paired true_cost - pooled, mean over worlds:", report["paired_mean"])
    if report["replicate_noise"]:
        print("replicate noise:", json.dumps(report["replicate_noise"], sort_keys=True))
    print("largest residual:", report["max_abs_residual"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
