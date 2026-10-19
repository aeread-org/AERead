"""The v15 sizing record from the variance pilot (plan Section 8, amendment 5): worlds needed for the Gemini - Luna pair.

    PYTHONPATH=src python tools/housing/price_v15_sizing.py runs/housing_v15 docs/families/housing/price_v15_sizing_record.json

Reads each pilot cell's sealed receipt (its seat-0 primary leaf, measure v2) through the cell record that names it,
averages the two landlord arms per world and replicate, and splits the pair's per-replicate difference into world and
replicate variance, as the data-center plan's sizing does. The sizing functions are ``aeread.design.sizing`` at
159cba3c, copied byte for byte (``sizing_159cba3c.py``, digest checked). Settings: power 0.8, alpha 0.05 (one pair
after amendment 5), 5% attrition, the $50 effect, one replicate in the confirmatory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIZING_SHA256 = "6a3f0794d336b92d6d5566159885d8b1dd03ff284e21d6478b2d8aba22d6a41f"
PAIR = ("gemini38_flash", "gpt6_luna")
EFFECT, POWER, ALPHA, ATTRITION, CAP = 50.0, 0.8, 0.05, 0.05, 260


def sizing_module():
    path = HERE / "sizing_159cba3c.py"
    if hashlib.sha256(path.read_bytes()).hexdigest() != SIZING_SHA256:
        raise SystemExit("the sizing copy is not 159cba3c's")
    spec = importlib.util.spec_from_file_location("sizing_159cba3c", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def primaries(run_root: Path, model: str) -> dict[tuple[int, int], float]:
    """(world, replicate) -> seat 0's primary, mean of the two arms; only worlds and replicates with both arms."""
    live = run_root / f"housing_lemons_price_v15_pilot_{model}" / "live"
    by: dict[tuple[int, int], dict[str, float]] = {}
    for path in sorted(live.glob("world_*.json")):
        row = json.loads(path.read_text())
        if row["status"] != "completed":
            continue
        receipt_path = next((live / path.name.replace(".json", "_evidence")).rglob("evaluation_receipt.json"))
        receipt = json.loads(receipt_path.read_text())
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise SystemExit(f"{path}: the cell record names another receipt")
        (score,) = [s for s in receipt["scores"] if s["leaf"]["leaf_id"] == "housing_seat0_net_v2_leaf"]
        by.setdefault((row["world_seed"], row["replicate_index"]), {})[row["arm"]] = float(score["primary"]["value"])
    return {k: statistics.fmean(v.values()) for k, v in by.items() if len(v) == 2}


def record(run_root: Path) -> dict:
    sz = sizing_module()
    a, b = (primaries(run_root, m) for m in PAIR)
    worlds = sorted({w for w, _ in a} & {w for w, _ in b})
    diffs = {w: [a[(w, r)] - b[(w, r)] for r in (0, 1) if (w, r) in a and (w, r) in b] for w in worlds}
    complete = {w: d for w, d in diffs.items() if len(d) == 2}
    var_play = statistics.fmean(statistics.variance(d) for d in complete.values())
    var_means = statistics.variance([statistics.fmean(d) for d in complete.values()])
    var_world = max(0.0, var_means - var_play / 2)
    sd_one = sz.sd_of_differences(var_world, var_play, 1)
    needed = sz.worlds_needed(sd_one, EFFECT, power=POWER, alpha=ALPHA, attrition=ATTRITION)
    return {"pair": f"{PAIR[0]} - {PAIR[1]}", "pilot_worlds": len(complete), "var_world": round(var_world, 2),
            "var_play": round(var_play, 2), "sd_one_replicate": round(sd_one, 2), "mean_difference_pilot": round(
                statistics.fmean(statistics.fmean(d) for d in complete.values()), 2),
            "effect": EFFECT, "power": POWER, "alpha": ALPHA, "attrition": ATTRITION,
            "worlds_needed": needed, "cap": CAP, "within_cap": needed <= CAP,
            "detectable_at_cap": round(sz.smallest_detectable_effect(sd_one, round(CAP * (1 - ATTRITION)), power=POWER, alpha=ALPHA), 2),
            "sizing_module_sha256": SIZING_SHA256}


if __name__ == "__main__":
    out = record(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps(out, indent=1, sort_keys=True))
