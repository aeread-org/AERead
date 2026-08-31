"""D11 frozen-counterpart design: deterministic concession sellers for the bundle arena.

What a "frozen supplier agent" IS (the B-side design; A runs it frozen via the
D9 per-role seam once that lands):

- **Hidden values**: the seller's private reservation cost ``c_k`` -- already the
  bundle world's preference entry for its own component (calibrated-assigned,
  never revealed in any output).
- **Concession schedule**: the seller quotes ``ask_t = c_k * (1 + margin_t)`` where
  ``margin_t = floor + (start - floor) * decay^(t-1)`` -- opens high, concedes
  geometrically toward a floor margin, never below cost. Deterministic in
  (c_k, round, params), so a replay reproduces it exactly.
- **Consent rule**: accept a settlement iff the seller's OWN utility delta
  (computed exactly, not self-reported -- the acceptance-elicitation fix baked in
  as code) meets the current round's required margin on every unit of its
  component being debited; never consent to any negative-delta mechanism.

`FrozenSellerCounterpartPolicy` is the scripted reference implementation
(zero LLM calls for seller roles) following the `AdversarialCounterpartyPolicy`
override pattern -- the interim per-agent seam until D9. `frozen_seller_role_prompt`
is the same contract expressed as a role prompt for the frozen-LLM variant
(D10 validation compares the LLM's behavior against this scripted oracle).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from aeread.exchange_v1 import economy as ex


@dataclass(frozen=True)
class FrozenSellerParams:
    """Concession-schedule parameters shared by the scripted and LLM variants."""

    margin_start: float = 0.35  # opening margin over reservation cost
    margin_floor: float = 0.05  # never sell below cost * (1 + floor)
    decay: float = 0.6          # geometric concession per round

    def required_margin(self, round_index: int) -> float:
        t = max(1, int(round_index))
        return self.margin_floor + (self.margin_start - self.margin_floor) * (self.decay ** (t - 1))


def bundle_seller_ids(world: ex.ExchangeWorld) -> list[int]:
    """Sellers on a bundle world: every non-buyer agent holding a required component."""
    spec = world.bundle_utility
    if spec is None:
        raise ValueError("bundle_seller_ids requires a bundle-under-budget world")
    sellers = []
    for i in range(world.num_agents):
        if i + 1 == spec.buyer_agent:
            continue
        if any(world.allocation[i][c - 1] >= 1 for c in spec.required_components):
            sellers.append(i + 1)
    return sellers


def seller_component_and_cost(world: ex.ExchangeWorld, seller_id: int) -> tuple[int, float]:
    spec = world.bundle_utility
    if spec is None:
        raise ValueError("seller_component_and_cost requires a bundle-under-budget world")
    i = seller_id - 1
    for component in spec.required_components:
        if world.allocation[i][component - 1] >= 1:
            return component, float(world.preferences[i][component - 1])
    raise ValueError(f"agent {seller_id} holds no required component")


def seller_ask(world: ex.ExchangeWorld, seller_id: int, round_index: int,
               params: Optional[FrozenSellerParams] = None) -> float:
    """The seller's deterministic per-unit quote for its component this round."""
    params = params or FrozenSellerParams()
    _, cost = seller_component_and_cost(world, seller_id)
    # Ceil to 2 decimals: the quote must never fall below the exact schedule, or the
    # seller's own consent rule would refuse its own ask.
    return math.ceil(cost * (1.0 + params.required_margin(round_index)) * 100) / 100


def seller_accepts(world: ex.ExchangeWorld, seller_id: int, mechanism: ex.CompiledMechanism,
                   round_index: int, params: Optional[FrozenSellerParams] = None) -> tuple[bool, float, float]:
    """Deterministic consent rule. Returns (accept, actual_delta, required_gain).

    The delta is computed exactly from the seller's own values (never trusted from
    the transcript). Required gain = this round's margin on every debited unit of
    the seller's component; any mechanism with negative delta is always refused.
    """
    params = params or FrozenSellerParams()
    component, cost = seller_component_and_cost(world, seller_id)
    delta = ex.utility_delta_for_mechanism(world, mechanism, seller_id)
    units_debited = sum(
        float(tr.quantity) for tr in mechanism.transfers
        if tr.from_agent == seller_id and tr.resource == component
    )
    required_gain = params.required_margin(round_index) * cost * units_debited
    return delta >= required_gain - 1e-9 and delta >= -1e-9, delta, required_gain


def _seller_response_text(world: ex.ExchangeWorld, seller_id: int, round_index: int,
                          params: FrozenSellerParams) -> str:
    component, _ = seller_component_and_cost(world, seller_id)
    ask = seller_ask(world, seller_id, round_index, params)
    resource_name = world.resource_names[component - 1]
    money_name = world.resource_names[world.bundle_utility.money_resource - 1]
    return (
        "PUBLIC ACTION\n"
        "ADDRESSEES:\n"
        f"a{world.bundle_utility.buyer_agent}\n"
        "MESSAGE:\n"
        f"I hold {resource_name} and will sell 1 unit for {ask} {money_name} this round. "
        "My price can improve in later rounds if we keep talking, but I will not sell below "
        "my private valuation.\n"
        "RESPONSE REQUEST:\n"
        "none\n"
        "SETTLEMENT:\n"
        f"I consent to transfer 1 {resource_name} to a{world.bundle_utility.buyer_agent} if and only if "
        f"I receive at least {ask} {money_name} in the same settlement.\n"
        "CONSENT CONDITIONS:\n"
        f"payment >= {ask} {money_name} per unit of {resource_name} debited from me\n"
        "PUBLIC STATE UPDATE:\n"
        "none\n"
        "NO-TRANSFER FALLBACK:\n"
        "No transfer this round."
    )


