"""Assemble the cross-case failure taxonomy from the four case outputs: taxonomy.json and summary.md.

Run the four case scripts first (see run_all.sh), then:
  python -I build.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent
CLASSES = [
    ("information_not_acquired", "Information not acquired"),
    ("contrary_to_information_held", "Acted contrary to information held"),
    ("worse_terms", "Worse terms"),
    ("commitment_error", "Commitment error"),
    ("interaction_cost", "Interaction cost"),
    ("procedure_and_format", "Procedure and format"),
    ("operational", "Operational"),
]
CANNOT = {"datacenter_agreement": {"information_not_acquired", "contrary_to_information_held"},
          "refund_v2_1": {"commitment_error", "interaction_cost"}}
TOL = 1e-9


def block(per_world: dict, share: dict, units: dict, total: float, case: str, extra: dict | None = None) -> dict[str, Any]:
    classes = {}
    for k, _ in CLASSES:
        if k in CANNOT.get(case, ()):
            classes[k] = {"amount_per_world": None, "share": None, "units": None, "cannot_occur": True}
        elif k == "operational":
            classes[k] = {"amount_per_world": None, "share": None, "units": units.get(k, 0),
                          "note": "missing cells (typed missingness): counted, never scored"}
        else:
            classes[k] = {"amount_per_world": per_world[k], "share": share[k], "units": units[k]}
    s = sum(v["amount_per_world"] or 0.0 for v in classes.values())
    assert abs(s - total) < 1e-5, (case, s, total)  # the per-class figures are rounded to 1e-6 when written
    return {"total_shortfall_per_world": total, "classes": classes, **(extra or {})}


def main() -> None:
    h = json.loads((OUT / "housing_v14_taxonomy.json").read_text())
    p = json.loads((OUT / "procurement_pay_or_test_taxonomy.json").read_text())
    d = json.loads((OUT / "datacenter_agreement_taxonomy.json").read_text())
    r = json.loads((OUT / "refund_v21_taxonomy.json").read_text())
    tax: dict[str, Any] = {
        "schema_version": "aeread.paper_failure_taxonomy/0.1",
        "convention": "aeread.gap_decomposition/0.1: every shortfall unit is assigned to exactly one class, so the classes "
                      "sum exactly to the shortfall; negative units (the subject beat the reference) are included",
        "classes": [{"key": k, "label": lab} for k, lab in CLASSES],
        "definitions": "definitions.md", "cases": {}}

    # Housing
    hc = {"unit": "USD per world, seat 0 net at the measure, reachable reference (inspect_lowball) minus model; "
                  "a world is the mean of its two landlord arms; main pack", "subjects": {}}
    for name, s in h["subjects"].items():
        entry = {"campaign_id": s["campaign_id"], "missing_cells": s["missing_cells"],
                 "reproduced_published_minus_reference": s["reproduced_published_minus_reference"],
                 "reproduced_corrected_minus_reference_hl_d_07": s["reproduced_corrected_minus_reference_hl_d_07"]}
        for measure in ("published", "corrected"):
            for scope, m in s["measures"][measure].items():
                units = dict(m["units_nonzero_gap"], operational=m["units"]["operational"])
                entry[f"{measure}/{scope}"] = block(m["per_world"], m["share"], units, m["total_shortfall_per_world"], "housing_v14",
                                                    {"worlds": m["worlds"], "cells_by_class_including_zero_gap": m["units"],
                                                     "gross_per_world": m["gross_per_world"],
                                                     "reading_pieces_per_world": m["reading_pieces_per_world"],
                                                     "operational_detail": m["operational"]})
        entry["rules_fired"] = s["diagnostics"]
        hc["subjects"][name] = entry
    tax["cases"]["housing_v14"] = hc

    # Procurement
    pc = {"unit": "USD of decision loss per world (sum over actions of best informed value less the value of the action "
                  "taken), 24 worlds", "subjects": {}}
    for name, s in p["subjects"].items():
        pc["subjects"][name] = block(s["per_world"], s["share"], s["units"], s["total_shortfall_per_world"], "procurement",
                                     {"run_root": s["run_root"], "worlds": s["worlds"],
                                      "reproduced_published_decision_loss": s["reproduced_published_decision_loss"],
                                      "by_rule_per_world": s["by_rule_per_world"], "by_rule_count": s["by_rule_count"],
                                      "report_parts_per_world": s["report_parts_per_world"],
                                      "award_actions_with_both_timing_and_terms_loss": s["award_actions_with_both_timing_and_terms_loss"]})
    tax["cases"]["procurement_pay_or_test_v1"] = pc

    # Data center
    dc = {"unit": "$k of joint value lost per world; deal_worlds_52 is the published headline basis",
          "subjects": {}, "side_level_commitment_errors": d["side_level_commitment_errors"]}
    for label, s in d["pairings"].items():
        entry = {}
        for scope in ("deal_worlds_52", "all_58_worlds"):
            m = s[scope]
            entry[scope] = block(m["per_world"], m["share"], m["units"], m["total_shortfall_per_world"], "datacenter_agreement",
                                 {"worlds": m["worlds"], **({"by_rule_per_world": m["by_rule_per_world"]} if "by_rule_per_world" in m else {})})
        dc["subjects"][label] = entry
    tax["cases"]["datacenter_agreement"] = dc

    # Refund
    rc = {"unit": r["unit"], "mapping": r["mapping"], "source": r["source"], "subjects": {}}
    for name, s in r["subjects"].items():
        rc["subjects"][name] = block(s["per_world"], s["share"], s["units"], s["total_shortfall_per_world"], "refund_v2_1",
                                     {"bundle": s["bundle"], "parts_points": s["parts_points"], "outcome_view": s["outcome_view"]})
    tax["cases"]["refund_v2_1"] = rc
    (OUT / "taxonomy.json").write_text(json.dumps(tax, indent=1, sort_keys=True) + "\n")

    # summary.md: one table
    cols = []
    for name in ("Gemini 3.8 Flash", "GLM 5.3 Flash", "GPT-6 Luna"):
        s = hc["subjects"][name]
        cols.append((f"Housing $ · {name.replace(' Flash', '').replace('GPT-6 ', '')}", s["published/main"], s["corrected/main"]))
    for name, short in (("Sol 6.1 (Codex CLI)", "Sol 6.1"), ("Opus 5.5 (Claude Code, brief v2)", "Opus 5.5"),
                        ("Gemini 3.8 Flash", "Gemini 3.8"), ("GPT-6 Luna", "Luna")):
        cols.append((f"Procurement $ · {short}", pc["subjects"][name], None))
    for label, short in (("Sol integrator vs Opus client", "Sol int × Opus"), ("Opus integrator vs Sol client", "Opus int × Sol"),
                         ("Sol 6.1 vs firm population (both seats)", "Sol × firm"),
                         ("Opus 5.5 vs firm population (both seats)", "Opus × firm")):
        cols.append((f"Data center $k · {short}", dc["subjects"][label]["deal_worlds_52"], None))
    for name, short in (("DeepSeek V4 Flash", "DeepSeek V4"), ("Gemini 2.5 Flash Lite", "Gemini 2.5 FL"),
                        ("GPT-5.6 Luna", "GPT-5.6 Luna"), ("Grok 4.3", "Grok 4.3")):
        cols.append((f"Refund pts · {short}", rc["subjects"][name], None))

    def fmt(v):
        return f"{v:.1f}" if abs(v) >= 0.05 else ("0" if v == 0 else f"{v:.2f}")

    def cell(main, alt, k):
        c = main["classes"][k]
        if c.get("cannot_occur"):
            return "—"
        if k == "operational":
            return f"{c['units']} missing" if c["units"] else "0"
        s = fmt(c["amount_per_world"])
        if alt is not None:
            s += f" ({fmt(alt['classes'][k]['amount_per_world'])})"
        return s

    lines = ["# Cross-case failure taxonomy: the shortfall to each case's reference, by what went wrong", "",
             "Native units per world. Housing: published primary measure, HL-D-07-corrected in parentheses (main pack, mean of the "
             "two landlord arms). Procurement: decision loss against the best informed policy (prompt v2). Data center: joint value "
             "lost on the 52 deal worlds (the published headline basis); \"× firm\" averages the model's two seats against the "
             "scripted firm population. Refund: percentage points of cells unresolved. Every unit is in exactly one class, so "
             "each column sums to its total; negative entries are units where the subject beat the reference. — : the class "
             "cannot occur in that case. Operational: missing cells, counted, never scored. Rules: definitions.md.", "",
             "| Class | " + " | ".join(c[0] for c in cols) + " |",
             "|---|" + "---|" * len(cols)]
    for k, lab in CLASSES:
        lines.append(f"| {lab} | " + " | ".join(cell(m, a, k) for _, m, a in cols) + " |")
    tot = []
    for _, m, a in cols:
        s = f"**{fmt(m['total_shortfall_per_world'])}**"
        if a is not None:
            s += f" ({fmt(a['total_shortfall_per_world'])})"
        tot.append(s)
    lines.append("| **Total shortfall** | " + " | ".join(tot) + " |")
    lines.append("")
    (OUT / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
