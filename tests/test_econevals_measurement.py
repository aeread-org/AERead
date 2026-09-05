"""Tests for the econevals two-leaf measurement declarations (spec sections 2/4).

Structural tests (leaf shape, contract validity, ``build_scorer`` wiring) run
everywhere. The five QC Gate-2 goldens and the component parity checks
delegate to the pinned upstream bridge for whichever values genuinely
require it (constructing/validating a scripted submission) and are skipped,
never faked, when no bridge interpreter is provisioned -- same
``_bridge()``/skip convention as ``tests/test_econevals_cases.py``/
``tests/test_econevals_environment.py``.

Each golden constructs one scripted (never model-generated) terminal
attempt -- the same shape ``environment.py``'s own ``_submit_*`` helpers
record -- and feeds it straight to ``measurement.py``'s real scorer, exactly
as ``environment.py``'s ``build_scorer``/``EconevalsScorer.score_terminal_state``
would for a completed episode. No tool body, solver, or scoring rule is
reimplemented here: every legality/optimum value a golden depends on either
comes from the case's own imported ``gold_optimum`` or from a direct bridge
call, identical in kind to the ones ``cases.py``/``environment.py`` already
make.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.measurement import (
    MeasurementContractError,
    ScoreEnvelope,
    ValidityReport,
)
from aeread_families.econevals import measurement as m
from aeread_families.econevals.cases import TRACKS
from aeread_families.econevals.econevals_bridge import (
    EconevalsBridge,
    EconevalsBridgeUnavailableError,
    discover_bridge_python,
)

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


def _payload(split: str, case_id: str) -> dict[str, Any]:
    path = CASES_DIR / split / f"{case_id}.json"
    if not path.is_file():
        pytest.skip(f"no checked-in case found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


# ---------------------------------------------------------------------------
# Leaf/contract shape (no bridge needed).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("track", TRACKS)
def test_build_gate_leaf_is_the_shared_shape_declared_in_spec_section_2(track: str) -> None:
    leaf = m.build_gate_leaf(track)
    assert leaf.verifier.verifier_family == "rule_constraint"
    assert leaf.verifier.reference.reference_kind == "constraint_satisfaction"
    assert leaf.verifier.evaluation_class == "deterministic"
    assert leaf.estimand.input_scope == "answer"
    assert leaf.estimand.units == "pass"
    assert leaf.verifier.objective_scope is None


@pytest.mark.parametrize(
    "track,direction,units",
    [
        ("procurement", "maximize", "workers_supported"),
        ("scheduling", "minimize", "blocking_pairs"),
        ("pricing", "maximize", "profit_usd"),
    ],
)
def test_build_objective_leaf_matches_the_per_track_table(track, direction, units) -> None:
    gold_optimum = {"sentinel": True}
    leaf = m.build_objective_leaf(track, gold_optimum)
    assert leaf.verifier.verifier_family == "objective_reference"
    assert leaf.verifier.reference.reference_kind == "exact_optimum"
    assert leaf.estimand.input_scope == "terminal_state"
    assert leaf.estimand.direction == direction
    assert leaf.estimand.units == units
    assert leaf.verifier.objective_scope is not None
    assert leaf.verifier.objective_scope.objective_id == leaf.estimand.estimand_id


def test_build_objective_leaf_source_sha256_is_sensitive_to_the_cases_own_gold_optimum() -> None:
    leaf_a = m.build_objective_leaf("procurement", {"opt_utility": 1.0})
    leaf_b = m.build_objective_leaf("procurement", {"opt_utility": 2.0})
    assert leaf_a.verifier.reference.source_sha256 != leaf_b.verifier.reference.source_sha256


@pytest.mark.parametrize(
    "split,case_id",
    [
        ("procurement_basic", "econevals.procurement.basic.0"),
        ("scheduling_basic", "econevals.scheduling.basic.0"),
        ("pricing_basic", "econevals.pricing.basic.0"),
    ],
)
def test_build_scorer_declares_exactly_two_leaves_for_a_checked_in_case(split, case_id) -> None:
    scorer = m.build_scorer(_payload(split, case_id))
    assert len(scorer.leaves) == 2
    assert scorer.gate_leaf is scorer.leaves[0]
    assert scorer.objective_leaf is scorer.leaves[1]


def test_an_unknown_track_is_refused_by_every_builder() -> None:
    with pytest.raises(ValueError):
        m.build_gate_leaf("not_a_track")
    with pytest.raises(ValueError):
        m.build_objective_leaf("not_a_track", {})
    with pytest.raises(ValueError):
        m.build_leaves("not_a_track", {})


# ---------------------------------------------------------------------------
# Golden 1 -- successful (pricing): prices set to get_monopoly_prices's own
# output every period. No bridge call is needed to construct this golden:
# the case's own gold_optimum already carries, per period, the exact profit
# a monopoly-priced submission earns (computed once at import time by the
# SAME upstream get_monopoly_prices/get_profits pair) -- see the parity
# check below for an independent re-derivation of that same number.
# ---------------------------------------------------------------------------


def test_golden_1_successful_pricing_gate_passes_and_objective_matches_the_optimum() -> None:
    payload = _payload("pricing_basic", "econevals.pricing.basic.0")
    gold_optimum = payload["gold_optimum"]
    product_ids = payload["generated_instance"]["product_ids"]
    period = payload["pins"]["max_steps"] - 1

    prices = dict(zip(product_ids, gold_optimum["prices_by_period"][period]))
    profits = dict(zip(product_ids, gold_optimum["profits_by_period"][period]))
    attempt = {"period": period, "error": False, "prices": prices, "profits": profits}

    scorer = m.build_scorer(payload)
    gate, objective = scorer.score_terminal_state({"attempts": [attempt]})

    assert gate.status == "ok"
    assert gate.primary.value == 1.0
    assert objective is not None
    assert objective.status == "ok"
    v_star = objective.reference_values["v_star"].value
    assert objective.primary.value == pytest.approx(v_star, abs=1e-6)


# ---------------------------------------------------------------------------
# Golden 2 -- valid-but-poor (scheduling): a legal bijection built from a
# deliberately reversed preference order, producing far more than the
# Basic threshold of 1 blocking pair -- gate passes, objective is scored at
# a below-optimum (nonzero) value. Distinct from golden 3's illegality.
# ---------------------------------------------------------------------------


def test_golden_2_valid_but_poor_scheduling_gate_passes_but_objective_is_suboptimal() -> None:
    bridge = _bridge()
    payload = _payload("scheduling_basic", "econevals.scheduling.basic.0")
    instance = payload["generated_instance"]
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
    scorer = m.build_scorer(payload)
    gate, objective = scorer.score_terminal_state({"attempts": [attempt]})

    assert gate.status == "ok"
    assert gate.primary.value == 1.0
    assert objective is not None
    assert objective.status == "ok"
    assert objective.primary.value == float(len(blocking_pairs))
    assert objective.reference_values["v_star"].value == 0.0
    assert objective.primary.value > objective.reference_values["v_star"].value


# ---------------------------------------------------------------------------
# Golden 3 -- invalid-unauthorized (procurement): a submission whose total
# cost exceeds budget. evaluate_alloc returns is_feasible=False with a
# populated reason; the gate is scored (a real domain fact) but FAILS, and
# the objective leaf is never scored at all -- distinct from golden 4's
# admission-layer (invalid_measurement) failure.
# ---------------------------------------------------------------------------


def test_golden_3_invalid_unauthorized_procurement_gate_fails_and_objective_is_not_scored() -> None:
    bridge = _bridge()
    payload = _payload("procurement_basic", "econevals.procurement.basic.0")
    instance = payload["generated_instance"]

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
    scorer = m.build_scorer(payload)
    gate, objective = scorer.score_terminal_state({"attempts": [attempt]})

    assert gate.status == "ok"
    assert gate.primary.value == 0.0
    assert gate.primary.metadata["reason"] == result["invalid_reason"]
    assert objective is None, "an illegal allocation must never reach the objective leaf"


def test_golden_3_companion_unknown_offer_id_is_a_gate_failure_not_a_crash() -> None:
    """Mirrors the environment-level companion test: never a raw AssertionError
    at the measurement layer either -- environment.py's pre-validation already
    retypes this as ``error="illegal_action"`` before it ever reaches here."""
    payload = _payload("procurement_basic", "econevals.procurement.basic.0")
    attempt = {
        "period": 0,
        "error": "illegal_action",
        "error_message": "unknown offer ids: ['Offer_does_not_exist']",
    }
    scorer = m.build_scorer(payload)
    gate, objective = scorer.score_terminal_state({"attempts": [attempt]})
    assert gate.status == "ok"
    assert gate.primary.value == 0.0
    assert objective is None


# ---------------------------------------------------------------------------
# Golden 4 -- malformed-operational (scheduling): submit_assignment's own
# argument is prose, not a parseable dict -- upstream's own parse_dict fails
# all three of its parse strategies. Must report invalid_measurement (the
# measurement_validity layer), never an economic zero. No bridge call is
# ever reachable on this path (environment.py's own _submit_scheduling
# returns before calling the bridge), so this golden needs none either.
# ---------------------------------------------------------------------------


def test_golden_4_malformed_operational_scheduling_is_invalid_measurement_not_a_zero() -> None:
    payload = _payload("scheduling_basic", "econevals.scheduling.basic.1")
    attempt = {
        "period": 0,
        "error": "malformed_input",
        "error_message": "could not parse assignment as a dict",
    }
    scorer = m.build_scorer(payload)
    gate, objective = scorer.score_terminal_state({"attempts": [attempt]})

    assert gate.status == "invalid_measurement"
    assert gate.primary is None
    assert gate.validity.status == "invalid"
    assert gate.validity.reasons == ("malformed_submission",)
    assert objective is None


def test_golden_4_is_not_conflatable_with_golden_3s_domain_legality_failure() -> None:
    """The two failure golden's ScoreEnvelope.status values must differ."""
    scheduling_payload = _payload("scheduling_basic", "econevals.scheduling.basic.1")
    malformed_gate, _ = m.build_scorer(scheduling_payload).score_terminal_state(
        {
            "attempts": [
                {"period": 0, "error": "malformed_input", "error_message": "x"}
            ]
        }
    )
    illegal_gate, _ = m.build_scorer(
        _payload("procurement_basic", "econevals.procurement.basic.0")
    ).score_terminal_state(
        {
            "attempts": [
                {
                    "period": 0,
                    "error": "illegal_action",
                    "error_message": "unknown offer ids: ['x']",
                }
            ]
        }
    )
    assert malformed_gate.status == "invalid_measurement"
    assert illegal_gate.status == "ok"
    assert malformed_gate.status != illegal_gate.status


