"""QC Gate-2 goldens and leaf-declaration coverage for termsbench's 4
measurement leaves (docs/termsbench_adapter_spec.md sections 2 and 4).

There is no upstream binary to replay against (dead repository link), so
parity here is **formula-level** (spec section 5): every golden below is
asserted once via ``measurement.py``'s scorer and once via an independently
written re-derivation of the same cited paper equation, shown inline in
comments. Goldens 1, 3, 4, and 5 run the real ``TermsBenchPlugin`` + the
scripted/kernel harness end to end (mirroring
``tests/test_termsbench_environment.py``'s own golden tests) so the scorer
is exercised against a genuine ``EpisodeResult.outcome``, never a hand-typed
mock of it. Golden 2 is explicitly exempted by its own spec text ("this
golden isolates the *scorer*, not the RNG") and constructs its terminal
outcome directly.
"""
from __future__ import annotations

import asyncio
from types import MappingProxyType
from typing import Any

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.termsbench import cases as tb_cases
from aeread_families.termsbench import measurement as m
from aeread_families.termsbench.environment import TermsBenchPlugin, register_plugin
from aeread_families.termsbench.harness import ScriptedTermsBenchHarness

# ---------------------------------------------------------------------------
# Common setup (spec section 4): p_min=0, p_max=200 (R=200), agent role=buyer,
# r_A=150, r_B=100 (Delta=50), family=Candid, eta_B=neutral, kappa_B=0.5,
# K=10, round k=1.
# ---------------------------------------------------------------------------


def _common_setup_payload(*, regime: str, chi: str, r_a: float, r_b: float) -> dict[str, Any]:
    return {
        "regime": regime,
        "family": "candid",
        "horizon": 10,
        "agent": {"role": "buyer", "r_a": r_a, "kappa_a": 0.5},
        "t_b": {"r_b": r_b, "kappa_b": 0.5, "eta_b": "neutral"},
        "counterpart_role": "seller",
        "chi": chi,
        "price_bounds": {"p_min": 0.0, "p_max": 200.0},
        "opening_harshness": 0.5,
        "geometry_percentile": 0.5,
        "delta": r_a - r_b,
        "difficulty_score": 0.5,
        "hyperparameters": {},
    }


def _common_setup_case(
    *, regime: str = "overlap", chi: str, r_a: float = 150.0, r_b: float = 100.0, world_seed: int
) -> CaseManifest:
    """Wrap the hand-picked common-setup payload in a full CaseManifest,
    reusing ``cases.build_case``'s own structure/digest machinery so this
    round-trips through the strict R1 grammar exactly like a generated case."""
    data = tb_cases.build_case("candid", "overlap", world_seed)
    data["payload"] = _common_setup_payload(regime=regime, chi=chi, r_a=r_a, r_b=r_b)
    data["content_sha256"] = "0" * 64
    data["content_sha256"] = case_content_sha256(data)
    return CaseManifest.from_dict(data)


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_termsbench_measurement",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_termsbench_measurement",
        suite_version="0.1.0",
        block_id="block_termsbench_measurement",
        sampling_plan_id="sampling_termsbench_measurement",
        analysis_plan_id="analysis_termsbench_measurement",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_termsbench_measurement",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"agent": "scripted_agent", "counterpart": "termsbench_counterpart_kernel_v1"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run(case: CaseManifest, harness: ScriptedTermsBenchHarness):
    registry = PluginRegistry()
    plugin = register_plugin(registry, regime=case.payload["regime"])
    return asyncio.run(run_episode(cell=_cell(case), case=case, plugin=plugin, response_source=harness))


def _scorer_for(case: CaseManifest) -> m.TermsBenchScorer:
    plugin = TermsBenchPlugin(regime=case.payload["regime"])
    family_case = plugin.validate_payload(case.payload)
    return m.build_scorer(family_case)


# ---------------------------------------------------------------------------
# Leaf-declaration rules (spec section 2's verifier table).
# ---------------------------------------------------------------------------


def test_overlap_case_declares_surplus_efficiency_feasible_agreement_and_protocol_compliance() -> None:
    payload = _common_setup_payload(regime="overlap", chi="agent_opens", r_a=150.0, r_b=100.0)
    leaves = m.build_leaves(payload)
    assert [leaf.leaf_id for leaf in leaves] == [
        m.SURPLUS_EFFICIENCY_LEAF_ID,
        m.FEASIBLE_AGREEMENT_LEAF_ID,
        m.PROTOCOL_COMPLIANCE_LEAF_ID,
    ]


