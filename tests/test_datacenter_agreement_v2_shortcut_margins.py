"""Measured headroom by the reference route on ``agreement_admitted_v2``: what the gate review states, recomputed.

``tools/datacenter/agreement_v2_shortcut_margins.py`` scores every scripted integrator rule against the client's public
firm style on all 80 worlds and compares it with the grid ceiling the admission screen uses (a lower bound on the best
reply, DC-D-40). These are the numbers ``docs/families/datacenter/agreement_confirmatory_v2_qc.md`` reports and
incident DC-D-43 records: the screen's own rule loses at least the margin in every deal world, but two other
shortcuts and several competent styles do not, and in the eight worlds without a deal every rule earns the reference.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "datacenter"))

import agreement_v2_shortcut_margins as sm  # noqa: E402

from aeread_families.datacenter_development import agreement_admitted_pack_v2 as v2  # noqa: E402


@lru_cache(maxsize=None)
def computed():
    return sm.margins(processes=1, recompute_styles=False)


def test_the_committed_style_earnings_are_what_the_styles_earn_when_played_again() -> None:
    manifest, cases, _ = v2.load(v2.ADMITTED)
    by_world = {r["world"]: r for r in computed()["worlds"]}
    for row in (manifest["worlds"][0], manifest["worlds"][-1]):
        cw, it = v2.world_of(cases[row["case_id"]])
        played = sm.style_earnings(cw, it)
        stored = by_world[row["case_id"].rsplit(".", 1)[-1]]["earnings"]
        assert all(abs(played[s] - stored[s]) < sm.TOL for s in played)


def test_the_screens_rule_loses_the_margin_everywhere_but_two_other_shortcuts_do_not() -> None:
    deal = computed()["summary"]["ceiling"]["deal"]
    assert deal["worlds"] == 72
    assert deal["rules"]["price_only"]["min_gap"] >= v2.HEADROOM_MARGIN and deal["rules"]["price_only"]["worlds_below_margin"] == 0
    assert deal["rules"]["draft"]["worlds_below_margin"] == 4 and deal["rules"]["walk"]["worlds_below_margin"] == 3
    assert deal["worlds_some_shortcut_below_margin"] == 4
    # Three deal worlds have a ceiling under 25: walking away at once comes within the margin of the best reply, and
    # price_only clears the screen there only because it pays redline fees.
    walk_close = [r for r in computed()["worlds"] if r["deal"] and r["references"]["ceiling"] - r["earnings"]["walk"] < v2.HEADROOM_MARGIN]
    assert len(walk_close) == 3 and all(r["references"]["ceiling"] < v2.HEADROOM_MARGIN and r["earnings"]["price_only"] < 0 for r in walk_close)


def test_competent_styles_come_within_the_margin_in_a_third_of_deal_worlds_and_some_beat_the_grid() -> None:
    deal = computed()["summary"]["ceiling"]["deal"]
    assert deal["worlds_some_style_below_margin"] == 24 and deal["worlds_some_any_rule_below_margin"] == 27
    assert deal["style_min_gap"] < 0  # a fixed style beats the grid ceiling somewhere: the grid is a lower bound (DC-D-40)


def test_in_every_world_without_a_deal_every_rule_earns_the_reference() -> None:
    no_deal = computed()["summary"]["ceiling"]["no_deal"]
    assert no_deal["worlds"] == 8
    assert all(s["worlds_at_or_above_reference"] == 8 and s["mean_gap"] == 0 for s in no_deal["rules"].values())
