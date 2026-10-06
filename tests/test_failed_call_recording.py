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
