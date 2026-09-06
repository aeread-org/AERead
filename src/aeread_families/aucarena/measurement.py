"""Measurement declarations for the ``aucarena`` adapter (spec section 2).

Declares the four leaves ``docs/aucarena_adapter_spec.md`` section 2 requires
and nothing else: **no** ``objective_reference`` leaf is declared (profit and
TrueSkill do not solve the auction policy game -- P21 row,
``verifier_taxonomy.md`` section 13). Every leaf is
``composition_kind="leaf"`` (the kernel's own fixed value); this module never
folds them into one blended number.

* **``aucarena_budget_invariant`` (``rule_constraint`` / ``state_invariant``,
  trajectory-scoped).** No seat's budget goes negative at any recorded
  post-round state. Checked directly against every ``TransitionResult.state``
  the scheduler already recorded -- a state property, not a re-derivation of
  auction policy.
* **``aucarena_bid_legality`` (``rule_constraint`` / ``constraint_satisfaction``,
  trajectory-scoped).** Every recorded non-withdraw bid (from any seat)
  independently satisfies vendored ``bid_sanity_check`` -- recomputed here
  from each action's own frozen pre-round observation, never by reading back
  the environment's own ``legal()`` verdict. Per ``verifier_taxonomy.md``
  section 13's P21 row: "Environment enforcement and independent
  verification remain distinct." When this module's independent recompute
  ever disagrees with the environment's own recorded legality determination,
  that is an adapter defect (not an ordinary scoring outcome) and this module
  raises :class:`AucArenaMeasurementError` rather than silently reporting it
  as a normal pass/fail -- proven not to be a vacuous check by
  ``tests/test_aucarena_parity.py``'s mutation test.
* **``aucarena_hammer_rule`` (``rule_constraint`` / ``temporal_property``,
  trajectory-scoped).** Each item's sold/unsold determination and winning
  bidder/price, in order, independently reproduced from the recorded
  per-round bid attempts via vendored ``record_bid``/``check_hammer``, and
  compared against the environment's own recorded transition consequences.
  This *is* the component parity check the spec's test plan (section 6)
  calls for: the environment produces its recorded outcome by calling these
  same vendored functions once, live, during ``step()``; this scorer calls
  them again, independently, from nothing but the sealed episode evidence.
  The accept/reject partition feeding that replay is itself independently
  recomputed from each action's own recorded parse and pre-round
  observation (``_independently_accepted_bid``), never read from
  ``record.envelope.valid`` -- this leaf's independence does not depend on
  ``environment.py``'s own legality gate having already run correctly.
* **``aucarena_profit_vs_field`` (``comparative`` / ``head_to_head``,
  terminal-state-scoped).** The tested seat's terminal profit against the
  *named, declared* field of frozen rule-bidder seats in the same scenario
  (section 2: the comparator and pairing are part of the estimand). Declared
  for every case; scored ``invalid_measurement`` when the case's roster
  carries no field seat at all (golden 5, ``verifier_taxonomy.md`` section 9:
  "An invalid or missing observation must not be scored as an economic
  zero... The receipt reports ``invalid_measurement``.").

Every scorer here is provider-free and judge-free: none of the four leaves
is ``evaluation_class="judge_dependent"`` (spec section 2 -- all four are
``"deterministic"`` in this family's scripted-rule-bidder scope), so there is
no judge-dependent component to separately label in this family, unlike
``tau3_retail``.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

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
from aeread.shared_runner.task.scheduler import EpisodeResult, PhaseInstance

from . import _vendored_upstream as vendored

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "aucarena_base_v1"
DOMAIN_VERSION = "1.0.0"

BUDGET_INVARIANT_ESTIMAND_ID = "aucarena_budget_invariant"
BUDGET_INVARIANT_LEAF_ID = "aucarena_budget_invariant_leaf"
BUDGET_INVARIANT_REFERENCE_ID = "aucarena_budget_invariant_rule"
BUDGET_INVARIANT_SCORER_ID = "aucarena_budget_invariant_scorer"

BID_LEGALITY_ESTIMAND_ID = "aucarena_bid_legality"
BID_LEGALITY_LEAF_ID = "aucarena_bid_legality_leaf"
BID_LEGALITY_REFERENCE_ID = "aucarena_bid_legality_rule"
BID_LEGALITY_SCORER_ID = "aucarena_bid_legality_scorer"

HAMMER_RULE_ESTIMAND_ID = "aucarena_hammer_rule"
HAMMER_RULE_LEAF_ID = "aucarena_hammer_rule_leaf"
HAMMER_RULE_REFERENCE_ID = "aucarena_hammer_rule_trace"
HAMMER_RULE_SCORER_ID = "aucarena_hammer_rule_scorer"

PROFIT_VS_FIELD_ESTIMAND_ID = "aucarena_profit_vs_field"
PROFIT_VS_FIELD_LEAF_ID = "aucarena_profit_vs_field_leaf"
PROFIT_VS_FIELD_REFERENCE_ID = "aucarena_frozen_field_v1"
PROFIT_VS_FIELD_SCORER_ID = "aucarena_profit_vs_field_scorer"

DEFAULT_TESTED_SEAT_ID = "agent"


class AucArenaMeasurementError(RuntimeError):
    """Independent verification disagreed with the environment's own record.

    This is an adapter-defect signal, never an ordinary scoring outcome:
    ``docs/aucarena_adapter_spec.md`` section 3 / ``verifier_taxonomy.md``
    section 13's P21 row both require "environment enforcement and
    independent verification" to be computed on genuinely separate code
    paths and to agree. If they ever disagree, the bug is in this adapter
    (either ``environment.py``'s own legality/hammer application or this
    module's independent recompute), not in the case under test -- so this
    raises loudly rather than reporting a receipt.
    """


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail.measurement``'s identical helper: the pinned file
    is whichever module actually performs the referenced step, so the pin
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
        schema_ref="aucarena_base_v1/case_payload",
        predicate=_implementation("aucarena_base_domain_predicate", "environment.py"),
    )


# ---------------------------------------------------------------------------
# Leaf declarations.
# ---------------------------------------------------------------------------


def build_budget_invariant_leaf() -> MeasurementLeafSpec:
    """Leaf: no seat's budget goes negative at any recorded state.

    ``reference.source_sha256`` pins the vendored rule source itself
    (``_vendored_upstream.py``) -- there is no separate data object to pin;
    the rule *is* the reference (mirrors the pattern of pinning a rubric or
    a gold database, applied to a vendored predicate instead).
    """
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=BUDGET_INVARIANT_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=BUDGET_INVARIANT_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="state_invariant",
        input_scope="trajectory",
        units="pass",
        source_sha256=_file_sha256("_vendored_upstream.py"),
        implementation=_implementation(
            "aucarena_budget_invariant_state_check", "_vendored_upstream.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=BUDGET_INVARIANT_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(BUDGET_INVARIANT_SCORER_ID, "measurement.py"),
    )


def build_bid_legality_leaf() -> MeasurementLeafSpec:
    """Leaf: every recorded non-withdraw bid meets vendored ``bid_sanity_check``."""
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
        source_sha256=_file_sha256("_vendored_upstream.py"),
        implementation=_implementation(
            "aucarena_bid_legality_independent_check", "_vendored_upstream.py"
        ),
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


def build_hammer_rule_leaf() -> MeasurementLeafSpec:
    """Leaf: sold/unsold + winner/price match the vendored trace, in order."""
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=HAMMER_RULE_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=HAMMER_RULE_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="temporal_property",
        input_scope="trajectory",
        units="pass",
        source_sha256=_file_sha256("_vendored_upstream.py"),
        implementation=_implementation(
            "aucarena_hammer_rule_independent_replay", "_vendored_upstream.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="rule_constraint",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=HAMMER_RULE_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(HAMMER_RULE_SCORER_ID, "measurement.py"),
    )


def _field_roster_sha256(
    field_seats: Sequence[Mapping[str, Any]], item_ids: Sequence[Any] = ()
) -> str:
    """Pin the frozen field (seat ids, model_name, budgets) *and* this
    case's item order -- both are declared part of the estimand (spec
    section 2: "the frozen bidder field ... and the pairing (same
    ``case_id``, same item order, same ``world_seed``) are part of the
    estimand"). Two cases with the same field but a different item order
    (a genuinely different matchup) now hash differently.

    ``case_id``/``world_seed`` are *not* included: ``build_scorer`` is
    called with only a bare ``family_case`` payload (the kernel's own
    ``plugin.build_scorer(family_case)`` calling convention never passes a
    ``cell``, and ``case_id``/``world_seed`` both live on the outer
    ``CaseManifest``/``PlanCell``, not inside ``payload``), so neither is
    reachable from here without a kernel signature change. That half of the
    pairing identity is tracked at the outer kernel bookkeeping layer
    instead (``cell_id``/``case_id`` already on the receipt) -- see
    ``docs/aucarena_codex_triage.md`` Finding 6 and
    ``docs/aucarena_adapter_spec.md`` section 2's own narrower restatement.
    """
    payload = {
        "field": [
            {
                "seat_id": seat["seat_id"],
                "model_name": seat["model_name"],
                "budget": seat["budget"],
            }
            for seat in field_seats
        ],
        "item_order": list(item_ids),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def build_profit_vs_field_leaf(
    field_seats: Sequence[Mapping[str, Any]], item_ids: Sequence[Any] = ()
) -> MeasurementLeafSpec:
    """Leaf: tested seat's terminal profit against the declared field.

    Always declared, even when ``field_seats`` is empty (golden 5) -- the
    *leaf* is unconditional (spec section 2: "Four leaves"); only the
    *score* becomes ``invalid_measurement`` for an empty field
    (:func:`score_profit_vs_field`).
    """
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=PROFIT_VS_FIELD_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="maximize",
        units="usd",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=PROFIT_VS_FIELD_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="head_to_head",
        input_scope="terminal_state",
        units="usd",
        source_sha256=_field_roster_sha256(field_seats, item_ids),
        implementation=_implementation(
            "aucarena_profit_vs_field_delta", "measurement.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=PROFIT_VS_FIELD_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(PROFIT_VS_FIELD_SCORER_ID, "measurement.py"),
    )


def build_leaves(
    field_seats: Sequence[Mapping[str, Any]], item_ids: Sequence[Any] = ()
) -> tuple[MeasurementLeafSpec, ...]:
    """The four leaves this family always declares (spec section 2)."""
    return (
        build_budget_invariant_leaf(),
        build_bid_legality_leaf(),
        build_hammer_rule_leaf(),
        build_profit_vs_field_leaf(field_seats, item_ids),
    )


# ---------------------------------------------------------------------------
# Scorers.
# ---------------------------------------------------------------------------


def _all_action_records(phase_instances: Sequence[PhaseInstance]):
    for phase_instance in phase_instances:
        yield from phase_instance.actions


def score_budget_invariant(
    leaf: MeasurementLeafSpec,
    *,
    result: EpisodeResult,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 1: no seat's budget goes negative at any recorded state.

    Checked directly against every ``TransitionResult.state`` the scheduler
    already recorded (one per bidding round) -- never a re-derivation of the
    auction policy, only a read of already-computed state.
    """
    violations: dict[str, MetricValue] = {}
    for phase_instance in result.phase_instances:
        for transition in phase_instance.transitions:
            seats = transition.state.get("seats", {})
            for seat_id, seat in seats.items():
                budget = seat["budget"]
                if budget < 0:
                    key = f"{phase_instance.phase_instance_id}_{seat_id}"
                    violations[key] = MetricValue(
                        float(budget),
                        "usd",
                        metadata={
                            "seat_id": seat_id,
                            "phase_instance_id": phase_instance.phase_instance_id,
                        },
                    )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(0.0 if violations else 1.0, "pass"),
        metrics=violations,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_bid_legality(
    leaf: MeasurementLeafSpec,
    *,
    result: EpisodeResult,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 2: every recorded non-withdraw bid is independently legal.

    Recomputes vendored ``bid_sanity_check`` from each action's own frozen
    pre-round observation (``own_budget``, ``highest_bid``, ``cur_item``,
    ``min_markup_pct``) -- never by reading back ``record.legality`` itself.
    A malformed response (``record.parse.ok is False``) never reaches
    ``bid_sanity_check`` at all -- it is counted separately
    (``malformed_action_count``), never folded into an illegal-bid count nor
    silently scored as a task-quality zero (spec section 5 golden 4).
    """
    violations: dict[str, MetricValue] = {}
    malformed_count = 0
    for record in _all_action_records(result.phase_instances):
        if not record.parse.ok:
            malformed_count += 1
            continue
        bid_price = record.parse.action["bid_price"]
        if bid_price < 0:
            continue  # withdraw: not in scope ("non-withdraw bid")
        observation = record.request.observation
        fail_reason = vendored.bid_sanity_check(
            bid_price,
            observation["highest_bid"],
            observation["cur_item"]["price"],
            observation["own_budget"],
            observation["min_markup_pct"],
        )
        independent_legal = fail_reason is None
        recorded_legal = record.legality.legal if record.legality is not None else None
        if recorded_legal != independent_legal:
            raise AucArenaMeasurementError(
                f"{record.logical_action_id}: environment recorded legal="
                f"{recorded_legal!r} but independent bid_sanity_check recompute "
                f"says legal={independent_legal!r} ({fail_reason!r})"
            )
        if not independent_legal:
            violations[record.logical_action_id] = MetricValue(
                0.0,
                "pass",
                metadata={"seat_id": record.seat_id, "reason": fail_reason},
            )
    metrics: dict[str, MetricValue] = dict(violations)
    if malformed_count:
        metrics["malformed_action_count"] = MetricValue(float(malformed_count), "count")
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(0.0 if violations else 1.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def _independently_accepted_bid(record: Any) -> bool:
    """Recompute round-acceptance from the recorded parse plus a fresh
    ``bid_sanity_check`` call -- never from ``record.envelope.valid`` or
    ``record.legality`` (the environment's own accept/reject decision).

    ``environment.py.step()`` only ever appends a parsed, independently-legal
    bid to its own ``round_bids`` (malformed responses and bids that fail
    ``bid_sanity_check`` are both skipped via ``if not envelope.valid:
    continue``), so this reproduces that same partition from nothing but
    this action's own recorded parse and frozen pre-round observation --
    the same recompute ``score_bid_legality`` performs, reused here so
    ``score_hammer_rule``'s "independent" claim does not silently depend on
    ``environment.py``'s own legality gate having already run correctly
    (see ``docs/aucarena_review_claude.md`` WARNING 1).
    """
    if not record.parse.ok:
        return False
    bid_price = record.parse.action["bid_price"]
    if bid_price < 0:
        return True  # withdraw: bid_sanity_check always treats bid<0 as legal
    observation = record.request.observation
    fail_reason = vendored.bid_sanity_check(
        bid_price,
        observation["highest_bid"],
        observation["cur_item"]["price"],
        observation["own_budget"],
        observation["min_markup_pct"],
    )
    return fail_reason is None


def _recompute_round(
    *,
    round_bids: Sequence[Mapping[str, Any]],
    highest_bid: int,
    highest_bidder: Any,
    prev_round_max_bid: int,
    bid_round: int,
    enable_discount: bool,
    world_seed: int,
    item_id: int,
) -> tuple[dict[str, Any], int, Any]:
    """One round's independent ``record_bid`` + ``check_hammer`` recompute.

    ``round_bids`` must already be filtered to valid (accepted) actions, in
    the same roster/eligible order the scheduler itself processed them in --
    ``score_hammer_rule`` builds it that way from ``PhaseInstance.actions``.
    """
    call_index = 0
    accumulated: list[dict[str, Any]] = []
    for entry in round_bids:
        accumulated.append(entry)
        rng = random.Random(f"{world_seed}_{item_id}_{bid_round}_{call_index}")
        call_index += 1
        highest_bid, highest_bidder = vendored.record_bid(
            accumulated, highest_bid, highest_bidder, rng=rng
        )
    num_bid = vendored._num_bids_in_round(accumulated)
    hammer = vendored.check_hammer(
        highest_bidder_is_none=highest_bidder is None,
        num_bid_this_round=num_bid,
        bid_round=bid_round,
        enable_discount=enable_discount,
        prev_round_max_bid=prev_round_max_bid,
        highest_bid=highest_bid,
    )
    return hammer, highest_bid, highest_bidder


def score_hammer_rule(
    leaf: MeasurementLeafSpec,
    *,
    result: EpisodeResult,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 3: sold/unsold + winner/price match the vendored trace, in order.

    Independently replays ``record_bid``/``check_hammer`` per round from
    nothing but ``PhaseInstance.actions`` (the recorded per-round bid
    attempts) and ``result.final_state["world_seed"]`` -- never from
    ``environment.py``'s own live state -- then compares the replay's
    sold/winner/hammer_price against the environment's own recorded
    ``TransitionResult.consequences``, item by item, round by round, in
    order. This is the component parity check the spec's test plan calls
    for: two independent computations of the same vendored rule, over the
    same trajectory, must agree. A disagreement raises
    :class:`AucArenaMeasurementError` immediately (see this module's
    docstring) rather than being folded into a soft failing score -- so a
    successful return always means every recorded round matched exactly and
    this leaf's ``primary`` is unconditionally ``1.0``.

    The round's accept/reject partition itself is independently recomputed
    too (``_independently_accepted_bid``), never read from
    ``record.envelope.valid`` -- so this leaf's independence does not rest
    on ``environment.py``'s own legality gate having already run correctly;
    it recomputes both *which* bids counted and *what they resolved to*
    from nothing but the sealed episode evidence.
    """
    world_seed = result.final_state["world_seed"]
    enable_discount = result.final_state["enable_discount"]

    highest_bid = -1
    highest_bidder: Any = None
    prev_round_max_bid = -1
    current_item_id: Any = object()  # sentinel: never equals a real item id

    for phase_instance in result.phase_instances:
        transition = phase_instance.transitions[0]
        consequences = transition.consequences
        item_id = consequences["item_id"]
        bid_round = consequences["bid_round"]
        if item_id != current_item_id:
            highest_bid, highest_bidder, prev_round_max_bid = -1, None, -1
            current_item_id = item_id

        round_bids = [
            {"bidder": record.seat_id, "bid": record.parse.action["bid_price"]}
            for record in phase_instance.actions
            if _independently_accepted_bid(record)
        ]
        hammer, highest_bid, highest_bidder = _recompute_round(
            round_bids=round_bids,
            highest_bid=highest_bid,
            highest_bidder=highest_bidder,
            prev_round_max_bid=prev_round_max_bid,
            bid_round=bid_round,
            enable_discount=enable_discount,
            world_seed=world_seed,
            item_id=item_id,
        )

        # ``hammer["is_sold"]`` means "this item's fate is decided this
        # round" -- true both for a real sale *and* for a decided
        # failed-to-sell (``highest_bidder is None``); it is not the same
        # thing as ``consequences["sold"]``, which upstream/``environment.py``
        # both define as "won by somebody" (``winner is not None``). Mirror
        # that distinction exactly, the same way ``environment.py``'s own
        # ``step()`` does.
        decided = hammer["is_sold"]
        if decided:
            winner = highest_bidder
            hammer_price = highest_bid if winner is not None else None
        else:
            winner = None
            hammer_price = None
        recomputed = (decided and winner is not None, winner, hammer_price)
        recorded = (
            consequences["sold"],
            consequences.get("winner"),
            consequences.get("hammer_price"),
        )
        if recorded != recomputed:
            raise AucArenaMeasurementError(
                f"{phase_instance.phase_instance_id} (item {item_id!r}, round "
                f"{bid_round!r}): environment recorded (sold, winner, "
                f"hammer_price)={recorded!r} but independent record_bid/"
                f"check_hammer recompute says {recomputed!r}"
            )

        if not decided:
            prev_round_max_bid = hammer["prev_round_max_bid"]
        # else: the next phase_instance (if any) is a new item; the loop's
        # own item_id != current_item_id guard resets highest_bid/
        # highest_bidder/prev_round_max_bid for it.

    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "pass"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_profit_vs_field(
    leaf: MeasurementLeafSpec,
    *,
    result: EpisodeResult,
    field_seats: Sequence[Mapping[str, Any]],
    tested_seat_id: str = DEFAULT_TESTED_SEAT_ID,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 4: tested seat's terminal profit against the declared field.

    ``invalid_measurement`` (never an economic zero) when ``field_seats`` is
    empty -- golden 5's single-seat roster (``verifier_taxonomy.md`` section
    9). Otherwise reports the mean delta as ``primary`` (a single required
    number), each field seat's own recorded profit in ``reference_values``,
    and each per-opponent delta in ``metrics`` -- the per-opponent vector is
    never hidden behind the mean (spec section 5: "mixed-sign per-item"
    deltas against a multi-member field).
    """
    if not field_seats:
        return ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=ValidityReport(
                "invalid",
                reasons=(
                    "empty comparator population: this scenario's roster "
                    "declares no frozen rule-bidder field seat",
                ),
            ),
            evidence_refs=evidence_refs,
        )
    seats = result.outcome["seats"]
    tested_profit = float(seats[tested_seat_id]["profit"])
    deltas: dict[str, MetricValue] = {}
    reference_values: dict[str, MetricValue] = {}
    for seat in field_seats:
        field_seat_id = seat["seat_id"]
        field_profit = float(seats[field_seat_id]["profit"])
        reference_values[f"{field_seat_id}_profit"] = MetricValue(field_profit, "usd")
        deltas[f"delta_vs_{field_seat_id}"] = MetricValue(
            tested_profit - field_profit, "usd"
        )
    mean_field_profit = sum(
        float(seats[seat["seat_id"]]["profit"]) for seat in field_seats
    ) / len(field_seats)
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(tested_profit - mean_field_profit, "usd"),
        metrics=deltas,
        reference_values=reference_values,
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True, slots=True)
class _ScoringInputResult:
    """Adapt a ``FamilyScoringInput`` to look like the ``EpisodeResult``
    attributes this family's four named ``score_*`` methods actually read --
    ``phase_instances`` (all three trajectory-scoped leaves),
    ``outcome["seats"]`` (:func:`score_profit_vs_field`), and
    ``final_state["world_seed"]``/``["enable_discount"]``
    (:func:`score_hammer_rule`) -- nothing else. Lets ``AucArenaScorer.
    __call__`` compose the existing named methods unchanged (spec section 5:
    no new scoring logic) over exactly the argument the shared kernel's real
    calling convention supplies.

    ``FamilyScoringInput`` carries no ``final_state`` field at all
    (kernel_scoring_contract_spec.md section 1). ``world_seed``/
    ``enable_discount`` are never carried by ``scoring_input.outcome``
    either (``environment.py``'s ``outcome()`` omits both), but both are
    static: set once in ``initial_state`` and never mutated by ``step()``
    (that method's own body never assigns either key), so every recorded
    ``TransitionResult.state`` -- including the LAST one -- carries them
    unchanged. Reading them off the last replayed phase instance's last
    transition is therefore the same value ``EpisodeResult.final_state``
    itself would have carried. Ruling R3 (kernel_scoring_contract_spec.md)
    makes this safe: it is the verified re-execution's own cross-checked
    state, never independently re-derived -- a state that diverged from the
    sealed run would already have failed finalization before this scorer
    is ever called.
    """

    outcome: Mapping[str, Any]
    phase_instances: tuple[PhaseInstance, ...]
    final_state: Mapping[str, Any]

    @classmethod
    def from_scoring_input(cls, scoring_input: FamilyScoringInput) -> "_ScoringInputResult":
        last_state = scoring_input.phase_instances[-1].transitions[-1].state
        return cls(
            outcome=scoring_input.outcome,
            phase_instances=scoring_input.phase_instances,
            final_state=last_state,
        )


@dataclass(frozen=True, slots=True)
class AucArenaScorer:
    """One case's fixed set of declared leaves, plus the scorers for them.

    Mirrors ``tau3_retail.measurement.Tau3RetailScorer``'s shape (four named
    methods, one per declared leaf), each still callable directly by any
    caller holding a full ``EpisodeResult`` -- every test in this family
    does exactly that. ``__call__`` (below) is the seam
    ``task.evaluation.finalize_family_execution`` calls directly
    (``plugin.build_scorer(family_case)(scoring_input,
    evidence_refs=scoring_input.evidence_refs)``, per
    kernel_scoring_contract_spec.md section 1).
    """

    field_seats: tuple[Mapping[str, Any], ...]
    tested_seat_id: str
    leaves: tuple[MeasurementLeafSpec, ...]

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        """Score one finalized episode exactly as the production finalizer
        calls it: ``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``
        (``task.evaluation.finalize_family_execution``, per
        kernel_scoring_contract_spec.md section 1).

        Returns every one of this family's four declared finalize-time
        leaves (spec section 5) -- this family has no ``score_all``, so
        this composes the four existing named ``score_*`` methods directly;
        no new scoring logic is written here.
        ``_ScoringInputResult.from_scoring_input`` adapts ``scoring_input``
        to the one shape all four already accept (see that class's own
        docstring for exactly what each field is read for and why that is
        safe with no ``EpisodeResult`` reachable from this signature).
        """
        result = _ScoringInputResult.from_scoring_input(scoring_input)
        scores = (
            self.score_budget_invariant(result=result, evidence_refs=evidence_refs),
            self.score_bid_legality(result=result, evidence_refs=evidence_refs),
            self.score_hammer_rule(result=result, evidence_refs=evidence_refs),
            self.score_profit_vs_field(result=result, evidence_refs=evidence_refs),
        )
        return FamilyScoreSet(
            primary_leaf_id=self.profit_vs_field_leaf.leaf_id,
            scores=scores,
            admission_leaf_ids=(self.profit_vs_field_leaf.leaf_id,),
        )

    @property
    def budget_invariant_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def bid_legality_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[1]

    @property
    def hammer_rule_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[2]

    @property
    def profit_vs_field_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[3]

    def score_budget_invariant(
        self, *, result: EpisodeResult, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_budget_invariant(
            self.budget_invariant_leaf, result=result, evidence_refs=evidence_refs
        )

    def score_bid_legality(
        self, *, result: EpisodeResult, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_bid_legality(
            self.bid_legality_leaf, result=result, evidence_refs=evidence_refs
        )

    def score_hammer_rule(
        self, *, result: EpisodeResult, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_hammer_rule(
            self.hammer_rule_leaf, result=result, evidence_refs=evidence_refs
        )

    def score_profit_vs_field(
        self, *, result: EpisodeResult, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        return score_profit_vs_field(
            self.profit_vs_field_leaf,
            result=result,
            field_seats=self.field_seats,
            tested_seat_id=self.tested_seat_id,
            evidence_refs=evidence_refs,
        )


def build_scorer(
    family_case: Mapping[str, Any], *, tested_seat_id: str = DEFAULT_TESTED_SEAT_ID
) -> AucArenaScorer:
    """Build the one ``AucArenaScorer`` for a case's validated ``family_case``.

    ``field_seats`` is every roster seat other than ``tested_seat_id`` --
    for every case this spec authors, exactly the frozen ``rule`` seats
    (spec section 5), empty only for golden 5's single-seat roster.
    """
    field_seats = tuple(
        seat for seat in family_case["roster"] if seat["seat_id"] != tested_seat_id
    )
    item_ids = tuple(item["id"] for item in family_case["items"])
    return AucArenaScorer(
        field_seats=field_seats,
        tested_seat_id=tested_seat_id,
        leaves=build_leaves(field_seats, item_ids),
    )


__all__ = [
    "AucArenaMeasurementError",
    "AucArenaScorer",
    "BID_LEGALITY_ESTIMAND_ID",
    "BID_LEGALITY_LEAF_ID",
    "BUDGET_INVARIANT_ESTIMAND_ID",
    "BUDGET_INVARIANT_LEAF_ID",
    "DEFAULT_TESTED_SEAT_ID",
    "HAMMER_RULE_ESTIMAND_ID",
    "HAMMER_RULE_LEAF_ID",
    "PROFIT_VS_FIELD_ESTIMAND_ID",
    "PROFIT_VS_FIELD_LEAF_ID",
    "build_bid_legality_leaf",
    "build_budget_invariant_leaf",
    "build_hammer_rule_leaf",
    "build_leaves",
    "build_profit_vs_field_leaf",
    "build_scorer",
    "score_bid_legality",
    "score_budget_invariant",
    "score_hammer_rule",
    "score_profit_vs_field",
]
