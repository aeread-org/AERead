"""Procurement pay-or-test (pay_or_test_v1, prompt v2 "finalquotes"): decision loss by failure class.

Offline and read-only. Replays each subject's sealed action trace through the worktree's environment and
``pay_or_test_reference.Reference`` and prices every action exactly as ``score_actions`` does (the report
tool's ``score_trace`` is called and every per-action loss is checked against it). Writes only to this folder.

Unit: the action. Its loss (best informed value at that point less the value of the action taken) goes to
one class by what the action did and what the buyer had learned, in PRIORITY order. A world's class amount is
the sum over its actions; per world is the mean over the 24 worlds.

Run:
  PYTHONDONTWRITEBYTECODE=1 python procurement_pay_or_test.py
"""
from __future__ import annotations

import os
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

WT = Path(os.environ["AEREAD_PROCUREMENT_ROOT"])  # a checkout of codex/procurement-pay-or-test with its runs/
CLI_RUNS = Path(os.environ["AEREAD_PROCUREMENT_CLI_RUNS"])  # the directory holding the two CLI run roots
sys.path[:0] = [str(WT / "src"), str(WT / "tools/cli_subjects")]
OUT = Path(__file__).resolve().parent

import pay_or_test_report as report  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_reference as por  # noqa: E402
from aeread_families.procurement_allocation.environment import evaluate_award  # noqa: E402

SUBJECTS = {
    "Sol 6.1 (Codex CLI)": CLI_RUNS / "pay_or_test_v1_finalquotes_codex_cli_sol61_v1",
    "Opus 5.5 (Claude Code, brief v2)": CLI_RUNS / "pay_or_test_v1_finalquotes_claude_code_opus55_v1",
    "Gemini 3.8 Flash": WT / "runs/procurement_allocation/pay_or_test_v1_finalquotes_openrouter_gemini38_flash_v2",
    "GPT-6 Luna": WT / "runs/procurement_allocation/pay_or_test_v1_finalquotes_openrouter_gpt6_luna_v2",
}
PUBLISHED_LOSS = {"Sol 6.1 (Codex CLI)": 1.0, "Opus 5.5 (Claude Code, brief v2)": 5.4, "Gemini 3.8 Flash": 75.2, "GPT-6 Luna": 74.4}
CLASSES = ("information_not_acquired", "contrary_to_information_held", "worse_terms", "commitment_error",
           "interaction_cost", "procedure_and_format", "operational")
PRIORITY = ("procedure_and_format", "information_not_acquired", "contrary_to_information_held", "commitment_error",
            "worse_terms", "interaction_cost")
EPS = 1e-9
STRAYS = ("inquire", "counter_offer", "check_award")


def best_set(ref: por.Reference, status, left, day) -> list[tuple]:
    """Every action whose value equals the best policy's value here (ties included)."""
    target = ref.value(status, left, day)
    out = []
    award_value, supplier, quantity = ref.best_award(status, day)
    if supplier is not None and award_value >= target - EPS:
        out.append(("submit_award", supplier, quantity))
    if left > 1:
        for kind, who in ref.requests(status):
            if ref.request_value(status, left, day, kind, who) >= target - EPS:
                out.append((kind, who))
    if ref.defer_value >= target - EPS:
        out.append(("defer",))
    return out


def classify_action(ref, status, best, kind, supplier, award_supplier, timing, terms, touched_before, touched_ever,
                    rejected) -> tuple[str, str]:
    newcomers = set(ref.newcomers)
    established = set(ref.established)
    best_requests = [b for b in best if b[0] in ("request_quote", "request_sample")]
    best_newcomer_tests = [b for b in best_requests if b[1] in newcomers]
    if rejected:
        return "procedure_and_format", "an action the environment rejected (priced as walking away)"
    if kind == "defer":
        return "commitment_error", "walked away (defer) where an award or a test was worth more"
    if kind in STRAYS:
        return "interaction_cost", f"{kind}: a move that costs and cannot change anything in this pack"
    if kind in ("request_quote", "request_sample"):
        if all(nxt == status for _p, nxt in ref.outcomes(status, kind, supplier)):
            return "interaction_cost", "a request that could show nothing new (repeat, or a supplier already settled)"
        if supplier in established and best_newcomer_tests:
            if not touched_ever:
                return "information_not_acquired", "worked toward the recorded supplier and never tested a newcomer where a test was worth it"
            if touched_before and any(status[i] == por.BAD for i in touched_before):
                return "contrary_to_information_held", "went to the recorded supplier after a bad newcomer where another test was worth it"
            return "contrary_to_information_held", "secured the recorded supplier before a newcomer test the odds and clock made best first"
        if supplier in newcomers:
            if not best_newcomer_tests:
                return "contrary_to_information_held", "tested a newcomer where the stated odds and clock made paying best"
            if supplier not in {b[1] for b in best_newcomer_tests}:
                return "contrary_to_information_held", "tested a newcomer the stated odds and prices made the worse test"
            return "contrary_to_information_held", "worked a newcomer's test in an order its stated fees and days made worse"
        if supplier in established:
            return "contrary_to_information_held", "worked the recorded supplier's qualification in a worse order or at a worse time"
        raise AssertionError("request on an unknown supplier")
    if kind == "submit_award":
        if timing > EPS:
            if any(b[1] == award_supplier for b in best_requests) and status[award_supplier] != por.QUALIFIED:
                return "information_not_acquired", "awarded before the awarded supplier's required quote or sample"
            if best_newcomer_tests and not touched_ever:
                return "information_not_acquired", "awarded the recorded supplier where the best policy tested a newcomer first"
            if best_newcomer_tests and any(status[i] == por.BAD for i in touched_before):
                return "contrary_to_information_held", "stopped after a bad newcomer where another test was worth it"
            if best_newcomer_tests:
                return "contrary_to_information_held", "awarded while a newcomer test begun was still worth finishing"
            return "information_not_acquired", "awarded where a further request was worth more"
        if award_supplier is not None and status[award_supplier] == por.BAD:
            return "contrary_to_information_held", "awarded a supplier its own quote or sample showed bad"
        if award_supplier is not None and status[award_supplier] != por.QUALIFIED:
            return "information_not_acquired", "awarded a supplier before its required quote or sample"
        return "worse_terms", "awarded a qualified supplier at a worse supplier choice or quantity"
    raise AssertionError(kind)


