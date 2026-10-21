"""Pay or test v3 confirmatory: the declared tests (``pay_or_test_v3_confirmatory_plan.md``, Section 4), committed first.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v3_confirmatory_analysis.py \\
        SOL_CONFIRM_ROOT OPUS_CONFIRM_ROOT OPUS_DIAGNOSTIC_ROOT > analysis.json

Every play is replayed and priced by ``pay_or_test_v3_pilot_report.read``. Arm A, the one confirmatory test: Sol's
share of the pay-to-best gap closed, each world the mean of its plays, over the 20 fresh option-value worlds; a
two-sided one-sample t-test of mean zero at alpha 0.05, its 95% t interval and a 95% bootstrap interval. The claim holds
if the t interval's lower end is above zero and no more than ``MAX_MISSING_WORLDS`` worlds lack a completed play;
otherwise the test is reported as failed or as inconclusive by dropout. Arm B, a diagnostic with no claim: per world,
whether Opus touched a newcomer (quote, sample or lookup) on the confirmatory world and on its twin under version 1's
cohort odds, paired; and whether the best policy's first action on the twin goes to a newcomer.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from scipy import stats

import pay_or_test_v3_pilot_report as report
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module

MAX_MISSING_WORLDS = 2
#: Arm B's declared reading: the odds are named the likely cause only if Opus touches a newcomer on at least this many
#: twins and at most ``CONTROL_AT_MOST`` confirmatory worlds.
TWINS_AT_LEAST, CONTROL_AT_MOST = 10, 2


def _by_world(read: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for play in read["plays_detail"]:
        out.setdefault(play["slug"], []).append(play)
    return out


def _touched(play: dict, newcomers: set[str]) -> bool:
    return any(token.split(":")[0] in ("quote", "sample", "lookup") and token.split(":")[1] in newcomers
               for token in play["trace"].split())


def arm_a(sol: dict) -> dict:
    planned = [w["slug"] for w in json.loads((pack_module.pack_root(pack_module.CONFIRM_PACK_ID) / "pack.json").read_text())["worlds"]]
    worlds = _by_world(sol)
    shares = {slug: statistics.fmean(p["gap_closed"] for p in plays) for slug, plays in worlds.items()}
    values = [shares[slug] for slug in planned if slug in shares]
    missing = [slug for slug in planned if slug not in shares]
    n = len(values)
    mean, sd = statistics.fmean(values), statistics.stdev(values)
    half = stats.t.ppf(0.975, n - 1) * sd / n ** 0.5
    t_value = mean / (sd / n ** 0.5) if sd > 0 else float("inf")
    p_value = float(2 * stats.t.sf(abs(t_value), n - 1)) if sd > 0 else 0.0
    if len(missing) > MAX_MISSING_WORLDS:
        verdict = "inconclusive_by_dropout"
    else:
        verdict = "positive_share_closed" if mean - half > 0 else "not_shown"
    return {"subject": sol["campaign_id"], "worlds": n, "missing_worlds": missing, "plays": sol["plays"],
            "failed_plays": sol["failed"], "gap_closed_mean": round(mean, 4), "world_sd": round(sd, 4),
            "t_ci95": [round(mean - half, 4), round(mean + half, 4)], "bootstrap_ci95": report._interval(values),
            "t": round(t_value, 3), "p_two_sided": p_value, "verdict": verdict,
            "per_world": {slug: round(shares[slug], 4) for slug in planned if slug in shares},
            "decision_loss_mean_usd": sol["by_kind"]["myopic_pays"]["decision_loss_mean_usd"],
            "pay_premium_loss_mean_usd": sol["by_kind"]["myopic_pays"]["pay_premium_loss_mean_usd"]}


def arm_b(opus_confirm: dict, opus_diagnostic: dict) -> dict:
    confirm = {w["slug"]: w for w in json.loads((pack_module.pack_root(pack_module.CONFIRM_PACK_ID) / "pack.json").read_text())["worlds"]}
    twins = {w["slug"]: w for w in json.loads((pack_module.pack_root(pack_module.DIAGNOSTIC_PACK_ID) / "pack.json").read_text())["worlds"]}
    control, twin = _by_world(opus_confirm), _by_world(opus_diagnostic)
    rows = []
    for slug in sorted(confirm):
        newcomers = {n["supplier_id"].replace("driver_board_", "") for n in confirm[slug]["newcomers"]}
        row = {"slug": slug, "control_touched": None, "twin_touched": None,
               "twin_best_first_to_newcomer": twins[slug]["best_first_to_newcomer"],
               "twin_best_over_pay_share": twins[slug]["best_over_pay_share"]}
        if slug in control:
            row["control_touched"] = any(_touched(p, newcomers) for p in control[slug])
            row["control_gap_closed"] = round(statistics.fmean(p["gap_closed"] for p in control[slug]), 4)
        if slug in twin:
            row["twin_touched"] = any(_touched(p, newcomers) for p in twin[slug])
            row["twin_gap_closed"] = (None if any(p["gap_closed"] is None for p in twin[slug])
                                      else round(statistics.fmean(p["gap_closed"] for p in twin[slug]), 4))
        rows.append(row)
    both = [r for r in rows if r["control_touched"] is not None and r["twin_touched"] is not None]
    twins_touched = sum(r["twin_touched"] for r in both)
    control_touched = sum(r["control_touched"] for r in both)
    reading = ("cohort_odds_named_likely_cause" if twins_touched >= TWINS_AT_LEAST and control_touched <= CONTROL_AT_MOST
               else "odds_alone_do_not_explain")
    return {"paired_worlds": len(both), "control_touched": control_touched, "twin_touched": twins_touched,
            "twin_only": sum(r["twin_touched"] and not r["control_touched"] for r in both),
            "control_only": sum(r["control_touched"] and not r["twin_touched"] for r in both),
            "twins_where_best_first_goes_to_a_newcomer": sum(r["twin_best_first_to_newcomer"] for r in rows),
            "reading": reading, "rows": rows}


if __name__ == "__main__":
    sol, opus_confirm, opus_diagnostic = (report.read(Path(p)) for p in sys.argv[1:4])
    print(json.dumps({"arm_a": arm_a(sol), "arm_b": arm_b(opus_confirm, opus_diagnostic)}, indent=1))
