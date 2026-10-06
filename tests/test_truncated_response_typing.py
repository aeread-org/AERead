"""A reply cut off at the output-token limit is a typed ``length`` failure.

Ruled on #152 (2026-09-10): truncated and unparseable is never a scored
answer, on any client. The growth of a length retry is bounded and stops
when it can no longer grow (#131), and it reaches every round of a
harness-driven attempt.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from types import SimpleNamespace

import pytest

from aeread.shared_runner.model_call.harness import (
    AttemptExecutor,
    BudgetView,
    CanonicalMessage,
    JsonDialectHarness,
    KernelModelPort,
    ModelTurn,
    _KernelAttemptContext,
    default_harnesses,
)
from aeread.shared_runner.task.execution import (
    TRUNCATED_FINISH_REASONS,
    EvidenceIntegrityError,
    EvidenceStore,
    OpenRouterChatClient,
    ProviderFailure,
)
from tests.test_shared_runner_execution import (
    SYSTEM_PROMPT,
    FakeOpenRouterNativeCompletions,
    InspectingProvider,
    _decision,
    _evidence,
    _executor,
    _openrouter_request,
    _profile,
    _success_result,
)
from tests.test_shared_runner_harness import FAKE_PRICING, ScriptedProvider, _result

CUT_OFF = '{"offer": 11111111111111111111'


def _truncated(text: str = CUT_OFF, *, finish_reason: str = "length"):
    return dataclasses.replace(_success_result(text=text), finish_reason=finish_reason)


def _with_config(profile, **config):
    return dataclasses.replace(
        profile,
        harness=dataclasses.replace(
            profile.harness, config={**dict(profile.harness.config), **config}
        ),
    )


def _events(evidence) -> list[dict]:
    return [json.loads(line) for line in evidence.events_path.read_text().splitlines()]


def _failure_conditions(evidence) -> list[str]:
    conditions = []
    for event in evidence.read_events():
        if event.event_type in {"action_attempt_failed", "logical_action_failed"}:
            payload = evidence.read_event_payload(event)
            conditions.append(payload.get("failure_condition") or payload.get("failure_code"))
    return conditions


@pytest.mark.parametrize("finish_reason", sorted(TRUNCATED_FINISH_REASONS))
@pytest.mark.parametrize("text", [CUT_OFF, "", "   "])
def test_an_unusable_truncated_reply_is_a_typed_length_failure(tmp_path, finish_reason, text) -> None:
    """With no retry declared, the reply used to reach the family parser as
    the model's own malformed action."""

    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path, [_truncated(text, finish_reason=finish_reason)]
    )
    executor = _executor(tmp_path, provider, evidence=evidence)
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(executor(_decision()))
    assert raised.value.condition == "length" and raised.value.retryable
    execution = executor.execution_for(_decision().logical_action_id)
    assert execution.status == "failed" and execution.failure_code == "length"
    (attempt,) = execution.attempts
    # The call completed and was billed: it is recorded as such, with its cost.
    assert [call.status for call in attempt.provider_calls] == ["succeeded"]
    assert attempt.provider_calls[0].finish_reason == finish_reason
    assert attempt.provider_calls[0].cost_usd > 0
    assert executor.total_cost_usd == pytest.approx(attempt.provider_calls[0].cost_usd)
    assert "action_attempt_succeeded" not in [event.event_type for event in evidence.read_events()]
    evidence.audit_reconciliation()


def test_a_truncated_reply_that_is_complete_json_is_still_an_answer(tmp_path) -> None:
    """The limit fell after the answer closed, as on the Arena client."""

    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_truncated('{"offer":7}')])
    executor = _executor(tmp_path, provider, evidence=evidence)
    response = asyncio.run(executor(_decision()))
    assert response.text == '{"offer":7}' and response.truncated is True


def test_a_finished_malformed_reply_is_still_the_models_answer(tmp_path) -> None:
    """Only truncation is retyped: a reply that finished and is malformed
    goes to the family parser, which types it as agent behaviour."""

    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result(text=CUT_OFF)])
    executor = _executor(tmp_path, provider, evidence=evidence)
    response = asyncio.run(executor(_decision()))
    assert response.text == CUT_OFF and response.truncated is False


def test_a_declared_length_retry_recovers_with_a_larger_budget(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_truncated(), _success_result()])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=2, retryable_conditions=("length",)),
    )
    response = asyncio.run(executor(_decision()))
    assert response.text == '{"offer":7}'
    assert [request.max_output_tokens for request in provider.requests] == [80, 160]


def test_growth_stops_at_the_ceiling_instead_of_repeating_the_same_request(tmp_path) -> None:
    """Six attempts used to send 2048, 4096, 8192, 16384, 16384, 16384: three
    billable calls at an identical limit. Now the run stops when it cannot grow."""

    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_truncated() for _ in range(10)])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=10, retryable_conditions=("length",)),
    )
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(executor(_decision()))
    assert raised.value.condition == "length"
    limits = [request.max_output_tokens for request in provider.requests]
    assert limits == [80, 160, 320, 640]
    assert len(set(limits)) == len(limits)
    assert _failure_conditions(evidence)[-1] == "length"
    evidence.audit_reconciliation()


