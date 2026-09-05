from __future__ import annotations

import pytest

from aeread.shared_runner import (
    BenchmarkQCStatus,
    QCCoverage,
    QCContractError,
    QCEvidenceRef,
    QCTrackStatus,
    evidence_coverage_complete,
)


def _evidence(*, observed: tuple[str, ...]) -> QCEvidenceRef:
    return QCEvidenceRef(
        artifact_type="housing_case_sweep",
        path="runs/housing/sweep_summary.json",
        sha256="a" * 64,
        family_id="housing_v1",
        family_version="1.0.0",
        profile_id="housing_normative_profile",
        coverage=(
            QCCoverage(
                coverage_id="task_distribution",
                required_ids=("case_1", "case_2"),
                observed_ids=observed,
            ),
        ),
    )


def test_development_pass_does_not_promote_a_partial_normative_profile() -> None:
    status = BenchmarkQCStatus(
        family_id="housing_v1",
        family_version="1.0.0",
        development=QCTrackStatus(
            scope_id="development_case_qualification",
            state="passed",
            rationale="The provider-free sweep passed.",
        ),
        normative=QCTrackStatus(
            scope_id="normative_housing_profile",
            state="partial",
            rationale="Confirmatory and live-model checks remain incomplete.",
        ),
    )

    assert status.development.state == "passed"
    assert status.normative.state == "partial"
    assert status.promotion_eligible is False
    assert status.to_dict()["promotion_eligible"] is False


def test_evidence_coverage_is_collective_and_cannot_exceed_required_units() -> None:
    first = _evidence(observed=("case_1",))
    second = QCEvidenceRef(
        artifact_type="housing_case_sweep_extension",
        path="runs/housing/sweep_extension.json",
        sha256="b" * 64,
        family_id="housing_v1",
        family_version="1.0.0",
        profile_id="housing_normative_profile",
        coverage=(
            QCCoverage(
                coverage_id="task_distribution",
                required_ids=("case_1", "case_2"),
                observed_ids=("case_2",),
            ),
        ),
    )

    assert evidence_coverage_complete((first,), "task_distribution") is False
    assert evidence_coverage_complete(
        (first, second), "task_distribution"
    ) is True

    with pytest.raises(QCContractError, match="outside required_ids"):
        QCCoverage(
            coverage_id="task_distribution",
            required_ids=("case_1",),
            observed_ids=("case_2",),
        )
