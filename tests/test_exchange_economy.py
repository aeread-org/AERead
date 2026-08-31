"""Deterministic tests for the 10x10 hidden-utility exchange economy."""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread.exchange_v1 import economy as ex  # noqa: E402


def test_legacy_named_action_stack_is_archived_not_active():
    # (the archived legacy module lives in the private development repo)

    for name in [
        "TradeProposal",
        "AuctionProposal",
        "BidDecision",
        "AuctionChoice",
        "LLMExchangePolicy",
        "run_exchange",
        "_proposal_prompt",
        "_bid_prompt",
        "_choice_prompt",
    ]:
        assert not hasattr(ex, name), f"{name} should live only in the archive"


def test_default_world_is_10_by_10_and_keeps_preferences_private():
    world = ex.make_exchange_world(seed=7)

    assert world.num_agents == 10
    assert world.num_resources == 10
    assert len(world.allocation) == 10
    assert all(len(row) == 10 for row in world.allocation)
    assert len(world.preferences) == 10
    assert all(len(row) == 10 for row in world.preferences)

    public = world.public_state(agent_id=1)
    assert "allocation" in public
    assert "agent_preferences" not in public
    assert "preferences" not in public
    assert public["own_preferences"] == pytest.approx(world.preferences[0])


def test_concave_utility_mode_has_diminishing_marginal_value_and_config_support():
    world = ex.make_exchange_world(
        num_agents=1,
        num_resources=1,
        units_per_home_resource=4,
        seed=7,
        utility_mode="concave_separable",
    )
    value = world.preferences[0][0]

    assert world.utility_mode == "concave_separable"
    assert world.utility(1, [[4]]) == pytest.approx(value * 2.0)
    assert world.utility(1, [[9]]) == pytest.approx(value * 3.0)
    assert world.utility(1, [[9]]) - world.utility(1, [[4]]) < world.utility(1, [[4]]) - world.utility(1, [[1]])


def test_institution_pressure_config_changes_cost_accounting_not_resource_totals():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_institution_pressure.json"
    )
    world = ex.make_world_from_config(cfg)
    before = world.copy_allocation()

    assert cfg.utility_mode == "concave_separable"
    assert cfg.institution_pressure.search_cost_per_public_round > 0
    assert cfg.protocol.private_acceptance_mode == "llm_structured"
    assert world.institution_pressure == cfg.institution_pressure

    event = ex.apply_institutional_costs(world, cfg.institution_pressure, round_index=1)
    prompt = ex._freeform_communication_prompt(world, agent_id=1, round_index=1, history=[], protocol=cfg.protocol)

    assert event["search_cost_total"] > 0
    assert ex.resource_totals(world.allocation) == ex.resource_totals(before)
    assert "Coordination pressure" in prompt
    assert "reduce your private payoff" in prompt


def test_anti_anchor_config_adds_bad_fit_example_without_locking_in():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_institution_pressure_anti_anchor.json"
    )
    world = ex.make_world_from_config(cfg)

    assert cfg.rounds == 15
    assert cfg.protocol.anti_anchor_mechanism_example
    prompt = ex._freeform_proposal_prompt(world, agent_id=1, round_index=1, history=[], protocol=cfg.protocol)
    lowered = prompt.lower()

    assert "anti-anchor example" in lowered
    assert "against this environment's incentive" in lowered
    assert "do not copy" in lowered
    assert "do not lock in" in lowered
    assert "rotating unanimity committee" in lowered
    for section in [
        "participants:",
        "timing:",
        "decision rule:",
        "settlement rule:",
        "public state update:",
        "verification/enforcement:",
        "amendment/exit:",
        "why this is bad-fit here:",
    ]:
        assert section in lowered
    assert "bilateral trade" not in lowered


def test_current_experiment_config_recreates_existing_full_visibility_setting():
    cfg = ex.load_experiment_config(ROOT / "configs" / "exchange_economy" / "baselines/current_linear_10x10.json")
    world = ex.make_world_from_config(cfg)

    assert cfg.name == "current_linear_10x10"
    assert cfg.rounds == 300
    assert cfg.controllers == [1, 3, 5]
    assert cfg.protocol.visibility_mode == "full_public"
    assert cfg.protocol.public_broadcast is True
    assert world.num_agents == 10
    assert world.num_resources == 10

    prompt = ex._freeform_proposal_prompt(world, agent_id=1, round_index=1, history=[], protocol=cfg.protocol)
    assert "Public allocation matrix rows are agents" in prompt
    assert "Visible/contactable agents this round" not in prompt


def test_experiment_config_runtime_overrides_are_explicit_and_immutable():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "ladders/capability_ladder_01_visible_bilateral_ir_trade.json"
    )

    overridden = ex.override_experiment_config_runtime(cfg, rounds=3, controllers=[1, 2, 3])

    assert cfg.rounds == 6
    assert cfg.controllers == [1, 2, 3, 4, 5]
    assert overridden.rounds == 3
    assert overridden.controllers == [1, 2, 3]
    assert overridden.protocol == cfg.protocol
    assert overridden.name == cfg.name


def test_public_solicitation_config_adds_search_pressure_without_named_prompt_leaks():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_search_pressure.json"
    )
    world = ex.make_world_from_config(cfg)

    assert cfg.protocol.visibility_mode == "limited_contact"
    assert cfg.protocol.visible_agents_per_agent == 2
    assert cfg.protocol.show_full_allocation is False
    assert cfg.protocol.direct_contact_scope == "visible_only"

    visible = ex.visible_agents_for(cfg.protocol, world, agent_id=1)
    assert len(visible) == 2
    assert 1 not in visible
    assert visible == ex.visible_agents_for(cfg.protocol, world, agent_id=1)

    prompt = ex._freeform_communication_prompt(world, agent_id=1, round_index=1, history=[], protocol=cfg.protocol)
    lowered = prompt.lower()
    assert "visible/contactable agents this round" in lowered
    assert "public broadcast path is available" in lowered
    assert "public allocation matrix rows are agents" not in lowered
    for term in [
        "bilateral trade",
        "auction",
        "clearinghouse",
        "order book",
        "market maker",
        "request for quote",
        "tender",
        "procurement",
        "bounty",
        "solicitation",
        "bid",
        "counteroffer",
    ]:
        assert term not in lowered


def test_optimum_conserves_resources_and_improves_initial_welfare():
    world = ex.make_exchange_world(seed=11)
    optimum = ex.greedy_social_optimum(world)

    assert ex.resource_totals(optimum) == ex.resource_totals(world.allocation)
    assert ex.total_welfare(world, optimum) >= ex.total_welfare(world, world.allocation)
    assert 0.0 <= ex.welfare_ratio(world, world.allocation, optimum) <= 1.0


def test_concave_social_optimum_splits_identical_resource_by_marginal_value():
    world = ex.ExchangeWorld(
        allocation=[
            [4],
            [0],
        ],
        preferences=[
            [1.0],
            [1.0],
        ],
        utility_mode="concave_separable",
    )

    optimum = ex.social_optimum(world)

    assert optimum == [[2.0], [2.0]]
    assert ex.resource_totals(optimum) == [4.0]
    assert ex.total_welfare(world, optimum) > ex.total_welfare(world, [[4], [0]])


def test_fractional_ir_oracle_finds_mutually_beneficial_swap():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )

    oracle = ex.solve_fractional_ir_oracle(world)

    assert oracle.success is True
    assert oracle.individually_rational is True
    assert oracle.welfare_gain == pytest.approx(6.0, abs=1e-5)
    assert oracle.utility_deltas[1] == pytest.approx(3.0, abs=1e-5)
    assert oracle.utility_deltas[2] == pytest.approx(3.0, abs=1e-5)
    assert {(tr.from_agent, tr.to_agent, tr.resource) for tr in oracle.mechanism.transfers} == {
        (1, 2, 1),
        (2, 1, 2),
    }


def test_protocol_constrained_ir_oracle_respects_row_limit_and_contacts():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=1,
        visibility_seed=1,
        settlement_row_limit=1,
    )

    one_row = ex.solve_protocol_constrained_ir_oracle(world, protocol, controller_id=1)
    two_rows = ex.solve_protocol_constrained_ir_oracle(
        world,
        ex.ProtocolConfig(
            visibility_mode="limited_contact",
            visible_agents_per_agent=1,
            visibility_seed=1,
            settlement_row_limit=2,
        ),
        controller_id=1,
    )

    assert one_row.row_limit == 1
    assert len(one_row.mechanism.transfers) <= 1
    assert one_row.welfare_gain == pytest.approx(0.0, abs=1e-6)
    assert two_rows.participants == [1, 2]
    assert len(two_rows.mechanism.transfers) == 2
    assert two_rows.welfare_gain == pytest.approx(6.0, abs=1e-5)


def test_bilateral_ir_oracle_separates_pairwise_trade_from_three_party_cycle():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        preferences=[
            [1.0, 10.0, 1.0],
            [1.0, 1.0, 10.0],
            [10.0, 1.0, 1.0],
        ],
    )

    bilateral = ex.solve_bilateral_ir_oracle(world, participants=[1, 2, 3], row_limit=2)
    coalition = ex.solve_fractional_ir_oracle(world, participants=[1, 2, 3], row_limit=3)

    assert bilateral.mechanism.label == "bilateral_ir_oracle"
    assert len(bilateral.participants) == 2
    assert bilateral.welfare_gain == pytest.approx(9.0, abs=1e-5)
    assert coalition.welfare_gain == pytest.approx(27.0, abs=1e-5)
    assert coalition.welfare_gain - bilateral.welfare_gain == pytest.approx(18.0, abs=1e-5)


def test_greedy_bilateral_floor_applies_memoryless_visible_ir_pairs():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(settlement_row_limit=2)

    floor = ex.simulate_greedy_bilateral_floor(world, protocol, controllers=[1], rounds=2)

    assert floor.applied_rounds == 1
    assert floor.total_welfare_gain == pytest.approx(6.0, abs=1e-5)
    assert floor.rounds[0].applied is True
    assert floor.rounds[0].welfare_gain == pytest.approx(6.0, abs=1e-5)
    assert floor.rounds[1].applied is False
    assert world.allocation == [[1, 0], [0, 1]]


def test_finite_horizon_institution_oracle_values_search_cost_savings_against_trade_opportunity():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
        institution_pressure=ex.InstitutionPressureConfig(
            search_cost_per_public_round=1.0,
            standing_rule_bonus_or_cost_saving=0.5,
        ),
    )
    protocol = ex.ProtocolConfig(settlement_row_limit=2)

    institution = ex.evaluate_finite_horizon_institution_oracle(
        world,
        protocol,
        world.institution_pressure,
        controllers=[1],
        rounds=5,
    )

    assert institution.active_rounds == 4
    assert institution.standing_rule_saving_total == pytest.approx(2.0)
    assert institution.first_round_protocol_gain == pytest.approx(6.0, abs=1e-5)
    assert institution.parallel_net_value == pytest.approx(2.0)
    assert institution.exclusive_net_value == pytest.approx(-4.0, abs=1e-5)
    assert institution.parallel_should_create is True
    assert institution.exclusive_should_create is False


def test_bounded_public_solicitation_oracle_discovers_hidden_counterparty_with_cost():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        preferences=[
            [1.0, 1.0, 4.0],
            [1.0, 1.0, 1.0],
            [4.0, 1.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=0,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="all",
        settlement_row_limit=2,
    )
    envelope = ex.PublicSolicitationEnvelope(
        max_participants=2,
        respondent_limit=None,
        solicitation_cost=1.0,
    )

    solicitation = ex.solve_bounded_public_solicitation_oracle(
        world,
        protocol,
        controller_id=1,
        envelope=envelope,
    )

    assert solicitation.visible_baseline.welfare_gain == pytest.approx(0.0)
    assert solicitation.solicited_solution.welfare_gain == pytest.approx(6.0, abs=1e-5)
    assert solicitation.selected_participants == [1, 3]
    assert solicitation.gross_discovery_gain == pytest.approx(6.0, abs=1e-5)
    assert solicitation.net_discovery_gain == pytest.approx(5.0, abs=1e-5)
    assert solicitation.should_solicit is True


def test_bounded_public_solicitation_oracle_respects_missing_public_broadcast_path():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=0,
        public_broadcast=False,
        communication_scope="controller_contacts",
        response_scope="all",
        settlement_row_limit=2,
    )

    solicitation = ex.solve_bounded_public_solicitation_oracle(world, protocol, controller_id=1)

    assert solicitation.candidate_agents == [1]
    assert solicitation.respondent_agents == []
    assert solicitation.solicited_solution.welfare_gain == pytest.approx(0.0)
    assert solicitation.should_solicit is False


