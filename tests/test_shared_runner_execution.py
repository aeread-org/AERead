from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import (
    CanonicalResponse,
    ClaudeCodePrintClient,
    EvidenceIntegrityError,
    EvidenceStore,
    MinimalChatExecutor,
    OpenAIResponsesClient,
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    ToolExecutor,
)
from aeread.shared_runner.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.scheduler import (
    DecisionRequest,
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
    episode_id_for_cell,
    run_episode,
)
from aeread.shared_runner.schemas import AgentProfile, CaseManifest


SYSTEM_PROMPT = (
    "Return only one JSON object matching the requested action schema. "
    "Do not add markdown."
)
FAKE_PRICING = TokenPricing(
    input_per_million=0.05,
    cached_input_per_million=0.005,
    output_per_million=0.40,
    pricing_id="fake-pricing-v1",
)


def _profile(
    *,
    max_action_attempts: int = 1,
    retryable_conditions: tuple[str, ...] = (),
    max_cost_usd: float = 0.05,
    model: str = "fake-model",
    provider: str = "fake",
) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": "subject_model_v1",
            "model": {
                "provider": provider,
                "model": model,
                "revision": "pinned-v1",
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": FAKE_PRICING.pricing_id,
                    "pricing_sha256": FAKE_PRICING.content_sha256(),
                },
            },
            "prompt": {
                "prompt_id": "fixture_action_prompt",
                "sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_low_v1",
                "effort": "low",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 80,
                "seed": None,
            },
            "budgets": {
                "max_logical_actions": 4,
                "timeout_seconds": 5.0,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                "max_action_attempts": max_action_attempts,
                "retryable_conditions": list(retryable_conditions),
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def _decision() -> DecisionRequest:
    return DecisionRequest(
        episode_id="episode_fixture",
        phase_instance_id="phase_instance_fixture",
        logical_action_id="logical_action_fixture",
        cell_id="cell_fixture",
        case_id="fixture_case",
        phase_id="offer",
        seat_id="buyer",
        role="buyer",
        profile_id="subject_model_v1",
        observation_schema="private_value_v1",
        action_schema="offer_v1",
        observation={"private_value": 11},
    )


def _evidence(tmp_path) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )


def _success_result(*, text: str = '{"offer":7}', cost: float | None = None):
    return ProviderResult(
        response_id="response_fixture",
        requested_model="fake-model",
        resolved_model="fake-model-v1",
        output_text=text,
        finish_reason="stop",
        input_tokens=20,
        cached_input_tokens=0,
        output_tokens=5,
        cost_usd=cost,
        raw_response={"id": "response_fixture", "output_text": text},
    )


class InspectingProvider:
    def __init__(self, evidence_path, outcomes):
        self.evidence_path = evidence_path
        self.outcomes = list(outcomes)
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        events = [json.loads(line) for line in self.evidence_path.read_text().splitlines()]
        assert events[-1]["event_type"] == "provider_call_started"
        assert events[-1]["provider_call_id"] == request.provider_call_id
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _executor(tmp_path, provider, *, profile=None, evidence=None):
    return MinimalChatExecutor(
        evidence=evidence or _evidence(tmp_path),
        profiles=(profile or _profile(),),
        prompt_sources={"fixture_action_prompt": SYSTEM_PROMPT},
        providers={"fake": provider},
        pricing={
            "fake-model": FAKE_PRICING
        },
    )


