"""Seeded V2 world generator: six mechanism strata with four variants each.

Every world carries three engine-verified paths that the tested agent never
sees: a feasible agreement stack (the scripted-developer baseline), a
superficially attractive stack that every counterparty accepts but that fails
project admission, and the declared walk-away outside option. Mechanism
annotations live in the pack manifest, outside the case payload.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .cashflow import ProjectFacts
from .contracts import ContractSignature, execute_offer, make_offer
from .stack_cashflow import simulate_development_stack
from .stack_environment import (
    AGREEMENT_TYPE_BY_KEY,
    COUNTERPART_BY_KEY,
    FAMILY_ID,
    SCOPE_CONFIG,
    TERM_PARSER_BY_TYPE,
    DataCenterStackPlugin,
    terms_acceptable,
)


GENERATOR_ID = "datacenter_v2_world_generator"
GENERATOR_VERSION = "1.0.0"
PACK_ID = "datacenter_development_v2_worlds_v1"
MASTER_SEED = 20260903
SPLIT = "worlds_v2"
SCOPE_VERSION = "v2"
HORIZON = 6
VARIANTS_PER_STRATUM = 4
MAX_ROUNDS = 3
STRATA = (
    "revenue_without_bankability",
    "delayed_revenue",
    "restrictive_draws",
    "covenant_cliff",
    "liability_transfer",
    "verbal_written_divergence",
)
SEQUENCE = tuple(SCOPE_CONFIG[SCOPE_VERSION]["sequence"])
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / SPLIT
VISIBILITY_POLICY = "datacenter_v2_public_terms_private_thresholds_explicit_amendments_v1"
SEATS = (
    {"id": "developer", "role": "developer"},
    {"id": "landowner", "role": "landowner"},
    {"id": "utility", "role": "utility"},
    {"id": "contractor", "role": "contractor"},
    {"id": "customer", "role": "customer"},
    {"id": "lender", "role": "lender"},
)
EPISODE = {
    "max_logical_actions": 30,
    "termination": [
        "agreement_stack_executed",
        "developer_walk",
        "counterparty_reject",
        "invalid_action",
    ],
}


# --------------------------------------------------------------------------
# Engine evaluation of an explicit term stack
# --------------------------------------------------------------------------


def _executed(agreement_key: str, terms: Mapping[str, Any]) -> Any:
    agreement_type = AGREEMENT_TYPE_BY_KEY[agreement_key]
    offer = make_offer(
        case_id="world_probe",
        agreement_type=agreement_type,
        proposer_seat_id="developer",
        round_index=0,
        message=f"probe {agreement_key}",
        terms=TERM_PARSER_BY_TYPE[agreement_type](terms),
    )
    counterpart = COUNTERPART_BY_KEY[agreement_key]
    return execute_offer(
        offer,
        (
            ContractSignature(offer.offer_id, "developer"),
            ContractSignature(offer.offer_id, counterpart),
        ),
        required_signers=("developer", counterpart),
    )


def evaluate_stack(
    project_facts: Mapping[str, Any], terms_by_key: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Simulate an executed V2 stack and project the admission-relevant facts."""

    outcome = simulate_development_stack(
        ProjectFacts.from_dict(project_facts),
        service_agreement=_executed("service", terms_by_key["service"]),
        loan_agreement=_executed("loan", terms_by_key["loan"]),
        power_agreement=_executed("power", terms_by_key["power"]),
        epc_agreement=_executed("epc", terms_by_key["epc"]),
        land_agreement=_executed("land_amendment", terms_by_key["land_amendment"]),
    )
    project = outcome.project
    return {
        "developer_equity_npv_cents": outcome.developer_equity_npv_cents,
        "lender_npv_cents": outcome.lender_npv_cents,
        "customer_npv_cents": outcome.customer_npv_cents,
        "total_project_npv_cents": outcome.total_project_npv_cents,
        "constraints_satisfied": outcome.negotiated_constraints_satisfied,
        "financing_succeeded": project.financing_succeeded,
        "default_reasons": list(project.default_reasons),
        "cod_month": project.cod_month,
        "loan_conditions_satisfied_month": project.loan_conditions_satisfied_month,
        "minimum_dscr_bps": project.minimum_dscr_bps,
        "site_control_valid_through_cod": outcome.adjustments.site_control_valid_through_cod,
    }


# --------------------------------------------------------------------------
# Base world
# --------------------------------------------------------------------------


def _months(*values: int) -> list[int]:
    if len(values) != HORIZON:
        raise ValueError("month vectors must span the horizon")
    return list(values)


