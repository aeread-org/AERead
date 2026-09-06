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
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import FamilyScoringInput
from aeread.shared_runner.task.scheduler import PhaseInstance

from .cases import MODULE_SHA256, TRACKS

LEAF_VERSION = "0.1.0"
ESTIMAND_VERSION = "0.1.0"
REFERENCE_VERSION = "0.1.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "econevals_base_v1"
DOMAIN_VERSION = "0.1.0"

# kernel_scoring_contract_spec.md section 3: the manifest's leaf policy
# declares ONE static leaf set per family/version (`_enforce_declared_leaf_policy`
# compares `set(produced_leaf_ids) == set(declared.leaf_ids)` against a single
# manifest read once, never per-case), but the pre-migration ids below were
# track-parameterized (`econevals_{track}_gate_leaf`), so a procurement case and
# a scheduling case produced disjoint leaf_id sets -- incompatible with one
# static declaration. These two track-agnostic ids are what the manifest
# declares and what `build_gate_leaf`/`build_objective_leaf` now use; the
# per-track distinctions (estimand_id, units, direction, reference.source_sha256)
# still live one level down inside each MeasurementLeafSpec, untouched by this
# rename -- see docs/econevals_migration_plan.md's "Leaf-identity finding".
GATE_LEAF_ID = "econevals_gate_leaf"
OBJECTIVE_LEAF_ID = "econevals_objective_leaf"

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
        leaf_id=GATE_LEAF_ID,
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
        leaf_id=OBJECTIVE_LEAF_ID,
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


