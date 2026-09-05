from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from types import MappingProxyType

import pytest

from aeread.shared_runner.task.execution import (
    ArenaChatClient,
    CanonicalResponse,
    ClaudeCodePrintClient,
    ConcurrentEvidenceWriterError,
    EvidenceSealedError,
    EvidenceIntegrityError,
    EvidenceStore,
    MinimalChatExecutor,
    OpenAIResponsesClient,
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    ToolExecutor,
    ToolFailure,
)
from aeread.shared_runner.model_call.harness import CanonicalMessage, NativeToolCall, ToolSchema
from aeread.shared_runner.run.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.task.scheduler import (
    DecisionRequest,
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
    episode_id_for_cell,
    run_episode,
)
from aeread.shared_runner.schemas import AgentProfile, CaseManifest


SYSTEM_PROMPT = (
    "Return only one JSON object matching the requested action schema. "
    "Do not add markdown."
)
FAKE_PRICING = TokenPricing(
    input_per_million=0.05,
    cached_input_per_million=0.005,
    output_per_million=0.40,
    pricing_id="fake-pricing-v1",
)


def _profile(
    *,
    max_action_attempts: int = 1,
    retryable_conditions: tuple[str, ...] = (),
    max_cost_usd: float = 0.05,
    model: str = "fake-model",
    provider: str = "fake",
) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": "subject_model_v1",
            "model": {
                "provider": provider,
                "model": model,
                "revision": "pinned-v1",
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": FAKE_PRICING.pricing_id,
                    "pricing_sha256": FAKE_PRICING.content_sha256(),
                },
            },
            "prompt": {
                "prompt_id": "fixture_action_prompt",
                "sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.task.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_low_v1",
                "effort": "low",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 80,
                "seed": None,
            },
            "budgets": {
                "max_logical_actions": 4,
                "timeout_seconds": 5.0,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                "max_action_attempts": max_action_attempts,
                "retryable_conditions": list(retryable_conditions),
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def _decision() -> DecisionRequest:
    return DecisionRequest(
        episode_id="episode_fixture",
        phase_instance_id="phase_instance_fixture",
        logical_action_id="logical_action_fixture",
        cell_id="cell_fixture",
        case_id="fixture_case",
        phase_id="offer",
        seat_id="buyer",
        role="buyer",
        profile_id="subject_model_v1",
        observation_schema="private_value_v1",
        action_schema="offer_v1",
        observation={"private_value": 11},
    )


def _evidence(tmp_path) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )


def _resume_evidence(tmp_path) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        resume=True,
    )


def _success_result(*, text: str = '{"offer":7}', cost: float | None = None):
    return ProviderResult(
        response_id="response_fixture",
        requested_model="fake-model",
        resolved_model="fake-model-v1",
        output_text=text,
        finish_reason="stop",
        input_tokens=20,
        cached_input_tokens=0,
        output_tokens=5,
        cost_usd=cost,
        raw_response={"id": "response_fixture", "output_text": text},
    )


class InspectingProvider:
    def __init__(self, evidence_path, outcomes):
        self.evidence_path = evidence_path
        self.outcomes = list(outcomes)
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        events = [json.loads(line) for line in self.evidence_path.read_text().splitlines()]
        assert events[-1]["event_type"] == "provider_call_started"
        assert events[-1]["provider_call_id"] == request.provider_call_id
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_evidence_store_refuses_a_concurrent_writer_before_the_first_event(tmp_path) -> None:
    first = _evidence(tmp_path)

    with pytest.raises(ConcurrentEvidenceWriterError):
        _evidence(tmp_path)

    first.close()
    resumed = _resume_evidence(tmp_path)
    resumed.append_event("continued", {"ok": True})
    resumed.close()


def test_evidence_store_resume_verifies_and_continues_the_hash_chain(tmp_path) -> None:
    first = _evidence(tmp_path)
    initial = first.append_event("first", {"value": 1})
    first.close()

    resumed = _resume_evidence(tmp_path)
    second = resumed.append_event("second", {"value": 2})

    assert second.sequence == 1
    assert second.prior_event_hash == initial.event_hash
    resumed.verify_chain()
    resumed.close()


def test_evidence_seal_is_persistent_idempotent_and_blocks_new_writes(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence.append_event("first", {"value": 1})
    sealed = evidence.seal()

    assert sealed.event_count == 1
    assert len(sealed.event_root_sha256) == 64
    assert len(sealed.artifact_root_sha256) == 64
    assert evidence.seal() == sealed
    with pytest.raises(EvidenceSealedError):
        evidence.append_event("late", {})
    with pytest.raises(EvidenceSealedError):
        evidence.put_artifact({"late": True})
    evidence.close()

    reopened = _resume_evidence(tmp_path)
    assert reopened.seal() == sealed
    with pytest.raises(EvidenceSealedError):
        reopened.append_event("later", {})
    reopened.close()


def test_read_only_audit_recovers_identity_and_verifies_a_sealed_generation(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    event = evidence.append_event("first", {"value": 1})
    seal = evidence.seal()
    root = evidence.root
    evidence.close()

    audited = EvidenceStore.audit_existing(root)

    assert audited.read_events() == (event,)
    assert audited.run_plan_id == seal.run_plan_id
    assert audited.cell_id == seal.cell_id
    assert audited.episode_id == seal.episode_id
    assert audited.episode_attempt_id == seal.episode_attempt_id
    assert audited.read_event_payload(event) == {"value": 1}
    assert audited.verify_seal() == seal
    audited.close()


def test_resume_rejects_a_symlink_replacement_for_the_event_log(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence.append_event("first", {"value": 1})
    evidence.close()
    external = tmp_path / "external.jsonl"
    external.write_text("untrusted\n", encoding="utf-8")
    events_path = tmp_path / "evidence" / "events.jsonl"
    events_path.unlink()
    events_path.symlink_to(external)

    with pytest.raises(EvidenceIntegrityError, match="regular file"):
        _resume_evidence(tmp_path)


def _executor(tmp_path, provider, *, profile=None, evidence=None):
    return MinimalChatExecutor(
        evidence=evidence or _evidence(tmp_path),
        profiles=(profile or _profile(),),
        prompt_sources={"fixture_action_prompt": SYSTEM_PROMPT},
        providers={"fake": provider},
        pricing={
            "fake-model": FAKE_PRICING
        },
    )


def test_provider_start_is_durable_before_call_and_all_records_reconcile(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    executor = _executor(tmp_path, provider, evidence=evidence)

    response = asyncio.run(executor(_decision()))
    assert isinstance(response, CanonicalResponse)
    assert response.text == '{"offer":7}'
    assert response.empty is False
    assert response.truncated is False
    assert len(provider.requests) == 1

    executor.finalize_logical_action(
        _decision().logical_action_id, valid=True, failure_code=None
    )
    evidence.audit_reconciliation()
    events = evidence.read_events()
    assert [event.sequence for event in events] == list(range(len(events)))
    assert [event.event_type for event in events] == [
        "logical_action_started",
        "action_attempt_started",
        "provider_call_started",
        "provider_call_succeeded",
        "action_attempt_succeeded",
        "logical_action_succeeded",
    ]
    evidence.verify_chain()


def test_declared_retry_creates_new_action_attempt_and_new_provider_call(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path,
        [ProviderFailure("timeout", "transient timeout", retryable=True), _success_result()],
    )
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=2, retryable_conditions=("timeout",)),
    )

    response = asyncio.run(executor(_decision()))
    executor.finalize_logical_action(
        _decision().logical_action_id, valid=True, failure_code=None
    )
    assert response.text == '{"offer":7}'
    execution = executor.execution_for(_decision().logical_action_id)
    assert len(execution.attempts) == 2
    assert [attempt.status for attempt in execution.attempts] == ["failed", "succeeded"]
    assert len({attempt.action_attempt_id for attempt in execution.attempts}) == 2
    assert len(provider.requests) == 2
    assert len({request.provider_call_id for request in provider.requests}) == 2
    assert execution.attempts[1].retry_reason == "timeout"
    assert execution.attempts[0].provider_calls[0].status == "outcome_unknown"
    assert "provider_call_outcome_unknown" in {
        event.event_type for event in evidence.read_events()
    }
    evidence.audit_reconciliation()


def test_nonretryable_provider_failure_is_terminal_and_not_hidden(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path,
        [ProviderFailure("authentication", "bad key", retryable=False)],
    )
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_action_attempts=3, retryable_conditions=("timeout",)),
    )

    with pytest.raises(ProviderFailure, match="bad key"):
        asyncio.run(executor(_decision()))
    assert len(provider.requests) == 1
    assert executor.execution_for(_decision().logical_action_id).status == "failed"
    evidence.audit_reconciliation()


