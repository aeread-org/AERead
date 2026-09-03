from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.confirmatory_campaign as campaign_module
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.confirmatory_campaign import (
    BOOTSTRAP_RESAMPLES,
    CAMPAIGN_ID,
    CONFIRMATORY_RETRY_CONDITIONS,
    FROZEN_CONTROL_PROMPT_SHA256,
    FROZEN_V4_PROMPT_SHA256,
    INFERENCE_SEEDS,
    V1_CAMPAIGN_ID,
    build_confirmatory_comparison,
    build_plan,
    publish_confirmatory_campaign,
    run_admission_canary,
)
from aeread_families.procurement_allocation.policy_baselines import (
    PublicObservationPolicyProvider,
)
from aeread_families.procurement_allocation.runner import (
    PROMPT as CONTROL_PROMPT,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider
from aeread_families.procurement_allocation.strategy_scaffold import (
    PROMPT_ID,
    STRATEGY_PROMPT,
    TREATMENT_ID,
)


def _write_canary(root: Path, *, condition: str) -> None:
    prompt_sha = (
        FROZEN_CONTROL_PROMPT_SHA256
        if condition == "control"
        else FROZEN_V4_PROMPT_SHA256
    )
    value = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "condition": condition,
        "status": "admitted",
        "scored": False,
        "prompt_id": (
            "procurement_allocation_prompt_v1"
            if condition == "control"
            else PROMPT_ID
        ),
        "prompt_sha256": prompt_sha,
        "model": "z-ai/glm-5.3-flash",
        "revision": "z-ai/glm-5.3-flash-20260826",
        "route_provider": "Parasail",
        "resolved_model": "z-ai/glm-5.3-flash-20260826",
        "cost_usd": 0.001,
    }
    value["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    path = root / "canaries" / f"{condition}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_arm_summary(
    root: Path,
    *,
    name: str,
    plan: dict,
    favorable: bool,
) -> None:
    surface = "labeled" if name.startswith("labeled") else "opaque"
    treatment = name.endswith("treatment")
    if favorable:
        feasible = treatment
        margin = 10.0 if treatment else 5.0
    else:
        feasible = True
        margin = 8.0 if treatment else 10.0
    world_pairs = plan["world_pairs"]
    rows = []
    for pair in world_pairs:
        slug = pair["slug"]
        case_id = pair[f"{surface}_case_id"]
        case_sha = pair[f"{surface}_case_content_sha256"]
        for seed in plan["inference_seeds"]:
            row = {
                "case_id": case_id,
                "case_content_sha256": case_sha,
                "inference_seed": seed,
                "status": "completed",
                "decision": "award",
                "termination_reason": "submitted",
                "feasible": feasible,
                "completed_kits": 18 if treatment else 16,
                "contribution_margin_usd": margin,
                "upper_bound_usd": 20.0,
                "regret_to_upper_bound_usd": 20.0 - margin,
                "violations": [] if feasible else [f"{slug}.synthetic_failure"],
                "elapsed_environment_days": 4,
                "action_count": 5,
                "action_trace": [{"ordinal": 1, "action": "request_quote"}],
                "elapsed_seconds": 1.0,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "cost_usd": 0.001,
                "provider_call_count": 5,
                "runner_retry_count": 0,
                "retry_condition_counts": {},
                "resolved_models": ["z-ai/glm-5.3-flash-20260826"],
                "receipt_sha256": "a" * 64,
                "receipt_replayed": True,
                "replay_level": "provider_response",
            }
            row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            rows.append(row)
    artifact = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": plan["arms"][name],
        "preflight": {
            "candidate_id": "glm53_flash_parasail",
            "model": "z-ai/glm-5.3-flash",
            "revision": "z-ai/glm-5.3-flash-20260826",
            "route_provider": "Parasail",
        },
        "summary": {
            "planned_trajectory_count": len(rows),
            "row_count": len(rows),
            "unattempted_trajectory_count": 0,
            "completed_trajectory_count": len(rows),
            "operational_failure_count": 0,
            "total_cost_usd": len(rows) * 0.001,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    path = root / "arms" / name / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(artifact) + b"\n")


def _synthetic_campaign(
    tmp_path: Path, *, favorable: bool
) -> tuple[Path, dict]:
    root = tmp_path / "runs" / "procurement_allocation" / CAMPAIGN_ID / "attempt_001"
    plan = build_plan()
    root.mkdir(parents=True)
    (root / "campaign_plan.json").write_bytes(canonical_json_bytes(plan) + b"\n")
    for name in plan["arm_execution_order"]:
        _write_arm_summary(root, name=name, plan=plan, favorable=favorable)
    _write_canary(root, condition="control")
    _write_canary(root, condition="treatment")
    return root, plan


def test_confirmatory_plan_freezes_distribution_route_and_analysis() -> None:
    plan = build_plan()

    assert plan["freeze_status"] == "confirmatory_frozen_before_live_execution"
    assert plan["planned_trajectory_count"] == 144
    assert plan["independent_world_count"] == 12
    assert plan["inference_seeds"] == list(INFERENCE_SEEDS)
    assert plan["inference_seeds"] == [307864013, 878679105, 611671506]
    assert plan["inference_seed_derivation_campaign_id"] == V1_CAMPAIGN_ID
    assert len(set(INFERENCE_SEEDS)) == 3
    assert plan["prompts"]["control_sha256"] == FROZEN_CONTROL_PROMPT_SHA256
    assert plan["prompts"]["treatment_sha256"] == FROZEN_V4_PROMPT_SHA256
    assert plan["conservative_scored_cost_ceiling_usd"] == pytest.approx(2.16)
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(2.22)
    assert plan["hard_scored_cost_ceiling_usd"] == pytest.approx(4.32)
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(4.38)
    assert plan["lineage"]["scientific_contract"] == "unchanged_from_v1"
    assert plan["analysis"]["bootstrap_resamples"] == BOOTSTRAP_RESAMPLES
    assert plan["analysis"]["no_early_efficacy_stopping"] is True
    assert plan["arm_execution_order"] == [
        "labeled_control",
        "opaque_control",
        "labeled_treatment",
        "opaque_treatment",
    ]
    assert all(arm["planned_trajectory_count"] == 36 for arm in plan["arms"].values())
    assert all(
        arm["retry_policy"]["retryable_conditions"]
        == list(CONFIRMATORY_RETRY_CONDITIONS)
        for arm in plan["arms"].values()
    )


def test_confirmatory_plan_rejects_prompt_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(campaign_module, "STRATEGY_PROMPT", STRATEGY_PROMPT + " drift")
    with pytest.raises(ValueError, match="frozen V4 treatment prompt changed"):
        campaign_module.build_plan()


def test_confirmatory_canaries_use_each_frozen_prompt(tmp_path: Path) -> None:
    for condition, prompt in (
        ("control", CONTROL_PROMPT),
        ("treatment", STRATEGY_PROMPT),
    ):
        provider = SequenceResponseProvider(
            (json.dumps({"action": "defer", "reason": "test canary"}),)
        )
        canary = asyncio.run(
            run_admission_canary(
                path=tmp_path / f"{condition}.json",
                condition=condition,
                provider_factory=lambda: provider,
            )
        )
        assert canary["status"] == "admitted"
        assert canary["scored"] is False
        assert canary["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        assert provider.requests[0].instructions == prompt
        assert "private_terms" not in provider.requests[0].input_text


def test_confirmatory_comparison_supports_constant_favorable_effect_and_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root, _ = _synthetic_campaign(tmp_path, favorable=True)

    comparison = build_confirmatory_comparison(run_root=root)

    assert comparison["readiness"]["confirmatory_evidence_qualified"] is True
    assert comparison["confirmation"]["status"] == "supported"
    regret = comparison["effects"]["overall_treatment_minus_control"][
        "regret_to_upper_bound_usd"
    ]
    assert regret["world_cluster_mean"] == -5.0
    assert regret["world_cluster_bootstrap_95_interval"] == [-5.0, -5.0]
    assert comparison["effects"]["overall_treatment_minus_control"]["feasible"][
        "world_cluster_mean"
    ] == 1.0

    publication = tmp_path / "evidence" / CAMPAIGN_ID
    manifest = publish_confirmatory_campaign(
        run_root=root, publication_root=publication
    )
    assert manifest["confirmation_status"] == "supported"
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(path.read_text() for path in publication.rglob("*.json"))
    assert "private_terms" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert STRATEGY_PROMPT not in serialized


def test_confirmatory_unfavorable_result_remains_eligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root, _ = _synthetic_campaign(tmp_path, favorable=False)

    comparison = build_confirmatory_comparison(run_root=root)

    assert comparison["readiness"]["confirmatory_evidence_qualified"] is True
    assert comparison["confirmation"]["status"] == "not_supported"
    assert comparison["confirmation"]["checks"]["primary_regret_upper_below_zero"] is False


def test_confirmatory_comparison_rejects_arm_plan_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 100)
    root, _ = _synthetic_campaign(tmp_path, favorable=True)
    path = root / "arms" / "opaque_treatment" / "summary.json"
    artifact = json.loads(path.read_text())
    artifact["plan"]["retry_policy"]["max_action_attempts"] = 2
    payload = {
        key: item for key, item in artifact["plan"].items() if key != "plan_sha256"
    }
    artifact["plan"]["plan_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    payload = {
        key: item for key, item in artifact.items() if key != "artifact_sha256"
    }
    artifact["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    path.write_bytes(canonical_json_bytes(artifact) + b"\n")

    comparison = build_confirmatory_comparison(run_root=root)

    assert comparison["readiness"]["confirmatory_evidence_qualified"] is False
    assert comparison["confirmation"]["status"] == "ineligible"
    assert comparison["integrity"]["opaque_treatment_model_plan_matches_frozen"] is False


def test_confirmatory_runner_checkpoints_without_replacing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = CASE_VARIANCE_PATHS[0]
    monkeypatch.setattr(campaign_module, "CASE_SLUGS", ("deadline_cost",))
    monkeypatch.setattr(campaign_module, "LABELED_PATHS", (path,))
    monkeypatch.setattr(campaign_module, "OPAQUE_PATHS", (path,))
    monkeypatch.setattr(campaign_module, "INFERENCE_SEEDS", (11, 12))
    monkeypatch.setattr(campaign_module, "CONFIRMATORY_BATCH_SIZE", 2)

    def tiny_specs() -> dict[str, dict]:
        return {
            f"{surface}_{condition}": {
                "surface": surface,
                "condition": condition,
                "case_paths": (path,),
                "prompt": CONTROL_PROMPT if condition == "control" else STRATEGY_PROMPT,
                "prompt_id": (
                    "procurement_allocation_prompt_v1"
                    if condition == "control"
                    else PROMPT_ID
                ),
                "treatment_id": (
                    "unscaffolded_control" if condition == "control" else TREATMENT_ID
                ),
            }
            for surface in ("labeled", "opaque")
            for condition in ("control", "treatment")
        }

    monkeypatch.setattr(campaign_module, "_arm_specs", tiny_specs)
    root = tmp_path / "runs" / CAMPAIGN_ID / "checkpoint"
    provider_factory = lambda: PublicObservationPolicyProvider("displayed_price_greedy")
    preflight = lambda _candidate: {"route_verified": True}

    first = asyncio.run(
        campaign_module.run_confirmatory_campaign(
            run_root=root,
            provider_factory=provider_factory,
            preflight_fn=preflight,
        )
    )
    canaries = {
        condition: (root / "canaries" / f"{condition}.json").read_bytes()
        for condition in ("control", "treatment")
    }
    assert first["summary"]["completed_trajectory_count"] == 2
    assert first["summary"]["failure_free_checkpoint"] is True

    second = asyncio.run(
        campaign_module.run_confirmatory_campaign(
            run_root=root,
            resume=True,
            provider_factory=provider_factory,
            preflight_fn=preflight,
        )
    )
    assert second["summary"]["completed_trajectory_count"] == 4
    assert all(
        (root / "canaries" / f"{condition}.json").read_bytes() == canaries[condition]
        for condition in canaries
    )
