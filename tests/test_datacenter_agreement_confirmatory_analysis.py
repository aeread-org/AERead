"""The agreement confirmatory's analysis (``tools/cli_subjects/agreement_confirmatory_analysis.py``), on constructed cells.

1. The sizing module is ``aeread.design.sizing`` at 159cba3c byte for byte, and it reproduces the plan's own sizing:
   27 deal worlds for P2 at the development SD of 71.9 and 28 for P1 at 148.7.
2. A world value is the seat-averaged Codex-less-Claude gap; one missing negotiation drops the world, and the bounds
   fill it with its pairing's lowest and highest earnings.
3. Holm steps down across the three contrasts; P3 is an exact McNemar on the discordant worlds; P2 reads "no gap of 50
   or more" only when the upper end of its 1 - 0.05/3 interval is below 50, and any contrast that loses more than 10%
   of its worlds is inconclusive.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "cli_subjects"))

import agreement_confirmatory_analysis as an  # noqa: E402

SIZING_159CBA3C_SHA256 = "6a3f0794d336b92d6d5566159885d8b1dd03ff284e21d6478b2d8aba22d6a41f"


def test_the_sizing_copy_is_the_design_module_at_159cba3c_and_reproduces_the_plans_sizing() -> None:
    module, digest = an._sizing_module()
    assert digest == SIZING_159CBA3C_SHA256
    assert hashlib.sha256((ROOT / "tools/cli_subjects/agreement_confirmatory_sizing_159cba3c.py").read_bytes()).hexdigest() == digest
    record = module.sizing_record(sd_of_differences=71.9, minimum_effect=50, pilot_worlds=52, pilot_source="development", power=an.POWER,
                                  alpha=an.ALPHA / an.FAMILY, attrition=an.ATTRITION)
    assert (record["worlds_before_attrition"], record["worlds"]) == (25, 27)
    assert module.worlds_needed(148.7, 100, power=an.POWER, alpha=an.ALPHA / an.FAMILY, attrition=an.ATTRITION) == 28


def cell(pairing: str, world: str, integ: float, client: float, valid: bool = True, client_ir: bool = False) -> dict:
    return {"pairing": pairing, "world": world, "replicate_index": 0, "valid": valid, "status": "ok", "cell_key": f"{pairing}__{world}",
            "leaves": {"integrator_surplus": integ, "client_surplus": client, "client_ir_violation": float(client_ir), "episode_valid": float(valid)}}


def test_a_world_value_is_the_seat_averaged_gap_and_a_missing_negotiation_drops_the_world_within_its_bounds() -> None:
    p = an.h_pairings()
    cells = {}
    for w, (ci, cc, oi, oc) in {"w1": (100, 40, 80, 60), "w2": (90, 50, 70, 30)}.items():
        # codex as integrator against claude as client, and the reverse
        cells[(p["codex_int"], w, 0)] = cell(p["codex_int"], w, ci, oc)
        cells[(p["claude_int"], w, 0)] = cell(p["claude_int"], w, oi, cc)
    assert an.world_value(an._entries_h(cells, "w1")) == ((100 - 80) + (40 - 60)) / 2
    assert an.world_value(an._entries_h(cells, "w2")) == ((90 - 70) + (50 - 30)) / 2
    cells[(p["claude_int"], "w2", 0)]["valid"] = False
    entries = an._entries_h(cells, "w2")
    assert an.world_value(entries) is None
    low, high = an._bounded(entries, cells, True), an._bounded(entries, cells, False)
    # claude's integrator earnings and codex's client earnings come from the one valid claude_int cell (80, 40)
    assert low == ((90 - 80) + (40 - 30)) / 2 and high == low
    result = an.paired_contrast("P1", {w: an._entries_h(cells, w) for w in ("w1", "w2")}, cells, 2)
    assert result["worlds_used"] == 1 and result["worlds_dropped"] == ["w2"] and result["dropout_share"] == 0.5


def test_holm_steps_down_and_a_large_dropout_is_inconclusive() -> None:
    rs = [{"contrast": "P1", "p": 0.01, "dropout_share": 0.0}, {"contrast": "P2", "p": 0.04, "dropout_share": 0.0},
          {"contrast": "P3", "p": 0.03, "dropout_share": 0.2}]
    an.holm(rs)
    assert [round(r["p_holm"], 6) for r in rs] == [0.03, 0.06, 0.06]
    assert [r["rejected"] for r in rs] == [True, False, False]
    assert [r["holm_alpha"] for r in rs] == [pytest.approx(0.05 / 3), 0.05, 0.025]
    assert [r["inconclusive_by_dropout"] for r in rs] == [False, False, True]
    assert an.reading(rs[2]).startswith("inconclusive")


def test_p2_reads_no_gap_only_when_the_strict_interval_ends_below_fifty() -> None:
    key = f"ci_{1 - an.ALPHA / an.FAMILY:.4f}"
    base = {"contrast": "P2", "rejected": False, "inconclusive_by_dropout": False}
    assert an.reading({**base, key: [-20.0, 49.0]}) == "no gap of 50 or more against a firm counterpart"
    assert an.reading({**base, key: [-20.0, 51.0]}) == "inconclusive"
    assert an.reading({**base, "rejected": True, key: [5.0, 51.0]}) == "a gap against the firm population is claimed"


def test_p3_is_an_exact_mcnemar_on_the_discordant_worlds() -> None:
    p = an.h_pairings()
    cells = {}
    worlds = [f"w{i}" for i in range(12)]
    for i, w in enumerate(worlds):
        opus = i < 8  # Opus as client signs below its walk-away point in 8 worlds
        codex = i == 0  # Codex as client in 1, which Opus shares
        cells[(p["codex_int"], w, 0)] = cell(p["codex_int"], w, 0, 0, client_ir=opus)
        cells[(p["claude_int"], w, 0)] = cell(p["claude_int"], w, 0, 0, client_ir=codex)
    r = an.mcnemar(cells, worlds)
    assert (r["discordant_opus_only"], r["discordant_codex_only"]) == (7, 0)
    assert r["p"] == pytest.approx(2 * 0.5 ** 7)
    assert (r["opus_below_walk_away"], r["codex_below_walk_away"]) == (8, 1)
