"""Published-kernel port: immutable case semantics and independent replay."""
import asyncio
import hashlib
import json

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread_families.refund import v2_5_release as release


FROZEN_CASE_HASHES = {
    301: ('c511f4fb93a2d08a575293fb69349ccde5300336cd8cf547c2bb28a58fdebc65',
          'db10fff09ee3b48d16f8463c599d79e5e9836117e7da5575a1e8a69a4216dc89'),
    302: ('577bbfab28eedfacea2e0ac14df593632c66df2ef4ab718757a2c87bc609b9e2',
          'e78720f11a958df4a52cd1939066e1635f9ce2a1562d22f5389f4b296d103d08'),
    303: ('dcde2d3a5b64a9f175b07cec9ed2d94bc650484a35ad2afb68d4376702d97ebd',
          '730e568a58a73daf5dfe957b21b3d3ca9bf601508b90081209e81edaf3f9a251'),
}


@pytest.mark.parametrize('seed', (301,302,303))
def test_port_preserves_frozen_case_contracts(seed):
    panels=release.v71.build_panels(seed,include_holdout=True)
    for seat,expected in zip(('intake','customer'),FROZEN_CASE_HASHES[seed]):
        assert len(panels[seat])==40
        assert hashlib.sha256(canonical_json_bytes(panels[seat])).hexdigest()==expected


def test_packaged_design_is_hash_bound():
    assert release.v71.parent.PROPOSAL.is_file()
    assert hashlib.sha256(release.v71.parent.PROPOSAL.read_bytes()).hexdigest()==release.v71.parent.PROPOSAL_SHA


def test_v71_public_receipts_reconstruct_and_audit(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail('Provider-free V7.1 initialized paid client or credentials')
    monkeypatch.setattr(release.core.legacy,'ArenaChatClient',forbidden)
    monkeypatch.setattr(release.core.legacy,'_load_env_file',forbidden)
    out=tmp_path/'v71'
    result=asyncio.run(release.conformance(out,panels=('v71_customer',),seats=('customer',),seed=301))
    assert result['completed']==result['planned']==32
    assert result['paid_calls']==result['operational_exclusions']==0
    monkeypatch.setenv('AEREAD_REFUND_V25_RUN_ROOT',str(out))
    for path in out.rglob('evaluation_receipt.json'):
        receipt=json.loads(path.read_bytes())
        setup=release.replay_setup(receipt)
        assert audit_family_receipt(setup=setup,receipt_path=path)['receipt_sha256']==receipt['receipt_sha256']
