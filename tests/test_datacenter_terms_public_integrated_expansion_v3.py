from __future__ import annotations

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread_families.datacenter_development_terms.public_integrated_expansion_v2_cases import (
    load_public_integrated_expansion_v2_cases,
)
from aeread_families.datacenter_development_terms.public_integrated_expansion_v3_cases import (
    CORRECTED_EVIDENCE_ID,
    TYDAL_SLUG,
    load_public_integrated_expansion_v3_cases,
    load_public_integrated_expansion_v3_manifest,
    public_integrated_expansion_v3_pack_sha256,
)


def _by_slug(cases):
    return {case.case_id.rsplit(".", 1)[-1]: case for case in cases}


def test_expansion_v3_corrects_one_observation_and_audits_all_amount_keys() -> None:
    manifest = load_public_integrated_expansion_v3_manifest()
    cases = load_public_integrated_expansion_v3_cases()

    assert manifest["case_count"] == len(cases) == 3
    assert len(public_integrated_expansion_v3_pack_sha256()) == 64
    assert all(case_content_sha256(case) == case.content_sha256 for case in cases)
    for case in cases:
        slug = case.case_id.rsplit(".", 1)[-1]
        assert set(manifest["amount_evidence_map"][slug]) == set(
            case.payload["oracle"]["gold"]["amounts"]
        )


def test_expansion_v3_preserves_everything_except_tydal_e05_and_identity() -> None:
    bases = _by_slug(load_public_integrated_expansion_v2_cases())
    corrected = _by_slug(load_public_integrated_expansion_v3_cases())

    for slug, case in corrected.items():
        base = bases[slug]
        public = case.payload["public_case"]
        base_public = base.payload["public_case"]
        assert public["prompt"] == base_public["prompt"]
        assert public["authority"] == base_public["authority"]
        assert public["independence_cluster_id"] == base_public["independence_cluster_id"]
        assert case.payload["response_vocabulary"] == base.payload["response_vocabulary"]
        assert case.payload["oracle"] == base.payload["oracle"]
        assert case.world_seed == base.world_seed
        if slug != TYDAL_SLUG:
            assert public["observations"] == base_public["observations"]
            continue
        base_e05 = next(
            item for item in base_public["observations"]
            if item["evidence_id"] == CORRECTED_EVIDENCE_ID
        )
        corrected_e05 = next(
            item for item in public["observations"]
            if item["evidence_id"] == CORRECTED_EVIDENCE_ID
        )
        assert "22nd" not in base_e05["content"]
        assert "22nd" in corrected_e05["content"]
        assert "seven days" in corrected_e05["content"]
        assert case.payload["oracle"]["gold"]["amounts"]["invoice_payment_day"] == 22.0
