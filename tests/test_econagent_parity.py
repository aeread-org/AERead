"""Tests for the econagent_v1 oracle-vs-adapter parity harness (parity.py,
spec section 5).

Follows the same ``_require_bridge()``/skip convention as
``tests/test_econagent_environment.py``: tests that actually run a scenario
through both an independent oracle subprocess and the real adapter run for
real when a provisioned bridge interpreter is available, and are skipped
(never faked) otherwise.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from aeread_families.econagent_v1 import parity
from aeread_families.econagent_v1.cases import SCENARIOS
from aeread_families.econagent_v1.econagent_bridge import (
    EconAgentBridgeUnavailableError,
    discover_bridge_python,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ECONAGENT_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-econagent",
    )
    root = Path(candidate)
    if not (root / "config.yaml").is_file():
        pytest.skip(
            f"pinned upstream EconAgent checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except EconAgentBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _require_bridge() -> None:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)


def _pins() -> dict[str, Any]:
    path = Path("cases/econagent_v1/econagent.pilot.tiny4x6.seed0.json")
    return dict(json.loads(path.read_text(encoding="utf-8"))["payload"]["pins"])


def test_parity_spec_declares_exactly_the_three_fields_spec_section_5_names() -> None:
    field_ids = {field.field_id for field in parity.PARITY_SPEC.fields}
    assert field_ids == {"final_inventory_coin", "cumulative_tax_paid", "dense_log_length"}


def test_run_oracle_reports_a_typed_error_for_an_unreadable_interpreter() -> None:
    with pytest.raises(parity.ParityRunError):
        parity.run_oracle(
            upstream_root=UPSTREAM_ROOT,
            python_executable=Path("/nonexistent/python"),
            n_agents=4,
            episode_length=2,
            world_seed=0,
        )


# ---------------------------------------------------------------------------
# Bridge-gated: run both sides for real and require an exact match.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    SCENARIOS,
    ids=[scenario["case_id"] for scenario in SCENARIOS],
)
def test_adapter_matches_an_independent_oracle_for_every_pilot_scenario(scenario) -> None:
    """Spec section 5: per-agent terminal inventory, cumulative tax_paid, and
    dense_log length must match the oracle's exactly, for all three pilot
    scenarios."""
    _require_bridge()
    result = parity.run_scenario_parity(
        upstream_root=UPSTREAM_ROOT,
        python_executable=BRIDGE_PYTHON,
        scenario_id=scenario["case_id"],
        n_agents=scenario["n_agents"],
        episode_length=scenario["episode_length"],
        world_seed=scenario["world_seed"],
        pins=_pins(),
    )
    assert result.status == "ran", result.reason
    assert result.matched, (
        f"{scenario['case_id']} diverged from the oracle: "
        f"{result.report.mismatched_fields if result.report else None}"
    )


def test_adapter_diverges_from_an_oracle_run_with_a_different_seed() -> None:
    """Mutation check: two genuinely different runs must NOT report a match.

    Guards against :func:`parity.run_scenario_parity` being vacuously true --
    a passing parity report on matched seeds would be meaningless if this
    same comparison could not also detect two runs that really did diverge.
    """
    _require_bridge()
    oracle = parity.run_oracle(
        upstream_root=UPSTREAM_ROOT,
        python_executable=BRIDGE_PYTHON,
        n_agents=4,
        episode_length=3,
        world_seed=0,
    )
    adapted = parity.run_adapter(
        upstream_root=UPSTREAM_ROOT,
        n_agents=4,
        episode_length=3,
        world_seed=1,  # deliberately different seed
        pins=_pins(),
    )
    from aeread.shared_runner.parity import compare_projections

    report = compare_projections(oracle.to_dict(), adapted.to_dict(), parity.PARITY_SPEC)
    assert report.status == "mismatch"
    assert "final_inventory_coin" in report.mismatched_fields
