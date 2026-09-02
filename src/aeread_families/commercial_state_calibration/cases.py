"""Load and validate the sanitized commercial-state calibration pilot."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import FAMILY_ID, FAMILY_VERSION, CommercialStatePlugin


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "pilot"
MANIFEST_PATH = PACK_ROOT / "manifest.json"
CASES_PATH = PACK_ROOT / "cases.jsonl"
SOURCE_CATALOG_PATH = PACK_ROOT / "source_catalog_private.json"

_OPAQUE_EVIDENCE_ID = re.compile(r"^e[0-9]{2}$")
_SANITIZATION_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "artifact-style hex identifier": re.compile(r"\b[0-9a-f]{24,}\b", re.IGNORECASE),
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
    if (
        not isinstance(inputs, list)
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in inputs)
        or isinstance(expected, bool)
        or not isinstance(expected, (int, float))
        or isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
    ):
        raise ValueError(f"{case_slug}: malformed arithmetic check")
    if not math.isclose(
        math.fsum(float(item) for item in inputs),
        float(expected),
        rel_tol=0.0,
        abs_tol=float(tolerance),
    ):
        raise ValueError(f"{case_slug}: arithmetic check does not reconcile")


def load_authoring_records(
    *,
    manifest_path: Path | str = MANIFEST_PATH,
    cases_path: Path | str = CASES_PATH,
    source_catalog_path: Path | str = SOURCE_CATALOG_PATH,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]]:
    """Load the authoring pack and enforce cross-file measurement invariants."""

    manifest_file = Path(manifest_path)
    cases_file = Path(cases_path)
    catalog_file = Path(source_catalog_path)
    manifest = _load_json(manifest_file)
    records = _load_jsonl(cases_file)
    catalog = _load_json(catalog_file)
    if manifest.get("benchmark_id") != FAMILY_ID:
        raise ValueError("pack benchmark_id does not match the AERead family")
    if manifest.get("version") != FAMILY_VERSION:
        raise ValueError("pack version does not match the AERead family")
    if manifest.get("case_count") != len(records):
        raise ValueError("pack case_count does not match cases.jsonl")
    if manifest.get("inference_status") != "diagnostic_only":
        raise ValueError("pilot must remain diagnostic_only")
    if manifest.get("authority_modes_exercised") != ["report"]:
        raise ValueError("v1 must declare report-only authority")
    if manifest.get("independence_cluster_count") != 1:
        raise ValueError("pilot must conservatively declare one independent cluster")

    source_map = catalog.get("sources")
    if not isinstance(source_map, dict) or not source_map:
        raise ValueError("source catalog must contain a non-empty sources object")
    if catalog.get("lineage_scope") != "role_only_not_reproducible_provenance":
        raise ValueError("source catalog must state its limited lineage scope")
    if catalog.get("rights_status") != "not_established_by_this_pack":
        raise ValueError("source catalog must not overclaim redistribution rights")

    slugs: set[str] = set()
    state_values: set[str] = set()
    clusters: set[str] = set()
    for record in records:
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
        if set(record) != expected_fields:
            raise ValueError(f"case record fields differ for {record.get('case_slug')!r}")
        slug = record["case_slug"]
        if not isinstance(slug, str) or not slug or slug in slugs:
            raise ValueError(f"duplicate or invalid case_slug {slug!r}")
        slugs.add(slug)
        clusters.add(record["independence_cluster_id"])
        if record["authority"] != {
            "mode": "report",
            "external_actions_authorized": False,
        }:
            raise ValueError(f"{slug}: v1 supports report-only authority")
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
        if "terminal_when" not in oracle:
            raise ValueError(f"{slug}: termination criterion must remain evaluator-only")
        gold = oracle["gold"]
        state_values.update(gold["states"].values())
        if set(gold["required_evidence_ids"]) - set(evidence_ids):
            raise ValueError(f"{slug}: gold references unavailable evidence")
        missing_sources = set(oracle["source_refs"]) - set(source_map)
        if missing_sources:
            raise ValueError(f"{slug}: unknown source refs {sorted(missing_sources)}")
        for check in oracle["arithmetic_checks"]:
            _validate_arithmetic(check, slug)

    if clusters != {"commercial_archive_pilot_01"}:
        raise ValueError("all pilot cases must share the conservative archive cluster")
    declared_states = set(manifest.get("state_value_vocabulary", []))
    if declared_states != state_values:
        raise ValueError(
            "state vocabulary drift: "
            f"missing={sorted(state_values - declared_states)}, "
            f"unused={sorted(declared_states - state_values)}"
        )

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
    case_id = f"{FAMILY_ID}.pilot.{record['case_slug']}"
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
        "split": "pilot",
        "world_seed": world_seed,
        "seats": [{"id": "analyst", "role": "analyst"}],
        "episode": {
            "max_logical_actions": 1,
            "termination": ["submitted", "invalid_submission"],
        },
        "visibility_policy": "commercial_state_public_evidence_private_oracle_v1",
        "payload": {
            "public_case": public_case,
            "response_vocabulary": {"state_values": list(state_values)},
            "oracle": record["oracle"],
        },
        "provenance": {
            "generator_id": "sanitized_commercial_state_import_v1",
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
    CommercialStatePlugin().validate_payload(case.payload)
    return case


def load_cases(
    *,
    case_slugs: tuple[str, ...] | None = None,
    manifest_path: Path | str = MANIFEST_PATH,
    cases_path: Path | str = CASES_PATH,
    source_catalog_path: Path | str = SOURCE_CATALOG_PATH,
) -> tuple[CaseManifest, ...]:
    manifest, records, _ = load_authoring_records(
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
            raise ValueError(f"unknown case slugs: {sorted(requested - found)}")
    state_values = tuple(manifest["state_value_vocabulary"])
    seed_by_slug = {
        record["case_slug"]: 410001 + index for index, record in enumerate(records)
    }
    return tuple(
        _case_manifest(
            record,
            state_values=state_values,
            world_seed=seed_by_slug[record["case_slug"]],
        )
        for record in selected
    )


__all__ = [
    "CASES_PATH",
    "MANIFEST_PATH",
    "PACK_ROOT",
    "SOURCE_CATALOG_PATH",
    "load_authoring_records",
    "load_cases",
]
