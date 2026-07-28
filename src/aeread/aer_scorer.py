"""D15 — the unified AER scorer + v0 leaderboard.

Turns a GatedCaseOracle + a submission's per-episode actions into the headline AER of the
carve-out contract v2 (docs 2026-07-08_carveout_oracle_unsaturated):

    AER = sum_e(gated W_real_e) / sum_e(denominator_e)      (RAW aggregate ratio)

- **Negatives are preserved**: an agent that pays more than it captures scores AER < 0 —
  value destruction is substantive, not clamp-to-zero noise. A favorable pool can exceed 1.
  `aer_clip = clamp01(AER)` is reported as an optional presentation companion only.
- **Gate cliff**: an action that fails the case's feasibility ∧ authorization gate
  contributes W_real := 0 for that episode; the episode's denominator is retained.
- **Degenerate denominator**: a pool with sum(denominator) <= EPS gets
  status="degenerate_denominator" and no fabricated score (never the old 0/0 -> 1.0).
- **CI**: bootstrap over episodes (percentile 2.5/97.5 on the resampled ratio of sums —
  the same loop as eval_dev/probe_carveout_market_gemini.py, byte-order compatible).
  For the mc_wbayes tier, denominator uncertainty (BayesResult.ci) is propagated into
  each replicate. With a single episode the interval is degenerate; `n_episodes` is the
  reader's guard — never report a single-seed ratio as a leaderboard number.
- **Tier discipline** (spec §1b): a score carries its denominator tier; the leaderboard
  never pools scores across tiers.

Provider-free: all arithmetic, no LLM.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

try:  # Supports both `python sprint/...py` and `python -m sprint...` import styles.
    from aeread import exchange_economy as _ex
    from aeread import exchange_procurement as _ep
    from aeread.agentecon_oracle import (
        BundleCaseOracle,
        ProcurementCaseOracle,
        GatedCaseOracle,
        EPS,
        TIER_MC,
        _clamp01,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by module execution.
    from . import exchange_economy as _ex
    from . import exchange_procurement as _ep
    from .agentecon_oracle import (
        BundleCaseOracle,
        ProcurementCaseOracle,
        GatedCaseOracle,
        EPS,
        TIER_MC,
        _clamp01,
    )

STATUS_OK = "ok"
STATUS_DEGENERATE = "degenerate_denominator"


@dataclass
class AERReport:
    """One submission's aggregate score on one case.

    `aer` is the RAW aggregate ratio sum(gated W_real)/sum(denominator) — negative when the
    submission destroys value, above 1 when the pool beats the prior frontier. `aer_clip` is
    the clamp01 presentation companion. `tier` is the denominator regime (never mix tiers
    across cases in an aggregate, per spec §1b)."""

    aer: Optional[float]
    aer_clip: Optional[float]
    ci: tuple                    # bootstrap 95% percentile CI on the raw aggregate
    tier: str
    status: str                  # STATUS_OK | STATUS_DEGENERATE
    gate_pass_rate: float
    n_episodes: int
    sum_w_real: float            # gated
    sum_denominator: float
    denominator: float           # the per-episode denominator (constant within a case)
    bayesian_score_status: str
    oracle_family: str
    oracle_version: str


def score_submission(
    oracle: GatedCaseOracle,
    actions: Sequence,
    *,
    seed: int = 0,
    n_boot: int = 2000,
    boot_seed: int = 7,
    propagate_mc: bool = True,
) -> AERReport:
    """Aggregate AER over one submission's per-episode actions (raw ratio of sums).

    Each episode contributes `gate ? W_real : 0` to the numerator and the tier-appropriate
    denominator to the denominator sum. The CI is a seeded bootstrap over episodes; under
    the mc_wbayes tier the denominator's own uncertainty is redrawn per replicate."""
    if not actions:
        raise ValueError("need >=1 episode action to score")
    br = oracle.w_bayes(seed=seed)
    denom = br.denominator()
    rows: list[tuple[float, float]] = []
    gate_passes = 0
    for a in actions:
        passed = bool(oracle.gate(a))
        gate_passes += int(passed)
        w_real = oracle.realized(a) if passed else 0.0  # gate cliff: numerator only
        rows.append((w_real, denom))
    n = len(rows)
    sum_wr = sum(r[0] for r in rows)
    sum_d = sum(r[1] for r in rows)
    common = dict(
        tier=br.tier,
        gate_pass_rate=gate_passes / n,
        n_episodes=n,
        sum_w_real=sum_wr,
        sum_denominator=sum_d,
        denominator=denom,
        bayesian_score_status=br.bayesian_score_status,
        oracle_family=br.oracle_family,
        oracle_version=br.oracle_version,
    )
    if sum_d <= EPS:
        return AERReport(
            aer=None, aer_clip=None, ci=(float("nan"), float("nan")),
            status=STATUS_DEGENERATE, **common)
    aer = sum_wr / sum_d

    # bootstrap CI on the pooled ratio (probe_carveout_market_gemini.py pattern)
    boot = random.Random(boot_seed)
    mc_sigma: Optional[float] = None
    if propagate_mc and br.tier == TIER_MC and br.ci is not None:
        lo, hi = br.ci
        mc_sigma = max(0.0, (hi - lo) / 3.92)  # 95% normal interval -> sigma
    samples: list[float] = []
    for _ in range(n_boot):
        pick = [rows[boot.randrange(n)] for _ in rows]
        swb = sum(p[1] for p in pick)
        if mc_sigma:
            # one case-level denominator per replicate, floored at 0 (frontiers are floored)
            d_star = max(0.0, boot.gauss(denom, mc_sigma))
            swb = d_star * len(pick)
        if swb > EPS:
            samples.append(sum(p[0] for p in pick) / swb)
    samples.sort()
    ci = (
        (samples[int(0.025 * len(samples))], samples[int(0.975 * len(samples))])
        if samples
        else (float("nan"), float("nan"))
    )
    return AERReport(aer=aer, aer_clip=_clamp01(aer), ci=ci, status=STATUS_OK, **common)


