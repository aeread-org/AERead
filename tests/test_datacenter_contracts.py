from __future__ import annotations

import dataclasses

import pytest

from aeread_families.datacenter_development.contracts import (
    ContractSignature,
    ContractValidationError,
    LoanAgreement,
    RampStep,
    ServiceAgreement,
    execute_offer,
    make_offer,
)


def _service() -> ServiceAgreement:
    return ServiceAgreement(
        committed_capacity_kw=1_000,
        service_commencement_month=3,
        ramp_schedule=(RampStep(month=3, capacity_kw=1_000),),
        monthly_capacity_charge_cents_per_kw=100,
        energy_pass_through_cents_per_kwh=0,
        take_or_pay_bps=10_000,
        initial_term_months=24,
        renewal_option_months=12,
        sla_credit_cap_bps=10_000,
        customer_termination_option_month=None,
        customer_termination_fee_cents=0,
        delay_damages_cents_per_month=10_000,
        delay_damages_cap_cents=20_000,
        credit_support_cents=100_000,
        conditions_precedent=("power_ready",),
    )


def test_offer_identity_binds_structured_terms_not_negotiation_prose() -> None:
    service = _service()
    first = make_offer(
        case_id="datacenter_case_001",
        agreement_type="service",
        proposer_seat_id="developer",
        round_index=0,
        message="We can commit these terms.",
        terms=service,
    )
    paraphrase = make_offer(
        case_id="datacenter_case_001",
        agreement_type="service",
        proposer_seat_id="developer",
        round_index=0,
        message="These are the same written terms.",
        terms=service,
    )
    changed_terms = make_offer(
        case_id="datacenter_case_001",
        agreement_type="service",
        proposer_seat_id="developer",
        round_index=0,
        message=first.message,
        terms=dataclasses.replace(
            service, monthly_capacity_charge_cents_per_kw=101
        ),
    )

    assert first.offer_id == paraphrase.offer_id
    assert first.offer_id != changed_terms.offer_id

    with pytest.raises(ContractValidationError, match="canonical written terms"):
        dataclasses.replace(first, terms=changed_terms.terms)


def test_only_exact_offer_signatures_compile_the_written_agreement() -> None:
    offer = make_offer(
        case_id="datacenter_case_001",
        agreement_type="service",
        proposer_seat_id="developer",
        round_index=1,
        message="Final written service offer.",
        terms=_service(),
    )
    executed = execute_offer(
        offer,
        (
            ContractSignature(offer.offer_id, "customer"),
            ContractSignature(offer.offer_id, "developer"),
        ),
        required_signers=("developer", "customer"),
    )

    assert executed.offer_id == offer.offer_id
    assert executed.terms == offer.terms
    assert executed.signed_by == ("customer", "developer")

    with pytest.raises(ContractValidationError, match="different offer"):
        execute_offer(
            offer,
            (
                ContractSignature("offer_wrong", "customer"),
                ContractSignature(offer.offer_id, "developer"),
            ),
            required_signers=("developer", "customer"),
        )


def test_contract_parsers_reject_unknown_fields_and_incoherent_ramps() -> None:
    service = _service()
    raw = dataclasses.asdict(service)
    raw["unexpected"] = True
    with pytest.raises(ContractValidationError, match="unexpected"):
        ServiceAgreement.from_dict(raw)

    with pytest.raises(ContractValidationError, match="final ramp capacity"):
        dataclasses.replace(
            service,
            ramp_schedule=(RampStep(month=3, capacity_kw=999),),
        )


def test_loan_terms_reject_maturity_before_draw_start() -> None:
    with pytest.raises(ContractValidationError, match="maturity_month"):
        LoanAgreement(
            maximum_commitment_cents=200_000,
            advance_rate_bps=5_000,
            base_rate_curve_id="base_curve_v1",
            spread_bps=0,
            unused_commitment_fee_bps_annual=0,
            origination_fee_bps=0,
            interest_reserve_cents=0,
            draw_start_month=3,
            minimum_contracted_capacity_kw=1_000,
            minimum_take_or_pay_bps=8_000,
            minimum_customer_credit_support_cents=50_000,
            minimum_dscr_bps=8_000,
            maximum_loan_to_cost_bps=5_000,
            maximum_loan_to_value_bps=10_000,
            maturity_month=2,
            extension_option_months=0,
            completion_guarantee_cents=0,
            conditions_precedent=("site_control",),
        )
