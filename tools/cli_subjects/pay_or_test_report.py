"""What each subject gave up, action by action, on the pay-or-test pack.

    PYTHONPATH=src python tools/cli_subjects/pay_or_test_report.py <runs/procurement_allocation> [--gate] [--json out.json]

The primary number is decision loss: for every action a subject took, the
best informed policy's value at that point less the value of the action taken,
summed over the episode. It is zero for a subject that always took a best
action and does not depend on how a tested supplier turned out. Scripted rules
are shown beside it with their exact expected loss on the same worlds.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any, Sequence

from aeread_families.procurement_allocation import pay_or_test_case_matrix as pack_module
from aeread_families.procurement_allocation.pay_or_test_reference import score_actions

ROOT_PREFIX = "pay_or_test_v1_accounting_"
SMALL_USD = 1.0
RESAMPLES = 10_000


def interval(values: Sequence[float], seed: int = 20261009) -> tuple[float, float, float]:
    """Mean and a 95% percentile interval from resampling worlds."""
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(RESAMPLES))
    return (sum(values) / n, means[int(0.025 * RESAMPLES)], means[int(0.975 * RESAMPLES) - 1])


def load_pack() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((pack_module.PACK_ROOT / "pack.json").read_text(encoding="utf-8"))
    payloads = {json.loads(p.read_text(encoding="utf-8"))["case_id"]: json.loads(p.read_text(encoding="utf-8"))["payload"]
                for p in pack_module.case_paths()}
    return manifest, payloads


def score_run(root: Path, manifest: dict[str, Any], payloads: dict[str, Any]) -> dict[str, Any]:
    artifact = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    by_case = {w["case_id"]: w for w in manifest["worlds"]}
    worlds, failed = [], []
    for row in artifact["rows"]:
        world = by_case[row["case_id"]]
        if row.get("status") != "completed":
            failed.append({"slug": world["slug"], "failure": row.get("failure_condition") or row.get("error_type")})
            continue
        scored = score_actions(payloads[row["case_id"]], row["action_trace"])
        replayed = float(scored["outcome"]["contribution_margin_usd"])
        if abs(replayed - float(row["contribution_margin_usd"])) > 1e-6:
            raise RuntimeError(f"replay of {world['slug']} in {root.name} gives {replayed}, the run recorded {row['contribution_margin_usd']}")
        newcomers = {n["supplier_id"] for n in world["newcomers"]}
        kinds = {n["supplier_id"]: n["type"] for n in world["newcomers"]}
        first_newcomer = next((s["supplier_id"] for s in scored["steps"] if s["supplier_id"] in newcomers), None)
        samples = [s["supplier_id"] for s in scored["steps"] if s["action"] == "request_sample"]
        recorded = world["established"]["supplier_id"]
        touched = [sid for sid in dict.fromkeys(s["supplier_id"] for s in scored["steps"]) if sid in newcomers]
        worlds.append({
            "slug": world["slug"], "move": world["move"], "clock": world["clock"],
            "decision_loss_usd": scored["decision_loss_usd"], **{f"loss_{k}_usd": v for k, v in scored["loss_by_part_usd"].items()},
            "margin_usd": replayed, "regret_to_upper_bound_usd": float(row["regret_to_upper_bound_usd"]),
            "best_policy_value_usd": world["best_policy_value_usd"],
            "best_policy_margin_usd": world["realized"]["best_policy"]["margin_usd"],
            "decision": row["decision"], "feasible_award": bool(row["feasible_award"]),
            "actions": len(scored["steps"]), "requests": scored["requests"], "newcomers_touched": scored["newcomers_touched"],
            "first_newcomer": first_newcomer,
            "first_newcomer_is_cheapest": first_newcomer == world["cheapest_newcomer"] if first_newcomer else None,
            "first_newcomer_is_best_test": first_newcomer == world["best_single_test"] if first_newcomer else None,
            # Sampled the recorded supplier before settling any newcomer: the fallback bought up front.
            "secured_recorded_first": bool(samples) and samples[0] == recorded and any(s in newcomers for s in samples[1:] + touched),
            "paid_without_testing": not touched,
            "first_newcomer_was_bad": kinds[touched[0]] != "good" if touched else None,
            "counters": sum(s["action"] == "counter_offer" for s in scored["steps"]),
            "strays": sum(s["action"] in ("inquire", "counter_offer", "check_award") for s in scored["steps"]),
            "trace": " ".join(_short(s) for s in scored["steps"]),
            "cost_usd": float(row.get("cost_usd") or 0.0), "seconds": float(row.get("elapsed_seconds") or 0.0),
        })
    return {"campaign_id": artifact["plan"]["campaign_id"], "model": artifact["plan"]["model"], "halted": artifact.get("halted"),
            "worlds": worlds, "failed": failed}


def _short(step: dict[str, Any]) -> str:
    code = {"request_quote": "q", "request_sample": "s", "submit_award": "AWARD", "defer": "DEFER", "inquire": "inq",
            "counter_offer": "ctr", "check_award": "chk"}.get(step["action"], str(step["action"]))
    who = (step["supplier_id"] or "").rsplit("_", 1)[-1]
    lost = f"(-{step['loss_usd']:.0f})" if step["loss_usd"] >= SMALL_USD else ""
    return f"{code}{':' + who if who else ''}{lost}"


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    worlds = run["worlds"]
    loss = [w["decision_loss_usd"] for w in worlds]
    mean, low, high = interval(loss)
    cells: dict[str, Any] = {}
    for move, clock in pack_module.CELLS:
        mine = [w for w in worlds if (w["move"], w["clock"]) == (move, clock)]
        if mine:
            cells[f"{move}/{clock}"] = {
                "n": len(mine), "decision_loss_usd": round(statistics.fmean(w["decision_loss_usd"] for w in mine), 1),
                "no_loss": sum(w["decision_loss_usd"] < SMALL_USD for w in mine),
                "tested_a_newcomer": sum(w["newcomers_touched"] > 0 for w in mine),
            }
    tested = [w for w in worlds if w["first_newcomer"]]
    return {
        "campaign_id": run["campaign_id"], "model": run["model"], "worlds": len(worlds), "failed_cells": len(run["failed"]),
        "decision_loss_usd": {"mean": round(mean, 1), "low": round(low, 1), "high": round(high, 1)},
        "worlds_with_no_loss": sum(x < SMALL_USD for x in loss),
        "loss_by_part_usd": {part: round(statistics.fmean(w[f"loss_{part}_usd"] for w in worlds), 1)
                             for part in ("requests", "strays", "walk_away", "award_timing", "award_terms")},
        "test_worlds": _test_worlds([w for w in worlds if w["move"].startswith("test")]),
        "pay_worlds": {"n": sum(w["move"].startswith("pay") for w in worlds),
                       "paid_without_testing": sum(w["paid_without_testing"] for w in worlds if w["move"].startswith("pay")),
                       "decision_loss_usd": round(statistics.fmean(w["decision_loss_usd"] for w in worlds if w["move"].startswith("pay")), 1)},
        "counter_offers": {"total": sum(w["counters"] for w in worlds), "worlds": sum(w["counters"] > 0 for w in worlds),
                           "largest_stray_loss_usd": round(max(w["loss_strays_usd"] for w in worlds), 1)},
        "share_of_best_policy_value": round(1.0 - sum(loss) / sum(w["best_policy_value_usd"] for w in worlds), 3),
        "margin_usd": round(statistics.fmean(w["margin_usd"] for w in worlds), 1),
        "best_policy_margin_usd": round(statistics.fmean(w["best_policy_margin_usd"] for w in worlds), 1),
        "regret_to_upper_bound_usd": round(statistics.fmean(w["regret_to_upper_bound_usd"] for w in worlds), 1),
        "no_supply": sum(not w["feasible_award"] for w in worlds),
        "tested_a_newcomer": len(tested),
        "first_newcomer_was_cheapest": sum(bool(w["first_newcomer_is_cheapest"]) for w in tested),
        "first_newcomer_was_best_test": sum(bool(w["first_newcomer_is_best_test"]) for w in tested),
        "newcomers_touched_per_world": round(statistics.fmean(w["newcomers_touched"] for w in worlds), 2),
        "stray_actions": sum(w["strays"] for w in worlds),
        "cost_usd": round(sum(w["cost_usd"] for w in worlds), 2),
        "by_cell": cells,
    }


def _test_worlds(worlds: list[dict[str, Any]]) -> dict[str, Any]:
    if not worlds:
        return {}
    after_bad = [w for w in worlds if w["first_newcomer_was_bad"]]
    return {
        "n": len(worlds),
        "decision_loss_usd": round(statistics.fmean(w["decision_loss_usd"] for w in worlds), 1),
        "paid_without_testing": sum(w["paid_without_testing"] for w in worlds),
        "first_newcomer_was_best_test": sum(bool(w["first_newcomer_is_best_test"]) for w in worlds),
        "secured_recorded_first": sum(w["secured_recorded_first"] for w in worlds),
        "first_newcomer_was_bad": len(after_bad),
        "then_stopped_where_another_test_paid": sum(w["newcomers_touched"] == 1 and w["loss_award_timing_usd"] >= SMALL_USD for w in after_bad),
        "then_tried_another": sum(w["newcomers_touched"] > 1 for w in after_bad),
        "award_timing_loss_usd": round(statistics.fmean(w["loss_award_timing_usd"] for w in worlds), 1),
    }


def rules_beside(manifest: dict[str, Any], slugs: set[str]) -> dict[str, Any]:
    worlds = [w for w in manifest["worlds"] if w["slug"] in slugs]
    out: dict[str, Any] = {}
    for name in worlds[0]["rule_value_usd"]:
        out[name] = {
            "expected_loss_usd": round(statistics.fmean(w["best_policy_value_usd"] - w["rule_value_usd"][name] for w in worlds), 1),
            "pay_worlds": round(statistics.fmean(w["best_policy_value_usd"] - w["rule_value_usd"][name] for w in worlds if w["move"].startswith("pay")), 1),
            "test_worlds": round(statistics.fmean(w["best_policy_value_usd"] - w["rule_value_usd"][name] for w in worlds if w["move"].startswith("test")), 1),
        }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--gate", action="store_true", help="read the one-world gates instead of the panels")
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args(argv)
    manifest, payloads = load_pack()
    roots = sorted(p for p in arguments.runs.glob(f"{ROOT_PREFIX}*") if (p / "summary.json").exists()
                   and (("_gate_" in p.name) == arguments.gate))
    runs = {root.name.removeprefix(ROOT_PREFIX): score_run(root, manifest, payloads) for root in roots}
    report: dict[str, Any] = {"subjects": {name: summarize(run) for name, run in runs.items() if run["worlds"]}}
    slugs = set.intersection(*({w["slug"] for w in run["worlds"]} for run in runs.values())) if runs else set()
    if slugs:
        report["rules_on_the_same_worlds"] = rules_beside(manifest, slugs)
    names = list(runs)
    report["paired_differences_usd"] = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            la = {w["slug"]: w["decision_loss_usd"] for w in runs[a]["worlds"]}
            lb = {w["slug"]: w["decision_loss_usd"] for w in runs[b]["worlds"]}
            common = sorted(set(la) & set(lb))
            if common:
                mean, low, high = interval([la[s] - lb[s] for s in common])
                report["paired_differences_usd"][f"{a} minus {b}"] = {"n": len(common), "mean": round(mean, 1), "low": round(low, 1), "high": round(high, 1)}
    print(json.dumps(report, indent=1))
    print()
    for name, run in runs.items():
        print(name)
        for w in run["worlds"]:
            print(f"  {w['slug']:26s} loss {w['decision_loss_usd']:7.1f}  margin {w['margin_usd']:7.1f} (best policy {w['best_policy_margin_usd']:7.1f})  {w['trace']}")
        for f in run["failed"]:
            print(f"  {f['slug']:26s} FAILED {f['failure']}")
    if arguments.json:
        arguments.json.write_text(json.dumps({"report": report, "runs": runs}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
