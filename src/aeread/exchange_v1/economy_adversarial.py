"""Adversarial-counterparty policy for the exchange arena.

A deterministic fraction (``defection_rate``) of counterparties DEFECT: they decline in
the response phase and reject at the private-acceptance gate, so any mechanism that
debits them is withheld/nullified. This tests robustness of the controller's surplus
capture to uncooperative counterparties, and whether screening mechanisms
(private_acceptance_check / ir_enforce) matter when counterparties won't cooperate.

Scope note: the harness settles synchronously and all-or-nothing, so this models
consent-withholding defection, NOT mid-settlement leg-risk/renege (which the escrow
story would require and is out of scope without a multi-phase settlement rewrite).
Core settlement is untouched; honest agents are unchanged LLM agents.
"""
from __future__ import annotations

import random
from typing import Any, Optional

from aeread.exchange_v1 import economy as ex

# Freeform decline the compiler reads as "no consent"; and a reject the audit honors.
_DEFECT_RESPONSE = (
    "PUBLIC ACTION\nADDRESSEES: none\nMESSAGE: I decline all proposed trades and will "
    "not transfer anything this round.\nRESPONSE REQUEST: none\nSETTLEMENT: none"
)
_DEFECT_ACCEPTANCE = '{"approve": false, "reason": "counterparty declines to settle"}'


class AdversarialCounterpartyPolicy(ex.LLMCompilerVerifierPolicy):
    """LLM policy where a seeded fraction of agents script rejections instead of LLM calls."""

    def __init__(self, *args: Any, defection_rate: float = 0.0, defection_seed: int = 0, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.defection_rate = float(defection_rate)
        self.defection_seed = int(defection_seed)
        self._defectors: Optional[set[int]] = None

    def _defector_set(self, num_agents: int) -> set[int]:
        if self._defectors is None:
            if self.defection_rate <= 0:
                self._defectors = set()
            else:
                rng = random.Random(self.defection_seed)
                k = min(num_agents, int(round(self.defection_rate * num_agents)))
                self._defectors = set(rng.sample(range(1, num_agents + 1), k))
        return self._defectors

    # ---- response phase ----
    def respond_text(self, world, agent_id, transcript, history):  # type: ignore[override]
        if agent_id in self._defector_set(world.num_agents):
            return _DEFECT_RESPONSE
        return super().respond_text(world, agent_id, transcript, history)

    def response_texts(self, world, agent_ids, transcript, history):  # type: ignore[override]
        defectors = self._defector_set(world.num_agents)
        out = {aid: _DEFECT_RESPONSE for aid in agent_ids if aid in defectors}
        honest = [aid for aid in agent_ids if aid not in defectors]
        if honest:
            out.update(super().response_texts(world, honest, transcript, history))
        return {aid: out[aid] for aid in agent_ids}

    # ---- private-acceptance gate ----
    def private_acceptance_text(self, world, agent_id, transcript, mechanism, history):  # type: ignore[override]
        if agent_id in self._defector_set(world.num_agents):
            return _DEFECT_ACCEPTANCE
        return super().private_acceptance_text(world, agent_id, transcript, mechanism, history)

    def private_acceptance_texts(self, world, agent_ids, transcript, mechanism, history):  # type: ignore[override]
        defectors = self._defector_set(world.num_agents)
        out = {aid: _DEFECT_ACCEPTANCE for aid in agent_ids if aid in defectors}
        honest = [aid for aid in agent_ids if aid not in defectors]
        if honest:
            out.update(super().private_acceptance_texts(world, honest, transcript, mechanism, history))
        return {aid: out[aid] for aid in agent_ids}
