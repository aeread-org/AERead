"""The agreement confirmatory's declared analysis: the pilot's sizing record, then P1, P2 and P3 and the secondary measures.

    PYTHONPATH=src python tools/cli_subjects/agreement_confirmatory_analysis.py sizing  runs/<pilot> OUT.json
    PYTHONPATH=src python tools/cli_subjects/agreement_confirmatory_analysis.py analyze --h runs/<H> --f runs/<F> [--a runs/<A>] OUT.json

Everything here is declared in ``docs/families/datacenter/agreement_confirmatory_plan.md`` ("Variance pilot",
"Sizing", "Primary contrasts", "Exclusions and missingness", "Analysis"); this module only computes it. Every number
is read from the sealed receipts' score leaves (``client_surplus``, ``integrator_surplus``, ``client_ir_violation``,
``episode_valid`` and the loss leaves), which the kernel's replay recomputes from sealed events; the cell record's copy
of the grade is checked against them and not used.

- Earnings: what a model's seat makes over its own outside option, $k, at both sides' true costs, redline fees
  deducted (the seat's ``*_surplus`` leaf). A negotiation counts when its receipt is ``ok`` and ``episode_valid`` is 1;
  anything else is missing for its pairing.
- P1, head to head, per deal world: the mean over the two seats of Codex's earnings less Opus's in that seat, from the
  two seat orders. P2, against the firm population: the same from the four negotiations against the publicly drawn
  style. Paired t on the world values, two-sided. P3: over all 60 worlds, head to head, whether the client signed
  below its walk-away point, Opus as client against Codex as client, exact McNemar on the discordant worlds.
- Holm across P1, P2, P3 at a familywise 0.05; 95% intervals and intervals at 1 - 0.05/3; a world bootstrap (10,000
  resamples, seed 20261013) as a check. A contrast that loses more than 10% of its worlds is inconclusive whatever its
  p-value. Missingness bounds set each missing negotiation's earnings to the lowest and highest observed in its pairing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import stats

from aeread.shared_runner.task.receipts import read_evaluation_receipt
from aeread_families.datacenter_development import agreement_admitted_pack as aap
from aeread_families.datacenter_development import agreement_pack as ap

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC = "drawn_public_v1"
MODELS = ("codex", "claude")  # Codex Sol 6.1, Claude Code Opus 5.5
ALPHA, FAMILY = 0.05, 3
EFFECTS = {"P1": 100.0, "P2": 50.0, "P3": 0.16}
DROPOUT = 0.10
BOOT, BOOT_SEED = 10_000, 20261013
#: The plan's sizing inputs for P2 ("Sizing"): power 0.8, the first Holm step, 7% attrition.
POWER, ATTRITION = 0.8, 0.07
LEAVES = ("episode_valid", "client_surplus", "integrator_surplus", "client_ir_violation", "integrator_ir_violation", "joint_value_lost",
          "allocation_loss", "no_deal_loss", "delay_loss", "best_agreement_signed", "contract_signed")


def load(run_dir: Path) -> dict[str, Any]:
    """The campaign's plan and every cell, with each sealed receipt's leaf values."""
    plan = json.loads((run_dir / "campaign_plan.json").read_text())
    cells = []
    for path in sorted((run_dir / "cells").glob("*.json")):
        r = json.loads(path.read_text())
        r["world"] = r["case_id"].rsplit(".", 1)[-1]
        r["leaves"] = None
        if r.get("receipt_sha256"):
            receipt = read_evaluation_receipt(next((run_dir / "evidence" / r["cell_key"]).rglob("evaluation_receipt.json")))
            if receipt["receipt_sha256"] != r["receipt_sha256"]:
                raise SystemExit(f"{r['cell_key']}: the cell record names another receipt")
            if receipt["status"] == "ok":
                r["leaves"] = {s["leaf"]["leaf_id"]: float(s["primary"]["value"]) for s in receipt["scores"]}
                g = r.get("grade") or {}
                for leaf in ("client_surplus", "integrator_surplus"):
                    if abs(r["leaves"][leaf] - float(g[leaf])) > 1e-9:
                        raise SystemExit(f"{r['cell_key']}: the record's {leaf} differs from the receipt's")
        r["valid"] = bool(r["leaves"] and r["leaves"]["episode_valid"] == 1.0 and r["status"] == "ok")
        cells.append(r)
    expected = sum(len(e["cells"]) for e in plan["plans"])
    if len(cells) != expected:
        raise SystemExit(f"{run_dir}: {len(cells)} cell records for {expected} planned cells")
    return {"plan": plan, "cells": cells}


def index(campaign: Mapping[str, Any]) -> dict[tuple[str, str, int], dict[str, Any]]:
    return {(c["pairing"], c["world"], c["replicate_index"]): c for c in campaign["cells"]}


def h_pairings() -> dict[str, str]:
    return {"codex_int": "codex_integrator__claude_client", "claude_int": "claude_integrator__codex_client"}


def script_pairings(style: str) -> dict[tuple[str, str], str]:
    """(model, seat) -> the pairing in which that model plays that seat against the scripted style."""
    out = {}
    for m in MODELS:
        out[(m, "integrator")] = f"{m}_integrator__negotiator_{style}_client"
        out[(m, "client")] = f"negotiator_{style}_integrator__{m}_client"
    return out


def earnings(cell: Mapping[str, Any] | None, seat: str) -> float | None:
    return cell["leaves"][f"{seat}_surplus"] if cell is not None and cell["valid"] else None


def _entries_h(cells: Mapping, w: str, r: int = 0) -> dict[tuple[str, str], tuple[str, float | None]]:
    """(model, seat) -> (pairing, earnings) head to head."""
    p = h_pairings()
    ci, oi = cells.get((p["codex_int"], w, r)), cells.get((p["claude_int"], w, r))
    return {("codex", "integrator"): (p["codex_int"], earnings(ci, "integrator")), ("claude", "client"): (p["codex_int"], earnings(ci, "client")),
            ("claude", "integrator"): (p["claude_int"], earnings(oi, "integrator")), ("codex", "client"): (p["claude_int"], earnings(oi, "client"))}


def _entries_s(cells: Mapping, w: str, style: str, r: int = 0) -> dict[tuple[str, str], tuple[str, float | None]]:
    return {(m, seat): (pairing, earnings(cells.get((pairing, w, r)), seat)) for (m, seat), pairing in script_pairings(style).items()}


def world_value(entries: Mapping[tuple[str, str], tuple[str, float | None]]) -> float | None:
    """Mean over the two seats of Codex's earnings less Claude's; None if any negotiation it needs is missing."""
    vals = {k: v for k, (_, v) in entries.items()}
    if any(v is None for v in vals.values()):
        return None
    return ((vals[("codex", "integrator")] - vals[("claude", "integrator")]) + (vals[("codex", "client")] - vals[("claude", "client")])) / 2.0


def _pairing_range(cells: Mapping, pairing: str, seat: str) -> tuple[float, float]:
    xs = [c["leaves"][f"{seat}_surplus"] for (p, _, _), c in cells.items() if p == pairing and c["valid"]]
    return (min(xs), max(xs)) if xs else (0.0, 0.0)


def _bounded(entries, cells, low_for_codex: bool) -> float:
    """The world value with each missing earnings set to its pairing's lowest or highest, against Codex or for it."""
    filled = {}
    for (m, seat), (pairing, v) in entries.items():
        if v is None:
            lo, hi = _pairing_range(cells, pairing, seat)
            v = (lo if m == "codex" else hi) if low_for_codex else (hi if m == "codex" else lo)
        filled[(m, seat)] = (pairing, v)
    return world_value(filled)


