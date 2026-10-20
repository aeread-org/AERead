"""Actual concurrent terms callbacks retain in-flight fees and receipt joins."""
import asyncio
from dataclasses import replace
import json

import pytest

from aeread import campaign_cli as entry
from aeread.shared_runner.task.execution import ProviderFailure
from aeread.shared_runner.task.receipts import read_evaluation_receipt
from aeread_families.datacenter_development_terms.cases import load_cases
from tests.test_budget_campaign_entry import contract_file
from tests.test_shared_runner_execution import _success_result


class TermsProvider:
    def __init__(self, *, account_fault=False):
        self.account_fault = account_fault
        self.calls = []
        self.b_started = asyncio.Event()

    async def complete(self, request):
        index = len(self.calls)
        self.calls.append(request)
        if self.account_fault:
            if index == 0:
                await self.b_started.wait()
                raise ProviderFailure('account_fault', 'synthetic exhausted account', retryable=False).with_reported_usage({'choices': [1], 'usage': {'cost': .01}})
            self.b_started.set()
            await asyncio.sleep(.02)
            raise ProviderFailure('timeout', 'synthetic late billed timeout', retryable=False).with_reported_usage({'choices': [1], 'usage': {'cost': .03}})
        case = load_cases()[0]
        gold = case.payload['oracle']['gold']
        response = dict(case_id=case.case_id, states=gold['states'], amounts=gold['amounts'],
                        actions=gold['required_actions'], claims=gold['required_claims'], evidence_ids=gold['required_evidence_ids'], external_actions_attempted=[])
        return replace(_success_result(text=entry.canonical_json_bytes(response).decode('utf-8'), cost=.001), requested_model=request.model, resolved_model=request.revision)


def test_actual_concurrent_account_fault_drains_fee_and_stops_queued_cells(tmp_path, monkeypatch):
    from aeread_families.datacenter_development_terms import budget_campaign as adapter
    path = contract_file(tmp_path, 'dc', concurrency=2)
    provider = TermsProvider(account_fault=True)
    built = []
    real = adapter.build_openrouter_setup
    def observed(*args, **kwargs):
        setup = real(*args, **kwargs); built.append((setup, kwargs)); return setup
    monkeypatch.setattr(adapter, 'build_openrouter_setup', observed)
    root = tmp_path/'live'
    result = asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert len(built) == 10  # prepared once, never rebuilt inside callback
    assert all(kwargs['case_slug'] == 'full-stack-cutoff-001' for _, kwargs in built)
    assert len(provider.calls) == 2
    assert result['planned'] == 10 and result['attempted'] == result['attempted_failure'] == 2
    assert result['completed'] == 0 and result['not_attempted'] == 8
    assert result['spend']['cost_usd'] == .04 and result['spend']['cost_accounting'] == 'lower_bound'
    assert result['spend']['unsettled_call_count'] == 1 and result['spend']['provider_call_count'] == 2
    assert result['halt']['condition'] == 'halted_on_account_fault'
    assert len(result['halt']['in_flight_at_trigger']) == 1
    assert len(result['halt']['not_started_keys']) == 8
    assert len(result['by_arm']) == 2
    for group in result['by_arm'].values():
        assert group['planned'] == 5 and group['attempted_failure'] == 1 and group['not_attempted'] == 4
    for row in result['rows'][:2]:
        receipt_path, = (root/'cells'/row['cell_key']).rglob('evaluation_receipt.json')
        receipt = read_evaluation_receipt(receipt_path)
        assert receipt['receipt_sha256'] == row['receipt_sha256']
        assert receipt['run_plan_id'] == row['run_plan_id'] and receipt['cell_id'] == row['cell_id']
        assert 'scores' not in row
    assert not list((root/'cells'/result['rows'][2]['cell_key']).rglob('events.jsonl'))


