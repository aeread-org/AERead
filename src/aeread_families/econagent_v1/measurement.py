"""Measurement declarations for the econagent_v1 adapter (spec section 2).

EconAgent has no upstream reward or task-success criterion at all --
``simulate.py`` never scores an episode; it only dumps ``dense_log``. There
is nothing to reproduce as a canonical score. This module therefore declares
a **vector** of three separately-labelled ``MeasurementLeafSpec`` claims,
never blended into one number, with **no ``objective_reference`` and no
optimum claim of any kind** (spec section 2/6):

* **Leaf 1 -- ``econagent_budget_identity`` (deterministic,
  ``rule_constraint``/``state_invariant``).** Per-agent, per-month:
  ``inventory_coin[t] == inventory_coin[t-1] + labor_income - tax_paid +
  lump_sum - consumption_spend + saving_interest``. All terms are read from
  the executed upstream ``dense_log`` -- see :func:`compute_budget_identity_residuals`
  for the one non-obvious sourcing decision (which of two upstream-recorded
  "income" fields is actually the right one) and for how ``saving_interest``
  -- a term upstream never separately records anywhere -- is derived
  honestly rather than either fabricated or silently dropped.
* **Leaf 2 -- ``econagent_tax_bracket_arithmetic`` (deterministic,
  ``rule_constraint``/``constraint_satisfaction``).** Each recorded
  ``tax_paid`` is checked against upstream's own ``PeriodicBracketTax``
  bracket computation, re-invoked live through
  :meth:`~aeread_families.econagent_v1.econagent_bridge.EconAgentBridge.recompute_tax`
  -- never a reimplemented piecewise formula (adapter rule 2).
* **Leaf 3 -- ``econagent_macro_trajectory`` (``comparative``/
  ``baseline_delta``, mode ``descriptive``/``baseline_only``).** GDP-proxy
  (aggregate consumption), price level, and unemployment-proxy time series.
  Diagnostic only: no comparator, no optimum, no pass/fail meaning.

The replay/hash/admission surface (spec section 2's fourth row,
``measurement_validity``) is not a ``MeasurementLeafSpec`` at all --
per ``docs/verifier_taxonomy.md`` section 9 it is an integrity layer, not a
capability score, and is expressed through each ``ScoreEnvelope``'s own
``status``/``validity`` fields (``status="invalid_measurement"`` when a
dense log could not be produced or is malformed) plus the replay test
(milestone 3), never as a fourth leaf here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
from aeread.shared_runner.task.evaluation import FamilyScoringInput
from aeread.shared_runner.task.scheduler import PhaseInstance

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "econagent_v1_pilot_v1"
DOMAIN_VERSION = "1.0.0"

# The one validity-domain predicate every leaf below shares (``_validity_domain()``).
# Named here -- rather than left as the inline literal `_validity_domain()`
# passes to `_implementation` -- so `environment.py`'s `family_manifest()` can
# declare it under `scoring.reference_provider_ids` without a second,
# independently-typed copy of the same string (mirrors govsim's identically-
# purposed `BASE_DOMAIN_PREDICATE_ID`).
DOMAIN_PREDICATE_ID = "econagent_v1_domain_predicate"

BUDGET_IDENTITY_ESTIMAND_ID = "econagent_budget_identity"
BUDGET_IDENTITY_LEAF_ID = "econagent_budget_identity_leaf"
BUDGET_IDENTITY_REFERENCE_ID = "econagent_budget_identity_reference"
# The reference's own IMPLEMENTATION id (`ReferenceSpec.implementation`) --
# distinct from `BUDGET_IDENTITY_REFERENCE_ID` above (`ReferenceSpec.reference_id`,
# a different field). Named for the same reason as `DOMAIN_PREDICATE_ID`.
BUDGET_IDENTITY_REFERENCE_IMPLEMENTATION_ID = "econagent_budget_identity_check"
BUDGET_IDENTITY_SCORER_ID = "econagent_budget_identity_scorer"

TAX_BRACKET_ESTIMAND_ID = "econagent_tax_bracket_arithmetic"
TAX_BRACKET_LEAF_ID = "econagent_tax_bracket_arithmetic_leaf"
TAX_BRACKET_REFERENCE_ID = "econagent_tax_bracket_reference"
TAX_BRACKET_REFERENCE_IMPLEMENTATION_ID = "econagent_tax_bracket_bridge_recompute"
TAX_BRACKET_SCORER_ID = "econagent_tax_bracket_arithmetic_scorer"

MACRO_TRAJECTORY_ESTIMAND_ID = "econagent_macro_trajectory"
MACRO_TRAJECTORY_LEAF_ID = "econagent_macro_trajectory_leaf"
MACRO_TRAJECTORY_REFERENCE_ID = "econagent_macro_trajectory_reference"
MACRO_TRAJECTORY_REFERENCE_IMPLEMENTATION_ID = "econagent_macro_trajectory_descriptive"
MACRO_TRAJECTORY_SCORER_ID = "econagent_macro_trajectory_scorer"

# Floating-point residue tolerance only -- a violation past this tolerance is
# an adapter/bridge bug, never a policy-quality slack (spec section 2:
# "violation is an adapter/bridge bug, not a policy failure").
BUDGET_IDENTITY_TOLERANCE = 1e-6
TAX_BRACKET_TOLERANCE = 1e-6


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail/measurement.py``'s identical helper: hashes the
    actual adapter module that performs the referenced step, so the pin
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
        schema_ref="econagent_v1/case_payload",
        predicate=_implementation(DOMAIN_PREDICATE_ID, "environment.py"),
    )


# ---------------------------------------------------------------------------
# Leaf declarations.
# ---------------------------------------------------------------------------


def build_budget_identity_leaf(pins: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 1: the deterministic, per-agent-per-month budget identity.

    ``reference.source_sha256`` pins ``config.yaml`` itself -- the source
    that defines the four components (and their fixed order) the identity's
    six terms are read from -- not any code.
    """
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=BUDGET_IDENTITY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=BUDGET_IDENTITY_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="state_invariant",
        input_scope="trajectory",
        units="pass",
        source_sha256=pins["config_yaml_sha256"],
        implementation=_implementation(BUDGET_IDENTITY_REFERENCE_IMPLEMENTATION_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=BUDGET_IDENTITY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(BUDGET_IDENTITY_SCORER_ID, "measurement.py"),
    )


