from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.procurement_allocation import continuous_recovery as recovery
from aeread_families.procurement_allocation.continuous_case_matrix import build_candidate
from aeread_families.procurement_allocation.runner import SequenceResponseProvider


def request():
    route = recovery.GLM_PARASAIL_CANDIDATE.route
    return SimpleNamespace(model=route.model, revision=route.revision,
        provider_metadata={'route_provider': route.route_provider}, provider_call_id='fixture_call',
        instructions='buyer', input_text='observe', output_schema={}, messages=None, tools=None,
        max_output_tokens=10, request_sha256='a'*64)


class Script:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = 0
    async def complete(self, req):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(cost_usd=.0001, resolved_model=req.revision, input_tokens=10, output_tokens=10)


def rate_limit(delay=None):
    return ProviderFailure('rate_limit', 'fixture 429', retryable=True, status_code=429, retry_after_seconds=delay)


def test_retry_reserves_both_calls_and_floors_delay(tmp_path):
    provider = recovery.RecoveryProvider(Script([rate_limit()]), tmp_path)
    baseline = provider.spent
    with pytest.raises(ProviderFailure) as failure:
        asyncio.run(provider.complete(request()))
    assert failure.value.retry_after_seconds == 60 and failure.value.retryable
    assert provider.spent > baseline and not provider.stopped
    reserved = provider.spent - baseline
    asyncio.run(provider.complete(request()))
    assert provider.spent == pytest.approx(baseline + reserved + .0001)
    assert len(provider.calls) == 2
    assert json.loads(provider.calls[0].read_text())['cost_usd'] is None
    assert json.loads(provider.calls[1].read_text())['retry_of_previous_request'] is True
    with pytest.raises(RuntimeError, match='cannot be dispatched twice'):
        recovery.RecoveryProvider(Script(), tmp_path)


@pytest.mark.parametrize('errors', [[rate_limit(), rate_limit()], [rate_limit(181)], [TimeoutError('ambiguous')],
                                 [ProviderFailure('rate_limit','no explicit status',retryable=True)]])
def test_stop_without_speculative_retry(tmp_path, errors):
    script = Script(errors)
    provider = recovery.RecoveryProvider(script, tmp_path)
    for _ in errors:
        with pytest.raises(Exception):
            asyncio.run(provider.complete(request()))
    assert provider.stopped
    before = script.calls
    with pytest.raises(recovery.CampaignBudgetExceeded):
        asyncio.run(provider.complete(request()))
    assert script.calls == before


def test_combined_cap_checked_before_dispatch(tmp_path):
    script = Script()
    provider = recovery.RecoveryProvider(script, tmp_path, baseline=.349999)
    with pytest.raises(recovery.CampaignBudgetExceeded):
        asyncio.run(provider.complete(request()))
    assert script.calls == 0


def test_retry_after_under_bound_is_respected_and_request_cannot_change(tmp_path):
    provider = recovery.RecoveryProvider(Script([rate_limit(130)]), tmp_path)
    with pytest.raises(ProviderFailure) as failure:
        asyncio.run(provider.complete(request()))
    assert failure.value.retry_after_seconds == 130
    req = request()
    req.request_sha256 = 'b'*64
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(provider.complete(req))
    assert provider.stopped


def test_real_runner_retry_receipts_and_delay_are_auditable(tmp_path, monkeypatch):
    delays = []
    async def sleep(seconds):
        delays.append(seconds)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    delegate = SequenceResponseProvider([json.dumps({'action':'defer','reason':'fixture'})]*2)
    class First429:
        def __init__(self):
            self.calls = 0
        async def complete(self, req):
            self.calls += 1
            if self.calls == 1:
                raise rate_limit(75)
            return await delegate.complete(req)
    root = tmp_path / 'runs/recovery'
    provider = recovery.RecoveryProvider(First429(), root)
    rows = asyncio.run(recovery._rows(root, 'confirmatory', [build_candidate(2)], [49001],
                      provider, recovery._run_cell, recovery._audit_row))
    assert all(r['status'] == 'completed' and r['receipt_replayed'] for r in rows)
    assert delays == [75]
    assert rows[0]['runner_retry_count'] == 1 and rows[0]['provider_call_count'] == 2
    assert len(provider.calls) == 3
    from aeread_families.procurement_allocation.continuous_recovery_publication import _verified_billing_view
    case_path = root / 'cases' / f"{rows[0]['world_id']}_49001.json"
    audited = _verified_billing_view(root, 'confirmatory', case_path, rows[0], [json.loads(p.read_text()) for p in provider.calls])
    assert audited['cost_usd'] is None and audited['unresolved_reserved_cost_usd'] > 0
    assert audited['known_cost_usd'] == 0


