"""Declared sampling noise, and the properties that make it usable as evidence.

Perfect verification settles a supplier in one draw, so there is no stopping
problem and award feasibility becomes a deterministic step in the action budget
(design review defects 17 and 18). Noisy sampling turns a single settlement into
an accumulation, which is the precondition for the family's own questions about
what to check and when to stop checking.

Three properties have to hold for the noise to be admissible evidence rather
than merely present. It must be off unless a case declares it, so no sealed
panel changes. It must be reproducible from the contract alone, so a receipt
replays. And it must not leak the truth it is hiding, so a buyer's estimate is
an estimate.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
    _binomial_defects,
)

PANEL = (
    Path(__file__).resolve().parents[1]
    / "cases"
    / "procurement_allocation_v1"
    / "duediligence_v1"
    / "labeled"
)


def _payload(noise: dict | None = None) -> dict:
    payload = json.loads(
        sorted(PANEL.glob("*.json"))[0].read_text(encoding="utf-8")
    )["payload"]
    payload = copy.deepcopy(payload)
    if noise is not None:
        payload["interaction"]["sample_noise"] = noise
    return payload


def _payload_with_noise(payload: dict, seed: int) -> dict:
    noisy = copy.deepcopy(payload)
    noisy["interaction"]["sample_noise"] = {"model": "binomial", "seed": seed}
    return noisy


def _sample(payload: dict, supplier_id: str, times: int) -> dict:
    """Quote then sample one supplier ``times`` times, returning its record."""
    plugin = ProcurementAllocationPlugin()
    case = plugin.validate_payload(payload)
    phase = plugin.phases(case)[0]
    state = plugin.initial_state(case, None)
    actions = [{"action": "request_quote", "supplier_id": supplier_id, "message": "quote"}]
    actions += [
        {"action": "request_sample", "supplier_id": supplier_id, "message": "sample"}
    ] * times
    for action in actions:
        parsed = plugin.parse_action(case, state, "buyer", phase, action)
        assert parsed.ok, parsed.error
        legality = plugin.legal(case, state, "buyer", phase, parsed.action)
        state = plugin.step(
            case,
            state,
            phase,
            {
                "buyer": ActionEnvelope(
                    seat_id="buyer",
                    valid=legality.legal,
                    action=parsed.action,
                    parse=parsed,
                    legality=legality,
                )
            },
        ).state
    return state["quality_evidence"][supplier_id]


def _first_supplier(payload: dict) -> str:
    return str(payload["suppliers"][0]["supplier_id"])


# --- the default must not move ---------------------------------------------


def test_noise_is_off_unless_declared() -> None:
    """Every sealed panel omits the block and must keep perfect verification."""
    payload = _payload()
    record = _sample(payload, _first_supplier(payload), 1)
    assert "verified_yield_rate" in record
    assert "observed_yield_rate" not in record


def test_a_second_draw_buys_nothing_without_noise() -> None:
    """It still costs a day and a fee; what it cannot do is add information.

    Comparing the whole record would compare `verified_day`, which advances by
    the sample lead time on every draw. The claim under test is narrower and is
    the reason there is no stopping problem under perfect verification.
    """
    payload = _payload()
    supplier = _first_supplier(payload)
    informational = ("verified_yield_rate", "observed_defects", "sample_size")
    once = _sample(payload, supplier, 1)
    twice = _sample(payload, supplier, 2)
    assert {k: once[k] for k in informational} == {k: twice[k] for k in informational}
    assert twice["verified_day"] > once["verified_day"]


# --- the contract ------------------------------------------------------------


@pytest.mark.parametrize(
    "noise",
    [
        {"model": "gaussian", "seed": 7},
        {"model": "binomial"},
        {"seed": 7},
        {"model": "binomial", "seed": 7, "extra": 1},
        {"model": "binomial", "seed": 0},
        "binomial",
    ],
)
def test_a_malformed_noise_block_is_rejected(noise: object) -> None:
    """An unreadable declaration must fail loudly, never fall back to perfect."""
    payload = _payload()
    payload["interaction"]["sample_noise"] = noise
    with pytest.raises(ValueError):
        ProcurementAllocationPlugin().validate_payload(payload)


# --- reproducibility ---------------------------------------------------------


def test_the_same_contract_reproduces_the_same_draws() -> None:
    """A receipt replays only if the draw is a function of the declared seed."""
    supplier = _first_supplier(_payload())
    first = _sample(_payload({"model": "binomial", "seed": 11}), supplier, 3)
    second = _sample(_payload({"model": "binomial", "seed": 11}), supplier, 3)
    assert first == second


def test_a_different_seed_gives_a_different_realisation() -> None:
    """Otherwise the seed is decorative and the noise is not really random."""
    supplier = _first_supplier(_payload())
    seeds = {
        _sample(_payload({"model": "binomial", "seed": seed}), supplier, 1)[
            "observed_defects"
        ]
        for seed in range(1, 40)
    }
    assert len(seeds) > 1


def test_draws_are_independent_across_batches() -> None:
    """A second batch must be a fresh draw, not a repeat of the first."""
    counts = {
        _binomial_defects(
            seed=5,
            supplier_id="s",
            draw_index=index,
            sample_size=40,
            defect_rate=0.25,
        )
        for index in range(12)
    }
    assert len(counts) > 1


def test_the_draw_is_calibrated_to_the_true_defect_rate() -> None:
    """Averaged over many batches the estimate must find the truth."""
    total = sum(
        _binomial_defects(
            seed=3,
            supplier_id="s",
            draw_index=index,
            sample_size=100,
            defect_rate=0.20,
        )
        for index in range(200)
    )
    assert 0.18 <= total / (200 * 100) <= 0.22


@pytest.mark.parametrize("rate,expected", [(0.0, 0), (1.0, 50)])
def test_degenerate_rates_are_exact(rate: float, expected: int) -> None:
    assert (
        _binomial_defects(
            seed=1, supplier_id="s", draw_index=0, sample_size=50, defect_rate=rate
        )
        == expected
    )


# --- accumulation, and not leaking the answer -------------------------------


def test_evidence_accumulates_across_draws() -> None:
    payload = _payload({"model": "binomial", "seed": 11})
    supplier = _first_supplier(payload)
    one = _sample(payload, supplier, 1)
    three = _sample(payload, supplier, 3)
    assert one["draws"] == 1 and three["draws"] == 3
    assert three["sample_size"] == 3 * one["sample_size"]
    assert three["observed_defects"] >= one["observed_defects"]


def test_the_buyer_never_sees_the_true_rate() -> None:
    """The whole point: the record carries an estimate, not the answer."""
    payload = _payload({"model": "binomial", "seed": 11})
    supplier = _first_supplier(payload)
    record = _sample(payload, supplier, 2)
    assert "verified_yield_rate" not in record
    assert "observed_yield_rate" in record
    assert "verified_yield_rate" not in json.dumps(record)


def test_the_estimate_converges_on_the_truth() -> None:
    """Accumulation must be worth something, or stopping is not a real decision."""
    payload = _payload({"model": "binomial", "seed": 11})
    supplier_terms = payload["suppliers"][0]["private_terms"]["quality"]
    supplier_terms["verified_yield_rate"] = 0.60
    supplier_terms["sample_size"] = 5
    supplier = _first_supplier(payload)
    near = abs(_sample(payload, supplier, 1)["observed_yield_rate"] - 0.60)
    far = abs(_sample(payload, supplier, 12)["observed_yield_rate"] - 0.60)
    assert far <= near


def _award_margin(payload: dict, seed: int | None) -> float:
    """Quote and sample one qualifying supplier per component, then award all of them.

    Every component in the bill of materials must be covered. An award that
    leaves one uncovered completes zero kits whatever the yields are, so it never
    reaches the yield arithmetic and cannot detect which yield the scorer used.
    """
    noisy = copy.deepcopy(payload)
    if seed is not None:
        noisy["interaction"]["sample_noise"] = {"model": "binomial", "seed": seed}
    plugin = ProcurementAllocationPlugin()
    case = plugin.validate_payload(noisy)
    phase = plugin.phases(case)[0]
    state = plugin.initial_state(case, None)
    required = case["policy"]["required_variant_by_component"]

    chosen = {}
    for supplier in case["suppliers"]:
        component = supplier["component"]
        if component in chosen:
            continue
        if supplier["private_terms"]["variant_id"] == required[component]:
            chosen[component] = str(supplier["supplier_id"])
    assert set(chosen) == set(case["objective"]["bom"]), chosen

    def play(action: dict) -> None:
        nonlocal state
        parsed = plugin.parse_action(case, state, "buyer", phase, action)
        assert parsed.ok, parsed.error
        legality = plugin.legal(case, state, "buyer", phase, parsed.action)
        state = plugin.step(
            case, state, phase,
            {"buyer": ActionEnvelope("buyer", legality.legal, parsed.action, parsed, legality)},
        ).state

    for supplier_id in chosen.values():
        play({"action": "request_quote", "supplier_id": supplier_id, "message": "quote"})
        play({"action": "request_sample", "supplier_id": supplier_id, "message": "sample"})

    lines = []
    for supplier_id in chosen.values():
        offer = next(
            value for value in state["offers"].values()
            if str(value["supplier_id"]) == supplier_id
        )
        lines.append({"offer_id": offer["offer_id"], "quantity": int(offer["capacity"])})
    play({"action": "submit_award", "award_lines": lines, "reason": None})

    terminal = plugin.terminal(case, state)
    outcome = plugin.outcome(case, terminal)
    assert outcome["completed_kits"] > 0, "award must complete kits to exercise yield"
    return float(outcome["contribution_margin_usd"])


def test_scoring_uses_ground_truth_not_the_buyers_estimate() -> None:
    """A lucky draw must not make a supplier more profitable than it is.

    The same award is placed under three different noise seeds, so the buyer's
    observed yield differs each time while the supplier's real yield does not.
    The economics must follow the supplier. If the scorer read the buyer's own
    estimate instead, these margins would separate, and sampling more would pay
    by producing a flattering number rather than a truer one.
    """
    payload = _payload()
    # A small batch, so the estimate is genuinely uncertain and moves between
    # seeds. The true yield is lowered only slightly: drop it far and the world
    # stops being legal, because its full-information optimum no longer beats
    # deferring, which is design-review defect 17 showing up in a unit test.
    for supplier in payload["suppliers"]:
        supplier["private_terms"]["quality"]["sample_size"] = 20
        supplier["private_terms"]["quality"]["verified_yield_rate"] = 0.95

    seeds = (3, 5, 9)
    observed = {
        _sample(_payload_with_noise(payload, seed), _first_supplier(payload), 1)[
            "observed_yield_rate"
        ]
        for seed in seeds
    }
    assert len(observed) > 1, "seeds must actually produce different estimates"

    margins = {round(_award_margin(payload, seed), 8) for seed in seeds}
    assert len(margins) == 1, f"margin followed the buyer's estimate: {margins}"
    assert margins == {round(_award_margin(payload, None), 8)}
