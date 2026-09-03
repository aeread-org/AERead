from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.blinded_invariance import (
    PAIRED_INFERENCE_SEEDS,
)
from aeread_families.procurement_allocation.case_matrix import CASE_SLUGS
from aeread_families.procurement_allocation.runner import SequenceResponseProvider
from aeread_families.procurement_allocation.strategy_scaffold import (
    CAMPAIGN_ID,
    PANELS,
    PROMPT_ID,
    STRATEGY_PROMPT,
    TREATMENT_ID,
    build_plan,
    build_strategy_comparison,
    publish_strategy_campaign,
    run_admission_canary,
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
    assert "private_terms" not in request.input_text


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
