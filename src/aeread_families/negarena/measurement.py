"""Measurement declarations for the ``negarena`` adapter (spec section 2).

Two separate leaves; ``composition_kind`` is fixed to ``"leaf"`` by the
kernel itself, so there is deliberately no cross-seat or cross-scenario
scalar here (spec section 2's opening line):

* **Leaf 1 -- ``negarena_seat_outcome`` (primary).** A ``comparative``,
  ``head_to_head`` claim: given a complete two-seat transcript, what did
  *this* seat realize under its own valuation, against the specific
  opponent it was paired with? Scored by delegating to upstream's own
  ``after_game_ends()`` through
  :meth:`~aeread_families.negarena.negarena_bridge.NegarenaBridge.settle`
  -- this module never recomputes ``Trade.execute_trade``/
  ``Valuation.value`` itself (adapter rule: "settlement computation,
  executed via the bridge, never reimplemented", spec section 3). Reported
  **per seat**: one ``ScoreEnvelope`` for RED, a separate one for BLUE,
  both sharing the same ``MeasurementLeafSpec`` declaration (the estimand
  is "this seat's own realized value", not a function of both seats at
  once) -- never a summed/blended two-seat number.
* **Leaf 2 -- ``negarena_agreement_reached`` (diagnostic).** A
  ``rule_constraint`` predicate over the terminal state: did the episode
  end via upstream's own ``ACCEPT`` sentinel, or fall through to
  ``iteration == iterations``/an explicit ``REJECT`` with no trade ever
  executed? Reported separately so a degenerate no-agreement episode is
  never silently averaged into the payoff leaderboard as a "loss"
  (``docs/verifier_taxonomy.md`` section 9).

Both leaves check the episode's termination reason first: a
``malformed_action``/``invalid_measurement`` terminal reason (the two
admission-gate failures ``environment.py`` already catches) yields
``ScoreEnvelope(status="invalid_measurement", primary=None, ...)`` for
*both* leaves -- never a computed "0" payoff, never a silent "false"
agreement (``docs/verifier_taxonomy.md`` section 9: "An invalid or missing
observation must not be scored as an economic zero ... or a dominated
policy").

One documented resolution of an under-specified point in the spec text
(spec section 2's leaf-2 sentence is genuinely readable two ways -- see
``AGREEMENT_TERMINATION_REASONS``'s docstring below for both readings and
why the narrower one was chosen): an ultimatum episode that ends via an
explicit ``REJECT`` is *not* counted as ``agreement_reached`` here (only
``"accepted"`` is), but the raw termination reason is still recorded as a
``metrics`` diagnostic on the same envelope, so no information is lost
under the other reading either.
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
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes

from .cases import BLUE, RED
from .negarena_bridge import NegarenaBridge

LEAF_VERSION = "0.1.0"
ESTIMAND_VERSION = "0.1.0"
REFERENCE_VERSION = "0.1.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "negarena_v1"
DOMAIN_VERSION = "0.1.0"

SEAT_OUTCOME_ESTIMAND_ID = "negarena_seat_outcome"
SEAT_OUTCOME_LEAF_ID = "negarena_seat_outcome_leaf"
HEAD_TO_HEAD_REFERENCE_ID = "negarena_head_to_head_opponent"
SEAT_OUTCOME_SCORER_ID = "negarena_seat_outcome_scorer"

AGREEMENT_ESTIMAND_ID = "negarena_agreement_reached"
AGREEMENT_LEAF_ID = "negarena_agreement_reached_leaf"
AGREEMENT_REFERENCE_ID = "negarena_terminal_agreement_predicate"
AGREEMENT_SCORER_ID = "negarena_agreement_reached_scorer"

# tonight's pairing rule (spec section 2's verifier YAML): one declared
# opponent per case, not a field/panel.
PAIRING_RULE = "fixed_pairing_v0"

# The two admission-gate failures environment.py already catches
# (parse_action/legal); neither leaf is ever scored for these -- see this
# module's docstring and spec section 4 goldens 3/4.
INVALID_TERMINATION_REASONS = frozenset({"malformed_action", "invalid_measurement"})

# Which raw termination reasons count as "an agreement was reached" for
# leaf 2. The spec's own sentence ("did the episode end via an in-band
# ACCEPT/REJECT sentinel, or via iteration == iterations with no
# resolution?") is genuinely readable two ways:
#   (a) narrow: only ACCEPT is an "agreement" -- REJECT is an explicit
#       non-agreement, just as much a resolution as an accept but not one
#       where the seats agreed on anything;
#   (b) broad: ACCEPT-or-REJECT together mean "the negotiation concluded
#       via an in-band sentinel" as opposed to expiring unresolved at the
#       iteration cap, treating "agreement_reached" as shorthand for
#       "reached a decisive conclusion".
# Reading (a) is used here: buy_sell's own game_over() never recognizes a
# REJECT tag at all (only ultimatum's does -- cases.py's
# BUY_SELL_TERMINATION_REASONS has no "rejected" entry), and calling an
# explicit rejection an "agreement" contradicts the leaf's own name. No
# information is lost under reading (b) either: the raw termination
# reason is always recorded as a same-envelope metrics diagnostic (see
# score_agreement_reached), so a consumer preferring reading (b) can
# recover it by combining "accepted" and "rejected" itself.
AGREEMENT_TERMINATION_REASONS = frozenset({"accepted"})


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail/measurement.py``'s identical convention: hashes
    the actual adapter module performing the referenced step, so the pin
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
        schema_ref="negarena_v1/case_payload",
        predicate=_implementation("negarena_domain_predicate", "environment.py"),
    )


def _pairing_rule_source_sha256() -> str:
    """Pins the declared pairing rule itself, not any specific opponent.

    Unlike tau3's ``GOLD_DATABASE_REFERENCE_ID`` (which pins one shared
    gold object every task references), negarena's head-to-head reference
    has no single canonical opponent -- the paired opponent varies per
    case/run and is recorded as score-time metadata (see
    ``score_seat_outcome``), never folded into this shared leaf
    declaration.
    """
    return hashlib.sha256(canonical_json_bytes({"pairing_rule": PAIRING_RULE})).hexdigest()


def _agreement_predicate_source_sha256() -> str:
    return hashlib.sha256(
        canonical_json_bytes({"agreement_reasons": sorted(AGREEMENT_TERMINATION_REASONS)})
    ).hexdigest()


def build_seat_outcome_leaf() -> MeasurementLeafSpec:
    """Leaf 1: the comparative, head-to-head, per-seat outcome claim.

    One shared declaration for both RED and BLUE, both families -- the
    opponent identity is score-time metadata (see ``score_seat_outcome``),
    not part of this leaf's own identity.
    """
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=SEAT_OUTCOME_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="maximize",
        units="native_valuation",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=HEAD_TO_HEAD_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="head_to_head",
        input_scope="trajectory",
        units="native_valuation",
        source_sha256=_pairing_rule_source_sha256(),
        implementation=_implementation(
            "negarena_seat_outcome_bridge_settlement", "negarena_bridge.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=SEAT_OUTCOME_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(SEAT_OUTCOME_SCORER_ID, "measurement.py"),
    )


def build_agreement_reached_leaf() -> MeasurementLeafSpec:
    """Leaf 2: the diagnostic, rule-constraint, terminal-state predicate."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=AGREEMENT_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=AGREEMENT_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="terminal_state",
        units="pass",
        source_sha256=_agreement_predicate_source_sha256(),
        implementation=_implementation("negarena_agreement_predicate", "environment.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=AGREEMENT_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(AGREEMENT_SCORER_ID, "measurement.py"),
    )


