"""S4b: first-progress and idle deadlines for streamed provider calls (#226 items 1 and 3).

A profile that declares ``transport_v1`` and ``provider_stream`` may add
``transport_first_progress_seconds`` and ``transport_idle_seconds`` to
``harness.config``. The streamed client then bounds the wait for the first
chunk that carries output and the gap between such chunks, and an expiry is a
retryable ``timeout`` with ``stream_deadline`` set.

The streamed golden control
``test_streamed_transport_v1_goldens_are_byte_identical`` compares the events
and the complete execution record of a streamed ``transport_v1`` profile
without the knobs against files in ``tests/fixtures/stream_deadlines/``. They
were generated on the #248 head 77254689 before any S4b change, once per
openai major version, since the SDK's ``model_dump`` of the same stream
differs between them (3.x adds nullable usage fields):

    AEREAD_REGENERATE_STREAM_GOLDENS=1 PYTHONPATH=src:. \\
        python -m pytest tests/test_stream_deadlines.py -k streamed_transport_v1_goldens -p no:cacheprovider
"""

from __future__ import annotations

import os
from pathlib import Path

import openai
import pytest

from aeread.shared_runner.model_call.harness import AttemptExecutor, default_harnesses
from aeread.shared_runner.task.execution import EvidenceStore
from tests.test_route_health import (  # noqa: F401  (autouse fixtures)
    _instant_asyncio_sleep,
    clock,
    run_async,
)
from tests.test_shared_runner_execution import _decision
from tests.test_transport_resend import (
    MODEL,
    PRICING,
    PROMPT,
    PROMPT_ID,
    Wire,
    _canon,
    build_client,
    make_profile,
    ok,
    refuse,
)


# =====================================================================================
# The streamed golden control
# =====================================================================================

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "stream_deadlines"
REGENERATE = "AEREAD_REGENERATE_STREAM_GOLDENS"
SDK_MAJOR = f"openai{openai.__version__.split('.')[0]}"

GOLDEN_STEPS = {
    "recovered_refusal": lambda: [refuse(503), ok()],
    "streamed_success": lambda: [ok()],
}


def _run_streamed_golden(tmp_path, steps):
    root = tmp_path / "golden"
    evidence = EvidenceStore(
        root,
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        clock=lambda: "2026-10-08T00:00:00Z",
    )
    wire = Wire(steps)
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=(make_profile(stream=True),),
        prompt_sources={PROMPT_ID: PROMPT},
        providers={"openrouter": build_client(wire)},
        pricing={MODEL: PRICING},
        harnesses=default_harnesses(),
    )
    decision = _decision()
    error = None
    try:
        run_async(executor(decision))
    except BaseException as caught:  # noqa: BLE001
        error = caught
    execution = {
        "error": None if error is None else [type(error).__name__, str(error)],
        "total_cost_usd": executor.total_cost_usd,
        "execution": executor.execution_for(decision.logical_action_id),
    }
    events = (root / "events.jsonl").read_bytes()
    evidence.close()
    return events, _canon(execution), wire


@pytest.mark.parametrize("name", sorted(GOLDEN_STEPS))
def test_streamed_transport_v1_goldens_are_byte_identical(tmp_path, clock, name) -> None:
    """A streamed transport_v1 profile without the knobs is untouched by S4b."""

    events, execution, wire = _run_streamed_golden(tmp_path, GOLDEN_STEPS[name]())
    assert wire.requests == len(GOLDEN_STEPS[name]())
    assert b'"stream": true' in wire.bodies[0] or b'"stream":true' in wire.bodies[0]
    stem = f"transport_v1_streamed_{name}.{SDK_MAJOR}"
    events_path = GOLDEN_DIR / f"{stem}.events.jsonl"
    execution_path = GOLDEN_DIR / f"{stem}.execution.json"
    if os.environ.get(REGENERATE) == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        events_path.write_bytes(events)
        execution_path.write_bytes(execution)
        pytest.skip("goldens regenerated; run again without the flag to compare")
    assert events_path.is_file() and execution_path.is_file(), f"golden files are missing: {stem}"
    assert events == events_path.read_bytes()
    assert execution == execution_path.read_bytes()


# =====================================================================================
# Red-first tests for the stream deadlines (spec v0.6, "Tests")
#
# How these tests are written
# - No new name of the implementation is imported or called. The knobs are declared
#   in ``harness.config``; the current head ignores them, so a red test fails on a
#   behavioural assertion (a success where a failure is expected, a watchdog that
#   fires where a deadline should), never on a missing attribute. New attributes
#   are read with ``getattr(..., None)``.
# - Deterministic tests inject the clock with ``monkeypatch.setattr(execution_module,
#   "_stream_monotonic", fake.monotonic, raising=False)`` and script a fake SDK
#   (``FakeCompletions`` / ``FakeStream``) whose steps move the fake clock. A stall is a
#   step that never completes, with a declared budget of 0.05 s of real time, so the
#   outcome is fixed and only its latency varies. Every event-loop run sits under a
#   watchdog that fails the test (never hangs it).
# - Smoke tests use the real SDK over a mock transport, 1 s deadlines and a 20 s
#   watchdog.
# =====================================================================================

import asyncio  # noqa: E402
import copy  # noqa: E402
import dataclasses  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import aeread.shared_runner.model_call.harness as harness_module  # noqa: E402
import aeread.shared_runner.task.execution as execution_module  # noqa: E402
from aeread.shared_runner.model_call.harness import KernelModelPort, MinimalChatHarness  # noqa: E402
from aeread.shared_runner.task.execution import (  # noqa: E402
    EvidenceIntegrityError,
    OpenRouterChatClient,
    ProviderFailure,
    declared_transport_policy,
)
from aeread.shared_runner.task.spend import attempt_spend  # noqa: E402
from tests.test_route_health import (  # noqa: E402
    ROUTE_MODULE,
    _new_registry,
    _r1,
    reports,  # noqa: F401  (fixture, used by S7)
    route_profile,
    run_route_cell,
)
from tests.test_transport_resend import (  # noqa: E402
    BASE_URL,
    DECLARED,
    V1,
    Rig,
    _http_lib,
    _install_scorer,
    _raw_completion,
    _reopen_sealed,
    _sse,
    _stream_frames,
    exactly,
    of,
    port_backoffs,
    read_log,
    run_cell,
    started_ids,
)

# The real sleep, captured before the autouse fixture replaces ``asyncio.sleep``.
_REAL_SLEEP = asyncio.sleep

# Fake time at which a step starts with 0.04 s of a 10 s budget left: the stall tests
# create the stream there, so the steps that must complete have the whole budget and
# only the step that never completes waits out the 0.04 s.
NEAR = 9.96
WATCHDOG = 5.0
SMOKE_WATCHDOG = 20.0
STALL = 6.0  # how long a smoke server holds back, far beyond the 1 s deadlines
NO_DEADLINE = "no stream deadline fired"

