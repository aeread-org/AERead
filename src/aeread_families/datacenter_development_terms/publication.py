"""Publish a sanitized projection of the data-center terms reliability panel."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .campaign import (
    CAMPAIGN_ID,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_RUN_ROOT,
    _route,
    load_contract,
)
from .runner import build_openrouter_setup


PUBLICATION_SCHEMA_VERSION = "aeread.datacenter_terms_publication/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID
PROHIBITED_PUBLIC_TEXT = (
    '"raw_response"',
    '"failure_message"',
    '"output_text"',
    '"user_id"',
    "authorization:",
    "api_key",
    "/users/",
)

README = """# Data-center development terms reliability v1

This directory is a sanitized, PR-ready projection of a ten-cell OpenRouter
reliability panel. Two exact model/provider routes received the same corrected
synthetic data-center agreement-state case under five paired inference seeds.

Complete provider payloads, prompts, event stores, and evaluation receipts are
not committed. They remain in the ignored local
`runs/datacenter_development_terms_reliability_v1/` directory. Receipt and event
digests bind this projection to that authoritative local evidence.

Operational failures remain typed exclusions and are not converted to zero.
Valid hard-gate failures remain scored model outcomes. Because all cells use one
synthetic project cluster, this panel measures route reliability and response
stability only; it does not support project-level generalization, inferential
model ranking, or a winner claim.
"""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: Any) -> str:
    return _sha256_bytes(canonical_json_bytes(value))


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": _sha256(core)}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read_sealed(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if value != _sealed(value):
        raise ValueError(f"artifact digest mismatch: {path}")
    return value


def _atomic_publish(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_file() and not path.is_symlink() and path.read_bytes() == payload:
            return
        raise ValueError(f"refusing to overwrite different publication bytes: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError(f"publication parent must not be a symlink: {path.parent}")
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _assert_public_payload(name: str, payload: bytes) -> None:
    text = payload.decode("utf-8").lower()
    matches = [token for token in PROHIBITED_PUBLIC_TEXT if token in text]
    if matches:
        raise ValueError(f"{name} contains prohibited public fields: {matches}")


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _csv(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _receipt_path(cell_root: Path) -> Path:
    matches = list(
        (cell_root / "evidence").glob(
            "runplan_*/tasks/*/attempts/*/evaluation_receipt.json"
        )
    )
    if len(matches) != 1:
        raise ValueError(f"live cell must contain exactly one receipt: {cell_root}")
    return matches[0]


def _verify_route(receipt_path: Path, expected: Mapping[str, Any]) -> bool:
    evidence = EvidenceStore.audit_existing(receipt_path.parent)
    selected: list[tuple[str | None, str | None]] = []
    try:
        for event in evidence.read_events():
            if event.event_type != "provider_call_succeeded":
                continue
            payload = evidence.read_event_payload(event)
            result = payload.get("provider_result") if isinstance(payload, Mapping) else None
            if not isinstance(result, Mapping):
                raise ValueError("successful provider event lacks a result")
            raw = result.get("raw_response")
            metadata = raw.get("openrouter_metadata") if isinstance(raw, Mapping) else None
            endpoints = metadata.get("endpoints") if isinstance(metadata, Mapping) else None
            available = endpoints.get("available") if isinstance(endpoints, Mapping) else None
            chosen = (
                [item for item in available if item.get("selected") is True]
                if isinstance(available, list)
                else []
            )
            if len(chosen) != 1:
                raise ValueError("successful provider event lacks one selected endpoint")
            selected.append((chosen[0].get("provider"), chosen[0].get("model")))
    finally:
        evidence.close()
    return selected == [(expected["provider"], expected["canonical_model"])]


def _source_rows(run_root: Path) -> tuple[dict[str, Any], ...]:
    paths = sorted((run_root / "live").glob("*/result.json"))
    if not paths:
        raise ValueError("campaign contains no live cell results")
    return tuple(_read_sealed(path) for path in paths)


def _audit_source(
    contract: Mapping[str, Any],
    run_root: Path,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], Path]]:
    controls = contract["execution"]
    audited: dict[str, tuple[dict[str, Any], Path]] = {}
    for row in rows:
        cell_key = str(row["cell_key"])
        if cell_key in audited:
            raise ValueError(f"duplicate live cell result: {cell_key}")
        model = contract["models"][row["model_id"]]
        setup = build_openrouter_setup(
            _route(model),
            seed=int(row["inference_seed"]),
            case_slug=str(contract["case_slug"]),
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
        )
        receipt_path = _receipt_path(run_root / "live" / cell_key)
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"receipt digest differs for {cell_key}")
        audited[cell_key] = (receipt, receipt_path)
    expected_keys = {
        f"{model_id}__seed_{seed}"
        for seed in contract["inference_seeds"]
        for model_id in contract["models"]
    }
    if set(audited) != expected_keys:
        raise ValueError("published live cell set differs from the frozen contract")
    return audited


def _trajectory(
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    receipt_path: Path,
) -> dict[str, Any]:
    model = contract["models"][row["model_id"]]
    expected_route = {
        "requested_model": model["requested_model"],
        "canonical_model": model["canonical_model"],
        "provider": model["provider"],
        "quantization": model["quantization"],
    }
    completed = row["status"] == "completed"
    route_verified = _verify_route(receipt_path, expected_route) if completed else False
    if completed and not route_verified:
        raise ValueError(f"completed route could not be verified: {row['cell_key']}")
    failure = row.get("failure")
    safe_failure = (
        {
            "failure_class": failure.get("failure_class"),
            "failure_condition": failure.get("failure_condition"),
        }
        if isinstance(failure, Mapping)
        else None
    )
    return {
        "campaign_id": contract["campaign_id"],
        "cell_key": row["cell_key"],
        "model_id": row["model_id"],
        "case_id": row["case_id"],
        "case_sha256": row["case_sha256"],
        "inference_seed": row["inference_seed"],
        "expected_route": expected_route,
        "status": row["status"],
        "inclusion_status": row["inclusion_status"],
        "route_verified": route_verified,
        "elapsed_seconds": row["elapsed_seconds"],
        "usage": row["usage"],
        "parsed_output": row["parsed_output"],
        "metrics": row["metrics"],
        "failure": safe_failure,
        "source_receipt_sha256": row["receipt_sha256"],
        "receipt_verified": True,
        "replay_verified": row["replay_verified"],
    }


def _receipt_projection(receipt: Mapping[str, Any], cell_key: str) -> dict[str, Any]:
    failure = receipt.get("failure")
    safe_failure = (
        {
            "failure_class": failure.get("failure_class"),
            "condition": failure.get("condition"),
        }
        if isinstance(failure, Mapping)
        else None
    )
    return {
        "campaign_cell_key": cell_key,
        "source_receipt_sha256": receipt["receipt_sha256"],
        "spec_version": receipt["spec_version"],
        "status": receipt["status"],
        "inclusion_status": receipt["inclusion_status"],
        "run_plan_id": receipt["run_plan_id"],
        "run_plan_sha256": receipt["run_plan_sha256"],
        "cell_id": receipt["cell_id"],
        "case_id": receipt["case_id"],
        "case_sha256": receipt["case_sha256"],
        "episode_id": receipt["episode_id"],
        "episode_attempt_id": receipt["episode_attempt_id"],
        "cluster_id": receipt["cluster_id"],
        "cluster_level": receipt["cluster_level"],
        "primary_leaf_id": receipt["primary_leaf_id"],
        "replay_level": receipt["replay_level"],
        "evidence": receipt["evidence"],
        "failure": safe_failure,
        "scores": receipt["scores"],
        "observability_limits": receipt["observability_limits"],
    }


def _benchmark_rows(
    contract: Mapping[str, Any],
    trajectories: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    fields: list[dict[str, Any]] = []
    metric_units = {
        "score": "ratio",
        "state_accuracy": "ratio",
        "amount_accuracy": "ratio",
        "required_action_recall": "ratio",
        "required_claim_recall": "ratio",
        "evidence_coverage": "ratio",
        "hard_gate_pass": "indicator",
        "elapsed_seconds": "seconds",
        "input_tokens": "tokens",
        "cached_input_tokens": "tokens",
        "output_tokens": "tokens",
        "reported_cost_usd": "usd",
    }
    for row in trajectories:
        base = {
            "campaign_id": contract["campaign_id"],
            "cell_key": row["cell_key"],
            "model_id": row["model_id"],
            "inference_seed": row["inference_seed"],
            "case_sha256": row["case_sha256"],
            "inclusion_status": row["inclusion_status"],
        }
        if row["status"] != "completed":
            fields.append(
                {
                    **base,
                    "record_kind": "status",
                    "metric": row["failure"]["failure_condition"],
                    "value": "",
                    "unit": "",
                    "reportable": False,
                }
            )
            continue
        values = {
            **{
                key: row["metrics"][key]
                for key in metric_units
                if key in row["metrics"]
            },
            "elapsed_seconds": row["elapsed_seconds"],
            "input_tokens": row["usage"]["input_tokens"],
            "cached_input_tokens": row["usage"]["cached_input_tokens"],
            "output_tokens": row["usage"]["output_tokens"],
            "reported_cost_usd": row["usage"]["reported_cost_usd"],
        }
        for metric, value in values.items():
            fields.append(
                {
                    **base,
                    "record_kind": "metric",
                    "metric": metric,
                    "value": value,
                    "unit": metric_units[metric],
                    "reportable": True,
                }
            )
    return tuple(fields)


def _profile_rows(
    contract: Mapping[str, Any],
    source_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for source in source_rows:
        model = contract["models"][source["model_id"]]
        rows.append(
            {
                "campaign_id": contract["campaign_id"],
                "cell_key": source["cell_key"],
                "run_plan_id": source["run_plan_id"],
                "run_plan_sha256": source["run_plan_sha256"],
                "model_id": source["model_id"],
                "profile_id": source["profile_id"],
                "inference_seed": source["inference_seed"],
                "provider": model["provider"],
                "requested_model": model["requested_model"],
                "canonical_model": model["canonical_model"],
                "quantization": model["quantization"],
                "access_class": model["access_class"],
                "license_id": model["license_id"],
                "harness": contract["execution"]["harness"],
                "reasoning_effort": model["reasoning_effort"],
                "max_output_tokens": contract["execution"]["max_output_tokens"],
                "timeout_seconds": contract["execution"]["timeout_seconds"],
                "max_action_attempts": contract["execution"]["max_action_attempts"],
                "sdk_retries": contract["execution"]["sdk_retries"],
            }
        )
    return tuple(rows)


def publish(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    publication_root: Path | str = DEFAULT_PUBLICATION_ROOT,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    source_root = Path(run_root)
    destination = Path(publication_root)
    source_summary = _read_sealed(source_root / "live" / "summary.json")
    if source_summary["contract_sha256"] != _sha256(contract):
        raise ValueError("source summary contract digest differs")
    source_rows = _source_rows(source_root)
    audited = _audit_source(contract, source_root, source_rows)
    trajectories = tuple(
        _trajectory(
            contract,
            row,
            receipt_path=audited[str(row["cell_key"])][1],
        )
        for row in source_rows
    )
    receipts = tuple(
        _receipt_projection(audited[str(row["cell_key"])][0], str(row["cell_key"]))
        for row in source_rows
    )
    summary = _sealed(
        {
            **{
                key: value
                for key, value in source_summary.items()
                if key != "artifact_sha256"
            },
            "schema_version": "aeread.datacenter_terms_public_summary/0.1",
            "source_summary_sha256": source_summary["artifact_sha256"],
            "publisher_implementation_sha256": _sha256_bytes(Path(__file__).read_bytes()),
            "all_completed_routes_verified": all(
                row["route_verified"]
                for row in trajectories
                if row["status"] == "completed"
            ),
            "complete_receipts_included": False,
            "full_prompts_included": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "failure_messages_included": False,
        }
    )
    benchmark = _benchmark_rows(contract, trajectories)
    benchmark_fields = (
        "campaign_id",
        "cell_key",
        "model_id",
        "inference_seed",
        "case_sha256",
        "inclusion_status",
        "record_kind",
        "metric",
        "value",
        "unit",
        "reportable",
    )
    profiles = _profile_rows(contract, source_rows)
    profile_fields = (
        "campaign_id",
        "cell_key",
        "run_plan_id",
        "run_plan_sha256",
        "model_id",
        "profile_id",
        "inference_seed",
        "provider",
        "requested_model",
        "canonical_model",
        "quantization",
        "access_class",
        "license_id",
        "harness",
        "reasoning_effort",
        "max_output_tokens",
        "timeout_seconds",
        "max_action_attempts",
        "sdk_retries",
    )
    payloads: dict[str, bytes] = {
        "README.md": README.encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/benchmark_results.csv": _csv(benchmark, benchmark_fields),
        "tables/profiles.csv": _csv(profiles, profile_fields),
    }
    table_manifest = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_fact_manifest/0.1",
            "campaign_id": contract["campaign_id"],
            "source_truth": ["RunPlan", "EvaluationReceipt"],
            "projection_semantics": (
                "deterministic campaign projection; sealed local receipts remain authoritative"
            ),
            "tables": {
                "benchmark_results": {
                    "path": "benchmark_results.csv",
                    "row_count": len(benchmark),
                    "sha256": _sha256_bytes(payloads["tables/benchmark_results.csv"]),
                },
                "profiles": {
                    "path": "profiles.csv",
                    "row_count": len(profiles),
                    "sha256": _sha256_bytes(payloads["tables/profiles.csv"]),
                },
            },
        }
    )
    payloads["tables/fact_manifest.json"] = canonical_json_bytes(table_manifest) + b"\n"
    for name, payload in payloads.items():
        _assert_public_payload(name, payload)
    row_counts = {
        "trajectories/sanitized.jsonl": len(trajectories),
        "receipts/projections.jsonl": len(receipts),
        "tables/benchmark_results.csv": len(benchmark),
        "tables/profiles.csv": len(profiles),
    }
    manifest = _sealed(
        {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "campaign_id": contract["campaign_id"],
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_fact_manifest_sha256": table_manifest["artifact_sha256"],
            "publisher_implementation_sha256": _sha256_bytes(Path(__file__).read_bytes()),
            "source_receipt_sha256s": [row["source_receipt_sha256"] for row in receipts],
            "files": {
                name: {
                    "bytes": len(payload),
                    "row_count": row_counts.get(name),
                    "sha256": _sha256_bytes(payload),
                }
                for name, payload in sorted(payloads.items())
            },
            "sanitization": {
                "complete_receipts_included": False,
                "failure_messages_included": False,
                "full_prompts_included": False,
                "model_reasoning_included": False,
                "raw_provider_responses_included": False,
            },
        }
    )
    for name, payload in payloads.items():
        _atomic_publish(destination / name, payload)
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    _assert_public_payload("publication_manifest.json", manifest_payload)
    _atomic_publish(destination / "publication_manifest.json", manifest_payload)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT)
    arguments = parser.parse_args(argv)
    manifest = publish(
        contract_path=arguments.contract,
        run_root=arguments.run_root,
        publication_root=arguments.publication_root,
    )
    print(canonical_json_bytes(manifest).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PUBLICATION_ROOT",
    "PROHIBITED_PUBLIC_TEXT",
    "PUBLICATION_SCHEMA_VERSION",
    "main",
    "publish",
]
