from aeread.exchange_subgame_oracles import (
    extract_subgame_episodes,
    summarize_d_dimensions,
    summarize_subgame_episodes,
)


def _swap_mechanism(label="swap", agents=(1, 2)):
    a, b = agents
    return {
        "mechanism_label": label,
        "summary": f"a{a} and a{b} swap resources",
        "transfers": [
            {"from": a, "to": b, "resource": f"r{a}", "quantity": 1.0},
            {"from": b, "to": a, "resource": f"r{b}", "quantity": 1.0},
        ],
        "institutional_updates": [],
        "consenting_agents": [a, b],
    }


def test_extracts_bilateral_offer_with_same_proposal_ir_oracle():
    records = [
        {
            "round_index": 1,
            "controller_id": 1,
            "proposal_text": "PUBLIC ACTION\nADDRESSEES: a2\nSETTLEMENT: ...",
            "verified_before_private_acceptance": _swap_mechanism("a1-a2 trade"),
            "event": {
                "applied": True,
                "accepted": True,
                "agent_deltas": {"1": 3.0, "2": 2.0},
                "private_acceptance_audits": [],
            },
        }
    ]

    episodes = extract_subgame_episodes(records, trace_id="trace-a")

    bilateral = [ep for ep in episodes if ep.episode_type == "bilateral_offer"]
    assert len(bilateral) == 1
    assert bilateral[0].participants == (1, 2)
    assert bilateral[0].oracle_kind == "same_proposal_ir_oracle"
    assert bilateral[0].actual_gain == 5.0
    assert bilateral[0].matched_frontier_gain == 5.0
    assert bilateral[0].frontier_ratio == 1.0
    assert bilateral[0].comparable_key == (
        "bilateral_offer",
        "same_proposal_ir_oracle",
        "n2",
        "positive_frontier",
    )


def test_private_acceptance_oracle_flags_wrong_rejection():
    records = [
        {
            "round_index": 4,
            "controller_id": 3,
            "verified_before_private_acceptance": _swap_mechanism("rejected-positive"),
            "event": {
                "applied": False,
                "accepted": False,
                "agent_deltas": {"3": 4.0, "4": 1.0},
                "private_acceptance_audits": [
                    {
                        "agent_id": 3,
                        "approve": False,
                        "actual_delta": 4.0,
                        "approval_correct": False,
                        "error_family": "wrong_sign_negative_rejection",
                    }
                ],
            },
        }
    ]

    episodes = extract_subgame_episodes(records)

    acceptance = [ep for ep in episodes if ep.episode_type == "private_acceptance"]
    assert len(acceptance) == 1
    assert acceptance[0].actor_id == 3
    assert acceptance[0].oracle_kind == "utility_delta_acceptance_oracle"
    assert acceptance[0].actual_gain == 0.0
    assert acceptance[0].matched_frontier_gain == 4.0
    assert acceptance[0].oracle_gap == 4.0


def test_extracts_multiparty_clearing_for_rejected_positive_bundle():
    records = [
        {
            "round_index": 6,
            "controller_id": 5,
            "verified_before_private_acceptance": {
                "mechanism_label": "three_way",
                "summary": "three-way settlement",
                "transfers": [
                    {"from": 4, "to": 5, "resource": "r4", "quantity": 2.0},
                    {"from": 5, "to": 4, "resource": "r6", "quantity": 3.0},
                    {"from": 6, "to": 5, "resource": "r5", "quantity": 2.0},
                ],
                "institutional_updates": [],
                "consenting_agents": [4, 5, 6],
            },
            "event": {
                "applied": False,
                "accepted": False,
                "agent_deltas": {"4": 3.0, "5": 1.0, "6": 2.0},
                "private_acceptance_audits": [],
            },
        }
    ]

    episodes = extract_subgame_episodes(records)

    clearing = [ep for ep in episodes if ep.episode_type == "multiparty_clearing"]
    assert len(clearing) == 1
    assert clearing[0].participants == (4, 5, 6)
    assert clearing[0].actual_gain == 0.0
    assert clearing[0].matched_frontier_gain == 6.0
    assert clearing[0].oracle_gap == 6.0


def test_same_proposal_ir_oracle_does_not_credit_applied_non_ir_bundle():
    records = [
        {
            "round_index": 7,
            "controller_id": 1,
            "verified_before_private_acceptance": _swap_mechanism("non-ir", agents=(1, 2)),
            "event": {
                "applied": True,
                "accepted": True,
                "agent_deltas": {"1": 4.0, "2": -1.0},
                "private_acceptance_audits": [],
            },
        }
    ]

    episodes = extract_subgame_episodes(records)

    bilateral = [ep for ep in episodes if ep.episode_type == "bilateral_offer"]
    assert len(bilateral) == 1
    assert bilateral[0].actual_gain == 0.0
    assert bilateral[0].matched_frontier_gain == 0.0
    assert bilateral[0].frontier_ratio is None


