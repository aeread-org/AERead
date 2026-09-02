from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from aeread.shared_runner import (
    CAMPAIGN_GATE_SEQUENCE,
    CampaignGateError,
    CampaignGateRecord,
    CampaignInvalidationRecord,
    QCCoverage,
    QCEvidenceRef,
    append_campaign_gate,
    append_campaign_invalidation,
    campaign_active_gate_records,
    campaign_gate_artifact_type,
    campaign_gate_record_sha256,
    campaign_history_record_from_dict,
    campaign_history_record_to_dict,
    campaign_promotion_decision,
)


def _gate(
    evidence_root: Path,
    gate_id: str,
    *,
    attempt_index: int = 1,
    status: str = "passed",
) -> CampaignGateRecord:
    coverage_item = f"{gate_id}_unit"
    relative_path = Path("evidence") / gate_id / f"attempt_{attempt_index}.json"
    artifact_path = evidence_root / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_bytes = f"{gate_id}:{attempt_index}:{status}\n".encode()
    artifact_path.write_bytes(artifact_bytes)
    return CampaignGateRecord(
        campaign_id="housing_harness_campaign_001",
        family_id="housing_v1",
        family_version="1.0.0",
        profile_id="housing_population_profile",
        gate_id=gate_id,
        attempt_index=attempt_index,
        status=status,
        evidence_refs=(
            QCEvidenceRef(
                artifact_type=campaign_gate_artifact_type(gate_id, status),
                path=str(relative_path),
                sha256=hashlib.sha256(artifact_bytes).hexdigest(),
                family_id="housing_v1",
                family_version="1.0.0",
                profile_id="housing_population_profile",
                coverage=(
                    QCCoverage(
                        coverage_id=gate_id,
                        required_ids=(coverage_item,),
                        observed_ids=(
                            (coverage_item,) if status == "passed" else ()
                        ),
                    ),
                ),
            ),
        ),
        failure_reasons=() if status == "passed" else ("declared check failed",),
    )


def _invalidation(
    evidence_root: Path,
    *,
    index: int = 1,
    from_gate_id: str = "profile_admission",
    changed_controls: tuple[str, ...] = ("retry_policy",),
) -> CampaignInvalidationRecord:
    invalidation_id = f"invalidation_{index}"
    relative_path = Path("evidence") / "invalidations" / f"{index}.json"
    artifact_path = evidence_root / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_bytes = f"invalidation:{index}\n".encode()
    artifact_path.write_bytes(artifact_bytes)
    return CampaignInvalidationRecord(
        campaign_id="housing_harness_campaign_001",
        family_id="housing_v1",
        family_version="1.0.0",
        profile_id="housing_population_profile",
        invalidation_index=index,
        from_gate_id=from_gate_id,
        changed_controls=changed_controls,
        reason="The retry policy changed after the trajectory probe.",
        evidence_refs=(
            QCEvidenceRef(
                artifact_type="campaign_invalidation",
                path=str(relative_path),
                sha256=hashlib.sha256(artifact_bytes).hexdigest(),
                family_id="housing_v1",
                family_version="1.0.0",
                profile_id="housing_population_profile",
                coverage=(
                    QCCoverage(
                        coverage_id="invalidation",
                        required_ids=(invalidation_id,),
                        observed_ids=(invalidation_id,),
                    ),
                ),
            ),
        ),
    )


def test_campaign_gates_require_every_predecessor_in_order(tmp_path: Path) -> None:
    records: tuple[CampaignGateRecord, ...] = ()
    blocked = campaign_promotion_decision(
        "housing_harness_campaign_001",
        "full_trajectory",
        records,
        evidence_root=tmp_path,
    )
    assert blocked.eligible is False
    assert blocked.blockers == (
        "design_contract:missing",
        "provider_free_validation:missing",
        "profile_admission:missing",
    )

    for gate_id in CAMPAIGN_GATE_SEQUENCE:
        record = _gate(tmp_path, gate_id)
        records = append_campaign_gate(
            records, record, evidence_root=tmp_path
        )
        assert campaign_gate_record_sha256(record) == campaign_gate_record_sha256(
            record
        )
    assert len(records) == len(CAMPAIGN_GATE_SEQUENCE)


def test_failed_gate_can_retry_but_blocks_downstream_work(tmp_path: Path) -> None:
    records = append_campaign_gate(
        (),
        _gate(tmp_path, "design_contract", status="failed"),
        evidence_root=tmp_path,
    )
    blocked = campaign_promotion_decision(
        "housing_harness_campaign_001",
        "provider_free_validation",
        records,
        evidence_root=tmp_path,
    )
    assert blocked.eligible is False
    assert blocked.blockers == ("design_contract:failed",)

    with pytest.raises(CampaignGateError, match="blocked"):
        append_campaign_gate(
            records,
            _gate(tmp_path, "provider_free_validation"),
            evidence_root=tmp_path,
        )

    retry = campaign_promotion_decision(
        "housing_harness_campaign_001",
        "design_contract",
        records,
        evidence_root=tmp_path,
    )
    assert retry.eligible is True
    assert retry.next_attempt_index == 2
    records = append_campaign_gate(
        records,
        _gate(tmp_path, "design_contract", attempt_index=2),
        evidence_root=tmp_path,
    )
    records = append_campaign_gate(
        records,
        _gate(tmp_path, "provider_free_validation"),
        evidence_root=tmp_path,
    )
    assert records[-1].gate_id == "provider_free_validation"


