from __future__ import annotations

import pytest

from aeread.shared_runner.housing_experiment import (
    analyze_paired_results,
    derive_world_seeds,
    paired_inference_seed,
)


def test_world_panel_is_deterministic_unique_and_pre_outcome() -> None:
    first = derive_world_seeds(master_seed=20260826, count=100)
    second = derive_world_seeds(master_seed=20260826, count=100)

    assert first == second
    assert len(first) == 100
    assert len(set(first)) == 100
    assert all(0 <= seed < 2**31 for seed in first)
    assert derive_world_seeds(master_seed=20260827, count=100) != first


def test_paired_inference_seed_excludes_condition_but_changes_by_world_and_replicate() -> None:
    seed = paired_inference_seed(
        base_seed=87001,
        world_seed=41001,
        replicate_index=0,
    )

    assert seed == paired_inference_seed(
        base_seed=87001,
        world_seed=41001,
        replicate_index=0,
    )
    assert seed != paired_inference_seed(
        base_seed=87001,
        world_seed=41001,
        replicate_index=1,
    )
    assert seed != paired_inference_seed(
        base_seed=87001,
        world_seed=41002,
        replicate_index=0,
    )


def _row(
    condition: str,
    world_seed: int,
    replicate: int,
    score: float | None,
    *,
    status: str = "completed",
) -> dict[str, object]:
    return {
        "condition_id": condition,
        "world_seed": world_seed,
        "replicate_index": replicate,
        "status": status,
        "within_case_score": score,
        "social_welfare": None if score is None else score * 100.0,
        "cost_usd": 0.001,
        "length_retry_count": 0,
    }


def test_paired_analysis_aggregates_replicates_then_resamples_world_clusters() -> None:
    rows: list[dict[str, object]] = []
    for world_seed in (11, 12, 13, 14):
        for replicate in range(3):
            rows.append(_row("reasoning_none_v1", world_seed, replicate, 0.50))
            rows.append(_row("reasoning_low_v1", world_seed, replicate, 0.60))

    result = analyze_paired_results(
        rows,
        control_condition="reasoning_none_v1",
        treatment_condition="reasoning_low_v1",
        expected_replicates=3,
        bootstrap_draws=1000,
        bootstrap_seed=20260826,
    )

    assert result["trajectory_count"] == 24
    assert result["planned_world_count"] == 4
    assert result["complete_pair_world_count"] == 4
    assert result["condition_means"] == {
        "reasoning_none_v1": pytest.approx(0.50),
        "reasoning_low_v1": pytest.approx(0.60),
    }
    assert result["mean_paired_difference"] == pytest.approx(0.10)
    assert result["cluster_bootstrap_95"] == pytest.approx([0.10, 0.10])
    assert result["resampling_unit"] == "world_seed"
    assert result["bootstrap_draws"] == 1000


def test_paired_analysis_excludes_incomplete_world_and_reports_worst_case_bounds() -> None:
    rows: list[dict[str, object]] = []
    for replicate in range(3):
        rows.append(_row("reasoning_none_v1", 11, replicate, 0.40))
        rows.append(_row("reasoning_low_v1", 11, replicate, 0.60))
        rows.append(_row("reasoning_none_v1", 12, replicate, 0.50))
    rows.extend(
        [
            _row("reasoning_low_v1", 12, 0, 0.70),
            _row("reasoning_low_v1", 12, 1, 0.70),
            _row(
                "reasoning_low_v1",
                12,
                2,
                None,
                status="operational_failure",
            ),
        ]
    )

    result = analyze_paired_results(
        rows,
        control_condition="reasoning_none_v1",
        treatment_condition="reasoning_low_v1",
        expected_replicates=3,
        bootstrap_draws=200,
        bootstrap_seed=7,
    )

    assert result["planned_world_count"] == 2
    assert result["complete_pair_world_count"] == 1
    assert result["incomplete_worlds"] == [12]
    assert result["operational_failure_count_by_condition"] == {
        "reasoning_none_v1": 0,
        "reasoning_low_v1": 1,
    }
    assert result["mean_paired_difference"] == pytest.approx(0.20)
    assert result["missingness_difference_bounds"] == pytest.approx([-0.15, 0.35])


def test_paired_analysis_rejects_duplicate_trajectory_identity() -> None:
    duplicate = _row("reasoning_none_v1", 11, 0, 0.50)

    with pytest.raises(ValueError, match="duplicate trajectory identity"):
        analyze_paired_results(
            [duplicate, dict(duplicate)],
            control_condition="reasoning_none_v1",
            treatment_condition="reasoning_low_v1",
            expected_replicates=3,
            bootstrap_draws=100,
            bootstrap_seed=1,
        )
