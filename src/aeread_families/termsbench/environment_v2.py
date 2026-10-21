"""The reproduction's plugin version: the paper's observation, parsing and fallback (family version 0.2.0).

The plan is ``docs/families/termsbench/reproduction_plan.md`` (identity ``termsbench_repro_v1``, Section 2).
:mod:`.environment` (family version 0.1.0) is not edited, so every published pilot keeps replaying from current
source. This subclass changes three things, each to what the paper's Appendix H.1.5 states:

- **Observation (TB-D-07).** The agent sees five top-level keys: ``private_context`` (its role, the opener and its
  reservation price), ``protocol_state`` (round number, maximum rounds, rounds remaining including this one, whether a
  counterpart offer is on the table, the legal decisions, its own previous offer), ``constraints`` (the price bounds
  and the monotone-concession rule), ``observation`` (the counterpart's current offer and message, and the utility of
  accepting it now) and ``history`` (the last :data:`HISTORY_WINDOW` rounds of play). The paper also lists a
  ``delta_max`` constraint without giving its value; it is left out and listed as a gap in the plan's Section 11.
- **Parsing.** Decisions are read case-insensitively (the paper writes ``Offer``, ``Accept``, ``Reject``). ``Offer``
  needs a finite price; for ``Accept`` and ``Reject`` a price is ignored, so an ``Accept`` that carries a price
  executes at the standing counterpart offer (TB-D-05). An offered price outside the bounds is clamped to them and
  recorded as a price-bound violation. An optional ``belief`` object is kept for diagnostics and never moves the
  state.
- **Fallback (TB-D-08).** A move that does not parse, or an ``Accept`` with no counterpart offer on the table, is
  replaced by the paper's deterministic fallback: accept the standing counterpart offer if it is weakly preferred to
  walking away, otherwise offer the agent's own reservation price. The fallback is recorded as an invalid-action
  violation and counted (``fallback_moves``), and the episode continues. v0.1.0 ended such an episode as an agreement
  violation and removed it from the surplus measures; that rule is reported as a sensitivity from the count.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult

from . import environment as v1
from .cases_v2 import FAMILY_VERSION

HISTORY_WINDOW = 6
DECISIONS = {"offer": "offer", "accept": "accept", "reject": "reject"}
ROLE_LABEL = {"buyer": "BUYER", "seller": "SELLER"}
OPENER_LABEL = {"agent_opens": "AgentOpens", "counterpart_opens": "CounterpartOpens"}
OBSERVATION_SCHEMA = "termsbench_agent_observation_paper_v1"


def family_manifest() -> FamilyManifest:
    base = v1.family_manifest()
    return dataclasses.replace(base, family=dataclasses.replace(base.family, version=FAMILY_VERSION))


def register_plugin(registry: PluginRegistry, *, plugin: "TermsBenchPluginV2 | None" = None) -> "TermsBenchPluginV2":
    plugin = plugin or TermsBenchPluginV2()
    registry.register_trusted(family_manifest(), plugin)
    return plugin


def _standing_offer(state: Mapping[str, Any]) -> float | None:
    """The counterpart offer on the table: its last move, when that move was an offer."""
    for entry in reversed(state["transcript"]):
        if entry["speaker"] == "counterpart":
            return float(entry["price"]) if entry["decision"] == "offer" else None
        return None
    return None


def accept_utility(role: str, r_a: float, price: float) -> float:
    return r_a - price if role == "buyer" else price - r_a


def fallback_action(family_case: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    """The paper's deterministic fallback (Appendix H.1.5)."""
    role, r_a = family_case["agent"]["role"], float(family_case["agent"]["r_a"])
    offer = _standing_offer(state)
    if offer is not None and accept_utility(role, r_a, offer) >= 0.0:
        return {"decision": "accept", "price": None, "message": "", "belief": None}
    return {"decision": "offer", "price": r_a, "message": "", "belief": None}


