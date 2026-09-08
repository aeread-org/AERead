"""Regression coverage for the repo-root ``conftest.py``'s
``AEREAD_STEER_FIXTURES_REQUIRED`` mechanism (docs/steer_codex_triage.md
finding 5: "silent module skips").

Every one of the 6 steer test modules module-level-skips its entire
contents when the flattened cache (or, for ``test_steer_cases.py``, the
pinned upstream checkout / bridge interpreter) is missing. Reproduced
empirically by the triage: with ``AEREAD_STEER_DATA_ROOT`` pointed at a
nonexistent directory, running the steer suite ALONE gives ``6 skipped`` at
pytest's "nothing ran" exit code 5 -- but run alongside any other passing
test file (the normal way a full suite runs), the picture changes
completely: ``N passed, 6 skipped`` at exit code 0, with nothing in the
exit code distinguishing "steer's tests ran and passed" from "steer's
tests never ran at all".

These tests spawn a REAL pytest subprocess against the REAL steer test
modules (never a synthetic stand-in) to prove the fix closes exactly that
gap, in exactly that multi-module shape.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_steer_suite_with_missing_cache(*, required: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["AEREAD_STEER_DATA_ROOT"] = str(REPO_ROOT / "tests" / "_nonexistent_steer_cache_dir")
    if required:
        env["AEREAD_STEER_FIXTURES_REQUIRED"] = "1"
    else:
        env.pop("AEREAD_STEER_FIXTURES_REQUIRED", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_steer_measurement.py",
            "tests/test_case_catalog.py",
            "-q",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_missing_steer_cache_is_silently_green_by_default_in_a_multi_module_run() -> None:
    """The exact shape the triage reproduced: without the opt-in env var, a
    missing cache is a legitimate, quiet skip for a contributor working on
    something else -- exit code 0, never surprising a local run."""
    completed = _run_steer_suite_with_missing_cache(required=False)
    assert completed.returncode == 0
    assert "skipped" in completed.stdout


def test_a_missing_steer_cache_fails_the_run_when_fixtures_are_required() -> None:
    """The fix: with $AEREAD_STEER_FIXTURES_REQUIRED=1 (CI, and any run
    meant to certify fidelity), the exact same multi-module invocation that
    was silently green above now fails, and says why."""
    completed = _run_steer_suite_with_missing_cache(required=True)
    assert completed.returncode != 0
    assert "steer fixtures required" in completed.stdout
    assert "flattened cache not built yet at" in completed.stdout