FIRST = "transport_first_progress_seconds"
IDLE = "transport_idle_seconds"
TERMINALS = ("provider_call_succeeded", "provider_call_failed", "provider_call_outcome_unknown")


# --- Frames -----------------------------------------------------------------------------

_BASE = {
    "id": "gen_transport_fixture",
    "model": MODEL,
    "object": "chat.completion.chunk",
    "provider": "DeepInfra",
}
FR_CONTENT, FR_FINISH, FR_FINAL = _stream_frames(_raw_completion('{"offer":7}'))
USAGE_3_2 = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "cost": 0.7}


def delta_frame(delta, finish=None):
    return {**_BASE, "choices": [{"index": 0, "finish_reason": finish, "delta": delta}]}


def usage_frame(usage=USAGE_3_2):
    return {**_BASE, "choices": [], "usage": dict(usage)}


def piece(text):
    return delta_frame({"role": "assistant", "content": text})


PROGRESS = {
    "content": piece('{"offer":7}'),
    "reasoning": delta_frame({"reasoning": "think"}),
    "reasoning_details": delta_frame(
        {"reasoning_details": [{"type": "reasoning.text", "text": "a", "index": 0}]}
    ),
    "tool_calls": delta_frame(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "act", "arguments": "{}"},
                }
            ]
        }
    ),
    "finish_reason": delta_frame({}, finish="stop"),
}
NON_PROGRESS = {
    "role_only": delta_frame({"role": "assistant"}),
    "usage_only": usage_frame(),
    "empty_delta": delta_frame({}),
    "empty_content": delta_frame({"role": "assistant", "content": ""}),
    "empty_reasoning": delta_frame({"reasoning": ""}),
    "empty_reasoning_details": delta_frame({"reasoning_details": []}),
    "empty_tool_calls": delta_frame({"tool_calls": []}),
}


# --- The scripted fake SDK ---------------------------------------------------------------


class StreamClock:
    """The stream client's monotonic clock; only the scripted steps move it."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def sclock(monkeypatch) -> StreamClock:
    fake = StreamClock()
    # raising=False: the current head has no such name; the tests then fail on behaviour.
    monkeypatch.setattr(execution_module, "_stream_monotonic", fake.monotonic, raising=False)
    return fake


class Handle:
    """Lets a scripted step find the task it must cancel."""

    task = None


def cancel_outer(handle: Handle):
    """Request the outer task's cancellation in the same loop iteration."""

    return lambda: asyncio.get_running_loop().call_soon(handle.task.cancel)


class _Escape(BaseException):
    """Ends a step the way no ``Exception`` handler can catch."""


class _Dumped:
    def __init__(self, body) -> None:
        self._body = body

    def model_dump(self, mode="json"):
        return copy.deepcopy(self._body)


def chunk(at, body, then=None):
    return ("chunk", at, body, then)


def end(at):
    return ("end", at)


def hang():
    return ("hang",)


def rest(at, *, content=True):
    """The frames of a normal finish, all delivered at fake time ``at``."""

    frames = [chunk(at, FR_CONTENT)] if content else []
    return frames + [chunk(at, FR_FINISH), chunk(at, FR_FINAL), end(at)]


class FakeStream:
    """An SDK stream: ``__anext__`` follows a script, ``close`` counts calls."""

    def __init__(
        self,
        clock,
        script,
        *,
        unwind_error=None,
        unwind_block=False,
        close_error=None,
        close_block=False,
        close_cancel_error=None,
    ) -> None:
        self.clock = clock
        self.script = list(script)
        self.unwind_error = unwind_error
        self.unwind_block = unwind_block
        self.close_error = close_error
        self.close_block = close_block
        self.close_cancel_error = close_cancel_error
        self.delivered = 0  # chunks handed to the caller
        self.unwound = 0  # cancellations of a step
        self.closes = 0
        self.close_cancelled = 0
        self.unwinding = asyncio.Event()
        self.hanging = asyncio.Event()
        self.close_started = asyncio.Event()

    def __aiter__(self):
        return self

    async def _unwind(self) -> None:
        self.unwound += 1
        self.unwinding.set()
        if self.unwind_block:
            await asyncio.get_running_loop().create_future()
        if self.unwind_error is not None:
            raise self.unwind_error

    async def __anext__(self):
        step = self.script.pop(0) if self.script else ("end", self.clock.now)
        try:
            await _REAL_SLEEP(0)  # a real suspension point, like a network read
            if step[0] == "chunk":
                _, at, body, then = step
                self.clock.now = at
                self.delivered += 1
                if then is not None:
                    then()
                return _Dumped(body)
            if step[0] == "end":
                self.clock.now = step[1]
                raise StopAsyncIteration
            self.hanging.set()
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            await self._unwind()
            raise

    async def close(self) -> None:
        self.closes += 1
        self.close_started.set()
        if self.closes > 1:
            return  # a second close is a no-op in both SDKs
        if self.close_block:
            try:
                await asyncio.get_running_loop().create_future()
            except asyncio.CancelledError:
                self.close_cancelled += 1
                if self.close_cancel_error is not None:
                    raise self.close_cancel_error
                raise
        if self.close_error is not None:
            raise self.close_error


class FakeCompletions:
    """``chat.completions``: ``create`` follows one scripted step."""

    def __init__(self, clock, stream, *, create=("return", 0.0), then=None) -> None:
        self.clock = clock
        self.stream = stream
        self.create_step = create
        self.then = then
        self.calls: list[dict] = []
        self.create_cancelled = 0

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        step = self.create_step
        try:
            await _REAL_SLEEP(0)
            if step[0] == "return":
                self.clock.now = step[1]
                if self.then is not None:
                    self.then()
                return self.stream
            if step[0] == "race":
                # The step ends with ``step[1]`` through a callback queued BEFORE the
                # outer cancellation, so both land in the same loop iteration.
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                loop.call_soon(future.set_exception, step[1])
                if self.then is not None:
                    self.then()
                await future
            await asyncio.get_running_loop().create_future()  # "hang"
        except asyncio.CancelledError:
            self.create_cancelled += 1
            raise


def sdk_provider(completions) -> OpenRouterChatClient:
    return OpenRouterChatClient(
        sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        base_url=BASE_URL,
    )


# --- Profiles, ports and the watchdog ------------------------------------------------------


def knobs(first=None, idle=None):
    declared = {}
    if first is not None:
        declared[FIRST] = first
    if idle is not None:
        declared[IDLE] = idle
    return declared


def stream_profile(first=None, idle=None, *, timeout_seconds=600.0, **profile_kwargs):
    """A streamed transport_v1 profile; the attempt timeout leaves room for any knob used here."""

    return make_profile(
        {**V1, **knobs(first, idle)}, stream=True, timeout_seconds=timeout_seconds, **profile_kwargs
    )


