from __future__ import annotations

import asyncio
from pathlib import Path

from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.model_call.open_harnesses import LangChainProviderStrategyHarness
from aeread_families.single_offer.runner import FixedResponseProvider
from aeread_families.procurement_grounding.bakeoff import OPEN_WEIGHT_CANDIDATES
from aeread_families.procurement_grounding.runner import (
    build_offline_setup,
    build_openrouter_setup,
    finalize_procurement_execution,
    replay_procurement_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
STRONG_RESPONSE = (
    ROOT / "tests" / "fixtures" / "procurement_grounding" / "strong.json"
).read_text(encoding="utf-8")


def test_langchain_harness_identity_and_runtime_are_sealed() -> None:
    setup = build_openrouter_setup(
        OPEN_WEIGHT_CANDIDATES[0].route,
        seed=88001,
        harness=LangChainProviderStrategyHarness(),
    )
    profile = setup.plan.agent_profiles[0]
    pins = {pin.component_id: pin for pin in setup.plan.implementation_pins}

    assert profile.harness.id == "langchain_provider_strategy"
    assert profile.runtime.implementation == "aeread.shared_runner.model_call.open_harnesses"
    assert "langchain_provider_strategy/1.0" in setup.harnesses
    assert pins["langchain_provider_strategy"].kind == "harness"
    assert pins["aeread.shared_runner.model_call.open_harnesses"].kind == "runtime"
    assert "minimal_chat" not in pins


def test_langchain_lifecycle_accepts_the_nested_procurement_schema(tmp_path) -> None:
    setup = build_openrouter_setup(
        OPEN_WEIGHT_CANDIDATES[0].route,
        seed=88002,
        harness=LangChainProviderStrategyHarness(),
    )

    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={"openrouter": FixedResponseProvider(STRONG_RESPONSE)},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    )

    assert execution.episode_result.outcome["valid"] is True
    assert execution.episode_result.outcome["score"] == 1.0


def test_procurement_receipt_replays_state_and_score_without_provider(tmp_path) -> None:
    setup = build_offline_setup()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={"fake": FixedResponseProvider(STRONG_RESPONSE)},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    )

    receipt = finalize_procurement_execution(setup=setup, execution=execution)
    replayed = replay_procurement_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=tmp_path,
    )

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"
    assert receipt.scores[0].primary.value == 1.0
    assert replayed == receipt
