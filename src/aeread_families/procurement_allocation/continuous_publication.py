"""Read-only verification and sanitized local review export of a stopped run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.quality import verify_qc_evidence_files
from aeread.shared_runner.run.campaign import campaign_gate_artifact_type
from .continuous_campaign import CAMPAIGN_ID, CONFIRMATORY_SEEDS, _digest, _seal, implementation_pins
from .continuous_execution import _audit_row, _history, pilot_diagnostics
from .model_campaign import _PUBLISHABLE_ROW_FIELDS, _validate_publication_root, _write_once_json, _write_once_text
from .runner import continuous_promotion_rule


def _read_sealed(path: Path, key='artifact_sha256'):
    value = json.loads(path.read_text())
    if value.get(key) != _digest({k: v for k, v in value.items() if k != key}):
        raise ValueError(f'artifact digest mismatch: {path.name}')
    return value


def publish_review(*, run_root: Path, publication_root: Path):
    """Export evidence without constructing a provider or issuing any request."""
    _validate_publication_root(publication_root)
    if (run_root / 'execution.lock').exists():
        raise ValueError('cannot publish a running or unaudited interrupted campaign')
    design = _read_sealed(run_root / 'execution_design.json', 'plan_sha256')
    worlds = design['design']['world_ids']
    if design['design']['implementation_pins'] != implementation_pins():
        raise ValueError('measurement source pins differ from the executed design')
    source_hashes = {}
    gates = []
    for record in _history(run_root):
        verify_qc_evidence_files(record.evidence_refs, run_root,
                                 expected_artifact_types=(campaign_gate_artifact_type(record.gate_id, record.status),))
        gates.append({'gate_id': record.gate_id, 'status': record.status,
                      'attempt_index': record.attempt_index, 'failure_reasons': list(record.failure_reasons)})
    reports = {}
    for phase in ('pilot', 'confirmatory'):
        rows = []
        for path in sorted((run_root / phase / 'rows').glob('*.json')):
            row = _read_sealed(path)
            case_path = run_root / 'cases' / f"{row['world_id']}_{row['environment_seed']}.json"
            _audit_row(run_root, phase, row['arm'], case_path, row)
            source_hashes[str(path.relative_to(run_root))] = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(row)
        if not rows:
            continue
        summary = (pilot_diagnostics(rows, worlds) if phase == 'pilot'
                   else continuous_promotion_rule(rows, world_ids=worlds, seeds=CONFIRMATORY_SEEDS))
        saved_path = run_root / ('pilot_summary.json' if phase == 'pilot' else 'comparison.json')
        if saved_path.exists():
            saved = _read_sealed(saved_path)
            if {k:v for k,v in saved.items() if k != 'artifact_sha256'} != summary:
                raise ValueError('saved summary differs from recomputed rows')
        fields = (*_PUBLISHABLE_ROW_FIELDS, 'world_id', 'environment_seed', 'arm')
        reports[f'reports/{phase}.json'] = _seal({
            'schema_version': 'aeread.procurement_continuous_review/1.0',
            'campaign_id': CAMPAIGN_ID, 'phase': phase, 'summary': summary,
            'rows': [{**{key:row[key] for key in fields if key in row},
                      'source_row_artifact_sha256':row['artifact_sha256']} for row in rows],
            'claim_scope': 'fixed curated synthetic panel; pilot rows are not confirmatory evidence',
        })
    billing = [json.loads(p.read_text()) for p in sorted((run_root / 'billing').glob('call_*.json'))]
    canaries = {p.stem:_read_sealed(p) for p in sorted((run_root / 'canaries').glob('*.json'))}
    canary_fields = ('status', 'request_sha256', 'resolved_model', 'cost_usd', 'input_tokens',
                     'output_tokens', 'scored', 'failure_type', 'artifact_sha256')
    status = {
        'campaign_id': CAMPAIGN_ID, 'gates': gates,
        'provider_call_count':len(billing),
        'settled_cost_usd':sum(r['cost_usd'] for r in billing if r['status'] == 'settled'),
        'unsettled_provider_outcomes':sum(r['status'] != 'settled' for r in billing),
        'canaries':{name:{k:c[k] for k in canary_fields if k in c} for name,c in canaries.items()},
        'confirmatory_executed': 'reports/confirmatory.json' in reports,
    }
    reports['reports/execution_status.json'] = _seal(status)
    artifacts = {}
    for relative, report in reports.items():
        path = publication_root / relative
        _write_once_json(path, report)
        artifacts[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    readme = '# Unified regret campaign: verified execution review\n\n'
    readme += ('Includes confirmatory execution; see the recomputed decision and interval.\n' if status['confirmatory_executed']
               else 'Pilot-stage evidence only. No confirmatory result is claimed.\n')
    readme += '\nEvery completed row was replayed again during export. Raw prompts, observations, provider payloads, and account metadata remain in ignored local storage.\n'
    _write_once_text(publication_root / 'README.md', readme)
    artifacts['README.md'] = hashlib.sha256((publication_root / 'README.md').read_bytes()).hexdigest()
    manifest = _seal({
        'schema_version':'aeread.publication_manifest/0.1', 'publication_id':publication_root.name,
        'campaign_id':CAMPAIGN_ID, 'artifacts':artifacts,
        'source_bindings':{'execution_design_sha256':design['plan_sha256'],
                           'implementation_pins':implementation_pins(), 'raw_row_file_sha256':source_hashes,
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
