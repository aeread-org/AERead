"""Provider-free scheduler coverage for the econagent_v1 environment plugin.

Split the same way as ``test_econagent_cases.py``: everything that only
needs the pinned upstream checkout's static files runs unconditionally;
anything that needs a live upstream engine (``initial_state``/``step`` call
the persistent bridge) is bridge-gated and skips, honestly, when no
provisioned interpreter is available -- never faked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.registry import (
    REQUIRED_FAMILY_PLUGIN_HOOKS,
    PluginRegistry,
)
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.econagent_v1 import measurement
from aeread_families.econagent_v1.cases import SCENARIOS
from aeread_families.econagent_v1.econagent_bridge import (
    EconAgentBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econagent_v1.environment import (
    AGENT_MONTH_PHASE,
    EconAgentV1Plugin,
    family_manifest,
    register_plugin,
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


def _case(case_id: str = "econagent.pilot.tiny4x6.seed0") -> CaseManifest:
    path = Path("cases/econagent_v1") / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    manifest = family_manifest()
    registered = register_plugin(registry, plugin=plugin)

    assert registered is plugin
    assert registry.resolve_manifest(manifest) is plugin
    assert set(REQUIRED_FAMILY_PLUGIN_HOOKS) == {
        name
        for name in REQUIRED_FAMILY_PLUGIN_HOOKS
        if callable(getattr(plugin, name, None))
    }


def test_family_manifest_declares_no_optimum_and_one_scripted_policy() -> None:
    manifest = family_manifest()
    assert manifest.measurement.direction == "none"
    assert manifest.measurement.optimum_lower_bound is None
    assert manifest.measurement.optimum_upper_bound is None
    assert manifest.measurement.comparison_baseline is None
    assert manifest.roles["agent"].testable is True
    assert manifest.roles["agent"].scripted_policies == ("complex",)


def test_family_manifest_declares_the_three_leaf_finalize_time_policy() -> None:
    """kernel_scoring_contract_spec.md section 3, migration milestone 2 of 3.

    ``econagent_budget_identity_leaf`` is this family's own already-declared
    ``primary_estimand`` (mirrored above); it and
    ``econagent_tax_bracket_arithmetic_leaf`` (the two ``rule_constraint``
    accounting leaves) gate admission, and ``econagent_macro_trajectory_leaf``
    (comparative, descriptive-only, per ``build_macro_trajectory_leaf``'s own
    docstring) does not -- see ``docs/econagent_adapter_status.md``'s
    "Leaf policy" section for the full reasoning.
    """
    manifest = family_manifest()
    declared = manifest.measurement.finalize_time_leaf_policy()

    assert set(declared.leaf_ids) == {
        measurement.BUDGET_IDENTITY_LEAF_ID,
        measurement.TAX_BRACKET_LEAF_ID,
        measurement.MACRO_TRAJECTORY_LEAF_ID,
    }
    assert declared.primary_leaf_id == measurement.BUDGET_IDENTITY_LEAF_ID
    assert declared.admission_leaf_ids == (
        measurement.BUDGET_IDENTITY_LEAF_ID,
        measurement.TAX_BRACKET_LEAF_ID,
    )
    # Ordering never encodes policy (spec section 3) -- primary first, then
    # lexical leaf_id, matching FamilyScoreSet's own canonicalization.
    assert declared.leaf_ids[0] == declared.primary_leaf_id


def test_phases_is_one_self_looping_simultaneous_phase() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(_case().payload)
    phases = plugin.phases(family_case)

    assert len(phases) == 1
    phase = phases[0]
    assert phase.phase_id == AGENT_MONTH_PHASE
    assert phase.mode == "simultaneous"
    assert phase.actor_selector == "all_agents"
    assert phase.next_phases == (AGENT_MONTH_PHASE,)
    # One logical action per agent seat per month (milestone-3 correction --
    # see cases.py's `build_case` docstring comment for the
    # SchedulerContractError a plain `episode_length` budget produced the
    # first time an episode ran through the real scheduler).
    assert (
        phase.max_logical_actions
        == family_case["scenario"]["n_agents"] * family_case["scenario"]["episode_length"]
    )


def test_eligible_actors_is_every_agent_seat_every_month() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(_case().payload)
    phase = plugin.phases(family_case)[0]

    actors = plugin.eligible_actors(family_case, state={}, phase=phase)
    n_agents = family_case["scenario"]["n_agents"]
    assert set(actors) == {f"agent_{index}" for index in range(n_agents)}


def test_validate_payload_rejects_a_wrong_upstream_commit() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    payload = dict(_case().payload)
    tampered_pins = dict(payload["pins"])
    tampered_pins["upstream_commit"] = "0000000"
    tampered = {"scenario": payload["scenario"], "pins": tampered_pins}
    with pytest.raises(ValueError, match="upstream commit"):
        plugin.validate_payload(tampered)


def test_validate_payload_rejects_a_tampered_config_hash() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    payload = dict(_case().payload)
    tampered_pins = dict(payload["pins"])
    tampered_pins["config_yaml_sha256"] = "0" * 64
    tampered = {"scenario": payload["scenario"], "pins": tampered_pins}
    with pytest.raises(ValueError, match="config_yaml_sha256 mismatch"):
        plugin.validate_payload(tampered)


def test_validate_payload_rejects_n_agents_below_upstream_floor() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    payload = dict(_case().payload)
    tampered_scenario = dict(payload["scenario"])
    tampered_scenario["n_agents"] = 1
    tampered = {"scenario": tampered_scenario, "pins": payload["pins"]}
    with pytest.raises(ValueError, match="n_agents"):
        plugin.validate_payload(tampered)


def test_parse_action_only_accepts_the_declared_acknowledgment_shape() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(_case().payload)
    phase = plugin.phases(family_case)[0]

    ok = plugin.parse_action(family_case, {}, "agent_0", phase, {"acknowledge": True})
    assert ok.ok
    assert ok.action == {"acknowledge": True}

    bad_value = plugin.parse_action(family_case, {}, "agent_0", phase, {"acknowledge": False})
    assert not bad_value.ok
    assert bad_value.error_code == "invalid_month_ack"

    extra_field = plugin.parse_action(
        family_case, {}, "agent_0", phase, {"acknowledge": True, "labor": 1}
    )
    assert not extra_field.ok

    not_an_object = plugin.parse_action(family_case, {}, "agent_0", phase, "yes")
    assert not not_an_object.ok
    assert not_an_object.error_code == "response_not_object"


def test_parse_action_and_legal_reject_a_seat_phase_mismatch() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(_case().payload)
    phase = plugin.phases(family_case)[0]

    mismatched = plugin.parse_action(family_case, {}, "planner", phase, {"acknowledge": True})
    assert not mismatched.ok
    assert mismatched.error_code == "seat_phase_mismatch"

    legality = plugin.legal(family_case, {}, "planner", phase, {"acknowledge": True})
    assert not legality.legal
    assert legality.reason == "seat_phase_mismatch"

    legal_seat = plugin.legal(family_case, {}, "agent_0", phase, {"acknowledge": True})
    assert legal_seat.legal


def test_build_scorer_declares_the_three_measurement_leaves() -> None:
    # Built in milestone 2 (measurement.py) -- see
    # tests/test_econagent_measurement.py for the leaf-declaration and
    # scoring coverage; this only confirms the environment plugin wires the
    # hook through rather than leaving it a stub.
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(_case().payload)
    scorer = plugin.build_scorer(family_case)
    assert len(scorer.leaves) == 3
    assert scorer.budget_identity_leaf.estimand.estimand_id == "econagent_budget_identity"
    assert (
        scorer.tax_bracket_leaf.estimand.estimand_id == "econagent_tax_bracket_arithmetic"
    )
    assert (
        scorer.macro_trajectory_leaf.estimand.estimand_id == "econagent_macro_trajectory"
    )


def test_build_reference_providers_and_generator_are_empty_this_pass() -> None:
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(_case().payload)
    assert plugin.build_reference_providers(family_case) == ()
    assert plugin.generator(family_case) is None


# ---------------------------------------------------------------------------
# Bridge-gated: a full tiny episode through the real upstream engine.
# ---------------------------------------------------------------------------


def test_scripted_tiny_episode_runs_end_to_end_through_the_real_bridge() -> None:
    _require_bridge()
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)

    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    case = _case("econagent.pilot.tiny4x6.seed0")
    family_case = plugin.validate_payload(case.payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, cell=None)

    n_agents = family_case["scenario"]["n_agents"]
    episode_length = family_case["scenario"]["episode_length"]
    months_run = 0
    while state["termination"] is None:
        actors = plugin.eligible_actors(family_case, state, phase)
        assert set(actors) == {f"agent_{index}" for index in range(n_agents)}
        actions = {}
        for seat in actors:
            observation = plugin.observe(family_case, state, seat, phase)
            assert observation["agent_index"] == seat.removeprefix("agent_")
            assert "inventory" in observation and "Coin" in observation["inventory"]
            parsed = plugin.parse_action(
                family_case, state, seat, phase, {"acknowledge": True}
            )
            assert parsed.ok
            legality = plugin.legal(family_case, state, seat, phase, parsed.action)
            assert legality.legal
            actions[seat] = parsed
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
        months_run += 1
        assert months_run <= episode_length  # never overruns the declared budget

    assert months_run == episode_length
    assert state["termination"] == "episode_length_reached"

    terminal = plugin.terminal(family_case, state)
    assert terminal is not None
    assert terminal["reason"] == "episode_length_reached"
    assert terminal["timestep"] == episode_length
    assert len(terminal["final_agents"]) == n_agents
    assert len(terminal["month_actions"]) == episode_length

    outcome = plugin.outcome(family_case, terminal)
    assert outcome["termination_reason"] == "episode_length_reached"
    assert set(outcome["final_inventory_coin"]) == {str(i) for i in range(n_agents)}
    for coin in outcome["final_inventory_coin"].values():
        assert isinstance(coin, float)

    # No live bridge session should remain once the episode is terminal.
    assert plugin._sessions == {}


def test_two_bridge_sessions_do_not_share_state() -> None:
    """Two concurrently-started episodes get two independent bridge sessions."""
    _require_bridge()
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)

    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    case_a = _case("econagent.pilot.tiny4x6.seed0")
    family_case_a = plugin.validate_payload(case_a.payload)
    state_a = plugin.initial_state(family_case_a, cell=None)

    case_b = _case("econagent.pilot.small10x12.seed0")
    family_case_b = plugin.validate_payload(case_b.payload)
    state_b = plugin.initial_state(family_case_b, cell=None)

    assert state_a["bridge_session_id"] != state_b["bridge_session_id"]
    assert state_a["n_agents"] == 4
    assert state_b["n_agents"] == 10
    assert len(plugin._sessions) == 2

    for session_id in list(plugin._sessions):
        plugin._sessions[session_id].close()
        plugin._sessions.pop(session_id)


def test_declared_scenarios_all_appear_on_disk_as_case_files() -> None:
    for scenario in SCENARIOS:
        path = Path("cases/econagent_v1") / f"{scenario['case_id']}.json"
        assert path.is_file(), f"missing case file for {scenario['case_id']!r}"
