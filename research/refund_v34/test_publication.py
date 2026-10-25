"""Offline deterministic tests of the publication boundary and native repairs."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import reproduce as p
d = p.bootstrap()
from aeread.shared_runner.run.publication import assert_public_payload, seal_publication_manifest
from aeread_families.refund import v34_json_output_protocol as protocol


@pytest.fixture(scope='module')
def cases():
    return d.build_catalog(610001)


def small_bundle(tmp_path):
    (tmp_path / 'qc').mkdir()
    (tmp_path / 'qc/runtime_bindings.json').write_text(json.dumps(dict(files={})))
    (tmp_path / 'result.json').write_text('{"strict":1}\n')
    seal_publication_manifest(tmp_path, publication_id='test', privacy_boundary=dict(included='typed', excluded='private'))
    return tmp_path


def test_publication_manifest_and_runtime():
    p.verify_manifest(p.DEFAULT)


@pytest.mark.parametrize('mutation', ['changed', 'unlisted', 'removed', 'manifest'])
def test_tampering_fails_closed(tmp_path, mutation):
    root = small_bundle(tmp_path)
    if mutation == 'changed':
        (root / 'result.json').write_text('{"strict":0}')
    elif mutation == 'unlisted':
        (root / 'extra.json').write_text('{}')
    elif mutation == 'removed':
        (root / 'result.json').unlink()
    else:
        m = p.read(root / 'publication_manifest.json')
        m['publication_id'] = 'altered'
        (root / 'publication_manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):
        p.verify_manifest(root)


@pytest.mark.parametrize('token', ['"raw_response"', '"output_text"', '"user_id"', 'authorization:', 'api_key', '/users/'])
def test_private_fields_are_rejected(token):
    with pytest.raises(ValueError):
        assert_public_payload('test', token.encode())


def test_duplicate_and_missing_cases_rejected():
    rows = p.lines(p.DEFAULT / 'trajectories/episodes.jsonl')
    with pytest.raises(ValueError):
        p.aggregate(rows[:-1])
    with pytest.raises(ValueError):
        p.aggregate(rows[:-1] + [rows[0]])


def test_summary_and_matched_counts():
    result = p.aggregate(p.lines(p.DEFAULT / 'trajectories/episodes.jsonl'))
    assert result == p.read(p.DEFAULT / 'reports/summary.json')
    assert result['matched_descriptive_comparisons']['gpt_low_to_gpt_medium'] == dict(
        both_pass=191, new_pass=11, regression=3, both_fail=15, unknown=0)


def test_missing_component_is_not_imputed():
    row = dict(components={'refund_v34_native_payment_binding_leaf': dict(value=None, validity='invalid')})
    assert not p.failed(row, 'payment_binding')


def test_first_illegal_intake_has_nonzero_initial_target(cases):
    case = next(c for c in cases if c.seat == 'intake' and d.admission()[c.case_id]['role'] == 'comparison')
    def source(seat, obs, transcript):
        return dict(decision='request_facts', fact_ids=['__unknown__']) if seat == 'intake' else d.reference(seat, obs)
    result = asyncio.run(d.execute(case, action_source=source))
    assert result['strict'] == 0
    assert result['outcome']['metrics']['intake_planning'] == 0


def test_binding_independent_of_amount(cases):
    case = next(c for c in cases if c.seat == 'payments' and d.admission()[c.case_id]['role'] == 'comparison')
    result = asyncio.run(d.execute(case))
    obs = next(t['observation'] for t in result['transcript'] if t['seat'] == 'payments')
    action = d.reference('payments', obs)
    assert d.binding_credit(action, obs) == 1
    action['amount'] += 100000
    assert d.binding_credit(action, obs) == 1
    action['proposal_id'] = '__wrong__'
    assert d.binding_credit(action, obs) == 0


@pytest.mark.parametrize('text', ['{}', '{bad}', '```json\n{"x":1,"x":2}\n```',
    'Explanation:\n```json\n{}\n```', '```json\n[]\n```'])
def test_protocol_does_not_repair_content(text):
    effective, record = protocol.normalize(text)
    assert effective == text and not record['changed']


def test_protocol_only_removes_complete_outer_fence():
    effective, record = protocol.normalize('```json\n{"decision":"invalid"}\n```')
    assert effective == '{"decision":"invalid"}'
    protocol.verify_transform(effective, record)


def test_no_network():
    import socket
    with pytest.raises(RuntimeError, match='prohibits network'):
        socket.create_connection(('example.com', 443))
