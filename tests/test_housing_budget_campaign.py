"""Actual public Housing entry, executor, failure finalizer and replay paths."""
import asyncio
import json

import pytest

from aeread import campaign_cli as entry
from aeread.shared_runner.task.receipts import read_evaluation_receipt
from tests.test_budget_campaign_entry import contract_file
from tests.test_failure_budget_campaign import SyntheticHousingProvider


@pytest.mark.parametrize('condition,lower', [('provider_5xx', False), ('timeout', True), ('provider_contract', False)])
def test_public_housing_keeps_real_failure_fee_receipt_and_all_arms(tmp_path, condition, lower):
    path = contract_file(tmp_path, cost_limit_usd=.039, per_cell_reserve_usd=.02)
    provider = SyntheticHousingProvider(condition)
    root = tmp_path/'live'
    result = asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert len(provider.requests) == 1
    assert result['planned'] == 12 and result['attempted'] == 1 and result['not_attempted'] == 11
    assert result['completed'] == 0 and result['attempted_failure'] == 1
    assert result['spend']['cost_usd'] == .02
    assert result['spend']['cost_accounting'] == ('lower_bound' if lower else 'exact')
    assert result['spend']['unsettled_call_count'] == int(lower)
    assert result['within_declared_campaign_cost_ceiling'] is (None if lower else True)
    row = next(row for row in result['rows'] if row['status'] == 'attempted_failure')
    assert row['provider_failure_condition'] == condition and row['final_failure_condition'] == 'cost_budget_exceeded'
    assert 'scores' not in row
    receipts = list((root/'cells'/row['cell_key']).rglob('evaluation_receipt.json'))
    assert len(receipts) == 1
    receipt = read_evaluation_receipt(receipts[0])
    assert receipt['receipt_sha256'] == row['receipt_sha256']
    assert receipt['run_plan_id'] == row['run_plan_id'] and receipt['cell_id'] == row['cell_id']
    assert receipt['failure']['condition'] == 'cost_budget_exceeded'
    assert result['halt']['condition'] == ('critical_route_or_replay_failure' if condition == 'provider_contract' else 'campaign_cost_reserve_reached')
    assert len(result['by_arm']) == 4
    assert sum(group['attempted'] == 0 for group in result['by_arm'].values()) == 3
    for group in result['by_arm'].values():
        assert group['planned'] == 3
        assert group['planned'] == group['completed'] + group['attempted_failure'] + group['not_attempted']
    for unstarted in [row for row in result['rows'] if row['status'] == 'not_attempted']:
        assert unstarted['receipt_sha256'] is None and 'scores' not in unstarted and 'spend' not in unstarted


def test_public_housing_successes_use_actual_replayed_receipts(tmp_path):
    path = contract_file(tmp_path, cost_limit_usd=.039, per_cell_reserve_usd=.02)
    # Compatibility: successful-call overrun remains a critical execution error
    # rather than being globally reclassified as a cell-local provider error.
    provider = SyntheticHousingProvider(success_overrun=True)
    result = asyncio.run(entry.run_campaign(contract_path=path, output_root=tmp_path/'live', stage='live', provider_factory=lambda: provider))
    assert result['halt']['condition'] == 'critical_route_or_replay_failure'
    assert result['spend']['cost_usd'] == .02 and len(provider.requests) == 1


def test_finalize_error_propagates_with_incomplete_evidence(tmp_path, monkeypatch):
    from aeread_families.housing import budget_campaign as adapter
    path = contract_file(tmp_path)
    def fail(**_): raise OSError('finalizer disk failure')
    monkeypatch.setattr(adapter, 'finalize_housing_failure', fail)
    root = tmp_path/'incomplete'
    with pytest.raises(OSError, match='finalizer'):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=SyntheticHousingProvider))
    assert (root/'incomplete.json').exists() and not (root/'summary.json').exists()
    assert list(root.rglob('events.jsonl')) and not list(root.rglob('result.json'))


def test_public_housing_completed_scores_come_from_real_replayed_receipts(tmp_path):
    from dataclasses import replace
    from aeread_families.housing.runner import HousingScriptedLandlordProvider, HousingScriptedTenantProvider
    class GoodProvider:
        async def complete(self, request):
            landlord = json.loads(request.input_text)['phase_id'] == 'respond'
            source = HousingScriptedLandlordProvider() if landlord else HousingScriptedTenantProvider()
            adapted = replace(request, provider='housing_scripted_landlord' if landlord else 'housing_scripted_tenant')
            result = await source.complete(adapted)
            return replace(result, requested_model=request.model, resolved_model=request.revision, cost_usd=0.0)
    path = contract_file(tmp_path)
    root = tmp_path/'live'
    result = asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=GoodProvider))
    assert result['completed'] == result['attempted'] == result['planned'] == 12
    assert result['attempted_failure'] == result['not_attempted'] == 0
    assert result['spend']['cost_accounting'] == 'exact' and result['spend']['cost_usd'] == 0
    assert all(row['scores'] and row['replay_verified'] and row['receipt_status'] == 'ok' for row in result['rows'])
    assert len(list(root.rglob('evaluation_receipt.json'))) == 12


def test_verified_housing_plan_case_cannot_change_base_header_identity(tmp_path, monkeypatch):
    from dataclasses import replace
    from aeread.shared_runner.registry import HarnessRegistry, ProviderCapabilities
    from aeread.shared_runner.run.resolver import case_content_sha256, resolve_run_plan, verify_run_plan
    from aeread_families.housing import budget_campaign as adapter
    from tests.test_budget_campaign_entry import forbid_factory
    path = contract_file(tmp_path)
    real_prepare = adapter.prepare
    def changed_header(base):
        bindings = list(real_prepare(base)); first = bindings[0]; old = first.setup.plan
        changed = replace(old.cases[0], provenance=replace(old.cases[0].provenance, review_status='curated'))
        changed = replace(changed, content_sha256=case_content_sha256(changed))
        harnesses = HarnessRegistry()
        for harness in first.setup.harnesses.values(): harnesses.register(harness)
        capabilities = {profile.model.provider: ProviderCapabilities(native_tools=True, structured_output=True,
            seed=True, system_prompt=True, reasoning_budget=True, reasoning_token_report=True,
            max_context_tokens=None) for profile in old.agent_profiles}
        actual = resolve_run_plan(families=old.families, cases=(changed,), suite=old.suite, sampling=old.sampling,
            evaluation_blocks=old.evaluation_blocks, analysis=old.analysis, agent_profiles=old.agent_profiles,
            run_spec=old.run_spec, registry=first.setup.registry, implementation_pins=old.implementation_pins,
            harness_registry=harnesses, provider_capabilities=capabilities)
        verify_run_plan(actual)
        bindings[0] = replace(first, setup=replace(first.setup, plan=actual), cell=actual.cells[0])
        return tuple(bindings)
    monkeypatch.setattr(adapter, 'prepare', changed_header)
    root = tmp_path/'foreign_header'
    with pytest.raises(ValueError):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, provider_factory=forbid_factory))
    assert not (root/'design.json').exists() and not (root/'summary.json').exists()
