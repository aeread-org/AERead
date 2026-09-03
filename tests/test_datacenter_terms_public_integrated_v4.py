from __future__ import annotations

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread_families.datacenter_development_terms.public_integrated_v2_cases import (
    load_public_integrated_v2_cases,
)
from aeread_families.datacenter_development_terms.public_integrated_v4_cases import (
    INDICATOR_MAP_SUFFIX,
    load_public_integrated_v4_cases,
    load_public_integrated_v4_manifest,
    public_integrated_v4_pack_sha256,
)


def test_integrated_v4_pack_is_three_independent_indicator_map_cases() -> None:
    manifest = load_public_integrated_v4_manifest()
    cases = load_public_integrated_v4_cases()

    assert manifest["case_count"] == len(cases) == 3
    assert manifest["independence_cluster_count"] == 3
    assert len({case.payload["public_case"]["independence_cluster_id"] for case in cases}) == 3
    assert public_integrated_v4_pack_sha256() == (
        "6bbf24c6d26be3451b366adc56e16a7d3761b9eb1e7cee71f9765d58c6bf64a0"
    )
    assert all(case_content_sha256(case) == case.content_sha256 for case in cases)


def test_integrated_v4_changes_only_identity_prompt_and_provenance() -> None:
    bases = {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_integrated_v2_cases()
    }
    for case in load_public_integrated_v4_cases():
        slug = case.case_id.rsplit(".", 1)[-1]
        base = bases[slug]
        public = case.payload["public_case"]
        base_public = base.payload["public_case"]
        assert public["prompt"] == base_public["prompt"] + INDICATOR_MAP_SUFFIX
        assert public["observations"] == base_public["observations"]
        assert public["authority"] == base_public["authority"]
        assert public["independence_cluster_id"] == base_public["independence_cluster_id"]
        assert case.payload["response_vocabulary"] == base.payload["response_vocabulary"]
        assert case.payload["oracle"] == base.payload["oracle"]
        assert case.world_seed == base.world_seed