def test_l4_inference_constrained_oracle_uses_public_signals_not_hidden_table():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        preferences=[
            [1.0, 1.0, 4.0],
            [1.0, 1.0, 1.0],
            [4.0, 1.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(settlement_row_limit=2)

    no_signal = ex.solve_l4_inference_constrained_oracle(
        world,
        protocol,
        controller_id=1,
        communication_texts={1: "PUBLIC ACTION\nMESSAGE: I am not revealing wants or offers."},
    )
    signal = ex.solve_l4_inference_constrained_oracle(
        world,
        protocol,
        controller_id=1,
        communication_texts={
            1: "PUBLIC ACTION\nMESSAGE: I want r3. I can offer r1.",
            3: "PUBLIC ACTION\nMESSAGE: I want r1. I can offer r3.",
        },
    )

    assert no_signal.solution.welfare_gain == pytest.approx(0.0, abs=1e-6)
    assert no_signal.inferred_edges == []
    assert signal.inferred_wants[1] == [3]
    assert signal.inferred_offers[3] == [3]
    assert signal.solution.welfare_gain == pytest.approx(6.0, abs=1e-5)
    assert signal.solution.participants == [1, 3]


def test_bayesian_protocol_frontier_matches_protocol_oracle_when_preferences_known():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(settlement_row_limit=2)
    full = ex.solve_protocol_constrained_ir_oracle(world, protocol, controller_id=1)

    bayes = ex.solve_bayesian_protocol_frontier(
        world,
        protocol,
        controller_id=1,
        exact_preference_agent_ids=[1, 2],
        sample_count=8,
        seed=7,
    )

    assert bayes.realized_gain == pytest.approx(full.welfare_gain, abs=1e-5)
    assert bayes.information_constrained_ratio(full.welfare_gain) == pytest.approx(1.0)
    assert bayes.candidate_count >= 1
    assert bayes.realized_individually_rational is True


def test_bayesian_protocol_frontier_is_bounded_by_full_information_ceiling():
    world = ex.make_exchange_world(
        num_agents=3,
        num_resources=3,
        units_per_home_resource=1,
        seed=11,
        utility_mode="concave_separable",
    )
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=1,
        visibility_seed=2,
        settlement_row_limit=2,
    )
    full = ex.solve_protocol_constrained_ir_oracle(world, protocol, controller_id=1)

    bayes = ex.solve_bayesian_protocol_frontier(
        world,
        protocol,
        controller_id=1,
        exact_preference_agent_ids=[1],
        sample_count=12,
        seed=3,
    )

    assert bayes.participants == full.participants
    assert bayes.sample_count == 12
    assert bayes.candidate_count >= 1
    assert bayes.realized_gain <= full.welfare_gain + 1e-6
    assert 0.0 <= bayes.information_constrained_ratio(full.welfare_gain) <= 1.0


def test_round_regret_decomposition_splits_discovery_and_proposal_gaps():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        preferences=[
            [1.0, 1.0, 4.0],
            [1.0, 1.0, 1.0],
            [4.0, 1.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=0,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="all",
        settlement_row_limit=2,
    )
    no_op = ex.CompiledMechanism(
        proposer_id=1,
        label="no_transfer",
        summary="no executable settlement",
        transfers=[],
        consenting_agents=[],
        confidence=1.0,
    )

    regret = ex.decompose_round_regret(
        world,
        protocol,
        round_index=1,
        controller_id=1,
        communication_texts={1: "PUBLIC ACTION\nMESSAGE: I will only talk to visible contacts.\nSETTLEMENT:\nnone"},
        verified_before_private_acceptance=no_op,
        executed_mechanism=no_op,
        pressure=ex.InstitutionPressureConfig(search_cost_per_public_round=0.0),
        solicitation_envelope=ex.PublicSolicitationEnvelope(
            max_participants=2,
            respondent_limit=None,
            solicitation_cost=1.0,
        ),
    )

    assert regret.discovery_regret == pytest.approx(5.0, abs=1e-5)
    assert regret.proposal_regret == pytest.approx(0.0, abs=1e-5)
    assert regret.acceptance_regret == pytest.approx(0.0, abs=1e-5)
    assert regret.finalization_regret == pytest.approx(0.0, abs=1e-5)
    assert regret.by_step["communication"].label == "missed_bounded_public_solicitation"


def test_round_regret_decomposition_finds_wrong_private_acceptance_rejection():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(settlement_row_limit=2)
    positive_swap = ex.CompiledMechanism(
        proposer_id=1,
        label="positive_swap",
        summary="mutually positive swap",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )
    executed = ex.CompiledMechanism(
        proposer_id=1,
        label="private_acceptance_rejected",
        summary="blocked after private acceptance",
        transfers=[],
        consenting_agents=[],
        confidence=1.0,
    )
    audit = ex.PrivateAcceptanceAudit(
        agent_id=1,
        approve=False,
        actual_delta=3.0,
        actual_delta_sign="positive",
        claimed_delta_sign="negative",
        sign_match=False,
        debit_rows_match=True,
        credit_rows_match=True,
        quantity_match=True,
        counterpart_transfers_present=True,
        same_bundle_authorized=True,
        approval_correct=False,
        error_family="claimed_delta_sign_mismatch",
    )

    regret = ex.decompose_round_regret(
        world,
        protocol,
        round_index=1,
        controller_id=1,
        communication_texts={1: "PUBLIC ACTION\nMESSAGE: any agent may opt in and state authorized rows"},
        verified_before_private_acceptance=positive_swap,
        executed_mechanism=executed,
        private_acceptance_audits=[audit],
    )

    assert regret.proposal_regret == pytest.approx(0.0, abs=1e-5)
    assert regret.acceptance_regret == pytest.approx(3.0, abs=1e-5)
    assert regret.finalization_regret == pytest.approx(0.0, abs=1e-5)
    assert regret.by_step["acceptance"].label == "private_acceptance_errors"
    assert regret.components_by_step("acceptance")[0].agent_id == 1


def test_generic_transfer_delta_uses_private_utility_but_harness_does_not_decide():
    world = ex.ExchangeWorld(
        allocation=[
            [0, 1],
            [1, 0],
        ],
        preferences=[
            [4.0, 1.0],
            [1.0, 4.0],
        ],
    )

    good_for_both = ex.CompiledMechanism(
        proposer_id=1,
        label="plain-language reciprocal transfer",
        summary="each side authorizes one resource movement",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=2, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )
    bad_for_receiver = ex.CompiledMechanism(
        proposer_id=1,
        label="one-sided transfer",
        summary="receiver gives one resource without compensation",
        transfers=[ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1)],
        consenting_agents=[1, 2],
        confidence=1.0,
    )

    assert ex.utility_delta_for_mechanism(world, good_for_both, agent_id=2) > 0
    assert ex.utility_delta_for_mechanism(world, bad_for_receiver, agent_id=2) < 0


def test_compiled_mechanism_executes_feasible_llm_acceptance_even_when_not_ir():
    world = ex.ExchangeWorld(
        allocation=[
            [0, 1],
            [1, 0],
        ],
        preferences=[
            [4.0, 1.0],
            [1.0, 4.0],
        ],
    )
    compiled = ex.CompiledMechanism(
        proposer_id=1,
        label="whatever mechanism the agents described",
        summary="receiver accepts a bad transfer",
        transfers=[ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1)],
        consenting_agents=[1, 2],
        confidence=0.95,
    )

    event = ex.apply_compiled_mechanism(world, compiled, round_index=1, controller_id=1)

    assert event.applied is True
    assert event.agent_deltas[2] < 0
    assert event.individually_rational is False
    assert world.allocation == [[1, 1], [0, 0]]
    assert ex.resource_totals(world.allocation) == [1, 1]


def test_empty_compiled_mechanism_is_noop_not_applied():
    world = ex.make_exchange_world(seed=3)
    before = world.copy_allocation()
    compiled = ex.CompiledMechanism(
        proposer_id=1,
        label="pass",
        summary="no clear transfer was finalized",
        transfers=[],
        consenting_agents=[1],
        confidence=1.0,
    )

    event = ex.apply_compiled_mechanism(world, compiled, round_index=1, controller_id=1)

    assert event.applied is False
    assert event.individually_rational is None
    assert world.allocation == before


def test_run_trace_jsonl_records_transcripts_and_verified_mechanism(tmp_path):
    world = ex.make_exchange_world(num_agents=2, num_resources=2, seed=3)
    trace_path = tmp_path / "trace.jsonl"

    class NoOpTracePolicy:
        def communication_text(self, world, agent_id, round_index, history):
            return "PUBLIC ACTION\nMESSAGE: observe\nSETTLEMENT:\nnone"

        def propose_text(self, world, agent_id, round_index, history, communication_texts):
            return "PUBLIC ACTION\nMESSAGE: proposal text\nSETTLEMENT:\nnone"

        def respond_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: response text\nSETTLEMENT:\nnone"

        def finalize_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: final text\nSETTLEMENT:\nnone"

        def compile_transcript(self, world, transcript):
            return ex.CompiledMechanism(
                proposer_id=transcript.controller_id,
                label="trace noop",
                summary="no transfer",
                transfers=[],
                consenting_agents=[],
                confidence=1.0,
            )

        def verify_compilation(self, world, transcript, mechanism):
            return mechanism

    result = ex.run_exchange_transcript(
        world,
        rounds=1,
        controllers=[1],
        policy=NoOpTracePolicy(),
        response_agent_ids=[2],
        trace_jsonl_path=trace_path,
    )

    rows = [ex.json.loads(line) for line in trace_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["proposal_text"].startswith("PUBLIC ACTION")
    assert rows[0]["final_text"].startswith("PUBLIC ACTION")
    assert rows[0]["verified_mechanism"]["mechanism_label"] == "trace noop"
    assert rows[0]["event"]["kind"] == "trace noop"
    assert result.history[0].kind == "trace noop"


def test_transcript_runner_uses_controllers_without_legacy_named_actions():
    world = ex.make_exchange_world(seed=23)
    initial = ex.total_welfare(world, world.allocation)

    class NoOpTranscriptPolicy:
        def communication_text(self, world, agent_id, round_index, history):
            return "PUBLIC ACTION\nMESSAGE: observation only\nSETTLEMENT: none"

        def propose_text(self, world, agent_id, round_index, history, communication_texts):
            return "PUBLIC ACTION\nMESSAGE: no executable action\nSETTLEMENT: none"

        def respond_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: no authorization\nSETTLEMENT: none"

        def finalize_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: finalize nothing\nSETTLEMENT: none"

        def compile_transcript(self, world, transcript):
            return ex.CompiledMechanism(
                proposer_id=transcript.controller_id,
                label="no executable effect",
                summary="no clear transfer or public-state update was finalized",
                transfers=[],
                consenting_agents=[transcript.controller_id],
                confidence=1.0,
            )

        def verify_compilation(self, world, transcript, mechanism):
            return mechanism

    result = ex.run_exchange_transcript(
        world,
        rounds=6,
        controllers=[1, 3, 5],
        policy=NoOpTranscriptPolicy(),
    )

    assert len(result.history) == 6
    assert [r.controller_id for r in result.history[:6]] == [1, 3, 5, 1, 3, 5]
    assert result.final_welfare == pytest.approx(initial)
    assert result.applied_mechanisms == 0


def test_llm_policy_records_usage_cost_and_cache_hits(monkeypatch):
    calls = []

    def fake_call_llm(system, user, model, max_tokens, temperature=0.0, sample=0):
        cached = len(calls) == 1
        calls.append(
            {
                "system": system,
                "user": user,
                "model": model,
                "max_tokens": max_tokens,
                "cached": cached,
                "temperature": temperature,
                "sample": sample,
            }
        )
        return SimpleNamespace(
            text=(
                "PUBLIC ACTION\n"
                "MESSAGE:\nnoop\n"
                "SETTLEMENT:\nnone\n"
                "CONSENT CONDITIONS:\nnone\n"
                "PUBLIC STATE UPDATE:\nnone\n"
                "NO-TRANSFER FALLBACK:\nnone"
            ),
            cached=cached,
            usage={
                "input_tokens": 10,
                "cached_input_tokens": 4,
                "output_tokens": 5,
                "total_tokens": 15,
                "reasoning_tokens": 2,
            },
            estimated_cost_usd=0.0 if cached else 0.001,
            cost_note="test",
        )

    monkeypatch.setattr(ex, "call_llm", fake_call_llm)
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=21)
    policy = ex.LLMCompilerVerifierPolicy(model="test-model", max_tokens=123, temperature=0.7, sample=42)

    policy.communication_text(world, agent_id=1, round_index=1, history=[])
    policy.propose_text(world, agent_id=1, round_index=1, history=[], communication_texts={})

    summary = policy.usage_summary()

    assert summary["calls"] == 2
    assert summary["fresh_calls"] == 1
    assert summary["cached_calls"] == 1
    assert summary["input_tokens"] == 20
    assert summary["cached_input_tokens"] == 8
    assert summary["provider_cache_hit_rate"] == 0.4
    assert summary["output_tokens"] == 10
    assert summary["total_tokens"] == 30
    assert summary["reasoning_tokens"] == 4
    assert summary["estimated_cost_usd"] == 0.001
    assert summary["unknown_cost_calls"] == 0
    assert summary["by_role"]["communication"]["calls"] == 1
    assert summary["by_role"]["proposal"]["calls"] == 1
    assert [call["temperature"] for call in calls] == [0.7, 0.7]
    assert [call["sample"] for call in calls] == [42, 42]


