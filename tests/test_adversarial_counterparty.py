"""Adversarial-counterparty axis: defection knobs + scripted-defector policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402
from aeread.exchange_economy_adversarial import AdversarialCounterpartyPolicy  # noqa: E402


def _pol(rate, seed=0):
    return AdversarialCounterpartyPolicy(
        defection_rate=rate, defection_seed=seed,
        model="google/gemini-2.5-flash", protocol=ex.ProtocolConfig(),
    )


def test_protocol_defection_knobs_load(tmp_path):
    cfg = {
        "name": "adv", "description": "", "num_agents": 8, "num_resources": 8,
        "units_per_home_resource": 10, "seed": 23, "rounds": 6, "controllers": [1],
        "protocol": {"name": "adv", "defection_rate": 0.5, "defection_seed": 7},
    }
    p = tmp_path / "adv.json"
    p.write_text(json.dumps(cfg))
    c = ex.load_experiment_config(p)
    assert c.protocol.defection_rate == 0.5
    assert c.protocol.defection_seed == 7


def test_defector_set_deterministic_fraction():
    p = _pol(0.5, seed=0)
    d = p._defector_set(10)
    assert len(d) == 5
    assert p._defector_set(10) == d                 # stable within an instance
    assert _pol(0.5, seed=0)._defector_set(10) == d  # reproducible across instances
    assert _pol(0.0)._defector_set(10) == set()      # no defectors at rate 0


def test_defectors_decline_without_llm():
    p = _pol(1.0)  # everyone defects -> no super()/LLM/transcript needed
    world = ex.make_exchange_world(num_agents=4, num_resources=4)
    resp = p.response_texts(world, [2, 3, 4], transcript=None, history=[])
    assert set(resp) == {2, 3, 4}
    assert all("decline" in t.lower() for t in resp.values())
    acc = p.private_acceptance_texts(world, [2, 3], transcript=None, mechanism=None, history=[])
    assert all('"approve": false' in t for t in acc.values())
