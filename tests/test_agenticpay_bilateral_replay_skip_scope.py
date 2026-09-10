"""Regression coverage for review finding 1 (docs/agenticpay_migration_review.md):
a missing pinned AgenticPay upstream checkout must skip only the
bridge-gated tests it actually affects, never suppress collection of a whole
module wholesale -- and, because ``tests/test_shared_runner_scoring_contract.py``
imports ``tests/test_agenticpay_bilateral_replay.py``'s helpers at module
scope, that blast radius used to reach a module this family never touches.

Before the fix, ``tests/test_agenticpay_bilateral_replay.py``'s import-time
``_upstream_root()`` called ``pytest.skip(..., allow_module_level=True)`` when
the pinned upstream checkout marker file was absent. That raises during
COLLECTION, before pytest can generate any individual test item in that
module at all, so:

1. Every bridge-INDEPENDENT test in ``test_agenticpay_bilateral_replay.py``
   itself (JSON round-tripping, recorded-response ordering, mismatch
   reporting) skipped too, even though none of them touches the upstream
   checkout.
2. Importing ``test_agenticpay_bilateral_replay`` from
   ``tests/test_shared_runner_scoring_contract.py`` (to reuse its
   ``_bridge``/``_case``/``_cell``/``_script`` helpers) re-raised the same
   ``Skipped`` exception during THAT module's own collection, skipping the
   entire shared protocol test file -- including the always-on
   ``test_every_registered_family_obeys_the_scoring_contract`` test that
   covers housing, procurement_allocation, procurement_grounding,
   commercial_state_calibration, and the kernel-owned reference family, none
   of which has anything to do with AgenticPay's upstream checkout.

Mirrors ``tests/test_govsim_replay_skip_behavior.py``'s and
``tests/test_amazonbarg_upstream_skip_scope.py``'s identical convention and,
like them, is deliberately a subprocess-level test: the behavior under test
is pytest's own COLLECTION-time behavior of these modules under a specific
environment, which cannot be observed by importing an already-collected
module in-process.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_NONEXISTENT_UPSTREAM_ROOT = "/tmp/aeread-agenticpay-replay-skip-scope-test-nonexistent"

_BRIDGE_INDEPENDENT_TEST = (
    "tests/test_agenticpay_bilateral_replay.py::"
    "test_recorded_episode_round_trips_through_plain_json"
)
_BRIDGE_GATED_TEST = (
    "tests/test_agenticpay_bilateral_replay.py::"
    "test_a_basic_negotiation_runs_end_to_end_with_sealed_evidence"
)
_SHARED_PROTOCOL_TEST = (
    "tests/test_shared_runner_scoring_contract.py::"
    "test_every_registered_family_obeys_the_scoring_contract"
)


def _run_pytest(*node_ids: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["AEREAD_AGENTICPAY_UPSTREAM_ROOT"] = _NONEXISTENT_UPSTREAM_ROOT
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "--color=no", *node_ids],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_missing_upstream_checkout_skips_only_the_bridge_gated_replay_test() -> None:
    result = _run_pytest(_BRIDGE_INDEPENDENT_TEST, _BRIDGE_GATED_TEST)
    output = result.stdout + result.stderr
    assert "found no collectors" not in output, (
        "module-level skip suppressed collection of a bridge-independent "
        f"test in test_agenticpay_bilateral_replay.py entirely:\n{output}"
    )
    assert f"{_BRIDGE_INDEPENDENT_TEST} PASSED" in output, output
    assert f"{_BRIDGE_GATED_TEST} SKIPPED" in output, output
    assert "1 passed, 1 skipped" in output, output


def test_a_missing_agenticpay_upstream_checkout_does_not_skip_the_shared_protocol_module() -> None:
    """The blast-radius half of finding 1: importing
    ``test_agenticpay_bilateral_replay``'s helpers from
    ``test_shared_runner_scoring_contract.py`` must never make a missing
    AgenticPay checkout skip that module's own always-on protocol test,
    which exercises four OTHER already-migrated families plus the
    kernel-owned reference family and has nothing to do with AgenticPay's
    upstream checkout.
    """
    result = _run_pytest(_SHARED_PROTOCOL_TEST)
    output = result.stdout + result.stderr
    assert "found no collectors" not in output, (
        "a missing AgenticPay upstream checkout suppressed collection of "
        "the shared scoring-contract protocol test -- every other migrated "
        f"family's coverage was skipped along with it:\n{output}"
    )
    assert f"{_SHARED_PROTOCOL_TEST} PASSED" in output, output
    assert result.returncode == 0, output
