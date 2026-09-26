"""Why each Refund V2.1 policy model falls short of the answer key.

A derived analysis in the Tier 1 sense: it reads only the published V2.1
bundles under ``evidence/refund/`` (``tables/refund_results_by_scenario.csv``,
``tables/benchmark_results.csv``, ``trajectories/sanitized.jsonl``) and the
cases rebuilt from ``v2_environment.build_1n_panel``, and regenerates
byte-identical output (``--check``).

**The answer key.** Every case states the authorized decision, amount and
method; the scripted canonical run reaches exactly that on all 120 cells,
which is checked here. A model cell is *resolved* when it passes both policy
compliance and transaction correctness, as the family scores it.

**Decomposition.** A model's shortfall from the answer key, in percentage
points of cells resolved, splits exactly into parts, one per failing cell,
chosen by the first thing that went wrong in its trajectory:

- procedure: ``decided_before_required_facts`` (the policy seat decided before
  every required fact was revealed; the environment rejects the decision and
  the case ends), ``re_requested_known_fact`` and ``requested_unknown_fact``
  (a fact request the environment rejects, which also ends the case);
- format: ``denial_method_null`` (a denial the answer key agrees with, written
  with ``method: null`` where the key says ``"none"``; the prompt says "deny
  with amount 0 and method none" and the schema allows null);
- outcome: ``wrong_decision``, ``wrong_amount_or_method``, ``transaction_error``.

Each part is cross-checked against the verifier reasons the bundle publishes.

**The unit is the case.** ``build_1n_case`` ignores the world seed, so the 20
seeds of a scenario repeat one case (RF-D-01): there are six distinct cases.
Means are taken per case and then over the six; no interval is reported,
because six clusters do not support one.

The reports follow ``aeread.gap_decomposition/0.1``, one per model with the
model on the left and the answer key on the right, and the Examiner renders
them like any other family's.

    python -m aeread_families.refund.v2_gap --write
    python -m aeread_families.refund.v2_gap --check
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import v2_environment

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence" / "refund"
OUT = EVIDENCE / "refund_v2_1_gap"
REFERENCE = "refund_v2_1_canonical_scripted_20_2026-09-12"
MODELS: tuple[tuple[str, str], ...] = (
    ("deepseekv4flash", "refund_v2_1_deepseekv4flash_controlled_2026-09-12"),
    ("gemini25flashlite", "refund_v2_1_gemini25flashlite_controlled_2026-09-12"),
    ("gpt56luna", "refund_v2_1_gpt56luna_controlled_2026-09-12"),
    ("grok43", "refund_v2_1_grok43_controlled_2026-09-12"),
)
CELL = 100.0  # one unresolved cell costs 100 percentage points of that cell

COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("decided_before_required_facts", "decided before a required fact", "procedure",
     "The policy seat approved or denied before every required fact was revealed; the environment rejects the decision and the case ends unresolved."),
    ("re_requested_known_fact", "asked again for a known fact", "procedure",
     "The policy seat requested a fact already revealed; the environment rejects the request and the case ends before any decision."),
    ("requested_unknown_fact", "asked for a fact the case lacks", "procedure",
     "The policy seat requested a field the case does not define; the environment rejects it and the case ends before any decision."),
    ("denial_method_null", "correct denial, method null", "format",
     "A denial the answer key agrees with, written with method null where the key says \"none\"."),
    ("wrong_decision", "wrong decision", "outcome",
     "A completed proposal that approves where the key denies, or denies where it approves."),
    ("wrong_amount_or_method", "wrong amount or method", "outcome",
     "The right decision with an amount or method the key does not authorize."),
    ("transaction_error", "transaction not as proposed", "outcome",
     "The right proposal, but the payment was not executed exactly once as the key requires."),
)
_REJECTED = {"decision_before_required_facts": "decided_before_required_facts",
             "repeated_fact": "re_requested_known_fact", "unknown_fact": "requested_unknown_fact"}
_PROCEDURE_REASON = "missing_proposal"
_TERMS_REASON = "policy_terms_mismatch"

CLASSES: dict[str, dict[str, str]] = {
    "right_outcome_skipped_procedure": {
        "group": "procedure", "label": "decided before a required fact, and the decision matched the answer key",
        "amount": "share of cells, percentage points"},
    "wrong_outcome_skipped_procedure": {
        "group": "outcome", "label": "decided before a required fact, and the decision contradicted the answer key",
        "amount": "share of cells, percentage points"},
    "no_decision_reached": {
        "group": "procedure", "label": "the case ended on a rejected fact request before any decision",
        "amount": "share of cells, percentage points"},
    "right_outcome_format_only": {
        "group": "format", "label": "a correct denial failed only on method null against \"none\"",
        "amount": "share of cells, percentage points"},
    "wrong_outcome": {
        "group": "outcome", "label": "a completed proposal with the wrong decision, amount or method",
        "amount": "share of cells, percentage points"},
}
VERIFIER_REASONS = ("missing_proposal", "invalid_fact_request", "required_facts_missing",
                    "policy_terms_mismatch", "transaction_not_exactly_once")


def _csv(bundle: str, table: str) -> list[dict[str, str]]:
    with (EVIDENCE / bundle / "tables" / table).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _steps(bundle: str) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for line in (EVIDENCE / bundle / "trajectories" / "sanitized.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by[row["source_receipt_sha256"]].append(row)
    for rows in by.values():
        rows.sort(key=lambda r: r["step_index"])
    return by


def _reasons(bundle: str) -> dict[str, tuple[str, ...]]:
    out = {}
    for row in _csv(bundle, "benchmark_results.csv"):
        if row.get("metric_name") == "refund_v21_policy_compliance":
            out[row["receipt_sha256"]] = tuple(json.loads(row["metric_metadata"] or "{}").get("verifier_reasons") or ())
    return out


def answer_key(case_id: str) -> dict[str, Any]:
    """The authorized resolution of a case, rebuilt from its definition."""
    _, _, scenario, seed = case_id.split(".")
    case = next(c for c in v2_environment.build_1n_panel(int(seed)) if c.scenario == scenario)
    if case.case_id != case_id:
        raise ValueError(f"rebuilt case {case.case_id} does not match {case_id}")
    return {"decision": "approve_direct" if case.authorized_refund_amount > 0 else "deny",
            "amount": float(case.authorized_refund_amount), "method": case.authorized_refund_method,
            "required_facts": tuple(case.required_facts), "scenario": scenario, "seed": int(seed)}


def _model(bundle: str) -> str:
    for row in _csv(bundle, "profiles.csv"):
        if "_policy_" in row["profile_id"]:
            return row["requested_model"]
    raise ValueError(f"{bundle} names no policy profile")


def _at(step: Mapping[str, Any]) -> dict[str, Any]:
    return {"step_index": int(step["step_index"]), "phase_id": step["phase_id"], "seat_id": step["seat_id"]}


def analyse_cell(result: Mapping[str, str], steps: Sequence[Mapping[str, Any]], reasons: Sequence[str]) -> dict[str, Any]:
    """The part a cell's shortfall belongs to, the step that decided it, and its classes."""
    key = answer_key(result["case_id"])
    resolved = result["policy_compliance"] == "1.0" and result["transaction_correctness"] == "1.0"
    parts = {name: 0.0 for name, *_ in COMPONENTS}
    if resolved:
        if reasons or any((s.get("outcome") or {}).get("valid") is False for s in steps):
            raise ValueError(f"{result['case_id']} is resolved but carries a rejected step or a verifier reason")
        return {"parts": parts, "component": None, "at": None, "note": None, "classes": [], "right_outcome": True}
    revealed: set[str] = set()
    for step in steps:
        action = step["action"] if isinstance(step["action"], dict) else {}
        outcome = step.get("outcome") or {}
        if outcome.get("valid") is False:
            code = outcome.get("failure_code")
            if code not in _REJECTED or step["seat_id"] != "policy":
                raise ValueError(f"{result['case_id']}: unexpected rejected step {code} at {step['seat_id']}")
            if _PROCEDURE_REASON not in reasons:
                raise ValueError(f"{result['case_id']}: a rejected step without the published {_PROCEDURE_REASON}")
            component = _REJECTED[code]
            missing = [f for f in key["required_facts"] if f not in revealed]
            if component == "decided_before_required_facts":
                matched = action.get("decision") == key["decision"]
                note = (f"{action.get('decision')} before {', '.join(missing)} was revealed; "
                        f"the answer key {'also ' if matched else ''}says {key['decision']}")
                cls = "right_outcome_skipped_procedure" if matched else "wrong_outcome_skipped_procedure"
                right = matched
            else:
                asked = list(action.get("requested_fields") or [])
                known = set(key["required_facts"]) | set(revealed)
                culprits = [f for f in asked if f in revealed] if component == "re_requested_known_fact" else [f for f in asked if f not in known]
                note = (f"asked for {', '.join(asked)}; {', '.join(culprits) or 'a field'} "
                        f"{'was already revealed' if component == 're_requested_known_fact' else 'is not a field of this case'}; "
                        f"the case ended with no decision (key: {key['decision']})")
                cls, right = "no_decision_reached", False
            parts[component] = -CELL
            return {"parts": parts, "component": component, "at": _at(step), "note": note, "classes": [cls], "right_outcome": right}
        if step["phase_id"] == "customer_facts":
            revealed.update(action.get("reveal_fields") or [])
    decisions = [s for s in steps if s["seat_id"] == "policy" and (s["action"] or {}).get("decision") in ("approve_direct", "deny")]
    if not decisions:
        raise ValueError(f"{result['case_id']}: unresolved with no rejected step and no decision")
    step = decisions[-1]
    proposal = step["action"]
    amount, method = float(proposal.get("amount") or 0.0), proposal.get("method")
    if _TERMS_REASON not in reasons and result["policy_compliance"] != "1.0":
        raise ValueError(f"{result['case_id']}: failed policy compliance without {_TERMS_REASON}")
    if proposal["decision"] != key["decision"]:
        component, cls, right = "wrong_decision", "wrong_outcome", False
        note = f"{proposal['decision']} at {amount:g} where the answer key says {key['decision']} at {key['amount']:g}"
    elif key["decision"] == "deny" and method is None and amount == key["amount"]:
        component, cls, right = "denial_method_null", "right_outcome_format_only", True
        note = "denied as the answer key does, with method null where the key says \"none\""
    elif amount != key["amount"] or method != key["method"]:
        component, cls, right = "wrong_amount_or_method", "wrong_outcome", False
        note = f"{proposal['decision']} at {amount:g} to {method} where the answer key says {key['amount']:g} to {key['method']}"
    else:
        payments = [s for s in steps if s["phase_id"] == "payments_execute"]
        step = payments[-1] if payments else step
        component, cls, right = "transaction_error", "wrong_outcome", False
        note = "the proposal matched the answer key, but the payment was not executed exactly once"
    parts[component] = -CELL
    return {"parts": parts, "component": component, "at": _at(step), "note": note, "classes": [cls], "right_outcome": right}


