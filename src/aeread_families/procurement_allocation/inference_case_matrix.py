"""Worlds where choosing whom to verify requires an inference, not a rule.

Twelve panels failed before this one, all for the same reason. Suppliers were
indistinguishable before verification: identical listing claims, uniform check
cost, uniform information per check. That leaves one decision, how many to check,
which the budget already fixes. So "verify what you can afford and award the
best" is not a baseline, it is optimal, and the gap between the best possible
agent and twenty lines of code is zero by construction. Every world then lands in
one of three useless places: everyone wins, nobody wins, or the outcome turns on
which suppliers you happened to check, which produces dispersion without skill.

Two changes here, and they only work together.

**A visible feature predicts quality, and which one differs by world.** Listings
carry heterogeneous price, lead time, minimum order and claimed capacity. In each
world one of those attributes genuinely tracks the supplier's true yield, and the
attribute and its direction change between worlds. Cheap means cut corners in one
world; in another cheap means a small shop with low overhead and the real tell is
an implausible promised lead time. A buyer must verify a supplier or two, notice
how the visible features line up with what it measured, and spend its remaining
checks accordingly. No fixed rule does that, and every fixed rule wins some
worlds and loses others, which is the signature of a task with something to
measure.

**The binding risk varies and is not labelled.** In some worlds the danger is
yield, in others an honest supplier who cannot hit the date, in others one who
cannot supply the volume. All three already exist on every supplier. A buyer that
always samples for quality loses the timing worlds.

Nothing here is admitted yet. The panel is generated and screened; admission is
`headroom_screen.classify_world_by_policy_separation`, which requires two
structurally different policies to differ in expectation on the world.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .duediligence_case_matrix import _build_case, _supplier

GENERATOR_ID = "procurement_allocation_inference_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
PANEL_ID = "procurement_allocation_inference_v1"

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LABELED_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / "inference_v1" / "labeled"
OPAQUE_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / "inference_v1" / "opaque"

COMPONENTS = ("sht30_i2c", "bh1750_gy302")
SAMPLE_BATCH = 8
BUDGET_ACTIONS = 9
NOISE_SEED = 20260910

#: Which visible attribute tracks true quality, and in which direction. The
#: buyer is never told; it has to be inferred from the suppliers it verifies.
SIGNALS: tuple[str, ...] = (
    "price_low_is_good",
    "price_high_is_good",
    "lead_time_short_is_good",
    "lead_time_long_is_good",
    "moq_low_is_good",
    "moq_high_is_good",
)

#: Which constraint actually binds. Also never labelled.
RISKS: tuple[str, ...] = ("yield", "timing", "capacity")

_GOOD, _POOR = 0.985, 0.82

#: Price order when price is *not* the signal. A fixed permutation chosen so that
#: price carries no information about quality in those worlds. Without it the
#: signal is always price in disguise: an earlier version tied every visible
#: attribute to one rank, and "buy the dearest" won 9 of 12 worlds.
_DECOY_PRICE_ORDER = (2, 0, 3, 1)
_NEUTRAL_LEAD_DAYS = 6
_NEUTRAL_MOQ = 10


def _position(index: int, count: int) -> float:
    """Where a supplier sits on its world's signal attribute, 0.0 to 1.0."""
    return index / max(count - 1, 1)


def _quality_for(signal: str, index: int, count: int) -> float:
    """True yield implied by the signal, so the visible attribute really predicts it."""
    high_is_good = signal.endswith("high_is_good") or signal.endswith("long_is_good")
    position = _position(index, count)
    if high_is_good:
        return _GOOD if position >= 0.5 else _POOR
    return _GOOD if position < 0.5 else _POOR


def _visible_attributes(signal: str, index: int, count: int) -> dict[str, Any]:
    """Carry the signal on one attribute and leave the others uninformative."""
    position = _position(index, count)
    if signal.startswith("price"):
        price_rank = position
    else:
        price_rank = _DECOY_PRICE_ORDER[index % len(_DECOY_PRICE_ORDER)] / max(count - 1, 1)
    lead = 4 + int(round(3 * position)) if signal.startswith("lead_time") else _NEUTRAL_LEAD_DAYS
    moq = (10 + 10 * (1 if position >= 0.5 else 0)) if signal.startswith("moq") else _NEUTRAL_MOQ
    return {
        "unit_price": round(0.60 + 0.40 * price_rank, 4),
        "lead_time": lead,
        "moq": moq,
    }


