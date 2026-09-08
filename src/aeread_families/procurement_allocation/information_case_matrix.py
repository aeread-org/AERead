"""Worlds that give the information and negotiation half of the objective bite.

The design review (docs/families/procurement-allocation/design_review.md) records
three reasons the family cannot currently measure what its objective declares:
verbal claims are always true, information is under 2% of gross revenue, and only
2 of 147 supplier records have any MOQ headroom while price floors sit about 3%
below the quote. Every world here is built to remove one of those.

- Suppliers state optimistic terms verbally (``verbal_bias``); only a sample or a
  formal quote reveals the truth, so verification has something to catch.
- Information is priced at a level where buying all of it is a real loss, so the
  buyer must choose what to learn.
- Price floors sit 15-30% below the quote and MOQ limits well below the quoted
  minimum, so a counter is worth tens of dollars rather than cents.

These worlds are for measuring the information half. They are deliberately not a
confirmatory panel for any frozen treatment.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .case_matrix import (
    CASE_VARIANCE_PATHS,
    GROUNDING_SELECTION,
    REPOSITORY_ROOT,
    REQUIRED_VARIANTS,
    validate_grounding_snapshot,
)
from .environment import ProcurementAllocationPlugin, solve_full_information_upper_bound


PANEL_ID = "procurement_allocation_information_v1"
GENERATOR_ID = "procurement_allocation_information_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
LABELED_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "information_v1"
    / "labeled"
)
OPAQUE_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "information_v1"
    / "opaque"
)
CASE_SLUGS = (
    "optimistic_yield_claim",
    "optimistic_lead_time_claim",
    "optimistic_capacity_claim",
    "price_floor_headroom",
    "moq_floor_headroom",
    "costly_information_budget",
    "claim_versus_sample_tradeoff",
    "negotiate_or_switch",
)
LABELED_PATHS = tuple(LABELED_ROOT / f"{slug}.json" for slug in CASE_SLUGS)
OPAQUE_PATHS = tuple(OPAQUE_ROOT / f"{slug}.json" for slug in CASE_SLUGS)


def _supplier(
    component: str,
    label: str,
    *,
    unit_price: float,
    shipping: float = 0.05,
    duty_rate: float = 0.05,
    lead_time: int = 6,
    on_time: float = 0.99,
    yield_rate: float = 0.99,
    capacity: int = 40,
    moq: int = 10,
    order_step: int = 10,
    payment_days: int = 30,
    offer_valid_days: int = 30,
    sample_cost: float = 0.4,
    sample_days: int = 1,
    variant: str | None = None,
    refund_days: int = 30,
    claim_acceptance: float = 0.95,
    restocking_rate: float = 0.0,
    freight_payer: str = "supplier",
    return_freight: float = 0.0,
    refund_delay: int = 5,
    floor_price: float | None = None,
    minimum_moq: int | None = None,
    maximum_payment_days: int | None = None,
    maximum_refund_days: int | None = None,
    supplier_paid_return_freight: bool | None = None,
    verbal_bias: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    supplier_id = f"{component}_{label}"
    exact_variant = variant or REQUIRED_VARIANTS[component]
    return {
        "supplier_id": supplier_id,
        "component": component,
        "listing": {
            "supplier_name": f"Synthetic {label.replace('_', ' ').title()} supplier",
            "displayed_unit_price_usd": round(unit_price * 0.82, 6),
            "claimed_lead_time_days": max(1, lead_time - 2),
            "claimed_variant": exact_variant.replace("_", " "),
            "evidence_status": "marketplace_listing_unverified",
        },
        "private_terms": {
            "variant_id": exact_variant,
            "base_unit_price_usd": unit_price,
            "shipping_per_unit_usd": shipping,
            "duty_rate": duty_rate,
            "capacity": capacity,
            "moq": moq,
            "order_step": order_step,
            "lead_time_days": lead_time,
            "on_time_probability": on_time,
            "payment_terms_days": payment_days,
            "offer_valid_days": offer_valid_days,
            "return_policy": {
                "refund_window_days": refund_days,
                "claim_acceptance_probability": claim_acceptance,
                "restocking_fee_rate": restocking_rate,
                "return_freight_payer": freight_payer,
                "return_freight_per_unit_usd": return_freight,
                "refund_delay_days": refund_delay,
            },
            "quality": {
                "sample_size": 100,
                "observed_defects": round(100 * (1.0 - yield_rate)),
                "verified_yield_rate": yield_rate,
                "sample_cost_usd": sample_cost,
                "sample_lead_time_days": sample_days,
            },
            **({"verbal_bias": dict(verbal_bias)} if verbal_bias else {}),
            "negotiation": {
                "floor_unit_price_usd": (
                    unit_price if floor_price is None else floor_price
                ),
                "minimum_moq": moq if minimum_moq is None else minimum_moq,
                "maximum_payment_terms_days": (
                    payment_days
                    if maximum_payment_days is None
                    else maximum_payment_days
                ),
                "maximum_refund_window_days": (
                    refund_days if maximum_refund_days is None else maximum_refund_days
                ),
                "supplier_paid_return_freight_available": (
                    freight_payer == "supplier"
                    if supplier_paid_return_freight is None
                    else supplier_paid_return_freight
                ),
            },
        },
    }


def _definitions() -> tuple[dict[str, Any], ...]:
    # Information priced to bite: an inquiry, quote, counter, and sample together
    # cost a meaningful share of gross margin rather than a rounding error.
    dear = {"inquiry": 1.2, "quote": 2.0, "counter": 2.5, "sample": 6.0}
    return (
        {
            "slug": "optimistic_yield_claim",
            "world_seed": 2514101,
            "product_id": "sensor_optimistic_yield",
            "bom": {"sht30_i2c": 1, "bh1750_gy302": 1},
            "objective": {"revenue": 10.0, "penalty": 4.0, "budget": 150.0, "deadline": 20, "minimum": 18},
            "interaction": dear,
            "suppliers": [
                _supplier("sht30_i2c", "claims_high_yield", unit_price=0.85, yield_rate=0.80, sample_cost=dear["sample"], verbal_bias={"verified_yield_rate": 0.99}),
                _supplier("sht30_i2c", "honest_yield", unit_price=1.45, yield_rate=0.99, sample_cost=dear["sample"]),
                _supplier("bh1750_gy302", "claims_high_yield", unit_price=0.50, yield_rate=0.80, sample_cost=dear["sample"], verbal_bias={"verified_yield_rate": 0.99}),
                _supplier("bh1750_gy302", "honest_yield", unit_price=0.95, yield_rate=0.99, sample_cost=dear["sample"]),
            ],
        },
        {
            "slug": "optimistic_lead_time_claim",
            "world_seed": 2514102,
            "product_id": "gateway_optimistic_lead_time",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 13.0, "penalty": 4.0, "budget": 200.0, "deadline": 12, "minimum": 18},
            "interaction": dear,
            "suppliers": [
                _supplier("esp32_s3_n8r8", "claims_fast", unit_price=2.9, lead_time=15, sample_cost=dear["sample"], verbal_bias={"lead_time_days": 5}),
                _supplier("esp32_s3_n8r8", "honest_fast", unit_price=3.9, lead_time=6, sample_cost=dear["sample"]),
                _supplier("ssd1306_oled_096", "claims_fast", unit_price=1.1, lead_time=15, sample_cost=dear["sample"], verbal_bias={"lead_time_days": 5}),
                _supplier("ssd1306_oled_096", "honest_fast", unit_price=1.7, lead_time=6, sample_cost=dear["sample"]),
            ],
        },
        {
            "slug": "optimistic_capacity_claim",
            "world_seed": 2514103,
            "product_id": "panel_optimistic_capacity",
            "bom": {"tactile_switch_6x6x5": 1, "ky040_encoder": 1},
            "objective": {"revenue": 9.0, "penalty": 3.0, "budget": 160.0, "deadline": 22, "minimum": 18},
            "interaction": dear,
            "suppliers": [
                _supplier("tactile_switch_6x6x5", "claims_full_lot", unit_price=0.12, capacity=10, moq=10, order_step=10, sample_cost=dear["sample"], verbal_bias={"capacity": 20}),
                _supplier("tactile_switch_6x6x5", "honest_half_lot", unit_price=0.15, capacity=10, moq=10, order_step=10, sample_cost=dear["sample"]),
                _supplier("ky040_encoder", "claims_full_lot", unit_price=0.60, capacity=10, moq=10, order_step=10, sample_cost=dear["sample"], verbal_bias={"capacity": 20}),
                _supplier("ky040_encoder", "honest_half_lot", unit_price=0.72, capacity=10, moq=10, order_step=10, sample_cost=dear["sample"]),
            ],
        },
        {
            "slug": "price_floor_headroom",
            "world_seed": 2514104,
            "product_id": "clock_price_headroom",
            "bom": {"ds3231_at24c32": 1, "ky023_joystick": 1},
            "objective": {"revenue": 12.0, "penalty": 3.0, "budget": 180.0, "deadline": 22, "minimum": 18},
            "interaction": dear,
            "suppliers": [
                _supplier("ds3231_at24c32", "deep_floor", unit_price=2.60, floor_price=1.90, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("ds3231_at24c32", "shallow_floor", unit_price=2.30, floor_price=2.28, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("ky023_joystick", "deep_floor", unit_price=1.70, floor_price=1.20, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("ky023_joystick", "shallow_floor", unit_price=1.50, floor_price=1.48, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "moq_floor_headroom",
            "world_seed": 2514105,
            "product_id": "charger_moq_headroom",
            "bom": {"tp4056_usb_c_protected": 1, "mosfet_low_side_3v3": 1},
            "objective": {"revenue": 8.0, "penalty": 3.0, "budget": 92.0, "deadline": 22, "minimum": 18},
            "interaction": dear,
            "suppliers": [
                _supplier("tp4056_usb_c_protected", "moq_negotiable", unit_price=0.70, moq=40, minimum_moq=20, capacity=40, order_step=10, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("tp4056_usb_c_protected", "moq_fixed", unit_price=0.95, moq=20, capacity=40, order_step=10, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("mosfet_low_side_3v3", "moq_negotiable", unit_price=0.60, moq=40, minimum_moq=20, capacity=40, order_step=10, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("mosfet_low_side_3v3", "moq_fixed", unit_price=0.85, moq=20, capacity=40, order_step=10, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "costly_information_budget",
            "world_seed": 2514106,
            "product_id": "sensor_costly_information",
            "bom": {"sht30_i2c": 1, "tp4056_usb_c_protected": 1},
            "objective": {"revenue": 7.0, "penalty": 2.0, "budget": 120.0, "deadline": 22, "minimum": 18},
            "interaction": {"inquiry": 2.5, "quote": 4.0, "counter": 4.0, "sample": 9.0},
            "suppliers": [
                _supplier("sht30_i2c", "adequate_a", unit_price=1.10, sample_cost=9.0, yield_rate=0.99, on_time=0.99),
                _supplier("sht30_i2c", "adequate_b", unit_price=1.15, sample_cost=9.0, yield_rate=0.99, on_time=0.99),
                _supplier("tp4056_usb_c_protected", "adequate_a", unit_price=0.60, sample_cost=9.0, yield_rate=0.99, on_time=0.99),
                _supplier("tp4056_usb_c_protected", "adequate_b", unit_price=0.64, sample_cost=9.0, yield_rate=0.99, on_time=0.99),
            ],
        },
        {
            "slug": "claim_versus_sample_tradeoff",
            "world_seed": 2514107,
            "product_id": "display_claim_versus_sample",
            "bom": {"ssd1306_oled_096": 1, "ky040_encoder": 1},
            "objective": {"revenue": 11.0, "penalty": 4.0, "budget": 170.0, "deadline": 20, "minimum": 18},
            "interaction": dear,
            "suppliers": [
                _supplier("ssd1306_oled_096", "cheap_overclaims", unit_price=1.00, yield_rate=0.86, sample_cost=dear["sample"], verbal_bias={"verified_yield_rate": 0.98, "on_time_probability": 0.99}, on_time=0.9),
                _supplier("ssd1306_oled_096", "dear_accurate", unit_price=1.80, yield_rate=0.98, on_time=0.99, sample_cost=dear["sample"]),
                _supplier("ky040_encoder", "cheap_overclaims", unit_price=0.55, yield_rate=0.86, sample_cost=dear["sample"], verbal_bias={"verified_yield_rate": 0.98, "on_time_probability": 0.99}, on_time=0.9),
                _supplier("ky040_encoder", "dear_accurate", unit_price=1.05, yield_rate=0.98, on_time=0.99, sample_cost=dear["sample"]),
            ],
        },
        {
            "slug": "negotiate_or_switch",
            "world_seed": 2514108,
            "product_id": "clock_negotiate_or_switch",
            "bom": {"ds3231_at24c32": 1, "bh1750_gy302": 1},
            "objective": {"revenue": 11.0, "penalty": 3.0, "budget": 145.0, "deadline": 22, "minimum": 18},
            "interaction": dear,
            "suppliers": [
                _supplier("ds3231_at24c32", "dear_but_negotiable", unit_price=2.90, floor_price=1.95, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("ds3231_at24c32", "cheap_but_fixed", unit_price=2.30, floor_price=2.29, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("bh1750_gy302", "dear_but_negotiable", unit_price=1.40, floor_price=0.95, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
                _supplier("bh1750_gy302", "cheap_but_fixed", unit_price=1.10, floor_price=1.09, sample_cost=dear["sample"], yield_rate=1.0, on_time=1.0),
            ],
        },
    )


def _build_case(definition: Mapping[str, Any], *, surface: str) -> dict[str, Any]:
    if surface not in {"labeled", "opaque"}:
        raise ValueError("surface must be labeled or opaque")
    knobs = definition["objective"]
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"procurement_allocation_v1.confirmatory_v1_{surface}.{definition['slug']}",
        "family_id": "procurement_allocation_v1",
        "family_version": "1.0.0",
        "split": f"confirmatory_v1_{surface}",
        "world_seed": definition["world_seed"],
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {
            "max_logical_actions": 10,
            "termination": ["submitted", "deferred", "interaction_budget_exhausted", "invalid_action"],
        },
        "visibility_policy": "procurement_allocation_public_listings_private_supplier_terms_v1",
        "payload": {
            "objective": {
                "product_id": definition["product_id"],
                "target_kits": 20,
                "minimum_service_kits": knobs.get("minimum", 16),
                "revenue_per_completed_kit_usd": knobs["revenue"],
                "shortfall_penalty_per_kit_usd": knobs["penalty"],
                "cash_budget_usd": knobs["budget"],
                "deadline_days": knobs["deadline"],
                "defect_detection_days": knobs.get("defect_days", 10),
                "working_capital_horizon_days": knobs.get("capital_horizon", 45),
                "annual_financing_rate": knobs.get("annual_rate", 0.12),
                "defer_value_usd": knobs.get("defer", 0.0),
                "bom": definition["bom"],
            },
            "interaction": {
                "max_actions": 10,
                "inquiry_days": 1,
                "quote_days": 1,
                "counter_days": 1,
                "inquiry_cost_usd": definition["interaction"]["inquiry"],
                "quote_cost_usd": definition["interaction"]["quote"],
                "counter_cost_usd": definition["interaction"]["counter"],
            },
            "policy": {
                "required_variant_by_component": {
                    component: REQUIRED_VARIANTS[component]
                    for component in definition["bom"]
                },
                "inquiry_fields": ["exact_variant", "moq_capacity", "lead_time", "shipping", "quality", "return_refund_policy"],
                "award_requires": ["unexpired_formal_offer", "verified_sample", "exact_variant"],
            },
            "suppliers": copy.deepcopy(definition["suppliers"]),
        },
        "provenance": {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    if surface == "opaque":
        slug = str(definition["slug"])
        for supplier in raw["payload"]["suppliers"]:
            opaque = hashlib.sha256(
                f"{PANEL_ID}:{slug}:{supplier['supplier_id']}".encode()
            ).hexdigest()[:12]
            supplier["supplier_id"] = f"supplier_{opaque}"
            supplier["listing"]["supplier_name"] = f"Supplier {opaque.upper()}"
        raw["payload"]["suppliers"].sort(
            key=lambda supplier: hashlib.sha256(
                f"{PANEL_ID}:order:{slug}:{supplier['supplier_id']}".encode()
            ).hexdigest()
        )
    draft = CaseManifest.from_dict(raw)
    ProcurementAllocationPlugin().validate_payload(draft.payload)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError(f"unstable case digest for {case.case_id}")
    upper = solve_full_information_upper_bound(case.payload)
    if upper.contribution_margin_usd <= case.payload["objective"]["defer_value_usd"]:
        raise ValueError(f"{case.case_id} has no beneficial feasible award")
    return raw


def economic_world_projection(case: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only presentation identity/order fields from a paired case."""

    payload = copy.deepcopy(case["payload"])
    normalized_suppliers = []
    for supplier in payload["suppliers"]:
        supplier.pop("supplier_id")
        supplier["listing"].pop("supplier_name")
        normalized_suppliers.append(supplier)
    normalized_suppliers.sort(key=canonical_json_bytes)
    payload["suppliers"] = normalized_suppliers
    return {"world_seed": case["world_seed"], "payload": payload}


