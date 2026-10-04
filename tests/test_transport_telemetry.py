"""Opt-in transport telemetry, foundation and isolation slices (#226 S1, M1a/M1b).

Real HTTP over loopback (tests/transport_responder.py), so httpcore emits real
trace events.  Covers spec tests 1 (off-path parity), 2 (success phases and
connection reuse), 10 (client lifecycle) and 11 (placement); M1b adds the
correlation (9) and isolation (8, minus the observation budget) tests.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.model_call import transport_telemetry as tt
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.run.publication import bundle_artifact_digests
from aeread.shared_runner.task import execution
from aeread.shared_runner.task.execution import (
    ArenaChatClient,
    OpenAIResponsesClient,
    OpenRouterChatClient,
    execute_plan_cell,
)
from aeread_families.single_offer.runner import build_single_offer_smoke
from tests.test_shared_runner_execution import (
    FakeOpenRouterCompletions,
    _openrouter_request,
)
from tests.transport_responder import Reply, TransportResponder, json_reply

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PHASES = [
    "connection.connect_tcp.started",
    "connection.connect_tcp.complete",
    "http11.send_request_headers.started",
    "http11.send_request_headers.complete",
    "http11.send_request_body.started",
    "http11.send_request_body.complete",
    "http11.receive_response_headers.started",
    "http11.receive_response_headers.complete",
    "http11.receive_response_body.started",
    "http11.receive_response_body.complete",
    "http11.response_closed.started",
    "http11.response_closed.complete",
]


def _build_openrouter_body() -> dict[str, Any]:
    response = asyncio.run(FakeOpenRouterCompletions().create())
    return response.model_dump(mode="json")


# Built at import: asyncio.run cannot be called from inside a running loop.
OPENROUTER_BODY = _build_openrouter_body()


def _request_for(base_url: str, call_id: str = "provider_call_openrouter_fixture"):
    return dataclasses.replace(
        _openrouter_request(), base_url=base_url, provider_call_id=call_id
    ).with_computed_hash()


def _records(directory: Path, wanted: int, *, event: str = "http11.response_closed.complete"):
    """Call-sidecar records, once the writer thread has flushed `wanted` of `event`."""

    deadline = time.monotonic() + 5
    while True:
        records = [
            json.loads(line)
            for path in sorted(directory.rglob("*.transport.jsonl"))
            for line in path.read_text().splitlines()
            if '"event"' in line
        ]
        if sum(r["event"] == event for r in records) >= wanted or time.monotonic() > deadline:
            return records
        time.sleep(0.02)


def _scoped_calls(responder_script, requests, *, env_dir: Path | None, monkeypatch):
    """Run `requests` in order on one OpenRouter client inside a cell scope."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    if env_dir is None:
        monkeypatch.delenv(tt.ENV_DIR, raising=False)
    else:
        monkeypatch.setenv(tt.ENV_DIR, str(env_dir))

    async def main():
        async with TransportResponder(responder_script) as responder:
            client = OpenRouterChatClient(base_url=responder.base_url)
            results = []
            with tt.bind_cell_scope(
                run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
            ):
                for call_id in requests:
                    request = _request_for(responder.base_url, call_id)
                    results.append(await client.complete(request))
            await client._client.close()
            return responder, results

    return asyncio.run(main())


# --- test 1: off-path parity -------------------------------------------------


@pytest.mark.parametrize(
    "client_cls, key_env",
    [
        (OpenAIResponsesClient, "OPENAI_API_KEY"),
        (OpenRouterChatClient, "OPENROUTER_API_KEY"),
        (ArenaChatClient, "ARENA_API_KEY"),
    ],
)
def test_with_telemetry_off_the_clients_pass_no_http_client(
    monkeypatch, client_cls, key_env
) -> None:
    import openai

    seen: list[dict[str, Any]] = []
    real = openai.AsyncOpenAI

    def spy(**kwargs):
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(openai, "AsyncOpenAI", spy)
    monkeypatch.setenv(key_env, "sk-test-key")
    monkeypatch.delenv(tt.ENV_DIR, raising=False)
    client_cls()
    assert set(seen[0]) == {"api_key", "base_url", "max_retries"}


