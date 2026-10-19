"""Measurement declarations for the agenticpay.bilateral adapter (spec section 2).

Declares the four kernel-sanctioned leaves and scores each independently --
never blended into one number:

* **``agenticpay_deal_reached`` (``rule_constraint``, deterministic).** Did
  the negotiation terminate ``agreed`` vs. ``timeout``? Independent of
  quality; read straight off ``EpisodeResult.terminal["reason"]``.
* **``agenticpay_contract_legality`` (``rule_constraint``, deterministic).**
  Declared only for contract-mode (realistic-split) cases: per attempted
  contract submission, did it satisfy this case's declared
  ``continuous_bounds``/``discrete_options``? Scored from
  ``environment.py``'s own ``round_trace`` (upstream's own recorded
  before/after ``buyer_contract``/``seller_contract``), never by
  re-deriving upstream's ``_validate_contract``.
* **``agenticpay_buyer_surplus_share`` / ``agenticpay_seller_surplus_share``
  (``objective_reference``, deterministic).** A ZOPA support-bound share in
  ``[0, 1]``: ``(buyer_max_price - agreed_price) / Z`` /
  ``(agreed_price - seller_min_price) / Z`` for basic (price-only) cases,
  ``buyer_utility / z_max`` / ``seller_utility / z_max`` for contract-mode
  cases (upstream's own already-computed MAUT utilities, never
  recalculated here). Reported ``invalid_measurement`` with reason
  ``"denominator_degenerate"`` whenever the ZOPA denominator is not
  strictly positive -- never a fabricated share (spec section 4 golden 5) --
  and, for basic (price-only) cases, with reason
  ``"agreed_price_out_of_declared_range"`` whenever ``agreed_price`` falls
  outside ``[seller_min_price, buyer_max_price]`` (the same ``valid_range``
  condition upstream's own ``_calculate_global_score`` requires before
  treating a deal as a success -- second-review Codex finding 2).

``GlobalScore``/``BuyerScore``/``SellerScore`` are **not** declared as a
``MeasurementLeafSpec`` here: per spec section 2, upstream's weighted
composite has no declared normative weights/decision-problem justification
on record, so it is carried forward only as a labeled compatibility
artifact -- already done, verbatim, by ``environment.py``'s
``terminal()``/``outcome()`` (Milestone 1), exactly as ``tau3_upstream_reward``
is recorded. Nothing in this module recomputes or approximates it.

Two documented deviations from the spec's literal prose, both forced by the
kernel's real, stricter ``VerifierSpec``/``ReferenceSpec`` enums (see
``aeread.shared_runner.measurement``) rather than by any change of meaning
-- the same class of deviation ``tau3_retail.measurement`` already
documents for its own "transcript" -> "trajectory" case:

* Section 2 writes ``input_scope="action"`` for the contract-legality leaf.
  The kernel only accepts ``{"answer", "terminal_state", "trajectory",
  "distribution"}``; this module uses ``"trajectory"`` -- the ordered
  per-round sequence of contract submissions the leaf actually evaluates.
* Section 2 writes ``reference_kind="outcome_support_normalized"`` for both
  surplus-share leaves. The kernel only accepts, for ``objective_reference``
  verifiers, ``{"exact_optimum", "objective_lower_bound",
  "objective_upper_bound", "comparison_baseline", "outcome_support_min",
  "outcome_support_max"}``. Both leaves' true support bounds are the fixed
  constants ``S_min=0``/``S_max=1``; since a ``VerifierSpec`` carries
  exactly one ``ReferenceSpec``, ``"outcome_support_max"`` is declared as
  the pinned bound and ``S_min=0`` is recorded as a fixed
  ``reference_values`` entry on every ``score_*_surplus_share`` result,
  never as a second ``ReferenceSpec``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
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
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import FamilyScoringInput
from aeread.shared_runner.task.scheduler import PhaseInstance

from .cases import TERMINATION_REASONS

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "agenticpay_bilateral_terminal_domain"
DOMAIN_VERSION = "1.0.0"

# Named (not inline-literal) implementation-pin component ids (migration
# milestone 3 of 3): `environment.py`'s `family_manifest()` must declare
# these as `scoring.reference_provider_ids` so `resolve_run_plan` admits a
# plan that pins them and `EvaluationReceipt`'s own
# `_validate_and_freeze_plan_pins` accepts the sealed receipt -- otherwise
# this family could never finalize through a real `RunPlan` at all, since
# `resolve_run_plan`'s `_check_pins` rejects any pin whose component id is
# not `scoring`-declared. Naming them here (rather than leaving them as
# string literals inline in each leaf builder below) is what lets
# `environment.py` reference the identical ids without risking drift.
TERMINAL_DOMAIN_PREDICATE_ID = "agenticpay_bilateral_terminal_domain_predicate"
DEAL_REACHED_RULE_ID = "agenticpay_bilateral_deal_reached_rule"
ZOPA_SUPPORT_BOUND_ID = "agenticpay_bilateral_zopa_support_bound"
CONTRACT_LEGALITY_RULE_ID = "agenticpay_bilateral_contract_legality_rule"

DEAL_REACHED_ESTIMAND_ID = "agenticpay_deal_reached"
DEAL_REACHED_LEAF_ID = "agenticpay_deal_reached_leaf"
DEAL_REACHED_REFERENCE_ID = "agenticpay_deal_reached_rule"
DEAL_REACHED_SCORER_ID = "agenticpay_deal_reached_scorer"

CONTRACT_LEGALITY_ESTIMAND_ID = "agenticpay_contract_legality"
CONTRACT_LEGALITY_LEAF_ID = "agenticpay_contract_legality_leaf"
CONTRACT_LEGALITY_REFERENCE_ID = "agenticpay_contract_legality_rule"
CONTRACT_LEGALITY_SCORER_ID = "agenticpay_contract_legality_scorer"

BUYER_SURPLUS_ESTIMAND_ID = "agenticpay_buyer_surplus_share"
BUYER_SURPLUS_LEAF_ID = "agenticpay_buyer_surplus_share_leaf"
BUYER_SURPLUS_REFERENCE_ID = "agenticpay_buyer_surplus_share_bound"
BUYER_SURPLUS_SCORER_ID = "agenticpay_buyer_surplus_share_scorer"

SELLER_SURPLUS_ESTIMAND_ID = "agenticpay_seller_surplus_share"
SELLER_SURPLUS_LEAF_ID = "agenticpay_seller_surplus_share_leaf"
SELLER_SURPLUS_REFERENCE_ID = "agenticpay_seller_surplus_share_bound"
SELLER_SURPLUS_SCORER_ID = "agenticpay_seller_surplus_share_scorer"

# Ruling R12 (kernel_scoring_contract_spec.md): the ONE leaf `family_manifest()`
# actually declares and `AgenticpayBilateralScorer.__call__` actually publishes
# for "surplus share" (spec section 5, migration milestone 2 of 3). The two
# ids above (`BUYER_SURPLUS_*`/`SELLER_SURPLUS_*`) hard-code an answer to
# "which seat is the tested subject" that the family manifest itself never
# declared -- both roles are independently `testable` (`environment.py`'s
# `family_manifest`), so a real evaluation cell may test either seat against
# a scripted opponent. Kept below as two always-computable role-specific
# leaves for backward compatibility with `replay.py`'s own diagnostic
# `ReplayScoreResult` (spec's ownership boundary: this migration touches the
# scoring-contract seam only, never `replay.py`'s pre-existing, independent
# reporting shape) and with every pure-fixture/golden test that already
# exercises their formula directly; neither is declared in the manifest any
# more, and `build_leaves()` (this case's declared-leaf inventory, below)
# still returns only these two -- `SURPLUS_SHARE_LEAF_ID` is built and scored
# separately, on demand, by `AgenticpayBilateralScorer.surplus_share_leaf`/
# `score_surplus_share`.
SURPLUS_SHARE_ESTIMAND_ID = "agenticpay_surplus_share"
SURPLUS_SHARE_LEAF_ID = "agenticpay_surplus_share_leaf"
SURPLUS_SHARE_REFERENCE_ID = "agenticpay_surplus_share_bound"
SURPLUS_SHARE_SCORER_ID = "agenticpay_surplus_share_scorer"

# A necessary (not sufficient) condition for upstream's own `_extract_price`
# to have returned None: every one of its regex patterns (labeled, triple-
# hash, and every fallback) requires at least one digit character. A
# message with zero digits therefore could not possibly have produced a
# price -- proven directly from upstream's own published patterns (spec's
# governing facts), never reimplemented here as a price parser of our own.
PRICE_DIGIT_PATTERN = re.compile(r"\d")


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail.measurement``'s identical convention: ``filename``
    is the actual adapter module that performs the referenced step, so the
    pin changes exactly when that code changes.
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
        schema_ref="agenticpay_bilateral_v1/terminal_payload",
        predicate=_implementation(TERMINAL_DOMAIN_PREDICATE_ID, "environment.py"),
    )


def is_contract_mode(family_case: Mapping[str, Any]) -> bool:
    """Mirrors upstream's own ``use_contract_mode = bool(contract_config)`` rule.

    Never a re-derivation of upstream's scoring/legality algorithms -- this
    is the exact truthiness test ``Task1BasicPriceNegotiation.__init__``
    itself applies to ``environment_info.get("contract_config")``.
    """
    environment_info = family_case["constructor_kwargs"].get("environment_info") or {}
    return bool(environment_info.get("contract_config"))


# ---------------------------------------------------------------------------
# Leaf 1 -- agenticpay_deal_reached.
# ---------------------------------------------------------------------------


def build_deal_reached_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Declared for every case: did the episode terminate ``agreed``?"""
    del family_case
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=DEAL_REACHED_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    source_sha256 = hashlib.sha256(
        canonical_json_bytes(list(TERMINATION_REASONS))
    ).hexdigest()
    reference = ReferenceSpec(
        reference_id=DEAL_REACHED_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="terminal_state",
        units="pass",
        source_sha256=source_sha256,
        implementation=_implementation(DEAL_REACHED_RULE_ID, "environment.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=DEAL_REACHED_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(DEAL_REACHED_SCORER_ID, "measurement.py"),
    )


def score_deal_reached(
    leaf: MeasurementLeafSpec,
    *,
    terminal: Mapping[str, Any],
    diagnostics: Mapping[str, MetricValue] | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 1: 1.0 iff ``terminal["reason"] == "agreed"``, else 0.0.

    Always deterministic and always computable once the episode has
    terminated -- independent of price/contract quality, per spec section 2.
    """
    reached = terminal["reason"] == "agreed"
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(
            1.0 if reached else 0.0,
            "pass",
            metadata={"termination_reason": terminal["reason"]},
        ),
        metrics=dict(diagnostics or {}),
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Diagnostics -- descriptive only, never part of a leaf's primary measurement.
# ---------------------------------------------------------------------------


def _could_not_have_parsed_a_price(message: str) -> bool:
    """See ``PRICE_DIGIT_PATTERN``: a digit-free message could not have
    produced a price under any of upstream's own extraction patterns."""
    return PRICE_DIGIT_PATTERN.search(message) is None


def build_action_diagnostics(round_trace: Sequence[Mapping[str, Any]]) -> dict[str, MetricValue]:
    """Typed evidence that a seat's message this round could not have moved
    upstream's own tracked price (spec section 3 / section 4 golden 4).

    Upstream's own trace is otherwise indistinguishable from "the seat chose
    not to move this round" -- left unflagged, a downstream analysis would
    conflate a parser miss with a deliberate negotiating tactic. Recorded
    here as descriptive-only ``metrics`` (never folded into any leaf's
    ``primary``), attached to leaf 1's ``ScoreEnvelope`` by
    ``AgenticpayBilateralScorer.score_deal_reached``.
    """
    metrics: dict[str, MetricValue] = {}
    count = 0
    for entry in round_trace:
        for seat in ("buyer", "seller"):
            if entry.get(f"{seat}_contract_attempted"):
                continue
            message = entry.get(f"{seat}_action") or ""
            if message.strip() and _could_not_have_parsed_a_price(message):
                metrics[f"round_{entry['round']}_{seat}_parse_failure"] = MetricValue(
                    1.0, "flag"
                )
                count += 1
    metrics["parse_failure_count"] = MetricValue(float(count), "count")
    return metrics


# ---------------------------------------------------------------------------
# Leaf 2 -- agenticpay_contract_legality (contract-mode cases only).
# ---------------------------------------------------------------------------


def build_contract_legality_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec | None:
    """Declared only when ``is_contract_mode`` is true, else ``None``.

    A contract-mode offer's declared bounds live in this case's own
    ``environment_info.contract_config``'s ``continuous_bounds``/
    ``discrete_options`` -- pinned here as the reference's ``source_sha256``
    so two cases with different declared bounds never collide.
    """
    if not is_contract_mode(family_case):
        return None
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=CONTRACT_LEGALITY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        # Spec section 2 literally writes input_scope="action"; see this
        # module's docstring for why "trajectory" is used instead.
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    contract_config = family_case["constructor_kwargs"]["environment_info"]["contract_config"]
    declared_bounds = {
        key: contract_config[key]
        for key in ("continuous_bounds", "discrete_options")
        if key in contract_config
    }
    source_sha256 = hashlib.sha256(canonical_json_bytes(declared_bounds)).hexdigest()
    reference = ReferenceSpec(
        reference_id=CONTRACT_LEGALITY_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="pass",
        source_sha256=source_sha256,
        implementation=_implementation(CONTRACT_LEGALITY_RULE_ID, "environment.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=CONTRACT_LEGALITY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(CONTRACT_LEGALITY_SCORER_ID, "measurement.py"),
    )


def score_contract_legality(
    leaf: MeasurementLeafSpec,
    *,
    round_trace: Sequence[Mapping[str, Any]],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 2 from ``environment.py``'s own recorded ``round_trace``.

    For every round in which a seat attempted a contract submission
    (``f"{seat}_contract_attempted"``), "accepted" is upstream's own
    ``f"{seat}_contract_valid"`` verdict for that round -- upstream's own
    ``_validate_contract`` result, called again by the bridge driver on the
    exact same raw text (never re-derived here; see
    ``agenticpay_bridge_driver.py``'s ``_overlay_contract_validity``).
    Deliberately *not* "did ``f'{seat}_contract'`` change from
    immediately-before to immediately-after": upstream assigns every
    validated contract to state unconditionally, even when it exactly
    repeats the previous value, so a repeated, already-accepted legal
    contract leaves that value unchanged too -- indistinguishable from a
    rejection by a before/after comparison alone (spec section 4 golden 3,
    second-review Codex finding 4). ``primary`` is 1.0 iff no attempted
    submission was rejected anywhere in the trajectory (vacuously 1.0 if
    nothing was ever attempted); every attempted submission's own pass/fail
    is retained in ``metrics`` so a downstream analysis can see exactly
    which round failed, per the taxonomy's "declared aggregation rule"
    requirement.
    """
    metrics: dict[str, MetricValue] = {}
    any_rejected = False
    for entry in round_trace:
        for seat in ("buyer", "seller"):
            if not entry.get(f"{seat}_contract_attempted"):
                continue
            accepted = bool(entry.get(f"{seat}_contract_valid"))
            metrics[f"round_{entry['round']}_{seat}_contract_legal"] = MetricValue(
                1.0 if accepted else 0.0, "pass"
            )
            if not accepted:
                any_rejected = True
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(0.0 if any_rejected else 1.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Leaves 3/4 -- agenticpay_buyer_surplus_share / agenticpay_seller_surplus_share.
# ---------------------------------------------------------------------------


def _surplus_share_reference_source_sha256(family_case: Mapping[str, Any]) -> str:
    constructor_kwargs = family_case["constructor_kwargs"]
    if is_contract_mode(family_case):
        payload: dict[str, Any] = {
            "contract_config": constructor_kwargs["environment_info"]["contract_config"]
        }
    else:
        payload = {
            "buyer_max_price": constructor_kwargs.get("buyer_max_price"),
            "seller_min_price": constructor_kwargs.get("seller_min_price"),
        }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _build_surplus_share_leaf(
    family_case: Mapping[str, Any],
    *,
    estimand_id: str,
    leaf_id: str,
    reference_id: str,
    scorer_id: str,
) -> MeasurementLeafSpec:
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=estimand_id,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="maximize",
        units="share_of_zopa",
        validity_domain=domain,
    )
    max_rounds = int(family_case["constructor_kwargs"]["max_rounds"])
    reference = ReferenceSpec(
        reference_id=reference_id,
        reference_version=REFERENCE_VERSION,
        # Spec section 2 literally writes "outcome_support_normalized"; see
        # this module's docstring for why "outcome_support_max" is declared
        # instead (S_min=0 is recorded as a fixed reference_values entry by
        # the scorer, not as a second ReferenceSpec).
        reference_kind="outcome_support_max",
        input_scope="terminal_state",
        units="share_of_zopa",
        source_sha256=_surplus_share_reference_source_sha256(family_case),
        implementation=_implementation(ZOPA_SUPPORT_BOUND_ID, "environment.py"),
    )
    objective_scope = ObjectiveScopeSpec(
        objective_id=estimand_id,
        objective_version=ESTIMAND_VERSION,
        direction="maximize",
        units="share_of_zopa",
        feasible_set=(
            "either side's offer sequence within [seller_min_price, buyer_max_price]"
        ),
        information_set="own reservation price only; counterpart's is private",
        horizon=f"{max_rounds} rounds (max_rounds)",
        environment_condition="the pinned agenticpay.bilateral case's constructor/reset kwargs",
        opponent_condition="the paired scripted-counterpart policy declared for this case",
        validity_domain=domain,
    )
    verifier = VerifierSpec(
        verifier_family="objective_reference",
        evaluation_class="deterministic",
        reference=reference,
        objective_scope=objective_scope,
    )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(scorer_id, "measurement.py"),
    )


def build_buyer_surplus_share_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    return _build_surplus_share_leaf(
        family_case,
        estimand_id=BUYER_SURPLUS_ESTIMAND_ID,
        leaf_id=BUYER_SURPLUS_LEAF_ID,
        reference_id=BUYER_SURPLUS_REFERENCE_ID,
        scorer_id=BUYER_SURPLUS_SCORER_ID,
    )


def build_seller_surplus_share_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    return _build_surplus_share_leaf(
        family_case,
        estimand_id=SELLER_SURPLUS_ESTIMAND_ID,
        leaf_id=SELLER_SURPLUS_LEAF_ID,
        reference_id=SELLER_SURPLUS_REFERENCE_ID,
        scorer_id=SELLER_SURPLUS_SCORER_ID,
    )


def build_surplus_share_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """The one leaf ``family_manifest()`` declares ``seat_scope="subject_seat"``.

    Built by the same generic ``_build_surplus_share_leaf`` helper as the two
    role-specific leaves above -- same estimand shape, units, bounds,
    ``objective_scope`` -- only the declared ids differ (ruling R12).
    """
    return _build_surplus_share_leaf(
        family_case,
        estimand_id=SURPLUS_SHARE_ESTIMAND_ID,
        leaf_id=SURPLUS_SHARE_LEAF_ID,
        reference_id=SURPLUS_SHARE_REFERENCE_ID,
        scorer_id=SURPLUS_SHARE_SCORER_ID,
    )


def _invalid_surplus_share(
    leaf: MeasurementLeafSpec, reason: str, evidence_refs: tuple[str, ...]
) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics={},
        reference_values={},
        validity=ValidityReport("invalid", reasons=(reason,)),
        evidence_refs=evidence_refs,
    )


def _score_surplus_share(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    terminal: Mapping[str, Any],
    side: str,
    evidence_refs: tuple[str, ...],
) -> ScoreEnvelope:
    if is_contract_mode(family_case):
        z_max = terminal.get("z_max")
        if z_max is None or z_max <= 0:
            return _invalid_surplus_share(leaf, "denominator_degenerate", evidence_refs)
        utility = terminal.get(f"{side}_utility")
        if utility is None:
            return _invalid_surplus_share(
                leaf, "contract_utility_not_available", evidence_refs
            )
        share = utility / z_max
    else:
        constructor_kwargs = family_case["constructor_kwargs"]
        buyer_max_price = constructor_kwargs.get("buyer_max_price")
        seller_min_price = constructor_kwargs.get("seller_min_price")
        if buyer_max_price is None or seller_min_price is None:
            return _invalid_surplus_share(
                leaf, "reservation_prices_not_declared", evidence_refs
            )
        zopa = buyer_max_price - seller_min_price
        if zopa <= 0:
            return _invalid_surplus_share(leaf, "denominator_degenerate", evidence_refs)
        agreed_price = terminal.get("agreed_price")
        if agreed_price is None:
            return _invalid_surplus_share(leaf, "no_agreement_reached", evidence_refs)
        # Upstream's own `_calculate_global_score` additionally requires
        # `seller_min_price <= final_price <= buyer_max_price` before it will
        # treat a deal as a success (`valid_range`, Task1_basic_price_negotiation.py);
        # an agreement outside that declared range is the same `valid_range=False`
        # branch upstream itself falls back to a failure penalty for, and this leaf
        # must never publish a share outside its own declared [0, 1] support for it
        # (second-review Codex finding 2).
        if not (seller_min_price <= agreed_price <= buyer_max_price):
            return _invalid_surplus_share(
                leaf, "agreed_price_out_of_declared_range", evidence_refs
            )
        share = (
            (buyer_max_price - agreed_price) / zopa
            if side == "buyer"
            else (agreed_price - seller_min_price) / zopa
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(float(share), "share_of_zopa"),
        metrics={},
        reference_values={
            "outcome_support_min": MetricValue(0.0, "share_of_zopa"),
            "outcome_support_max": MetricValue(1.0, "share_of_zopa"),
        },
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_buyer_surplus_share(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    terminal: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 3: ``(buyer_max_price - agreed_price) / Z`` (basic) or
    ``buyer_utility / z_max`` (contract mode); ``invalid_measurement`` with
    reason ``"denominator_degenerate"`` whenever ``Z``/``z_max`` is not
    strictly positive (spec section 4 golden 5) -- never a fabricated share.
    """
    return _score_surplus_share(
        leaf,
        family_case=family_case,
        terminal=terminal,
        side="buyer",
        evidence_refs=evidence_refs,
    )


def score_seller_surplus_share(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    terminal: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 4: the seller-side mirror of ``score_buyer_surplus_share``."""
    return _score_surplus_share(
        leaf,
        family_case=family_case,
        terminal=terminal,
        side="seller",
        evidence_refs=evidence_refs,
    )


_SURPLUS_SHARE_SEATS = ("buyer", "seller")


def score_surplus_share(
    leaf: MeasurementLeafSpec,
    *,
    family_case: Mapping[str, Any],
    terminal: Mapping[str, Any],
    subject_seat: str,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score the merged, seat-scoped surplus-share leaf (ruling R12).

    Delegates both sides' shares to ``_score_surplus_share`` -- the exact
    same, unchanged formula/degeneracy rules ``score_buyer_surplus_share``/
    ``score_seller_surplus_share`` already use -- so no new scoring logic is
    written here, only the seat-scope wrapping ruling R12 requires:

    * ``primary`` is ``subject_seat``'s OWN value, never a blend of both
      sides (spec's problem statement: "one value exists for each seat, and
      a summed or blended two-seat number is not the estimand"). If
      ``subject_seat``'s own share cannot be computed (a degenerate ZOPA, no
      agreement, an out-of-range agreed price, or -- contract mode only --
      that side's utility missing from ``terminal``), this envelope is
      ``invalid_measurement`` with that same reason, never a fabricated
      value.
    * ``utility_by_seat`` carries the subject's own value (required by the
      kernel's ``primary == utility_by_seat[subject_seat]`` enforcement) AND
      the opponent's own value, computed the identical way -- "every seat's
      own value is carried, not only the subject's". If the OPPONENT's own
      share cannot itself be computed while the subject's can (only
      reachable via the contract-mode ``contract_utility_not_available``
      branch, since every other degeneracy reason is symmetric across both
      sides for one case), the opponent's entry is simply absent from
      ``utility_by_seat`` -- never a fabricated value standing in for it.

    Ruling R12 rule 3 ("opponent identity comes from
    ``seat_context.profile_by_seat[opponent_seat]``") does not apply here:
    unlike negarena's bridge-settled ``score_seat_outcome`` (which needs an
    upstream ``opponent_policy_id`` to call ``NegarenaBridge.settle``),
    neither side's surplus share depends in any way on WHICH policy sits in
    the opponent's seat -- ``_score_surplus_share`` reads only
    ``family_case``/``terminal``. No profile-id-to-policy-id mapping is
    declared, and ``AgenticpayBilateralScorer.__call__`` correctly never
    reads ``profile_by_seat`` for this leaf.
    """
    if subject_seat not in _SURPLUS_SHARE_SEATS:
        raise ValueError(
            f"agenticpay.bilateral has no seat named {subject_seat!r}; "
            f"expected one of {_SURPLUS_SHARE_SEATS}"
        )
    opponent_seat = "seller" if subject_seat == "buyer" else "buyer"
    subject_envelope = _score_surplus_share(
        leaf,
        family_case=family_case,
        terminal=terminal,
        side=subject_seat,
        evidence_refs=evidence_refs,
    )
    if subject_envelope.status != "ok":
        return subject_envelope
    opponent_envelope = _score_surplus_share(
        leaf,
        family_case=family_case,
        terminal=terminal,
        side=opponent_seat,
        evidence_refs=evidence_refs,
    )
    utility_by_seat = {subject_seat: subject_envelope.primary}
    if opponent_envelope.status == "ok":
        utility_by_seat[opponent_seat] = opponent_envelope.primary
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=subject_envelope.primary,
        metrics=subject_envelope.metrics,
        reference_values=subject_envelope.reference_values,
        validity=subject_envelope.validity,
        evidence_refs=evidence_refs,
        utility_by_seat=utility_by_seat,
    )


def build_leaves(family_case: Mapping[str, Any]) -> tuple[MeasurementLeafSpec, ...]:
    """This case's declared leaves: always 3, 4 when contract mode applies.

    Exactly ``(deal_reached, buyer_surplus_share, seller_surplus_share)`` for
    a basic (price-only) case; ``(..., contract_legality)`` appended for a
    contract-mode (realistic-split) case. There is no fifth, composed leaf:
    ``GlobalScore``/``BuyerScore``/``SellerScore`` are carried in
    ``terminal``/``outcome`` verbatim, never sealed here (spec section 2).

    Unchanged by ruling R12's seat-scope migration (spec section 5, milestone
    2 of 3): this stays the pre-migration, per-role inventory
    ``AgenticpayBilateralScorer``'s legacy ``buyer_surplus_share_leaf``/
    ``seller_surplus_share_leaf``/``score_buyer_surplus_share``/
    ``score_seller_surplus_share`` (kept for ``replay.py``'s own diagnostic
    use, see ``SURPLUS_SHARE_LEAF_ID``'s docstring above) index into. The one
    leaf ``family_manifest()`` actually declares in its place --
    ``SURPLUS_SHARE_LEAF_ID``, ``seat_scope="subject_seat"`` -- is built by
    ``build_surplus_share_leaf``/``AgenticpayBilateralScorer.surplus_share_leaf``
    instead, never appended here.
    """
    leaves: list[MeasurementLeafSpec] = [
        build_deal_reached_leaf(family_case),
        build_buyer_surplus_share_leaf(family_case),
        build_seller_surplus_share_leaf(family_case),
    ]
    contract_legality_leaf = build_contract_legality_leaf(family_case)
    if contract_legality_leaf is not None:
        leaves.append(contract_legality_leaf)
    return tuple(leaves)


def _round_trace_from_phase_instances(
    phase_instances: tuple[PhaseInstance, ...],
) -> list[Any]:
    """Read the cumulative ``round_trace`` off the last replayed phase state.

    Spec section 5 (migration milestone 2 of 3): a ``trajectory``-scoped leaf
    reads ``scoring_input.phase_instances``, never ``scoring_input.outcome``
    -- even though ``environment.py``'s ``outcome()`` also embeds
    ``round_trace`` verbatim (rulings R9/R10: the family declares
    ``trajectory_outcome_paths=("/round_trace",)`` because that embedded copy
    is for inspection only; ``phase_instances`` remains the authoritative
    scoring provenance). ``AgenticpayBilateralScorer.__call__`` calls this for
    ``score_contract_legality``, mirroring ``govsim.measurement``'s identical
    ``_round_trace_from_phase_instances``.

    ``environment.py``'s ``step()`` SELLER_PHASE branch is the only place
    that appends to ``round_trace``, directly into its own state dict, and
    never resets it; the episode always terminates via that same branch
    (``BUYER_PHASE``'s ``step()`` never sets ``next_phase_id=None``), so by
    the LAST phase instance's LAST transition, that state carries the full,
    cumulative trace for the whole episode -- exactly what
    ``AgenticpayBilateralPlugin.terminal()`` itself reads off that same
    state. Ruling R2 (kernel_scoring_contract_spec.md): reading it here is
    safe because every phase boundary's post-state hash is cross-checked
    against sealed evidence during the verified re-execution that produces
    ``FamilyScoringInput``, so a ``round_trace`` that diverged from the real
    run would already have failed finalization before this scorer is ever
    called -- this only reads what that re-execution produced, never
    re-derives it independently.
    """
    if not phase_instances:
        return []
    last_state = phase_instances[-1].transitions[-1].state
    if not isinstance(last_state, Mapping):
        return []
    return list(last_state.get("round_trace", ()))


@dataclass(frozen=True, slots=True)
class AgenticpayBilateralScorer:
    """One case's fixed set of declared leaves, plus the scorers for them.

    ``environment.py``'s ``build_scorer`` hook returns one of these, mirroring
    ``tau3_retail.measurement.Tau3RetailScorer``'s identical convention.
    """

    family_case: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, ...]

    @property
    def deal_reached_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def buyer_surplus_share_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    @property
    def seller_surplus_share_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[2]

    @property
    def contract_legality_leaf(self) -> MeasurementLeafSpec | None:
        return self.leaves[3] if len(self.leaves) > 3 else None

    @property
    def surplus_share_leaf(self) -> MeasurementLeafSpec:
        """The one leaf ``family_manifest()`` declares (ruling R12), computed
        fresh from ``family_case`` rather than indexed into ``self.leaves``
        -- see ``SURPLUS_SHARE_LEAF_ID``'s and ``build_leaves``'s docstrings
        for why it is deliberately kept out of that legacy, per-role tuple.
        """
        return build_surplus_share_leaf(self.family_case)

    def score_deal_reached(
        self,
        *,
        terminal: Mapping[str, Any],
        diagnostics: Mapping[str, MetricValue] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_deal_reached(
            self.deal_reached_leaf,
            terminal=terminal,
            diagnostics=diagnostics,
            evidence_refs=evidence_refs,
        )

    def score_buyer_surplus_share(
        self, *, terminal: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_buyer_surplus_share(
            self.buyer_surplus_share_leaf,
            family_case=self.family_case,
            terminal=terminal,
            evidence_refs=evidence_refs,
        )

    def score_seller_surplus_share(
        self, *, terminal: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_seller_surplus_share(
            self.seller_surplus_share_leaf,
            family_case=self.family_case,
            terminal=terminal,
            evidence_refs=evidence_refs,
        )

    def score_surplus_share(
        self,
        *,
        terminal: Mapping[str, Any],
        subject_seat: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_surplus_share(
            self.surplus_share_leaf,
            family_case=self.family_case,
            terminal=terminal,
            subject_seat=subject_seat,
            evidence_refs=evidence_refs,
        )

    def score_contract_legality(
        self,
        *,
        round_trace: Sequence[Mapping[str, Any]],
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        leaf = self.contract_legality_leaf
        if leaf is None:
            raise ValueError(
                "this case declares no contract-legality leaf "
                "(is_contract_mode(family_case) is False)"
            )
        return score_contract_legality(
            leaf, round_trace=round_trace, evidence_refs=evidence_refs
        )

    def _score_surplus_share_for_subject_seat(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...]
    ) -> ScoreEnvelope:
        """Score ``surplus_share_leaf`` for the plan's tested subject seat.

        Ruling R12 rule 2, checked before any arithmetic: zero subject seats
        (``"no_subject_seat"``) and several with no declared
        ``subject_reduction`` (``"ambiguous_subject_seat"``, this family
        declares none -- no case in today's corpus pairs a seat against
        itself) both short-circuit to ``invalid_measurement`` here, never a
        fabricated value. Exactly one subject seat delegates to
        ``score_surplus_share`` above, whose own docstring records why
        ruling R12 rule 3's opponent-identity mapping does not apply to this
        leaf.
        """
        subject_seats = scoring_input.seat_context.subject_seats
        leaf = self.surplus_share_leaf
        if len(subject_seats) == 0:
            return _invalid_surplus_share(leaf, "no_subject_seat", evidence_refs)
        if len(subject_seats) > 1:
            return _invalid_surplus_share(leaf, "ambiguous_subject_seat", evidence_refs)
        return self.score_surplus_share(
            terminal=scoring_input.outcome,
            subject_seat=subject_seats[0],
            evidence_refs=evidence_refs,
        )

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        """Score one finalized episode exactly as the production finalizer
        calls it: ``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``
        (``task.evaluation.finalize_family_execution``, per
        kernel_scoring_contract_spec.md section 1).

        Returns every one of this family's declared finalize-time leaves
        (spec section 5) -- ``agenticpay_deal_reached`` and
        ``agenticpay_surplus_share`` always, ``agenticpay_contract_legality``
        only when ``self.contract_legality_leaf`` is not ``None`` (ruling
        R13: exactly the leaves ``family_manifest()`` declares minus
        ``AgenticpayBilateralPlugin.inapplicable_leaf_ids(family_case)``,
        which restates the identical ``is_contract_mode`` predicate this
        already-existing ``build_leaves``/``build_contract_legality_leaf``
        applies -- never a second decision). Composes the existing named
        ``score_deal_reached``/``score_surplus_share``/
        ``score_contract_legality`` methods -- no new scoring logic is
        written here, only the dispatch ruling R12 requires.

        ``agenticpay_deal_reached`` is ``terminal_state``-scoped and reads
        ``scoring_input.outcome`` directly (``outcome()`` is ``dict(terminal)``
        verbatim, so it carries the same ``"reason"`` key
        ``score_deal_reached`` already expects). ``agenticpay_contract_legality``
        is ``trajectory``-scoped and reads ``scoring_input.phase_instances``
        via ``_round_trace_from_phase_instances`` instead, per spec section 5
        -- never ``scoring_input.outcome["round_trace"]``, even though that
        embedded copy (rulings R9/R10) usually agrees.
        """
        outcome = scoring_input.outcome
        deal_score = self.score_deal_reached(terminal=outcome, evidence_refs=evidence_refs)
        surplus_score = self._score_surplus_share_for_subject_seat(
            scoring_input, evidence_refs=evidence_refs
        )
        scores: list[ScoreEnvelope] = [deal_score, surplus_score]
        if self.contract_legality_leaf is not None:
            round_trace = _round_trace_from_phase_instances(scoring_input.phase_instances)
            scores.append(
                self.score_contract_legality(
                    round_trace=round_trace, evidence_refs=evidence_refs
                )
            )
        return FamilyScoreSet(
            primary_leaf_id=self.surplus_share_leaf.leaf_id,
            scores=tuple(scores),
            admission_leaf_ids=(self.surplus_share_leaf.leaf_id,),
        )


def build_scorer(family_case: Mapping[str, Any]) -> AgenticpayBilateralScorer:
    """Build the one ``AgenticpayBilateralScorer`` for a case's ``family_case``."""
    return AgenticpayBilateralScorer(family_case=family_case, leaves=build_leaves(family_case))


__all__ = [
    "BUYER_SURPLUS_ESTIMAND_ID",
    "BUYER_SURPLUS_LEAF_ID",
    "BUYER_SURPLUS_REFERENCE_ID",
    "CONTRACT_LEGALITY_ESTIMAND_ID",
    "CONTRACT_LEGALITY_LEAF_ID",
    "CONTRACT_LEGALITY_REFERENCE_ID",
    "CONTRACT_LEGALITY_RULE_ID",
    "DEAL_REACHED_ESTIMAND_ID",
    "DEAL_REACHED_LEAF_ID",
    "DEAL_REACHED_REFERENCE_ID",
    "DEAL_REACHED_RULE_ID",
    "DEAL_REACHED_SCORER_ID",
    "CONTRACT_LEGALITY_SCORER_ID",
    "SURPLUS_SHARE_SCORER_ID",
    "TERMINAL_DOMAIN_PREDICATE_ID",
    "ZOPA_SUPPORT_BOUND_ID",
    "SELLER_SURPLUS_ESTIMAND_ID",
    "SELLER_SURPLUS_LEAF_ID",
    "SELLER_SURPLUS_REFERENCE_ID",
    "SURPLUS_SHARE_ESTIMAND_ID",
    "SURPLUS_SHARE_LEAF_ID",
    "SURPLUS_SHARE_REFERENCE_ID",
    "AgenticpayBilateralScorer",
    "build_action_diagnostics",
    "build_buyer_surplus_share_leaf",
    "build_contract_legality_leaf",
    "build_deal_reached_leaf",
    "build_leaves",
    "build_scorer",
    "build_seller_surplus_share_leaf",
    "build_surplus_share_leaf",
    "is_contract_mode",
    "score_buyer_surplus_share",
    "score_contract_legality",
    "score_deal_reached",
    "score_seller_surplus_share",
    "score_surplus_share",
]
