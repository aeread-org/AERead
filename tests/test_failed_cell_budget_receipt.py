"""A final cost_budget_exceeded failure is an environment_failure at the receipt (#291).

The class is decided by the final condition, ahead of the retryable check: a
cell that ends over its cap is not retried into the same cap. A length retry
followed by a success that crosses the cap used to read as
retryable_infrastructure because the earlier length failure matched.
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Sequence

from aeread.shared_runner.task.evaluation import finalize_family_failure
from aeread.shared_runner.task.execution import execute_plan_cell, ProviderFailure, ProviderRequest, ProviderResult
from tests import test_shared_runner_scoring_contract as contract

# The reference profile's cap is $0.00 and every scripted call reports $1.00,
# so any charged call crosses it.
RETRY = {
    "max_action_attempts": 3,
    "retryable_conditions": ["length"],
    "session_mode": "restart",
    "sdk_retries": 0,
}


class Scripted:
    def __init__(self, outcomes: Sequence[object]) -> None:
        self._outcomes = list(outcomes)

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, ProviderFailure):
            raise outcome
        return ProviderResult(
            response_id=f"scripted_{request.provider_call_id}",
            requested_model=request.model,
            resolved_model=request.revision or request.model,
            output_text='{"label": "x"}',
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=1,
            cost_usd=1.0,
            raw_response={"fixture": True},
        )


def _billed(condition: str, *, retryable: bool, cost: float) -> ProviderFailure:
    return ProviderFailure(condition, "billed failure", retryable=retryable).with_reported_usage(
        {"choices": [{"index": 0}], "usage": {"cost": cost}}
    )


def _receipt(tmp_path: Path, outcomes: Sequence[object]):
    setup = contract._build_reference_setup(
        plugin_factory=functools.partial(contract._CaseConditionalPlugin, mode="default"),
        case=contract._case_conditional_case(mode="basic"),
        family_manifest=contract._case_conditional_family_manifest(),
        extra_pins=contract._case_conditional_extra_pins(),
        retry_policy=RETRY,
    )
    root = tmp_path / "evidence"
    caught = None
    try:
        asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=root,
                prompt_sources=setup.prompt_sources,
                providers={contract._REFERENCE_PROVIDER_ID: Scripted(outcomes)},
                pricing=setup.pricing,
                harnesses=setup.harnesses,
            )
        )
    except Exception as error:
        caught = error
    assert caught is not None
    return finalize_family_failure(
        setup=setup,
        cell_id=setup.plan.cells[0].cell_id,
        evidence_root=root,
        error=caught,
        leaf_builder=lambda family_case: contract._reference_leaf(
            leaf_id=contract._REFERENCE_BALANCE_LEAF_ID, input_scope="terminal_state"
        ),
    )


def test_a_billed_failed_call_that_crosses_the_cap_is_an_environment_failure(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path, [_billed("provider_5xx", retryable=True, cost=1.0)])
    assert receipt.failure.condition == "cost_budget_exceeded"
    assert receipt.failure.failure_class == "environment_failure"


def test_a_length_retry_then_a_success_over_the_cap_is_an_environment_failure(tmp_path: Path) -> None:
    receipt = _receipt(
        tmp_path,
        [_billed("length", retryable=True, cost=0.0), "success"],
    )
    assert receipt.failure.condition == "cost_budget_exceeded"
    assert receipt.failure.failure_class == "environment_failure"
