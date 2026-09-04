from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.negotiation_worksheet_campaign as campaign_module
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.confirmatory_campaign import (
    FROZEN_V4_PROMPT_SHA256,
    INFERENCE_SEEDS as CONFIRMATORY_SEEDS,
)
from aeread_families.procurement_allocation.negotiation_worksheet_campaign import (
    CAMPAIGN_ID,
    FROZEN_WORKSHEET_PROMPT_SHA256,
    INFERENCE_SEEDS,
    PROMPT_ID,
    TREATMENT_ID,
    WORKSHEET_PROMPT,
    build_plan,
    build_worksheet_comparison,
    publish_worksheet_campaign,
    run_admission_canary,
)
from aeread_families.procurement_allocation.policy_baselines import (
    PublicObservationPolicyProvider,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider
from aeread_families.procurement_allocation.strategy_scaffold import STRATEGY_PROMPT


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _write_canary(root: Path) -> None:
    value = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "condition": "treatment",
        "status": "admitted",
        "scored": False,
        "prompt_id": PROMPT_ID,
        "prompt_sha256": FROZEN_WORKSHEET_PROMPT_SHA256,
        "model": "z-ai/glm-5.3-flash",
        "revision": "z-ai/glm-5.3-flash-20260826",
        "route_provider": "Parasail",
        "resolved_model": "z-ai/glm-5.3-flash-20260826",
        "cost_usd": 0.001,
    }
    value["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    path = root / "canaries" / "treatment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _parent_rows(surface: str) -> list[dict]:
    path = (
        REPOSITORY_ROOT
        / "evidence"
        / "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2"
        / "reports"
        / f"{surface}_treatment.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def _write_arm_summary(root: Path, *, name: str, plan: dict, favorable: bool) -> None:
    """Synthesize a worksheet arm by copying the sealed V4 rows and shifting regret.

    Copying the parent action traces keeps the negotiation diagnostics replayable.
    """
    surface = "labeled" if name.startswith("labeled") else "opaque"
    rows = []
    for parent in _parent_rows(surface):
        row = {
            key: parent[key]
            for key in parent
            if key not in {"result_sha256", "cost_usd", "elapsed_seconds"}
        }
        if favorable and row["feasible"]:
            row["contribution_margin_usd"] = float(row["upper_bound_usd"])
            row["regret_to_upper_bound_usd"] = 0.0
        row["cost_usd"] = 0.001
        row["elapsed_seconds"] = 1.0
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
    artifact["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(artifact)).hexdigest()
    path = root / "arms" / name / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(artifact) + b"\n")


def _synthetic_campaign(tmp_path: Path, *, favorable: bool) -> tuple[Path, dict]:
    root = tmp_path / "runs" / "procurement_allocation" / CAMPAIGN_ID / "attempt_001"
    plan = build_plan()
    root.mkdir(parents=True)
    (root / "campaign_plan.json").write_bytes(canonical_json_bytes(plan) + b"\n")
    for name in plan["arm_execution_order"]:
        _write_arm_summary(root, name=name, plan=plan, favorable=favorable)
    _write_canary(root)
    return root, plan


def test_worksheet_prompt_extends_frozen_v4_and_is_frozen() -> None:
    assert WORKSHEET_PROMPT.startswith(STRATEGY_PROMPT)
    assert hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest() == FROZEN_V4_PROMPT_SHA256
    assert hashlib.sha256(WORKSHEET_PROMPT.encode()).hexdigest() == FROZEN_WORKSHEET_PROMPT_SHA256
    assert "working_capital_horizon_days" in WORKSHEET_PROMPT
    assert "proposes only that single term" in WORKSHEET_PROMPT


def test_plan_freezes_parent_control_seeds_and_ceilings() -> None:
    plan = build_plan()
    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["arm_execution_order"] == ["labeled_worksheet", "opaque_worksheet"]
    assert plan["planned_trajectory_count"] == 72
    assert plan["inference_seeds"] == list(CONFIRMATORY_SEEDS) == list(INFERENCE_SEEDS)
    assert plan["independent_world_count"] == 12
    assert plan["prompts"]["treatment_sha256"] == FROZEN_WORKSHEET_PROMPT_SHA256
    assert plan["prompts"]["base_prompt_sha256"] == FROZEN_V4_PROMPT_SHA256
    assert plan["parent_control"]["control_prompt_sha256"] == FROZEN_V4_PROMPT_SHA256
    for surface in ("labeled", "opaque"):
        binding = plan["parent_control"]["arms"][surface]
        path = REPOSITORY_ROOT / binding["report_path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["file_sha256"]
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(72 * 0.03 + 0.03)
    assert plan["conservative_total_cost_ceiling_usd"] < plan["hard_total_cost_ceiling_usd"]
    assert plan["admission_canaries"] == ["treatment"]
    for name in plan["arm_execution_order"]:
        assert plan["arms"][name]["prompt"] == {
            "prompt_id": PROMPT_ID,
            "sha256": FROZEN_WORKSHEET_PROMPT_SHA256,
            "treatment_id": TREATMENT_ID,
        }
    assert build_plan()["plan_sha256"] == plan["plan_sha256"]


def test_plan_rejects_prompt_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(campaign_module, "WORKSHEET_PROMPT", WORKSHEET_PROMPT + " ")
    with pytest.raises(ValueError, match="worksheet prompt changed"):
        build_plan()


def test_canary_uses_worksheet_prompt(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "test canary"}),)
    )
    canary = asyncio.run(
        run_admission_canary(path=tmp_path / "treatment.json", provider_factory=lambda: provider)
    )
    assert canary["status"] == "admitted"
    assert canary["scored"] is False
    assert canary["prompt_sha256"] == FROZEN_WORKSHEET_PROMPT_SHA256
    assert provider.requests[0].instructions == WORKSHEET_PROMPT
    assert "private_terms" not in provider.requests[0].input_text
    again = asyncio.run(
        run_admission_canary(path=tmp_path / "treatment.json", provider_factory=lambda: provider)
    )
    assert again == canary


