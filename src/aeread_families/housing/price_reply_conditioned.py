"""The v14 price panel under measure v2 (HL-D-07): a derived analysis, beside the sealed bundle.

The v14 bundle (``evidence/housing/housing_lemons_price_confirmatory_v14``) publishes seat-level
totals only, so the v2 measure (``price_reply_posterior``) cannot be computed from it: v2 needs,
per cell, the round each listing was inspected, every landlord reply to seat 0 and seat 0's commit
decisions. Those live in the sealed run roots (``runs/<campaign_id>/live``, 145 MB, not in git).

So this analysis has two steps, and both are reproducible:

1. ``--from-runs`` extracts, read-only, one row per completed cell of the three v14 identities and
   of the declared Gemini fill into ``tables/seat0_trajectories.jsonl``: those facts, seat 0's
   typed invalid actions, and the cell's receipt digest and event-root digest. Each receipt is
   read from its attempt directory, verified, and must carry the digest the published bundle
   lists for that cell.
2. Everything else is computed from that table, the two published bundles and the worlds
   regenerated from their seeds. v1 recomputed from the table must reproduce every published
   cell's ``net_realized`` and primary and the published ``analysis.json`` and fill
   ``sensitivity.json`` byte for byte (as canonical JSON); the analysis stops otherwise. The
   declared v14 analysis (``price_publication.analysis``, unchanged) is then run with v2 as the
   primary.

``--check`` regenerates every file from the committed table and compares bytes; with
``--from-runs`` it re-extracts the table from the run roots first. The published bundles are
not edited, and nothing here claims a declared verdict changed unless the numbers say so.

    python -m aeread_families.housing.price_reply_conditioned --write --from-runs
    python -m aeread_families.housing.price_reply_conditioned --check [--from-runs]

Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.publication import assert_public_payload, jsonl
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from . import price_publication as pp
from . import price_reference
from . import price_reply_posterior as posterior

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evidence/housing/housing_lemons_price_v14_reply_conditioned"
V14 = ROOT / "evidence/housing/housing_lemons_price_confirmatory_v14"
FILL = ROOT / "evidence/housing/housing_lemons_price_confirmatory_v14_gemini_fill"
RUNS = ROOT / "runs"
TRAJECTORIES = "tables/seat0_trajectories.jsonl"
SCHEMA_VERSION = "aeread.housing_price_reply_conditioned/1"
GEMINI = "housing_lemons_price_confirmatory_v14_gemini38_flash"
SHORT = {"housing_lemons_price_confirmatory_v14_glm53_flash_nextbit": "GLM",
         "housing_lemons_price_confirmatory_v14_gpt6_luna": "Luna", GEMINI: "Gemini"}
CAMPAIGNS = (*pp.V14_PANEL, pp.FILL_ID)


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _canonical(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def published() -> dict[str, list[dict[str, Any]]]:
    """The published cell rows by campaign: the three v14 identities and the fill."""
    by_campaign: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in _rows(V14 / "tables/cells.jsonl"):
        by_campaign[row["campaign_id"]].append(row)
    by_campaign[pp.FILL_ID] = _rows(FILL / "tables/cells.jsonl")
    return dict(by_campaign)


# --- step 1: the trajectory table, from the sealed run roots ----------------------------------

def extract(runs_root: Path = RUNS) -> list[dict[str, Any]]:
    """One row per published completed cell, read-only from ``runs_root``; see the module docstring."""
    rows = []
    bundle = published()
    for campaign_id in CAMPAIGNS:
        for cell in bundle[campaign_id]:
            if cell["status"] != "completed":
                continue
            seed, arm = int(cell["world_seed"]), cell["arm"]
            live = runs_root / campaign_id / "live"
            result = json.loads((live / f"world_{seed}__{arm}.json").read_text())
            attempts = sorted(glob.glob(str(live / f"world_{seed}__{arm}_evidence/runplan_*/tasks/*/attempts/*/events.jsonl")))
            if len(attempts) != 1:
                raise ValueError(f"{len(attempts)} sealed attempts for {campaign_id} {seed} {arm}")
            events = Path(attempts[0])
            receipt = read_evaluation_receipt(events.parent / "evaluation_receipt.json")  # verifies its digest
            if receipt["receipt_sha256"] != cell["receipt_sha256"] or result["receipt_sha256"] != cell["receipt_sha256"]:
                raise ValueError(f"receipt of {campaign_id} {seed} {arm} is not the one the bundle publishes")
            EvidenceStore.audit_existing(events.parent)  # verifies the sealed event chain
            seal = json.loads((events.parent / "events.jsonl.sealed.json").read_text())
            if seal["event_root_sha256"] != receipt["evidence"]["event_root_sha256"]:
                raise ValueError(f"sealed event root of {campaign_id} {seed} {arm} is not the receipt's")
            trajectory, outcome = posterior.trajectory_from_events(events)
            if canonical_json_bytes(outcome["commit_decisions"]) != canonical_json_bytes(result["outcome_facts"]["commit_decisions"]):
                raise ValueError(f"sealed outcome of {campaign_id} {seed} {arm} differs from its result file")
            seat = f"tenant_{price_reference.FOCAL_SEAT}"
            rows.append({
                "campaign_id": campaign_id, "world_seed": seed, "arm": arm,
                "receipt_sha256": cell["receipt_sha256"], "event_root_sha256": receipt["evidence"]["event_root_sha256"],
                "inspection_spend": float(outcome["tenant_inspection_spend"][seat]),
                "commit_decisions": [d for d in outcome["commit_decisions"] if int(d["tenant_id"]) == price_reference.FOCAL_SEAT],
                **trajectory.to_row(),
            })
    return rows


# --- step 2: everything else, from the table and the published bundles -------------------------

def score(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int, str], dict[str, Any]]:
    """Every extracted cell under v1 and v2; v1 must reproduce the published cell."""
    pub = {(r["campaign_id"], r["world_seed"], r["arm"]): r for rs in published().values() for r in rs}
    scored = {}
    for row in rows:
        key = (row["campaign_id"], int(row["world_seed"]), row["arm"])
        world = price_reference.make_world(key[1], key[2])
        cell = posterior.score_seat(world, row["commit_decisions"], posterior.Trajectory.from_row(row),
                                    row["inspection_spend"])
        if (cell["net_realized"], cell["primary_v1"]) != (pub[key]["net_realized"], pub[key][pp.PRIMARY]):
            raise ValueError(f"v1 from the trajectory table does not reproduce published cell {key}")
        scored[key] = {**cell, "invalid_actions": row["invalid_actions"]}
    if set(scored) != {k for k, r in pub.items() if r["status"] == "completed"}:
        raise ValueError("the trajectory table does not cover exactly the published completed cells")
    return scored


def _with_primary(rows: Sequence[Mapping[str, Any]], scored: Mapping[tuple[str, int, str], Mapping[str, Any]],
                  measure: str, campaign_id: str | None = None) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        row = dict(row)
        if row["status"] == "completed":
            row[pp.PRIMARY] = scored[(campaign_id or row["campaign_id"], row["world_seed"], row["arm"])][measure]
        out.append(row)
    return out


def _panel(scored, measure: str, with_fill: bool) -> dict[str, list[dict[str, Any]]]:
    pub = published()
    panel = {cid: _with_primary(pub[cid], scored, measure) for cid in pp.V14_PANEL}
    if with_fill:
        fill = {(r["world_seed"], r["arm"]): r for r in _with_primary(pub[pp.FILL_ID], scored, measure, pp.FILL_ID)}
        refused = {(r["world_seed"], r["arm"]) for r in pub[GEMINI] if r["status"] != "completed"}
        merged = [dict(fill[(r["world_seed"], r["arm"])], campaign_id=GEMINI, role="filled")
                  if (r["world_seed"], r["arm"]) in refused else r for r in panel[GEMINI]]
        panel = {cid: panel[cid] for cid in sorted(panel) if cid != GEMINI}
        panel[GEMINI] = merged
    return panel


def _brief(report: Mapping[str, Any]) -> dict[str, Any]:
    """Primary by scope per model, and every pair oriented as the case contract reports it."""
    iv = lambda x: {k: x[k] for k in ("n", "mean", "lo", "hi")}  # noqa: E731
    out: dict[str, Any] = {"models": {}, "pairs": {}}
    for model, entry in report["models"].items():
        out["models"][SHORT[model]] = {scope: iv(value["primary"]) for scope, value in entry["by_scope"].items()}
    for key, value in report["pairs"].items():
        a, b = (SHORT[x] for x in key.split(" - "))
        sign = -1 if b == "Gemini" else 1
        name = f"{b}-{a}" if sign < 0 else f"{a}-{b}"

        def orient(x: Mapping[str, Any]) -> dict[str, Any]:
            lo, hi = sign * x["lo"], sign * x["hi"]
            return {"n": x["n"], "mean": round(sign * x["mean"], 2), "lo": min(lo, hi), "hi": max(lo, hi), "p": x["p"]}
        main = value["main"]
        out["pairs"][name] = {"main": {**orient(main), "p_holm": main["p_holm"],
                                       "separated_after_holm": main["separated_after_holm"],
                                       "at_least_minimum_meaningful": main["at_least_minimum_meaningful"]},
                              "holdout": orient(value["holdout"])}
    return out


def _verdicts(brief: Mapping[str, Any]) -> dict[str, list[bool]]:
    return {pair: [v["main"]["separated_after_holm"], v["main"]["at_least_minimum_meaningful"]]
            for pair, v in brief["pairs"].items()}


def _counts(scored, model: str) -> dict[str, Any]:
    pub = {(r["world_seed"], r["arm"]): r for r in published()[model]}
    cells = {k[1:]: v for k, v in scored.items() if k[0] == model}
    blind = [(pub[k], b) for k, v in cells.items() for b in v["blind_signings"]]
    changed = [(r, b) for r, b in blind if abs(b["value_v2"] - b["value_v1"]) > 0.005]
    invalid: collections.Counter[str] = collections.Counter()
    for v in cells.values():
        invalid.update(v["invalid_actions"])
    return {
        "completed_cells": len(cells),
        "blind_signings": len(blind),
        "blind_signings_after_a_sound_counter_this_round": sum(b["reply_this_round"] == "sound" for _, b in blind),
        "changed_signings": len(changed),
        "changed_signings_main_pack": sum(r["population"] == "main" for r, _ in changed),
        "changed_by_a_reply_on_the_signed_listing": sum(b["reply_this_round"] is not None for _, b in changed),
        "changed_by_a_reply_on_another_listing": sum(b["reply_this_round"] is None for _, b in changed),
        "changed_signings_all_sound": all(b["quality"] == "sound" for _, b in changed),
        "sum_value_change_usd": round(float(sum(b["value_v2"] - b["value_v1"] for _, b in changed)), 2),
        "informative_replies": sum(v["informative_replies"] for v in cells.values()),
        "cells_with_invalid_seat0_actions": sum(bool(v["invalid_actions"]) for v in cells.values()),
        "invalid_seat0_actions_by_code": dict(sorted(invalid.items())),
    }


def analyse(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scored = score(rows)
    v1 = pp.analysis(_panel(scored, "primary_v1", with_fill=False))
    if _canonical(v1) != json.loads((V14 / "reports/analysis.json").read_text()):
        raise ValueError("v1 from the trajectory table does not reproduce the published v14 analysis")
    v1_fill = pp.analysis(_panel(scored, "primary_v1", with_fill=True))
    if _canonical(v1_fill) != json.loads((FILL / "reports/sensitivity.json").read_text())["v14_analysis_with_fill"]:
        raise ValueError("v1 from the trajectory table does not reproduce the published fill sensitivity")
    v2 = pp.analysis(_panel(scored, "primary_v2", with_fill=False))
    v2_fill = pp.analysis(_panel(scored, "primary_v2", with_fill=True))
    brief = {"v1": _brief(v1), "v2": _brief(v2), "v1_with_fill": _brief(v1_fill), "v2_with_fill": _brief(v2_fill)}
    table = [{"campaign_id": cid, "world_seed": seed, "arm": arm, "net_realized": v["net_realized"],
              "primary_v1": v["primary_v1"], "primary_v2": v["primary_v2"],
              "changed_signings": v["changed_signings"], "informative_replies": v["informative_replies"]}
             for (cid, seed, arm), v in sorted(scored.items())]
    report = {
        "schema_version": SCHEMA_VERSION,
        "measure": posterior.MEASURE,
        "inputs": {
            "v14_manifest_sha256": json.loads((V14 / "publication_manifest.json").read_text())["manifest_sha256"],
            "fill_manifest_sha256": json.loads((FILL / "publication_manifest.json").read_text())["manifest_sha256"],
            "trajectory_table_sha256": hashlib.sha256(_trajectory_bytes(rows)).hexdigest(),
            "trajectory_rows": len(rows),
        },
        "reproduction": {"published_cells": "net_realized and primary of every completed cell, exact",
                         "published_analysis": "reports/analysis.json, exact", "fill_sensitivity": "reports/sensitivity.json, exact"},
        "declared_verdicts_changed": _verdicts(brief["v1"]) != _verdicts(brief["v2"]),
        "summary": brief,
        "counts": {SHORT.get(m, "Gemini fill"): _counts(scored, m) for m in CAMPAIGNS},
        "v2_analysis": v2,
        "v2_analysis_with_fill": v2_fill,
    }
    return report, table


def _trajectory_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return jsonl(list(rows))


def _report_bytes(report: Mapping[str, Any]) -> bytes:
    return (json.dumps(report, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _fmt(x: Mapping[str, Any]) -> str:
    return f"{x['mean']:+.0f} [{x['lo']:+.0f}, {x['hi']:+.0f}]"


def _readme(report: Mapping[str, Any]) -> str:
    s, c = report["summary"], report["counts"]
    lines = [
        f"# {OUT.name}",
        "",
        "The v14 confirmatory price panel scored under measure v2 (`price_reply_posterior`, HL-D-07): each blind "
        "signing at its lemon probability given every inspection and every informative landlord reply seat 0 had seen, "
        "instead of v1's reading of a hold below the sound floor only. A derived analysis beside the sealed v14 bundle, "
        "which is not edited: `python -m aeread_families.housing.price_reply_conditioned`; `--check` regenerates these "
        "bytes, and `--check --from-runs` first re-extracts the trajectory table from the sealed run roots.",
        "",
        "v1 recomputed from `tables/seat0_trajectories.jsonl` reproduces every published cell and the published "
        "`analysis.json` and fill `sensitivity.json` exactly; v2 then runs the declared analysis unchanged.",
        "",
        "| | GLM | Luna | Gemini |",
        "|---|---|---|---|",
        "| primary, main pack, v1 (published) | " + " | ".join(_fmt(s["v1"]["models"][m]["main"]) for m in ("GLM", "Luna", "Gemini")) + " |",
        "| primary, main pack, v2 | " + " | ".join(_fmt(s["v2"]["models"][m]["main"]) for m in ("GLM", "Luna", "Gemini")) + " |",
        "| blind signings v2 reprices (all populations) | " + " | ".join(str(c[m]["changed_signings"]) for m in ("GLM", "Luna", "Gemini")) + " |",
        "| of them on a reply on another listing | " + " | ".join(str(c[m]["changed_by_a_reply_on_another_listing"]) for m in ("GLM", "Luna", "Gemini")) + " |",
        "| cells with an invalid seat-0 action | " + " | ".join(str(c[m]["cells_with_invalid_seat0_actions"]) for m in ("GLM", "Luna", "Gemini")) + " |",
        "",
        "| Pair, main pack | v1 (published) | v2 | v2, Holm p | v2 with the fill | v2 holdout |",
        "|---|---|---|---|---|---|",
    ]
    for pair in ("Gemini-GLM", "Gemini-Luna", "GLM-Luna"):
        v1, v2, vf = s["v1"]["pairs"][pair], s["v2"]["pairs"][pair], s["v2_with_fill"]["pairs"][pair]
        lines.append(f"| {pair} | {_fmt(v1['main'])} | {_fmt(v2['main'])} | {v2['main']['p_holm']:.2g} | "
                     f"{_fmt(vf['main'])} | {_fmt(v2['holdout'])} |")
    lines += [
        "",
        f"Declared verdicts (separated after Holm; at least the $50 band) changed: "
        f"{'yes' if report['declared_verdicts_changed'] else 'no'}. Every repriced signing was of a sound listing. "
        "Invalid seat-0 actions are counted by the kernel's typed code (the family applies one as a pass): "
        + "; ".join(f"{m} " + (", ".join(f"{code} {n}" for code, n in c[m]["invalid_seat0_actions_by_code"].items()) or "none")
                    for m in ("GLM", "Luna", "Gemini")) + ".",
        "",
        "Files: `tables/seat0_trajectories.jsonl` (per completed cell: seat 0's commit decisions, inspection rounds, "
        "landlord replies, typed invalid actions, receipt and event-root digests; numbers only), `tables/cells.jsonl` "
        "(v1 and v2 per cell), `reports/reply_conditioned.json` (the declared analysis under v2, with and without the "
        "fill, and the counts).",
        "",
    ]
    return "\n".join(lines)


def _files(rows: Sequence[Mapping[str, Any]]) -> dict[str, bytes]:
    report, table = analyse(rows)
    files = {TRAJECTORIES: _trajectory_bytes(rows), "tables/cells.jsonl": jsonl(table),
             "reports/reply_conditioned.json": _report_bytes(report), "README.md": _readme(report).encode("utf-8")}
    for name, payload in files.items():
        assert_public_payload(name, payload)
    return files


def committed_rows() -> list[dict[str, Any]]:
    return _rows(OUT / TRAJECTORIES)


def write(from_runs: bool) -> None:
    for name, payload in _files(extract() if from_runs else committed_rows()).items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def check(from_runs: bool) -> bool:
    rows = committed_rows()
    ok = True
    if from_runs:
        ok = _trajectory_bytes(extract()) == (OUT / TRAJECTORIES).read_bytes()
        print("trajectory table re-extracts from the run roots to the committed bytes" if ok
              else "trajectory table differs from the run roots")
    same = all((OUT / name).read_bytes() == payload for name, payload in _files(rows).items())
    print("reply-conditioned analysis regenerates to the committed bytes" if same
          else "reply-conditioned analysis differs from its generator")
    return ok and same


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--from-runs", action="store_true", help="extract the trajectory table from runs/ (read-only)")
    args = parser.parse_args(argv)
    if args.write:
        write(args.from_runs)
        return 0
    if args.check:
        return 0 if check(args.from_runs) else 1
    report, _ = analyse(extract() if args.from_runs else committed_rows())
    print(json.dumps({k: report[k] for k in ("summary", "counts", "declared_verdicts_changed")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
