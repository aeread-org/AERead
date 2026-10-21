"""Pay or test v3, the frozen control: the declared read-out (``pay_or_test_v3_control_plan.md``, Section 4).

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v3_control_analysis.py \\
        --probe LUNA_PROBE_ROOT GEMINI_PROBE_ROOT [--control CONTROL_ROOT --sol SOL_CONFIRM_ROOT] > analysis.json

Every play is replayed and priced by ``pay_or_test_v3_pilot_report.read``. Phase A counts each candidate's plays that
touch a new listing and applies the plan's selection rule. Phase B reads the control's three plays of each declared
world for the two grounds of the measured-headroom check: degenerate (decision loss within $0.01 at every seed) and
trivial (a screened deterministic rule worth at least the control's best play, within $0.01).
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import pay_or_test_v3_pilot_report as report
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module
from aeread_families.procurement_allocation import pay_or_test_v3_reference as reference

CANDIDATE_ORDER = ("gpt6_luna_high", "gemini38_flash_high")
QUALIFY_MIN_TOUCHING, QUALIFY_MAX_FAILED = 4, 1
TOLERANCE_USD = 0.01
#: The set admission screened (``pay_or_test_v3_case_matrix.ADMISSION_RULES``): the one-step rule, the four fixed rules
#: and the kind-blind shortcut.
SCREENED = tuple(pack_module.ADMISSION_RULES)
BESIDE = ("probe_same_kind_first", "two_step_value")


def _worlds(split: str) -> dict[str, dict]:
    return {w["slug"]: w for w in json.loads((pack_module.pack_root(split) / "pack.json").read_text())["worlds"]}


def _touches(play: dict, world: dict) -> bool:
    newcomers = {n["supplier_id"].replace("driver_board_", "") for n in world["newcomers"]}
    return any(t.split(":")[0] in ("quote", "sample", "lookup") and t.split(":")[1] in newcomers for t in play["trace"].split())


def phase_a(roots: list[Path]) -> dict:
    out = {}
    for root in roots:
        read = report.read(root)
        subject = next(name for name in CANDIDATE_ORDER if name in read["campaign_id"])
        worlds = _worlds(pack_module.PILOT_PACK_ID)
        touching = sum(_touches(p, worlds[p["slug"]]) for p in read["plays_detail"])
        out[subject] = {"campaign_id": read["campaign_id"], "plays": read["plays"], "failed": len(read["failed"]),
                        "plays_touching_a_newcomer": touching,
                        "qualifies": touching >= QUALIFY_MIN_TOUCHING and len(read["failed"]) <= QUALIFY_MAX_FAILED}
    qualifying = [s for s in CANDIDATE_ORDER if out.get(s, {}).get("qualifies")]
    chosen = max(qualifying, key=lambda s: (out[s]["plays_touching_a_newcomer"], -CANDIDATE_ORDER.index(s))) if qualifying else None
    return {"candidates": out, "control": chosen,
            "rule": f"touches a newcomer in at least {QUALIFY_MIN_TOUCHING} of 12 plays with at most {QUALIFY_MAX_FAILED} "
                    "failed cell; the qualifying candidate with more such plays, ties to the first in order"}


def phase_b(control_root: Path, sol_root: Path | None) -> dict:
    worlds = _worlds(pack_module.CONFIRM_PACK_ID)
    read = report.read(control_root)
    plays: dict[str, list[dict]] = {}
    for p in read["plays_detail"]:
        plays.setdefault(p["slug"], []).append(p)
    sol = {}
    if sol_root is not None:
        for p in report.read(sol_root)["plays_detail"]:
            sol.setdefault(p["slug"], []).append(p["gap_closed"])
    per_world, degenerate, trivial = {}, [], []
    for slug in sorted(worlds, key=lambda s: int(s.split("__")[1])):
        w, mine = worlds[slug], plays.get(slug, [])
        losses = [p["decision_loss_usd"] for p in mine]
        best_value = w["best_policy_value_usd"]
        control_best = best_value - min(losses) if losses else None
        screened_best = max(w["rule_value_usd"][r] for r in SCREENED)
        is_degenerate = len(losses) >= 2 and max(losses) - min(losses) <= TOLERANCE_USD
        is_trivial = control_best is not None and screened_best >= control_best - TOLERANCE_USD
        if is_degenerate:
            degenerate.append(slug)
        if is_trivial:
            trivial.append(slug)
        shares = [p["gap_closed"] for p in mine]
        per_world[slug] = {
            "plays": len(mine), "gap_closed_by_seed": [round(s, 4) for s in shares],
            "within_world_sd": round(statistics.stdev(shares), 4) if len(shares) >= 2 else None,
            "decision_loss_by_seed": [round(x, 2) for x in losses], "control_best_value_usd": round(control_best, 2) if losses else None,
            "screened_rule_best_value_usd": round(screened_best, 2),
            "screened_rule_best": max(SCREENED, key=lambda r: w["rule_value_usd"][r]),
            "beside": {r: round(w["rule_value_usd"][r], 2) for r in BESIDE},
            "degenerate": is_degenerate, "trivial": is_trivial,
            "sol_gap_closed": [round(x, 4) for x in sol.get(slug, [])]}
    meets = [s for s in per_world if not per_world[s]["degenerate"] and not per_world[s]["trivial"] and per_world[s]["plays"] == 3]
    world_means = [statistics.fmean(v["gap_closed_by_seed"]) for v in per_world.values() if v["gap_closed_by_seed"]]
    return {"campaign_id": read["campaign_id"], "plays": read["plays"], "failed": read["failed"],
            "control_gap_closed_mean": round(statistics.fmean(world_means), 4) if world_means else None,
            "plays_touching_a_newcomer": sum(_touches(p, worlds[p["slug"]]) for p in read["plays_detail"]),
            "degenerate_worlds": degenerate, "trivial_worlds": trivial,
            "worlds_meeting_the_ground": len(meets), "gate_1_measured_headroom": "met" if len(meets) == 20 else "partial",
            "per_world": per_world}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--probe", type=Path, nargs="+", required=True)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--sol", type=Path)
    args = parser.parse_args()
    out = {"plan": "docs/families/procurement-allocation/pay_or_test_v3_control_plan.md", "phase_a": phase_a(args.probe)}
    if args.control:
        out["phase_b"] = phase_b(args.control, args.sol)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
