from __future__ import annotations

import asyncio
import dataclasses

import pytest

from aeread.shared_runner.execution import ProviderRequest, execute_plan_cell
from aeread.shared_runner.housing import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
)
from aeread.shared_runner.housing_experiment import (
    analyze_paired_results,
    build_housing_condition_setup,
    derive_world_seeds,
    paired_inference_seed,
)


DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPSEEK_REVISION = "deepseek/deepseek-v4-flash-20260731"


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


def test_condition_plans_pair_worlds_and_replicates_but_seal_distinct_treatments() -> None:
    common = {
        "world_seeds": (101, 202, 303),
        "replicates": 2,
        "tenant_model": DEEPSEEK_MODEL,
        "tenant_revision": DEEPSEEK_REVISION,
        "num_tenants": 6,
        "num_listings": 4,
        "rounds": 4,
        "inference_seed_base": 87001,
    }
    disabled = build_housing_condition_setup(
        condition_id="reasoning_none_v1",
        reasoning_effort="none",
        **common,
    )
    low = build_housing_condition_setup(
        condition_id="reasoning_low_v1",
        reasoning_effort="low",
        **common,
    )

    assert len(disabled.plan.cases) == 3
    assert len(disabled.plan.cells) == 6
    assert {case.world_seed for case in disabled.plan.cases} == {101, 202, 303}
    assert disabled.plan.sampling.panel_mode == "sampled_panel"
    assert disabled.plan.sampling.replicates == 2
    assert disabled.plan.analysis.uncertainty == "cluster_bootstrap_95"
    assert all(case.episode.max_logical_actions == 64 for case in disabled.plan.cases)

    disabled_profile = next(
        profile
        for profile in disabled.plan.agent_profiles
        if profile.model.provider == "openrouter"
    )
    low_profile = next(
        profile
        for profile in low.plan.agent_profiles
        if profile.model.provider == "openrouter"
    )
    assert disabled_profile.profile_id != low_profile.profile_id
    assert disabled_profile.reasoning.condition_id == "reasoning_none_v1"
    assert disabled_profile.reasoning.effort == "none"
    assert low_profile.reasoning.condition_id == "reasoning_low_v1"
    assert low_profile.reasoning.effort == "low"
    assert disabled_profile.sampling.seed is None
    assert disabled_profile.harness.config["request_seed_source"] == "paired_cell_v1"
    assert disabled_profile.harness.config["request_seed_base"] == 87001

    disabled_cells = {
        (cell.world_seed, cell.replicate_index): cell for cell in disabled.plan.cells
    }
    low_cells = {(cell.world_seed, cell.replicate_index): cell for cell in low.plan.cells}
    assert set(disabled_cells) == set(low_cells)
    for identity in disabled_cells:
        assert disabled_cells[identity].cluster_id == low_cells[identity].cluster_id
        assert disabled_cells[identity].pair_id == low_cells[identity].pair_id


class _RecordingTenantProvider:
    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []
        self._delegate = HousingScriptedTenantProvider()

    async def complete(self, request: ProviderRequest):
        self.requests.append(request)
        translated = dataclasses.replace(request, provider="housing_scripted_tenant")
        return await self._delegate.complete(translated)


def _cell_for(setup, *, world_seed: int, replicate_index: int):
    return next(
        cell
        for cell in setup.plan.cells
        if cell.world_seed == world_seed and cell.replicate_index == replicate_index
    )


def _execute_recorded(setup, cell, output):
    recorder = _RecordingTenantProvider()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=cell.cell_id,
            registry=setup.registry,
            evidence_root=output,
            prompt_sources=setup.prompt_sources,
            providers={
                "openrouter": recorder,
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    return recorder, execution


def test_executor_applies_same_paired_seed_across_conditions_and_new_seed_per_replicate(
    tmp_path,
) -> None:
    common = {
        "world_seeds": (41001,),
        "replicates": 2,
        "tenant_model": DEEPSEEK_MODEL,
        "tenant_revision": DEEPSEEK_REVISION,
        "num_tenants": 2,
        "num_listings": 1,
        "rounds": 1,
        "inference_seed_base": 87001,
    }
    disabled = build_housing_condition_setup(
        condition_id="reasoning_none_v1", reasoning_effort="none", **common
    )
    low = build_housing_condition_setup(
        condition_id="reasoning_low_v1", reasoning_effort="low", **common
    )

    disabled_r0, _ = _execute_recorded(
        disabled,
        _cell_for(disabled, world_seed=41001, replicate_index=0),
        tmp_path / "disabled-r0",
    )
    low_r0, _ = _execute_recorded(
        low,
        _cell_for(low, world_seed=41001, replicate_index=0),
        tmp_path / "low-r0",
    )
    disabled_r1, _ = _execute_recorded(
        disabled,
        _cell_for(disabled, world_seed=41001, replicate_index=1),
        tmp_path / "disabled-r1",
    )

    assert {request.reasoning_effort for request in disabled_r0.requests} == {"none"}
    assert {request.reasoning_effort for request in low_r0.requests} == {"low"}
    assert len({request.seed for request in disabled_r0.requests}) == 1
    assert len({request.seed for request in low_r0.requests}) == 1
    assert disabled_r0.requests[0].seed == low_r0.requests[0].seed
    assert disabled_r0.requests[0].seed == paired_inference_seed(
        base_seed=87001,
        world_seed=41001,
        replicate_index=0,
    )
    assert disabled_r1.requests[0].seed != disabled_r0.requests[0].seed
