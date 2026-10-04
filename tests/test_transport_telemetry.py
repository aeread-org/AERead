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
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path / "telemetry"))

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
    assert len(scope.execution_id) == 32
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
    # Tee marks (first_body_chunk, last_chunk) are checked in the M2 tests.
    first = [r["event"] for r in by_call["call_one"] if r["event"] not in MARK_EVENTS]
    assert first == EXPECTED_PHASES
    second = [r["event"] for r in by_call["call_two"] if r["event"] not in MARK_EVENTS]
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
    assert sidecar.parent == session_dir / "plan_x" / "cell_x"
    assert sidecar.name.startswith("attempt_x.") and sidecar.name.endswith(".transport.jsonl")
    execution_id = sidecar.name.split(".")[1]
    assert len(execution_id) == 32
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
        (sidecar,) = (
            tmp_path / tt.HIDDEN_DIRNAME / session / "plan_x" / "cell_x"
        ).glob("attempt_x.*.transport.jsonl")
        events = [json.loads(l)["event"] for l in sidecar.read_text().splitlines()[1:]]
        assert [e for e in events if e not in MARK_EVENTS] == EXPECTED_PHASES


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
        (sidecar,) = (session_dir / f"plan_{name}" / f"cell_{name}").glob(
            f"attempt_{name}.*.transport.jsonl"
        )
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
        # Every phase plus the two chunk marks of a JSON body, minus the one queued.
        assert runtime.counters["telemetry_dropped"] == len(EXPECTED_PHASES) + 2 - 1
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


# --- M2: the stream tee (spec section 4; tests 5, 6, 7 and the budget case of 8) ---

import gzip  # noqa: E402
import zlib  # noqa: E402

import httpx  # noqa: E402
import openai  # noqa: E402

from tests.transport_responder import (  # noqa: E402
    SSE_DONE,
    SSE_KEEPALIVE,
    sse_reply,
)

MARK_EVENTS = {
    "first_body_chunk",
    "last_chunk",
    "keepalive",
    "first_delta.content",
    "first_delta.reasoning",
    "first_delta.tool_args",
    "delta_marks",
}


def _chunk_obj(delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }


def _frame(delta: dict[str, Any]) -> bytes:
    return b"data: " + json.dumps(_chunk_obj(delta), ensure_ascii=False).encode() + b"\n\n"


TOOL_DELTA = {"tool_calls": [{"index": 0, "function": {"arguments": "{"}}]}


def _bomb() -> bytes:
    # ~50 MiB of zeros inflate from a few tens of KiB.
    return gzip.compress(b"\0" * 50_000_000, 1)


def _utf8_split() -> list[bytes]:
    whole = _frame({"content": "café"})
    cut = whole.index("é".encode()) + 1  # between the two bytes of the character
    return [whole[:cut], whole[cut:], SSE_DONE]


def _multiline_frame() -> bytes:
    text = json.dumps(_chunk_obj({"content": "x"}), indent=1)
    return ("".join(f"data: {line}\n" for line in text.splitlines()) + "\n").encode()


_BODY = _frame({"content": "hi"})
_DELAYS = (0, 0.05, 0.05, 0.05)
# name -> (reply, marks the tee must record besides first_body_chunk and last_chunk)
CASES: dict[str, tuple[Reply, set[str]]] = {
    "keepalive_only": (sse_reply([SSE_KEEPALIVE, SSE_KEEPALIVE, SSE_DONE]), {"keepalive"}),
    "content": (sse_reply([_frame({"content": "hi"}), SSE_DONE]), {"first_delta.content"}),
    "reasoning": (
        sse_reply([_frame({"reasoning": "think"}), SSE_DONE]),
        {"first_delta.reasoning"},
    ),
    "tool_only": (sse_reply([_frame(TOOL_DELTA), SSE_DONE]), {"first_delta.tool_args"}),
    "empty_then_content": (
        sse_reply([_frame({"role": "assistant", "content": ""}), _BODY, SSE_DONE]),
        {"first_delta.content"},
    ),
    "gzip": (
        sse_reply([SSE_KEEPALIVE, _BODY, SSE_DONE], gzip=True),
        {"keepalive", "first_delta.content"},
    ),
    "utf8_split": (
        sse_reply(_utf8_split(), chunk_delays=_DELAYS),
        {"first_delta.content"},
    ),
    "delimiter_split": (
        sse_reply([_BODY[:-1], b"\n", SSE_DONE], chunk_delays=_DELAYS),
        {"first_delta.content"},
    ),
    "crlf_split": (
        sse_reply(
            [_BODY[:-2].rstrip(b"\n") + b"\r", b"\n\r", b"\n", SSE_DONE],
            chunk_delays=_DELAYS,
        ),
        {"first_delta.content"},
    ),
    "crlf_multiline_split": (
        # CRLF cut between its CR and LF in the middle of one multi-line event.
        sse_reply(
            [
                b'data: {"choices":[{"delta":\r',
                b'\ndata: {"content":"x"}}]}\r\n\r\n',
                SSE_DONE,
            ],
            chunk_delays=_DELAYS,
        ),
        {"first_delta.content"},
    ),
    "multiline_data": (sse_reply([_multiline_frame(), SSE_DONE]), {"first_delta.content"}),
    "unknown_encoding": (
        sse_reply([_BODY, SSE_DONE], headers={"Content-Encoding": "x-custom"}),
        {"delta_marks"},
    ),
}


