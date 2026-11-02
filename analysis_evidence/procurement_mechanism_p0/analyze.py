"""Offline audit and analysis of a P0 run (pilot or confirmatory). No provider calls.

python p0/analyze.py pilot            -> tables, contrasts, variance split, confirmatory sizing
python p0/analyze.py confirm          -> tables and the frozen primary tests
"""
from pathlib import Path
import sys,json,math,random,statistics as st
HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path[:0]=[str(STUDY),str(HERE)]
import pandas as pd
import run_pilot as r
from scipy.stats import norm

def audit(run):
 protocol=r.load(run/'protocol.json');results=r.load(run/'results.json')
 assert r.digest({k:v for k,v in protocol.items() if k!='sha256'})==protocol['sha256']==results['protocol_sha256']
 assert not r.load(run/'isolation.json')['violations']
 rows=[];calls=0
 for row in results['rows']:
  cell=row['cell'];path=run/'inputs'/f'{cell}.json';assert r.sha(path.read_bytes())==protocol['input_sha256'][cell]
  item=r.load(path);ref=r.Reference(item['payload']);state,_=r.make_state(ref);aid=r.assistance(item);history=[]
  if row.get('plan'):
   obs=ref.plugin.observe(ref.case,state,'buyer',None);text,schema=r.planning_request(item,obs)
   req=r.load(run/'requests'/f'{cell}_plan.json');assert req['input_text']==json.dumps(text,sort_keys=True);calls+=1
   aid['your_frozen_plan_and_estimates']=row['plan']
  for step in row['steps']:
   obs=ref.plugin.observe(ref.case,state,'buyer',None)
   text={'initial_assistance':aid,'previous_public_steps':history,'current_public_observation':obs,'instruction':'Choose the next legal action to maximize the stated economic objective. Continue until the episode terminates.'}
   req=r.load(run/'requests'/f'{cell}_action_{step["index"]:02d}.json');resp=r.load(run/'responses'/f'{cell}_action_{step["index"]:02d}.json')
   assert req['input_text']==json.dumps(text,sort_keys=True) and json.loads(resp['output_text'])==step['action'];calls+=1
   state,again=r.raw_step(ref,state,step['action'],step['index']);assert again==step
   history.append({'observation':obs,'action':step['action']})
  s=item['reference_summary'];pa=row.get('plan_assessment') or {}
  first=row['steps'][0]['action'] if row['steps'] else {}
  supplied_adv=item['supplied_values']['actual_plan_value']-item['supplied_values']['actual_buy_value']
  rows.append({'cell':cell,'seed':row['seed'],'repeat':row['repeat'],'frame':row['frame'],'arm':row['arm'],'status':row['status'],
   'loss':row.get('cumulative_loss_usd'),'first_loss':row['steps'][0]['loss_usd'] if row['steps'] else None,'actions':len(row['steps']),
   'investigation_gain':s['investigation_gain'],'format_gap':s['format_gap_unrestricted'],'cost':row['cost_usd'],
   'bought_now':first.get('action')=='submit_award' and len(row['steps'])==1,
   'started_candidate':first.get('action')=='request_sample' and first.get('supplier_id')==item['candidate'],
   'plan_status':row.get('plan_status'),'planning_gap':pa.get('planning_gap'),'est_adv':pa.get('estimated_advantage'),'act_adv':pa.get('actual_advantage'),
   'adv_error':pa.get('advantage_error'),'aggregation_residual':pa.get('aggregation_residual'),'supplied_advantage':supplied_adv})
 df=pd.DataFrame(rows)
 df['mismatch']=(df.est_adv>5)&df.bought_now
 return protocol,results,df,calls

def contrasts(df,pairs):
 w=df[df.status.isin(['completed','invalid_action'])].groupby(['seed','arm']).loss.mean().unstack()
 out={}
 for a,b in pairs:
  d=(w[a]-w[b]).dropna();out[f'{a} - {b}']=d
 return w,out

def boot_ci(x,n=20000,seed=0):
 x=list(x);rng=random.Random(seed);m=[st.mean(rng.choices(x,k=len(x))) for _ in range(n)];m.sort()
 return m[int(.025*n)],m[int(.975*n)]

def holm(ps,alpha=.05):
 order=sorted(range(len(ps)),key=lambda i:ps[i]);k=len(ps);adj=[None]*k;run=0
 for rank,i in enumerate(order):run=max(run,min(1,(k-rank)*ps[i]));adj[i]=run
 return adj

def perm_p(d,n=50000,seed=1):
 """Two-sided sign-flip test of mean world-level contrast = 0."""
 d=list(d);rng=random.Random(seed);obs=abs(st.mean(d));hits=0
 for _ in range(n):
  if abs(st.mean([x if rng.random()<.5 else -x for x in d]))>=obs-1e-12:hits+=1
 return (hits+1)/(n+1)

def perm_one(d,shift,side,n=50000,seed=3):
 """One-sided sign-flip test on d+shift: side 'less' tests mean(d)+shift<0, 'greater' tests >0."""
 x=[v+shift for v in d];rng=random.Random(seed);obs=st.mean(x);hits=0
 for _ in range(n):
  m=st.mean([v if rng.random()<.5 else -v for v in x])
  hits+= m<=obs+1e-12 if side=='less' else m>=obs-1e-12
 return (hits+1)/(n+1)

def size(sd,delta=5.0,k=3,power=.8):
 z=norm.ppf(1-.05/(2*k))+norm.ppf(power);return max(2,math.ceil((z*sd/delta)**2))