def test_growth_also_stops_at_the_ceiling_on_the_client_failure_path(tmp_path) -> None:
    """Arena raises ``length`` from the client; that path must not repeat a
    request at the ceiling either."""

    evidence = _evidence(tmp_path)
    cut = ProviderFailure("length", "truncated at the output-token limit", retryable=True)
    provider = InspectingProvider(evidence.events_path, [cut for _ in range(10)])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=10, retryable_conditions=("length",)),
    )
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    assert [request.max_output_tokens for request in provider.requests] == [80, 160, 320, 640]


def test_a_declared_ceiling_replaces_the_default_multiple(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_truncated() for _ in range(10)])
    profile = _with_config(
        _profile(max_action_attempts=10, retryable_conditions=("length",)),
        max_output_tokens_ceiling=200,
    )
    executor = _executor(tmp_path, provider, evidence=evidence, profile=profile)
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    assert [request.max_output_tokens for request in provider.requests] == [80, 160, 200]


@pytest.mark.parametrize("ceiling", [79, 0, -1, True, 160.0, "160"])
def test_a_bad_ceiling_is_refused_before_any_call(tmp_path, ceiling) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    with pytest.raises(EvidenceIntegrityError, match="max_output_tokens_ceiling"):
        _executor(
            tmp_path,
            provider,
            evidence=evidence,
            profile=_with_config(_profile(), max_output_tokens_ceiling=ceiling),
        )
    assert provider.requests == []


def test_a_ceiling_equal_to_the_budget_disables_growth(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_truncated(), _success_result()])
    profile = _with_config(
        _profile(max_action_attempts=5, retryable_conditions=("length",)),
        max_output_tokens_ceiling=80,
    )
    executor = _executor(tmp_path, provider, evidence=evidence, profile=profile)
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(executor(_decision()))
    assert raised.value.condition == "length" and len(provider.requests) == 1


# --- harness-driven attempts ---


def _harness_executor(tmp_path, provider, *, harnesses, profile, name="harness"):
    decision = _decision()
    evidence = EvidenceStore(
        tmp_path / name,
        run_plan_id="runplan_fixture",
        cell_id=decision.cell_id,
        episode_id=decision.episode_id,
        episode_attempt_id="episode_attempt_fixture",
    )
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=[profile],
        prompt_sources={profile.prompt.prompt_id: SYSTEM_PROMPT},
        providers={profile.model.provider: provider},
        pricing={profile.model.model: FAKE_PRICING},
        harnesses=harnesses,
    )
    return executor, decision, evidence


def _json_dialect_profile(**retry):
    base = _profile(**retry)
    return dataclasses.replace(
        base,
        harness=dataclasses.replace(
            base.harness, id="json_dialect", config={**dict(base.harness.config), "max_rounds": 4}
        ),
    )


def test_the_production_executor_types_an_unusable_truncated_reply(tmp_path) -> None:
    """Every production cell runs through AttemptExecutor and minimal_chat."""

    provider = ScriptedProvider([_result(text=CUT_OFF, finish_reason="length")])
    executor, decision, evidence = _harness_executor(
        tmp_path, provider, harnesses=default_harnesses(), profile=_profile()
    )
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(executor(decision))
    assert raised.value.condition == "length"
    assert executor.total_cost_usd > 0
    evidence.audit_reconciliation()


