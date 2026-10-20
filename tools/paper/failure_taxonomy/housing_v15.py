"""Housing v15 (lemons price, outside demand): the shortfall to the reachable reference, by failure class.

Offline and read-only. Reads the published v15 bundle (cells.jsonl) for the reproduction check, the sealed run
roots for seat 0's trajectory (the seat-0 block of each family outcome), and regenerates each world and the
reference (``inspect_lowball``) from the worktree code. Writes only to this folder.

The classes, their rules and their PRIORITY order are ``housing_v14.py``'s, unchanged. What differs is what v15
changed in the case, and only where a rule reads it:

- measure: v15's primary is measure v2 (``price_reply_posterior``, ``seat0_primary_v2``), which v14's taxonomy
  computed after the fact as the HL-D-07 "corrected" measure. A blind signing's lemon probability is v2's
  posterior (``p_v2``) and its value v2's (``value_v2``), exactly as the v14 corrected column used ``p_full`` and
  ``v_full``. The output keeps v14's key ``corrected`` for it, so the panels read both versions the same way.
- reference: ``inspect_lowball`` played offline at the main stream's outside-demand rate and scored under v2, as
  v15's seat-0 scorer does (``price_seat0.references``); it signs only inspected listings, so its v2 value is its
  realized net. Each cell's gap is the reference less seat 0's v2 net, the negative of the receipt's
  ``inspect_lowball_gap``.
- seat 0's decisions, trajectory, inspection spend and typed invalid actions come from the v15 outcome's seat-0
  block, the record the receipt was scored from, not from v14's six-tenant facts.
- walks: the commitment-error rule's label ("walked from a hold worth its rent" or "no hold worth signing") values
  a walked hold at v2's posterior for its round. v14 read v1's response odds there. This changes a label inside
  one class, never a class or an amount.
- strata come from pack v2's manifest (``streams.main.by_stratum``); v15's cells do not carry them.

Unit: the cell (one world, one landlord arm), main stream only (260 worlds; the holdout runs at another
outside-demand rate and is not in the panels). The whole cell shortfall, negative or positive, goes to the first
class whose rule fires, in PRIORITY order. A world's class amount is the mean over its two arms, as the primary is;
worlds missing an arm are left out (Operational; v15 completed every cell).

Run:
  AEREAD_HOUSING_ROOT=<checkout of codex/housing-v15-offline with runs/housing_v15> PYTHONDONTWRITEBYTECODE=1 \\
      PYTHONPATH=$AEREAD_HOUSING_ROOT/src python housing_v15.py
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

WT = Path(os.environ["AEREAD_HOUSING_ROOT"])
RUNS = WT / "runs/housing_v15"
OUT = Path(__file__).resolve().parent
BUNDLES = {"v15": WT / "evidence/housing/housing_lemons_price_v15_confirmatory",
           "addendum": WT / "evidence/housing/housing_lemons_price_v15_glm_addendum"}
PACK = WT / "evidence/housing/housing_lemons_price_pack_v2/reports/pack.json"
ANALYSIS = WT / "evidence/housing/housing_lemons_price_v15_analysis/reports/analysis.json"
ADDENDUM_ANALYSIS = WT / "evidence/housing/housing_lemons_price_v15_glm_addendum_analysis/reports/analysis.json"

from aeread_families.housing import lemons, price_controls, price_endpoint as pe, price_reference as pr  # noqa: E402
from aeread_families.housing import price_reply_posterior as posterior  # noqa: E402

# campaign id -> (name, bundle, whether it is in v15's declared pair). GLM is addendum A, reported apart.
PANEL = {"housing_lemons_price_v15_gemini38_flash": ("Gemini 3.8 Flash", "v15", True),
         "housing_lemons_price_v15_gpt6_luna": ("GPT-6 Luna", "v15", True),
         "housing_lemons_price_v15_glm53_flash_nearai": ("GLM 5.3 Flash (addendum A)", "addendum", False)}
CLASSES = ("information_not_acquired", "contrary_to_information_held", "worse_terms", "commitment_error",
           "interaction_cost", "procedure_and_format", "operational")
PRIORITY = ("procedure_and_format", "contrary_to_information_held", "information_not_acquired", "commitment_error",
            "worse_terms", "interaction_cost")
TOL = 0.005
SEAT = pr.FOCAL_SEAT


@lru_cache(maxsize=None)
def strata() -> dict[int, str]:
    by = json.loads(PACK.read_text())["streams"]["main"]["by_stratum"]
    return {int(seed): stratum for stratum, seeds in by.items() for seed in seeds}


@lru_cache(maxsize=None)
def reference_view(seed: int, arm: str) -> dict[str, Any]:
    """``inspect_lowball`` at seat 0 in one world and arm, main-stream rate, scored under v2."""
    market, trajectory = posterior.run_recorded(seed, arm, price_controls.CONTROLS["inspect_lowball"])
    scored = posterior.score_market(market, trajectory)
    assert not scored["blind_signings"], (seed, arm)  # it signs only inspected listings
    world = market.world
    leased = dict(market.pairs)
    out = {"net": scored["primary_v2"], "spend": float(market.inspection_spend[SEAT]), "leased": SEAT in leased}
    if out["leased"]:
        l = leased[SEAT]
        out.update(listing=l, rent=float(market.signed_rent[SEAT]),
                   surplus=round(float(world.values[SEAT][l]) - float(market.signed_rent[SEAT]), 2),
                   quality="lemon" if world.quality[l] == lemons.LEMON else "sound")
    else:
        out["surplus"] = 0.0
    return out


def seat0_block(cell_json: Path) -> tuple[dict[str, Any], posterior.Trajectory]:
    """The family outcome's seat-0 block (what the receipt scored) and the trajectory read from the events."""
    ev_root = cell_json.with_name(cell_json.stem + "_evidence")
    (events,) = glob.glob(str(ev_root / "runplan_*/tasks/*/attempts/*/events.jsonl"))
    from_events, outcome = posterior.trajectory_from_events(Path(events), SEAT)
    seat0 = outcome["seat0"]
    recorded = posterior.Trajectory.from_row(seat0["trajectory"])
    assert recorded.inspections == from_events.inspections and recorded.replies == from_events.replies, cell_json
    return seat0, recorded


