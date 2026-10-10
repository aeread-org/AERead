"""Make readable transcripts from the separately retained housing CLI diagnostic.

Only provider-exposed summaries are copied. Missing summaries are explicit; no
reasoning is inferred or reconstructed. Raw capture files remain the source.
"""
from pathlib import Path
import hashlib
import json
import sys


def export(base: Path):
    index=['# Housing Claude/Codex reasoning diagnostic','',
           'New plays of the nine selected cells, not recovered reasoning from the original runs. '
           'Text below is provider-exposed thinking/reasoning summaries, not full internal chain of thought. '
           'Prompts, models and low reasoning effort are unchanged; output display settings changed.','']
    manifest={}
    for root in sorted(base.glob('housing_*')):
        summary=json.loads((root/'summary.json').read_text())
        index += [f"## {summary['subject']}",'',
                  f"Completed {summary['completed_cells']}/{summary['planned_cells']} cells; "
                  f"{summary['calls_with_exposed_reasoning']}/{summary['calls_captured']} captured calls contain readable summaries. "
                  f"List-price token cost: ${summary['cost_usd']:.4f}.",'']
        requests={}
        for folder in (root/'retained_calls').iterdir():
            req=json.loads((folder/'request.json').read_text());requests[req['provider_call_id']]=folder
        out=root/'transcripts';out.mkdir(exist_ok=True)
        for row in summary['cells']:
            seed,arm=row['world_seed'],row['arm'];text=[f'# {summary["subject"]}: {seed}, {arm}','',f"Status: {row['status']}",'']
            evidence=root/'live'/f'world_{seed}__{arm}_evidence'
            events_path=next(evidence.rglob('events.jsonl'),None)
            if events_path:
                observations={}
                for e in map(json.loads,events_path.open()):
                    if e['visibility']!='seat:tenant_0':continue
                    if e['event_type']=='logical_action_started':
                        payload=json.loads((events_path.parent/e['payload_ref']).read_text())
                        observations[e['logical_action_id']]=payload['request']['observation']
                    if e['event_type']=='provider_call_succeeded':
                        folder=requests.get(e['provider_call_id'])
                        if folder is None:continue
                        observation=observations[e['logical_action_id']]
                        result=json.loads((folder/'provider_result.json').read_text())
                        reasoning=(folder/'reasoning.txt').read_text()
                        text += [f"## Round {observation['round_index']}: {observation['phase']}",'',
                                 f"Capture: [{folder.name}]({folder})",'',
                                 '**Observation shown to the model**','', '```json',json.dumps(observation,indent=2),'```','',
                                 '**Provider-exposed reasoning summary**','',reasoning or '[No readable summary returned for this call.]','',
                                 '**Final action**','', '```json',result['output_text'],'```','']
            path=out/f'world_{seed}__{arm}.md';path.write_text('\n'.join(text))
            index.append(f'- [{seed}, {arm}]({path})')
        index.append('')
        for file in root.rglob('*'):
            if file.is_file() and file.name!='retention_manifest.json':
                manifest[str(file.relative_to(base))]=hashlib.sha256(file.read_bytes()).hexdigest()
    index += ['## Interpretation','',
              'The cells were selected after observing the original results. This is a behavioral diagnostic, '
              'not a new confirmatory comparison. Fresh CLI calls may choose differently. Empty thinking '
              'fields and signatures are retained in raw streams; signatures are not decoded.','']
    (base/'README.md').write_text('\n'.join(index))
    manifest['README.md']=hashlib.sha256((base/'README.md').read_bytes()).hexdigest()
    (base/'retention_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True))
    print(base/'README.md')


if __name__=='__main__':export(Path(sys.argv[1]))
