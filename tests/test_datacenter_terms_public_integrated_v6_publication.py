from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_integrated_v6_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)


def test_integrated_v6_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_integrated_v6"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_integrated_v6_publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert len(manifest["source_receipt_sha256s"]) == 6
    assert len(manifest["source_result_sha256s"]) == 6
    assert all(value is False for value in manifest["sanitization"].values())

    summary = json.loads((publication / "reports/summary.json").read_text())
    assert summary["completed_cells"] == 4
    assert summary["operational_failure_cells"] == 2
    assert summary["reportable_pair_count"] == 1
    assert summary["reported_cost_usd"] == pytest.approx(0.003203442)
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["operational_missingness_finding"] == {
        "model_id": "mistral32_deepinfra",
        "provider": "DeepInfra",
        "observed_condition": "rate_limit",
        "affected_cells": 2,
        "model_output_available": False,
        "reported_usage_available": False,
    }
    assert summary["case_answerability_invalidation"] == {
        "case_slug": "tydal-open-book-epc-governance-and-risk",
        "oracle_field": "amounts.invoice_payment_day",
        "oracle_value": 22.0,
        "visible_observation_status": "omitted",
        "raw_model_value": 7.0,
        "disposition": "do_not_attribute_amount_error_or_interpret_case_score",
    }

    with (publication / "tables/cell_results.csv").open(newline="") as handle:
        cells = list(csv.DictReader(handle))
    assert len(cells) == 6
    mistral = [row for row in cells if row["model_id"] == "mistral32_deepinfra"]
    qwen = [row for row in cells if row["model_id"] == "qwen3_235b_google"]
    assert len([row for row in mistral if row["status"] == "completed"]) == 1
    failed_mistral = [row for row in mistral if row["status"] != "completed"]
    assert len(failed_mistral) == 2
    assert all(row["failure_condition"] == "rate_limit" for row in failed_mistral)
    assert all(row["inclusion_status"] == "excluded" for row in failed_mistral)
    assert all(row["route_verified"] == "True" for row in qwen)
    assert all(row["replay_verified"] == "True" for row in qwen)

    with (publication / "tables/paired_contrasts.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == 3
    reportable = [row for row in pairs if row["pair_reportable"] == "True"]
    missing = [row for row in pairs if row["pair_reportable"] == "False"]
    assert len(reportable) == 1
    assert reportable[0]["case_slug"] == "helios-phased-capacity-revenue-and-draws"
    assert float(reportable[0]["qwen_minus_mistral"]) == pytest.approx(
        0.033333333333333215
    )
    assert len(missing) == 2
    assert all(row["qwen_minus_mistral"] == "" for row in missing)

    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    completed = [row for row in trajectories if row["status"] == "completed"]
    assert len(completed) == 4
    for row in completed:
        for field in (
            "actions",
            "claims",
            "evidence_ids",
            "external_actions_attempted",
        ):
            values = row["parsed_output"][field]
            assert len(values) == len(set(values))

    payload = b"".join(
        path.read_bytes() for path in publication.rglob("*") if path.is_file()
    ).decode("utf-8").lower()
    assert all(token not in payload for token in PROHIBITED_PUBLIC_TEXT)


def test_integrated_v6_publication_is_idempotent() -> None:
    assert publish() == publish()
