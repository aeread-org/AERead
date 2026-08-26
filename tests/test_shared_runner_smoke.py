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
