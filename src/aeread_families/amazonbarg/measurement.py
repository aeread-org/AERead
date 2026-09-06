"""Measurement declarations for the amazonbarg.bilateral adapter (spec section 2).

Five leaves, ``composition_kind="leaf"`` throughout -- no composite score is
sealed by the kernel (spec section 2). Each leaf delegates its underlying
legality/profit arithmetic to upstream's own ``eval.py:Metrics`` (imported
in-process through :mod:`aeread_families.amazonbarg.upstream_shim`, never
reimplemented -- adapter rule 2):

* **``amazonbarg_deal_authenticity`` (delegated, rule_constraint).** Upstream's
  own ``wrongAction`` verdict, verbatim: did the recorded deal reproduce a
  genuine prior same-type offer from the other party and match the buyer's
  declared need? Sealed ``status="ok"`` even when it fails (spec section 4
  golden 4): the malformed/inauthentic action itself is the evidence.
* **``amazonbarg_zopa_membership`` (AERead-owned, rule_constraint).** Is the
  realized deal price (delegated ``D``) inside the case's genuine
  ``[derived.cost, derived.budget]`` -- never upstream's own, sometimes
  internally widened, ``B``/``C`` (see ``score_zopa_membership``'s own
  docstring: upstream silently widens its internal budget/cost whenever the
  raw bargaining room is under $1, a private detail of its own legality
  check, not a genuine relaxation of this case's bracket)? Reports a typed
  ``invalid_measurement`` with a ``"degenerate_no_zopa: ..."`` reason (never
  a computed pass/fail) when ``cost > budget`` -- see this module's
  ``_measurement_gate`` docstring for why the kernel's own two-value
  ``ScoreEnvelope.status`` enum has no third
  "degenerate" state and how this module works around that (also logged to
  the ledger).
* **``amazonbarg_deal_lower_bound`` / ``amazonbarg_deal_upper_bound``
  (AERead-owned, objective_reference).** ``S_min = cost`` /
  ``S_max = budget``; each leaf's ``primary`` is the realized deal price
  itself, with its own single bound recorded in ``reference_values`` --
  never one combined ``outcome_support_normalized`` leaf (not a legal
  ``reference_kind`` in the real contract; see the ledger entry already
  filed for this family documenting that taxonomy/code gap). The *derived*
  ``support_score = (V - S_min) / (S_max - S_min)`` belongs to a later
  parity/analysis layer, never sealed here as a third kernel score.
* **``amazonbarg_bargained_ratio`` (AERead-owned scorer, delegated
  arithmetic, comparative).** The tested seat's own ``buyer_bargained_ratio``
  / ``seller_bargained_ratio`` against the fixed scripted counterpart.
  Ruling R12 (kernel_scoring_contract_spec.md): this is a genuinely
  per-seat primary, declared ``seat_scope="subject_seat"`` in
  ``environment.py``'s ``family_manifest()`` (no ``subject_reduction`` --
  this family's own docs already say the ratio is one side's, never
  blended); ``AmazonbargScorer.__call__`` resolves *which* seat from
  ``FamilyScoringInput.seat_context.subject_seats`` via
  :func:`score_bargained_ratio_for_subject_seats`, which alone decides
  ``tested_seat`` and then defers to :func:`score_bargained_ratio` for the
  actual ratio arithmetic (never reimplemented there). Both seats' ratios
  are always recorded together in the returned envelope's
  ``utility_by_seat`` / ``capture_by_seat`` (never only the tested seat's
  number, so a poor ratio for one seat is never silently hidden -- spec
  section 4 golden 1's "comparative ratios ~=0.49/0.51"), and the kernel
  itself enforces ``primary == utility_by_seat[tested_seat]`` for every
  ``status="ok"`` envelope (``task/evaluation.py``'s
  ``_enforce_subject_seat_primaries``).

**Measurement validity gate** (spec section 2): whenever upstream's
delegated ``Metrics`` output cannot support a deal-price claim -- upstream
flagged ``wrongAction=1`` (spec golden 4), no ZOPA exists (``cost >
budget``, golden 5), or simply no deal ever closed -- the zopa/bound/ratio
leaves are sealed ``ScoreEnvelope(status="invalid_measurement", primary=None,
validity=ValidityReport(status="invalid", reasons=[...]))``, never a
computed zero. ``amazonbarg_deal_authenticity`` alone is exempt: it is
computed from ``wrongAction`` directly and is *always* sealed ``status="ok"``
(spec: "the malformed action is the evidence being checked").

One documented interpretation of underspecified spec text (both flagged
here, mirroring ``tau3_retail``'s own "one documented deviation" docstring
convention, rather than silently guessing): the kernel's real
``ObjectiveScopeSpec.direction`` only accepts ``"maximize"``/``"minimize"``
(never ``"none"``), and ``MeasurementLeafSpec`` requires it to match the
estimand's own ``direction`` exactly. The two bound leaves' own claim ("a
bounded support position, not an attainable optimum") has no seat-neutral
notion of "higher/lower is better" -- a higher deal price is better for the
seller and worse for the buyer. ``"maximize"`` is recorded on both bound
leaves as a required structural placeholder only, never as a normative
claim that a higher deal price is "better" (also logged to the ledger:
``objective_reference`` cannot express a genuinely directionless bound).

**Leaf policy and the finalizer seam** (kernel_scoring_contract_spec.md,
migration milestone 2 of 3, extended by ruling R12): ``environment.py``'s
``family_manifest()`` declares all five leaves ``scope="finalize_time"``,
``amazonbarg_bargained_ratio_leaf`` as primary and it alone gating
admission (see ``docs/amazonbarg_adapter_status.md``'s "Leaf policy"
section for why), and ``amazonbarg_bargained_ratio_leaf`` alone
``seat_scope="subject_seat"``. ``AmazonbargScorer.__call__`` is the seam
``task.evaluation.finalize_family_execution`` calls; it returns every
declared leaf, the four seat-neutral diagnostics via their own named
methods and ``amazonbarg_bargained_ratio`` via
:func:`score_bargained_ratio_for_subject_seats`, which reads
``FamilyScoringInput.seat_context.subject_seats`` (ruling R12) and never
fabricates a seat: zero, several, or an unrecognized subject seat is
reported ``invalid_measurement`` with a named reason
(``REASON_NO_SUBJECT_SEAT`` / ``REASON_AMBIGUOUS_SUBJECT_SEAT`` /
``REASON_UNKNOWN_SUBJECT_SEAT``), never guessed.
"""
from __future__ import annotations

