"""Prospective synthetic Housing campaigns exercise the real cell/receipt consumer.

No historical campaign is resumed and no provider network request is made.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest

from aeread.shared_runner.task.execution import EvidenceIntegrityError, EvidenceStore, ProviderFailure
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.receipts import read_evaluation_receipt
from aeread_families.housing import model_sensitivity as campaign
from aeread_families.housing.runner import HousingScriptedLandlordProvider, HousingScriptedTenantProvider

CONTRACT = Path(__file__).resolve().parents[1] / "configs/housing_model_sensitivity_v1.json"


def fresh_contract():
    contract = json.loads(CONTRACT.read_bytes())
    contract["campaign_id"] = "synthetic_issue253_failure_budget_prospective"
    contract["execution"].update(config_ids=["mild_cw085_r2"], replicates=2,
                                 cost_ceiling_usd=10.0, per_trajectory_cost_reserve_usd=0.1)
    contract["conditions"] = contract["conditions"][:2]
    return contract


class SyntheticHousingProvider:
    """Adapt valid scripted Housing actions to the real OpenRouter profile route."""
    def __init__(self, condition="provider_5xx", *, success_overrun=False):
        self.condition = condition
        self.success_overrun = success_overrun
        self.requests = []
        self.failure = ProviderFailure(condition, "synthetic billed failure", retryable=True,
                                       status_code=503 if condition == "provider_5xx" else None)
        self.failure.with_reported_usage({"choices": [{"index": 0}],
                                         "usage": {"cost": 0.02}})

    async def complete(self, request):
        self.requests.append(request)
        first = len(self.requests) == 1
        if first and not self.success_overrun:
            raise self.failure
        landlord = json.loads(request.input_text)["phase_id"] == "respond"
        provider = HousingScriptedLandlordProvider() if landlord else HousingScriptedTenantProvider()
        adapted = replace(request, provider="housing_scripted_landlord" if landlord else "housing_scripted_tenant")
        result = await provider.complete(adapted)
        return replace(result, requested_model=request.model,
                       resolved_model=request.revision, cost_usd=0.02 if first else 0.0)


def observe_real_cells(monkeypatch):
    calls = []
    real_execute = campaign.execute_plan_cell
    async def observed(**kwargs):
        observation = {"kwargs": kwargs}
        calls.append(observation)
        try:
            observation["execution"] = await real_execute(**kwargs)
            return observation["execution"]
        except Exception as error:
            observation["error"] = error
            raise
    monkeypatch.setattr(campaign, "execute_plan_cell", observed)
    return calls


def cell_receipts(call):
    kwargs = call["kwargs"]
    return [path for path in kwargs["evidence_root"].rglob("evaluation_receipt.json")
            if read_evaluation_receipt(path)["cell_id"] == kwargs["cell_id"]]


def assert_denominators(summary):
    assert summary["planned_trajectories"] == summary["attempted_trajectories"] + summary["not_started_trajectories"]
    assert summary["attempted_trajectories"] == summary["completed_trajectories"] + summary["operational_failures"]
    for view in summary["configuration_views"].values():
        for group in [view, *view["conditions"].values()]:
            not_started = group["planned_trajectories"] - group["attempted_trajectories"]
            assert not_started >= 0
            assert group["attempted_trajectories"] == group["completed_trajectories"] + group["operational_failures"]


@pytest.mark.parametrize("condition,critical", [("provider_5xx", False), ("timeout", False), ("provider_contract", True)])
def test_real_campaign_preserves_provider_cause_and_linked_budget_receipt(tmp_path, monkeypatch, condition, critical):
    calls = observe_real_cells(monkeypatch)
    provider = SyntheticHousingProvider(condition)
    summary = asyncio.run(campaign.run_live(fresh_contract(), output_root=tmp_path, provider_client=provider))
    assert_denominators(summary)
    assert summary["critical_stop"] is critical
    assert summary["attempted_trajectories"] == (1 if critical else 4)
    assert summary["operational_failures"] == 1
    assert summary["completed_trajectories"] == (0 if critical else 3)
    assert len(calls) == summary["attempted_trajectories"]
    row = summary["rows"][0]
    assert row["failure_condition"] == condition
    assert "within_case_score" not in row
    assert row["receipt_sha256"] is not None
    assert summary["total_cost_usd"] == 0.02
    usage = row["failure_usage"]
    assert usage["cost_accounting"] == ("lower_bound" if condition == "timeout" else "exact")
    assert isinstance(calls[0]["error"].__cause__, EvidenceIntegrityError)
    assert calls[0]["error"].__cause__.__cause__ is provider.failure
    kwargs = calls[0]["kwargs"]
    receipts = cell_receipts(calls[0])
    assert len(receipts) == 1
    receipt = read_evaluation_receipt(receipts[0])

    assert receipt["receipt_sha256"] == row["receipt_sha256"]
    assert receipt["run_plan_id"] == row["run_plan_id"] == kwargs["plan"].run_plan_id
    assert receipt["cell_id"] == row["cell_id"] == kwargs["cell_id"]
    assert receipt["failure"]["condition"] == "cost_budget_exceeded"
    assert receipt["failure"]["failure_class"] == "environment_failure"
    assert receipt["status"] == "invalid_measurement"
    assert receipt["inclusion_status"] == "excluded"
    assert not receipt["scores"]
    setup = campaign.build_setups(fresh_contract())[(row["config_id"], row["condition_id"])]
    assert audit_family_receipt(setup=setup, receipt_path=receipts[0])["receipt_sha256"] == row["receipt_sha256"]
    evidence = EvidenceStore.audit_existing(receipts[0].parent)
    evidence.verify_seal()
    events = evidence.read_events()
    terminals = [event for event in events if event.event_type.startswith("provider_call_") and event.event_type != "provider_call_started"]
    assert len(terminals) == 1
    assert evidence.read_event_payload(terminals[0])["failure_condition"] == condition
    budget = [event for event in events if event.event_type == "action_attempt_failed"]
    assert len(budget) == 1
    assert evidence.read_event_payload(budget[0])["failure_condition"] == "cost_budget_exceeded"
    assert terminals[0].cell_id == row["cell_id"]
    evidence.close()
    assert json.loads((tmp_path / "live/summary.json").read_bytes()) == summary


def test_real_success_only_budget_overrun_remains_campaign_critical(tmp_path, monkeypatch):
    calls = observe_real_cells(monkeypatch)
    provider = SyntheticHousingProvider(success_overrun=True)
    summary = asyncio.run(campaign.run_live(fresh_contract(), output_root=tmp_path, provider_client=provider))
    assert_denominators(summary)
    assert summary["critical_stop"] is True
    assert summary["attempted_trajectories"] == summary["operational_failures"] == 1
    assert summary["not_started_trajectories"] == 3
    assert summary["rows"][0]["failure_condition"] == "execution_error"
    assert summary["total_cost_usd"] == 0.02
    receipt_path, = cell_receipts(calls[0])
    receipt = read_evaluation_receipt(receipt_path)
    assert receipt["failure"]["condition"] == "cost_budget_exceeded"
    assert receipt["failure"]["failure_class"] == "environment_failure"
    assert not receipt["scores"]


def test_real_failed_cell_sealing_fallback_does_not_invent_receipt_or_score(tmp_path, monkeypatch):
    calls = observe_real_cells(monkeypatch)
    def sealing_failure(**kwargs):
        raise OSError("synthetic receipt write failure")
    monkeypatch.setattr(campaign, "finalize_housing_failure", sealing_failure)
    provider = SyntheticHousingProvider("provider_contract")
    summary = asyncio.run(campaign.run_live(fresh_contract(), output_root=tmp_path, provider_client=provider))
    assert_denominators(summary)
    assert len(summary["rows"]) == 1 and summary["critical_stop"]
    row = summary["rows"][0]
    assert row["status"] == "operational_failure"
    assert row["receipt_sha256"] is None
    assert row["cost_usd"] == summary["total_cost_usd"] == 0.02
    assert row["failure_usage"]["cost_accounting"] == "exact"
    assert "within_case_score" not in row
    assert not list(cell_receipts(calls[0]))


def test_historical_campaign_refuses_current_execution_pin_before_any_call(tmp_path):
    path = CONTRACT.parent / "housing_model_sensitivity_openrouter_alt_v8.json"
    contract = json.loads(path.read_bytes())
    provider = SyntheticHousingProvider()
    with pytest.raises(EvidenceIntegrityError, match="create a new campaign identity"):
        asyncio.run(campaign.run_live(contract, output_root=tmp_path, provider_client=provider))
    assert provider.requests == []
    assert not (tmp_path / "live/summary.json").exists()


@pytest.mark.parametrize("condition,failure_class,critical", [("provider_5xx", "retryable_infrastructure", False),
    ("timeout", "retryable_infrastructure", False), ("provider_contract", "integration_or_configuration", True)])
def test_real_nonbudget_provider_failure_keeps_historical_receipt_precedence(tmp_path, monkeypatch, condition, failure_class, critical):
    calls = observe_real_cells(monkeypatch)
    provider = SyntheticHousingProvider(condition)
    provider.failure = ProviderFailure(condition, "synthetic unbilled nonretryable control", retryable=False)
    summary = asyncio.run(campaign.run_live(fresh_contract(), output_root=tmp_path, provider_client=provider))
    assert_denominators(summary)
    assert summary["critical_stop"] is critical
    assert summary["attempted_trajectories"] == (1 if critical else 4)
    receipt_path, = cell_receipts(calls[0])
    receipt = read_evaluation_receipt(receipt_path)
    assert receipt["failure"]["condition"] == condition
    assert receipt["failure"]["failure_class"] == failure_class
    assert summary["total_cost_usd"] == 0
