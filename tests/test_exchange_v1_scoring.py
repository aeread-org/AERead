"""D15 scoring bridge for arena run dirs (exchange_v1_scoring.score_run).

Provider-free: score_run reads only summary.json. Locks the carve-out contract v2 on
the arena path: RAW gain ratio (negatives preserved), clip as companion, degenerate
denominators flagged (the arena's own `welfare_ratio` clamps and fabricates 1.0 on a
degenerate optimum — the bridge must never inherit either behavior), and the
wstar_fallback denominator tier labeled with a reason, never silently.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread.exchange_v1 import scoring as scoring  # noqa: E402


def _run_dir(tmp_path, *, initial=10.0, final_net=None, final=16.0, optimum=22.0):
    d = tmp_path / "run"
    d.mkdir()
    summary = {
        "initial_welfare": initial,
        "final_welfare": final,
        "optimum_welfare": optimum,
        "welfare_ratio": 0.5,  # the clamped arena ratio — the bridge must ignore it
    }
    if final_net is not None:
        summary["final_net_welfare"] = final_net
    (d / "summary.json").write_text(json.dumps(summary))
    return d


def test_raw_gain_ratio_from_net_welfare(tmp_path):
    # W_real = net gain (coordination costs charged); denominator = W* gain
    r = scoring.score_run(_run_dir(tmp_path, initial=10.0, final_net=16.0, optimum=22.0))
    assert abs(r["score"] - 0.5) < 1e-9          # (16-10)/(22-10)
    assert r["score_clip"] == 0.5
    assert r["status"] == "ok"
    assert r["denominator_tier"] == "wstar_fallback"
    assert r["bayesian_score_status"] == "skipped_with_reason"
    assert "tier" not in r                        # never clobber the harness's scorer-tier label


def test_negative_net_gain_preserved(tmp_path):
    # coordination costs exceeding captured value must show as AER < 0
    r = scoring.score_run(_run_dir(tmp_path, initial=10.0, final_net=7.0, optimum=22.0))
    assert abs(r["score"] - (-0.25)) < 1e-9      # (7-10)/(22-10)
    assert r["score_clip"] == 0.0                 # companion only
    assert r["status"] == "ok"


def test_falls_back_to_gross_final_when_no_net(tmp_path):
    r = scoring.score_run(_run_dir(tmp_path, initial=10.0, final=13.0, optimum=22.0))
    assert abs(r["score"] - 0.25) < 1e-9
    assert r["w_real_basis"] == "final_welfare"


def test_degenerate_optimum_flagged_not_perfect(tmp_path):
    # the arena's welfare_ratio fabricates 1.0 here; the bridge must flag instead
    r = scoring.score_run(_run_dir(tmp_path, initial=10.0, final_net=10.0, optimum=10.0))
    assert r["status"] == "degenerate_denominator"
    assert r["score"] is None and r["score_clip"] is None


def test_missing_summary_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scoring.score_run(tmp_path)  # no summary.json
