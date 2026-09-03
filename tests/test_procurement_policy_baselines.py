from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.blinded_invariance import (
    CAMPAIGN_ID as BLINDED_CAMPAIGN_ID,
)
from aeread_families.procurement_allocation.model_campaign import (
    CAMPAIGN_ID as LABELED_CAMPAIGN_ID,
)
from aeread_families.procurement_allocation.policy_baselines import (
    CAMPAIGN_ID,
    POLICY_IDS,
    build_glm_policy_context,
    build_plan,
    publish_policy_baselines,
    run_policy_baselines,
)


def _write_model_summary(
    root: Path,
    *,
    campaign_id: str,
    panel: str,
    policy_rows: list[dict],
    margin_gap: float,
) -> None:
    rows = []
    for policy_row in policy_rows:
        if (
            policy_row["panel"] != panel
            or policy_row["policy_id"] != "displayed_price_greedy"
        ):
            continue
        for seed in (11, 12, 13):
            row = {
                "case_id": (
                    f"procurement_allocation_v1.{panel}.{policy_row['case_slug']}"
                ),
                "case_content_sha256": "a" * 64,
                "inference_seed": seed,
                "status": "completed",
                "feasible": False,
                "completed_kits": policy_row["completed_kits"] - 2,
                "contribution_margin_usd": (
                    policy_row["contribution_margin_usd"] - margin_gap
                ),
                "upper_bound_usd": policy_row["upper_bound_usd"],
                "regret_to_upper_bound_usd": (
                    policy_row["regret_to_upper_bound_usd"] + margin_gap
                ),
                "receipt_replayed": True,
            }
            row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            rows.append(row)
    plan = {"campaign_id": campaign_id, "plan_sha256": "b" * 64}
    artifact = {
        "plan": plan,
        "summary": {
            "completed_trajectory_count": 18,
            "feasible_count": 0,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    root.mkdir(parents=True)
    (root / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def test_policy_plan_declares_zero_cost_paired_surface_controls() -> None:
    plan = build_plan()

    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["policy_ids"] == list(POLICY_IDS)
    assert plan["planned_trajectory_count"] == 48
    assert plan["independent_case_count"] == 6
    assert plan["cost_usd"] == 0.0
    assert plan["hidden_state_access"] is False
    assert len(plan["panels"]["labeled_original"]) == 6
    assert len(plan["panels"]["opaque_reordered"]) == 6


def test_public_policy_campaign_replays_and_publishes_without_hidden_state(
    tmp_path: Path,
) -> None:
    run_root = (
        tmp_path
        / "runs"
        / "procurement_allocation"
        / CAMPAIGN_ID
        / "qualification_attempt_001"
    )
    artifact = asyncio.run(run_policy_baselines(run_root=run_root))

    summary = artifact["summary"]
    assert summary["readiness"]["policy_baselines_qualified"] is True
    assert summary["completed_trajectory_count"] == 48
    assert summary["operational_failure_count"] == 0
    assert summary["integrity"] == {
        "all_rows_present": True,
        "all_rows_completed": True,
        "all_receipts_replayed": True,
        "zero_provider_cost": True,
        "all_policy_pairs_present": True,
        "all_upper_bounds_invariant": True,
    }
    assert all(row["cost_usd"] == 0.0 for row in artifact["rows"])
    assert all(row["receipt_replayed"] is True for row in artifact["rows"])
    assert all(
        action["action"] != "unparseable"
        for row in artifact["rows"]
        for action in row["action_trace"]
    )

    paired = summary["paired_invariance"]
    for policy_id in ("defer", "displayed_price_greedy", "listing_claim_fit"):
        assert paired[policy_id]["pair_count"] == 6
        assert paired[policy_id]["mean_contribution_margin_delta_usd"] == 0.0
        assert all(pair["outcome_invariant"] for pair in paired[policy_id]["pairs"])
    assert paired["semantic_hint"][
        "mean_contribution_margin_delta_usd"
    ] == pytest.approx(4.013839215)
    assert (
        sum(not pair["outcome_invariant"] for pair in paired["semantic_hint"]["pairs"])
        == 3
    )

    labeled_model_root = tmp_path / "model" / "labeled"
    blinded_model_root = tmp_path / "model" / "blinded"
    _write_model_summary(
        labeled_model_root,
        campaign_id=LABELED_CAMPAIGN_ID,
        panel="labeled_original",
        policy_rows=artifact["rows"],
        margin_gap=10.0,
    )
    _write_model_summary(
        blinded_model_root,
        campaign_id=BLINDED_CAMPAIGN_ID,
        panel="opaque_reordered",
        policy_rows=artifact["rows"],
        margin_gap=20.0,
    )
    context = build_glm_policy_context(
        policy_artifact=artifact,
        labeled_run_root=labeled_model_root,
        blinded_run_root=blinded_model_root,
    )
    assert context["readiness"]["model_context_qualified"] is True
    labeled_margin = context["comparisons"]["labeled_original"]["aggregate"][
        "contribution_margin_usd"
    ]
    assert labeled_margin["case_cluster_mean_policy_minus_glm"] == pytest.approx(10.0)
    assert labeled_margin["case_cluster_bootstrap_95_interval"] == pytest.approx(
        [10.0, 10.0]
    )
    assert context["comparisons"]["opaque_reordered"]["aggregate"][
        "contribution_margin_usd"
    ]["case_cluster_mean_policy_minus_glm"] == pytest.approx(20.0)

    publication_root = tmp_path / "evidence" / CAMPAIGN_ID
    manifest = publish_policy_baselines(
        run_root=run_root,
        publication_root=publication_root,
        model_context=context,
    )
    for relative_path, expected_sha in manifest["artifacts"].items():
        assert (
            hashlib.sha256((publication_root / relative_path).read_bytes()).hexdigest()
            == expected_sha
        )
    serialized = (publication_root / "reports" / "results.json").read_text()
    assert "private_terms" not in serialized
    assert "raw_response" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert '"request_sha256s"' in serialized
    assert "reports/glm_context.json" in manifest["artifacts"]


def test_policy_campaign_refuses_to_replace_an_existing_attempt(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / CAMPAIGN_ID / "qualification_attempt_001"
    run_root.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="already exists"):
        asyncio.run(run_policy_baselines(run_root=run_root))
