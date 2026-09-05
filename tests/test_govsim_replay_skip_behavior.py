"""Closes triage Finding 7: a missing pinned upstream checkout must only
skip ``tests/test_govsim_replay.py``'s individual bridge-gated tests, never
suppress collection of that module's bridge-independent tests (JSON
round-tripping, recorded-response ordering, mismatch reporting, harness
behavior).

Before the fix, ``tests/test_govsim_replay.py``'s import-time
``_upstream_root()`` called ``pytest.skip(..., allow_module_level=True)``
when the upstream marker was absent -- this raises during collection,
before pytest can generate any individual test item in that module at all,
so even explicitly requesting one bridge-independent test by its exact
node ID fails with "found no collectors" and reports the whole selection
as skipped, hiding whether that pure test would have passed or failed.

This is deliberately a subprocess-level test (spawns a real, separate
``pytest`` collecting only ``tests/test_govsim_replay.py``): the behavior
under test is COLLECTION-time behavior of that module under a specific
environment (``$AEREAD_GOVSIM_UPSTREAM_ROOT`` pointed at a path that does
not exist), which cannot be observed by importing the already-collected
module in-process.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_BRIDGE_INDEPENDENT_TEST = (
    "tests/test_govsim_replay.py::test_recorded_episode_round_trips_through_plain_json"
)
_BRIDGE_GATED_TEST = (
    "tests/test_govsim_replay.py::test_live_run_produces_sealed_evidence_that_verifies"
)


def test_a_missing_upstream_checkout_skips_only_the_bridge_gated_test(
    tmp_path: Path,
) -> None:
    nonexistent_root = tmp_path / "no-such-govsim-checkout"
    env = dict(os.environ)
    env["AEREAD_GOVSIM_UPSTREAM_ROOT"] = str(nonexistent_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "--color=no",
            _BRIDGE_INDEPENDENT_TEST,
            _BRIDGE_GATED_TEST,
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert "found no collectors" not in output, (
        "module-level skip suppressed collection of a bridge-independent "
        f"test entirely:\n{output}"
    )
    assert f"{_BRIDGE_INDEPENDENT_TEST} PASSED" in output, output
    assert f"{_BRIDGE_GATED_TEST} SKIPPED" in output, output
    assert "1 passed, 1 skipped" in output, output
