"""The offline A/A check: one profile dealt into two arms should rarely look like two."""

from __future__ import annotations

import numpy as np
import pytest

from aeread.design import aa_check


def pilot(worlds: int, plays: int, seed: int, drift: float = 0.0) -> dict[int, list[float]]:
    rng = np.random.default_rng(seed)
    level = rng.normal(0.0, 5.0, size=worlds)                       # worlds differ; that is not a difference between arms
    return {w: list(level[w] + rng.standard_exponential(plays) * 3.0 + drift * (np.arange(plays) >= plays // 2)) for w in range(worlds)}


def bootstrap_excludes_zero(arm_a: np.ndarray, arm_b: np.ndarray) -> bool:
    """A percentile bootstrap over worlds, as several paired analyses report."""

    difference = arm_a.mean(axis=1) - arm_b.mean(axis=1)
    rng = np.random.default_rng(1)
    means = difference[rng.integers(0, len(difference), size=(400, len(difference)))].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return bool(low > 0 or high < 0)


def test_the_paired_t_rule_fires_at_its_declared_rate_when_the_arms_are_one_profile() -> None:
    for worlds in (6, 24):
        result = aa_check(pilot(worlds, plays=4, seed=worlds), deals=3000)
        assert (result["worlds"], result["plays_per_arm"]) == (worlds, 2)
        assert result["claim_rate"] == pytest.approx(0.05, abs=0.02)


def test_an_interval_too_narrow_for_few_worlds_shows_as_a_higher_rate() -> None:
    cells = pilot(6, plays=2, seed=5)
    narrow = aa_check(cells, claim_fires=bootstrap_excludes_zero, deals=1500)["claim_rate"]
    assert narrow > 0.09 > aa_check(cells, deals=1500)["claim_rate"]


def test_drift_between_replicate_runs_shows_in_the_recorded_order_only() -> None:
    drifting = aa_check(pilot(24, plays=4, seed=2, drift=6.0), deals=1500)
    assert drifting["as_recorded_fires"] is True                    # later plays against earlier ones
    assert drifting["claim_rate"] < 0.08                            # dealing the plays at random removes it
    assert aa_check(pilot(24, plays=4, seed=2), deals=200)["as_recorded_fires"] is False


def test_unequal_or_odd_replicates_are_refused() -> None:
    with pytest.raises(ValueError, match="same even number"):
        aa_check({1: [1.0, 2.0], 2: [1.0, 2.0, 3.0, 4.0]})
    with pytest.raises(ValueError, match="same even number"):
        aa_check({1: [1.0, 2.0, 3.0], 2: [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="same even number"):
        aa_check({1: [1.0, 2.0]})
    with pytest.raises(ValueError, match="finite"):
        aa_check({1: [1.0, float("nan")], 2: [1.0, 2.0]})
