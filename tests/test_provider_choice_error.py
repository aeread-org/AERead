"""A choice that finishes with an upstream error is retryable by name (#223).

A 200 response whose choice had ``finish_reason: "error"`` was typed
``provider_rejected`` and could never be retried, although the same request
succeeded on the same route minutes later (DC-T-15: 9 cells, three campaigns).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aeread.shared_runner import PROVIDER_CHOICE_ERROR
from aeread.shared_runner.run.adapter_campaign import _SAFE_PROVIDER_FAILURE_CONDITIONS
from aeread.shared_runner.task.execution import OpenRouterChatClient, ProviderFailure
from tests.test_shared_runner_execution import (
    InspectingProvider,
    _decision,
    _evidence,
    _executor,
    _openrouter_request,
    _profile,
    _success_result,
)


def _client(choice: dict) -> OpenRouterChatClient:
    class Completions:
        async def create(self, **_kwargs):
            raw = {"id": "gen_choice_error", "model": "deepseek/deepseek-v4-flash-0731", "choices": [choice]}
            return SimpleNamespace(model_dump=lambda mode: raw)

    return OpenRouterChatClient(sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())))


def _failure(choice: dict) -> ProviderFailure:
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(_client(choice).complete(_openrouter_request()))
    return raised.value


@pytest.mark.parametrize(
    "choice",
    [
        {"index": 0, "finish_reason": "error", "message": {"role": "assistant", "content": ""}},
        {"index": 0, "finish_reason": "error", "message": {"role": "assistant", "content": '{"offer":'}},
        {"index": 0, "finish_reason": "error", "error": {"message": "upstream stopped"}, "message": {}},
        {"index": 0, "finish_reason": "error", "error": {"code": "server_error", "message": "x"}, "message": {}},
    ],
)
def test_an_error_finish_with_no_status_is_its_own_retryable_condition(choice) -> None:
    failure = _failure(choice)
    assert failure.condition == PROVIDER_CHOICE_ERROR == "provider_choice_error"
    assert failure.retryable is True and failure.status_code is None
    assert PROVIDER_CHOICE_ERROR in _SAFE_PROVIDER_FAILURE_CONDITIONS


@pytest.mark.parametrize(
    ("code", "condition", "retryable"),
    [
        (502, "provider_5xx", True),
        (429, "rate_limit", True),
        (402, "account_fault", False),
        (400, "provider_rejected", False),
    ],
)
def test_an_error_finish_that_carries_a_status_is_still_typed_by_it(code, condition, retryable) -> None:
    failure = _failure(
        {"index": 0, "finish_reason": "error", "error": {"code": code, "message": "typed"}, "message": {}}
    )
    assert (failure.condition, failure.retryable, failure.status_code) == (condition, retryable, code)


def test_a_profile_that_names_the_condition_recovers_the_cell(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    fault = ProviderFailure(PROVIDER_CHOICE_ERROR, "OpenRouter choice finished with an error", retryable=True)
    provider = InspectingProvider(evidence.events_path, [fault, _success_result()])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=2, retryable_conditions=(PROVIDER_CHOICE_ERROR,)),
    )
    response = asyncio.run(executor(_decision()))
    assert response.text == '{"offer":7}' and len(provider.requests) == 2
    execution = executor.execution_for(_decision().logical_action_id)
    assert [attempt.status for attempt in execution.attempts] == ["failed", "succeeded"]
    assert execution.attempts[1].retry_reason == PROVIDER_CHOICE_ERROR


@pytest.mark.parametrize("declared", [(), ("provider_5xx",), ("provider_5xx", "transport", "timeout")])
def test_declaring_5xx_retries_does_not_retry_it(tmp_path, declared) -> None:
    """Opt-in by name: no profile sealed before this condition existed
    acquires a retry it did not declare."""

    evidence = _evidence(tmp_path)
    fault = ProviderFailure(PROVIDER_CHOICE_ERROR, "OpenRouter choice finished with an error", retryable=True)
    provider = InspectingProvider(evidence.events_path, [fault, _success_result()])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=3, retryable_conditions=declared),
    )
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(executor(_decision()))
    assert raised.value.condition == PROVIDER_CHOICE_ERROR and len(provider.requests) == 1
    assert executor.execution_for(_decision().logical_action_id).failure_code == PROVIDER_CHOICE_ERROR
