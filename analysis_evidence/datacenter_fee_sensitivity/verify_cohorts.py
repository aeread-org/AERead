"""Check cohort aggregation, sensitivity tables, and the concrete redline from saved replay output."""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import math
import statistics

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT.parents[1]
rows = json.loads((ROOT / 'rows.json').read_text())
results = json.loads((ROOT / 'results.json').read_text())
edits = json.loads((ROOT / 'edits.json').read_text())
assert results['validation']['cells_replayed'] == 240
assert len(rows) == results['validation']['fee_trajectories_replayed'] == 1440
assert len({(r['cell'], r['fee_usd']) for r in rows}) == 1440
summary = {}
for cohort in ('all', 'deal'):
    for fee in results['validation']['fees_k']:
        for model in ('codex', 'claude'):
            selected = [r for r in rows if r['model'] == model and
                        r['fee_usd'] == fee * 1000 and (cohort == 'all' or r['deal'])]
            worlds = defaultdict(list)
            for row in selected:
                worlds[row['world']].append(row)
            assert len(worlds) == (60 if cohort == 'all' else 45)
            assert all({r['seat'] for r in rr} == {'integrator', 'client'} and len(rr) == 2
                       for rr in worlds.values())
            record = next(s for s in results['summary'] if s['cohort'] == cohort and
                          s['fee_usd'] == fee * 1000 and s['model'] == model)
            for metric in ('joint_loss_usd', 'delay_usd', 'allocation_usd',
                           'no_deal_usd', 'earnings_usd'):
                mean = statistics.fmean(statistics.fmean(r[metric] for r in rr)
                                        for rr in worlds.values())
                assert math.isclose(mean, record[metric], abs_tol=1e-8)
            summary[cohort, fee, model] = record

thresholds = {}
for cohort in ('all', 'deal'):
    thresholds[cohort] = {}
    for metric in ('joint_loss_usd', 'earnings_usd'):
        delta0 = summary[cohort, 0, 'codex'][metric] - summary[cohort, 0, 'claude'][metric]
        delta25 = summary[cohort, 25, 'codex'][metric] - summary[cohort, 25, 'claude'][metric]
        slope = (delta25 - delta0) / 25000
        for fee in results['validation']['fees_k']:
            delta = summary[cohort, fee, 'codex'][metric] - summary[cohort, fee, 'claude'][metric]
            assert math.isclose(delta, delta0 + slope * fee * 1000, abs_tol=1e-7)
        thresholds[cohort][metric] = -delta0 / slope

source = (PACKAGE / 'source/paper_appendix_details.md').read_text()
table_cells = 0
for cohort, table_id, columns in [('deal', 'E.11', 4), ('all', 'E.12', 3)]:
    block = source.split('**Table ' + table_id + '.', 1)[1]
    lines = [line for line in block.split('\n\n', 2)[1].splitlines() if line.startswith('|')][2:]
    assert len(lines) == 6
    for fee, line in zip(results['validation']['fees_k'], lines, strict=True):
        cells = [c.strip() for c in line.strip('|').split('|')]
        a, b = [summary[cohort, fee, m] for m in ('codex', 'claude')]
        expected = [f'{fee:g}', f"{a['joint_loss_usd']/1000:.1f}", f"{b['joint_loss_usd']/1000:.1f}"]
        if columns == 4:
            expected += [f"{(a['earnings_usd']-b['earnings_usd'])/1000:+.1f}"]
        assert cells == expected, (cohort, cells, expected)
        table_cells += len(cells)

for model, paid, useful in [('codex', 150, 23), ('claude', 48, 5)]:
    selected = [e for e in edits if e['model'] == model and e['paid'] and e['deal']
                and e['author'] == e['focal_seat']]
    assert len(selected) == paid
    assert sum(e['delta_usd'] > e['fee_usd'] + 1e-5 for e in selected) == useful
example = [e for e in edits if e['cell'] ==
           'negotiator_drawn_public_v1_integrator__codex_client__cd6b12a1__r0' and e['move'] == 2]
assert len(example) == 1
assert math.isclose(example[0]['delta_usd'], 87500, abs_tol=1e-6)
assert example[0]['fee_usd'] == 25000
sources = json.loads((ROOT / 'source_hashes.json').read_text())
assert len(sources) == 240
for name, digest in sources.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest

checks = {
    'cells': 240, 'fee_replays': len(rows), 'event_stream_hashes_verified': len(sources),
    'tables_verified': ['E.11', 'E.12'], 'table_cells_verified': table_cells,
    'equal_seat_weighting_verified': True, 'worlds_all': 60, 'worlds_deal_feasible': 45,
    'fixed_behavior_thresholds_usd': thresholds, 'concrete_redline': example[0],
    'all_world_fee_shares': {m: summary['all', 25, m]['fee_share'] for m in ('codex', 'claude')},
    'scope_note': 'Opus lower joint loss at zero fees applies only to the 45 deal-feasible worlds; the all-60 ranking reverses.',
    'new_model_calls': 0
}
(ROOT / 'COHORT_CHECKS.json').write_text(json.dumps(checks, indent=2) + '\n')
print(json.dumps(checks, indent=2))
