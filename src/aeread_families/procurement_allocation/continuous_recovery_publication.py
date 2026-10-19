"""Read-only verification and sanitized local review export of a stopped run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.quality import verify_qc_evidence_files
from aeread.shared_runner.run.campaign import campaign_gate_artifact_type
from aeread.shared_runner.task.evaluation import audit_family_receipt
from .continuous_campaign import _digest, _seal
from .continuous_recovery import CAMPAIGN_ID, CONFIRMATORY_SEEDS, implementation_pins, RETRY_POLICY, BASELINE_SETTLED, BASELINE_RESERVED, SUPPORT_REVIEW_COST_USD
from .continuous_recovery import _audit_row, _history, GLM_PARASAIL_CANDIDATE, PROMPTS
from .model_campaign import _PUBLISHABLE_ROW_FIELDS, _safe_case_directory, _validate_publication_root, _write_once_json, _write_once_text
from .runner import continuous_promotion_rule, build_openrouter_setup


def _read_sealed(path: Path, key='artifact_sha256'):
    value = json.loads(path.read_text())
    if value.get(key) != _digest({k: v for k, v in value.items() if k != key}):
        raise ValueError(f'artifact digest mismatch: {path.name}')
    return value


def _verified_billing_view(run_root, phase, case_path, row, billing):
    setup = build_openrouter_setup(GLM_PARASAIL_CANDIDATE.route, seed=row['inference_seed'],
                                   case_path=case_path, prompt=PROMPTS[row['arm']],
                                   prompt_id=f"{CAMPAIGN_ID}_{row['arm']}", max_cost_usd=.035, **RETRY_POLICY)
    directory = run_root / phase / row['arm'] / 'executions' / _safe_case_directory(setup.case.case_id, setup.case.content_sha256) / f"seed_{row['inference_seed']}"
    receipts = list(directory.rglob('evaluation_receipt.json'))
    if len(receipts) != 1:
        raise ValueError('trajectory must have one sealed receipt')
    receipt = audit_family_receipt(setup=setup, receipt_path=receipts[0])
    failed = row['status'] == 'operational_failure'
    if failed and (receipt['receipt_sha256'] != row['failure_receipt_sha256'] or receipt['scores']):
        raise ValueError('failed trajectory is not a verified score-free exclusion')
    request_ids = set()
    for path in (receipts[0].parent / 'artifacts' / 'sha256').rglob('*'):
        if path.is_file():
            try:
                value = json.loads(path.read_text())
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict) and isinstance(value.get('request'), dict):
                request_ids.add(value['request'].get('request_sha256'))
    calls = [r for r in billing if r['request_sha256'] in request_ids]
    result = {**row, **({'failure_receipt_verified': True} if failed else {})}
    if any(r['status'] != 'settled' for r in calls):
        result.update(runner_reported_cost_usd=row.get('cost_usd'), cost_usd=None,
                      cost_accounting='unknown_provider_billing',
                      known_cost_usd=sum(r['cost_usd'] for r in calls if r['status'] == 'settled'),
                      unresolved_reserved_cost_usd=sum(r['reserved_cost_usd'] for r in calls if r['status'] != 'settled'))
    return result


def publish_review(*, run_root: Path, publication_root: Path):
    """Export evidence without constructing a provider or issuing any request."""
    _validate_publication_root(publication_root)
    if (run_root / 'execution.lock').exists():
        raise ValueError('cannot publish a running or unaudited interrupted campaign')
    design = _read_sealed(run_root / 'execution_design.json', 'plan_sha256')
    worlds = design['world_ids']
    if design['implementation_pins'] != implementation_pins():
        raise ValueError('measurement source pins differ from the executed design')
    source_hashes = {}
    billing = [json.loads(p.read_text()) for p in sorted((run_root / 'billing').glob('call_*.json'))]
    gates = []
    for record in _history(run_root):
        verify_qc_evidence_files(record.evidence_refs, run_root,
                                 expected_artifact_types=(campaign_gate_artifact_type(record.gate_id, record.status),))
        gates.append({'gate_id': record.gate_id, 'status': record.status,
                      'attempt_index': record.attempt_index, 'failure_reasons': list(record.failure_reasons)})
    reports = {}
    frozen_path = run_root / 'confirmatory_plan.json'
    if frozen_path.exists():
        frozen = _read_sealed(frozen_path, 'plan_sha256')
        if frozen['execution_design_sha256'] != design['plan_sha256']:
            raise ValueError('frozen plan names a different execution design')
        reports['tables/frozen_plan.json'] = frozen
    for phase in ('confirmatory',):
        rows = []
        for path in sorted((run_root / phase / 'rows').glob('*.json')):
            row = _read_sealed(path)
            case_path = run_root / 'cases' / f"{row['world_id']}_{row['environment_seed']}.json"
            _audit_row(run_root, phase, row['arm'], case_path, row)
            source_hashes[str(path.relative_to(run_root))] = hashlib.sha256(path.read_bytes()).hexdigest()
            if row.get('status') in {'completed', 'operational_failure'}:
                row = _verified_billing_view(run_root, phase, case_path, row, billing)
            rows.append(row)
        if not rows:
            continue
        summary = continuous_promotion_rule(rows, world_ids=worlds, seeds=CONFIRMATORY_SEEDS)
        saved_path = run_root / ('comparison.json')
        if saved_path.exists():
            saved = _read_sealed(saved_path)
            if {k:v for k,v in saved.items() if k != 'artifact_sha256'} != summary:
                raise ValueError('saved summary differs from recomputed rows')
        fields = (*_PUBLISHABLE_ROW_FIELDS, 'world_id', 'environment_seed', 'arm',
                  'failure_receipt_verified', 'runner_reported_cost_usd', 'known_cost_usd', 'unresolved_reserved_cost_usd')
        reports[f'reports/{phase}.json'] = _seal({
            'schema_version': 'aeread.procurement_continuous_review/1.0',
            'campaign_id': CAMPAIGN_ID, 'phase': phase, 'summary': summary,
            'rows': [{**{key:row[key] for key in fields if key in row},
                      'source_row_artifact_sha256':row['artifact_sha256']} for row in rows],
            'claim_scope': 'fixed curated synthetic panel; pilot rows are not confirmatory evidence',
        })
    canaries = {p.stem:_read_sealed(p) for p in sorted((run_root / 'canaries').glob('*.json'))}
    canary_fields = ('status', 'request_sha256', 'resolved_model', 'cost_usd', 'input_tokens',
                     'output_tokens', 'scored', 'failure_type', 'artifact_sha256')
    status = {
        'campaign_id': CAMPAIGN_ID, 'gates': gates,
        'provider_call_count':len(billing),
        'settled_cost_usd':sum(r['cost_usd'] for r in billing if r['status'] == 'settled'),
        'unsettled_provider_outcomes':sum(r['status'] != 'settled' for r in billing),
        'unresolved_reserved_cost_usd':sum(r['reserved_cost_usd'] for r in billing if r['status'] != 'settled'),
        'canaries':{name:{k:c[k] for k in canary_fields if k in c} for name,c in canaries.items()},
        'confirmatory_executed': 'reports/confirmatory.json' in reports,
    }
    status.update(
        baseline_settled_cost_usd=BASELINE_SETTLED, baseline_reserved_cost_usd=BASELINE_RESERVED,
        support_review_settled_cost_usd=SUPPORT_REVIEW_COST_USD,
        combined_settled_cost_usd=BASELINE_SETTLED + SUPPORT_REVIEW_COST_USD + status['settled_cost_usd'],
        combined_reserved_cost_usd=BASELINE_RESERVED + status['unresolved_reserved_cost_usd'],
        combined_accounted_cost_usd=BASELINE_SETTLED + BASELINE_RESERVED + SUPPORT_REVIEW_COST_USD + status['settled_cost_usd'] + status['unresolved_reserved_cost_usd'],
        hard_combined_cost_ceiling_usd=.35,
    )
    calibration = _read_sealed(run_root / 'calibration.json')
    if calibration['artifact_sha256'] != design['calibration_artifact_sha256']:
        raise ValueError('calibration link differs from frozen design')
    reports['tables/calibration.json'] = calibration
    reports['tables/execution_contract.json'] = _seal({
        **{k: v for k, v in design.items() if k not in {'prompts', 'plan_sha256'}},
        'source_execution_design_sha256': design['plan_sha256'],
        'prompt_sha256': {arm: hashlib.sha256(prompt.encode()).hexdigest()
                          for arm, prompt in design['prompts'].items()},
    })
    reports['reports/execution_status.json'] = _seal(status)
    artifacts = {}
    for relative, report in reports.items():
        path = publication_root / relative
        _write_once_json(path, report)
        artifacts[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    readme = '# Separately approved recovery: verified execution review\n\n'
    readme += ('Includes confirmatory execution; see the recomputed decision and interval.\n' if status['confirmatory_executed']
               else 'No confirmatory execution is claimed.\n')
    readme += '\nOriginal attempt remains ineligible and is not pooled. Every completed recovery row was replayed again during export. Raw prompts, observations, provider payloads, and account metadata remain in ignored local storage.\n'
    _write_once_text(publication_root / 'README.md', readme)
    artifacts['README.md'] = hashlib.sha256((publication_root / 'README.md').read_bytes()).hexdigest()
    manifest = _seal({
        'schema_version':'aeread.publication_manifest/0.1', 'publication_id':publication_root.name,
        'campaign_id':CAMPAIGN_ID, 'artifacts':artifacts,
        'source_bindings':{'execution_design_sha256':design['plan_sha256'],
                           'confirmatory_plan_sha256':reports.get('tables/frozen_plan.json', {}).get('plan_sha256'),
                           'implementation_pins':implementation_pins(), 'raw_row_file_sha256':source_hashes,
                           'billing_file_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                                   for p in sorted((run_root / 'billing').glob('call_*.json'))},
                           'exporter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        'privacy_boundary':{'included':'public action traces, economics, typed failures, usage, billing totals, digests',
                            'excluded':'full prompts, observations, raw provider payloads, account metadata'},
    }, 'manifest_sha256')
    _write_once_json(publication_root / 'publication_manifest.json', manifest)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--publication-root', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(publish_review(run_root=args.run_root, publication_root=args.publication_root), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