def _objective_not_computed(
    leaf: MeasurementLeafSpec, *, gate: ScoreEnvelope, evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """The objective leaf's own envelope whenever the gate did not pass.

    ``score_attempt``/``score_terminal_state`` (unchanged by this function)
    return ``None`` for the objective in exactly this case -- per this
    module's own docstring, "only when the gate passes does it compute the
    objective." kernel_scoring_contract_spec.md section 3 requires a family's
    scorer to return every declared leaf on every case, and ``ScoreEnvelope``
    has only two statuses (``measurement.py``'s own two-state contract): with
    no legally-scoreable achieved value to report -- fabricating one is
    exactly what this module refuses to do -- ``invalid_measurement`` is the
    only honest status left for the objective leaf itself.

    This does not relabel the GATE's own status: a well-formed-but-illegal
    submission keeps its gate ``status="ok", primary=0.0`` real domain fact
    (``_gate_fail``), and only a malformed one keeps the gate's own
    ``invalid_measurement`` (``_invalid_measurement``) -- both are read here,
    never overwritten, only to build a reason string that keeps a malformed
    submission and a domain-illegal one distinguishable in the OBJECTIVE
    leaf's own record even though this leaf's own status cannot separate them
    the way the gate leaf's status still does. Because this leaf is the
    family's sole admission leaf (see ``docs/econevals_adapter_status.md``'s
    "Leaf policy" section), any case reaching this function -- malformed,
    illegal, infeasible, or no attempt recorded at all -- excludes the
    receipt from the family's own admitted-episode aggregate; that is an
    honest consequence of there being no achieved value to include, not a
    mislabelling of the submission itself.
    """
    if gate.status == "invalid_measurement":
        reason = f"objective_not_computed: gate {'; '.join(gate.validity.reasons)}"
    else:
        gate_reason = gate.primary.metadata.get("reason") if gate.primary is not None else None
        reason = "objective_not_computed: gate_failed" + (
            f" ({gate_reason})" if gate_reason else ""
        )
    return _invalid_measurement(leaf, reason=reason, evidence_refs=evidence_refs)


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
# FamilyScoringInput plumbing (kernel_scoring_contract_spec.md section 1).
# --------------------------------------------------------------------------


def _state_from_phase_instances(phase_instances: tuple[PhaseInstance, ...]) -> Mapping[str, Any]:
    """The FSM state after the final logical action of the final phase instance.

    Both of this family's leaves are declared ``input_scope="answer"``/
    ``"terminal_state"`` (never ``"trajectory"``) -- correctly, since each
    scores only the LAST recorded attempt (``score_terminal_state``'s own
    ``horizon``), never anything earlier. But ``EconevalsPlugin.outcome()``
    carries only ``{termination_reason, period_count, num_attempts}`` --
    never the ``attempts`` list itself (docs/econevals_migration_plan.md's
    "Paired-history pair: constructible" section confirms this directly
    against this base) -- so ``scoring_input.outcome`` alone cannot supply
    what ``score_terminal_state`` needs. ``scoring_input.phase_instances``
    is the only carrier that reconstructs it: ``step()`` writes
    ``new_state["attempts"]`` once per period and never resets it, so the
    LAST phase instance's LAST transition's ``state`` carries the full,
    cumulative attempt history, from which only the final entry is ever
    read. This mirrors govsim's own
    ``_round_trace_from_phase_instances``, applied here to a
    terminal-scoped leaf rather than a trajectory-scoped one, for the same
    underlying reason: the leaf's declared scope is about WHAT it depends
    on (only the final state), not about WHICH ``FamilyScoringInput`` field
    happens to carry that final state.

    Ruling R3 (kernel_scoring_contract_spec.md): reading this is safe
    because every phase boundary's post-state hash is cross-checked against
    sealed evidence during the verified re-execution that produces
    ``phase_instances``, so a state that diverged from the real run would
    already have failed finalization before this scorer is ever called --
    this only reads what that re-execution produced, never re-derives
    anything independently.
    """
    if not phase_instances:
        return {}
    last_state = phase_instances[-1].transitions[-1].state
    return last_state if isinstance(last_state, Mapping) else {}


# --------------------------------------------------------------------------
# One case's fixed set of declared leaves, plus the scorer for it.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EconevalsScorer:
    """One case's declared ``(gate_leaf, objective_leaf)`` plus its scorer.

    Mirrors ``tau3_retail.measurement.Tau3RetailScorer``'s shape: a small,
    case-bound wrapper around the module-level ``score_*``/``build_*``
    functions, exercised directly by tests and returned from
    ``environment.py``'s ``build_scorer`` hook. ``task.evaluation.finalize_family_execution``
    calls the returned object directly
    (``plugin.build_scorer(family_case)(scoring_input, evidence_refs=scoring_input.evidence_refs)``,
    per kernel_scoring_contract_spec.md section 1) -- ``__call__`` below is
    the seam that satisfies that exact production call and returns both of
    this family's declared finalize-time leaves (section 5), via
    ``score_all`` (the single source of truth for the full set; ``__call__``
    is a thin wrapper over it, never new scoring logic). Each leaf's own
    named method (``score_attempt``/``score_terminal_state``) is still
    exercised directly by ``tests/test_econevals_measurement.py``'s goldens,
    unchanged by this migration.
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

    def score_all(
        self, state: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> tuple[ScoreEnvelope, ScoreEnvelope]:
        """Both declared leaves, always both, never ``None`` -- the single
        source of truth ``__call__`` wraps (spec section 5, item 3).

        Delegates entirely to ``score_terminal_state`` (unchanged by this
        migration): whenever the gate did not pass, ``score_terminal_state``
        returns ``None`` for the objective, and only here does that ``None``
        become an explicit ``invalid_measurement`` envelope
        (``_objective_not_computed`` -- see its own docstring for why this
        is a plumbing widening, never a change to the underlying arithmetic).
        """
        gate, objective = self.score_terminal_state(state, evidence_refs=evidence_refs)
        if objective is None:
            objective = _objective_not_computed(
                self.objective_leaf, gate=gate, evidence_refs=evidence_refs
            )
        return gate, objective

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        """Score one finalized episode exactly as the production finalizer
        calls it: ``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``
        (``task.evaluation.finalize_family_execution``, per
        kernel_scoring_contract_spec.md section 1).

        Returns both of this family's declared finalize-time leaves (spec
        section 5) -- a thin wrapper over ``score_all``, this family's
        single source of truth for the full set; no new scoring logic is
        written here. Neither leaf's declared ``input_scope`` is
        ``"trajectory"`` (both score only the last recorded attempt, per
        each leaf's own ``horizon``), but ``scoring_input.outcome`` never
        carries the ``attempts`` list either kind of leaf needs
        (``EconevalsPlugin.outcome()`` omits it), so the terminal FSM state
        is read off ``scoring_input.phase_instances`` instead, via
        ``_state_from_phase_instances`` (see that function's own docstring
        for why this is safe under ruling R3 and consistent with a
        terminal-scoped leaf's own contract).
        """
        state = _state_from_phase_instances(scoring_input.phase_instances)
        gate, objective = self.score_all(state, evidence_refs=evidence_refs)
        return FamilyScoreSet(
            primary_leaf_id=self.objective_leaf.leaf_id,
            scores=(gate, objective),
            admission_leaf_ids=(self.objective_leaf.leaf_id,),
        )


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
    "GATE_LEAF_ID",
    "OBJECTIVE_LEAF_ID",
    "EconevalsScorer",
    "build_gate_leaf",
    "build_leaves",
    "build_objective_leaf",
    "build_scorer",
    "score_pricing",
    "score_procurement",
    "score_scheduling",
]
