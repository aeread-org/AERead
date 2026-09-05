from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.strategy_scaffold as scaffold_module
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.blinded_invariance import (
    PAIRED_INFERENCE_SEEDS,
)
from aeread_families.procurement_allocation.case_matrix import (
    CASE_SLUGS,
    CASE_VARIANCE_PATHS,
)
from aeread_families.procurement_allocation.policy_baselines import (
    PublicObservationPolicyProvider,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider
from aeread_families.procurement_allocation.strategy_scaffold import (
    CAMPAIGN_ID,
    GLM_CLOUDFLARE_CANDIDATE,
    GLM_PARASAIL_CANDIDATE,
    GLM_REKA_CANDIDATE,
    PANELS,
    PARASAIL_INFERENCE_SEEDS,
    PARASAIL_LABELED_CONTROL_CAMPAIGN_ID,
    PARASAIL_OPAQUE_CONTROL_CAMPAIGN_ID,
    PARASAIL_STRATEGY_CAMPAIGN_ID,
    PROMPT_ID,
    STRATEGY_PROMPT,
    TREATMENT_ID,
    build_plan,
    build_strategy_comparison,
    publish_strategy_campaign,
    run_admission_canary,
    strategy_campaign_id,
)


def _write_summary(
    root: Path,
    *,
    campaign_id: str,
    panel: str,
    treatment: bool,
) -> None:
    if panel == "labeled_original":
        margin = 15.0 if treatment else 10.0
        kits = 17 if treatment else 15
    else:
        margin = 14.0 if treatment else 8.0
        kits = 17 if treatment else 14
    rows = []
    for slug in CASE_SLUGS:
        for seed in PAIRED_INFERENCE_SEEDS:
            row = {
                "case_id": f"procurement_allocation_v1.{panel}.{slug}",
                "case_content_sha256": hashlib.sha256(
                    f"{panel}:{slug}".encode()
                ).hexdigest(),
                "inference_seed": seed,
                "status": "completed",
                "decision": "award",
                "termination_reason": "award_submitted",
                "feasible": treatment,
                "completed_kits": kits,
                "contribution_margin_usd": margin,
                "upper_bound_usd": 20.0,
                "regret_to_upper_bound_usd": 20.0 - margin,
                "violations": [],
                "elapsed_environment_days": 2,
                "action_count": 5,
                "action_trace": [{"ordinal": 1, "action": "request_quote"}],
                "elapsed_seconds": 1.0,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "cost_usd": 0.001,
                "resolved_models": ["z-ai/glm-5.3-flash-20260826"],
                "receipt_sha256": "a" * 64,
                "receipt_replayed": True,
                "replay_level": "provider_response",
            }
            row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            rows.append(row)
    plan = {
        "schema_version": "test/0.1",
        "campaign_id": campaign_id,
        "inference_seeds": list(PAIRED_INFERENCE_SEEDS),
        "model": "z-ai/glm-5.3-flash",
        "revision": "z-ai/glm-5.3-flash-20260826",
        "provider": "Morph",
        "quantization": "fp8",
        "harness": "minimal_chat/1.0 (fixed transport; not an estimand)",
    }
    if treatment:
        plan["prompt"] = {
            "prompt_id": PROMPT_ID,
            "sha256": hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest(),
            "treatment_id": TREATMENT_ID,
        }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    artifact = {
        "schema_version": "test/0.1",
        "plan": plan,
        "preflight": {
            "candidate_id": "glm53_flash_morph",
            "model": "z-ai/glm-5.3-flash",
            "revision": "z-ai/glm-5.3-flash-20260826",
            "route_provider": "Morph",
        },
        "summary": {
            "row_count": 18,
            "completed_trajectory_count": 18,
            "operational_failure_count": 0,
            "unattempted_trajectory_count": 0,
            "total_cost_usd": 0.018,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    root.mkdir(parents=True)
    (root / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def _synthetic_campaign(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    treatment_root = (
        tmp_path
        / "runs"
        / "procurement_allocation"
        / CAMPAIGN_ID
        / "qualification_attempt_001"
    )
    control_roots = {}
    for panel, spec in PANELS.items():
        control_root = tmp_path / "controls" / panel
        control_roots[panel] = control_root
        _write_summary(
            control_root,
            campaign_id=str(spec["control_campaign_id"]),
            panel=panel,
            treatment=False,
        )
        _write_summary(
            treatment_root / panel,
            campaign_id=str(spec["treatment_campaign_id"]),
            panel=panel,
            treatment=True,
        )
    return treatment_root, control_roots


def test_strategy_plan_binds_prompt_and_declares_paired_analysis() -> None:
    plan = build_plan(max_parallel_cells=1)

    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["planned_trajectory_count"] == 36
    assert plan["independent_case_count"] == 6
    assert plan["inference_seeds"] == list(PAIRED_INFERENCE_SEEDS)
    assert plan["max_parallel_cells"] == 1
    assert plan["batch_size"] == 6
    assert "adaptive development treatment" in plan["development_status"]
    assert plan["prompt"] == {
        "prompt_id": PROMPT_ID,
        "sha256": hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest(),
        "control_prompt_sha256": plan["prompt"]["control_prompt_sha256"],
    }
    assert plan["conservative_scored_cost_ceiling_usd"] == pytest.approx(0.4788)
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.5088)
    for panel in PANELS:
        assert plan["panels"][panel]["prompt"]["treatment_id"] == TREATMENT_ID
        assert plan["panels"][panel]["planned_trajectory_count"] == 18
        assert plan["panels"][panel]["max_new_trajectories_per_invocation"] == 6


def test_strategy_plan_seals_alternate_route_under_distinct_campaign() -> None:
    campaign_id = strategy_campaign_id(GLM_REKA_CANDIDATE)

    plan = build_plan(candidate=GLM_REKA_CANDIDATE)

    assert campaign_id != CAMPAIGN_ID
    assert plan["campaign_id"] == campaign_id
    assert plan["candidate_id"] == "glm53_flash_reka"
    assert plan["provider"] == "Reka"
    assert plan["quantization"] == "fp8"
    assert plan["conservative_scored_cost_ceiling_usd"] == pytest.approx(0.54)
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.57)
    assert plan["control_campaign_ids"] == {
        "labeled_original": (
            "procurement_allocation_glm53_flash_reka_case_variance_v2"
        ),
        "opaque_reordered": (
            "procurement_allocation_glm53_flash_reka_blinded_invariance_v1"
        ),
    }
    for panel, panel_plan in plan["panels"].items():
        assert panel_plan["campaign_id"] == f"{campaign_id}.{panel}"
        assert panel_plan["provider"] == "Reka"

    with pytest.raises(ValueError, match="does not match the sealed strategy candidate"):
        build_plan(candidate=GLM_REKA_CANDIDATE, campaign_id=CAMPAIGN_ID)


def test_strategy_plan_seals_cloudflare_route() -> None:
    campaign_id = strategy_campaign_id(GLM_CLOUDFLARE_CANDIDATE)

    plan = build_plan(candidate=GLM_CLOUDFLARE_CANDIDATE)

    assert plan["campaign_id"] == campaign_id
    assert plan["candidate_id"] == "glm53_flash_cloudflare"
    assert plan["provider"] == "Cloudflare"
    assert plan["quantization"] == "unknown"
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.57)
    assert plan["control_campaign_ids"]["labeled_original"] == (
        "procurement_allocation_glm53_flash_cloudflare_case_variance_v2"
    )


def test_strategy_plan_seals_retry_aware_parasail_route() -> None:
    plan = build_plan(candidate=GLM_PARASAIL_CANDIDATE)

    assert strategy_campaign_id(GLM_PARASAIL_CANDIDATE) == (
        PARASAIL_STRATEGY_CAMPAIGN_ID
    )
    assert plan["campaign_id"] == PARASAIL_STRATEGY_CAMPAIGN_ID
    assert plan["candidate_id"] == "glm53_flash_parasail"
    assert plan["provider"] == "Parasail"
    assert plan["quantization"] == "fp8"
    assert plan["inference_seeds"] == list(PARASAIL_INFERENCE_SEEDS)
    assert plan["control_campaign_ids"] == {
        "labeled_original": PARASAIL_LABELED_CONTROL_CAMPAIGN_ID,
        "opaque_reordered": PARASAIL_OPAQUE_CONTROL_CAMPAIGN_ID,
    }
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.57)
    for panel_plan in plan["panels"].values():
        assert panel_plan["inference_seeds"] == list(PARASAIL_INFERENCE_SEEDS)
        assert panel_plan["retry_policy"] == {
            "owner": "shared_runner",
            "max_action_attempts": 3,
            "retryable_conditions": ["rate_limit", "provider_5xx"],
            "retry_backoff": "exponential_jitter_v1",
            "retry_base_seconds": 2.0,
            "retry_after_max_seconds": 60.0,
            "session_mode": "restart",
            "sdk_retries": 0,
            "cost_boundary": "retry only known-zero-cost provider failures",
        }


def test_strategy_canary_uses_treatment_prompt_and_is_unscored(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "test canary"}),)
    )
    path = tmp_path / "runs" / CAMPAIGN_ID / "admission_canary.json"

    canary = asyncio.run(
        run_admission_canary(path=path, provider_factory=lambda: provider)
    )

    assert canary["status"] == "admitted"
    assert canary["scored"] is False
    assert canary["prompt_id"] == PROMPT_ID
    assert (
        canary["prompt_sha256"] == hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest()
    )
    request = provider.requests[0]
    assert "Ignore supplier IDs and names as quality signals" in request.instructions
    assert "Before considering price" in request.instructions
    assert "Request a sample only from an offer" in request.instructions
    assert "private_terms" not in request.input_text


