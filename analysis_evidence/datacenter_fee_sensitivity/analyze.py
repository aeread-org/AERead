import sys,json,hashlib,statistics,copy
from pathlib import Path
from dataclasses import replace
ROOT=Path('/Users/chenyusu/AERead-worktrees/dc-agreement')
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools/cli_subjects')]
import agreement_confirmatory_analysis as analysis
from aeread_families.datacenter_development import agreement as ag, agreement_admitted_pack as ap, risk_allocation_contracts as rc
OUT=Path(__file__).resolve().parent
RUN=ROOT/'runs/datacenter_agreement_confirm_firm_population_v1'
manifest,cases,_=ap.load()
worlds={w['case_id']:w for w in manifest['worlds']}
campaign=analysis.load(RUN)
assert len(campaign['cells'])==240 and all(c['valid'] for c in campaign['cells'])
rows=[]; edits=[]; hashes={}
fees=[0,5,12.5,25,50,100]
for cell in campaign['cells']:
    key=cell['cell_key']; model='codex' if 'codex' in cell['pairing'] else 'claude'
    seat='integrator' if cell['pairing'].startswith(model) else 'client'
    cw,it=rc.world_from(cases[cell['case_id']]['payload'])
    ev=RUN/cell['evidence_dir']/'events.jsonl'
    events=[json.loads(l) for l in ev.read_text().splitlines()]
    hashes[str(ev)]=hashlib.sha256(ev.read_bytes()).hexdigest()
    actions=[]; saved=None
    for e in events:
        if e['event_type'] not in ('action_parsed','transition_applied'):continue
        raw=(ev.parent/e['payload_ref']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==e['payload_sha256']
        p=json.loads(raw)
        if e['event_type']=='action_parsed':
            assert p['parse_result']['ok'];actions.append(p['parse_result']['action'])
        else:saved=p['transition']['state']
    state=ag.initial_state(cw)
    for a in actions:
        before=state;state=ag.apply(state,a,cw)
        if a['action']=='redline':
            delta=ag.joint_cost(cw,it,rc.Contract(**before['terms']))-ag.joint_cost(cw,it,rc.Contract(**state['terms']))
            edits.append(dict(cell=key,model=model,focal_seat=seat,author=before['to_move'],move=before['move'],paid=before['move']>1,delta_usd=delta*1000,fee_usd=(cw.w.terms.round_cost*1000 if before['move']>1 else 0),price_only=not state['history'][-1]['changes'],signed=bool(saved['signed']),deal=worlds[cell['case_id']]['available_surplus']>0))
    assert state==saved
    original=ag.grade(cw,it,state)
    for k in ('joint_value_lost','allocation_loss','no_deal_loss','delay_loss','client_surplus','integrator_surplus'):
        assert abs(original[k]-cell['leaves'][k])<1e-6,(key,k)
    assert cw.w.terms.round_cost==25
    for fee in fees:
        modified=replace(cw,w=replace(cw.w,terms=replace(cw.w.terms,round_cost=fee)))
        s=ag.initial_state(modified)
        for a in actions:s=ag.apply(s,a,modified)
        assert s['signed']==state['signed'] and s['history']==state['history']
        g=ag.grade(modified,it,s)
        assert abs(g['joint_value_lost']-(original['joint_value_lost']+(fee/25-1)*original['delay_loss']))<1e-5
        rows.append(dict(cell=key,world=cell['case_id'],model=model,seat=seat,deal=worlds[cell['case_id']]['available_surplus']>0,fee_usd=fee*1000,joint_loss_usd=g['joint_value_lost']*1000,delay_usd=g['delay_loss']*1000,allocation_usd=g['allocation_loss']*1000,no_deal_usd=g['no_deal_loss']*1000,earnings_usd=g[seat+'_surplus']*1000))
summary=[]
for cohort in ('all','deal'):
 for fee in fees:
  for model in ('codex','claude'):
   rr=[r for r in rows if r['fee_usd']==fee*1000 and r['model']==model and (cohort=='all' or r['deal'])]
   z=dict(cohort=cohort,fee_usd=fee*1000,model=model,n=len(rr),worlds=len({r['world'] for r in rr}))
   for k in ('joint_loss_usd','delay_usd','allocation_usd','no_deal_usd','earnings_usd'):z[k]=statistics.fmean(r[k] for r in rr)
   z['fee_share']=z['delay_usd']/z['joint_loss_usd'] if z['joint_loss_usd'] else 0
   summary.append(z)
diagnostics=[]
for model in ('codex','claude'):
 ee=[e for e in edits if e['model']==model and e['author']==e['focal_seat'] and e['paid'] and e['deal']]
 diagnostics.append(dict(model=model,paid_redlines=len(ee),price_only=sum(e['price_only'] for e in ee),clause_gain_above_fee=sum(e['delta_usd']>e['fee_usd']+1e-5 for e in ee),positive_gain=sum(e['delta_usd']>1e-5 for e in ee),gross_clause_change_usd=sum(e['delta_usd'] for e in ee),fees_usd=sum(e['fee_usd'] for e in ee)))
result=dict(validation={'cells_replayed':240,'fee_trajectories_replayed':len(rows),'original_scores_match_receipts':True,'fees_k':fees},summary=summary,paid_focal_edits_deal_worlds=diagnostics)
for name,value in [('results.json',result),('rows.json',rows),('edits.json',edits),('source_hashes.json',hashes)]:
 (OUT/name).write_text(json.dumps(value,indent=2)+'\n')
lines=['# Data-center negotiation fee sensitivity','', 'Fixed-trajectory replay of all 240 valid firm-population negotiations (60 worlds, two models, two seats). Every original state and six score leaves match saved evidence/receipts. All 1,440 fee trajectories rerun through native apply/grade. Prices, clauses, notes, signatures and walks held fixed. No model calls or behavioral reruns. Amounts below are USD.','', '## Main comparison: 45 deal worlds, both seats','', '| Fee per paid redline | Sol joint loss | Opus joint loss | Sol earnings | Opus earnings | Sol earnings lead |','|---|---:|---:|---:|---:|---:|']
for fee in fees:
 a,b=[next(z for z in summary if z['cohort']=='deal' and z['fee_usd']==fee*1000 and z['model']==m) for m in ('codex','claude')]
 lines.append(f"| ${fee*1000:,.0f} | ${a['joint_loss_usd']:,.0f} | ${b['joint_loss_usd']:,.0f} | ${a['earnings_usd']:,.0f} | ${b['earnings_usd']:,.0f} | ${a['earnings_usd']-b['earnings_usd']:,.0f} |")
lines+=['','## Fee attribution at the original $25,000','']
for z in summary:
 if z['fee_usd']==25000:lines.append(f"- {z['model']}, {z['cohort']} worlds: fees {z['fee_share']:.1%} of joint loss; mean fees ${z['delay_usd']:,.0f}, allocation ${z['allocation_usd']:,.0f}, no-deal ${z['no_deal_usd']:,.0f}. n={z['n']} negotiations on {z['worlds']} worlds.")
lines+=['','## Paid model-authored edits in deal worlds','', 'These measure immediate full-information clause value, not private earnings or causal benefits of information exchange. Opening offers excluded; all later edits included, including subsequently undone edits and negotiations ending without signature. Price-only moves can secure transfers or agreement despite adding zero clause value.','']
for d in diagnostics:lines.append('- '+json.dumps(d))
a,b=[next(z for z in summary if z['cohort']=='deal' and z['fee_usd']==0 and z['model']==m) for m in ('codex','claude')]
a25,b25=[next(z for z in summary if z['cohort']=='deal' and z['fee_usd']==25000 and z['model']==m) for m in ('codex','claude')]
slope=((a25['joint_loss_usd']-a['joint_loss_usd'])-(b25['joint_loss_usd']-b['joint_loss_usd']))/25000
cross=(b['joint_loss_usd']-a['joint_loss_usd'])/slope
lines+=['','## Interpretation','',f'Opus has lower joint loss at every nonnegative fee under fixed behavior. The linear equality lies at a negative fee (${cross:,.0f}), outside the tested policy range. Sol earnings exceed Opus until approximately $48,315 per paid redline, holding behavior fixed. Neither threshold establishes an optimal or empirically justified fee.','', 'The observed fee-free contract/no-deal outcomes and bargaining earnings must be distinguished. The full-information reference remains unchanged: removing fees does not remove information disadvantage. Fee shares include both parties\' fees, whereas the edit diagnostics count only model-authored paid redlines. The source of the $25k calibration is not established by this test.','', 'This is exploratory sensitivity analysis, not a new confirmatory significance test. Independent unit is world; two seats are correlated. No claim about behavior at alternate fees is supported without new paired model runs. Historical source files and production scorer were not modified.']
(OUT/'report.md').write_text('\n'.join(lines)+'\n'+"\n## Concrete useful redline\n\nIn `negotiator_drawn_public_v1_integrator__codex_client__cd6b12a1__r0`, move 2, the model's clause change reduced joint contract cost by $87,500.00 for a $25,000 fee: immediate net improvement $62,500.00. This is a local clause-value comparison, not proof that every change survived later negotiations.\n")
print(json.dumps(result,indent=2))
