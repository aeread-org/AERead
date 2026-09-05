"""Provider-free scripted-policy response source for ``collusion`` integration
tests (spec section 3: "the four scripted policies -- constant,
tit-for-tat-style, Nash-play, monopoly-play -- none paper-specified").

Every policy here is a pure function ``observation -> price``: no model
call, no randomness, no wall clock -- exactly the "scripted/gold trajectory"
requirement this milestone is built under. ``ScriptedCollusionHarness``
binds one policy per seat and serves it as the real scheduler's own
``ResponseSource`` (``aeread.shared_runner.task.scheduler.run_episode``), so a
harness-driven episode exercises the identical phase graph, simultaneous
peer-hiding, and legality gate that milestone 1's ``test_collusion_
environment.py`` exercised directly with inline ``respond`` closures -- this
module simply gives that same convention a reusable, named shape, the same
way ``tau3_retail.harness.ScriptedTau3RetailHarness`` formalizes tau3's own
inline-script convention.

Unlike ``ScriptedTau3RetailHarness``, this family declares
``needs_tools=False`` (``environment.py``'s ``family_manifest``): there is
no ``ToolRuntime`` to delegate to and no upstream database to re-verify
against. The ``EvidenceStore`` wired into ``ScriptedCollusionHarness`` is
therefore not a tool-replay cross-check (nothing plays that role for this
family -- ``economics.py``'s ``step()`` is pure closed-form arithmetic, not
a delegated call); it is this harness's own tamper-evident record that a
genuine, deterministic decision -- never a placeholder -- was served for
every logical action of the episode it drove, sealed with ``EvidenceStore.
seal()`` once the episode terminates (spec section 3, milestone 3's own
"sealed evidence" requirement).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from aeread.shared_runner.task.execution import EvidenceSeal, EvidenceStore

_SEATS = ("firm_a", "firm_b")

PolicyFn = Callable[[Mapping[str, Any]], float]
"""One seat's pricing policy: this seat's own current observation (spec
section 3's ``collusion_price_round_observation_v1`` shape, i.e.
``environment.py``'s ``observe()`` return value) to its next round's price.
"""

# Named, versioned policy identities (spec section 1's case-manifest note:
# scripted policies are AERead's own, never paper-specified). Nash-play's id
# intentionally matches ``measurement.BASELINE_POLICY_ID`` -- it *is* the
# same named baseline leaf 4 compares against, not a separate policy that
# happens to reproduce the same price by coincidence.
POLICY_ID_CONSTANT = "collusion_constant_v1"
POLICY_ID_TIT_FOR_TAT = "collusion_tit_for_tat_v1"
POLICY_ID_NASH_PLAY = "collusion_nash_play_baseline_v1"
POLICY_ID_MONOPOLY_PLAY = "collusion_monopoly_play_v1"


def constant_policy(price: float) -> PolicyFn:
    """Submit the same fixed price every round, regardless of history."""

    def policy(observation: Mapping[str, Any]) -> float:
        del observation
        return price

    return policy


def nash_play_policy(p_nash: float) -> PolicyFn:
    """The named baseline (``POLICY_ID_NASH_PLAY`` ==
    ``measurement.BASELINE_POLICY_ID``): play the paper's own closed-form
    Bertrand-Nash price every round. Mechanically a constant policy at one
    particular, paper-derived price -- named separately because it is
    leaf 4's fixed comparison baseline (spec section 2), not an arbitrary
    constant.
    """
    return constant_policy(p_nash)


def monopoly_play_policy(p_monopoly: float) -> PolicyFn:
    """Play the paper's own closed-form joint-monopoly price every round."""
    return constant_policy(p_monopoly)


def tit_for_tat_policy(*, seat_id: str, opening_price: float) -> PolicyFn:
    """AERead-authored reward-punishment probe (spec section 3: "AERead-
    authored probes inspired by the reward-punishment literature the paper
    itself cites in §4"): open with ``opening_price`` on round 0 (no
    history exists yet), then mirror the opponent's most recently observed
    price every later round.
    """
    if seat_id not in _SEATS:
        raise ValueError(f"seat_id must be one of {_SEATS}, got {seat_id!r}")
    opponent_seat = "firm_b" if seat_id == "firm_a" else "firm_a"

    def policy(observation: Mapping[str, Any]) -> float:
        history = observation["price_history"]
        if not history:
            return opening_price
        return history[-1]["prices"][opponent_seat]

    return policy


class ScriptedCollusionHarness:
    """Serve one deterministic pricing policy per seat through the real
    scheduler, and seal evidence of every decision served.

    ``policy_by_seat`` binds every seat (``firm_a``, ``firm_b``) to one
    :data:`PolicyFn`. Every time ``run_episode`` requests a price for a
    seat, this harness reads that seat's own frozen observation (never the
    peer's -- the scheduler's own simultaneous-phase freezing already
    enforces that, spec section 3), applies its policy, records the served
    decision as one evidence event, and returns ``{"price": price}``. Call
    :meth:`seal` once the episode terminates to commit the durable
    ``EvidenceSeal`` (module docstring).
    """

    def __init__(
        self,
        *,
        policy_by_seat: Mapping[str, PolicyFn],
        evidence: EvidenceStore,
    ) -> None:
        if set(policy_by_seat) != set(_SEATS):
            raise ValueError(f"policy_by_seat must declare exactly {_SEATS}")
        self._policy_by_seat = dict(policy_by_seat)
        self.evidence = evidence
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        policy = self._policy_by_seat[request.seat_id]
        price = policy(request.observation)
        self.evidence.append_event(
            "collusion_price_submitted",
            {
                "seat_id": request.seat_id,
                "round": request.observation["round"],
                "price": price,
            },
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        return {"price": price}

    def seal(self) -> EvidenceSeal:
        """Commit this harness's own recorded decision trail (module
        docstring's "sealed evidence" requirement)."""
        return self.evidence.seal()


__all__ = [
    "POLICY_ID_CONSTANT",
    "POLICY_ID_MONOPOLY_PLAY",
    "POLICY_ID_NASH_PLAY",
    "POLICY_ID_TIT_FOR_TAT",
    "PolicyFn",
    "ScriptedCollusionHarness",
    "constant_policy",
    "monopoly_play_policy",
    "nash_play_policy",
    "tit_for_tat_policy",
]
