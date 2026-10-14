"""Housing v14 (lemons price, outside demand): the shortfall to the reachable reference, by failure class.

Offline and read-only. Reads the published v14 bundle (cells.jsonl) for the reproduction check, the sealed
run roots for seat 0's trajectory, and regenerates each world and the reference (``inspect_lowball``) from
the worktree code. Writes only to this folder.

Unit: the cell (one world, one landlord arm). A cell's shortfall is the reference's net less seat 0's net at
the measure (published ``net_expected_response_odds``, or the HL-D-07 corrected posterior). The whole cell
shortfall, negative or positive, goes to the first class whose rule fires, in PRIORITY order. A world's class
amount is the mean over its two arms, as the primary is; worlds missing an arm are left out (Operational).

Run:
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$AEREAD_HOUSING_ROOT/src:../hl_d_07 \
      python housing_v14.py
"""
from __future__ import annotations

import glob
import os
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

WT = Path(os.environ["AEREAD_HOUSING_ROOT"])  # a checkout of codex/housing-lemons-outside-demand with its runs/
V14 = WT / "evidence/housing/housing_lemons_price_confirmatory_v14"
RUNS = WT / "runs"
OUT = Path(__file__).resolve().parent

import hl_d_07 as h7  # noqa: E402  (the HL-D-07 analysis: trajectory reader and corrected posterior)
from aeread_families.housing import lemons, price_endpoint as pe, price_reference as pr  # noqa: E402

PANEL = {"housing_lemons_price_confirmatory_v14_gemini38_flash": "Gemini 3.8 Flash",
         "housing_lemons_price_confirmatory_v14_glm53_flash_nextbit": "GLM 5.3 Flash",
         "housing_lemons_price_confirmatory_v14_gpt6_luna": "GPT-6 Luna"}
PUBLISHED_MINUS_REFERENCE = {"housing_lemons_price_confirmatory_v14_gemini38_flash": -80.99,
                             "housing_lemons_price_confirmatory_v14_glm53_flash_nextbit": -155.09,
                             "housing_lemons_price_confirmatory_v14_gpt6_luna": -161.64}
CLASSES = ("information_not_acquired", "contrary_to_information_held", "worse_terms", "commitment_error",
           "interaction_cost", "procedure_and_format", "operational")
PRIORITY = ("procedure_and_format", "contrary_to_information_held", "information_not_acquired", "commitment_error",
            "worse_terms", "interaction_cost")
TOL = 0.005
HL_D_07_RESULTS = Path(__file__).resolve().parents[1] / "hl_d_07" / "hl_d_07_results.json"
HL_SHORT = {"housing_lemons_price_confirmatory_v14_gemini38_flash": "Gemini",
            "housing_lemons_price_confirmatory_v14_glm53_flash_nextbit": "GLM",
            "housing_lemons_price_confirmatory_v14_gpt6_luna": "Luna"}
LOSS, FEE = 1000.0, 25.0


def seat0_invalid(cell_json: Path) -> list[dict[str, Any]]:
    """Seat 0's actions the environment did not accept: a parse failure or an illegal action."""
    ev_root = cell_json.with_name(cell_json.stem + "_evidence")
    (events,) = glob.glob(str(ev_root / "runplan_*/tasks/*/attempts/*/events.jsonl"))
    base = Path(events).parent
    requests, bad = {}, []
    for line in Path(events).read_text().splitlines():
        e = json.loads(line)
        if e["event_type"] == "logical_action_started":
            req = json.loads((base / e["payload_ref"]).read_text())["request"]
            requests[e["logical_action_id"]] = req
        elif e["event_type"] in ("action_parsed", "action_legality_checked"):
            pl = json.loads((base / e["payload_ref"]).read_text())
            res = pl.get("parse_result") or pl.get("legality_result")
            req = requests[e["logical_action_id"]]
            if req["seat_id"] != "tenant_0":
                continue
            if res.get("ok") is False or res.get("legal") is False:
                bad.append({"phase_id": req["phase_id"], "round_index": req["observation"].get("round_index"),
                            "code": res.get("error_code") or res.get("reason")})
    return bad


