"""Provider-free admission and frozen contract for the unified regret campaign.

A failed screen produces an auditable rejection artifact, never a six-world
panel padded with rejected worlds. Model control rates are not inferred from
these deterministic reference rates. This module makes no provider calls.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from .environment import solve_full_information_upper_bound
from .headroom_screen import (
    ADMIT, FLOORED, TRIVIAL, classify_world_continuous,
    replay_baseline_outcome, replay_best_qualified, within_world_variance,
)
from .model_campaign import _write_once_json

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_ID = 'procurement_allocation_unified_regret_v1'
SCREEN_SEEDS = tuple(range(19001, 19013))
PILOT_SEEDS = (29001, 29002)
CONFIRMATORY_SEEDS = (39001, 39002, 39003)
MINIMUM_RELATIVE_SPREAD = .15
REQUIRED_WORLDS = 6
HARD_COST_CEILING_USD = .35
SOURCE_FILES = ('continuous_campaign.py', 'continuous_execution.py', 'continuous_case_matrix.py', 'environment.py', 'headroom_screen.py', 'policy_baselines.py', 'runner.py')


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _seal(value: dict, key: str = 'artifact_sha256') -> dict:
    return {**value, key: _digest(value)}


def implementation_pins() -> dict[str, str]:
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def economic_world_id(case: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(case['payload'])
    # Environment realisations are repeated measurements of the same market.
    payload['interaction'].pop('sample_noise', None)
    payload['interaction'].pop('counter_feedback', None)
    for supplier in payload['suppliers']:
        supplier.pop('supplier_id')
        supplier['listing'].pop('supplier_name')
    payload['suppliers'].sort(key=canonical_json_bytes)
    return _digest(payload)


def episode_case(case: Mapping[str, Any], environment_seed: int) -> dict:
    """Bind the actual sampling seed into case bytes, separately from inference."""
    if isinstance(environment_seed, bool) or not isinstance(environment_seed, int) or environment_seed <= 0:
        raise ValueError('environment seed must be a positive integer')
    result = copy.deepcopy(case)
    result['case_id'] = f'{CAMPAIGN_ID}.{economic_world_id(case)[:16]}.sample_{environment_seed}'
    result['split'] = 'unified_regret_v1'
    noise = result['payload']['interaction'].setdefault('sample_noise', {'model': 'binomial'})
    noise['seed'] = environment_seed
    result['payload']['interaction']['counter_feedback'] = 'field_specific'
    result['content_sha256'] = '0' * 64
    result['content_sha256'] = case_content_sha256(CaseManifest.from_dict(result))
    return result


def screen_world(case: Mapping[str, Any], seeds: Sequence[int] = SCREEN_SEEDS) -> dict:
    if len(seeds) < 3 or len(set(seeds)) != len(seeds):
        raise ValueError('screen requires at least three distinct environment seeds')
    if case_content_sha256(CaseManifest.from_dict(case)) != case['content_sha256']:
        raise ValueError('candidate content digest mismatch')
    bound = solve_full_information_upper_bound(case['payload']).contribution_margin_usd
    if not math.isfinite(bound) or bound <= 0:
        raise ValueError('screen requires a positive certified contribution margin')
    policy_rows = {'displayed_price_greedy': [], 'replay_best_qualified': []}
    episode_digests = []
    for seed in seeds:
        episode = episode_case(case, seed)
        episode_digests.append(episode['content_sha256'])
        for policy in policy_rows:
            outcome = (replay_best_qualified(episode['payload']) if policy == 'replay_best_qualified'
                       else replay_baseline_outcome(episode['payload'], policy))
            if outcome is None:
                raise ValueError(f'{policy} did not produce a terminal outcome')
            policy_rows[policy].append({'environment_seed': seed, **outcome})
    ref = policy_rows['replay_best_qualified']
    greedy = policy_rows['displayed_price_greedy']
    regrets = [r['regret_to_upper_bound_usd'] for r in ref]
    greedy_mean = statistics.mean(r['regret_to_upper_bound_usd'] for r in greedy)
    reference_mean = statistics.mean(regrets)
    continuous = classify_world_continuous(
        regrets, {'displayed_price_greedy': greedy_mean}, minimum_relative_spread=MINIMUM_RELATIVE_SPREAD,
        materiality_scale=bound,
    )
    # Dispersion can be luck. Also require mean policy separation, not only one
    # lucky reference seed, and a reference that can form an authorized award.
    reasons = []
    if continuous != ADMIT:
        reasons.append(continuous)
    if not any(r['feasible_award'] for r in ref):
        reasons.append(FLOORED)
    if greedy_mean <= 1e-8:
        reasons.append(TRIVIAL)
    if greedy_mean - reference_mean < MINIMUM_RELATIVE_SPREAD * bound:
        reasons.append('reject: mean policy spread below 15 percent of certified margin')
    return {
        'case_id': case['case_id'], 'case_content_sha256': case['content_sha256'],
        'world_id': economic_world_id(case), 'world_seed': case['world_seed'],
        'verdict': 'reject' if reasons else ADMIT, 'rejection_reasons': reasons,
        'continuous_verdict': continuous, 'environment_seeds': list(seeds),
        'episode_case_digests': episode_digests,
        'materiality_scale': 'certified_full_information_contribution_margin_usd',
        'materiality_scale_usd': bound, 'minimum_spread_usd': MINIMUM_RELATIVE_SPREAD * bound,
        'mean_policy_spread_usd': greedy_mean - reference_mean,
        'reference_within_world_variance': within_world_variance(regrets),
        'reference_feasible_award_rate': statistics.mean(r['feasible_award'] for r in ref),
        'greedy_feasible_award_rate': statistics.mean(r['feasible_award'] for r in greedy),
        'live_model_control_rate': None, 'policy_rows': policy_rows,
    }


def screen_panel(cases: Sequence[Mapping[str, Any]], seeds: Sequence[int] = SCREEN_SEEDS) -> dict:
    if not cases:
        raise ValueError('candidate panel must be nonempty')
    world_ids = [economic_world_id(case) for case in cases]
    if len(world_ids) != len(set(world_ids)):
        raise ValueError('candidate panel repeats an economic world or presentation mirror')
    candidates = [screen_world(case, seeds) for case in cases]
    admitted = [r['world_id'] for r in candidates if r['verdict'] == ADMIT]
    selected = admitted[:REQUIRED_WORLDS]
    return _seal({
        'schema_version': 'aeread.procurement_continuous_screen/1.0',
        'campaign_id': CAMPAIGN_ID, 'status': 'passed' if len(selected) == REQUIRED_WORLDS else 'failed',
        'selection_rule': 'first six admitted worlds in predeclared candidate order',
        'required_world_count': REQUIRED_WORLDS, 'candidate_count': len(candidates),
        'admitted_world_count': len(admitted), 'selected_world_ids': selected,
        'environment_seeds': list(seeds), 'minimum_relative_spread': MINIMUM_RELATIVE_SPREAD,
        'implementation_pins': implementation_pins(), 'candidates': candidates,
        'provider_calls': 0, 'provider_cost_usd': 0.,
        'rate_scope': 'offline public-observation policies; no measured live-model control rate',
        'claim_scope': 'curated synthetic candidate screen; not production procurement or model confirmation',
    })


def build_plan(screen: Mapping[str, Any]) -> dict:
    if _digest({k: v for k, v in screen.items() if k != 'artifact_sha256'}) != screen.get('artifact_sha256'):
        raise ValueError('screen digest mismatch')
    if screen.get('implementation_pins') != implementation_pins():
        raise ValueError('screen implementation changed; rerun provider-free admission')
    selected = screen.get('selected_world_ids', [])
    candidates = {row['world_id']: row for row in screen['candidates']}
    if screen.get('status') != 'passed' or len(selected) != REQUIRED_WORLDS or len(set(selected)) != REQUIRED_WORLDS:
        raise ValueError('cannot plan live execution without exactly six admitted economic worlds')
    if any(candidates[w]['verdict'] != ADMIT for w in selected):
        raise ValueError('selected world did not pass admission')
    return _seal({
        'schema_version': 'aeread.procurement_continuous_design/1.0', 'campaign_id': CAMPAIGN_ID,
        'freeze_status': 'design_only_pending_provider_admission_and_variance_pilot',
        'screen_artifact_sha256': screen['artifact_sha256'], 'world_ids': selected,
        'implementation_pins': implementation_pins(),
        'metric': 'regret_to_upper_bound_usd', 'promotion_rule': 'runner.continuous_promotion_rule',
        'sample_noise': 'counter_based_binomial_accumulating_per_supplier',
        'pilot_environment_seeds': list(PILOT_SEEDS), 'pilot_rows': REQUIRED_WORLDS * len(PILOT_SEEDS) * 2,
        'confirmatory_environment_seeds': list(CONFIRMATORY_SEEDS), 'confirmatory_rows': 36,
        'seed_pairing': 'same environment seed and inference seed in both arms',
        'canaries': 'one per distinct admitted provider/harness/prompt profile; separately counted',
        'hard_total_cost_ceiling_usd': HARD_COST_CEILING_USD,
        'budget_scope': 'canaries plus pilot plus confirmatory calls, retries, and failed calls',
        'inference': 'paired cluster bootstrap over six economic worlds after within-world seed means',
        'power': 'not established; estimate from pilot variance and declared meaningful effect before freeze',
        'live_call_count': 'trajectories are multi-turn; count every provider request separately',
        'required_gates': ['provider_free_full_suite', 'six_world_admission', 'synthetic_falsification',
                           'provider_admission', 'full_trajectory_per_arm', 'paired_variance_pilot',
                           'budget_and_precision', 'confirmatory_freeze', 'all_receipts_replayed'],
        'no_selective_reruns': True,
    }, 'plan_sha256')


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--candidate', type=Path, action='append')
    source.add_argument('--generated-pool', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selected-case-output', type=Path)
    parser.add_argument('--seeds', type=int, nargs='+', default=SCREEN_SEEDS)
    args = parser.parse_args(argv)
    if args.generated_pool:
        from .continuous_case_matrix import build_candidate, CANDIDATE_COUNT
        cases = [build_candidate(i) for i in range(CANDIDATE_COUNT)]
    else:
        cases = [json.loads(path.read_text()) for path in args.candidate]
    result = screen_panel(cases, args.seeds)
    _write_once_json(args.output, result)
    if args.selected_case_output and result['status'] == 'passed':
        selected = set(result['selected_world_ids'])
        for case in cases:
            if economic_world_id(case) in selected:
                _write_once_json(args.selected_case_output / f"{case['case_id'].rsplit('.', 1)[-1]}.json", case)
    print(json.dumps({k: result[k] for k in ('status', 'candidate_count', 'admitted_world_count', 'selected_world_ids', 'artifact_sha256')}, indent=2))
    return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