def _supplier_for(
    component: str, index: int, count: int, *, signal: str, risk: str
) -> dict[str, Any]:
    """One supplier whose visible attributes carry the world's signal and nothing else."""
    visible = _visible_attributes(signal, index, count)
    yield_rate = _quality_for(signal, index, count)
    good = yield_rate == _GOOD

    # Exactly one constraint can cost a buyer the order in a given world, and the
    # listing never says which.
    on_time, capacity = 0.99, 20
    if risk == "timing":
        yield_rate = _GOOD
        on_time = 0.99 if good else 0.55
    elif risk == "capacity":
        yield_rate = _GOOD
        capacity = 20 if good else 10

    return _supplier(
        component,
        f"t{index}",
        unit_price=visible["unit_price"],
        capacity=capacity,
        moq=min(visible["moq"], capacity),
        order_step=10,
        lead_time=visible["lead_time"],
        on_time=on_time,
        sample_cost=0.25,
        sample_days=2,
        yield_rate=yield_rate,
        verbal_bias={"verified_yield_rate": 0.99},
    )


def _definition(
    slug: str, world_seed: int, *, signal: str, risk: str, ordinal: int
) -> dict[str, Any]:
    suppliers: list[dict[str, Any]] = []
    for component in COMPONENTS:
        for index in range(4):
            suppliers.append(
                _supplier_for(component, index, 4, signal=signal, risk=risk)
            )
    return {
        "slug": slug,
        "world_seed": world_seed,
        # Neutral, because the slug names the world's signal and binding risk and
        # the product id is inside the payload the buyer reads. An earlier version
        # used f"inference_{slug}" and handed the answer over in the objective,
        # which is design defect 8 arriving through a new door.
        "product_id": f"inference_kit_{ordinal:02d}",
        "bom": {component: 1 for component in COMPONENTS},
        "budget_actions": BUDGET_ACTIONS,
        "objective": {
            "revenue": 16.0,
            "penalty": 3.0,
            "budget": 60.0,
            "deadline": 24,
            "minimum": 18,
        },
        "interaction": {"inquiry": 0.05, "quote": 0.1, "counter": 0.15},
        "suppliers": suppliers,
    }


def world_specs() -> tuple[tuple[str, int, str, str], ...]:
    """Every signal crossed with every binding risk, so no fixed rule wins all."""
    specs: list[tuple[str, int, str, str]] = []
    for signal_index, signal in enumerate(SIGNALS):
        for risk_index, risk in enumerate(RISKS):
            slug = f"{signal}__{risk}"
            specs.append((slug, 8810000 + 10 * signal_index + risk_index, signal, risk))
    return tuple(specs)


def finish_case(
    case: dict[str, Any],
    *,
    case_id: str,
    split: str,
    sample_batch: int,
    noise_seed: int,
    generator: tuple[str, str] = (GENERATOR_ID, GENERATOR_VERSION),
    review_status: str = "curated",
) -> dict[str, Any]:
    """Stamp identity, the noisy-sample terms and provenance, then seal the digest.

    Shared by the fixed v1 panel and the seed-domain packs so both carry the
    same evidence terms: a sample inspects ``sample_batch`` units, draws are
    binomial from ``noise_seed``, and the digest is computed last.
    """
    from aeread.shared_runner.run.resolver import case_content_sha256
    from aeread.shared_runner.schemas import CaseManifest

    case["case_id"] = case_id
    case["split"] = split
    for supplier in case["payload"]["suppliers"]:
        quality = supplier["private_terms"]["quality"]
        quality["sample_size"] = sample_batch
        quality["observed_defects"] = round(
            sample_batch * (1.0 - float(quality["verified_yield_rate"]))
        )
    case["payload"]["interaction"]["sample_noise"] = {
        "model": "binomial",
        "seed": noise_seed,
    }
    case["provenance"] = {
        "generator_id": generator[0],
        "generator_version": generator[1],
        "review_status": review_status,
    }
    # The provenance schema is closed, so what the world was built to test
    # lives in the slug: "<signal>__<risk>". An auditor reads it there, and
    # the buyer never sees it because the slug is not in the payload.
    case["content_sha256"] = "0" * 64
    case["content_sha256"] = case_content_sha256(CaseManifest.from_dict(case))
    return case