def test_nodeal_case_declares_no_deal_agreement_and_protocol_compliance_only() -> None:
    payload = _common_setup_payload(regime="nodeal", chi="agent_opens", r_a=100.0, r_b=150.0)
    leaves = m.build_leaves(payload)
    assert [leaf.leaf_id for leaf in leaves] == [
        m.NO_DEAL_AGREEMENT_LEAF_ID,
        m.PROTOCOL_COMPLIANCE_LEAF_ID,
    ]


def test_leaf_families_and_directions_match_the_spec_verifier_table() -> None:
    overlap_payload = _common_setup_payload(regime="overlap", chi="agent_opens", r_a=150.0, r_b=100.0)
    se_leaf, agr_leaf, cv_leaf = m.build_leaves(overlap_payload)

    assert se_leaf.verifier.verifier_family == "comparative"
    assert se_leaf.verifier.reference.reference_kind == "head_to_head"
    assert se_leaf.estimand.direction == "maximize"
    assert se_leaf.estimand.input_scope == "terminal_state"

    assert agr_leaf.verifier.verifier_family == "comparative"
    assert agr_leaf.verifier.reference.reference_kind == "head_to_head"
    assert agr_leaf.estimand.direction == "maximize"

    assert cv_leaf.verifier.verifier_family == "rule_constraint"
    assert cv_leaf.verifier.reference.reference_kind == "constraint_satisfaction"
    assert cv_leaf.estimand.direction == "minimize"
    assert cv_leaf.estimand.input_scope == "trajectory"

    nodeal_payload = _common_setup_payload(regime="nodeal", chi="agent_opens", r_a=100.0, r_b=150.0)
    no_deal_leaf, _cv_leaf2 = m.build_leaves(nodeal_payload)
    assert no_deal_leaf.verifier.verifier_family == "comparative"
    assert no_deal_leaf.verifier.reference.reference_kind == "head_to_head"
    assert no_deal_leaf.estimand.direction == "minimize"

    # All 4 leaves are deterministic per realized episode (spec section 2):
    # the counterpart kernel is stochastic within an episode, but a sealed
    # world_seed realization is scored deterministically from logged actions.
    for leaf in (se_leaf, agr_leaf, cv_leaf, no_deal_leaf):
        assert leaf.verifier.evaluation_class == "deterministic"
        assert leaf.composition_kind == "leaf"


def test_protocol_compliance_reference_hash_changes_with_the_agent_ir_anchor() -> None:
    """``_case_constants_sha256``'s docstring claims it pins "price bounds,
    agent role/IR anchor, and horizon"; the IR anchor is ``agent["r_a"]``,
    the value ``environment.py``'s ``_step_agent`` individual-rationality
    check tests against. Two payloads sharing ``price_bounds``/
    ``agent_role``/``horizon`` but differing only in ``r_a`` (which happens
    routinely -- ``r_a`` is drawn per-seed in ``cases.generate_payload``)
    must get different reference hashes, or the hash cannot do its job of
    letting a consumer detect "the rule set this leaf was checked against
    changed"."""
    payload_a = _common_setup_payload(regime="overlap", chi="agent_opens", r_a=150.0, r_b=100.0)
    payload_b = _common_setup_payload(regime="overlap", chi="agent_opens", r_a=50.0, r_b=100.0)

    leaf_a = m.build_protocol_compliance_leaf(payload_a)
    leaf_b = m.build_protocol_compliance_leaf(payload_b)

    assert leaf_a.verifier.reference.source_sha256 != leaf_b.verifier.reference.source_sha256


def test_plugin_build_scorer_hook_returns_the_same_leaves_as_measurement_py() -> None:
    payload = _common_setup_payload(regime="overlap", chi="agent_opens", r_a=150.0, r_b=100.0)
    plugin = TermsBenchPlugin(regime="overlap")
    family_case = plugin.validate_payload(payload)

    scorer = plugin.build_scorer(family_case)

    expected = m.build_leaves(family_case)
    assert tuple(leaf.leaf_id for leaf in scorer.leaves) == tuple(leaf.leaf_id for leaf in expected)


