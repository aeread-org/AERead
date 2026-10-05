"""S4 (#226 items 1, 3, 4): in-attempt re-send of declared HTTP refusals.

Red-first tests for the slice specified in
``docs/architecture/provider_reliability.md`` (S4, spec v0.5). Under a profile
that declares ``harness.config["transport_policy"] = "transport_v1"``, a 429 or
5xx that the server answered with no usage is re-sent inside one
``ActionAttempt`` by ``KernelModelPort.complete``, as a new ``ProviderCall``
with the identical request, under its own budget. Every other failure, and
every profile without the declaration (v0), keeps today's path.

How these tests drive the code
- Failures that the spec says must come from the transport originate from the
  REAL openai SDK over the SDK's own mock transport (``httpx`` under openai
  2.x, ``httpx2`` under 3.x, resolved from ``openai._base_client``); the
  kernel's ``OpenRouterChatClient`` classifies them. Nothing hand-builds a
  ``ProviderFailure`` for R1-R5, R10 or R13-R15.
- The clock and the sleep are injected through two module functions the port
  must read: ``harness._transport_monotonic()`` and
  ``harness._transport_sleep(seconds)``. The fixtures below replace both, so no
  test waits for a backoff (R8 waits for the outer timeout, by design).
- Names the implementation must provide, imported lazily so the module still
  collects on main: ``harness._transport_monotonic``, ``harness._transport_sleep``,
  ``execution.declared_transport_policy``, ``execution.transport_resend_class``,
  ``ProviderFailure.http_refusal``, ``KernelModelPort.refused_calls``,
  ``KernelModelPort.in_transport_backoff``.

The v0 golden control
``test_v0_goldens_are_byte_identical`` compares the events and the complete
``LogicalActionExecution`` records of four fault scripts under a v0 profile
with fixed identity inputs and a fixed clock against files committed under
``tests/fixtures/transport_resend/``. They were generated on main before any
implementation change. To regenerate them (only when v0 bytes are meant to
change, and never in CI)::

    AEREAD_REGENERATE_TRANSPORT_GOLDENS=1 PYTHONPATH=src:. \\
        python -m pytest tests/test_transport_resend.py -k v0_goldens -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import gc
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import aeread.shared_runner.model_call.harness as harness_module
from aeread.shared_runner.model_call.harness import (
    AttemptExecutor,
    JsonDialectHarness,
    default_harnesses,
)
from aeread.shared_runner.schemas import AgentProfile
from aeread.shared_runner.task.execution import (
    POST_ADMISSION_REJECTION,
    PROVIDER_CHOICE_ERROR,
    EvidenceIntegrityError,
    EvidenceStore,
    MinimalChatExecutor,
    OpenRouterChatClient,
    ProviderFailure,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from tests.test_shared_runner_execution import _decision, _openrouter_request

import openai

# --- The HTTP library the installed SDK uses ---------------------------------


def _http_lib():
    """``httpx`` under openai 2.x, ``httpx2`` under 3.x (decided by the SDK)."""

    import openai._base_client as base_client

    return base_client.httpx2 if hasattr(base_client, "httpx2") else base_client.httpx


# --- Scenario constants -------------------------------------------------------

MODEL = "deepseek/deepseek-v4-flash-0731"
CANONICAL_MODEL = "deepseek/deepseek-v4-flash-20260731"
BASE_URL = "https://openrouter.ai/api/v1"
PROMPT = "Return only one JSON object matching the requested action schema."
PROMPT_ID = "transport_resend_prompt"
PRICING = TokenPricing(0.08, 0.016, 0.18, "transport_resend_pricing_v1")
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"offer": {"type": "integer", "minimum": 0}},
    "required": ["offer"],
    "additionalProperties": False,
}
PROVIDER_METADATA = {
    "route_provider": "DeepInfra",
    "quantization": "fp8",
    "canonical_model": CANONICAL_MODEL,
    "max_prompt_price_per_million": "0.08",
    "max_completion_price_per_million": "0.18",
}
OK_COST = 0.00001726
TRUNCATED = '{"offer":'

V0_BACKOFF = {"retry_backoff": "exponential_jitter_v1", "retry_base_seconds": 2.0}
V1 = {
    "transport_policy": "transport_v1",
    "transport_max_calls": 3,
    "transport_max_retry_seconds": 30.0,
    **V0_BACKOFF,
}
DECLARED = ("rate_limit", "provider_5xx", "length", "empty_response")


def _v1(**overrides):
    return {**V1, **overrides}


def make_profile(
    config=None,
    *,
    stream: bool = False,
    max_action_attempts: int = 3,
    retryable=DECLARED,
    timeout_seconds: float = 60.0,
    max_cost_usd: float = 0.05,
    harness_id: str = "minimal_chat",
) -> AgentProfile:
    harness_config = {
        "pricing_id": PRICING.pricing_id,
        "pricing_sha256": PRICING.content_sha256(),
        "output_schema": OUTPUT_SCHEMA,
        "provider_metadata": PROVIDER_METADATA,
        **(V1 if config is None else config),
    }
    if stream:
        harness_config["provider_stream"] = True
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": "subject_model_v1",
            "model": {
                "provider": "openrouter",
                "model": MODEL,
                "revision": CANONICAL_MODEL,
                "base_url": BASE_URL,
            },
            "harness": {
                "id": harness_id,
                "version": "1.0",
                "config": harness_config,
            },
            "prompt": {
                "prompt_id": PROMPT_ID,
                "sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
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
                "max_output_tokens": 512,
                "seed": 71001,
                "top_p": 1.0,
            },
            "budgets": {
                "max_logical_actions": 4,
                "timeout_seconds": timeout_seconds,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                "max_action_attempts": max_action_attempts,
                "retryable_conditions": list(retryable),
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


# --- Fake clock and sleep -------------------------------------------------------


class FakeClock:
    """The port's monotonic clock and its backoff sleep.

    Time moves only when a sleep runs (or a test moves it), so every bound in
    the spec can be hit exactly. ``advance_after_first_read`` models time that
    passes between the executor computing ``attempt_deadline`` (the first read,
    in ``AttemptExecutor._obtain_result``) and the port reading ``t0``.
    """

    START = 1000.0

    def __init__(self) -> None:
        self.now = self.START
        self.sleeps: list[float] = []
        self.reads = 0
        self.advance_after_first_read = 0.0
        self.on_sleep = None

    def monotonic(self) -> float:
        value = self.now
        self.reads += 1
        if self.reads == 1 and self.advance_after_first_read:
            self.now += self.advance_after_first_read
        return value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self.on_sleep is not None:
            await self.on_sleep(self, seconds)
        else:
            self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    # raising=False: on main these names do not exist yet; the tests then fail
    # on behaviour, not on a monkeypatch error.
    monkeypatch.setattr(harness_module, "_transport_monotonic", fake.monotonic, raising=False)
    monkeypatch.setattr(harness_module, "_transport_sleep", fake.sleep, raising=False)
    return fake


@pytest.fixture(autouse=True)
def _instant_asyncio_sleep(monkeypatch) -> None:
    """The executor's own (v0 and non-refusal) backoff must not slow the suite."""

    real_sleep = asyncio.sleep

    async def instant(delay, result=None):
        await real_sleep(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", instant)


# --- A scripted server behind the real SDK -----------------------------------------


def _raw_completion(content, *, finish_reason="stop", cost=OK_COST):
    return {
        "id": "gen_transport_fixture",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": 123,
            "completion_tokens": 45,
            "total_tokens": 168,
            "prompt_tokens_details": {"cached_tokens": 7},
            "cost": cost,
            "is_byok": False,
        },
        "openrouter_metadata": {
            "requested": MODEL,
            "strategy": "direct",
            "attempt": 1,
            "endpoints": {
                "total": 1,
                "available": [
                    {"model": CANONICAL_MODEL, "provider": "DeepInfra", "selected": True}
                ],
            },
            "attempts": [
                {"model": CANONICAL_MODEL, "provider": "DeepInfra", "status": 200}
            ],
        },
    }


def _sse(frames) -> bytes:
    body = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames)
    return (body + "data: [DONE]\n\n").encode()


def _stream_frames(raw):
    base = {
        "id": raw["id"],
        "model": raw["model"],
        "object": "chat.completion.chunk",
        "provider": "DeepInfra",
    }
    choice = raw["choices"][0]
    content = choice["message"]["content"]
    frames = []
    if content:
        frames.append(
            {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": None,
                        "delta": {"role": "assistant", "content": content},
                    }
                ],
            }
        )
    finish = {"index": 0, "finish_reason": choice["finish_reason"], "delta": {"role": "assistant", "content": ""}}
    frames.append({**base, "choices": [finish]})
    frames.append(
        {
            **base,
            "choices": [finish],
            "usage": raw["usage"],
            "openrouter_metadata": raw["openrouter_metadata"],
        }
    )
    return frames


