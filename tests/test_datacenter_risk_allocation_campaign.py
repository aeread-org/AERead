"""The risk-allocation case through the shared runner: plans resolve, receipts seal and replay.

The reference plays one cell per seat and protocol through ``execute_plan_cell``
with no network; each receipt must verify, replay to the same digest, and grade
zero decision regret. This is the path live campaigns take.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_campaign as rc


@pytest.mark.parametrize("arm", ["one_price_low", "two_prices_low"])
@pytest.mark.parametrize("seat", ra.SEATS)
def test_the_reference_seals_a_verified_replayable_zero_regret_receipt(tmp_path: Path, arm: str, seat: str) -> None:
    cases = rc._cases(rc.ARMS[arm]["pack"], seat)[:1]
    setup = rc.build_setup(arm, "reference", seat, cases)
    entry = {"arm": arm, "route_id": "reference", "seat": seat}
    record = asyncio.run(rc._run_cell(tmp_path, entry, setup, setup.plan.cells[0], rc.Spend(1.0), asyncio.Semaphore(1)))
    assert record["status"] == "ok", record
    assert record["grade"]["valid"] and record["grade"]["decision_regret"] == pytest.approx(0.0, abs=1e-6)
    receipts = list(tmp_path.rglob("evaluation_receipt.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["receipt_sha256"] == record["receipt_sha256"]


def test_live_plans_resolve_with_the_declared_limits() -> None:
    for arm, spec in rc.ARMS.items():
        for route in rc.ROUTES:
            setup = rc.build_setup(arm, route, "client", rc._cases(spec["pack"], "client")[:2])
            profile = setup.plan.agent_profiles[0]
            assert profile.sampling.max_output_tokens == spec["max_output_tokens"][route]
            assert profile.reasoning.effort == spec["reasoning_effort"]
            assert profile.budgets.timeout_seconds == spec["timeout_seconds"][route]


def test_the_system_prompt_keeps_the_accept_instruction_the_two_prices_probe_lost() -> None:
    for seat in ra.SEATS:
        assert "price is null" in rc.system_prompt(seat, False)
        assert "price is null" in rc.system_prompt(seat, True) and "alternate is null" in rc.system_prompt(seat, True)