import hashlib
import json
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

from . import upstream_shim
from .cases import UPSTREAM_COMMIT, UPSTREAM_REPO

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "amazonbarg_bilateral_base_v1"
DOMAIN_VERSION = "1.0.0"

DEAL_AUTHENTICITY_ESTIMAND_ID = "amazonbarg_deal_authenticity"
DEAL_AUTHENTICITY_LEAF_ID = "amazonbarg_deal_authenticity_leaf"
DEAL_AUTHENTICITY_REFERENCE_ID = "amazonbarg_upstream_wrongaction_reference"
DEAL_AUTHENTICITY_SCORER_ID = "amazonbarg_deal_authenticity_scorer"

ZOPA_MEMBERSHIP_ESTIMAND_ID = "amazonbarg_zopa_membership"
ZOPA_MEMBERSHIP_LEAF_ID = "amazonbarg_zopa_membership_leaf"
ZOPA_MEMBERSHIP_REFERENCE_ID = "amazonbarg_zopa_bracket_reference"
ZOPA_MEMBERSHIP_SCORER_ID = "amazonbarg_zopa_membership_scorer"

DEAL_LOWER_BOUND_ESTIMAND_ID = "amazonbarg_deal_lower_bound"
DEAL_LOWER_BOUND_LEAF_ID = "amazonbarg_deal_lower_bound_leaf"
DEAL_LOWER_BOUND_REFERENCE_ID = "amazonbarg_cost_floor_reference"
DEAL_LOWER_BOUND_SCORER_ID = "amazonbarg_deal_lower_bound_scorer"

DEAL_UPPER_BOUND_ESTIMAND_ID = "amazonbarg_deal_upper_bound"
DEAL_UPPER_BOUND_LEAF_ID = "amazonbarg_deal_upper_bound_leaf"
DEAL_UPPER_BOUND_REFERENCE_ID = "amazonbarg_budget_ceiling_reference"
DEAL_UPPER_BOUND_SCORER_ID = "amazonbarg_deal_upper_bound_scorer"

BARGAINED_RATIO_ESTIMAND_ID = "amazonbarg_bargained_ratio"
BARGAINED_RATIO_LEAF_ID = "amazonbarg_bargained_ratio_leaf"
BARGAINED_RATIO_REFERENCE_ID = "amazonbarg_scripted_counterpart_reference"
BARGAINED_RATIO_SCORER_ID = "amazonbarg_bargained_ratio_scorer"

# The fixed opponent this milestone's goldens and (later) the pilot harness
# hold constant while scoring `amazonbarg_bargained_ratio` -- an
# AERead-authored fixture, never upstream code (spec section 3: upstream's
# own CLI-mode dummyAgent classes are a constant [REJECT] no-op and cannot
# produce deal/no-deal variety). The actual fixture module is milestone 3's
# own deliverable (spec: "milestone 3 is expected to cover the scripted
# counterpart harness"); this milestone only pins the identifier + version
# the estimand's validity_domain records today, so it is already stable
# once that fixture lands.
SCRIPTED_COUNTERPART_POLICY_ID = "amazonbarg_scripted_counterpart"
SCRIPTED_COUNTERPART_POLICY_VERSION = "0.1.0"

