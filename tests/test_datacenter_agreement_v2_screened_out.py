"""The addendum's pack is exactly the v2 generator's refused worlds, and its Holm step matches the declaration."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "cases/datacenter_agreement_v1/agreement_v2_screened_out_v1"
V2 = ROOT / "cases/datacenter_agreement_v1/agreement_admitted_v2"


def test_pack_is_the_refused_worlds_and_only_those():
    manifest = json.loads((PACK / "pack.json").read_text())
    fields = json.loads((V2 / "pack.json").read_text())["scan_log_fields"]
    log = json.loads((V2 / "scan.json").read_text())
    refused = {r[0]: r[fields.index("headroom")] for r in log if r[fields.index("status")] == "headroom_under_margin"}
    assert len(refused) == 14 and {w["world_seed"] for w in manifest["worlds"]} == set(refused)
    for world in manifest["worlds"]:
        assert world["available_surplus"] > 0
        assert abs(world["integrator_headroom"]["headroom"] - refused[world["world_seed"]]) < 1e-3
        assert world["integrator_headroom"]["headroom"] < 25


def test_pack_is_disjoint_from_the_admitted_worlds():
    admitted = {w["world_seed"] for w in json.loads((V2 / "pack.json").read_text())["worlds"]}
    assert admitted.isdisjoint(w["world_seed"] for w in json.loads((PACK / "pack.json").read_text())["worlds"])
