from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from aeread.shared_runner.execution import (
    EvidenceIntegrityError,
    EvidenceStore,
    ProviderCallRecord,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    ToolFailure,
    ToolInvocationRecord,
    _sha256_bytes,
)
from aeread.shared_runner.harness import (
    NativeToolCall,
    CanonicalMessage,
    KernelModelPort,
    KernelToolPort,
    ModelTurn,
    ToolExecutionEnvelope,
)
from aeread.shared_runner.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import AgentProfile
from aeread.shared_runner.tools import ToolBinding, ToolDefinition, ToolRuntime


FAKE_PRICING = TokenPricing(
    input_per_million=0.05,
    cached_input_per_million=0.005,
    output_per_million=0.40,
    pricing_id="fake-pricing-v1",
)
SYSTEM_PROMPT = "Return one JSON object matching the requested action schema."


def _profile(*, max_output_tokens: int = 80) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": "subject_model_v1",
            "model": {"provider": "fake", "model": "fake-model", "revision": "pinned-v1"},
            "harness": {
                "id": "native_tool_chat",
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
                "implementation": "aeread.shared_runner.harness",
                "version": "0.1.0",
            },
            "tools": ["get_balance", "refund_order"],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_low_v1",
                "effort": "low",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {"temperature": 0.0, "max_output_tokens": max_output_tokens, "seed": None},
            "budgets": {"max_logical_actions": 4, "timeout_seconds": 5.0, "max_cost_usd": 1.0},
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def _evidence(tmp_path, name: str = "evidence") -> EvidenceStore:
    return EvidenceStore(
        tmp_path / name,
        run_plan_id="runplan_harness_fixture",
        cell_id="cell_harness_fixture",
        episode_id="episode_harness_fixture",
        episode_attempt_id="episode_attempt_harness_fixture",
    )


def _result(
    *, text: str, finish_reason: str = "stop", tool_calls=None
) -> ProviderResult:
    return ProviderResult(
        tool_calls=tool_calls,
        response_id="response_fixture",
        requested_model="fake-model",
        resolved_model="fake-model-v1",
        output_text=text,
        finish_reason=finish_reason,
        input_tokens=20,
        cached_input_tokens=0,
        output_tokens=5,
        cost_usd=None,
        raw_response={"finish_reason": finish_reason, "output_text": text},
    )


class ScriptedProvider:
    def __init__(self, results):
        self.results = list(results)
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        outcome = self.results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _tool_runtime(tmp_path, evidence, *, balance_db=None):
    balance_db = {"balance": 10} if balance_db is None else balance_db

    async def get_balance(_arguments):
        return {"balance": balance_db["balance"]}

    async def refund(arguments):
        balance_db["balance"] += arguments["amount_usd"]
        return {"status": "refunded", "amount_usd": arguments["amount_usd"]}

    bindings = (
        ToolBinding(
            ToolDefinition(
                tool_id="get_balance",
                tool_version="1.0.0",
                effect="read_only",
                input_schema={"type": "object", "properties": {}},
                idempotency_supported=True,
            ),
            implementation=get_balance,
        ),
        ToolBinding(
            ToolDefinition(
                tool_id="refund_order",
                tool_version="1.0.0",
                effect="mutating",
                input_schema={
                    "type": "object",
                    "properties": {"amount_usd": {"type": "number"}},
                    "required": ["amount_usd"],
                },
                idempotency_supported=True,
            ),
            implementation=refund,
            state_reader=lambda: balance_db,
        ),
    )
    return ToolRuntime(evidence, bindings), balance_db


# --- Golden hash: ProviderCallRecord / ToolInvocationRecord shapes are untouched ---


def test_provider_call_and_tool_invocation_record_hashes_are_unchanged() -> None:
    provider_record = ProviderCallRecord(
        provider_call_id="provider_call_fixture",
        action_attempt_id="action_attempt_fixture",
        status="succeeded",
        request_sha256="a" * 64,
        requested_model="fake-model",
        resolved_model="fake-model-v1",
        response_id="response_fixture",
        finish_reason="stop",
        input_tokens=20,
        cached_input_tokens=0,
        output_tokens=5,
        cost_usd=0.001,
        failure_condition=None,
    )
    tool_record = ToolInvocationRecord(
        tool_invocation_id="tool_invocation_fixture",
        action_attempt_id="action_attempt_fixture",
        tool_id="get_balance",
        tool_version="1.0.0",
        tool_schema_sha256="f" * 64,
        input_sha256="b" * 64,
        idempotency_supported=True,
        status="succeeded",
        result_sha256="c" * 64,
        failure_condition=None,
        effect="read_only",
        state_before_sha256=None,
        state_after_sha256=None,
        state_diff_sha256=None,
        state_changed=None,
        outcome_known=True,
    )
    assert (
        _sha256_bytes(canonical_json_bytes(provider_record))
        == "4411e12d003914f1d4aebccc2bab2ba52da5c389f4d39ae49203907ee168b1d7"
    )
    assert (
        _sha256_bytes(canonical_json_bytes(tool_record))
        == "5c7ae9090e4ff7c4415163d9d9d0a80a0a24c6feb211e0b0f19e3d222e3017dd"
    )


