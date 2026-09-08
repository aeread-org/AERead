"""Publish sanitized V1/V2 counteroffer action-schema evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.execution import EvidenceStore

from . import action_schema_campaign as campaign_v1
from . import action_schema_campaign_v2 as campaign_v2
from .affordance_publication import (
    _benchmark_rows,
    _changed_fields,
    _initial_request_sha256,
    _profile_rows,
)
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


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = Path(__file__).with_name("affordance_publication.py")
VERSIONS = {
    "v1": {
        "campaign": campaign_v1,
        "interpretation": "instrumentation_preflight_ambiguous_opening_offer_id",
        "readme": """# Data-center counteroffer action-schema preflight V1

This is the sanitized projection of the first 20-cell broad-versus-dedicated
action-schema panel on one curated land negotiation. Both arms used identical
profiles, prompt text, schema catalogs, and first-request content. The intended
treatment occurred only after a formal public counteroffer.

V1 did not qualify that comparison. Nineteen cells completed and one rate-limit
failure remains excluded. Seventeen included cells produced an invalid opening
action before any counteroffer: each returned a non-null offer ID even though
none existed. Nine also returned null terms; eight returned a terms object. The
two cells that reached and adopted a counteroffer occurred on different paired
seeds, leaving zero exposure-qualified matched pairs.

Treat V1 as an instrumentation finding, not an action-schema effect estimate.
Raw provider records, prompts, terms, free-form text, and complete receipts
remain in the ignored local run directory. This publication retains typed
outcomes, safe first-action shape labels, exclusions, route checks, and source
digests. It supports no population, causal, or model-winner claim.
""",
    },
    "v2": {
        "campaign": campaign_v2,
        "interpretation": "qualified_explicit_opening_contract_schema_diagnostic",
        "readme": """# Data-center counteroffer action-schema diagnostic V2

This is the sanitized projection of a fresh 20-cell successor to V1. It keeps
the cases, formal counteroffer, routes, schema contrast, and execution controls,
but replaces the ambiguous opening instruction with an explicit field-by-field
opening action contract. Five fresh seeds form a complete new panel; V2 is not
a retry of V1 failures.

Fourteen cells completed and were included; six rate-limit failures remain
typed exclusions. Every included cell reached the formal counteroffer, accepted
it by public ID, signed, and executed the exact package. Six matched pairs were
usable—five on one route and one on the throttled route—and all six adopted
under both the shared multi-action schema and dedicated acceptance-only schema.
No dedicated-only transition was observed.