def test_provider_start_is_durable_before_call_and_all_records_reconcile(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    executor = _executor(tmp_path, provider, evidence=evidence)

    response = asyncio.run(executor(_decision()))
    assert isinstance(response, CanonicalResponse)
    assert response.text == '{"offer":7}'
    assert response.empty is False
    assert response.truncated is False
    assert len(provider.requests) == 1

    executor.finalize_logical_action(
        _decision().logical_action_id, valid=True, failure_code=None
    )
    evidence.audit_reconciliation()
    events = evidence.read_events()
    assert [event.sequence for event in events] == list(range(len(events)))
    assert [event.event_type for event in events] == [
        "logical_action_started",
        "action_attempt_started",
        "provider_call_started",
        "provider_call_succeeded",
        "action_attempt_succeeded",
        "logical_action_succeeded",
    ]
    evidence.verify_chain()


def test_declared_retry_creates_new_action_attempt_and_new_provider_call(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path,
        [ProviderFailure("timeout", "transient timeout", retryable=True), _success_result()],
    )
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=2, retryable_conditions=("timeout",)),
    )

    response = asyncio.run(executor(_decision()))
    executor.finalize_logical_action(
        _decision().logical_action_id, valid=True, failure_code=None
    )
    assert response.text == '{"offer":7}'
    execution = executor.execution_for(_decision().logical_action_id)
    assert len(execution.attempts) == 2
    assert [attempt.status for attempt in execution.attempts] == ["failed", "succeeded"]
    assert len({attempt.action_attempt_id for attempt in execution.attempts}) == 2
    assert len(provider.requests) == 2
    assert len({request.provider_call_id for request in provider.requests}) == 2
    assert execution.attempts[1].retry_reason == "timeout"
    assert execution.attempts[0].provider_calls[0].status == "outcome_unknown"
    assert "provider_call_outcome_unknown" in {
        event.event_type for event in evidence.read_events()
    }
    evidence.audit_reconciliation()


def test_nonretryable_provider_failure_is_terminal_and_not_hidden(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path,
        [ProviderFailure("authentication", "bad key", retryable=False)],
    )
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=3, retryable_conditions=("timeout",)),
    )

    with pytest.raises(ProviderFailure, match="bad key"):
        asyncio.run(executor(_decision()))
    assert len(provider.requests) == 1
    assert executor.execution_for(_decision().logical_action_id).status == "failed"
    evidence.audit_reconciliation()


def test_cancelled_provider_call_is_marked_outcome_unknown(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [asyncio.CancelledError()])
    executor = _executor(tmp_path, provider, evidence=evidence)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor(_decision()))
    event_types = [event.event_type for event in evidence.read_events()]
    assert "provider_call_outcome_unknown" in event_types
    assert "action_attempt_outcome_unknown" in event_types
    assert "logical_action_outcome_unknown" in event_types
    evidence.audit_reconciliation()


def test_prompt_hash_mismatch_fails_before_any_provider_or_event(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])

    with pytest.raises(EvidenceIntegrityError, match="prompt hash"):
        MinimalChatExecutor(
            evidence=evidence,
            profiles=(_profile(),),
            prompt_sources={"fixture_action_prompt": "changed prompt"},
            providers={"fake": provider},
            pricing={
                "fake-model": FAKE_PRICING
            },
        )
    assert not evidence.events_path.exists()
    assert provider.requests == []


def test_pricing_hash_mismatch_fails_before_any_provider_or_event(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    changed_pricing = TokenPricing(0.06, 0.005, 0.4, "fake-pricing-v1")

    with pytest.raises(EvidenceIntegrityError, match="pricing hash"):
        MinimalChatExecutor(
            evidence=evidence,
            profiles=(_profile(),),
            prompt_sources={"fixture_action_prompt": SYSTEM_PROMPT},
            providers={"fake": provider},
            pricing={"fake-model": changed_pricing},
        )
    assert not evidence.events_path.exists()
    assert provider.requests == []


def test_cost_budget_is_checked_from_recorded_usage_without_retry(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result(cost=0.02)])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_cost_usd=0.01),
    )

    with pytest.raises(EvidenceIntegrityError, match="cost budget"):
        asyncio.run(executor(_decision()))
    assert len(provider.requests) == 1
    assert executor.total_cost_usd == pytest.approx(0.02)
    evidence.audit_reconciliation()


def test_cost_budgets_are_enforced_per_profile_not_against_run_total(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path,
        [_success_result(cost=0.01), _success_result(cost=0.01)],
    )
    first_profile = _profile(max_cost_usd=0.015)
    second_profile = replace(first_profile, profile_id="second_model_v1")
    executor = MinimalChatExecutor(
        evidence=evidence,
        profiles=(first_profile, second_profile),
        prompt_sources={"fixture_action_prompt": SYSTEM_PROMPT},
        providers={"fake": provider},
        pricing={"fake-model": FAKE_PRICING},
    )
    first_decision = _decision()
    second_decision = replace(
        first_decision,
        profile_id="second_model_v1",
        logical_action_id="logical_action_second",
    )

    asyncio.run(executor(first_decision))
    executor.finalize_logical_action(
        first_decision.logical_action_id, valid=True, failure_code=None
    )
    asyncio.run(executor(second_decision))
    executor.finalize_logical_action(
        second_decision.logical_action_id, valid=True, failure_code=None
    )
    assert executor.total_cost_usd == pytest.approx(0.02)
    evidence.audit_reconciliation()


