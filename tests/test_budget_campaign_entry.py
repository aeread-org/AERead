"""Public entry admission, identity and fresh-root ownership regressions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from aeread import campaign_cli as entry, cli


def contract_file(tmp_path, family='housing', **controls):
    name = 'housing_budget_campaign_v1' if family == 'housing' else 'datacenter_terms_budget_campaign_v1'
    contract = json.loads((entry.ROOT / 'configs' / f'{name}.json').read_bytes())
    # Mutation tests deliberately repin the current source so they exercise
    # the changed behavior, rather than failing only on a stale code digest.
    contract['source_pins'] = entry.source_pins()
    contract['controls'].update(controls)
    path = tmp_path / f'{name}.json'
    path.write_text(json.dumps(contract))
    return path


def forbid_factory():
    pytest.fail('live provider factory was called before admission')


@pytest.mark.parametrize('family', ['housing', 'dc'])
def test_default_design_has_complete_plans_resources_and_no_factory(tmp_path, family):
    path = contract_file(tmp_path, family)
    root = tmp_path/'launch'
    result = asyncio.run(entry.run_campaign(contract_path=path, output_root=root, provider_factory=forbid_factory))
    assert result['stage'] == 'design' and result['status'] == 'passed'
    assert len(result['cells']) == (12 if family == 'housing' else 10)
    assert all(cell['seat_to_profile'] for cell in result['cells'])
    for profile in result['resources'].values():
        assert profile['effective_max_output_tokens_ceiling'] == 8*profile['base_max_output_tokens']
        assert profile['max_cost_usd'] == (.01 if family == 'housing' else .02)
    assert not list(root.rglob('evaluation_receipt.json'))
    assert not (root/'summary.json').exists()
    with pytest.raises(ValueError, match='fresh empty'):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=forbid_factory))


@pytest.mark.parametrize('field', ['adapter', 'id', 'source', 'base', 'cap', 'ceiling', 'extra', 'stage'])
def test_contract_and_resource_tampering_fails_before_factory(tmp_path, field):
    path = contract_file(tmp_path)
    contract = json.loads(path.read_bytes())
    if field == 'adapter': contract['adapter_id'] = 'arbitrary.module:execute'
    elif field == 'id': contract['campaign_id'] = 'housing_model_sensitivity_v1'
    elif field == 'source': contract['source_pins'].pop(next(iter(contract['source_pins'])))
    elif field == 'base': contract['base_contract']['sha256'] = '0'*64
    elif field in {'cap', 'ceiling'}:
        profile = next(iter(contract['resources'].values()))
        profile['max_cost_usd' if field == 'cap' else 'effective_max_output_tokens_ceiling'] *= 2
    elif field == 'extra': contract['resume'] = True
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=tmp_path/'launch', stage='invalid' if field == 'stage' else 'live', provider_factory=forbid_factory))
    assert not (tmp_path/'launch'/'summary.json').exists()


@pytest.mark.parametrize('gate', ['design', 'provider_free', 'admission'])
def test_live_runs_every_gate_before_client_creation(tmp_path, monkeypatch, gate):
    from aeread_families.datacenter_development_terms import budget_campaign as adapter
    path = contract_file(tmp_path, 'dc')
    if gate == 'design':
        monkeypatch.setattr(adapter, 'design_gate', lambda *_: {'status': 'failed'})
    elif gate == 'provider_free':
        async def failed(*_): return {'status': 'failed'}
        monkeypatch.setattr(adapter, 'provider_free_gate', failed)
    else:
        # Exercise the admission boundary with a failing verified plan check.
        real_inventory = entry._inventory
        def bad_inventory(bindings, expected):
            value = real_inventory(bindings, expected)
            object.__setattr__(bindings[0].setup.plan.profile_admissions[0], 'admitted', False)
            return value
        monkeypatch.setattr(entry, '_inventory', bad_inventory)
    with pytest.raises(ValueError):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=tmp_path/'launch', stage='live', provider_factory=forbid_factory))
    assert (tmp_path/'launch'/'incomplete.json').exists()
    assert not (tmp_path/'launch'/'summary.json').exists()


@pytest.mark.parametrize('status', ['unsupported', 'unknown', 'failed'])
def test_required_account_preflight_fails_closed_without_invented_api(tmp_path, status):
    path = contract_file(tmp_path, 'dc')
    contract = json.loads(path.read_bytes()); contract['account_preflight']['required'] = True
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match='preflight'):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=tmp_path/'launch', stage='live', provider_factory=forbid_factory,
                                       account_preflight=lambda: {'status': status, 'real_account_verified': False}))


def test_cli_dispatches_new_entry_and_preserves_all_exchange_verbs(tmp_path, monkeypatch):
    assert cli.VERBS['run'][0] == 'aeread.exchange_v1.runner'
    assert cli.VERBS['campaign'][0] == 'aeread.campaign_cli'
    path = contract_file(tmp_path, 'dc')
    monkeypatch.setattr('sys.argv', ['aeread','campaign','--contract',str(path),'--output-root',str(tmp_path/'cli')])
    assert cli.main() == 0
    assert (tmp_path/'cli'/'design.json').exists()


def test_nonempty_root_refused_instead_of_cached_summary_early_return(tmp_path):
    path = contract_file(tmp_path, 'dc'); root = tmp_path/'stale'; root.mkdir()
    (root/'summary.json').write_text(json.dumps(entry.sealed({'status': 'completed', 'campaign_id': 'stale'})))
    with pytest.raises(ValueError, match='fresh empty'):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=forbid_factory))


def test_concurrent_invocations_claim_root_exclusively(tmp_path):
    path = contract_file(tmp_path, 'dc'); root = tmp_path/'shared'
    def launch():
        try:
            asyncio.run(entry.run_campaign(contract_path=path, output_root=root, provider_factory=forbid_factory))
            return 'ok'
        except ValueError:
            return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: launch(), range(2)))
    assert sorted(results) == ['ok', 'rejected']


@pytest.mark.parametrize('family', ['housing', 'datacenter_terms'])
def test_shipped_envelope_has_current_exact_source_pins(family):
    path = entry.ROOT/'configs'/f'{family}_budget_campaign_v1.json'
    contract, adapter, base = entry.load_contract(path)
    assert contract['source_pins'] == entry.source_pins()
    assert contract['resources'] == entry._resources(adapter.prepare(base))


@pytest.mark.parametrize('tamper', ['missing', 'foreign_key', 'foreign_arm', 'foreign_plan_cell', 'foreign_cell_id', 'metadata', 'duplicate_provenance'])
def test_design_rejects_incomplete_or_reassigned_base_inventory(tmp_path, monkeypatch, tamper):
    from dataclasses import replace
    from aeread.shared_runner.run.controlled_campaign import PlannedCell
    from aeread_families.housing import budget_campaign as adapter
    path = contract_file(tmp_path)
    real_prepare = adapter.prepare
    def malformed(base):
        bindings = list(real_prepare(base))
        first = bindings[0]
        if tamper == 'missing':
            return tuple(bindings[:-1])
        if tamper == 'foreign_key':
            bindings[0] = replace(first, planned=PlannedCell('foreign', first.planned.arm_key))
        elif tamper == 'foreign_arm':
            bindings[0] = replace(first, planned=PlannedCell(first.planned.cell_key, 'foreign_arm'))
        elif tamper == 'foreign_plan_cell':
            bindings[0] = replace(first, cell=bindings[-1].cell)
        elif tamper == 'foreign_cell_id':
            bindings[0] = replace(first, cell=replace(first.cell, cell_id='foreign'))
        elif tamper == 'metadata':
            bindings[0] = replace(first, metadata={**first.metadata, 'world_seed': 12345})
        else:
            bindings[1] = replace(first, planned=bindings[1].planned, metadata=bindings[1].metadata)
        return tuple(bindings)
    monkeypatch.setattr(adapter, 'prepare', malformed)
    root = tmp_path/'launch'
    with pytest.raises(ValueError):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, provider_factory=forbid_factory))
    assert not (root/'design.json').exists() and not (root/'summary.json').exists()
