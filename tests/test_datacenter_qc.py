"""Quality control for the data-center family.

Three layers that together say "the engine is right", as opposed to "the engine
still returns the number it returned last time":

1. **Accounting identities** hold for every world in the pack, not just a
   fixture. Sources equal uses, principal rolls forward, and the three seat
   NPVs sum to the reported total.
2. **Metamorphic properties**: a directional change to one input must move the
   outcome the way finance says it must. These catch sign errors and
   mis-wired terms that a golden-value test cannot.
3. **Calibration bounds**: every generated magnitude sits inside a published
   2026 market range, so the worlds cannot silently drift back to toy scale.
"""

from __future__ import annotations

import copy
import json

import pytest

from aeread_families.datacenter_development.cashflow import ProjectFacts, simulate_project
from aeread_families.datacenter_development.stack_worlds import (
    CAPACITY_KW,
    DEFAULT_OUTPUT_ROOT,
    HORIZON,
    evaluate_stack,
    load_pack_manifest,
)

SEQUENCE = ("land", "power", "epc", "service", "land_amendment", "loan")


def _payload(file_name: str) -> dict:
    return json.loads((DEFAULT_OUTPUT_ROOT / file_name).read_text())["payload"]


def _worlds() -> list[dict]:
    return [_payload(w["file"]) for w in load_pack_manifest()["worlds"]]


def _scripted(payload: dict) -> dict:
    return {k: payload["scripted_developer"][f"{k}_terms"] for k in SEQUENCE}


def _evaluate(payload: dict, terms: dict) -> dict:
    return evaluate_stack(payload["project_facts"], terms)


# ---------------------------------------------------------------- identities


def test_every_world_satisfies_the_ledger_identities() -> None:
    """Sources equal uses and principal rolls forward, in every world."""
    for payload in _worlds():
        terms = _scripted(payload)
        # simulate_project raises on any identity violation; reaching the
        # assertions below means every month reconciled.
        outcome = _evaluate(payload, terms)
        assert outcome["constraints_satisfied"] is True
        assert (
            outcome["developer_equity_npv_cents"]
            + outcome["lender_npv_cents"]
            + outcome["customer_npv_cents"]
            == outcome["total_project_npv_cents"]
        )


def test_walk_away_is_worse_than_the_negotiated_outcome_everywhere() -> None:
    """Transacting must beat the declared outside option, or the world is broken."""
    for world in load_pack_manifest()["worlds"]:
        payload = _payload(world["file"])
        feasible = world["mechanism"]["feasible_path"]["developer_equity_npv_cents"]
        walk = payload["outside_option"]["developer_equity_npv_cents"]
        assert walk < 0, world["file"]
        assert feasible > walk, world["file"]


# -------------------------------------------------------------- metamorphic


def test_raising_the_capacity_charge_never_lowers_developer_value() -> None:
    payload = _payload("revenue_without_bankability_001.json")
    terms = _scripted(payload)
    base = _evaluate(payload, terms)["developer_equity_npv_cents"]

    richer = copy.deepcopy(terms)
    richer["service"]["monthly_capacity_charge_cents_per_kw"] += 2_000
    assert _evaluate(payload, richer)["developer_equity_npv_cents"] > base


def test_raising_the_epc_price_never_raises_developer_value() -> None:
    payload = _payload("revenue_without_bankability_001.json")
    terms = _scripted(payload)
    base = _evaluate(payload, terms)["developer_equity_npv_cents"]

    dearer = copy.deepcopy(terms)
    extra = 1_000_000_000
    dearer["epc"]["contract_price_cents"] += extra
    dearer["epc"]["payment_schedule"] = [
        dict(step) for step in dearer["epc"]["payment_schedule"]
    ]
    dearer["epc"]["payment_schedule"][-1]["amount_cents"] += extra
    assert _evaluate(payload, dearer)["developer_equity_npv_cents"] < base


def test_energization_that_delays_operations_lowers_developer_value() -> None:
    """Only a delay that actually moves commercial operation destroys value.

    Slipping energisation while construction is still the binding constraint
    saves demand charges on power the project cannot yet use, so the naive
    property "later energisation is always worse" is false. The property that
    must hold is about the date that drives commercial operation.
    """
    payload = _payload("revenue_without_bankability_001.json")
    terms = _scripted(payload)
    base_outcome = _evaluate(payload, terms)
    base = base_outcome["developer_equity_npv_cents"]
    completion = terms["epc"]["guaranteed_completion_month"]

    binding = copy.deepcopy(terms)
    binding["power"]["energization_month"] = completion + 4
    delayed = _evaluate(payload, binding)

    assert delayed["cod_month"] is None or delayed["cod_month"] > base_outcome["cod_month"]
    assert delayed["developer_equity_npv_cents"] < base


