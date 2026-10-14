"""What an admission screen can miss: the operating characteristics of its sampling plan.

A headroom screen runs the frozen control on a candidate world at several
seeds, rejects the world as floored when the control succeeds too rarely and
as saturated when it succeeds too often, and admits the rest. The number of
seeds and the two cut-offs are the sampling plan. A plan is a statement about
a rate measured on a few draws, so it errs in known ways: these functions say
how often.
"""

from __future__ import annotations

from typing import Any

from scipy import stats


def _cutoffs(seeds: int, floored_at_most: int, saturated_at_least: int | None) -> tuple[int, int]:
    if seeds < 1:
        raise ValueError("seeds must be at least 1")
    upper = seeds if saturated_at_least is None else saturated_at_least
    if not 0 <= floored_at_most < upper <= seeds:
        raise ValueError("cut-offs must satisfy 0 <= floored_at_most < saturated_at_least <= seeds")
    return floored_at_most, upper


def admit_probability(
    control_rate: float,
    seeds: int,
    *,
    floored_at_most: int = 0,
    saturated_at_least: int | None = None,
) -> float:
    """Chance the plan admits a world on which the control truly succeeds at ``control_rate``.

    The world is rejected as floored with ``floored_at_most`` successes or
    fewer and as saturated with ``saturated_at_least`` or more. The defaults
    are the rule the QC standard states: floored when the control never
    succeeds, saturated when it always does.
    """

    if not 0 <= control_rate <= 1:
        raise ValueError("control_rate must lie between 0 and 1")
    lower, upper = _cutoffs(seeds, floored_at_most, saturated_at_least)
    # admitted when lower < successes < upper
    return float(stats.binom.cdf(upper - 1, seeds, control_rate) - stats.binom.cdf(lower, seeds, control_rate))


def screen_plan(
    seeds: int,
    *,
    floored_at_most: int = 0,
    saturated_at_least: int | None = None,
    floored_rate: float = 0.05,
    saturated_rate: float = 0.95,
    informative_rate: float = 0.5,
) -> dict[str, Any]:
    """A sampling plan and its miss rates, for the panel manifest.

    ``admits_saturated`` and ``admits_floored`` are the chances of admitting a
    world whose true control rate is the declared saturated or floored rate.
    ``rejects_informative`` is the chance of refusing one at the informative rate.
    """

    lower, upper = _cutoffs(seeds, floored_at_most, saturated_at_least)

    def admit(rate: float) -> float:
        return admit_probability(rate, seeds, floored_at_most=lower, saturated_at_least=upper)

    return {
        "seeds_per_world": seeds,
        "reject_floored_at_most": lower,
        "reject_saturated_at_least": upper,
        "declared_rates": {"floored": floored_rate, "saturated": saturated_rate, "informative": informative_rate},
        "admits_saturated": admit(saturated_rate),
        "admits_floored": admit(floored_rate),
        "rejects_informative": 1.0 - admit(informative_rate),
    }
