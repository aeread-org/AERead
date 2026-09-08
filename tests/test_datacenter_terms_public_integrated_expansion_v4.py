from __future__ import annotations

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread_families.datacenter_development_terms.public_integrated_expansion_v3_cases import (
    load_public_integrated_expansion_v3_cases,
)
from aeread_families.datacenter_development_terms.public_integrated_expansion_v4_cases import (
    CURRENCY_BASE_UNIT_FIELDS,
    UNIT_INSTRUCTION,
    load_public_integrated_expansion_v4_cases,
    load_public_integrated_expansion_v4_manifest,
    public_integrated_expansion_v4_pack_sha256,
)


def _by_slug(cases):
    return {case.case_id.rsplit(".", 1)[-1]: case for case in cases}


def test_expansion_v4_freezes_explicit_currency_unit_contract() -> None:
    manifest = load_public_integrated_expansion_v4_manifest()
    cases = load_public_integrated_expansion_v4_cases()

    assert manifest["case_count"] == len(cases) == 3
    assert len(public_integrated_expansion_v4_pack_sha256()) == 64
    assert manifest["unit_instruction"] == UNIT_INSTRUCTION
    assert manifest["currency_base_unit_fields"] == {
        slug: list(fields) for slug, fields in CURRENCY_BASE_UNIT_FIELDS.items()
    }
    assert all(case_content_sha256(case) == case.content_sha256 for case in cases)
    for case in cases:
        slug = case.case_id.rsplit(".", 1)[-1]
        assert case.payload["public_case"]["prompt"].endswith(UNIT_INSTRUCTION)
        assert set(CURRENCY_BASE_UNIT_FIELDS[slug]) <= set(
            case.payload["oracle"]["gold"]["amounts"]
        )


def test_expansion_v4_preserves_v3_except_prompt_and_identity() -> None:
    bases = _by_slug(load_public_integrated_expansion_v3_cases())
    corrected = _by_slug(load_public_integrated_expansion_v4_cases())

    for slug, case in corrected.items():
        base = bases[slug]
        public = case.payload["public_case"]
        base_public = base.payload["public_case"]
        assert public["prompt"] == f"{base_public['prompt']}\n\n{UNIT_INSTRUCTION}"
        assert public["authority"] == base_public["authority"]
        assert public["independence_cluster_id"] == base_public[
            "independence_cluster_id"
        ]
        assert public["observations"] == base_public["observations"]
        assert case.payload["response_vocabulary"] == base.payload[
            "response_vocabulary"
        ]
        assert case.payload["oracle"] == base.payload["oracle"]
        assert case.world_seed == base.world_seed

    tydal = corrected["tydal-open-book-epc-governance-and-risk"]
    e05 = next(
        item
        for item in tydal.payload["public_case"]["observations"]
        if item["evidence_id"] == "e05"
    )
    assert "22nd" in e05["content"]
