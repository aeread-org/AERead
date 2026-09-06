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
HORIZON = 36
CAPACITY_KW = 50_000
VARIANTS_PER_STRATUM = 4
MAX_ROUNDS = 3
# The utility will happily sell less capacity than the project needs. Because
# power is agreed two steps before the lease and executed agreements cannot be
# reopened, accepting its smaller, cheaper package is an irreversible planning
# error that only surfaces when the tenant asks for full capacity.
UNDERSIZED_CAPACITY_BPS = 8_000
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
    """One feasible 50 MW world calibrated to published 2026 market figures.

    Anchors, all per published industry benchmarks rather than invented:
    construction near $10M per MW, wholesale colocation near $200 per kW-month,
    construction debt at a floating benchmark plus 250-400bps at 60-70 percent
    loan-to-cost, EPC delay damages around 3 percent of contract value per
    month capped near 8 percent, and 15-year take-or-pay leases.
    """

    # $9.6M to $11.2M per MW of turnkey construction.
    epc_per_mw = rng.choice((960_000_000, 1_000_000_000, 1_120_000_000))
    epc_price = epc_per_mw * (CAPACITY_KW // 1000)
    # $185 to $215 per kW per month wholesale.
    capacity_price = rng.choice((18_500, 20_000, 21_500))
    # $10 to $14 per kW per month utility demand charge.
    demand_charge = rng.choice((1_000, 1_200, 1_400))
    # Land at $400k to $700k per acre over a 100 acre campus.
    land_price = rng.choice((4_000_000_000, 5_000_000_000, 7_000_000_000))
    # Sunk predevelopment cost if the developer walks: $8M to $15M.
    sunk_cents = rng.choice((800_000_000, 1_100_000_000, 1_500_000_000))
    energization_month = 22
    completion_month = 24
    commencement_month = 25

    def ramp(first_month: int) -> list[int]:
        return [0 if month < first_month else CAPACITY_KW for month in range(1, HORIZON + 1)]

    monthly_noi = CAPACITY_KW * (capacity_price - 4_000)
    facts = {
        "horizon_months": HORIZON,
        "construction_cost_cents_by_month": [0] * HORIZON,
        "development_cost_cents_by_month": [0] * HORIZON,
        "built_capacity_kw_by_month": ramp(completion_month),
        "energized_capacity_kw_by_month": ramp(energization_month),
        "customer_usage_kw_by_month": [CAPACITY_KW] * HORIZON,
        # SOFR near 4 percent, expressed in annual basis points.
        "base_rate_bps_by_month": [400] * HORIZON,
        # Wholesale power near $0.07 per kWh.
        "energy_cost_cents_per_kwh_by_month": [7] * HORIZON,
        "tax_and_insurance_cents_by_month": [0] * HORIZON,
        # Operating cost near $40 per kW per month.
        "operating_cost_cents_per_kw_month": 4_000,
        # About 70 percent utilisation of a kW over a 730 hour month.
        "energy_kwh_per_kw_month": 500,
        # The tenant values capacity above the rent it agrees to pay.
        "customer_value_cents_per_kw_month": capacity_price + 6_000,
        "developer_equity_budget_cents": 30_000_000_000,
        "appraised_value_cents": 130_000_000_000,
        # Stabilised asset value at a 7 percent capitalisation rate.
        "terminal_value_cents": (monthly_noi * 12 * 10_000) // 700,
        # Equity 12 percent, debt 7 percent, tenant 8 percent.
        "developer_discount_rate_bps_annual": 1_200,
        "lender_discount_rate_bps_annual": 700,
        "customer_discount_rate_bps_annual": 800,
        "base_rate_curve_id": "sofr_forward_2026_v1",
        "condition_satisfaction": [
            {"condition_id": "zoning_approval", "satisfied_month": 2},
            {"condition_id": "site_control", "satisfied_month": 2},
            {"condition_id": "power_commitment", "satisfied_month": 4},
            {"condition_id": "power_ready", "satisfied_month": energization_month},
            {"condition_id": "construction_complete", "satisfied_month": completion_month},
        ],
        "customer_termination_month": None,
    }
    quarter = epc_price // 4
    terms = {
        "land": {
            "site_control_start_month": 1,
            "closing_month": 2,
            "site_control_expiry_month": 30,
            "purchase_price_cents": land_price,
            "extension_option_months": 6,
            "extension_price_cents": land_price // 25,
            "permitted_use_capacity_kw": CAPACITY_KW,
            "conditions_precedent": ["zoning_approval"],
        },
        "power": {
            "contracted_capacity_kw": CAPACITY_KW,
            "energization_month": energization_month,
            # $20M of interconnection and network upgrades.
            "interconnection_cost_cents": 2_000_000_000,
            "monthly_demand_charge_cents_per_kw": demand_charge,
            "energy_charge_cents_per_kwh": 7,
            "delay_liquidated_damages_cents_per_month": 200_000_000,
            "delay_liquidated_damages_cap_cents": 1_000_000_000,
            # Queue deposit near $4,000 per MW.
            "developer_security_cents": 20_000_000,
            "initial_term_months": 180,
            "conditions_precedent": ["site_control", "power_commitment"],
        },
        "epc": {
            "notice_to_proceed_month": 3,
            "guaranteed_completion_month": completion_month,
            "guaranteed_capacity_kw": CAPACITY_KW,
            "contract_price_cents": epc_price,
            "payment_schedule": [
                {"month": 4, "amount_cents": quarter},
                {"month": 10, "amount_cents": quarter},
                {"month": 16, "amount_cents": quarter},
                {"month": 22, "amount_cents": epc_price - 3 * quarter},
            ],
            # About 3 percent of contract value per month, capped near 8 percent.
            "delay_liquidated_damages_cents_per_month": epc_price * 3 // 100,
            "delay_liquidated_damages_cap_cents": epc_price * 8 // 100,
            "cost_overrun_cap_cents": 0,
            "completion_guarantee_cents": epc_price // 10,
            "conditions_precedent": ["site_control"],
        },
        "service": {
            "committed_capacity_kw": CAPACITY_KW,
            "service_commencement_month": commencement_month,
            "ramp_schedule": [{"month": commencement_month, "capacity_kw": CAPACITY_KW}],
            "monthly_capacity_charge_cents_per_kw": capacity_price,
            "energy_pass_through_cents_per_kwh": 7,
            "take_or_pay_bps": 10_000,
            "initial_term_months": 180,
            "renewal_option_months": 60,
            # SLA credits capped at 5 percent of the monthly charge.
            "sla_credit_cap_bps": 500,
            "customer_termination_option_month": None,
            "customer_termination_fee_cents": 0,
            "delay_damages_cents_per_month": 50_000_000,
            "delay_damages_cap_cents": 200_000_000,
            # Six months of rent as credit support.
            "credit_support_cents": CAPACITY_KW * capacity_price * 6,
            "conditions_precedent": ["power_ready", "construction_complete"],
        },
        "loan": {
            "maximum_commitment_cents": 40_000_000_000,
            "advance_rate_bps": 6_500,
            "base_rate_curve_id": "sofr_forward_2026_v1",
            "spread_bps": 300,
            "unused_commitment_fee_bps_annual": 50,
            "origination_fee_bps": 100,
            "interest_reserve_cents": 0,
            "draw_start_month": 3,
            "minimum_contracted_capacity_kw": CAPACITY_KW,
            "minimum_take_or_pay_bps": 9_000,
            "minimum_customer_credit_support_cents": CAPACITY_KW * 18_500 * 6,
            "minimum_dscr_bps": 12_500,
            "maximum_loan_to_cost_bps": 6_500,
            "maximum_loan_to_value_bps": 6_000,
            "maturity_month": HORIZON,
            "extension_option_months": 12,
            "completion_guarantee_cents": 0,
            "conditions_precedent": ["site_control", "power_commitment"],
        },
    }
    terms["land_amendment"] = {
        **copy.deepcopy(terms["land"]),
        "site_control_expiry_month": terms["land"]["site_control_expiry_month"] + 3,
    }
    return {
        "facts": facts,
        "terms": terms,
        "sunk_cents": sunk_cents,
        "knobs": {
            "epc_price_cents": epc_price,
            "capacity_price_cents_per_kw": capacity_price,
            "demand_charge_cents_per_kw": demand_charge,
            "land_price_cents": land_price,
            "sunk_cents": sunk_cents,
        },
    }


def _round_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator // 2) // denominator


def _floor(value: int, *, width_bps: int = 1500) -> int:
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
                "permitted_use_capacity_kw": CAPACITY_KW,
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
                # The utility's own floor is below what the project needs, so a
                # developer that simply adopts its counter strands the lease.
                "contracted_capacity_kw": _round_div(
                    CAPACITY_KW * UNDERSIZED_CAPACITY_BPS, 10_000
                ),
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
                "energy_charge_cents_per_kwh": power["energy_charge_cents_per_kwh"],
                "developer_security_cents": power["developer_security_cents"],
                "delay_liquidated_damages_cents_per_month": power[
                    "delay_liquidated_damages_cents_per_month"
                ],
                "delay_liquidated_damages_cap_cents": power[
                    "delay_liquidated_damages_cap_cents"
                ],
            },
            "required_conditions": ["site_control", "power_commitment"],
            "counter_terms": {
                **copy.deepcopy(power),
                # Locally rational for the utility and visibly cheaper: a
                # smaller connection carries proportionally lower demand
                # charges. Jointly infeasible with the tenant's requirement.
                "contracted_capacity_kw": _round_div(
                    CAPACITY_KW * UNDERSIZED_CAPACITY_BPS, 10_000
                ),
            },
        },
        "epc": {
            "minimums": {
                "guaranteed_capacity_kw": CAPACITY_KW,
                # Contractors concede far less than utilities or lenders, and a
                # deeper discount would put the negotiated price below market.
                "contract_price_cents": _floor(
                    epc["contract_price_cents"], width_bps=800
                ),
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
                "committed_capacity_kw": CAPACITY_KW,
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
                "permitted_use_capacity_kw": CAPACITY_KW,
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
                "minimum_contracted_capacity_kw": CAPACITY_KW,
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
    minimum_take_or_pay = rng.choice((8500, 9000, 9500))
    monthly_rent = (
        CAPACITY_KW * world["terms"]["service"]["monthly_capacity_charge_cents_per_kw"]
    )
    minimum_credit = monthly_rent * rng.choice((5, 6, 7, 8))
    terms = world["terms"]
    terms["loan"]["minimum_take_or_pay_bps"] = minimum_take_or_pay
    terms["loan"]["minimum_customer_credit_support_cents"] = minimum_credit
    terms["service"]["credit_support_cents"] = minimum_credit
    policies = _default_policies(terms)
    # The customer accepts any weaker take-or-pay or credit support.
    trap = copy.deepcopy(terms)
    terms["service"]["credit_support_cents"] = minimum_credit
    trap["service"]["take_or_pay_bps"] = minimum_take_or_pay - 500
    trap["service"]["credit_support_cents"] = max(0, minimum_credit - monthly_rent)
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
    ready_month = rng.choice((26, 28, 30))
    spread_bps = rng.choice((300, 350, 400))
    facts = world["facts"]
    vector = [0] * HORIZON
    for month in range(ready_month, HORIZON + 1):
        vector[month - 1] = CAPACITY_KW
    facts["built_capacity_kw_by_month"] = list(vector)
    facts["energized_capacity_kw_by_month"] = list(vector)
    for condition in facts["condition_satisfaction"]:
        if condition["condition_id"] in {"power_ready", "construction_complete"}:
            condition["satisfied_month"] = ready_month
    terms = world["terms"]
    terms["power"]["energization_month"] = ready_month - 2
    terms["epc"]["guaranteed_completion_month"] = ready_month - 1
    terms["epc"]["payment_schedule"] = [
        {**step, "month": min(step["month"], ready_month - 2)}
        for step in terms["epc"]["payment_schedule"]
    ]
    terms["service"]["service_commencement_month"] = ready_month
    terms["service"]["ramp_schedule"] = [
        {"month": ready_month, "capacity_kw": CAPACITY_KW}
    ]
    terms["land"]["site_control_expiry_month"] = ready_month + 1
    terms["land_amendment"]["site_control_expiry_month"] = ready_month + 2
    terms["loan"]["spread_bps"] = spread_bps
    terms["loan"]["minimum_dscr_bps"] = 10_000
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
    origination_fee_bps = rng.choice((100, 125, 150))
    trap_advance = rng.choice((3000, 3500, 4000))
    equity_budget = rng.choice((28_000_000_000, 30_000_000_000, 32_000_000_000))
    world["facts"]["developer_equity_budget_cents"] = equity_budget
    terms = world["terms"]
    terms["loan"]["origination_fee_bps"] = origination_fee_bps
    policies = _default_policies(terms)
    policies["loan"]["maximums"]["origination_fee_bps"] = origination_fee_bps
    policies["loan"]["minimums"]["origination_fee_bps"] = origination_fee_bps
    # A larger headline commitment is fine with the lender; draws are what bind.
    policies["loan"]["maximums"]["maximum_commitment_cents"] = 60_000_000_000
    trap = copy.deepcopy(terms)
    trap["loan"]["maximum_commitment_cents"] = 60_000_000_000
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
    minimum_dscr = rng.choice((12_500, 13_000, 13_500))
    trap_advance = rng.choice((6800, 6900, 7000))
    operating_cost = rng.choice((4_000, 4_400))
    world["facts"]["operating_cost_cents_per_kw_month"] = operating_cost
    terms = world["terms"]
    terms["loan"]["minimum_dscr_bps"] = minimum_dscr
    # A phased tenant ramp: coverage is tightest while revenue is partial.
    commencement = terms["service"]["service_commencement_month"]
    terms["service"]["ramp_schedule"] = [
        {"month": commencement, "capacity_kw": CAPACITY_KW // 2},
        {"month": commencement + 4, "capacity_kw": CAPACITY_KW},
    ]
    policies = _default_policies(terms)
    # The tenant will pay a premium for a slower ramp, and the lender's
    # coverage covenant is what that trade actually spends.
    premium = terms["service"]["monthly_capacity_charge_cents_per_kw"] + 2_000
    policies["service"]["maximums"]["monthly_capacity_charge_cents_per_kw"] = premium
    trap = copy.deepcopy(terms)
    trap["service"]["monthly_capacity_charge_cents_per_kw"] = premium
    trap["service"]["ramp_schedule"] = [
        {"month": commencement, "capacity_kw": CAPACITY_KW // 3},
        {"month": commencement + 4, "capacity_kw": CAPACITY_KW},
    ]
    return {
        "policies": policies,
        "feasible": terms,
        "trap": trap,
        "knobs": {
            "minimum_dscr_bps": minimum_dscr,
            "premium_price_cents_per_kw": premium,
            "operating_cost_cents_per_kw_month": operating_cost,
        },
        "expected_failure": "minimum_dscr_breach",
        "explanation": (
            "The priced facility clears its coverage covenant by a thin margin "
            "during the tenant ramp. The tenant offers a higher rate in return "
            "for a slower ramp, which reads as more revenue but removes the "
            "early-period cash the covenant is measured on, and the loan "
            "breaches its minimum DSCR before the ramp completes. Leverage is "
            "not the lever here: loan-to-cost caps well below the point where "
            "stabilised coverage is at risk."
        ),
    }


def _stratum_liability_transfer(world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    premium_price = world["terms"]["service"][
        "monthly_capacity_charge_cents_per_kw"
    ] + rng.choice((4_000, 5_000, 6_000))
    delay_damages = rng.choice((40_000_000, 50_000_000))
    facts = world["facts"]
    late_month = 28
    facts["built_capacity_kw_by_month"] = [
        0 if month < late_month else CAPACITY_KW for month in range(1, HORIZON + 1)
    ]
    for condition in facts["condition_satisfaction"]:
        if condition["condition_id"] == "construction_complete":
            condition["satisfied_month"] = late_month
    # The prudent package starts billing when capacity actually exists, so no
    # month carries debt service against a contractual date it cannot serve.
    terms = world["terms"]
    terms["service"]["service_commencement_month"] = late_month
    terms["service"]["ramp_schedule"] = [
        {"month": late_month, "capacity_kw": CAPACITY_KW}
    ]
    terms["service"]["delay_damages_cents_per_month"] = delay_damages
    terms["service"]["delay_damages_cap_cents"] = 2 * delay_damages
    policies = _default_policies(terms)
    policies["service"]["required_conditions"] = ["power_ready"]
    policies["service"]["maximums"]["service_commencement_month"] = late_month
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
    # Billing nominally starts at energization, months before capacity exists.
    trap["service"]["service_commencement_month"] = terms["power"]["energization_month"]
    trap["service"]["ramp_schedule"] = [
        {"month": terms["power"]["energization_month"], "capacity_kw": CAPACITY_KW}
    ]
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
        "expected_failure": "minimum_dscr_breach",
        "explanation": (
            "Construction lands several months after energization. The customer "
            "pays a premium for service gated only on power readiness, so "
            "billing nominally starts before any capacity exists: the schedule "
            "earns nothing while SLA credits and delay damages accrue against "
            "it, and debt service is left uncovered. The premium is a liability "
            "transfer dressed as revenue."
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
