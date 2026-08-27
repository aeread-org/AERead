"""Shared paired analysis with nested repeats and world-cluster uncertainty."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
from scipy import stats


def _score_row(row: Mapping[str, Any]) -> float | None:
    if row.get("status") != "completed":
        return None
    score = row.get("within_case_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    numeric = float(score)
    if not math.isfinite(numeric) or numeric > 1.0:
        raise ValueError(
            "completed within_case_score must be finite and no greater than 1; "
            "negative legal outcomes are allowed"
        )
    return numeric



def _declared_score_support(
    score_support_by_world: Mapping[int, Sequence[float]] | None,
    world_seed: int,
) -> tuple[float, float] | None:
    if score_support_by_world is None or world_seed not in score_support_by_world:
        return None
    support = score_support_by_world[world_seed]
    if isinstance(support, (str, bytes)) or len(support) != 2:
        raise ValueError("score support must contain exactly lower and upper bounds")
    lower, upper = support
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in (lower, upper)
    ):
        raise ValueError("score support bounds must be numeric")
    numeric_lower, numeric_upper = float(lower), float(upper)
    if not math.isfinite(numeric_lower) or not math.isfinite(numeric_upper):
        raise ValueError("score support bounds must be finite")
    if numeric_lower > numeric_upper or numeric_upper > 1.0:
        raise ValueError("score support must satisfy lower <= upper <= 1")
    return numeric_lower, numeric_upper



def _percentile_interval(values: np.ndarray) -> list[float]:
    return [
        float(np.percentile(values, 2.5)),
        float(np.percentile(values, 97.5)),
    ]



def analyze_paired_results(
    rows: Iterable[Mapping[str, Any]],
    *,
    control_condition: str,
    treatment_condition: str,
    expected_replicates: int,
    bootstrap_draws: int = 10_000,
    bootstrap_seed: int = 20260826,
    score_support_by_world: Mapping[int, Sequence[float]] | None = None,
) -> dict[str, Any]:
    """Aggregate nested replicates and compare conditions at the world-cluster level."""

    if control_condition == treatment_condition:
        raise ValueError("control and treatment conditions must differ")
    if expected_replicates < 1:
        raise ValueError("expected_replicates must be positive")
    if bootstrap_draws < 1:
        raise ValueError("bootstrap_draws must be positive")
    materialized = [dict(row) for row in rows]
    allowed_conditions = {control_condition, treatment_condition}
    by_identity: dict[tuple[str, int, int], dict[str, Any]] = {}
    failures = {control_condition: 0, treatment_condition: 0}
    for row in materialized:
        condition = row.get("condition_id")
        world_seed = row.get("world_seed")
        replicate = row.get("replicate_index")
        if condition not in allowed_conditions:
            raise ValueError(f"unexpected condition_id: {condition!r}")
        if isinstance(world_seed, bool) or not isinstance(world_seed, int):
            raise ValueError("world_seed must be an integer")
        if isinstance(replicate, bool) or not isinstance(replicate, int):
            raise ValueError("replicate_index must be an integer")
        identity = (condition, world_seed, replicate)
        if identity in by_identity:
            raise ValueError(f"duplicate trajectory identity: {identity}")
        by_identity[identity] = row
        if _score_row(row) is None:
            failures[condition] += 1

    worlds = sorted({identity[1] for identity in by_identity})
    condition_world_means: dict[str, dict[int, float]] = {
        control_condition: {},
        treatment_condition: {},
    }
    incomplete_worlds: list[int] = []
    complete_differences: list[float] = []
    complete_control: list[float] = []
    complete_treatment: list[float] = []
    lower_differences: list[float] = []
    upper_differences: list[float] = []
    missing_support_worlds: set[int] = set()
    support_used: dict[str, list[float]] = {}

    for world_seed in worlds:
        bounds: dict[str, tuple[float, float] | None] = {}
        complete = True
        for condition in (control_condition, treatment_condition):
            scores: list[float] = []
            replicates_seen: set[int] = set()
            for replicate in range(expected_replicates):
                row = by_identity.get((condition, world_seed, replicate))
                if row is None:
                    continue
                replicates_seen.add(replicate)
                score = _score_row(row)
                if score is not None:
                    scores.append(score)
            condition_complete = (
                replicates_seen == set(range(expected_replicates))
                and len(scores) == expected_replicates
            )
            if condition_complete:
                mean_score = float(np.mean(scores))
                condition_world_means[condition][world_seed] = mean_score
                bounds[condition] = (mean_score, mean_score)
            else:
                complete = False
                support = _declared_score_support(
                    score_support_by_world, world_seed
                )
                if support is None:
                    bounds[condition] = None
                    missing_support_worlds.add(world_seed)
                else:
                    support_lower, support_upper = support
                    missing_count = expected_replicates - len(scores)
                    bounds[condition] = (
                        float(
                            (sum(scores) + missing_count * support_lower)
                            / expected_replicates
                        ),
                        float(
                            (sum(scores) + missing_count * support_upper)
                            / expected_replicates
                        ),
                    )
                    support_used[str(world_seed)] = [
                        support_lower,
                        support_upper,
                    ]
        control_bounds = bounds[control_condition]
        treatment_bounds = bounds[treatment_condition]
        if control_bounds is not None and treatment_bounds is not None:
            control_lower, control_upper = control_bounds
            treatment_lower, treatment_upper = treatment_bounds
            lower_differences.append(treatment_lower - control_upper)
            upper_differences.append(treatment_upper - control_lower)
        if complete:
            control_mean = condition_world_means[control_condition][world_seed]
            treatment_mean = condition_world_means[treatment_condition][world_seed]
            complete_control.append(control_mean)
            complete_treatment.append(treatment_mean)
            complete_differences.append(treatment_mean - control_mean)
        else:
            incomplete_worlds.append(world_seed)

    if not complete_differences:
        raise ValueError("paired analysis has no complete world clusters")
    difference_array = np.asarray(complete_differences, dtype=float)
    rng = np.random.default_rng(bootstrap_seed)
    draws = rng.choice(
        difference_array,
        size=(bootstrap_draws, len(difference_array)),
        replace=True,
    ).mean(axis=1)
    if len(difference_array) > 1:
        sem = float(stats.sem(difference_array))
        t_critical = float(stats.t.ppf(0.975, df=len(difference_array) - 1))
        paired_t_interval = [
            float(difference_array.mean() - t_critical * sem),
            float(difference_array.mean() + t_critical * sem),
        ]
    else:
        paired_t_interval = [float(difference_array[0]), float(difference_array[0])]

    missingness_bounds_available = len(lower_differences) == len(worlds)

    return {
        "trajectory_count": len(materialized),
        "planned_world_count": len(worlds),
        "complete_pair_world_count": len(complete_differences),
        "incomplete_worlds": incomplete_worlds,
        "expected_replicates": expected_replicates,
        "condition_means": {
            control_condition: float(np.mean(complete_control)),
            treatment_condition: float(np.mean(complete_treatment)),
        },
        "mean_paired_difference": float(difference_array.mean()),
        "cluster_bootstrap_95": _percentile_interval(draws),
        "paired_t_95": paired_t_interval,
        "missingness_difference_bounds": (
            [
                float(np.mean(lower_differences)),
                float(np.mean(upper_differences)),
            ]
            if missingness_bounds_available
            else None
        ),
        "missingness_bounds_status": (
            "available_declared_outcome_support"
            if missingness_bounds_available
            else "unavailable_without_declared_outcome_support"
        ),
        "missingness_support_by_incomplete_world": support_used,
        "missingness_support_missing_worlds": sorted(missing_support_worlds),
        "operational_failure_count_by_condition": failures,
        "resampling_unit": "world_seed",
        "bootstrap_draws": bootstrap_draws,
        "bootstrap_seed": bootstrap_seed,
    }



def analyze_paired_results_if_available(
    rows: Iterable[Mapping[str, Any]],
    *,
    control_condition: str,
    treatment_condition: str,
    expected_replicates: int,
    bootstrap_draws: int,
    bootstrap_seed: int,
    score_support_by_world: Mapping[int, Sequence[float]] | None = None,
) -> dict[str, Any]:
    """Return a typed deferred state while an interrupted panel has no full cluster."""

    try:
        analysis = analyze_paired_results(
            rows,
            control_condition=control_condition,
            treatment_condition=treatment_condition,
            expected_replicates=expected_replicates,
            bootstrap_draws=bootstrap_draws,
            bootstrap_seed=bootstrap_seed,
            score_support_by_world=score_support_by_world,
        )
    except ValueError as error:
        if str(error) != "paired analysis has no complete world clusters":
            raise
        return {
            "status": "deferred_no_complete_world_clusters",
            "analysis": None,
        }
    return {"status": "complete", "analysis": analysis}
