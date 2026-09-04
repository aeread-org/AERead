"""Publish a sanitized Housing backend-campaign qualification bundle."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.analysis.research import (
    deserialize_evaluation_receipt,
    export_canonical_fact_tables,
)
from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .backend_campaign import load_contract, route_table
from .model_sensitivity import _read_sealed, build_setups


QUALIFICATION_SCHEMA_VERSION = "aeread.housing_backend_qualification/0.4"
TRAJECTORY_SCHEMA_VERSION = "aeread.housing_trajectory_examples/0.3"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {
        **core,
        "artifact_sha256": _sha256_bytes(canonical_json_bytes(core)),
    }


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(
                f"refusing to replace different published evidence: {path}"
            )
        return
    path.write_bytes(payload)


def _write_immutable_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(
                f"refusing to replace different published evidence: {path}"
            )
        return
    path.write_bytes(payload)


def _csv_bytes(*, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _artifact_payload(attempt_dir: Path, payload_ref: str) -> Mapping[str, Any]:
    if not payload_ref.startswith("artifacts/sha256/"):
        raise ValueError("event payload is not content-addressed")
    path = attempt_dir / payload_ref
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("event artifact payload must be an object")
    return value


def _attempt_dir(
    *, live_root: Path, row: Mapping[str, Any], design: Mapping[str, Any]
) -> tuple[Path, Mapping[str, Any]]:
    matches = [
        plan
        for plan in design["plans"]
        if plan["config_id"] == row["config_id"]
        and plan["condition_id"] == row["condition_id"]
        and (
            "world_seed" not in plan
            or plan["world_seed"] == row["world_seed"]
        )
        and (
            "replicate_index" not in plan
            or plan["replicate_index"] == row["replicate_index"]
        )
    ]
    if len(matches) != 1:
        raise ValueError("live row does not map to exactly one frozen design cell")
    plan = matches[0]
    receipt_candidates = list(
        (
            live_root
            / row["config_id"]
            / row["condition_id"]
            / "evidence"
            / plan["run_plan_id"]
            / "tasks"
        ).glob("*/attempts/*/evaluation_receipt.json")
    )
    receipt_matches = [
        (path, receipt)
        for path in receipt_candidates
        for receipt in (read_evaluation_receipt(path),)
        if receipt["cell_id"] == row["cell_id"]
    ]
    if len(receipt_matches) != 1:
        raise ValueError("live cell must contain exactly one evaluation receipt")
    receipt_path, receipt = receipt_matches[0]
    return receipt_path.parent, receipt


def _project_attempt(
    *, live_root: Path, row: Mapping[str, Any], design: Mapping[str, Any]
) -> dict[str, Any]:
    attempt_dir, receipt = _attempt_dir(live_root=live_root, row=row, design=design)
    if receipt["receipt_sha256"] != row["receipt_sha256"]:
        raise ValueError("live result and evaluation receipt digests differ")
    with EvidenceStore.audit_existing(attempt_dir) as store:
        events = store.read_events()
    seal = json.loads((attempt_dir / "events.jsonl.sealed.json").read_bytes())
    if seal != receipt["evidence"]:
        raise ValueError("evaluation receipt and evidence seal differ")

    phase_order: list[str] = []
    action_outcomes: collections.Counter[str] = collections.Counter()
    outcome: Mapping[str, Any] | None = None
    for event in events:
        if event.event_type not in {
            "phase_instance_started",
            "action_parsed",
            "family_outcome_recorded",
        }:
            continue
        payload = _artifact_payload(attempt_dir, event.payload_ref)
        if event.event_type == "phase_instance_started":
            phase_order.append(payload["phase"]["phase_id"])
        elif event.event_type == "action_parsed":
            parse_result = payload["parse_result"]
            action = parse_result.get("action")
            if parse_result.get("ok") is True and isinstance(action, dict):
                decision = action.get("decision")
                if isinstance(decision, str):
                    action_outcomes[decision] += 1
        else:
            outcome = payload["outcome"]

    projected: dict[str, Any] = {
        "config_id": row["config_id"],
        "condition_id": row["condition_id"],
        "subject": row["subject"],
        "opponent": row["opponent"],
        "evaluation_kind": row["evaluation_kind"],
        "world_seed": row["world_seed"],
        "replicate_index": row["replicate_index"],
        "status": row["status"],
        "run_plan_id": receipt["run_plan_id"],
        "cell_id": receipt["cell_id"],
        "episode_attempt_id": receipt["episode_attempt_id"],
        "event_count": seal["event_count"],
        "event_root_sha256": seal["event_root_sha256"],
        "artifact_count": seal["artifact_count"],
        "artifact_root_sha256": seal["artifact_root_sha256"],
        "receipt_sha256": receipt["receipt_sha256"],
        "result_artifact_sha256": row["artifact_sha256"],
        "phase_order": phase_order,
        "action_outcomes": dict(sorted(action_outcomes.items())),
        "cost_usd": row["cost_usd"],
        "elapsed_seconds": row["elapsed_seconds"],
    }
    if row["status"] == "completed":
        if outcome is None:
            raise ValueError("completed trajectory omitted its family outcome")
        projected.update(
            {
                "logical_action_count": row["logical_action_count"],
                "effective_retry_count": row["role_metrics"][
                    "effective_retry_count"
                ],
                "assignment_pairs": outcome["assignment_pairs"],
                "signed_rents": outcome["signed_rents"],
                "termination_reason": outcome["reason"],
                "social_welfare": row["social_welfare"],
                "comparison_baseline": outcome["baseline_total"],
                "oracle_upper_bound": outcome["oracle_total"],
                "within_case_score": row["within_case_score"],
                "ir_violation_count": row["ir_violation_count"],
                "wasted_contacts": row["wasted_contacts"],
                "role_metrics": row["role_metrics"],
                "provider_cost_complete": row["provider_cost_complete"],
                "route_verified": row["route_verified"],
                "replay_verified": row["replay_verified"],
            }
        )
    else:
        if outcome is not None:
            raise ValueError("failed trajectory unexpectedly contains an outcome")
        projected.update(
            {
                "inclusion_status": receipt["inclusion_status"],
                "failure_type": row["failure_type"],
                "failure_condition": row["failure_condition"],
                "failure_status_code": row["failure_status_code"],
                "failure_usage": row["failure_usage"],
                "score": None,
                "replay_verified": False,
            }
        )
    return projected


def _profile_results(
    contract: Mapping[str, Any], admission: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id, model in contract["models"].items():
        probes = [row for row in admission["rows"] if row["model_id"] == model_id]
        rows.append(
            {
                "model_id": model_id,
                "provider": model["provider"],
                "planned_probes": len(probes),
                "passed_probes": sum(row["status"] == "passed" for row in probes),
                "operational_failures": sum(
                    row["status"] != "passed" for row in probes
                ),
                "observed_cost_usd": sum(
                    float(row["cost_usd"])
                    for row in probes
                    if isinstance(row.get("cost_usd"), (int, float))
                ),
            }
        )
    return rows


def _publish_fact_tables(
    *,
    contract: Mapping[str, Any],
    catalog: Mapping[str, Any],
    admission: Mapping[str, Any],
    publish_root: Path,
) -> dict[str, Any]:
    campaign_id = contract["campaign_id"]
    admission_fields = (
        "campaign_id",
        "model_id",
        "provider",
        "role",
        "action_schema",
        "probe_index",
        "status",
        "elapsed_seconds",
        "pacing_provider_calls",
        "paced_call_count",
        "pacing_wait_seconds",
        "failure_condition",
        "failure_status_code",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "cost_usd",
        "billing_status",
        "route_verified",
        "request_sha256",
        "action_sha256",
        "raw_response_sha256",
        "artifact_sha256",
    )
    admission_rows: list[dict[str, Any]] = []
    for row in admission["rows"]:
        pacing = row.get("call_pacing")
        pacing_fields = (
            {
                "pacing_provider_calls": pacing.get("provider_calls"),
                "paced_call_count": pacing.get("paced_call_count"),
                "pacing_wait_seconds": pacing.get("pacing_wait_seconds"),
            }
            if isinstance(pacing, Mapping)
            else {}
        )
        admission_rows.append(
            {
                field: (
                    campaign_id
                    if field == "campaign_id"
                    else contract["models"][row["model_id"]]["provider"]
                    if field == "provider"
                    else pacing_fields.get(field)
                    if field in pacing_fields
                    else row.get(field)
                )
                for field in admission_fields
            }
        )
    admission_payload = _csv_bytes(
        fieldnames=admission_fields, rows=admission_rows
    )
    admission_path = publish_root / "tables" / "profile_admission.csv"
    _write_immutable_bytes(admission_path, admission_payload)

    catalog_by_model = {row["model_id"]: row for row in catalog["routes"]}
    profile_fields = (
        "campaign_id",
        "model_id",
        "requested_model",
        "canonical_model",
        "provider",
        "quantization",
        "tenant_profile_id",
        "tenant_profile_sha256",
        "landlord_profile_id",
        "landlord_profile_sha256",
        "input_per_million",
        "cached_input_per_million",
        "output_per_million",
        "endpoint_snapshot_sha256",
        "endpoint_status",
        "uptime_last_5m",
        "uptime_last_30m",
        "planned_admission_probes",
        "passed_admission_probes",
        "admission_failures",
    )
    profile_rows: list[dict[str, Any]] = []
    profile_digests = admission["profile_sha256s"]
    for model_id, model in contract["models"].items():
        route = catalog_by_model[model_id]
        probes = [row for row in admission["rows"] if row["model_id"] == model_id]
        profile_rows.append(
            {
                "campaign_id": campaign_id,
                "model_id": model_id,
                "requested_model": model["requested_model"],
                "canonical_model": model["canonical_model"],
                "provider": model["provider"],
                "quantization": model["quantization"],
                "tenant_profile_id": model["tenant_profile_id"],
                "tenant_profile_sha256": profile_digests[
                    model["tenant_profile_id"]
                ],
                "landlord_profile_id": model["landlord_profile_id"],
                "landlord_profile_sha256": profile_digests[
                    model["landlord_profile_id"]
                ],
                "input_per_million": model["input_per_million"],
                "cached_input_per_million": model["cached_input_per_million"],
                "output_per_million": model["output_per_million"],
                "endpoint_snapshot_sha256": route["endpoint_snapshot_sha256"],
                "endpoint_status": route["status"],
                "uptime_last_5m": route.get("uptime_last_5m"),
                "uptime_last_30m": route.get("uptime_last_30m"),
                "planned_admission_probes": len(probes),
                "passed_admission_probes": sum(
                    row["status"] == "passed" for row in probes
                ),
                "admission_failures": sum(
                    row["status"] != "passed" for row in probes
                ),
            }
        )
    profile_payload = _csv_bytes(fieldnames=profile_fields, rows=profile_rows)
    profile_path = publish_root / "tables" / "model_profiles.csv"
    _write_immutable_bytes(profile_path, profile_payload)

    manifest = _sealed(
        {
            "schema_version": "aeread.housing_backend_fact_manifest/0.1",
            "campaign_id": campaign_id,
            "artifacts": {
                "model_profiles": {
                    "path": f"evidence/{campaign_id}/tables/model_profiles.csv",
                    "row_count": len(profile_rows),
                    "sha256": _sha256_bytes(profile_payload),
                },
                "profile_admission": {
                    "path": f"evidence/{campaign_id}/tables/profile_admission.csv",
                    "row_count": len(admission_rows),
                    "sha256": _sha256_bytes(admission_payload),
                },
            },
        }
    )
    _write_immutable(publish_root / "tables" / "fact_manifest.json", manifest)
    return manifest


def _publish_run_fact_tables(
    *,
    contract: Mapping[str, Any],
    design: Mapping[str, Any],
    live: Mapping[str, Any],
    run_root: Path,
    publish_root: Path,
) -> dict[str, Any]:
    setups = build_setups(contract, routes=route_table(contract))
    rows_by_plan: dict[str, list[Mapping[str, Any]]] = {}
    for row in live["rows"]:
        rows_by_plan.setdefault(row["run_plan_id"], []).append(row)

    index_rows: list[dict[str, Any]] = []
    for (config_id, condition_id), setup in sorted(setups.items()):
        plan = setup.plan
        plan_rows = rows_by_plan.get(plan.run_plan_id, [])
        receipts = []
        for row in plan_rows:
            _, serialized = _attempt_dir(
                live_root=run_root / contract["execution"].get("stage", "live"),
                row=row,
                design=design,
            )
            receipts.append(deserialize_evaluation_receipt(serialized))
        table_root = publish_root / "tables" / "by_run" / plan.run_plan_id
        paths = export_canonical_fact_tables(plan, receipts, table_root)
        manifest = json.loads(paths["fact_manifest"].read_bytes())
        index_rows.append(
            {
                "config_id": config_id,
                "condition_id": condition_id,
                "run_plan_id": plan.run_plan_id,
                "run_plan_sha256": plan.plan_sha256,
                "receipt_count": len(receipts),
                "fact_manifest_path": (
                    f"evidence/{contract['campaign_id']}/tables/by_run/"
                    f"{plan.run_plan_id}/fact_manifest.json"
                ),
                "fact_manifest_file_sha256": _sha256_bytes(
                    paths["fact_manifest"].read_bytes()
                ),
                "fact_manifest_sha256": manifest["manifest_sha256"],
            }
        )
    contrast_artifact: dict[str, Any] | None = None
    variance = live.get("variance_pilot_analysis")
    if isinstance(variance, Mapping):
        contrast_fields = (
            "campaign_id",
            "world_seed",
            "complete_pair",
            "glm_53_flash_mean",
            "deepseek_v4_flash_mean",
            "contrast",
            "glm_53_flash_completed_cells",
            "deepseek_v4_flash_completed_cells",
        )
        contrast_rows = [
            {
                "campaign_id": contract["campaign_id"],
                "world_seed": row["world_seed"],
                "complete_pair": row["complete_pair"],
                "glm_53_flash_mean": row["subject_means"].get(
                    "glm_53_flash"
                ),
                "deepseek_v4_flash_mean": row["subject_means"].get(
                    "deepseek_v4_flash"
                ),
                "contrast": row["contrast"],
                "glm_53_flash_completed_cells": row[
                    "completed_cells_by_subject"
                ].get("glm_53_flash", 0),
                "deepseek_v4_flash_completed_cells": row[
                    "completed_cells_by_subject"
                ].get("deepseek_v4_flash", 0),
            }
            for row in variance["worlds"]
        ]
        contrast_payload = _csv_bytes(
            fieldnames=contrast_fields, rows=contrast_rows
        )
        contrast_path = publish_root / "tables" / "paired_world_contrasts.csv"
        _write_immutable_bytes(contrast_path, contrast_payload)
        contrast_artifact = {
            "path": (
                f"evidence/{contract['campaign_id']}/tables/"
                "paired_world_contrasts.csv"
            ),
            "row_count": len(contrast_rows),
            "sha256": _sha256_bytes(contrast_payload),
            "source_artifact_sha256": variance["artifact_sha256"],
        }
    index = _sealed(
        {
            "schema_version": "aeread.housing_canonical_fact_index/0.1",
            "campaign_id": contract["campaign_id"],
            "source_live_artifact_sha256": live["artifact_sha256"],
            "run_count": len(index_rows),
            "source_truth": ["RunPlan", "EvaluationReceipt"],
            "runs": index_rows,
            "paired_world_contrasts": contrast_artifact,
        }
    )
    _write_immutable(
        publish_root / "tables" / "canonical_fact_index.json", index
    )
    return index


def _publish_blocked_campaign(
    *,
    contract_path: Path,
    run_root: Path,
    publish_root: Path,
    contract: Mapping[str, Any],
    design: Mapping[str, Any],
    provider_free: Mapping[str, Any],
    catalog: Mapping[str, Any],
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    terminal_stage = contract["execution"].get("stage", "live")
    blocked = _read_sealed(run_root / terminal_stage / "blocked.json")
    campaign_id = contract["campaign_id"]
    if (
        blocked["campaign_id"] != campaign_id
        or blocked["status"] != "blocked_by_profile_admission"
        or blocked["profile_admission_sha256"] != admission["artifact_sha256"]
        or blocked["provider_calls"] != 0
        or blocked.get("gate_id", "live") != terminal_stage
    ):
        raise ValueError("blocked terminal gate does not bind the failed admission")

    trajectory_export = _sealed(
        {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "claim_status": contract["claim_status"],
            "source_gate": f"{terminal_stage}_block",
            "source_summary_artifact_sha256": blocked["artifact_sha256"],
            "selection_rule": "No trajectory was eligible after profile admission failed.",
            "selection_is_for_presentation_not_inference": True,
            "ranking_allowed": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "local_source": f"runs/{campaign_id}/{terminal_stage}",
            "limitations": [
                "Profile admission failed, so no Housing trajectory was started.",
                "The admission failure is provider reliability evidence, not a model score.",
            ],
            "planned_trajectories": design["planned_trajectories"],
            "attempted_trajectories": 0,
            "completed_trajectories": 0,
            "operational_failures": 0,
            "trajectories": [],
        }
    )
    trajectory_path = publish_root / "trajectories" / "attempted.json"
    _write_immutable(trajectory_path, trajectory_export)
    fact_manifest = _publish_fact_tables(
        contract=contract,
        catalog=catalog,
        admission=admission,
        publish_root=publish_root,
    )
    failed_probes = [
        {
            key: row.get(key)
            for key in (
                "model_id",
                "role",
                "action_schema",
                "probe_index",
                "failure_type",
                "failure_condition",
                "failure_status_code",
                "billing_status",
                "artifact_sha256",
            )
        }
        for row in admission["rows"]
        if row["status"] != "passed"
    ]
    qualification = _sealed(
        {
            "schema_version": "aeread.housing_backend_qualification/0.4",
            "campaign_id": campaign_id,
            "created_date": contract["backend"]["catalog_retrieved_at"],
            "status": blocked["status"],
            "claim_status": contract["claim_status"],
            "winner_claim_allowed": False,
            "ranking_allowed": False,
            "contract_binding": {
                "path": f"configs/{contract_path.name}",
                "file_sha256": _sha256_bytes(contract_path.read_bytes()),
                "artifact_sha256": design["contract_sha256"],
            },
            "source_case_selection": {
                "campaign_id": "housing_case_config_sweep_v1",
                "artifact_sha256": contract["source_case_selection"][
                    "artifact_sha256"
                ],
                "confirmatory_holdout_status": provider_free[
                    "confirmatory_holdout_status"
                ],
            },
            "gate_status": [
                {
                    "gate_id": "design",
                    "status": design["status"],
                    "artifact_sha256": design["artifact_sha256"],
                    "planned_trajectories": design["planned_trajectories"],
                },
                {
                    "gate_id": "provider_free",
                    "status": provider_free["status"],
                    "artifact_sha256": provider_free["artifact_sha256"],
                    "provider_calls": provider_free["provider_calls"],
                    "cost_usd": provider_free["provider_cost_usd"],
                },
                {
                    "gate_id": "catalog_preflight",
                    "status": catalog["status"],
                    "artifact_sha256": catalog["artifact_sha256"],
                    "provider_inference_calls": catalog[
                        "provider_inference_calls"
                    ],
                },
                {
                    "gate_id": "profile_admission",
                    "status": admission["status"],
                    "artifact_sha256": admission["artifact_sha256"],
                    "expected_probe_count": admission["expected_probe_count"],
                    "attempted_probe_count": admission["attempted_probe_count"],
                    "passed_probe_count": admission["passed_probe_count"],
                    "operational_failures": admission["operational_failures"],
                    "hidden_retry_count": admission["hidden_retry_count"],
                    "observed_cost_usd": admission["observed_cost_usd"],
                    "provider_cost_complete": admission[
                        "provider_cost_complete"
                    ],
                },
                {
                    "gate_id": terminal_stage,
                    "status": blocked["status"],
                    "artifact_sha256": blocked["artifact_sha256"],
                    "planned_trajectories": design["planned_trajectories"],
                    "attempted_trajectories": 0,
                    "completed_trajectories": 0,
                    "not_started_trajectories": design[
                        "planned_trajectories"
                    ],
                    "provider_calls": blocked["provider_calls"],
                    "cost_usd": blocked["cost_usd"],
                },
            ],
            "profile_results": _profile_results(contract, admission),
            "failed_admission_probes": failed_probes,
            "trajectory_export": {
                "path": f"evidence/{campaign_id}/trajectories/attempted.json",
                "artifact_sha256": trajectory_export["artifact_sha256"],
                "planned_trajectories": design["planned_trajectories"],
                "attempted_trajectories": 0,
            },
            "fact_tables": {
                "path": f"evidence/{campaign_id}/tables/fact_manifest.json",
                "artifact_sha256": fact_manifest["artifact_sha256"],
            },
            "acceptance": {
                "publishable_gate_evidence": True,
                "publishable_integration_evidence": False,
                "all_frozen_cells_attempted": False,
                "prerequisite_gates_passed": False,
                "typed_missingness_preserved": True,
                "leaderboard_eligible": False,
            },
            "interpretation": (
                f"{campaign_id} passed design, provider-free, and catalog gates, "
                f"but only "
                f"{admission['passed_probe_count']} of "
                f"{admission['expected_probe_count']} profile-admission probes "
                f"passed. The failed admission blocked all "
                f"{design['planned_trajectories']} Housing "
                "trajectories, so this campaign contains no model score or "
                "variance estimate."
            ),
            "cost_note": (
                f"Profile admission recorded ${admission['observed_cost_usd']} "
                f"in provider-reported cost; {terminal_stage} execution cost $0.0."
            ),
            "stop_reason": (
                f"Profile admission failed; {terminal_stage} execution was not "
                "eligible."
            ),
            "next_gate": (
                "Review the typed provider failure and freeze a new campaign "
                "identity; do not selectively rerun a failed probe."
            ),
            "local_evidence": {
                "path": f"runs/{campaign_id}",
                "committed": False,
                "contains_raw_provider_evidence": True,
            },
            "publication_policy": {
                "raw_provider_responses_included": False,
                "model_reasoning_included": False,
                "absolute_user_paths_included": False,
                "typed_failures_included": True,
            },
        }
    )
    _write_immutable(publish_root / "reports" / "qualification.json", qualification)
    return qualification


def publish_campaign(
    *, contract_path: str | Path, run_root: str | Path, publish_root: str | Path
) -> dict[str, Any]:
    contract_path = Path(contract_path)
    run_root = Path(run_root)
    publish_root = Path(publish_root)
    contract = load_contract(contract_path)
    design = _read_sealed(run_root / "design" / "summary.json")
    provider_free = _read_sealed(run_root / "provider_free" / "summary.json")
    catalog = _read_sealed(run_root / "catalog_preflight" / "summary.json")
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    campaign_id = contract["campaign_id"]
    if any(
        artifact["campaign_id"] != campaign_id
        for artifact in (design, provider_free, catalog, admission)
    ):
        raise ValueError("source gate campaign identities differ")
    if not (
        design["status"] == "passed"
        and provider_free["status"] == "passed"
        and catalog["status"] == "passed"
    ):
        raise ValueError("cannot publish after a failed provider-free prerequisite")
    if admission["status"] != "passed":
        return _publish_blocked_campaign(
            contract_path=contract_path,
            run_root=run_root,
            publish_root=publish_root,
            contract=contract,
            design=design,
            provider_free=provider_free,
            catalog=catalog,
            admission=admission,
        )

    terminal_stage = contract["execution"].get("stage", "live")
    live = _read_sealed(run_root / terminal_stage / "summary.json")
    if live["campaign_id"] != campaign_id:
        raise ValueError("live gate campaign identity differs")
    if live["attempted_trajectories"] != live["planned_trajectories"]:
        raise ValueError("publication requires every frozen cell to be attempted")

    trajectories = [
        _project_attempt(
            live_root=run_root / terminal_stage, row=row, design=design
        )
        for row in live["rows"]
    ]
    world_count = len(contract["execution"]["world_seeds"])
    limitations = [
        (
            "Action summaries project sealed parsed actions; raw responses and "
            "reasoning remain local."
        )
    ]
    if world_count == 1:
        limitations.insert(
            0,
            "Only one world cluster was attempted, so uncertainty is not estimable.",
        )
    else:
        limitations.insert(
            0,
            (
                f"The exploratory pilot contains {world_count} development-world "
                "clusters and cannot support a model ranking."
            ),
        )
        limitations.insert(
            1,
            (
                "The changed route proceeded from profile admission directly to "
                "the multi-world pilot without a separately recorded full-trajectory "
                "gate."
            ),
        )
    if live["operational_failures"]:
        limitations.insert(
            1,
            (
                f"{live['operational_failures']} attempted trajectories remain "
                "typed operational missingness and are excluded from scores."
            ),
        )
    trajectory_export = _sealed(
        {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "claim_status": contract["claim_status"],
            "source_gate": terminal_stage,
            "source_summary_artifact_sha256": live["artifact_sha256"],
            "selection_rule": (
                "Retain every attempted trajectory, including typed operational "
                "missingness, in frozen execution order."
            ),
            "selection_is_for_presentation_not_inference": True,
            "ranking_allowed": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "local_source": f"runs/{campaign_id}/{terminal_stage}",
            "limitations": limitations,
            "planned_trajectories": live["planned_trajectories"],
            "attempted_trajectories": live["attempted_trajectories"],
            "completed_trajectories": live["completed_trajectories"],
            "operational_failures": live["operational_failures"],
            "trajectories": trajectories,
        }
    )
    trajectory_path = publish_root / "trajectories" / "attempted.json"
    _write_immutable(trajectory_path, trajectory_export)
    fact_index = _publish_run_fact_tables(
        contract=contract,
        design=design,
        live=live,
        run_root=run_root,
        publish_root=publish_root,
    )

    completed_scores = [
        float(row["within_case_score"])
        for row in live["rows"]
        if row["status"] == "completed"
    ]
    backend_routes = []
    catalog_by_model = {row["model_id"]: row for row in catalog["routes"]}
    for model_id, model in contract["models"].items():
        route = catalog_by_model[model_id]
        backend_routes.append(
            {
                "model_id": model_id,
                "canonical_model": model["canonical_model"],
                "provider": model["provider"],
                "quantization": model["quantization"],
                "input_per_million": model["input_per_million"],
                "cached_input_per_million": model["cached_input_per_million"],
                "output_per_million": model["output_per_million"],
                "endpoint_snapshot_sha256": route["endpoint_snapshot_sha256"],
            }
        )
    combined_cost = admission["observed_cost_usd"] + live["total_cost_usd"]
    variance = live.get("variance_pilot_analysis")
    full_trajectory_gate_passed = world_count == 1
    paired_worlds_complete = bool(
        isinstance(variance, Mapping)
        and variance.get("status") == "estimable"
        and variance.get("paired_world_count") == variance.get("planned_world_count")
    )
    confirmatory_freeze_ready = bool(
        paired_worlds_complete and variance.get("within_declared_maximum") is True
    )
    trajectory_relative_path = (
        f"evidence/{campaign_id}/trajectories/attempted.json"
    )
    qualification = _sealed(
        {
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "created_date": contract["backend"]["catalog_retrieved_at"],
            "status": live["status"],
            "claim_status": contract["claim_status"],
            "winner_claim_allowed": False,
            "ranking_allowed": False,
            "contract_binding": {
                "path": f"configs/{contract_path.name}",
                "file_sha256": _sha256_bytes(contract_path.read_bytes()),
                "artifact_sha256": design["contract_sha256"],
            },
            "source_case_selection": {
                "campaign_id": "housing_case_config_sweep_v1",
                "artifact_sha256": contract["source_case_selection"][
                    "artifact_sha256"
                ],
                "confirmatory_holdout_status": provider_free[
                    "confirmatory_holdout_status"
                ],
            },
            "controls": {
                "harness": contract["controls"]["harness"],
                "tools": contract["controls"]["tools"],
                "memory": contract["controls"]["memory"],
                "reasoning_effort": contract["controls"]["reasoning_effort"],
                "temperature": contract["controls"]["temperature"],
                "top_p": contract["controls"]["top_p"],
                "max_output_tokens": contract["controls"]["max_output_tokens"],
                "timeout_seconds": contract["controls"]["timeout_seconds"],
                "sdk_retries": contract["controls"]["sdk_retries"],
                "max_action_attempts": contract["controls"][
                    "max_action_attempts"
                ],
                "retryable_conditions": contract["controls"][
                    "retryable_conditions"
                ],
                "action_schema_version": contract["controls"][
                    "action_schema_version"
                ],
                "conditional_action_schemas": True,
                "live_profile_controls_wired": contract["controls"][
                    "wire_live_profile_controls"
                ],
                "condition_order": contract["controls"]["condition_order"],
            },
            "backend": {
                "gateway": contract["backend"]["gateway"],
                "allow_fallbacks": contract["backend"]["allow_fallbacks"],
                "catalog_retrieved_at": contract["backend"][
                    "catalog_retrieved_at"
                ],
                "routes": backend_routes,
            },
            "gate_status": [
                {
                    "gate_id": "design",
                    "status": design["status"],
                    "artifact_sha256": design["artifact_sha256"],
                    "planned_trajectories": design["planned_trajectories"],
                },
                {
                    "gate_id": "provider_free",
                    "status": provider_free["status"],
                    "artifact_sha256": provider_free["artifact_sha256"],
                    "provider_calls": provider_free["provider_calls"],
                    "cost_usd": provider_free["provider_cost_usd"],
                },
                {
                    "gate_id": "catalog_preflight",
                    "status": catalog["status"],
                    "artifact_sha256": catalog["artifact_sha256"],
                    "provider_inference_calls": catalog[
                        "provider_inference_calls"
                    ],
                },
                {
                    "gate_id": "profile_admission",
                    "status": admission["status"],
                    "artifact_sha256": admission["artifact_sha256"],
                    "expected_probe_count": admission["expected_probe_count"],
                    "attempted_probe_count": admission["attempted_probe_count"],
                    "passed_probe_count": admission["passed_probe_count"],
                    "operational_failures": admission["operational_failures"],
                    "hidden_retry_count": admission["hidden_retry_count"],
                    "observed_cost_usd": admission["observed_cost_usd"],
                    "provider_cost_complete": admission[
                        "provider_cost_complete"
                    ],
                },
                {
                    "gate_id": terminal_stage,
                    "status": live["status"],
                    "artifact_sha256": live["artifact_sha256"],
                    "planned_trajectories": live["planned_trajectories"],
                    "attempted_trajectories": live["attempted_trajectories"],
                    "completed_trajectories": live["completed_trajectories"],
                    "operational_failures": live["operational_failures"],
                    "not_started_trajectories": live[
                        "not_started_trajectories"
                    ],
                    "cost_usd": live["total_cost_usd"],
                    "stop_reason": live["stop_reason"],
                    "complete_matrix": live["complete_matrix"],
                    "critical_stop": live["critical_stop"],
                },
            ],
            "profile_results": _profile_results(contract, admission),
            "observed_score_range": {
                "minimum": min(completed_scores),
                "maximum": max(completed_scores),
                "interpretation": (
                    "Descriptive development-pilot range only; it does not support "
                    "ranking."
                ),
            },
            "trajectory_export": {
                "path": trajectory_relative_path,
                "artifact_sha256": trajectory_export["artifact_sha256"],
                "planned_trajectories": live["planned_trajectories"],
                "attempted_trajectories": live["attempted_trajectories"],
                "completed_trajectories": live["completed_trajectories"],
                "operational_failures": live["operational_failures"],
            },
            "fact_tables": {
                "path": (
                    f"evidence/{campaign_id}/tables/canonical_fact_index.json"
                ),
                "artifact_sha256": fact_index["artifact_sha256"],
                "run_count": fact_index["run_count"],
            },
            "variance_pilot_analysis": variance,
            "protocol_gate_assessment": {
                "required_before_variance_pilot": "full_trajectory",
                "full_trajectory_gate_passed": full_trajectory_gate_passed,
                "protocol_conformant": full_trajectory_gate_passed,
                "interpretation": (
                    "A one-world integration slice satisfies this publication's "
                    "full-trajectory role."
                    if full_trajectory_gate_passed
                    else (
                        "No separate full-trajectory gate was recorded for the "
                        "changed route before multi-world execution. Retain the run "
                        "as operational evidence but do not promote it as a valid "
                        "variance pilot."
                    )
                ),
            },
            "acceptance": {
                "publishable_integration_evidence": True,
                "all_frozen_cells_attempted": True,
                "prerequisite_gates_passed": full_trajectory_gate_passed,
                "typed_missingness_preserved": True,
                "paired_worlds_complete": paired_worlds_complete,
                "confirmatory_freeze_ready": confirmatory_freeze_ready,
                "leaderboard_eligible": False,
                "protocol_conformant": full_trajectory_gate_passed,
            },
            "interpretation": (
                f"The campaign passed all prerequisite gates and attempted all "
                f"{live['planned_trajectories']} frozen Housing model-to-model "
                f"cells. {live['completed_trajectories']} trajectories completed "
                f"with verified replay and {live['operational_failures']} remain "
                "typed operational missingness. This is exploratory pilot evidence, "
                "not a model ranking or leaderboard."
                if full_trajectory_gate_passed
                else (
                    f"The campaign passed design, provider-free, catalog, and "
                    f"profile-admission gates and attempted all "
                    f"{live['planned_trajectories']} frozen Housing model-to-model "
                    f"cells. {live['completed_trajectories']} trajectories completed "
                    f"with verified replay and {live['operational_failures']} remain "
                    "typed operational missingness. The required full-trajectory "
                    "gate was not separately recorded before multi-world execution, "
                    "so this is protocol-deviation and route-reliability evidence, "
                    "not a valid variance pilot, model ranking, or leaderboard."
                )
            ),
            "cost_note": (
                f"Profile admission cost ${admission['observed_cost_usd']}; live "
                f"execution cost ${live['total_cost_usd']}; combined provider-"
                f"reported cost ${combined_cost}."
            ),
            "stop_reason": (
                "All frozen cells were attempted; typed operational failures, if "
                "any, were retained without selective retry."
            ),
            "next_gate": (
                (
                    "Freeze the confirmatory campaign with "
                    f"{variance['recommended_confirmatory_worlds']} worlds and the "
                    "sealed holdout; do not infer a winner from this pilot."
                )
                if confirmatory_freeze_ready
                else (
                    "The full-trajectory gate passed on the selected routes; freeze "
                    "a new campaign identity for a multi-world variance pilot that "
                    "carries these routes, cooldown, and admission-timeout controls "
                    "forward unchanged. Do not pool or rerun this one-world gate."
                )
                if (
                    terminal_stage == "full_trajectory"
                    and live["complete_matrix"]
                    and not live["operational_failures"]
                )
                else (
                    "Freeze a new campaign identity, pass one complete trajectory "
                    "per subject-opponent condition on the selected routes, then run "
                    "a new multi-world variance pilot; do not selectively rerun or "
                    "impute missing V10 cells."
                )
            ),
            "local_evidence": {
                "path": f"runs/{campaign_id}",
                "committed": False,
                "contains_raw_provider_evidence": True,
            },
            "publication_policy": {
                "raw_provider_responses_included": False,
                "model_reasoning_included": False,
                "absolute_user_paths_included": False,
                "typed_failures_included": True,
            },
        }
    )
    _write_immutable(publish_root / "reports" / "qualification.json", qualification)
    return qualification


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        default="configs/housing_model_sensitivity_openrouter_alt_v8.json",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("runs/housing_model_sensitivity_openrouter_alt_v8"),
    )
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=Path("evidence/housing_model_sensitivity_openrouter_alt_v8"),
    )
    arguments = parser.parse_args(argv)
    result = publish_campaign(
        contract_path=arguments.contract,
        run_root=arguments.run_root,
        publish_root=arguments.publish_root,
    )
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
