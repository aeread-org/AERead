from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from aeread.shared_runner.execution import (
    CanonicalResponse,
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
    ClaimedToolCall,
    HarnessOutput,
    HarnessRequirements,
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


def test_canonical_response_hash_is_unchanged_when_no_harness_sets_an_action() -> None:
    """§5.1 adds `CanonicalResponse.action`, defaulting to None, so a caller
    that never touches the harness seam -- every fixture built the way the
    kernel has always built one -- still hashes to the value pinned here."""

    canonical = CanonicalResponse(
        text="an offer",
        finish_reason="stop",
        empty=False,
        truncated=False,
        provider_call_ids=("provider_call_fixture",),
        tool_invocation_ids=(),
        input_tokens=20,
        cached_input_tokens=0,
        output_tokens=5,
        cost_usd=0.001,
    )
    assert canonical.action is None
    assert (
        _sha256_bytes(canonical_json_bytes(canonical))
        == "88d7146edd88c1fedd7ff092aa67f4478aab49a1fffd025f005438995dab572c"
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


def test_tool_port_rejects_a_dispatch_outside_the_granted_set(tmp_path) -> None:
    """The family runtime may declare more tools than one profile is granted;
    admissibility must be enforced at the port, not left to the family."""

    evidence = _evidence(tmp_path)
    runtime, balance_db = _tool_runtime(tmp_path, evidence)
    port = KernelToolPort(
        runtime=runtime,
        attempt_id="attempt_fixture",
        action_attempt_id="action_attempt_fixture",
        granted_tools=frozenset({"get_balance"}),
    )

    with pytest.raises(ToolFailure) as captured:
        asyncio.run(
            port.invoke(
                tool_id="refund_order",
                arguments={"amount_usd": 5},
                source_provider_call_id="provider_call_pc_0",
                source_call_index=0,
            )
        )
    assert captured.value.condition == "tool_not_granted"
    event_types = [event.event_type for event in evidence.read_events()]
    assert event_types == ["tool_dispatch_intended", "tool_dispatch_rejected"]
    assert "tool_invocation_started" not in event_types

    envelope = asyncio.run(
        port.invoke(
            tool_id="get_balance",
            arguments={},
            source_provider_call_id="provider_call_pc_0",
            source_call_index=1,
        )
    )
    assert envelope.invocation_record.status == "succeeded"


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
    assert response.action is None, "a text harness carries no action of its own"
    assert response.provider_call_ids, "the attempt must record its provider call"
    # The attempt lifecycle is the kernel's, unchanged: success is recorded
    # before the scheduler ever parses the action.
    events = [json.loads(line) for line in evidence.events_path.read_text().splitlines()]
    kinds = [e["event_type"] for e in events]
    assert "action_attempt_succeeded" in kinds
    assert kinds.index("provider_call_started") < kinds.index("action_attempt_succeeded")


def test_attempt_executor_carries_a_harness_action_onto_the_canonical_response(
    tmp_path,
) -> None:
    """§5.1: `HarnessOutput.action` reaches the `CanonicalResponse` the
    executor hands back, so the scheduler can hand a family's `parse_action`
    the Mapping it requires instead of reading `.text`."""

    from aeread.shared_runner.harness import AttemptExecutor, MinimalChatHarness

    class ActionHarness(MinimalChatHarness):
        async def act(self, request, ctx):
            await ctx.model.complete(
                messages=(CanonicalMessage(role="user", content="hi"),),
                response_mode="text",
            )
            return HarnessOutput(
                action={"decision": "accept", "amount_usd": 12.5},
                claimed_tool_calls=(),
                rounds_used=1,
                notes={},
            )

    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "action_evidence",
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
        providers={profile.model.provider: ScriptedProvider([_result(text="an offer")])},
        pricing={profile.model.model: FAKE_PRICING},
        harnesses={"minimal_chat/1.0": ActionHarness()},
    )

    response = asyncio.run(executor(decision))

    assert response.action == {"decision": "accept", "amount_usd": 12.5}
    assert response.text == "an offer"


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


def _tools_capable_requirements() -> HarnessRequirements:
    return HarnessRequirements(
        provider=frozenset(),
        tools="declared",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=False,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )


def test_attempt_context_grants_a_live_tool_port_when_profile_and_harness_admit_tools(
    tmp_path,
) -> None:
    """Stage 4: the port withheld above is granted once both halves admit
    tools -- the profile declares them (`_profile()`'s `tools=["get_balance",
    "refund_order"]`) and the registered harness's `requires.tools != "none"`.

    `_validate_profile` still hard-requires `minimal_chat/1.0` with no tools
    (that gate is unchanged by this stage), so this exercises the admission
    at `_obtain_result` directly rather than through `executor(decision)`,
    the same way `_profile()` already exists for `KernelModelPort`-level
    tests below rather than for the full executor.
    """

    from aeread.shared_runner.harness import AttemptExecutor, MinimalChatHarness

    seen = {}

    class ToolCapableHarness(MinimalChatHarness):
        requires = _tools_capable_requirements()

        async def act(self, request, ctx):
            seen["tools"] = ctx.tools
            return await super().act(request, ctx)

    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "tools_admitted",
        run_plan_id="runplan_harness_fixture",
        cell_id=decision.cell_id,
        episode_id=decision.episode_id,
        episode_attempt_id="episode_attempt_harness_fixture",
    )
    profile = _profile()
    runtime, _ = _tool_runtime(tmp_path, evidence)
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=[],
        prompt_sources={},
        providers={profile.model.provider: ScriptedProvider([_result(text="ok")])},
        pricing={profile.model.model: FAKE_PRICING},
        harnesses={"native_tool_chat/1.0": ToolCapableHarness()},
        tool_runtimes={profile.profile_id: runtime},
    )
    executor._prompt_text[profile.profile_id] = SYSTEM_PROMPT
    action_attempt_id = "action_attempt_tools_admitted"
    request = executor._request_for(
        decision,
        profile,
        action_attempt_id=action_attempt_id,
        max_output_tokens=profile.sampling.max_output_tokens,
    )

    asyncio.run(
        executor._obtain_result(
            provider=executor._providers[profile.model.provider],
            request=request,
            profile=profile,
            decision=decision,
            action_attempt_id=action_attempt_id,
        )
    )

    assert isinstance(seen["tools"], KernelToolPort)