def test_with_telemetry_on_the_clients_pass_a_telemetry_http_client(
    monkeypatch, tmp_path
) -> None:
    import openai

    seen: list[dict[str, Any]] = []
    real = openai.AsyncOpenAI

    def spy(**kwargs):
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(openai, "AsyncOpenAI", spy)
    monkeypatch.setenv("ARENA_API_KEY", "sk-test-key")
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))
    ArenaChatClient()
    assert isinstance(seen[0]["http_client"], tt.telemetry_client_class())


def _fixed_clock(monkeypatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 4, 12, 0, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(execution, "datetime", FixedDatetime)


def test_a_scripted_cell_is_byte_identical_with_telemetry_off_and_on(
    monkeypatch, tmp_path
) -> None:
    from aeread_families.single_offer.runner import FixedResponseProvider

    _fixed_clock(monkeypatch)

    def run(name: str):
        setup = build_single_offer_smoke(
            provider="fake", model="fake-model", revision="fixed-v1"
        )
        return asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=tmp_path / name,
                prompt_sources=setup.prompt_sources,
                providers={"fake": FixedResponseProvider('{"offer":7}')},
                pricing=setup.pricing,
                harnesses=default_harnesses(),
            )
        )

    monkeypatch.delenv(tt.ENV_DIR, raising=False)
    off = run("off")
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path / "telemetry"))
    on = run("on")
    off.evidence.seal()
    on.evidence.seal()

    assert off.evidence.events_path.read_bytes() == on.evidence.events_path.read_bytes()
    assert off.evidence.events_path.stat().st_size > 0
    assert off.evidence.seal_path.read_bytes() == on.evidence.seal_path.read_bytes()


def test_execute_plan_cell_binds_the_cell_scope_around_the_episode(
    monkeypatch, tmp_path
) -> None:
    from aeread_families.single_offer.runner import FixedResponseProvider

    seen: list[Any] = []

    class ScopeProbe(FixedResponseProvider):
        async def complete(self, request):
            seen.append(tt.current_scope())
            return await super().complete(request)

    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )
    execution_result = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "probe",
            prompt_sources=setup.prompt_sources,
            providers={"fake": ScopeProbe('{"offer":7}')},
            pricing=setup.pricing,
            harnesses=default_harnesses(),
        )
    )
    (scope,) = seen
    assert scope.run_plan_id == setup.plan.run_plan_id
    assert scope.cell_id == setup.plan.cells[0].cell_id
    assert scope.episode_attempt_id == execution_result.episode_attempt_id
    assert tt.current_scope() is None, "the token is reset after the episode"


def test_a_live_call_returns_an_equal_result_with_telemetry_off_and_on(
    monkeypatch, tmp_path
) -> None:
    script = [json_reply(OPENROUTER_BODY)]
    _, off = _scoped_calls(script, ["c1"], env_dir=None, monkeypatch=monkeypatch)
    _, on = _scoped_calls(
        script, ["c1"], env_dir=tmp_path / "telemetry", monkeypatch=monkeypatch
    )
    assert off[0] == on[0]
    assert off[0].output_text == '{"offer":7}'


# --- test 2: success phases and connection reuse -----------------------------


def test_phases_appear_in_order_and_the_second_call_reuses_the_connection(
    monkeypatch, tmp_path
) -> None:
    responder, _ = _scoped_calls(
        [json_reply(OPENROUTER_BODY)],
        ["call_one", "call_two"],
        env_dir=tmp_path,
        monkeypatch=monkeypatch,
    )
    records = _records(tmp_path, wanted=2)
    assert responder.connections == 1

    by_call = {
        call: [r for r in records if r["provider_call_id"] == call]
        for call in ("call_one", "call_two")
    }
    first = [r["event"] for r in by_call["call_one"]]
    assert first == EXPECTED_PHASES
    second = [r["event"] for r in by_call["call_two"]]
    assert second == [e for e in EXPECTED_PHASES if not e.startswith("connection.connect_tcp")]

    def reuse(call: str) -> Any:
        (record,) = [
            r for r in by_call[call] if r["event"] == "http11.send_request_headers.started"
        ]
        return record["connection_reused"]

    assert reuse("call_one") is False
    assert reuse("call_two") is True
    (headers,) = [
        r for r in by_call["call_one"] if r["event"] == "http11.receive_response_headers.complete"
    ]
    assert headers["status"] == 200

    for record in records:
        assert record["session_id"] == tt.SESSION_ID
        assert record["pid"] == os.getpid()
        assert record["run_plan_id"] == "plan_x"
        assert record["cell_id"] == "cell_x"
        assert record["episode_attempt_id"] == "attempt_x"
        assert record["credential_fp"] == tt.credential_fingerprint("sk-test-key")
        assert record["route_provider"] == "DeepInfra"
        assert "sk-test-key" not in json.dumps(record)