async def _raw_read(base_url: str, **client_kwargs: Any):
    """Read the raw body; returns (chunks, exception).  Telemetry follows the env."""

    client = tt.build_http_client(**client_kwargs) or httpx.AsyncClient(**client_kwargs)
    chunks: list[bytes] = []
    error: BaseException | None = None
    try:
        with tt.bind_cell_scope(
            run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
        ):
            async with client.stream("POST", base_url + "/chat/completions") as response:
                async for chunk in response.aiter_raw():
                    chunks.append(chunk)
    except Exception as exc:
        error = exc
    finally:
        await client.aclose()
    return chunks, error


def _env(monkeypatch, directory: Path | None) -> None:
    if directory is None:
        monkeypatch.delenv(tt.ENV_DIR, raising=False)
    else:
        monkeypatch.setenv(tt.ENV_DIR, str(directory))


def _off_and_on(reply: Reply, tmp_path: Path, monkeypatch, **client_kwargs: Any):
    async def once():
        async with TransportResponder([reply]) as responder:
            return await _raw_read(responder.base_url, **client_kwargs)

    _env(monkeypatch, None)
    off = asyncio.run(once())
    _env(monkeypatch, tmp_path)
    on = asyncio.run(once())
    return off, on


def _marks(directory: Path) -> list[dict[str, Any]]:
    _records(directory, 1)  # wait for the writer to flush the call
    return [r for r in _records(directory, 1) if r["event"] in MARK_EVENTS]


def _mark_names(directory: Path) -> list[str]:
    return [r["event"] for r in _marks(directory)]


@pytest.mark.parametrize("name", sorted(CASES))
def test_sse_bytes_and_marks(monkeypatch, tmp_path, name) -> None:
    reply, expected = CASES[name]
    (off_chunks, off_error), (on_chunks, on_error) = _off_and_on(reply, tmp_path, monkeypatch)
    assert off_error is None and on_error is None
    assert on_chunks == off_chunks  # same raw bytes, same chunking
    marks = _mark_names(tmp_path)
    assert set(marks) == {"first_body_chunk", "last_chunk"} | expected
    if name != "unknown_encoding":  # its note is written when the stream opens
        assert marks[0] == "first_body_chunk"
    assert marks[-1] == "last_chunk"
    assert len(marks) == len(set(marks))  # each mark once per stream
    if name == "unknown_encoding":
        (note,) = [r for r in _marks(tmp_path) if r["event"] == "delta_marks"]
        assert note["delta_marks"] == "unobservable(encoding=x-custom)"
    assert tt.get_runtime().counters["observer_disabled"] == 0


@pytest.mark.parametrize("name", sorted(CASES))
def test_sse_sdk_result_equals_telemetry_off(monkeypatch, tmp_path, name) -> None:
    reply, _ = CASES[name]

    async def once():
        async with TransportResponder([reply]) as responder:
            client = openai.AsyncOpenAI(
                api_key="k",
                base_url=responder.base_url,
                max_retries=0,
                **tt.sdk_client_kwargs(),
            )
            with tt.bind_cell_scope(
                run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
            ):
                stream = await client.chat.completions.create(
                    model="m", messages=[{"role": "user", "content": "x"}], stream=True
                )
                return [c.model_dump(mode="json") async for c in stream]

    _env(monkeypatch, None)
    off = asyncio.run(once())
    _env(monkeypatch, tmp_path)
    on = asyncio.run(once())
    assert on == off
    assert off or name == "keepalive_only"  # the SDK yields nothing for keepalives