# ---------------------------------------------------------------------------
# Golden 1 (spec section 4): successful agreement. Exercises leaves 1, 2, 4.
# ---------------------------------------------------------------------------


def test_golden1_successful_agreement() -> None:
    """Delta_bar_1 = (110-100)/200 = 0.05 (eq. 5's unnumbered display).
    D_tilde_1 = sqrt(1/10) = 0.3162, D_tilde_bar_1 = 0.6838 (eq. above eq. 5).
    g_theta = 6(0.05) + 1(0.5) - 2(0.6838) + 0 + 0 = 0.3+0.5-1.3675 = -0.5675
    (eq. 6). a_1 = sigmoid(-0.5675) = 0.3618 (eq. 5). Counterpart RNG stub
    u=0.10 < a_1 -> realized Accept. f=110 (termination case 3, App. B.3).
    u_A(f) = r_A-f = 150-110 = 40; SE+ = 40/50 = 0.8 (eq. 56). AGR+ = 1
    (eq. 57). CritViol% = 0: 110 in [0,200] and 110 < r_A=150 (eq. 66).
    """
    case = _common_setup_case(chi="agent_opens", world_seed=1000046)
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed,
        script=[{"decision": "offer", "price": 110.0, "message": "opening"}],
        counterpart_draws_by_round={1: {"u_accept": 0.10, "sentiment_noise": 0.0}},
    )
    result = _run(case, harness)
    assert result.terminal["reason"] == "counterpart_accept"
    assert result.terminal["final_price"] == pytest.approx(110.0)

    scorer = _scorer_for(case)
    se = scorer.score_surplus_efficiency(outcome=result.outcome)
    agr = scorer.score_feasible_agreement(outcome=result.outcome)
    cv = scorer.score_protocol_compliance(outcome=result.outcome)

    assert se.status == "ok"
    assert se.primary.unit == "zopa_fraction"
    assert se.primary.value == pytest.approx(0.8, abs=1e-9)
    # Independent re-derivation: u_A(f)/Delta computed directly from the
    # golden's own numbers, not by calling any adapter code.
    assert se.primary.value == pytest.approx((150.0 - 110.0) / 50.0, abs=1e-9)

    assert agr.status == "ok"
    assert agr.primary.value == 1.0

    assert cv.status == "ok"
    assert cv.primary.value == 0.0
    assert cv.metrics["price_bound_violation"].value == 0.0
    assert cv.metrics["individual_rationality_violation"].value == 0.0
    assert cv.metrics["invalid_action_violation"].value == 0.0


# ---------------------------------------------------------------------------
# Golden 2 (spec section 4): valid but poor. Isolates the *scorer*, not the
# RNG -- the counterpart's prior offer is pinned directly as fixture input,
# bypassing the stochastic kernel entirely, exactly as the spec text directs.
# ---------------------------------------------------------------------------


def test_golden2_valid_but_poor_surplus_stays_valid_and_unclipped() -> None:
    """Counterpart's prior offer is pinned at p=145; agent accepts. f=145,
    u_A(f) = 150-145 = 5, SE+ = 5/50 = 0.10 (eq. 56) -- legal, positive, but
    poor surplus. Per Gate 2, the low-quality outcome stays valid and
    preserves the component (surplus reported honestly, never clipped or
    flagged invalid). CritViol% = 0: 145 in [0,200] and 145 < r_A=150.
    """
    payload = _common_setup_payload(regime="overlap", chi="counterpart_opens", r_a=150.0, r_b=100.0)
    outcome = {
        "termination_reason": "agent_accept",
        "final_price": 145.0,
        "rounds_used": 1,
        "critical_violations": {
            "price_bound": False,
            "individual_rationality": False,
            "invalid_action": False,
        },
        "secondary_violations": {"monotonicity": False, "turn_budget": False},
        "malformed_action_schema": False,
        "regime": "overlap",
        "family": "candid",
        "agent_role": "buyer",
        "r_a": 150.0,
        "delta": 50.0,
    }

    scorer = m.build_scorer(payload)
    se = scorer.score_surplus_efficiency(outcome=outcome)
    cv = scorer.score_protocol_compliance(outcome=outcome)

    assert se.status == "ok"
    assert se.validity.status == "valid"
    assert se.primary.value == pytest.approx(0.10, abs=1e-9)
    # Independent re-derivation.
    assert se.primary.value == pytest.approx((150.0 - 145.0) / 50.0, abs=1e-9)

    assert cv.primary.value == 0.0


