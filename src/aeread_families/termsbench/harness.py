"""Provider-free scripted response source for termsbench integration tests.

Supplies **both** seats without any LLM call (spec section 3):

* ``agent`` -- a fixed script, one response per ``agent_turn`` call, for
  hand-derived goldens.
* ``counterpart`` -- the real stochastic kernel (``kernel.resolve_counterpart_turn``),
  drawing fresh random numbers from a per-``(world_seed, round)`` seeded
  generator and returning both the resolved decision and the raw draws it
  consumed, so that ``TermsBenchPlugin.step`` can independently recompute and
  verify the same decision from the sealed draws rather than trusting the
  harness (spec section 3.1/5).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from . import kernel as k

_SENTIMENT_TONE: Mapping[str, str] = {
    "positive": "glad we're making progress",
    "neutral": "here is where things stand",
    "negative": "frankly, this is difficult",
}
_POSTURE_PHRASE: Mapping[str, str] = {
    "Concede": "I can move a bit further to close this",
    "Hold": "I'll hold near this level",
    "Pressure": "time is running short on this",
}


def render_counterpart_message(decision: "k.CounterpartDecision") -> str:
    """Deterministic natural-language template, never an LLM (App. C.5.4)."""
    if decision.resolved == "accept":
        return "I accept your offer."
    if decision.resolved == "reject":
        return "I'm walking away from this negotiation."
    if decision.resolved == "timeout":
        return ""
    tone = _SENTIMENT_TONE[decision.sentiment_cue]
    posture = _POSTURE_PHRASE[decision.strategic_cue]
    return f"{tone.capitalize()}: I offer {decision.price:.2f}. {posture}."


def _draw_randoms(rng: np.random.Generator) -> dict[str, float]:
    """Draw a fixed set of raw random numbers, in a fixed order, every
    invocation -- regardless of which branch ``resolve_counterpart_turn``
    ends up taking. Simpler and more robust than conditionally drawing only
    "the ones that will be needed", and harmless: unused entries are ignored
    by ``kernel.resolve_counterpart_turn``.
    """
    return {
        "u_accept": float(rng.uniform(0.0, 1.0)),
        "u_walkaway": float(rng.uniform(0.0, 1.0)),
        "opening_noise": float(rng.normal(0.0, 1.0)),
        "price_noise": float(rng.normal(0.0, 1.0)),
        "sentiment_noise": float(rng.normal(0.0, 1.0)),
        "posture_u": float(rng.uniform(0.0, 1.0)),
    }


def _rng_for_round(world_seed: int, round_k: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([world_seed, round_k])))


class ScriptedTermsBenchHarness:
    """Serve a fixed agent script and the real counterpart kernel.

    ``script`` is an ordered sequence of raw agent responses, one per
    ``agent_turn`` request (e.g. ``{"decision": "offer", "price": 110.0,
    "message": "..."}``). The counterpart side needs no script: it is
    computed fresh every ``counterpart_turn`` request from ``kernel.py``,
    using a per-``(world_seed, round)`` seeded stream unless
    ``counterpart_draws_by_round`` pins specific raw draws for that round
    (e.g. to hit a hand-derived golden's exact ``u_accept`` exactly, while
    still running the real formula so ``step()``'s replay-and-verify passes
    naturally rather than being bypassed).
    """

    def __init__(
        self,
        *,
        world_seed: int,
        script: Sequence[Mapping[str, Any]],
        counterpart_draws_by_round: Mapping[int, Mapping[str, float]] | None = None,
    ):
        self.world_seed = world_seed
        self._script = list(script)
        self._agent_cursor = 0
        self._draws_override = dict(counterpart_draws_by_round or {})
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if request.phase_id == "agent_turn":
            if self._agent_cursor >= len(self._script):
                raise RuntimeError("agent script exhausted before episode termination")
            response = self._script[self._agent_cursor]
            self._agent_cursor += 1
            return dict(response)
        if request.phase_id == "counterpart_turn":
            return self._resolve_counterpart(request.observation)
        raise RuntimeError(f"unknown phase_id: {request.phase_id!r}")

    def _resolve_counterpart(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        round_k = observation["round"]
        override = self._draws_override.get(round_k)
        if override is not None:
            draws = dict(_draw_randoms(_rng_for_round(self.world_seed, round_k)))
            draws.update(override)
        else:
            draws = _draw_randoms(_rng_for_round(self.world_seed, round_k))
        decision = k.resolve_counterpart_turn(
            round_k=round_k,
            horizon=observation["horizon"],
            family=observation["family"],
            agent_role=observation["agent_role"],
            counterpart_role=observation["counterpart_role"],
            r_b=float(observation["t_b"]["r_b"]),
            kappa_b=float(observation["t_b"]["kappa_b"]),
            eta_b=observation["t_b"]["eta_b"],
            p_min=float(observation["price_bounds"]["p_min"]),
            p_max=float(observation["price_bounds"]["p_max"]),
            opening_harshness=float(observation["opening_harshness"]),
            agent_offers=tuple(observation["agent_offers"]),
            counterpart_offers=tuple(observation["counterpart_offers"]),
            draws=draws,
        )
        return {
            "resolved": decision.resolved,
            "price": decision.price,
            "sentiment_cue": decision.sentiment_cue,
            "strategic_cue": decision.strategic_cue,
            "message": render_counterpart_message(decision),
            "round": round_k,
            "draws": draws,
        }

    @property
    def exhausted(self) -> bool:
        return self._agent_cursor == len(self._script)


__all__ = [
    "ScriptedTermsBenchHarness",
    "render_counterpart_message",
]
