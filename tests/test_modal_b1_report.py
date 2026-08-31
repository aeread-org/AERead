"""Provider-free tests for the B1 Modal smoke reporting layer."""

import pytest

from integrations.rllm.modal_b1.report import (
    A10G_USD_PER_SECOND,
    build_run_report,
    format_cost_line,
    gpu_cost_usd,
    signal_rows_from_eval_output,
    variance_verdict,
)


class _FakeSignal:
    def __init__(self, name, value, metadata=None):
        self.name = name
        self.value = value
        self.metadata = metadata or {}


class _FakeEvalOutput:
    def __init__(self, signals, metadata=None):
        self.signals = signals
        self.metadata = metadata or {}


def test_signal_rows_flattens_named_signals():
    output = _FakeEvalOutput(
        signals=[
            _FakeSignal("episode_aer", 0.031, {"tier": "wstar_fallback"}),
            _FakeSignal("w_real", 3.1),
            _FakeSignal("denominator", 100.0),
            _FakeSignal("valid_measurement", 1.0),
            _FakeSignal("blank_completion_count", 0.0),
        ]
    )
    row = signal_rows_from_eval_output("case01:1200", output)
    assert row["task_id"] == "case01:1200"
    assert row["episode_aer"] == pytest.approx(0.031)
    assert row["valid_measurement"] is True
    assert row["tier"] == "wstar_fallback"


def test_variance_verdict_flags_degenerate_group():
    verdict = variance_verdict([0.25, 0.25, 0.25, 0.25])
    assert verdict["degenerate"] is True
    assert verdict["spread"] == pytest.approx(0.0)
    assert "escalate" in verdict["recommendation"]


def test_variance_verdict_accepts_real_spread():
    verdict = variance_verdict([-0.25, 0.25, 0.10, 0.0])
    assert verdict["degenerate"] is False
    assert verdict["spread"] == pytest.approx(0.5)
    assert "proceed" in verdict["recommendation"]


def test_variance_verdict_needs_at_least_two_values():
    verdict = variance_verdict([0.25])
    assert verdict["degenerate"] is True
    assert "insufficient" in verdict["recommendation"]


def test_negative_aer_is_a_score_not_a_failure():
    output = _FakeEvalOutput(
        signals=[
            _FakeSignal("episode_aer", -0.4),
            _FakeSignal("w_real", -40.0),
            _FakeSignal("denominator", 100.0),
            _FakeSignal("valid_measurement", 1.0),
        ]
    )
    row = signal_rows_from_eval_output("case02:1201", output)
    assert row["valid_measurement"] is True
    assert row["failure_class"] is None
    assert row["episode_aer"] == pytest.approx(-0.4)


def test_gpu_cost_uses_measured_seconds():
    assert gpu_cost_usd(600.0, A10G_USD_PER_SECOND) == pytest.approx(0.1836)


def test_cost_line_reports_zero_calls_without_crashing():
    report = build_run_report(
        stage="probe",
        rows=[],
        telemetry={"attempted": 0, "measured": 0, "failed": 0, "failed_by_class": {}},
        gpu_seconds=0.0,
        openrouter_usd=0.0,
        live_calls=0,
        cached_calls=0,
        total_tokens=0,
    )
    line = format_cost_line(report)
    assert line.startswith("cost: $")
    assert "0 calls" in line


def test_run_report_carries_pooled_aer_not_accuracy():
    rows = [
        {"task_id": "a", "episode_aer": 0.5, "w_real": 1.0, "denominator": 2.0,
         "valid_measurement": True, "tier": "wstar_fallback", "blank_completion_count": 0.0},
        {"task_id": "b", "episode_aer": 0.01, "w_real": 1.0, "denominator": 100.0,
         "valid_measurement": True, "tier": "wstar_fallback", "blank_completion_count": 0.0},
    ]
    report = build_run_report(
        stage="probe",
        rows=rows,
        telemetry={"attempted": 2, "measured": 2, "failed": 0, "failed_by_class": {}},
        gpu_seconds=100.0,
        openrouter_usd=0.014,
        live_calls=2,
        cached_calls=0,
        total_tokens=1000,
    )
    pooled = report["aggregate"]["pooled_aer_by_tier"]["wstar_fallback"]
    assert pooled == pytest.approx(2.0 / 102.0)
    assert report["aggregate"]["mean_episode_aer"] == pytest.approx(0.255)
    assert "accuracy" not in report