def test_model_turn_reports_why_the_provider_stopped(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    port = KernelModelPort(
        evidence=evidence,
        provider=ScriptedProvider(
            [_result(text=CUT_OFF, finish_reason="length"), _result(text='{"a":1}')]
        ),
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )
    cut = asyncio.run(port.complete(messages=(), response_mode="text"))
    done = asyncio.run(port.complete(messages=(), response_mode="text"))
    assert (cut.finish_reason, cut.truncated) == ("length", True)
    assert (done.finish_reason, done.truncated) == ("stop", False)
    # Additive: a turn built without it is unknown, not truncated.
    assert ModelTurn(text="x").finish_reason is None and not ModelTurn(text="x").truncated


def test_a_tool_loop_round_cut_off_mid_object_is_length_not_a_malformed_round(tmp_path) -> None:
    """It used to be counted as the model's malformed output."""

    evidence = _evidence(tmp_path)
    port = KernelModelPort(
        evidence=evidence,
        provider=ScriptedProvider(
            [_result(text='{"kind":"tool_calls","calls":[{"id":"c0","na', finish_reason="length")]
        ),
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )
    context = _KernelAttemptContext(
        attempt_id="action_attempt_fixture",
        seed=0,
        budget=BudgetView(rounds_left=2, tokens_left=None, cost_left=None),
        model=port,
        tools=None,
        evidence=evidence,
    )
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(JsonDialectHarness().act(_decision(), context))
    assert raised.value.condition == "length" and raised.value.retryable
    assert "harness_note" not in [event.event_type for event in evidence.read_events()]
    assert len(port.rounds) == 1, "the completed call stays on the port's ledger"


def test_a_finished_malformed_tool_loop_round_is_still_a_malformed_round(tmp_path) -> None:
    provider = ScriptedProvider([_result(text='{"kind":"tool_call"}', finish_reason="stop")])
    executor, decision, evidence = _harness_executor(
        tmp_path,
        provider,
        harnesses={"json_dialect/1.0": JsonDialectHarness()},
        profile=_json_dialect_profile(),
    )
    response = asyncio.run(executor(decision))
    assert response.action is not None
    assert "harness_note" in [event.event_type for event in evidence.read_events()]


def test_a_harness_attempt_cut_off_is_recorded_billed_and_typed_length(tmp_path) -> None:
    provider = ScriptedProvider([_result(text='{"kind":"reply","te', finish_reason="length")])
    executor, decision, evidence = _harness_executor(
        tmp_path,
        provider,
        harnesses={"json_dialect/1.0": JsonDialectHarness()},
        profile=_json_dialect_profile(),
    )
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(executor(decision))
    assert raised.value.condition == "length"
    (execution,) = executor.executions()
    (attempt,) = execution.attempts
    assert [call.status for call in attempt.provider_calls] == ["succeeded"]
    assert executor.total_cost_usd == pytest.approx(
        FAKE_PRICING.cost(input_tokens=20, cached_input_tokens=0, output_tokens=5)
    )
    kinds = [event["event_type"] for event in _events(evidence)]
    assert kinds.count("provider_call_succeeded") == 1
    assert "provider_call_failed" not in kinds
    evidence.audit_reconciliation()


def test_a_length_retry_widens_every_round_of_a_harness_attempt(tmp_path) -> None:
    """The widened limit used to reach round 0 only: later rounds were
    rebuilt from the profile, and a harness could not raise them itself."""

    provider = ScriptedProvider(
        [
            _result(text='{"kind":"reply","te', finish_reason="length"),
            _result(text='{"kind":"reply","text":"first"}'),
        ]
    )
    executor, decision, evidence = _harness_executor(
        tmp_path,
        provider,
        harnesses={"json_dialect/1.0": JsonDialectHarness()},
        profile=_json_dialect_profile(max_action_attempts=2, retryable_conditions=("length",)),
    )
    response = asyncio.run(executor(decision))
    assert response.action is not None
    assert [request.max_output_tokens for request in provider.requests] == [80, 160]

    # A later round of the widened attempt is built at the widened limit, and
    # the harness may ask for anything up to it but nothing above it.
    port = KernelModelPort(
        evidence=evidence,
        provider=ScriptedProvider([_result(text="a"), _result(text="b"), _result(text="c")]),
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_widened",
        sealed_request=dataclasses.replace(provider.requests[1], provider_call_id="widened_round_0"),
    )
    asyncio.run(port.complete(messages=(), response_mode="text"))
    asyncio.run(port.complete(messages=(), response_mode="text"))
    asyncio.run(port.complete(messages=(), response_mode="text", max_output_tokens=120))
    assert [entry.request.max_output_tokens for entry in port.rounds] == [160, 160, 120]
    with pytest.raises(EvidenceIntegrityError, match="never raise"):
        asyncio.run(port.complete(messages=(), response_mode="text", max_output_tokens=161))


class _CutOffNativeCompletions(FakeOpenRouterNativeCompletions):
    """The native fixture with its first tool call's arguments cut mid-JSON."""

    def __init__(self, finish_reason: str) -> None:
        super().__init__()
        self._finish_reason = finish_reason

    async def create(self, **kwargs):
        raw = (await super().create(**kwargs)).model_dump(mode="json")
        choice = raw["choices"][0]
        choice["finish_reason"] = self._finish_reason
        choice["message"]["tool_calls"][0]["function"]["arguments"] = '{"amount_u'
        return SimpleNamespace(model_dump=lambda mode: raw)


def _native_request():
    return dataclasses.replace(
        _openrouter_request(),
        output_schema=None,
        messages=(CanonicalMessage(role="user", content="please act"),),
    ).with_computed_hash()


def test_openrouter_types_a_truncated_native_tool_call_as_length() -> None:
    """Arguments cut off mid-JSON under finish_reason "length" were a
    non-retryable provider_contract failure."""

    completions = _CutOffNativeCompletions("length")
    client = OpenRouterChatClient(sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(client.complete(_native_request()))
    assert raised.value.condition == "length" and raised.value.retryable


def test_openrouter_keeps_a_finished_malformed_tool_call_a_contract_failure() -> None:
    completions = _CutOffNativeCompletions("tool_calls")
    client = OpenRouterChatClient(sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(client.complete(_native_request()))
    assert raised.value.condition == "provider_contract" and not raised.value.retryable
