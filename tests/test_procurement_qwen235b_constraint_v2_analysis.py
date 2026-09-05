from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.qwen_case_campaign import (
    PAIRED_INFERENCE_SEEDS,
)
from aeread_families.procurement_allocation.qwen235b_constraint_campaign import (
    CAMPAIGN_ID as V1_CAMPAIGN_ID,
    build_plan as build_v1_plan,
)
from aeread_families.procurement_allocation.qwen235b_constraint_v2_analysis import (
    build_v2_analysis,
    publish_campaign,
)
from aeread_families.procurement_allocation.qwen235b_constraint_v2_campaign import (
    CAMPAIGN_ID as V2_CAMPAIGN_ID,
    build_plan as build_v2_plan,
)
from aeread_families.procurement_allocation.qwen235b_google_case_campaign import (
    CAMPAIGN_ID as CONTROL_CAMPAIGN_ID,
    QWEN235B_GOOGLE_CANDIDATE,
    build_plan as build_control_plan,
)


def _row(*, path: Path, seed: int, feasible: bool, margin: float) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    row: dict[str, object] = {
        "case_id": raw["case_id"],
        "case_content_sha256": raw["content_sha256"],
        "inference_seed": seed,
        "status": "completed",
        "decision": "award" if feasible else "failed",
        "termination_reason": "submitted" if feasible else "invalid_action",
        "feasible": feasible,
        "completed_kits": 10 if feasible else 0,
        "contribution_margin_usd": margin,
        "upper_bound_usd": 20.0,
        "regret_to_upper_bound_usd": 20.0 - margin,
        "violations": [] if feasible else ["malformed_procurement_action"],
        "elapsed_environment_days": 1,
        "action_count": 1,
        "action_trace": [{"ordinal": 1, "action": "request_quote"}],
        "elapsed_seconds": 2.0,
        "input_tokens": 100,
        "cached_input_tokens": 0,
        "output_tokens": 20,
        "cost_usd": 0.001,
        "cost_accounting": "exact",
        "resolved_models": [],
        "receipt_sha256": "a" * 64,
        "receipt_replayed": True,
        "replay_level": "provider_response",
        "provider_call_count": 1,
        "runner_retry_count": 0,
        "retry_condition_counts": {},
    }
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
    return row


def _write_attempt(
    root: Path, *, outer_plan: dict, feasible: bool, margin: float
) -> None:
    root.mkdir(parents=True)
    (root / "campaign_plan.json").write_bytes(
        canonical_json_bytes(outer_plan) + b"\n"
    )
    canary = {
        "campaign_id": outer_plan["campaign_id"],
        "status": "admitted",
        "scored": False,
        "model": QWEN235B_GOOGLE_CANDIDATE.route.model,
        "revision": QWEN235B_GOOGLE_CANDIDATE.route.revision,
        "route_provider": QWEN235B_GOOGLE_CANDIDATE.route.route_provider,
        "resolved_model": QWEN235B_GOOGLE_CANDIDATE.route.revision,
        "cost_usd": 0.0001,
        "cost_accounting": "exact",
    }
    canary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(canary)
    ).hexdigest()
    (root / "admission_canary.json").write_bytes(
        canonical_json_bytes(canary) + b"\n"
    )
    rows = [
        _row(path=path, seed=seed, feasible=feasible, margin=margin)
        for path in CASE_VARIANCE_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    ]
    summary = {
        "completed_trajectory_count": 18,
        "operational_failure_count": 0,
        "total_cost_usd": 0.018,
        "cost_accounting": "exact",
        "median_elapsed_seconds": 2.0,
        "feasible_count": 18 if feasible else 0,
        "violation_counts": {} if feasible else {"malformed_procurement_action": 18},
        "readiness": {"execution_qualified": True},
    }
    artifact = {
        "plan": outer_plan["scored_plan"],
        "summary": summary,
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    scored = root / "scored"
    scored.mkdir()
    (scored / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    control = tmp_path / "runs" / CONTROL_CAMPAIGN_ID / "attempt"
    v1 = tmp_path / "runs" / V1_CAMPAIGN_ID / "attempt"
    v2 = tmp_path / "runs" / V2_CAMPAIGN_ID / "attempt"
    _write_attempt(control, outer_plan=build_control_plan(), feasible=False, margin=8.0)
    _write_attempt(v1, outer_plan=build_v1_plan(), feasible=False, margin=8.0)
    _write_attempt(v2, outer_plan=build_v2_plan(), feasible=True, margin=10.0)
    return control, v1, v2


def test_v2_analysis_keeps_repair_and_control_contrasts_separate(
    tmp_path: Path,
) -> None:
    control, v1, v2 = _fixture_roots(tmp_path)

    result = build_v2_analysis(
        control_run_root=control, v1_run_root=v1, v2_run_root=v2
    )

    assert result["readiness"]["constraint_v2_analysis_qualified"] is True
    assert result["primary_contract_recovery_v2_minus_v1"][
        "feasibility_transition_counts"
    ] == {"fail_to_pass": 18}
    assert result["exploratory_development_v2_minus_control"][
        "aggregate_effects"
    ]["feasible"]["case_cluster_mean"] == 1.0
    assert result["action_contract_diagnostics"] == {
        "control_malformed_procurement_action_count": 18,
        "v1_malformed_procurement_action_count": 18,
        "v2_malformed_procurement_action_count": 0,
    }
    assert all(result["integrity"].values())


def test_v2_publisher_writes_sanitized_digest_bound_bundle(tmp_path: Path) -> None:
    control, v1, v2 = _fixture_roots(tmp_path)
    publication_root = tmp_path / "evidence" / V2_CAMPAIGN_ID

    manifest = publish_campaign(
        control_run_root=control,
        v1_run_root=v1,
        v2_run_root=v2,
        publication_root=publication_root,
    )

    assert manifest["publication_id"] == V2_CAMPAIGN_ID
    report = publication_root / "reports" / "constraint_v2_analysis.json"
    assert report.is_file()
    assert json.loads(report.read_text())["readiness"][
        "constraint_v2_analysis_qualified"
    ]
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication_root / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(
        path.read_text() for path in publication_root.rglob("*.json")
    )
    assert "raw_response" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
