"""Publish the Housing v15 confirmatory: per-cell seat-0 numbers, receipt projections and the declared analysis.

    python -m aeread_families.housing.price_v15_publication runs/housing_v15 evidence/housing/housing_lemons_price_v15_confirmatory

The plan (``docs/families/housing/price_confirmatory_v15_plan.md``, Section 6) publishes seat 0's numbers for every
cell and each receipt's projection, so the primary is recomputed from ``evidence/`` alone and ``aeread verify-replay``
can bind every published receipt to its run root (the replay factory is ``price_publication.replay_setup``). v14's
publisher hard-codes the v14 panel and measure, so v15 has its own; nothing hashed is edited. The bundle holds the
three identities that ran (GLM left at admission, amendment 5): Luna and Gemini on the main pack and the holdout, and
Luna's A/A twin on the main pack. Provider text stays in the run roots.

Addendum A (GLM 5.3 Flash on Near AI fp8, declared after v15's analysis) is published apart, never inside v15's
bundle: ``--addendum`` seals its one identity with its declared rows, ``--addendum-admission`` its admissions (the
refused Novita cells included, as its amendment 1 says).
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


#: Addendum A (plan, "Addendum A" and its amendments 1 and 2): its identity, its declared rows
#: (``tools/housing/price_v15_addendum_analysis.py``, committed before its results) and its admissions.
ADDENDUM_ID = "housing_lemons_price_v15_glm_addendum"
ADDENDUM = ("housing_lemons_price_v15_glm53_flash_nearai",)
ADDENDUM_ANALYSIS = ROOT / "evidence/housing/housing_lemons_price_v15_glm_addendum_analysis/reports/analysis.json"
ADDENDUM_ADMISSION_ID = "housing_lemons_price_v15_glm_addendum_admission"
ADDENDUM_ADMISSION = ("housing_lemons_price_v15_admission_glm53_flash_novita",
                      "housing_lemons_price_v15_admission_glm53_flash_nearai")


def publish(run_root: Path, bundle: Path, *, development: bool = False, addendum: str | None = None) -> dict[str, Any]:
    """v15's confirmatory or its development bundle; with ``addendum`` (``"main"`` or ``"admission"``), addendum A's."""
    if addendum is not None:
        return _publish_addendum(run_root, bundle, admission=addendum == "admission")
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


def _publish_addendum(run_root: Path, bundle: Path, *, admission: bool) -> dict[str, Any]:
    if bundle.exists() and any(bundle.iterdir()):
        raise SystemExit(f"{bundle} is not empty; a published bundle is never edited")
    identities = ADDENDUM_ADMISSION if admission else ADDENDUM
    publication_id = ADDENDUM_ADMISSION_ID if admission else ADDENDUM_ID
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
    if admission:
        files["README.md"] = _addendum_admission_readme(rows).encode("utf-8")
    else:
        analysis = json.loads(ADDENDUM_ANALYSIS.read_text())
        files["reports/analysis.json"] = canonical_json_bytes(analysis) + b"\n"
        files["README.md"] = _addendum_readme(analysis, rows).encode("utf-8")
    bundle.mkdir(parents=True, exist_ok=True)
    for relative, payload in files.items():
        assert_public_payload(relative, payload)
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_publish(path, payload)
    return seal_publication_manifest(
        bundle, publication_id=publication_id, campaign_id=publication_id,
        privacy_boundary={"included": "contracts, per-cell seat-0 numbers and typed failures, receipt projections, "
                                      "receipt digests" + ("" if admission else ", the declared rows"),
                          "excluded": "raw provider responses, model reasoning, complete receipts and events, failure "
                                      "messages (they stay in the run roots)"},
        source_bindings={"contract_sha256s": {c["campaign_id"]: hashlib.sha256(canonical_json_bytes(c)).hexdigest()
                                              for c in contracts},
                         **({} if admission else {"analysis_sha256": hashlib.sha256(ADDENDUM_ANALYSIS.read_bytes()).hexdigest()}),
                         "source_receipt_sha256s": sorted(r["receipt_sha256"] for r in rows if r.get("receipt_sha256")),
                         "run_root_layout": "runs/housing_v15/<campaign_id>/live/[holdout_]world_<seed>__<arm>[_evidence]",
                         "replay_setup": "aeread_families.housing.price_publication:replay_setup"},
        claim_status="development" if admission else "confirmatory", winner_claim_allowed=False,
        inferential_model_ranking_allowed=not admission,
        cost_qualifier="lower_bound", total_cost_usd=round(sum(r["cost_usd"] for r in rows), 6),
        cost_basis=("every cell of the addendum's admissions" if admission else "every cell of addendum A's identity")
                   + "; a timed-out call's cost is unknown to the kernel",
    )


def _addendum_readme(a: dict[str, Any], rows: list[dict]) -> str:
    def iv(r, level="ci_0.95"):
        return f"{r['mean']:+.1f} [{r[level][0]:.1f}, {r[level][1]:.1f}]"
    b3 = a["B3"]
    lines = [f"# {ADDENDUM_ID}", "",
             "Housing v15 addendum A: GLM 5.3 Flash on Near AI fp8 as seat 0, on v15's main pack (260 worlds) and holdout",
             "(40), v15's controls, notice v5 and seat-0 scorer (plan `docs/families/housing/price_confirmatory_v15_plan.md`,",
             "Addendum A and its amendments 1 and 2). Reported beside v15, outside its Holm family; it changes nothing in",
             f"v15's results. {len(rows)} cells, {sum(r['status'] == 'completed' for r in rows)} completed.", "",
             "| Row (main pack) | $ per world [95%] |", "|---|---|",
             f"| B3: GLM − `inspect_then_sign` | {iv(b3)}; at 1 − 0.05/3 {iv(b3, 'ci_0.983')}: "
             f"{'beats' if b3['beats_baseline'] else 'does not beat'} the baseline |",
             f"| G3: GLM − best-informed tenant | {iv(a['G3'])} |",
             f"| R3: GLM − `inspect_lowball` | {iv(a['R3'])} |"]
    lines += [f"| {r['contrast']} (descriptive) | {iv(r)} |" for r in a["pairs"]]
    lines += ["", f"GLM's mean seat-0 value: main {a['glm_mean_main']:.2f}, holdout {a['glm_mean_holdout']:.2f} a world.",
              "", "`tables/cells.jsonl`, `receipts/projections.jsonl` and `reports/contracts.json` as in v15's bundle;",
              "`reports/analysis.json`: the declared rows (`tools/housing/price_v15_addendum_analysis.py`). Replay:",
              "`aeread verify-replay <bundle> --run-root runs/housing_v15/housing_lemons_price_v15_glm53_flash_nearai",
              "--setup aeread_families.housing.price_publication:replay_setup`.", ""]
    return "\n".join(lines)


def _addendum_admission_readme(rows: list[dict]) -> str:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["campaign_id"], []).append(r)
    lines = [f"# {ADDENDUM_ADMISSION_ID}", "", "Development evidence of addendum A's admission: the one-world full trajectory "
             "on each route it tried. Never analysed with the addendum's rows.", "", "| Identity | Cells | Completed | Cost $ |",
             "|---|---:|---:|---:|"]
    for cid, rs in sorted(by.items()):
        lines.append(f"| {cid} | {len(rs)} | {sum(r['status'] == 'completed' for r in rs)} | "
                     f"{sum(r['cost_usd'] for r in rs):.4f} |")
    lines += ["", "Novita's two cells were refused at OpenRouter's parameter filter before any token (HL-J-15; amendment 1);",
              "Near AI's passed. The one-call route probes are `evidence/housing/housing_lemons_price_v15_route_probes/`.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_root", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--development", action="store_true", help="the admissions and the pilot")
    parser.add_argument("--addendum", choices=("main", "admission"), help="addendum A's identity or its admissions")
    args = parser.parse_args(argv)
    manifest = publish(args.run_root, args.bundle, development=args.development, addendum=args.addendum)
    print(json.dumps({k: manifest.get(k) for k in ("publication_id", "manifest_sha256", "total_cost_usd")}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
