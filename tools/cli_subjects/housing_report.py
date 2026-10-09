"""Read a CLI subject's Housing price cells beside the v14 confirmatory cells of the same worlds.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/housing_report.py <runs dir>

The measure is v14's primary: the deciding tenant's net at the reply-conditioned odds, mean of
the two landlord arms, per world. Every interval is a 95% Student-t interval over worlds, paired
by world where two things are compared. The v14 cells are the published confirmatory cells of
the same worlds; nothing is rerun.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from aeread_families.housing import price_publication as pub

import housing_cli

V14 = {
    "gemini 3.8 flash (v14)": "housing_lemons_price_confirmatory_v14_gemini38_flash",
    "glm 5.3 flash (v14)": "housing_lemons_price_confirmatory_v14_glm53_flash_nextbit",
    "gpt-6 luna (v14)": "housing_lemons_price_confirmatory_v14_gpt6_luna",
}
CLI = {
    "claude code opus 5.5": housing_cli.campaign_id("claude_opus55", "panel"),
    "codex sol 6.1": housing_cli.campaign_id("codex_sol61", "panel"),
    "claude code opus 5.5 (gate)": housing_cli.campaign_id("claude_opus55", "gate"),
    "claude code fable 5.1": housing_cli.campaign_id("claude_fable51", "panel"),
}


def fmt(interval: dict) -> str:
    if interval["mean"] is None:
        return "n/a"
    if interval["lo"] is None:
        return f"{interval['mean']:+.0f} (n={interval['n']})"
    return f"{interval['mean']:+.0f} [{interval['lo']:+.0f}, {interval['hi']:+.0f}] (n={interval['n']})"


def main() -> int:
    runs = Path(sys.argv[1])
    worlds = housing_cli.PANELS["panel"]
    rows: dict[str, list[dict]] = {}
    for name, campaign in {**CLI, **V14}.items():
        root = runs / campaign
        if not (root / "live").exists():
            continue
        seeds = [s for s in worlds if (root / "live" / f"world_{s}__pooled.json").exists()
                 or (root / "live" / f"world_{s}__true_cost.json").exists()] if name in CLI else worlds
        rows[name] = pub.cell_rows({"campaign_id": campaign, "world_seeds": seeds, "arms": list(pub.ARMS)}, root)
    reference_rows = rows[next(n for n in rows if n in V14)]
    reference = {s: statistics.fmean(r["reference_net"] for r in reference_rows if r["world_seed"] == s) for s in worlds}
    ceiling = {s: statistics.fmean(r["ceiling"] for r in reference_rows if r["world_seed"] == s) for s in worlds}
    level = {name: pub.per_world(r, pub.PRIMARY) for name, r in rows.items()}
    print(f"{len(worlds)} worlds, {worlds[0]} to {worlds[-1]}; scripted inspect-and-lowball rule {statistics.fmean(reference.values()):.0f} "
          f"per world, full-information ceiling {statistics.fmean(ceiling.values()):.0f}")
    print(f"\n{'subject':30s} cells done  worlds  primary per world            minus the scripted rule      share of ceiling  signed  on inspected  revealed lemon signed/walked  list cost")
    for name, r in rows.items():
        done = [x for x in r if x["status"] == "completed"]
        lv = level[name]
        realized = pub.per_world(r, "net_realized")
        share = sum(realized.values()) / sum(ceiling[s] for s in realized) if realized else float("nan")
        print(f"{name:30s} {len(r):5d} {len(done):4d} {len(lv):7d}  {fmt(pub._interval(list(lv.values()))):27s} "
              f"{fmt(pub._interval([lv[s] - reference[s] for s in lv])):27s} {share:16.0%} {sum(x['signed'] for x in done):7d} "
              f"{sum(x['ended_on_inspected_listing'] for x in done):13d} "
              f"{sum(x['signed_blind_after_revealing_reply'] for x in done):14d} / {sum(x['walked_revealing_reply'] for x in done):<10d} "
              f"{sum(x['cost_usd'] for x in r):9.2f}")
    cli = [n for n in rows if n in CLI and len(level[n]) >= 5]
    for name in cli:
        print(f"\n{name} minus each other subject, same worlds, primary measure")
        for other in [n for n in cli if n != name and cli.index(n) > cli.index(name)] + list(V14):
            if other not in level:
                continue
            both = sorted(set(level[name]) & set(level[other]))
            diffs = [level[name][s] - level[other][s] for s in both]
            higher = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
            print(f"  minus {other:26s} {fmt(pub._interval(diffs))}; higher on {higher[0]}, lower on {higher[1]}, level on {len(diffs) - sum(higher)}")
        print(f"\n{name} minus the scripted rule, by landlord arm, per cell")
        for arm in pub.ARMS:
            d = [r[pub.PRIMARY] - r["reference_net"] for r in rows[name] if r["arm"] == arm and r["status"] == "completed"]
            print(f"  {arm:10s} {fmt(pub._interval(d)):30s} below the rule in {sum(x < -0.5 for x in d)} cells, above in {sum(x > 0.5 for x in d)}, equal in {sum(abs(x) <= 0.5 for x in d)}")
        print(f"\n{name} by stratum (worlds with both arms)")
        for stratum in ("favourite_is_lemon", "favourite_is_sound"):
            lv = pub.per_world(rows[name], pub.PRIMARY, stratum=stratum)
            line = f"  {stratum:20s} {fmt(pub._interval(list(lv.values()))):28s} rule {statistics.fmean(reference[s] for s in lv):.0f}"
            for other in [n for n in cli if n != name] + list(V14):
                if other in rows:
                    ov = pub.per_world(rows[other], pub.PRIMARY, stratum=stratum)
                    both = sorted(set(lv) & set(ov))
                    line += f" | {other.split(' (')[0]} {statistics.fmean(ov[s] for s in both):.0f}"
            print(line)
    names = [n for n in rows if level[n]]
    print("\nprimary per world (mean of the two arms); the scripted rule and the ceiling beside it")
    print(f"{'world':8s} {'stratum':20s} {'rule':>6s} {'ceiling':>8s} " + " ".join(f"{n.split(' (')[0][:16]:>17s}" for n in names))
    stratum = {r["world_seed"]: r["stratum"] for r in reference_rows}
    for s in worlds:
        print(f"{s:<8d} {stratum[s]:20s} {reference[s]:6.0f} {ceiling[s]:8.0f} "
              + " ".join((f"{level[n][s]:.0f}" if s in level[n] else "").rjust(17) for n in names))
    for name in [n for n in rows if n in CLI]:
        bad = [(x["world_seed"], x["arm"], x["status"], x["failure_condition"]) for x in rows[name] if x["status"] != "completed"]
        if bad:
            print(f"\n{name}: cells that did not complete: {bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