def test_campaign_gate_record_requires_typed_content_bound_evidence() -> None:
    with pytest.raises(CampaignGateError, match="evidence_refs"):
        CampaignGateRecord(
            campaign_id="campaign_001",
            family_id="housing_v1",
            family_version="1.0.0",
            profile_id="profile_001",
            gate_id="design_contract",
            attempt_index=1,
            status="passed",
            evidence_refs=(),
        )

    with pytest.raises(CampaignGateError, match="typed QCEvidenceRef"):
        CampaignGateRecord(
            campaign_id="campaign_001",
            family_id="housing_v1",
            family_version="1.0.0",
            profile_id="profile_001",
            gate_id="design_contract",
            attempt_index=1,
            status="passed",
            evidence_refs=("bare/path.json",),  # type: ignore[arg-type]
        )


def test_campaign_append_rejects_wrong_type_missing_file_and_digest_drift(
    tmp_path: Path,
) -> None:
    coverage = (
        QCCoverage(
            coverage_id="design_contract",
            required_ids=("design_contract_unit",),
            observed_ids=("design_contract_unit",),
        ),
    )
    common = {
        "campaign_id": "housing_harness_campaign_001",
        "family_id": "housing_v1",
        "family_version": "1.0.0",
        "profile_id": "housing_population_profile",
        "gate_id": "design_contract",
        "attempt_index": 1,
        "status": "passed",
    }
    with pytest.raises(CampaignGateError, match="artifact_type"):
        CampaignGateRecord(
            **common,
            evidence_refs=(
                QCEvidenceRef(
                    artifact_type="unrelated_report",
                    path="evidence/design.json",
                    sha256="0" * 64,
                    family_id="housing_v1",
                    family_version="1.0.0",
                    profile_id="housing_population_profile",
                    coverage=coverage,
                ),
            ),
        )

    missing = CampaignGateRecord(
        **common,
        evidence_refs=(
            QCEvidenceRef(
                artifact_type=campaign_gate_artifact_type(
                    "design_contract", "passed"
                ),
                path="evidence/design.json",
                sha256="0" * 64,
                family_id="housing_v1",
                family_version="1.0.0",
                profile_id="housing_population_profile",
                coverage=coverage,
            ),
        ),
    )
    with pytest.raises(CampaignGateError, match="does not resolve"):
        append_campaign_gate((), missing, evidence_root=tmp_path)

    artifact_path = tmp_path / "evidence" / "design.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("changed bytes\n", encoding="utf-8")
    with pytest.raises(CampaignGateError, match="digest mismatch"):
        append_campaign_gate((), missing, evidence_root=tmp_path)


def test_retry_policy_invalidation_reopens_profile_and_downstream_attempts(
    tmp_path: Path,
) -> None:
    records = ()
    for gate_id in CAMPAIGN_GATE_SEQUENCE[:4]:
        records = append_campaign_gate(
            records,
            _gate(tmp_path, gate_id),
            evidence_root=tmp_path,
        )

    with pytest.raises(CampaignGateError, match="append an invalidation"):
        campaign_promotion_decision(
            "housing_harness_campaign_001",
            "profile_admission",
            records,
            evidence_root=tmp_path,
        )

    records = append_campaign_invalidation(
        records,
        _invalidation(tmp_path),
        evidence_root=tmp_path,
    )
    active = campaign_active_gate_records(
        "housing_harness_campaign_001", records, evidence_root=tmp_path
    )
    assert [record.gate_id for record in active] == [
        "design_contract",
        "provider_free_validation",
    ]
    profile = campaign_promotion_decision(
        "housing_harness_campaign_001",
        "profile_admission",
        records,
        evidence_root=tmp_path,
    )
    assert profile.eligible is True
    assert profile.next_attempt_index == 2

    records = append_campaign_gate(
        records,
        _gate(tmp_path, "profile_admission", attempt_index=2),
        evidence_root=tmp_path,
    )
    trajectory = campaign_promotion_decision(
        "housing_harness_campaign_001",
        "full_trajectory",
        records,
        evidence_root=tmp_path,
    )
    assert trajectory.eligible is True
    assert trajectory.next_attempt_index == 2
    assert records[2].gate_id == "profile_admission"
    assert isinstance(records[4], CampaignInvalidationRecord)


def test_retry_policy_change_has_a_fixed_invalidation_boundary(tmp_path: Path) -> None:
    with pytest.raises(CampaignGateError, match="profile_admission"):
        _invalidation(tmp_path, from_gate_id="full_trajectory")


def test_campaign_history_round_trips_typed_gate_and_invalidation_records(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path, "design_contract")
    invalidation = _invalidation(
        tmp_path,
        from_gate_id="design_contract",
        changed_controls=("design_contract",),
    )
    assert campaign_history_record_from_dict(
        campaign_history_record_to_dict(gate)
    ) == gate
    assert campaign_history_record_from_dict(
        campaign_history_record_to_dict(invalidation)
    ) == invalidation
