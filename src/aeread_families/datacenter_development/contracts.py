"""Typed written instruments for data-center development V0.

The benchmark never extracts binding truth from prose. A model-facing offer
contains prose for negotiation quality and one complete typed term object for
state transitions. Only signatures over the immutable offer ID execute those
terms.
"""

from __future__ import annotations

import hashlib
import dataclasses
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aeread.shared_runner.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import is_exportable_id


class ContractValidationError(ValueError):
    """A proposed or executed written instrument is malformed."""


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _basis_points(value: Any, path: str, *, maximum: int = 10_000) -> int:
    checked = _integer(value, path)
    if checked > maximum:
        raise ContractValidationError(f"{path} must be <= {maximum} basis points")
    return checked


def _identifier(value: Any, path: str) -> str:
    if not is_exportable_id(value):
        raise ContractValidationError(f"{path} must be an exportable identifier")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{path} must be non-empty text")
    return value


def _identifiers(values: Any, path: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ContractValidationError(f"{path} must be an array")
    checked = tuple(_identifier(value, f"{path}[{index}]") for index, value in enumerate(values))
    if len(set(checked)) != len(checked):
        raise ContractValidationError(f"{path} must not contain duplicates")
    return checked


def _exact_mapping(
    value: Any, *, required: set[str], optional: set[str] | None = None, path: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{path} must be an object")
    optional = optional or set()
    keys = set(value)
    missing = required - keys
    unexpected = keys - required - optional
    if missing or unexpected:
        raise ContractValidationError(
            f"{path} fields differ: missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    return value


@dataclass(frozen=True, slots=True)
class RampStep:
    month: int
    capacity_kw: int

    def __post_init__(self) -> None:
        _integer(self.month, "ramp month", minimum=1)
        _integer(self.capacity_kw, "ramp capacity_kw")

    @classmethod
    def from_dict(cls, value: Any, path: str = "ramp_step") -> "RampStep":
        data = _exact_mapping(
            value,
            required={"month", "capacity_kw"},
            path=path,
        )
        return cls(
            month=_integer(data["month"], f"{path}.month", minimum=1),
            capacity_kw=_integer(data["capacity_kw"], f"{path}.capacity_kw"),
        )


@dataclass(frozen=True, slots=True)
class ServiceAgreement:
    committed_capacity_kw: int
    service_commencement_month: int
    ramp_schedule: tuple[RampStep, ...]
    monthly_capacity_charge_cents_per_kw: int
    energy_pass_through_cents_per_kwh: int
    take_or_pay_bps: int
    initial_term_months: int
    renewal_option_months: int
    sla_credit_cap_bps: int
    customer_termination_option_month: int | None
    customer_termination_fee_cents: int
    delay_damages_cents_per_month: int
    delay_damages_cap_cents: int
    credit_support_cents: int
    conditions_precedent: tuple[str, ...]

    def __post_init__(self) -> None:
        _integer(self.committed_capacity_kw, "committed_capacity_kw", minimum=1)
        _integer(
            self.service_commencement_month,
            "service_commencement_month",
            minimum=1,
        )
        if not isinstance(self.ramp_schedule, tuple) or not self.ramp_schedule:
            raise ContractValidationError("ramp_schedule must be a non-empty tuple")
        if any(not isinstance(step, RampStep) for step in self.ramp_schedule):
            raise ContractValidationError("ramp_schedule must contain RampStep values")
        months = tuple(step.month for step in self.ramp_schedule)
        capacities = tuple(step.capacity_kw for step in self.ramp_schedule)
        if tuple(sorted(months)) != months or len(set(months)) != len(months):
            raise ContractValidationError(
                "ramp_schedule months must be strictly increasing"
            )
        if months[0] < self.service_commencement_month:
            raise ContractValidationError(
                "ramp_schedule cannot begin before service commencement"
            )
        if any(left > right for left, right in zip(capacities, capacities[1:])):
            raise ContractValidationError("ramp capacity must be non-decreasing")
        if capacities[-1] != self.committed_capacity_kw:
            raise ContractValidationError(
                "final ramp capacity must equal committed_capacity_kw"
            )
        for step in self.ramp_schedule:
            if step.capacity_kw > self.committed_capacity_kw:
                raise ContractValidationError(
                    "ramp capacity cannot exceed committed_capacity_kw"
                )
        _integer(
            self.monthly_capacity_charge_cents_per_kw,
            "monthly_capacity_charge_cents_per_kw",
        )
        _integer(
            self.energy_pass_through_cents_per_kwh,
            "energy_pass_through_cents_per_kwh",
        )
        _basis_points(self.take_or_pay_bps, "take_or_pay_bps")
        _integer(self.initial_term_months, "initial_term_months", minimum=1)
        _integer(self.renewal_option_months, "renewal_option_months")
        _basis_points(self.sla_credit_cap_bps, "sla_credit_cap_bps")
        if self.customer_termination_option_month is not None:
            _integer(
                self.customer_termination_option_month,
                "customer_termination_option_month",
                minimum=1,
            )
            if self.customer_termination_option_month < self.service_commencement_month:
                raise ContractValidationError(
                    "customer termination option cannot precede service commencement"
                )
            final_service_month = (
                self.service_commencement_month + self.initial_term_months - 1
            )
            if self.customer_termination_option_month > final_service_month:
                raise ContractValidationError(
                    "customer termination option cannot follow the initial term"
                )
        _integer(
            self.customer_termination_fee_cents,
            "customer_termination_fee_cents",
        )
        _integer(
            self.delay_damages_cents_per_month,
            "delay_damages_cents_per_month",
        )
        _integer(self.delay_damages_cap_cents, "delay_damages_cap_cents")
        _integer(self.credit_support_cents, "credit_support_cents")
        object.__setattr__(
            self,
            "conditions_precedent",
            _identifiers(self.conditions_precedent, "conditions_precedent"),
        )

    @classmethod
    def from_dict(
        cls, value: Any, path: str = "service_agreement"
    ) -> "ServiceAgreement":
        fields = {
            "committed_capacity_kw",
            "service_commencement_month",
            "ramp_schedule",
            "monthly_capacity_charge_cents_per_kw",
            "energy_pass_through_cents_per_kwh",
            "take_or_pay_bps",
            "initial_term_months",
            "renewal_option_months",
            "sla_credit_cap_bps",
            "customer_termination_option_month",
            "customer_termination_fee_cents",
            "delay_damages_cents_per_month",
            "delay_damages_cap_cents",
            "credit_support_cents",
            "conditions_precedent",
        }
        data = _exact_mapping(value, required=fields, path=path)
        raw_ramp = data["ramp_schedule"]
        if not isinstance(raw_ramp, (list, tuple)):
            raise ContractValidationError(f"{path}.ramp_schedule must be an array")
        termination_month = data["customer_termination_option_month"]
        return cls(
            committed_capacity_kw=_integer(
                data["committed_capacity_kw"],
                f"{path}.committed_capacity_kw",
                minimum=1,
            ),
            service_commencement_month=_integer(
                data["service_commencement_month"],
                f"{path}.service_commencement_month",
                minimum=1,
            ),
            ramp_schedule=tuple(
                RampStep.from_dict(step, f"{path}.ramp_schedule[{index}]")
                for index, step in enumerate(raw_ramp)
            ),
            monthly_capacity_charge_cents_per_kw=_integer(
                data["monthly_capacity_charge_cents_per_kw"],
                f"{path}.monthly_capacity_charge_cents_per_kw",
            ),
            energy_pass_through_cents_per_kwh=_integer(
                data["energy_pass_through_cents_per_kwh"],
                f"{path}.energy_pass_through_cents_per_kwh",
            ),
            take_or_pay_bps=_basis_points(
                data["take_or_pay_bps"], f"{path}.take_or_pay_bps"
            ),
            initial_term_months=_integer(
                data["initial_term_months"],
                f"{path}.initial_term_months",
                minimum=1,
            ),
            renewal_option_months=_integer(
                data["renewal_option_months"],
                f"{path}.renewal_option_months",
            ),
            sla_credit_cap_bps=_basis_points(
                data["sla_credit_cap_bps"], f"{path}.sla_credit_cap_bps"
            ),
            customer_termination_option_month=(
                None
                if termination_month is None
                else _integer(
                    termination_month,
                    f"{path}.customer_termination_option_month",
                    minimum=1,
                )
            ),
            customer_termination_fee_cents=_integer(
                data["customer_termination_fee_cents"],
                f"{path}.customer_termination_fee_cents",
            ),
            delay_damages_cents_per_month=_integer(
                data["delay_damages_cents_per_month"],
                f"{path}.delay_damages_cents_per_month",
            ),
            delay_damages_cap_cents=_integer(
                data["delay_damages_cap_cents"],
                f"{path}.delay_damages_cap_cents",
            ),
            credit_support_cents=_integer(
                data["credit_support_cents"], f"{path}.credit_support_cents"
            ),
            conditions_precedent=_identifiers(
                data["conditions_precedent"], f"{path}.conditions_precedent"
            ),
        )


@dataclass(frozen=True, slots=True)
class LoanAgreement:
    maximum_commitment_cents: int
    advance_rate_bps: int
    base_rate_curve_id: str
    spread_bps: int
    unused_commitment_fee_bps_annual: int
    origination_fee_bps: int
    interest_reserve_cents: int
    draw_start_month: int
    minimum_contracted_capacity_kw: int
    minimum_take_or_pay_bps: int
    minimum_customer_credit_support_cents: int
    minimum_dscr_bps: int
    maximum_loan_to_cost_bps: int
    maximum_loan_to_value_bps: int
    maturity_month: int
    extension_option_months: int
    completion_guarantee_cents: int
    conditions_precedent: tuple[str, ...]

    def __post_init__(self) -> None:
        _integer(self.maximum_commitment_cents, "maximum_commitment_cents", minimum=1)
        _basis_points(self.advance_rate_bps, "advance_rate_bps")
        _identifier(self.base_rate_curve_id, "base_rate_curve_id")
        _basis_points(self.spread_bps, "spread_bps", maximum=100_000)
        _basis_points(
            self.unused_commitment_fee_bps_annual,
            "unused_commitment_fee_bps_annual",
            maximum=100_000,
        )
        _basis_points(
            self.origination_fee_bps,
            "origination_fee_bps",
            maximum=100_000,
        )
        _integer(self.interest_reserve_cents, "interest_reserve_cents")
        if self.interest_reserve_cents > self.maximum_commitment_cents:
            raise ContractValidationError(
                "interest_reserve_cents cannot exceed maximum_commitment_cents"
            )
        _integer(self.draw_start_month, "draw_start_month", minimum=1)
        _integer(
            self.minimum_contracted_capacity_kw,
            "minimum_contracted_capacity_kw",
        )
        _basis_points(self.minimum_take_or_pay_bps, "minimum_take_or_pay_bps")
        _integer(
            self.minimum_customer_credit_support_cents,
            "minimum_customer_credit_support_cents",
        )
        _basis_points(
            self.minimum_dscr_bps, "minimum_dscr_bps", maximum=100_000
        )
        _basis_points(self.maximum_loan_to_cost_bps, "maximum_loan_to_cost_bps")
        _basis_points(
            self.maximum_loan_to_value_bps,
            "maximum_loan_to_value_bps",
        )
        _integer(self.maturity_month, "maturity_month", minimum=1)
        if self.maturity_month < self.draw_start_month:
            raise ContractValidationError(
                "maturity_month cannot precede draw_start_month"
            )
        _integer(self.extension_option_months, "extension_option_months")
        _integer(
            self.completion_guarantee_cents,
            "completion_guarantee_cents",
        )
        object.__setattr__(
            self,
            "conditions_precedent",
            _identifiers(self.conditions_precedent, "conditions_precedent"),
        )

    @classmethod
    def from_dict(cls, value: Any, path: str = "loan_agreement") -> "LoanAgreement":
        fields = {
            "maximum_commitment_cents",
            "advance_rate_bps",
            "base_rate_curve_id",
            "spread_bps",
            "unused_commitment_fee_bps_annual",
            "origination_fee_bps",
            "interest_reserve_cents",
            "draw_start_month",
            "minimum_contracted_capacity_kw",
            "minimum_take_or_pay_bps",
            "minimum_customer_credit_support_cents",
            "minimum_dscr_bps",
            "maximum_loan_to_cost_bps",
            "maximum_loan_to_value_bps",
            "maturity_month",
            "extension_option_months",
            "completion_guarantee_cents",
            "conditions_precedent",
        }
        data = _exact_mapping(value, required=fields, path=path)
        return cls(
            maximum_commitment_cents=_integer(
                data["maximum_commitment_cents"],
                f"{path}.maximum_commitment_cents",
                minimum=1,
            ),
            advance_rate_bps=_basis_points(
                data["advance_rate_bps"], f"{path}.advance_rate_bps"
            ),
            base_rate_curve_id=_identifier(
                data["base_rate_curve_id"], f"{path}.base_rate_curve_id"
            ),
            spread_bps=_basis_points(
                data["spread_bps"], f"{path}.spread_bps", maximum=100_000
            ),
            unused_commitment_fee_bps_annual=_basis_points(
                data["unused_commitment_fee_bps_annual"],
                f"{path}.unused_commitment_fee_bps_annual",
                maximum=100_000,
            ),
            origination_fee_bps=_basis_points(
                data["origination_fee_bps"],
                f"{path}.origination_fee_bps",
                maximum=100_000,
            ),
            interest_reserve_cents=_integer(
                data["interest_reserve_cents"],
                f"{path}.interest_reserve_cents",
            ),
            draw_start_month=_integer(
                data["draw_start_month"], f"{path}.draw_start_month", minimum=1
            ),
            minimum_contracted_capacity_kw=_integer(
                data["minimum_contracted_capacity_kw"],
                f"{path}.minimum_contracted_capacity_kw",
            ),
            minimum_take_or_pay_bps=_basis_points(
                data["minimum_take_or_pay_bps"],
                f"{path}.minimum_take_or_pay_bps",
            ),
            minimum_customer_credit_support_cents=_integer(
                data["minimum_customer_credit_support_cents"],
                f"{path}.minimum_customer_credit_support_cents",
            ),
            minimum_dscr_bps=_basis_points(
                data["minimum_dscr_bps"],
                f"{path}.minimum_dscr_bps",
                maximum=100_000,
            ),
            maximum_loan_to_cost_bps=_basis_points(
                data["maximum_loan_to_cost_bps"],
                f"{path}.maximum_loan_to_cost_bps",
            ),
            maximum_loan_to_value_bps=_basis_points(
                data["maximum_loan_to_value_bps"],
                f"{path}.maximum_loan_to_value_bps",
            ),
            maturity_month=_integer(
                data["maturity_month"], f"{path}.maturity_month", minimum=1
            ),
            extension_option_months=_integer(
                data["extension_option_months"],
                f"{path}.extension_option_months",
            ),
            completion_guarantee_cents=_integer(
                data["completion_guarantee_cents"],
                f"{path}.completion_guarantee_cents",
            ),
            conditions_precedent=_identifiers(
                data["conditions_precedent"], f"{path}.conditions_precedent"
            ),
        )


@dataclass(frozen=True, slots=True)
class PowerAgreement:
    contracted_capacity_kw: int
    energization_month: int
    interconnection_cost_cents: int
    monthly_demand_charge_cents_per_kw: int
    energy_charge_cents_per_kwh: int
    delay_liquidated_damages_cents_per_month: int
    delay_liquidated_damages_cap_cents: int
    developer_security_cents: int
    initial_term_months: int
    conditions_precedent: tuple[str, ...]

    def __post_init__(self) -> None:
        _integer(self.contracted_capacity_kw, "contracted_capacity_kw", minimum=1)
        _integer(self.energization_month, "energization_month", minimum=1)
        _integer(self.interconnection_cost_cents, "interconnection_cost_cents")
        _integer(
            self.monthly_demand_charge_cents_per_kw,
            "monthly_demand_charge_cents_per_kw",
        )
        _integer(self.energy_charge_cents_per_kwh, "energy_charge_cents_per_kwh")
        _integer(
            self.delay_liquidated_damages_cents_per_month,
            "delay_liquidated_damages_cents_per_month",
        )
        _integer(
            self.delay_liquidated_damages_cap_cents,
            "delay_liquidated_damages_cap_cents",
        )
        _integer(self.developer_security_cents, "developer_security_cents")
        _integer(self.initial_term_months, "initial_term_months", minimum=1)
        object.__setattr__(
            self,
            "conditions_precedent",
            _identifiers(self.conditions_precedent, "conditions_precedent"),
        )

    @classmethod
    def from_dict(cls, value: Any, path: str = "power_agreement") -> "PowerAgreement":
        fields = {
            "contracted_capacity_kw",
            "energization_month",
            "interconnection_cost_cents",
            "monthly_demand_charge_cents_per_kw",
            "energy_charge_cents_per_kwh",
            "delay_liquidated_damages_cents_per_month",
            "delay_liquidated_damages_cap_cents",
            "developer_security_cents",
            "initial_term_months",
            "conditions_precedent",
        }
        data = _exact_mapping(value, required=fields, path=path)
        return cls(
            contracted_capacity_kw=_integer(
                data["contracted_capacity_kw"],
                f"{path}.contracted_capacity_kw",
                minimum=1,
            ),
            energization_month=_integer(
                data["energization_month"], f"{path}.energization_month", minimum=1
            ),
            interconnection_cost_cents=_integer(
                data["interconnection_cost_cents"],
                f"{path}.interconnection_cost_cents",
            ),
            monthly_demand_charge_cents_per_kw=_integer(
                data["monthly_demand_charge_cents_per_kw"],
                f"{path}.monthly_demand_charge_cents_per_kw",
            ),
            energy_charge_cents_per_kwh=_integer(
                data["energy_charge_cents_per_kwh"],
                f"{path}.energy_charge_cents_per_kwh",
            ),
            delay_liquidated_damages_cents_per_month=_integer(
                data["delay_liquidated_damages_cents_per_month"],
                f"{path}.delay_liquidated_damages_cents_per_month",
            ),
            delay_liquidated_damages_cap_cents=_integer(
                data["delay_liquidated_damages_cap_cents"],
                f"{path}.delay_liquidated_damages_cap_cents",
            ),
            developer_security_cents=_integer(
                data["developer_security_cents"], f"{path}.developer_security_cents"
            ),
            initial_term_months=_integer(
                data["initial_term_months"], f"{path}.initial_term_months", minimum=1
            ),
            conditions_precedent=_identifiers(
                data["conditions_precedent"], f"{path}.conditions_precedent"
            ),
        )


@dataclass(frozen=True, slots=True)
class EpcPayment:
    month: int
    amount_cents: int

    def __post_init__(self) -> None:
        _integer(self.month, "epc payment month", minimum=1)
        _integer(self.amount_cents, "epc payment amount_cents")

    @classmethod
    def from_dict(cls, value: Any, path: str = "epc_payment") -> "EpcPayment":
        data = _exact_mapping(
            value, required={"month", "amount_cents"}, path=path
        )
        return cls(
            month=_integer(data["month"], f"{path}.month", minimum=1),
            amount_cents=_integer(data["amount_cents"], f"{path}.amount_cents"),
        )


@dataclass(frozen=True, slots=True)
class EpcAgreement:
    notice_to_proceed_month: int
    guaranteed_completion_month: int
    guaranteed_capacity_kw: int
    contract_price_cents: int
    payment_schedule: tuple[EpcPayment, ...]
    delay_liquidated_damages_cents_per_month: int
    delay_liquidated_damages_cap_cents: int
    cost_overrun_cap_cents: int
    completion_guarantee_cents: int
    conditions_precedent: tuple[str, ...]

    def __post_init__(self) -> None:
        _integer(self.notice_to_proceed_month, "notice_to_proceed_month", minimum=1)
        _integer(
            self.guaranteed_completion_month,
            "guaranteed_completion_month",
            minimum=self.notice_to_proceed_month,
        )
        _integer(self.guaranteed_capacity_kw, "guaranteed_capacity_kw", minimum=1)
        _integer(self.contract_price_cents, "contract_price_cents", minimum=1)
        if not isinstance(self.payment_schedule, tuple) or not self.payment_schedule:
            raise ContractValidationError("payment_schedule must be a non-empty tuple")
        if any(not isinstance(item, EpcPayment) for item in self.payment_schedule):
            raise ContractValidationError("payment_schedule must contain EpcPayment values")
        months = tuple(item.month for item in self.payment_schedule)
        if tuple(sorted(months)) != months or len(set(months)) != len(months):
            raise ContractValidationError("EPC payment months must be strictly increasing")
        if months[0] < self.notice_to_proceed_month:
            raise ContractValidationError("EPC payments cannot precede notice to proceed")
        if sum(item.amount_cents for item in self.payment_schedule) != self.contract_price_cents:
            raise ContractValidationError("EPC payment schedule must equal contract_price_cents")
        _integer(
            self.delay_liquidated_damages_cents_per_month,
            "delay_liquidated_damages_cents_per_month",
        )
        _integer(
            self.delay_liquidated_damages_cap_cents,
            "delay_liquidated_damages_cap_cents",
        )
        _integer(self.cost_overrun_cap_cents, "cost_overrun_cap_cents")
        _integer(self.completion_guarantee_cents, "completion_guarantee_cents")
        object.__setattr__(
            self,
            "conditions_precedent",
            _identifiers(self.conditions_precedent, "conditions_precedent"),
        )

    @classmethod
    def from_dict(cls, value: Any, path: str = "epc_agreement") -> "EpcAgreement":
        fields = {
            "notice_to_proceed_month",
            "guaranteed_completion_month",
            "guaranteed_capacity_kw",
            "contract_price_cents",
            "payment_schedule",
            "delay_liquidated_damages_cents_per_month",
            "delay_liquidated_damages_cap_cents",
            "cost_overrun_cap_cents",
            "completion_guarantee_cents",
            "conditions_precedent",
        }
        data = _exact_mapping(value, required=fields, path=path)
        schedule = data["payment_schedule"]
        if not isinstance(schedule, (list, tuple)):
            raise ContractValidationError(f"{path}.payment_schedule must be an array")
        return cls(
            notice_to_proceed_month=_integer(
                data["notice_to_proceed_month"],
                f"{path}.notice_to_proceed_month",
                minimum=1,
            ),
            guaranteed_completion_month=_integer(
                data["guaranteed_completion_month"],
                f"{path}.guaranteed_completion_month",
                minimum=1,
            ),
            guaranteed_capacity_kw=_integer(
                data["guaranteed_capacity_kw"],
                f"{path}.guaranteed_capacity_kw",
                minimum=1,
            ),
            contract_price_cents=_integer(
                data["contract_price_cents"], f"{path}.contract_price_cents", minimum=1
            ),
            payment_schedule=tuple(
                EpcPayment.from_dict(item, f"{path}.payment_schedule[{index}]")
                for index, item in enumerate(schedule)
            ),
            delay_liquidated_damages_cents_per_month=_integer(
                data["delay_liquidated_damages_cents_per_month"],
                f"{path}.delay_liquidated_damages_cents_per_month",
            ),
            delay_liquidated_damages_cap_cents=_integer(
                data["delay_liquidated_damages_cap_cents"],
                f"{path}.delay_liquidated_damages_cap_cents",
            ),
            cost_overrun_cap_cents=_integer(
                data["cost_overrun_cap_cents"], f"{path}.cost_overrun_cap_cents"
            ),
            completion_guarantee_cents=_integer(
                data["completion_guarantee_cents"],
                f"{path}.completion_guarantee_cents",
            ),
            conditions_precedent=_identifiers(
                data["conditions_precedent"], f"{path}.conditions_precedent"
            ),
        )


@dataclass(frozen=True, slots=True)
class LandAgreement:
    site_control_start_month: int
    closing_month: int
    site_control_expiry_month: int
    purchase_price_cents: int
    extension_option_months: int
    extension_price_cents: int
    permitted_use_capacity_kw: int
    conditions_precedent: tuple[str, ...]

    def __post_init__(self) -> None:
        _integer(self.site_control_start_month, "site_control_start_month", minimum=1)
        _integer(self.closing_month, "closing_month", minimum=self.site_control_start_month)
        _integer(
            self.site_control_expiry_month,
            "site_control_expiry_month",
            minimum=self.closing_month,
        )
        _integer(self.purchase_price_cents, "purchase_price_cents")
        _integer(self.extension_option_months, "extension_option_months")
        _integer(self.extension_price_cents, "extension_price_cents")
        _integer(self.permitted_use_capacity_kw, "permitted_use_capacity_kw", minimum=1)
        object.__setattr__(
            self,
            "conditions_precedent",
            _identifiers(self.conditions_precedent, "conditions_precedent"),
        )

    @classmethod
    def from_dict(cls, value: Any, path: str = "land_agreement") -> "LandAgreement":
        fields = {
            "site_control_start_month",
            "closing_month",
            "site_control_expiry_month",
            "purchase_price_cents",
            "extension_option_months",
            "extension_price_cents",
            "permitted_use_capacity_kw",
            "conditions_precedent",
        }
        data = _exact_mapping(value, required=fields, path=path)
        return cls(
            site_control_start_month=_integer(
                data["site_control_start_month"],
                f"{path}.site_control_start_month",
                minimum=1,
            ),
            closing_month=_integer(
                data["closing_month"], f"{path}.closing_month", minimum=1
            ),
            site_control_expiry_month=_integer(
                data["site_control_expiry_month"],
                f"{path}.site_control_expiry_month",
                minimum=1,
            ),
            purchase_price_cents=_integer(
                data["purchase_price_cents"], f"{path}.purchase_price_cents"
            ),
            extension_option_months=_integer(
                data["extension_option_months"], f"{path}.extension_option_months"
            ),
            extension_price_cents=_integer(
                data["extension_price_cents"], f"{path}.extension_price_cents"
            ),
            permitted_use_capacity_kw=_integer(
                data["permitted_use_capacity_kw"],
                f"{path}.permitted_use_capacity_kw",
                minimum=1,
            ),
            conditions_precedent=_identifiers(
                data["conditions_precedent"], f"{path}.conditions_precedent"
            ),
        )


AgreementTerms = (
    ServiceAgreement | LoanAgreement | PowerAgreement | EpcAgreement | LandAgreement
)

_TERM_TYPE_BY_AGREEMENT = {
    "service": ServiceAgreement,
    "loan": LoanAgreement,
    "power": PowerAgreement,
    "epc": EpcAgreement,
    "land": LandAgreement,
}


@dataclass(frozen=True, slots=True)
class ContractOffer:
    offer_id: str
    case_id: str
    agreement_type: str
    proposer_seat_id: str
    round_index: int
    message: str
    terms: AgreementTerms
    supersedes_offer_id: str | None = None
    amended_fields: tuple[str, ...] = ()
    precedence_index: int = 0

    def __post_init__(self) -> None:
        _identifier(self.offer_id, "offer_id")
        _identifier(self.case_id, "case_id")
        if self.agreement_type not in _TERM_TYPE_BY_AGREEMENT:
            raise ContractValidationError("agreement_type is unsupported")
        _identifier(self.proposer_seat_id, "proposer_seat_id")
        _integer(self.round_index, "round_index")
        _text(self.message, "message")
        expected = _TERM_TYPE_BY_AGREEMENT[self.agreement_type]
        if not isinstance(self.terms, expected):
            raise ContractValidationError(
                f"{self.agreement_type} offer carries the wrong term type"
            )
        if self.supersedes_offer_id is None:
            if self.amended_fields or self.precedence_index != 0:
                raise ContractValidationError(
                    "non-amendment offer cannot carry amendment precedence"
                )
        else:
            _identifier(self.supersedes_offer_id, "supersedes_offer_id")
            fields = _identifiers(self.amended_fields, "amended_fields")
            if not fields:
                raise ContractValidationError("amendment must identify changed fields")
            if any(field not in {item.name for item in dataclasses.fields(self.terms)} for field in fields):
                raise ContractValidationError("amended_fields contains an unknown term field")
            _integer(self.precedence_index, "precedence_index", minimum=1)
            object.__setattr__(self, "amended_fields", tuple(sorted(fields)))
        expected_offer_id = offer_id_for(
            case_id=self.case_id,
            agreement_type=self.agreement_type,
            proposer_seat_id=self.proposer_seat_id,
            round_index=self.round_index,
            terms=self.terms,
            supersedes_offer_id=self.supersedes_offer_id,
            amended_fields=self.amended_fields,
            precedence_index=self.precedence_index,
        )
        if self.offer_id != expected_offer_id:
            raise ContractValidationError(
                "offer_id does not match the canonical written terms"
            )


@dataclass(frozen=True, slots=True)
class ContractSignature:
    offer_id: str
    seat_id: str

    def __post_init__(self) -> None:
        _identifier(self.offer_id, "signature offer_id")
        _identifier(self.seat_id, "signature seat_id")


@dataclass(frozen=True, slots=True)
class ExecutedAgreement:
    offer_id: str
    case_id: str
    agreement_type: str
    proposer_seat_id: str
    round_index: int
    terms: AgreementTerms
    signed_by: tuple[str, ...]
    supersedes_offer_id: str | None = None
    amended_fields: tuple[str, ...] = ()
    precedence_index: int = 0

    def __post_init__(self) -> None:
        _identifier(self.offer_id, "executed offer_id")
        _identifier(self.case_id, "executed case_id")
        if self.agreement_type not in _TERM_TYPE_BY_AGREEMENT:
            raise ContractValidationError("executed agreement_type is invalid")
        expected = _TERM_TYPE_BY_AGREEMENT[self.agreement_type]
        if not isinstance(self.terms, expected):
            raise ContractValidationError("executed agreement carries wrong terms")
        _identifier(self.proposer_seat_id, "executed proposer_seat_id")
        _integer(self.round_index, "executed round_index")
        if self.offer_id != offer_id_for(
            case_id=self.case_id,
            agreement_type=self.agreement_type,
            proposer_seat_id=self.proposer_seat_id,
            round_index=self.round_index,
            terms=self.terms,
            supersedes_offer_id=self.supersedes_offer_id,
            amended_fields=self.amended_fields,
            precedence_index=self.precedence_index,
        ):
            raise ContractValidationError(
                "executed offer_id does not match the canonical written terms"
            )
        object.__setattr__(
            self,
            "signed_by",
            tuple(sorted(_identifiers(self.signed_by, "signed_by"))),
        )
        if self.supersedes_offer_id is None:
            if self.amended_fields or self.precedence_index != 0:
                raise ContractValidationError(
                    "executed non-amendment cannot carry precedence metadata"
                )
        else:
            _identifier(self.supersedes_offer_id, "executed supersedes_offer_id")
            fields = _identifiers(self.amended_fields, "executed amended_fields")
            if not fields:
                raise ContractValidationError("executed amendment lacks amended_fields")
            _integer(self.precedence_index, "executed precedence_index", minimum=1)
            object.__setattr__(self, "amended_fields", tuple(sorted(fields)))


def offer_id_for(
    *,
    case_id: str,
    agreement_type: str,
    proposer_seat_id: str,
    round_index: int,
    terms: AgreementTerms,
    supersedes_offer_id: str | None = None,
    amended_fields: Sequence[str] = (),
    precedence_index: int = 0,
) -> str:
    """Derive the immutable written-offer identity from canonical term bytes."""

    _identifier(case_id, "case_id")
    _identifier(proposer_seat_id, "proposer_seat_id")
    _integer(round_index, "round_index")
    if agreement_type not in _TERM_TYPE_BY_AGREEMENT:
        raise ContractValidationError("agreement_type is unsupported")
    expected = _TERM_TYPE_BY_AGREEMENT[agreement_type]
    if not isinstance(terms, expected):
        raise ContractValidationError(
            f"{agreement_type} offer carries the wrong term type"
        )
    identity: dict[str, Any] = {
        "case_id": case_id,
        "agreement_type": agreement_type,
        "proposer_seat_id": proposer_seat_id,
        "round_index": round_index,
        "terms": terms,
    }
    if supersedes_offer_id is not None:
        _identifier(supersedes_offer_id, "supersedes_offer_id")
        checked_fields = tuple(sorted(_identifiers(amended_fields, "amended_fields")))
        if not checked_fields:
            raise ContractValidationError("amendment must identify changed fields")
        _integer(precedence_index, "precedence_index", minimum=1)
        identity.update(
            {
                "supersedes_offer_id": supersedes_offer_id,
                "amended_fields": checked_fields,
                "precedence_index": precedence_index,
            }
        )
    elif amended_fields or precedence_index != 0:
        raise ContractValidationError(
            "non-amendment offer cannot carry amendment precedence"
        )
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return f"offer_{digest[:24]}"


def make_offer(
    *,
    case_id: str,
    agreement_type: str,
    proposer_seat_id: str,
    round_index: int,
    message: str,
    terms: AgreementTerms,
    supersedes_offer_id: str | None = None,
    amended_fields: Sequence[str] = (),
    precedence_index: int = 0,
) -> ContractOffer:
    return ContractOffer(
        offer_id=offer_id_for(
            case_id=case_id,
            agreement_type=agreement_type,
            proposer_seat_id=proposer_seat_id,
            round_index=round_index,
            terms=terms,
            supersedes_offer_id=supersedes_offer_id,
            amended_fields=amended_fields,
            precedence_index=precedence_index,
        ),
        case_id=case_id,
        agreement_type=agreement_type,
        proposer_seat_id=proposer_seat_id,
        round_index=round_index,
        message=message,
        terms=terms,
        supersedes_offer_id=supersedes_offer_id,
        amended_fields=tuple(amended_fields),
        precedence_index=precedence_index,
    )


def execute_offer(
    offer: ContractOffer,
    signatures: Sequence[ContractSignature],
    *,
    required_signers: Sequence[str],
) -> ExecutedAgreement:
    """Execute exactly one immutable offer after every required signature."""

    if not isinstance(offer, ContractOffer):
        raise ContractValidationError("offer must be a ContractOffer")
    required = tuple(sorted(_identifiers(required_signers, "required_signers")))
    if not required:
        raise ContractValidationError("required_signers must not be empty")
    if not isinstance(signatures, Sequence) or isinstance(signatures, (str, bytes)):
        raise ContractValidationError("signatures must be a sequence")
    checked: list[ContractSignature] = []
    for signature in signatures:
        if not isinstance(signature, ContractSignature):
            raise ContractValidationError(
                "signatures must contain ContractSignature values"
            )
        if signature.offer_id != offer.offer_id:
            raise ContractValidationError("signature references a different offer")
        checked.append(signature)
    signers = tuple(sorted(signature.seat_id for signature in checked))
    if len(set(signers)) != len(signers):
        raise ContractValidationError("an offer cannot be signed twice by one seat")
    if signers != required:
        raise ContractValidationError(
            f"signers differ: required={list(required)}, observed={list(signers)}"
        )
    return ExecutedAgreement(
        offer_id=offer.offer_id,
        case_id=offer.case_id,
        agreement_type=offer.agreement_type,
        proposer_seat_id=offer.proposer_seat_id,
        round_index=offer.round_index,
        terms=offer.terms,
        signed_by=signers,
        supersedes_offer_id=offer.supersedes_offer_id,
        amended_fields=offer.amended_fields,
        precedence_index=offer.precedence_index,
    )


def apply_executed_amendment(
    prior: ExecutedAgreement, amendment: ExecutedAgreement
) -> ExecutedAgreement:
    """Validate explicit field-level precedence and return the superseding instrument."""

    if prior.case_id != amendment.case_id or prior.agreement_type != amendment.agreement_type:
        raise ContractValidationError("amendment must target the same case and agreement type")
    if amendment.supersedes_offer_id != prior.offer_id:
        raise ContractValidationError("amendment does not supersede the active offer")
    if amendment.precedence_index <= prior.precedence_index:
        raise ContractValidationError("amendment precedence must increase")
    prior_terms = dataclasses.asdict(prior.terms)
    amendment_terms = dataclasses.asdict(amendment.terms)
    changed = tuple(
        sorted(
            field
            for field in prior_terms
            if prior_terms[field] != amendment_terms[field]
        )
    )
    if changed != amendment.amended_fields:
        raise ContractValidationError(
            "amended_fields must exactly match the changed structured terms"
        )
    return amendment


__all__ = [
    "AgreementTerms",
    "ContractOffer",
    "ContractSignature",
    "ContractValidationError",
    "EpcAgreement",
    "EpcPayment",
    "ExecutedAgreement",
    "LandAgreement",
    "LoanAgreement",
    "PowerAgreement",
    "RampStep",
    "ServiceAgreement",
    "apply_executed_amendment",
    "execute_offer",
    "make_offer",
    "offer_id_for",
]
