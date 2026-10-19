from __future__ import annotations

import copy

import pytest

from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin, _base_offer, _counter_rejection_fields, stated_listing,
)
from aeread_families.procurement_allocation.headroom_screen import (
    ADMIT, DEGENERATE, UNMEASURED, classify_world_continuous,
)
from aeread_families.procurement_allocation.runner import load_case
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import ActionEnvelope
import json


def _play(plugin, case, state, action):
    phase = plugin.phases(case)[0]
    parsed = plugin.parse_action(case, state, 'buyer', phase, action)
    assert parsed.ok
    legality = plugin.legal(case, state, 'buyer', phase, parsed.action)
    assert legality.legal
    return plugin.step(case, state, phase, {'buyer': ActionEnvelope('buyer', True, parsed.action, parsed, legality)}).state


def test_rejections_name_all_failed_fields_without_disclosing_limits():
    payload = json.loads(canonical_json_bytes(load_case().payload))
    payload['interaction']['counter_feedback'] = 'field_specific'
    plugin = ProcurementAllocationPlugin()
    case = plugin.validate_payload(payload)
    state = plugin.initial_state(case, None)
    state = _play(plugin, case, state, {'action': 'request_quote', 'supplier_id': 'switch_reliable', 'message': 'quote'})
    old_offers = copy.deepcopy(state['offers'])
    state = _play(plugin, case, state, {
        'action': 'counter_offer', 'supplier_id': 'switch_reliable',
        'offer_id': 'offer_switch_reliable_v1', 'message': 'counter',
        'proposal': {'unit_price_usd': .001, 'moq': 1, 'payment_terms_days': 999, 'refund_window_days': 999},
    })
    assert state['offers'] == old_offers
    reply = state['conversation'][-1]['content']
    assert 'Rejected terms: unit_price_usd, moq, payment_terms_days, refund_window_days.' in reply
    assert '0.082' not in reply
    assert state['actions_used'] == 2


@pytest.mark.parametrize('field,value', [('unit_price_usd', .001), ('moq', 1), ('payment_terms_days', 999), ('refund_window_days', 999), ('return_freight_payer', 'supplier')])
def test_each_counterable_field_has_a_specific_rejection(field, value):
    supplier = json.loads(canonical_json_bytes(load_case().payload))['suppliers'][0]
    supplier['private_terms']['negotiation']['supplier_paid_return_freight_available'] = False
    offer = _base_offer(supplier, version=1, issued_day=0)
    assert _counter_rejection_fields(supplier, offer, {field: value}) == [field]


def test_listing_bias_changes_public_claims_without_changing_binding_terms():
    supplier = json.loads(canonical_json_bytes(load_case().payload))['suppliers'][0]
    before = _base_offer(supplier, version=1, issued_day=0)
    supplier['private_terms']['verbal_bias'] = {'verified_yield_rate': .999, 'capacity': 999, 'moq': 1, 'lead_time_days': 3, 'base_unit_price_usd': .001}
    listing = stated_listing(supplier)
    assert listing['claimed_yield_rate'] == .999
    assert listing['claimed_capacity'] == 999
    assert listing['claimed_moq'] == 1
    assert listing['claimed_lead_time_days'] == 1
    assert listing['displayed_unit_price_usd'] == .00082
    assert _base_offer(supplier, version=1, issued_day=0) == before


def test_materiality_uses_declared_margin_scale():
    # Five dollars looks large relative to low regret, but is tiny on a $300 world.
    assert classify_world_continuous([1, 4, 6], {'greedy': 10}, minimum_relative_spread=.15) == ADMIT
    assert classify_world_continuous([1, 4, 6], {'greedy': 10}, minimum_relative_spread=.15, materiality_scale=300) == DEGENERATE


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_scores_cannot_admit_a_world(bad):
    assert classify_world_continuous([1, 3, bad], {'greedy': 10}) == UNMEASURED
    assert classify_world_continuous([1, 3, 8], {'greedy': bad}) == UNMEASURED


def test_full_information_cache_preserves_economics_and_returns_independent_certificates():
    import aeread_families.procurement_allocation.environment as env
    payload = json.loads(canonical_json_bytes(load_case().payload))
    expected = env._enumerate_full_information_upper_bound(payload)
    env._cached_full_information_upper_bound.cache_clear()
    first = env.solve_full_information_upper_bound(payload)
    assert first == expected
    payload['interaction'].update(sample_noise={'model': 'binomial', 'seed': 71}, counter_feedback='field_specific')
    assert env.solve_full_information_upper_bound(payload) == expected
    assert env._cached_full_information_upper_bound.cache_info().hits == 1
    first.award_plan[0]['quantity'] = 123456
    assert env.solve_full_information_upper_bound(payload) == expected
    payload['objective']['revenue_per_completed_kit_usd'] += 10
    assert env.solve_full_information_upper_bound(payload).contribution_margin_usd > expected.contribution_margin_usd


def test_generated_markets_are_reproducible_and_do_not_encode_a_universal_signal_direction():
    from aeread_families.procurement_allocation.continuous_case_matrix import build_candidate
    from aeread_families.procurement_allocation.continuous_campaign import economic_world_id
    directions=set()
    identities=set()
    for index in range(6):
        case=build_candidate(index)
        assert case==build_candidate(index)
        assert case['payload']['interaction']['sample_noise']['model']=='binomial'
        identities.add(economic_world_id(case))
        component=next(iter(case['payload']['objective']['bom']))
        suppliers=sorted((s for s in case['payload']['suppliers'] if s['component']==component),key=lambda s:s['private_terms']['quality']['verified_yield_rate'])
        directions.add(suppliers[0]['listing']['claimed_lead_time_days'] < suppliers[-1]['listing']['claimed_lead_time_days'])
    assert len(identities)==6
    assert directions=={True,False}
