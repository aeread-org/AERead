"""Randomized, repeated summary-display experiment on five selected housing worlds."""
from __future__ import annotations
import argparse, asyncio, contextvars, hashlib, json, random
from pathlib import Path
import housing_reasoning_diagnostic as d

MODE=contextvars.ContextVar('summary_mode',default='on')
WORLDS=(300002,300003,300005,300011,300018)

async def claude_runner(arguments,stdin):
    args=list(arguments)
    args[args.index('--output-format')+1]='stream-json'
    args.extend(['--verbose','--thinking-display','summarized' if MODE.get()=='on' else 'omitted'])
    code,out,err=await d.ke._run_subprocess(tuple(args),stdin)
    events=d.save_stream(out,err,code,'claude_summary_'+MODE.get())
    results=[e for e in events if e.get('type')=='result']
    return (code,d.canonical_json_bytes(results[-1]),err) if results else (code or 1,b'',err or b'Missing result')

async def codex_runner(arguments,stdin):
    if 'exec' not in arguments:return await d.BASE_CODEX_RUN(arguments,stdin)
    args=list(arguments);args[2:2]=['-c','model_reasoning_summary="'+('detailed' if MODE.get()=='on' else 'none')+'"']
    code,out,err=await d.BASE_CODEX_RUN(tuple(args),stdin)
    d.save_stream(out,err,code,'codex_summary_'+MODE.get())
    return code,out,err

def schedule(seed,repeats):
    rng=random.Random(seed)
    blocks=[]
    for repeat in range(repeats):
        modes=['on','off'];rng.shuffle(modes)
        for mode in modes:
            cells=[(w,a) for w in WORLDS for a in ('pooled','true_cost')]
            rng.shuffle(cells)
            blocks.append({'repeat':repeat,'mode':mode,'cells':cells})
    return blocks

async def main(args):
    root=args.base/args.subject
    root.mkdir(parents=True,exist_ok=False)
    plan={'subject':args.subject,'randomization_seed':args.seed,'repeats':args.repeats,
          'worlds':WORLDS,'blocks':schedule(args.seed,args.repeats),
          'selection':'five worlds implicated in the previous result-selected diagnostic',
          'estimand':'summary ON minus OFF, averaged within world across repeats and landlord arms',
          'primary':'focal tenant net_expected_response_odds',
          'secondary':['inspection count','signed listing','rent','completed signing'],
          'raw_retention':'both conditions','reasoning_effort':'low',
          'inference_seed':'not controllable; fresh independent CLI sessions',
          'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root/'experiment_plan.json').write_bytes(d.canonical_json_bytes(plan))
    (root/'experiment_driver.py').write_bytes(Path(__file__).read_bytes())
    d.claude_stream_runner=claude_runner;d.codex_stream_runner=codex_runner
    original_build=d.hc.build_contract
    for block in plan['blocks']:
        mode=block['mode'];repeat=block['repeat']
        def build(*a,**kw):
            contract=original_build(*a,**kw)
            contract['diagnostic_campaign_suffix']=f'_summary_{mode}_repeat_{repeat}_experiment_v1'
            contract['diagnostic_selection']='five selected worlds, both landlord arms, randomized repeated summary experiment'
            contract['diagnostic_transport']=f'verbose JSON retention in both arms; summary {mode}'
            contract['summary_experiment']={'mode':mode,'repeat':repeat,'plan_sha256':hashlib.sha256((root/'experiment_plan.json').read_bytes()).hexdigest()}
            return contract
        d.hc.build_contract=build
        d.CELLS=tuple(tuple(c) for c in block['cells'])
        token=MODE.set(mode)
        try:await d.run(args.subject,root/f'repeat_{repeat}__summary_{mode}',None)
        finally:MODE.reset(token)
        summaries=list((root/f'repeat_{repeat}__summary_{mode}').glob('*/summary.json'))
        summary=json.loads(summaries[0].read_text())
        if summary['completed_cells']!=len(d.CELLS):
            raise RuntimeError('Incomplete block; experiment halted without retry')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--subject',choices=['claude_opus55','codex_sol61'],required=True)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--seed',type=int,default=20261009)
    p.add_argument('--repeats',type=int,default=3)
    args=p.parse_args()
    if args.repeats<2:p.error('--repeats must be at least 2 to estimate fresh-play variation')
    if 'runs' not in args.base.resolve().parts:raise ValueError('Outputs must live under runs/')
    asyncio.run(main(args))
