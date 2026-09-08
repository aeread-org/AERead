from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_integrated_v5_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)


def test_integrated_v5_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_integrated_v5"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_integrated_v5_publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert len(manifest["source_receipt_sha256s"]) == 18
    assert len(manifest["source_result_sha256s"]) == 18
    assert all(value is False for value in manifest["sanitization"].values())

    summary = json.loads((publication / "reports/summary.json").read_text())
    assert summary["completed_cells"] == 18
    assert summary["operational_failure_cells"] == 0
    assert summary["reportable_pair_count"] == 9
    assert summary["reported_cost_usd"] == pytest.approx(0.0106847829)
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["model_case_group_count"] == 6
    assert summary["model_case_groups_with_exact_seed_repeats"] == 6
    assert summary["aggregate_qwen_minus_mistral_mean_score"] == pytest.approx(
        0.6252525252525252
    )

    with (publication / "tables/cell_results.csv").open(newline="") as handle:
        cells = list(csv.DictReader(handle))
    assert len(cells) == 18
    assert all(row["status"] == "completed" for row in cells)
    assert all(row["route_verified"] == "True" for row in cells)
    assert all(row["replay_verified"] == "True" for row in cells)

    with (publication / "tables/paired_contrasts.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == 9
    assert all(row["pair_reportable"] == "True" for row in pairs)
    assert [float(row["qwen_minus_mistral"]) for row in pairs] == pytest.approx(
        [
            0.909090909090909,
            0.909090909090909,
            0.909090909090909,
            -0.033333333333333215,
            -0.033333333333333215,
            -0.033333333333333215,
            1.0,
            1.0,
            1.0,
        ]
    )

    with (publication / "tables/output_stability.csv").open(newline="") as handle:
        stability = list(csv.DictReader(handle))
    assert len(stability) == 6
    assert all(row["seed_count"] == "3" for row in stability)
    assert all(row["unique_output_count"] == "1" for row in stability)
    assert all(row["exact_repeat_across_seeds"] == "True" for row in stability)

    payload = b"".join(
        path.read_bytes() for path in publication.rglob("*") if path.is_file()
    ).decode("utf-8").lower()
    assert all(token not in payload for token in PROHIBITED_PUBLIC_TEXT)


@pytest.mark.local_run("datacenter_development_terms_public_integrated_v5")
def test_integrated_v5_publication_is_idempotent() -> None:
    assert publish() == publish()
