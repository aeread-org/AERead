"""Tests for the ``aucarena`` measurement declarations (measurement.py).

Two kinds of coverage, mirroring ``tests/test_tau3_retail_measurement.py``'s
split:

* Leaf-declaration tests -- ``build_leaves``/``build_scorer`` construct
  without raising and match the ``verifier_family``/``reference_kind``/
  ``evaluation_class``/``input_scope``/``direction``/``units`` table in
  ``docs/aucarena_adapter_spec.md`` section 2 exactly, including the kernel's
  own ``_REFERENCE_KINDS``/``_REFERENCE_SCOPE`` acceptance (a construction
  that violated either table would raise ``MeasurementContractError``
  before this module ever ran).
* Golden-by-golden scorer tests -- one test per leaf per QC Gate-2 golden
  (section 5), run through the real kernel scheduler
  (``aeread.shared_runner.task.scheduler.run_episode``) with the same scripted
  policies ``tests/test_aucarena_environment.py`` already established, then
  scored with ``AucArenaPlugin.build_scorer``'s real scorer.

The component parity check the milestone brief calls for --
"our recorded scoring equals upstream computed scoring on the same
scripted trajectory" -- is exercised here implicitly (every golden's
``score_bid_legality``/``score_hammer_rule`` call succeeds without raising
``AucArenaMeasurementError``, i.e. the environment's own recorded legality/
hammer determinations agree with this module's independent vendored-function
recompute) and explicitly, with a mutation proving the check is real, in
``tests/test_aucarena_parity.py``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.measurement import FamilyScoreSet, MeasurementContractError
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import FamilyScoringInput
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode
from aeread_families.aucarena import measurement as m
from aeread_families.aucarena.environment import AucArenaPlugin, family_manifest, register_plugin
from aeread.shared_runner.registry import PluginRegistry

from tests.test_aucarena_environment import (
    ScriptedAucArenaHarness,
    _always_withdraw_policy,
    _case,
    _cell,
    _illegal_150_policy,
    _malformed_text_policy,
    _min_markup_policy,
)

CASES_DIR = Path("cases/aucarena/pilot")


def _run(golden_name: str, policy) -> tuple[EpisodeResult, dict[str, Any]]:
    case = _case(golden_name)
    plugin = AucArenaPlugin()
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)
    cell = _cell(case)
    harness = ScriptedAucArenaHarness(policy)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved, response_source=harness)
    )
    return result, family_case


# ---------------------------------------------------------------------------
# Leaf declaration: matches spec section 2's table exactly, always four,
# never collapsed, no objective_reference leaf.
# ---------------------------------------------------------------------------


def test_build_leaves_declares_exactly_the_four_spec_leaves() -> None:
    field_seats = ({"seat_id": "field_low", "model_name": "rule", "budget": 2000},)
    leaves = m.build_leaves(field_seats)
    assert len(leaves) == 4
    assert all(leaf.composition_kind == "leaf" for leaf in leaves)

    by_id = {leaf.leaf_id: leaf for leaf in leaves}
    assert set(by_id) == {
        m.BUDGET_INVARIANT_LEAF_ID,
        m.BID_LEGALITY_LEAF_ID,
        m.HAMMER_RULE_LEAF_ID,
        m.PROFIT_VS_FIELD_LEAF_ID,
    }

    budget = by_id[m.BUDGET_INVARIANT_LEAF_ID]
    assert budget.verifier.verifier_family == "rule_constraint"
    assert budget.verifier.reference.reference_kind == "state_invariant"
    assert budget.verifier.evaluation_class == "deterministic"
    assert budget.estimand.input_scope == "trajectory"
    assert budget.estimand.direction == "none"
    assert budget.estimand.units == "pass"

    legality = by_id[m.BID_LEGALITY_LEAF_ID]
    assert legality.verifier.verifier_family == "rule_constraint"
    assert legality.verifier.reference.reference_kind == "constraint_satisfaction"
    assert legality.verifier.evaluation_class == "deterministic"
    assert legality.estimand.input_scope == "trajectory"

    hammer = by_id[m.HAMMER_RULE_LEAF_ID]
    assert hammer.verifier.verifier_family == "rule_constraint"
    assert hammer.verifier.reference.reference_kind == "temporal_property"
    assert hammer.verifier.evaluation_class == "deterministic"
    assert hammer.estimand.input_scope == "trajectory"

    profit = by_id[m.PROFIT_VS_FIELD_LEAF_ID]
    assert profit.verifier.verifier_family == "comparative"
    assert profit.verifier.reference.reference_kind == "head_to_head"
    assert profit.verifier.evaluation_class == "deterministic"
    assert profit.estimand.input_scope == "terminal_state"
    assert profit.estimand.direction == "maximize"
    assert profit.estimand.units == "usd"


def test_no_objective_reference_leaf_is_declared() -> None:
    """Profit and TrueSkill do not solve the auction policy game (spec section 2)."""
    leaves = m.build_leaves(())
    assert all(leaf.verifier.verifier_family != "objective_reference" for leaf in leaves)


def test_profit_vs_field_leaf_is_declared_even_for_an_empty_field() -> None:
    """The leaf is unconditional; only the *score* becomes invalid_measurement."""
    leaf = m.build_profit_vs_field_leaf(())
    assert leaf.leaf_id == m.PROFIT_VS_FIELD_LEAF_ID


def test_bid_legality_reference_kind_rejected_by_a_disallowed_scope() -> None:
    """Sanity check: the kernel's own tables, not a local reimplementation, gate this."""
    from aeread.shared_runner.measurement import ReferenceSpec

    with pytest.raises(MeasurementContractError, match="does not accept input_scope"):
        ReferenceSpec(
            reference_id="aucarena_bad_reference",
            reference_version="1.0.0",
            reference_kind="temporal_property",
            input_scope="answer",  # temporal_property only accepts "trajectory"
            units="pass",
            source_sha256="0" * 64,
            implementation=m._implementation("aucarena_bad_scorer", "measurement.py"),
        )