def t_summary(values: Sequence[float], alphas: Sequence[float] = (0.05, ALPHA / FAMILY)) -> dict[str, Any]:
    x = np.asarray(values, dtype=float)
    n = len(x)
    mean, sd = float(x.mean()), float(x.std(ddof=1)) if n > 1 else float("nan")
    se = sd / math.sqrt(n)
    t = mean / se if se > 0 else float("inf") * (1 if mean > 0 else -1 if mean < 0 else 0)
    p = float(2 * stats.t.sf(abs(t), n - 1)) if se > 0 else (0.0 if mean != 0 else 1.0)
    out = {"n": n, "mean": round(mean, 3), "sd": round(sd, 3), "p": p}
    for a in alphas:
        h = float(stats.t.ppf(1 - a / 2, n - 1)) * se
        out[f"ci_{1 - a:.4f}"] = [round(mean - h, 3), round(mean + h, 3)]
    rng = np.random.default_rng(BOOT_SEED)
    boots = x[rng.integers(0, n, size=(BOOT, n))].mean(axis=1)
    out["bootstrap_95"] = [round(float(np.quantile(boots, 0.025)), 3), round(float(np.quantile(boots, 0.975)), 3)]
    return out


def paired_contrast(name: str, entries_by_world: Mapping[str, Mapping], cells: Mapping, base: int) -> dict[str, Any]:
    values = {w: world_value(e) for w, e in entries_by_world.items()}
    used = {w: v for w, v in values.items() if v is not None}
    dropped = sorted(w for w, v in values.items() if v is None)
    out = {"contrast": name, "worlds_base": base, "worlds_used": len(used), "worlds_dropped": dropped,
           "dropout_share": round(1 - len(used) / base, 4), **t_summary(list(used.values())), "minimum_effect": EFFECTS[name]}
    lo = [_bounded(e, cells, True) for e in entries_by_world.values()]
    hi = [_bounded(e, cells, False) for e in entries_by_world.values()]
    out["missingness_bounds_mean"] = [round(statistics.fmean(lo), 3), round(statistics.fmean(hi), 3)]
    out["world_values"] = {w: round(v, 3) for w, v in sorted(used.items())}
    return out


