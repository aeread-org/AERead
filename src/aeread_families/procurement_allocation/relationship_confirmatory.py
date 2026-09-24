"""The pre-registered analysis of the repeated-sourcing confirmatory.

Written, committed and digested into both frozen plans before any cell of the
confirmatory ran, so the outcomes, their definitions and the decision rule
cannot move after the results exist. Three outcomes, each a paired contrast or
a per-model check on the plan's worlds, each with a world-clustered bootstrap:

O1  breach rate: the share of a model's completed cells with any violation
    (missed minimum service, an invalid award, a malformed action, a period
    left unplayed). Paired per world, left minus right.
O2  regret on valid orders: mean regret over a model's cells with no violation.
    Paired per world over the worlds where both models have a valid cell.
O3  against the competent observation-only baseline: `replay_deadline_aware`
    replayed on each cell's own episode case, advantage = baseline regret minus
    model regret, per model. Reported per world and as a mean.

Decision rule: a direction is supported when its 95% interval excludes zero;
otherwise the outcome is reported as not separated. Failed cells are typed
missingness, excluded and counted, never rerun. Nothing here extends beyond
the two routes, the one prompt and the generator's worlds.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping

from .headroom_screen import replay_deadline_aware

PREREGISTRATION: dict[str, Any] = {
    "id": "procurement_relationship_confirmatory_v1",
    "pack": "relationship_holdout_v1",
    "seeds": [76001, 76002, 76003, 76004, 76005],
    "outcomes": {
        "O1_breach_rate": "share of completed cells with any violation; paired per world, left minus right",
        "O2_regret_on_valid_orders": (
            "mean regret over cells with no violation; paired per world over worlds where both "
            "models have a valid cell, left minus right"
        ),
        "O3_vs_deadline_aware": (
            "per model: deadline_aware regret on the same episode case minus the model's regret; "
            "per-world means and their mean"
        ),
    },
    "secondary": ["overall paired regret (the campaign's compare step)"],
    "decision_rule": "a direction is supported when the 95% world-bootstrap interval excludes zero",
    "bootstrap": {"unit": "world", "resamples": 10_000, "seed": 20260923},
    "missingness": "failed cells are typed, excluded and counted; no cell is rerun",
    "claim_scope": "these two routes, this prompt, the generator's worlds; no statement about the models in general",
}


def _rows(run_root: Path) -> list[dict[str, Any]]:
    results = json.loads((run_root / "results.json").read_text(encoding="utf-8"))
    return [row for row in results["rows"] if row.get("status") == "completed"]


def _interval(per_world: Mapping[str, list[float]]) -> dict[str, Any]:
    worlds = sorted(slug for slug, values in per_world.items() if values)
    if not worlds:
        return {"mean": None, "interval_95": [None, None], "worlds": 0}
    means = {slug: statistics.mean(per_world[slug]) for slug in worlds}
    spec = PREREGISTRATION["bootstrap"]
    rng = random.Random(spec["seed"])
    draws = sorted(
        statistics.mean(means[worlds[rng.randrange(len(worlds))]] for _ in worlds)
        for _ in range(spec["resamples"])
    )
    lower, upper = draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]
    return {
        "mean": statistics.mean(means.values()),
        "interval_95": [lower, upper],
        "worlds": len(worlds),
        "per_world": means,
    }


def _verdict(interval: Mapping[str, Any], *, negative: str, positive: str) -> str:
    lower, upper = interval["interval_95"]
    if lower is None:
        return "not estimable"
    if upper < 0:
        return negative
    if lower > 0:
        return positive
    return "not separated"


def analyse(
    left_root: Path,
    right_root: Path,
    *,
    baseline: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] = replay_deadline_aware,
) -> dict[str, Any]:
    left_plan = json.loads((left_root / "plan.json").read_text(encoding="utf-8"))
    right_plan = json.loads((right_root / "plan.json").read_text(encoding="utf-8"))
    for plan in (left_plan, right_plan):
        if plan.get("preregistration") != PREREGISTRATION:
            raise ValueError(f"{plan['campaign_id']} was not frozen under this pre-registration")
    if left_plan["seeds"] != right_plan["seeds"] or [w["content_sha256"] for w in left_plan["worlds"]] != [
        w["content_sha256"] for w in right_plan["worlds"]
    ]:
        raise ValueError("the two plans are not paired on identical worlds and seeds")
    left, right = _rows(left_root), _rows(right_root)

    def breach(row: Mapping[str, Any]) -> float:
        return 1.0 if row.get("violations") else 0.0

    by_world: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"left": [], "right": []})
    for side, rows in (("left", left), ("right", right)):
        for row in rows:
            by_world[row["slug"]][side].append(row)

    o1 = {
        slug: [statistics.mean(map(breach, sides["left"])) - statistics.mean(map(breach, sides["right"]))]
        for slug, sides in by_world.items()
        if sides["left"] and sides["right"]
    }
    o2: dict[str, list[float]] = {}
    for slug, sides in by_world.items():
        valid_left = [row["regret_to_upper_bound_usd"] for row in sides["left"] if not row.get("violations")]
        valid_right = [row["regret_to_upper_bound_usd"] for row in sides["right"] if not row.get("violations")]
        if valid_left and valid_right:
            o2[slug] = [statistics.mean(valid_left) - statistics.mean(valid_right)]

    baseline_regret: dict[tuple[str, int], float] = {}

    def advantage(run_root: Path, row: Mapping[str, Any]) -> float:
        key = (row["slug"], int(row["seed"]))
        if key not in baseline_regret:
            payload = json.loads((run_root / "cases" / f"{row['slug']}__seed_{row['seed']}.json").read_text(encoding="utf-8"))["payload"]
            outcome = baseline(payload)
            if outcome is None:
                raise ValueError(f"deadline_aware did not complete on {key}")
            baseline_regret[key] = float(outcome["regret_to_upper_bound_usd"])
        return baseline_regret[key] - float(row["regret_to_upper_bound_usd"])

    o3 = {}
    for side, root, rows in (("left", left_root, left), ("right", right_root, right)):
        per_world: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            per_world[row["slug"]].append(advantage(root, row))
        interval = _interval(per_world)
        o3[side] = {
            **interval,
            "worlds_model_better": sum(1 for value in interval.get("per_world", {}).values() if value > 0),
            "verdict": _verdict(interval, negative="baseline better", positive="model better"),
        }

    breach_rate = {
        side: sum(map(breach, rows)) / len(rows) if rows else None for side, rows in (("left", left), ("right", right))
    }
    o1_interval, o2_interval = _interval(o1), _interval(o2)
    return {
        "preregistration": PREREGISTRATION["id"],
        "left_campaign_id": left_plan["campaign_id"],
        "right_campaign_id": right_plan["campaign_id"],
        "left_route": left_plan["route"]["model"],
        "right_route": right_plan["route"]["model"],
        "completed": {"left": len(left), "right": len(right)},
        "cells": {"left": len(left_plan["cells"]), "right": len(right_plan["cells"])},
        "O1_breach_rate": {
            "left": breach_rate["left"],
            "right": breach_rate["right"],
            "paired_difference": o1_interval,
            "verdict": _verdict(o1_interval, negative="left breaches less", positive="right breaches less"),
        },
        "O2_regret_on_valid_orders": {
            "paired_difference": o2_interval,
            "verdict": _verdict(o2_interval, negative="left lower regret", positive="right lower regret"),
        },
        "O3_vs_deadline_aware": o3,
        "claim_scope": PREREGISTRATION["claim_scope"],
    }


def write(left_root: Path, right_root: Path) -> dict[str, Any]:
    report = analyse(left_root, right_root)
    path = left_root / f"confirmatory_vs_{report['right_campaign_id']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
