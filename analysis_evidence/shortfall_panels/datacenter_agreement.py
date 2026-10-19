"""Data-center agreement case: joint value lost by failure class, per pairing.

Offline and read-only. Reads the published bundles' ``tables/cells.jsonl`` (the exact ``agreement.grade``
of every negotiation). Writes only to this folder.

Unit: one part of one negotiation's joint value lost. ``grade`` splits every negotiation's joint value
lost exactly into allocation + no deal + delay; each part is one unit and goes to one class by rule:

- an invalid negotiation (``termination == "invalid_action"``): its whole loss to Procedure and format;
- no deal where a deal was available (``no_deal_loss > 0``): Commitment error, by the seat that walked;
- a signed agreement in a world where no agreement beats both outside options (``available_surplus == 0``):
  its allocation part to Commitment error (signed what both should have refused);
- otherwise the allocation part (a worse clause set than the best one): Worse terms;
- the delay part (redline fees after the opening): Interaction cost, split by the seat that paid it;
- a negotiation with no measurement (``status != "ok"``): Operational, counted, never scored.

Per world is the mean over the negotiations of a pairing, all 58 development worlds (the published headline
uses the 52 deal worlds; both are reported and the headline is reproduced).

Run:
  python datacenter_agreement.py
"""
from __future__ import annotations

import os
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

WT = Path(os.environ["AEREAD_DATACENTER_ROOT"])  # a checkout of codex/datacenter-agreement
EVID = WT / "evidence/datacenter_development"
OUT = Path(__file__).resolve().parent
CLASSES = ("information_not_acquired", "contrary_to_information_held", "worse_terms", "commitment_error",
           "interaction_cost", "procedure_and_format", "operational")
NAMES = {"codex_sol61": "Sol 6.1", "claude_opus55": "Opus 5.5"}
GROUPS = {
    "head_to_head": ["datacenter_agreement_cli_pair_dev_v1", "datacenter_agreement_cli_pair_reverse_dev_v1",
                     "datacenter_agreement_cli_pair_spread_dev_v1", "datacenter_agreement_cli_pair_rest_dev_v1"],
    "vs_firm_population": ["datacenter_agreement_cli_scripted_canary_v1", "datacenter_agreement_cli_scripted_rest_v1"],
}
PAIRINGS = {
    "Sol integrator vs Opus client": ("head_to_head", "codex_integrator__claude_client"),
    "Opus integrator vs Sol client": ("head_to_head", "claude_integrator__codex_client"),
    "Sol integrator vs firm client": ("vs_firm_population", "codex_integrator__negotiator_drawn_client"),
    "Opus integrator vs firm client": ("vs_firm_population", "claude_integrator__negotiator_drawn_client"),
    "Sol client vs firm integrator": ("vs_firm_population", "negotiator_drawn_integrator__codex_client"),
    "Opus client vs firm integrator": ("vs_firm_population", "negotiator_drawn_integrator__claude_client"),
}
HEADLINE_52 = {"Sol integrator vs Opus client": 82.0, "Opus integrator vs Sol client": 79.0}  # write-up, 52 deal worlds
TOL = 1e-6


def rows(bundles: list[str]) -> list[dict[str, Any]]:
    out = []
    for b in bundles:
        for line in (EVID / b / "tables/cells.jsonl").read_text().splitlines():
            r = json.loads(line)
            r["_bundle"] = b
            out.append(r)
    return out


def seat_round_costs(r: dict[str, Any]) -> dict[str, float]:
    """Each seat's redline fees: the integrator's opening redline is free, every later redline costs one round."""
    paid = {"integrator": max(0, r["edits"]["integrator"]["redlines"] - 1), "client": r["edits"]["client"]["redlines"]}
    n = paid["integrator"] + paid["client"]
    if n == 0:
        assert r["delay_loss"] < TOL
        return {"integrator": 0.0, "client": 0.0}
    per = r["delay_loss"] / n
    return {s: per * k for s, k in paid.items()}