def test_a_non_streamed_body_records_only_chunk_marks(monkeypatch, tmp_path) -> None:
    _scoped_calls(
        [json_reply(OPENROUTER_BODY)], ["c1"], env_dir=tmp_path, monkeypatch=monkeypatch
    )
    assert _mark_names(tmp_path) == ["first_body_chunk", "last_chunk"]


# --- test 6: mid-stream drop, early close, cancellation ----------------------


def test_a_mid_stream_drop_delivers_the_same_bytes_and_error(monkeypatch, tmp_path) -> None:
    reply = sse_reply([_BODY, _BODY, SSE_DONE], close_after_chunks=2, chunk_delays=_DELAYS)
    (off_chunks, off_error), (on_chunks, on_error) = _off_and_on(reply, tmp_path, monkeypatch)
    assert off_chunks and on_chunks == off_chunks
    assert type(on_error) is type(off_error) is httpx.RemoteProtocolError
    assert str(on_error) == str(off_error)
    names = _mark_names(tmp_path)
    assert "first_body_chunk" in names
    assert "last_chunk" not in names  # the stream never ended


def test_read_timeout_on_sse_stays_read_timeout(monkeypatch, tmp_path) -> None:
    reply = sse_reply([_BODY, _BODY], chunk_delays=(0, 2.0))
    (off_chunks, off_error), (on_chunks, on_error) = _off_and_on(
        reply, tmp_path, monkeypatch, timeout=httpx.Timeout(5.0, read=0.3)
    )
    assert off_chunks == on_chunks == [_BODY]
    assert type(on_error) is type(off_error) is httpx.ReadTimeout


def test_a_non_streamed_timeout_is_the_same_api_timeout_error(monkeypatch, tmp_path) -> None:
    async def once():
        async with TransportResponder([json_reply({}, header_delay=2.0)]) as responder:
            client = openai.AsyncOpenAI(
                api_key="k",
                base_url=responder.base_url,
                max_retries=0,
                timeout=0.3,
                **tt.sdk_client_kwargs(),
            )
            with tt.bind_cell_scope(
                run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
            ):
                with pytest.raises(openai.APITimeoutError) as caught:
                    await client.chat.completions.create(
                        model="m", messages=[{"role": "user", "content": "x"}]
                    )
            return caught.value

    _env(monkeypatch, None)
    off = asyncio.run(once())
    _env(monkeypatch, tmp_path)
    on = asyncio.run(once())
    assert type(on.__cause__) is type(off.__cause__) is httpx.ReadTimeout
    assert str(on) == str(off)


def test_an_early_close_delivers_the_first_chunk_once_and_closes_the_response(
    monkeypatch, tmp_path
) -> None:
    async def once():
        async with TransportResponder(
            [sse_reply([_BODY, _BODY, SSE_DONE], chunk_delays=(0, 0.3, 0.3))]
        ) as responder:
            client = tt.build_http_client() or httpx.AsyncClient()
            chunks: list[bytes] = []
            with tt.bind_cell_scope(
                run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
            ):
                async with client.stream("POST", responder.base_url + "/x") as response:
                    async for chunk in response.aiter_raw():
                        chunks.append(chunk)
                        break
            await client.aclose()
            return chunks

    _env(monkeypatch, None)
    off = asyncio.run(once())
    _env(monkeypatch, tmp_path)
    on = asyncio.run(once())
    assert on == off == [_BODY]
    names = [r["event"] for r in _records(tmp_path, 1)]
    assert "http11.response_closed.complete" in names  # aclose reached the source
    assert "last_chunk" not in names