# --- KernelModelPort: empty completion rejected before the harness sees it (M-B) ---


def test_model_port_rejects_empty_completion_before_returning_a_model_turn(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = ScriptedProvider([_result(text="   ", finish_reason="stop")])
    port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )

    with pytest.raises(ProviderFailure) as captured:
        asyncio.run(
            port.complete(
                messages=(CanonicalMessage(role="user", content="hi"),),
                response_mode="text",
            )
        )
    assert captured.value.condition == "empty_response"  # the kernel retry vocabulary

    events = [event.event_type for event in evidence.read_events()]
    assert events == ["provider_call_started", "provider_call_succeeded"]


def test_model_port_returns_a_model_turn_for_a_non_empty_completion(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = ScriptedProvider([_result(text="hello", finish_reason="stop")])
    port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )

    turn = asyncio.run(
        port.complete(
            messages=(CanonicalMessage(role="user", content="hi"),),
            response_mode="text",
        )
    )
    assert turn.text == "hello"
    assert turn.tool_calls == ()


def test_model_port_rejects_a_harness_that_raises_max_output_tokens(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    provider = ScriptedProvider([_result(text="hello")])
    port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=_profile(max_output_tokens=80),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )

    with pytest.raises(Exception, match="max_output_tokens"):
        asyncio.run(
            port.complete(
                messages=(CanonicalMessage(role="user", content="hi"),),
                response_mode="text",
                max_output_tokens=8000,
            )
        )


# --- KernelToolPort: deterministic identity (M-D) ---


def test_tool_port_mints_tool_invocation_id_from_attempt_and_source_call_not_an_instance_counter(
    tmp_path,
) -> None:
    """A resume opens a fresh ``KernelToolPort`` instance and must recompute
    the identical id for a dispatch that already happened before the crash.
    ``source_call_index=1`` is the *second* dispatch on the pre-crash
    instance but the *first* call the resumed instance ever makes -- an
    instance-local ordinal would mint 1 before crash and 0 after resume,
    diverging; the (attempt_id, source_provider_call_id, source_call_index)
    formula does not."""

    async def dispatch(port: KernelToolPort, source_call_index: int) -> str:
        envelope = await port.invoke(
            tool_id="get_balance",
            arguments={},
            source_provider_call_id="provider_call_pc_0",
            source_call_index=source_call_index,
        )
        return envelope.invocation_record.tool_invocation_id

    async def run_before_crash() -> str:
        evidence = _evidence(tmp_path, "evidence_before_crash")
        runtime, _ = _tool_runtime(tmp_path, evidence)
        port = KernelToolPort(
            runtime=runtime, attempt_id="attempt_fixture", action_attempt_id="action_attempt_fixture"
        )
        await dispatch(port, 0)
        return await dispatch(port, 1)

    async def run_after_resume() -> str:
        evidence = _evidence(tmp_path, "evidence_after_resume")
        runtime, _ = _tool_runtime(tmp_path, evidence)
        port = KernelToolPort(
            runtime=runtime, attempt_id="attempt_fixture", action_attempt_id="action_attempt_fixture"
        )
        return await dispatch(port, 1)

    before_crash_id = asyncio.run(run_before_crash())
    after_resume_id = asyncio.run(run_after_resume())
    assert before_crash_id == after_resume_id


# --- KernelToolPort: undeclared tool is a typed rejection, never an orphan (M-C) ---


