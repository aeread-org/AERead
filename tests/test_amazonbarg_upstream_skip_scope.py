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

Gate follow-up: ``_run_pytest`` used to copy the parent's ``os.environ``
verbatim into this deliberately checkout-less child. Run under the
``amazonbarg-fidelity`` CI job -- which sets
``AEREAD_AMAZONBARG_BRIDGE_REQUIRED=1`` and lists this very file -- that flag
leaked into the child, whose whole point is to run *without* the upstream
checkout: the child's own expected skips then tripped ``conftest.py``'s
skip-to-failure hook inside the child itself, turning its exit code from 0
into 1 and failing the two tests here that expect a skip
(``test_an_upstream_dependent_shim_test_skips_individually_not_the_whole_module``
and ``test_running_the_whole_pure_and_impure_mix_reports_both_outcomes_honestly``).
``_run_pytest`` now strips every ``AEREAD_*_BRIDGE_REQUIRED`` flag from the
child's environment; see
``test_the_checkout_less_child_never_inherits_a_bridge_required_flag`` below.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_pytest(*node_ids: str, upstream_root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["AEREAD_AMAZONBARG_UPSTREAM_ROOT"] = str(upstream_root)
    # This child never gets a real upstream checkout (that is the whole point
    # of this module), so it must never be asked to enforce *any* family's
    # bridge -- inheriting a *_BRIDGE_REQUIRED flag from the parent run (e.g.
    # the amazonbarg-fidelity CI job, which sets exactly this one) would turn
    # the child's own expected skips into a hard failure.
    for key in [k for k in env if k.startswith("AEREAD_") and k.endswith("_BRIDGE_REQUIRED")]:
        env.pop(key, None)
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


def test_the_checkout_less_child_never_inherits_a_bridge_required_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate follow-up regression: with ``AEREAD_AMAZONBARG_BRIDGE_REQUIRED=1``
    set in the parent process -- exactly what the ``amazonbarg-fidelity`` CI
    job does while listing this very file -- ``_run_pytest``'s checkout-less
    child must still exit 0 and report its expected skip, not fail because it
    inherited a flag telling it to enforce a bridge it deliberately has no
    checkout for."""
    monkeypatch.setenv("AEREAD_AMAZONBARG_BRIDGE_REQUIRED", "1")
    missing_root = tmp_path / "no-such-amazonbarg-checkout"
    result = _run_pytest(
        "tests/test_amazonbarg_shim.py::test_import_parse_reply_delegates_upstreams_own_three_field_grammar",
        upstream_root=missing_root,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "1 skipped" in combined, combined
