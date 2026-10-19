"""``aeread verify-replay`` setup for TERMS-Bench: the campaign is found by plan digest."""
from __future__ import annotations

import pytest

from aeread_families.termsbench.campaign import CAMPAIGNS, PANEL_CASE_IDS, SEED
from aeread_families.termsbench.live import build_live_setup
from aeread_families.termsbench.replay_setup import setup_for_receipt


def _setup(campaign_id: str):
    spec = CAMPAIGNS[campaign_id]
    return build_live_setup(
        case_id=PANEL_CASE_IDS[0],
        seed=SEED,
        max_trajectory_cost_usd=spec.max_trajectory_cost_usd,
        reasoning=spec.reasoning,
        max_output_tokens=spec.max_output_tokens,
        route=spec.route,
    )


@pytest.mark.parametrize("campaign_id", sorted(CAMPAIGNS))
def test_each_registered_campaign_is_found_by_its_plan_digest(campaign_id: str) -> None:
    expected = _setup(campaign_id)
    receipt = {"case_id": PANEL_CASE_IDS[0], "run_plan_sha256": expected.plan.plan_sha256}
    assert setup_for_receipt(receipt).plan.plan_sha256 == expected.plan.plan_sha256


def test_a_plan_no_campaign_rebuilds_is_reported_not_guessed() -> None:
    receipt = {"case_id": PANEL_CASE_IDS[0], "run_plan_sha256": "0" * 64}
    with pytest.raises(ValueError, match="no campaign rebuilds the plan"):
        setup_for_receipt(receipt)