def test_cancelled_provider_call_is_marked_outcome_unknown(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [asyncio.CancelledError()])
    executor = _executor(tmp_path, provider, evidence=evidence)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor(_decision()))
    event_types = [event.event_type for event in evidence.read_events()]
    assert "provider_call_outcome_unknown" in event_types
    assert "action_attempt_outcome_unknown" in event_types
    assert "logical_action_outcome_unknown" in event_types
    evidence.audit_reconciliation()


def test_prompt_hash_mismatch_fails_before_any_provider_or_event(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])

    with pytest.raises(EvidenceIntegrityError, match="prompt hash"):
        MinimalChatExecutor(
            evidence=evidence,
            profiles=(_profile(),),
            prompt_sources={"fixture_action_prompt": "changed prompt"},
            providers={"fake": provider},
            pricing={
                "fake-model": FAKE_PRICING
            },
        )
    assert not evidence.events_path.exists()
    assert provider.requests == []


def test_pricing_hash_mismatch_fails_before_any_provider_or_event(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    changed_pricing = TokenPricing(0.06, 0.005, 0.4, "fake-pricing-v1")

    with pytest.raises(EvidenceIntegrityError, match="pricing hash"):
        MinimalChatExecutor(
            evidence=evidence,
            profiles=(_profile(),),
            prompt_sources={"fixture_action_prompt": SYSTEM_PROMPT},
            providers={"fake": provider},
            pricing={"fake-model": changed_pricing},
        )
    assert not evidence.events_path.exists()
    assert provider.requests == []


def test_cost_budget_is_checked_from_recorded_usage_without_retry(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(evidence.events_path, [_success_result(cost=0.02)])
    executor = _executor(
        tmp_path,
        provider,
        evidence=evidence,
        profile=_profile(max_cost_usd=0.01),
    )

    with pytest.raises(EvidenceIntegrityError, match="cost budget"):
        asyncio.run(executor(_decision()))
    assert len(provider.requests) == 1
    assert executor.total_cost_usd == pytest.approx(0.02)
    evidence.audit_reconciliation()


def test_cost_budgets_are_enforced_per_profile_not_against_run_total(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = InspectingProvider(
        evidence.events_path,
        [_success_result(cost=0.01), _success_result(cost=0.01)],
    )
    first_profile = _profile(max_cost_usd=0.015)
    second_profile = replace(first_profile, profile_id="second_model_v1")
    executor = MinimalChatExecutor(
        evidence=evidence,
        profiles=(first_profile, second_profile),
        prompt_sources={"fixture_action_prompt": SYSTEM_PROMPT},
        providers={"fake": provider},
        pricing={"fake-model": FAKE_PRICING},
    )
    first_decision = _decision()
    second_decision = replace(
        first_decision,
        profile_id="second_model_v1",
        logical_action_id="logical_action_second",
    )

    asyncio.run(executor(first_decision))
    executor.finalize_logical_action(
        first_decision.logical_action_id, valid=True, failure_code=None
    )
    asyncio.run(executor(second_decision))
    executor.finalize_logical_action(
        second_decision.logical_action_id, valid=True, failure_code=None
    )
    assert executor.total_cost_usd == pytest.approx(0.02)
    evidence.audit_reconciliation()


def test_tool_executor_records_success_and_unknown_outcome(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)

    async def successful(arguments):
        events = evidence.read_events()
        assert events[-1].event_type == "tool_invocation_started"
        return {"echo": arguments["value"]}

    result, record = asyncio.run(
        tools.invoke(
            action_attempt_id="action_attempt_fixture",
            tool_id="echo",
            tool_version="1.0.0",
            arguments={"value": 3},
            implementation=successful,
            idempotency_supported=True,
            effect="read_only",
            tool_schema_sha256="a" * 64,
        )
    )
    assert result == {"echo": 3}
    assert record.status == "succeeded"

    async def cancelled(_arguments):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="cancelled",
                tool_version="1.0.0",
                arguments={},
                implementation=cancelled,
                idempotency_supported=False,
                effect="read_only",
                tool_schema_sha256="b" * 64,
            )
        )
    evidence.audit_reconciliation(entity_types=("tool_invocation",))
    assert "tool_invocation_outcome_unknown" in {
        event.event_type for event in evidence.read_events()
    }


def test_mutating_tool_requires_a_state_reader(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)

    async def mutate(_arguments):
        return {"status": "updated"}

    with pytest.raises(EvidenceIntegrityError, match="state_reader"):
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="refund_order",
                tool_version="1.0.0",
                arguments={"order_id": "order_1"},
                implementation=mutate,
                idempotency_supported=True,
                effect="mutating",
                tool_schema_sha256="c" * 64,
            )
        )
    assert evidence.read_events() == ()


def test_refund_mutation_records_before_after_and_state_diff(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    database = {"orders": {"order_1": {"status": "paid", "refund_usd": 0}}}

    async def refund(_arguments):
        database["orders"]["order_1"] = {"status": "refunded", "refund_usd": 25}
        return {"status": "refunded", "amount_usd": 25}

    result, record = asyncio.run(
        tools.invoke(
            action_attempt_id="action_attempt_fixture",
            tool_id="refund_order",
            tool_version="1.0.0",
            arguments={"order_id": "order_1", "amount_usd": 25},
            implementation=refund,
            idempotency_supported=True,
            effect="mutating",
            tool_schema_sha256="d" * 64,
            state_reader=lambda: database,
        )
    )

    assert result["status"] == "refunded"
    assert record.effect == "mutating"
    assert record.state_changed is True
    assert record.state_before_sha256 != record.state_after_sha256
    assert record.state_diff_sha256 is not None
    assert record.outcome_known is True
    evidence.audit_reconciliation(entity_types=("tool_invocation",))


def test_supply_chain_failure_after_partial_mutation_is_not_recorded_as_no_op(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10, "pending_orders": []}

    async def order_stock(_arguments):
        ledger["pending_orders"].append("po_7")
        raise ToolFailure("supplier_timeout", "supplier timed out after accepting PO", retryable=True)

    with pytest.raises(ToolFailure) as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget", "quantity": 5},
                implementation=order_stock,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="e" * 64,
                state_reader=lambda: ledger,
            )
        )

    record = captured.value.record
    assert record is not None
    assert record.status == "failed"
    assert record.failure_condition == "supplier_timeout"
    assert record.state_changed is True
    assert record.state_diff_sha256 is not None
    assert record.outcome_known is True
    evidence.audit_reconciliation(entity_types=("tool_invocation",))


