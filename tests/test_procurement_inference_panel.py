"""The inference panel: worlds where a fixed rule cannot win everywhere.

Twelve earlier panels failed because suppliers were indistinguishable before
verification, which makes "verify what you can afford and award the best"
optimal and leaves no gap for an agent to demonstrate anything. These tests pin
the three properties that change that, so a later edit which quietly restores
the old shape fails here rather than in a screen or, worse, in a published run.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
)
from aeread_families.procurement_allocation.inference_case_matrix import (
    RISKS,
    SIGNALS,
    _quality_for,
    _visible_attributes,
    build_inference_case_matrix,
    world_specs,
)

SURFACES = ("labeled", "opaque")
COUNT = 4


@pytest.fixture(scope="module")
def labeled() -> tuple[dict, ...]:
    return build_inference_case_matrix(surface="labeled")


# --- the panel is well formed ------------------------------------------------


@pytest.mark.parametrize("surface", SURFACES)
def test_every_case_is_valid_and_self_describing(surface: str) -> None:
    plugin = ProcurementAllocationPlugin()
    cases = build_inference_case_matrix(surface=surface)
    assert len(cases) == len(SIGNALS) * len(RISKS) == 18
    for case in cases:
        plugin.validate_payload(case["payload"])
        assert case_content_sha256(CaseManifest.from_dict(case)) == case["content_sha256"]


def test_worlds_have_distinct_seeds_and_content(labeled: tuple) -> None:
    assert len({case["world_seed"] for case in labeled}) == len(labeled)
    assert len({case["content_sha256"] for case in labeled}) == len(labeled)


def test_the_generator_is_deterministic() -> None:
    first = json.dumps(build_inference_case_matrix(surface="labeled"), sort_keys=True)
    second = json.dumps(build_inference_case_matrix(surface="labeled"), sort_keys=True)
    assert first == second


# --- property one: a visible attribute really predicts quality ---------------


@pytest.mark.parametrize("signal", SIGNALS)
def test_the_signal_attribute_predicts_quality(signal: str) -> None:
    """Otherwise there is nothing to infer and the panel is the old one again."""
    qualities = [_quality_for(signal, index, COUNT) for index in range(COUNT)]
    assert len(set(qualities)) == 2, f"{signal} does not separate suppliers"
    attribute = "unit_price" if signal.startswith("price") else (
        "lead_time" if signal.startswith("lead_time") else "moq")
    values = [_visible_attributes(signal, index, COUNT)[attribute] for index in range(COUNT)]
    good = [v for v, q in zip(values, qualities) if q > 0.9]
    poor = [v for v, q in zip(values, qualities) if q <= 0.9]
    if signal.endswith("high_is_good") or signal.endswith("long_is_good"):
        assert min(good) > max(poor), f"{signal}: high values must mark good suppliers"
    else:
        assert max(good) < min(poor), f"{signal}: low values must mark good suppliers"


@pytest.mark.parametrize("signal", [s for s in SIGNALS if not s.startswith("price")])
def test_price_carries_no_signal_when_it_is_not_the_signal(signal: str) -> None:
    """The flaw that made 'buy the dearest' win 9 of 12 in an earlier version.

    If price tracked quality in every world, the signal was always price wearing
    a different name, and one fixed rule swept the panel.
    """
    prices = [_visible_attributes(signal, i, COUNT)["unit_price"] for i in range(COUNT)]
    qualities = [_quality_for(signal, i, COUNT) for i in range(COUNT)]
    good_prices = sorted(p for p, q in zip(prices, qualities) if q > 0.9)
    poor_prices = sorted(p for p, q in zip(prices, qualities) if q <= 0.9)
    assert min(good_prices) < max(poor_prices) and min(poor_prices) < max(good_prices), (
        f"{signal}: price still separates good from poor suppliers")


def test_both_directions_of_every_signal_are_present() -> None:
    """A panel that only rewarded 'dearer is better' is swept by one rule."""
    families = Counter(s.rsplit("_", 3)[0] for s in SIGNALS)
    assert set(families.values()) == {2}, families
    highs = sum(1 for s in SIGNALS if s.endswith("high_is_good") or s.endswith("long_is_good"))
    assert highs == len(SIGNALS) - highs


# --- property two: the binding risk varies and is unlabelled ----------------


def test_every_risk_appears_and_none_is_labelled_in_the_payload(labeled: tuple) -> None:
    specs = world_specs()
    assert {risk for _, _, _, risk in specs} == set(RISKS)
    for case in labeled:
        body = json.dumps(case["payload"])
        # Risk words are checked through the slug rather than through the body,
        # because "capacity" and "yield" are legitimate supplier field names. The
        # label to keep out of the buyer's reach is the world's own description.
        for signal in SIGNALS:
            assert signal not in body, "the payload must not name the signal"
        assert case["case_id"].rsplit(".", 1)[-1] not in body
        assert "binding_risk" not in body and "declared_signal" not in body


@pytest.mark.parametrize("risk", RISKS)
def test_each_risk_actually_binds_somewhere(risk: str) -> None:
    """A declared risk that changes no supplier field is decoration."""
    from aeread_families.procurement_allocation.inference_case_matrix import _supplier_for
    component = "sht30_i2c"
    good = _supplier_for(component, 0, COUNT, signal="price_low_is_good", risk=risk)
    poor = _supplier_for(component, 3, COUNT, signal="price_low_is_good", risk=risk)
    field = {"yield": ("quality", "verified_yield_rate"),
             "timing": ("on_time_probability",),
             "capacity": ("capacity",)}[risk]
    def read(supplier):
        value = supplier["private_terms"]
        for key in field:
            value = value[key]
        return value
    assert read(good) != read(poor), f"{risk} does not distinguish suppliers"