def analyse_cell(row: dict[str, Any], cid: str) -> dict[str, Any]:
    seed, arm = int(row["world_seed"]), row["arm"]
    cell_json = RUNS / cid / "live" / f"world_{seed}__{arm}.json"
    seat0, trajectory = seat0_block(cell_json)
    world = pr.make_world(seed, arm)
    decisions = seat0["commit_decisions"]
    spend = float(seat0["inspection_spend"])
    scored = posterior.score_seat(world, decisions, trajectory, spend, seat=SEAT)
    assert abs(scored["primary_v2"] - row["seat0_primary_v2"]) < TOL, (cid, seed, arm)
    ref = reference_view(seed, arm)
    assert abs(ref["net"] - row["references"]["scripted_reference"]) < TOL, (cid, seed, arm)
    gap = round(ref["net"] - scored["primary_v2"], 2)
    assert abs(gap + row["metrics"]["inspect_lowball_gap"]) < 0.011, (cid, seed, arm, gap)
    invalid = [{"code": code, "count": n} for code, n in sorted(seat0.get("invalid_actions", {}).items()) if n]
    signed = [d for d in decisions if d["decision"] == "sign"]
    assert len(signed) <= 1
    loss, count, listings = float(world.lemon_loss), world.lemon_count, world.num_listings
    walks = []
    for d in decisions:
        if d["decision"] != "walk":
            continue
        l, r = int(d["listing_id"]), int(d["round_index"])
        if d["informed"]:
            value = float(world.values[SEAT][l])
        else:
            inspected, revealed = posterior.knowledge(world, r, trajectory)
            p = posterior.lemon_posterior(l, {**inspected, **revealed}, count, listings)
            value = round(float(world.values_if_sound[SEAT][l]) - p * loss, 2)
        walks.append({"round_index": r, "listing_id": l, "rent": float(d["rent"]), "informed": bool(d["informed"]),
                      "ev_response": value})
    lease = None
    if signed:
        d = signed[0]
        l = int(d["listing_id"])
        if d["informed"]:
            p, value, settled_by = (1.0 if d["quality"] == "lemon" else 0.0), float(world.values[SEAT][l]), "inspection"
        else:
            (b,) = [b for b in scored["blind_signings"] if (b["round_index"], b["listing_id"]) == (int(d["round_index"]), l)]
            p, value = b["p_v2"], b["value_v2"]
            settled_by = "reply or elimination" if p in (0.0, 1.0) else None
        sound_value = float(world.values_if_sound[SEAT][l])
        inspect_gain = p * (loss - (sound_value - float(d["rent"]))) - 25.0 if 0.0 < p < 1.0 else None
        lease = {"listing_id": l, "round_index": int(d["round_index"]), "rent": float(d["rent"]),
                 "informed": bool(d["informed"]), "quality": d["quality"], "p_lemon": p, "value_at_measure": value,
                 "surplus": round(value - float(d["rent"]), 2), "settled_by": settled_by,
                 "below_sound_floor": float(d["rent"]) < pe.sound_floor(world, l) - 1e-6,
                 "inspection_was_worth_it": None if inspect_gain is None else inspect_gain > 0}
    cls, rule = classify(lease, ref, spend, invalid, gap, walks)
    out = {"world_seed": seed, "arm": arm, "population": "main", "stratum": strata()[seed], "reference": ref,
           "spend": spend, "invalid_actions": invalid, "walks": walks,
           "corrected": {"primary": scored["primary_v2"], "gap": gap, "lease": lease, "class": cls, "rule": rule}}
    if lease is not None:
        # for the reading only (not classes): gap = listing choice at the landlord's floor + rent above that floor
        # + inspection spend above the reference's
        res = world.reservation_cost(lease["listing_id"])
        floor = round(max(res, min(float(world.ask[lease["listing_id"]]), res + pe.LANDLORD_MARGIN)), 2)
        premium = round(lease["rent"] - floor, 2)
        spend_diff = round(spend - ref["spend"], 2)
        out["corrected"]["pieces"] = {"listing_choice_at_floor": round(gap - premium - spend_diff, 2),
                                      "rent_above_landlord_floor": premium, "inspection_spend_above_reference": spend_diff}
    return out


