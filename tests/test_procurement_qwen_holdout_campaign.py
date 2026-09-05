from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.qwen_holdout_campaign as campaign_module
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.qwen_case_campaign import (
    run_admission_canary,
)
from aeread_families.procurement_allocation.qwen_holdout_campaign import (
    BOOTSTRAP_RESAMPLES,
    CAMPAIGN_ID,
    FROZEN_CONTROL_PROMPT_SHA256,
    FROZEN_V2_PROMPT_SHA256,
    HARD_TOTAL_COST_CEILING_USD,
    INFERENCE_SEEDS,
    build_comparison,
    build_plan,
    publish_campaign,
)
from aeread_families.procurement_allocation.qwen_holdout_case_matrix import (
    CASE_SLUGS,
    OPAQUE_PATHS,
)
from aeread_families.procurement_allocation.runner import (
    PROMPT as CONTROL_PROMPT,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_canary(root: Path, *, name: str, outer: dict) -> None:
    candidate = outer["candidate"]
    value = {
        "schema_version": "aeread.provider_admission_canary/0.4",
        "campaign_id": outer["campaign_id"],
        "status": "admitted",
        "scored": False,
        "request_sha256": "a" * 64,
        "model": candidate["model"],
        "revision": candidate["revision"],
        "route_provider": candidate["provider"],
        "resolved_model": candidate["revision"],
        "cost_usd": 0.001,
        "cost_accounting": "exact",
        "provider_call_count": 1,
        "runner_retry_count": 0,
        "retry_condition_counts": {},
    }
    value["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(value)
    ).hexdigest()
    _write_json(root / "arms" / name / "admission_canary.json", value)


def _write_arm_summary(
    root: Path,
    *,
    name: str,
    outer: dict,
    worlds: list[dict],
    favorable: bool,
) -> None:
    treatment = name == "treatment"
    if favorable:
        feasible = treatment
        margin = 10.0 if treatment else 5.0
    else:
        feasible = True
        margin = 8.0 if treatment else 10.0
    rows = []
    for world, case_path in zip(worlds, OPAQUE_PATHS, strict=True):
        supplier_id = json.loads(case_path.read_text())["payload"]["suppliers"][0][
            "supplier_id"
        ]
        for seed in INFERENCE_SEEDS:
            row = {
                "case_id": world["case_id"],
                "case_content_sha256": world["case_content_sha256"],
                "inference_seed": seed,
                "status": "completed",
                "decision": "award",
                "termination_reason": "submitted",
                "feasible": feasible,
                "completed_kits": 18 if treatment else 16,
                "contribution_margin_usd": margin,
                "upper_bound_usd": 20.0,
                "regret_to_upper_bound_usd": 20.0 - margin,
                "violations": [] if feasible else ["minimum_service_not_met"],
                "elapsed_environment_days": 4,
                "action_count": 5,
                "action_trace": [
                    {
                        "ordinal": 1,
                        "action": "request_quote",
                        "supplier_id": supplier_id,
                        "status": "succeeded",
                    }
                ],
                "elapsed_seconds": 1.0,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "cost_usd": 0.001,
                "cost_accounting": "exact",
                "provider_call_count": 5,
                "runner_retry_count": 0,
                "retry_condition_counts": {},
                "resolved_models": [outer["candidate"]["revision"]],
                "receipt_sha256": "b" * 64,
                "receipt_replayed": True,
                "replay_level": "provider_response",
            }
            row["result_sha256"] = hashlib.sha256(
                canonical_json_bytes(row)
            ).hexdigest()
            rows.append(row)
    artifact = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": outer["scored_plan"],
        "preflight": {
            "candidate_id": outer["candidate"]["candidate_id"],
            "model": outer["candidate"]["model"],
            "revision": outer["candidate"]["revision"],
            "route_provider": outer["candidate"]["provider"],
            "quantization": outer["candidate"]["quantization"],
        },
        "summary": {
            "planned_trajectory_count": len(rows),
            "row_count": len(rows),
            "unattempted_trajectory_count": 0,
            "completed_trajectory_count": len(rows),
            "operational_failure_count": 0,
            "total_cost_usd": len(rows) * 0.001,
            "cost_accounting": "exact",
            "feasible_count": len(rows) if feasible else 0,
            "violation_counts": (
                {} if feasible else {"minimum_service_not_met": len(rows)}
            ),
            "median_elapsed_seconds": 1.0,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    _write_json(root / "arms" / name / "scored" / "summary.json", artifact)


def _synthetic_campaign(tmp_path: Path, *, favorable: bool) -> tuple[Path, dict]:
    root = tmp_path / "runs" / "procurement_allocation" / CAMPAIGN_ID / "attempt_001"
    plan = build_plan()
    _write_json(root / "campaign_plan.json", plan)
    for name, outer in plan["arms"].items():
        _write_json(root / "arms" / name / "campaign_plan.json", outer)
        _write_canary(root, name=name, outer=outer)
        _write_arm_summary(
            root,
            name=name,
            outer=outer,
            worlds=plan["worlds"],
            favorable=favorable,
        )
    return root, plan


def test_qwen_holdout_plan_freezes_targeted_paired_design_and_budget() -> None:
    plan = build_plan()

    assert plan["freeze_status"] == "targeted_holdout_frozen_before_live_execution"
    assert plan["selection_status"].startswith("held out from execution")
    assert plan["planned_trajectory_count"] == 36
    assert plan["independent_world_count"] == 6
    assert plan["inference_seeds"] == [1645760607, 826870386, 1489883660]
    assert plan["prompts"]["control_sha256"] == FROZEN_CONTROL_PROMPT_SHA256
    assert plan["prompts"]["treatment_sha256"] == FROZEN_V2_PROMPT_SHA256
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.94704)
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(1.14)
    assert HARD_TOTAL_COST_CEILING_USD == pytest.approx(1.14)
    assert plan["arm_execution_order"] == ["control", "treatment"]
    assert plan["analysis"]["bootstrap_resamples"] == BOOTSTRAP_RESAMPLES
    assert plan["analysis"]["no_early_efficacy_stopping"] is True
    assert plan["plan_sha256"] == (
        "5ae0b91427f07c024120de0e96698ceafe1343c55d95e07b867b5cc8c479efde"
    )
    for name, arm in plan["arms"].items():
        assert arm["scored_plan"]["planned_trajectory_count"] == 18
        assert arm["scored_plan"]["cases"] == [
            {
                "case_id": world["case_id"],
                "content_sha256": world["case_content_sha256"],
            }
            for world in plan["worlds"]
        ]
        assert arm["scored_plan"]["inference_seeds"] == list(INFERENCE_SEEDS)
        assert arm["matched_baseline_campaign_id"] is None
        assert arm["campaign_id"] == f"{CAMPAIGN_ID}.{name}"


def test_qwen_holdout_plan_rejects_prompt_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(campaign_module, "V2_PROMPT", campaign_module.V2_PROMPT + " drift")
    with pytest.raises(ValueError, match="frozen V2 treatment prompt changed"):
        campaign_module.build_plan()


def test_qwen_holdout_canaries_use_each_frozen_prompt(tmp_path: Path) -> None:
    for name, prompt in (
        ("control", CONTROL_PROMPT),
        ("treatment", campaign_module.V2_PROMPT),
    ):
        provider = SequenceResponseProvider(
            (json.dumps({"action": "defer", "reason": "test canary"}),)
        )
        canary = asyncio.run(
            run_admission_canary(
                path=tmp_path / f"{name}.json",
                spec=campaign_module._arm_specs()[name],
                provider_factory=lambda: provider,
            )
        )
        assert canary["status"] == "admitted"
        assert canary["scored"] is False
        assert provider.requests[0].instructions == prompt
        assert "private_terms" not in provider.requests[0].input_text


def test_qwen_holdout_favorable_effect_is_qualified_and_publishable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root, _ = _synthetic_campaign(tmp_path, favorable=True)

    comparison = build_comparison(run_root=root)

    assert comparison["readiness"]["holdout_diagnostic_qualified"] is True
    assert comparison["diagnostic"]["status"] == "residual_capability_gain_supported"
    regret = comparison["effects_v2_minus_control"]["regret_to_upper_bound_usd"]
    assert regret["world_cluster_mean"] == -5.0
    assert regret["world_cluster_bootstrap_95_interval"] == [-5.0, -5.0]
    assert comparison["effects_v2_minus_control"]["feasible"][
        "world_cluster_mean"
    ] == 1.0
    assert comparison["residual_failure_diagnostics"]["control"][
        "violation_families"
    ]["minimum_service_not_met"] == 18

    publication = tmp_path / "evidence" / CAMPAIGN_ID
    manifest = publish_campaign(run_root=root, publication_root=publication)
    assert manifest["diagnostic_status"] == "residual_capability_gain_supported"
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(path.read_text() for path in publication.rglob("*.json"))
    assert "private_terms" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert campaign_module.V2_PROMPT not in serialized


def test_qwen_holdout_unfavorable_effect_remains_integrity_qualified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root, _ = _synthetic_campaign(tmp_path, favorable=False)

    comparison = build_comparison(run_root=root)

    assert comparison["readiness"]["holdout_diagnostic_qualified"] is True
    assert (
        comparison["diagnostic"]["status"]
        == "residual_capability_gain_not_supported"
    )
    assert comparison["diagnostic"]["checks"]["regret_upper_below_zero"] is False


def test_unknown_supplier_diagnostic_ignores_inactive_superset_fields() -> None:
    case = json.loads(OPAQUE_PATHS[0].read_text())
    valid_supplier = case["payload"]["suppliers"][0]["supplier_id"]
    rows = [
        {
            "case_id": case["case_id"],
            "action_trace": [
                {
                    "action": "submit_award",
                    "supplier_id": "",
                    "award_lines": [],
                },
                {
                    "action": "request_quote",
                    "supplier_id": valid_supplier,
                },
                {
                    "action": "request_sample",
                    "supplier_id": "supplier_not_in_case",
                },
            ],
        }
    ]

    assert campaign_module._unknown_supplier_attempt_count(rows) == 1


def test_decision_diagnostic_separates_defer_from_feasible_award() -> None:
    case = json.loads(OPAQUE_PATHS[0].read_text())
    supplier_ids = [
        supplier["supplier_id"] for supplier in case["payload"]["suppliers"]
    ]
    rows = [
        {
            "case_id": case["case_id"],
            "decision": "award",
            "feasible": False,
            "action_trace": [
                {
                    "action": "submit_award",
                    "award_lines": [
                        {"offer_id": f"offer_{supplier_ids[0]}_v1", "quantity": 10},
                        {"offer_id": f"offer_{supplier_ids[1]}_v1", "quantity": 10},
                    ],
                }
            ],
        },
        {
            "case_id": case["case_id"],
            "decision": "defer",
            "feasible": True,
            "action_trace": [{"action": "defer"}],
        },
    ]

    diagnostic = campaign_module._decision_diagnostics(rows)

    assert diagnostic["award_decision_count"] == 1
    assert diagnostic["feasible_award_count"] == 0
    assert diagnostic["feasible_defer_count"] == 1
    assert diagnostic["split_required_submission_count"] == 1
    assert diagnostic["split_award_attempt_count"] == 1


def test_qwen_holdout_rejects_lower_runtime_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="below the frozen hard total ceiling"):
        asyncio.run(
            campaign_module.run_campaign(
                run_root=tmp_path / "runs" / CAMPAIGN_ID / "attempt_001",
                max_spend_usd=HARD_TOTAL_COST_CEILING_USD - 0.01,
            )
        )
