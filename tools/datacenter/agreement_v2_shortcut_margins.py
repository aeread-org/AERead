"""Measured headroom by the reference route on the v2 admitted pack: how far each scripted integrator rule falls short.

    PYTHONPATH=src python tools/datacenter/agreement_v2_shortcut_margins.py [--best-informed PER_WORLD.csv] > OUT.json

The v2 admission screen (``agreement_admitted_pack_v2``, amendment 3) compares one rule, ``price_only``, with the
integrator's grid ceiling, and only on deal worlds. This applies the comparison to every scripted rule the family
defines, on all 80 worlds of ``agreement_admitted_v2``, in the integrator seat against the client's publicly drawn firm
style (the counterpart of the "vs firm" arms). No model is called. The rules:

- each fixed style of the scripted negotiator (``agreement_admitted_baselines_v2.STYLES``, ``public`` being the style
  the public world draws for the integrator seat), each knowing only its own costs and the declared odds;
- ``draft``: the integrator's paper as it stands at an even split of what it leaves (``agreement.draft_move``), the
  integrator half of the draft pair, against the same client;
- ``walk``: walk away at once.

The reference is the grid ceiling ``agreement_negotiator_check.best_plan`` (both types known), as the screen uses it:
read from the committed free baselines (``agreement_admitted_v2_free_baselines``), whose earnings for the fixed styles
are recomputed here and must agree. It is a lower bound on the best reply (DC-D-40), so a gap computed against it is a
lower bound on the true gap. ``--best-informed`` adds the tighter references of ``agreement_best_informed_v2``
(branch ``codex/datacenter-best-informed``, c12539b5): the best informed policy at the true types and told the type.
Earnings are the integrator's surplus over its outside option, $k, redline fees deducted: the quantity contrasts P3a and
P3b score.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Mapping

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_baselines_v2 as b2
from aeread_families.datacenter_development import agreement_admitted_pack as aap
from aeread_families.datacenter_development import agreement_admitted_pack_v2 as v2

BASELINES = (Path(__file__).resolve().parents[2] / "evidence" / "datacenter_development"
             / "agreement_admitted_v2_free_baselines" / "reports" / "baselines.json")
RULES = (*b2.STYLES, "draft", "walk")
#: The rules that skip the decision the case measures: no clause is negotiated (``price_only``, ``draft``) or nothing is.
SHORTCUTS = ("price_only", "draft", "walk")
SEAT = "integrator"
TOL = 1e-3


def _play(cw, it, rule: str) -> float:
    """The integrator's earnings when it plays ``draft`` or ``walk`` against the client's public firm style."""
    other = aap.public_style(cw, "client")
    state = ag.initial_state(cw)
    while not state["finished"]:
        if state["to_move"] == SEAT:
            move = ({"action": "walk", "clauses": None, "price": None, "note": "walk"} if rule == "walk"
                    else ag.draft_move(state, cw, it))
        else:
            move = v2.an.negotiator_move(state, cw, it, other)
        state = ag.apply(state, move, cw)
    return round(ag.grade(cw, it, state)[f"{SEAT}_surplus"], 3)


def style_earnings(cw, it) -> dict[str, float]:
    return {s: v2.rule_earnings(cw, it, SEAT, aap.public_style(cw, SEAT) if s == "public" else s)["earnings"]
            for s in b2.STYLES}


def one_world(job: tuple[str, Mapping[str, Any], bool]) -> dict[str, Any]:
    code, raw, styles = job
    cw, it = v2.world_of(raw)
    earnings = style_earnings(cw, it) if styles else {}
    earnings.update({r: _play(cw, it, r) for r in ("draft", "walk")})
    return {"world": code, "earnings": earnings}


def margins(processes: int = 8, best_informed: Path | None = None, recompute_styles: bool = True) -> dict[str, Any]:
    """Every world's references and rule earnings, and the summary. With ``recompute_styles=False`` the fixed styles'
    earnings are taken from the committed free baselines instead of being played again (``draft`` and ``walk`` are
    always played)."""
    manifest, cases, _ = v2.load(v2.ADMITTED)
    committed = {w["world"]: w for w in json.loads(BASELINES.read_text())["packs"][v2.ADMITTED.pack]["worlds"]}
    jobs = [(row["case_id"].rsplit(".", 1)[-1], cases[row["case_id"]], recompute_styles) for row in manifest["worlds"]]
    if processes > 1:
        with Pool(processes) as pool:
            played = pool.map(one_world, jobs, chunksize=1)
    else:
        played = [one_world(j) for j in jobs]
    if not recompute_styles:
        for p in played:
            p["earnings"] |= {s: committed[p["world"]]["seats"][SEAT]["styles"][s]["earnings"] for s in b2.STYLES}
    informed = {}
    if best_informed is not None:
        with best_informed.open() as f:
            informed = {r["world"]: r for r in csv.DictReader(f) if r["seat"] == SEAT}
    rows = []
    for (code, _, _), p, row in zip(jobs, played, manifest["worlds"]):
        c = committed[code]["seats"][SEAT]
        for s in b2.STYLES:  # the committed baselines and this run agree on every fixed style
            assert abs(c["styles"][s]["earnings"] - p["earnings"][s]) < TOL, (code, s)
        deal = row["available_surplus"] > 0
        refs = {"ceiling": c["best_plan"]["earnings"]}
        if deal:
            assert abs(row["integrator_headroom"]["ceiling"] - refs["ceiling"]) < TOL, code
        if code in informed:
            refs |= {"best_informed": float(informed[code]["plan_at_true"]), "told_the_type": float(informed[code]["told_the_type"])}
        rows.append({"world": code, "deal": deal, "references": refs, "earnings": p["earnings"]})
    return {"pack": v2.ADMITTED.pack, "margin": v2.HEADROOM_MARGIN, "rules": list(RULES), "worlds": rows,
            "summary": summary(rows)}


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ref in ("ceiling", "best_informed", "told_the_type"):
        if not all(ref in r["references"] for r in rows):
            continue
        out[ref] = {}
        for kind, subset in (("deal", [r for r in rows if r["deal"]]), ("no_deal", [r for r in rows if not r["deal"]])):
            out[ref][kind] = {"worlds": len(subset), "rules": {}}
            for rule in RULES:
                gaps = [r["references"][ref] - r["earnings"][rule] for r in subset]
                out[ref][kind]["rules"][rule] = {
                    "min_gap": round(min(gaps), 2), "mean_gap": round(statistics.fmean(gaps), 2),
                    "worlds_below_margin": sum(g < v2.HEADROOM_MARGIN for g in gaps),
                    "worlds_at_or_above_reference": sum(g <= TOL for g in gaps)}
            for name, group in (("any_rule", RULES), ("shortcut", SHORTCUTS),
                                ("style", tuple(r for r in RULES if r not in SHORTCUTS))):
                best = [min(r["references"][ref] - r["earnings"][rule] for rule in group) for r in subset]
                out[ref][kind][f"{name}_min_gap"] = round(min(best), 2)
                out[ref][kind][f"worlds_some_{name}_below_margin"] = sum(g < v2.HEADROOM_MARGIN for g in best)
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--best-informed", type=Path, default=None)
    args = parser.parse_args(argv)
    print(json.dumps(margins(args.processes, args.best_informed), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
