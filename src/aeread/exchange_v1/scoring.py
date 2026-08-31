"""D15 scoring bridge for arena run dirs — the seam `submit._score_run` imports.

Scores one V1 arena run directory under the carve-out contract v2
(docs/design/2026-07-08_carveout_oracle_unsaturated.md), consistent with
`aeread.exchange_v1.aer_scorer` (the case-oracle scorer for bundle/procurement actions):

    score = W_real / denominator        (RAW — negatives preserved, may exceed 1)
    W_real      = final_net_welfare - initial_welfare   (net gain; coordination
                  costs are charged, so value destruction shows as score < 0)
    denominator = optimum_welfare - initial_welfare     (the W* gain)

- `score_clip = clamp01(score)` is a presentation companion only.
- A degenerate denominator (W* gain <= EPS) is flagged `degenerate_denominator`
  with no fabricated number. NOTE: the arena's own `welfare_ratio`
  (RunResult.final_welfare_ratio) clamps to [0,1] AND fabricates 1.0 on a
  degenerate optimum — the bridge deliberately ignores it and recomputes from
  the raw summary fields.
- Denominator tier: multi-agent arena W_bayes is a Bayesian-Nash fixed point
  (deferred, same reason as the bundle/procurement oracles), so the denominator
  degrades UPWARD to W* — `wstar_fallback`, labeled `skipped_with_reason`,
  never a silent zero (spec §1b). The reported score is a conservative lower
  bound on true efficiency.

Aggregation across cases happens in `exchange_v1_submit` (pooled ratio of sums
per denominator tier — the v2 aggregate); this module scores ONE run dir.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EPS = 1e-9

DENOM_TIER_WSTAR = "wstar_fallback"
_FALLBACK_REASON = (
    "multi-agent arena W_bayes is a Bayesian-Nash fixed point; wstar_fallback per "
    "oracle_carveout_spec §1b (mc_wbayes tier deferred)"
)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def score_run(run_dir: str | Path) -> dict[str, Any]:
    """Score one arena run dir. Returns the D15 result row (no 'tier' key — the
    submission harness owns the scorer-tier label)."""
    run_dir = Path(run_dir)
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"no summary.json in {run_dir}")
    summary = json.loads(summary_path.read_text())
    try:
        initial = float(summary["initial_welfare"])
        optimum = float(summary["optimum_welfare"])
    except KeyError as err:
        raise ValueError(f"{summary_path}: summary missing welfare field {err}") from err
    if summary.get("final_net_welfare") is not None:
        w_real = float(summary["final_net_welfare"]) - initial
        basis = "final_net_welfare"
    else:
        w_real = float(summary["final_welfare"]) - initial
        basis = "final_welfare"
    denominator = max(0.0, optimum - initial)  # frontiers are floored (v2)
    result: dict[str, Any] = {
        "w_real": w_real,
        "w_real_basis": basis,
        "denominator": denominator,
        "denominator_tier": DENOM_TIER_WSTAR,
        "bayesian_score_status": "skipped_with_reason",
        "not_scorable_reason": _FALLBACK_REASON,
    }
    if denominator <= EPS:
        result.update(score=None, score_clip=None, status="degenerate_denominator")
        return result
    score = w_real / denominator
    result.update(score=score, score_clip=_clamp01(score), status="ok")
    return result