def test_gemini_policy_enables_context_cache_defaults_without_overriding_opt_out(monkeypatch):
    monkeypatch.delenv("GEMINI_CONTEXT_CACHE", raising=False)
    monkeypatch.delenv("GEMINI_CONTEXT_CACHE_MARKER", raising=False)
    monkeypatch.delenv("GEMINI_CONTEXT_CACHE_MIN_CHARS", raising=False)

    ex.LLMCompilerVerifierPolicy(model="google/gemini-3.5-flash")

    assert "GEMINI_CONTEXT_CACHE" in os.environ
    assert os.environ["GEMINI_CONTEXT_CACHE"] == "1"
    assert os.environ["GEMINI_CONTEXT_CACHE_MARKER"] == "Viewer-specific contact context:"
    assert int(os.environ["GEMINI_CONTEXT_CACHE_MIN_CHARS"]) <= 4000

    monkeypatch.setenv("GEMINI_CONTEXT_CACHE", "0")
    ex.LLMCompilerVerifierPolicy(model="google/gemini-3.5-flash")

    assert os.environ["GEMINI_CONTEXT_CACHE"] == "0"


def test_transcript_runner_batches_independent_llm_phases(monkeypatch):
    batch_sizes = []
    batch_requests_seen = []
    single_calls = []

    def fake_call_llm(system, user, model, max_tokens, temperature=0.0, sample=0):
        single_calls.append(
            {
                "system": system,
                "user": user,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "sample": sample,
            }
        )
        if "mechanism compiler" in system:
            text = (
                '{"mechanism_label":"noop","summary":"no executable effect",'
                '"transfers":[],"institutional_updates":[],"consenting_agents":[1],"confidence":1.0}'
            )
        elif "semantic verifier" in system:
            text = '{"verifier_ok":true,"confidence":1.0,"reason":"ok"}'
        else:
            text = (
                "PUBLIC ACTION\n"
                "MESSAGE:\nno executable action\n"
                "SETTLEMENT:\nnone\n"
                "CONSENT CONDITIONS:\nnone\n"
                "PUBLIC STATE UPDATE:\nnone\n"
                "NO-TRANSFER FALLBACK:\nnone"
            )
        return SimpleNamespace(
            text=text,
            cached=False,
            usage={
                "input_tokens": 5,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "total_tokens": 6,
                "reasoning_tokens": 0,
            },
            estimated_cost_usd=0.01,
            cost_note="single",
        )

    def fake_call_llm_batch(requests, model, cache_dir=None, poll_interval=None):
        batch_sizes.append(len(requests))
        batch_requests_seen.extend(requests)
        return [
            SimpleNamespace(
                text=(
                    "PUBLIC ACTION\n"
                    f"MESSAGE:\nbatched {i}\n"
                    "SETTLEMENT:\nnone\n"
                    "CONSENT CONDITIONS:\nnone\n"
                    "PUBLIC STATE UPDATE:\nnone\n"
                    "NO-TRANSFER FALLBACK:\nnone"
                ),
                cached=False,
                usage={
                    "input_tokens": 10,
                    "cached_input_tokens": 4,
                    "output_tokens": 2,
                    "total_tokens": 12,
                    "reasoning_tokens": 0,
                },
                estimated_cost_usd=0.001,
                cost_note="batch",
            )
            for i, _ in enumerate(requests)
        ]

    monkeypatch.setattr(ex, "call_llm", fake_call_llm)
    monkeypatch.setattr(ex, "call_llm_batch", fake_call_llm_batch)
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=31)
    policy = ex.LLMCompilerVerifierPolicy(
        model="google/gemini-3.5-flash",
        batch_enabled=True,
        temperature=0.6,
        sample=7,
    )

    result = ex.run_exchange_transcript(world, rounds=1, controllers=[1], policy=policy)
    summary = policy.usage_summary()

    assert batch_sizes == [3, 2]
    assert len(single_calls) == 4
    assert result.applied_mechanisms == 0
    assert summary["by_role"]["communication"]["calls"] == 3
    assert summary["by_role"]["response"]["calls"] == 2
    assert summary["estimated_cost_usd"] == pytest.approx(0.045)
    assert {item["temperature"] for item in batch_requests_seen} == {0.6}
    assert {item["sample"] for item in batch_requests_seen} == {7}
    agent_single_calls = [
        call
        for call in single_calls
        if "mechanism compiler" not in call["system"] and "semantic verifier" not in call["system"]
    ]
    execution_single_calls = [
        call
        for call in single_calls
        if "mechanism compiler" in call["system"] or "semantic verifier" in call["system"]
    ]
    assert {call["temperature"] for call in agent_single_calls} == {0.6}
    assert {call["sample"] for call in agent_single_calls} == {7}
    assert {call["temperature"] for call in execution_single_calls} == {0.0}
    assert {call["sample"] for call in execution_single_calls} == {0}


def test_compiler_json_parser_handles_generic_transfer_schema():
    text = """
    Compiler output:
    {
      "mechanism_label":"compiled public ledger transfer",
      "summary":"a3 gives r2 to a1 in exchange for r1",
      "transfers":[
        {"from":1,"to":3,"resource":"r1","quantity":1},
        {"from":3,"to":1,"resource":"r2","quantity":1}
      ],
      "consenting_agents":[1,3],
      "confidence":0.91
    }
    """
    mechanism = ex.parse_compiled_mechanism(text, proposer_id=1, num_agents=10, num_resources=10)

    assert mechanism.proposer_id == 1
    assert mechanism.label == "compiled public ledger transfer"
    assert mechanism.transfers[0] == ex.Transfer(from_agent=1, to_agent=3, resource=1, quantity=1)
    assert mechanism.transfers[1] == ex.Transfer(from_agent=3, to_agent=1, resource=2, quantity=1)
    assert mechanism.consenting_agents == [1, 3]

    with pytest.raises(ValueError):
        ex.parse_compiled_mechanism(
            '{"transfers":[{"from":99,"to":1,"resource":"r1","quantity":1}]}',
            proposer_id=1,
            num_agents=10,
            num_resources=10,
        )


def test_fractional_compiled_transfers_parse_apply_and_conserve_resources():
    world = ex.ExchangeWorld(
        allocation=[
            [3.0, 0.0],
            [0.0, 2.0],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    text = """
    {
      "mechanism_label": "fractional public settlement",
      "summary": "fractional transfers are supported",
      "transfers": [
        {"from": "a1", "to": "a2", "resource": "r1", "quantity": 1.5},
        {"from": "a2", "to": "a1", "resource": "r2", "quantity": 0.5}
      ],
      "consenting_agents": ["a1", "a2"],
      "confidence": 0.99
    }
    """

    mechanism = ex.parse_compiled_mechanism(text, proposer_id=1, num_agents=2, num_resources=2)
    event = ex.apply_compiled_mechanism(world, mechanism, round_index=1, controller_id=1)

    assert mechanism.transfers[0].quantity == pytest.approx(1.5)
    assert mechanism.transfers[1].quantity == pytest.approx(0.5)
    assert event.applied is True
    assert event.individually_rational is True
    assert event.agent_deltas[1] == pytest.approx(0.5)
    assert event.agent_deltas[2] == pytest.approx(5.5)
    assert [x for row in world.allocation for x in row] == pytest.approx([1.5, 0.5, 1.5, 1.5])
    assert ex.resource_totals(world.allocation) == pytest.approx([3.0, 2.0])


def test_compiler_parser_keeps_arbitrary_institutional_updates():
    text = """
    {
      "mechanism_label": "standing public coordination record",
      "summary": "agents create a public rule without immediate transfers",
      "transfers": [],
      "institutional_updates": [
        "For the next two rounds, a3 will collect voluntary r2/r4 quantity statements and announce a public proposal.",
        {
          "anything_the_agents_named": "rotation rule",
          "free_text_terms": "a1, a3, and a5 can revise public terms each controller turn.",
          "custom_nested_shape": {"no_fixed_taxonomy": true}
        }
      ],
      "consenting_agents": ["a1", "a3", "a5"],
      "confidence": 0.88
    }
    """

    mechanism = ex.parse_compiled_mechanism(text, proposer_id=1, num_agents=5, num_resources=5)

    assert mechanism.transfers == []
    assert mechanism.institutional_updates == [
        {"text": "For the next two rounds, a3 will collect voluntary r2/r4 quantity statements and announce a public proposal."},
        {
            "anything_the_agents_named": "rotation rule",
            "free_text_terms": "a1, a3, and a5 can revise public terms each controller turn.",
            "custom_nested_shape": {"no_fixed_taxonomy": True},
        },
    ]
    assert mechanism.consenting_agents == [1, 3, 5]


def test_institution_only_mechanism_persists_without_resource_transfer():
    world = ex.make_exchange_world(num_agents=5, num_resources=5, seed=17)
    before = world.copy_allocation()
    compiled = ex.CompiledMechanism(
        proposer_id=1,
        label="public interest log",
        summary="a1 and a3 create a nonbinding public interest log",
        transfers=[],
        institutional_updates=[
            {
                "name": "r2 interest log",
                "terms": "agents may post willingness to exchange r2 for any bundle; later transfers still need explicit consent",
                "participants": ["a1", "a3"],
            }
        ],
        consenting_agents=[1, 3],
        confidence=0.95,
    )

    event = ex.apply_compiled_mechanism(world, compiled, round_index=1, controller_id=1)

    assert event.applied is True
    assert event.accepted is True
    assert event.individually_rational is None
    assert world.allocation == before
    assert world.institutions == [
        {
            "name": "r2 interest log",
            "terms": "agents may post willingness to exchange r2 for any bundle; later transfers still need explicit consent",
            "participants": ["a1", "a3"],
            "source_round": 1,
            "status": "active",
        }
    ]
    assert "r2 interest log" in ex._state_text(world, agent_id=2)


def test_freeform_prompt_foregrounds_universal_mechanism_elements_without_named_templates():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=5)

    prompt = ex._freeform_proposal_prompt(world, agent_id=1, round_index=1, history=[])
    lowered = prompt.lower()

    assert "public action" in lowered
    for term in [
        "bilateral trade",
        "auction",
        "clearinghouse",
        "order book",
        "market maker",
        "direct exchange",
        "bid",
        "counteroffer",
    ]:
        assert term not in lowered
    for element in [
        "participants",
        "information",
        "messages",
        "timing",
        "decision rule",
        "settlement",
        "consent",
        "public state update",
        "no-transfer fallback",
    ]:
        assert element in lowered


def test_transcript_and_proposal_prompt_include_public_cheap_talk():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=9)
    messages = {
        1: "I may value r2 highly, but this could be strategic cheap talk.",
        2: "I want a clearing rule before committing resources.",
        3: "I claim r1 is low value to me and invite offers.",
    }

    prompt = ex._freeform_proposal_prompt(
        world,
        agent_id=1,
        round_index=1,
        history=[],
        communication_texts=messages,
    )
    transcript = ex.RoundTranscript(
        round_index=1,
        controller_id=1,
        proposal_text="I propose after observing public messages.",
        response_texts={2: "accept with conditions"},
        final_text="finalize nothing",
        communication_texts=messages,
    )
    transcript_text = ex._transcript_text(transcript)

    assert "Public observation / cheap-talk messages" in prompt
    assert "could be strategic cheap talk" in prompt
    assert "public_communication" in transcript_text
    assert "I want a clearing rule" in transcript_text


def test_prompt_public_prefix_is_shared_before_private_context():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=12)

    p1 = ex._freeform_communication_prompt(world, agent_id=1, round_index=1, history=[])
    p2 = ex._freeform_communication_prompt(world, agent_id=2, round_index=1, history=[])

    marker = "Private agent context:"
    assert marker in p1
    assert marker in p2
    assert p1.split(marker)[0] == p2.split(marker)[0]
    assert "private marginal utilities" not in p1.split(marker)[0].lower()
    assert p1.index("Shared public context:") < p1.index(marker)


