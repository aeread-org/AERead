"""Measurement declarations for the termsbench adapter (spec section 2).

There is no defensible optimum for a bilateral price negotiation against a
version-pinned counterpart (no oracle binary to delegate to -- the paper's
own repository link is dead, and the Oracle-Cue Bayes-optimal DP is
explicitly deferred, spec section 6). This module therefore never folds the
negotiation outcome into one blended number. It declares up to 4 separate,
explicitly labelled ``MeasurementLeafSpec`` claims and scores each
independently, exactly per the spec's verifier-declaration table:

* **Leaf 1 -- ``termsbench_surplus_efficiency`` (comparative, deterministic).**
  ``SE+_i = u_A(f_i) / Delta_i`` (eq. 56, Section F.1); disagreement
  contributes 0, well-defined (spec section 4 golden 5). Declared only for
  Overlap-regime cases (``Delta_i > 0``).
* **Leaf 2 -- ``termsbench_feasible_agreement`` (comparative, deterministic).**
  ``AGR+_i = 1`` iff the episode terminates with a bound price (eq. 57,
  Section F.1). Declared only for Overlap-regime cases.
* **Leaf 3 -- ``termsbench_no_deal_agreement`` (comparative, deterministic).**
  The eq. 60 (Section F.2) mirror of leaf 2 for a No-deal-regime case, where
  the geometry admits no positive ZOPA: any bound price is a "false
  agreement" (``FAGR-``), so the same 0/1 indicator is declared with
  ``direction="minimize"`` instead of ``"maximize"``. Declared only for
  No-deal-regime cases (``Delta_i < 0``).
* **Leaf 4 -- ``termsbench_protocol_compliance`` (rule_constraint,
  deterministic).** ``CritViol%`` (eq. 66, App. B.3/F.4): whether any of the
  3 critical predicates (price-bound, individual-rationality, invalid-action)
  fired anywhere in the trajectory. Declared for every episode, independent
  of regime or counterpart -- this is a genuine constraint check, not a
  comparative claim (spec section 2).

``CSE+`` (eq. 58) and ``SafeTerm-=1-FAGR-`` are corpus-level aggregations,
never separate leaves and never recomputed inside one ``ScoreEnvelope``
(spec section 2); :func:`aggregate_surplus_efficiency_corpus` below is the
analysis-layer helper for the ``SE+=AGR+*CSE+`` invariant (eq. 59), used only
by tests / a paired-analysis layer, never sealed into a per-episode receipt.

Secondary diagnostics (``MonoViol%``, turn-budget) are attached to leaf 4's
``ScoreEnvelope.metrics`` mapping for visibility, never folded into its
``primary`` value: per spec section 6, only ``CritViol%`` is a scored leaf
this cycle.

All 4 leaves score from the ``outcome`` dict returned by
:meth:`~aeread_families.termsbench.environment.TermsBenchPlugin.outcome` --
never re-derived from the raw transcript here, mirroring tau3_retail's rule
that a scorer never recomputes what the environment/kernel already sealed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import (
    FamilyScoreSet,
    EstimandSpec,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import kernel as k

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "termsbench_pilot_v1"
DOMAIN_VERSION = "1.0.0"

SURPLUS_EFFICIENCY_ESTIMAND_ID = "termsbench_surplus_efficiency"
SURPLUS_EFFICIENCY_LEAF_ID = "termsbench_surplus_efficiency_leaf"
SURPLUS_EFFICIENCY_REFERENCE_ID = "termsbench_surplus_efficiency_counterpart_reference"
SURPLUS_EFFICIENCY_SCORER_ID = "termsbench_surplus_efficiency_scorer"

FEASIBLE_AGREEMENT_ESTIMAND_ID = "termsbench_feasible_agreement"
FEASIBLE_AGREEMENT_LEAF_ID = "termsbench_feasible_agreement_leaf"
FEASIBLE_AGREEMENT_REFERENCE_ID = "termsbench_feasible_agreement_counterpart_reference"
FEASIBLE_AGREEMENT_SCORER_ID = "termsbench_feasible_agreement_scorer"

NO_DEAL_AGREEMENT_ESTIMAND_ID = "termsbench_no_deal_agreement"
NO_DEAL_AGREEMENT_LEAF_ID = "termsbench_no_deal_agreement_leaf"
NO_DEAL_AGREEMENT_REFERENCE_ID = "termsbench_no_deal_agreement_counterpart_reference"
NO_DEAL_AGREEMENT_SCORER_ID = "termsbench_no_deal_agreement_scorer"

PROTOCOL_COMPLIANCE_ESTIMAND_ID = "termsbench_protocol_compliance"
PROTOCOL_COMPLIANCE_LEAF_ID = "termsbench_protocol_compliance_leaf"
PROTOCOL_COMPLIANCE_REFERENCE_ID = "termsbench_protocol_compliance_case_constants"
PROTOCOL_COMPLIANCE_SCORER_ID = "termsbench_protocol_compliance_scorer"


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail/measurement.py``'s convention of hashing a sibling
    source file rather than inventing an opaque marker.
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
        schema_ref="termsbench_pilot_v1/case_payload",
        predicate=_implementation("termsbench_environment_domain_predicate", "environment.py"),
    )


def _counterpart_reference_sha256(family: str) -> str:
    """Pin the declared, version-pinned counterpart family (spec section 2's
    ``reference_kind="head_to_head"``), never a per-episode runtime draw.

    Hashes Table 3/4's own preset constants for ``family`` (``kernel.py``'s
    ``FAMILY_PRESETS``/``ECONOMIC_PRESETS``), not the case's realized private
    type ``t_B`` -- the head-to-head opponent identity is "the Candid/
    Taciturn/Expressive family", which is fixed by ``family_version``, not by
    ``world_seed``. This is why every case in the same family shares one
    reference hash regardless of its own drawn ``t_B``.
    """
    preset_name = k.FAMILY_PRESETS[family]["economic_preset"]
    preset = k.ECONOMIC_PRESETS[preset_name]
    payload = {
        "family": family,
        "family_preset": dict(k.FAMILY_PRESETS[family]),
        "economic_preset": {
            "name": preset_name,
            "rho": dict(preset["rho"]),
            "xi": dict(preset["xi"]),
            "lambda2": dict(preset["lambda2"]),
        },
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _case_constants_sha256(payload: Mapping[str, Any]) -> str:
    """Pin "the case's own declared constants" leaf 4 checks against (spec
    section 2): price bounds, agent role/IR anchor, and horizon. Unlike the
    comparative leaves' reference, this is case-specific by design -- the
    rule set genuinely differs across cases (e.g. different ``price_bounds``).
    """
    rule_payload = {
        "price_bounds": dict(payload["price_bounds"]),
        "agent_role": payload["agent"]["role"],
        "agent_r_a": float(payload["agent"]["r_a"]),
        "horizon": payload["horizon"],
    }
    return hashlib.sha256(canonical_json_bytes(rule_payload)).hexdigest()


# ---------------------------------------------------------------------------
# Leaf declarations.
# ---------------------------------------------------------------------------


def build_surplus_efficiency_leaf(payload: Mapping[str, Any]) -> MeasurementLeafSpec | None:
    """Leaf 1: ``SE+`` (eq. 56, Section F.1). ``None`` outside the Overlap
    regime -- spec section 2's verifier table declares this leaf only for
    ``Delta_i > 0`` cases."""
    if payload["regime"] != "overlap":
        return None
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=SURPLUS_EFFICIENCY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="maximize",
        units="zopa_fraction",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=SURPLUS_EFFICIENCY_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="head_to_head",
        input_scope="terminal_state",
        units="zopa_fraction",
        source_sha256=_counterpart_reference_sha256(payload["family"]),
        implementation=_implementation(SURPLUS_EFFICIENCY_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative", evaluation_class="deterministic", reference=reference
    )
    return MeasurementLeafSpec(
        leaf_id=SURPLUS_EFFICIENCY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(SURPLUS_EFFICIENCY_SCORER_ID, "measurement.py"),
    )


def build_feasible_agreement_leaf(payload: Mapping[str, Any]) -> MeasurementLeafSpec | None:
    """Leaf 2: ``AGR+`` (eq. 57, Section F.1). ``None`` outside the Overlap
    regime."""
    if payload["regime"] != "overlap":
        return None
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=FEASIBLE_AGREEMENT_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="maximize",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=FEASIBLE_AGREEMENT_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="head_to_head",
        input_scope="terminal_state",
        units="pass",
        source_sha256=_counterpart_reference_sha256(payload["family"]),
        implementation=_implementation(FEASIBLE_AGREEMENT_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative", evaluation_class="deterministic", reference=reference
    )
    return MeasurementLeafSpec(
        leaf_id=FEASIBLE_AGREEMENT_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(FEASIBLE_AGREEMENT_SCORER_ID, "measurement.py"),
    )


def build_no_deal_agreement_leaf(payload: Mapping[str, Any]) -> MeasurementLeafSpec | None:
    """Leaf 3: ``FAGR-`` (eq. 60, Section F.2). ``None`` outside the No-deal
    regime -- spec section 2's verifier table declares this leaf only for
    ``Delta_i < 0`` cases, with ``direction="minimize"`` (an agreement here
    is a "false agreement": the counterpart kernel's own IR gate,
    ``acceptance_probability``'s ``delta_bar < 0.0`` hard return of 0,
    guarantees the counterpart never accepts an offer that is not
    individually rational for it, so any bound price in a genuine No-deal
    geometry can only arise from the agent script itself accepting an
    IR-violating counterpart price -- undesirable by construction).
    """
    if payload["regime"] != "nodeal":
        return None
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=NO_DEAL_AGREEMENT_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="minimize",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=NO_DEAL_AGREEMENT_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="head_to_head",
        input_scope="terminal_state",
        units="pass",
        source_sha256=_counterpart_reference_sha256(payload["family"]),
        implementation=_implementation(NO_DEAL_AGREEMENT_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative", evaluation_class="deterministic", reference=reference
    )
    return MeasurementLeafSpec(
        leaf_id=NO_DEAL_AGREEMENT_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(NO_DEAL_AGREEMENT_SCORER_ID, "measurement.py"),
    )


def build_protocol_compliance_leaf(payload: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 4: ``CritViol%`` (eq. 66, App. B.3/F.4). Declared for every
    episode -- a genuine ``rule_constraint`` check that does not depend on
    the counterpart at all (spec section 2)."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=PROTOCOL_COMPLIANCE_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="minimize",
        units="violation_rate",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=PROTOCOL_COMPLIANCE_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="violation_rate",
        source_sha256=_case_constants_sha256(payload),
        implementation=_implementation(PROTOCOL_COMPLIANCE_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint", evaluation_class="deterministic", reference=reference
    )
    return MeasurementLeafSpec(
        leaf_id=PROTOCOL_COMPLIANCE_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(PROTOCOL_COMPLIANCE_SCORER_ID, "measurement.py"),
    )


def build_leaves(payload: Mapping[str, Any]) -> tuple[MeasurementLeafSpec, ...]:
    """The measurement leaves declared for one case's payload: exactly
    ``(surplus_efficiency, feasible_agreement, protocol_compliance)`` for an
    Overlap-regime case, or ``(no_deal_agreement, protocol_compliance)`` for
    a No-deal-regime case. Leaf 4 is never absent; leaves 1-3 are mutually
    exclusive by regime (spec section 2's verifier table)."""
    leaves: list[MeasurementLeafSpec] = []
    surplus_leaf = build_surplus_efficiency_leaf(payload)
    if surplus_leaf is not None:
        leaves.append(surplus_leaf)
    feasible_leaf = build_feasible_agreement_leaf(payload)
    if feasible_leaf is not None:
        leaves.append(feasible_leaf)
    no_deal_leaf = build_no_deal_agreement_leaf(payload)
    if no_deal_leaf is not None:
        leaves.append(no_deal_leaf)
    leaves.append(build_protocol_compliance_leaf(payload))
    return tuple(leaves)


# ---------------------------------------------------------------------------
# Scorers -- score from ``TermsBenchPlugin.outcome()``'s dict, never from the
# raw transcript (the environment/kernel already sealed every fact needed).
# ---------------------------------------------------------------------------


def _value_axis_validity(outcome: Mapping[str, Any]) -> ValidityReport:
    """Leaves 1-3 (the "value axis": SE+/AGR+/FAGR-) share one admission
    rule (spec section 4 golden 4): a malformed agent response that never
    recovers a valid economic action is typed ``invalid_measurement`` and
    excluded from the SE+/AGR+ denominator, never scored as an economic
    zero. A well-formed but *unauthorized* action (golden 3's
    AgreementViolation, e.g. Accept with no counterpart offer observed) is
    different: it parses fine, so it stays a *valid* measurement that simply
    earns no credit (handled by the 0-credit arithmetic in the scorers
    below, not by this validity gate).
    """
    if outcome["malformed_action_schema"]:
        return ValidityReport("invalid", reasons=("malformed_action_schema",))
    return ValidityReport("valid")


def _agent_utility(outcome: Mapping[str, Any]) -> float:
    """u_A(f) for the realized outcome; ``u_A(bot) = 0`` by definition (spec
    section 4 golden 3) when no price was bound."""
    final_price = outcome["final_price"]
    if final_price is None:
        return 0.0
    r_a = float(outcome["r_a"])
    if outcome["agent_role"] == "buyer":
        return r_a - float(final_price)
    return float(final_price) - r_a


def _agreement_indicator(outcome: Mapping[str, Any]) -> float:
    """1.0 iff the episode terminates with a bound price (``f_i != bot``),
    i.e. ``termination_reason`` is ``agent_accept`` or ``counterpart_accept``
    -- the only two cases ``environment.py`` ever sets ``final_price`` for.
    Shared by leaf 2 (``AGR+``, Overlap) and leaf 3 (``FAGR-``, No-deal)."""
    return 1.0 if outcome["final_price"] is not None else 0.0


def score_surplus_efficiency(
    leaf: MeasurementLeafSpec, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """Score leaf 1: ``SE+_i = u_A(f_i) / Delta_i`` (eq. 56).

    Golden 1 (spec section 4): ``u_A(110) = 150-110 = 40``, ``Delta=50`` ->
    ``SE+ = 40/50 = 0.8``. Golden 2: ``u_A(145) = 5`` -> ``SE+ = 5/50 = 0.1``.
    Golden 3/5: ``final_price is None`` -> ``u_A(bot) = 0`` -> ``SE+ = 0``,
    well-defined disagreement value (never imputed/clipped).
    """
    validity = _value_axis_validity(outcome)
    if validity.status == "invalid":
        return ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=validity,
            evidence_refs=evidence_refs,
        )
    delta = float(outcome["delta"])
    se_plus = _agent_utility(outcome) / delta
    metrics = {"agreement_reached": MetricValue(_agreement_indicator(outcome), "pass")}
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(se_plus, "zopa_fraction"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_feasible_agreement(
    leaf: MeasurementLeafSpec, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """Score leaf 2: ``AGR+_i`` (eq. 57). Golden 1/2: agreement reached ->
    ``1``. Golden 3 (AgreementViolation, unauthorized Accept): ``final_price
    is None`` -> ``0`` -- "no positive credit for an unauthorized action"
    (spec section 4), a valid 0, not an invalid measurement. Golden 5:
    5 immediate Rejects -> ``0`` for all 5 -> corpus ``AGR+ = 0``.
    """
    validity = _value_axis_validity(outcome)
    if validity.status == "invalid":
        return ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=validity,
            evidence_refs=evidence_refs,
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(_agreement_indicator(outcome), "pass"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_no_deal_agreement(
    leaf: MeasurementLeafSpec, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """Score leaf 3: ``FAGR-_i`` (eq. 60) -- the same 0/1 agreement
    indicator as leaf 2, declared only for No-deal-regime cases with
    ``direction="minimize"`` (spec section 2)."""
    validity = _value_axis_validity(outcome)
    if validity.status == "invalid":
        return ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=validity,
            evidence_refs=evidence_refs,
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(_agreement_indicator(outcome), "pass"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_protocol_compliance(
    leaf: MeasurementLeafSpec, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """Score leaf 4: ``CritViol%_i`` (eq. 66) -- ``1`` iff any of the 3
    critical predicates fired anywhere in the trajectory, else ``0``.

    Never gated by ``malformed_action_schema`` (unlike leaves 1-3): golden 3
    and golden 4 both record ``CritViol%=1`` (``InvalidAct%`` component)
    even though golden 4's leaves 1-2 are separately typed
    ``invalid_measurement`` -- the paper's own convention double-counts
    unrecoverable schema failure as both "missing" for the value axis and
    "positive" for compliance (spec section 4).
    """
    critical = outcome["critical_violations"]
    any_violation = any(bool(value) for value in critical.values())
    metrics: dict[str, MetricValue] = {
        "price_bound_violation": MetricValue(1.0 if critical["price_bound"] else 0.0, "pass"),
        "individual_rationality_violation": MetricValue(
            1.0 if critical["individual_rationality"] else 0.0, "pass"
        ),
        "invalid_action_violation": MetricValue(1.0 if critical["invalid_action"] else 0.0, "pass"),
        "malformed_action_schema": MetricValue(
            1.0 if outcome["malformed_action_schema"] else 0.0, "pass"
        ),
    }
    # Secondary diagnostics (App. F.4): logged, never gated (spec section 6).
    secondary = outcome["secondary_violations"]
    for key, value in secondary.items():
        metrics[f"secondary_{key}"] = MetricValue(1.0 if value else 0.0, "pass")
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0 if any_violation else 0.0, "violation_rate"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True, slots=True)
class TermsBenchScorer:
    """One case's fixed set of declared leaves, plus the scorers for them.

    Built once from the case's own ``payload`` (before the episode ever
    runs, mirroring ``Tau3RetailScorer``); each ``score_*`` method is then
    called once per realized episode with that episode's own ``outcome``
    dict from :meth:`TermsBenchPlugin.outcome`.
    """

    payload: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, ...]

    def _leaf(self, leaf_id: str) -> MeasurementLeafSpec | None:
        for leaf in self.leaves:
            if leaf.leaf_id == leaf_id:
                return leaf
        return None

    @property
    def surplus_efficiency_leaf(self) -> MeasurementLeafSpec | None:
        return self._leaf(SURPLUS_EFFICIENCY_LEAF_ID)

    @property
    def feasible_agreement_leaf(self) -> MeasurementLeafSpec | None:
        return self._leaf(FEASIBLE_AGREEMENT_LEAF_ID)

    @property
    def no_deal_agreement_leaf(self) -> MeasurementLeafSpec | None:
        return self._leaf(NO_DEAL_AGREEMENT_LEAF_ID)

    @property
    def protocol_compliance_leaf(self) -> MeasurementLeafSpec:
        leaf = self._leaf(PROTOCOL_COMPLIANCE_LEAF_ID)
        if leaf is None:
            raise AssertionError("protocol_compliance_leaf is declared for every case")
        return leaf

    def score_surplus_efficiency(
        self, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        leaf = self.surplus_efficiency_leaf
        if leaf is None:
            raise ValueError("this case declares no termsbench_surplus_efficiency leaf (regime != overlap)")
        return score_surplus_efficiency(leaf, outcome=outcome, evidence_refs=evidence_refs)

    def score_feasible_agreement(
        self, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        leaf = self.feasible_agreement_leaf
        if leaf is None:
            raise ValueError("this case declares no termsbench_feasible_agreement leaf (regime != overlap)")
        return score_feasible_agreement(leaf, outcome=outcome, evidence_refs=evidence_refs)

    def score_no_deal_agreement(
        self, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        leaf = self.no_deal_agreement_leaf
        if leaf is None:
            raise ValueError("this case declares no termsbench_no_deal_agreement leaf (regime != nodeal)")
        return score_no_deal_agreement(leaf, outcome=outcome, evidence_refs=evidence_refs)

    def score_protocol_compliance(
        self, *, outcome: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_protocol_compliance(
            self.protocol_compliance_leaf, outcome=outcome, evidence_refs=evidence_refs
        )


    def __call__(
        self, scoring_input: Any, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        """The kernel's once-per-episode scoring hook (issue #75).

        ``evaluation.py`` passes a ``FamilyScoringInput`` and expects every
        declared leaf; this family had no ``__call__`` at all, so the
        finalizer could not score it and none of its leaves could reach a
        receipt. Scores exactly the leaves this case declares -- they are
        regime-dependent, `(surplus_efficiency, feasible_agreement,
        protocol_compliance)` for Overlap and `(no_deal_agreement,
        protocol_compliance)` for No-deal -- rather than a fixed set, so a
        case is never scored on a leaf it does not declare.

        `protocol_compliance` is the admission leaf: it is the one leaf every
        regime declares, and a trajectory that broke the protocol is an
        invalid measurement rather than a low score. The primary leaf is the
        family's declared estimand where the regime has it, and the
        compliance leaf otherwise, so an included receipt always carries a
        primary that case actually declares.
        """
        outcome = scoring_input.outcome
        if not isinstance(outcome, Mapping):
            raise ValueError("termsbench scoring input carries no outcome mapping")
        scores: list[ScoreEnvelope] = []
        if self.surplus_efficiency_leaf is not None:
            scores.append(
                self.score_surplus_efficiency(
                    outcome=outcome, evidence_refs=evidence_refs
                )
            )
        if self.feasible_agreement_leaf is not None:
            scores.append(
                self.score_feasible_agreement(
                    outcome=outcome, evidence_refs=evidence_refs
                )
            )
        if self.no_deal_agreement_leaf is not None:
            scores.append(
                self.score_no_deal_agreement(
                    outcome=outcome, evidence_refs=evidence_refs
                )
            )
        compliance = self.score_protocol_compliance(
            outcome=outcome, evidence_refs=evidence_refs
        )
        scores.append(compliance)
        primary = (
            self.surplus_efficiency_leaf
            or self.no_deal_agreement_leaf
            or self.protocol_compliance_leaf
        )
        admission = {compliance.leaf.leaf_id, primary.leaf_id}
        return FamilyScoreSet(
            primary_leaf_id=primary.leaf_id,
            scores=tuple(scores),
            admission_leaf_ids=tuple(sorted(admission)),
        )


def declared_reference_implementations() -> tuple[ImplementationRef, ...]:
    """Every implementation this family's leaves cite, across both regimes.

    The resolver requires exactly the manifest's declared reference
    providers while the receipt requires a pin for every cited
    implementation, so the set must be the family-wide union: a No-deal case
    cites the no-deal scorer, an Overlap case the surplus and feasibility
    scorers, and every case the compliance scorer and the domain predicate.
    Built from the same `_implementation` helper the leaves use, so a pin and
    a leaf can never disagree about a digest.
    """
    return (
        _implementation("termsbench_environment_domain_predicate", "environment.py"),
        _implementation(FEASIBLE_AGREEMENT_SCORER_ID, "measurement.py"),
        _implementation(NO_DEAL_AGREEMENT_SCORER_ID, "measurement.py"),
        _implementation(PROTOCOL_COMPLIANCE_SCORER_ID, "measurement.py"),
        _implementation(SURPLUS_EFFICIENCY_SCORER_ID, "measurement.py"),
    )


def declared_reference_provider_ids() -> tuple[str, ...]:
    """The manifest's ``scoring.reference_provider_ids``, in canonical order."""
    return tuple(
        sorted({ref.implementation_id for ref in declared_reference_implementations()})
    )



def build_scorer(payload: Mapping[str, Any]) -> TermsBenchScorer:
    """Build the one ``TermsBenchScorer`` for a case's ``family_case``
    payload."""
    return TermsBenchScorer(payload=payload, leaves=build_leaves(payload))


# ---------------------------------------------------------------------------
# Analysis-layer corpus aggregation (eq. 58-59) -- never sealed inside a
# per-episode ScoreEnvelope (spec section 2).
# ---------------------------------------------------------------------------


def aggregate_surplus_efficiency_corpus(
    envelopes: Sequence[tuple[ScoreEnvelope, ScoreEnvelope]]
) -> dict[str, float | None]:
    """Corpus-level ``SE+``/``AGR+``/``CSE+`` over a sequence of
    ``(surplus_efficiency_envelope, feasible_agreement_envelope)`` pairs,
    one pair per Overlap-regime episode in the corpus/cell.

    ``CSE+`` (eq. 58) is the mean of the paired ``SE+`` values restricted to
    the agreed subset ``A+`` (``AGR+ == 1``); it is ``None`` -- never
    imputed as ``0.0`` -- when ``A+`` is empty (spec section 4 golden 5,
    quoting eq. 58's own text: "if an agent reaches no feasible agreements,
    we report CSE+ as undefined rather than imputing a value"). The product
    identity ``SE+ = AGR+ * CSE+`` (eq. 59) is vacuous and not asserted when
    ``CSE+`` is ``None``; callers should check that themselves rather than
    treating this helper's output as always satisfying eq. 59.

    Pairs whose either envelope has ``status="invalid_measurement"`` (a
    malformed-schema episode, spec section 4 golden 4) are excluded from
    both the numerator and the denominator, never scored as an economic 0.
    """
    valid_pairs = [
        (se.primary.value, agr.primary.value)
        for se, agr in envelopes
        if se.status == "ok" and agr.status == "ok"
    ]
    if not valid_pairs:
        raise ValueError("no valid (surplus_efficiency, feasible_agreement) pairs to aggregate")
    se_values = [se for se, _agr in valid_pairs]
    agr_values = [agr for _se, agr in valid_pairs]
    se_plus = sum(se_values) / len(se_values)
    agr_plus = sum(agr_values) / len(agr_values)
    agreed_se_values = [se for se, agr in valid_pairs if agr == 1.0]
    cse_plus = (sum(agreed_se_values) / len(agreed_se_values)) if agreed_se_values else None
    return {"SE_plus": se_plus, "AGR_plus": agr_plus, "CSE_plus": cse_plus}


__all__ = [
    "FEASIBLE_AGREEMENT_ESTIMAND_ID",
    "FEASIBLE_AGREEMENT_LEAF_ID",
    "NO_DEAL_AGREEMENT_ESTIMAND_ID",
    "NO_DEAL_AGREEMENT_LEAF_ID",
    "PROTOCOL_COMPLIANCE_ESTIMAND_ID",
    "PROTOCOL_COMPLIANCE_LEAF_ID",
    "SURPLUS_EFFICIENCY_ESTIMAND_ID",
    "SURPLUS_EFFICIENCY_LEAF_ID",
    "TermsBenchScorer",
    "aggregate_surplus_efficiency_corpus",
    "build_feasible_agreement_leaf",
    "build_leaves",
    "build_no_deal_agreement_leaf",
    "build_protocol_compliance_leaf",
    "build_scorer",
    "build_surplus_efficiency_leaf",
    "score_feasible_agreement",
    "score_no_deal_agreement",
    "score_protocol_compliance",
    "score_surplus_efficiency",
]