def drive(factory, *, handle=None, trigger=None, on_trigger=None, watchdog=WATCHDOG, what=NO_DEADLINE):
    """Run ``factory()`` as a task under a watchdog; return ``(value, error)``.

    With ``trigger`` (an event) the task is left running until the event is set,
    then ``on_trigger(task)`` runs (default: cancel it). A task that ends before
    the trigger, or one still running when the watchdog expires, fails the test.
    """

    on_trigger = on_trigger or (lambda task: task.cancel())

    async def main():
        task = asyncio.ensure_future(factory())
        if handle is not None:
            handle.task = task
        if trigger is not None:
            waiter = asyncio.ensure_future(trigger.wait())
            done, _ = await asyncio.wait(
                {task, waiter}, timeout=watchdog, return_when=asyncio.FIRST_COMPLETED
            )
            if waiter not in done:
                waiter.cancel()
                status = "untriggered" if task in done else "watchdog"
            else:
                on_trigger(task)
                done, _ = await asyncio.wait({task}, timeout=watchdog)
                status = "done" if task in done else "watchdog"
        else:
            done, _ = await asyncio.wait({task}, timeout=watchdog)
            status = "done" if task in done else "watchdog"
        if task not in done:
            task.cancel()
            await asyncio.wait({task}, timeout=1.0)
            if task.done() and not task.cancelled():
                task.exception()  # retrieved, so the loop does not log it
            return status, None, None
        if task.cancelled():
            return status, None, asyncio.CancelledError()
        error = task.exception()
        return status, (None if error is not None else task.result()), error

    status, value, error = asyncio.run(main())
    if status == "watchdog":
        pytest.fail(f"{what} (the watchdog expired after {watchdog} s)")
    if status == "untriggered":
        pytest.fail(f"{what} (the call ended before reaching the awaited state: {error!r} / {value!r})")
    return value, error


def new_store(tmp_path, name="evidence") -> EvidenceStore:
    return EvidenceStore(
        tmp_path / name,
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        clock=lambda: "2026-10-08T00:00:00Z",
    )


def new_port(evidence, provider, profile) -> KernelModelPort:
    return KernelModelPort(
        evidence=evidence,
        provider=provider,
        pricing=PRICING,
        profile=profile,
        instructions=PROMPT,
        action_attempt_id="action_attempt_fixture",
    )


def run_port(
    tmp_path,
    sclock,
    profile,
    script,
    *,
    create=("return", 0.0),
    create_then=None,
    handle=None,
    trigger=None,
    on_trigger=None,
    what=NO_DEADLINE,
    **stream_kwargs,
):
    """One ``KernelModelPort.complete`` over the scripted fake SDK."""

    stream = FakeStream(sclock, script, **stream_kwargs)
    completions = FakeCompletions(sclock, stream, create=create, then=create_then)
    evidence = new_store(tmp_path)
    port = new_port(evidence, sdk_provider(completions), profile)
    try:
        value, error = drive(
            lambda: port.complete(messages=(), response_mode="text"),
            handle=handle,
            trigger=None if trigger is None else getattr(stream, trigger),
            on_trigger=on_trigger,
            what=what,
        )
    finally:
        evidence.close()
    return SimpleNamespace(
        value=value,
        error=error,
        stream=stream,
        completions=completions,
        port=port,
        log=read_log(tmp_path / "evidence") if (tmp_path / "evidence" / "events.jsonl").exists() else [],
    )


def expect_success(ran) -> None:
    assert ran.error is None, f"expected the call to succeed, got {ran.error!r}"
    assert json.loads(ran.value.text) == {"offer": 7}


def expect_deadline(ran, kind) -> ProviderFailure:
    failure = ran.error
    assert isinstance(failure, ProviderFailure), (
        f"expected a {kind!r} stream-deadline failure; the call ended with "
        f"{failure!r} (value {ran.value!r})"
    )
    assert failure.condition == "timeout" and failure.retryable is True, repr(failure)
    assert getattr(failure, "stream_deadline", None) == kind, (
        f"stream_deadline is {getattr(failure, 'stream_deadline', None)!r}, expected {kind!r}"
    )
    return failure


def expect_cancelled(ran) -> None:
    assert isinstance(ran.error, asyncio.CancelledError), (
        f"expected the outer cancellation to propagate; the call ended with "
        f"{ran.error!r} (value {ran.value!r})"
    )


# =====================================================================================
# U1  What counts as progress
# =====================================================================================


@pytest.mark.parametrize("kind", sorted(PROGRESS))
def test_u1_each_progress_field_alone_counts_as_progress(tmp_path, sclock, kind) -> None:
    """First-progress 10, idle 100: the chunk under test at t=1, the rest at t=50.

    If the chunk counts as progress the idle deadline (101) holds at t=50.
    """

    script = [chunk(1.0, PROGRESS[kind])] + rest(50.0, content=kind != "content")
    expect_success(run_port(tmp_path, sclock, stream_profile(10, 100), script))


@pytest.mark.parametrize("kind", sorted(NON_PROGRESS))
def test_u1_a_chunk_without_output_is_not_progress(tmp_path, sclock, kind) -> None:
    """The same shape: if the chunk is not progress, t=50 is past the 10 s first-progress deadline."""

    script = [chunk(1.0, NON_PROGRESS[kind])] + rest(50.0)
    expect_deadline(run_port(tmp_path, sclock, stream_profile(10, 100), script), "first_progress")


# =====================================================================================
# U2  The first-progress budget is never restarted
# =====================================================================================


def test_u2_headers_and_non_progress_chunks_do_not_restart_the_first_progress_budget(
    tmp_path, sclock
) -> None:
    # Headers at 60% of 10 s, two non-progress chunks, the first progress chunk at 110%.
    script = [
        chunk(7.0, NON_PROGRESS["role_only"]),
        chunk(8.0, NON_PROGRESS["empty_delta"]),
        *rest(11.0),
    ]
    ran = run_port(tmp_path, sclock, stream_profile(10), script, create=("return", 6.0))
    expect_deadline(ran, "first_progress")


def test_u2_progress_inside_the_budget_after_the_same_prefix_succeeds(tmp_path, sclock) -> None:
    script = [
        chunk(7.0, NON_PROGRESS["role_only"]),
        chunk(8.0, NON_PROGRESS["empty_delta"]),
        *rest(9.5),
    ]
    expect_success(
        run_port(tmp_path, sclock, stream_profile(10), script, create=("return", 6.0))
    )


# =====================================================================================
# U3  idle-only, U4 first-only
# =====================================================================================


def test_u3_idle_only_has_no_stream_deadline_before_the_first_progress_chunk(
    tmp_path, sclock
) -> None:
    script = [chunk(500.0, NON_PROGRESS["role_only"]), *rest(505.0)]
    expect_success(run_port(tmp_path, sclock, stream_profile(idle=10), script, create=("return", 400.0)))


def test_u3_idle_only_enforces_the_idle_deadline_after_the_first_progress_chunk(
    tmp_path, sclock
) -> None:
    script = [
        chunk(500.0, NON_PROGRESS["role_only"]),
        chunk(505.0, FR_CONTENT),  # progress: the idle deadline is now 515
        chunk(516.0, FR_FINISH),
        chunk(516.0, FR_FINAL),
        end(516.0),
    ]
    ran = run_port(tmp_path, sclock, stream_profile(idle=10), script, create=("return", 400.0))
    expect_deadline(ran, "idle")
    # The wait before the first progress chunk was not bounded: the late chunk was reached.
    assert ran.stream.delivered == 3


