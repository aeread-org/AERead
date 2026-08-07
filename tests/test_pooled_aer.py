"""Provider-free tests for AERead's pooled-AER aggregation helper.

No rLLM import, no network -- these run in the plain unit matrix. See
``integrations/rllm/READINESS_PROPOSAL.md``, Workstream 5.
"""
from __future__ import annotations

import pytest

from aeread.integrations.pooled_aer import (
    EpisodeSignalRow,
    aggregate_eval_signals,
    pooled_aer_report,
)


def _measured(
    *, episode_aer, w_real, denominator, tier="wstar_fallback", **overrides
):
    row = {
        "valid_measurement": True,
        "episode_aer": episode_aer,
        "w_real": w_real,
        "denominator": denominator,
        "tier": tier,
    }
    row.update(overrides)
    return row


def _errored(*, failure_class="retryable_infrastructure", **overrides):
    row = {"valid_measurement": False, "failure_class": failure_class}
    row.update(overrides)
    return row


def test_pooled_aer_uses_sums_of_numerators_and_denominators_not_a_mean():
    # Episode 1: aer 1.0 on a thin denominator. Episode 2: aer 0.0 on a
    # denominator 99x larger. The simple mean of episode AER is 0.5; the
    # pooled AER, dominated by the large episode, is close to 0.0.
    rows = [
        _measured(episode_aer=1.0, w_real=1.0, denominator=1.0),
        _measured(episode_aer=0.0, w_real=0.0, denominator=99.0),
    ]
    report = pooled_aer_report(rows)
    assert report.mean_episode_aer == pytest.approx(0.5)
    assert report.pooled_aer_by_tier["wstar_fallback"] == pytest.approx(0.01)
    assert report.mean_episode_aer != pytest.approx(
        report.pooled_aer_by_tier["wstar_fallback"]
    )


def test_pooled_aer_never_mixes_denominator_tiers():
    rows = [
        _measured(episode_aer=1.0, w_real=10.0, denominator=10.0, tier="tier_a"),
        _measured(episode_aer=-1.0, w_real=-10.0, denominator=10.0, tier="tier_b"),
    ]
    report = pooled_aer_report(rows)
    assert report.pooled_aer_by_tier == {
        "tier_a": pytest.approx(1.0),
        "tier_b": pytest.approx(-1.0),
    }


def test_error_rows_are_counted_in_coverage_but_never_pooled():
    measured_rows = [
        _measured(episode_aer=0.2, w_real=2.0, denominator=10.0),
    ]
    baseline = pooled_aer_report(measured_rows)

    with_error = pooled_aer_report(
        measured_rows + [_errored(failure_class="invalid_measurement")]
    )
    # Adding a failed episode changes coverage and the error tally...
    assert with_error.episode_count == baseline.episode_count + 1
    assert with_error.measured_episode_count == baseline.measured_episode_count
    assert with_error.measurement_coverage < baseline.measurement_coverage
    assert with_error.errors_by_class == {"invalid_measurement": 1}
    # ...but it cannot silently disappear and inflate the pooled headline.
    assert (
        with_error.pooled_aer_by_tier
        == baseline.pooled_aer_by_tier
    )


def test_multiple_error_classes_are_each_tallied():
    rows = [
        _errored(failure_class="retryable_infrastructure"),
        _errored(failure_class="retryable_infrastructure"),
        _errored(failure_class="invalid_measurement"),
        _errored(failure_class=None),
    ]
    report = pooled_aer_report(rows)
    assert report.episode_count == 4
    assert report.measured_episode_count == 0
    assert report.measurement_coverage == 0.0
    assert report.pooled_aer_by_tier == {}
    assert report.errors_by_class == {
        "invalid_measurement": 1,
        "retryable_infrastructure": 2,
        "unclassified": 1,
    }


def test_positive_welfare_rate_is_a_diagnostic_not_the_headline():
    rows = [
        _measured(episode_aer=0.031, w_real=3.1, denominator=100.0),
        _measured(episode_aer=-0.5, w_real=-5.0, denominator=10.0),
    ]
    report = pooled_aer_report(rows)
    # One of two measured episodes is positive.
    assert report.positive_welfare_rate == pytest.approx(0.5)
    # The pooled AER is the sums, not the fraction of "wins".
    assert report.pooled_aer_by_tier["wstar_fallback"] == pytest.approx(
        (3.1 - 5.0) / (100.0 + 10.0)
    )
    assert report.positive_welfare_rate != pytest.approx(
        report.pooled_aer_by_tier["wstar_fallback"]
    )


def test_degenerate_pooled_denominator_reports_none_not_a_fabricated_zero():
    rows = [_measured(episode_aer=0.0, w_real=0.0, denominator=1e-12)]
    report = pooled_aer_report(rows)
    assert report.pooled_aer_by_tier["wstar_fallback"] is None


def test_untiered_measured_rows_pool_under_the_unknown_bucket():
    rows = [_measured(episode_aer=0.1, w_real=1.0, denominator=10.0, tier=None)]
    report = pooled_aer_report(rows)
    assert report.pooled_aer_by_tier == {"unknown": pytest.approx(0.1)}


def test_valid_measurement_row_without_numerator_or_denominator_raises():
    with pytest.raises(ValueError):
        pooled_aer_report([EpisodeSignalRow(valid_measurement=True)])


def test_empty_rows_report_no_coverage_and_no_pooled_tiers():
    report = pooled_aer_report([])
    assert report.episode_count == 0
    assert report.measurement_coverage is None
    assert report.pooled_aer_by_tier == {}
    assert report.positive_welfare_rate is None
    assert report.mean_episode_aer is None


def test_blank_completion_count_sums_across_episodes():
    rows = [
        _measured(
            episode_aer=0.1, w_real=1.0, denominator=10.0, blank_completion_count=1
        ),
        _errored(blank_completion_count=2),
    ]
    report = pooled_aer_report(rows)
    assert report.blank_completion_count == 3


def test_aggregate_eval_signals_entry_point_matches_the_pure_helper():
    """The evaluation post-processor entry point is a thin wrapper: it must
    compute exactly what the pure helper computes from the same rows."""
    rows = [
        _measured(episode_aer=1.0, w_real=1.0, denominator=1.0),
        _measured(episode_aer=0.0, w_real=0.0, denominator=99.0),
        _errored(failure_class="invalid_measurement"),
    ]
    assert aggregate_eval_signals(rows) == pooled_aer_report(rows).as_dict()


def test_row_from_mapping_reads_denominator_tier_alias():
    row = EpisodeSignalRow.from_mapping(
        {
            "valid_measurement": True,
            "episode_aer": 0.1,
            "w_real": 1.0,
            "denominator": 10.0,
            "denominator_tier": "wstar_fallback",
        }
    )
    assert row.tier == "wstar_fallback"