class TermsBenchPluginV2(v1.TermsBenchPlugin):
    """The paper's protocol over v0.1.0's kernel, counterpart and scorer."""

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        state = super().initial_state(family_case, cell)
        state.update(fallback_moves=0, beliefs=[])
        return state

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        return tuple(
            dataclasses.replace(p, observation_schema_by_role={"agent": OBSERVATION_SCHEMA}) if p.phase_id == v1.AGENT_PHASE else p
            for p in super().phases(family_case)
        )

    def observe(self, family_case: Mapping[str, Any], state: Mapping[str, Any], seat_id: str, phase: PhaseSpec) -> dict[str, Any]:
        if not (phase.phase_id == v1.AGENT_PHASE and seat_id == "agent"):
            return super().observe(family_case, state, seat_id, phase)
        role, r_a = family_case["agent"]["role"], float(family_case["agent"]["r_a"])
        horizon, round_k = int(family_case["horizon"]), int(state["round"])
        offer = _standing_offer(state)
        message = next((e["message"] for e in reversed(state["transcript"]) if e["speaker"] == "counterpart"), None)
        bounds = family_case["price_bounds"]
        return {
            "private_context": {"agent_role": ROLE_LABEL[role], "opener_role": OPENER_LABEL[family_case["chi"]],
                                "reservation_price": r_a},
            "protocol_state": {"round_number": round_k, "max_rounds": horizon, "rounds_remaining": horizon - round_k + 1,
                               "counterpart_offer_on_table": offer is not None,
                               "legal_decisions": ["Offer", "Accept", "Reject"] if offer is not None else ["Offer"],
                               "own_previous_offer": state["agent_offers"][-1] if state["agent_offers"] else None},
            "constraints": {"price_bounds": [bounds["p_min"], bounds["p_max"]],
                            "monotone_concession": ("buyer offers weakly increase across rounds" if role == "buyer"
                                                    else "seller offers weakly decrease across rounds")},
            "observation": {"counterpart_offer": offer, "counterpart_message": message if offer is not None else None,
                            "accept_utility": accept_utility(role, r_a, offer) if offer is not None else None},
            "history": [dict(e) for e in state["transcript"][-2 * HISTORY_WINDOW:]],
        }

    def parse_action(self, family_case: Mapping[str, Any], state: Mapping[str, Any], seat_id: str, phase: PhaseSpec,
                     response: Any) -> ParseResult:
        if not (phase.phase_id == v1.AGENT_PHASE and seat_id == "agent"):
            return super().parse_action(family_case, state, seat_id, phase, response)
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = v1._plain(response)
        decision = DECISIONS.get(str(raw.get("decision", "")).strip().lower())
        if decision is None:
            return ParseResult.failure("invalid_decision")
        price = raw.get("price")
        if decision == "offer":
            if not v1._finite_number(price):
                return ParseResult.failure("offer_requires_price")
            price = float(price)
        else:
            price = None
        message = raw.get("message", "")
        if not isinstance(message, str):
            message = ""
        belief = raw.get("belief") if isinstance(raw.get("belief"), Mapping) else None
        return ParseResult.success({"decision": decision, "price": price, "message": message, "belief": belief})

    def legal(self, family_case: Mapping[str, Any], state: Mapping[str, Any], seat_id: str, phase: PhaseSpec,
              action: Mapping[str, Any]) -> LegalityResult:
        if phase.phase_id == v1.AGENT_PHASE and action["decision"] == "accept" and _standing_offer(state) is None:
            return LegalityResult.illegal("accept_without_counterpart_offer")
        return super().legal(family_case, state, seat_id, phase, action)

    def _step_agent(self, family_case: Mapping[str, Any], state: Mapping[str, Any], new_state: dict[str, Any],
                    envelope: Any) -> TransitionResult:
        if envelope.valid:
            action = dict(envelope.action)
        else:
            action = fallback_action(family_case, state)
            new_state["critical_violations"]["invalid_action"] = True
            new_state["fallback_moves"] = int(state.get("fallback_moves", 0)) + 1
        if action.get("belief") is not None:
            new_state["beliefs"] = list(state.get("beliefs", [])) + [{"round": state["round"], "belief": action["belief"]}]
        if action["decision"] == "offer":
            p_min, p_max = float(family_case["price_bounds"]["p_min"]), float(family_case["price_bounds"]["p_max"])
            clamped = min(max(action["price"], p_min), p_max)
            if clamped != action["price"] or not math.isfinite(action["price"]):
                new_state["critical_violations"]["price_bound"] = True
            action["price"] = clamped
        legacy = dataclasses.replace(envelope, valid=True, action={k: action[k] for k in ("decision", "price", "message")}) \
            if dataclasses.is_dataclass(envelope) else _Envelope(True, {k: action[k] for k in ("decision", "price", "message")})
        result = super()._step_agent(family_case, state, new_state, legacy)
        result.state["critical_violations"]["price_bound"] = (
            result.state["critical_violations"]["price_bound"] or new_state["critical_violations"]["price_bound"])
        return result

    def terminal(self, family_case: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any] | None:
        out = super().terminal(family_case, state)
        if out is not None:
            out["fallback_moves"] = int(state.get("fallback_moves", 0))
        return out

    def outcome(self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]) -> dict[str, Any]:
        out = super().outcome(family_case, terminal)
        out["fallback_moves"] = int(terminal.get("fallback_moves", 0))
        return out


@dataclasses.dataclass(frozen=True)
class _Envelope:
    valid: bool
    action: Mapping[str, Any]
    parse: Any = None


__all__ = ["HISTORY_WINDOW", "TermsBenchPluginV2", "accept_utility", "fallback_action", "family_manifest", "register_plugin"]
