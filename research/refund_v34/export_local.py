"""Export whitelisted public projections from locally retained sealed V3.4 runs.

No credentials, provider SDK construction, network or paid execution. This
requires the private local evidence; public users only need reproduce.py.
"""
import argparse
import asyncio
import csv
from io import StringIO
import json
from pathlib import Path
import sys

import reproduce as p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-workspace', type=Path, required=True)
    parser.add_argument('--publication-root', type=Path, default=p.DEFAULT)
    args = parser.parse_args()
    d = p.bootstrap()
    from aeread.shared_runner.task.execution import EvidenceStore
    from aeread.shared_runner.run.publication import (
        atomic_publish, assert_public_payload, sanitized_trajectory_rows,
        sanitized_trajectory_jsonl, seal_publication_manifest, jsonl)
    out = args.publication_root
    p.require(not (out / 'publication_manifest.json').exists(), 'Publication already sealed')
    source = args.source_workspace / 'artifacts'
    bindings = {}

    def load(relative):
        path = source / relative
        bindings['artifacts/' + relative] = p.sha(path)
        return p.read(path)

    def publish(relative, payload):
        assert_public_payload(relative, payload)
        atomic_publish(out / relative, payload)

    def save(relative, value):
        publish(relative, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())

    def table(relative, rows):
        stream = StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        publish(relative, stream.getvalue().encode())

    old = load('refund_v34_pro_timeout_retry1/merged_rows.json')
    pro = load('refund_v34_pro_output_continuation1/merged_rows.json')
    low = load('refund_v34_gpt_low_full1/cell_summaries.json')
    medium = load('refund_v34_gpt_medium_full1/cell_summaries.json')
    details = load('refund_v34_three_model_taxonomy2/DETAILS.json')
    low_details = load('refund_v34_gpt_low_full1/analysis_trace_rows.json')
    medium_details = load('refund_v34_gpt_medium_full1/analysis_trace_rows.json')
    profiles = dict(lite=[r for r in old if r['model'] == 'gemini-2.5-flash-lite'],
        pro_low=pro, gpt_none=[r for r in old if r['model'] == 'gpt-6-sol'], gpt_low=low, gpt_medium=medium)
    classes = {(r['model'], r['case_id']): r for r in details}
    traces = dict(gpt_low={r['case_id']: r for r in low_details}, gpt_medium={r['case_id']: r for r in medium_details})
    cases = {c.case_id: c for c in d.build_catalog(610001)}
    episodes, trajectories, receipt_projections, tasks, results, calls = [], [], [], [], [], []
    runs = {}
    for profile, rows in profiles.items():
        p.require(len(rows) == 220, 'Incomplete source profile')
        for n, row in enumerate(rows, 1):
            detail = traces[profile][row['case_id']] if profile in traces else classes[(row['model'], row['case_id'])]
            path = Path(row['receipt_path'])
            p.require(path.resolve().is_relative_to(args.source_workspace.resolve()), 'Source receipt escaped workspace')
            p.require(p.sha(path) == row['receipt_file_sha256'], 'Original receipt file drift')
            receipt = p.read(path)
            store = EvidenceStore.audit_existing(path.parent)
            try:
                p.require(d.plain(store.verify_seal()) == receipt['evidence'], 'Original evidence seal drift')
                actions = [dict(a, publication_profile_id=profile) for a in sanitized_trajectory_rows(store, receipt)]
            finally:
                store.close()
            p.require(actions and all(isinstance(a['action'], dict) for a in actions), 'Nonparsed selected action cannot use typed replay')
            # The public replay regenerates observations from these typed actions.
            # It does not claim to reproduce provider text or the original seal.
            trajectories.extend(actions)
            def response(seat, obs, transcript):
                action = actions[len(transcript)]
                p.require(action['seat_id'] == seat and action['phase_id'] == obs['phase_id'], 'Export seat/phase drift')
                return action['action']['raw']
            replay = asyncio.run(d.execute(cases[row['case_id']], action_source=response))
            components = {s['leaf']['leaf_id']: dict(value=s['primary']['value'] if s['primary'] else None,
                validity=s['validity']['status']) for s in replay['scores']['scores']}
            p.require(components == row['components'], 'Source native components disagree with public action replay')
            state_digest = d.digest(replay['state'])
            p.require(row.get('native_state_sha256', state_digest) == state_digest, 'Source native-state drift')
            episode = {key: row[key] for key in ('case_id', 'pair_id', 'seat', 'model', 'strict', 'validity', 'components',
                'active_calls', 'reported_cost_usd', 'receipt_sha256', 'receipt_file_sha256')}
            episode.update(native_state_sha256=state_digest,
                native_state_hash_origin='retained_stage_audit' if 'native_state_sha256' in row else 'publication_native_recomputation')
            episode.update(profile_id=profile, primary_class=detail['primary_class'],
                active_failed_dimensions=detail['active_failed_dimensions'],
                source_run_plan_id=receipt['run_plan_id'], source_cell_id=receipt['cell_id'],
                source_episode_attempt_id=receipt['episode_attempt_id'])
            episodes.append(episode)
            receipt_projections.append(dict(profile_id=profile, case_id=row['case_id'],
                source_receipt_sha256=receipt['receipt_sha256'], source_receipt_file_sha256=row['receipt_file_sha256'],
                source_seal=receipt['evidence'], status=receipt['status'], inclusion_status=receipt['inclusion_status'],
                projection_not_original_receipt=True))
            runs[receipt['run_plan_id']] = dict(run_id=receipt['run_plan_id'], profile_id=profile, stage='developmental')
            task = dict(run_id=receipt['run_plan_id'], task_id=receipt['cell_id'],
                episode_attempt_id=receipt['episode_attempt_id'], case_id=row['case_id'], pair_id=row['pair_id'],
                profile_id=profile, active_seat=row['seat'])
            tasks.append(task)
            for name, score in row['components'].items():
                results.append(dict(run_id=task['run_id'], task_id=task['task_id'], episode_attempt_id=task['episode_attempt_id'],
                    profile_id=profile, leaf_id=name, value=score['value'], validity=score['validity']))
            for a in actions:
                for attempt in a['attempts']:
                    for call in attempt.get('provider_calls', []):
                        calls.append(dict(run_id=task['run_id'], task_id=task['task_id'], episode_attempt_id=task['episode_attempt_id'],
                            profile_id=profile, seat=a['seat_id'], call_id=call['provider_call_id'],
                            provider=call.get('provider'), status=call.get('status'), requested_model=call.get('requested_model'),
                            input_tokens=call.get('input_tokens'), output_tokens=call.get('output_tokens'),
                            reported_reasoning_tokens=call.get('reasoning_tokens'), reported_cost_usd=call.get('cost_usd')))
            if n % 50 == 0:
                print(f'Sanitized sealed evidence {profile} {n}/220', flush=True)
    publish('trajectories/episodes.jsonl', jsonl(episodes))
    publish('trajectories/sanitized.jsonl', sanitized_trajectory_jsonl(trajectories))
    publish('receipts/projections.jsonl', jsonl(receipt_projections))
    table('tables/runs.csv', list(runs.values()))
    table('tables/tasks.csv', tasks)
    table('tables/benchmark_results.csv', results)
    p.require(calls, 'Missing provider-call grain')
    table('tables/model_calls.csv', calls)
    # Preserve original old-Pro results separately: not silently substituted by
    # the later new-protocol experiment, and not added to selected denominators.
    history = [{k: r[k] for k in ('case_id', 'pair_id', 'model', 'seat', 'strict', 'validity', 'components',
        'active_calls', 'reported_cost_usd', 'receipt_sha256', 'receipt_file_sha256')} for r in old]
    publish('tables/historical_original660.jsonl', jsonl(history))
    save('reports/summary.json', p.aggregate(episodes))
    panel = sorted({r['case_id'] for r in episodes})
    save('tables/case_panel.json', [dict(case_id=key, pair_id=cases[key].pair_id, seat=cases[key].seat,
        payload_sha256=d.digest(d.payload(cases[key])), world_seed=610001, execution=0, repetition=0) for key in panel])
    profile_rows = [dict(profile_id=key, model=rows[0]['model'], reasoning_effort=(
        'unspecified' if key == 'lite' else key.split('_')[-1]),
        collection_version='3.3' if key == 'lite' else '3.4', scoring_version='3.4.0',
        output_protocol='legacy_bare_json' if key in ('lite', 'gpt_none') else 'refund_json_outer_fence/1',
        cases=220, complete_pairs=110, holdout=False) for key, rows in profiles.items()]
    save('tables/profiles.json', profile_rows)
    stage_records = {}
    for root in ('refund_v34_pro_output_full1', 'refund_v34_pro_output_continuation1',
                 'refund_v34_gpt_low_full1', 'refund_v34_gpt_medium_full1'):
        summary = load(root + '/summary.json')
        proof = load(root + '/FINAL_VERIFICATION.json')
        load(root + '/execution_contract.json')
        stage_records[root] = dict(summary={k: summary[k] for k in (
            'status', 'completed', 'planned', 'calls_started', 'calls_returned', 'known_spend_usd',
            'elapsed_minutes', 'billing_complete', 'unresolved_calls', 'max_usd', 'max_minutes')},
            local_final_audit={k: v for k, v in proof.items() if not isinstance(v, (dict, list))},
            projection_not_original_audit=True)
    save('qc/stages.json', stage_records)
    for relative in ('refund_v34_pro_output_continuation1/MERGE_VERIFICATION.json',
        'refund_v34_three_model_taxonomy2/VERIFICATION.json', 'refund_v34_campaign_taxonomy1/VERIFICATION.json',
        'refund_v34_output_protocol_gate3/VERIFICATION.json', 'refund_v34_output_protocol_gate3/PAIRED_EQUIVALENCE.json',
        'refund_v34_gpt_medium_full1/ANALYSIS.json'):
        load(relative)
    # Bind all executable publication files and the unmodified upstream kernel.
    runtime = {str(path.relative_to(p.ROOT)): p.sha(path) for base in (
        p.ROOT / 'research/refund_v34', p.ROOT / 'src/aeread/shared_runner') for path in base.rglob('*.py')}
    runtime.update({str(path.relative_to(p.ROOT)): p.sha(path)
        for path in (p.ROOT / 'research/refund_v34/configs').glob('*.json')})
    original_source_hashes = {name: p.sha(args.source_workspace / 'src/aeread_families/refund' / name)
        for name in d.sources() if name.endswith('.py')}
    save('qc/runtime_bindings.json', dict(upstream_commit='1e2ae36748b69a928494d4a673c84b3c47105407',
        files=runtime, family_sources=d.sources(), original_family_file_hashes=original_source_hashes,
        kernel_modified=False, native_v34_source_bytes_preserved=True,
        source_projection_exceptions={'v2_5_seat_design_v3.py':
            'Only the legacy paid CLI credential-file default is replaced with a relative path. No case, scorer or transition edits.'}))
    save('qc/source_bindings.json', dict(private_source_artifact_sha256=bindings,
        local_audit_claims_not_independent_public_certification=True,
        original_receipt_bytes_public=False, original_seals_publicly_reverifiable=False,
        low_original_analysis_export_failed_and_preserved=True, historical_unknown_billing_resolved=False,
        new_provider_calls=0, publication_qc=False, formal_family_admission=False,
        label='amended sequential developmental/exploratory'))
    seal_publication_manifest(out, publication_id=out.name, campaign_id='refund_v34_developmental_five_profiles',
        privacy_boundary=dict(included='Parsed typed actions, synthetic development case identities, scores, digest bindings and descriptive taxonomy.',
            excluded='Provider text, prompts, observations, reasoning text, private run stores, credentials and personal filesystem paths.'),
        source_bindings=dict(upstream_commit='1e2ae36748b69a928494d4a673c84b3c47105407',
            original660_sha256=bindings['artifacts/refund_v34_pro_timeout_retry1/merged_rows.json']),
        status='developmental_public_projection_not_formal_qc', selected_episodes=1100,
        profiles=5, cases_per_profile=220, complete_pairs_per_profile=110, new_provider_calls=0)
    print('Export complete; run reproduce.py for independent public native replay', flush=True)


if __name__ == '__main__':
    main()
