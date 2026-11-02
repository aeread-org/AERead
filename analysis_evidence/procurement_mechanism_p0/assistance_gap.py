"""P0-1: bound the supplied-policy format against the unrestricted optimum, including the first action. No provider calls."""
from pathlib import Path
import sys,json,copy,time
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent.parent/'contingent_probe'))
from policy import Reference,make_state,best_format
from aeread_families.procurement_allocation.pay_or_test_v3_case_matrix import draw_structure,draw_types,build_case

def world(seed,dep,rep=0,slug='mechanism_p0'):
 spec={'slug':f'{slug}_{seed}','pack_id':'mechanism_p0'};st=copy.deepcopy(draw_structure(spec,seed))
 if dep=='independent':st['same_source_probability']=0
 if rep:st['reply_seed']=draw_structure(spec,seed+10**9*rep)['reply_seed']
 tseed=seed if not rep else f'{seed}:rep{rep}'
 return st,build_case(spec,seed,st,draw_types(st,tseed))

def gaps(case):
 ref=Reference(case['payload']);state,_=make_state(ref)
 seen=ref.status_of(state);left=ref.max_actions-state['actions_used'];day=state['elapsed_days']
 B=ref.best_award(seen,day)[0];V=ref.value(seen,left,day)
 U=max(ref.restricted_value(seen,left,day,frozenset({i})) for i in ref.newcomers)
 per={}
 for i in ref.newcomers:
  b=best_format(ref,state,ref.ids[i]);q=ref.request_value(seen,left,day,'request_sample',i)
  per[ref.ids[i]]={'format_value':b['value'],'sample_then_optimal':q,'plan':b['plan']}
 cheap=ref.ids[min(ref.newcomers,key=lambda i:(ref.sample[i][0],ref.price[i],ref.ids[i]))]
 best_sid=max(per,key=lambda s:(per[s]['format_value'],-ord(s[1])))
 S=max(B,per[best_sid]['format_value'])
 return {'buy_now':B,'optimum':V,'one_newcomer':U,'investigation_gain':V-B,
  'best_supplied_option':'buy_now' if B>=per[best_sid]['format_value'] else best_sid,'best_supplied_value':S,
  'format_gap_unrestricted':V-S,'cheapest_candidate':cheap,'cheapest_candidate_format_value':per[cheap]['format_value'],
  'cheapest_candidate_gap':V-max(B,per[cheap]['format_value']),'per_candidate':per}

if __name__=='__main__':
 seeds=[int(x) for x in sys.argv[1:]] or [10600000,10600001,10700120,10700139]
 out=[]
 for s in seeds:
  for dep in ['correlated','independent']:
   t=time.time();g=gaps(world(s,dep)[1]);g.update(seed=s,dependence=dep,seconds=round(time.time()-t,1))
   print(s,dep,{k:(round(v,2) if isinstance(v,float) else v) for k,v in g.items() if k!='per_candidate'},flush=True);out.append(g)
 (HERE/'existing_world_gaps.json').write_text(json.dumps(out,indent=1)+'\n')
