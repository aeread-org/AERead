"""Unified CaseOracle + Bayes-optimal carve-out (Slice 1 of the oracle carve-out spec,
docs/experiments/2026-07-06_oracle_carveout_spec.md).

Scores an agent by welfare-efficiency against the *achievable* frontier W_bayes (not the god's-eye
W*), and reports Delta_unc = W* - W_bayes (the Myerson-Satterthwaite floor) separately from the charged
gap W_bayes - W_real. This first slice wires the exact 2x2 bilateral backend (delta_inf_oracle) behind
the general interface; the ExchangeWorld (mc_wbayes) and eval_dev adapters come in later slices.

Naming follows the canonical cheap_talk_bench.oracle_decomposition:
    inf  = w_post - w_real   (posterior-inference failure; charged)
    unc  = w_star - w_bayes  (irreducible uncertainty / M-S floor; carved out, NOT charged)
    ctrl = w_bayes - w_post  (control given the belief; charged)
so charged = inf + ctrl = w_bayes - w_real, and unc + charged telescopes to w_star - w_real.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Protocol, runtime_checkable

from aeread import delta_inf_oracle as _do

EPS = 1e-9

# denominator tiers, in preference order (spec §1b)
TIER_EXACT = "exact_wbayes"
TIER_MC = "mc_wbayes"
TIER_FALLBACK = "wstar_fallback"


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass
class BayesResult:
    """The Bayes-optimal denominator for one case + its provenance.

    Carries the V1 per-record fields (Contract D4) so a score is always traceable and a
    skipped/failed Bayesian computation is labeled, never silently a zero (Reference §8)."""
    w_bayes: float
    w_star: float
    tier: str                                   # TIER_EXACT | TIER_MC | TIER_FALLBACK
    delta_unc: float                            # w_star - w_bayes (>=0 by definition; may be ~0)
    bayesian_score_status: str = "scored"       # scored | skipped_with_reason | timeout_with_partial_result
    ci: Optional[tuple] = None                  # (lo, hi) on w_bayes for the mc tier; None if exact
    oracle_family: str = ""
    oracle_version: str = ""
    state_hash: str = ""
    transcript_hash: str = ""
    scorable: bool = True
    not_scorable_reason: str = ""

    def denominator(self) -> float:
        """The tier-appropriate denominator: W* under fallback, else W_bayes (spec §1b)."""
        return self.w_star if self.tier == TIER_FALLBACK else self.w_bayes


@runtime_checkable
class CaseOracle(Protocol):
    """Every case implements this. The objective is case-defined (total welfare, buyer surplus,
    or expected surplus); efficiency = realized / denominator is the common currency."""

    def w_star(self) -> float: ...
    def w_bayes(self, *, seed: int = 0) -> BayesResult: ...
    def realized(self, action) -> float: ...


def decompose_carveout(w_real: float, w_bayes: float, w_star: float,
                       *, w_post: Optional[float] = None,
                       denominator: Optional[float] = None) -> dict:
    """Split the total gap W* - W_real into the carved-out floor (unc) and the charged shortfall.

    With a belief-injected arm (w_post), further split the charged region into inference (inf) and
    control (ctrl) at the W_bayes frontier, per the canonical oracle_decomposition naming. Without
    it, only the combined `charged` is known (inf/ctrl left None). The gaps are reported as
    tiered, model-relative diagnostics (Rationale §9-10), not asserted as identified additive facts.

    Per the carve-out contract v2 the efficiency ratio is RAW: `ratio_raw` preserves negative
    (value-destroying) and above-frontier values; `ratio_clip` is the clamp01 presentation
    companion. A degenerate denominator (<= EPS) yields None for both — never a fabricated
    perfect score. `denominator` overrides w_bayes for the ratio (pass the tier-appropriate
    BayesResult.denominator(); the gap decomposition stays anchored at w_bayes).
    """
    unc = max(0.0, w_star - w_bayes)
    charged = w_bayes - w_real
    if w_post is None:
        inf = ctrl = None
    else:
        inf = w_post - w_real
        ctrl = w_bayes - w_post
    denom = w_bayes if denominator is None else denominator
    ratio_raw = None if denom <= EPS else w_real / denom
    ratio_clip = None if ratio_raw is None else _clamp01(ratio_raw)
    return {"unc": unc, "charged": charged, "inf": inf, "ctrl": ctrl,
            "ratio_raw": ratio_raw, "ratio_clip": ratio_clip}


@dataclass
class BilateralExchangeCase:
    """The exact 2x2 bilateral case (a1 holds good0, a2 holds good1). Delegates to delta_inf_oracle;
    no arithmetic of its own. `action` is a transfers list `[(frm, to, good, qty), ...]`.

    The Bayes-optimal denominator is exact: an exact expectation over the uniform-integer prior on
    the counterpart's two values [prior_lo, prior_hi], times a grid over the proposer's action."""
    values: list                                # [[a1g0, a1g1], [a2g0, a2g1]]
    holdings: list                              # [[q0, 0], [0, q1]]
    proposer: int = 0
    prior_lo: int = 0
    prior_hi: int = 9
    grid: int = 40

    def w_star(self) -> float:
        return _do.best_mutually_ir_gain_2x2(self.values, self.holdings, grid=self.grid)

    def w_bayes(self, *, seed: int = 0) -> BayesResult:
        wb = _do.bayes_optimal_prior_welfare(
            self.values[self.proposer], self.holdings, self.prior_lo, self.prior_hi, grid=self.grid)
        ws = self.w_star()
        return BayesResult(
            w_bayes=wb, w_star=ws, tier=TIER_EXACT, delta_unc=max(0.0, ws - wb),
            oracle_family="bilateral_2x2", oracle_version="v0")

    def realized(self, action) -> float:
        return _do.realized_welfare(self.values, self.holdings, self.proposer, action)


def score_case(case: CaseOracle, action, *, seed: int = 0) -> dict:
    """Score one (case, action): the raw efficiency ratio against the tier-appropriate
    denominator (BayesResult.denominator() — W* under wstar_fallback, else W_bayes), plus the
    carve-out diagnostics and the BayesResult provenance."""
    br = case.w_bayes(seed=seed)
    w_real = case.realized(action)
    dec = decompose_carveout(w_real, br.w_bayes, br.w_star, denominator=br.denominator())
    return {"w_real": w_real, "result": br, "score_tier": br.tier,
            "bayesian_score_status": br.bayesian_score_status, **dec}


# ---------------------------------------------------------------------------
# D14 — multi-party welfare oracles (bundle + procurement)
#
# Welfare-max cases: the objective is total welfare gain over the initial endowment,
# and an exact full-information optimizer already exists per domain. These wrappers add
# no arithmetic -- they delegate to the existing solver (w_star) + episode summarizer
# (realized + gate). Multi-agent W_bayes is a Bayesian-Nash fixed point (intractable
# for this slice), so the denominator degrades UPWARD to W* (TIER_FALLBACK) per spec
# §1b -- labeled `skipped_with_reason`, never a silent zero. The reported number is a
# conservative lower bound on true efficiency (W_real/W* <= W_real/W_bayes).
# ---------------------------------------------------------------------------

try:  # Supports both `python sprint/...py` and `python -m sprint...` import styles.
    from aeread import exchange_economy as _ex
    from aeread import exchange_procurement as _ep
    from aeread import bundle_bayes_oracle as _bb
except ModuleNotFoundError:  # pragma: no cover - exercised by module execution.
    from . import exchange_economy as _ex
    from . import exchange_procurement as _ep
    from . import bundle_bayes_oracle as _bb


@runtime_checkable
class GatedCaseOracle(CaseOracle, Protocol):
    """A CaseOracle that also exposes the feasibility ∧ authorization gate (for the D15
    scorer). An action that fails the gate scores 0 regardless of welfare."""

    def gate(self, action) -> bool: ...


_BUNDLE_FALLBACK_REASON = (
    "multi-agent bundle W_bayes is a Bayesian-Nash fixed point; wstar_fallback per "
    "oracle_carveout_spec §1b (mc_wbayes tier deferred)")
_PROC_FALLBACK_REASON = (
    "multi-supplier procurement W_bayes over private costs is a Bayesian-Nash fixed "
    "point; wstar_fallback per oracle_carveout_spec §1b (mc_wbayes tier deferred)")


@dataclass
class BundleCaseOracle:
    """Welfare-max wrapper over the bundle-under-budget world. `action` is the
    post-settlement FINAL allocation matrix; `self.world` carries the INITIAL endowment."""

    world: "_ex.ExchangeWorld"

    def w_star(self) -> float:
        # Rational full-info ceiling: a buyer never completes a value-destroying bundle, so the
        # ceiling floors at 0 (matches the bilateral best_mutually_ir_gain_2x2, which is inherently
        # >=0). No-op when bundle_value > min_cost (the pilot); correct for low-value configs.
        return max(0.0, _ex.solve_bundle_min_cost(self.world).optimal_welfare_gain)

    def w_bayes(self, *, seed: int = 0) -> BayesResult:
        # mc_wbayes (carve-out spec §1b): the best EXPECTED social welfare a buyer can realize
        # knowing its mandate + the PRIOR over sellers' costs, sellers accepting iff price >= cost
        # (a best response to rational IR-responders, NOT a Bayesian-Nash fixed point). See
        # bundle_bayes_oracle. Degrades to wstar_fallback for unsupported world structures.
        ws = self.w_star()
        try:
            wb, ci = _bb.bundle_bayes_optimal_welfare(self.world, seed=seed)
        except Exception as exc:  # never a silent zero: label the reason and fall back to W*
            return BayesResult(
                w_bayes=ws, w_star=ws, tier=TIER_FALLBACK, delta_unc=0.0,
                bayesian_score_status="skipped_with_reason",
                not_scorable_reason=f"{_BUNDLE_FALLBACK_REASON} [mc_wbayes unavailable: {exc}]",
                oracle_family="bundle_min_cost", oracle_version="v0", scorable=True)
        # W_bayes >= 0 (the buyer can always decline). Do NOT clamp to the per-instance W*: the
        # ordering W_bayes <= E[W*] holds in EXPECTATION, not per-instance (same as the bilateral
        # backend, whose ordering test is `w_bayes <= expected_wstar`); the scorer floors the
        # carve-out as unc = max(0, W* - W_bayes).
        wb = max(0.0, wb)
        return BayesResult(
            w_bayes=wb, w_star=ws, tier=TIER_MC, delta_unc=max(0.0, ws - wb),
            bayesian_score_status="scored", ci=ci,
            oracle_family="bundle_bayes_mc", oracle_version="v1", scorable=True)

    def _metrics(self, action):
        final_world = replace(self.world, allocation=action)
        return _ex.summarize_bundle_episode(self.world.allocation, final_world)

    def realized(self, action) -> float:
        return self._metrics(action).welfare_gain

    def gate(self, action) -> bool:
        m = self._metrics(action)
        return bool(m.bundle_completed and not m.over_budget)


@dataclass
class ProcurementCaseOracle:
    """Welfare-max wrapper over the D12 procurement world. `action` is a list[AwardLine]."""

    world: "_ep.ProcurementWorld"
    signoff_granted: bool = False

    def w_star(self) -> float:
        return _ep.solve_min_cost_award(self.world).optimal_welfare_gain

    def w_bayes(self, *, seed: int = 0) -> BayesResult:
        ws = self.w_star()
        return BayesResult(
            w_bayes=ws, w_star=ws, tier=TIER_FALLBACK, delta_unc=0.0,
            bayesian_score_status="skipped_with_reason",
            not_scorable_reason=_PROC_FALLBACK_REASON,
            oracle_family="procurement_min_cost", oracle_version="v0", scorable=True)

    def _metrics(self, action):
        return _ep.summarize_award(self.world, action, signoff_granted=self.signoff_granted)

    def realized(self, action) -> float:
        return self._metrics(action).welfare_gain

    def gate(self, action) -> bool:
        m = self._metrics(action)
        return bool(m.complete and m.feasible and m.authorized)
