"""Streamed provider calls: declared per profile, assembled to the same result.

A long reasoning call sent with ``stream: false`` holds a connection that
carries no bytes until the answer; 76 such calls lost their connection 76 s
after starting (DC-T-14). The chunk shapes here are the ones OpenRouter
returned to a live streamed call on 2026-10-01.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from aeread.shared_runner.model_call.harness import CanonicalMessage, KernelModelPort
from aeread.shared_runner.task.execution import (
    ArenaChatClient,
    EvidenceIntegrityError,
    OpenAIResponsesClient,
    OpenRouterChatClient,
    ProviderFailure,
    _assemble_chat_stream,
    declared_provider_stream,
)
from tests.test_shared_runner_execution import (
    SYSTEM_PROMPT,
    FakeOpenRouterCompletions,
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


class TransportError(Exception):
    """Stands in for the transport library's base error, matched by name."""


class RemoteProtocolError(TransportError):
    pass


class TimeoutException(TransportError):
    pass


class ReadTimeout(TimeoutException):
    pass


def _chunks_of(raw: dict, *, pieces: int = 3) -> list[dict]:
    """Split a non-streamed response into the chunks a stream would carry."""

    choice = raw["choices"][0]
    message = choice["message"]
    base = {"id": raw["id"], "model": raw["model"], "object": "chat.completion.chunk", "provider": "DeepInfra"}
    chunks: list[dict] = []
    content = message.get("content") or ""
    size = max(1, -(-len(content) // pieces))
    for start in range(0, len(content), size):
        chunks.append(
            {**base, "choices": [{"index": 0, "finish_reason": None, "delta": {"role": "assistant", "content": content[start : start + size]}}]}
        )
    for index, call in enumerate(message.get("tool_calls") or ()):
        arguments = call["function"]["arguments"]
        half = len(arguments) // 2
        chunks.append(
            {**base, "choices": [{"index": 0, "finish_reason": None, "delta": {"role": "assistant", "content": None, "tool_calls": [
                {"index": index, "id": call["id"], "type": "function", "function": {"name": call["function"]["name"], "arguments": arguments[:half]}}]}}]}
        )
        chunks.append(
            {**base, "choices": [{"index": 0, "finish_reason": None, "delta": {"role": "assistant", "content": None, "tool_calls": [
                {"index": index, "function": {"arguments": arguments[half:]}}]}}]}
        )
    chunks.append({**base, "choices": [{"index": 0, "finish_reason": choice["finish_reason"], "delta": {"role": "assistant", "content": ""}}]})
    chunks.append(
        {
            **base,
            "choices": [{"index": 0, "finish_reason": choice["finish_reason"], "delta": {"role": "assistant", "content": ""}}],
            "usage": raw["usage"],
            "openrouter_metadata": raw["openrouter_metadata"],
        }
    )
    return chunks


class _Stream:
    def __init__(self, chunks, *, fail_after=None, error=None):
        self._chunks = list(chunks)
        self._fail_after = fail_after
        self._error = error

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for index, chunk in enumerate(self._chunks):
            if self._fail_after is not None and index == self._fail_after:
                raise self._error
            yield SimpleNamespace(model_dump=lambda mode, chunk=chunk: chunk)
        if self._fail_after is not None and self._fail_after >= len(self._chunks):
            raise self._error


class _StreamingCompletions:
    """Serves the same response as a fixture, whole or as a stream."""

    def __init__(self, fixture, *, fail_after=None, error=None, mutate=None):
        self._fixture = fixture
        self._fail_after = fail_after
        self._error = error
        self._mutate = mutate
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        whole = await self._fixture.create(**{k: v for k, v in kwargs.items() if k != "stream_options"})
        if not kwargs.get("stream"):
            return whole
        chunks = _chunks_of(whole.model_dump(mode="json"))
        if self._mutate is not None:
            chunks = self._mutate(chunks)
        return _Stream(chunks, fail_after=self._fail_after, error=self._error)


def _client(completions) -> OpenRouterChatClient:
    return OpenRouterChatClient(sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))


def _streamed(request):
    return dataclasses.replace(request, stream=True).with_computed_hash()


def _native(request):
    return dataclasses.replace(
        request, output_schema=None, messages=(CanonicalMessage(role="user", content="please act"),)
    ).with_computed_hash()


def test_a_streamed_structured_call_yields_the_same_result_as_a_whole_one() -> None:
    whole = asyncio.run(_client(FakeOpenRouterCompletions()).complete(_openrouter_request()))
    completions = _StreamingCompletions(FakeOpenRouterCompletions())
    streamed = asyncio.run(_client(completions).complete(_streamed(_openrouter_request())))
    assert completions.kwargs["stream"] is True
    assert completions.kwargs["stream_options"] == {"include_usage": True}
    for field in (
        "response_id", "requested_model", "resolved_model", "output_text", "finish_reason",
        "input_tokens", "cached_input_tokens", "output_tokens", "cost_usd", "tool_calls",
    ):
        assert getattr(streamed, field) == getattr(whole, field), field
    assert streamed.raw_response["stream"] == {"chunk_count": 5}


def test_a_streamed_native_call_reassembles_tool_calls_in_source_order() -> None:
    request = _native(_openrouter_request())
    whole = asyncio.run(_client(FakeOpenRouterNativeCompletions()).complete(request))
    streamed = asyncio.run(
        _client(_StreamingCompletions(FakeOpenRouterNativeCompletions())).complete(_streamed(request))
    )
    assert streamed.tool_calls == whole.tool_calls
    assert [call.call_id for call in streamed.tool_calls] == ["call_bravo", "call_alpha"]
    assert streamed.finish_reason == "tool_calls" and streamed.cost_usd == whole.cost_usd


def test_a_whole_call_is_sent_exactly_as_before() -> None:
    completions = _StreamingCompletions(FakeOpenRouterCompletions())
    asyncio.run(_client(completions).complete(_openrouter_request()))
    assert completions.kwargs["stream"] is False
    assert "stream_options" not in completions.kwargs


@pytest.mark.parametrize(
    ("error", "condition"),
    [
        (RemoteProtocolError("peer closed connection without sending complete message body"), "transport"),
        (ReadTimeout("timed out"), "timeout"),
    ],
)
@pytest.mark.parametrize("fail_after", [0, 2, 5])
def test_a_connection_that_dies_mid_reply_is_a_retryable_typed_failure(error, condition, fail_after) -> None:
    """Read after the SDK returns, so it arrives as the transport library's
    own exception; untyped it was a non-retryable provider_rejected."""

    completions = _StreamingCompletions(FakeOpenRouterCompletions(), fail_after=fail_after, error=error)
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(_client(completions).complete(_streamed(_openrouter_request())))
    assert raised.value.condition == condition and raised.value.retryable


def test_a_stream_that_ends_before_any_chunk_is_transport() -> None:
    completions = _StreamingCompletions(FakeOpenRouterCompletions(), mutate=lambda chunks: [])
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(_client(completions).complete(_streamed(_openrouter_request())))
    assert raised.value.condition == "transport" and raised.value.retryable


def test_an_error_chunk_is_typed_by_its_status() -> None:
    def with_error(chunks):
        return chunks[:1] + [{"id": chunks[0]["id"], "model": chunks[0]["model"], "choices": [],
                              "error": {"code": 502, "message": "upstream connection error"}}]

    completions = _StreamingCompletions(FakeOpenRouterCompletions(), mutate=with_error)
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(_client(completions).complete(_streamed(_openrouter_request())))
    assert raised.value.condition == "provider_5xx" and raised.value.status_code == 502


def test_a_stream_without_its_final_usage_chunk_is_refused() -> None:
    """Cost that never arrived is not priced locally and called complete."""

    completions = _StreamingCompletions(FakeOpenRouterCompletions(), mutate=lambda chunks: chunks[:-1])
    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(_client(completions).complete(_streamed(_openrouter_request())))
    assert raised.value.condition == "provider_contract"


def test_assembly_rejects_a_chunk_with_two_choices() -> None:
    with pytest.raises(ProviderFailure, match="at most one choice"):
        _assemble_chat_stream([{"id": "x", "choices": [{"delta": {}}, {"delta": {}}]}])


def test_the_request_hash_binds_stream_only_when_it_is_set() -> None:
    request = _openrouter_request()
    assert request.stream is False
    assert request.request_sha256 == "f440c8eb12eb57980096d6f7742b30a707590f15bf3f20065ff1c9f71fc0a03a"
    assert _streamed(request).request_sha256 != request.request_sha256


def _stream_profile(value=True, **retry):
    base = _profile(**retry)
    return dataclasses.replace(
        base,
        harness=dataclasses.replace(base.harness, config={**dict(base.harness.config), "provider_stream": value}),
    )


def test_a_profile_declares_streaming_and_the_executor_sends_it(tmp_path) -> None:
    assert declared_provider_stream(_profile()) is False
    assert declared_provider_stream(_stream_profile()) is True
    for name, profile, expected in (("plain", _profile(), False), ("stream", _stream_profile(), True)):
        evidence = _evidence(tmp_path / name)
        provider = InspectingProvider(evidence.events_path, [_success_result()])
        executor = _executor(tmp_path / name, provider, evidence=evidence, profile=profile)
        asyncio.run(executor(_decision()))
        assert provider.requests[0].stream is expected


@pytest.mark.parametrize("value", ["true", 1, None, 0])
def test_a_non_boolean_declaration_is_refused_before_any_call(tmp_path, value) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    with pytest.raises(EvidenceIntegrityError, match="provider_stream"):
        _executor(tmp_path, provider, evidence=evidence, profile=_stream_profile(value))


def test_every_round_of_a_harness_attempt_is_streamed(tmp_path) -> None:
    port = KernelModelPort(
        evidence=_evidence(tmp_path),
        provider=ScriptedProvider([_result(text="a"), _result(text="b")]),
        pricing=FAKE_PRICING,
        profile=_stream_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )
    asyncio.run(port.complete(messages=(), response_mode="text"))
    asyncio.run(port.complete(messages=(), response_mode="text"))
    assert [entry.request.stream for entry in port.rounds] == [True, True]


def test_clients_that_cannot_stream_refuse_instead_of_ignoring_the_declaration() -> None:
    arena = ArenaChatClient(sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=None)))
    request = dataclasses.replace(
        _openrouter_request(), provider="arena", base_url="https://api.preview.arena.ai/v1", stream=True
    )
    with pytest.raises(ProviderFailure, match="does not support streamed") as raised:
        asyncio.run(arena.complete(request))
    assert raised.value.condition == "provider_contract"

    openai = OpenAIResponsesClient(sdk_client=SimpleNamespace(responses=None))
    request = dataclasses.replace(
        _openrouter_request(), provider="openai", base_url="https://api.openai.com/v1", stream=True
    )
    with pytest.raises(ProviderFailure, match="does not support streamed"):
        asyncio.run(openai.complete(request))