def test_u3_idle_only_a_stalled_stream_expires_as_idle(tmp_path, sclock) -> None:
    ran = run_port(tmp_path, sclock, stream_profile(idle=0.05), [chunk(0.0, FR_CONTENT), hang()])
    expect_deadline(ran, "idle")
    assert ran.stream.unwound == 1


def test_u4_first_only_leaves_the_steps_after_first_progress_unbounded(tmp_path, sclock) -> None:
    script = [chunk(9.0, FR_CONTENT), chunk(9000.0, FR_FINISH), chunk(9000.0, FR_FINAL), end(9000.0)]
    expect_success(run_port(tmp_path, sclock, stream_profile(first=10), script))


def test_u4_first_only_a_stalled_first_progress_wait_expires(tmp_path, sclock) -> None:
    ran = run_port(tmp_path, sclock, stream_profile(first=10), [hang()], create=("return", NEAR))
    expect_deadline(ran, "first_progress")
    assert ran.stream.unwound == 1


def test_u4_first_only_a_stalled_create_expires(tmp_path, sclock) -> None:
    """A create() that never returns: nothing to close, and the call still ends."""

    ran = run_port(tmp_path, sclock, stream_profile(first=0.05), [], create=("hang",))
    expect_deadline(ran, "first_progress")
    assert ran.completions.create_cancelled == 1 and ran.stream.closes == 0


# =====================================================================================
# U5  Boundary: a deadline is reached when now >= deadline
# =====================================================================================


@pytest.mark.parametrize(
    ("at", "expires"), [(9.999, False), (10.0, True)], ids=["just_before", "equal"]
)
def test_u5_first_progress_boundary(tmp_path, sclock, at, expires) -> None:
    ran = run_port(tmp_path, sclock, stream_profile(first=10), rest(at))
    if expires:
        expect_deadline(ran, "first_progress")
    else:
        expect_success(ran)


def test_u5_a_create_that_returns_at_the_deadline_expires_without_reading(tmp_path, sclock) -> None:
    """Headers that arrive exactly at the first-progress deadline: the stream is
    closed at once and no chunk read is started."""

    ran = run_port(tmp_path, sclock, stream_profile(first=10), rest(10.0), create=("return", 10.0))
    expect_deadline(ran, "first_progress")
    assert ran.stream.closes == 1
    assert ran.stream.delivered == 0 and ran.stream.unwound == 0


@pytest.mark.parametrize(
    ("at", "expires"), [(9.999, False), (10.0, True)], ids=["just_before", "equal"]
)
def test_u5_idle_boundary(tmp_path, sclock, at, expires) -> None:
    script = [chunk(0.0, FR_CONTENT), chunk(at, FR_FINISH), chunk(at, FR_FINAL), end(at)]
    ran = run_port(tmp_path, sclock, stream_profile(idle=10), script)
    if expires:
        expect_deadline(ran, "idle")
    else:
        expect_success(ran)


# =====================================================================================
# U6  A late chunk is not accepted; its usage is kept; the response is closed at once
# =====================================================================================


def _late_usage_chunk():
    return {**piece("x"), "usage": dict(USAGE_3_2)}


def test_u6_a_late_progress_chunk_expires_keeps_its_usage_and_closes_the_stream(
    tmp_path, sclock
) -> None:
    script = [chunk(11.0, _late_usage_chunk()), *rest(11.0, content=False)]
    ran = run_port(tmp_path, sclock, stream_profile(first=10), script)

    failure = expect_deadline(ran, "first_progress")
    assert failure.billing == "reported"
    assert (failure.input_tokens, failure.output_tokens, failure.cost_usd) == (3, 2, 0.7)
    assert ran.stream.closes == 1
    # The terminal the port wrote carries the phase and the reported tokens; the
    # cost stays unknown on every outcome_unknown terminal (spec section 4).
    (terminal,) = exactly(of(ran.log, *TERMINALS), 1)
    assert terminal["event_type"] == "provider_call_outcome_unknown"
    assert terminal["payload"]["failure_condition"] == "timeout"
    assert terminal["payload"].get("stream_deadline") == "first_progress"
    assert terminal["payload"]["cost_usd"] == "unknown"
    assert (terminal["payload"]["input_tokens"], terminal["payload"]["output_tokens"]) == (3, 2)
    # A deadline expiry is not an HTTP refusal: the call is not re-sent inside the attempt.
    assert len(of(ran.log, "provider_call_started")) == 1
    assert port_backoffs(ran.log) == []


# =====================================================================================
# U7a / U7b  A step that completes in the same loop iteration as an outer cancellation
# =====================================================================================


def _race(tmp_path, sclock, race):
    handle = Handle()
    cancel = cancel_outer(handle)
    script = [
        chunk(1.0, FR_CONTENT, then=cancel if race == "anext" else None),
        chunk(1.0, FR_FINISH),
        chunk(1.0, FR_FINAL),
        end(1.0),
    ]
    return run_port(
        tmp_path,
        sclock,
        stream_profile(first=100),
        script,
        create=("return", 1.0),
        create_then=cancel if race == "create" else None,
        handle=handle,
    )


@pytest.mark.parametrize("race", ["create", "anext"])
def test_u7a_a_completed_step_never_swallows_an_outer_cancellation(tmp_path, sclock, race) -> None:
    ran = _race(tmp_path, sclock, race)
    expect_cancelled(ran)


@pytest.mark.parametrize("race", ["create", "anext"])
def test_u7b_the_discarded_or_yielded_stream_is_closed_at_once(tmp_path, sclock, race) -> None:
    ran = _race(tmp_path, sclock, race)
    expect_cancelled(ran)
    assert ran.stream.closes == 1


# =====================================================================================
# U8, U9, U10  Cancellation and cleanup errors around an expiry
# =====================================================================================


def test_u8_an_outer_cancellation_while_the_expiry_unwinds_the_step_propagates(
    tmp_path, sclock
) -> None:
    ran = run_port(
        tmp_path,
        sclock,
        stream_profile(first=10),
        [hang()],
        create=("return", NEAR),
        trigger="unwinding",
        unwind_block=True,
    )
    expect_cancelled(ran)
    assert ran.log and not of(ran.log, "provider_call_failed")


def test_u9_a_cleanup_error_while_the_expiry_unwinds_the_step_is_suppressed(tmp_path, sclock) -> None:
    ran = run_port(
        tmp_path,
        sclock,
        stream_profile(first=10),
        [hang()],
        create=("return", NEAR),
        unwind_error=RuntimeError("SDK cleanup failed"),
    )
    expect_deadline(ran, "first_progress")
    assert ran.stream.unwound == 1


