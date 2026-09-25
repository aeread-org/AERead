"""Publish a risk-allocation campaign as an evidence bundle.

    python -m aeread_families.datacenter_development.risk_allocation_publication runs/<campaign> evidence/datacenter_development/<campaign>

Reads only the campaign's cell records and its sealed receipts. The bundle holds:

- ``receipts/projections.jsonl``: every receipt, projected onto the publishable fields;
- ``tables/cells.jsonl``: one row per cell with the grade's diagnostics and the world's cell name;
- ``reports/summary.json``: per arm, route and seat, valid cells, mean decision regret, how often the
  model signed a package other than its first and the efficient one, with the rules' regret on the
  same worlds from the pack manifest;
- ``README.md``; the kernel manifest; and the kernel trajectory grain.

Provider text and raw event logs stay in the run directory.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.publication import atomic_publish, jsonl, receipt_projection, seal_publication_manifest
from aeread.shared_runner.run.publish_trajectories import publish_trajectory_grain
from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import risk_allocation_pack as rp


def _records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((run_dir / "cells").glob("*.json"))]


def _world_index(packs: set[str]) -> dict[str, dict[str, Any]]:
    out = {}
    for pack in packs:
        manifest, _ = rp.load(pack)
        for w in manifest["worlds"]:
            for seat, s in w["seats"].items():
                out[s["case_id"]] = {"pack": pack, "slug": w["slug"], "cell": w["cell"], "twin_of": w.get("twin_of"),
                                     "rule_regret_prior": s["rule_regret_prior"]}
    return out


def publish(run_dir: Path, bundle: Path) -> dict[str, Any]:
    plan = json.loads((run_dir / "campaign_plan.json").read_text())
    records = _records(run_dir)
    if bundle.exists():
        raise SystemExit(f"{bundle} exists; a published bundle is never edited")
    worlds = _world_index({a["pack"] for a in plan["arms"].values()})
    projections, rows, attempts = [], [], []
    for r in records:
        if not r.get("receipt_sha256"):
            rows.append({**{k: r.get(k) for k in ("cell_key", "arm", "route_id", "seat", "case_id", "status")}, "note": "no sealed receipt"})
            continue
        receipt_paths = list((run_dir / "evidence" / r["cell_key"]).rglob("evaluation_receipt.json"))
        receipt = json.loads(receipt_paths[0].read_text())
        if receipt["receipt_sha256"] != r["receipt_sha256"]:
            raise SystemExit(f"{r['cell_key']}: the record and the sealed receipt disagree")
        projections.append(receipt_projection(receipt, campaign_cell_key=r["cell_key"]))
        attempts.append(receipt_paths[0].parent)
        g = r.get("grade") or {}
        w = worlds.get(r["case_id"], {})
        rows.append({
            "cell_key": r["cell_key"], "arm": r["arm"], "route_id": r["route_id"], "seat": r["seat"], "case_id": r["case_id"],
            "world": w.get("slug"), "world_cell": w.get("cell"), "twin_of": w.get("twin_of"),
            "receipt_sha256": r["receipt_sha256"], "receipt_status": r["status"], "termination": r.get("termination"),
            "valid": g.get("valid"), "invalid": g.get("invalid"), "decision_regret": g.get("decision_regret"),
            "allocation_gap": g.get("allocation_gap"), "price_gap": g.get("price_gap"), "signed_package": g.get("signed_package"),
            "efficient_package": g.get("efficient_package"), "first_proposed_package": g.get("first_proposed_package"),
            "switched_package": g.get("switched_package"), "refused_rounds": g.get("refused_rounds"), "cost_usd": r.get("cost_usd"),
        })
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['arm']}/{row['route_id']}/{row['seat']}"
        s = groups.setdefault(key, {"cells": 0, "valid": 0, "missing": {}, "regret": [], "signed": 0, "switched": 0, "efficient": 0,
                                    "zero_regret": 0, "cost_usd": 0.0, "rule_regret_same_worlds": {}})
        s["cells"] += 1
        s["cost_usd"] += float(row.get("cost_usd") or 0.0)
        if not row.get("valid"):
            reason = row.get("invalid") or row.get("receipt_status") or row.get("note") or "unknown"
            s["missing"][reason] = s["missing"].get(reason, 0) + 1
            continue
        s["valid"] += 1
        s["regret"].append(row["decision_regret"])
        s["zero_regret"] += int(row["decision_regret"] < 1.0)
        if row["signed_package"]:
            s["signed"] += 1
            s["switched"] += int(bool(row["switched_package"]))
            s["efficient"] += int(row["signed_package"] == row["efficient_package"])
        for name, v in worlds.get(row["case_id"], {}).get("rule_regret_prior", {}).items():
            s["rule_regret_same_worlds"].setdefault(name, []).append(v)
    for s in groups.values():
        s["mean_decision_regret"] = round(statistics.fmean(s["regret"]), 3) if s["regret"] else None
        s["rule_regret_same_worlds"] = {k: round(statistics.fmean(v), 3) for k, v in s["rule_regret_same_worlds"].items()}
        s["regret"] = len(s["regret"])
        s["cost_usd"] = round(s["cost_usd"], 4)
    summary = {
        "campaign_id": plan["campaign_id"], "plan_sha256": plan["plan_sha256"], "claim_status": plan["claim_status"],
        "arms": plan["arms"], "routes": sorted(plan["routes"]), "groups": dict(sorted(groups.items())),
        "cost_usd_total": round(sum(g["cost_usd"] for g in groups.values()), 4),
    }
    (bundle / "receipts").mkdir(parents=True)
    (bundle / "tables").mkdir()
    (bundle / "reports").mkdir()
    atomic_publish(bundle / "receipts" / "projections.jsonl", jsonl(projections))
    atomic_publish(bundle / "tables" / "cells.jsonl", jsonl(rows))
    atomic_publish(bundle / "reports" / "summary.json", canonical_json_bytes(summary) + b"\n")
    atomic_publish(bundle / "README.md", _readme(summary).encode())
    manifest = seal_publication_manifest(
        bundle, publication_id=plan["campaign_id"], campaign_id=plan["campaign_id"],
        privacy_boundary={"included": "receipt projections, per-cell grades and diagnostics, the sanitized trajectory grain, the campaign summary",
                          "excluded": "provider request and response text, raw event logs and artifacts, which stay in the local run directory"},
        source_bindings={"campaign_plan_sha256": plan["plan_sha256"], "pack_manifest_sha256": plan["pack_manifest_sha256"],
                         "sources": plan["sources"]},
        claim_status=plan["claim_status"],
    )
    rows_published, manifest = publish_trajectory_grain(bundle, attempts)
    return {"bundle": str(bundle), "cells": len(rows), "receipts": len(projections), "trajectory_rows": rows_published,
            "manifest_sha256": manifest["manifest_sha256"]}


def _readme(summary: dict[str, Any]) -> str:
    lines = [
        f"# {summary['campaign_id']}",
        "",
        "The integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`) run through the",
        "shared runner: every episode sealed, verified and replayed. A diagnostic dev campaign on a 16-world pack, one run per",
        "cell, both seats of every world. It does not rank models.",
        "",
        "Decision regret ($ thousands) is what each move gave up against the best play on the model's own information,",
        "summed over the episode. Invalid episodes (malformed or illegal moves, replies cut off by the output limit) are",
        "reported as missing, not scored.",
        "",
        "| arm / route / seat | valid | mean regret | signed another package than its first | signed the efficient one | cost |",
        "|---|---|---|---|---|---|",
    ]
    for key, g in summary["groups"].items():
        lines.append(f"| {key} | {g['valid']}/{g['cells']} | {g['mean_decision_regret']} | {g['switched']} of {g['signed']} | "
                     f"{g['efficient']} of {g['signed']} | ${g['cost_usd']:.2f} |")
    lines += ["", f"Total cost ${summary['cost_usd_total']:.2f}. Plan `{summary['plan_sha256'][:12]}`.", ""]
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