def test_limited_contact_prompt_keeps_cacheable_shared_prefix_before_viewer_specific_context():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_search_pressure.json"
    )
    world = ex.make_world_from_config(cfg)

    p1 = ex._freeform_communication_prompt(world, agent_id=1, round_index=1, history=[], protocol=cfg.protocol)
    p2 = ex._freeform_communication_prompt(world, agent_id=2, round_index=1, history=[], protocol=cfg.protocol)

    marker = "Viewer-specific contact context:"
    private_marker = "Private agent context:"
    assert marker in p1
    assert marker in p2
    assert p1.split(marker)[0] == p2.split(marker)[0]
    assert "Visible/contactable agents this round" not in p1.split(marker)[0]
    assert "Visible/contactable agents this round" in p1.split(marker)[1].split(private_marker)[0]
    assert "Your private marginal utilities" not in p1.split(marker)[0]
    assert p1.index("Shared public context:") < p1.index(marker) < p1.index(private_marker)


def test_anti_anchor_example_and_envelope_are_cacheable_shared_prefix():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_institution_pressure_anti_anchor.json"
    )
    world = ex.make_world_from_config(cfg)

    p1 = ex._freeform_communication_prompt(world, agent_id=1, round_index=1, history=[], protocol=cfg.protocol)
    p2 = ex._freeform_communication_prompt(world, agent_id=2, round_index=1, history=[], protocol=cfg.protocol)

    marker = "Viewer-specific contact context:"
    private_marker = "Private agent context:"
    prefix1 = p1.split(marker)[0]
    prefix2 = p2.split(marker)[0]

    assert prefix1 == prefix2
    assert "Anti-anchor example" in prefix1
    assert "Rotating Unanimity Committee" in prefix1
    assert "Use this universal public-action envelope exactly" in prefix1
    assert "SETTLEMENT:" in prefix1
    assert "PUBLIC STATE UPDATE:" in prefix1
    assert "Your private marginal utilities" not in prefix1
    assert p1.index("Anti-anchor example") < p1.index(marker) < p1.index(private_marker)
    assert p1.index("Use this universal public-action envelope exactly") < p1.index(marker)


def test_universal_public_action_schema_addressees_and_response_request_are_cacheable():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/public_solicitation/treatment_public_solicitation_solicited.json"
    )
    world = ex.make_world_from_config(cfg)

    p1 = ex._freeform_communication_prompt(world, agent_id=1, round_index=1, history=[], protocol=cfg.protocol)
    p2 = ex._freeform_communication_prompt(world, agent_id=2, round_index=1, history=[], protocol=cfg.protocol)

    marker = "Viewer-specific contact context:"
    prefix1 = p1.split(marker)[0]
    prefix2 = p2.split(marker)[0]

    assert prefix1 == prefix2
    assert "ADDRESSEES:" in prefix1
    assert "RESPONSE REQUEST:" in prefix1
    assert "one agent, multiple named agents, all agents, or any agent" in prefix1
    assert "Visible/contactable agents this round" not in prefix1
    assert prefix1.index("ADDRESSEES:") < prefix1.index("MESSAGE:")
    assert prefix1.index("MESSAGE:") < prefix1.index("RESPONSE REQUEST:")
    assert prefix1.index("RESPONSE REQUEST:") < prefix1.index("SETTLEMENT:")


def test_public_action_section_parser_respects_addressees_and_response_request_headings():
    action = (
        "PUBLIC ACTION\n"
        "ADDRESSEES:\n"
        "all agents\n"
        "MESSAGE:\n"
        "checking for mutually useful rows\n"
        "RESPONSE REQUEST:\n"
        "share feasible counterparties and quantities\n"
        "SETTLEMENT:\n"
        "none\n"
        "CONSENT CONDITIONS:\n"
        "none\n"
        "PUBLIC STATE UPDATE:\n"
        "none\n"
        "NO-TRANSFER FALLBACK:\n"
        "no transfer"
    )

    assert ex._public_action_section(action, "ADDRESSEES") == "all agents"
    assert ex._public_action_section(action, "MESSAGE") == "checking for mutually useful rows"
    assert (
        ex._public_action_section(action, "RESPONSE REQUEST")
        == "share feasible counterparties and quantities"
    )


def test_controller_finalization_requires_public_action_envelope_no_reasoning_prefix():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=13)
    transcript = ex.RoundTranscript(
        round_index=1,
        controller_id=1,
        proposal_text="I propose a clearing cycle.",
        response_texts={2: "I accept giving 1 r2 to a3.", 3: "I accept giving 1 r3 to a1."},
        final_text="",
    )

    prompt = ex._freeform_finalize_prompt(world, agent_id=1, transcript=transcript, history=[])

    assert "First line must be exactly `PUBLIC ACTION`" in prompt
    assert "Do not put reasoning before PUBLIC ACTION" in prompt
    assert "omit that transfer" in prompt
    for section in [
        "ADDRESSEES:",
        "MESSAGE:",
        "RESPONSE REQUEST:",
        "SETTLEMENT:",
        "CONSENT CONDITIONS:",
        "PUBLIC STATE UPDATE:",
        "NO-TRANSFER FALLBACK:",
    ]:
        assert section in prompt
    assert "from | to | resource | quantity" in prompt


def test_freeform_prompts_ban_scratchpad_and_require_public_action_envelope():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=14)
    communication_prompt = ex._freeform_communication_prompt(world, agent_id=1, round_index=1, history=[])
    proposal_prompt = ex._freeform_proposal_prompt(world, agent_id=1, round_index=1, history=[])
    response_prompt = ex._freeform_response_prompt(
        world,
        agent_id=2,
        transcript=ex.RoundTranscript(
            round_index=1,
            controller_id=1,
            proposal_text="PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT: none",
            response_texts={},
            final_text="",
        ),
        history=[],
    )
    final_prompt = ex._freeform_finalize_prompt(
        world,
        agent_id=1,
        transcript=ex.RoundTranscript(
            round_index=1,
            controller_id=1,
            proposal_text="PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT: none",
            response_texts={2: "I accept the institution."},
            final_text="",
        ),
        history=[],
    )

    assert "Do not output private calculations" in ex._FREEFORM_SYSTEM
    for prompt in [communication_prompt, proposal_prompt, response_prompt, final_prompt]:
        assert "First line must be exactly `PUBLIC ACTION`" in prompt
        assert "ADDRESSEES:" in prompt
        assert "MESSAGE:" in prompt
        assert "RESPONSE REQUEST:" in prompt
        assert "SETTLEMENT:" in prompt
        assert "CONSENT CONDITIONS:" in prompt
        assert "PUBLIC STATE UPDATE:" in prompt
        assert "NO-TRANSFER FALLBACK:" in prompt
    assert "No scratchpad" in final_prompt


def test_institutional_updates_require_final_public_state_update_support():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=15)
    transcript = ex.RoundTranscript(
        round_index=1,
        controller_id=1,
        proposal_text=(
            "PUBLIC ACTION\n"
            "MESSAGE: propose nothing\n"
            "SETTLEMENT:\nnone\n"
            "CONSENT CONDITIONS:\nnone\n"
            "PUBLIC STATE UPDATE:\nnone\n"
            "NO-TRANSFER FALLBACK:\nno transfer"
        ),
        response_texts={},
        final_text=(
            "PUBLIC ACTION\n"
            "MESSAGE: no transfer because the proposal was rejected\n"
            "SETTLEMENT:\nnone\n"
            "CONSENT CONDITIONS:\nnone\n"
            "PUBLIC STATE UPDATE:\nnone\n"
            "NO-TRANSFER FALLBACK:\nno transfer"
        ),
    )
    mechanism = ex.CompiledMechanism(
        proposer_id=1,
        label="no-transfer fallback",
        summary="No transfer occurred.",
        transfers=[],
        consenting_agents=[],
        confidence=1.0,
        institutional_updates=[{"text": "Round 1 had no transfer."}],
    )

    hardened = ex.enforce_transcript_support(world, transcript, mechanism)

    assert hardened.institutional_updates == []
    assert hardened.verifier_ok is True


def test_supported_institutional_update_survives_when_finalization_explicitly_creates_state():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=16)
    transcript = ex.RoundTranscript(
        round_index=1,
        controller_id=1,
        proposal_text="PUBLIC ACTION\nMESSAGE: propose state\nSETTLEMENT:\nnone",
        response_texts={2: "PUBLIC ACTION\nMESSAGE: I consent to the public memory\nSETTLEMENT:\nnone"},
        final_text=(
            "PUBLIC ACTION\n"
            "MESSAGE: create a persistent public memory for future rounds\n"
            "SETTLEMENT:\nnone\n"
            "CONSENT CONDITIONS:\na1 and a2 consent to the public memory\n"
            "PUBLIC STATE UPDATE:\nPersist: a1 and a2 are willing to evaluate future conditional arrangements together.\n"
            "NO-TRANSFER FALLBACK:\nno transfer"
        ),
    )
    mechanism = ex.CompiledMechanism(
        proposer_id=1,
        label="public memory",
        summary="Create public memory.",
        transfers=[],
        consenting_agents=[1, 2],
        confidence=1.0,
        institutional_updates=[{"text": "a1 and a2 are willing to evaluate future conditional arrangements together."}],
    )

    hardened = ex.enforce_transcript_support(world, transcript, mechanism)

    assert hardened.institutional_updates == mechanism.institutional_updates


def test_strict_self_interest_protocol_adds_private_delta_and_non_leakage_instructions():
    protocol = ex.ProtocolConfig(strict_self_interest=True)
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=17)

    proposal_prompt = ex._freeform_proposal_prompt(
        world,
        agent_id=1,
        round_index=1,
        history=[],
        protocol=protocol,
    )
    response_prompt = ex._freeform_response_prompt(
        world,
        agent_id=2,
        transcript=ex.RoundTranscript(
            round_index=1,
            controller_id=1,
            proposal_text="PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT:\nnone",
            response_texts={},
            final_text="",
        ),
        history=[],
        protocol=protocol,
    )

    for prompt in [proposal_prompt, response_prompt]:
        assert "Privately compute your own utility delta" in prompt
        assert "Reject or counter instead of consenting" in prompt
        assert "Do not quote numeric private marginal utilities" in prompt


def test_strict_public_solicitation_config_loads_strict_protocol():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_search_pressure_strict.json"
    )

    assert cfg.rounds == 15
    assert cfg.protocol.strict_self_interest is True
    assert cfg.protocol.require_final_public_state_update_for_institutions is True
    assert cfg.protocol.communication_scope == "controller_contacts"
    assert cfg.protocol.private_acceptance_check is True


def test_atomic_commit_config_loads_one_step_protocol():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_institution_pressure_anti_anchor_atomic_commit.json"
    )

    assert cfg.protocol.atomic_commit is True
    assert cfg.protocol.private_acceptance_check is False
    assert cfg.protocol.strict_self_interest is True


def test_clean_main_and_public_solicitation_treatment_configs_are_separate():
    main = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "baselines/core_atomic_ir_clean.json"
    )
    treatment = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/public_solicitation/treatment_public_solicitation_solicited.json"
    )

    assert main.protocol.atomic_commit is True
    assert main.protocol.ir_enforce is True
    assert main.protocol.private_acceptance_check is False
    assert main.protocol.anti_anchor_mechanism_example == ""
    assert main.institution_pressure.search_cost_per_public_round == 0.0
    assert main.protocol.public_broadcast is False
    assert main.protocol.response_scope == "visible_only"

    assert treatment.protocol.atomic_commit == main.protocol.atomic_commit
    assert treatment.protocol.ir_enforce == main.protocol.ir_enforce
    assert treatment.protocol.private_acceptance_check == main.protocol.private_acceptance_check
    assert treatment.protocol.anti_anchor_mechanism_example == ""
    assert treatment.institution_pressure.search_cost_per_public_round == 0.0
    assert treatment.protocol.public_broadcast is True
    assert treatment.protocol.response_scope == "solicited_public"


def test_clean_configs_use_validated_information_reveal_profile():
    config_names = [
        "baselines/core_atomic_ir_clean.json",
        "treatments/public_solicitation/treatment_public_solicitation_solicited.json",
        "treatments/public_solicitation/treatment_public_solicitation_auto_response_upper_bound.json",
        "treatments/public_solicitation/treatment_public_solicitation_with_search_cost.json",
    ]

    for name in config_names:
        cfg = ex.load_experiment_config(ROOT / "configs" / "exchange_economy" / name)
        world = ex.make_world_from_config(cfg)
        audit = ex.validate_information_reveal_protocol(
            world,
            cfg.protocol,
            history=[],
            agent_ids=[1, 2, 3],
            controller_id=1,
        )

        assert cfg.protocol.information_reveal_profile == "clean_market_v1"
        assert audit.ok, audit.format()


