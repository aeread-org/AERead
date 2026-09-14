"""What the verifier does at each edge it enforces.

None of these boundaries was tested. They decide whether an award counts, and a
$275 swing in regret rides on the service minimum, so each one is pinned here
with an award placed exactly on the edge and one step off it.
"""

from __future__ import annotations

import copy
import math

import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
)
from aeread_families.procurement_allocation.inference_case_matrix import (
    build_inference_case_matrix,
)

WORLD = "price_low_is_good__yield"
ON_TIME = 0.99
ORDER = 20


@pytest.fixture(scope="module")
def payload() -> dict:
    cases = {c["case_id"].rsplit(".", 1)[-1]: c
             for c in build_inference_case_matrix(surface="labeled")}
    return cases[WORLD]["payload"]


def _first_per_component(case) -> list[str]:
    seen: dict[str, str] = {}
    for supplier in case["suppliers"]:
        seen.setdefault(supplier["component"], str(supplier["supplier_id"]))
    return list(seen.values())


def play(payload: dict, *, quantities=None, skip_sample_for=(), cover_all=True):
    """Qualify one supplier per component, then award. Returns the outcome."""
    plugin = ProcurementAllocationPlugin()
    case = plugin.validate_payload(payload)
    phase = plugin.phases(case)[0]
    state = plugin.initial_state(case, None)
    ids = _first_per_component(case)
    script: list[dict] = []
    for sid in ids:
        script.append({"action": "request_quote", "supplier_id": sid, "message": "q"})
        if sid not in skip_sample_for:
            script.append({"action": "request_sample", "supplier_id": sid, "message": "s"})
    lines = [{"offer_id": f"offer_{sid}_v1",
              "quantity": (quantities or {}).get(sid, ORDER)}
             for sid in (ids if cover_all else ids[:1])]
    script.append({"action": "submit_award", "award_lines": lines, "reason": None})
    for action in script:
        if state["done"]:
            break
        parsed = plugin.parse_action(case, state, "buyer", phase, action)
        if not parsed.ok:
            return {"parse_error": parsed.error_code}
        legality = plugin.legal(case, state, "buyer", phase, parsed.action)
        state = plugin.step(case, state, phase, {"buyer": ActionEnvelope(
            "buyer", legality.legal, parsed.action, parsed, legality)}).state
    terminal = plugin.terminal(case, state)
    return plugin.outcome(case, terminal)


def uniform(payload: dict, yield_rate: float) -> dict:
    out = copy.deepcopy(payload)
    for supplier in out["suppliers"]:
        supplier["private_terms"]["quality"]["verified_yield_rate"] = yield_rate
        supplier["private_terms"]["on_time_probability"] = ON_TIME
        supplier["private_terms"]["quality"]["observed_defects"] = round(
            8 * (1.0 - yield_rate))
    return out


# --- order-shape boundaries -------------------------------------------------


def test_an_order_at_capacity_is_accepted(payload: dict) -> None:
    assert play(payload)["violations"] == []


def test_one_unit_above_capacity_is_rejected(payload: dict) -> None:
    case = ProcurementAllocationPlugin().validate_payload(payload)
    sid = _first_per_component(case)[0]
    violations = play(payload, quantities={sid: ORDER + 1})["violations"]
    assert f"{sid}.over_capacity" in violations


def test_one_unit_below_the_minimum_order_is_rejected(payload: dict) -> None:
    case = ProcurementAllocationPlugin().validate_payload(payload)
    sid = _first_per_component(case)[0]
    moq = int(next(s for s in case["suppliers"]
                   if str(s["supplier_id"]) == sid)["private_terms"]["moq"])
    violations = play(payload, quantities={sid: moq - 1})["violations"]
    assert f"{sid}.below_moq" in violations


def test_a_quantity_off_the_order_step_is_rejected(payload: dict) -> None:
    case = ProcurementAllocationPlugin().validate_payload(payload)
    sid = _first_per_component(case)[0]
    moq = int(next(s for s in case["suppliers"]
                   if str(s["supplier_id"]) == sid)["private_terms"]["moq"])
    violations = play(payload, quantities={sid: moq + 1})["violations"]
    assert f"{sid}.invalid_order_step" in violations


# --- evidence boundaries ----------------------------------------------------


def test_awarding_a_supplier_that_was_never_quoted_is_an_unknown_offer(payload: dict) -> None:
    case = ProcurementAllocationPlugin().validate_payload(payload)
    second = _first_per_component(case)[1]
    out = play(payload, skip_sample_for=(second,))
    assert any("unknown_offer" in v or "sample_not_verified" in v for v in out["violations"])


def test_an_award_that_covers_one_component_completes_no_kits(payload: dict) -> None:
    out = play(payload, cover_all=False)
    assert out["completed_kits"] == 0
    assert "minimum_service_not_met" in out["violations"]


# --- the service minimum, which decides feasibility -------------------------


def tipping_yield(payload: dict) -> float:
    case = ProcurementAllocationPlugin().validate_payload(payload)
    return case["objective"]["minimum_service_kits"] / (ORDER * ON_TIME)


def test_an_award_exactly_on_the_service_minimum_is_feasible(payload: dict) -> None:
    """Exact arithmetic lands on the threshold; floating point must not sink it.

    Completed kits are floor(expected + 1e-12) for this reason. Without the
    epsilon a yield that reaches the minimum exactly rounds to one kit short and
    a feasible award is scored as a failure.
    """
    edge = tipping_yield(payload)
    out = play(uniform(payload, edge), quantities=None)
    assert out["completed_kits"] == int(round(ORDER * edge * ON_TIME))
    assert out["violations"] == []
    assert out["feasible_award"] is True


def test_a_hair_below_the_service_minimum_is_infeasible(payload: dict) -> None:
    edge = tipping_yield(payload)
    out = play(uniform(payload, edge - 1e-8))
    assert "minimum_service_not_met" in out["violations"]
    assert out["feasible_award"] is False


def test_the_threshold_is_a_floor_not_a_rounding(payload: dict) -> None:
    """17.99 kits is 17, not 18. The buyer does not get credit for nearly."""
    case = ProcurementAllocationPlugin().validate_payload(payload)
    minimum = case["objective"]["minimum_service_kits"]
    edge = tipping_yield(payload)
    out = play(uniform(payload, edge * 0.9995))
    expected = ORDER * edge * 0.9995 * ON_TIME
    assert expected > minimum - 1
    assert out["completed_kits"] == math.floor(expected + 1e-12)
    assert out["completed_kits"] < minimum


def test_an_infeasible_award_scores_as_a_deferral_minus_what_it_spent(payload: dict) -> None:
    """The buyer does not pay for goods it is not credited with."""
    out = play(uniform(payload, tipping_yield(payload) - 1e-8))
    assert out["feasible_award"] is False
    assert out["contribution_margin_usd"] == pytest.approx(-out["information_cost_usd"])