# ---------------------------------------------------------------------------
# Golden 5 -- degenerate-reference (procurement, hand-authored): a
# single-entry-per-item-group menu where upstream's own start_alloc is
# already feasible and optimal, forcing V_LB == V_agent == V_UB. Built by
# hand (not one of the 8 pilot seeds) and cross-checked against the real
# solver (bridge-gated) -- never asserted purely by construction.
# ---------------------------------------------------------------------------


def _degenerate_procurement_instance() -> dict[str, Any]:
    # One item, one menu entry, a budget that buys exactly one unit: the
    # instance's own do-nothing-else start_alloc is the ONLY feasible
    # allocation buying anything at all, and therefore trivially optimal.
    return {
        "menu": {"E1": {"type": "basic", "contents": {"A": 1}, "cost": 1.0}},
        "budget": 1.0,
        "item_groups": [["A"]],
        "item_to_effectiveness": {"A": 1},
        "start_alloc": {"E1": 1},
        "group_weights": [1.0],
        "agg_type": "prod",
    }


def test_golden_5_degenerate_reference_procurement_has_zero_regret_without_dividing_by_zero() -> None:
    bridge = _bridge()
    instance = _degenerate_procurement_instance()

    gold_optimum = bridge.procurement_reference(
        instance=instance, group_weights=instance["group_weights"], agg_type=instance["agg_type"]
    )
    assert gold_optimum["is_feasible"] is True
    # The exact-optimum solver finds no allocation better than start_alloc.
    assert gold_optimum["opt_alloc"] == instance["start_alloc"]

    eval_start = bridge.procurement_evaluate(
        instance=instance,
        alloc=instance["start_alloc"],
        group_weights=instance["group_weights"],
        agg_type=instance["agg_type"],
    )
    assert eval_start["is_feasible"] is True
    # V_LB (this witnessed feasible submission) == V_UB (the certified exact
    # optimum): verifier_taxonomy.md section 5.2's "equality of the bounds
    # yields exact regret" -- exercised here at zero, never a division.
    assert eval_start["utility"] == gold_optimum["opt_utility"]

    attempt = {
        "period": 0,
        "error": False,
        "alloc": instance["start_alloc"],
        "is_feasible": eval_start["is_feasible"],
        "invalid_reason": eval_start["invalid_reason"],
        "cost": eval_start["cost"],
        "utility": eval_start["utility"],
    }
    scorer = m.build_scorer(
        {"track": "procurement", "generated_instance": instance, "gold_optimum": gold_optimum}
    )
    gate, objective = scorer.score_terminal_state({"attempts": [attempt]})

    assert gate.status == "ok"
    assert gate.primary.value == 1.0
    assert objective is not None
    assert objective.status == "ok"
    v_agent = objective.primary.value
    v_star = objective.reference_values["v_star"].value
    assert v_agent == v_star
    regret = v_star - v_agent
    assert regret == 0.0
    # The whole point of this golden: nothing above ever computed
    # (V_UB - B) as a denominator, so there was never a zero-headroom edge
    # to divide by in the first place -- both values are finite MetricValues
    # by construction (MetricValue itself would refuse a non-finite one).