def classify(lease, ref, spend, invalid, gap, walks=()) -> tuple[str, str]:
    """``housing_v14.classify``, unchanged: the first rule that fires, in PRIORITY order."""
    if invalid:
        return "procedure_and_format", "seat 0 sent an action the environment did not accept (" + \
            ", ".join(sorted({x["code"] for x in invalid})) + ")"
    if lease is not None and lease["p_lemon"] == 1.0 and lease["surplus"] < -TOL:
        return "contrary_to_information_held", ("signed an uninspected listing its information showed a lemon (a hold only a "
                                       "lemon's landlord offers, or elimination), at a rent above a lemon's value"
                                       if not lease["informed"] else
                                       "signed a listing its inspection showed a lemon, at a rent above a lemon's value")
    if lease is not None and 0.0 < lease["p_lemon"] < 1.0:
        return "information_not_acquired", "signed a listing whose quality its information did not settle"
    if lease is None and ref["leased"]:
        worth = any(w["ev_response"] >= w["rent"] for w in walks)
        return "commitment_error", ("ended with no lease where the reference leased: walked from a hold worth its rent"
                                    if worth else "ended with no lease where the reference leased: no hold worth signing")
    if lease is not None and lease["surplus"] < -TOL:
        return "commitment_error", "signed a listing known sound at a rent above its value"
    if lease is not None and abs(lease["surplus"] - ref["surplus"]) > TOL:
        if not ref["leased"]:
            return "worse_terms", "terms: leased where the reference did not"
        if lease["surplus"] > ref["surplus"]:
            return "worse_terms", "terms: a better lease than the reference's (negative)"
        if lease["listing_id"] == ref["listing"]:
            return "worse_terms", "terms: the reference's listing at a higher rent"
        return "worse_terms", "terms: a listing worth less, net of rent, than the reference's"
    return "interaction_cost", ("same lease value as the reference; the difference is inspection spend"
                               if lease is not None else "neither leased; the difference is inspection spend")


