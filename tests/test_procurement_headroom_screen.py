"""The Gate 1 screen must reject on three grounds, not on policy disagreement.

Each test below corresponds to a failure that actually happened and is recorded
in docs/operations/incident_log.md. They are regression tests in the strict
sense: every one of them fails against the version of the screen that shipped
the defect it names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread_families.procurement_allocation.headroom_screen import (
    ADMIT,
    FLOORED,
    SATURATED,
    SCREEN_BASELINES,
    TRIVIAL,
    UNMEASURED,
    classify_world,
    replay_baseline,
    screen_baselines,
    within_world_variance,
)

PANEL = (
    Path(__file__).resolve().parents[1]
    / "cases"
    / "procurement_allocation_v1"
    / "duediligence_v1"
    / "labeled"
)
LOSE_ALL = {policy: False for policy in SCREEN_BASELINES}


def test_saturated_world_is_rejected_even_though_baselines_lose() -> None:
    """J-07: the disagreement rule admitted exactly this shape.

    The control wins every seed and every baseline loses, so the two policies
    disagree. They also leave a treatment no room to improve, which is the
    saturation of J-01 and defect 14. Disagreement is not sufficient.
    """
    assert classify_world([True, True, True, True], LOSE_ALL) == SATURATED


def test_floored_world_is_rejected() -> None:
    """D-16: a control-only screen passes this world because the control fails."""
    assert classify_world([False, False, False], LOSE_ALL) == FLOORED


def test_trivial_world_is_rejected_before_the_control_rate_is_consulted() -> None:
    """A public-observation policy already wins, so verification is not tested.

    Triviality is checked first: a healthy-looking control rate must not rescue
    a world whose subject is absent.
    """
    winning = dict(LOSE_ALL) | {SCREEN_BASELINES[0]: True}
    assert classify_world([True, False, True], winning) == TRIVIAL


def test_interior_control_rate_with_losing_baselines_is_admitted() -> None:
    assert classify_world([True, False, True], LOSE_ALL) == ADMIT


def test_single_seed_cannot_admit() -> None:
    """One seed cannot separate a ceiling from a lucky draw."""
    assert classify_world([True], LOSE_ALL) == UNMEASURED
    assert classify_world([False], LOSE_ALL) == UNMEASURED


def test_baselines_that_never_terminate_reject_rather_than_admit() -> None:
    """J-06: a screen that cannot run its own test must not admit on that basis."""
    unmeasured = {policy: None for policy in SCREEN_BASELINES}
    assert classify_world([True, False, True], unmeasured) == UNMEASURED


def test_zero_within_world_variance_is_visible() -> None:
    """D-18: seeds that always agree are repeats, and the screen must show it."""
    assert within_world_variance([True, True, True, True]) == 0.0
    assert within_world_variance([False, False, False]) == 0.0
    assert within_world_variance([True, False, True, False]) > 0.0


@pytest.mark.parametrize("policy_id", SCREEN_BASELINES)
def test_every_baseline_actually_plays_a_world(policy_id: str) -> None:
    """J-06: the screen once scored a TypeError as a loss in every world.

    A baseline must reach a terminal state and return a bool. Returning ``None``
    everywhere is indistinguishable from a crashed policy at the call site, so
    this asserts the stronger property directly on a real case.
    """
    payload = json.loads(
        sorted(PANEL.glob("*.json"))[0].read_text(encoding="utf-8")
    )["payload"]
    assert isinstance(replay_baseline(payload, policy_id), bool)


def test_screen_baselines_covers_every_declared_policy() -> None:
    payload = json.loads(
        sorted(PANEL.glob("*.json"))[0].read_text(encoding="utf-8")
    )["payload"]
    outcomes = screen_baselines(payload)
    assert set(outcomes) == set(SCREEN_BASELINES)
    assert all(isinstance(value, bool) for value in outcomes.values())