def test_u9_a_cleanup_error_while_an_outer_cancellation_unwinds_the_step_is_suppressed(
    tmp_path, sclock
) -> None:
    ran = run_port(
        tmp_path,
        sclock,
        stream_profile(first=50),
        [hang()],
        trigger="hanging",
        unwind_error=RuntimeError("SDK cleanup failed"),
    )
    expect_cancelled(ran)
    assert ran.stream.unwound == 1


def test_u10_an_explicit_close_that_raises_is_suppressed(tmp_path, sclock) -> None:
    script = [chunk(11.0, FR_CONTENT), *rest(11.0, content=False)]
    ran = run_port(
        tmp_path,
        sclock,
        stream_profile(first=10),
        script,
        close_error=RuntimeError("aclose failed"),
    )
    expect_deadline(ran, "first_progress")
    assert ran.stream.closes == 1


# =====================================================================================
# U11, U12, U15  The idle timer
# =====================================================================================


def test_u11_non_progress_chunks_inside_the_idle_window_do_not_reset_the_timer(
    tmp_path, sclock
) -> None:
    # Idle 10: progress at 0; non-progress at 9 and at 18. The window closed at 10.
    script = [
        chunk(0.0, FR_CONTENT),
        chunk(9.0, NON_PROGRESS["empty_delta"]),
        chunk(18.0, NON_PROGRESS["role_only"]),
        chunk(18.0, FR_FINISH),
        chunk(18.0, FR_FINAL),
        end(18.0),
    ]
    expect_deadline(run_port(tmp_path, sclock, stream_profile(idle=10), script), "idle")


@pytest.mark.parametrize(
    ("end_at", "expires"),
    [(11.999, False), (12.0, True), (12.5, True)],
    ids=["just_before", "equal", "after"],
)
def test_u12_a_stream_that_ends_after_the_idle_deadline_is_an_expiry(
    tmp_path, sclock, end_at, expires
) -> None:
    """The finish chunk (with usage) resets the idle timer at t=2, so the deadline is 12."""

    script = [
        chunk(0.0, FR_CONTENT),
        chunk(1.0, FR_FINISH),
        chunk(2.0, FR_FINAL),
        end(end_at),
    ]
    ran = run_port(tmp_path, sclock, stream_profile(idle=10), script)
    if expires:
        expect_deadline(ran, "idle")
        assert ran.value is None
    else:
        expect_success(ran)


def _fragments(kind):
    """Content at 0 and two fragments of ``kind`` at 9 and 18 (idle 10)."""

    if kind == "content":
        return [
            chunk(0.0, piece('{"of')),
            chunk(9.0, piece('fer":')),
            chunk(18.0, piece("7}")),
        ]
    first = PROGRESS[kind]
    return [chunk(0.0, FR_CONTENT), chunk(9.0, first), chunk(18.0, first)]


@pytest.mark.parametrize("kind", ["content", "reasoning", "reasoning_details", "tool_calls"])
def test_u15_intermediate_progress_keeps_the_stream_alive(tmp_path, sclock, kind) -> None:
    """Idle 10; progress at 0, 9 and 18; finish at 27; EOF at 28.

    On the current head (no deadlines) this passes: it guards the mutation that
    resets the idle timer only on the first and the finish chunks.
    """

    script = [*_fragments(kind), chunk(27.0, FR_FINAL), end(28.0)]
    expect_success(run_port(tmp_path, sclock, stream_profile(idle=10), script))


# =====================================================================================
# U13  The documented limit: usage seen before a cancellation during the close is lost
# =====================================================================================


def _late_script():
    return [chunk(11.0, _late_usage_chunk()), *rest(11.0, content=False)]


def test_u13_a_cancellation_during_the_explicit_close_propagates(tmp_path, sclock) -> None:
    ran = run_port(
        tmp_path,
        sclock,
        stream_profile(first=10),
        _late_script(),
        trigger="close_started",
        close_block=True,
        close_cancel_error=RuntimeError("transport aclose failed"),
    )
    expect_cancelled(ran)
    assert ran.stream.closes >= 1 and ran.stream.close_cancelled == 1


def test_u13_through_the_executor_the_call_is_interrupted_with_zero_measurements(
    tmp_path, sclock
) -> None:
    stream = FakeStream(
        sclock,
        _late_script(),
        close_block=True,
        close_cancel_error=RuntimeError("transport aclose failed"),
    )
    completions = FakeCompletions(sclock, stream)
    rig = Rig(
        tmp_path,
        [],
        stream_profile(first=10, max_action_attempts=1),
        wrap=lambda client: sdk_provider(completions),
    )
    _, error = drive(
        lambda: rig.executor(rig.decision), trigger=stream.close_started
    )
    assert isinstance(error, asyncio.CancelledError), repr(error)

    log = rig.log
    (terminal,) = exactly(of(log, *TERMINALS), 1)
    assert terminal["event_type"] == "provider_call_outcome_unknown"
    assert terminal["payload"]["failure_condition"] == "interrupted_during_provider_call"
    assert "input_tokens" not in terminal["payload"] and "output_tokens" not in terminal["payload"]
    (attempt,) = exactly(rig.execution.attempts, 1)
    (record,) = exactly(attempt.provider_calls, 1)
    assert record.status == "outcome_unknown"
    assert record.failure_condition == "interrupted_during_provider_call"
    assert (record.input_tokens, record.output_tokens, record.cost_usd) == (0, 0, 0.0)
    assert rig.executor.total_cost_usd == 0.0


# =====================================================================================
# U14a-c  An outer cancellation at the attempt boundary (the executor's wait)
# =====================================================================================


def spy_reports(monkeypatch, handle=None):
    """Every ``RouteHealth.report`` label; optionally cancel the outer task right after one."""

    route = importlib.import_module(ROUTE_MODULE)
    real = route.RouteHealth.report
    seen: list[str | None] = []

    def spy(self, *args, **kwargs):
        seen.append("success" if kwargs.get("success") else kwargs.get("condition"))
        result = real(self, *args, **kwargs)
        if handle is not None and handle.task is not None:
            asyncio.get_running_loop().call_soon(handle.task.cancel)
        return result

    monkeypatch.setattr(route.RouteHealth, "report", spy)
    return seen


class SuspendingHarness(MinimalChatHarness):
    """``minimal_chat`` that suspends after a failed model call, as a harness with
    cleanup or bookkeeping of its own would: a cancellation lands there, after the
    port wrote the failed call's terminal and before the executor records it."""

    async def act(self, request, ctx):
        try:
            return await super().act(request, ctx)
        except ProviderFailure:
            await asyncio.get_running_loop().create_future()


