"""Reproduce Table 5.5 from packaged, sanitized evidence; no model calls.

Run: uv run --with scipy python analysis_evidence/shortfall_panels/derive_panels.py
Housing retains the existing priority classification, checked cell by cell
against reply-conditioned v2. Data center averages both focal roles within
each world before averaging worlds. Refund first averages repeats per case.
Intervals are descriptive t intervals over these independent units; no
cross-model hypothesis or new confirmatory claim is made.
"""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import math
import statistics as st
from scipy.stats import t

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT.parent
INPUTS = {}
CLASSES = ('information_not_acquired', 'contrary_to_information_held',
           'worse_terms', 'commitment_error', 'interaction_cost',
           'procedure_and_format', 'operational')


def read(path, lines=False):
    data = path.read_bytes()
    INPUTS[str(path.relative_to(EVIDENCE))] = hashlib.sha256(data).hexdigest()
    return [json.loads(s) for s in data.splitlines()] if lines else json.loads(data)


def close(a, b, tol=1e-5):
    assert abs(a-b) < tol, (a, b, tol)


def describe(values):
    n = len(values)
    mean = st.fmean(values)
    error = float(t.ppf(.975, n-1)) * st.stdev(values) / math.sqrt(n)
    quartiles = st.quantiles(values, n=4, method='inclusive')
    return dict(n=n, mean=mean, ci95=[mean-error, mean+error],
                min=min(values), q1=quartiles[0], median=st.median(values),
                q3=quartiles[2], max=max(values),
                zero_count=sum(abs(v) < 1e-8 for v in values),
                negative_count=sum(v < -1e-8 for v in values))


def summarize(units):
    keys = list(next(iter(units.values())))
    for row in units.values():
        close(sum(v for k, v in row.items() if k != 'total'), row['total'])
    return {k: describe([row[k] for row in units.values()]) for k in keys}


