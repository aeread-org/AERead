"""An admission screen's sampling plan states what it can miss, and the QC standard prints the same numbers."""

from __future__ import annotations

from pathlib import Path

import pytest

from aeread.design import admit_probability, screen_plan

QC_STANDARD = Path(__file__).resolve().parents[1] / "docs" / "operations" / "benchmark_qc.md"
#: seeds per world, reject as floored at or below, reject as saturated at or above
PLANS = [(1, 0, 1), (3, 0, 3), (5, 0, 5), (10, 0, 10), (10, 1, 9), (20, 2, 18)]


def table_row(seeds: int, floored: int, saturated: int) -> str:
    plan = screen_plan(seeds, floored_at_most=floored, saturated_at_least=saturated)
    near = admit_probability(0.9, seeds, floored_at_most=floored, saturated_at_least=saturated)
    rule = "never or always" if (floored, saturated) == (0, seeds) else f"{floored} or fewer, or {saturated} or more"
    return (f"| {seeds} | {rule} | {plan['admits_saturated']:.0%} | {near:.0%} | {plan['admits_floored']:.0%} "
            f"| {plan['rejects_informative']:.0%} |")


def test_one_seed_cannot_admit_a_world_under_the_stated_rule() -> None:
    for rate in (0.0, 0.3, 0.5, 0.9, 1.0):
        assert admit_probability(rate, 1) == 0.0                     # never-or-always covers both outcomes of one draw
    assert screen_plan(1)["rejects_informative"] == 1.0


def test_a_world_the_control_solves_nine_times_in_ten_usually_slips_through_never_or_always() -> None:
    assert admit_probability(0.9, 3) == pytest.approx(1 - 0.9**3 - 0.1**3)
    assert admit_probability(0.9, 3) < admit_probability(0.9, 10) < admit_probability(0.9, 30)   # more seeds, more often admitted
    assert admit_probability(0.9, 10) == pytest.approx(0.651, abs=0.001)


def test_cutoffs_on_the_rate_trade_the_two_errors_and_more_seeds_shrink_both() -> None:
    loose, tight = screen_plan(10, floored_at_most=1, saturated_at_least=9), screen_plan(20, floored_at_most=2, saturated_at_least=18)
    assert tight["admits_saturated"] < loose["admits_saturated"] < screen_plan(10)["admits_saturated"]
    assert tight["rejects_informative"] < loose["rejects_informative"] < 0.03
    assert tight["admits_saturated"] == pytest.approx(tight["admits_floored"])   # the plan and the declared rates are symmetric


def test_a_certain_world_is_always_classified() -> None:
    for seeds in (3, 10):
        assert admit_probability(1.0, seeds) == 0.0 and admit_probability(0.0, seeds) == 0.0
    assert admit_probability(0.5, 2) == pytest.approx(0.5)            # one success in two


def test_impossible_plans_are_refused() -> None:
    for kwargs in ({"seeds": 0}, {"seeds": 5, "floored_at_most": 5}, {"seeds": 5, "saturated_at_least": 6}, {"seeds": 5, "floored_at_most": 3, "saturated_at_least": 3}):
        with pytest.raises(ValueError):
            screen_plan(**kwargs)
    with pytest.raises(ValueError):
        admit_probability(1.2, 5)


def test_the_qc_standard_prints_the_numbers_the_function_gives() -> None:
    text = QC_STANDARD.read_text(encoding="utf-8")
    for plan in PLANS:
        assert table_row(*plan) in text, table_row(*plan)
