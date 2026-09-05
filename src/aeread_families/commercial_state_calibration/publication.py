"""Publish a sanitized, PR-ready projection of a commercial-state campaign.

Raw provider responses and complete event stores remain under the ignored run
root.  This module verifies the sealed result rows and receipt identities, then
publishes only parsed model actions, typed failures, measurements, route facts,
and content digests.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.contract import read_sealed as _read_sealed
from aeread.shared_runner.run.contract import sealed as _sealed
from aeread.shared_runner.run.contract import sha256_bytes as _sha256_bytes
from aeread.shared_runner.run.contract import sha256_json as _sha256
from aeread.shared_runner.run.publication import (
    PROHIBITED_PUBLIC_TEXT,
    SANITIZATION_DECLARATION,
    receipt_projection,
)
from aeread.shared_runner.run.publication import assert_public_payload as _assert_public_payload
from aeread.shared_runner.run.publication import atomic_publish as _atomic_publish
from aeread.shared_runner.run.publication import jsonl as _jsonl
from aeread.shared_runner.task.receipts import read_evaluation_receipt
from aeread.shared_runner.run.resolver import canonical_json_bytes

from .campaign import CAMPAIGN_ID, DEFAULT_CONTRACT_PATH, load_contract


PUBLICATION_SCHEMA_VERSION = "aeread.commercial_state_publication/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CAMPAIGN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID
__all__ = ["PROHIBITED_PUBLIC_TEXT", "publish_campaign_evidence", "main"]


def _publisher_implementation_sha256() -> str:
    return _sha256_bytes(Path(__file__).read_bytes())


def _inside(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("publication source path must be non-empty and relative")
    destination = (root / relative).resolve(strict=True)
    destination.relative_to(root.resolve(strict=True))
    if destination.is_symlink() or not destination.is_file():
        raise ValueError(f"publication source must be a regular file: {relative}")
    return destination


def _parsed_action(receipt_path: Path) -> Mapping[str, Any] | None:
    events_path = receipt_path.parent / "events.jsonl"
    if not events_path.is_file() or events_path.is_symlink():
        raise ValueError(f"receipt event log is unavailable: {events_path}")
    parsed: Mapping[str, Any] | None = None
    for raw_line in events_path.read_bytes().splitlines():
        event = json.loads(raw_line)
        if event.get("event_type") != "action_parsed":
            continue
        relative = event.get("payload_ref")
        digest = event.get("payload_sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise ValueError("action_parsed event lacks a payload identity")
        payload_path = _inside(receipt_path.parent, relative)
        payload = payload_path.read_bytes()
        if _sha256_bytes(payload) != digest:
            raise ValueError("action_parsed payload digest mismatch")
        value = json.loads(payload)
        candidate = value.get("parse_result", {}).get("action")
        if not isinstance(candidate, Mapping):
            raise ValueError("action_parsed payload lacks a parsed action")
        if parsed is not None:
            raise ValueError("single-action case produced multiple parsed actions")
        parsed = dict(candidate)
    return parsed


def _receipt_projection(
    *, row: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    return receipt_projection(receipt, campaign_cell_key=row["cell_key"])


def _transcript_projection(
    *,
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    parsed_action: Mapping[str, Any] | None,
) -> dict[str, Any]:
    model = contract["models"][row["model_id"]]
    usage = row.get("usage")
    if not isinstance(usage, Mapping):
        raise ValueError(f"campaign row lacks typed usage: {row['cell_key']}")
    failure = None
    if row.get("status") == "operational_failure":
        failure = {
            "failure_class": row.get("failure_class"),
            "failure_condition": row.get("failure_condition"),
        }
    return {
        "campaign_id": contract["campaign_id"],
        "cell_key": row["cell_key"],
        "model_id": row["model_id"],
        "case_slug": row["case_slug"],
        "case_sha256": row["case_sha256"],
        "inference_seed": row["inference_seed"],
        "expected_route": {
            "requested_model": model["requested_model"],
            "canonical_model": model["canonical_model"],
            "provider": model["provider"],
        },
        "status": row["status"],
        "inclusion_status": row["inclusion_status"],
        "route_verified": row["route_verified"],
        "elapsed_seconds": row["elapsed_seconds"],
        "usage": dict(usage),
        "parsed_output": parsed_action,
        "metrics": row.get("metrics"),
        "failure": failure,
        "source_receipt_sha256": row["receipt_sha256"],
        "replay_verified": row["replay_verified"],
    }


def _publication_summary(
    *,
    contract: Mapping[str, Any],
    source: Mapping[str, Any],
    transcripts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    started = int(source["provider_calls_started"])
    succeeded = int(source["provider_calls_succeeded"])
    failures = Counter(
        row["failure"]["failure_condition"]
        for row in transcripts
        if isinstance(row.get("failure"), Mapping)
    )
    return _sealed(
        {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "campaign_id": contract["campaign_id"],
            "source_stage": source["stage"],
            "source_summary_sha256": source["artifact_sha256"],
            "contract_sha256": _sha256(contract),
            "publisher_implementation_sha256": _publisher_implementation_sha256(),
            "status": source["status"],
            "claim_status": source["claim_status"],
            "attempt_index": source["attempt_index"],
            "planned_cells": source["planned_cells"],
            "completed_cells": source["completed_cells"],
            "measurement_invalid_cells": source["measurement_invalid_cells"],
            "operational_failure_cells": source["operational_failure_cells"],
            "failure_fraction": source["failure_fraction"],
            "failure_conditions": dict(sorted(failures.items())),
            "provider_calls_started": started,
            "provider_calls_succeeded": succeeded,
            "reported_cost_usd": source["total_cost_usd"],
            "provider_cost_complete": started == succeeded,
            "cost_qualifier": "exact" if started == succeeded else "lower_bound",
            "all_receipts_replayed": source["all_receipts_replayed"],
            "all_completed_routes_verified": source["all_completed_routes_verified"],
            "independent_cluster_count": source["independent_cluster_count"],
            "inferential_model_ranking_allowed": source[
                "inferential_model_ranking_allowed"
            ],
            "winner_claim_allowed": source["winner_claim_allowed"],
            "blockers": source["blockers"],
            "model_summaries": source["model_summaries"],
            "pairwise_contrasts": source["pairwise_contrasts"],
            "raw_provider_responses_included": False,
            "full_prompts_included": False,
            "model_reasoning_included": False,
            "complete_receipts_included": False,
        }
    )


def _readme(campaign_id: str) -> bytes:
    text = f"""# {campaign_id} evidence

