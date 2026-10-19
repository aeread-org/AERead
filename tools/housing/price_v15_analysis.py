"""The Housing v15 confirmatory's declared analysis (plan Section 5, amendments 2 and 5), written before any result.

    PYTHONPATH=src python tools/housing/price_v15_analysis.py runs/housing_v15 OUT.json

Every model value is seat 0's primary (measure v2, ``housing_seat0_net_v2_leaf``) read from the sealed receipt each
cell record names; the controls (``inspect_then_sign``, ``inspect_lowball``, the best-informed tenant, the ceiling)
come from the pack's published table (``evidence/housing/housing_lemons_price_pack_v2/tables/controls.jsonl``) and
are checked against each receipt's own reference values. A world's value is the mean of its two landlord arms; a
world counts in a contrast when every cell it needs completed. Main pack (260 worlds) unless stated; the holdout (40
worlds, outside demand at 0.3) is reported apart and never pooled.

- **P** (amendment 5): Gemini − Luna, paired t, α = 0.05; found when p < 0.05; "larger than $50" only when the 95%
  interval clears $50, and only if the A/A arm calibrates the band.
- **B1, B2:** each model − ``inspect_then_sign``; Holm over the two; a model beats the baseline when the lower end of
  its interval at 1 − 0.05/2 is above $0 (Section 5's rule at the two remaining models).
- **G1, G2:** each model − the best-informed tenant; intervals, no test.
- **R1, R2** (amendment 2): each model − ``inspect_lowball``; 95% intervals and intervals at 1 − 0.05/2, no test.
- **A/A** (amendments 4 and 5): Luna − its twin on the main pack; the $50 band is calibrated when the 95% interval of
  the A/A difference lies inside ±$50.
- A contrast that loses more than 10% of its worlds is inconclusive.
- Beside them, without a claim: both strata, the holdout, realized net, blind signings, seat 0's invalid actions, cost.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
CONTROLS = ROOT / "evidence/housing/housing_lemons_price_pack_v2/tables/controls.jsonl"
SCAN = ROOT / "evidence/housing/housing_lemons_price_pack_v2/tables/scan.jsonl"
MODELS = {"gemini": "housing_lemons_price_v15_gemini38_flash", "luna": "housing_lemons_price_v15_gpt6_luna"}
TWIN = "housing_lemons_price_v15_gpt6_luna_aa"
LEAF = "housing_seat0_net_v2_leaf"
ARMS = ("true_cost", "pooled")
BAND, DROPOUT = 50.0, 0.10
REFERENCE_KEYS = {"inspect_then_sign": "comparison_baseline", "best_informed": "best_informed"}


def cells(run_root: Path, identity: str) -> dict[tuple[str, int, str], dict]:
    """(stream, world, arm) -> the completed cell's primary, metrics and reference values, from its receipt."""
    live = run_root / identity / "live"
    out = {}
    for path in sorted(live.glob("*world_*.json")):
        row = json.loads(path.read_text())
        if row["status"] != "completed":
            continue
        receipt_path = next((live / path.name.replace(".json", "_evidence")).rglob("evaluation_receipt.json"))
        receipt = json.loads(receipt_path.read_text())
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise SystemExit(f"{path}: the cell record names another receipt")
        (score,) = [s for s in receipt["scores"] if s["leaf"]["leaf_id"] == LEAF]
        key = (row.get("stream", "main"), row["world_seed"], row["arm"])
        if key in out or row["replicate_index"] != 0:
            raise SystemExit(f"{path}: the confirmatory has one cell per world and arm")
        out[key] = {
            "primary": float(score["primary"]["value"]),
            "metrics": {k: v["value"] for k, v in score["metrics"].items()},
            "references": {k: v["value"] for k, v in score["reference_values"].items()},
            "cost": float(row.get("cost_usd") or 0.0),
        }
    return out


def controls() -> dict[tuple[str, int, str], dict]:
    out = {}
    for line in CONTROLS.read_text().splitlines():
        r = json.loads(line)
        out[(r["stream"], r["world_seed"], r["arm"])] = {k: float(r[k]["primary_v2"]) for k in
                                                          ("inspect_then_sign", "inspect_lowball", "best_informed")} | {
            "ceiling": float(r["ceiling"])}
    return out


def strata() -> dict[int, str]:
    return {r["world_seed"]: r["stratum"] for r in map(json.loads, SCAN.read_text().splitlines()) if r["status"] == "admitted"}


def world_values(model_cells: dict, stream: str, worlds: list[int], value) -> dict[int, float | None]:
    out = {}
    for w in worlds:
        parts = [value(model_cells[(stream, w, a)], (stream, w, a)) if (stream, w, a) in model_cells else None for a in ARMS]
        out[w] = None if any(p is None for p in parts) else statistics.fmean(parts)
    return out


def interval(values: list[float], alpha: float) -> list[float]:
    n, m = len(values), statistics.fmean(values)
    h = stats.t.ppf(1 - alpha / 2, n - 1) * statistics.stdev(values) / math.sqrt(n)
    return [round(m - h, 2), round(m + h, 2)]