# Typed, machine-checkable reason-code prefixes for the measurement validity
# gate (see this module's docstring and `_measurement_gate`). A caller can
# distinguish "no evidence at all" / "malformed or unauthenticated action"
# / "no ZOPA exists" / "no deal ever closed" from these prefixes without
# parsing free-text.
REASON_NO_EVIDENCE = "no_evidence"
REASON_ACTION_ERROR = "action_error"
REASON_DEGENERATE_NO_ZOPA = "degenerate_no_zopa"
REASON_NO_DEAL = "no_deal"
# Ruling R12 (kernel_scoring_contract_spec.md): which seat (buyer or
# seller) a RunPlan is testing now reaches this scorer via
# ``FamilyScoringInput.seat_context.subject_seats`` --
# ``AmazonbargScorer.__call__`` reads it and resolves it through
# :func:`score_bargained_ratio_for_subject_seats` before ever calling
# :func:`score_bargained_ratio`'s own arithmetic. These three reasons
# replace the pre-R12 ``REASON_TESTED_SEAT_UNKNOWN`` (retired: no path
# reaches "no signal at all" any more, only these three, more specific,
# named failures of the seat context itself):
REASON_NO_SUBJECT_SEAT = "no_subject_seat"
REASON_AMBIGUOUS_SUBJECT_SEAT = "ambiguous_subject_seat"
REASON_UNKNOWN_SUBJECT_SEAT = "unknown_subject_seat"


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail/measurement.py``'s own ``_implementation`` helper:
    hashing a sibling adapter source file so the pin changes exactly when
    that code changes.
    """
    return ImplementationRef(
        implementation_id=implementation_id,
        version=IMPLEMENTATION_VERSION,
        content_sha256=_file_sha256(filename),
    )


def _rule_source_sha256(rule: str) -> str:
    """Pin a *structured description* of a delegated upstream rule.

    Unlike ``tau3_retail``'s gold-database hash (which pins DATA that
    already flows through the case payload's own pins), these five leaves'
    "reference" is a delegated *rule* (upstream's ``wrongAction``
    semantics; the ``B``/``C``/``D`` bracket arithmetic) rather than a
    data file. ``build_leaves``/``build_scorer`` are deliberately
    upstream-root-free and filesystem-free, mirroring ``tau3_retail``'s own
    ``build_db_state_leaf(pins)`` (never touches ``upstream_root``), so
    this hashes a stable, versioned JSON description of the rule (repo +
    pinned commit + qualified name) instead of re-reading upstream source
    bytes from disk.
    """
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "upstream_repo": UPSTREAM_REPO,
                "upstream_commit": UPSTREAM_COMMIT,
                "rule": rule,
            }
        )
    ).hexdigest()


def _validity_domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id=DOMAIN_ID,
        domain_version=DOMAIN_VERSION,
        schema_ref="amazonbarg_bilateral_base_v1/case_payload",
        predicate=_implementation("amazonbarg_base_domain_predicate", "environment.py"),
    )


# ---------------------------------------------------------------------------
# Leaf 1 -- amazonbarg_deal_authenticity (delegated, rule_constraint).
# ---------------------------------------------------------------------------


def build_deal_authenticity_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=DEAL_AUTHENTICITY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        # kernel_scoring_contract_spec.md migration: upstream's `wrongAction`
        # verdict is computed by walking the FULL recorded transcript
        # (`eval.py:Metrics.evaluate`), not derivable from a terminal
        # snapshot alone -- `AmazonbargPlugin.outcome()` deliberately never
        # carries `history` (see `docs/amazonbarg_migration_plan.md`'s "Flag
        # for the implementation milestone"). Relabelled from
        # `terminal_state` (no `reference_kind` restriction blocks this;
        # `constraint_satisfaction` has no `_REFERENCE_SCOPE` entry in
        # measurement.py, unlike the two bound leaves below).
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=DEAL_AUTHENTICITY_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="pass",
        source_sha256=_rule_source_sha256("eval.py:Metrics.evaluate:wrongAction"),
        implementation=_implementation(
            "amazonbarg_upstream_metrics_bridge", "upstream_shim.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=DEAL_AUTHENTICITY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(DEAL_AUTHENTICITY_SCORER_ID, "measurement.py"),
    )


# ---------------------------------------------------------------------------
# Leaf 2 -- amazonbarg_zopa_membership (AERead-owned, rule_constraint).
# ---------------------------------------------------------------------------


def build_zopa_membership_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=ZOPA_MEMBERSHIP_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        # See build_deal_authenticity_leaf's comment: the realized deal
        # price `D` this leaf compares against `[cost, budget]` is delegated
        # from the full recorded transcript, not the terminal snapshot.
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=ZOPA_MEMBERSHIP_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="pass",
        source_sha256=_rule_source_sha256(
            "eval.py:Metrics.evaluate:B,C,D (budget/cost/deal price) "
            "+ AERead zopa-membership comparison"
        ),
        implementation=_implementation(
            "amazonbarg_upstream_metrics_bridge", "upstream_shim.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=ZOPA_MEMBERSHIP_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(ZOPA_MEMBERSHIP_SCORER_ID, "measurement.py"),
    )


# ---------------------------------------------------------------------------
# Leaves 3-4 -- the two bound leaves (AERead-owned, objective_reference).
# ---------------------------------------------------------------------------


def _bound_objective_scope(estimand: EstimandSpec) -> ObjectiveScopeSpec:
    return ObjectiveScopeSpec(
        objective_id=estimand.estimand_id,
        objective_version=estimand.estimand_version,
        direction=estimand.direction,
        units=estimand.units,
        feasible_set=(
            "the realized deal price, bracketed by the seller's private cost "
            "and the buyer's declared budget"
        ),
        information_set=(
            "ex-post recorded transcript only; no hidden-information policy "
            "optimum is claimed (spec section 2)"
        ),
        horizon="one pinned bilateral bargaining session (<= 6 rounds)",
        environment_condition="pinned budget_ratio=0.8, pinned max_turns=6",
        opponent_condition="the counterpart seat recorded in the same episode",
        validity_domain=estimand.validity_domain,
    )


def build_deal_lower_bound_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=DEAL_LOWER_BOUND_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        # kernel_scoring_contract_spec.md migration: unlike the three leaves
        # above, this stays "terminal_state" -- NOT a claim that the
        # realized deal price is knowable without the recorded transcript
        # (it is not; `AmazonbargScorer.__call__` still delegates to the
        # full replayed ``history`` for every leaf, see that method's
        # docstring). It is forced: `measurement.py`'s `_REFERENCE_SCOPE`
        # restricts `reference_kind="outcome_support_min"` to
        # `{"terminal_state", "distribution"}` -- "trajectory" is rejected
        # at `ReferenceSpec.__post_init__`. `tau3_retail`'s already-migrated
        # `db_state` leaf (`reference_kind="terminal_state_equivalence"`,
        # scope-restricted to exactly `{"terminal_state"}`) is the same
        # shape: a `__call__` that reads `phase_instances` for a
        # `terminal_state`-labelled leaf because `outcome()` does not carry
        # what it needs. See `docs/amazonbarg_adapter_status.md`'s "Leaf
        # policy" section for the full account of this mismatch.
        input_scope="terminal_state",
        # See module docstring: a required structural placeholder, not a
        # claim that a higher deal price is "better" (there is no
        # seat-neutral direction for this estimand).
        direction="maximize",
        units="usd",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=DEAL_LOWER_BOUND_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="outcome_support_min",
        input_scope="terminal_state",
        units="usd",
        source_sha256=_rule_source_sha256("eval.py:Metrics.evaluate:C (seller cost floor)"),
        implementation=_implementation(
            "amazonbarg_upstream_metrics_bridge", "upstream_shim.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="objective_reference",
        evaluation_class="deterministic",
        reference=reference,
        objective_scope=_bound_objective_scope(estimand),
    )
    return MeasurementLeafSpec(
        leaf_id=DEAL_LOWER_BOUND_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(DEAL_LOWER_BOUND_SCORER_ID, "measurement.py"),
    )


def build_deal_upper_bound_leaf() -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=DEAL_UPPER_BOUND_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        # Same forced "terminal_state" as build_deal_lower_bound_leaf's own
        # comment (reference_kind="outcome_support_max" carries the
        # identical _REFERENCE_SCOPE restriction).
        input_scope="terminal_state",
        direction="maximize",  # placeholder -- see module docstring.
        units="usd",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=DEAL_UPPER_BOUND_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="outcome_support_max",
        input_scope="terminal_state",
        units="usd",
        source_sha256=_rule_source_sha256("eval.py:Metrics.evaluate:B (buyer budget ceiling)"),
        implementation=_implementation(
            "amazonbarg_upstream_metrics_bridge", "upstream_shim.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="objective_reference",
        evaluation_class="deterministic",
        reference=reference,
        objective_scope=_bound_objective_scope(estimand),
    )
    return MeasurementLeafSpec(
        leaf_id=DEAL_UPPER_BOUND_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(DEAL_UPPER_BOUND_SCORER_ID, "measurement.py"),
    )


# ---------------------------------------------------------------------------
# Leaf 5 -- amazonbarg_bargained_ratio (AERead-owned scorer, comparative).
# ---------------------------------------------------------------------------


def build_bargained_ratio_leaf() -> MeasurementLeafSpec:
    """The one ``amazonbarg_bargained_ratio`` leaf declaration.

    ``AmazonbargPlugin.build_scorer`` (the kernel's required hook) takes
    only ``family_case`` -- it has no way to know in advance which seat a
    RunPlan will test -- so this leaf's own identity/``validity_domain``
    cannot vary per seat and stays seat-neutral here. The fixed
    scripted-counterpart identity (spec: "opponent identity recorded in the
    estimand's validity_domain") is recorded here as
    ``SCRIPTED_COUNTERPART_POLICY_ID``/``_VERSION``. *Which* seat is
    tested, and which seat's ratio becomes this leaf's ``primary``, is
    resolved at finalize time from ``FamilyScoringInput.seat_context``
    (ruling R12) by :func:`score_bargained_ratio_for_subject_seats` --
    this leaf's own *policy* (declared separately, in
    ``environment.py``'s ``family_manifest()``) is
    ``seat_scope="subject_seat"``, even though this declaration itself
    carries no seat.
    """
    domain = ValidityDomainSpec(
        domain_id=f"amazonbarg_bargained_ratio_domain_{SCRIPTED_COUNTERPART_POLICY_ID}",
        domain_version=SCRIPTED_COUNTERPART_POLICY_VERSION,
        schema_ref="amazonbarg_bilateral_base_v1/bargained_ratio_estimand",
        predicate=_implementation("amazonbarg_base_domain_predicate", "environment.py"),
    )
    estimand = EstimandSpec(
        estimand_id=BARGAINED_RATIO_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        # See build_deal_authenticity_leaf's comment: buyer/seller bargained
        # ratios are delegated from the full recorded transcript
        # (`eval.py:Metrics.evaluate`), never the terminal snapshot alone.
        # `reference_kind="head_to_head"` has no `_REFERENCE_SCOPE` entry,
        # so nothing blocks this relabelling the way it blocks the two
        # bound leaves above.
        input_scope="trajectory",
        direction="maximize",
        units="ratio",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=BARGAINED_RATIO_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="head_to_head",
        input_scope="trajectory",
        units="ratio",
        source_sha256=_rule_source_sha256(
            "eval.py:Metrics.evaluate:buyer_bargained_ratio,seller_bargained_ratio"
        ),
        implementation=_implementation(
            "amazonbarg_upstream_metrics_bridge", "upstream_shim.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=BARGAINED_RATIO_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(BARGAINED_RATIO_SCORER_ID, "measurement.py"),
    )


def build_leaves(family_case: Mapping[str, Any] | None = None) -> tuple[MeasurementLeafSpec, ...]:
    """The five measurement leaves, always declared together (spec section 2).

    ``family_case`` is accepted (mirroring ``tau3_retail.measurement
    .build_leaves(task, pins)``'s own signature shape) but unused: unlike
    ``tau3_retail``, none of amazonbarg's five leaves are conditionally
    declared -- every leaf is declared for every case, every leaf's
    ``evaluation_class`` is ``"deterministic"`` (scripted trajectories, no
    sampled trials), and none of them read ``family_case`` at declaration
    time (only the *scorers* below read a case's ``derived`` fields).
    """
    del family_case
    return (
        build_deal_authenticity_leaf(),
        build_zopa_membership_leaf(),
        build_deal_lower_bound_leaf(),
        build_deal_upper_bound_leaf(),
        build_bargained_ratio_leaf(),
    )


# ---------------------------------------------------------------------------
# Delegation: build the `line` dict upstream's own eval.py:Metrics expects,
# and call it. Never reimplements Metrics' own legality/profit arithmetic
# (adapter rule 2).
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """Detach the scheduler's frozen MappingProxyType/tuple containers.

    Mirrors ``tau3_retail/parity.py``'s own ``_plain`` helper: upstream's
    ``Metrics`` indexes into ``history`` with plain ``dict``/``list``
    operations, so anything read off a (possibly frozen) episode state must
    be converted to an ordinary JSON-native structure first.
    """
    return json.loads(canonical_json_bytes(value))


def build_metrics_line(
    family_case: Mapping[str, Any], *, history: Any, row: int = -1
) -> dict[str, Any]:
    """Build the ``line`` dict upstream's own ``eval.py:Metrics`` expects.

    Mirrors ``session.py``'s own
    ``Agent2AgentSession.agents_talk_with_action`` return-dict shape
    exactly: ``inv`` is ``Inventory._catalog()`` --
    ``{codename: (title, description, price, cost)}`` -- and ``need`` is
    ``shopping_list()``'s own per-product need list
    (``{"codename", "title", "quantity", "budget"}``). Built entirely from
    the case's own already-delegated ``derived`` fields (never
    re-derived, never touching ``upstream_root``), so this function -- like
    ``build_leaves`` -- stays filesystem-free.
    """
    derived = family_case["derived"]
    codename = derived["codename"]
    return {
        "index": 0,
        "row": row,
        "inv": {
            codename: [
                derived["title"],
                derived["description"],
                derived["price"],
                derived["cost"],
            ]
        },
        "need": [
            {
                "codename": codename,
                "title": derived["title"],
                "quantity": 1,
                "budget": derived["budget"],
            }
        ],
        "history": _plain(history),
    }


def compute_upstream_metrics(
    *,
    upstream_root: Path,
    family_case: Mapping[str, Any],
    history: Any,
    row: int = -1,
) -> dict[str, Any]:
    """Delegate to the pinned ``eval.py:Metrics`` on one recorded transcript.

    Returns upstream's own ``.output()`` dict verbatim (``turns``,
    ``closeADeal``, ``wrongAction``, ``costGTbudget``, and -- only when a
    deal actually closed -- ``B``/``C``/``D``,
    ``buyer_bargained_profit``/``ratio``,
    ``seller_bargained_profit``/``ratio``, ``buyer_offer_num``,
    ``seller_offer_num``). Never reimplements any of upstream's own
    legality/profit arithmetic (adapter rule 2).
    """
    metrics_cls = upstream_shim.import_metrics(upstream_root)
    line = build_metrics_line(family_case, history=history, row=row)
    return metrics_cls(line, row=row).output()


# ---------------------------------------------------------------------------
# Measurement validity gate (see module docstring).
# ---------------------------------------------------------------------------


def _measurement_gate(
    *, family_case: Mapping[str, Any], metrics_output: Mapping[str, Any]
) -> tuple[str, ...] | None:
    """Return ``None`` if a real deal price can be reported, else typed reasons.

    Used by every leaf except ``amazonbarg_deal_authenticity`` (which is
    always computable from ``wrongAction`` alone, deal or no deal). A
    non-empty tuple means the caller must seal
    ``ScoreEnvelope(status="invalid_measurement", primary=None, ...)`` with
    these reasons -- never a computed zero (spec section 2). More than one
    reason can legitimately be true at once (e.g. golden 5: both
    ``degenerate_no_zopa`` and ``no_deal``); nothing here treats that as an
    error.

    **Kernel limitation, logged to the ledger:** the real
    ``ScoreEnvelope.status`` enum is exactly ``{"ok", "invalid_measurement"}``
    -- there is no distinct "degenerate"/"not_applicable" status a
    ``rule_constraint``/``objective_reference`` leaf can seal for "this
    claim has no ZOPA to evaluate" as opposed to "this claim's evidence was
    malformed". Both are represented here as ``invalid_measurement`` with a
    different, stable reason-code *prefix* (``degenerate_no_zopa:`` vs.
    ``action_error:``/``no_deal:``) rather than a different top-level
    status -- see :func:`reasons_include`.
    """
    reasons: list[str] = []
    wrong_action = metrics_output.get("wrongAction")
    if wrong_action is None:
        return (
            f"{REASON_NO_EVIDENCE}: upstream Metrics produced no wrongAction "
            "verdict (empty recorded history)",
        )
    if wrong_action == 1:
        reasons.append(
            f"{REASON_ACTION_ERROR}: upstream Metrics flagged wrongAction=1 "
            "(malformed or unauthenticated action); no deal price could be evaluated"
        )
    derived = family_case["derived"]
    if derived["interest"] == "conflicting":
        reasons.append(
            f"{REASON_DEGENERATE_NO_ZOPA}: cost {derived['cost']} > budget "
            f"{derived['budget']}; no zone of possible agreement exists"
        )
    if metrics_output.get("closeADeal") != 1:
        reasons.append(
            f"{REASON_NO_DEAL}: episode did not close a deal; there is no "
            "deal price to evaluate"
        )
    return tuple(reasons) if reasons else None


def reasons_include(validity: ValidityReport, prefix: str) -> bool:
    """Whether any of ``validity.reasons`` carries the given reason-code prefix."""
    return any(reason.startswith(f"{prefix}:") for reason in validity.reasons)


def _invalid(leaf: MeasurementLeafSpec, reasons: tuple[str, ...], evidence_refs: tuple[str, ...]) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics={},
        reference_values={},
        validity=ValidityReport("invalid", reasons),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Scorers.
# ---------------------------------------------------------------------------


def score_deal_authenticity(
    leaf: MeasurementLeafSpec,
    *,
    metrics_output: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 1 from upstream's own delegated ``wrongAction`` verdict.

    Always ``status="ok"`` -- deal or no deal, authentic or not -- since
    "the malformed action is the evidence being checked" (spec section 2,
    golden 4). The one exception is an episode with zero recorded turns,
    for which upstream's own ``Metrics`` never even runs its evaluation
    loop and reports no ``wrongAction`` verdict at all; that has no
    evidence to seal a claim from and is reported ``invalid_measurement``.
    """
    wrong_action = metrics_output.get("wrongAction")
    if wrong_action is None:
        return _invalid(
            leaf,
            (
                f"{REASON_NO_EVIDENCE}: upstream Metrics produced no wrongAction "
                "verdict (empty recorded history)",
            ),
            evidence_refs,
        )
    metrics: dict[str, MetricValue] = {
        "wrong_action": MetricValue(float(wrong_action), "count"),
        "turns": MetricValue(float(metrics_output.get("turns", 0)), "count"),
        "close_a_deal": MetricValue(float(metrics_output.get("closeADeal", 0)), "pass"),
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(0.0 if wrong_action else 1.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_zopa_membership(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    metrics_output: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 2: is the delegated deal price ``D`` inside the case's
    genuine ``[cost, budget]``?

    ``D`` is read verbatim from upstream's own delegated ``Metrics``
    output -- never recomputed. The ZOPA bracket itself, however, is the
    case's own genuine ``derived.cost``/``derived.budget`` -- *not*
    upstream's own delegated ``C``/``B``. Upstream's own
    ``eval.py:Metrics.evaluate`` silently widens ``B``/``C`` whenever the
    raw bargaining room (``budget - cost``) is under $1 in absolute value
    (``0 <= room < 1`` forces ``budget = cost + 1`` before recording
    ``self.B``; the mirror branch for ``-1 < room < 0`` forces
    ``cost = budget - 1`` before recording ``self.C``) -- a private detail
    of its own internal legality check, not a genuine relaxation of this
    case's buyer budget / seller cost. Trusting that widened value here
    would let a deal above the buyer's real budget (or below the seller's
    real cost) pass as "inside the ZOPA" on any narrow-room case (codex
    review finding 2, reproduced on ``home-kitchen_20``: ``derived.budget
    =47.992``, ``derived.cost=47.99``, delegated ``B=48.99`` -- a deal at
    ``$48.50`` is above the real budget but inside upstream's widened
    bracket). Upstream's own (possibly widened) ``B``/``C`` are still
    recorded verbatim in ``metrics`` for audit, never used for the
    ``in_zopa`` comparison itself.
    """
    gate_reasons = _measurement_gate(family_case=family_case, metrics_output=metrics_output)
    if gate_reasons is not None:
        return _invalid(leaf, gate_reasons, evidence_refs)
    derived = family_case["derived"]
    lower, upper, deal_price = (
        float(derived["cost"]),
        float(derived["budget"]),
        float(metrics_output["D"]),
    )
    in_zopa = lower <= deal_price <= upper
    metrics = {
        "genuine_cost": MetricValue(lower, "usd", metadata={"source": "family_case.derived.cost"}),
        "genuine_budget": MetricValue(
            upper, "usd", metadata={"source": "family_case.derived.budget"}
        ),
        "delegated_budget": MetricValue(
            float(metrics_output["B"]), "usd", metadata={"upstream_field": "B"}
        ),
        "delegated_cost": MetricValue(
            float(metrics_output["C"]), "usd", metadata={"upstream_field": "C"}
        ),
        "deal_price": MetricValue(deal_price, "usd", metadata={"upstream_field": "D"}),
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0 if in_zopa else 0.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def _score_bound(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    metrics_output: Mapping[str, Any],
    bound_field: str,
    bound_reference_id: str,
    reference_kind: str,
    evidence_refs: tuple[str, ...],
) -> ScoreEnvelope:
    gate_reasons = _measurement_gate(family_case=family_case, metrics_output=metrics_output)
    if gate_reasons is not None:
        return _invalid(leaf, gate_reasons, evidence_refs)
    deal_price = float(metrics_output["D"])
    bound_value = float(family_case["derived"][bound_field])
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(deal_price, "usd"),
        metrics={"deal_price": MetricValue(deal_price, "usd", metadata={"upstream_field": "D"})},
        reference_values={
            bound_reference_id: MetricValue(
                bound_value, "usd", metadata={"reference_kind": reference_kind}
            )
        },
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_deal_lower_bound(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    metrics_output: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 3: the realized deal price against ``S_min = cost``."""
    return _score_bound(
        leaf,
        family_case=family_case,
        metrics_output=metrics_output,
        bound_field="cost",
        bound_reference_id="s_min",
        reference_kind="outcome_support_min",
        evidence_refs=evidence_refs,
    )


def score_deal_upper_bound(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    metrics_output: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 4: the realized deal price against ``S_max = budget``."""
    return _score_bound(
        leaf,
        family_case=family_case,
        metrics_output=metrics_output,
        bound_field="budget",
        bound_reference_id="s_max",
        reference_kind="outcome_support_max",
        evidence_refs=evidence_refs,
    )


def score_bargained_ratio(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    metrics_output: Mapping[str, Any],
    tested_seat: str,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 5: ``tested_seat``'s own bargained ratio.

    ``utility_by_seat``/``capture_by_seat`` always carry *both* seats'
    ratios (spec section 4 golden 1: "comparative ratios ~=0.49/0.51") --
    only ``primary`` is seat-selected. Diagnostics (``turns``,
    ``buyer_offer_num``, ``seller_offer_num``, raw ``wrongAction``) live in
    ``metrics``, never ``primary`` (spec section 2).

    ``tested_seat`` is a required ``"buyer"``/``"seller"`` string: every
    caller of this function already knows which seat it tested --
    ``AmazonbargScorer.__call__`` resolves it from
    ``FamilyScoringInput.seat_context.subject_seats`` (ruling R12) via
    :func:`score_bargained_ratio_for_subject_seats` before ever calling
    here; ``replay.py``'s ``score_replayed_episode`` and every test in this
    suite already pass an explicit ``"buyer"``/``"seller"`` string. Before
    ruling R12, no ``FamilyScoringInput`` could carry which seat a RunPlan
    was testing, so this parameter was widened to ``str | None`` and
    ``AmazonbargScorer.__call__`` always called this with
    ``tested_seat=None``, sealing ``invalid_measurement`` with a since
    -retired ``REASON_TESTED_SEAT_UNKNOWN``; ruling R12 makes the seat
    reachable, so that widening and its reason are retired here in favour
    of :func:`score_bargained_ratio_for_subject_seats`'s three named seat
    -selection reasons.
    """
    if tested_seat not in ("buyer", "seller"):
        raise ValueError(f"tested_seat must be 'buyer' or 'seller', got {tested_seat!r}")
    gate_reasons = _measurement_gate(family_case=family_case, metrics_output=metrics_output)
    if gate_reasons:
        return _invalid(leaf, gate_reasons, evidence_refs)
    buyer_ratio = float(metrics_output["buyer_bargained_ratio"])
    seller_ratio = float(metrics_output["seller_bargained_ratio"])
    primary_ratio = buyer_ratio if tested_seat == "buyer" else seller_ratio
    metrics = {
        "turns": MetricValue(float(metrics_output.get("turns", 0)), "count"),
        "buyer_offer_num": MetricValue(float(metrics_output.get("buyer_offer_num", 0)), "count"),
        "seller_offer_num": MetricValue(float(metrics_output.get("seller_offer_num", 0)), "count"),
        "wrong_action": MetricValue(float(metrics_output.get("wrongAction", 0)), "count"),
    }
    utility_by_seat = {
        "buyer": MetricValue(buyer_ratio, "ratio"),
        "seller": MetricValue(seller_ratio, "ratio"),
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(primary_ratio, "ratio", metadata={"tested_seat": tested_seat}),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
        utility_by_seat=utility_by_seat,
        capture_by_seat=utility_by_seat,
    )


def score_bargained_ratio_for_subject_seats(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    metrics_output: Mapping[str, Any],
    subject_seats: tuple[str, ...],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Ruling R12: resolve ``tested_seat`` from seat context, then defer to
    :func:`score_bargained_ratio` alone for the actual ratio arithmetic
    (never reimplemented here).

    ``subject_seats`` is ``scoring_input.seat_context.subject_seats`` --
    the RunPlan's own record of which seat(s) are the tested subjects
    (kernel_scoring_contract_spec.md ruling R12). Exactly one subject seat
    that is one of this family's own seat ids (``"buyer"``/``"seller"``)
    resolves ``tested_seat`` and is scored normally; every other shape is
    reported ``invalid_measurement`` with a named reason, never a guessed
    side:

    * zero subject seats -> ``REASON_NO_SUBJECT_SEAT``
    * two or more subject seats (this leaf declares no
      ``subject_reduction`` -- the ratio is one side's, never blended) ->
      ``REASON_AMBIGUOUS_SUBJECT_SEAT``
    * a subject seat that is not ``"buyer"``/``"seller"`` ->
      ``REASON_UNKNOWN_SUBJECT_SEAT``
    """
    if not subject_seats:
        return _invalid(
            leaf,
            (
                f"{REASON_NO_SUBJECT_SEAT}: seat_context.subject_seats is "
                "empty; there is no seat to score amazonbarg_bargained_ratio for",
            ),
            evidence_refs,
        )
    if len(subject_seats) > 1:
        return _invalid(
            leaf,
            (
                f"{REASON_AMBIGUOUS_SUBJECT_SEAT}: seat_context.subject_seats "
                f"names {len(subject_seats)} seats {sorted(subject_seats)!r}, but "
                "amazonbarg_bargained_ratio declares no subject_reduction -- "
                "the ratio is one side's own, never blended across seats",
            ),
            evidence_refs,
        )
    tested_seat = subject_seats[0]
    if tested_seat not in ("buyer", "seller"):
        return _invalid(
            leaf,
            (
                f"{REASON_UNKNOWN_SUBJECT_SEAT}: seat_context names subject "
                f"seat {tested_seat!r}, which is not one of this family's own "
                "seat ids ('buyer', 'seller')",
            ),
            evidence_refs,
        )
    return score_bargained_ratio(
        leaf,
        family_case=family_case,
        metrics_output=metrics_output,
        tested_seat=tested_seat,
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# The one scorer object per case (spec: build_scorer returns this).
# ---------------------------------------------------------------------------


def _history_from_phase_instances(phase_instances: tuple[PhaseInstance, ...]) -> list[Any]:
    """Read the cumulative ``history`` off the last replayed phase state.

    ``scoring_input.outcome`` never carries ``history``
    (``environment.py``'s ``outcome()`` omits it -- see that module's own
    ``terminal()``/``outcome()`` split), so ``AmazonbargScorer.__call__``
    reads it from ``scoring_input.phase_instances`` instead, exactly the way
    ``govsim``'s already-migrated ``_round_trace_from_phase_instances``
    reads ``round_trace``.

    ``environment.py``'s ``step()`` is the only place that appends to
    ``history``, directly into its own state dict, and never resets it, so
    by the LAST phase instance's LAST transition, that state carries the
    full, cumulative transcript for the whole episode -- exactly what
    ``AmazonbargPlugin.terminal()`` itself reads off that same state
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
class AmazonbargScorer:
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
    ``tests/test_amazonbarg_measurement.py``'s goldens today, mirroring
    ``Tau3RetailScorer``'s identical convention for its own non-primary leaf.
    """

    family_case: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, ...]
    # Mirrors ``Tau3RetailScorer.bridge``: ``build_scorer(family_case)`` (the
    # kernel's required, single-argument hook) cannot smuggle in the pinned
    # upstream checkout any other way, so ``AmazonbargPlugin.build_scorer``
    # passes its own ``self.upstream_root`` through here. ``None`` only when
    # a caller builds a scorer directly without one (every existing test
    # that never calls ``__call__``); ``__call__`` raises if it is missing.
    upstream_root: Path | None = None

    @property
    def deal_authenticity_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def zopa_membership_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    @property
    def deal_lower_bound_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[2]

    @property
    def deal_upper_bound_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[3]

    @property
    def bargained_ratio_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[4]

    def score_deal_authenticity(
        self, *, metrics_output: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_deal_authenticity(
            self.deal_authenticity_leaf, metrics_output=metrics_output, evidence_refs=evidence_refs
        )

    def score_zopa_membership(
        self, *, metrics_output: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_zopa_membership(
            self.zopa_membership_leaf,
            family_case=self.family_case,
            metrics_output=metrics_output,
            evidence_refs=evidence_refs,
        )

    def score_deal_lower_bound(
        self, *, metrics_output: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_deal_lower_bound(
            self.deal_lower_bound_leaf,
            family_case=self.family_case,
            metrics_output=metrics_output,
            evidence_refs=evidence_refs,
        )

    def score_deal_upper_bound(
        self, *, metrics_output: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_deal_upper_bound(
            self.deal_upper_bound_leaf,
            family_case=self.family_case,
            metrics_output=metrics_output,
            evidence_refs=evidence_refs,
        )

    def score_bargained_ratio(
        self,
        *,
        metrics_output: Mapping[str, Any],
        tested_seat: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_bargained_ratio(
            self.bargained_ratio_leaf,
            family_case=self.family_case,
            metrics_output=metrics_output,
            tested_seat=tested_seat,
            evidence_refs=evidence_refs,
        )

    def score_bargained_ratio_for_subject_seats(
        self,
        *,
        metrics_output: Mapping[str, Any],
        subject_seats: tuple[str, ...],
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_bargained_ratio_for_subject_seats(
            self.bargained_ratio_leaf,
            family_case=self.family_case,
            metrics_output=metrics_output,
            subject_seats=subject_seats,
            evidence_refs=evidence_refs,
        )

    def _score_diagnostics(
        self, *, metrics_output: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> dict[str, ScoreEnvelope]:
        """The four seat-neutral diagnostic leaves, shared by ``score_all``
        (``replay.py``'s seam, which already knows ``tested_seat``) and
        ``__call__`` (the finalizer seam, which resolves it from
        ``FamilyScoringInput.seat_context`` instead) -- never duplicated
        between them."""
        return {
            self.deal_authenticity_leaf.leaf_id: self.score_deal_authenticity(
                metrics_output=metrics_output, evidence_refs=evidence_refs
            ),
            self.zopa_membership_leaf.leaf_id: self.score_zopa_membership(
                metrics_output=metrics_output, evidence_refs=evidence_refs
            ),
            self.deal_lower_bound_leaf.leaf_id: self.score_deal_lower_bound(
                metrics_output=metrics_output, evidence_refs=evidence_refs
            ),
            self.deal_upper_bound_leaf.leaf_id: self.score_deal_upper_bound(
                metrics_output=metrics_output, evidence_refs=evidence_refs
            ),
        }

    def score_all(
        self,
        *,
        metrics_output: Mapping[str, Any],
        tested_seat: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> dict[str, ScoreEnvelope]:
        """All five leaves' envelopes, keyed by ``leaf_id``, in one call.

        ``replay.py``'s ``score_replayed_episode`` -- which already knows
        which seat it tested -- is this method's one remaining caller;
        ``__call__`` below resolves ``tested_seat`` from seat context
        instead and no longer goes through this method (see its own
        docstring).
        """
        return {
            **self._score_diagnostics(metrics_output=metrics_output, evidence_refs=evidence_refs),
            self.bargained_ratio_leaf.leaf_id: self.score_bargained_ratio(
                metrics_output=metrics_output, tested_seat=tested_seat, evidence_refs=evidence_refs
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

        Returns every one of this family's five declared finalize-time
        leaves (spec section 5): the four seat-neutral diagnostics via
        ``_score_diagnostics`` and ``amazonbarg_bargained_ratio`` via
        :meth:`score_bargained_ratio_for_subject_seats`, which resolves
        ``tested_seat`` from ``scoring_input.seat_context.subject_seats``
        (ruling R12, kernel_scoring_contract_spec.md) and defers to
        ``score_bargained_ratio`` alone for the actual arithmetic -- no new
        scoring logic is written here. ``scoring_input.outcome`` never
        carries ``history`` (``environment.py``'s ``outcome()`` omits it),
        so the full transcript every leaf's delegated ``eval.py:Metrics``
        call needs is read off ``scoring_input.phase_instances`` via
        :func:`_history_from_phase_instances` -- including for the two
        bound leaves, which stay declared ``input_scope="terminal_state"``
        (forced by ``measurement.py``'s ``_REFERENCE_SCOPE`` restriction on
        ``outcome_support_min``/``outcome_support_max``; see those leaves'
        own build functions for the full account, and
        ``docs/amazonbarg_adapter_status.md``'s "Leaf policy" section).

        Before ruling R12, no ``tested_seat`` signal was reachable from a
        ``FamilyScoringInput`` at all, so this always called ``score_all``
        with ``tested_seat=None`` and ``amazonbarg_bargained_ratio_leaf`` --
        this family's declared primary and sole admission leaf -- was
        sealed ``invalid_measurement`` with a since-retired
        ``REASON_TESTED_SEAT_UNKNOWN`` through this exact seam, for every
        episode, clean or not. Ruling R12 makes the seat reachable; see
        ``docs/amazonbarg_adapter_status.md``'s "Leaf policy" section for
        the resolution and the first included receipt.
        """
        if self.upstream_root is None:
            raise ValueError(
                "amazonbarg scoring requires the pinned upstream checkout "
                "(AmazonbargScorer.upstream_root is None)"
            )
        history = _history_from_phase_instances(scoring_input.phase_instances)
        metrics_output = compute_upstream_metrics(
            upstream_root=self.upstream_root,
            family_case=self.family_case,
            history=history,
        )
        scored = {
            **self._score_diagnostics(metrics_output=metrics_output, evidence_refs=evidence_refs),
            self.bargained_ratio_leaf.leaf_id: self.score_bargained_ratio_for_subject_seats(
                metrics_output=metrics_output,
                subject_seats=scoring_input.seat_context.subject_seats,
                evidence_refs=evidence_refs,
            ),
        }
        return FamilyScoreSet(
            primary_leaf_id=self.bargained_ratio_leaf.leaf_id,
            scores=tuple(scored.values()),
            admission_leaf_ids=(self.bargained_ratio_leaf.leaf_id,),
        )


def build_scorer(
    family_case: Mapping[str, Any], *, upstream_root: Path | None = None
) -> AmazonbargScorer:
    """Build the one ``AmazonbargScorer`` for a case's ``family_case``."""
    return AmazonbargScorer(
        family_case=family_case,
        leaves=build_leaves(family_case),
        upstream_root=upstream_root,
    )


__all__ = [
    "AmazonbargScorer",
    "BARGAINED_RATIO_ESTIMAND_ID",
    "BARGAINED_RATIO_LEAF_ID",
    "DEAL_AUTHENTICITY_ESTIMAND_ID",
    "DEAL_AUTHENTICITY_LEAF_ID",
    "DEAL_LOWER_BOUND_ESTIMAND_ID",
    "DEAL_LOWER_BOUND_LEAF_ID",
    "DEAL_UPPER_BOUND_ESTIMAND_ID",
    "DEAL_UPPER_BOUND_LEAF_ID",
    "REASON_ACTION_ERROR",
    "REASON_AMBIGUOUS_SUBJECT_SEAT",
    "REASON_DEGENERATE_NO_ZOPA",
    "REASON_NO_DEAL",
    "REASON_NO_EVIDENCE",
    "REASON_NO_SUBJECT_SEAT",
    "REASON_UNKNOWN_SUBJECT_SEAT",
    "SCRIPTED_COUNTERPART_POLICY_ID",
    "SCRIPTED_COUNTERPART_POLICY_VERSION",
    "ZOPA_MEMBERSHIP_ESTIMAND_ID",
    "ZOPA_MEMBERSHIP_LEAF_ID",
    "build_bargained_ratio_leaf",
    "build_deal_authenticity_leaf",
    "build_deal_lower_bound_leaf",
    "build_deal_upper_bound_leaf",
    "build_leaves",
    "build_metrics_line",
    "build_scorer",
    "build_zopa_membership_leaf",
    "compute_upstream_metrics",
    "reasons_include",
    "score_bargained_ratio",
    "score_bargained_ratio_for_subject_seats",
    "score_deal_authenticity",
    "score_deal_lower_bound",
    "score_deal_upper_bound",
    "score_zopa_membership",
]