This directory is a sanitized, PR-ready projection of the local campaign run.
It publishes parsed model outputs, typed failures, measurements, route and cost
facts, receipt identities, and digest-bound fact tables.

Complete provider payloads, prompts, event stores, and evaluation receipts are
not committed. They remain in the ignored local `runs/{campaign_id}/`
directory. `source_receipt_sha256` binds each projection to its authoritative
local receipt without exposing provider-account metadata.

This run is diagnostic. All cases belong to one source-archive cluster, and the
published summary does not support an inferential model ranking or winner claim.
"""
    return text.encode("utf-8")


def publish_campaign_evidence(
    *,
    campaign_root: Path = DEFAULT_CAMPAIGN_ROOT,
    publication_root: Path = DEFAULT_PUBLICATION_ROOT,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    if not campaign_root.is_dir() or campaign_root.is_symlink():
        raise ValueError("campaign root must be a real directory")
    if publication_root.exists() and (
        not publication_root.is_dir() or publication_root.is_symlink()
    ):
        raise ValueError("publication root must be a real directory")

    stage = (
        "variance_pilot"
        if (campaign_root / "variance_pilot" / "summary.json").exists()
        else "full_trajectory"
    )
    stage_root = campaign_root / stage
    source_summary = _read_sealed(stage_root / "summary.json")
    if source_summary.get("campaign_id") != CAMPAIGN_ID:
        raise ValueError("source summary campaign identity drifted")

    rows = [
        _read_sealed(path)
        for path in sorted((stage_root / "cells").glob("*/result.json"))
    ]
    if len(rows) != source_summary.get("planned_cells"):
        raise ValueError("publication requires every planned result row")

    transcripts: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for row in rows:
        receipt_path = _inside(campaign_root, row["receipt_path"])
        receipt = read_evaluation_receipt(receipt_path)
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"receipt identity drifted for {row['cell_key']}")
        parsed_action = _parsed_action(receipt_path) if row["status"] == "completed" else None
        transcripts.append(
            _transcript_projection(
                contract=contract, row=row, parsed_action=parsed_action
            )
        )
        receipts.append(_receipt_projection(row=row, receipt=receipt))

    analysis_root = stage_root / "analysis"
    source_fact_manifest = _read_sealed(analysis_root / "fact_manifest.json")
    payloads: dict[str, bytes] = {
        "README.md": _readme(contract["campaign_id"]),
        "reports/summary.json": canonical_json_bytes(
            _publication_summary(
                contract=contract,
                source=source_summary,
                transcripts=transcripts,
            )
        )
        + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(transcripts),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/fact_manifest.json": canonical_json_bytes(source_fact_manifest) + b"\n",
    }
    for table in ("profiles", "model_features", "benchmark_results"):
        metadata = source_fact_manifest["tables"][table]
        source_path = _inside(analysis_root, metadata["path"])
        payload = source_path.read_bytes()
        if _sha256_bytes(payload) != metadata["sha256"]:
            raise ValueError(f"source fact table digest drifted: {table}")
        payloads[f"tables/{metadata['path']}"] = payload

    for name, payload in payloads.items():
        _assert_public_payload(name, payload)
        _atomic_publish(publication_root / name, payload)

    row_counts = {
        "trajectories/sanitized.jsonl": len(transcripts),
        "receipts/projections.jsonl": len(receipts),
    }
    for table in source_fact_manifest["tables"].values():
        row_counts[f"tables/{table['path']}"] = table["row_count"]
    manifest = _sealed(
        {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "campaign_id": contract["campaign_id"],
            "source_stage": stage,
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_fact_manifest_sha256": source_fact_manifest["artifact_sha256"],
            "publisher_implementation_sha256": _publisher_implementation_sha256(),
            "files": {
                name: {
                    "sha256": _sha256_bytes(payload),
                    "bytes": len(payload),
                    "row_count": row_counts.get(name),
                }
                for name, payload in sorted(payloads.items())
            },
            "sanitization": dict(SANITIZATION_DECLARATION),
        }
    )
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    _assert_public_payload("publication_manifest.json", manifest_payload)
    _atomic_publish(publication_root / "publication_manifest.json", manifest_payload)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign-root",
        "--output-root",
        dest="campaign_root",
        type=Path,
        default=DEFAULT_CAMPAIGN_ROOT,
        help="ignored local campaign directory (legacy alias: --output-root)",
    )
    parser.add_argument(
        "--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    arguments = parser.parse_args(argv)
    result = publish_campaign_evidence(
        campaign_root=arguments.campaign_root,
        publication_root=arguments.publication_root,
        contract_path=arguments.contract,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CAMPAIGN_ROOT",
    "DEFAULT_PUBLICATION_ROOT",
    "PUBLICATION_SCHEMA_VERSION",
    "publish_campaign_evidence",
]