def mcnemar(h_cells: Mapping, worlds: Sequence[str]) -> dict[str, Any]:
    p = h_pairings()
    rows, dropped = [], []
    for w in worlds:
        opus_client, codex_client = h_cells.get((p["codex_int"], w, 0)), h_cells.get((p["claude_int"], w, 0))
        if not (opus_client and opus_client["valid"] and codex_client and codex_client["valid"]):
            dropped.append(w)
            continue
        rows.append((int(opus_client["leaves"]["client_ir_violation"]), int(codex_client["leaves"]["client_ir_violation"])))
    b = sum(1 for o, c in rows if o and not c)
    c = sum(1 for o, cc in rows if cc and not o)
    pval = float(stats.binomtest(b, b + c, 0.5).pvalue) if b + c else 1.0
    n = len(rows)
    return {"contrast": "P3", "worlds_base": len(worlds), "worlds_used": n, "worlds_dropped": dropped, "dropout_share": round(1 - n / len(worlds), 4),
            "opus_below_walk_away": sum(o for o, _ in rows), "codex_below_walk_away": sum(cc for _, cc in rows),
            "discordant_opus_only": b, "discordant_codex_only": c, "difference_in_rate": round((b - c) / n, 4) if n else None,
            "p": pval, "minimum_effect": EFFECTS["P3"], "bounds_if_missing_all_opus_or_all_codex": [b, b + len(dropped), c, c + len(dropped)]}


def holm(results: list[dict[str, Any]]) -> None:
    order = sorted(range(len(results)), key=lambda i: results[i]["p"])
    running = 0.0
    for step, i in enumerate(order):
        adj = min(1.0, (len(results) - step) * results[i]["p"])
        running = max(running, adj)
        results[i]["holm_step"] = step + 1
        results[i]["holm_alpha"] = ALPHA / (len(results) - step)
        results[i]["p_holm"] = running
    stop = False
    for i in order:
        stop = stop or results[i]["p_holm"] > ALPHA
        results[i]["rejected"] = not stop
    for r in results:
        r["inconclusive_by_dropout"] = r["dropout_share"] > DROPOUT


def reading(r: Mapping[str, Any]) -> str:
    if r["inconclusive_by_dropout"]:
        return "inconclusive: more than 10% of its worlds dropped out"
    if r["contrast"] == "P2":
        # the plan's two readings are not exclusive (DC-T-21): a gap can be claimed and be smaller than 50
        readings = []
        if r["rejected"]:
            readings.append("a gap against the firm population is claimed")
        if r[f"ci_{1 - ALPHA / FAMILY:.4f}"][1] < EFFECTS["P2"]:
            readings.append("no gap of 50 or more against a firm counterpart")
        return "; ".join(readings) or "inconclusive"
    return "rejects 0" if r["rejected"] else "does not reject 0"


