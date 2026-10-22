"""Focused checks for the EconAgent GLM 5.2 campaign."""
from pathlib import Path
from aeread_families.econagent_v1.campaign import CELLS,campaign_plan
from aeread_families.econagent_v1.live import SUBJECT_SEAT,build_live_setup

def test_campaign_has_six_positions_and_continues_failures():
 plan=campaign_plan();assert len(CELLS)==6
 assert {seed for _,seed in CELLS}=={300,301}
 assert plan["execution"]["subject_seat"]==SUBJECT_SEAT
 assert plan["execution"]["abort_on_operational_failure"] is False

def test_live_setup_declares_one_subject_and_local_controls():
 root=Path("/private/tmp/aeread-upstream-econagent")
 if not root.is_dir():return
 setup=build_live_setup(case_id=CELLS[0][0],upstream_root=root);block=setup.plan.evaluation_blocks[0]
 assert block.subject_seats==(SUBJECT_SEAT,)
 assert len(block.controlled_profiles)==3
