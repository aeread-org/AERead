"""Publish sanitized evidence for the indicator-map integrated campaign v5."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt

from .campaign import _read_sealed, _sealed, _sha256
from .public_integrated_v4_publication import (
    _cell_rows as _base_cell_rows,
    _csv,
    _jsonl,
    _pair_rows as _base_pair_rows,
)
from .public_integrated_v5_campaign import (
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
    "aeread.datacenter_terms_public_integrated_v5_publication/0.1"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID
HELPER_PATH = Path(__file__).with_name("publication.py")

README = """# Indicator-map public integrated campaign v5

This sanitized, PR-ready projection contains an 18-cell model-to-model
data-center agreement-state campaign: three independent SEC project clusters,
three fresh stability seeds, and two pinned Apache-2.0 open-weight routes. Both
routes received the same corrected evidence and hidden oracle through the
minimal-chat harness. Candidate actions, claims, and evidence IDs were encoded
as complete boolean classifier maps, then normalized to canonical arrays before
deterministic scoring. The frozen run used no retries, cache, or fallback.

All 18 cells completed, were included, route-verified, and replayed, making all
nine case-seed pairs reportable. Exact campaign cost was $0.0106847829. Qwen on
Google passed the hard gate 9/9 with mean score 0.9586. Mistral on DeepInfra
passed 3/9 with mean score 0.3333. The aggregate Qwen-minus-Mistral score delta
is +0.6253, but it is descriptive only.

The result is case-dependent. Qwen scored 0.9091 versus Mistral 0 on all three
Black Pearl seeds and 1.0 versus 0 on all three Polaris seeds. Mistral scored
1.0 versus Qwen 0.9667 on all three Horizon seeds. Mistral selected one
forbidden claim in each Black Pearl output and a different forbidden claim in
each Polaris output; Polaris also omitted one required action. Qwen passed every
hard gate but missed five Black Pearl amount values and one Horizon state.

Each of the six model-by-project groups produced one unique normalized output
across its three seeds. The seeds therefore show exact within-route stability,
not additional independent project evidence. With only three independent
project clusters and sign-changing case effects, this campaign does not support
an inferential model ranking, winner, project-population generalization, or
causal effect. Full prompts, provider payloads, model reasoning, and complete
receipts remain in ignored local run state.
"""


def _source_rows(run_root: Path) -> tuple[dict[str, Any], ...]:
    paths = sorted((run_root / "live").glob("*/result.json"))
    if len(paths) != 18:
        raise ValueError("integrated v5 publication requires all 18 cell results")
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
    if row["status"] != "completed":
        raise ValueError(f"integrated v5 source cell is incomplete: {row['cell_key']}")
    if not _verify_route(receipt_path, expected_route):
        raise ValueError(f"completed integrated v5 route is unverified: {row['cell_key']}")
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
        "route_verified": True,
        "elapsed_seconds": row["elapsed_seconds"],
        "usage": row["usage"],
        "parsed_output": row["parsed_output"],
        "metrics": row["metrics"],
        "failure": None,
        "source_result_sha256": row["artifact_sha256"],
        "source_receipt_sha256": row["receipt_sha256"],
        "receipt_verified": True,
        "replay_verified": row["replay_verified"],
    }


def _output_stability(
    trajectories: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    groups: dict[tuple[str, str], list[str]] = {}
    for row in trajectories:
        key = (row["model_id"], row["case_slug"])
        digest = hashlib.sha256(
            canonical_json_bytes(row["parsed_output"])
        ).hexdigest()
        groups.setdefault(key, []).append(digest)
    return tuple(
        {
            "campaign_id": CAMPAIGN_ID,
            "model_id": model_id,
            "case_slug": case_slug,
            "seed_count": len(hashes),
            "unique_output_count": len(set(hashes)),
            "exact_repeat_across_seeds": len(set(hashes)) == 1,
            "output_sha256s": sorted(set(hashes)),
        }
        for (model_id, case_slug), hashes in sorted(groups.items())
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
        raise ValueError("integrated v5 source design contract differs")
    if summary["contract_sha256"] != contract_hash:
        raise ValueError("integrated v5 source summary contract differs")
    source_rows = _source_rows(source_root)
    if {row["cell_key"] for row in source_rows} != {
        cell["cell_key"] for cell in design["cells"]
    }:
        raise ValueError("integrated v5 publication cells differ from sealed design")

    cases = _cases_by_slug()
    trajectory_list = []
    receipts = []
    for row in source_rows:
        setup = _setup(contract, row, cases)
        receipt_path = _receipt_path(source_root / "live" / row["cell_key"])
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"integrated v5 receipt digest differs: {row['cell_key']}")
        receipts.append(_receipt_projection(receipt, row["cell_key"]))
        trajectory_list.append(_trajectory(contract, row, receipt_path=receipt_path))
    trajectories = tuple(trajectory_list)
    stability = _output_stability(trajectories)

    publisher_hash = _sha256_bytes(Path(__file__).read_bytes())
    helper_hash = _sha256_bytes(HELPER_PATH.read_bytes())
    public_summary = _sealed(
        {
            **{key: value for key, value in summary.items() if key != "artifact_sha256"},
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v5_public_summary/0.1"
            ),
            "source_summary_sha256": summary["artifact_sha256"],
            "source_design_sha256": design["artifact_sha256"],
            "publisher_implementation_sha256": publisher_hash,
            "publisher_helper_sha256": helper_hash,
            "all_receipts_audited": len(receipts) == 18,
            "all_completed_routes_verified": all(
                row["route_verified"] for row in trajectories
            ),
            "model_case_group_count": len(stability),
            "model_case_groups_with_exact_seed_repeats": sum(
                row["exact_repeat_across_seeds"] for row in stability
            ),
            "independent_analysis_unit_count": 3,
            "stability_seed_count_per_model_case": 3,
            "aggregate_qwen_minus_mistral_mean_score": (
                summary["model_route_summaries"][1]["mean_score"]
                - summary["model_route_summaries"][0]["mean_score"]
            ),
            "comparison_disposition": (
                "descriptive_case_dependent_three_project_clusters"
            ),
            "complete_receipts_included": False,
            "full_prompts_included": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "failure_messages_included": False,
        }
    )
    cell_rows = tuple(
        {**row, "campaign_id": CAMPAIGN_ID}
        for row in _base_cell_rows(trajectories)
    )
    pair_rows = tuple(
        {**row, "campaign_id": CAMPAIGN_ID}
        for row in _base_pair_rows(summary)
    )
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
    stability_fields = (
        "campaign_id", "model_id", "case_slug", "seed_count",
        "unique_output_count", "exact_repeat_across_seeds", "output_sha256s",
    )
    payloads = {
        "README.md": README.encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(public_summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/cell_results.csv": _csv(cell_rows, cell_fields),
        "tables/paired_contrasts.csv": _csv(pair_rows, pair_fields),
        "tables/profiles.csv": _csv(profile_rows, profile_fields),
        "tables/output_stability.csv": _csv(stability, stability_fields),
    }
    fact_manifest = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_integrated_v5_facts/0.1",
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
                    ("tables/output_stability.csv", stability),
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