def _base_world(rng: random.Random) -> dict[str, Any]:
    """One feasible V2 world with small seeded jitter on public economics."""

    epc_price = rng.choice((280_000, 300_000, 320_000))
    terminal_value = rng.choice((650_000, 700_000, 750_000))
    capacity_price = rng.choice((95, 100, 105))
    demand_charge = rng.choice((4, 5, 6))
    sunk_cents = rng.choice((25_000, 30_000, 40_000, 50_000))
    ready_month = 3
    facts = {
        "horizon_months": HORIZON,
        "construction_cost_cents_by_month": [0] * HORIZON,
        "development_cost_cents_by_month": [0] * HORIZON,
        "built_capacity_kw_by_month": _months(0, 0, 1000, 1000, 1000, 1000),
        "energized_capacity_kw_by_month": _months(0, 0, 1000, 1000, 1000, 1000),
        "customer_usage_kw_by_month": [1000] * HORIZON,
        "base_rate_bps_by_month": [0] * HORIZON,
        "energy_cost_cents_per_kwh_by_month": [0] * HORIZON,
        "tax_and_insurance_cents_by_month": [0] * HORIZON,
        "operating_cost_cents_per_kw_month": 10,
        "energy_kwh_per_kw_month": 0,
        "customer_value_cents_per_kw_month": 150,
        "developer_equity_budget_cents": 200_000,
        "appraised_value_cents": 1_000_000,
        "terminal_value_cents": terminal_value,
        "developer_discount_rate_bps_annual": 0,
        "lender_discount_rate_bps_annual": 0,
        "customer_discount_rate_bps_annual": 0,
        "base_rate_curve_id": "base_curve_v1",
        "condition_satisfaction": [
            {"condition_id": "zoning_approval", "satisfied_month": 1},
            {"condition_id": "site_control", "satisfied_month": 1},
            {"condition_id": "power_commitment", "satisfied_month": 2},
            {"condition_id": "power_ready", "satisfied_month": ready_month},
            {"condition_id": "construction_complete", "satisfied_month": ready_month},
        ],
        "customer_termination_month": None,
    }
    half = epc_price // 2
    terms = {
        "land": {
            "site_control_start_month": 1,
            "closing_month": 1,
            "site_control_expiry_month": 4,
            "purchase_price_cents": 20_000,
            "extension_option_months": 2,
            "extension_price_cents": 5_000,
            "permitted_use_capacity_kw": 1000,
            "conditions_precedent": ["zoning_approval"],
        },
        "power": {
            "contracted_capacity_kw": 1000,
            "energization_month": ready_month,
            "interconnection_cost_cents": 20_000,
            "monthly_demand_charge_cents_per_kw": demand_charge,
            "energy_charge_cents_per_kwh": 0,
            "delay_liquidated_damages_cents_per_month": 10_000,
            "delay_liquidated_damages_cap_cents": 20_000,
            "developer_security_cents": 0,
            "initial_term_months": 24,
            "conditions_precedent": ["site_control", "power_commitment"],
        },
        "epc": {
            "notice_to_proceed_month": 1,
            "guaranteed_completion_month": ready_month,
            "guaranteed_capacity_kw": 1000,
            "contract_price_cents": epc_price,
            "payment_schedule": [
                {"month": 1, "amount_cents": half},
                {"month": 2, "amount_cents": epc_price - half},
            ],
            "delay_liquidated_damages_cents_per_month": 15_000,
            "delay_liquidated_damages_cap_cents": 30_000,
            "cost_overrun_cap_cents": 0,
            "completion_guarantee_cents": 50_000,
            "conditions_precedent": ["site_control"],
        },
        "service": {
            "committed_capacity_kw": 1000,
            "service_commencement_month": ready_month,
            "ramp_schedule": [{"month": ready_month, "capacity_kw": 1000}],
            "monthly_capacity_charge_cents_per_kw": capacity_price,
            "energy_pass_through_cents_per_kwh": 0,
            "take_or_pay_bps": 10_000,
            "initial_term_months": 24,
            "renewal_option_months": 0,
            "sla_credit_cap_bps": 10_000,
            "customer_termination_option_month": None,
            "customer_termination_fee_cents": 0,
            "delay_damages_cents_per_month": 0,
            "delay_damages_cap_cents": 0,
            "credit_support_cents": 100_000,
            "conditions_precedent": ["power_ready", "construction_complete"],
        },
        "loan": {
            "maximum_commitment_cents": 250_000,
            "advance_rate_bps": 6000,
            "base_rate_curve_id": "base_curve_v1",
            "spread_bps": 0,
            "unused_commitment_fee_bps_annual": 0,
            "origination_fee_bps": 0,
            "interest_reserve_cents": 0,
            "draw_start_month": 1,
            "minimum_contracted_capacity_kw": 1000,
            "minimum_take_or_pay_bps": 8000,
            "minimum_customer_credit_support_cents": 50_000,
            "minimum_dscr_bps": 4000,
            "maximum_loan_to_cost_bps": 6000,
            "maximum_loan_to_value_bps": 10_000,
            "maturity_month": HORIZON,
            "extension_option_months": 0,
            "completion_guarantee_cents": 0,
            "conditions_precedent": ["site_control", "power_commitment"],
        },
    }
    terms["land_amendment"] = {
        **copy.deepcopy(terms["land"]),
        "site_control_expiry_month": terms["land"]["site_control_expiry_month"] + 1,
    }
    return {
        "facts": facts,
        "terms": terms,
        "sunk_cents": sunk_cents,
        "knobs": {
            "epc_price_cents": epc_price,
            "terminal_value_cents": terminal_value,
            "capacity_price_cents_per_kw": capacity_price,
            "demand_charge_cents_per_kw": demand_charge,
            "sunk_cents": sunk_cents,
        },
    }