def test_cancellation_mid_stream_propagates_and_delivers_the_same_bytes(
    monkeypatch, tmp_path
) -> None:
    async def once():
        async with TransportResponder(
            [sse_reply([_BODY, _BODY], chunk_delays=(0, 5.0))]
        ) as responder:
            client = tt.build_http_client() or httpx.AsyncClient()
            chunks: list[bytes] = []
            first = asyncio.Event()

            async def reader():
                with tt.bind_cell_scope(
                    run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
                ):
                    async with client.stream("POST", responder.base_url + "/x") as response:
                        async for chunk in response.aiter_raw():
                            chunks.append(chunk)
                            first.set()

            task = asyncio.ensure_future(reader())
            await first.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await client.aclose()
            return chunks

    _env(monkeypatch, None)
    off = asyncio.run(once())
    _env(monkeypatch, tmp_path)
    on = asyncio.run(once())
    assert on == off == [_BODY]
    assert "http11.response_closed.complete" in [r["event"] for r in _records(tmp_path, 1)]


class _Source(httpx.AsyncByteStream):
    """A scripted source stream that records how it is used."""

    def __init__(self, chunks: list[bytes], raises: BaseException | None = None) -> None:
        self._chunks = chunks
        self._raises = raises
        self.closed = 0

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk
        if self._raises is not None:
            raise self._raises

    async def aclose(self) -> None:
        self.closed += 1


def _tee(tmp_path, monkeypatch, source, *, sse=True, encoding=""):
    _env(monkeypatch, tmp_path)
    runtime = tt.get_runtime()
    scope = tt.CallScope("plan_x", "cell_x", "attempt_x", provider_call_id="c")
    return tt.observed_stream_class()(source, runtime, scope, sse=sse, content_encoding=encoding), runtime


@pytest.mark.parametrize(
    "error", [RuntimeError("boom"), asyncio.CancelledError(), httpx.ReadTimeout("t")]
)
def test_the_tee_propagates_source_errors_as_the_same_object(
    monkeypatch, tmp_path, error
) -> None:
    source = _Source([_BODY], raises=error)
    stream, _ = _tee(tmp_path, monkeypatch, source)

    async def drain():
        seen = []
        try:
            async for chunk in stream:
                seen.append(chunk)
        except BaseException as caught:
            return seen, caught
        raise AssertionError("no error")

    seen, caught = asyncio.run(drain())
    assert caught is error
    assert seen == [_BODY]

    asyncio.run(stream.aclose())
    assert source.closed == 1


# --- test 7: observer failure after a chunk was consumed ---------------------


def test_an_observer_failure_still_delivers_every_chunk_exactly_once(
    monkeypatch, tmp_path
) -> None:
    calls = {"n": 0}
    real = tt._SseObserver.feed

    def flaky(self, chunk):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("observer bug")
        return real(self, chunk)

    chunks = [b"data: first\n\n", b"data: second\n\n", b"data: third\n\n"]
    source = _Source(chunks)
    stream, runtime = _tee(tmp_path, monkeypatch, source)
    monkeypatch.setattr(tt._SseObserver, "feed", flaky)

    async def drain():
        out = [c async for c in stream]
        await stream.aclose()
        return out

    before = runtime.counters["observer_disabled"]
    assert asyncio.run(drain()) == chunks
    assert runtime.counters["observer_disabled"] > before
    assert calls["n"] == 2  # observation stayed off for the third chunk
    assert source.closed == 1


def test_an_observer_failure_over_http_leaves_bytes_and_chunk_marks(
    monkeypatch, tmp_path
) -> None:
    reply = sse_reply([_BODY, _BODY, SSE_DONE], chunk_delays=_DELAYS)

    async def off_run():
        async with TransportResponder([reply]) as responder:
            return await _raw_read(responder.base_url)

    _env(monkeypatch, None)
    off_chunks, _ = asyncio.run(off_run())

    def broken(self, chunk):
        raise RuntimeError("observer bug")

    monkeypatch.setattr(tt._SseObserver, "feed", broken)
    _env(monkeypatch, tmp_path)

    async def once():
        async with TransportResponder([reply]) as responder:
            return await _raw_read(responder.base_url)

    on_chunks, on_error = asyncio.run(once())
    assert on_error is None and on_chunks == off_chunks
    assert tt.get_runtime().counters["observer_disabled"] > 0
    names = _mark_names(tmp_path)
    assert names == ["first_body_chunk", "last_chunk"]


# --- test 8 (budget): a bomb and many tiny frames stop observation, chunk unchanged ---


