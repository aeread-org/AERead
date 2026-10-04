"""Opt-in transport telemetry, foundation slice (#226 S1, M1a).

Real HTTP over loopback (tests/transport_responder.py), so httpcore emits real
trace events.  Covers spec tests 1 (off-path parity), 2 (success phases and
connection reuse), 10 (client lifecycle) and 11 (placement).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
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
