"""Deterministic monthly project-finance ledger for V0 negotiations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any, Mapping

from aeread.shared_runner.schemas import is_exportable_id

from .contracts import (
    ExecutedAgreement,
    LoanAgreement,
    ServiceAgreement,
)


class CashFlowValidationError(ValueError):
    """Project facts or a compiled ledger violate the V0 finance contract."""


def _exact_mapping(value: Any, *, required: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CashFlowValidationError(f"{path} must be an object")
    keys = set(value)
    missing = required - keys
    unexpected = keys - required
    if missing or unexpected:
        raise CashFlowValidationError(
            f"{path} fields differ: missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CashFlowValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _basis_points(value: Any, path: str, *, maximum: int = 100_000) -> int:
    checked = _integer(value, path)
    if checked > maximum:
        raise CashFlowValidationError(f"{path} must be <= {maximum} basis points")
    return checked


def _integer_tuple(
    value: Any, path: str, *, length: int, minimum: int = 0
) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise CashFlowValidationError(f"{path} must contain exactly {length} values")
    return tuple(
        _integer(item, f"{path}[{index}]", minimum=minimum)
        for index, item in enumerate(value)
    )


def _round_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator >= 0:
        return (numerator + denominator // 2) // denominator
    return -((-numerator + denominator // 2) // denominator)


def _bps_amount(amount: int, basis_points: int) -> int:
    return _round_div(amount * basis_points, 10_000)


def _monthly_bps_amount(amount: int, annual_basis_points: int) -> int:
    return _round_div(amount * annual_basis_points, 120_000)


def _ratio_bps(numerator: int, denominator: int) -> int | None:
    if denominator == 0:
        return None
    return _round_div(numerator * 10_000, denominator)


@dataclass(frozen=True, slots=True)
class ConditionSatisfaction:
    condition_id: str
    satisfied_month: int | None

    def __post_init__(self) -> None:
        if not is_exportable_id(self.condition_id):
            raise CashFlowValidationError(
                "condition_id must be an exportable identifier"
            )
        if self.satisfied_month is not None:
            _integer(self.satisfied_month, "satisfied_month", minimum=1)

    @classmethod
    def from_dict(
        cls, value: Any, path: str = "condition_satisfaction"
    ) -> "ConditionSatisfaction":
        data = _exact_mapping(
            value,
            required={"condition_id", "satisfied_month"},
            path=path,
        )
        return cls(
            condition_id=data["condition_id"],
            satisfied_month=(
                None
                if data["satisfied_month"] is None
                else _integer(
                    data["satisfied_month"],
                    f"{path}.satisfied_month",
                    minimum=1,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ProjectFacts:
    horizon_months: int
    construction_cost_cents_by_month: tuple[int, ...]
    development_cost_cents_by_month: tuple[int, ...]
    built_capacity_kw_by_month: tuple[int, ...]
    energized_capacity_kw_by_month: tuple[int, ...]
    customer_usage_kw_by_month: tuple[int, ...]
    base_rate_bps_by_month: tuple[int, ...]
    energy_cost_cents_per_kwh_by_month: tuple[int, ...]
    tax_and_insurance_cents_by_month: tuple[int, ...]
    operating_cost_cents_per_kw_month: int
    energy_kwh_per_kw_month: int
    customer_value_cents_per_kw_month: int
    developer_equity_budget_cents: int
    appraised_value_cents: int
    terminal_value_cents: int
    developer_discount_rate_bps_annual: int
    lender_discount_rate_bps_annual: int
    customer_discount_rate_bps_annual: int
    base_rate_curve_id: str
    condition_satisfaction: tuple[ConditionSatisfaction, ...]
    customer_termination_month: int | None = None

    def __post_init__(self) -> None:
        horizon = _integer(self.horizon_months, "horizon_months", minimum=1)
        for name in (
            "construction_cost_cents_by_month",
            "development_cost_cents_by_month",
            "built_capacity_kw_by_month",
            "energized_capacity_kw_by_month",
            "customer_usage_kw_by_month",
            "base_rate_bps_by_month",
            "energy_cost_cents_per_kwh_by_month",
            "tax_and_insurance_cents_by_month",
        ):
            object.__setattr__(
                self,
                name,
                _integer_tuple(getattr(self, name), name, length=horizon),
            )
        for name in (
            "built_capacity_kw_by_month",
            "energized_capacity_kw_by_month",
        ):
            values = getattr(self, name)
            if any(left > right for left, right in zip(values, values[1:])):
                raise CashFlowValidationError(f"{name} must be non-decreasing")
        _integer(
            self.operating_cost_cents_per_kw_month,
            "operating_cost_cents_per_kw_month",
        )
        _integer(self.energy_kwh_per_kw_month, "energy_kwh_per_kw_month")
        _integer(
            self.customer_value_cents_per_kw_month,
            "customer_value_cents_per_kw_month",
        )
        _integer(
            self.developer_equity_budget_cents,
            "developer_equity_budget_cents",
        )
        _integer(self.appraised_value_cents, "appraised_value_cents")
        _integer(self.terminal_value_cents, "terminal_value_cents")
        _basis_points(
            self.developer_discount_rate_bps_annual,
            "developer_discount_rate_bps_annual",
        )
        _basis_points(
            self.lender_discount_rate_bps_annual,
            "lender_discount_rate_bps_annual",
        )
        _basis_points(
            self.customer_discount_rate_bps_annual,
            "customer_discount_rate_bps_annual",
        )
        if not is_exportable_id(self.base_rate_curve_id):
            raise CashFlowValidationError(
                "base_rate_curve_id must be an exportable identifier"
            )
        if not isinstance(self.condition_satisfaction, tuple):
            raise CashFlowValidationError("condition_satisfaction must be a tuple")
        if any(
            not isinstance(condition, ConditionSatisfaction)
            for condition in self.condition_satisfaction
        ):
            raise CashFlowValidationError(
                "condition_satisfaction must contain ConditionSatisfaction values"
            )
        condition_ids = tuple(
            condition.condition_id for condition in self.condition_satisfaction
        )
        if len(set(condition_ids)) != len(condition_ids):
            raise CashFlowValidationError(
                "condition_satisfaction contains duplicate condition IDs"
            )
        if any(
            condition.satisfied_month is not None
            and condition.satisfied_month > horizon
            for condition in self.condition_satisfaction
        ):
            raise CashFlowValidationError(
                "condition satisfaction cannot occur after the project horizon"
            )
        if self.customer_termination_month is not None:
            _integer(
                self.customer_termination_month,
                "customer_termination_month",
                minimum=1,
            )
            if self.customer_termination_month > horizon:
                raise CashFlowValidationError(
                    "customer termination cannot occur after the project horizon"
                )

    @classmethod
    def from_dict(cls, value: Any, path: str = "project_facts") -> "ProjectFacts":
        fields = {
            "horizon_months",
            "construction_cost_cents_by_month",
            "development_cost_cents_by_month",
            "built_capacity_kw_by_month",
            "energized_capacity_kw_by_month",
            "customer_usage_kw_by_month",
            "base_rate_bps_by_month",
            "energy_cost_cents_per_kwh_by_month",
            "tax_and_insurance_cents_by_month",
            "operating_cost_cents_per_kw_month",
            "energy_kwh_per_kw_month",
            "customer_value_cents_per_kw_month",
            "developer_equity_budget_cents",
            "appraised_value_cents",
            "terminal_value_cents",
            "developer_discount_rate_bps_annual",
            "lender_discount_rate_bps_annual",
            "customer_discount_rate_bps_annual",
            "base_rate_curve_id",
            "condition_satisfaction",
            "customer_termination_month",
        }
        data = _exact_mapping(value, required=fields, path=path)
        horizon = _integer(data["horizon_months"], f"{path}.horizon_months", minimum=1)
        raw_conditions = data["condition_satisfaction"]
        if not isinstance(raw_conditions, (list, tuple)):
            raise CashFlowValidationError(
                f"{path}.condition_satisfaction must be an array"
            )
        termination_month = data["customer_termination_month"]
        return cls(
            horizon_months=horizon,
            construction_cost_cents_by_month=_integer_tuple(
                data["construction_cost_cents_by_month"],
                f"{path}.construction_cost_cents_by_month",
                length=horizon,
            ),
            development_cost_cents_by_month=_integer_tuple(
                data["development_cost_cents_by_month"],
                f"{path}.development_cost_cents_by_month",
                length=horizon,
            ),
            built_capacity_kw_by_month=_integer_tuple(
                data["built_capacity_kw_by_month"],
                f"{path}.built_capacity_kw_by_month",
                length=horizon,
            ),
            energized_capacity_kw_by_month=_integer_tuple(
                data["energized_capacity_kw_by_month"],
                f"{path}.energized_capacity_kw_by_month",
                length=horizon,
            ),
            customer_usage_kw_by_month=_integer_tuple(
                data["customer_usage_kw_by_month"],
                f"{path}.customer_usage_kw_by_month",
                length=horizon,
            ),
            base_rate_bps_by_month=_integer_tuple(
                data["base_rate_bps_by_month"],
                f"{path}.base_rate_bps_by_month",
                length=horizon,
            ),
            energy_cost_cents_per_kwh_by_month=_integer_tuple(
                data["energy_cost_cents_per_kwh_by_month"],
                f"{path}.energy_cost_cents_per_kwh_by_month",
                length=horizon,
            ),
            tax_and_insurance_cents_by_month=_integer_tuple(
                data["tax_and_insurance_cents_by_month"],
                f"{path}.tax_and_insurance_cents_by_month",
                length=horizon,
            ),
            operating_cost_cents_per_kw_month=_integer(
                data["operating_cost_cents_per_kw_month"],
                f"{path}.operating_cost_cents_per_kw_month",
            ),
            energy_kwh_per_kw_month=_integer(
                data["energy_kwh_per_kw_month"],
                f"{path}.energy_kwh_per_kw_month",
            ),
            customer_value_cents_per_kw_month=_integer(
                data["customer_value_cents_per_kw_month"],
                f"{path}.customer_value_cents_per_kw_month",
            ),
            developer_equity_budget_cents=_integer(
                data["developer_equity_budget_cents"],
                f"{path}.developer_equity_budget_cents",
            ),
            appraised_value_cents=_integer(
                data["appraised_value_cents"], f"{path}.appraised_value_cents"
            ),
            terminal_value_cents=_integer(
                data["terminal_value_cents"], f"{path}.terminal_value_cents"
            ),
            developer_discount_rate_bps_annual=_basis_points(
                data["developer_discount_rate_bps_annual"],
                f"{path}.developer_discount_rate_bps_annual",
            ),
            lender_discount_rate_bps_annual=_basis_points(
                data["lender_discount_rate_bps_annual"],
                f"{path}.lender_discount_rate_bps_annual",
            ),
            customer_discount_rate_bps_annual=_basis_points(
                data["customer_discount_rate_bps_annual"],
                f"{path}.customer_discount_rate_bps_annual",
            ),
            base_rate_curve_id=data["base_rate_curve_id"],
            condition_satisfaction=tuple(
                ConditionSatisfaction.from_dict(
                    condition,
                    f"{path}.condition_satisfaction[{index}]",
                )
                for index, condition in enumerate(raw_conditions)
            ),
            customer_termination_month=(
                None
                if termination_month is None
                else _integer(
                    termination_month,
                    f"{path}.customer_termination_month",
                    minimum=1,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class MonthlyLedgerRow:
    month: int
    opening_cash_cents: int
    opening_principal_cents: int
    scheduled_capacity_kw: int
    delivered_capacity_kw: int
    billed_capacity_kw: int
    gross_capacity_revenue_cents: int
    energy_pass_through_revenue_cents: int
    service_credit_cents: int
    delay_damages_cents: int
    termination_fee_cents: int
    net_service_revenue_cents: int
    customer_value_cents: int
    construction_cost_cents: int
    development_cost_cents: int
    operating_cost_cents: int
    energy_cost_cents: int
    tax_and_insurance_cents: int
    debt_draw_cents: int
    equity_contribution_cents: int
    origination_fee_cents: int
    unused_commitment_fee_cents: int
    interest_cents: int
    principal_repayment_cents: int
    developer_distribution_cents: int
    terminal_value_cents: int
    closing_cash_cents: int
    closing_principal_cents: int
    dscr_bps: int | None
    loan_conditions_satisfied: bool
    default_reasons: tuple[str, ...]

    @property
    def sources_cents(self) -> int:
        return (
            self.opening_cash_cents
            + self.net_service_revenue_cents
            + self.debt_draw_cents
            + self.equity_contribution_cents
            + self.terminal_value_cents
        )

    @property
    def uses_cents(self) -> int:
        return (
            self.construction_cost_cents
            + self.development_cost_cents
            + self.operating_cost_cents
            + self.energy_cost_cents
            + self.tax_and_insurance_cents
            + self.origination_fee_cents
            + self.unused_commitment_fee_cents
            + self.interest_cents
            + self.principal_repayment_cents
            + self.developer_distribution_cents
            + self.closing_cash_cents
        )


@dataclass(frozen=True, slots=True)
class ProjectOutcome:
    rows: tuple[MonthlyLedgerRow, ...]
    cod_month: int | None
    loan_conditions_satisfied_month: int | None
    minimum_dscr_bps: int | None
    defaulted: bool
    default_reasons: tuple[str, ...]
    developer_equity_npv_cents: int
    lender_npv_cents: int
    customer_npv_cents: int
    total_project_npv_cents: int
    financing_succeeded: bool


def _agreement_terms(
    agreement: ExecutedAgreement,
    *,
    agreement_type: str,
    term_type: type[ServiceAgreement] | type[LoanAgreement],
) -> ServiceAgreement | LoanAgreement:
    if not isinstance(agreement, ExecutedAgreement):
        raise CashFlowValidationError("project simulation requires executed agreements")
    if agreement.agreement_type != agreement_type or not isinstance(
        agreement.terms, term_type
    ):
        raise CashFlowValidationError(
            f"expected an executed {agreement_type} agreement"
        )
    return agreement.terms


def _scheduled_capacity(service: ServiceAgreement, month: int) -> int:
    if month < service.service_commencement_month:
        return 0
    capacity = 0
    for step in service.ramp_schedule:
        if step.month > month:
            break
        capacity = step.capacity_kw
    return capacity


def _conditions_met(
    required: tuple[str, ...],
    satisfied_month_by_id: Mapping[str, int | None],
    month: int,
) -> bool:
    for condition_id in required:
        satisfied_month = satisfied_month_by_id.get(condition_id)
        if satisfied_month is None or satisfied_month > month:
            return False
    return True


def _npv_cents(cashflows: tuple[int, ...], annual_rate_bps: int) -> int:
    with localcontext() as context:
        context.prec = 40
        monthly_rate = Decimal(annual_rate_bps) / Decimal(120_000)
        value = sum(
            Decimal(cashflow) / ((Decimal(1) + monthly_rate) ** month)
            for month, cashflow in enumerate(cashflows, start=1)
        )
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def simulate_project(
    facts: ProjectFacts,
    *,
    service_agreement: ExecutedAgreement,
    loan_agreement: ExecutedAgreement,
) -> ProjectOutcome:
    """Compile executed terms into a deterministic, reconciled monthly ledger."""

    if not isinstance(facts, ProjectFacts):
        raise CashFlowValidationError("facts must be ProjectFacts")
    service = _agreement_terms(
        service_agreement,
        agreement_type="service",
        term_type=ServiceAgreement,
    )
    loan = _agreement_terms(
        loan_agreement,
        agreement_type="loan",
        term_type=LoanAgreement,
    )
    assert isinstance(service, ServiceAgreement)
    assert isinstance(loan, LoanAgreement)
    if loan.base_rate_curve_id != facts.base_rate_curve_id:
        raise CashFlowValidationError(
            "loan base-rate curve does not match the project facts"
        )
    if loan.maturity_month > facts.horizon_months:
        raise CashFlowValidationError("loan maturity exceeds the project horizon")
    if service.ramp_schedule[-1].month > facts.horizon_months:
        raise CashFlowValidationError("service ramp exceeds the project horizon")
    if (
        facts.customer_termination_month is not None
        and service.customer_termination_option_month is None
    ):
        raise CashFlowValidationError(
            "project facts exercise a customer termination right that does not exist"
        )
    if (
        facts.customer_termination_month is not None
        and service.customer_termination_option_month is not None
        and facts.customer_termination_month
        < service.customer_termination_option_month
    ):
        raise CashFlowValidationError(
            "customer termination occurs before the contractual option month"
        )

    satisfied_month_by_id = {
        condition.condition_id: condition.satisfied_month
        for condition in facts.condition_satisfaction
    }
    missing_conditions = sorted(
        (set(service.conditions_precedent) | set(loan.conditions_precedent))
        - set(satisfied_month_by_id)
    )
    if missing_conditions:
        raise CashFlowValidationError(
            "project facts omit condition IDs: " + ", ".join(missing_conditions)
        )

    service_is_bankable = (
        service.committed_capacity_kw >= loan.minimum_contracted_capacity_kw
        and service.take_or_pay_bps >= loan.minimum_take_or_pay_bps
        and service.credit_support_cents
        >= loan.minimum_customer_credit_support_cents
    )
    loan_conditions_month: int | None = None
    for month in range(loan.draw_start_month, facts.horizon_months + 1):
        if service_is_bankable and _conditions_met(
            loan.conditions_precedent, satisfied_month_by_id, month
        ):
            loan_conditions_month = month
            break

    cod_month = next(
        (
            month
            for month in range(1, facts.horizon_months + 1)
            if min(
                facts.built_capacity_kw_by_month[month - 1],
                facts.energized_capacity_kw_by_month[month - 1],
            )
            >= service.committed_capacity_kw
        ),
        None,
    )

    rows: list[MonthlyLedgerRow] = []
    opening_cash = 0
    opening_principal = 0
    cumulative_eligible_cost = 0
    cumulative_delay_damages = 0
    equity_contributed = 0
    interest_reserve_used = 0
    loan_has_drawn = False
    default_reasons: list[str] = []
    developer_cashflows: list[int] = []
    lender_cashflows: list[int] = []
    customer_cashflows: list[int] = []

    for month in range(1, facts.horizon_months + 1):
        index = month - 1
        scheduled_capacity = _scheduled_capacity(service, month)
        service_conditions_met = _conditions_met(
            service.conditions_precedent, satisfied_month_by_id, month
        )
        terminated = (
            facts.customer_termination_month is not None
            and month >= facts.customer_termination_month
        )
        if not service_conditions_met or terminated:
            scheduled_capacity = 0
        delivered_capacity = min(
            scheduled_capacity,
            facts.built_capacity_kw_by_month[index],
            facts.energized_capacity_kw_by_month[index],
        )
        minimum_take_capacity = _bps_amount(
            scheduled_capacity, service.take_or_pay_bps
        )
        requested_capacity = min(
            scheduled_capacity,
            max(facts.customer_usage_kw_by_month[index], minimum_take_capacity),
        )
        billed_capacity = min(delivered_capacity, requested_capacity)
        gross_capacity_revenue = (
            billed_capacity * service.monthly_capacity_charge_cents_per_kw
        )
        energy_kwh = delivered_capacity * facts.energy_kwh_per_kw_month
        energy_pass_through = (
            energy_kwh * service.energy_pass_through_cents_per_kwh
        )
        energy_cost = energy_kwh * facts.energy_cost_cents_per_kwh_by_month[index]
        scheduled_charge = (
            scheduled_capacity * service.monthly_capacity_charge_cents_per_kw
        )
        unavailable_capacity = max(0, scheduled_capacity - delivered_capacity)
        raw_service_credit = (
            0
            if scheduled_capacity == 0
            else _round_div(
                scheduled_charge * unavailable_capacity,
                scheduled_capacity,
            )
        )
        service_credit = min(
            raw_service_credit,
            _bps_amount(scheduled_charge, service.sla_credit_cap_bps),
        )
        delay_damages = 0
        if unavailable_capacity > 0:
            delay_damages = min(
                service.delay_damages_cents_per_month,
                service.delay_damages_cap_cents - cumulative_delay_damages,
            )
            cumulative_delay_damages += delay_damages
        termination_fee = (
            service.customer_termination_fee_cents
            if facts.customer_termination_month == month
            else 0
        )
        net_service_revenue = (
            gross_capacity_revenue
            + energy_pass_through
            + termination_fee
            - service_credit
            - delay_damages
        )
        customer_value = (
            delivered_capacity * facts.customer_value_cents_per_kw_month
        )

        construction_cost = facts.construction_cost_cents_by_month[index]
        development_cost = facts.development_cost_cents_by_month[index]
        eligible_cost = construction_cost + development_cost
        cumulative_eligible_cost += eligible_cost
        operating_cost = (
            delivered_capacity * facts.operating_cost_cents_per_kw_month
        )
        tax_and_insurance = facts.tax_and_insurance_cents_by_month[index]

        prior_default = bool(default_reasons)
        loan_conditions_satisfied = (
            loan_conditions_month is not None
            and month >= loan_conditions_month
            and not prior_default
            and month < loan.maturity_month
        )
        debt_draw = 0
        annual_interest_bps = facts.base_rate_bps_by_month[index] + loan.spread_bps
        interest = _monthly_bps_amount(opening_principal, annual_interest_bps)
        unused_commitment_fee = (
            _monthly_bps_amount(
                max(0, loan.maximum_commitment_cents - opening_principal),
                loan.unused_commitment_fee_bps_annual,
            )
            if month <= loan.maturity_month and not prior_default
            else 0
        )
        origination_fee = 0
        if loan_conditions_satisfied:
            lending_rate_bps = min(
                loan.advance_rate_bps, loan.maximum_loan_to_cost_bps
            )
            cost_limit = _bps_amount(cumulative_eligible_cost, lending_rate_bps)
            value_limit = _bps_amount(
                facts.appraised_value_cents, loan.maximum_loan_to_value_bps
            )
            maximum_principal = min(
                loan.maximum_commitment_cents,
                cost_limit,
                value_limit,
            )
            project_cost_draw = max(0, maximum_principal - opening_principal)
            project_cost_draw = min(
                project_cost_draw,
                loan.maximum_commitment_cents - opening_principal,
            )
            reserve_available = max(
                0, loan.interest_reserve_cents - interest_reserve_used
            )
            reserve_draw = min(
                interest,
                reserve_available,
                max(
                    0,
                    loan.maximum_commitment_cents
                    - opening_principal
                    - project_cost_draw,
                ),
            )
            debt_draw = project_cost_draw + reserve_draw
            interest_reserve_used += reserve_draw
            if debt_draw > 0 and not loan_has_drawn:
                origination_fee = _bps_amount(
                    loan.maximum_commitment_cents,
                    loan.origination_fee_bps,
                )
                loan_has_drawn = True

        principal_before_repayment = opening_principal + debt_draw
        pre_repayment_uses = (
            construction_cost
            + development_cost
            + operating_cost
            + energy_cost
            + tax_and_insurance
            + origination_fee
            + unused_commitment_fee
            + interest
        )
        terminal_value = (
            facts.terminal_value_cents if month == facts.horizon_months else 0
        )
        pre_equity_cash = (
            opening_cash
            + net_service_revenue
            + debt_draw
            + terminal_value
            - pre_repayment_uses
        )
        remaining_equity = max(
            0, facts.developer_equity_budget_cents - equity_contributed
        )
        principal_repayment = 0
        if month == loan.maturity_month:
            principal_repayment = min(
                principal_before_repayment,
                max(0, pre_equity_cash + remaining_equity),
            )
        cash_before_equity = pre_equity_cash - principal_repayment
        equity_contribution = min(remaining_equity, max(0, -cash_before_equity))
        equity_contributed += equity_contribution
        closing_cash = cash_before_equity + equity_contribution
        closing_principal = principal_before_repayment - principal_repayment

        month_defaults: list[str] = []
        if closing_cash < 0:
            month_defaults.append("funding_shortfall")
        if month == loan.maturity_month and closing_principal > 0:
            month_defaults.append("maturity_nonpayment")

        net_operating_cashflow = (
            net_service_revenue
            - operating_cost
            - energy_cost
            - tax_and_insurance
        )
        debt_service = interest + principal_repayment
        dscr_bps = _ratio_bps(net_operating_cashflow, debt_service)
        if (
            month >= service.service_commencement_month
            and debt_service > 0
            and dscr_bps is not None
            and dscr_bps < loan.minimum_dscr_bps
        ):
            month_defaults.append("minimum_dscr_breach")

        for reason in month_defaults:
            if reason not in default_reasons:
                default_reasons.append(reason)

        developer_distribution = 0
        if month == facts.horizon_months and closing_cash > 0:
            developer_distribution = closing_cash
            closing_cash = 0

        row = MonthlyLedgerRow(
            month=month,
            opening_cash_cents=opening_cash,
            opening_principal_cents=opening_principal,
            scheduled_capacity_kw=scheduled_capacity,
            delivered_capacity_kw=delivered_capacity,
            billed_capacity_kw=billed_capacity,
            gross_capacity_revenue_cents=gross_capacity_revenue,
            energy_pass_through_revenue_cents=energy_pass_through,
            service_credit_cents=service_credit,
            delay_damages_cents=delay_damages,
            termination_fee_cents=termination_fee,
            net_service_revenue_cents=net_service_revenue,
            customer_value_cents=customer_value,
            construction_cost_cents=construction_cost,
            development_cost_cents=development_cost,
            operating_cost_cents=operating_cost,
            energy_cost_cents=energy_cost,
            tax_and_insurance_cents=tax_and_insurance,
            debt_draw_cents=debt_draw,
            equity_contribution_cents=equity_contribution,
            origination_fee_cents=origination_fee,
            unused_commitment_fee_cents=unused_commitment_fee,
            interest_cents=interest,
            principal_repayment_cents=principal_repayment,
            developer_distribution_cents=developer_distribution,
            terminal_value_cents=terminal_value,
            closing_cash_cents=closing_cash,
            closing_principal_cents=closing_principal,
            dscr_bps=dscr_bps,
            loan_conditions_satisfied=loan_conditions_satisfied,
            default_reasons=tuple(month_defaults),
        )
        if row.sources_cents != row.uses_cents:
            raise CashFlowValidationError(
                f"month {month} cash sources do not equal uses"
            )
        if (
            row.opening_principal_cents + row.debt_draw_cents
            != row.principal_repayment_cents + row.closing_principal_cents
        ):
            raise CashFlowValidationError(
                f"month {month} principal does not roll forward"
            )
        rows.append(row)

        developer_cashflows.append(
            developer_distribution - equity_contribution
        )
        lender_cashflows.append(
            -debt_draw
            + origination_fee
            + unused_commitment_fee
            + interest
            + principal_repayment
        )
        customer_cashflows.append(customer_value - net_service_revenue)
        opening_cash = closing_cash
        opening_principal = closing_principal

    dscr_values = tuple(row.dscr_bps for row in rows if row.dscr_bps is not None)
    developer_npv = _npv_cents(
        tuple(developer_cashflows), facts.developer_discount_rate_bps_annual
    )
    lender_npv = _npv_cents(
        tuple(lender_cashflows), facts.lender_discount_rate_bps_annual
    )
    customer_npv = _npv_cents(
        tuple(customer_cashflows), facts.customer_discount_rate_bps_annual
    )
    total_npv = developer_npv + lender_npv + customer_npv
    financing_succeeded = (
        loan_conditions_month is not None
        and loan_has_drawn
        and not default_reasons
        and rows[-1].closing_principal_cents == 0
    )
    return ProjectOutcome(
        rows=tuple(rows),
        cod_month=cod_month,
        loan_conditions_satisfied_month=loan_conditions_month,
        minimum_dscr_bps=min(dscr_values) if dscr_values else None,
        defaulted=bool(default_reasons),
        default_reasons=tuple(default_reasons),
        developer_equity_npv_cents=developer_npv,
        lender_npv_cents=lender_npv,
        customer_npv_cents=customer_npv,
        total_project_npv_cents=total_npv,
        financing_succeeded=financing_succeeded,
    )


__all__ = [
    "CashFlowValidationError",
    "ConditionSatisfaction",
    "MonthlyLedgerRow",
    "ProjectFacts",
    "ProjectOutcome",
    "simulate_project",
]
