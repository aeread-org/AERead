"""Eight fixed synthetic markets, authored without model outcomes."""

from __future__ import annotations
import copy
import hashlib
import json
import random
from pathlib import Path

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from .case_matrix import REQUIRED_VARIANTS
from .duediligence_case_matrix import _supplier
from .phase2_environment import FAMILY_ID, Phase2Plugin

CATEGORIES = (
    "split",
    "split",
    "quality",
    "quality",
    "deadline",
    "deadline",
    "trap_deadline",
    "trap_budget",
)
SCREEN_SEEDS = tuple(range(51001, 51025))
PILOT_SEEDS = (52001,)
CONFIRMATORY_SEEDS = (53001, 53002, 53003)
CASE_ROOT = Path(__file__).resolve().parents[3] / "cases" / FAMILY_ID / "panel_v1"


def rehash(raw):
    raw = copy.deepcopy(raw)
    raw["content_sha256"] = "0" * 64
    raw["content_sha256"] = case_content_sha256(CaseManifest.from_dict(raw))
    return raw


def episode_case(raw, seed):
    raw = copy.deepcopy(raw)
    raw["payload"]["interaction"]["sample_noise"]["seed"] = seed
    return rehash(raw)


def build_world(index):
    if index not in range(8):
        raise ValueError("world index must be 0..7")
    category = CATEGORIES[index]
    component = sorted(REQUIRED_VARIANTS)[index % len(REQUIRED_VARIANTS)]
    # One bottleneck component per kit; the other assembled parts are sunk costs.
    split = category == "split"
    capacity = 12 if split else 24
    prices = [0.55, 0.95, 1.10, 1.35, 1.6, 1.8, 2.1, 2.4]
    yields = [0.35 if split else 0.58, 0.96, 0.97, 0.84, 0.8, 0.75, 0.88, 0.91]
    leads = [6] * 8
    prior = [0.65, 0.93, 0.90, 0.86, 0.81, 0.76, 0.84, 0.88]
    deadline, revenue, budget, minimum = (
        24,
        4.5 + index * 0.05,
        100.0,
        18 if split else 10,
    )
    market = dict(
        minimum_delivery_days=1,
        minimum_unit_price_usd=0.1,
        status="certified_market_floor_not_supplier_claim",
    )
    if category == "quality":
        yields = [
            0.55,
            0.96 if index == 2 else 0.70,
            0.97,
            0.83,
            0.79,
            0.75,
            0.88,
            0.91,
        ]
        # Historical evidence ranks the first prospect, but it is wrong in world 4.
        prior = [0.62, 0.95, 0.94, 0.88, 0.8, 0.77, 0.87, 0.90]
    if category == "deadline":
        leads = [28, 24, 3, 4, 5, 8, 10, 12]
        yields = [0.98, 0.97, 0.96, 0.94, 0.90, 0.94, 0.96, 0.97]
        prior = [0.96, 0.94, 0.92, 0.91, 0.89, 0.90, 0.92, 0.94]
        deadline, minimum = 12 + (index - 4), 16
    if category == "trap_deadline":
        leads, deadline, minimum = [30 + i for i in range(8)], 14, 18
        yields = [0.97] * 8
        market["minimum_delivery_days"] = 30
    if category == "trap_budget":
        prices, budget, minimum = [6.0 + 0.15 * i for i in range(8)], 80.0, 18
        yields = [0.97] * 8
        market["minimum_unit_price_usd"] = 6.0
    suppliers = []
    for j in range(8):
        supplier = _supplier(
            component,
            str(j),
            unit_price=prices[j],
            shipping=0.05,
            duty_rate=0.0,
            lead_time=leads[j],
            on_time=1.0,
            yield_rate=yields[j],
            capacity=capacity,
            moq=capacity,
            order_step=capacity,
            claim_acceptance=0.0,
            sample_cost=0.65,
            sample_days=1,
            offer_valid_days=60,
            verbal_bias={"verified_yield_rate": 0.94},
        )
        opaque = hashlib.sha256(f"phase2-v1:{index}:{j}".encode()).hexdigest()[:10]
        supplier["supplier_id"] = f"vendor_{opaque}"
        supplier["listing"].update(
            supplier_name=f"Vendor {opaque.upper()}",
            historical_yield_estimate=prior[j],
            historical_sample_units=40,
            historical_status="previous_batch_nonbinding_prior",
            advertised_capacity=capacity,
            advertised_moq=capacity,
            sample_batch_units=24,
            sample_cost_usd=0.65,
            sample_days=1,
        )
        supplier["private_terms"]["quality"].update(
            sample_size=24, observed_defects=round(24 * (1 - yields[j]))
        )
        suppliers.append(supplier)
    random.Random(41000 + index).shuffle(suppliers)
    raw = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"{FAMILY_ID}.world_{index+1:02d}",
        "family_id": FAMILY_ID,
        "family_version": "1.0.0",
        "split": "phase2_v1",
        "world_seed": 41000 + index,
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
        "visibility_policy": "phase2_public_market_floors_no_hidden_yield_checker_v1",
        "payload": {
            "objective": {
                "product_id": "pilot_kit_bottleneck_procurement",
                "target_kits": 20,
                "minimum_service_kits": minimum,
                "revenue_per_completed_kit_usd": revenue,
                "shortfall_penalty_per_kit_usd": 0.5,
                "cash_budget_usd": budget,
                "deadline_days": deadline,
                "defect_detection_days": 10,
                "working_capital_horizon_days": 45,
                "annual_financing_rate": 0.0,
                "defer_value_usd": 0.0,
                "bom": {component: 1},
            },
            "interaction": {
                "max_actions": 10,
                "inquiry_days": 1,
                "quote_days": 1,
                "counter_days": 1,
                "inquiry_cost_usd": 0.1,
                "quote_cost_usd": 0.1,
                "counter_cost_usd": 0.1,
                "counter_feedback": "field_specific",
                "sample_noise": {"model": "binomial", "seed": SCREEN_SEEDS[0]},
            },
            "policy": {
                "required_variant_by_component": {
                    component: REQUIRED_VARIANTS[component]
                },
                "inquiry_fields": [
                    "exact_variant",
                    "moq_capacity",
                    "lead_time",
                    "shipping",
                    "quality",
                    "sample_logistics",
                ],
                "award_requires": [
                    "unexpired_formal_offer",
                    "verified_sample",
                    "exact_variant",
                ],
                "market_constraints": market,
            },
            "suppliers": suppliers,
        },
        "provenance": {
            "generator_id": "procurement_phase2_worlds_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    Phase2Plugin().validate_payload(raw["payload"])
    return rehash(raw)


def write_worlds(root=CASE_ROOT):
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(8):
        path = root / f"world_{i+1:02d}.json"
        data = json.dumps(build_world(i), indent=2, sort_keys=True) + "\n"
        if path.exists() and path.read_text() != data:
            raise FileExistsError(f"refusing to replace world: {path}")
        path.write_text(data)
        paths.append(path)
    return paths