def test_actual_terms_successes_execute_finalize_replay_and_sum(tmp_path):
    path = contract_file(tmp_path, 'dc')
    provider = TermsProvider()
    root = tmp_path/'live'
    result = asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert len(provider.calls) == 10
    assert result['planned'] == result['attempted'] == result['completed'] == 10
    assert result['not_attempted'] == result['attempted_failure'] == 0 and result['halt'] is None
    assert result['spend']['cost_usd'] == pytest.approx(.01)
    assert result['spend']['cost_accounting'] == 'exact'
    assert all(row['replay_verified'] and row['receipt_status'] == 'ok' and row['scores'] for row in result['rows'])
    saved = json.loads((root/'summary.json').read_bytes())
    assert saved == entry.sealed(saved)


@pytest.mark.parametrize('failure', ['persist', 'cancel'])
def test_actual_entry_errors_drain_inflight_fees_and_leave_incomplete(tmp_path, monkeypatch, failure):
    from aeread.shared_runner.task.spend import attempt_spend, total_spend
    path = contract_file(tmp_path, 'dc', concurrency=2)
    root = tmp_path/'incomplete'
    provider = TermsProvider(account_fault=True)
    real_write = entry._write
    if failure == 'persist':
        def fail_first_result(path, value):
            if path.name == 'result.json' and value['cell_key'] == 'glm53_reka__seed_31101':
                raise OSError('synthetic result persistence failure')
            return real_write(path, value)
        monkeypatch.setattr(entry, '_write', fail_first_result)
    async def run():
        task = asyncio.create_task(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
        if failure == 'cancel':
            await provider.b_started.wait()
            task.cancel()
        with pytest.raises(OSError if failure == 'persist' else asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert len(provider.calls) == 2
    assert (root/'incomplete.json').exists() and not (root/'summary.json').exists()
    events = list((root/'cells').rglob('events.jsonl'))
    assert len(events) == len(list((root/'cells').rglob('evaluation_receipt.json'))) == 2
    spend = total_spend(attempt_spend(path.parent) for path in events)
    assert spend.cost_usd == .04 and spend.cost_accounting == 'lower_bound'
    assert spend.unsettled_call_count == 1
    late = json.loads((root/'cells'/'mistral_small__seed_31101'/'result.json').read_bytes())
    assert late['spend']['cost_usd'] == .03 and late['spend']['cost_accounting'] == 'lower_bound'


@pytest.mark.parametrize('tamper', ['foreign_binding', 'receipt_digest', 'plan_hash', 'arm', 'scores', 'inclusion'])
def test_actual_receipt_is_bound_to_expected_cell_and_payload(tmp_path, monkeypatch, tamper):
    from aeread_families.datacenter_development_terms import budget_campaign as adapter
    path = contract_file(tmp_path, 'dc', concurrency=1)
    real_prepare, real_execute = adapter.prepare, adapter.execute
    prepared = []
    def observed(base):
        bindings = real_prepare(base); prepared.extend(bindings); return bindings
    monkeypatch.setattr(adapter, 'prepare', observed)
    async def wrong_result(binding, provider, root):
        if tamper == 'foreign_binding':
            result = await real_execute(prepared[1], provider, root)
            # The foreign receipt is legitimate. Remove incidental identity
            # hints so acceptance must check its actual expected-root binding.
            payload = {key: value for key, value in result.payload.items()
                       if key in {'receipt_sha256', 'receipt_status', 'inclusion_status', 'scores', 'replay_verified'}}
            return replace(result, payload=payload)
        result = await real_execute(binding, provider, root)
        payload = dict(result.payload)
        if tamper == 'receipt_digest': payload['receipt_sha256'] = '0'*64
        elif tamper == 'plan_hash': payload['run_plan_sha256'] = '0'*64
        elif tamper == 'arm': payload['arm_key'] = 'foreign'
        elif tamper == 'scores': payload['scores'] = []
        elif tamper == 'inclusion': payload['inclusion_status'] = 'excluded'
        return replace(result, payload=payload)
    monkeypatch.setattr(adapter, 'execute', wrong_result)
    provider = TermsProvider()
    root = tmp_path/'invalid'
    with pytest.raises(ValueError):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert len(provider.calls) == 1
    assert (root/'incomplete.json').exists() and not (root/'summary.json').exists()
    assert list((root/'cells').rglob('evaluation_receipt.json'))
    assert not list((root/'cells').rglob('result.json'))


@pytest.mark.parametrize('failure_point', ['file', 'directory'])
def test_summary_fsync_error_preserves_fees_without_completed_summary(tmp_path, monkeypatch, failure_point):
    import os
    import stat
    path = contract_file(tmp_path, 'dc')
    root = tmp_path/'fsync_error'
    real_fsync = entry.os.fsync
    faulted = []
    def fail_summary(fd):
        fd_stat = os.fstat(fd)
        if not faulted:
            if failure_point == 'file':
                candidates = [root/'summary.json', *root.glob('summary.json.*.tmp')]
                for candidate in candidates:
                    if candidate.exists() and (candidate.stat().st_dev, candidate.stat().st_ino) == (fd_stat.st_dev, fd_stat.st_ino):
                        faulted.append('file')
                        raise OSError('synthetic summary file fsync failure')
            elif stat.S_ISDIR(fd_stat.st_mode) and (root/'summary.json').exists():
                faulted.append('directory')
                raise OSError('synthetic summary directory fsync failure')
        return real_fsync(fd)
    monkeypatch.setattr(entry.os, 'fsync', fail_summary)
    provider = TermsProvider()
    with pytest.raises(OSError, match='summary'):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert faulted == [failure_point]
    assert len(provider.calls) == 10
    assert not (root/'summary.json').exists()
    assert (root/'incomplete.json').exists()
    assert not list(root.glob('summary.json.*.tmp'))
    from aeread.shared_runner.task.spend import attempt_spend, total_spend
    costs = total_spend(attempt_spend(event.parent) for event in (root/'cells').rglob('events.jsonl'))
    assert costs.cost_usd == pytest.approx(.01) and costs.cost_accounting == 'exact'


def test_sealed_output_cannot_overwrite_existing_artifact(tmp_path):
    path = tmp_path/'sealed.json'
    first = entry._write(path, {'value': 'first'})
    original = path.read_bytes()
    with pytest.raises((FileExistsError, ValueError)):
        entry._write(path, {'value': 'replacement'})
    assert path.read_bytes() == original and json.loads(original) == first


def test_summary_temporary_cleanup_error_rolls_back_published_summary(tmp_path, monkeypatch):
    from pathlib import Path
    path = contract_file(tmp_path, 'dc')
    root = tmp_path/'cleanup_error'
    real_unlink = Path.unlink
    primary = OSError('synthetic summary temporary cleanup failure')
    failures = []
    def fail_summary_temp(candidate, *args, **kwargs):
        if candidate.parent == root and candidate.name.startswith('summary.json.') and candidate.name.endswith('.tmp') and not failures:
            failures.append(primary)
            raise primary
        return real_unlink(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail_summary_temp)
    provider = TermsProvider()
    with pytest.raises(OSError) as caught:
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert caught.value is primary and len(provider.calls) == 10
    assert not (root/'summary.json').exists() and (root/'incomplete.json').exists()
    assert not list(root.glob('summary.json.*.tmp'))
    assert len(list((root/'cells').rglob('evaluation_receipt.json'))) == 10


def test_summary_cleanup_cannot_mask_primary_fsync_failure(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    path = contract_file(tmp_path, 'dc')
    root = tmp_path/'primary_error'
    primary = OSError('primary summary fsync failure')
    secondary = OSError('secondary summary cleanup failure')
    real_fsync, real_unlink = os.fsync, Path.unlink
    failed = []
    def fail_fsync(fd):
        info = os.fstat(fd)
        if not failed:
            for candidate in [root/'summary.json', *root.glob('summary.json.*.tmp')]:
                if candidate.exists() and (candidate.stat().st_ino, candidate.stat().st_dev) == (info.st_ino, info.st_dev):
                    failed.append(primary)
                    raise primary
        return real_fsync(fd)
    def fail_cleanup(candidate, *args, **kwargs):
        if candidate.parent == root and candidate.name.startswith('summary.json.') and candidate.name.endswith('.tmp') and secondary not in failed:
            failed.append(secondary)
            raise secondary
        return real_unlink(candidate, *args, **kwargs)
    monkeypatch.setattr(entry.os, 'fsync', fail_fsync)
    monkeypatch.setattr(Path, 'unlink', fail_cleanup)
    provider = TermsProvider()
    with pytest.raises(OSError) as caught:
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert caught.value is primary
    assert failed == [primary, secondary] and len(provider.calls) == 10
    assert not (root/'summary.json').exists() and (root/'incomplete.json').exists()


def test_summary_normalization_failure_happens_before_publication(tmp_path, monkeypatch):
    path = contract_file(tmp_path, 'dc')
    root = tmp_path/'normalization_error'
    real_loads = entry.json.loads
    primary = ValueError('synthetic summary normalization failure')
    failed = []
    def fail_summary_loads(value, *args, **kwargs):
        if isinstance(value, bytes) and b'"by_arm":' in value and not failed:
            failed.append(primary)
            raise primary
        return real_loads(value, *args, **kwargs)
    monkeypatch.setattr(entry.json, 'loads', fail_summary_loads)
    provider = TermsProvider()
    with pytest.raises(ValueError) as caught:
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert caught.value is primary and len(provider.calls) == 10
    assert not (root/'summary.json').exists() and (root/'incomplete.json').exists()
    assert len(list((root/'cells').rglob('evaluation_receipt.json'))) == 10


def test_actual_plan_case_must_match_base_despite_restored_setup_facade(tmp_path, monkeypatch):
    from aeread.shared_runner.run.resolver import case_content_sha256
    from aeread_families.datacenter_development_terms import budget_campaign as adapter
    path = contract_file(tmp_path, 'dc')
    real_prepare = adapter.prepare
    def foreign_case(base):
        bindings = list(real_prepare(base)); first = bindings[0]
        original = first.setup.case
        changed = replace(original, world_seed=original.world_seed+1)
        changed = replace(changed, content_sha256=case_content_sha256(changed))
        controls = base['execution']
        actual = adapter.build_openrouter_setup(adapter.base._route(base['models'][first.metadata['model_id']]),
            seed=first.metadata['inference_seed'], case_slug=base['case_slug'], case_manifest=changed,
            max_output_tokens=controls['max_output_tokens'], timeout_seconds=controls['timeout_seconds'],
            max_cost_usd=controls['max_cost_usd_per_cell'])
        actual = replace(actual, case=original)
        bindings[0] = replace(first, setup=actual, cell=actual.plan.cells[0])
        return tuple(bindings)
    monkeypatch.setattr(adapter, 'prepare', foreign_case)
    factories = []
    def factory(): factories.append(True); return TermsProvider()
    root = tmp_path/'foreign_case'
    with pytest.raises(ValueError):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=factory))
    assert factories == [] and not (root/'summary.json').exists()


def test_self_sealed_receipt_case_hash_cannot_disagree_with_admitted_cell(tmp_path, monkeypatch):
    from aeread_families.datacenter_development_terms import budget_campaign as adapter
    path = contract_file(tmp_path, 'dc', concurrency=1)
    real_execute = adapter.execute
    async def mismatched_receipt(binding, provider, root):
        result = await real_execute(binding, provider, root)
        receipt_path, = root.rglob('evaluation_receipt.json')
        receipt = json.loads(receipt_path.read_bytes())
        receipt['case_sha256'] = '0'*64
        receipt.pop('receipt_sha256')
        receipt['receipt_sha256'] = entry.digest(receipt)
        receipt_path.write_bytes(entry.canonical_json_bytes(receipt) + b'\n')
        verified = read_evaluation_receipt(receipt_path)
        assert verified['case_sha256'] != binding.cell.case_sha256
        return replace(result, payload={**result.payload, 'receipt_sha256': receipt['receipt_sha256']})
    monkeypatch.setattr(adapter, 'execute', mismatched_receipt)
    provider = TermsProvider()
    root = tmp_path/'receipt_case_mismatch'
    with pytest.raises(ValueError, match='case_sha256'):
        asyncio.run(entry.run_campaign(contract_path=path, output_root=root, stage='live', provider_factory=lambda: provider))
    assert len(provider.calls) == 1
    assert (root/'incomplete.json').exists() and not (root/'summary.json').exists()
    assert not list((root/'cells').rglob('result.json'))