def test_build_scorer_field_seats_excludes_the_tested_seat() -> None:
    _, family_case = _run("successful", _min_markup_policy)
    scorer = m.build_scorer(family_case)
    assert scorer.tested_seat_id == "agent"
    assert {seat["seat_id"] for seat in scorer.field_seats} == {"field_low", "field_high"}


def test_profit_vs_field_reference_hash_distinguishes_item_order_not_only_the_field() -> None:
    """``docs/aucarena_codex_triage.md`` Finding 6: the adapter spec (section
    2) declares the item order part of ``aucarena_profit_vs_field``'s
    estimand identity ("the pairing (same case_id, same item order, same
    world_seed) are part of the estimand"), but the reference hash used to
    hash only the field roster. Two cases with an identical field but a
    genuinely different matchup (item order reversed) must not collide."""
    field_seats = ({"seat_id": "field_low", "model_name": "rule", "budget": 2000},)
    leaf_forward = m.build_profit_vs_field_leaf(field_seats, item_ids=(1, 2, 3))
    leaf_reversed = m.build_profit_vs_field_leaf(field_seats, item_ids=(3, 2, 1))
    leaf_forward_again = m.build_profit_vs_field_leaf(field_seats, item_ids=(1, 2, 3))

    assert (
        leaf_forward.verifier.reference.source_sha256
        != leaf_reversed.verifier.reference.source_sha256
    )
    assert (
        leaf_forward.verifier.reference.source_sha256
        == leaf_forward_again.verifier.reference.source_sha256
    )


def test_build_scorer_reference_hash_reflects_the_real_cases_item_order() -> None:
    """End-to-end (not just the leaf builder in isolation): two validated
    ``family_case`` payloads sharing one field roster but reordering the
    same items produce different ``build_scorer(...)`` reference hashes."""
    _, family_case = _run("successful", _min_markup_policy)
    plugin = AucArenaPlugin()

    forward_payload = dict(family_case)
    reversed_payload = {
        **family_case,
        "item_ids": list(reversed(family_case["item_ids"])),
        "items": list(reversed(family_case["items"])),
    }

    forward_case = plugin.validate_payload(forward_payload)
    reversed_case = plugin.validate_payload(reversed_payload)

    forward_scorer = m.build_scorer(forward_case)
    reversed_scorer = m.build_scorer(reversed_case)

    assert (
        forward_scorer.profit_vs_field_leaf.verifier.reference.source_sha256
        != reversed_scorer.profit_vs_field_leaf.verifier.reference.source_sha256
    )


