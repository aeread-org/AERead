"""Publish sanitized evidence for the public GPT-OSS data-center add-on."""

from __future__ import annotations

import argparse
import csv
import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt

from .campaign import _read_sealed, _sealed, _sha256
from .public_cases import public_pack_sha256
from .public_gptoss_campaign import (
    CAMPAIGN_ID,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_RUN_ROOT,
    MODEL_ID,
    _cases_by_slug,
    _setup,
    load_contract,
)
from .publication import (
    PROHIBITED_PUBLIC_TEXT,
    _assert_public_payload,
    _atomic_publish,
    _receipt_path,
    _receipt_projection,
    _sha256_bytes,
    _verify_route,
)


PUBLICATION_SCHEMA_VERSION = "aeread.datacenter_terms_public_gptoss_publication/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID
HELPER_PATH = Path(__file__).with_name("publication.py")

README = """# Public-source data-center GPT-OSS add-on v1

This sanitized add-on applies one exact GPT-OSS 120B/CoreWeave fp4 OpenRouter
route to the same five public-primary-source cases, response schema, minimal-chat
harness, and three inference seeds as `datacenter_development_terms_public_v1`.
The predecessor's two routes were not rerun. The bridge is sealed to its case,
contract, design, live-summary, and public-manifest hashes.

All 15 GPT-OSS calls completed, were included, route-verified, and replayed.
Successful-call cost was exactly $0.0018843759. Median elapsed time was 18.06
seconds. GPT-OSS passed 12 of 15 hard gates and had mean primary score 0.5163.

All three failures were on the linked land/power/construction underwriting case.
Every seed selected fixed-price EPC treatment and asserted that the ground lease
survives power termination; two also treated the executed assignment as already
effective. Component means remained high, but the deterministic hard gate set
all three primary scores to zero because these selections could corrupt future
cash-flow, consent, and construction-risk underwriting.

Twelve of 15 three-model case/seed rows are reportable because three predecessor
Mistral calls were rate-limited. Within those 12 rows, GPT-OSS was never the sole
highest scorer; Qwen was highest in seven, Mistral in two, and three were ties.
This is descriptive only. Qwen and GPT-OSS both displayed hard-gate failures,
while Mistral's predecessor route had operational missingness.

These five filing clusters do not establish a model winner, inferential ranking,
population causal effect, or project generalization. Raw provider payloads,
prompts, reasoning, complete receipts, and failure messages remain in ignored
local run state.
"""


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _csv(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _source_rows(run_root: Path) -> tuple[dict[str, Any], ...]:
    paths = sorted((run_root / "live").glob("*/result.json"))
    if len(paths) != 15:
        raise ValueError("public GPT-OSS publication requires all 15 cell results")
    return tuple(_read_sealed(path) for path in paths)


def _trajectory(
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    receipt_path: Path,
) -> dict[str, Any]:
    model = contract["model"]
    expected_route = {
        "requested_model": model["requested_model"],
        "canonical_model": model["canonical_model"],
        "provider": model["provider"],
        "quantization": model["quantization"],
    }
    completed = row["status"] == "completed"
    route_verified = _verify_route(receipt_path, expected_route) if completed else False
    if completed and not route_verified:
        raise ValueError(f"completed GPT-OSS route is unverified: {row['cell_key']}")
    failure = row.get("failure")
    return {
        "campaign_id": CAMPAIGN_ID,
        "cell_key": row["cell_key"],
        "pair_key": row["pair_key"],
        "case_slug": row["case_slug"],
        "source_cluster_id": row["source_cluster_id"],
        "case_id": row["case_id"],
        "case_sha256": row["case_sha256"],
        "model_id": MODEL_ID,
        "inference_seed": row["inference_seed"],
        "expected_route": expected_route,
        "status": row["status"],
        "inclusion_status": row["inclusion_status"],
        "route_verified": route_verified,
        "elapsed_seconds": row["elapsed_seconds"],
        "usage": row["usage"],
        "parsed_output": row["parsed_output"],
        "metrics": row["metrics"],
        "failure": (
            {
                "failure_class": failure.get("failure_class"),
                "failure_condition": failure.get("failure_condition"),
            }
            if isinstance(failure, Mapping)
            else None
        ),
        "source_result_sha256": row["artifact_sha256"],
        "source_receipt_sha256": row["receipt_sha256"],
        "receipt_verified": True,
        "replay_verified": row["replay_verified"],
    }


def _benchmark_rows(
    trajectories: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    units = {
        "score": "ratio",
        "component_mean": "ratio",
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
    rows = []
    for trajectory in trajectories:
        base = {
            "campaign_id": CAMPAIGN_ID,
            "cell_key": trajectory["cell_key"],
            "pair_key": trajectory["pair_key"],
            "case_slug": trajectory["case_slug"],
            "source_cluster_id": trajectory["source_cluster_id"],
            "model_id": MODEL_ID,
            "inference_seed": trajectory["inference_seed"],
            "case_sha256": trajectory["case_sha256"],
            "inclusion_status": trajectory["inclusion_status"],
        }
        if trajectory["status"] != "completed":
            rows.append(
                {
                    **base,
                    "record_kind": "status",
                    "metric": trajectory["failure"]["failure_condition"],
                    "value": "",
                    "unit": "",
                    "reportable": False,
                }
            )
            continue
        values = {
            **{
                name: trajectory["metrics"][name]
                for name in units
                if name in trajectory["metrics"]
            },
            "elapsed_seconds": trajectory["elapsed_seconds"],
            "input_tokens": trajectory["usage"]["input_tokens"],
            "cached_input_tokens": trajectory["usage"]["cached_input_tokens"],
            "output_tokens": trajectory["usage"]["output_tokens"],
            "reported_cost_usd": trajectory["usage"]["reported_cost_usd"],
        }
        for metric, value in values.items():
            rows.append(
                {
                    **base,
                    "record_kind": "metric",
                    "metric": metric,
                    "value": value,
                    "unit": units[metric],
                    "reportable": True,
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
    design = _read_sealed(source_root / "design" / "summary.json")
    summary = _read_sealed(source_root / "live" / "summary.json")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("GPT-OSS source design contract differs")
    if summary["contract_sha256"] != _sha256(contract):
        raise ValueError("GPT-OSS source summary contract differs")
    source_rows = _source_rows(source_root)
    if {row["cell_key"] for row in source_rows} != {
        cell["cell_key"] for cell in design["cells"]
    }:
        raise ValueError("GPT-OSS publication cell set differs from sealed design")

    cases = _cases_by_slug()
    trajectories = []
    receipts = []
    for row in source_rows:
        setup = _setup(contract, row, cases)
        receipt_path = _receipt_path(source_root / "live" / row["cell_key"])
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"GPT-OSS receipt digest differs for {row['cell_key']}")
        receipts.append(_receipt_projection(receipt, row["cell_key"]))
        trajectories.append(_trajectory(contract, row, receipt_path=receipt_path))

    publisher_hash = _sha256_bytes(Path(__file__).read_bytes())
    helper_hash = _sha256_bytes(HELPER_PATH.read_bytes())
    public_summary = _sealed(
        {
            **{key: value for key, value in summary.items() if key != "artifact_sha256"},
            "schema_version": "aeread.datacenter_terms_public_gptoss_summary/0.1",
            "source_summary_sha256": summary["artifact_sha256"],
            "source_design_sha256": design["artifact_sha256"],
            "pack_sha256": public_pack_sha256(),
            "publisher_implementation_sha256": publisher_hash,
            "publisher_helper_sha256": helper_hash,
            "all_receipts_audited": len(receipts) == 15,
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
    benchmark = _benchmark_rows(trajectories)
    model = contract["model"]
    profiles = [
        {
            "campaign_id": CAMPAIGN_ID,
            "cell_key": row["cell_key"],
            "pair_key": row["pair_key"],
            "case_slug": row["case_slug"],
            "source_cluster_id": row["source_cluster_id"],
            "run_plan_id": row["run_plan_id"],
            "run_plan_sha256": row["run_plan_sha256"],
            "model_id": MODEL_ID,
            "profile_id": row["profile_id"],
            "inference_seed": row["inference_seed"],
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
            "response_cache": contract["execution"]["response_cache"],
        }
        for row in source_rows
    ]
    bridge_rows = [
        {
            "campaign_id": CAMPAIGN_ID,
            "pair_key": row["pair_key"],
            "case_slug": row["case_slug"],
            "source_cluster_id": row["source_cluster_id"],
            "inference_seed": row["inference_seed"],
            "bridge_reportable": row["bridge_reportable"],
            "mistral_score": (
                row["scores"].get("mistral32_deepinfra") if row["scores"] else None
            ),
            "qwen_score": (
                row["scores"].get("qwen3_235b_novita") if row["scores"] else None
            ),
            "gptoss_score": row["scores"].get(MODEL_ID) if row["scores"] else None,
            "mistral_hard_gate_pass": (
                row["hard_gate_pass"].get("mistral32_deepinfra")
                if row["hard_gate_pass"]
                else None
            ),
            "qwen_hard_gate_pass": (
                row["hard_gate_pass"].get("qwen3_235b_novita")
                if row["hard_gate_pass"]
                else None
            ),
            "gptoss_hard_gate_pass": (
                row["hard_gate_pass"].get(MODEL_ID) if row["hard_gate_pass"] else None
            ),
        }
        for row in summary["bridge_rows"]
    ]
    benchmark_fields = (
        "campaign_id", "cell_key", "pair_key", "case_slug", "source_cluster_id",
        "model_id", "inference_seed", "case_sha256", "inclusion_status",
        "record_kind", "metric", "value", "unit", "reportable",
    )
    profile_fields = (
        "campaign_id", "cell_key", "pair_key", "case_slug", "source_cluster_id",
        "run_plan_id", "run_plan_sha256", "model_id", "profile_id",
        "inference_seed", "provider", "requested_model", "canonical_model",
        "quantization", "access_class", "license_id", "harness",
        "reasoning_effort", "max_output_tokens", "timeout_seconds",
        "max_action_attempts", "sdk_retries", "response_cache",
    )
    bridge_fields = (
        "campaign_id", "pair_key", "case_slug", "source_cluster_id",
        "inference_seed", "bridge_reportable", "mistral_score", "qwen_score",
        "gptoss_score", "mistral_hard_gate_pass", "qwen_hard_gate_pass",
        "gptoss_hard_gate_pass",
    )
    payloads = {
        "README.md": README.encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(public_summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/benchmark_results.csv": _csv(benchmark, benchmark_fields),
        "tables/profiles.csv": _csv(profiles, profile_fields),
        "tables/three_model_bridge.csv": _csv(bridge_rows, bridge_fields),
    }
    fact_manifest = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_gptoss_facts/0.1",
            "campaign_id": CAMPAIGN_ID,
            "source_truth": ["RunPlan", "CampaignCellResult", "EvaluationReceipt"],
            "tables": {
                "benchmark_results": {
                    "path": "tables/benchmark_results.csv",
                    "row_count": len(benchmark),
                    "sha256": _sha256_bytes(payloads["tables/benchmark_results.csv"]),
                },
                "profiles": {
                    "path": "tables/profiles.csv",
                    "row_count": len(profiles),
                    "sha256": _sha256_bytes(payloads["tables/profiles.csv"]),
                },
                "three_model_bridge": {
                    "path": "tables/three_model_bridge.csv",
                    "row_count": len(bridge_rows),
                    "sha256": _sha256_bytes(payloads["tables/three_model_bridge.csv"]),
                },
            },
        }
    )
    payloads["tables/fact_manifest.json"] = canonical_json_bytes(fact_manifest) + b"\n"
    for name, payload in payloads.items():
        _assert_public_payload(name, payload)

    manifest = _sealed(
        {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "campaign_id": CAMPAIGN_ID,
            "source_summary_sha256": summary["artifact_sha256"],
            "source_design_sha256": design["artifact_sha256"],
            "source_fact_manifest_sha256": fact_manifest["artifact_sha256"],
            "pack_sha256": public_pack_sha256(),
            "bridge": contract["bridge"],
            "publisher_implementation_sha256": publisher_hash,
            "publisher_helper_sha256": helper_hash,
            "source_receipt_sha256s": [row["source_receipt_sha256"] for row in receipts],
            "source_result_sha256s": [row["source_result_sha256"] for row in trajectories],
            "files": {
                name: {"bytes": len(payload), "sha256": _sha256_bytes(payload)}
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
    args = parser.parse_args(argv)
    manifest = publish(
        contract_path=args.contract,
        run_root=args.run_root,
        publication_root=args.publication_root,
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