def build_leaves() -> tuple[MeasurementLeafSpec, MeasurementLeafSpec]:
    """Both declared leaves, always exactly ``(seat_outcome, agreement)``.

    Unlike ``tau3_retail`` (whose second leaf is declared only for some
    tasks), both negarena leaves are declared for every case in the
    six-scenario corpus -- neither game kind ever makes leaf 2 inapplicable,
    and leaf 1 is scored per seat at score time, not per case at
    declaration time.
    """
    return (build_seat_outcome_leaf(), build_agreement_reached_leaf())


# ---------------------------------------------------------------------------
# Scorers.
# ---------------------------------------------------------------------------


def _invalid_envelope(
    leaf: MeasurementLeafSpec, reason: str, evidence_refs: tuple[str, ...]
) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics={},
        reference_values={},
        validity=ValidityReport("invalid", (reason,)),
        evidence_refs=evidence_refs,
    )


def _accepted_trade_give(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """The give-dict of the trade that would actually be executed.

    Mirrors ``environment.py``'s ``terminal()`` docstring note exactly:
    upstream's own accept grammar always sets the ACCEPTING turn's own
    trade tag to ``"NONE"``; the trade that gets executed is the one
    proposed on the turn *before* the accept (``state["history"][-2]``).
    Returns ``None`` when fewer than two turns were ever recorded, or when
    that prior turn proposed no trade at all (``"kind" != "proposal"``) --
    ``bridge.settle`` treats ``None`` as "no trade to execute", matching
    upstream's own non-accept branch (``final_resources = initial_resources``).
    """
    history = state["history"]
    if len(history) < 2:
        return None
    prior_trade = history[-2]["public"]["newly proposed trade"]
    if prior_trade.get("kind") != "proposal":
        return None
    return dict(prior_trade["give"])


def native_outcome_value(entry: Mapping[str, Any]) -> float:
    """Reduce one typed ``bridge.settle`` outcome entry to one native scalar.

    ``buy_sell``'s entries are already ``{"kind": "scalar", ...}``
    (``Valuation.value`` already reduces to one ``ZUP``-denominated
    number). ``ultimatum``'s are ``{"kind": "resources", ...}`` -- raw
    ``Resources`` holdings/deltas, since ``UltimatumGoal`` carries no
    ``Valuation`` (see ``negarena_bridge_driver.py``'s ``_outcome_json``
    for the exact upstream asymmetry this is reducing). Every
    ``negarena.ultimatum.*`` scenario authored in ``cases.py`` uses exactly
    one money token, so summing the resource dict's values recovers that
    single scalar without having to name which key is "the" money token.
    """
    if entry["kind"] == "scalar":
        return float(entry["value"])
    if entry["kind"] == "resources":
        return float(sum(entry["value"].values()))
    raise ValueError(f"unknown outcome entry kind: {entry!r}")


def score_seat_outcome(
    leaf: MeasurementLeafSpec,
    *,
    bridge: NegarenaBridge,
    family_case: Mapping[str, Any],
    state: Mapping[str, Any],
    terminal: Mapping[str, Any],
    seat_id: str,
    opponent_policy_id: str,
    pairing_rule: str = PAIRING_RULE,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 1 for one seat by delegating settlement to the bridge.

    Never recomputes ``Trade.execute_trade``/``Valuation.value`` itself:
    :meth:`NegarenaBridge.settle` shells out to the pinned upstream
    checkout and calls ``after_game_ends()`` on a freshly constructed real
    game object; this function only reduces the two-entry ``player_outcome``
    it returns to this seat's own native-unit scalar. A
    ``malformed_action``/``invalid_measurement`` terminal reason short-
    circuits to an ``invalid_measurement`` envelope before any bridge call
    is made (spec section 4 goldens 3/4: "no negarena_seat_outcome leaf is
    emitted for either").
    """
    reason = terminal["reason"]
    if reason in INVALID_TERMINATION_REASONS:
        return _invalid_envelope(leaf, reason, evidence_refs)

    scenario = family_case["scenario"]
    proposed_trade = _accepted_trade_give(state)
    result = bridge.settle(
        game_kind=scenario["game_kind"],
        scenario=scenario,
        iteration_count=terminal["iteration_count"],
        final_answer=terminal["last_answer"] or "",
        proposed_trade=proposed_trade,
    )
    if not result["settled"]:
        return _invalid_envelope(leaf, f"no_settlement:{result['reason']}", evidence_refs)

    seat_index = 0 if seat_id == RED else 1
    opponent_index = 1 - seat_index
    opponent_seat_id = BLUE if seat_id == RED else RED
    own_value = native_outcome_value(result["player_outcome"][seat_index])
    opponent_value = native_outcome_value(result["player_outcome"][opponent_index])

    primary = MetricValue(
        own_value,
        "native_valuation",
        metadata={
            "seat_role": seat_id,
            "opponent_seat_role": opponent_seat_id,
            "opponent_policy_id": opponent_policy_id,
            "pairing_rule": pairing_rule,
        },
    )
    metrics = {"counterparty_outcome": MetricValue(opponent_value, "native_valuation")}
    utility = {seat_id: MetricValue(own_value, "native_valuation")}
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=primary,
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
        utility_by_seat=utility,
        capture_by_seat=utility,
    )


def score_agreement_reached(
    leaf: MeasurementLeafSpec,
    *,
    terminal: Mapping[str, Any],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 2 from the terminal state's own recorded reason.

    A pure predicate over ``terminal["reason"]`` -- never calls the bridge,
    never touches settlement. See ``AGREEMENT_TERMINATION_REASONS`` for the
    documented reading this module resolves the spec's ambiguous wording
    to, and why the raw reason is still recorded here regardless.
    """
    reason = terminal["reason"]
    if reason in INVALID_TERMINATION_REASONS:
        return _invalid_envelope(leaf, reason, evidence_refs)
    agreement_reached = reason in AGREEMENT_TERMINATION_REASONS
    metrics = {
        "terminated_by_iteration_cap": MetricValue(
            1.0 if reason == "iteration_cap" else 0.0, "pass"
        ),
        "terminated_by_explicit_rejection": MetricValue(
            1.0 if reason == "rejected" else 0.0, "pass"
        ),
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0 if agreement_reached else 0.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True, slots=True)
class NegarenaScorer:
    """One case's fixed set of declared leaves, plus the scorers for them.

    ``environment.py``'s ``build_scorer`` hook returns one of these,
    mirroring ``tau3_retail``'s identical ``Tau3RetailScorer`` convention.
    """

    family_case: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, MeasurementLeafSpec]

    @property
    def seat_outcome_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def agreement_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    def __call__(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        """Conform to the shared kernel's single-outcome scorer call.

        ``family_evaluation.py``'s ``finalize_family_execution``/
        ``replay_family_receipt``/``audit_family_receipt`` all call
        ``plugin.build_scorer(family_case)(outcome, evidence_refs=...)``
        directly -- before this method existed, any completed negarena
        ``CellExecution`` reaching that call site raised
        ``TypeError: 'NegarenaScorer' object is not callable`` before
        ``score_recorded`` was ever appended, before evidence was ever
        sealed, and before a receipt was ever written
        (docs/negarena_codex_triage.md Finding 1).

        That generic call site passes only the plugin's own ``outcome()``
        dict and a tuple of evidence refs -- never the ``NegarenaBridge``,
        never which seat is the tested subject, never the fixed opponent's
        policy id. Real per-seat scoring (``score_seat_outcome``) needs all
        three: which seat is realizing a value depends on a RunPlan cell's
        ``profile_by_seat``/``EvaluationBlock.subject_seats`` -- context this
        single-outcome call site does not carry and this method must not
        guess at (spec section 2: "never a computed zero payoff ... An
        invalid or missing observation must not be scored as an economic
        zero"). So this always reports the declared primary leaf
        (``negarena_seat_outcome``) as ``invalid_measurement`` here, with a
        typed reason rather than a fabricated score -- ``finalize_family_execution``
        already has a well-formed ``invalid_measurement`` receipt path (score
        recorded, evidence sealed, receipt written, ``inclusion_status="excluded"``)
        that this now reaches instead of crashing. A caller that needs the
        real per-seat/agreement scores must call
        ``score_seat_outcome``/``score_agreement_reached`` directly, exactly
        as ``tests/test_negarena_harness.py`` already does (mirroring
        ``tau3_retail``'s identical ``Tau3RetailScorer`` convention, whose own
        docstring notes the kernel does not yet invoke ``build_scorer`` with
        per-seat context either).
        """
        del outcome
        return _invalid_envelope(
            self.seat_outcome_leaf,
            "negarena_kernel_finalizer_lacks_seat_pairing_context",
            evidence_refs,
        )

    def score_seat_outcome(
        self,
        *,
        bridge: NegarenaBridge,
        state: Mapping[str, Any],
        terminal: Mapping[str, Any],
        seat_id: str,
        opponent_policy_id: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_seat_outcome(
            self.seat_outcome_leaf,
            bridge=bridge,
            family_case=self.family_case,
            state=state,
            terminal=terminal,
            seat_id=seat_id,
            opponent_policy_id=opponent_policy_id,
            evidence_refs=evidence_refs,
        )

    def score_agreement_reached(
        self, *, terminal: Mapping[str, Any], evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_agreement_reached(
            self.agreement_leaf, terminal=terminal, evidence_refs=evidence_refs
        )


def build_scorer(family_case: Mapping[str, Any]) -> NegarenaScorer:
    """Build the one ``NegarenaScorer`` for a case's ``family_case``."""
    return NegarenaScorer(family_case=family_case, leaves=build_leaves())


__all__ = [
    "AGREEMENT_ESTIMAND_ID",
    "AGREEMENT_LEAF_ID",
    "AGREEMENT_REFERENCE_ID",
    "AGREEMENT_TERMINATION_REASONS",
    "HEAD_TO_HEAD_REFERENCE_ID",
    "INVALID_TERMINATION_REASONS",
    "NegarenaScorer",
    "PAIRING_RULE",
    "SEAT_OUTCOME_ESTIMAND_ID",
    "SEAT_OUTCOME_LEAF_ID",
    "build_agreement_reached_leaf",
    "build_leaves",
    "build_scorer",
    "build_seat_outcome_leaf",
    "native_outcome_value",
    "score_agreement_reached",
    "score_seat_outcome",
]
