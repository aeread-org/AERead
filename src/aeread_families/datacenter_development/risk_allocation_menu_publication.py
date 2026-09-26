"""Publish a playbook-menu campaign as an evidence bundle.

    python -m aeread_families.datacenter_development.risk_allocation_menu_publication runs/<campaign> evidence/datacenter_development/<campaign>

Reads only the campaign's cell records, sealed receipts and event logs. The bundle
holds receipt projections, one row per cell, the kernel trajectory grain, the
analysis the frozen plan declared (``reports/summary.json``) and a README.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.publication import assert_public_payload, atomic_publish, jsonl, receipt_projection, seal_publication_manifest
from aeread.shared_runner.run.publish_trajectories import publish_trajectory_grain
from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import risk_allocation_menu_pack as mp
from . import risk_allocation_publication as op

BOOTSTRAP_SEED = 20260927
MODELS = ("gemini38_flash", "glm53_flash")
SCRIPTED = "scripted_"
GRADE_FIELDS = ("valid", "invalid", "decision_regret", "playbook", "signed_item", "best_item", "best_is_deal", "best_outside", "signed_best_item",
                "walked_to", "price_over_floor", "realised_cost", "cost_over_best_attainable", "refused_counters")


def _key(r: dict[str, Any]) -> tuple[str, int]:
    return (r["world"], int(r.get("replicate_index") or 0))


def _paired(first: list[dict[str, Any]], second: list[dict[str, Any]], rng: random.Random) -> dict[str, Any] | None:
    a = {_key(r): r for r in first if r.get("valid")}
    diffs: dict[str, list[float]] = {}
    for r in second:
        if r.get("valid") and _key(r) in a:
            diffs.setdefault(op._cluster(r), []).append(r["decision_regret"] - a[_key(r)]["decision_regret"])
    flat = [x for d in diffs.values() for x in d]
    if not flat:
        return None
    return {"pairs": len(flat), "worlds": len(diffs), "mean_difference": round(statistics.fmean(flat), 3), "ci95": op._cluster_bootstrap(diffs, rng),
            "second_lower": sum(x < -1.0 for x in flat), "second_higher": sum(x > 1.0 for x in flat), "within_one": sum(abs(x) <= 1.0 for x in flat)}


def _run_to_run(rs: list[dict[str, Any]]) -> dict[str, Any] | None:
    by: dict[str, dict[int, dict[str, Any]]] = {}
    for r in rs:
        if r.get("valid"):
            by.setdefault(r["world"], {})[int(r.get("replicate_index") or 0)] = r
    both = [(w[0], w[1]) for w in by.values() if 0 in w and 1 in w]
    if not both:
        return None
    gaps = [b["decision_regret"] - a["decision_regret"] for a, b in both]
    means = [(a["decision_regret"] + b["decision_regret"]) / 2 for a, b in both]
    within = math.sqrt(statistics.fmean(g * g for g in gaps) / 2)
    between = statistics.pstdev(means) if len(means) > 1 else 0.0
    return {"worlds_with_both": len(both), "mean_abs_gap": round(statistics.fmean(abs(g) for g in gaps), 3), "within_world_sd": round(within, 3),
            "within_share_of_variance": round(within ** 2 / (within ** 2 + between ** 2), 3) if within or between else None,
            "same_choice_both_replicates": sum((a["signed_item"], a["walked_to"]) == (b["signed_item"], b["walked_to"]) for a, b in both)}


def analysis(rows: list[dict[str, Any]], arms: list[str], declared: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED)
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(f"{r['arm']}/{r['route_id']}", []).append(r)
    out: dict[str, Any] = {
        "declared": dict(declared),
        "intervals": f"95% percentile bootstrap, {op.BOOTSTRAP_DRAWS} draws, seed {BOOTSTRAP_SEED}, worlds resampled as clusters",
        "judges": "none: decision regret is an exact computation against the informed reference, and every receipt was replayed to the same digest",
        "run_to_run_variance": "per model group (`run_to_run`): two replicates per world under different request seeds",
        "groups": {},
    }
    for key, rs in sorted(groups.items()):
        valid = [r for r in rs if r.get("valid")]
        missing: dict[str, int] = {}
        for r in rs:
            if not r.get("valid"):
                cause = r.get("invalid") or r.get("failure_cause") or r.get("receipt_status") or "unsealed"
                missing[cause] = missing.get(cause, 0) + 1
        by_cluster: dict[str, list[float]] = {}
        for r in valid:
            by_cluster.setdefault(op._cluster(r), []).append(r["decision_regret"])
        deal_worlds = [r for r in valid if r["best_is_deal"]]
        walk_worlds = [r for r in valid if not r["best_is_deal"]]
        by_playbook = {}
        for pb in ("coordination", "managed", "turnkey"):
            xs = [r["decision_regret"] for r in valid if r["playbook"] == pb]
            by_playbook[pb] = {"valid": len(xs), "mean_regret": round(statistics.fmean(xs), 3) if xs else None}
        g = {
            "cells": len(rs), "valid": len(valid), "missing": missing,
            "decision_regret": ({**op._quantiles([r["decision_regret"] for r in valid]), "mean": round(statistics.fmean(r["decision_regret"] for r in valid), 3),
                                 "mean_ci95": op._cluster_bootstrap(by_cluster, rng)} if valid else None),
            "zero_regret": sum(r["decision_regret"] < 1.0 for r in valid),
            "signed_best_item": sum(bool(r["signed_best_item"]) for r in deal_worlds), "worlds_where_a_menu_item_is_best": len(deal_worlds),
            "walked_to_the_best_outside": sum(r["walked_to"] == r["best_outside"] for r in walk_worlds), "worlds_where_walking_is_best": len(walk_worlds),
            "mean_cost_over_best_attainable": round(statistics.fmean(r["cost_over_best_attainable"] for r in valid), 3) if valid else None,
            "mean_refused_counters": round(statistics.fmean(r["refused_counters"] for r in valid), 3) if valid else None,
            "exploratory_by_playbook": by_playbook,
        }
        if not key.split("/")[1].startswith(SCRIPTED):
            g["run_to_run"] = _run_to_run(rs)
        out["groups"][key] = g
    out["model_contrast_glm_minus_gemini"] = {
        arm: _paired(groups[f"{arm}/{MODELS[0]}"], groups[f"{arm}/{MODELS[1]}"], rng)
        for arm in arms if f"{arm}/{MODELS[0]}" in groups and f"{arm}/{MODELS[1]}" in groups
    }
    if "low_effort" in arms and "default_reasoning" in arms:
        out["default_minus_low"] = {m: _paired(groups.get(f"low_effort/{m}", []), groups.get(f"default_reasoning/{m}", []), rng) for m in MODELS}
    ref = out["groups"].get(f"scripted_controls/{SCRIPTED}reference")
    out["reference_is_zero_everywhere"] = bool(ref and ref["valid"] == ref["cells"] and (ref["decision_regret"] or {}).get("max", 1) < 1e-6)
    return out


def publish(run_dir: Path, bundle: Path) -> dict[str, Any]:
    plan = json.loads((run_dir / "campaign_plan.json").read_text())
    if bundle.exists():
        raise SystemExit(f"{bundle} exists; a published bundle is never edited")
    records = [json.loads(p.read_text()) for p in sorted((run_dir / "cells").glob("*.json"))]
    manifest, _ = mp.load(plan["pack"])
    worlds = {w["case_id"]: w for w in manifest["worlds"]}
    projections, rows, attempts = [], [], []
    for r in records:
        w = worlds.get(r["case_id"], {})
        base = {**{k: r.get(k) for k in ("cell_key", "arm", "route_id", "case_id", "replicate_index", "status")},
                "world": w.get("slug"), "world_cell": w.get("cell"), "twin_of": None}
        if not r.get("receipt_sha256"):
            rows.append({**base, "valid": False, "note": "no sealed receipt"})
            continue
        receipt_paths = list((run_dir / "evidence" / r["cell_key"]).rglob("evaluation_receipt.json"))
        receipt = json.loads(receipt_paths[0].read_text())
        if receipt["receipt_sha256"] != r["receipt_sha256"]:
            raise SystemExit(f"{r['cell_key']}: the record and the sealed receipt disagree")
        projections.append(receipt_projection(receipt, campaign_cell_key=r["cell_key"]))
        attempts.append(receipt_paths[0].parent)
        g = r.get("grade") or {}
        rows.append({**base, "receipt_sha256": r["receipt_sha256"], "receipt_status": r["status"], "termination": r.get("termination"),
                     "failure_cause": op._failure_cause(run_dir / "evidence" / r["cell_key"]) if r["status"] != "ok" else None,
                     "cost_usd": r.get("cost_usd"), "provider_calls": r.get("provider_calls"), "calls_outcome_unknown": r.get("calls_outcome_unknown"),
                     **{k: g.get(k) for k in GRADE_FIELDS}})
        rows[-1]["valid"] = bool(g.get("valid")) and r["status"] == "ok"
        if rows[-1]["playbook"] is None:
            rows[-1]["playbook"] = w.get("playbook")
    acc = op.accounting(plan, records, rows)
    acc["claim_scope"] = ("diagnostic: a declared paired contrast of two models negotiating a scripted integrator's posted playbook menu on one "
                          "generated pack, reported with intervals; not a model ranking and not a population estimate")
    summary = {"campaign_id": plan["campaign_id"], "plan_sha256": plan["plan_sha256"], "claim_status": plan["claim_status"], "arms": plan["arms"],
               "routes": sorted(plan["routes"]), "controls": plan["controls"], "analysis": analysis(rows, list(plan["arms"]), plan["declared_analysis"]),
               "cost_usd_total": acc["total_cost_usd"], **acc}
    for sub in ("receipts", "tables", "reports"):
        (bundle / sub).mkdir(parents=True, exist_ok=sub != "receipts")
    atomic_publish(bundle / "receipts" / "projections.jsonl", jsonl(projections))
    atomic_publish(bundle / "tables" / "cells.jsonl", jsonl(rows))
    atomic_publish(bundle / "reports" / "summary.json", canonical_json_bytes(summary) + b"\n")
    atomic_publish(bundle / "README.md", _readme(summary).encode())
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            assert_public_payload(str(path.relative_to(bundle)), path.read_bytes())
    seal_publication_manifest(
        bundle, publication_id=plan["campaign_id"], campaign_id=plan["campaign_id"],
        privacy_boundary={"included": "receipt projections, per-cell grades and diagnostics, the sanitized trajectory grain, the campaign summary",
                          "excluded": "provider request and response text, raw event logs and artifacts, which stay in the local run directory"},
        source_bindings={"campaign_plan_sha256": plan["plan_sha256"], "pack_manifest_sha256": plan["pack_manifest_sha256"], "sources": plan["sources"]},
        claim_status=plan["claim_status"],
    )
    rows_published, manifest_out = publish_trajectory_grain(bundle, attempts)
    grain = bundle / "trajectories" / "sanitized.jsonl"
    assert_public_payload(str(grain.relative_to(bundle)), grain.read_bytes())
    return {"bundle": str(bundle), "cells": len(rows), "receipts": len(projections), "trajectory_rows": rows_published, "manifest_sha256": manifest_out["manifest_sha256"]}


def _ci(ci: list[float] | None) -> str:
    return f" [{ci[0]}, {ci[1]}]" if ci else ""


def _readme(s: dict[str, Any]) -> str:
    a = s["analysis"]
    lines = [
        f"# {s['campaign_id']}", "",
        "The playbook-menu variant of the integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`): a scripted "
        "integrator posts one of three playbooks (coordination, managed, turnkey) with a menu pricing every combination of three negotiable options, "
        "by a policy the client is not told; the model, as client, accepts an item, counters one, or walks to a rival turnkey offer or to managing "
        "the deployment itself. Sealed, verified and replayed through the shared runner. It does not rank models.", "",
        "Decision regret ($ thousands) is what each move gave up against a client who knows how integrators in this market choose and price their "
        "menus, summed over the episode.", "",
        "| arm / client | valid | decision regret [95% CI] | zero regret | signed the best item | walked to the best outside option | cost over best attainable |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, g in a["groups"].items():
        d = g["decision_regret"] or {}
        lines.append(f"| {key} | {g['valid']}/{g['cells']} | {d.get('mean')}{_ci(d.get('mean_ci95'))} | {g['zero_regret']} | "
                     f"{g['signed_best_item']} of {g['worlds_where_a_menu_item_is_best']} | {g['walked_to_the_best_outside']} of {g['worlds_where_walking_is_best']} | "
                     f"{g['mean_cost_over_best_attainable']} |")
    d = a["declared"]
    lines += ["", "## The declared contrast", "", f"{d['primary']}. {d['interval']}. Positive means GLM gave up more.", "",
              "| arm | pairs (worlds) | GLM minus Gemini |", "|---|---|---|"]
    for arm, c in a["model_contrast_glm_minus_gemini"].items():
        lines.append(f"| {arm} | {c['pairs']} ({c['worlds']}) | {c['mean_difference']}{_ci(c['ci95'])} |" if c else f"| {arm} | 0 | — |")
    if "default_minus_low" in a:
        lines += ["", "Default reasoning minus low effort, same worlds:", "", "| client | pairs | difference |", "|---|---|---|"]
        for m, c in a["default_minus_low"].items():
            lines.append(f"| {m} | {c['pairs']} | {c['mean_difference']}{_ci(c['ci95'])} |" if c else f"| {m} | 0 | — |")
    lines += ["", f"Claim: {d['claim']}.", "", f"The reference graded zero regret on every cell: {a['reference_is_zero_everywhere']}.", "",
              "## Accounting", "",
              f"{s['completed_cells']} of {s['planned_cells']} planned cells executed, {s['operational_failure_cells']} sealed as typed exclusions, "
              f"{s['not_attempted_cells']} not attempted; {s['included_cells']} valid episodes. Replay verified: {s['replay_verified']}. "
              f"Cost ${s['total_cost_usd']:.2f} ({s['cost_qualifier']}): {s['cost_note']}.", "", f"Plan `{s['plan_sha256'][:12]}`.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("bundle", type=Path)
    args = ap.parse_args(argv)
    print(json.dumps(publish(args.run_dir, args.bundle), indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
