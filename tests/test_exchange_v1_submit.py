"""D10 submission harness: exam pipeline, isolation boundary, replay verification.

Keyless: the frozen panel runs against the in-process fake provider; the
"foreign" candidate is a scripted object behind the text boundary. Claims under
test: the pipeline produces a complete submission dir with honest scorer tiers,
the candidate's actions record + replay without the candidate present, and the
candidate never sees anything an LLM seat wouldn't see.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402
from aeread import exchange_v1_roles as roles_mod  # noqa: E402
from aeread import exchange_v1_runner as runner  # noqa: E402
from aeread import exchange_v1_submit as submit  # noqa: E402
from aeread import llm_agent  # noqa: E402
from test_exchange_v1_roles import _roles_block, fake_provider  # noqa: E402,F401
from test_exchange_v1_runner import _write_config  # noqa: E402


class ScriptedCandidate:
    """A deterministic 'foreign' agent: text in, text out, logs its observations."""

    def __init__(self):
        self.observations: list[tuple[str, str]] = []

    def act(self, observation: str, phase: str) -> str:
        self.observations.append((phase, observation))
        marker = runner._sha256_bytes(observation.encode())[:8]
        if phase == "proposal":
            return f"PUBLIC ACTION\nI propose no trade this round. [{marker}]"
        if phase == "private_acceptance":
            return '{"approve": false, "reason": "candidate declines"}'
        return f"PUBLIC ACTION\nacknowledged. [{marker}]"


def _case(tmp_path, name):
    return _write_config(tmp_path, name, roles=_roles_block())


def _submission(tmp_path, cases, agent, **kwargs):
    return submit.run_submission(
        cases,
        agent,
        agent_label="scripted-candidate",
        out_root=tmp_path / "submissions",
        submission_id="sub_test",
        quiet=True,
        **kwargs,
    )


def test_submission_pipeline_end_to_end(tmp_path, fake_provider):
    cases = [_case(tmp_path, "case_a"), _case(tmp_path, "case_b")]
    agent = ScriptedCandidate()
    sub_dir = _submission(tmp_path, cases, agent)

    report = json.loads((sub_dir / "submission_report.json").read_text())
    assert report["cases_total"] == 2 and report["cases_ok"] == 2
    assert report["all_verified"] is True  # every case replayed byte-identically
    assert len(report["caseset_hash"]) == 64
    assert report["scorer_tiers"] == [submit.SCORER_TIER_D15]
    assert report["aggregate"]["score_mean"] is not None
    assert report["aggregate"]["note"] is None  # d15 is the official scorer, not provisional
    # the v2 headline: pooled sum(W_real)/sum(denominator), per denominator tier
    pooled = report["aggregate"]["pooled_aer_by_denominator_tier"]
    assert set(pooled) == {"wstar_fallback"}
    d15 = [r["score"] for r in report["cases"]]
    expected = sum(s["w_real"] for s in d15) / sum(s["denominator"] for s in d15)
    assert abs(pooled["wstar_fallback"] - expected) < 1e-9

    # the candidate's actions are manifest rows (origin=submitted, seat=under_test)
    run_dir = Path(report["cases"][0]["run_dir"])
    rows = [json.loads(l) for l in (run_dir / "inference_manifest.jsonl").read_text().splitlines()]
    submitted = [r for r in rows if r["origin"] == "submitted"]
    assert submitted and all(r["seat"] == "under_test" for r in submitted)
    assert all(r["model"] == "submitted:scripted-candidate" for r in submitted)
    assert all(r["agent_id"] == 1 for r in submitted)
    # funnel accounting stays consistent: llm rows == observer == call_records
    meta = json.loads((run_dir / "run_meta.json").read_text())
    assert meta["funnel_check"]["ok"] is True
    assert meta["funnel_check"]["submitted_rows"] == len(submitted)
    # per-seat split covers the candidate too
    assert "under_test" in meta["manifest_totals"]["by_seat"]


def test_candidate_sees_exactly_what_an_llm_seat_would_see(tmp_path, fake_provider):
    """Isolation boundary: for EVERY phase the candidate served, the observation
    equals the engine's own per-agent prompt (round 1, reconstructed from the
    trace), and each observation exposes exactly one private-context block."""
    config = _case(tmp_path, "case_iso")
    agent = ScriptedCandidate()
    _submission(tmp_path, [config], agent, verify_replay=False)

    phases_seen = {phase for phase, _ in agent.observations}
    assert {"communication", "proposal", "finalization"} <= phases_seen

    sub_dir = tmp_path / "submissions" / "sub_test"
    resolved = runner.resolve_config(sub_dir / "cases" / "case_iso.json")
    world = ex.make_world_from_config(resolved)
    trace_row = json.loads(
        (sub_dir / "runs" / "case_iso" / "trace.jsonl").read_text().splitlines()[0]
    )

    def _first(phase):
        return next(obs for p, obs in agent.observations if p == phase)

    # round 1 prompts are reconstructible exactly: initial world + trace texts
    assert _first("communication") == ex._freeform_communication_prompt(
        world, 1, 1, [], protocol=resolved.protocol
    )
    comm_texts = {int(k): v for k, v in trace_row["communication_texts"].items()}
    assert _first("proposal") == ex._freeform_proposal_prompt(
        world, 1, 1, [], comm_texts, protocol=resolved.protocol
    )
    transcript = ex.RoundTranscript(
        1,
        1,
        trace_row["proposal_text"],
        {int(k): v for k, v in trace_row["response_texts"].items()},
        "",
        comm_texts,
    )
    assert _first("finalization") == ex._freeform_finalize_prompt(
        world, 1, transcript, [], protocol=resolved.protocol
    )
    # exactly one private-context block — the candidate's own — in every observation
    for _, obs in agent.observations:
        assert obs.count("Private agent context") == 1


def test_tampered_submitted_snapshot_fails_replay(tmp_path, fake_provider):
    config = _case(tmp_path, "case_tamper")
    sub_dir = _submission(tmp_path, [config], ScriptedCandidate(), verify_replay=False)
    run_dir = sub_dir / "runs" / "case_tamper"
    rows = [json.loads(l) for l in (run_dir / "inference_manifest.jsonl").read_text().splitlines()]
    victim_key = next(r["replay_key"] for r in rows if r["origin"] == "submitted")
    (run_dir / "llm_cache" / f"{victim_key}.json").unlink()
    with pytest.raises(llm_agent.ReplayCacheMiss, match="submitted-agent action"):
        runner.run_v1(
            mode="replay",
            replay_from=run_dir,
            out_root=tmp_path / "replays",
            run_id="tamper_replay",
            quiet=True,
        )


def test_preflight_rejects_bad_cases_before_any_spend(tmp_path, fake_provider):
    """Static case defects fail the WHOLE submission up front — all defects
    listed, nothing run, no partial submission dir left behind."""
    good = _case(tmp_path, "case_good")
    bare = _write_config(tmp_path, "case_bare")  # no roles block
    missing = tmp_path / "case_missing.json"  # never written
    agent = ScriptedCandidate()
    with pytest.raises(runner.RunnerError, match="invalid case") as excinfo:
        _submission(tmp_path, [good, bare, missing], agent, verify_replay=False)
    # both defects reported at once; the good case was never executed
    assert "case_bare" in str(excinfo.value) and "case_missing" in str(excinfo.value)
    assert agent.observations == []
    assert not (tmp_path / "submissions" / "sub_test").exists()


def test_tampered_snapshot_content_fails_reverification(tmp_path, fake_provider):
    """A MODIFIED (not deleted) snapshot replays to a different trace — the
    audit tool must report the case as unverified."""
    config = _case(tmp_path, "case_mutate")
    sub_dir = _submission(tmp_path, [config], ScriptedCandidate(), verify_replay=False)
    assert submit.verify_submission(sub_dir) == {"case_mutate": True}  # pristine passes
    run_dir = sub_dir / "runs" / "case_mutate"
    rows = [json.loads(l) for l in (run_dir / "inference_manifest.jsonl").read_text().splitlines()]
    victim_key = next(r["replay_key"] for r in rows if r["origin"] == "submitted")
    victim = run_dir / "llm_cache" / f"{victim_key}.json"
    snapshot = json.loads(victim.read_text())
    snapshot["text"] = "PUBLIC ACTION\nTAMPERED: I propose to take everything."
    victim.write_text(json.dumps(snapshot))
    assert submit.verify_submission(sub_dir) == {"case_mutate": False}


def test_live_submitted_seat_without_agent_is_refused(tmp_path, fake_provider):
    config = _case(tmp_path, "case_noagent")
    raw = json.loads(Path(config).read_text())
    raw["roles"]["under_test"]["policy"] = {"kind": "submitted", "name": "ghost"}
    Path(config).write_text(json.dumps(raw))
    with pytest.raises(roles_mod.RoleConfigError, match="requires\\s+an agent instance"):
        runner.run_v1(
            config,
            mode="live_frozen",
            out_root=tmp_path / "runs",
            run_id="no_agent",
            quiet=True,
        )


def test_load_agent_rejects_malformed_spec():
    with pytest.raises(runner.RunnerError, match="module:Class"):
        submit.load_agent("not-an-entry-point")