def test_attempt_context_withholds_the_tool_port_for_a_no_tools_profile_even_with_a_tools_capable_harness(
    tmp_path,
) -> None:
    """A harness's own capability is necessary but not sufficient: without a
    profile that declares tools, the port stays withheld regardless."""

    from aeread.shared_runner.harness import AttemptExecutor, MinimalChatHarness

    seen = {}

    class ToolCapableHarness(MinimalChatHarness):
        requires = _tools_capable_requirements()

        async def act(self, request, ctx):
            seen["tools"] = ctx.tools
            return await super().act(request, ctx)

    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "tools_capable_harness_no_tools_profile",
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
        harnesses={"minimal_chat/1.0": ToolCapableHarness()},
    )

    asyncio.run(executor(decision))

    assert seen["tools"] is None, (
        "a no-tools profile must not receive a tool port even from a "
        "tools-capable harness"
    )


def test_attempt_context_withholds_the_tool_port_when_the_harness_declares_tools_none(
    tmp_path,
) -> None:
    """The profile's own tools declaration is necessary but not sufficient:
    a registered harness that still declares `requires.tools == "none"`
    must not be handed a live port, even for a tools-declaring profile."""

    from aeread.shared_runner.harness import AttemptExecutor, MinimalChatHarness

    seen = {}

    class NoToolsHarness(MinimalChatHarness):
        async def act(self, request, ctx):
            seen["tools"] = ctx.tools
            return await super().act(request, ctx)

    assert NoToolsHarness.requires.tools == "none"

    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "no_tools_harness_tools_profile",
        run_plan_id="runplan_harness_fixture",
        cell_id=decision.cell_id,
        episode_id=decision.episode_id,
        episode_attempt_id="episode_attempt_harness_fixture",
    )
    profile = _profile()
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=[],
        prompt_sources={},
        providers={profile.model.provider: ScriptedProvider([_result(text="ok")])},
        pricing={profile.model.model: FAKE_PRICING},
        harnesses={"native_tool_chat/1.0": NoToolsHarness()},
    )
    executor._prompt_text[profile.profile_id] = SYSTEM_PROMPT
    action_attempt_id = "action_attempt_no_tools_harness"
    request = executor._request_for(
        decision,
        profile,
        action_attempt_id=action_attempt_id,
        max_output_tokens=profile.sampling.max_output_tokens,
    )

    asyncio.run(
        executor._obtain_result(
            provider=executor._providers[profile.model.provider],
            request=request,
            profile=profile,
            decision=decision,
            action_attempt_id=action_attempt_id,
        )
    )

    assert seen["tools"] is None, (
        'a harness declaring tools="none" must not receive a live port'
    )


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