def test_the_observer_refuses_a_gzip_bomb_before_inflating_it() -> None:
    observer = tt._SseObserver(47, lambda name: None)
    with pytest.raises(tt.ObservationBudgetExceeded):
        observer.feed(_bomb())


def test_the_observer_refuses_too_many_lines_and_an_unbounded_frame() -> None:
    with pytest.raises(tt.ObservationBudgetExceeded):
        tt._SseObserver(None, lambda name: None).feed(b":\n" * (tt.MAX_LINES_PER_CHUNK + 1))
    observer = tt._SseObserver(None, lambda name: None)
    with pytest.raises(tt.ObservationBudgetExceeded):
        observer.feed(b"data: " + b"x" * (tt.MAX_FRAME_BUFFER + 1))
    # Exactly at the line budget is fine.
    tt._SseObserver(None, lambda name: None).feed(b":\n" * tt.MAX_LINES_PER_CHUNK)


@pytest.mark.parametrize(
    "body, headers",
    [
        (_bomb(), {"Content-Encoding": "gzip"}),
        (b":\n" * 5000, {}),
        (b"data: " + b"x" * 300_000, {}),
    ],
    ids=["gzip_bomb", "many_tiny_frames", "huge_frame"],
)
def test_a_budget_breach_stops_observation_and_delivers_the_chunk_unchanged(
    monkeypatch, tmp_path, body, headers
) -> None:
    reply = sse_reply([body, SSE_DONE], headers=headers)
    (off_chunks, off_error), (on_chunks, on_error) = _off_and_on(reply, tmp_path, monkeypatch)
    assert off_error is None and on_error is None
    assert b"".join(on_chunks) == b"".join(off_chunks) == body + SSE_DONE
    notes = [r for r in _marks(tmp_path) if r["event"] == "delta_marks"]
    assert [n["delta_marks"] for n in notes] == ["unobservable(budget)"]
    names = [r["event"] for r in _marks(tmp_path)]
    assert names[0] == "first_body_chunk" and names[-1] == "last_chunk"
    assert not any(n.startswith("first_delta") for n in names)


def test_the_observer_decodes_utf8_split_across_chunks_into_one_character() -> None:
    seen: list[Any] = []
    real = tt._delta_channels
    tt._delta_channels = lambda payload: seen.append(payload) or real(payload)  # type: ignore[assignment]
    try:
        first, second, _ = _utf8_split()
        observer = tt._SseObserver(None, lambda name: None)
        observer.feed(first)
        observer.feed(second)
    finally:
        tt._delta_channels = real  # type: ignore[assignment]
    assert seen[0]["choices"][0]["delta"]["content"] == "caf\u00e9"


def test_the_observer_inflates_at_most_the_budget_per_chunk(monkeypatch) -> None:
    produced: list[int] = []
    real = zlib.decompressobj

    class Spy:
        def __init__(self, wbits):
            self._inner = real(wbits)

        def decompress(self, data, max_length=0):
            out = self._inner.decompress(data, max_length)
            produced.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(tt.zlib, "decompressobj", Spy)
    with pytest.raises(tt.ObservationBudgetExceeded):
        tt._SseObserver(47, lambda name: None).feed(_bomb())
    assert produced and max(produced) <= tt.DECOMPRESS_LIMIT


def test_an_empty_delta_marks_nothing_and_a_real_one_marks_once() -> None:
    marks: list[str] = []
    observer = tt._SseObserver(None, marks.append)
    observer.feed(_frame({"role": "assistant", "content": ""}))
    observer.feed(_frame({"reasoning": "", "tool_calls": []}))
    assert marks == []
    observer.feed(_frame({"content": "a"}))
    assert marks == ["first_delta.content"]


# --- M3: loop lag and hang snapshot (spec section 7; tests 3, 4 and 10) -------


def _call_events(directory: Path) -> list[str]:
    return [r["event"] for r in _records(directory, 1, event="http11.response_closed.complete")]


def _hang_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("hang_*.txt"))


