from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread_families.procurement_allocation.qwen235b_case_campaign import (
    CAMPAIGN_ID,
    HARD_TOTAL_COST_CEILING_USD,
    PARENT_EVIDENCE_FILE_SHA256,
    PARENT_EVIDENCE_PATH,
    QWEN235B_CANDIDATE,
    build_plan,
    run_admission_canary,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_qwen235b_plan_freezes_adaptive_matched_panel() -> None:
    plan = build_plan()
    scored = plan["scored_plan"]

    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["candidate"] == {
        "candidate_id": "qwen3_235b_a22b_instruct_2507_atlascloud",
        "model": "qwen/qwen3-235b-a22b-2507",
        "revision": "qwen/qwen3-235b-a22b-07-25",
        "provider": "AtlasCloud",
        "quantization": "fp8",
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "model_card_url": (
            "https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507"
        ),
    }
    assert plan["lineage"]["selection_status"] == "adaptive_model_follow_up"
    assert plan["lineage"]["parent_evidence_file_sha256"] == (
        PARENT_EVIDENCE_FILE_SHA256
    )
    assert scored["planned_trajectory_count"] == 18
    assert scored["max_new_trajectories_per_invocation"] == 6
    assert scored["max_parallel_cells"] == 1
    assert scored["max_cost_usd_per_trajectory"] == pytest.approx(0.03)
    assert scored["conservative_cost_ceiling_usd"] == pytest.approx(0.42912)
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.45912)
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(0.57)
    assert plan["plan_sha256"] == (
        "9b7b2fbea8200eb9900ee063bf34255c3162f9aa7e733a5d76adb7224507a78f"
    )


def test_qwen235b_parent_evidence_binding_matches_tracked_file() -> None:
    path = REPOSITORY_ROOT / PARENT_EVIDENCE_PATH

    assert hashlib.sha256(path.read_bytes()).hexdigest() == PARENT_EVIDENCE_FILE_SHA256


def test_qwen235b_candidate_reaches_exact_request_builder(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "route test"}),)
    )

    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "canary.json",
            provider_factory=lambda: provider,
        )
    )

    request = provider.requests[0]
    assert canary["status"] == "admitted"
    assert canary["cost_accounting"] == "exact"
    assert request.model == QWEN235B_CANDIDATE.route.model
    assert request.revision == QWEN235B_CANDIDATE.route.revision
    assert request.provider_metadata["route_provider"] == "AtlasCloud"
    assert request.provider_metadata["quantization"] == "fp8"
    assert request.reasoning_effort is None
    assert request.max_cost_usd == pytest.approx(0.03)


def test_qwen235b_hard_total_ceiling_stays_within_goal_budget() -> None:
    assert HARD_TOTAL_COST_CEILING_USD == pytest.approx(0.57)
    assert HARD_TOTAL_COST_CEILING_USD < 1.0