class ExecRig:
    """One logical action through ``AttemptExecutor`` under route_v1, one attempt."""

    def __init__(self, tmp_path, config, *, steps=(), completions=None, harness=None) -> None:
        self.profile = route_profile(config, max_action_attempts=1)
        self.wire = Wire(list(steps))
        provider = build_client(self.wire) if completions is None else sdk_provider(completions)
        self.root = tmp_path / "evidence"
        self.evidence = EvidenceStore(
            self.root,
            run_plan_id="runplan_fixture",
            cell_id="cell_fixture",
            episode_id="episode_fixture",
            episode_attempt_id="episode_attempt_fixture_0",
            clock=lambda: "2026-10-08T00:00:00Z",
        )
        self.executor = AttemptExecutor(
            evidence=self.evidence,
            profiles=(self.profile,),
            prompt_sources={PROMPT_ID: PROMPT},
            providers={"openrouter": provider},
            pricing={MODEL: PRICING},
            harnesses={"minimal_chat/1.0": harness or MinimalChatHarness()},
            route_health=_new_registry(),
        )
        self.decision = _decision()

    @property
    def log(self):
        return read_log(self.root)

    @property
    def execution(self):
        return self.executor.execution_for(self.decision.logical_action_id)


def test_u14a_a_cancellation_before_the_port_terminalized_the_call_is_the_interrupted_path(
    tmp_path, sclock, monkeypatch
) -> None:
    """The step ends in the loop iteration that requests the cancellation, before any terminal.

    On Python 3.10 and 3.11 the raw ``wait_for`` around the act returns the child's
    outcome and drops the cancellation; on 3.12 it awaits the act inline and the
    cancellation wins.
    """

    handle = Handle()
    seen = spy_reports(monkeypatch)
    completions = FakeCompletions(
        sclock, FakeStream(sclock, []), create=("race", _Escape()), then=cancel_outer(handle)
    )
    rig = ExecRig(tmp_path, _r1(provider_stream=True, **knobs(first=10)), completions=completions)
    _, error = drive(lambda: rig.executor(rig.decision), handle=handle)
    assert isinstance(error, asyncio.CancelledError), (
        f"the cancellation was dropped; the attempt ended with {error!r}"
    )

    log = rig.log
    (terminal,) = exactly(of(log, *TERMINALS), 1)
    assert terminal["event_type"] == "provider_call_outcome_unknown"
    assert terminal["payload"]["failure_condition"] == "interrupted_during_provider_call"
    assert [e for e in log if e["payload"].get("failure_condition") == "timeout"] == []
    assert seen == []


def _assert_one_billed_call(rig, *, status, condition, call_id) -> None:
    """The ledger of the interrupted attempt: the call once, with 3 in, 2 out, 0.7."""

    (attempt,) = exactly(rig.execution.attempts, 1)
    (record,) = exactly(attempt.provider_calls, 1)
    assert record.provider_call_id == call_id
    assert record.status == status and record.failure_condition == condition
    assert (record.input_tokens, record.output_tokens) == (3, 2)
    assert record.cost_usd == pytest.approx(0.7)
    assert rig.executor.total_cost_usd == pytest.approx(0.7)


def test_u14b_a_cancellation_after_the_port_terminalized_a_deadline_failure_keeps_its_record(
    tmp_path, sclock, monkeypatch
) -> None:
    handle = Handle()
    seen = spy_reports(monkeypatch, handle)
    # A usage-only chunk (non-progress) reports 3 in, 2 out, cost 0.7; then the stream stalls.
    stream = FakeStream(sclock, [chunk(NEAR, usage_frame()), hang()])
    rig = ExecRig(
        tmp_path,
        _r1(provider_stream=True, **knobs(first=10)),
        completions=FakeCompletions(sclock, stream),
    )
    _, error = drive(lambda: rig.executor(rig.decision), handle=handle)
    assert isinstance(error, asyncio.CancelledError), (
        f"the cancellation was dropped; the attempt ended with {error!r}"
    )

    log = rig.log
    (call_id,) = exactly(started_ids(log), 1)
    (terminal,) = exactly(of(log, *TERMINALS), 1)
    assert terminal["event_type"] == "provider_call_outcome_unknown"
    assert terminal["payload"]["failure_condition"] == "timeout"
    assert terminal["payload"].get("stream_deadline") == "first_progress"
    assert seen == ["timeout"]
    _assert_one_billed_call(rig, status="outcome_unknown", condition="timeout", call_id=call_id)
    # The public spend keeps the call unsettled (outcome_unknown terminals carry cost "unknown").
    spend = attempt_spend(rig.evidence)
    assert spend.cost_accounting == "lower_bound" and spend.unsettled_call_count == 1


def _billed_503():
    """Usage (3 in, 2 out, cost 0.7), then an SSE 503 error frame: provider_5xx, no http_refusal."""

    def render(stream):
        lib = _http_lib()
        frames = [
            piece("{"),
            usage_frame(),
            {"error": {"message": "Provider returned error", "code": 503}},
        ]
        return lib.Response(
            200, content=_sse(frames), headers={"content-type": "text/event-stream"}
        )

    return render


@pytest.mark.parametrize("window", ["race", "suspended"])
@pytest.mark.parametrize("declared", ["knobs", "no_knobs"])
def test_u14c_a_cancellation_after_the_port_terminalized_a_billed_failure_keeps_its_record(
    tmp_path, monkeypatch, declared, window
) -> None:
    """A billed failure that is not a deadline, with and without the knobs (spec section 3c).

    ``race``: the cancellation is requested in the iteration the port reports the
    failure, so it can only land at the attempt boundary (the executor's wait).
    ``suspended``: the harness suspends after the failed call, so the cancellation
    reaches the interruption handler on every version, knobs or not.
    """

    handle = Handle()
    seen = spy_reports(monkeypatch, handle)
    config = _r1(provider_stream=True, **(knobs(first=10) if declared == "knobs" else {}))
    rig = ExecRig(
        tmp_path,
        config,
        steps=[_billed_503()],
        harness=SuspendingHarness() if window == "suspended" else None,
    )
    _, error = drive(lambda: rig.executor(rig.decision), handle=handle)

    # With the knobs the outer wait is cancellation-safe on every version. Without them
    # and without a suspension the raw wait_for of 3.10 and 3.11 drops the cancellation
    # (and on 3.12 awaits the act inline, so it has nowhere to land): the executor then
    # records the failure on its normal path. The ledger is the same either way.
    if declared == "knobs" or window == "suspended":
        assert isinstance(error, asyncio.CancelledError), (
            f"the cancellation was dropped; the attempt ended with {error!r}"
        )

    log = rig.log
    (call_id,) = exactly(started_ids(log), 1)
    (terminal,) = exactly(of(log, *TERMINALS), 1)
    assert terminal["event_type"] == "provider_call_failed"
    assert terminal["payload"]["cost_usd"] == pytest.approx(0.7)
    assert seen == ["provider_5xx"]
    _assert_one_billed_call(rig, status="failed", condition="provider_5xx", call_id=call_id)