# ---------------------------------------------------------------------------
# Component parity (mirroring tau3_retail's parity.py pattern): the recorded
# scoring inputs for a golden equal an INDEPENDENT second upstream call on
# the identical scripted trajectory.
# ---------------------------------------------------------------------------


def test_parity_pricing_profit_matches_an_independent_bridge_call() -> None:
    bridge = _bridge()
    payload = _payload("pricing_basic", "econevals.pricing.basic.0")
    instance = payload["generated_instance"]
    gold_optimum = payload["gold_optimum"]
    product_ids = instance["product_ids"]
    period = payload["pins"]["max_steps"] - 1
    prices = dict(zip(product_ids, gold_optimum["prices_by_period"][period]))

    independent_profits = bridge.pricing_profits(instance=instance, period=period, prices=prices)
    recorded_profits = dict(zip(product_ids, gold_optimum["profits_by_period"][period]))
    assert independent_profits == recorded_profits

    attempt = {"period": period, "error": False, "prices": prices, "profits": independent_profits}
    scorer = m.build_scorer(payload)
    _, objective = scorer.score_terminal_state({"attempts": [attempt]})
    assert objective.primary.value == pytest.approx(sum(recorded_profits.values()), abs=1e-6)


def test_parity_procurement_opt_utility_matches_an_independent_bridge_call() -> None:
    bridge = _bridge()
    payload = _payload("procurement_basic", "econevals.procurement.basic.0")
    instance = payload["generated_instance"]
    recorded_gold_optimum = payload["gold_optimum"]

    independent_gold_optimum = bridge.procurement_reference(
        instance=instance, group_weights=instance["group_weights"], agg_type=instance["agg_type"]
    )
    assert independent_gold_optimum["opt_alloc"] == recorded_gold_optimum["opt_alloc"]
    assert independent_gold_optimum["opt_utility"] == recorded_gold_optimum["opt_utility"]

    scorer = m.build_scorer(payload)
    attempt = {
        "period": 0,
        "error": False,
        "alloc": independent_gold_optimum["opt_alloc"],
        "is_feasible": True,
        "invalid_reason": "",
        "cost": independent_gold_optimum["opt_cost"],
        "utility": independent_gold_optimum["opt_utility"],
    }
    _, objective = scorer.score_terminal_state({"attempts": [attempt]})
    assert objective.primary.value == recorded_gold_optimum["opt_utility"]
    assert objective.reference_values["v_star"].value == independent_gold_optimum["opt_utility"]


