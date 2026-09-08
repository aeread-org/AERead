"""Publish the sanitized route-refreshed objective-grounding campaign."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .objective_campaign_v2 import (
    CAMPAIGN_ID,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_RUN_ROOT,
    load_contract,
)
from .objective_campaign import _read_sealed
from .objective_publication import (
    PROHIBITED_PUBLIC_TEXT,
    _assert_public_payload,
    _atomic_publish,
    _audit_source,
    _benchmark_rows,
    _csv,
    _jsonl,
    _profile_rows,
    _receipt_projection,
    _sealed,
    _sha256,
    _sha256_bytes,
    _source_rows,
    _trajectory,
)


PUBLICATION_SCHEMA_VERSION = "aeread.datacenter_objective_publication/0.2"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID

README = """# Data-center V2 objective-grounding campaign, route panel V2

This directory is the sanitized, PR-ready projection of a six-cell route-panel
campaign on the bounded V2 data-center agreement-stack case. It is a new
campaign identity created after the V1 panel produced only operational
exclusions; it does not retry or replace any V1 cell.

Three new inference seeds are paired across two named open-source model routes.
Only the developer is live, and five deterministic counterparties enforce the
single complete calibrated package required by the exact-optimum reference.

The authoritative prompts, provider payloads, event stores, and complete
evaluation receipts remain under the ignored local
`runs/datacenter_development_v2_objective_grounding_v2/` directory. This
publication omits raw responses, reasoning, free-form negotiation messages,
and failure text. Receipt and event digests bind the projections to local
source evidence.

Operational failures are typed exclusions, never score zero. `observed_usage`
counts only successful provider calls sealed before terminal failure and is a
spend lower bound whenever any cell is excluded. One curated project cluster
supports objective-grounding and route-compatibility diagnosis only—not
population generalization, a model winner, or a causal model effect.
"""


def publish(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    publication_root: Path | str = DEFAULT_PUBLICATION_ROOT,
    _contract_loader: Callable[[Path | str], dict[str, Any]] = load_contract,
    _publication_schema_version: str = PUBLICATION_SCHEMA_VERSION,
    _public_summary_schema_version: str = (
        "aeread.datacenter_objective_public_summary/0.2"
    ),
    _fact_manifest_schema_version: str = (
        "aeread.datacenter_objective_fact_manifest/0.2"
    ),
    _readme: str = README,
    _publisher_path: Path | None = None,
) -> dict[str, Any]:
    contract = _contract_loader(contract_path)
    source_root = Path(run_root)
    destination = Path(publication_root)
    source_design = _read_sealed(source_root / "design.json")
    source_summary = _read_sealed(source_root / "live" / "summary.json")
    if source_summary["contract_sha256"] != _sha256(contract):
        raise ValueError("V2 source summary contract digest differs")
    if source_summary["design_sha256"] != source_design["artifact_sha256"]:
        raise ValueError("V2 source summary design digest differs")
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
    publisher_sha256 = _sha256_bytes((_publisher_path or Path(__file__)).read_bytes())
    observed_cost = sum(
        float(row["observed_usage"]["reported_cost_usd"])
        for row in trajectories
    )
    observed_successes = sum(
        int(row["observed_usage"]["successful_call_count"])
        for row in trajectories
    )
    summary = _sealed(
        {
            **{
                key: value
                for key, value in source_summary.items()
                if key != "artifact_sha256"
            },
            "schema_version": _public_summary_schema_version,
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
            "all_receipts_audited": len(receipts) == source_summary["planned_cells"],
            "all_completed_routes_verified": all(
                row["route_verified"]
                for row in trajectories
                if row["status"] == "completed"
            ),
            "observed_successful_provider_calls": observed_successes,
            "observed_reported_cost_usd": observed_cost,
            "observed_cost_qualifier": (
                "exact"
                if source_summary["operational_failure_cells"] == 0
                else "lower_bound"
            ),
            "complete_receipts_included": False,
            "full_prompts_included": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "free_form_negotiation_messages_included": False,
            "failure_messages_included": False,
        }
    )
    benchmark = _benchmark_rows(trajectories)
    benchmark_fields = (
        "campaign_id",
        "cell_key",
        "condition",
        "model_id",
        "inference_seed",
        "case_sha256",
        "inclusion_status",
        "record_kind",
        "metric",
        "value",
        "unit",
        "reportable",
        "termination_reason",
    )
    profiles = _profile_rows(contract, source_rows)
    profile_fields = (
        "campaign_id",
        "cell_key",
        "run_plan_id",
        "run_plan_sha256",
        "condition",
        "evaluation_block_kind",
        "live_profile_count",
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
        "max_output_tokens_per_action",
        "timeout_seconds_per_action",
        "max_action_attempts",
        "sdk_retries",
        "response_cache",
    )
    payloads: dict[str, bytes] = {
        "README.md": _readme.encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/benchmark_results.csv": _csv(benchmark, benchmark_fields),
        "tables/profiles.csv": _csv(profiles, profile_fields),
    }
    table_manifest = _sealed(
        {
            "schema_version": _fact_manifest_schema_version,
            "campaign_id": contract["campaign_id"],
            "source_truth": ["RunPlan", "CampaignCellResult", "EvaluationReceipt"],
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
            "schema_version": _publication_schema_version,
            "campaign_id": contract["campaign_id"],
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "source_fact_manifest_sha256": table_manifest["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
            "source_receipt_sha256s": [
                row["source_receipt_sha256"] for row in receipts
            ],
            "source_result_sha256s": [
                row["source_result_sha256"] for row in trajectories
            ],
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
                "free_form_negotiation_messages_included": False,
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
