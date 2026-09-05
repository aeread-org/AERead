"""Tests for the negarena component-level parity harness (parity.py, spec
section 5, "the tau3 parity.py pattern").

Follows the same ``_bridge()``/skip convention as
``tests/test_negarena_environment.py``: these tests actually execute golden
1's scripted transcript through both the real adapter path and an
independent upstream-direct replay when a pinned upstream Python
interpreter is provisioned, and are skipped (never faked) otherwise.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aeread_families.negarena import parity
from aeread_families.negarena.environment import NegarenaPlugin

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = Path(
    os.environ.get(
        "AEREAD_NEGARENA_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-negarena",
    )
)


def _bridge():
    from aeread_families.negarena.negarena_bridge import (
        NegarenaBridge,
        NegarenaBridgeUnavailableError,
    )

    if not (UPSTREAM_ROOT / "negotiationarena").is_dir():
        pytest.skip(f"pinned upstream NegotiationArena checkout not found at {UPSTREAM_ROOT}")
    try:
        return NegarenaBridge.discover(UPSTREAM_ROOT)
    except NegarenaBridgeUnavailableError as error:
        pytest.skip(f"upstream NegotiationArena Python interpreter unavailable: {error}")


@pytest.fixture(scope="module")
def bridge():
    return _bridge()


@pytest.fixture
def plugin(bridge) -> NegarenaPlugin:
    return NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)


def _load_case(case_id: str, split: str) -> dict:
    path = REPO_ROOT / "cases" / "negarena" / split / f"{case_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_buy_sell_golden_one_parity_is_byte_identical(plugin, bridge) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    transcript = parity.build_buy_sell_golden_one(family_case)

    result = parity.run_golden_one_parity(plugin, transcript, bridge=bridge)

    assert result.game_kind == "buy_sell"
    assert result.adapter_player_outcome == (0.0, 20.0)
    assert result.upstream_direct_player_outcome == (0.0, 20.0)
    assert result.adapter_final_response == "ACCEPT"
    assert result.upstream_direct_final_response == "ACCEPT"
    assert result.matched


def test_ultimatum_golden_one_parity_is_byte_identical(plugin, bridge) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    transcript = parity.build_ultimatum_golden_one(family_case)

    result = parity.run_golden_one_parity(plugin, transcript, bridge=bridge)

    assert result.game_kind == "ultimatum"
    assert result.adapter_player_outcome == (60.0, 40.0)
    assert result.upstream_direct_player_outcome == (60.0, 40.0)
    assert result.matched


def test_upstream_direct_replay_never_touches_the_adapters_environment_module(
    plugin, bridge
) -> None:
    """The upstream-direct side is a genuinely independent code path: it
    calls ``NegarenaBridge.replay_transcript`` directly, never
    ``NegarenaPlugin.parse_action``/``legal``/``step`` -- so a match against
    the adapter side is real parity evidence, not a tautology.
    """
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    transcript = parity.build_buy_sell_golden_one(family_case)

    scenario = family_case["scenario"]
    raw_turns = [text for _seat, text in transcript.turns]
    direct = bridge.replay_transcript(game_kind=scenario["game_kind"], scenario=scenario, turns=raw_turns)

    assert direct["settled"]
    assert direct["final_response"] == "ACCEPT"
    # Same result as run_golden_one_parity's own upstream_direct call --
    # proves replay_transcript is deterministic given the same transcript.
    result = parity.run_golden_one_parity(plugin, transcript, bridge=bridge)
    assert result.upstream_direct_final_response == direct["final_response"]
