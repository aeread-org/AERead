from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread_families.procurement_allocation.qwen235b_constraint_v2_campaign import (
    CAMPAIGN_ID,
    HARD_TOTAL_COST_CEILING_USD,
    PARENT_EVIDENCE_FILE_SHA256,
    PARENT_EVIDENCE_PATH,
    PROMPT_ID,
    SPEC,
    TREATMENT_ID,
    V2_PROMPT,
    build_plan,
    run_admission_canary,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider
from aeread_families.procurement_allocation.strategy_scaffold import STRATEGY_PROMPT


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_constraint_v2_plan_freezes_message_contract_repair() -> None:
    plan = build_plan()
    scored = plan["scored_plan"]

    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["lineage"]["selection_status"] == "adaptive_action_contract_repair"
    assert plan["lineage"]["parent_evidence_file_sha256"] == (
        PARENT_EVIDENCE_FILE_SHA256
    )
    assert V2_PROMPT.startswith(STRATEGY_PROMPT)
    assert 'non-empty `message`' in V2_PROMPT
    assert scored["prompt"] == {
        "prompt_id": PROMPT_ID,
        "sha256": hashlib.sha256(V2_PROMPT.encode()).hexdigest(),
        "treatment_id": TREATMENT_ID,
    }
    assert scored["planned_trajectory_count"] == 18
    assert scored["max_new_trajectories_per_invocation"] == 6
    assert scored["max_parallel_cells"] == 1
    assert scored["max_cost_usd_per_trajectory"] == pytest.approx(0.03)
    assert scored["conservative_cost_ceiling_usd"] == pytest.approx(0.44352)
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.47352)
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(0.57)
    assert plan["plan_sha256"] == (
        "b08c0d86956ce522b7bd401d617acf110fabea0f4637b077749e7722043ff308"
    )
    assert scored["plan_sha256"] == (
        "b94067f4cab43bc1b885061e229b669b7986d715080a7f48cfdb09cbc437b24a"
    )


def test_constraint_v2_parent_binding_matches_tracked_file() -> None:
    path = REPOSITORY_ROOT / PARENT_EVIDENCE_PATH

    assert hashlib.sha256(path.read_bytes()).hexdigest() == PARENT_EVIDENCE_FILE_SHA256


def test_constraint_v2_prompt_reaches_exact_request_builder(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "prompt test"}),)
    )

    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "canary.json",
            provider_factory=lambda: provider,
        )
    )

    request = provider.requests[0]
    assert canary["status"] == "admitted"
    assert request.instructions == V2_PROMPT
    assert request.model == SPEC.candidate.route.model
    assert request.provider_metadata["route_provider"] == "Google"
    assert request.max_cost_usd == pytest.approx(0.03)


def test_constraint_v2_hard_total_ceiling_stays_within_goal_budget() -> None:
    assert HARD_TOTAL_COST_CEILING_USD == pytest.approx(0.57)
    assert HARD_TOTAL_COST_CEILING_USD < 1.0
