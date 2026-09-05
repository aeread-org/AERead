"""Native shared-runner adapter for consent-gated IR cycle construction.

The agent controls participant ordering in a barter cycle.  Agent ``0`` gives
good ``0`` to the first participant, each participant gives its own good to the
next, and the final participant gives its good to agent ``0``.  A proposed
cycle executes only when every participant strictly prefers the received good
to the good surrendered.

This ports the economic kernel and deterministic oracle from the private
``eval_dev/consent_ir_env.py`` prototype.  The execution adapter, action
schema, and typed measurement contracts are native AERead implementations.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from itertools import permutations
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import (
    EstimandSpec,
    FamilyScoreSet,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

FAMILY_ID = "consent_ir_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "consent_ir_environment"
SCORER_ID = "consent_ir_scorer_v1"
ORACLE_ID = "consent_ir_exact_cycle_oracle_v1"
PHASE_ID = "propose_cycle"
GAIN_LEAF_ID = "consent_ir_buyer_gain_leaf"
IR_LEAF_ID = "consent_ir_all_participant_ir_leaf"


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def cycle_all_ir(cycle: Sequence[int], values: Sequence[Sequence[float]]) -> bool:
    """Return whether a non-trivial, unique cycle strictly benefits everyone."""
    if len(cycle) < 2 or cycle[0] != 0 or len(set(cycle)) != len(cycle):
        return False
    if any(agent < 0 or agent >= len(values) for agent in cycle):
        return False
    return all(
        values[agent][cycle[index - 1]] > values[agent][agent]
        for index, agent in enumerate(cycle)
    )


def buyer_gain(cycle: Sequence[int], values: Sequence[Sequence[float]]) -> float:
    """Agent 0 receives the final participant's good and gives good 0."""
    if len(cycle) < 2:
        return 0.0
    return float(values[0][cycle[-1]]) - float(values[0][0])


def ir_oracle(values: Sequence[Sequence[float]]) -> dict[str, Any]:
    """Enumerate the exact buyer-optimal all-IR cycle for the visible world."""
    others = range(1, len(values))
    best_gain = 0.0
    best_cycle = (0,)
    for length in range(1, len(values)):
        for suffix in permutations(others, length):
            cycle = (0, *suffix)
            gain = buyer_gain(cycle, values)
            if cycle_all_ir(cycle, values) and gain > best_gain:
                best_gain = gain
                best_cycle = cycle
    return {"max_buyer_gain": best_gain, "best_cycle": list(best_cycle)}


def _validate_values(raw: Any) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("payload.values must be a square matrix with at least two agents")
    size = len(raw)
    values: list[list[float]] = []
    for row in raw:
        if not isinstance(row, list) or len(row) != size:
            raise ValueError("payload.values must be square")
        if not all(_finite_number(item) for item in row):
            raise ValueError("payload.values entries must be finite numbers")
        values.append([float(item) for item in row])
    if ir_oracle(values)["max_buyer_gain"] <= 0:
        raise ValueError("development cases must contain a beneficial all-IR cycle")
    return values


def _source_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _implementation(identifier: str) -> ImplementationRef:
    return ImplementationRef(identifier, "1.0.0", _source_digest())


def _domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id="consent_ir_visible_cycle_domain",
        domain_version="1.0.0",
        schema_ref="consent_ir_v1/outcome/1",
        predicate=_implementation("consent_ir_outcome_domain_predicate_v1"),
    )


def _case_reference_digest(case: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes({"values": case["values"]})).hexdigest()


