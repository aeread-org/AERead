"""Tests for the root ``conftest.py``'s ``AEREAD_ECONAGENT_BRIDGE_REQUIRED``
enforcement (docs/econagent_codex_triage.md finding 5).

``discover_bridge_python``/``_require_bridge()`` convert a missing upstream
bridge into a plain ``pytest.skip`` regardless of any requirement flag; the
enforcement that turns that skip into a failed run lives entirely in the
root ``conftest.py``'s ``pytest_terminal_summary`` hook, which only ever
fires on an actual pytest run's own terminal summary. There is no in-process
shortcut for exercising it -- these tests spawn a real, nested ``pytest``
subprocess against real test modules, so the assertion is made against the
genuine production path (the real ``_upstream_root()`` skip, the real hook,
the real exit status), never a hand-called stand-in for it.

Each nested run mixes a real econagent module that will skip entirely (the
upstream checkout is pointed at a directory that does not exist) with
``test_shared_runner_smoke.py``, which needs no bridge at all and always
passes -- a lone, fully-skipped module reports pytest's own "no tests
collected" exit status (5) regardless of any bridge-required enforcement,
which is not what a real, mixed suite run (this repo's actual usage) looks
like; mixing in a real passing module keeps these tests honest about the
"green run, but the fidelity tests didn't run" failure mode finding 5 names.
"""
from __future__ import annotations

import os
import subprocess
import sys

_NONEXISTENT_UPSTREAM_ROOT = "/tmp/aeread-econagent-bridge-enforcement-test-nonexistent"
_NESTED_TEST_FILES = (
    "tests/test_shared_runner_smoke.py",
    "tests/test_econagent_environment.py",
)


def _run_nested_pytest(*, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run real test modules under a real, separate pytest process, with the
    upstream checkout deliberately missing -- the real ``_upstream_root()``
    in ``tests/test_econagent_environment.py`` then raises the real,
    module-level ``pytest.skip`` production code already takes for a
    missing checkout, independent of whatever bridge happens to be
    provisioned on the machine actually running this outer test.
    """
    env = dict(os.environ)
    env["AEREAD_ECONAGENT_UPSTREAM_ROOT"] = _NONEXISTENT_UPSTREAM_ROOT
    env.pop("AEREAD_ECONAGENT_BRIDGE_REQUIRED", None)
    env.pop("AEREAD_TAU2_BRIDGE_REQUIRED", None)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", *_NESTED_TEST_FILES, "-q"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_missing_upstream_checkout_still_skips_cleanly_when_not_required() -> None:
    """Regression guard: the fix below must never surprise a local run that
    never set the requirement flag -- a missing bridge remains a plain,
    zero-exit skip by default."""
    result = _run_nested_pytest(extra_env={})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout


def test_a_missing_upstream_checkout_fails_the_run_when_econagent_bridge_is_required() -> None:
    """Finding 5 (docs/econagent_codex_triage.md): before the fix, the root
    conftest.py's ``pytest_terminal_summary`` hook recognized only
    ``AEREAD_TAU2_BRIDGE_REQUIRED`` and tau2-specific skip markers, so
    setting ``AEREAD_ECONAGENT_BRIDGE_REQUIRED=1`` with no usable upstream
    checkout still produced a skipped, zero-exit run -- a fidelity-
    certifying run (e.g. CI) could pass while econagent's own fidelity
    tests never ran at all. Now the same missing checkout, under the same
    flag, fails the run.
    """
    result = _run_nested_pytest(extra_env={"AEREAD_ECONAGENT_BRIDGE_REQUIRED": "1"})
    assert result.returncode != 0, result.stdout + result.stderr
    assert "upstream bridge required" in result.stdout
    assert "EconAgent" in result.stdout
    assert "pinned upstream EconAgent checkout not found" in result.stdout


def test_setting_only_the_tau2_flag_does_not_catch_a_missing_econagent_checkout() -> None:
    """Companion guard: the two families' own requirement flags/markers must
    stay independent -- tau2's own flag must never accidentally catch (or
    silently swallow) econagent's own skip, and vice versa."""
    result = _run_nested_pytest(extra_env={"AEREAD_TAU2_BRIDGE_REQUIRED": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
