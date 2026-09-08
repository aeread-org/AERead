"""Provider-free scripted policies + response source for alympics.wac (milestone 3).

Mirrors ``tau3_retail``'s ``ScriptedTau3RetailHarness`` (``harness.py``): a
response source class that serves fixed, deterministic actions in place of a
live model call, so a complete episode can be driven through the *real*
``run_episode`` scheduler path with zero network calls, zero API keys, and
zero LLM calls. The shape here is simpler than tau3.retail's own harness for
one declared reason: this family's ``family_manifest`` declares
``needs_tools: False`` (``environment.py``) -- there is no ``ToolRuntime`` to
delegate through, because every seat's only action is a single integer bid,
settled entirely by upstream's own, already-imported ``waterAllocation``
mechanics inside ``environment.step`` (spec section 3). What tau3.retail's
harness records as delegated tool-call evidence, this harness instead
records as one sealed event per bid it serves -- the only externally
observable "thing a live provider would have produced" this family has.

Four named scripted policies (spec section 6: "illustrative of the family's
shape, not claimed-optimal or literature-calibrated strategies; their exact
constants are finalized at implementation time"), each a pure, deterministic
function of *only* the seat's own observation (``environment.py``'s
``observe`` -- never another seat's balance, HP, no-drink streak, or bid;
this is the same leakage-audit boundary spec section 2 leaf 4 requires of
the environment itself, restated here as the boundary this harness's own
policy functions must never cross):

* ``proportional`` -- bid a fixed ``3 * requirement`` every round. Verified
  against spec section 4 golden 1's own round-1 bid vector
  (``{Alex:24, Bob:27, Cindy:30, David:33, Eric:36}``).
* ``conservative`` -- bid a fixed ``1 * requirement`` every round. Spec
  section 4 golden 2 ("valid but poor"): every bid stays legal and
  well-formed, but this seat is systematically outbid by ``proportional``
  rivals.
* ``aggressive`` -- bid a fixed ``5 * requirement`` every round: over-bids
  ``proportional`` on a fixed multiplier, illustrating a more spend-heavy
  (but still upstream-fixed-persona-scaled) claim on scarce supply.
* ``myopic_need`` -- bid ``requirement * (1 + no_drink)``: reacts only to
  this seat's own, already-escalating drought penalty (``no_drink`` is
  upstream's own literal "need" counter -- starts at 1, increases by 1 every
  round this seat loses, per the governing facts) -- never to round number,
  balance, or any other seat's state. "Myopic" names the fact that it never
  looks ahead to future rounds or plans a multi-round budget; it only reacts
  to the immediately observable escalation of its own need.

These constants are this adapter's own choice (spec section 6 explicitly
defers them to "implementation time"); no earlier milestone locks in a
different value, and nothing here reimplements or overrides upstream's own
settlement mechanics (``_get_salary``/``_check_winner``/``_round_settlement``),
which remain exclusively ``environment.py``'s (via ``_delegate_round``).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from aeread.shared_runner.task.execution import EvidenceStore

from .cases import POLICY_IDS, SEAT_ORDER

Observation = Mapping[str, Any]
PolicyFn = Callable[[Observation], int]


def proportional_bid(observation: Observation) -> int:
    """Bid a fixed ``3 * requirement`` every round -- never round/balance/HP
    dependent, and never a function of any other seat's state."""
    return 3 * observation["requirement"]


def aggressive_bid(observation: Observation) -> int:
    """Bid a fixed ``5 * requirement`` every round -- systematically over-bids
    ``proportional``'s claim on scarce supply. Illustrative only (spec
    section 6), not literature-calibrated or claimed-optimal."""
    return 5 * observation["requirement"]


def conservative_bid(observation: Observation) -> int:
    """Bid a fixed ``1 * requirement`` every round -- spec section 4 golden
    2's "valid but poor" policy: legal and well-formed, but systematically
    outbid by ``proportional`` rivals."""
    return 1 * observation["requirement"]


def myopic_need_bid(observation: Observation) -> int:
    """Bid ``requirement * (1 + no_drink)`` -- see the module docstring for
    why keying this policy off ``no_drink`` (upstream's own escalating
    drought-need counter) is the "myopic, need-reactive" shape this policy
    id names."""
    return observation["requirement"] * (1 + observation["no_drink"])


