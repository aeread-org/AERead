import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.refund import v2_5_seat_extension_v7_1 as design


def test_panel_identity_and_real_authority_revision_conflict():
    for seed in (301, 302, 303):
        parent = design.parent.build_panels(seed, True)
        panels = design.build_panels(seed, True)
        assert {k: len(v) for k, v in panels.items()} == {'intake': 40, 'customer': 40}
        assert {c.case_id for group in parent.values() for c in group}.isdisjoint(
            c.case_id for group in panels.values() for c in group)
        for case in panels['customer']:
            if case.seat_context['structure_id'] == 'C02':
                records = case.seat_context['private_records_v6']
                assert {r['revision'] for r in records if r['document_id'] == 'backup'} == {99}
                assert {r['revision'] for r in records if r['document_id'] == 'primary'} == {1}
        # Building the new panel cannot mutate parent cases.
        assert canonical_json_bytes(parent) == canonical_json_bytes(design.parent.build_panels(seed, True))


@pytest.mark.parametrize('seat', ('customer', 'intake', 'policy', 'payments'))
def test_four_seat_branch_traces_and_visibility(seat):
    async def check():
        for panel, cases in design.build_panels(301, True).items():
            setup = design.build_run(cases, active_agents=(seat,))
            plugin = design.ExtensionPlugin(); provider = design.ScriptedProvider()
            for cell in setup.plan.cells:
                manifest = next(c for c in setup.plan.cases if c.case_id == cell.case_id)
                seen = []
                async def source(request):
                    obs = json.loads(canonical_json_bytes(request.observation))
                    inp = {'role': request.seat_id, 'phase_id': request.phase_id, 'observation': obs}
                    result = await provider.complete(SimpleNamespace(input_text=json.dumps(inp), model='scripted', revision=design.REVISION, provider_call_id='offline'))
                    seen.append((inp, json.loads(result.output_text)))
                    return result.output_text
                episode = await run_episode(cell=cell, case=manifest, plugin=plugin, response_source=source)
                case = plugin.validate_payload(manifest.payload)
                assert not episode.final_state['failures']
                assert plugin.outcome(case, episode.final_state)['end_to_end'] == 1
                for inp, action in seen:
                    obs = inp['observation']; role = inp['role']
                    assert 'reference_resolution' not in obs
                    if role == 'intake':
                        assert not {'private_facts', 'private_fact_records', 'policy_contract'} & obs.keys()
                        if panel == 'intake': assert obs['access_contract_v71']['external_business_validation'] is False
                    if role in ('policy', 'payments'): assert 'private_fact_records' not in obs
                    if role != 'intake': assert 'access_contract_v71' not in obs
                confirmations = [a for i, a in seen if i['phase_id'] == 'customer_confirmation']
                if case.seat_context['structure_id'] == 'CH02':
                    assert len(confirmations) == 2 and confirmations[0]['proposal_id'] != confirmations[1]['proposal_id']
                assert len(episode.final_state['transactions']) <= 1
    asyncio.run(check())

def test_admission_requires_conflict_and_public_access_contract():
    panels = design.build_panels()
    for seat, structure, mutation in [('customer', 'C02', 'revision'), ('intake', 'I04', 'rationale')]:
        pair = [c for c in panels[seat] if c.seat_context['mechanism'] == structure + '.0']
        bad = []
        for c in pair:
            ctx = copy.deepcopy(c.seat_context)
            if mutation == 'revision':
                for r in ctx['private_records_v6']: r['revision'] = 1
            else: ctx['access_contract_v71']['external_business_validation'] = True
            bad.append(replace(c, seat_context=ctx))
        with pytest.raises(ValueError): design.admit_panels({'test': bad})


def test_new_plugin_rejects_parent_revision_and_multiple_active_seats():
    cases = design.build_panels()['intake'][:2]
    with pytest.raises(ValueError): design.build_run(cases, ('intake', 'customer'))
    setup = design.build_run(cases)
    raw = dict(setup.plan.cases[0].payload); raw['design_revision'] = design.parent.REVISION
    with pytest.raises(ValueError): design.ExtensionPlugin().validate_payload(raw)


def test_receipt_measurement_pins_and_replay(tmp_path):
    async def check():
        cases = design.build_panels()['customer'][:2]
        setup = design.build_run(cases, active_agents=('customer',))
        cell = setup.plan.cells[0]
        execution = await design.parent.v3.legacy.execute_plan_cell(
            plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources, providers={'scripted': design.ScriptedProvider()},
            pricing=setup.pricing, episode_attempt_ordinal=0, harnesses=setup.harnesses)
        receipt = design.parent.v3.legacy.finalize_family_execution(setup=setup, execution=execution)
        design.parent.v3.legacy.replay_family_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path)
        assert all(s.primary.value == 1 for s in receipt.scores)
    asyncio.run(check())