Within this single-project panel, narrowing the post-counter schema added no
observed adoption benefit once the opening contract was explicit. Cross-version
improvement is descriptive because the prompt changed. Raw provider records,
prompts, terms, free-form text, and complete receipts remain local. This result
supports no population, causal, or model-winner claim.
""",
    },
}


def _outcome_projection(outcome: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    history = outcome.get("public_history")
    history_rows = history if isinstance(history, list) else []
    developer_rows = [
        row
        for row in history_rows
        if isinstance(row, Mapping) and row.get("seat_id") == "developer"
    ]
    developer_offers = [row for row in developer_rows if row.get("decision") == "offer"]
    changed_fields: list[str] = []
    if len(developer_offers) >= 2:
        first = developer_offers[0].get("terms")
        second = developer_offers[1].get("terms")
        if isinstance(first, Mapping) and isinstance(second, Mapping):
            changed_fields = _changed_fields(first, second)
    return {
        "schema_condition": outcome["schema_condition"],
        "stage_id": outcome["stage_id"],
        "termination_reason": outcome["termination_reason"],
        "temporal_violations": outcome["temporal_violations"],
        "prefix_completed": outcome["prefix_completed"],
        "exact_package_integrity": outcome["exact_package_integrity"],
        "counteroffer_opportunity_count": outcome[
            "counteroffer_opportunity_count"
        ],
        "counteroffer_adoption_count": outcome["counteroffer_adoption_count"],
        "counteroffer_adoption_rate": outcome["counteroffer_adoption_rate"],
        "reference_acceptance_count": outcome["reference_acceptance_count"],
        "reference_acceptance_used": outcome["reference_acceptance_used"],
        "public_history_row_count": len(history_rows),
        "developer_decision_sequence": [
            str(row.get("decision")) for row in developer_rows
        ],
        "developer_offer_count": len(developer_offers),
        "fields_changed_between_first_and_second_offer": changed_fields,
    }


def _first_action_shape(receipt_path: Path) -> dict[str, Any] | None:
    evidence = EvidenceStore.audit_existing(receipt_path.parent)
    try:
        for event in evidence.read_events():
            if event.event_type != "provider_call_succeeded":
                continue
            payload = evidence.read_event_payload(event)
            result = payload.get("provider_result") if isinstance(payload, Mapping) else None
            text = result.get("output_text") if isinstance(result, Mapping) else None
            try:
                action = json.loads(text) if isinstance(text, str) else None
            except json.JSONDecodeError:
                action = None
            if not isinstance(action, Mapping):
                return {"json_object": False}

            def state(field: str) -> str:
                if field not in action:
                    return "absent"
                value = action[field]
                if value is None:
                    return "null"
                if isinstance(value, Mapping):
                    return "object"
                if isinstance(value, str):
                    return "string"
                return type(value).__name__

            return {
                "json_object": True,
                "keys": sorted(str(key) for key in action),
                "decision": (
                    str(action.get("decision"))
                    if isinstance(action.get("decision"), str)
                    else None
                ),
                "offer_id_state": state("offer_id"),
                "message_state": state("message"),
                "terms_state": state("terms"),
            }
    finally:
        evidence.close()
    return None


def _trajectory(
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    receipt_path: Path,
) -> dict[str, Any]:
    model = contract["models"][row["model_id"]]
    completed = row["status"] == "completed"
    route_verified, call_count = (
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
    try:
        first_request_sha256 = _initial_request_sha256(receipt_path)
    except ValueError:
        first_request_sha256 = None
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
        "verified_openrouter_call_count": call_count,
        "initial_provider_request_sha256": first_request_sha256,
        "first_action_shape": _first_action_shape(receipt_path),
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


def _paired_rows(
    contract: Mapping[str, Any], trajectories: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    indexed = {
        (row["model_id"], row["inference_seed"], row["condition"]): row
        for row in trajectories
    }
    transitions = {
        (0.0, 0.0): "neither_adopted",
        (0.0, 1.0): "dedicated_only_adopted",
        (1.0, 0.0): "shared_only_adopted",
        (1.0, 1.0): "both_adopted",
    }
    rows = []
    for model_id in sorted(contract["models"]):
        for seed in contract["inference_seeds"]:
            shared = indexed[(model_id, seed, "shared_offer_schema")]
            dedicated = indexed[(model_id, seed, "dedicated_accept_schema")]
            usable = all(
                row["status"] == "completed"
                and row["inclusion_status"] == "included"
                for row in (shared, dedicated)
            )
            shared_score = (
                float(shared["scores"]["counteroffer_adoption_rate"]["value"])
                if usable
                else None
            )
            dedicated_score = (
                float(
                    dedicated["scores"]["counteroffer_adoption_rate"]["value"]
                )
                if usable
                else None
            )
            transition = (
                transitions[(shared_score, dedicated_score)]
                if usable
                else "missing_pair"
            )
            exposure_qualified = usable and all(
                row["outcome"]["counteroffer_opportunity_count"] == 1
                for row in (shared, dedicated)
            )
            rows.append(
                {
                    "campaign_id": contract["campaign_id"],
                    "pair_key": f"{model_id}__seed_{seed}",
                    "model_id": model_id,
                    "inference_seed": seed,
                    "shared_status": shared["status"],
                    "shared_inclusion_status": shared["inclusion_status"],
                    "dedicated_status": dedicated["status"],
                    "dedicated_inclusion_status": dedicated["inclusion_status"],
                    "pair_reportable": usable,
                    "initial_provider_request_match": (
                        shared["initial_provider_request_sha256"] is not None
                        and shared["initial_provider_request_sha256"]
                        == dedicated["initial_provider_request_sha256"]
                    ),
                    "exposure_qualified": exposure_qualified,
                    "shared_adoption": shared_score,
                    "dedicated_adoption": dedicated_score,
                    "transition": transition,
                }
            )
    return tuple(rows)


def publish_version(version: str) -> dict[str, Any]:
    selection = VERSIONS[version]
    module = selection["campaign"]
    contract = module.load_contract(module.DEFAULT_CONTRACT_PATH)
    source_root = Path(module.DEFAULT_RUN_ROOT)
    destination = REPOSITORY_ROOT / "evidence" / module.CAMPAIGN_ID
    source_design = _read_sealed(source_root / "design.json")
    source_summary = _read_sealed(source_root / "live" / "summary.json")
    if source_summary["contract_sha256"] != _sha256(contract):
        raise ValueError(f"{version}: source summary contract digest differs")
    if source_summary["design_sha256"] != source_design["artifact_sha256"]:
        raise ValueError(f"{version}: source summary design digest differs")
    source_rows = tuple(
        _read_sealed(path)
        for path in sorted((source_root / "live").glob("*/result.json"))
    )
    expected = {cell["cell_key"] for cell in source_design["cells"]}
    if {row["cell_key"] for row in source_rows} != expected:
        raise ValueError(f"{version}: live cell set differs from sealed design")

    receipts = []
    trajectories = []
    for row in source_rows:
        setup = module._setup(contract, row)
        receipt_path = _receipt_path(source_root / "live" / row["cell_key"])
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"{version}: receipt digest differs for {row['cell_key']}")
        receipts.append(_receipt_projection(receipt, row["cell_key"]))
        trajectories.append(_trajectory(contract, row, receipt_path=receipt_path))

    benchmark = _benchmark_rows(trajectories)
    profiles = _profile_rows(contract, source_rows)
    pairs = _paired_rows(contract, trajectories)
    publisher_sha256 = _sha256_bytes(Path(__file__).read_bytes())
    helper_sha256 = _sha256_bytes(HELPER_PATH.read_bytes())
    observed_cost = sum(
        float(row["observed_usage"]["reported_cost_usd"])
        for row in trajectories
    )
    transition_counts = dict(
        sorted(Counter(str(row["transition"]) for row in pairs).items())
    )
    qualified = [row for row in pairs if row["exposure_qualified"]]
    qualified_transitions = dict(
        sorted(Counter(str(row["transition"]) for row in qualified).items())
    )
    opening_invalid = [
        row
        for row in trajectories
        if row["outcome"] is not None
        and row["outcome"]["termination_reason"] == "invalid_action"
        and row["outcome"]["public_history_row_count"] == 0
    ]
    public_summary = _sealed(
        {
            **{
                key: value
                for key, value in source_summary.items()
                if key != "artifact_sha256"
            },
            "schema_version": f"aeread.datacenter_counteroffer_action_schema_public_summary/0.{version[-1]}",
            "publication_interpretation": selection["interpretation"],
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
            "publisher_helper_sha256": helper_sha256,
            "all_receipts_audited": len(receipts)
            == source_summary["planned_cells"],
            "all_completed_routes_verified": all(
                row["route_verified"]
                for row in trajectories
                if row["status"] == "completed"
            ),
            "paired_initial_request_matches": sum(
                bool(row["initial_provider_request_match"]) for row in pairs
            ),
            "assignment_level_usable_pairs": sum(
                bool(row["pair_reportable"]) for row in pairs
            ),
            "counteroffer_exposed_cells": sum(
                row["outcome"] is not None
                and row["outcome"]["counteroffer_opportunity_count"] == 1
                for row in trajectories
            ),
            "exposure_qualified_pairs": len(qualified),
            "paired_transition_counts_published": transition_counts,
            "exposure_qualified_transition_counts": qualified_transitions,
            "opening_invalid_action_cells": len(opening_invalid),
            "opening_non_null_offer_id_cells": sum(
                row["first_action_shape"] is not None
                and row["first_action_shape"].get("offer_id_state") == "string"
                for row in opening_invalid
            ),
            "opening_null_terms_cells": sum(
                row["first_action_shape"] is not None
                and row["first_action_shape"].get("terms_state") == "null"
                for row in opening_invalid
            ),
            "opening_object_terms_cells": sum(
                row["first_action_shape"] is not None
                and row["first_action_shape"].get("terms_state") == "object"
                for row in opening_invalid
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
    benchmark_fields = (
        "campaign_id", "cell_key", "pair_key", "condition", "model_id",
        "inference_seed", "case_sha256", "inclusion_status", "record_kind",
        "metric", "value", "unit", "reportable", "termination_reason",
    )
    profile_fields = (
        "campaign_id", "cell_key", "pair_key", "condition", "run_plan_id",
        "run_plan_sha256", "model_id", "profile_id", "inference_seed",
        "provider", "requested_model", "canonical_model", "harness",
        "max_action_attempts", "sdk_retries", "response_cache",
    )
    pair_fields = (
        "campaign_id", "pair_key", "model_id", "inference_seed",
        "shared_status", "shared_inclusion_status", "dedicated_status",
        "dedicated_inclusion_status", "pair_reportable",
        "initial_provider_request_match", "exposure_qualified",
        "shared_adoption", "dedicated_adoption", "transition",
    )
    payloads = {
        "README.md": selection["readme"].encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(public_summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/benchmark_results.csv": _csv(benchmark, benchmark_fields),
        "tables/profiles.csv": _csv(profiles, profile_fields),
        "tables/paired_results.csv": _csv(pairs, pair_fields),
    }
    fact_manifest = _sealed(
        {
            "schema_version": f"aeread.datacenter_counteroffer_action_schema_fact_manifest/0.{version[-1]}",
            "campaign_id": contract["campaign_id"],
            "source_truth": [
                "RunPlan", "CampaignCellResult", "EvaluationReceipt",
                "ProviderRequestEvent", "ProviderResultShape",
            ],
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
                "paired_results": {
                    "path": "tables/paired_results.csv",
                    "row_count": len(pairs),
                    "sha256": _sha256_bytes(payloads["tables/paired_results.csv"]),
                },
            },
        }
    )
    payloads["tables/fact_manifest.json"] = canonical_json_bytes(fact_manifest) + b"\n"
    for name, payload in payloads.items():
        _assert_public_payload(name, payload)
    manifest = _sealed(
        {
            "schema_version": f"aeread.datacenter_counteroffer_action_schema_publication/0.{version[-1]}",
            "campaign_id": contract["campaign_id"],
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "source_fact_manifest_sha256": fact_manifest["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
            "publisher_helper_sha256": helper_sha256,
            "source_receipt_sha256s": [row["source_receipt_sha256"] for row in receipts],
            "source_result_sha256s": [row["source_result_sha256"] for row in trajectories],
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
        _atomic_publish(destination / name, payload)
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    _assert_public_payload("publication_manifest.json", manifest_payload)
    _atomic_publish(destination / "publication_manifest.json", manifest_payload)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v1", "v2", "all"), default="all")
    args = parser.parse_args(argv)
    versions = tuple(VERSIONS) if args.version == "all" else (args.version,)
    result = {version: publish_version(version) for version in versions}
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PROHIBITED_PUBLIC_TEXT", "VERSIONS", "main", "publish_version"]