def test_declared_read_only_tool_cannot_silently_mutate_observed_state(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    database = {"balance": 10}

    async def broken_read(_arguments):
        database["balance"] = 9
        return {"balance": 9}

    with pytest.raises(ToolFailure, match="read_only") as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="get_balance",
                tool_version="1.0.0",
                arguments={},
                implementation=broken_read,
                idempotency_supported=True,
                effect="read_only",
                tool_schema_sha256="f" * 64,
                state_reader=lambda: database,
            )
        )

    assert captured.value.record is not None
    assert captured.value.record.failure_condition == "tool_effect_violation"
    assert captured.value.record.state_changed is True
    evidence.audit_reconciliation(entity_types=("tool_invocation",))


def _reader_failing_after_first_call(state, failures: dict):
    calls = {"count": 0}

    def reader():
        calls["count"] += 1
        if calls["count"] > 1:
            error = RuntimeError("state snapshot io failure")
            failures["bookkeeping"] = error
            raise error
        return dict(state)

    return reader


def test_snapshot_failure_in_failure_handler_preserves_the_original_tool_failure(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10}
    failures: dict = {}

    async def order_stock(_arguments):
        ledger["inventory"] = 5
        raise ToolFailure("supplier_timeout", "supplier timed out", retryable=True)

    with pytest.raises(ToolFailure) as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget"},
                implementation=order_stock,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="a" * 64,
                state_reader=_reader_failing_after_first_call(ledger, failures),
            )
        )

    assert captured.value.condition == "supplier_timeout"
    assert captured.value.__context__ is failures["bookkeeping"]
    events = evidence.read_events()
    unknown = [e for e in events if e.event_type == "tool_invocation_outcome_unknown"]
    assert len(unknown) == 1
    payload = json.loads(evidence._read_artifact(unknown[0].payload_ref))
    assert payload["failure_condition"] == "bookkeeping_failed"
    assert payload["outcome_known"] is False


def test_snapshot_failure_during_cancellation_preserves_the_cancellation(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10}
    failures: dict = {}

    async def cancelled_mutation(_arguments):
        ledger["inventory"] = 5
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError) as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget"},
                implementation=cancelled_mutation,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="b" * 64,
                state_reader=_reader_failing_after_first_call(ledger, failures),
            )
        )

    assert captured.value.__context__ is failures["bookkeeping"]
    events = evidence.read_events()
    unknown = [e for e in events if e.event_type == "tool_invocation_outcome_unknown"]
    assert len(unknown) == 1
    payload = json.loads(evidence._read_artifact(unknown[0].payload_ref))
    assert payload["failure_condition"] == "bookkeeping_failed"
    assert payload["outcome_known"] is False


def test_snapshot_failure_after_unexpected_error_preserves_the_original_error(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10}
    failures: dict = {}

    async def crashing_mutation(_arguments):
        ledger["inventory"] = 5
        raise ValueError("implementation bug")

    with pytest.raises(ValueError, match="implementation bug") as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget"},
                implementation=crashing_mutation,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="c" * 64,
                state_reader=_reader_failing_after_first_call(ledger, failures),
            )
        )

    assert captured.value.__context__ is failures["bookkeeping"]
    events = evidence.read_events()
    unknown = [e for e in events if e.event_type == "tool_invocation_outcome_unknown"]
    assert len(unknown) == 1
    payload = json.loads(evidence._read_artifact(unknown[0].payload_ref))
    assert payload["failure_condition"] == "bookkeeping_failed"
    assert payload["outcome_known"] is False


def _fail_append_for(evidence, event_type: str, failures: dict) -> None:
    original_append = evidence.append_event

    def failing_append(kind, payload, **kwargs):
        if kind == event_type:
            error = RuntimeError("evidence write failure")
            failures["bookkeeping"] = error
            raise error
        return original_append(kind, payload, **kwargs)

    evidence.append_event = failing_append


def test_failed_event_write_failure_preserves_the_original_tool_failure(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10}
    failures: dict = {}
    _fail_append_for(evidence, "tool_invocation_failed", failures)

    async def order_stock(_arguments):
        ledger["inventory"] = 5
        raise ToolFailure("supplier_timeout", "supplier timed out", retryable=True)

    with pytest.raises(ToolFailure) as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget"},
                implementation=order_stock,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="d" * 64,
                state_reader=lambda: dict(ledger),
            )
        )

    assert captured.value.condition == "supplier_timeout"
    assert captured.value.__context__ is failures["bookkeeping"]


def test_unknown_event_write_failure_preserves_the_cancellation(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10}
    failures: dict = {}
    _fail_append_for(evidence, "tool_invocation_outcome_unknown", failures)

    async def cancelled_mutation(_arguments):
        ledger["inventory"] = 5
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError) as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget"},
                implementation=cancelled_mutation,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="e" * 64,
                state_reader=lambda: dict(ledger),
            )
        )

    assert captured.value.__context__ is failures["bookkeeping"]


def test_unknown_event_write_failure_preserves_the_unexpected_error(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10}
    failures: dict = {}
    _fail_append_for(evidence, "tool_invocation_outcome_unknown", failures)

    async def crashing_mutation(_arguments):
        ledger["inventory"] = 5
        raise ValueError("implementation bug")

    with pytest.raises(ValueError, match="implementation bug") as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget"},
                implementation=crashing_mutation,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="f" * 64,
                state_reader=lambda: dict(ledger),
            )
        )

    assert captured.value.__context__ is failures["bookkeeping"]


def test_composed_snapshot_and_event_write_failure_still_preserves_the_original(
    tmp_path,
) -> None:
    """Both bookkeeping layers fail: the post-effect snapshot raises AND the
    outcome_unknown event write raises. The caller must still see the tool's
    own failure, never either bookkeeping error."""

    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    ledger = {"inventory": 10}
    reader_failures: dict = {}
    append_failures: dict = {}
    _fail_append_for(evidence, "tool_invocation_outcome_unknown", append_failures)

    async def order_stock(_arguments):
        ledger["inventory"] = 5
        raise ToolFailure("supplier_timeout", "supplier timed out", retryable=True)

    with pytest.raises(ToolFailure) as captured:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="place_purchase_order",
                tool_version="1.0.0",
                arguments={"sku": "widget"},
                implementation=order_stock,
                idempotency_supported=False,
                effect="mutating",
                tool_schema_sha256="9" * 64,
                state_reader=_reader_failing_after_first_call(ledger, reader_failures),
            )
        )

    assert captured.value.condition == "supplier_timeout"
    assert "bookkeeping" in append_failures, "the unknown-event write must have failed"


