"""Derive the corrected integrated public data-center project case pack."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, DataCenterTermsPlugin
from .public_integrated_cases import PACK_ID as BASE_PACK_ID
from .public_integrated_cases import (
    load_public_integrated_cases,
    public_integrated_pack_sha256,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "public_integrated_v2"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
PACK_ID = "datacenter_development_terms_public_integrated_v2"
DERIVED_SPLIT = "public_integrated_v2"
HORIZON_SLUG = "horizon-tranche-acceptance-financing-guarantees"
SERVICE_STATE = "executed_service_agreement"
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


def load_public_integrated_v2_manifest(
    path: Path | str = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "benchmark_id": FAMILY_ID,
        "version": FAMILY_VERSION,
        "pack_id": PACK_ID,
        "base_pack_id": BASE_PACK_ID,
        "base_pack_sha256": public_integrated_pack_sha256(),
        "case_count": 3,
        "independent_sampling_unit": "public_filing_project_cluster",
        "independence_cluster_count": 3,
        "derived_split": DERIVED_SPLIT,
        "transformation_id": (
            "correct_service_agreement_state_and_affirmed_candidate_"
            "instruction_v1"
        ),
        "prompt_suffix": CANDIDATE_SCREEN_SUFFIX,
        "oracle_correction": {
            "case_slug": HORIZON_SLUG,
            "field": "gold.states.customer_contract_state",
            "from": "executed_long_term_lease",
            "to": SERVICE_STATE,
            "reason": (
                "the public evidence describes a GPU services agreement rather "
                "than a lease"
            ),
        },
        "response_vocabulary_additions": [SERVICE_STATE],
        "preserved_fields": [
            "title",
            "task_family_id",
            "independence_cluster_id",
            "tier",
            "cutoff",
            "authority",
            "observations",
            "amounts",
            "required_actions",
            "forbidden_actions",
            "required_claims",
            "forbidden_claims",
            "required_evidence_ids",
            "amount_tolerance",
            "terminal_when",
            "source_refs",
            "failure_mechanisms",
            "arithmetic_checks",
            "world_seed",
        ],
        "inference_status": (
            "corrected_exploratory_three_project_cluster_diagnostic"
        ),
        "authority_modes_exercised": ["report"],
    }
    if not isinstance(manifest, dict) or manifest != required:
        raise ValueError("public integrated v2 derivation manifest differs")
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
    base_oracle = _plain(base.payload["oracle"])
    oracle = _plain(base_oracle)
    response_vocabulary = _plain(base.payload["response_vocabulary"])
    state_values = list(response_vocabulary["state_values"])
    if SERVICE_STATE in state_values:
        raise ValueError("base integrated vocabulary already contains correction")
    state_values.append(SERVICE_STATE)
    response_vocabulary["state_values"] = state_values
    if slug == HORIZON_SLUG:
        states = oracle["gold"]["states"]
        if states["customer_contract_state"] != "executed_long_term_lease":
            raise ValueError("Horizon base contract state differs")
        states["customer_contract_state"] = SERVICE_STATE

    case_id = f"{FAMILY_ID}.{DERIVED_SPLIT}.{slug}"
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
            "datacenter_terms_public_integrated_v2_observation_private_oracle_v1"
        ),
        "payload": {
            "public_case": public_case,
            "response_vocabulary": response_vocabulary,
            "oracle": oracle,
        },
        "provenance": {
            "generator_id": "public_sec_integrated_case_correction_v2",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    draft = CaseManifest.from_dict(raw)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError(f"unstable corrected case hash for {slug}")
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
            raise ValueError(f"{slug}: corrected public field {field} differs")
    for field in (
        "amounts",
        "required_actions",
        "forbidden_actions",
        "required_claims",
        "forbidden_claims",
        "required_evidence_ids",
        "amount_tolerance",
    ):
        if oracle["gold"][field] != base_oracle["gold"][field]:
            raise ValueError(f"{slug}: corrected oracle gold {field} differs")
    for field in (
        "terminal_when",
        "source_refs",
        "failure_mechanisms",
        "arithmetic_checks",
    ):
        if oracle[field] != base_oracle[field]:
            raise ValueError(f"{slug}: corrected oracle {field} differs")
    expected_states = _plain(base_oracle["gold"]["states"])
    if slug == HORIZON_SLUG:
        expected_states["customer_contract_state"] = SERVICE_STATE
    if oracle["gold"]["states"] != expected_states:
        raise ValueError(f"{slug}: corrected state scope differs")
    return case


def load_public_integrated_v2_cases(
    *,
    case_slugs: tuple[str, ...] | None = None,
    manifest_path: Path | str = MANIFEST_PATH,
) -> tuple[CaseManifest, ...]:
    load_public_integrated_v2_manifest(manifest_path)
    base_cases = load_public_integrated_cases(case_slugs=case_slugs)
    cases = tuple(_derived_case(case) for case in base_cases)
    expected_count = 3 if case_slugs is None else len(case_slugs)
    if len(cases) != expected_count:
        raise ValueError("public integrated v2 case count differs")
    if len(
        {
            case.payload["public_case"]["independence_cluster_id"]
            for case in cases
        }
    ) != len(cases):
        raise ValueError("corrected integrated cases must retain source clusters")
    return cases


def public_integrated_v2_pack_sha256() -> str:
    manifest = load_public_integrated_v2_manifest()
    digest = hashlib.sha256()
    digest.update(MANIFEST_PATH.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(MANIFEST_PATH.read_bytes())
    digest.update(b"\0base_pack_sha256\0")
    digest.update(manifest["base_pack_sha256"].encode("ascii"))
    return digest.hexdigest()


__all__ = [
    "CANDIDATE_SCREEN_SUFFIX",
    "DERIVED_SPLIT",
    "HORIZON_SLUG",
    "MANIFEST_PATH",
    "PACK_ID",
    "PACK_ROOT",
    "SERVICE_STATE",
    "load_public_integrated_v2_cases",
    "load_public_integrated_v2_manifest",
    "public_integrated_v2_pack_sha256",
]