def test_stalled_phase_is_derived_from_open_phases_before_failure_or_cleanup() -> None:
    started = "http11.receive_response_headers.started"
    assert tt.stalled_phase(["connection.connect_tcp.started"]) == "connection.connect_tcp.started"
    # Headers awaited, then a timeout: the failure and cleanup lines do not hide the phase.
    assert tt.stalled_phase(
        [
            "http11.send_request_headers.started",
            "http11.send_request_headers.complete",
            started,
            "http11.receive_response_headers.failed",
            "http11.response_closed.started",
            "http11.response_closed.complete",
        ]
    ) == started
    assert tt.stalled_phase(
        [
            "http11.receive_response_headers.started",
            "http11.receive_response_headers.complete",
            "http11.receive_response_body.started",
            "http11.response_closed.started",
        ]
    ) == "http11.receive_response_body.started"
    # Only tee marks: a first chunk with no last chunk is a stalled body.
    assert tt.stalled_phase(["first_body_chunk"]) == "first_body_chunk"
    assert tt.stalled_phase(["first_body_chunk", "last_chunk"]) is None
    assert tt.stalled_phase([]) is None
    # A phase that completed is not stalled.
    assert tt.stalled_phase(
        ["connection.connect_tcp.started", "connection.connect_tcp.complete"]
    ) is None