def test_stub_state_reader_on_a_nonidempotent_mutation_leaves_a_typed_trace(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    accounts = {"balance": 100}

    async def debit(_arguments):
        accounts["balance"] = 70
        return {"debited": 30}

    _, record = asyncio.run(
        tools.invoke(
            action_attempt_id="action_attempt_fixture",
            tool_id="debit_account",
            tool_version="1.0.0",
            arguments={"amount": 30},
            implementation=debit,
            idempotency_supported=False,
            effect="mutating",
            tool_schema_sha256="a" * 64,
            state_reader=lambda: {"balance": 100},
        )
    )

    assert record.status == "succeeded"
    assert record.state_changed is False
    events = evidence.read_events()
    unobserved = [
        event
        for event in events
        if event.event_type == "tool_invocation_mutation_unobserved"
    ]
    assert len(unobserved) == 1
    assert unobserved[0].tool_invocation_id == record.tool_invocation_id
    payload = json.loads(evidence._read_artifact(unobserved[0].payload_ref))
    assert payload["condition"] == "mutation_unobserved"
    assert payload["tool_id"] == "debit_account"
    evidence.audit_reconciliation(entity_types=("tool_invocation",))


def test_an_observed_change_or_declared_idempotency_leaves_no_unobserved_trace(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    accounts = {"balance": 100}

    async def debit(_arguments):
        accounts["balance"] = 70
        return {"debited": 30}

    asyncio.run(
        tools.invoke(
            action_attempt_id="action_attempt_fixture",
            tool_id="debit_account",
            tool_version="1.0.0",
            arguments={"amount": 30},
            implementation=debit,
            idempotency_supported=False,
            effect="mutating",
            tool_schema_sha256="a" * 64,
            state_reader=lambda: dict(accounts),
        )
    )

    async def idempotent_noop(_arguments):
        return {"already": "cancelled"}

    asyncio.run(
        tools.invoke(
            action_attempt_id="action_attempt_fixture",
            tool_id="cancel_order",
            tool_version="1.0.0",
            arguments={"order_id": "order_1"},
            implementation=idempotent_noop,
            idempotency_supported=True,
            effect="mutating",
            tool_schema_sha256="b" * 64,
            state_reader=lambda: dict(accounts),
        )
    )

    event_types = {event.event_type for event in evidence.read_events()}
    assert "tool_invocation_mutation_unobserved" not in event_types


async def _echo_tool(arguments):
    return {"echo": arguments.get("value")}


def _minted_invocation_id(tools: ToolExecutor, value: int) -> str:
    _, record = asyncio.run(
        tools.invoke(
            action_attempt_id="action_attempt_fixture",
            tool_id="echo",
            tool_version="1.0.0",
            arguments={"value": value},
            implementation=_echo_tool,
            idempotency_supported=True,
            effect="read_only",
            tool_schema_sha256="a" * 64,
        )
    )
    return record.tool_invocation_id


def test_resumed_executor_never_reuses_a_minted_tool_invocation_id(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    first_id = _minted_invocation_id(ToolExecutor(evidence), value=1)
    evidence.close()

    resumed = _resume_evidence(tmp_path)
    second_id = _minted_invocation_id(ToolExecutor(resumed), value=2)

    assert first_id != second_id
    resumed.audit_reconciliation(entity_types=("tool_invocation",))


def test_two_live_executors_over_one_store_never_mint_the_same_id(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    first_executor = ToolExecutor(evidence)
    second_executor = ToolExecutor(evidence)

    first_id = _minted_invocation_id(first_executor, value=1)
    second_id = _minted_invocation_id(second_executor, value=2)

    assert first_id != second_id
    evidence.audit_reconciliation(entity_types=("tool_invocation",))


def test_legacy_ids_are_resume_stable_when_mixed_with_explicit_id_traffic(
    tmp_path,
) -> None:
    """KernelToolPort passes explicit ids; those invocations append started
    events too. A legacy mint after explicit traffic must produce the same id
    whether the run was uninterrupted or resumed past the explicit call."""

    def explicit_invocation(tools: ToolExecutor) -> None:
        asyncio.run(
            tools.invoke(
                action_attempt_id="action_attempt_fixture",
                tool_id="echo",
                tool_version="1.0.0",
                arguments={"value": 0},
                implementation=_echo_tool,
                idempotency_supported=True,
                effect="read_only",
                tool_schema_sha256="a" * 64,
                tool_invocation_id="tool_invocation_explicit_0",
            )
        )

    uninterrupted = EvidenceStore(
        tmp_path / "uninterrupted",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    tools = ToolExecutor(uninterrupted)
    explicit_invocation(tools)
    expected = _minted_invocation_id(tools, value=1)
    uninterrupted.close()

    interrupted = EvidenceStore(
        tmp_path / "interrupted",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    explicit_invocation(ToolExecutor(interrupted))
    interrupted.close()
    resumed = EvidenceStore(
        tmp_path / "interrupted",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        resume=True,
    )
    actual = _minted_invocation_id(ToolExecutor(resumed), value=1)
    resumed.close()

    assert actual == expected


def test_resumed_executor_reproduces_the_uninterrupted_id_sequence(tmp_path) -> None:
    uninterrupted = EvidenceStore(
        tmp_path / "uninterrupted",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    tools = ToolExecutor(uninterrupted)
    expected = [_minted_invocation_id(tools, value=1), _minted_invocation_id(tools, value=2)]
    uninterrupted.close()

    interrupted = EvidenceStore(
        tmp_path / "interrupted",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    first = _minted_invocation_id(ToolExecutor(interrupted), value=1)
    interrupted.close()
    resumed = EvidenceStore(
        tmp_path / "interrupted",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        resume=True,
    )
    second = _minted_invocation_id(ToolExecutor(resumed), value=2)
    resumed.close()

    assert [first, second] == expected


class FakeResponsesAPI:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_openai_fixture",
            model="gpt-5-nano-2025-08-07",
            status="completed",
            output_text='{"offer":7}',
            incomplete_details=None,
            usage=SimpleNamespace(
                input_tokens=31,
                output_tokens=9,
                input_tokens_details=SimpleNamespace(cached_tokens=4),
            ),
            model_dump=lambda mode: {
                "id": "resp_openai_fixture",
                "model": "gpt-5-nano-2025-08-07",
                "status": "completed",
                "output_text": '{"offer":7}',
            },
        )


def test_openai_responses_adapter_uses_explicit_supported_request_fields() -> None:
    responses = FakeResponsesAPI()
    sdk = SimpleNamespace(responses=responses)
    client = OpenAIResponsesClient(sdk_client=sdk)
    request = ProviderRequest(
        provider_call_id="provider_call_fixture",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-5-nano-2025-08-07",
        revision="gpt-5-nano-2025-08-07",
        instructions=SYSTEM_PROMPT,
        input_text='{"observation":{"private_value":11},"action_schema":"offer_v1"}',
        temperature=0.0,
        top_p=None,
        max_output_tokens=80,
        reasoning_effort="low",
        timeout_seconds=5.0,
        request_sha256="",
    ).with_computed_hash()

    result = asyncio.run(client.complete(request))
    assert responses.kwargs == {
        "model": "gpt-5-nano-2025-08-07",
        "instructions": SYSTEM_PROMPT,
        "input": request.input_text,
        "max_output_tokens": 80,
        "reasoning": {"effort": "low"},
        "store": False,
    }
    assert result.response_id == "resp_openai_fixture"
    assert result.resolved_model == "gpt-5-nano-2025-08-07"
    assert result.input_tokens == 31
    assert result.cached_input_tokens == 4
    assert result.output_tokens == 9


def test_openai_responses_adapter_refuses_native_chat_messages() -> None:
    """§6: the Responses adapter never learned native tool calls, so a
    request built for `native_tool_chat` must fail typed, not silently drop
    the messages and fall back to `input_text`."""
    responses = FakeResponsesAPI()
    sdk = SimpleNamespace(responses=responses)
    client = OpenAIResponsesClient(sdk_client=sdk)
    request = replace(
        ProviderRequest(
            provider_call_id="provider_call_fixture",
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-5-nano-2025-08-07",
            revision="gpt-5-nano-2025-08-07",
            instructions=SYSTEM_PROMPT,
            input_text="ignored",
            temperature=0.0,
            top_p=None,
            max_output_tokens=80,
            reasoning_effort="low",
            timeout_seconds=5.0,
            request_sha256="",
        ),
        messages=(CanonicalMessage(role="user", content="hi"),),
    ).with_computed_hash()

    with pytest.raises(ProviderFailure) as captured:
        asyncio.run(client.complete(request))
    assert captured.value.condition == "provider_contract"
    assert responses.kwargs is None


def test_openai_adapter_rejects_missing_responses_surface() -> None:
    with pytest.raises(EvidenceIntegrityError, match="Responses API"):
        OpenAIResponsesClient(sdk_client=SimpleNamespace())


def test_openai_adapter_requires_key_before_constructing_default_sdk(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EvidenceIntegrityError, match="OPENAI_API_KEY"):
        OpenAIResponsesClient()


class FakeOpenRouterCompletions:
    def __init__(
        self,
        *,
        selected_provider: str = "DeepInfra",
        attempt: int = 1,
        include_attempts: bool = True,
        content: object = '{"offer":7}',
    ) -> None:
        self.kwargs = None
        self.selected_provider = selected_provider
        self.attempt = attempt
        self.include_attempts = include_attempts
        self.content = content

    async def create(self, **kwargs):
        self.kwargs = kwargs
        routing_metadata = {
            "requested": "deepseek/deepseek-v4-flash-0731",
            "strategy": "direct",
            "region": "iad",
            "summary": f"available=1, selected={self.selected_provider}",
            "attempt": self.attempt,
            "is_byok": False,
            "endpoints": {
                "total": 1,
                "available": [
                    {
                        "model": "deepseek/deepseek-v4-flash-20260731",
                        "provider": self.selected_provider,
                        "selected": True,
                    }
                ],
            },
        }
        if self.include_attempts:
            routing_metadata["attempts"] = [
                {
                    "model": "deepseek/deepseek-v4-flash-20260731",
                    "provider": self.selected_provider,
                    "status": 200,
                }
            ]
        raw = {
            "id": "gen_openrouter_fixture",
            "model": "deepseek/deepseek-v4-flash-0731",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": self.content},
                }
            ],
            "usage": {
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "total_tokens": 168,
                "prompt_tokens_details": {"cached_tokens": 7},
                "cost": 0.00001726,
                "is_byok": False,
            },
            "openrouter_metadata": routing_metadata,
        }
        return SimpleNamespace(model_dump=lambda mode: raw)


def _openrouter_request() -> ProviderRequest:
    output_schema = {
        "type": "object",
        "properties": {"offer": {"type": "integer", "minimum": 0}},
        "required": ["offer"],
        "additionalProperties": False,
    }
    return ProviderRequest(
        provider_call_id="provider_call_openrouter_fixture",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="deepseek/deepseek-v4-flash-0731",
        revision="deepseek/deepseek-v4-flash-20260731",
        instructions=SYSTEM_PROMPT,
        input_text='{"observation":{"private_value":11},"action_schema":"offer_v1"}',
        temperature=0.0,
        top_p=1.0,
        max_output_tokens=512,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        max_cost_usd=0.001,
        output_schema=output_schema,
        provider_metadata={
            "route_provider": "DeepInfra",
            "quantization": "fp8",
            "canonical_model": "deepseek/deepseek-v4-flash-20260731",
            "max_prompt_price_per_million": "0.08",
            "max_completion_price_per_million": "0.18",
        },
        seed=71001,
    ).with_computed_hash()


# --- Golden hash: ProviderRequest.request_sha256 is unaffected by the new
# native fields (§6, stage 2) -- they default to None and are deliberately
# excluded from the hash payload, since `input_text` already carries a
# canonical serialization of messages/tools for every response mode. ---


def test_provider_request_sha256_is_unchanged_by_the_new_native_fields() -> None:
    request = _openrouter_request()
    assert request.messages is None
    assert request.tools is None
    assert request.reasoning_token_budget is None
    assert (
        request.request_sha256
        == "f440c8eb12eb57980096d6f7742b30a707590f15bf3f20065ff1c9f71fc0a03a"
    )


def test_openrouter_adapter_pins_deepseek_route_and_parses_usage() -> None:
    completions = FakeOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    request = _openrouter_request()

    result = asyncio.run(client.complete(request))

    assert completions.kwargs == {
        "model": "deepseek/deepseek-v4-flash-0731",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request.input_text},
        ],
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 71001,
        "max_tokens": 512,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "aeread_action",
                "strict": True,
                "schema": request.output_schema,
            },
        },
        "tools": [],
        "stream": False,
        "extra_headers": {"X-OpenRouter-Metadata": "enabled"},
        "extra_body": {
            "reasoning": {"effort": "low"},
            "provider": {
                "only": ["DeepInfra"],
                "order": ["DeepInfra"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "quantizations": ["fp8"],
                "max_price": {"prompt": "0.08", "completion": "0.18"},
            },
        },
    }
    assert result.output_text == '{"offer":7}'
    assert result.requested_model == "deepseek/deepseek-v4-flash-0731"
    assert result.resolved_model == "deepseek/deepseek-v4-flash-20260731"
    assert result.input_tokens == 123
    assert result.cached_input_tokens == 7
    assert result.output_tokens == 45
    assert result.cost_usd == pytest.approx(0.00001726)


def test_arena_adapter_sends_selected_model_and_parses_json() -> None:
    response = SimpleNamespace(
        model_dump=lambda mode: {
            "id": "arena-response",
            "model": "glm-5p2",
            "choices": [
                {
                    "message": {"content": 'Result: {"offer":7}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 21,
                "completion_tokens": 8,
                "prompt_tokens_details": {"cached_tokens": 3},
            },
        }
    )

    class Completions:
        kwargs = None

        async def create(self, **kwargs):
            self.kwargs = kwargs
            return response

    completions = Completions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = ArenaChatClient(sdk_client=sdk)
    request = ProviderRequest(
        provider_call_id="arena-call",
        provider="arena",
        base_url="https://api.preview.arena.ai/v1",
        model="glm-5p2",
        revision="glm-5p2",
        instructions=SYSTEM_PROMPT,
        input_text='{"observation":{}}',
        temperature=0.0,
        top_p=None,
        max_output_tokens=512,
        reasoning_effort="low",
        timeout_seconds=120.0,
        request_sha256="",
        output_schema={
            "type": "object",
            "properties": {"offer": {"type": "integer"}},
            "required": ["offer"],
        },
    ).with_computed_hash()

    result = asyncio.run(client.complete(request))

    assert completions.kwargs["model"] == "glm-5p2"
    assert completions.kwargs["reasoning_effort"] == "low"
    assert result.output_text == '{"offer":7}'
    assert result.resolved_model == "glm-5p2"
    assert result.input_tokens == 21
    assert result.cached_input_tokens == 3
    assert result.output_tokens == 8
    assert result.cost_usd is None


def test_openrouter_adapter_serializes_a_frozen_schema_as_plain_json() -> None:
    completions = FakeOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    frozen_schema = MappingProxyType(
        {
            "type": "object",
            "properties": MappingProxyType(
                {"offer": MappingProxyType({"type": "integer", "minimum": 0})}
            ),
            "required": ("offer",),
            "additionalProperties": False,
        }
    )
    request = replace(_openrouter_request(), output_schema=frozen_schema).with_computed_hash()

    asyncio.run(client.complete(request))

    transmitted_schema = completions.kwargs["response_format"]["json_schema"]["schema"]
    assert transmitted_schema == {
        "type": "object",
        "properties": {"offer": {"type": "integer", "minimum": 0}},
        "required": ["offer"],
        "additionalProperties": False,
    }
    json.dumps(completions.kwargs)


def test_openrouter_adapter_preserves_empty_completion_for_visible_retry() -> None:
    completions = FakeOpenRouterCompletions(content=None)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)

    result = asyncio.run(client.complete(_openrouter_request()))

    assert result.output_text == ""
    assert result.resolved_model == "deepseek/deepseek-v4-flash-20260731"
    assert result.input_tokens == 123
    assert result.output_tokens == 45
    assert result.cost_usd == pytest.approx(0.00001726)


def test_openrouter_adapter_preserves_malformed_model_output_and_exact_usage() -> None:
    completions = FakeOpenRouterCompletions(content='{"offer":')
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)

    result = asyncio.run(client.complete(_openrouter_request()))

    assert result.output_text == '{"offer":'
    assert result.resolved_model == "deepseek/deepseek-v4-flash-20260731"
    assert result.input_tokens == 123
    assert result.cached_input_tokens == 7
    assert result.output_tokens == 45
    assert result.cost_usd == pytest.approx(0.00001726)
    assert result.raw_response["choices"][0]["message"]["content"] == '{"offer":'


def test_openrouter_adapter_omits_unavailable_sampling_controls() -> None:
    completions = FakeOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    request = replace(_openrouter_request(), temperature=None, top_p=None).with_computed_hash()

    asyncio.run(client.complete(request))

    assert "temperature" not in completions.kwargs
    assert "top_p" not in completions.kwargs


def test_openrouter_adapter_omits_absent_reasoning_controls() -> None:
    completions = FakeOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    request = replace(_openrouter_request(), reasoning_effort=None).with_computed_hash()

    asyncio.run(client.complete(request))

    assert "reasoning" not in completions.kwargs["extra_body"]
    assert "provider" in completions.kwargs["extra_body"]


def test_openrouter_adapter_rejects_an_unpinned_selected_provider() -> None:
    completions = FakeOpenRouterCompletions(selected_provider="OpenInference")
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)

    with pytest.raises(ProviderFailure, match="selected provider"):
        asyncio.run(client.complete(_openrouter_request()))


def test_openrouter_adapter_rejects_a_later_route_attempt_without_attempt_details() -> None:
    completions = FakeOpenRouterCompletions(attempt=2, include_attempts=False)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)

    with pytest.raises(ProviderFailure, match="fallback"):
        asyncio.run(client.complete(_openrouter_request()))