def _seller_acceptance_json(accept: bool, delta_sign: str) -> str:
    reason = (
        "settlement meets my required margin this round"
        if accept
        else "settlement does not meet my required margin this round"
    )
    return (
        '{"claimed_delta_sign": "%s", "counterpart_transfers_present": true, '
        '"same_bundle_authorized": true, "approve": %s, "reason": "%s"}'
        % (delta_sign, "true" if accept else "false", reason)
    )


class FrozenSellerCounterpartPolicy(ex.LLMCompilerVerifierPolicy):
    """LLM policy where bundle-world sellers are scripted concession agents (zero LLM calls).

    The buyer (and compiler/verifier plumbing) stays LLM-backed; every seller in
    ``seller_ids`` (default: auto-detected from the bundle world) responds with its
    deterministic quote and applies the exact-delta consent rule at the private
    acceptance gate. This is the interim per-agent seam (the pattern
    AdversarialCounterpartyPolicy established) until the D9 role seam lands.
    """

    def __init__(self, *args: Any, seller_params: Optional[FrozenSellerParams] = None,
                 seller_ids: Optional[list[int]] = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.seller_params = seller_params or FrozenSellerParams()
        self._seller_ids = seller_ids

    def _sellers(self, world: ex.ExchangeWorld) -> set[int]:
        if self._seller_ids is not None:
            return set(self._seller_ids)
        return set(bundle_seller_ids(world))

    # ---- response phase ----
    def respond_text(self, world, agent_id, transcript, history):  # type: ignore[override]
        if agent_id in self._sellers(world):
            return _seller_response_text(world, agent_id, transcript.round_index, self.seller_params)
        return super().respond_text(world, agent_id, transcript, history)

    def response_texts(self, world, agent_ids, transcript, history):  # type: ignore[override]
        sellers = self._sellers(world)
        out = {
            aid: _seller_response_text(world, aid, transcript.round_index, self.seller_params)
            for aid in agent_ids if aid in sellers
        }
        buyers = [aid for aid in agent_ids if aid not in sellers]
        if buyers:
            out.update(super().response_texts(world, buyers, transcript, history))
        return {aid: out[aid] for aid in agent_ids}

    # ---- private-acceptance gate ----
    def private_acceptance_text(self, world, agent_id, transcript, mechanism, history):  # type: ignore[override]
        if agent_id in self._sellers(world):
            accept, delta, _ = seller_accepts(
                world, agent_id, mechanism, transcript.round_index, self.seller_params)
            sign = "positive" if delta > 1e-9 else ("negative" if delta < -1e-9 else "zero")
            return _seller_acceptance_json(accept, sign)
        return super().private_acceptance_text(world, agent_id, transcript, mechanism, history)

    def private_acceptance_texts(self, world, agent_ids, transcript, mechanism, history):  # type: ignore[override]
        sellers = self._sellers(world)
        out = {
            aid: self.private_acceptance_text(world, aid, transcript, mechanism, history)
            for aid in agent_ids if aid in sellers
        }
        buyers = [aid for aid in agent_ids if aid not in sellers]
        if buyers:
            out.update(super().private_acceptance_texts(world, buyers, transcript, mechanism, history))
        return {aid: out[aid] for aid in agent_ids}


def frozen_seller_role_prompt(world: ex.ExchangeWorld, seller_id: int,
                              params: Optional[FrozenSellerParams] = None) -> str:
    """The same counterpart contract as a role prompt for the frozen-LLM variant (D9/D10).

    Includes the private reservation cost (the model must know its own value), the
    concession schedule as an explicit rule, the forced own-delta computation at the
    acceptance gate (the acceptance-elicitation fix), and a hard prohibition on
    revealing the private cost. D10 validation replays this agent against the
    scripted implementation above and requires behavioral agreement.
    """
    params = params or FrozenSellerParams()
    component, cost = seller_component_and_cost(world, seller_id)
    spec = world.bundle_utility
    resource_name = world.resource_names[component - 1]
    money_name = world.resource_names[spec.money_resource - 1]
    return (
        f"You are agent a{seller_id}, a supplier in a procurement negotiation. You hold units of "
        f"{resource_name}. Your PRIVATE reservation cost is {cost} {money_name} per unit: selling below "
        "it makes you worse off. NEVER state, hint at, or bound your reservation cost in any message.\n\n"
        "Pricing rule (follow it exactly):\n"
        f"- In round t, your quote is cost * (1 + m_t) where m_t = {params.margin_floor} + "
        f"({params.margin_start} - {params.margin_floor}) * {params.decay}^(t-1), rounded to 2 decimals.\n"
        "- Quote this price when asked; you may restate it, but never quote below it in that round.\n\n"
        "Consent rule (follow it exactly): before approving any settlement, compute your OWN utility "
        "delta step by step -- money you receive minus (reservation cost x units of your good debited). "
        "Approve if and only if the delta is at least m_t * cost * units_debited and never when the delta "
        "is negative. Write the computation out before your decision.\n\n"
        "You respond only for yourself. Do not coordinate with other suppliers."
    )
