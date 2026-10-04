"""Opt-in transport telemetry for kernel-scoped live provider calls (#226, S1).

HL-O-07 hung inside a provider call and left no record of where in the
transport it stopped: connecting, sending, waiting for headers, or reading the
body.  This module records the httpcore trace phases of every call made inside
`execute_plan_cell`, so the next hang can be explained after the fact.

It is diagnostic only.  With `AEREAD_TRANSPORT_TELEMETRY_DIR` unset nothing in
here runs on a call path and the live clients build `AsyncOpenAI(...)` exactly
as before.  With it set, no result, event, receipt or exception changes: the
trace callback never raises, never awaits, and never waits on the writer
(a lock-free `deque` and one daemon writer thread; no `Queue`, no executor).

Files are written under `<dir>/.aeread-telemetry/<session_id>/`.  The hidden
component keeps publication from hashing them into a bundle manifest.
"""
from __future__ import annotations

import atexit
import codecs
import collections
import contextlib
import contextvars
import dataclasses
import asyncio
import hashlib
import itertools
import json
import os
import re
import sys
import threading
import time
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterator, Mapping, Sequence

ENV_DIR = "AEREAD_TRANSPORT_TELEMETRY_DIR"
SCHEMA = "aeread.transport_telemetry/0.2"
HIDDEN_DIRNAME = ".aeread-telemetry"
QUEUE_LIMIT = 10_000
POLL_SECONDS = 0.05
HEARTBEAT_SECONDS = 30.0
DRAIN_SECONDS = 2.0
ENV_HANG_SECONDS = "AEREAD_TRANSPORT_HANG_DUMP_SECONDS"
DEFAULT_HANG_SECONDS = 60.0
LAG_INTERVAL_SECONDS = 1.0
LAG_THRESHOLD_SECONDS = 0.1
# Hang snapshot bounds (spec section 7).
SNAPSHOT_MAX_TASKS = 200
SNAPSHOT_MAX_FRAMES = 30
_ROUTE_FIELDS = ("route_provider", "quantization", "canonical_model")
# Per-source-chunk observation budget (spec section 4): observing must not add
# unbounded work or memory before the chunk is yielded.
DECOMPRESS_LIMIT = 262_144
MAX_LINES_PER_CHUNK = 2_000
MAX_FRAME_BUFFER = 262_144
# Records the writer takes per pass before it writes them out and heartbeats.
DRAIN_BATCH = 1_000
# ... and the wall-clock share of one pass, so a slow disk cannot starve the loop.
DRAIN_BATCH_SECONDS = 0.05
# major.minor families the trace-extension names, the wrapper class and the tee were
# checked on; a patch release inside a family keeps telemetry on.
SUPPORTED_VERSIONS = (("openai", "2.53"), ("httpx", "0.28"), ("httpcore", "1.0"))

# One random id per process: two processes running the same cell never share a file.
SESSION_ID = uuid.uuid4().hex


@dataclasses.dataclass(frozen=True, slots=True)
class CallScope:
    """Immutable correlation snapshot; every record copies it at enqueue time."""

    run_plan_id: str
    cell_id: str
    episode_attempt_id: str
    # Telemetry-only, minted per `execute_plan_cell` entry: the same cell run
    # twice in one process must not share a sidecar. Kernel ids are unchanged.
    execution_id: str = ""
    provider_call_id: str | None = None
    route_provider: str | None = None
    quantization: str | None = None
    canonical_model: str | None = None
    credential_fp: str | None = None


_SCOPE: contextvars.ContextVar[CallScope | None] = contextvars.ContextVar(
    "aeread_transport_scope", default=None
)


def current_scope() -> CallScope | None:
    return _SCOPE.get()


@contextlib.contextmanager
def bind_cell_scope(
    *, run_plan_id: str, cell_id: str, episode_attempt_id: str
) -> Iterator[None]:
    token = None
    try:  # fail open: a telemetry-only failure here must not touch the cell
        if get_runtime() is not None:
            token = _SCOPE.set(
                CallScope(run_plan_id, cell_id, episode_attempt_id, uuid.uuid4().hex)
            )
    except Exception:
        _count_prep_failure()
        yield
        return
    if token is None:
        # Off path: touch nothing, so it stays identical to a build without telemetry.
        yield
        return
    try:
        yield
    finally:
        _SCOPE.reset(token)


