"""Generate held-out procurement worlds for the risk-gate factorial.

Three worlds expose confirmable sample logistics; three make formal landed cash
arithmetic decisive. Supplier economics are synthetic, while component-family
selection remains bound to the frozen 231-project grounding snapshot.
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
from .confirmatory_case_matrix import (
    LABELED_PATHS as CONFIRMATORY_LABELED_PATHS,
)
from .confirmatory_case_matrix import (
    OPAQUE_PATHS as CONFIRMATORY_OPAQUE_PATHS,
)
from .confirmatory_case_matrix import _supplier, economic_world_sha256
from .environment import ProcurementAllocationPlugin, solve_full_information_upper_bound


PANEL_ID = "procurement_allocation_risk_gate_factorial_v1"
GENERATOR_ID = "procurement_allocation_risk_gate_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
LABELED_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "risk_gates_v1"
    / "labeled"
)
OPAQUE_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "risk_gates_v1"
    / "opaque"
)
CASE_SLUGS = (
    "sample_schedule_symmetric",
    "sample_schedule_asymmetric",
    "sample_schedule_tight_slack",
    "landed_cash_freight",
    "landed_cash_duty",
    "landed_cash_moq",
)
STRATA_BY_SLUG = {
    slug: ("sample_timing" if slug.startswith("sample_") else "landed_cash")
    for slug in CASE_SLUGS
}
LABELED_PATHS = tuple(LABELED_ROOT / f"{slug}.json" for slug in CASE_SLUGS)
OPAQUE_PATHS = tuple(OPAQUE_ROOT / f"{slug}.json" for slug in CASE_SLUGS)


def _definitions() -> tuple[dict[str, Any], ...]:
    return (
        {
            "slug": "sample_schedule_symmetric",
            "world_seed": 2313201,
            "product_id": "telemetry_pair_sample_schedule_holdout_a",
            "bom": {"sht30_i2c": 1, "esp32_s3_n8r8": 1},
            "objective": {
                "revenue": 13.0,
                "penalty": 5.0,
                "budget": 155.0,
                "deadline": 13,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "sht30_i2c",
                    "economy_sample_a",
                    unit_price=1.0,
                    lead_time=4,
                    sample_days=4,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "sht30_i2c",
                    "expedite_sample_a",
                    unit_price=1.6,
                    lead_time=4,
                    sample_days=1,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "esp32_s3_n8r8",
                    "economy_sample_a",
                    unit_price=3.2,
                    lead_time=4,
                    sample_days=4,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "esp32_s3_n8r8",
                    "expedite_sample_a",
                    unit_price=4.1,
                    lead_time=4,
                    sample_days=1,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
            ],
        },
        {
            "slug": "sample_schedule_asymmetric",
            "world_seed": 2313202,
            "product_id": "battery_sensor_sample_schedule_holdout_b",
            "bom": {"bh1750_gy302": 1, "tp4056_usb_c_protected": 1},
            "objective": {
                "revenue": 9.0,
                "penalty": 4.0,
                "budget": 110.0,
                "deadline": 13,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "bh1750_gy302",
                    "economy_sample_b",
                    unit_price=0.62,
                    lead_time=3,
                    sample_days=5,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "bh1750_gy302",
                    "expedite_sample_b",
                    unit_price=1.0,
                    lead_time=3,
                    sample_days=1,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "tp4056_usb_c_protected",
                    "economy_sample_b",
                    unit_price=0.48,
                    lead_time=5,
                    sample_days=4,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "tp4056_usb_c_protected",
                    "expedite_sample_b",
                    unit_price=0.9,
                    lead_time=5,
                    sample_days=1,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
            ],
        },
        {
            "slug": "sample_schedule_tight_slack",
            "world_seed": 2313203,
            "product_id": "clock_encoder_sample_schedule_holdout_c",
            "bom": {"ds3231_at24c32": 1, "ky040_encoder": 1},
            "objective": {
                "revenue": 9.0,
                "penalty": 4.0,
                "budget": 125.0,
                "deadline": 15,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "ds3231_at24c32",
                    "economy_sample_c",
                    unit_price=1.8,
                    lead_time=4,
                    sample_days=6,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "ds3231_at24c32",
                    "expedite_sample_c",
                    unit_price=2.5,
                    lead_time=4,
                    sample_days=2,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "ky040_encoder",
                    "economy_sample_c",
                    unit_price=0.55,
                    lead_time=4,
                    sample_days=6,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "ky040_encoder",
                    "expedite_sample_c",
                    unit_price=0.95,
                    lead_time=4,
                    sample_days=2,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
            ],
        },
        {
            "slug": "landed_cash_freight",
            "world_seed": 2313204,
            "product_id": "display_gateway_landed_cash_holdout_d",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {
                "revenue": 12.0,
                "penalty": 4.0,
                "budget": 168.0,
                "deadline": 20,
                "minimum": 16,
            },
            "suppliers": [
                _supplier(
                    "esp32_s3_n8r8",
                    "low_sticker_d",
                    unit_price=2.9,
                    shipping=2.5,
                    duty_rate=0.18,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "esp32_s3_n8r8",
                    "landed_clear_d",
                    unit_price=4.1,
                    shipping=0.1,
                    duty_rate=0.02,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "ssd1306_oled_096",
                    "low_sticker_d",
                    unit_price=0.85,
                    shipping=1.15,
                    duty_rate=0.18,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "ssd1306_oled_096",
                    "landed_clear_d",
                    unit_price=1.45,
                    shipping=0.1,
                    duty_rate=0.02,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
            ],
        },
        {
            "slug": "landed_cash_duty",
            "world_seed": 2313205,
            "product_id": "control_board_landed_cash_holdout_e",
            "bom": {"mosfet_low_side_3v3": 1, "tactile_switch_6x6x5": 2},
            "objective": {
                "revenue": 8.0,
                "penalty": 4.0,
                "budget": 50.0,
                "deadline": 22,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "mosfet_low_side_3v3",
                    "low_sticker_e",
                    unit_price=0.58,
                    shipping=0.65,
                    duty_rate=0.35,
                    capacity=50,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "mosfet_low_side_3v3",
                    "landed_clear_e",
                    unit_price=0.92,
                    shipping=0.05,
                    duty_rate=0.02,
                    capacity=50,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "tactile_switch_6x6x5",
                    "low_sticker_e",
                    unit_price=0.06,
                    shipping=0.35,
                    duty_rate=0.35,
                    capacity=80,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "tactile_switch_6x6x5",
                    "landed_clear_e",
                    unit_price=0.13,
                    shipping=0.03,
                    duty_rate=0.02,
                    capacity=80,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
            ],
        },
        {
            "slug": "landed_cash_moq",
            "world_seed": 2313206,
            "product_id": "operator_sensor_landed_cash_holdout_f",
            "bom": {"ky023_joystick": 1, "bh1750_gy302": 1},
            "objective": {
                "revenue": 9.0,
                "penalty": 4.0,
                "budget": 80.0,
                "deadline": 22,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "ky023_joystick",
                    "low_sticker_f",
                    unit_price=1.2,
                    shipping=0.3,
                    duty_rate=0.15,
                    moq=30,
                    order_step=10,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "ky023_joystick",
                    "landed_clear_f",
                    unit_price=1.7,
                    shipping=0.05,
                    duty_rate=0.02,
                    moq=20,
                    order_step=10,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "bh1750_gy302",
                    "low_sticker_f",
                    unit_price=0.7,
                    shipping=0.25,
                    duty_rate=0.15,
                    moq=30,
                    order_step=10,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
                _supplier(
                    "bh1750_gy302",
                    "landed_clear_f",
                    unit_price=1.1,
                    shipping=0.05,
                    duty_rate=0.02,
                    moq=20,
                    order_step=10,
                    yield_rate=1.0,
                    on_time=1.0,
                ),
            ],
        },
    )


def _build_case(definition: Mapping[str, Any], *, surface: str) -> dict[str, Any]:
    if surface not in {"labeled", "opaque"}:
        raise ValueError("surface must be labeled or opaque")
    knobs = definition["objective"]
    inquiry_fields = [
        "exact_variant",
        "moq_capacity",
        "lead_time",
        "shipping",
        "quality",
        "return_refund_policy",
    ]
    if STRATA_BY_SLUG[str(definition["slug"])] == "sample_timing":
        inquiry_fields.insert(5, "sample_logistics")
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": (
            "procurement_allocation_v1.risk_gates_v1_"
            f"{surface}.{definition['slug']}"
        ),
        "family_id": "procurement_allocation_v1",
        "family_version": "1.0.0",
        "split": f"risk_gates_v1_{surface}",
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
        "visibility_policy": (
            "procurement_allocation_public_listings_private_supplier_terms_v1"
        ),
        "payload": {
            "objective": {
                "product_id": definition["product_id"],
                "target_kits": 20,
                "minimum_service_kits": knobs["minimum"],
                "revenue_per_completed_kit_usd": knobs["revenue"],
                "shortfall_penalty_per_kit_usd": knobs["penalty"],
                "cash_budget_usd": knobs["budget"],
                "deadline_days": knobs["deadline"],
                "defect_detection_days": 10,
                "working_capital_horizon_days": 45,
                "annual_financing_rate": 0.12,
                "defer_value_usd": 0.0,
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
                "inquiry_fields": inquiry_fields,
                "award_requires": [
                    "unexpired_formal_offer",
                    "verified_sample",
                    "exact_variant",
                ],
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


def build_risk_gate_case_matrix(*, surface: str) -> tuple[dict[str, Any], ...]:
    validate_grounding_snapshot()
    cases = tuple(_build_case(definition, surface=surface) for definition in _definitions())
    if len(cases) != 6 or len({case["world_seed"] for case in cases}) != len(cases):
        raise AssertionError("risk-gate panel requires six distinct worlds")
    prior_paths = (
        *CASE_VARIANCE_PATHS,
        *CONFIRMATORY_LABELED_PATHS,
        *CONFIRMATORY_OPAQUE_PATHS,
    )
    prior_digests = {
        CaseManifest.from_dict(json.loads(path.read_text())).content_sha256
        for path in prior_paths
    }
    if prior_digests.intersection(case["content_sha256"] for case in cases):
        raise AssertionError("risk-gate cases reuse a prior case digest")
    used_components = {
        component
        for case in cases
        for component in case["payload"]["objective"]["bom"]
    }
    if not used_components <= set(GROUNDING_SELECTION):
        raise AssertionError("risk-gate component is absent from grounding selection")
    return cases


def write_risk_gate_case_matrix(
    *, surface: str, root: Path | None = None
) -> tuple[Path, ...]:
    destination = root or (LABELED_ROOT if surface == "labeled" else OPAQUE_ROOT)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in build_risk_gate_case_matrix(surface=surface):
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
    cases = build_risk_gate_case_matrix(surface=arguments.surface)
    if arguments.write:
        for path in write_risk_gate_case_matrix(surface=arguments.surface):
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
    "STRATA_BY_SLUG",
    "build_risk_gate_case_matrix",
    "economic_world_sha256",
    "write_risk_gate_case_matrix",
]
