"""Component parity test for the alympics.wac adapter (spec section 5).

Required per the "never reimplement" rule: this is the independent-oracle
cross-check (Gate 2 requirement 1) for ``alympics.wac.reference_baseline``,
comparing the real, kernel-facing adapter path against a *second, separately
constructed* upstream ``waterAllocation`` instance driven directly and
continuously, entirely outside the kernel's scheduler/state machinery. See
``src/aeread_families/alympics_wac/parity.py``'s module docstring for the
full rationale (mirrors ``tests/test_tau3_retail_parity.py``'s role, adapted
to a "no bridge" in-process adapter -- see that module's docstring for why
this one carries no subprocess/CLI shape).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aeread_families.alympics_wac.parity import run_reference_baseline_parity


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ALYMPICS_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-alympics",
    )
    root = Path(candidate)
    marker = root / "src" / "waterAllocation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream Alympics checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()


def test_reference_baseline_adapter_matches_a_second_continuous_upstream_instance() -> None:
    report = run_reference_baseline_parity(UPSTREAM_ROOT)

    assert report.matched, (
        f"parity mismatch on {report.report.mismatched_fields}: "
        f"adapter={report.adapter_projection} "
        f"upstream_direct={report.upstream_direct_projection}"
    )
    assert report.report.status == "match"
    assert not report.report.mismatched_fields


def test_parity_projections_are_non_trivial_not_a_vacuous_all_zero_match() -> None:
    """Guard against a parity check that would trivially "match" only
    because both sides produced empty/degenerate projections (the same
    lesson as the project's "skips hide unrun claims" finding, applied to
    a parity report instead of a skipped test)."""
    report = run_reference_baseline_parity(UPSTREAM_ROOT)

    balances = report.adapter_projection["final_balance_by_seat"]
    assert any(value > 0 for value in balances.values())
    assert any(len(round_winners) > 0 for round_winners in report.adapter_projection["winners_by_round"])
    assert len(report.adapter_projection["winners_by_round"]) == 20
