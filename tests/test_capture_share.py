"""Per-agent captured surplus — the distributional companion to market-level AER."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import capture_share as cs  # noqa: E402
from aeread import exchange_economy as ex  # noqa: E402
from aeread import exchange_v1_runner as runner  # noqa: E402


def _apply(world, mechanism):
    """Settle a mechanism's transfers into a fresh final-allocation matrix."""
    final = [row[:] for row in world.allocation]
    for t in mechanism.transfers:
        final[t.from_agent - 1][t.resource - 1] -= t.quantity
        final[t.to_agent - 1][t.resource - 1] += t.quantity
    return final


def test_no_trade_gives_zero_total_and_undefined_share():
    world = ex.make_exchange_world(num_agents=4, num_resources=4, seed=1)
    rep = cs.episode_capture(world, world.allocation, agent_id=1)  # final == initial
    assert rep.total_surplus == pytest.approx(0.0, abs=1e-9)
    assert rep.share is None  # never a fabricated ratio on a degenerate total
    assert rep.fair_share == pytest.approx(0.25)


def test_per_agent_surplus_matches_the_oracle_deltas():
    # capture-share from allocations must equal utility_delta_for_mechanism (the oracle's
    # own per-agent gain) — a cross-check against an independent code path.
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=3)
    mech = runner.ScriptedBilateralIRPolicy()._find_bilateral_ir_swap(world, 1)
    assert mech is not None
    final = _apply(world, mech)
    rep = cs.episode_capture(world, final, agent_id=1)
    for aid in (1, 2, 3):
        expected = ex.utility_delta_for_mechanism(world, mech, aid)
        assert rep.per_agent_surplus[aid - 1] == pytest.approx(expected)
    assert rep.total_surplus == pytest.approx(sum(rep.per_agent_surplus))
    assert rep.share == pytest.approx(rep.agent_surplus / rep.total_surplus)


def test_capture_reflects_the_extractor_taking_more_absolute_surplus():
    # max_own maximizes the proposer's ABSOLUTE surplus (not its share — a bigger joint pie
    # can dilute the share). capture_share must report that higher absolute take.
    first = runner.ScriptedBilateralIRPolicy()
    extract = runner.ScriptedBilateralIRPolicy(selection="max_own")
    saw_strict = False
    for seed in range(24):
        world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=seed)
        m_first = first._find_bilateral_ir_swap(world, 1)
        m_ex = extract._find_bilateral_ir_swap(world, 1)
        if m_first is None:
            continue
        own_first = cs.episode_capture(world, _apply(world, m_first), agent_id=1).agent_surplus
        own_ex = cs.episode_capture(world, _apply(world, m_ex), agent_id=1).agent_surplus
        assert own_ex >= own_first - 1e-9
        if own_ex > own_first + 1e-9:
            saw_strict = True
    assert saw_strict  # extraction demonstrably shifts absolute surplus toward the proposer


def test_positive_total_shares_sum_to_one():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=3)
    mech = runner.ScriptedBilateralIRPolicy()._find_bilateral_ir_swap(world, 1)
    rep = cs.episode_capture(world, _apply(world, mech), agent_id=1)
    assert rep.total_surplus > 0
    shares = [s / rep.total_surplus for s in rep.per_agent_surplus]
    assert sum(shares) == pytest.approx(1.0)


def test_pooled_capture_is_ratio_of_sums():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=3)
    mech = runner.ScriptedBilateralIRPolicy()._find_bilateral_ir_swap(world, 1)
    reps = [cs.episode_capture(world, _apply(world, mech), agent_id=1) for _ in range(3)]
    pooled = cs.pooled_capture_share(reps)
    num = sum(r.agent_surplus for r in reps)
    den = sum(r.total_surplus for r in reps)
    assert pooled == pytest.approx(num / den)
    assert cs.pooled_capture_share([]) is None
    assert cs.pooled_capture_share([None]) is None


def test_agent_id_out_of_range_is_rejected():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=0)
    with pytest.raises(ValueError):
        cs.episode_capture(world, world.allocation, agent_id=0)
    with pytest.raises(ValueError):
        cs.episode_capture(world, world.allocation, agent_id=4)