def test_detects_public_rule_update_and_repeated_dyad_reuse():
    records = [
        {
            "round_index": 1,
            "controller_id": 5,
            "verified_before_private_acceptance": {
                **_swap_mechanism("first a4-a5", agents=(4, 5)),
                "institutional_updates": [
                    {
                        "text": "ESTABLISH Rule_Stable_Exchange_v1: priority matching in subsequent rounds."
                    }
                ],
            },
            "event": {
                "applied": True,
                "accepted": True,
                "agent_deltas": {"4": 1.5, "5": 2.5},
                "private_acceptance_audits": [],
            },
        },
        {
            "round_index": 2,
            "controller_id": 5,
            "verified_before_private_acceptance": _swap_mechanism("repeat a4-a5", agents=(4, 5)),
            "event": {
                "applied": True,
                "accepted": True,
                "agent_deltas": {"4": 0.5, "5": 1.0},
                "private_acceptance_audits": [],
            },
        },
    ]

    episodes = extract_subgame_episodes(records)

    assert [ep.episode_type for ep in episodes].count("public_rule_update") == 1
    reuse = [ep for ep in episodes if ep.episode_type == "repeated_dyad_reuse"]
    assert len(reuse) == 1
    assert reuse[0].participants == (4, 5)
    assert reuse[0].actual_gain == 1.5
    assert reuse[0].matched_frontier_gain == 1.5


def test_summary_groups_by_episode_type_and_normalized_gain():
    records = [
        {
            "round_index": 1,
            "controller_id": 1,
            "verified_before_private_acceptance": _swap_mechanism("good"),
            "event": {
                "applied": True,
                "accepted": True,
                "agent_deltas": {"1": 2.0, "2": 2.0},
                "private_acceptance_audits": [],
            },
        },
        {
            "round_index": 2,
            "controller_id": 3,
            "verified_before_private_acceptance": _swap_mechanism("bad", agents=(3, 4)),
            "event": {
                "applied": False,
                "accepted": False,
                "agent_deltas": {"3": 3.0, "4": 1.0},
                "private_acceptance_audits": [],
            },
        },
    ]

    summary = summarize_subgame_episodes(extract_subgame_episodes(records))

    assert summary["by_type"]["bilateral_offer"]["count"] == 2
    assert summary["by_type"]["bilateral_offer"]["actual_gain"] == 4.0
    assert summary["by_type"]["bilateral_offer"]["matched_frontier_gain"] == 8.0
    assert summary["by_type"]["bilateral_offer"]["frontier_ratio"] == 0.5


def test_d_dimension_summary_maps_disclosure_to_settlement_pipeline():
    records = [
        {
            "round_index": 1,
            "controller_id": 1,
            "proposal_text": "PUBLIC ACTION\nADDRESSEES: all agents\nMESSAGE: everyone state wants",
            "verified_before_private_acceptance": _swap_mechanism("good"),
            "event": {
                "applied": True,
                "accepted": True,
                "agent_deltas": {"1": 2.0, "2": 2.0},
                "private_acceptance_audits": [
                    {"agent_id": 1, "approve": True, "actual_delta": 2.0},
                    {"agent_id": 2, "approve": True, "actual_delta": 2.0},
                ],
            },
        },
        {
            "round_index": 2,
            "controller_id": 1,
            "proposal_text": "PUBLIC ACTION\nADDRESSEES: all agents\nMESSAGE: everyone coordinate",
            "verified_before_private_acceptance": _swap_mechanism("blocked", agents=(1, 2)),
            "event": {
                "applied": False,
                "accepted": False,
                "agent_deltas": {"1": 3.0, "2": 1.0},
                "private_acceptance_audits": [
                    {"agent_id": 1, "approve": False, "actual_delta": 3.0},
                    {"agent_id": 2, "approve": True, "actual_delta": 1.0},
                ],
            },
        },
    ]

    dimensions = summarize_d_dimensions(extract_subgame_episodes(records))

    assert dimensions["D1_sender_disclosure"]["count"] == 2
    assert dimensions["D2_receiver_inference"]["opportunities_formed"] == 2
    assert dimensions["D2_receiver_inference"]["opportunity_per_disclosure"] == 1.0
    assert dimensions["D3_executable_proposal"]["frontier_ratio"] == 0.5
    assert dimensions["D4_settlement_evaluation"]["frontier_ratio"] == 0.625
    assert dimensions["D5_reuse_continuation"]["count"] == 1