def test_tool_port_rejects_an_undeclared_tool_before_tool_runtime_ever_sees_it(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    runtime, _ = _tool_runtime(tmp_path, evidence)
    port = KernelToolPort(
        runtime=runtime, attempt_id="attempt_fixture", action_attempt_id="action_attempt_fixture"
    )

    with pytest.raises(ToolFailure) as captured:
        asyncio.run(
            port.invoke(
                tool_id="delete_everything",
                arguments={},
                source_provider_call_id="provider_call_pc_0",
                source_call_index=0,
            )
        )
    assert captured.value.condition == "undeclared_tool"

    events = evidence.read_events()
    event_types = [event.event_type for event in events]
    assert event_types == ["tool_dispatch_intended", "tool_dispatch_rejected"]
    assert "tool_invocation_started" not in event_types


def test_tool_port_rejects_a_dispatch_past_its_invocation_budget(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    runtime, _ = _tool_runtime(tmp_path, evidence)
    port = KernelToolPort(
        runtime=runtime,
        attempt_id="attempt_fixture",
        action_attempt_id="action_attempt_fixture",
        max_invocations=1,
    )

    asyncio.run(
        port.invoke(
            tool_id="get_balance",
            arguments={},
            source_provider_call_id="provider_call_pc_0",
            source_call_index=0,
        )
    )
    with pytest.raises(ToolFailure) as captured:
        asyncio.run(
            port.invoke(
                tool_id="get_balance",
                arguments={},
                source_provider_call_id="provider_call_pc_0",
                source_call_index=1,
            )
        )
    assert captured.value.condition == "tool_budget_exceeded"


def test_tool_port_wraps_the_kernel_record_in_an_envelope_with_family_reconciliation(
    tmp_path,
) -> None:
    evidence = _evidence(tmp_path)
    runtime, _ = _tool_runtime(tmp_path, evidence)
    port = KernelToolPort(
        runtime=runtime,
        attempt_id="attempt_fixture",
        action_attempt_id="action_attempt_fixture",
        family_reconciliation=lambda tool_id, result, record: {"post_db_hash": "deadbeef"},
    )

    envelope = asyncio.run(
        port.invoke(
            tool_id="get_balance",
            arguments={},
            source_provider_call_id="provider_call_pc_0",
            source_call_index=0,
        )
    )
    assert isinstance(envelope, ToolExecutionEnvelope)
    assert envelope.result == {"balance": 10}
    assert envelope.invocation_record.status == "succeeded"
    assert envelope.family_reconciliation == {"post_db_hash": "deadbeef"}


# --- ToolExecutor: guarded post-effect observation (M-A) ---


def test_bookkeeping_failure_after_a_tool_failure_preserves_the_original_exception(
    tmp_path,
) -> None:
    from aeread.shared_runner.execution import ToolExecutor

    evidence = _evidence(tmp_path)
    tools = ToolExecutor(evidence)
    calls = {"n": 0}

    def flaky_reader():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"balance": 10}
        raise RuntimeError("bookkeeping backend unavailable")

    async def order_stock(_arguments):
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
                tool_schema_sha256="e" * 64,
                state_reader=flaky_reader,
            )
        )

    error = captured.value
    assert error.condition == "supplier_timeout"
    assert isinstance(error.__context__, RuntimeError)
    assert "bookkeeping backend unavailable" in str(error.__context__)
    assert error.record is None

    event_types = [event.event_type for event in evidence.read_events()]
    assert event_types == ["tool_invocation_started", "tool_invocation_outcome_unknown"]
    payloads = [
        __import__("json").loads(
            (evidence.root / event.payload_ref).read_bytes()
        )
        for event in evidence.read_events()
    ]
    assert payloads[-1]["failure_condition"] == "bookkeeping_failed"



def test_bookkeeping_failure_that_is_a_base_exception_is_still_recorded(tmp_path) -> None:
    """A cancellation during post-effect observation must not escape the guard.

    `asyncio.CancelledError` is a direct `BaseException` subclass, so a guard
    catching only `Exception` misses exactly the case where a mutating call is
    most likely to have posted unobserved: the run being torn down mid-tool.
    The evidence must still say "unknown", and the ORIGINAL tool failure must
    still be the exception that propagates.
    """

    from aeread.shared_runner.execution import ToolExecutor

    evidence = _evidence(tmp_path, "base_exception_evidence")
    tools = ToolExecutor(evidence)
    calls = {"n": 0}

    def cancelling_reader():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"balance": 10}
        raise asyncio.CancelledError()

    async def order_stock(_arguments):
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
                tool_schema_sha256="e" * 64,
                state_reader=cancelling_reader,
            )
        )

    error = captured.value
    assert error.condition == "supplier_timeout", "the original failure must propagate"
    assert isinstance(error.__context__, asyncio.CancelledError)

    event_types = [event.event_type for event in evidence.read_events()]
    assert event_types == ["tool_invocation_started", "tool_invocation_outcome_unknown"]