def units_of(r: dict[str, Any]) -> list[dict[str, Any]]:
    """The parts of one graded negotiation, each with its class and rule."""
    if r["status"] != "ok":
        return [{"class": "operational", "rule": f"no measurement ({r['status']})", "amount": 0.0, "seat": None}]
    total = r["joint_value_lost"]
    parts = r["allocation_loss"] + r["no_deal_loss"] + r["delay_loss"]
    assert abs(total - parts) < 1e-5, (r["cell_key"], total, parts)
    if r["termination"] == "invalid_action":
        return [{"class": "procedure_and_format", "rule": "an invalid move ended the negotiation", "amount": total,
                 "seat": r["invalid_by"]}]
    out = []
    if r["no_deal_loss"] > TOL:
        out.append({"class": "commitment_error", "rule": f"walked from an available deal ({r['walked_by']} walked)",
                    "amount": r["no_deal_loss"], "seat": r["walked_by"]})
    if abs(r["allocation_loss"]) > TOL:
        if r["available_surplus"] <= TOL:
            out.append({"class": "commitment_error", "rule": "signed where no agreement beats both outside options",
                        "amount": r["allocation_loss"], "seat": r["offered_by"]})
        else:
            out.append({"class": "worse_terms", "rule": "signed a clause set worth less together than the best one",
                        "amount": r["allocation_loss"], "seat": None})
    if r["delay_loss"] > TOL:
        for seat, fee in seat_round_costs(r).items():
            if fee > TOL:
                out.append({"class": "interaction_cost", "rule": f"redline fees paid by the {seat}", "amount": fee, "seat": seat})
    assert abs(sum(u["amount"] for u in out) - total) < 1e-5, r["cell_key"]
    return out


def aggregate(cells: list[dict[str, Any]], deal_worlds_only: bool) -> dict[str, Any]:
    ok = [r for r in cells if r["status"] == "ok" and (not deal_worlds_only or r["available_surplus"] > TOL)]
    n = len(ok)
    per = {k: 0.0 for k in CLASSES}
    counts = {k: 0 for k in CLASSES}
    by_rule: dict[str, float] = defaultdict(float)
    by_rule_n: Counter = Counter()
    for r in ok:
        for u in units_of(r):
            per[u["class"]] += u["amount"]
            counts[u["class"]] += 1
            by_rule[f"{u['class']}: {u['rule']}"] += u["amount"]
            by_rule_n[f"{u['class']}: {u['rule']}"] += 1
    total = sum(r["joint_value_lost"] for r in ok) / n
    per_world = {k: v / n for k, v in per.items()}
    assert abs(sum(per_world.values()) - total) < 1e-9, (sum(per_world.values()), total)
    counts["operational"] = sum(1 for r in cells if r["status"] != "ok")
    return {"worlds": n, "total_shortfall_per_world": round(total, 6),
            "per_world": {k: round(v, 6) for k, v in per_world.items()},
            "share": {k: (round(v / total, 6) if total else None) for k, v in per_world.items()},
            "units": counts, "by_rule_per_world": {k: round(v / n, 4) for k, v in sorted(by_rule.items())},
            "by_rule_count": dict(sorted(by_rule_n.items()))}


