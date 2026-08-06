"""Provider-free tests for the rLLM integration surface.

These cover the two things a first-time user hits: the advertised install path
has to find the case configs without a checkout, and a harness failure has to
be distinguishable from a genuine score of zero.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aeread.integrations import rllm_dataset


def test_build_rows_does_not_depend_on_cwd(tmp_path, monkeypatch):
    """`pip install aeread` then `--register` must work from any directory.

    The default glob used to be resolved against the process CWD, so the
    documented three-line recipe only worked when you happened to be standing
    in a repo checkout.
    """
    monkeypatch.chdir(tmp_path)
    rows = rllm_dataset.build_rows()
    assert rows, "default case set resolved to nothing outside a checkout"
    assert all(Path(r["case_path"]).is_file() for r in rows)


def test_build_rows_still_honours_an_explicit_glob(tmp_path):
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    (case_dir / "case99_fake.json").write_text("{}")
    rows = rllm_dataset.build_rows(str(case_dir / "case9*.json"), seeds=(1,))
    assert [r["uid"] for r in rows] == ["case99_fake:s1"]


def test_build_rows_reports_a_glob_that_matches_nothing(tmp_path):
    with pytest.raises(FileNotFoundError):
        rllm_dataset.build_rows(str(tmp_path / "nothing_here_*.json"))


# --------------------------------------------------------------------------
# A harness failure must not be reportable as a score of zero.
#
# rLLM counts an item as an error only when the episode's termination_reason
# is ERROR; otherwise it reads trajectories[0].reward and reports it as a
# score. An episode where the seat under test never got a model response was
# therefore indistinguishable from an episode where it played and realised no
# welfare: "Accuracy 0.0%, Errors 0". This is the mute-artifact failure mode
# wearing a different hat, so it gets a test.
# --------------------------------------------------------------------------

_STUB_TURNS = [{"observation": "you are agent a1", "response": "PUBLIC ACTION\n..."}]


def _flow_with_result(monkeypatch, result):
    from aeread.integrations import rllm_flow
    monkeypatch.setattr(rllm_flow, "run_episode", lambda *a, **k: result)
    task = {"case_path": "/nonexistent/case.json", "seed": 1200}
    config = type("Cfg", (), {"base_url": "http://x/v1", "model": "m"})()
    return rllm_flow.aeread_flow(task, config)


def test_harness_error_terminates_the_episode_as_an_error(monkeypatch):
    pytest.importorskip("rllm")
    from rllm.workflows.workflow import TerminationReason

    episode = _flow_with_result(monkeypatch, {
        "status": "harness_error", "aer": None, "w_real": None,
        "denominator": None, "score": {}, "turns": _STUB_TURNS,
    })

    assert episode.termination_reason == TerminationReason.ERROR
    message = (episode.metadata or {}).get("error", {}).get("message", "")
    assert "harness_error" in message
    assert episode.is_correct is False


def test_a_real_zero_score_is_not_an_error(monkeypatch):
    """AER can legitimately be 0.0 or negative. Only broken runs are errors."""
    pytest.importorskip("rllm")
    from rllm.workflows.workflow import TerminationReason

    episode = _flow_with_result(monkeypatch, {
        "status": "ok", "aer": 0.0, "w_real": 0.0, "denominator": 68.4,
        "score": {}, "turns": _STUB_TURNS,
    })

    assert episode.termination_reason != TerminationReason.ERROR
    assert not (episode.metadata or {}).get("error")
    assert episode.trajectories[0].reward == 0.0


def test_degenerate_denominator_is_an_error_not_a_zero(monkeypatch):
    """A denominator we could not compute is a missing measurement, not a score."""
    pytest.importorskip("rllm")
    from rllm.workflows.workflow import TerminationReason

    episode = _flow_with_result(monkeypatch, {
        "status": "ok", "aer": None, "w_real": 1.0, "denominator": 0.0,
        "score": {}, "turns": _STUB_TURNS,
    })

    assert episode.termination_reason == TerminationReason.ERROR


def test_evaluator_passes_the_error_through(monkeypatch):
    """The evaluator keeps returning a reward, but never claims a broken run scored."""
    from aeread.integrations.rllm_eval import aeread_evaluator

    broken = type("Ep", (), {"artifacts": {"status": "harness_error", "aer": None,
                                           "w_real": None, "denominator": None}})()
    out = aeread_evaluator(None, broken)
    assert out["is_correct"] is False
    assert out["metadata"]["status"] == "harness_error"
    assert out["metadata"]["error"]

    scored = type("Ep", (), {"artifacts": {"status": "ok", "aer": 0.031,
                                           "w_real": 2.1, "denominator": 68.4}})()
    out = aeread_evaluator(None, scored)
    assert out["reward"] == pytest.approx(0.031)
    assert not out["metadata"].get("error")
