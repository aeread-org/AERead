"""Reliability is the share of a comparison that recurs, checked against planted variance."""

from __future__ import annotations

import numpy as np
import pytest

from aeread.design import reliability, sign_agreement, variance_components, worlds_for_reliability

PLANTED = {"var_model": 4.0, "var_world": 9.0, "var_world_model": 2.0, "var_play": 6.0}


def draw(rng: np.random.Generator, model_effect: np.ndarray, worlds: int, plays: int) -> np.ndarray:
    """One run of the design: fresh worlds and plays, the same models."""

    models = len(model_effect)
    world = rng.normal(0.0, np.sqrt(PLANTED["var_world"]), size=(worlds, 1, 1))
    interaction = rng.normal(0.0, np.sqrt(PLANTED["var_world_model"]), size=(worlds, models, 1))
    play = rng.normal(0.0, np.sqrt(PLANTED["var_play"]), size=(worlds, models, plays))
    return 50.0 + model_effect[None, :, None] + world + interaction + play


def test_planted_variance_shares_are_recovered() -> None:
    rng = np.random.default_rng(20261013)
    effect = rng.normal(0.0, np.sqrt(PLANTED["var_model"]), size=150)
    found = variance_components(draw(rng, effect, worlds=300, plays=3))
    assert (found["worlds"], found["models"], found["plays"]) == (300, 150, 3)
    for name, planted in PLANTED.items():
        assert found[name] == pytest.approx(planted, rel=0.2), name


def test_reliability_is_the_agreement_of_two_independent_runs() -> None:
    rng = np.random.default_rng(7)
    effect = rng.normal(0.0, np.sqrt(PLANTED["var_model"]), size=400)
    for worlds, plays in ((4, 1), (12, 2), (40, 3)):
        agreement = np.mean([
            np.corrcoef(draw(rng, effect, worlds, plays).mean(axis=(0, 2)), draw(rng, effect, worlds, plays).mean(axis=(0, 2)))[0, 1]
            for _ in range(20)
        ])
        # these 400 models are the population the two runs share, so their own spread is the model variance
        stated = reliability(float(np.var(effect, ddof=1)), PLANTED["var_world_model"], PLANTED["var_play"], worlds=worlds, plays=plays)
        assert agreement == pytest.approx(stated, abs=0.03), (worlds, plays)


def test_a_worlds_own_level_is_not_error() -> None:
    rng = np.random.default_rng(3)
    scores = draw(rng, rng.normal(0.0, 2.0, size=60), worlds=80, plays=2)
    shifted = scores + rng.normal(0.0, 100.0, size=(80, 1, 1))     # make some worlds far easier, for every model alike
    a, b = variance_components(scores), variance_components(shifted)
    assert b["var_world"] > 100 * a["var_world"]
    for name in ("var_model", "var_world_model", "var_play"):
        assert b[name] == pytest.approx(a[name], rel=1e-6), name


def test_one_value_per_cell_cannot_separate_interaction_from_play_noise() -> None:
    rng = np.random.default_rng(11)
    scores = draw(rng, rng.normal(0.0, 2.0, size=120), worlds=250, plays=1)[:, :, 0]
    found = variance_components(scores)
    assert found["var_play"] is None and found["plays"] == 1
    assert found["var_world_model"] == pytest.approx(PLANTED["var_world_model"] + PLANTED["var_play"], rel=0.1)
    assert reliability(found["var_model"], found["var_world_model"], None, worlds=250) == pytest.approx(
        reliability(found["var_model"], found["var_world_model"], 0.0, worlds=250)
    )


def test_the_decision_study_gives_the_smallest_design_that_reaches_the_target() -> None:
    parts = (PLANTED["var_model"], PLANTED["var_world_model"], PLANTED["var_play"])
    for target, plays in ((0.8, 1), (0.9, 2), (0.95, 5)):
        worlds = worlds_for_reliability(target, *parts, plays=plays)
        assert reliability(*parts, worlds=worlds, plays=plays) >= target
        assert worlds == 1 or reliability(*parts, worlds=worlds - 1, plays=plays) < target
    assert worlds_for_reliability(0.9, *parts, plays=4) < worlds_for_reliability(0.9, *parts, plays=1)   # repeats help, but
    assert worlds_for_reliability(0.9, *parts, plays=10_000) >= 0.9 / 0.1 * PLANTED["var_world_model"] / PLANTED["var_model"] - 1e-9  # not past this floor


def test_two_runs_agree_on_a_pairs_order_by_chance_when_there_is_no_gap() -> None:
    assert sign_agreement(0.0, 10.0, 50) == pytest.approx(0.5)
    assert sign_agreement(5.0, 10.0, 4) == sign_agreement(-5.0, 10.0, 4)
    assert sign_agreement(5.0, 10.0, 4) < sign_agreement(5.0, 10.0, 40) < 1.0
    assert sign_agreement(50.0, 10.0, 40) == pytest.approx(1.0)


def test_inputs_that_cannot_be_split_are_refused() -> None:
    with pytest.raises(ValueError, match="drop incomplete worlds"):
        variance_components([[1.0, float("nan")], [2.0, 3.0]])
    with pytest.raises(ValueError, match="worlds x models"):
        variance_components([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="at least 2 worlds and 2 models"):
        variance_components([[1.0, 2.0]])
    with pytest.raises(ValueError, match="no model variance"):
        worlds_for_reliability(0.9, 0.0, 2.0)
    with pytest.raises(ValueError, match="strictly between"):
        worlds_for_reliability(1.0, 4.0, 2.0)
