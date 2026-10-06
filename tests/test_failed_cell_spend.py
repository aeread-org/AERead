"""The spend of a failed cell is recorded, charged and readable (#226 item 7).

A call that failed after the provider answered was written as cost 0 and
never charged against the profile's budget; totals that omitted a failed
cell's spend were fixed twice in family drivers (DC-T-13, E-J-03).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from types import SimpleNamespace

import pytest

from aeread.shared_runner import AttemptSpend, attempt_spend, total_spend
from aeread.shared_runner.model_call.harness import KernelModelPort
from aeread.shared_runner.task.execution import (
    ArenaChatClient,
    OpenRouterChatClient,
    ProviderFailure,
    failed_call_cost,
)
from tests.test_shared_runner_execution import (
    FAKE_PRICING,
    SYSTEM_PROMPT,
    FakeOpenRouterCompletions,
    InspectingProvider,
    _decision,
    _evidence,
    _executor,
    _openrouter_request,
    _profile,
    _success_result,
)
from tests.test_shared_runner_harness import ScriptedProvider

SUCCESS_COST = FAKE_PRICING.cost(input_tokens=20, cached_input_tokens=0, output_tokens=5)


def _billed(condition: str = "provider_contract", *, cost: float | None = 0.004, retryable: bool = False):
    usage = {"prompt_tokens": 300, "completion_tokens": 4000, "prompt_tokens_details": {"cached_tokens": 10}}
    if cost is not None:
        usage["cost"] = cost
    failure = ProviderFailure(condition, "failed after the provider answered", retryable=retryable)
    return failure.with_reported_usage({"choices": [{"index": 0}], "usage": usage})


def _client_failure(client, request) -> ProviderFailure:
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(client.complete(request))
    return raised.value


def test_a_failure_before_any_completion_is_not_billed() -> None:
    plain = ProviderFailure("rate_limit", "429", retryable=True)
    assert plain.billing == "not_billed" and failed_call_cost(plain, FAKE_PRICING) == 0.0
    error_body = ProviderFailure("rate_limit", "429", retryable=True).with_reported_usage(
        {"error": {"code": 429, "message": "busy"}}
    )
    assert error_body.billing == "not_billed"


def test_a_failure_after_a_completion_carries_what_the_provider_reported() -> None:
    reported = _billed()
    assert reported.billing == "reported"
    assert (reported.input_tokens, reported.cached_input_tokens, reported.output_tokens) == (300, 10, 4000)
    assert failed_call_cost(reported, FAKE_PRICING) == 0.004
    # No provider figure: the profile's pricing on the reported tokens, the
    # rule a completed call is costed by.
    priced = _billed(cost=None)
    assert failed_call_cost(priced, FAKE_PRICING) == pytest.approx(
        FAKE_PRICING.cost(input_tokens=300, cached_input_tokens=10, output_tokens=4000)
    )
    unusable = ProviderFailure("provider_contract", "x", retryable=False).with_reported_usage(
        {"choices": [{"index": 0}], "usage": {"prompt_tokens": -1}}
    )
    assert unusable.billing == "unknown" and failed_call_cost(unusable, FAKE_PRICING) is None


def test_openrouter_attaches_usage_to_a_route_failure_after_a_billed_reply() -> None:
    """The reply was generated and billed by a provider that was not the pin."""

    completions = FakeOpenRouterCompletions(selected_provider="OpenInference")
    client = OpenRouterChatClient(sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    failure = _client_failure(client, _openrouter_request())
    assert failure.condition == "provider_contract"
    assert failure.billing == "reported" and failure.cost_usd == pytest.approx(0.00001726)
    assert (failure.input_tokens, failure.cached_input_tokens, failure.output_tokens) == (123, 7, 45)


def test_arena_attaches_usage_to_a_truncated_reply() -> None:
    class Completions:
        async def create(self, **_kwargs):
            raw = {
                "id": "arena-truncated",
                "model": "glm-5p2",
                "choices": [{"index": 0, "finish_reason": "length", "message": {"role": "assistant", "content": '{"offer":'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 256},
            }
            return SimpleNamespace(model_dump=lambda mode: raw)

    client = ArenaChatClient(sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    request = dataclasses.replace(
        _openrouter_request(), provider="arena", base_url="https://api.preview.arena.ai/v1"
    )
    failure = _client_failure(client, request)
    assert failure.condition == "length" and failure.billing == "reported"
    assert failure.cost_usd is None and failure.output_tokens == 256


def test_a_billed_failed_call_is_charged_recorded_and_in_the_event(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_billed(), _success_result()])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=2, retryable_conditions=()),
    )
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    assert executor.total_cost_usd == pytest.approx(0.004)
    (attempt,) = executor.execution_for(_decision().logical_action_id).attempts
    (call,) = attempt.provider_calls
    assert (call.status, call.cost_usd, call.output_tokens) == ("failed", 0.004, 4000)
    failed = next(event for event in evidence.read_events() if event.event_type == "provider_call_failed")
    payload = evidence.read_event_payload(failed)
    assert payload["cost_usd"] == 0.004 and payload["output_tokens"] == 4000
    assert attempt_spend(evidence) == AttemptSpend(
        cost_usd=0.004,
        cost_accounting="exact",
        input_tokens=300,
        cached_input_tokens=10,
        output_tokens=4000,
        provider_call_count=1,
        unsettled_call_count=0,
    )


def test_an_unbilled_failed_call_writes_the_event_it_always_wrote(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [ProviderFailure("rate_limit", "429", retryable=True)])
    executor = _executor(tmp_path, provider, evidence=evidence)
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    failed = next(event for event in evidence.read_events() if event.event_type == "provider_call_failed")
    assert evidence.read_event_payload(failed) == {
        "cost_usd": 0.0,
        "failure_condition": "rate_limit",
        "message": "429",
        "retryable": True,
        "status_code": None,
    }
    assert executor.total_cost_usd == 0.0


def test_spend_of_a_cell_that_failed_after_paid_calls(tmp_path) -> None:
    """Retried twice, then failed for good: three billed calls, all counted."""

    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path,
        [_billed("length", retryable=True), _billed("length", cost=0.008, retryable=True), _billed("provider_contract", cost=0.001)],
    )
    executor = _executor(
        tmp_path, provider, evidence=evidence, profile=_profile(max_action_attempts=3, retryable_conditions=("length",))
    )
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    spend = attempt_spend(evidence)
    assert spend.cost_usd == pytest.approx(0.013) and spend.cost_accounting == "exact"
    assert spend.provider_call_count == 3 and spend.output_tokens == 12_000
    assert executor.total_cost_usd == pytest.approx(0.013)
    evidence.close()
    # The same figure from the directory alone, as a driver reads it.
    assert attempt_spend(tmp_path / "evidence") == spend


@pytest.mark.parametrize("condition", ["timeout", "transport"])
def test_a_call_whose_outcome_is_unknown_makes_the_total_a_lower_bound(tmp_path, condition) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path, [ProviderFailure(condition, "lost", retryable=True), _success_result()]
    )
    executor = _executor(
        tmp_path, provider, evidence=evidence, profile=_profile(max_action_attempts=2, retryable_conditions=(condition,))
    )
    asyncio.run(executor(_decision()))
    spend = attempt_spend(evidence)
    assert spend.cost_accounting == "lower_bound" and spend.unsettled_call_count == 1
    assert spend.cost_usd == pytest.approx(SUCCESS_COST) and spend.provider_call_count == 2


def test_a_billed_failure_with_no_usable_usage_is_a_lower_bound(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    unusable = ProviderFailure("provider_contract", "no usage", retryable=False).with_reported_usage(
        {"choices": [{"index": 0}]}
    )
    executor = _executor(tmp_path, InspectingProvider(evidence.events_path, [unusable]), evidence=evidence)
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    failed = next(event for event in evidence.read_events() if event.event_type == "provider_call_failed")
    assert evidence.read_event_payload(failed)["cost_usd"] == "unknown"
    spend = attempt_spend(evidence)
    assert (spend.cost_usd, spend.cost_accounting, spend.unsettled_call_count) == (0.0, "lower_bound", 1)


def test_an_interrupted_attempt_is_readable_and_a_lower_bound(tmp_path) -> None:
    """A started call with no terminal event: the log an interruption leaves,
    which the audited store refuses to open."""

    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    executor = _executor(tmp_path, provider, evidence=evidence)
    asyncio.run(executor(_decision()))
    evidence.append_event(
        "provider_call_started", {"request": None}, provider_call_id="provider_call_left_open"
    )
    evidence.close()
    spend = attempt_spend(tmp_path / "evidence")
    assert spend.cost_accounting == "lower_bound" and spend.unsettled_call_count == 1
    assert spend.cost_usd == pytest.approx(SUCCESS_COST) and spend.provider_call_count == 2


def test_the_harness_port_records_a_billed_failed_round(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    port = KernelModelPort(
        evidence=evidence,
        provider=ScriptedProvider([_billed()]),
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )
    with pytest.raises(ProviderFailure):
        asyncio.run(port.complete(messages=(), response_mode="text"))
    failed = next(event for event in evidence.read_events() if event.event_type == "provider_call_failed")
    payload = evidence.read_event_payload(failed)
    assert payload["cost_usd"] == 0.004 and payload["input_tokens"] == 300 and payload["round"] == 0


def test_totals_add_and_one_lower_bound_qualifies_the_sum() -> None:
    exact = AttemptSpend(0.25, "exact", 10, 1, 5, 2, 0)
    bound = AttemptSpend(0.5, "lower_bound", 20, 2, 10, 3, 1)
    assert total_spend([exact, exact]) == AttemptSpend(0.5, "exact", 20, 2, 10, 4, 0)
    assert total_spend([exact, bound]) == AttemptSpend(0.75, "lower_bound", 30, 3, 15, 5, 1)
    assert total_spend([]) == AttemptSpend(0.0, "exact", 0, 0, 0, 0, 0)
    assert json.dumps(bound.as_dict(), sort_keys=True).count("lower_bound") == 1
