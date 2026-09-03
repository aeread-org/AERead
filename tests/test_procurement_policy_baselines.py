from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread_families.procurement_allocation.policy_baselines import (
    CAMPAIGN_ID,
    POLICY_IDS,
    build_plan,
    publish_policy_baselines,
    run_policy_baselines,
)


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

    publication_root = tmp_path / "evidence" / CAMPAIGN_ID
    manifest = publish_policy_baselines(
        run_root=run_root, publication_root=publication_root
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


def test_policy_campaign_refuses_to_replace_an_existing_attempt(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / CAMPAIGN_ID / "qualification_attempt_001"
    run_root.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="already exists"):
        asyncio.run(run_policy_baselines(run_root=run_root))