# --- Design §8: two tools in one turn, exact event order ---


def test_two_tool_calls_in_one_turn_match_design_section_8_event_order(tmp_path) -> None:
    """A scripted, provider-free drive of one model turn requesting two tools,
    matching design §8's illustrative event sequence exactly. This test plays
    the role of the not-yet-built ``Harness.act``/``AttemptExecutor`` (stage
    3/4) by hand, using only the stage-1 ports, to prove the ports alone
    already produce the required order."""

    evidence = _evidence(tmp_path)
    runtime, balance_db = _tool_runtime(tmp_path, evidence)
    profile = _profile()
    action_attempt_id = "action_attempt_fixture"

    provider = ScriptedProvider(
        [
            _result(text="calling tools", finish_reason="tool_calls"),
            _result(text="here is your answer", finish_reason="reply"),
        ]
    )
    model_port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=profile,
        instructions=SYSTEM_PROMPT,
        action_attempt_id=action_attempt_id,
        logical_action_id="logical_action_fixture",
        visibility="seat:buyer",
    )
    tool_port = KernelToolPort(
        runtime=runtime, attempt_id="attempt_fixture", action_attempt_id=action_attempt_id
    )

    async def run_attempt() -> None:
        evidence.append_event(
            "logical_action_started",
            {"profile_id": profile.profile_id, "request": {"phase_id": "assistant_turn"}},
            logical_action_id="logical_action_fixture",
        )
        evidence.append_event(
            "action_attempt_started",
            {
                "ordinal": 0,
                "retry_reason": None,
                "session_mode": profile.retry_policy.session_mode,
                "rounds_max": 4,
                "seed": profile.sampling.seed,
            },
            logical_action_id="logical_action_fixture",
            action_attempt_id=action_attempt_id,
        )

        turn_0 = await model_port.complete(
            messages=(CanonicalMessage(role="user", content="please act"),),
            response_mode="native_tools",
        )
        assert turn_0.text == "calling tools"
        provider_call_id_0 = provider.requests[0].provider_call_id

        first = await tool_port.invoke(
            tool_id="get_balance",
            arguments={},
            source_provider_call_id=provider_call_id_0,
            source_call_index=0,
        )
        second = await tool_port.invoke(
            tool_id="refund_order",
            arguments={"amount_usd": 5},
            source_provider_call_id=provider_call_id_0,
            source_call_index=1,
        )
        assert first.invocation_record.effect == "read_only"
        assert second.invocation_record.effect == "mutating"
        assert second.invocation_record.state_changed is True

        turn_1 = await model_port.complete(
            messages=(
                CanonicalMessage(role="user", content="please act"),
                CanonicalMessage(role="tool", content="ok", tool_call_id="ti_0"),
                CanonicalMessage(role="tool", content="ok", tool_call_id="ti_1"),
            ),
            response_mode="native_tools",
        )
        assert turn_1.text == "here is your answer"
        provider_call_id_1 = provider.requests[1].provider_call_id

        evidence.append_event(
            "action_attempt_succeeded",
            {
                "provider_call_ids": [provider_call_id_0, provider_call_id_1],
                "tool_invocation_ids": [
                    first.invocation_record.tool_invocation_id,
                    second.invocation_record.tool_invocation_id,
                ],
                "claimed_tool_calls": 2,
                "reconciled": True,
                "rounds_used": 2,
                "empty_completions": 0,
                "malformed_rounds": 0,
            },
            logical_action_id="logical_action_fixture",
            action_attempt_id=action_attempt_id,
        )
        evidence.append_event(
            "action_parsed",
            {"verdict": "applied"},
            logical_action_id="logical_action_fixture",
            action_attempt_id=action_attempt_id,
        )
        evidence.append_event(
            "action_legality_checked",
            {"legal": True},
            logical_action_id="logical_action_fixture",
            action_attempt_id=action_attempt_id,
        )

    asyncio.run(run_attempt())

    events = evidence.read_events()
    event_types = [event.event_type for event in events]
    assert event_types == [
        "logical_action_started",
        "action_attempt_started",
        "provider_call_started",
        "provider_call_succeeded",
        "tool_dispatch_intended",
        "tool_invocation_started",
        "tool_invocation_succeeded",
        "tool_dispatch_intended",
        "tool_invocation_started",
        "tool_invocation_succeeded",
        "provider_call_started",
        "provider_call_succeeded",
        "action_attempt_succeeded",
        "action_parsed",
        "action_legality_checked",
    ]

    provider_call_events = [event for event in events if event.provider_call_id is not None]
    assert len({event.provider_call_id for event in provider_call_events}) == 2
    tool_events = [event for event in events if event.tool_invocation_id is not None]
    tool_ids = {event.tool_invocation_id for event in tool_events}
    assert len(tool_ids) == 2
    # Every tool_invocation identity gets exactly one dispatch-intent, one
    # started, and one terminal event -- never orphaned.
    for tool_invocation_id in tool_ids:
        subset = [event.event_type for event in tool_events if event.tool_invocation_id == tool_invocation_id]
        assert subset == [
            "tool_dispatch_intended",
            "tool_invocation_started",
            "tool_invocation_succeeded",
        ]

    evidence.audit_reconciliation(entity_types=("action_attempt", "provider_call", "tool_invocation"))


