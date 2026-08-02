"""Lockstep pilot driver (keyless): dry-run, concurrent jobs, pooled aggregation.

The concurrency test is the load-bearing one: 8 jobs on 4 worker threads against the
fake provider, every run strict-funnel checked and replay-verified — proof that the
context-local llm_agent hook state keeps concurrent runs' manifests isolated."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_v1_pilot as pilot  # noqa: E402
from test_exchange_v1_roles import _roles_block, fake_provider  # noqa: E402,F401
from test_exchange_v1_runner import _write_config  # noqa: E402


def test_dry_run_lists_jobs(tmp_path, capsys):
    case = _write_config(tmp_path, "case_dry", roles=_roles_block())
    rc = pilot.main([
        "--cases", str(case), "--agents", "noop", "greedy",
        "--seeds", "3", "--out", str(tmp_path / "out"), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "6 jobs" in out and "1 cases x 2 agents x 3 seeds" in out
    assert not (tmp_path / "out").exists()          # dry run touches nothing


def test_concurrent_pilot_runs_isolated_and_aggregates(tmp_path, fake_provider):
    case = _write_config(tmp_path, "case_pilot", roles=_roles_block())
    out = tmp_path / "out"
    rc = pilot.main([
        "--cases", str(case), "--agents", "noop", "greedy",
        "--seed-list", "1201", "1202", "1203", "1204",
        "--workers", "4", "--out", str(out)])   # batch pool is opt-in (parked)
    assert rc == 0
    rows = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 8
    # every run ok + replay-verified under 4-way concurrency (strict funnel inside)
    assert all(r["status"] == "ok" for r in rows), [r.get("error") for r in rows]
    assert all(r["verified"] is True for r in rows)

    summary = json.loads((out / "summary.json").read_text())
    noop = summary["by_case_agent"]["case_pilot|noop"]
    assert noop["n_ok"] == 4 and noop["n_verified"] == 4 and noop["n_error"] == 0
    # noop's pooled AER over the seeds is the do-nothing floor: exactly 0
    assert noop["pooled_aer"] == 0.0 and noop["ci"] is not None
    greedy = summary["by_agent"]["greedy"]
    assert greedy["n_ok"] == 4 and greedy["pooled_aer"] is not None


def test_abort_on_error_rate(tmp_path, monkeypatch):
    def flaky(case_path, agent, seed, out_root, max_tokens):
        return {"case": case_path.stem, "agent": agent, "seed": seed,
                "status": "harness_error", "error": "boom"}

    monkeypatch.setattr(pilot, "run_job", flaky)
    case = _write_config(tmp_path, "case_abort", roles=_roles_block())
    out = tmp_path / "out"
    rc = pilot.main([
        "--cases", str(case), "--agents", "noop",
        "--seed-list", "1", "2", "3", "4", "5", "6",
        "--workers", "1", "--min-jobs-before-abort", "2",
        "--max-error-rate", "0.5", "--out", str(out)])
    assert rc == 2                                  # money guard tripped
    summary = json.loads((out / "summary.json").read_text())
    assert summary["aborted"] is True and "error rate" in summary["abort_reason"]
    assert summary["skipped"] >= 1                  # later jobs never spent money


def test_abort_on_verification_failure(tmp_path, monkeypatch):
    def unverified(case_path, agent, seed, out_root, max_tokens):
        return {"case": case_path.stem, "agent": agent, "seed": seed,
                "status": "ok", "verified": False,
                "score_row": {"status": "ok", "w_real": 1.0, "denominator": 2.0}}

    monkeypatch.setattr(pilot, "run_job", unverified)
    case = _write_config(tmp_path, "case_vfail", roles=_roles_block())
    out = tmp_path / "out"
    rc = pilot.main([
        "--cases", str(case), "--agents", "noop", "--seed-list", "1", "2", "3",
        "--workers", "1", "--out", str(out)])
    assert rc == 2
    summary = json.loads((out / "summary.json").read_text())
    assert "replay verification" in summary["abort_reason"]


def test_agent_seat_policy_specs():
    assert pilot.agent_seat_policy("greedy") == {"kind": "scripted_bilateral_ir"}
    assert pilot.agent_seat_policy("google/gemini-2.5-flash") == {
        "kind": "llm", "model": "google/gemini-2.5-flash"}
    # E-arm stochasticity suffix: temperature + sample land in the seat spec
    assert pilot.agent_seat_policy("google/gemini-2.5-flash@t0.7:s2") == {
        "kind": "llm", "model": "google/gemini-2.5-flash",
        "temperature": 0.7, "sample": 2}


# --- mute escalation ladder (2026-08-01: breaker must recover, not just drop) --

def test_mute_floor_ladder_escalates_then_gives_up(monkeypatch):
    from aeread import exchange_v1_pilot as p

    monkeypatch.delenv("OPENROUTER_MIN_COMPLETION_TOKENS", raising=False)
    # unset = the run had NO floor at all, so the first rung is the base one
    assert p._next_mute_floor() == 4096
    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "4096")
    assert p._next_mute_floor() == 8192
    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "8192")
    assert p._next_mute_floor() == 16384
    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "16384")
    assert p._next_mute_floor() == 32768
    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "32768")
    assert p._next_mute_floor() is None          # ladder exhausted -> give up
    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "99999")
    assert p._next_mute_floor() is None          # already above the ladder


def test_run_job_retries_once_at_a_higher_floor_on_mute_trip(monkeypatch, tmp_path):
    """A health trip must escalate the budget and re-run, not drop the episode."""
    from aeread import exchange_v1_pilot as p
    from aeread import exchange_v1_runner as runner

    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "4096")
    seen_floors = []

    def fake_run_v1(*a, **kw):
        seen_floors.append(os.environ.get("OPENROUTER_MIN_COMPLETION_TOKENS"))
        if len(seen_floors) == 1:
            raise runner.RunHealthError("mute circuit breaker: 9/12 EMPTY")
        raise RuntimeError("stop-after-retry")   # proves the retry happened

    monkeypatch.setattr(p, "seeded_case", lambda *a, **k: tmp_path / "c.json")
    monkeypatch.setattr(p, "agent_seat_policy", lambda a: {})
    monkeypatch.setattr(runner, "run_v1", fake_run_v1)

    row = p.run_job(tmp_path / "c.json", "some/model", 1200, tmp_path, 1200)
    assert seen_floors == ["4096", "8192"], seen_floors
    assert row["mute_retry_floor"] == 8192
    # env restored so the escalation never leaks into the next episode
    assert os.environ["OPENROUTER_MIN_COMPLETION_TOKENS"] == "4096"
