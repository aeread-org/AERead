"""Procurement pay-or-test v3, the 20 declared worlds: decision loss by failure class.

Offline and read-only. The rules are version 1's (``procurement_pay_or_test.py``), extended for what version 3 adds,
and fixed before the flash models' plays were seen (``pay_or_test_v3_flash_plan.md``):

- a source lookup (``look_up_source``) is a request. A lookup that can no longer move a belief (its kind's sharing
  already settled, or the listing already looked up) is ``interaction_cost``. A lookup with loss otherwise is
  ``contrary_to_information_held``: the stated odds made another move better.
- a newcomer is shown bad in one of two ways, late or poor (version 2's ``BAD_STATES``), in place of version 1's one;
- an unanswered quote is a chance outcome of a request, not an action of its own, so a repeated quote to a newcomer
  that has not answered can still show something and is priced like any request;
- the best set at each point includes lookups, so "a newcomer test was worth it" counts a lookup of a newcomer;
- ``check_award`` is the only stray: it costs no money or days but spends an action.

Unit: the action; its loss is the best informed value at that point less the value of the action taken, exactly as
``pay_or_test_v3_reference.score_actions`` prices it (checked step by step). A play's class amounts sum its actions; a
world's are the mean over its plays; a subject's per-world figure is the mean over the 20 worlds.

Run (paths are a checkout of codex/procurement-pay-or-test, and the four run roots):
  AEREAD_PROCUREMENT_ROOT=... AEREAD_V3_RUNS=<dir holding the run roots> PYTHONDONTWRITEBYTECODE=1 \\
      python procurement_pay_or_test_v3.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

WT = Path(os.environ["AEREAD_PROCUREMENT_ROOT"])
RUNS = Path(os.environ["AEREAD_V3_RUNS"])
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(WT / "src"))

from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_v3_reference as R  # noqa: E402
from aeread_families.procurement_allocation.environment import evaluate_award  # noqa: E402
from aeread_families.procurement_allocation.pay_or_test_reference import QUALIFIED, _complete, _step  # noqa: E402
from aeread_families.procurement_allocation.pay_or_test_v2_reference import BAD_STATES  # noqa: E402

SUBJECTS = {
    "Sol 6.1 (Codex)": "pay_or_test_v3_confirm_cli_codex_sol61",
    "Opus 5.5 (Claude Code)": "pay_or_test_v3_confirm_cli_claude_opus55",
    "Gemini 3.8 Flash": "pay_or_test_v3_confirm_v3_openrouter_gemini38_flash_v1",
    "GPT-6 Luna": "pay_or_test_v3_confirm_v3_openrouter_gpt6_luna_v1",
}
CLASSES = ("information_not_acquired", "contrary_to_information_held", "worse_terms", "commitment_error",
           "interaction_cost", "procedure_and_format", "operational")
EPS = 1e-9
STRAYS = ("check_award",)


def best_set(ref: R.Reference, seen, left: int, day: int) -> list[tuple]:
    """Every action whose value equals the best policy's value here (ties included); requests include lookups."""
    target = ref.value(seen, left, day)
    out = []
    award_value, supplier, quantity = ref.best_award(seen, day)
    if supplier is not None and award_value >= target - EPS:
        out.append(("submit_award", supplier, quantity))
    if left > 1:
        for kind, who in ref.requests(seen):
            if ref.request_value(seen, left, day, kind, who) >= target - EPS:
                out.append((kind, who))
    if ref.defer_value >= target - EPS:
        out.append(("defer",))
    return out


