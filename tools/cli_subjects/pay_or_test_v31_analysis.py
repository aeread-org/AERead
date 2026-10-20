"""Pay or test v3 under brief v3.1: the declared read-out (``pay_or_test_v31_brief_plan.md``, Section 4), committed first.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v31_analysis.py \\
        --sol-v3 SOL_V3_ROOT --sol-v31 SOL_V31_ROOT --opus-v3 OPUS_V3_ROOT --opus-v31 OPUS_V31_ROOT \\
        [--comprehension SOL_RECORD OPUS_RECORD] > analysis.json

Every play is replayed and priced by ``pay_or_test_v3_pilot_report.read``. Per subject, on the 20 confirmatory worlds,
each world the mean of its plays and paired by world with the sealed v3 run under the v3 brief:

1. the share of the pay-to-best gap closed under each brief, and the paired change (v3.1 minus v3) with its 95% t
   interval over worlds;
2. plays that touch a new listing (a quote, sample or lookup), plays that touch two or more new listings, plays with a
   lookup, and plays that settle whether a kind shares a source;
3. the share of plays under each brief whose stated reasons mention a shared source, and of those, how many treat it
   as information (a test of one listing tells about another) rather than as risk; and Opus's turns doing either;
4. the kind-blind shortcut's share on the same worlds, beside each subject's.

The comprehension records, when given, are summarised as answers within the declared tolerance, per question type.
No contrast is a claim; the plan's reading rules say what each count can and cannot show.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

from scipy import stats

import pay_or_test_v3_pilot_report as report
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module

#: A stated reason mentions a shared source when it matches SHARED; it reads the source as information when it also
#: matches INFORMATION (what one listing's test shows about another), as the plan's Section 4 declares.
SHARED = re.compile(r"shar|same source|same factory|one source|sibling|correlat", re.I)
#: The comprehension reading (plan Section 5 and amendment 1): 14 of 18 and 9 of 18 as shares of the answered asks.
READ_MIN_ANSWERED, READS_AT, FAILS_AT = 14, 14 / 18, 9 / 18
INFORMATION = re.compile(r"tells?|reveal|inform|learn|signal|indicat|implies|evidence|update|posterior|if .{0,40}sound|"
                         r"if .{0,40}pass|test(ing)? (it|one|the)", re.I)


def _confirm_worlds() -> dict[str, dict]:
    return {w["slug"]: w for w in json.loads((pack_module.pack_root(pack_module.CONFIRM_PACK_ID) / "pack.json").read_text())["worlds"]}


def _by_world(read: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for play in read["plays_detail"]:
        out.setdefault(play["slug"], []).append(play)
    return out


def _touched(play: dict, newcomers: set[str]) -> set[str]:
    return {token.split(":")[1] for token in play["trace"].split()
            if token.split(":")[0] in ("quote", "sample", "lookup") and token.split(":")[1] in newcomers}


def _reasons(run_root: Path) -> list[list[str]]:
    """Each completed play's stated reasons and messages, turn by turn, from the run's own rows."""
    artifact = json.loads((run_root / "summary.json").read_text())
    return [[f"{step.get('reason') or ''} {step.get('message') or ''}".strip() for step in row["action_trace"]]
            for row in artifact["rows"] if row.get("status") == "completed"]


def _reason_counts(run_root: Path) -> dict:
    plays = _reasons(run_root)
    turns = [t for play in plays for t in play]
    shared = [t for t in turns if SHARED.search(t)]
    return {"plays": len(plays), "turns": len(turns), "turns_with_a_reason": sum(bool(t) for t in turns),
            "turns_mentioning_a_shared_source": len(shared),
            "of_which_as_information": sum(bool(INFORMATION.search(t)) for t in shared),
            "plays_mentioning_a_shared_source": sum(any(SHARED.search(t) for t in play) for play in plays)}


def subject(v3_root: Path, v31_root: Path) -> dict:
    worlds = _confirm_worlds()
    before, after = report.read(v3_root), report.read(v31_root)
    a, b = _by_world(before), _by_world(after)
    paired = sorted(set(a) & set(b), key=lambda s: int(s.split("__")[1]))
    share = lambda plays: statistics.fmean(p["gap_closed"] for p in plays)
    diffs = [share(b[s]) - share(a[s]) for s in paired]
    n = len(diffs)
    mean, sd = statistics.fmean(diffs), statistics.stdev(diffs)
    half = stats.t.ppf(0.975, n - 1) * sd / n ** 0.5 if sd > 0 else 0.0

    def process(read: dict) -> dict:
        plays = read["plays_detail"]
        touched = [_touched(p, {n["supplier_id"].replace("driver_board_", "") for n in worlds[p["slug"]]["newcomers"]})
                   for p in plays]
        return {"plays": len(plays), "failed": read["failed"],
                "gap_closed_mean": round(statistics.fmean(share(ps) for ps in _by_world(read).values()), 4),
                "touched_a_new_listing": sum(bool(t) for t in touched),
                "touched_two_or_more_new_listings": sum(len(t) >= 2 for t in touched),
                "plays_with_a_lookup": sum(p["lookups"] > 0 for p in plays),
                "plays_settling_a_kind": sum(p["settled_a_kind"] for p in plays),
                "first_info_to_newcomer": sum(p["first_info_to_newcomer"] for p in plays)}

    return {"v3": {"campaign_id": before["campaign_id"], **process(before), "reasons": _reason_counts(v3_root)},
            "v31": {"campaign_id": after["campaign_id"], **process(after), "reasons": _reason_counts(v31_root)},
            "paired_worlds": n, "unpaired": sorted(set(a) ^ set(b)),
            "change_in_gap_closed": {"mean": round(mean, 4), "t_ci95": [round(mean - half, 4), round(mean + half, 4)]},
            "per_world": {s: {"v3": round(share(a[s]), 4), "v31": round(share(b[s]), 4)} for s in paired}}


def comprehension(paths: list[Path]) -> dict:
    out = {}
    for path in paths:
        record = json.loads(path.read_text())
        by_question: dict[str, list[bool]] = {}
        for answer in record["answers"]:
            if not answer.get("refused"):
                by_question.setdefault(answer["id"], []).append(answer["correct"])
        answered, correct = record.get("answered", record["asked"]), record["correct"]
        # Plan amendment 1: read on answered asks, and only when at least READ_MIN_ANSWERED were answered.
        if answered < READ_MIN_ANSWERED:
            reading = "no reading: too few answered"
        elif correct / answered >= READS_AT:
            reading = "reads the rule"
        elif correct / answered <= FAILS_AT:
            reading = "does not read the rule"
        else:
            reading = "no reading"
        out[record["subject"]] = {"correct": correct, "answered": answered, "refused": record.get("refused", 0),
                                  "asked": record["asked"], "reading": reading,
                                  "by_question": {k: f"{sum(v)} of {len(v)}" for k, v in by_question.items()}}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("sol-v3", "sol-v31", "opus-v3", "opus-v31"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--comprehension", type=Path, nargs="*", default=[])
    args = parser.parse_args()
    worlds = _confirm_worlds()
    shortcut = statistics.fmean(1 - w["rule_loss_usd"]["cheapest_sample_first"] / w["rule_loss_usd"]["pay_premium"]
                                for w in worlds.values())
    print(json.dumps({"plan": "docs/families/procurement-allocation/pay_or_test_v31_brief_plan.md",
                      "sol": subject(args.sol_v3, args.sol_v31), "opus": subject(args.opus_v3, args.opus_v31),
                      "kind_blind_shortcut_gap_closed": round(shortcut, 4),
                      "comprehension": comprehension(args.comprehension)}, indent=1))


if __name__ == "__main__":
    main()
