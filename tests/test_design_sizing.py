"""The shared sizing calculation delivers its declared power and seals its own arithmetic."""

from __future__ import annotations

import math

import pytest

from aeread.design import (
    detection_rate,
    sd_of_differences,
    sizing_record,
    smallest_detectable_effect,
    verify_sizing_record,
    worlds_needed,
)


@pytest.mark.parametrize("ratio", [0.9, 1.6, 2.7, 5.0])  # sd / effect: about 6, 23, 60 and 199 worlds
def test_the_count_delivers_the_declared_power_from_few_worlds_to_many(ratio: float) -> None:
    worlds = worlds_needed(ratio, 1.0, power=0.8)
    assert 0.78 <= detection_rate(ratio, 1.0, worlds) <= 0.86
    assert detection_rate(ratio, 1.0, max(2, worlds // 2)) < 0.62  # half the worlds does not


def test_no_effect_is_detected_at_the_declared_error_rate() -> None:
    for worlds in (6, 20, 80):
        assert detection_rate(3.0, 0.0, worlds) == pytest.approx(0.025, abs=0.005)  # one side of a 5% rule


def test_few_worlds_cost_more_than_the_normal_formula_says() -> None:
    normal = math.ceil(((1.959964 + 0.841621) * 0.9) ** 2)
    assert worlds_needed(0.9, 1.0) > normal            # the t multiplier is larger when worlds are few
    assert worlds_needed(20.0, 1.0) == pytest.approx(4 * worlds_needed(10.0, 1.0), rel=0.01)  # half the effect, four times the worlds


def test_attrition_inflates_the_count_so_the_survivors_still_reach_it() -> None:
    base = worlds_needed(250.0, 50.0)
    assert worlds_needed(250.0, 50.0, attrition=0.2) == math.ceil(base / 0.8)
    assert worlds_needed(250.0, -50.0) == base           # the sign of the effect does not matter


def test_the_detectable_effect_is_the_same_relation_solved_the_other_way() -> None:
    effect = smallest_detectable_effect(250.0, 60)
    assert worlds_needed(250.0, effect * 1.01) <= 60 < worlds_needed(250.0, effect * 0.9)


def test_repeat_plays_shrink_only_the_play_part() -> None:
    assert sd_of_differences(9.0, 16.0, plays=1) == 5.0
    assert sd_of_differences(9.0, 16.0, plays=4) == pytest.approx(math.sqrt(13.0))
    assert sd_of_differences(9.0, 16.0, plays=10_000) == pytest.approx(3.0, abs=0.001)  # the world part stays


def test_the_sizing_record_holds_inputs_and_counts_and_recomputes() -> None:
    record = sizing_record(sd_of_differences=250.0, minimum_effect=50.0, pilot_worlds=24, pilot_source="evidence/x/pilot_v1", attrition=0.1)
    assert record["worlds_before_attrition"] == worlds_needed(250.0, 50.0)
    assert record["worlds"] == worlds_needed(250.0, 50.0, attrition=0.1)
    assert set(record) == {"schema_version", "method", "inputs", "worlds_before_attrition", "worlds", "artifact_sha256"}
    assert record == sizing_record(**record["inputs"])     # equal inputs, equal digest
    verify_sizing_record(record, frozen_worlds=record["worlds"])


def test_a_changed_or_undersized_record_is_refused() -> None:
    record = sizing_record(sd_of_differences=250.0, minimum_effect=50.0, pilot_worlds=24, pilot_source="evidence/x/pilot_v1")
    with pytest.raises(ValueError, match="does not recompute"):
        verify_sizing_record({**record, "worlds": record["worlds"] - 40})
    with pytest.raises(ValueError, match="does not recompute"):
        verify_sizing_record({**record, "inputs": {**record["inputs"], "minimum_effect": 80.0}})
    with pytest.raises(ValueError, match="needs"):
        verify_sizing_record(record, frozen_worlds=record["worlds"] - 1)
    with pytest.raises(ValueError, match="not a sizing record"):
        verify_sizing_record({"schema_version": "something/else"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sd_of_differences": 0.0, "minimum_effect": 1.0},
        {"sd_of_differences": 1.0, "minimum_effect": 0.0},
        {"sd_of_differences": float("nan"), "minimum_effect": 1.0},
        {"sd_of_differences": 1.0, "minimum_effect": 1.0, "power": 1.0},
        {"sd_of_differences": 1.0, "minimum_effect": 1.0, "attrition": 1.0},
    ],
)
def test_inputs_that_cannot_size_a_campaign_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        worlds_needed(**kwargs)
