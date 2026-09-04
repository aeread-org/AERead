from __future__ import annotations

import csv
import json
from pathlib import Path

from aeread_families.datacenter_development_terms.public_integrated_v12_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_integrated_v12_publication_is_sanitized_and_sealed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "publication"
    manifest = publish(publication_root=root)

    assert manifest["campaign_id"] == (
        "datacenter_development_terms_public_integrated_v12"
    )
    assert manifest["source_summary_sha256"] == (
        "d689dee969e9bcb45ce9767866fad615fa5f6054360d6cc523d9e5a59826b349"
    )
    assert manifest["source_design_sha256"] == (
        "6bb249462ee8e182c1741be57f174b35d89da3d2332a301471969508955c9162"
    )
    assert manifest["sanitization"]["failure_messages_included"] is False
    assert len(manifest["source_receipt_sha256s"]) == 6

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in PROHIBITED_PUBLIC_TEXT)
        assert "user_2f0wmzynEcRZmgX9vlIERzZasQO" not in text
        assert "upstream_provider_shared_pool" not in text


def test_integrated_v12_publication_preserves_typed_missingness(
    tmp_path: Path,
) -> None:
    root = tmp_path / "publication"
    publish(publication_root=root)
    summary = json.loads((root / "reports/summary.json").read_text())
    trajectories = _jsonl(root / "trajectories/sanitized.jsonl")
    with (root / "tables/paired_contrasts.csv").open(newline="") as stream:
        pairs = list(csv.DictReader(stream))

    assert summary["completed_cells"] == 3
    assert summary["operational_failure_cells"] == 3
    assert summary["reportable_pair_count"] == 0
    assert summary["reported_cost_usd"] == 0.0029699208000000003
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["gptoss_indicator_map_qualification"] == {
        "model_id": "gptoss120b_coreweave",
        "provider": "CoreWeave",
        "schema_mode": "complete_indicator_maps_v1",
        "max_output_tokens": 1200,
        "planned_cells": 3,
        "completed_cells": 0,
        "failure_conditions": {"provider_contract": 2, "rate_limit": 1},
        "model_output_available": False,
        "reported_usage_available": False,
        "qualified": False,
        "disposition": "separate_predeclared_higher_cap_qualification_required",
    }
    assert all(pair["pair_reportable"] == "False" for pair in pairs)
    assert all(pair["qwen_minus_gptoss"] == "" for pair in pairs)
    assert sum(row["status"] == "completed" for row in trajectories) == 3
    assert all(
        row["route_verified"]
        for row in trajectories
        if row["status"] == "completed"
    )
    failures = [row for row in trajectories if row["status"] != "completed"]
    assert len(failures) == 3
    assert {row["failure"]["failure_condition"] for row in failures} == {
        "provider_contract",
        "rate_limit",
    }
    assert all("message" not in row["failure"] for row in failures)