def test_the_sidecar_has_a_header_line_and_the_process_sidecar_a_session_start(
    monkeypatch, tmp_path
) -> None:
    _scoped_calls(
        [json_reply(OPENROUTER_BODY)], ["c1"], env_dir=tmp_path, monkeypatch=monkeypatch
    )
    _records(tmp_path, wanted=1)
    session_dir = tmp_path / tt.HIDDEN_DIRNAME / tt.SESSION_ID
    (sidecar,) = session_dir.rglob("*.transport.jsonl")
    assert sidecar == session_dir / "plan_x" / "cell_x" / "attempt_x.transport.jsonl"
    header = json.loads(sidecar.read_text().splitlines()[0])
    assert header["schema"] == "aeread.transport_telemetry/0.2"
    assert header["pid"] == os.getpid() and header["session_id"] == tt.SESSION_ID
    process = [json.loads(l) for l in (session_dir / "process.jsonl").read_text().splitlines()]
    assert process[0]["event"] == "session_start"


def test_a_call_with_no_cell_scope_is_untraced_and_counted(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))

    async def main():
        async with TransportResponder([json_reply(OPENROUTER_BODY)]) as responder:
            client = OpenRouterChatClient(base_url=responder.base_url)
            await client.complete(_request_for(responder.base_url))

    asyncio.run(main())
    runtime = tt.get_runtime()
    assert runtime.counters["unscoped_calls"] == 1
    assert not list(tmp_path.rglob("*.transport.jsonl"))


@pytest.mark.parametrize("bad", ["relative/dir", "/proc/definitely/not/writable"])
def test_a_bad_directory_disables_telemetry_with_one_stderr_line(
    monkeypatch, capsys, bad
) -> None:
    monkeypatch.setenv(tt.ENV_DIR, bad)
    assert tt.get_runtime() is None
    assert tt.get_runtime() is None
    assert tt.build_http_client() is None
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "telemetry disabled" in err[0]


# --- test 10: lifecycle ------------------------------------------------------


def test_the_telemetry_client_is_the_sdk_wrapper_and_closes_its_transport(
    monkeypatch, tmp_path
) -> None:
    from openai._base_client import AsyncHttpxClientWrapper

    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))
    client = tt.build_http_client()
    assert isinstance(client, AsyncHttpxClientWrapper)
    assert issubclass(tt.telemetry_client_class(), AsyncHttpxClientWrapper)
    assert "__del__" in vars(AsyncHttpxClientWrapper)

    closed: list[bool] = []
    transport = client._transport
    original = transport.aclose

    async def spy() -> None:
        closed.append(True)
        await original()

    transport.aclose = spy
    asyncio.run(client.aclose())
    assert client.is_closed and closed == [True]


def test_the_telemetry_client_keeps_the_sdk_defaults(monkeypatch, tmp_path) -> None:
    import openai

    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))
    client = tt.build_http_client()
    default = openai.DefaultAsyncHttpxClient()
    assert client.timeout == default.timeout
    assert client.follow_redirects is True
    assert client._transport._pool._max_connections == default._transport._pool._max_connections
    assert openai.__version__ == "2.53.0"


# --- test 11: placement and sessions -----------------------------------------


def test_a_telemetry_dir_inside_a_bundle_root_is_not_an_artifact(
    monkeypatch, tmp_path
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "result.json").write_text("{}")
    before = bundle_artifact_digests(bundle)

    _scoped_calls(
        [json_reply(OPENROUTER_BODY)],
        ["c1"],
        env_dir=bundle / "telemetry",
        monkeypatch=monkeypatch,
    )
    assert _records(bundle, wanted=1)
    assert list(bundle.rglob("*.transport.jsonl"))
    assert bundle_artifact_digests(bundle) == before


