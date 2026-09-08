"""Publish sanitized evidence for the public clause-mechanism campaign."""

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
from .public_mechanism_campaign import (
    CAMPAIGN_ID,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_RUN_ROOT,
    _cases_by_slug,
    _setup,
    load_contract,
)
from .public_mechanism_cases import public_mechanism_pack_sha256
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
    "aeread.datacenter_terms_public_mechanism_publication/0.1"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID
HELPER_PATH = Path(__file__).with_name("publication.py")

README = """# Public data-center clause-mechanism campaign v1

This sanitized 54-cell OpenRouter campaign decomposes one public Denton
land/power/construction filing cluster into assignment-consent, coterminous
land-power, and change-order-adjustable GMP mechanisms. Each mechanism has a
baseline case and a paired case that adds one sentence: include only supported
actions and claims and omit rejected candidates. Evidence, hidden oracle,
authority, cutoff, title, and world seed are otherwise identical within pairs.

The panel uses three exact Apache-2.0 open-weight model/provider routes and three
inference seeds. Fifty-three cells completed, were included, route-verified, and
replayed. One affirm-only Mistral land-power cell was rate-limited and remains an
operational exclusion. Successful-call cost is a $0.0051079545 lower bound.

Baseline wording passed 24 of 27 hard gates. All three failures were in the GMP
mechanism: Qwen selected fixed-price EPC treatment in one seed and GPT-OSS did so
in two, even while identifying the change-order-adjustable GMP structure. The
affirm-only wording passed all 26 completed hard gates, rescuing all three paired
GMP failures with no hard-gate regressions.

Assignment and land-power baseline cases had no hard-gate failures. This means
decomposition removed the unsafe consent and cotermination selections observed
in the original integrated case; the remaining failure was a contradictory GMP
action-selection problem. Score effects outside GMP were mixed: affirm-only was
slightly negative for Mistral and the land-power mechanism, positive for Qwen and
GPT-OSS, and strongly positive for GMP because of the three hard-gate rescues.

All cases share one source cluster. Results diagnose these exact cases and routes;
they do not establish a population effect, independent-project generalization,
an inferential model ranking, or a winner. Raw prompts, provider payloads,
reasoning, complete receipts, and failure messages remain in ignored local run
state.
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
    if len(paths) != 54:
        raise ValueError("mechanism publication requires all 54 cell results")
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
        raise ValueError(f"completed mechanism route is unverified: {row['cell_key']}")
    failure = row.get("failure")
    return {
        "campaign_id": CAMPAIGN_ID,
        "cell_key": row["cell_key"],
        "pair_key": row["pair_key"],
        "case_slug": row["case_slug"],
        "mechanism_id": row["mechanism_id"],
        "wording_condition": row["wording_condition"],
        "source_cluster_id": row["source_cluster_id"],
        "world_seed": row["world_seed"],
        "case_id": row["case_id"],
        "case_sha256": row["case_sha256"],
        "model_id": row["model_id"],
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
            "mechanism_id": trajectory["mechanism_id"],
            "wording_condition": trajectory["wording_condition"],
            "source_cluster_id": trajectory["source_cluster_id"],
            "world_seed": trajectory["world_seed"],
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


def _paired_rows(summary: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = []
    for pair in summary["paired_wording_contrasts"]:
        deltas = pair["component_deltas"] or {}
        rows.append(
            {
                "campaign_id": CAMPAIGN_ID,
                "pair_key": pair["pair_key"],
                "mechanism_id": pair["mechanism_id"],
                "model_id": pair["model_id"],
                "inference_seed": pair["inference_seed"],
                "pair_reportable": pair["pair_reportable"],
                "baseline_cell_key": pair["baseline_cell_key"],
                "affirm_only_cell_key": pair["affirm_only_cell_key"],
                "baseline_score": pair["baseline_score"],
                "affirm_only_score": pair["affirm_only_score"],
                "score_delta": pair["score_delta"],
                "baseline_hard_gate_pass": pair["baseline_hard_gate_pass"],
                "affirm_only_hard_gate_pass": pair["affirm_only_hard_gate_pass"],
                "hard_gate_rescue": pair["hard_gate_rescue"],
                "hard_gate_regression": pair["hard_gate_regression"],
                "baseline_forbidden_selection_count": pair[
                    "baseline_forbidden_selection_count"
                ],
                "affirm_only_forbidden_selection_count": pair[
                    "affirm_only_forbidden_selection_count"
                ],
                "forbidden_selection_delta": pair["forbidden_selection_delta"],
                "state_accuracy_delta": deltas.get("state_accuracy"),
                "amount_accuracy_delta": deltas.get("amount_accuracy"),
                "required_action_recall_delta": deltas.get(
                    "required_action_recall"
                ),
                "required_claim_recall_delta": deltas.get(
                    "required_claim_recall"
                ),
                "evidence_coverage_delta": deltas.get("evidence_coverage"),
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
        raise ValueError("mechanism source design contract differs")
    if summary["contract_sha256"] != _sha256(contract):
        raise ValueError("mechanism source summary contract differs")
    source_rows = _source_rows(source_root)
    if {row["cell_key"] for row in source_rows} != {
        cell["cell_key"] for cell in design["cells"]
    }:
        raise ValueError("mechanism publication cells differ from sealed design")

    cases = _cases_by_slug()
    trajectories = []
    receipts = []
    for row in source_rows:
        setup = _setup(contract, row, cases)
        receipt_path = _receipt_path(source_root / "live" / row["cell_key"])
        receipt = dict(audit_family_receipt(setup=setup, receipt_path=receipt_path))
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"mechanism receipt digest differs for {row['cell_key']}")
        receipts.append(_receipt_projection(receipt, row["cell_key"]))
        trajectories.append(_trajectory(contract, row, receipt_path=receipt_path))

    publisher_hash = _sha256_bytes(Path(__file__).read_bytes())
    helper_hash = _sha256_bytes(HELPER_PATH.read_bytes())
    public_summary = _sealed(
        {
            **{key: value for key, value in summary.items() if key != "artifact_sha256"},
            "schema_version": "aeread.datacenter_terms_public_mechanism_summary/0.1",
            "source_summary_sha256": summary["artifact_sha256"],
            "source_design_sha256": design["artifact_sha256"],
            "pack_sha256": public_mechanism_pack_sha256(),
            "publisher_implementation_sha256": publisher_hash,
            "publisher_helper_sha256": helper_hash,
            "all_receipts_audited": len(receipts) == 54,
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
    pairs = _paired_rows(summary)
    profiles = [
        {
            "campaign_id": CAMPAIGN_ID,
            "cell_key": row["cell_key"],
            "pair_key": row["pair_key"],
            "case_slug": row["case_slug"],
            "mechanism_id": row["mechanism_id"],
            "wording_condition": row["wording_condition"],
            "world_seed": row["world_seed"],
            "model_id": row["model_id"],
            "profile_id": row["profile_id"],
            "inference_seed": row["inference_seed"],
            "provider": contract["models"][row["model_id"]]["provider"],
            "requested_model": contract["models"][row["model_id"]][
                "requested_model"
            ],
            "canonical_model": contract["models"][row["model_id"]][
                "canonical_model"
            ],
            "quantization": contract["models"][row["model_id"]]["quantization"],
            "harness": contract["execution"]["harness"],
            "reasoning_effort": contract["models"][row["model_id"]][
                "reasoning_effort"
            ],
            "max_output_tokens": contract["execution"]["max_output_tokens"],
            "timeout_seconds": contract["execution"]["timeout_seconds"],
            "max_action_attempts": contract["execution"]["max_action_attempts"],
            "sdk_retries": contract["execution"]["sdk_retries"],
            "response_cache": contract["execution"]["response_cache"],
        }
        for row in source_rows
    ]
    benchmark_fields = (
        "campaign_id", "cell_key", "pair_key", "case_slug", "mechanism_id",
        "wording_condition", "source_cluster_id", "world_seed", "model_id",
        "inference_seed", "case_sha256", "inclusion_status", "record_kind",
        "metric", "value", "unit", "reportable",
    )
    profile_fields = (
        "campaign_id", "cell_key", "pair_key", "case_slug", "mechanism_id",
        "wording_condition", "world_seed", "model_id", "profile_id",
        "inference_seed", "provider", "requested_model", "canonical_model",
        "quantization", "harness", "reasoning_effort", "max_output_tokens",
        "timeout_seconds", "max_action_attempts", "sdk_retries", "response_cache",
    )
    pair_fields = (
        "campaign_id", "pair_key", "mechanism_id", "model_id", "inference_seed",
        "pair_reportable", "baseline_cell_key", "affirm_only_cell_key",
        "baseline_score", "affirm_only_score", "score_delta",
        "baseline_hard_gate_pass", "affirm_only_hard_gate_pass",
        "hard_gate_rescue", "hard_gate_regression",
        "baseline_forbidden_selection_count",
        "affirm_only_forbidden_selection_count", "forbidden_selection_delta",
        "state_accuracy_delta", "amount_accuracy_delta",
        "required_action_recall_delta", "required_claim_recall_delta",
        "evidence_coverage_delta",
    )
    payloads = {
        "README.md": README.encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(public_summary) + b"\n",
        "trajectories/sanitized.jsonl": _jsonl(trajectories),
        "receipts/projections.jsonl": _jsonl(receipts),
        "tables/benchmark_results.csv": _csv(benchmark, benchmark_fields),
        "tables/profiles.csv": _csv(profiles, profile_fields),
        "tables/paired_wording_contrasts.csv": _csv(pairs, pair_fields),
    }
    fact_manifest = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_mechanism_facts/0.1",
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
                "paired_wording_contrasts": {
                    "path": "tables/paired_wording_contrasts.csv",
                    "row_count": len(pairs),
                    "sha256": _sha256_bytes(
                        payloads["tables/paired_wording_contrasts.csv"]
                    ),
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
            "pack_sha256": public_mechanism_pack_sha256(),
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
