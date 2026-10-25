"""Provider-free verifier for the sanitized V3.4 developmental publication."""
from __future__ import annotations

import argparse
import asyncio
import csv
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'evidence/refund/refund_v34_developmental_20261025'
SEATS = dict(policy=82, intake=56, payments=26, customer=56)
EXPECTED = dict(lite=23, pro_low=192, gpt_none=160, gpt_low=194, gpt_medium=202)
SEAT_DIMS = dict(policy=('policy_semantic', 'workflow', 'contract', 'evidence'),
    intake=('intake_planning',), customer=('customer_disclosure', 'customer_confirmation'),
    payments=('payment_binding', 'payment_execution'))


def blocked(*args, **kwargs):
    raise RuntimeError('V3.4 publication verification prohibits network')


def bootstrap():
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    sys.path.insert(0, str(ROOT / 'src'))
    import aeread_families.refund as family
    snapshot = Path(__file__).parent / 'source/aeread_families/refund'
    if str(snapshot) not in family.__path__:
        family.__path__.insert(0, str(snapshot))
    from aeread_families.refund import v34_native
    return v34_native


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def failed(row, dimension):
    c = row['components']['refund_v34_native_' + dimension + '_leaf']
    return c['validity'] == 'valid' and c['value'] is not None and c['value'] != 1


def classify(row, events, observations):
    if row['strict'] == 1 and row['validity'] == 'valid':
        return 'pass'
    for event, obs in zip(events, observations):
        if event['valid']:
            continue
        reason = event.get('reason', 'unspecified')
        if reason == 'unsafe_or_duplicate_mutation':
            return 'payment.duplicate_mutation' if obs.get('delivery_already_applied') else 'payment.unsafe_mutation'
        mapping = {'collection_access_or_budget': 'collection.illegal_request',
            'intake_horizon_exhausted': 'collection.round_limit',
            'unsolicited_disclosure': 'customer.unrequested_disclosure',
            'unowned_record': 'customer.unowned_record', 'stale_consent': 'customer.stale_confirmation',
            'consent_terms_mismatch': 'customer.confirmation_terms_mismatch',
            'payment_binding_error': 'payment.proposal_binding_error', 'capacity_exceeded': 'payment.capacity_exceeded',
            'unauthorized_destination': 'payment.unauthorized_destination', 'allocation_conservation': 'payment.allocation_conservation',
            'unsafe_noop': 'payment.unsafe_noop', 'unconfirmed_payment': 'payment.unconfirmed_execution',
            'policy_assigned_proposal_binding_mismatch': 'policy.proposal_binding_error',
            'invalid_amount': 'contract.invalid_amount', 'unsafe_proposal': 'policy.unsafe_proposal'}
        return mapping.get(reason, 'guard.' + reason)
    for dimension, label in (
        [('policy_semantic', 'policy.semantic_mismatch'), ('evidence', 'evidence.insufficient_or_inefficient'),
         ('workflow', 'workflow.routing_mismatch'), ('contract', 'contract.reason_or_canonical_mismatch')]
        if row['seat'] == 'policy' else
        [('intake_planning', 'collection.suboptimal_plan')] if row['seat'] == 'intake' else
        [('customer_disclosure', 'customer.disclosure_content_integrity'),
         ('customer_confirmation', 'customer.confirmation_preference_mismatch')] if row['seat'] == 'customer' else []):
        if failed(row, dimension):
            return label
    if row['seat'] == 'payments':
        return 'payment.incorrect_execution' if row['validity'] == 'valid' else 'unknown.unobserved'
    return 'unknown.unattributed'


