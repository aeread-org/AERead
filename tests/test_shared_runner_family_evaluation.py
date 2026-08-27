"""A family-neutral receipt path must work with Housing before RFQ adopts it."""
import asyncio
from dataclasses import replace

import pytest

from aeread.shared_runner.execution import ProviderFailure, execute_plan_cell
from aeread.shared_runner.scheduler import SchedulerContractError
from aeread.shared_runner.family_evaluation import (
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.housing import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    _housing_measurement_leaf,
    build_housing_smoke,
)


def _setup():
    return build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )


def _execute(setup, root, tenant=None):
    return asyncio.run(execute_plan_cell(
        plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry,
        evidence_root=root, prompt_sources=setup.prompt_sources, pricing=setup.pricing,
        providers={
            "housing_scripted_tenant": tenant or HousingScriptedTenantProvider(),
            "housing_scripted_landlord": HousingScriptedLandlordProvider(),
        },
    ))


def test_family_neutral_finalizer_replays_housing_without_provider_calls(tmp_path):
    setup = _setup()
    execution = _execute(setup, tmp_path)
    receipt = finalize_family_execution(setup=setup, execution=execution)
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"
    assert receipt.plan_implementation_pins == setup.plan.implementation_pins
    assert replay_family_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path) == receipt


def test_family_finalizer_rejects_an_outcome_different_from_recorded_state(tmp_path):
    setup = _setup()
    execution = _execute(setup, tmp_path)
    altered = replace(execution, episode_result=replace(
        execution.episode_result,
        outcome={**execution.episode_result.outcome, "social_welfare": 1e9},
    ))
    with pytest.raises(ValueError, match="event log"):
        finalize_family_execution(setup=setup, execution=altered)


def test_family_failure_is_excluded_with_no_economic_score(tmp_path):
    class BrokenProvider:
        async def complete(self, request):
            raise ProviderFailure("provider_contract", "test failure", retryable=False)

    setup = _setup()
    with pytest.raises(SchedulerContractError) as caught:
        _execute(setup, tmp_path, BrokenProvider())
    receipt = finalize_family_failure(
        setup=setup, cell_id=setup.plan.cells[0].cell_id, evidence_root=tmp_path,
        error=caught.value, leaf_builder=_housing_measurement_leaf,
    )
    assert receipt.status == "invalid_measurement"
    assert receipt.inclusion_status == "excluded"
    assert receipt.scores == ()
    assert receipt.failure.failure_class == "integration_or_configuration"
