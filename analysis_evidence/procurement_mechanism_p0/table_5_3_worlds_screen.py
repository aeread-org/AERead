import sys,json,glob,os,time
W='/Users/chenyusu/AERead-worktrees/housing-v15-to-main'
sys.path[:0]=[W+'/src','/Users/chenyusu/AERead/notebooks/procurement_v3/contingent_probe','/Users/chenyusu/AERead/notebooks/procurement_v3/mechanism_study/p0']
import aeread_families; print(aeread_families.__file__,flush=True)
import assistance_gap as a
d=W+'/cases/procurement_allocation_v1/pay_or_test_v3_confirm/'
fs=[f for f in sorted(glob.glob(d+'*.json')) if not f.endswith('pack.json')]
print(len(fs),flush=True)
out=[]
for f in fs:
    c=json.load(open(f))
    t=time.time(); g=a.gaps(c)
    V,B,S=g['optimum'],g['buy_now'],g['best_supplied_value']
    row=dict(file=os.path.basename(f),inv_gain=V-B,S_minus_B=S-B,V_minus_S=V-S,passes=(V-B>=5 and S-B>=5 and V-S<=5),sec=round(time.time()-t,1))
    print(row,flush=True); out.append(row)
    json.dump(out,open(sys.argv[1],'w'),indent=0)
print('PASS',sum(r['passes'] for r in out),'of',len(out))
