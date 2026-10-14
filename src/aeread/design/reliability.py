"""Reliability of a model comparison: how much of what a campaign reports would recur.

A campaign scores every model on the same worlds, with one or more plays of
each. Its model means differ for two reasons: the models differ, and this draw
of worlds and plays happened to favour some of them. Reliability is the share
that is the models: the expected correlation between the model means of two
independent runs of the same design, each on its own draw of worlds and plays
(a generalizability coefficient with models as the object of measurement and
worlds and plays as error).

A world's own level is not error here. Every model meets the same worlds, so
an easy or a hard world moves all of them alike and cancels in any comparison.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats


def variance_components(scores: Any) -> dict[str, Any]:
    """Split scores into model, world, world-by-model and play variance.

    ``scores`` is worlds x models, one value per cell, or worlds x models x
    plays. Every cell must be present: drop a world that is missing a model
    before calling. With one value per cell the world-by-model term cannot be
    told from play noise, so ``var_world_model`` holds both and ``var_play`` is
    ``None``. A negative estimate is reported as zero.
    """

    x = np.asarray(scores, dtype=float)
    if x.ndim not in (2, 3):
        raise ValueError("scores must be worlds x models or worlds x models x plays")
    if not np.isfinite(x).all():
        raise ValueError("every cell must be present and finite; drop incomplete worlds first")
    n_w, n_m = x.shape[0], x.shape[1]
    n_p = x.shape[2] if x.ndim == 3 else 1
    if n_w < 2 or n_m < 2:
        raise ValueError("at least 2 worlds and 2 models are needed")
    cell = x.mean(axis=2) if x.ndim == 3 else x
    grand = float(cell.mean())
    world_mean, model_mean = cell.mean(axis=1), cell.mean(axis=0)
    ms_world = n_m * n_p * float(((world_mean - grand) ** 2).sum()) / (n_w - 1)
    ms_model = n_w * n_p * float(((model_mean - grand) ** 2).sum()) / (n_m - 1)
    residual = cell - world_mean[:, None] - model_mean[None, :] + grand
    ms_interaction = n_p * float((residual**2).sum()) / ((n_w - 1) * (n_m - 1))
    if n_p > 1:
        var_play: float | None = float(((x - cell[:, :, None]) ** 2).sum()) / (n_w * n_m * (n_p - 1))
        var_world_model = max(0.0, (ms_interaction - var_play) / n_p)
    else:
        var_play = None
        var_world_model = ms_interaction
    return {
        "worlds": n_w,
        "models": n_m,
        "plays": n_p,
        "var_model": max(0.0, (ms_model - ms_interaction) / (n_w * n_p)),
        "var_world": max(0.0, (ms_world - ms_interaction) / (n_m * n_p)),
        "var_world_model": var_world_model,
        "var_play": var_play,
    }


def _error_per_world(var_world_model: float, var_play: float | None, plays: int) -> float:
    if plays < 1:
        raise ValueError("plays must be at least 1")
    play = 0.0 if var_play is None else float(var_play)
    if var_world_model < 0 or play < 0:
        raise ValueError("variances cannot be negative")
    return float(var_world_model) + play / plays


def reliability(
    var_model: float,
    var_world_model: float,
    var_play: float | None = None,
    *,
    worlds: int,
    plays: int = 1,
) -> float:
    """Reliability of the model means of a design with this many worlds and plays.

    ``var_model / (var_model + var_world_model / worlds + var_play / (worlds * plays))``.
    Pass ``var_play=None`` when the components came from one value per cell.
    """

    if worlds < 1:
        raise ValueError("worlds must be at least 1")
    if var_model < 0:
        raise ValueError("variances cannot be negative")
    error = _error_per_world(var_world_model, var_play, plays) / worlds
    total = float(var_model) + error
    return float(var_model) / total if total > 0 else float("nan")


def worlds_for_reliability(
    target: float,
    var_model: float,
    var_world_model: float,
    var_play: float | None = None,
    *,
    plays: int = 1,
) -> int:
    """Smallest number of worlds whose model means reach ``target`` reliability."""

    if not 0 < target < 1:
        raise ValueError("target must lie strictly between 0 and 1")
    if var_model <= 0:
        raise ValueError("no model variance was found, so no number of worlds reaches the target")
    needed = target / (1 - target) * _error_per_world(var_world_model, var_play, plays) / float(var_model)
    return max(1, math.ceil(needed - 1e-12))


def sign_agreement(gap: float, sd_of_differences: float, worlds: int) -> float:
    """Chance that two independent runs of the design put one pair of models in the same order.

    For a single pair the ranking is the sign of the paired gap. Each run's
    estimate is the true gap plus normal error of ``sd / sqrt(worlds)``.
    """

    if worlds < 1 or sd_of_differences <= 0:
        raise ValueError("worlds must be at least 1 and sd_of_differences positive")
    right = float(stats.norm.cdf(abs(gap) * math.sqrt(worlds) / sd_of_differences))
    return right**2 + (1 - right) ** 2