def test_openrouter_adapter_rejects_choice_level_provider_error() -> None:
    class ChoiceErrorCompletions:
        async def create(self, **_kwargs):
            raw = {
                "id": "gen_choice_error",
                "model": "deepseek/deepseek-v4-flash-0731",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "error",
                        "error": {
                            "code": 502,
                            "message": "upstream JSON generation failed",
                        },
                        "message": {"role": "assistant", "content": "1.0"},
                    }
                ],
            }
            return SimpleNamespace(model_dump=lambda mode: raw)

    sdk = SimpleNamespace(
        chat=SimpleNamespace(completions=ChoiceErrorCompletions())
    )
    client = OpenRouterChatClient(sdk_client=sdk)

    with pytest.raises(ProviderFailure, match="upstream JSON generation failed") as caught:
        asyncio.run(client.complete(_openrouter_request()))

    assert caught.value.condition == "provider_5xx"
    assert caught.value.retryable is True


def test_openrouter_adapter_classifies_embedded_429_as_retryable_rate_limit() -> None:
    class RateLimitedCompletions:
        async def create(self, **_kwargs):
            raw = {
                "error": {
                    "code": 429,
                    "message": "upstream provider shared pool is busy",
                    "metadata": {
                        "retry_after_seconds": 30,
                        "headers": {"Retry-After": "30"},
                    },
                }
            }
            return SimpleNamespace(model_dump=lambda mode: raw)

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=RateLimitedCompletions()))
    client = OpenRouterChatClient(sdk_client=sdk)

    with pytest.raises(ProviderFailure, match="shared pool") as caught:
        asyncio.run(client.complete(_openrouter_request()))

    assert caught.value.condition == "rate_limit"
    assert caught.value.retryable is True
    assert caught.value.status_code == 429
    assert caught.value.retry_after_seconds == 30


