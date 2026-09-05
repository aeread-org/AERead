from __future__ import annotations
import hashlib
from aeread_families.procurement_allocation.pre_award_confirmatory_campaign import (
    CAMPAIGN_ID, FROZEN_SCAFFOLD_PROMPT_SHA256, FROZEN_V4_PROMPT_SHA256, build_plan,
)
from aeread_families.procurement_allocation.confirmatory_v2_case_matrix import CASE_SLUGS, build_confirmatory_case_matrix
from aeread_families.procurement_allocation.environment import solve_full_information_upper_bound


def test_holdout_panel_is_disjoint_and_solvable() -> None:
    assert len(CASE_SLUGS) == 12
    for surface in ("labeled", "opaque"):
        cases = build_confirmatory_case_matrix(surface=surface)
        assert len(cases) == 12
        for case in cases:
            upper = solve_full_information_upper_bound(case["payload"])
            assert upper.contribution_margin_usd > 0
            assert upper.actions_required <= case["payload"]["interaction"]["max_actions"]


def test_plan_runs_both_arms_fresh_on_one_environment() -> None:
    plan = build_plan()
    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["planned_trajectory_count"] == 144
    assert plan["arm_execution_order"] == [
        "labeled_control", "opaque_control", "labeled_treatment", "opaque_treatment",
    ]
    assert plan["prompts"]["control_sha256"] == FROZEN_SCAFFOLD_PROMPT_SHA256
    assert plan["prompts"]["treatment_sha256"] == FROZEN_V4_PROMPT_SHA256
    assert plan["prompts"]["control_sha256"] != plan["prompts"]["treatment_sha256"]
    assert plan["independent_world_count"] == 12
    assert build_plan()["plan_sha256"] == plan["plan_sha256"]
