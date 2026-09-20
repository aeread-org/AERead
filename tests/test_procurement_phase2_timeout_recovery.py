"""Timeout recovery through the real scheduler, with no paid calls or delays."""

import asyncio
import json

import pytest

from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.procurement_allocation import phase2_budget as budget
from aeread_families.procurement_allocation.phase2_execution import run_row
from aeread_families.procurement_allocation.phase2_worlds import build_world, CATEGORIES
from tests.test_procurement_phase2 import fixture_contribution
from tests.test_procurement_phase2_execution import PolicyProvider, Script, request, rate_limit


def test_local_deadline_is_typed_and_holds_unknown_charge(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "PROVIDER_TIMEOUT_SECONDS", 0.001)

    class NeverReturns:
        async def complete(self, request):
            await asyncio.Event().wait()

    p = budget.Phase2BudgetedProvider(NeverReturns(), tmp_path)
    with pytest.raises(ProviderFailure) as caught:
        asyncio.run(p.complete(request()))
    assert caught.value.condition == "timeout" and caught.value.retryable
    assert caught.value.retry_after_seconds == 60
    assert p.retry_request == request().request_sha256 and not p.stopped
    bill = json.loads(p.calls[0].read_text())
    assert bill["cost_usd"] is None and bill["reserved_cost_usd"] > 0


@pytest.mark.parametrize("second", [TimeoutError("second timeout"), rate_limit()])
def test_timeout_second_failure_stops_with_both_reservations(tmp_path, second):
    delegate = Script([TimeoutError("first timeout"), second])
    p = budget.Phase2BudgetedProvider(delegate, tmp_path)
    for retryable in (True, False):
        with pytest.raises(ProviderFailure) as caught:
            asyncio.run(p.complete(request()))
        assert caught.value.retryable == retryable
    assert p.stopped and len(p.calls) == 2
    assert p.spent == pytest.approx(sum(json.loads(x.read_text())["reserved_cost_usd"] for x in p.calls))
    with pytest.raises(budget.CampaignBudgetExceeded):
        asyncio.run(p.complete(request()))
    assert delegate.calls == 2


def test_external_cancellation_never_becomes_retry_permission(tmp_path):
    p = budget.Phase2BudgetedProvider(Script([asyncio.CancelledError()]), tmp_path)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(p.complete(request()))
    assert p.stopped and p.retry_request is None
    assert json.loads(p.calls[0].read_text())["cost_usd"] is None


def test_timeout_retry_cannot_change_request(tmp_path):
    p = budget.Phase2BudgetedProvider(Script([TimeoutError("fixture")]), tmp_path)
    with pytest.raises(ProviderFailure):
        asyncio.run(p.complete(request()))
    changed = request()
    changed.request_sha256 = "b" * 64
    with pytest.raises(ValueError, match="changed the logical"):
        asyncio.run(p.complete(changed))
    assert p.stopped and len(p.calls) == 1


def test_real_scheduler_retries_timeout_and_replays_without_free_unknown_call(tmp_path, monkeypatch):
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    delegate = PolicyProvider()

    class FirstTimeout:
        calls = 0

        async def complete(self, request):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("fixture timeout")
            return await delegate.complete(request)

    admission = tmp_path / "admission"
    admission.mkdir()
    c = fixture_contribution(admission)
    root = tmp_path / "run"
    p = budget.Phase2BudgetedProvider(FirstTimeout(), root)
    row = asyncio.run(run_row(root, "pilot", build_world(6), CATEGORIES[6],
                             52001, "control", p, c, admission))
    assert row["status"] == "completed" and row["receipt_replayed"]
    assert row["runner_retry_count"] == 1 and delays == [60]
    assert row["cost_usd"] is None and row["known_cost_usd"] == 0
    assert row["unresolved_reserved_cost_usd"] > 0 and not p.stopped
    bills = [json.loads(x.read_text()) for x in p.calls]
    assert bills[0]["request_sha256"] == bills[1]["request_sha256"]
    assert bills[0]["provider_failure"]["condition"] == "timeout"