def test_strategy_canary_seals_alternate_route_identity(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "test canary"}),)
    )
    campaign_id = strategy_campaign_id(GLM_REKA_CANDIDATE)
    path = tmp_path / "runs" / campaign_id / "admission_canary.json"

    canary = asyncio.run(
        run_admission_canary(
            path=path,
            provider_factory=lambda: provider,
            candidate=GLM_REKA_CANDIDATE,
        )
    )

    assert canary["campaign_id"] == campaign_id
    assert canary["route_provider"] == "Reka"
    assert provider.requests[0].provider_metadata["route_provider"] == "Reka"


def test_strategy_campaign_resumes_only_a_failure_free_batch_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = {
        "labeled_original": {
            "case_paths": (CASE_VARIANCE_PATHS[0],),
            "treatment_campaign_id": f"{CAMPAIGN_ID}.labeled_original",
            "control_campaign_id": "unused-control",
        }
    }
    monkeypatch.setattr(scaffold_module, "PANELS", panel)
    monkeypatch.setattr(scaffold_module, "PAIRED_INFERENCE_SEEDS", (11, 12))
    run_root = tmp_path / "runs" / CAMPAIGN_ID / "batched_attempt"
    provider_factory = lambda: PublicObservationPolicyProvider("displayed_price_greedy")
    preflight = lambda _candidate: {"route_verified": True}

    first = asyncio.run(
        scaffold_module.run_strategy_campaign(
            run_root=run_root,
            batch_size=1,
            provider_factory=provider_factory,
            preflight_fn=preflight,
        )
    )
    sealed_canary = (run_root / "admission_canary.json").read_bytes()

    assert first["summary"]["completed_trajectory_count"] == 1
    assert first["summary"]["operational_failure_count"] == 0
    assert first["summary"]["failure_free_checkpoint"] is True

    second = asyncio.run(
        scaffold_module.run_strategy_campaign(
            run_root=run_root,
            batch_size=1,
            resume=True,
            provider_factory=provider_factory,
            preflight_fn=preflight,
        )
    )

    assert second["summary"]["completed_trajectory_count"] == 2
    assert second["summary"]["execution_qualified"] is True
    assert (run_root / "admission_canary.json").read_bytes() == sealed_canary


