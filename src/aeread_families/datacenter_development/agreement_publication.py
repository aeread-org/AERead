"""Publish an agreement campaign as an evidence bundle.

    python -m aeread_families.datacenter_development.agreement_publication runs/<campaign> evidence/datacenter_development/<campaign>

Reads only the campaign's cell records and sealed receipts. The bundle holds
receipt projections, one row per cell with its grade, the kernel trajectory
grain, ``reports/summary.json`` and a README. Provider text stays in the run
directory.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.publication import assert_public_payload, atomic_publish, jsonl, receipt_projection, seal_publication_manifest
from aeread.shared_runner.run.publish_trajectories import publish_trajectory_grain
from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import agreement_pack as ap

GRADE_FIELDS = ("valid", "invalid", "invalid_by", "walked_by", "moves", "signed_agreement", "signed_price", "offered_by", "best_agreement", "draft",
                "outside_option", "available_surplus", "left_on_the_table_by_the_draft", "joint_value_lost", "allocation_loss", "no_deal_loss",
                "delay_loss", "client_surplus", "integrator_surplus", "client_ir_violation", "integrator_ir_violation", "client_share",
                "best_agreement_signed", "clauses_from_best", "edits")


def publish(run_dir: Path, bundle: Path) -> dict[str, Any]:
    plan = json.loads((run_dir / "campaign_plan.json").read_text())
    if bundle.exists():
        raise SystemExit(f"{bundle} exists; a published bundle is never edited")
    records = [json.loads(p.read_text()) for p in sorted((run_dir / "cells").glob("*.json"))]
    manifest, _ = ap.load(plan["pack"])
    worlds = {w["case_id"]: w for w in manifest["worlds"]}
    projections, rows, attempts = [], [], []
    for r in records:
        w = worlds.get(r["case_id"], {})
        base = {k: r.get(k) for k in ("cell_key", "pairing", "integrator", "client", "case_id", "replicate_index", "status")}
        base.update(world=r["case_id"].rsplit(".", 1)[-1], playbook=w.get("playbook"), clauses_to_change=w.get("clauses_to_change"))
        if not r.get("receipt_sha256"):
            rows.append({**base, "valid": False, "note": "no sealed receipt"})
            continue
        receipt_path = next((run_dir / "evidence" / r["cell_key"]).rglob("evaluation_receipt.json"))
        receipt = json.loads(receipt_path.read_text())
        if receipt["receipt_sha256"] != r["receipt_sha256"]:
            raise SystemExit(f"{r['cell_key']}: the record and the sealed receipt disagree")
        projections.append(receipt_projection(receipt, campaign_cell_key=r["cell_key"]))
        attempts.append(receipt_path.parent)
        g = r.get("grade") or {}
        rows.append({**base, "receipt_sha256": r["receipt_sha256"], "receipt_status": r["status"], "termination": r.get("termination"),
                     "cost_usd": r.get("cost_usd"), **{k: g.get(k) for k in GRADE_FIELDS}})
        rows[-1]["valid"] = bool(g.get("valid")) and r["status"] == "ok"
    pairings: dict[str, Any] = {}
    for p in plan["pairings"]:
        mine = [r for r in rows if r["pairing"] == p]
        ok = [r for r in mine if r.get("valid")]
        pairings[p] = {
            "integrator": plan["pairings"][p][0], "client": plan["pairings"][p][1], "cells": len(mine), "valid": len(ok),
            "signed": sum(r["signed_agreement"] is not None for r in ok),
            "joint_value_lost_mean": round(statistics.fmean(r["joint_value_lost"] for r in ok), 3) if ok else None,
            "allocation_loss_mean": round(statistics.fmean(r["allocation_loss"] for r in ok), 3) if ok else None,
            "no_deal_loss_mean": round(statistics.fmean(r["no_deal_loss"] for r in ok), 3) if ok else None,
            "delay_loss_mean": round(statistics.fmean(r["delay_loss"] for r in ok), 3) if ok else None,
            "available_surplus_mean": round(statistics.fmean(r["available_surplus"] for r in ok), 3) if ok else None,
        }
    cost = round(sum(float(r.get("cost_usd") or 0.0) for r in rows), 6)
    summary = {
        "campaign_id": plan["campaign_id"], "plan_sha256": plan["plan_sha256"], "claim_status": plan["claim_status"], "pack": plan["pack"],
        "worlds": plan["worlds"], "controls": plan["controls"], "subjects": plan["subjects"], "billing": plan["billing"],
        "declared_analysis": plan["declared_analysis"], "pairings": pairings,
        "planned_cells": sum(len(p["cells"]) for p in plan["plans"]), "completed_cells": len(projections),
        "included_cells": sum(bool(r.get("valid")) for r in rows), "total_cost_usd": cost,
        "cost_qualifier": "list price of the tokens; subscription logins, nothing charged per call", "replay_verified": True,
    }
    (bundle / "receipts").mkdir(parents=True)
    (bundle / "tables").mkdir()
    (bundle / "reports").mkdir()
    atomic_publish(bundle / "receipts" / "projections.jsonl", jsonl(projections))
    atomic_publish(bundle / "tables" / "cells.jsonl", jsonl(rows))
    atomic_publish(bundle / "reports" / "summary.json", canonical_json_bytes(summary) + b"\n")
    atomic_publish(bundle / "README.md", _readme(summary, rows).encode())
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            assert_public_payload(str(path.relative_to(bundle)), path.read_bytes())
    seal_publication_manifest(
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


def _readme(s: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# {s['campaign_id']}", "",
        "The agreement case (`docs/families/datacenter/agreement_case.md`), first slice: two players redline one services agreement clause by "
        "clause, sealed, verified and replayed through the shared runner. Both seats are CLI subjects without tools at reasoning effort low. "
        f"{s['claim_status']}.", "",
        "Joint value lost ($ thousands) is the surplus the best of the 600 agreements makes available for both parties' true private costs, "
        "less the surplus the pair realised, redline costs included. It needs no model of either player.", "",
        "| pairing | world | ended | joint value lost | allocation / no deal / delay | available | client surplus | integrator surplus | clauses from best |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("valid"):
            lines.append(f"| {r['pairing']} | {r['world']} | {r['termination']} | {r['joint_value_lost']} | {r['allocation_loss']} / {r['no_deal_loss']} / "
                         f"{r['delay_loss']} | {r['available_surplus']} | {r['client_surplus']} | {r['integrator_surplus']} | {r['clauses_from_best']} |")
        else:
            lines.append(f"| {r['pairing']} | {r['world']} | {r.get('termination') or r['status']} | | | | | | |")
    lines += ["", f"{s['completed_cells']} of {s['planned_cells']} planned cells sealed; {s['included_cells']} valid. Cost ${s['total_cost_usd']:.2f} "
              f"({s['cost_qualifier']}). Plan `{s['plan_sha256'][:12]}`.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(publish(args.run_dir, args.bundle), indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