def test_model_turn_carries_the_kernel_provider_call_id(tmp_path) -> None:
    """A harness must be able to correlate a tool call to the model output that
    requested it using ONLY the port result.

    `ToolPort.invoke` requires `source_provider_call_id`.  Before this, the id
    existed solely on the `ProviderRequest` the port had already sent, so the
    only way to reach it was through the provider client's internals -- which a
    real harness does not have.  A test that reads `provider.requests[...]` is
    testing around the port, not through it, so this asserts the id arrives on
    the `ModelTurn` and matches what the kernel actually recorded.
    """

    evidence = _evidence(tmp_path)
    provider = ScriptedProvider([_result(text="hello", finish_reason="stop")])
    port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )

    turn = asyncio.run(
        port.complete(
            messages=(CanonicalMessage(role="user", content="hi"),),
            response_mode="text",
        )
    )

    assert turn.provider_call_id, "the port must return the kernel provider_call_id"
    # It is the same id the kernel sent and sealed, not a fresh one.
    assert turn.provider_call_id == provider.requests[0].provider_call_id
    events = [json.loads(line) for line in evidence.events_path.read_text().splitlines()]
    started = [e for e in events if e["event_type"] == "provider_call_started"]
    assert [e["provider_call_id"] for e in started] == [turn.provider_call_id]


def _executor_profile():
    """The execution-test profile, reused so the two suites cannot drift."""

    from tests.test_shared_runner_execution import _profile

    return _profile()


def _executor_prompt() -> str:
    """The prompt whose hash the reused profile declares."""

    from tests.test_shared_runner_execution import SYSTEM_PROMPT as EXECUTION_PROMPT

    return EXECUTION_PROMPT


def _executor_decision():
    from tests.test_shared_runner_execution import _decision

    return _decision()


def test_attempt_executor_drives_a_registered_harness_end_to_end(tmp_path) -> None:
    """The executor resolves the profile's harness and returns its result.

    This is the stage-3 contract: `minimal_chat/1.0` expressed as a `Harness`
    over the ports produces the same `CanonicalResponse` the kernel has always
    produced, through the registered harness rather than a hardcoded loop.
    """

    from aeread.shared_runner.harness import AttemptExecutor, default_harnesses

    # The evidence store's identity must match the decision's, so build one
    # around the reused execution-suite decision rather than the local fixture.
    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "executor_evidence",
        run_plan_id="runplan_harness_fixture",
        cell_id=decision.cell_id,
        episode_id=decision.episode_id,
        episode_attempt_id="episode_attempt_harness_fixture",
    )
    profile = _executor_profile()
    provider = ScriptedProvider([_result(text="an offer", finish_reason="stop")])
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=[profile],
        prompt_sources={profile.prompt.prompt_id: _executor_prompt()},
        providers={profile.model.provider: provider},
        pricing={profile.model.model: FAKE_PRICING},
        harnesses=default_harnesses(),
    )

    response = asyncio.run(executor(decision))

    assert response.text == "an offer"
    assert response.provider_call_ids, "the attempt must record its provider call"
    # The attempt lifecycle is the kernel's, unchanged: success is recorded
    # before the scheduler ever parses the action.
    events = [json.loads(line) for line in evidence.events_path.read_text().splitlines()]
    kinds = [e["event_type"] for e in events]
    assert "action_attempt_succeeded" in kinds
    assert kinds.index("provider_call_started") < kinds.index("action_attempt_succeeded")


