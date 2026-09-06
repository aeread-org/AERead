"""Kernel family plugin for the ``termsbench`` bilateral price-negotiation
environment (docs/termsbench_adapter_spec.md section 3).

Two single-actor phases, strict alternation (spec section 3.1): ``agent_turn``
(one agent logical action ``a_k=(d_k,p_k,l_k)``) and ``counterpart_turn`` (one
full realization of the counterpart's stochastic kernel, computed in
``kernel.py`` and supplied by :class:`~.harness.ScriptedTermsBenchHarness`,
never an LLM). Which phase starts is an episode attribute (the opener ``chi``
frozen into the case payload), not a fixed property of the phase graph, so
``phases()`` orders the two phases per case.

Owner decision (kernel_scoring_contract_spec.md ruling R13 rule 1): this
family is split into two regime-specific family VERSIONS -- ``termsbench.overlap``
and ``termsbench.nodeal`` -- each with its OWN static leaf set, rather than one
family declaring a leaf conditionally by case regime (the rejected design;
see ``docs/termsbench_migration_plan.md``). One ``TermsBenchPlugin`` class,
carrying a ``regime`` attribute fixed at construction, is registered as TWO
separate instances -- this is what the registry mechanism supports most
simply: ``PluginRegistry`` keys a registration by ``(family_id,
family_version, plugin_id)`` on the MANIFEST and PLUGIN INSTANCE it is given,
never by class identity, so two instances of one class bound to two distinct
manifests need no subclassing at all. ``validate_payload`` rejects any case
whose own ``regime`` does not match the instance's ``regime`` -- a
wrong-regime case can never reach either instance's scorer.

Milestone 1 built the environment only: cases + phase graph + counterpart
kernel + scripted harness. Milestone 2 (docs/termsbench_adapter_spec.md
section 2) adds the 4 measurement leaves (SE+/AGR+/FAGR-/CritViol%) in
``measurement.py``; ``build_scorer`` below wires them in.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from . import kernel as k
from .cases import FAMILY_ID_BY_REGIME, FAMILY_VERSION, REGIMES, TERMINATION_REASONS
from .measurement import (
    DOMAIN_PREDICATE_ID,
    FEASIBLE_AGREEMENT_LEAF_ID,
    FEASIBLE_AGREEMENT_SCORER_ID,
    NO_DEAL_AGREEMENT_ESTIMAND_ID,
    NO_DEAL_AGREEMENT_LEAF_ID,
    NO_DEAL_AGREEMENT_SCORER_ID,
    PROTOCOL_COMPLIANCE_LEAF_ID,
    PROTOCOL_COMPLIANCE_SCORER_ID,
    SURPLUS_EFFICIENCY_ESTIMAND_ID,
    SURPLUS_EFFICIENCY_LEAF_ID,
    SURPLUS_EFFICIENCY_SCORER_ID,
    TermsBenchScorer,
    build_scorer as build_measurement_scorer,
)

# One plugin id and one scorer id per regime -- the two family versions are
# distinct trusted registrations (registry.py's TRUSTED_BUILTIN_PLUGIN_KEYS),
# never a shared identity distinguished only by manifest content.
PLUGIN_ID_BY_REGIME: Mapping[str, str] = {
    "overlap": "termsbench_overlap_environment",
    "nodeal": "termsbench_nodeal_environment",
}
SCORER_ID_BY_REGIME: Mapping[str, str] = {
    "overlap": "termsbench_overlap_scorer",
    "nodeal": "termsbench_nodeal_scorer",
}
# Each family version's own headline estimand -- SE+ for Overlap, FAGR- for
# No-deal (docs/termsbench_migration_plan.md's leaf tables). Before the split
# this was one family-wide field fixed at "termsbench_surplus_efficiency"
# even for No-deal cases, for which it never applied; the split makes each
# family's own value correct instead of merely legal.
PRIMARY_ESTIMAND_BY_REGIME: Mapping[str, str] = {
    "overlap": SURPLUS_EFFICIENCY_ESTIMAND_ID,
    "nodeal": NO_DEAL_AGREEMENT_ESTIMAND_ID,
}
AGENT_PHASE = "agent_turn"
COUNTERPART_PHASE = "counterpart_turn"

_DECISIONS = ("offer", "accept", "reject")


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    Mirrors tau3_retail's ``_set_termination``: the case manifest publishes
    ``TERMINATION_REASONS`` as this family's termination vocabulary, and
    nothing in the kernel cross-checks a terminal reason against that
    declaration at runtime, so this closes the gap here instead.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


def family_manifest(regime: str) -> FamilyManifest:
    """Return the strict family declaration for one regime's family version.

    ``regime`` selects which of the two split identities this manifest
    declares -- ``termsbench.overlap`` or ``termsbench.nodeal``
    (owner decision, ruling R13 rule 1). There is no longer a single
    cross-regime ``termsbench`` manifest.
    """
    if regime not in REGIMES:
        raise ValueError(f"unknown regime: {regime!r}")
    direction = "maximize" if regime == "overlap" else "minimize"
    outcome_support = "zopa_fraction" if regime == "overlap" else "pass"
    if regime == "overlap":
        # termsbench.overlap's static leaf set (docs/termsbench_migration_plan.md):
        # SE+ (primary, sole admission), AGR+, CritViol% -- all finalize_time,
        # none case_conditional (ruling R13's hook is not needed: every case
        # this family version ever sees is Overlap, by validate_payload).
        leaves = [
            {"leaf_id": SURPLUS_EFFICIENCY_LEAF_ID, "scope": "finalize_time"},
            {"leaf_id": FEASIBLE_AGREEMENT_LEAF_ID, "scope": "finalize_time"},
            {"leaf_id": PROTOCOL_COMPLIANCE_LEAF_ID, "scope": "finalize_time"},
        ]
        primary_leaf_id = SURPLUS_EFFICIENCY_LEAF_ID
        admission_leaf_ids = [SURPLUS_EFFICIENCY_LEAF_ID]
        reference_provider_ids = [
            DOMAIN_PREDICATE_ID,
            SURPLUS_EFFICIENCY_SCORER_ID,
            FEASIBLE_AGREEMENT_SCORER_ID,
            PROTOCOL_COMPLIANCE_SCORER_ID,
        ]
    else:
        # termsbench.nodeal's static leaf set: FAGR- (primary, sole
        # admission), CritViol% -- both finalize_time, neither
        # case_conditional.
        leaves = [
            {"leaf_id": NO_DEAL_AGREEMENT_LEAF_ID, "scope": "finalize_time"},
            {"leaf_id": PROTOCOL_COMPLIANCE_LEAF_ID, "scope": "finalize_time"},
        ]
        primary_leaf_id = NO_DEAL_AGREEMENT_LEAF_ID
        admission_leaf_ids = [NO_DEAL_AGREEMENT_LEAF_ID]
        reference_provider_ids = [
            DOMAIN_PREDICATE_ID,
            NO_DEAL_AGREEMENT_SCORER_ID,
            PROTOCOL_COMPLIANCE_SCORER_ID,
        ]
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID_BY_REGIME[regime],
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID_BY_REGIME[regime],
            },
            "environment": {
                "topology": "bilateral_alternating_offer",
                "phase_specs": [AGENT_PHASE, COUNTERPART_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "agent": {"testable": True, "scripted_policies": ["scripted"]},
                "counterpart": {
                    "testable": False,
                    "scripted_policies": ["termsbench_counterpart_kernel_v1"],
                },
            },
            "measurement": {
                # This family version's own headline estimand -- SE+ for
                # Overlap, FAGR- for No-deal (docs/termsbench_migration_plan.md).
                # Every case admitted by this instance's validate_payload has
                # this regime (self.regime == regime), so this id is never
                # vacuous for any case this family version ever scores --
                # unlike the retired single-manifest design, where the same
                # field was fixed at the Overlap value even for No-deal cases.
                "primary_estimand": PRIMARY_ESTIMAND_BY_REGIME[regime],
                "measurement_kind": "comparative_or_human_judged",
                "direction": direction,
                "outcome_support": outcome_support,
                "bound_status": "not_demonstrated",
                # kernel_scoring_contract_spec.md section 3: every leaf this
                # family version publishes at finalize time, exactly one
                # primary, and precisely the leaves that gate admission --
                # declared here, the one source of truth, never inferred
                # from TermsBenchScorer.__call__ or a test fixture. See
                # docs/termsbench_adapter_status.md's "Leaf policy" section
                # for why this leaf is primary and why it alone gates
                # admission.
                "leaves": leaves,
                "primary_leaf_id": primary_leaf_id,
                "admission_leaf_ids": admission_leaf_ids,
            },
            "scoring": {
                "scorer_id": SCORER_ID_BY_REGIME[regime],
                "reference_provider_ids": reference_provider_ids,
            },
        }
    )


def register_plugin(
    registry: PluginRegistry, *, regime: str, plugin: "TermsBenchPlugin | None" = None
) -> "TermsBenchPlugin":
    """Register one exact family/version binding in the kernel registry.

    ``regime`` is required (no default): a caller must say which of the two
    split family versions it is registering, never leave it implicit.

    A supplied ``plugin``'s own ``regime`` must match ``regime`` exactly: the
    manifest returned by ``family_manifest(regime)`` declares that regime's
    own static leaf set/primary/admission, and binding it to a plugin built
    for the OTHER regime would register (say) the overlap manifest against
    a nodeal validator/scorer -- a nodeal payload would then be accepted
    and scored under the overlap identity, silently. Rejected here, before
    registration, never left for a mismatched receipt to surface later.
    """
    if plugin is None:
        plugin = TermsBenchPlugin(regime=regime)
    elif plugin.regime != regime:
        raise ValueError(
            f"plugin.regime {plugin.regime!r} does not match the manifest "
            f"regime {regime!r} being registered for it"
        )
    registry.register_trusted(family_manifest(regime), plugin)
    return plugin


class TermsBenchPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``.

    One instance is bound to exactly one regime, fixed at construction --
    ``termsbench.overlap`` and ``termsbench.nodeal`` are two separate
    ``TermsBenchPlugin(regime=...)`` instances, each registered under its own
    manifest (``register_plugin``), never one instance shared across both.
    """

    def __init__(self, *, regime: str) -> None:
        if regime not in REGIMES:
            raise ValueError(f"unknown regime: {regime!r}")
        self.regime = regime

    # -- validate_payload ---------------------------------------------------

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if data.get("regime") not in ("overlap", "nodeal"):
            raise ValueError("payload.regime must be 'overlap' or 'nodeal'")
        if data["regime"] != self.regime:
            # Ruling R13 rule 1's split: a wrong-regime case can no longer
            # reach a family version's scorer at all -- not even as a named
            # "wrong_regime" invalid_measurement (the rejected design,
            # tag termsbench-attempt1). It is rejected here, at validation,
            # before any measurement machinery ever sees it.
            raise ValueError(
                f"payload.regime {data['regime']!r} does not match this family "
                f"version's own regime {self.regime!r} -- "
                f"termsbench.{self.regime} only accepts {self.regime!r} cases"
            )
        family = data.get("family")
        if family not in k.FAMILY_PRESETS:
            raise ValueError(f"payload.family must be one of {list(k.FAMILY_PRESETS)}")
        if not isinstance(data.get("horizon"), int) or data["horizon"] <= 0:
            raise ValueError("payload.horizon must be a positive integer")
        if data.get("chi") not in ("agent_opens", "counterpart_opens"):
            raise ValueError("payload.chi must be 'agent_opens' or 'counterpart_opens'")

        agent = data.get("agent")
        if not isinstance(agent, Mapping) or agent.get("role") not in ("buyer", "seller"):
            raise ValueError("payload.agent.role must be 'buyer' or 'seller'")
        if not _finite_number(agent.get("r_a")):
            raise ValueError("payload.agent.r_a must be a finite number")

        t_b = data.get("t_b")
        if not isinstance(t_b, Mapping):
            raise ValueError("payload.t_b must be an object")
        if not _finite_number(t_b.get("r_b")):
            raise ValueError("payload.t_b.r_b must be a finite number")
        kappa_b = t_b.get("kappa_b")
        if not _finite_number(kappa_b) or not 0.0 <= float(kappa_b) <= 1.0:
            raise ValueError("payload.t_b.kappa_b must be in [0, 1]")
        if t_b.get("eta_b") not in k.STANCE_TYPES:
            raise ValueError(f"payload.t_b.eta_b must be one of {k.STANCE_TYPES}")

        if data.get("counterpart_role") not in ("buyer", "seller"):
            raise ValueError("payload.counterpart_role must be 'buyer' or 'seller'")
        if data["counterpart_role"] == agent["role"]:
            raise ValueError("payload.counterpart_role must differ from payload.agent.role")

        price_bounds = data.get("price_bounds")
        if not isinstance(price_bounds, Mapping):
            raise ValueError("payload.price_bounds must be an object")
        p_min, p_max = price_bounds.get("p_min"), price_bounds.get("p_max")
        if not _finite_number(p_min) or not _finite_number(p_max) or not p_min < p_max:
            raise ValueError("payload.price_bounds must satisfy p_min < p_max")

        opening_harshness = data.get("opening_harshness")
        if not _finite_number(opening_harshness) or not 0.0 <= float(opening_harshness) <= 1.0:
            raise ValueError("payload.opening_harshness must be in [0, 1]")

        if not isinstance(data.get("difficulty_score"), (int, float)):
            raise ValueError("payload.difficulty_score must be a number")
        if not isinstance(data.get("hyperparameters"), Mapping):
            raise ValueError("payload.hyperparameters must be an object")

        return data

    # -- initial_state / phases / eligible_actors ---------------------------

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        """Build the initial family state for one episode.

        The second parameter is named ``run`` (not ``cell``) to match every
        other family's own ``initial_state`` hook -- required because
        ``task.evaluation._replay_family_trajectory`` calls
        ``plugin.initial_state(family_case, run=None)`` by keyword
        (kernel_scoring_contract_spec.md's ``replay_family_scoring_input``
        contract); the live scheduler (``task.scheduler.run_episode``) still
        passes this positionally, so this rename does not change what value
        actually arrives here.
        """
        del family_case, run
        return {
            "round": 1,
            "agent_offers": [],
            "counterpart_offers": [],
            "termination": None,
            "final_price": None,
            "critical_violations": {
                "price_bound": False,
                "individual_rationality": False,
                "invalid_action": False,
            },
            "secondary_violations": {"monotonicity": False, "turn_budget": False},
            "malformed_action_schema": False,
            "transcript": [],
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        horizon = int(family_case["horizon"])
        agent_phase = PhaseSpec(
            phase_id=AGENT_PHASE,
            actor_selector="agent",
            mode="single",
            observation_schema_by_role={"agent": "termsbench_agent_observation_v1"},
            action_schema_by_role={"agent": "termsbench_agent_action_v1"},
            max_logical_actions=horizon,
            invalid_action_policy="family_defined",
            next_phases=(COUNTERPART_PHASE,),
        )
        counterpart_phase = PhaseSpec(
            phase_id=COUNTERPART_PHASE,
            actor_selector="counterpart",
            mode="single",
            observation_schema_by_role={"counterpart": "termsbench_counterpart_observation_v1"},
            action_schema_by_role={"counterpart": "termsbench_counterpart_action_v1"},
            max_logical_actions=horizon,
            invalid_action_policy="family_defined",
            next_phases=(AGENT_PHASE,),
        )
        if family_case["chi"] == "counterpart_opens":
            return (counterpart_phase, agent_phase)
        return (agent_phase, counterpart_phase)

    def eligible_actors(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any], phase: PhaseSpec
    ) -> tuple[str, ...]:
        del family_case, state
        if phase.phase_id == AGENT_PHASE:
            return ("agent",)
        if phase.phase_id == COUNTERPART_PHASE:
            return ("counterpart",)
        raise ValueError(f"unknown phase: {phase.phase_id}")

    # -- observe -------------------------------------------------------------

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        if phase.phase_id == AGENT_PHASE and seat_id == "agent":
            # The agent never observes t_B, family, or the raw cue labels
            # (spec section 2.2.1/2.2.2): only prices and rendered messages.
            return {
                "role": family_case["agent"]["role"],
                "r_a": family_case["agent"]["r_a"],
                "price_bounds": dict(family_case["price_bounds"]),
                "horizon": family_case["horizon"],
                "round": state["round"],
                "agent_offers": list(state["agent_offers"]),
                "counterpart_offers": list(state["counterpart_offers"]),
                "transcript": [dict(entry) for entry in state["transcript"]],
            }
        if phase.phase_id == COUNTERPART_PHASE and seat_id == "counterpart":
            # The counterpart seat is our own simulator, not a tested role
            # (FamilyManifest.roles.counterpart.testable == False): it needs
            # the full private type to realize the kernel in kernel.py.
            return {
                "family": family_case["family"],
                "agent_role": family_case["agent"]["role"],
                "counterpart_role": family_case["counterpart_role"],
                "t_b": dict(family_case["t_b"]),
                "price_bounds": dict(family_case["price_bounds"]),
                "opening_harshness": family_case["opening_harshness"],
                "horizon": family_case["horizon"],
                "round": state["round"],
                "agent_offers": list(state["agent_offers"]),
                "counterpart_offers": list(state["counterpart_offers"]),
            }
        raise ValueError(f"seat {seat_id!r} is not active in phase {phase.phase_id!r}")

    # -- parse_action ---------------------------------------------------------

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, state
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)

        if phase.phase_id == AGENT_PHASE and seat_id == "agent":
            decision = raw.get("decision")
            if decision not in _DECISIONS:
                return ParseResult.failure("invalid_decision")
            price = raw.get("price")
            if decision == "offer":
                if not _finite_number(price):
                    return ParseResult.failure("offer_requires_price")
                price = float(price)
            else:
                if price is not None:
                    return ParseResult.failure("price_forbidden_for_non_offer")
            message = raw.get("message", "")
            if not isinstance(message, str):
                return ParseResult.failure("invalid_message")
            return ParseResult.success(
                {"decision": decision, "price": price, "message": message}
            )

        if phase.phase_id == COUNTERPART_PHASE and seat_id == "counterpart":
            resolved = raw.get("resolved")
            if resolved not in ("accept", "reject", "offer", "timeout"):
                return ParseResult.failure("invalid_resolved_action")
            price = raw.get("price")
            if resolved in ("offer", "accept"):
                # App. B.3 case 3: an accepted outcome binds at the agent's
                # proposed price, so "accept" carries a price too, unlike
                # "reject" (walk-away) and "timeout" (both -> disagreement).
                if not _finite_number(price):
                    return ParseResult.failure("offer_requires_price")
                price = float(price)
            elif price is not None:
                return ParseResult.failure("price_forbidden_for_non_offer")
            draws = raw.get("draws")
            if not isinstance(draws, Mapping):
                return ParseResult.failure("missing_draws")
            round_k = raw.get("round")
            if not isinstance(round_k, int) or isinstance(round_k, bool) or round_k <= 0:
                return ParseResult.failure("invalid_round")
            message = raw.get("message", "")
            if not isinstance(message, str):
                return ParseResult.failure("invalid_message")
            return ParseResult.success(
                {
                    "resolved": resolved,
                    "price": price,
                    "sentiment_cue": raw.get("sentiment_cue"),
                    "strategic_cue": raw.get("strategic_cue"),
                    "message": message,
                    "round": round_k,
                    "draws": {str(key): value for key, value in draws.items()},
                }
            )

        return ParseResult.failure("seat_phase_mismatch")

    # -- legal ----------------------------------------------------------------

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case
        expected = "agent" if phase.phase_id == AGENT_PHASE else "counterpart"
        if seat_id != expected:
            return LegalityResult.illegal("seat_phase_mismatch")
        if (
            phase.phase_id == AGENT_PHASE
            and action["decision"] == "accept"
            and not state["counterpart_offers"]
        ):
            # App. B.3 / F.4: choosing Accept when no counterpart offer has
            # been observed. Legal (not raised) so step() can bind it to the
            # adapter-defined AgreementViolation outcome (spec section 4,
            # golden 3) instead of the scheduler hard-failing the episode.
            return LegalityResult.illegal("accept_without_counterpart_offer")
        return LegalityResult.legal_action()

    # -- step -----------------------------------------------------------------

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        new_state = _plain(state)

        if phase.phase_id == AGENT_PHASE:
            return self._step_agent(family_case, state, new_state, actions["agent"])
        if phase.phase_id == COUNTERPART_PHASE:
            return self._step_counterpart(family_case, state, new_state, actions["counterpart"])
        raise ValueError(f"unknown phase: {phase.phase_id}")

    def _step_agent(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        new_state: dict[str, Any],
        envelope: Any,
    ) -> TransitionResult:
        if not envelope.valid:
            if envelope.parse is not None and not envelope.parse.ok:
                new_state["malformed_action_schema"] = True
            new_state["critical_violations"]["invalid_action"] = True
            _set_termination(new_state, "agreement_violation")
            new_state["final_price"] = None
            return TransitionResult(
                state=new_state,
                next_phase_id=None,
                consequences={"valid": False},
            )

        action = envelope.action
        decision, price, message = action["decision"], action["price"], action["message"]
        new_state["transcript"].append(
            {"speaker": "agent", "decision": decision, "price": price, "message": message}
        )
        agent_role = family_case["agent"]["role"]
        r_a = float(family_case["agent"]["r_a"])

        if decision == "accept":
            f = state["counterpart_offers"][-1]
            ir_violation = (f > r_a) if agent_role == "buyer" else (f < r_a)
            if ir_violation:
                new_state["critical_violations"]["individual_rationality"] = True
            _set_termination(new_state, "agent_accept")
            new_state["final_price"] = f
            return TransitionResult(state=new_state, next_phase_id=None, consequences={"decision": decision})

        if decision == "reject":
            _set_termination(new_state, "agent_reject")
            new_state["final_price"] = None
            return TransitionResult(state=new_state, next_phase_id=None, consequences={"decision": decision})

        # decision == "offer"
        p_min = float(family_case["price_bounds"]["p_min"])
        p_max = float(family_case["price_bounds"]["p_max"])
        if price < p_min or price > p_max:
            new_state["critical_violations"]["price_bound"] = True
        ir_violation = (price > r_a) if agent_role == "buyer" else (price < r_a)
        if ir_violation:
            new_state["critical_violations"]["individual_rationality"] = True
        if state["agent_offers"]:
            last = state["agent_offers"][-1]
            mono_violation = (price < last) if agent_role == "buyer" else (price > last)
            if mono_violation:
                new_state["secondary_violations"]["monotonicity"] = True
        new_state["agent_offers"] = list(state["agent_offers"]) + [price]
        return TransitionResult(
            state=new_state, next_phase_id=COUNTERPART_PHASE, consequences={"decision": decision, "price": price}
        )

    def _step_counterpart(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        new_state: dict[str, Any],
        envelope: Any,
    ) -> TransitionResult:
        if not envelope.valid:
            raise RuntimeError(
                "termsbench's own counterpart harness produced an invalid action; "
                "this is an internal error, not a scoreable episode outcome"
            )
        action = envelope.action
        round_k = action["round"]

        # Replay-and-verify (spec section 3.1/section 5): re-execute the same
        # formula code on the sealed random draws and confirm it reproduces
        # exactly what the harness claimed, instead of trusting it blindly.
        recomputed = k.resolve_counterpart_turn(
            round_k=round_k,
            horizon=family_case["horizon"],
            family=family_case["family"],
            agent_role=family_case["agent"]["role"],
            counterpart_role=family_case["counterpart_role"],
            r_b=float(family_case["t_b"]["r_b"]),
            kappa_b=float(family_case["t_b"]["kappa_b"]),
            eta_b=family_case["t_b"]["eta_b"],
            p_min=float(family_case["price_bounds"]["p_min"]),
            p_max=float(family_case["price_bounds"]["p_max"]),
            opening_harshness=float(family_case["opening_harshness"]),
            agent_offers=tuple(state["agent_offers"]),
            counterpart_offers=tuple(state["counterpart_offers"]),
            draws=action["draws"],
        )
        claimed = (action["resolved"], action["price"], action["sentiment_cue"], action["strategic_cue"])
        actual = (recomputed.resolved, recomputed.price, recomputed.sentiment_cue, recomputed.strategic_cue)
        if claimed != actual:
            raise RuntimeError(
                "counterpart replay mismatch: harness claimed "
                f"{claimed!r} but recomputing kernel.resolve_counterpart_turn from the "
                f"sealed draws gives {actual!r}"
            )

        new_state["transcript"].append(
            {
                "speaker": "counterpart",
                "decision": recomputed.resolved,
                "price": recomputed.price,
                "message": action["message"],
            }
        )

        if recomputed.resolved == "accept":
            f = state["agent_offers"][-1]
            _set_termination(new_state, "counterpart_accept")
            new_state["final_price"] = f
            return TransitionResult(state=new_state, next_phase_id=None, consequences={"decision": "accept"})
        if recomputed.resolved == "reject":
            _set_termination(new_state, "counterpart_walk_away")
            new_state["final_price"] = None
            return TransitionResult(state=new_state, next_phase_id=None, consequences={"decision": "reject"})
        if recomputed.resolved == "timeout":
            _set_termination(new_state, "timeout")
            new_state["final_price"] = None
            return TransitionResult(state=new_state, next_phase_id=None, consequences={"decision": "timeout"})

        # resolved == "offer": the episode continues into another round --
        # only here does the round cursor advance (Codex review finding 4:
        # advancing it unconditionally, before this branch, made every
        # counterpart-side termination -- Accept, Reject, and Timeout alike
        # -- report one more round than was actually used).
        new_state["round"] = state["round"] + 1
        new_state["counterpart_offers"] = list(state["counterpart_offers"]) + [recomputed.price]
        return TransitionResult(
            state=new_state, next_phase_id=AGENT_PHASE, consequences={"decision": "offer", "price": recomputed.price}
        )

    # -- terminal / outcome ----------------------------------------------------

    def terminal(self, family_case: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        return {
            "reason": reason,
            "final_price": state["final_price"],
            "rounds_used": state["round"],
            "critical_violations": dict(state["critical_violations"]),
            "secondary_violations": dict(state["secondary_violations"]),
            "malformed_action_schema": state["malformed_action_schema"],
        }

    def outcome(self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]) -> dict[str, Any]:
        agent_role = family_case["agent"]["role"]
        r_a = float(family_case["agent"]["r_a"])
        r_b = float(family_case["t_b"]["r_b"])
        delta = (r_a - r_b) if agent_role == "buyer" else (r_b - r_a)
        return {
            "termination_reason": terminal["reason"],
            "final_price": terminal["final_price"],
            "rounds_used": terminal["rounds_used"],
            "critical_violations": dict(terminal["critical_violations"]),
            "secondary_violations": dict(terminal["secondary_violations"]),
            "malformed_action_schema": terminal["malformed_action_schema"],
            "regime": family_case["regime"],
            "family": family_case["family"],
            "agent_role": agent_role,
            "r_a": r_a,
            "delta": delta,
        }

    # -- build_scorer / build_reference_providers / generator -------------------

    def build_scorer(self, family_case: Mapping[str, Any]) -> TermsBenchScorer:
        """Return the declared measurement leaves plus their scorers
        (``measurement.py``, spec section 2): 3 leaves (SE+, AGR+, CritViol%)
        for a ``termsbench.overlap`` case, 2 (FAGR-, CritViol%) for a
        ``termsbench.nodeal`` case -- guaranteed by this regime, since
        ``validate_payload`` rejects any other. ``task.evaluation.
        finalize_family_execution`` calls the returned ``TermsBenchScorer``
        directly (``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``, per
        kernel_scoring_contract_spec.md section 1); ``TermsBenchScorer.__call__``
        is the seam that satisfies that call. Each leaf's own named method is
        still exercised directly by ``tests/test_termsbench_measurement.py``'s
        goldens.
        """
        return build_measurement_scorer(family_case)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        # Appendix D's Oracle-Cue Bayes-optimal DP is explicitly deferred
        # (spec section 6): no objective_reference/oracle-gap leaf tonight.
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None


__all__ = [
    "AGENT_PHASE",
    "COUNTERPART_PHASE",
    "PLUGIN_ID_BY_REGIME",
    "PRIMARY_ESTIMAND_BY_REGIME",
    "SCORER_ID_BY_REGIME",
    "TermsBenchPlugin",
    "family_manifest",
    "register_plugin",
]