# ---------------------------------------------------------------------------
# Golden 3 (spec section 4): invalid/unauthorized Accept with no counterpart
# offer observed. Must change no protected state and earn no credit -- a
# *valid* 0, never an invalid_measurement (that is golden 4's case).
# ---------------------------------------------------------------------------


def test_golden3_invalid_unauthorized_accept_earns_no_credit_but_stays_valid() -> None:
    """Round 1, chi=AgentOpens, agent's first action is Accept with no
    counterpart offer yet observed -- App. F.4's invalid-action case,
    resolved as AgreementViolation (App. C.2.3) with f=bot. u_A(bot)=0 by
    definition -> SE+ = 0/50 = 0 (eq. 56); AGR+ = 0, "no positive credit for
    an unauthorized action" (eq. 57). CritViol% = 1, the InvalidAct%
    component of eq. 66. No protected state (price, DB) is touched.
    """
    case = _common_setup_case(chi="agent_opens", world_seed=1000046)
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed,
        script=[{"decision": "accept", "price": None, "message": "premature"}],
    )
    result = _run(case, harness)
    assert result.terminal["reason"] == "agreement_violation"
    assert result.terminal["final_price"] is None
    assert result.terminal["malformed_action_schema"] is False
    assert result.terminal["critical_violations"]["invalid_action"] is True
    # The invariant golden 3 exists to demonstrate: "no protected state
    # (price, DB) is touched" is the ledger, not just the terminal reason.
    assert result.final_state["round"] == 1
    assert result.final_state["agent_offers"] == ()
    assert result.final_state["counterpart_offers"] == ()
    assert result.final_state["transcript"] == ()

    scorer = _scorer_for(case)
    se = scorer.score_surplus_efficiency(outcome=result.outcome)
    agr = scorer.score_feasible_agreement(outcome=result.outcome)
    cv = scorer.score_protocol_compliance(outcome=result.outcome)

    assert se.status == "ok"
    assert se.validity.status == "valid"
    assert se.primary.value == pytest.approx(0.0 / 50.0, abs=1e-9)

    assert agr.status == "ok"
    assert agr.primary.value == 0.0

    assert cv.status == "ok"
    assert cv.primary.value == 1.0
    assert cv.metrics["invalid_action_violation"].value == 1.0


# ---------------------------------------------------------------------------
# Golden 4 (spec section 4): malformed/operational. Leaves 1-2 are typed
# invalid_measurement and excluded from the SE+/AGR+ denominator -- never
# scored as an economic zero -- while leaf 4 still records the violation.
# ---------------------------------------------------------------------------


def test_golden4_malformed_action_is_invalid_measurement_for_value_axis_but_scored_for_compliance() -> None:
    """The agent's raw round-1 response fails to parse into {d_k,p_k,l_k}.
    Per Section F.4 ("if the malformed output prevents recovery of a valid
    economic action, it is also counted as an invalid-action violation"),
    the episode is typed invalid_measurement at the receipt layer for the
    value-axis leaves (SE+/AGR+), while CritViol%'s InvalidAct% component
    still records 1 -- the paper's own convention double-counts unrecoverable
    schema failure as both "missing" for value axes and "positive" for
    compliance.
    """
    case = _common_setup_case(chi="agent_opens", world_seed=1000046)
    harness = ScriptedTermsBenchHarness(world_seed=case.world_seed, script=[{"nonsense": True}])
    result = _run(case, harness)
    assert result.terminal["reason"] == "agreement_violation"
    assert result.terminal["malformed_action_schema"] is True
    assert result.terminal["critical_violations"]["invalid_action"] is True

    scorer = _scorer_for(case)
    se = scorer.score_surplus_efficiency(outcome=result.outcome)
    agr = scorer.score_feasible_agreement(outcome=result.outcome)
    cv = scorer.score_protocol_compliance(outcome=result.outcome)

    assert se.status == "invalid_measurement"
    assert se.primary is None
    assert se.validity.status == "invalid"
    assert se.validity.reasons == ("malformed_action_schema",)

    assert agr.status == "invalid_measurement"
    assert agr.primary is None
    assert agr.validity.status == "invalid"

    assert cv.status == "ok"
    assert cv.primary.value == 1.0
    assert cv.metrics["invalid_action_violation"].value == 1.0
    assert cv.metrics["malformed_action_schema"].value == 1.0


