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


def build_inference_case_matrix(*, surface: str) -> tuple[dict[str, Any], ...]:
    from aeread.shared_runner.run.resolver import case_content_sha256
    from aeread.shared_runner.schemas import CaseManifest

    cases: list[dict[str, Any]] = []
    for ordinal, (slug, world_seed, signal, risk) in enumerate(world_specs(), start=1):
        case = _build_case(
            _definition(slug, world_seed, signal=signal, risk=risk, ordinal=ordinal),
            surface=surface,
        )
        case["case_id"] = f"procurement_allocation_v1.inference_v1_{surface}.{slug}"
        case["split"] = f"inference_v1_{surface}"
        for supplier in case["payload"]["suppliers"]:
            quality = supplier["private_terms"]["quality"]
            quality["sample_size"] = SAMPLE_BATCH
            quality["observed_defects"] = round(
                SAMPLE_BATCH * (1.0 - float(quality["verified_yield_rate"]))
            )
        case["payload"]["interaction"]["sample_noise"] = {
            "model": "binomial",
            "seed": NOISE_SEED,
        }
        case["provenance"] = {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "review_status": "curated",
        }
        # The provenance schema is closed, so what the world was built to test
        # lives in the slug: "<signal>__<risk>". An auditor reads it there, and
        # the buyer never sees it because the slug is not in the payload.
        case["content_sha256"] = "0" * 64
        case["content_sha256"] = case_content_sha256(CaseManifest.from_dict(case))
        cases.append(case)
    return tuple(cases)


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
    "PANEL_ID",
    "RISKS",
    "SIGNALS",
    "build_inference_case_matrix",
    "world_specs",
    "write_inference_case_matrix",
]
