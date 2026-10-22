"""Pack v2's room above simple rules, read against the best-informed tenant (QC Gate 1, the reference route).

Gate 1 can rest on an exact reference instead of a model control when every *shortcut* (a deterministic policy that
skips the decision the case measures) loses a declared margin to the reference in every admitted world, and every
other deterministic rule is reported per world. This test recomputes both from the committed controls table of
``housing_lemons_price_pack_v2`` (``price_pack_v2.controls``), on measure v2, each world the mean of its two
landlord arms, the quantity the pack's headroom screen used.

Shortcuts, each losing at least the declared $25 in all 260 main worlds:

* ``pass`` never trades (smallest loss $28.06);
* ``sign_anything`` never inspects and signs at the ask (smallest loss $92.37);
* ``inspect_then_sign`` inspects by its posterior but signs at the ask, so it skips the pricing half of the case;
  it is the screened rule (smallest loss $25.69).

``inspect_lowball`` is not a shortcut: it inspects, offers $0 and signs the landlord's counter only when the verified
value covers it, so it exercises both halves. It is the finding (HL-D-10): it comes within $25 of the reference in
229 of 260 worlds, equals it to the cent in all 60 favourite-sound worlds, and beats it in 26 favourite-lemon worlds
(by up to $61.26), because the reference maximises expected value before the quality draw and is compared here
after it. Its mean shortfall is $14.27 a world against the reference's $307.43, which is the 95% the paper reports.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from aeread_families.housing import price_pack_v2 as pack

TABLES = Path(__file__).resolve().parents[1] / "evidence/housing" / pack.PACK_ID / "tables"
SHORTCUTS = {"pass": 28.06, "sign_anything": 92.37, "inspect_then_sign": 25.69}


def _main_worlds() -> tuple[dict[int, dict[str, dict]], dict[int, dict]]:
    scan = [json.loads(line) for line in (TABLES / "scan.jsonl").read_text().splitlines()]
    admitted = {r["world_seed"]: r for r in scan if r["stream"] == "main" and r["status"] == "admitted"}
    worlds: dict[int, dict[str, dict]] = {}
    for line in (TABLES / "controls.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["stream"] == "main":
            worlds.setdefault(row["world_seed"], {})[row["arm"]] = row
    assert set(worlds) == set(admitted) and len(worlds) == 260
    return worlds, admitted


def _value(arms: dict[str, dict], name: str) -> float:
    return math.fsum(arms[arm][name]["primary_v2"] for arm in pack.ARMS) / len(pack.ARMS)


def _gaps(name: str) -> dict[int, float]:
    worlds, _ = _main_worlds()
    return {w: _value(arms, "best_informed") - _value(arms, name) for w, arms in worlds.items()}


def test_the_table_is_the_screen_the_pack_admitted_on() -> None:
    _, admitted = _main_worlds()
    gaps = _gaps("inspect_then_sign")
    assert max(abs(gaps[w] - admitted[w]["headroom"]) for w in gaps) <= 0.01


def test_every_shortcut_loses_the_declared_margin_in_every_world() -> None:
    for name, smallest in SHORTCUTS.items():
        gaps = _gaps(name)
        assert min(gaps.values()) >= pack.HEADROOM_MIN, name
        assert round(min(gaps.values()), 2) == smallest, name


def test_the_lowball_rule_comes_within_the_margin_of_the_reference_almost_everywhere() -> None:
    _, admitted = _main_worlds()
    gaps = _gaps("inspect_lowball")
    sound = [w for w in gaps if admitted[w]["stratum"] == "favourite_is_sound"]
    assert len(sound) == 60 and all(abs(gaps[w]) < 0.005 for w in sound)
    assert sum(g < pack.HEADROOM_MIN for g in gaps.values()) == 229
    beaten = [g for g in gaps.values() if g < 0]
    assert len(beaten) == 26 and round(min(beaten), 2) == -61.26
    assert all(admitted[w]["stratum"] == "favourite_is_lemon" for w, g in gaps.items() if g < 0)
    assert round(math.fsum(gaps.values()) / len(gaps), 2) == 14.27


def test_two_worlds_replay_offline_to_the_table() -> None:
    worlds, _ = _main_worlds()
    for seed in (500155, 500001):  # the lowball rule's largest win over the reference; a favourite-sound world
        for arm, row in worlds[seed].items():
            for name in ("best_informed", "inspect_lowball"):
                assert pack.play(seed, arm, name, row["rate_per_round"])["primary_v2"] == row[name]["primary_v2"]
