"""Publish the Housing v15 confirmatory: per-cell seat-0 numbers, receipt projections and the declared analysis.

    python -m aeread_families.housing.price_v15_publication runs/housing_v15 evidence/housing/housing_lemons_price_v15_confirmatory

The plan (``docs/families/housing/price_confirmatory_v15_plan.md``, Section 6) publishes seat 0's numbers for every
cell and each receipt's projection, so the primary is recomputed from ``evidence/`` alone and ``aeread verify-replay``
can bind every published receipt to its run root (the replay factory is ``price_publication.replay_setup``). v14's
publisher hard-codes the v14 panel and measure, so v15 has its own; nothing hashed is edited. The bundle holds the
three identities that ran (GLM left at admission, amendment 5): Luna and Gemini on the main pack and the holdout, and
Luna's A/A twin on the main pack. Provider text stays in the run roots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.publication import (
    assert_public_payload, atomic_publish, jsonl, receipt_projection, seal_publication_manifest,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import price_campaign

PUBLICATION_ID = "housing_lemons_price_v15_confirmatory"
IDENTITIES = ("housing_lemons_price_v15_gpt6_luna", "housing_lemons_price_v15_gemini38_flash",
              "housing_lemons_price_v15_gpt6_luna_aa")
LEAF = "housing_seat0_net_v2_leaf"
ROOT = Path(__file__).resolve().parents[3]
ANALYSIS = ROOT / "evidence/housing/housing_lemons_price_v15_analysis/reports/analysis.json"


def _receipt(live: Path, name: str) -> dict[str, Any]:
    return json.loads(next((live / name.replace(".json", "_evidence")).rglob("evaluation_receipt.json")).read_text())


def rows_and_projections(contract: dict[str, Any], run_root: Path) -> tuple[list[dict], list[dict]]:
    live = run_root / contract["campaign_id"] / "live"
    rows, projections = [], []
    for path in sorted(live.glob("*world_*.json")):
        row = json.loads(path.read_text())
        public: dict[str, Any] = {
            "campaign_id": contract["campaign_id"], "stream": row.get("stream", "main"), "world_seed": row["world_seed"],
            "arm": row["arm"], "status": row["status"], "failure_condition": row.get("failure_condition"),
            "cost_usd": round(float(row.get("cost_usd") or 0.0), 6), "receipt_sha256": row.get("receipt_sha256"),
            "run_plan_id": row.get("run_plan_id"), "cell_id": row.get("cell_id"),
        }
        if row["status"] == "completed":
            receipt = _receipt(live, path.name)
            if receipt["receipt_sha256"] != row["receipt_sha256"]:
                raise SystemExit(f"{path}: the cell record names another receipt")
            (score,) = [s for s in receipt["scores"] if s["leaf"]["leaf_id"] == LEAF]
            public["seat0_primary_v2"] = score["primary"]["value"]
            public["metrics"] = {k: v["value"] for k, v in score["metrics"].items()}
            public["references"] = {k: v["value"] for k, v in score["reference_values"].items()}
            projections.append(receipt_projection(receipt, campaign_cell_key=f"{contract['campaign_id']}:{path.stem}"))
        rows.append(public)
    return rows, projections


#: Development evidence of plan Sections 7 and 8: the profile admissions (GLM's two refused cells included) and the
#: variance pilot. Never analysed with the confirmatory.
DEVELOPMENT_ID = "housing_lemons_price_v15_admission_and_pilot"
DEVELOPMENT = tuple(f"housing_lemons_price_v15_{kind}_{m}" for kind in ("admission", "pilot")
                    for m in ("glm53_flash_nextbit", "gpt6_luna", "gemini38_flash")
                    if not (kind == "pilot" and m == "glm53_flash_nextbit"))


def publish(run_root: Path, bundle: Path, *, development: bool = False) -> dict[str, Any]:
    if bundle.exists() and any(bundle.iterdir()):
        raise SystemExit(f"{bundle} is not empty; a published bundle is never edited")
    identities = DEVELOPMENT if development else IDENTITIES
    publication_id = DEVELOPMENT_ID if development else PUBLICATION_ID
    contracts = [price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT.with_name(f"{i}.json")) for i in identities]
    rows, projections = [], []
    for contract in contracts:
        r, p = rows_and_projections(contract, run_root)
        rows += r
        projections += p
    files = {
        "tables/cells.jsonl": jsonl(rows),
        "receipts/projections.jsonl": jsonl(projections),
        "reports/contracts.json": canonical_json_bytes({c["campaign_id"]: c for c in contracts}) + b"\n",
    }
    if development:
        files["README.md"] = _development_readme(rows).encode("utf-8")
    else:
        analysis = json.loads(ANALYSIS.read_text())
        files["reports/analysis.json"] = canonical_json_bytes(analysis) + b"\n"
        files["README.md"] = _readme(analysis, rows).encode("utf-8")
    bundle.mkdir(parents=True, exist_ok=True)
    for relative, payload in files.items():
        assert_public_payload(relative, payload)
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_publish(path, payload)
    return seal_publication_manifest(
        bundle, publication_id=publication_id, campaign_id=publication_id,
        privacy_boundary={"included": "contracts, per-cell seat-0 numbers and typed failures, receipt projections, "
                                      "receipt digests, the declared analysis",
                          "excluded": "raw provider responses, model reasoning, complete receipts and events, failure "
                                      "messages (they stay in the run roots)"},
        source_bindings={"contract_sha256s": {c["campaign_id"]: hashlib.sha256(canonical_json_bytes(c)).hexdigest()
                                              for c in contracts},
                         **({} if development else {"analysis_sha256": hashlib.sha256(ANALYSIS.read_bytes()).hexdigest()}),
                         "source_receipt_sha256s": sorted(r["receipt_sha256"] for r in rows if r.get("receipt_sha256")),
                         "run_root_layout": "runs/housing_v15/<campaign_id>/live/[holdout_]world_<seed>__<arm>[_evidence]",
                         "replay_setup": "aeread_families.housing.price_publication:replay_setup"},
        claim_status="development" if development else "confirmatory", winner_claim_allowed=False,
        inferential_model_ranking_allowed=not development,
        cost_qualifier="lower_bound", total_cost_usd=round(sum(r["cost_usd"] for r in rows), 6),
        cost_basis="every cell of the three identities; a timed-out call's cost is unknown to the kernel",
    )


def _readme(a: dict[str, Any], rows: list[dict]) -> str:
    def iv(r):
        return f"{r['mean']:+.1f} [{r['ci_0.95'][0]:.1f}, {r['ci_0.95'][1]:.1f}]"
    lines = [f"# {PUBLICATION_ID}", "",
             "Housing lemons price with outside demand, v15 confirmatory (plan `docs/families/housing/price_confirmatory_v15_plan.md`,",
             "amendments 1 to 5). Seat 0 against scripted outside demand and both landlord kinds; measure v2, mean of the two",
             f"landlord arms per world; main pack 260 worlds, holdout 40 at outside-demand rate 0.3. {len(rows)} cells, "
             f"{sum(r['status'] == 'completed' for r in rows)} completed.", "",
             "| Contrast (main pack) | $ per world [95%] |", "|---|---|",
             f"| P: Gemini 3.8 Flash − GPT-6 Luna | {iv(a['P'])} |", f"| A/A: Luna − its twin | {iv(a['AA'])} |"]
    lines += [f"| {r['contrast']} | {iv(r)} |" for r in a["B"] + a["G"] + a["R"]]
    lines += ["", "`tables/cells.jsonl`: one row per cell with seat 0's primary, metrics and references from its receipt;",
              "`receipts/projections.jsonl`: each receipt's projection; `reports/analysis.json`: the declared analysis",
              "(`tools/housing/price_v15_analysis.py`). Replay: `aeread verify-replay <bundle> --run-root runs/housing_v15/<id>",
              "--setup aeread_families.housing.price_publication:replay_setup`.", ""]
    return "\n".join(lines)


def _development_readme(rows: list[dict]) -> str:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["campaign_id"], []).append(r)
    lines = [f"# {DEVELOPMENT_ID}", "", "Development evidence of the v15 plan's Sections 7 and 8: the profile admissions and the "
             "variance pilot. Never analysed with the confirmatory.", "", "| Identity | Cells | Completed | Cost $ |",
             "|---|---:|---:|---:|"]
    for cid, rs in sorted(by.items()):
        lines.append(f"| {cid} | {len(rs)} | {sum(r['status'] == 'completed' for r in rs)} | "
                     f"{sum(r['cost_usd'] for r in rs):.4f} |")
    lines += ["", "GLM 5.3 Flash's two admission cells were refused at OpenRouter's quantization filter (HL-O-22); GLM left",
              "v15 by Section 7's rule (amendment 5). The sizing record is `docs/families/housing/price_v15_sizing_record.json`.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_root", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--development", action="store_true", help="the admissions and the pilot")
    args = parser.parse_args(argv)
    manifest = publish(args.run_root, args.bundle, development=args.development)
    print(json.dumps({k: manifest.get(k) for k in ("publication_id", "manifest_sha256", "total_cost_usd")}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
