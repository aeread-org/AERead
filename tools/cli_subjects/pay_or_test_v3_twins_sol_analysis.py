"""Sol on the v3 odds twins: the declared read-out (``pay_or_test_v3_twins_sol_plan.md``), committed before any play.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v3_twins_sol_analysis.py \\
        SOL_TWINS_ROOT SOL_CONFIRM_ROOT > analysis.json

Every play is replayed from its public trace and priced by ``pay_or_test_v3_pilot_report.read``. Descriptive only.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from scipy import stats

import pay_or_test_v3_pilot_report as report
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module

RULES = ("one_step_value", "cheapest_sample_first", "two_step_value")


def _shares(read: dict) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for play in read["plays_detail"]:
        by.setdefault(play["slug"], []).append(play["gap_closed"])
    return {slug: statistics.fmean(v) for slug, v in sorted(by.items())}


def main(twins_root: str, confirm_root: str) -> dict:
    twins = json.loads((pack_module.pack_root(pack_module.DIAGNOSTIC_PACK_ID) / "pack.json").read_text())["worlds"]
    newcomers = {w["slug"]: {n["supplier_id"].replace("driver_board_", "") for n in w["newcomers"]} for w in twins}
    sol_twins, sol_confirm = report.read(Path(twins_root)), report.read(Path(confirm_root))
    plays = sol_twins["plays_detail"]
    touched = sum(any(t.split(":")[0] in ("quote", "sample", "lookup") and t.split(":")[1] in newcomers[p["slug"]]
                      for t in p["trace"].split()) for p in plays)
    shares = _shares(sol_twins)
    values = list(shares.values())
    n, mean, sd = len(values), statistics.fmean(values), statistics.stdev(values)
    half = stats.t.ppf(0.975, n - 1) * sd / n ** 0.5
    rules = {r: round(statistics.fmean(1 - w["rule_loss_usd"][r] / w["rule_loss_usd"]["pay_premium"] for w in twins), 4)
             for r in RULES}
    original = _shares(sol_confirm)
    paired = [shares[s] - original[s] for s in shares if s in original]
    return {
        "plays": sol_twins["plays"], "failed": sol_twins["failed"], "worlds": n,
        "plays_touching_a_newcomer": touched,
        "first_information_request_to_a_newcomer": sol_twins["by_kind"]["myopic_pays"]["first_info_to_newcomer"],
        "gap_closed_mean": round(mean, 4), "t_ci95": [round(mean - half, 4), round(mean + half, 4)],
        "decision_loss_mean_usd": sol_twins["by_kind"]["myopic_pays"]["decision_loss_mean_usd"],
        "pay_premium_loss_mean_usd": sol_twins["by_kind"]["myopic_pays"]["pay_premium_loss_mean_usd"],
        "rules_gap_closed_on_twins": rules,
        "paired_twin_minus_original": {"worlds": len(paired), "mean": round(statistics.fmean(paired), 4),
                                       "sd": round(statistics.stdev(paired), 4)},
        "per_world": {s: round(v, 4) for s, v in shares.items()},
    }


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2]), indent=1))
