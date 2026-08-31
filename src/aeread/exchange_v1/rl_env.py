"""Structured (LLM-free) 2-agent RL wrapper around the exchange-economy substrate.

`run_one_round` in `economy.py` drives every decision through a
duck-typed `policy` object; the only shipped implementation
(`LLMCompilerVerifierPolicy`) makes that decision via a free-form-text LLM
call. `StructuredBilateralPolicy` below implements the same duck-typed
surface with typed actions instead, so `run_one_round`/`apply_compiled_mechanism`
can be reused unmodified for RL rollouts with zero API calls.

Round protocol (matches `protocol.atomic_commit=True`, `private_acceptance_check=False`):
one agent is controller per round; the environment alternates controllers so a
`propose` by agent A on round t is followed by agent B controlling round t+1,
where `accept`/`reject` resolves A's pending offer.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from aeread.exchange_v1 import economy as ex  # noqa: E402

ActionKind = Literal["propose", "accept", "reject", "no_op"]

_EMPTY_MECHANISM_LABEL = "no_op"


@dataclass(frozen=True)
class StructuredAction:
    kind: ActionKind
    give: dict[int, float] = field(default_factory=dict)
    get: dict[int, float] = field(default_factory=dict)


def _empty_mechanism(agent_id: int, label: str = _EMPTY_MECHANISM_LABEL) -> ex.CompiledMechanism:
    return ex.CompiledMechanism(
        proposer_id=agent_id,
        label=label,
        summary=label,
        transfers=[],
        consenting_agents=[],
        confidence=1.0,
        verifier_ok=True,
    )


def _clamp_transfers(
    world: ex.ExchangeWorld,
    from_agent: int,
    to_agent: int,
    goods: dict[int, float],
) -> tuple[list[ex.Transfer], list[str]]:
    """Build Transfers from a {resource_id: qty} map, clamping to what `from_agent` owns.

    Returns (transfers, warnings). Never raises on out-of-range/oversized requests
    from an (untrained) RL policy -- infeasible legs are dropped/clamped instead.
    """
    transfers: list[ex.Transfer] = []
    warnings: list[str] = []
    for resource_id, qty in goods.items():
        if not (1 <= resource_id <= world.num_resources):
            warnings.append(f"resource {resource_id} out of range, dropped")
            continue
        qty = float(qty)
        if qty <= 0:
            warnings.append(f"non-positive quantity {qty} for resource {resource_id}, dropped")
            continue
        available = world.allocation[from_agent - 1][resource_id - 1]
        if qty > available:
            warnings.append(
                f"resource {resource_id} qty {qty} exceeds {from_agent}'s holding {available}, clamped"
            )
            qty = float(available)
        if qty <= 0:
            continue
        transfers.append(ex.Transfer(from_agent=from_agent, to_agent=to_agent, resource=resource_id, quantity=qty))
    return transfers, warnings


class StructuredBilateralPolicy:
    """Zero-LLM `run_one_round` policy driven by externally-injected StructuredActions.

    The env wrapper sets `_pending` to the CompiledMechanism for the current
    round before calling `run_one_round`; `compile_transcript` just returns it.
    """

    def __init__(self) -> None:
        self._pending: Optional[ex.CompiledMechanism] = None

    def communication_texts(self, world, agent_ids, t, history) -> dict[int, str]:
        return {}

    def propose_text(self, world, controller_id, t, history, communication_texts) -> str:
        return f"structured round {t} controller a{controller_id}"

    def response_texts(self, world, responder_ids, blank, history) -> dict[int, str]:
        return {aid: "" for aid in responder_ids}

    def compile_transcript(self, world, transcript) -> ex.CompiledMechanism:
        assert self._pending is not None, "wrapper must set _pending before run_one_round"
        return self._pending

    def verify_compilation(self, world, transcript, compiled) -> ex.CompiledMechanism:
        return compiled


class BilateralNegotiationEnv:
    """Minimal reset()/step() wrapper for 2-agent structured bilateral negotiation."""

    def __init__(self, config_path: str | Path):
        self.config = ex.load_experiment_config(config_path)
        if self.config.num_agents != 2:
            raise ValueError("BilateralNegotiationEnv requires a 2-agent config")
        self.policy = StructuredBilateralPolicy()
        self.world: Optional[ex.ExchangeWorld] = None
        self.history: list[ex.RoundEvent] = []
        self.round_index: int = 1
        self._pending_offer: Optional[dict[str, Any]] = None
        self._controllers = list(self.config.controllers)

    def reset(self) -> dict[int, dict]:
        self.world = ex.make_world_from_config(self.config)
        self.history = []
        self.round_index = 1
        self._pending_offer = None
        return {aid: self._observation(aid) for aid in (1, 2)}

    def _observation(self, agent_id: int) -> dict:
        assert self.world is not None
        obs = self.world.public_state(agent_id)
        last = self.history[-1] if self.history else None
        obs["last_event"] = (
            None
            if last is None
            else {
                "kind": last.kind,
                "applied": last.applied,
                "agent_deltas": dict(last.agent_deltas),
            }
        )
        obs["round_index"] = self.round_index
        obs["rounds_remaining"] = max(0, self.config.rounds - self.round_index + 1)
        return obs

    def _counterpart(self, agent_id: int) -> int:
        return 2 if agent_id == 1 else 1

    def _build_mechanism(self, agent_id: int, action: StructuredAction) -> tuple[ex.CompiledMechanism, list[str]]:
        assert self.world is not None
        counterpart = self._counterpart(agent_id)
        warnings: list[str] = []

        if action.kind == "no_op":
            return _empty_mechanism(agent_id, "no_op"), warnings

        if action.kind == "propose":
            give_transfers, give_warnings = _clamp_transfers(self.world, agent_id, counterpart, action.give)
            get_transfers, get_warnings = _clamp_transfers(self.world, counterpart, agent_id, action.get)
            warnings.extend(give_warnings)
            warnings.extend(get_warnings)
            transfers = give_transfers + get_transfers
            self._pending_offer = {
                "proposer_id": agent_id,
                "responder_id": counterpart,
                "transfers": transfers,
            }
            if not transfers:
                warnings.append("propose had no valid legs, treated as no_op")
            # A lone propose never moves resources: only the proposer has consented.
            return (
                ex.CompiledMechanism(
                    proposer_id=agent_id,
                    label="propose",
                    summary=f"a{agent_id} proposes trade with a{counterpart}",
                    transfers=transfers,
                    consenting_agents=[agent_id],
                    confidence=1.0,
                    verifier_ok=True,
                ),
                warnings,
            )

        if action.kind == "accept":
            offer = self._pending_offer
            if offer is None or offer["responder_id"] != agent_id:
                warnings.append("accept with no matching pending offer, treated as no_op")
                return _empty_mechanism(agent_id, "accept_no_offer"), warnings
            self._pending_offer = None
            return (
                ex.CompiledMechanism(
                    proposer_id=offer["proposer_id"],
                    label="accept",
                    summary=f"a{agent_id} accepts a{offer['proposer_id']}'s offer",
                    transfers=offer["transfers"],
                    consenting_agents=[offer["proposer_id"], offer["responder_id"]],
                    confidence=1.0,
                    verifier_ok=True,
                ),
                warnings,
            )

        if action.kind == "reject":
            if self._pending_offer is not None and self._pending_offer["responder_id"] == agent_id:
                self._pending_offer = None
            return _empty_mechanism(agent_id, "reject"), warnings

        raise ValueError(f"unknown action kind: {action.kind}")

    def step(self, agent_id: int, action: StructuredAction) -> tuple[dict, float, bool, dict]:
        assert self.world is not None, "call reset() first"
        if self.round_index > self.config.rounds:
            raise RuntimeError("episode already finished; call reset()")

        mechanism, warnings = self._build_mechanism(agent_id, action)
        self.policy._pending = mechanism
        event, coordination_cost = ex.run_one_round(
            self.world,
            self.round_index,
            agent_id,
            self.history,
            self.policy,
            self.config.protocol,
        )
        self.history.append(event)
        self.round_index += 1

        # RoundEvent.agent_deltas is computed as-if every listed transfer executed,
        # even when the mechanism was infeasible/unconsented (e.g. a lone `propose`
        # with only one consenting party) and nothing was actually applied to
        # world.allocation -- gate on `applied` so an un-accepted offer pays no reward.
        if event.applied:
            reward = event.agent_deltas.get(agent_id, 0.0)
            counterpart_reward = event.agent_deltas.get(self._counterpart(agent_id), 0.0)
        else:
            reward = 0.0
            counterpart_reward = 0.0
        done = self.round_index > self.config.rounds

        next_controller = agent_id if done else self._next_controller()
        obs = self._observation(next_controller)
        info = {
            "applied": event.applied,
            "feasible": event.feasible,
            "individually_rational": event.individually_rational,
            "coordination_cost": coordination_cost,
            "counterpart_reward": counterpart_reward,
            "warnings": warnings,
            "event": event,
            "next_controller": next_controller,
        }
        return obs, reward, done, info

    def _next_controller(self) -> int:
        idx = (self.round_index - 1) % len(self._controllers)
        return self._controllers[idx]
