"""Load the integrated public-primary-source data-center project case pack."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, DataCenterTermsPlugin


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "public_integrated_v1"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
CASES_PATH = PACK_ROOT / "cases.jsonl"
SOURCE_CATALOG_PATH = PACK_ROOT / "source_catalog.json"
PACK_ID = "datacenter_development_terms_public_integrated_v1"
_OPAQUE_EVIDENCE_ID = re.compile(r"^e[0-9]{2}$")
_ACCESSION = re.compile(r"^[0-9]{18}$")
_SANITIZATION_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\Users\\\\)"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}"),
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} must contain an object")
        rows.append(value)
    return rows


def _validate_arithmetic(check: Mapping[str, Any], case_slug: str) -> None:
    if check.get("operation") != "sum":
        raise ValueError(f"{case_slug}: unsupported arithmetic operation")
    inputs = check.get("inputs")
    expected = check.get("expected")
    tolerance = check.get("tolerance", 0.01)
    numeric = (int, float)
    if (
        not isinstance(inputs, list)
        or any(isinstance(item, bool) or not isinstance(item, numeric) for item in inputs)
        or isinstance(expected, bool)
        or not isinstance(expected, numeric)
        or isinstance(tolerance, bool)
        or not isinstance(tolerance, numeric)
    ):
        raise ValueError(f"{case_slug}: malformed arithmetic check")
    if not math.isclose(
        math.fsum(float(item) for item in inputs),
        float(expected),
        rel_tol=0.0,
        abs_tol=float(tolerance),
    ):
        raise ValueError(f"{case_slug}: arithmetic check does not reconcile")


def _pack_digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_public_integrated_authoring_records(
    *,
    manifest_path: Path | str = MANIFEST_PATH,
    cases_path: Path | str = CASES_PATH,
    source_catalog_path: Path | str = SOURCE_CATALOG_PATH,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]]:
    """Validate source lineage, cluster accounting, leakage, and hidden oracles."""

    manifest_file = Path(manifest_path)
    cases_file = Path(cases_path)
    catalog_file = Path(source_catalog_path)
    manifest = _load_json(manifest_file)
    records = _load_jsonl(cases_file)
    catalog = _load_json(catalog_file)
    expected_manifest = {
        "benchmark_id": FAMILY_ID,
        "version": FAMILY_VERSION,
        "pack_id": PACK_ID,
        "case_count": 3,
        "evidence_basis": "public_primary_sec_filings_paraphrased",
        "historical_grounding_status": (
            "public_source_reproducible_from_sec_accessions_and_locators"
        ),
        "independent_sampling_unit": "public_filing_project_cluster",
        "independence_cluster_count": 3,
        "inference_status": (
            "exploratory_three_new_integrated_public_project_clusters"
        ),
        "authority_modes_exercised": ["report"],
    }
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise ValueError("public integrated pack manifest differs")
    if len(records) != 3:
        raise ValueError("public integrated v1 must contain exactly three cases")

    source_map = catalog.get("sources")
    if not isinstance(source_map, dict) or len(source_map) != 5:
        raise ValueError("public integrated source catalog must contain five documents")
    if catalog.get("lineage_scope") != "sec_accession_document_and_clause_locator":
        raise ValueError("public integrated source lineage differs")
    if catalog.get("original_artifacts_included") is not False:
        raise ValueError("public integrated pack must not vendor source documents")
    if catalog.get("public_reproducibility") is not True:
        raise ValueError("public integrated sources must remain reproducible")
    if catalog.get("upstream_byte_hash_status") != (
        "not_collected_public_web_review_no_upstream_hash"
    ):
        raise ValueError("public integrated source hash boundary differs")
    for source_id, source in source_map.items():
        if not isinstance(source, Mapping):
            raise ValueError(f"{source_id}: source entry must be an object")
        if source.get("verification") != "public_primary_filing_reviewed":
            raise ValueError(f"{source_id}: source verification differs")
        if source.get("original_included") is not False:
            raise ValueError(f"{source_id}: source artifact must remain unvendored")
        if source.get("upstream_sha256") is not None:
            raise ValueError(f"{source_id}: unavailable source hash must remain null")
        accession = source.get("accession")
        document = source.get("document")
        url = source.get("url")
        locators = source.get("locators")
        if not isinstance(accession, str) or _ACCESSION.fullmatch(accession) is None:
            raise ValueError(f"{source_id}: malformed SEC accession")
        if not isinstance(document, str) or not document.endswith((".htm", ".html")):
            raise ValueError(f"{source_id}: malformed SEC document name")
        if not isinstance(url, str):
            raise ValueError(f"{source_id}: missing SEC URL")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "www.sec.gov":
            raise ValueError(f"{source_id}: source must use SEC HTTPS")
        if f"/{accession}/{document}" not in parsed.path:
            raise ValueError(f"{source_id}: SEC URL does not bind accession and document")
        if not isinstance(locators, list) or not locators or any(
            not isinstance(locator, str) or not locator for locator in locators
        ):
            raise ValueError(f"{source_id}: source locators are required")

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
    slugs = set()
    clusters = set()
    referenced_sources = set()
    state_values = set()
    for record in records:
        if set(record) != expected_fields:
            raise ValueError(f"case fields differ for {record.get('case_slug')!r}")
        slug = record["case_slug"]
        if not isinstance(slug, str) or not slug or slug in slugs:
            raise ValueError(f"duplicate or invalid case slug {slug!r}")
        slugs.add(slug)
        cluster = record["independence_cluster_id"]
        if not isinstance(cluster, str) or not cluster:
            raise ValueError(f"{slug}: invalid source cluster")
        clusters.add(cluster)
        if record["tier"] != 3:
            raise ValueError(f"{slug}: integrated cases must be tier three")
        if record["authority"] != {
            "mode": "report",
            "external_actions_authorized": False,
        }:
            raise ValueError(f"{slug}: integrated pack supports report-only authority")
        observations = record["observations"]
        evidence_ids = [item.get("evidence_id") for item in observations]
        if any(
            not isinstance(item, str) or _OPAQUE_EVIDENCE_ID.fullmatch(item) is None
            for item in evidence_ids
        ):
            raise ValueError(f"{slug}: evidence identifiers must be opaque eNN values")
        if evidence_ids != [f"e{index:02d}" for index in range(1, len(evidence_ids) + 1)]:
            raise ValueError(f"{slug}: evidence identifiers must be ordered and contiguous")
        oracle = record["oracle"]
        gold = oracle["gold"]
        state_values.update(gold["states"].values())
        if set(gold["required_evidence_ids"]) - set(evidence_ids):
            raise ValueError(f"{slug}: gold references unavailable evidence")
        source_refs = set(oracle["source_refs"])
        if not source_refs:
            raise ValueError(f"{slug}: at least one filing source is required")
        missing = source_refs - set(source_map)
        if missing:
            raise ValueError(f"{slug}: unknown source refs {sorted(missing)}")
        source_clusters = {source_map[source]["source_cluster_id"] for source in source_refs}
        if source_clusters != {cluster}:
            raise ValueError(f"{slug}: all source documents must share the case cluster")
        referenced_sources.update(source_refs)
        for check in oracle["arithmetic_checks"]:
            _validate_arithmetic(check, slug)
    if len(clusters) != 3:
        raise ValueError("public integrated cases require three project clusters")
    if clusters != {source["source_cluster_id"] for source in source_map.values()}:
        raise ValueError("public integrated case and source clusters differ")
    if referenced_sources != set(source_map):
        raise ValueError("public integrated source catalog has unreferenced documents")
    if set(manifest.get("state_value_vocabulary", [])) != state_values:
        raise ValueError("public integrated state vocabulary differs from oracles")

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
    case_id = f"{FAMILY_ID}.public_integrated_v1.{record['case_slug']}"
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
        "split": "public_integrated_v1",
        "world_seed": world_seed,
        "seats": [{"id": "analyst", "role": "analyst"}],
        "episode": {
            "max_logical_actions": 1,
            "termination": ["submitted", "invalid_submission"],
        },
        "visibility_policy": (
            "datacenter_terms_public_observation_private_oracle_v1"
        ),
        "payload": {
            "public_case": public_case,
            "response_vocabulary": {"state_values": list(state_values)},
            "oracle": record["oracle"],
        },
        "provenance": {
            "generator_id": "public_sec_integrated_case_pack_v1",
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


def load_public_integrated_cases(
    *,
    case_slugs: tuple[str, ...] | None = None,
    manifest_path: Path | str = MANIFEST_PATH,
    cases_path: Path | str = CASES_PATH,
    source_catalog_path: Path | str = SOURCE_CATALOG_PATH,
) -> tuple[CaseManifest, ...]:
    manifest, records, _ = load_public_integrated_authoring_records(
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
            raise ValueError(f"unknown integrated case slugs: {sorted(requested - found)}")
    state_values = tuple(manifest["state_value_vocabulary"])
    seed_by_slug = {
        record["case_slug"]: 441001 + index for index, record in enumerate(records)
    }
    return tuple(
        _case_manifest(
            record,
            state_values=state_values,
            world_seed=seed_by_slug[record["case_slug"]],
        )
        for record in selected
    )


def public_integrated_pack_sha256() -> str:
    return _pack_digest((MANIFEST_PATH, CASES_PATH, SOURCE_CATALOG_PATH))


__all__ = [
    "CASES_PATH",
    "MANIFEST_PATH",
    "PACK_ID",
    "PACK_ROOT",
    "SOURCE_CATALOG_PATH",
    "load_public_integrated_authoring_records",
    "load_public_integrated_cases",
    "public_integrated_pack_sha256",
]
