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
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .case_matrix import REQUIRED_VARIANTS, _supplier
from .environment import ProcurementAllocationPlugin
from .headroom_screen import ADMIT, classify_relationship_world, replay_baseline_outcome
from .relationship import (
    period_schedule,
    solve_loyal_reference,
    solve_myopic_reference,
    solve_relationship_upper_bound,
    solve_shopping_reference,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1"
CASE_ROOT = CASES_ROOT / "relationship_v1"
GENERATOR_ID = "procurement_allocation_relationship_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
PERIODS = 4
MAX_ACTIONS = 10

#: Generated packs: the stratum parameters are sampled from declared ranges
#: by a generator seeded with the world seed, every world declares noisy
#: verification so a campaign seed reaches the evidence the buyer reads, and a
#: world enters a pack only when the screen admits it. The two domains are
#: disjoint so a holdout is never a development world under another seed.
PACK_GENERATOR_ID = "procurement_allocation_relationship_pack_v1"
PACK_GENERATOR_VERSION = "1.0.0"
PACK_SCHEMA = "aeread.procurement_relationship_pack/0.1"
PACKS: dict[str, dict[str, Any]] = {
    "relationship_dev_v2": {"seed_start": 2420000, "per_stratum": 2, "scan_limit": 60, "split": "dev"},
    "relationship_holdout_v1": {"seed_start": 2430000, "per_stratum": 2, "scan_limit": 60, "split": "holdout"},
}
#: The public-observation policies whose per-world outcome every pack manifest
#: publishes, the Gate 1 baseline facts a live control is read against.
PACK_POLICIES = ("defer", "displayed_price_greedy", "listing_claim_fit", "semantic_hint")

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


def _build_case(
    definition: Mapping[str, Any],
    *,
    screen: bool = True,
    pack: str = "relationship_v1",
    split: str = "dev",
    generator: tuple[str, str] = (GENERATOR_ID, GENERATOR_VERSION),
    sample_noise: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    knobs = definition["objective"]
    periods: dict[str, Any] = {
        "count": PERIODS,
        "delivery_seed": int(definition["world_seed"]) + 100_000,
    }
    if definition.get("overrides"):
        periods["overrides"] = copy.deepcopy(definition["overrides"])
    interaction: dict[str, Any] = {
        "max_actions": MAX_ACTIONS,
        "inquiry_days": 1,
        "quote_days": 1,
        "counter_days": 1,
        "inquiry_cost_usd": 0.05,
        "quote_cost_usd": 0.1,
        "counter_cost_usd": 0.15,
        "periods": periods,
    }
    if sample_noise is not None:
        interaction["sample_noise"] = dict(sample_noise)
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"procurement_allocation_v1.{pack}.{definition['slug']}",
        "family_id": "procurement_allocation_v1",
        "family_version": "1.0.0",
        "split": split,
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
            "interaction": interaction,
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
            "generator_id": generator[0],
            "generator_version": generator[1],
            "review_status": "curated" if generator[0] == GENERATOR_ID else "generated",
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
    shopping = solve_shopping_reference(payload)
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
        "shopping_usd": shopping.contribution_margin_usd,
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



# --------------------------------------------------------------------------
# Generated packs: sampled strata, admitted by the screen over a seed stream
# --------------------------------------------------------------------------


def _sample_definition(stratum: str, seed: int) -> dict[str, Any]:
    """One world of ``stratum`` with its numbers drawn from declared ranges.

    The draws are a pure function of the world seed. Ranges sit around the
    hand-tuned values of the six curated worlds and are wide enough that the
    screen refuses a fair share of draws: that refusal rate is published in
    the pack manifest, so a pack is a selection by rule and not by hand.
    """
    draw = random.Random(f"{PACK_GENERATOR_ID}:{stratum}:{seed}")
    uniform = lambda low, high, places=4: round(draw.uniform(low, high), places)  # noqa: E731
    bom = {"esp32_s3_n8r8": 1, "ssd1306_oled_096": 1}
    objective = {"revenue": 10.0, "penalty": 3.0, "budget": 150.0, "deadline": 14}
    definition: dict[str, Any] = {
        "slug": f"{stratum}_{seed}",
        "stratum": stratum,
        "world_seed": seed,
        "product_id": f"display_controller_{stratum}_{seed}",
        "bom": bom,
        "objective": objective,
    }
    if stratum in ("loyalty_investment", "retaliation_trap"):
        spot = uniform(3.05, 3.35)
        per_award = uniform(0.06, 0.10)
        retaliation = uniform(0.10, 0.20) if stratum == "retaliation_trap" else uniform(0.04, 0.10)
        controllers = [
            _related("esp32_s3_n8r8", "spot", unit_price=spot, programme=_programme(retaliation=retaliation)),
            _related(
                "esp32_s3_n8r8",
                "partner",
                unit_price=round(spot * (1 + uniform(0.015, 0.04)), 4),
                programme=_programme(per_award=per_award, cap=round(3 * per_award, 4), retaliation=retaliation),
            ),
        ]
        if stratum == "loyalty_investment":
            displays = _plain_pair("ssd1306_oled_096", price=uniform(1.15, 1.35))
        else:
            north = uniform(1.18, 1.32)
            markup = uniform(0.10, 0.20)
            displays = [
                _related("ssd1306_oled_096", "north", unit_price=north, programme=_programme(per_award=0.02, cap=0.06, retaliation=markup)),
                _related(
                    "ssd1306_oled_096",
                    "south",
                    unit_price=round(north - uniform(0.005, 0.02), 4),
                    lead_time=8,
                    programme=_programme(per_award=0.02, cap=0.06, retaliation=markup),
                ),
            ]
        definition["suppliers"] = [*controllers, *displays]
    elif stratum in ("qualification_investment", "unreliable_incumbent"):
        known = uniform(1.30, 1.45)
        displays = [
            _related("ssd1306_oled_096", "known", unit_price=known),
            _related(
                "ssd1306_oled_096",
                "unproven",
                unit_price=round(known * uniform(0.66, 0.75), 4),
                sample_cost=uniform(8.0, 11.0, 2),
                sample_days=draw.choice((2, 3, 4)),
            ),
        ]
        if stratum == "qualification_investment":
            controllers = _plain_pair("esp32_s3_n8r8", price=uniform(3.10, 3.30))
        else:
            reliable = uniform(3.15, 3.35)
            controllers = [
                _related(
                    "esp32_s3_n8r8",
                    "flaky",
                    unit_price=round(reliable - uniform(0.20, 0.35), 4),
                    on_time=uniform(0.80, 0.90, 3),
                    yield_rate=0.97,
                    programme=_programme(per_award=0.04, cap=0.12),
                    verbal_bias={"on_time_probability": 0.98, "lead_time_days": 6},
                ),
                _related("esp32_s3_n8r8", "reliable", unit_price=reliable, programme=_programme(per_award=0.04, cap=0.12)),
            ]
        definition["suppliers"] = [*controllers, *displays]
    elif stratum == "demand_ramp":
        definition["objective"] = {**objective, "budget": 250.0}
        definition["overrides"] = [
            {"target_kits": 10, "minimum_service_kits": 8},
            {"target_kits": 10, "minimum_service_kits": 8},
            {"target_kits": 30, "minimum_service_kits": 24},
            {"target_kits": 30, "minimum_service_kits": 24},
        ]
        small = uniform(2.95, 3.15)
        per_award = uniform(0.06, 0.10)
        definition["suppliers"] = [
            _related("esp32_s3_n8r8", "small", unit_price=small, capacity=10, moq=10, order_step=10),
            _related(
                "esp32_s3_n8r8",
                "scale",
                unit_price=round(small + uniform(0.15, 0.35), 4),
                capacity=30,
                moq=10,
                order_step=10,
                programme=_programme(per_award=per_award, cap=round(3 * per_award, 4)),
            ),
            _related("ssd1306_oled_096", "steady", unit_price=uniform(1.15, 1.35), capacity=30),
            _related("ssd1306_oled_096", "slow", unit_price=uniform(1.35, 1.50), capacity=30, lead_time=11, on_time=0.96),
        ]
    elif stratum == "incumbent_capacity":
        steady = uniform(3.20, 3.40)
        per_award = uniform(0.06, 0.10)
        definition["suppliers"] = [
            _related(
                "esp32_s3_n8r8",
                "flex",
                unit_price=round(steady + uniform(-0.05, 0.05), 4),
                capacity=10,
                moq=10,
                order_step=10,
                programme=_programme(per_award=per_award, cap=round(3 * per_award, 4), bonus=10),
            ),
            _related("esp32_s3_n8r8", "steady", unit_price=steady),
            *_plain_pair("ssd1306_oled_096", price=uniform(1.15, 1.35)),
        ]
    else:
        raise ValueError(f"unknown stratum: {stratum}")
    return definition


def _policy_outcomes(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The public-observation policies' outcomes on one world, per policy."""
    outcomes: dict[str, Any] = {}
    for policy in PACK_POLICIES:
        outcome = replay_baseline_outcome(payload, policy)
        outcomes[policy] = (
            None
            if outcome is None
            else {
                "regret_to_upper_bound_usd": outcome["regret_to_upper_bound_usd"],
                "contribution_margin_usd": outcome["contribution_margin_usd"],
                "periods_awarded": outcome["periods_awarded"],
                "switches": outcome["switches"],
            }
        )
    return outcomes


def build_pack(name: str, *, spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Walk the pack's seed stream and admit worlds by the screen.

    Seed ``s`` in the stream is offered to stratum ``s - seed_start mod 6``;
    a draw the screen refuses is recorded with its verdict and the stream
    moves on. The walk stops when every stratum holds ``per_stratum``
    admitted worlds or ``scan_limit`` seeds have been scanned, in which case
    the pack is short and says so.
    """
    spec = dict(spec or PACKS[name])
    seed_start = int(spec["seed_start"])
    per_stratum = int(spec["per_stratum"])
    scan_limit = int(spec["scan_limit"])
    admitted: dict[str, list[dict[str, Any]]] = {stratum: [] for stratum in CASE_SLUGS}
    excluded: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    scanned = 0
    for offset in range(scan_limit):
        if all(len(rows) >= per_stratum for rows in admitted.values()):
            break
        seed = seed_start + offset
        stratum = CASE_SLUGS[offset % len(CASE_SLUGS)]
        scanned += 1
        if len(admitted[stratum]) >= per_stratum:
            excluded.append({"world_seed": seed, "stratum": stratum, "verdict": "stratum full"})
            continue
        definition = _sample_definition(stratum, seed)
        try:
            raw = _build_case(
                definition,
                screen=False,
                pack=name,
                split=str(spec["split"]),
                generator=(PACK_GENERATOR_ID, PACK_GENERATOR_VERSION),
                sample_noise={"model": "binomial", "seed": seed + 500_000},
            )
        except ValueError as error:
            excluded.append({"world_seed": seed, "stratum": stratum, "verdict": f"invalid: {error}"[:200]})
            continue
        verdict = screen_world(raw["payload"])
        if verdict["verdict"] != ADMIT:
            excluded.append({"world_seed": seed, "stratum": stratum, "verdict": verdict["verdict"]})
            continue
        row = {
            "slug": definition["slug"],
            "stratum": stratum,
            "world_seed": seed,
            "case_id": raw["case_id"],
            "content_sha256": raw["content_sha256"],
            "upper_bound_usd": verdict["upper_bound_usd"],
            "myopic_usd": verdict["myopic_usd"],
            "loyal_usd": verdict["loyal_usd"],
            "shopping_usd": verdict["shopping_usd"],
            "headroom_over_myopic": round(
                (verdict["upper_bound_usd"] - verdict["myopic_usd"]) / verdict["upper_bound_usd"], 6
            ),
            "headroom_over_loyal": round(
                (verdict["upper_bound_usd"] - verdict["loyal_usd"]) / verdict["upper_bound_usd"], 6
            ),
            "optimum_switches": verdict["optimum_switches"],
            "public_policies": _policy_outcomes(raw["payload"]),
        }
        admitted[stratum].append(row)
        cases.append(raw)
    manifest = {
        "schema_version": PACK_SCHEMA,
        "pack": name,
        "generator_id": PACK_GENERATOR_ID,
        "generator_version": PACK_GENERATOR_VERSION,
        "split": spec["split"],
        "seed_domain": {"start": seed_start, "scan_limit": scan_limit},
        "selection_rule": (
            "seed s is offered to stratum (s - start) mod 6; its numbers are drawn from the "
            "stratum's declared ranges by a generator seeded with s; the world is admitted when "
            f"classify_relationship_world admits it at {MINIMUM_RELATIVE_MARGIN} and the stratum "
            f"is not yet full at {per_stratum}; every world declares binomial sample noise"
        ),
        "minimum_relative_margin": MINIMUM_RELATIVE_MARGIN,
        "per_stratum": per_stratum,
        "seeds_scanned": scanned,
        "admitted": sum(len(rows) for rows in admitted.values()),
        "complete": all(len(rows) >= per_stratum for rows in admitted.values()),
        "admission_rate": round(
            sum(len(rows) for rows in admitted.values())
            / max(1, sum(1 for row in excluded if row["verdict"] != "stratum full") + sum(len(rows) for rows in admitted.values())),
            4,
        ),
        "worlds": [row for stratum in CASE_SLUGS for row in admitted[stratum]],
        "excluded": excluded,
        "public_policies": list(PACK_POLICIES),
        "claim_scope": "synthetic worlds selected by rule; the references are full-information solvers, not a model",
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"manifest": manifest, "cases": cases}


def pack_root(name: str) -> Path:
    return CASES_ROOT / name


def pack_case_paths(name: str) -> tuple[Path, ...]:
    """The committed worlds of a pack, in manifest order."""
    manifest = json.loads((pack_root(name) / "pack.json").read_text(encoding="utf-8"))
    return tuple(pack_root(name) / f"{row['slug']}.json" for row in manifest["worlds"])


def write_pack(name: str, *, root: Path | str | None = None) -> tuple[Path, ...]:
    built = build_pack(name)
    destination = Path(root) if root is not None else pack_root(name)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in built["cases"]:
        path = destination / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        written.append(path)
    manifest_path = destination / "pack.json"
    temporary = manifest_path.with_suffix(f".json.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(built["manifest"], indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    written.append(manifest_path)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--screen",
        action="store_true",
        help="print the three references and the verdict for every definition",
    )
    parser.add_argument(
        "--pack",
        choices=sorted(PACKS),
        default=None,
        help="build a generated pack (sampled strata, noisy verification, admitted by rule) instead of the curated six",
    )
    arguments = parser.parse_args(argv)
    if arguments.pack:
        if arguments.write:
            for path in write_pack(arguments.pack):
                print(path)
        else:
            built = build_pack(arguments.pack)
            print(json.dumps({k: v for k, v in built["manifest"].items() if k != "worlds"}, indent=2))
            for row in built["manifest"]["worlds"]:
                print(row["slug"], row["headroom_over_myopic"], row["headroom_over_loyal"])
        return 0
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
    "PACKS",
    "PACK_GENERATOR_ID",
    "PACK_POLICIES",
    "PERIODS",
    "build_case_matrix",
    "build_pack",
    "pack_case_paths",
    "pack_root",
    "screen_world",
    "write_case_matrix",
    "write_pack",
]
