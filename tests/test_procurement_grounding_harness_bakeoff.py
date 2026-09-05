from __future__ import annotations

import pytest

from aeread_families.procurement_grounding.harness_bakeoff import (
    HARNESS_ARM_IDS,
    conservative_cost_ceiling,
    derive_inference_seeds,
    planned_probe,
    summarize_rows,
)


def test_procurement_harness_seeds_are_deterministic_and_unique() -> None:
    first = derive_inference_seeds(master_seed=20260831, count=5)
    second = derive_inference_seeds(master_seed=20260831, count=5)

    assert first == second
    assert len(set(first)) == 5
    assert derive_inference_seeds(master_seed=20260830, count=5) != first


def test_probe_plan_holds_model_route_and_budget_fixed() -> None:
    seeds = derive_inference_seeds(master_seed=20260831, count=3)
    plan = planned_probe(inference_seeds=seeds)

    assert tuple(plan["arms"]) == HARNESS_ARM_IDS
    assert plan["model"] == "z-ai/glm-5.3-flash"
    assert plan["provider"] == "DeepInfra"
    assert plan["inference_seeds"] == list(seeds)
    assert plan["conservative_cost_ceiling_usd"] == pytest.approx(
        conservative_cost_ceiling(arm_count=2, seed_count=3)
    )
    assert plan["conservative_cost_ceiling_usd"] < 0.02
    assert "single frozen case" in plan["claim_scope"]


def test_summary_pairs_only_complete_same_seed_rows() -> None:
    rows = [
        {
            "condition_id": "aeread_minimal_chat_v1",
            "inference_seed": 1,
            "status": "completed",
            "score": 1.0,
            "elapsed_seconds": 10.0,
            "cost_usd": 0.001,
            "input_tokens": 100,
            "cached_input_tokens": 0,
        },
        {
            "condition_id": "langchain_provider_strategy_v1",
            "inference_seed": 1,
            "status": "completed",
            "score": 0.9,
            "elapsed_seconds": 12.0,
            "cost_usd": 0.0012,
            "input_tokens": 120,
            "cached_input_tokens": 20,
        },
        {
            "condition_id": "aeread_minimal_chat_v1",
            "inference_seed": 2,
            "status": "completed",
            "score": 1.0,
            "elapsed_seconds": 9.0,
            "cost_usd": 0.0009,
            "input_tokens": 100,
            "cached_input_tokens": 100,
        },
        {
            "condition_id": "langchain_provider_strategy_v1",
            "inference_seed": 2,
            "status": "operational_failure",
            "elapsed_seconds": 1.0,
        },
    ]

    summary = summarize_rows(rows)

    assert summary["complete_pair_count"] == 1
    assert summary["paired_score_difference_mean"] == pytest.approx(-0.1)
    assert summary["conditions"]["aeread_minimal_chat_v1"]["reliability"] == 1.0
    assert (
        summary["conditions"]["langchain_provider_strategy_v1"]["reliability"]
        == 0.5
    )
    assert "not independent cases" in summary["inference"]


def test_public_failure_summary_recovers_nested_rate_limit_without_raw_text() -> None:
    from aeread_families.procurement_grounding.harness_bakeoff import _failure_summary

    try:
        try:
            raise RuntimeError("Error code: 429 - private provider payload")
        except RuntimeError as error:
            raise ValueError("scheduler wrapper") from error
    except ValueError as error:
        summary = _failure_summary(error)

    assert summary == {
        "failure_type": "ValueError",
        "failure_condition": "rate_limit",
        "failure_status_code": None,
    }
    assert "private provider payload" not in repr(summary)