def test_tool_executor_records_success_and_unknown_outcome(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)

    async def successful(arguments):
        events = evidence.read_events()
        assert events[-1].event_type == "tool_invocation_started"
        return {"echo": arguments["value"]}

    result, record = asyncio.run(
        tools.invoke(
            action_attempt_id="action_attempt_fixture",
            tool_id="echo",
            tool_version="1.0.0",
            arguments={"value": 3},
            implementation=successful,
            idempotency_supported=True,
        )
    )
    assert result == {"echo": 3}
    assert record.status == "succeeded"

    async def cancelled(_arguments):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="cancelled",
                tool_version="1.0.0",
                arguments={},
                implementation=cancelled,
                idempotency_supported=False,
            )
        )
    evidence.audit_reconciliation(entity_types=("tool_invocation",))
    assert "tool_invocation_outcome_unknown" in {
        event.event_type for event in evidence.read_events()
    }


class FakeResponsesAPI:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_openai_fixture",
            model="gpt-5-nano-2025-08-07",
            status="completed",
            output_text='{"offer":7}',
            incomplete_details=None,
            usage=SimpleNamespace(
                input_tokens=31,
                output_tokens=9,
                input_tokens_details=SimpleNamespace(cached_tokens=4),
            ),
            model_dump=lambda mode: {
                "id": "resp_openai_fixture",
                "model": "gpt-5-nano-2025-08-07",
                "status": "completed",
                "output_text": '{"offer":7}',
            },
        )


def test_openai_responses_adapter_uses_explicit_supported_request_fields() -> None:
    responses = FakeResponsesAPI()
    sdk = SimpleNamespace(responses=responses)
    client = OpenAIResponsesClient(sdk_client=sdk)
    request = ProviderRequest(
        provider_call_id="provider_call_fixture",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-5-nano-2025-08-07",
        revision="gpt-5-nano-2025-08-07",
        instructions=SYSTEM_PROMPT,
        input_text='{"observation":{"private_value":11},"action_schema":"offer_v1"}',
        temperature=0.0,
        top_p=None,
        max_output_tokens=80,
        reasoning_effort="low",
        timeout_seconds=5.0,
        request_sha256="",
    ).with_computed_hash()

    result = asyncio.run(client.complete(request))
    assert responses.kwargs == {
        "model": "gpt-5-nano-2025-08-07",
        "instructions": SYSTEM_PROMPT,
        "input": request.input_text,
        "max_output_tokens": 80,
        "reasoning": {"effort": "low"},
        "store": False,
    }
    assert result.response_id == "resp_openai_fixture"
    assert result.resolved_model == "gpt-5-nano-2025-08-07"
    assert result.input_tokens == 31
    assert result.cached_input_tokens == 4
    assert result.output_tokens == 9


def test_openai_adapter_rejects_missing_responses_surface() -> None:
    with pytest.raises(EvidenceIntegrityError, match="Responses API"):
        OpenAIResponsesClient(sdk_client=SimpleNamespace())


def test_openai_adapter_requires_key_before_constructing_default_sdk(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EvidenceIntegrityError, match="OPENAI_API_KEY"):
        OpenAIResponsesClient()


