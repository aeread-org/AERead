"""Focused checks for the collusion GLM 5.2 campaign."""
from aeread_families.collusion.campaign import CASE_IDS, campaign_plan
from aeread_families.collusion.live import SUBJECT_SEAT, build_live_setup

def test_campaign_freezes_all_six_cells_and_continues_failures():
    plan=campaign_plan()
    assert len(CASE_IDS)==len(set(CASE_IDS))==6
    assert plan["execution"]["subject_seat"]==SUBJECT_SEAT
    assert plan["execution"]["abort_on_operational_failure"] is False
    assert plan["budget"]=={"max_case_cost_usd":0.03,"hard_total_cost_usd":0.20}

def test_live_setup_has_one_subject_and_one_nash_control():
    setup=build_live_setup(case_id=CASE_IDS[0]); block=setup.plan.evaluation_blocks[0]
    assert block.subject_seats==(SUBJECT_SEAT,)
    assert dict(block.controlled_profiles)=={"firm_b":"collusion_nash_rule_v1"}