def analyse_world(payload: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    scored, margin = report.score_trace(payload, row)
    trace = [report.as_parsed(step) for step in row["action_trace"]]
    ref = por.Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    newcomers = set(ref.newcomers)
    touched: list[int] = []
    executed_newcomers = {ref.index[s["supplier_id"]] for s in scored["steps"]
                          if not s.get("rejected") and s["supplier_id"] in ref.index and ref.index[s["supplier_id"]] in newcomers
                          and s["action"] in ("request_quote", "request_sample")}
    units = []
    for i, step in enumerate(scored["steps"]):
        rejected = bool(step.get("rejected"))
        raw = trace[i]
        status = ref.status_of(state)
        left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
        assert left == step["actions_left"] and day == step["day"], (row["case_id"], i)
        best = best_set(ref, status, left, day)
        action = por._complete(ref, raw)
        kind = action.get("action")
        supplier = ref.index.get(action.get("supplier_id")) if kind in ("request_quote", "request_sample") else None
        award_supplier, timing, terms = None, 0.0, 0.0
        if kind == "submit_award" and not rejected:
            offer_id = action["award_lines"][0]["offer_id"]
            sid = state["offers"][offer_id]["supplier_id"]
            award_supplier = ref.index[sid]
            result = evaluate_award(ref.case, award_lines=action["award_lines"], offers=state["offers"],
                                    quality_evidence=state["quality_evidence"], elapsed_days=day, information_cost_usd=0.0)
            taken = float(result["contribution_margin_usd"]) if result["feasible"] else ref.defer_value
            best_now = ref.best_award(status, day)[0]
            timing = max(0.0, ref.value(status, left, day) - best_now)
            terms = best_now - taken
            assert abs(timing + terms - step["loss_usd"]) < 1e-3, (row["case_id"], i)
        # the loss unrounded (score_actions rounds each step to 1e-4); checked against the report's step
        best_value = ref.value(status, left, day)
        if rejected or kind == "defer":
            loss = best_value - ref.defer_value
        elif kind == "submit_award":
            loss = timing + terms
        else:
            loss = best_value - ref.request_value(status, left, day, kind, supplier)
        assert abs(loss - float(step["loss_usd"])) < 1e-3, (row["case_id"], i, loss, step["loss_usd"])
        cls, rule = (None, "no loss") if abs(loss) < 1e-6 else classify_action(
            ref, status, best, kind if not rejected else "rejected", supplier, award_supplier, timing, terms,
            list(touched), bool(executed_newcomers), rejected)
        units.append({"index": i, "action": "rejected:" + str(kind) if rejected else kind,
                      "supplier_id": action.get("supplier_id") if kind != "submit_award" else (ref.ids[award_supplier] if award_supplier is not None else None),
                      "status": dict(zip(ref.ids, status)), "best": [por._describe(ref, b) for b in best],
                      "loss_usd": loss, "award_timing_usd": round(timing, 4), "award_terms_usd": round(terms, 4),
                      "class": cls, "rule": rule})
        if rejected:
            break
        nxt, _valid = por._step(ref, state, action)
        if kind in ("request_quote", "request_sample") and supplier in newcomers and supplier not in touched:
            touched.append(supplier)
        state = nxt
    total = sum(u["loss_usd"] for u in units)
    assert abs(total - scored["decision_loss_usd"]) < 1e-3, (row["case_id"], total, scored["decision_loss_usd"])
    return {"decision_loss_usd": total, "units": units, "margin_usd": margin}


def run() -> dict[str, Any]:
    manifest, payloads = report.load_pack()
    by_case = {w["case_id"]: w for w in manifest["worlds"]}
    out: dict[str, Any] = {"case": "procurement_pay_or_test_v1", "unit": "USD of decision loss per world", "subjects": {}}
    for name, root in SUBJECTS.items():
        artifact = json.loads((root / "summary.json").read_text())
        worlds, missing = [], []
        for row in artifact["rows"]:
            w = by_case[row["case_id"]]
            if row.get("status") != "completed":
                missing.append({"slug": w["slug"], "failure": row.get("failure_condition") or row.get("error_type")})
                continue
            res = analyse_world(payloads[row["case_id"]], row)
            # each world's units sum to its decision loss; reclass the per-action loss into the seven classes
            per = {k: 0.0 for k in CLASSES}
            for u in res["units"]:
                if u["class"]:
                    per[u["class"]] += u["loss_usd"]
            unclassed = sum(u["loss_usd"] for u in res["units"] if not u["class"])
            assert abs(unclassed) < 1e-5, unclassed  # only zero-loss actions go unclassed
            per["information_not_acquired"] += 0.0
            res["decision_loss_usd"] = sum(u["loss_usd"] for u in res["units"] if u["class"])
            assert abs(sum(per.values()) - res["decision_loss_usd"]) < 1e-9
            worlds.append({"slug": w["slug"], "move": w["move"], "clock": w["clock"], **res, "per_class": per})
        n = len(worlds)
        total = statistics.fmean(w["decision_loss_usd"] for w in worlds)
        assert abs(round(total, 1) - PUBLISHED_LOSS[name]) < 0.051, (name, total)
        per_world = {k: sum(w["per_class"][k] for w in worlds) / n for k in CLASSES}
        assert abs(sum(per_world.values()) - total) < 1e-9
        counts = {k: sum(1 for w in worlds for u in w["units"] if u["class"] == k) for k in CLASSES}
        counts["operational"] = len(missing)
        rules = Counter((u["class"], u["rule"]) for w in worlds for u in w["units"] if u["class"])
        rule_amounts: dict[str, float] = {}
        for w in worlds:
            for u in w["units"]:
                if u["class"]:
                    key = f"{u['class']}: {u['rule']}"
                    rule_amounts[key] = rule_amounts.get(key, 0.0) + u["loss_usd"] / n
        both = sum(1 for w in worlds for u in w["units"] if u["award_timing_usd"] > EPS and abs(u["award_terms_usd"]) > EPS)
        negative = sum(1 for w in worlds for u in w["units"] if u["loss_usd"] < -EPS)
        out["subjects"][name] = {
            "run_root": str(root), "campaign_id": artifact["plan"]["campaign_id"], "worlds": n, "missing_cells": missing,
            "total_shortfall_per_world": round(total, 6), "reproduced_published_decision_loss": round(total, 1),
            "per_world": {k: round(v, 6) for k, v in per_world.items()},
            "share": {k: (round(v / total, 6) if total else None) for k, v in per_world.items()},
            "units": counts, "actions_total": sum(len(w["units"]) for w in worlds),
            "actions_with_no_loss": sum(1 for w in worlds for u in w["units"] if u["class"] is None),
            "by_rule_per_world": {k: round(v, 4) for k, v in sorted(rule_amounts.items())},
            "by_rule_count": {f"{c}: {r}": v for (c, r), v in sorted(rules.items())},
            "award_actions_with_both_timing_and_terms_loss": both, "actions_with_negative_loss": negative,
            "report_parts_per_world": {p: round(statistics.fmean(sum(
                (u["loss_usd"] if (p == "walk_away" and (u["action"] == "defer" or u["action"].startswith("rejected")))
                 or (p == "strays" and u["action"] in STRAYS)
                 or (p == "requests" and u["action"] in ("request_quote", "request_sample")) else 0.0)
                + (u["award_timing_usd"] if p == "award_timing" else 0.0) + (u["award_terms_usd"] if p == "award_terms" else 0.0)
                for u in w["units"]) for w in worlds), 4)
                for p in ("requests", "strays", "walk_away", "award_timing", "award_terms")},
            "worlds_detail": [{k: w[k] for k in ("slug", "move", "clock", "decision_loss_usd", "per_class")}
                              | {"trace": [{k: u[k] for k in ("action", "supplier_id", "loss_usd", "class", "rule", "best")} for u in w["units"]]}
                              for w in worlds],
        }
    return out


if __name__ == "__main__":
    res = run()
    (OUT / "procurement_pay_or_test_taxonomy.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    for name, s in res["subjects"].items():
        print(f"{name:34s} total {s['total_shortfall_per_world']:7.2f} "
              + " ".join(f"{k[:14]}={v:6.2f}({s['units'][k]})" for k, v in s["per_world"].items()))
        print("   report parts", s["report_parts_per_world"])
        for k, v in s["by_rule_per_world"].items():
            print(f"     {v:7.2f}  {s['by_rule_count'][k]:3d}  {k}")
        print("   both timing+terms:", s["award_actions_with_both_timing_and_terms_loss"], "negative:", s["actions_with_negative_loss"])
