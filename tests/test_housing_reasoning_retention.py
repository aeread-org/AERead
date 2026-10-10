"""Provider stream retention must preserve actions and decision controls."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'cli_subjects'))
import housing_reasoning_diagnostic as retention


def test_claude_stream_retains_summary_without_changing_decision_controls(tmp_path, monkeypatch):
    async def fake(arguments, stdin):
        assert stdin == b'observation'
        assert arguments[arguments.index('--effort') + 1] == 'low'
        assert '--no-session-persistence' in arguments
        assert arguments[arguments.index('--thinking-display') + 1] == 'summarized'
        events = [
            {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 'exposed summary'}]}},
            {'type': 'result', 'is_error': False, 'structured_output': {'decision': 'pass'}},
        ]
        return 0, '\n'.join(map(json.dumps, events)).encode(), b''

    monkeypatch.setattr(retention.ke, '_run_subprocess', fake)
    token = retention.CALL_DIR.set(tmp_path)
    try:
        code, stdout, _ = asyncio.run(retention.claude_stream_runner(
            ('claude', '--output-format', 'json', '--effort', 'low', '--no-session-persistence'), b'observation'))
    finally:
        retention.CALL_DIR.reset(token)
    assert code == 0
    assert json.loads(stdout)['structured_output'] == {'decision': 'pass'}
    assert (tmp_path / 'reasoning.txt').read_text() == 'exposed summary'
    assert len(retention.stream_events((tmp_path / 'stdout.jsonl').read_bytes())) == 2


def test_codex_retains_complete_stream_and_enables_summary(tmp_path, monkeypatch):
    stdout = b'{"type":"item.completed","item":{"type":"reasoning","text":"summary"}}\n'

    async def fake(arguments, stdin):
        assert 'model_reasoning_summary="detailed"' in arguments
        assert '--ephemeral' in arguments
        assert stdin == b'observation'
        return 0, stdout, b''

    monkeypatch.setattr(retention, 'BASE_CODEX_RUN', fake)
    token = retention.CALL_DIR.set(tmp_path)
    try:
        result = asyncio.run(retention.codex_stream_runner(('codex', 'exec', '--ephemeral'), b'observation'))
    finally:
        retention.CALL_DIR.reset(token)
    assert result[1] == stdout
    assert (tmp_path / 'stdout.jsonl').read_bytes() == stdout
    assert (tmp_path / 'reasoning.txt').read_text() == 'summary'


def test_omitted_thinking_is_not_reconstructed():
    assert retention.reasoning_text([
        {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': '', 'signature': 'opaque'}]}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"decision":"pass"}'}},
    ]) == []