def _side(bundle: str, side: str) -> list[dict[str, Any]]:
    steps, reasons = _steps(bundle), _reasons(bundle)
    cells = []
    for result in _csv(bundle, "refund_results_by_scenario.csv"):
        if result["status"] != "ok" or result["inclusion_status"] != "included":
            continue
        rec = result["receipt_sha256"]
        analysed = analyse_cell(result, steps.get(rec, []), reasons.get(rec, ()))
        key = answer_key(result["case_id"])
        cells.append({"side": side, "campaign_id": bundle, "receipt_sha256": rec, "case_id": result["case_id"],
                      "unit": key["scenario"], "world_seed": key["seed"], "replicate_index": key["seed"],
                      "stratum": "refund due" if key["decision"] == "approve_direct" else "denial due",
                      "reasons": reasons.get(rec, ()), **analysed})
    return cells


def _check_reference(cells: Sequence[Mapping[str, Any]]) -> None:
    steps = _steps(REFERENCE)
    for cell in cells:
        if cell["component"] is not None:
            raise ValueError(f"the answer key's own run failed {cell['case_id']}")
        key = answer_key(cell["case_id"])
        final = [s["action"] for s in steps[cell["receipt_sha256"]] if s["seat_id"] == "policy" and s["action"].get("decision") in ("approve_direct", "deny")][-1]
        if (final["decision"], float(final["amount"]), final["method"]) != (key["decision"], key["amount"], key["method"]):
            raise ValueError(f"the canonical run's resolution of {cell['case_id']} differs from the case definition")