def build_inference_case_matrix(*, surface: str) -> tuple[dict[str, Any], ...]:
    cases: list[dict[str, Any]] = []
    for ordinal, (slug, world_seed, signal, risk) in enumerate(world_specs(), start=1):
        case = _build_case(
            _definition(slug, world_seed, signal=signal, risk=risk, ordinal=ordinal),
            surface=surface,
        )
        cases.append(
            finish_case(
                case,
                case_id=f"procurement_allocation_v1.inference_v1_{surface}.{slug}",
                split=f"inference_v1_{surface}",
                sample_batch=SAMPLE_BATCH,
                noise_seed=NOISE_SEED,
            )
        )
    return tuple(cases)


# --- worlds drawn from a seed domain, for packs no live cell has read ---------

#: Declared ranges a pack draws a world's numbers from, by its seed. v1's fixed
#: numbers sit inside every range; the minimum order is the exception, see
#: ``MOQ_LEVELS``.
RANGES: dict[str, tuple[float, float]] = {
    "good_yield": (0.975, 0.99),
    # Poor quality must cost more than the price it saves, or the signal
    # predicts quality without predicting the better decision: on v1's
    # `price_high_is_good__yield` the full-information optimum buys only the
    # 0.82-yield suppliers, because a fifth more units at a third less per
    # unit is the cheaper lot (incident P-D-13). Below 0.62 a poor lot costs
    # more per good unit than any good lot the price scale allows.
    "poor_yield": (0.45, 0.62),
    "price_base_usd": (0.50, 0.70),
    # The spread across a component's four suppliers, as a share of the base.
    # v1 spread 0.40 over 0.60, a dearest-to-cheapest ratio of 1.67, and at
    # that ratio a cheap poor lot beats a dear good lot in the optimum even
    # at a yield of 0.5; a ratio below 1.3 keeps the signal's direction and
    # the profitable direction the same in every yield and timing world.
    "price_spread_over_base": (0.15, 0.30),
    "lead_short_days": (3, 4),
    # A gap of two rounds two of the four positions onto the same day, and a
    # tie between a good and a poor supplier is no signal.
    "lead_gap_days": (3, 4),
    "lead_neutral_days": (5, 7),
    "poor_on_time": (0.30, 0.50),
    # One lot, as in v1: two such suppliers cover the target, so a wrong
    # direction in a capacity world costs actions rather than money. The
    # screen admits capacity worlds without the margin test for that reason.
    "poor_capacity": (10, 10),
    "revenue_usd": (14.0, 18.0),
    "penalty_usd": (2.0, 4.0),
    # The cash budget is a multiple of the dearest basket a rule that reads
    # the signal may order (two 20-unit lots per component at the top price,
    # landed; a 20-unit minimum order forces the second lot),
    # so cash never decides a world whose subject is whom to verify. A fixed
    # range did: at the dear end of the price scale the aligned rule's
    # rounded-up order broke the budget and deferred (seen on 6 of 36 draws).
    "cash_budget_over_dearest_basket": (1.05, 1.25),
    "deadline_days": (22, 28),
    "minimum_kits": (16, 18),
    "sample_cost_usd": (0.20, 0.40),
    "sample_days": (1, 2),
    "sample_batch": (6, 10),
}