# ---------------------------------------------------------------------------
# Golden 1: successful_01.
# ---------------------------------------------------------------------------


def test_golden_1_all_rule_constraint_leaves_pass() -> None:
    result, family_case = _run("successful", _min_markup_policy)
    scorer = m.build_scorer(family_case)

    budget_score = scorer.score_budget_invariant(result=result)
    assert budget_score.primary.value == 1.0
    assert budget_score.metrics == {}

    legality_score = scorer.score_bid_legality(result=result)
    assert legality_score.primary.value == 1.0
    assert legality_score.metrics == {}

    hammer_score = scorer.score_hammer_rule(result=result)
    assert hammer_score.primary.value == 1.0


def test_golden_1_profit_vs_field_is_finite_and_mixed_sign() -> None:
    result, family_case = _run("successful", _min_markup_policy)
    scorer = m.build_scorer(family_case)
    score = scorer.score_profit_vs_field(result=result)

    assert score.status == "ok"
    # agent profit=300 (test_aucarena_environment.py's own established
    # golden-1 numbers, post Finding-4 RNG fix); field_low never wins
    # (profit 0), field_high wins items 2-4 (profit 1300).
    assert score.metrics["delta_vs_field_low"].value == 300.0
    assert score.metrics["delta_vs_field_high"].value == -1000.0
    assert score.primary.value == pytest.approx((300.0 - 1000.0) / 2.0)


_ALL_FOUR_LEAF_IDS = frozenset(
    {
        m.BUDGET_INVARIANT_LEAF_ID,
        m.BID_LEGALITY_LEAF_ID,
        m.HAMMER_RULE_LEAF_ID,
        m.PROFIT_VS_FIELD_LEAF_ID,
    }
)


def test_scorer_is_callable_and_returns_every_declared_leaf_never_just_the_primary() -> None:
    """``AucArenaScorer`` must be callable: ``task.evaluation.
    finalize_family_execution`` never calls a named method -- it calls
    whatever ``AucArenaPlugin.build_scorer`` returns *as a function*::

        score_set = plugin.build_scorer(family_case)(
            scoring_input, evidence_refs=scoring_input.evidence_refs,
        )

    (kernel_scoring_contract_spec.md section 1). Before this milestone,
    ``__call__`` took a raw ``outcome`` mapping and returned exactly ONE of
    this family's four declared leaves (``aucarena_profit_vs_field``, the
    sole leaf reachable from a bare terminal ``outcome``), silently
    dropping the other three; this test proves every declared leaf now
    comes back, from a ``FamilyScoringInput`` built off a real episode's
    own ``outcome``/``phase_instances``, never a full ``EpisodeResult``
    (which this contract's scorer signature can never receive).
    """
    result, family_case = _run("successful", _min_markup_policy)
    scorer = m.build_scorer(family_case)
    assert callable(scorer)

    scoring_input = FamilyScoringInput(
        outcome=result.outcome,
        phase_instances=result.phase_instances,
        evidence_refs=("outcome_event_1",),
    )

    score_set = scorer(scoring_input, evidence_refs=scoring_input.evidence_refs)

    assert isinstance(score_set, FamilyScoreSet)
    assert {score.leaf.leaf_id for score in score_set.scores} == set(_ALL_FOUR_LEAF_IDS)
    assert score_set.primary_leaf_id == m.PROFIT_VS_FIELD_LEAF_ID
    assert score_set.admission_leaf_ids == (m.PROFIT_VS_FIELD_LEAF_ID,)
    assert all(score.evidence_refs == ("outcome_event_1",) for score in score_set.scores)

    profit = next(s for s in score_set.scores if s.leaf.leaf_id == m.PROFIT_VS_FIELD_LEAF_ID)
    assert profit.status == "ok"
    assert profit.metrics["delta_vs_field_low"].value == 300.0
    assert profit.metrics["delta_vs_field_high"].value == -1000.0
    assert profit.primary.value == pytest.approx((300.0 - 1000.0) / 2.0)

    # Byte-identical to each leaf's own named-method call over the full
    # ``EpisodeResult`` -- ``__call__`` composes the existing named
    # ``score_*`` methods, never a second, divergent scoring path.
    assert canonical_json_bytes(profit) == canonical_json_bytes(
        scorer.score_profit_vs_field(result=result, evidence_refs=("outcome_event_1",))
    )
    budget = next(s for s in score_set.scores if s.leaf.leaf_id == m.BUDGET_INVARIANT_LEAF_ID)
    assert canonical_json_bytes(budget) == canonical_json_bytes(
        scorer.score_budget_invariant(result=result, evidence_refs=("outcome_event_1",))
    )
    legality = next(s for s in score_set.scores if s.leaf.leaf_id == m.BID_LEGALITY_LEAF_ID)
    assert canonical_json_bytes(legality) == canonical_json_bytes(
        scorer.score_bid_legality(result=result, evidence_refs=("outcome_event_1",))
    )
    hammer = next(s for s in score_set.scores if s.leaf.leaf_id == m.HAMMER_RULE_LEAF_ID)
    assert canonical_json_bytes(hammer) == canonical_json_bytes(
        scorer.score_hammer_rule(result=result, evidence_refs=("outcome_event_1",))
    )


