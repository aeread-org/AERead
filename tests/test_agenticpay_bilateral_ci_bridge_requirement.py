"""Second-review regression (Codex finding 6): CI must require the agenticpay
bridge, or upstream-fidelity assertions can silently skip while the run stays
green.

``conftest.py``'s ``pytest_terminal_summary`` hook already converts a bridge-gated
skip into a hard failure -- but only when the matching
``AEREAD_<FAMILY>_BRIDGE_REQUIRED`` environment variable is set ("Off by default so
it never surprises a local run", per that module's own docstring). Nothing enforces
that *some* run in this project's CI actually opts in: as checked in,
``.github/workflows/ci.yml`` ran ``pytest tests/ -q`` with no bridge-required
variable set at all, so a plain CI run could report success (green) even though
every agenticpay upstream-fidelity test (``test_agenticpay_bilateral_cases.py``,
``test_agenticpay_bilateral_environment.py``, ``test_agenticpay_bilateral_
measurement.py``, ``test_agenticpay_bilateral_replay.py``) silently skipped for want
of a provisioned bridge.

This test never actually runs GitHub Actions (this suite is provider-free/offline,
and there is no local runner for it) -- it inspects the checked-in workflow text
directly, so it cannot prove the job it finds actually succeeds end to end. What it
can and does prove is that the opt-in switch is wired on for this family and that
the fidelity test files are actually invoked under it, so this protection cannot
silently regress (e.g. someone deleting the job, or the job drifting to run a
different, non-fidelity test selection) without this test failing first.
"""
from __future__ import annotations

from pathlib import Path

_CI_WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"

_FIDELITY_TEST_FILES = (
    "tests/test_agenticpay_bilateral_cases.py",
    "tests/test_agenticpay_bilateral_environment.py",
    "tests/test_agenticpay_bilateral_measurement.py",
    "tests/test_agenticpay_bilateral_replay.py",
)


def _workflow_text() -> str:
    assert _CI_WORKFLOW.is_file(), f"CI workflow not found at {_CI_WORKFLOW}"
    return _CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_sets_the_agenticpay_bridge_required_switch() -> None:
    text = _workflow_text()
    assert "AEREAD_AGENTICPAY_BRIDGE_REQUIRED" in text, (
        "no CI step sets AEREAD_AGENTICPAY_BRIDGE_REQUIRED: without it, "
        "conftest.py's skip-to-failure hook stays off by default, and CI can go "
        "green while every agenticpay upstream-fidelity assertion silently skipped "
        "(second-review Codex finding 6)"
    )


def test_ci_actually_runs_every_agenticpay_fidelity_test_file_under_the_bridge_gate() -> None:
    text = _workflow_text()
    for test_file in _FIDELITY_TEST_FILES:
        assert test_file in text, (
            f"no CI job invokes {test_file}; requiring the bridge is meaningless if "
            "the gated job never actually runs this family's fidelity tests"
        )
