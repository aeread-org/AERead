"""Publish a risk-allocation campaign as an evidence bundle.

    python -m aeread_families.datacenter_development.risk_allocation_publication runs/<campaign> evidence/datacenter_development/<campaign>

Reads only the campaign's cell records and its sealed receipts. The bundle holds:

- ``receipts/projections.jsonl``: every receipt, projected onto the publishable fields;
- ``tables/cells.jsonl``: one row per cell with the grade's diagnostics and the world's cell name;
- ``reports/summary.json``: per arm, route and seat, valid cells, mean decision regret, how often the
  model signed a package other than its first and the efficient one, with the rules' regret on the
  same worlds from the pack manifest; the cell accounting, replay, cost qualifier and claim flags
  under the keys the examiner reads; and, when the campaign declared one, its two-model contrast;
- ``README.md``; the kernel manifest; and the kernel trajectory grain.

Provider text and raw event logs stay in the run directory.
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

from . import risk_allocation_pack as rp


def _records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((run_dir / "cells").glob("*.json"))]


def _failure_cause(evidence_root: Path) -> str | None:
    """Why an excluded cell ended, from its sealed event log: the failed logical action's condition
    (``rate_limit``, ``empty_response``...). The receipt says only ``invalid_measurement``."""
    for events in sorted(evidence_root.rglob("events.jsonl")):
        for line in events.read_text().splitlines():
            event = json.loads(line)
            if event.get("event_type") == "logical_action_failed":
                return json.loads((events.parent / event["payload_ref"]).read_text()).get("failure_condition")
    return None


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
            "replicate_index": r.get("replicate_index", 0),
            "world": w.get("slug"), "world_cell": w.get("cell"), "twin_of": w.get("twin_of"),
            "receipt_sha256": r["receipt_sha256"], "receipt_status": r["status"], "termination": r.get("termination"),
            "valid": g.get("valid"), "invalid": g.get("invalid"), "decision_regret": g.get("decision_regret"),
            "allocation_gap": g.get("allocation_gap"), "price_gap": g.get("price_gap"), "signed_package": g.get("signed_package"),
            "efficient_package": g.get("efficient_package"), "first_proposed_package": g.get("first_proposed_package"),
            "switched_package": g.get("switched_package"), "refused_rounds": g.get("refused_rounds"), "cost_usd": r.get("cost_usd"),
            "provider_calls": r.get("provider_calls"), "calls_outcome_unknown": r.get("calls_outcome_unknown"),
            "failure_cause": _failure_cause(run_dir / "evidence" / r["cell_key"]) if r["status"] != "ok" else None,
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
            reason = row.get("invalid") or row.get("failure_cause") or row.get("receipt_status") or row.get("note") or "unknown"
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
        "analysis": analysis(rows, list(plan["arms"]), plan.get("declared_analysis") or {}),
        "campaign_id": plan["campaign_id"], "plan_sha256": plan["plan_sha256"], "claim_status": plan["claim_status"],
        "arms": plan["arms"], "routes": sorted(plan["routes"]), "groups": dict(sorted(groups.items())),
        "cost_usd_total": round(sum(g["cost_usd"] for g in groups.values()), 4),
    }
    if plan.get("declared_analysis"):
        summary.update(accounting(plan, records, rows))
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


MODELS = ("gemini38_flash", "glm53_flash")  # the declared contrast is the second minus the first
SCRIPTED = "scripted_"


def _pair_key(row: dict[str, Any]) -> tuple[str, int]:
    """Cells pair on world and replicate: both models answered the same world under the same request seed."""
    return (row["world"], int(row.get("replicate_index") or 0))


def _paired(a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]], rng: random.Random) -> dict[str, Any] | None:
    """Mean of b minus a over pairs valid on both sides, with a world-clustered bootstrap interval."""
    a = {_pair_key(r): r for r in a_rows if r.get("valid")}
    diffs: dict[str, list[float]] = {}
    for r in b_rows:
        if r.get("valid") and _pair_key(r) in a:
            diffs.setdefault(_cluster(r), []).append(r["decision_regret"] - a[_pair_key(r)]["decision_regret"])
    flat = [x for d in diffs.values() for x in d]
    if not flat:
        return None
    return {"pairs": len(flat), "worlds": len(diffs), "mean_difference": round(statistics.fmean(flat), 3),
            "ci95": _cluster_bootstrap(diffs, rng), "second_lower": sum(x < -1.0 for x in flat),
            "second_higher": sum(x > 1.0 for x in flat), "within_one": sum(abs(x) <= 1.0 for x in flat)}


def _run_to_run(rs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The two replicates of each world: how far the model's regret and its contract moved between them."""
    by_world: dict[str, dict[int, dict[str, Any]]] = {}
    for r in rs:
        if r.get("valid"):
            by_world.setdefault(r["world"], {})[int(r.get("replicate_index") or 0)] = r
    both = [(w[0], w[1]) for w in by_world.values() if 0 in w and 1 in w]
    if not both:
        return None
    gaps = [b["decision_regret"] - a["decision_regret"] for a, b in both]
    means = [(a["decision_regret"] + b["decision_regret"]) / 2 for a, b in both]
    within = math.sqrt(statistics.fmean(g * g for g in gaps) / 2)
    between = statistics.pstdev(means) if len(means) > 1 else 0.0
    return {"worlds_with_both": len(both), "mean_abs_gap": round(statistics.fmean(abs(g) for g in gaps), 3),
            "within_world_sd": round(within, 3), "between_world_sd_of_means": round(between, 3),
            "within_share_of_variance": round(within ** 2 / (within ** 2 + between ** 2), 3) if within or between else None,
            "same_contract_both_replicates": sum(a["signed_package"] == b["signed_package"] for a, b in both)}