def ok(content='{"offer":7}', *, finish_reason="stop", cost=OK_COST):
    """A 200 reply, rendered as JSON or as an SSE stream to match the request."""

    def render(stream):
        lib = _http_lib()
        raw = _raw_completion(content, finish_reason=finish_reason, cost=cost)
        if stream:
            return lib.Response(
                200,
                content=_sse(_stream_frames(raw)),
                headers={"content-type": "text/event-stream"},
            )
        return lib.Response(200, json=raw)

    return render


def choice_error(cost):
    """A 200 whose choice finished with an error, billed with ``cost``."""

    def render(stream):
        lib = _http_lib()
        raw = _raw_completion(None, finish_reason="error", cost=cost)
        return lib.Response(200, json=raw)

    return render


_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def refuse(
    status,
    *,
    headers=None,
    usage_at_top=False,
    usage_under_error=False,
    raw_body=None,
):
    """An HTTP error status; optionally with usage in the body or a non-JSON body."""

    def render(stream):
        lib = _http_lib()
        if raw_body is not None:
            return lib.Response(
                status, content=raw_body, headers={"content-type": "text/html", **(headers or {})}
            )
        error = {"message": f"upstream {status}", "code": status}
        if usage_under_error:
            error["usage"] = dict(_USAGE)
        payload = {"error": error}
        if usage_at_top:
            payload["usage"] = dict(_USAGE)
        return lib.Response(status, json=payload, headers=headers)

    return render


def stalled_status(status=503):
    """An error status whose body never arrives: the library's ReadTimeout."""

    def render(stream):
        lib = _http_lib()

        class Stalled(lib.AsyncByteStream):
            async def __aiter__(self):
                raise lib.ReadTimeout("stalled body")
                yield b""  # pragma: no cover

        return lib.Response(status, stream=Stalled())

    return render


def read_timeout():
    def render(stream):
        lib = _http_lib()
        raise lib.ReadTimeout("read timed out")

    return render


def connect_refused():
    def render(stream):
        lib = _http_lib()
        raise lib.ConnectError("connection refused")

    return render


def error_frame():
    """A streamed 200 that carries an ``error`` frame (S2 shape, no status)."""

    def render(stream):
        lib = _http_lib()
        frame = {"error": {"message": "Provider returned error", "code": 502}}
        return lib.Response(200, content=_sse([frame]), headers={"content-type": "text/event-stream"})

    return render


def dropped_stream():
    def render(stream):
        lib = _http_lib()
        first = _stream_frames(_raw_completion("partial"))[0]

        class Dropped(lib.AsyncByteStream):
            async def __aiter__(self):
                yield f"data: {json.dumps(first)}\n\n".encode()
                raise lib.RemoteProtocolError("peer closed connection")

        return lib.Response(200, stream=Dropped(), headers={"content-type": "text/event-stream"})

    return render


class Wire:
    """Records every request and answers from a script; extras get a 400."""

    def __init__(self, steps) -> None:
        self.steps = list(steps)
        self.bodies: list[bytes] = []

    @property
    def requests(self) -> int:
        return len(self.bodies)

    def handler(self, request):
        lib = _http_lib()
        self.bodies.append(bytes(request.content))
        streamed = bool(json.loads(request.content).get("stream"))
        if not self.steps:
            return lib.Response(400, json={"error": {"message": "unscripted request"}})
        return self.steps.pop(0)(streamed)


def build_client(wire: Wire) -> OpenRouterChatClient:
    lib = _http_lib()
    sdk = openai.AsyncOpenAI(
        api_key="k",
        base_url=BASE_URL,
        max_retries=0,
        http_client=lib.AsyncClient(transport=lib.MockTransport(wire.handler)),
    )
    return OpenRouterChatClient(sdk_client=sdk, base_url=BASE_URL)


class Injecting:
    """Delegates to a client but raises a scripted exception on chosen calls."""

    def __init__(self, inner, faults) -> None:
        self.inner = inner
        self.faults = dict(faults)
        self.calls = 0

    async def complete(self, request):
        index = self.calls
        self.calls += 1
        fault = self.faults.get(index)
        if fault is not None:
            raise fault
        return await self.inner.complete(request)


# --- Evidence reading --------------------------------------------------------------


def read_log(root: Path):
    """Events with their payloads, read straight from disk."""

    entries = []
    for line in (Path(root) / "events.jsonl").read_text().splitlines():
        entry = json.loads(line)
        entry["payload"] = json.loads((Path(root) / entry["payload_ref"]).read_bytes())
        entries.append(entry)
    return entries


def of(log, *types):
    return [entry for entry in log if entry["event_type"] in types]


def port_backoffs(log, kind="retry_backoff_started"):
    """Backoff events the port wrote (they carry a transport ordinal); the
    executor's own backoff between two attempts does not."""

    return [e for e in of(log, kind) if "transport_ordinal" in e["payload"]]


def kinds(log, *types):
    return [entry["event_type"] for entry in log if entry["event_type"] in types]


LIFECYCLE = (
    "action_attempt_started",
    "action_attempt_failed",
    "action_attempt_succeeded",
    "action_attempt_outcome_unknown",
    "provider_call_started",
    "provider_call_failed",
    "provider_call_succeeded",
    "provider_call_outcome_unknown",
    "retry_backoff_started",
    "retry_backoff_completed",
)


def started_ids(log):
    return [entry["provider_call_id"] for entry in of(log, "provider_call_started")]


def exactly(items, count):
    """``items`` as a list, asserting its length first so a mismatch reads as one."""

    items = list(items)
    assert len(items) == count, f"expected {count} item(s), got {len(items)}"
    return items


def jitter_of(call_id: str) -> float:
    """The documented jitter of ``exponential_jitter_v1``: from the call's id."""

    return int(call_id[-4:], 16) % 1000 / 1000.0


def expected_delay(k: int, call_id: str, base: float = 2.0) -> float:
    return min(30.0, base * (2**k)) + jitter_of(call_id)


# --- Driving AttemptExecutor ------------------------------------------------------


class Rig:
    """One logical action through ``AttemptExecutor`` with fixed identities."""

    def __init__(self, tmp_path, steps, profile=None, *, wrap=None, name="evidence"):
        self.profile = profile or make_profile()
        self.wire = Wire(steps)
        client = build_client(self.wire)
        self.provider = wrap(client) if wrap else client
        self.root = tmp_path / name
        self.evidence = EvidenceStore(
            self.root,
            run_plan_id="runplan_fixture",
            cell_id="cell_fixture",
            episode_id="episode_fixture",
            episode_attempt_id="episode_attempt_fixture_0",
            clock=lambda: "2026-10-04T00:00:00Z",
        )
        self.executor = AttemptExecutor(
            evidence=self.evidence,
            profiles=(self.profile,),
            prompt_sources={PROMPT_ID: PROMPT},
            providers={"openrouter": self.provider},
            pricing={MODEL: PRICING},
            harnesses=default_harnesses(),
        )
        self.decision = _decision()
        self.response = None
        self.error: BaseException | None = None

    def run(self) -> "Rig":
        try:
            self.response = asyncio.run(self.executor(self.decision))
        except BaseException as error:  # noqa: BLE001 - CancelledError is the point
            self.error = error
        return self

    @property
    def log(self):
        return read_log(self.root)

    @property
    def execution(self):
        return self.executor.execution_for(self.decision.logical_action_id)

    def finalize_valid(self) -> None:
        """Close a succeeded logical action, as the scheduler does after parsing."""

        self.executor.finalize_logical_action(
            self.decision.logical_action_id, valid=True, failure_code=None
        )

    def close(self) -> None:
        self.evidence.close()


def run_rig(tmp_path, steps, profile=None, **kwargs) -> Rig:
    return Rig(tmp_path, steps, profile, **kwargs).run()


def assert_failed_with(rig: Rig, condition: str) -> ProviderFailure:
    assert isinstance(rig.error, ProviderFailure), (
        f"expected the logical action to fail with {condition!r}; it ended with {rig.error!r}"
    )
    assert rig.error.condition == condition
    return rig.error


# =====================================================================================
# R1  503 then 200: one attempt, two calls
# =====================================================================================


def _plan_setup(monkeypatch, *, config=None, stream=False, max_action_attempts=3,
                retryable=DECLARED, timeout_seconds=60.0, max_cost_usd=0.05):
    """The openrouter single-offer smoke plan with a v1 profile sealed in.

    ``build_single_offer_smoke`` fixes its profile; a shim around
    ``AgentProfile.from_dict`` (restored by monkeypatch) rewrites the few
    fields the scenario needs before the profile is built and pinned.
    """

    import aeread_families.single_offer.runner as runner_module

    real = runner_module.AgentProfile
    declared = V1 if config is None else config

    class Shim:
        @staticmethod
        def from_dict(data):
            data = copy.deepcopy(data)
            data["harness"]["config"].update(declared)
            if stream:
                data["harness"]["config"]["provider_stream"] = True
            data["retry_policy"]["max_action_attempts"] = max_action_attempts
            data["retry_policy"]["retryable_conditions"] = list(retryable)
            data["budgets"]["timeout_seconds"] = timeout_seconds
            data["budgets"]["max_cost_usd"] = max_cost_usd
            return real.from_dict(data)

    monkeypatch.setattr(runner_module, "AgentProfile", Shim)
    return runner_module.build_single_offer_smoke(
        provider="openrouter", model=MODEL, revision=CANONICAL_MODEL
    )