def _unit_mean(cells: Sequence[Mapping[str, Any]], pick) -> float:
    by: dict[str, list[float]] = collections.defaultdict(list)
    for cell in cells:
        by[cell["unit"]].append(pick(cell))
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def _outcome_view(cells: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    share = lambda f: round(100.0 * sum(1 for c in cells if f(c)) / len(cells), 4)
    return {"resolved_as_scored": share(lambda c: c["component"] is None),
            "right_outcome": share(lambda c: c["right_outcome"]),
            "no_decision_reached": share(lambda c: "no_decision_reached" in c["classes"]),
            "wrong_outcome": share(lambda c: any(k.startswith("wrong_outcome") for k in c["classes"]))}


def _report(label: str, bundle: str, left: list[dict[str, Any]], right: list[dict[str, Any]],
            panel: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    def block(pick) -> dict[str, Any]:
        a, b = _unit_mean(left, pick), _unit_mean(right, pick)
        return {"left": round(a, 6), "right": round(b, 6), "difference": round(a - b, 6), "difference_ci": None}

    components = [{"key": k, "label": lab, "group": grp, "description": desc, **block(lambda c, k=k: c["parts"][k])}
                  for k, lab, grp, desc in COMPONENTS]
    classes = []
    for key, meta in CLASSES.items():
        amounts = block(lambda c, key=key: CELL if key in c["classes"] else 0.0)
        classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": meta["amount"],
                        "left_count": sum(key in c["classes"] for c in left), "right_count": sum(key in c["classes"] for c in right),
                        "left_amount_per_market": amounts["left"], "right_amount_per_market": amounts["right"],
                        "amount_difference": amounts["difference"], "amount_difference_ci": None})
    instances, table = [], []
    for cell in left:
        if cell["component"] is None:
            continue
        where = {"side": "left", "campaign_id": cell["campaign_id"], "receipt_sha256": cell["receipt_sha256"],
                 "world_seed": cell["world_seed"], "replicate_index": cell["replicate_index"], "unit": cell["unit"], **cell["at"]}
        table.append({**where, "component": cell["component"], "amount": -CELL, "note": cell["note"]})
        instances.extend({**where, "class": cls, "amount": -CELL, "note": cell["note"]} for cls in cell["classes"])
    sources = {b: hashlib.sha256((EVIDENCE / b / "publication_manifest.json").read_bytes()).hexdigest() for b in (bundle, REFERENCE)}
    residual = max(abs(sum(c["parts"].values()) - (0.0 if c["component"] is None else -CELL)) for c in left)
    report = {
        "schema_version": "aeread.gap_decomposition/0.1",
        "family": "refund", "world_kind": "refund_v2_1n",
        "title": "Why it falls short of the answer key",
        "left": bundle, "right": REFERENCE, "reference_side": "right",
        "left_model": _model(bundle), "right_model": "answer key (the scripted canonical policy)", "right_label": "answer key",
        "endpoint": "resolved: policy compliance and transaction correctness both pass",
        "unit": "percentage points of cells resolved, averaged per case then over cases",
        "unit_label": "case", "per_label": "case", "amount_label": "points",
        "class_heading": "failure class (judged against the answer key)",
        "direction": "higher", "claim_status": "descriptive_fixed_panel",
        "winner_claim_allowed": False, "inferential_model_ranking_allowed": False,
        "paired_worlds": len({c["unit"] for c in left}), "cells": {"left": len(left), "right": len(right)},
        "bootstrap": None,
        "intervals": "none: the 20 seeds of a scenario repeat one case (RF-D-01), so there are six clusters, too few for an interval",
        "realized": block(lambda c: sum(c["parts"].values())),
        "components": components,
        "accounting_check": {"max_abs_residual_per_cell": residual,
                             "statement": "each unresolved cell is exactly one part at minus 100 points; resolved cells are zero",
                             "max_abs_contribution_residual": 0.0,
                             "contribution_statement": "one contribution row per unresolved cell, equal to its part"},
        "outcome_view": {"left": _outcome_view(left), "right": _outcome_view(right),
                         "statement": "resolved as scored, against reaching the answer key's decision and terms whatever the procedure or format"},
        "published_reasons": {"reasons": list(VERIFIER_REASONS),
                              "left": {r: sum(r in c["reasons"] for c in left) for r in VERIFIER_REASONS},
                              "right": {r: sum(r in c["reasons"] for c in right) for r in VERIFIER_REASONS}},
        "classes": classes,
        "instances": sorted(instances, key=lambda i: (i["class"], i["unit"], i["world_seed"])),
        "panel": panel,
        "cell_parts": [{k: c[k] for k in ("side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit", "stratum", "parts")}
                       for c in sorted(left + right, key=lambda c: (c["side"], c["unit"], c["world_seed"]))],
        "contributions": {"table": f"tables/contributions_{label}.jsonl", "rows": len(table),
                          "fields": ["side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit",
                                     "step_index", "phase_id", "seat_id", "component", "amount", "note"]},
        "source_manifest_sha256": sources,
    }
    return report, sorted(table, key=lambda r: (r["unit"], r["world_seed"]))


