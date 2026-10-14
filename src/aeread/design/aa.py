"""An A/A check: how often a claim rule fires when both arms are the same profile.

The full A/A run puts one profile in both arms and sends it through execution,
scoring and analysis. This is its offline half: it takes the replicate plays a
pilot already has for one profile, deals them into two arms world by world, and
runs the campaign's claim rule on the result. It tests the analysis and the
claim rule on the pilot's own score distribution. It cannot see an artifact of
execution, such as seat order or a tie-break, which only the live run exercises.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
from scipy import stats


def paired_t_excludes_zero(arm_a: np.ndarray, arm_b: np.ndarray, *, alpha: float = 0.05) -> bool:
    """The default claim rule: the paired t interval on world means excludes zero."""

    difference = arm_a.mean(axis=1) - arm_b.mean(axis=1)
    spread = float(difference.std(ddof=1))
    if spread == 0:
        return bool(difference.mean() != 0)
    half = float(stats.t.ppf(1 - alpha / 2, len(difference) - 1)) * spread / math.sqrt(len(difference))
    return bool(abs(float(difference.mean())) > half)


def aa_check(
    plays_by_world: Mapping[Any, Sequence[float]],
    *,
    claim_fires: Callable[[np.ndarray, np.ndarray], bool] = paired_t_excludes_zero,
    deals: int = 2_000,
    seed: int = 20261013,
) -> dict[str, Any]:
    """Deal one profile's replicate plays into two arms and count how often the claim rule fires.

    ``plays_by_world`` maps each world to the scores of its replicate plays of
    one profile; every world needs the same even number of plays. ``claim_fires``
    receives two worlds x plays arrays. With a sound analysis ``claim_rate`` is
    close to the rule's declared error rate. An interval that is too narrow for
    the number of worlds, such as a percentile bootstrap over a handful of
    worlds, shows up as a higher rate. ``as_recorded_fires`` compares the plays
    in the order they were recorded, first half against second, which is where
    drift between replicate runs would show.
    """

    rows = [list(plays_by_world[world]) for world in sorted(plays_by_world, key=repr)]
    lengths = {len(row) for row in rows}
    if len(rows) < 2 or len(lengths) != 1 or min(lengths) < 2 or min(lengths) % 2:
        raise ValueError("every world needs the same even number of replicate plays, and at least 2 worlds")
    table = np.asarray(rows, dtype=float)
    if not np.isfinite(table).all():
        raise ValueError("replicate scores must be finite")
    if deals < 1:
        raise ValueError("deals must be positive")
    half = table.shape[1] // 2
    rng = np.random.default_rng(seed)
    fired = 0
    for _ in range(deals):
        dealt = rng.permuted(table, axis=1)
        fired += bool(claim_fires(dealt[:, :half], dealt[:, half:]))
    return {
        "worlds": int(table.shape[0]),
        "plays_per_arm": half,
        "deals": deals,
        "seed": seed,
        "claim_rate": fired / deals,
        "as_recorded_fires": bool(claim_fires(table[:, :half], table[:, half:])),
    }
