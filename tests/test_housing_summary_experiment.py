import asyncio
import housing_summary_experiment as e

def test_schedule_is_balanced_and_reproducible():
    blocks=e.schedule(20261009,3)
    assert blocks==e.schedule(20261009,3)
    assert len(blocks)==6
    for repeat in range(3):
        assert {b['mode'] for b in blocks if b['repeat']==repeat}=={'on','off'}
    for block in blocks:
        assert set(block['cells'])=={(w,a) for w in e.WORLDS for a in ('pooled','true_cost')}

def test_codex_summary_flag_preserves_request(monkeypatch):
    seen=[]
    async def run(args,stdin):
        seen.append((args,stdin));return 0,b'',b''
    monkeypatch.setattr(e.d,'BASE_CODEX_RUN',run)
    monkeypatch.setattr(e.d,'save_stream',lambda *a:[])
    for mode,value in [('on','detailed'),('off','none')]:
        token=e.MODE.set(mode)
        try:asyncio.run(e.codex_runner(('codex','exec','--json'),b'identical prompt'))
        finally:e.MODE.reset(token)
        assert seen[-1]==(('codex','exec','-c',f'model_reasoning_summary="{value}"','--json'),b'identical prompt')

def test_claude_summary_flag_preserves_request(monkeypatch):
    seen=[]
    async def run(args,stdin):
        seen.append((args,stdin));return 0,b'',b''
    monkeypatch.setattr(e.d.ke,'_run_subprocess',run)
    monkeypatch.setattr(e.d,'save_stream',lambda *a:[{'type':'result','result':'ok'}])
    for mode,value in [('on','summarized'),('off','omitted')]:
        token=e.MODE.set(mode)
        try:asyncio.run(e.claude_runner(('claude','--output-format','json'),b'identical prompt'))
        finally:e.MODE.reset(token)
        assert seen[-1][0][-2:]==('--thinking-display',value)
        assert seen[-1][1]==b'identical prompt'
