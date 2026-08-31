"""D15 — the unified AER scorer + v0 leaderboard aggregator (provider-free).

Locks the carve-out contract v2: the headline is the RAW aggregate ratio
sum(gated W_real)/sum(denominator) — negatives preserved, clip demoted to a companion,
bootstrap CI over episodes, degenerate denominators flagged (never a fabricated score),
and tier discipline (§1b: scores in different denominator tiers are never pooled)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402
from aeread import exchange_procurement as ep  # noqa: E402
from aeread.agentecon_oracle import (  # noqa: E402
    BayesResult,
    BundleCaseOracle,
    ProcurementCaseOracle,
    TIER_EXACT,
    TIER_FALLBACK,
    TIER_MC,
)
from aeread.aer_scorer import (  # noqa: E402
    AERReport,
    STATUS_DEGENERATE,
    STATUS_OK,
    build_oracle,
    leaderboard,
    score_submission,
)

BUNDLE_CFG = "cases/exchange_v1/specialized/bundle_under_budget_trip3.json"
PROC_CFG = "cases/exchange_v1/specialized/procurement_electronics_q3.json"


def _trip3():
    return BundleCaseOracle(ex.make_world_from_config(ex.load_experiment_config(BUNDLE_CFG)))


class _FakeOracle:
    """Gate-always-pass oracle whose action IS its realized value — lets the tests drive
    the numerator to any value (negative, above-frontier) against a chosen denominator."""

    def __init__(self, w_bayes=10.0, w_star=10.0, tier=TIER_EXACT, ci=None):
        self._br = BayesResult(
            w_bayes=w_bayes, w_star=w_star, tier=tier,
            delta_unc=max(0.0, w_star - w_bayes), ci=ci,
            oracle_family="fake", oracle_version="v0")

    def w_star(self):
        return self._br.w_star

    def w_bayes(self, *, seed: int = 0):
        return self._br

    def realized(self, action):
        return float(action)

    def gate(self, action):
        return True


# ---- the v2 headline: raw aggregate ratio ----------------------------------------------------

def test_optimal_actions_score_one():
    o = _trip3()
    opt = ex.social_optimum(o.world)
    r = score_submission(o, [opt, opt, opt])
    assert isinstance(r, AERReport)
    assert abs(r.aer - 1.0) < 1e-6 and r.tier == TIER_FALLBACK
    assert r.gate_pass_rate == 1.0 and r.n_episodes == 3
    assert r.status == STATUS_OK
    assert r.ci[0] <= r.aer <= r.ci[1]
    assert r.oracle_family == "bundle_min_cost"


def test_infeasible_episode_zeroes_numerator_keeps_denominator():
    o = _trip3()
    opt = ex.social_optimum(o.world)
    noop = o.world.allocation                 # stranded / incomplete bundle
    r = score_submission(o, [opt, noop])
    assert abs(r.aer - 0.5) < 1e-6            # (w* + 0) / (2 w*)
    assert r.gate_pass_rate == 0.5
    assert abs(r.sum_denominator - 2 * o.w_star()) < 1e-6  # denominator retained


def test_negative_pool_preserved():
    # an agent that destroys value must show AER < 0 — not clamp-to-zero
    r = score_submission(_FakeOracle(w_bayes=10.0), [-5.0, 2.0])
    assert abs(r.aer - (-0.15)) < 1e-9        # (-5 + 2) / 20
    assert r.aer_clip == 0.0                  # companion only
    assert r.ci[0] < 0                        # the CI lives on the raw scale too


def test_above_frontier_pool_preserved():
    r = score_submission(_FakeOracle(w_bayes=10.0), [15.0, 10.0])
    assert abs(r.aer - 1.25) < 1e-9           # 25 / 20 — a favorable pool may exceed 1
    assert r.aer_clip == 1.0


def test_degenerate_denominator_flagged_not_perfect():
    # the old scorer fabricated ratio 1.0 on a ~0 denominator
    r = score_submission(_FakeOracle(w_bayes=0.0, w_star=0.0), [0.0, 0.0])
    assert r.status == STATUS_DEGENERATE
    assert r.aer is None and r.aer_clip is None
    assert math.isnan(r.ci[0])


def test_procurement_submission_scores():
    w = ep.load_procurement_world(PROC_CFG)
    o = ProcurementCaseOracle(w)
    award = ep.solve_min_cost_award(w).lines
    r = score_submission(o, [award, []])      # optimal + empty
    assert abs(r.aer - 0.5) < 1e-6 and r.oracle_family == "procurement_min_cost"
    assert r.bayesian_score_status == "skipped_with_reason"  # fallback tier, labeled


def test_score_submission_requires_episodes():
    with pytest.raises(ValueError):
        score_submission(_trip3(), [])


# ---- bootstrap CI ----------------------------------------------------------------------------

def test_bootstrap_ci_deterministic_given_seed():
    actions = [3.0, 7.0, 12.0, 5.0, 9.0]
    r1 = score_submission(_FakeOracle(), actions, boot_seed=7)
    r2 = score_submission(_FakeOracle(), actions, boot_seed=7)
    assert r1.ci == r2.ci
    r3 = score_submission(_FakeOracle(), actions, boot_seed=11)
    assert r3.ci != r1.ci                     # a different seed resamples differently


def test_mc_tier_denominator_uncertainty_widens_ci():
    actions = [6.0, 8.0, 10.0, 12.0]
    exact = score_submission(_FakeOracle(w_bayes=10.0, tier=TIER_EXACT), actions)
    mc = score_submission(
        _FakeOracle(w_bayes=10.0, tier=TIER_MC, ci=(8.0, 12.0)), actions)
    assert mc.aer == exact.aer                # the point estimate is unchanged
    assert (mc.ci[1] - mc.ci[0]) > (exact.ci[1] - exact.ci[0])  # the CI is not


# ---- leaderboard aggregator + oracle factory ------------------------------------------------

def test_build_oracle_dispatches_by_config():
    b = build_oracle(BUNDLE_CFG)
    p = build_oracle(PROC_CFG)
    assert isinstance(b, BundleCaseOracle) and isinstance(p, ProcurementCaseOracle)


def test_leaderboard_groups_by_tier_no_mixing():
    o = build_oracle(BUNDLE_CFG)
    opt = ex.social_optimum(o.world)
    rep = score_submission(o, [opt, o.world.allocation])   # aer 0.5
    lb = leaderboard({"trip3": rep})
    assert lb["rows"][0]["case_id"] == "trip3" and lb["rows"][0]["tier"] == TIER_FALLBACK
    assert abs(lb["tiers"][TIER_FALLBACK]["pooled_aer"] - 0.5) < 1e-6
    # a wstar-tier score must never be pooled into a different tier's aggregate
    assert set(lb["tiers"]) == {TIER_FALLBACK}


def test_leaderboard_pools_episodes_within_tier():
    b = build_oracle(BUNDLE_CFG)
    p = build_oracle(PROC_CFG)
    rb = score_submission(b, [ex.social_optimum(b.world)])          # aer 1.0
    rp = score_submission(p, [[]])                                   # aer 0.0 (empty award)
    lb = leaderboard({"trip3": rb, "electronics": rp})
    assert {r["case_id"] for r in lb["rows"]} == {"trip3", "electronics"}
    tier = lb["tiers"][TIER_FALLBACK]
    # v2 aggregate = ratio of pooled sums (denominator-weighted), NOT the mean of case AERs
    expected = (rb.sum_w_real + rp.sum_w_real) / (rb.sum_denominator + rp.sum_denominator)
    assert abs(tier["pooled_aer"] - expected) < 1e-9
    assert abs(tier["mean_case_aer"] - 0.5) < 1e-6                   # secondary view


def test_leaderboard_excludes_degenerate_cases_from_aggregates():
    good = score_submission(_FakeOracle(w_bayes=10.0), [5.0])
    bad = score_submission(_FakeOracle(w_bayes=0.0, w_star=0.0), [0.0])
    lb = leaderboard({"good": good, "bad": bad})
    tier = lb["tiers"][TIER_EXACT]
    assert tier["n_cases"] == 1 and tier["n_degenerate"] == 1
    assert abs(tier["pooled_aer"] - 0.5) < 1e-9
    statuses = {r["case_id"]: r["status"] for r in lb["rows"]}
    assert statuses["bad"] == STATUS_DEGENERATE   # listed, labeled, excluded