def test_strategy_comparison_recovers_effects_and_surface_mitigation(
    tmp_path: Path,
) -> None:
    treatment_root, control_roots = _synthetic_campaign(tmp_path)

    comparison = build_strategy_comparison(
        treatment_run_root=treatment_root, control_roots=control_roots
    )

    assert comparison["readiness"]["strategy_comparison_qualified"] is True
    labeled_margin = comparison["panels"]["labeled_original"][
        "aggregate_treatment_minus_control"
    ]["contribution_margin_usd"]
    opaque_margin = comparison["panels"]["opaque_reordered"][
        "aggregate_treatment_minus_control"
    ]["contribution_margin_usd"]
    assert labeled_margin["case_cluster_mean"] == pytest.approx(5.0)
    assert labeled_margin["case_cluster_bootstrap_95_interval"] == [5.0, 5.0]
    assert opaque_margin["case_cluster_mean"] == pytest.approx(6.0)
    margin_surface = comparison["surface_sensitivity"]["contribution_margin_usd"]
    assert margin_surface["control_surface_effect"]["case_cluster_mean"] == -2.0
    assert margin_surface["treatment_surface_effect"]["case_cluster_mean"] == -1.0
    assert margin_surface["difference_in_differences"]["case_cluster_mean"] == 1.0
    assert margin_surface["absolute_surface_gap_reduction"]["case_cluster_mean"] == 1.0
    assert comparison["artifact_sha256"]