def aggregate(cells, rows, stratum) -> dict[str, Any]:
    by_world: dict[int, dict[str, dict]] = defaultdict(dict)
    planned = defaultdict(set)
    for r in rows:
        if r["stream"] == "main" and (stratum is None or strata()[int(r["world_seed"])] == stratum):
            planned[int(r["world_seed"])].add(r["arm"])
    for (seed, arm), c in cells.items():
        if stratum is None or c["stratum"] == stratum:
            by_world[seed][arm] = c["corrected"]
    worlds = {s: arms for s, arms in by_world.items() if len(arms) == 2}
    per_class = {k: 0.0 for k in CLASSES}
    counts = {k: 0 for k in CLASSES}
    nonzero = {k: 0 for k in CLASSES}
    gross = {k: {"positive": 0.0, "negative": 0.0} for k in CLASSES}
    by_rule: dict[str, float] = defaultdict(float)
    rule_cells: Counter = Counter()
    pieces = {k: defaultdict(float) for k in ("worse_terms", "information_not_acquired", "contrary_to_information_held",
                                              "commitment_error")}
    for s, arms in worlds.items():
        for arm, m in arms.items():
            per_class[m["class"]] += m["gap"] / 2.0
            counts[m["class"]] += 1
            nonzero[m["class"]] += abs(m["gap"]) > TOL
            gross[m["class"]]["positive" if m["gap"] > 0 else "negative"] += m["gap"] / 2.0
            by_rule[f"{m['class']}: {m['rule']}"] += m["gap"] / 2.0
            rule_cells[f"{m['class']}: {m['rule']}"] += 1
            if m["class"] in pieces and "pieces" in m:
                for k, v in m["pieces"].items():
                    pieces[m["class"]][k] += v / 2.0
    n = len(worlds)
    total = sum(statistics.fmean(m["gap"] for m in arms.values()) for arms in worlds.values()) / n
    per_world = {k: v / n for k, v in per_class.items()}
    assert abs(sum(per_world.values()) - total) < 1e-9, (sum(per_world.values()), total)
    dropped_worlds = sorted(s for s in planned if s not in worlds)
    missing_cells = sum(len(planned[s]) - len(by_world.get(s, {})) for s in planned)
    counts["operational"] = missing_cells
    return {"worlds": n, "total_shortfall_per_world": round(total, 6),
            "per_world": {k: round(v, 6) for k, v in per_world.items()},
            "share": {k: (round(v / total, 6) if total else None) for k, v in per_world.items()},
            "units": counts, "units_nonzero_gap": nonzero,
            "gross_per_world": {k: {g: round(v / n, 6) for g, v in d.items()} for k, d in gross.items()},
            "by_rule_per_world": {k: round(v / n, 6) for k, v in sorted(by_rule.items())},
            "by_rule_cells": dict(sorted(rule_cells.items())),
            "reading_pieces_per_world": {k: {g: round(v / n, 4) for g, v in d.items()} for k, d in pieces.items()},
            "operational": {"missing_cells": missing_cells, "worlds_left_out": len(dropped_worlds),
                            "completed_cells_left_out_with_their_world": sum(len(by_world.get(s, {})) for s in dropped_worlds)}}


def published_total(cid: str) -> float:
    """The published v15 (or addendum) main-pack mean of seat 0 less inspect_lowball's, $ per world."""
    if PANEL[cid][1] == "v15":
        means = json.loads(ANALYSIS.read_text())["secondary"]["means_main"]
        key = {"housing_lemons_price_v15_gemini38_flash": "gemini", "housing_lemons_price_v15_gpt6_luna": "luna"}[cid]
        return round(means[key] - means["inspect_lowball"], 2)
    return None


