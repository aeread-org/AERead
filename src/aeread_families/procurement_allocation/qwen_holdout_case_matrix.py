"""Generate the targeted opaque Qwen procurement holdout panel.

The six worlds are new relative to every earlier procurement-allocation panel.
They target the residual failures observed after the frozen Qwen constraint-ledger
V2 repair: split capacity, order-step arithmetic, minimum-service allocations,
and evidence-grounded use of opaque supplier identifiers.  The panel is frozen
before live execution and is a targeted diagnostic, not a population sample.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
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
from .risk_gate_case_matrix import LABELED_PATHS as RISK_GATE_LABELED_PATHS
from .risk_gate_case_matrix import OPAQUE_PATHS as RISK_GATE_OPAQUE_PATHS


PANEL_ID = "procurement_allocation_qwen_holdout_v1"
GENERATOR_ID = "procurement_allocation_qwen_holdout_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
OPAQUE_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "qwen_holdout_v1"
    / "opaque"
)
CASE_SLUGS = (
    "split_capacity_steps",
    "split_capacity_asymmetric",
    "dual_component_split",
    "multi_unit_split",
    "minimum_service_capacity",
    "minimum_service_budget",
)
STRATA_BY_SLUG = {
    "split_capacity_steps": "single_component_split",
    "split_capacity_asymmetric": "single_component_split",
    "dual_component_split": "dual_component_split",
    "multi_unit_split": "multi_unit_bom_split",
    "minimum_service_capacity": "minimum_service_capacity",
    "minimum_service_budget": "minimum_service_budget",
}
OPAQUE_PATHS = tuple(OPAQUE_ROOT / f"{slug}.json" for slug in CASE_SLUGS)
PRIOR_PATHS = (
    *CASE_VARIANCE_PATHS,
    *CONFIRMATORY_LABELED_PATHS,
    *CONFIRMATORY_OPAQUE_PATHS,
    *RISK_GATE_LABELED_PATHS,
    *RISK_GATE_OPAQUE_PATHS,
)


def _definitions() -> tuple[dict[str, Any], ...]:
    reliable = {"yield_rate": 1.0, "on_time": 1.0, "sample_days": 1}
    return (
        {
            "slug": "split_capacity_steps",
            "world_seed": 2313301,
            "product_id": "encoder_panel_split_steps_qwen_holdout",
            "bom": {"ky040_encoder": 1, "tactile_switch_6x6x5": 1},
            "objective": {
                "revenue": 8.0,
                "penalty": 4.0,
                "budget": 75.0,
                "deadline": 20,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "ky040_encoder",
                    "step_split_a",
                    unit_price=0.62,
                    capacity=10,
                    moq=5,
                    order_step=5,
                    **reliable,
                ),
                _supplier(
                    "ky040_encoder",
                    "step_split_b",
                    unit_price=0.68,
                    capacity=10,
                    moq=5,
                    order_step=5,
                    **reliable,
                ),
                _supplier(
                    "tactile_switch_6x6x5",
                    "full_capacity",
                    unit_price=0.11,
                    capacity=20,
                    moq=10,
                    order_step=5,
                    **reliable,
                ),
            ],
        },
        {
            "slug": "split_capacity_asymmetric",
            "world_seed": 2313302,
            "product_id": "sensor_pair_asymmetric_split_qwen_holdout",
            "bom": {"sht30_i2c": 1, "bh1750_gy302": 1},
            "objective": {
                "revenue": 9.0,
                "penalty": 4.0,
                "budget": 90.0,
                "deadline": 20,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "sht30_i2c",
                    "asymmetric_twelve",
                    unit_price=1.15,
                    capacity=12,
                    moq=4,
                    order_step=4,
                    **reliable,
                ),
                _supplier(
                    "sht30_i2c",
                    "asymmetric_eight",
                    unit_price=1.25,
                    capacity=8,
                    moq=4,
                    order_step=4,
                    **reliable,
                ),
                _supplier(
                    "bh1750_gy302",
                    "full_capacity",
                    unit_price=0.82,
                    capacity=20,
                    moq=10,
                    order_step=5,
                    **reliable,
                ),
            ],
        },
        {
            "slug": "dual_component_split",
            "world_seed": 2313303,
            "product_id": "operator_clock_dual_split_qwen_holdout",
            "bom": {"ds3231_at24c32": 1, "ky023_joystick": 1},
            "objective": {
                "revenue": 10.0,
                "penalty": 5.0,
                "budget": 115.0,
                "deadline": 20,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "ds3231_at24c32",
                    "dual_a",
                    unit_price=1.7,
                    capacity=10,
                    moq=5,
                    order_step=5,
                    **reliable,
                ),
                _supplier(
                    "ds3231_at24c32",
                    "dual_b",
                    unit_price=1.8,
                    capacity=10,
                    moq=5,
                    order_step=5,
                    **reliable,
                ),
                _supplier(
                    "ky023_joystick",
                    "dual_a",
                    unit_price=1.25,
                    capacity=10,
                    moq=5,
                    order_step=5,
                    **reliable,
                ),
                _supplier(
                    "ky023_joystick",
                    "dual_b",
                    unit_price=1.35,
                    capacity=10,
                    moq=5,
                    order_step=5,
                    **reliable,
                ),
            ],
        },
        {
            "slug": "multi_unit_split",
            "world_seed": 2313304,
            "product_id": "multi_channel_control_split_qwen_holdout",
            "bom": {"mosfet_low_side_3v3": 2, "tactile_switch_6x6x5": 3},
            "objective": {
                "revenue": 11.0,
                "penalty": 5.0,
                "budget": 95.0,
                "deadline": 20,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "mosfet_low_side_3v3",
                    "multi_split_a",
                    unit_price=0.58,
                    capacity=20,
                    moq=10,
                    order_step=10,
                    **reliable,
                ),
                _supplier(
                    "mosfet_low_side_3v3",
                    "multi_split_b",
                    unit_price=0.64,
                    capacity=20,
                    moq=10,
                    order_step=10,
                    **reliable,
                ),
                _supplier(
                    "tactile_switch_6x6x5",
                    "multi_full",
                    unit_price=0.09,
                    capacity=60,
                    moq=20,
                    order_step=10,
                    **reliable,
                ),
            ],
        },
        {
            "slug": "minimum_service_capacity",
            "world_seed": 2313305,
            "product_id": "display_gateway_minimum_capacity_qwen_holdout",
            "bom": {"ssd1306_oled_096": 1, "esp32_s3_n8r8": 1},
            "objective": {
                "revenue": 14.0,
                "penalty": 4.0,
                "budget": 140.0,
                "deadline": 20,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "ssd1306_oled_096",
                    "minimum_a",
                    unit_price=1.35,
                    capacity=9,
                    moq=9,
                    order_step=9,
                    **reliable,
                ),
                _supplier(
                    "ssd1306_oled_096",
                    "minimum_b",
                    unit_price=1.45,
                    capacity=9,
                    moq=9,
                    order_step=9,
                    **reliable,
                ),
                _supplier(
                    "esp32_s3_n8r8",
                    "minimum_a",
                    unit_price=3.65,
                    capacity=9,
                    moq=9,
                    order_step=9,
                    **reliable,
                ),
                _supplier(
                    "esp32_s3_n8r8",
                    "minimum_b",
                    unit_price=3.8,
                    capacity=9,
                    moq=9,
                    order_step=9,
                    **reliable,
                ),
            ],
        },
        {
            "slug": "minimum_service_budget",
            "world_seed": 2313306,
            "product_id": "battery_sensor_minimum_budget_qwen_holdout",
            "bom": {"tp4056_usb_c_protected": 1, "bh1750_gy302": 1},
            "objective": {
                "revenue": 9.0,
                "penalty": 4.0,
                "budget": 50.0,
                "deadline": 20,
                "minimum": 18,
            },
            "suppliers": [
                _supplier(
                    "tp4056_usb_c_protected",
                    "low_sticker_freight",
                    unit_price=0.3,
                    shipping=1.0,
                    duty_rate=0.2,
                    capacity=20,
                    moq=2,
                    order_step=2,
                    **reliable,
                ),
                _supplier(
                    "tp4056_usb_c_protected",
                    "landed_clear",
                    unit_price=1.0,
                    shipping=0.05,
                    duty_rate=0.05,
                    capacity=20,
                    moq=2,
                    order_step=2,
                    **reliable,
                ),
                _supplier(
                    "bh1750_gy302",
                    "low_sticker_freight",
                    unit_price=0.6,
                    shipping=1.0,
                    duty_rate=0.2,
                    capacity=20,
                    moq=2,
                    order_step=2,
                    **reliable,
                ),
                _supplier(
                    "bh1750_gy302",
                    "landed_clear",
                    unit_price=1.4,
                    shipping=0.05,
                    duty_rate=0.05,
                    capacity=20,
                    moq=2,
                    order_step=2,
                    **reliable,
                ),
            ],
        },
    )


def _build_case(definition: Mapping[str, Any]) -> dict[str, Any]:
    knobs = definition["objective"]
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": (
            "procurement_allocation_v1.qwen_holdout_v1_opaque."
            f"{definition['slug']}"
        ),
        "family_id": "procurement_allocation_v1",
        "family_version": "1.0.0",
        "split": "qwen_holdout_v1_opaque",
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
            "suppliers": copy.deepcopy(definition["suppliers"]),
        },
        "provenance": {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
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


def build_qwen_holdout_case_matrix() -> tuple[dict[str, Any], ...]:
    validate_grounding_snapshot()
    cases = tuple(_build_case(definition) for definition in _definitions())
    if len(cases) != 6 or len({case["world_seed"] for case in cases}) != len(cases):
        raise AssertionError("Qwen holdout requires six distinct worlds")
    prior = [json.loads(path.read_text(encoding="utf-8")) for path in PRIOR_PATHS]
    prior_content_digests = {case["content_sha256"] for case in prior}
    prior_world_digests = {economic_world_sha256(case) for case in prior}
    if prior_content_digests.intersection(case["content_sha256"] for case in cases):
        raise AssertionError("Qwen holdout reuses a prior case digest")
    if prior_world_digests.intersection(economic_world_sha256(case) for case in cases):
        raise AssertionError("Qwen holdout reuses a prior economic world")
    used_components = {
        component
        for case in cases
        for component in case["payload"]["objective"]["bom"]
    }
    if not used_components <= set(GROUNDING_SELECTION):
        raise AssertionError("Qwen holdout component is absent from grounding selection")
    return cases


def write_qwen_holdout_case_matrix(*, root: Path | None = None) -> tuple[Path, ...]:
    destination = root or OPAQUE_ROOT
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in build_qwen_holdout_case_matrix():
        path = destination / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        payload = json.dumps(case, indent=2, sort_keys=True) + "\n"
        temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
        written.append(path)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    cases = build_qwen_holdout_case_matrix()
    if arguments.write:
        for path in write_qwen_holdout_case_matrix():
            print(path)
    else:
        print(json.dumps(cases, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_SLUGS",
    "OPAQUE_PATHS",
    "PANEL_ID",
    "PRIOR_PATHS",
    "STRATA_BY_SLUG",
    "build_qwen_holdout_case_matrix",
    "write_qwen_holdout_case_matrix",
]