def test_a_stall_before_headers_snapshots_once_and_leaves_the_outcome_unchanged(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(tt.ENV_HANG_SECONDS, "0.2")

    async def provider_call_under_test(base_url: str) -> BaseException:
        client = openai.AsyncOpenAI(
            api_key="k",
            base_url=base_url,
            max_retries=0,
            timeout=0.8,
            **tt.sdk_client_kwargs(),
        )
        with tt.bind_cell_scope(
            run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
        ):
            with pytest.raises(openai.APITimeoutError) as caught:
                await client.chat.completions.create(
                    model="m", messages=[{"role": "user", "content": "x"}]
                )
        await client.close()
        return caught.value

    async def once():
        async with TransportResponder([json_reply({}, header_delay=3.0)]) as responder:
            return await provider_call_under_test(responder.base_url)

    _env(monkeypatch, None)
    off = asyncio.run(once())
    _env(monkeypatch, tmp_path)
    on = asyncio.run(once())

    assert type(on) is type(off) and str(on) == str(off)
    assert type(on.__cause__) is type(off.__cause__) is httpx.ReadTimeout
    assert tt.stalled_phase(_call_events(tmp_path)) == "http11.receive_response_headers.started"
    dumps = _hang_files(tmp_path)
    assert [d.name for d in dumps] == ["hang_1.txt"]
    text = dumps[0].read_text()
    assert "provider_call_under_test" in text
    assert text.startswith("tasks: ")
    # The snapshot is indexed in the call and process sidecars.
    assert "hang_snapshot" in _call_events(tmp_path)
    index = [
        json.loads(line)
        for line in next(tmp_path.rglob("process.jsonl")).read_text().splitlines()
    ]
    assert [r["file"] for r in index if r["event"] == "hang_dump"] == ["hang_1.txt"]


def test_a_call_that_ends_before_the_threshold_never_snapshots(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(tt.ENV_HANG_SECONDS, "0.5")
    _env(monkeypatch, tmp_path)

    async def main():
        async with TransportResponder([json_reply({}, header_delay=1.0)]) as responder:
            client = tt.build_http_client(timeout=httpx.Timeout(5.0, read=0.2))
            with tt.bind_cell_scope(
                run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
            ):
                with pytest.raises(httpx.ReadTimeout):
                    await client.post(responder.base_url + "/chat/completions")
            await asyncio.sleep(0.8)  # well past the threshold: the timer must be gone
            await client.aclose()

    asyncio.run(main())
    assert _call_events(tmp_path)
    assert _hang_files(tmp_path) == []


def test_headers_then_a_stalled_body_is_a_body_stall_with_no_snapshot(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(tt.ENV_HANG_SECONDS, "0.1")
    reply = sse_reply([_BODY, _BODY], chunk_delays=(0, 2.0))
    (off_chunks, off_error), (on_chunks, on_error) = _off_and_on(
        reply, tmp_path, monkeypatch, timeout=httpx.Timeout(5.0, read=0.5)
    )
    assert off_chunks == on_chunks == [_BODY]
    assert type(on_error) is type(off_error) is httpx.ReadTimeout
    assert tt.stalled_phase(_call_events(tmp_path)) == "http11.receive_response_body.started"
    assert _hang_files(tmp_path) == []


def test_the_lag_sampler_records_loop_drift_over_the_threshold(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tt, "LAG_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(tt, "LAG_THRESHOLD_SECONDS", 0.1)
    _env(monkeypatch, tmp_path)

    async def main():
        async with TransportResponder([json_reply({})]) as responder:
            client = tt.build_http_client()
            with tt.bind_cell_scope(
                run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
            ):
                await client.post(responder.base_url + "/chat/completions")
            await asyncio.sleep(0.06)
            time.sleep(0.4)  # block the loop: the sampler wakes late
            await asyncio.sleep(0.1)
            await client.aclose()

    asyncio.run(main())
    deadline = time.monotonic() + 5
    lags: list[dict[str, Any]] = []
    while not lags and time.monotonic() < deadline:
        time.sleep(0.05)
        lags = [
            r
            for line in next(tmp_path.rglob("process.jsonl")).read_text().splitlines()
            if (r := json.loads(line))["event"] == "loop_lag"
        ]
    assert lags and lags[0]["drift_seconds"] > 0.1


def test_two_consecutive_loops_each_start_and_cancel_their_own_sampler(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path)
    runtime = tt.get_runtime()
    seen: list[asyncio.Task] = []

    async def one_loop():
        client = tt.build_http_client()
        async with TransportResponder([json_reply({})]) as responder:
            with tt.bind_cell_scope(
                run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"
            ):
                await client.post(responder.base_url + "/chat/completions")
                await client.post(responder.base_url + "/chat/completions")
        lag_tasks = [
            t for t in asyncio.all_tasks() if t.get_name() == "aeread-transport-lag"
        ]
        assert len(lag_tasks) == 1  # one per loop, not one per call
        assert len(runtime.samplers) == 1
        seen.append(next(iter(runtime.samplers.values())))
        await client.aclose()

    asyncio.run(one_loop())
    asyncio.run(one_loop())
    assert len(seen) == 2 and seen[0] is not seen[1]
    assert all(task.cancelled() for task in seen)
    assert runtime.samplers == {}


# --- M3 addendum: execution id, strict off path, atomic producer ---------------


def _run_probe_cell(tmp_path: Path, seen: list[Any], evidence: str):
    from aeread_families.single_offer.runner import FixedResponseProvider

    class ScopeProbe(FixedResponseProvider):
        async def complete(self, request):
            seen.append(tt.current_scope())
            return await super().complete(request)

    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )
    return asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / evidence,
            prompt_sources=setup.prompt_sources,
            providers={"fake": ScopeProbe('{"offer":7}')},
            pricing=setup.pricing,
            harnesses=default_harnesses(),
        )
    )


def test_two_executions_of_one_cell_in_one_process_get_distinct_execution_ids(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path / "telemetry"))
    seen: list[Any] = []
    _run_probe_cell(tmp_path, seen, "first")
    _run_probe_cell(tmp_path, seen, "second")
    first, second = seen
    assert first.execution_id and second.execution_id
    assert first.execution_id != second.execution_id
    assert (first.run_plan_id, first.cell_id) == (second.run_plan_id, second.cell_id)


def test_with_telemetry_off_no_scope_is_bound_in_an_episode_or_a_client_call(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv(tt.ENV_DIR, raising=False)
    seen: list[Any] = []
    _run_probe_cell(tmp_path, seen, "off")
    assert seen == [None]

    with tt.bind_cell_scope(run_plan_id="p", cell_id="c", episode_attempt_id="a"):
        assert tt.current_scope() is None
        with tt.bind_call_scope(
            provider_call_id="x", provider_metadata=None, credential_fp=None
        ):
            assert tt.current_scope() is None


def test_a_producer_that_finds_the_lock_held_drops_and_counts_without_waiting(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path / "telemetry"))
    runtime = tt.get_runtime()
    scope = tt.CallScope("p", "c", "a", "e")
    dropped = runtime.counters["telemetry_dropped"]
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with runtime._producer_lock:
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(5)
    before = len(runtime.queue)
    started = time.monotonic()
    runtime.emit(scope, "probe", {})
    elapsed = time.monotonic() - started
    release.set()
    thread.join()
    assert elapsed < 0.5
    assert runtime.counters["telemetry_dropped"] == dropped + 1
    assert len(runtime.queue) <= before