_CHILD = """
import asyncio, json, sys
from aeread.shared_runner.model_call import transport_telemetry as tt
from aeread.shared_runner.task.execution import OpenRouterChatClient
from tests.test_transport_telemetry import OPENROUTER_BODY, _request_for
from tests.transport_responder import TransportResponder, json_reply

async def main():
    async with TransportResponder([json_reply(OPENROUTER_BODY)]) as responder:
        client = OpenRouterChatClient(base_url=responder.base_url)
        with tt.bind_cell_scope(run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"):
            await client.complete(_request_for(responder.base_url))
asyncio.run(main())
print(tt.SESSION_ID)
"""


def test_two_processes_running_the_same_scope_write_separate_session_files(
    tmp_path,
) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}",
        "OPENROUTER_API_KEY": "sk-test-key",
        tt.ENV_DIR: str(tmp_path),
    }
    sessions = [
        subprocess.run(
            [sys.executable, "-c", _CHILD],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.strip()
        for _ in range(2)
    ]
    assert sessions[0] != sessions[1]
    for session in sessions:
        sidecar = (
            tmp_path / tt.HIDDEN_DIRNAME / session / "plan_x" / "cell_x"
            / "attempt_x.transport.jsonl"
        )
        events = [json.loads(l)["event"] for l in sidecar.read_text().splitlines()[1:]]
        assert events == EXPECTED_PHASES


# --- test 9: correlation across concurrent cells, rounds, cancellation -------


def _cell(plan: str, cell: str, attempt: str):
    return tt.bind_cell_scope(run_plan_id=plan, cell_id=cell, episode_attempt_id=attempt)


def test_concurrent_cells_each_land_in_their_own_sidecar_with_their_own_ids(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))

    async def one_cell(client, base_url, name: str) -> None:
        with _cell(f"plan_{name}", f"cell_{name}", f"attempt_{name}"):
            for index in range(2):
                await client.complete(_request_for(base_url, f"call_{name}_{index}"))

    async def main() -> None:
        # Overlapping replies force the two cells' calls to interleave.
        async with TransportResponder(
            [json_reply(OPENROUTER_BODY, header_delay=0.05)]
        ) as responder:
            client = OpenRouterChatClient(base_url=responder.base_url)
            await asyncio.gather(
                *(one_cell(client, responder.base_url, n) for n in ("a", "b"))
            )
            await client._client.close()

    asyncio.run(main())
    records = _records(tmp_path, wanted=4)
    session_dir = tmp_path / tt.HIDDEN_DIRNAME / tt.SESSION_ID
    for name in ("a", "b"):
        sidecar = session_dir / f"plan_{name}" / f"cell_{name}" / f"attempt_{name}.transport.jsonl"
        mine = [json.loads(l) for l in sidecar.read_text().splitlines()[1:]]
        assert {r["provider_call_id"] for r in mine} == {f"call_{name}_0", f"call_{name}_1"}
        assert {(r["run_plan_id"], r["cell_id"], r["episode_attempt_id"]) for r in mine} == {
            (f"plan_{name}", f"cell_{name}", f"attempt_{name}")
        }
        assert [r["event"] for r in mine].count("http11.response_closed.complete") == 2
    assert len(records) == sum(
        len(path.read_text().splitlines()) - 1 for path in session_dir.rglob("*.transport.jsonl")
    )