POLICY_FUNCTIONS: Mapping[str, PolicyFn] = {
    "proportional": proportional_bid,
    "aggressive": aggressive_bid,
    "conservative": conservative_bid,
    "myopic_need": myopic_need_bid,
}


def _validate_policy_functions() -> None:
    declared = set(POLICY_IDS)
    implemented = set(POLICY_FUNCTIONS)
    if declared != implemented:
        raise AssertionError(
            "harness.POLICY_FUNCTIONS must implement exactly cases.POLICY_IDS; "
            f"declared={sorted(declared)} implemented={sorted(implemented)}"
        )


_validate_policy_functions()


def baseline_policy_assignment(
    policy_assignment: Mapping[str, str],
    *,
    focal_seat: str,
    baseline_policy_id: str = "proportional",
) -> dict[str, str]:
    """Swap ``focal_seat``'s own policy for ``baseline_policy_id``, holding
    every other seat's policy fixed -- spec section 2 leaf 1's comparative
    estimand: "terminal balance for the focal seat compared with the same
    seat run under a named baseline policy... on the *same* supply
    schedule/seed/opponent panel." The opponent panel is deliberately never
    touched here (spec: "the opponent panel... is part of the estimand").
    """
    if focal_seat not in policy_assignment:
        raise ValueError(f"focal_seat {focal_seat!r} is not in policy_assignment")
    if baseline_policy_id not in POLICY_FUNCTIONS:
        raise ValueError(f"unknown baseline_policy_id: {baseline_policy_id!r}")
    result = dict(policy_assignment)
    result[focal_seat] = baseline_policy_id
    return result


class ScriptedAlympicsWacHarness:
    """Serve one scripted bid per seat per round, from a fixed policy
    assignment, and seal one durable evidence event per bid served.

    ``policy_assignment`` binds exactly one of :data:`POLICY_FUNCTIONS`'s
    four named policies per seat (typically a grid cell's own
    ``grid_cell.policy_assignment``, or :func:`baseline_policy_assignment`'s
    output). Every served bid is computed purely from that seat's own
    ``DecisionRequest.observation`` (never another seat's bid or state,
    never this harness's own prior responses) -- the same leakage boundary
    ``environment.py``'s own ``observe`` enforces from the other side.

    Every request this harness answers is additionally appended to
    ``evidence`` as one ``alympics_wac_bid_served`` event before the
    response is returned, so a live run through this harness produces a
    durable, hash-chained record of every decision it served -- callers
    seal it with ``evidence.seal()`` once the episode terminates, exactly
    the way ``tau3_retail``'s harness threads tool-call evidence through
    the same ``EvidenceStore``.
    """

    def __init__(
        self, *, policy_assignment: Mapping[str, str], evidence: EvidenceStore
    ) -> None:
        if set(policy_assignment) != set(SEAT_ORDER):
            raise ValueError(
                f"policy_assignment must cover exactly {SEAT_ORDER}, got "
                f"{sorted(policy_assignment)}"
            )
        undeclared = set(policy_assignment.values()) - set(POLICY_FUNCTIONS)
        if undeclared:
            raise ValueError(f"undeclared policy id(s): {sorted(undeclared)}")
        self.policy_assignment = dict(policy_assignment)
        self.evidence = evidence
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> dict[str, int]:
        self.requests.append(request)
        seat_id = request.seat_id
        policy_id = self.policy_assignment[seat_id]
        bid = POLICY_FUNCTIONS[policy_id](request.observation)
        self.evidence.append_event(
            "alympics_wac_bid_served",
            {
                "seat_id": seat_id,
                "policy_id": policy_id,
                "round_id": request.observation["round_id"],
                "bid": bid,
            },
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
        )
        return {"bid": bid}


__all__ = [
    "POLICY_FUNCTIONS",
    "Observation",
    "PolicyFn",
    "ScriptedAlympicsWacHarness",
    "aggressive_bid",
    "baseline_policy_assignment",
    "conservative_bid",
    "myopic_need_bid",
    "proportional_bid",
]