def contrast(name: str, a: dict[int, float | None], b: dict[int, float | None], *, strict: float | None = None) -> dict:
    worlds = sorted(a)
    diffs = {w: a[w] - b[w] for w in worlds if a[w] is not None and b[w] is not None}
    xs = list(diffs.values())
    out = {"contrast": name, "worlds_base": len(worlds), "worlds_used": len(xs),
           "dropout_share": round(1 - len(xs) / len(worlds), 4), "mean": round(statistics.fmean(xs), 2),
           "ci_0.95": interval(xs, 0.05), "p": float(stats.ttest_1samp(xs, 0.0).pvalue)}
    if strict is not None:
        out[f"ci_{1 - strict:.3f}"] = interval(xs, strict)
    out["inconclusive_by_dropout"] = out["dropout_share"] > DROPOUT
    return out


def holm(results: list[dict]) -> None:
    order = sorted(range(len(results)), key=lambda i: results[i]["p"])
    running = 0.0
    for step, i in enumerate(order):
        running = max(running, min(1.0, (len(results) - step) * results[i]["p"]))
        results[i]["p_holm"] = running


def analyze(run_root: Path) -> dict:
    ctrl, stratum = controls(), strata()
    data = {k: cells(run_root, v) for k, v in MODELS.items()}
    twin = cells(run_root, TWIN)
    mismatches = [(m, key) for m, c in data.items() for key, cell in c.items()
                  for ref, rkey in REFERENCE_KEYS.items() if abs(cell["references"][rkey] - ctrl[key][ref]) > 1e-6]
    if mismatches:
        raise SystemExit(f"receipt references differ from the published controls: {mismatches[:5]}")
    main = sorted(w for (s, w, _a) in ctrl if s == "main")
    main = sorted(set(main))
    holdout = sorted({w for (s, w, _a) in ctrl if s == "holdout"})
    primary = lambda c, _k: c["primary"]  # noqa: E731
    ref = lambda name: (lambda _c, k: ctrl[k][name])  # noqa: E731
    v = {m: world_values(data[m], "main", main, primary) for m in MODELS}
    controls_by = {name: world_values({k: None for k in ctrl}, "main", main, ref(name)) for name in
                   ("inspect_then_sign", "inspect_lowball", "best_informed", "ceiling")}
    p = contrast("P: Gemini - Luna", v["gemini"], v["luna"])
    b = [contrast(f"B: {m} - inspect_then_sign", v[m], controls_by["inspect_then_sign"], strict=0.05 / 2) for m in MODELS]
    holm(b)
    for r in b:
        r["beats_baseline"] = (not r["inconclusive_by_dropout"]) and r["ci_0.975"][0] > 0
    g = [contrast(f"G: {m} - best_informed", v[m], controls_by["best_informed"]) for m in MODELS]
    rr = [contrast(f"R: {m} - inspect_lowball", v[m], controls_by["inspect_lowball"], strict=0.05 / 2) for m in MODELS]
    aa = contrast("A/A: Luna - Luna twin", v["luna"], world_values(twin, "main", main, primary))
    calibrated = (not aa["inconclusive_by_dropout"]) and -BAND < aa["ci_0.95"][0] and aa["ci_0.95"][1] < BAND
    p["found"] = (not p["inconclusive_by_dropout"]) and p["p"] < 0.05
    clears = p["ci_0.95"][0] > BAND or p["ci_0.95"][1] < -BAND
    p["larger_than_band"] = bool(p["found"] and clears and calibrated)
    p["band_calibrated_by_aa"] = calibrated
    secondary = {
        "means_main": {m: round(statistics.fmean(x for x in v[m].values() if x is not None), 2) for m in MODELS}
        | {name: round(statistics.fmean(controls_by[name].values()), 2) for name in controls_by},
        "strata": {s: {m: round(statistics.fmean(v[m][w] for w in main if stratum.get(w) == s and v[m][w] is not None), 2)
                       for m in MODELS} for s in ("favourite_is_lemon", "favourite_is_sound")},
        "holdout": {**{m: round(statistics.fmean(x for x in world_values(data[m], "holdout", holdout, primary).values()
                                                 if x is not None), 2) for m in MODELS},
                    "best_informed": round(statistics.fmean(world_values({k: None for k in ctrl}, "holdout", holdout, ref("best_informed")).values()), 2),
                    "pair": contrast("holdout P: Gemini - Luna", world_values(data["gemini"], "holdout", holdout, primary),
                                     world_values(data["luna"], "holdout", holdout, primary))},
        "realized_net_main": {m: round(statistics.fmean(c["metrics"]["seat0_net_realized"] for (s, _w, _a), c in data[m].items()
                                                        if s == "main"), 2) for m in MODELS},
        "blind_signings": {m: sum(int(c["metrics"]["blind_signings"]) for c in data[m].values()) for m in MODELS},
        "invalid_actions": {m: sum(int(c["metrics"]["invalid_actions"]) for c in data[m].values()) for m in MODELS},
        "cells_completed": {**{m: len(data[m]) for m in MODELS}, "luna_twin": len(twin)},
        "cost_usd": {**{m: round(sum(c["cost"] for c in data[m].values()), 4) for m in MODELS},
                     "luna_twin": round(sum(c["cost"] for c in twin.values()), 4)},
    }
    return {"plan": "docs/families/housing/price_confirmatory_v15_plan.md (Section 5, amendments 2 and 5)",
            "measure": "seat 0 net, measure v2 (housing_price_reply_conditioned_v2), mean of the two landlord arms",
            "P": p, "B": b, "G": g, "R": rr, "AA": aa, "secondary": secondary}


if __name__ == "__main__":
    result = analyze(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("P", "AA")}, indent=1))
