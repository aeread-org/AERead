"""Generate the six-case procurement-allocation variance panel.

Component selection is pinned to the frozen 231-project grounding snapshot.
Supplier identities and economics are synthetic: they create controlled decision
problems and must not be interpreted as current marketplace offers.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import ProcurementAllocationPlugin, solve_full_information_upper_bound


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / "dev"
GROUNDING_PATH = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_grounding_v1"
    / "dev"
    / "procurement_grounding_231_projects.json"
)

CASE_SLUGS = (
    "deadline_cost",
    "quality_refund",
    "moq_capacity_split",
    "working_capital",
    "variant_substitution",
    "service_defer",
)
CASE_VARIANCE_PATHS = tuple(CASE_ROOT / f"{slug}.json" for slug in CASE_SLUGS)

GROUNDING_SELECTION = {
    "tactile_switch_6x6x5": (39, 81, 79),
    "ssd1306_oled_096": (49, 49, 69),
    "tp4056_usb_c_protected": (17, 18, 52),
    "mosfet_low_side_3v3": (7, 14, 47),
    "ky040_encoder": (7, 8, 42),
    "esp32_s3_n8r8": (3, 3, 38),
    "ky023_joystick": (7, 8, 37),
    "ds3231_at24c32": (3, 3, 33),
    "bh1750_gy302": (2, 3, 32),
    "sht30_i2c": (1, 2, 31),
}

REQUIRED_VARIANTS = {
    "tactile_switch_6x6x5": "6x6x5mm_four_pin_normally_open",
    "ssd1306_oled_096": "096in_128x64_four_pin_i2c_ssd1306",
    "tp4056_usb_c_protected": "usb_c_dw01a_8205a_separate_bat_out",
    "mosfet_low_side_3v3": "3v3_logic_level_low_side_module",
    "ky040_encoder": "ec11_ky040_module_with_pullups",
    "esp32_s3_n8r8": "esp32_s3_devkitc_1_n8r8",
    "ky023_joystick": "ky023_dual_axis_push_switch_module",
    "ds3231_at24c32": "ds3231_at24c32_i2c_module",
    "bh1750_gy302": "bh1750_gy302_i2c_module",
    "sht30_i2c": "sht30_i2c_module_3v3",
}


def validate_grounding_snapshot(
    path: Path | str = GROUNDING_PATH,
) -> dict[str, Mapping[str, Any]]:
    """Verify the frozen demand proxies used to choose the panel's BOMs."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    counts = raw["payload"]["oracle"]["source_counts"]
    if (counts["projects"], counts["bom_rows"]) != (231, 1156):
        raise ValueError("procurement grounding snapshot population changed")
    rows = {
        row["family_id"]: row
        for row in raw["payload"]["visible_evidence"]["priority_matrix"]
    }
    for family_id, expected in GROUNDING_SELECTION.items():
        row = rows.get(family_id)
        actual = None if row is None else (
            row["projects"],
            row["bom_rows"],
            row["priority_score"],
        )
        if actual != expected:
            raise ValueError(
                f"grounding facts changed for {family_id}: {actual!r} != {expected!r}"
            )
    return {family_id: rows[family_id] for family_id in GROUNDING_SELECTION}


def _supplier(
    component: str,
    label: str,
    *,
    unit_price: float,
    lead_time: int = 7,
    on_time: float = 0.99,
    yield_rate: float = 0.99,
    capacity: int = 20,
    moq: int = 10,
    order_step: int = 10,
    payment_days: int = 30,
    shipping: float = 0.05,
    sample_cost: float = 0.4,
    sample_days: int = 1,
    variant: str | None = None,
    refund_days: int = 30,
    claim_acceptance: float = 0.95,
    restocking_rate: float = 0.0,
    freight_payer: str = "supplier",
    return_freight: float = 0.0,
    refund_delay: int = 5,
) -> dict[str, Any]:
    supplier_id = f"{component}_{label}"
    exact_variant = variant or REQUIRED_VARIANTS[component]
    floor = round(unit_price * 0.94, 6)
    return {
        "supplier_id": supplier_id,
        "component": component,
        "listing": {
            "supplier_name": f"Synthetic {component} {label} supplier",
            "displayed_unit_price_usd": round(unit_price * 0.88, 6),
            "claimed_lead_time_days": max(1, lead_time - 2),
            "claimed_variant": exact_variant.replace("_", " "),
            "evidence_status": "marketplace_listing_unverified",
        },
        "private_terms": {
            "variant_id": exact_variant,
            "base_unit_price_usd": unit_price,
            "shipping_per_unit_usd": shipping,
            "duty_rate": 0.05,
            "capacity": capacity,
            "moq": moq,
            "order_step": order_step,
            "lead_time_days": lead_time,
            "on_time_probability": on_time,
            "payment_terms_days": payment_days,
            "offer_valid_days": 30,
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
                "floor_unit_price_usd": floor,
                "minimum_moq": moq,
                "maximum_payment_terms_days": max(payment_days, 60),
                "maximum_refund_window_days": max(refund_days, 45),
                "supplier_paid_return_freight_available": freight_payer == "supplier",
            },
        },
    }