def test_discounting_actually_bites() -> None:
    """A positive discount rate must reduce a positive future-heavy NPV."""
    payload = _payload("revenue_without_bankability_001.json")
    terms = _scripted(payload)
    discounted = _evaluate(payload, terms)["developer_equity_npv_cents"]

    undiscounted_facts = dict(payload["project_facts"])
    undiscounted_facts["developer_discount_rate_bps_annual"] = 0
    undiscounted = evaluate_stack(undiscounted_facts, terms)["developer_equity_npv_cents"]

    assert payload["project_facts"]["developer_discount_rate_bps_annual"] > 0
    assert discounted < undiscounted


def test_more_leverage_lowers_debt_service_coverage() -> None:
    payload = _payload("covenant_cliff_001.json")
    terms = _scripted(payload)
    base = _evaluate(payload, terms)["minimum_dscr_bps"]

    levered = copy.deepcopy(terms)
    levered["loan"]["advance_rate_bps"] = min(
        10_000, levered["loan"]["advance_rate_bps"] + 1_000
    )
    levered["loan"]["maximum_loan_to_cost_bps"] = levered["loan"]["advance_rate_bps"]
    assert base is not None
    assert _evaluate(payload, levered)["minimum_dscr_bps"] <= base


# -------------------------------------------------------------- calibration

# Published 2026 reference ranges. Sources are recorded in
# docs/families/datacenter/design_findings_2026-09.md.
CALIBRATION = {
    "epc_cost_per_mw_usd": (8_000_000, 13_000_000),
    "capacity_charge_per_kw_month_usd": (130, 400),
    "loan_spread_bps": (250, 450),
    "loan_to_cost_bps": (5_000, 7_000),
    "epc_delay_cap_fraction_of_price": (0.05, 0.10),
    "lease_term_months": (120, 240),
}


def test_generated_worlds_sit_inside_published_market_ranges() -> None:
    for world in load_pack_manifest()["worlds"]:
        payload = _payload(world["file"])
        scripted = _scripted(payload)
        name = world["file"]

        megawatts = CAPACITY_KW / 1000
        epc_per_mw = scripted["epc"]["contract_price_cents"] / 100 / megawatts
        low, high = CALIBRATION["epc_cost_per_mw_usd"]
        assert low <= epc_per_mw <= high, f"{name}: ${epc_per_mw:,.0f}/MW"

        charge = scripted["service"]["monthly_capacity_charge_cents_per_kw"] / 100
        low, high = CALIBRATION["capacity_charge_per_kw_month_usd"]
        assert low <= charge <= high, f"{name}: ${charge}/kW/month"

        low, high = CALIBRATION["loan_spread_bps"]
        assert low <= scripted["loan"]["spread_bps"] <= high, name

        low, high = CALIBRATION["loan_to_cost_bps"]
        assert low <= scripted["loan"]["maximum_loan_to_cost_bps"] <= high, name

        cap_fraction = (
            scripted["epc"]["delay_liquidated_damages_cap_cents"]
            / scripted["epc"]["contract_price_cents"]
        )
        low, high = CALIBRATION["epc_delay_cap_fraction_of_price"]
        assert low <= cap_fraction <= high, f"{name}: {cap_fraction:.3f}"

        low, high = CALIBRATION["lease_term_months"]
        assert low <= scripted["service"]["initial_term_months"] <= high, name


def test_worlds_exercise_the_subsystems_the_plan_declares() -> None:
    """Energy, floating rates and discounting must not be silently switched off."""
    for world in load_pack_manifest()["worlds"]:
        facts = _payload(world["file"])["project_facts"]
        name = world["file"]
        assert facts["horizon_months"] == HORIZON >= 24, name
        assert facts["energy_kwh_per_kw_month"] > 0, name
        assert all(rate > 0 for rate in facts["energy_cost_cents_per_kwh_by_month"]), name
        assert all(rate > 0 for rate in facts["base_rate_bps_by_month"]), name
        assert facts["developer_discount_rate_bps_annual"] > 0, name
        assert facts["lender_discount_rate_bps_annual"] > 0, name
        assert facts["customer_discount_rate_bps_annual"] > 0, name


@pytest.mark.parametrize("field", ("developer", "lender", "customer"))
def test_each_seat_has_its_own_discount_rate(field: str) -> None:
    facts = _payload("covenant_cliff_001.json")["project_facts"]
    rates = {
        seat: facts[f"{seat}_discount_rate_bps_annual"]
        for seat in ("developer", "lender", "customer")
    }
    assert facts[f"{field}_discount_rate_bps_annual"] > 0
    # Equity is priced above debt; a family that collapses them is mis-specified.
    assert rates["developer"] > rates["lender"]