class FakeOpenRouterCompletions:
    def __init__(
        self,
        *,
        selected_provider: str = "DeepInfra",
        attempt: int = 1,
        include_attempts: bool = True,
    ) -> None:
        self.kwargs = None
        self.selected_provider = selected_provider
        self.attempt = attempt
        self.include_attempts = include_attempts

    async def create(self, **kwargs):
        self.kwargs = kwargs
        routing_metadata = {
            "requested": "deepseek/deepseek-v4-flash-0731",
            "strategy": "direct",
            "region": "iad",
            "summary": f"available=1, selected={self.selected_provider}",
            "attempt": self.attempt,
            "is_byok": False,
            "endpoints": {
                "total": 1,
                "available": [
                    {
                        "model": "deepseek/deepseek-v4-flash-20260731",
                        "provider": self.selected_provider,
                        "selected": True,
                    }
                ],
            },
        }
        if self.include_attempts:
            routing_metadata["attempts"] = [
                {
                    "model": "deepseek/deepseek-v4-flash-20260731",
                    "provider": self.selected_provider,
                    "status": 200,
                }
            ]
        raw = {
            "id": "gen_openrouter_fixture",
            "model": "deepseek/deepseek-v4-flash-0731",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"offer":7}'},
                }
            ],
            "usage": {
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "total_tokens": 168,
                "prompt_tokens_details": {"cached_tokens": 7},
                "cost": 0.00001726,
                "is_byok": False,
            },
            "openrouter_metadata": routing_metadata,
        }
        return SimpleNamespace(model_dump=lambda mode: raw)


def _openrouter_request() -> ProviderRequest:
    output_schema = {
        "type": "object",
        "properties": {"offer": {"type": "integer", "minimum": 0}},
        "required": ["offer"],
        "additionalProperties": False,
    }
    return ProviderRequest(
        provider_call_id="provider_call_openrouter_fixture",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="deepseek/deepseek-v4-flash-0731",
        revision="deepseek/deepseek-v4-flash-20260731",
        instructions=SYSTEM_PROMPT,
        input_text='{"observation":{"private_value":11},"action_schema":"offer_v1"}',
        temperature=0.0,
        top_p=1.0,
        max_output_tokens=512,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        max_cost_usd=0.001,
        output_schema=output_schema,
        provider_metadata={
            "route_provider": "DeepInfra",
            "quantization": "fp8",
            "canonical_model": "deepseek/deepseek-v4-flash-20260731",
            "max_prompt_price_per_million": "0.08",
            "max_completion_price_per_million": "0.18",
        },
        seed=71001,
    ).with_computed_hash()


def test_openrouter_adapter_pins_deepseek_route_and_parses_usage() -> None:
    completions = FakeOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    request = _openrouter_request()

    result = asyncio.run(client.complete(request))

    assert completions.kwargs == {
        "model": "deepseek/deepseek-v4-flash-0731",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request.input_text},
        ],
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 71001,
        "max_tokens": 512,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "aeread_action",
                "strict": True,
                "schema": request.output_schema,
            },
        },
        "tools": [],
        "stream": False,
        "extra_headers": {"X-OpenRouter-Metadata": "enabled"},
        "extra_body": {
            "reasoning": {"effort": "low"},
            "provider": {
                "only": ["DeepInfra"],
                "order": ["DeepInfra"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "quantizations": ["fp8"],
                "max_price": {"prompt": "0.08", "completion": "0.18"},
            },
        },
    }
    assert result.output_text == '{"offer":7}'
    assert result.requested_model == "deepseek/deepseek-v4-flash-0731"
    assert result.resolved_model == "deepseek/deepseek-v4-flash-20260731"
    assert result.input_tokens == 123
    assert result.cached_input_tokens == 7
    assert result.output_tokens == 45
    assert result.cost_usd == pytest.approx(0.00001726)


def test_openrouter_adapter_serializes_a_frozen_schema_as_plain_json() -> None:
    completions = FakeOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    frozen_schema = MappingProxyType(
        {
            "type": "object",
            "properties": MappingProxyType(
                {"offer": MappingProxyType({"type": "integer", "minimum": 0})}
            ),
            "required": ("offer",),
            "additionalProperties": False,
        }
    )
    request = replace(_openrouter_request(), output_schema=frozen_schema).with_computed_hash()

    asyncio.run(client.complete(request))

    transmitted_schema = completions.kwargs["response_format"]["json_schema"]["schema"]
    assert transmitted_schema == {
        "type": "object",
        "properties": {"offer": {"type": "integer", "minimum": 0}},
        "required": ["offer"],
        "additionalProperties": False,
    }
    json.dumps(completions.kwargs)


def test_openrouter_adapter_rejects_an_unpinned_selected_provider() -> None:
    completions = FakeOpenRouterCompletions(selected_provider="OpenInference")
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)

    with pytest.raises(ProviderFailure, match="selected provider"):
        asyncio.run(client.complete(_openrouter_request()))