def test_the_sealed_request_is_the_request_actually_sent(tmp_path) -> None:
    """Evidence must record the bytes that were sent, not a second request.

    The executor seals a ProviderRequest and emits provider_call_started for
    it, then hands control to the harness through the port. When the port built
    its own request instead of reusing the sealed one, the provider received
    bytes no event ever recorded: replay would faithfully replay a call that
    never happened, and the mismatch would be invisible because both requests
    look well-formed.
    """

    from aeread.shared_runner.harness import AttemptExecutor, default_harnesses

    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "sealed_request",
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

    asyncio.run(executor(decision))

    sent = provider.requests[-1]
    events = [json.loads(line) for line in evidence.events_path.read_text().splitlines()]
    started = [e for e in events if e["event_type"] == "provider_call_started"]
    assert len(started) == 1, "exactly one provider call must be recorded"

    payload = json.loads((evidence.root / started[0]["payload_ref"]).read_bytes())
    recorded = payload["request"]
    assert recorded["provider_call_id"] == sent.provider_call_id
    assert recorded["request_sha256"] == sent.request_sha256, (
        "the sealed request hash must equal the hash of what was sent"
    )
    assert recorded["input_text"] == sent.input_text



def _executor_with(harness, provider, tmp_path, name):
    """An AttemptExecutor wired to one harness, sharing the executor fixtures."""

    from aeread.shared_runner.harness import AttemptExecutor

    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / name,
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
        providers={profile.model.provider: provider},
        pricing={profile.model.model: FAKE_PRICING},
        harnesses={"minimal_chat/1.0": harness},
    )
    return executor, decision, evidence


def test_a_harness_that_never_returns_is_bounded_by_the_profile_timeout(tmp_path) -> None:
    """A hung provider or a runaway loop must not block the episode forever.

    The base executor bounds its single provider call with asyncio.wait_for.
    A harness owns a loop, so overriding that hook dropped the bound entirely:
    timeout_seconds became a field nobody enforced.
    """

    from aeread.shared_runner.harness import MinimalChatHarness

    class HangingHarness(MinimalChatHarness):
        async def act(self, request, ctx):
            await asyncio.sleep(30)

    provider = ScriptedProvider([_result(text="never reached")])
    executor, decision, _ = _executor_with(
        HangingHarness(), provider, tmp_path, "timeout_evidence"
    )

    with pytest.raises(ProviderFailure) as captured:
        asyncio.run(executor(decision))
    assert captured.value.condition == "timeout"


def test_a_harness_claim_that_disagrees_with_the_kernel_is_recorded(tmp_path) -> None:
    """A harness's claim is reconciled against what the kernel recorded.

    The kernel's count is the truth. A divergence is written as evidence
    rather than raised: a buggy harness must not be able to abort an episode,
    but it must not pass unnoticed either.
    """

    from aeread.shared_runner.harness import MinimalChatHarness

    class LyingHarness(MinimalChatHarness):
        async def act(self, request, ctx):
            output = await super().act(request, ctx)
            return HarnessOutput(
                action=output.action,
                claimed_tool_calls=(
                    ClaimedToolCall(
                        tool_id="get_balance",
                        source_provider_call_id="call_ghost",
                        source_call_index=0,
                    ),
                ),
                rounds_used=output.rounds_used,
                notes=output.notes,
            )

    provider = ScriptedProvider([_result(text="an offer")])
    executor, decision, evidence = _executor_with(
        LyingHarness(), provider, tmp_path, "claim_evidence"
    )

    asyncio.run(executor(decision))

    kinds = [
        json.loads(line)["event_type"]
        for line in evidence.events_path.read_text().splitlines()
    ]
    assert "harness_claim_unreconciled" in kinds


