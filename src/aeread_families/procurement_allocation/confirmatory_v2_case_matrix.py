"""Held-out confirmatory v2 worlds for the pre-award-check treatment.

Twelve economic worlds created after the pre-award-check prompt was frozen
(digest 600828117b31f363232085cfcf088bfa20ba0207adeed05e83255c55f5f7a871) and
after the development result on the confirmatory v1 panel was read. They target
the failure modes the check is claimed to remove -- unsampled award lines,
over-capacity and order-step quantities, minimum-service shortfalls, cash-budget
breaches, and late suppliers -- with new world seeds, new case digests, and new
economic-world digests relative to the development, confirmatory v1, risk-gate,
and Qwen holdout panels.
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


PANEL_ID = "procurement_allocation_confirmatory_v2"
GENERATOR_ID = "procurement_allocation_confirmatory_v2_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
LABELED_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "confirmatory_v2"
    / "labeled"
)
OPAQUE_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "confirmatory_v2"
    / "opaque"
)
CASE_SLUGS = (
    "unsampled_split_temptation",
    "order_step_rounding_trap",
    "capacity_ceiling_split",
    "service_floor_cheap_bait",
    "cash_ceiling_landed",
    "late_supplier_discount",
    "dual_component_capacity",
    "multi_unit_bom_step",
    "yield_shortfall_service",
    "budget_versus_target",
    "terms_headroom_holdout",
    "variant_decoy_split",
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
    wrong_tp4056 = "usb_c_unprotected_no_separate_outputs"
    return (
        {
            "slug": "unsampled_split_temptation",
            "world_seed": 2414101,
            "product_id": "gateway_unsampled_split_holdout",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 14.0, "penalty": 4.0, "budget": 220.0, "deadline": 20, "minimum": 18},
            "suppliers": [
                _supplier("esp32_s3_n8r8", "half_lot_a", unit_price=3.1, capacity=10, moq=10, order_step=10, sample_days=2, yield_rate=1.0, on_time=1.0),
                _supplier("esp32_s3_n8r8", "half_lot_b", unit_price=3.3, capacity=10, moq=10, order_step=10, sample_days=2, yield_rate=1.0, on_time=1.0),
                _supplier("ssd1306_oled_096", "full_lot", unit_price=1.6, capacity=20, moq=10, order_step=10, yield_rate=1.0, on_time=1.0),
                _supplier("ssd1306_oled_096", "half_lot", unit_price=1.2, capacity=10, moq=10, order_step=10, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "order_step_rounding_trap",
            "world_seed": 2414102,
            "product_id": "panel_order_step_holdout",
            "bom": {"tactile_switch_6x6x5": 1, "ky040_encoder": 1},
            "objective": {"revenue": 7.0, "penalty": 3.0, "budget": 110.0, "deadline": 22, "minimum": 18},
            "suppliers": [
                _supplier("tactile_switch_6x6x5", "step_six", unit_price=0.10, capacity=24, moq=6, order_step=6, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("tactile_switch_6x6x5", "step_ten", unit_price=0.14, capacity=20, moq=10, order_step=10, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("ky040_encoder", "step_six", unit_price=0.66, capacity=24, moq=6, order_step=6, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("ky040_encoder", "step_ten", unit_price=0.80, capacity=20, moq=10, order_step=10, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
            ],
        },
        {
            "slug": "capacity_ceiling_split",
            "world_seed": 2414103,
            "product_id": "sensor_capacity_ceiling_holdout",
            "bom": {"sht30_i2c": 1, "bh1750_gy302": 1},
            "objective": {"revenue": 10.0, "penalty": 4.0, "budget": 150.0, "deadline": 20, "minimum": 18},
            "suppliers": [
                _supplier("sht30_i2c", "cap_twelve", unit_price=1.05, capacity=12, moq=6, order_step=6, yield_rate=1.0, on_time=1.0),
                _supplier("sht30_i2c", "cap_twelve_alt", unit_price=1.15, capacity=12, moq=6, order_step=6, yield_rate=1.0, on_time=1.0),
                _supplier("bh1750_gy302", "cap_twelve", unit_price=0.62, capacity=12, moq=6, order_step=6, yield_rate=1.0, on_time=1.0),
                _supplier("bh1750_gy302", "cap_twelve_alt", unit_price=0.70, capacity=12, moq=6, order_step=6, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "service_floor_cheap_bait",
            "world_seed": 2414104,
            "product_id": "joystick_service_floor_holdout",
            "bom": {"ky023_joystick": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 11.0, "penalty": 5.0, "budget": 160.0, "deadline": 20, "minimum": 18},
            "suppliers": [
                _supplier("ky023_joystick", "bait_low_yield", unit_price=0.55, yield_rate=0.80, on_time=0.95),
                _supplier("ky023_joystick", "service_grade", unit_price=1.60, yield_rate=0.99, on_time=0.99),
                _supplier("ssd1306_oled_096", "bait_low_yield", unit_price=0.85, yield_rate=0.80, on_time=0.95),
                _supplier("ssd1306_oled_096", "service_grade", unit_price=1.90, yield_rate=0.99, on_time=0.99),
            ],
        },
        {
            "slug": "cash_ceiling_landed",
            "world_seed": 2414105,
            "product_id": "gateway_cash_ceiling_holdout",
            "bom": {"esp32_s3_n8r8": 1, "ds3231_at24c32": 1},
            "objective": {"revenue": 13.0, "penalty": 4.0, "budget": 128.0, "deadline": 20, "minimum": 18},
            "suppliers": [
                _supplier("esp32_s3_n8r8", "sticker_low_landed_high", unit_price=2.6, shipping=1.9, duty_rate=0.16),
                _supplier("esp32_s3_n8r8", "landed_clean", unit_price=3.4, shipping=0.08, duty_rate=0.02),
                _supplier("ds3231_at24c32", "sticker_low_landed_high", unit_price=1.5, shipping=1.2, duty_rate=0.16),
                _supplier("ds3231_at24c32", "landed_clean", unit_price=2.1, shipping=0.08, duty_rate=0.02),
            ],
        },
        {
            "slug": "late_supplier_discount",
            "world_seed": 2414106,
            "product_id": "charger_late_discount_holdout",
            "bom": {"tp4056_usb_c_protected": 1, "mosfet_low_side_3v3": 1},
            "objective": {"revenue": 9.0, "penalty": 4.0, "budget": 140.0, "deadline": 12, "minimum": 18},
            "suppliers": [
                _supplier("tp4056_usb_c_protected", "cheap_late", unit_price=0.40, lead_time=14, yield_rate=1.0, on_time=1.0),
                _supplier("tp4056_usb_c_protected", "on_deadline", unit_price=0.78, lead_time=6, yield_rate=1.0, on_time=1.0),
                _supplier("mosfet_low_side_3v3", "cheap_late", unit_price=0.35, lead_time=14, yield_rate=1.0, on_time=1.0),
                _supplier("mosfet_low_side_3v3", "on_deadline", unit_price=0.70, lead_time=6, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "dual_component_capacity",
            "world_seed": 2414107,
            "product_id": "dual_capacity_holdout",
            "bom": {"ky040_encoder": 1, "bh1750_gy302": 1},
            "objective": {"revenue": 8.0, "penalty": 3.0, "budget": 130.0, "deadline": 22, "minimum": 18},
            "suppliers": [
                _supplier("ky040_encoder", "cap_ten_a", unit_price=0.58, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0),
                _supplier("ky040_encoder", "cap_ten_b", unit_price=0.64, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0),
                _supplier("bh1750_gy302", "cap_ten_a", unit_price=0.52, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0),
                _supplier("bh1750_gy302", "cap_ten_b", unit_price=0.58, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "multi_unit_bom_step",
            "world_seed": 2414108,
            "product_id": "multi_unit_step_holdout",
            "bom": {"tactile_switch_6x6x5": 3, "mosfet_low_side_3v3": 2},
            "objective": {"revenue": 12.0, "penalty": 4.0, "budget": 200.0, "deadline": 22, "minimum": 18},
            "suppliers": [
                _supplier("tactile_switch_6x6x5", "volume", unit_price=0.10, capacity=70, moq=20, order_step=10, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("tactile_switch_6x6x5", "small_lot", unit_price=0.08, capacity=40, moq=10, order_step=10, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("mosfet_low_side_3v3", "volume", unit_price=0.75, capacity=60, moq=20, order_step=10, yield_rate=1.0, on_time=1.0),
                _supplier("mosfet_low_side_3v3", "small_lot", unit_price=0.62, capacity=30, moq=10, order_step=10, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "yield_shortfall_service",
            "world_seed": 2414109,
            "product_id": "yield_shortfall_holdout",
            "bom": {"sht30_i2c": 1, "tp4056_usb_c_protected": 1},
            "objective": {"revenue": 10.0, "penalty": 5.0, "budget": 150.0, "deadline": 20, "minimum": 18, "defect_days": 20},
            "suppliers": [
                _supplier("sht30_i2c", "low_yield_cheap", unit_price=0.90, yield_rate=0.84, refund_days=40, claim_acceptance=0.9),
                _supplier("sht30_i2c", "high_yield", unit_price=1.55, yield_rate=0.995),
                _supplier("tp4056_usb_c_protected", "low_yield_cheap", unit_price=0.45, yield_rate=0.84, refund_days=40, claim_acceptance=0.9),
                _supplier("tp4056_usb_c_protected", "high_yield", unit_price=0.85, yield_rate=0.995),
            ],
        },
        {
            "slug": "budget_versus_target",
            "world_seed": 2414110,
            "product_id": "budget_versus_target_holdout",
            "bom": {"ds3231_at24c32": 1, "ky023_joystick": 1},
            "objective": {"revenue": 12.0, "penalty": 3.0, "budget": 96.0, "deadline": 22, "minimum": 18},
            "suppliers": [
                _supplier("ds3231_at24c32", "only_source", unit_price=2.2, capacity=20, moq=18, order_step=2, yield_rate=1.0, on_time=1.0),
                _supplier("ds3231_at24c32", "pricier_source", unit_price=2.6, capacity=20, moq=18, order_step=2, yield_rate=1.0, on_time=1.0),
                _supplier("ky023_joystick", "only_source", unit_price=1.5, capacity=20, moq=18, order_step=2, yield_rate=1.0, on_time=1.0),
                _supplier("ky023_joystick", "pricier_source", unit_price=1.8, capacity=20, moq=18, order_step=2, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "terms_headroom_holdout",
            "world_seed": 2414111,
            "product_id": "terms_headroom_holdout",
            "bom": {"ds3231_at24c32": 1, "ky040_encoder": 1},
            "objective": {"revenue": 11.0, "penalty": 3.0, "budget": 150.0, "deadline": 22, "minimum": 18, "capital_horizon": 180, "annual_rate": 2.0},
            "suppliers": [
                _supplier("ds3231_at24c32", "terms_open", unit_price=2.3, payment_days=1, maximum_payment_days=150, floor_price=2.28, yield_rate=1.0, on_time=1.0),
                _supplier("ds3231_at24c32", "terms_shut", unit_price=2.55, payment_days=90, maximum_payment_days=90, floor_price=2.53, yield_rate=1.0, on_time=1.0),
                _supplier("ky040_encoder", "terms_open", unit_price=0.80, payment_days=1, maximum_payment_days=150, floor_price=0.79, yield_rate=1.0, on_time=1.0),
                _supplier("ky040_encoder", "terms_shut", unit_price=0.98, payment_days=90, maximum_payment_days=90, floor_price=0.97, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "variant_decoy_split",
            "world_seed": 2414112,
            "product_id": "variant_decoy_split_holdout",
            "bom": {"tp4056_usb_c_protected": 1, "ky040_encoder": 1},
            "objective": {"revenue": 9.0, "penalty": 4.0, "budget": 140.0, "deadline": 20, "minimum": 18},
            "suppliers": [
                _supplier("tp4056_usb_c_protected", "decoy_cheap", unit_price=0.30, variant=wrong_tp4056, capacity=40),
                _supplier("tp4056_usb_c_protected", "exact_half_a", unit_price=0.74, capacity=10, moq=10, order_step=10),
                _supplier("tp4056_usb_c_protected", "exact_half_b", unit_price=0.80, capacity=10, moq=10, order_step=10),
                _supplier("ky040_encoder", "exact_full", unit_price=0.70, capacity=40),
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
                "inquiry_cost_usd": 0.05,
                "quote_cost_usd": 0.1,
                "counter_cost_usd": 0.15,
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
    if len(cases) != 12 or len({case["world_seed"] for case in cases}) != len(cases):
        raise AssertionError("confirmatory panel requires twelve distinct worlds")
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
