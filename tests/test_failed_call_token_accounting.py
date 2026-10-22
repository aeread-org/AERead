"""A failed call with unusable token counts never reports them as zeros (F1, #291)."""

from __future__ import annotations

import asyncio

import pytest

from aeread.shared_runner.analysis import research
from aeread.shared_runner.task.execution import ProviderFailure, failed_call_event_fields
from tests.test_shared_runner_execution import (
    FAKE_PRICING,
    InspectingProvider,
    _decision,
    _evidence,
    _executor,
)


def _failure(usage: dict) -> ProviderFailure:
    return ProviderFailure("provider_contract", "billed failure", retryable=False).with_reported_usage(
        {"choices": [{"index": 0}], "usage": usage}
    )


def _run(tmp_path, failure):
    evidence = _evidence(tmp_path)
    evidence.append_event(
        "phase_instance_started",
        {"phase": {"phase_id": "phase"}},
        phase_instance_id=_decision().phase_instance_id,
    )
    executor = _executor(tmp_path, InspectingProvider(evidence.events_path, [failure]), evidence=evidence)
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    failed = next(e for e in evidence.read_events() if e.event_type == "provider_call_failed")
    (call,) = research._extract_model_calls(evidence, task_id="t")
    return evidence.read_event_payload(failed), call


def test_invalid_input_count_with_valid_cost_is_incomplete_not_zero(tmp_path) -> None:
    payload, call = _run(tmp_path, _failure({"prompt_tokens": -1, "completion_tokens": 5, "cost": 0.04}))
    assert payload["token_accounting"] == "incomplete"
    assert "input_tokens" not in payload
    assert payload["output_tokens"] == 5 and payload["cost_usd"] == 0.04
    assert call.prompt_tokens is None and call.telemetry_complete is False
    assert call.completion_tokens == 5 and call.total_cost_usd == 0.04


def test_complete_counts_write_the_event_they_always_wrote(tmp_path) -> None:
    payload, call = _run(
        tmp_path,
        _failure({"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 4}, "cost": 0.04}),
    )
    assert "token_accounting" not in payload
    assert (payload["input_tokens"], payload["cached_input_tokens"], payload["output_tokens"]) == (20, 4, 5)
    assert (call.prompt_tokens, call.cached_tokens, call.completion_tokens, call.total_cost_usd) == (20, 4, 5, 0.04)
    assert call.telemetry_complete is True


def test_unknown_billing_does_not_fabricate_zero_for_the_invalid_field() -> None:
    failure = _failure({"prompt_tokens": 20, "completion_tokens": -2})
    assert failure.billing == "unknown"
    fields = failed_call_event_fields(failure, None, outcome_unknown=False)
    assert fields["token_accounting"] == "incomplete"
    assert fields["input_tokens"] == 20
    assert "output_tokens" not in fields
    assert fields["cost_usd"] == "unknown"


def test_no_usage_or_no_input_count_writes_no_cached_zero() -> None:
    # An unreported cache breakdown means no cached input only beside a valid input count.
    for usage in ({}, {"completion_tokens": 5}, {"prompt_tokens": -1, "completion_tokens": 5}):
        fields = failed_call_event_fields(_failure(usage), None, outcome_unknown=False)
        assert fields["token_accounting"] == "incomplete", usage
        assert "cached_input_tokens" not in fields, usage
        assert "input_tokens" not in fields, usage


def test_an_event_without_token_fields_or_marker_reads_as_before(tmp_path) -> None:
    # A never-billed failure writes the event shape all evidence before the
    # marker has: a cost and no token fields. The reader keeps reading it as
    # zero tokens with complete telemetry.
    payload, call = _run(tmp_path, ProviderFailure("provider_5xx", "no completion", retryable=False))
    assert "token_accounting" not in payload and "input_tokens" not in payload
    assert payload["cost_usd"] == 0.0
    assert (call.prompt_tokens, call.cached_tokens, call.completion_tokens) == (0, 0, 0)
    assert call.total_cost_usd == 0.0 and call.telemetry_complete is True
