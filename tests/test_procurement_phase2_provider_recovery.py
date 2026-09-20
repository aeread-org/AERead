"""Regressions for the observed 429 evidence loss and cross-attempt budget."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.procurement_allocation.phase2_budget import (
    Phase2BudgetedProvider,
    CampaignBudgetExceeded,
)
from aeread_families.procurement_allocation.phase2_campaign import (
    BASELINE_RESERVED_USD,
    BASELINE_SETTLED_USD,
    execution_contract,
    offline_screen,
    prior_campaign_accounting,
)
from aeread_families.procurement_allocation.phase2_worlds import build_world
from tests.test_procurement_phase2_execution import Script, request

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / "evidence/procurement_allocation/procurement_allocation_phase2_provider_recovery_v1"


def test_all_prior_attempts_count_once_and_unknown_charges_remain_reserved():
    prior = prior_campaign_accounting()
    attempts = prior["campaigns"]
    assert len(attempts) == 3
    assert [a["settled_cost_usd"] for a in attempts] == [0.0099593505, 0.016059285, 0.0688965255]
    assert [a["unresolved_reserved_cost_usd"] for a in attempts] == [0, 0.0051345, 0.00287595]
    assert prior["settled_cost_usd"] == pytest.approx(0.094915161, abs=1e-12)
    assert prior["accounted_cost_usd"] == pytest.approx(0.102925611, abs=1e-12)


@pytest.mark.parametrize("status", [429, 503])
def test_original_provider_message_is_preserved_privately(tmp_path, status):
    message = f"fixture provider {status}: explanatory detail; account=private-fixture"
    failure = ProviderFailure(
        "rate_limit" if status == 429 else "provider_5xx",
        message,
        retryable=True,
        status_code=status,
        retry_after_seconds=75 if status == 429 else None,
    )
    provider = Phase2BudgetedProvider(Script([failure]), tmp_path)
    with pytest.raises(ProviderFailure) as caught:
        asyncio.run(provider.complete(request()))
    assert str(caught.value) == message
    bill = json.loads(provider.calls[0].read_text())
    assert bill["cost_usd"] is None
    details = bill["provider_failure"]
    assert details["message"] == message
    assert details["message_sha256"] == hashlib.sha256(message.encode()).hexdigest()
    assert details["condition"] == failure.condition
    assert details["status_code"] == status
    assert provider.stopped == (status != 429)
    assert caught.value.retry_after_seconds == (75 if status == 429 else None)


def test_second_429_stops_dispatch_and_keeps_both_reservations(tmp_path):
    errors = [ProviderFailure("rate_limit", f"fixture rejection {i}",
                              retryable=True, status_code=429) for i in range(2)]
    script = Script(errors)
    baseline = BASELINE_SETTLED_USD + BASELINE_RESERVED_USD
    provider = Phase2BudgetedProvider(script, tmp_path, baseline=baseline)
    for ordinal in range(2):
        with pytest.raises(ProviderFailure) as caught:
            asyncio.run(provider.complete(request()))
        assert caught.value.retryable == (ordinal == 0)
    with pytest.raises(CampaignBudgetExceeded):
        asyncio.run(provider.complete(request()))
    bills = [json.loads(p.read_text()) for p in provider.calls]
    assert script.calls == 2 and all(b["cost_usd"] is None for b in bills)
    assert provider.spent == pytest.approx(
        baseline + sum(b["reserved_cost_usd"] for b in bills), abs=1e-12
    )


def test_new_contract_changes_timeout_retry_and_accounting_only():
    previous = json.loads((PREVIOUS / "tables/execution_contract.json").read_text())
    current = execution_contract([build_world(i) for i in range(8)], offline_screen())
    assert current["campaign_id"] != previous["campaign_id"]
    for key in ("implementation_pins", "screen_sha256", "campaign_id", "plan_sha256", "recovery_scope"):
        previous.pop(key)
        current.pop(key)
    previous.pop("prior_phase2_campaigns")
    current.pop("prior_phase2_campaigns")
    assert current.pop("provider_timeout_seconds") == 175
    assert current.pop("harness_timeout_seconds") == 180
    assert current["retry_policy"]["conditions"] == ["rate_limit", "timeout"]
    current["retry_policy"]["conditions"] = ["rate_limit"]
    assert current == previous
    pins = json.loads((PREVIOUS / "publication_manifest.json").read_text())["source_bindings"]["implementation_pins"]
    changed = {
        path for path, old_sha in pins.items()
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != old_sha
    }
    assert changed == {
        "src/aeread/shared_runner/run/resolver.py",  # upstream PR #149, additive helper
        "src/aeread_families/procurement_allocation/phase2_budget.py",
        "src/aeread_families/procurement_allocation/phase2_campaign.py",
        "src/aeread_families/procurement_allocation/phase2_execution.py",
        "src/aeread_families/procurement_allocation/phase2_runner.py",
        "tests/test_procurement_phase2_provider_recovery.py",
        "tests/test_procurement_phase2_execution.py",
    }


def test_publication_keeps_private_provider_message_out_and_checks_its_digest():
    from tools.publish_procurement_phase2_recovery import public_provider_failures

    message = "private fixture account information"
    details = dict(message=message, message_sha256=hashlib.sha256(message.encode()).hexdigest(),
                   exception_type="ProviderFailure", condition="rate_limit", status_code=429, retryable=True)
    bill = dict(request_sha256="a" * 64, provider_call_id="fixture", provider_failure=details)
    public = public_provider_failures([bill])
    assert message not in json.dumps(public)
    assert "message" not in public[0]
    assert public[0]["message_sha256"] == details["message_sha256"]
    details["message"] += "modified"
    with pytest.raises(ValueError, match="digest mismatch"):
        public_provider_failures([bill])