def test_treatment_toolbox_catalog_keeps_public_solicitation_stepwise():
    toolbox = json.loads(
        (ROOT / "configs" / "exchange_economy" / "treatments/treatment_toolbox.json").read_text()
    )

    assert toolbox["main_config"] == "baselines/core_atomic_ir_clean.json"
    public_solicitation = toolbox["mechanisms"]["public_solicitation"]
    steps = public_solicitation["steps"]
    assert [step["id"] for step in steps] == [
        "ps0_no_public_response",
        "ps1_solicited_public_response",
        "ps1b_solicited_public_response_visibility_gap",
        "ps1c_visibility_gap_partial_clearing_private_acceptance",
        "ps2_auto_public_response_upper_bound",
        "ps3_solicited_public_response_with_search_cost",
    ]

    for step in steps:
        config_path = ROOT / "configs" / "exchange_economy" / step["config"]
        assert config_path.exists()
        assert "single_change_from_previous" in step
        assert "interpretation" in step


def test_treatment_toolbox_catalog_keeps_t0_pressure_optional_and_detachable():
    toolbox = json.loads(
        (ROOT / "configs" / "exchange_economy" / "treatments/treatment_toolbox.json").read_text()
    )

    assert toolbox["main_config"] == "baselines/core_atomic_ir_clean.json"
    assisted = toolbox["mechanisms"]["explicit_rule_savings_affordance"]
    assert assisted["optional_treatment_family"] is True
    assert assisted["do_not_mix_with"] == [
        "anti-anchor examples",
        "automatic all-agent response unless labeled as an upper bound",
        "atomic protocol simplification",
        "currency/numeraire treatments",
    ]
    assert [step["id"] for step in assisted["steps"]] == [
        "t0_recurring_search_no_rule_savings",
        "t0_recurring_search_codified_rule_savings",
    ]
    assert toolbox["mechanisms"]["indirect_routing_pressure"]["steps"][0]["id"] == (
        "t0_indirect_routing_per_contact_cost"
    )
    for step in assisted["steps"] + toolbox["mechanisms"]["indirect_routing_pressure"]["steps"]:
        config_path = ROOT / "configs" / "exchange_economy" / step["config"]
        assert config_path.exists()
        assert "single_change_from_previous" in step
        assert "interpretation" in step


def test_visibility_gap_treatment_has_one_effective_pressure_channel():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/public_solicitation/treatment_public_solicitation_visibility_gap.json"
    )
    world = ex.make_world_from_config(cfg)

    assert cfg.protocol.information_reveal_profile == "clean_market_v1"
    assert cfg.protocol.visible_agents_per_agent == 1
    assert cfg.protocol.public_broadcast is True
    assert cfg.protocol.response_scope == "solicited_public"
    assert cfg.protocol.ir_enforce is False
    assert cfg.protocol.private_acceptance_check is False
    assert cfg.institution_pressure.search_cost_per_public_round == 0.0
    assert cfg.institution_pressure.contact_expansion_cost == 0.0
    assert cfg.institution_pressure.standing_rule_bonus_or_cost_saving == 0.0

    for controller_id in cfg.controllers:
        visible = ex.visible_agents_for(cfg.protocol, world, controller_id)
        visible_gain = max(
            ex.solve_bilateral_ir_oracle(
                world,
                participants=[controller_id, other_id],
                row_limit=cfg.protocol.settlement_row_limit,
            ).welfare_gain
            for other_id in visible
        )
        best_hidden_gain = max(
            ex.solve_bilateral_ir_oracle(
                world,
                participants=[controller_id, other_id],
                row_limit=cfg.protocol.settlement_row_limit,
            ).welfare_gain
            for other_id in range(1, world.num_agents + 1)
            if other_id != controller_id and other_id not in visible
        )

        assert best_hidden_gain - visible_gain > 7.0

        solicitation = ex.solve_bounded_public_solicitation_oracle(
            world,
            cfg.protocol,
            controller_id=controller_id,
        )
        assert solicitation.net_discovery_gain > 7.0
        assert any(agent_id not in visible for agent_id in solicitation.selected_participants)


def test_visibility_gap_private_acceptance_treatment_has_no_deterministic_auto_block():
    cfg = ex.load_experiment_config(
        ROOT
        / "configs"
        / "exchange_economy"
        / "treatments/public_solicitation/treatment_public_solicitation_visibility_gap_private_acceptance.json"
    )

    assert cfg.rounds == 15
    assert cfg.protocol.response_scope == "solicited_public"
    assert cfg.protocol.private_acceptance_check is True
    assert cfg.protocol.private_acceptance_mode == "llm_structured"
    assert cfg.protocol.atomic_commit is False
    assert cfg.protocol.ir_enforce is False
    assert ex.ProtocolConfig().ir_enforce is False


def test_visibility_gap_partial_clearing_treatment_is_one_isolated_knob():
    cfg = ex.load_experiment_config(
        ROOT
        / "configs"
        / "exchange_economy"
        / "treatments/public_solicitation/treatment_public_solicitation_visibility_gap_partial_clearing.json"
    )
    world = ex.make_world_from_config(cfg)

    assert cfg.rounds == 15
    assert cfg.protocol.information_reveal_profile == "clean_market_v1"
    assert cfg.protocol.visibility_mode == "limited_contact"
    assert cfg.protocol.visible_agents_per_agent == 2
    assert cfg.protocol.public_broadcast is True
    assert cfg.protocol.communication_scope == "controller_contacts"
    assert cfg.protocol.response_scope == "solicited_public"
    assert cfg.protocol.partial_clearing is True
    assert cfg.protocol.private_acceptance_check is True
    assert cfg.protocol.private_acceptance_mode == "llm_structured"
    assert cfg.protocol.atomic_commit is False
    assert cfg.protocol.ir_enforce is False
    assert cfg.institution_pressure.search_cost_per_public_round == 0.0
    assert cfg.institution_pressure.contact_expansion_cost == 0.0
    assert cfg.institution_pressure.standing_rule_bonus_or_cost_saving == 0.0
    assert cfg.institution_pressure.recurring_demand_mode == "none"

    for controller_id in cfg.controllers:
        visible = ex.visible_agents_for(cfg.protocol, world, controller_id)
        assert len(visible) == 2


def test_t0_recurring_search_configs_are_detachable_pair():
    control_path = ROOT / "configs" / "exchange_economy" / "treatments/t0/treatment_t0_recurring_search_no_rule_savings.json"
    savings_path = ROOT / "configs" / "exchange_economy" / "treatments/t0/treatment_t0_recurring_search_codified_rule_savings.json"
    control_raw = json.loads(control_path.read_text())
    savings_raw = json.loads(savings_path.read_text())
    control = ex.load_experiment_config(control_path)
    savings = ex.load_experiment_config(savings_path)

    assert control.rounds == 30
    assert savings.rounds == 30
    assert control.controllers == [1, 3, 5]
    assert savings.controllers == [1, 3, 5]
    assert control.protocol.response_scope == "solicited_public"
    assert savings.protocol.response_scope == "solicited_public"
    assert control.protocol.partial_clearing is True
    assert savings.protocol.partial_clearing is True
    assert control.protocol.private_acceptance_check is True
    assert savings.protocol.private_acceptance_check is True
    assert control.protocol.ir_enforce is False
    assert savings.protocol.ir_enforce is False
    assert control.institution_pressure.recurring_demand_mode == "stable_hidden_values"
    assert savings.institution_pressure.recurring_demand_mode == "stable_hidden_values"
    assert control.institution_pressure.search_cost_per_public_round == pytest.approx(0.05)
    assert savings.institution_pressure.search_cost_per_public_round == pytest.approx(0.05)
    assert control.institution_pressure.contact_expansion_cost == 0.0
    assert savings.institution_pressure.contact_expansion_cost == 0.0
    assert control.institution_pressure.standing_rule_bonus_or_cost_saving == 0.0
    assert savings.institution_pressure.standing_rule_bonus_or_cost_saving == pytest.approx(0.2)

    normalized_control = json.loads(json.dumps(control_raw))
    normalized_savings = json.loads(json.dumps(savings_raw))
    normalized_control["name"] = normalized_savings["name"]
    normalized_control["description"] = normalized_savings["description"]
    normalized_control["protocol"]["name"] = normalized_savings["protocol"]["name"]
    normalized_control["institution_pressure"]["standing_rule_bonus_or_cost_saving"] = (
        normalized_savings["institution_pressure"]["standing_rule_bonus_or_cost_saving"]
    )
    assert normalized_control == normalized_savings


def test_t0_recurring_search_prompt_discloses_only_active_pressure_knobs():
    control = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/t0/treatment_t0_recurring_search_no_rule_savings.json"
    )
    savings = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/t0/treatment_t0_recurring_search_codified_rule_savings.json"
    )
    forbidden_examples = [
        "auction",
        "clearing house",
        "clearinghouse",
        "registry",
        "market maker",
        "bilateral trade",
        "public solicitation",
    ]

    for cfg in [control, savings]:
        world = ex.make_world_from_config(cfg)
        audit = ex.validate_information_reveal_protocol(
            world,
            cfg.protocol,
            history=[],
            agent_ids=[1, 3, 5],
            controller_id=1,
        )
        prompt = ex._freeform_proposal_prompt(
            world,
            agent_id=1,
            round_index=1,
            history=[],
            communication_texts={},
            protocol=cfg.protocol,
        )
        lowered = prompt.lower()

        assert audit.ok, audit.format()
        assert "repeated demand conditions are stable across rounds" in lowered
        assert "search_cost_per_agent=0.05" in lowered
        assert "expanded contact costs" not in lowered
        for phrase in forbidden_examples:
            assert phrase not in lowered

    control_prompt = ex._freeform_proposal_prompt(
        ex.make_world_from_config(control),
        agent_id=1,
        round_index=1,
        history=[],
        communication_texts={},
        protocol=control.protocol,
    )
    savings_prompt = ex._freeform_proposal_prompt(
        ex.make_world_from_config(savings),
        agent_id=1,
        round_index=1,
        history=[],
        communication_texts={},
        protocol=savings.protocol,
    )

    assert "active reusable public rules can save" not in control_prompt.lower()
    assert "active reusable public rules can save later coordination cost by 0.2" in savings_prompt.lower()


def test_t0_indirect_routing_config_uses_per_contact_cost_without_rule_bonus():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/t0/treatment_t0_indirect_routing_per_contact_cost.json"
    )
    world = ex.make_world_from_config(cfg)
    prompt = ex._freeform_proposal_prompt(
        world,
        agent_id=1,
        round_index=1,
        history=[],
        communication_texts={},
        protocol=cfg.protocol,
    )
    lowered = prompt.lower()

    assert cfg.rounds == 30
    assert cfg.protocol.response_scope == "solicited_public"
    assert cfg.protocol.partial_clearing is True
    assert cfg.protocol.private_acceptance_check is True
    assert cfg.protocol.ir_enforce is False
    assert cfg.institution_pressure.recurring_demand_mode == "stable_hidden_values"
    assert cfg.institution_pressure.search_cost_per_public_round == 0.0
    assert cfg.institution_pressure.search_cost_per_contacted_agent == pytest.approx(0.05)
    assert cfg.institution_pressure.standing_rule_bonus_or_cost_saving == 0.0
    assert "repeated demand conditions are stable across rounds" in lowered
    assert "search_cost_per_contacted_agent=0.05" in lowered
    assert "targeted requests to fewer agents cost less than broad requests" in lowered
    assert "active reusable public rules can save" not in lowered


def test_per_contact_cost_counts_actual_prompted_responders_without_rule_discount():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    world.institutions.append({"id": "rule_x", "status": "active", "source_round": 1})
    pressure = ex.InstitutionPressureConfig(
        search_cost_per_contacted_agent=0.05,
        standing_rule_bonus_or_cost_saving=0.2,
    )

    cost = ex.apply_institutional_costs(
        world,
        pressure,
        round_index=2,
        contacted_agent_count=3,
    )

    assert cost["search_cost_basis"] == "prompted_responders"
    assert cost["contacted_agent_count"] == 3
    assert cost["search_cost_total"] == pytest.approx(0.15)
    assert cost["standing_rule_saving"] == 0.0
    assert cost["net_coordination_cost"] == pytest.approx(0.15)
    assert cost["active_institutions"] == 1


