"""Measurement declarations for the econevals adapter (spec section 2).

Every track composes two leaves as a ``hybrid_gate``
(``docs/verifier_taxonomy.md`` section 10): a deterministic legality/
feasibility gate, then the objective leaf -- reported as a vector, never
collapsed into one blended scalar. Both leaves are declared once per track
(:func:`build_gate_leaf`/:func:`build_objective_leaf`), and scored per case
from that case's own terminal state (:class:`EconevalsScorer`).

**Gate leaf** (identical shape across all three tracks): ``rule_constraint``/
``constraint_satisfaction``, ``input_scope="answer"``, ``units="pass"``,
``evaluation_class="deterministic"``. The scorer for procurement/scheduling
is the pinned *upstream* legality primitive (``evaluate_alloc``/
``is_valid_matching``) -- pinned by reusing ``cases.MODULE_SHA256``'s own
module hash for the file that primitive lives in, never re-hashing this
adapter's own bridge file (spec section 2's worked example pins
``opt_solver.py`` directly). Pricing's gate has no upstream primitive to
delegate to at all (upstream's own ``set_prices`` tool never checks price
sign -- verified in recon against ``run_pricing_experiment.py``): it is
AERead's own declared rule ("prices non-negative, keyed to declared
product_ids", spec section 2's table), computed locally in
:func:`score_pricing` and pinned to this file's own hash instead.

**Objective leaf** (per spec section 2's table): ``objective_reference``/
``exact_optimum``, ``input_scope="terminal_state"``, scored from the FINAL
period's own recorded attempt only (``horizon`` per track below) --
``primary`` is the achieved value ``V_agent`` in the track's own native
units (never a normalized/blended ratio), and ``reference_values["v_star"]``
is the case's own pinned exact optimum. Regret (``V* - V_agent``) or any
headroom-style ratio is left for a consumer to compute from these two typed
values; this module deliberately never computes ``headroom_capture`` itself
-- ``environment.py``'s family manifest already documents why
(verifier_taxonomy.md section 5.3: "not automatically a score in [0, 1]",
and no ``baseline_headroom`` reference/leaf is declared anywhere in spec
section 2's table for this milestone). The hybrid-gate composition itself
is what "exercises the zero-headroom edge" for golden 5's hand-authored,
already-optimal instance: because nothing here ever divides by
``V_UB - B``, that instance scores cleanly (``V_agent == V_star``, both
finite) without any of the machinery a headroom-ratio scorer would need to
special-case.

One documented deviation from the literal spec text: section 2's worked
example writes ``estimand_id="econevals_procurement_utility"`` for the
estimand but ``objective_id="econevals_procurement_utility_v1"`` (a
different string, with a ``_v1`` suffix) for the paired
``ObjectiveScopeSpec``. The kernel's real
``MeasurementLeafSpec.__post_init__`` requires
``objective_scope.objective_id == estimand.estimand_id`` exactly (verified
empirically: constructing the spec's literal two IDs raises
``MeasurementContractError``). This module uses one identical id for both
fields instead of introducing the ``_v1`` suffix.

Track-specific pieces are data-driven (one small lookup table per
dimension) rather than three near-duplicate builder functions, mirroring
how ``cases.py`` already factors "shared shape, per-track parameters" for
generation.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.measurement import (
    EstimandSpec,
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
from aeread.shared_runner.resolver import canonical_json_bytes

from .cases import MODULE_SHA256, TRACKS

LEAF_VERSION = "0.1.0"
ESTIMAND_VERSION = "0.1.0"
REFERENCE_VERSION = "0.1.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "econevals_base_v1"
DOMAIN_VERSION = "0.1.0"

# --------------------------------------------------------------------------
# Per-track declarative tables (spec section 2's per-track table).
# --------------------------------------------------------------------------

_OBJECTIVE_ESTIMAND_ID: Mapping[str, str] = {
    "procurement": "econevals_procurement_utility",
    "scheduling": "econevals_scheduling_blocking_pairs",
    "pricing": "econevals_pricing_profit",
}
_OBJECTIVE_DIRECTION: Mapping[str, str] = {
    "procurement": "maximize",
    "scheduling": "minimize",
    "pricing": "maximize",
}
_OBJECTIVE_UNITS: Mapping[str, str] = {
    "procurement": "workers_supported",
    "scheduling": "blocking_pairs",
    "pricing": "profit_usd",
}
_OBJECTIVE_FEASIBLE_SET: Mapping[str, str] = {
    "procurement": "alloc: Offer_id->qty with total_cost<=budget, per-entry minimums met",
    "scheduling": "matching: bijection Worker_id->Task_id over the declared worker/task ids",
    "pricing": "prices: Product_id->price, non-negative, keyed exactly to the declared product_ids",
}
_OBJECTIVE_INFORMATION_SET: Mapping[str, str] = {
    "procurement": "full menu, item groups, effectiveness, budget observable each period",
    "scheduling": (
        "worker/task ids observable each period; worker/task preference lists are never "
        "exposed by any tool (verified against upstream's own run_scheduling_experiment.py: "
        "it exposes no preference-revealing tool either) -- the agent infers them only from "
        "blocking-pair feedback on its own previously submitted matchings"
    ),
    "pricing": (
        "product ids and each period's own realized profit/quantity feedback observable; "
        "the underlying per-period demand shift (alpha/multiplier) is never exposed by any "
        "tool (verified against upstream's own run_pricing_experiment.py: it exposes no such "
        "tool either)"
    ),
}
_OBJECTIVE_HORIZON: Mapping[str, str] = {
    "procurement": "final submitted allocation (period 100)",
    "scheduling": "final submitted matching (period 100)",
    "pricing": (
        "final submitted price vector, scored against that same period's own "
        "monopoly-optimal profit (period 100)"
    ),
}
_OBJECTIVE_ENVIRONMENT_CONDITION: Mapping[str, str] = {
    "procurement": "static menu/budget fixed at instance generation",
    "scheduling": "static worker/task preference lists fixed at instance generation",
    "pricing": (
        "demand shifts every period per the instance's own alpha_list/multiplier_list, "
        "themselves fixed at instance generation"
    ),
}
# The upstream module (already sha256-pinned in cases.MODULE_SHA256) whose
# code performs each track's gate/objective primitive -- None where there is
# no upstream primitive to delegate to (pricing's gate; see module docstring).
_GATE_MODULE: Mapping[str, str | None] = {
    "procurement": "experiments/procurement/opt_solver.py",
    "scheduling": "experiments/scheduling/stable_matching_environment.py",
    "pricing": None,
}
_OBJECTIVE_MODULE: Mapping[str, str] = {
    "procurement": "experiments/procurement/opt_solver.py",
    "scheduling": "experiments/scheduling/stable_matching_environment.py",
    "pricing": "experiments/pricing/pricing_market_logic_multiproduct.py",
}
_GATE_SCORER_ID: Mapping[str, str] = {
    "procurement": "econevals_bridge.evaluate_alloc",
    "scheduling": "econevals_bridge.is_valid_matching",
    "pricing": "econevals_pricing_gate_scorer",
}
_OBJECTIVE_SCORER_ID: Mapping[str, str] = {
    "procurement": "econevals_bridge.compute_opt",
    "scheduling": "econevals_bridge.get_blocking_pairs",
    "pricing": "econevals_bridge.get_monopoly_prices",
}


def _require_track(track: str) -> str:
    if track not in TRACKS:
        raise ValueError(f"unknown track: {track!r}")
    return track


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation_from_module(implementation_id: str, module_relpath: str) -> ImplementationRef:
    """Pin an ``ImplementationRef`` to a pinned *upstream* module's own hash.

    Reuses ``cases.MODULE_SHA256`` -- never rehashes this adapter's own
    bridge file -- matching spec section 2's literal worked example
    (``compute_opt``'s ``scorer`` pins ``opt_solver.py``'s hash directly).
    """
    return ImplementationRef(
        implementation_id=implementation_id,
        version=IMPLEMENTATION_VERSION,
        content_sha256=MODULE_SHA256[module_relpath],
    )


def _implementation_from_file(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin an ``ImplementationRef`` to one of THIS adapter's own source files.

    Used only where there is no upstream primitive to delegate to (pricing's
    gate) or for the shared validity-domain predicate.
    """
    return ImplementationRef(
        implementation_id=implementation_id,
        version=IMPLEMENTATION_VERSION,
        content_sha256=_file_sha256(filename),
    )


