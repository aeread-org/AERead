"""Repeated-sourcing worlds: six strata where the periods have to matter.

Each world is the single-period family's shape (two components, two suppliers
each, twenty kits, ten actions) run over four periods with supplier standing
carried between them. One component carries the stratum's *tension*, the
reason a T-period optimum differs from both a period-by-period optimizer and
a never-switch rule; the other carries a *trap* for the buyer that the
full-information references do not fall into, or is plain.

Every world is screened before it is written: the exact T-period bound must
beat the myopic and the loyal reference by the declared margin
(`headroom_screen.classify_relationship_world`), or the world is refused. The
numbers below were tuned against that screen; `--screen` prints the three
references and the verdict for each world so a retune is visible.

Synthetic throughout: supplier identities and economics are calibrated to
exercise the intertemporal trade-offs and do not represent live suppliers.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .case_matrix import REQUIRED_VARIANTS, _supplier
from .environment import ProcurementAllocationPlugin
from .headroom_screen import ADMIT, classify_relationship_world
from .relationship import (
    period_schedule,
    solve_loyal_reference,
    solve_myopic_reference,
    solve_relationship_upper_bound,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / "relationship_v1"
GENERATOR_ID = "procurement_allocation_relationship_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
PERIODS = 4
MAX_ACTIONS = 10

#: The intertemporal structure must be worth this fraction of the T-period
#: optimum against both references. Same materiality as the Gate 1 screen.
MINIMUM_RELATIVE_MARGIN = 0.05

CASE_SLUGS = (
    "loyalty_investment",
    "qualification_investment",
    "demand_ramp",
    "incumbent_capacity",
    "retaliation_trap",
    "unreliable_incumbent",
)
CASE_PATHS = tuple(CASE_ROOT / f"{slug}.json" for slug in CASE_SLUGS)

NO_PROGRAMME = {
    "loyalty_discount_per_award": 0.0,
    "loyalty_discount_cap": 0.0,
    "incumbent_capacity_bonus": 0,
    "retaliation_markup": 0.0,
}


def _programme(
    *,
    per_award: float = 0.0,
    cap: float = 0.0,
    bonus: int = 0,
    retaliation: float = 0.0,
) -> dict[str, Any]:
    return {
        "loyalty_discount_per_award": per_award,
        "loyalty_discount_cap": cap,
        "incumbent_capacity_bonus": bonus,
        "retaliation_markup": retaliation,
    }


def _related(
    component: str,
    label: str,
    *,
    programme: Mapping[str, Any] | None = None,
    verbal_bias: Mapping[str, Any] | None = None,
    **terms: Any,
) -> dict[str, Any]:
    supplier = _supplier(component, label, **terms)
    supplier["private_terms"]["relationship"] = dict(programme or NO_PROGRAMME)
    if verbal_bias:
        supplier["private_terms"]["verbal_bias"] = dict(verbal_bias)
    return supplier


def _plain_pair(component: str, *, price: float) -> list[dict[str, Any]]:
    """A component with one clearly better supplier and no programme."""
    return [
        _related(component, "steady", unit_price=price),
        _related(
            component,
            "slow",
            unit_price=round(price * 1.12, 4),
            lead_time=11,
            on_time=0.96,
            yield_rate=0.98,
        ),
    ]


def _definitions() -> tuple[dict[str, Any], ...]:
    return (
        {
            # A spot supplier is cheapest today; a partner supplier is dearer
            # today and discounts every consecutive award. Buying from the
            # partner is an investment that pays from the third period on.
            "slug": "loyalty_investment",
            "world_seed": 2410001,
            "product_id": "display_controller_loyalty",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 10.0, "penalty": 3.0, "budget": 150.0, "deadline": 14},
            "suppliers": [
                _related(
                    "esp32_s3_n8r8",
                    "spot",
                    unit_price=3.20,
                    programme=_programme(retaliation=0.06),
                ),
                _related(
                    "esp32_s3_n8r8",
                    "partner",
                    unit_price=3.28,
                    programme=_programme(per_award=0.08, cap=0.24, retaliation=0.06),
                ),
                *_plain_pair("ssd1306_oled_096", price=1.25),
            ],
        },
        {
            # An unproven supplier is cheaper per unit but costs a large
            # one-time qualification sample. One period cannot recover it;
            # four can. The myopic buyer re-prices the sample every period.
            "slug": "qualification_investment",
            "world_seed": 2410002,
            "product_id": "display_controller_qualification",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 10.0, "penalty": 3.0, "budget": 150.0, "deadline": 14},
            "suppliers": [
                *_plain_pair("esp32_s3_n8r8", price=3.20),
                _related("ssd1306_oled_096", "known", unit_price=1.35),
                _related(
                    "ssd1306_oled_096",
                    "unproven",
                    unit_price=0.95,
                    sample_cost=9.5,
                    sample_days=3,
                ),
            ],
        },
        {
            # Demand ramps from ten kits to thirty. A small supplier is
            # cheapest at ten; only the scale supplier can fill thirty, and its
            # programme rewards having been its customer before the ramp.
            "slug": "demand_ramp",
            "world_seed": 2410003,
            "product_id": "display_controller_ramp",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 10.0, "penalty": 3.0, "budget": 250.0, "deadline": 14},
            "overrides": [
                {"target_kits": 10, "minimum_service_kits": 8},
                {"target_kits": 10, "minimum_service_kits": 8},
                {"target_kits": 30, "minimum_service_kits": 24},
                {"target_kits": 30, "minimum_service_kits": 24},
            ],
            "suppliers": [
                _related(
                    "esp32_s3_n8r8",
                    "small",
                    unit_price=3.05,
                    capacity=10,
                    moq=10,
                    order_step=10,
                ),
                _related(
                    "esp32_s3_n8r8",
                    "scale",
                    unit_price=3.30,
                    capacity=30,
                    moq=10,
                    order_step=10,
                    programme=_programme(per_award=0.08, cap=0.24),
                ),
                _related("ssd1306_oled_096", "steady", unit_price=1.25, capacity=30),
                _related(
                    "ssd1306_oled_096",
                    "slow",
                    unit_price=1.40,
                    capacity=30,
                    lead_time=11,
                    on_time=0.96,
                ),
            ],
        },
        {
            # A flexible supplier can fill only half the target until it is
            # the incumbent, when it reserves the rest and discounts every
            # consecutive award; a steady supplier fills all of it at the same
            # price today and never moves. Splitting today, which costs a
            # little more, is the only door to a cheaper single source later.
            "slug": "incumbent_capacity",
            "world_seed": 2410004,
            "product_id": "display_controller_incumbent",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 10.0, "penalty": 3.0, "budget": 150.0, "deadline": 14},
            "suppliers": [
                _related(
                    "esp32_s3_n8r8",
                    "flex",
                    unit_price=3.30,
                    capacity=10,
                    moq=10,
                    order_step=10,
                    programme=_programme(per_award=0.08, cap=0.24, bonus=10),
                ),
                _related("esp32_s3_n8r8", "steady", unit_price=3.30),
                *_plain_pair("ssd1306_oled_096", price=1.25),
            ],
        },
        {
            # The loyalty tension of the first world, plus a second component
            # whose two suppliers are priced within a cent and retaliate hard
            # when quoted and dropped. Shopping both every period is what
            # makes the loser dear when the buyer comes back.
            "slug": "retaliation_trap",
            "world_seed": 2410005,
            "product_id": "display_controller_retaliation",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 10.0, "penalty": 3.0, "budget": 150.0, "deadline": 14},
            "suppliers": [
                _related(
                    "esp32_s3_n8r8",
                    "spot",
                    unit_price=3.20,
                    programme=_programme(retaliation=0.10),
                ),
                _related(
                    "esp32_s3_n8r8",
                    "partner",
                    unit_price=3.28,
                    programme=_programme(per_award=0.08, cap=0.24, retaliation=0.10),
                ),
                _related(
                    "ssd1306_oled_096",
                    "north",
                    unit_price=1.25,
                    programme=_programme(per_award=0.02, cap=0.06, retaliation=0.15),
                ),
                _related(
                    "ssd1306_oled_096",
                    "south",
                    unit_price=1.24,
                    lead_time=8,
                    programme=_programme(per_award=0.02, cap=0.06, retaliation=0.15),
                ),
            ],
        },
        {
            # The qualification tension of the second world, plus a cheap
            # controller supplier whose listing and verbal claims overstate
            # its delivery reliability. Its formal quote tells the truth and
            # its history shows it; a buyer that trusts the listing pays.
            "slug": "unreliable_incumbent",
            "world_seed": 2410006,
            "product_id": "display_controller_unreliable",
            "bom": {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1},
            "objective": {"revenue": 10.0, "penalty": 3.0, "budget": 150.0, "deadline": 14},
            "suppliers": [
                _related(
                    "esp32_s3_n8r8",
                    "flaky",
                    unit_price=2.95,
                    on_time=0.86,
                    yield_rate=0.97,
                    programme=_programme(per_award=0.04, cap=0.12),
                    verbal_bias={"on_time_probability": 0.98, "lead_time_days": 6},
                ),
                _related(
                    "esp32_s3_n8r8",
                    "reliable",
                    unit_price=3.25,
                    programme=_programme(per_award=0.04, cap=0.12),
                ),
                _related("ssd1306_oled_096", "known", unit_price=1.35),
                _related(
                    "ssd1306_oled_096",
                    "unproven",
                    unit_price=0.95,
                    sample_cost=9.5,
                    sample_days=3,
                ),
            ],
        },
    )


def _build_case(definition: Mapping[str, Any], *, screen: bool = True) -> dict[str, Any]:
    knobs = definition["objective"]
    periods: dict[str, Any] = {
        "count": PERIODS,
        "delivery_seed": int(definition["world_seed"]) + 100_000,
    }
    if definition.get("overrides"):
        periods["overrides"] = copy.deepcopy(definition["overrides"])
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"procurement_allocation_v1.relationship_v1.{definition['slug']}",
        "family_id": "procurement_allocation_v1",
        "family_version": "1.0.0",
        "split": "dev",
        "world_seed": definition["world_seed"],
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {
            "max_logical_actions": MAX_ACTIONS * PERIODS,
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
                "max_actions": MAX_ACTIONS,
                "inquiry_days": 1,
                "quote_days": 1,
                "counter_days": 1,
                "inquiry_cost_usd": 0.05,
                "quote_cost_usd": 0.1,
                "counter_cost_usd": 0.15,
                "periods": periods,
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
    draft = CaseManifest.from_dict(raw)
    ProcurementAllocationPlugin().validate_payload(draft.payload)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError(f"unstable case digest for {case.case_id}")
    if screen:
        verdict = screen_world(case.payload)
        if verdict["verdict"] != ADMIT:
            raise ValueError(
                f"{case.case_id} refused by the relationship screen: {verdict}"
            )
    return raw


def screen_world(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The three full-information references and the admission verdict."""
    bound = solve_relationship_upper_bound(payload)
    myopic = solve_myopic_reference(payload)
    loyal = solve_loyal_reference(payload)
    outside = sum(float(row["defer_value_usd"]) for row in period_schedule(payload))
    verdict = classify_relationship_world(
        upper_bound=bound.contribution_margin_usd,
        myopic=myopic.contribution_margin_usd,
        loyal=loyal.contribution_margin_usd,
        outside_option=outside,
        minimum_relative_margin=MINIMUM_RELATIVE_MARGIN,
    )
    return {
        "verdict": verdict,
        "upper_bound_usd": bound.contribution_margin_usd,
        "myopic_usd": myopic.contribution_margin_usd,
        "loyal_usd": loyal.contribution_margin_usd,
        "optimum_switches": bound.switches,
        "myopic_switches": myopic.switches,
        "optimum_path": [
            sorted({line["supplier_id"] for line in plan}) for plan in bound.period_plans
        ],
        "myopic_path": [
            sorted({line["supplier_id"] for line in plan}) for plan in myopic.period_plans
        ],
        "loyal_path": [
            sorted({line["supplier_id"] for line in plan}) for plan in loyal.period_plans
        ],
    }


def build_case_matrix() -> tuple[dict[str, Any], ...]:
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
    parser.add_argument(
        "--screen",
        action="store_true",
        help="print the three references and the verdict for every definition",
    )
    arguments = parser.parse_args(argv)
    if arguments.screen:
        # Unscreened on purpose: this is how a retune sees what it did.
        for definition in _definitions():
            raw = _build_case(definition, screen=False)
            print(definition["slug"], json.dumps(screen_world(raw["payload"]), sort_keys=True))
        return 0
    if arguments.write:
        for path in write_case_matrix():
            print(path)
    else:
        print(json.dumps(build_case_matrix(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_PATHS",
    "CASE_ROOT",
    "CASE_SLUGS",
    "GENERATOR_ID",
    "MINIMUM_RELATIVE_MARGIN",
    "PERIODS",
    "build_case_matrix",
    "screen_world",
    "write_case_matrix",
]