def buyer_gain_leaf(case: Mapping[str, Any]) -> MeasurementLeafSpec:
    domain = _domain()
    estimand = EstimandSpec(
        estimand_id="consent_ir_buyer_gain",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="utility",
        validity_domain=domain,
    )
    return MeasurementLeafSpec(
        leaf_id=GAIN_LEAF_ID,
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id=ORACLE_ID,
                reference_version="1.0.0",
                reference_kind="exact_optimum",
                input_scope="terminal_state",
                units="utility",
                source_sha256=_case_reference_digest(case),
                implementation=_implementation(ORACLE_ID),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id=estimand.estimand_id,
                objective_version=estimand.estimand_version,
                direction=estimand.direction,
                units=estimand.units,
                feasible_set="unique cycles beginning with agent 0 that strictly benefit every participant",
                information_set="the complete valuation matrix shown to agent 0",
                horizon="one cycle proposal",
                environment_condition="deterministic barter execution with strict individual rationality",
                opponent_condition="counterparties deterministically consent exactly when strictly better off",
                validity_domain=domain,
            ),
        ),
        scorer=_implementation(SCORER_ID),
    )


def ir_leaf(case: Mapping[str, Any]) -> MeasurementLeafSpec:
    domain = _domain()
    return MeasurementLeafSpec(
        leaf_id=IR_LEAF_ID,
        leaf_version="1.0.0",
        estimand=EstimandSpec(
            estimand_id="consent_ir_all_participant_ir",
            estimand_version="1.0.0",
            input_scope="terminal_state",
            direction="maximize",
            units="indicator",
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family="rule_constraint",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="consent_ir_strict_gain_rule_v1",
                reference_version="1.0.0",
                reference_kind="constraint_satisfaction",
                input_scope="terminal_state",
                units="indicator",
                source_sha256=_case_reference_digest(case),
                implementation=_implementation("consent_ir_strict_gain_rule_v1"),
            ),
        ),
        scorer=_implementation(SCORER_ID),
    )


class ConsentIRScorer:
    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case

    def __call__(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        gain = outcome.get("buyer_gain") if isinstance(outcome, Mapping) else None
        optimum = outcome.get("max_buyer_gain") if isinstance(outcome, Mapping) else None
        is_ir = outcome.get("all_participant_ir") if isinstance(outcome, Mapping) else None
        reasons = []
        if not _finite_number(gain) or not _finite_number(optimum):
            reasons.append("buyer gain and optimum must be finite")
        if not isinstance(is_ir, bool):
            reasons.append("all_participant_ir must be boolean")
        if not reasons and (float(gain) < 0 or float(gain) > float(optimum) + 1e-9):
            reasons.append("buyer gain must lie between zero and the exact optimum")
        if reasons:
            scores = tuple(
                ScoreEnvelope(
                    status="invalid_measurement",
                    leaf=leaf,
                    primary=None,
                    metrics={},
                    reference_values={},
                    validity=ValidityReport("invalid", tuple(reasons)),
                    evidence_refs=evidence_refs,
                )
                for leaf in (buyer_gain_leaf(self.case), ir_leaf(self.case))
            )
        else:
            efficiency = float(gain) / float(optimum) if float(optimum) > 0 else 0.0
            scores = (
                ScoreEnvelope(
                    status="ok",
                    leaf=buyer_gain_leaf(self.case),
                    primary=MetricValue(float(gain), "utility"),
                    metrics={"efficiency": MetricValue(efficiency, "fraction")},
                    reference_values={"exact_optimum": MetricValue(float(optimum), "utility")},
                    validity=ValidityReport("valid"),
                    evidence_refs=evidence_refs,
                    utility_by_seat={"buyer": MetricValue(float(gain), "utility")},
                ),
                ScoreEnvelope(
                    status="ok",
                    leaf=ir_leaf(self.case),
                    primary=MetricValue(1.0 if is_ir else 0.0, "indicator"),
                    metrics={},
                    reference_values={},
                    validity=ValidityReport("valid"),
                    evidence_refs=evidence_refs,
                ),
            )
        return FamilyScoreSet(
            primary_leaf_id=GAIN_LEAF_ID,
            scores=scores,
            admission_leaf_ids=(GAIN_LEAF_ID, IR_LEAF_ID),
        )


def family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
            "environment": {
                "topology": "single_agent_visible_ir_cycle_construction",
                "phase_specs": [PHASE_ID],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {"buyer": {"testable": True, "scripted_policies": ["scripted"]}},
            "measurement": {
                "primary_estimand": "consent_ir_buyer_gain",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "bound_status": "exact_same_information_optimum",
                "outcome_support": "nonnegative_utility",
            },
            "scoring": {"scorer_id": SCORER_ID, "oracle_id": ORACLE_ID},
        }
    )


