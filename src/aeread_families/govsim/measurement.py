"""Measurement declarations for the govsim adapter (spec section 2).

GovSim has no single upstream "evaluate" function the way tau2-bench ships
``EnvironmentEvaluator`` (spec section 1's "no discrete upstream task list"):
every quantity a case's terminal state can support is instead declared as its
own separately-labelled ``MeasurementLeafSpec`` and scored here, never folded
into one blended number. Five leaves, in two families:

* **Rule/constraint leaves (``rule_constraint``, ``deterministic``,
  ``trajectory``-scoped)** -- diagnostics, never admission gates (per
  ``docs/verifier_taxonomy.md`` section 4, "a hard gate ... should not
  silently convert a normative tradeoff into invalidity"):

  - ``govsim_no_collapse``: pass iff upstream's own recorded per-round
    ``collapsed_or_horizon`` flag never fires while ``round_index + 1 <
    max_num_rounds`` -- read straight off ``environment.py``'s
    ``round_trace`` (itself built only from upstream's own recorded
    per-round state; see that module's ``step()``), never independently
    re-derived from the regeneration formula.
  - ``govsim_threshold_adherence``: per spec section 2, "a vector of
    pass/fail per agent-round, never one rate" -- ``primary`` is a single
    pass/fail (logical AND over every agent-round predicate, the one
    declared aggregation rule per ``docs/verifier_taxonomy.md`` section 4's
    "a single pass rate may summarize predicates only when the aggregation
    rule is declared"), and the full per-agent-round vector is recorded in
    ``metrics``, never blended into ``primary``.

* **Comparative leaves (``comparative``/``baseline_delta``, ``deterministic``,
  ``terminal_state``-scoped)** -- ``govsim_survival_months``,
  ``govsim_total_harvest``, ``govsim_equality_gini``. Per
  ``docs/problem_bound_case_audit.md`` row P06, no ``objective_reference``
  leaf is declared for any of these: survival months, total harvest, and
  equality are not solved policies, so no leaf here claims an approach to a
  bound. Each leaf's ``primary`` is the episode's own native quantity
  (never blended with the baseline); the baseline comparator
  (``govsim_sustainable_v1``, an AERead-authored reference policy, not an
  upstream oracle) is recorded separately in ``reference_values``, and the
  delta is a separate ``metrics`` diagnostic -- three distinct numbers, never
  collapsed into one adjusted score. Callers must supply the baseline's own
  already-computed terminal quantities (``baseline_survival_months`` etc.);
  this module never re-runs a baseline episode itself (that belongs to
  whatever drives the case, e.g. ``tests/test_govsim_measurement.py``'s
  golden harness), matching this module's own "never reimplement env
  stepping" discipline.

  These three leaves are also unreliable by construction for the QC Gate 2
  "degenerate-reference" golden (``num_agents=1``): "the common-pool dilemma
  structurally vanishes ... uninformative by construction and must be
  flagged, not reported as a clean win/loss" (spec section 4). Rather than
  silently emit a number nobody should read, each comparative scorer stamps
  ``primary.metadata["degenerate_single_agent"]`` explicitly (``True`` iff
  ``num_agents == 1``) so a caller can filter degenerate comparisons out
  without guessing.

An episode that terminated via ``operational_failure`` (a caught upstream
assertion on a malformed action, QC Gate 2's "malformed-operational" golden)
is not scored as an economic zero by any of the five leaves: every scorer
below returns ``status="invalid_measurement"`` with a typed ``validity``
reason instead (``docs/verifier_taxonomy.md`` section 9: "An invalid or
missing observation must not be scored as an economic zero ... The receipt
reports ``invalid_measurement``").

``govsim_equality_gini`` vendors upstream's own ``gini()`` function
(``simulation/analysis/plots.py``, commit 1d11adf047b24fa2ba0d44a1d4931015ea2e5210,
lines 669-683) verbatim, with the provenance header on ``_vendored_gini``
below -- not imported, because that module's own top-level imports
(``plotly``, ``dash``, ``dash_mantine_components``, ``statsmodels``) are
neither installed in the bridge venv nor needed for this one pure-numpy
function (see ``docs/govsim_adapter_spec.md`` section 2 and
``govsim_bridge_driver.py``'s ``_op_call_upstream_gini`` for the parity
cross-check that proves this vendored copy agrees with upstream's real,
unmodified code byte-for-byte -- ``tests/test_govsim_measurement.py``'s
``test_vendored_gini_matches_upstreams_own_gini_through_the_bridge*``).
``govsim_survival_months`` similarly mirrors ``compute_survival_months_stats``'s
single-episode rule (``plots.py:14-56``) rather than delegating to it: that
function operates over a multi-run wide dataframe (many episodes' columns at
once), a different shape than one episode's own recorded state, so instead of
vendoring it this module computes the equivalent single-episode value
directly from ``terminal["num_round"]`` -- itself upstream's own recorded
round count, never re-derived, and exactly equal to the "first round the
value dropped below 5, else max_num_rounds" rule because this environment's
own ``step()`` already halts the episode the instant its collapse-or-horizon
test fires (``concurrent_env.py``; see ``environment.py``'s ``step()``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from aeread.shared_runner.measurement import (
    EstimandSpec,
    FamilyScoreSet,
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
from aeread.shared_runner.task.scheduler import PhaseInstance

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "govsim_common_pool_v1"
DOMAIN_VERSION = "1.0.0"

# Matches family_manifest()'s own "comparison_baseline" declaration
# (environment.py) exactly -- an AERead-authored scripted policy, never an
# upstream oracle (spec section 2).
BASELINE_POLICY_ID = "govsim_sustainable_v1"

NO_COLLAPSE_ESTIMAND_ID = "govsim_no_collapse"
NO_COLLAPSE_LEAF_ID = "govsim_no_collapse_leaf"
NO_COLLAPSE_REFERENCE_ID = "govsim_no_collapse_invariant"
NO_COLLAPSE_SCORER_ID = "govsim_no_collapse_scorer"

THRESHOLD_ADHERENCE_ESTIMAND_ID = "govsim_threshold_adherence"
THRESHOLD_ADHERENCE_LEAF_ID = "govsim_threshold_adherence_leaf"
THRESHOLD_ADHERENCE_REFERENCE_ID = "govsim_threshold_adherence_constraint"
THRESHOLD_ADHERENCE_SCORER_ID = "govsim_threshold_adherence_scorer"

SURVIVAL_MONTHS_ESTIMAND_ID = "govsim_survival_months"
SURVIVAL_MONTHS_LEAF_ID = "govsim_survival_months_leaf"
SURVIVAL_MONTHS_REFERENCE_ID = "govsim_survival_months_baseline"
SURVIVAL_MONTHS_SCORER_ID = "govsim_survival_months_scorer"

TOTAL_HARVEST_ESTIMAND_ID = "govsim_total_harvest"
TOTAL_HARVEST_LEAF_ID = "govsim_total_harvest_leaf"
TOTAL_HARVEST_REFERENCE_ID = "govsim_total_harvest_baseline"
TOTAL_HARVEST_SCORER_ID = "govsim_total_harvest_scorer"

EQUALITY_GINI_ESTIMAND_ID = "govsim_equality_gini"
EQUALITY_GINI_LEAF_ID = "govsim_equality_gini_leaf"
EQUALITY_GINI_REFERENCE_ID = "govsim_equality_gini_baseline"
EQUALITY_GINI_SCORER_ID = "govsim_equality_gini_scorer"

# The exact upstream file this module vendors gini() from, pinned at the
# adapter's own commit (docs/govsim_adapter_spec.md section 1). Checked
# against the pinned checkout by
# tests/test_govsim_measurement.py::test_upstream_plots_py_has_not_drifted_from_the_pinned_hash
# so a silent upstream file change cannot invalidate the vendored copy
# without this suite noticing.
UPSTREAM_GINI_SOURCE_FILE = "simulation/analysis/plots.py"
UPSTREAM_GINI_SOURCE_SHA256 = (
    "f6c2e6acef71e24777dc5764f7003a68ad8198d47efc636809988c4da69e7c68"
)

_NO_COLLAPSE_RULE: Mapping[str, str] = {
    "invariant": (
        "upstream's own recorded per-round collapse-or-horizon flag never "
        "fires while round_index + 1 < max_num_rounds"
    ),
    "upstream_collapse_test": "resource_in_pool < 5 or num_round >= max_num_rounds",
    "source": "simulation/scenarios/common/environment/concurrent_env.py",
}

_THRESHOLD_ADHERENCE_RULE: Mapping[str, str] = {
    "constraint": (
        "wanted_resource[agent] <= sustainability_threshold for every agent "
        "and every round"
    ),
    "note": (
        "sustainability_threshold is advisory only in upstream; nothing "
        "rejects or clamps a harvest above it (docs/govsim_adapter_spec.md "
        "section 0)"
    ),
    "source": "simulation/scenarios/common/environment/concurrent_env.py",
}


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail/measurement.py``'s identical convention: the pin
    changes exactly when the referenced adapter file changes.
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
        schema_ref="govsim/v1/case_payload",
        predicate=_implementation("govsim_base_domain_predicate", "environment.py"),
    )


def _rule_source_sha256(description: Mapping[str, str]) -> str:
    """Hash a rule's own canonical description text (never its code).

    Distinct from ``implementation`` (which pins the code that evaluates the
    rule): this pins the rule's declared TEXT, mirroring
    ``tau3_retail/measurement.py``'s ``nl_assertions`` rubric-text hash --
    the rule text changing (not just the code around it) is exactly what
    should change this digest.
    """
    return hashlib.sha256(canonical_json_bytes(dict(description))).hexdigest()


def _baseline_policy_source_sha256() -> str:
    """Pin the baseline policy's own definition (``policies.py``).

    The "source" a ``baseline_delta`` reference points at is the named,
    versioned, executable comparator itself (``docs/verifier_taxonomy.md``
    section 6) -- here ``govsim_sustainable_v1``, defined in ``policies.py``.
    """
    return _file_sha256("policies.py")


# ---------------------------------------------------------------------------
# Leaf declarations (spec section 2's table).
# ---------------------------------------------------------------------------


def build_no_collapse_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=NO_COLLAPSE_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=NO_COLLAPSE_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="state_invariant",
        input_scope="trajectory",
        units="pass",
        source_sha256=_rule_source_sha256(_NO_COLLAPSE_RULE),
        implementation=_implementation(NO_COLLAPSE_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=NO_COLLAPSE_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(NO_COLLAPSE_SCORER_ID, "measurement.py"),
    )


def build_threshold_adherence_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=THRESHOLD_ADHERENCE_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=THRESHOLD_ADHERENCE_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="pass",
        source_sha256=_rule_source_sha256(_THRESHOLD_ADHERENCE_RULE),
        implementation=_implementation(THRESHOLD_ADHERENCE_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=THRESHOLD_ADHERENCE_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(THRESHOLD_ADHERENCE_SCORER_ID, "measurement.py"),
    )


def build_survival_months_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=SURVIVAL_MONTHS_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        # Matches family_manifest()'s own family-level declaration
        # (environment.py): more survival is unambiguously the direction of
        # interest for this one leaf, unlike total_harvest/equality_gini
        # below (see their own build_*_leaf docstrings for why those two
        # stay direction="none").
        direction="maximize",
        units="rounds",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=SURVIVAL_MONTHS_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="baseline_delta",
        input_scope="terminal_state",
        units="rounds",
        source_sha256=_baseline_policy_source_sha256(),
        implementation=_implementation(SURVIVAL_MONTHS_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=SURVIVAL_MONTHS_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(SURVIVAL_MONTHS_SCORER_ID, "measurement.py"),
    )


def build_total_harvest_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=TOTAL_HARVEST_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        # Deliberately "none", not "maximize": harvesting more is a genuine
        # normative tradeoff in a commons dilemma (it can also be what
        # drives govsim_no_collapse to fail), never an unambiguous good --
        # docs/verifier_taxonomy.md section 4's "should not silently
        # convert a normative tradeoff into invalidity" applies just as much
        # to a declared direction as to a hard gate.
        direction="none",
        units="resource_units",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=TOTAL_HARVEST_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="baseline_delta",
        input_scope="terminal_state",
        units="resource_units",
        source_sha256=_baseline_policy_source_sha256(),
        implementation=_implementation(TOTAL_HARVEST_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=TOTAL_HARVEST_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(TOTAL_HARVEST_SCORER_ID, "measurement.py"),
    )


def build_equality_gini_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=EQUALITY_GINI_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        # Deliberately "none": a lower Gini is conventionally read as "more
        # equal," but this leaf declares no normative preference of its own
        # for equality over inequality -- it reports the coefficient and its
        # baseline delta, descriptively (docs/verifier_taxonomy.md section
        # 6: "Comparative effects stay in native units").
        direction="none",
        units="gini_coefficient",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=EQUALITY_GINI_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="baseline_delta",
        input_scope="terminal_state",
        units="gini_coefficient",
        source_sha256=_baseline_policy_source_sha256(),
        implementation=_implementation(EQUALITY_GINI_SCORER_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=EQUALITY_GINI_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(EQUALITY_GINI_SCORER_ID, "measurement.py"),
    )


def build_leaves() -> tuple[MeasurementLeafSpec, ...]:
    """The five leaves this family always declares, in a fixed order.

    Unlike ``tau3_retail`` (whose second leaf is declared only for some
    tasks), govsim's five leaves are identical for every case regardless of
    scenario, policy, or ``num_agents`` -- only the *scored values* vary
    with the case, never which claims are declared for it.
    """
    return (
        build_no_collapse_leaf(),
        build_threshold_adherence_leaf(),
        build_survival_months_leaf(),
        build_total_harvest_leaf(),
        build_equality_gini_leaf(),
    )


# ---------------------------------------------------------------------------
# Vendored upstream arithmetic (equality_gini only).
# ---------------------------------------------------------------------------


def _vendored_gini(array: np.ndarray) -> float:
    """Verbatim copy of upstream's ``gini()``.

    Source: ``simulation/analysis/plots.py`` lines 669-683, pinned upstream
    commit ``1d11adf047b24fa2ba0d44a1d4931015ea2e5210`` (sha256 of the whole
    file at that commit: ``UPSTREAM_GINI_SOURCE_SHA256`` above). Copied
    verbatim -- variable names, comments, and all -- rather than imported,
    because ``plots.py``'s own top-level imports (``plotly``, ``dash``,
    ``dash_mantine_components``, ``statsmodels``) are not installed in the
    bridge venv and are not needed for this one pure-numpy function (spec
    section 2). ``tests/test_govsim_measurement.py`` cross-checks this copy
    against upstream's real, unmodified function executed through the
    bridge (``GovsimBridge.call_upstream_gini``), byte-for-byte, so a
    transcription error here cannot go unnoticed.
    """
    # --- verbatim from here ---
    array = array.flatten()  # all values are treated equally, arrays must be 1d
    # remove nans
    array = array[~np.isnan(array)]
    if np.amin(array) < 0:
        array -= np.amin(array)  # values cannot be negative
    # array += 0.0000001 #values cannot be 0
    array = np.sort(array)  # values must be sorted
    index = np.arange(1, array.shape[0] + 1)  # index per array element
    n = array.shape[0]  # number of array elements
    g = (np.sum((2 * index - n - 1) * array)) / (n * np.sum(array))  # Gini coefficient
    # --- verbatim to here ---
    return float(g)


# ---------------------------------------------------------------------------
# Scorers.
# ---------------------------------------------------------------------------


def _operational_failure_envelope(
    leaf: MeasurementLeafSpec, evidence_refs: tuple[str, ...]
) -> ScoreEnvelope:
    """The typed, never-a-zero result for an ``operational_failure`` episode.

    Per ``docs/verifier_taxonomy.md`` section 9: "An invalid or missing
    observation must not be scored as an economic zero ... The receipt
    reports ``invalid_measurement``." Every scorer below returns exactly
    this for QC Gate 2's "malformed-operational" golden, never a forced
    ``0.0`` the way ``tau3_retail``'s termination-reason forcing does (that
    forcing is deliberately different: a non-stop tau2 termination is still
    a *known*, scoreable outcome; govsim's ``operational_failure`` is
    ``outcome_status: "outcome_unknown"`` -- see ``environment.py``'s
    ``outcome()`` -- which is a stronger, "cannot measure this" claim).
    """
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics={},
        reference_values={},
        validity=ValidityReport(
            "invalid",
            reasons=(
                "operational_failure: the episode terminated via a caught "
                "upstream assertion on a malformed action; measurement "
                "leaves are not computable for it and must never be "
                "reported as a scored zero",
            ),
        ),
        evidence_refs=evidence_refs,
    )


def score_no_collapse(
    leaf: MeasurementLeafSpec,
    *,
    terminal: Mapping[str, Any],
    max_num_rounds: int,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score ``govsim_no_collapse`` from ``terminal["round_trace"]``.

    Reads only upstream's own recorded ``collapsed_or_horizon`` flag per
    round (see ``environment.py``'s ``step()``); never re-derives the
    regeneration formula or the collapse test independently (spec section
    2's "never re-derived independently of upstream's own state").
    """
    if terminal["reason"] == "operational_failure":
        return _operational_failure_envelope(leaf, evidence_refs)
    round_trace = terminal["round_trace"]
    collapse_round: int | None = None
    for entry in round_trace:
        round_number = int(entry["round_index"]) + 1
        if entry["collapsed_or_horizon"] and round_number < max_num_rounds:
            collapse_round = round_number
            break
    passed = collapse_round is None
    metrics: dict[str, MetricValue] = {
        "rounds_completed": MetricValue(float(len(round_trace)), "count"),
    }
    if collapse_round is not None:
        metrics["collapse_round"] = MetricValue(float(collapse_round), "round")
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0 if passed else 0.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_threshold_adherence(
    leaf: MeasurementLeafSpec,
    *,
    terminal: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score ``govsim_threshold_adherence`` as a declared AND over a vector.

    ``primary`` is the single logical AND across every agent-round
    predicate (the one declared aggregation rule, per
    ``docs/verifier_taxonomy.md`` section 4); the complete per-agent-round
    vector is recorded in ``metrics``, never blended into ``primary`` --
    "a vector of pass/fail per agent-round, never one rate" (spec section
    2).
    """
    if terminal["reason"] == "operational_failure":
        return _operational_failure_envelope(leaf, evidence_refs)
    round_trace = terminal["round_trace"]
    metrics: dict[str, MetricValue] = {}
    all_within = True
    for entry in round_trace:
        round_index = int(entry["round_index"])
        threshold = entry["sustainability_threshold"]
        for agent_id in sorted(entry["wanted_resource"]):
            wanted = entry["wanted_resource"][agent_id]
            within = threshold is None or wanted <= threshold
            if not within:
                all_within = False
            metrics[f"round_{round_index}_{agent_id}_within_threshold"] = MetricValue(
                1.0 if within else 0.0, "pass"
            )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0 if all_within else 0.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_survival_months(
    leaf: MeasurementLeafSpec,
    *,
    terminal: Mapping[str, Any],
    baseline_survival_months: float | None,
    max_num_rounds: int,
    num_agents: int,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score ``govsim_survival_months`` against the baseline's own value.

    ``primary`` is this episode's own native survival-months count
    (``terminal["num_round"]``, upstream's own recorded round count at
    termination -- never re-derived; see this module's own docstring for
    why that value already equals the "first round below 5, else
    max_num_rounds" rule for this environment). The baseline's value is
    recorded separately in ``reference_values``, and the delta as a
    ``metrics`` diagnostic -- three distinct numbers, per spec section 2.

    ``baseline_survival_months`` is ``None`` when no caller supplied one
    (this module never re-runs a baseline episode itself, per this
    module's own docstring): ``reference_values``/``metrics`` simply omit
    the baseline/delta in that case rather than fabricating one -- this is
    exactly the shape ``GovsimScorer.__call__`` (the production finalizer
    seam, ``task.evaluation.finalize_family_execution``'s
    ``plugin.build_scorer(family_case)(scoring_input, ...)``) hits, since no
    baseline is reachable from a ``FamilyScoringInput`` alone.
    """
    if terminal["reason"] == "operational_failure":
        return _operational_failure_envelope(leaf, evidence_refs)
    survival_months = min(float(terminal["num_round"]), float(max_num_rounds))
    metrics: dict[str, MetricValue] = {}
    reference_values: dict[str, MetricValue] = {}
    if baseline_survival_months is not None:
        delta = survival_months - float(baseline_survival_months)
        metrics["delta_vs_baseline"] = MetricValue(delta, "rounds")
        reference_values["baseline"] = MetricValue(float(baseline_survival_months), "rounds")
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(
            survival_months,
            "rounds",
            metadata={"degenerate_single_agent": num_agents == 1},
        ),
        metrics=metrics,
        reference_values=reference_values,
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_total_harvest(
    leaf: MeasurementLeafSpec,
    *,
    terminal: Mapping[str, Any],
    baseline_total_harvest: float | None,
    num_agents: int,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score ``govsim_total_harvest`` against the baseline's own value.

    ``primary`` is the sum of ``terminal["collected_resource"]`` --
    upstream's own cumulative per-agent harvest total across the whole
    episode (``concurrent_env.py``'s ``_assign_resource``:
    ``collected_resource[agent] += res`` every round; never reset until the
    next episode), never re-derived from a per-round trace.

    ``baseline_total_harvest`` is ``None`` when no caller supplied one (this
    module never re-runs a baseline episode itself, per this module's own
    docstring): ``reference_values``/``metrics`` simply omit the
    baseline/delta in that case rather than fabricating one -- mirrors
    ``score_survival_months``'s identical pattern, which is exactly the
    shape ``GovsimScorer.__call__`` (the production finalizer seam) hits,
    since no baseline is reachable from a ``FamilyScoringInput`` alone.
    """
    if terminal["reason"] == "operational_failure":
        return _operational_failure_envelope(leaf, evidence_refs)
    collected = terminal["collected_resource"]
    total = float(sum(collected.values()))
    metrics = {
        f"collected_{agent_id}": MetricValue(float(quantity), "resource_units")
        for agent_id, quantity in sorted(collected.items())
    }
    reference_values: dict[str, MetricValue] = {}
    if baseline_total_harvest is not None:
        delta = total - float(baseline_total_harvest)
        metrics["delta_vs_baseline"] = MetricValue(delta, "resource_units")
        reference_values["baseline"] = MetricValue(
            float(baseline_total_harvest), "resource_units"
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(
            total,
            "resource_units",
            metadata={"degenerate_single_agent": num_agents == 1},
        ),
        metrics=metrics,
        reference_values=reference_values,
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_equality_gini(
    leaf: MeasurementLeafSpec,
    *,
    terminal: Mapping[str, Any],
    baseline_gini: float | None,
    num_agents: int,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score ``govsim_equality_gini`` against the baseline's own value.

    ``primary`` is the vendored ``gini()`` (this module's own ``_vendored_gini``,
    upstream's own formula) applied to ``terminal["collected_resource"]``'s
    per-agent totals. For ``num_agents == 1`` this is trivially ``0.0``
    (upstream's own formula, a single-element array); ``primary.metadata``
    flags this explicitly rather than silently reporting a "perfectly
    equal" verdict for a case with no peer to be unequal against (spec
    section 4's degenerate-reference golden).

    ``baseline_gini`` is ``None`` when no caller supplied one (this module
    never re-runs a baseline episode itself, per this module's own
    docstring): ``reference_values``/``metrics`` simply omit the
    baseline/delta in that case rather than fabricating one -- mirrors
    ``score_survival_months``'s identical pattern, which is exactly the
    shape ``GovsimScorer.__call__`` (the production finalizer seam) hits,
    since no baseline is reachable from a ``FamilyScoringInput`` alone.
    """
    if terminal["reason"] == "operational_failure":
        return _operational_failure_envelope(leaf, evidence_refs)
    collected = terminal["collected_resource"]
    values = np.array(
        [float(quantity) for _agent_id, quantity in sorted(collected.items())],
        dtype=float,
    )
    gini_value = _vendored_gini(values)
    metrics: dict[str, MetricValue] = {}
    reference_values: dict[str, MetricValue] = {}
    if baseline_gini is not None:
        delta = gini_value - float(baseline_gini)
        metrics["delta_vs_baseline"] = MetricValue(delta, "gini_coefficient")
        reference_values["baseline"] = MetricValue(float(baseline_gini), "gini_coefficient")
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(
            gini_value,
            "gini_coefficient",
            metadata={"degenerate_single_agent": num_agents == 1},
        ),
        metrics=metrics,
        reference_values=reference_values,
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Scorer wiring (environment.py's ``build_scorer`` hook).
# ---------------------------------------------------------------------------


def _round_trace_from_phase_instances(
    phase_instances: tuple[PhaseInstance, ...],
) -> list[Any]:
    """Read the cumulative ``round_trace`` off the last replayed phase state.

    ``scoring_input.outcome`` never carries ``round_trace``
    (``environment.py``'s ``outcome()`` omits it -- see that module's own
    ``terminal()``/``outcome()`` split), so the two trajectory-scoped leaves
    (``govsim_no_collapse``, ``govsim_threshold_adherence``) read it from
    ``scoring_input.phase_instances`` instead.

    ``environment.py``'s ``step()`` REFLECT branch is the only place that
    appends to ``round_trace``, directly into its own state dict, and never
    resets it, so by the LAST phase instance's LAST transition, that state
    carries the full, cumulative trace for the whole episode -- exactly what
    ``GovsimPlugin.terminal()`` itself reads off that same state
    (``state.get("round_trace", [])``). Ruling R3
    (kernel_scoring_contract_spec.md): reading it here is safe because every
    phase boundary's post-state hash is cross-checked against sealed
    evidence during replay, so a ``round_trace`` that diverged from the real
    run would already have failed finalization before this scorer is ever
    called -- this only reads what the verified re-execution produced, never
    re-derives it independently.
    """
    if not phase_instances:
        return []
    last_state = phase_instances[-1].transitions[-1].state
    if not isinstance(last_state, Mapping):
        return []
    return list(last_state.get("round_trace", ()))


@dataclass(frozen=True, slots=True)
class GovsimScorer:
    """One case's fixed set of five declared leaves, plus their scorers.

    ``environment.py``'s ``build_scorer`` hook returns one of these.
    ``task.evaluation.finalize_family_execution`` calls the returned object
    directly (``plugin.build_scorer(family_case)(scoring_input,
    evidence_refs=scoring_input.evidence_refs)``, per
    kernel_scoring_contract_spec.md section 1) -- ``__call__`` below is the
    seam that satisfies that exact production call and returns every one of
    this family's five declared finalize-time leaves (section 5), via
    ``score_all`` (the single source of truth for the full set; ``__call__``
    is a thin wrapper over it, never new scoring logic). Each leaf's own
    named method is still exercised directly by
    ``tests/test_govsim_measurement.py``'s goldens, mirroring
    ``tau3_retail``'s identical convention for its own non-primary leaf.
    """

    scenario: str
    num_agents: int
    max_num_rounds: int
    leaves: tuple[MeasurementLeafSpec, ...]

    @property
    def no_collapse_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def threshold_adherence_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    @property
    def survival_months_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[2]

    @property
    def total_harvest_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[3]

    @property
    def equality_gini_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[4]

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        """Score one finalized episode exactly as the production finalizer
        calls it: ``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``
        (``task.evaluation.finalize_family_execution``, per
        kernel_scoring_contract_spec.md section 1).

        Returns every one of this family's five declared finalize-time
        leaves (spec section 5) -- a thin wrapper over ``score_all``, this
        family's single source of truth for the full set; no new scoring
        logic is written here. ``scoring_input.outcome`` never carries
        ``round_trace`` (``environment.py``'s ``outcome()`` omits it), so
        the two trajectory-scoped leaves' input is read off
        ``scoring_input.phase_instances`` instead, via
        ``_round_trace_from_phase_instances`` (see that function's own
        docstring for why this is safe under ruling R3). No baseline is
        reachable from a ``FamilyScoringInput`` alone (this module never
        re-runs a baseline episode itself): every comparative leaf's delta
        and reference value are honestly omitted here, never fabricated
        (see ``score_survival_months``'s own docstring, and its identical
        pattern now mirrored by ``score_total_harvest``/
        ``score_equality_gini``).
        """
        outcome = scoring_input.outcome
        terminal_like: dict[str, Any] = {
            "reason": outcome["termination_reason"],
            "num_round": outcome["num_round"],
            "collected_resource": outcome["collected_resource"],
            "round_trace": _round_trace_from_phase_instances(scoring_input.phase_instances),
        }
        scored = self.score_all(
            terminal=terminal_like,
            baseline_survival_months=None,
            baseline_total_harvest=None,
            baseline_gini=None,
            evidence_refs=evidence_refs,
        )
        return FamilyScoreSet(
            primary_leaf_id=self.survival_months_leaf.leaf_id,
            scores=(
                scored[NO_COLLAPSE_ESTIMAND_ID],
                scored[THRESHOLD_ADHERENCE_ESTIMAND_ID],
                scored[SURVIVAL_MONTHS_ESTIMAND_ID],
                scored[TOTAL_HARVEST_ESTIMAND_ID],
                scored[EQUALITY_GINI_ESTIMAND_ID],
            ),
            admission_leaf_ids=(self.survival_months_leaf.leaf_id,),
        )

    def score_no_collapse(
        self, *, terminal: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_no_collapse(
            self.no_collapse_leaf,
            terminal=terminal,
            max_num_rounds=self.max_num_rounds,
            evidence_refs=evidence_refs,
        )

    def score_threshold_adherence(
        self, *, terminal: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_threshold_adherence(
            self.threshold_adherence_leaf, terminal=terminal, evidence_refs=evidence_refs
        )

    def score_survival_months(
        self,
        *,
        terminal: Mapping[str, Any],
        baseline_survival_months: float | None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_survival_months(
            self.survival_months_leaf,
            terminal=terminal,
            baseline_survival_months=baseline_survival_months,
            max_num_rounds=self.max_num_rounds,
            num_agents=self.num_agents,
            evidence_refs=evidence_refs,
        )

    def score_total_harvest(
        self,
        *,
        terminal: Mapping[str, Any],
        baseline_total_harvest: float | None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_total_harvest(
            self.total_harvest_leaf,
            terminal=terminal,
            baseline_total_harvest=baseline_total_harvest,
            num_agents=self.num_agents,
            evidence_refs=evidence_refs,
        )

    def score_equality_gini(
        self,
        *,
        terminal: Mapping[str, Any],
        baseline_gini: float | None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_equality_gini(
            self.equality_gini_leaf,
            terminal=terminal,
            baseline_gini=baseline_gini,
            num_agents=self.num_agents,
            evidence_refs=evidence_refs,
        )

    def score_all(
        self,
        *,
        terminal: Mapping[str, Any],
        baseline_survival_months: float | None,
        baseline_total_harvest: float | None,
        baseline_gini: float | None,
        evidence_refs: tuple[str, ...] = (),
    ) -> dict[str, ScoreEnvelope]:
        """All five leaves at once -- still five separate typed envelopes,
        keyed by estimand id, never blended into one number."""
        return {
            NO_COLLAPSE_ESTIMAND_ID: self.score_no_collapse(
                terminal=terminal, evidence_refs=evidence_refs
            ),
            THRESHOLD_ADHERENCE_ESTIMAND_ID: self.score_threshold_adherence(
                terminal=terminal, evidence_refs=evidence_refs
            ),
            SURVIVAL_MONTHS_ESTIMAND_ID: self.score_survival_months(
                terminal=terminal,
                baseline_survival_months=baseline_survival_months,
                evidence_refs=evidence_refs,
            ),
            TOTAL_HARVEST_ESTIMAND_ID: self.score_total_harvest(
                terminal=terminal,
                baseline_total_harvest=baseline_total_harvest,
                evidence_refs=evidence_refs,
            ),
            EQUALITY_GINI_ESTIMAND_ID: self.score_equality_gini(
                terminal=terminal, baseline_gini=baseline_gini, evidence_refs=evidence_refs
            ),
        }


def build_scorer(family_case: Mapping[str, Any]) -> GovsimScorer:
    """Build the one ``GovsimScorer`` for a case's ``family_case`` payload.

    Unlike ``tau3_retail`` (whose declared leaves vary per task), every
    govsim case declares the identical five leaves (``build_leaves()``
    takes no arguments) -- only the scored *values* depend on
    ``family_case``'s ``num_agents``/``max_num_rounds``, stored here for the
    convenience wrapper methods above.
    """
    env_cfg = family_case["env_cfg"]
    return GovsimScorer(
        scenario=family_case["scenario"],
        num_agents=int(env_cfg["num_agents"]),
        max_num_rounds=int(env_cfg["max_num_rounds"]),
        leaves=build_leaves(),
    )


__all__ = [
    "BASELINE_POLICY_ID",
    "EQUALITY_GINI_ESTIMAND_ID",
    "EQUALITY_GINI_LEAF_ID",
    "EQUALITY_GINI_REFERENCE_ID",
    "GovsimScorer",
    "NO_COLLAPSE_ESTIMAND_ID",
    "NO_COLLAPSE_LEAF_ID",
    "NO_COLLAPSE_REFERENCE_ID",
    "SURVIVAL_MONTHS_ESTIMAND_ID",
    "SURVIVAL_MONTHS_LEAF_ID",
    "SURVIVAL_MONTHS_REFERENCE_ID",
    "THRESHOLD_ADHERENCE_ESTIMAND_ID",
    "THRESHOLD_ADHERENCE_LEAF_ID",
    "THRESHOLD_ADHERENCE_REFERENCE_ID",
    "TOTAL_HARVEST_ESTIMAND_ID",
    "TOTAL_HARVEST_LEAF_ID",
    "TOTAL_HARVEST_REFERENCE_ID",
    "UPSTREAM_GINI_SOURCE_FILE",
    "UPSTREAM_GINI_SOURCE_SHA256",
    "build_equality_gini_leaf",
    "build_leaves",
    "build_no_collapse_leaf",
    "build_scorer",
    "build_survival_months_leaf",
    "build_threshold_adherence_leaf",
    "build_total_harvest_leaf",
    "score_equality_gini",
    "score_no_collapse",
    "score_survival_months",
    "score_threshold_adherence",
    "score_total_harvest",
]
