"""Publish sanitized evidence for the provider-order diagnostic v11."""

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
from .public_integrated_v11_campaign import (
    CAMPAIGN_ID,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_RUN_ROOT,
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


PUBLICATION_SCHEMA_VERSION = (
    "aeread.datacenter_terms_public_integrated_v11_publication/0.1"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID
HELPER_PATH = Path(__file__).with_name("publication.py")

README = """# Provider-order diagnostic campaign v11

This sanitized, PR-ready projection runs three independent SEC-grounded
data-center project clusters after making numeric units explicit in every case
prompt. One fresh predeclared seed paired two pinned Apache-2.0 open-weight
routes through the same minimal-chat harness and complete boolean indicator-map
schema. DeepInfra used a predeclared Tydal, Lake Mariner, then Helios order with
a 30-second post-attempt cooldown; Google retained Helios, Lake Mariner, then
Tydal and ran concurrently. The frozen full panel used no retries, cache, or
provider fallback.

Five of six cells completed, were included, route-verified, and replayed. Every
completed cell scored 1.0 and passed every hard gate. Qwen on Google completed
all three projects. Mistral on DeepInfra completed Tydal first and Helios third;
its second-position Lake Mariner call returned a typed rate-limit exclusion
with no model output or reported usage. That failure remains operational
missingness rather than a zero score. Successful-call cost is a $0.00347697405
lower bound.

Helios and Tydal are valid reportable pairs and both tied. Both Tydal routes
returned the visible 22nd-day invoice term. Lake Mariner has no model-to-model
contrast because its paired Mistral cell is missing; Qwen retained the
unit-explicit base-dollar and 750 MW representation. A separately qualified
Parasail route was rejected before inference at zero reported cost and was not
substituted.

Moving Tydal from third to first changed it from missing in V9/V10 to a perfect
completion, while Lake failed second and Helios then completed third. This rules
out a Tydal-specific failure and a deterministic third-call failure. It supports
intermittent DeepInfra availability as the operational diagnosis, without
establishing a causal order effect.

This campaign expands mechanism coverage and supplies descriptive diagnostics.
It does not establish a model winner, inferential ranking, project-population
generalization, or causal effect. Full prompts, provider payloads, model
reasoning, complete receipts, and verbose failure messages remain in ignored
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
    if len(paths) != 6:
        raise ValueError("integrated v11 publication requires all six cell results")
    return tuple(_read_sealed(path) for path in paths)


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
        raise ValueError(f"completed integrated v11 route is unverified: {row['cell_key']}")
    failure = row.get("failure")
    return {
        "campaign_id": CAMPAIGN_ID,
        "cell_key": row["cell_key"],
        "pair_key": row["pair_key"],
        "case_slug": row["case_slug"],
        "source_cluster_id": row["source_cluster_id"],
        "world_seed": row["world_seed"],
        "case_id": row["case_id"],
        "case_sha256": row["case_sha256"],
        "model_id": row["model_id"],
        "inference_seed": row["inference_seed"],
        "schema_mode": row["schema_mode"],
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


def _cell_rows(
    trajectories: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows = []
    for trajectory in trajectories:
        metrics = trajectory.get("metrics") or {}
        usage = trajectory.get("usage") or {}
        failure = trajectory.get("failure") or {}
        rows.append(
            {
                "campaign_id": CAMPAIGN_ID,
                "cell_key": trajectory["cell_key"],
                "pair_key": trajectory["pair_key"],
                "case_slug": trajectory["case_slug"],
                "source_cluster_id": trajectory["source_cluster_id"],
                "model_id": trajectory["model_id"],
                "inference_seed": trajectory["inference_seed"],
                "schema_mode": trajectory["schema_mode"],
                "status": trajectory["status"],
                "inclusion_status": trajectory["inclusion_status"],
                "route_verified": trajectory["route_verified"],
                "replay_verified": trajectory["replay_verified"],
                "score": metrics.get("score"),
                "hard_gate_pass": metrics.get("hard_gate_pass"),
                "forbidden_action_count": len(metrics.get("forbidden_actions", [])),
                "forbidden_claim_count": len(metrics.get("forbidden_claims", [])),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "reported_cost_usd": usage.get("reported_cost_usd"),
                "failure_class": failure.get("failure_class"),
                "failure_condition": failure.get("failure_condition"),
            }
        )
    return tuple(rows)


def _pair_rows(summary: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "campaign_id": CAMPAIGN_ID,
            "pair_key": pair["pair_key"],
            "case_slug": pair["case_slug"],
            "source_cluster_id": pair["source_cluster_id"],
            "inference_seed": pair["inference_seed"],
            "pair_reportable": pair["pair_reportable"],
            "mistral_score": (
                pair["model_scores"].get("mistral32_deepinfra")
                if pair["model_scores"]
                else None
            ),
            "qwen_score": (
                pair["model_scores"].get("qwen3_235b_google")
                if pair["model_scores"]
                else None
            ),
            "qwen_minus_mistral": pair["qwen_minus_mistral"],
            "hard_gate_transition": pair["hard_gate_transition"],
        }
        for pair in summary["paired_case_seed_contrasts"]
    )


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
    contract_hash = _sha256(contract)
    if design["contract_sha256"] != contract_hash:
        raise ValueError("integrated v11 source design contract differs")
    if summary["contract_sha256"] != contract_hash:
        raise ValueError("integrated v11 source summary contract differs")
    source_rows = _source_rows(source_root)
    if {row["cell_key"] for row in source_rows} != {
        cell["cell_key"] for cell in design["cells"]
    }:
        raise ValueError("integrated v11 publication cells differ from sealed design")

    cases = _cases_by_slug()
    trajectories = []
    receipts = []
    for row in source_rows:
        setup = _setup(contract, row, cases)
        receipt_path = _receipt_path(source_root / "live" / row["cell_key"])
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"integrated v11 receipt digest differs: {row['cell_key']}")
        receipts.append(_receipt_projection(receipt, row["cell_key"]))
        trajectories.append(_trajectory(contract, row, receipt_path=receipt_path))

    publisher_hash = _sha256_bytes(Path(__file__).read_bytes())
    helper_hash = _sha256_bytes(HELPER_PATH.read_bytes())
    public_summary = _sealed(
        {
            **{key: value for key, value in summary.items() if key != "artifact_sha256"},
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v11_public_summary/0.1"
            ),
            "source_summary_sha256": summary["artifact_sha256"],
            "source_design_sha256": design["artifact_sha256"],
            "publisher_implementation_sha256": publisher_hash,
            "publisher_helper_sha256": helper_hash,
            "all_receipts_audited": len(receipts) == 6,
            "all_completed_routes_verified": all(
                row["route_verified"]
                for row in trajectories
                if row["status"] == "completed"
            ),
            "operational_missingness_finding": {
                "model_id": "mistral32_deepinfra",
                "provider": "DeepInfra",
                "case_slug": (
                    "lake-mariner-lease-commencement-prepaid-rent-and-land"
                ),
                "provider_queue_position": 2,
                "observed_condition": "rate_limit",
                "affected_cells": 1,
                "model_output_available": False,
                "reported_usage_available": False,
            },
            "provider_order_finding": {
                "provider": "DeepInfra",
                "cooldown_seconds_after_attempt": 30.0,
                "ordered_outcomes": [
                    {
                        "position": 1,
                        "case_slug": "tydal-open-book-epc-governance-and-risk",
                        "status": "completed",
                        "score": 1.0,
                    },
                    {
                        "position": 2,
                        "case_slug": (
                            "lake-mariner-lease-commencement-prepaid-rent-and-land"
                        ),
                        "status": "rate_limit",
                        "score": None,
                    },
                    {
                        "position": 3,
                        "case_slug": "helios-phased-capacity-revenue-and-draws",
                        "status": "completed",
                        "score": 1.0,
                    },
                ],
                "tydal_specific_failure_supported": False,
                "deterministic_third_call_failure_supported": False,
                "causal_effect_allowed": False,
                "disposition": "intermittent_provider_availability_supported",
            },
            "completed_cell_findings": {
                "mistral_helios": "perfect_score",
                "mistral_tydal": "perfect_score_corrected_invoice_payment_day_22",
                "qwen_helios": "perfect_score",
                "qwen_lake_mariner": "perfect_score_unit_contract_observed",
                "qwen_tydal": "perfect_score_corrected_invoice_payment_day_22",
            },
            "answerability_correction_verified": {
                **summary["answerability_correction"],
                "observed_values": {
                    "mistral32_deepinfra": 22.0,
                    "qwen3_235b_google": 22.0,
                },
                "observed_scores": {
                    "mistral32_deepinfra": 1.0,
                    "qwen3_235b_google": 1.0,
                },
                "replay_verified": True,
                "disposition": "corrected_tydal_pair_valid_for_interpretation",
            },
            "numeric_unit_contract_observed": {
                **summary["numeric_unit_correction"],
                "observed_model_ids": ["qwen3_235b_google"],
                "observed_base_currency_values": {
                    "prepaid_rent_received": 90000000.0,
                    "current_deferred_rent": 58200000.0,
                    "noncurrent_deferred_rent": 23300000.0,
                    "remaining_deferred_rent": 81500000.0,
                },
                "observed_conditional_power_access_gross_mw": 750.0,
                "observed_scores": {"qwen3_235b_google": 1.0},
                "replay_verified": True,
                "cross_route_current_run_verified": False,
                "disposition": "qwen_valid_mistral_operationally_missing",
            },
            "alternate_route_finding": {
                **summary["alternate_route_qualification"],
                "substituted_into_campaign": False,
            },
            "comparison_disposition": (
                "helios_and_tydal_pairs_tied_lake_pair_operationally_missing"
            ),
            "complete_receipts_included": False,
            "full_prompts_included": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "failure_messages_included": False,
        }
    )
    cell_rows = _cell_rows(trajectories)
    pair_rows = _pair_rows(summary)
    profile_rows = tuple(
        {
            "campaign_id": CAMPAIGN_ID,
            "model_id": model_id,
            "profile_id": model["profile_id"],
            "provider": model["provider"],
            "requested_model": model["requested_model"],
            "canonical_model": model["canonical_model"],
            "quantization": model["quantization"],
            "license_id": model["license_id"],
            "harness": contract["execution"]["harness"],
            "schema_mode": contract["execution"]["schema_mode"],
            "max_output_tokens": contract["execution"]["max_output_tokens"],
            "max_action_attempts": contract["execution"]["max_action_attempts"],
            "sdk_retries": contract["execution"]["sdk_retries"],
            "response_cache": contract["execution"]["response_cache"],
            "provider_fallbacks": contract["execution"]["provider_fallbacks"],
        }
        for model_id, model in contract["models"].items()
    )
    cell_fields = (
        "campaign_id", "cell_key", "pair_key", "case_slug", "source_cluster_id",
        "model_id", "inference_seed", "schema_mode", "status", "inclusion_status",
        "route_verified", "replay_verified", "score", "hard_gate_pass",
        "forbidden_action_count", "forbidden_claim_count", "input_tokens",
        "output_tokens", "reported_cost_usd", "failure_class", "failure_condition",
    )
    pair_fields = (
        "campaign_id", "pair_key", "case_slug", "source_cluster_id",
        "inference_seed", "pair_reportable", "mistral_score", "qwen_score",
        "qwen_minus_mistral", "hard_gate_transition",
    )
    profile_fields = (
        "campaign_id", "model_id", "profile_id", "provider", "requested_model",
        "canonical_model", "quantization", "license_id", "harness", "schema_mode",
        "max_output_tokens", "max_action_attempts", "sdk_retries", "response_cache",
        "provider_fallbacks",
    )
    payloads = {
        "README.md": README.encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(public_summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/cell_results.csv": _csv(cell_rows, cell_fields),
        "tables/paired_contrasts.csv": _csv(pair_rows, pair_fields),
        "tables/profiles.csv": _csv(profile_rows, profile_fields),
    }
    fact_manifest = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v11_facts/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "source_truth": ["RunPlan", "CampaignCellResult", "EvaluationReceipt"],
            "tables": {
                name.removeprefix("tables/").removesuffix(".csv"): {
                    "path": name,
                    "row_count": len(rows),
                    "sha256": _sha256_bytes(payloads[name]),
                }
                for name, rows in (
                    ("tables/cell_results.csv", cell_rows),
                    ("tables/paired_contrasts.csv", pair_rows),
                    ("tables/profiles.csv", profile_rows),
                )
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
            "pack_sha256": design["pack_sha256"],
            "publisher_implementation_sha256": publisher_hash,
            "publisher_helper_sha256": helper_hash,
            "source_receipt_sha256s": [
                row["source_receipt_sha256"] for row in receipts
            ],
            "source_result_sha256s": [
                row["source_result_sha256"] for row in trajectories
            ],
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
