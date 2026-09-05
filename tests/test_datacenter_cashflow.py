from __future__ import annotations

import dataclasses

import pytest

from aeread_families.datacenter_development.cashflow import (
    CashFlowValidationError,
    ConditionSatisfaction,
    ProjectFacts,
    simulate_project,
)
from aeread_families.datacenter_development.contracts import (
    ContractSignature,
    LoanAgreement,
    RampStep,
    ServiceAgreement,
    execute_offer,
    make_offer,
)


def _service(*, take_or_pay_bps: int = 10_000, price: int = 100) -> ServiceAgreement:
    return ServiceAgreement(
        committed_capacity_kw=1_000,
        service_commencement_month=1,
        ramp_schedule=(RampStep(month=1, capacity_kw=1_000),),
        monthly_capacity_charge_cents_per_kw=price,
        energy_pass_through_cents_per_kwh=0,
        take_or_pay_bps=take_or_pay_bps,
        initial_term_months=24,
        renewal_option_months=0,
        sla_credit_cap_bps=10_000,
        customer_termination_option_month=None,
        customer_termination_fee_cents=0,
        delay_damages_cents_per_month=0,
        delay_damages_cap_cents=0,
        credit_support_cents=100_000,
        conditions_precedent=("power_ready",),
    )


def _loan(*, minimum_dscr_bps: int = 8_000) -> LoanAgreement:
    return LoanAgreement(
        maximum_commitment_cents=200_000,
        advance_rate_bps=5_000,
        base_rate_curve_id="base_curve_v1",
        spread_bps=0,
        unused_commitment_fee_bps_annual=0,
        origination_fee_bps=0,
        interest_reserve_cents=0,
        draw_start_month=1,
        minimum_contracted_capacity_kw=1_000,
        minimum_take_or_pay_bps=8_000,
        minimum_customer_credit_support_cents=50_000,
        minimum_dscr_bps=minimum_dscr_bps,
        maximum_loan_to_cost_bps=5_000,
        maximum_loan_to_value_bps=10_000,
        maturity_month=4,
        extension_option_months=0,
        completion_guarantee_cents=0,
        conditions_precedent=("site_control", "power_commitment"),
    )


def _execute(agreement_type: str, terms):
    counterpart = "customer" if agreement_type == "service" else "lender"
    offer = make_offer(
        case_id="datacenter_case_001",
        agreement_type=agreement_type,
        proposer_seat_id="developer",
        round_index=0,
        message=f"Final written {agreement_type} offer.",
        terms=terms,
    )
    return execute_offer(
        offer,
        (
            ContractSignature(offer.offer_id, "developer"),
            ContractSignature(offer.offer_id, counterpart),
        ),
        required_signers=("developer", counterpart),
    )


def _facts(*, equity_budget: int = 500_000) -> ProjectFacts:
    return ProjectFacts(
        horizon_months=4,
        construction_cost_cents_by_month=(100_000, 100_000, 0, 0),
        development_cost_cents_by_month=(0, 0, 0, 0),
        built_capacity_kw_by_month=(0, 500, 1_000, 1_000),
        energized_capacity_kw_by_month=(0, 0, 1_000, 1_000),
        customer_usage_kw_by_month=(1_000, 1_000, 1_000, 1_000),
        base_rate_bps_by_month=(0, 0, 0, 0),
        energy_cost_cents_per_kwh_by_month=(0, 0, 0, 0),
        tax_and_insurance_cents_by_month=(0, 0, 0, 0),
        operating_cost_cents_per_kw_month=10,
        energy_kwh_per_kw_month=0,
        customer_value_cents_per_kw_month=200,
        developer_equity_budget_cents=equity_budget,
        appraised_value_cents=1_000_000,
        terminal_value_cents=0,
        developer_discount_rate_bps_annual=0,
        lender_discount_rate_bps_annual=0,
        customer_discount_rate_bps_annual=0,
        base_rate_curve_id="base_curve_v1",
        condition_satisfaction=(
            ConditionSatisfaction("site_control", 1),
            ConditionSatisfaction("power_commitment", 2),
            ConditionSatisfaction("power_ready", 3),
        ),
    )