def analyze(h_dir: Path, f_dir: Path, a_dir: Path | None) -> dict[str, Any]:
    manifest, _ = ap.load(aap.ADMITTED.pack)
    worlds = sorted(w["case_id"].rsplit(".", 1)[-1] for w in manifest["worlds"])
    meta = {w["case_id"].rsplit(".", 1)[-1]: w for w in manifest["worlds"]}
    deal = [w for w in worlds if meta[w]["available_surplus"] > 0]
    H, F = load(h_dir), load(f_dir)
    hc, fc = index(H), index(F)
    p1 = paired_contrast("P1", {w: _entries_h(hc, w) for w in deal}, hc, len(deal))
    p2 = paired_contrast("P2", {w: _entries_s(fc, w, PUBLIC) for w in deal}, fc, len(deal))
    p3 = mcnemar(hc, worlds)
    primary = [p1, p2, p3]
    holm(primary)
    for r in primary:
        r["reading"] = reading(r)
    out: dict[str, Any] = {"pack": aap.ADMITTED.pack, "deal_worlds": len(deal), "worlds": len(worlds), "primary": primary,
                           "campaigns": {"H": _campaign_meta(H, h_dir), "F": _campaign_meta(F, f_dir)}}
    secondary = {"H": secondary_of(H, meta), "F": secondary_of(F, meta)}
    # sensitivity: an invalid negotiation scored as the environment scores it
    out["invalid_negotiations"] = {k: [c["cell_key"] for c in camp["cells"] if c["leaves"] and not c["valid"]] for k, camp in (("H", H), ("F", F))}
    if a_dir is not None:
        A = load(a_dir)
        out["campaigns"]["A"] = _campaign_meta(A, a_dir)
        secondary["A"] = secondary_of(A, meta)
        ac = index(A)
        secondary["A"]["codex_less_claude_by_style"] = {
            style: paired_contrast("P2", {w: _entries_s(ac, w, style) for w in deal}, ac, len(deal)) | {"contrast": f"against {style}", "claim": "none"}
            for style in ("overreach", "price_only", "collapse")}
        out["invalid_negotiations"]["A"] = [c["cell_key"] for c in A["cells"] if c["leaves"] and not c["valid"]]
    out["secondary"] = secondary
    return out


