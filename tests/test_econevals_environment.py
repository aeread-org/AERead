"""Provider-free scheduler coverage for the econevals environment plugin.

Structural tests (registration, family manifest shape, phase graph, parse
rejections) run everywhere. Tests that actually execute one period through
the plugin's ``step`` -- which delegates to the pinned upstream scoring
primitives via the bridge for a period's terminating submit call -- run for
real when a bridge interpreter is provisioned, and are skipped otherwise
(mirroring ``tests/test_econevals_cases.py``'s ``_bridge()`` convention).

The trailing section (milestone 3) drives full, multi-period episodes
through the REAL kernel scheduler (``run_episode``) with
``harness.ScriptedEconevalsHarness`` -- never ``plugin.step`` called
directly, unlike every test above it -- which is what caught this file's
own ``phases()`` role-vs-seat-id key bug (see the ``observation_schema_by_role``
build note in ``environment.py``): nothing above this section ever went
through ``scheduler._eligible_actors``, so it went undetected through
milestones 1 and 2.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.registry import REQUIRED_FAMILY_PLUGIN_HOOKS, PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import ActionEnvelope, run_episode
from aeread_families.econevals.econevals_bridge import (
    EconevalsBridge,
    EconevalsBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econevals.environment import (
    PERIOD_PHASE,
    ROLE_ID,
    SEAT_ID,
    EconevalsPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.econevals.harness import ScriptedEconevalsHarness

CASES_DIR = Path("cases/econevals")

try:
    BRIDGE_PYTHON = discover_bridge_python()
except EconevalsBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> EconevalsBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return EconevalsBridge(python_executable=BRIDGE_PYTHON)


def _case(split: str, case_id: str) -> CaseManifest:
    path = CASES_DIR / split / f"{case_id}.json"
    if not path.is_file():
        pytest.skip(f"no checked-in case found at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _run_one_period(plugin, family_case, response):
    phases = plugin.phases(family_case)
    state = plugin.initial_state(family_case, None)
    phase = phases[0]
    parsed = plugin.parse_action(family_case, state, SEAT_ID, phase, response)
    assert parsed.ok, parsed.error_code
    legality = plugin.legal(family_case, state, SEAT_ID, phase, parsed.action)
    assert legality.legal
    envelope = ActionEnvelope(
        seat_id=SEAT_ID, valid=True, action=parsed.action, parse=parsed, legality=legality
    )
    return plugin.step(family_case, state, phase, {SEAT_ID: envelope})


# ---------------------------------------------------------------------------
# Registration / family manifest (import-level; no bridge, no case files).
# ---------------------------------------------------------------------------


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = EconevalsPlugin(bridge=None)
    registry = PluginRegistry()
    manifest = family_manifest()
    registered = register_plugin(registry, plugin=plugin)

    assert registered is plugin
    assert registry.resolve_manifest(manifest) is plugin
    assert set(REQUIRED_FAMILY_PLUGIN_HOOKS) == {
        name for name in REQUIRED_FAMILY_PLUGIN_HOOKS if callable(getattr(plugin, name, None))
    }


def test_family_manifest_declares_one_self_looping_period_phase() -> None:
    manifest = family_manifest()
    assert manifest.family.id == "econevals"
    assert manifest.environment.phase_specs == (PERIOD_PHASE,)
    assert set(manifest.roles) == {ROLE_ID}
    assert manifest.roles[ROLE_ID].testable is True


def test_registering_the_same_family_version_twice_is_refused() -> None:
    registry = PluginRegistry()
    register_plugin(registry, plugin=EconevalsPlugin(bridge=None))
    with pytest.raises(Exception):
        register_plugin(registry, plugin=EconevalsPlugin(bridge=None))


@pytest.mark.parametrize(
    "split,case_id",
    [
        ("procurement_basic", "econevals.procurement.basic.0"),
        ("scheduling_basic", "econevals.scheduling.basic.0"),
        ("pricing_basic", "econevals.pricing.basic.0"),
    ],
)
def test_build_scorer_declares_exactly_a_gate_leaf_and_an_objective_leaf(
    split, case_id
) -> None:
    """See ``tests/test_econevals_measurement.py`` for the full leaf/scoring contract."""
    plugin = EconevalsPlugin(bridge=None)
    case = _case(split, case_id)
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    assert len(scorer.leaves) == 2
    assert scorer.gate_leaf.verifier.verifier_family == "rule_constraint"
    assert scorer.objective_leaf.verifier.verifier_family == "objective_reference"


# ---------------------------------------------------------------------------
# validate_payload / phases (no bridge needed).
# ---------------------------------------------------------------------------


def test_validate_payload_accepts_a_checked_in_procurement_case() -> None:
    plugin = EconevalsPlugin(bridge=None)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    assert family_case["track"] == "procurement"
    assert family_case["difficulty"] == "Basic"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {},
        {"track": "procurement"},
        {
            "track": "not_a_track",
            "difficulty": "Basic",
            "seed": 0,
            "generated_instance": {},
            "gold_optimum": {},
            "pins": {"max_steps": 100},
        },
        {
            "track": "procurement",
            "difficulty": "Medium",
            "seed": 0,
            "generated_instance": {},
            "gold_optimum": {},
            "pins": {"max_steps": 100},
        },
    ],
)
def test_validate_payload_rejects_malformed_or_out_of_scope_payloads(bad_payload) -> None:
    plugin = EconevalsPlugin(bridge=None)
    with pytest.raises(ValueError):
        plugin.validate_payload(bad_payload)


def test_phases_is_one_self_looping_period_phase_with_the_case_max_steps() -> None:
    plugin = EconevalsPlugin(bridge=None)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    phases = plugin.phases(family_case)
    assert [(phase.phase_id, phase.mode, phase.next_phases) for phase in phases] == [
        (PERIOD_PHASE, "single", (PERIOD_PHASE,))
    ]
    assert phases[0].max_logical_actions == 100
    assert plugin.eligible_actors(family_case, {}, phases[0]) == (SEAT_ID,)


# ---------------------------------------------------------------------------
# parse_action structural rejections (no bridge needed).
# ---------------------------------------------------------------------------


def test_parse_action_rejects_a_submit_call_that_is_not_last() -> None:
    plugin = EconevalsPlugin(bridge=None)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    phase = plugin.phases(family_case)[0]
    response = {
        "tool_calls": [
            {"id": "1", "name": "submit_purchase_plan", "arguments": {"purchase_plan": {}}},
            {"id": "2", "name": "get_budget", "arguments": {}},
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": {}},
                "result": {"content": {}, "error": False},
            },
            {
                "tool_call_id": "2",
                "name": "get_budget",
                "arguments": {},
                "result": {"content": {}, "error": False},
            },
        ],
    }
    parsed = plugin.parse_action(family_case, {}, SEAT_ID, phase, response)
    assert not parsed.ok
    assert parsed.error_code == "submit_tool_must_be_the_final_call"


def test_parse_action_rejects_a_period_with_no_submit_call_at_all() -> None:
    plugin = EconevalsPlugin(bridge=None)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    phase = plugin.phases(family_case)[0]
    response = {
        "tool_calls": [{"id": "1", "name": "get_budget", "arguments": {}}],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "get_budget",
                "arguments": {},
                "result": {"content": {}, "error": False},
            }
        ],
    }
    parsed = plugin.parse_action(family_case, {}, SEAT_ID, phase, response)
    assert not parsed.ok
    assert parsed.error_code == "submit_tool_must_be_the_final_call"


def test_parse_action_rejects_a_tool_execution_count_mismatch() -> None:
    plugin = EconevalsPlugin(bridge=None)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    phase = plugin.phases(family_case)[0]
    response = {
        "tool_calls": [
            {"id": "1", "name": "submit_purchase_plan", "arguments": {"purchase_plan": {}}}
        ],
        "tool_executions": [],
    }
    parsed = plugin.parse_action(family_case, {}, SEAT_ID, phase, response)
    assert not parsed.ok
    assert parsed.error_code == "tool_execution_count_mismatch"


# ---------------------------------------------------------------------------
# Live period execution (bridge-gated): one full period per track.
# ---------------------------------------------------------------------------


def test_procurement_period_all_zero_allocation_is_feasible_and_free() -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    instance = family_case["generated_instance"]

    alloc = {entry_id: 0 for entry_id in instance["menu"]}
    result = bridge.procurement_evaluate(
        instance=instance,
        alloc=alloc,
        group_weights=instance["group_weights"],
        agg_type=instance["agg_type"],
    )
    attempt = {
        "period": 0,
        "error": False,
        "alloc": alloc,
        "is_feasible": result["is_feasible"],
        "invalid_reason": result["invalid_reason"],
        "cost": result["cost"],
        "utility": result["utility"],
    }
    response = {
        "tool_calls": [
            {"id": "1", "name": "get_budget", "arguments": {}},
            {"id": "2", "name": "submit_purchase_plan", "arguments": {"purchase_plan": {}}},
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "get_budget",
                "arguments": {},
                "result": {"content": {"budget": instance["budget"]}, "error": False},
            },
            {
                "tool_call_id": "2",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": {}},
                "result": {"content": attempt, "error": False},
            },
        ],
    }
    transition = _run_one_period(plugin, family_case, response)
    assert transition.next_phase_id == PERIOD_PHASE
    assert transition.state["period"] == 1
    assert transition.state["attempts"][0]["is_feasible"] is True


def test_procurement_unknown_offer_id_is_a_declared_illegal_action_not_a_crash() -> None:
    """Companion unit test for spec golden 3: never a raw AssertionError."""
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)

    attempt = {
        "period": 0,
        "error": "illegal_action",
        "error_message": "unknown offer ids: ['Offer_does_not_exist']",
    }
    response = {
        "tool_calls": [
            {
                "id": "1",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": {"Offer_does_not_exist": 1}},
            }
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": {"Offer_does_not_exist": 1}},
                "result": {"content": attempt, "error": True},
            }
        ],
    }
    transition = _run_one_period(plugin, family_case, response)
    recorded = transition.state["attempts"][0]
    assert recorded["error"] == "illegal_action"


def test_scheduling_period_valid_bijection_reports_blocking_pairs() -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("scheduling_basic", "econevals.scheduling.basic.0")
    family_case = plugin.validate_payload(case.payload)
    instance = family_case["generated_instance"]

    matching = dict(zip(instance["worker_ids"], instance["task_ids"]))
    blocking_pairs = bridge.scheduling_blocking_pairs(
        matching=matching,
        worker_prefs=instance["worker_prefs"],
        task_prefs=instance["task_prefs"],
    )
    attempt = {
        "period": 0,
        "error": False,
        "matching": matching,
        "valid": True,
        "reason": "",
        "blocking_pairs": blocking_pairs,
    }
    response = {
        "tool_calls": [
            {"id": "1", "name": "submit_assignment", "arguments": {"assignment": matching}}
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "submit_assignment",
                "arguments": {"assignment": matching},
                "result": {"content": attempt, "error": False},
            }
        ],
    }
    transition = _run_one_period(plugin, family_case, response)
    assert transition.state["attempts"][0]["valid"] is True
    assert isinstance(transition.state["attempts"][0]["blocking_pairs"], list)


def test_scheduling_malformed_assignment_is_invalid_measurement_not_a_crash() -> None:
    """Companion check for spec golden 4: parse_dict failure, never an exception."""
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("scheduling_basic", "econevals.scheduling.basic.1")
    family_case = plugin.validate_payload(case.payload)

    attempt = {
        "period": 0,
        "error": "malformed_input",
        "error_message": "could not parse assignment as a dict",
    }
    response = {
        "tool_calls": [
            {
                "id": "1",
                "name": "submit_assignment",
                "arguments": {"assignment": "this is prose, not a dict"},
            }
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "submit_assignment",
                "arguments": {"assignment": "this is prose, not a dict"},
                "result": {"content": attempt, "error": True},
            }
        ],
    }
    transition = _run_one_period(plugin, family_case, response)
    assert transition.state["attempts"][0]["error"] == "malformed_input"


def test_pricing_period_reports_profits_at_submitted_prices() -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("pricing_basic", "econevals.pricing.basic.0")
    family_case = plugin.validate_payload(case.payload)
    instance = family_case["generated_instance"]

    prices = {instance["product_ids"][0]: 12.5}
    profits = bridge.pricing_profits(instance=instance, period=0, prices=prices)
    attempt = {
        "period": 0,
        "error": False,
        "prices": {product_id: float(price) for product_id, price in prices.items()},
        "profits": profits,
    }
    response = {
        "tool_calls": [
            {"id": "1", "name": "set_prices", "arguments": {"prices_dict_str": prices}}
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "set_prices",
                "arguments": {"prices_dict_str": prices},
                "result": {"content": attempt, "error": False},
            }
        ],
    }
    transition = _run_one_period(plugin, family_case, response)
    assert transition.state["attempts"][0]["profits"] == profits


# ---------------------------------------------------------------------------
# QC Gate-2 goldens, driven through the REAL step()/dispatch_submit path
# (spec section 4), not merely hand-constructed ``attempt`` dicts fed
# straight to ``EconevalsScorer.score_terminal_state`` the way
# ``tests/test_econevals_measurement.py``'s goldens do. Those unit tests
# prove the scorer computes the right vector from a given attempt; these
# additionally prove ``_submit_*`` actually PRODUCES that attempt (and
# leaves ``family_case["generated_instance"]`` untouched) for the exact
# scripted scenario spec section 4 names -- see
# ``docs/econevals_review_disposition.md`` finding 2.
# ---------------------------------------------------------------------------


def test_golden_1_successful_pricing_through_step_gate_passes_and_objective_matches_the_optimum() -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("pricing_basic", "econevals.pricing.basic.0")
    family_case = plugin.validate_payload(case.payload)
    instance = family_case["generated_instance"]
    gold_optimum = family_case["gold_optimum"]
    product_ids = instance["product_ids"]
    period = 0

    prices = dict(zip(product_ids, gold_optimum["prices_by_period"][period]))
    profits = bridge.pricing_profits(instance=instance, period=period, prices=prices)
    attempt = {
        "period": period,
        "error": False,
        "prices": {product_id: float(price) for product_id, price in prices.items()},
        "profits": profits,
    }
    response = {
        "tool_calls": [
            {"id": "1", "name": "get_product_ids", "arguments": {}},
            {"id": "2", "name": "set_prices", "arguments": {"prices_dict_str": prices}},
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "get_product_ids",
                "arguments": {},
                "result": {"content": {"product_ids": product_ids}, "error": False},
            },
            {
                "tool_call_id": "2",
                "name": "set_prices",
                "arguments": {"prices_dict_str": prices},
                "result": {"content": attempt, "error": False},
            },
        ],
    }
    transition = _run_one_period(plugin, family_case, response)

    scorer = plugin.build_scorer(family_case)
    gate, objective = scorer.score_terminal_state(transition.state)

    assert gate.status == "ok"
    assert gate.primary.value == 1.0
    assert objective is not None
    assert objective.status == "ok"
    v_star = objective.reference_values["v_star"].value
    assert objective.primary.value == pytest.approx(v_star, abs=1e-6)


def test_golden_2_valid_but_poor_scheduling_through_step_gate_passes_but_objective_is_suboptimal() -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("scheduling_basic", "econevals.scheduling.basic.0")
    family_case = plugin.validate_payload(case.payload)
    instance = family_case["generated_instance"]
    worker_ids = instance["worker_ids"]
    task_ids = instance["task_ids"]

    reversed_matching = dict(zip(worker_ids, reversed(task_ids)))
    validity = bridge.scheduling_validate(
        matching=reversed_matching, worker_ids=worker_ids, task_ids=task_ids
    )
    assert validity["valid"], "the reversed assignment must still be a legal bijection"
    blocking_pairs = bridge.scheduling_blocking_pairs(
        matching=reversed_matching,
        worker_prefs=instance["worker_prefs"],
        task_prefs=instance["task_prefs"],
    )
    assert len(blocking_pairs) > 1, "the reversed matching must be strictly below Basic's own threshold of 1"

    attempt = {
        "period": 0,
        "error": False,
        "matching": reversed_matching,
        "valid": True,
        "reason": "",
        "blocking_pairs": blocking_pairs,
    }
    response = {
        "tool_calls": [
            {
                "id": "1",
                "name": "submit_assignment",
                "arguments": {"assignment": reversed_matching},
            }
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "submit_assignment",
                "arguments": {"assignment": reversed_matching},
                "result": {"content": attempt, "error": False},
            }
        ],
    }
    transition = _run_one_period(plugin, family_case, response)

    scorer = plugin.build_scorer(family_case)
    gate, objective = scorer.score_terminal_state(transition.state)

    assert gate.status == "ok"
    assert gate.primary.value == 1.0
    assert objective is not None
    assert objective.status == "ok"
    assert objective.primary.value == float(len(blocking_pairs))
    assert objective.reference_values["v_star"].value == 0.0
    assert objective.primary.value > objective.reference_values["v_star"].value


def test_golden_3_invalid_unauthorized_procurement_through_step_gate_fails_and_objective_is_not_scored() -> None:
    """Spec golden 3's actual scenario (over-budget submission), not just its
    unknown-offer-id companion above. Also pins down the failure scenario
    named in the second-reviewer report: a future aliasing bug in
    ``_submit_procurement`` that mutated ``generated_instance`` in place
    would be caught here, not silently missed."""
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    instance = family_case["generated_instance"]
    instance_before = canonical_json_bytes(instance)

    over_budget_alloc = {entry_id: 1000 for entry_id in instance["menu"]}
    result = bridge.procurement_evaluate(
        instance=instance,
        alloc=over_budget_alloc,
        group_weights=instance["group_weights"],
        agg_type=instance["agg_type"],
    )
    assert result["is_feasible"] is False
    assert "exceeds budget" in result["invalid_reason"]

    attempt = {
        "period": 0,
        "error": False,
        "alloc": over_budget_alloc,
        "is_feasible": result["is_feasible"],
        "invalid_reason": result["invalid_reason"],
        "cost": result["cost"],
        "utility": result["utility"],
    }
    response = {
        "tool_calls": [
            {
                "id": "1",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": over_budget_alloc},
            }
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": over_budget_alloc},
                "result": {"content": attempt, "error": False},
            }
        ],
    }
    transition = _run_one_period(plugin, family_case, response)

    assert canonical_json_bytes(instance) == instance_before, (
        "generated_instance must never be mutated by _submit_procurement"
    )

    scorer = plugin.build_scorer(family_case)
    gate, objective = scorer.score_terminal_state(transition.state)

    assert gate.status == "ok"
    assert gate.primary.value == 0.0
    assert gate.primary.metadata["reason"] == result["invalid_reason"]
    assert objective is None, "an illegal allocation must never reach the objective leaf"


def test_golden_5_degenerate_reference_procurement_through_step_has_zero_regret() -> None:
    """Spec golden 5: a hand-authored, single-entry-per-item-group menu
    where upstream's own ``start_alloc`` is already feasible and optimal
    (``V_LB == V_agent == V_UB``), driven through the real ``step()`` path
    rather than a hand-typed attempt dict. Mirrors
    ``tests/test_econevals_measurement.py``'s
    ``_degenerate_procurement_instance`` fixture."""
    bridge = _bridge()
    instance = {
        "menu": {"E1": {"type": "basic", "contents": {"A": 1}, "cost": 1.0}},
        "budget": 1.0,
        "item_groups": [["A"]],
        "item_to_effectiveness": {"A": 1},
        "start_alloc": {"E1": 1},
        "group_weights": [1.0],
        "agg_type": "prod",
    }
    gold_optimum = bridge.procurement_reference(
        instance=instance, group_weights=instance["group_weights"], agg_type=instance["agg_type"]
    )
    assert gold_optimum["is_feasible"] is True
    assert gold_optimum["opt_alloc"] == instance["start_alloc"]

    plugin = EconevalsPlugin(bridge=bridge)
    payload = {
        "track": "procurement",
        "difficulty": "Basic",
        "seed": 0,
        "generated_instance": instance,
        "gold_optimum": gold_optimum,
        "pins": {"max_steps": 1},
    }
    family_case = plugin.validate_payload(payload)
    instance_before = canonical_json_bytes(family_case["generated_instance"])

    start_alloc = instance["start_alloc"]
    eval_start = bridge.procurement_evaluate(
        instance=instance,
        alloc=start_alloc,
        group_weights=instance["group_weights"],
        agg_type=instance["agg_type"],
    )
    assert eval_start["is_feasible"] is True
    assert eval_start["utility"] == gold_optimum["opt_utility"]

    attempt = {
        "period": 0,
        "error": False,
        "alloc": start_alloc,
        "is_feasible": eval_start["is_feasible"],
        "invalid_reason": eval_start["invalid_reason"],
        "cost": eval_start["cost"],
        "utility": eval_start["utility"],
    }
    response = {
        "tool_calls": [
            {"id": "1", "name": "submit_purchase_plan", "arguments": {"purchase_plan": start_alloc}}
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": start_alloc},
                "result": {"content": attempt, "error": False},
            }
        ],
    }
    transition = _run_one_period(plugin, family_case, response)

    assert canonical_json_bytes(family_case["generated_instance"]) == instance_before

    scorer = plugin.build_scorer(family_case)
    gate, objective = scorer.score_terminal_state(transition.state)

    assert gate.status == "ok"
    assert gate.primary.value == 1.0
    assert objective is not None
    assert objective.status == "ok"
    v_agent = objective.primary.value
    v_star = objective.reference_values["v_star"].value
    assert v_agent == v_star
    assert v_star - v_agent == 0.0


def test_step_rejects_a_harness_tool_replay_mismatch() -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("procurement_basic", "econevals.procurement.basic.0")
    family_case = plugin.validate_payload(case.payload)
    instance = family_case["generated_instance"]

    response = {
        "tool_calls": [
            {"id": "1", "name": "get_budget", "arguments": {}},
            {"id": "2", "name": "submit_purchase_plan", "arguments": {"purchase_plan": {}}},
        ],
        "tool_executions": [
            {
                "tool_call_id": "1",
                "name": "get_budget",
                "arguments": {},
                # Deliberately wrong: the real budget is instance["budget"].
                "result": {"content": {"budget": instance["budget"] + 1000.0}, "error": False},
            },
            {
                "tool_call_id": "2",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": {}},
                "result": {"content": {"period": 0, "error": False}, "error": False},
            },
        ],
    }
    with pytest.raises(RuntimeError, match="tool replay result differs"):
        _run_one_period(plugin, family_case, response)


# ---------------------------------------------------------------------------
# Milestone 3: full multi-period episodes through the REAL kernel scheduler.
# ---------------------------------------------------------------------------


def _shrunk_case(split: str, case_id: str, *, max_steps: int) -> CaseManifest:
    """A test-scoped copy of a real, pinned pilot case with a much smaller
    ``pins.max_steps``/``episode.max_logical_actions``.

    Keeps the real ``generated_instance``/``gold_optimum`` payload data (so
    every period still drives a real bridge call, exactly as the full
    100-period case would) and only shrinks the episode length, so a test
    can reach a genuine ``"max_periods"`` termination in a handful of
    periods rather than the full pilot budget. ``content_sha256`` is never
    hand-typed -- it is recomputed the same way the real importer does,
    through the kernel's own ``case_content_sha256`` resolver, so
    ``run_episode``'s own cross-check (``case content hash changed after
    plan resolution``) passes for the right reason.
    """
    path = CASES_DIR / split / f"{case_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"] = dict(raw["payload"])
    raw["payload"]["pins"] = dict(raw["payload"]["pins"])
    raw["payload"]["pins"]["max_steps"] = max_steps
    raw["episode"] = dict(raw["episode"])
    raw["episode"]["max_logical_actions"] = max_steps
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econevals_environment_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econevals_environment",
        suite_version="0.1.0",
        block_id="block_econevals_environment",
        sampling_plan_id="sampling_econevals_environment",
        analysis_plan_id="analysis_econevals_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econevals_environment_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({SEAT_ID: "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_scripted_episode(bridge, case, script, *, tmp_path: Path, suffix: str):
    plugin = EconevalsPlugin(bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)

    cell = _cell(case, suffix=suffix)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_econevals_environment_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_econevals_environment_{suffix}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedEconevalsHarness(
        plugin=resolved_plugin, family_case=family_case, evidence=evidence, script=script
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    evidence.seal()
    return harness, result


def test_procurement_full_episode_runs_through_the_real_kernel_scheduler(
    tmp_path: Path,
) -> None:
    """Info tools -> notes -> one ``submit_purchase_plan`` call, every
    period, driven end to end through ``run_episode`` (not ``plugin.step``
    called directly) -- the REAL shared-runner path."""
    bridge = _bridge()
    case = _shrunk_case("procurement_basic", "econevals.procurement.basic.0", max_steps=3)

    script = [
        [
            {"id": "1", "name": "get_budget", "arguments": {}},
            {"id": "2", "name": "get_equipment_information", "arguments": {}},
            {"id": "3", "name": "write_notes", "arguments": {"notes": f"period {period}"}},
            {
                "id": "4",
                "name": "submit_purchase_plan",
                "arguments": {"purchase_plan": {}},
            },
        ]
        for period in range(3)
    ]

    harness, result = _run_scripted_episode(
        bridge, case, script, tmp_path=tmp_path, suffix="procurement"
    )

    assert harness.exhausted is True
    assert result.logical_action_count == 3
    assert [instance.phase_id for instance in result.phase_instances] == [PERIOD_PHASE] * 3
    assert result.terminal["reason"] == "max_periods"
    assert result.terminal["num_attempts"] == 3
    assert all(attempt["is_feasible"] for attempt in result.final_state["attempts"])


def test_scheduling_full_episode_runs_through_the_real_kernel_scheduler(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case = _shrunk_case("scheduling_basic", "econevals.scheduling.basic.0", max_steps=2)
    family_case_probe = EconevalsPlugin(bridge=bridge).validate_payload(case.payload)
    instance = family_case_probe["generated_instance"]
    matching = dict(zip(instance["worker_ids"], instance["task_ids"]))

    script = [
        [
            {"id": "1", "name": "get_worker_ids", "arguments": {}},
            {"id": "2", "name": "get_task_ids", "arguments": {}},
            {"id": "3", "name": "submit_assignment", "arguments": {"assignment": matching}},
        ]
        for _ in range(2)
    ]

    harness, result = _run_scripted_episode(
        bridge, case, script, tmp_path=tmp_path, suffix="scheduling"
    )

    assert harness.exhausted is True
    assert result.logical_action_count == 2
    assert result.terminal["reason"] == "max_periods"
    assert all(attempt["valid"] for attempt in result.final_state["attempts"])


def test_pricing_full_episode_runs_through_the_real_kernel_scheduler(tmp_path: Path) -> None:
    bridge = _bridge()
    case = _shrunk_case("pricing_basic", "econevals.pricing.basic.0", max_steps=2)
    family_case_probe = EconevalsPlugin(bridge=bridge).validate_payload(case.payload)
    product_ids = family_case_probe["generated_instance"]["product_ids"]
    prices = {product_id: 1.0 for product_id in product_ids}

    script = [
        [
            {"id": "1", "name": "get_product_ids", "arguments": {}},
            {"id": "2", "name": "read_notes", "arguments": {"attempt_number": 0}},
            {"id": "3", "name": "set_prices", "arguments": {"prices_dict_str": prices}},
        ]
        for _ in range(2)
    ]

    harness, result = _run_scripted_episode(
        bridge, case, script, tmp_path=tmp_path, suffix="pricing"
    )

    assert harness.exhausted is True
    assert result.logical_action_count == 2
    assert result.terminal["reason"] == "max_periods"
    assert [attempt["prices"] for attempt in result.final_state["attempts"]] == [prices, prices]


def test_scripted_harness_seals_one_tool_invocation_event_per_declared_tool_call(
    tmp_path: Path,
) -> None:
    """The harness's evidence is genuinely sealed (spec's "sealed evidence"):
    once ``EvidenceStore.seal()`` is called, the store round-trips to the
    same seal and every scripted tool call left a
    ``tool_invocation_started``/``tool_invocation_succeeded`` event pair."""
    bridge = _bridge()
    case = _shrunk_case("pricing_basic", "econevals.pricing.basic.0", max_steps=1)
    family_case_probe = EconevalsPlugin(bridge=bridge).validate_payload(case.payload)
    product_ids = family_case_probe["generated_instance"]["product_ids"]
    prices = {product_id: 1.0 for product_id in product_ids}

    script = [
        [
            {"id": "1", "name": "get_product_ids", "arguments": {}},
            {"id": "2", "name": "set_prices", "arguments": {"prices_dict_str": prices}},
        ]
    ]

    plugin = EconevalsPlugin(bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)
    cell = _cell(case, suffix="sealed_evidence")
    evidence = EvidenceStore(
        tmp_path / "evidence_sealed",
        run_plan_id="runplan_econevals_environment_sealed_evidence",
        cell_id=cell.cell_id,
        episode_id="episode_econevals_environment_sealed_evidence",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedEconevalsHarness(
        plugin=resolved_plugin, family_case=family_case, evidence=evidence, script=script
    )
    asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )

    seal = evidence.seal()
    assert seal == evidence.seal()

    event_types = [event.event_type for event in evidence.read_events()]
    assert event_types.count("tool_invocation_started") == 2
    assert event_types.count("tool_invocation_succeeded") == 2