def test_monthly_ledger_reconciles_and_couples_service_terms_to_loan_draws() -> None:
    outcome = simulate_project(
        _facts(),
        service_agreement=_execute("service", _service()),
        loan_agreement=_execute("loan", _loan()),
    )

    assert outcome.cod_month == 3
    assert outcome.loan_conditions_satisfied_month == 2
    assert outcome.financing_succeeded is True
    assert outcome.defaulted is False
    assert [row.debt_draw_cents for row in outcome.rows] == [0, 100_000, 0, 0]
    assert [row.net_service_revenue_cents for row in outcome.rows] == [
        0,
        0,
        100_000,
        100_000,
    ]
    assert outcome.developer_equity_npv_cents == -20_000
    assert outcome.lender_npv_cents == 0
    assert outcome.customer_npv_cents == 200_000
    assert outcome.total_project_npv_cents == 180_000
    assert outcome.minimum_dscr_bps == 9_000
    for row in outcome.rows:
        assert row.sources_cents == row.uses_cents
        assert (
            row.opening_principal_cents + row.debt_draw_cents
            == row.principal_repayment_cents + row.closing_principal_cents
        )


def test_weak_take_or_pay_prevents_financing_and_exposes_equity_shortfall() -> None:
    outcome = simulate_project(
        _facts(equity_budget=150_000),
        service_agreement=_execute("service", _service(take_or_pay_bps=5_000)),
        loan_agreement=_execute("loan", _loan()),
    )

    assert outcome.loan_conditions_satisfied_month is None
    assert all(row.debt_draw_cents == 0 for row in outcome.rows)
    assert outcome.financing_succeeded is False
    assert outcome.defaulted is True
    assert "funding_shortfall" in outcome.default_reasons


def test_service_price_changes_developer_value_without_changing_project_physics() -> None:
    high = simulate_project(
        _facts(),
        service_agreement=_execute("service", _service(price=100)),
        loan_agreement=_execute("loan", _loan()),
    )
    low = simulate_project(
        _facts(),
        service_agreement=_execute("service", _service(price=50)),
        loan_agreement=_execute("loan", _loan()),
    )

    assert high.cod_month == low.cod_month == 3
    assert high.developer_equity_npv_cents > low.developer_equity_npv_cents
    assert high.customer_npv_cents < low.customer_npv_cents


def test_dscr_threshold_is_a_separate_financing_failure() -> None:
    outcome = simulate_project(
        _facts(),
        service_agreement=_execute("service", _service()),
        loan_agreement=_execute("loan", _loan(minimum_dscr_bps=10_000)),
    )

    assert outcome.minimum_dscr_bps == 9_000
    assert outcome.defaulted is True
    assert outcome.financing_succeeded is False
    assert "minimum_dscr_breach" in outcome.default_reasons


def test_simulator_rejects_a_different_base_rate_curve() -> None:
    loan = dataclasses.replace(_loan(), base_rate_curve_id="other_curve")
    with pytest.raises(CashFlowValidationError, match="base-rate curve"):
        simulate_project(
            _facts(),
            service_agreement=_execute("service", _service()),
            loan_agreement=_execute("loan", loan),
        )


def test_project_facts_parser_rejects_unversioned_extra_state() -> None:
    raw = dataclasses.asdict(_facts())
    raw["hidden_override"] = 1
    with pytest.raises(CashFlowValidationError, match="unexpected"):
        ProjectFacts.from_dict(raw)


def test_explicitly_unsatisfied_condition_is_valid_but_blocks_the_loan() -> None:
    facts = dataclasses.replace(
        _facts(),
        condition_satisfaction=(
            ConditionSatisfaction("site_control", 1),
            ConditionSatisfaction("power_commitment", None),
            ConditionSatisfaction("power_ready", 3),
        ),
    )
    outcome = simulate_project(
        facts,
        service_agreement=_execute("service", _service()),
        loan_agreement=_execute("loan", _loan()),
    )

    assert outcome.loan_conditions_satisfied_month is None
    assert all(row.debt_draw_cents == 0 for row in outcome.rows)
    assert outcome.financing_succeeded is False
