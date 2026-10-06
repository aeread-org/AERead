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

import pytest

from aeread.shared_runner.task.execution import ProviderFailure
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


