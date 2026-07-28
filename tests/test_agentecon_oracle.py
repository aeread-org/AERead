"""Probe test for the unified CaseOracle + Bayes-optimal carve-out (Slice 1 of
docs/experiments/2026-07-06_oracle_carveout_spec.md).

Provider-free: exercises the exact 2x2 bilateral backend only (no LLM). Verifies the §7 carve-out
invariants and the two anchors (degenerate-prior => Delta_unc = 0; information-matters => Delta_unc > 0).

Correctness note the anchors respect: W_bayes is the prior-EXPECTATION of the best prior-only policy
(a scalar), while W_real and W_star are for the REALIZED type. So `W_real <= W_star` and the
expectation ordering `W_bayes <= E_prior[W_star]` are robust invariants; `W_real <= W_bayes` is NOT a
per-episode invariant (a favorable draw can beat the prior-expected value -> the headline clamps).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import delta_inf_oracle as do  # noqa: E402
from aeread import agentecon_oracle as ao  # noqa: E402

EPS = 1e-6

# a1 holds good0 and wants good1; a2 holds good1 and wants good0 -> large gains from trade.
FAVORABLE = dict(values=[[1, 8], [9, 1]], holdings=[[10, 0], [0, 10]])
SWAP = [(0, 1, 0, 5), (1, 0, 1, 5)]  # mutually-IR swap (from the delta_inf test suite)


# ---- pure decomposition arithmetic ----------------------------------------------------------

def test_decompose_telescopes_to_total_gap():
    d = ao.decompose_carveout(w_real=2.0, w_bayes=5.0, w_star=8.0)
    assert d["unc"] == 3.0                      # W* - W_bayes  (carved out)
    assert d["charged"] == 3.0                  # W_bayes - W_real (charged: inf+ctrl)
    assert abs(d["unc"] + d["charged"] - (8.0 - 2.0)) < EPS   # telescopes to W* - W_real
    assert abs(d["ratio_raw"] - 0.4) < EPS      # 2/5, raw
    assert abs(d["ratio_clip"] - 0.4) < EPS


def test_decompose_splits_inf_ctrl_with_belief_arm():
    d = ao.decompose_carveout(w_real=2.0, w_bayes=5.0, w_star=8.0, w_post=4.0)
    assert d["inf"] == 2.0                       # w_post - w_real (canonical: post-base)
    assert d["ctrl"] == 1.0                      # w_bayes - w_post
    assert abs(d["inf"] + d["ctrl"] - d["charged"]) < EPS


def test_ratio_raw_preserves_negative_and_above_frontier():
    # carve-out contract v2: the ratio is RAW — clipping is a presentation companion only
    assert ao.decompose_carveout(0.0, 5.0, 8.0)["ratio_raw"] == 0.0        # nothing realized
    d_neg = ao.decompose_carveout(-3.0, 5.0, 8.0)                          # value destroyed
    assert abs(d_neg["ratio_raw"] - (-0.6)) < EPS                          # negative PRESERVED
    assert d_neg["ratio_clip"] == 0.0
    d_hi = ao.decompose_carveout(9.0, 5.0, 8.0)                            # beat the prior-Bayes
    assert abs(d_hi["ratio_raw"] - 1.8) < EPS                              # above-frontier PRESERVED
    assert d_hi["ratio_clip"] == 1.0


def test_degenerate_denominator_yields_none_not_perfect():
    # the old 0/0 -> 1.0 convention fabricated a perfect score; v2 flags it instead
    d = ao.decompose_carveout(0.0, 0.0, 0.0)
    assert d["ratio_raw"] is None and d["ratio_clip"] is None


def test_score_case_uses_tier_denominator_not_wbayes_field():
    # regression: score_case ignored BayesResult.denominator(), so a fallback-tier case
    # with w_bayes != w_star would be scored against the wrong denominator
    class _FakeFallbackCase:
        def w_star(self):
            return 8.0

        def w_bayes(self, *, seed: int = 0):
            return ao.BayesResult(
                w_bayes=5.0, w_star=8.0, tier=ao.TIER_FALLBACK, delta_unc=3.0,
                bayesian_score_status="skipped_with_reason",
                oracle_family="fake", oracle_version="v0")

        def realized(self, action):
            return 4.0

    s = ao.score_case(_FakeFallbackCase(), action=None)
    assert abs(s["ratio_raw"] - 0.5) < EPS       # 4/8 (W* fallback), NOT 4/5 (w_bayes field)
    assert s["bayesian_score_status"] == "skipped_with_reason"


# ---- the 2x2 case oracle end-to-end ---------------------------------------------------------

def test_case_delegates_to_exact_backend():
    case = ao.BilateralExchangeCase(**FAVORABLE, prior_lo=0, prior_hi=9, grid=24)
    br = case.w_bayes()
    assert br.tier == "exact_wbayes"
    assert br.bayesian_score_status == "scored"
    assert abs(br.w_bayes - do.bayes_optimal_prior_welfare([1, 8], FAVORABLE["holdings"], 0, 9, grid=24)) < EPS
    assert abs(br.w_star - do.best_mutually_ir_gain_2x2(FAVORABLE["values"], FAVORABLE["holdings"], grid=24)) < EPS


def test_realized_never_exceeds_full_info_ceiling():
    # robust per-episode invariant: W_real <= W_star for any action
    case = ao.BilateralExchangeCase(**FAVORABLE, grid=24)
    ws = case.w_star()
    for action in [SWAP, [], [(0, 1, 0, 3), (1, 0, 1, 4)], [(0, 1, 0, 10), (1, 0, 1, 10)]]:
        assert case.realized(action) <= ws + EPS


def test_expectation_ordering_wbayes_le_expected_wstar():
    # W_bayes <= E_prior[W*] (the identification-safe ordering)
    case = ao.BilateralExchangeCase(**FAVORABLE, prior_lo=0, prior_hi=9, grid=24)
    wb = case.w_bayes().w_bayes
    exp_wstar = sum(do.best_mutually_ir_gain_2x2([[1, 8], [b0, b1]], FAVORABLE["holdings"], grid=24)
                    for b0 in range(10) for b1 in range(10)) / 100.0
    assert wb <= exp_wstar + EPS


def test_carveout_positive_when_information_matters():
    # favorable realized type ([9,1]) + spread prior -> a real Myerson-Satterthwaite floor
    case = ao.BilateralExchangeCase(**FAVORABLE, prior_lo=0, prior_hi=9, grid=24)
    br = case.w_bayes()
    assert br.delta_unc > 0.5
    assert br.w_bayes < br.w_star


def test_degenerate_prior_zero_carveout_anchor():
    # prior collapsed to the realized counterpart type [5,5] -> Delta_unc == 0, W_bayes == W_star,
    # headline == W_real / W_star. Proves the carve-out vanishes when there is nothing to carve out.
    world = dict(values=[[1, 8], [5, 5]], holdings=[[10, 0], [0, 10]])
    case = ao.BilateralExchangeCase(**world, prior_lo=5, prior_hi=5, grid=24)
    br = case.w_bayes()
    assert abs(br.delta_unc) < EPS
    assert abs(br.w_bayes - br.w_star) < EPS
    scored = ao.score_case(case, SWAP)
    assert abs(scored["ratio_raw"] - scored["w_real"] / br.w_star) < EPS


def test_score_case_reports_tier_and_carveout():
    case = ao.BilateralExchangeCase(**FAVORABLE, prior_lo=0, prior_hi=9, grid=24)
    s = ao.score_case(case, SWAP)
    assert s["score_tier"] == "exact_wbayes"
    assert s["ratio_raw"] is not None            # raw ratio, unclamped
    assert 0.0 <= s["ratio_clip"] <= 1.0         # the presentation companion is bounded
    assert s["unc"] >= 0.0
    assert s["w_real"] <= s["result"].w_star + EPS


# ---- D14: multi-party welfare oracles (bundle + procurement) ---------------------------------

from aeread import exchange_economy as ex  # noqa: E402
from aeread.agentecon_oracle import BundleCaseOracle, TIER_FALLBACK  # noqa: E402

BUNDLE_CFG = "configs/exchange_economy/bundle_under_budget_trip3.json"


def _trip3_world():
    return ex.make_world_from_config(ex.load_experiment_config(BUNDLE_CFG))


def test_bundle_oracle_wstar_matches_solver_and_is_45678():
    w = _trip3_world()
    o = BundleCaseOracle(w)
    assert o.w_star() == ex.solve_bundle_min_cost(w).optimal_welfare_gain
    assert abs(o.w_star() - 45.678) < 1e-3


def test_bundle_oracle_wbayes_gated_default_fallback_optin_mc(monkeypatch):
    # DEFAULT: mc_wbayes is gated (ex-ante estimator pending denominator-semantics
    # decision) -> labeled fallback, reason recorded, never silent (spec §1b).
    monkeypatch.delenv("AEREAD_MC_WBAYES", raising=False)
    br = BundleCaseOracle(_trip3_world()).w_bayes()
    assert br.tier == TIER_FALLBACK
    assert br.w_bayes == br.w_star and br.denominator() == br.w_star
    assert br.bayesian_score_status == "skipped_with_reason"
    assert br.scorable is True and "gated" in br.not_scorable_reason
    # OPT-IN: with the flag (and the 2026-07-23 seller_layout wiring fix), the
    # estimator engages on the production config->world path.
    monkeypatch.setenv("AEREAD_MC_WBAYES", "1")
    br2 = BundleCaseOracle(_trip3_world()).w_bayes()
    assert br2.tier == "mc_wbayes"
    assert br2.bayesian_score_status == "scored"


def test_bundle_oracle_realized_and_gate():
    w = _trip3_world()
    o = BundleCaseOracle(w)
    opt = ex.social_optimum(w)                       # min-cost complete bundle
    assert abs(o.realized(opt) - o.w_star()) < 1e-6  # optimal allocation realizes w_star
    assert o.gate(opt) is True                       # completed ∧ ¬over_budget
    assert o.realized(w.allocation) == 0.0           # no trade → incomplete bundle → 0
    assert o.gate(w.allocation) is False


from aeread import exchange_procurement as ep  # noqa: E402
from aeread.agentecon_oracle import ProcurementCaseOracle  # noqa: E402

PROC_CFG = "configs/exchange_economy/procurement_electronics_q3.json"


def test_procurement_oracle_wstar_and_realized():
    w = ep.load_procurement_world(PROC_CFG)
    o = ProcurementCaseOracle(w)
    assert o.w_star() == ep.solve_min_cost_award(w).optimal_welfare_gain
    assert abs(o.w_star() - 920.0) < 1e-6
    award = ep.solve_min_cost_award(w).lines
    assert abs(o.realized(award) - o.w_star()) < 1e-6
    assert o.gate(award) is True


def test_procurement_oracle_empty_award_gated_zero():
    o = ProcurementCaseOracle(ep.load_procurement_world(PROC_CFG))
    assert o.realized([]) == 0.0
    assert o.gate([]) is False       # incomplete demand → gate fails