def classify(ref, seen, best, kind, supplier, award_supplier, timing, touched_before, touched_ever, rejected):
    newcomers, established = set(ref.newcomers), set(ref.established)
    best_info = [b for b in best if b[0] in R.REQUESTS]
    best_newcomer = [b for b in best_info if b[1] in newcomers]
    if rejected:
        return "procedure_and_format", "an action the environment rejected (priced as walking away)"
    if kind == "defer":
        return "commitment_error", "walked away (defer) where an award or a test was worth more"
    if kind in STRAYS:
        return "interaction_cost", "check_award: spends an action and shows nothing quotes and samples had not"
    if kind == R.LOOKUP:
        if not ref.lookup_informs(seen, supplier):
            return "interaction_cost", "a lookup that could show nothing new"
        return "contrary_to_information_held", "looked a source up where the stated odds made another move better"
    if kind in ("request_quote", "request_sample"):
        if all(nxt == seen for _p, nxt in ref.outcomes(seen, kind, supplier)):
            return "interaction_cost", "a request that could show nothing new (repeat, or a supplier already settled)"
        if supplier in established and best_newcomer:
            if not touched_ever:
                return "information_not_acquired", "worked toward the recorded supplier and never tested a newcomer where a test was worth it"
            if any(seen[i] in BAD_STATES for i in touched_before):
                return "contrary_to_information_held", "went to the recorded supplier after a bad newcomer where another test was worth it"
            return "contrary_to_information_held", "secured the recorded supplier before a newcomer test the odds and clock made best first"
        if supplier in newcomers:
            if not best_newcomer:
                return "contrary_to_information_held", "tested a newcomer where the stated odds and clock made paying best"
            if supplier not in {b[1] for b in best_newcomer}:
                return "contrary_to_information_held", "tested a newcomer the stated odds and prices made the worse test"
            return "contrary_to_information_held", "worked a newcomer's test in an order its stated fees and days made worse"
        if supplier in established:
            return "contrary_to_information_held", "worked the recorded supplier's qualification in a worse order or at a worse time"
        raise AssertionError("request on an unknown supplier")
    if kind == "submit_award":
        if timing > EPS:
            if any(b[1] == award_supplier for b in best_info) and seen[award_supplier] != QUALIFIED:
                return "information_not_acquired", "awarded before the awarded supplier's required quote or sample"
            if best_newcomer and not touched_ever:
                return "information_not_acquired", "awarded the recorded supplier where the best policy tested a newcomer first"
            if best_newcomer and any(seen[i] in BAD_STATES for i in touched_before):
                return "contrary_to_information_held", "stopped after a bad newcomer where another test was worth it"
            if best_newcomer:
                return "contrary_to_information_held", "awarded while a newcomer test begun was still worth finishing"
            return "information_not_acquired", "awarded where a further request was worth more"
        if award_supplier is not None and seen[award_supplier] in BAD_STATES:
            return "contrary_to_information_held", "awarded a supplier its own quote or sample showed bad"
        if award_supplier is not None and seen[award_supplier] != QUALIFIED:
            return "information_not_acquired", "awarded a supplier before its required quote or sample"
        return "worse_terms", "awarded a qualified supplier at a worse supplier choice or quantity"
    raise AssertionError(kind)


