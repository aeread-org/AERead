"""Publication regression for the observed score-free scheduler timeout."""

from tools.publish_procurement_phase2_recovery import public_failure_event


def test_timeout_is_publicly_typed_without_private_message():
    event = dict(event_type="provider_call_outcome_unknown", event_hash="a" * 64)
    payload = dict(failure_condition="timeout", retryable=True, status_code=None,
                   cost_usd="unknown", message="private provider context")
    result = public_failure_event(event, payload, phase="confirmatory", row_id="fixture")
    assert result["failure_condition"] == "timeout"
    assert result["status_code"] is None
    assert result["event_hash"] == event["event_hash"]
    assert "message" not in result and "cost_usd" not in result
    assert public_failure_event(
        dict(event_type="action_parsed", event_hash="b" * 64), payload,
        phase="confirmatory", row_id="fixture",
    ) is None
