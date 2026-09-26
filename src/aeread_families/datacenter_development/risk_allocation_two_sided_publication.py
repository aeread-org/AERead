"""Publish a two-sided risk-allocation campaign as an evidence bundle.

    python -m aeread_families.datacenter_development.risk_allocation_two_sided_publication runs/<campaign> evidence/datacenter_development/<campaign>

Reads only the campaign's cell records, sealed receipts and event logs (for the
cost and each exclusion's cause). The bundle holds receipt projections, one row
per cell, the kernel trajectory grain, ``reports/summary.json`` with the analysis
the frozen plan declared, and a README. Provider text stays in the run directory.
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

from . import risk_allocation_publication as op  # the one-sided publisher: bootstrap, quantiles, exclusion causes
from . import risk_allocation_two_sided_pack as tp

BOOTSTRAP_SEED = 20260926
MODELS = ("gemini38_flash", "glm53_flash")
SHORT = {"gemini38_flash": "gemini", "glm53_flash": "glm"}


def pairing_of(client: str, integrator: str) -> str:
    return f"{SHORT[client]}_client_{SHORT[integrator]}_integrator"


# (swapped seat, held seat, held model): the second pairing minus the first, GLM minus Gemini in the swapped seat
CONTRASTS = [
    ("client", "integrator", "gemini38_flash"),
    ("client", "integrator", "glm53_flash"),
    ("integrator", "client", "gemini38_flash"),
    ("integrator", "client", "glm53_flash"),
]


def _contrast_pairings(swapped: str, held: str, model: str) -> tuple[str, str]:
    def p(swap_model: str) -> str:
        roles = {swapped: swap_model, held: model}
        return pairing_of(roles["client"], roles["integrator"])
    return p("gemini38_flash"), p("glm53_flash")


def _key(row: dict[str, Any]) -> tuple[str, int]:
    return (row["world"], int(row.get("replicate_index") or 0))


def _paired(first: list[dict[str, Any]], second: list[dict[str, Any]], field: str, rng: random.Random) -> dict[str, Any] | None:
    a = {_key(r): r for r in first if r.get("valid")}
    diffs: dict[str, list[float]] = {}
    for r in second:
        if r.get("valid") and _key(r) in a:
            diffs.setdefault(op._cluster(r), []).append(r[field] - a[_key(r)][field])
    flat = [x for d in diffs.values() for x in d]
    if not flat:
        return None
    return {"pairs": len(flat), "worlds": len(diffs), "mean_difference": round(statistics.fmean(flat), 3), "ci95": op._cluster_bootstrap(diffs, rng),
            "second_lower": sum(x < -1.0 for x in flat), "second_higher": sum(x > 1.0 for x in flat), "within_one": sum(abs(x) <= 1.0 for x in flat)}


def _run_to_run(rs: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_world: dict[str, dict[int, dict[str, Any]]] = {}
    for r in rs:
        if r.get("valid"):
            by_world.setdefault(r["world"], {})[int(r.get("replicate_index") or 0)] = r
    both = [(w[0], w[1]) for w in by_world.values() if 0 in w and 1 in w]
    if not both:
        return None
    gaps = [b["joint_value_lost"] - a["joint_value_lost"] for a, b in both]
    means = [(a["joint_value_lost"] + b["joint_value_lost"]) / 2 for a, b in both]
    within = math.sqrt(statistics.fmean(g * g for g in gaps) / 2)
    between = statistics.pstdev(means) if len(means) > 1 else 0.0
    return {"worlds_with_both": len(both), "mean_abs_gap": round(statistics.fmean(abs(g) for g in gaps), 3), "within_world_sd": round(within, 3),
            "within_share_of_variance": round(within ** 2 / (within ** 2 + between ** 2), 3) if within or between else None,
            "same_outcome_both_replicates": sum(a["signed_package"] == b["signed_package"] for a, b in both)}


def analysis(rows: list[dict[str, Any]], declared: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED)
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["pairing"], []).append(r)
    out: dict[str, Any] = {
        "declared": dict(declared),
        "intervals": f"95% percentile bootstrap, {op.BOOTSTRAP_DRAWS} draws, seed {BOOTSTRAP_SEED}, worlds resampled as clusters (a twin with its base world)",
        "judges": "none: joint value lost is an exact computation at both true private costs, and every receipt was replayed to the same digest",
        "run_to_run_variance": "per model pairing (`run_to_run`): two replicates per world under different request seeds",
        "pairings": {},
    }
    for pairing, rs in sorted(groups.items()):
        valid = [r for r in rs if r.get("valid")]
        missing: dict[str, int] = {}
        for r in rs:
            if not r.get("valid"):
                cause = r.get("invalid") or r.get("failure_cause") or r.get("receipt_status") or "unsealed"
                who = r.get("invalid_by") or "provider"
                missing[f"{cause} ({who})"] = missing.get(f"{cause} ({who})", 0) + 1
        by_cluster: dict[str, list[float]] = {}
        for r in valid:
            by_cluster.setdefault(op._cluster(r), []).append(r["joint_value_lost"])
        signed = [r for r in valid if r["signed_package"] is not None]
        mean = lambda f, xs=valid: round(statistics.fmean(r[f] for r in xs), 3) if xs else None  # noqa: E731
        shares = [r["client_share"] for r in signed if r["client_share"] is not None]
        g = {
            "cells": len(rs), "valid": len(valid), "missing": missing,
            "joint_value_lost": ({**op._quantiles([r["joint_value_lost"] for r in valid]), "mean": mean("joint_value_lost"),
                                  "mean_ci95": op._cluster_bootstrap(by_cluster, rng)} if valid else None),
            "allocation_loss": mean("allocation_loss"), "no_deal_loss": mean("no_deal_loss"), "delay_loss": mean("delay_loss"),
            "client_surplus": mean("client_surplus"), "integrator_surplus": mean("integrator_surplus"),
            "signed": len(signed), "efficient_contract": sum(bool(r["efficient_contract_signed"]) for r in valid),
            "deals_where_gains_existed": sum(r["signed_package"] is not None for r in valid if r["available_surplus"] > 0),
            "worlds_with_gains": sum(r["available_surplus"] > 0 for r in valid),
            "client_ir_violations": sum(bool(r["client_ir_violation"]) for r in valid),
            "integrator_ir_violations": sum(bool(r["integrator_ir_violation"]) for r in valid),
            "median_client_share": round(statistics.median(shares), 3) if shares else None,
            "terminations": {t: sum(r["termination"] == t for r in valid) for t in ("signed", "walked", "broke_off")},
        }
        if not pairing.startswith(("rule_", "oracle_")):
            g["run_to_run"] = _run_to_run(rs)
        out["pairings"][pairing] = g
    contrasts = {}
    for swapped, held, model in CONTRASTS:
        first, second = _contrast_pairings(swapped, held, model)
        if first not in groups or second not in groups:
            continue
        name = f"{swapped} seat GLM minus Gemini, {held} {SHORT[model]}"
        contrasts[name] = {
            "pairings": [second, first],
            "joint_value_lost": _paired(groups[first], groups[second], "joint_value_lost", rng),
            f"{swapped}_surplus": _paired(groups[first], groups[second], f"{swapped}_surplus", rng),
        }
    out["seat_contrasts"] = contrasts
    oracle = out["pairings"].get("oracle_client_oracle_integrator")
    out["oracle_is_zero_everywhere"] = bool(oracle and oracle["valid"] == oracle["cells"] and (oracle["joint_value_lost"] or {}).get("max", 1) < 1e-6)
    return out


def publish(run_dir: Path, bundle: Path) -> dict[str, Any]:
    plan = json.loads((run_dir / "campaign_plan.json").read_text())
    if bundle.exists():
        raise SystemExit(f"{bundle} exists; a published bundle is never edited")
    records = [json.loads(p.read_text()) for p in sorted((run_dir / "cells").glob("*.json"))]
    manifest, _ = tp.load(plan["pack"])
    worlds = {w["case_id"]: w for w in manifest["worlds"]}
    projections, rows, attempts = [], [], []
    for r in records:
        base = {k: r.get(k) for k in ("cell_key", "pairing", "client_route", "integrator_route", "case_id", "replicate_index", "status")}
        w = worlds.get(r["case_id"], {})
        base.update(world=w.get("slug"), world_cell=w.get("cell"), twin_of=w.get("twin_of"))
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
                     **{k: g.get(k) for k in ("valid", "invalid", "invalid_by", "walked_by", "moves", "signed_package", "signed_price", "offered_by",
                                              "efficient_package", "available_surplus", "joint_value_lost", "allocation_loss", "no_deal_loss", "delay_loss",
                                              "client_surplus", "integrator_surplus", "client_ir_violation", "integrator_ir_violation", "client_share",
                                              "efficient_contract_signed", "packages_proposed", "changed_package")}})
        rows[-1]["valid"] = bool(g.get("valid")) and r["status"] == "ok"
    acc = op.accounting(plan, records, rows)
    acc["claim_scope"] = ("diagnostic: declared paired contrasts of two models in each seat of a two-sided negotiation on one generated pack, "
                          "reported with intervals; not a model ranking and not a population estimate")
    summary = {
        "campaign_id": plan["campaign_id"], "plan_sha256": plan["plan_sha256"], "claim_status": plan["claim_status"], "arm": plan["arm"],
        "pairings": plan["pairings"], "routes": sorted(plan["routes"]), "analysis": analysis(rows, plan["declared_analysis"]),
        "cost_usd_total": acc["total_cost_usd"], **acc,
    }
    (bundle / "receipts").mkdir(parents=True)
    (bundle / "tables").mkdir()
    (bundle / "reports").mkdir()
    atomic_publish(bundle / "receipts" / "projections.jsonl", jsonl(projections))
    atomic_publish(bundle / "tables" / "cells.jsonl", jsonl(rows))
    atomic_publish(bundle / "reports" / "summary.json", canonical_json_bytes(summary) + b"\n")
    atomic_publish(bundle / "README.md", _readme(summary).encode())
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            assert_public_payload(str(path.relative_to(bundle)), path.read_bytes())
    manifest_out = seal_publication_manifest(
        bundle, publication_id=plan["campaign_id"], campaign_id=plan["campaign_id"],
        privacy_boundary={"included": "receipt projections, per-cell outcomes and grades, the sanitized trajectory grain, the campaign summary",
                          "excluded": "provider request and response text, raw event logs and artifacts, which stay in the local run directory"},
        source_bindings={"campaign_plan_sha256": plan["plan_sha256"], "pack_manifest_sha256": plan["pack_manifest_sha256"], "sources": plan["sources"]},
        claim_status=plan["claim_status"],
    )
    rows_published, manifest_out = publish_trajectory_grain(bundle, attempts)
    grain = bundle / "trajectories" / "sanitized.jsonl"
    assert_public_payload(str(grain.relative_to(bundle)), grain.read_bytes())
    return {"bundle": str(bundle), "cells": len(rows), "receipts": len(projections), "trajectory_rows": rows_published,
            "manifest_sha256": manifest_out["manifest_sha256"]}


def _ci(ci: list[float] | None) -> str:
    return f" [{ci[0]}, {ci[1]}]" if ci else ""


def _readme(s: dict[str, Any]) -> str:
    a = s["analysis"]
    lines = [
        f"# {s['campaign_id']}", "",
        "The two-sided integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`, section two-sided): "
        "both seats played, on the 32 worlds of the one-sided eval pack, sealed, verified and replayed through the shared runner. "
        f"Arm `{s['arm']}`; two replicates per model pairing; two scripted pairings as controls in the same run. It does not rank models.", "",
        "Joint value lost ($ thousands) is the surplus the best outcome for both parties' true private costs makes available, less the surplus "
        "the pair realised, round costs included; zero is the best any pair could do. It needs no model of either player.", "",
        "| pairing (client / integrator) | valid | joint value lost [95% CI] | allocation / no deal / delay | signed (efficient) | IR violations client / integrator | median client share |",
        "|---|---|---|---|---|---|---|",
    ]
    for p, g in a["pairings"].items():
        j = g["joint_value_lost"] or {}
        lines.append(f"| {p} | {g['valid']}/{g['cells']} | {j.get('mean')}{_ci(j.get('mean_ci95'))} | {g['allocation_loss']} / {g['no_deal_loss']} / {g['delay_loss']} | "
                     f"{g['signed']} ({g['efficient_contract']}) | {g['client_ir_violations']} / {g['integrator_ir_violations']} | {g['median_client_share']} |")
    d = a["declared"]
    lines += ["", "## Declared seat contrasts", "", f"{d['contrasts']}. {d['interval']}. Negative joint value lost favours GLM in the swapped seat.", "",
              "| contrast | pairs (worlds) | joint value lost | swapped seat's own surplus |", "|---|---|---|---|"]
    for name, c in a["seat_contrasts"].items():
        j = c["joint_value_lost"] or {}
        own = next(v for k, v in c.items() if k.endswith("_surplus")) or {}
        lines.append(f"| {name} | {j.get('pairs', 0)} ({j.get('worlds', 0)}) | {j.get('mean_difference')}{_ci(j.get('ci95'))} | {own.get('mean_difference')}{_ci(own.get('ci95'))} |")
    lines += ["", f"Claim: {d['claim']}.", "", f"The oracle pair lost zero on every world: {a['oracle_is_zero_everywhere']}.", "",
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
