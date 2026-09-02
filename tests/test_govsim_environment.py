"""Structural tests for the govsim kernel family plugin.

No bridge needed (mirrors ``docs/govsim_adapter_spec.md`` section 5's test
classification): every test here drives ``GovsimPlugin`` against an
in-process fake bridge, never the real subprocess bridge. This exercises the
phase graph, seat eligibility, and the kernel-facing mechanics of QC Gate
2's five goldens (spec section 4) -- never upstream's own
regeneration/collapse arithmetic, which belongs to the replay/parity suite
once the bridge is wired into CI. One test (``validate_payload`` accepting a
well-formed case) does check the pinned upstream *checkout* is present and
clean at the pinned revision -- a plain ``git`` call, not the bridge venv --
and skips itself if that checkout is not on disk.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.scheduler import ActionEnvelope, LegalityResult, ParseResult
from aeread_families.govsim import cases as govsim_cases
from aeread_families.govsim import environment
from aeread_families.govsim.environment import (
    DISCUSS_PHASE,
    GovsimPlugin,
    HARVEST_PHASE,
    PERSONA_ROLE,
    PLUGIN_ID,
    REFLECT_PHASE,
    family_manifest,
    register_plugin,
)
from aeread_families.govsim.govsim_bridge import GovsimActionError

_UNUSED_UPSTREAM_ROOT = Path("/nonexistent/govsim-upstream-not-needed-for-these-tests")

_REAL_UPSTREAM_ROOT = Path(
    os.environ.get(
        "AEREAD_GOVSIM_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-govsim",
    )
)


class FakeGovsimBridge:
    """A deterministic stand-in for ``GovsimBridge.run_actions``.

    Tracks every call it receives (for assertions on exactly what the
    plugin submits) and, absent a configured failure, projects a plausible
    ``resource_in_pool``/``terminations`` state purely as a function of how
    many actions have accumulated -- enough to drive the kernel-level phase
    loop through multiple rounds without claiming anything about upstream's
    own regeneration/collapse arithmetic (that fidelity claim belongs to
    the real bridge, tested separately once wired into CI).
    """

    def __init__(self, *, fail_at_action_count: int | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_at_action_count = fail_at_action_count

    def run_actions(
        self,
        *,
        scenario: str,
        env_cfg: Mapping[str, Any],
        seed: int,
        actions,
    ) -> dict[str, Any]:
        actions = list(actions)
        self.calls.append(
            {
                "scenario": scenario,
                "env_cfg": dict(env_cfg),
                "seed": seed,
                "actions": actions,
            }
        )
        if self.fail_at_action_count is not None and len(actions) >= self.fail_at_action_count:
            # Mimics a real bridge call whose replay fails exactly at the
            # `fail_at_action_count`-th action ever submitted (1-based),
            # regardless of how many actions this one call happened to add
            # in a single batch -- a batch is a kernel-level "harvest"/
            # "reflect" phase's own accounting, not upstream's own replay
            # granularity (spec section 3.1: one bridge call replays 2N/1/N
            # individual upstream env.step() calls).
            raise GovsimActionError(
                error_type="AssertionError",
                message="stub upstream assertion for a deliberately malformed action",
                failed_action_index=self.fail_at_action_count - 1,
            )
        num_agents = int(env_cfg["num_agents"])
        max_num_rounds = int(env_cfg["max_num_rounds"])
        # Bridge-level action count per round: 2N (harvest: N real + N dummy
        # pool_after_harvesting) + 1 (discuss) + N (reflect) -- distinct from
        # the KERNEL-level logical-action budget in environment.py's
        # `phases()` (2N+1/round), which counts one action per seat per
        # phase-instance, never upstream's own 2N-call harvest expansion.
        per_round = 3 * num_agents + 1
        num_round = len(actions) // per_round
        terminated = num_round >= max_num_rounds
        personas = [f"persona_{i}" for i in range(num_agents)]
        return {
            "phase": "lake",
            "pool_location": "lake",
            "agent_selection": "persona_0",
            "num_round": num_round,
            "resource_in_pool": 100,
            "resource_before_harvesting": 100,
            "sustainability_threshold": 10,
            "wanted_resource": {persona: 0 for persona in personas},
            "collected_resource": {persona: 0 for persona in personas},
            "last_collected_resource": {persona: 0 for persona in personas},
            "rewards": {persona: 0.0 for persona in personas},
            "terminations": {persona: terminated for persona in personas},
        }


def _plugin(*, bridge: FakeGovsimBridge | None = None) -> GovsimPlugin:
    return GovsimPlugin(
        upstream_root=_UNUSED_UPSTREAM_ROOT,
        bridge=bridge if bridge is not None else FakeGovsimBridge(),
    )


def _family_case(*, num_agents: int = 5, scenario: str = "fishing") -> dict[str, Any]:
    case = govsim_cases.build_case(scenario, "sustainable_v1", 0, num_agents=num_agents)
    return dict(case["payload"])


def _envelope(seat_id: str, action: dict[str, Any]) -> ActionEnvelope:
    parse = ParseResult.success(action)
    legality = LegalityResult.legal_action()
    return ActionEnvelope(seat_id=seat_id, valid=True, action=parse.action, parse=parse, legality=legality)


# ---------------------------------------------------------------------------
# family_manifest / register_plugin
# ---------------------------------------------------------------------------


def test_family_manifest_round_trips_through_the_strict_grammar() -> None:
    manifest = family_manifest()
    assert isinstance(manifest, FamilyManifest)
    assert manifest.family.id == "govsim"
    assert manifest.family.plugin_id == PLUGIN_ID
    assert set(manifest.environment.phase_specs) == {HARVEST_PHASE, DISCUSS_PHASE, REFLECT_PHASE}
    assert manifest.environment.needs_tools is False
    assert manifest.environment.needs_sandbox is False
    assert manifest.roles[PERSONA_ROLE].scripted_policies == (
        "sustainable_v1",
        "greedy_v1",
        "mixed_v1",
    )
    # Per docs/problem_bound_case_audit.md row P06: comparative-only, no
    # certified upper bound declared.
    assert manifest.measurement.measurement_kind == "comparative_or_human_judged"
    assert manifest.measurement.bound_status == "baseline_only"
    assert manifest.measurement.optimum_upper_bound is None


def test_register_plugin_succeeds_with_every_required_hook() -> None:
    registry = PluginRegistry()
    plugin = register_plugin(registry, plugin=_plugin())
    resolved = registry.resolve("govsim", "0.1.0", PLUGIN_ID)
    assert resolved is plugin


# ---------------------------------------------------------------------------
# phases() / eligible_actors()
# ---------------------------------------------------------------------------


def test_phases_budget_is_per_phase_total_across_the_whole_episode() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    assert set(phases) == {HARVEST_PHASE, DISCUSS_PHASE, REFLECT_PHASE}
    # 5 personas/round x 12 rounds for harvest/reflect; 1 (persona_0)/round
    # x 12 rounds for discuss. Not a shared/blanket value: the scheduler's
    # own `phase_action_counts` accumulates per phase across every round it
    # runs again, never resets per instance.
    assert phases[HARVEST_PHASE].max_logical_actions == 5 * 12
    assert phases[REFLECT_PHASE].max_logical_actions == 5 * 12
    assert phases[DISCUSS_PHASE].max_logical_actions == 1 * 12
    assert phases[HARVEST_PHASE].mode == "simultaneous"
    assert phases[REFLECT_PHASE].mode == "simultaneous"
    assert phases[DISCUSS_PHASE].mode == "single"
    assert phases[HARVEST_PHASE].next_phases == (DISCUSS_PHASE,)
    assert phases[DISCUSS_PHASE].next_phases == (REFLECT_PHASE,)
    assert phases[REFLECT_PHASE].next_phases == (HARVEST_PHASE,)


def test_phases_budget_scales_with_num_agents() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=1)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    assert phases[HARVEST_PHASE].max_logical_actions == 1 * 12
    assert phases[DISCUSS_PHASE].max_logical_actions == 1 * 12


def test_eligible_actors_harvest_and_reflect_are_every_persona() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    personas = tuple(f"persona_{i}" for i in range(5))
    assert plugin.eligible_actors(family_case, state, phases[HARVEST_PHASE]) == personas
    assert plugin.eligible_actors(family_case, state, phases[REFLECT_PHASE]) == personas


def test_eligible_actors_discuss_is_only_the_fixed_spokesperson() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    assert plugin.eligible_actors(family_case, state, phases[DISCUSS_PHASE]) == ("persona_0",)


# ---------------------------------------------------------------------------
# validate_payload
# ---------------------------------------------------------------------------


def test_validate_payload_rejects_missing_or_extra_keys() -> None:
    plugin = _plugin()
    payload = _family_case()
    del payload["world_seed"]
    with pytest.raises(ValueError, match="must contain exactly"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_wrong_upstream_pin() -> None:
    plugin = _plugin()
    payload = _family_case()
    payload["upstream_commit"] = "0" * 40
    with pytest.raises(ValueError, match="wrong upstream commit"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_unknown_scenario() -> None:
    plugin = _plugin()
    payload = _family_case()
    payload["scenario"] = "desert"
    with pytest.raises(ValueError, match="unknown scenario"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_policy_assignment_missing_a_seat() -> None:
    plugin = _plugin()
    payload = _family_case(num_agents=2)
    del payload["policy_assignment"]["persona_1"]
    with pytest.raises(ValueError, match="policy_assignment"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_an_undeclared_scripted_policy() -> None:
    plugin = _plugin()
    payload = _family_case(num_agents=1)
    payload["policy_assignment"]["persona_0"] = "aggressive_v1"
    with pytest.raises(ValueError, match="undeclared policies"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_negative_world_seed() -> None:
    plugin = _plugin()
    payload = _family_case()
    payload["world_seed"] = -1
    with pytest.raises(ValueError, match="world_seed"):
        plugin.validate_payload(payload)


def test_validate_payload_accepts_a_generated_case_at_the_pinned_revision() -> None:
    marker = (
        _REAL_UPSTREAM_ROOT
        / "simulation"
        / "scenarios"
        / "common"
        / "environment"
        / "concurrent_env.py"
    )
    if not marker.is_file():
        pytest.skip(f"pinned upstream govsim checkout not found at {_REAL_UPSTREAM_ROOT}")
    plugin = GovsimPlugin(upstream_root=_REAL_UPSTREAM_ROOT, bridge=None)
    payload = _family_case()
    validated = plugin.validate_payload(payload)
    assert validated == payload


# ---------------------------------------------------------------------------
# Recorded source/dependency pins are enforced (triage Finding 4). No bridge
# subprocess needed: these drive ``_verify_source_and_dependency_pins``
# directly against a fabricated source tree / a fake ``runtime_info()``, so
# they run everywhere and do not depend on the real pinned checkout being on
# disk (except the one test that deliberately does need it, to isolate a
# dependency-version mismatch from a source mismatch).
# ---------------------------------------------------------------------------


def _write_pinned_source_tree(root: Path, *, concurrent_env_text: str, persona_common_text: str, scenario_env_text: str) -> None:
    common_dir = root / "simulation" / "scenarios" / "common" / "environment"
    common_dir.mkdir(parents=True)
    (common_dir / "concurrent_env.py").write_text(concurrent_env_text, encoding="utf-8")
    persona_dir = root / "simulation" / "persona"
    persona_dir.mkdir(parents=True)
    (persona_dir / "common.py").write_text(persona_common_text, encoding="utf-8")
    for scenario in govsim_cases.SCENARIOS:
        scenario_dir = root / "simulation" / "scenarios" / scenario / "environment"
        scenario_dir.mkdir(parents=True)
        (scenario_dir / "env.py").write_text(scenario_env_text, encoding="utf-8")


def test_verify_source_and_dependency_pins_rejects_tampered_source_bytes(
    tmp_path: Path,
) -> None:
    """Closes triage Finding 4's source-hash half: altered source bytes in
    a checkout git itself would still consider clean at the pinned commit
    (this fabricated tree has no git repo at all -- the point is that
    ``git status``/``git rev-parse`` alone cannot catch this) are rejected
    by name and by which file, never silently accepted."""
    _write_pinned_source_tree(
        tmp_path,
        concurrent_env_text="# tampered concurrent_env.py\n",
        persona_common_text="# tampered persona/common.py\n",
        scenario_env_text="# tampered scenario env.py\n",
    )

    with pytest.raises(ValueError, match="concurrent_env.py sha256 mismatch"):
        environment._verify_source_and_dependency_pins(tmp_path, None)


def test_verify_source_and_dependency_pins_accepts_the_real_pinned_checkout() -> None:
    if not _REAL_UPSTREAM_ROOT.is_dir():
        pytest.skip(f"pinned upstream govsim checkout not found at {_REAL_UPSTREAM_ROOT}")
    # Must not raise: the real, unmodified checkout's source bytes are
    # exactly what cases/govsim/v1/pins.json records.
    environment._verify_source_and_dependency_pins(_REAL_UPSTREAM_ROOT, None)


class _WrongVersionBridge:
    """Reports a runtime dependency set that does not match pins.json --
    never a real bridge subprocess."""

    def runtime_info(self) -> dict[str, str]:
        return {
            "python_version": "9.9.9",
            "numpy_version": "1.24.4",
            "pandas_version": "2.0.3",
            "omegaconf_version": "2.3.0",
            "pettingzoo_version": "1.24.2",
        }


def test_verify_source_and_dependency_pins_rejects_a_runtime_dependency_mismatch() -> None:
    """Closes triage Finding 4's dependency-version half: a clean checkout
    at the pinned commit says nothing about the INTERPRETER executing it --
    a bridge resolving NumPy 2.x (or, here, a mismatched Python version)
    instead of the recorded 1.24.4 must be rejected, never silently
    accepted because the source bytes alone matched."""
    if not _REAL_UPSTREAM_ROOT.is_dir():
        pytest.skip(f"pinned upstream govsim checkout not found at {_REAL_UPSTREAM_ROOT}")

    with pytest.raises(ValueError, match="python_version mismatch"):
        environment._verify_source_and_dependency_pins(
            _REAL_UPSTREAM_ROOT, _WrongVersionBridge()
        )


# ---------------------------------------------------------------------------
# legal(): QC Gate 2's "invalid-unauthorized" golden.
# ---------------------------------------------------------------------------


def test_legal_rejects_a_seat_that_is_not_eligible_for_the_phase() -> None:
    # "During the discuss phase, submit a PersonaActionHarvesting from a
    # seat that is not persona_0" (spec section 4): upstream itself only has
    # a bare `assert action.agent_id == self.agent_selection`, which would
    # crash the process. The adapter's own `legal()` hook must reject this
    # before any bridge call is ever made -- confirmed here by never
    # configuring the fake bridge to accept a call at all.
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    result = plugin.legal(
        family_case, state, "persona_1", phases[DISCUSS_PHASE], {"quantity": 5}
    )
    assert isinstance(result, LegalityResult)
    assert result.legal is False
    assert result.reason == "seat_phase_mismatch"


def test_legal_accepts_the_eligible_spokesperson_for_discuss() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    result = plugin.legal(family_case, state, "persona_0", phases[DISCUSS_PHASE], {})
    assert result.legal is True


# ---------------------------------------------------------------------------
# observe() / parse_action()
# ---------------------------------------------------------------------------


def test_observe_rejects_an_ineligible_seat() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    with pytest.raises(ValueError, match="not active in phase"):
        plugin.observe(family_case, state, "persona_1", phases[DISCUSS_PHASE])


def test_observe_harvest_exposes_pool_and_threshold() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    observation = plugin.observe(family_case, state, "persona_0", phases[HARVEST_PHASE])
    assert observation["resource_in_pool"] == 100
    assert observation["sustainability_threshold"] == 10
    assert observation["num_round"] == 0
    assert observation["num_agents"] == 5


def test_parse_action_harvest_requires_a_nonnegative_integer_quantity() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=5)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    ok = plugin.parse_action(family_case, {}, "persona_0", phases[HARVEST_PHASE], {"quantity": 3})
    assert ok.ok is True
    assert ok.action == {"quantity": 3}

    bad = plugin.parse_action(family_case, {}, "persona_0", phases[HARVEST_PHASE], {"quantity": -1})
    assert bad.ok is False
    assert bad.error_code == "invalid_harvest_quantity"

    not_object = plugin.parse_action(family_case, {}, "persona_0", phases[HARVEST_PHASE], "nope")
    assert not_object.ok is False
    assert not_object.error_code == "response_not_object"


# ---------------------------------------------------------------------------
# step(): phase graph mechanics.
# ---------------------------------------------------------------------------


def test_step_harvest_submits_2n_actions_in_agent_order_then_dummies() -> None:
    bridge = FakeGovsimBridge()
    plugin = _plugin(bridge=bridge)
    family_case = _family_case(num_agents=3)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    actions = {
        f"persona_{i}": _envelope(f"persona_{i}", {"quantity": 4 + i})
        for i in range(3)
    }
    transition = plugin.step(family_case, state, phases[HARVEST_PHASE], actions)
    assert transition.next_phase_id == DISCUSS_PHASE

    submitted = bridge.calls[-1]["actions"]
    assert len(submitted) == 6
    assert [a["agent_id"] for a in submitted[:3]] == ["persona_0", "persona_1", "persona_2"]
    assert [a["quantity"] for a in submitted[:3]] == [4, 5, 6]
    assert [a["agent_id"] for a in submitted[3:]] == ["persona_0", "persona_1", "persona_2"]
    assert all(a["quantity"] == 0 for a in submitted[3:])
    assert all(a["kind"] == "harvesting" for a in submitted)


def test_step_discuss_submits_one_chat_action_for_the_spokesperson() -> None:
    bridge = FakeGovsimBridge()
    plugin = _plugin(bridge=bridge)
    family_case = _family_case(num_agents=5)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    transition = plugin.step(
        family_case, state, phases[DISCUSS_PHASE], {"persona_0": _envelope("persona_0", {})}
    )
    assert transition.next_phase_id == REFLECT_PHASE
    submitted = bridge.calls[-1]["actions"]
    assert submitted == [{"kind": "chat", "agent_id": "persona_0"}]


def test_step_reflect_submits_n_home_actions_and_loops_to_harvest() -> None:
    bridge = FakeGovsimBridge()
    plugin = _plugin(bridge=bridge)
    family_case = _family_case(num_agents=2)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    actions = {f"persona_{i}": _envelope(f"persona_{i}", {}) for i in range(2)}
    transition = plugin.step(family_case, state, phases[REFLECT_PHASE], actions)
    assert transition.next_phase_id == HARVEST_PHASE
    submitted = bridge.calls[-1]["actions"]
    assert submitted == [
        {"kind": "home", "agent_id": "persona_0"},
        {"kind": "home", "agent_id": "persona_1"},
    ]


def test_full_episode_via_stub_bridge_terminates_after_max_num_rounds() -> None:
    bridge = FakeGovsimBridge()
    plugin = _plugin(bridge=bridge)
    family_case = _family_case(num_agents=2)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    phase_id = HARVEST_PHASE
    rounds_completed = 0
    for _ in range(400):
        phase = phases[phase_id]
        if phase.phase_id == DISCUSS_PHASE:
            actions = {"persona_0": _envelope("persona_0", {})}
        else:
            actions = {
                f"persona_{i}": _envelope(f"persona_{i}", {"quantity": 1})
                for i in range(2)
            }
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
        if phase.phase_id == REFLECT_PHASE:
            rounds_completed += 1
        if transition.next_phase_id is None:
            break
        phase_id = transition.next_phase_id
    else:
        raise AssertionError("episode did not terminate within 400 phase steps")

    assert rounds_completed == 12
    assert state["termination"] == "collapse_or_horizon"
    terminal = plugin.terminal(family_case, state)
    assert terminal["reason"] == "collapse_or_horizon"
    outcome = plugin.outcome(family_case, terminal)
    assert outcome["outcome_status"] == "known"


def test_step_raises_if_called_after_termination() -> None:
    bridge = FakeGovsimBridge()
    plugin = _plugin(bridge=bridge)
    family_case = _family_case(num_agents=1)
    state = plugin.initial_state(family_case, cell=None)
    state["termination"] = "collapse_or_horizon"
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    with pytest.raises(ValueError, match="already terminated"):
        plugin.step(
            family_case, state, phases[HARVEST_PHASE], {"persona_0": _envelope("persona_0", {"quantity": 1})}
        )


# ---------------------------------------------------------------------------
# step(): QC Gate 2's "malformed-operational" golden.
# ---------------------------------------------------------------------------


def test_step_catches_a_bridge_action_error_as_a_typed_operational_failure() -> None:
    # "A well-turned, correctly-timed action whose location field is wrong"
    # (spec section 4): here simulated by a fake bridge that raises
    # GovsimActionError on its first call, standing in for upstream's own
    # `assert action.location == self.POOL_LOCATION` firing inside the real
    # bridge subprocess. The adapter must never crash or silently promote
    # this to a scored zero.
    bridge = FakeGovsimBridge(fail_at_action_count=1)
    plugin = _plugin(bridge=bridge)
    family_case = _family_case(num_agents=1)
    state = plugin.initial_state(family_case, cell=None)
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    actions = {"persona_0": _envelope("persona_0", {"quantity": 5})}

    transition = plugin.step(family_case, state, phases[HARVEST_PHASE], actions)

    assert transition.next_phase_id is None
    assert transition.state["termination"] == "operational_failure"
    failure = transition.state["operational_failure"]
    assert failure["error_type"] == "AssertionError"
    assert failure["failed_action_index"] == 0

    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "operational_failure"
    assert terminal["operational_failure"]["error_type"] == "AssertionError"

    outcome = plugin.outcome(family_case, terminal)
    assert outcome["outcome_status"] == "outcome_unknown"
    assert outcome["termination_reason"] == "operational_failure"


# ---------------------------------------------------------------------------
# terminal() / outcome() before termination.
# ---------------------------------------------------------------------------


def test_terminal_is_none_before_the_episode_ends() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=1)
    state = plugin.initial_state(family_case, cell=None)
    assert plugin.terminal(family_case, state) is None


# ---------------------------------------------------------------------------
# build_scorer (measurement.py's five leaves; see test_govsim_measurement.py
# for the full leaf-declaration/scoring/golden coverage -- this file only
# checks the hook wiring itself, mirroring test_tau3_retail_environment.py's
# identical split).
# ---------------------------------------------------------------------------


def test_build_scorer_returns_the_five_measurement_leaves() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=1)
    scorer = plugin.build_scorer(family_case)
    assert len(scorer.leaves) == 5
    assert scorer.num_agents == 1
    assert scorer.max_num_rounds == 12


def test_build_reference_providers_is_empty_no_certified_bound() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=1)
    assert plugin.build_reference_providers(family_case) == ()


def test_generator_returns_none_corpus_generation_is_offline() -> None:
    plugin = _plugin()
    family_case = _family_case(num_agents=1)
    assert plugin.generator(family_case) is None
