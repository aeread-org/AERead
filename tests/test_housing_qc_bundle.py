from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.housing.qc_bundle import execute_bundle, load_contract


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "housing_qc_goldens_v1.json"
)


def test_housing_qc_contract_is_provider_free_and_complete() -> None:
    contract = load_contract(CONTRACT_PATH)

    assert contract["external_provider_calls_allowed"] is False
    assert [row["scenario_id"] for row in contract["scenarios"]] == [
        "efficient_outcome",
        "valid_poor_outcome",
        "invalid_unauthorized_action",
        "malformed_output",
        "provider_failure",
        "zero_upper_bound",
    ]


def test_housing_qc_bundle_publishes_distinct_digest_bound_receipts(
    tmp_path: Path,
) -> None:
    publish_root = tmp_path / "published"
    report = asyncio.run(
        execute_bundle(
            contract_path=CONTRACT_PATH,
            run_root=tmp_path / "runs",
            publish_root=publish_root,
        )
    )
    by_id = {row["scenario_id"]: row for row in report["scenarios"]}

    assert report["status"] == "passed"
    assert report["external_provider_calls"] == 0
    assert report["provider_cost_usd"] == 0.0
    assert by_id["efficient_outcome"]["within_case_score"] == 1.0
    assert by_id["valid_poor_outcome"]["within_case_score"] == 0.0
    assert by_id["valid_poor_outcome"]["parse_failure_count"] == 0
    assert by_id["valid_poor_outcome"]["legality_failure_count"] == 0
    assert by_id["invalid_unauthorized_action"]["within_case_score"] == 0.0
    assert by_id["invalid_unauthorized_action"]["parse_failure_count"] == 0
    assert by_id["invalid_unauthorized_action"]["legality_failure_count"] > 0
    assert by_id["malformed_output"]["within_case_score"] == 0.0
    assert by_id["malformed_output"]["parse_failure_count"] > 0
    assert by_id["provider_failure"]["receipt_status"] == "invalid_measurement"
    assert by_id["provider_failure"]["inclusion_status"] == "excluded"
    assert by_id["provider_failure"]["failure"]["condition"] == "provider_contract"
    assert by_id["zero_upper_bound"]["oracle_upper_bound"] == 0.0
    assert by_id["zero_upper_bound"]["within_case_score"] is None
    assert all(
        row["replay_verified"]
        for row in report["scenarios"]
        if row["receipt_status"] == "ok"
    )

    core = {key: value for key, value in report.items() if key != "artifact_sha256"}
    assert report["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    for ref in report["receipts"]:
        receipt_path = publish_root / ref["path"]
        assert receipt_path.is_file()
        assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == ref[
            "file_sha256"
        ]
    written = json.loads((publish_root / "reports" / "qc_bundle.json").read_bytes())
    assert written == report
    assert "raw_response" not in json.dumps(written)


def test_checked_in_housing_qc_bundle_is_digest_bound() -> None:
    root = CONTRACT_PATH.parents[1] / "evidence" / "housing_qc_goldens_v1"
    report = json.loads((root / "reports" / "qc_bundle.json").read_bytes())
    core = {key: value for key, value in report.items() if key != "artifact_sha256"}

    assert report["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert report["status"] == "passed"
    assert report["scenario_count"] == 6
    assert report["external_provider_calls"] == 0
    for ref in report["receipts"]:
        receipt_path = root / ref["path"]
        assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == ref[
            "file_sha256"
        ]
    assert "raw_response" not in json.dumps(report)