def test_harness_rounds_keep_the_kernel_provider_call_ids(monkeypatch, tmp_path) -> None:
    from aeread.shared_runner.model_call.harness import CanonicalMessage, KernelModelPort
    from tests.test_shared_runner_harness import (
        FAKE_PRICING,
        SYSTEM_PROMPT,
        _evidence,
        _profile,
    )

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path / "telemetry"))

    class LiveProvider:
        """The live client, pointed at the responder; keeps the port's call ids."""

        def __init__(self, client, base_url: str) -> None:
            self._client, self._base_url = client, base_url

        async def complete(self, request):
            # The port's request is a fake-provider one; keep only its call id.
            return await self._client.complete(
                _request_for(self._base_url, request.provider_call_id)
            )

    async def main() -> list[str]:
        async with TransportResponder([json_reply(OPENROUTER_BODY)]) as responder:
            client = OpenRouterChatClient(base_url=responder.base_url)
            port = KernelModelPort(
                evidence=_evidence(tmp_path),
                provider=LiveProvider(client, responder.base_url),
                pricing=FAKE_PRICING,
                profile=_profile(),
                instructions=SYSTEM_PROMPT,
                action_attempt_id="action_attempt_fixture",
            )
            ids = []
            with _cell("plan_h", "cell_h", "attempt_h"):
                for _ in range(3):
                    turn = await port.complete(
                        messages=(CanonicalMessage(role="user", content="hi"),),
                        response_mode="text",
                    )
                    ids.append(turn.provider_call_id)
            await client._client.close()
            return ids

    ids = asyncio.run(main())
    assert len(set(ids)) == 3 and all(ids)
    records = _records(tmp_path / "telemetry", wanted=3)
    closed = [r["provider_call_id"] for r in records if r["event"] == "http11.response_closed.complete"]
    assert closed == ids
    assert {r["episode_attempt_id"] for r in records} == {"attempt_h"}


def test_a_cancelled_call_resets_its_context_for_the_next_call(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))
    seen: list[Any] = []

    async def main() -> None:
        async with TransportResponder(
            [Reply(header_delay=30.0), Reply(header_delay=30.0), json_reply(OPENROUTER_BODY)]
        ) as responder:
            client = OpenRouterChatClient(base_url=responder.base_url)
            with _cell("plan_c", "cell_c", "attempt_c"):
                slow = asyncio.ensure_future(
                    client.complete(_request_for(responder.base_url, "call_cancelled"))
                )
                await asyncio.sleep(0.2)
                slow.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await slow
                seen.append(tt.current_scope())
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        client.complete(_request_for(responder.base_url, "call_timeout")), 0.05
                    )
                seen.append(tt.current_scope())
                # The same task's next call carries only its own ids.
                await client.complete(_request_for(responder.base_url, "call_next"))
                seen.append(tt.current_scope())
            await client._client.close()

    asyncio.run(main())
    for scope in seen:
        assert scope.provider_call_id is None and scope.credential_fp is None
        assert scope.cell_id == "cell_c"

    records = _records(tmp_path, wanted=3)
    nxt = [r for r in records if r["provider_call_id"] == "call_next"]
    assert [r["event"] for r in nxt][-1] == "http11.response_closed.complete"
    assert {r["provider_call_id"] for r in records} == {
        "call_cancelled", "call_timeout", "call_next",
    }


def test_an_unscoped_call_beside_a_scoped_one_is_untraced_and_counted(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))

    async def scoped(client, base_url) -> None:
        with _cell("plan_s", "cell_s", "attempt_s"):
            await client.complete(_request_for(base_url, "call_scoped"))

    async def main() -> None:
        async with TransportResponder([json_reply(OPENROUTER_BODY)]) as responder:
            client = OpenRouterChatClient(base_url=responder.base_url)
            await asyncio.gather(
                scoped(client, responder.base_url),
                client.complete(_request_for(responder.base_url, "call_canary")),
            )
            await client._client.close()

    asyncio.run(main())
    records = _records(tmp_path, wanted=1)
    assert {r["provider_call_id"] for r in records} == {"call_scoped"}
    assert tt.get_runtime().counters["unscoped_calls"] == 1


# --- test 8: isolation (observation budget lands with the tee in M2) ---------


def _block_writer(monkeypatch) -> threading.Event:
    """Make the writer thread's file work wait on an Event, as a hung disk would."""

    release = threading.Event()
    real = tt._Runtime._drain

    def blocked(self) -> None:
        release.wait(30)
        real(self)

    monkeypatch.setattr(tt._Runtime, "_drain", blocked)
    return release