#: Minimum-order levels, v1's. The listing states the level as the supplier's
#: claimed minimum order, so the signal is visible before a quote; the private
#: minimum order is the level capped at the supplier's capacity, as in v1. The
#: two differ only for a capacity-poor supplier whose level is 20, where v1
#: capped the private figure to 10 and, because v1 listings never stated a
#: minimum order, left `moq_low_is_good__capacity` with no signal at all
#: (incident P-D-12). Here the listing carries the level and the formal offer
#: the truth, the family's own claim-against-offer design. Levels stay multiples
#: of the order step of 10 and capacities stay at or below 20 because the
#: full-information oracle enumerates two offers per quantity per supplier and
#: eight suppliers at five options each already sit at its limit.
MOQ_LEVELS = {"low": 10, "high": 20, "neutral": 10}
ORDER_STEP = 10
GOOD_CAPACITY = 20
#: Nineteen kits, not v1's twenty. A good supplier's 20-unit lot completes
#: 19 expected kits (20 x 0.975+ yield x 0.99 on time), so at a target of 20
#: the optimum must top up, and the cheapest top-up is often a poor supplier's
#: cheap lot: on v1 and on a first draft of these ranges the full-information
#: plan sourced about half its good units from poor suppliers in most yield
#: worlds (P-D-13). At 19 one good lot is exactly sufficient, and a poor
#: supplier's lots can only compete as a whole substitute, which they lose.
PACK_TARGET_KITS = 19
SUPPLIERS_PER_COMPONENT = 4
#: v1's action budget, kept fixed: two quotes and two samples per component and
#: the award fit exactly, so a wrong first direction cannot be recovered.
PACK_BUDGET_ACTIONS = BUDGET_ACTIONS


def _interleaved(ranks: Sequence[float], good_at: Sequence[bool]) -> bool:
    """True when a rank order does not separate the good suppliers from the poor."""
    good = sorted(rank for rank, good in zip(ranks, good_at) if good)
    poor = sorted(rank for rank, good in zip(ranks, good_at) if not good)
    return min(good) < max(poor) and min(poor) < max(good)


def _pack_supplier(
    component: str,
    label: str,
    *,
    good: bool,
    good_yield: float,
    poor_yield: float,
    unit_price: float,
    lead_time: int,
    moq_level: int,
    risk: str,
    poor_on_time: float,
    poor_capacity: int,
    sample_cost: float,
    sample_days: int,
) -> dict[str, Any]:
    """One supplier of a drawn world; the same shape as ``_supplier_for`` in v1.

    The listing states the minimum-order level as the supplier's claim, so the
    minimum-order signal is as visible before a quote as price and lead time
    are; v1 listings never stated it. The private minimum order is the level
    capped at capacity, exactly as in v1, and the formal offer states that.
    """
    yield_rate = good_yield if good else poor_yield
    on_time, capacity = 0.99, GOOD_CAPACITY
    if risk == "timing":
        yield_rate = good_yield
        on_time = 0.99 if good else poor_on_time
    elif risk == "capacity":
        yield_rate = good_yield
        capacity = GOOD_CAPACITY if good else poor_capacity
    return _supplier(
        component,
        label,
        unit_price=unit_price,
        capacity=capacity,
        moq=min(moq_level, capacity),
        order_step=ORDER_STEP,
        lead_time=lead_time,
        on_time=on_time,
        sample_cost=sample_cost,
        sample_days=sample_days,
        yield_rate=yield_rate,
        verbal_bias={"verified_yield_rate": 0.99, "moq": moq_level},
    )


