"""Baseline candidate agents for the D10 submission harness (text boundary).

These are the deterministic floor submissions every case must separate from a real
agent (the D1b non-triviality ordering: no-op <= random < greedy < model). They
implement the submitted-agent contract — `act(observation: str, phase: str) -> str`
— and never see the world object, exactly like a foreign submission:

- `NoOpCandidate`: proposes nothing, declines every debit. The zero-action floor;
  its AER is the do-nothing baseline (0 gain, 0 destruction).
- `RandomCandidate(seed)`: seeded random choice over well-formed templated actions
  (generic offers / no-ops; random consent). Random-but-parseable — it measures how
  much of a case's score is available to noise that never reasons about the world.

The greedy floor is NOT a text-boundary candidate: it runs as the in-arena
`scripted_bilateral_ir` under-test seat (roles block, kind "scripted_bilateral_ir"),
because greedy IR search needs the world, which the text boundary forbids. A model
run uses the `llm` under-test kind the same way.

Usage with the harness CLI:
    python -m aeread.exchange_v1.submit --cases ... \
        --agent aeread.exchange_v1.candidates:NoOpCandidate
"""
from __future__ import annotations

import random


class NoOpCandidate:
    """The zero-action floor: no proposals, no consent."""

    def act(self, observation: str, phase: str) -> str:  # noqa: ARG002 - contract
        if phase == "private_acceptance":
            return '{"approve": false, "reason": "no-op baseline declines all debits"}'
        if phase == "proposal":
            return "PUBLIC ACTION\nI propose no trade this round."
        return "PUBLIC ACTION\nstanding by."

    def __repr__(self) -> str:  # keeps submission labels readable
        return "NoOpCandidate()"


class RandomCandidate:
    """Seeded random-but-parseable actions: the noise floor above no-op."""

    _COMMUNICATION = (
        "PUBLIC ACTION\nMESSAGE: open to trades this round.",
        "PUBLIC ACTION\nMESSAGE: seeking any mutually beneficial exchange.",
        "PUBLIC ACTION\nstanding by.",
    )
    _PROPOSALS = (
        "PUBLIC ACTION\nI propose no trade this round.",
        "PUBLIC ACTION\nPROPOSAL: I offer 1 unit of my most plentiful resource to any "
        "counterparty offering 1 unit of theirs in return.",
        "PUBLIC ACTION\nPROPOSAL: seeking a 2-for-1 exchange with any interested party.",
    )
    _RESPONSES = (
        "PUBLIC ACTION\nI accept the proposal as stated.",
        "PUBLIC ACTION\nI decline this round.",
        "PUBLIC ACTION\nI would accept a smaller quantity.",
    )

    def __init__(self, seed: int = 7):
        self._rng = random.Random(seed)
        self.seed = seed

    def act(self, observation: str, phase: str) -> str:  # noqa: ARG002 - contract
        if phase == "private_acceptance":
            approve = self._rng.random() < 0.5
            return (
                '{"approve": %s, "reason": "random baseline coin flip"}'
                % ("true" if approve else "false")
            )
        if phase == "proposal":
            return self._rng.choice(self._PROPOSALS)
        if phase == "communication":
            return self._rng.choice(self._COMMUNICATION)
        return self._rng.choice(self._RESPONSES)

    def __repr__(self) -> str:
        return f"RandomCandidate(seed={self.seed})"
