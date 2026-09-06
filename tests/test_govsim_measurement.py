"""Tests for the govsim measurement leaves (measurement.py) and QC Gate 2.

Three kinds of coverage, mirroring ``tests/test_tau3_retail_measurement.py``'s
own split:

* **Pure, provider-free, bridge-free** tests against ``measurement.py``
  directly -- leaf-declaration rules (spec section 2's table),
  ``operational_failure`` never scoring as a zero, and the vendored
  ``gini()`` against hand-computed values. These need neither the pinned
  upstream checkout nor the bridge and always run.
* **QC Gate 2's five goldens** (spec section 4), each built and driven
  through the REAL ``GovsimPlugin``/``GovsimBridge`` -- never a fake bridge
  (unlike ``tests/test_govsim_environment.py``'s structural coverage of the
  same five scenarios) -- so this suite proves the goldens hold against the
  actual pinned upstream checkout, not just an adapter-side assumption about
  it. These follow ``tests/test_tau3_retail_measurement.py``'s
  ``_bridge()``/skip convention: they run for real when
  ``$AEREAD_GOVSIM_BRIDGE_PYTHON``/a colocated venv resolves, and are
  skipped (never faked) otherwise.
* **Parity (spec section 5's P4).** The vendored ``gini()`` copy in
  ``measurement.py`` matches upstream's own, real, unmodified ``gini()``
  function -- called through ``GovsimBridge.call_upstream_gini`` -- byte for
  byte on the same sample arrays, including the negative-shift and
  NaN-removal branches.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope, LegalityResult, ParseResult
from aeread_families.govsim import cases as govsim_cases
from aeread_families.govsim import measurement as m
from aeread_families.govsim import policies
from aeread_families.govsim.environment import (
    DISCUSS_PHASE,
    GovsimPlugin,
    HARVEST_PHASE,
)
from aeread_families.govsim.govsim_bridge import (
    GovsimBridge,
    GovsimBridgeUnavailableError,
    discover_bridge_python,
)

# ---------------------------------------------------------------------------
# Upstream checkout / bridge discovery -- per-test skip, never a module-level
# skip: the pure tests below need neither.
# ---------------------------------------------------------------------------


def _find_upstream_root() -> Path | None:
    candidate = os.environ.get(
        "AEREAD_GOVSIM_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-govsim",
    )
    root = Path(candidate)
    marker = root / "simulation" / "scenarios" / "common" / "environment" / "concurrent_env.py"
    return root if marker.is_file() else None


UPSTREAM_ROOT = _find_upstream_root()

if UPSTREAM_ROOT is not None:
    try:
        BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
    except GovsimBridgeUnavailableError as error:
        BRIDGE_PYTHON = None
        _BRIDGE_SKIP_REASON = str(error)
    else:
        _BRIDGE_SKIP_REASON = ""
else:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = "pinned upstream govsim checkout not found"


def _bridge() -> GovsimBridge:
    if UPSTREAM_ROOT is None or BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )


@pytest.fixture(scope="module")
def bridge() -> GovsimBridge:
    return _bridge()


# ---------------------------------------------------------------------------
# Episode-driving helpers (bridge-gated tests only).
# ---------------------------------------------------------------------------


def _envelope(seat_id: str, action: dict[str, Any]) -> ActionEnvelope:
    parse = ParseResult.success(action)
    legality = LegalityResult.legal_action()
    return ActionEnvelope(seat_id=seat_id, valid=True, action=parse.action, parse=parse, legality=legality)


def _family_case(
    scenario: str, policy_id: str, *, num_agents: int = 5, world_seed: int = 0
) -> dict[str, Any]:
    case = govsim_cases.build_case(scenario, policy_id, world_seed, num_agents=num_agents)
    return dict(case["payload"])


def _drive_episode(
    plugin: GovsimPlugin, family_case: Mapping[str, Any], *, max_phase_steps: int = 600
) -> dict[str, Any]:
    """Drive one full scripted episode straight through the real phase graph.

    Computes each round's harvest quantity from ``policies.py`` via the
    case's own ``policy_assignment`` -- the same mechanics
    ``tests/test_govsim_environment.py``'s ad hoc per-golden loops already
    use, generalized here so every golden below can drive an arbitrary
    scenario/policy/``num_agents`` combination without repeating the loop.
    """
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    phase_id = HARVEST_PHASE
    for _ in range(max_phase_steps):
        phase = phases[phase_id]
        eligible = plugin.eligible_actors(family_case, state, phase)
        actions: dict[str, ActionEnvelope] = {}
        for seat_id in eligible:
            observation = plugin.observe(family_case, state, seat_id, phase)
            if phase.phase_id == HARVEST_PHASE:
                policy_id = family_case["policy_assignment"][seat_id]
                quantity = policies.SCRIPTED_POLICIES[policy_id](observation)
                response: dict[str, Any] = {"quantity": quantity}
            else:
                response = {}
            parse = plugin.parse_action(family_case, state, seat_id, phase, response)
            assert parse.ok, parse.error_code
            legality = plugin.legal(family_case, state, seat_id, phase, parse.action)
            assert legality.legal, legality.reason
            actions[seat_id] = _envelope(seat_id, parse.action)
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
        if transition.next_phase_id is None:
            return plugin.terminal(family_case, state)
        phase_id = transition.next_phase_id
    raise AssertionError("episode did not terminate within max_phase_steps")


def _baseline_values(terminal: Mapping[str, Any], *, max_num_rounds: int) -> dict[str, float]:
    """The three comparative quantities computed from one baseline episode's
    own terminal state -- exactly what a caller must supply to
    ``GovsimScorer``'s comparative scorers (measurement.py never re-runs a
    baseline episode itself)."""
    survival_months = min(float(terminal["num_round"]), float(max_num_rounds))
    total_harvest = float(sum(terminal["collected_resource"].values()))
    gini = m._vendored_gini(
        np.array(list(terminal["collected_resource"].values()), dtype=float)
    )
    return {
        "survival_months": survival_months,
        "total_harvest": total_harvest,
        "gini": gini,
    }


class _CountingBridge:
    """A call-counting spy wrapping a real bridge -- never a fake one."""

    def __init__(self, inner: GovsimBridge) -> None:
        self._inner = inner
        self.call_count = 0

    def run_actions(self, **kwargs: Any) -> Any:
        self.call_count += 1
        return self._inner.run_actions(**kwargs)


class _LocationCorruptingBridge:
    """Wraps a real ``GovsimBridge``, forcing the FIRST submitted action's
    ``location`` to a value upstream itself rejects.

    Reproduces QC Gate 2's "malformed-operational" golden (spec section 4,
    "a correctly-timed action... during the lake phase" whose location is
    wrong) against the REAL upstream checkout -- never a fake bridge (that
    coverage already exists in
    ``tests/test_govsim_environment.py::test_step_catches_a_bridge_action_error_as_a_typed_operational_failure``).
    """

    def __init__(self, inner: GovsimBridge) -> None:
        self._inner = inner

    def run_actions(
        self, *, scenario: str, env_cfg: Mapping[str, Any], seed: int, actions: Any
    ) -> Any:
        actions = [dict(action) for action in actions]
        if actions and actions[0].get("kind") == "harvesting":
            actions[0]["location"] = "restaurant"  # wrong during the lake phase
        return self._inner.run_actions(
            scenario=scenario, env_cfg=env_cfg, seed=seed, actions=actions
        )


# ---------------------------------------------------------------------------
# Leaf declaration rules -- pure, no bridge, no upstream checkout.
# ---------------------------------------------------------------------------


def test_build_leaves_returns_exactly_five_leaves_matching_the_spec_table() -> None:
    leaves = m.build_leaves()
    assert len(leaves) == 5
    by_id = {leaf.estimand.estimand_id: leaf for leaf in leaves}
    assert set(by_id) == {
        m.NO_COLLAPSE_ESTIMAND_ID,
        m.THRESHOLD_ADHERENCE_ESTIMAND_ID,
        m.SURVIVAL_MONTHS_ESTIMAND_ID,
        m.TOTAL_HARVEST_ESTIMAND_ID,
        m.EQUALITY_GINI_ESTIMAND_ID,
    }
    # Never blended: five distinct leaf ids, the kernel's own fixed
    # composition_kind on every one of them.
    assert len({leaf.leaf_id for leaf in leaves}) == 5
    assert all(leaf.composition_kind == "leaf" for leaf in leaves)

    no_collapse = by_id[m.NO_COLLAPSE_ESTIMAND_ID]
    assert no_collapse.verifier.verifier_family == "rule_constraint"
    assert no_collapse.verifier.reference.reference_kind == "state_invariant"
    assert no_collapse.verifier.evaluation_class == "deterministic"
    assert no_collapse.estimand.input_scope == "trajectory"

    threshold = by_id[m.THRESHOLD_ADHERENCE_ESTIMAND_ID]
    assert threshold.verifier.verifier_family == "rule_constraint"
    assert threshold.verifier.reference.reference_kind == "constraint_satisfaction"
    assert threshold.verifier.evaluation_class == "deterministic"
    assert threshold.estimand.input_scope == "trajectory"

    for estimand_id in (
        m.SURVIVAL_MONTHS_ESTIMAND_ID,
        m.TOTAL_HARVEST_ESTIMAND_ID,
        m.EQUALITY_GINI_ESTIMAND_ID,
    ):
        leaf = by_id[estimand_id]
        assert leaf.verifier.verifier_family == "comparative"
        assert leaf.verifier.reference.reference_kind == "baseline_delta"
        assert leaf.verifier.evaluation_class == "deterministic"
        assert leaf.estimand.input_scope == "terminal_state"


def test_no_objective_reference_leaf_is_declared_per_p06() -> None:
    """docs/problem_bound_case_audit.md row P06: no certified policy upper
    bound exists for any of these estimands -- never framed as an approach
    to a bound."""
    for leaf in m.build_leaves():
        assert leaf.verifier.verifier_family != "objective_reference"
        assert leaf.verifier.objective_scope is None


def test_build_scorer_hook_returns_the_same_five_leaves_as_measurement_py() -> None:
    # upstream_root/bridge are never touched by build_scorer (it delegates
    # straight to measurement.py) -- a real checkout is not needed here.
    plugin = GovsimPlugin(upstream_root=Path("/nonexistent/not-needed"), bridge=None)
    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)

    scorer = plugin.build_scorer(family_case)

    expected = m.build_leaves()
    assert tuple(leaf.leaf_id for leaf in scorer.leaves) == tuple(
        leaf.leaf_id for leaf in expected
    )
    assert scorer.scenario == "fishing"
    assert scorer.num_agents == 5
    assert scorer.max_num_rounds == 12


def test_build_scorer_scales_with_num_agents_for_the_degenerate_case() -> None:
    plugin = GovsimPlugin(upstream_root=Path("/nonexistent/not-needed"), bridge=None)
    family_case = _family_case("fishing", "sustainable_v1", num_agents=1)
    scorer = plugin.build_scorer(family_case)
    assert scorer.num_agents == 1


# ---------------------------------------------------------------------------
# operational_failure never scores as a zero -- pure, no bridge needed.
# ---------------------------------------------------------------------------


def _terminal_stub(reason: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "reason": reason,
        "num_round": 3,
        "resource_in_pool": 50,
        "collected_resource": {"persona_0": 10, "persona_1": 12},
        "round_trace": [],
    }
    base.update(overrides)
    return base


_OPERATIONAL_FAILURE_CASES = [
    pytest.param(m.build_no_collapse_leaf, m.score_no_collapse, {"max_num_rounds": 12}, id="no_collapse"),
    pytest.param(
        m.build_threshold_adherence_leaf, m.score_threshold_adherence, {}, id="threshold_adherence"
    ),
    pytest.param(
        m.build_survival_months_leaf,
        m.score_survival_months,
        {"baseline_survival_months": 12.0, "max_num_rounds": 12, "num_agents": 5},
        id="survival_months",
    ),
    pytest.param(
        m.build_total_harvest_leaf,
        m.score_total_harvest,
        {"baseline_total_harvest": 100.0, "num_agents": 5},
        id="total_harvest",
    ),
    pytest.param(
        m.build_equality_gini_leaf,
        m.score_equality_gini,
        {"baseline_gini": 0.1, "num_agents": 5},
        id="equality_gini",
    ),
]


@pytest.mark.parametrize("build_leaf, score_fn, extra_kwargs", _OPERATIONAL_FAILURE_CASES)
def test_every_scorer_returns_invalid_measurement_never_a_zero_on_operational_failure(
    build_leaf, score_fn, extra_kwargs
) -> None:
    leaf = build_leaf()
    terminal = _terminal_stub("operational_failure")

    envelope = score_fn(leaf, terminal=terminal, **extra_kwargs)

    assert envelope.status == "invalid_measurement"
    assert envelope.primary is None
    assert envelope.validity.status == "invalid"
    assert envelope.validity.reasons
    assert "operational_failure" in envelope.validity.reasons[0]


# ---------------------------------------------------------------------------
# GovsimScorer.score_recorded_outcome -- the OLD finalizer seam.
# ``finalize_family_execution`` once executed
# ``plugin.build_scorer(family_case)(recorded_outcome, evidence_refs=...)``.
# It now passes a ``FamilyScoringInput`` and expects every declared leaf
# (issue #76), so ``__call__`` implements that contract and this recorded-
# outcome path keeps its own name. Both are kept: the goldens below pin the
# survival-months scoring itself, independently of which seam reaches it.
# ---------------------------------------------------------------------------


def test_govsim_scorer_is_callable_and_used_exactly_as_the_production_finalizer_calls_it() -> None:
    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)
    scorer = m.build_scorer(family_case)
    assert callable(scorer)

    outcome = {
        "termination_reason": "collapse_or_horizon",
        "outcome_status": "known",
        "num_round": 12,
        "resource_in_pool": 40,
        "collected_resource": {"persona_0": 10, "persona_1": 12},
    }

    score = scorer.score_recorded_outcome(outcome, evidence_refs=("evt_outcome_0",))

    assert score.status == "ok"
    assert score.leaf.leaf_id == m.SURVIVAL_MONTHS_LEAF_ID
    assert score.primary.value == 12.0
    # No baseline is reachable from a recorded outcome alone (measurement.py
    # never re-runs a baseline episode itself): the comparative delta and
    # reference value are honestly omitted here, never fabricated.
    assert score.reference_values == {}
    assert "delta_vs_baseline" not in score.metrics
    assert score.evidence_refs == ("evt_outcome_0",)


def test_govsim_scorer_call_reports_invalid_measurement_for_an_operational_failure_outcome() -> None:
    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)
    scorer = m.build_scorer(family_case)
    outcome = {
        "termination_reason": "operational_failure",
        "outcome_status": "outcome_unknown",
        "num_round": 3,
        "resource_in_pool": 40,
        "collected_resource": {"persona_0": 5},
        "operational_failure": {
            "error_type": "AssertionError",
            "message": "boom",
            "failed_action_index": 2,
        },
    }

    score = scorer.score_recorded_outcome(outcome, evidence_refs=("evt_outcome_1",))

    assert score.status == "invalid_measurement"
    assert score.primary is None
    assert score.leaf.leaf_id == m.SURVIVAL_MONTHS_LEAF_ID
    assert score.validity.status == "invalid"
    assert score.evidence_refs == ("evt_outcome_1",)


# ---------------------------------------------------------------------------
# Vendored gini() -- pure, hand-computed values, no bridge needed (the
# bridge-gated cross-check against upstream's real function is below).
# ---------------------------------------------------------------------------


def test_vendored_gini_equal_split_is_zero() -> None:
    assert m._vendored_gini(np.array([10.0, 10.0, 10.0])) == 0.0


def test_vendored_gini_matches_a_hand_computed_value() -> None:
    value = m._vendored_gini(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
    assert value == pytest.approx(0.26666666666666666)


def test_vendored_gini_shifts_negative_values_before_computing() -> None:
    shifted = m._vendored_gini(np.array([-1.0, -2.0, 3.0, 4.0]))
    manual_shift = m._vendored_gini(np.array([1.0, 0.0, 5.0, 6.0]))  # shifted by +2
    assert shifted == manual_shift


def test_vendored_gini_removes_nans() -> None:
    with_nan = m._vendored_gini(np.array([1.0, 2.0, np.nan, 3.0]))
    without_nan = m._vendored_gini(np.array([1.0, 2.0, 3.0]))
    assert with_nan == without_nan


def test_vendored_gini_single_element_is_zero_the_degenerate_case() -> None:
    # num_agents=1: upstream's own formula, applied to one value, is
    # trivially 0.0 -- this is exactly why the comparative scorers stamp
    # degenerate_single_agent explicitly (see the golden test below).
    assert m._vendored_gini(np.array([42.0])) == 0.0


# ---------------------------------------------------------------------------
# QC Gate 2's five goldens (spec section 4) -- bridge-gated, real upstream.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline_5_agent_fishing(bridge: GovsimBridge) -> dict[str, Any]:
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)
    return _drive_episode(plugin, family_case)


def test_golden_successful_fishing_sustainable_survives_the_full_horizon(
    bridge: GovsimBridge, baseline_5_agent_fishing: dict[str, Any]
) -> None:
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)

    terminal = _drive_episode(plugin, family_case)

    assert terminal["reason"] == "collapse_or_horizon"
    assert terminal["num_round"] == 12  # reached the horizon, never collapsed early

    scorer = m.build_scorer(family_case)
    no_collapse = scorer.score_no_collapse(terminal=terminal)
    assert no_collapse.status == "ok"
    assert no_collapse.primary.value == 1.0

    threshold = scorer.score_threshold_adherence(terminal=terminal)
    assert threshold.status == "ok"
    # sustainable_v1 harvests exactly the advisory threshold every round --
    # never above it -- so every agent-round predicate holds.
    assert threshold.primary.value == 1.0

    baseline = _baseline_values(baseline_5_agent_fishing, max_num_rounds=12)
    survival = scorer.score_survival_months(
        terminal=terminal, baseline_survival_months=baseline["survival_months"]
    )
    assert survival.status == "ok"
    assert survival.primary.value == 12.0
    assert survival.reference_values["baseline"].value == baseline["survival_months"]


def test_golden_valid_but_poor_fishing_greedy_collapses_before_the_horizon(
    bridge: GovsimBridge, baseline_5_agent_fishing: dict[str, Any]
) -> None:
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = _family_case("fishing", "greedy_v1", num_agents=5)

    terminal = _drive_episode(plugin, family_case)

    assert terminal["reason"] == "collapse_or_horizon"
    assert terminal["num_round"] < 12  # collapsed well before the horizon
    assert terminal["resource_in_pool"] < 5
    # Every action was legal and well-formed: the environment executed
    # cleanly all the way to a real termination, never an operational
    # failure (spec section 4's "valid-but-poor" golden).
    assert "operational_failure" not in terminal

    scorer = m.build_scorer(family_case)
    no_collapse = scorer.score_no_collapse(terminal=terminal)
    assert no_collapse.status == "ok"
    assert no_collapse.primary.value == 0.0
    assert no_collapse.metrics["collapse_round"].value == float(terminal["num_round"])

    baseline = _baseline_values(baseline_5_agent_fishing, max_num_rounds=12)
    survival = scorer.score_survival_months(
        terminal=terminal, baseline_survival_months=baseline["survival_months"]
    )
    assert survival.primary.value < 12.0

    total_harvest = scorer.score_total_harvest(
        terminal=terminal, baseline_total_harvest=baseline["total_harvest"]
    )
    assert total_harvest.status == "ok"
    assert total_harvest.primary.value > 0.0  # positive total_harvest, per spec section 4


def test_golden_invalid_unauthorized_rejected_before_any_bridge_call_no_credit(
    bridge: GovsimBridge,
) -> None:
    counting_bridge = _CountingBridge(bridge)
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=counting_bridge)
    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)

    state = plugin.initial_state(family_case, cell=None)
    calls_after_reset = counting_bridge.call_count
    assert calls_after_reset == 1

    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    # "During the discuss phase, submit a PersonaActionHarvesting from a
    # seat that is not persona_0" (spec section 4): upstream itself only has
    # a bare assert that would crash the process; the adapter's own legal()
    # hook must reject this before any bridge call.
    result = plugin.legal(
        family_case, state, "persona_1", phases[DISCUSS_PHASE], {"quantity": 5}
    )

    assert result.legal is False
    assert result.reason == "seat_phase_mismatch"
    # The only claim this specific assertion supports: this call to legal()
    # made no additional bridge call (it is architecturally side-effect-free
    # -- environment.py's legal() `del`s its own `action` argument and never
    # touches `self`/bridge state, regardless of what this test checks).
    # This does NOT exercise what the real kernel's run_episode does with an
    # illegal action for a reject-policy phase -- it cannot: legal() is
    # called directly here, never through run_episode, and the scheduler
    # only ever requests an action from a seat plugin.eligible_actors()
    # already names (run_episode's own `actors = _eligible_actors(...)`), so
    # a request from an ineligible seat is not a reachable path through the
    # real scheduler for this family. See
    # tests/test_govsim_replay.py's
    # test_a_malformed_first_harvest_response_aborts_the_real_scheduler_with_a_reject_policy
    # for the govsim-specific, run_episode-driven proof of the
    # invalid_action_policy="reject" contract for the path that IS
    # reachable (a legitimately-requested seat answering with a value
    # parse_action itself rejects).
    assert counting_bridge.call_count == calls_after_reset


def test_golden_malformed_operational_real_upstream_assertion_is_caught_typed(
    bridge: GovsimBridge,
) -> None:
    corrupting_bridge = _LocationCorruptingBridge(bridge)
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=corrupting_bridge)
    family_case = _family_case("fishing", "sustainable_v1", num_agents=1)

    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    actions = {"persona_0": _envelope("persona_0", {"quantity": 5})}

    transition = plugin.step(family_case, state, phases[HARVEST_PHASE], actions)

    assert transition.next_phase_id is None
    assert transition.state["termination"] == "operational_failure"
    failure = transition.state["operational_failure"]
    # Upstream's own real assertion fired inside the real bridge subprocess
    # -- never a fake bridge standing in for it.
    assert failure["error_type"] == "AssertionError"
    assert failure["failed_action_index"] == 0

    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "operational_failure"
    outcome = plugin.outcome(family_case, terminal)
    assert outcome["outcome_status"] == "outcome_unknown"

    scorer = m.build_scorer(family_case)
    envelopes = (
        scorer.score_no_collapse(terminal=terminal),
        scorer.score_threshold_adherence(terminal=terminal),
        scorer.score_survival_months(terminal=terminal, baseline_survival_months=12.0),
        scorer.score_total_harvest(terminal=terminal, baseline_total_harvest=10.0),
        scorer.score_equality_gini(terminal=terminal, baseline_gini=0.0),
    )
    for envelope in envelopes:
        # Never a silently promoted scored zero (docs/verifier_taxonomy.md
        # section 9); never a crash either -- we got this far.
        assert envelope.status == "invalid_measurement"
        assert envelope.primary is None


def test_golden_degenerate_reference_num_agents_1_flags_the_comparison(
    bridge: GovsimBridge,
) -> None:
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)

    baseline_case = _family_case("fishing", "sustainable_v1", num_agents=1)
    baseline_terminal = _drive_episode(plugin, baseline_case)
    baseline = _baseline_values(baseline_terminal, max_num_rounds=12)

    greedy_case = _family_case("fishing", "greedy_v1", num_agents=1)
    greedy_terminal = _drive_episode(plugin, greedy_case)

    scorer = m.build_scorer(greedy_case)
    assert scorer.num_agents == 1

    survival = scorer.score_survival_months(
        terminal=greedy_terminal, baseline_survival_months=baseline["survival_months"]
    )
    total_harvest = scorer.score_total_harvest(
        terminal=greedy_terminal, baseline_total_harvest=baseline["total_harvest"]
    )
    gini = scorer.score_equality_gini(
        terminal=greedy_terminal, baseline_gini=baseline["gini"]
    )

    # "uninformative by construction and must be flagged, not reported as a
    # clean win/loss" (spec section 4): every comparative leaf stamps this
    # explicitly rather than silently reporting a bare number.
    for envelope in (survival, total_harvest, gini):
        assert envelope.status == "ok"
        assert envelope.primary.metadata["degenerate_single_agent"] is True

    # The rule/constraint leaves are not comparative and are not flagged --
    # only the comparison against a baseline is uninformative here, not the
    # single episode's own invariants.
    no_collapse = scorer.score_no_collapse(terminal=greedy_terminal)
    assert no_collapse.status == "ok"
    assert no_collapse.primary.metadata == {}


# ---------------------------------------------------------------------------
# Cross-scenario coverage (review finding W1): every golden above hard-codes
# "fishing", so a regression that only breaks `sheep`/`pollution` (2 of the
# 3 declared `cases.SCENARIOS`) -- e.g. a bug in `SheepConcurrentEnv`/
# `PollutionConcurrentEnv`'s own `env.py`, or in `_SCENARIO_ENV_CLASSES`/
# `POOL_LOCATION_BY_SCENARIO` (govsim_bridge_driver.py/cases.py) -- would
# stay invisible to this suite. `cases.py`'s own "governing facts" claim
# (spec section 0) is that all three scenarios share one arithmetic core;
# this drives all three, for the same seed and policy, through the REAL
# bridge and asserts their terminal states match exactly, so a future
# scenario-specific divergence is actually caught, not just manually
# recon'd once.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", [s for s in govsim_cases.SCENARIOS if s != "fishing"])
def test_sheep_and_pollution_match_fishings_terminal_state_exactly_for_the_same_seed_and_policy(
    bridge: GovsimBridge, scenario: str
) -> None:
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)

    fishing_sustainable = _drive_episode(
        plugin, _family_case("fishing", "sustainable_v1", num_agents=5)
    )
    other_sustainable = _drive_episode(
        plugin, _family_case(scenario, "sustainable_v1", num_agents=5)
    )
    assert other_sustainable == fishing_sustainable

    # And again on the greedy policy, which additionally exercises the
    # collapse-before-horizon path for the non-fishing scenario.
    fishing_greedy = _drive_episode(plugin, _family_case("fishing", "greedy_v1", num_agents=5))
    other_greedy = _drive_episode(plugin, _family_case(scenario, "greedy_v1", num_agents=5))
    assert other_greedy == fishing_greedy
    assert other_greedy["num_round"] < 12  # collapsed well before the horizon, same as fishing


# ---------------------------------------------------------------------------
# Parity (spec section 5's P4): vendored gini() vs. upstream's real gini().
# ---------------------------------------------------------------------------


def test_upstream_plots_py_has_not_drifted_from_the_pinned_hash() -> None:
    if UPSTREAM_ROOT is None:
        pytest.skip("pinned upstream govsim checkout not found")
    path = UPSTREAM_ROOT / m.UPSTREAM_GINI_SOURCE_FILE
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == m.UPSTREAM_GINI_SOURCE_SHA256


@pytest.mark.parametrize(
    "array",
    [
        [1.0, 2.0, 3.0, 4.0, 5.0],
        [22.0, 20.0, 17.0, 22.0, 19.0],
        [10.0],
        [-1.0, -2.0, 3.0, 4.0],
    ],
)
def test_vendored_gini_matches_upstreams_own_gini_through_the_bridge(
    bridge: GovsimBridge, array: list[float]
) -> None:
    upstream_value = bridge.call_upstream_gini(array)
    vendored_value = m._vendored_gini(np.array(array, dtype=float))
    assert upstream_value == vendored_value


def test_vendored_gini_matches_upstream_on_an_all_zero_array_nan_case(
    bridge: GovsimBridge,
) -> None:
    # 0/0 division -- upstream's own formula also produces NaN here; both
    # sides must agree it's NaN, not merely both be "wrong" the same way.
    array = [0.0, 0.0, 0.0, 0.0]
    upstream_value = bridge.call_upstream_gini(array)
    vendored_value = m._vendored_gini(np.array(array, dtype=float))
    assert np.isnan(upstream_value)
    assert np.isnan(vendored_value)


def test_vendored_gini_matches_upstreams_own_gini_with_nans_removed(
    bridge: GovsimBridge,
) -> None:
    array = [1.0, 2.0, float("nan"), 3.0]
    upstream_value = bridge.call_upstream_gini(array)
    vendored_value = m._vendored_gini(np.array(array, dtype=float))
    assert upstream_value == vendored_value


# ---------------------------------------------------------------------------
# GovsimScorer.__call__ -- the kernel's finalizer contract (issue #76).
# ---------------------------------------------------------------------------


def _scoring_input(state, *, refs=()):
    from types import SimpleNamespace

    return SimpleNamespace(
        outcome={},
        phase_instances=(
            SimpleNamespace(transitions=(SimpleNamespace(state=state),)),
        ),
        evidence_refs=refs,
    )


def _terminal_for(num_round: int, *, agents: int) -> dict:
    share = 10.0
    return {
        "reason": "max_num_rounds",
        "num_round": num_round,
        "resource_in_pool": 50.0,
        "collected_resource": {f"agent_{i}": share for i in range(agents)},
        # The shape environment.step() actually appends, not an invented one.
        "round_trace": [
            {
                "round_index": index,
                "wanted_resource": {f"agent_{i}": 1.0 for i in range(agents)},
                "sustainability_threshold": 10.0,
                "resource_in_pool_after_regen": 100.0,
                "collapsed_or_horizon": False,
            }
            for index in range(num_round)
        ],
    }


def test_call_surfaces_every_leaf_when_baselines_are_present() -> None:
    """The kernel expects all declared leaves, not just the primary one."""
    import aeread_families.govsim.measurement as m

    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)
    terminal = _terminal_for(12, agents=5)
    scorer = m.build_scorer(
        family_case,
        terminal_builder=lambda state: terminal,
        baselines={"survival_months": 12.0, "total_harvest": 50.0, "gini": 0.0},
    )
    result = scorer(_scoring_input({"any": "state"}))
    assert isinstance(result, m.FamilyScoreSet)
    assert len(result.scores) == 5
    assert result.primary_leaf_id == m.SURVIVAL_MONTHS_LEAF_ID


def test_call_omits_the_comparative_leaves_rather_than_inventing_a_baseline() -> None:
    """Without reference values, report less -- never fabricate a comparison."""
    import aeread_families.govsim.measurement as m

    family_case = _family_case("fishing", "sustainable_v1", num_agents=5)
    terminal = _terminal_for(12, agents=5)
    scorer = m.build_scorer(
        family_case, terminal_builder=lambda state: terminal, baselines=None
    )
    result = scorer(_scoring_input({"any": "state"}))
    leaf_ids = {score.leaf.leaf_id for score in result.scores}
    assert m.TOTAL_HARVEST_LEAF_ID not in leaf_ids
    assert m.EQUALITY_GINI_LEAF_ID not in leaf_ids
    # The family's declared primary estimand is always present, so an
    # included receipt always carries the leaf the family is defined by.
    assert result.primary_leaf_id == m.SURVIVAL_MONTHS_LEAF_ID


def test_call_refuses_a_scoring_input_with_no_replayed_state() -> None:
    import aeread_families.govsim.measurement as m
    from types import SimpleNamespace

    scorer = m.build_scorer(
        _family_case("fishing", "sustainable_v1", num_agents=5),
        terminal_builder=lambda state: None,
    )
    empty = SimpleNamespace(outcome={}, phase_instances=(), evidence_refs=())
    with pytest.raises(ValueError, match="no replayed terminal state"):
        scorer(empty)
