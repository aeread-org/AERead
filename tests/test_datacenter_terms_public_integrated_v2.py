from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development_terms.environment import (
    DataCenterTermsPlugin,
)
from aeread_families.datacenter_development_terms.public_integrated_cases import (
    load_public_integrated_cases,
)
from aeread_families.datacenter_development_terms.public_integrated_v2_cases import (
    CANDIDATE_SCREEN_SUFFIX,
    HORIZON_SLUG,
    MANIFEST_PATH,
    SERVICE_STATE,
    load_public_integrated_v2_cases,
    load_public_integrated_v2_manifest,
    public_integrated_v2_pack_sha256,
)


def test_integrated_v2_changes_only_declared_prompt_and_oracle_scope() -> None:
    base_by_slug = {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_integrated_cases()
    }
    corrected = load_public_integrated_v2_cases()

    assert len(corrected) == 3
    assert len(public_integrated_v2_pack_sha256()) == 64
    assert len(
        {
            case.payload["public_case"]["independence_cluster_id"]
            for case in corrected
        }
    ) == 3
    for case in corrected:
        slug = case.case_id.rsplit(".", 1)[-1]
        base = base_by_slug[slug]
        public = case.payload["public_case"]
        base_public = base.payload["public_case"]
        assert case.content_sha256 == case_content_sha256(case)
        assert case.world_seed == base.world_seed
        assert public["prompt"] == base_public["prompt"] + CANDIDATE_SCREEN_SUFFIX
        assert public["observations"] == base_public["observations"]
        assert public["authority"] == base_public["authority"]
        assert public["independence_cluster_id"] == (
            base_public["independence_cluster_id"]
        )
        assert SERVICE_STATE in case.payload["response_vocabulary"]["state_values"]
        expected_states = dict(base.payload["oracle"]["gold"]["states"])
        if slug == HORIZON_SLUG:
            expected_states["customer_contract_state"] = SERVICE_STATE
        assert case.payload["oracle"]["gold"]["states"] == expected_states


def test_integrated_v2_horizon_uses_service_agreement_state() -> None:
    horizon = load_public_integrated_v2_cases(case_slugs=(HORIZON_SLUG,))[0]

    assert horizon.payload["oracle"]["gold"]["states"][
        "customer_contract_state"
    ] == SERVICE_STATE
    observation = DataCenterTermsPlugin().observe(
        DataCenterTermsPlugin().validate_payload(horizon.payload),
        DataCenterTermsPlugin().initial_state(
            DataCenterTermsPlugin().validate_payload(horizon.payload), run=None
        ),
        "analyst",
        DataCenterTermsPlugin().phases(
            DataCenterTermsPlugin().validate_payload(horizon.payload)
        )[0],
    )
    encoded = canonical_json_bytes(observation).decode("utf-8")
    assert SERVICE_STATE in encoded
    assert '"oracle"' not in encoded
    assert '"source_refs"' not in encoded


def test_integrated_v2_manifest_rejects_untracked_correction(
    tmp_path: Path,
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest["oracle_correction"]["to"] = "executed_long_term_lease"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="derivation manifest differs"):
        load_public_integrated_v2_manifest(path)
