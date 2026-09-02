"""Component parity: ``measurement.py``'s independent recompute vs the
environment's own recorded trajectory (docs/aucarena_adapter_spec.md
section 3 / ``verifier_taxonomy.md`` section 13's P21 row: "Environment
enforcement and independent verification remain distinct").

Unlike ``tau3_retail``'s ``parity.py`` (which shells out to a live, pinned
upstream checkout and compares two independently-executed trajectories),
``aucarena`` has no live external upstream process to run against: the
vendored functions in ``_vendored_upstream.py`` *are* upstream's logic,
hand-transcribed (spec section 3, "Not delegated, and why that's safe
here"). The genuine parity check for this family is therefore between two
independent *code paths* over the same sealed episode: the environment's own
``step()`` (which calls the vendored functions once, live, during the
episode) and ``measurement.py``'s ``score_bid_legality``/``score_hammer_rule``
(which call the same vendored functions again, independently, from nothing
but the recorded ``EpisodeResult`` -- never from a live reference to
``environment.py``'s internal state).

This module proves that check two ways:

1. **Positive.** Every one of the five QC Gate-2 goldens' recorded
   trajectories passes both scorers without ``AucArenaMeasurementError`` --
   the environment's own recorded legality/hammer determinations agree with
   the independent recompute on every recorded action and round.
2. **Mutation.** A hand-corrupted copy of a real episode result -- one
   recorded legality verdict or one recorded hammer consequence flipped --
   *does* raise ``AucArenaMeasurementError``. Without this, a parity check
   that always agrees could just as easily be a parity check that never
   actually compares anything (the exact failure mode
   ``ledger_entries``/project memory calls out: "skips hide unrun claims" --
   a green parity suite that never really exercised its own comparison).
"""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.scheduler import LegalityResult, run_episode
from aeread_families.aucarena import measurement as m
from aeread_families.aucarena.environment import AucArenaPlugin, family_manifest, register_plugin

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

GOLDEN_POLICIES = {
    "successful": _min_markup_policy,
    "valid_but_poor": _always_withdraw_policy,
    "invalid_unauthorized": _illegal_150_policy,
    "malformed_operational": _malformed_text_policy,
    "degenerate_reference": _always_withdraw_policy,
}


def _run(golden_name: str):
    case = _case(golden_name)
    plugin = AucArenaPlugin()
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)
    cell = _cell(case)
    harness = ScriptedAucArenaHarness(GOLDEN_POLICIES[golden_name])
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved, response_source=harness)
    )
    return result, family_case


# ---------------------------------------------------------------------------
# Positive: every golden's recorded trajectory agrees with the independent
# recompute (component parity, tau3 parity.py's pattern applied to a family
# with no live upstream process to shell out to).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("golden_name", sorted(GOLDEN_POLICIES))
def test_recorded_legality_matches_independent_bid_sanity_check_recompute(
    golden_name: str,
) -> None:
    result, family_case = _run(golden_name)
    scorer = m.build_scorer(family_case)
    scorer.score_bid_legality(result=result)  # raises AucArenaMeasurementError on mismatch


@pytest.mark.parametrize("golden_name", sorted(GOLDEN_POLICIES))
def test_recorded_hammer_trace_matches_independent_record_bid_check_hammer_recompute(
    golden_name: str,
) -> None:
    result, family_case = _run(golden_name)
    scorer = m.build_scorer(family_case)
    scorer.score_hammer_rule(result=result)  # raises AucArenaMeasurementError on mismatch


# ---------------------------------------------------------------------------
# Mutation: prove the checks above are not vacuous by corrupting one
# recorded fact and confirming the parity check actually catches it.
# ---------------------------------------------------------------------------


def test_mutated_recorded_legality_is_caught_by_the_independent_recompute() -> None:
    result, family_case = _run("successful")
    scorer = m.build_scorer(family_case)

    # golden 1's every recorded action is genuinely legal -- flip exactly one
    # to illegal (with a bogus reason) without touching its underlying bid,
    # so the *environment's* record now disagrees with what an independent
    # bid_sanity_check recompute over that same action's own observation
    # would find.
    target_phase_index, target_action_index = next(
        (p_idx, a_idx)
        for p_idx, phase_instance in enumerate(result.phase_instances)
        for a_idx, record in enumerate(phase_instance.actions)
        if record.parse.ok and record.parse.action["bid_price"] >= 0
    )
    phase_instance = result.phase_instances[target_phase_index]
    record = phase_instance.actions[target_action_index]
    assert record.legality is not None and record.legality.legal is True

    mutated_record = dataclasses.replace(
        record, legality=LegalityResult.illegal("mutation-test: forced illegal")
    )
    mutated_actions = tuple(
        mutated_record if idx == target_action_index else existing
        for idx, existing in enumerate(phase_instance.actions)
    )
    mutated_phase_instance = dataclasses.replace(phase_instance, actions=mutated_actions)
    mutated_phase_instances = tuple(
        mutated_phase_instance if idx == target_phase_index else existing
        for idx, existing in enumerate(result.phase_instances)
    )
    mutated_result = dataclasses.replace(result, phase_instances=mutated_phase_instances)

    with pytest.raises(m.AucArenaMeasurementError, match="but independent bid_sanity_check"):
        scorer.score_bid_legality(result=mutated_result)