def side_commitment(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Each model's signatures below its own walk-away point, by seat and opponent, and who put the terms on the table."""
    out: dict[str, Any] = {}
    for label, (group, pairing) in PAIRINGS.items():
        cells = [r for r in all_rows if r["_group"] == group and r["pairing"] == pairing and r["status"] == "ok"]
        entry = {}
        for seat in ("integrator", "client"):
            model = cells[0][seat]
            if model not in NAMES:
                continue
            flag = f"{seat}_ir_violation"
            bad = [r for r in cells if r[flag]]
            loss = [round(-(r[f"{seat}_surplus"] + 0.0), 3) for r in bad]
            entry[f"{NAMES[model]} as {seat}"] = {
                "negotiations": len(cells), "signed": sum(r["termination"] == "signed" for r in cells),
                "below_own_walk_away": len(bad),
                "below_own_walk_away_deal_worlds": sum(1 for r in bad if r["available_surplus"] > TOL),
                "terms_put_on_the_table_by_itself": sum(1 for r in bad if r["offered_by"] == seat),
                "terms_put_on_the_table_by_the_other_side": sum(1 for r in bad if r["offered_by"] != seat),
                "own_surplus_in_those_negotiations_usd_k": sorted(round(r[f"{seat}_surplus"], 3) for r in bad),
                "walked_from_an_available_deal": sum(1 for r in cells if r["walked_by"] == seat and r["no_deal_loss"] > TOL),
            }
        out[label] = entry
    return out


def run() -> dict[str, Any]:
    all_rows = []
    for group, bundles in GROUPS.items():
        for r in rows(bundles):
            r["_group"] = group
            all_rows.append(r)
    result: dict[str, Any] = {"case": "datacenter_agreement", "unit": "$k of joint value lost per world (negotiation)",
                              "pairings": {}, "side_level_commitment_errors": side_commitment(all_rows),
                              "bundles": GROUPS}
    for label, (group, pairing) in PAIRINGS.items():
        cells = [r for r in all_rows if r["_group"] == group and r["pairing"] == pairing]
        worlds = Counter(r["world"] for r in cells)
        assert len(worlds) == 58 and max(worlds.values()) == 1, (label, len(worlds))
        a58, a52 = aggregate(cells, False), aggregate(cells, True)
        if label in HEADLINE_52:
            assert abs(round(a52["total_shortfall_per_world"]) - HEADLINE_52[label]) < 1e-9, (label, a52["total_shortfall_per_world"])
        result["pairings"][label] = {"group": group, "pairing": pairing, "bundles": sorted({r["_bundle"] for r in cells}),
                                     "all_58_worlds": a58, "deal_worlds_52": a52,
                                     "missing": [{"world": r["world"], "status": r["status"]} for r in cells if r["status"] != "ok"]}
    # each model against the firm population, both seats: per world the mean of its two seatings, over the
    # worlds where both seatings were measured (as Housing averages its two arms)
    for model, (as_int, as_cli) in {"Sol 6.1": ("Sol integrator vs firm client", "Sol client vs firm integrator"),
                                    "Opus 5.5": ("Opus integrator vs firm client", "Opus client vs firm integrator")}.items():
        seatings = {}
        for label in (as_int, as_cli):
            group, pairing = PAIRINGS[label]
            seatings[label] = {r["world"]: r for r in all_rows if r["_group"] == group and r["pairing"] == pairing}
        entry = {"seatings": [as_int, as_cli]}
        for scope, deal_only in (("all_58_worlds", False), ("deal_worlds_52", True)):
            worlds = sorted(w for w in seatings[as_int] if all(seatings[l][w]["status"] == "ok" for l in seatings)
                            and (not deal_only or seatings[as_int][w]["available_surplus"] > TOL))
            per = {k: 0.0 for k in CLASSES}
            counts = {k: 0 for k in CLASSES}
            for w in worlds:
                for l in seatings:
                    for u in units_of(seatings[l][w]):
                        per[u["class"]] += u["amount"] / 2.0
                        counts[u["class"]] += 1
            total = sum(statistics.fmean(seatings[l][w]["joint_value_lost"] for l in seatings) for w in worlds) / len(worlds)
            per_world = {k: v / len(worlds) for k, v in per.items()}
            assert abs(sum(per_world.values()) - total) < 1e-9
            counts["operational"] = sum(1 for l in seatings for r in seatings[l].values() if r["status"] != "ok")
            entry[scope] = {"worlds": len(worlds), "total_shortfall_per_world": round(total, 6),
                            "per_world": {k: round(v, 6) for k, v in per_world.items()},
                            "share": {k: (round(v / total, 6) if total else None) for k, v in per_world.items()},
                            "units": counts,
                            "worlds_left_out": sorted(w for w in seatings[as_int] if any(seatings[l][w]["status"] != "ok" for l in seatings))}
        result["pairings"][f"{model} vs firm population (both seats)"] = entry
    # the summary's per-pairing means agree with the cells (per bundle)
    for b in [x for v in GROUPS.values() for x in v]:
        summary = json.loads((EVID / b / "reports/summary.json").read_text())
        mine = [r for r in all_rows if r["_bundle"] == b]
        for pairing, s in summary["pairings"].items():
            ok = [r for r in mine if r["pairing"] == pairing and r["status"] == "ok"]
            assert abs(statistics.fmean(r["joint_value_lost"] for r in ok) - s["joint_value_lost_mean"]) < 1e-3, (b, pairing)
    return result


if __name__ == "__main__":
    res = run()
    (OUT / "datacenter_agreement_taxonomy.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    for label, p in res["pairings"].items():
        for scope in ("all_58_worlds", "deal_worlds_52"):
            m = p[scope]
            if "by_rule_per_world" not in m:
                m = dict(m, by_rule_per_world={}, by_rule_count={})
            print(f"{label:32s} {scope:14s} total {m['total_shortfall_per_world']:7.2f} "
                  + " ".join(f"{k[:12]}={v:6.2f}({m['units'][k]})" for k, v in m["per_world"].items() if v or m['units'][k]))
        for k, v in p["all_58_worlds"].get("by_rule_per_world", {}).items():
            print(f"      {v:7.2f} {p['all_58_worlds']['by_rule_count'][k]:3d} {k}")
    print(json.dumps(res["side_level_commitment_errors"], indent=1))