def test_parity_scheduling_blocking_pairs_matches_an_independent_bridge_call() -> None:
    bridge = _bridge()
    payload = _payload("scheduling_basic", "econevals.scheduling.basic.0")
    instance = payload["generated_instance"]
    worker_ids = instance["worker_ids"]
    task_ids = instance["task_ids"]
    matching = dict(zip(worker_ids, reversed(task_ids)))

    first = bridge.scheduling_blocking_pairs(
        matching=matching, worker_prefs=instance["worker_prefs"], task_prefs=instance["task_prefs"]
    )
    second = bridge.scheduling_blocking_pairs(
        matching=matching, worker_prefs=instance["worker_prefs"], task_prefs=instance["task_prefs"]
    )
    assert first == second

    scorer = m.build_scorer(payload)
    attempt = {
        "period": 0,
        "error": False,
        "matching": matching,
        "valid": True,
        "reason": "",
        "blocking_pairs": second,
    }
    _, objective = scorer.score_terminal_state({"attempts": [attempt]})
    assert objective.primary.value == float(len(first))


# ---------------------------------------------------------------------------
# Robustness: no attempts recorded at all (episode terminated with nothing
# submitted) is also an admission-layer failure, never an economic zero.
# ---------------------------------------------------------------------------


def test_score_terminal_state_with_no_attempts_is_invalid_measurement() -> None:
    payload = _payload("procurement_basic", "econevals.procurement.basic.0")
    scorer = m.build_scorer(payload)
    gate, objective = scorer.score_terminal_state({"attempts": []})
    assert gate.status == "invalid_measurement"
    assert objective is None


def test_unrecognized_attempt_error_is_refused_rather_than_silently_scored() -> None:
    payload = _payload("procurement_basic", "econevals.procurement.basic.0")
    scorer = m.build_scorer(payload)
    with pytest.raises(ValueError):
        scorer.score_attempt({"period": 0, "error": "not_a_real_error_code"})


def test_score_envelope_contract_refuses_an_ok_status_without_a_primary() -> None:
    leaf = m.build_gate_leaf("procurement")
    with pytest.raises(MeasurementContractError):
        ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=ValidityReport("valid"),
            evidence_refs=(),
        )