def _validity_domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id=DOMAIN_ID,
        domain_version=DOMAIN_VERSION,
        schema_ref="econevals_base_v1/case_payload",
        predicate=_implementation_from_file("econevals_base_domain_predicate", "environment.py"),
    )


def _gate_scorer_implementation(track: str) -> ImplementationRef:
    module = _GATE_MODULE[track]
    if module is not None:
        return _implementation_from_module(_GATE_SCORER_ID[track], module)
    return _implementation_from_file(_GATE_SCORER_ID[track], "measurement.py")


# --------------------------------------------------------------------------
# Leaf construction (spec section 2).
# --------------------------------------------------------------------------


def build_gate_leaf(track: str) -> MeasurementLeafSpec:
    """The shared-shape legality/feasibility gate leaf for one track."""
    _require_track(track)
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=f"econevals_{track}_gate",
        estimand_version=ESTIMAND_VERSION,
        input_scope="answer",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    scorer = _gate_scorer_implementation(track)
    reference = ReferenceSpec(
        reference_id=f"econevals_{track}_gate_reference",
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="answer",
        units="pass",
        source_sha256=scorer.content_sha256,
        implementation=scorer,
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=f"econevals_{track}_gate_leaf",
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=scorer,
    )


def build_objective_leaf(track: str, gold_optimum: Mapping[str, Any]) -> MeasurementLeafSpec:
    """The ``exact_optimum`` objective leaf for one track's specific case.

    Takes ``gold_optimum`` (per-case, from ``payload.gold_optimum``) so the
    declared reference's ``source_sha256`` pins the exact numbers this case's
    scoring will be compared against -- not just the generic upstream module
    hash that ``MeasurementLeafSpec.scorer``/``reference.implementation``
    already carry.
    """
    _require_track(track)
    domain = _validity_domain()
    estimand_id = _OBJECTIVE_ESTIMAND_ID[track]
    direction = _OBJECTIVE_DIRECTION[track]
    units = _OBJECTIVE_UNITS[track]
    estimand = EstimandSpec(
        estimand_id=estimand_id,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction=direction,
        units=units,
        validity_domain=domain,
    )
    implementation = _implementation_from_module(_OBJECTIVE_SCORER_ID[track], _OBJECTIVE_MODULE[track])
    source_sha256 = hashlib.sha256(canonical_json_bytes(dict(gold_optimum))).hexdigest()
    reference = ReferenceSpec(
        reference_id=f"econevals_{track}_exact_optimum_reference",
        reference_version=REFERENCE_VERSION,
        reference_kind="exact_optimum",
        input_scope="terminal_state",
        units=units,
        source_sha256=source_sha256,
        implementation=implementation,
    )
    objective_scope = ObjectiveScopeSpec(
        # Deliberately identical to estimand_id -- see module docstring's
        # "documented deviation from the literal spec text".
        objective_id=estimand_id,
        objective_version=ESTIMAND_VERSION,
        direction=direction,
        units=units,
        feasible_set=_OBJECTIVE_FEASIBLE_SET[track],
        information_set=_OBJECTIVE_INFORMATION_SET[track],
        horizon=_OBJECTIVE_HORIZON[track],
        environment_condition=_OBJECTIVE_ENVIRONMENT_CONDITION[track],
        opponent_condition="none (single-agent)",
        validity_domain=domain,
    )
    verifier = VerifierSpec(
        verifier_family="objective_reference",
        evaluation_class="deterministic",
        reference=reference,
        objective_scope=objective_scope,
    )
    return MeasurementLeafSpec(
        leaf_id=f"econevals_{track}_objective_leaf",
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=implementation,
    )


