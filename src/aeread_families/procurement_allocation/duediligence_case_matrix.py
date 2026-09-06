"""Due-diligence worlds: verification is scarce and the listing overstates.

The positioning decision of 2026-09-06 scopes this family to the value of
information before an irreversible commitment. Two structural conditions make
that measurable, and neither held in any earlier panel:

- **Verification is scarce.** Six suppliers against a seven-action budget. Quoting
  every supplier costs six actions and leaves nothing for sampling or the award,
  so the buyer must choose whom to investigate on the strength of the listing.
- **The listing overstates.** ``verbal_bias`` now drives the public listing, which
  every evaluated policy reads; formal offers and verified samples stay truthful.
  A screen recorded zero ``inquire`` actions across a whole panel, so biasing only
  the verbal reply was inert.

Each world hides its defect behind an attractive listing: the cheapest-looking
supplier is the one whose true yield, lead time, or capacity fails the objective.
Working capital, refund financing, and negotiation are deliberately absent --
they are immaterial at this scale and are owned by other families.
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


PANEL_ID = "procurement_allocation_duediligence_v1"
GENERATOR_ID = "procurement_allocation_duediligence_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
LABELED_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "duediligence_v1"
    / "labeled"
)
OPAQUE_ROOT = (
    REPOSITORY_ROOT
    / "cases"
    / "procurement_allocation_v1"
    / "duediligence_v1"
    / "opaque"
)
CASE_SLUGS = (
    "cheap_listing_hides_yield",
    "cheap_listing_hides_lead_time",
    "cheap_listing_hides_capacity",
    "two_traps_one_budget",
    "honest_premium_is_correct",
    "decoy_variant_and_yield",
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
    # Seven actions against six suppliers: quoting everyone costs six and leaves
    # nothing for a sample or the award, so whom to investigate is a decision.
    lean = {"inquiry": 0.05, "quote": 0.1, "counter": 0.15}
    return (
        {
            "slug": "cheap_listing_hides_yield",
            "world_seed": 2614101,
            "product_id": "duediligence_yield",
            "bom": {"sht30_i2c": 1, "bh1750_gy302": 1},
            "budget_actions": 7,
            "objective": {"revenue": 10.0, "penalty": 4.0, "budget": 200.0, "deadline": 20, "minimum": 18},
            "interaction": lean,
            "suppliers": [
                _supplier("sht30_i2c", "bargain_trap", unit_price=0.7, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.78, verbal_bias={'verified_yield_rate': 0.99}),
                _supplier("sht30_i2c", "mid_honest", unit_price=1.3, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.99),
                _supplier("sht30_i2c", "premium_honest", unit_price=1.8, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.995),
                _supplier("bh1750_gy302", "bargain_trap", unit_price=0.45, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.78, verbal_bias={'verified_yield_rate': 0.99}),
                _supplier("bh1750_gy302", "mid_honest", unit_price=0.9, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.99),
                _supplier("bh1750_gy302", "premium_honest", unit_price=1.25, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.995),
            ],
        },
        {
            "slug": "cheap_listing_hides_lead_time",
            "world_seed": 2614102,
            "product_id": "duediligence_lead_time",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "budget_actions": 7,
            "objective": {"revenue": 13.0, "penalty": 4.0, "budget": 240.0, "deadline": 12, "minimum": 18},
            "interaction": lean,
            "suppliers": [
                _supplier("esp32_s3_n8r8", "bargain_trap", unit_price=2.6, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=16, verbal_bias={'lead_time_days': 5}),
                _supplier("esp32_s3_n8r8", "mid_honest", unit_price=3.4, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=6),
                _supplier("esp32_s3_n8r8", "premium_honest", unit_price=4.1, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=4),
                _supplier("ssd1306_oled_096", "bargain_trap", unit_price=0.85, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=16, verbal_bias={'lead_time_days': 5}),
                _supplier("ssd1306_oled_096", "mid_honest", unit_price=1.35, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=6),
                _supplier("ssd1306_oled_096", "premium_honest", unit_price=1.75, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=4),
            ],
        },
        {
            "slug": "cheap_listing_hides_capacity",
            "world_seed": 2614103,
            "product_id": "duediligence_capacity",
            "bom": {"tactile_switch_6x6x5": 1, "ky040_encoder": 1},
            "budget_actions": 7,
            "objective": {"revenue": 9.0, "penalty": 3.0, "budget": 200.0, "deadline": 22, "minimum": 18},
            "interaction": lean,
            "suppliers": [
                _supplier("tactile_switch_6x6x5", "bargain_trap", unit_price=0.09, capacity=20, moq=10, order_step=10, sample_cost=0.4, verbal_bias={'capacity': 20}),
                _supplier("tactile_switch_6x6x5", "mid_honest", unit_price=0.15, capacity=20, moq=10, order_step=10, sample_cost=0.4),
                _supplier("tactile_switch_6x6x5", "premium_honest", unit_price=0.2, capacity=20, moq=10, order_step=10, sample_cost=0.4),
                _supplier("ky040_encoder", "bargain_trap", unit_price=0.55, capacity=20, moq=10, order_step=10, sample_cost=0.4, verbal_bias={'capacity': 20}),
                _supplier("ky040_encoder", "mid_honest", unit_price=0.85, capacity=20, moq=10, order_step=10, sample_cost=0.4),
                _supplier("ky040_encoder", "premium_honest", unit_price=1.1, capacity=20, moq=10, order_step=10, sample_cost=0.4),
            ],
        },
        {
            "slug": "two_traps_one_budget",
            "world_seed": 2614104,
            "product_id": "duediligence_two_traps",
            "bom": {"tp4056_usb_c_protected": 1, "mosfet_low_side_3v3": 1},
            "budget_actions": 7,
            "objective": {"revenue": 9.0, "penalty": 4.0, "budget": 200.0, "deadline": 14, "minimum": 18},
            "interaction": lean,
            "suppliers": [
                _supplier("tp4056_usb_c_protected", "bargain_trap", unit_price=0.35, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.75, verbal_bias={'verified_yield_rate': 0.99}),
                _supplier("tp4056_usb_c_protected", "mid_honest", unit_price=0.75, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.99),
                _supplier("tp4056_usb_c_protected", "premium_honest", unit_price=1.0, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.995),
                _supplier("mosfet_low_side_3v3", "bargain_trap", unit_price=0.3, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=18, verbal_bias={'lead_time_days': 5}),
                _supplier("mosfet_low_side_3v3", "mid_honest", unit_price=0.7, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=6),
                _supplier("mosfet_low_side_3v3", "premium_honest", unit_price=0.95, capacity=20, moq=10, order_step=10, sample_cost=0.4, lead_time=4),
            ],
        },
        {
            "slug": "honest_premium_is_correct",
            "world_seed": 2614105,
            "product_id": "duediligence_honest_premium",
            "bom": {"ds3231_at24c32": 1, "ky023_joystick": 1},
            "budget_actions": 7,
            "objective": {"revenue": 12.0, "penalty": 3.0, "budget": 220.0, "deadline": 20, "minimum": 18},
            "interaction": lean,
            "suppliers": [
                _supplier("ds3231_at24c32", "bargain_trap", unit_price=1.6, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.8, verbal_bias={'verified_yield_rate': 0.99}),
                _supplier("ds3231_at24c32", "mid_trap", unit_price=2.0, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.85, verbal_bias={'verified_yield_rate': 0.98}),
                _supplier("ds3231_at24c32", "premium_honest", unit_price=2.7, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.995),
                _supplier("ky023_joystick", "bargain_trap", unit_price=1.0, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.8, verbal_bias={'verified_yield_rate': 0.99}),
                _supplier("ky023_joystick", "mid_trap", unit_price=1.35, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.85, verbal_bias={'verified_yield_rate': 0.98}),
                _supplier("ky023_joystick", "premium_honest", unit_price=1.9, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.995),
            ],
        },
        {
            "slug": "decoy_variant_and_yield",
            "world_seed": 2614106,
            "product_id": "duediligence_decoy_variant",
            "bom": {"tp4056_usb_c_protected": 1, "ky040_encoder": 1},
            "budget_actions": 7,
            "objective": {"revenue": 10.0, "penalty": 4.0, "budget": 200.0, "deadline": 20, "minimum": 18},
            "interaction": lean,
            "suppliers": [
                _supplier("tp4056_usb_c_protected", "wrong_variant_cheap", unit_price=0.3, capacity=20, moq=10, order_step=10, sample_cost=0.4, variant='usb_c_unprotected_no_separate_outputs'),
                _supplier("tp4056_usb_c_protected", "bargain_trap", unit_price=0.6, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.78, verbal_bias={'verified_yield_rate': 0.99}),
                _supplier("tp4056_usb_c_protected", "premium_honest", unit_price=1.05, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.995),
                _supplier("ky040_encoder", "wrong_variant_cheap", unit_price=0.4, capacity=20, moq=10, order_step=10, sample_cost=0.4, variant='ec11_rotary_no_switch'),
                _supplier("ky040_encoder", "bargain_trap", unit_price=0.7, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.78, verbal_bias={'verified_yield_rate': 0.99}),
                _supplier("ky040_encoder", "premium_honest", unit_price=1.15, capacity=20, moq=10, order_step=10, sample_cost=0.4, yield_rate=0.995),
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
            "max_logical_actions": definition["budget_actions"],
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
                "max_actions": definition["budget_actions"],
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
        raise AssertionError("due-diligence panel requires six distinct worlds")
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