def build_oracle(config_path: str) -> GatedCaseOracle:
    """Factory: dispatch a config file to its domain oracle by world shape. Bundle worlds
    (`world_type=bundle_under_budget`) → BundleCaseOracle; procurement worlds
    (`suppliers`+`demand`) → ProcurementCaseOracle."""
    raw = json.loads(Path(config_path).read_text())
    if raw.get("world_type") == "bundle_under_budget" or "bundle_spec" in raw:
        return BundleCaseOracle(_ex.make_world_from_config(_ex.load_experiment_config(config_path)))
    if "suppliers" in raw and "demand" in raw:
        return ProcurementCaseOracle(_ep.load_procurement_world(config_path))
    raise ValueError(f"cannot infer a domain oracle for {config_path}")


def leaderboard(reports: dict) -> dict:
    """v0 leaderboard: one row per case (tier-tagged) + per-tier aggregates.

    Tier discipline (carve-out §1b): scores in different denominator tiers are NEVER pooled
    together — the aggregate is per-tier, not one global number. Within a tier the headline
    `pooled_aer` is the v2 aggregate over every episode of every case
    (sum of case numerators / sum of case denominators); `mean_case_aer` (unweighted mean of
    per-case AERs) is reported as a secondary view. Degenerate cases are listed in rows with
    their status but excluded from the aggregates."""
    rows = [
        {"case_id": case_id, "aer": r.aer, "aer_clip": r.aer_clip, "ci": r.ci,
         "tier": r.tier, "status": r.status, "gate_pass_rate": r.gate_pass_rate,
         "n_episodes": r.n_episodes, "oracle_family": r.oracle_family,
         "oracle_version": r.oracle_version}
        for case_id, r in reports.items()
    ]
    tiers: dict = {}
    for tier in {r.tier for r in reports.values()}:
        scored = [r for r in reports.values() if r.tier == tier and r.status == STATUS_OK]
        degenerate = [r for r in reports.values() if r.tier == tier and r.status != STATUS_OK]
        sum_wr = sum(r.sum_w_real for r in scored)
        sum_d = sum(r.sum_denominator for r in scored)
        pooled = sum_wr / sum_d if sum_d > EPS else None
        tiers[tier] = {
            "pooled_aer": pooled,
            "pooled_aer_clip": None if pooled is None else _clamp01(pooled),
            "mean_case_aer": (sum(r.aer for r in scored) / len(scored)) if scored else None,
            "n_cases": len(scored),
            "n_degenerate": len(degenerate),
        }
    rows.sort(key=lambda x: (x["tier"], -(x["aer"] if x["aer"] is not None else -math.inf)))
    return {"rows": rows, "tiers": tiers}
