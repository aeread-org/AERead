"""Publish the v14 confirmatory price panel as one sealed, sanitized evidence bundle.

The three v14 identities (``price_campaign.IDENTITIES``, ``confirmatory_v14``) share every
control but the model and its route, so they are one bundle. This module reads each run root's
result files, scores every completed cell with ``price_endpoint.score_cell``, adds the reachable
reference and the full-information ceiling for the same world and arm (``price_reference``), and
computes exactly the analysis the contracts declared before any v14 cell ran
(``price_campaign.CONFIRMATORY_ANALYSIS``). Rows carry numbers, digests and typed conditions
only: no prompt, response, reasoning or failure message leaves the run root.

Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from scipy import stats

from aeread.shared_runner.run.publication import (
    assert_public_payload,
    atomic_publish,
    jsonl,
    seal_publication_manifest,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import price_campaign, price_endpoint, price_reference

PUBLICATION_ID = "housing_lemons_price_confirmatory_v14"
ARMS = ("true_cost", "pooled")
SEAT = 0
SEAT_FIELDS = ("net_realized", "net_expected_stated_odds", "net_expected_response_odds",
               "reply_leak_expected_loss", "signed_blind", "signed_blind_after_revealing_reply",
               "walked_revealing_reply", "inspection_spend")
PRIMARY = "net_expected_response_odds"


def _population() -> tuple[dict[int, str], dict[int, str]]:
    population, stratum = {}, {}
    for part in ("main", "holdout"):
        for name, seeds in price_campaign.PACK[part]["by_stratum"].items():
            for seed in seeds:
                population[int(seed)] = part
                stratum[int(seed)] = name
    return population, stratum


def cell_rows(contract: Mapping[str, Any], run_root: Path) -> list[dict[str, Any]]:
    """One public row per planned cell of one identity: outcome numbers or typed missingness."""
    population, stratum = _population()
    found = {}
    for path in sorted((run_root / "live").glob("world_*__*.json")):
        row = json.loads(path.read_text())
        if "world_seed" in row:
            found[(int(row["world_seed"]), row["arm"])] = row
    rows = []
    for seed in contract["world_seeds"]:
        for arm in contract["arms"]:
            row = found.get((int(seed), arm), {"status": "not_attempted", "cost_usd": 0.0})
            public = {
                "campaign_id": contract["campaign_id"], "world_seed": int(seed), "arm": arm,
                "population": population[int(seed)], "stratum": stratum[int(seed)],
                "status": row["status"], "failure_condition": row.get("failure_condition"),
                "cost_usd": round(float(row.get("cost_usd", 0.0)), 6),
                "receipt_sha256": row.get("receipt_sha256"), "run_plan_id": row.get("run_plan_id"),
                "cell_id": row.get("cell_id"),
                "reference_net": price_reference.seat_net(
                    price_reference.run_world(seed, arm, price_reference.inspect_lowball_action)),
                "ceiling": price_reference.ceiling(seed, arm),
            }
            if row["status"] == "completed":
                scored = price_endpoint.score_cell(row["outcome_facts"], world_seed=int(seed), arm=arm)
                seat = scored["by_seat"][SEAT]
                public.update({field: seat[field] for field in SEAT_FIELDS})
                signed = [d for d in scored["decisions"] if d["tenant_id"] == SEAT and d["decision"] == "sign"]
                public["signed"] = bool(signed)
                public["ended_on_inspected_listing"] = bool(signed) and all(d["informed"] for d in signed)
            rows.append(public)
    return rows


def _interval(values: Sequence[float]) -> dict[str, Any]:
    n = len(values)
    if n < 2:
        return {"n": n, "mean": round(values[0], 2) if values else None, "lo": None, "hi": None, "p": None}
    mean = statistics.fmean(values)
    se = statistics.stdev(values) / math.sqrt(n)
    half = float(stats.t.ppf(0.975, n - 1)) * se
    p = float(2 * stats.t.sf(abs(mean / se), n - 1)) if se > 0 else (0.0 if mean else 1.0)
    return {"n": n, "mean": round(mean, 2), "lo": round(mean - half, 2), "hi": round(mean + half, 2), "p": p}


def _holm(pvalues: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues, key=pvalues.get)
    adjusted, running = {}, 0.0
    for rank, key in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * pvalues[key]))
        adjusted[key] = running
    return adjusted


def per_world(rows: Sequence[Mapping[str, Any]], field: str, *, population: str | None = "main",
              stratum: str | None = None) -> dict[int, float]:
    """A world's value: the mean of its two arms; a world missing an arm is left out."""
    by_world: dict[int, dict[str, float]] = {}
    for row in rows:
        if row["status"] != "completed" or (population and row["population"] != population):
            continue
        if stratum and row["stratum"] != stratum:
            continue
        by_world.setdefault(row["world_seed"], {})[row["arm"]] = float(row[field])
    return {seed: statistics.fmean(arms.values()) for seed, arms in by_world.items() if len(arms) == len(ARMS)}