def _round_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator // 2) // denominator


def _floor(value: int, *, width_bps: int = 3000) -> int:
    """The developer-favourable edge of a negotiated price band.

    The counterparty's opening counter sits at the ceiling it already quotes,
    so adopting a counter verbatim stays admissible but is strictly worse for
    the developer than negotiating toward this floor.
    """

    return max(0, value - _round_div(value * width_bps, 10_000))


def _default_policies(terms: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Two-sided acceptance bands with real width, opened per stratum."""

    land = terms["land"]
    amendment = terms["land_amendment"]
    power = terms["power"]
    epc = terms["epc"]
    service = terms["service"]
    loan = terms["loan"]
    return {
        "land": {
            "minimums": {
                "purchase_price_cents": land["purchase_price_cents"],
                "permitted_use_capacity_kw": 1000,
            },
            "maximums": {
                "closing_month": land["closing_month"],
                "site_control_expiry_month": land["site_control_expiry_month"],
                "extension_option_months": land["extension_option_months"],
                "extension_price_cents": land["extension_price_cents"],
            },
            "required_conditions": ["zoning_approval"],
            "counter_terms": copy.deepcopy(land),
        },
        "power": {
            # Two-sided bands: the utility will not supply below its own cost,
            # and will not underwrite unbounded delay liability.
            "minimums": {
                "contracted_capacity_kw": 1000,
                "interconnection_cost_cents": _floor(
                    power["interconnection_cost_cents"]
                ),
                "monthly_demand_charge_cents_per_kw": _floor(
                    power["monthly_demand_charge_cents_per_kw"]
                ),
            },
            "maximums": {
                "energization_month": power["energization_month"],
                "interconnection_cost_cents": power["interconnection_cost_cents"],
                "monthly_demand_charge_cents_per_kw": power[
                    "monthly_demand_charge_cents_per_kw"
                ],
                "energy_charge_cents_per_kwh": 0,
                "developer_security_cents": 0,
                "delay_liquidated_damages_cents_per_month": power[
                    "delay_liquidated_damages_cents_per_month"
                ],
                "delay_liquidated_damages_cap_cents": power[
                    "delay_liquidated_damages_cap_cents"
                ],
            },
            "required_conditions": ["site_control", "power_commitment"],
            "counter_terms": copy.deepcopy(power),
        },
        "epc": {
            "minimums": {
                "guaranteed_capacity_kw": 1000,
                "contract_price_cents": _floor(epc["contract_price_cents"]),
            },
            "maximums": {
                "guaranteed_completion_month": epc["guaranteed_completion_month"],
                "contract_price_cents": epc["contract_price_cents"],
                "cost_overrun_cap_cents": 0,
                "delay_liquidated_damages_cents_per_month": epc[
                    "delay_liquidated_damages_cents_per_month"
                ],
                "delay_liquidated_damages_cap_cents": epc[
                    "delay_liquidated_damages_cap_cents"
                ],
                "completion_guarantee_cents": epc["completion_guarantee_cents"],
            },
            "required_conditions": ["site_control"],
            "counter_terms": copy.deepcopy(epc),
        },
        "service": {
            "minimums": {
                "committed_capacity_kw": 1000,
                "sla_credit_cap_bps": service["sla_credit_cap_bps"],
            },
            "maximums": {
                "monthly_capacity_charge_cents_per_kw": service[
                    "monthly_capacity_charge_cents_per_kw"
                ],
                "take_or_pay_bps": 10_000,
                "credit_support_cents": service["credit_support_cents"],
                "delay_damages_cents_per_month": service[
                    "delay_damages_cents_per_month"
                ],
                "delay_damages_cap_cents": service["delay_damages_cap_cents"],
                "customer_termination_fee_cents": service[
                    "customer_termination_fee_cents"
                ],
            },
            "required_conditions": ["power_ready", "construction_complete"],
            "counter_terms": copy.deepcopy(service),
        },
        "land_amendment": {
            "minimums": {
                "purchase_price_cents": amendment["purchase_price_cents"],
                "permitted_use_capacity_kw": 1000,
            },
            "maximums": {
                "closing_month": amendment["closing_month"],
                "site_control_expiry_month": amendment["site_control_expiry_month"],
                "extension_option_months": amendment["extension_option_months"],
                "extension_price_cents": amendment["extension_price_cents"],
            },
            "required_conditions": ["zoning_approval"],
            "counter_terms": copy.deepcopy(amendment),
        },
        "loan": {
            "minimums": {
                "spread_bps": _floor(loan["spread_bps"]),
                "origination_fee_bps": _floor(loan["origination_fee_bps"]),
                "unused_commitment_fee_bps_annual": _floor(
                    loan["unused_commitment_fee_bps_annual"]
                ),
                "minimum_contracted_capacity_kw": 1000,
                "minimum_take_or_pay_bps": loan["minimum_take_or_pay_bps"],
                "minimum_customer_credit_support_cents": loan[
                    "minimum_customer_credit_support_cents"
                ],
                "minimum_dscr_bps": loan["minimum_dscr_bps"],
            },
            "maximums": {
                "maximum_commitment_cents": loan["maximum_commitment_cents"],
                "advance_rate_bps": loan["advance_rate_bps"],
                "maximum_loan_to_cost_bps": loan["maximum_loan_to_cost_bps"],
                "maximum_loan_to_value_bps": 10_000,
                "maturity_month": loan["maturity_month"],
            },
            "required_conditions": ["site_control", "power_commitment"],
            "counter_terms": copy.deepcopy(loan),
        },
    }


# --------------------------------------------------------------------------
# Strata
# --------------------------------------------------------------------------


def _stratum_revenue_without_bankability(world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    minimum_take_or_pay = rng.choice((8000, 8500, 9000, 9500))
    minimum_credit = rng.choice((50_000, 60_000, 75_000, 90_000))
    terms = world["terms"]
    terms["loan"]["minimum_take_or_pay_bps"] = minimum_take_or_pay
    terms["loan"]["minimum_customer_credit_support_cents"] = minimum_credit
    policies = _default_policies(terms)
    # The customer accepts any weaker take-or-pay or credit support.
    trap = copy.deepcopy(terms)
    trap["service"]["take_or_pay_bps"] = minimum_take_or_pay - 1000
    trap["service"]["credit_support_cents"] = max(0, minimum_credit - 20_000)
    return {
        "policies": policies,
        "feasible": terms,
        "trap": trap,
        "knobs": {
            "lender_minimum_take_or_pay_bps": minimum_take_or_pay,
            "lender_minimum_credit_support_cents": minimum_credit,
        },
        "expected_failure": "loan_never_funds",
        "explanation": (
            "The customer accepts a weaker take-or-pay and credit-support "
            "package, but the lender's private minimums make that service "
            "agreement unbankable, so the loan never funds and construction "
            "spend exhausts the equity budget."
        ),
    }


def _stratum_delayed_revenue(world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    ready_month = rng.choice((4, 5))
    spread_bps = rng.choice((1200, 1800, 2400))
    facts = world["facts"]
    vector = [0] * HORIZON
    for month in range(ready_month, HORIZON + 1):
        vector[month - 1] = 1000
    facts["built_capacity_kw_by_month"] = list(vector)
    facts["energized_capacity_kw_by_month"] = list(vector)
    for condition in facts["condition_satisfaction"]:
        if condition["condition_id"] in {"power_ready", "construction_complete"}:
            condition["satisfied_month"] = ready_month
    terms = world["terms"]
    terms["power"]["energization_month"] = ready_month
    terms["epc"]["guaranteed_completion_month"] = ready_month
    terms["service"]["service_commencement_month"] = ready_month
    terms["service"]["ramp_schedule"] = [{"month": ready_month, "capacity_kw": 1000}]
    terms["land"]["site_control_expiry_month"] = ready_month + 1
    terms["land_amendment"]["site_control_expiry_month"] = ready_month + 2
    terms["loan"]["spread_bps"] = spread_bps
    terms["loan"]["minimum_dscr_bps"] = 2000
    policies = _default_policies(terms)
    # The lender accepts any maturity up to the horizon and any spread.
    trap = copy.deepcopy(terms)
    trap["loan"]["maturity_month"] = ready_month
    return {
        "policies": policies,
        "feasible": terms,
        "trap": trap,
        "knobs": {"physical_ready_month": ready_month, "lender_spread_bps": spread_bps},
        "expected_failure": "maturity_nonpayment",
        "explanation": (
            "Revenue only begins once construction and energization land in "
            "the ready month. A loan maturing in that same month looks like a "
            "shorter, cheaper tenor, but the project cannot repay principal "
            "before revenue has accumulated."
        ),
    }


def _stratum_restrictive_draws(world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    origination_fee_bps = rng.choice((150, 200, 250))
    trap_advance = rng.choice((2000, 2500, 3000))
    equity_budget = rng.choice((190_000, 200_000, 210_000))
    world["facts"]["developer_equity_budget_cents"] = equity_budget
    terms = world["terms"]
    terms["loan"]["origination_fee_bps"] = origination_fee_bps
    policies = _default_policies(terms)
    policies["loan"]["maximums"]["origination_fee_bps"] = origination_fee_bps
    policies["loan"]["minimums"]["origination_fee_bps"] = origination_fee_bps
    # A larger headline commitment is fine with the lender; draws are what bind.
    policies["loan"]["maximums"]["maximum_commitment_cents"] = 400_000
    trap = copy.deepcopy(terms)
    trap["loan"]["maximum_commitment_cents"] = 400_000
    trap["loan"]["advance_rate_bps"] = trap_advance
    trap["loan"]["maximum_loan_to_cost_bps"] = trap_advance
    return {
        "policies": policies,
        "feasible": terms,
        "trap": trap,
        "knobs": {
            "origination_fee_bps": origination_fee_bps,
            "trap_advance_rate_bps": trap_advance,
            "developer_equity_budget_cents": equity_budget,
        },
        "expected_failure": "funding_shortfall",
        "explanation": (
            "A larger headline commitment reads as generous, but the "
            "advance-rate and loan-to-cost draw conditions fund far less of "
            "each month's spend than the priced facility, so equity runs out "
            "before completion."
        ),
    }


def _stratum_covenant_cliff(world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    minimum_dscr = rng.choice((4000, 4100))
    trap_advance = rng.choice((7000, 7500, 8000))
    operating_cost = rng.choice((10, 12))
    world["facts"]["operating_cost_cents_per_kw_month"] = operating_cost
    terms = world["terms"]
    terms["loan"]["minimum_dscr_bps"] = minimum_dscr
    policies = _default_policies(terms)
    policies["loan"]["maximums"]["advance_rate_bps"] = 8000
    policies["loan"]["maximums"]["maximum_loan_to_cost_bps"] = 8000
    policies["loan"]["maximums"]["maximum_commitment_cents"] = 320_000
    trap = copy.deepcopy(terms)
    trap["loan"]["advance_rate_bps"] = trap_advance
    trap["loan"]["maximum_loan_to_cost_bps"] = trap_advance
    trap["loan"]["maximum_commitment_cents"] = 320_000
    return {
        "policies": policies,
        "feasible": terms,
        "trap": trap,
        "knobs": {
            "minimum_dscr_bps": minimum_dscr,
            "trap_advance_rate_bps": trap_advance,
            "operating_cost_cents_per_kw_month": operating_cost,
        },
        "expected_failure": "minimum_dscr_breach",
        "explanation": (
            "The priced facility clears the debt-service covenant by a thin "
            "margin. Pushing leverage up within the lender's stated window "
            "raises the maturity repayment enough to breach the minimum DSCR."
        ),
    }


def _stratum_liability_transfer(world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    premium_price = rng.choice((130, 140, 150))
    delay_damages = rng.choice((30_000, 40_000))
    facts = world["facts"]
    facts["built_capacity_kw_by_month"] = _months(0, 0, 0, 0, 1000, 1000)
    for condition in facts["condition_satisfaction"]:
        if condition["condition_id"] == "construction_complete":
            condition["satisfied_month"] = 5
    terms = world["terms"]
    policies = _default_policies(terms)
    policies["service"]["required_conditions"] = ["power_ready"]
    policies["service"]["maximums"]["monthly_capacity_charge_cents_per_kw"] = premium_price
    policies["service"]["maximums"]["delay_damages_cents_per_month"] = delay_damages
    policies["service"]["maximums"]["delay_damages_cap_cents"] = 2 * delay_damages
    # The customer prices the premium against a real availability commitment.
    policies["service"]["minimums"]["sla_credit_cap_bps"] = terms["service"][
        "sla_credit_cap_bps"
    ]
    trap = copy.deepcopy(terms)
    trap["service"]["monthly_capacity_charge_cents_per_kw"] = premium_price
    trap["service"]["conditions_precedent"] = ["power_ready"]
    trap["service"]["delay_damages_cents_per_month"] = delay_damages
    trap["service"]["delay_damages_cap_cents"] = 2 * delay_damages
    return {
        "policies": policies,
        "feasible": terms,
        "trap": trap,
        "knobs": {
            "premium_price_cents_per_kw": premium_price,
            "delay_damages_cents_per_month": delay_damages,
        },
        "expected_failure": "funding_shortfall",
        "explanation": (
            "Construction lands two months after energization. The customer "
            "pays a premium for service gated only on power readiness, but "
            "that schedule bills nothing while SLA credits and delay damages "
            "accrue, so the premium becomes a liability transfer."
        ),
    }


def _stratum_verbal_written_divergence(world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    trap_advance = rng.choice((2000, 2500, 3000))
    origination_fee_bps = rng.choice((100, 150))
    terms = world["terms"]
    terms["loan"]["origination_fee_bps"] = origination_fee_bps
    policies = _default_policies(terms)
    policies["loan"]["minimums"]["origination_fee_bps"] = origination_fee_bps
    policies["loan"]["maximums"]["origination_fee_bps"] = origination_fee_bps
    trap = copy.deepcopy(terms)
    trap["loan"]["advance_rate_bps"] = trap_advance
    trap["loan"]["maximum_loan_to_cost_bps"] = trap_advance
    policies["loan"]["counter_terms"] = copy.deepcopy(trap["loan"])
    policies["loan"]["counter_message"] = (
        "We can accept your proposed structure with the origination fee set "
        f"to {origination_fee_bps} bps; the advance rate and all other "
        "economics remain exactly as you proposed."
    )
    built_undisclosed = ("advance_rate_bps", "maximum_loan_to_cost_bps")
    return {
        "policies": policies,
        "feasible": terms,
        "trap": trap,
        "knobs": {
            "trap_advance_rate_bps": trap_advance,
            "origination_fee_bps": origination_fee_bps,
        },
        "undisclosed_counter_fields": {"loan": list(built_undisclosed)},
        "expected_failure": "funding_shortfall",
        "explanation": (
            "A fee-free loan offer is countered with a message that claims "
            "only the fee changed, while the written counter also cuts the "
            "advance rate and loan-to-cost limit. Adopting the counter as "
            "described leaves the project underfunded."
        ),
    }


STRATUM_BUILDERS = {
    "revenue_without_bankability": _stratum_revenue_without_bankability,
    "delayed_revenue": _stratum_delayed_revenue,
    "restrictive_draws": _stratum_restrictive_draws,
    "covenant_cliff": _stratum_covenant_cliff,
    "liability_transfer": _stratum_liability_transfer,
    "verbal_written_divergence": _stratum_verbal_written_divergence,
}


# --------------------------------------------------------------------------
# World assembly and verification
# --------------------------------------------------------------------------


def _assert_accepted(terms_by_key: Mapping[str, Any], policies: Mapping[str, Any], label: str) -> None:
    for key in SEQUENCE:
        parsed = TERM_PARSER_BY_TYPE[AGREEMENT_TYPE_BY_KEY[key]](terms_by_key[key])
        if not terms_acceptable(parsed, policies[key]):
            raise ValueError(f"{label}: {key} terms are not acceptable to the counterparty")


def _verify_world(world: dict[str, Any]) -> dict[str, Any]:
    facts = world["facts"]
    policies = world["policies"]
    feasible = evaluate_stack(facts, world["feasible"])
    trap = evaluate_stack(facts, world["trap"])
    outside = world["outside_option"]
    _assert_accepted(world["feasible"], policies, "feasible path")
    _assert_accepted(world["trap"], policies, "trap path")
    if not feasible["constraints_satisfied"] or not feasible["financing_succeeded"]:
        raise ValueError(f"feasible path fails admission: {feasible}")
    if feasible["developer_equity_npv_cents"] <= outside["developer_equity_npv_cents"]:
        raise ValueError("feasible path does not beat the walk-away outside option")
    if trap["constraints_satisfied"]:
        raise ValueError("trap path unexpectedly satisfies project constraints")
    expected = world["expected_failure"]
    observed = set(trap["default_reasons"])
    if expected == "loan_never_funds":
        if trap["loan_conditions_satisfied_month"] is not None:
            raise ValueError("bankability trap still funded the loan")
    elif expected not in observed:
        raise ValueError(f"trap failed for {sorted(observed)} rather than {expected}")
    return {
        "feasible_path": feasible,
        "attractive_path": trap,
        "walk_away": dict(outside),
        "expected_failure": expected,
    }


NEGOTIABLE_FLOOR_FIELDS = {
    "power": ("interconnection_cost_cents", "monthly_demand_charge_cents_per_kw"),
    "epc": ("contract_price_cents",),
    "loan": ("spread_bps", "origination_fee_bps", "unused_commitment_fee_bps_annual"),
}


def _drive_to_floor(
    terms: dict[str, dict[str, Any]], policies: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Move the scripted developer to the best terms its counterparties accept."""

    driven = copy.deepcopy(terms)
    for agreement_key, fields in NEGOTIABLE_FLOOR_FIELDS.items():
        minimums = policies[agreement_key]["minimums"]
        for field in fields:
            if field in minimums:
                driven[agreement_key][field] = minimums[field]
    if "payment_schedule" in driven["epc"]:
        price = driven["epc"]["contract_price_cents"]
        half = price // 2
        driven["epc"]["payment_schedule"] = [
            {"month": driven["epc"]["payment_schedule"][0]["month"], "amount_cents": half},
            {
                "month": driven["epc"]["payment_schedule"][-1]["month"],
                "amount_cents": price - half,
            },
        ]
    return driven


def build_world(stratum: str, variant: int, rng: random.Random) -> dict[str, Any]:
    base = _base_world(rng)
    world = {
        "facts": base["facts"],
        "terms": base["terms"],
    }
    built = STRATUM_BUILDERS[stratum](world, rng)
    built["feasible"] = _drive_to_floor(built["feasible"], built["policies"])
    undisclosed = built.get("undisclosed_counter_fields", {})
    outside_option = {
        "developer_equity_npv_cents": -base["sunk_cents"],
        "lender_npv_cents": 0,
        "customer_npv_cents": 0,
        "total_project_npv_cents": -base["sunk_cents"],
    }
    assembled = {
        "stratum": stratum,
        "variant": variant,
        "facts": world["facts"],
        "policies": built["policies"],
        "feasible": built["feasible"],
        "trap": built["trap"],
        "outside_option": outside_option,
        "knobs": {**base["knobs"], **built["knobs"]},
        "expected_failure": built["expected_failure"],
        "explanation": built["explanation"],
        "undisclosed_counter_fields": undisclosed,
    }
    assembled["mechanism"] = _verify_world(assembled)
    return assembled


def _case_document(world: Mapping[str, Any], index: int) -> dict[str, Any]:
    slug = f"{world['stratum']}_{world['variant']:03d}"
    scripted = {f"{key}_terms": copy.deepcopy(world["feasible"][key]) for key in SEQUENCE}
    scripted["land_amendment_fields"] = ["site_control_expiry_month"]
    baseline = world["mechanism"]["feasible_path"]
    payload = {
        "scope_version": SCOPE_VERSION,
        "scenario_id": f"datacenter_v2_world_{slug}",
        "project_facts": copy.deepcopy(world["facts"]),
        "negotiation": {"max_rounds": {key: MAX_ROUNDS for key in SEQUENCE}},
        "policies": copy.deepcopy(world["policies"]),
        "scripted_developer": scripted,
        "outside_option": dict(world["outside_option"]),
        "baseline": {
            "developer_equity_npv_cents": baseline["developer_equity_npv_cents"],
            "lender_npv_cents": baseline["lender_npv_cents"],
            "customer_npv_cents": baseline["customer_npv_cents"],
            "total_project_npv_cents": baseline["total_project_npv_cents"],
        },
    }
    if world.get("undisclosed_counter_fields"):
        payload["diagnostics"] = {
            "undisclosed_counter_fields": copy.deepcopy(
                world["undisclosed_counter_fields"]
            )
        }
    DataCenterStackPlugin(SCOPE_VERSION).validate_payload(payload)
    document = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"{FAMILY_ID}.{SPLIT}.{slug}",
        "family_id": FAMILY_ID,
        "family_version": SCOPE_CONFIG[SCOPE_VERSION]["family_version"],
        "split": SPLIT,
        "world_seed": MASTER_SEED + index,
        "seats": [dict(seat) for seat in SEATS],
        "episode": copy.deepcopy(EPISODE),
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "review_status": "generated",
        },
        "content_sha256": "0" * 64,
    }
    document["content_sha256"] = case_content_sha256(document)
    CaseManifest.from_dict(document)
    return document