def test_new_identity_and_seed_bind_actual_case_bytes():
    case = build_candidate(2)
    old = recovery.original_episode_case(case, 39001)
    new = recovery.episode_case(case, 49001)
    assert new['case_id'].startswith(recovery.CAMPAIGN_ID)
    assert new['content_sha256'] != old['content_sha256']
    assert new['payload']['interaction']['sample_noise']['seed'] == 49001
    assert recovery.economic_world_id(new) == recovery.economic_world_id(old)


def campaign_fixture(tmp_path):
    repository = recovery.REPOSITORY_ROOT
    screen = json.loads((repository / 'evidence/procurement_allocation/procurement_allocation_unified_regret_v1/reports/admission.json').read_text())
    cases = [build_candidate(i) for i in (2, 9, 11, 23, 25, 31)]
    log = tmp_path / 'fixture-suite.log'
    log.write_text('1782 passed in 1.00s')
    import hashlib
    validation = {'log_path':str(log), 'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
                  'exit_code':0, 'tests_passed':1782, 'implementation_pins':recovery.implementation_pins(),
                  'synthetic_falsification_passed':True}
    calibration = recovery._seal({'pilot':{'passed':True, 'total_provider_cost_usd':.08,
                   'bootstrap_power_sensitivity':{'monte_carlo_95_lower':.9}},
                   'usage':'synthetic pytest fixture only'})
    return dict(root=tmp_path / 'runs/full_recovery', screen=screen, cases=cases, validation=validation,
                calibration_root=tmp_path / 'fixture_calibration',
                calibration_verifier=lambda *args: calibration, preflight=lambda candidate:{'fixture':True})


def test_complete_36_receipts_freeze_publication_and_no_redispatch(tmp_path):
    kwargs = campaign_fixture(tmp_path)
    provider = SequenceResponseProvider([json.dumps({'action':'defer','reason':'synthetic receipt fixture'})]*38)
    kwargs['provider_factory'] = lambda:provider
    result = asyncio.run(recovery.run_campaign(**kwargs))
    assert result['status'] == 'not_supported'
    assert result['observed_rows'] == 36
    assert len(provider.requests) == 38
    assert recovery._latest(kwargs['root'], 'confirmatory_execution').status == 'passed'
    frozen = recovery._read_sealed(kwargs['root'] / 'confirmatory_plan.json', 'plan_sha256')
    assert frozen['environment_seeds'] == [49001,49002,49003]
    assert frozen['retry_policy']['minimum_delay_seconds'] == 60
    def forbidden():
        pytest.fail('completed recovery attempted to construct provider')
    kwargs['provider_factory'] = forbidden
    resumed = asyncio.run(recovery.run_campaign(**kwargs))
    assert resumed['status'] == 'not_supported'
    assert len(provider.requests) == 38
    from aeread_families.procurement_allocation.continuous_recovery_publication import publish_review
    published = tmp_path / 'evidence/procurement_allocation_recovery_fixture'
    status = publish_review(run_root=kwargs['root'], publication_root=published)
    assert status['provider_call_count'] == 38
    assert status['combined_accounted_cost_usd'] == recovery.BASELINE_SETTLED + recovery.BASELINE_RESERVED + recovery.SUPPORT_REVIEW_COST_USD
    report = json.loads((published/'reports/confirmatory.json').read_text())
    assert len(report['rows']) == 36
    assert report['summary']['world_cluster_bootstrap_95_interval'] == [0.,0.]
    contract = json.loads((published/'tables/execution_contract.json').read_text())
    assert 'prompts' not in contract and set(contract['prompt_sha256']) == {'control','treatment'}
    # A freshly rehashed local row cannot override sealed economic evidence.
    path = next((kwargs['root'] / 'confirmatory/rows').glob('*.json'))
    row = recovery._read_sealed(path)
    row.pop('artifact_sha256')
    row['regret_to_upper_bound_usd'] += 1
    path.write_text(json.dumps(recovery._seal(row)))
    with pytest.raises(ValueError, match='differs from replayed outcome'):
        publish_review(run_root=kwargs['root'], publication_root=published)


def test_stale_validation_cannot_construct_provider(tmp_path):
    kwargs = campaign_fixture(tmp_path)
    kwargs['validation']['implementation_pins'] = {}
    def forbidden():
        pytest.fail('stale validation reached provider')
    result = asyncio.run(recovery.run_campaign(**kwargs, provider_factory=forbidden))
    assert result['status'] == 'blocked'


def test_unhandled_operational_failure_stops_remaining_panel(tmp_path):
    root = tmp_path / 'runs/failure'
    provider = recovery.RecoveryProvider(Script(), root)
    attempted = []
    async def executor(**kwargs):
        attempted.append(kwargs['inference_seed'])
        return {'status':'operational_failure','receipt_replayed':False}
    rows = asyncio.run(recovery._rows(root,'confirmatory',[build_candidate(2)],[49001,49002],
                       provider,executor,lambda *args:None))
    assert attempted == [49001]
    assert [r['status'] for r in rows] == ['operational_failure'] + ['not_attempted']*3