def build_tax_bracket_leaf(pins: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 2: tax_paid checked against upstream's own bracket computation."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=TAX_BRACKET_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=TAX_BRACKET_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="pass",
        source_sha256=pins["config_yaml_sha256"],
        implementation=_implementation(
            TAX_BRACKET_REFERENCE_IMPLEMENTATION_ID, "econagent_bridge.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=TAX_BRACKET_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(TAX_BRACKET_SCORER_ID, "measurement.py"),
    )


def build_macro_trajectory_leaf(pins: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 3: descriptive-only GDP-proxy/price/unemployment time series.

    Deliberately **not** given an ``objective_reference`` even though it
    looks numeric (spec section 2): no declared optimum, no bound, no
    comparator this pass. ``reference_kind="baseline_delta"`` is the
    closest-fitting ``comparative`` reference kind in the kernel's own
    grammar; ``mode: descriptive/baseline_only`` (spec section 4's wording)
    is recorded in ``reference.implementation``'s own docstring rather than
    a schema field, since the kernel's ``ReferenceSpec`` has no separate
    "mode" attribute -- there is no comparator to bind here at all this pass.
    """
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=MACRO_TRAJECTORY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="coin",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=MACRO_TRAJECTORY_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="baseline_delta",
        input_scope="trajectory",
        units="coin",
        source_sha256=pins["config_yaml_sha256"],
        implementation=_implementation(MACRO_TRAJECTORY_REFERENCE_IMPLEMENTATION_ID, "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=MACRO_TRAJECTORY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(MACRO_TRAJECTORY_SCORER_ID, "measurement.py"),
    )


def build_leaves(pins: Mapping[str, Any]) -> tuple[MeasurementLeafSpec, ...]:
    """The three measurement leaves declared for every econagent_v1 case.

    Always exactly three -- unlike ``tau3_retail`` (whose second leaf is
    conditionally absent), nothing about this family's leaf declaration is
    task-dependent: every pinned scenario carries the same four upstream
    components, so all three leaves apply uniformly.
    """
    return (
        build_budget_identity_leaf(pins),
        build_tax_bracket_leaf(pins),
        build_macro_trajectory_leaf(pins),
    )


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _agent_ids(n_agents: int) -> tuple[str, ...]:
    return tuple(str(index) for index in range(n_agents))


def _invalid(
    leaf: MeasurementLeafSpec, reason: str, *, evidence_refs: tuple[str, ...] = ()
) -> ScoreEnvelope:
    """A typed ``invalid_measurement`` result -- never a fabricated zero.

    Used whenever the episode's ``dense_log`` is missing (bridge failure,
    e.g. the malformed/operational-failure golden) or structurally
    malformed -- per spec section 6/``docs/verifier_taxonomy.md`` section 9,
    an invalid or missing observation must not be scored as an economic
    zero or a failed policy.
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


def _require_dense_log(dense_log: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Return ``dense_log`` if it looks usable, else ``None`` (caller invalidates)."""
    if dense_log is None:
        return None
    if "states" not in dense_log or "PeriodicTax" not in dense_log:
        return None
    return dense_log


# ---------------------------------------------------------------------------
# Leaf 1: econagent_budget_identity.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BudgetIdentityResidual:
    """One agent-month's closing residual for the six-term budget identity.

    ``expected_saving_interest`` is 0.0 on every non-boundary month (the
    identity's own invariant: no interest term can legitimately appear
    outside a ``world.period`` boundary) and ``world_interest_rate *
    closing_balance_before_interest`` on a boundary month -- the one formula
    upstream's own ``SimpleSaving.component_step`` actually applies, using
    upstream's own recorded rate for that month, never a reimplemented
    Taylor-rule computation. ``residual`` must equal this value exactly (to
    tolerance) for the identity to hold; see :func:`score_budget_identity`.
    """

    month: int
    agent_id: str
    residual: float
    is_boundary_month: bool
    expected_saving_interest: float


def compute_budget_identity_residuals(
    dense_log: Mapping[str, Any],
    n_agents: int,
    world_period: int,
    month_actions: Sequence[Mapping[str, Sequence[float]]],
    world_interest_rate_by_month: Sequence[float],
) -> tuple[BudgetIdentityResidual, ...]:
    """Derive, per agent-month, the budget identity's closing residual.

    Never recomputes upstream's tax/consumption/interest arithmetic --
    re-arranges five already-recorded terms
    (``inventory_coin[t-1]``, ``labor_income``, ``tax_paid``, ``lump_sum``,
    ``consumption_spend``, ``inventory_coin[t]``) read verbatim from
    ``dense_log``/``month_actions`` to isolate the sixth, ``saving_interest``:

        residual := inventory_coin[t]
            - (inventory_coin[t-1] + labor_income - tax_paid
               + lump_sum - consumption_spend)

    **Why this, not a direct read, for ``saving_interest``.** Upstream's
    ``SimpleSaving.component_step`` adds the interest payoff straight to
    ``agent.state["inventory"]["Coin"]`` with no separate per-agent field or
    dense-log entry anywhere -- ``agent.state["saving"]`` is a vestigial
    field upstream initializes to 0 and never mutates (confirmed empirically:
    it reads 0 in every recorded month of every probed episode). There is
    therefore no upstream-recorded value to "read" for this one term; the
    residual above is the only honest way to surface it, and it is exactly
    equal to ``world_interest_rate * closing_balance_before_interest`` on a
    ``world.period`` boundary month by upstream's own component ORDER
    (Labor, Tax, Consumption, Saving -- SimpleSaving always runs last), and
    exactly 0 on every other month by upstream's own documented
    ``timestep % world.period == 0`` gate on ``SimpleSaving.component_step``
    -- :func:`score_budget_identity` checks the residual against exactly
    this formula (via ``expected_saving_interest`` below), never merely that
    a boundary-month residual is non-negative. ``world_interest_rate_by_month``
    supplies the one input that formula needs per month:
    ``environment.py``'s ``step()`` captures ``state["world"]["interest_rate"]``
    -- upstream's own recorded rate, read from the live bridge immediately
    *before* that month's ``step_month()`` call, i.e. before that same
    month's ``SimpleSaving`` could have advanced it to the *next* boundary
    month's rate -- and carries it forward per month, never a reimplemented
    Taylor-rule computation of the rate itself.

    **Why ``dense_log["PeriodicTax"][...]["income"]``, not
    ``dense_log["states"][...]["income"]["Coin"]``, for ``labor_income``.**
    Both are upstream-recorded, but they answer different questions.
    ``SimpleLabor.component_step`` sets ``agent.income["Coin"] = payoff``
    only inside its ``if 1 <= action <= num_labor_hours:`` branch -- on a
    month where ``complex_actions`` chooses zero labor for an agent, that
    field is **never reset to 0** and keeps showing whatever positive value
    it last held, i.e. it means "last positive income", not "this month's
    income". ``PeriodicBracketTax``'s own ``income`` field
    (``agent.state["production"] - last_coin``, a production-delta) reads 0
    on exactly that same no-op month, because ``agent.state["production"]``
    is only incremented inside the identical branch. Confirmed empirically
    against a real bridge-driven episode while building this leaf: sourcing
    ``labor_income`` from ``states[...]["income"]["Coin"]`` produces large
    spurious residuals on any no-op-labor month; sourcing it from
    ``PeriodicTax[...]["income"]`` produces an exact-zero (to float
    precision) residual on every non-boundary month.

    **Why ``consumption_spend`` needs ``month_actions``, not a direct read
    of ``dense_log["states"][...]["consumption"]["Coin"]``.** The exact
    same staleness problem recurs one component later:
    ``SimpleConsumption.component_step`` also does ``if action == 0:
    continue`` for its own (separate) consumption action -- on a month
    where ``complex_actions`` chooses a consumption action of 0 for an
    agent, ``agent.consumption["Coin"]`` is never reset and keeps showing
    the last month's positive consumption value, even though *no coin was
    actually deducted from inventory this month*. There is no
    production-delta-style substitute field for consumption the way
    ``PeriodicBracketTax`` incidentally provides one for income, so this
    reads the actual action ``complex_actions`` chose that month instead
    (``month_actions[month-1][agent_id][1]``, upstream's own returned
    ``[labor, consumption]`` action pair, verbatim, reported back by the
    bridge's own ``step_month`` response -- never reimplemented or
    guessed): a consumption action of exactly 0 means upstream's own
    ``SimpleConsumption`` took its own NO-OP branch, so the true
    ``consumption_spend`` for that month is 0, not the stale field value.
    Confirmed empirically against a real 2-agent bridge-driven episode
    while building this leaf (an agent with a 0 consumption action).

    Raises ``ValueError``/``KeyError`` on a structurally malformed
    ``dense_log``/``month_actions`` -- callers (:func:`score_budget_identity`)
    turn that into a typed ``invalid_measurement`` result, never a silent
    pass.
    """
    states = dense_log["states"]
    tax_log = dense_log["PeriodicTax"]
    episode_length = len(tax_log)
    if len(states) != episode_length + 1:
        raise ValueError(
            "dense_log is inconsistent: expected len(states) == "
            f"len(PeriodicTax) + 1 (post-reset state plus one per month), "
            f"got len(states)={len(states)} len(PeriodicTax)={episode_length}"
        )
    if len(month_actions) != episode_length:
        raise ValueError(
            "month_actions is inconsistent: expected one entry per month, "
            f"got len(month_actions)={len(month_actions)} episode_length={episode_length}"
        )
    if len(world_interest_rate_by_month) != episode_length:
        raise ValueError(
            "world_interest_rate_by_month is inconsistent: expected one entry "
            f"per month, got len(world_interest_rate_by_month)="
            f"{len(world_interest_rate_by_month)} episode_length={episode_length}"
        )
    residuals: list[BudgetIdentityResidual] = []
    for month in range(1, episode_length + 1):
        prev_state = states[month - 1]
        cur_state = states[month]
        tax_month = tax_log[month - 1]
        actions_month = month_actions[month - 1]
        is_boundary_month = world_period > 0 and (month % world_period) == 0
        for agent_id in _agent_ids(n_agents):
            inv_prev = float(prev_state[agent_id]["inventory"]["Coin"])
            inv_cur = float(cur_state[agent_id]["inventory"]["Coin"])
            labor_income = float(tax_month[agent_id]["income"])
            tax_paid = float(tax_month[agent_id]["tax_paid"])
            lump_sum = float(tax_month[agent_id]["lump_sum"])
            consumption_action = float(actions_month[agent_id][1])
            consumption_spend = (
                0.0
                if consumption_action == 0.0
                else float(cur_state[agent_id]["consumption"]["Coin"])
            )
            closing_balance_before_interest = (
                inv_prev + labor_income - tax_paid + lump_sum - consumption_spend
            )
            residual = inv_cur - closing_balance_before_interest
            expected_saving_interest = (
                float(world_interest_rate_by_month[month - 1]) * closing_balance_before_interest
                if is_boundary_month
                else 0.0
            )
            residuals.append(
                BudgetIdentityResidual(
                    month=month,
                    agent_id=agent_id,
                    residual=residual,
                    # Real check, not a guess: mirrors SimpleSaving's own
                    # documented `timestep % world.period == 0` gate.
                    is_boundary_month=is_boundary_month,
                    expected_saving_interest=expected_saving_interest,
                )
            )
    return tuple(residuals)


def score_budget_identity(
    leaf: MeasurementLeafSpec,
    *,
    dense_log: Mapping[str, Any] | None,
    n_agents: int,
    world_period: int,
    month_actions: Sequence[Mapping[str, Sequence[float]]],
    world_interest_rate_by_month: Sequence[float],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 1 from an already-terminated episode's dense log.

    ``world_period`` is upstream's own config constant (``env.world.period``,
    exposed by ``econagent_bridge_driver.py``'s ``agent_snapshot`` op) --
    read, not guessed, and used only to identify which months
    ``SimpleSaving`` fires on, mirroring its own documented gate.
    ``month_actions`` is ``terminal()``'s own ``month_actions`` list -- the
    verbatim, upstream-computed ``[labor, consumption]`` pair the bridge
    reported back for each month (see
    :func:`compute_budget_identity_residuals`'s docstring for why this is
    required, not optional, to source ``consumption_spend`` correctly).
    ``world_interest_rate_by_month`` is ``terminal()``'s own
    ``world_interest_rate_by_month`` list (``environment.py``'s ``step()``
    captures it once per month, before that month's mutation, from the live
    bridge's own ``state["world"]["interest_rate"]``) -- required so a
    boundary-month residual can be checked against the exact formula
    upstream's own ``SimpleSaving`` applies, not merely against "not
    negative" (see :func:`compute_budget_identity_residuals`'s docstring).
    """
    usable = _require_dense_log(dense_log)
    if usable is None:
        return _invalid(
            leaf,
            "no usable dense_log for this episode (bridge failure, early "
            "termination, or a dense_log missing the 'states'/'PeriodicTax' keys)",
            evidence_refs=evidence_refs,
        )
    try:
        residuals = compute_budget_identity_residuals(
            usable, n_agents, world_period, month_actions, world_interest_rate_by_month
        )
    except (KeyError, ValueError, TypeError, IndexError) as error:
        return _invalid(
            leaf, f"malformed dense_log: {type(error).__name__}: {error}",
            evidence_refs=evidence_refs,
        )

    violations: list[dict[str, Any]] = []
    boundary_residuals = 0
    for entry in residuals:
        if entry.is_boundary_month:
            boundary_residuals += 1
        # One uniform, exact check for every month: a non-boundary month's
        # expected_saving_interest is always 0.0 (no interest can
        # legitimately appear off-cycle), and a boundary month's is
        # `world_interest_rate * closing_balance_before_interest` -- the
        # actual formula upstream's own SimpleSaving applies, never merely
        # "not negative" (docs/econagent_codex_triage.md finding 1: an
        # arbitrary, unexplained positive residual on a boundary month used
        # to pass unconditionally).
        if abs(entry.residual - entry.expected_saving_interest) > BUDGET_IDENTITY_TOLERANCE:
            violations.append(
                {
                    "month": entry.month,
                    "agent_id": entry.agent_id,
                    "residual": entry.residual,
                    "expected_saving_interest": entry.expected_saving_interest,
                    "reason": (
                        "boundary-month residual does not match "
                        "world_interest_rate * closing_balance_before_interest"
                        if entry.is_boundary_month
                        else "nonzero residual on a non-saving-interest month"
                    ),
                }
            )

    all_pass = not violations
    metrics: dict[str, MetricValue] = {
        "checked_agent_months": MetricValue(float(len(residuals)), "count"),
        "boundary_agent_months": MetricValue(float(boundary_residuals), "count"),
        "violation_count": MetricValue(float(len(violations)), "count"),
        "max_abs_residual": MetricValue(
            max((abs(entry.residual) for entry in residuals), default=0.0), "coin"
        ),
    }
    primary = MetricValue(
        1.0 if all_pass else 0.0,
        "pass",
        metadata={"first_violation": violations[0] if violations else None},
    )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=primary,
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Leaf 2: econagent_tax_bracket_arithmetic.
# ---------------------------------------------------------------------------


def score_tax_bracket_arithmetic(
    leaf: MeasurementLeafSpec,
    *,
    dense_log: Mapping[str, Any] | None,
    n_agents: int,
    bridge: Any,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 2 by re-invoking upstream's own bracket method.

    ``bridge`` is any :class:`~aeread_families.econagent_v1.econagent_bridge.EconAgentBridge`
    instance -- ``recompute_tax`` is stateless (see its own docstring), so
    this never needs the specific episode's own (already-closed) session.

    Upstream's own ``effective_taxes = min(inventory, tax_due)`` (spec
    section 1's redistribution.py governing fact) means a recorded
    ``tax_paid`` can legitimately be *less than* the recomputed bracket
    amount when an agent's inventory could not cover it in full -- that is
    upstream's own clipping, not a bug, and is surfaced as a diagnostic
    (``clipped_agent_month_count``), never a violation. The one
    mathematically-guaranteed, falsifiable invariant this leaf enforces is
    ``tax_paid <= tax_due`` (recorded tax can never *exceed* what the
    bracket schedule allows) -- a violation there is a genuine bracket-
    arithmetic mismatch.
    """
    usable = _require_dense_log(dense_log)
    if usable is None:
        return _invalid(
            leaf,
            "no usable dense_log for this episode (bridge failure, early "
            "termination, or a dense_log missing the 'states'/'PeriodicTax' keys)",
            evidence_refs=evidence_refs,
        )
    tax_log = usable["PeriodicTax"]

    violations: list[dict[str, Any]] = []
    clipped = 0
    max_delta = 0.0
    checked = 0
    for month_index, tax_month in enumerate(tax_log, start=1):
        incomes = {agent_id: float(tax_month[agent_id]["income"]) for agent_id in _agent_ids(n_agents)}
        recomputed = bridge.recompute_tax(incomes)
        for agent_id in _agent_ids(n_agents):
            recorded_tax_paid = float(tax_month[agent_id]["tax_paid"])
            recomputed_due = float(recomputed[agent_id]["tax_due"])
            delta = recomputed_due - recorded_tax_paid
            checked += 1
            max_delta = max(max_delta, delta)
            if delta < -TAX_BRACKET_TOLERANCE:
                violations.append(
                    {
                        "month": month_index,
                        "agent_id": agent_id,
                        "recorded_tax_paid": recorded_tax_paid,
                        "recomputed_tax_due": recomputed_due,
                        "reason": "recorded tax_paid exceeds the recomputed bracket amount",
                    }
                )
            elif delta > TAX_BRACKET_TOLERANCE:
                clipped += 1

    all_pass = not violations
    metrics: dict[str, MetricValue] = {
        "checked_agent_months": MetricValue(float(checked), "count"),
        "violation_count": MetricValue(float(len(violations)), "count"),
        "clipped_agent_month_count": MetricValue(float(clipped), "count"),
        "max_tax_due_minus_paid": MetricValue(max_delta, "coin"),
    }
    primary = MetricValue(
        1.0 if all_pass else 0.0,
        "pass",
        metadata={"first_violation": violations[0] if violations else None},
    )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=primary,
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Leaf 3: econagent_macro_trajectory.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MacroTrajectory:
    """Three descriptive, per-month time series -- never blended."""

    gdp_proxy_by_month: tuple[float, ...]
    price_level_by_month: tuple[float, ...]
    unemployment_rate_by_month: tuple[float, ...]


def compute_macro_trajectory(
    dense_log: Mapping[str, Any],
    n_agents: int,
    month_actions: Sequence[Mapping[str, Sequence[float]]],
) -> MacroTrajectory:
    """Derive the three descriptive time series from an episode's dense log.

    Every value is read verbatim from ``dense_log``/``month_actions``
    (aggregate consumption, price, and job status), never recomputed from
    upstream's own GDP/unemployment bookkeeping
    (``world.nominal_gdp``/``world.unemployment``, which this module
    deliberately does not touch -- the spec's own "GDP-proxy (aggregate
    consumption)" wording names a proxy, not upstream's own GDP figure,
    precisely so this stays a simple, auditable sum over already-recorded
    per-agent consumption rather than a second, competing definition of
    GDP).

    ``month_actions`` is required for the same reason
    :func:`compute_budget_identity_residuals` needs it: a month where an
    agent's consumption action is 0 leaves
    ``dense_log["states"][...][agent_id]["consumption"]["Coin"]`` holding a
    stale prior-month value (upstream's own ``SimpleConsumption`` never
    resets it on its own NO-OP branch) -- summing that stale value into
    "aggregate consumption" would overstate the GDP-proxy on any month with
    a no-op consumer.
    """
    states = dense_log["states"]
    world = dense_log["world"]
    episode_length = len(dense_log["PeriodicTax"])
    if len(month_actions) != episode_length:
        raise ValueError(
            "month_actions is inconsistent: expected one entry per month, "
            f"got len(month_actions)={len(month_actions)} episode_length={episode_length}"
        )
    agent_ids = _agent_ids(n_agents)

    gdp_proxy: list[float] = []
    price_level: list[float] = []
    unemployment_rate: list[float] = []
    for month in range(1, episode_length + 1):
        state_month = states[month]
        actions_month = month_actions[month - 1]
        total_consumption = 0.0
        for agent_id in agent_ids:
            consumption_action = float(actions_month[agent_id][1])
            if consumption_action != 0.0:
                total_consumption += float(state_month[agent_id]["consumption"]["Coin"])
        gdp_proxy.append(total_consumption)
        price_level.append(float(world[month]["Price"]))
        unemployed = sum(
            1 for agent_id in agent_ids if state_month[agent_id]["endogenous"]["job"] == "Unemployment"
        )
        unemployment_rate.append(unemployed / len(agent_ids))
    return MacroTrajectory(
        gdp_proxy_by_month=tuple(gdp_proxy),
        price_level_by_month=tuple(price_level),
        unemployment_rate_by_month=tuple(unemployment_rate),
    )


def score_macro_trajectory(
    leaf: MeasurementLeafSpec,
    *,
    dense_log: Mapping[str, Any] | None,
    n_agents: int,
    month_actions: Sequence[Mapping[str, Sequence[float]]],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 3: descriptive time series, never a pass/fail claim.

    ``primary`` carries the episode-mean GDP-proxy (units ``"coin"``, the
    estimand's declared unit) purely so the required ``ScoreEnvelope``
    schema has one scalar to bind; the full per-month breakdown for all
    three series -- the actual diagnostic content -- lives in ``metrics``,
    each entry carrying its own unit independent of the leaf's declared
    ``"coin"`` (spec section 2: "Diagnostic only", never scored).
    """
    usable = _require_dense_log(dense_log)
    if usable is None:
        return _invalid(
            leaf,
            "no usable dense_log for this episode (bridge failure, early "
            "termination, or a dense_log missing the 'states'/'PeriodicTax' keys)",
            evidence_refs=evidence_refs,
        )
    try:
        trajectory = compute_macro_trajectory(usable, n_agents, month_actions)
    except (KeyError, ValueError, TypeError, ZeroDivisionError, IndexError) as error:
        return _invalid(
            leaf, f"malformed dense_log: {type(error).__name__}: {error}",
            evidence_refs=evidence_refs,
        )

    metrics: dict[str, MetricValue] = {}
    for month, value in enumerate(trajectory.gdp_proxy_by_month, start=1):
        metrics[f"gdp_proxy_month_{month:02d}"] = MetricValue(value, "coin")
    for month, value in enumerate(trajectory.price_level_by_month, start=1):
        metrics[f"price_level_month_{month:02d}"] = MetricValue(value, "price_ratio")
    for month, value in enumerate(trajectory.unemployment_rate_by_month, start=1):
        metrics[f"unemployment_rate_month_{month:02d}"] = MetricValue(value, "fraction")

    episode_length = len(trajectory.gdp_proxy_by_month)
    mean_gdp_proxy = (
        sum(trajectory.gdp_proxy_by_month) / episode_length if episode_length else 0.0
    )
    primary = MetricValue(mean_gdp_proxy, "coin")
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=primary,
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# FamilyScoringInput plumbing (kernel_scoring_contract_spec.md section 1).
# ---------------------------------------------------------------------------


def _terminal_fields_from_phase_instances(
    phase_instances: tuple[PhaseInstance, ...],
) -> dict[str, Any]:
    """Read this episode's terminal accounting fields off the last replayed
    phase instance's transition state.

    ``scoring_input.outcome`` (``environment.py``'s ``outcome()``) returns
    only ``termination_reason, timestep, n_agents, final_inventory_coin`` --
    final aggregates -- and never ``dense_log``/``month_actions``/
    ``world_interest_rate_by_month``/``world`` (docs/econagent_migration_plan.md's
    "Ruling applicability" section confirms this against the real
    implementation, not by assumption). All three of this family's leaves
    are declared ``input_scope="trajectory"``, so ``EconAgentV1Scorer.__call__``
    reads those fields off ``scoring_input.phase_instances`` instead, via
    this function.

    ``environment.py``'s ``step()`` is the only place that mutates
    ``dense_log``/``month_actions``/``world_interest_rate_by_month``/``world``/
    ``n_agents``, directly into its own state dict, and this family's one
    phase (``AGENT_MONTH_PHASE``) is ``mode="simultaneous"`` with exactly one
    ``step()`` call per phase instance (one month each) -- so the LAST phase
    instance's LAST (only) transition's state carries the full, cumulative,
    terminal content for the whole episode, exactly what
    ``EconAgentV1Plugin.terminal()`` itself reads off that same state.

    Ruling R3 (kernel_scoring_contract_spec.md): reading it here is safe
    because every phase boundary's post-state hash is cross-checked against
    sealed evidence during replay, so a state that diverged from the real
    run would already have failed finalization before this scorer is ever
    called -- this only reads what the verified re-execution produced, never
    re-derives it independently.

    Returns an empty ``dict`` (every field absent) when ``phase_instances``
    itself is empty or its last state is not a mapping -- the caller's own
    ``.get(..., default)`` calls turn that into the same
    ``dense_log=None``/``invalid_measurement`` path every ``score_*``
    function already takes for a missing or malformed dense log.
    """
    if not phase_instances:
        return {}
    last_state = phase_instances[-1].transitions[-1].state
    if not isinstance(last_state, Mapping):
        return {}
    world = last_state.get("world")
    world_period = world.get("period") if isinstance(world, Mapping) else None
    return {
        "dense_log": last_state.get("dense_log"),
        "n_agents": last_state.get("n_agents"),
        "world_period": world_period,
        "month_actions": last_state.get("month_actions"),
        "world_interest_rate_by_month": last_state.get("world_interest_rate_by_month"),
    }


# ---------------------------------------------------------------------------
# Scorer bundle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EconAgentV1Scorer:
    """One case's fixed set of declared leaves, plus the scorers for them.

    Mirrors ``tau3_retail``'s ``Tau3RetailScorer``: ``environment.py``'s
    ``build_scorer`` hook returns one of these. ``__call__`` (spec section 1)
    is the seam ``task.evaluation.finalize_family_execution`` calls directly
    (``plugin.build_scorer(family_case)(scoring_input,
    evidence_refs=scoring_input.evidence_refs)``); the ``score_*`` methods
    below remain exercised directly by ``tests/test_econagent_measurement.py``'s
    goldens too, exactly as before this migration.
    """

    scenario: Mapping[str, Any]
    pins: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, ...]
    # A live, stateless ``EconAgentBridge`` factory for ``__call__``'s
    # ``econagent_tax_bracket_arithmetic`` leaf (``recompute_tax`` is a pure
    # function of the pinned config, never of any particular episode -- see
    # that method's own docstring, and R2's guarantee that no LIVE EPISODE
    # is ever reachable here: this is a fresh reference computation, not a
    # second episode and not the live in-memory ``EpisodeResult``).
    # ``EconAgentV1Plugin.build_scorer`` always supplies its own
    # ``self._bridge_factory``; ``None`` only serves direct construction in
    # tests that never call ``__call__``.
    bridge_factory: Callable[[], Any] | None = None

    @property
    def budget_identity_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def tax_bracket_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    @property
    def macro_trajectory_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[2]

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        """Score one finalized episode exactly as the production finalizer
        calls it: ``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``
        (``task.evaluation.finalize_family_execution``, per
        kernel_scoring_contract_spec.md section 1).

        Returns every one of this family's three declared finalize-time
        leaves (spec section 5) -- a thin wrapper composing the three
        existing named ``score_*`` methods (this module has no
        ``score_all``); no new scoring logic is written here. All three
        leaves are declared ``input_scope="trajectory"``
        (docs/econagent_migration_plan.md's leaf table), so every one reads
        its dense-log/month-action/interest-rate input off
        ``scoring_input.phase_instances`` via
        ``_terminal_fields_from_phase_instances``, never off
        ``scoring_input.outcome`` (which never carries them -- see that
        function's own docstring).

        ``econagent_budget_identity`` is this family's primary leaf;
        ``econagent_budget_identity`` and ``econagent_tax_bracket_arithmetic``
        (the two ``rule_constraint`` leaves) gate admission;
        ``econagent_macro_trajectory`` (comparative, descriptive-only) does
        not -- see ``docs/econagent_adapter_status.md``'s "Leaf policy"
        section for why.
        """
        fields = _terminal_fields_from_phase_instances(scoring_input.phase_instances)
        dense_log = fields.get("dense_log")
        n_agents = fields.get("n_agents") or 0
        world_period = fields.get("world_period") or 0
        month_actions = fields.get("month_actions") or ()
        world_interest_rate_by_month = fields.get("world_interest_rate_by_month") or ()

        budget_identity = self.score_budget_identity(
            dense_log=dense_log,
            n_agents=n_agents,
            world_period=world_period,
            month_actions=month_actions,
            world_interest_rate_by_month=world_interest_rate_by_month,
            evidence_refs=evidence_refs,
        )
        tax_bracket = self.score_tax_bracket_arithmetic(
            dense_log=dense_log,
            n_agents=n_agents,
            bridge=self._require_bridge() if dense_log is not None else None,
            evidence_refs=evidence_refs,
        )
        macro_trajectory = self.score_macro_trajectory(
            dense_log=dense_log,
            n_agents=n_agents,
            month_actions=month_actions,
            evidence_refs=evidence_refs,
        )
        return FamilyScoreSet(
            primary_leaf_id=self.budget_identity_leaf.leaf_id,
            scores=(budget_identity, tax_bracket, macro_trajectory),
            admission_leaf_ids=(
                self.budget_identity_leaf.leaf_id,
                self.tax_bracket_leaf.leaf_id,
            ),
        )

    def _require_bridge(self) -> Any:
        if self.bridge_factory is None:
            raise ValueError(
                "EconAgentV1Scorer.bridge_factory is required to call __call__ on a "
                "usable dense_log; build_scorer is normally invoked through "
                "EconAgentV1Plugin.build_scorer, which always supplies one"
            )
        return self.bridge_factory()

    def score_budget_identity(
        self,
        *,
        dense_log: Mapping[str, Any] | None,
        n_agents: int,
        world_period: int,
        month_actions: Sequence[Mapping[str, Sequence[float]]],
        world_interest_rate_by_month: Sequence[float],
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_budget_identity(
            self.budget_identity_leaf,
            dense_log=dense_log,
            n_agents=n_agents,
            world_period=world_period,
            month_actions=month_actions,
            world_interest_rate_by_month=world_interest_rate_by_month,
            evidence_refs=evidence_refs,
        )

    def score_tax_bracket_arithmetic(
        self,
        *,
        dense_log: Mapping[str, Any] | None,
        n_agents: int,
        bridge: Any,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_tax_bracket_arithmetic(
            self.tax_bracket_leaf,
            dense_log=dense_log,
            n_agents=n_agents,
            bridge=bridge,
            evidence_refs=evidence_refs,
        )

    def score_macro_trajectory(
        self,
        *,
        dense_log: Mapping[str, Any] | None,
        n_agents: int,
        month_actions: Sequence[Mapping[str, Sequence[float]]],
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_macro_trajectory(
            self.macro_trajectory_leaf,
            dense_log=dense_log,
            n_agents=n_agents,
            month_actions=month_actions,
            evidence_refs=evidence_refs,
        )


def build_scorer(
    scenario: Mapping[str, Any],
    pins: Mapping[str, Any],
    *,
    bridge_factory: Callable[[], Any] | None = None,
) -> EconAgentV1Scorer:
    """Build the one ``EconAgentV1Scorer`` for a case's ``family_case``.

    ``bridge_factory`` -- when supplied -- mints a fresh, stateless
    ``EconAgentBridge`` for ``__call__``'s ``econagent_tax_bracket_arithmetic``
    leaf. ``EconAgentV1Plugin.build_scorer`` always passes its own
    ``self._bridge_factory``; the default of ``None`` here only serves
    direct construction in tests that never call ``__call__`` on a usable
    ``dense_log``.
    """
    return EconAgentV1Scorer(
        scenario=scenario,
        pins=pins,
        leaves=build_leaves(pins),
        bridge_factory=bridge_factory,
    )


__all__ = [
    "BUDGET_IDENTITY_ESTIMAND_ID",
    "BUDGET_IDENTITY_LEAF_ID",
    "BUDGET_IDENTITY_REFERENCE_IMPLEMENTATION_ID",
    "BUDGET_IDENTITY_SCORER_ID",
    "BudgetIdentityResidual",
    "DOMAIN_PREDICATE_ID",
    "EconAgentV1Scorer",
    "MACRO_TRAJECTORY_ESTIMAND_ID",
    "MACRO_TRAJECTORY_LEAF_ID",
    "MACRO_TRAJECTORY_REFERENCE_IMPLEMENTATION_ID",
    "MACRO_TRAJECTORY_SCORER_ID",
    "MacroTrajectory",
    "TAX_BRACKET_ESTIMAND_ID",
    "TAX_BRACKET_LEAF_ID",
    "TAX_BRACKET_REFERENCE_IMPLEMENTATION_ID",
    "TAX_BRACKET_SCORER_ID",
    "build_budget_identity_leaf",
    "build_leaves",
    "build_macro_trajectory_leaf",
    "build_scorer",
    "build_tax_bracket_leaf",
    "compute_budget_identity_residuals",
    "compute_macro_trajectory",
    "score_budget_identity",
    "score_macro_trajectory",
    "score_tax_bracket_arithmetic",
]
