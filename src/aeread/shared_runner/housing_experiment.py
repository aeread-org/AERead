"""Paired, cluster-aware Housing reasoning-condition experiments."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
from scipy import stats

from .housing import HousingSmokeSetup, build_housing_smoke


def _derived_nonnegative_int(namespace: str, *values: int) -> int:
    payload = ":".join((namespace, *(str(value) for value in values))).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFF_FFFF


def derive_world_seeds(*, master_seed: int, count: int) -> tuple[int, ...]:
    """Derive a version-stable, outcome-blind panel of unique world seeds."""

    if isinstance(master_seed, bool) or not isinstance(master_seed, int) or master_seed < 0:
        raise ValueError("master_seed must be a non-negative integer")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    seeds: list[int] = []
    seen: set[int] = set()
    counter = 0
    while len(seeds) < count:
        candidate = _derived_nonnegative_int("housing_panel_v1", master_seed, counter)
        counter += 1
        if candidate in seen:
            continue
        seen.add(candidate)
        seeds.append(candidate)
    return tuple(seeds)


def paired_inference_seed(
    *, base_seed: int, world_seed: int, replicate_index: int
) -> int:
    """Return the same provider seed for paired conditions of one world replicate."""

    for name, value in (
        ("base_seed", base_seed),
        ("world_seed", world_seed),
        ("replicate_index", replicate_index),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    return _derived_nonnegative_int(
        "housing_inference_seed_v1", base_seed, world_seed, replicate_index
    )


def build_housing_condition_setup(
    *,
    condition_id: str,
    reasoning_effort: str,
    world_seeds: Sequence[int],
    replicates: int,
    tenant_model: str,
    tenant_revision: str,
    num_tenants: int = 6,
    num_listings: int = 4,
    rounds: int = 4,
    inference_seed_base: int = 87001,
) -> HousingSmokeSetup:
    """Seal one arm of the paired Housing reasoning experiment."""

    expected_effort = {
        "reasoning_none_v1": "none",
        "reasoning_low_v1": "low",
    }
    if expected_effort.get(condition_id) != reasoning_effort:
        raise ValueError(
            "condition_id and reasoning_effort must be one of the locked "
            "none/low experiment arms"
        )
    return build_housing_smoke(
        tenant_provider="openrouter",
        tenant_model=tenant_model,
        tenant_revision=tenant_revision,
        world_seeds=tuple(world_seeds),
        replicates=replicates,
        reasoning_condition_id=condition_id,
        reasoning_effort=reasoning_effort,
        inference_seed_base=inference_seed_base,
        num_tenants=num_tenants,
        num_listings=num_listings,
        rounds=rounds,
    )


def _score_row(row: Mapping[str, Any]) -> float | None:
    if row.get("status") != "completed":
        return None
    score = row.get("within_case_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    numeric = float(score)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError("completed within_case_score must be finite and in [0, 1]")
    return numeric


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

    for world_seed in worlds:
        bounds: dict[str, tuple[float, float]] = {}
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
                bounds[condition] = (0.0, 1.0)
        control_lower, control_upper = bounds[control_condition]
        treatment_lower, treatment_upper = bounds[treatment_condition]
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
        "missingness_difference_bounds": [
            float(np.mean(lower_differences)),
            float(np.mean(upper_differences)),
        ],
        "operational_failure_count_by_condition": failures,
        "resampling_unit": "world_seed",
        "bootstrap_draws": bootstrap_draws,
        "bootstrap_seed": bootstrap_seed,
    }


__all__ = [
    "analyze_paired_results",
    "build_housing_condition_setup",
    "derive_world_seeds",
    "paired_inference_seed",
]
