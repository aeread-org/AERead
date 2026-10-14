"""Measure v2 for the price case (HL-D-07) and the v14 panel recomputed under it.

Hand-built trajectories on a real pack world check each rule of the posterior; a property test
checks that the real landlord rule never makes an informative reply lie; scripted seats in the
real market check v1 and v2 agree where they should and part where HL-D-07 says they do; and
the derived analysis regenerates byte for byte, reproduces the published v14 analysis under v1,
and gives the recomputation recorded in HL-D-07 under v2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from aeread_families.housing import lemons, price_bargaining, price_campaign, price_endpoint
from aeread_families.housing import price_reference as pr
from aeread_families.housing import price_reply_conditioned as rc
from aeread_families.housing import price_reply_posterior as post
from aeread_families.housing.price_reply_posterior import Reply, Trajectory

SEED = 300000  # qualities sound, sound, lemon, lemon; sound floors 2552.31, 2125.78, 3138.5, 3018.15
LEAKY, POOLED = (pr.make_world(SEED, arm) for arm in ("true_cost", "pooled"))
FLOORS = [price_endpoint.sound_floor(LEAKY, listing) for listing in range(4)]


def _decision(world, round_index: int, listing: int, rent: float, known: Mapping[int, str]) -> dict[str, Any]:
    """A blind signing as the environment records it: its value at the stated odds."""
    p = post.lemon_posterior(listing, known, world.lemon_count, world.num_listings)
    return {"tenant_id": 0, "round_index": round_index, "listing_id": listing, "rent": rent, "informed": False,
            "decision": "sign", "quality": post.quality(world, listing),
            "expected_value": round(float(world.values_if_sound[0][listing]) - p * world.lemon_loss, 2)}


def _p_v2(world, decision, trajectory: Trajectory) -> float:
    scored = post.score_seat(world, [decision], trajectory, 25.0 * len(trajectory.inspections))
    return scored["blind_signings"][0]["p_v2"]


def test_the_world_is_the_one_the_cases_assume() -> None:
    assert [post.quality(LEAKY, l) for l in range(4)] == ["sound", "sound", "lemon", "lemon"]
    assert FLOORS == [2552.31, 2125.78, 3138.5, 3018.15]
    assert all(post.lemon_target(LEAKY, l) < FLOORS[l] for l in range(4))


def test_posterior_counts_lemons_exactly() -> None:
    p = lambda listing, known: post.lemon_posterior(listing, known, 2, 4)  # noqa: E731
    assert p(0, {}) == 0.5 and p(1, {0: "lemon"}) == pytest.approx(1 / 3) and p(1, {0: "sound"}) == pytest.approx(2 / 3)
    assert p(3, {0: "lemon", 1: "lemon"}) == 0.0 and p(3, {0: "sound", 1: "sound"}) == 1.0
    assert p(2, {2: "lemon"}) == 1.0 and p(2, {2: "sound"}) == 0.0


@pytest.mark.parametrize("world, reply, expected", [
    (LEAKY, Reply(0, 0, 1500.0, 2552.31), "sound"),           # counter at the sound floor
    (LEAKY, Reply(0, 2, 0.0, 2138.5), "lemon"),               # counter at the lemon target, below the floor
    (LEAKY, Reply(0, 2, 2200.0, 2200.0), "lemon"),            # acceptance below the floor
    (LEAKY, Reply(0, 0, 2552.31, 2552.31), None),             # acceptance at the floor: either quality
    (LEAKY, Reply(0, 0, 2600.0, 2600.0), None),               # acceptance above it
    (POOLED, Reply(0, 0, 0.0, 2552.31), None),                # pooled: nothing
    (POOLED, Reply(0, 2, 0.0, 3138.5), None),
])
def test_what_a_reply_proves(world, reply: Reply, expected) -> None:
    assert post.reply_quality(world, reply) == expected


def test_a_reply_the_rule_cannot_give_stops_the_scorer() -> None:
    with pytest.raises(ValueError, match="cannot give"):
        post.reply_quality(LEAKY, Reply(0, 0, 1500.0, 2560.0))


def test_a_listing_whose_landlords_answer_alike_reveals_nothing() -> None:
    # If the ask sits below the lemon's cost plus margin, both landlords counter at the ask.
    import dataclasses

    world = dataclasses.replace(LEAKY, ask=[1600.0, *LEAKY.ask[1:]], sound_costs=(1590.0, *LEAKY.sound_costs[1:]))
    floor = price_endpoint.sound_floor(world, 0)
    assert post.lemon_target(world, 0) < floor  # still separating here: lemon cost 590
    world = dataclasses.replace(world, lemon_loss=5.0)
    assert post.lemon_target(world, 0) == floor and post.reply_quality(world, Reply(0, 0, 0.0, floor)) is None


def test_hl_d_07_gap_one_a_sound_counter_on_the_signed_listing() -> None:
    reply = Reply(0, 0, 1500.0, FLOORS[0])
    decision = _decision(LEAKY, 0, 0, FLOORS[0], {})
    assert _p_v2(LEAKY, decision, Trajectory(replies=[reply])) == 0.0
    scored = post.score_seat(LEAKY, [decision], Trajectory(replies=[reply]), 0.0)
    assert scored["blind_signings"][0]["p_v1"] == 0.5 and scored["changed_signings"] == 1
    assert scored["primary_v2"] - scored["primary_v1"] == pytest.approx(500.0)
    # The same reply in the pooled arm changes nothing.
    assert _p_v2(POOLED, _decision(POOLED, 0, 0, FLOORS[0], {}), Trajectory(replies=[reply])) == 0.5


def test_hl_d_07_gap_two_a_reply_on_another_listing() -> None:
    # Round 0 proves listing 2 a lemon; round 1 signs listing 0 at an uninformative acceptance.
    replies = [Reply(0, 2, 1000.0, 1000.0), Reply(1, 0, 2600.0, 2600.0)]
    assert _p_v2(LEAKY, _decision(LEAKY, 1, 0, 2600.0, {}), Trajectory(replies=replies)) == pytest.approx(1 / 3, abs=1e-6)
    # A sound listing found by reply raises the odds on the rest.
    replies = [Reply(0, 1, 1500.0, FLOORS[1]), Reply(1, 0, 2600.0, 2600.0)]
    trajectory = Trajectory(inspections={2: 0}, replies=replies)
    assert _p_v2(LEAKY, _decision(LEAKY, 1, 0, 2600.0, {2: "lemon"}), trajectory) == 0.5
    # Both lemons known, one inspected and one by reply: the rest are sound.
    trajectory = Trajectory(inspections={2: 0}, replies=[Reply(0, 3, 1000.0, 1000.0), Reply(1, 0, 2600.0, 2600.0)])
    assert _p_v2(LEAKY, _decision(LEAKY, 1, 0, 2600.0, {2: "lemon"}), trajectory) == 0.0


def test_knowledge_follows_the_round_order() -> None:
    # A reply in a later round is not used for an earlier decision; a listing both inspected and
    # revealed counts once; a reveal in an earlier round on the same listing carries forward.
    later = Trajectory(replies=[Reply(0, 0, 2600.0, 2600.0), Reply(1, 2, 1000.0, 1000.0)])
    assert _p_v2(LEAKY, _decision(LEAKY, 0, 0, 2600.0, {}), later) == 0.5
    twice = Trajectory(inspections={2: 0}, replies=[Reply(0, 2, 1000.0, 1000.0), Reply(1, 0, 2600.0, 2600.0)])
    assert _p_v2(LEAKY, _decision(LEAKY, 1, 0, 2600.0, {2: "lemon"}), twice) == pytest.approx(1 / 3, abs=1e-6)
    earlier = Trajectory(replies=[Reply(0, 0, 1500.0, FLOORS[0]), Reply(1, 0, FLOORS[0], FLOORS[0])])
    assert _p_v2(LEAKY, _decision(LEAKY, 1, 0, FLOORS[0], {}), earlier) == 0.0


def test_a_decision_that_does_not_match_its_record_stops_the_scorer() -> None:
    decision = dict(_decision(LEAKY, 0, 0, 2600.0, {}), expected_value=1.0)
    with pytest.raises(ValueError, match="stated odds"):
        post.score_seat(LEAKY, [decision], Trajectory(), 0.0)
    with pytest.raises(ValueError, match="inspected"):
        post.score_seat(LEAKY, [_decision(LEAKY, 1, 0, 2600.0, {})], Trajectory(inspections={0: 0}), 25.0)


def test_the_real_landlord_rule_never_makes_an_informative_reply_lie() -> None:
    informative = 0
    for seed in price_campaign.PACK_WORLD_SEEDS:
        world = pr.make_world(seed, "true_cost")
        for listing in range(4):
            floor = price_endpoint.sound_floor(world, listing)
            for offer in (0.0, floor - 1100, floor - 600, floor - 30, floor - 1, floor - 0.01, floor, floor + 5,
                          float(world.ask[listing])):
                offer = max(0.0, round(offer, 2))
                observation = {"inbox": [{"offer_id": "o", "tenant_id": 0, "rent": offer, "listing_id": listing}],
                               "private_cost": world.costs[listing], "listing": {"rent_asked": world.ask[listing]}}
                action = price_bargaining.landlord_action(observation)
                hold = offer if action["decision"] == "accept" else action["counter_rent"]
                found = post.reply_quality(world, Reply(0, listing, offer, hold))
                informative += found is not None
                assert found in (None, post.quality(world, listing)), (seed, listing, offer)
    assert informative > 3000


def _blind_lowball(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    """Offers $0 on its favourite without inspecting and signs any hold its value-if-sound covers."""
    if phase_id == "contact":
        rows = [r for r in lemons._open_candidates(observation) if lemons._gain_if_sound(observation, r) > 0]
        if rows:
            best = max(rows, key=lambda r: lemons._gain_if_sound(observation, r))
            return {"decision": "offer", "listing_id": best["listing_id"], "rent": 0.0}
    if phase_id == "commit":
        hold = lemons._hold_view(observation)
        if hold and float(hold["rent"]) <= float(observation["private_values_if_sound"][hold["listing_id"]]):
            return {"decision": "sign", "hold_id": hold["hold_id"]}
    return lemons._pass(phase_id)


def test_scripted_seats_in_the_real_market_split_where_hl_d_07_says() -> None:
    # A blind $0 offer on the leaky arm is answered by a reply that proves quality: a lemon below
    # the floor (v1 and v2 agree, p = 1) or a sound counter at the floor (v1 keeps 0.5, v2 has 0).
    seen = {"lemon": 0, "sound": 0}
    for seed in price_campaign.PACK["main"]["world_seeds"][:60]:
        market, trajectory = post.run_recorded(seed, "true_cost", _blind_lowball)
        scored = post.score_market(market, trajectory)
        for blind in scored["blind_signings"]:
            seen[blind["reply_this_round"]] += 1
            assert blind["p_v2"] == (1.0 if blind["quality"] == "lemon" else 0.0)
            assert blind["p_v1"] == (1.0 if blind["quality"] == "lemon" else blind["p_stated"])
        assert scored["primary_v2"] >= scored["primary_v1"]
        pooled = post.score_market(*post.run_recorded(seed, "pooled", _blind_lowball))
        assert pooled["primary_v2"] == pooled["primary_v1"]
    assert seen["lemon"] and seen["sound"]


def test_the_recorder_reads_inspections_by_round_and_one_reply_per_hold() -> None:
    market, trajectory = post.run_recorded(300003, "pooled", pr.inspect_lowball_action)
    assert trajectory.inspections == {3: 0, 1: 1}
    assert [(r.round_index, r.listing_id, r.offer) for r in trajectory.replies] == [(0, 3, 0.0), (1, 1, 0.0)]
    assert Trajectory.from_row(json.loads(json.dumps(trajectory.to_row()))) == trajectory


# --- the derived analysis -----------------------------------------------------------------

@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return json.loads((rc.OUT / "reports/reply_conditioned.json").read_text())


def test_the_analysis_regenerates_to_the_committed_bytes() -> None:
    assert rc.check(from_runs=False)


def test_v2_gives_the_recomputation_recorded_in_hl_d_07(report) -> None:
    v2 = report["summary"]["v2"]
    main = {m: v2["models"][m]["main"] for m in ("Gemini", "GLM", "Luna")}
    assert {m: (x["mean"], x["lo"], x["hi"]) for m, x in main.items()} == {
        "Gemini": (212.81, 190.28, 235.35), "GLM": (149.4, 123.77, 175.03), "Luna": (147.34, 121.15, 173.54)}
    pairs = {k: (v["main"]["mean"], v["main"]["lo"], v["main"]["hi"]) for k, v in v2["pairs"].items()}
    assert pairs == {"Gemini-GLM": (59.64, 38.52, 80.75), "Gemini-Luna": (66.54, 49.37, 83.7), "GLM-Luna": (2.06, -20.03, 24.14)}
    assert {m: report["counts"][m]["changed_signings"] for m in ("GLM", "Luna", "Gemini")} == {"GLM": 21, "Luna": 33, "Gemini": 3}
    assert all(report["counts"][m]["changed_by_a_reply_on_another_listing"] == 0 for m in ("GLM", "Luna", "Gemini"))
    assert report["declared_verdicts_changed"] is False
    fill = report["summary"]["v2_with_fill"]["pairs"]
    assert (fill["Gemini-GLM"]["main"]["mean"], fill["Gemini-Luna"]["main"]["mean"]) == (63.4, 65.46)


def test_v1_from_the_table_is_the_published_analysis(report) -> None:
    published = json.loads((rc.V14 / "reports/analysis.json").read_text())
    for model, short in rc.SHORT.items():
        assert report["summary"]["v1"]["models"][short]["main"]["mean"] == published["models"][model]["by_scope"]["main"]["primary"]["mean"]


def test_invalid_seat0_actions_are_counted(report) -> None:
    assert report["counts"]["GLM"]["invalid_seat0_actions_by_code"] == {"malformed_commit": 1, "unavailable_listing": 15}
    assert report["counts"]["GLM"]["cells_with_invalid_seat0_actions"] == 16
    assert all(not report["counts"][m]["invalid_seat0_actions_by_code"] for m in ("Luna", "Gemini", "Gemini fill"))


def test_the_check_fails_when_the_measure_ignores_a_sound_counter(monkeypatch) -> None:
    # Counterexample: drop gap (1) from v2 and the committed analysis no longer regenerates.
    original = post.reply_quality
    monkeypatch.setattr(post, "reply_quality", lambda world, reply, margin=price_bargaining.LANDLORD_MARGIN:
                        None if original(world, reply, margin) == post.SOUND else original(world, reply, margin))
    report, _ = rc.analyse(rc.committed_rows())
    assert {m: report["counts"][m]["changed_signings"] for m in ("GLM", "Luna", "Gemini")} == {"GLM": 0, "Luna": 0, "Gemini": 0}
    assert not rc.check(from_runs=False)


RUN_ROOTS = [rc.RUNS / cid / "live" for cid in rc.CAMPAIGNS]


@pytest.mark.skipif(not all(root.is_dir() for root in RUN_ROOTS), reason="the sealed v14 run roots are not in runs/")
def test_a_sample_of_the_table_re_extracts_from_the_sealed_run_roots(tmp_path, monkeypatch) -> None:
    # The full re-extraction is ``--check --from-runs`` (about six minutes: every event chain is
    # audited). Here: two cells per campaign, through the same code, against the committed rows.
    committed = {(r["campaign_id"], r["world_seed"], r["arm"]): r for r in rc.committed_rows()}
    sample = {k for cid in rc.CAMPAIGNS for k in sorted(k for k in committed if k[0] == cid)[:2]}
    for cid, seed, arm in sample:
        (tmp_path / cid / "live").mkdir(parents=True, exist_ok=True)
        for suffix in (".json", "_evidence"):
            (tmp_path / cid / "live" / f"world_{seed}__{arm}{suffix}").symlink_to(rc.RUNS / cid / "live" / f"world_{seed}__{arm}{suffix}")
    restricted = {cid: [r for r in rows if (cid, r["world_seed"], r["arm"]) in sample] for cid, rows in rc.published().items()}
    monkeypatch.setattr(rc, "published", lambda: restricted)
    rows = rc.extract(tmp_path)
    assert len(rows) == len(sample) == 2 * len(rc.CAMPAIGNS)
    for row in rows:
        assert row == committed[(row["campaign_id"], row["world_seed"], row["arm"])]
