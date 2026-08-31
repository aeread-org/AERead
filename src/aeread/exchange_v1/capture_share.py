"""Per-agent captured surplus — the distributional companion to the market-level AER.

AER measures TOTAL realized welfare (share of W*). It is blind to how that welfare is
split: a market can be efficient while the agent under test captured almost none of it
(out-negotiated) or claimed a disproportionate share (assertive). This module reports that
split as a pure function of the episode's allocations — no oracle, no LLM.

    surplus_i = u_i(final) - u_i(initial)      per-agent realized gain
    total     = sum_i surplus_i                = the market welfare gain (the AER basis)
    share     = surplus_test / total           fraction captured by the tested seat

In a symmetric N-agent market a fair share is 1/N: share < 1/N means the tested agent was
out-negotiated, > 1/N means it claimed more than an equal cut. The share is RAW — it
preserves signs — and a degenerate total (|total| <= EPS) yields None rather than a
fabricated ratio, matching the AER scorer's discipline. Most diagnostic against the
`scripted_bilateral_extract` panel, where a competent agent should resist being driven to
near-zero surplus by a self-interested counterparty.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from . import economy as ex

EPS = 1e-9


@dataclass
class CaptureReport:
    """One episode's surplus split, from the seat-under-test's point of view."""

    agent_id: int                 # 1-indexed seat under test
    agent_surplus: float          # u_test(final) - u_test(initial)
    total_surplus: float          # sum over seats = market welfare gain
    share: Optional[float]        # agent_surplus / total_surplus, raw; None if degenerate
    fair_share: float             # 1 / num_agents — the equal-split reference
    per_agent_surplus: list       # every seat's realized surplus (for the distribution view)


def episode_capture(
    world,
    final_allocation,
    agent_id: int,
    *,
    initial_allocation=None,
) -> CaptureReport:
    """Capture report for one episode. `agent_id` is the 1-indexed seat under test.

    `initial_allocation` defaults to `world.allocation` (the endowment); pass it explicitly
    when the world object has already been advanced to the final state.
    """
    n = world.num_agents
    if not (1 <= agent_id <= n):
        raise ValueError(f"agent_id {agent_id} out of range 1..{n}")
    initial = world.allocation if initial_allocation is None else initial_allocation
    u_init = ex.utility_vector(world, initial)
    u_final = ex.utility_vector(world, final_allocation)
    surplus = [u_final[i] - u_init[i] for i in range(n)]
    total = sum(surplus)
    agent_surplus = surplus[agent_id - 1]
    share = None if abs(total) <= EPS else agent_surplus / total
    return CaptureReport(
        agent_id=agent_id,
        agent_surplus=agent_surplus,
        total_surplus=total,
        share=share,
        fair_share=1.0 / n,
        per_agent_surplus=surplus,
    )


def pooled_capture_share(reports: Sequence[Optional[CaptureReport]]) -> Optional[float]:
    """Pool capture across episodes as sum(agent_surplus) / sum(total_surplus).

    Ratio-of-sums (the AER aggregation), so a run's near-zero-total episodes cannot blow up
    the average. Returns None if there are no reports or the pooled total is degenerate.
    """
    kept = [r for r in reports if r is not None]
    if not kept:
        return None
    num = sum(r.agent_surplus for r in kept)
    den = sum(r.total_surplus for r in kept)
    return None if abs(den) <= EPS else num / den
