"""AERead-authored scripted policies standing in for govsim personas.

Every policy here is a pure, deterministic function of the current round's
public observation -- never upstream's ``persona_v3``/pathfinder LLM
cognition stack, which this adapter never imports, bridges, or reimplements
in any form (``docs/govsim_adapter_spec.md``'s scope note). Each returns the
native-unit quantity (tons of fish / hectares of grass / units of pollution
capacity, depending on scenario framing) one persona wants to harvest this
round; ``environment.py`` submits it as the ``quantity`` field of a
``govsim_harvest_action_v1`` action during the ``harvest`` phase.

These are intentionally simple. They exist to drive the three named case
cells (``sustainable_v1``/``greedy_v1``/``mixed_v1``) through the real
environment for the QC Gate 2 goldens and, later, the replay/parity suite --
not to model plausible human behavior.
"""
from __future__ import annotations

from typing import Callable, Mapping

PolicyFn = Callable[[Mapping[str, object]], int]


def sustainable_v1(observation: Mapping[str, object]) -> int:
    """Harvest exactly the advisory sustainability threshold, never more."""
    return max(0, int(observation["sustainability_threshold"]))  # type: ignore[arg-type]


def greedy_v1(observation: Mapping[str, object]) -> int:
    """Harvest the entire pool this round, ignoring the advisory threshold."""
    return max(0, int(observation["resource_in_pool"]))  # type: ignore[arg-type]


def mixed_v1(observation: Mapping[str, object]) -> int:
    """Alternate ``sustainable_v1``/``greedy_v1`` by round parity.

    A third scripted stand-in distinct from the other two -- never a hedge
    or an average of their quantities, which would just be another fixed
    number every round. Alternating by round instead varies the
    round-over-round *pattern* the environment sees, which the other two
    policies cannot produce on their own.
    """
    round_index = int(observation["num_round"])  # type: ignore[arg-type]
    if round_index % 2 == 0:
        return sustainable_v1(observation)
    return greedy_v1(observation)


SCRIPTED_POLICIES: Mapping[str, PolicyFn] = {
    "sustainable_v1": sustainable_v1,
    "greedy_v1": greedy_v1,
    "mixed_v1": mixed_v1,
}

# Short form used only in case identifiers (spec section 1's
# ``govsim.<scenario>.<policy>.<world_seed>``, e.g.
# ``govsim.fishing.sustainable.0``): dropping the "_v1" suffix keeps ids
# shorter without dropping the version discipline from the policy id itself
# (``policy_assignment`` values in the case payload always carry the full
# ``sustainable_v1``/``greedy_v1``/``mixed_v1`` form).
POLICY_ID_SHORT_NAME: Mapping[str, str] = {
    "sustainable_v1": "sustainable",
    "greedy_v1": "greedy",
    "mixed_v1": "mixed",
}

__all__ = [
    "POLICY_ID_SHORT_NAME",
    "SCRIPTED_POLICIES",
    "greedy_v1",
    "mixed_v1",
    "sustainable_v1",
]