def reference_view(seed: int, arm: str) -> dict[str, Any]:
    market = pr.run_world(seed, arm, pr.inspect_lowball_action)
    world = market.world
    leased = dict(market.pairs)
    out = {"net": pr.seat_net(market), "spend": float(market.inspection_spend[0]), "leased": 0 in leased}
    if out["leased"]:
        l = leased[0]
        out.update(listing=l, rent=float(market.signed_rent[0]),
                   surplus=round(float(world.values[0][l]) - float(market.signed_rent[0]), 2),
                   quality="lemon" if world.quality[l] == lemons.LEMON else "sound")
    else:
        out["surplus"] = 0.0
    return out


def analyse_cell(row: dict[str, Any], cid: str) -> dict[str, Any]:
    """Features of one completed cell, and its class under the published and the corrected measure."""
    seed, arm = int(row["world_seed"]), row["arm"]
    cell_json = RUNS / cid / "live" / f"world_{seed}__{arm}.json"
    raw = json.loads(cell_json.read_text())
    facts = raw["outcome_facts"]
    world = pr.make_world(seed, arm)
    scored = pe.score_cell(facts, world_seed=seed, arm=arm)
    seat = scored["by_seat"][0]
    assert abs(seat["net_expected_response_odds"] - row["net_expected_response_odds"]) < TOL
    h = h7.score_cell(cell_json)  # HL-D-07: per blind signing p_published / p_full, and the corrected primary
    assert abs(h["primary_published"] - row["net_expected_response_odds"]) < TOL
    ref = reference_view(seed, arm)
    assert abs(ref["net"] - row["reference_net"]) < TOL, (cid, seed, arm)
    decisions = [d for d in scored["decisions"] if d["tenant_id"] == 0]
    signed = [d for d in decisions if d["decision"] == "sign"]
    assert len(signed) <= 1
    walks = [d for d in decisions if d["decision"] == "walk"]
    invalid = seat0_invalid(cell_json)
    spend = float(seat["inspection_spend"])
    out = {"world_seed": seed, "arm": arm, "population": row["population"], "stratum": row["stratum"],
           "reference": ref, "spend": spend, "invalid_actions": invalid,
           "walks": [{"round_index": d["round_index"], "listing_id": d["listing_id"], "rent": d["rent"],
                      "ev_stated": d["expected_value_stated"], "ev_response": d["expected_value_response"],
                      "informed": d["informed"], "revealed_lemon": d["reply_revealed_lemon"]} for d in walks]}
    blind = {(b["round_index"], b["listing_id"]): b for b in h["blind_signings"]}
    for measure in ("published", "corrected"):
        primary = row["net_expected_response_odds"] if measure == "published" else h["primary_corrected"]
        gap = round(ref["net"] - primary, 2)
        lease = None
        if signed:
            d = signed[0]
            l = d["listing_id"]
            sound_value = float(world.values_if_sound[0][l])
            if d["informed"]:
                p, value = (1.0 if d["quality"] == "lemon" else 0.0), float(d["true_value"])
                settled_by = "inspection"
            else:
                b = blind[(d["round_index"], l)]
                p = b["p_published"] if measure == "published" else b["p_full"]
                value = b["v_published"] if measure == "published" else b["v_full"]
                settled_by = "reply or elimination" if p in (0.0, 1.0) else None
            inspect_gain = p * (LOSS - (sound_value - d["rent"])) - FEE if 0.0 < p < 1.0 else None
            lease = {"listing_id": l, "round_index": d["round_index"], "rent": d["rent"], "informed": d["informed"],
                     "quality": d["quality"], "p_lemon": p, "value_at_measure": value,
                     "surplus": round(value - d["rent"], 2), "settled_by": settled_by,
                     "below_sound_floor": d["rent"] < pe.sound_floor(world, l) - 1e-6,
                     "inspection_was_worth_it": None if inspect_gain is None else inspect_gain > 0}
        cls, rule = classify(lease, ref, spend, invalid, gap, out["walks"])
        out[measure] = {"primary": round(primary, 2), "gap": gap, "lease": lease, "class": cls, "rule": rule}
        if lease is not None:
            # for the reading only (not classes): gap = listing choice at the landlord's floor + rent above that
            # floor + inspection spend above the reference's
            res = world.reservation_cost(lease["listing_id"])
            floor = round(max(res, min(float(world.ask[lease["listing_id"]]), res + pe.LANDLORD_MARGIN)), 2)
            premium = round(lease["rent"] - floor, 2)
            spend_diff = round(spend - ref["spend"], 2)
            out[measure]["pieces"] = {"listing_choice_at_floor": round(gap - premium - spend_diff, 2),
                                      "rent_above_landlord_floor": premium, "inspection_spend_above_reference": spend_diff}
    return out


