"""V1/V2 agreement-stack compiler over the reconciled V0 monthly ledger."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Mapping

from .cashflow import ConditionSatisfaction, ProjectFacts, ProjectOutcome, simulate_project
from .contracts import (
    EpcAgreement,
    ExecutedAgreement,
    LandAgreement,
    LoanAgreement,
    PowerAgreement,
    ServiceAgreement,
)


class DevelopmentStackValidationError(ValueError):
    """The negotiated stack cannot be compiled into the project ledger."""


@dataclass(frozen=True, slots=True)
class AgreementStackAdjustments:
    physical_epc_completion_month: int | None
    physical_power_ready_month: int | None
    epc_delay_months: int
    power_delay_months: int
    epc_delay_damages_cents: int
    power_delay_damages_cents: int
    power_and_security_cost_cents: int
    land_cost_cents: int
    land_extension_exercised: bool
    site_control_valid_through_cod: bool


@dataclass(frozen=True, slots=True)
class DevelopmentStackOutcome:
    project: ProjectOutcome
    adjustments: AgreementStackAdjustments
    negotiated_constraints_satisfied: bool
    developer_equity_npv_cents: int
    lender_npv_cents: int
    customer_npv_cents: int
    total_project_npv_cents: int


def _terms(
    agreement: ExecutedAgreement,
    agreement_type: str,
    expected_type: type,
):
    if not isinstance(agreement, ExecutedAgreement):
        raise DevelopmentStackValidationError("agreement stack requires executed terms")
    if agreement.agreement_type != agreement_type or not isinstance(
        agreement.terms, expected_type
    ):
        raise DevelopmentStackValidationError(
            f"expected an executed {agreement_type} agreement"
        )
    return agreement.terms


def _ready_month(values: tuple[int, ...], required_capacity_kw: int) -> int | None:
    return next(
        (
            month
            for month, value in enumerate(values, start=1)
            if value >= required_capacity_kw
        ),
        None,
    )


def _condition_months(facts: ProjectFacts) -> dict[str, int | None]:
    return {
        condition.condition_id: condition.satisfied_month
        for condition in facts.condition_satisfaction
    }


def _conditions_met_by(
    required: tuple[str, ...],
    condition_month_by_id: Mapping[str, int | None],
    month: int,
) -> bool:
    return all(
        condition_month_by_id.get(condition_id) is not None
        and condition_month_by_id[condition_id] <= month
        for condition_id in required
    )


def _replace_condition(
    conditions: tuple[ConditionSatisfaction, ...],
    condition_id: str,
    satisfied_month: int | None,
) -> tuple[ConditionSatisfaction, ...]:
    by_id = {item.condition_id: item for item in conditions}
    by_id[condition_id] = ConditionSatisfaction(condition_id, satisfied_month)
    return tuple(by_id[key] for key in sorted(by_id))


def simulate_development_stack(
    facts: ProjectFacts,
    *,
    service_agreement: ExecutedAgreement,
    loan_agreement: ExecutedAgreement,
    power_agreement: ExecutedAgreement,
    epc_agreement: ExecutedAgreement,
    land_agreement: ExecutedAgreement | None = None,
) -> DevelopmentStackOutcome:
    """Compile V1/V2 terms into project physics, costs, conditions, and value."""

    if not isinstance(facts, ProjectFacts):
        raise DevelopmentStackValidationError("facts must be ProjectFacts")
    service = _terms(service_agreement, "service", ServiceAgreement)
    loan = _terms(loan_agreement, "loan", LoanAgreement)
    power = _terms(power_agreement, "power", PowerAgreement)
    epc = _terms(epc_agreement, "epc", EpcAgreement)
    land = (
        None
        if land_agreement is None
        else _terms(land_agreement, "land", LandAgreement)
    )
    assert isinstance(service, ServiceAgreement)
    assert isinstance(loan, LoanAgreement)
    assert isinstance(power, PowerAgreement)
    assert isinstance(epc, EpcAgreement)
    assert land is None or isinstance(land, LandAgreement)

    horizon = facts.horizon_months
    for payment in epc.payment_schedule:
        if payment.month > horizon:
            raise DevelopmentStackValidationError("EPC payment exceeds project horizon")
    if power.energization_month > horizon:
        raise DevelopmentStackValidationError("power energization exceeds project horizon")
    if land is not None and land.closing_month > horizon:
        raise DevelopmentStackValidationError("land closing exceeds project horizon")

    physical_epc_month = _ready_month(
        facts.built_capacity_kw_by_month, epc.guaranteed_capacity_kw
    )
    physical_power_month = _ready_month(
        facts.energized_capacity_kw_by_month, power.contracted_capacity_kw
    )
    epc_delay_months = max(
        0,
        (physical_epc_month or horizon + 1) - epc.guaranteed_completion_month,
    )
    power_delay_months = max(
        0,
        (physical_power_month or horizon + 1) - power.energization_month,
    )
    epc_delay_damages = min(
        epc.delay_liquidated_damages_cap_cents,
        epc_delay_months * epc.delay_liquidated_damages_cents_per_month,
    )
    power_delay_damages = min(
        power.delay_liquidated_damages_cap_cents,
        power_delay_months * power.delay_liquidated_damages_cents_per_month,
    )

    construction_costs = [0] * horizon
    for payment in epc.payment_schedule:
        construction_costs[payment.month - 1] += payment.amount_cents
    development_costs = list(facts.development_cost_cents_by_month)
    development_costs[0] += (
        power.interconnection_cost_cents + power.developer_security_cents
    )
    power_cost = power.interconnection_cost_cents + power.developer_security_cents
    final_power_month = min(
        horizon, power.energization_month + power.initial_term_months - 1
    )
    for month in range(power.energization_month, final_power_month + 1):
        demand_charge = (
            power.contracted_capacity_kw
            * power.monthly_demand_charge_cents_per_kw
        )
        development_costs[month - 1] += demand_charge
        power_cost += demand_charge

    land_cost = 0
    land_extension_exercised = False
    if land is not None:
        development_costs[land.closing_month - 1] += land.purchase_price_cents
        land_cost += land.purchase_price_cents

    built_capacity = tuple(
        min(value, epc.guaranteed_capacity_kw)
        for value in facts.built_capacity_kw_by_month
    )
    energized_capacity = tuple(
        0
        if month < power.energization_month
        else min(value, power.contracted_capacity_kw)
        for month, value in enumerate(
            facts.energized_capacity_kw_by_month, start=1
        )
    )
    physical_cod = next(
        (
            month
            for month in range(1, horizon + 1)
            if min(built_capacity[month - 1], energized_capacity[month - 1])
            >= service.committed_capacity_kw
        ),
        None,
    )

    site_control_valid = True
    if land is not None:
        final_site_control_month = land.site_control_expiry_month
        if (
            physical_cod is not None
            and physical_cod > final_site_control_month
            and physical_cod
            <= final_site_control_month + land.extension_option_months
        ):
            development_costs[land.site_control_expiry_month - 1] += (
                land.extension_price_cents
            )
            land_cost += land.extension_price_cents
            final_site_control_month += land.extension_option_months
            land_extension_exercised = True
        site_control_valid = (
            physical_cod is not None
            and physical_cod <= final_site_control_month
            and land.permitted_use_capacity_kw >= service.committed_capacity_kw
        )

    conditions = facts.condition_satisfaction
    effective_power_month = (
        None
        if physical_power_month is None
        else max(physical_power_month, power.energization_month)
    )
    conditions = _replace_condition(conditions, "power_ready", effective_power_month)
    conditions = _replace_condition(
        conditions, "construction_complete", physical_epc_month
    )
    if land is not None:
        conditions = _replace_condition(conditions, "site_control", land.closing_month)

    terminal_value = (
        facts.terminal_value_cents
        + power.developer_security_cents
        + epc_delay_damages
        + power_delay_damages
    )
    overlaid_facts = dataclasses.replace(
        facts,
        construction_cost_cents_by_month=tuple(construction_costs),
        development_cost_cents_by_month=tuple(development_costs),
        built_capacity_kw_by_month=built_capacity,
        energized_capacity_kw_by_month=energized_capacity,
        energy_cost_cents_per_kwh_by_month=(
            power.energy_charge_cents_per_kwh,
        )
        * horizon,
        terminal_value_cents=terminal_value,
        condition_satisfaction=conditions,
    )
    project = simulate_project(
        overlaid_facts,
        service_agreement=service_agreement,
        loan_agreement=loan_agreement,
    )

    base_conditions = _condition_months(facts)
    epc_conditions_ok = _conditions_met_by(
        epc.conditions_precedent,
        base_conditions,
        epc.notice_to_proceed_month,
    )
    power_conditions_ok = _conditions_met_by(
        power.conditions_precedent,
        base_conditions,
        power.energization_month,
    )
    constraints_ok = (
        epc.guaranteed_capacity_kw >= service.committed_capacity_kw
        and power.contracted_capacity_kw >= service.committed_capacity_kw
        and epc_conditions_ok
        and power_conditions_ok
        and site_control_valid
        and project.financing_succeeded
        and not project.defaulted
    )
    adjustments = AgreementStackAdjustments(
        physical_epc_completion_month=physical_epc_month,
        physical_power_ready_month=physical_power_month,
        epc_delay_months=epc_delay_months,
        power_delay_months=power_delay_months,
        epc_delay_damages_cents=epc_delay_damages,
        power_delay_damages_cents=power_delay_damages,
        power_and_security_cost_cents=power_cost,
        land_cost_cents=land_cost,
        land_extension_exercised=land_extension_exercised,
        site_control_valid_through_cod=site_control_valid,
    )
    return DevelopmentStackOutcome(
        project=project,
        adjustments=adjustments,
        negotiated_constraints_satisfied=constraints_ok,
        developer_equity_npv_cents=project.developer_equity_npv_cents,
        lender_npv_cents=project.lender_npv_cents,
        customer_npv_cents=project.customer_npv_cents,
        total_project_npv_cents=project.total_project_npv_cents,
    )


__all__ = [
    "AgreementStackAdjustments",
    "DevelopmentStackOutcome",
    "DevelopmentStackValidationError",
    "simulate_development_stack",
]