def _definitions() -> tuple[dict[str, Any], ...]:
    return (
        {
            "slug": "deadline_cost",
            "world_seed": 2312001,
            "product_id": "display_controller_deadline_pilot",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 10.0, "penalty": 3.0, "budget": 150.0, "deadline": 14},
            "suppliers": [
                _supplier("esp32_s3_n8r8", "value", unit_price=3.20, lead_time=20, on_time=0.95, yield_rate=0.98),
                _supplier("esp32_s3_n8r8", "express", unit_price=4.35, lead_time=5, on_time=0.995, yield_rate=0.995),
                _supplier("ssd1306_oled_096", "value", unit_price=1.20, lead_time=19, on_time=0.94, yield_rate=0.97),
                _supplier("ssd1306_oled_096", "express", unit_price=1.85, lead_time=4, on_time=0.995, yield_rate=0.995),
            ],
        },
        {
            "slug": "quality_refund",
            "world_seed": 2312002,
            "product_id": "environment_sensor_quality_pilot",
            "bom": {"sht30_i2c": 1, "bh1750_gy302": 1},
            "objective": {"revenue": 7.0, "penalty": 4.0, "budget": 100.0, "deadline": 24, "defect_days": 12},
            "suppliers": [
                _supplier("sht30_i2c", "value", unit_price=1.05, yield_rate=0.84, refund_days=7, claim_acceptance=0.45, restocking_rate=0.15, freight_payer="buyer", return_freight=0.25),
                _supplier("sht30_i2c", "assured", unit_price=1.75, yield_rate=0.995, refund_days=45, claim_acceptance=0.99),
                _supplier("bh1750_gy302", "value", unit_price=0.60, yield_rate=0.83, refund_days=7, claim_acceptance=0.40, restocking_rate=0.15, freight_payer="buyer", return_freight=0.20),
                _supplier("bh1750_gy302", "assured", unit_price=1.15, yield_rate=0.995, refund_days=45, claim_acceptance=0.99),
            ],
        },
        {
            "slug": "moq_capacity_split",
            "world_seed": 2312003,
            "product_id": "control_panel_capacity_pilot",
            "bom": {"tactile_switch_6x6x5": 1, "ky040_encoder": 1},
            "objective": {"revenue": 5.0, "penalty": 2.0, "budget": 100.0, "deadline": 24, "minimum": 18},
            "suppliers": [
                _supplier("tactile_switch_6x6x5", "lot_a", unit_price=0.07, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("tactile_switch_6x6x5", "lot_b", unit_price=0.08, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("ky040_encoder", "lot_a", unit_price=0.55, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
                _supplier("ky040_encoder", "lot_b", unit_price=0.60, capacity=10, moq=5, order_step=5, yield_rate=1.0, on_time=1.0, sample_cost=0.2),
            ],
        },
        {
            "slug": "working_capital",
            "world_seed": 2312004,
            "product_id": "connected_clock_financing_pilot",
            "bom": {"ds3231_at24c32": 1, "esp32_s3_n8r8": 1},
            "objective": {"revenue": 12.0, "penalty": 2.0, "budget": 180.0, "deadline": 24, "annual_rate": 1.5, "capital_horizon": 90},
            "suppliers": [
                _supplier("ds3231_at24c32", "prepay", unit_price=1.15, payment_days=1),
                _supplier("ds3231_at24c32", "net_terms", unit_price=1.35, payment_days=90),
                _supplier("esp32_s3_n8r8", "prepay", unit_price=3.90, payment_days=1),
                _supplier("esp32_s3_n8r8", "net_terms", unit_price=4.30, payment_days=90),
            ],
        },
        {
            "slug": "variant_substitution",
            "world_seed": 2312005,
            "product_id": "protected_power_driver_variant_pilot",
            "bom": {"tp4056_usb_c_protected": 1, "mosfet_low_side_3v3": 1},
            "objective": {"revenue": 6.0, "penalty": 3.0, "budget": 100.0, "deadline": 24},
            "suppliers": [
                _supplier("tp4056_usb_c_protected", "near_match", unit_price=0.30, variant="micro_usb_tp4056_unprotected"),
                _supplier("tp4056_usb_c_protected", "exact", unit_price=0.62),
                _supplier("mosfet_low_side_3v3", "near_match", unit_price=0.18, variant="five_volt_gate_threshold_module"),
                _supplier("mosfet_low_side_3v3", "exact", unit_price=0.48),
            ],
        },
        {
            "slug": "service_defer",
            "world_seed": 2312006,
            "product_id": "input_display_service_pilot",
            "bom": {"ky023_joystick": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 5.0, "penalty": 1.5, "budget": 100.0, "deadline": 18, "minimum": 18, "defer": 3.0},
            "suppliers": [
                _supplier("ky023_joystick", "risky", unit_price=0.75, yield_rate=0.76, on_time=0.92),
                _supplier("ky023_joystick", "service", unit_price=1.80, yield_rate=0.98, on_time=0.98),
                _supplier("ssd1306_oled_096", "risky", unit_price=1.05, yield_rate=0.78, on_time=0.92),
                _supplier("ssd1306_oled_096", "service", unit_price=2.10, yield_rate=0.98, on_time=0.98),
            ],
        },
    )


def _build_case(definition: Mapping[str, Any]) -> dict[str, Any]:
    knobs = definition["objective"]
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"procurement_allocation_v1.dev.{definition['slug']}",
        "family_id": "procurement_allocation_v1",
        "family_version": "1.0.0",
        "split": "dev",
        "world_seed": definition["world_seed"],
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {
            "max_logical_actions": 10,
            "termination": [
                "submitted",
                "deferred",
                "interaction_budget_exhausted",
                "invalid_action",
            ],
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
                "inquiry_fields": [
                    "exact_variant",
                    "moq_capacity",
                    "lead_time",
                    "shipping",
                    "quality",
                    "return_refund_policy",
                ],
                "award_requires": [
                    "unexpired_formal_offer",
                    "verified_sample",
                    "exact_variant",
                ],
            },
            "suppliers": definition["suppliers"],
        },
        "provenance": {
            "generator_id": "procurement_allocation_case_matrix_v2",
            "generator_version": "2.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    draft = CaseManifest.from_dict(raw)
    ProcurementAllocationPlugin().validate_payload(draft.payload)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError(f"unstable case digest for {case.case_id}")
    bound = solve_full_information_upper_bound(case.payload)
    if bound.contribution_margin_usd <= case.payload["objective"]["defer_value_usd"]:
        raise ValueError(f"{case.case_id} has no beneficial feasible award")
    return raw


def build_case_matrix() -> tuple[dict[str, Any], ...]:
    validate_grounding_snapshot()
    cases = tuple(_build_case(definition) for definition in _definitions())
    if len({case["world_seed"] for case in cases}) != len(CASE_SLUGS):
        raise AssertionError("case worlds must use distinct generation seeds")
    return cases


def write_case_matrix(root: Path | str = CASE_ROOT) -> tuple[Path, ...]:
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in build_case_matrix():
        path = destination / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        written.append(path)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    cases = build_case_matrix()
    if arguments.write:
        for path in write_case_matrix():
            print(path)
    else:
        print(json.dumps(cases, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_SLUGS",
    "CASE_VARIANCE_PATHS",
    "GROUNDING_PATH",
    "GROUNDING_SELECTION",
    "build_case_matrix",
    "validate_grounding_snapshot",
    "write_case_matrix",
]