def classify(lease, ref, spend, invalid, gap, walks=()) -> tuple[str, str]:
    """The first rule that fires, in PRIORITY order. ``lease`` carries p_lemon at the measure's information."""
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


def run() -> dict[str, Any]:
    rows = [json.loads(l) for l in (V14 / "tables/cells.jsonl").read_text().splitlines()]
    result: dict[str, Any] = {"case": "housing_v14", "unit": "USD per world (mean of the two landlord arms)",
                              "subjects": {}, "checks": {}}
    for cid, name in PANEL.items():
        mine = [r for r in rows if r["campaign_id"] == cid]
        cells = {}
        for r in mine:
            if r["status"] == "completed":
                cells[(r["world_seed"], r["arm"])] = analyse_cell(r, cid)
        missing = [r for r in mine if r["status"] != "completed"]
        subj: dict[str, Any] = {"campaign_id": cid, "planned_cells": len(mine), "completed_cells": len(cells),
                                "missing_cells": {"total": len(missing),
                                                  "main": sum(r["population"] == "main" for r in missing),
                                                  "by_condition": dict(Counter(r["failure_condition"] or r["status"] for r in missing))},
                                "measures": {}}
        for measure in ("published", "corrected"):
            subj["measures"][measure] = {}
            for scope, stratum in (("main", None), ("main_favourite_is_lemon", "favourite_is_lemon"),
                                   ("main_favourite_is_sound", "favourite_is_sound")):
                subj["measures"][measure][scope] = aggregate(cells, mine, measure, stratum)
        # reproduce the published headline before trusting anything else
        pub = subj["measures"]["published"]["main"]["total_shortfall_per_world"]
        assert abs(pub + PUBLISHED_MINUS_REFERENCE[cid]) < 0.006, (cid, pub)
        subj["reproduced_published_minus_reference"] = -pub
        # every scope, both measures, against the published analysis and the HL-D-07 results
        published = json.loads((V14 / "reports/analysis.json").read_text())["models"][cid]["by_scope"]
        hl = json.loads(HL_D_07_RESULTS.read_text())["corrected"]["v14"]["models"][HL_SHORT[cid]]
        for scope in ("main", "main_favourite_is_lemon", "main_favourite_is_sound"):
            got = subj["measures"]["published"][scope]["total_shortfall_per_world"]
            assert abs(got + published[scope]["minus_reference"]["mean"]) < 0.006, (cid, scope, got)
            got = subj["measures"]["corrected"][scope]["total_shortfall_per_world"]
            assert abs(got + hl[scope]["minus_reference"]["mean"]) < 0.006, (cid, scope, "corrected", got)
        subj["reproduced_corrected_minus_reference_hl_d_07"] = -subj["measures"]["corrected"]["main"]["total_shortfall_per_world"]
        subj["instances"] = [{"world_seed": c["world_seed"], "arm": c["arm"], "population": c["population"],
                              "stratum": c["stratum"],
                              **{m: {k: c[m][k] for k in ("gap", "class", "rule")} for m in ("published", "corrected")}}
                             for c in sorted(cells.values(), key=lambda c: (c["world_seed"], c["arm"]))]
        subj["diagnostics"] = diagnostics(cells)
        result["subjects"][name] = subj
    return result


