"""A failed provider call is recorded correctly (#249, #250, #247 review).

Three small kernel fixes with one concern, each pinned red-first.

- #249: a failure raised after a round has terminalized as succeeded (for
  example a ``minimal_chat/1.0`` reply with both text and a tool call, typed
  ``provider_contract``) attaches to the attempt only, under every profile. No
  second provider-call terminal is written and no provider record is built for
  the attempt's first request. Under v0 this used to write
  ``provider_call_failed`` after ``provider_call_succeeded`` for one call, and
  ``EvidenceStore.audit_reconciliation()`` rejected the store.
- #250: an HTTP status error whose response body reports usage records that
  usage. ``APIStatusError.body`` holds only the inner ``error`` object, so the
  classifier reads ``error.response``. The failure becomes ``billing: reported``
  and its cost is charged once; a body with no usable usage is recorded as before.
- #247 review: a streamed failure that had seen usage was raised ``from`` itself,
  so ``failure.__cause__ is failure``.

The server side is the REAL openai SDK over its own mock transport (``httpx``
under openai 2.x, ``httpx2`` under 3.x), reusing the helpers of
``tests/test_transport_resend.py``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import traceback
from types import SimpleNamespace

import openai
import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import CanonicalMessage, default_harnesses
from aeread.shared_runner.task.execution import (
    EvidenceStore,
    MinimalChatExecutor,
    OpenAIResponsesClient,
    ProviderFailure,
    failed_call_cost,
)
from tests.test_transport_resend import (  # noqa: F401 - the two fixtures are autouse there
    MODEL,
    PRICING,
    V0_BACKOFF,
    V1,
    Scripted,
    Wire,
    _assert_evidence_survives_audit_and_resume,
    _failure_of,
    _http_lib,
    _instant_asyncio_sleep,
    _raw_completion,
    _scripted_ok,
    _sse,
    _stream_frames,
    _terminals,
    _text_and_a_tool_call,
    _USAGE,
    assert_failed_with,
    build_client,
    clock,
    exactly,
    make_profile,
    refuse,
    run_rig,
    started_ids,
    stalled_status,
)

PROFILES = {"v0": V0_BACKOFF, "transport_v1": V1}

# =====================================================================================
# #249  a failure after a succeeded round attaches to the attempt only
# =====================================================================================


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_text_and_a_tool_call_writes_one_terminal_and_the_store_reconciles(
    tmp_path, profile_name
) -> None:
    rig = run_rig(
        tmp_path,
        [],
        make_profile(PROFILES[profile_name]),
        wrap=lambda client: Scripted([_text_and_a_tool_call]),
    )

    assert_failed_with(rig, "provider_contract")
    log = rig.log
    (call_id,) = exactly(started_ids(log), 1)
    assert [(e["provider_call_id"], e["event_type"]) for e in _terminals(log, "provider_call")] == [
        (call_id, "provider_call_succeeded")
    ]
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert attempt.status == "failed"
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [
        (call_id, "succeeded")
    ]
    assert rig.execution.status == "failed"
    assert rig.execution.failure_code == "provider_contract"
    _assert_evidence_survives_audit_and_resume(rig)


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_a_failure_before_any_round_answered_still_gets_its_executor_terminal(
    tmp_path, profile_name
) -> None:
    """Control: nothing answered, so the executor writes the terminal as before."""

    rig = run_rig(
        tmp_path,
        [],
        make_profile(PROFILES[profile_name]),
        wrap=lambda client: Scripted(
            [ProviderFailure("provider_rejected", "bad request", retryable=False, status_code=400)]
        ),
    )

    assert_failed_with(rig, "provider_rejected")
    log = rig.log
    (call_id,) = exactly(started_ids(log), 1)
    assert [(e["provider_call_id"], e["event_type"]) for e in _terminals(log, "provider_call")] == [
        (call_id, "provider_call_failed")
    ]
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [
        (call_id, "failed")
    ]
    _assert_evidence_survives_audit_and_resume(rig)


class _FailsAfterOneRound:
    """A tool-owning-style harness: one successful round, then its own typed failure.

    The shape of govsim's ``malformed_structured_output`` and tau3's exhausted
    rounds: the failure is raised by the harness after a round answered.
    """

    id = "fails_after_round"
    version = "1.0"
    requires = default_harnesses()["minimal_chat/1.0"].requires

    async def open_episode(self, episode):
        return None

    async def close_episode(self, episode):
        return None

    def state_reader(self):
        return None

    def classify_failure(self, exc):
        from aeread.shared_runner.model_call.harness import FailureCondition

        return FailureCondition(exc.condition, retryable=exc.retryable)

    async def act(self, request, ctx):
        await ctx.model.complete(
            messages=(CanonicalMessage(role="user", content="go"),), response_mode="text"
        )
        raise ProviderFailure(
            "malformed_structured_output", "answer is not the schema", retryable=False
        )


@pytest.mark.parametrize("profile_name", ["v0"])
def test_a_harness_failure_after_a_succeeded_round_writes_one_terminal_per_call(
    tmp_path, monkeypatch, profile_name
) -> None:
    import tests.test_transport_resend as transport_tests

    monkeypatch.setattr(
        transport_tests,
        "default_harnesses",
        lambda: {**default_harnesses(), "fails_after_round/1.0": _FailsAfterOneRound()},
    )
    rig = run_rig(
        tmp_path,
        [],
        make_profile(PROFILES[profile_name], harness_id="fails_after_round"),
        wrap=lambda client: Scripted([_scripted_ok]),
    )

    assert_failed_with(rig, "malformed_structured_output")
    log = rig.log
    (call_id,) = exactly(started_ids(log), 1)
    assert [(e["provider_call_id"], e["event_type"]) for e in _terminals(log, "provider_call")] == [
        (call_id, "provider_call_succeeded")
    ]
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert attempt.status == "failed"
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [
        (call_id, "succeeded")
    ]
    assert rig.execution.status == "failed"
    assert rig.execution.failure_code == "malformed_structured_output"
    _assert_evidence_survives_audit_and_resume(rig)


# =====================================================================================
# #250  usage reported in an HTTP error body is recorded
# =====================================================================================

STREAMS = pytest.mark.parametrize("stream", [False, True], ids=["non_streamed", "streamed"])
STATUSES = pytest.mark.parametrize("status", [429, 503])
PLACES = pytest.mark.parametrize(
    "where", ["usage_at_top", "usage_under_error"], ids=["usage_at_top_level", "usage_under_error"]
)


def _reported(status, where):
    return refuse(status, **{where: True})


def _expected_cost() -> float:
    return PRICING.cost(
        input_tokens=_USAGE["prompt_tokens"],
        cached_input_tokens=0,
        output_tokens=_USAGE["completion_tokens"],
    )


@STREAMS
@STATUSES
@PLACES
def test_a_status_error_whose_body_reports_usage_is_recorded_as_billed(
    tmp_path, stream, status, where
) -> None:
    rig = run_rig(
        tmp_path,
        [_reported(status, where)],
        make_profile(V0_BACKOFF, stream=stream, max_action_attempts=1),
    )

    failure = rig.error
    assert isinstance(failure, ProviderFailure)
    assert failure.billing == "reported"
    assert failure.http_refusal is False
    assert (failure.input_tokens, failure.output_tokens) == (10, 5)
    (event,) = [e for e in rig.log if e["event_type"] == "provider_call_failed"]
    payload = event["payload"]
    cost = _expected_cost()
    assert cost > 0
    assert payload["cost_usd"] == pytest.approx(cost)
    assert (payload["input_tokens"], payload["cached_input_tokens"], payload["output_tokens"]) == (
        10,
        0,
        5,
    )
    (attempt,) = exactly(rig.execution.attempts, 1)
    (call,) = exactly(attempt.provider_calls, 1)
    assert call.cost_usd == pytest.approx(cost)
    assert (call.input_tokens, call.output_tokens) == (10, 5)
    # Charged exactly once: the executor charges it, the port only writes the event.
    assert rig.executor.total_cost_usd == pytest.approx(cost)
    _assert_evidence_survives_audit_and_resume(rig)


@STREAMS
def test_a_reported_cost_in_the_error_body_is_the_recorded_cost(tmp_path, stream) -> None:
    lib = _http_lib()

    def step(streamed):
        usage = {**_USAGE, "cost": 0.25}
        return lib.Response(503, json={"error": {"message": "x", "code": 503}, "usage": usage})

    rig = run_rig(
        tmp_path, [step], make_profile(V0_BACKOFF, stream=stream, max_action_attempts=1)
    )

    assert rig.error.billing == "reported"
    assert rig.executor.total_cost_usd == pytest.approx(0.25)
    (event,) = [e for e in rig.log if e["event_type"] == "provider_call_failed"]
    assert event["payload"]["cost_usd"] == pytest.approx(0.25)


@STREAMS
def test_a_refusal_whose_body_reports_usage_is_billed_and_not_resent_under_v1(
    tmp_path, stream
) -> None:
    rig = run_rig(
        tmp_path,
        [refuse(503, usage_at_top=True)],
        make_profile(V1, stream=stream, max_action_attempts=1),
    )

    assert rig.error.billing == "reported"
    assert rig.wire.requests == 1
    assert rig.executor.total_cost_usd == pytest.approx(_expected_cost())
    _assert_evidence_survives_audit_and_resume(rig)


UNBILLED = pytest.mark.parametrize(
    "step",
    [
        refuse(503),
        refuse(429),
        refuse(502, raw_body=b"<html><body>502 Bad Gateway</body></html>"),
        stalled_status(503),
    ],
    ids=["no_usage_503", "no_usage_429", "non_json_body", "stalled_body"],
)


@STREAMS
@UNBILLED
def test_a_status_error_with_no_usable_usage_is_recorded_as_before(
    tmp_path, stream, step
) -> None:
    rig = run_rig(
        tmp_path, [step], make_profile(V0_BACKOFF, stream=stream, max_action_attempts=1)
    )

    assert isinstance(rig.error, ProviderFailure)
    assert rig.error.billing == "not_billed"
    (event,) = [
        e
        for e in rig.log
        if e["event_type"] in {"provider_call_failed", "provider_call_outcome_unknown"}
    ]
    assert "input_tokens" not in event["payload"]
    assert event["payload"]["cost_usd"] in (0.0, "unknown")
    assert rig.executor.total_cost_usd == 0.0


@STREAMS
def test_a_body_with_malformed_usage_is_recorded_as_before(stream) -> None:
    lib = _http_lib()

    def step(streamed):
        return lib.Response(
            503, json={"error": {"message": "x", "code": 503}, "usage": {"prompt_tokens": "ten"}}
        )

    failure = _failure_of(stream, step)
    assert failure.billing == "not_billed"
    assert failure.cost_usd is None


def _status_error(body, status=503):
    lib = _http_lib()
    response = lib.Response(
        status, request=lib.Request("POST", "https://offline.invalid/v1/x"), json=body
    )
    return openai.APIStatusError("billed failure", response=response, body=body.get("error"))


RESPONSES_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "input_tokens_details": {"cached_tokens": 3},
}


@pytest.mark.parametrize("where", ["top", "under_error"])
def test_responses_style_usage_in_an_error_body_is_normalized(where) -> None:
    error = {"message": "billed failure", "code": 503}
    body = {"error": error}
    if where == "top":
        body["usage"] = dict(RESPONSES_USAGE)
    else:
        error["usage"] = dict(RESPONSES_USAGE)
    failure = OpenAIResponsesClient._classify_error(_status_error(body))

    assert failure.billing == "reported"
    assert (failure.input_tokens, failure.cached_input_tokens, failure.output_tokens) == (10, 3, 5)
    expected = PRICING.cost(input_tokens=10, cached_input_tokens=3, output_tokens=5)
    assert expected > 0
    assert failed_call_cost(failure, PRICING) == pytest.approx(expected)
    assert failure.http_refusal is False


def test_a_responses_error_body_with_usage_is_billed_through_the_client_and_executor(
    tmp_path,
) -> None:
    from tests.test_shared_runner_execution import FAKE_PRICING, _decision, _profile

    lib = _http_lib()
    body = {"error": {"message": "billed failure", "code": 503}, "usage": dict(RESPONSES_USAGE)}
    sdk = openai.AsyncOpenAI(
        api_key="k",
        max_retries=0,
        http_client=lib.AsyncClient(
            transport=lib.MockTransport(lambda request: lib.Response(503, json=body))
        ),
    )
    evidence = EvidenceStore(
        tmp_path / "responses",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    from tests.test_shared_runner_execution import SYSTEM_PROMPT

    executor = MinimalChatExecutor(
        evidence=evidence,
        profiles=(_profile(provider="openai"),),
        prompt_sources={"fixture_action_prompt": SYSTEM_PROMPT},
        providers={"openai": OpenAIResponsesClient(sdk_client=sdk)},
        pricing={"fake-model": FAKE_PRICING},
    )

    with pytest.raises(ProviderFailure) as raised:
        asyncio.run(executor(_decision()))

    expected = FAKE_PRICING.cost(input_tokens=10, cached_input_tokens=3, output_tokens=5)
    assert expected > 0
    assert raised.value.billing == "reported"
    assert executor.total_cost_usd == pytest.approx(expected)
    (event,) = [
        json.loads((evidence.root / entry["payload_ref"]).read_bytes())
        for entry in map(json.loads, (evidence.root / "events.jsonl").read_text().splitlines())
        if entry["event_type"] == "provider_call_failed"
    ]
    assert (event["input_tokens"], event["cached_input_tokens"], event["output_tokens"]) == (10, 3, 5)
    assert event["cost_usd"] == pytest.approx(expected)
    evidence.audit_reconciliation()


@pytest.mark.parametrize(
    "usage",
    [{}, {"foo": 1, "total_tokens": 15}, {"cost": 0.5}],
    ids=["empty", "unknown_keys", "cost_only"],
)
def test_a_mapping_that_is_not_usage_never_certifies_zero(usage) -> None:
    body = {"error": {"message": "x", "code": 503}, "usage": usage}
    failure = OpenAIResponsesClient._classify_error(_status_error(body))

    assert failure.billing == "not_billed"
    assert failed_call_cost(failure, PRICING) == 0.0


@pytest.mark.parametrize("bad_cost", [10**400, "1.5", [1], True])
def test_an_unusable_optional_cost_keeps_the_tokens_and_falls_back_to_pricing(bad_cost) -> None:
    usage = {**_USAGE, "cost": bad_cost}
    body = {"error": {"message": "x", "code": 503}, "usage": usage}
    failure = OpenAIResponsesClient._classify_error(_status_error(body))

    assert failure.billing == "reported"
    assert failure.cost_usd is None
    assert (failure.input_tokens, failure.output_tokens) == (10, 5)
    assert failed_call_cost(failure, PRICING) == pytest.approx(_expected_cost())


# =====================================================================================
# #247 review: a streamed failure is not its own cause
# =====================================================================================


def _usage_then_no_finish(streamed):
    lib = _http_lib()
    first = _stream_frames(_raw_completion("partial"))[0]
    first["usage"] = dict(_USAGE)
    return lib.Response(
        200, content=_sse([first]), headers={"content-type": "text/event-stream"}
    )


def test_a_streamed_failure_after_usage_was_seen_is_not_its_own_cause() -> None:
    failure = _failure_of(True, _usage_then_no_finish)

    assert failure.condition == "transport"
    assert failure.billing == "reported"
    assert (failure.input_tokens, failure.output_tokens) == (10, 5)
    assert failure.__cause__ is not failure


def test_a_streamed_failure_keeps_its_identity_cause_context_and_traceback(monkeypatch) -> None:
    """The usage is attached to the very exception the stream raised, untouched."""

    raised: list[BaseException] = []
    roots: list[BaseException] = []

    def failing_assemble(chunks):
        try:
            raise ValueError("root cause")
        except ValueError as root:
            roots.append(root)
            failure = ProviderFailure("transport", "assembly failed", retryable=True)
            raised.append(failure)
            raise failure from root

    monkeypatch.setattr(execution_module, "_assemble_chat_stream", failing_assemble)
    failure = _failure_of(True, _usage_then_no_finish)

    assert failure is raised[0]
    assert failure.billing == "reported"
    assert failure.__cause__ is roots[0]
    assert failure.__context__ is roots[0]
    assert any(
        frame.name == "failing_assemble" for frame in traceback.extract_tb(failure.__traceback__)
    )
