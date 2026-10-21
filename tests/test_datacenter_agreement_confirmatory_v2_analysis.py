"""The agreement case's v2 analysis (``tools/cli_subjects/agreement_confirmatory_v2_analysis.py``), on constructed cells.

1. The committed sizing module reproduces Section 6: 27 deal worlds for P2 at SD 140.6, 38 to 39 for P3 at SD 69 to 70,
   and 32 to 43 for P1 at SD 62 to 73 (the plan's 44 is SD 73.2 or more, its table rounds the SD to 73).
2. A model's valid plays are averaged within a world first; a world drops out of P1 only when a model has no valid play,
   and the bounds fill each missing play with its pairing's lowest or highest earnings.
3. P3 subtracts the rule's earnings in the same world; P2 is v1's seat-averaged head-to-head value.
4. Holm steps down across four contrasts; a found contrast is "at least its minimum effect" only when its 95% interval
   clears it, in either direction; more than 10% of deal worlds missing is inconclusive.
5. Identical plays are counted per model over the worlds where every play is valid.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "cli_subjects"))

import agreement_confirmatory_v2_analysis as an  # noqa: E402


def cell(pairing: str, world: str, r: int, integ: float, client: float = 0.0, valid: bool = True, grade: dict | None = None) -> dict:
    return {"pairing": pairing, "world": world, "replicate_index": r, "valid": valid, "status": "ok", "cell_key": f"{pairing}__{world}__r{r}",
            "grade": grade or {}, "leaves": {"integrator_surplus": integ, "client_surplus": client, "episode_valid": float(valid)}}


def index(cells: list[dict]) -> dict:
    return {(c["pairing"], c["world"], c["replicate_index"]): c for c in cells}


def test_the_sizing_module_reproduces_section_6() -> None:
    s = an.sizing()
    assert s["P2"] == 27 and s["P3"] == [38, 39] and s["P1_two_plays"] == [32, 43]
    assert s["alpha"] == 0.0125 and s["attrition"] == 0.05


def test_plays_are_averaged_first_and_a_world_drops_only_without_any_valid_play() -> None:
    cx, cl = an.if_pairing("codex"), an.if_pairing("claude")
    cells = index([cell(cx, "w1", 0, 100), cell(cx, "w1", 1, 60), cell(cl, "w1", 0, 50), cell(cl, "w1", 1, 30),
                   cell(cx, "w2", 0, 90), cell(cx, "w2", 1, 0, valid=False), cell(cl, "w2", 0, 40), cell(cl, "w2", 1, 40),
                   cell(cx, "w3", 0, 0, valid=False), cell(cx, "w3", 1, 0, valid=False), cell(cl, "w3", 0, 10), cell(cl, "w3", 1, 20)])
    assert an.play_mean(cells, cx, "w1", "integrator", 2) == 80 and an.play_mean(cells, cx, "w2", "integrator", 2) == 90
    assert an.play_mean(cells, cx, "w3", "integrator", 2) is None
    r = an.p1(cells, ["w1", "w2", "w3"], 2)
    assert r["world_values"] == {"w1": 40.0, "w2": 50.0} and r["worlds_dropped"] == ["w3"] and r["dropout_share"] == round(1 - 2 / 3, 4)
    lo, hi = r["missingness_bounds_mean"]
    assert lo <= r["mean"] <= hi


def test_p3_subtracts_the_rule_in_the_same_world_and_p2_is_v1s_head_to_head_value() -> None:
    cx = an.if_pairing("codex")
    cells = index([cell(cx, "w1", 0, 100), cell(cx, "w1", 1, 80), cell(cx, "w2", 0, 50), cell(cx, "w2", 1, 70)])
    r = an.p3("P3a", "codex", cells, ["w1", "w2"], 2, {"w1": 60.0, "w2": 20.0})
    assert r["world_values"] == {"w1": 30.0, "w2": 40.0} and r["minimum_effect"] == 40.0
    h = {"codex_int": "codex_integrator__claude_client", "claude_int": "claude_integrator__codex_client"}
    hh = index([cell(h["codex_int"], "w1", 0, 100, 40), cell(h["claude_int"], "w1", 0, 80, 60),
                cell(h["codex_int"], "w2", 0, 90, 30), cell(h["claude_int"], "w2", 0, 70, 50)])
    r2 = an.p2(hh, ["w1", "w2"])
    assert r2["world_values"] == {"w1": ((100 - 80) + (60 - 40)) / 2, "w2": ((90 - 70) + (50 - 30)) / 2}


def _result(name: str, p: float, lo: float, hi: float, mean: float, dropout: float = 0.0) -> dict:
    return {"contrast": name, "p": p, "ci_0.9500": [lo, hi], "mean": mean, "minimum_effect": an.EFFECTS[name], "dropout_share": dropout}


def test_holm_over_four_and_the_readings() -> None:
    results = [_result("P1", 0.001, 45, 90, 67), _result("P2", 0.004, 20, 200, 110), _result("P3a", 0.02, 5, 60, 30),
               _result("P3b", 0.3, -50, 15, -20)]
    an.v1a.holm(results)
    for r in results:
        r["inconclusive_by_dropout"] = r["dropout_share"] > an.DROPOUT
        r["reading"] = an.reading(r)
    assert [r["holm_alpha"] for r in sorted(results, key=lambda r: r["holm_step"])] == [0.0125, 0.05 / 3, 0.025, 0.05]
    assert [r["rejected"] for r in results] == [True, True, True, False]
    assert results[0]["reading"].startswith("found, at least") and "does not clear" in results[1]["reading"]
    assert "does not clear" in results[2]["reading"] and results[3]["reading"].startswith("not found")
    neg = _result("P1", 0.001, -90, -45, -67)
    an.v1a.holm([neg])
    neg["inconclusive_by_dropout"] = False
    assert an.reading(neg).startswith("found, at least")
    gone = _result("P1", 0.001, 45, 90, 67, dropout=0.11)
    an.v1a.holm([gone])
    gone["inconclusive_by_dropout"] = gone["dropout_share"] > an.DROPOUT
    assert an.reading(gone).startswith("inconclusive")


def test_identical_plays_are_counted_over_worlds_with_every_play_valid() -> None:
    cx, cl = an.if_pairing("codex"), an.if_pairing("claude")
    same = {"termination": "signed", "signed_agreement": "a", "signed_price": 10.0, "moves": 3}
    other = {**same, "signed_price": 11.0}
    campaign = {"plan": {"controls": {"replicates": 2}},
                "cells": [cell(cx, "w1", 0, 1, grade=same), cell(cx, "w1", 1, 1, grade=same), cell(cx, "w2", 0, 1, grade=same),
                          cell(cx, "w2", 1, 1, grade=other), cell(cl, "w1", 0, 1, grade=same), cell(cl, "w1", 1, 1, valid=False, grade=same)]}
    assert an.identical_plays(campaign) == {"codex": "1 of 2 worlds", "claude": "0 of 0 worlds"}
