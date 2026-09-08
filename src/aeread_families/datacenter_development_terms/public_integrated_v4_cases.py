"""Derive typed indicator-map prompts from corrected integrated public cases."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, DataCenterTermsPlugin
from .public_integrated_v2_cases import PACK_ID as BASE_PACK_ID
from .public_integrated_v2_cases import (
    load_public_integrated_v2_cases,
    public_integrated_v2_pack_sha256,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "public_integrated_v4"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
PACK_ID = "datacenter_development_terms_public_integrated_v4"
DERIVED_SPLIT = "public_integrated_v4"
INDICATOR_MAP_SUFFIX = (
    " Encode actions, claims, and evidence_ids as complete objects mapping "
    "every candidate label to true or false exactly once, not as arrays. "
    "Encode external_actions_attempted as an object with the single boolean "
    "key any; set it false unless you actually attempted an external action."
)
_SANITIZATION_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def load_public_integrated_v4_manifest(
    path: Path | str = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "benchmark_id": FAMILY_ID,
        "version": FAMILY_VERSION,
        "pack_id": PACK_ID,
        "base_pack_id": BASE_PACK_ID,
        "base_pack_sha256": public_integrated_v2_pack_sha256(),
        "case_count": 3,
        "independent_sampling_unit": "public_filing_project_cluster",
        "independence_cluster_count": 3,
        "derived_split": DERIVED_SPLIT,
        "transformation_id": "append_complete_indicator_map_instruction_v1",
        "prompt_suffix": INDICATOR_MAP_SUFFIX,
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
        "required_harness_schema_constraint": (
            "complete_boolean_indicator_objects_for_candidate_fields"
        ),
        "inference_status": (
            "corrected_indicator_map_exploratory_three_project_cluster_diagnostic"
        ),
        "authority_modes_exercised": ["report"],
    }
    if not isinstance(manifest, dict) or manifest != required:
        raise ValueError("public integrated v4 derivation manifest differs")
    text = manifest_path.read_text(encoding="utf-8")
    for label, pattern in _SANITIZATION_PATTERNS.items():
        if pattern.search(text):
            raise ValueError(f"manifest.json: sanitization violation: {label}")
    return manifest


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _derived_case(base: CaseManifest) -> CaseManifest:
    slug = base.case_id.rsplit(".", 1)[-1]
    base_public = _plain(base.payload["public_case"])
    oracle = _plain(base.payload["oracle"])
    vocabulary = _plain(base.payload["response_vocabulary"])
    case_id = f"{FAMILY_ID}.{DERIVED_SPLIT}.{slug}"
    public_case = {
        **base_public,
        "case_id": case_id,
        "prompt": base_public["prompt"] + INDICATOR_MAP_SUFFIX,
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
            "datacenter_terms_public_integrated_v4_observation_private_oracle_v1"
        ),
        "payload": {
            "public_case": public_case,
            "response_vocabulary": vocabulary,
            "oracle": oracle,
        },
        "provenance": {
            "generator_id": "public_sec_integrated_indicator_map_derivation_v4",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    draft = CaseManifest.from_dict(raw)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError(f"unstable indicator-map case hash for {slug}")
    DataCenterTermsPlugin().validate_payload(case.payload)
    derived_public = _plain(case.payload["public_case"])
    for field in (
        "title",
        "task_family_id",
        "independence_cluster_id",
        "tier",
        "cutoff",
        "authority",
        "observations",
    ):
        if derived_public[field] != base_public[field]:
            raise ValueError(f"{slug}: indicator-map public field {field} differs")
    if _plain(case.payload["response_vocabulary"]) != vocabulary:
        raise ValueError(f"{slug}: indicator-map vocabulary differs")
    if _plain(case.payload["oracle"]) != oracle:
        raise ValueError(f"{slug}: indicator-map oracle differs")
    return case


def load_public_integrated_v4_cases(
    *,
    case_slugs: tuple[str, ...] | None = None,
    manifest_path: Path | str = MANIFEST_PATH,
) -> tuple[CaseManifest, ...]:
    load_public_integrated_v4_manifest(manifest_path)
    base_cases = load_public_integrated_v2_cases(case_slugs=case_slugs)
    cases = tuple(_derived_case(case) for case in base_cases)
    expected_count = 3 if case_slugs is None else len(case_slugs)
    if len(cases) != expected_count:
        raise ValueError("public integrated v4 case count differs")
    return cases


def public_integrated_v4_pack_sha256() -> str:
    manifest = load_public_integrated_v4_manifest()
    digest = hashlib.sha256()
    digest.update(MANIFEST_PATH.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(MANIFEST_PATH.read_bytes())
    digest.update(b"\0base_pack_sha256\0")
    digest.update(manifest["base_pack_sha256"].encode("ascii"))
    return digest.hexdigest()


__all__ = [
    "DERIVED_SPLIT",
    "INDICATOR_MAP_SUFFIX",
    "MANIFEST_PATH",
    "PACK_ID",
    "PACK_ROOT",
    "load_public_integrated_v4_cases",
    "load_public_integrated_v4_manifest",
    "public_integrated_v4_pack_sha256",
]
