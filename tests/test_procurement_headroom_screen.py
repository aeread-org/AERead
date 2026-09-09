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


# --- continuous scoring ------------------------------------------------------
#
# Defect 21: award feasibility is a threshold on regret, and thresholding
# discarded the only dispersion the noisy panel had. These cover the continuous
# rule that replaces it.

from aeread_families.procurement_allocation.headroom_screen import (  # noqa: E402
    DEGENERATE,
    classify_world_continuous,
)

LOSE_ALL_SCORES = {policy: 90.0 for policy in SCREEN_BASELINES}


def test_identical_control_scores_are_degenerate() -> None:
    """Zero dispersion subsumes floored and saturated: nothing can be moved."""
    assert (
        classify_world_continuous([12.0, 12.0, 12.0], LOSE_ALL_SCORES) == DEGENERATE
    )


def test_a_baseline_matching_the_control_best_is_trivial() -> None:
    """Verification buys nothing if a public-observation policy already ties it."""
    scores = dict(LOSE_ALL_SCORES) | {SCREEN_BASELINES[0]: 8.0}
    assert classify_world_continuous([8.0, 19.0, 20.0], scores) == TRIVIAL


def test_dispersed_control_beating_every_baseline_is_admitted() -> None:
    assert classify_world_continuous([8.0, 19.0, 20.0], LOSE_ALL_SCORES) == ADMIT


def test_continuous_screen_needs_several_seeds() -> None:
    assert classify_world_continuous([8.0], LOSE_ALL_SCORES) == UNMEASURED


def test_continuous_screen_rejects_when_no_baseline_scored() -> None:
    unmeasured = {policy: None for policy in SCREEN_BASELINES}
    assert classify_world_continuous([8.0, 19.0, 20.0], unmeasured) == UNMEASURED


def test_higher_is_better_metrics_are_supported() -> None:
    """Margin rather than regret: the same rule with the comparison flipped."""
    baselines = {policy: 10.0 for policy in SCREEN_BASELINES}
    assert (
        classify_world_continuous([50.0, 60.0], baselines, lower_is_better=False)
        == UNMEASURED
    )
    assert (
        classify_world_continuous([50.0, 60.0, 70.0], baselines, lower_is_better=False)
        == ADMIT
    )
    beating = {policy: 99.0 for policy in SCREEN_BASELINES}
    assert (
        classify_world_continuous([50.0, 60.0, 70.0], beating, lower_is_better=False)
        == TRIVIAL
    )


def test_variance_is_computed_on_real_numbers_not_just_booleans() -> None:
    """The screen reports dispersion for continuous scores too."""
    assert within_world_variance([8.04, 8.04, 8.04]) == 0.0
    assert within_world_variance([18.32, 29.32, 18.87, 20.85]) > 0.0


# --- dispersion must be material -------------------------------------------
#
# Two worlds were admitted on a $0.25 spread and a $0.35 margin against a $269
# baseline. The control failed at every seed there and differed only in what it
# spent on information, so "not all identical" admitted a world with no headroom.


def test_a_sub_material_spread_is_degenerate() -> None:
    """The measured case: control fails every seed, spends slightly differently."""
    baselines = {policy: 269.07 for policy in SCREEN_BASELINES}
    assert (
        classify_world_continuous([268.72, 268.97, 268.80, 268.91], baselines)
        == DEGENERATE
    )


def test_a_sub_material_margin_over_the_baseline_is_trivial() -> None:
    """Beating a public-observation policy by a rounding error is not beating it.

    The spread here is large, so this isolates the margin test: the control
    varies a lot but its *best* barely improves on a policy that reads only the
    public listing.
    """
    baselines = {policy: 201.0 for policy in SCREEN_BASELINES}
    assert classify_world_continuous([200.0, 269.0, 240.0], baselines) == TRIVIAL


def test_a_material_spread_and_margin_is_admitted() -> None:
    """The two worlds that genuinely separated, at their measured values."""
    baselines = {policy: 267.88 for policy in SCREEN_BASELINES}
    assert classify_world_continuous([1.88, 267.88, 130.0], baselines) == ADMIT


def test_materiality_is_relative_not_absolute() -> None:
    """A small-stakes world is judged on its own scale, not a fixed dollar cut."""
    baselines = {policy: 10.0 for policy in SCREEN_BASELINES}
    assert classify_world_continuous([0.1, 5.0, 9.0], baselines) == ADMIT
    tiny = {policy: 0.5 for policy in SCREEN_BASELINES}
    assert classify_world_continuous([0.40, 0.42, 0.44], tiny) == DEGENERATE


def test_the_threshold_is_declarable() -> None:
    baselines = {policy: 100.0 for policy in SCREEN_BASELINES}
    scores = [70.0, 78.0, 74.0]
    assert classify_world_continuous(scores, baselines, minimum_relative_spread=0.05) == ADMIT
    assert (
        classify_world_continuous(scores, baselines, minimum_relative_spread=0.30)
        == DEGENERATE
    )