def economic_world_sha256(case: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(economic_world_projection(case))).hexdigest()


def build_confirmatory_case_matrix(*, surface: str) -> tuple[dict[str, Any], ...]:
    validate_grounding_snapshot()
    cases = tuple(_build_case(definition, surface=surface) for definition in _definitions())
    if len(cases) != len(CASE_SLUGS) or len({case["world_seed"] for case in cases}) != len(cases):
        raise AssertionError("information panel requires eight distinct worlds")
    development = {
        CaseManifest.from_dict(json.loads(path.read_text())).content_sha256
        for path in CASE_VARIANCE_PATHS
    }
    if development.intersection(case["content_sha256"] for case in cases):
        raise AssertionError("confirmatory cases reuse a development case digest")
    used_components = {
        component
        for case in cases
        for component in case["payload"]["objective"]["bom"]
    }
    if not used_components <= set(GROUNDING_SELECTION):
        raise AssertionError("confirmatory component is absent from grounding selection")
    return cases


def write_confirmatory_case_matrix(*, surface: str, root: Path | None = None) -> tuple[Path, ...]:
    destination = root or (LABELED_ROOT if surface == "labeled" else OPAQUE_ROOT)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in build_confirmatory_case_matrix(surface=surface):
        path = destination / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        payload = json.dumps(case, indent=2, sort_keys=True) + "\n"
        temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
        written.append(path)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=("labeled", "opaque"), required=True)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    cases = build_confirmatory_case_matrix(surface=arguments.surface)
    if arguments.write:
        for path in write_confirmatory_case_matrix(surface=arguments.surface):
            print(path)
    else:
        print(json.dumps(cases, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_SLUGS",
    "LABELED_PATHS",
    "OPAQUE_PATHS",
    "PANEL_ID",
    "build_confirmatory_case_matrix",
    "economic_world_projection",
    "economic_world_sha256",
    "write_confirmatory_case_matrix",
]
