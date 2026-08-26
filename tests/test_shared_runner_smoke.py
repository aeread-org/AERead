from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from aeread.shared_runner.execution import EvidenceIntegrityError, execute_plan_cell
from aeread.shared_runner.smoke import (
    FixedResponseProvider,
    build_single_offer_smoke,
    main,
)
import aeread.shared_runner.execution as execution_module
import aeread.shared_runner.smoke as smoke_module


class CountingProvider(FixedResponseProvider):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return await super().complete(request)


class CapturingProvider(FixedResponseProvider):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return await super().complete(request)


def test_full_r1_to_r4_fake_model_smoke_is_executable_and_reconciled(tmp_path) -> None:
    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )
    provider = CountingProvider('{"offer":7}')

    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "runs",
            prompt_sources=setup.prompt_sources,
            providers={"fake": provider},
            pricing=setup.pricing,
        )
    )

    assert provider.calls == 1
    assert execution.episode_result.final_state["offer"] == 7
    assert execution.episode_result.outcome == {
        "valid": True,
        "reason": "submitted",
        "offer": 7,
    }
    assert execution.total_cost_usd == pytest.approx(0.0)
    assert execution.evidence.events_path.is_file()
    execution.evidence.audit_reconciliation()
    assert execution.action_executions[0].status == "succeeded"
    event_types = [event.event_type for event in execution.evidence.read_events()]
    assert event_types.index("phase_instance_started") < event_types.index(
        "logical_action_started"
    )
    assert event_types.index("action_parsed") < event_types.index(
        "logical_action_succeeded"
    )
    assert event_types.index("action_legality_checked") < event_types.index(
        "logical_action_succeeded"
    )
    assert event_types.index("transition_applied") < event_types.index(
        "episode_terminated"
    )
    assert event_types[-1] == "family_outcome_recorded"


def test_plan_cell_orchestrator_preflights_prompt_before_provider_call(tmp_path) -> None:
    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )
    provider = CountingProvider('{"offer":7}')

    with pytest.raises(EvidenceIntegrityError, match="prompt hash"):
        asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=tmp_path / "runs",
                prompt_sources={"single_offer_prompt_v1": "changed"},
                providers={"fake": provider},
                pricing=setup.pricing,
            )
        )
    assert provider.calls == 0


def test_episode_attempt_destination_is_immutable_and_never_overwritten(tmp_path) -> None:
    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )
    arguments = {
        "plan": setup.plan,
        "cell_id": setup.plan.cells[0].cell_id,
        "registry": setup.registry,
        "evidence_root": tmp_path / "runs",
        "prompt_sources": setup.prompt_sources,
        "providers": {"fake": FixedResponseProvider('{"offer":7}')},
        "pricing": setup.pricing,
    }
    first = asyncio.run(execute_plan_cell(**arguments))

    with pytest.raises(EvidenceIntegrityError, match="existing event log"):
        asyncio.run(execute_plan_cell(**arguments))
    assert first.evidence.events_path.is_file()
    first.evidence.verify_chain()


def test_fake_smoke_cli_prints_machine_readable_summary(tmp_path, capsys) -> None:
    assert main(["--provider", "fake", "--output", str(tmp_path / "cli")]) == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["outcome"] == {"valid": True, "reason": "submitted", "offer": 7}
    assert payload["total_cost_usd"] == 0.0


def test_smoke_implementation_pins_are_actual_source_hashes() -> None:
    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )
    pins = {pin.component_id: pin.sha256 for pin in setup.plan.implementation_pins}
    smoke_sha = hashlib.sha256(Path(smoke_module.__file__).read_bytes()).hexdigest()
    execution_sha = hashlib.sha256(
        Path(execution_module.__file__).read_bytes()
    ).hexdigest()
    assert pins["aeread.single_offer_v1"] == smoke_sha
    assert pins["single_offer_scorer_v1"] == smoke_sha
    assert pins["single_offer_generator_v1"] == smoke_sha
    assert pins["minimal_chat"] == execution_sha
    assert pins["aeread.shared_runner.execution"] == execution_sha


def test_claude_code_smoke_seals_runtime_schema_and_reviewed_pricing() -> None:
    runtime_sha256 = "a" * 64
    setup = build_single_offer_smoke(
        provider="claude_code",
        model="claude-haiku-4-5-20251001",
        revision="claude-haiku-4-5-20251001",
        provider_runtime={
            "runtime_version": "2.1.241",
            "runtime_sha256": runtime_sha256,
        },
    )

    profile = setup.plan.agent_profiles[0]
    assert profile.model.provider == "claude_code"
    assert profile.model.model == "claude-haiku-4-5-20251001"
    assert profile.harness.config["provider_runtime"] == {
        "runtime_version": "2.1.241",
        "runtime_sha256": runtime_sha256,
    }
    assert profile.harness.config["output_schema"]["required"] == ("offer",)
    pricing = setup.pricing[profile.model.model]
    assert pricing.input_per_million == 1.0
    assert pricing.cached_input_per_million == 0.10
    assert pricing.output_per_million == 5.0
    assert profile.budgets.max_cost_usd == 0.01


def test_claude_code_smoke_records_only_controls_the_cli_can_apply(tmp_path) -> None:
    setup = build_single_offer_smoke(
        provider="claude_code",
        model="claude-haiku-4-5-20251001",
        revision="claude-haiku-4-5-20251001",
        provider_runtime={
            "runtime_version": "2.1.241",
            "runtime_sha256": "a" * 64,
        },
    )
    provider = CapturingProvider('{"offer":7}')

    asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "runs",
            prompt_sources=setup.prompt_sources,
            providers={"claude_code": provider},
            pricing=setup.pricing,
        )
    )

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.temperature is None
    assert request.top_p is None
    assert request.max_output_tokens == 32_000


def test_openrouter_deepseek_smoke_seals_exact_route_controls_and_pricing() -> None:
    setup = build_single_offer_smoke(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash-0731",
        revision="deepseek/deepseek-v4-flash-20260731",
    )

    profile = setup.plan.agent_profiles[0]
    assert profile.model.base_url == "https://openrouter.ai/api/v1"
    assert profile.model.revision == "deepseek/deepseek-v4-flash-20260731"
    assert profile.sampling.temperature == 0.0
    assert profile.sampling.top_p == 1.0
    assert profile.sampling.seed == 71001
    assert profile.sampling.max_output_tokens == 512
    assert profile.reasoning.effort == "low"
    assert profile.budgets.max_cost_usd == 0.001
    assert profile.harness.config["provider_metadata"] == {
        "route_provider": "DeepInfra",
        "quantization": "fp8",
        "canonical_model": "deepseek/deepseek-v4-flash-20260731",
        "max_prompt_price_per_million": "0.08",
        "max_completion_price_per_million": "0.18",
    }
    pricing = setup.pricing[profile.model.model]
    assert pricing.input_per_million == 0.08
    assert pricing.cached_input_per_million == 0.016
    assert pricing.output_per_million == 0.18