# ---------------------------------------------------------------------------
# Golden 5 (spec section 4): degenerate reference. AGR+ = 0 across the cell
# -> A+ = empty set -> CSE+ is reported undefined, never imputed as 0. The
# product identity SE+=AGR+*CSE+ is vacuous here and not asserted.
# ---------------------------------------------------------------------------


def test_golden5_degenerate_reference_reports_cse_plus_as_undefined_not_zero() -> None:
    """5 scripted episodes, all Overlap (Delta_i=50>0), agent script =
    immediate Reject in round 1 for all 5 -> f_i=bot for all i.
    SE+ = (1/5) * sum(0/Delta_i) = 0 (eq. 56, disagreement contributes 0,
    well-defined). AGR+ = 0/5 = 0 (eq. 57) -> A+ = empty set -> CSE+ is
    undefined (eq. 58's own text), never imputed as 0.
    """
    se_agr_pairs = []
    for world_seed in (1000046, 1000047, 1000048, 1000049, 1000050):
        case = _common_setup_case(chi="agent_opens", world_seed=world_seed)
        harness = ScriptedTermsBenchHarness(
            world_seed=case.world_seed,
            script=[{"decision": "reject", "price": None, "message": "no deal"}],
        )
        result = _run(case, harness)
        assert result.terminal["reason"] == "agent_reject"
        assert result.terminal["final_price"] is None

        scorer = _scorer_for(case)
        se = scorer.score_surplus_efficiency(outcome=result.outcome)
        agr = scorer.score_feasible_agreement(outcome=result.outcome)
        assert se.status == "ok"
        assert se.primary.value == pytest.approx(0.0, abs=1e-9)
        assert agr.status == "ok"
        assert agr.primary.value == 0.0
        se_agr_pairs.append((se, agr))

    aggregate = m.aggregate_surplus_efficiency_corpus(se_agr_pairs)
    assert aggregate["SE_plus"] == pytest.approx(0.0, abs=1e-9)
    assert aggregate["AGR_plus"] == pytest.approx(0.0, abs=1e-9)
    assert aggregate["CSE_plus"] is None  # undefined, never imputed as 0.0


# ---------------------------------------------------------------------------
# The SE+=AGR+*CSE+ invariant (eq. 59) on a small enumerated corpus that
# mixes an agreement and a disagreement, so CSE+ is actually defined.
# ---------------------------------------------------------------------------


def test_se_plus_equals_agr_plus_times_cse_plus_on_a_small_mixed_corpus() -> None:
    agreement_case = _common_setup_case(chi="agent_opens", world_seed=1000046)
    agreement_result = _run(
        agreement_case,
        ScriptedTermsBenchHarness(
            world_seed=agreement_case.world_seed,
            script=[{"decision": "offer", "price": 110.0, "message": "opening"}],
            counterpart_draws_by_round={1: {"u_accept": 0.10, "sentiment_noise": 0.0}},
        ),
    )
    disagreement_case = _common_setup_case(chi="agent_opens", world_seed=1000047)
    disagreement_result = _run(
        disagreement_case,
        ScriptedTermsBenchHarness(
            world_seed=disagreement_case.world_seed,
            script=[{"decision": "reject", "price": None, "message": "no deal"}],
        ),
    )

    pairs = []
    for case, result in ((agreement_case, agreement_result), (disagreement_case, disagreement_result)):
        scorer = _scorer_for(case)
        se = scorer.score_surplus_efficiency(outcome=result.outcome)
        agr = scorer.score_feasible_agreement(outcome=result.outcome)
        pairs.append((se, agr))

    aggregate = m.aggregate_surplus_efficiency_corpus(pairs)
    # Independent re-derivation: SE+ = (0.8+0)/2 = 0.4; AGR+ = (1+0)/2 = 0.5;
    # CSE+ = mean of SE+ over the agreed subset {0.8} = 0.8.
    assert aggregate["SE_plus"] == pytest.approx(0.4, abs=1e-9)
    assert aggregate["AGR_plus"] == pytest.approx(0.5, abs=1e-9)
    assert aggregate["CSE_plus"] == pytest.approx(0.8, abs=1e-9)
    assert aggregate["SE_plus"] == pytest.approx(
        aggregate["AGR_plus"] * aggregate["CSE_plus"], abs=1e-9
    )