@contextlib.contextmanager
def bind_call_scope(
    *,
    provider_call_id: str,
    provider_metadata: Mapping[str, Any] | None,
    credential_fp: str | None,
) -> Iterator[None]:
    """Add the call fields to the cell scope; outside a cell, bind nothing.

    A call with no cell scope stays untraced and is counted as `unscoped_calls`
    (canaries and admission probes are out of S1's scope).
    """

    parent = _SCOPE.get()
    if parent is None:
        yield
        return
    try:  # fail open: the provider call itself stays outside this catch
        route = {
            name: value
            for name in _ROUTE_FIELDS
            if isinstance(provider_metadata, Mapping)
            and isinstance(value := provider_metadata.get(name), str)
        }
        token = _SCOPE.set(
            dataclasses.replace(
                parent,
                provider_call_id=provider_call_id,
                credential_fp=credential_fp,
                **route,
            )
        )
    except Exception:
        _count_prep_failure()
        yield
        return
    try:
        yield
    finally:
        _SCOPE.reset(token)


def _count_prep_failure() -> None:
    with contextlib.suppress(Exception):
        runtime = get_runtime()
        if runtime is not None:
            runtime.count("telemetry_dropped")


def credential_fingerprint(api_key: str) -> str:
    """First 12 hex digits of the key's SHA-256; the key itself is never stored."""

    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _stderr(message: str) -> None:
    with contextlib.suppress(Exception):
        print(f"aeread transport telemetry: {message}", file=sys.stderr, flush=True)


def _wall() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _kernel_source_digest() -> str:
    """SHA-256 over this module's and `task/execution.py`'s bytes (writer thread only)."""

    digest = hashlib.sha256()
    try:
        here = Path(__file__).resolve()
        for path in (here, here.parents[1] / "task" / "execution.py"):
            digest.update(path.read_bytes())
    except OSError:
        return "unavailable"
    return digest.hexdigest()


