"""Publish a sanitized Housing backend-campaign qualification bundle."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .backend_campaign import load_contract
from .model_sensitivity import _read_sealed


QUALIFICATION_SCHEMA_VERSION = "aeread.housing_backend_qualification/0.3"
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
    ]
    if len(matches) != 1:
        raise ValueError("live row does not map to exactly one frozen design cell")
    plan = matches[0]
    receipt_paths = list(
        (
            live_root
            / row["config_id"]
            / row["condition_id"]
            / "evidence"
            / plan["run_plan_id"]
            / "tasks"
        ).glob("*/attempts/*/evaluation_receipt.json")
    )
    if len(receipt_paths) != 1:
        raise ValueError("live cell must contain exactly one evaluation receipt")
    receipt_path = receipt_paths[0]
    return receipt_path.parent, read_evaluation_receipt(receipt_path)


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
    live = _read_sealed(run_root / "live" / "summary.json")
    campaign_id = contract["campaign_id"]
    if any(
        artifact["campaign_id"] != campaign_id
        for artifact in (design, provider_free, catalog, admission, live)
    ):
        raise ValueError("source gate campaign identities differ")
    if not (
        design["status"] == "passed"
        and provider_free["status"] == "passed"
        and catalog["status"] == "passed"
        and admission["status"] == "passed"
    ):
        raise ValueError("cannot publish a live result whose prerequisite gate failed")
    if live["attempted_trajectories"] != live["planned_trajectories"]:
        raise ValueError("V8 publication requires every frozen cell to be attempted")

    trajectories = [
        _project_attempt(live_root=run_root / "live", row=row, design=design)
        for row in live["rows"]
    ]
    trajectory_export = _sealed(
        {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "claim_status": contract["claim_status"],
            "source_gate": "live",
            "source_summary_artifact_sha256": live["artifact_sha256"],
            "selection_rule": (
                "Retain every attempted V8 trajectory, including typed operational "
                "missingness, in the frozen execution order."
            ),
            "selection_is_for_presentation_not_inference": True,
            "ranking_allowed": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "local_source": f"runs/{campaign_id}/live",
            "limitations": [
                (
                    "Only one world cluster was attempted, so uncertainty is not "
                    "estimable."
                ),
                (
                    "One mild GLM self-play trajectory timed out and remains "
                    "excluded from scores."
                ),
                (
                    "Action summaries project sealed parsed actions; raw responses "
                    "and reasoning remain local."
                ),
            ],
            "planned_trajectories": live["planned_trajectories"],
            "attempted_trajectories": live["attempted_trajectories"],
            "completed_trajectories": live["completed_trajectories"],
            "operational_failures": live["operational_failures"],
            "trajectories": trajectories,
        }
    )
    trajectory_path = publish_root / "trajectories" / "attempted.json"
    _write_immutable(trajectory_path, trajectory_export)

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
                    "gate_id": "live",
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
                    "Descriptive only; one world cluster and one typed timeout do "
                    "not support ranking."
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
            "acceptance": {
                "publishable_integration_evidence": True,
                "all_frozen_cells_attempted": True,
                "prerequisite_gates_passed": True,
                "typed_missingness_preserved": True,
                "leaderboard_eligible": False,
            },
            "interpretation": (
                "V8 passed all prerequisite gates and attempted all 12 frozen "
                "Housing model-to-model cells. Eleven trajectories completed with "
                "verified replay; one mild GLM self-play trajectory timed out and "
                "remains typed operational missingness. This is acceptable "
                "integration evidence, not a complete comparison or leaderboard."
            ),
            "cost_note": (
                f"Profile admission cost ${admission['observed_cost_usd']}; live "
                f"execution cost ${live['total_cost_usd']}; combined provider-"
                f"reported cost ${combined_cost}."
            ),
            "stop_reason": (
                "All frozen cells were attempted; one call timeout produced typed "
                "operational missingness and did not trigger a critical stop."
            ),
            "next_gate": (
                "Freeze a multi-world variance pilot with a new campaign identity; "
                "do not selectively rerun or impute the timed-out V8 cell."
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
