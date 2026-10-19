from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation import continuous_execution as execution
from aeread_families.procurement_allocation.continuous_campaign import economic_world_id, implementation_pins
from aeread_families.procurement_allocation.runner import load_case, SequenceResponseProvider


def _request():
    route = execution.GLM_PARASAIL_CANDIDATE.route
    return SimpleNamespace(model=route.model, revision=route.revision, provider_metadata={'route_provider':route.route_provider},
                           instructions='buyer', input_text='observe', output_schema={}, messages=None, tools=None,
                           max_output_tokens=10, request_sha256='a'*64)


class CountingProvider:
    def __init__(self, fail=False):
        self.calls=0
        self.fail=fail
    async def complete(self, request):
        self.calls+=1
        if self.fail:
            raise TimeoutError('ambiguous provider completion')
        return SimpleNamespace(cost_usd=.0001, resolved_model=request.revision, input_tokens=10, output_tokens=10)


def test_budget_is_reserved_before_dispatch_and_persists_across_arms(tmp_path):
    underlying=CountingProvider()
    provider=execution.BudgetedProvider(underlying,tmp_path,ceiling=.00001)
    with pytest.raises(execution.CampaignBudgetExceeded):
        asyncio.run(provider.complete(_request()))
    assert underlying.calls==0
    provider=execution.BudgetedProvider(underlying,tmp_path,ceiling=.01)
    asyncio.run(provider.complete(_request()))
    assert underlying.calls==1
    restored=execution.BudgetedProvider(CountingProvider(),tmp_path,ceiling=.01)
    assert restored.spent==.0001


def test_unknown_billed_outcome_stops_dispatch_and_cannot_be_retried(tmp_path):
    underlying=CountingProvider(fail=True)
    provider=execution.BudgetedProvider(underlying,tmp_path)
    with pytest.raises(TimeoutError):
        asyncio.run(provider.complete(_request()))
    assert provider.stopped
    with pytest.raises(RuntimeError,match='unsettled'):
        execution.BudgetedProvider(CountingProvider(),tmp_path)
    assert json.loads((tmp_path/'billing/call_00000.json').read_text())['cost_usd'] is None


