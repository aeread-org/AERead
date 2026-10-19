"""v15 addendum A's declared rows: GLM 5.3 Flash on Near AI fp8, reported beside v15 (committed before its results).

    PYTHONPATH=src python tools/housing/price_v15_addendum_analysis.py runs/housing_v15 OUT.json

As addendum A (plan) declares, outside v15's Holm family and never changing v15's results: B3, GLM −
``inspect_then_sign``, read by Section 5's rule with three models carrying a B row (GLM beats the baseline when the
lower end of its interval at 1 − 0.05/3 is above $0); G3 and R3 as v15's G and R rows; GLM − Gemini and GLM − Luna with
95% intervals, descriptive; the holdout beside. Everything is computed with ``price_v15_analysis``'s own functions on
the main pack, seat 0's measure-v2 primary, the mean of the two landlord arms per world.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import price_v15_analysis as a  # noqa: E402

GLM = "housing_lemons_price_v15_glm53_flash_nearai"


def analyze(run_root: Path) -> dict:
    ctrl = a.controls()
    main = sorted({w for (s, w, _x) in ctrl if s == "main"})
    holdout = sorted({w for (s, w, _x) in ctrl if s == "holdout"})
    glm = a.cells(run_root, GLM)
    mismatches = [key for key, cell in glm.items() for ref, rkey in a.REFERENCE_KEYS.items()
                  if abs(cell["references"][rkey] - ctrl[key][ref]) > 1e-6]
    if mismatches:
        raise SystemExit(f"receipt references differ from the published controls: {mismatches[:5]}")
    primary = lambda c, _k: c["primary"]  # noqa: E731
    everything = {k: None for k in ctrl}
    ref = lambda name: (lambda _c, k: ctrl[k][name])  # noqa: E731
    v = a.world_values(glm, "main", main, primary)
    others = {m: a.world_values(a.cells(run_root, ident), "main", main, primary) for m, ident in a.MODELS.items()}
    b3 = a.contrast("B3: glm - inspect_then_sign", v, a.world_values(everything, "main", main, ref("inspect_then_sign")),
                    strict=0.05 / 3)
    b3["beats_baseline"] = (not b3["inconclusive_by_dropout"]) and b3["ci_0.983"][0] > 0
    hv = a.world_values(glm, "holdout", holdout, primary)
    return {
        "addendum": "docs/families/housing/price_confirmatory_v15_plan.md, Addendum A and its amendments",
        "identity": GLM, "B3": b3,
        "G3": a.contrast("G3: glm - best_informed", v, a.world_values(everything, "main", main, ref("best_informed"))),
        "R3": a.contrast("R3: glm - inspect_lowball", v, a.world_values(everything, "main", main, ref("inspect_lowball")),
                         strict=0.05 / 3),
        "pairs": [a.contrast("GLM - Gemini", v, others["gemini"]), a.contrast("GLM - Luna", v, others["luna"])],
        "glm_mean_main": round(statistics.fmean(x for x in v.values() if x is not None), 2),
        "glm_mean_holdout": round(statistics.fmean(x for x in hv.values() if x is not None), 2),
        "cells_completed": len(glm), "cost_usd": round(sum(c["cost"] for c in glm.values()), 4),
        "blind_signings": sum(int(c["metrics"]["blind_signings"]) for c in glm.values()),
        "invalid_actions": sum(int(c["metrics"]["invalid_actions"]) for c in glm.values()),
    }


if __name__ == "__main__":
    result = analyze(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("B3", "glm_mean_main")}, indent=1))
