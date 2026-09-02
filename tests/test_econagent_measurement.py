"""Tests for the econagent_v1 measurement declarations (measurement.py).

Two kinds of coverage, mirroring ``tests/test_tau3_retail_measurement.py``'s
split:

* Pure, provider-free, bridge-free tests -- leaf-declaration rules (spec
  section 2) and the budget-identity/macro-trajectory arithmetic against
  small, hand-verifiable, synthetic ``dense_log`` fixtures (QC Gate 2
  requirement 1: "cross-check deterministic oracles against ... hand-
  verifiable goldens"). These include deliberate mutation checks -- a
  fabricated violation injected into an otherwise-passing fixture -- so a
  green suite here cannot hide a vacuously-always-passing check.
* Bridge-gated tests that run a real tiny episode through the pinned
  upstream engine and score it for real, following
  ``tests/test_econagent_environment.py``'s ``_require_bridge()`` skip
  convention: they run for real when a provisioned bridge interpreter
  resolves, and skip (never faked) otherwise.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.econagent_v1 import measurement as m
from aeread_families.econagent_v1.econagent_bridge import (
    EconAgentBridge,
    EconAgentBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econagent_v1.environment import EconAgentV1Plugin, register_plugin


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


def _case(case_id: str = "econagent.pilot.tiny4x6.seed0") -> CaseManifest:
    path = Path("cases/econagent_v1") / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pins() -> dict[str, Any]:
    return dict(_case().payload["pins"])


def _run_episode_and_score(case_id: str) -> tuple[dict[str, Any], m.EconAgentV1Scorer, int, int]:
    """Run one real episode end to end and return (terminal, scorer, n_agents, world_period)."""
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    case = _case(case_id)
    family_case = plugin.validate_payload(case.payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, cell=None)
    n_agents = family_case["scenario"]["n_agents"]
    while state["termination"] is None:
        actors = plugin.eligible_actors(family_case, state, phase)
        actions = {
            seat: plugin.parse_action(family_case, state, seat, phase, {"acknowledge": True})
            for seat in actors
        }
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
    terminal = plugin.terminal(family_case, state)
    scorer = plugin.build_scorer(family_case)
    world_period = terminal["final_world"]["period"]
    return terminal, scorer, n_agents, world_period


# ---------------------------------------------------------------------------
# Leaf declaration rules -- pure, no bridge.
# ---------------------------------------------------------------------------


def test_build_leaves_declares_exactly_three_separately_labelled_leaves() -> None:
    pins = _pins()
    leaves = m.build_leaves(pins)

    assert len(leaves) == 3
    assert [leaf.leaf_id for leaf in leaves] == [
        m.BUDGET_IDENTITY_LEAF_ID,
        m.TAX_BRACKET_LEAF_ID,
        m.MACRO_TRAJECTORY_LEAF_ID,
    ]
    # composition_kind is fixed to "leaf" by the kernel itself -- never a
    # blended/weighted scalar (spec section 2's "no weighted scalar").
    for leaf in leaves:
        assert leaf.composition_kind == "leaf"


def test_budget_identity_leaf_is_a_deterministic_rule_constraint_state_invariant() -> None:
    leaf = m.build_budget_identity_leaf(_pins())
    assert leaf.verifier.verifier_family == "rule_constraint"
    assert leaf.verifier.evaluation_class == "deterministic"
    assert leaf.verifier.reference.reference_kind == "state_invariant"
    assert leaf.estimand.direction == "none"


def test_tax_bracket_leaf_is_a_deterministic_rule_constraint_constraint_satisfaction() -> None:
    leaf = m.build_tax_bracket_leaf(_pins())
    assert leaf.verifier.verifier_family == "rule_constraint"
    assert leaf.verifier.evaluation_class == "deterministic"
    assert leaf.verifier.reference.reference_kind == "constraint_satisfaction"


def test_macro_trajectory_leaf_is_comparative_never_objective_reference() -> None:
    # Spec section 2's one framing rule this module must not violate: no
    # declared optimum, no bound, no comparator this pass.
    leaf = m.build_macro_trajectory_leaf(_pins())
    assert leaf.verifier.verifier_family == "comparative"
    assert leaf.verifier.reference.reference_kind == "baseline_delta"
    assert leaf.verifier.objective_scope is None
    assert leaf.estimand.direction == "none"


def test_build_scorer_binds_leaves_to_the_case_pins() -> None:
    scenario = _case().payload["scenario"]
    pins = _pins()
    scorer = m.build_scorer(scenario, pins)
    assert scorer.scenario == scenario
    assert scorer.pins == pins
    assert scorer.budget_identity_leaf.leaf_id == m.BUDGET_IDENTITY_LEAF_ID
    assert scorer.tax_bracket_leaf.leaf_id == m.TAX_BRACKET_LEAF_ID
    assert scorer.macro_trajectory_leaf.leaf_id == m.MACRO_TRAJECTORY_LEAF_ID


# ---------------------------------------------------------------------------
# Synthetic, hand-verifiable dense_log fixtures -- pure arithmetic, no bridge.
# ---------------------------------------------------------------------------


def _agent_state(inventory_coin: float, consumption_coin: float, job: str = "Baker") -> dict[str, Any]:
    return {
        "inventory": {"Coin": inventory_coin},
        "consumption": {"Coin": consumption_coin},
        "endogenous": {"job": job},
    }


def _synthetic_dense_log() -> dict[str, Any]:
    """Two agents, two months, world_period=3 (so neither month is a boundary).

    Every inventory value is hand-derived from the identity itself
    (``inv[t] = inv[t-1] + income - tax + lump_sum - consumption``), so the
    residual is exactly 0 for both agents on both months -- a
    hand-verifiable "successful" fixture.
    """
    return {
        "states": [
            {"0": _agent_state(100.0, 0.0), "1": _agent_state(200.0, 0.0)},
            {"0": _agent_state(125.0, 20.0), "1": _agent_state(240.0, 30.0)},
            {"0": _agent_state(154.0, 25.0), "1": _agent_state(283.0, 35.0)},
        ],
        "PeriodicTax": [
            {
                "0": {"income": 50.0, "tax_paid": 10.0, "lump_sum": 5.0, "marginal_rate": 0.2},
                "1": {"income": 80.0, "tax_paid": 15.0, "lump_sum": 5.0, "marginal_rate": 0.2},
            },
            {
                "0": {"income": 60.0, "tax_paid": 12.0, "lump_sum": 6.0, "marginal_rate": 0.2},
                "1": {"income": 90.0, "tax_paid": 18.0, "lump_sum": 6.0, "marginal_rate": 0.2},
            },
        ],
        "world": [
            {"Price": 100.0},
            {"Price": 101.0},
            {"Price": 103.0},
        ],
    }


def _synthetic_month_actions() -> list[dict[str, list[float]]]:
    """Both agents take a nonzero labor and consumption action every month.

    Matches ``_synthetic_dense_log``'s own assumption that every recorded
    ``consumption["Coin"]`` value is fresh, not stale -- see
    ``test_score_budget_identity_ignores_a_stale_consumption_field_on_a_noop_month``
    for the fixture that exercises the opposite case.
    """
    return [
        {"0": [1, 1], "1": [1, 1]},
        {"0": [1, 1], "1": [1, 1]},
    ]


def test_compute_budget_identity_residuals_is_hand_verifiable() -> None:
    dense_log = _synthetic_dense_log()
    residuals = m.compute_budget_identity_residuals(
        dense_log, n_agents=2, world_period=3, month_actions=_synthetic_month_actions()
    )

    assert len(residuals) == 4  # 2 agents x 2 months
    for entry in residuals:
        assert entry.residual == pytest.approx(0.0, abs=1e-9)
        assert entry.is_boundary_month is False  # world_period=3, months 1/2 never hit it


def test_compute_budget_identity_residuals_flags_a_saving_interest_boundary_month() -> None:
    dense_log = _synthetic_dense_log()
    # world_period=2: month 2 is a boundary month. Bump agent 0's month-2
    # inventory by exactly 3.08 above the identity's closing balance --
    # exactly what a positive saving_interest term would look like.
    dense_log["states"][2]["0"]["inventory"]["Coin"] = 154.0 + 3.08

    residuals = m.compute_budget_identity_residuals(
        dense_log, n_agents=2, world_period=2, month_actions=_synthetic_month_actions()
    )
    by_key = {(entry.month, entry.agent_id): entry for entry in residuals}

    assert by_key[(1, "0")].is_boundary_month is False
    assert by_key[(1, "0")].residual == pytest.approx(0.0, abs=1e-9)
    assert by_key[(2, "0")].is_boundary_month is True
    assert by_key[(2, "0")].residual == pytest.approx(3.08, abs=1e-9)
    # Agent 1's month-2 state was never mutated -- residual stays 0, but
    # the month is still flagged as a boundary month (a legitimate 0
    # saving-interest outcome is not a violation).
    assert by_key[(2, "1")].is_boundary_month is True
    assert by_key[(2, "1")].residual == pytest.approx(0.0, abs=1e-9)


def test_score_budget_identity_passes_on_the_synthetic_fixture() -> None:
    leaf = m.build_budget_identity_leaf(_pins())
    score = m.score_budget_identity(
        leaf,
        dense_log=_synthetic_dense_log(),
        n_agents=2,
        world_period=3,
        month_actions=_synthetic_month_actions(),
    )
    assert score.status == "ok"
    assert score.primary.value == 1.0
    assert score.metrics["violation_count"].value == 0.0
    assert score.metrics["checked_agent_months"].value == 4.0


def test_score_budget_identity_detects_a_fabricated_off_cycle_violation() -> None:
    """Mutation check: a single corrupted inventory value must be caught.

    Guards against the check being vacuously true -- a green
    ``score_budget_identity`` on real data would be meaningless if this
    same function could not also fail on a known-bad trajectory.
    """
    dense_log = _synthetic_dense_log()
    # Corrupt the LAST month's ending inventory only -- no later month reads
    # it as its own starting balance, so exactly one residual breaks
    # (mutating an earlier month would cascade into the next month's own
    # identity too, since each month's closing balance is the next month's
    # opening balance).
    dense_log["states"][2]["1"]["inventory"]["Coin"] += 1000.0  # corrupt month-2 agent-1

    leaf = m.build_budget_identity_leaf(_pins())
    score = m.score_budget_identity(
        leaf,
        dense_log=dense_log,
        n_agents=2,
        world_period=3,
        month_actions=_synthetic_month_actions(),
    )

    assert score.status == "ok"
    assert score.primary.value == 0.0
    assert score.metrics["violation_count"].value == 1.0
    assert score.primary.metadata["first_violation"]["agent_id"] == "1"
    assert score.primary.metadata["first_violation"]["month"] == 2


def test_score_budget_identity_detects_a_negative_boundary_month_residual() -> None:
    dense_log = _synthetic_dense_log()
    # A negative residual on a boundary month cannot be legitimate saving
    # interest (upstream's own rate is always >= 0) -- must be flagged.
    dense_log["states"][2]["0"]["inventory"]["Coin"] -= 50.0

    leaf = m.build_budget_identity_leaf(_pins())
    score = m.score_budget_identity(
        leaf,
        dense_log=dense_log,
        n_agents=2,
        world_period=2,
        month_actions=_synthetic_month_actions(),
    )

    assert score.primary.value == 0.0
    assert score.metrics["violation_count"].value == 1.0
    assert score.primary.metadata["first_violation"]["reason"] == (
        "negative residual on a saving-interest month"
    )


def test_score_budget_identity_ignores_a_stale_consumption_field_on_a_noop_month() -> None:
    """A 0 consumption action must zero consumption_spend, not the stale field.

    Regression fixture for the real 2-agent discovery made while building
    this leaf (see ``compute_budget_identity_residuals``'s own docstring):
    ``SimpleConsumption`` never resets ``agent.consumption["Coin"]`` on its
    own NO-OP branch, so trusting the raw field on a 0-consumption-action
    month would fabricate a nonzero spend that was never actually deducted.
    """
    dense_log = _synthetic_dense_log()
    # Leave month-2 agent-1's *recorded* consumption field at its stale
    # month-1 value (30.0, not the "fresh" 35.0 the fixture otherwise uses)
    # and correct its inventory so the identity holds when consumption_spend
    # is correctly treated as 0 for that no-op month.
    dense_log["states"][2]["1"]["consumption"]["Coin"] = 30.0  # stale, unused value
    dense_log["states"][2]["1"]["inventory"]["Coin"] = 240.0 + 90.0 - 18.0 + 6.0 - 0.0

    month_actions = _synthetic_month_actions()
    month_actions[1]["1"] = [1, 0]  # month 2, agent 1: consumption action is 0 (NO-OP)

    leaf = m.build_budget_identity_leaf(_pins())
    score = m.score_budget_identity(
        leaf, dense_log=dense_log, n_agents=2, world_period=3, month_actions=month_actions
    )
    assert score.primary.value == 1.0
    assert score.metrics["violation_count"].value == 0.0


def test_score_budget_identity_reports_invalid_measurement_when_dense_log_is_none() -> None:
    leaf = m.build_budget_identity_leaf(_pins())
    score = m.score_budget_identity(
        leaf, dense_log=None, n_agents=2, world_period=12, month_actions=[]
    )
    assert score.status == "invalid_measurement"
    assert score.primary is None
    assert score.validity.status == "invalid"
    assert score.validity.reasons


def test_score_budget_identity_reports_invalid_measurement_on_malformed_dense_log() -> None:
    leaf = m.build_budget_identity_leaf(_pins())
    score = m.score_budget_identity(
        leaf, dense_log={"states": []}, n_agents=2, world_period=12, month_actions=[]
    )
    assert score.status == "invalid_measurement"
    assert score.primary is None


def test_compute_macro_trajectory_is_hand_verifiable() -> None:
    dense_log = _synthetic_dense_log()
    trajectory = m.compute_macro_trajectory(
        dense_log, n_agents=2, month_actions=_synthetic_month_actions()
    )

    assert trajectory.gdp_proxy_by_month == (20.0 + 30.0, 25.0 + 35.0)
    assert trajectory.price_level_by_month == (101.0, 103.0)
    # No agent's job is "Unemployment" in the synthetic fixture.
    assert trajectory.unemployment_rate_by_month == (0.0, 0.0)


def test_compute_macro_trajectory_ignores_a_stale_consumption_field_on_a_noop_month() -> None:
    dense_log = _synthetic_dense_log()
    month_actions = _synthetic_month_actions()
    month_actions[1]["1"] = [1, 0]  # month 2, agent 1: consumption action is 0 (NO-OP)

    trajectory = m.compute_macro_trajectory(dense_log, n_agents=2, month_actions=month_actions)
    # Agent 1's month-2 recorded consumption (35.0) must be excluded --
    # only agent 0's 25.0 counts.
    assert trajectory.gdp_proxy_by_month == (20.0 + 30.0, 25.0)


def test_compute_macro_trajectory_reports_a_real_unemployment_fraction() -> None:
    dense_log = _synthetic_dense_log()
    dense_log["states"][1]["0"]["endogenous"]["job"] = "Unemployment"

    trajectory = m.compute_macro_trajectory(
        dense_log, n_agents=2, month_actions=_synthetic_month_actions()
    )
    assert trajectory.unemployment_rate_by_month == (0.5, 0.0)


def test_score_macro_trajectory_never_produces_a_pass_fail_claim() -> None:
    leaf = m.build_macro_trajectory_leaf(_pins())
    score = m.score_macro_trajectory(
        leaf,
        dense_log=_synthetic_dense_log(),
        n_agents=2,
        month_actions=_synthetic_month_actions(),
    )

    assert score.status == "ok"
    assert score.primary.unit == "coin"
    assert score.metrics["gdp_proxy_month_01"].value == pytest.approx(50.0)
    assert score.metrics["price_level_month_01"].value == pytest.approx(101.0)
    assert score.metrics["unemployment_rate_month_01"].value == 0.0


def test_score_macro_trajectory_reports_invalid_measurement_when_dense_log_is_none() -> None:
    leaf = m.build_macro_trajectory_leaf(_pins())
    score = m.score_macro_trajectory(leaf, dense_log=None, n_agents=2, month_actions=[])
    assert score.status == "invalid_measurement"
    assert score.primary is None


def test_score_tax_bracket_arithmetic_reports_invalid_measurement_when_dense_log_is_none() -> None:
    leaf = m.build_tax_bracket_leaf(_pins())
    score = m.score_tax_bracket_arithmetic(leaf, dense_log=None, n_agents=2, bridge=None)
    assert score.status == "invalid_measurement"
    assert score.primary is None


# ---------------------------------------------------------------------------
# Bridge-gated: score a real episode through the real upstream engine.
# ---------------------------------------------------------------------------


def test_score_budget_identity_holds_exactly_for_a_real_tiny_episode() -> None:
    _require_bridge()
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)

    terminal, scorer, n_agents, world_period = _run_episode_and_score(
        "econagent.pilot.tiny4x6.seed0"
    )
    score = scorer.score_budget_identity(
        dense_log=terminal["dense_log"],
        n_agents=n_agents,
        world_period=world_period,
        month_actions=terminal["month_actions"],
    )
    assert score.status == "ok"
    assert score.primary.value == 1.0
    assert score.metrics["violation_count"].value == 0.0
    assert score.metrics["checked_agent_months"].value == n_agents * terminal["episode_length"]


def test_score_budget_identity_holds_exactly_across_a_saving_interest_boundary_month() -> None:
    # small10x12: episode_length=12 == world_period=12, so month 12 is a
    # real saving-interest boundary month -- the primary golden scenario
    # (spec section 4's "Successful" golden).
    _require_bridge()
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)

    terminal, scorer, n_agents, world_period = _run_episode_and_score(
        "econagent.pilot.small10x12.seed0"
    )
    score = scorer.score_budget_identity(
        dense_log=terminal["dense_log"],
        n_agents=n_agents,
        world_period=world_period,
        month_actions=terminal["month_actions"],
    )
    assert score.status == "ok"
    assert score.primary.value == 1.0
    assert score.metrics["boundary_agent_months"].value == n_agents  # month 12 only
    assert score.metrics["violation_count"].value == 0.0


def test_score_tax_bracket_arithmetic_matches_upstream_bracket_computation() -> None:
    _require_bridge()
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)

    terminal, scorer, n_agents, _world_period = _run_episode_and_score(
        "econagent.pilot.tiny4x6.seed0"
    )
    bridge = EconAgentBridge.discover(UPSTREAM_ROOT)
    score = scorer.score_tax_bracket_arithmetic(
        dense_log=terminal["dense_log"], n_agents=n_agents, bridge=bridge
    )
    assert score.status == "ok"
    assert score.primary.value == 1.0
    assert score.metrics["violation_count"].value == 0.0
    assert score.metrics["checked_agent_months"].value == n_agents * terminal["episode_length"]


def test_score_tax_bracket_arithmetic_detects_a_fabricated_violation() -> None:
    """Mutation check on a REAL recorded trajectory, not just the synthetic fixture."""
    _require_bridge()
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)

    terminal, scorer, n_agents, _world_period = _run_episode_and_score(
        "econagent.pilot.tiny4x6.seed0"
    )
    dense_log = copy.deepcopy(terminal["dense_log"])
    # Inflate month-1 agent-0's recorded tax_paid far past what the
    # bracket schedule could ever produce for its recorded income.
    dense_log["PeriodicTax"][0]["0"]["tax_paid"] += 1_000_000.0

    bridge = EconAgentBridge.discover(UPSTREAM_ROOT)
    score = scorer.score_tax_bracket_arithmetic(
        dense_log=dense_log, n_agents=n_agents, bridge=bridge
    )
    assert score.primary.value == 0.0
    assert score.metrics["violation_count"].value == 1.0
    assert score.primary.metadata["first_violation"]["agent_id"] == "0"
    assert score.primary.metadata["first_violation"]["month"] == 1


def test_score_macro_trajectory_reports_real_descriptive_series() -> None:
    _require_bridge()
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)

    terminal, scorer, n_agents, _world_period = _run_episode_and_score(
        "econagent.pilot.tiny4x6.seed0"
    )
    score = scorer.score_macro_trajectory(
        dense_log=terminal["dense_log"],
        n_agents=n_agents,
        month_actions=terminal["month_actions"],
    )
    assert score.status == "ok"
    episode_length = terminal["episode_length"]
    assert f"gdp_proxy_month_{episode_length:02d}" in score.metrics
    assert f"price_level_month_{episode_length:02d}" in score.metrics
    assert f"unemployment_rate_month_{episode_length:02d}" in score.metrics
    for key, metric in score.metrics.items():
        if key.startswith("unemployment_rate_month_"):
            assert 0.0 <= metric.value <= 1.0
