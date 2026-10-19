from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation import continuous_campaign as campaign
from aeread_families.procurement_allocation.runner import load_case


def _case():
    return json.loads(canonical_json_bytes(load_case()))


def test_environment_seeds_change_case_identity_but_keep_economic_world():
    case = _case()
    first, second = [campaign.episode_case(case, seed) for seed in (1, 2)]
    assert first['payload']['interaction']['sample_noise']['seed'] == 1
    assert second['payload']['interaction']['sample_noise']['seed'] == 2
    assert first['content_sha256'] != second['content_sha256']
    assert campaign.economic_world_id(first) == campaign.economic_world_id(second)
    assert first['content_sha256'] == case_content_sha256(CaseManifest.from_dict(first))
    assert 'sample_noise' not in case['payload']['interaction']
    assert first['payload']['interaction']['counter_feedback'] == 'field_specific'


def test_mirrored_worlds_cannot_count_as_independent_clusters():
    case = _case()
    other = copy.deepcopy(case)
    other['world_seed'] += 1
    other['payload']['suppliers'].reverse()
    for supplier in other['payload']['suppliers']:
        supplier['supplier_id'] += '_mirror'
        supplier['listing']['supplier_name'] += '_mirror'
    assert campaign.economic_world_id(case) == campaign.economic_world_id(other)
    with pytest.raises(ValueError, match='repeats an economic world'):
        campaign.screen_panel([case, other])


def test_failed_screen_is_preserved_and_cannot_be_promoted():
    case = _case()
    result = campaign.screen_panel([case], seeds=(1, 2, 3))
    assert result['status'] == 'failed'
    assert result['provider_calls'] == 0
    assert len(result['candidates']) == 1
    assert len(result['candidates'][0]['policy_rows']['replay_best_qualified']) == 3
    assert result['candidates'][0]['live_model_control_rate'] is None
    with pytest.raises(ValueError, match='exactly six'):
        campaign.build_plan(result)
    result['status'] = 'passed'
    with pytest.raises(ValueError, match='digest mismatch'):
        campaign.build_plan(result)


@pytest.mark.parametrize('seeds', [(1,), (1, 1, 2)])
def test_screen_cannot_fake_replication_with_repeated_seeds(seeds):
    with pytest.raises(ValueError, match='distinct environment seeds'):
        campaign.screen_world(_case(), seeds)


def test_design_binds_every_required_component_and_corrects_pilot_arithmetic():
    # Synthetic admission evidence isolates contract construction; it is not a
    # claim that these worlds were admitted by the real screen.
    screen = campaign._seal({
        'implementation_pins': campaign.implementation_pins(), 'status': 'passed',
        'selected_world_ids': [f'w{i}' for i in range(6)],
        'candidates': [{'world_id': f'w{i}', 'verdict': 'admit'} for i in range(6)],
    })
    plan = campaign.build_plan(screen)
    assert plan['pilot_rows'] == 24
    assert plan['confirmatory_rows'] == 36
    assert plan['metric'] == 'regret_to_upper_bound_usd'
    assert plan['hard_total_cost_ceiling_usd'] == .35
    assert 'synthetic_falsification' in plan['required_gates']
    assert plan['freeze_status'].startswith('design_only')
    assert set(plan['pilot_environment_seeds']).isdisjoint(plan['confirmatory_environment_seeds'])
    assert plan['plan_sha256'] == campaign._digest({k:v for k,v in plan.items() if k != 'plan_sha256'})
    screen['implementation_pins']['runner.py'] = '0' * 64
    screen = campaign._seal({k:v for k,v in screen.items() if k != 'artifact_sha256'})
    with pytest.raises(ValueError, match='implementation changed'):
        campaign.build_plan(screen)
