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
import random
import statistics
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.publication import assert_public_payload, atomic_publish, jsonl, receipt_projection, seal_publication_manifest
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
            "first_move_regret": (g.get("decisions") or [{}])[0].get("regret"),
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
        "analysis": analysis(rows, list(plan["arms"])),
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
    for path in sorted(bundle.rglob("*")):  # the prohibited-public-text scan, before anything is sealed
        if path.is_file():
            assert_public_payload(str(path.relative_to(bundle)), path.read_bytes())
    manifest = seal_publication_manifest(
        bundle, publication_id=plan["campaign_id"], campaign_id=plan["campaign_id"],
        privacy_boundary={"included": "receipt projections, per-cell grades and diagnostics, the sanitized trajectory grain, the campaign summary",
                          "excluded": "provider request and response text, raw event logs and artifacts, which stay in the local run directory"},
        source_bindings={"campaign_plan_sha256": plan["plan_sha256"], "pack_manifest_sha256": plan["pack_manifest_sha256"],
                         "sources": plan["sources"]},
        claim_status=plan["claim_status"],
    )
    rows_published, manifest = publish_trajectory_grain(bundle, attempts)
    grain = bundle / "trajectories" / "sanitized.jsonl"
    assert_public_payload(str(grain.relative_to(bundle)), grain.read_bytes())
    return {"bundle": str(bundle), "cells": len(rows), "receipts": len(projections), "trajectory_rows": rows_published,
            "manifest_sha256": manifest["manifest_sha256"]}


BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260925
BASE_ARM = "one_price_low"


def _cluster(row: dict[str, Any]) -> str:
    """A world and its twin share every public fact, so they are one cluster."""
    return row.get("twin_of") or row.get("world") or row["case_id"]


def _quantiles(values: list[float]) -> dict[str, float]:
    v = sorted(values)
    q = lambda f: v[min(len(v) - 1, int(f * (len(v) - 1) + 0.5))]  # noqa: E731
    return {"min": v[0], "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "max": v[-1]}


def _cluster_bootstrap(by_cluster: dict[str, list[float]], rng: random.Random) -> list[float] | None:
    keys = sorted(by_cluster)
    if len(keys) < 2:
        return None
    means = []
    for _ in range(BOOTSTRAP_DRAWS):
        pick = [by_cluster[keys[rng.randrange(len(keys))]] for _ in keys]
        flat = [x for group in pick for x in group]
        means.append(statistics.fmean(flat))
    means.sort()
    return [round(means[int(0.025 * BOOTSTRAP_DRAWS)], 3), round(means[int(0.975 * BOOTSTRAP_DRAWS) - 1], 3)]


def analysis(rows: list[dict[str, Any]], arms: list[str]) -> dict[str, Any]:
    """The analysis CLAUDE.md asks for: distributions, run-to-run variance, clustered and paired
    intervals, judge agreement, and what else the numbers suggest (labelled exploratory)."""
    rng = random.Random(BOOTSTRAP_SEED)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(f"{row['arm']}/{row['route_id']}/{row['seat']}", []).append(row)
    out: dict[str, Any] = {
        "run_to_run_variance": "unmeasured: one run per cell. The break-off draws are fixed per world, so a later "
                               "replicate campaign would measure the model's own spread.",
        "judges": "none: decision regret is an exact computation, and every receipt was replayed to the same digest",
        "intervals": f"95% percentile bootstrap, {BOOTSTRAP_DRAWS} draws, worlds resampled as clusters (a twin with its base world)",
        "groups": {}, "paired_vs_" + BASE_ARM: {},
    }
    for key, rs in sorted(groups.items()):
        valid = [r for r in rs if r.get("valid")]
        outcomes: dict[str, int] = {}
        for r in rs:
            label = r.get("termination") or r.get("receipt_status") or "unsealed"
            if not r.get("valid"):
                label = f"missing: {r.get('invalid') or r.get('receipt_status') or 'unsealed'}"
            outcomes[label] = outcomes.get(label, 0) + 1
        by_cluster: dict[str, list[float]] = {}
        for r in valid:
            by_cluster.setdefault(_cluster(r), []).append(r["decision_regret"])
        signed = [r for r in valid if r["signed_package"]]
        out["groups"][key] = {
            "cells": len(rs), "valid": len(valid), "outcomes": dict(sorted(outcomes.items())),
            "decision_regret": ({**_quantiles([r["decision_regret"] for r in valid]), "mean": round(statistics.fmean(r["decision_regret"] for r in valid), 3),
                                 "mean_ci95": _cluster_bootstrap(by_cluster, rng)} if valid else None),
            "strict_pass_zero_regret": sum(r["decision_regret"] < 1.0 for r in valid),
            "exploratory": {
                "signed": len(signed), "switched_package": sum(bool(r["switched_package"]) for r in signed),
                "efficient_contract": sum(r["signed_package"] == r["efficient_package"] for r in signed),
                "mean_first_move_regret": round(statistics.fmean(r["first_move_regret"] or 0.0 for r in valid), 3) if valid else None,
                "mean_allocation_gap": round(statistics.fmean(r["allocation_gap"] for r in valid), 3) if valid else None,
            },
        }
    for arm in arms:
        if arm == BASE_ARM:
            continue
        for key in sorted(groups):
            a, route, seat = key.split("/")
            if a != arm:
                continue
            base = {r["world"]: r for r in groups.get(f"{BASE_ARM}/{route}/{seat}", []) if r.get("valid")}
            diffs: dict[str, list[float]] = {}
            for r in groups[key]:
                if r.get("valid") and r["world"] in base:
                    diffs.setdefault(_cluster(r), []).append(r["decision_regret"] - base[r["world"]]["decision_regret"])
            flat = [x for d in diffs.values() for x in d]
            if flat:
                out["paired_vs_" + BASE_ARM][key] = {"worlds": len(flat), "mean_difference": round(statistics.fmean(flat), 3),
                                                     "ci95": _cluster_bootstrap(diffs, rng)}
    return out


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
    a = summary["analysis"]
    lines += ["", "Analysis (`reports/summary.json`, key `analysis`):", "",
              f"- Run-to-run variance: {a['run_to_run_variance']}", f"- Judges: {a['judges']}", f"- Intervals: {a['intervals']}.", "",
              "| arm / route / seat | valid | mean regret [95% CI] | median | strict pass (zero regret) |", "|---|---|---|---|---|"]
    for key, g in a["groups"].items():
        d = g["decision_regret"]
        lines.append(f"| {key} | {g['valid']}/{g['cells']} | " + (f"{d['mean']} [{d['mean_ci95'][0]}, {d['mean_ci95'][1]}]" if d and d["mean_ci95"] else "—")
                     + f" | {d['median'] if d else '—'} | {g['strict_pass_zero_regret']} |")
    lines += ["", f"Paired against `{BASE_ARM}` on the same worlds (difference in decision regret, $ thousands; negative is better):", "",
              "| arm / route / seat | worlds | mean difference [95% CI] |", "|---|---|---|"]
    for key, d in a["paired_vs_" + BASE_ARM].items():
        ci = d["ci95"]
        lines.append(f"| {key} | {d['worlds']} | {d['mean_difference']}" + (f" [{ci[0]}, {ci[1]}]" if ci else "") + " |")
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
