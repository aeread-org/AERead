"""Tests for the structured, LLM-free 2-agent RL wrapper (sprint/exchange_v1/rl_env.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread.exchange_v1 import economy as ex  # noqa: E402
from aeread.exchange_v1 import rl_env as rl  # noqa: E402

CONFIG_PATH = ROOT / "configs" / "exchange_economy" / "baselines/rl_bilateral_2agent.json"


def _deterministic_world() -> ex.ExchangeWorld:
    """Agent 1 holds resource 1, agent 2 holds resource 2; each prefers the other's good."""
    return ex.ExchangeWorld(
        allocation=[[10, 0], [0, 10]],
        preferences=[[1.0, 3.0], [3.0, 1.0]],
        utility_mode="linear",
    )


def _make_env(rounds: int = 6) -> rl.BilateralNegotiationEnv:
    env = rl.BilateralNegotiationEnv(CONFIG_PATH)
    env.reset()
    env.world = _deterministic_world()
    env.config = ex.replace(env.config, rounds=rounds)
    env.history = []
    env.round_index = 1
    env._pending_offer = None
    return env


def test_config_loads_as_2_agent_atomic_commit():
    config = ex.load_experiment_config(CONFIG_PATH)
    assert config.num_agents == 2
    assert config.protocol.atomic_commit is True
    assert config.protocol.private_acceptance_check is False


def test_propose_alone_does_not_move_resources_or_pay_reward():
    env = _make_env()
    obs, reward, done, info = env.step(1, rl.StructuredAction("propose", give={1: 2}, get={2: 2}))

    assert env.world.allocation == [[10, 0], [0, 10]]
    assert reward == 0.0
    assert info["applied"] is False
    assert done is False


def test_propose_then_accept_executes_mutually_beneficial_trade():
    env = _make_env()
    env.step(1, rl.StructuredAction("propose", give={1: 2}, get={2: 2}))
    obs, reward, done, info = env.step(2, rl.StructuredAction("accept"))

    assert env.world.allocation == [[8, 2], [2, 8]]
    assert info["applied"] is True
    assert info["individually_rational"] is True
    # agent1: before 1*10+3*0=10, after 1*8+3*2=14 -> +4
    assert reward == pytest.approx(4.0)
    # agent2 (counterpart) got the symmetric gain in this hand-built example
    assert info["counterpart_reward"] == pytest.approx(4.0)


def test_propose_then_reject_leaves_state_unchanged():
    env = _make_env()
    env.step(1, rl.StructuredAction("propose", give={1: 2}, get={2: 2}))
    obs, reward, done, info = env.step(2, rl.StructuredAction("reject"))

    assert env.world.allocation == [[10, 0], [0, 10]]
    assert reward == 0.0
    assert info["applied"] is False

    # a stale accept after the offer was rejected/cleared is a no-op, not a crash
    obs, reward, done, info = env.step(1, rl.StructuredAction("no_op"))
    obs, reward, done, info = env.step(2, rl.StructuredAction("accept"))
    assert env.world.allocation == [[10, 0], [0, 10]]
    assert reward == 0.0


def test_no_op_round_is_a_true_pass():
    env = _make_env()
    obs, reward, done, info = env.step(1, rl.StructuredAction("no_op"))

    assert env.world.allocation == [[10, 0], [0, 10]]
    assert reward == 0.0
    assert info["applied"] is False


def test_infeasible_propose_clamps_instead_of_crashing():
    env = _make_env()
    # agent 1 only holds 10 units of resource 1; asking to give 999 must not raise
    obs, reward, done, info = env.step(1, rl.StructuredAction("propose", give={1: 999}, get={2: 2}))
    assert info["warnings"]
    obs, reward, done, info = env.step(2, rl.StructuredAction("accept"))
    # clamped give leg == 10 (all of agent1's resource 1)
    assert env.world.allocation == [[0, 2], [10, 8]]


def test_episode_terminates_at_configured_round_count_and_reset_clears_state():
    env = _make_env(rounds=2)
    _, _, done1, _ = env.step(1, rl.StructuredAction("no_op"))
    assert done1 is False
    _, _, done2, _ = env.step(2, rl.StructuredAction("no_op"))
    assert done2 is True

    with pytest.raises(RuntimeError):
        env.step(1, rl.StructuredAction("no_op"))

    obs = env.reset()
    assert env.round_index == 1
    assert env.history == []
    assert set(obs) == {1, 2}


def test_reward_sum_matches_final_minus_initial_utility_over_a_trajectory():
    env = _make_env(rounds=10)
    world = env.world
    initial_u1 = world.utility(1)
    initial_u2 = world.utility(2)

    env.step(1, rl.StructuredAction("propose", give={1: 3}, get={2: 1}))
    _, reward2, _, info = env.step(2, rl.StructuredAction("accept"))
    reward1 = info["counterpart_reward"]  # agent 1's realized delta on the same accept step

    final_u1 = world.utility(1)
    final_u2 = world.utility(2)

    assert reward1 == pytest.approx(final_u1 - initial_u1)
    assert reward2 == pytest.approx(final_u2 - initial_u2)