def test_a_raising_trace_recorder_leaves_the_result_unchanged_and_is_counted(
    monkeypatch, tmp_path
) -> None:
    script = [json_reply(OPENROUTER_BODY)]
    _, off = _scoped_calls(script, ["c1"], env_dir=None, monkeypatch=monkeypatch)

    def boom(self, scope, event, fields) -> None:
        raise RuntimeError("recorder exploded")

    monkeypatch.setattr(tt._Runtime, "emit", boom)
    _, on = _scoped_calls(script, ["c1"], env_dir=tmp_path, monkeypatch=monkeypatch)
    assert on[0] == off[0]
    assert tt.get_runtime().counters["telemetry_dropped"] >= len(EXPECTED_PHASES)


@pytest.mark.parametrize("bad", ["relative/m1b_dir", "FILE_PARENT"])
def test_an_unusable_directory_leaves_the_call_result_unchanged(
    monkeypatch, tmp_path, capsys, bad
) -> None:
    if bad == "FILE_PARENT":
        (tmp_path / "afile").write_text("x")
        bad = str(tmp_path / "afile" / "sub")
    script = [json_reply(OPENROUTER_BODY)]
    _, off = _scoped_calls(script, ["c1"], env_dir=None, monkeypatch=monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv(tt.ENV_DIR, bad)

    async def main():
        async with TransportResponder(script) as responder:
            client = OpenRouterChatClient(base_url=responder.base_url)
            with _cell("plan_x", "cell_x", "attempt_x"):
                result = await client.complete(_request_for(responder.base_url, "c1"))
            await client._client.close()
            return result

    assert asyncio.run(main()) == off[0]
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 1 and "telemetry disabled" in lines[0]


def test_a_full_deque_drops_and_counts_without_touching_the_call(
    monkeypatch, tmp_path
) -> None:
    script = [json_reply(OPENROUTER_BODY)]
    _, off = _scoped_calls(script, ["c1"], env_dir=None, monkeypatch=monkeypatch)
    release = _block_writer(monkeypatch)
    monkeypatch.setattr(tt, "QUEUE_LIMIT", 1)
    try:
        _, on = _scoped_calls(script, ["c1"], env_dir=tmp_path, monkeypatch=monkeypatch)
        runtime = tt.get_runtime()
        assert on[0] == off[0]
        assert len(runtime.queue) == 1
        assert runtime.counters["telemetry_dropped"] == len(EXPECTED_PHASES) - 1
    finally:
        release.set()


def test_a_blocked_writer_does_not_delay_a_call(monkeypatch, tmp_path) -> None:
    script = [json_reply(OPENROUTER_BODY)]
    _scoped_calls(script, ["warm"], env_dir=None, monkeypatch=monkeypatch)
    release = _block_writer(monkeypatch)
    try:
        started = time.monotonic()
        _scoped_calls(script, ["c1"] * 5, env_dir=tmp_path, monkeypatch=monkeypatch)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    # The writer is stuck for up to 30 s; five calls still finish within a margin.
    assert elapsed < 2.0


_BLOCKED_CHILD = """
import asyncio, threading, time
from aeread.shared_runner.model_call import transport_telemetry as tt
tt._Runtime._drain = lambda self: threading.Event().wait()
from aeread.shared_runner.task.execution import OpenRouterChatClient
from tests.test_transport_telemetry import OPENROUTER_BODY, _request_for
from tests.transport_responder import TransportResponder, json_reply

async def main():
    async with TransportResponder([json_reply(OPENROUTER_BODY)]) as responder:
        client = OpenRouterChatClient(base_url=responder.base_url)
        with tt.bind_cell_scope(run_plan_id="p", cell_id="c", episode_attempt_id="a"):
            await client.complete(_request_for(responder.base_url))
asyncio.run(main())
print(time.time(), flush=True)
"""


def test_a_subprocess_whose_writer_is_blocked_still_exits_promptly(tmp_path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}",
        "OPENROUTER_API_KEY": "sk-test-key",
        tt.ENV_DIR: str(tmp_path),
    }
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCKED_CHILD],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60, check=True,
    )
    exit_lag = time.time() - float(completed.stdout.strip().splitlines()[-1])
    assert exit_lag < 5.0, f"interpreter exit took {exit_lag:.1f}s with a blocked writer"
