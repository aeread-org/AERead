"""govsim: a reply cut off at the output-token limit is a typed ``length`` failure.

Ruled on #152 (2026-09-10) and applied to the kernel tool loop in #233: a
cut-off reply that is not a complete answer is never the model's malformed
output, so the profile's declared ``length`` retry (doubled output budget)
must be able to run. govsim declares that retry.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from aeread.shared_runner.model_call.harness import ModelTurn
from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.govsim.live import (
    DISCUSS_PHASE,
    HARVEST_PHASE,
    REFLECT_PHASE,
    GovsimJsonHarness,
)
from tests.test_shared_runner_harness import ScriptedProvider, _result
from tests.test_truncated_response_typing import (
    _events,
    _harness_executor,
    _json_dialect_profile,
)

CUT = {
    DISCUSS_PHASE: '{"message":"We should harv',
    REFLECT_PHASE: '{"reflection":"I lea',
    HARVEST_PHASE: '{"quantity": 1',
}


class _StubModel:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = list(turns)
        self.calls = 0

    async def complete(self, **_kwargs) -> ModelTurn:
        self.calls += 1
        return self.turns.pop(0)


def _turn(text: str, finish_reason: str) -> ModelTurn:
    return ModelTurn(
        text=text, tool_calls=(), provider_call_id="pc_0", finish_reason=finish_reason
    )


def _act(phase: str, model: _StubModel, rounds_left: int = 3):
    ctx = SimpleNamespace(
        model=model, tools=None, budget=SimpleNamespace(rounds_left=rounds_left)
    )
    request = SimpleNamespace(
        phase_id=phase,
        seat_id="s0",
        role="r",
        observation_schema={},
        action_schema={},
        observation={},
    )
    return asyncio.run(GovsimJsonHarness().act(request, ctx))


@pytest.mark.parametrize("phase", [DISCUSS_PHASE, REFLECT_PHASE, HARVEST_PHASE])
def test_a_cut_off_reply_is_a_retryable_length_failure(phase) -> None:
    model = _StubModel(_turn(CUT[phase], "length"), _turn(CUT[phase], "length"))
    with pytest.raises(ProviderFailure) as raised:
        _act(phase, model)
    assert raised.value.condition == "length" and raised.value.retryable
    assert phase in str(raised.value)
    assert model.calls == 1, "a cut-off reply is not re-prompted"


def test_max_output_tokens_counts_as_truncated() -> None:
    with pytest.raises(ProviderFailure) as raised:
        _act(REFLECT_PHASE, _StubModel(_turn(CUT[REFLECT_PHASE], "max_output_tokens")))
    assert raised.value.condition == "length" and raised.value.retryable


def test_a_finished_malformed_discuss_reply_is_still_malformed() -> None:
    with pytest.raises(ProviderFailure) as raised:
        _act(DISCUSS_PHASE, _StubModel(_turn(CUT[DISCUSS_PHASE], "stop")))
    assert raised.value.condition == "malformed_structured_output"
    assert not raised.value.retryable


def test_a_finished_malformed_reflection_is_still_empty() -> None:
    output = _act(REFLECT_PHASE, _StubModel(_turn(CUT[REFLECT_PHASE], "stop")))
    assert output.action == {"reflection": ""}


def test_a_finished_malformed_harvest_is_still_malformed() -> None:
    with pytest.raises(ProviderFailure) as raised:
        _act(HARVEST_PHASE, _StubModel(_turn(CUT[HARVEST_PHASE], "stop")), rounds_left=1)
    assert raised.value.condition == "malformed_structured_output"
    assert not raised.value.retryable


def test_a_truncated_harvest_that_is_complete_json_is_an_answer() -> None:
    output = _act(HARVEST_PHASE, _StubModel(_turn('{"quantity": 3}', "length")))
    assert output.action == {"quantity": 3}


def test_the_executor_runs_the_declared_length_retry_with_a_doubled_budget(tmp_path) -> None:
    base = _json_dialect_profile(max_action_attempts=2, retryable_conditions=("length",))
    profile = dataclasses.replace(
        base, harness=dataclasses.replace(base.harness, id="govsim_json")
    )
    provider = ScriptedProvider(
        [
            _result(text='{"quantity": 1', finish_reason="length"),
            _result(text='{"quantity": 3}'),
        ]
    )
    executor, decision, evidence = _harness_executor(
        tmp_path,
        provider,
        harnesses={"govsim_json/1.0": GovsimJsonHarness()},
        profile=profile,
    )
    decision = dataclasses.replace(decision, phase_id=HARVEST_PHASE)
    response = asyncio.run(executor(decision))
    assert response.action == {"quantity": 3}
    assert len(provider.requests) == 2
    first, second = (request.max_output_tokens for request in provider.requests)
    assert second == 2 * first
    (execution,) = executor.executions()
    assert [attempt.retry_reason for attempt in execution.attempts] == [None, "length"]
    assert execution.attempts[0].status == "failed"
    calls = [call for attempt in execution.attempts for call in attempt.provider_calls]
    assert len(calls) == 2 and all(call.cost_usd > 0 for call in calls)
    assert executor.total_cost_usd == pytest.approx(sum(call.cost_usd for call in calls))
    # The cut-off call completed and was billed: it is recorded as a succeeded
    # provider call inside a failed attempt, never as a failed or unknown call.
    lifecycle = [
        event["event_type"]
        for event in _events(evidence)
        if event["event_type"].startswith(("provider_call_", "action_attempt_"))
        and event["event_type"] != "provider_call_started"
        and event["event_type"] != "action_attempt_started"
    ]
    assert lifecycle == [
        "provider_call_succeeded",
        "action_attempt_failed",
        "provider_call_succeeded",
        "action_attempt_succeeded",
    ]
    executor.finalize_logical_action(
        decision.logical_action_id, valid=True, failure_code=None
    )
    evidence.audit_reconciliation()