def test_3b_the_attempt_deadline_still_ends_a_stall_no_stream_deadline_bounds(
    tmp_path, sclock
) -> None:
    """Control (section 3b): with a knob declared, the attempt's own deadline still ends the act.

    Idle-only: the wait before the first progress chunk has no stream deadline, so the
    attempt deadline (0.05 s) is the only bound. The act is cancelled and drained, and
    the executor records a plain timeout, without ``stream_deadline``.
    """

    stream = FakeStream(sclock, [])
    completions = FakeCompletions(sclock, stream, create=("hang",))
    profile = make_profile(
        {**V1, "transport_max_retry_seconds": 0.05, **knobs(idle=0.04)},
        stream=True,
        timeout_seconds=0.05,
        max_action_attempts=1,
    )
    rig = Rig(tmp_path, [], profile, wrap=lambda client: sdk_provider(completions))
    _, error = drive(lambda: rig.executor(rig.decision), what="the attempt deadline did not end the act")
    assert isinstance(error, ProviderFailure) and error.condition == "timeout", repr(error)
    assert getattr(error, "stream_deadline", None) is None
    assert completions.create_cancelled == 1
    (terminal,) = exactly(of(rig.log, *TERMINALS), 1)
    assert terminal["event_type"] == "provider_call_outcome_unknown"
    assert terminal["payload"]["failure_condition"] == "timeout"
    assert "stream_deadline" not in terminal["payload"]


# =====================================================================================
# Request identity
# =====================================================================================

# request_sha256 of the streamed transport_v1 request without the knobs, computed on
# the #248 head 77254689 (the hash covers model, prompt, sampling, stream and the
# provider metadata; it must not move).
NO_KNOB_REQUEST_SHA256 = "28bfd7ee7fa9356216d6599ee2004ffca7964f64a22d4558f2f9ef8da44ebbdb"


def _sealed_request(tmp_path, profile, name):
    rig = Rig(tmp_path, [ok()], profile, name=name).run()
    assert rig.error is None, repr(rig.error)
    rig.close()
    (started,) = exactly(of(rig.log, "provider_call_started"), 1)
    return started["payload"]["request"], rig


def test_request_identity_without_the_knobs_is_unchanged(tmp_path) -> None:
    request, _ = _sealed_request(tmp_path, make_profile(stream=True), "plain")
    assert "first_progress_seconds" not in request and "idle_seconds" not in request
    assert request["request_sha256"] == NO_KNOB_REQUEST_SHA256


def test_a_declared_knob_is_bound_into_the_sealed_request(tmp_path) -> None:
    plain, _ = _sealed_request(tmp_path, make_profile(stream=True), "plain")
    first, _ = _sealed_request(tmp_path, stream_profile(first=10), "first")
    idle, _ = _sealed_request(tmp_path, stream_profile(idle=20), "idle")
    both, _ = _sealed_request(tmp_path, stream_profile(first=10, idle=20), "both")
    assert first.get("first_progress_seconds") == 10 and "idle_seconds" not in first
    assert idle.get("idle_seconds") == 20 and "first_progress_seconds" not in idle
    assert both.get("first_progress_seconds") == 10 and both.get("idle_seconds") == 20
    hashes = [r["request_sha256"] for r in (plain, first, idle, both)]
    assert len(set(hashes)) == 4, hashes


def test_the_knobs_are_not_sent_on_the_wire(tmp_path) -> None:
    rig = Rig(tmp_path, [ok()], stream_profile(first=10, idle=20)).run()
    assert rig.error is None, repr(rig.error)
    (body,) = exactly(rig.wire.bodies, 1)
    assert json.loads(body).get("stream") is True
    assert b"first_progress" not in body and b"idle" not in body
    assert b"transport_" not in body


# =====================================================================================
# V1  Validation at construction
# =====================================================================================

BAD_VALUES = {
    "zero": 0,
    "negative": -1,
    "above_timeout": 61,
    "bool": True,
    "huge_int": 10**400,
    "string": "5",
}
# The profile schema already refuses a non-finite number in harness.config, with its
# own error, before an executor exists; the executor's check is reached by replacing
# the config of a valid profile (the way test_streamed_provider_calls does).
NON_FINITE = {"nan": float("nan"), "inf": float("inf")}


@pytest.mark.parametrize("knob", [FIRST, IDLE])
@pytest.mark.parametrize("bad", sorted(BAD_VALUES))
def test_v1_a_malformed_value_is_refused_at_construction(tmp_path, knob, bad) -> None:
    profile = make_profile({**V1, knob: BAD_VALUES[bad]}, stream=True)
    with pytest.raises(EvidenceIntegrityError, match=knob):
        Rig(tmp_path, [], profile)


@pytest.mark.parametrize("knob", [FIRST, IDLE])
@pytest.mark.parametrize("bad", sorted(NON_FINITE))
def test_v1_a_non_finite_value_is_refused_at_construction(tmp_path, knob, bad) -> None:
    valid = make_profile({**V1, knob: 5}, stream=True)
    profile = dataclasses.replace(
        valid,
        harness=dataclasses.replace(
            valid.harness, config={**dict(valid.harness.config), knob: NON_FINITE[bad]}
        ),
    )
    with pytest.raises(EvidenceIntegrityError, match=knob):
        Rig(tmp_path, [], profile)


@pytest.mark.parametrize("knob", [FIRST, IDLE])
def test_v1_a_knob_without_transport_v1_is_refused(tmp_path, knob) -> None:
    config = {key: value for key, value in V1.items() if key != "transport_policy"}
    with pytest.raises(EvidenceIntegrityError, match=knob):
        Rig(tmp_path, [], make_profile({**config, knob: 5}, stream=True))


@pytest.mark.parametrize("knob", [FIRST, IDLE])
def test_v1_a_knob_without_provider_stream_is_refused(tmp_path, knob) -> None:
    with pytest.raises(EvidenceIntegrityError, match=knob):
        Rig(tmp_path, [], make_profile({**V1, knob: 5}, stream=False))


@pytest.mark.parametrize("declared", [{FIRST: 5}, {IDLE: 5}, {FIRST: 60, IDLE: 0.5}, {FIRST: 2.5}])
def test_v1_valid_declarations_construct(tmp_path, declared) -> None:
    Rig(tmp_path, [], make_profile({**V1, **declared}, stream=True)).close()


def test_v1_the_policy_carries_the_declared_values() -> None:
    both = declared_transport_policy(stream_profile(first=10, idle=20))
    assert getattr(both, "first_progress_seconds", None) == 10
    assert getattr(both, "idle_seconds", None) == 20
    first_only = declared_transport_policy(stream_profile(first=10))
    assert getattr(first_only, "first_progress_seconds", None) == 10
    assert getattr(first_only, "idle_seconds", None) is None


# =====================================================================================
# Smoke tests: the real SDK over a mock transport
# =====================================================================================


def _sse_bytes(frame) -> bytes:
    return f"data: {json.dumps(frame)}\n\n".encode()


DONE = b"data: [DONE]\n\n"
FRAMES = [_sse_bytes(frame) for frame in (FR_CONTENT, FR_FINISH, FR_FINAL)] + [DONE]