class _Runtime:
    """Per-directory queue, counters and daemon writer thread."""

    def __init__(self, root: Path) -> None:
        self.session_dir = root / HIDDEN_DIRNAME / SESSION_ID
        self.queue: collections.deque[dict[str, Any]] = collections.deque()
        self.counters = {
            "telemetry_dropped": 0,
            "observer_disabled": 0,
            "unscoped_calls": 0,
            "writer_disabled": 0,
        }
        self._producer_lock = threading.Lock()
        self.credential_fps: set[str] = set()
        self.samplers: dict[Any, asyncio.Task[None]] = {}
        self._hang_ids = itertools.count(1)
        self.disabled = False
        self._stop = threading.Event()
        self._started_at = _wall()
        self.pid = os.getpid()
        self._kernel_digest = ""
        # Every filesystem operation happens on the writer thread, never on the
        # thread that builds the runtime or shuts it down.
        self._thread = threading.Thread(
            target=self._run, name="aeread-transport-writer", daemon=True
        )
        self._thread.start()
        atexit.register(self.shutdown)

    # -- producer side (event loop thread): never raises, never waits ----------

    def count(self, name: str) -> None:
        self.counters[name] += 1

    def _enqueue(self, item: dict[str, Any]) -> None:
        """Bounded append: the length check and append are one step, and a
        producer that finds the lock held drops and counts instead of waiting."""

        if not self._producer_lock.acquire(blocking=False):
            self.count("telemetry_dropped")
            return
        try:
            if len(self.queue) >= QUEUE_LIMIT:
                self.count("telemetry_dropped")
            else:
                self.queue.append(item)
        finally:
            self._producer_lock.release()

    def emit(self, scope: CallScope, event: str, fields: Mapping[str, Any]) -> None:
        if self.disabled or self.pid != os.getpid():
            return
        if scope.credential_fp:
            self.credential_fps.add(scope.credential_fp)
        self._enqueue(
            {
                **dataclasses.asdict(scope),
                "pid": os.getpid(),
                "session_id": SESSION_ID,
                "event": event,
                "mono": time.monotonic(),
                "wall": _wall(),
                **fields,
            }
        )

    def emit_process(self, event: str, **fields: Any) -> None:
        """Queue one process-sidecar record (loop lag, dump index) for the writer."""

        if self.disabled:
            return
        self._enqueue({"_kind": "process", "event": event, "fields": fields})

    def emit_hang(self, scope: CallScope, text: str) -> None:
        """Hand a hang snapshot to the writer as `hang_<n>.txt` in the session dir."""

        if self.disabled:
            return
        name = f"hang_{next(self._hang_ids)}.txt"
        self._enqueue(
            {
                "_kind": "hang",
                "file": name,
                "text": text,
                "scope": dataclasses.asdict(scope),
            }
        )
        self.emit(scope, "hang_snapshot", {"file": name})

    # -- consumer side (daemon thread) ---------------------------------------

    def _process_record(self, event: str, **extra: Any) -> None:
        record = {
            "event": event,
            "pid": os.getpid(),
            "session_id": SESSION_ID,
            "wall": _wall(),
            "credential_fps": sorted(self.credential_fps),
            "counters": dict(self.counters),
            **extra,
        }
        with (self.session_dir / "process.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _call_path(self, record: Mapping[str, Any]) -> Path:
        return (
            self.session_dir
            / str(record["run_plan_id"])
            / str(record["cell_id"])
            / f"{record['episode_attempt_id']}.{record['execution_id']}.transport.jsonl"
        )

    def _drain(self) -> None:
        batch: dict[Path, list[str]] = {}
        taken = 0
        started = time.monotonic()
        # A bounded pass (count and elapsed time): sustained producers cannot keep
        # it from writing.
        while (
            self.queue
            and taken < DRAIN_BATCH
            and (taken == 0 or time.monotonic() - started < DRAIN_BATCH_SECONDS)
        ):
            try:
                record = self.queue.popleft()
            except IndexError:  # shutdown cleared the queue under us
                break
            taken += 1
            kind = record.get("_kind")
            if kind in ("process", "hang"):
                # Records already consumed reach their sidecars before any other
                # filesystem work that may stall.
                self._write_calls(batch)
                batch = {}
            if kind == "process":
                self._process_record(record["event"], **record["fields"])
                continue
            if kind == "hang":
                (self.session_dir / record["file"]).write_text(
                    record["text"], encoding="utf-8"
                )
                self._process_record(
                    "hang_dump", file=record["file"], scope=record["scope"]
                )
                continue
            batch.setdefault(self._call_path(record), []).append(
                json.dumps(record, sort_keys=True, default=str)
            )
            event = str(record.get("event", ""))
            if ".send_request_" in event and event.endswith(".complete"):
                # The send boundary reaches disk before the next record is handled.
                self._write_calls(batch)
                batch = {}
        self._write_calls(batch)

    def _write_calls(self, batch: Mapping[Path, list[str]]) -> None:
        for path, lines in batch.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not path.exists()
            # Closed after every batch: a hang keeps its last phase on disk
            # within one poll (50 ms), well inside the 250 ms flush bound.
            with path.open("a", encoding="utf-8") as handle:
                if fresh:
                    handle.write(
                        json.dumps(
                            {
                                "schema": SCHEMA,
                                "pid": os.getpid(),
                                "session_id": SESSION_ID,
                                "started": self._started_at,
                                "kernel_source_sha256": self._kernel_digest,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                handle.write("\n".join(lines) + "\n")

    def _run(self) -> None:
        next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self._kernel_digest = _kernel_source_digest()
            self._process_record("session_start")
            while not self._stop.wait(POLL_SECONDS):
                while True:
                    self._drain()
                    if time.monotonic() >= next_heartbeat:
                        self._process_record("heartbeat")
                        next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
                    if not self.queue or self._stop.is_set():
                        break
            while self.queue:
                self._drain()
            self._process_record("session_end")
        except Exception as error:  # a write error never reaches a provider call
            self.disabled = True
            self.counters["writer_disabled"] = 1
            _stderr(
                f"writer disabled after {type(error).__name__}: {error}; telemetry disabled"
            )

    def shutdown(self) -> None:
        """Signal the writer and join it for at most 2 s; it writes `session_end`.

        This thread never touches the filesystem: a stuck writer is abandoned,
        and what it had not written is dropped and counted.
        """

        if self.pid != os.getpid():  # inherited across fork: not ours to stop
            return
        self._stop.set()
        self._thread.join(DRAIN_SECONDS)
        if self._thread.is_alive():
            self.counters["telemetry_dropped"] += len(self.queue)
            self.queue.clear()


_RUNTIMES: dict[str, _Runtime | None] = {}
_RUNTIMES_LOCK = threading.Lock()


def _installed_version(name: str) -> Any:
    """The version constant of the already-imported module: no filesystem read."""

    import importlib

    return importlib.import_module(name).__version__


def _unsupported_versions() -> list[str]:
    found = []
    for name, family in SUPPORTED_VERSIONS:
        try:
            version = _installed_version(name)
        except Exception:
            version = None
        if not isinstance(version, str):
            version = "unavailable"
        if ".".join(version.split(".")[:2]) != family:
            found.append(f"{name} {version} (supported {family}.x)")
    return found


def _open_runtime(value: str) -> _Runtime | None:
    root = Path(value)
    if not root.is_absolute():
        _stderr(f"{ENV_DIR}={value!r} is not absolute; telemetry disabled")
        return None
    unsupported = _unsupported_versions()
    if unsupported:
        _stderr(f"unsupported versions: {', '.join(unsupported)}; telemetry disabled")
        return None
    try:
        return _Runtime(root)
    except Exception as error:
        _stderr(f"{ENV_DIR}={value!r} is not writable ({error}); telemetry disabled")
        return None


def get_runtime() -> _Runtime | None:
    """The runtime for the configured directory, or None when telemetry is off.

    A bad directory disables telemetry with exactly one stderr line (the
    verdict is cached) and never raises into a client.
    """

    value = os.environ.get(ENV_DIR)
    if not value or _CHILD_DISABLED:
        return None
    with _RUNTIMES_LOCK:
        if value not in _RUNTIMES:
            _RUNTIMES[value] = _open_runtime(value)
        runtime = _RUNTIMES[value]
    return None if runtime is None or runtime.disabled else runtime


_CHILD_DISABLED = False


def _reset_after_fork() -> None:
    """A forked child shares no session, runtime, writer thread or held lock."""

    global SESSION_ID, _RUNTIMES_LOCK, _CHILD_DISABLED
    # Reset everything inherited first: minting the new id is the fallible step.
    _RUNTIMES_LOCK = threading.Lock()
    _RUNTIMES.clear()
    _SCOPE.set(None)
    try:
        SESSION_ID = uuid.uuid4().hex
        _CHILD_DISABLED = False
    except Exception:
        _CHILD_DISABLED = True


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def telemetry_enabled() -> bool:
    return get_runtime() is not None


def stalled_phase(events: Sequence[str]) -> str | None:
    """The phase a call was stuck in, derived from its ordered event names.

    The last `*.started` with no matching `.complete`, taken before any failure
    or cleanup event (`*.failed`, `response_closed.*`): the trace ends with
    cleanup lines after a timeout, so the last line is never the phase.  Waiting
    for headers is `...receive_response_headers.started`; a stalled body is
    `...receive_response_body.started`, or `first_body_chunk` when only the tee
    marks show it (chunk seen, no `last_chunk`).  None when nothing was open.
    """

    open_phases: list[str] = []
    chunk_seen = False
    finished = False
    ended = sent = dead = False
    for name in events:
        stem, _, kind = name.rpartition(".")
        # A redirect or retry is a new exchange: only the last one can be stalled.
        if kind == "started" and not stem.endswith("response_closed") and (
            ended or (stem.endswith("send_request_headers") and sent)
        ):
            open_phases, chunk_seen, finished = [], False, False
            ended = sent = dead = False
        if dead:
            continue
        if stem.endswith("send_request_headers") and kind == "started":
            sent = True
        if kind == "failed" or stem.endswith("response_closed"):
            dead = True
            ended = ended or stem.endswith("response_closed")
            continue
        if kind == "started":
            open_phases.append(stem)
        elif kind == "complete":
            if stem in open_phases:
                del open_phases[len(open_phases) - 1 - open_phases[::-1].index(stem)]
        elif name == "first_body_chunk":
            chunk_seen = True
        elif name == "last_chunk":
            finished = True
    if open_phases:
        return f"{open_phases[-1]}.started"
    return "first_body_chunk" if chunk_seen and not finished else None


def _hang_seconds() -> float:
    try:
        value = float(os.environ.get(ENV_HANG_SECONDS, DEFAULT_HANG_SECONDS))
    except ValueError:
        return DEFAULT_HANG_SECONDS
    return value if value > 0 else DEFAULT_HANG_SECONDS


def _coroutine_frames(coro: Any) -> list[Any]:
    """Frames of a suspended coroutine chain, outermost first (`get_stack` gives one)."""

    frames: list[Any] = []
    while coro is not None and len(frames) < SNAPSHOT_MAX_FRAMES:
        frame = (
            getattr(coro, "cr_frame", None)
            or getattr(coro, "ag_frame", None)
            or getattr(coro, "gi_frame", None)
        )
        if frame is not None:
            frames.append(frame)
        coro = (
            getattr(coro, "cr_await", None)
            or getattr(coro, "ag_await", None)
            or getattr(coro, "gi_yieldfrom", None)
        )
    return frames


def task_snapshot(loop: asyncio.AbstractEventLoop) -> str:
    """Bounded text of `asyncio.all_tasks(loop)` stacks; must run on the loop."""

    tasks = sorted(asyncio.all_tasks(loop), key=lambda task: task.get_name())
    lines = [f"tasks: {len(tasks)} (showing {min(len(tasks), SNAPSHOT_MAX_TASKS)})"]
    for task in tasks[:SNAPSHOT_MAX_TASKS]:
        lines.append(f"task {task.get_name()} {task.get_coro()!r}")
        for frame in _coroutine_frames(task.get_coro()):
            code = frame.f_code
            lines.append(f"  {code.co_filename}:{frame.f_lineno} in {code.co_name}")
    return "\n".join(lines) + "\n"


async def _lag_sampler(runtime: _Runtime) -> None:
    """Record event-loop drift over the threshold; cancelled with the loop's tasks."""

    while True:
        before = time.monotonic()
        await asyncio.sleep(LAG_INTERVAL_SECONDS)
        drift = time.monotonic() - before - LAG_INTERVAL_SECONDS
        if drift > LAG_THRESHOLD_SECONDS:
            runtime.emit_process("loop_lag", drift_seconds=round(drift, 3))


def ensure_lag_sampler(runtime: _Runtime) -> None:
    """Start this loop's sampler on the first traced call; a new loop gets its own."""

    loop = asyncio.get_running_loop()
    if loop in runtime.samplers:
        return
    task = loop.create_task(_lag_sampler(runtime), name="aeread-transport-lag")
    runtime.samplers[loop] = task
    # Dropping the entry also drops the loop reference once asyncio.run cancels it.
    task.add_done_callback(lambda _: runtime.samplers.pop(loop, None))


class _CallTrace:
    """Per-request trace callback: httpcore awaits it inline, so it must not block."""

    def __init__(self, runtime: _Runtime, scope: CallScope) -> None:
        self._runtime = runtime
        self.scope = scope
        self._connected = False
        self._reused: bool | str = "unknown"
        self._hang_timer: asyncio.TimerHandle | None = None

    def _cancel_hang_timer(self) -> None:
        if self._hang_timer is not None:
            self._hang_timer.cancel()
            self._hang_timer = None

    def _hang_fired(self) -> None:
        """Loop timer: no headers by now (it is cancelled on headers), so snapshot."""

        self._hang_timer = None  # one-shot: at most one snapshot per call
        try:
            self._runtime.emit_hang(
                self.scope, task_snapshot(asyncio.get_running_loop())
            )
        except Exception:
            self._runtime.count("telemetry_dropped")

    def _watch(self, phase: str, kind: str) -> None:
        if phase == "send_request_headers" and kind == "complete":
            if self._hang_timer is None:
                self._hang_timer = asyncio.get_running_loop().call_later(
                    _hang_seconds(), self._hang_fired
                )
        elif phase == "receive_response_headers" and kind == "complete":
            self._cancel_hang_timer()
        elif kind == "failed" or phase == "response_closed":
            self._cancel_hang_timer()

    async def __call__(self, name: str, info: Mapping[str, Any]) -> None:
        try:
            # httpcore names are "<layer>.<phase>.<started|complete|failed>",
            # e.g. "connection.connect_tcp.started"; recorded raw, matched on phase.
            phase = name.rpartition(".")[0].rpartition(".")[2]
            kind = name.rpartition(".")[2]
            fields: dict[str, Any] = {}
            if phase == "connect_tcp" and kind == "started":
                self._connected = True
                self._reused = False
            elif (
                phase == "send_request_headers"
                and kind == "started"
                and not self._connected
            ):
                self._reused = True
            if phase == "receive_response_headers" and kind == "complete":
                status = _status_of(info.get("return_value"))
                if status is not None:
                    fields["status"] = status
            fields["connection_reused"] = self._reused
            self._runtime.emit(self.scope, name, fields)
            self._watch(phase, kind)
        except Exception:
            self._runtime.count("telemetry_dropped")


class ObservationBudgetExceeded(Exception):
    """A chunk would cost more to observe than the per-chunk budget allows."""


# Content-Encoding value -> zlib wbits; anything else is unobservable.
_ZLIB_WBITS = {"": None, "identity": None, "gzip": 47, "x-gzip": 47, "deflate": 15}
_LINE_BREAK = re.compile(r"\r\n|\n|\r")
# Responses-API streaming events carry the channel in the event type instead.
_RESPONSES_CHANNELS = {
    "response.output_text.delta": "content",
    "response.reasoning_summary_text.delta": "reasoning",
    "response.reasoning_text.delta": "reasoning",
    "response.function_call_arguments.delta": "tool_args",
}


def _nonempty(value: Any) -> bool:
    return bool(value) and value != []


def _delta_channels(payload: Any) -> list[str]:
    """Channels in which one SSE data frame carries a non-empty value."""

    if not isinstance(payload, dict):
        return []
    channel = _RESPONSES_CHANNELS.get(str(payload.get("type")))
    if channel is not None:
        return [channel] if _nonempty(payload.get("delta")) else []
    found: list[str] = []
    choices = payload.get("choices")
    delta = choices[0].get("delta") if isinstance(choices, list) and choices else None
    if not isinstance(delta, dict):
        return found
    if _nonempty(delta.get("content")):
        found.append("content")
    if any(
        _nonempty(delta.get(key))
        for key in ("reasoning", "reasoning_content", "reasoning_details")
    ):
        found.append("reasoning")
    calls = delta.get("tool_calls")
    if isinstance(calls, list) and any(
        isinstance(call, dict)
        and isinstance(call.get("function"), dict)
        and _nonempty(call["function"].get("arguments"))
        for call in calls
    ):
        found.append("tool_args")
    return found


class _SseObserver:
    """Decode, frame and inspect a copy of the body; raises only on budget or bugs."""

    def __init__(self, wbits: int | None, mark: Callable[[str], None]) -> None:
        self._inflater = None if wbits is None else zlib.decompressobj(wbits)
        # "replace": a malformed byte must not end observation of the stream.
        self._text = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._mark = mark
        self._buffer = ""
        self._data: list[str] = []
        self._data_size = 0

    def feed(self, chunk: bytes) -> None:
        data = chunk
        if self._inflater is not None:
            data = self._inflater.decompress(chunk, DECOMPRESS_LIMIT)
            if self._inflater.unconsumed_tail:
                raise ObservationBudgetExceeded("decompression")
        self._buffer += self._text.decode(data)
        # A trailing CR may be the first half of CRLF: hold it for the next chunk.
        held = "\r" if self._buffer.endswith("\r") else ""
        lines = _LINE_BREAK.split(self._buffer[: len(self._buffer) - len(held)])
        self._buffer = lines.pop() + held
        if len(lines) > MAX_LINES_PER_CHUNK:
            raise ObservationBudgetExceeded("lines")
        for line in lines:
            self._line(line)
        if len(self._buffer.encode("utf-8")) + self._data_size > MAX_FRAME_BUFFER:
            raise ObservationBudgetExceeded("frame buffer")

    def _line(self, line: str) -> None:
        # Every accumulated line counts, comments and ignored fields included.
        if len(line.encode("utf-8")) + self._data_size > MAX_FRAME_BUFFER:
            raise ObservationBudgetExceeded("frame buffer")
        if not line:
            self._dispatch()
        elif line.startswith(":"):
            self._mark("keepalive")
        elif line.startswith("data:"):
            value = line[5:]
            value = value[1:] if value.startswith(" ") else value
            self._data.append(value)
            self._data_size += len(value.encode("utf-8"))
            if self._data_size > MAX_FRAME_BUFFER:
                raise ObservationBudgetExceeded("frame buffer")

    def _dispatch(self) -> None:
        data, self._data, self._data_size = "\n".join(self._data), [], 0
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except ValueError:
            return
        for channel in _delta_channels(payload):
            self._mark(f"first_delta.{channel}")


def _make_stream_class() -> type:
    # httpx checks `isinstance(stream, AsyncByteStream)`; imported lazily so the
    # telemetry-off path never pays for it.
    import httpx

    class ObservedStream(httpx.AsyncByteStream):
        """Tee over the response's raw byte stream (an `httpx.AsyncByteStream`).

        Every chunk is yielded exactly once, unmodified.  Observation works on the
        chunk after it is held for yielding; its failures are caught and counted
        and only switch observation off.  Source exceptions (including
        `CancelledError`) pass through as the same object, and `aclose()` always
        reaches the source.
        """

        def __init__(
            self,
            source: Any,
            runtime: _Runtime,
            scope: CallScope,
            *,
            sse: bool,
            content_encoding: str,
        ) -> None:
            self._source = source
            self._runtime = runtime
            self._scope = scope
            self._seen: set[str] = set()
            self._observer: _SseObserver | None = None
            if sse:
                encodings = [e.strip().lower() for e in content_encoding.split(",")]
                encoding = content_encoding.strip().lower()
                if len(encodings) == 1 and encoding in _ZLIB_WBITS:
                    self._observer = _SseObserver(_ZLIB_WBITS[encoding], self._mark)
                else:
                    self._emit("delta_marks", delta_marks=f"unobservable(encoding={encoding})")

        def _emit(self, event: str, **fields: Any) -> None:
            try:
                self._runtime.emit(self._scope, event, fields)
            except Exception:
                self._runtime.count("telemetry_dropped")

        def _mark(self, name: str) -> None:
            if name not in self._seen:
                self._seen.add(name)
                self._emit(name)

        def _observe(self, chunk: bytes) -> None:
            if chunk:
                self._mark("first_body_chunk")
            if self._observer is None or not chunk:
                return
            try:
                self._observer.feed(chunk)
            except ObservationBudgetExceeded:
                self._observer = None
                self._emit("delta_marks", delta_marks="unobservable(budget)")
            except Exception:
                self._observer = None
                self._runtime.count("observer_disabled")
                self._emit("delta_marks", delta_marks="unobservable(observer_error)")

        async def __aiter__(self) -> AsyncIterator[bytes]:
            async for chunk in self._source:
                self._observe(chunk)
                yield chunk
            self._emit("last_chunk")

        async def aclose(self) -> None:
            await self._source.aclose()

    return ObservedStream


_STREAM_CLASS: type | None = None


def observed_stream_class() -> type:
    global _STREAM_CLASS
    if _STREAM_CLASS is None:
        _STREAM_CLASS = _make_stream_class()
    return _STREAM_CLASS


def _status_of(return_value: Any) -> int | None:
    if isinstance(return_value, tuple) and len(return_value) >= 2:
        status = return_value[1]
        return status if isinstance(status, int) else None
    return None


def _make_client_class() -> type:
    import httpx

    # Activation is limited to the checked SDK version, which has this wrapper.
    from openai._base_client import AsyncHttpxClientWrapper as base

    class TelemetryHttpClient(base):  # type: ignore[valid-type, misc]
        """The SDK's default async client plus the trace hooks."""

        def __init__(self, runtime: _Runtime, **kwargs: Any) -> None:
            async def on_request(request: httpx.Request) -> None:
                try:
                    if runtime.pid != os.getpid():  # runtime inherited across fork
                        return
                    scope = _SCOPE.get()
                    if scope is None:
                        runtime.count("unscoped_calls")
                        return
                    request.extensions["trace"] = _CallTrace(runtime, scope)
                    ensure_lag_sampler(runtime)
                except Exception:
                    runtime.count("telemetry_dropped")

            async def on_response(response: httpx.Response) -> None:
                try:
                    trace = response.request.extensions.get("trace")
                    if not isinstance(trace, _CallTrace):
                        return
                    headers = response.headers
                    response.stream = observed_stream_class()(
                        response.stream,
                        runtime,
                        trace.scope,
                        sse=headers.get("content-type", "")
                        .lower()
                        .startswith("text/event-stream"),
                        content_encoding=headers.get("content-encoding", ""),
                    )
                except Exception:
                    runtime.count("telemetry_dropped")

            hooks = kwargs.setdefault("event_hooks", {})
            hooks["request"] = [*hooks.get("request", []), on_request]
            hooks["response"] = [*hooks.get("response", []), on_response]
            super().__init__(**kwargs)

    return TelemetryHttpClient


_CLIENT_CLASS: type | None = None


def telemetry_client_class() -> type:
    global _CLIENT_CLASS
    if _CLIENT_CLASS is None:
        _CLIENT_CLASS = _make_client_class()
    return _CLIENT_CLASS


def build_http_client(**kwargs: Any) -> Any | None:
    """A telemetry `httpx.AsyncClient`, or None when telemetry is off.

    Any failure to build one (for example an SDK without the wrapper's
    expected constructor) disables telemetry for this client rather than risk
    the call.
    """

    try:
        runtime = get_runtime()
        if runtime is None:
            return None
        return telemetry_client_class()(runtime, **kwargs)
    except Exception as error:
        _stderr(f"cannot build the telemetry client ({error}); telemetry disabled")
        return None


def sdk_client_kwargs() -> dict[str, Any]:
    """Extra `AsyncOpenAI(...)` kwargs: empty when telemetry is off (today's call)."""

    client = build_http_client()
    return {} if client is None else {"http_client": client}


def credential_fp_if_enabled(api_key: str) -> str | None:
    try:
        return credential_fingerprint(api_key) if telemetry_enabled() else None
    except Exception:
        _count_prep_failure()
        return None


__all__ = [
    "CallScope",
    "ENV_DIR",
    "SCHEMA",
    "SESSION_ID",
    "bind_call_scope",
    "bind_cell_scope",
    "build_http_client",
    "credential_fingerprint",
    "credential_fp_if_enabled",
    "current_scope",
    "get_runtime",
    "observed_stream_class",
    "ensure_lag_sampler",
    "sdk_client_kwargs",
    "stalled_phase",
    "task_snapshot",
    "telemetry_client_class",
    "telemetry_enabled",
]