def run() -> dict[str, Any]:
    result: dict[str, Any] = {"case": "housing_v15", "unit": "USD per world (mean of the two landlord arms)",
                              "measure": posterior.MEASURE_ID, "reference": "inspect_lowball (v15 seat-0 scorer)",
                              "subjects": {}}
    for cid, (name, bundle, declared) in PANEL.items():
        rows = [json.loads(l) for l in (BUNDLES[bundle] / "tables/cells.jsonl").read_text().splitlines()]
        mine = [r for r in rows if r["campaign_id"] == cid and r["stream"] == "main"]
        cells = {}
        for r in mine:
            if r["status"] == "completed":
                cells[(int(r["world_seed"]), r["arm"])] = analyse_cell(r, cid)
        missing = [r for r in mine if r["status"] != "completed"]
        subj: dict[str, Any] = {"campaign_id": cid, "declared_v15_pair": declared, "planned_cells": len(mine),
                                "completed_cells": len(cells),
                                "missing_cells": {"total": len(missing),
                                                  "by_condition": dict(Counter(r["failure_condition"] or r["status"] for r in missing))},
                                "measures": {"corrected": {}}}
        for scope, stratum in (("main", None), ("main_favourite_is_lemon", "favourite_is_lemon"),
                               ("main_favourite_is_sound", "favourite_is_sound")):
            subj["measures"]["corrected"][scope] = aggregate(cells, mine, stratum)
        # reproduce the published row before trusting anything else
        main = subj["measures"]["corrected"]["main"]
        expected = published_total(cid)
        recomputed = round(-statistics.fmean(
            statistics.fmean(-r["metrics"]["inspect_lowball_gap"] for r in mine if int(r["world_seed"]) == s)
            for s in {int(r["world_seed"]) for r in mine}), 6)
        assert abs(main["total_shortfall_per_world"] + recomputed) < 1e-6, (cid, main["total_shortfall_per_world"], recomputed)
        if expected is not None:
            assert abs(main["total_shortfall_per_world"] + expected) < 0.011, (cid, main["total_shortfall_per_world"], expected)
        subj["reproduced_minus_reference"] = {"from_classes": -main["total_shortfall_per_world"],
                                              "from_cells_inspect_lowball_gap": recomputed,
                                              "published_means_main_difference": expected}
        subj["instances"] = [{"world_seed": c["world_seed"], "arm": c["arm"], "population": c["population"],
                              "stratum": c["stratum"], "corrected": {k: c["corrected"][k] for k in ("gap", "class", "rule")}}
                             for c in sorted(cells.values(), key=lambda c: (c["world_seed"], c["arm"]))]
        subj["worlds_detail"] = [{"world_seed": s, "stratum": strata()[s],
                                  "per_class": {k: round(sum(cells[(s, a)]["corrected"]["gap"] / 2.0 for a in ("true_cost", "pooled")
                                                              if cells[(s, a)]["corrected"]["class"] == k), 6) for k in CLASSES},
                                  "total": round(statistics.fmean(cells[(s, a)]["corrected"]["gap"] for a in ("true_cost", "pooled")), 6)}
                                 for s in sorted({s for s, _ in cells})]
        subj["diagnostics"] = diagnostics(cells)
        result["subjects"][name] = subj
    return result


def diagnostics(cells) -> dict[str, Any]:
    rules = Counter(c["corrected"]["rule"] for c in cells.values())
    blind_not_worth = sum(1 for c in cells.values() if c["corrected"]["class"] == "information_not_acquired"
                          and c["corrected"]["lease"]["inspection_was_worth_it"] is False)
    neg = Counter(c["corrected"]["class"] for c in cells.values() if c["corrected"]["gap"] < -TOL)
    blind = [c["corrected"]["lease"] for c in cells.values()
             if c["corrected"]["lease"] is not None and not c["corrected"]["lease"]["informed"]]
    return {"rules_fired_main": dict(rules), "blind_signings_where_inspecting_was_not_worth_the_fee": blind_not_worth,
            "negative_gap_cells_by_class": dict(neg),
            "blind_signings": {"total": len(blind), "known_lemon": sum(l["p_lemon"] == 1.0 for l in blind),
                               "known_sound": sum(l["p_lemon"] == 0.0 for l in blind),
                               "unsettled": sum(0.0 < l["p_lemon"] < 1.0 for l in blind),
                               "lemon_drawn": sum(l["quality"] == "lemon" for l in blind)},
            "no_lease_cells": sum(1 for c in cells.values() if c["corrected"]["lease"] is None)}


if __name__ == "__main__":
    res = run()
    (OUT / "housing_v15_taxonomy.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    for name, s in res["subjects"].items():
        m = s["measures"]["corrected"]["main"]
        print(f"{name:28s} total {m['total_shortfall_per_world']:8.2f} "
              + " ".join(f"{k[:12]}={v:7.2f}({m['units'][k]})" for k, v in m["per_world"].items()))
        print("  ", json.dumps(s["reproduced_minus_reference"]), json.dumps(s["diagnostics"]["blind_signings"]))
    sys.exit(0)