def test_strategy_comparison_rejects_retry_policy_mismatch(tmp_path: Path) -> None:
    treatment_root, control_roots = _synthetic_campaign(tmp_path)
    path = treatment_root / "labeled_original" / "summary.json"
    artifact = json.loads(path.read_text())
    artifact["plan"]["retry_policy"] = {
        "owner": "shared_runner",
        "max_action_attempts": 3,
    }
    plan_payload = {
        key: value
        for key, value in artifact["plan"].items()
        if key != "plan_sha256"
    }
    artifact["plan"]["plan_sha256"] = hashlib.sha256(
        canonical_json_bytes(plan_payload)
    ).hexdigest()
    artifact_payload = {
        key: value for key, value in artifact.items() if key != "artifact_sha256"
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact_payload)
    ).hexdigest()
    path.write_bytes(canonical_json_bytes(artifact) + b"\n")

    comparison = build_strategy_comparison(
        treatment_run_root=treatment_root,
        control_roots=control_roots,
    )

    assert comparison["integrity"]["labeled_original_route_and_harness_match"] is False
    assert comparison["readiness"]["strategy_comparison_qualified"] is False


def test_strategy_publication_is_digest_bound_and_sanitized(tmp_path: Path) -> None:
    treatment_root, control_roots = _synthetic_campaign(tmp_path)
    plan = build_plan()
    (treatment_root / "campaign_plan.json").write_bytes(
        canonical_json_bytes(plan) + b"\n"
    )
    canary = {
        "campaign_id": CAMPAIGN_ID,
        "status": "admitted",
        "scored": False,
        "cost_usd": 0.001,
        "prompt_id": PROMPT_ID,
        "prompt_sha256": hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest(),
    }
    canary["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(canary)).hexdigest()
    (treatment_root / "admission_canary.json").write_bytes(
        canonical_json_bytes(canary) + b"\n"
    )
    comparison = build_strategy_comparison(
        treatment_run_root=treatment_root, control_roots=control_roots
    )
    publication_root = tmp_path / "evidence" / CAMPAIGN_ID

    manifest = publish_strategy_campaign(
        run_root=treatment_root,
        publication_root=publication_root,
        comparison=comparison,
    )

    for relative, expected_sha in manifest["artifacts"].items():
        assert (
            hashlib.sha256((publication_root / relative).read_bytes()).hexdigest()
            == expected_sha
        )
    serialized = "\n".join(
        path.read_text() for path in (publication_root / "reports").glob("*.json")
    )
    assert "private_terms" not in serialized
    assert "raw_response" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert STRATEGY_PROMPT not in serialized
    assert (publication_root / "README.md").is_file()
