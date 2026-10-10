"""Analyze the retained ON/OFF experiment, clustering comparisons by world."""
import argparse,json,statistics,hashlib
from pathlib import Path
from aeread_families.housing import price_publication as p

def analyze(base):
    result={}
    for subject in ('claude_opus55','codex_sol61'):
        root=base/subject;plan=json.loads((root/'experiment_plan.json').read_text());rows=[];captures=[];initial_inputs={}
        for block in plan['blocks']:
            folders=list((root/f"repeat_{block['repeat']}__summary_{block['mode']}").glob('housing_*'))
            if not folders:continue
            folder=folders[0];contract=json.loads((folder/'contract.json').read_text())
            requests={json.loads(q.read_text())['provider_call_id']:json.loads(q.read_text()) for q in (folder/'retained_calls').glob('*/request.json')}
            for events in (folder/'live').rglob('events.jsonl'):
                cell_folder=events.parent
                while not cell_folder.name.endswith('_evidence') and cell_folder!=folder:cell_folder=cell_folder.parent
                if cell_folder==folder:continue
                key=cell_folder.name
                for event in map(json.loads,events.read_text().splitlines()):
                    if event.get('visibility')=='seat:tenant_0' and event.get('event_type')=='provider_call_succeeded':
                        req=requests.get(event.get('provider_call_id'))
                        if req:
                            content={k:req[k] for k in ('instructions','input_text','output_schema','model','reasoning_effort')}
                            digest=hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()
                            initial_inputs.setdefault(key,[]).append(digest)
                        break
            for row in p.cell_rows(contract,folder):
                row.update(mode=block['mode'],repeat=block['repeat'])
                if row['status']=='completed':
                    raw=json.loads((folder/'live'/f"world_{row['world_seed']}__{row['arm']}.json").read_text())
                    facts=raw['outcome_facts'];decisions=[d for d in facts['commit_decisions'] if d['tenant_id']==0 and d['decision']=='sign']
                    row['rent']=decisions[0]['rent'] if decisions else None
                    row['listing_id']=decisions[0]['listing_id'] if decisions else None
                    row['quality']=decisions[0]['quality'] if decisions else None
                    row['inspection_count']=facts['tenant_inspection_spend'].get('tenant_0',0)/25
                rows.append(row)
            for path in (folder/'retained_calls').glob('*/capture.json'):
                capture=json.loads(path.read_text());capture['mode']=block['mode'];captures.append(capture)
        expected=len(plan['worlds'])*2*2*plan['repeats'];done=[r for r in rows if r['status']=='completed']
        summary={'expected':expected,'completed':len(done),'failed':sum(r['status'] not in ('completed','not_attempted') for r in rows),'pending':expected-len(done)-sum(r['status'] not in ('completed','not_attempted') for r in rows),'capture':{mode:{'calls':sum(c['mode']==mode for c in captures),'readable':sum(c['mode']==mode and c['exposed_reasoning_chars']>0 for c in captures)} for mode in ('on','off')},'initial_input_hashes_match':all(len(set(v))==1 for v in initial_inputs.values()),'initial_input_groups':{k:len(v) for k,v in initial_inputs.items()},'rows':rows}
        if len(done)==expected:
            metrics={}
            for metric in (p.PRIMARY,'inspection_count','signed','ended_on_inspected_listing'):
                levels={mode:[statistics.mean(float(r[metric]) for r in done if r['mode']==mode and r['world_seed']==world) for world in plan['worlds']] for mode in ('on','off')}
                metrics[metric]={'on':p._interval(levels['on']),'off':p._interval(levels['off']),'on_minus_off':p._interval([a-b for a,b in zip(levels['on'],levels['off'])])}
            summary['metrics']=metrics
            summary['exploratory_by_landlord']={}
            for arm in ('pooled','true_cost'):
                levels={mode:[statistics.mean(r[p.PRIMARY] for r in done if r['mode']==mode and r['world_seed']==world and r['arm']==arm) for world in plan['worlds']] for mode in ('on','off')}
                summary['exploratory_by_landlord'][arm]={'on':p._interval(levels['on']),'off':p._interval(levels['off']),'on_minus_off':p._interval([a-b for a,b in zip(levels['on'],levels['off'])])}
            summary['payoff_range']={mode:[min(r[p.PRIMARY] for r in done if r['mode']==mode),max(r[p.PRIMARY] for r in done if r['mode']==mode)] for mode in ('on','off')}
            summary['within_cell_payoff_sd']={mode:statistics.mean(statistics.stdev(r[p.PRIMARY] for r in done if r['mode']==mode and r['world_seed']==w and r['arm']==arm) for w in plan['worlds'] for arm in ('pooled','true_cost')) for mode in ('on','off')}
        result[subject]=summary
    (base/'analysis.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:{x:y for x,y in v.items() if x!='rows'} for k,v in result.items()},indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);analyze(parser.parse_args().base)
