"""Which interval holds its stated coverage when independent worlds are few."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats


def coverage(worlds: int, campaigns: int = 4000, resamples: int = 1000, seed: int = 20261013) -> tuple[float, float]:
    """Share of simulated campaigns with no true gap whose 95% interval contains zero: (world bootstrap, paired t)."""

    rng = np.random.default_rng(seed)
    difference = rng.normal(0.0, 1.0, size=(campaigns, worlds))     # one paired difference per world
    mean, spread = difference.mean(axis=1), difference.std(axis=1, ddof=1)
    half = float(stats.t.ppf(0.975, worlds - 1)) * spread / math.sqrt(worlds)
    t_covers = float(np.mean(np.abs(mean) <= half))
    boot_covers = 0
    for row in difference:
        means = row[rng.integers(0, worlds, size=(resamples, worlds))].mean(axis=1)
        low, high = np.percentile(means, [2.5, 97.5])
        boot_covers += low <= 0.0 <= high
    return boot_covers / campaigns, t_covers


def test_the_world_bootstrap_is_too_narrow_below_fifty_worlds_and_the_t_interval_is_not() -> None:
    found = {worlds: coverage(worlds) for worlds in (10, 20, 50)}
    for worlds, (_, t_covers) in found.items():
        assert t_covers == pytest.approx(0.95, abs=0.012), worlds     # the paired t interval holds at every size
    assert found[10][0] < 0.925 and found[20][0] < 0.94               # the percentile bootstrap claims 95%
    assert found[50][0] == pytest.approx(0.95, abs=0.015)             # and reaches it by about fifty worlds
    assert found[10][0] < found[20][0] < found[50][0]
