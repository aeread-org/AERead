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


def _stack(payload: dict, source: str) -> dict:
    if source == "scripted":
        return _scripted(payload)
    return {k: payload["policies"][k]["counter_terms"] for k in SEQUENCE}


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


def test_an_absurd_integer_is_a_model_error_not_an_infrastructure_failure() -> None:
    """A 6,000-digit term must be recorded against the model, not the provider.

    CPython refuses to decode an integer past 4,300 digits, and that refusal is
    raised inside the provider call, so without the guard the scheduler books a
    model error as `child_provider_outcome_unknown` missingness.
    """
    from aeread.shared_runner.task.execution import CanonicalResponse
    from aeread_families.datacenter_development.stack_environment import (
        DataCenterStackPlugin,
    )

    plugin = DataCenterStackPlugin("v2")
    case = plugin.validate_payload(_payload("covenant_cliff_001.json"))
    phase = next(p for p in plugin.phases(case) if p.phase_id == "land_developer_offer")
    absurd = "9" * 6_000
    response = CanonicalResponse(
        text='{"decision": "offer", "message": "m", "terms": {"purchase_price_cents": '
        + absurd
        + "}}",
        finish_reason="stop",
        empty=False,
        truncated=False,
        provider_call_ids=(),
        tool_invocation_ids=(),
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )

    result = plugin.parse_action(
        case, plugin.initial_state(case, None), "developer", phase, response
    )
    assert not result.ok
    assert result.error_code == "malformed_datacenter_stack_action"


# ------------------------------------------------------------------ planning


def test_the_task_cannot_be_solved_without_cross_agreement_lookahead() -> None:
    """Adopting every counter must strand the project, in every world.

    The utility is agreed two steps before the tenant and executed agreements
    cannot be reopened, so a developer that accepts its smaller, cheaper
    connection has already lost by the time the lease demands full capacity.
    Without this the counter package is a complete, consistent answer and no
    planning is required at all.
    """
    from aeread_families.datacenter_development.stack_environment import (
        TERM_PARSER_BY_TYPE,
        terms_acceptable,
    )

    for world in load_pack_manifest()["worlds"]:
        payload = _payload(world["file"])
        name = world["file"]
        counters = _stack(payload, "counter")
        scripted = _stack(payload, "scripted")

        # Each counter is individually acceptable to the seat that made it.
        for key, terms in counters.items():
            assert terms_acceptable(
                TERM_PARSER_BY_TYPE[
                    "land" if key == "land_amendment" else key
                ](terms),
                payload["policies"][key],
            ), f"{name}: {key} counter must be admissible on its own"

        # Jointly they are infeasible, and specifically on capacity.
        adopted = _evaluate(payload, counters)
        assert adopted["constraints_satisfied"] is False, name
        assert (
            counters["power"]["contracted_capacity_kw"]
            < counters["service"]["committed_capacity_kw"]
        ), name

        # The scripted plan resolves it, so the world remains solvable.
        assert _evaluate(payload, scripted)["constraints_satisfied"] is True, name


def test_the_capacity_gap_is_a_planning_failure_not_a_cash_failure() -> None:
    """Where the counter carries no cash trap, the money still works.

    Some strata additionally bait the counter with a financing trap, and those
    worlds demand that both problems be solved. But the capacity gap must stand
    on its own as a planning failure somewhere, or it is indistinguishable from
    running out of cash.
    """
    pure = 0
    for world in load_pack_manifest()["worlds"]:
        payload = _payload(world["file"])
        adopted = _evaluate(payload, _stack(payload, "counter"))
        if adopted["financing_succeeded"] and not adopted["default_reasons"]:
            assert adopted["constraints_satisfied"] is False, world["file"]
            pure += 1
    assert pure >= 18, f"only {pure} of 24 worlds isolate the planning failure"


def test_the_lookahead_has_a_reachable_solution_and_a_closed_alternative() -> None:
    """The developer can insist on full capacity; it cannot shrink the lease."""
    import copy

    from aeread_families.datacenter_development.stack_environment import (
        TERM_PARSER_BY_TYPE,
        terms_acceptable,
    )

    for world in load_pack_manifest()["worlds"]:
        payload = _payload(world["file"])
        name = world["file"]
        counters = _stack(payload, "counter")
        required = counters["service"]["committed_capacity_kw"]

        insisted = copy.deepcopy(counters)
        insisted["power"]["contracted_capacity_kw"] = required
        assert terms_acceptable(
            TERM_PARSER_BY_TYPE["power"](insisted["power"]),
            payload["policies"]["power"],
        ), f"{name}: the utility must accept a full-size connection"
        adopted = _evaluate(payload, counters)
        if adopted["financing_succeeded"] and not adopted["default_reasons"]:
            # Where capacity is the only defect, correcting it is sufficient.
            assert _evaluate(payload, insisted)["constraints_satisfied"] is True, name
        # Everywhere, the scripted plan is a complete solution.
        assert _evaluate(payload, _stack(payload, "scripted"))[
            "constraints_satisfied"
        ] is True, name

        # Downsizing the lease to match is not a way out: the tenant's floor is
        # full capacity, so exactly one plan survives.
        reduced = counters["power"]["contracted_capacity_kw"]
        shrunk = copy.deepcopy(counters)
        shrunk["service"]["committed_capacity_kw"] = reduced
        shrunk["service"]["ramp_schedule"] = [
            {**step, "capacity_kw": min(step["capacity_kw"], reduced)}
            for step in shrunk["service"]["ramp_schedule"]
        ]
        shrunk["service"]["ramp_schedule"][-1]["capacity_kw"] = reduced
        assert not terms_acceptable(
            TERM_PARSER_BY_TYPE["service"](shrunk["service"]),
            payload["policies"]["service"],
        ), f"{name}: shrinking the lease must not be an escape"


def test_the_requirement_is_visible_before_the_binding_commitment() -> None:
    """A planning test is unfair if the constraint only appears after the fact."""
    for world in load_pack_manifest()["worlds"]:
        facts = _payload(world["file"])["project_facts"]
        required = max(facts["customer_usage_kw_by_month"])

        assert required == CAPACITY_KW, world["file"]
        assert max(facts["built_capacity_kw_by_month"]) == required, world["file"]
        assert max(facts["energized_capacity_kw_by_month"]) == required, world["file"]


def test_the_episode_budget_covers_a_fully_negotiated_stack() -> None:
    """A developer must never be cut off for using the rounds it was granted.

    Each agreement allows MAX_ROUNDS offers, the same number of responses, and
    one commit. An episode budget below that silently penalises negotiation,
    which is one of the two things this family exists to measure.
    """
    from aeread_families.datacenter_development.stack_worlds import (
        MAX_ROUNDS,
        SEQUENCE,
        WORST_CASE_ACTIONS,
    )

    assert WORST_CASE_ACTIONS == len(SEQUENCE) * (2 * MAX_ROUNDS + 1)
    for world in load_pack_manifest()["worlds"]:
        document = json.loads((DEFAULT_OUTPUT_ROOT / world["file"]).read_text())
        rounds = document["payload"]["negotiation"]["max_rounds"]
        needed = sum(2 * value + 1 for value in rounds.values())

        assert document["episode"]["max_logical_actions"] >= needed, world["file"]