def aggregate(cells, rows, measure, stratum) -> dict[str, Any]:
    by_world: dict[int, dict[str, dict]] = defaultdict(dict)
    planned = defaultdict(set)
    for r in rows:
        if r["population"] == "main" and (stratum is None or r["stratum"] == stratum):
            planned[r["world_seed"]].add(r["arm"])
    for (seed, arm), c in cells.items():
        if c["population"] == "main" and (stratum is None or c["stratum"] == stratum):
            by_world[seed][arm] = c[measure]
    worlds = {s: arms for s, arms in by_world.items() if len(arms) == 2}
    per_class = {k: 0.0 for k in CLASSES}
    counts = {k: 0 for k in CLASSES}
    nonzero = {k: 0 for k in CLASSES}
    gross = {k: {"positive": 0.0, "negative": 0.0} for k in CLASSES}
    pieces = {k: defaultdict(float) for k in ("worse_terms", "information_not_acquired", "contrary_to_information_held")}
    for s, arms in worlds.items():
        for arm, m in arms.items():
            per_class[m["class"]] += m["gap"] / 2.0
            counts[m["class"]] += 1
            nonzero[m["class"]] += abs(m["gap"]) > TOL
            gross[m["class"]]["positive" if m["gap"] > 0 else "negative"] += m["gap"] / 2.0
            if m["class"] in pieces:
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
            "reading_pieces_per_world": {k: {g: round(v / n, 4) for g, v in d.items()} for k, d in pieces.items()},
            "operational": {"missing_cells": missing_cells, "worlds_left_out": len(dropped_worlds),
                            "completed_cells_left_out_with_their_world": sum(len(by_world.get(s, {})) for s in dropped_worlds)}}


def diagnostics(cells) -> dict[str, Any]:
    """Counts that show how often a rule's edge case occurred, for the ambiguity report."""
    out: dict[str, Any] = {}
    for measure in ("published", "corrected"):
        rules = Counter(c[measure]["rule"] for c in cells.values() if c["population"] == "main")
        blind_not_worth = sum(1 for c in cells.values() if c["population"] == "main" and c[measure]["class"] == "information_not_acquired"
                              and c[measure]["lease"]["inspection_was_worth_it"] is False)
        invalid_other = Counter()
        for c in cells.values():
            if c["population"] == "main" and c[measure]["class"] == "procedure_and_format":
                cls2, _ = classify(c[measure]["lease"], c["reference"], c["spend"], [], c[measure]["gap"], c["walks"])
                invalid_other[cls2] += 1
        neg = Counter(c[measure]["class"] for c in cells.values() if c["population"] == "main" and c[measure]["gap"] < -TOL)
        out[measure] = {"rules_fired_main": dict(rules), "blind_signings_where_inspecting_was_not_worth_the_fee": blind_not_worth,
                        "procedure_cells_next_class_if_procedure_ignored": dict(invalid_other),
                        "negative_gap_cells_by_class": dict(neg)}
    out["no_lease_cells_main"] = {
        "walked_from_a_hold_worth_signing_at_stated_odds": sum(
            1 for c in cells.values() if c["population"] == "main" and c["published"]["lease"] is None
            and any(w["ev_response"] >= w["rent"] for w in c["walks"])),
        "total": sum(1 for c in cells.values() if c["population"] == "main" and c["published"]["lease"] is None)}
    return out


if __name__ == "__main__":
    res = run()
    (OUT / "housing_v14_taxonomy.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    for name, s in res["subjects"].items():
        for measure in ("published", "corrected"):
            m = s["measures"][measure]["main"]
            print(f"{name:18s} {measure:9s} total {m['total_shortfall_per_world']:8.2f} "
                  + " ".join(f"{k[:12]}={v:7.2f}({m['units'][k]})" for k, v in m["per_world"].items()))
        print("  ", json.dumps(s["diagnostics"]))
    sys.exit(0)
