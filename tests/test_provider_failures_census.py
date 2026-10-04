"""The provider-failure census (#226 S1, spec section 8, test 12).

Telemetry inputs come from the real writer: in-process calls against the
scripted responder (a stall before headers, a stalled body, a budget-disabled
stream followed by a stall, two executions of one cell) and child processes
(one killed mid-stall, two alive together on one credential).  Run roots are
synthetic event logs in the kernel's on-disk shape, plus one written by the
kernel itself.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from aeread import cli
from aeread.shared_runner.model_call import transport_telemetry as tt
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.run import provider_failures
from aeread.shared_runner.task.execution import ProviderFailure, execute_plan_cell
from aeread_families.single_offer.runner import build_single_offer_smoke
from tests.transport_responder import (
    SSE_DONE,
    Reply,
    TransportResponder,
    json_reply,
    sse_reply,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HEADERS_PHASE = "http11.receive_response_headers.started"
BODY_PHASE = "http11.receive_response_body.started"


# --- synthetic run roots ------------------------------------------------------


def _artifact(attempt: Path, payload: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    path = attempt / "artifacts" / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return f"artifacts/sha256/{digest[:2]}/{digest}", digest


def _event(attempt: Path, sequence: int, event_type: str, payload: Any, **ids: Any) -> dict[str, Any]:
    ref, digest = _artifact(attempt, json.dumps(payload).encode())
    return {
        "event_id": f"e{sequence}",
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": ids.pop("occurred_at", "2026-10-04T09:15:00.000000Z"),
        "run_plan_id": "plan",
        "cell_id": "cell",
        "episode_id": "ep",
        "episode_attempt_id": "att",
        "phase_instance_id": None,
        "logical_action_id": ids.pop("logical_action_id", None),
        "action_attempt_id": None,
        "provider_call_id": ids.pop("provider_call_id", None),
        "tool_invocation_id": None,
        "visibility": "kernel",
        "payload_ref": ref,
        "payload_sha256": digest,
        "prior_event_hash": None,
        "event_hash": "h",
    }


def _failure_events(
    attempt: Path, *, start: int, condition: str, status: int | None, seat: str, model: str,
    occurred_at: str = "2026-10-04T09:15:00.000000Z",
) -> list[dict[str, Any]]:
    action, call = f"la{start}", f"call{start}"
    return [
        _event(attempt, start, "logical_action_started",
               {"profile_id": "p", "request": {"seat_id": seat}}, logical_action_id=action),
        _event(attempt, start + 1, "provider_call_started",
               {"request": {"provider": "openrouter", "model": model}},
               logical_action_id=action, provider_call_id=call),
        _event(attempt, start + 2, "provider_call_failed",
               {"failure_condition": condition, "status_code": status},
               logical_action_id=action, provider_call_id=call, occurred_at=occurred_at),
    ]


def _write_attempt(
    root: Path, name: str, events: list[dict[str, Any]], *, sealed: bool, tail: bytes = b""
) -> Path:
    attempt = root / "attempts" / name
    attempt.mkdir(parents=True, exist_ok=True)
    (attempt / "events.jsonl").write_bytes(
        b"".join(json.dumps(e).encode() + b"\n" for e in events) + tail
    )
    if sealed:
        (attempt / "events.jsonl.sealed.json").write_text("{}")
    return attempt


def _census(runs: list[Path], telemetry: list[Path] | None = None) -> dict[str, Any]:
    return provider_failures.build_report(runs, telemetry or [])


def _by_name(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {Path(a["attempt"]).name: a for a in report["attempts"]}


@pytest.fixture
def run_roots(tmp_path: Path) -> list[Path]:
    one, two = tmp_path / "run_one", tmp_path / "run_two"
    a1 = one / "attempts" / "sealed_clean"
    _write_attempt(
        one, "sealed_clean",
        _failure_events(a1, start=1, condition="provider_5xx", status=503, seat="seat_a", model="m1")
        + _failure_events(a1, start=11, condition="provider_5xx", status=502, seat="seat_a", model="m1",
                          occurred_at="2026-10-04T10:01:00.000000Z"),
        sealed=True,
    )
    a2 = one / "attempts" / "unsealed"
    _write_attempt(
        one, "unsealed",
        _failure_events(a2, start=1, condition="rate_limited", status=429, seat="seat_b", model="m2"),
        sealed=False,
    )
    a3 = two / "attempts" / "torn_tail"
    _write_attempt(
        two, "torn_tail",
        _failure_events(a3, start=1, condition="provider_5xx", status=503, seat="seat_a", model="m1"),
        sealed=True, tail=b'{"event_id": "e9", "sequ',
    )
    a4 = two / "attempts" / "corrupt_line"
    good = _failure_events(a4, start=1, condition="provider_5xx", status=503, seat="seat_a", model="m1")
    later = _failure_events(a4, start=11, condition="never_counted", status=500, seat="seat_a", model="m1")
    attempt = _write_attempt(two, "corrupt_line", good, sealed=True)
    with (attempt / "events.jsonl").open("ab") as handle:
        handle.write(b"not json\n")
        handle.write(b"".join(json.dumps(e).encode() + b"\n" for e in later))
    return [one, two]


def test_counts_by_condition_status_route_hour_and_seat(run_roots: list[Path]) -> None:
    report = _census(run_roots)
    # sealed_clean (2) + unsealed (1) + torn_tail prefix (1) + corrupt_line prefix (1).
    assert report["failures_total"] == 5
    assert report["by_failure_condition"] == {"provider_5xx": 4, "rate_limited": 1}
    assert report["by_status"] == {"429": 1, "502": 1, "503": 3}
    assert report["by_route"] == {"openrouter/m1": 4, "openrouter/m2": 1}
    assert report["by_hour"] == {"2026-10-04T09Z": 4, "2026-10-04T10Z": 1}
    assert report["by_seat"] == {"seat_a": 4, "seat_b": 1}


def test_labels_distinguish_unaudited_truncated_and_corrupt_logs(run_roots: list[Path]) -> None:
    attempts = _by_name(_census(run_roots))
    assert attempts["sealed_clean"]["labels"] == [] and attempts["sealed_clean"]["sealed"]
    assert attempts["unsealed"]["labels"] == ["unaudited"]
    assert attempts["torn_tail"]["labels"] == ["incomplete"]
    assert attempts["torn_tail"]["issues"] == ["truncated_tail"]
    assert attempts["corrupt_line"]["labels"] == ["incomplete"]
    assert attempts["corrupt_line"]["issues"] == ["corrupt"]


def test_a_seal_alone_does_not_make_a_damaged_log_audited(run_roots: list[Path]) -> None:
    # torn_tail is sealed, yet it carries a label: sealed is a fact, not a verdict.
    torn = _by_name(_census(run_roots))["torn_tail"]
    assert torn["sealed"] is True and torn["labels"] == ["incomplete"]


@pytest.mark.parametrize(
    "damage, issue",
    [
        ("missing", "payload_missing"),
        ("symlink", "payload_missing"),
        ("malformed", "payload_corrupt"),
        ("mismatch", "payload_digest_mismatch"),
    ],
)
def test_a_damaged_payload_is_reported_left_out_and_reading_continues(
    tmp_path: Path, damage: str, issue: str
) -> None:
    root = tmp_path / "run"
    attempt = root / "attempts" / "damaged"
    events = _failure_events(attempt, start=1, condition="provider_5xx", status=503, seat="seat_a", model="m1")
    events += _failure_events(attempt, start=11, condition="rate_limited", status=429, seat="seat_a", model="m1")
    victim = events[2]  # the first provider_call_failed
    path = attempt / victim["payload_ref"]
    if damage == "missing":
        path.unlink()
    elif damage == "symlink":
        content = path.read_bytes()
        path.unlink()
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_bytes(content)
        path.symlink_to(elsewhere)  # right bytes, but the artifact is not a plain file
    elif damage == "mismatch":
        path.write_bytes(b'{"failure_condition": "tampered"}')
    else:
        ref, digest = _artifact(attempt, b"{not json")
        victim["payload_ref"], victim["payload_sha256"] = ref, digest
    _write_attempt(root, "damaged", events, sealed=True)
    other = tmp_path / "other"
    _write_attempt(
        other, "fine",
        _failure_events(other / "attempts" / "fine", start=1, condition="timeout", status=None,
                        seat="seat_c", model="m3"),
        sealed=True,
    )
    report = _census([root, other])
    assert _by_name(report)["damaged"]["labels"] == ["incomplete"]
    assert _by_name(report)["damaged"]["issues"] == [issue]
    # The damaged event is out of the counts; the next event and the next root are read.
    assert report["by_failure_condition"] == {"rate_limited": 1, "timeout": 1}


def test_a_log_written_by_the_kernel_is_counted_with_its_seat(tmp_path: Path) -> None:
    class Failing:
        async def complete(self, request):
            raise ProviderFailure("provider_rejected", "bad request", retryable=False, status_code=400)

    setup = build_single_offer_smoke(provider="fake", model="fake-model", revision="fixed-v1")
    # The cell aborts on the failure and is left unsealed, as an interrupted run is.
    with pytest.raises(Exception, match="bad request"):
        asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=tmp_path / "run" / "attempts" / "real",
                prompt_sources=setup.prompt_sources,
                providers={"fake": Failing()},
                pricing=setup.pricing,
                harnesses=default_harnesses(),
            )
        )
    report = _census([tmp_path / "run"])
    assert report["by_failure_condition"] == {"provider_rejected": 1}
    assert report["by_status"] == {"400": 1}
    assert report["by_route"] == {"fake/fake-model": 1}
    (seat,) = report["by_seat"]
    assert seat and report["by_seat"][seat] == 1
    (attempt,) = report["attempts"]
    assert attempt["labels"] == ["unaudited"]


# --- telemetry from the real writer -------------------------------------------


def _call(base_url: str, call_id: str, fp: str, *, timeout: float):
    """Awaitable: one raw streaming call inside the current cell scope; errors are swallowed."""

    async def run() -> None:
        client = tt.build_http_client(timeout=timeout)
        try:
            with tt.bind_call_scope(provider_call_id=call_id, provider_metadata=None, credential_fp=fp):
                async with client.stream("POST", base_url + "/chat/completions") as response:
                    async for _ in response.aiter_raw():
                        pass
        except httpx.HTTPError:
            pass
        finally:
            await client.aclose()

    return run()


def _execution(coro_factory) -> None:
    async def main() -> None:
        with tt.bind_cell_scope(run_plan_id="plan", cell_id="cell", episode_attempt_id="att"):
            await coro_factory()

    asyncio.run(main())


def _frames(n: int) -> bytes:
    return b":\n" * n


@pytest.fixture(scope="module")
def telemetry_dir(tmp_path_factory) -> Path:
    """One in-process session: stalls, a budget stall, two executions of one cell."""

    directory = tmp_path_factory.mktemp("telemetry")
    os.environ[tt.ENV_DIR] = str(directory)
    try:
        # Execution A: call_1 stalls before headers (test 3), call_2 stalls in the body (test 4).
        async def execution_a() -> None:
            async with TransportResponder([json_reply({}, header_delay=3.0)]) as r:
                await _call(r.base_url, "call_1", "fp_in_process", timeout=0.4)
            async with TransportResponder(
                [sse_reply([b'data: {"choices": []}\n\n', SSE_DONE], chunk_delays=[0.0, 3.0])]
            ) as r:
                await _call(r.base_url, "call_2", "fp_in_process", timeout=0.4)
            # Observation stops (budget), then the stream stalls: progress is unknown.
            async with TransportResponder(
                [sse_reply([_frames(5000), SSE_DONE], chunk_delays=[0.0, 3.0])]
            ) as r:
                await _call(r.base_url, "call_3", "fp_in_process", timeout=0.4)

        # Execution B: the same cell, the same call id as call_1, and it succeeds.
        async def execution_b() -> None:
            async with TransportResponder([json_reply({"ok": True})]) as r:
                await _call(r.base_url, "call_1", "fp_in_process", timeout=5.0)

        _execution(execution_a)
        _execution(execution_b)
        tt.get_runtime().shutdown()
    finally:
        os.environ.pop(tt.ENV_DIR, None)
    return directory


def _hangs(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {h["provider_call_id"] + "@" + h["execution_id"]: h for h in report["hang_candidates"]}


def test_stalls_from_the_real_writer_are_hang_candidates_with_phase_and_duration(
    telemetry_dir: Path,
) -> None:
    report = _census([], [telemetry_dir])
    assert report["calls_traced"] == 4
    by_call = {}
    for hang in report["hang_candidates"]:
        by_call[hang["provider_call_id"]] = hang
    assert set(by_call) == {"call_1", "call_2", "call_3"}
    assert by_call["call_1"]["phase"] == HEADERS_PHASE
    assert by_call["call_1"]["status"] == "stalled_before_first_delta"
    assert by_call["call_2"]["phase"] == BODY_PHASE
    assert by_call["call_2"]["status"] == "stalled_before_first_delta"
    assert 0.2 < by_call["call_1"]["duration_seconds"] < 3.0


def test_a_budget_disabled_stream_then_a_stall_is_progress_unknown(telemetry_dir: Path) -> None:
    hang = next(h for h in _census([], [telemetry_dir])["hang_candidates"] if h["provider_call_id"] == "call_3")
    assert hang["status"] == "stalled_progress_unknown"
    assert hang["phase"] == BODY_PHASE


def test_an_observer_error_then_a_stall_is_progress_unknown(monkeypatch, tmp_path) -> None:
    import zlib

    monkeypatch.setenv(tt.ENV_DIR, str(tmp_path))
    # Raw deflate: the SDK's client decodes it, the observer's zlib wbits=15 cannot.
    compressor = zlib.compressobj(wbits=-15)
    delta = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    first = compressor.compress(delta) + compressor.flush(zlib.Z_SYNC_FLUSH)

    async def stalled() -> None:
        reply = sse_reply(
            [first, SSE_DONE], headers={"Content-Encoding": "deflate"}, chunk_delays=[0.0, 3.0]
        )
        async with TransportResponder([reply]) as r:
            await _call(r.base_url, "call_raw", "fp_raw", timeout=0.4)

    _execution(stalled)
    tt.get_runtime().shutdown()
    (hang,) = _census([], [tmp_path])["hang_candidates"]
    assert hang["provider_call_id"] == "call_raw"
    assert hang["status"] == "stalled_progress_unknown"
    assert hang["phase"] == BODY_PHASE


def test_two_executions_of_one_cell_are_separate_census_keys(telemetry_dir: Path) -> None:
    report = _census([], [telemetry_dir])
    call_1 = [h for h in report["hang_candidates"] if h["provider_call_id"] == "call_1"]
    # The stalled execution A is a candidate; the successful execution B, same
    # cell and same call id, is not merged into it.
    assert len(call_1) == 1
    sidecars = list(telemetry_dir.rglob("*.transport.jsonl"))
    assert len(sidecars) == 2
    executions = {p.name.split(".")[1] for p in sidecars}
    assert len(executions) == 2 and call_1[0]["execution_id"] in executions


def test_a_sealed_off_in_process_session_with_one_credential_has_no_overlap(telemetry_dir: Path) -> None:
    assert _census([], [telemetry_dir])["credential_overlaps"] == []


# --- torn and corrupt telemetry -----------------------------------------------


def test_torn_and_corrupt_telemetry_files_keep_their_valid_prefix(
    telemetry_dir: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(telemetry_dir, copy)
    base = copy / tt.HIDDEN_DIRNAME
    sidecars = sorted(base.rglob("*.transport.jsonl"))
    corrupt, torn = sorted(sidecars, key=lambda p: p.stat().st_size)  # torn = execution A
    torn_lines = torn.read_bytes().splitlines()
    torn.write_bytes(b"\n".join(torn_lines[:-1]) + b"\n" + torn_lines[-1][: len(torn_lines[-1]) // 2])
    corrupt_lines = corrupt.read_bytes().splitlines()
    corrupt.write_bytes(b"\n".join([*corrupt_lines[:3], b"garbage", *corrupt_lines[3:]]) + b"\n")
    report = _census([], [copy])
    issues = {Path(i["file"]).name: i["issue"] for i in report["telemetry_issues"]}
    assert issues == {torn.name: "truncated_tail", corrupt.name: "corrupt"}
    # Reading continued: the other file's stall is still found.
    assert any(h["provider_call_id"] == "call_2" for h in report["hang_candidates"])


# --- child processes: an abandoned session and overlapping sessions ------------

_CHILD = """
import asyncio, os, sys, time
from pathlib import Path
from aeread.shared_runner.model_call import transport_telemetry as tt
from aeread.shared_runner.task.execution import OpenRouterChatClient
from tests.test_transport_telemetry import OPENROUTER_BODY, _request_for
from tests.transport_responder import TransportResponder, json_reply