def sample_definition(signal: str, risk: str, seed: int) -> dict[str, Any]:
    """Draw one world's numbers from ``RANGES`` with a generator seeded by ``seed``.

    The construct is v1's: one visible attribute tracks true quality in the
    declared direction, price carries nothing where it is not the signal, and
    exactly one unlabelled constraint binds. What the seed moves is every
    number around that: the two yield levels, the price scale and the decoy
    price order, lead-time and minimum-order levels, the poor supplier's
    on-time rate or capacity, the objective, the sample terms and the action
    budget, the listing order, and the noise seed. Two worlds of one cell
    therefore differ in their economics, not only in their identifiers.
    """
    if signal not in SIGNALS:
        raise ValueError(f"unknown signal {signal!r}")
    if risk not in RISKS:
        raise ValueError(f"unknown risk {risk!r}")
    rng = random.Random(int(seed))

    def real(key: str, digits: int) -> float:
        low, high = RANGES[key]
        return round(rng.uniform(float(low), float(high)), digits)

    def integer(key: str) -> int:
        low, high = RANGES[key]
        return rng.randint(int(low), int(high))

    good_yield, poor_yield = real("good_yield", 3), real("poor_yield", 3)
    price_base = real("price_base_usd", 2)
    price_spread = round(price_base * real("price_spread_over_base", 3), 4)
    count = SUPPLIERS_PER_COMPONENT
    high_is_good = signal.endswith("high_is_good") or signal.endswith("long_is_good")
    positions = [_position(index, count) for index in range(count)]
    good_at = [(position >= 0.5) == high_is_good for position in positions]

    if signal.startswith("price"):
        price_ranks = list(positions)
    else:
        while True:
            order = list(range(count))
            rng.shuffle(order)
            price_ranks = [order[index] / (count - 1) for index in range(count)]
            if _interleaved(price_ranks, good_at):
                break
    if signal.startswith("lead_time"):
        short, gap = integer("lead_short_days"), integer("lead_gap_days")
        leads = [short + int(round(gap * position)) for position in positions]
    else:
        neutral_lead = integer("lead_neutral_days")
        leads = [neutral_lead] * count
    if signal.startswith("moq"):
        moqs = [MOQ_LEVELS["high"] if position >= 0.5 else MOQ_LEVELS["low"] for position in positions]
    else:
        moqs = [MOQ_LEVELS["neutral"]] * count
    poor_on_time = real("poor_on_time", 2)
    poor_capacity = integer("poor_capacity")
    sample_cost, sample_days = real("sample_cost_usd", 2), integer("sample_days")
    dearest_basket = len(COMPONENTS) * 40 * (price_base + price_spread) * 1.10 + 3.0
    cash_budget = round(dearest_basket * real("cash_budget_over_dearest_basket", 3), 2)

    suppliers: list[dict[str, Any]] = []
    for component in COMPONENTS:
        listing_order = list(range(count))
        rng.shuffle(listing_order)
        for label_index, index in enumerate(listing_order):
            suppliers.append(
                _pack_supplier(
                    component,
                    f"s{label_index}",
                    good=good_at[index],
                    good_yield=good_yield,
                    poor_yield=poor_yield,
                    unit_price=round(price_base + price_spread * price_ranks[index], 4),
                    lead_time=leads[index],
                    moq_level=moqs[index],
                    risk=risk,
                    poor_on_time=poor_on_time,
                    poor_capacity=poor_capacity,
                    sample_cost=sample_cost,
                    sample_days=sample_days,
                )
            )
    return {
        "slug": f"{signal}__{risk}_{int(seed)}",
        "signal": signal,
        "risk": risk,
        "world_seed": int(seed),
        "product_id": f"inference_kit_{int(seed)}",
        "bom": {component: 1 for component in COMPONENTS},
        "budget_actions": PACK_BUDGET_ACTIONS,
        "objective": {
            "target_kits": PACK_TARGET_KITS,
            "revenue": real("revenue_usd", 2),
            "penalty": real("penalty_usd", 2),
            "budget": cash_budget,
            "deadline": integer("deadline_days"),
            "minimum": integer("minimum_kits"),
        },
        "interaction": {"inquiry": 0.05, "quote": 0.1, "counter": 0.15},
        "sample_batch": integer("sample_batch"),
        "noise_seed": int(seed) + 500_000,
        "levels": {
            "good_yield": good_yield,
            "poor_yield": poor_yield,
            "poor_on_time": poor_on_time,
            "poor_capacity": poor_capacity,
        },
        "suppliers": suppliers,
    }


def write_inference_case_matrix(*, surface: str, root: Path | None = None) -> tuple[Path, ...]:
    destination = root or (LABELED_ROOT if surface == "labeled" else OPAQUE_ROOT)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in build_inference_case_matrix(surface=surface):
        path = destination / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        body = json.dumps(case, indent=2, sort_keys=True) + "\n"
        temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, path)
        written.append(path)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=("labeled", "opaque"), required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.write:
        for path in write_inference_case_matrix(surface=arguments.surface, root=arguments.root):
            print(path)
    else:
        for case in build_inference_case_matrix(surface=arguments.surface):
            print(case["case_id"], case["content_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GENERATOR_ID",
    "GOOD_CAPACITY",
    "MOQ_LEVELS",
    "PANEL_ID",
    "RANGES",
    "RISKS",
    "SIGNALS",
    "build_inference_case_matrix",
    "finish_case",
    "sample_definition",
    "world_specs",
    "write_inference_case_matrix",
]
