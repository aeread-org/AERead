"""Money / double-coincidence axis: wire with_money through the config system.

make_exchange_world already supports with_money (appends a transferable numeraire good
valued 1.0 by everyone). This tests that a config `"with_money": true` reaches the world
builder, so money-vs-barter arenas can be run from config.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread.exchange_v1 import economy as ex  # noqa: E402


def _cfg(with_money):
    return {
        "name": "m", "description": "", "num_agents": 6, "num_resources": 6,
        "units_per_home_resource": 10, "seed": 7, "rounds": 6, "controllers": [1, 3],
        "utility_mode": "concave_separable", "with_money": with_money,
        "protocol": {"name": "m"},
    }


def test_with_money_config_appends_numeraire(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(_cfg(True)))
    c = ex.load_experiment_config(p)
    assert c.with_money is True
    w = ex.make_world_from_config(c)
    assert w.money_good_index == 6          # appended after the 6 base goods
    assert w.num_resources == 7             # 6 goods + money
    assert all(row[6] > 0 for row in w.allocation)  # everyone endowed with money


def test_default_config_has_no_money(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(_cfg(False)))
    c = ex.load_experiment_config(p)
    assert c.with_money is False
    w = ex.make_world_from_config(c)
    assert w.money_good_index is None
    assert w.num_resources == 6
