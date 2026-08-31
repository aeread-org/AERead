"""Tests for the tau3.retail component-level pilot parity harness (parity.py,
spec section 8).

Follows the same ``_bridge()``/skip convention as
``tests/test_tau3_retail_environment.py``: pure structural/error-path tests
run everywhere; tests that actually execute gold actions through both
upstream and the adapter run for real when a pinned upstream Python
interpreter is provisioned, and are skipped (never faked) otherwise.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aeread_families.tau3_retail import parity
from aeread_families.tau3_retail.cases import PILOT_UPSTREAM_TASK_IDS
from aeread_families.tau3_retail.tau2_bridge import (
    Tau2Bridge,
    Tau2BridgeUnavailableError,
    discover_bridge_python,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_TAU2_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-tau2",
    )
    root = Path(candidate)
    marker = root / "data" / "tau2" / "domains" / "retail" / "tasks.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream tau2-bench checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent. Without this flag pytest treats a
            # module-level skip as an error and the whole file fails to
            # collect -- which is what CI hit, since CI has no checkout.
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except Tau2BridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> Tau2Bridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return Tau2Bridge(python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT)


# ---------------------------------------------------------------------------
# Pure, no bridge: the parity spec's own shape, and typed error handling.
# ---------------------------------------------------------------------------


def test_parity_spec_declares_exactly_the_components_the_task_asks_to_compare() -> None:
    field_ids = tuple(field.field_id for field in parity.PARITY_SPEC.fields)
    assert field_ids == (
        "initial_database",
        "ordered_tool_calls",
        "ordered_tool_results",
        "final_database",
        "db_reward_component",
        "nl_judge_inputs",
    )


def test_component_result_to_dict_is_typed_available_or_typed_unavailable() -> None:
    available = parity.ComponentResult(True, {"a": 1})
    unavailable = parity.ComponentResult(False, reason="no gold actions")

    assert available.to_dict() == {"available": True, "value": {"a": 1}}
    assert unavailable.to_dict() == {"available": False, "reason": "no gold actions"}


def test_pilot_ids_are_exactly_the_18_documented_pilot_tasks() -> None:
    assert len(PILOT_UPSTREAM_TASK_IDS) == 18
    assert len(set(PILOT_UPSTREAM_TASK_IDS)) == 18


def test_run_pilot_task_reports_a_typed_error_rather_than_raising_for_a_missing_case() -> None:
    """A task id with no checked-in case file must not raise -- and must not
    require touching the bridge to report why."""
    result = parity.run_pilot_task(
        bridge=None,  # never dereferenced: the failure happens before any bridge call
        upstream_root=UPSTREAM_ROOT,
        task_id="not-a-real-task-id",
    )

    assert result.status == "error"
    assert "no checked-in case file" in result.reason
    assert result.report is None
    assert result.upstream_projection is None
    assert result.adapted_projection is None


def test_run_pilot_reports_every_task_as_skipped_when_the_bridge_is_unavailable() -> None:
    report = parity.run_pilot(
        bridge=None,
        upstream_root=UPSTREAM_ROOT,
        task_ids=("14", "53", "73"),
        bridge_unavailable_reason="no pinned interpreter provisioned in this environment",
    )

    assert report.summary() == {
        "total": 3,
        "ran": 0,
        "matched": 0,
        "mismatched": 0,
        "skipped": 3,
        "errored": 0,
    }
    assert all(result.status == "skipped" for result in report.results)
    assert all(
        result.reason == "no pinned interpreter provisioned in this environment"
        for result in report.results
    )


# ---------------------------------------------------------------------------
# Bridge-gated: real component-level parity for representative pilot tasks.
# ---------------------------------------------------------------------------


def test_pilot_task_73_unjudged_single_action_task_matches_component_by_component() -> None:
    bridge = _bridge()

    result = parity.run_pilot_task(bridge=bridge, upstream_root=UPSTREAM_ROOT, task_id="73")

    assert result.status == "ran"
    assert result.report is not None
    assert result.report.status == "match"
    assert result.report.mismatched_fields == ()
    # Task 73 has no non-empty nl_assertions -- both sides must agree the
    # judged component is explicitly, typedly unavailable, never omitted.
    assert result.upstream_projection["nl_judge_inputs"] == {
        "available": False,
        "reason": (
            "task has no non-empty nl_assertions; upstream's NL judge "
            "never fires for it (spec section 7)"
        ),
    }
    assert result.adapted_projection["nl_judge_inputs"] == result.upstream_projection[
        "nl_judge_inputs"
    ]
    assert result.upstream_projection["db_reward_component"]["value"] == 1.0
    assert result.adapted_projection["db_reward_component"]["value"] == 1.0


def test_pilot_task_108_judged_task_matches_including_judge_input_component() -> None:
    bridge = _bridge()

    result = parity.run_pilot_task(bridge=bridge, upstream_root=UPSTREAM_ROOT, task_id="108")

    assert result.status == "ran"
    assert result.report is not None
    assert result.report.status == "match"
    assert result.report.mismatched_fields == ()
    nl_inputs = result.upstream_projection["nl_judge_inputs"]
    assert nl_inputs["available"] is True
    assert nl_inputs["value"]["model"] == "gpt-4.1-2025-04-14"
    assert (
        result.adapted_projection["nl_judge_inputs"]["value"]["model"]
        == nl_inputs["value"]["model"]
    )
    # The judge prompt content itself -- not just its presence -- must
    # match between the two independently executed trajectories.
    assert (
        result.upstream_projection["nl_judge_inputs"]["value"]["messages"]
        == result.adapted_projection["nl_judge_inputs"]["value"]["messages"]
    )


def test_pilot_task_ordered_tool_calls_actually_reflect_the_tasks_own_gold_actions() -> None:
    """A task with more than one gold action -- proves the component is a
    genuine ordered list, not just a length-1 coincidence."""
    bridge = _bridge()

    result = parity.run_pilot_task(bridge=bridge, upstream_root=UPSTREAM_ROOT, task_id="91")

    assert result.status == "ran"
    calls = result.upstream_projection["ordered_tool_calls"]["value"]
    assert len(calls) == 2
    assert result.adapted_projection["ordered_tool_calls"]["value"] == calls
    assert result.report.status == "match"
