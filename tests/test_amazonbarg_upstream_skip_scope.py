"""Regression coverage for codex-review finding 6: tests silently skip wholesale.

Every ``tests/test_amazonbarg_*.py`` module computed its own ``UPSTREAM_ROOT``
at *module import time* and called ``pytest.skip(..., allow_module_level=True)``
when the pinned upstream checkout was not found -- which skips every test in
that file, including pure declaration/logic tests that never touch
``upstream_root`` at all (e.g. ``test_amazonbarg_measurement.py``'s five
``build_*_leaf`` tests). On a machine without the checkout, a green run's
"106/106 passed" headline figure silently became "0 ran, N skipped" for tests
that had nothing to do with the checkout in the first place.

This module drives the real, installed pytest CLI as a subprocess (the actual
production test-collection path -- not a shortcut that imports pytest
internals directly) against a deliberately nonexistent
``AEREAD_AMAZONBARG_UPSTREAM_ROOT``, and asserts that a genuinely pure test
still runs and passes while a genuinely upstream-dependent test in the same
module is skipped individually -- never the whole module collapsing to one
skip.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_pytest(*node_ids: str, upstream_root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["AEREAD_AMAZONBARG_UPSTREAM_ROOT"] = str(upstream_root)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *node_ids],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_a_pure_shim_test_still_passes_without_the_upstream_checkout(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "no-such-amazonbarg-checkout"
    result = _run_pytest(
        "tests/test_amazonbarg_shim.py::test_global_miss_counter_starts_at_zero_in_a_fresh_process",
        upstream_root=missing_root,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "1 passed" in combined, combined


def test_an_upstream_dependent_shim_test_skips_individually_not_the_whole_module(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "no-such-amazonbarg-checkout"
    result = _run_pytest(
        "tests/test_amazonbarg_shim.py::test_import_parse_reply_delegates_upstreams_own_three_field_grammar",
        upstream_root=missing_root,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "1 skipped" in combined, combined


def test_a_pure_measurement_leaf_test_still_passes_without_the_upstream_checkout(
    tmp_path: Path,
) -> None:
    """The exact reproduction named in the codex triage: the five pure
    ``build_*_leaf`` declaration tests in ``test_amazonbarg_measurement.py``
    touch no upstream checkout at all, yet used to skip along with every
    other test in that file."""
    missing_root = tmp_path / "no-such-amazonbarg-checkout"
    result = _run_pytest(
        "tests/test_amazonbarg_measurement.py::test_build_leaves_declares_exactly_five_leaves_every_time",
        upstream_root=missing_root,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "1 passed" in combined, combined


def test_running_the_whole_pure_and_impure_mix_reports_both_outcomes_honestly(
    tmp_path: Path,
) -> None:
    """A single run over the whole file must report a genuine mix -- some
    passed (the pure tests), some skipped (the upstream-dependent ones) --
    never a single collapsed "N skipped" for the entire module."""
    missing_root = tmp_path / "no-such-amazonbarg-checkout"
    result = _run_pytest("tests/test_amazonbarg_shim.py", upstream_root=missing_root)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "passed" in combined, combined
    assert "skipped" in combined, combined
