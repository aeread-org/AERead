"""AERead's pooled-AER aggregation, shared by every reporting surface.

``exchange_v1_submit.py`` computes AERead's official headline inline: for
each denominator tier, pool welfare numerator and denominator across cases
and divide the sums, never the per-case ratios. This module extracts that
same formula into one dependency-free, independently unit-tested helper so
an rLLM evaluation post-processor (:mod:`aeread.integrations.rllm_eval`) can
compute the identical number from per-episode signals without re-deriving
the arithmetic. It has no rLLM import and performs no I/O.

Unifying this module with ``exchange_v1_submit.py``'s inline pooling is an
upstream follow-up: that file is exported from the private canonical repo
and is out of scope here (see ``integrations/rllm/READINESS_PROPOSAL.md``,
Workstream 5).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

MIN_DENOMINATOR = 1e-9
UNKNOWN_TIER = "unknown"
UNCLASSIFIED_FAILURE = "unclassified"


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True)
class EpisodeSignalRow:
    """One episode's aggregation-relevant signals.

    ``valid_measurement`` mirrors the evaluator's ``Signal`` of the same
    name: only rows where it is true contribute a numerator and denominator
    to the pooled AER. Every row -- valid or not -- counts once toward
    ``episode_count`` and measurement coverage, so an error episode cannot
    improve the headline by simply not being counted.
    """

    valid_measurement: bool
    episode_aer: float | None = None
    w_real: float | None = None
    denominator: float | None = None
    tier: str | None = None
    failure_class: str | None = None
    blank_completion_count: float = 0.0

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> EpisodeSignalRow:
        """Build a row from a plain per-episode signal/metadata dict.

        Reads AERead's own field names (``episode_aer`` / ``w_real`` /
        ``denominator`` / ``valid_measurement``) so it can consume the
        evaluator's ``EvalOutput`` signals flattened to name -> value, plus
        ``tier`` (or ``denominator_tier``) and ``failure_class`` carried
        alongside them, without a second row schema.
        """
        tier = row.get("tier", row.get("denominator_tier"))
        failure_class = row.get("failure_class")
        return cls(
            valid_measurement=bool(row.get("valid_measurement")),
            episode_aer=_optional_float(row.get("episode_aer")),
            w_real=_optional_float(row.get("w_real")),
            denominator=_optional_float(row.get("denominator")),
            tier=str(tier) if tier is not None else None,
            failure_class=str(failure_class) if failure_class is not None else None,
            blank_completion_count=float(row.get("blank_completion_count") or 0.0),
        )


@dataclass(frozen=True)
class PooledAerReport:
    """AERead's official aggregate: sums of numerators and denominators,
    never an average of per-episode ratios."""

    episode_count: int
    measured_episode_count: int
    measurement_coverage: float | None
    pooled_aer_by_tier: dict[str, float | None]
    mean_episode_aer: float | None
    positive_welfare_rate: float | None
    errors_by_class: dict[str, int]
    blank_completion_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode_count": self.episode_count,
            "measured_episode_count": self.measured_episode_count,
            "measurement_coverage": self.measurement_coverage,
            "pooled_aer_by_tier": dict(self.pooled_aer_by_tier),
            "mean_episode_aer": self.mean_episode_aer,
            "positive_welfare_rate": self.positive_welfare_rate,
            "errors_by_class": dict(self.errors_by_class),
            "blank_completion_count": self.blank_completion_count,
        }


def pooled_aer_report(
    rows: Iterable[EpisodeSignalRow | Mapping[str, Any]],
) -> PooledAerReport:
    """Compute AERead's pooled-by-tier AER report from per-episode rows.

    Pooled AER per tier is ``sum(w_real) / sum(denominator)`` over that
    tier's measured rows -- never a mean of the per-episode ratios -- so one
    large-denominator episode cannot be swamped by many small ones, and a
    thin episode cannot dominate a thick one. This is the same formula
    ``exchange_v1_submit.py`` computes inline for its submission report.

    Every row, valid or not, counts once toward ``episode_count``. A row
    that is not a valid measurement never contributes a numerator or
    denominator; it is tallied by its ``failure_class`` in ``errors_by_class``
    and lowers ``measurement_coverage``, never the pooled AER.
    """
    materialized = [
        row if isinstance(row, EpisodeSignalRow) else EpisodeSignalRow.from_mapping(row)
        for row in rows
    ]
    episode_count = len(materialized)
    measured = [row for row in materialized if row.valid_measurement]
    measured_episode_count = len(measured)

    numerators: dict[str, float] = {}
    denominators: dict[str, float] = {}
    aers: list[float] = []
    positive = 0
    for row in measured:
        if row.w_real is None or row.denominator is None:
            raise ValueError(
                "a row marked valid_measurement=True must carry w_real and "
                "denominator"
            )
        tier = row.tier or UNKNOWN_TIER
        numerators[tier] = numerators.get(tier, 0.0) + row.w_real
        denominators[tier] = denominators.get(tier, 0.0) + row.denominator
        if row.episode_aer is not None:
            aers.append(row.episode_aer)
            if row.episode_aer > 0.0:
                positive += 1

    pooled_by_tier = {
        tier: (
            numerators[tier] / denominators[tier]
            if denominators[tier] > MIN_DENOMINATOR
            else None
        )
        for tier in sorted(numerators)
    }

    errors_by_class: Counter[str] = Counter()
    for row in materialized:
        if not row.valid_measurement:
            errors_by_class[row.failure_class or UNCLASSIFIED_FAILURE] += 1

    return PooledAerReport(
        episode_count=episode_count,
        measured_episode_count=measured_episode_count,
        measurement_coverage=(
            measured_episode_count / episode_count if episode_count else None
        ),
        pooled_aer_by_tier=pooled_by_tier,
        mean_episode_aer=(sum(aers) / len(aers)) if aers else None,
        positive_welfare_rate=(positive / len(aers)) if aers else None,
        errors_by_class=dict(sorted(errors_by_class.items())),
        blank_completion_count=int(
            sum(row.blank_completion_count for row in materialized)
        ),
    )


def aggregate_eval_signals(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluation post-processor entry point.

    Turns a list of per-episode signal dicts -- one flattened
    ``{signal.name: signal.value, ...}`` plus ``tier`` and ``failure_class``
    per completed or failed episode, the shape
    :mod:`aeread.integrations.rllm_eval`'s ``aeread_evaluator`` naturally
    produces -- into the same report :func:`pooled_aer_report` returns.

    This is AERead's official aggregate. It runs after an eval pass, never
    inside the training loop, and it is not itself a reward. rLLM's own
    ``Accuracy`` line remains a compatibility diagnostic
    (``positive_welfare_rate``) until rLLM supports a custom aggregate or
    headline-label hook; see ``integrations/rllm/READINESS_PROPOSAL.md``.
    """
    return pooled_aer_report(records).as_dict()


__all__ = [
    "EpisodeSignalRow",
    "PooledAerReport",
    "aggregate_eval_signals",
    "pooled_aer_report",
]
