"""Generate the frozen procurement-allocation confirmatory panel.

The economic worlds are new relative to the six adaptive development worlds.
Component families remain anchored to the frozen 231-project demand snapshot;
all supplier identities and commercial terms are synthetic experimental inputs.
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


PANEL_ID = "procurement_allocation_confirmatory_v1"
GENERATOR_ID = "procurement_allocation_confirmatory_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
LABELED_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "confirmatory_v1"
    / "labeled"
)
OPAQUE_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "confirmatory_v1"
    / "opaque"
)
CASE_SLUGS = (
    "landed_cost_freight",
    "quality_refund_tail",
    "split_capacity_rounding",
    "cash_budget_counter",
    "exact_variant_decoys",
    "defer_borderline_service",
    "sample_lead_time",
    "refund_counter",
    "payment_terms_counter",
    "on_time_reliability",
    "multi_unit_bom",
    "negotiated_moq",
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
    wrong_mosfet = "five_volt_gate_high_side_module"
    return (
        {
            "slug": "landed_cost_freight",
            "world_seed": 2313101,
            "product_id": "display_gateway_landed_cost_holdout",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 12.0, "penalty": 4.0, "budget": 175.0, "deadline": 18},
            "suppliers": [
                _supplier("esp32_s3_n8r8", "low_sticker", unit_price=3.0, shipping=2.4, duty_rate=0.18),
                _supplier("esp32_s3_n8r8", "landed_clear", unit_price=4.2, shipping=0.1, duty_rate=0.02),
                _supplier("ssd1306_oled_096", "low_sticker", unit_price=0.9, shipping=1.2, duty_rate=0.18),
                _supplier("ssd1306_oled_096", "landed_clear", unit_price=1.5, shipping=0.1, duty_rate=0.02),
            ],
        },
        {
            "slug": "quality_refund_tail",
            "world_seed": 2313102,
            "product_id": "sensor_pair_quality_tail_holdout",
            "bom": {"sht30_i2c": 1, "bh1750_gy302": 1},
            "objective": {"revenue": 9.0, "penalty": 5.0, "budget": 120.0, "deadline": 22, "minimum": 18, "defect_days": 20},
            "suppliers": [
                _supplier("sht30_i2c", "refund_heavy", unit_price=0.95, yield_rate=0.86, refund_days=45, claim_acceptance=0.99),
                _supplier("sht30_i2c", "yield_stable", unit_price=1.7, yield_rate=0.995, refund_days=8, claim_acceptance=0.3, freight_payer="buyer", return_freight=0.3),
                _supplier("bh1750_gy302", "refund_heavy", unit_price=0.55, yield_rate=0.85, refund_days=45, claim_acceptance=0.99),
                _supplier("bh1750_gy302", "yield_stable", unit_price=1.1, yield_rate=0.995, refund_days=8, claim_acceptance=0.3, freight_payer="buyer", return_freight=0.2),
            ],
        },
        {
            "slug": "split_capacity_rounding",
            "world_seed": 2313103,
            "product_id": "control_panel_split_rounding_holdout",
            "bom": {"tactile_switch_6x6x5": 1, "ky040_encoder": 1},
            "objective": {"revenue": 6.0, "penalty": 3.0, "budget": 90.0, "deadline": 22, "minimum": 18},
            "suppliers": [
                _supplier("tactile_switch_6x6x5", "lot_seven_a", unit_price=0.08, capacity=14, moq=7, order_step=7, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("tactile_switch_6x6x5", "lot_seven_b", unit_price=0.09, capacity=14, moq=7, order_step=7, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("ky040_encoder", "full_lot", unit_price=0.62, capacity=21, moq=7, order_step=7, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("ky040_encoder", "small_capacity", unit_price=0.48, capacity=14, moq=7, order_step=7, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
            ],
        },
        {
            "slug": "cash_budget_counter",
            "world_seed": 2313104,
            "product_id": "connected_clock_cash_counter_holdout",
            "bom": {"ds3231_at24c32": 1, "esp32_s3_n8r8": 1},
            "objective": {"revenue": 13.0, "penalty": 4.0, "budget": 114.0, "deadline": 24, "minimum": 18},
            "suppliers": [
                _supplier("ds3231_at24c32", "negotiable", unit_price=2.4, floor_price=1.8, yield_rate=1.0, on_time=1.0),
                _supplier("ds3231_at24c32", "fixed", unit_price=2.1, floor_price=2.08, yield_rate=0.9, on_time=0.95),
                _supplier("esp32_s3_n8r8", "negotiable", unit_price=4.8, floor_price=3.4, yield_rate=1.0, on_time=1.0),
                _supplier("esp32_s3_n8r8", "fixed", unit_price=4.2, floor_price=4.18, yield_rate=0.9, on_time=0.95),
            ],
        },
        {
            "slug": "exact_variant_decoys",
            "world_seed": 2313105,
            "product_id": "protected_power_stage_variant_holdout",
            "bom": {"tp4056_usb_c_protected": 1, "mosfet_low_side_3v3": 1},
            "objective": {"revenue": 8.0, "penalty": 4.0, "budget": 95.0, "deadline": 20},
            "suppliers": [
                _supplier("tp4056_usb_c_protected", "cheap_near_match", unit_price=0.32, variant=wrong_tp4056),
                _supplier("tp4056_usb_c_protected", "exact_protected", unit_price=0.78),
                _supplier("mosfet_low_side_3v3", "cheap_near_match", unit_price=0.28, variant=wrong_mosfet),
                _supplier("mosfet_low_side_3v3", "exact_logic", unit_price=0.82),
            ],
        },
        {
            "slug": "defer_borderline_service",
            "world_seed": 2313106,
            "product_id": "operator_console_service_holdout",
            "bom": {"ky023_joystick": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 8.0, "penalty": 4.0, "budget": 125.0, "deadline": 18, "minimum": 18, "defer": 8.0},
            "suppliers": [
                _supplier("ky023_joystick", "risky", unit_price=0.72, yield_rate=0.82, on_time=0.9),
                _supplier("ky023_joystick", "service", unit_price=1.75, yield_rate=0.96, on_time=0.99),
                _supplier("ssd1306_oled_096", "risky", unit_price=1.0, yield_rate=0.82, on_time=0.9),
                _supplier("ssd1306_oled_096", "service", unit_price=2.05, yield_rate=0.96, on_time=0.99),
            ],
        },
        {
            "slug": "sample_lead_time",
            "world_seed": 2313107,
            "product_id": "telemetry_node_sample_delay_holdout",
            "bom": {"sht30_i2c": 1, "esp32_s3_n8r8": 1},
            "objective": {"revenue": 13.0, "penalty": 5.0, "budget": 150.0, "deadline": 14, "minimum": 18},
            "suppliers": [
                _supplier("sht30_i2c", "slow_sample", unit_price=1.0, lead_time=5, sample_days=5, yield_rate=1.0, on_time=1.0),
                _supplier("sht30_i2c", "fast_sample", unit_price=1.6, lead_time=5, sample_days=1, yield_rate=1.0, on_time=1.0),
                _supplier("esp32_s3_n8r8", "slow_sample", unit_price=3.2, lead_time=5, sample_days=5, yield_rate=1.0, on_time=1.0),
                _supplier("esp32_s3_n8r8", "fast_sample", unit_price=4.2, lead_time=5, sample_days=1, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "refund_counter",
            "world_seed": 2313108,
            "product_id": "battery_sensor_refund_counter_holdout",
            "bom": {"bh1750_gy302": 1, "tp4056_usb_c_protected": 1},
            "objective": {"revenue": 8.0, "penalty": 3.0, "budget": 90.0, "deadline": 24, "minimum": 16, "defect_days": 20},
            "suppliers": [
                _supplier("bh1750_gy302", "counterable_returns", unit_price=0.85, yield_rate=0.9, refund_days=7, claim_acceptance=0.98, freight_payer="buyer", return_freight=0.25, floor_price=0.84, maximum_refund_days=45, supplier_paid_return_freight=True),
                _supplier("bh1750_gy302", "clean_fixed", unit_price=1.25, yield_rate=0.97, refund_days=30, floor_price=1.24),
                _supplier("tp4056_usb_c_protected", "counterable_returns", unit_price=0.72, yield_rate=0.9, refund_days=7, claim_acceptance=0.98, freight_payer="buyer", return_freight=0.2, floor_price=0.71, maximum_refund_days=45, supplier_paid_return_freight=True),
                _supplier("tp4056_usb_c_protected", "clean_fixed", unit_price=1.05, yield_rate=0.97, refund_days=30, floor_price=1.04),
            ],
        },
        {
            "slug": "payment_terms_counter",
            "world_seed": 2313109,
            "product_id": "encoder_clock_financing_holdout",
            "bom": {"ds3231_at24c32": 1, "ky040_encoder": 1},
            "objective": {"revenue": 8.0, "penalty": 3.0, "budget": 100.0, "deadline": 24, "capital_horizon": 180, "annual_rate": 2.0},
            "suppliers": [
                _supplier("ds3231_at24c32", "terms_flexible", unit_price=2.2, payment_days=1, maximum_payment_days=150, floor_price=2.18),
                _supplier("ds3231_at24c32", "terms_fixed", unit_price=2.5, payment_days=90, maximum_payment_days=90, floor_price=2.48),
                _supplier("ky040_encoder", "terms_flexible", unit_price=0.75, payment_days=1, maximum_payment_days=150, floor_price=0.74),
                _supplier("ky040_encoder", "terms_fixed", unit_price=0.95, payment_days=90, maximum_payment_days=90, floor_price=0.94),
            ],
        },
        {
            "slug": "on_time_reliability",
            "world_seed": 2313110,
            "product_id": "input_display_reliability_holdout",
            "bom": {"tactile_switch_6x6x5": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 8.0, "penalty": 5.0, "budget": 105.0, "deadline": 18, "minimum": 18},
            "suppliers": [
                _supplier("tactile_switch_6x6x5", "cheap_variable", unit_price=0.06, yield_rate=1.0, on_time=0.8),
                _supplier("tactile_switch_6x6x5", "reliable", unit_price=0.16, yield_rate=0.99, on_time=0.99),
                _supplier("ssd1306_oled_096", "cheap_variable", unit_price=0.95, yield_rate=1.0, on_time=0.8),
                _supplier("ssd1306_oled_096", "reliable", unit_price=1.75, yield_rate=0.99, on_time=0.99),
            ],
        },
        {
            "slug": "multi_unit_bom",
            "world_seed": 2313111,
            "product_id": "multi_channel_switch_board_holdout",
            "bom": {"mosfet_low_side_3v3": 2, "tactile_switch_6x6x5": 3},
            "objective": {"revenue": 11.0, "penalty": 4.0, "budget": 125.0, "deadline": 22, "minimum": 18},
            "suppliers": [
                _supplier("mosfet_low_side_3v3", "volume_exact", unit_price=0.72, capacity=60, moq=20, order_step=10, yield_rate=1.0, on_time=1.0),
                _supplier("mosfet_low_side_3v3", "small_lot", unit_price=0.6, capacity=30, moq=10, order_step=10, yield_rate=1.0, on_time=1.0),
                _supplier("tactile_switch_6x6x5", "volume_exact", unit_price=0.09, capacity=80, moq=20, order_step=10, yield_rate=1.0, on_time=1.0),
                _supplier("tactile_switch_6x6x5", "small_lot", unit_price=0.07, capacity=40, moq=10, order_step=10, yield_rate=1.0, on_time=1.0),
            ],
        },
        {
            "slug": "negotiated_moq",
            "world_seed": 2313112,
            "product_id": "control_sensor_moq_counter_holdout",
            "bom": {"ky023_joystick": 1, "bh1750_gy302": 1},
            "objective": {"revenue": 8.0, "penalty": 4.0, "budget": 70.0, "deadline": 24, "minimum": 18},
            "suppliers": [
                _supplier("ky023_joystick", "moq_flexible", unit_price=1.6, capacity=40, moq=30, order_step=10, floor_price=1.3, minimum_moq=20, yield_rate=1.0, on_time=1.0),
                _supplier("ky023_joystick", "small_fixed", unit_price=1.9, capacity=20, moq=20, order_step=10, floor_price=1.88, yield_rate=0.9, on_time=0.95),
                _supplier("bh1750_gy302", "moq_flexible", unit_price=1.2, capacity=40, moq=30, order_step=10, floor_price=0.9, minimum_moq=20, yield_rate=1.0, on_time=1.0),
                _supplier("bh1750_gy302", "small_fixed", unit_price=1.4, capacity=20, moq=20, order_step=10, floor_price=1.38, yield_rate=0.9, on_time=0.95),
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