def _campaign_meta(campaign: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    cells = campaign["cells"]
    log = [json.loads(line) for line in (run_dir / "run_log.jsonl").read_text().splitlines()] if (run_dir / "run_log.jsonl").exists() else []
    return {"campaign_id": campaign["plan"]["campaign_id"], "plan_sha256": campaign["plan"]["plan_sha256"], "cells": len(cells),
            "valid": sum(c["valid"] for c in cells), "status": dict(Counter(c["status"] for c in cells)),
            "missing_by_cause": dict(Counter((c.get("error") or c["status"]).split(":")[0] for c in cells if not c["valid"])),
            "missing": sorted(c["cell_key"] for c in cells if not c["valid"]),
            "list_price_usd": round(sum(float(c.get("cost_usd") or 0.0) for c in cells), 4),
            "wall_minutes": [x.get("wall_minutes") for x in log]}


def secondary_of(campaign: Mapping[str, Any], meta: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Per pairing, without a claim: joint value lost and its split, best agreement signed, deals in no-deal worlds,
    signatures below a walk-away point, the share of each model seat's redlines that move only the price, earnings by
    seat and by cell."""
    by_pairing: dict[str, Any] = {}
    for pairing, (integ, client) in campaign["plan"]["pairings"].items():
        cs = [c for c in campaign["cells"] if c["pairing"] == pairing and c["valid"]]
        deal = [c for c in cs if meta[c["world"]]["available_surplus"] > 0]
        nodeal = [c for c in cs if meta[c["world"]]["available_surplus"] <= 0]
        row: dict[str, Any] = {"valid": len(cs)}
        for leaf in ("joint_value_lost", "allocation_loss", "no_deal_loss", "delay_loss"):
            row[leaf] = round(statistics.fmean(c["leaves"][leaf] for c in cs), 2) if cs else None
        row["best_agreement_signed_in_deal_worlds"] = sum(int(c["leaves"]["best_agreement_signed"]) for c in deal)
        row["deal_worlds"] = len(deal)
        row["signed_in_no_deal_worlds"] = f"{sum(int(c['leaves']['contract_signed']) for c in nodeal)} of {len(nodeal)}"
        for seat, subject in (("integrator", integ), ("client", client)):
            if subject.startswith("scripted_"):
                continue
            e = [c["leaves"][f"{seat}_surplus"] for c in deal]
            row[f"{seat}_earnings_deal_worlds_mean"] = round(statistics.fmean(e), 2) if e else None
            row[f"{seat}_below_walk_away"] = sum(int(c["leaves"][f"{seat}_ir_violation"]) for c in cs)
            red = sum((c.get("grade") or {}).get("edits", {}).get(seat, {}).get("redlines", 0) for c in cs)
            po = sum((c.get("grade") or {}).get("edits", {}).get(seat, {}).get("price_only", 0) for c in cs)
            row[f"{seat}_redlines_price_only"] = f"{po} of {red}"
            by_cell: dict[str, list[float]] = {}
            for c in deal:
                by_cell.setdefault(meta[c["world"]]["cell"], []).append(c["leaves"][f"{seat}_surplus"])
            row[f"{seat}_earnings_by_cell"] = {k: round(statistics.fmean(v), 2) for k, v in sorted(by_cell.items())}
        by_pairing[pairing] = row
    return by_pairing


# ---------------------------------------------------------------------------
# The pilot and the sizing record.


def _sizing_module():
    """``aeread.design.sizing`` as committed at 159cba3c on codex/methods-design, run from a copy (the plan, "Sizing")."""
    path = Path(__file__).resolve().parent / "agreement_confirmatory_sizing_159cba3c.py"
    spec = importlib.util.spec_from_file_location("aeread_design_sizing_159cba3c", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, hashlib.sha256(path.read_bytes()).hexdigest()


def pilot_sizing(pilot_dir: Path) -> dict[str, Any]:
    """The P2 sizing record rewritten from the pilot: the seat-averaged paired SD of one play, from the variance of the
    paired difference between worlds and between the two plays of a world."""
    sizing, sizing_sha = _sizing_module()
    P = load(pilot_dir)
    pc = index(P)
    manifest, _ = ap.load(aap.PILOT.pack)
    meta = {w["case_id"].rsplit(".", 1)[-1]: w for w in manifest["worlds"]}
    deal = sorted(w for w, m in meta.items() if m["available_surplus"] > 0)
    d: dict[str, list[float]] = {}
    spread: dict[str, dict[str, Any]] = {}
    for w in deal:
        plays = [world_value(_entries_s(pc, w, PUBLIC, r)) for r in (0, 1)]
        if all(v is not None for v in plays):
            d[w] = plays
        spread[w] = {f"{m}_{seat}": [earnings(pc.get((pairing, w, r)), seat) for r in (0, 1)]
                     for (m, seat), pairing in script_pairings(PUBLIC).items()}
    x = np.asarray(list(d.values()))
    n = len(x)
    var_play = float(np.mean(np.var(x, axis=1, ddof=1)))  # within a world, between its two plays
    var_mean = float(np.var(x.mean(axis=1), ddof=1))  # between world means of two plays
    var_world = max(0.0, var_mean - var_play / 2)
    sd_one_play = sizing.sd_of_differences(var_world, var_play, plays=1)
    record = sizing.sizing_record(sd_of_differences=round(sd_one_play, 3), minimum_effect=EFFECTS["P2"], pilot_worlds=n,
                                  pilot_source=f"{P['plan']['campaign_id']} (plan {P['plan']['plan_sha256'][:12]}): arm F on "
                                               f"{aap.PILOT.pack}, two plays a world",
                                  power=POWER, alpha=ALPHA / FAMILY, attrition=ATTRITION)
    play_sd = {k: [abs(v[0] - v[1]) for v in vals.values() if None not in v] for k, vals in
               {k: {w: spread[w][k] for w in spread} for k in next(iter(spread.values()))}.items()}
    return {
        "pilot_pack": aap.PILOT.pack, "contrast": "P2", "deal_worlds_needed": record["worlds"],
        "deal_worlds_available": 42, "record": record, "sizing_module_sha256": sizing_sha,
        # the frozen arms pin this file's digest, so they pin the analysis that will read them
        "analysis_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "variance": {"worlds_complete": n, "worlds_deal": len(deal), "var_world": round(var_world, 3), "var_play": round(var_play, 3),
                     "sd_one_play": round(sd_one_play, 3), "sd_two_play_mean": round(math.sqrt(var_mean), 3),
                     "development_sd": 71.9},
        "within_world_spread": {"mean_absolute_difference_between_plays": {k: round(statistics.fmean(v), 2) if v else None for k, v in play_sd.items()},
                                "by_world": spread},
        "pilot_world_values": {w: [round(v, 3) for v in vals] for w, vals in sorted(d.items())},
        "pilot_campaign": _campaign_meta(P, pilot_dir),
        "detectable_at_42": round(sizing.smallest_detectable_effect(sd_one_play, 42, power=POWER, alpha=ALPHA / FAMILY), 2),
    }


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sizing")
    s.add_argument("pilot", type=Path)
    s.add_argument("out", type=Path)
    a = sub.add_parser("analyze")
    a.add_argument("--h", type=Path, required=True)
    a.add_argument("--f", type=Path, required=True)
    a.add_argument("--a", type=Path)
    a.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    result = pilot_sizing(args.pilot) if args.command == "sizing" else analyze(args.h, args.f, args.a)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k in ("deal_worlds_needed", "variance", "detectable_at_42", "primary")}, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