def aggregate(rows):
    result = {}
    for profile in EXPECTED:
        selected = [r for r in rows if r['profile_id'] == profile]
        require(len(selected) == 220, 'Incomplete profile: ' + profile)
        require(len({r['case_id'] for r in selected}) == 220, 'Duplicate case')
        seats = {}
        for seat, expected in SEATS.items():
            rs = [r for r in selected if r['seat'] == seat]
            require(len(rs) == expected, 'Seat coverage drift')
            pairs = Counter(r['pair_id'] for r in rs)
            require(len(pairs) == expected // 2 and set(pairs.values()) == {2}, 'Pair coverage drift')
            leaves = {}
            require(all(len(r['components']) == 11 for r in rs), 'Expected all eleven native leaves')
            for name in sorted(rs[0]['components']):
                values = [r['components'][name] for r in rs]
                valid = [v['value'] for v in values if v['validity'] == 'valid' and v['value'] is not None]
                leaves[name] = dict(valid=len(valid), unmeasured=len(rs) - len(valid),
                    full_score=valid.count(1), nonfull_score=sum(v != 1 for v in valid),
                    validity_counts=dict(sorted(Counter(v['validity'] for v in values).items())))
            seats[seat] = dict(n=len(rs), success=sum(r['validity'] == 'valid' and r['strict'] == 1 for r in rs),
                failure=sum(r['validity'] == 'valid' and r['strict'] == 0 for r in rs),
                unknown=sum(r['validity'] != 'valid' or r['strict'] not in (0, 1) for r in rs),
                complete_pairs=len(pairs), primary_classes=dict(sorted(Counter(r['primary_class'] for r in rs).items())),
                overlapping_failed_dimensions=dict(sorted(Counter(d for r in rs for d in r['active_failed_dimensions']).items())),
                all_native_leaves=leaves)
        result[profile] = dict(success=sum(s['success'] for s in seats.values()),
            failure=sum(s['failure'] for s in seats.values()), unknown=sum(s['unknown'] for s in seats.values()),
            complete_pairs=sum(s['complete_pairs'] for s in seats.values()), seats=seats)
        require(result[profile]['success'] == EXPECTED[profile], 'Published success count drift')
    baseline_keys = {(r['case_id'], r['pair_id'], r['seat']) for r in rows if r['profile_id'] == 'lite'}
    require(all({(r['case_id'], r['pair_id'], r['seat']) for r in rows if r['profile_id'] == p} == baseline_keys
        for p in EXPECTED), 'Profiles use different case panels')
    comparisons = {}
    for baseline, target in [('gpt_none', 'gpt_low'), ('gpt_low', 'gpt_medium'), ('gpt_none', 'gpt_medium')]:
        a = {r['case_id']: r for r in rows if r['profile_id'] == baseline}
        counts = Counter()
        for r in rows:
            if r['profile_id'] != target:
                continue
            b = a[r['case_id']]
            key = 'unknown' if r['validity'] != 'valid' or b['validity'] != 'valid' else {
                (1, 1): 'both_pass', (0, 1): 'new_pass', (1, 0): 'regression', (0, 0): 'both_fail'
            }[(b['strict'], r['strict'])]
            counts[key] += 1
        comparisons[baseline + '_to_' + target] = {k: counts[k] for k in ('both_pass', 'new_pass', 'regression', 'both_fail', 'unknown')}
    return dict(profiles=result, matched_descriptive_comparisons=comparisons, episodes=len(rows),
        label='amended sequential developmental/exploratory', confirmatory_ranking=False,
        taxonomy_precedence='format/schema then active-seat guards then seat-scoped business components',
        taxonomy_is_cognitive_cause=False, overlapping_dimensions_are_not_additive=True)


def verify_manifest(bundle):
    from aeread.shared_runner.run.publication import assert_public_payload, bundle_artifact_digests
    from aeread.shared_runner.run.resolver import canonical_json_bytes
    m = read(bundle / 'publication_manifest.json')
    core = {k: v for k, v in m.items() if k != 'manifest_sha256'}
    require(hashlib.sha256(canonical_json_bytes(core)).hexdigest() == m['manifest_sha256'], 'Manifest seal drift')
    require(bundle_artifact_digests(bundle) == m['artifacts'], 'Artifact changed or unlisted')
    for path in bundle.rglob('*'):
        if path.is_file():
            require(not path.is_symlink(), 'Symlink in bundle')
            assert_public_payload(str(path.relative_to(bundle)), path.read_bytes())
    bindings = read(bundle / 'qc/runtime_bindings.json')
    for relative, digest in bindings['files'].items():
        p = ROOT / relative
        require(p.resolve().is_relative_to(ROOT.resolve()), 'Unsafe runtime path')
        require(sha(p) == digest, 'Runtime source drift: ' + relative)
    return m


def verify_relational_grains(bundle, rows, actions):
    def csv_rows(name):
        with (bundle / 'tables' / name).open(newline='') as stream:
            return list(csv.DictReader(stream))
    def identity(r):
        return (r['run_id'], r['task_id'], r['episode_attempt_id'])
    tasks = csv_rows('tasks.csv')
    require(len(tasks) == 1100 and len({identity(r) for r in tasks}) == 1100, 'Task grain drift')
    expected = {(r['source_run_plan_id'], r['source_cell_id'], r['source_episode_attempt_id']): r for r in rows}
    require({identity(t) for t in tasks} == set(expected), 'Task/episode join drift')
    for task in tasks:
        row = expected[identity(task)]
        require(all(task[k] == row[k] for k in ('profile_id', 'case_id', 'pair_id')), 'Task metadata drift')
    require({r['run_id'] for r in csv_rows('runs.csv')} == {t['run_id'] for t in tasks}, 'Run grain drift')
    results = csv_rows('benchmark_results.csv')
    require(len(results) == 12100, 'Eleven-result grain drift')
    require(len({(*identity(r), r['leaf_id']) for r in results}) == 12100, 'Duplicate result')
    for result in results:
        score = expected[identity(result)]['components'][result['leaf_id']]
        value = None if result['value'] == '' else float(result['value'])
        require(value == score['value'] and result['validity'] == score['validity'], 'Result recomputation drift')
    call_rows = csv_rows('model_calls.csv')
    require(len({(*identity(r), r['call_id']) for r in call_rows}) == len(call_rows), 'Duplicate scoped call')
    action_calls = {(a['run_plan_id'], a['cell_id'], a['episode_attempt_id'], c['provider_call_id']): (a, c) for a in actions
        for attempt in a['attempts'] for c in attempt.get('provider_calls', [])}
    require(set(action_calls) == {(*identity(r), r['call_id']) for r in call_rows}, 'Call/action grain drift')
    active = defaultdict(list)
    for call in call_rows:
        a, c = action_calls[(*identity(call), call['call_id'])]
        require(identity(call) == (a['run_plan_id'], a['cell_id'], a['episode_attempt_id']), 'Call identity drift')
        require(call['status'] == c['status'], 'Call terminal-status drift')
        if call['provider'] == 'arena':
            active[identity(call)].append(call)
    for key, row in expected.items():
        require(len(active[key]) == row['active_calls'], 'Active call coverage drift')
        require(abs(sum(float(c['reported_cost_usd']) for c in active[key]) - row['reported_cost_usd']) < 1e-7,
            'Selected-episode call cost drift')
    history = lines(bundle / 'tables/historical_original660.jsonl')
    require(len(history) == 660 and len({(r['model'], r['case_id']) for r in history}) == 660, 'Historical grain drift')
    require(Counter(r['model'] for r in history) == Counter({
        'gemini-2.5-flash-lite': 220, 'gemini-2.5-pro': 220, 'gpt-6-sol': 220}), 'Historical model coverage drift')


async def replay(bundle, d):
    rows = lines(bundle / 'trajectories/episodes.jsonl')
    actions = lines(bundle / 'trajectories/sanitized.jsonl')
    verify_relational_grains(bundle, rows, actions)
    by_key = defaultdict(list)
    for action in actions:
        by_key[(action['publication_profile_id'], action['case_id'])].append(action)
    require(len(rows) == 1100 and len({(r['profile_id'], r['case_id']) for r in rows}) == 1100, 'Episode coverage drift')
    require(set(by_key) == {(r['profile_id'], r['case_id']) for r in rows}, 'Action/episode key drift')
    cases = {c.case_id: c for c in d.build_catalog(610001)}
    panel = read(bundle / 'tables/case_panel.json')
    require({r['case_id'] for r in panel} == {r['case_id'] for r in rows}, 'Panel coverage drift')
    for item in panel:
        c = cases[item['case_id']]
        require(d.digest(d.payload(c)) == item['payload_sha256'], 'Case payload drift')
        require(d.admission()[c.case_id]['role'] == 'comparison', 'Noncomparison selected')
    for i, row in enumerate(rows, 1):
        tape = by_key[(row['profile_id'], row['case_id'])]
        require([a['step_index'] for a in tape] == list(range(len(tape))), 'Action order drift')
        def source(seat, obs, transcript):
            a = tape[len(transcript)]
            require(a['seat_id'] == seat and a['phase_id'] == obs['phase_id'], 'Seat/phase drift')
            # The native parser adds a typed `raw` object before normalizing
            # policy aliases. It is structured action data, not provider text.
            return a['action']['raw']
        native = await d.execute(cases[row['case_id']], action_source=source)
        components = {s['leaf']['leaf_id']: dict(value=s['primary']['value'] if s['primary'] else None,
            validity=s['validity']['status']) for s in native['scores']['scores']}
        require(len(native['transcript']) == len(tape), 'Unused actions')
        require(components == row['components'], 'Native score drift')
        require(d.digest(native['state']) == row['native_state_sha256'], 'Native state drift')
        require(native['strict'] == row['strict'], 'Strict drift')
        events = [e for e in native['state']['events'] if e['seat'] == row['seat']]
        observations = [t['observation'] for t in native['transcript'] if t['seat'] == row['seat']]
        require(classify(row, events, observations) == row['primary_class'], 'Failure taxonomy drift')
        require([dim for dim in SEAT_DIMS[row['seat']] if failed(row, dim)] == row['active_failed_dimensions'], 'Failed dimensions drift')
        if i % 100 == 0:
            print(f'Offline native replay {i}/1100', flush=True)
    require(aggregate(rows) == read(bundle / 'reports/summary.json'), 'Summary recomputation drift')
    return len(rows), len(actions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication-root', type=Path, default=DEFAULT)
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()
    d = bootstrap()
    verify_manifest(args.publication_root)
    if not args.manifest_only:
        n, actions = asyncio.run(replay(args.publication_root, d))
        print(f'PASS: {n} episodes, {actions} typed actions; native states, 11 leaves, pairs and taxonomy reproduced; provider calls=0')
    else:
        print('PASS: manifest, all file digests, runtime pins and prohibited-text scan')


if __name__ == '__main__':
    main()