def generate_pack(master_seed: int = MASTER_SEED) -> dict[str, Any]:
    """Return the 24 case documents and the sealed pack manifest."""

    rng = random.Random(master_seed)
    cases: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    index = 0
    for stratum in STRATA:
        seen: set[str] = set()
        for variant in range(1, VARIANTS_PER_STRATUM + 1):
            for _attempt in range(64):
                probe_rng = random.Random(rng.getrandbits(64))
                try:
                    world = build_world(stratum, variant, probe_rng)
                except ValueError:
                    # Jitter drew an infeasible or non-trapping combination.
                    continue
                signature = canonical_json_bytes(world["knobs"]).decode("utf-8")
                if signature not in seen:
                    break
            else:
                raise ValueError(f"could not draw a distinct {stratum} variant")
            seen.add(signature)
            document = _case_document(world, index)
            cases.append(document)
            entries.append(
                {
                    "case_id": document["case_id"],
                    "file": f"{document['case_id'].rsplit('.', 1)[1]}.json",
                    "content_sha256": document["content_sha256"],
                    "world_seed": document["world_seed"],
                    "stratum": stratum,
                    "variant": variant,
                    "knobs": world["knobs"],
                    "mechanism": world["mechanism"],
                    "explanation": world["explanation"],
                }
            )
            index += 1
    manifest = {
        "schema_version": "aeread.datacenter_world_pack/0.1",
        "pack_id": PACK_ID,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "master_seed": master_seed,
        "scope_version": SCOPE_VERSION,
        "strata": list(STRATA),
        "variants_per_stratum": VARIANTS_PER_STRATUM,
        "world_count": len(entries),
        "worlds": entries,
    }
    manifest["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    return {"cases": cases, "manifest": manifest}


def _dump(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def write_pack(output_root: Path | str = DEFAULT_OUTPUT_ROOT, *, master_seed: int = MASTER_SEED) -> dict[str, Any]:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    pack = generate_pack(master_seed)
    for document, entry in zip(pack["cases"], pack["manifest"]["worlds"]):
        (root / entry["file"]).write_text(_dump(document), encoding="utf-8")
    (root / "manifest.json").write_text(_dump(pack["manifest"]), encoding="utf-8")
    return pack["manifest"]


def check_pack(output_root: Path | str = DEFAULT_OUTPUT_ROOT, *, master_seed: int = MASTER_SEED) -> dict[str, Any]:
    """Confirm the on-disk pack equals a fresh generation from the pinned seed."""

    root = Path(output_root)
    pack = generate_pack(master_seed)
    drift: list[str] = []
    for document, entry in zip(pack["cases"], pack["manifest"]["worlds"]):
        path = root / entry["file"]
        if not path.is_file() or path.read_text(encoding="utf-8") != _dump(document):
            drift.append(entry["file"])
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != _dump(pack["manifest"]):
        drift.append("manifest.json")
    return {"pack_id": PACK_ID, "drift": drift, "reproducible": not drift}


def load_pack_manifest(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(output_root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    if manifest["artifact_sha256"] != hashlib.sha256(canonical_json_bytes(core)).hexdigest():
        raise ValueError("world pack manifest digest mismatch")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--master-seed", type=int, default=MASTER_SEED)
    parser.add_argument("--check", action="store_true", help="verify instead of write")
    arguments = parser.parse_args(argv)
    if arguments.check:
        result = check_pack(arguments.output, master_seed=arguments.master_seed)
        print(canonical_json_bytes(result).decode("utf-8"))
        return 0 if result["reproducible"] else 1
    manifest = write_pack(arguments.output, master_seed=arguments.master_seed)
    summary = {
        "pack_id": manifest["pack_id"],
        "world_count": manifest["world_count"],
        "artifact_sha256": manifest["artifact_sha256"],
        "strata": {
            stratum: sum(world["stratum"] == stratum for world in manifest["worlds"])
            for stratum in STRATA
        },
    }
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "MASTER_SEED",
    "PACK_ID",
    "STRATA",
    "build_world",
    "check_pack",
    "evaluate_stack",
    "generate_pack",
    "load_pack_manifest",
    "main",
    "write_pack",
]


if __name__ == "__main__":
    raise SystemExit(main())