def test_mutated_recorded_hammer_consequence_is_caught_by_the_independent_recompute() -> None:
    result, family_case = _run("invalid_unauthorized")  # one item, one round: simplest trace
    scorer = m.build_scorer(family_case)

    phase_instance = result.phase_instances[0]
    transition = phase_instance.transitions[0]
    assert transition.consequences["winner"] == "field_high"

    mutated_consequences = dict(transition.consequences)
    mutated_consequences["winner"] = "field_low"  # field_low never even bid this round
    mutated_transition = dataclasses.replace(transition, consequences=mutated_consequences)
    mutated_phase_instance = dataclasses.replace(
        phase_instance, transitions=(mutated_transition,)
    )
    mutated_result = dataclasses.replace(
        result, phase_instances=(mutated_phase_instance,) + result.phase_instances[1:]
    )

    with pytest.raises(
        m.AucArenaMeasurementError, match="but independent record_bid/check_hammer"
    ):
        scorer.score_hammer_rule(result=mutated_result)


def test_hammer_rule_does_not_silently_trust_a_forged_envelope_valid_flag() -> None:
    """``aucarena_hammer_rule`` must not depend on ``record.envelope.valid``
    for its own accept/reject partition (``docs/aucarena_review_claude.md``
    WARNING 1): a hypothetical bug in ``environment.py.legal()`` that
    incorrectly accepted an illegal bid must still be caught by this leaf
    alone, not only by ``score_bid_legality``.

    golden 3's agent bid (``150``, below the item's starting bid) is
    genuinely illegal. This forges the exact shape a buggy ``legal()`` would
    have produced -- ``envelope.valid=True`` for that same illegal bid, plus
    the recorded consequences a buggy ``step()`` would have derived from
    trusting that forged flag (including the bogus bid raises this round's
    bid count from 1 to 2, which flips ``check_hammer``'s own "won this
    round" determination from sold to unsold -- vendored
    ``check_hammer``'s own branch, not an arbitrary mutation) -- so a
    scorer that itself reads ``envelope.valid`` would find these forged
    "recorded" and "recomputed" sides in tautological agreement and never
    raise. The independent ``bid_sanity_check`` recompute this leaf now
    performs must still reject the bid on its own terms and therefore still
    disagree with the forged (unsold) consequences.
    """
    result, family_case = _run("invalid_unauthorized")
    scorer = m.build_scorer(family_case)

    phase_instance = result.phase_instances[0]
    agent_index, agent_record = next(
        (idx, record)
        for idx, record in enumerate(phase_instance.actions)
        if record.seat_id == "agent"
    )
    assert agent_record.parse.ok is True
    assert agent_record.parse.action["bid_price"] == 150
    assert agent_record.legality is not None and agent_record.legality.legal is False
    assert agent_record.envelope.valid is False

    forged_envelope = dataclasses.replace(
        agent_record.envelope, valid=True, action=agent_record.parse.action
    )
    forged_legality = LegalityResult.legal_action()
    forged_record = dataclasses.replace(
        agent_record, envelope=forged_envelope, legality=forged_legality
    )
    forged_actions = tuple(
        forged_record if idx == agent_index else existing
        for idx, existing in enumerate(phase_instance.actions)
    )

    transition = phase_instance.transitions[0]
    assert transition.consequences == {
        "item_id": 1,
        "bid_round": 0,
        "sold": True,
        "winner": "field_high",
        "hammer_price": 1000,
    }
    # What a genuinely buggy step() would have recorded had it trusted the
    # forged envelope: field_high's 1000 plus the now-"accepted" 150 raises
    # num_bid_this_round from 1 to 2, so vendored check_hammer's own
    # ``prev_round_max_bid < 0 and num_bid_this_round == 1`` branch no
    # longer applies -- the round is left undecided (unsold), exactly
    # mirroring environment.py's own unsold consequences shape (spec
    # section 3: no "winner"/"hammer_price" keys when undecided).
    forged_consequences = {"item_id": 1, "bid_round": 0, "sold": False}
    forged_transition = dataclasses.replace(transition, consequences=forged_consequences)
    forged_phase_instance = dataclasses.replace(
        phase_instance, actions=forged_actions, transitions=(forged_transition,)
    )
    forged_result = dataclasses.replace(
        result, phase_instances=(forged_phase_instance,) + result.phase_instances[1:]
    )

    with pytest.raises(
        m.AucArenaMeasurementError, match="but independent record_bid/check_hammer"
    ):
        scorer.score_hammer_rule(result=forged_result)
