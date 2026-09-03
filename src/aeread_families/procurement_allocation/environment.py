"""Interactive supplier qualification and contribution-margin procurement case.

Natural-language buyer messages are retained in the trajectory, while the family
environment alone creates canonical claims, offers, sample records, and award state.
Listings and verbal claims are provisional; a final award requires an unexpired formal
offer, a verified sample, and an exact-variant match.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.measurement import (
    EstimandSpec,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)


FAMILY_ID = "procurement_allocation_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "procurement_allocation_environment"
SCORER_ID = "procurement_allocation_contribution_margin_scorer_v1"
PHASE_ID = "buyer_procurement_turn"
LEAF_ID = "procurement_contribution_margin_leaf"

ACTION_TYPES = frozenset(
    {
        "inquire",
        "request_quote",
        "counter_offer",
        "request_sample",
        "submit_award",
        "defer",
    }
)
COUNTER_FIELDS = frozenset(
    {
        "unit_price_usd",
        "moq",
        "payment_terms_days",
        "refund_window_days",
        "return_freight_payer",
    }
)
ACTION_FIELDS = {
    "inquire": frozenset({"action", "supplier_id", "fields", "message"}),
    "request_quote": frozenset({"action", "supplier_id", "message"}),
    "request_sample": frozenset({"action", "supplier_id", "message"}),
    "counter_offer": frozenset(
        {"action", "supplier_id", "offer_id", "proposal", "message"}
    ),
    "submit_award": frozenset({"action", "award_lines"}),
    "defer": frozenset({"action", "reason"}),
}
WIRE_ACTION_FIELDS = frozenset().union(*ACTION_FIELDS.values())


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _finite_number(value: Any, path: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be a finite number")
    if minimum is not None and result < minimum:
        raise ValueError(f"{path} must be at least {minimum}")
    return result


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _exact_fields(value: Any, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    actual = set(value)
    if actual != fields:
        raise ValueError(
            f"{path} fields differ: missing={sorted(fields - actual)}, "
            f"unexpected={sorted(actual - fields)}"
        )
    return value


def _supplier_by_id(family_case: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(supplier["supplier_id"]): _plain(supplier)
        for supplier in family_case["suppliers"]
    }


def _validate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _plain(payload)
    if set(data) != {"objective", "interaction", "policy", "suppliers"}:
        raise ValueError(
            "payload must contain exactly objective, interaction, policy, and suppliers"
        )
    objective = data["objective"]
    interaction = data["interaction"]
    policy = data["policy"]
    suppliers = data["suppliers"]
    if not all(isinstance(item, dict) for item in (objective, interaction, policy)):
        raise ValueError("objective, interaction, and policy must be objects")
    if not isinstance(suppliers, list) or not suppliers:
        raise ValueError("suppliers must be a non-empty array")

    target = _positive_int(objective.get("target_kits"), "objective.target_kits")
    minimum_service = _positive_int(
        objective.get("minimum_service_kits"), "objective.minimum_service_kits"
    )
    if minimum_service > target:
        raise ValueError("minimum_service_kits cannot exceed target_kits")
    for field in (
        "revenue_per_completed_kit_usd",
        "shortfall_penalty_per_kit_usd",
        "cash_budget_usd",
        "annual_financing_rate",
    ):
        _finite_number(objective.get(field), f"objective.{field}", minimum=0.0)
    _finite_number(objective.get("defer_value_usd"), "objective.defer_value_usd")
    for field in (
        "deadline_days",
        "defect_detection_days",
        "working_capital_horizon_days",
    ):
        _positive_int(objective.get(field), f"objective.{field}")
    bom = objective.get("bom")
    if not isinstance(bom, dict) or not bom:
        raise ValueError("objective.bom must be a non-empty object")
    for component, units in bom.items():
        _text(component, "objective.bom key")
        _positive_int(units, f"objective.bom.{component}")

    if interaction.get("max_actions") != 10:
        raise ValueError("interaction.max_actions must equal the case's 10-action budget")
    for field in ("inquiry_days", "quote_days", "counter_days"):
        _positive_int(interaction.get(field), f"interaction.{field}")
    for field in ("inquiry_cost_usd", "quote_cost_usd", "counter_cost_usd"):
        _finite_number(interaction.get(field), f"interaction.{field}", minimum=0.0)

    required_variants = policy.get("required_variant_by_component")
    inquiry_fields = policy.get("inquiry_fields")
    award_requires = policy.get("award_requires")
    if not isinstance(required_variants, dict) or set(required_variants) != set(bom):
        raise ValueError("policy required variants must match objective.bom")
    if not isinstance(inquiry_fields, list) or not inquiry_fields:
        raise ValueError("policy.inquiry_fields must be a non-empty array")
    if not isinstance(award_requires, list) or set(award_requires) != {
        "unexpired_formal_offer",
        "verified_sample",
        "exact_variant",
    }:
        raise ValueError("policy.award_requires does not match the v1 award contract")

    seen: set[str] = set()
    components_seen: set[str] = set()
    for index, supplier in enumerate(suppliers):
        path = f"suppliers[{index}]"
        if not isinstance(supplier, dict):
            raise ValueError(f"{path} must be an object")
        supplier_id = _text(supplier.get("supplier_id"), f"{path}.supplier_id")
        if supplier_id in seen:
            raise ValueError(f"duplicate supplier_id: {supplier_id}")
        seen.add(supplier_id)
        component = _text(supplier.get("component"), f"{path}.component")
        if component not in bom:
            raise ValueError(f"{path}.component is absent from objective.bom")
        components_seen.add(component)
        listing = supplier.get("listing")
        terms = supplier.get("private_terms")
        if not isinstance(listing, dict) or not isinstance(terms, dict):
            raise ValueError(f"{path} listing and private_terms must be objects")
        if listing.get("evidence_status") != "marketplace_listing_unverified":
            raise ValueError(f"{path}.listing must remain explicitly unverified")
        _text(terms.get("variant_id"), f"{path}.private_terms.variant_id")
        for field in (
            "base_unit_price_usd",
            "shipping_per_unit_usd",
            "duty_rate",
            "on_time_probability",
        ):
            value = _finite_number(terms.get(field), f"{path}.private_terms.{field}", minimum=0.0)
            if field == "on_time_probability" and value > 1.0:
                raise ValueError(f"{path}.private_terms.on_time_probability must be <= 1")
        for field in (
            "capacity",
            "moq",
            "order_step",
            "lead_time_days",
            "payment_terms_days",
            "offer_valid_days",
        ):
            _positive_int(terms.get(field), f"{path}.private_terms.{field}")
        if terms["moq"] > terms["capacity"]:
            raise ValueError(f"{path} MOQ exceeds capacity")
        quality = terms.get("quality")
        returns = terms.get("return_policy")
        negotiation = terms.get("negotiation")
        if not all(isinstance(item, dict) for item in (quality, returns, negotiation)):
            raise ValueError(f"{path} quality, return policy, and negotiation are required")
        yield_rate = _finite_number(
            quality.get("verified_yield_rate"),
            f"{path}.private_terms.quality.verified_yield_rate",
            minimum=0.0,
        )
        if yield_rate > 1.0:
            raise ValueError(f"{path} verified yield must be <= 1")
        for field in ("sample_size", "sample_lead_time_days"):
            _positive_int(quality.get(field), f"{path}.private_terms.quality.{field}")
        defects = quality.get("observed_defects")
        if isinstance(defects, bool) or not isinstance(defects, int) or defects < 0:
            raise ValueError(f"{path} observed_defects must be non-negative")
        _finite_number(
            quality.get("sample_cost_usd"),
            f"{path}.private_terms.quality.sample_cost_usd",
            minimum=0.0,
        )
        for field in (
            "claim_acceptance_probability",
            "restocking_fee_rate",
        ):
            value = _finite_number(
                returns.get(field), f"{path}.private_terms.return_policy.{field}", minimum=0.0
            )
            if value > 1.0:
                raise ValueError(f"{path} return probability/rate must be <= 1")
        for field in ("refund_window_days", "refund_delay_days"):
            _positive_int(returns.get(field), f"{path}.private_terms.return_policy.{field}")
        if returns.get("return_freight_payer") not in {"buyer", "supplier"}:
            raise ValueError(f"{path} return_freight_payer is invalid")
        _finite_number(
            returns.get("return_freight_per_unit_usd"),
            f"{path}.private_terms.return_policy.return_freight_per_unit_usd",
            minimum=0.0,
        )
        _finite_number(
            negotiation.get("floor_unit_price_usd"),
            f"{path}.private_terms.negotiation.floor_unit_price_usd",
            minimum=0.0,
        )
        for field in (
            "minimum_moq",
            "maximum_payment_terms_days",
            "maximum_refund_window_days",
        ):
            _positive_int(negotiation.get(field), f"{path}.private_terms.negotiation.{field}")
        if not isinstance(negotiation.get("supplier_paid_return_freight_available"), bool):
            raise ValueError(f"{path} supplier freight flexibility must be boolean")
    if components_seen != set(bom):
        raise ValueError("every BOM component requires at least one supplier")
    return data


def _base_offer(supplier: Mapping[str, Any], *, version: int, issued_day: int) -> dict[str, Any]:
    terms = supplier["private_terms"]
    return {
        "offer_id": f"offer_{supplier['supplier_id']}_v{version}",
        "version": version,
        "supplier_id": supplier["supplier_id"],
        "component": supplier["component"],
        "evidence_status": "formal_offer",
        "issued_day": issued_day,
        "expires_day": issued_day + terms["offer_valid_days"],
        "variant_id": terms["variant_id"],
        "unit_price_usd": terms["base_unit_price_usd"],
        "shipping_per_unit_usd": terms["shipping_per_unit_usd"],
        "duty_rate": terms["duty_rate"],
        "capacity": terms["capacity"],
        "moq": terms["moq"],
        "order_step": terms["order_step"],
        "lead_time_days": terms["lead_time_days"],
        "on_time_probability": terms["on_time_probability"],
        "payment_terms_days": terms["payment_terms_days"],
        "return_policy": _plain(terms["return_policy"]),
        "negotiated": False,
    }


def _best_offer(supplier: Mapping[str, Any], *, version: int, issued_day: int) -> dict[str, Any]:
    offer = _base_offer(supplier, version=version, issued_day=issued_day)
    negotiation = supplier["private_terms"]["negotiation"]
    offer["unit_price_usd"] = negotiation["floor_unit_price_usd"]
    offer["moq"] = negotiation["minimum_moq"]
    offer["payment_terms_days"] = negotiation["maximum_payment_terms_days"]
    offer["return_policy"]["refund_window_days"] = negotiation[
        "maximum_refund_window_days"
    ]
    if negotiation["supplier_paid_return_freight_available"]:
        offer["return_policy"]["return_freight_payer"] = "supplier"
        offer["return_policy"]["return_freight_per_unit_usd"] = 0.0
    offer["negotiated"] = True
    return offer


def _counter_is_accepted(
    supplier: Mapping[str, Any], offer: Mapping[str, Any], proposal: Mapping[str, Any]
) -> bool:
    limits = supplier["private_terms"]["negotiation"]
    if "unit_price_usd" in proposal and not (
        limits["floor_unit_price_usd"] <= proposal["unit_price_usd"] <= offer["unit_price_usd"]
    ):
        return False
    if "moq" in proposal and not (
        limits["minimum_moq"] <= proposal["moq"] <= offer["moq"]
    ):
        return False
    if "payment_terms_days" in proposal and not (
        offer["payment_terms_days"]
        <= proposal["payment_terms_days"]
        <= limits["maximum_payment_terms_days"]
    ):
        return False
    current_window = offer["return_policy"]["refund_window_days"]
    if "refund_window_days" in proposal and not (
        current_window
        <= proposal["refund_window_days"]
        <= limits["maximum_refund_window_days"]
    ):
        return False
    if proposal.get("return_freight_payer") == "supplier" and not limits[
        "supplier_paid_return_freight_available"
    ]:
        return False
    return True


def _apply_counter(
    offer: Mapping[str, Any], proposal: Mapping[str, Any], *, version: int, issued_day: int
) -> dict[str, Any]:
    updated = _plain(offer)
    updated["offer_id"] = f"offer_{offer['supplier_id']}_v{version}"
    updated["version"] = version
    updated["issued_day"] = issued_day
    updated["expires_day"] = issued_day + (offer["expires_day"] - offer["issued_day"])
    for field in ("unit_price_usd", "moq", "payment_terms_days"):
        if field in proposal:
            updated[field] = proposal[field]
    if "refund_window_days" in proposal:
        updated["return_policy"]["refund_window_days"] = proposal["refund_window_days"]
    if "return_freight_payer" in proposal:
        updated["return_policy"]["return_freight_payer"] = proposal[
            "return_freight_payer"
        ]
        if proposal["return_freight_payer"] == "supplier":
            updated["return_policy"]["return_freight_per_unit_usd"] = 0.0
    updated["negotiated"] = True
    return updated


def _quantity_values(offer: Mapping[str, Any]) -> tuple[int, ...]:
    values = list(range(offer["moq"], offer["capacity"] + 1, offer["order_step"]))
    if values and values[-1] != offer["capacity"]:
        values.append(offer["capacity"])
    return tuple(values)


def evaluate_award(
    family_case: Mapping[str, Any],
    *,
    award_lines: Sequence[Mapping[str, Any]],
    offers: Mapping[str, Mapping[str, Any]],
    quality_evidence: Mapping[str, Mapping[str, Any]],
    elapsed_days: int,
    information_cost_usd: float,
) -> dict[str, Any]:
    """Evaluate a terminal award in buyer contribution-margin units."""
    objective = family_case["objective"]
    suppliers = _supplier_by_id(family_case)
    required_variants = family_case["policy"]["required_variant_by_component"]
    violations: list[str] = []
    seen_suppliers: set[str] = set()
    expected_units = {component: 0.0 for component in objective["bom"]}
    purchase_cost = 0.0
    shipping_cost = 0.0
    duty_cost = 0.0
    working_capital_cost = 0.0
    expected_recovery = 0.0
    return_freight_cost = 0.0
    refund_financing_cost = 0.0

    for index, line in enumerate(award_lines):
        offer_id = line["offer_id"]
        quantity = line["quantity"]
        offer = offers.get(offer_id)
        if offer is None:
            violations.append(f"award_lines[{index}].unknown_offer")
            continue
        supplier_id = offer["supplier_id"]
        if supplier_id in seen_suppliers:
            violations.append(f"award_lines[{index}].duplicate_supplier")
            continue
        seen_suppliers.add(supplier_id)
        supplier = suppliers[supplier_id]
        component = offer["component"]
        if elapsed_days > offer["expires_day"]:
            violations.append(f"{supplier_id}.expired_offer")
        if offer["variant_id"] != required_variants[component]:
            violations.append(f"{supplier_id}.wrong_variant")
        quality = quality_evidence.get(supplier_id)
        if not isinstance(quality, Mapping) or quality.get("evidence_status") != "verified_sample":
            violations.append(f"{supplier_id}.sample_not_verified")
            continue
        if quality.get("variant_id") != offer["variant_id"]:
            violations.append(f"{supplier_id}.sample_variant_mismatch")
            continue
        if quantity < offer["moq"]:
            violations.append(f"{supplier_id}.below_moq")
        if quantity > offer["capacity"]:
            violations.append(f"{supplier_id}.over_capacity")
        if (quantity - offer["moq"]) % offer["order_step"] != 0 and quantity != offer["capacity"]:
            violations.append(f"{supplier_id}.invalid_order_step")

        unit_price = float(offer["unit_price_usd"])
        line_purchase = quantity * unit_price
        line_shipping = quantity * float(offer["shipping_per_unit_usd"])
        line_duty = (line_purchase + line_shipping) * float(offer["duty_rate"])
        purchase_cost += line_purchase
        shipping_cost += line_shipping
        duty_cost += line_duty

        horizon = objective["working_capital_horizon_days"]
        early_days = max(0, horizon - offer["payment_terms_days"])
        working_capital_cost += (
            line_purchase * objective["annual_financing_rate"] * early_days / 365.0
        )

        yield_rate = float(quality["verified_yield_rate"])
        arrives_in_time = elapsed_days + offer["lead_time_days"] <= objective["deadline_days"]
        on_time_probability = float(offer["on_time_probability"]) if arrives_in_time else 0.0
        expected_units[component] += quantity * yield_rate * on_time_probability

        defects = quantity * (1.0 - yield_rate)
        returns = offer["return_policy"]
        claims_timely = returns["refund_window_days"] >= objective["defect_detection_days"]
        accepted_claim_units = (
            defects * returns["claim_acceptance_probability"] if claims_timely else 0.0
        )
        gross_recovery = (
            accepted_claim_units
            * unit_price
            * (1.0 - returns["restocking_fee_rate"])
        )
        expected_recovery += gross_recovery
        if returns["return_freight_payer"] == "buyer":
            return_freight_cost += (
                accepted_claim_units * returns["return_freight_per_unit_usd"]
            )
        refund_financing_cost += (
            gross_recovery
            * objective["annual_financing_rate"]
            * returns["refund_delay_days"]
            / 365.0
        )

    completed_kits = min(
        math.floor(expected_units[component] / units_per_kit + 1e-12)
        for component, units_per_kit in objective["bom"].items()
    )
    completed_kits = min(completed_kits, objective["target_kits"])
    cash_spend = purchase_cost + shipping_cost + duty_cost + information_cost_usd
    if cash_spend > objective["cash_budget_usd"] + 1e-9:
        violations.append("cash_budget_exceeded")
    if completed_kits < objective["minimum_service_kits"]:
        violations.append("minimum_service_not_met")

    shortage = objective["target_kits"] - completed_kits
    revenue = completed_kits * objective["revenue_per_completed_kit_usd"]
    shortfall_penalty = shortage * objective["shortfall_penalty_per_kit_usd"]
    total_cost = (
        purchase_cost
        + shipping_cost
        + duty_cost
        + working_capital_cost
        + information_cost_usd
        + return_freight_cost
        + refund_financing_cost
        - expected_recovery
    )
    raw_margin = revenue - total_cost - shortfall_penalty
    feasible = not violations
    # Information already purchased is sunk even when an attempted award is
    # rejected.  Otherwise a buyer could erase research costs by submitting an
    # intentionally infeasible order instead of explicitly deferring.
    realized_margin = (
        raw_margin
        if feasible
        else objective["defer_value_usd"] - information_cost_usd
    )
    return {
        "feasible": feasible,
        "contribution_margin_usd": round(realized_margin, 8),
        "raw_contribution_margin_usd": round(raw_margin, 8),
        "completed_kits": completed_kits,
        "expected_good_on_time_units": {
            key: round(value, 8) for key, value in sorted(expected_units.items())
        },
        "cash_spend_usd": round(cash_spend, 8),
        "purchase_cost_usd": round(purchase_cost, 8),
        "shipping_cost_usd": round(shipping_cost, 8),
        "duty_cost_usd": round(duty_cost, 8),
        "working_capital_cost_usd": round(working_capital_cost, 8),
        "information_cost_usd": round(information_cost_usd, 8),
        "expected_recovery_usd": round(expected_recovery, 8),
        "return_freight_cost_usd": round(return_freight_cost, 8),
        "refund_financing_cost_usd": round(refund_financing_cost, 8),
        "shortfall_penalty_usd": round(shortfall_penalty, 8),
        "total_cost_usd": round(total_cost, 8),
        "violations": violations,
    }


@dataclass(frozen=True, slots=True)
class UpperBoundResult:
    contribution_margin_usd: float
    award_plan: tuple[Mapping[str, Any], ...]
    completed_kits: int
    cash_spend_usd: float
    actions_required: int
    elapsed_days: int


def solve_full_information_upper_bound(family_case: Mapping[str, Any]) -> UpperBoundResult:
    """Enumerate the small curated world under full information.

    The bound charges every quote, sample, and counter action needed to make its
    award reachable. It relaxes only the buyer's information problem: the solver
    knows which supplier terms to acquire and which admissible counter to make.
    """
    objective = family_case["objective"]
    interaction = family_case["interaction"]
    supplier_options: list[tuple[dict[str, Any] | None, ...]] = []
    suppliers = list(family_case["suppliers"])
    for supplier in suppliers:
        options: list[dict[str, Any] | None] = [None]
        for mode, offer in (
            ("base", _base_offer(supplier, version=1, issued_day=0)),
            ("negotiated", _best_offer(supplier, version=2, issued_day=0)),
        ):
            for quantity in _quantity_values(offer):
                options.append(
                    {
                        "supplier_id": supplier["supplier_id"],
                        "component": supplier["component"],
                        "mode": mode,
                        "offer": offer,
                        "quantity": quantity,
                    }
                )
        supplier_options.append(tuple(options))

    best_value = float(objective["defer_value_usd"])
    best_plan: tuple[Mapping[str, Any], ...] = ()
    best_completed = 0
    best_cash = 0.0
    best_actions = 1
    best_elapsed = 0
    for combination in itertools.product(*supplier_options):
        selected = tuple(item for item in combination if item is not None)
        if not selected:
            continue
        actions_required = 1 + sum(
            2 + (1 if item["mode"] == "negotiated" else 0) for item in selected
        )
        if actions_required > interaction["max_actions"]:
            continue
        elapsed_days = sum(
            interaction["quote_days"]
            + suppliers[index]["private_terms"]["quality"]["sample_lead_time_days"]
            + (interaction["counter_days"] if item["mode"] == "negotiated" else 0)
            for index, item in enumerate(combination)
            if item is not None
        )
        information_cost = sum(
            interaction["quote_cost_usd"]
            + suppliers[index]["private_terms"]["quality"]["sample_cost_usd"]
            + (interaction["counter_cost_usd"] if item["mode"] == "negotiated" else 0.0)
            for index, item in enumerate(combination)
            if item is not None
        )
        offers = {item["offer"]["offer_id"]: item["offer"] for item in selected}
        qualities = {
            item["supplier_id"]: {
                **_plain(suppliers[index]["private_terms"]["quality"]),
                "supplier_id": item["supplier_id"],
                "variant_id": suppliers[index]["private_terms"]["variant_id"],
                "evidence_status": "verified_sample",
            }
            for index, item in enumerate(combination)
            if item is not None
        }
        lines = [
            {"offer_id": item["offer"]["offer_id"], "quantity": item["quantity"]}
            for item in selected
        ]
        result = evaluate_award(
            family_case,
            award_lines=lines,
            offers=offers,
            quality_evidence=qualities,
            elapsed_days=elapsed_days,
            information_cost_usd=information_cost,
        )
        if not result["feasible"]:
            continue
        candidate_key = (
            result["contribution_margin_usd"],
            -actions_required,
            -result["cash_spend_usd"],
            tuple((item["supplier_id"], item["mode"], item["quantity"]) for item in selected),
        )
        best_key = (
            best_value,
            -best_actions,
            -best_cash,
            tuple((item["supplier_id"], item["mode"], item["quantity"]) for item in best_plan),
        )
        if candidate_key > best_key:
            best_value = result["contribution_margin_usd"]
            best_plan = tuple(
                {
                    "supplier_id": item["supplier_id"],
                    "component": item["component"],
                    "mode": item["mode"],
                    "quantity": item["quantity"],
                }
                for item in selected
            )
            best_completed = result["completed_kits"]
            best_cash = result["cash_spend_usd"]
            best_actions = actions_required
            best_elapsed = elapsed_days
    return UpperBoundResult(
        contribution_margin_usd=round(best_value, 8),
        award_plan=best_plan,
        completed_kits=best_completed,
        cash_spend_usd=round(best_cash, 8),
        actions_required=best_actions,
        elapsed_days=best_elapsed,
    )


def procurement_allocation_measurement_leaf(
    family_case: Mapping[str, Any],
) -> MeasurementLeafSpec:
    source_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    reference_digest = hashlib.sha256(canonical_json_bytes(family_case)).hexdigest()
    domain = ValidityDomainSpec(
        domain_id="procurement_allocation_terminal_domain",
        domain_version="1.0.0",
        schema_ref="procurement_allocation_v1/outcome/1",
        predicate=ImplementationRef(SCORER_ID, "1.0.0", source_digest),
    )
    estimand = EstimandSpec(
        estimand_id="buyer_contribution_margin",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="usd",
        validity_domain=domain,
    )
    return MeasurementLeafSpec(
        leaf_id=LEAF_ID,
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="procurement_full_information_upper_bound_v1",
                reference_version="1.0.0",
                reference_kind="objective_upper_bound",
                input_scope="terminal_state",
                units="usd",
                source_sha256=reference_digest,
                implementation=ImplementationRef(
                    "procurement_full_information_upper_bound_v1",
                    "1.0.0",
                    source_digest,
                ),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id="buyer_contribution_margin",
                objective_version="1.0.0",
                direction="maximize",
                units="usd",
                feasible_set=(
                    "unexpired formal offers with verified samples, exact variants, "
                    "MOQ/capacity/order-step compliance, cash budget, and minimum service"
                ),
                information_set=(
                    "buyer-visible listings and acquired claims/offers/samples; reference "
                    "relaxes supplier-term information while charging required actions"
                ),
                horizon="one sourcing episode through the declared delivery deadline",
                environment_condition="pinned synthetic supplier response policies",
                opponent_condition="deterministic supplier acceptance limits in the case",
                validity_domain=domain,
            ),
        ),
        scorer=ImplementationRef(SCORER_ID, "1.0.0", source_digest),
    )


@dataclass(frozen=True, slots=True)
class ProcurementAllocationMeasurementScorer:
    family_case: Mapping[str, Any]

    def __call__(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        leaf = procurement_allocation_measurement_leaf(self.family_case)
        reasons: list[str] = []
        if not isinstance(outcome, Mapping):
            reasons.append("procurement allocation outcome must be an object")
            outcome = {}
        value = outcome.get("contribution_margin_usd")
        upper = outcome.get("upper_bound_usd")
        regret = outcome.get("regret_to_upper_bound_usd")
        for field, item in (
            ("contribution_margin_usd", value),
            ("upper_bound_usd", upper),
            ("regret_to_upper_bound_usd", regret),
        ):
            if (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
            ):
                reasons.append(f"{field} must be finite")
        if not reasons and float(value) > float(upper) + 1e-7:
            reasons.append("realized contribution margin exceeds the declared upper bound")
        if not reasons and abs(float(regret) - max(0.0, float(upper) - float(value))) > 1e-6:
            reasons.append("regret does not match upper bound minus realized margin")
        if reasons:
            return ScoreEnvelope(
                status="invalid_measurement",
                leaf=leaf,
                primary=None,
                metrics={},
                reference_values={},
                validity=ValidityReport("invalid", tuple(reasons)),
                evidence_refs=evidence_refs,
            )
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(float(value), "usd"),
            metrics={
                "regret_to_upper_bound": MetricValue(float(regret), "usd"),
                "completed_kits": MetricValue(float(outcome["completed_kits"]), "kits"),
                "cash_spend": MetricValue(float(outcome["cash_spend_usd"]), "usd"),
                "information_cost": MetricValue(
                    float(outcome["information_cost_usd"]), "usd"
                ),
                "elapsed_days": MetricValue(float(outcome["elapsed_days"]), "days"),
                "feasible_award": MetricValue(
                    1.0 if outcome["feasible"] else 0.0, "indicator"
                ),
            },
            reference_values={"full_information_upper_bound": MetricValue(float(upper), "usd")},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )


def family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "interactive_supplier_qualification_and_award",
                "phase_specs": [PHASE_ID],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {"buyer": {"testable": True, "scripted_policies": ["scripted"]}},
            "measurement": {
                "primary_estimand": "buyer_contribution_margin",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "optimum_lower_bound": "defer_value_usd",
                "optimum_upper_bound": "full_information_enumeration",
                "optimum_upper_bound_kind": "certified",
                "bound_status": "case_computed",
                "outcome_support": "real_valued_usd",
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "oracle_id": "procurement_full_information_upper_bound_v1",
            },
        }
    )


def register_plugin(
    registry: PluginRegistry, *, plugin: "ProcurementAllocationPlugin | None" = None
) -> "ProcurementAllocationPlugin":
    resolved = plugin or ProcurementAllocationPlugin()
    registry.register_trusted(family_manifest(), resolved)
    return resolved


class ProcurementAllocationPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _validate_payload(payload)
        upper = solve_full_information_upper_bound(data)
        if upper.contribution_margin_usd <= data["objective"]["defer_value_usd"]:
            raise ValueError("development case requires a positive ordering upper bound")
        return data

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        del family_case, run
        return {
            "done": False,
            "termination_reason": None,
            "failure_code": None,
            "actions_used": 0,
            "elapsed_days": 0,
            "information_cost_usd": 0.0,
            "conversation": [],
            "claims": {},
            "offers": {},
            "latest_offer_by_supplier": {},
            "offer_versions": {},
            "quality_evidence": {},
            "award_lines": [],
            "defer_reason": None,
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        max_actions = int(family_case["interaction"]["max_actions"])
        return (
            PhaseSpec(
                phase_id=PHASE_ID,
                actor_selector="buyer_only",
                mode="single",
                observation_schema_by_role={"buyer": "procurement_allocation_observation_v1"},
                action_schema_by_role={"buyer": "procurement_allocation_action_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="family_defined",
                next_phases=(PHASE_ID,),
            ),
        )

    def eligible_actors(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any], phase: PhaseSpec
    ) -> tuple[str, ...]:
        del family_case, state, phase
        return ("buyer",)

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        del seat, phase
        return {
            "objective": _plain(family_case["objective"]),
            "policy": _plain(family_case["policy"]),
            "supplier_listings": [
                {
                    "supplier_id": supplier["supplier_id"],
                    "component": supplier["component"],
                    "listing": _plain(supplier["listing"]),
                }
                for supplier in family_case["suppliers"]
            ],
            "actions_left": family_case["interaction"]["max_actions"] - state["actions_used"],
            "elapsed_days": state["elapsed_days"],
            "information_cost_usd": state["information_cost_usd"],
            "conversation": _plain(state["conversation"]),
            "verbal_claims": _plain(state["claims"]),
            "formal_offers": _plain(state["offers"]),
            "verified_samples": _plain(state["quality_evidence"]),
        }

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del state, seat, phase
        if isinstance(response, CanonicalResponse):
            raw = response.action if isinstance(response.action, Mapping) else None
            if raw is None:
                try:
                    raw = json.loads(response.text)
                except (TypeError, json.JSONDecodeError):
                    return ParseResult.failure("malformed_json")
        elif isinstance(response, str):
            try:
                raw = json.loads(response)
            except (TypeError, json.JSONDecodeError):
                return ParseResult.failure("malformed_json")
        elif isinstance(response, Mapping):
            raw = _plain(response)
        else:
            return ParseResult.failure("noncanonical_response")
        if not isinstance(raw, dict) or raw.get("action") not in ACTION_TYPES:
            return ParseResult.failure("unknown_procurement_action")
        action_type = raw["action"]
        expected_fields = ACTION_FIELDS[action_type]
        unknown_fields = set(raw) - WIRE_ACTION_FIELDS
        if unknown_fields:
            return ParseResult.failure("malformed_procurement_action")
        # Provider-native structured output uses one strict superset object.
        # Project it onto the selected action before exact validation. Known
        # fields belonging to another action never acquire semantic authority.
        raw = {key: value for key, value in raw.items() if key in expected_fields}
        suppliers = _supplier_by_id(family_case)
        try:
            if action_type == "inquire":
                data = _exact_fields(raw, {"action", "supplier_id", "fields", "message"}, "action")
                _text(data["supplier_id"], "action.supplier_id")
                _text(data["message"], "action.message")
                fields = data["fields"]
                if not isinstance(fields, list) or not fields or any(
                    field not in family_case["policy"]["inquiry_fields"] for field in fields
                ):
                    raise ValueError("action.fields contains an unsupported inquiry")
                if len(fields) != len(set(fields)):
                    raise ValueError("action.fields contains duplicates")
            elif action_type in {"request_quote", "request_sample"}:
                data = _exact_fields(raw, {"action", "supplier_id", "message"}, "action")
                _text(data["supplier_id"], "action.supplier_id")
                _text(data["message"], "action.message")
            elif action_type == "counter_offer":
                data = _exact_fields(
                    raw,
                    {"action", "supplier_id", "offer_id", "proposal", "message"},
                    "action",
                )
                _text(data["supplier_id"], "action.supplier_id")
                _text(data["offer_id"], "action.offer_id")
                _text(data["message"], "action.message")
                proposal = data["proposal"]
                if isinstance(proposal, dict):
                    proposal = {
                        key: value for key, value in proposal.items() if value is not None
                    }
                    data["proposal"] = proposal
                if (
                    not isinstance(proposal, dict)
                    or not proposal
                    or not set(proposal) <= COUNTER_FIELDS
                ):
                    raise ValueError("action.proposal is empty or unsupported")
                if "unit_price_usd" in proposal:
                    proposal["unit_price_usd"] = _finite_number(
                        proposal["unit_price_usd"], "action.proposal.unit_price_usd", minimum=0.0
                    )
                for field in ("moq", "payment_terms_days", "refund_window_days"):
                    if field in proposal:
                        _positive_int(proposal[field], f"action.proposal.{field}")
                if proposal.get("return_freight_payer") not in {None, "buyer", "supplier"}:
                    raise ValueError("action.proposal.return_freight_payer is invalid")
            elif action_type == "submit_award":
                data = _exact_fields(raw, {"action", "award_lines"}, "action")
                lines = data["award_lines"]
                if not isinstance(lines, list) or not lines:
                    raise ValueError("action.award_lines must be non-empty")
                for index, line in enumerate(lines):
                    row = _exact_fields(
                        line,
                        {"offer_id", "quantity"},
                        f"action.award_lines[{index}]",
                    )
                    _text(row["offer_id"], f"action.award_lines[{index}].offer_id")
                    _positive_int(row["quantity"], f"action.award_lines[{index}].quantity")
            else:
                data = _exact_fields(raw, {"action", "reason"}, "action")
                _text(data["reason"], "action.reason")
        except ValueError:
            return ParseResult.failure("malformed_procurement_action")
        if action_type in {"inquire", "request_quote", "request_sample", "counter_offer"}:
            if data["supplier_id"] not in suppliers:
                return ParseResult.failure("unknown_supplier")
        return ParseResult.success(data)

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, seat, phase
        if state["done"]:
            return LegalityResult.illegal("episode_already_done")
        if action["action"] == "counter_offer":
            offer = state["offers"].get(action["offer_id"])
            if offer is None or offer["supplier_id"] != action["supplier_id"]:
                return LegalityResult.illegal("counter_requires_matching_formal_offer")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        del phase
        next_state = _plain(state)
        envelope = actions["buyer"]
        next_state["actions_used"] += 1
        if not envelope.valid:
            next_state["done"] = True
            next_state["termination_reason"] = "invalid_action"
            next_state["failure_code"] = (
                envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
            )
            return TransitionResult(
                state=next_state,
                next_phase_id=None,
                consequences={"failure_code": next_state["failure_code"]},
            )

        action = _plain(envelope.action)
        action_type = action["action"]
        supplier = _supplier_by_id(family_case).get(action.get("supplier_id", ""))
        interaction = family_case["interaction"]
        consequences: dict[str, Any] = {"action": action_type}
        if action_type == "inquire":
            next_state["elapsed_days"] += interaction["inquiry_days"]
            next_state["information_cost_usd"] += interaction["inquiry_cost_usd"]
            next_state["conversation"].append({"role": "buyer", "content": action["message"]})
            claims = next_state["claims"].setdefault(action["supplier_id"], {})
            summaries: list[str] = []
            terms = supplier["private_terms"]
            for field in action["fields"]:
                if field == "exact_variant":
                    value = terms["variant_id"]
                elif field == "moq_capacity":
                    value = {key: terms[key] for key in ("moq", "capacity", "order_step")}
                elif field == "lead_time":
                    value = {key: terms[key] for key in ("lead_time_days", "on_time_probability")}
                elif field == "shipping":
                    value = {
                        key: terms[key]
                        for key in ("shipping_per_unit_usd", "duty_rate", "payment_terms_days")
                    }
                elif field == "quality":
                    value = {
                        "claimed_yield_rate": terms["quality"]["verified_yield_rate"],
                        "sample_required_for_verification": True,
                    }
                else:
                    value = _plain(terms["return_policy"])
                claims[field] = {
                    "evidence_status": "verbal_claim",
                    "day": next_state["elapsed_days"],
                    "value": value,
                }
                summaries.append(f"{field}={json.dumps(value, sort_keys=True)}")
            reply = (
                "Verbal confirmation only; request a formal quote or sample. "
                + "; ".join(summaries)
            )
            next_state["conversation"].append(
                {"role": "supplier", "supplier_id": action["supplier_id"], "content": reply}
            )
        elif action_type == "request_quote":
            next_state["elapsed_days"] += interaction["quote_days"]
            next_state["information_cost_usd"] += interaction["quote_cost_usd"]
            version = next_state["offer_versions"].get(action["supplier_id"], 0) + 1
            offer = _base_offer(supplier, version=version, issued_day=next_state["elapsed_days"])
            next_state["offer_versions"][action["supplier_id"]] = version
            next_state["offers"][offer["offer_id"]] = offer
            next_state["latest_offer_by_supplier"][action["supplier_id"]] = offer["offer_id"]
            next_state["conversation"].extend(
                [
                    {"role": "buyer", "content": action["message"]},
                    {
                        "role": "supplier",
                        "supplier_id": action["supplier_id"],
                        "content": (
                            f"Formal offer {offer['offer_id']} issued at "
                            f"${offer['unit_price_usd']:.4f}/unit; MOQ {offer['moq']}; "
                            f"lead {offer['lead_time_days']} days; "
                            f"expires day {offer['expires_day']}."
                        ),
                    },
                ]
            )
            consequences["offer_id"] = offer["offer_id"]
        elif action_type == "counter_offer":
            next_state["elapsed_days"] += interaction["counter_days"]
            next_state["information_cost_usd"] += interaction["counter_cost_usd"]
            current = next_state["offers"][action["offer_id"]]
            accepted = _counter_is_accepted(supplier, current, action["proposal"])
            next_state["conversation"].append({"role": "buyer", "content": action["message"]})
            if accepted:
                version = (
                    next_state["offer_versions"].get(
                        action["supplier_id"], current["version"]
                    )
                    + 1
                )
                offer = _apply_counter(
                    current,
                    action["proposal"],
                    version=version,
                    issued_day=next_state["elapsed_days"],
                )
                next_state["offer_versions"][action["supplier_id"]] = version
                next_state["offers"][offer["offer_id"]] = offer
                next_state["latest_offer_by_supplier"][action["supplier_id"]] = offer["offer_id"]
                reply = f"Counter accepted and formalized as {offer['offer_id']}."
                consequences["offer_id"] = offer["offer_id"]
            else:
                reply = (
                    f"Counter rejected; {current['offer_id']} remains available "
                    f"until day {current['expires_day']}."
                )
            next_state["conversation"].append(
                {"role": "supplier", "supplier_id": action["supplier_id"], "content": reply}
            )
            consequences["accepted"] = accepted
        elif action_type == "request_sample":
            quality = supplier["private_terms"]["quality"]
            next_state["elapsed_days"] += quality["sample_lead_time_days"]
            next_state["information_cost_usd"] += quality["sample_cost_usd"]
            record = {
                "supplier_id": action["supplier_id"],
                "component": supplier["component"],
                "variant_id": supplier["private_terms"]["variant_id"],
                "evidence_status": "verified_sample",
                "verified_day": next_state["elapsed_days"],
                **_plain(quality),
            }
            next_state["quality_evidence"][action["supplier_id"]] = record
            next_state["conversation"].extend(
                [
                    {"role": "buyer", "content": action["message"]},
                    {
                        "role": "supplier",
                        "supplier_id": action["supplier_id"],
                        "content": (
                            f"Sample verified: {record['observed_defects']} defects in "
                            f"{record['sample_size']}; qualified yield "
                            f"{record['verified_yield_rate']:.3f}."
                        ),
                    },
                ]
            )
        elif action_type == "submit_award":
            next_state["award_lines"] = _plain(action["award_lines"])
            next_state["done"] = True
            next_state["termination_reason"] = "submitted"
        else:
            next_state["defer_reason"] = action["reason"]
            next_state["done"] = True
            next_state["termination_reason"] = "deferred"

        next_state["information_cost_usd"] = round(next_state["information_cost_usd"], 8)
        if (
            not next_state["done"]
            and next_state["actions_used"] >= family_case["interaction"]["max_actions"]
        ):
            next_state["done"] = True
            next_state["termination_reason"] = "interaction_budget_exhausted"
        return TransitionResult(
            state=next_state,
            next_phase_id=None if next_state["done"] else PHASE_ID,
            consequences=consequences,
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        if not state["done"]:
            return None
        return {
            "reason": state["termination_reason"],
            "failure_code": state["failure_code"],
            "actions_used": state["actions_used"],
            "elapsed_days": state["elapsed_days"],
            "information_cost_usd": state["information_cost_usd"],
            "offers": _plain(state["offers"]),
            "quality_evidence": _plain(state["quality_evidence"]),
            "award_lines": _plain(state["award_lines"]),
            "defer_reason": state["defer_reason"],
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        upper = solve_full_information_upper_bound(family_case)
        if terminal["reason"] == "submitted":
            evaluation = evaluate_award(
                family_case,
                award_lines=terminal["award_lines"],
                offers=terminal["offers"],
                quality_evidence=terminal["quality_evidence"],
                elapsed_days=terminal["elapsed_days"],
                information_cost_usd=terminal["information_cost_usd"],
            )
            decision = "award"
        else:
            fallback_value = round(
                family_case["objective"]["defer_value_usd"]
                - terminal["information_cost_usd"],
                8,
            )
            evaluation = {
                "feasible": terminal["reason"] == "deferred",
                "contribution_margin_usd": fallback_value,
                "raw_contribution_margin_usd": fallback_value,
                "completed_kits": 0,
                "cash_spend_usd": terminal["information_cost_usd"],
                "information_cost_usd": terminal["information_cost_usd"],
                "expected_recovery_usd": 0.0,
                "total_cost_usd": terminal["information_cost_usd"],
                "violations": (
                    []
                    if terminal["reason"] == "deferred"
                    else [terminal["failure_code"] or terminal["reason"]]
                ),
            }
            decision = "defer" if terminal["reason"] == "deferred" else "failed"
        value = float(evaluation["contribution_margin_usd"])
        return {
            "decision": decision,
            "termination_reason": terminal["reason"],
            "feasible": bool(evaluation["feasible"]),
            "contribution_margin_usd": value,
            "raw_contribution_margin_usd": float(evaluation["raw_contribution_margin_usd"]),
            "upper_bound_usd": upper.contribution_margin_usd,
            "regret_to_upper_bound_usd": round(max(0.0, upper.contribution_margin_usd - value), 8),
            "completed_kits": int(evaluation["completed_kits"]),
            "target_kits": family_case["objective"]["target_kits"],
            "cash_spend_usd": float(evaluation["cash_spend_usd"]),
            "information_cost_usd": float(evaluation["information_cost_usd"]),
            "expected_recovery_usd": float(evaluation.get("expected_recovery_usd", 0.0)),
            "total_cost_usd": float(evaluation["total_cost_usd"]),
            "elapsed_days": int(terminal["elapsed_days"]),
            "action_count": int(terminal["actions_used"]),
            "violations": list(evaluation["violations"]),
            "failure_code": terminal["failure_code"],
        }

    def build_scorer(
        self, family_case: Mapping[str, Any]
    ) -> ProcurementAllocationMeasurementScorer:
        return ProcurementAllocationMeasurementScorer(family_case)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any] | None = None) -> None:
        del family_case
        return None


__all__ = [
    "ACTION_TYPES",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "LEAF_ID",
    "PHASE_ID",
    "PLUGIN_ID",
    "SCORER_ID",
    "ProcurementAllocationMeasurementScorer",
    "ProcurementAllocationPlugin",
    "UpperBoundResult",
    "evaluate_award",
    "family_manifest",
    "procurement_allocation_measurement_leaf",
    "register_plugin",
    "solve_full_information_upper_bound",
]