def test_scorer_call_reports_invalid_measurement_on_the_primary_leaf_alone_for_golden_5() -> None:
    """Golden 5's degenerate (single-seat) roster leaves
    ``aucarena_profit_vs_field`` (this family's primary AND its only
    admission leaf) ``invalid_measurement`` -- never an economic zero -- while
    the three ``rule_constraint`` diagnostics still report a real, ``"ok"``
    pass, since nothing about an empty comparator population makes bid
    legality, the hammer rule, or the budget invariant unmeasurable. A
    ``FamilyScoreSet`` with a mix of ``ok`` and ``invalid_measurement``
    leaves is exactly what ``FamilyScoreSet.__post_init__`` allows (see that
    class's own docstring): only the *admission* leaves' validity should
    ever exclude a receipt.
    """
    result, family_case = _run("degenerate_reference", _always_withdraw_policy)
    scorer = m.build_scorer(family_case)

    scoring_input = FamilyScoringInput(
        outcome=result.outcome,
        phase_instances=result.phase_instances,
        evidence_refs=("outcome_event_2",),
    )
    score_set = scorer(scoring_input, evidence_refs=scoring_input.evidence_refs)

    assert {score.leaf.leaf_id for score in score_set.scores} == set(_ALL_FOUR_LEAF_IDS)
    assert score_set.primary_leaf_id == m.PROFIT_VS_FIELD_LEAF_ID
    assert score_set.invalid_admission_leaf_ids == (m.PROFIT_VS_FIELD_LEAF_ID,)

    profit = next(s for s in score_set.scores if s.leaf.leaf_id == m.PROFIT_VS_FIELD_LEAF_ID)
    assert profit.status == "invalid_measurement"
    assert profit.primary is None

    for leaf_id in (m.BUDGET_INVARIANT_LEAF_ID, m.BID_LEGALITY_LEAF_ID, m.HAMMER_RULE_LEAF_ID):
        diagnostic = next(s for s in score_set.scores if s.leaf.leaf_id == leaf_id)
        assert diagnostic.status == "ok"
        assert diagnostic.primary.value == 1.0


# ---------------------------------------------------------------------------
# Golden 2: valid_but_poor_01.
# ---------------------------------------------------------------------------


def test_golden_2_rule_constraint_leaves_pass_trivially() -> None:
    result, family_case = _run("valid_but_poor", _always_withdraw_policy)
    scorer = m.build_scorer(family_case)

    assert scorer.score_budget_invariant(result=result).primary.value == 1.0
    legality_score = scorer.score_bid_legality(result=result)
    assert legality_score.primary.value == 1.0
    assert legality_score.metrics == {}
    assert scorer.score_hammer_rule(result=result).primary.value == 1.0


def test_golden_2_profit_vs_field_is_negative() -> None:
    result, family_case = _run("valid_but_poor", _always_withdraw_policy)
    scorer = m.build_scorer(family_case)
    score = scorer.score_profit_vs_field(result=result)

    assert score.status == "ok"
    assert score.primary.value < 0.0
    # field_low never wins regardless of scenario (max_bid_cnt=0); the
    # field's real earner here is field_high, uncontested on every item.
    assert score.metrics["delta_vs_field_low"].value == 0.0
    assert score.metrics["delta_vs_field_high"].value < 0.0