def analysis(rows_by_model: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """The declared analysis, computed; nothing here was chosen after seeing v14 data."""
    reference_rows = next(iter(rows_by_model.values()))
    out: dict[str, Any] = {"declared": price_campaign.CONFIRMATORY_ANALYSIS, "models": {}, "pairs": {}}
    scopes = {"main": {"population": "main"}, "holdout": {"population": "holdout"},
              "main_favourite_is_lemon": {"population": "main", "stratum": "favourite_is_lemon"},
              "main_favourite_is_sound": {"population": "main", "stratum": "favourite_is_sound"}}
    for model, rows in rows_by_model.items():
        cells = len(rows)
        entry: dict[str, Any] = {
            "planned_cells": cells,
            "completed_cells": sum(r["status"] == "completed" for r in rows),
            "operational_failures": sum(r["status"] == "operational_failure" for r in rows),
            "not_attempted": sum(r["status"].startswith("not_attempted") for r in rows),
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
            "by_scope": {},
        }
        for scope, selector in scopes.items():
            level = per_world(rows, PRIMARY, **selector)
            realized = per_world(rows, "net_realized", **selector)
            reference = {s: statistics.fmean(r["reference_net"] for r in reference_rows if r["world_seed"] == s)
                         for s in level}
            ceiling = {s: statistics.fmean(r["ceiling"] for r in reference_rows if r["world_seed"] == s)
                       for s in level}
            done = [r for r in rows if r["status"] == "completed" and r["population"] == selector["population"]
                    and ("stratum" not in selector or r["stratum"] == selector["stratum"])]
            entry["by_scope"][scope] = {
                "worlds_with_both_arms": len(level),
                "primary": _interval(list(level.values())),
                "realized": _interval(list(realized.values())),
                "minus_reference": _interval([level[s] - reference[s] for s in level]),
                "realized_share_of_reference": round(sum(realized.values()) / sum(reference.values()), 4) if level else None,
                "realized_share_of_ceiling": round(sum(realized.values()) / sum(ceiling.values()), 4) if level else None,
                "revealed_lemon_holds_signed": sum(r["signed_blind_after_revealing_reply"] for r in done),
                "revealed_lemon_holds_walked": sum(r["walked_revealing_reply"] for r in done),
                "cells_ending_on_an_inspected_listing": sum(r["ended_on_inspected_listing"] for r in done),
                "cells_signed": sum(r["signed"] for r in done),
                "cells": len(done),
            }
        out["models"][model] = entry
    raw = {}
    for a, b in itertools.combinations(rows_by_model, 2):
        left, right = per_world(rows_by_model[a], PRIMARY), per_world(rows_by_model[b], PRIMARY)
        both = sorted(set(left) & set(right))
        key = f"{a} - {b}"
        out["pairs"][key] = {"main": _interval([left[s] - right[s] for s in both])}
        holdout_left = per_world(rows_by_model[a], PRIMARY, population="holdout")
        holdout_right = per_world(rows_by_model[b], PRIMARY, population="holdout")
        hold = sorted(set(holdout_left) & set(holdout_right))
        out["pairs"][key]["holdout"] = _interval([holdout_left[s] - holdout_right[s] for s in hold])
        raw[key] = out["pairs"][key]["main"]["p"]
    adjusted = _holm({k: v for k, v in raw.items() if v is not None})
    mmd = price_campaign.CONFIRMATORY_ANALYSIS["minimum_meaningful_difference_usd_per_world"]
    for key, value in out["pairs"].items():
        main = value["main"]
        main["p_holm"] = adjusted.get(key)
        main["separated_after_holm"] = main["p_holm"] is not None and main["p_holm"] < 0.05
        main["at_least_minimum_meaningful"] = main["mean"] is not None and abs(main["mean"]) >= mmd
    return out


def publish(contract_paths: Sequence[Path], run_roots: Sequence[Path], publication_root: Path) -> dict[str, Any]:
    contracts = [price_campaign.load_contract(path) for path in contract_paths]
    if {c["campaign_id"] for c in contracts} != {k for k in price_campaign.IDENTITIES if "confirmatory_v14" in k}:
        raise ValueError("the v14 bundle publishes exactly the three v14 identities")
    bundle = Path(publication_root)
    if bundle.exists() and any(bundle.iterdir()):
        raise ValueError(f"publication root is not empty: {bundle}")
    rows_by_model = {c["campaign_id"]: cell_rows(c, Path(root)) for c, root in zip(contracts, run_roots)}
    report = analysis(rows_by_model)
    all_rows = [row for rows in rows_by_model.values() for row in rows]
    files = {
        "tables/cells.jsonl": jsonl(all_rows),
        "reports/analysis.json": canonical_json_bytes(report) + b"\n",
        "reports/contracts.json": canonical_json_bytes({c["campaign_id"]: c for c in contracts}) + b"\n",
        "reports/pack.json": canonical_json_bytes(price_campaign.PACK) + b"\n",
        "README.md": _readme(report).encode("utf-8"),
    }
    bundle.mkdir(parents=True, exist_ok=True)
    for relative, payload in files.items():
        assert_public_payload(relative, payload)
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_publish(path, payload)
    receipts = sorted({row["receipt_sha256"] for row in all_rows if row.get("receipt_sha256")})
    return seal_publication_manifest(
        bundle,
        publication_id=PUBLICATION_ID,
        campaign_id=PUBLICATION_ID,
        privacy_boundary={
            "included": "contracts, the pack, per-cell numeric outcomes with typed failure conditions, "
                        "receipt digests, the declared analysis computed",
            "excluded": "raw provider responses, model reasoning, complete receipts, failure messages, "
                        "provider identifiers, and the kernel trajectory grain (see README)",
        },
        source_bindings={
            "contract_paths": [f"configs/{Path(path).name}" for path in contract_paths],
            "contract_sha256s": {c["campaign_id"]: hashlib.sha256(canonical_json_bytes(c)).hexdigest()
                                 for c in contracts},
            "pack_sha256": price_campaign.PACK["sha256"],
            "source_receipt_sha256s": receipts,
            "run_root_layout": "runs/<campaign_id>/live/world_<seed>__<arm>[_evidence]",
        },
        claim_status="confirmatory",
        winner_claim_allowed=False,
        inferential_model_ranking_allowed=True,
        cost_qualifier="lower_bound",
        total_cost_usd=round(sum(m["cost_usd"] for m in report["models"].values()), 6),
        cost_basis="every v14 cell of the three identities, completed and failed; a timed-out call's cost is unknown "
                   "to the kernel and not counted, so the total is a lower bound; the full-trajectory gates are the "
                   "first world of each run and are included",
    )


def _fmt(interval: Mapping[str, Any]) -> str:
    if interval["mean"] is None or interval["lo"] is None:
        return "n/a"
    return f"{interval['mean']:+.0f} [{interval['lo']:+.0f}, {interval['hi']:+.0f}]"


def _pct(share: float | None) -> str:
    return "n/a" if share is None else f"{100 * share:.0f}%"


def _readme(report: Mapping[str, Any]) -> str:
    lines = [
        f"# {PUBLICATION_ID}",
        "",
        "Confirmatory panel of the Housing lemons price case with one deciding tenant and outside demand: "
        "three models on the same 260-world pack and 40-world holdout, both landlord arms, one replicate. "
        "The rules are in the sealed tenant prompt and the reply history in the sealed observation (notice v4). "
        "The analysis below is the one declared in the contracts before any v14 cell ran.",
        "",
        "Primary measure: seat 0's net at the reply-conditioned odds, mean of the two arms, per world; "
        "95% Student-t over worlds; Holm over the three model pairs.",
        "",
        "| Model | Completed cells | Primary, main pack | Minus reachable reference | Realized share of reference | Holdout primary | Cost |",
        "|---|---|---|---|---|---|---|",
    ]
    for model, entry in report["models"].items():
        main, holdout = entry["by_scope"]["main"], entry["by_scope"]["holdout"]
        lines.append(
            f"| `{model}` | {entry['completed_cells']} of {entry['planned_cells']} | {_fmt(main['primary'])} | "
            f"{_fmt(main['minus_reference'])} | {_pct(main['realized_share_of_reference'])} | {_fmt(holdout['primary'])} | "
            f"${entry['cost_usd']:.2f} |")
    lines += ["", "| Pair | Main pack | Holm p | Holdout |", "|---|---|---|---|"]
    for pair, value in report["pairs"].items():
        p = value["main"]["p_holm"]
        lines.append(f"| `{pair}` | {_fmt(value['main'])} | {p:.3g} | {_fmt(value['holdout'])} |" if p is not None
                     else f"| `{pair}` | {_fmt(value['main'])} | n/a | {_fmt(value['holdout'])} |")
    lines += ["", "Files: `tables/cells.jsonl` (every planned cell, with typed missingness), `reports/analysis.json`, "
              "`reports/contracts.json`, `reports/pack.json`. `publication_manifest.json` digests every file and binds "
              "the bundle to its source receipts.", "",
              "No kernel trajectory grain: for 1,800 cells it is 145 MB, 22 times the largest grain in `evidence/`, "
              "because every outside-demand seat and landlord action is a row (85% of rows; seat 0 is 12%). The "
              "sealed attempt directories it would be built from stay in the run roots, bound here by receipt digest; "
              "`aeread publish-trajectories` adds it to a copy of this bundle when they are at hand.", ""]
    return "\n".join(lines)


_SETUPS: dict[str, Any] = {}


def replay_setup(receipt: Mapping[str, Any]) -> Any:
    """``aeread verify-replay --setup aeread_families.housing.price_publication:replay_setup``.

    Returns the sealed setup whose plan the durable receipt names: one of the six v14 plans
    (three identities, two landlord arms), each built once from its committed contract.
    """
    if not _SETUPS:
        for campaign_id in (k for k in price_campaign.IDENTITIES if "confirmatory_v14" in k):
            contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json"))
            for arm in contract["arms"]:
                setup = price_campaign.build_setup(contract, arm, live=True)
                _SETUPS[setup.plan.run_plan_id] = setup
    setup = _SETUPS.get(receipt.get("run_plan_id"))
    if setup is None:
        raise ValueError(f"no v14 plan has run_plan_id {receipt.get('run_plan_id')!r}")
    return setup


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contract", type=Path, action="append", required=True)
    parser.add_argument("--run-root", type=Path, action="append", required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if len(args.contract) != len(args.run_root):
        parser.error("give one --run-root per --contract, in the same order")
    manifest = publish(args.contract, args.run_root, args.publication_root)
    print(json.dumps({"publication_id": manifest["publication_id"], "manifest_sha256": manifest["manifest_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