def sim_power(d,n,delta=5.0,k=3,reps=2000,seed=2):
 """Resample pilot world contrasts, recentred to the target effect, and apply the frozen test at alpha/k."""
 d=list(d);mu=st.mean(d);centred=[x-mu+delta for x in d];rng=random.Random(seed);hit=0
 for _ in range(reps):
  s=rng.choices(centred,k=n);se=st.stdev(s)/math.sqrt(n)
  if se>0 and abs(st.mean(s))/se>norm.ppf(1-.05/(2*k)):hit+=1
 return hit/reps

if __name__=='__main__':
 name=sys.argv[1];run=HERE/name;protocol,results,df,calls=audit(run);out=run/'tables';out.mkdir(exist_ok=True)
 df.to_csv(out/'episodes.csv',index=False)
 pairs=[tuple(p) for p in protocol['primary_contrasts']]
 pairs+=[x for x in [('elicitation','direct'),('supplied_policy','elicitation'),('supplied_policy_values','supplied_policy'),('supplied_policy_values','direct')] if x not in pairs]
 steps=[]
 for row in results['rows']:steps+=[{'cell':row['cell'],'loss':s['loss_usd']} for s in row['steps']]
 worst=pd.DataFrame(steps).groupby('cell').loss.max();df['catastrophic']=df.cell.map(worst).fillna(0)>100
 report={'run':name,'status':results['status'],'episodes':len(df),'verified_calls':calls,'cost_usd':round(results['cost_usd'],4),
  'cost_per_episode':round(df.cost.mean(),4),'status_counts':df.status.value_counts().to_dict()}
 for frame in ['gap_bounded','unscreened']:
  f=df[df.frame==frame]
  if f.empty:continue
  w,cs=contrasts(f,pairs)
  arm=f.groupby('arm').agg(loss=('loss','mean'),bought_now=('bought_now','mean'),mismatch=('mismatch','sum'),n=('loss','size')).round(3)
  arm.to_csv(out/f'{frame}_arms.csv');w.round(3).to_csv(out/f'{frame}_world_arm_loss.csv')
  ent={'worlds':int(f.seed.nunique()),'arm_means':arm.to_dict(orient='index'),'contrasts':{}}
  ps=[]
  cs={k:d for k,d in cs.items() if len(d)>=2}
  for k,d in cs.items():
   lo,hi=boot_ci(d);p=perm_p(d);ps.append(p)
   ent['contrasts'][k]={'mean':round(st.mean(d),3),'sd':round(st.stdev(d),3),'ci95':[round(lo,3),round(hi,3)],'p_signflip':round(p,4),'worlds':len(d)}
  for (k,v),a in zip(ent['contrasts'].items(),holm(ps)):v['p_holm']=round(a,4)
  # Within-world (repeat) vs between-world variance of each contrast.
  g=f[f.status.isin(['completed','invalid_action'])].pivot_table(index=['seed','repeat'],columns='arm',values='loss')
  for a,b in pairs:
   d=(g[a]-g[b]).dropna().unstack('repeat').dropna()
   if d.shape[1]>=2 and len(d)>=2 and f"{a} - {b}" in ent["contrasts"]:
    within=st.mean((d[0]-d[1])**2/2);total=st.variance(d.mean(axis=1))
    ent['contrasts'][f'{a} - {b}'].update(within_var_per_draw=round(within,2),var_of_world_means=round(total,2))
  # Planning diagnostics in assisted arms.
  p=f[f.plan_status=='scored']
  ent['planning']={'E_best_policy':f"{int((p[p.arm=='elicitation'].planning_gap.abs()<1e-6).sum())}/{int((p.arm=='elicitation').sum())}",
   'E_median_planning_gap':round(p[p.arm=='elicitation'].planning_gap.median(),3) if len(p) else None,
   'max_abs_adv_error_by_arm':p.groupby('arm').adv_error.apply(lambda x:round(x.abs().max(),3)).to_dict(),
   'mismatches_by_arm':f.groupby('arm').mismatch.sum().astype(int).to_dict(),
   'catastrophic_commitments_by_arm':f.groupby('arm').catastrophic.sum().astype(int).to_dict()}
  tests=protocol.get('primary_tests')
  if tests and frame in protocol['frames']:
   raw={}
   for h in ['H1','H2']:
    t=tests[h];d=list(w[t['contrast'][0]]-w[t['contrast'][1]].dropna());d=[x for x in d if x==x]
    if t['kind']=='superiority':raw[h]=perm_p(d)
    else:
     m=t['margin_usd'];upper=perm_one(d,-m,'less');lower=perm_one(d,m,'greater');raw[h]=max(upper,lower)
   adj=holm([raw['H1'],raw['H2']])
   ent['primary_tests']={h:{'p_raw':round(raw[h],5),'p_holm':round(a,5),'reject_null':a<.05,'worlds':len(w[tests[h]['contrast']].dropna())} for h,a in zip(['H1','H2'],adj)}
   ent['coverage']={'scheduled_worlds':len(protocol['frames'][frame]),'complete_worlds':int(w.dropna().shape[0])}
  if frame=='gap_bounded' and name=='pilot':
   sds={k:v['sd'] for k,v in ent['contrasts'].items()};worst=max(sds,key=sds.get);n=size(sds[worst])
   ent['sizing']={'rule':'N=((z_{1-.05/6}+z_.8)*SD/5)^2 on the largest world-level contrast SD, then checked by resampling','largest_sd_contrast':worst,'sd':sds[worst],'N_normal':n,
    'sim_power_at_N':{k:sim_power(cs[k],n) for k in cs},'per_contrast_N':{k:size(v) for k,v in sds.items()}}
  report[frame]=ent
 (out/'report.json').write_text(json.dumps(report,indent=1,default=float)+'\n');print(json.dumps(report,indent=1,default=float))