def _provider_failure_in(error):
    """The ProviderFailure a scheduler wrapper carries, if any."""

    while error is not None:
        if isinstance(error, ProviderFailure):
            return error
        error = error.__cause__ or error.__context__
    return None


def run_cell(tmp_path, monkeypatch, steps, *, name="run", **plan_kwargs):
    """``execute_plan_cell`` with the real SDK behind the kernel client."""

    setup = _plan_setup(monkeypatch, **plan_kwargs)
    wire = Wire(steps)
    root = tmp_path / name
    outcome = SimpleNamespace(setup=setup, wire=wire, root=root, execution=None, error=None)
    try:
        outcome.execution = asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=root,
                prompt_sources=setup.prompt_sources,
                providers={"openrouter": build_client(wire)},
                pricing=setup.pricing,
            )
        )
        outcome.attempt_dir = outcome.execution.evidence.root
    except BaseException as error:  # noqa: BLE001
        outcome.error = error
        outcome.attempt_dir = next(root.rglob("events.jsonl")).parent
    outcome.log = read_log(outcome.attempt_dir)
    outcome.failure = _provider_failure_in(outcome.error)
    return outcome


@pytest.mark.parametrize("stream", [False, True], ids=["non_streamed", "streamed"])
def test_a_503_then_200_is_resent_inside_one_attempt(tmp_path, monkeypatch, stream) -> None:
    run = run_cell(tmp_path, monkeypatch, [refuse(503), ok()], stream=stream)

    assert run.error is None, repr(run.error)
    assert run.execution.episode_result.final_state["offer"] == 7
    assert run.wire.requests == 2

    # One attempt, with the two calls in order; max_action_attempts is untouched.
    log = run.log
    assert kinds(log, *LIFECYCLE) == [
        "action_attempt_started",
        "provider_call_started",
        "provider_call_failed",
        "retry_backoff_started",
        "retry_backoff_completed",
        "provider_call_started",
        "provider_call_succeeded",
        "action_attempt_succeeded",
    ]
    (action,) = exactly(run.execution.action_executions, 1)
    (attempt,) = exactly(action.attempts, 1)
    assert attempt.ordinal == 0 and attempt.retry_reason is None
    c0, c1 = exactly(started_ids(log), 2)
    assert c0 != c1
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [
        (c0, "failed"),
        (c1, "succeeded"),
    ]

    # The refused call carries the new facts; the re-sent call is a new call id.
    (failed,) = exactly(of(log, "provider_call_failed"), 1)
    assert failed["provider_call_id"] == c0
    assert failed["payload"]["http_refusal"] is True
    assert failed["payload"]["transport_ordinal"] == 0
    assert failed["payload"]["failure_condition"] == "provider_5xx"
    started = of(log, "provider_call_started")
    assert started[1]["payload"]["transport_ordinal"] == 1
    for backoff in of(log, "retry_backoff_started", "retry_backoff_completed"):
        assert backoff["payload"]["transport_ordinal"] == 0
        assert backoff["action_attempt_id"] == attempt.action_attempt_id

    # The identical request: same hash, byte-identical wire body.
    first, second = (entry["payload"]["request"] for entry in started)
    assert first["request_sha256"] == second["request_sha256"]
    assert run.wire.bodies[0] == run.wire.bodies[1]
    assert (stream is True) == bool(json.loads(run.wire.bodies[0]).get("stream"))
    run.execution.evidence.audit_reconciliation()


# =====================================================================================
# R2, R3  The backoff schedule
# =====================================================================================


def test_each_resend_waits_base_times_two_to_the_k_plus_the_jitter_of_that_call(tmp_path, clock) -> None:
    rig = run_rig(
        tmp_path,
        [refuse(503), refuse(503), ok()],
        make_profile(_v1(transport_max_calls=3)),
    )

    assert rig.error is None, repr(rig.error)
    assert rig.wire.requests == 3
    log = rig.log
    c0, c1, c2 = exactly(started_ids(log), 3)
    backoffs = of(log, "retry_backoff_started")
    assert [entry["payload"].get("transport_ordinal") for entry in backoffs] == [0, 1]
    delays = [entry["payload"]["delay_seconds"] for entry in backoffs]
    assert delays == [
        pytest.approx(expected_delay(0, c0), abs=1e-9),
        pytest.approx(expected_delay(1, c1), abs=1e-9),
    ]
    assert clock.sleeps == pytest.approx(delays, abs=1e-9)
    assert [e["payload"]["delay_seconds"] for e in of(log, "retry_backoff_completed")] == pytest.approx(delays)
    assert [(call.provider_call_id, call.status) for call in rig.execution.attempts[0].provider_calls] == [
        (c0, "failed"),
        (c1, "failed"),
        (c2, "succeeded"),
    ]
    rig.finalize_valid()
    rig.evidence.audit_reconciliation()


def _rate_limited(retry_after):
    return refuse(429, headers={"Retry-After": str(retry_after)})


def test_a_429_with_retry_after_waits_that_long_when_the_cap_allows_it(tmp_path, clock) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=50.0, retry_after_max_seconds=60.0))
    rig = run_rig(tmp_path, [_rate_limited(45), ok()], profile)

    assert rig.error is None, repr(rig.error)
    (backoff,) = exactly(of(rig.log, "retry_backoff_started"), 1)
    assert backoff["payload"].get("transport_ordinal") == 0
    assert backoff["payload"]["failure_condition"] == "rate_limit"
    assert backoff["payload"]["delay_seconds"] == 45.0
    assert backoff["payload"]["provider_retry_after_seconds"] == 45.0
    assert backoff["payload"]["retry_after_capped"] is False
    assert clock.sleeps == [45.0]


def test_a_429_retry_after_above_the_cap_is_capped_and_recorded_as_capped(tmp_path, clock) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=50.0, retry_after_max_seconds=30.0))
    rig = run_rig(tmp_path, [_rate_limited(45), ok()], profile)

    assert rig.error is None, repr(rig.error)
    (backoff,) = exactly(of(rig.log, "retry_backoff_started"), 1)
    assert backoff["payload"].get("transport_ordinal") == 0
    assert backoff["payload"]["delay_seconds"] == 30.0
    assert backoff["payload"]["provider_retry_after_seconds"] == 45.0
    assert backoff["payload"]["retry_after_capped"] is True
    assert backoff["payload"]["retry_after_max_seconds"] == 30.0
    assert clock.sleeps == [30.0]


# =====================================================================================
# R4  Exhausting the re-send budget ends the logical action
# =====================================================================================


def test_exhausting_the_resend_budget_fails_the_logical_action_without_a_second_attempt(tmp_path) -> None:
    profile = make_profile(_v1(transport_max_calls=3), max_action_attempts=3)
    rig = run_rig(tmp_path, [refuse(503)] * 4 + [ok()], profile)

    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == 3
    log = rig.log
    assert len(of(log, "action_attempt_started")) == 1
    c0, c1, c2 = exactly(started_ids(log), 3)
    assert len({c0, c1, c2}) == 3
    (failed_attempt,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed_attempt["payload"]["failure_condition"] == "provider_5xx"
    assert failed_attempt["payload"]["transport_exhausted"] is True
    assert [e["payload"]["transport_ordinal"] for e in of(log, "provider_call_failed")] == [0, 1, 2]
    assert len(of(log, "retry_backoff_started")) == 2
    assert len(of(log, "logical_action_failed")) == 1
    assert rig.execution.status == "failed"
    assert rig.execution.failure_code == "provider_5xx"
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert [call.provider_call_id for call in attempt.provider_calls] == [c0, c1, c2]
    assert {call.status for call in attempt.provider_calls} == {"failed"}
    rig.evidence.audit_reconciliation()


def test_the_port_keeps_refused_calls_apart_from_the_rounds_that_prove_a_route(tmp_path) -> None:
    rig = run_rig(tmp_path, [refuse(503), refuse(503), ok()], make_profile(_v1(transport_max_calls=3)))

    assert rig.error is None, repr(rig.error)
    (port,) = exactly(rig.executor._ports.values(), 1)
    c0, c1, c2 = exactly(started_ids(rig.log), 3)
    assert [(call.provider_call_id, call.status, call.cost_usd) for call in port.refused_calls] == [
        (c0, "failed", 0.0),
        (c1, "failed", 0.0),
    ]
    assert [entry.provider_call_id for entry in port.rounds] == [c2]
    assert port.in_transport_backoff is False


# =====================================================================================
# R5  Admission before the sleep
# =====================================================================================


def _assert_ended_without_a_backoff(rig: Rig, condition="rate_limit") -> None:
    assert rig.wire.requests == 1, "the refused request must not be sent again"
    assert_failed_with(rig, condition)
    log = rig.log
    assert of(log, "retry_backoff_started") == []
    assert len(of(log, "provider_call_started")) == 1
    assert len(of(log, "action_attempt_started")) == 1
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed["payload"]["transport_exhausted"] is True
    assert len(of(log, "logical_action_failed")) == 1


def test_a_retry_after_past_the_retry_window_starts_no_backoff(tmp_path) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=10.0, retry_after_max_seconds=30.0))
    rig = run_rig(tmp_path, [_rate_limited(20), ok()], profile)
    _assert_ended_without_a_backoff(rig)


