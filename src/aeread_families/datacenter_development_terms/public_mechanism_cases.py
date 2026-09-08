"""Load the paired public integrated-underwriting mechanism cases."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, DataCenterTermsPlugin


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "public_mechanism_v1"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
CASES_PATH = PACK_ROOT / "cases.jsonl"
SOURCE_CATALOG_PATH = PACK_ROOT / "source_catalog.json"
PACK_ID = "datacenter_development_terms_public_mechanism_v1"
SOURCE_ID = "core_denton_project_terms_2026"
CLUSTER_ID = "sec_core_denton_project_terms_2026"
AFFIRM_ONLY_SUFFIX = (
    " In the actions and claims arrays, include only labels you affirm as "
    "supported by the evidence; omit labels you reject."
)
MECHANISM_BY_PREFIX = {
    "assignment-consent": "assignment_consent",
    "land-power-cotermination": "land_power_cotermination",
    "gmp-change-order": "gmp_change_order",
}
_OPAQUE_EVIDENCE_ID = re.compile(r"^e[0-9]{2}$")
_ACCESSION = re.compile(r"^[0-9]{18}$")
_SANITIZATION_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} must contain an object")
        rows.append(value)
    return rows


def _pack_digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def mechanism_and_condition(case_slug: str) -> tuple[str, str]:
    for prefix, mechanism in MECHANISM_BY_PREFIX.items():
        if case_slug == f"{prefix}-m01":
            return mechanism, "baseline"
        if case_slug == f"{prefix}-m02":
            return mechanism, "affirm_only"
    raise ValueError(f"unknown public mechanism case slug {case_slug!r}")


def load_public_mechanism_authoring_records(
    *,
    manifest_path: Path | str = MANIFEST_PATH,
    cases_path: Path | str = CASES_PATH,
    source_catalog_path: Path | str = SOURCE_CATALOG_PATH,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]]:
    manifest_file = Path(manifest_path)
    cases_file = Path(cases_path)
    catalog_file = Path(source_catalog_path)
    manifest = _load_json(manifest_file)
    records = _load_jsonl(cases_file)
    catalog = _load_json(catalog_file)

    required_manifest = {
        "benchmark_id": FAMILY_ID,
        "version": FAMILY_VERSION,
        "pack_id": PACK_ID,
        "case_count": 6,
        "evidence_basis": "public_primary_sec_filing_paraphrased",
        "historical_grounding_status": (
            "public_source_reproducible_from_sec_accession_and_locators"
        ),
        "independent_sampling_unit": "public_filing_cluster",
        "independence_cluster_count": 1,
        "mechanism_count": 3,
        "wording_conditions": ["baseline", "affirm_only"],
        "inference_status": "within_source_mechanism_diagnostic_only",
        "authority_modes_exercised": ["report"],
    }
    if any(manifest.get(key) != value for key, value in required_manifest.items()):
        raise ValueError("public mechanism manifest differs")
    state_values = manifest.get("state_value_vocabulary")
    if (
        not isinstance(state_values, list)
        or len(state_values) != len(set(state_values))
        or any(not isinstance(value, str) or not value for value in state_values)
    ):
        raise ValueError("public mechanism state vocabulary differs")

    sources = catalog.get("sources")
    if not isinstance(sources, dict) or set(sources) != {SOURCE_ID}:
        raise ValueError("public mechanism source catalog differs")
    if (
        catalog.get("lineage_scope")
        != "sec_accession_document_and_clause_locator"
        or catalog.get("original_artifacts_included") is not False
        or catalog.get("public_reproducibility") is not True
        or catalog.get("upstream_byte_hash_status")
        != "not_available_shell_retrieval_returned_http_403"
    ):
        raise ValueError("public mechanism provenance boundary differs")
    source = sources[SOURCE_ID]
    accession = source.get("accession")
    document = source.get("document")
    url = source.get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (
        source.get("verification") != "public_primary_filing_reviewed"
        or source.get("original_included") is not False
        or source.get("upstream_sha256") is not None
        or source.get("source_cluster_id") != CLUSTER_ID
        or not isinstance(accession, str)
        or _ACCESSION.fullmatch(accession) is None
        or not isinstance(document, str)
        or not document.endswith((".htm", ".html"))
        or parsed is None
        or parsed.scheme != "https"
        or parsed.netloc != "www.sec.gov"
        or f"/{accession}/{document}" not in parsed.path
        or not isinstance(source.get("locators"), list)
        or not source["locators"]
    ):
        raise ValueError("public mechanism SEC source entry differs")

    expected_fields = {
        "case_slug",
        "task_family_id",
        "independence_cluster_id",
        "tier",
        "title",
        "cutoff",
        "authority",
        "prompt",
        "observations",
        "oracle",
    }
    if len(records) != 6:
        raise ValueError("public mechanism pack requires six cases")
    by_mechanism: dict[str, dict[str, dict[str, Any]]] = {}
    gold_states: set[str] = set()
    slugs: set[str] = set()
    for record in records:
        if set(record) != expected_fields:
            raise ValueError(f"case fields differ for {record.get('case_slug')!r}")
        slug = record["case_slug"]
        if not isinstance(slug, str) or slug in slugs:
            raise ValueError(f"duplicate or invalid case slug {slug!r}")
        slugs.add(slug)
        mechanism, condition = mechanism_and_condition(slug)
        by_mechanism.setdefault(mechanism, {})[condition] = record
        if record["independence_cluster_id"] != CLUSTER_ID:
            raise ValueError(f"{slug}: source cluster differs")
        if record["authority"] != {
            "mode": "report",
            "external_actions_authorized": False,
        }:
            raise ValueError(f"{slug}: report-only authority differs")
        observations = record["observations"]
        evidence_ids = [item.get("evidence_id") for item in observations]
        if evidence_ids != [f"e{index:02d}" for index in range(1, len(evidence_ids) + 1)]:
            raise ValueError(f"{slug}: evidence IDs must be ordered and contiguous")
        if any(
            not isinstance(evidence_id, str)
            or _OPAQUE_EVIDENCE_ID.fullmatch(evidence_id) is None
            for evidence_id in evidence_ids
        ):
            raise ValueError(f"{slug}: evidence IDs must be opaque")
        oracle = record["oracle"]
        gold = oracle["gold"]
        gold_states.update(gold["states"].values())
        if set(gold["required_evidence_ids"]) - set(evidence_ids):
            raise ValueError(f"{slug}: gold references unavailable evidence")
        if oracle["source_refs"] != [SOURCE_ID]:
            raise ValueError(f"{slug}: source reference differs")
        if oracle["arithmetic_checks"] != []:
            raise ValueError(f"{slug}: mechanism cases have no arithmetic checks")
        for required, forbidden in (
            (gold["required_actions"], gold["forbidden_actions"]),
            (gold["required_claims"], gold["forbidden_claims"]),
        ):
            if set(required) & set(forbidden):
                raise ValueError(f"{slug}: required and forbidden labels overlap")
    if set(by_mechanism) != set(MECHANISM_BY_PREFIX.values()) or any(
        set(pair) != {"baseline", "affirm_only"} for pair in by_mechanism.values()
    ):
        raise ValueError("public mechanism wording pairs differ")
    if not gold_states < set(state_values):
        raise ValueError("state vocabulary must contain gold states and decoys")

    for mechanism, pair in by_mechanism.items():
        baseline = pair["baseline"]
        explicit = pair["affirm_only"]
        if explicit["prompt"] != baseline["prompt"] + AFFIRM_ONLY_SUFFIX:
            raise ValueError(f"{mechanism}: wording contrast differs")
        for field in expected_fields - {"case_slug", "prompt"}:
            if baseline[field] != explicit[field]:
                raise ValueError(f"{mechanism}: paired field {field} differs")

    for path in (manifest_file, cases_file, catalog_file):
        text = path.read_text(encoding="utf-8")
        for label, pattern in _SANITIZATION_PATTERNS.items():
            if pattern.search(text):
                raise ValueError(f"{path.name}: sanitization violation: {label}")
    return manifest, tuple(records), catalog


def _case_manifest(
    record: Mapping[str, Any],
    *,
    state_values: tuple[str, ...],
    world_seed: int,
) -> CaseManifest:
    case_id = f"{FAMILY_ID}.public_mechanism_v1.{record['case_slug']}"
    public_case = {
        "case_id": case_id,
        "title": record["title"],
        "task_family_id": record["task_family_id"],
        "independence_cluster_id": record["independence_cluster_id"],
        "tier": record["tier"],
        "cutoff": record["cutoff"],
        "authority": record["authority"],
        "prompt": record["prompt"],
        "observations": record["observations"],
    }
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": "public_mechanism_v1",
        "world_seed": world_seed,
        "seats": [{"id": "analyst", "role": "analyst"}],
        "episode": {
            "max_logical_actions": 1,
            "termination": ["submitted", "invalid_submission"],
        },
        "visibility_policy": (
            "datacenter_terms_public_mechanism_observation_private_oracle_v1"
        ),
        "payload": {
            "public_case": public_case,
            "response_vocabulary": {"state_values": list(state_values)},
            "oracle": record["oracle"],
        },
        "provenance": {
            "generator_id": "public_sec_filing_mechanism_case_pack_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    draft = CaseManifest.from_dict(raw)
    raw["content_sha256"] = case_content_sha256(draft)
    case = CaseManifest.from_dict(raw)
    if case_content_sha256(case) != case.content_sha256:
        raise AssertionError(f"unstable content hash for {case_id}")
    DataCenterTermsPlugin().validate_payload(case.payload)
    return case


def load_public_mechanism_cases(
    *,
    case_slugs: tuple[str, ...] | None = None,
    manifest_path: Path | str = MANIFEST_PATH,
    cases_path: Path | str = CASES_PATH,
    source_catalog_path: Path | str = SOURCE_CATALOG_PATH,
) -> tuple[CaseManifest, ...]:
    manifest, records, _ = load_public_mechanism_authoring_records(
        manifest_path=manifest_path,
        cases_path=cases_path,
        source_catalog_path=source_catalog_path,
    )
    selected = records
    if case_slugs is not None:
        requested = set(case_slugs)
        selected = tuple(record for record in records if record["case_slug"] in requested)
        found = {record["case_slug"] for record in selected}
        if found != requested:
            raise ValueError(f"unknown mechanism slugs: {sorted(requested - found)}")
    seed_by_mechanism = {
        "assignment_consent": 450001,
        "land_power_cotermination": 450002,
        "gmp_change_order": 450003,
    }
    return tuple(
        _case_manifest(
            record,
            state_values=tuple(manifest["state_value_vocabulary"]),
            world_seed=seed_by_mechanism[mechanism_and_condition(record["case_slug"])[0]],
        )
        for record in selected
    )


def public_mechanism_pack_sha256() -> str:
    return _pack_digest((MANIFEST_PATH, CASES_PATH, SOURCE_CATALOG_PATH))


__all__ = [
    "AFFIRM_ONLY_SUFFIX",
    "CASES_PATH",
    "CLUSTER_ID",
    "MANIFEST_PATH",
    "MECHANISM_BY_PREFIX",
    "PACK_ID",
    "PACK_ROOT",
    "SOURCE_CATALOG_PATH",
    "SOURCE_ID",
    "load_public_mechanism_authoring_records",
    "load_public_mechanism_cases",
    "mechanism_and_condition",
    "public_mechanism_pack_sha256",
]
