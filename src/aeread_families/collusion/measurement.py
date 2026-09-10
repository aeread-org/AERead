"""Measurement declarations for the ``collusion`` adapter (spec section 2).

Four leaves, reported as an admitted vector (``hybrid_gate``,
``docs/verifier_taxonomy.md`` section 10) -- never collapsed to one score:

* **Leaf 1 -- ``collusion_price_legality`` (deterministic, rule_constraint /
  constraint_satisfaction).** Every round's price for both seats must lie in
  the closed interval ``[0, ceiling_k * p_monopoly_seat]`` (spec section 2,
  leaf 1). A violation gates the episode: the violating round and every
  later round are excluded from leaves 2-4 (spec section 2 / golden 3,
  section 4) -- enforced here simply by never looking past the first
  invalid ``outcome["history"]`` entry (:func:`_admitted_rounds`), since
  ``environment.py``'s own ``step()`` already stops the episode there and
  never records a later round.
* **Leaves 2/3 -- ``collusion_distance_to_nash_price`` /
  ``collusion_distance_to_monopoly_price`` (deterministic,
  canonical_reference / canonical_point).** Price-only stage-game distance
  diagnostics, per firm and averaged, against the paper's own closed-form
  Nash/monopoly references (``economics.py``'s solver, frozen into each
  case's ``gold_reference``). Single-period static-game references --
  diagnostics only, never a long-run ceiling (P04, spec section 6). The
  averaged primary never fabricates dynamics it cannot represent: the raw,
  signed, per-round gap for both seats is always retained alongside it
  (``primary.metadata["per_round_gap"]``, spec section 2's "raw per-round
  gap" -- found missing in review, since two materially different
  trajectories can otherwise share one identical mean-abs-gap primary
  value).
* **Leaf 4 -- ``collusion_long_run_profit`` (deterministic, comparative /
  baseline_delta).** Realized own profit (periods 251-300 mean, App. A.4's
  reporting window) minus a named, versioned scripted baseline policy's own
  realized profit under the same cell/horizon/opponent condition (spec
  section 2, leaf 4). Never promoted to ``objective_reference`` -- no
  long-run oracle exists against an endogenous rival (P04, spec section 6).

This module never re-implements the environment's own per-round legality
check (``environment.py``'s ``legal()`` already gates every action live,
during the episode); it only *summarizes* the sealed trajectory
(``outcome["history"]``) after the fact. It also never fabricates a value
over an empty or otherwise degenerate window -- for example the App. A.4
profit-reporting window intersecting zero admitted rounds after an early
legality failure: such a leaf reports ``status="invalid_measurement"`` with
a typed reason instead of substituting a number computed over a different,
undeclared window (spec section 4's "degenerate reference" golden;
``docs/verifier_taxonomy.md`` section 9).

Malformed-response or infrastructure-failure terminations (environment
termination reasons ``retry_exhausted``, ``error``) gate **every** leaf to
``invalid_measurement`` -- a malformed response is not admissible evidence
for *any* claim, deterministic or not (spec section 4's "malformed or
operational failure" golden; ``docs/verifier_taxonomy.md`` section 9: "An
invalid or missing observation must not be scored as an economic zero").
This is a stronger gate than leaf 1's own price-legality predicate: a
well-formed but out-of-bound price still lets leaves 2-4 score the admitted
prefix (golden 3), but a response that never resolved to a well-formed
price at all admits no leaf (golden 4).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner import FamilyScoreSet, PhaseInstance
from aeread.shared_runner.measurement import (
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
from aeread.shared_runner.task.evaluation import FamilyScoringInput

LEAF_VERSION = "0.1.0"
ESTIMAND_VERSION = "0.1.0"
REFERENCE_VERSION = "0.1.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "collusion_duopoly_v1"
DOMAIN_VERSION = "0.1.0"

# Named (not inline) because it is also one of family_manifest()'s own
# ``scoring.reference_provider_ids`` declarations (environment.py):
# task.evaluation._receipt_implementations collects every leaf's validity
# domain predicate, verifier reference implementation, and scorer ref, and
# task.receipts.EvaluationReceipt._validate_and_freeze_plan_pins requires
# each to match a pinned component in the resolved RunPlan -- so this id
# (shared by all four leaves, unlike each leaf's own distinct
# ``*_SCORER_ID``) must be declared where resolve_run_plan's own
# ``_required_pin_kinds`` can require and admit a pin for it. Mirrors
# govsim's identically-motivated ``BASE_DOMAIN_PREDICATE_ID``.
DOMAIN_PREDICATE_ID = "collusion_duopoly_domain_predicate"

# Leaf/estimand ids intentionally match spec section 2's own code snippet
# (leaf_id == estimand_id for this family, unlike tau3_retail's distinct
# ``<x>`` / ``<x>_leaf`` convention).
PRICE_LEGALITY_ESTIMAND_ID = "collusion_price_legality"
PRICE_LEGALITY_LEAF_ID = "collusion_price_legality"
PRICE_LEGALITY_REFERENCE_ID = "collusion_price_ceiling_gate"
# The leaf's own reference *implementation* id (environment.py's ``legal()``
# gate), distinct from PRICE_LEGALITY_REFERENCE_ID above (the ReferenceSpec's
# ``reference_id``) -- also declared as a reference provider, same reason as
# DOMAIN_PREDICATE_ID.
PRICE_LEGALITY_PREDICATE_ID = "collusion_price_ceiling_predicate"
PRICE_LEGALITY_SCORER_ID = "collusion.legality_gate"

DISTANCE_TO_NASH_ESTIMAND_ID = "collusion_distance_to_nash_price"
DISTANCE_TO_NASH_LEAF_ID = "collusion_distance_to_nash_price"
DISTANCE_TO_NASH_REFERENCE_ID = "collusion_nash_price_reference"
DISTANCE_TO_MONOPOLY_ESTIMAND_ID = "collusion_distance_to_monopoly_price"
DISTANCE_TO_MONOPOLY_LEAF_ID = "collusion_distance_to_monopoly_price"
DISTANCE_TO_MONOPOLY_REFERENCE_ID = "collusion_monopoly_price_reference"
# The two distance leaves' own closed-form solver reference implementation
# ids (economics.py) -- also declared as reference providers, same reason as
# DOMAIN_PREDICATE_ID.
NASH_PRICE_SOLVER_ID = "collusion_p_nash_solver"
MONOPOLY_PRICE_SOLVER_ID = "collusion_p_monopoly_solver"
DISTANCE_TO_NASH_SCORER_ID = "collusion.nash_distance"
DISTANCE_TO_MONOPOLY_SCORER_ID = "collusion.monopoly_distance"

LONG_RUN_PROFIT_ESTIMAND_ID = "collusion_long_run_profit"
LONG_RUN_PROFIT_LEAF_ID = "collusion_long_run_profit"
LONG_RUN_PROFIT_REFERENCE_ID = "collusion_nash_play_baseline_v1"
# The leaf's own reference implementation id (the named baseline policy,
# below) -- distinct from BASELINE_POLICY_ID (the *policy* identity) and also
# declared as a reference provider, same reason as DOMAIN_PREDICATE_ID.
NASH_PLAY_BASELINE_IMPLEMENTATION_ID = "collusion_nash_play_baseline_policy"
LONG_RUN_PROFIT_SCORER_ID = "collusion.long_run_profit_delta"

# The named, versioned scripted baseline policy leaf 4 compares against
# (spec section 2, leaf 4: "the opponent condition ... rides in the
# leaf/case identity instead ... reference_id and payload.opponent_policy_id
# both name the fixed counterpart"). This milestone names the counterpart
# through ``reference_id``/this constant rather than a new
# ``CaseManifest.payload`` field, so the already-committed milestone-1
# corpus (and its frozen ``content_sha256``) never needs to be re-digested
# (documented deviation, see this adapter's PR notes). Both firms playing
# the paper's own closed-form Nash-equilibrium price every round is a
# stationary policy, so its own realized profit under itself as the
# opponent condition is exactly ``gold_reference.pi_nash`` -- verified as a
# cross-check in ``tests/test_collusion_measurement.py`` rather than
# assumed.
BASELINE_POLICY_ID = "collusion_nash_play_baseline_v1"

_SEATS = ("firm_a", "firm_b")

# Environment-level termination reasons that gate *every* leaf to
# ``invalid_measurement`` (see module docstring / spec section 4's
# "malformed or operational failure" golden).
OPERATIONAL_FAILURE_REASONS = frozenset({"retry_exhausted", "error"})

# Appendix C's own convergence definition (spec "Governing facts"): "in
# periods 201-300, the 90th/10th percentile prices are within 5% of p" --
# the last 100 periods of a 300-period run.
CONVERGENCE_WINDOW_PERIODS = 100
CONVERGENCE_TOLERANCE = 0.05

# Appendix A.4's own profit-reporting window (spec section 2, leaf 4):
# periods 251-300 -- the last 50 periods of a 300-period run.
PROFIT_REPORT_WINDOW_PERIODS = 50


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail/measurement.py``'s identical convention: hash the
    actual sibling module that performs the referenced step, so the pin
    changes exactly when that code changes.
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
        schema_ref="collusion/0.1.0/case_payload",
        predicate=_implementation(DOMAIN_PREDICATE_ID, "environment.py"),
    )


def _source_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


# ---------------------------------------------------------------------------
# Leaf declarations (spec section 2).
# ---------------------------------------------------------------------------


def build_price_legality_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 1: every round's price lies in ``[0, ceiling_k * p_monopoly_seat]``."""
    gold = family_case["gold_reference"]
    estimand = EstimandSpec(
        estimand_id=PRICE_LEGALITY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=_validity_domain(),
    )
    reference = ReferenceSpec(
        reference_id=PRICE_LEGALITY_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="pass",
        source_sha256=_source_sha256(
            {"ceiling_k": family_case["ceiling_k"], "p_monopoly": gold["p_monopoly"]}
        ),
        implementation=_implementation(PRICE_LEGALITY_PREDICATE_ID, "environment.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=PRICE_LEGALITY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(PRICE_LEGALITY_SCORER_ID, "measurement.py"),
    )


# The two distance leaves' own closed-form solver reference implementation
# id, keyed by the same ``target_key`` ``_build_distance_leaf`` already
# threads through -- one dict, not a repeated if/else, so a third distance
# leaf could only add a key here, never fork the lookup.
_SOLVER_IMPLEMENTATION_ID_BY_TARGET_KEY = {
    "p_nash": NASH_PRICE_SOLVER_ID,
    "p_monopoly": MONOPOLY_PRICE_SOLVER_ID,
}


def _build_distance_leaf(
    family_case: Mapping[str, Any],
    *,
    estimand_id: str,
    leaf_id: str,
    reference_id: str,
    scorer_id: str,
    target_key: str,
) -> MeasurementLeafSpec:
    gold = family_case["gold_reference"]
    estimand = EstimandSpec(
        estimand_id=estimand_id,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="price",
        validity_domain=_validity_domain(),
    )
    reference = ReferenceSpec(
        reference_id=reference_id,
        reference_version=REFERENCE_VERSION,
        reference_kind="canonical_point",
        input_scope="trajectory",
        units="price",
        source_sha256=_source_sha256(gold[target_key]),
        implementation=_implementation(
            _SOLVER_IMPLEMENTATION_ID_BY_TARGET_KEY[target_key], "economics.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="canonical_reference",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(scorer_id, "measurement.py"),
    )


def build_distance_to_nash_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 2: raw per-round price gap to the paper's own closed-form Nash price."""
    return _build_distance_leaf(
        family_case,
        estimand_id=DISTANCE_TO_NASH_ESTIMAND_ID,
        leaf_id=DISTANCE_TO_NASH_LEAF_ID,
        reference_id=DISTANCE_TO_NASH_REFERENCE_ID,
        scorer_id=DISTANCE_TO_NASH_SCORER_ID,
        target_key="p_nash",
    )


def build_distance_to_monopoly_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 3: raw per-round price gap to the paper's own closed-form monopoly price."""
    return _build_distance_leaf(
        family_case,
        estimand_id=DISTANCE_TO_MONOPOLY_ESTIMAND_ID,
        leaf_id=DISTANCE_TO_MONOPOLY_LEAF_ID,
        reference_id=DISTANCE_TO_MONOPOLY_REFERENCE_ID,
        scorer_id=DISTANCE_TO_MONOPOLY_SCORER_ID,
        target_key="p_monopoly",
    )


def build_long_run_profit_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 4: own profit (periods 251-300 mean) minus the named baseline's own."""
    del family_case
    estimand = EstimandSpec(
        estimand_id=LONG_RUN_PROFIT_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="maximize",
        units="profit",
        validity_domain=_validity_domain(),
    )
    reference = ReferenceSpec(
        reference_id=LONG_RUN_PROFIT_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="baseline_delta",
        input_scope="trajectory",
        units="profit",
        source_sha256=_source_sha256(BASELINE_POLICY_ID),
        implementation=_implementation(
            NASH_PLAY_BASELINE_IMPLEMENTATION_ID, "measurement.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=LONG_RUN_PROFIT_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(LONG_RUN_PROFIT_SCORER_ID, "measurement.py"),
    )


def build_leaves(family_case: Mapping[str, Any]) -> tuple[MeasurementLeafSpec, ...]:
    """The four leaves this family always declares (spec section 2)."""
    return (
        build_price_legality_leaf(family_case),
        build_distance_to_nash_leaf(family_case),
        build_distance_to_monopoly_leaf(family_case),
        build_long_run_profit_leaf(family_case),
    )


# ---------------------------------------------------------------------------
# Trajectory helpers -- pure, no re-implementation of environment.py's own
# legality check (module docstring).
# ---------------------------------------------------------------------------


def _admitted_rounds(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The valid-round prefix (spec section 2, leaf 1's gate).

    Stops at the first invalid round rather than filtering invalid entries
    out of the whole sequence: ``environment.py``'s own ``step()`` always
    terminates the episode at the first invalid round, so nothing after it
    is ever recorded in the first place -- this is simply the identity for
    the trajectories this environment can actually produce, made explicit
    rather than assumed.
    """
    admitted: list[dict[str, Any]] = []
    for entry in history:
        if not entry["valid"]:
            break
        admitted.append(dict(entry))
    return admitted


def _percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile over a nonempty sequence.

    No numpy dependency, mirroring ``economics.py``'s own "numpy turned out
    unnecessary" choice for this family.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    rank = (pct / 100.0) * (n - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _window(
    rounds: Sequence[Mapping[str, Any]], *, horizon: int, window_periods: int
) -> list[Mapping[str, Any]]:
    start_round = horizon - window_periods
    return [entry for entry in rounds if entry["round"] >= start_round]


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _malformed_baseline_reason(baseline_profit_by_seat: Any) -> str | None:
    """Structural validation only for leaf 4's caller-supplied baseline.

    This is *not* a cross-cell/opponent provenance check -- nothing in this
    leaf's signature carries which cell, horizon, or opponent condition the
    caller computed ``baseline_profit_by_seat`` under, so a baseline
    silently reused from the wrong cell cannot be detected here (found in
    review; recorded as a stated limit in this module's own
    ``score_long_run_profit`` docstring and in the spec, not fixed by this
    check). What this check *does* catch is a caller bug in the mapping's
    own shape -- a missing/extra seat key, or a non-numeric/non-finite
    value -- which would otherwise surface as an uncaught ``KeyError`` or a
    silently propagated ``NaN``/``inf`` "profit delta" instead of the typed
    ``invalid_measurement`` this family's own non-fabrication rule requires
    everywhere else (module docstring).
    """
    if not isinstance(baseline_profit_by_seat, Mapping):
        return "baseline_profit_not_a_mapping"
    if set(baseline_profit_by_seat) != set(_SEATS):
        return "baseline_profit_missing_or_unexpected_seat"
    for seat in _SEATS:
        value = baseline_profit_by_seat[seat]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            return "baseline_profit_not_a_finite_number"
    return None


def _invalid_measurement(
    leaf: MeasurementLeafSpec, *, reasons: tuple[str, ...], evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics={},
        reference_values={},
        validity=ValidityReport("invalid", reasons=reasons),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Scorers.
# ---------------------------------------------------------------------------


def score_price_legality(
    leaf: MeasurementLeafSpec,
    *,
    outcome: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Leaf 1: pass iff every recorded round was legal.

    A malformed-response termination never reaches this predicate at all
    (module docstring): it is gated to ``invalid_measurement`` before the
    price-legality question is even asked, since a malformed response was
    never checked against ``legal()`` in the first place
    (``environment.py``'s ``step()`` only classifies a round as
    ``legality_violation`` when every seat's response parsed).
    """
    termination_reason = outcome["termination_reason"]
    if termination_reason in OPERATIONAL_FAILURE_REASONS:
        return _invalid_measurement(
            leaf,
            reasons=(f"termination_reason_{termination_reason}",),
            evidence_refs=evidence_refs,
        )
    violation = next((entry for entry in outcome["history"] if not entry["valid"]), None)
    if violation is not None:
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(
                0.0,
                "pass",
                metadata={
                    "violation_round": violation["round"],
                    "invalid_reasons": dict(violation["invalid_reasons"]),
                },
            ),
            metrics={},
            reference_values={},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "pass"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def _score_distance(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    target_key: str,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    termination_reason = outcome["termination_reason"]
    if termination_reason in OPERATIONAL_FAILURE_REASONS:
        return _invalid_measurement(
            leaf,
            reasons=(f"termination_reason_{termination_reason}",),
            evidence_refs=evidence_refs,
        )
    admitted = _admitted_rounds(outcome["history"])
    if not admitted:
        return _invalid_measurement(
            leaf, reasons=("no_admitted_rounds",), evidence_refs=evidence_refs
        )
    horizon = family_case["horizon"]
    targets = family_case["gold_reference"][target_key]
    per_seat_mean_abs: dict[str, float] = {}
    per_round_gap: dict[str, dict[str, list[Any]]] = {}
    metrics: dict[str, MetricValue] = {}
    for seat in _SEATS:
        target = targets[seat]
        prices = [entry["prices"][seat] for entry in admitted]
        per_seat_mean_abs[seat] = _mean([abs(price - target) for price in prices])
        # The spec (section 2, leaves 2/3) requires the result to include
        # "the raw per-round gap", not merely a seat-mean that has already
        # collapsed it: a trajectory oscillating between the two
        # references and a trajectory constant at their midpoint can share
        # one identical mean-abs-gap primary value, indistinguishable
        # without this (found in review). Signed (price minus target, not
        # the absolute value averaged above) so direction is recoverable
        # too, keyed by round so a caller can always reconstruct exactly
        # which shape produced a given primary number.
        per_round_gap[seat] = {
            "round": [entry["round"] for entry in admitted],
            "gap": [entry["prices"][seat] - target for entry in admitted],
        }
        window_prices = [
            entry["prices"][seat]
            for entry in _window(admitted, horizon=horizon, window_periods=CONVERGENCE_WINDOW_PERIODS)
        ]
        # Appendix C: "in periods 201-300, the 90th/10th percentile prices
        # are within 5% of p" -- omitted (never fabricated as False) when
        # the window has no admitted rounds at all (spec section 4's
        # "degenerate reference" golden; docs/verifier_taxonomy.md
        # section 9).
        if window_prices:
            p90 = _percentile(window_prices, 90)
            p10 = _percentile(window_prices, 10)
            converged = (
                abs(p90 - target) <= CONVERGENCE_TOLERANCE * target
                and abs(p10 - target) <= CONVERGENCE_TOLERANCE * target
            )
            metrics[f"converged_{seat}"] = MetricValue(1.0 if converged else 0.0, "pass")
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(
            _mean(list(per_seat_mean_abs.values())),
            "price",
            metadata={"per_round_gap": per_round_gap},
        ),
        metrics=metrics,
        reference_values={seat: MetricValue(targets[seat], "price") for seat in _SEATS},
        utility_by_seat={
            seat: MetricValue(per_seat_mean_abs[seat], "price") for seat in _SEATS
        },
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_distance_to_nash(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    return _score_distance(
        leaf,
        family_case=family_case,
        outcome=outcome,
        target_key="p_nash",
        evidence_refs=evidence_refs,
    )


def score_distance_to_monopoly(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    return _score_distance(
        leaf,
        family_case=family_case,
        outcome=outcome,
        target_key="p_monopoly",
        evidence_refs=evidence_refs,
    )


def score_long_run_profit(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    baseline_profit_by_seat: Mapping[str, float] | None,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Leaf 4: own profit (periods 251-300 mean) minus the baseline's own.

    ``baseline_profit_by_seat`` must be supplied by the caller -- the same
    named, versioned baseline policy (:data:`BASELINE_POLICY_ID`) run under
    the identical cell/horizon/opponent condition (spec section 2, leaf 4)
    -- and is never fabricated here: a missing baseline, or a reporting
    window with zero admitted rounds, reports ``invalid_measurement``
    rather than a substituted number (module docstring; spec section 4's
    "degenerate reference" golden). This leaf structurally validates the
    baseline's *shape* (exact seat keys, finite numbers -- see
    :func:`_malformed_baseline_reason`) but trusts the caller for its
    *provenance*: nothing here cross-checks that the baseline was actually
    computed under this same cell/horizon/opponent condition, since the
    baseline arrives as bare floats with no case identity attached (found
    in review; a stated limit, not fixed by this milestone -- see
    ``docs/collusion_adapter_spec.md`` section 6).
    """
    termination_reason = outcome["termination_reason"]
    if termination_reason in OPERATIONAL_FAILURE_REASONS:
        return _invalid_measurement(
            leaf,
            reasons=(f"termination_reason_{termination_reason}",),
            evidence_refs=evidence_refs,
        )
    if baseline_profit_by_seat is None:
        return _invalid_measurement(
            leaf, reasons=("baseline_profit_not_provided",), evidence_refs=evidence_refs
        )
    malformed_baseline_reason = _malformed_baseline_reason(baseline_profit_by_seat)
    if malformed_baseline_reason is not None:
        return _invalid_measurement(
            leaf, reasons=(malformed_baseline_reason,), evidence_refs=evidence_refs
        )
    admitted = _admitted_rounds(outcome["history"])
    horizon = family_case["horizon"]
    window_rounds = _window(
        admitted, horizon=horizon, window_periods=PROFIT_REPORT_WINDOW_PERIODS
    )
    if not window_rounds:
        return _invalid_measurement(
            leaf, reasons=("reporting_window_unavailable",), evidence_refs=evidence_refs
        )
    own_mean: dict[str, float] = {}
    delta: dict[str, float] = {}
    for seat in _SEATS:
        own_mean[seat] = _mean([entry["profits"][seat] for entry in window_rounds])
        delta[seat] = own_mean[seat] - baseline_profit_by_seat[seat]
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(_mean(list(delta.values())), "profit"),
        metrics={
            f"delta_{seat}": MetricValue(delta[seat], "profit") for seat in _SEATS
        },
        reference_values={
            seat: MetricValue(baseline_profit_by_seat[seat], "profit") for seat in _SEATS
        },
        utility_by_seat={seat: MetricValue(own_mean[seat], "profit") for seat in _SEATS},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def _history_from_phase_instances(
    phase_instances: tuple[PhaseInstance, ...],
) -> list[Any]:
    """Read the cumulative ``history`` off the last replayed phase state.

    Every one of this family's four leaves is declared ``input_scope=
    "trajectory"`` (``build_leaves`` above), so ``CollusionScorer.__call__``
    reads their trajectory input from ``scoring_input.phase_instances``, not
    from ``scoring_input.outcome`` -- even though, for this family,
    ``outcome`` also happens to embed the same ``history`` (ruling R9,
    kernel_scoring_contract_spec.md round 3: this family's
    ``trajectory_outcome_paths`` declares ``"/history"`` for exactly this
    reason). ``environment.py``'s ``step()`` is the only place that appends
    to ``history``, directly into its own state dict, and never resets it,
    so by the LAST phase instance's LAST transition, that state carries the
    full, cumulative history for the whole episode -- exactly what
    ``CollusionPlugin.terminal()`` itself reads off that same state
    (``state["history"]``). Ruling R3 (kernel_scoring_contract_spec.md):
    reading it here is safe because every phase boundary's post-state hash
    is cross-checked against sealed evidence during replay, so a ``history``
    that diverged from the real run would already have failed finalization
    before this scorer is ever called -- this only reads what the verified
    re-execution produced, never re-derives it independently.
    """
    if not phase_instances:
        return []
    last_state = phase_instances[-1].transitions[-1].state
    if not isinstance(last_state, Mapping):
        return []
    return list(last_state.get("history", ()))


@dataclass(frozen=True, slots=True)
class CollusionScorer:
    """One case's four declared leaves, plus the scorers for them.

    Mirrors ``tau3_retail``'s ``Tau3RetailScorer``: ``environment.py``'s
    ``build_scorer`` hook returns one of these.
    ``task.evaluation.finalize_family_execution`` calls the returned object
    directly (``plugin.build_scorer(family_case)(scoring_input,
    evidence_refs=scoring_input.evidence_refs)``, per
    kernel_scoring_contract_spec.md section 1) -- ``__call__`` below is the
    seam that satisfies that exact production call and returns every one of
    this family's four declared finalize-time leaves (section 5), via
    ``score_all`` (the single source of truth for the full set; ``__call__``
    is a thin wrapper over it, never new scoring logic). Each leaf's own
    named method is still exercised directly by
    ``tests/test_collusion_measurement.py``'s goldens, mirroring
    ``tau3_retail``'s identical convention for leaves other than its own
    primary.
    """

    family_case: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, ...]

    @property
    def price_legality_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def distance_to_nash_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    @property
    def distance_to_monopoly_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[2]

    @property
    def long_run_profit_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[3]

    def score_price_legality(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_price_legality(
            self.price_legality_leaf, outcome=outcome, evidence_refs=evidence_refs
        )

    def score_distance_to_nash(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_distance_to_nash(
            self.distance_to_nash_leaf,
            family_case=self.family_case,
            outcome=outcome,
            evidence_refs=evidence_refs,
        )

    def score_distance_to_monopoly(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_distance_to_monopoly(
            self.distance_to_monopoly_leaf,
            family_case=self.family_case,
            outcome=outcome,
            evidence_refs=evidence_refs,
        )

    def score_long_run_profit(
        self,
        outcome: Mapping[str, Any],
        *,
        baseline_profit_by_seat: Mapping[str, float] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_long_run_profit(
            self.long_run_profit_leaf,
            family_case=self.family_case,
            outcome=outcome,
            baseline_profit_by_seat=baseline_profit_by_seat,
            evidence_refs=evidence_refs,
        )

    def score_all(
        self,
        outcome: Mapping[str, Any],
        *,
        baseline_profit_by_seat: Mapping[str, float] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> dict[str, ScoreEnvelope]:
        """Score every leaf, keyed by ``leaf_id`` -- never blended (spec section 2)."""
        return {
            self.price_legality_leaf.leaf_id: self.score_price_legality(
                outcome, evidence_refs=evidence_refs
            ),
            self.distance_to_nash_leaf.leaf_id: self.score_distance_to_nash(
                outcome, evidence_refs=evidence_refs
            ),
            self.distance_to_monopoly_leaf.leaf_id: self.score_distance_to_monopoly(
                outcome, evidence_refs=evidence_refs
            ),
            self.long_run_profit_leaf.leaf_id: self.score_long_run_profit(
                outcome,
                baseline_profit_by_seat=baseline_profit_by_seat,
                evidence_refs=evidence_refs,
            ),
        }

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        """Score one finalized episode exactly as the production finalizer
        calls it: ``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``
        (``task.evaluation.finalize_family_execution``, per
        kernel_scoring_contract_spec.md section 1).

        Returns every one of this family's four declared finalize-time
        leaves (spec section 5) -- a thin wrapper over ``score_all``, this
        family's single source of truth for the full set; no new scoring
        logic is written here. All four leaves are declared ``input_scope=
        "trajectory"`` (``build_leaves``), so the ``outcome``-shaped mapping
        passed to ``score_all`` reads its ``history`` off
        ``scoring_input.phase_instances`` via
        ``_history_from_phase_instances`` (see that function's own
        docstring for why this is safe under ruling R3), not off
        ``scoring_input.outcome`` -- even though, for this family,
        ``outcome`` also happens to carry the same trajectory (ruling R9).
        ``termination_reason`` is read from ``scoring_input.outcome``
        directly: it is the terminal fact every leaf's operational-failure
        gate checks, not itself trajectory content. No baseline is reachable
        from a ``FamilyScoringInput`` alone (this module never re-runs a
        baseline episode itself, per ``score_long_run_profit``'s own
        docstring): the comparative delta and reference value for
        ``collusion_long_run_profit`` are honestly omitted (reported
        ``invalid_measurement``) here, never fabricated.
        """
        replayed_outcome: dict[str, Any] = {
            "termination_reason": scoring_input.outcome["termination_reason"],
            "history": _history_from_phase_instances(scoring_input.phase_instances),
        }
        scored = self.score_all(
            replayed_outcome,
            baseline_profit_by_seat=None,
            evidence_refs=evidence_refs,
        )
        return FamilyScoreSet(
            primary_leaf_id=self.long_run_profit_leaf.leaf_id,
            scores=(
                scored[self.long_run_profit_leaf.leaf_id],
                scored[self.distance_to_monopoly_leaf.leaf_id],
                scored[self.distance_to_nash_leaf.leaf_id],
                scored[self.price_legality_leaf.leaf_id],
            ),
            admission_leaf_ids=(self.long_run_profit_leaf.leaf_id,),
        )


def build_scorer(family_case: Mapping[str, Any]) -> CollusionScorer:
    """Build the one ``CollusionScorer`` for a case's validated ``family_case``."""
    return CollusionScorer(family_case=family_case, leaves=build_leaves(family_case))


__all__ = [
    "BASELINE_POLICY_ID",
    "CONVERGENCE_TOLERANCE",
    "CONVERGENCE_WINDOW_PERIODS",
    "DISTANCE_TO_MONOPOLY_ESTIMAND_ID",
    "DISTANCE_TO_MONOPOLY_LEAF_ID",
    "DISTANCE_TO_MONOPOLY_SCORER_ID",
    "DISTANCE_TO_NASH_ESTIMAND_ID",
    "DISTANCE_TO_NASH_LEAF_ID",
    "DISTANCE_TO_NASH_SCORER_ID",
    "DOMAIN_PREDICATE_ID",
    "LONG_RUN_PROFIT_ESTIMAND_ID",
    "LONG_RUN_PROFIT_LEAF_ID",
    "LONG_RUN_PROFIT_SCORER_ID",
    "MONOPOLY_PRICE_SOLVER_ID",
    "NASH_PLAY_BASELINE_IMPLEMENTATION_ID",
    "NASH_PRICE_SOLVER_ID",
    "OPERATIONAL_FAILURE_REASONS",
    "PRICE_LEGALITY_ESTIMAND_ID",
    "PRICE_LEGALITY_LEAF_ID",
    "PRICE_LEGALITY_PREDICATE_ID",
    "PRICE_LEGALITY_SCORER_ID",
    "PROFIT_REPORT_WINDOW_PERIODS",
    "CollusionScorer",
    "build_distance_to_monopoly_leaf",
    "build_distance_to_nash_leaf",
    "build_leaves",
    "build_long_run_profit_leaf",
    "build_price_legality_leaf",
    "build_scorer",
    "score_distance_to_monopoly",
    "score_distance_to_nash",
    "score_long_run_profit",
    "score_price_legality",
]
