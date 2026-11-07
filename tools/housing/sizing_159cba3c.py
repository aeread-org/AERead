"""How many independent worlds a paired comparison needs, and the record of that arithmetic."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from scipy import stats

from aeread.shared_runner.run.contract import sealed

SIZING_SCHEMA = "aeread.design.sizing/1"
SIZING_METHOD = (
    "paired t on per-world differences: the smallest n with "
    "n >= ((t(n-1, 1-alpha/2) + z(power)) * sd / effect)^2, then n / (1 - attrition) rounded up"
)


def _finite_positive(name: str, value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return numeric


def _share(name: str, value: float, *, allow_zero: bool = False) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric >= 1 or numeric < 0 or (numeric == 0 and not allow_zero):
        raise ValueError(f"{name} must lie strictly between 0 and 1" + (" or equal 0" if allow_zero else ""))
    return numeric


def sd_of_differences(var_world: float, var_play: float, plays: int = 1) -> float:
    """SD of one world's paired difference when each arm plays the world ``plays`` times.

    ``var_world`` is how much the true difference varies from world to world and
    ``var_play`` how much one play's difference varies inside a world. Repeats
    shrink only the second term, which is why more worlds usually buys more than
    more plays.
    """

    if plays < 1:
        raise ValueError("plays must be at least 1")
    if var_world < 0 or var_play < 0:
        raise ValueError("variances cannot be negative")
    return math.sqrt(var_world + var_play / plays)


def _worlds_before_attrition(sd: float, effect: float, power: float, alpha: float) -> int:
    ratio = sd / effect
    z_power = float(stats.norm.ppf(power))
    # The normal formula is a lower bound: the t multiplier is larger at every n.
    n = max(2, math.ceil(((float(stats.norm.ppf(1 - alpha / 2)) + z_power) * ratio) ** 2))
    while n < ((float(stats.t.ppf(1 - alpha / 2, n - 1)) + z_power) * ratio) ** 2:
        n += 1
    return n


def worlds_needed(
    sd_of_differences: float,
    minimum_effect: float,
    *,
    power: float = 0.8,
    alpha: float = 0.05,
    attrition: float = 0.0,
) -> int:
    """Worlds to freeze so a paired gap of ``minimum_effect`` is detected with ``power``.

    The unit is the independent cluster, a world or a cluster of twins, and
    ``sd_of_differences`` is the SD of its paired difference after repeats are
    averaged. ``attrition`` is the declared share of worlds expected to drop out
    of the pairing; the count is inflated so the surviving worlds still reach it.
    """

    sd = _finite_positive("sd_of_differences", sd_of_differences)
    effect = _finite_positive("minimum_effect", abs(minimum_effect))
    n = _worlds_before_attrition(sd, effect, _share("power", power), _share("alpha", alpha))
    return math.ceil(n / (1 - _share("attrition", attrition, allow_zero=True)))


def smallest_detectable_effect(
    sd_of_differences: float, worlds: int, *, power: float = 0.8, alpha: float = 0.05
) -> float:
    """The paired gap ``worlds`` worlds detect with ``power``: ``worlds_needed`` solved for the effect."""

    if worlds < 2:
        raise ValueError("worlds must be at least 2")
    sd = _finite_positive("sd_of_differences", sd_of_differences)
    multiplier = float(stats.t.ppf(1 - _share("alpha", alpha) / 2, worlds - 1)) + float(stats.norm.ppf(_share("power", power)))
    return multiplier * sd / math.sqrt(worlds)


def detection_rate(
    sd_of_differences: float,
    effect: float,
    worlds: int,
    *,
    alpha: float = 0.05,
    draws: int = 20_000,
    seed: int = 20261013,
) -> float:
    """Simulated share of campaigns whose paired t interval excludes zero on the effect's side.

    Per-world differences are drawn normal with the given mean and SD. At
    ``effect = 0`` the result is the false-positive rate of one side.
    """

    if worlds < 2 or draws < 1:
        raise ValueError("worlds must be at least 2 and draws positive")
    sd = _finite_positive("sd_of_differences", sd_of_differences)
    rng = np.random.default_rng(seed)
    sample = rng.normal(float(effect), sd, size=(draws, worlds))
    mean = sample.mean(axis=1)
    half = float(stats.t.ppf(1 - _share("alpha", alpha) / 2, worlds - 1)) * sample.std(axis=1, ddof=1) / math.sqrt(worlds)
    side = 1.0 if effect >= 0 else -1.0
    return float(np.mean(side * mean > half))


def sizing_record(
    *,
    sd_of_differences: float,
    minimum_effect: float,
    pilot_worlds: int,
    pilot_source: str,
    power: float = 0.8,
    alpha: float = 0.05,
    attrition: float = 0.0,
) -> dict[str, Any]:
    """The sizing arithmetic as one sealed record, written at ``confirmatory_freeze``.

    It holds the declared inputs and the resulting counts only, so its digest
    does not depend on the interpreter or the SciPy build that computed it.
    """

    if pilot_worlds < 2:
        raise ValueError("a pilot needs at least 2 worlds to give an SD of differences")
    if not pilot_source:
        raise ValueError("pilot_source names the bundle or run the SD was measured on")
    before = _worlds_before_attrition(
        _finite_positive("sd_of_differences", sd_of_differences),
        _finite_positive("minimum_effect", abs(minimum_effect)),
        _share("power", power),
        _share("alpha", alpha),
    )
    return sealed(
        {
            "schema_version": SIZING_SCHEMA,
            "method": SIZING_METHOD,
            "inputs": {
                "sd_of_differences": float(sd_of_differences),
                "minimum_effect": abs(float(minimum_effect)),
                "power": float(power),
                "alpha": float(alpha),
                "attrition": float(attrition),
                "pilot_worlds": int(pilot_worlds),
                "pilot_source": pilot_source,
            },
            "worlds_before_attrition": before,
            "worlds": math.ceil(before / (1 - _share("attrition", attrition, allow_zero=True))),
        }
    )


def verify_sizing_record(record: Mapping[str, Any], *, frozen_worlds: int | None = None) -> None:
    """Raise unless the record recomputes from its own inputs and, if given, covers the frozen pack."""

    if record.get("schema_version") != SIZING_SCHEMA:
        raise ValueError(f"not a sizing record: schema_version {record.get('schema_version')!r}")
    inputs = dict(record.get("inputs") or {})
    expected = sizing_record(**inputs)
    if dict(record) != expected:
        raise ValueError("sizing record does not recompute from its inputs")
    if frozen_worlds is not None and frozen_worlds < expected["worlds"]:
        raise ValueError(
            f"the frozen pack has {frozen_worlds} worlds and the sizing record needs {expected['worlds']}"
        )