def main():
    result = dict(analysis_id='paper_shortfall_panels_v9_20261018',
                  status='post-run descriptive accounting',
                  interval_method='95% Student t interval across worlds; Refund across six fixed cases, descriptive only',
                  housing={}, procurement={}, datacenter={}, refund={})
    housing = read(ROOT/'housing_v14_taxonomy.json')
    cells = read(EVIDENCE/'housing_reply_conditioned/tables/cells.jsonl', True)
    index = {(c['campaign_id'], c['world_seed'], c['arm']): c for c in cells}
    assert len(index) == len(cells)
    report = read(EVIDENCE/'housing_reply_conditioned/reports/reply_conditioned.json')
    # Gemini on the completed panel: its 36 refused cells come from the declared fill (HL-O-21).
    completed = housing.get('completed_with_declared_fill', {})
    for name, declared in housing['subjects'].items():
        subject = completed.get(name, declared)
        analysis = 'v2_analysis_with_fill' if name in completed else 'v2_analysis'
        by_world = defaultdict(list)
        matched = 0
        for row in subject['instances']:
            key = (row.get('campaign_id', subject['campaign_id']), row['world_seed'], row['arm'])
            if 'gap' not in row.get('corrected', {}):
                assert key not in index
                continue
            current = index[key]
            close(row['corrected']['gap']-row['published']['gap'],
                  current['primary_v1']-current['primary_v2'])
            matched += 1
            if row['population'] == 'main':
                by_world[row['world_seed']].append(row)
        assert matched == subject['completed_cells']
        units = {}
        for world, rows in by_world.items():
            if len(rows) != 2:
                continue
            assert {r['arm'] for r in rows} == {'pooled', 'true_cost'}
            values = {k: sum(r['corrected']['gap'] for r in rows
                            if r['corrected']['class'] == k)/2 for k in CLASSES}
            values['total'] = st.fmean(r['corrected']['gap'] for r in rows)
            units[str(world)] = values
        summary = summarize(units)
        old = subject['measures']['corrected']['main']
        for k in CLASSES:
            close(summary[k]['mean'], old['per_world'][k])
        current = report[analysis]['models'][subject['campaign_id']]['by_scope']['main']
        close(summary['total']['mean'], -current['minus_reference']['mean'], .0051)
        assert len(units) == current['worlds_with_both_arms'] == old['worlds']
        result['housing'][name] = dict(summary=summary, units=units,
            measure='housing_price_reply_conditioned_v2',
            panel='completed with the declared fill' if name in completed else 'declared bundle',
            missingness=old['operational'], cell_corrections_matched=matched)

    proc = read(ROOT/'procurement_pay_or_test_taxonomy.json')
    headline = read(EVIDENCE/'procurement_reanalysis/reports/headline.json')
    for name, subject in proc['subjects'].items():
        # Match each retained campaign by all 24 world values, not display name.
        units = {r['slug']: dict(r['per_class'], total=r['decision_loss_usd'])
                 for r in subject['worlds_detail']}
        assert len(units) == subject['worlds'] == 24 and not subject['missing_cells']
        matches = []
        for key, panel in headline['panels'].items():
            pv = {k.rsplit('.', 1)[-1]: v for k,v in panel['per_world_decision_loss_usd'].items()}
            if set(pv) == set(units) and all(abs(pv[k]-v['total']) < .00011 for k,v in units.items()):
                matches.append(key)
        assert len(matches) == 1, (name, matches)
        summary = summarize(units)
        for k in CLASSES:
            close(summary[k]['mean'], subject['per_world'][k])
        close(summary['total']['mean'], subject['total_shortfall_per_world'])
        result['procurement'][name] = dict(summary=summary, units=units,
            source_panel=matches[0], missing_cells=0)

    dc_report = read(EVIDENCE/'campaign_refresh/datacenter/analysis/reports/analysis.json')
    dc_pairings = {}
    dc_cells = {}
    for campaign, report_key in [('firm_population','F'),('head_to_head','H')]:
        bundle = EVIDENCE/f'campaign_refresh/datacenter/bundles/datacenter_agreement_confirm_{campaign}_v1'
        manifest = read(bundle/'publication_manifest.json')
        for rel, digest in manifest['artifacts'].items():
            assert hashlib.sha256((bundle/rel).read_bytes()).hexdigest() == digest, rel
        rows = read(bundle/'tables/cells.jsonl', True)
        assert len({r['cell_key'] for r in rows}) == len(rows)
        for pairing in sorted({r['pairing'] for r in rows}):
            group = [r for r in rows if r['pairing'] == pairing]
            assert len(group) == 60 and all(r['valid'] and r['status']=='ok' for r in group)
            units = {}
            for r in group:
                units[r['world']] = dict(
                    inferior_clauses=r['allocation_loss'] if r['available_surplus'] > 1e-6 else 0,
                    harmful_agreement=r['allocation_loss'] if r['available_surplus'] <= 1e-6 else 0,
                    missed_deal=r['no_deal_loss'], redline_fees=r['delay_loss'],
                    total=r['joint_value_lost'])
                close(r['joint_value_lost'], r['allocation_loss']+r['no_deal_loss']+r['delay_loss'])
            assert len(units) == 60
            summary = summarize(units)
            published = dc_report['secondary'][report_key][pairing]
            for leaf in ('allocation_loss','no_deal_loss','delay_loss','joint_value_lost'):
                close(st.fmean(r[leaf] for r in group), published[leaf], .0051)
            dc_pairings[pairing] = dict(summary=summary, units=units,
                client_below_walkaway=sum(r['client_ir_violation'] for r in group),
                integrator_below_walkaway=sum(r['integrator_ir_violation'] for r in group),
                deal_worlds=sum(r['available_surplus'] > 1e-6 for r in group), missing=0)
            dc_cells[pairing] = group
    for name, prefix in [('Opus 5.5','claude'),('Sol 6.1','codex')]:
        pairs = [f'{prefix}_integrator__negotiator_drawn_public_v1_client',
                 f'negotiator_drawn_public_v1_integrator__{prefix}_client']
        left, right = [dc_pairings[p]['units'] for p in pairs]
        assert set(left) == set(right)
        units = {w:{k:(left[w][k]+right[w][k])/2 for k in left[w]} for w in left}
        result['datacenter'][name] = dict(summary=summarize(units), units=units,
            focal_roles='equal mean of integrator and client in each world',
            counterpart='firm population', negotiations=120, worlds=60,
            client_below_walkaway=dc_pairings[pairs[1]]['client_below_walkaway'],
            integrator_below_walkaway=dc_pairings[pairs[0]]['integrator_below_walkaway'])
    result['datacenter_pairings'] = dc_pairings

    refund = read(ROOT/'refund_v21_taxonomy.json')
    for path in sorted((ROOT/'refund_sources').glob('*.json')):
        source = read(path)
        matches = [(n,s) for n,s in refund['subjects'].items() if s['bundle']==source['left']]
        assert len(matches) == 1
        name, subject = matches[0]
        by_case = defaultdict(list)
        seen = set()
        for r in source['cell_parts']:
            if r['side'] != 'left':
                continue
            key = (r['unit'], r['world_seed'], r['replicate_index'])
            assert key not in seen
            seen.add(key)
            values = {k:0. for k in CLASSES}
            for part, value in r['parts'].items():
                values[refund['mapping'][part]] -= value
            values['total'] = sum(values.values())
            by_case[r['unit']].append(values)
        assert len(by_case)==6 and len(seen)==120 and subject['units']['operational']==0
        units = {case:{k:st.fmean(r[k] for r in rs) for k in rs[0]} for case,rs in by_case.items()}
        summary = summarize(units)
        for k in CLASSES:
            close(summary[k]['mean'], subject['per_world'][k])
        close(summary['total']['mean'], subject['total_shortfall_per_world'])
        result['refund'][name] = dict(summary=summary, units=units,
            fixed_cases=6, cells=120, missing_cells=0,
            per_case_cell_totals={k:[r['total'] for r in rs] for k,rs in by_case.items()})
    result['inputs_sha256'] = INPUTS
    result['checks'] = dict(all_component_sums=True, all_primary_source_totals_reproduced=True,
        all_housing_cell_corrections_matched=True, dc_publication_artifact_hashes=True,
        dc_all_worlds_denominator_verified=True, procurement_all_worlds_matched=True)
    (ROOT/'panels.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    for case in ('housing','procurement','datacenter','refund'):
        for name, value in result[case].items():
            print(case, name, {k:round(v['mean'],4) for k,v in value['summary'].items()})


if __name__ == '__main__':
    main()
