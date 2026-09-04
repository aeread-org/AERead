from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread_families.datacenter_development_terms.public_integrated_v2_cases import (
    load_public_integrated_v2_cases,
)
from aeread_families.datacenter_development_terms.public_integrated_v3_cases import (
    MANIFEST_PATH,
    UNIQUE_ARRAY_SUFFIX,
    load_public_integrated_v3_cases,
    load_public_integrated_v3_manifest,
    public_integrated_v3_pack_sha256,
)
from aeread_families.datacenter_development_terms.runner import (
    datacenter_terms_output_schema,
)


def test_integrated_v3_changes_only_prompt_and_case_identity() -> None:
    base_by_slug = {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_integrated_v2_cases()
    }
    derived = load_public_integrated_v3_cases()

    assert len(derived) == 3
    assert len(public_integrated_v3_pack_sha256()) == 64
    for case in derived:
        slug = case.case_id.rsplit(".", 1)[-1]
        base = base_by_slug[slug]
        public = case.payload["public_case"]
        base_public = base.payload["public_case"]
        assert case.content_sha256 == case_content_sha256(case)
        assert case.world_seed == base.world_seed
        assert public["prompt"] == base_public["prompt"] + UNIQUE_ARRAY_SUFFIX
        assert public["observations"] == base_public["observations"]
        assert public["authority"] == base_public["authority"]
        assert case.payload["response_vocabulary"] == (
            base.payload["response_vocabulary"]
        )
        assert case.payload["oracle"] == base.payload["oracle"]


def test_integrated_v3_schema_can_enforce_every_array_as_unique() -> None:
    for case in load_public_integrated_v3_cases():
        schema = datacenter_terms_output_schema(case, unique_array_items=True)
        for field in (
            "actions",
            "claims",
            "evidence_ids",
            "external_actions_attempted",
        ):
            assert schema["properties"][field]["uniqueItems"] is True


def test_integrated_v3_manifest_rejects_schema_contract_drift(
    tmp_path: Path,
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest["required_harness_schema_constraint"] = "none"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="derivation manifest differs"):
        load_public_integrated_v3_manifest(path)