# ---------------------------------------------------------------------------
# Golden 3: invalid_unauthorized_01 -- must change no protected state and
# earn no credit, and aucarena_bid_legality must record the failure.
# ---------------------------------------------------------------------------


def test_golden_3_bid_legality_records_the_illegal_bid_keyed_to_its_action_id() -> None:
    result, family_case = _run("invalid_unauthorized", _illegal_150_policy)
    scorer = m.build_scorer(family_case)
    score = scorer.score_bid_legality(result=result)

    assert score.primary.value == 0.0
    assert len(score.metrics) == 1
    ((action_id, violation),) = score.metrics.items()
    assert violation.metadata["seat_id"] == "agent"
    assert "lower than the starting bid" in violation.metadata["reason"]

    # Cross-check the key really is a real logical_action_id belonging to
    # agent's one recorded attempt this episode.
    agent_records = [
        record
        for phase_instance in result.phase_instances
        for record in phase_instance.actions
        if record.seat_id == "agent"
    ]
    assert len(agent_records) == 1
    assert action_id == agent_records[0].logical_action_id


def test_golden_3_other_rule_constraint_leaves_still_pass() -> None:
    """The illegal attempt never mutated state, so the other two leaves are clean."""
    result, family_case = _run("invalid_unauthorized", _illegal_150_policy)
    scorer = m.build_scorer(family_case)
    assert scorer.score_budget_invariant(result=result).primary.value == 1.0
    assert scorer.score_hammer_rule(result=result).primary.value == 1.0


def test_golden_3_earns_no_credit() -> None:
    result, family_case = _run("invalid_unauthorized", _illegal_150_policy)
    scorer = m.build_scorer(family_case)
    score = scorer.score_profit_vs_field(result=result)
    assert score.status == "ok"
    assert score.primary.value < 0.0


# ---------------------------------------------------------------------------
# Golden 4: malformed_operational_01 -- typed invalidity, never a
# task-quality zero folded into the legality leaf, on a distinct code path
# from golden 3.
# ---------------------------------------------------------------------------


def test_golden_4_malformed_action_is_not_counted_as_an_illegal_bid() -> None:
    result, family_case = _run("malformed_operational", _malformed_text_policy)
    scorer = m.build_scorer(family_case)
    score = scorer.score_bid_legality(result=result)

    assert score.primary.value == 1.0  # never folded into a legality failure
    assert score.metrics["malformed_action_count"].value == 1.0
    assert not any(key != "malformed_action_count" for key in score.metrics)


def test_golden_4_other_leaves_match_golden_3_outcome() -> None:
    """Same uncontested-field-win outcome as golden 3, reached via a distinct path."""
    result3, family_case3 = _run("invalid_unauthorized", _illegal_150_policy)
    result4, family_case4 = _run("malformed_operational", _malformed_text_policy)
    scorer3 = m.build_scorer(family_case3)
    scorer4 = m.build_scorer(family_case4)

    assert (
        scorer3.score_hammer_rule(result=result3).primary.value
        == scorer4.score_hammer_rule(result=result4).primary.value
        == 1.0
    )
    profit3 = scorer3.score_profit_vs_field(result=result3)
    profit4 = scorer4.score_profit_vs_field(result=result4)
    assert profit3.primary.value == profit4.primary.value


# ---------------------------------------------------------------------------
# Golden 5: degenerate_reference_01 -- empty comparator population ->
# invalid_measurement, never an economic zero; other leaves pass trivially.
# ---------------------------------------------------------------------------


def test_golden_5_profit_vs_field_is_invalid_measurement_not_zero() -> None:
    result, family_case = _run("degenerate_reference", _always_withdraw_policy)
    scorer = m.build_scorer(family_case)
    assert scorer.field_seats == ()

    score = scorer.score_profit_vs_field(result=result)
    assert score.status == "invalid_measurement"
    assert score.primary is None
    assert score.validity.status == "invalid"
    assert score.validity.reasons


def test_golden_5_rule_constraint_leaves_pass_trivially() -> None:
    result, family_case = _run("degenerate_reference", _always_withdraw_policy)
    scorer = m.build_scorer(family_case)
    assert scorer.score_budget_invariant(result=result).primary.value == 1.0
    assert scorer.score_bid_legality(result=result).primary.value == 1.0
    assert scorer.score_hammer_rule(result=result).primary.value == 1.0
