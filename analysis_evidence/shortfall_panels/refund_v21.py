"""Refund V2.1: the published gap decomposition's parts, mapped to the shared failure classes.

Offline and read-only. Reads ``evidence/refund/refund_v2_1_gap`` from the branch ``codex/refund-gap-analysis``
with ``git show`` (no checkout) and each model bundle's ``tables/refund_results_by_scenario.csv`` for
missingness. Writes only to this folder.

Unit: the cell. The bundle already assigns every unresolved cell to exactly one part (-100 points), chosen by
the first thing that went wrong in its trajectory; this script maps each part to one class (MAPPING) and
recomputes the class shares from ``cell_parts`` (mean per case, then over the six cases), in points.

Run:
  python refund_v21.py
"""
from __future__ import annotations

import os
import csv
import io
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = os.environ.get("AEREAD_REPO", ".")  # any clone with the origin/codex/refund-gap-analysis ref
REF = "origin/codex/refund-gap-analysis"
GAP = "evidence/refund/refund_v2_1_gap"
OUT = Path(__file__).resolve().parent
MODELS = {"deepseekv4flash": "DeepSeek V4 Flash", "gemini25flashlite": "Gemini 2.5 Flash Lite",
          "gpt56luna": "GPT-5.6 Luna", "grok43": "Grok 4.3"}
CLASSES = ("information_not_acquired", "contrary_to_information_held", "worse_terms", "commitment_error",
           "interaction_cost", "procedure_and_format", "operational")
MAPPING = {
    "decided_before_required_facts": "information_not_acquired",
    "re_requested_known_fact": "procedure_and_format",
    "requested_unknown_fact": "procedure_and_format",
    "denial_method_null": "procedure_and_format",
    "wrong_decision": "contrary_to_information_held",
    "wrong_amount_or_method": "worse_terms",
    "transaction_error": "procedure_and_format",
}
CANNOT_OCCUR = ("commitment_error", "interaction_cost")  # one decision, no counterpart to sign with or haggle against


def show(path: str) -> str:
    return subprocess.run(["git", "-C", REPO, "show", f"{REF}:{path}"], check=True, capture_output=True, text=True).stdout


def run() -> dict[str, Any]:
    out: dict[str, Any] = {"case": "refund_v2_1", "unit": "percentage points of cells unresolved, mean per case then over the six cases",
                           "source": f"{REF}:{GAP}", "mapping": MAPPING, "cannot_occur": list(CANNOT_OCCUR), "subjects": {}}
    for key, name in MODELS.items():
        d = json.loads(show(f"{GAP}/reports/gap_decomposition_{key}.json"))
        assert d["schema_version"] == "aeread.gap_decomposition/0.1"
        bundle = d["left"]
        results = list(csv.DictReader(io.StringIO(show(f"evidence/refund/{bundle}/tables/refund_results_by_scenario.csv"))))
        missing = [r for r in results if r["status"] != "ok" or r["inclusion_status"] != "included"]
        cells = [c for c in d["cell_parts"] if c["side"] == "left"]
        assert len(cells) == len(results) - len(missing) == d["cells"]["left"]
        by_case: dict[str, list[dict[str, float]]] = defaultdict(list)
        part_by_case: dict[str, list[dict[str, float]]] = defaultdict(list)
        for c in cells:
            assert sum(v != 0 for v in c["parts"].values()) <= 1 and all(v in (0.0, -100.0) for v in c["parts"].values())
            cls = {k: 0.0 for k in CLASSES}
            for part, v in c["parts"].items():
                cls[MAPPING[part]] += -v  # shortfall is positive
            by_case[c["unit"]].append(cls)
            part_by_case[c["unit"]].append({p: -v for p, v in c["parts"].items()})

        def mean_over_cases(table, k):
            return sum(sum(x[k] for x in rows) / len(rows) for rows in table.values()) / len(table)

        per = {k: mean_over_cases(by_case, k) for k in CLASSES}
        parts = {p: mean_over_cases(part_by_case, p) for p in MAPPING}
        total = sum(per.values())
        assert abs(total - sum(parts.values())) < 1e-9
        # against the published numbers (rounded to 1e-6 there)
        assert abs(total + d["realized"]["left"]) < 1e-5, (key, total, d["realized"])
        for comp in d["components"]:
            assert abs(parts[comp["key"]] + comp["left"]) < 1e-5, (key, comp["key"])
        counts = {k: sum(1 for c in cells for p, v in c["parts"].items() if v and MAPPING[p] == k) for k in CLASSES}
        counts["operational"] = len(missing)
        out["subjects"][name] = {
            "bundle": bundle, "model": d["left_model"], "cells": len(cells), "cases": len(by_case),
            "total_shortfall_per_world": round(total, 6),
            "per_world": {k: round(v, 6) for k, v in per.items()},
            "share": {k: (round(v / total, 6) if total else None) for k, v in per.items()},
            "units": counts, "parts_points": {p: round(v, 6) for p, v in parts.items()},
            "published_classes": {c["key"]: {"count": c["left_count"], "points": -c["left_amount_per_market"]} for c in d["classes"]},
            "outcome_view": d["outcome_view"]["left"],
        }
    return out


if __name__ == "__main__":
    res = run()
    (OUT / "refund_v21_taxonomy.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    for name, s in res["subjects"].items():
        print(f"{name:22s} total {s['total_shortfall_per_world']:6.2f} "
              + " ".join(f"{k[:12]}={v:6.2f}({s['units'][k]})" for k, v in s["per_world"].items()))
