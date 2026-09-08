from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development_terms.environment import DataCenterTermsPlugin
from aeread_families.datacenter_development_terms.public_integrated_expansion_cases import (
    CASES_PATH,
    MANIFEST_PATH,
    SOURCE_CATALOG_PATH,
    load_public_integrated_expansion_authoring_records,
    load_public_integrated_expansion_cases,
    public_integrated_expansion_pack_sha256,
)
from aeread_families.datacenter_development_terms.runner import (
    datacenter_terms_indicator_output_schema,
)


def test_expansion_pack_has_three_new_independent_project_clusters() -> None:
    manifest, records, catalog = load_public_integrated_expansion_authoring_records()

    assert manifest["case_count"] == len(records) == 3
    assert manifest["independence_cluster_count"] == 3
    assert len({record["independence_cluster_id"] for record in records}) == 3
    assert len(catalog["sources"]) == 4
    assert catalog["original_artifacts_included"] is False
    assert catalog["public_reproducibility"] is True
    assert all(
        source["url"].startswith("https://www.sec.gov/Archives/edgar/data/")
        and source["upstream_sha256"] is None
        and source["original_included"] is False
        for source in catalog["sources"].values()
    )
    assert len(public_integrated_expansion_pack_sha256()) == 64


def test_expansion_cases_are_hash_pinned_and_hide_private_fields() -> None:
    plugin = DataCenterTermsPlugin()
    cases = load_public_integrated_expansion_cases()

    assert len(cases) == 3
    assert len({case.content_sha256 for case in cases}) == 3
    assert {case.world_seed for case in cases} == {552001, 552002, 552003}
    for case in cases:
        assert case.content_sha256 == case_content_sha256(case)
        family_case = plugin.validate_payload(case.payload)
        state = plugin.initial_state(family_case, run=None)
        observation = plugin.observe(
            family_case,
            state,
            "analyst",
            plugin.phases(family_case)[0],
        )
        encoded = canonical_json_bytes(observation).decode("utf-8")
        assert '"oracle"' not in encoded
        assert '"source_refs"' not in encoded
        assert '"failure_mechanisms"' not in encoded
        assert '"terminal_when"' not in encoded
        assert "sec.gov" not in encoded


def test_expansion_indicator_schemas_cover_all_candidates_without_gold() -> None:
    for case in load_public_integrated_expansion_cases():
        schema = datacenter_terms_indicator_output_schema(case)
        family_case = DataCenterTermsPlugin().validate_payload(case.payload)
        gold = family_case["oracle"]["gold"]

        assert set(schema["properties"]["states"]["properties"]) == set(gold["states"])
        assert set(schema["properties"]["amounts"]["properties"]) == set(gold["amounts"])
        assert set(schema["properties"]["actions"]["properties"]) == (
            set(gold["required_actions"]) | set(gold["forbidden_actions"])
        )
        assert set(schema["properties"]["claims"]["properties"]) == (
            set(gold["required_claims"]) | set(gold["forbidden_claims"])
        )


def test_expansion_pack_rejects_cross_cluster_source_refs(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    cases = tmp_path / "cases.jsonl"
    catalog = tmp_path / "source_catalog.json"
    manifest.write_bytes(MANIFEST_PATH.read_bytes())
    catalog.write_bytes(SOURCE_CATALOG_PATH.read_bytes())
    rows = [json.loads(line) for line in CASES_PATH.read_text().splitlines()]
    rows[0]["oracle"]["source_refs"].append("bitdeer_tydal_epc_exhibit")
    cases.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    with pytest.raises(ValueError, match="share the case cluster"):
        load_public_integrated_expansion_authoring_records(
            manifest_path=manifest,
            cases_path=cases,
            source_catalog_path=catalog,
        )


def test_expansion_pack_rejects_broken_arithmetic(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    cases = tmp_path / "cases.jsonl"
    catalog = tmp_path / "source_catalog.json"
    manifest.write_bytes(MANIFEST_PATH.read_bytes())
    catalog.write_bytes(SOURCE_CATALOG_PATH.read_bytes())
    rows = [json.loads(line) for line in CASES_PATH.read_text().splitlines()]
    rows[2]["oracle"]["arithmetic_checks"][0]["expected"] = 1.0
    cases.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    with pytest.raises(ValueError, match="does not reconcile"):
        load_public_integrated_expansion_authoring_records(
            manifest_path=manifest,
            cases_path=cases,
            source_catalog_path=catalog,
        )