def held_stream(parts, closed):
    """A 200 SSE response whose body yields ``parts``: bytes, or seconds to wait.

    ``closed`` collects a mark each time the transport closes the response.
    """

    def render(stream):
        lib = _http_lib()

        class Body(lib.AsyncByteStream):
            async def __aiter__(self):
                for part in parts:
                    if isinstance(part, bytes):
                        yield part
                    else:
                        await _REAL_SLEEP(part)

            async def aclose(self):
                closed.append("closed")

        return lib.Response(
            200, stream=Body(), headers={"content-type": "text/event-stream"}
        )

    return render


class AsyncWire:
    """A mock transport handler that may wait before it answers."""

    def __init__(self, responder) -> None:
        self.responder = responder
        self.bodies: list[bytes] = []

    async def handler(self, request):
        self.bodies.append(bytes(request.content))
        return await self.responder(bool(json.loads(request.content).get("stream")))


def smoke_port(tmp_path, wire, profile, name="evidence"):
    evidence = new_store(tmp_path, name)
    return new_port(evidence, build_client(wire), profile), evidence


def smoke_run(tmp_path, wire, profile, name="evidence"):
    port, evidence = smoke_port(tmp_path, wire, profile, name)
    try:
        value, error = drive(
            lambda: port.complete(messages=(), response_mode="text"),
            watchdog=SMOKE_WATCHDOG,
        )
    finally:
        evidence.close()
    return SimpleNamespace(value=value, error=error, port=port, log=read_log(tmp_path / name))


def test_s1_headers_then_no_chunk_expires_as_first_progress(tmp_path) -> None:
    closed: list[str] = []
    wire = Wire([held_stream([STALL, *FRAMES], closed)])
    ran = smoke_run(tmp_path, wire, stream_profile(first=1))
    expect_deadline(ran, "first_progress")


def test_s2_headers_delayed_past_the_deadline_expire_as_first_progress(tmp_path) -> None:
    async def late_headers(streamed):
        await _REAL_SLEEP(STALL)
        return ok()(streamed)

    ran = smoke_run(tmp_path, AsyncWire(late_headers), stream_profile(first=1))
    expect_deadline(ran, "first_progress")


def test_s3_keepalive_comments_are_not_progress(tmp_path) -> None:
    closed: list[str] = []
    keepalives = [b": keepalive\n\n", 0.2] * int(STALL / 0.2)
    wire = Wire([held_stream([*keepalives, *FRAMES], closed)])
    ran = smoke_run(tmp_path, wire, stream_profile(first=1))
    expect_deadline(ran, "first_progress")


def test_s4_content_then_a_stall_expires_as_idle_and_closes_the_response(tmp_path) -> None:
    closed: list[str] = []
    wire = Wire([held_stream([FRAMES[0], STALL, *FRAMES[1:]], closed)])
    ran = smoke_run(tmp_path, wire, stream_profile(first=10, idle=1))
    expect_deadline(ran, "idle")
    assert closed, "the HTTP response was never closed"


def test_s5_a_normal_stream_with_generous_deadlines_matches_the_same_stream_without_knobs(
    tmp_path,
) -> None:
    """Control: green on the current head."""

    declared = smoke_run(tmp_path, Wire([ok()]), stream_profile(first=10, idle=10), "declared")
    plain = smoke_run(tmp_path, Wire([ok()]), make_profile(stream=True), "plain")
    assert declared.error is None and plain.error is None, (declared.error, plain.error)
    assert declared.port.rounds[0].result == plain.port.rounds[0].result
    assert declared.value.text == plain.value.text


def _stalled_then_ok():
    """Attempt 1: headers, then a stall far beyond the 1 s deadline (then a normal reply)."""

    return held_stream([STALL, *FRAMES], [])


def _attempts_of(run):
    (action,) = exactly(run.execution.action_executions, 1)
    return action.attempts


RETRYABLE = (*DECLARED, "timeout")
CELL = {"stream": True, "retryable": RETRYABLE, "max_action_attempts": 2, "timeout_seconds": 10.0}
WINDOW = {"transport_max_retry_seconds": 5.0}  # V1 allows at most the attempt timeout


def _one_real_clock(monkeypatch) -> None:
    """Both of the kernel's monotonic clocks are ``time.monotonic`` in production.

    The autouse ``clock`` fixture fakes the port's (``harness._transport_monotonic``,
    origin 1000.0) and leaves ``_stream_monotonic`` real. These tests run real time end
    to end, so they put the port's clock back: an attempt deadline taken from one clock
    and compared against the other would be a test artifact, not behaviour.
    """

    monkeypatch.setattr(harness_module, "_transport_monotonic", time.monotonic)


def test_s6_a_stalled_attempt_is_retried_as_a_new_attempt(tmp_path, monkeypatch) -> None:
    from aeread.shared_runner.task.evaluation import finalize_family_execution

    _one_real_clock(monkeypatch)
    run = run_cell(
        tmp_path,
        monkeypatch,
        [_stalled_then_ok(), ok()],
        config={**V1, **WINDOW, **knobs(first=1)},
        **CELL,
    )
    assert run.error is None, repr(run.error)
    assert run.wire.requests == 2, "the stalled call must end by its deadline, then a new attempt sends"

    log = run.log
    # Attempt 1 ends with the deadline's terminal; attempt 2 succeeds.
    (unknown,) = exactly(of(log, "provider_call_outcome_unknown"), 1)
    assert unknown["payload"]["failure_condition"] == "timeout"
    assert unknown["payload"].get("stream_deadline") == "first_progress"
    (succeeded,) = exactly(of(log, "provider_call_succeeded"), 1)
    assert succeeded["action_attempt_id"] != unknown["action_attempt_id"]
    # No in-attempt re-send: one call per attempt and no port backoff.
    for attempt_id in {e["action_attempt_id"] for e in of(log, "provider_call_started")}:
        calls = [e for e in of(log, "provider_call_started") if e["action_attempt_id"] == attempt_id]
        assert len(calls) == 1
    assert port_backoffs(log) == []
    first, second = exactly(_attempts_of(run), 2)
    assert (first.ordinal, first.retry_reason) == (0, None)
    assert (second.ordinal, second.retry_reason) == (1, "timeout")
    assert run.execution.episode_result.final_state["offer"] == 7

    # Reconciliation, audit and resume pass.
    execution = run.execution
    execution.evidence.audit_reconciliation()
    _install_scorer(run.setup)
    receipt = finalize_family_execution(setup=run.setup, execution=execution)
    assert receipt.status == "ok" and receipt.inclusion_status == "included"
    execution.evidence.close()
    _reopen_sealed(run.attempt_dir, receipt)


def test_s7_a_stalled_attempt_reports_one_transient_timeout_to_the_route(
    tmp_path, monkeypatch, reports
) -> None:
    _one_real_clock(monkeypatch)
    run = run_route_cell(
        tmp_path,
        monkeypatch,
        [_stalled_then_ok(), ok()],
        registry=_new_registry(),
        config=_r1(**WINDOW, **knobs(first=1)),
        **CELL,
    )
    assert run.error is None, repr(run.error)
    assert [report.label for report in reports] == ["timeout", "success"]
