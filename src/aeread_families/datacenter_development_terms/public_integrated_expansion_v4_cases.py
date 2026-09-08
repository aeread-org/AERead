"""Add an explicit numeric-unit contract to the corrected expansion cases."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, DataCenterTermsPlugin
from .public_integrated_expansion_v3_cases import PACK_ID as BASE_PACK_ID
from .public_integrated_expansion_v3_cases import (
    load_public_integrated_expansion_v3_cases,
    public_integrated_expansion_v3_pack_sha256,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "public_integrated_expansion_v4"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
PACK_ID = "datacenter_development_terms_public_integrated_expansion_v4"
DERIVED_SPLIT = "public_integrated_expansion_v4"
UNIT_INSTRUCTION = (
    "Numeric-unit rule: return monetary amounts in base currency units, not in "
    "millions or billions (for example, $90 million is 90000000 and NOK 4.5 "
    "billion is 4500000000). For every other numeric field, use the unit named "
    "by its key, including MW, percent, days, months, years, acres, DSCR, and counts."
)
CURRENCY_BASE_UNIT_FIELDS = {
    "helios-phased-capacity-revenue-and-draws": (
        "advance_lease_billings",
        "recognized_data_center_lease_revenue",
        "facility_maximum",
        "facility_drawn",
    ),
    "lake-mariner-lease-commencement-prepaid-rent-and-land": (
        "prepaid_rent_received",
        "current_deferred_rent",
        "noncurrent_deferred_rent",
        "remaining_deferred_rent",
    ),
    "tydal-open-book-epc-governance-and-risk": (
        "estimated_total_refurbishment_nok",
    ),
}
_SANITIZATION_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def load_public_integrated_expansion_v4_manifest(
    path: Path | str = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("public integrated expansion v4 manifest must be an object")
    expected = {
        "benchmark_id": FAMILY_ID,
        "version": FAMILY_VERSION,
        "pack_id": PACK_ID,
        "base_pack_id": BASE_PACK_ID,
        "base_pack_sha256": public_integrated_expansion_v3_pack_sha256(),
        "case_count": 3,
        "independent_sampling_unit": "public_filing_project_cluster",
        "independence_cluster_count": 3,
        "derived_split": DERIVED_SPLIT,
        "transformation_id": "append_explicit_numeric_unit_contract_v1",
        "unit_instruction": UNIT_INSTRUCTION,
        "currency_base_unit_fields": {
            slug: list(fields) for slug, fields in CURRENCY_BASE_UNIT_FIELDS.items()
        },
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
        "inference_status": (
            "answerability_and_units_corrected_indicator_map_three_additional_"
            "project_cluster_diagnostic"
        ),
        "authority_modes_exercised": ["report"],
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("public integrated expansion v4 derivation manifest differs")
    text = manifest_path.read_text(encoding="utf-8")
    for label, pattern in _SANITIZATION_PATTERNS.items():
        if pattern.search(text):
            raise ValueError(f"manifest.json: sanitization violation: {label}")
    return manifest


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _derived_case(base: CaseManifest) -> CaseManifest:
    slug = base.case_id.rsplit(".", 1)[-1]
    public_case = _plain(base.payload["public_case"])
    prompt = str(public_case["prompt"])
    if UNIT_INSTRUCTION in prompt:
        raise ValueError(f"{slug}: base prompt already contains unit instruction")
    public_case["prompt"] = f"{prompt}\n\n{UNIT_INSTRUCTION}"
    case_id = f"{FAMILY_ID}.{DERIVED_SPLIT}.{slug}"
    public_case["case_id"] = case_id
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
            "datacenter_terms_public_expansion_v4_unit_explicit_observation_"
            "private_oracle_v1"
        ),
        "payload": {
            "public_case": public_case,
            "response_vocabulary": _plain(base.payload["response_vocabulary"]),
            "oracle": _plain(base.payload["oracle"]),
        },
        "provenance": {
            "generator_id": "public_sec_expansion_numeric_unit_correction_v4",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    draft = CaseManifest.from_dict(raw)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError(f"unstable unit-explicit case hash for {slug}")
    DataCenterTermsPlugin().validate_payload(case.payload)
    return case


def _validate_unit_answerability(cases: tuple[CaseManifest, ...]) -> None:
    cases_by_slug = {case.case_id.rsplit(".", 1)[-1]: case for case in cases}
    if set(cases_by_slug) != set(CURRENCY_BASE_UNIT_FIELDS):
        raise ValueError("currency unit case set differs")
    for slug, case in cases_by_slug.items():
        prompt = str(case.payload["public_case"]["prompt"])
        if not prompt.endswith(UNIT_INSTRUCTION):
            raise ValueError(f"{slug}: numeric unit instruction absent")
        gold_amounts = set(case.payload["oracle"]["gold"]["amounts"])
        fields = set(CURRENCY_BASE_UNIT_FIELDS[slug])
        if not fields or not fields <= gold_amounts:
            raise ValueError(f"{slug}: currency unit fields differ from oracle")


def load_public_integrated_expansion_v4_cases(
    *,
    case_slugs: tuple[str, ...] | None = None,
    manifest_path: Path | str = MANIFEST_PATH,
) -> tuple[CaseManifest, ...]:
    load_public_integrated_expansion_v4_manifest(manifest_path)
    base_cases = load_public_integrated_expansion_v3_cases(case_slugs=case_slugs)
    cases = tuple(_derived_case(case) for case in base_cases)
    expected_count = 3 if case_slugs is None else len(case_slugs)
    if len(cases) != expected_count:
        raise ValueError("public integrated expansion v4 case count differs")
    if case_slugs is None:
        _validate_unit_answerability(cases)
    return cases


def public_integrated_expansion_v4_pack_sha256() -> str:
    manifest = load_public_integrated_expansion_v4_manifest()
    digest = hashlib.sha256()
    digest.update(MANIFEST_PATH.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(MANIFEST_PATH.read_bytes())
    digest.update(b"\0base_pack_sha256\0")
    digest.update(manifest["base_pack_sha256"].encode("ascii"))
    return digest.hexdigest()


__all__ = [
    "CURRENCY_BASE_UNIT_FIELDS",
    "DERIVED_SPLIT",
    "MANIFEST_PATH",
    "PACK_ID",
    "PACK_ROOT",
    "UNIT_INSTRUCTION",
    "load_public_integrated_expansion_v4_cases",
    "load_public_integrated_expansion_v4_manifest",
    "public_integrated_expansion_v4_pack_sha256",
]