def test_favorable_comparison_is_supported_and_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    # The favorable fixture shifts outcomes without new traces, so the replay-bound
    # diagnostics would refuse it; they are exercised on genuine rows below.
    calls: list[int] = []
    monkeypatch.setattr(
        campaign_module,
        "_negotiation_diagnostics",
        lambda rows, *, repository_root: calls.append(len(rows)) or {"row_count": len(rows)},
    )
    root, _ = _synthetic_campaign(tmp_path, favorable=True)

    comparison = build_worksheet_comparison(run_root=root)

    assert comparison["readiness"]["worksheet_treatment_qualified"] is True
    assert all(comparison["integrity"].values()), comparison["integrity"]
    assert comparison["support"]["status"] == "supported"
    assert calls == [36, 36, 36, 36]
    regret = comparison["effects"]["overall_worksheet_minus_v4"]["regret_to_upper_bound_usd"]
    assert regret["world_cluster_mean"] < 0.0
    assert regret["world_cluster_bootstrap_95_interval"][1] < 0.0
    feasible = comparison["effects"]["overall_worksheet_minus_v4"]["feasible"]
    assert feasible["world_cluster_mean"] == 0.0

    publication = tmp_path / "evidence" / CAMPAIGN_ID
    manifest = publish_worksheet_campaign(run_root=root, publication_root=publication)
    assert manifest["support_status"] == "supported"
    for relative, digest in manifest["artifacts"].items():
        assert hashlib.sha256((publication / relative).read_bytes()).hexdigest() == digest
    serialized = "\n".join(path.read_text() for path in publication.rglob("*.json"))
    assert "private_terms" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert WORKSHEET_PROMPT not in serialized


def test_null_effect_remains_eligible_but_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign_module, "BOOTSTRAP_RESAMPLES", 1_000)
    root, _ = _synthetic_campaign(tmp_path, favorable=False)
    comparison = build_worksheet_comparison(run_root=root)
    assert comparison["readiness"]["worksheet_treatment_qualified"] is True
    assert comparison["support"]["status"] == "not_supported"
    regret = comparison["effects"]["overall_worksheet_minus_v4"]["regret_to_upper_bound_usd"]
    assert regret["world_cluster_mean"] == 0.0
    diagnostics = comparison["negotiation_diagnostics"]
    for surface in ("labeled", "opaque"):
        control = diagnostics[surface]["v4_control"]
        treatment = diagnostics[surface]["worksheet"]
        assert control["row_count"] == treatment["row_count"] == 36
        assert control["feasible_award_count"] > 0
        assert control["accepted_counter_count"] >= control["feasible_awards_on_negotiated_offer"]
        assert control["counter_attempt_count"] >= control["single_field_counter_count"]
        assert set(control["feasible_term_total_usd"]) == set(campaign_module.REGRET_TERMS)
        assert treatment["feasible_term_total_usd"] == control["feasible_term_total_usd"]


def test_comparison_rejects_plan_drift(tmp_path: Path) -> None:
    root, plan = _synthetic_campaign(tmp_path, favorable=True)
    plan = dict(plan)
    plan["batch_size"] = 99
    (root / "campaign_plan.json").write_bytes(canonical_json_bytes(plan) + b"\n")
    with pytest.raises(ValueError, match="differs from frozen"):
        build_worksheet_comparison(run_root=root)


def test_runner_checkpoints_without_replacing_rows(
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
            f"{surface}_worksheet": {
                "surface": surface,
                "case_paths": (path,),
                "prompt": WORKSHEET_PROMPT,
                "prompt_id": PROMPT_ID,
                "treatment_id": TREATMENT_ID,
            }
            for surface in ("labeled", "opaque")
        }

    monkeypatch.setattr(campaign_module, "_arm_specs", tiny_specs)
    # The tiny plan cannot pair against the twelve-world parent control; the
    # comparison is exercised on genuine rows in the synthetic-campaign tests.
    monkeypatch.setattr(
        campaign_module,
        "build_worksheet_comparison",
        lambda *, run_root, repository_root=None: {"stub": True},
    )
    root = tmp_path / "runs" / CAMPAIGN_ID / "checkpoint"
    provider_factory = lambda: PublicObservationPolicyProvider("displayed_price_greedy")
    preflight = lambda _candidate: {"route_verified": True}

    first = asyncio.run(
        campaign_module.run_worksheet_campaign(
            run_root=root, provider_factory=provider_factory, preflight_fn=preflight
        )
    )
    canary_bytes = (root / "canaries" / "treatment.json").read_bytes()
    assert first["summary"]["completed_trajectory_count"] == 2
    assert first["summary"]["failure_free_checkpoint"] is True

    second = asyncio.run(
        campaign_module.run_worksheet_campaign(
            run_root=root, resume=True, provider_factory=provider_factory, preflight_fn=preflight
        )
    )
    assert second["summary"]["completed_trajectory_count"] == 4
    assert (root / "canaries" / "treatment.json").read_bytes() == canary_bytes
    with pytest.raises(FileExistsError):
        asyncio.run(
            campaign_module.run_worksheet_campaign(
                run_root=root, provider_factory=provider_factory, preflight_fn=preflight
            )
        )
