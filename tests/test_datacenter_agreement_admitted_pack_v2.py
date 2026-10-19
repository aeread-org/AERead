"""The agreement case's v2 packs (``agreement_admitted_pack_v2``): v1's admission, the walk-away brief and the headroom screen.

What ``docs/families/datacenter/agreement_confirmatory_v2_plan.md`` (Section 2, amendment 3) asks of them, each checked:

1. Both committed packs pass the pack checks (quotas, the give-up share, distinct worlds, nothing shared with a v1 pack,
   a development pack or the other v2 pack, at least 56 deal worlds in the confirmatory pack) and their scan logs are
   consistent row by row.
2. Every case carries the walk-away brief, its digest recomputes, the client's brief gains exactly the walk-away line and
   the integrator's brief is v1's.
3. Every deal world clears the screen and no world without a deal was screened; a world below the margin is refused.
4. Logged rows recompute from their seeds, including a screened deal world's headroom.
5. A seed's status follows the declared rule: reasons, then the cell's quota, then the screen; the extension admits only
   deal worlds that pass the screen.
"""

from __future__ import annotations

import copy

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_pack as aap
from aeread_families.datacenter_development import agreement_admitted_pack_v2 as v2
from aeread_families.datacenter_development.agreement_environment import BRIEF_FIELD, AgreementPlugin, _world


@pytest.fixture(scope="module", params=[v2.ADMITTED.pack, v2.PILOT.pack])
def pack(request):
    spec = v2.SPECS[request.param]
    manifest, cases, log = v2.load(spec)
    return spec, manifest, cases, log


def test_the_committed_packs_pass_the_pack_and_log_checks(pack) -> None:
    spec, manifest, cases, log = pack
    assert v2.pack_failures(manifest, cases, spec) == []
    assert v2.log_failures(log, spec) == []
    deal = [w for w in manifest["worlds"] if w["available_surplus"] > 0]
    assert len(manifest["worlds"]) == sum(spec.quotas.values()) + sum(w["status"] == "admitted_extension" for w in manifest["worlds"])
    if spec == v2.ADMITTED:
        assert len(manifest["worlds"]) == 80 and len(deal) >= v2.MIN_DEAL_WORLDS


def test_every_case_carries_the_walk_away_brief_and_the_integrators_brief_is_v1s(pack) -> None:
    _, _, cases, _ = pack
    plugin = AgreementPlugin()
    for case in cases.values():
        assert case["payload"][BRIEF_FIELD] == v2.BRIEF_VERSION
        assert case_content_sha256(case) == case["content_sha256"]
        payload = plugin.validate_payload(case["payload"])
        cw, it = _world(payload)
        state = ag.initial_state(cw)
        client = plugin.observe(payload, state, "client", None)["brief"].split("\n")
        added = [line for line in client if line not in ag.brief(cw, "client").split("\n")]
        assert len(added) == 1 and "Walking away therefore costs you" in added[0]
        assert plugin.observe(payload, state, "integrator", None)["brief"] == ag.brief(cw, "integrator", it)


def test_every_deal_world_clears_the_screen_and_a_world_below_it_is_refused(pack) -> None:
    spec, manifest, cases, log = pack
    for w in manifest["worlds"]:
        h = w["integrator_headroom"]
        assert (h is not None) == (w["available_surplus"] > 0)
        if h is not None:
            assert h["headroom"] >= v2.HEADROOM_MARGIN and abs(h["ceiling"] - h["rule"] - h["headroom"]) < 2e-3
    below = [row for row in log if row[5] == "headroom_under_margin"]
    assert below and all(row[10] == 1 and row[11] < v2.HEADROOM_MARGIN for row in below)
    broken = copy.deepcopy(manifest)
    deal = next(w for w in broken["worlds"] if w["integrator_headroom"])
    deal["integrator_headroom"]["headroom"] = v2.HEADROOM_MARGIN - 1
    assert any("breaks the headroom screen" in x for x in v2.pack_failures(broken, cases, spec))


def test_logged_rows_recompute_from_their_seeds() -> None:
    spec = v2.PILOT
    _, _, log = v2.load(spec)
    seeds = [next(r[0] for r in log if r[5] == s) for s in ("rejected", "cell_full")]
    seeds.append(next(r[0] for r in log if r[5] == "admitted" and r[10] == 0))
    seeds.append(min((r for r in log if r[5] == "headroom_under_margin"), key=lambda r: r[0])[0])
    assert v2.verify_rows(log, seeds, spec) == []
    changed = [list(r) for r in log]
    row = next(r for r in changed if r[0] == seeds[-1])
    row[11] = round(row[11] + 1.0, 3)
    assert v2.verify_rows(changed, [seeds[-1]], spec)


def test_a_seeds_status_follows_reasons_then_quota_then_screen_then_extension() -> None:
    open_cell = {"walk": 1, "trade": 0, "hand_risk_over": 0, "take_risk_on": 0, "move_the_price": 0}
    deal_ok, deal_low, no_deal = ({"deal": True, "headroom": 30.0}, {"deal": True, "headroom": 10.0},
                                  {"deal": False, "headroom": None})
    assert v2.decide({"reasons": ["walk_loses_under_margin"], "cell": "walk"}, None, open_cell, 0, 56) == "rejected"
    assert v2.decide({"reasons": [], "cell": "trade"}, None, open_cell, 0, 56) == "cell_full"
    assert v2.decide({"reasons": [], "cell": "walk"}, deal_low, open_cell, 0, 56) == "headroom_under_margin"
    assert v2.decide({"reasons": [], "cell": "walk"}, deal_ok, open_cell, 0, 56) == "admitted"
    assert v2.decide({"reasons": [], "cell": "walk"}, no_deal, open_cell, 0, 56) == "admitted"
    full = {k: 0 for k in open_cell}
    assert v2.decide({"reasons": [], "cell": "trade"}, deal_ok, full, 55, 56) == "admitted_extension"
    assert v2.decide({"reasons": [], "cell": "trade"}, deal_low, full, 55, 56) == "headroom_under_margin"
    assert v2.decide({"reasons": [], "cell": "trade"}, no_deal, full, 55, 56) == "cell_full"
    assert not v2.needs_screen({"reasons": [], "cell": "trade"}, full, 56, 56)


def test_the_v2_packs_share_no_world_with_v1_and_use_their_own_type_stream() -> None:
    v1_worlds = {w["world_seed"] for spec in (aap.ADMITTED, aap.PILOT) for w in aap.load(spec)[0]["worlds"]}
    for spec in (v2.ADMITTED, v2.PILOT):
        seeds = {w["world_seed"] for w in v2.load(spec)[0]["worlds"]}
        assert not seeds & v1_worlds and min(seeds) >= spec.base_seed
        assert spec.type_stream.startswith(spec.pack + "/")
