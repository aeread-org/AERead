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
    result = dict(analysis_id='paper_shortfall_panels_v11_20261020',
                  status='post-run descriptive accounting',
                  interval_method='95% Student t interval across worlds; Refund across six fixed cases, descriptive only',
                  housing={}, housing_v14={}, procurement={}, datacenter={}, datacenter_v1={}, refund={}, refund_v21={})
    # Housing v15 (Table 5.2, Figure 5.2a): the 260 main worlds, measure v2 primary, shortfall to inspect_lowball.
    # Each cell's class and gap come from housing_v15.py (5522d543; Sol and Opus, addendum B, from 2443c035); a world is the mean of its two landlord arms.
    v15 = read(ROOT/'housing_v15_taxonomy.json')
    v15_report = read(EVIDENCE/'housing_v15/v15_analysis.json')['secondary']['means_main']
    glm_report = read(EVIDENCE/'housing_v15/glm_addendum_analysis.json')['R3']
    cli_report = read(EVIDENCE/'housing_v15/cli_addendum_analysis.json')['subjects']
    published = {'Gemini 3.8 Flash': v15_report['inspect_lowball'] - v15_report['gemini'],
                 'GPT-6 Luna': v15_report['inspect_lowball'] - v15_report['luna'],
                 'GLM 5.3 Flash (addendum A)': -glm_report['mean'],
                 'Sol 6.1 (Codex, addendum B)': -cli_report['sol']['R']['mean'],
                 'Opus 5.5 (Claude Code, addendum B)': -cli_report['opus']['R']['mean']}
    for name, subject in v15['subjects'].items():
        assert subject['completed_cells'] == subject['planned_cells'] == 520 and not subject['missing_cells']['total']
        by_world = defaultdict(list)
        for row in subject['instances']:
            if row['population'] == 'main':
                by_world[row['world_seed']].append(row)
        units = {}
        for world, rows in by_world.items():
            assert len(rows) == 2 and len({r['arm'] for r in rows}) == 2
            values = {k: sum(r['corrected']['gap'] for r in rows if r['corrected']['class'] == k)/2 for k in CLASSES}
            values['total'] = st.fmean(r['corrected']['gap'] for r in rows)
            units[str(world)] = values
        assert len(units) == 260
        detail = {str(w['world_seed']): w for w in subject['worlds_detail']}
        for world, row in units.items():
            close(row['total'], detail[world]['total'], 1e-3)
        summary = summarize(units)
        for k in CLASSES:
            close(summary[k]['mean'], subject['measures']['corrected']['main']['per_world'][k])
        close(summary['total']['mean'], published[name], .0051)
        result['housing'][name] = dict(summary=summary, units=units, measure='housing_price_reply_conditioned_v2 (v15 primary)',
            reference='inspect_lowball', campaign_id=subject['campaign_id'], worlds=260, cells=520, missing_cells=0,
            declared_v15_pair=subject['declared_v15_pair'],
            by_stratum={s: st.fmean(w['total'] for w in subject['worlds_detail'] if w['stratum'] == s)
                        for s in sorted({w['stratum'] for w in subject['worlds_detail']})})

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
        result['housing_v14'][name] = dict(summary=summary, units=units,
            measure='housing_price_reply_conditioned_v2',
            panel='completed with the declared fill' if name in completed else 'declared bundle',
            missingness=old['operational'], cell_corrections_matched=matched)

    # Procurement: the 20 declared worlds of the harder pack (Section 5.1), each world the mean of its two plays.
    proc = read(ROOT/'procurement_pay_or_test_v3_taxonomy.json')
    readouts = {'Sol 6.1 (Codex)': 'readout_sol61.json', 'Opus 5.5 (Claude Code)': 'readout_opus55.json',
                'Gemini 3.8 Flash': 'readout_gemini38_flash.json', 'GPT-6 Luna': 'readout_gpt6_luna.json'}
    for name, subject in proc['subjects'].items():
        units = {r['slug']: dict(r['per_class'], total=r['decision_loss_usd']) for r in subject['worlds_detail']}
        assert len(units) == subject['worlds'] == 20 and not subject['missing_cells']
        readout = read(EVIDENCE/'procurement_v3'/readouts[name])
        readout = readout[0] if isinstance(readout, list) else readout
        plays = defaultdict(list)
        for play in readout['plays_detail']:
            plays[play['slug']].append(play['decision_loss_usd'])
        assert set(plays) == set(units), name
        for slug, row in units.items():  # every world's total matches the replayed read-out
            close(st.fmean(plays[slug]), row['total'], tol=1e-3)
        summary = summarize(units)
        for k in CLASSES:
            close(summary[k]['mean'], subject['per_world'][k])
        close(summary['total']['mean'], subject['total_shortfall_per_world'])
        result['procurement'][name] = dict(summary=summary, units=units,
            source_panel=subject['campaign_id'], missing_cells=0)

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
        result['datacenter_v1'][name] = dict(summary=summarize(units), units=units,
            focal_roles='equal mean of integrator and client in each world',
            counterpart='firm population', negotiations=120, worlds=60,
            client_below_walkaway=dc_pairings[pairs[1]]['client_below_walkaway'],
            integrator_below_walkaway=dc_pairings[pairs[0]]['integrator_below_walkaway'])
    result['datacenter_v1_pairings'] = dc_pairings

    # Data center v2 (Table 5.4, Figure 5.2c): 80 admitted worlds, 72 with a deal. The integrator arm against the firm
    # client has two plays a world, averaged within the world before the roles are; the client arm has one.
    v2 = EVIDENCE/'campaign_refresh/datacenter_v2'
    v2_report = read(v2/'analysis/reports/analysis.json')
    v2_pairings = {}
    for campaign, report_key, plays in [('integrator_firm','IF',2), ('client_firm','CF',1), ('head_to_head','HH',1)]:
        bundle = v2/f'bundles/datacenter_agreement_v2_{campaign}'
        manifest = read(bundle/'publication_manifest.json')
        for rel in ('README.md', 'reports/summary.json', 'tables/cells.jsonl'):
            assert hashlib.sha256((bundle/rel).read_bytes()).hexdigest() == manifest['artifacts'][rel], rel
        rows = read(bundle/'tables/cells.jsonl', True)
        assert len({r['cell_key'] for r in rows}) == len(rows)
        for pairing in sorted({r['pairing'] for r in rows}):
            group = [r for r in rows if r['pairing'] == pairing]
            assert len(group) == 80*plays and all(r['valid'] and r['status']=='ok' for r in group)
            by_world = defaultdict(list)
            for r in group:
                close(r['joint_value_lost'], r['allocation_loss']+r['no_deal_loss']+r['delay_loss'])
                by_world[r['world']].append(dict(
                    inferior_clauses=r['allocation_loss'] if r['available_surplus'] > 1e-6 else 0,
                    harmful_agreement=r['allocation_loss'] if r['available_surplus'] <= 1e-6 else 0,
                    missed_deal=r['no_deal_loss'], redline_fees=r['delay_loss'],
                    total=r['joint_value_lost']))
            assert len(by_world) == 80 and all(len(v) == plays for v in by_world.values())
            units = {w: {k: st.fmean(p[k] for p in ps) for k in ps[0]} for w, ps in by_world.items()}
            published = v2_report['secondary'][report_key][pairing]
            for leaf in ('allocation_loss','no_deal_loss','delay_loss','joint_value_lost'):
                close(st.fmean(r[leaf] for r in group), published[leaf], .0051)
            v2_pairings[pairing] = dict(summary=summarize(units), units=units, plays_per_world=plays,
                client_below_walkaway=sum(r['client_ir_violation'] for r in group),
                integrator_below_walkaway=sum(r['integrator_ir_violation'] for r in group),
                deal_worlds=len({r['world'] for r in group if r['available_surplus'] > 1e-6}), missing=0)
    for name, prefix in [('Opus 5.5','claude'),('Sol 6.1','codex')]:
        pairs = [f'{prefix}_integrator__negotiator_drawn_public_v1_client',
                 f'negotiator_drawn_public_v1_integrator__{prefix}_client']
        left, right = [v2_pairings[p]['units'] for p in pairs]
        assert set(left) == set(right)
        units = {w:{k:(left[w][k]+right[w][k])/2 for k in left[w]} for w in left}
        result['datacenter'][name] = dict(summary=summarize(units), units=units,
            focal_roles='equal mean of integrator and client in each world (the integrator first averaged over its two plays)',
            counterpart='firm population', negotiations=240, worlds=80, campaign='v2',
            client_below_walkaway=v2_pairings[pairs[1]]['client_below_walkaway'],
            integrator_below_walkaway=v2_pairings[pairs[0]]['integrator_below_walkaway'])
    result['datacenter_pairings'] = v2_pairings

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
        result['refund_v21'][name] = dict(summary=summary, units=units,
            fixed_cases=6, cells=120, missing_cells=0,
            per_case_cell_totals={k:[r['total'] for r in rs] for k,rs in by_case.items()})
    # Refund V2.5 (Figure 5.2d): the calibration's policy seat, 72 episodes per model, each failed episode counted once
    # under its first applicable class. The panel record's counts must equal Yuchen Fang's data record (refund_v25.json,
    # which binds the digests of his measurements, analysis and audit), and each total 100 minus the strict compliance.
    v25 = read(EVIDENCE/'refund_v25/policy_seat_panel.json')
    record = read(EVIDENCE/'refund_v25/refund_v25.json')
    keys = {'Gemini 2.5 Flash Lite': 'gemini-2.5-flash-lite', 'Gemini 2.5 Pro': 'gemini-2.5-pro', 'GPT-6-sol': 'gpt-6-sol'}
    rename = {'information_not_acquired': 'required_facts_skipped', 'contrary_to_information_held': 'resolution_mismatch',
              'procedure_and_format': 'procedure_or_format'}
    for name, key in keys.items():
        counts = record['policy_exclusive_counts'][key]
        assert v25['models'][name]['strict_pass'] == counts.get('pass', 0) == record['seats']['policy'][key]['strict_passes']
        for ours, theirs in rename.items():
            assert v25['models'][name]['classes'][ours] == counts.get(theirs, 0), (name, ours)
        close(100*record['seats']['policy'][key]['metrics']['end_to_end']['score_among_observed'],
              v25['weighted_strict_compliance_policy'][name], .051)
    for name, model in v25['models'].items():
        n = v25['episodes_per_model']
        counts = model['classes']
        assert sum(counts.values()) + model['strict_pass'] == n and counts['contract_only'] == 0
        values = {k: 100*counts.get(k, 0)/n for k in CLASSES}
        values['total'] = sum(values.values())
        close(values['total'], 100 - v25['weighted_strict_compliance_policy'][name], .051)
        result['refund'][name] = dict(summary={k: dict(n=n, mean=v) for k, v in values.items()},
            episodes=n, templates=v25['templates'], accounting='first applicable class',
            intervals='none for this panel: see Appendix E.4')
    result['inputs_sha256'] = INPUTS
    result['checks'] = dict(all_component_sums=True, all_primary_source_totals_reproduced=True,
        all_housing_cell_corrections_matched=True, housing_v15_published_totals_reproduced=True, dc_publication_artifact_hashes=True, dc_v2_table_hashes_and_published_leaves=True,
        dc_all_worlds_denominator_verified=True, procurement_all_worlds_matched=True)
    (ROOT/'panels.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    for case in ('housing','housing_v14','procurement','datacenter','datacenter_v1','refund','refund_v21'):
        for name, value in result[case].items():
            print(case, name, {k:round(v['mean'],4) for k,v in value['summary'].items()})


if __name__ == '__main__':
    main()
