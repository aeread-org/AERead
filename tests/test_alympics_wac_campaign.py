"""Focused checks for the Alympics GLM 5.2 campaign wiring."""
from pathlib import Path

from aeread_families.alympics_wac.campaign import CASE_IDS, campaign_plan
from aeread_families.alympics_wac.live import SUBJECT_SEAT, build_live_setup


def test_campaign_freezes_six_non_degenerate_cases_and_continues_failures() -> None:
    plan = campaign_plan()
    assert len(CASE_IDS) == len(set(CASE_IDS)) == 6
    assert "alympics.wac.zero_supply_degenerate" not in CASE_IDS
    assert plan["execution"]["subject_seat"] == SUBJECT_SEAT
    assert plan["execution"]["abort_on_operational_failure"] is False
    assert plan["execution"]["replay_every_receipt"] is True
    assert plan["budget"] == {"max_case_cost_usd": 0.03, "hard_total_cost_usd": 0.20}


def test_live_setup_declares_exactly_one_subject_and_four_controls() -> None:
    upstream = Path("/private/tmp/aeread-upstream-alympics")
    if not upstream.is_dir():
        return
    setup = build_live_setup(case_id=CASE_IDS[-1], upstream_root=upstream)
    block = setup.plan.evaluation_blocks[0]
    assert block.subject_seats == (SUBJECT_SEAT,)
    assert set(block.controlled_profiles) == {"bob", "cindy", "david", "eric"}
