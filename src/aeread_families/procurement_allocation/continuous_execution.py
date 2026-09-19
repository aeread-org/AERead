"""Sequential execution of the admitted continuous procurement experiment.

Every stage consumes a shared campaign promotion decision. No paid call is made
until the full offline validation record and six-world screen have passed.
Requests reserve a conservative token-cost bound before dispatch; an unknown
provider outcome retains its reservation and stops the campaign.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from aeread.shared_runner.quality import QCCoverage, QCEvidenceRef
from aeread.shared_runner.run.campaign import (
    CampaignGateRecord, append_campaign_gate, campaign_gate_artifact_type,
    campaign_history_record_from_dict, campaign_promotion_decision,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient, execute_plan_cell
from aeread.shared_runner.task.evaluation import audit_family_receipt
from .continuous_campaign import (
    CAMPAIGN_ID, PILOT_SEEDS, CONFIRMATORY_SEEDS, HARD_COST_CEILING_USD,
    _digest, _seal, build_plan, economic_world_id, episode_case, implementation_pins,
)
from .environment import FAMILY_ID, FAMILY_VERSION
from .model_campaign import (
    _run_cell, _write_once_json, _validate_operational_run_root,
    _read_result, _result_path, _safe_case_directory,
)
from .pre_award_confirmatory_campaign import SCAFFOLD_PROMPT, STRATEGY_PROMPT
from .runner import continuous_promotion_rule, build_openrouter_setup, SequenceResponseProvider
from .strategy_scaffold import GLM_PARASAIL_CANDIDATE
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

# The same observation contract is added to both historical, frozen prompts.
NOISE_NOTICE = '''\nThis episode uses binomial sample batches. A verified sample establishes
variant/evidence eligibility, not exact yield. observed_yield_rate is an estimate;
repeat samples accumulate. check_award projects only from your available evidence.
Optimize contribution margin; do not equate an eligible award with a good deal.
'''
PROMPTS = {'control': SCAFFOLD_PROMPT + NOISE_NOTICE, 'treatment': STRATEGY_PROMPT + NOISE_NOTICE}
PROFILE_ID = 'procurement_continuous_regret_v1'


class CampaignBudgetExceeded(RuntimeError):
    pass


class BudgetedProvider:
    """One sequential, persistent ledger shared by all arms and all stages."""
    def __init__(self, provider: Any, root: Path, ceiling: float = HARD_COST_CEILING_USD):
        if not math.isfinite(ceiling) or ceiling <= 0 or ceiling > HARD_COST_CEILING_USD:
            raise ValueError('budget must be positive and within the declared hard ceiling')
        self.provider, self.root, self.ceiling = provider, root, ceiling
        self.calls = sorted((root / 'billing').glob('call_*.json'))
        self.spent = 0.
        for path in self.calls:
            record = json.loads(path.read_text())
            if record['status'] != 'settled':
                raise RuntimeError('unsettled provider request; audit before resuming')
            self.spent += record['cost_usd']
        self.stopped = False

    async def complete(self, request):
        if self.stopped:
            raise CampaignBudgetExceeded('campaign dispatch stopped')
        route = GLM_PARASAIL_CANDIDATE.route
        if request.model != route.model or request.revision != route.revision:
            raise ValueError('request model/revision differs from frozen route')
        if (request.provider_metadata or {}).get('route_provider') != route.route_provider:
            raise ValueError('request provider differs from frozen route')
        # Text tokens cannot exceed encoded bytes on this pinned byte-tokenized
        # route; include the complete schema and a 2,048-token wire overhead.
        input_ceiling = len(canonical_json_bytes({
            'instructions': request.instructions, 'input': request.input_text,
            'schema': request.output_schema, 'messages': request.messages, 'tools': request.tools,
        })) + 2048
        reserve = (input_ceiling * route.pricing.input_per_million
                   + request.max_output_tokens * route.pricing.output_per_million) / 1_000_000
        if self.spent + reserve > self.ceiling:
            self.stopped = True
            raise CampaignBudgetExceeded('next request cannot fit the campaign hard cost ceiling')
        ordinal = len(self.calls)
        pending = self.root / 'billing' / f'pending_{ordinal:05d}.json'
        if pending.exists():
            raise RuntimeError('pending provider request cannot be repeated')
        _write_once_json(pending, {'request_sha256': request.request_sha256, 'reserved_cost_usd': reserve})
        path = self.root / 'billing' / f'call_{ordinal:05d}.json'
        try:
            result = await self.provider.complete(request)
        except BaseException:
            self.stopped = True
            _write_once_json(path, {'status': 'unknown_provider_outcome', 'request_sha256': request.request_sha256, 'reserved_cost_usd': reserve, 'cost_usd': None})
            raise
        cost = result.cost_usd
        valid_cost = isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0
        record = {
            'status': 'settled' if valid_cost else 'unknown_provider_cost',
            'request_sha256': request.request_sha256, 'reserved_cost_usd': reserve,
            'cost_usd': cost, 'resolved_model': result.resolved_model,
            'input_tokens': result.input_tokens, 'output_tokens': result.output_tokens,
        }
        _write_once_json(path, record)
        self.calls.append(path)
        if not valid_cost:
            self.stopped = True
            raise RuntimeError('provider omitted valid billing; campaign stopped')
        self.spent += cost
        if cost > reserve + 1e-10 or self.spent > self.ceiling + 1e-10:
            self.stopped = True
            raise RuntimeError('provider charge exceeded conservative reservation')
        if result.resolved_model != route.revision:
            self.stopped = True
            raise RuntimeError('provider revision drifted')
        return result


def _history(root: Path):
    return [campaign_history_record_from_dict(json.loads(p.read_text())) for p in sorted((root / 'gates').glob('*.json'))]


def _gate(root: Path, gate: str, artifact: Mapping[str, Any], *, passed: bool, failures=()):
    history = _history(root)
    decision = campaign_promotion_decision(CAMPAIGN_ID, gate, history, evidence_root=root)
    if not decision.eligible:
        raise ValueError(f'{gate} blocked: {decision.blockers}')
    status = 'passed' if passed else 'failed'
    path = root / 'gate_evidence' / f'{gate}_{decision.next_attempt_index}.json'
    _write_once_json(path, dict(artifact))
    import hashlib
    ref = QCEvidenceRef(
        artifact_type=campaign_gate_artifact_type(gate, status), path=str(path.relative_to(root)),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), family_id=FAMILY_ID,
        family_version=FAMILY_VERSION, profile_id=PROFILE_ID,
        coverage=(QCCoverage(gate, ('declared_contract',), ('declared_contract',) if passed else ()),),
    )
    record = CampaignGateRecord(CAMPAIGN_ID, FAMILY_ID, FAMILY_VERSION, PROFILE_ID, gate,
                                decision.next_attempt_index, status, (ref,), tuple(failures))
    append_campaign_gate(history, record, evidence_root=root)
    _write_once_json(root / 'gates' / f'{len(history):02d}_{gate}.json',
                     {'record_type':'gate', **json.loads(canonical_json_bytes(record))})


def _latest(root: Path, gate: str):
    matches = [r for r in _history(root) if r.gate_id == gate]
    return matches[-1] if matches else None


def pilot_diagnostics(rows, worlds):
    complete = len(rows) == len(worlds) * len(PILOT_SEEDS) * 2
    index = {(r['world_id'], r['environment_seed'], r['arm']): r for r in rows}
    complete = complete and len(index) == len(rows) and all(
        (w, s, a) in index for w in worlds for s in PILOT_SEEDS for a in PROMPTS
    )
    completed = complete and all(r.get('status') == 'completed' and r.get('receipt_replayed') is True for r in rows)
    diagnostics = {'complete_paired_design': complete, 'no_operational_failures': completed,
                   'within_world_arm_variance': {}, 'measured_live_control_rates': {},
                   'precision_status': 'unmeasured'}
    if not completed:
        return {**diagnostics, 'passed': False}
    deltas, bounds = [], []
    for world in worlds:
        for arm in PROMPTS:
            scores = [index[world, s, arm]['regret_to_upper_bound_usd'] for s in PILOT_SEEDS]
            diagnostics['within_world_arm_variance'][f'{world}:{arm}'] = statistics.variance(scores)
        diagnostics['measured_live_control_rates'][world] = statistics.mean(index[world, s, 'control']['feasible_award'] for s in PILOT_SEEDS)
        deltas.append(statistics.mean(index[world,s,'treatment']['regret_to_upper_bound_usd'] - index[world,s,'control']['regret_to_upper_bound_usd'] for s in PILOT_SEEDS))
        bounds.append(index[world, PILOT_SEEDS[0], 'control']['upper_bound_usd'])
    # A transparent sizing sensitivity, not an unsupported bootstrap-power claim.
    from scipy.stats import nct, t
    sd = statistics.stdev(deltas)
    meaningful_effect = .15 * statistics.mean(bounds)
    critical = t.ppf(.975, len(worlds) - 1)
    power = None if sd == 0 else float(1 - nct.cdf(critical, len(worlds) - 1, meaningful_effect / sd * len(worlds)**.5)
                                     + nct.cdf(-critical, len(worlds) - 1, meaningful_effect / sd * len(worlds)**.5))
    diagnostics.update(
        paired_world_delta_sd_usd=sd, minimum_meaningful_regret_effect_usd=meaningful_effect,
        paired_t_power_sensitivity=power, precision_status='proxy_only_not_bootstrap_power',
        nonzero_sampling_dispersion=any(v > 0 for v in diagnostics['within_world_arm_variance'].values()),
        total_provider_cost_usd=sum(r.get('cost_usd') or 0 for r in rows),
        provider_call_count=sum(r.get('provider_call_count', 0) for r in rows),
        maximum_trajectory_latency_seconds=max(r['elapsed_seconds'] for r in rows),
        token_and_latency_bounds_respected=all(
            r['elapsed_seconds'] <= 9 * 180 and r.get('output_tokens', 0) <= 9 * 1800 for r in rows
        ),
        bootstrap_power_sensitivity=bootstrap_power_sensitivity(sd, meaningful_effect, len(worlds)),
    )
    diagnostics['passed'] = diagnostics['nonzero_sampling_dispersion'] and diagnostics['token_and_latency_bounds_respected']
    return diagnostics


def bootstrap_power_sensitivity(sd, meaningful_effect, world_count):
    """Conditional planning simulation, with assumptions and Monte Carlo error.

    Six noisy pilot cluster means cannot identify a population distribution.
    This reports power only under independent normal world effects at the
    observed pilot SD; it does not establish unconditional population power.
    """
    if sd <= 0 or not math.isfinite(sd):
        return {'status':'unidentified', 'power':None, 'monte_carlo_95_lower':None}
    import numpy as np
    rng = np.random.default_rng(9192026)
    simulations, resamples = 1000, 2000
    supported = 0
    for _ in range(simulations):
        worlds = rng.normal(-meaningful_effect, sd, world_count)
        means = worlds[rng.integers(0, world_count, size=(resamples, world_count))].mean(axis=1)
        supported += np.quantile(means, .975) < 0
    p = float(supported / simulations)
    z = 1.959963984540054
    denominator = 1 + z*z/simulations
    lower = (p + z*z/(2*simulations) - z*math.sqrt(p*(1-p)/simulations + z*z/(4*simulations**2))) / denominator
    return {'status':'conditional_simulation', 'power':p, 'monte_carlo_95_lower':lower,
            'assumptions':'independent normal world effects with SD estimated from six pilot cluster means',
            'simulations':simulations, 'bootstrap_resamples_per_simulation':resamples, 'seed':9192026,
            'limitations':'conditional planning sensitivity; pilot SD and population distribution remain uncertain'}


async def _canary(root, arm, case_path, provider):
    setup = build_openrouter_setup(GLM_PARASAIL_CANDIDATE.route, case_path=case_path, seed=PILOT_SEEDS[0],
                                   prompt=PROMPTS[arm], prompt_id=f'{CAMPAIGN_ID}_{arm}', max_cost_usd=.035)
    fake = SequenceResponseProvider((json.dumps({'action':'defer', 'reason':'canary request capture'}),))
    with tempfile.TemporaryDirectory(prefix='procurement-canary-') as temp:
        await execute_plan_cell(plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry,
                                evidence_root=Path(temp), prompt_sources=setup.prompt_sources,
                                providers={'openrouter':fake}, pricing=setup.pricing, harnesses=setup.harnesses)
    assert len(fake.requests) == 1
    request = fake.requests[0]
    path = root / 'canaries' / f'{arm}.json'
    if path.exists():
        record = json.loads(path.read_text())
        if record['request_sha256'] != request.request_sha256 or record.get('artifact_sha256') != _digest({k:v for k,v in record.items() if k != 'artifact_sha256'}):
            raise ValueError('canary request changed')
        return record
    try:
        response = await provider.complete(request)
        from .environment import ProcurementAllocationPlugin
        plugin = ProcurementAllocationPlugin()
        case = plugin.validate_payload(setup.case.payload)
        parsed = plugin.parse_action(case, plugin.initial_state(case, None), 'buyer', plugin.phases(case)[0], response.output_text)
        valid = parsed.ok and plugin.legal(case, plugin.initial_state(case, None), 'buyer', plugin.phases(case)[0], parsed.action).legal
        record = {'status': 'admitted' if valid else 'rejected', 'request_sha256': request.request_sha256,
                  'resolved_model': response.resolved_model, 'cost_usd': response.cost_usd,
                  'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens,
                  'raw_output': response.output_text, 'scored': False}
    except Exception as error:
        record = {'status':'rejected', 'request_sha256':request.request_sha256,
                  'failure_type':type(error).__name__, 'cost_usd':None, 'scored':False}
    _write_once_json(path, _seal(record))
    return record


def _audit_row(root, phase, arm, case_path, row):
    if row.get('status') != 'completed':
        return
    setup = build_openrouter_setup(GLM_PARASAIL_CANDIDATE.route, seed=row['inference_seed'],
                                   case_path=case_path, prompt=PROMPTS[arm], prompt_id=f'{CAMPAIGN_ID}_{arm}',
                                   max_cost_usd=.035)
    directory = root / phase / arm / 'executions' / _safe_case_directory(setup.case.case_id, setup.case.content_sha256) / f"seed_{row['inference_seed']}"
    receipts = list(directory.rglob('evaluation_receipt.json'))
    if len(receipts) != 1:
        raise ValueError('completed row must have exactly one sealed receipt')
    receipt = audit_family_receipt(setup=setup, receipt_path=receipts[0])
    if receipt['receipt_sha256'] != row['receipt_sha256']:
        raise ValueError('row points at a different receipt')
    from .regret_decomposition import replay_action_trace
    outcome = replay_action_trace(setup.case.payload, row['action_trace'])['outcome']
    for field in ('contribution_margin_usd', 'upper_bound_usd', 'regret_to_upper_bound_usd', 'completed_kits', 'feasible_award'):
        if outcome[field] != row[field]:
            raise ValueError(f'row {field} differs from replayed outcome')


async def _rows(root, phase, cases, seeds, provider, executor, receipt_auditor, limit=None):
    rows = []
    for case in cases:
        world = economic_world_id(case)
        for seed in seeds:
            episode = episode_case(case, seed)
            case_path = root / 'cases' / f'{world}_{seed}.json'
            _write_once_json(case_path, episode)
            # Alternate order independently of outcomes; both arms receive the same draw stream.
            arms = list(PROMPTS) if seed % 2 else list(reversed(PROMPTS))
            for arm in arms:
                path = root / phase / 'rows' / f'{world}_{seed}_{arm}.json'
                if path.exists():
                    row = json.loads(path.read_text())
                    if row.get('artifact_sha256') != _digest({k:v for k,v in row.items() if k != 'artifact_sha256'}):
                        raise ValueError('saved row digest mismatch')
                elif provider.stopped:
                    row = _seal({'world_id':world, 'environment_seed':seed, 'arm':arm,
                                 'status':'not_attempted', 'failure_condition':'campaign_dispatch_stopped',
                                 'receipt_replayed':False, 'cost_usd':None})
                    _write_once_json(path, row)
                else:
                    raw_path = _result_path(root / phase / arm, case_id=episode['case_id'],
                                            content_sha256=episode['content_sha256'], seed=seed)
                    evidence_path = root / phase / arm / 'executions' / _safe_case_directory(episode['case_id'], episode['content_sha256']) / f'seed_{seed}'
                    if raw_path.exists():
                        raw = _read_result(raw_path, case_id=episode['case_id'], content_sha256=episode['content_sha256'], seed=seed)
                    elif evidence_path.exists():
                        raise RuntimeError('partial trajectory requires receipt/billing audit before resume')
                    else:
                        raw = await executor(
                            run_root=root / phase / arm, case_path=case_path, inference_seed=seed,
                            semaphore=asyncio.Semaphore(1), provider_factory=lambda: provider,
                            candidate=GLM_PARASAIL_CANDIDATE, prompt=PROMPTS[arm],
                            prompt_id=f'{CAMPAIGN_ID}_{arm}', max_action_attempts=1, retryable_conditions=(),
                            retry_backoff=None, retry_base_seconds=2., retry_after_max_seconds=60., max_cost_usd_per_trajectory=.035,
                        )
                    row = _seal({**raw, 'world_id': world, 'environment_seed': seed, 'arm': arm})
                    _write_once_json(path, row)
                receipt_auditor(root, phase, arm, case_path, row)
                rows.append(row)
                if limit is not None and len(rows) >= limit:
                    return rows
    return rows


async def run_campaign(*, root: Path, screen: Mapping, cases: list[dict], validation: Mapping,
                       stop_after='pilot', provider_factory: Callable = OpenRouterChatClient,
                       preflight: Callable = preflight_candidate, executor: Callable = _run_cell,
                       receipt_auditor: Callable = _audit_row):
    _validate_operational_run_root(root)
    design = build_plan(screen)
    wanted = design['world_ids']
    by_id = {economic_world_id(c): c for c in cases}
    cases = [by_id[w] for w in wanted]
    screened = {c['world_id']: c for c in screen['candidates']}
    if any(c['content_sha256'] != screened[economic_world_id(c)]['case_content_sha256'] for c in cases):
        raise ValueError('selected case bytes differ from admitted candidates')
    plan = _seal({
        'design': design, 'prompts': PROMPTS,
        'route': json.loads(canonical_json_bytes(GLM_PARASAIL_CANDIDATE)),
        'case_digests': [c['content_sha256'] for c in cases],
        'execution_order': 'world_then_environment_seed_then_alternating_arm',
        'retries': 0, 'max_output_tokens': 1800, 'max_trajectory_cost_usd': .035,
        'precision_policy': 'report pilot sizing proxy; no unsupported 80 percent bootstrap-power claim',
        'pilot_max_trajectory_latency_seconds': 9 * 180.,
        'pilot_max_output_tokens_per_trajectory': 9 * 1800,
    }, 'plan_sha256')
    _write_once_json(root / 'execution_design.json', plan)
    if not _latest(root, 'design_contract'):
        _gate(root, 'design_contract', plan, passed=True)
    if not _latest(root, 'provider_free_validation'):
        valid = validation_is_current(validation)
        _gate(root, 'provider_free_validation', validation, passed=valid,
              failures=() if valid else ('full provider-free validation is missing or stale',))
    if not _latest(root, 'profile_admission'):
        decision = campaign_promotion_decision(CAMPAIGN_ID, 'profile_admission', _history(root), evidence_root=root)
        if not decision.eligible:
            return {'status': 'blocked', 'blockers': decision.blockers}
    provider = BudgetedProvider(provider_factory(), root)
    if not _latest(root, 'profile_admission'):
        route = preflight(GLM_PARASAIL_CANDIDATE)
        canary_case = root / 'cases' / 'canary.json'
        _write_once_json(canary_case, episode_case(cases[0], PILOT_SEEDS[0]))
        canaries = {arm:await _canary(root, arm, canary_case, provider) for arm in PROMPTS}
        admitted = all(c['status'] == 'admitted' for c in canaries.values())
        _gate(root, 'profile_admission', {'route':route, 'canaries':canaries}, passed=admitted,
              failures=() if admitted else ('provider canary failed',))
    if _latest(root, 'profile_admission').status != 'passed':
        return {'status':'provider_admission_failed', 'spent_usd':provider.spent}
    if _latest(root, 'full_trajectory') and _latest(root, 'full_trajectory').status != 'passed':
        return {'status':'failed_full_trajectory', 'spent_usd':provider.spent}
    if _latest(root, 'variance_pilot') is None:
        rows = await _rows(root, 'pilot', cases, PILOT_SEEDS, provider, executor, receipt_auditor, limit=2)
        representative = {arm: next((r for r in rows if r['arm'] == arm), None) for arm in PROMPTS}
        trajectories_ok = all(r and r.get('status') == 'completed' and r.get('receipt_replayed') is True for r in representative.values())
        if not _latest(root, 'full_trajectory'):
            _gate(root, 'full_trajectory', {'representative_rows': representative}, passed=trajectories_ok,
                  failures=() if trajectories_ok else ('one complete replayed trajectory per arm is required',))
        if not trajectories_ok:
            return {'status': 'failed_full_trajectory', 'spent_usd': provider.spent}
        rows = await _rows(root, 'pilot', cases, PILOT_SEEDS, provider, executor, receipt_auditor)
        diagnostics = pilot_diagnostics(rows, wanted)
        _gate(root, 'variance_pilot', diagnostics, passed=diagnostics['passed'],
              failures=() if diagnostics['passed'] else ('paired pilot incomplete, failed, or zero sampling dispersion',))
        _write_once_json(root / 'pilot_summary.json', _seal(diagnostics))
    pilot = json.loads((root / 'pilot_summary.json').read_text())
    if stop_after == 'pilot' or not pilot['passed']:
        return {'status': 'pilot_passed' if pilot['passed'] else 'pilot_failed', 'pilot': pilot, 'spent_usd': provider.spent}
    # Precision is a separate exit gate: a six-world result cannot be justified
    # by the attachment's unsupported d=1.15 power assertion.
    power = pilot['bootstrap_power_sensitivity']
    if power['monte_carlo_95_lower'] is None or power['monte_carlo_95_lower'] < .8:
        return {'status': 'precision_gate_failed', 'pilot': pilot, 'spent_usd': provider.spent}
    expected_remaining = pilot['total_provider_cost_usd'] / 24 * 36
    if provider.spent + expected_remaining > HARD_COST_CEILING_USD:
        return {'status': 'projected_budget_gate_failed', 'spent_usd': provider.spent, 'expected_remaining_usd': expected_remaining}
    if not _latest(root, 'confirmatory_freeze'):
        frozen = _seal({'execution_design_sha256': plan['plan_sha256'], 'pilot_artifact_sha256': pilot['artifact_sha256'],
                        'environment_seeds': list(CONFIRMATORY_SEEDS), 'planned_rows': 36,
                        'hard_total_cost_ceiling_usd': HARD_COST_CEILING_USD}, 'plan_sha256')
        _write_once_json(root / 'confirmatory_plan.json', frozen)
        _gate(root, 'confirmatory_freeze', frozen, passed=True)
    if _latest(root, 'confirmatory_execution'):
        return json.loads((root / 'comparison.json').read_text())
    rows = await _rows(root, 'confirmatory', cases, CONFIRMATORY_SEEDS, provider, executor, receipt_auditor)
    comparison = continuous_promotion_rule(rows, world_ids=wanted, seeds=CONFIRMATORY_SEEDS)
    _write_once_json(root / 'comparison.json', _seal(comparison))
    replay_complete = len(rows) == 36 and all(r.get('receipt_replayed') is True for r in rows)
    _gate(root, 'confirmatory_execution', comparison, passed=replay_complete,
          failures=() if replay_complete else ('all 36 cells must complete and replay',))
    return comparison


def validation_is_current(validation):
    import hashlib
    import re
    try:
        raw = Path(validation['log_path']).read_bytes()
    except (KeyError, OSError):
        return False
    matches = re.findall(rb'(\d+) passed', raw)
    return (
        validation.get('exit_code') == 0 and bool(matches)
        and int(matches[-1]) == validation.get('tests_passed')
        and int(matches[-1]) >= 1782
        and hashlib.sha256(raw).hexdigest() == validation.get('log_sha256')
        and validation.get('implementation_pins') == implementation_pins()
        and validation.get('synthetic_falsification_passed') is True
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screen', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--stage', choices=('pilot','confirmatory'), default='pilot')
    args = parser.parse_args(argv)
    args.run_root.mkdir(parents=True, exist_ok=True)
    lock = args.run_root / 'execution.lock'
    # An orphaned lock requires a receipt/billing audit, not automatic replay of
    # a potentially billed request. Normal completion releases it.
    with lock.open('x') as handle:
        import os
        handle.write(str(os.getpid()))
    try:
        result = asyncio.run(run_campaign(root=args.run_root, screen=json.loads(args.screen.read_text()),
                                         cases=[json.loads(p.read_text()) for p in sorted(args.cases.glob('*.json'))],
                                         validation=json.loads(args.validation.read_text()), stop_after=args.stage))
        print(json.dumps(result, indent=2))
    finally:
        lock.unlink()
    return 0 if result.get('status') in {'pilot_passed','supported','not_supported'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
