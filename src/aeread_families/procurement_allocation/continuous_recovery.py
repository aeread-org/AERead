"""Approved, separately frozen recovery; original measurement artifacts stay immutable."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import tempfile
from pathlib import Path

from aeread.shared_runner.quality import QCCoverage, QCEvidenceRef, verify_qc_evidence_files
from aeread.shared_runner.run.campaign import (
    CampaignGateRecord, append_campaign_gate, campaign_gate_artifact_type,
    campaign_promotion_decision,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.execution import OpenRouterChatClient, ProviderFailure, execute_plan_cell
from aeread.shared_runner.task.evaluation import audit_family_receipt
from . import continuous_execution as original
from .continuous_campaign import (
    _digest, _seal, build_plan, economic_world_id, episode_case as original_episode_case,
    implementation_pins as original_pins, REPOSITORY_ROOT, HARD_COST_CEILING_USD,
)
from .continuous_publication import _read_sealed
from .environment import FAMILY_ID, FAMILY_VERSION
from .model_campaign import (
    _run_cell, _write_once_json, _validate_operational_run_root,
    _read_result, _result_path, _safe_case_directory,
)
from .runner import continuous_promotion_rule, build_openrouter_setup, SequenceResponseProvider
from .strategy_scaffold import GLM_PARASAIL_CANDIDATE
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

CAMPAIGN_ID = 'procurement_allocation_unified_regret_recovery_v2'
PROFILE_ID = 'procurement_continuous_regret_recovery_v2'
CONFIRMATORY_SEEDS = (49001, 49002, 49003)
CANARY_SEED = 49000
PROMPTS = original.PROMPTS
BASELINE_SETTLED = .1320779295
BASELINE_RESERVED = .0023634
# Two authorized Gemini coding-review requests; never benchmark observations.
SUPPORT_REVIEW_COST_USD = .0138647025
RETRY_POLICY = dict(max_action_attempts=2, retryable_conditions=('rate_limit',),
                    retry_backoff='exponential_jitter_v1', retry_base_seconds=2.,
                    retry_after_max_seconds=180.)
_history = original._history
_latest = original._latest
CampaignBudgetExceeded = original.CampaignBudgetExceeded


def implementation_pins():
    pins = {f'family/{k}': v for k, v in original_pins().items()}
    paths = ['src/aeread_families/procurement_allocation/continuous_recovery.py',
             'src/aeread_families/procurement_allocation/continuous_recovery_publication.py',
             'src/aeread_families/procurement_allocation/model_campaign.py']
    paths += [str(p.relative_to(REPOSITORY_ROOT)) for p in
              sorted((REPOSITORY_ROOT / 'src/aeread/shared_runner').rglob('*.py'))]
    pins.update({p: hashlib.sha256((REPOSITORY_ROOT / p).read_bytes()).hexdigest() for p in paths})
    return pins


def episode_case(case, seed):
    result = original_episode_case(case, seed)
    result['case_id'] = f'{CAMPAIGN_ID}.{economic_world_id(case)[:16]}.sample_{seed}'
    result['split'] = 'unified_regret_recovery_v2'
    result['content_sha256'] = '0' * 64
    result['content_sha256'] = case_content_sha256(CaseManifest.from_dict(result))
    return result


class RecoveryProvider:
    """Reserve before every request; only an explicit 429 can enter retry state.

    The runner owns action retries. Raising a typed 429 with a floor of 60s
    makes its sealed backoff event carry the actual required delay. A second
    rejection, an excessive Retry-After, or any other error stops all dispatch.
    Interrupted runs cannot be restarted automatically, even after a 429.
    """
    def __init__(self, provider, root, *, baseline=BASELINE_SETTLED + BASELINE_RESERVED + SUPPORT_REVIEW_COST_USD,
                 ceiling=HARD_COST_CEILING_USD):
        if not (math.isfinite(baseline) and math.isfinite(ceiling)
                and 0 <= baseline < ceiling <= HARD_COST_CEILING_USD):
            raise ValueError('invalid combined campaign budget')
        if list((root / 'billing').glob('*.json')):
            raise RuntimeError('existing billing requires audit; recovery cannot be dispatched twice')
        self.provider, self.root, self.ceiling = provider, root, ceiling
        self.spent, self.calls, self.stopped = baseline, [], False
        self.retry_request = None

    async def complete(self, request):
        if self.stopped:
            raise CampaignBudgetExceeded('campaign dispatch stopped')
        route = GLM_PARASAIL_CANDIDATE.route
        if (request.model != route.model or request.revision != route.revision
                or (request.provider_metadata or {}).get('route_provider') != route.route_provider):
            self.stopped = True
            raise ValueError('request differs from frozen route')
        retrying = self.retry_request is not None
        if retrying and request.request_sha256 != self.retry_request:
            self.stopped = True
            raise ValueError('retry changed the logical action request')
        input_ceiling = len(canonical_json_bytes({
            'instructions': request.instructions, 'input': request.input_text,
            'schema': request.output_schema, 'messages': request.messages, 'tools': request.tools,
        })) + 2048
        reserve = (input_ceiling * route.pricing.input_per_million
                   + request.max_output_tokens * route.pricing.output_per_million) / 1_000_000
        if self.spent + reserve > self.ceiling:
            self.stopped = True
            raise CampaignBudgetExceeded('next request cannot fit combined hard ceiling')
        ordinal = len(self.calls)
        pending = {'request_sha256': request.request_sha256,
                   'provider_call_id': request.provider_call_id,
                   'reserved_cost_usd': reserve, 'retry_of_previous_request': retrying}
        _write_once_json(self.root / 'billing' / f'pending_{ordinal:05d}.json', pending)
        path = self.root / 'billing' / f'call_{ordinal:05d}.json'
        self.spent += reserve
        self.calls.append(path)
        try:
            result = await self.provider.complete(request)
        except BaseException as error:
            explicit_429 = isinstance(error, ProviderFailure) and error.condition == 'rate_limit' and error.status_code == 429
            delay = max(60., error.retry_after_seconds or 0.) if explicit_429 else None
            allowed = explicit_429 and error.retryable and not retrying and delay <= 180.
            self.stopped = not allowed
            self.retry_request = request.request_sha256 if allowed else None
            _write_once_json(path, {**pending, 'status': 'rejected_429_billing_unknown' if explicit_429 else 'unknown_provider_outcome',
                                   'cost_usd': None, 'retry_permitted': allowed,
                                   'required_retry_delay_seconds': delay,
                                   'provider_retry_after_seconds': error.retry_after_seconds if explicit_429 else None})
            if explicit_429:
                raise ProviderFailure('rate_limit', 'explicit HTTP 429; see preserved provider evidence',
                                      retryable=allowed, status_code=429,
                                      retry_after_seconds=delay) from error
            raise
        cost = result.cost_usd
        valid = isinstance(cost, (float, int)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0
        _write_once_json(path, {**pending, 'status': 'settled' if valid else 'unknown_provider_cost',
                               'cost_usd': cost if valid else None, 'resolved_model': result.resolved_model,
                               'input_tokens': result.input_tokens, 'output_tokens': result.output_tokens})
        if not valid:
            self.stopped = True
            raise RuntimeError('provider omitted valid billing')
        self.spent += cost - reserve
        self.retry_request = None
        if cost > reserve + 1e-10 or self.spent > self.ceiling + 1e-10 or result.resolved_model != route.revision:
            self.stopped = True
            raise RuntimeError('charge or resolved revision violated the frozen contract')
        return result


async def _canary_complete(provider, request):
    for attempt in range(2):
        try:
            return await provider.complete(request)
        except ProviderFailure as error:
            if attempt or not error.retryable or error.status_code != 429:
                raise
            await asyncio.sleep(error.retry_after_seconds)

def _gate(root: Path, gate: str, artifact: dict, *, passed: bool, failures=()):
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


async def _canary(root, arm, case_path, provider):
    setup = build_openrouter_setup(GLM_PARASAIL_CANDIDATE.route, case_path=case_path, seed=CANARY_SEED,
                                   prompt=PROMPTS[arm], prompt_id=f'{CAMPAIGN_ID}_{arm}', max_cost_usd=.035, **RETRY_POLICY)
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
        response = await _canary_complete(provider, request)
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
                                   max_cost_usd=.035, **RETRY_POLICY)
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
                            prompt_id=f'{CAMPAIGN_ID}_{arm}', max_cost_usd_per_trajectory=.035, **RETRY_POLICY,
                        )
                    if raw.get('status') != 'completed':
                        provider.stopped = True
                    row = _seal({**raw, 'world_id': world, 'environment_seed': seed, 'arm': arm})
                    _write_once_json(path, row)
                receipt_auditor(root, phase, arm, case_path, row)
                rows.append(row)
                if limit is not None and len(rows) >= limit:
                    return rows
    return rows


def verify_calibration(root, worlds):
    """Re-audit the pre-existing pilot and carry all original spend, not just pilot cost."""
    if (root / 'execution.lock').exists():
        raise ValueError('original execution must be stopped')
    design = _read_sealed(root / 'execution_design.json', 'plan_sha256')
    if design['plan_sha256'] != '9991fc71eed89d1ed9154bdc7f0f3c27b7eeb53273d9e6e5017ee43f95e554e5':
        raise ValueError('unapproved original design')
    if design['design']['implementation_pins'] != original_pins() or design['design']['world_ids'] != worlds:
        raise ValueError('original calibration source or world selection changed')
    records = _history(root)
    for record in records:
        verify_qc_evidence_files(record.evidence_refs, root,
                                expected_artifact_types=(campaign_gate_artifact_type(record.gate_id, record.status),))
    for gate in ('full_trajectory', 'variance_pilot', 'confirmatory_freeze'):
        if _latest(root, gate).status != 'passed':
            raise ValueError('original calibration gate did not pass')
    rows = []
    hashes = {}
    for path in sorted((root / 'pilot/rows').glob('*.json')):
        row = _read_sealed(path)
        original._audit_row(root, 'pilot', row['arm'], root / 'cases' / f"{row['world_id']}_{row['environment_seed']}.json", row)
        rows.append(row)
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    pilot = _read_sealed(root / 'pilot_summary.json')
    if pilot['artifact_sha256'] != '02ab75c59eb99fb45033f68056979a713c8af8d98bba472ee3f931ec40628960':
        raise ValueError('unapproved calibration summary')
    if {k:v for k,v in pilot.items() if k != 'artifact_sha256'} != original.pilot_diagnostics(rows, worlds):
        raise ValueError('calibration summary differs from replayed pilot')
    calls = []
    for path in sorted((root / 'billing').glob('call_*.json')):
        calls.append(json.loads(path.read_text()))
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    settled = sum(c['cost_usd'] for c in calls if c['status'] == 'settled')
    reserved = sum(c['reserved_cost_usd'] for c in calls if c['status'] != 'settled')
    if len(calls) != 267 or not math.isclose(settled, BASELINE_SETTLED, abs_tol=1e-12, rel_tol=0) or not math.isclose(reserved, BASELINE_RESERVED, abs_tol=1e-12, rel_tol=0):
        raise ValueError('original billing differs from approved carry-forward')
    return _seal({'campaign_id': original.CAMPAIGN_ID, 'execution_design_sha256': design['plan_sha256'],
                  'pilot': pilot, 'pilot_rows_replayed': len(rows), 'source_file_sha256': hashes,
                  'settled_cost_usd': settled, 'unresolved_reserved_cost_usd': reserved,
                  'usage': 'calibration only; original partial confirmation is not pooled'})


def validation_is_current(validation):
    legacy = {**validation, 'implementation_pins': original_pins()}
    return original.validation_is_current(legacy) and validation.get('implementation_pins') == implementation_pins()


async def run_campaign(*, root, screen, cases, validation, calibration_root,
                       provider_factory=OpenRouterChatClient, preflight=preflight_candidate,
                       executor=_run_cell, receipt_auditor=_audit_row, calibration_verifier=verify_calibration):
    _validate_operational_run_root(root)
    admitted = build_plan(screen)
    worlds = admitted['world_ids']
    by_id = {economic_world_id(c): c for c in cases}
    cases = [by_id[w] for w in worlds]
    screened = {c['world_id']: c for c in screen['candidates']}
    if any(c['content_sha256'] != screened[economic_world_id(c)]['case_content_sha256'] for c in cases):
        raise ValueError('case differs from admitted candidate')
    calibration = calibration_verifier(calibration_root, worlds)
    design = _seal({
        'campaign_id': CAMPAIGN_ID, 'world_ids': worlds, 'screen_artifact_sha256': screen['artifact_sha256'],
        'implementation_pins': implementation_pins(), 'case_digests': [c['content_sha256'] for c in cases],
        'prompts': PROMPTS, 'route': json.loads(canonical_json_bytes(GLM_PARASAIL_CANDIDATE)),
        'environment_and_inference_seeds': list(CONFIRMATORY_SEEDS), 'planned_rows': 36,
        'execution_order': 'world_then_environment_seed_then_alternating_arm',
        'retry_policy': {**RETRY_POLICY, 'minimum_delay_seconds': 60., 'over_max_retry_after': 'stop'},
        'max_output_tokens': 1800, 'max_trajectory_cost_usd': .035,
        'hard_combined_cost_ceiling_usd': HARD_COST_CEILING_USD,
        'baseline_settled_cost_usd': BASELINE_SETTLED, 'baseline_reserved_cost_usd': BASELINE_RESERVED,
        'support_review_settled_cost_usd': SUPPORT_REVIEW_COST_USD,
        'calibration_artifact_sha256': calibration['artifact_sha256'],
        'inference': 'same guarded regret, 50000-resample paired world bootstrap; no pooling',
        'approval': 'user explicitly approved separate recovery on 2026-09-19',
    }, 'plan_sha256')
    if (root / 'comparison.json').exists():
        if canonical_json_bytes(_read_sealed(root / 'execution_design.json', 'plan_sha256')) != canonical_json_bytes(design):
            raise ValueError('completed recovery design changed')
        return _read_sealed(root / 'comparison.json')
    if (root / 'execution_design.json').exists():
        raise RuntimeError('interrupted recovery requires audit; no automatic redispatch')
    _write_once_json(root / 'execution_design.json', design)
    _write_once_json(root / 'calibration.json', calibration)
    _gate(root, 'design_contract', design, passed=True)
    valid = validation_is_current(validation)
    _gate(root, 'provider_free_validation', validation, passed=valid,
          failures=() if valid else ('full provider-free validation missing or stale',))
    if not valid:
        return {'status': 'blocked', 'reason': 'provider-free validation missing or stale'}
    provider = RecoveryProvider(provider_factory(), root)
    route = preflight(GLM_PARASAIL_CANDIDATE)
    canary_case = root / 'cases/canary.json'
    _write_once_json(canary_case, episode_case(cases[0], CANARY_SEED))
    canaries = {}
    for arm in PROMPTS:
        canaries[arm] = await _canary(root, arm, canary_case, provider)
        if canaries[arm]['status'] != 'admitted':
            provider.stopped = True
    admitted_profile = len(canaries) == 2 and all(c['status'] == 'admitted' for c in canaries.values())
    _gate(root, 'profile_admission', {'route': route, 'canaries': canaries}, passed=admitted_profile,
          failures=() if admitted_profile else ('new unscored prompt canary failed',))
    if not admitted_profile:
        return {'status': 'provider_admission_failed', 'accounted_combined_cost_usd': provider.spent}
    pilot = calibration['pilot']
    _gate(root, 'full_trajectory', {'linked_calibration': calibration['artifact_sha256'], 'replayed_rows': 24}, passed=True)
    _gate(root, 'variance_pilot', {'linked_calibration': calibration['artifact_sha256'], 'diagnostics': pilot}, passed=pilot['passed'])
    power = pilot['bootstrap_power_sensitivity']['monte_carlo_95_lower']
    expected = pilot['total_provider_cost_usd'] / 24 * 36
    if power is None or power < .8 or provider.spent + expected > HARD_COST_CEILING_USD:
        return {'status': 'precision_or_projected_budget_gate_failed'}
    frozen = _seal({'campaign_id': CAMPAIGN_ID, 'execution_design_sha256': design['plan_sha256'],
                    'calibration_artifact_sha256': calibration['artifact_sha256'],
                    'environment_seeds': list(CONFIRMATORY_SEEDS), 'planned_rows': 36,
                    'retry_policy': design['retry_policy'], 'hard_combined_cost_ceiling_usd': HARD_COST_CEILING_USD,
                    'baseline_settled_cost_usd': BASELINE_SETTLED, 'baseline_reserved_cost_usd': BASELINE_RESERVED,
                    'support_review_settled_cost_usd': SUPPORT_REVIEW_COST_USD}, 'plan_sha256')
    _write_once_json(root / 'confirmatory_plan.json', frozen)
    _gate(root, 'confirmatory_freeze', frozen, passed=True)
    rows = await _rows(root, 'confirmatory', cases, CONFIRMATORY_SEEDS, provider, executor, receipt_auditor)
    comparison = continuous_promotion_rule(rows, world_ids=worlds, seeds=CONFIRMATORY_SEEDS)
    _write_once_json(root / 'comparison.json', _seal(comparison))
    complete = len(rows) == 36 and all(r.get('status') == 'completed' and r.get('receipt_replayed') is True for r in rows)
    _gate(root, 'confirmatory_execution', comparison, passed=complete,
          failures=() if complete else ('all 36 cells must complete and replay',))
    return comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('screen', 'cases', 'validation', 'run-root', 'calibration-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    args.run_root.mkdir(parents=True, exist_ok=True)
    lock = args.run_root / 'execution.lock'
    with lock.open('x') as handle:
        import os
        handle.write(str(os.getpid()))
    try:
        result = asyncio.run(run_campaign(root=args.run_root, screen=json.loads(args.screen.read_text()),
                            cases=[json.loads(p.read_text()) for p in sorted(args.cases.glob('*.json'))],
                            validation=json.loads(args.validation.read_text()), calibration_root=args.calibration_root))
        print(json.dumps(result, indent=2))
    finally:
        lock.unlink()
    return 0 if result.get('status') in {'supported', 'not_supported'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