def test_a_retry_after_past_the_attempt_deadline_starts_no_backoff(tmp_path, clock) -> None:
    """Only the attempt deadline binds here.

    Five seconds pass between the executor computing ``attempt_deadline`` (the
    first clock read) and the port reading ``t0``, so ``t0 + window`` lies
    beyond the deadline while a 14 s delay still fits inside the window.
    """

    clock.advance_after_first_read = 5.0
    profile = make_profile(
        _v1(transport_max_retry_seconds=15.0, retry_after_max_seconds=30.0), timeout_seconds=15.0
    )
    rig = run_rig(tmp_path, [_rate_limited(14), ok()], profile)
    _assert_ended_without_a_backoff(rig)


def test_the_same_delay_inside_both_bounds_is_admitted(tmp_path, clock) -> None:
    clock.advance_after_first_read = 5.0
    profile = make_profile(
        _v1(transport_max_retry_seconds=15.0, retry_after_max_seconds=30.0), timeout_seconds=15.0
    )
    rig = run_rig(tmp_path, [_rate_limited(4), ok()], profile)

    assert rig.error is None, repr(rig.error)
    assert clock.sleeps == [4.0]
    assert rig.wire.requests == 2


# =====================================================================================
# R6  The check before the opening event
# =====================================================================================


def _assert_stopped_before_the_opening(rig: Rig) -> None:
    assert rig.wire.requests == 1, "no second request may be sent"
    failure = assert_failed_with(rig, "provider_5xx")
    log = rig.log
    (c0,) = exactly(started_ids(log), 1)
    assert len(of(log, "retry_backoff_started")) == 1
    assert len(of(log, "retry_backoff_completed")) == 1
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed["payload"]["transport_exhausted"] is True
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert [call.provider_call_id for call in attempt.provider_calls] == [c0]
    assert str(failure) == of(log, "provider_call_failed")[0]["payload"]["message"]
    rig.evidence.audit_reconciliation()


def test_a_clock_that_passes_the_window_during_the_sleep_stops_the_resend(tmp_path, clock) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=10.0))

    async def overshoot(fake, seconds):
        fake.now = FakeClock.START + 10.0 + 1.0

    clock.on_sleep = overshoot
    rig = run_rig(tmp_path, [refuse(503), ok()], profile)
    _assert_stopped_before_the_opening(rig)


def test_a_clock_that_passes_the_window_while_the_completed_event_is_written_stops_the_resend(
    tmp_path, clock
) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=10.0))
    rig = Rig(tmp_path, [refuse(503), ok()], profile)
    original = rig.evidence.append_event

    def slow_write(kind, payload, **labels):
        event = original(kind, payload, **labels)
        if kind == "retry_backoff_completed":
            clock.now = FakeClock.START + 10.0 + 1.0
        return event

    rig.evidence.append_event = slow_write
    rig.run()
    _assert_stopped_before_the_opening(rig)


def test_a_clock_that_passes_the_attempt_deadline_during_the_sleep_stops_the_resend(tmp_path, clock) -> None:
    """Only the deadline is passed: ``t0 + window`` (START + 20) is still ahead.

    The deadline is START + 15 (first clock read); the sleep ends at START + 16.
    """

    clock.advance_after_first_read = 5.0
    profile = make_profile(
        _v1(transport_max_retry_seconds=15.0), timeout_seconds=15.0
    )

    async def overshoot(fake, seconds):
        fake.now = FakeClock.START + 16.0

    clock.on_sleep = overshoot
    rig = run_rig(tmp_path, [refuse(503), ok()], profile)
    _assert_stopped_before_the_opening(rig)


# =====================================================================================
# R7  Interruption
# =====================================================================================


def _terminals(log, prefix):
    return [e for e in log if e["event_type"] in {f"{prefix}_failed", f"{prefix}_succeeded", f"{prefix}_outcome_unknown"}]


def _assert_evidence_survives_audit_and_resume(rig: Rig) -> None:
    rig.evidence.audit_reconciliation()
    rig.close()
    audited = EvidenceStore.audit_existing(rig.root)
    audited.close()
    resumed = EvidenceStore(
        rig.root,
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        resume=True,
    )
    resumed.close()


def test_cancelling_a_resent_call_records_one_terminal_per_call_attempt_and_action(tmp_path) -> None:
    rig = run_rig(
        tmp_path,
        [refuse(503), ok()],
        make_profile(_v1()),
        wrap=lambda client: Injecting(client, {1: asyncio.CancelledError()}),
    )

    assert isinstance(rig.error, asyncio.CancelledError), repr(rig.error)
    log = rig.log
    c0, c1 = exactly(started_ids(log), 2)
    assert [(e["provider_call_id"], e["event_type"]) for e in _terminals(log, "provider_call")] == [
        (c0, "provider_call_failed"),
        (c1, "provider_call_outcome_unknown"),
    ]
    assert len(_terminals(log, "action_attempt")) == 1
    assert len(of(log, "action_attempt_outcome_unknown")) == 1
    assert len(of(log, "logical_action_outcome_unknown")) == 1
    execution = rig.execution
    assert execution.status == "outcome_unknown"
    (attempt,) = exactly(execution.attempts, 1)
    assert attempt.status == "outcome_unknown"
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [
        (c0, "failed"),
        (c1, "outcome_unknown"),
    ]
    _assert_evidence_survives_audit_and_resume(rig)


def test_cancelling_a_port_backoff_writes_no_provider_terminal_and_names_the_backoff(tmp_path, clock) -> None:
    rig = Rig(tmp_path, [refuse(503), ok()], make_profile(_v1()))
    seen = {}

    async def cancel(fake, seconds):
        (port,) = exactly(rig.executor._ports.values(), 1)
        seen["in_backoff"] = port.in_transport_backoff
        raise asyncio.CancelledError()

    clock.on_sleep = cancel
    rig.run()

    assert isinstance(rig.error, asyncio.CancelledError), repr(rig.error)
    assert seen == {"in_backoff": True}
    log = rig.log
    (c0,) = exactly(started_ids(log), 1)
    assert [e["provider_call_id"] for e in _terminals(log, "provider_call")] == [c0]
    assert of(log, "retry_backoff_completed") == []
    (unknown,) = exactly(of(log, "action_attempt_outcome_unknown"), 1)
    assert unknown["payload"]["failure_condition"] == "interrupted_during_retry_backoff"
    assert len(of(log, "logical_action_outcome_unknown")) == 1
    execution = rig.execution
    assert execution.status == "outcome_unknown"
    (attempt,) = exactly(execution.attempts, 1)
    assert attempt.status == "outcome_unknown"
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [(c0, "failed")]
    _assert_evidence_survives_audit_and_resume(rig)


# =====================================================================================
# R8  The outer timeout during a port backoff
# =====================================================================================


def test_the_outer_timeout_during_a_port_backoff_fabricates_no_record(tmp_path, clock) -> None:
    """The real ``wait_for`` fires (1.5 s) while the stub sleep blocks forever.

    The delay (base 0.05 s plus a jitter below 1 s) is admitted against the
    fake clock, which does not move, so the timeout can only be by overshoot.
    """

    profile = make_profile(
        _v1(transport_max_retry_seconds=1.5, retry_base_seconds=0.05),
        timeout_seconds=1.5,
        retryable=("rate_limit", "provider_5xx"),
    )

    async def block(fake, seconds):
        await asyncio.Event().wait()

    clock.on_sleep = block
    rig = run_rig(tmp_path, [refuse(503), ok()], profile)

    assert rig.wire.requests == 1
    assert_failed_with(rig, "timeout")
    log = rig.log
    (c0,) = exactly(started_ids(log), 1)
    assert [e["provider_call_id"] for e in _terminals(log, "provider_call")] == [c0]
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed["payload"]["failure_condition"] == "timeout"
    assert failed["payload"]["during_transport_backoff"] is True
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [(c0, "failed")]
    rig.evidence.audit_reconciliation()