def test_t0_indirect_routing_charges_visible_contacts_when_no_public_expansion():
    world = ex.make_exchange_world(
        num_agents=10,
        num_resources=10,
        seed=23,
        institution_pressure=ex.InstitutionPressureConfig(search_cost_per_contacted_agent=0.05),
    )
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        visibility_seed=46,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )

    class NoOpPolicy:
        def communication_text(self, world, agent_id, round_index, history):
            return "PUBLIC ACTION\nMESSAGE: observation\nSETTLEMENT:\nnone"

        def propose_text(self, world, agent_id, round_index, history, communication_texts):
            return (
                "PUBLIC ACTION\n"
                "ADDRESSEES:\na3\n"
                "MESSAGE:\nQuiet visible-contact note.\n"
                "RESPONSE REQUEST:\nnone\n"
                "SETTLEMENT:\nnone\n"
                "CONSENT CONDITIONS:\nnone\n"
                "PUBLIC STATE UPDATE:\nnone\n"
                "NO-TRANSFER FALLBACK:\nno transfer"
            )

        def respond_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: response\nSETTLEMENT:\nnone"

        def finalize_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: finalize\nSETTLEMENT:\nnone"

        def compile_transcript(self, world, transcript):
            return ex.CompiledMechanism(
                proposer_id=transcript.controller_id,
                label="noop",
                summary="no transfer",
                transfers=[],
                consenting_agents=[],
                confidence=1.0,
            )

        def verify_compilation(self, world, transcript, mechanism):
            return mechanism

    result = ex.run_exchange_transcript(
        world,
        rounds=1,
        controllers=[1],
        policy=NoOpPolicy(),
        protocol=protocol,
    )

    cost = result.history[0].coordination_cost
    assert cost["search_cost_basis"] == "prompted_responders"
    assert cost["contacted_agent_count"] == 2
    assert result.coordination_cost_total == pytest.approx(0.1)


def test_partial_clearing_is_disclosed_in_cacheable_protocol_context_and_validates():
    world = ex.make_exchange_world(num_agents=5, num_resources=5, seed=23)
    protocol = ex.ProtocolConfig(
        information_reveal_profile="clean_market_v1",
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
        partial_clearing=True,
    )

    audit = ex.validate_information_reveal_protocol(
        world,
        protocol,
        agent_ids=[1, 2],
        controller_id=1,
    )
    prompt = ex._cacheable_protocol_context_text(protocol)

    assert audit.ok, audit.format()
    assert "Consent-subset finalization rule" in prompt
    assert "independent consented subset" in prompt
    assert "all-or-nothing" in prompt


def test_partial_clearing_finalizer_compiler_and_verifier_receive_same_rule():
    world = ex.make_exchange_world(num_agents=5, num_resources=5, seed=23)
    protocol = ex.ProtocolConfig(partial_clearing=True)
    transcript = ex.RoundTranscript(
        round_index=1,
        controller_id=1,
        proposal_text=(
            "PUBLIC ACTION\n"
            "ADDRESSEES:\na2, a3\n"
            "MESSAGE:\nTwo independent settlement rows are offered.\n"
            "RESPONSE REQUEST:\nPlease accept any row that works for you.\n"
            "SETTLEMENT:\na1 -> a2 r1 1; a1 -> a3 r1 1\n"
            "CONSENT CONDITIONS:\nEach row can clear independently.\n"
            "PUBLIC STATE UPDATE:\nnone\n"
            "NO-TRANSFER FALLBACK:\nNo transfer for rows without consent."
        ),
        response_texts={
            2: (
                "PUBLIC ACTION\nADDRESSEES:\na1\nMESSAGE:\nI accept my row.\n"
                "RESPONSE REQUEST:\nnone\nSETTLEMENT:\na1 -> a2 r1 1\n"
                "CONSENT CONDITIONS:\nI authorize this independent row.\n"
                "PUBLIC STATE UPDATE:\nnone\nNO-TRANSFER FALLBACK:\nnone"
            ),
            3: (
                "PUBLIC ACTION\nADDRESSEES:\na1\nMESSAGE:\nI reject my row.\n"
                "RESPONSE REQUEST:\nnone\nSETTLEMENT:\nnone\n"
                "CONSENT CONDITIONS:\nnone\nPUBLIC STATE UPDATE:\nnone\n"
                "NO-TRANSFER FALLBACK:\nNo transfer."
            ),
        },
        final_text="",
    )
    mechanism = ex.CompiledMechanism(
        proposer_id=1,
        label="partial_subset",
        summary="Only the consented independent row clears.",
        transfers=[ex.Transfer(1, 2, 1, 1)],
        consenting_agents=[1],
        confidence=0.9,
    )

    final_prompt = ex._freeform_finalize_prompt(world, 1, transcript, [], protocol=protocol)
    compile_prompt = ex._compile_transcript_prompt(world, transcript, protocol=protocol)
    verify_prompt = ex._verify_compilation_prompt(world, transcript, mechanism, protocol=protocol)

    for prompt in [final_prompt, compile_prompt, verify_prompt]:
        assert "Consent-subset finalization rule" in prompt
        assert "independent consented subset" in prompt
        assert "rejection or missing consent for one independent leg" in prompt


def test_agent_facing_history_sanitizes_compiler_mechanism_labels():
    world = ex.make_exchange_world(num_agents=5, num_resources=5, seed=23)
    protocol = ex.ProtocolConfig(
        information_reveal_profile="clean_market_v1",
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )
    history = [
        ex.RoundEvent(
            round_index=1,
            controller_id=1,
            proposer_id=1,
            kind="bilateral_trade_proposal",
            accepted=True,
            applied=True,
            welfare_after=110.0,
        ),
        ex.RoundEvent(
            round_index=2,
            controller_id=3,
            proposer_id=3,
            kind="three_way_clearinghouse_auction",
            accepted=False,
            applied=False,
            welfare_after=110.0,
        ),
    ]

    prompt = ex._freeform_proposal_prompt(
        world,
        agent_id=5,
        round_index=3,
        history=history,
        communication_texts={},
        protocol=protocol,
    )
    lowered = prompt.lower()

    assert "recent public history" in lowered
    for forbidden in ["bilateral", "three_way", "auction", "clearinghouse"]:
        assert forbidden not in lowered
    assert "outcome=applied_resource_transfer" in lowered
    assert "outcome=no_transfer" in lowered


def test_controller_contact_communication_scope_does_not_auto_prompt_every_agent():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        visibility_seed=911,
        public_broadcast=True,
        communication_scope="controller_contacts",
    )

    communication_ids = ex._communication_agent_ids_for(protocol, world, controller_id=1)

    assert 1 in communication_ids
    assert len(communication_ids) == 3
    assert communication_ids != list(range(1, 11))


def test_solicited_public_response_scope_requires_explicit_public_solicitation():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        visibility_seed=911,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )

    quiet = ex._response_agent_ids_for(
        protocol,
        world,
        controller_id=1,
        proposal_text="PUBLIC ACTION\nMESSAGE: I propose a direct trade with a5 only.\nSETTLEMENT:\nnone",
    )
    solicited = ex._response_agent_ids_for(
        protocol,
        world,
        controller_id=1,
        proposal_text=(
            "PUBLIC ACTION\n"
            "MESSAGE: All agents may opt in. Please respond with resources you offer and want.\n"
            "SETTLEMENT:\nnone"
        ),
    )

    assert quiet == ex.visible_agents_for(protocol, world, 1)
    assert solicited == [aid for aid in range(1, 11) if aid != 1]


def test_solicited_public_response_scope_honors_structured_action_fields():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        visibility_seed=911,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )

    structured = ex._response_agent_ids_for(
        protocol,
        world,
        controller_id=1,
        proposal_text=(
            "PUBLIC ACTION\n"
            "ADDRESSEES:\n"
            "all agents\n"
            "MESSAGE:\n"
            "checking for mutually useful rows\n"
            "RESPONSE REQUEST:\n"
            "share feasible counterparties and quantities\n"
            "SETTLEMENT:\n"
            "none\n"
            "CONSENT CONDITIONS:\n"
            "none\n"
            "PUBLIC STATE UPDATE:\n"
            "none\n"
            "NO-TRANSFER FALLBACK:\n"
            "no transfer"
        ),
    )

    assert structured == [aid for aid in range(1, 11) if aid != 1]


def test_solicited_public_response_scope_honors_controller_communication_request():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=1,
        visibility_seed=46,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )

    responders = ex._response_agent_ids_for(
        protocol,
        world,
        controller_id=1,
        proposal_text=(
            "PUBLIC ACTION\n"
            "ADDRESSEES:\n"
            "a4\n"
            "MESSAGE:\n"
            "I may propose to a visible contact.\n"
            "RESPONSE REQUEST:\n"
            "a4\n"
            "SETTLEMENT:\n"
            "none\n"
        ),
        communication_texts={
            1: (
                "PUBLIC ACTION\n"
                "ADDRESSEES:\n"
                "all agents\n"
                "MESSAGE:\n"
                "Anyone who can offer r6 should respond with terms.\n"
                "RESPONSE REQUEST:\n"
                "all agents respond with offers or opt in\n"
                "SETTLEMENT:\n"
                "none\n"
            )
        },
    )

    assert responders == [aid for aid in range(1, 11) if aid != 1]


def test_solicited_public_response_scope_honors_accept_counter_and_consent_requests():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        visibility_seed=911,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )

    structured = ex._response_agent_ids_for(
        protocol,
        world,
        controller_id=5,
        proposal_text=(
            "PUBLIC ACTION\n"
            "ADDRESSEES:\n"
            "a4, a6, all agents\n"
            "MESSAGE:\n"
            "I propose visible trades and invite any non-visible agents with useful resources.\n"
            "RESPONSE REQUEST:\n"
            "a4, a6, or any other agent to accept, reject, consent, propose trades, or counter-propose.\n"
            "SETTLEMENT:\n"
            "none\n"
            "CONSENT CONDITIONS:\n"
            "none\n"
            "PUBLIC STATE UPDATE:\n"
            "none\n"
            "NO-TRANSFER FALLBACK:\n"
            "no transfer"
        ),
    )

    assert structured == [aid for aid in range(1, 11) if aid != 5]


def test_solicited_public_response_scope_honors_targeted_nonvisible_addressees():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        visibility_seed=46,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )
    assert 9 not in ex.visible_agents_for(protocol, world, 1)

    targeted = ex._response_agent_ids_for(
        protocol,
        world,
        controller_id=1,
        proposal_text=(
            "PUBLIC ACTION\n"
            "ADDRESSEES:\n"
            "a9\n"
            "MESSAGE:\n"
            "Targeted request to a previously known counterparty.\n"
            "RESPONSE REQUEST:\n"
            "a9 should accept, reject, or counter-propose.\n"
            "SETTLEMENT:\n"
            "none\n"
            "CONSENT CONDITIONS:\n"
            "none\n"
            "PUBLIC STATE UPDATE:\n"
            "none\n"
            "NO-TRANSFER FALLBACK:\n"
            "no transfer"
        ),
    )

    assert targeted == [9]


def test_solicited_public_response_scope_does_not_expand_on_headings_only():
    world = ex.make_exchange_world(num_agents=10, num_resources=10, seed=23)
    protocol = ex.ProtocolConfig(
        visibility_mode="limited_contact",
        visible_agents_per_agent=2,
        visibility_seed=911,
        public_broadcast=True,
        communication_scope="controller_contacts",
        response_scope="solicited_public",
    )

    headings_only = ex._response_agent_ids_for(
        protocol,
        world,
        controller_id=1,
        proposal_text=(
            "PUBLIC ACTION\n"
            "ADDRESSEES:\n"
            "all agents\n"
            "MESSAGE:\n"
            "notifying the market that I may act later\n"
            "RESPONSE REQUEST:\n"
            "none\n"
            "SETTLEMENT:\n"
            "none\n"
            "CONSENT CONDITIONS:\n"
            "none\n"
            "PUBLIC STATE UPDATE:\n"
            "none\n"
            "NO-TRANSFER FALLBACK:\n"
            "no transfer"
        ),
    )

    assert headings_only == ex.visible_agents_for(protocol, world, 1)


def test_solicited_public_prompt_reveals_exact_trigger_without_raw_knob_names():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/public_solicitation/treatment_public_solicitation_solicited.json"
    )
    world = ex.make_world_from_config(cfg)

    prompt = ex._freeform_proposal_prompt(
        world,
        agent_id=1,
        round_index=1,
        history=[],
        communication_texts={},
        protocol=cfg.protocol,
    )
    lowered = prompt.lower()

    assert "information reveal protocol: clean_market_v1" in lowered
    assert "public response affordance" in lowered
    assert "uses addressees to ask" in lowered
    assert "uses response request to ask" in lowered
    assert "non-contact agents may be prompted to respond" in lowered
    assert "only visible/contactable agents respond" in lowered
    assert "public solicitation" not in lowered
    assert "response_scope" not in lowered
    assert "solicited_public" not in lowered
    assert "anti-anchor" not in lowered


