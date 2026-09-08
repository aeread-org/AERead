"""Audit and publish sanitized projections of the three adoption campaigns."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt

from . import adoption_campaign as campaign_v1
from . import adoption_campaign_v2 as campaign_v2
from . import adoption_campaign_v3 as campaign_v3
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
VERSIONS = {
    "v1": {
        "campaign": campaign_v1,
        "interpretation": "instrumentation_preflight_initial_offer_confound",
        "readme": """# Data-center counteroffer-adoption preflight V1

This is the sanitized, PR-ready projection of the first 18-cell nested-depth
preflight. V1 required the live developer to invent a valid opening package
before any written counteroffer appeared. Most included cells therefore ended
before a counteroffer opportunity. Treat V1 as instrumentation evidence, not
as a counteroffer-adoption capability estimate.

The complete panel is retained: three stages by two named routes by three
inference seeds. Operational failures are exclusions, while model-produced
invalid actions remain included zeros. Raw provider records, prompts, free-form
messages, and complete receipts remain in the ignored local run directory.
All stages share one curated project and support no population, winner, or
causal claim.
""",
    },
    "v2": {
        "campaign": campaign_v2,
        "interpretation": "instrumentation_preflight_nullable_prose_mismatch",
        "readme": """# Data-center counteroffer-adoption preflight V2

This is the sanitized, PR-ready projection of the second complete 18-cell
preflight. V2 added a public, valid, nonexact starter package, removing the need
to invent opening terms. Both routes copied it, but the admitted schema allowed
null nonbinding offer prose while the parser rejected it. Treat V2 as a
schema-parser instrumentation finding, not as an adoption capability estimate.

V2 is a new full panel, not a selective retry of V1. Raw provider records,
prompts, free-form messages, and complete receipts remain in the ignored local
run directory. All stages share one curated project and support no population,
winner, or causal claim.
""",
    },
    "v3": {
        "campaign": campaign_v3,
        "interpretation": "scoreable_counteroffer_adoption_diagnostic",
        "readme": """# Data-center counteroffer-adoption diagnostic V3

This is the sanitized, PR-ready projection of the schema-aligned 18-cell
counteroffer-adoption depth diagnostic. The developer receives a public valid
nonexact starter package, then a controlled complete written counteroffer.
Nullable nonbinding offer prose is normalized; structured terms are never
changed. Every included V3 cell reached a genuine counteroffer opportunity.

Fifteen of 18 cells were included; three rate-limit failures remain exclusions.
One included cell copied and executed the exact land counteroffer. The other 14
repeated the one-field-different starter price and exhausted land negotiation.
This isolates adoption failure from initial-term invention and parser mismatch.

Raw provider records, prompts, terms, free-form messages, and complete receipts
remain in the ignored local run directory. Digests in this publication bind the
sanitized rows to those sources. The stages are correlated prefixes of one
curated project, so this is diagnostic evidence—not population generalization,
a model winner, or a causal depth effect.
""",
    },
}


def _campaign_setup(module: Any, contract: Mapping[str, Any], row: Mapping[str, Any]):
    return module._setup(contract, row)


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
    difference_fields: list[str] = []
    if len(developer_land_offers) >= 2:
        first = developer_land_offers[0].get("terms")
        second = developer_land_offers[1].get("terms")
        if isinstance(first, Mapping) and isinstance(second, Mapping):
            difference_fields = sorted(
                key
                for key in set(first) | set(second)
                if canonical_json_bytes(first.get(key))
                != canonical_json_bytes(second.get(key))
            )
    return {
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
        "fields_changed_between_first_and_second_land_offer": difference_fields,
    }


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
        "condition": row["condition"],
        "stage_id": row["stage_id"],
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


def _benchmark_rows(trajectories: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for trajectory in trajectories:
        base = {
            "campaign_id": trajectory["campaign_id"],
            "cell_key": trajectory["cell_key"],
            "stage_id": trajectory["stage_id"],
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
            "stage_id": row["stage_id"],
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


def publish_version(version: str) -> dict[str, Any]:
    if version not in VERSIONS:
        raise ValueError(f"unknown publication version: {version}")
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

    receipts: list[dict[str, Any]] = []
    trajectories: list[dict[str, Any]] = []
    for row in source_rows:
        setup = _campaign_setup(module, contract, row)
        receipt_path = _receipt_path(source_root / "live" / row["cell_key"])
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"{version}: receipt digest differs for {row['cell_key']}")
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
            "schema_version": f"aeread.datacenter_counteroffer_adoption_public_summary/0.{version[-1]}",
            "publication_interpretation": selection["interpretation"],
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
            "all_receipts_audited": len(receipts) == source_summary["planned_cells"],
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
            "free_form_negotiation_messages_included": False,
            "failure_messages_included": False,
        }
    )
    benchmark = _benchmark_rows(trajectories)
    profiles = _profile_rows(contract, source_rows)
    benchmark_fields = (
        "campaign_id", "cell_key", "stage_id", "model_id", "inference_seed",
        "case_sha256", "inclusion_status", "record_kind", "metric", "value",
        "unit", "reportable", "termination_reason",
    )
    profile_fields = (
        "campaign_id", "cell_key", "stage_id", "run_plan_id",
        "run_plan_sha256", "model_id", "profile_id", "inference_seed",
        "provider", "requested_model", "canonical_model", "harness",
        "max_action_attempts", "sdk_retries", "response_cache",
    )
    payloads = {
        "README.md": selection["readme"].encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(public_summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/benchmark_results.csv": _csv(benchmark, benchmark_fields),
        "tables/profiles.csv": _csv(profiles, profile_fields),
    }
    fact_manifest = _sealed(
        {
            "schema_version": f"aeread.datacenter_counteroffer_adoption_fact_manifest/0.{version[-1]}",
            "campaign_id": contract["campaign_id"],
            "source_truth": ["RunPlan", "CampaignCellResult", "EvaluationReceipt"],
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
    payloads["tables/fact_manifest.json"] = canonical_json_bytes(fact_manifest) + b"\n"
    for name, payload in payloads.items():
        _assert_public_payload(name, payload)
    manifest = _sealed(
        {
            "schema_version": f"aeread.datacenter_counteroffer_adoption_publication/0.{version[-1]}",
            "campaign_id": contract["campaign_id"],
            "source_summary_sha256": source_summary["artifact_sha256"],
            "source_design_sha256": source_design["artifact_sha256"],
            "source_fact_manifest_sha256": fact_manifest["artifact_sha256"],
            "publisher_implementation_sha256": publisher_sha256,
            "source_receipt_sha256s": [row["source_receipt_sha256"] for row in receipts],
            "source_result_sha256s": [row["source_result_sha256"] for row in trajectories],
            "files": {
                name: {"bytes": len(payload), "sha256": _sha256_bytes(payload)}
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
    parser.add_argument("--version", choices=("v1", "v2", "v3", "all"), default="all")
    args = parser.parse_args(argv)
    versions = tuple(VERSIONS) if args.version == "all" else (args.version,)
    result = {version: publish_version(version) for version in versions}
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PROHIBITED_PUBLIC_TEXT", "VERSIONS", "main", "publish_version"]