def test_openrouter_adapter_requires_key_before_constructing_default_sdk(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(EvidenceIntegrityError, match="OPENROUTER_API_KEY"):
        OpenRouterChatClient()


# --- §6: native messages + tools, response tool_calls preserved in order (M-E) ---


class FakeOpenRouterNativeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        raw = {
            "id": "gen_openrouter_native_fixture",
            "model": "deepseek/deepseek-v4-flash-0731",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        # Deliberately neither call-id-sorted nor
                        # tool-name-sorted, so a sort-based ordering
                        # mutation (M-E) cannot pass by accident.
                        "tool_calls": [
                            {
                                "id": "call_bravo",
                                "type": "function",
                                "function": {
                                    "name": "refund_order",
                                    "arguments": '{"amount_usd":5}',
                                },
                            },
                            {
                                "id": "call_alpha",
                                "type": "function",
                                "function": {
                                    "name": "get_balance",
                                    "arguments": '{"customer_id":"c_1"}',
                                },
                            },
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 88,
                "completion_tokens": 21,
                "prompt_tokens_details": {"cached_tokens": 0},
                "cost": 0.00002,
            },
            "openrouter_metadata": {
                "requested": "deepseek/deepseek-v4-flash-0731",
                "strategy": "direct",
                "region": "iad",
                "summary": "available=1, selected=DeepInfra",
                "attempt": 1,
                "is_byok": False,
                "endpoints": {
                    "total": 1,
                    "available": [
                        {
                            "model": "deepseek/deepseek-v4-flash-20260731",
                            "provider": "DeepInfra",
                            "selected": True,
                        }
                    ],
                },
                "attempts": [
                    {
                        "model": "deepseek/deepseek-v4-flash-20260731",
                        "provider": "DeepInfra",
                        "status": 200,
                    }
                ],
            },
        }
        return SimpleNamespace(model_dump=lambda mode: raw)


def test_openrouter_adapter_translates_native_messages_and_tools_preserving_call_order() -> None:
    completions = FakeOpenRouterNativeCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    request = replace(
        _openrouter_request(),
        output_schema=None,
        messages=(CanonicalMessage(role="user", content="please act"),),
        tools=(
            ToolSchema(
                tool_id="get_balance",
                description="Look up a customer's balance",
                input_schema={"type": "object", "properties": {}},
            ),
            ToolSchema(
                tool_id="refund_order",
                description="Refund an order",
                input_schema={
                    "type": "object",
                    "properties": {"amount_usd": {"type": "number"}},
                },
            ),
        ),
    ).with_computed_hash()

    result = asyncio.run(client.complete(request))

    assert completions.kwargs["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "please act"},
    ]
    assert completions.kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_balance",
                "description": "Look up a customer's balance",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "refund_order",
                "description": "Refund an order",
                "parameters": {
                    "type": "object",
                    "properties": {"amount_usd": {"type": "number"}},
                },
            },
        },
    ]
    assert "response_format" not in completions.kwargs
    assert result.tool_calls == (
        NativeToolCall(
            call_id="call_bravo", tool_id="refund_order", arguments={"amount_usd": 5}
        ),
        NativeToolCall(
            call_id="call_alpha", tool_id="get_balance", arguments={"customer_id": "c_1"}
        ),
    )
    assert result.output_text == ""
    assert result.finish_reason == "tool_calls"
    assert result.resolved_model == "deepseek/deepseek-v4-flash-20260731"