def analyse_play(payload: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    keep = ("action", "supplier_id", "award_lines", "reason")
    actions = [{k: v for k, v in s.items() if k in keep} for s in row["action_trace"] if s["action"] != "unparseable"]
    scored = R.score_actions(payload, actions)
    ref = R.Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    newcomers = set(ref.newcomers)
    touched: list[int] = []
    executed = {ref.index[s["supplier_id"]] for s in scored["steps"]
                if s["valid"] and s["supplier_id"] in ref.index and ref.index[s["supplier_id"]] in newcomers
                and s["action"] in R.REQUESTS}
    units = []
    for i, step in enumerate(scored["steps"]):
        rejected = not step["valid"]
        seen = ref.status_of(state)
        left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
        best = best_set(ref, seen, left, day)
        action = _complete(ref, actions[i])
        kind = action.get("action")
        supplier = ref.index.get(action.get("supplier_id")) if kind in R.REQUESTS else None
        award_supplier, timing = None, 0.0
        best_value = ref.value(seen, left, day)
        if kind == "submit_award" and not rejected:
            sid = state["offers"][action["award_lines"][0]["offer_id"]]["supplier_id"]
            award_supplier = ref.index[sid]
            result = evaluate_award(ref.case, award_lines=action["award_lines"], offers=state["offers"],
                                    quality_evidence=state["quality_evidence"], elapsed_days=day, information_cost_usd=0.0)
            taken = float(result["contribution_margin_usd"]) if result["feasible"] else ref.defer_value
            best_now = ref.best_award(seen, day)[0]
            timing = max(0.0, best_value - best_now)
            loss = timing + (best_now - taken)
        elif rejected or kind == "defer":
            loss = best_value - ref.defer_value
        else:
            loss = best_value - ref.request_value(seen, left, day, kind, supplier)
        assert abs(loss - float(step["loss_usd"])) < 1e-3, (row["case_id"], i, loss, step["loss_usd"])
        cls, rule = (None, "no loss") if abs(loss) < 1e-6 else classify(
            ref, seen, best, "rejected" if rejected else kind, supplier, award_supplier, timing, list(touched),
            bool(executed), rejected)
        units.append({"action": kind, "supplier_id": action.get("supplier_id"), "loss_usd": loss, "class": cls, "rule": rule})
        if rejected:
            break
        state, _ = _step(ref, state, action)
        if kind in R.REQUESTS and supplier in newcomers and supplier not in touched:
            touched.append(supplier)
    total = sum(u["loss_usd"] for u in units)
    assert abs(total - scored["decision_loss_usd"]) < 1e-3, (row["case_id"], total, scored["decision_loss_usd"])
    return {"decision_loss_usd": total, "units": units}


def run() -> dict[str, Any]:
    manifest = json.loads((pack.pack_root(pack.CONFIRM_PACK_ID) / "pack.json").read_text())
    by_case = {w["case_id"]: w for w in manifest["worlds"]}
    payloads = {json.loads(p.read_text())["case_id"]: json.loads(p.read_text())["payload"]
                for p in pack.case_paths(split=pack.CONFIRM_PACK_ID)}
    out: dict[str, Any] = {"case": "procurement_pay_or_test_v3_confirm", "unit": "USD of decision loss per world",
                           "subjects": {}}
    for name, root_name in SUBJECTS.items():
        root = RUNS / root_name
        if not (root / "summary.json").exists():
            continue
        artifact = json.loads((root / "summary.json").read_text())
        plays: dict[str, list[dict[str, Any]]] = {}
        missing = []
        for row in artifact["rows"]:
            w = by_case[row["case_id"]]
            if row.get("status") != "completed":
                missing.append({"slug": w["slug"], "failure": row.get("failure_condition") or row.get("error_type")})
                continue
            res = analyse_play(payloads[row["case_id"]], row)
            per = {k: 0.0 for k in CLASSES}
            for u in res["units"]:
                if u["class"]:
                    per[u["class"]] += u["loss_usd"]
            plays.setdefault(w["slug"], []).append({**res, "per_class": per})
        worlds = {slug: {k: statistics.fmean(p["per_class"][k] for p in ps) for k in CLASSES} for slug, ps in plays.items()}
        n = len(worlds)
        per_world = {k: statistics.fmean(w[k] for w in worlds.values()) for k in CLASSES}
        total = sum(per_world.values())
        rules = Counter((u["class"], u["rule"]) for ps in plays.values() for p in ps for u in p["units"] if u["class"])
        out["subjects"][name] = {
            "run_root": root_name, "campaign_id": artifact["plan"]["campaign_id"], "worlds": n,
            "plays": sum(len(ps) for ps in plays.values()), "missing_cells": missing,
            "total_shortfall_per_world": round(total, 6),
            "per_world": {k: round(v, 6) for k, v in per_world.items()},
            "share": {k: (round(v / total, 6) if total else None) for k, v in per_world.items()},
            "by_rule_count": {f"{c}: {r}": v for (c, r), v in sorted(rules.items())},
            # Per world (the mean of its plays), the shape derive_panels.py reads for the paper's panels.
            "worlds_detail": [{"slug": slug, "per_class": {k: round(worlds[slug][k], 9) for k in CLASSES},
                               "decision_loss_usd": round(statistics.fmean(p["decision_loss_usd"] for p in plays[slug]), 9)}
                              for slug in sorted(worlds)],
        }
    return out


if __name__ == "__main__":
    result = run()
    (OUT / "procurement_pay_or_test_v3_taxonomy.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: {"total": v["total_shortfall_per_world"], "worlds": v["worlds"], "plays": v["plays"]}
                      for k, v in result["subjects"].items()}, indent=1))