def test_information_reveal_text_validator_detects_missing_and_extra_items():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "treatments/public_solicitation/treatment_public_solicitation_solicited.json"
    )
    world = ex.make_world_from_config(cfg)
    prompt = ex._freeform_proposal_prompt(
        world,
        agent_id=1,
        round_index=1,
        history=[],
        communication_texts={},
        protocol=cfg.protocol,
    )

    missing = prompt.replace("Public response affordance:", "Public response path:")
    missing_audit = ex.validate_information_reveal_texts(
        cfg.protocol,
        {"proposal:a1": missing},
        world=world,
    )
    extra_audit = ex.validate_information_reveal_texts(
        cfg.protocol,
        {"proposal:a1": prompt + "\nAnti-anchor example: rotating unanimity committee"},
        world=world,
    )

    assert not missing_audit.ok
    assert any("required" in item for item in missing_audit.violations)
    assert not extra_audit.ok
    assert any("forbidden" in item for item in extra_audit.violations)


def test_atomic_commit_runner_skips_controller_amend_finalization():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )

    class AtomicPolicy:
        protocol = ex.ProtocolConfig(atomic_commit=True, private_acceptance_check=True)

        def communication_text(self, world, agent_id, round_index, history):
            return "PUBLIC ACTION\nMESSAGE: observation\nSETTLEMENT:\nnone"

        def propose_text(self, world, agent_id, round_index, history, communication_texts):
            return (
                "PUBLIC ACTION\nMESSAGE: exact atomic swap\n"
                "SETTLEMENT:\n"
                "a1 | a2 | r1 | 1 | requires a1 and a2\n"
                "a2 | a1 | r2 | 1 | requires a1 and a2\n"
                "CONSENT CONDITIONS:\na1 and a2 must consent to this exact proposal\n"
                "PUBLIC STATE UPDATE:\nnone\n"
                "NO-TRANSFER FALLBACK:\nnone"
            )

        def respond_text(self, world, agent_id, transcript, history):
            return (
                "PUBLIC ACTION\nMESSAGE: I consent to the exact proposal.\n"
                "SETTLEMENT:\n"
                "a1 | a2 | r1 | 1 | consented exact proposal\n"
                "a2 | a1 | r2 | 1 | consented exact proposal\n"
                "CONSENT CONDITIONS:\nexact proposal only\n"
                "PUBLIC STATE UPDATE:\nnone\n"
                "NO-TRANSFER FALLBACK:\nnone"
            )

        def finalize_text(self, world, agent_id, transcript, history):
            raise AssertionError("atomic_commit should skip controller amend/finalization")

        def compile_transcript(self, world, transcript):
            assert "Atomic commit: no controller amendment phase" in transcript.final_text
            assert "a1 | a2 | r1 | 1" in transcript.final_text
            return ex.CompiledMechanism(
                proposer_id=1,
                label="atomic compiled swap",
                summary="swap r1 and r2",
                transfers=[
                    ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
                    ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
                ],
                consenting_agents=[1, 2],
                confidence=1.0,
            )

        def verify_compilation(self, world, transcript, mechanism):
            return mechanism

        def private_acceptance_texts(self, *args, **kwargs):
            raise AssertionError("atomic config disables the post-finalization private re-check")

    result = ex.run_exchange_transcript(
        world,
        rounds=1,
        controllers=[1],
        response_agent_ids=[2],
        policy=AtomicPolicy(),
        protocol=ex.ProtocolConfig(atomic_commit=True, private_acceptance_check=False),
    )

    assert result.applied_mechanisms == 1
    assert result.history[0].kind == "atomic compiled swap"


def test_private_acceptance_rejection_blocks_finalized_transfer():
    world = ex.ExchangeWorld(
        allocation=[
            [0, 1],
            [1, 0],
        ],
        preferences=[
            [4.0, 1.0],
            [1.0, 4.0],
        ],
    )
    before = world.copy_allocation()

    class RejectingPolicy:
        protocol = ex.ProtocolConfig(private_acceptance_check=True)

        def communication_text(self, world, agent_id, round_index, history):
            return "PUBLIC ACTION\nMESSAGE: observation\nSETTLEMENT:\nnone"

        def propose_text(self, world, agent_id, round_index, history, communication_texts):
            return "PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT:\na2 | a1 | r1 | 1 | requires a2"

        def respond_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: I consent\nSETTLEMENT:\na2 | a1 | r1 | 1 | consented by a2"

        def finalize_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: finalize\nSETTLEMENT:\na2 | a1 | r1 | 1 | consented by a2"

        def compile_transcript(self, world, transcript):
            return ex.CompiledMechanism(
                proposer_id=1,
                label="compiled transfer",
                summary="a2 gives r1 to a1",
                transfers=[ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1)],
                consenting_agents=[2],
                confidence=1.0,
            )

        def verify_compilation(self, world, transcript, mechanism):
            return mechanism

        def private_acceptance_texts(self, world, agent_ids, transcript, mechanism, history):
            assert agent_ids == [2]
            return {2: '{"approve": false, "reason": "negative for me"}'}

    result = ex.run_exchange_transcript(
        world,
        rounds=1,
        controllers=[1],
        policy=RejectingPolicy(),
        protocol=RejectingPolicy.protocol,
        response_agent_ids=[2],
    )

    assert result.history[0].applied is False
    assert "private acceptance rejected" in result.history[0].message
    assert world.allocation == before


def test_structured_private_acceptance_audit_classifies_wrong_positive_approval():
    world = ex.ExchangeWorld(
        allocation=[
            [0, 1],
            [1, 0],
        ],
        preferences=[
            [4.0, 1.0],
            [1.0, 4.0],
        ],
    )
    mechanism = ex.CompiledMechanism(
        proposer_id=1,
        label="bad private approval",
        summary="a2 gives valuable r1 for nothing",
        transfers=[ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1)],
        consenting_agents=[2],
        confidence=1.0,
    )
    decision_text = """
    {
      "own_debits_seen": [{"resource": "r1", "quantity": 1}],
      "own_credits_seen": [],
      "claimed_delta_sign": "positive",
      "counterpart_transfers_present": true,
      "same_bundle_authorized": true,
      "approve": true,
      "reason": "seems useful"
    }
    """

    audit = ex.audit_private_acceptance_decision(world, mechanism, agent_id=2, decision_text=decision_text)

    assert audit.approve is True
    assert audit.actual_delta < 0
    assert audit.actual_delta_sign == "negative"
    assert audit.sign_match is False
    assert audit.approval_correct is False
    assert audit.error_family == "wrong_sign_positive_approval"


def test_hybrid_private_acceptance_blocks_negative_llm_approval():
    world = ex.ExchangeWorld(
        allocation=[
            [0, 1],
            [1, 0],
        ],
        preferences=[
            [4.0, 1.0],
            [1.0, 4.0],
        ],
    )
    mechanism = ex.CompiledMechanism(
        proposer_id=1,
        label="bad private approval",
        summary="a2 gives valuable r1 for nothing",
        transfers=[ex.Transfer(from_agent=2, to_agent=1, resource=1, quantity=1)],
        consenting_agents=[2],
        confidence=1.0,
    )

    blocked, audits = ex.enforce_private_acceptance(
        mechanism,
        {
            2: (
                '{"own_debits_seen":[{"resource":"r1","quantity":1}],'
                '"own_credits_seen":[],"claimed_delta_sign":"positive",'
                '"counterpart_transfers_present":true,"same_bundle_authorized":true,'
                '"approve":true,"reason":"seems useful"}'
            )
        },
        world=world,
        mode="hybrid_block_bad",
    )

    assert blocked.transfers == []
    assert blocked.label == "private_acceptance_rejected"
    assert audits[0].error_family == "wrong_sign_positive_approval"


def test_default_private_acceptance_does_not_auto_block_malformed_output():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    good_swap = ex.CompiledMechanism(
        proposer_id=1,
        label="good swap",
        summary="both agents swap into better resources",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )

    verified, audits = ex.enforce_private_acceptance(
        good_swap,
        {
            1: "I computed this but forgot JSON",
            2: (
                '{"own_debits_seen":[{"resource":"r2","quantity":1}],'
                '"own_credits_seen":[{"resource":"r1","quantity":1}],'
                '"claimed_delta_sign":"positive",'
                '"counterpart_transfers_present":true,"same_bundle_authorized":true,'
                '"approve":true,"reason":"positive after settlement"}'
            ),
        },
        world=world,
        mode="llm_structured",
    )

    assert verified.transfers == good_swap.transfers
    assert audits[0].error_family == "malformed_private_acceptance"
    assert audits[0].approve is False
    assert audits[1].approve is True


def test_private_acceptance_invalid_quantity_is_malformed_not_crash():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    good_swap = ex.CompiledMechanism(
        proposer_id=1,
        label="good swap",
        summary="both agents swap into better resources",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )

    audit = ex.audit_private_acceptance_decision(
        world,
        good_swap,
        agent_id=1,
        decision_text=(
            '{"own_debits_seen":[{"resource":"r1","quantity":0}],'
            '"own_credits_seen":[{"resource":"r2","quantity":1}],'
            '"claimed_delta_sign":"positive",'
            '"counterpart_transfers_present":true,"same_bundle_authorized":true,'
            '"approve":true,"reason":"positive after settlement"}'
        ),
    )

    assert audit.error_family == "malformed_private_acceptance"
    assert audit.approve is False
    assert audit.quantity_match is False


def test_strict_private_acceptance_mode_still_blocks_malformed_output():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    good_swap = ex.CompiledMechanism(
        proposer_id=1,
        label="good swap",
        summary="both agents swap into better resources",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )

    blocked, audits = ex.enforce_private_acceptance(
        good_swap,
        {1: "not json", 2: '{"approve": true}'},
        world=world,
        mode="llm_structured_strict",
    )

    assert blocked.transfers == []
    assert blocked.label == "private_acceptance_rejected"
    assert audits[0].error_family == "malformed_private_acceptance"


def test_deterministic_oracle_private_acceptance_allows_only_positive_deltas():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    good_swap = ex.CompiledMechanism(
        proposer_id=1,
        label="good swap",
        summary="both agents swap into better resources",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )

    verified, audits = ex.enforce_private_acceptance(good_swap, {}, world=world, mode="deterministic_oracle")

    assert verified.transfers == good_swap.transfers
    assert [a.approve for a in audits] == [True, True]
    assert all(a.actual_delta > 0 for a in audits)


def test_runner_deterministic_oracle_private_acceptance_skips_llm_acceptance_call():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )
    protocol = ex.ProtocolConfig(
        private_acceptance_check=True,
        private_acceptance_mode="deterministic_oracle",
    )

    class OraclePolicy:
        def communication_text(self, world, agent_id, round_index, history):
            return "PUBLIC ACTION\nMESSAGE: observation\nSETTLEMENT:\nnone"

        def propose_text(self, world, agent_id, round_index, history, communication_texts):
            return "PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT:\nnone"

        def respond_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: response\nSETTLEMENT:\nnone"

        def finalize_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: finalize\nSETTLEMENT:\nnone"

        def compile_transcript(self, world, transcript):
            return ex.CompiledMechanism(
                proposer_id=1,
                label="good swap",
                summary="both agents swap into better resources",
                transfers=[
                    ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
                    ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
                ],
                consenting_agents=[1, 2],
                confidence=1.0,
            )

        def verify_compilation(self, world, transcript, mechanism):
            return mechanism

        def private_acceptance_texts(self, *args, **kwargs):
            raise AssertionError("deterministic oracle should not call LLM private acceptance")

    result = ex.run_exchange_transcript(
        world,
        rounds=1,
        controllers=[1],
        policy=OraclePolicy(),
        protocol=protocol,
        response_agent_ids=[2],
    )

    assert result.history[0].applied is True
    assert result.history[0].private_acceptance_audits


def test_run_summary_reports_private_acceptance_error_decomposition():
    bad_audit = ex.PrivateAcceptanceAudit(
        agent_id=2,
        approve=True,
        actual_delta=-1.0,
        actual_delta_sign="negative",
        claimed_delta_sign="positive",
        sign_match=False,
        debit_rows_match=True,
        credit_rows_match=True,
        quantity_match=True,
        counterpart_transfers_present=True,
        same_bundle_authorized=True,
        approval_correct=False,
        error_family="wrong_sign_positive_approval",
        reason="bad approval",
    )
    result = ex.RunResult(
        initial_allocation=[[0, 1], [1, 0]],
        final_allocation=[[1, 1], [0, 0]],
        history=[
            ex.RoundEvent(
                round_index=1,
                controller_id=1,
                kind="compiled_transfer",
                proposer_id=1,
                accepted=True,
                applied=True,
                feasible=True,
                individually_rational=False,
                agent_deltas={2: -1.0},
                welfare_after=2.0,
                message="bad applied transfer",
                private_acceptance_audits=[bad_audit],
            )
        ],
        initial_welfare=1.0,
        final_welfare=2.0,
        optimum_welfare=3.0,
        initial_welfare_ratio=0.0,
        final_welfare_ratio=0.5,
        initial_gini=0.0,
        final_gini=0.1,
    )

    summary = ex.summarize_run_errors(result)
    report = ex.render_error_decomposition_report(summary)

    assert summary["private_acceptance"]["agent_checks"] == 1
    assert summary["private_acceptance"]["bad_positive_approvals"] == 1
    assert summary["private_acceptance"]["error_families"]["wrong_sign_positive_approval"] == 1
    assert summary["applied_resource_ir_false"] == 1
    assert "wrong_sign_positive_approval" in report
    assert "Agent Decision Errors" in report


