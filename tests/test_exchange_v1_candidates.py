"""Baseline candidates (no-op / random) through the D10 pipeline — keyless.

The candidates are ordinary submitted agents: they must run the full exam against the
fake-provider panel, replay byte-identically, and be deterministic (random = SEEDED)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_v1_submit as submit  # noqa: E402
from aeread.exchange_v1_candidates import NoOpCandidate, RandomCandidate  # noqa: E402
from test_exchange_v1_roles import _roles_block, fake_provider  # noqa: E402,F401
from test_exchange_v1_runner import _write_config  # noqa: E402


def _submit(tmp_path, agent, label, sid):
    config = _write_config(tmp_path, f"case_{sid}", roles=_roles_block())
    return submit.run_submission(
        [config], agent, agent_label=label,
        out_root=tmp_path / "submissions", submission_id=sid, quiet=True)


def test_noop_candidate_completes_and_verifies(tmp_path, fake_provider):
    sub_dir = _submit(tmp_path, NoOpCandidate(), "noop", "sub_noop")
    report = json.loads((sub_dir / "submission_report.json").read_text())
    assert report["cases_ok"] == 1 and report["all_verified"] is True
    assert report["scorer_tiers"] == [submit.SCORER_TIER_D15]


def test_random_candidate_is_seeded_deterministic(tmp_path, fake_provider):
    # same seed -> byte-identical action stream (a replayable exam requires it)
    a, b = RandomCandidate(seed=11), RandomCandidate(seed=11)
    phases = ["communication", "proposal", "response", "private_acceptance"] * 5
    assert [a.act("obs", p) for p in phases] == [b.act("obs", p) for p in phases]
    c = RandomCandidate(seed=12)
    assert [a.act("obs", p) for p in phases] != [c.act("obs", p) for p in phases]


def test_random_candidate_completes_and_verifies(tmp_path, fake_provider):
    sub_dir = _submit(tmp_path, RandomCandidate(seed=7), "random", "sub_random")
    report = json.loads((sub_dir / "submission_report.json").read_text())
    assert report["cases_ok"] == 1 and report["all_verified"] is True