def test_the_context_carries_the_action_attempt_id_not_a_provider_call_id(
    tmp_path,
) -> None:
    """§5.2: AttemptContext.attempt_id identifies the attempt.

    It previously carried the provider_call_id, so every id a harness derived
    from it -- and every tool invocation id minted from it -- was scoped to one
    provider call rather than to the attempt.
    """

    from aeread.shared_runner.harness import MinimalChatHarness

    seen = {}

    class RecordingHarness(MinimalChatHarness):
        async def act(self, request, ctx):
            seen["attempt_id"] = ctx.attempt_id
            return await super().act(request, ctx)

    provider = ScriptedProvider([_result(text="an offer")])
    executor, decision, _ = _executor_with(
        RecordingHarness(), provider, tmp_path, "attempt_id_evidence"
    )
    asyncio.run(executor(decision))

    assert seen["attempt_id"].startswith("action_attempt")
    assert not seen["attempt_id"].startswith("provider_call")


# --- native_tool_chat/1.0: the tool loop matches design §8 exactly ---


def test_native_tool_chat_dispatches_a_grouped_two_call_turn_and_matches_design_section_8_event_order(
    tmp_path,
) -> None:
    """`native_tool_chat/1.0`'s real `act()`, given two rounds of budget,
    reproduces design §8's event sequence exactly: both tool calls of one
    model turn are dispatched under that turn's own `provider_call_id`, the
    results are fed back as one grouped turn, and the attempt is recorded a
    success before the scheduler would ever parse the action.  The scheduler
    events themselves (`action_attempt_started`/`succeeded`, `action_parsed`,
    `action_legality_checked`) are not this harness's to emit -- as in the
    stage-1 hand-simulation above, they are appended around the real `act()`
    call the way the executor's lifecycle already does.
    """

    from aeread.shared_runner.harness import (
        BudgetView,
        NativeToolChatHarness,
        _KernelAttemptContext,
    )

    evidence = _evidence(tmp_path)
    runtime, balance_db = _tool_runtime(tmp_path, evidence)
    profile = _profile()
    decision = _executor_decision()
    action_attempt_id = "action_attempt_native_tool_chat"

    provider = ScriptedProvider(
        [
            _result(
                text="",
                finish_reason="tool_calls",
                tool_calls=(
                    NativeToolCall(call_id="call_0", tool_id="get_balance", arguments={}),
                    NativeToolCall(
                        call_id="call_1",
                        tool_id="refund_order",
                        arguments={"amount_usd": 5},
                    ),
                ),
            ),
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
    context = _KernelAttemptContext(
        attempt_id=action_attempt_id,
        seed=0,
        budget=BudgetView(rounds_left=2, tokens_left=None, cost_left=None),
        model=model_port,
        tools=tool_port,
        evidence=evidence,
    )
    harness = NativeToolChatHarness()

    async def run_attempt() -> HarnessOutput:
        evidence.append_event(
            "logical_action_started",
            {"profile_id": profile.profile_id, "request": {"phase_id": decision.phase_id}},
            logical_action_id="logical_action_fixture",
        )
        evidence.append_event(
            "action_attempt_started",
            {
                "ordinal": 0,
                "retry_reason": None,
                "session_mode": profile.retry_policy.session_mode,
                "rounds_max": context.budget.rounds_left,
                "seed": profile.sampling.seed,
            },
            logical_action_id="logical_action_fixture",
            action_attempt_id=action_attempt_id,
        )

        harness_output = await harness.act(decision, context)

        pre_close_events = evidence.read_events()
        provider_call_ids = list(
            dict.fromkeys(e.provider_call_id for e in pre_close_events if e.provider_call_id)
        )
        tool_invocation_ids = list(
            dict.fromkeys(e.tool_invocation_id for e in pre_close_events if e.tool_invocation_id)
        )
        evidence.append_event(
            "action_attempt_succeeded",
            {
                "provider_call_ids": provider_call_ids,
                "tool_invocation_ids": tool_invocation_ids,
                "claimed_tool_calls": len(harness_output.claimed_tool_calls),
                "reconciled": True,
                "rounds_used": harness_output.rounds_used,
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
        return harness_output

    output = asyncio.run(run_attempt())

    assert output.rounds_used == 2
    # Both calls of the one turn share the same provider_call_id -- one
    # grouped environment hop, in source order.
    first_call, second_call = output.claimed_tool_calls
    assert first_call.source_provider_call_id == second_call.source_provider_call_id
    assert (first_call.source_call_index, second_call.source_call_index) == (0, 1)
    assert first_call.source_provider_call_id == provider.requests[0].provider_call_id
    assert output.action["tool_executions"] == [{}, {}]

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
    for tool_invocation_id in tool_ids:
        subset = [
            event.event_type for event in tool_events if event.tool_invocation_id == tool_invocation_id
        ]
        assert subset == [
            "tool_dispatch_intended",
            "tool_invocation_started",
            "tool_invocation_succeeded",
        ]
    # Attempt success is recorded before the scheduler would ever parse.
    assert event_types.index("action_attempt_succeeded") < event_types.index("action_parsed")

    evidence.audit_reconciliation(entity_types=("action_attempt", "provider_call", "tool_invocation"))


def test_native_tool_chat_rounds_budget_exhausted_is_a_typed_failure(tmp_path) -> None:
    """§8: budgets are port-enforced -- exceeding `rounds_left` closes the
    attempt as a typed `ProviderFailure("rounds_exhausted", ...)`, the same
    typed-failure vocabulary the kernel already retries or terminates on,
    never a bare/untyped exception escaping the loop.  With `rounds_left=1`
    the loop must stop after the first (tool-calling) round rather than ever
    asking the provider a second time.
    """

    from aeread.shared_runner.harness import (
        BudgetView,
        NativeToolChatHarness,
        _KernelAttemptContext,
    )

    evidence = _evidence(tmp_path)
    runtime, _ = _tool_runtime(tmp_path, evidence)
    profile = _profile()
    decision = _executor_decision()
    action_attempt_id = "action_attempt_rounds_exhausted"

    provider = ScriptedProvider(
        [
            _result(
                text="",
                finish_reason="tool_calls",
                tool_calls=(
                    NativeToolCall(call_id="call_0", tool_id="get_balance", arguments={}),
                ),
            ),
        ]
    )
    model_port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=profile,
        instructions=SYSTEM_PROMPT,
        action_attempt_id=action_attempt_id,
    )
    tool_port = KernelToolPort(
        runtime=runtime, attempt_id="attempt_fixture", action_attempt_id=action_attempt_id
    )
    context = _KernelAttemptContext(
        attempt_id=action_attempt_id,
        seed=0,
        budget=BudgetView(rounds_left=1, tokens_left=None, cost_left=None),
        model=model_port,
        tools=tool_port,
        evidence=evidence,
    )
    harness = NativeToolChatHarness()

    with pytest.raises(ProviderFailure) as captured:
        asyncio.run(harness.act(decision, context))

    assert captured.value.condition == "rounds_exhausted"
    assert captured.value.retryable is False
    # The loop stopped before ever asking the provider a second time.
    assert len(provider.requests) == 1


# --- json_dialect/1.0: a thin codec over the same shared tool loop (§6) ---


def test_json_dialect_plural_object_matches_native_tool_chat_grouping_and_event_order(
    tmp_path,
) -> None:
    """The same two-call turn `native_tool_chat/1.0` receives natively, here
    expressed as ONE plural JSON object via `output_schema`
    (`{"kind":"tool_calls","calls":[...]}` then `{"kind":"reply","text":...}`),
    must dispatch the same grouped two-call turn and produce the identical
    event order -- proof that `json_dialect/1.0` is a codec over the same
    `_run_tool_loop` engine, not a second loop with its own grouping.
    """

    from aeread.shared_runner.harness import (
        BudgetView,
        JsonDialectHarness,
        _KernelAttemptContext,
    )

    evidence = _evidence(tmp_path)
    runtime, balance_db = _tool_runtime(tmp_path, evidence)
    profile = _profile()
    decision = _executor_decision()
    action_attempt_id = "action_attempt_json_dialect"

    tool_calls_text = json.dumps(
        {
            "kind": "tool_calls",
            "calls": [
                {"id": "call_0", "name": "get_balance", "arguments": {}},
                {"id": "call_1", "name": "refund_order", "arguments": {"amount_usd": 5}},
            ],
        }
    )
    reply_text = json.dumps({"kind": "reply", "text": "here is your answer"})

    provider = ScriptedProvider(
        [
            _result(text=tool_calls_text, finish_reason="stop"),
            _result(text=reply_text, finish_reason="stop"),
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
    context = _KernelAttemptContext(
        attempt_id=action_attempt_id,
        seed=0,
        budget=BudgetView(rounds_left=2, tokens_left=None, cost_left=None),
        model=model_port,
        tools=tool_port,
        evidence=evidence,
    )
    harness = JsonDialectHarness()

    async def run_attempt() -> HarnessOutput:
        evidence.append_event(
            "logical_action_started",
            {"profile_id": profile.profile_id, "request": {"phase_id": decision.phase_id}},
            logical_action_id="logical_action_fixture",
        )
        evidence.append_event(
            "action_attempt_started",
            {
                "ordinal": 0,
                "retry_reason": None,
                "session_mode": profile.retry_policy.session_mode,
                "rounds_max": context.budget.rounds_left,
                "seed": profile.sampling.seed,
            },
            logical_action_id="logical_action_fixture",
            action_attempt_id=action_attempt_id,
        )

        harness_output = await harness.act(decision, context)

        pre_close_events = evidence.read_events()
        provider_call_ids = list(
            dict.fromkeys(e.provider_call_id for e in pre_close_events if e.provider_call_id)
        )
        tool_invocation_ids = list(
            dict.fromkeys(e.tool_invocation_id for e in pre_close_events if e.tool_invocation_id)
        )
        evidence.append_event(
            "action_attempt_succeeded",
            {
                "provider_call_ids": provider_call_ids,
                "tool_invocation_ids": tool_invocation_ids,
                "claimed_tool_calls": len(harness_output.claimed_tool_calls),
                "reconciled": True,
                "rounds_used": harness_output.rounds_used,
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
        return harness_output

    output = asyncio.run(run_attempt())

    assert output.rounds_used == 2
    # Both calls of the one plural object share the same provider_call_id --
    # one grouped environment hop, in source order, exactly as native.
    first_call, second_call = output.claimed_tool_calls
    assert first_call.source_provider_call_id == second_call.source_provider_call_id
    assert (first_call.source_call_index, second_call.source_call_index) == (0, 1)
    assert first_call.source_provider_call_id == provider.requests[0].provider_call_id
    assert output.action["tool_executions"] == [{}, {}]

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
    ], "json_dialect must match native_tool_chat's event order exactly (§8)"

    provider_call_events = [event for event in events if event.provider_call_id is not None]
    assert len({event.provider_call_id for event in provider_call_events}) == 2
    tool_events = [event for event in events if event.tool_invocation_id is not None]
    tool_ids = {event.tool_invocation_id for event in tool_events}
    assert len(tool_ids) == 2
    for tool_invocation_id in tool_ids:
        subset = [
            event.event_type for event in tool_events if event.tool_invocation_id == tool_invocation_id
        ]
        assert subset == [
            "tool_dispatch_intended",
            "tool_invocation_started",
            "tool_invocation_succeeded",
        ]
    assert event_types.index("action_attempt_succeeded") < event_types.index("action_parsed")

    evidence.audit_reconciliation(entity_types=("action_attempt", "provider_call", "tool_invocation"))


def test_json_dialect_singular_object_is_a_malformed_round_not_a_crash(tmp_path) -> None:
    """§6: the model is asked for the PLURAL shape only -- a singular
    `{"kind":"tool_call", ...}` object has no legal fallback.  It must become
    a typed, counted `malformed_rounds` outcome, never an exception: the
    model's own malformed output must not be able to abort the attempt the
    way a genuine provider or tool contract violation does.
    """

    from aeread.shared_runner.harness import (
        BudgetView,
        JsonDialectHarness,
        _KernelAttemptContext,
    )

    evidence = _evidence(tmp_path, "json_dialect_malformed")
    runtime, _ = _tool_runtime(tmp_path, evidence)
    profile = _profile()
    decision = _executor_decision()
    action_attempt_id = "action_attempt_json_dialect_malformed"

    singular_text = json.dumps(
        {"kind": "tool_call", "id": "call_0", "name": "get_balance", "arguments": {}}
    )
    provider = ScriptedProvider([_result(text=singular_text, finish_reason="stop")])
    model_port = KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=FAKE_PRICING,
        profile=profile,
        instructions=SYSTEM_PROMPT,
        action_attempt_id=action_attempt_id,
    )
    tool_port = KernelToolPort(
        runtime=runtime, attempt_id="attempt_fixture", action_attempt_id=action_attempt_id
    )
    context = _KernelAttemptContext(
        attempt_id=action_attempt_id,
        seed=0,
        budget=BudgetView(rounds_left=2, tokens_left=None, cost_left=None),
        model=model_port,
        tools=tool_port,
        evidence=evidence,
    )
    harness = JsonDialectHarness()

    output = asyncio.run(harness.act(decision, context))

    assert output.claimed_tool_calls == (), "a malformed round dispatches no tool calls"
    assert output.rounds_used == 1
    assert output.notes.get("malformed_rounds") == 1
    # The loop stopped rather than guessing a repair or asking again.
    assert len(provider.requests) == 1

    event_types = [event.event_type for event in evidence.read_events()]
    assert "harness_note" in event_types, "the malformed round must be recorded, not silent"



def test_a_tool_using_profile_is_accepted_by_a_tool_capable_harness(tmp_path) -> None:
    """A tool harness must be reachable through the executor's public API.

    AttemptExecutor inherits MinimalChatExecutor, and inherited its
    harness-specific validation too: every profile was checked against
    minimal_chat/1.0's own guarantee, so a profile naming native_tool_chat was
    refused as "not minimal_chat/1.0". Both tool harnesses S4 built were
    therefore unreachable from production -- they could only ever be driven by
    hand in tests. Validation now runs against the harness the profile names.
    """

    import dataclasses

    from aeread.shared_runner.harness import AttemptExecutor, NativeToolChatHarness

    base = _executor_profile()
    tools_profile = dataclasses.replace(
        base,
        harness=dataclasses.replace(base.harness, id="native_tool_chat"),
        tools=("get_balance",),
    )
    decision = _executor_decision()
    evidence = EvidenceStore(
        tmp_path / "tools_profile",
        run_plan_id="runplan_harness_fixture",
        cell_id=decision.cell_id,
        episode_id=decision.episode_id,
        episode_attempt_id="episode_attempt_harness_fixture",
    )

    # Construction is the gate that used to reject it; reaching past it proves
    # the harness is selectable for a real tools-declaring profile.
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=[tools_profile],
        prompt_sources={base.prompt.prompt_id: _executor_prompt()},
        providers={base.model.provider: ScriptedProvider([_result(text="ok")])},
        pricing={base.model.model: FAKE_PRICING},
        harnesses={"native_tool_chat/1.0": NativeToolChatHarness()},
    )
    assert executor._harness_key(tools_profile) == "native_tool_chat/1.0"

    # minimal_chat's own guarantee is untouched: it still refuses tools.
    from aeread.shared_runner.harness import MinimalChatHarness

    minimal_with_tools = dataclasses.replace(base, tools=("get_balance",))
    with pytest.raises(EvidenceIntegrityError, match="does not permit tools"):
        AttemptExecutor(
            evidence=EvidenceStore(
                tmp_path / "minimal_with_tools",
                run_plan_id="runplan_harness_fixture",
                cell_id=decision.cell_id,
                episode_id=decision.episode_id,
                episode_attempt_id="episode_attempt_harness_fixture",
            ),
            profiles=[minimal_with_tools],
            prompt_sources={base.prompt.prompt_id: _executor_prompt()},
            providers={base.model.provider: ScriptedProvider([_result(text="ok")])},
            pricing={base.model.model: FAKE_PRICING},
            harnesses={"minimal_chat/1.0": MinimalChatHarness()},
        )
