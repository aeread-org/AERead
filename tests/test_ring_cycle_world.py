"""Required-cycle-length substrate: make_ring_cycle_world.

Agents are partitioned into disjoint directed cycles of length k (agent owns good i,
wants only the next good in its cycle). Property under test, verified with the existing
provider-free oracles:
  - k=2  -> bilateral IR surplus exists (pairwise swaps suffice)
  - k>=3 -> NO bilateral IR surplus, but a k-party fractional settlement captures it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402


def test_ring_cycle_k2_has_bilateral_surplus():
    w = ex.make_ring_cycle_world(num_agents=12, cycle_length=2)
    sol = ex.solve_bilateral_ir_oracle(w, participants=list(range(1, 13)))
    assert sol.welfare_gain > 1e-6


def test_ring_cycle_k3_no_bilateral_but_triplet_captures():
    w = ex.make_ring_cycle_world(num_agents=12, cycle_length=3)
    bilateral = ex.solve_bilateral_ir_oracle(w, participants=list(range(1, 13)))
    assert bilateral.welfare_gain < 1e-6  # no pairwise IR gain
    triplet = ex.solve_fractional_ir_oracle(w, participants=[1, 2, 3])
    assert triplet.welfare_gain > 1e-6  # the 3-cycle captures surplus


def test_ring_cycle_k4_no_bilateral_but_quad_captures():
    w = ex.make_ring_cycle_world(num_agents=12, cycle_length=4)
    bilateral = ex.solve_bilateral_ir_oracle(w, participants=list(range(1, 13)))
    assert bilateral.welfare_gain < 1e-6
    quad = ex.solve_fractional_ir_oracle(w, participants=[1, 2, 3, 4])
    assert quad.welfare_gain > 1e-6


def test_ring_cycle_requires_divisible_num_agents():
    with pytest.raises(ValueError):
        ex.make_ring_cycle_world(num_agents=10, cycle_length=3)  # 10 % 3 != 0


def test_ring_cycle_config_dispatch(tmp_path):
    import json

    cfg = {
        "name": "rc_k3", "description": "", "num_agents": 12, "num_resources": 12,
        "units_per_home_resource": 10, "seed": 0, "rounds": 8, "controllers": [1, 2],
        "world_type": "ring_cycle", "cycle_length": 3, "utility_mode": "linear",
        "protocol": {"name": "rc_k3"},
    }
    p = tmp_path / "rc_k3.json"
    p.write_text(json.dumps(cfg))
    c = ex.load_experiment_config(p)
    assert c.world_type == "ring_cycle"
    assert c.cycle_length == 3
    w = ex.make_world_from_config(c)
    bilateral = ex.solve_bilateral_ir_oracle(w, participants=list(range(1, 13)))
    assert bilateral.welfare_gain < 1e-6  # config-built k=3 ring has no bilateral surplus
