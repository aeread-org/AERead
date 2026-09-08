"""Restore one omitted visible amount and audit numeric answerability."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, DataCenterTermsPlugin
from .public_integrated_expansion_v2_cases import PACK_ID as BASE_PACK_ID
from .public_integrated_expansion_v2_cases import (
    load_public_integrated_expansion_v2_cases,
    public_integrated_expansion_v2_pack_sha256,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "public_integrated_expansion_v3"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
PACK_ID = "datacenter_development_terms_public_integrated_expansion_v3"
DERIVED_SPLIT = "public_integrated_expansion_v3"
TYDAL_SLUG = "tydal-open-book-epc-governance-and-risk"
CORRECTED_EVIDENCE_ID = "e05"
CORRECTED_OBSERVATION_CONTENT = (
    "The contractor invoices monthly in arrears after account review. The final "
    "itemized invoice is due on the 22nd of the month in which project accounts "
    "are submitted, or on the first working day thereafter if the 22nd is not a "
    "working day. Payment is structured to keep the contractor cash neutral "
    "rather than financing project costs. If an undisputed invoice remains "
    "unpaid after its due date and seven days following written notice, the "
    "contractor may suspend work and claim documented time and cost effects."
)
_SANITIZATION_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def load_public_integrated_expansion_v3_manifest(
    path: Path | str = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("public integrated expansion v3 manifest must be an object")
    expected = {
        "benchmark_id": FAMILY_ID,
        "version": FAMILY_VERSION,
        "pack_id": PACK_ID,
        "base_pack_id": BASE_PACK_ID,
        "base_pack_sha256": public_integrated_expansion_v2_pack_sha256(),
        "case_count": 3,
        "independent_sampling_unit": "public_filing_project_cluster",
        "independence_cluster_count": 3,
        "derived_split": DERIVED_SPLIT,
        "transformation_id": "restore_visible_tydal_invoice_payment_day_v1",
        "answerability_correction": {
            "case_slug": TYDAL_SLUG,
            "evidence_id": CORRECTED_EVIDENCE_ID,
            "oracle_field": "amounts.invoice_payment_day",
            "oracle_value": 22.0,
            "omission_in_base": "invoice payment day absent from visible observation",
            "source_locator": "Tydal EPC Agreement clause 7.5 - Invoicing",
        },
        "preserved_fields": [
            "title",
            "task_family_id",
            "independence_cluster_id",
            "tier",
            "cutoff",
            "authority",
            "prompt",
            "response_vocabulary",
            "oracle",
            "world_seed",
        ],
        "inference_status": (
            "answerability_corrected_indicator_map_three_additional_project_"
            "cluster_diagnostic"
        ),
        "authority_modes_exercised": ["report"],
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("public integrated expansion v3 derivation manifest differs")
    amount_evidence_map = manifest.get("amount_evidence_map")
    required_fragments = manifest.get("required_visible_fragments")
    if not isinstance(amount_evidence_map, Mapping) or not isinstance(
        required_fragments, Mapping
    ):
        raise ValueError("public integrated expansion v3 answerability audit differs")
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
    public_case = _plain(base_public)
    if slug == TYDAL_SLUG:
        observations = public_case["observations"]
        matches = [
            item for item in observations if item["evidence_id"] == CORRECTED_EVIDENCE_ID
        ]
        if len(matches) != 1 or "22nd" in matches[0]["content"]:
            raise ValueError("Tydal base e05 answerability state differs")
        matches[0]["content"] = CORRECTED_OBSERVATION_CONTENT

    case_id = f"{FAMILY_ID}.{DERIVED_SPLIT}.{slug}"
    public_case["case_id"] = case_id
    oracle = _plain(base.payload["oracle"])
    vocabulary = _plain(base.payload["response_vocabulary"])
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
            "datacenter_terms_public_expansion_v3_observation_private_oracle_v1"
        ),
        "payload": {
            "public_case": public_case,
            "response_vocabulary": vocabulary,
            "oracle": oracle,
        },
        "provenance": {
            "generator_id": "public_sec_expansion_answerability_correction_v3",
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
    return case


def _validate_answerability(
    manifest: Mapping[str, Any], cases: tuple[CaseManifest, ...]
) -> None:
    amount_map = manifest["amount_evidence_map"]
    fragment_map = manifest["required_visible_fragments"]
    cases_by_slug = {case.case_id.rsplit(".", 1)[-1]: case for case in cases}
    if set(amount_map) != set(cases_by_slug):
        raise ValueError("amount evidence map case set differs")
    for slug, case in cases_by_slug.items():
        public_case = _plain(case.payload["public_case"])
        observations = {
            item["evidence_id"]: item["content"] for item in public_case["observations"]
        }
        gold_amounts = set(case.payload["oracle"]["gold"]["amounts"])
        mapping = amount_map[slug]
        if not isinstance(mapping, Mapping) or set(mapping) != gold_amounts:
            raise ValueError(f"{slug}: numeric oracle evidence coverage differs")
        if any(evidence_id not in observations for evidence_id in mapping.values()):
            raise ValueError(f"{slug}: numeric oracle maps to unavailable evidence")
        for evidence_id, fragments in fragment_map.get(slug, {}).items():
            if evidence_id not in observations or any(
                fragment.casefold() not in observations[evidence_id].casefold()
                for fragment in fragments
            ):
                raise ValueError(f"{slug}: required visible amount fragment absent")


def load_public_integrated_expansion_v3_cases(
    *,
    case_slugs: tuple[str, ...] | None = None,
    manifest_path: Path | str = MANIFEST_PATH,
) -> tuple[CaseManifest, ...]:
    manifest = load_public_integrated_expansion_v3_manifest(manifest_path)
    base_cases = load_public_integrated_expansion_v2_cases(case_slugs=case_slugs)
    cases = tuple(_derived_case(case) for case in base_cases)
    expected_count = 3 if case_slugs is None else len(case_slugs)
    if len(cases) != expected_count:
        raise ValueError("public integrated expansion v3 case count differs")
    if case_slugs is None:
        _validate_answerability(manifest, cases)
    return cases


def public_integrated_expansion_v3_pack_sha256() -> str:
    manifest = load_public_integrated_expansion_v3_manifest()
    digest = hashlib.sha256()
    digest.update(MANIFEST_PATH.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(MANIFEST_PATH.read_bytes())
    digest.update(b"\0base_pack_sha256\0")
    digest.update(manifest["base_pack_sha256"].encode("ascii"))
    return digest.hexdigest()


__all__ = [
    "CORRECTED_EVIDENCE_ID",
    "CORRECTED_OBSERVATION_CONTENT",
    "DERIVED_SPLIT",
    "MANIFEST_PATH",
    "PACK_ID",
    "PACK_ROOT",
    "TYDAL_SLUG",
    "load_public_integrated_expansion_v3_cases",
    "load_public_integrated_expansion_v3_manifest",
    "public_integrated_expansion_v3_pack_sha256",
]