def analysis(rows: list[dict[str, Any]], arms: list[str], declared: dict[str, Any] | None = None) -> dict[str, Any]:
    """The analysis CLAUDE.md asks for: distributions, run-to-run variance, clustered and paired
    intervals, judge agreement, and what else the numbers suggest (labelled exploratory). A campaign
    that declared a two-model contrast in its frozen plan gets that contrast, its controls and the
    spread between replicates."""
    rng = random.Random(BOOTSTRAP_SEED)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(f"{row['arm']}/{row['route_id']}/{row['seat']}", []).append(row)
    replicated = any(int(r.get("replicate_index") or 0) > 0 for r in rows)
    out: dict[str, Any] = {
        "run_to_run_variance": ("per model group below (`run_to_run`): two replicates per world under different request seeds"
                                if replicated else "unmeasured: one run per cell. The break-off draws are fixed per world, so a later "
                                "replicate campaign would measure the model's own spread."),
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
                label = f"missing: {r.get('invalid') or r.get('failure_cause') or r.get('receipt_status') or 'unsealed'}"
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
        if replicated and not key.split("/")[1].startswith(SCRIPTED):
            out["groups"][key]["run_to_run"] = _run_to_run(rs)
    for arm in arms:
        if arm == BASE_ARM or arm not in {k.split("/")[0] for k in groups}:
            continue
        for key in sorted(groups):
            a, route, seat = key.split("/")
            if a != arm or route.startswith(SCRIPTED) or f"{BASE_ARM}/{route}/{seat}" not in groups:
                continue
            d = _paired(groups[f"{BASE_ARM}/{route}/{seat}"], groups[key], rng)
            if d:
                out["paired_vs_" + BASE_ARM][key] = {"worlds": d["pairs"], "clusters": d["worlds"], "mean_difference": d["mean_difference"],
                                                     "ci95": d["ci95"]}
    if declared:
        out["declared"] = dict(declared)
        contrast: dict[str, Any] = {}
        for key in sorted(groups):
            arm, route, seat = key.split("/")
            if route != MODELS[1] or f"{arm}/{MODELS[0]}/{seat}" not in groups:
                continue
            first, second = groups[f"{arm}/{MODELS[0]}/{seat}"], groups[key]
            d = _paired(first, second, rng)
            contrast[f"{arm}/{seat}"] = {
                **(d or {"pairs": 0}),
                "missing": {m: {k: v for k, v in out["groups"][f"{arm}/{m}/{seat}"]["outcomes"].items() if k.startswith("missing")}
                            for m in MODELS},
            }
        out["model_contrast_" + "_minus_".join(reversed(MODELS))] = contrast
        controls: dict[str, Any] = {}
        for key, rs in sorted(groups.items()):
            _arm, route, seat = key.split("/")
            if route.startswith(SCRIPTED):
                g = out["groups"][key]
                controls[f"{route[len(SCRIPTED):]}/{seat}"] = {"cells": g["cells"], "valid": g["valid"],
                                                              "mean_regret": (g["decision_regret"] or {}).get("mean"),
                                                              "max_regret": (g["decision_regret"] or {}).get("max")}
        out["controls"] = controls
        out["reference_is_zero_everywhere"] = all(
            (c["max_regret"] or 0.0) < 1e-6 and c["valid"] == c["cells"] for k, c in controls.items() if k.startswith("reference/"))
    return out


def accounting(plan: dict[str, Any], records: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The run's accounting under the keys the examiner reads, each derived from the cell records."""
    planned = sum(len(p["cells"]) for p in plan["plans"])
    executed = [r for r in records if r.get("status") == "ok"]
    excluded = [r for r in records if r.get("receipt_sha256") and r.get("status") != "ok"]
    valid = sum(1 for row in rows if row.get("valid"))
    unknown = sum(int(r.get("calls_outcome_unknown") or 0) for r in records)
    replay_failed = [r["cell_key"] for r in records if "replay produced a different receipt" in str(r.get("error", ""))]
    worlds = {_cluster(r) for r in rows if r.get("world")}
    return {
        "planned_cells": planned, "completed_cells": len(executed), "operational_failure_cells": len(excluded),
        "not_attempted_cells": planned - len(executed) - len(excluded), "included_cells": valid, "excluded_cells": planned - valid,
        "missingness_fraction": round((planned - valid) / planned, 4) if planned else None,
        "replay_verified": not replay_failed and bool(executed),
        "replay_note": f"every one of the {len(executed)} executed receipts was replayed from its sealed evidence to the same digest during the run; "
                       "a mismatch would have excluded the cell",
        "cost_qualifier": "lower_bound" if unknown else "exact",
        "provider_cost_complete": not unknown,
        "total_cost_usd": round(math.fsum(float(r.get("cost_usd") or 0.0) for r in records), 4),
        "cost_note": ("every answered provider call of every cell, read from the sealed event logs at the declared per-token prices"
                      + (f"; {unknown} call(s) ended with the outcome unknown (a dropped connection) and may have been billed, so the total is a floor"
                         if unknown else "")),
        "independent_cluster_count": len(worlds),
        "winner_claim_allowed": False, "inferential_model_ranking_allowed": False, "causal_condition_effect_allowed": False,
        "claim_scope": "diagnostic: a declared paired contrast of two models on one generated pack, reported with intervals; "
                       "not a model ranking and not a population estimate",
    }


def _ci(ci: list[float] | None) -> str:
    return f" [{ci[0]}, {ci[1]}]" if ci else ""


def _readme(summary: dict[str, Any]) -> str:
    a = summary["analysis"]
    declared = a.get("declared")
    packs = sorted({arm.get("pack") for arm in summary["arms"].values() if arm.get("pack")})
    lines = [
        f"# {summary['campaign_id']}",
        "",
        "The integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`) run through the",
        "shared runner: every episode sealed, verified and replayed. "
        + (f"Pack {', '.join(f'`{p}`' for p in packs)}, {summary.get('independent_cluster_count', '?')} independent worlds (a twin counts with "
           "its base world), two replicates per model cell, scripted controls seated in the run. It declares one two-model "
           "contrast and does not rank models." if declared else
           "A diagnostic dev campaign on a 16-world pack, one run per cell, both seats of every world. It does not rank models."),
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
    if declared:
        contrast = a["model_contrast_" + "_minus_".join(reversed(MODELS))]
        lines += ["", "## The declared contrast", "", f"{declared['primary'][0].upper() + declared['primary'][1:]}. {declared['interval']}. "
                  f"{declared['missingness'][0].upper() + declared['missingness'][1:]}. Negative means GLM gave up less.", "",
                  "| arm / seat | pairs (worlds) | GLM minus Gemini [95% CI] | GLM lower / higher / within $1k | missing, Gemini | missing, GLM |",
                  "|---|---|---|---|---|---|"]
        for key, d in contrast.items():
            miss = {m: ", ".join(f"{k.split(': ', 1)[1]} {v}" for k, v in d["missing"][m].items()) or "none" for m in MODELS}
            lines.append(f"| {key} | {d['pairs']} ({d.get('worlds', 0)}) | " + (f"{d['mean_difference']}{_ci(d['ci95'])}" if d["pairs"] else "—")
                         + f" | {d.get('second_lower', 0)} / {d.get('second_higher', 0)} / {d.get('within_one', 0)} | {miss[MODELS[0]]} | {miss[MODELS[1]]} |")
        lines += ["", f"Claim: {declared['claim']}.", "", "## Run to run", "",
                  "| arm / route / seat | worlds with both replicates | mean gap between replicates | within-world SD | share of variance within worlds | same contract both times |",
                  "|---|---|---|---|---|---|"]
        for key, g in a["groups"].items():
            r = g.get("run_to_run")
            if r:
                lines.append(f"| {key} | {r['worlds_with_both']} | {r['mean_abs_gap']} | {r['within_world_sd']} | {r['within_share_of_variance']} | "
                             f"{r['same_contract_both_replicates']} of {r['worlds_with_both']} |")
        lines += ["", "## Controls in the run", "", "| policy / seat | valid | mean regret | max regret |", "|---|---|---|---|"]
        for key, c in a["controls"].items():
            lines.append(f"| {key} | {c['valid']}/{c['cells']} | {c['mean_regret']} | {c['max_regret']} |")
        lines += ["", f"The reference graded zero regret on every cell: {a['reference_is_zero_everywhere']}."]
    lines += ["", "## Distributions", "", f"- Run-to-run variance: {a['run_to_run_variance']}", f"- Judges: {a['judges']}", f"- Intervals: {a['intervals']}.", "",
              "| arm / route / seat | valid | mean regret [95% CI] | median | strict pass (zero regret) |", "|---|---|---|---|---|"]
    for key, g in a["groups"].items():
        d = g["decision_regret"]
        lines.append(f"| {key} | {g['valid']}/{g['cells']} | " + (f"{d['mean']}{_ci(d['mean_ci95'])}" if d else "—")
                     + f" | {d['median'] if d else '—'} | {g['strict_pass_zero_regret']} |")
    lines += ["", f"Paired against `{BASE_ARM}` on the same worlds (difference in decision regret, $ thousands; negative is better):", "",
              "| arm / route / seat | pairs | mean difference [95% CI] |", "|---|---|---|"]
    for key, d in a["paired_vs_" + BASE_ARM].items():
        lines.append(f"| {key} | {d['worlds']} | {d['mean_difference']}{_ci(d['ci95'])} |")
    if "planned_cells" in summary:
        lines += ["", "## Accounting", "",
                  f"{summary['completed_cells']} of {summary['planned_cells']} planned cells executed, {summary['operational_failure_cells']} sealed as typed "
                  f"exclusions, {summary['not_attempted_cells']} not attempted; {summary['included_cells']} valid episodes. Replay verified: "
                  f"{summary['replay_verified']}. Cost ${summary['total_cost_usd']:.2f} ({summary['cost_qualifier']}): {summary['cost_note']}."]
    else:
        lines += ["", f"Total cost ${summary['cost_usd_total']:.2f}."]
    lines += ["", f"Plan `{summary['plan_sha256'][:12]}`.", ""]
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