def test_build_run_summary_payload_includes_revision_fields():
    cfg = ex.load_experiment_config(
        ROOT / "configs" / "exchange_economy" / "diagnostics/public_solicitation/public_solicitation_institution_pressure.json"
    )
    world = ex.make_world_from_config(cfg)
    result = ex.run_exchange_transcript(
        world,
        rounds=1,
        controllers=[1],
        policy=type(
            "NoOpPolicy",
            (),
            {
                "communication_text": lambda self, world, agent_id, round_index, history: "PUBLIC ACTION\nMESSAGE: noop\nSETTLEMENT:\nnone",
                "propose_text": lambda self, world, agent_id, round_index, history, communication_texts: "PUBLIC ACTION\nMESSAGE: noop\nSETTLEMENT:\nnone",
                "respond_text": lambda self, world, agent_id, transcript, history: "PUBLIC ACTION\nMESSAGE: noop\nSETTLEMENT:\nnone",
                "finalize_text": lambda self, world, agent_id, transcript, history: "PUBLIC ACTION\nMESSAGE: noop\nSETTLEMENT:\nnone",
                "compile_transcript": lambda self, world, transcript: ex.CompiledMechanism(
                    proposer_id=transcript.controller_id,
                    label="noop",
                    summary="no executable effect",
                    transfers=[],
                    consenting_agents=[],
                    confidence=1.0,
                ),
                "verify_compilation": lambda self, world, transcript, mechanism: mechanism,
            },
        )(),
        protocol=cfg.protocol,
    )

    payload = ex.build_run_summary_payload(result, config=cfg, usage={"calls": 0})

    assert payload["config_name"] == "public_solicitation_institution_pressure"
    assert payload["utility_mode"] == "concave_separable"
    assert payload["institution_pressure"]["search_cost_per_public_round"] == pytest.approx(0.05)
    assert payload["protocol"]["private_acceptance_mode"] == "llm_structured"
    assert payload["coordination_cost_total"] > 0
    assert payload["final_net_welfare"] < payload["final_welfare"]
    assert "error_decomposition" in payload


def test_private_acceptance_approval_allows_finalized_transfer():
    world = ex.ExchangeWorld(
        allocation=[
            [1, 0],
            [0, 1],
        ],
        preferences=[
            [1.0, 4.0],
            [4.0, 1.0],
        ],
    )

    class ApprovingPolicy:
        protocol = ex.ProtocolConfig(private_acceptance_check=True)

        def communication_text(self, world, agent_id, round_index, history):
            return "PUBLIC ACTION\nMESSAGE: observation\nSETTLEMENT:\nnone"

        def propose_text(self, world, agent_id, round_index, history, communication_texts):
            return "PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT:\na1 | a2 | r1 | 1 | requires a1"

        def respond_text(self, world, agent_id, transcript, history):
            return "PUBLIC ACTION\nMESSAGE: I consent\nSETTLEMENT:\na2 | a1 | r2 | 1 | consented by a2"

        def finalize_text(self, world, agent_id, transcript, history):
            return (
                "PUBLIC ACTION\nMESSAGE: finalize\n"
                "SETTLEMENT:\na1 | a2 | r1 | 1 | consented by a1\n"
                "a2 | a1 | r2 | 1 | consented by a2"
            )

        def compile_transcript(self, world, transcript):
            return ex.CompiledMechanism(
                proposer_id=1,
                label="compiled swap",
                summary="swap r1 and r2",
                transfers=[
                    ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
                    ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
                ],
                consenting_agents=[1, 2],
                confidence=1.0,
            )

        def verify_compilation(self, world, transcript, mechanism):
            return mechanism

        def private_acceptance_texts(self, world, agent_ids, transcript, mechanism, history):
            assert agent_ids == [1, 2]
            return {
                1: '{"approve": true, "reason": "positive for me"}',
                2: '{"approve": true, "reason": "positive for me"}',
            }

    result = ex.run_exchange_transcript(
        world,
        rounds=1,
        controllers=[1],
        policy=ApprovingPolicy(),
        protocol=ApprovingPolicy.protocol,
        response_agent_ids=[2],
    )

    assert result.history[0].applied is True
    assert result.history[0].individually_rational is True
    assert world.allocation == [[0, 1], [1, 0]]


def test_private_acceptance_prompt_asks_for_private_json_approval_without_public_leakage():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=18)
    transcript = ex.RoundTranscript(
        round_index=1,
        controller_id=1,
        proposal_text="PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT:\na2 | a1 | r2 | 1 | requires a2",
        response_texts={2: "PUBLIC ACTION\nMESSAGE: I may accept\nSETTLEMENT:\na2 | a1 | r2 | 1 | consented"},
        final_text="PUBLIC ACTION\nMESSAGE: finalize\nSETTLEMENT:\na2 | a1 | r2 | 1 | consented",
    )
    mechanism = ex.CompiledMechanism(
        proposer_id=1,
        label="compiled transfer",
        summary="a2 gives r2 to a1",
        transfers=[ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1)],
        consenting_agents=[2],
        confidence=1.0,
    )

    prompt = ex._private_acceptance_prompt(world, agent_id=2, transcript=transcript, mechanism=mechanism, history=[])

    # the default prompt now ELICITS the explicit before/after utility computation (the validated
    # fix) and drops the "do not quote numbers" gag that suppressed it
    assert "compute your total utility for your CURRENT holdings" in prompt
    assert "after-utility is strictly larger" in prompt
    assert "Do not quote numeric private marginal utilities" not in prompt
    assert "own_debits_seen" in prompt
    assert "own_credits_seen" in prompt
    assert "Your credits in this mechanism" in prompt
    assert "approve" in prompt
    assert "JSON" in prompt
    assert "a2 -> a1 r2 quantity 1" in prompt


def test_private_acceptance_prompt_keeps_finalized_mechanism_in_cacheable_prefix():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=18)
    transcript = ex.RoundTranscript(
        round_index=1,
        controller_id=1,
        proposal_text="PUBLIC ACTION\nMESSAGE: proposal\nSETTLEMENT:\na2 | a1 | r2 | 1 | requires a2",
        response_texts={2: "PUBLIC ACTION\nMESSAGE: I may accept\nSETTLEMENT:\na2 | a1 | r2 | 1 | consented"},
        final_text="PUBLIC ACTION\nMESSAGE: finalize\nSETTLEMENT:\na2 | a1 | r2 | 1 | consented",
    )
    mechanism = ex.CompiledMechanism(
        proposer_id=1,
        label="compiled transfer",
        summary="a2 gives r2 to a1",
        transfers=[
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=0.5),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )

    p1 = ex._private_acceptance_prompt(world, agent_id=1, transcript=transcript, mechanism=mechanism, history=[])
    p2 = ex._private_acceptance_prompt(world, agent_id=2, transcript=transcript, mechanism=mechanism, history=[])

    marker = "Viewer-specific contact context:"
    prefix1 = p1.split(marker)[0]
    prefix2 = p2.split(marker)[0]

    assert marker in p1
    assert prefix1 == prefix2
    assert "Compiled finalized mechanism" in prefix1
    assert "return the decision as JSON" in prefix1
    assert "Private agent context:" not in prefix1
    assert "Your debits in this mechanism" not in prefix1
    assert f"{marker}\nPrivate acceptance target: agent a1." in p1
    assert f"{marker}\nPrivate acceptance target: agent a2." in p2


def test_private_acceptance_decision_requires_explicit_json_approval():
    assert ex._private_acceptance_approved('{"approve": true, "reason": "ok"}') is True
    assert ex._private_acceptance_approved(
        '{"own_debits_seen":[],"own_credits_seen":[],"claimed_delta_sign":"positive",'
        '"counterpart_transfers_present":true,"same_bundle_authorized":true,'
        '"approve": true, "reason": "ok"}'
    ) is True
    assert ex._private_acceptance_approved('{"approve": false, "reason": "bad"}') is False
    assert ex._private_acceptance_approved("I guess this is fine") is False


def test_ir_enforce_off_tags_violation_but_applies_on_blocks_and_preserves_world():
    """IR as a diagnostic: default tags (applies + flags) IR-violating trades; the
    ir_enforce control arm blocks them. Consent and feasibility are unchanged."""
    # a1 gives away r1 (which it values at 1) to a2 (who values it at 4). Welfare rises
    # (+3) but a1's own delta is -1 -> IR-violating for a1, even though both consent.
    alloc = [[1, 0], [0, 1]]
    prefs = [[1.0, 4.0], [4.0, 1.0]]
    mech = ex.CompiledMechanism(
        proposer_id=2,
        label="welfare_up_but_ir_violating",
        summary="a1 gives r1 to a2; a1 loses",
        transfers=[ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1)],
        consenting_agents=[1, 2],
        confidence=1.0,
    )

    # Default (tag, do not gate): trade applies, flagged IR-violating, not blocked.
    w_off = ex.ExchangeWorld(allocation=[row[:] for row in alloc], preferences=[row[:] for row in prefs])
    ev_off = ex.apply_compiled_mechanism(w_off, mech, round_index=1, controller_id=2)
    assert ev_off.applied is True
    assert ev_off.individually_rational is False
    assert ev_off.ir_blocked is False
    assert w_off.allocation[0][0] == 0  # a1's r1 was transferred

    # Control arm (ir_enforce on): IR-violating trade is blocked, world preserved.
    w_on = ex.ExchangeWorld(allocation=[row[:] for row in alloc], preferences=[row[:] for row in prefs])
    ev_on = ex.apply_compiled_mechanism(w_on, mech, round_index=1, controller_id=2, ir_enforce=True)
    assert ev_on.applied is False
    assert ev_on.ir_blocked is True
    assert ev_on.individually_rational is False
    assert w_on.allocation[0][0] == 1  # transfer blocked; allocation unchanged


def test_ir_enforce_still_applies_ir_valid_trade():
    """The control arm blocks only IR violations; a mutually beneficial swap still executes."""
    world = ex.ExchangeWorld(allocation=[[1, 0], [0, 1]], preferences=[[1.0, 4.0], [4.0, 1.0]])
    swap = ex.CompiledMechanism(
        proposer_id=1,
        label="mutual_swap",
        summary="both gain",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )
    ev = ex.apply_compiled_mechanism(world, swap, round_index=1, controller_id=1, ir_enforce=True)
    assert ev.applied is True
    assert ev.ir_blocked is False
    assert ev.individually_rational is True


def test_ir_enforce_config_flag_parses_and_defaults_off():
    proto = ex._protocol_config_from_dict({"name": "p", "ir_enforce": True})
    assert proto.ir_enforce is True
    assert ex.ProtocolConfig().ir_enforce is False


def test_reveal_all_private_values_parses_and_defaults_off():
    proto = ex._protocol_config_from_dict({"reveal_all_private_values": True})
    assert proto.reveal_all_private_values is True
    assert ex._protocol_config_from_dict({}).reveal_all_private_values is False
    assert ex.ProtocolConfig().reveal_all_private_values is False


def test_reveal_all_private_values_flag_discloses_every_agent_table():
    """Full-information condition: with the flag on, an agent's private context
    discloses every agent's utility table; off (default), only its own row."""
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=31)
    rows = [json.dumps(world.preferences[j]) for j in range(3)]
    assert len(set(rows)) == 3  # rows distinct -> presence/absence is meaningful

    off = ex._private_context_text(world, agent_id=1)  # default: hidden
    assert rows[0] in off
    assert rows[1] not in off
    assert rows[2] not in off

    on = ex._private_context_text(
        world, agent_id=1, protocol=ex.ProtocolConfig(reveal_all_private_values=True))
    for j in range(3):
        assert rows[j] in on, f"agent a{j + 1}'s table missing under full information"
    assert "full information" in on.lower()


def test_reveal_all_private_values_stays_out_of_cacheable_shared_prefix():
    """The disclosed tables live in the per-viewer private block, never the shared
    cache prefix (which must stay identical across viewers)."""
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=31)
    proto = ex.ProtocolConfig(reveal_all_private_values=True)
    prompt = ex._freeform_communication_prompt(
        world, agent_id=1, round_index=0, history=[], protocol=proto)
    prefix = prompt.split("Private agent context:")[0]
    # another agent's table must NOT leak into the shared/public prefix
    assert json.dumps(world.preferences[1]) not in prefix
    assert json.dumps(world.preferences[2]) not in prefix
