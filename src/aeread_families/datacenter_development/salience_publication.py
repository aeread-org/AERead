"""Publish the sanitized paired counteroffer-salience campaign evidence."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.execution import EvidenceStore

from . import salience_campaign as campaign
from .objective_campaign import _read_sealed
from .objective_publication import (
    PROHIBITED_PUBLIC_TEXT,
    _assert_public_payload,
    _atomic_publish,
    _csv,
    _jsonl,
    _observed_usage,
    _receipt_path,
    _receipt_projection,
    _sealed,
    _sha256,
    _sha256_bytes,
    _verify_completed_route,
)


CAMPAIGN_ID = campaign.CAMPAIGN_ID
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID

README = """# Data-center counteroffer-salience diagnostic V1

This is the sanitized, PR-ready projection of a paired 20-cell diagnostic on
one curated land negotiation. Two named open-source routes and five fresh
inference seeds were each run under two conditions: the complete written
counteroffer alone, and the same counteroffer plus an explicit public
`purchase_price_cents` delta. The delta was derived only from the already
visible offer packages; no private counterparty policy was exposed.

All 20 cells completed, were included, and replayed from sealed evidence. All
10 matched model-and-seed pairs are reportable at assignment level. Nineteen
cells reached the counteroffer and nine pairs were exposure-qualified; one
full-package cell produced an invalid action before either arm's differing
second observation could be applied. The initial provider requests in every
pair were content-identical, so this pre-treatment divergence is retained as
provider nondeterminism rather than attributed to salience.

No cell adopted a counteroffer. All 10 assignment-level transitions, and all
nine exposure-qualified transitions, are neither adopted. The explicit-delta
condition had perfect negotiation-temporal compliance, while the full-package
condition contained the one pre-treatment invalid action. This result weighs
against a simple local salience explanation for the pinned failure, but it does
not establish a population effect or that salience never matters elsewhere.