def build_leaves(
    track: str, gold_optimum: Mapping[str, Any]
) -> tuple[MeasurementLeafSpec, MeasurementLeafSpec]:
    """Exactly ``(gate_leaf, objective_leaf)`` for one track -- always both."""
    return (build_gate_leaf(track), build_objective_leaf(track, gold_optimum))


# --------------------------------------------------------------------------
# Envelope helpers (shared shape across tracks).
# --------------------------------------------------------------------------


def _gate_pass(leaf: MeasurementLeafSpec, *, evidence_refs: tuple[str, ...] = ()) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "pass"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def _gate_fail(
    leaf: MeasurementLeafSpec, *, reason: str, evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """A real, scored legality failure -- a domain fact, never an economic zero.

    Distinct from :func:`_invalid_measurement`: this IS a valid measurement
    (the submission was well-formed enough to check legality on, and legality
    genuinely failed), so ``status="ok"`` with a 0.0 primary, exactly per
    spec golden 3 ("gate fails, objective is not scored") -- not
    ``invalid_measurement`` (reserved for golden 4's admission-layer failure).
    """
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(0.0, "pass", metadata={"reason": reason}),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def _invalid_measurement(
    leaf: MeasurementLeafSpec, *, reason: str, evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """The measurement_validity (admission) failure path -- never an economic zero.

    Per verifier_taxonomy.md section 9: "An invalid or missing observation
    must not be scored as an economic zero" -- spec golden 4's exact
    requirement for a submission upstream's own ``parse_dict`` cannot parse
    at all.
    """
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics={},
        reference_values={},
        validity=ValidityReport("invalid", reasons=(reason,)),
        evidence_refs=evidence_refs,
    )


def _objective_ok(
    leaf: MeasurementLeafSpec,
    *,
    value: float,
    v_star: float,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    units = leaf.estimand.units
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(float(value), units),
        metrics={},
        reference_values={"v_star": MetricValue(float(v_star), units)},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# --------------------------------------------------------------------------
# Scorers -- one recorded (terminal) attempt in, (gate, objective|None) out.
#
# None of these delegate to the bridge themselves: every value they read
# (``is_feasible``/``utility``, ``valid``/``blocking_pairs``, ``profits``)
# was already produced, once, by ``environment.py``'s live dispatch (which
# DOES delegate to the bridge) and sealed into the recorded attempt. This
# mirrors tau3.retail's own boundary: measurement.py's scorers read
# already-produced evidence, they do not re-derive it.
# --------------------------------------------------------------------------


def score_procurement(
    *,
    gate_leaf: MeasurementLeafSpec,
    objective_leaf: MeasurementLeafSpec,
    gold_optimum: Mapping[str, Any],
    attempt: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> tuple[ScoreEnvelope, ScoreEnvelope | None]:
    error = attempt.get("error")
    if error == "malformed_input":
        return (
            _invalid_measurement(gate_leaf, reason="malformed_submission", evidence_refs=evidence_refs),
            None,
        )
    if error == "illegal_action":
        # Spec's companion unit test: an unknown offer id, pre-validated by
        # environment.py before it could ever reach evaluate_alloc.
        reason = str(attempt.get("error_message") or "illegal_action")
        return _gate_fail(gate_leaf, reason=reason, evidence_refs=evidence_refs), None
    if error is not False:
        raise ValueError(f"unrecognized procurement attempt.error: {error!r}")
    if not attempt["is_feasible"]:
        reason = str(attempt.get("invalid_reason") or "infeasible")
        return _gate_fail(gate_leaf, reason=reason, evidence_refs=evidence_refs), None
    gate = _gate_pass(gate_leaf, evidence_refs=evidence_refs)
    objective = _objective_ok(
        objective_leaf,
        value=attempt["utility"],
        v_star=gold_optimum["opt_utility"],
        evidence_refs=evidence_refs,
    )
    return gate, objective


def score_scheduling(
    *,
    gate_leaf: MeasurementLeafSpec,
    objective_leaf: MeasurementLeafSpec,
    gold_optimum: Mapping[str, Any],
    attempt: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> tuple[ScoreEnvelope, ScoreEnvelope | None]:
    error = attempt.get("error")
    if error == "malformed_input":
        return (
            _invalid_measurement(gate_leaf, reason="malformed_submission", evidence_refs=evidence_refs),
            None,
        )
    if error is not False:
        raise ValueError(f"unrecognized scheduling attempt.error: {error!r}")
    if not attempt["valid"]:
        reason = str(attempt.get("reason") or "invalid_matching")
        return _gate_fail(gate_leaf, reason=reason, evidence_refs=evidence_refs), None
    gate = _gate_pass(gate_leaf, evidence_refs=evidence_refs)
    blocking_pairs = attempt["blocking_pairs"]
    objective = _objective_ok(
        objective_leaf,
        value=len(blocking_pairs),
        v_star=gold_optimum["min_blocking_pairs"],
        evidence_refs=evidence_refs,
    )
    return gate, objective


def score_pricing(
    *,
    gate_leaf: MeasurementLeafSpec,
    objective_leaf: MeasurementLeafSpec,
    instance: Mapping[str, Any],
    gold_optimum: Mapping[str, Any],
    attempt: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> tuple[ScoreEnvelope, ScoreEnvelope | None]:
    """Score pricing's gate independently -- there is no upstream primitive to
    delegate to (see module docstring): non-negativity and product-id keying
    are AERead's own declared rule, checked here, never by upstream's own
    ``set_prices`` (verified in recon: it never checks price sign).
    """
    error = attempt.get("error")
    if error == "malformed_input":
        return (
            _invalid_measurement(gate_leaf, reason="malformed_submission", evidence_refs=evidence_refs),
            None,
        )
    if error == "illegal_action":
        reason = str(attempt.get("error_message") or "illegal_action")
        return _gate_fail(gate_leaf, reason=reason, evidence_refs=evidence_refs), None
    if error is not False:
        raise ValueError(f"unrecognized pricing attempt.error: {error!r}")
    prices = attempt["prices"]
    product_ids = set(instance["product_ids"])
    if set(prices) != product_ids:
        return (
            _gate_fail(gate_leaf, reason="prices do not match declared product_ids", evidence_refs=evidence_refs),
            None,
        )
    negative = sorted(product_id for product_id, price in prices.items() if price < 0)
    if negative:
        return (
            _gate_fail(gate_leaf, reason=f"negative prices: {negative}", evidence_refs=evidence_refs),
            None,
        )
    gate = _gate_pass(gate_leaf, evidence_refs=evidence_refs)
    period = attempt["period"]
    v_star = float(sum(gold_optimum["profits_by_period"][period]))
    v_agent = float(sum(attempt["profits"].values()))
    objective = _objective_ok(objective_leaf, value=v_agent, v_star=v_star, evidence_refs=evidence_refs)
    return gate, objective


# --------------------------------------------------------------------------
# One case's fixed set of declared leaves, plus the scorer for it.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EconevalsScorer:
    """One case's declared ``(gate_leaf, objective_leaf)`` plus its scorer.

    Mirrors ``tau3_retail.measurement.Tau3RetailScorer``'s shape: a small,
    case-bound wrapper around the module-level ``score_*``/``build_*``
    functions, exercised directly by tests and returned from
    ``environment.py``'s ``build_scorer`` hook.
    """

    track: str
    instance: Mapping[str, Any]
    gold_optimum: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, MeasurementLeafSpec]

    @property
    def gate_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def objective_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    def score_attempt(
        self, attempt: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> tuple[ScoreEnvelope, ScoreEnvelope | None]:
        if self.track == "procurement":
            return score_procurement(
                gate_leaf=self.gate_leaf,
                objective_leaf=self.objective_leaf,
                gold_optimum=self.gold_optimum,
                attempt=attempt,
                evidence_refs=evidence_refs,
            )
        if self.track == "scheduling":
            return score_scheduling(
                gate_leaf=self.gate_leaf,
                objective_leaf=self.objective_leaf,
                gold_optimum=self.gold_optimum,
                attempt=attempt,
                evidence_refs=evidence_refs,
            )
        if self.track == "pricing":
            return score_pricing(
                gate_leaf=self.gate_leaf,
                objective_leaf=self.objective_leaf,
                instance=self.instance,
                gold_optimum=self.gold_optimum,
                attempt=attempt,
                evidence_refs=evidence_refs,
            )
        raise ValueError(f"unknown track: {self.track!r}")

    def score_terminal_state(
        self, state: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> tuple[ScoreEnvelope, ScoreEnvelope | None]:
        """Score the LAST recorded attempt only (each leaf's own ``horizon``)."""
        attempts = state.get("attempts")
        if not attempts:
            return (
                _invalid_measurement(self.gate_leaf, reason="no_attempts_recorded", evidence_refs=evidence_refs),
                None,
            )
        return self.score_attempt(attempts[-1], evidence_refs=evidence_refs)


def build_scorer(family_case: Mapping[str, Any]) -> EconevalsScorer:
    """Build the one ``EconevalsScorer`` for a case's validated ``family_case``."""
    track = family_case["track"]
    instance = family_case["generated_instance"]
    gold_optimum = family_case["gold_optimum"]
    return EconevalsScorer(
        track=track,
        instance=instance,
        gold_optimum=gold_optimum,
        leaves=build_leaves(track, gold_optimum),
    )


__all__ = [
    "EconevalsScorer",
    "build_gate_leaf",
    "build_leaves",
    "build_objective_leaf",
    "build_scorer",
    "score_pricing",
    "score_procurement",
    "score_scheduling",
]