def test_openrouter_adapter_rejects_a_later_route_attempt_without_attempt_details() -> None:
    completions = FakeOpenRouterCompletions(attempt=2, include_attempts=False)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)

    with pytest.raises(ProviderFailure, match="fallback"):
        asyncio.run(client.complete(_openrouter_request()))


def test_openrouter_adapter_requires_key_before_constructing_default_sdk(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(EvidenceIntegrityError, match="OPENROUTER_API_KEY"):
        OpenRouterChatClient()


def test_claude_code_adapter_pins_runtime_and_parses_structured_usage(tmp_path) -> None:
    executable = tmp_path / "claude"
    executable.write_bytes(b"pinned claude executable")
    executable.chmod(0o755)
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    calls: list[tuple[tuple[str, ...], bytes]] = []
    payload = {
        "is_error": False,
        "uuid": "result_fixture",
        "stop_reason": "end_turn",
        "terminal_reason": "completed",
        "total_cost_usd": 0.001798,
        "structured_output": {"offer": 7},
        "modelUsage": {
            "claude-haiku-4-5-20251001": {
                "inputTokens": 1188,
                "outputTokens": 122,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "costUSD": 0.001798,
                "canonicalModel": "claude-haiku-4-5",
                "provider": "firstParty",
            }
        },
    }

    async def command_runner(arguments: tuple[str, ...], standard_input: bytes):
        calls.append((arguments, standard_input))
        return 0, json.dumps(payload).encode(), b""

    client = ClaudeCodePrintClient(
        executable=executable,
        runtime_version="2.1.241",
        runtime_sha256=executable_sha256,
        command_runner=command_runner,
    )
    output_schema = {
        "type": "object",
        "properties": {"offer": {"type": "integer", "minimum": 0}},
        "required": ["offer"],
        "additionalProperties": False,
    }
    request = ProviderRequest(
        provider_call_id="provider_call_claude_fixture",
        provider="claude_code",
        base_url=None,
        model="claude-haiku-4-5-20251001",
        revision="claude-haiku-4-5-20251001",
        instructions=SYSTEM_PROMPT,
        input_text='{"observation":{"private_value":11},"action_schema":"offer_v1"}',
        temperature=0.0,
        top_p=None,
        max_output_tokens=256,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        max_cost_usd=0.01,
        output_schema=output_schema,
        provider_metadata={
            "runtime_version": "2.1.241",
            "runtime_sha256": executable_sha256,
        },
    ).with_computed_hash()

    result = asyncio.run(client.complete(request))

    assert result.output_text == '{"offer":7}'
    assert result.requested_model == "claude-haiku-4-5-20251001"
    assert result.resolved_model == "claude-haiku-4-5-20251001"
    assert result.input_tokens == 1188
    assert result.output_tokens == 122
    assert result.cost_usd == pytest.approx(0.001798)
    assert len(calls) == 1
    arguments, standard_input = calls[0]
    assert arguments[0] == str(executable)
    assert arguments[arguments.index("--model") + 1] == request.model
    assert arguments[arguments.index("--effort") + 1] == "low"
    assert arguments[arguments.index("--max-budget-usd") + 1] == "0.01"
    assert arguments[arguments.index("--json-schema") + 1] == json.dumps(
        output_schema, sort_keys=True, separators=(",", ":")
    )
    assert "--safe-mode" in arguments
    assert "--no-session-persistence" in arguments
    assert request.input_text not in arguments
    assert standard_input == request.input_text.encode("utf-8")


def test_claude_code_adapter_rejects_runtime_hash_mismatch_before_call(tmp_path) -> None:
    executable = tmp_path / "claude"
    executable.write_bytes(b"changed executable")
    calls = 0

    async def command_runner(_arguments: tuple[str, ...], _standard_input: bytes):
        nonlocal calls
        calls += 1
        return 0, b"{}", b""

    client = ClaudeCodePrintClient(
        executable=executable,
        runtime_version="2.1.241",
        runtime_sha256="0" * 64,
        command_runner=command_runner,
    )
    request = ProviderRequest(
        provider_call_id="provider_call_claude_fixture",
        provider="claude_code",
        base_url=None,
        model="claude-haiku-4-5-20251001",
        revision="claude-haiku-4-5-20251001",
        instructions=SYSTEM_PROMPT,
        input_text="{}",
        temperature=0.0,
        top_p=None,
        max_output_tokens=256,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        max_cost_usd=0.01,
        output_schema={"type": "object"},
        provider_metadata={
            "runtime_version": "2.1.241",
            "runtime_sha256": "0" * 64,
        },
    ).with_computed_hash()

    with pytest.raises(ProviderFailure, match="runtime digest"):
        asyncio.run(client.complete(request))
    assert calls == 0


def _single_case() -> CaseManifest:
    raw = {
        "spec_version": "aeread.case/0.1",
        "case_id": "single_v1__dev__000001",
        "family_id": "single_v1",
        "family_version": "1.0.0",
        "split": "dev",
        "world_seed": 71001,
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {"max_logical_actions": 1, "termination": ["submitted"]},
        "visibility_policy": "single_private_v1",
        "payload": {"private_value": 11},
        "provenance": {
            "generator_id": "single_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _single_cell() -> PlanCell:
    case = _single_case()
    return PlanCell(
        spec_version="aeread.plan_cell/0.1",
        cell_id="cell_single000000000001",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="single_dev_v1",
        suite_version="1.0.0",
        block_id="single_controlled",
        sampling_plan_id="single_sample_v1",
        analysis_plan_id="single_analysis_v1",
        world_seed=case.world_seed,
        sampling_seed=1,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_single",
        cluster_level="world_seed",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="fixed_panel",
        profile_by_seat=MappingProxyType({"buyer": "subject_model_v1"}),
        execution_mode="evaluate",
        case_max_logical_actions=1,
    )


class SingleActionPlugin:
    def validate_payload(self, payload):
        return dict(payload)

    def initial_state(self, case, run):
        return {"private_value": case["private_value"], "offer": None, "done": False}

    def phases(self, case):
        return (
            PhaseSpec(
                phase_id="offer",
                actor_selector="buyer_only",
                mode="single",
                observation_schema_by_role={"buyer": "private_value_v1"},
                action_schema_by_role={"buyer": "offer_v1"},
                max_logical_actions=1,
                invalid_action_policy="reject",
                next_phases=(),
            ),
        )

    def eligible_actors(self, case, state, phase):
        return ("buyer",)

    def observe(self, case, state, seat, phase):
        return {"private_value": state["private_value"]}

    def parse_action(self, case, state, seat, phase, response):
        assert isinstance(response, CanonicalResponse)
        parsed = json.loads(response.text)
        if not isinstance(parsed.get("offer"), int):
            return ParseResult.failure("malformed_offer")
        return ParseResult.success(parsed)

    def legal(self, case, state, seat, phase, action):
        return (
            LegalityResult.legal_action()
            if action["offer"] >= 0
            else LegalityResult.illegal("negative_offer")
        )

    def step(self, case, state, phase, actions):
        next_state = dict(state)
        next_state["offer"] = actions["buyer"].action["offer"]
        next_state["done"] = True
        return TransitionResult(state=next_state, next_phase_id=None)

    def terminal(self, case, state):
        return {"reason": "submitted"} if state["done"] else None

    def outcome(self, case, terminal):
        return {"valid": True, "reason": terminal["reason"]}


def test_r3_scheduler_drives_r4_executor_and_reconciles_action(tmp_path) -> None:
    cell = _single_cell()
    episode_id = episode_id_for_cell(cell)
    evidence = EvidenceStore(
        tmp_path / "integrated_evidence",
        run_plan_id="runplan_single",
        cell_id=cell.cell_id,
        episode_id=episode_id,
        episode_attempt_id=f"episode_attempt_{episode_id}_0",
    )
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    executor = _executor(tmp_path, provider, evidence=evidence)

    result = asyncio.run(
        run_episode(
            cell=cell,
            case=_single_case(),
            plugin=SingleActionPlugin(),
            response_source=executor,
        )
    )

    assert result.episode_id == episode_id
    assert result.final_state["offer"] == 7
    assert result.outcome == {"valid": True, "reason": "submitted"}
    execution = executor.execution_for(
        result.phase_instances[0].actions[0].logical_action_id
    )
    assert execution.status == "succeeded"
    evidence.audit_reconciliation()