def _fixture(monkeypatch, tmp_path):
    cases=[]
    for i in range(6):
        case=json.loads(canonical_json_bytes(load_case()))
        case['payload']['objective']['revenue_per_completed_kit_usd']+=i
        case['content_sha256']='0'*64
        case['content_sha256']=case_content_sha256(CaseManifest.from_dict(case))
        cases.append(case)
    worlds=[economic_world_id(c) for c in cases]
    # Isolate orchestration from candidate admission, which has its own real
    # screen regressions. No simulated artifact leaves the pytest temp tree.
    monkeypatch.setattr(execution,'build_plan',lambda screen:{'world_ids':worlds})
    screen={'candidates':[{'world_id':w,'case_content_sha256':c['content_sha256']} for w,c in zip(worlds,cases)]}
    log = tmp_path / 'synthetic_test_log.txt'
    log.write_text('1782 passed in 1.00s')
    import hashlib
    validation={'log_path':str(log), 'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(), 'exit_code':0,'tests_passed':1782,'implementation_pins':implementation_pins(),'synthetic_falsification_passed':True}
    return cases,worlds,screen,validation


def test_missing_validation_cannot_construct_a_provider(tmp_path,monkeypatch):
    cases,worlds,screen,validation=_fixture(monkeypatch, tmp_path)
    validation['exit_code']=1
    def forbidden():
        pytest.fail('provider constructed before offline validation passed')
    result=asyncio.run(execution.run_campaign(root=tmp_path/'runs/attempt',screen=screen,cases=cases,
                                            validation=validation,provider_factory=forbidden))
    assert result['status']=='blocked'


def test_complete_pilot_freeze_and_36_row_campaign_use_shared_gates(tmp_path,monkeypatch):
    cases,worlds,screen,validation=_fixture(monkeypatch, tmp_path)
    attempts=[]
    async def executor(**kwargs):
        case=json.loads(kwargs['case_path'].read_text())
        seed=case['payload']['interaction']['sample_noise']['seed']
        assert seed==kwargs['inference_seed']
        arm=kwargs['prompt_id'].rsplit('_',1)[-1]
        world=economic_world_id(case)
        offset=worlds.index(world)*.1
        regret=(60 if arm=='control' else 20)+seed%2+offset*(arm=='treatment')
        attempts.append((world,seed,arm))
        return {'status':'completed','receipt_replayed':True,'upper_bound_usd':100.,
                'regret_to_upper_bound_usd':regret,'contribution_margin_usd':100-regret,
                'feasible_award':True,'feasible':True,'decision':'award','violations':[],
                'cost_usd':0.,'provider_call_count':0,'elapsed_seconds':.1}
    root=tmp_path/'runs/attempt'
    kwargs=dict(root=root,screen=screen,cases=cases,validation=validation,
                provider_factory=lambda:SequenceResponseProvider([json.dumps({'action':'defer','reason':'canary'})]*2),
                preflight=lambda candidate:{'route':'synthetic'},executor=executor,receipt_auditor=lambda *args:None)
    pilot=asyncio.run(execution.run_campaign(**kwargs))
    assert pilot['status']=='pilot_passed'
    assert len(attempts)==24
    assert [r.gate_id for r in execution._history(root)]==['design_contract','provider_free_validation','profile_admission','full_trajectory','variance_pilot']
    result=asyncio.run(execution.run_campaign(**kwargs,stop_after='confirmatory'))
    assert result['status']=='supported'
    assert len(attempts)==60
    assert result['observed_rows']==36
    assert (root/'confirmatory_plan.json').is_file()
    assert execution._latest(root,'confirmatory_execution').status=='passed'
    # Resume reads the sealed result; it must not spend or execute another cell.
    result=asyncio.run(execution.run_campaign(**kwargs,stop_after='confirmatory'))
    assert result['status']=='supported'
    assert len(attempts)==60


def test_real_runner_seals_and_reaudits_noisy_fixture_receipts(tmp_path):
    from aeread_families.procurement_allocation.continuous_case_matrix import build_candidate
    from aeread_families.procurement_allocation.model_campaign import _run_cell
    case=build_candidate(2)
    supplier=case['payload']['suppliers'][0]['supplier_id']
    script=[json.dumps(a) for a in [
        {'action':'request_quote','supplier_id':supplier,'message':'quote'},
        {'action':'request_sample','supplier_id':supplier,'message':'sample'},
        {'action':'defer','reason':'fixture ends without buying'},
    ]]*2
    root=tmp_path/'runs/real_receipts'
    provider=execution.BudgetedProvider(SequenceResponseProvider(script),root)
    rows=asyncio.run(execution._rows(root,'pilot',[case],[29001],provider,_run_cell,execution._audit_row))
    assert len(rows)==2
    assert all(r['status']=='completed' and r['receipt_replayed'] for r in rows)
    assert len(list(root.rglob('evaluation_receipt.json')))==2
    # Auditing and resuming consume no new scripted responses or billable calls.
    saved=asyncio.run(execution._rows(root,'pilot',[case],[29001],provider,_run_cell,execution._audit_row))
    assert saved==rows
    assert len(provider.calls)==6
    # The review exporter independently replays the actual sealed receipts.
    from aeread_families.procurement_allocation.continuous_campaign import _seal
    from aeread_families.procurement_allocation.continuous_publication import publish_review
    fixture_design = _seal({
        'design':{'world_ids':[economic_world_id(case)],'implementation_pins':implementation_pins()},
    }, 'plan_sha256')
    execution._write_once_json(root/'execution_design.json', fixture_design)
    fixture_freeze = _seal({'execution_design_sha256':fixture_design['plan_sha256']}, 'plan_sha256')
    execution._write_once_json(root/'confirmatory_plan.json', fixture_freeze)
    publication=tmp_path/'evidence'/'procurement_allocation_fixture_review'
    result=publish_review(run_root=root,publication_root=publication)
    assert result['provider_call_count']==6
    assert result['confirmatory_executed'] is False
    review=json.loads((publication/'reports/pilot.json').read_text())
    assert len(review['rows'])==2
    assert all(r['receipt_replayed'] for r in review['rows'])
    assert json.loads((publication/'tables/frozen_plan.json').read_text()) == fixture_freeze
    # Even a freshly rehashed row cannot override receipt-backed economics.
    row_path=next((root/'pilot'/'rows').glob('*.json'))
    tampered=json.loads(row_path.read_text())
    tampered.pop('artifact_sha256')
    tampered['contribution_margin_usd']+=1
    row_path.write_text(json.dumps(_seal(tampered)))
    with pytest.raises(ValueError,match='differs from replayed outcome'):
        publish_review(run_root=root,publication_root=publication)


def test_precision_gate_can_fail_even_with_nonzero_pilot_variance():
    result=execution.bootstrap_power_sensitivity(sd=100.,meaningful_effect=1.,world_count=6)
    assert result['power'] < .2
    assert result['monte_carlo_95_lower'] < .8
    assert execution.bootstrap_power_sensitivity(0.,1.,6)['status']=='unidentified'


def test_failure_export_keeps_unknown_billing_and_unattempted_cells_distinct(tmp_path):
    from aeread_families.procurement_allocation.continuous_case_matrix import build_candidate
    from aeread_families.procurement_allocation.continuous_campaign import _seal
    from aeread_families.procurement_allocation.continuous_publication import publish_review
    case = build_candidate(2)
    root = tmp_path / 'runs' / 'failed'
    provider = execution.BudgetedProvider(CountingProvider(fail=True), root)
    rows = asyncio.run(execution._rows(root, 'pilot', [case], [29001], provider, execution._run_cell, execution._audit_row))
    assert [r['status'] for r in rows] == ['operational_failure', 'not_attempted']
    execution._write_once_json(root / 'execution_design.json', _seal({
        'design':{'world_ids':[economic_world_id(case)], 'implementation_pins':implementation_pins()},
    }, 'plan_sha256'))
    target = tmp_path / 'evidence' / 'procurement_allocation_failed_review'
    status = publish_review(run_root=root, publication_root=target)
    assert status['unsettled_provider_outcomes'] == 1
    assert status['unresolved_reserved_cost_usd'] > 0
    review = json.loads((target / 'reports/pilot.json').read_text())
    failed = next(r for r in review['rows'] if r['status'] == 'operational_failure')
    assert failed['failure_receipt_verified'] is True
    assert failed['cost_usd'] is None
    assert failed['known_cost_usd'] == 0
    assert failed['cost_accounting'] == 'unknown_provider_billing'