# =====================================================================================
# R9  A refused call does not prove the route
# =====================================================================================


def test_a_refusal_followed_by_a_first_ever_404_is_a_plain_rejection(tmp_path) -> None:
    profile = make_profile(
        retryable=("rate_limit", "provider_5xx", POST_ADMISSION_REJECTION),
        config=_v1(),
    )
    rig = run_rig(tmp_path, [refuse(503), refuse(404), ok()], profile)

    assert_failed_with(rig, "provider_rejected")
    assert rig.wire.requests == 2
    log = rig.log
    (attempt_failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert attempt_failed["payload"]["failure_condition"] == "provider_rejected"
    assert len(of(log, "action_attempt_started")) == 1
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert [call.status for call in attempt.provider_calls] == ["failed", "failed"]
    assert rig.execution.failure_code == "provider_rejected"
    rig.evidence.audit_reconciliation()


# =====================================================================================
# R10  http_refusal
# =====================================================================================


def _failure_of(stream: bool, step) -> ProviderFailure:
    wire = Wire([step])
    client = build_client(wire)
    request = _openrouter_request()
    if stream:
        request = dataclasses.replace(request, stream=True).with_computed_hash()
    with pytest.raises(ProviderFailure) as captured:
        asyncio.run(client.complete(request))
    return captured.value


@pytest.mark.parametrize("stream", [False, True], ids=["non_streamed", "streamed"])
@pytest.mark.parametrize(
    "step",
    [
        refuse(429),
        refuse(500),
        refuse(503),
        refuse(502, raw_body=b"<html><body>502 Bad Gateway</body></html>"),
    ],
    ids=["429", "500", "503", "502_non_json_body"],
)
def test_a_status_refusal_with_no_usage_is_marked_http_refusal(stream, step) -> None:
    assert _failure_of(stream, step).http_refusal is True


@pytest.mark.parametrize("stream", [False, True], ids=["non_streamed", "streamed"])
@pytest.mark.parametrize(
    "step",
    [refuse(503, usage_at_top=True), refuse(503, usage_under_error=True)],
    ids=["usage_at_top_level", "usage_under_error"],
)
def test_a_refusal_whose_body_reports_usage_is_not_marked(stream, step) -> None:
    failure = _failure_of(stream, step)
    assert failure.condition == "provider_5xx"
    assert failure.http_refusal is False


@pytest.mark.parametrize("stream", [False, True], ids=["non_streamed", "streamed"])
def test_a_stalled_error_body_is_not_marked(stream) -> None:
    failure = _failure_of(stream, stalled_status(503))
    assert failure.condition == "timeout"
    assert failure.http_refusal is False


def test_an_error_frame_on_a_stream_is_not_marked() -> None:
    failure = _failure_of(True, error_frame())
    assert failure.http_refusal is False


@pytest.mark.parametrize("status", [402, 404, 408])
def test_statuses_outside_429_and_5xx_are_never_marked(status) -> None:
    failure = _failure_of(False, refuse(status))
    assert failure.status_code == status
    assert failure.http_refusal is False


def test_a_hand_built_failure_is_not_a_refusal_unless_a_classifier_says_so() -> None:
    assert ProviderFailure("provider_5xx", "x", retryable=True, status_code=503).http_refusal is False


# =====================================================================================
# R11  Declaration and validation
# =====================================================================================


def _declared(profile):
    from aeread.shared_runner.task import execution as execution_module

    return execution_module.declared_transport_policy(profile)


def test_no_declaration_means_no_policy() -> None:
    assert _declared(make_profile(V0_BACKOFF)) is None


def test_a_well_formed_declaration_is_accepted_at_its_boundaries() -> None:
    for overrides in (
        {},
        {"transport_max_calls": 2},
        {"transport_max_calls": 20},
        {"transport_max_retry_seconds": 60.0},
        {"transport_max_retry_seconds": 5},
        {"transport_max_retry_seconds": 0.001},
    ):
        assert _declared(make_profile(_v1(**overrides))) is not None, overrides


_MALFORMED = {
    "policy_wrong_string": {"transport_policy": "transport_v2"},
    "policy_not_string": {"transport_policy": 1},
    "policy_bool": {"transport_policy": True},
    "calls_missing": {"transport_max_calls": None},
    "calls_one": {"transport_max_calls": 1},
    "calls_zero": {"transport_max_calls": 0},
    "calls_above_20": {"transport_max_calls": 21},
    "calls_bool": {"transport_max_calls": True},
    "calls_float": {"transport_max_calls": 3.0},
    "calls_string": {"transport_max_calls": "3"},
    "window_missing": {"transport_max_retry_seconds": None},
    "window_zero": {"transport_max_retry_seconds": 0},
    "window_negative": {"transport_max_retry_seconds": -1.0},
    "window_above_timeout": {"transport_max_retry_seconds": 60.5},
    "window_bool": {"transport_max_retry_seconds": True},
    "window_string": {"transport_max_retry_seconds": "10"},
    "backoff_missing": {"retry_backoff": None},
    "backoff_other": {"retry_backoff": "fixed_delay"},
}


def _malformed_profile(overrides):
    config = _v1()
    for key, value in overrides.items():
        if value is None:
            config.pop(key)
        else:
            config[key] = value
    return make_profile(config)


@pytest.mark.parametrize("case", sorted(_MALFORMED))
def test_every_malformed_declaration_is_refused(case) -> None:
    with pytest.raises(EvidenceIntegrityError):
        _declared(_malformed_profile(_MALFORMED[case]))


@pytest.mark.parametrize("case", ["calls_one", "window_above_timeout", "backoff_missing", "policy_wrong_string"])
def test_the_attempt_executor_refuses_a_malformed_declaration_at_construction(tmp_path, case) -> None:
    with pytest.raises(EvidenceIntegrityError):
        Rig(tmp_path, [], _malformed_profile(_MALFORMED[case]))


def test_the_direct_minimal_chat_executor_refuses_v1_at_construction(tmp_path) -> None:
    evidence = EvidenceStore(
        tmp_path / "direct",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    with pytest.raises(EvidenceIntegrityError):
        MinimalChatExecutor(
            evidence=evidence,
            profiles=(make_profile(_v1()),),
            prompt_sources={PROMPT_ID: PROMPT},
            providers={"openrouter": build_client(Wire([]))},
            pricing={MODEL: PRICING},
        )
    evidence.close()


def test_the_direct_minimal_chat_executor_still_accepts_a_v0_profile(tmp_path) -> None:
    evidence = EvidenceStore(
        tmp_path / "direct_v0",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    MinimalChatExecutor(
        evidence=evidence,
        profiles=(make_profile(V0_BACKOFF),),
        prompt_sources={PROMPT_ID: PROMPT},
        providers={"openrouter": build_client(Wire([]))},
        pricing={MODEL: PRICING},
    )
    evidence.close()


def test_the_attempt_executor_refuses_v1_for_any_harness_but_minimal_chat(tmp_path) -> None:
    evidence = EvidenceStore(
        tmp_path / "other_harness",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    with pytest.raises(EvidenceIntegrityError):
        AttemptExecutor(
            evidence=evidence,
            profiles=(make_profile(_v1(), harness_id="json_dialect"),),
            prompt_sources={PROMPT_ID: PROMPT},
            providers={"openrouter": build_client(Wire([]))},
            pricing={MODEL: PRICING},
            harnesses={**default_harnesses(), "json_dialect/1.0": JsonDialectHarness()},
        )
    evidence.close()


def test_the_attempt_executor_accepts_that_other_harness_without_v1(tmp_path) -> None:
    evidence = EvidenceStore(
        tmp_path / "other_harness_v0",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    AttemptExecutor(
        evidence=evidence,
        profiles=(make_profile(V0_BACKOFF, harness_id="json_dialect"),),
        prompt_sources={PROMPT_ID: PROMPT},
        providers={"openrouter": build_client(Wire([]))},
        pricing={MODEL: PRICING},
        harnesses={**default_harnesses(), "json_dialect/1.0": JsonDialectHarness()},
    )
    evidence.close()


# Eligibility, as a pure function of the failure and the profile.


def _refusal(condition="provider_5xx", status=503, *, marked=True) -> ProviderFailure:
    failure = ProviderFailure(condition, "refused", retryable=True, status_code=status)
    failure.http_refusal = marked
    return failure


@pytest.mark.parametrize(
    ("failure", "retryable", "expected"),
    [
        (_refusal("provider_5xx", 503), DECLARED, True),
        (_refusal("rate_limit", 429), DECLARED, True),
        (_refusal("provider_5xx", 503, marked=False), DECLARED, False),
        (_refusal("transport", 503), DECLARED, False),
        (_refusal("timeout", 503), DECLARED, False),
        (_refusal("provider_5xx", 503), ("rate_limit",), False),
        (_refusal("rate_limit", 429), ("provider_5xx",), False),
    ],
    ids=[
        "5xx_declared",
        "429_declared",
        "unmarked",
        "marked_but_transport",
        "marked_but_timeout",
        "5xx_undeclared",
        "429_undeclared",
    ],
)
def test_transport_resend_class_needs_a_marked_refusal_of_a_declared_condition(
    failure, retryable, expected
) -> None:
    from aeread.shared_runner.task import execution as execution_module

    profile = make_profile(_v1(), retryable=retryable)
    assert bool(execution_module.transport_resend_class(failure, profile)) is expected


# =====================================================================================
# R12  Cost admission
# =====================================================================================


def _cost_fixture(tmp_path, *, budget, billed, final_cost=0.000001):
    """A billed choice-error attempt, then a 503 in the retry attempt."""

    profile = make_profile(
        _v1(),
        max_cost_usd=budget,
        retryable=("rate_limit", "provider_5xx", PROVIDER_CHOICE_ERROR),
    )
    return run_rig(
        tmp_path,
        [choice_error(billed), refuse(503), ok(cost=final_cost), ok(cost=final_cost)],
        profile,
    )


def test_no_resend_when_a_prior_billed_attempt_exceeded_the_cost_budget(tmp_path) -> None:
    rig = _cost_fixture(tmp_path, budget=0.00001, billed=0.00002)

    assert rig.wire.requests == 2
    assert_failed_with(rig, "provider_5xx")
    assert rig.executor.total_cost_usd == pytest.approx(0.00002)
    log = rig.log
    assert port_backoffs(log) == []
    (second_failed,) = exactly([e for e in of(log, "action_attempt_failed") if e["payload"]["failure_condition"] == "provider_5xx"], 1)
    assert second_failed["payload"]["transport_exhausted"] is True


def test_no_resend_when_spent_equals_the_cost_budget_exactly(tmp_path) -> None:
    rig = _cost_fixture(tmp_path, budget=0.00002, billed=0.00002)

    assert rig.wire.requests == 2
    assert_failed_with(rig, "provider_5xx")
    assert port_backoffs(rig.log) == []


def test_a_resend_is_admitted_while_spent_is_strictly_below_the_cost_budget(tmp_path) -> None:
    rig = _cost_fixture(tmp_path, budget=0.00002, billed=0.00001)

    assert rig.error is None, repr(rig.error)
    assert rig.wire.requests == 3
    log = rig.log
    attempts = of(log, "action_attempt_started")
    assert len(attempts) == 2
    second = attempts[1]["action_attempt_id"]
    assert [e["payload"].get("transport_ordinal") for e in of(log, "provider_call_failed") if e["action_attempt_id"] == second] == [0]
    assert len([e for e in of(log, "provider_call_started") if e["action_attempt_id"] == second]) == 2


# =====================================================================================
# R13  Diagnostics name the call that produced the result
# =====================================================================================


def test_an_empty_completion_after_a_resend_names_the_resent_call(tmp_path) -> None:
    profile = make_profile(_v1(), max_action_attempts=1)
    rig = run_rig(tmp_path, [refuse(503), ok(content="")], profile)

    failure = assert_failed_with(rig, "empty_response")
    c0, c1 = exactly(started_ids(rig.log), 2)
    assert c1 in str(failure)
    assert c0 not in str(failure)
    assert len(of(rig.log, "action_attempt_started")) == 1


def test_a_truncated_completion_after_a_resend_names_the_resent_call(tmp_path) -> None:
    profile = make_profile(_v1(), max_action_attempts=1)
    rig = run_rig(tmp_path, [refuse(503), ok(content=TRUNCATED, finish_reason="length")], profile)

    failure = assert_failed_with(rig, "length")
    c0, c1 = exactly(started_ids(rig.log), 2)
    assert c1 in str(failure)
    assert c0 not in str(failure)
    assert len(of(rig.log, "action_attempt_started")) == 1


# =====================================================================================
# R14  The declared call cap and its per-attempt reset
# =====================================================================================


@pytest.mark.parametrize("limit", [2, 3, 5])
def test_the_call_cap_is_exactly_the_declared_transport_max_calls(tmp_path, limit) -> None:
    profile = make_profile(
        _v1(transport_max_calls=limit, transport_max_retry_seconds=60.0), max_action_attempts=3
    )
    rig = run_rig(tmp_path, [refuse(503)] * (limit + 2), profile)

    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == limit
    log = rig.log
    ids = started_ids(log)
    assert len(ids) == len(set(ids)) == limit
    assert len(of(log, "action_attempt_started")) == 1
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed["payload"]["transport_exhausted"] is True
    assert len(of(log, "retry_backoff_started")) == limit - 1


def test_a_semantic_retry_gets_a_fresh_resend_budget_and_ordinals_restart(tmp_path) -> None:
    profile = make_profile(_v1(transport_max_calls=3), max_action_attempts=3)
    steps = [
        refuse(503),
        ok(content=TRUNCATED, finish_reason="length"),
        refuse(503),
        refuse(503),
        ok(),
    ]
    rig = run_rig(tmp_path, steps, profile)

    assert rig.error is None, repr(rig.error)
    assert rig.wire.requests == 5
    log = rig.log
    ids = started_ids(log)
    assert len(ids) == len(set(ids)) == 5
    first, second = exactly([e["action_attempt_id"] for e in of(log, "action_attempt_started")], 2)

    def ordinals(kind, attempt):
        return [
            e["payload"]["transport_ordinal"]
            for e in of(log, kind)
            if e["action_attempt_id"] == attempt
        ]

    assert ordinals("provider_call_failed", first) == [0]
    assert ordinals("retry_backoff_started", first) == [0]
    assert ordinals("provider_call_failed", second) == [0, 1]
    assert ordinals("retry_backoff_started", second) == [0, 1]
    first_record, second_record = exactly(rig.execution.attempts, 2)
    assert first_record.status == "failed" and second_record.status == "succeeded"
    assert second_record.retry_reason == "length"
    assert [call.status for call in first_record.provider_calls] == ["failed", "succeeded"]
    assert [call.status for call in second_record.provider_calls] == ["failed", "failed", "succeeded"]
    rig.finalize_valid()
    rig.evidence.audit_reconciliation()


# =====================================================================================
# R15  The window is cumulative
# =====================================================================================


def test_the_retry_window_runs_from_the_first_call_and_is_not_restarted(tmp_path, clock) -> None:
    profile = make_profile(
        _v1(transport_max_calls=5, transport_max_retry_seconds=6.0, retry_base_seconds=2.0),
        max_action_attempts=3,
    )
    rig = run_rig(tmp_path, [refuse(503)] * 4 + [ok()], profile)

    assert_failed_with(rig, "provider_5xx")
    log = rig.log
    c0, c1 = exactly(started_ids(log), 2)
    assert rig.wire.requests == 2
    # Call 1 starts after delay 0 (2 s plus a jitter below 1 s); call 2 would
    # start after another 4 s or more, which is past the 6 s window.
    assert 2.0 <= clock.now - FakeClock.START < 3.0
    assert len(of(log, "retry_backoff_started")) == 1
    assert len(of(log, "action_attempt_started")) == 1
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed["payload"]["transport_exhausted"] is True
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert [call.provider_call_id for call in attempt.provider_calls] == [c0, c1]


def test_a_delay_that_lands_exactly_on_the_window_end_is_refused(tmp_path, clock) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=10.0, retry_after_max_seconds=30.0))
    rig = run_rig(tmp_path, [_rate_limited(10), ok()], profile)
    _assert_ended_without_a_backoff(rig)


def test_a_delay_just_inside_the_window_is_admitted(tmp_path, clock) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=10.0, retry_after_max_seconds=30.0))
    rig = run_rig(tmp_path, [_rate_limited(9), ok()], profile)

    assert rig.error is None, repr(rig.error)
    assert clock.sleeps == [9.0]


def test_a_clock_that_lands_exactly_on_the_window_end_after_the_sleep_is_refused(tmp_path, clock) -> None:
    profile = make_profile(_v1(transport_max_retry_seconds=10.0))

    async def land_on_the_end(fake, seconds):
        fake.now = FakeClock.START + 10.0

    clock.on_sleep = land_on_the_end
    rig = run_rig(tmp_path, [refuse(503), ok()], profile)
    _assert_stopped_before_the_opening(rig)


# =====================================================================================
# Controls: green before and after
# =====================================================================================

UNKNOWN_PROGRESS = {
    "read_timeout": (read_timeout, False, "timeout", True),
    "stalled_503_body": (stalled_status, False, "timeout", True),
    "stalled_503_body_streamed": (stalled_status, True, "timeout", True),
    "dropped_stream": (dropped_stream, True, "transport", True),
    "connect_refused": (connect_refused, False, "transport", True),
    "error_frame": (error_frame, True, "provider_rejected", False),
}


@pytest.mark.parametrize("case", sorted(UNKNOWN_PROGRESS))
def test_v1_leaves_failures_of_unknown_progress_on_todays_path(tmp_path, case) -> None:
    factory, stream, condition, retried = UNKNOWN_PROGRESS[case]
    profile = make_profile(
        _v1(),
        stream=stream,
        max_action_attempts=2,
        retryable=("rate_limit", "provider_5xx", "timeout", "transport"),
    )
    rig = run_rig(tmp_path, [factory(), ok()], profile)

    log = rig.log
    failed = of(log, "provider_call_failed", "provider_call_outcome_unknown")[0]
    assert failed["payload"]["failure_condition"] == condition
    assert not failed["payload"].get("http_refusal")
    for entry in of(log, "action_attempt_failed", "retry_backoff_started"):
        assert "transport_exhausted" not in entry["payload"]
        assert "transport_ordinal" not in entry["payload"]
    if retried:
        assert rig.error is None, repr(rig.error)
        assert rig.wire.requests == 2
        assert len(of(log, "action_attempt_started")) == 2
        assert rig.execution.attempts[1].retry_reason == condition
    else:
        assert_failed_with(rig, condition)
        assert rig.wire.requests == 1
        assert len(of(log, "action_attempt_started")) == 1


@pytest.mark.parametrize(
    ("declared", "step", "condition"),
    [(("rate_limit",), refuse(503), "provider_5xx"), (("provider_5xx",), refuse(429), "rate_limit")],
    ids=["503_undeclared", "429_undeclared"],
)
def test_v1_does_not_resend_a_condition_the_profile_did_not_declare(
    tmp_path, declared, step, condition
) -> None:
    rig = run_rig(tmp_path, [step, ok()], make_profile(_v1(), retryable=declared, max_action_attempts=3))

    assert_failed_with(rig, condition)
    log = rig.log
    assert rig.wire.requests == 1
    assert of(log, "retry_backoff_started") == []
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert "transport_exhausted" not in failed["payload"]


def test_v1_does_not_resend_a_refusal_whose_body_reports_usage(tmp_path) -> None:
    rig = run_rig(
        tmp_path,
        [refuse(503, usage_at_top=True), ok()],
        make_profile(_v1(), max_action_attempts=2),
    )

    assert rig.error is None, repr(rig.error)
    log = rig.log
    assert rig.wire.requests == 2
    assert len(of(log, "action_attempt_started")) == 2
    (failed,) = exactly(of(log, "provider_call_failed"), 1)
    assert not failed["payload"].get("http_refusal")
    assert failed["payload"]["cost_usd"] == 0.0
    assert "input_tokens" not in failed["payload"]
    assert rig.executor.total_cost_usd == pytest.approx(OK_COST)
    first, second = exactly(rig.execution.attempts, 2)
    assert first.provider_calls[0].cost_usd == 0.0
    assert first.provider_calls[0].status == "failed"
    assert second.retry_reason == "provider_5xx"


@pytest.mark.parametrize("case", ["length", "empty_response"])
def test_v1_semantic_retries_are_still_attempts_under_max_action_attempts(tmp_path, case) -> None:
    first = ok(content=TRUNCATED, finish_reason="length") if case == "length" else ok(content="")
    rig = run_rig(tmp_path, [first, ok()], make_profile(_v1(), max_action_attempts=2))

    assert rig.error is None, repr(rig.error)
    assert rig.wire.requests == 2
    log = rig.log
    assert len(of(log, "action_attempt_started")) == 2
    assert rig.execution.attempts[1].retry_reason == case
    assert [len(a.provider_calls) for a in rig.execution.attempts] == [1, 1]
    assert port_backoffs(log) == []


def test_v1_semantic_retries_stop_at_max_action_attempts(tmp_path) -> None:
    steps = [ok(content=TRUNCATED, finish_reason="length")] * 3
    rig = run_rig(tmp_path, steps, make_profile(_v1(), max_action_attempts=2))

    assert_failed_with(rig, "length")
    assert rig.wire.requests == 2
    assert len(of(rig.log, "action_attempt_started")) == 2


def test_a_success_followed_by_a_404_is_still_provider_rejected_after_route_proven(tmp_path) -> None:
    profile = make_profile(
        _v1(),
        max_action_attempts=3,
        retryable=("length", POST_ADMISSION_REJECTION),
    )
    rig = run_rig(
        tmp_path,
        [ok(content=TRUNCATED, finish_reason="length"), refuse(404), ok()],
        profile,
    )

    assert rig.error is None, repr(rig.error)
    log = rig.log
    conditions = [e["payload"]["failure_condition"] for e in of(log, "action_attempt_failed")]
    assert conditions == ["length", POST_ADMISSION_REJECTION]
    assert rig.wire.requests == 3


def test_a_recovered_503_then_a_terminal_402_is_retryable_infrastructure_with_account_fault(
    tmp_path, monkeypatch
) -> None:
    from aeread.shared_runner.task.evaluation import finalize_family_failure
    from tests.test_shared_runner_research import _score

    run = run_cell(tmp_path, monkeypatch, [refuse(503), refuse(402), ok()])

    assert run.failure is not None and run.failure.condition == "account_fault", repr(run.error)
    receipt = finalize_family_failure(
        setup=run.setup,
        cell_id=run.setup.plan.cells[0].cell_id,
        evidence_root=run.root,
        error=run.error,
        leaf_builder=lambda family_case: _score(run.setup.plan).leaf,
    )
    assert receipt.failure.failure_class == "retryable_infrastructure"
    assert receipt.failure.condition == "account_fault"


# =====================================================================================
# Integration: R1's and R4's evidence, checked as the downstream consumers read it
# =====================================================================================


def _release_evidence_lock(error) -> None:
    """A failed ``execute_plan_cell`` leaves its store unclosed, held by the
    traceback; drop the traceback chain so the store's finalizer releases it."""

    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        error.__traceback__ = None
        error = error.__cause__ or error.__context__
    gc.collect()


def _install_scorer(setup) -> None:
    """Give the single-offer smoke family a kernel-shaped scorer.

    The smoke plugin's own scorer is not a ``FamilyScorer``, so a completed cell
    could not be finalized. This one scores every completed cell as passed; the
    scoring is irrelevant here, the evidence plumbing is what is under test.
    """

    from aeread.shared_runner import FamilyScoreSet
    from tests.test_shared_runner_research import _score

    plugin = setup.registry.resolve_manifest(setup.plan.families[0])

    def build_scorer(case):
        def score(scoring_input, *, evidence_refs=()):
            primary = dataclasses.replace(
                _score(setup.plan), evidence_refs=tuple(evidence_refs)
            )
            return FamilyScoreSet(
                primary_leaf_id=primary.leaf.leaf_id,
                scores=(primary,),
                admission_leaf_ids=(primary.leaf.leaf_id,),
            )

        return score

    plugin.build_scorer = build_scorer


def _reopen_sealed(attempt_dir, receipt) -> None:
    """Audit and resume sealed evidence; both must accept a multi-call attempt."""

    audited = EvidenceStore.audit_existing(attempt_dir)
    assert audited.verify_seal() == receipt.evidence
    audited.close()
    resumed = EvidenceStore(
        attempt_dir,
        run_plan_id=receipt.run_plan_id,
        cell_id=receipt.cell_id,
        episode_id=receipt.episode_id,
        episode_attempt_id=receipt.episode_attempt_id,
        resume=True,
    )
    resumed.close()


def _publish_and_replay(tmp_path, run, receipt):
    """Publish the trajectory grain and verify the bundle provider-free."""

    from aeread.shared_runner.run.publication import seal_publication_manifest
    from aeread.shared_runner.run.publish_trajectories import GRAIN, publish_trajectory_grain
    from aeread.shared_runner.run.replay_verification import verify_bundle_replay

    bundle = tmp_path / "bundle"
    (bundle / "reports").mkdir(parents=True)
    (bundle / "reports" / "summary.json").write_text(
        json.dumps({"receipts": [receipt.receipt_sha256]})
    )
    seal_publication_manifest(
        bundle,
        publication_id="transport_resend_fixture_v1",
        privacy_boundary={"included": "receipt digests", "excluded": "raw run evidence"},
    )
    publish_trajectory_grain(bundle, [run.attempt_dir])
    rows = [json.loads(line) for line in (bundle / GRAIN).read_text().splitlines()]
    report = verify_bundle_replay(bundle, run.root, setup_for=lambda _receipt: run.setup)
    return rows, report


def test_a_recovered_cell_reads_correctly_downstream(tmp_path, monkeypatch) -> None:
    from aeread.shared_runner import project_loss_analysis_tables
    from aeread.shared_runner.task.evaluation import (
        audit_family_receipt,
        finalize_family_execution,
        replay_family_receipt,
    )
    from aeread.shared_runner.task.spend import attempt_spend

    run = run_cell(tmp_path, monkeypatch, [refuse(503), ok()])
    assert run.error is None, repr(run.error)
    execution = run.execution
    c0, c1 = exactly(started_ids(run.log), 2)

    # Spend totals: only the answered call costs; both calls are counted.
    spend = attempt_spend(execution.evidence)
    assert spend.provider_call_count == 2
    assert spend.cost_usd == pytest.approx(OK_COST)
    assert spend.cost_accounting == "exact"
    assert execution.total_cost_usd == pytest.approx(OK_COST)

    # Ordered attempt records.
    (action,) = exactly(execution.action_executions, 1)
    (attempt,) = exactly(action.attempts, 1)
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [
        (c0, "failed"),
        (c1, "succeeded"),
    ]
    assert attempt.canonical_response.provider_call_ids == (c1,)

    # Finalize (which seals), then audit, resume and replay without a provider.
    _install_scorer(run.setup)
    receipt = finalize_family_execution(setup=run.setup, execution=execution)
    assert receipt.status == "ok" and receipt.inclusion_status == "included"
    execution.evidence.close()
    _reopen_sealed(run.attempt_dir, receipt)
    replayed = replay_family_receipt(setup=run.setup, receipt=receipt, evidence_root=run.root)
    assert replayed == receipt
    audited = audit_family_receipt(
        setup=run.setup, receipt_path=run.attempt_dir / "evaluation_receipt.json"
    )
    assert audited["receipt_sha256"] == receipt.receipt_sha256

    # Research provider-call pairing.
    sealed = EvidenceStore.audit_existing(run.attempt_dir)
    tables = project_loss_analysis_tables(
        run.setup.plan, (receipt,), {receipt.episode_attempt_id: sealed}
    )
    sealed.close()
    assert [(call.call_id, call.status) for call in tables.model_calls] == [
        (c0, "failed"),
        (c1, "succeeded"),
    ]
    assert tables.model_calls[0].exception_type == "provider_5xx"
    assert tables.tasks[0].call_count == 2

    # Publication call records and verify-replay.
    rows, report = _publish_and_replay(tmp_path, run, receipt)
    (published_attempt,) = exactly(rows[0]["attempts"], 1)
    assert [(c["provider_call_id"], c["status"]) for c in published_attempt["provider_calls"]] == [
        (c0, "failed"),
        (c1, "succeeded"),
    ]
    assert len({c["request_sha256"] for c in published_attempt["provider_calls"]}) == 1
    assert report["verified"] is True, report


def test_an_exhausted_cell_finalizes_publishes_and_replays_provider_free(tmp_path, monkeypatch) -> None:
    from aeread.shared_runner import project_loss_analysis_tables
    from aeread.shared_runner.task.evaluation import audit_family_receipt, finalize_family_failure
    from aeread.shared_runner.task.spend import attempt_spend
    from tests.test_shared_runner_research import _score

    run = run_cell(
        tmp_path, monkeypatch, [refuse(503)] * 3 + [ok()], config=_v1(transport_max_calls=3)
    )
    assert run.failure is not None and run.failure.condition == "provider_5xx", repr(run.error)
    assert run.wire.requests == 3
    assert len(of(run.log, "action_attempt_started")) == 1
    ids = exactly(started_ids(run.log), 3)
    assert len(set(ids)) == 3
    _release_evidence_lock(run.error)

    # Spend: three refused calls, none billed, all settled.
    spend = attempt_spend(run.attempt_dir)
    assert spend.provider_call_count == 3
    assert spend.cost_usd == 0.0
    assert spend.cost_accounting == "exact"

    # Finalize: the failure receipt classes the cell by the conditions it saw.
    plan = run.setup.plan
    receipt = finalize_family_failure(
        setup=run.setup,
        cell_id=plan.cells[0].cell_id,
        evidence_root=run.root,
        error=run.error,
        leaf_builder=lambda family_case: _score(plan).leaf,
    )
    assert receipt.failure.failure_class == "retryable_infrastructure"
    assert receipt.failure.condition == "provider_5xx"

    # Seal, audit and resume; research pairing; provider-free replay.
    _reopen_sealed(run.attempt_dir, receipt)
    sealed = EvidenceStore.audit_existing(run.attempt_dir)
    tables = project_loss_analysis_tables(plan, (receipt,), {receipt.episode_attempt_id: sealed})
    sealed.close()
    assert [call.call_id for call in tables.model_calls] == ids
    assert {call.status for call in tables.model_calls} == {"failed"}
    audited = audit_family_receipt(
        setup=run.setup, receipt_path=run.attempt_dir / "evaluation_receipt.json"
    )
    assert audited["receipt_sha256"] == receipt.receipt_sha256

    # Publication call records and verify-replay.
    rows, report = _publish_and_replay(tmp_path, run, receipt)
    (published_attempt,) = exactly(rows[0]["attempts"], 1)
    assert [c["provider_call_id"] for c in published_attempt["provider_calls"]] == ids
    assert {c["status"] for c in published_attempt["provider_calls"]} == {"failed"}
    assert report["verified"] is True, report


# =====================================================================================
# The v0 golden control
# =====================================================================================

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "transport_resend"
REGENERATE = "AEREAD_REGENERATE_TRANSPORT_GOLDENS"


def _canon(value):
    """Deterministic JSON of dataclasses, mappings and sequences."""

    def convert(item):
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            return {f.name: convert(getattr(item, f.name)) for f in dataclasses.fields(item)}
        if isinstance(item, dict) or hasattr(item, "items"):
            return {str(k): convert(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(v) for v in item]
        return item

    return (json.dumps(convert(value), sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


class Scripted:
    """A provider that replays fixed outcomes; exceptions are raised."""

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)

    async def complete(self, request):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome(request)


def _scripted_503():
    # The classifier marks a status refusal; on main the attribute is inert and
    # a v0 profile must neither act on it nor write it.
    failure = ProviderFailure("provider_5xx", "service unavailable", retryable=True, status_code=503)
    failure.http_refusal = True
    return failure


def _scripted_ok(request):
    return ProviderResult(
        response_id="gen_golden_fixture",
        requested_model=request.model,
        resolved_model=CANONICAL_MODEL,
        output_text='{"offer":7}',
        finish_reason="stop",
        input_tokens=123,
        cached_input_tokens=7,
        output_tokens=45,
        cost_usd=OK_COST,
        raw_response={"id": "gen_golden_fixture", "output_text": '{"offer":7}'},
    )


GOLDEN_SCRIPTS = {
    "r1_refusal_then_success": lambda: [_scripted_503(), _scripted_ok],
    "r4_three_refusals": lambda: [_scripted_503(), _scripted_503(), _scripted_503()],
    "r9_refusal_then_first_404": lambda: [
        _scripted_503(),
        ProviderFailure("provider_rejected", "not found", retryable=False, status_code=404),
    ],
    "cancel_during_provider_call": lambda: [asyncio.CancelledError()],
}


def _run_golden(tmp_path, name):
    profile = make_profile(
        V0_BACKOFF, max_action_attempts=3, retryable=("rate_limit", "provider_5xx", POST_ADMISSION_REJECTION)
    )
    root = tmp_path / name
    evidence = EvidenceStore(
        root,
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        clock=lambda: "2026-10-04T00:00:00Z",
    )
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=(profile,),
        prompt_sources={PROMPT_ID: PROMPT},
        providers={"openrouter": Scripted(GOLDEN_SCRIPTS[name]())},
        pricing={MODEL: PRICING},
        harnesses=default_harnesses(),
    )
    decision = _decision()
    error = None
    try:
        asyncio.run(executor(decision))
    except BaseException as caught:  # noqa: BLE001
        error = caught
    execution = {
        "error": None if error is None else [type(error).__name__, str(error)],
        "total_cost_usd": executor.total_cost_usd,
        "execution": executor.execution_for(decision.logical_action_id),
    }
    events = (root / "events.jsonl").read_bytes()
    evidence.close()
    return events, _canon(execution)


@pytest.mark.parametrize("name", sorted(GOLDEN_SCRIPTS))
def test_v0_goldens_are_byte_identical(tmp_path, name) -> None:
    """Events and complete execution records of a v0 profile equal main's bytes.

    Regenerate (never in CI): see the module docstring.
    """

    events, execution = _run_golden(tmp_path, name)
    events_path = GOLDEN_DIR / f"v0_{name}.events.jsonl"
    execution_path = GOLDEN_DIR / f"v0_{name}.execution.json"
    if os.environ.get(REGENERATE) == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        events_path.write_bytes(events)
        execution_path.write_bytes(execution)
        pytest.skip("goldens regenerated; run again without the flag to compare")
    assert events_path.is_file() and execution_path.is_file(), "golden files are missing"
    assert events == events_path.read_bytes()
    assert execution == execution_path.read_bytes()
