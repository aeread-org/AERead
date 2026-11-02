"""Recompute the mechanism test's reported numbers from episodes.csv alone: arm counts, world-level contrasts,
bootstrap intervals, the equivalence test and the missing-cell fills. Writes CHECKS.json beside the input."""
import csv,json,math,random,statistics as st,sys,pathlib
here=pathlib.Path(__file__).resolve().parent/'confirm'
rows=list(csv.DictReader(open(here/'episodes.csv')))
ARMS=['direct','elicitation','supplied_policy','supplied_policy_values']
done=[r for r in rows if r['status']=='completed']
tr=lambda v:v in('True','true','1')
loss={}
for r in done: loss.setdefault(r['seed'],{})[r['arm']]=float(r['loss'])
gain={r['seed']:float(r['investigation_gain']) for r in rows if r['investigation_gain']}
def boot(d,seed=0,n=20000):
    g=random.Random(seed);m=sorted(st.mean(g.choices(d,k=len(d))) for _ in range(n));return m[int(.025*n)],m[int(.975*n)-1]
def flip(d,shift=0.0,n=20000,seed=1,side=None):
    g=random.Random(seed);x=[v-shift for v in d];o=st.mean(x);c=0
    for _ in range(n):
        m=st.mean(v if g.random()<.5 else -v for v in x)
        c+= (abs(m)>=abs(o)) if side is None else (m<=o if side=='lower' else m>=o)
    return (c+1)/(n+1)
def diff(a,b,tab):
    return [v[a]-v[b] for v in tab.values() if a in v and b in v]
out={'arms':{}}
for a in ARMS:
    e=[r for r in done if r['arm']==a]
    out['arms'][a]={'completed':len(e),'mean_loss':round(st.mean(float(r['loss']) for r in e),2),'median_loss':round(st.median(float(r['loss']) for r in e),2),
      'bought_at_once':sum(tr(r['bought_now']) for r in e),'bought_despite_own_gain':sum(tr(r['mismatch']) for r in e)}
c={}
for name,a,b in [('E_minus_D','elicitation','direct'),('P_minus_E','supplied_policy','elicitation'),('PV_minus_P','supplied_policy_values','supplied_policy'),('PV_minus_D','supplied_policy_values','direct')]:
    d=diff(a,b,loss);lo,hi=boot(d);c[name]={'worlds':len(d),'mean':round(st.mean(d),2),'ci95':[round(lo,1),round(hi,1)],'sd':round(st.stdev(d),1)}
out['contrasts']=c
worlds=sorted({r['seed'] for r in rows}|set(gain))
out['investigation_gain_mean_direct']=round(st.mean(gain[r['seed']] for r in done if r['arm']=='direct'),2)
out['direct_loss_share_of_gain']=round(out['arms']['direct']['mean_loss']/out['investigation_gain_mean_direct'],3)
def tests(tab):
    h1=diff('elicitation','direct',tab);h2=diff('supplied_policy','elicitation',tab)
    p1=flip(h1);p2=max(flip(h2,-25,side='upper' ) if False else flip(h2,-25,side='lower')*0+flip(h2,25,side='lower'),flip(h2,-25,side='upper'))
    ps=sorted([p1,p2]);ad=[min(1,2*ps[0]),min(1,max(2*ps[0],ps[1]))];pass_both=ad[1]<.05
    return {'H1_mean':round(st.mean(h1),2),'H1_p':round(p1,5),'H2_mean':round(st.mean(h2),2),'H2_p_tost':round(p2,5),'both_pass_holm':pass_both}
out['tests_complete_pairs']=tests(loss)
sched={w:set(ARMS) for w in gain}
missing=[(w,a) for w in sched for a in ARMS if a not in loss.get(w,{})]
out['missing_cells']=len(missing)
fills={}
worst={a:max(float(r['loss']) for r in done if r['arm']==a) for a in ARMS}
for name,f in {'buy_now_loss':lambda w,a:gain[w],'arm_worst_observed':lambda w,a:worst[a]}.items():
    t={w:dict(v) for w,v in loss.items()}
    for w,a in missing: t.setdefault(w,{})[a]=f(w,a)
    fills[name]=tests(t)
# adversarial: each missing cell fills against the hypothesis
out['fills']=fills
adv={w:dict(v) for w,v in loss.items()}
for w,a in missing: adv.setdefault(w,{})[a]=1150.0 if a in('elicitation','supplied_policy','supplied_policy_values') else 0.0
out['fills']['adversarial_1150']=tests(adv)
print(json.dumps(out,indent=1))
json.dump(out,open(here.parent/'CHECKS.json','w'),indent=1)
