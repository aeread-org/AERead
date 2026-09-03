"""Regression coverage for ``docs/aucarena_codex_triage.md`` Finding 8:
``tests/test_aucarena_cases.py``'s own module-level
``pytest.skip(..., allow_module_level=True)`` collapses 19 QC-Gate-1 tests
into one silent ``1 skipped`` line the moment the pinned upstream
auction-arena checkout is absent (a hardcoded, developer-specific default
path), with zero signal in a plain CI log.

These tests exercise the real production path, not a shortcut: they spawn
``pytest`` as a real subprocess against the real
``tests/test_aucarena_cases.py`` file with a nonexistent upstream root, and
assert on the *actual* terminal behavior (exit code, printed text) --
never a locally re-derived assumption about what ``conftest.py``'s
``pytest_terminal_summary`` hook would do.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_aucarena_cases(*, qc_gate_required: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["AEREAD_AUCARENA_UPSTREAM_ROOT"] = f"/tmp/does_not_exist_{os.getpid()}"
    env.pop("AEREAD_TAU2_BRIDGE_REQUIRED", None)
    if qc_gate_required:
        env["AEREAD_AUCARENA_QC_GATE_REQUIRED"] = "1"
    else:
        env.pop("AEREAD_AUCARENA_QC_GATE_REQUIRED", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_aucarena_cases.py", "-q"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_missing_upstream_checkout_skips_quietly_by_default() -> None:
    """No behavior regression: a local contributor not working on this
    family's QC-Gate-1 tests still just gets a quiet skip, never a failure.
    (Exit code 5 is pytest's own "no tests were collected" status -- the
    whole module skips at collection time, so nothing runs; it is not a
    failure exit code.)"""
    result = _run_aucarena_cases(qc_gate_required=False)
    assert result.returncode in (0, 5)
    assert "1 skipped" in result.stdout


def test_missing_upstream_checkout_fails_loudly_when_the_gate_is_required() -> None:
    """``AEREAD_AUCARENA_QC_GATE_REQUIRED=1`` (CI, and any run meant to
    certify this family's QC-Gate-1 claims) turns that same silent skip
    into a failed run with the reason and a provisioning hint printed --
    the mechanism this repo already uses for tau2, extended to cover this
    family's own hardcoded, developer-specific upstream path."""
    result = _run_aucarena_cases(qc_gate_required=True)
    assert result.returncode != 0
    assert "upstream auction-arena QC gate required" in result.stdout
    assert "pinned upstream auction-arena checkout not found" in result.stdout
    assert "AEREAD_AUCARENA_UPSTREAM_ROOT" in result.stdout