def test_attempt_executor_refuses_a_profile_with_no_registered_harness(tmp_path) -> None:
    """A profile naming an unregistered harness fails before any provider call."""

    from aeread.shared_runner.harness import AttemptExecutor

    evidence = _evidence(tmp_path, "unregistered_evidence")
    profile = _executor_profile()
    provider = ScriptedProvider([_result(text="unused")])

    with pytest.raises(EvidenceIntegrityError, match="no harness registered"):
        AttemptExecutor(
            evidence=evidence,
            profiles=[profile],
            prompt_sources={profile.prompt.prompt_id: _executor_prompt()},
            providers={profile.model.provider: provider},
            pricing={profile.model.model: FAKE_PRICING},
            harnesses={},
        )



def test_attempt_context_exposes_no_tool_port_until_a_tools_harness_is_admitted(
    tmp_path,
) -> None:
    """Stage 3 deliberately hands every harness `tools=None`.

    Only `minimal_chat/1.0` is registered, and it declares `tools="none"`, so
    there is no admitted tool-using profile yet: a live `ToolPort` here would be
    capability nobody asked for. Stage 4 introduces the tool harnesses and the
    admission that grants the port, and this test is what fails if that wiring
    is added without also granting the port -- or if a tool port is ever handed
    to a harness whose profile declares no tools.
    """

    from aeread.shared_runner.harness import (
        AttemptExecutor,
        MinimalChatHarness,
        default_harnesses,
    )

    assert MinimalChatHarness.requires.tools == "none"

    seen = {}

    class RecordingHarness(MinimalChatHarness):
        async def act(self, request, ctx):
            seen["tools"] = ctx.tools
            seen["subagents"] = ctx.subagents
            return await super().act(request, ctx)

    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "tools_boundary",
        run_plan_id="runplan_harness_fixture",
        cell_id=decision.cell_id,
        episode_id=decision.episode_id,
        episode_attempt_id="episode_attempt_harness_fixture",
    )
    profile = _executor_profile()
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=[profile],
        prompt_sources={profile.prompt.prompt_id: _executor_prompt()},
        providers={profile.model.provider: ScriptedProvider([_result(text="ok")])},
        pricing={profile.model.model: FAKE_PRICING},
        harnesses={"minimal_chat/1.0": RecordingHarness()},
    )

    asyncio.run(executor(decision))

    assert seen["tools"] is None, "a no-tools profile must not receive a tool port"
    assert seen["subagents"] is None, "nested agents are not admitted before stage 11"
    assert set(default_harnesses()) == {"minimal_chat/1.0"}



def test_model_port_returns_a_tool_call_turn_without_calling_it_empty(tmp_path) -> None:
    """A native tool-call turn carries no text; it must not be judged empty.

    OpenRouter returns `output_text=""` with a populated `tool_calls` list when
    the model asks for tools. Judging emptiness on text alone rejected exactly
    that shape as `empty_response`, so a native tool call could never reach a
    harness -- the tools would silently never be dispatched.
    """

    evidence = _evidence(tmp_path, "tool_turn_evidence")
    call = NativeToolCall(call_id="call_alpha", tool_id="get_balance", arguments={})
    provider = ScriptedProvider(
        [_result(text="", finish_reason="tool_calls", tool_calls=(call,))]
    )
    port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )

    turn = asyncio.run(
        port.complete(
            messages=(CanonicalMessage(role="user", content="check my balance"),),
            response_mode="native_tools",
        )
    )

    assert turn.text is None
    assert turn.tool_calls == (call,), "the ordered calls must reach the harness"
    assert turn.provider_call_id


def test_model_port_refuses_a_turn_carrying_both_text_and_tool_calls(tmp_path) -> None:
    """A model turn is text XOR calls; both would make the harness guess."""

    evidence = _evidence(tmp_path, "both_evidence")
    call = NativeToolCall(call_id="call_alpha", tool_id="get_balance", arguments={})
    provider = ScriptedProvider(
        [_result(text="thinking", finish_reason="tool_calls", tool_calls=(call,))]
    )
    port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=_profile(),
        instructions=SYSTEM_PROMPT,
        action_attempt_id="action_attempt_fixture",
    )

    with pytest.raises(ProviderFailure) as captured:
        asyncio.run(
            port.complete(
                messages=(CanonicalMessage(role="user", content="hi"),),
                response_mode="native_tools",
            )
        )
    assert captured.value.condition == "provider_contract"
    assert captured.value.retryable is False