Raw provider records, prompts, complete written terms, free-form messages, and
complete receipts remain in the ignored local run directory. This publication
contains typed verifier leaves, sanitized outcome projections, per-pair
transitions, route checks, usage, and source digests. It supports no population
generalization, causal claim, or model-winner claim.
"""


def _outcome_projection(outcome: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    history = outcome.get("public_history")
    history_rows = history if isinstance(history, list) else []
    developer_land_offers = [
        row
        for row in history_rows
        if isinstance(row, Mapping)
        and row.get("seat_id") == "developer"
        and row.get("agreement_key") == "land"
        and row.get("decision") == "offer"
    ]
    changed_fields: list[str] = []
    if len(developer_land_offers) >= 2:
        first = developer_land_offers[0].get("terms")
        second = developer_land_offers[1].get("terms")
        if isinstance(first, Mapping) and isinstance(second, Mapping):
            changed_fields = sorted(
                key
                for key in set(first) | set(second)
                if canonical_json_bytes(first.get(key))
                != canonical_json_bytes(second.get(key))
            )
    return {
        "salience_condition": outcome["salience_condition"],
        "stage_id": outcome["stage_id"],
        "required_sequence": outcome["required_sequence"],
        "termination_reason": outcome["termination_reason"],
        "temporal_violations": outcome["temporal_violations"],
        "prefix_completed": outcome["prefix_completed"],
        "executed_agreement_count": outcome["executed_agreement_count"],
        "exact_package_integrity": outcome["exact_package_integrity"],
        "counteroffer_opportunity_count": outcome[
            "counteroffer_opportunity_count"
        ],
        "counteroffer_adoption_count": outcome["counteroffer_adoption_count"],
        "counteroffer_adoption_rate": outcome["counteroffer_adoption_rate"],
        "intentional_resolution": outcome["intentional_resolution"],
        "public_history_row_count": len(history_rows),
        "developer_land_offer_count": len(developer_land_offers),
        "fields_changed_between_first_and_second_land_offer": changed_fields,
    }


def _initial_request_sha256(receipt_path: Path) -> str:
    evidence = EvidenceStore.audit_existing(receipt_path.parent)
    try:
        for event in evidence.read_events():
            if event.event_type != "provider_call_started":
                continue
            payload = evidence.read_event_payload(event)
            request = payload.get("request") if isinstance(payload, Mapping) else None
            if not isinstance(request, Mapping):
                raise ValueError("provider-call event lacks a request object")
            stable = {
                key: request.get(key)
                for key in (
                    "instructions",
                    "input_text",
                    "messages",
                    "model",
                    "output_schema",
                    "reasoning_effort",
                    "seed",
                    "temperature",
                    "top_p",
                    "max_output_tokens",
                )
            }
            return _sha256(stable)
    finally:
        evidence.close()
    raise ValueError("completed cell lacks a provider-call start event")


def _trajectory(
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    receipt_path: Path,
) -> dict[str, Any]:
    model = contract["models"][row["model_id"]]
    completed = row["status"] == "completed"
    route_verified, verified_call_count = (
        _verify_completed_route(
            receipt_path,
            requested_model=str(model["requested_model"]),
            canonical_model=str(model["canonical_model"]),
            route_provider=str(model["provider"]),
        )
        if completed
        else (False, 0)
    )
    if completed and not route_verified:
        raise ValueError(f"completed route could not be verified: {row['cell_key']}")
    failure = row.get("failure")
    return {
        "campaign_id": contract["campaign_id"],
        "cell_key": row["cell_key"],
        "pair_key": row["pair_key"],
        "condition": row["condition"],
        "model_id": row["model_id"],
        "case_id": row["case_id"],
        "case_sha256": row["case_sha256"],
        "inference_seed": row["inference_seed"],
        "evaluation_block_kind": row["evaluation_block_kind"],
        "live_profile_count": row["live_profile_count"],
        "expected_route": {
            "requested_model": model["requested_model"],
            "canonical_model": model["canonical_model"],
            "provider": model["provider"],
            "quantization": model["quantization"],
        },
        "status": row["status"],
        "inclusion_status": row["inclusion_status"],
        "route_verified": route_verified,
        "verified_openrouter_call_count": verified_call_count,
        "initial_provider_request_sha256": (
            _initial_request_sha256(receipt_path) if completed else None
        ),
        "elapsed_seconds": row["elapsed_seconds"],
        "observed_usage": _observed_usage(
            receipt_path, requested_model=str(model["requested_model"])
        ),
        "outcome": _outcome_projection(row.get("outcome")),
        "scores": row["scores"],
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
    rows: list[dict[str, Any]] = []
    for trajectory in trajectories:
        base = {
            "campaign_id": trajectory["campaign_id"],
            "cell_key": trajectory["cell_key"],
            "pair_key": trajectory["pair_key"],
            "condition": trajectory["condition"],
            "model_id": trajectory["model_id"],
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
                    "termination_reason": "",
                }
            )
            continue
        for leaf_id, score in trajectory["scores"].items():
            rows.append(
                {
                    **base,
                    "record_kind": "verifier_leaf",
                    "metric": leaf_id,
                    "value": score["value"],
                    "unit": score["unit"],
                    "reportable": True,
                    "termination_reason": trajectory["outcome"][
                        "termination_reason"
                    ],
                }
            )
    return tuple(rows)


def _profile_rows(
    contract: Mapping[str, Any], source_rows: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "campaign_id": contract["campaign_id"],
            "cell_key": row["cell_key"],
            "pair_key": row["pair_key"],
            "condition": row["condition"],
            "run_plan_id": row["run_plan_id"],
            "run_plan_sha256": row["run_plan_sha256"],
            "model_id": row["model_id"],
            "profile_id": contract["models"][row["model_id"]]["profile_id"],
            "inference_seed": row["inference_seed"],
            "provider": contract["models"][row["model_id"]]["provider"],
            "requested_model": contract["models"][row["model_id"]][
                "requested_model"
            ],
            "canonical_model": contract["models"][row["model_id"]][
                "canonical_model"
            ],
            "harness": contract["execution"]["harness"],
            "max_action_attempts": contract["execution"]["max_action_attempts"],
            "sdk_retries": contract["execution"]["sdk_retries"],
            "response_cache": contract["execution"]["response_cache"],
        }
        for row in source_rows
    )


def _paired_rows(
    contract: Mapping[str, Any], trajectories: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    indexed = {
        (row["model_id"], row["inference_seed"], row["condition"]): row
        for row in trajectories
    }
    rows: list[dict[str, Any]] = []
    for model_id in sorted(contract["models"]):
        for seed in contract["inference_seeds"]:
            full = indexed[(model_id, seed, "full_package")]
            delta = indexed[(model_id, seed, "explicit_delta")]
            usable = all(
                row["status"] == "completed"
                and row["inclusion_status"] == "included"
                for row in (full, delta)
            )
            full_score = (
                float(full["scores"]["counteroffer_adoption_rate"]["value"])
                if usable
                else None
            )
            delta_score = (
                float(delta["scores"]["counteroffer_adoption_rate"]["value"])
                if usable
                else None
            )
            transition = "missing_pair"
            if usable:
                transition = {
                    (0.0, 0.0): "neither_adopted",
                    (0.0, 1.0): "delta_only_adopted",
                    (1.0, 0.0): "full_only_adopted",
                    (1.0, 1.0): "both_adopted",
                }[(full_score, delta_score)]
            full_opportunities = (
                int(full["outcome"]["counteroffer_opportunity_count"])
                if usable
                else None
            )
            delta_opportunities = (
                int(delta["outcome"]["counteroffer_opportunity_count"])
                if usable
                else None
            )
            exposure_qualified = (
                usable
                and full_opportunities == 1
                and delta_opportunities == 1
            )
            rows.append(
                {
                    "campaign_id": contract["campaign_id"],
                    "pair_key": f"{model_id}__seed_{seed}",
                    "model_id": model_id,
                    "inference_seed": seed,
                    "full_package_status": full["status"],
                    "full_package_inclusion_status": full["inclusion_status"],
                    "explicit_delta_status": delta["status"],
                    "explicit_delta_inclusion_status": delta["inclusion_status"],
                    "pair_reportable": usable,
                    "initial_provider_request_match": (
                        usable
                        and full["initial_provider_request_sha256"] is not None
                        and full["initial_provider_request_sha256"]
                        == delta["initial_provider_request_sha256"]
                    ),
                    "full_package_opportunity_count": full_opportunities,
                    "explicit_delta_opportunity_count": delta_opportunities,
                    "exposure_qualified": exposure_qualified,
                    "full_package_adoption": full_score,
                    "explicit_delta_adoption": delta_score,
                    "transition": transition,
                    "exposure_transition": (
                        transition if exposure_qualified else "unexposed_pair"
                    ),
                }
            )
    return tuple(rows)


def publish(
    *,
    run_root: Path = campaign.DEFAULT_RUN_ROOT,
    publication_root: Path = DEFAULT_PUBLICATION_ROOT,
) -> dict[str, Any]:
    contract = campaign.load_contract(campaign.DEFAULT_CONTRACT_PATH)
    source_design = _read_sealed(run_root / "design.json")
    source_summary = _read_sealed(run_root / "live" / "summary.json")
    if source_summary["contract_sha256"] != _sha256(contract):
        raise ValueError("source summary contract digest differs")
    if source_summary["design_sha256"] != source_design["artifact_sha256"]:
        raise ValueError("source summary design digest differs")

    source_rows = tuple(
        _read_sealed(path)
        for path in sorted((run_root / "live").glob("*/result.json"))
    )
    expected = {cell["cell_key"] for cell in source_design["cells"]}
    if {row["cell_key"] for row in source_rows} != expected:
        raise ValueError("live cell set differs from sealed design")

    receipts: list[dict[str, Any]] = []
    trajectories: list[dict[str, Any]] = []
    for row in source_rows:
        setup = campaign._setup(contract, row)
        receipt_path = _receipt_path(run_root / "live" / row["cell_key"])
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"receipt digest differs for {row['cell_key']}")
        receipts.append(_receipt_projection(receipt, row["cell_key"]))
        trajectories.append(_trajectory(contract, row, receipt_path=receipt_path))

    publisher_sha256 = _sha256_bytes(Path(__file__).read_bytes())
    observed_cost = sum(
        float(row["observed_usage"]["reported_cost_usd"])
        for row in trajectories
    )
    public_summary = _sealed(
        {
            **{
                key: value
                for key, value in source_summary.items()
                if key != "artifact_sha256"
            },
            "schema_version": "aeread.datacenter_counteroffer_salience_public_summary/0.1",
            "publication_interpretation": "paired_public_delta_salience_diagnostic",
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
            "all_receipts_audited": len(receipts)
            == source_summary["planned_cells"],
            "all_completed_routes_verified": all(
                row["route_verified"]
                for row in trajectories
                if row["status"] == "completed"
            ),
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
            "complete_written_terms_included": False,
            "free_form_negotiation_messages_included": False,
            "failure_messages_included": False,
        }
    )
    benchmark = _benchmark_rows(trajectories)
    profiles = _profile_rows(contract, source_rows)
    pairs = _paired_rows(contract, trajectories)
    exposure_qualified_pairs = [row for row in pairs if row["exposure_qualified"]]
    public_summary = _sealed(
        {
            **{
                key: value
                for key, value in public_summary.items()
                if key != "artifact_sha256"
            },
            "initial_provider_requests_match_within_all_pairs": all(
                row["initial_provider_request_match"] for row in pairs
            ),
            "assignment_level_usable_pairs": sum(
                bool(row["pair_reportable"]) for row in pairs
            ),
            "counteroffer_exposed_cells": sum(
                int(row["outcome"]["counteroffer_opportunity_count"] == 1)
                for row in trajectories
                if row["outcome"] is not None
            ),
            "exposure_qualified_pairs": len(exposure_qualified_pairs),
            "unexposed_pairs": len(pairs) - len(exposure_qualified_pairs),
            "exposure_qualified_transition_counts": {
                name: sum(
                    row["exposure_transition"] == name
                    for row in exposure_qualified_pairs
                )
                for name in (
                    "neither_adopted",
                    "delta_only_adopted",
                    "full_only_adopted",
                    "both_adopted",
                )
            },
        }
    )
    benchmark_fields = (
        "campaign_id",
        "cell_key",
        "pair_key",
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
    profile_fields = (
        "campaign_id",
        "cell_key",
        "pair_key",
        "condition",
        "run_plan_id",
        "run_plan_sha256",
        "model_id",
        "profile_id",
        "inference_seed",
        "provider",
        "requested_model",
        "canonical_model",
        "harness",
        "max_action_attempts",
        "sdk_retries",
        "response_cache",
    )
    pair_fields = (
        "campaign_id",
        "pair_key",
        "model_id",
        "inference_seed",
        "full_package_status",
        "full_package_inclusion_status",
        "explicit_delta_status",
        "explicit_delta_inclusion_status",
        "pair_reportable",
        "initial_provider_request_match",
        "full_package_opportunity_count",
        "explicit_delta_opportunity_count",
        "exposure_qualified",
        "full_package_adoption",
        "explicit_delta_adoption",
        "transition",
        "exposure_transition",
    )
    payloads = {
        "README.md": README.encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(public_summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/benchmark_results.csv": _csv(benchmark, benchmark_fields),
        "tables/profiles.csv": _csv(profiles, profile_fields),
        "tables/paired_results.csv": _csv(pairs, pair_fields),
    }
    fact_manifest = _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_salience_fact_manifest/0.1",
            "campaign_id": contract["campaign_id"],
            "source_truth": [
                "RunPlan",
                "CampaignCellResult",
                "EvaluationReceipt",
                "ProviderRequestEvent",
            ],
            "tables": {
                "benchmark_results": {
                    "path": "tables/benchmark_results.csv",
                    "row_count": len(benchmark),
                    "sha256": _sha256_bytes(
                        payloads["tables/benchmark_results.csv"]
                    ),
                },
                "profiles": {
                    "path": "tables/profiles.csv",
                    "row_count": len(profiles),
                    "sha256": _sha256_bytes(payloads["tables/profiles.csv"]),
                },
                "paired_results": {
                    "path": "tables/paired_results.csv",
                    "row_count": len(pairs),
                    "sha256": _sha256_bytes(
                        payloads["tables/paired_results.csv"]
                    ),
                },
            },
        }
    )
    payloads["tables/fact_manifest.json"] = (
        canonical_json_bytes(fact_manifest) + b"\n"
    )
    for name, payload in payloads.items():
        _assert_public_payload(name, payload)
    manifest = _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_salience_publication/0.1",
            "campaign_id": contract["campaign_id"],
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "source_fact_manifest_sha256": fact_manifest["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
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
                "complete_written_terms_included": False,
                "failure_messages_included": False,
                "free_form_negotiation_messages_included": False,
                "full_prompts_included": False,
                "model_reasoning_included": False,
                "raw_provider_responses_included": False,
            },
        }
    )
    for name, payload in payloads.items():
        _atomic_publish(publication_root / name, payload)
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    _assert_public_payload("publication_manifest.json", manifest_payload)
    _atomic_publish(publication_root / "publication_manifest.json", manifest_payload)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=campaign.DEFAULT_RUN_ROOT)
    parser.add_argument(
        "--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT
    )
    args = parser.parse_args(argv)
    result = publish(run_root=args.run_root, publication_root=args.publication_root)
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PUBLICATION_ROOT",
    "PROHIBITED_PUBLIC_TEXT",
    "main",
    "publish",
]