def analyse() -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    reference = _side(REFERENCE, "right")
    _check_reference(reference)
    sides = {label: _side(bundle, "left") for label, bundle in MODELS}
    for label, cells in sides.items():
        if {c["case_id"] for c in cells} != {c["case_id"] for c in reference}:
            raise ValueError(f"{label} does not cover the answer key's cases")
    panel = [{"label": label, "campaign_id": bundle, "model": _model(bundle),
              "realized": round(_unit_mean(sides[label], lambda c: sum(c["parts"].values())), 6),
              "components": {k: round(_unit_mean(sides[label], lambda c, k=k: c["parts"][k]), 6) for k, *_ in COMPONENTS},
              "outcome_view": _outcome_view(sides[label])} for label, bundle in MODELS]
    return {label: _report(label, bundle, sides[label], reference, panel) for label, bundle in MODELS}


def _table_bytes(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _readme(reports: Mapping[str, tuple[dict[str, Any], list]]) -> str:
    first = next(iter(reports.values()))[0]
    panel = first["panel"]
    name = lambda m: str(m).split("/")[-1]
    head = "| part | " + " | ".join(name(p["model"]) for p in panel) + " |"
    rows = [head, "|---" * (len(panel) + 1) + "|",
            "| **resolved, minus the answer key** | " + " | ".join(f"**{p['realized']:.1f}**" for p in panel) + " |"]
    rows += [f"| {label} ({group}) | " + " | ".join(f"{p['components'][key]:.1f}" for p in panel) + " |"
             for key, label, group, _ in COMPONENTS]
    view = ["| cells | " + " | ".join(name(p["model"]) for p in panel) + " |", "|---" * (len(panel) + 1) + "|"]
    for key, label in (("resolved_as_scored", "resolved as scored"), ("right_outcome", "reached the answer key's outcome"),
                       ("no_decision_reached", "ended before any decision"), ("wrong_outcome", "reached a wrong outcome")):
        view.append(f"| {label} | " + " | ".join(f"{p['outcome_view'][key]:.1f}%" for p in panel) + " |")
    return "\n".join([
        f"# {OUT.name}",
        "",
        "Why each Refund V2.1 policy model falls short of the answer key (the scripted canonical policy, which resolves "
        "all 120 cells as the case definitions authorize). Derived from the published bundles and the cases rebuilt from "
        "their definitions by `python -m aeread_families.refund.v2_gap`; `--check` regenerates these bytes. Descriptive "
        "only: no winner, no ranking, no interval.",
        "",
        "The unit is the case. The 20 seeds of a scenario repeat one case (RF-D-01), so each number is a mean over the "
        "six cases of the share of cells, in percentage points. Every unresolved cell is exactly one part, chosen by the "
        "first thing that went wrong in its trajectory, so the parts sum to the shortfall.",
        "",
        *rows,
        "",
        "What the shortfall is made of, per model (share of its 120 cells):",
        "",
        *view,
        "",
        "Procedure parts end the case at a rejected step; a correct denial written with `method: null` fails on the "
        "string \"none\" alone (RF-D-03). Each model's report is `reports/gap_decomposition_<model>.json`, with every "
        "unresolved cell and the step that decided it; `tables/contributions_<model>.jsonl` gives one row per unresolved "
        "cell.",
        "",
    ])


def write() -> None:
    reports = analyse()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    for label, (report, table) in reports.items():
        (OUT / "reports" / f"gap_decomposition_{label}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        (OUT / "tables" / f"contributions_{label}.jsonl").write_text(_table_bytes(table))
    (OUT / "README.md").write_text(_readme(reports))


def check() -> bool:
    reports = analyse()
    ok = (OUT / "README.md").exists() and (OUT / "README.md").read_text() == _readme(reports)
    for label, (report, table) in reports.items():
        rp, tp = OUT / "reports" / f"gap_decomposition_{label}.json", OUT / "tables" / f"contributions_{label}.jsonl"
        ok = ok and rp.exists() and rp.read_text() == json.dumps(report, indent=2, sort_keys=True) + "\n"
        ok = ok and tp.exists() and tp.read_text() == _table_bytes(table)
    print("refund gap analysis regenerates to the committed bytes" if ok else "refund gap analysis differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    if args.check:
        return 0 if check() else 1
    for label, (report, _) in analyse().items():
        print(label, report["realized"]["difference"], {c["key"]: c["difference"] for c in report["components"] if c["difference"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
