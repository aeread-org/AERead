"""Measurement declarations for the alympics.wac adapter (spec section 2).

Four leaves, each ``composition_kind`` fixed to ``"leaf"`` by the kernel
itself, reported as a **vector** -- never collapsed into one blended score
-- per the problem-bound audit's explicit verdict on this family
(``docs/problem_bound_case_audit.md`` row P01, quoted in the adapter spec):
"survival has natural support, but the paper does not solve the policy
game... do not equate survival with a solved optimum."

* **Leaf 1 -- ``alympics_wac_terminal_wealth`` (primary, comparative).**
  Terminal balance for the focal seat, compared with the same seat run
  under a named baseline policy on the *same* supply schedule/seed/opponent
  panel. The opponent panel is part of the estimand (spec section 2), so
  every leaf declaration is built for one ``(focal_seat, panel_policy_ids)``
  pair, never for a case in the abstract.
* **Leaf 2 -- ``alympics_wac_survival`` (diagnostic, comparative).** Rounds
  survived and alive-at-terminal, reported *separately* from wealth so a
  degenerate zero-information elimination (spec section 4 golden 5) is
  never averaged into wealth as if it were an ordinary loss.
* **Leaf 3 -- ``alympics_wac_bid_legality`` (rule_constraint).** Per round,
  per seat: was the focal seat's bid legal (``bid <= balance`` at bid time,
  the gate upstream itself only enforces implicitly -- governing facts)?
  This leaf also gates leaves 1/2: an illegal bid must never "masquerade as
  an ordinary legal loss" (spec section 4 golden 3), so any illegal round
  forces leaves 1/2 to ``invalid_measurement`` for that focal seat, never a
  silently-lower wealth number.
* **Leaf 4 -- ``alympics_wac_settlement_exactness`` (rule_constraint).**
  Recomputes each round's transition by a second, independent call into
  upstream's own settlement mechanics (:func:`aeread_families.alympics_wac.
  environment._delegate_round`, itself a direct, unmodified call into
  ``_get_salary``/``_check_winner``/``_round_settlement`` -- never a
  reimplementation) against the sealed pre-round state
  (``round_log[i]["players_before"]``), and requires exact equality with
  the sealed post-round state (``round_log[i]["players_after"]``). This is
  the Gate 2 requirement 2 "reconstruct transitions from sealed
  observations ... and pre-state" check; the requirement 1 "independent
  implementation" cross-check lives in ``parity.py``, which drives a
  *second, separately constructed* upstream object outside this leaf
  entirely.

All four leaves are ``evaluation_class="deterministic"``: upstream's own
game mechanics are fully mechanical given a complete scripted trajectory,
so none of these leaves is judge-dependent (unlike ``tau3.retail``, this
family declares no rater/judge component at all).

One documented deviation from the literal spec text, mirroring
``tau3_retail.measurement``'s own documented deviation: section 2's leaf 1
YAML block writes ``direction: higher_is_better``. The kernel's real
``EstimandSpec`` only accepts ``{"maximize", "minimize", "none"}`` --
``"higher_is_better"`` is not a legal value and construction raises
``MeasurementContractError`` for it. This module uses ``"maximize"``
(the kernel's own name for exactly that) for leaves 1 and 2, and ``"none"``
for the two rule-constraint leaves (3 and 4), which have no directional
sense.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

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
from aeread.shared_runner.resolver import canonical_json_bytes

from .environment import _delegate_round

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "alympics_wac_base_v1"
DOMAIN_VERSION = "1.0.0"

DEFAULT_BASELINE_POLICY_ID = "proportional"

TERMINAL_WEALTH_ESTIMAND_ID = "alympics_wac_terminal_wealth"
TERMINAL_WEALTH_LEAF_ID = "alympics_wac_terminal_wealth_leaf"
TERMINAL_WEALTH_REFERENCE_ID = "alympics_wac_terminal_wealth_baseline_delta"
TERMINAL_WEALTH_SCORER_ID = "alympics_wac_terminal_wealth_scorer"

SURVIVAL_ESTIMAND_ID = "alympics_wac_survival"
SURVIVAL_LEAF_ID = "alympics_wac_survival_leaf"
SURVIVAL_REFERENCE_ID = "alympics_wac_survival_baseline_delta"
SURVIVAL_SCORER_ID = "alympics_wac_survival_scorer"

BID_LEGALITY_ESTIMAND_ID = "alympics_wac_bid_legality"
BID_LEGALITY_LEAF_ID = "alympics_wac_bid_legality_leaf"
BID_LEGALITY_REFERENCE_ID = "alympics_wac_bid_legality_rule_v1"
BID_LEGALITY_SCORER_ID = "alympics_wac_bid_legality_scorer"

SETTLEMENT_EXACTNESS_ESTIMAND_ID = "alympics_wac_settlement_exactness"
SETTLEMENT_EXACTNESS_LEAF_ID = "alympics_wac_settlement_exactness_leaf"
SETTLEMENT_EXACTNESS_REFERENCE_ID = "alympics_wac_settlement_exactness_rule_v1"
SETTLEMENT_EXACTNESS_SCORER_ID = "alympics_wac_settlement_exactness_scorer"

# Fixed rule text pinned by the two rule_constraint leaves' `source_sha256`
# (spec section 2, leaves 3/4). Neither rule varies by case -- upstream's
# own settlement/legality mechanics are identical for every grid cell -- so
# the reference source is this leaf's own versioned rule description, not
# per-case content (contrast leaf 1/2 below, whose reference source *is*
# per-(case, focal_seat) content: the opponent panel).
BID_LEGALITY_RULE_TEXT = (
    "alympics_wac_bid_legality_rule_v1: for every round the focal seat "
    "participates in, its bid must be a non-negative integer and must not "
    "exceed its balance at the time of bidding (post-salary, pre-settlement)."
)
SETTLEMENT_EXACTNESS_RULE_TEXT = (
    "alympics_wac_settlement_exactness_rule_v1: recomputing "
    "_get_salary/_check_winner/_round_settlement against a round's sealed "
    "pre-state and recorded bids must reproduce the sealed post-state "
    "(balance/hp/no_drink per seat) and winners list exactly."
)


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail.measurement``'s identical helper: the pin changes
    exactly when the referenced adapter module changes.
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
        schema_ref="alympics_wac_base_v1/case_payload",
        predicate=_implementation("alympics_wac_base_domain_predicate", "environment.py"),
    )


def _opponent_panel_sha256(focal_seat: str, panel_policy_ids: Mapping[str, str]) -> str:
    """Content digest binding a leaf 1/2 reference to its exact opponent panel.

    The opponent panel (the other 4 seats' declared policies) is part of
    the estimand (spec section 2): two leaves that differ only in which
    policies the non-focal seats run are not interchangeable, so they must
    not collide on ``source_sha256``.
    """
    payload = {"focal_seat": focal_seat, "panel_policy_ids": dict(sorted(panel_policy_ids.items()))}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


# ---------------------------------------------------------------------------
# Leaf declarations.
# ---------------------------------------------------------------------------


def build_terminal_wealth_leaf(
    *,
    focal_seat: str,
    panel_policy_ids: Mapping[str, str],
    baseline_policy_id: str = DEFAULT_BASELINE_POLICY_ID,
) -> MeasurementLeafSpec:
    """Leaf 1: the primary, comparative terminal-wealth claim."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=TERMINAL_WEALTH_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="maximize",
        units="native_currency",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=TERMINAL_WEALTH_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="baseline_delta",
        input_scope="trajectory",
        units="native_currency",
        source_sha256=_opponent_panel_sha256(focal_seat, panel_policy_ids),
        implementation=_implementation(
            "alympics_wac_terminal_wealth_baseline_run", "measurement.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=TERMINAL_WEALTH_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(TERMINAL_WEALTH_SCORER_ID, "measurement.py"),
    )


def build_survival_leaf(
    *,
    focal_seat: str,
    panel_policy_ids: Mapping[str, str],
    baseline_policy_id: str = DEFAULT_BASELINE_POLICY_ID,
) -> MeasurementLeafSpec:
    """Leaf 2: the diagnostic, comparative survival claim -- never blended
    into leaf 1's wealth number (spec section 2)."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=SURVIVAL_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="maximize",
        units="rounds_survived",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=SURVIVAL_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="baseline_delta",
        input_scope="trajectory",
        units="rounds_survived",
        source_sha256=_opponent_panel_sha256(focal_seat, panel_policy_ids),
        implementation=_implementation("alympics_wac_survival_baseline_run", "measurement.py"),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=SURVIVAL_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(SURVIVAL_SCORER_ID, "measurement.py"),
    )


def build_bid_legality_leaf() -> MeasurementLeafSpec:
    """Leaf 3: the rule_constraint gate upstream itself only enforces implicitly."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=BID_LEGALITY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=BID_LEGALITY_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="constraint_satisfaction",
        input_scope="trajectory",
        units="pass",
        source_sha256=hashlib.sha256(BID_LEGALITY_RULE_TEXT.encode("utf-8")).hexdigest(),
        implementation=_implementation("alympics_wac_bid_legality_gate", "environment.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=BID_LEGALITY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(BID_LEGALITY_SCORER_ID, "measurement.py"),
    )


def build_settlement_exactness_leaf() -> MeasurementLeafSpec:
    """Leaf 4: the shadow-recompute parity cross-check (spec section 2)."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=SETTLEMENT_EXACTNESS_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=SETTLEMENT_EXACTNESS_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="state_invariant",
        input_scope="trajectory",
        units="pass",
        source_sha256=hashlib.sha256(SETTLEMENT_EXACTNESS_RULE_TEXT.encode("utf-8")).hexdigest(),
        implementation=_implementation("alympics_wac_settlement_shadow_recompute", "environment.py"),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=SETTLEMENT_EXACTNESS_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(SETTLEMENT_EXACTNESS_SCORER_ID, "measurement.py"),
    )


def build_leaves(
    *,
    focal_seat: str,
    panel_policy_ids: Mapping[str, str],
    baseline_policy_id: str = DEFAULT_BASELINE_POLICY_ID,
) -> tuple[MeasurementLeafSpec, MeasurementLeafSpec, MeasurementLeafSpec, MeasurementLeafSpec]:
    """The complete, always-4 leaf vector for one ``(focal_seat, panel)`` pair.

    Unlike ``tau3.retail`` (where a task sometimes declares 1 leaf, sometimes
    2), alympics.wac always declares exactly these 4 -- spec section 2 names
    no condition under which any of them is omitted.
    """
    return (
        build_terminal_wealth_leaf(
            focal_seat=focal_seat,
            panel_policy_ids=panel_policy_ids,
            baseline_policy_id=baseline_policy_id,
        ),
        build_survival_leaf(
            focal_seat=focal_seat,
            panel_policy_ids=panel_policy_ids,
            baseline_policy_id=baseline_policy_id,
        ),
        build_bid_legality_leaf(),
        build_settlement_exactness_leaf(),
    )


# ---------------------------------------------------------------------------
# Evidence helpers -- pure functions over already-recorded round_log/final
# state, never re-running an episode themselves (that stays the caller's
# job, via `run_episode`, exactly as tau3_retail.measurement's scorers never
# invoke the bridge to *produce* a trajectory, only to *score* one).
# ---------------------------------------------------------------------------


def is_supply_degenerate(
    supply_schedule: Sequence[int], personas: Mapping[str, Mapping[str, Any]]
) -> bool:
    """True iff no persona's requirement can ever be met by this schedule.

    Generalizes spec section 4 golden 5's verified fact ("no seat's
    requirement <= 0 ever holds"): if every round's supply is strictly
    below the *smallest* persona requirement, ``_check_winner`` can never
    admit a single winner regardless of any seat's policy -- leaves 1/2
    become information-free by construction for every policy assignment,
    never a real measurement of skill (never "every policy tied at zero
    skill" -- spec section 4).
    """
    if not supply_schedule:
        raise ValueError("supply_schedule must be non-empty")
    min_requirement = min(persona["requirement"] for persona in personas.values())
    return all(supply < min_requirement for supply in supply_schedule)


def rounds_survived(round_log: Sequence[Mapping[str, Any]], seat: str) -> int:
    """Count of rounds ``seat`` actually participated in (bid during).

    A round's ``bids`` mapping only ever contains seats alive at that
    round's start (``environment.step``'s ``alive_seats``), so this is
    exactly "how many rounds did this seat survive to bid in" -- computed
    purely from already-recorded evidence, never by re-deriving upstream's
    own elimination bookkeeping.
    """
    return sum(1 for entry in round_log if seat in entry.get("bids", {}))


def alive_at_terminal(final_players: Mapping[str, Mapping[str, Any]], seat: str) -> bool:
    return bool(final_players[seat]["alive"])


def bid_legality_ok(round_log: Sequence[Mapping[str, Any]], seat: str) -> bool:
    return _first_illegal_round(round_log, seat) is None


def _first_illegal_round(round_log: Sequence[Mapping[str, Any]], seat: str) -> int | None:
    for entry in round_log:
        bid_legal = entry.get("bid_legal")
        if not bid_legal or seat not in bid_legal:
            continue
        if not bid_legal[seat]:
            return entry["round_id"]
    return None


def _malformed_round_entry(round_log: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for entry in round_log:
        if entry.get("status") == "malformed_action":
            return entry
    raise ValueError("round_log contains no malformed_action entry")


def _invalid_envelope(
    leaf: MeasurementLeafSpec,
    *,
    reasons: tuple[str, ...],
    metrics: Mapping[str, MetricValue] | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics=dict(metrics or {}),
        reference_values={},
        validity=ValidityReport("invalid", reasons=reasons),
        evidence_refs=evidence_refs,
    )


def _malformed_envelope(
    leaf: MeasurementLeafSpec,
    round_log: Sequence[Mapping[str, Any]],
    *,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """The typed-invalidity result every leaf returns on a malformed episode.

    Never a task-quality zero (spec section 4 golden 4 / taxonomy section
    9): settlement never ran for the malformed round, so nothing about
    wealth, survival, legality, or settlement exactness can be claimed for
    it, or for the episode as a whole (it terminates there).
    """
    entry = _malformed_round_entry(round_log)
    reason = f"malformed_action:round_{entry['round_id']}:{entry.get('error')}"
    return _invalid_envelope(leaf, reasons=(reason,), evidence_refs=evidence_refs)


# ---------------------------------------------------------------------------
# Scorers.
# ---------------------------------------------------------------------------


def score_bid_legality(
    leaf: MeasurementLeafSpec,
    *,
    focal_seat: str,
    round_log: Sequence[Mapping[str, Any]],
    termination_reason: str,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 3 from the environment's own already-recorded ``bid_legal``.

    Never recomputes legality itself: ``environment.step``'s
    ``_check_winner_wrapper`` already computed ``bid_legal`` per round from
    the real, delegated post-salary balance (governing facts); this
    function only reduces that already-recorded evidence to one typed
    per-focal-seat result, never re-deriving it from raw bids/balances.
    """
    if termination_reason == "malformed_action":
        return _malformed_envelope(leaf, round_log, evidence_refs=evidence_refs)
    metrics = {
        f"round_{entry['round_id']}_bid_legal": MetricValue(
            1.0 if entry["bid_legal"][focal_seat] else 0.0, "pass"
        )
        for entry in round_log
        if entry.get("bid_legal") and focal_seat in entry["bid_legal"]
    }
    illegal_round = _first_illegal_round(round_log, focal_seat)
    if illegal_round is not None:
        return _invalid_envelope(
            leaf,
            reasons=(f"bid_exceeds_balance:round_{illegal_round}:seat_{focal_seat}",),
            metrics=metrics,
            evidence_refs=evidence_refs,
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_settlement_exactness(
    leaf: MeasurementLeafSpec,
    *,
    upstream_module: Any,
    round_log: Sequence[Mapping[str, Any]],
    termination_reason: str,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 4 by shadow-recomputing every round from sealed evidence.

    For each non-malformed round, calls
    ``environment._delegate_round`` -- upstream's own, unmodified
    ``_get_salary``/``_check_winner``/``_round_settlement`` -- a second
    time against ``round_log[i]["players_before"]`` and the recorded bids,
    and requires the result to reproduce ``round_log[i]["players_after"]``,
    the recorded winners, and the recorded bid-legality flags exactly. This
    never diffs against a second, independently-written implementation
    (that check is ``parity.py``'s job); it proves the sealed evidence is
    sufficient to deterministically reconstruct the sealed outcome (Gate 2
    requirement 2), which a corrupted or hand-edited round_log entry would
    fail.
    """
    if termination_reason == "malformed_action":
        return _malformed_envelope(leaf, round_log, evidence_refs=evidence_refs)
    diverged_rounds: list[int] = []
    checked = 0
    for entry in round_log:
        if entry.get("status") == "malformed_action":
            continue
        recomputed = _delegate_round(
            upstream_module,
            round_id=entry["round_id"],
            supply=entry["supply"],
            alive_seats=tuple(entry["players_before"]),
            players_state=entry["players_before"],
            bids=entry["bids"],
        )
        checked += 1
        if (
            dict(recomputed.players) != dict(entry["players_after"])
            or list(recomputed.winners) != list(entry["winners"])
            or dict(recomputed.bid_legal) != dict(entry["bid_legal"])
        ):
            diverged_rounds.append(entry["round_id"])
    if diverged_rounds:
        return _invalid_envelope(
            leaf,
            reasons=tuple(
                f"settlement_recompute_diverged:round_{round_id}" for round_id in diverged_rounds
            ),
            evidence_refs=evidence_refs,
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "pass"),
        metrics={"rounds_checked": MetricValue(float(checked), "count")},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_terminal_wealth(
    leaf: MeasurementLeafSpec,
    *,
    focal_seat: str,
    actual_final_players: Mapping[str, Mapping[str, Any]],
    actual_round_log: Sequence[Mapping[str, Any]],
    actual_termination_reason: str,
    baseline_final_players: Mapping[str, Mapping[str, Any]],
    not_informative: bool = False,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 1: gated by leaf 3, never a silent illegal-loss masquerade.

    ``not_informative`` is a caller-declared fact (from
    :func:`is_supply_degenerate` against the case's own frozen supply
    schedule and personas), not re-derived here from the trajectory --
    mirrors ``tau3_retail.score_db_state`` taking an already-known
    ``termination_reason`` rather than re-deriving it.
    """
    if actual_termination_reason == "malformed_action":
        return _malformed_envelope(leaf, actual_round_log, evidence_refs=evidence_refs)
    if not bid_legality_ok(actual_round_log, focal_seat):
        illegal_round = _first_illegal_round(actual_round_log, focal_seat)
        return _invalid_envelope(
            leaf,
            reasons=(f"bid_exceeds_balance:round_{illegal_round}:seat_{focal_seat}",),
            evidence_refs=evidence_refs,
        )
    actual_wealth = float(actual_final_players[focal_seat]["balance"])
    baseline_wealth = float(baseline_final_players[focal_seat]["balance"])
    metadata: dict[str, Any] = {}
    if not_informative:
        metadata["not_informative"] = True
        metadata["reason"] = (
            "supply schedule never permits any seat's requirement to be "
            "met; every policy is tied at zero information by construction"
        )
    primary = MetricValue(actual_wealth - baseline_wealth, "native_currency", metadata=metadata)
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=primary,
        metrics={},
        reference_values={
            "actual_terminal_wealth": MetricValue(actual_wealth, "native_currency"),
            "baseline_terminal_wealth": MetricValue(baseline_wealth, "native_currency"),
        },
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_survival(
    leaf: MeasurementLeafSpec,
    *,
    focal_seat: str,
    actual_round_log: Sequence[Mapping[str, Any]],
    actual_final_players: Mapping[str, Mapping[str, Any]],
    actual_termination_reason: str,
    baseline_round_log: Sequence[Mapping[str, Any]],
    baseline_final_players: Mapping[str, Mapping[str, Any]],
    not_informative: bool = False,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 2: reported separately from wealth, same gating as leaf 1."""
    if actual_termination_reason == "malformed_action":
        return _malformed_envelope(leaf, actual_round_log, evidence_refs=evidence_refs)
    if not bid_legality_ok(actual_round_log, focal_seat):
        illegal_round = _first_illegal_round(actual_round_log, focal_seat)
        return _invalid_envelope(
            leaf,
            reasons=(f"bid_exceeds_balance:round_{illegal_round}:seat_{focal_seat}",),
            evidence_refs=evidence_refs,
        )
    actual_rounds = float(rounds_survived(actual_round_log, focal_seat))
    baseline_rounds = float(rounds_survived(baseline_round_log, focal_seat))
    metadata: dict[str, Any] = {}
    if not_informative:
        metadata["not_informative"] = True
        metadata["reason"] = (
            "supply schedule never permits any seat's requirement to be "
            "met; every policy is tied at zero information by construction"
        )
    primary = MetricValue(actual_rounds - baseline_rounds, "rounds_survived", metadata=metadata)
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=primary,
        metrics={
            "actual_alive_at_terminal": MetricValue(
                1.0 if alive_at_terminal(actual_final_players, focal_seat) else 0.0, "pass"
            ),
            "baseline_alive_at_terminal": MetricValue(
                1.0 if alive_at_terminal(baseline_final_players, focal_seat) else 0.0, "pass"
            ),
        },
        reference_values={
            "actual_rounds_survived": MetricValue(actual_rounds, "rounds_survived"),
            "baseline_rounds_survived": MetricValue(baseline_rounds, "rounds_survived"),
        },
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Case-bound scorer (environment.py's ``build_scorer`` hook).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlympicsWacScorer:
    """One case's fixed leaf-building context, plus the scorers for them.

    Mirrors ``tau3_retail.measurement.Tau3RetailScorer``'s shape: bundles
    the case-level context (here, ``family_case`` -- the validated payload,
    which carries ``grid_cell.policy_assignment``, ``supply_schedule``, and
    ``personas``) so callers never have to re-derive the opponent panel or
    the degenerate-supply flag by hand.
    """

    family_case: Mapping[str, Any]

    def panel_policy_ids(self, focal_seat: str) -> dict[str, str]:
        assignment = self.family_case["grid_cell"]["policy_assignment"]
        return {seat: policy for seat, policy in assignment.items() if seat != focal_seat}

    def leaves_for_focal_seat(
        self, focal_seat: str
    ) -> tuple[MeasurementLeafSpec, MeasurementLeafSpec, MeasurementLeafSpec, MeasurementLeafSpec]:
        return build_leaves(focal_seat=focal_seat, panel_policy_ids=self.panel_policy_ids(focal_seat))

    def is_not_informative(self) -> bool:
        return is_supply_degenerate(
            self.family_case["supply_schedule"], self.family_case["personas"]
        )

    def score_terminal_wealth(
        self,
        *,
        focal_seat: str,
        actual_final_players: Mapping[str, Mapping[str, Any]],
        actual_round_log: Sequence[Mapping[str, Any]],
        actual_termination_reason: str,
        baseline_final_players: Mapping[str, Mapping[str, Any]],
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        leaf = self.leaves_for_focal_seat(focal_seat)[0]
        return score_terminal_wealth(
            leaf,
            focal_seat=focal_seat,
            actual_final_players=actual_final_players,
            actual_round_log=actual_round_log,
            actual_termination_reason=actual_termination_reason,
            baseline_final_players=baseline_final_players,
            not_informative=self.is_not_informative(),
            evidence_refs=evidence_refs,
        )

    def score_survival(
        self,
        *,
        focal_seat: str,
        actual_round_log: Sequence[Mapping[str, Any]],
        actual_final_players: Mapping[str, Mapping[str, Any]],
        actual_termination_reason: str,
        baseline_round_log: Sequence[Mapping[str, Any]],
        baseline_final_players: Mapping[str, Mapping[str, Any]],
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        leaf = self.leaves_for_focal_seat(focal_seat)[1]
        return score_survival(
            leaf,
            focal_seat=focal_seat,
            actual_round_log=actual_round_log,
            actual_final_players=actual_final_players,
            actual_termination_reason=actual_termination_reason,
            baseline_round_log=baseline_round_log,
            baseline_final_players=baseline_final_players,
            not_informative=self.is_not_informative(),
            evidence_refs=evidence_refs,
        )

    def score_bid_legality(
        self,
        *,
        focal_seat: str,
        round_log: Sequence[Mapping[str, Any]],
        termination_reason: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        leaf = self.leaves_for_focal_seat(focal_seat)[2]
        return score_bid_legality(
            leaf,
            focal_seat=focal_seat,
            round_log=round_log,
            termination_reason=termination_reason,
            evidence_refs=evidence_refs,
        )

    def score_settlement_exactness(
        self,
        *,
        focal_seat: str,
        upstream_module: Any,
        round_log: Sequence[Mapping[str, Any]],
        termination_reason: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        leaf = self.leaves_for_focal_seat(focal_seat)[3]
        return score_settlement_exactness(
            leaf,
            upstream_module=upstream_module,
            round_log=round_log,
            termination_reason=termination_reason,
            evidence_refs=evidence_refs,
        )


def build_scorer(family_case: Mapping[str, Any]) -> AlympicsWacScorer:
    """Build the one ``AlympicsWacScorer`` for a case's ``family_case``."""
    return AlympicsWacScorer(family_case=family_case)


__all__ = [
    "AlympicsWacScorer",
    "BID_LEGALITY_ESTIMAND_ID",
    "BID_LEGALITY_LEAF_ID",
    "DEFAULT_BASELINE_POLICY_ID",
    "SETTLEMENT_EXACTNESS_ESTIMAND_ID",
    "SETTLEMENT_EXACTNESS_LEAF_ID",
    "SURVIVAL_ESTIMAND_ID",
    "SURVIVAL_LEAF_ID",
    "TERMINAL_WEALTH_ESTIMAND_ID",
    "TERMINAL_WEALTH_LEAF_ID",
    "alive_at_terminal",
    "bid_legality_ok",
    "build_bid_legality_leaf",
    "build_leaves",
    "build_scorer",
    "build_settlement_exactness_leaf",
    "build_survival_leaf",
    "build_terminal_wealth_leaf",
    "is_supply_degenerate",
    "rounds_survived",
    "score_bid_legality",
    "score_settlement_exactness",
    "score_survival",
    "score_terminal_wealth",
]