def test_openrouter_native_adapter_omits_absent_reasoning_controls() -> None:
    completions = FakeOpenRouterNativeCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    request = replace(
        _openrouter_request(),
        output_schema=None,
        messages=(CanonicalMessage(role="user", content="please act"),),
        tools=(),
        reasoning_effort=None,
    ).with_computed_hash()

    asyncio.run(client.complete(request))

    assert "reasoning" not in completions.kwargs["extra_body"]
    assert "provider" in completions.kwargs["extra_body"]


def test_openrouter_adapter_leaves_the_text_path_untouched_when_messages_is_none() -> None:
    """§6: `messages is None` must behave byte-identically to the pre-stage-2
    structured-output dialect -- this is the same fixture and assertions as
    ``test_openrouter_adapter_pins_deepseek_route_and_parses_usage``, run
    again to pin that the new branch does not leak into the untouched path."""
    completions = FakeOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterChatClient(sdk_client=sdk)
    request = _openrouter_request()
    assert request.messages is None

    result = asyncio.run(client.complete(request))

    assert "tool_call_id" not in str(completions.kwargs)
    assert completions.kwargs["response_format"]["type"] == "json_schema"
    assert result.tool_calls is None
    assert result.output_text == '{"offer":7}'


def test_claude_code_adapter_pins_runtime_and_parses_structured_usage(tmp_path) -> None:
    executable = tmp_path / "claude"
    executable.write_bytes(b"pinned claude executable")
    executable.chmod(0o755)
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    calls: list[tuple[tuple[str, ...], bytes]] = []
    payload = {
        "is_error": False,
        "uuid": "result_fixture",
        "stop_reason": "end_turn",
        "terminal_reason": "completed",
        "total_cost_usd": 0.001798,
        "structured_output": {"offer": 7},
        "modelUsage": {
            "claude-haiku-4-5-20251001": {
                "inputTokens": 1188,
                "outputTokens": 122,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "costUSD": 0.001798,
                "canonicalModel": "claude-haiku-4-5",
                "provider": "firstParty",
            }
        },
    }

    async def command_runner(arguments: tuple[str, ...], standard_input: bytes):
        calls.append((arguments, standard_input))
        return 0, json.dumps(payload).encode(), b""

    client = ClaudeCodePrintClient(
        executable=executable,
        runtime_version="2.1.241",
        runtime_sha256=executable_sha256,
        command_runner=command_runner,
    )
    output_schema = {
        "type": "object",
        "properties": {"offer": {"type": "integer", "minimum": 0}},
        "required": ["offer"],
        "additionalProperties": False,
    }
    request = ProviderRequest(
        provider_call_id="provider_call_claude_fixture",
        provider="claude_code",
        base_url=None,
        model="claude-haiku-4-5-20251001",
        revision="claude-haiku-4-5-20251001",
        instructions=SYSTEM_PROMPT,
        input_text='{"observation":{"private_value":11},"action_schema":"offer_v1"}',
        temperature=0.0,
        top_p=None,
        max_output_tokens=256,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        max_cost_usd=0.01,
        output_schema=output_schema,
        provider_metadata={
            "runtime_version": "2.1.241",
            "runtime_sha256": executable_sha256,
        },
    ).with_computed_hash()

    result = asyncio.run(client.complete(request))

    assert result.output_text == '{"offer":7}'
    assert result.requested_model == "claude-haiku-4-5-20251001"
    assert result.resolved_model == "claude-haiku-4-5-20251001"
    assert result.input_tokens == 1188
    assert result.output_tokens == 122
    assert result.cost_usd == pytest.approx(0.001798)
    assert len(calls) == 1
    arguments, standard_input = calls[0]
    assert arguments[0] == str(executable)
    assert arguments[arguments.index("--model") + 1] == request.model
    assert arguments[arguments.index("--effort") + 1] == "low"
    assert arguments[arguments.index("--max-budget-usd") + 1] == "0.01"
    assert arguments[arguments.index("--json-schema") + 1] == json.dumps(
        output_schema, sort_keys=True, separators=(",", ":")
    )
    assert "--safe-mode" in arguments
    assert "--no-session-persistence" in arguments
    assert request.input_text not in arguments
    assert standard_input == request.input_text.encode("utf-8")


def test_claude_code_adapter_rejects_runtime_hash_mismatch_before_call(tmp_path) -> None:
    executable = tmp_path / "claude"
    executable.write_bytes(b"changed executable")
    calls = 0

    async def command_runner(_arguments: tuple[str, ...], _standard_input: bytes):
        nonlocal calls
        calls += 1
        return 0, b"{}", b""

    client = ClaudeCodePrintClient(
        executable=executable,
        runtime_version="2.1.241",
        runtime_sha256="0" * 64,
        command_runner=command_runner,
    )
    request = ProviderRequest(
        provider_call_id="provider_call_claude_fixture",
        provider="claude_code",
        base_url=None,
        model="claude-haiku-4-5-20251001",
        revision="claude-haiku-4-5-20251001",
        instructions=SYSTEM_PROMPT,
        input_text="{}",
        temperature=0.0,
        top_p=None,
        max_output_tokens=256,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        max_cost_usd=0.01,
        output_schema={"type": "object"},
        provider_metadata={
            "runtime_version": "2.1.241",
            "runtime_sha256": "0" * 64,
        },
    ).with_computed_hash()

    with pytest.raises(ProviderFailure, match="runtime digest"):
        asyncio.run(client.complete(request))
    assert calls == 0


def test_claude_code_adapter_refuses_native_chat_messages(tmp_path) -> None:
    """§6: Claude Code print sessions deliberately disable tools; a request
    built for `native_tool_chat` must fail typed, not silently ignore
    `messages` and run the text-only session anyway."""
    executable = tmp_path / "claude"
    executable.write_bytes(b"pinned claude executable")
    executable.chmod(0o755)
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    calls = 0

    async def command_runner(_arguments: tuple[str, ...], _standard_input: bytes):
        nonlocal calls
        calls += 1
        return 0, b"{}", b""

    client = ClaudeCodePrintClient(
        executable=executable,
        runtime_version="2.1.241",
        runtime_sha256=executable_sha256,
        command_runner=command_runner,
    )
    request = replace(
        ProviderRequest(
            provider_call_id="provider_call_claude_fixture",
            provider="claude_code",
            base_url=None,
            model="claude-haiku-4-5-20251001",
            revision="claude-haiku-4-5-20251001",
            instructions=SYSTEM_PROMPT,
            input_text="ignored",
            temperature=0.0,
            top_p=None,
            max_output_tokens=256,
            reasoning_effort="low",
            timeout_seconds=30.0,
            request_sha256="",
            max_cost_usd=0.01,
            output_schema={"type": "object"},
            provider_metadata={
                "runtime_version": "2.1.241",
                "runtime_sha256": executable_sha256,
            },
        ),
        messages=(CanonicalMessage(role="user", content="hi"),),
    ).with_computed_hash()

    with pytest.raises(ProviderFailure) as captured:
        asyncio.run(client.complete(request))
    assert captured.value.condition == "provider_contract"
    assert calls == 0