mode, mark, wait_for = sys.argv[1:4]

async def main():
    script = [json_reply({}, header_delay=600.0)] if mode == "stall" else [json_reply(OPENROUTER_BODY)]
    async with TransportResponder(script) as responder:
        client = OpenRouterChatClient(base_url=responder.base_url)
        with tt.bind_cell_scope(run_plan_id="plan_x", cell_id="cell_x", episode_attempt_id="attempt_x"):
            await client.complete(_request_for(responder.base_url))
asyncio.run(main())
Path(mark).write_text("up")
deadline = time.time() + 40
while wait_for != "-" and not Path(wait_for).exists() and time.time() < deadline:
    time.sleep(0.05)
"""


def _spawn(telemetry: Path, *args: str) -> subprocess.Popen:
    env = {
        **os.environ,
        "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}",
        "OPENROUTER_API_KEY": "sk-census-key",
        tt.ENV_DIR: str(telemetry),
    }
    return subprocess.Popen([sys.executable, "-c", _CHILD, *args], cwd=REPO_ROOT, env=env)


def _wait_for(predicate, what: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)


@pytest.fixture(scope="module")
def process_telemetry(tmp_path_factory) -> dict[str, Any]:
    directory = tmp_path_factory.mktemp("process_telemetry")
    marks = tmp_path_factory.mktemp("marks")
    stalled = _spawn(directory, "stall", str(marks / "never"), "-")
    _wait_for(
        lambda: any(
            HEADERS_PHASE in p.read_text() for p in directory.rglob("*.transport.jsonl")
        ),
        "the stalled child to reach the header wait",
    )
    stalled.kill()  # abandoned: no session_end
    stalled.wait()
    first = _spawn(directory, "ok", str(marks / "a"), str(marks / "b"))
    second = _spawn(directory, "ok", str(marks / "b"), str(marks / "a"))
    assert first.wait(60) == 0 and second.wait(60) == 0
    later = _spawn(directory, "ok", str(marks / "c"), "-")
    assert later.wait(60) == 0
    return {"directory": directory}


def _session_ids(directory: Path) -> dict[str, Path]:
    return {p.parent.name: p for p in (directory / tt.HIDDEN_DIRNAME).glob("*/process.jsonl")}


def test_an_abandoned_session_is_a_hang_candidate_and_has_no_session_end(
    process_telemetry: dict[str, Any],
) -> None:
    directory = process_telemetry["directory"]
    report = _census([], [directory])
    (hang,) = report["hang_candidates"]
    assert hang["phase"] == HEADERS_PHASE
    sessions = _session_ids(directory)
    assert len(sessions) == 4
    assert hang["session_id"] in sessions
    events = [json.loads(l)["event"] for l in sessions[hang["session_id"]].read_text().splitlines()]
    assert "session_end" not in events


def test_overlap_is_found_only_between_live_sessions_on_one_credential(
    process_telemetry: dict[str, Any],
) -> None:
    directory = process_telemetry["directory"]
    report = _census([], [directory])
    (overlap,) = report["credential_overlaps"]
    assert overlap["credential_fp"] == tt.credential_fingerprint("sk-census-key")
    (pair,) = overlap["session_pairs"]
    sessions = _session_ids(directory)
    abandoned = _census([], [directory])["hang_candidates"][0]["session_id"]
    assert len(pair) == 2 and abandoned not in pair and set(pair) <= set(sessions)


# --- output --------------------------------------------------------------------


def test_json_output_is_byte_stable_and_the_table_prints(
    run_roots: list[Path], telemetry_dir: Path, tmp_path: Path, capsys
) -> None:
    outputs = []
    for name in ("one.json", "two.json"):
        out = tmp_path / name
        code = provider_failures.main(
            ["--runs", *map(str, run_roots), "--telemetry", str(telemetry_dir), "--json", str(out)]
        )
        assert code == 0
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["schema"] == provider_failures.REPORT_SCHEMA
    capsys.readouterr()
    assert provider_failures.main(["--runs", *map(str, run_roots), "--telemetry", str(telemetry_dir)]) == 0
    text = capsys.readouterr().out
    assert "provider_5xx" in text and "stalled_progress_unknown" in text and "unaudited" in text


def test_the_census_does_not_write_into_its_inputs(run_roots: list[Path], telemetry_dir: Path) -> None:
    def snapshot() -> dict[str, bytes]:
        return {
            str(p): p.read_bytes()
            for root in [*run_roots, telemetry_dir]
            for p in sorted(root.rglob("*")) if p.is_file()
        }

    before = snapshot()
    _census(run_roots, [telemetry_dir])
    assert snapshot() == before


def test_the_verb_is_listed_and_dispatches_directly(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["aeread", "--help"])
    assert cli.main() == 0
    assert "provider-failures" in capsys.readouterr().out
    assert "provider-failures" in cli._DIRECT_VERBS
    monkeypatch.setattr(sys, "argv", ["aeread", "provider-failures", "--runs", "/nonexistent-root"])
    assert cli.main() == 0
    assert "provider failures: 0" in capsys.readouterr().out
