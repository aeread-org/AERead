"""Rerun the nine shared non-inspected-signing cells with exposed reasoning retention.

Original run roots and pinned family/kernel modules are untouched. Each call saves
its request, raw CLI stdout/stderr, final provider result, and hashes. Claude streams
verbose JSON; Codex requests detailed reasoning summaries. Neither resumes sessions
or changes the decision prompt. Captured text is provider-exposed, not a guarantee
of full internal chain of thought. This result-selected rerun is diagnostic only.
"""
from __future__ import annotations
import argparse
import asyncio
import contextvars
import dataclasses
import hashlib
import json
from pathlib import Path
import uuid

import housing_cli as hc
import codex_exec_client as cx
from aeread.shared_runner.task import execution as ke
from aeread.shared_runner.run.resolver import canonical_json_bytes

CELLS = ((300002,'pooled'),(300002,'true_cost'),(300003,'pooled'),(300003,'true_cost'),
         (300005,'pooled'),(300005,'true_cost'),(300011,'pooled'),(300018,'pooled'),(300018,'true_cost'))
CALL_DIR = contextvars.ContextVar('housing_reasoning_call_dir')
BASE_CODEX_RUN = cx._run


def stream_events(stdout: bytes) -> list[dict]:
    return [json.loads(line) for line in stdout.decode().splitlines() if line.startswith('{')]


def reasoning_text(events: list[dict]) -> list[str]:
    texts=[]
    for event in events:
        item=event.get('item',{})
        if event.get('type')=='item.completed' and item.get('type')=='reasoning' and item.get('text'):
            texts.append(item['text'])
        if event.get('type')=='assistant':
            for block in event.get('message',{}).get('content',[]):
                if block.get('type')=='thinking' and block.get('thinking'):
                    texts.append(block['thinking'])
    return texts


