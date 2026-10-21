"""v15 addendum B's declared rows: Sol 6.1 (Codex) and Opus 5.5 (Claude Code), reported beside v15 (committed before
any of its cells).

    PYTHONPATH=src python tools/housing/price_v15_addendum_b_analysis.py CLI_RUNS V15_RUNS OUT.json

``CLI_RUNS`` holds the two addendum-B identities' run roots and ``V15_RUNS`` v15's and addendum A's
(``runs/housing_v15``). As ``price_v15_addendum_b_cli_plan.md`` (Section 4) declares, all descriptive and outside v15's
Holm family: per subject, the main-pack mean as a share of the best-informed tenant's, the same within each stratum and
on the holdout; B (subject − ``inspect_then_sign``, read at 1 − 0.05/3 as addendum A reads B3); G and R as v15's; the
subject against Gemini, Luna and GLM, and Sol against Opus, with 95% intervals. Everything is computed with
``price_v15_analysis``'s own functions on seat 0's measure-v2 primary, the mean of the two landlord arms per world.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import price_v15_analysis as a  # noqa: E402

SUBJECTS = {"sol": "housing_lemons_price_v15_cli_codex_sol61", "opus": "housing_lemons_price_v15_cli_claude_opus55"}
OTHERS = {**a.MODELS, "glm": "housing_lemons_price_v15_glm53_flash_nearai"}


def _mean(values) -> float:
    xs = [x for x in values if x is not None]
    return round(statistics.fmean(xs), 2) if xs else None


def analyze(cli_runs: Path, v15_runs: Path) -> dict:
    ctrl, stratum = a.controls(), a.strata()
    main = sorted({w for (s, w, _x) in ctrl if s == "main"})
    holdout = sorted({w for (s, w, _x) in ctrl if s == "holdout"})
    primary = lambda c, _k: c["primary"]  # noqa: E731
    everything = {k: None for k in ctrl}
    ref = lambda name: (lambda _c, k: ctrl[k][name])  # noqa: E731
    best_main = a.world_values(everything, "main", main, ref("best_informed"))
    best_hold = a.world_values(everything, "holdout", holdout, ref("best_informed"))
    others = {m: a.world_values(a.cells(v15_runs, ident), "main", main, primary) for m, ident in OTHERS.items()}
    out = {"addendum": "docs/families/housing/price_v15_addendum_b_cli_plan.md", "subjects": {}}
    values = {}
    for name, ident in SUBJECTS.items():
        cells = a.cells(cli_runs, ident)
        mismatches = [key for key, cell in cells.items() for r, rkey in a.REFERENCE_KEYS.items()
                      if abs(cell["references"][rkey] - ctrl[key][r]) > 1e-6]
        if mismatches:
            raise SystemExit(f"{ident}: receipt references differ from the published controls: {mismatches[:5]}")
        v = a.world_values(cells, "main", main, primary)
        hv = a.world_values(cells, "holdout", holdout, primary)
        values[name] = v
        b = a.contrast(f"B: {name} - inspect_then_sign", v, a.world_values(everything, "main", main, ref("inspect_then_sign")),
                       strict=0.05 / 3)
        b["beats_baseline"] = (not b["inconclusive_by_dropout"]) and b["ci_0.983"][0] > 0
        strata = {}
        for s in ("favourite_is_lemon", "favourite_is_sound"):
            ws = [w for w in main if stratum.get(w) == s]
            m, bi = _mean(v[w] for w in ws), _mean(best_main[w] for w in ws)
            strata[s] = {"mean": m, "best_informed": bi, "share": round(m / bi, 4) if m is not None else None}
        mean_main, mean_hold = _mean(v.values()), _mean(hv.values())
        out["subjects"][name] = {
            "identity": ident, "mean_main": mean_main,
            "share_of_best_informed_main": round(mean_main / _mean(best_main.values()), 4) if mean_main is not None else None,
            "strata": strata, "mean_holdout": mean_hold,
            "share_of_best_informed_holdout": round(mean_hold / _mean(best_hold.values()), 4) if mean_hold is not None else None,
            "B": b,
            "G": a.contrast(f"G: {name} - best_informed", v, best_main),
            "R": a.contrast(f"R: {name} - inspect_lowball", v, a.world_values(everything, "main", main, ref("inspect_lowball")),
                            strict=0.05 / 3),
            "pairs": [a.contrast(f"{name} - {m}", v, others[m]) for m in OTHERS],
            "cells_completed": len(cells), "cost_usd": round(sum(c["cost"] for c in cells.values()), 4),
            "blind_signings": sum(int(c["metrics"]["blind_signings"]) for c in cells.values()),
            "invalid_actions": sum(int(c["metrics"]["invalid_actions"]) for c in cells.values()),
        }
    out["sol_minus_opus"] = a.contrast("Sol - Opus", values["sol"], values["opus"])
    out["best_informed_main"] = _mean(best_main.values())
    out["best_informed_holdout"] = _mean(best_hold.values())
    return out


if __name__ == "__main__":
    result = analyze(Path(sys.argv[1]), Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps({n: {k: s[k] for k in ("share_of_best_informed_main", "mean_main", "cells_completed")}
                      for n, s in result["subjects"].items()}, indent=1))