def register_plugin(registry: PluginRegistry, *, plugin: "ConsentIRPlugin | None" = None) -> "ConsentIRPlugin":
    resolved = plugin or ConsentIRPlugin()
    registry.register_trusted(family_manifest(), resolved)
    return resolved


class ConsentIRPlugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != {"values"}:
            raise ValueError("payload must contain exactly values")
        return {"values": _validate_values(data["values"])}

    def initial_state(self, case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        del case, run
        return {"cycle": None, "parse_valid": None, "done": False}

    def phases(self, case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del case
        return (
            PhaseSpec(
                phase_id=PHASE_ID,
                actor_selector="buyer",
                mode="single",
                observation_schema_by_role={"buyer": "consent_ir_visible_values_v1"},
                action_schema_by_role={"buyer": "consent_ir_cycle_v1"},
                max_logical_actions=1,
                invalid_action_policy="family_defined",
                next_phases=(),
            ),
        )

    def eligible_actors(self, case, state, phase) -> tuple[str, ...]:
        del case, state, phase
        return ("buyer",)

    def observe(self, case, state, seat, phase) -> dict[str, Any]:
        del state, seat, phase
        return {"buyer_id": 0, "held_good": 0, "values": _plain(case["values"])}

    def parse_action(self, case, state, seat, phase, response) -> ParseResult:
        del state, seat, phase
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            data = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        if not isinstance(data, dict) or set(data) != {"cycle"}:
            return ParseResult.failure("malformed_cycle")
        cycle = data["cycle"]
        if not isinstance(cycle, list) or any(
            isinstance(item, bool) or not isinstance(item, int) for item in cycle
        ):
            return ParseResult.failure("malformed_cycle")
        return ParseResult.success({"cycle": [0, *cycle]})

    def legal(self, case, state, seat, phase, action) -> LegalityResult:
        del state, seat, phase
        cycle = action["cycle"]
        if len(cycle) < 2:
            return LegalityResult.illegal("empty_cycle")
        if len(set(cycle)) != len(cycle):
            return LegalityResult.illegal("duplicate_participant")
        if any(agent < 0 or agent >= len(case["values"]) for agent in cycle):
            return LegalityResult.illegal("unknown_participant")
        return LegalityResult.legal_action()

    def step(self, case, state, phase, actions) -> TransitionResult:
        del case, phase
        envelope = actions["buyer"]
        next_state = dict(state)
        next_state["cycle"] = list(envelope.action["cycle"]) if envelope.valid else [0]
        next_state["parse_valid"] = bool(envelope.valid)
        next_state["done"] = True
        return TransitionResult(state=next_state, next_phase_id=None)

    def terminal(self, case, state) -> dict[str, Any] | None:
        if not state["done"]:
            return None
        cycle = state["cycle"]
        is_ir = cycle_all_ir(cycle, case["values"])
        optimum = ir_oracle(case["values"])
        gain = buyer_gain(cycle, case["values"]) if is_ir else 0.0
        return {
            "reason": "submitted",
            "cycle": list(cycle),
            "parse_valid": state["parse_valid"],
            "all_participant_ir": is_ir,
            "buyer_gain": max(0.0, gain),
            **optimum,
        }

    def outcome(self, case, terminal) -> dict[str, Any]:
        del case
        return _plain(terminal)

    def build_scorer(self, case) -> ConsentIRScorer:
        return ConsentIRScorer(case)

    def build_reference_providers(self, case) -> tuple[Any, ...]:
        del case
        return ()

    def generator(self):
        return None
