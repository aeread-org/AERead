"""Derive the integrated candidate-screen case from the frozen public pack."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, DataCenterTermsPlugin
from .public_cases import PACK_ID as BASE_PACK_ID
from .public_cases import load_public_cases, public_pack_sha256


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "public_candidate_screen_v1"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
PACK_ID = "datacenter_development_terms_public_candidate_screen_v1"
CASE_SLUG = "linked-land-power-construction-underwriting"
DERIVED_SPLIT = "public_v1c"
CANDIDATE_SCREEN_SUFFIX = (
    " Before filling the actions and claims arrays, evaluate each allowed label "
    "independently against all relevant evidence. Include a label only when every "
    "controlling clause is consistent with it. If any controlling clause "
    "contradicts the label, omit it. Do not include rejected labels."
)
_SANITIZATION_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def load_public_candidate_screen_manifest(
    path: Path | str = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "benchmark_id": FAMILY_ID,
        "version": FAMILY_VERSION,
        "pack_id": PACK_ID,
        "base_pack_id": BASE_PACK_ID,
        "base_pack_sha256": public_pack_sha256(),
        "case_count": 1,
        "case_slug": CASE_SLUG,
        "independent_sampling_unit": "public_filing_cluster",
        "independence_cluster_count": 1,
        "transformation_id": "append_cross_clause_candidate_screen_sentence_v1",
        "derived_split": DERIVED_SPLIT,
        "prompt_suffix": CANDIDATE_SCREEN_SUFFIX,
        "preserved_fields": [
            "title",
            "task_family_id",
            "independence_cluster_id",
            "tier",
            "cutoff",
            "authority",
            "observations",
            "response_vocabulary",
            "oracle",
            "world_seed",
        ],
        "inference_status": "exploratory_single_cluster_prompt_intervention",
        "authority_modes_exercised": ["report"],
    }
    if not isinstance(manifest, dict) or manifest != required:
        raise ValueError("public candidate-screen derivation manifest differs")
    text = manifest_path.read_text(encoding="utf-8")
    for label, pattern in _SANITIZATION_PATTERNS.items():
        if pattern.search(text):
            raise ValueError(f"manifest.json: sanitization violation: {label}")
    return manifest


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def load_public_candidate_screen_case(
    *, manifest_path: Path | str = MANIFEST_PATH
) -> CaseManifest:
    load_public_candidate_screen_manifest(manifest_path)
    base = load_public_cases(case_slugs=(CASE_SLUG,))[0]
    base_public = _plain(base.payload["public_case"])
    base_oracle = _plain(base.payload["oracle"])
    response_vocabulary = _plain(base.payload["response_vocabulary"])
    case_id = f"{FAMILY_ID}.{DERIVED_SPLIT}.{CASE_SLUG}"
    public_case = {
        **base_public,
        "case_id": case_id,
        "prompt": base_public["prompt"] + CANDIDATE_SCREEN_SUFFIX,
    }
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": DERIVED_SPLIT,
        "world_seed": base.world_seed,
        "seats": [{"id": "analyst", "role": "analyst"}],
        "episode": {
            "max_logical_actions": 1,
            "termination": ["submitted", "invalid_submission"],
        },
        "visibility_policy": (
            "datacenter_terms_public_v1c_observation_private_oracle_v1"
        ),
        "payload": {
            "public_case": public_case,
            "response_vocabulary": response_vocabulary,
            "oracle": base_oracle,
        },
        "provenance": {
            "generator_id": "public_sec_filing_candidate_screen_derivation_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    draft = CaseManifest.from_dict(raw)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError("unstable public candidate-screen content hash")
    family_case = DataCenterTermsPlugin().validate_payload(case.payload)
    derived_public = family_case["public_case"]
    for field in (
        "title",
        "task_family_id",
        "independence_cluster_id",
        "tier",
        "cutoff",
        "authority",
        "observations",
    ):
        if _plain(derived_public[field]) != _plain(base_public[field]):
            raise ValueError(f"candidate-screen derived public field {field} differs")
    if _plain(family_case["oracle"]) != base_oracle:
        raise ValueError("candidate-screen derived oracle differs")
    if _plain(family_case["response_vocabulary"]) != response_vocabulary:
        raise ValueError("candidate-screen derived response vocabulary differs")
    return case


def public_candidate_screen_pack_sha256() -> str:
    manifest = load_public_candidate_screen_manifest()
    digest = hashlib.sha256()
    digest.update(MANIFEST_PATH.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(MANIFEST_PATH.read_bytes())
    digest.update(b"\0base_pack_sha256\0")
    digest.update(manifest["base_pack_sha256"].encode("ascii"))
    return digest.hexdigest()


__all__ = [
    "CANDIDATE_SCREEN_SUFFIX",
    "CASE_SLUG",
    "DERIVED_SPLIT",
    "MANIFEST_PATH",
    "PACK_ID",
    "PACK_ROOT",
    "load_public_candidate_screen_case",
    "load_public_candidate_screen_manifest",
    "public_candidate_screen_pack_sha256",
]