def _single_case() -> CaseManifest:
    raw = {
        "spec_version": "aeread.case/0.1",
        "case_id": "single_v1__dev__000001",
        "family_id": "single_v1",
        "family_version": "1.0.0",
        "split": "dev",
        "world_seed": 71001,
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {"max_logical_actions": 1, "termination": ["submitted"]},
        "visibility_policy": "single_private_v1",
        "payload": {"private_value": 11},
        "provenance": {
            "generator_id": "single_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _single_cell() -> PlanCell:
    case = _single_case()
    return PlanCell(
        spec_version="aeread.plan_cell/0.1",
        cell_id="cell_single000000000001",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="single_dev_v1",
        suite_version="1.0.0",
        block_id="single_controlled",
        sampling_plan_id="single_sample_v1",
        analysis_plan_id="single_analysis_v1",
        world_seed=case.world_seed,
        sampling_seed=1,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_single",
        cluster_level="world_seed",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="fixed_panel",
        profile_by_seat=MappingProxyType({"buyer": "subject_model_v1"}),
        execution_mode="evaluate",
        case_max_logical_actions=1,
    )


class SingleActionPlugin:
    def validate_payload(self, payload):
        return dict(payload)

    def initial_state(self, case, run):
        return {"private_value": case["private_value"], "offer": None, "done": False}

    def phases(self, case):
        return (
            PhaseSpec(
                phase_id="offer",
                actor_selector="buyer_only",
                mode="single",
                observation_schema_by_role={"buyer": "private_value_v1"},
                action_schema_by_role={"buyer": "offer_v1"},
                max_logical_actions=1,
                invalid_action_policy="reject",
                next_phases=(),
            ),
        )

    def eligible_actors(self, case, state, phase):
        return ("buyer",)

    def observe(self, case, state, seat, phase):
        return {"private_value": state["private_value"]}

    def parse_action(self, case, state, seat, phase, response):
        assert isinstance(response, CanonicalResponse)
        parsed = json.loads(response.text)
        if not isinstance(parsed.get("offer"), int):
            return ParseResult.failure("malformed_offer")
        return ParseResult.success(parsed)

    def legal(self, case, state, seat, phase, action):
        return (
            LegalityResult.legal_action()
            if action["offer"] >= 0
            else LegalityResult.illegal("negative_offer")
        )

    def step(self, case, state, phase, actions):
        next_state = dict(state)
        next_state["offer"] = actions["buyer"].action["offer"]
        next_state["done"] = True
        return TransitionResult(state=next_state, next_phase_id=None)

    def terminal(self, case, state):
        return {"reason": "submitted"} if state["done"] else None

    def outcome(self, case, terminal):
        return {"valid": True, "reason": terminal["reason"]}


def test_r3_scheduler_drives_r4_executor_and_reconciles_action(tmp_path) -> None:
    cell = _single_cell()
    episode_id = episode_id_for_cell(cell)
    evidence = EvidenceStore(
        tmp_path / "integrated_evidence",
        run_plan_id="runplan_single",
        cell_id=cell.cell_id,
        episode_id=episode_id,
        episode_attempt_id=f"episode_attempt_{episode_id}_0",
    )
    provider = InspectingProvider(evidence.events_path, [_success_result()])
    executor = _executor(tmp_path, provider, evidence=evidence)

    result = asyncio.run(
        run_episode(
            cell=cell,
            case=_single_case(),
            plugin=SingleActionPlugin(),
            response_source=executor,
        )
    )

    assert result.episode_id == episode_id
    assert result.final_state["offer"] == 7
    assert result.outcome == {"valid": True, "reason": "submitted"}
    execution = executor.execution_for(
        result.phase_instances[0].actions[0].logical_action_id
    )
    assert execution.status == "succeeded"
    evidence.audit_reconciliation()



def test_a_declared_reasoning_budget_reaches_the_wire() -> None:
    """A profile's reasoning token budget must be sent, not silently dropped.

    ReasoningSpec.token_budget was a sealed profile field that no request
    builder copied, and the providers substituted effort="low" whenever effort
    was absent. Two arms declaring different budgets therefore sent identical
    requests: the run was labelled with one reasoning condition and executed
    another -- the shape of a treatment that silently fails to be delivered.
    """

    from aeread.shared_runner.task.execution import _reasoning_block

    declared = ProviderRequest(
        provider_call_id="provider_call_fixture",
        provider="openrouter",
        base_url=None,
        model="fake-model",
        revision=None,
        instructions="sys",
        input_text="hi",
        temperature=None,
        top_p=None,
        max_output_tokens=64,
        reasoning_effort=None,
        timeout_seconds=30.0,
        request_sha256="",
        reasoning_token_budget=4096,
    ).with_computed_hash()

    block = _reasoning_block(declared)
    assert block == {"max_tokens": 4096}, "the declared budget must be sent"
    assert "effort" not in block, "an absent control must not be invented"


def test_native_request_fields_bind_the_request_hash() -> None:
    """Two native requests differing only in messages must not share a hash.

    request_sha256 excluded messages, tools, and the reasoning budget, so
    replay could not prove which request produced a given response. Legacy
    text-only requests must still hash exactly as before.
    """

    from aeread.shared_runner.model_call.harness import CanonicalMessage

    def _request(**overrides):
        base = dict(
            provider_call_id="provider_call_fixture",
            provider="openrouter",
            base_url=None,
            model="fake-model",
            revision=None,
            instructions="sys",
            input_text="hi",
            temperature=None,
            top_p=None,
            max_output_tokens=64,
            reasoning_effort=None,
            timeout_seconds=30.0,
            request_sha256="",
        )
        base.update(overrides)
        return ProviderRequest(**base).with_computed_hash()

    legacy = _request()
    first = _request(messages=(CanonicalMessage(role="user", content="alpha"),))
    second = _request(messages=(CanonicalMessage(role="user", content="bravo"),))
    budgeted = _request(reasoning_token_budget=4096)

    assert first.request_sha256 != second.request_sha256, "messages must bind the hash"
    assert budgeted.request_sha256 != legacy.request_sha256
    # A text-only request is unaffected by the new fields.
    assert legacy.request_sha256 == _request().request_sha256



def test_protocol_records_serialize_their_full_current_shape() -> None:
    """The canonical serializer emits every field, including new ones set to None.

    Consequence, recorded deliberately rather than papered over: a
    ProviderResult persisted before the native fields existed hashes
    differently if re-serialized now, because the bytes gain "tool_calls":null
    and the two reasoning counters. Nothing in the runner re-serializes a
    persisted record -- artifacts are written once and read back as bytes -- so
    no stored evidence is invalidated today.

    Suppressing None globally would change the hash of every record in the
    system, which is a larger break than the one it fixes. The real answer is a
    versioned canonical encoding with golden byte vectors (the canonical-JSON
    spec task); this test pins the CURRENT shape so that work starts from a
    measured baseline and any accidental drift fails here first.
    """

    from aeread.shared_runner.run.resolver import canonical_json_bytes

    result = ProviderResult(
        response_id="response_fixture",
        requested_model="fake-model",
        resolved_model="fake-model-v1",
        output_text="hello",
        finish_reason="stop",
        input_tokens=20,
        cached_input_tokens=0,
        output_tokens=5,
        cost_usd=None,
        raw_response={"output_text": "hello"},
    )
    payload = canonical_json_bytes(result).decode("utf-8")

    for field in ("tool_calls", "reasoning_tokens", "visible_output_tokens"):
        assert f'"{field}":null' in payload, (
            f"{field} must serialize explicitly; if this changes, the canonical "
            "encoding has been versioned and the golden vectors must be updated"
        )