def save_stream(stdout: bytes, stderr: bytes, code: int, mode: str) -> list[dict]:
    folder=CALL_DIR.get()
    (folder/'stdout.jsonl').write_bytes(stdout)
    (folder/'stderr.txt').write_bytes(stderr)
    events=stream_events(stdout)
    texts=reasoning_text(events)
    (folder/'reasoning.txt').write_text('\n\n'.join(texts))
    manifest={'exit_code':code,'capture_mode':mode,'exposed_reasoning_blocks':len(texts),
              'exposed_reasoning_chars':sum(map(len,texts)),
              'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}}
    (folder/'capture.json').write_bytes(canonical_json_bytes(manifest))
    return events


async def claude_stream_runner(arguments: tuple[str,...], stdin: bytes):
    args=list(arguments);args[args.index('--output-format')+1]='stream-json';args.extend(['--verbose','--thinking-display','summarized'])
    code,out,err=await ke._run_subprocess(tuple(args),stdin)
    events=save_stream(out,err,code,'claude_verbose_stream_json_summarized')
    results=[e for e in events if e.get('type')=='result']
    if not results:
        return code or 1,b'',err or b'Claude stream omitted final result'
    payload=results[-1]
    if code and not err:err=str(payload.get('result','Claude error')).encode()
    return code,canonical_json_bytes(payload),err


async def codex_stream_runner(arguments: tuple[str,...], stdin: bytes):
    if 'exec' not in arguments:return await BASE_CODEX_RUN(arguments,stdin)
    args=list(arguments);args[2:2]=['-c','model_reasoning_summary="detailed"']
    code,out,err=await BASE_CODEX_RUN(tuple(args),stdin)
    save_stream(out,err,code,'codex_detailed_summary_jsonl')
    return code,out,err


class RetainedClient:
    def __init__(self,inner,root):self.inner,self.root=inner,root
    async def complete(self,request):
        folder=self.root/uuid.uuid4().hex;folder.mkdir(parents=True)
        (folder/'request.json').write_bytes(canonical_json_bytes({f.name:getattr(request,f.name) for f in dataclasses.fields(request)}))
        token=CALL_DIR.set(folder)
        try:
            result=await self.inner.complete(request)
            (folder/'provider_result.json').write_bytes(canonical_json_bytes({f.name:getattr(result,f.name) for f in dataclasses.fields(result)}))
            capture=json.loads((folder/'capture.json').read_text())
            raw=dict(result.raw_response or {});raw['diagnostic_retention']={'directory':str(folder),**capture}
            return dataclasses.replace(result,raw_response=raw)
        except BaseException as exc:
            (folder/'failure.json').write_bytes(canonical_json_bytes({'type':type(exc).__name__,'message':str(exc)}))
            raise
        finally:CALL_DIR.reset(token)


async def run(subject: str,base: Path,limit: int|None):
    inner=await hc.discover(subject)
    if subject=='claude_opus55':inner._command_runner=claude_stream_runner
    else:cx._run=codex_stream_runner
    runtime=dict(inner.runtime_metadata)
    contract=hc.build_contract(subject,'panel',runtime)
    original=contract['campaign_id'];name=original+'_reasoning_diagnostic_v1'
    hc.pc.IDENTITIES[name]={**hc.pc.IDENTITIES[original],'world_seeds':sorted({s for s,a in CELLS})}
    contract.update(campaign_id=name,world_seeds=sorted({s for s,a in CELLS}),claim_status='result_selected_reasoning_diagnostic')
    selected=CELLS[:limit] if limit else CELLS
    contract['diagnostic']={'selected_cells':[{'world_seed':s,'arm':a} for s,a in selected],
        'original_campaign':original,'selection':'nine cells where neither original subject signed an inspected listing',
        'retention':'request and raw stdout/stderr per call; exposed reasoning blocks and summaries',
        'transport_change':'Claude verbose stream-json and summarized thinking display; Codex detailed reasoning summary',
        'full_internal_chain_of_thought_available':False,'prompt_changed':False,'session_persistence':False}
    spec=hc.SUBJECTS[subject]
    contract['total_cost_ceiling_usd']=spec['cell_ceiling_usd']*len(selected)
    root=base/name
    root.mkdir(parents=True,exist_ok=False)
    (root/'contract.json').write_bytes(canonical_json_bytes(contract))
    (root/'retention_adapter.py').write_bytes(Path(__file__).read_bytes())
    setups={a:hc.cli_setup(contract,a,subject,runtime) for a in contract['arms']}
    focal=cx.LoggedClient(RetainedClient(inner,root/'retained_calls'),root/'cli_calls.jsonl',subject=subject)
    provider=hc.pc.make_seat_router(hc.pc.identity(contract),contract,focal,root/'seat_calls.jsonl')
    live=root/'live';live.mkdir();semaphore=asyncio.Semaphore(2);rows=[]
    for start in range(0,len(selected),2):
        wave=selected[start:start+2]
        if any(r['status']!='completed' for r in rows[-2:]):break
        if any(float(r.get('cost_usd') or 0)>spec['cell_ceiling_usd'] for r in rows):break
        rows.extend(await asyncio.gather(*(hc.run_cell(contract=contract,setup=setups[a],seed=s,arm=a,
            results_root=live,provider=provider,provider_name=spec['provider'],semaphore=semaphore) for s,a in wave)))
    captures=[json.loads(p.read_text()) for p in (root/'retained_calls').glob('*/capture.json')]
    summary={'subject':subject,'planned_cells':len(selected),'attempted_cells':len(rows),
        'completed_cells':sum(r['status']=='completed' for r in rows),
        'calls_captured':len(captures),'calls_with_exposed_reasoning':sum(r['exposed_reasoning_chars']>0 for r in captures),
        'exposed_reasoning_chars':sum(r['exposed_reasoning_chars'] for r in captures),
        'cost_usd':sum(float(r.get('cost_usd') or 0) for r in rows),'cells':rows}
    (root/'summary.json').write_bytes(canonical_json_bytes(summary))
    print(json.dumps({k:v for k,v in summary.items() if k!='cells'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject',choices=['claude_opus55','codex_sol61'],required=True)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    if 'runs' not in args.base.resolve().parts:raise ValueError('diagnostics must live under runs/')
    asyncio.run(run(args.subject,args.base,args.limit))
