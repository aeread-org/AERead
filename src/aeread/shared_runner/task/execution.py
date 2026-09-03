"""Task-attempt execution and append-only evidence for the AERead runner.

This layer turns an R3 ``DecisionRequest`` into a ``CanonicalResponse`` while
making logical actions, declared attempts, provider calls, tools, failures,
budgets, artifacts, and retry ownership explicit. It also publishes and verifies
durable evaluation receipts once a family adapter supplies its typed score or
failure. Family-specific state reconstruction, transition replay, and scoring remain
adapter responsibilities.
"""
from __future__ import annotations

import asyncio
import dataclasses
import fcntl
import hashlib
import inspect
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, Protocol, Sequence

from ..registry import PluginRegistry, PluginRegistryError
from ..run.resolver import RunPlan, canonical_json_bytes, verify_run_plan, write_run_plan
from .scheduler import (
    DecisionRequest,
    EpisodeResult,
    PhaseInstance,
    PhaseSpec,
    TransitionResult,
    episode_id_for_cell,
    run_episode,
)
from ..schemas import AgentProfile

if TYPE_CHECKING:
    # `harness.py` imports `ProviderRequest`/`ProviderResult` from this module,
    # so the reverse reference is type-checking only; call sites that need the
    # classes at runtime (harness registration, native tool-call construction)
    # import them lazily.
    from ..model_call.harness import CanonicalMessage, Harness, NativeToolCall, ToolSchema


class EvidenceIntegrityError(RuntimeError):
    """Evidence, pins, or budgets cannot support a valid execution."""


class ProviderFailure(RuntimeError):
    """Typed provider failure visible to the action-attempt retry policy."""

    def __init__(
        self,
        condition: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        if not isinstance(condition, str) or not condition:
            raise ValueError("ProviderFailure.condition must be a non-empty string")
        self.condition = condition
        self.retryable = bool(retryable)
        self.status_code = status_code


class ToolFailure(RuntimeError):
    """A known tool failure, including failures after a partial mutation."""

    def __init__(self, condition: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        if not isinstance(condition, str) or not condition:
            raise ValueError("ToolFailure.condition must be a non-empty string")
        self.condition = condition
        self.retryable = bool(retryable)
        self.record: ToolInvocationRecord | None = None


class ConcurrentEvidenceWriterError(EvidenceIntegrityError):
    """Another process or object already owns the evidence writer lock."""


class EvidenceSealedError(EvidenceIntegrityError):
    """A sealed evidence generation cannot accept more events or artifacts."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_sha256_bytes(canonical_json_bytes(value))[:20]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write while persisting evidence")
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    sha256: str
    size_bytes: int
    media_type: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    sequence: int
    event_type: str
    occurred_at: str
    run_plan_id: str
    cell_id: str
    episode_id: str
    episode_attempt_id: str
    phase_instance_id: str | None
    logical_action_id: str | None
    action_attempt_id: str | None
    provider_call_id: str | None
    tool_invocation_id: str | None
    visibility: str
    payload_ref: str
    payload_sha256: str
    prior_event_hash: str | None
    event_hash: str


@dataclass(frozen=True, slots=True)
class EvidenceSeal:
    run_plan_id: str
    cell_id: str
    episode_id: str
    episode_attempt_id: str
    event_count: int
    artifact_count: int
    event_root_sha256: str
    artifact_root_sha256: str


def _event_hash_payload(event: Event | Mapping[str, Any]) -> Mapping[str, Any]:
    if dataclasses.is_dataclass(event):
        value = {
            field.name: getattr(event, field.name) for field in dataclasses.fields(event)
        }
    else:
        value = dict(event)
    value.pop("event_hash", None)
    return value


class EvidenceStore:
    """Durable single-writer event chain and content-addressed artifacts."""

    _TERMINAL_SUFFIXES = {
        "succeeded",
        "failed",
        "outcome_unknown",
        "agent_action_failure",
    }
    _NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

    def __init__(
        self,
        root: str | Path,
        *,
        run_plan_id: str,
        cell_id: str,
        episode_id: str,
        episode_attempt_id: str,
        clock: Callable[[], str] = _utc_now,
        resume: bool = False,
    ) -> None:
        self.root = Path(root)
        if self.root.is_symlink():
            raise EvidenceIntegrityError("evidence root must be a real directory")
        existed = self.root.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or self.root.is_symlink():
            raise EvidenceIntegrityError("evidence root must be a real directory")
        if not existed:
            _fsync_directory(self.root.parent)
        self.artifacts_dir = self.root / "artifacts" / "sha256"
        self.events_path = self.root / "events.jsonl"
        self.seal_path = self.root / "events.jsonl.sealed.json"
        self.run_plan_id = run_plan_id
        self.cell_id = cell_id
        self.episode_id = episode_id
        self.episode_attempt_id = episode_attempt_id
        self._clock = clock
        self._sequence = 0
        self._prior_hash: str | None = None
        self._closed = False
        self._sealed = False
        self._read_only = False
        self._lock_fd: int | None = None
        self._events_inode: tuple[int, int] | None = None
        self._acquire_writer_lock()
        try:
            self._open_or_create_events(resume=resume)
            if resume:
                self.verify_chain()
                events = self.read_events()
                self._sequence = len(events)
                self._prior_hash = None if not events else events[-1].event_hash
            if os.path.lexists(self.seal_path):
                self._sealed = True
                sealed = self._load_seal()
                if sealed != self._compute_seal():
                    raise EvidenceIntegrityError(
                        "seal marker does not match the durable evidence generation"
                    )
        except Exception:
            self.close()
            raise

    def _acquire_writer_lock(self) -> None:
        lock_path = self.root / ".writer.lock"
        try:
            fd = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | self._NOFOLLOW,
                0o600,
            )
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("writer lock is not a regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                os.close(fd)
                raise ConcurrentEvidenceWriterError(
                    f"existing event log is owned by another writer: {self.root}"
                ) from error
        except ConcurrentEvidenceWriterError:
            raise
        except OSError as error:
            raise EvidenceIntegrityError("cannot acquire evidence writer lock") from error
        self._lock_fd = fd
        _fsync_directory(self.root)

    def _open_or_create_events(self, *, resume: bool) -> None:
        if os.path.lexists(self.events_path):
            info = os.lstat(self.events_path)
            if not stat.S_ISREG(info.st_mode):
                raise EvidenceIntegrityError("event log must be a non-symlink regular file")
            if not resume:
                raise EvidenceIntegrityError(
                    f"refusing to append to an existing event log without resume=True: "
                    f"{self.events_path}"
                )
            self._events_inode = (info.st_dev, info.st_ino)

    def _open_bound_events(self, flags: int) -> int:
        self._ensure_open()
        if self._events_inode is None:
            if not (flags & (os.O_WRONLY | os.O_RDWR)):
                raise EvidenceIntegrityError("event log has not been created")
            try:
                fd = os.open(
                    self.events_path,
                    flags | os.O_CREAT | os.O_EXCL | self._NOFOLLOW,
                    0o600,
                )
            except OSError as error:
                raise EvidenceIntegrityError("cannot create bound event log") from error
            info = os.fstat(fd)
            self._events_inode = (info.st_dev, info.st_ino)
            _fsync_directory(self.root)
            return fd
        try:
            fd = os.open(self.events_path, flags | self._NOFOLLOW)
        except OSError as error:
            raise EvidenceIntegrityError("event log is missing or unsafe") from error
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != self._events_inode:
            os.close(fd)
            raise EvidenceIntegrityError("event log binding changed during execution")
        return fd

    def _ensure_open(self) -> None:
        if self._closed:
            raise EvidenceIntegrityError("evidence store is closed")

    def _ensure_writable(self) -> None:
        self._ensure_open()
        if self._read_only:
            raise EvidenceIntegrityError("audited evidence is read-only")
        if self._sealed or os.path.lexists(self.seal_path):
            self._sealed = True
            raise EvidenceSealedError("sealed evidence cannot accept writes")

    def close(self) -> None:
        if self._closed:
            return
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None
        self._closed = True

    def __enter__(self) -> "EvidenceStore":
        self._ensure_open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best-effort process cleanup
        try:
            self.close()
        except Exception:
            pass

    @classmethod
    def audit_existing(cls, root: str | Path) -> "EvidenceStore":
        """Open an immutable evidence directory and verify its full event chain."""

        instance = object.__new__(cls)
        instance.root = Path(root)
        if instance.root.is_symlink():
            raise EvidenceIntegrityError("evidence root must be a real directory")
        instance.artifacts_dir = instance.root / "artifacts" / "sha256"
        instance.events_path = instance.root / "events.jsonl"
        instance.seal_path = instance.root / "events.jsonl.sealed.json"
        if not instance.root.is_dir() or not instance.events_path.is_file():
            raise EvidenceIntegrityError(
                f"existing evidence is incomplete at {instance.root}"
            )
        try:
            info = os.lstat(instance.events_path)
        except OSError as error:
            raise EvidenceIntegrityError("event log is missing or unsafe") from error
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceIntegrityError("event log must be a non-symlink regular file")
        instance._events_inode = (info.st_dev, info.st_ino)
        instance._closed = False
        instance._sealed = os.path.lexists(instance.seal_path)
        instance._read_only = True
        instance._lock_fd = None
        instance._sequence = 0
        instance._prior_hash = None
        events = instance.read_events()
        if not events:
            raise EvidenceIntegrityError("existing evidence contains no identity-bearing event")
        first = events[0]
        instance.run_plan_id = first.run_plan_id
        instance.cell_id = first.cell_id
        instance.episode_id = first.episode_id
        instance.episode_attempt_id = first.episode_attempt_id
        instance._sequence = len(events)
        instance._prior_hash = events[-1].event_hash
        instance.audit_reconciliation()
        if instance._sealed and instance._load_seal() != instance._compute_seal():
            raise EvidenceIntegrityError(
                "seal marker does not match the durable evidence generation"
            )
        return instance

    def put_artifact(
        self, value: bytes | str | Any, *, media_type: str = "application/json"
    ) -> ArtifactRef:
        self._ensure_writable()
        if isinstance(value, bytes):
            payload = value
        elif isinstance(value, str) and media_type.startswith("text/"):
            payload = value.encode("utf-8")
        else:
            payload = canonical_json_bytes(value)
        digest = _sha256_bytes(payload)
        relative_path = Path("artifacts") / "sha256" / digest[:2] / digest
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.parent.is_symlink():
            raise EvidenceIntegrityError("artifact directory must not be a symlink")
        try:
            fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._NOFOLLOW,
                0o600,
            )
            try:
                _write_all(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_directory(destination.parent)
        except FileExistsError:
            try:
                fd = os.open(destination, os.O_RDONLY | self._NOFOLLOW)
                with os.fdopen(fd, "rb") as handle:
                    existing = handle.read()
            except OSError as error:
                raise EvidenceIntegrityError("existing artifact is unsafe") from error
            if existing != payload:
                raise EvidenceIntegrityError(
                    f"artifact digest collision or corruption at {destination}"
                )
        return ArtifactRef(
            sha256=digest,
            size_bytes=len(payload),
            media_type=media_type,
            relative_path=relative_path.as_posix(),
        )

    def append_event(
        self,
        event_type: str,
        payload: Any,
        *,
        phase_instance_id: str | None = None,
        logical_action_id: str | None = None,
        action_attempt_id: str | None = None,
        provider_call_id: str | None = None,
        tool_invocation_id: str | None = None,
        visibility: str = "evaluator_only",
    ) -> Event:
        self._ensure_writable()
        if not isinstance(event_type, str) or not event_type:
            raise EvidenceIntegrityError("event_type must be a non-empty string")
        payload_ref = self.put_artifact(payload)
        provisional = Event(
            event_id=f"event_{self._sequence:08d}",
            sequence=self._sequence,
            event_type=event_type,
            occurred_at=self._clock(),
            run_plan_id=self.run_plan_id,
            cell_id=self.cell_id,
            episode_id=self.episode_id,
            episode_attempt_id=self.episode_attempt_id,
            phase_instance_id=phase_instance_id,
            logical_action_id=logical_action_id,
            action_attempt_id=action_attempt_id,
            provider_call_id=provider_call_id,
            tool_invocation_id=tool_invocation_id,
            visibility=visibility,
            payload_ref=payload_ref.relative_path,
            payload_sha256=payload_ref.sha256,
            prior_event_hash=self._prior_hash,
            event_hash="",
        )
        event_hash = _sha256_bytes(canonical_json_bytes(_event_hash_payload(provisional)))
        event = dataclasses.replace(provisional, event_hash=event_hash)
        fd = self._open_bound_events(os.O_WRONLY | os.O_APPEND)
        try:
            _write_all(fd, canonical_json_bytes(event) + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        self._sequence += 1
        self._prior_hash = event_hash
        return event

    def read_events(self) -> tuple[Event, ...]:
        self._ensure_open()
        if self._events_inode is None:
            if os.path.lexists(self.events_path):
                raise EvidenceIntegrityError("unexpected event log appeared during execution")
            return ()
        fd = self._open_bound_events(os.O_RDONLY)
        try:
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except Exception as error:
            raise EvidenceIntegrityError("cannot read event log") from error
        events: list[Event] = []
        for line_number, line in enumerate(lines, start=1):
            try:
                events.append(Event(**json.loads(line)))
            except Exception as error:
                raise EvidenceIntegrityError(
                    f"invalid event at line {line_number}: {error}"
                ) from error
        return tuple(events)

    def _read_artifact(self, relative_path: str) -> bytes:
        path = self.root / relative_path
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("artifact is not a regular file")
            fd = os.open(path, os.O_RDONLY | self._NOFOLLOW)
            with os.fdopen(fd, "rb") as handle:
                return handle.read()
        except OSError as error:
            raise EvidenceIntegrityError(f"unsafe or missing artifact: {relative_path}") from error

    def read_event_payload(self, event: Event) -> Any:
        """Return one verified canonical JSON event payload."""

        if not isinstance(event, Event):
            raise EvidenceIntegrityError("event payload lookup requires an Event")
        payload = self._read_artifact(event.payload_ref)
        if _sha256_bytes(payload) != event.payload_sha256:
            raise EvidenceIntegrityError(
                f"payload artifact hash mismatch for {event.event_id}"
            )
        try:
            return json.loads(payload)
        except json.JSONDecodeError as error:
            raise EvidenceIntegrityError(
                f"event payload is not canonical JSON for {event.event_id}"
            ) from error

    def verify_chain(self) -> None:
        prior_hash: str | None = None
        identity = (
            self.run_plan_id,
            self.cell_id,
            self.episode_id,
            self.episode_attempt_id,
        )
        for expected_sequence, event in enumerate(self.read_events()):
            if event.sequence != expected_sequence:
                raise EvidenceIntegrityError(
                    f"event sequence mismatch at {event.event_id}: {event.sequence}"
                )
            if (
                event.run_plan_id,
                event.cell_id,
                event.episode_id,
                event.episode_attempt_id,
            ) != identity:
                raise EvidenceIntegrityError(f"event identity mismatch at {event.event_id}")
            if event.prior_event_hash != prior_hash:
                raise EvidenceIntegrityError(
                    f"prior event hash mismatch at {event.event_id}"
                )
            expected_hash = _sha256_bytes(
                canonical_json_bytes(_event_hash_payload(event))
            )
            if event.event_hash != expected_hash:
                raise EvidenceIntegrityError(f"event hash mismatch at {event.event_id}")
            artifact = self._read_artifact(event.payload_ref)
            if _sha256_bytes(artifact) != event.payload_sha256:
                raise EvidenceIntegrityError(
                    f"payload artifact hash mismatch for {event.event_id}"
                )
            prior_hash = event.event_hash

    def _artifact_manifest(self) -> tuple[Mapping[str, Any], ...]:
        if not self.artifacts_dir.exists():
            return ()
        if self.artifacts_dir.is_symlink():
            raise EvidenceIntegrityError("artifact root must not be a symlink")
        rows: list[Mapping[str, Any]] = []
        for path in sorted(self.artifacts_dir.glob("*/*")):
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                raise EvidenceIntegrityError(f"artifact entry is not a regular file: {path}")
            payload = self._read_artifact(path.relative_to(self.root).as_posix())
            digest = _sha256_bytes(payload)
            if path.name != digest:
                raise EvidenceIntegrityError(f"artifact filename digest mismatch: {path}")
            rows.append(
                {
                    "sha256": digest,
                    "size_bytes": len(payload),
                    "relative_path": path.relative_to(self.root).as_posix(),
                }
            )
        return tuple(rows)

    def _compute_seal(self) -> EvidenceSeal:
        events = self.read_events()
        artifacts = self._artifact_manifest()
        return EvidenceSeal(
            run_plan_id=self.run_plan_id,
            cell_id=self.cell_id,
            episode_id=self.episode_id,
            episode_attempt_id=self.episode_attempt_id,
            event_count=len(events),
            artifact_count=len(artifacts),
            event_root_sha256=_sha256_bytes(
                canonical_json_bytes(tuple(event.event_hash for event in events))
            ),
            artifact_root_sha256=_sha256_bytes(canonical_json_bytes(artifacts)),
        )

    def _load_seal(self) -> EvidenceSeal:
        try:
            info = os.lstat(self.seal_path)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("seal is not a regular file")
            fd = os.open(self.seal_path, os.O_RDONLY | self._NOFOLLOW)
            with os.fdopen(fd, "rb") as handle:
                return EvidenceSeal(**json.loads(handle.read()))
        except Exception as error:
            raise EvidenceIntegrityError("seal marker is invalid or unsafe") from error

    def seal(self) -> EvidenceSeal:
        self._ensure_open()
        computed = self._compute_seal()
        if os.path.lexists(self.seal_path):
            self._sealed = True
            existing = self._load_seal()
            if existing != computed:
                raise EvidenceIntegrityError("seal marker does not match current evidence")
            return existing
        temporary = self.root / f".seal-{uuid.uuid4().hex}.tmp"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._NOFOLLOW,
            0o600,
        )
        try:
            _write_all(fd, canonical_json_bytes(computed) + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, self.seal_path)
        _fsync_directory(self.root)
        self._sealed = True
        return computed

    def verify_seal(self) -> EvidenceSeal:
        """Return the durable seal after checking it against current evidence."""

        self._ensure_open()
        if not os.path.lexists(self.seal_path):
            raise EvidenceIntegrityError("evidence generation is not sealed")
        existing = self._load_seal()
        if existing != self._compute_seal():
            raise EvidenceIntegrityError(
                "seal marker does not match the durable evidence generation"
            )
        self._sealed = True
        return existing

    def audit_reconciliation(
        self,
        *,
        entity_types: Sequence[str] = (
            "logical_action",
            "action_attempt",
            "provider_call",
            "tool_invocation",
        ),
    ) -> None:
        self.verify_chain()
        events = self.read_events()
        for entity_type in entity_types:
            identity_field = f"{entity_type}_id"
            started: dict[str, int] = {}
            terminal: dict[str, int] = {}
            for event in events:
                identity = getattr(event, identity_field)
                if identity is None:
                    continue
                if event.event_type == f"{entity_type}_started":
                    started[identity] = started.get(identity, 0) + 1
                elif event.event_type.startswith(f"{entity_type}_"):
                    suffix = event.event_type[len(entity_type) + 1 :]
                    if suffix in self._TERMINAL_SUFFIXES:
                        terminal[identity] = terminal.get(identity, 0) + 1
            invalid = {
                identity: (started.get(identity, 0), terminal.get(identity, 0))
                for identity in set(started) | set(terminal)
                if started.get(identity, 0) != 1 or terminal.get(identity, 0) != 1
            }
            if invalid:
                raise EvidenceIntegrityError(
                    f"unreconciled {entity_type} events: {invalid}"
                )


@dataclass(frozen=True, slots=True)
class TokenPricing:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    pricing_id: str

    def __post_init__(self) -> None:
        for name in (
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        if not isinstance(self.pricing_id, str) or not self.pricing_id:
            raise ValueError("pricing_id must be a non-empty string")

    def cost(
        self, *, input_tokens: int, cached_input_tokens: int, output_tokens: int
    ) -> float:
        cached = min(max(cached_input_tokens, 0), max(input_tokens, 0))
        uncached = max(input_tokens, 0) - cached
        return (
            uncached * self.input_per_million
            + cached * self.cached_input_per_million
            + max(output_tokens, 0) * self.output_per_million
        ) / 1_000_000

    def content_sha256(self) -> str:
        return _sha256_bytes(canonical_json_bytes(self))


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    provider_call_id: str
    provider: str
    base_url: str | None
    model: str
    revision: str | None
    instructions: str
    input_text: str
    temperature: float | None
    top_p: float | None
    max_output_tokens: int
    reasoning_effort: str | None
    timeout_seconds: float
    request_sha256: str
    max_cost_usd: float | None = None
    output_schema: Mapping[str, Any] | None = None
    provider_metadata: Mapping[str, Any] | None = None
    seed: int | None = None
    # Native model protocol (§6, stage 2): additive, excluded from the
    # request_sha256 payload below by design -- `input_text` already carries
    # a canonical serialization of `messages`/`tools` for every response
    # mode, so the identity hash does not need a second source of truth.
    # `reasoning_token_budget` is wired to a wire request in a later stage.
    messages: tuple["CanonicalMessage", ...] | None = None
    tools: tuple["ToolSchema", ...] | None = None
    reasoning_token_budget: int | None = None

    def with_computed_hash(self) -> "ProviderRequest":
        payload = {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "revision": self.revision,
            "instructions": self.instructions,
            "input_text": self.input_text,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "reasoning_effort": self.reasoning_effort,
            "timeout_seconds": self.timeout_seconds,
            "max_cost_usd": self.max_cost_usd,
            "output_schema": self.output_schema,
            "provider_metadata": self.provider_metadata,
            "seed": self.seed,
        }
        # Native fields join the hash only when set, so a legacy text request
        # hashes exactly as before while a native call binds the bytes it
        # actually sends.  Without this, two native requests differing only in
        # messages or tools share a request_sha256 and replay cannot prove
        # which one produced a response.
        for field, value in (
            ("messages", self.messages),
            ("tools", self.tools),
            ("reasoning_token_budget", self.reasoning_token_budget),
        ):
            if value is not None:
                payload[field] = value
        return dataclasses.replace(
            self, request_sha256=_sha256_bytes(canonical_json_bytes(payload))
        )


@dataclass(frozen=True, slots=True)
class ProviderResult:
    response_id: str
    requested_model: str
    resolved_model: str | None
    output_text: str
    finish_reason: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cost_usd: float | None
    raw_response: Any
    # Native model protocol (§6, stage 2): additive; None unless the
    # provider adapter actually reports the field.
    tool_calls: tuple["NativeToolCall", ...] | None = None
    reasoning_tokens: int | None = None
    visible_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class CanonicalResponse:
    text: str
    finish_reason: str
    empty: bool
    truncated: bool
    provider_call_ids: tuple[str, ...]
    tool_invocation_ids: tuple[str, ...]
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cost_usd: float
    # The harness seam (§5.1, stage 4): additive, default None, so every
    # existing record hashes unchanged. A harness-driven executor carries
    # HarnessOutput.action here -- opaque to the kernel -- so the scheduler
    # can hand a family's parse_action the mapping it requires instead of
    # this response itself. A text harness (minimal_chat) leaves it None and
    # a family keeps reading `.text` exactly as before.
    action: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProviderCallRecord:
    provider_call_id: str
    action_attempt_id: str
    status: str
    request_sha256: str
    requested_model: str
    resolved_model: str | None
    response_id: str | None
    finish_reason: str | None
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cost_usd: float
    failure_condition: str | None


@dataclass(frozen=True, slots=True)
class ActionAttemptRecord:
    action_attempt_id: str
    logical_action_id: str
    ordinal: int
    retry_reason: str | None
    session_mode: str
    status: str
    provider_calls: tuple[ProviderCallRecord, ...]
    tool_invocations: tuple[str, ...]
    canonical_response: CanonicalResponse | None


@dataclass(frozen=True, slots=True)
class LogicalActionExecution:
    logical_action_id: str
    profile_id: str
    status: str
    attempts: tuple[ActionAttemptRecord, ...]
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class CellExecution:
    run_plan_id: str
    cell_id: str
    episode_attempt_id: str
    episode_result: EpisodeResult
    evidence: EvidenceStore
    action_executions: tuple[LogicalActionExecution, ...]
    total_cost_usd: float


@dataclass(frozen=True, slots=True)
class ToolInvocationRecord:
    tool_invocation_id: str
    action_attempt_id: str
    tool_id: str
    tool_version: str
    tool_schema_sha256: str
    input_sha256: str
    idempotency_supported: bool
    status: str
    result_sha256: str | None
    failure_condition: str | None
    effect: str
    state_before_sha256: str | None
    state_after_sha256: str | None
    state_diff_sha256: str | None
    state_changed: bool | None
    outcome_known: bool


class ProviderClient(Protocol):
    async def complete(self, request: ProviderRequest) -> ProviderResult: ...



def _reasoning_block(request: "ProviderRequest") -> dict[str, Any]:
    """The reasoning controls to send, carrying exactly what the profile declared.

    A profile may declare an effort, a token budget, or both.  Substituting a
    default for an absent control -- the previous `or "low"` -- meant a run
    labelled with one reasoning condition executed another, which is how a
    treatment silently fails to be delivered.  Absent controls are simply not
    sent, so the provider applies its own documented default rather than one
    this kernel invented.
    """

    block: dict[str, Any] = {}
    if request.reasoning_effort is not None:
        block["effort"] = request.reasoning_effort
    if request.reasoning_token_budget is not None:
        block["max_tokens"] = request.reasoning_token_budget
    return block


class OpenAIResponsesClient:
    """OpenAI Responses API adapter with SDK-level retries disabled."""

    def __init__(
        self,
        *,
        sdk_client: Any | None = None,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        if sdk_client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as error:  # pragma: no cover - dependency error
                raise EvidenceIntegrityError(
                    "OpenAIResponsesClient requires the openai package"
                ) from error
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise EvidenceIntegrityError(
                    "OPENAI_API_KEY must be set before constructing the live OpenAI client"
                )
            sdk_client = AsyncOpenAI(
                api_key=api_key,
                base_url=self._base_url,
                max_retries=0,
            )
        if not hasattr(sdk_client, "responses"):
            raise EvidenceIntegrityError(
                "installed OpenAI SDK does not expose the Responses API"
            )
        self._client = sdk_client

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.messages is not None:
            raise ProviderFailure(
                "provider_contract",
                "OpenAI Responses adapter does not support native chat messages",
                retryable=False,
            )
        if request.provider != "openai":
            raise ProviderFailure(
                "provider_contract",
                f"OpenAI adapter received provider {request.provider!r}",
                retryable=False,
            )
        requested_base_url = (request.base_url or "https://api.openai.com/v1").rstrip("/")
        if requested_base_url != self._base_url:
            raise ProviderFailure(
                "provider_contract",
                f"request base URL {requested_base_url!r} does not match client base URL "
                f"{self._base_url!r}",
                retryable=False,
            )
        kwargs: dict[str, Any] = {
            "model": request.model,
            "instructions": request.instructions,
            "input": request.input_text,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }
        if request.reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": request.reasoning_effort}
        else:
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.top_p is not None:
                kwargs["top_p"] = request.top_p
        try:
            response = await self._client.responses.create(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise self._classify_error(error) from error
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None)
        status = str(getattr(response, "status", "unknown"))
        incomplete = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete, "reason", None)
        finish_reason = str(incomplete_reason or ("stop" if status == "completed" else status))
        raw_response = response.model_dump(mode="json")
        return ProviderResult(
            response_id=str(getattr(response, "id", "")),
            requested_model=request.model,
            resolved_model=getattr(response, "model", None),
            output_text=str(getattr(response, "output_text", "") or ""),
            finish_reason=finish_reason,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            cached_input_tokens=int(
                getattr(input_details, "cached_tokens", 0) or 0
            ),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cost_usd=None,
            raw_response=raw_response,
        )

    @staticmethod
    def _classify_error(error: Exception) -> ProviderFailure:
        name = type(error).__name__
        status_code = getattr(error, "status_code", None)
        if name in {"APITimeoutError", "TimeoutError"}:
            return ProviderFailure("timeout", str(error), retryable=True)
        if name == "RateLimitError" or status_code == 429:
            return ProviderFailure(
                "rate_limit", str(error), retryable=True, status_code=status_code
            )
        if name == "APIConnectionError":
            return ProviderFailure("transport", str(error), retryable=True)
        if name == "InternalServerError" or (
            isinstance(status_code, int) and status_code >= 500
        ):
            return ProviderFailure(
                "provider_5xx", str(error), retryable=True, status_code=status_code
            )
        return ProviderFailure(
            "provider_rejected",
            str(error),
            retryable=False,
            status_code=status_code,
        )


class OpenRouterChatClient:
    """OpenRouter Chat Completions adapter with an exact provider route."""

    def __init__(
        self,
        *,
        sdk_client: Any | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        if sdk_client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as error:  # pragma: no cover - dependency error
                raise EvidenceIntegrityError(
                    "OpenRouterChatClient requires the openai package"
                ) from error
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                raise EvidenceIntegrityError(
                    "OPENROUTER_API_KEY must be set before constructing the live "
                    "OpenRouter client"
                )
            sdk_client = AsyncOpenAI(
                api_key=api_key,
                base_url=self._base_url,
                max_retries=0,
            )
        chat = getattr(sdk_client, "chat", None)
        if chat is None or not hasattr(chat, "completions"):
            raise EvidenceIntegrityError(
                "installed OpenAI SDK does not expose Chat Completions"
            )
        self._client = sdk_client

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "openrouter":
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter adapter received provider {request.provider!r}",
                retryable=False,
            )
        requested_base_url = (request.base_url or "").rstrip("/")
        if requested_base_url != self._base_url:
            raise ProviderFailure(
                "provider_contract",
                f"request base URL {requested_base_url!r} does not match client base URL "
                f"{self._base_url!r}",
                retryable=False,
            )
        if request.messages is not None:
            return await self._complete_native(request)
        if not isinstance(request.output_schema, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter adapter requires a structured output schema",
                retryable=False,
            )
        provider_preferences, canonical_model, route_provider = self._route_preferences(
            request
        )
        wire_output_schema = json.loads(canonical_json_bytes(request.output_schema))
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.instructions},
                {"role": "user", "content": request.input_text},
            ],
            "seed": request.seed,
            "max_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "aeread_action",
                    "strict": True,
                    "schema": wire_output_schema,
                },
            },
            "tools": [],
            "stream": False,
            "extra_headers": {"X-OpenRouter-Metadata": "enabled"},
            "extra_body": {
                "reasoning": _reasoning_block(request),
                "provider": provider_preferences,
            },
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            kwargs["top_p"] = request.top_p
        response = await self._create(**kwargs)
        raw_response, choice, message = self._parsed_choice(response)
        content = message.get("content") if isinstance(message, Mapping) else None
        input_tokens, cached_input_tokens, output_tokens, cost = self._usage(raw_response)
        selected_model = self._verify_route(
            raw_response.get("openrouter_metadata"),
            requested_model=request.model,
            canonical_model=canonical_model,
            route_provider=route_provider,
        )
        response_model = raw_response.get("model")
        if response_model not in {request.model, canonical_model}:
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter response model {response_model!r} was not requested",
                retryable=False,
            )
        if content is None or (isinstance(content, str) and not content.strip()):
            return ProviderResult(
                response_id=str(raw_response.get("id") or ""),
                requested_model=request.model,
                resolved_model=selected_model,
                output_text="",
                finish_reason=str(choice.get("finish_reason") or "unknown"),
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                cost_usd=float(cost),
                raw_response=raw_response,
            )
        if not isinstance(content, str):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response choice has non-text content",
                retryable=False,
            )
        try:
            structured_output = json.loads(content)
        except json.JSONDecodeError as error:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter structured output is not valid JSON",
                retryable=False,
            ) from error
        return ProviderResult(
            response_id=str(raw_response.get("id") or ""),
            requested_model=request.model,
            resolved_model=selected_model,
            output_text=canonical_json_bytes(structured_output).decode("utf-8"),
            finish_reason=str(choice.get("finish_reason") or "unknown"),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            cost_usd=float(cost),
            raw_response=raw_response,
        )

    async def _complete_native(self, request: ProviderRequest) -> ProviderResult:
        """§6: `request.messages` set means send chat messages + tools
        natively instead of the structured-output dialect above."""
        provider_preferences, canonical_model, route_provider = self._route_preferences(
            request
        )
        wire_messages = [{"role": "system", "content": request.instructions}]
        for message in request.messages:
            wire_message: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.tool_call_id is not None:
                wire_message["tool_call_id"] = message.tool_call_id
            if message.name is not None:
                wire_message["name"] = message.name
            wire_messages.append(wire_message)
        wire_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.tool_id,
                    "description": tool.description,
                    "parameters": json.loads(canonical_json_bytes(tool.input_schema)),
                },
            }
            for tool in (request.tools or ())
        ]
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": wire_messages,
            "seed": request.seed,
            "max_tokens": request.max_output_tokens,
            "tools": wire_tools,
            "stream": False,
            "extra_headers": {"X-OpenRouter-Metadata": "enabled"},
            "extra_body": {
                "reasoning": _reasoning_block(request),
                "provider": provider_preferences,
            },
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            kwargs["top_p"] = request.top_p
        response = await self._create(**kwargs)
        raw_response, choice, message = self._parsed_choice(response)
        if not isinstance(message, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response choice has no message",
                retryable=False,
            )
        tool_calls = self._native_tool_calls(message.get("tool_calls"))
        content = message.get("content")
        if tool_calls is None and not isinstance(content, str):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response choice has neither text nor tool calls",
                retryable=False,
            )
        input_tokens, cached_input_tokens, output_tokens, cost = self._usage(raw_response)
        selected_model = self._verify_route(
            raw_response.get("openrouter_metadata"),
            requested_model=request.model,
            canonical_model=canonical_model,
            route_provider=route_provider,
        )
        response_model = raw_response.get("model")
        if response_model not in {request.model, canonical_model}:
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter response model {response_model!r} was not requested",
                retryable=False,
            )
        return ProviderResult(
            response_id=str(raw_response.get("id") or ""),
            requested_model=request.model,
            resolved_model=selected_model,
            output_text=content if isinstance(content, str) else "",
            finish_reason=str(choice.get("finish_reason") or "unknown"),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            raw_response=raw_response,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _native_tool_calls(raw_tool_calls: Any) -> "tuple[NativeToolCall, ...] | None":
        """Map the response's `tool_calls` into `NativeToolCall`s, preserving
        source order -- order is the only correlation a later round has with
        `source_call_index` (§8), so this must never reorder."""
        if raw_tool_calls is None:
            return None
        if not isinstance(raw_tool_calls, list) or not raw_tool_calls:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter tool_calls must be a non-empty array",
                retryable=False,
            )
        from ..model_call.harness import NativeToolCall

        calls: list[NativeToolCall] = []
        for entry in raw_tool_calls:
            if not isinstance(entry, Mapping):
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter tool_calls entries must be objects",
                    retryable=False,
                )
            call_id = entry.get("id")
            function = entry.get("function")
            if not isinstance(call_id, str) or not call_id or not isinstance(function, Mapping):
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter tool_calls entry is missing an id or function",
                    retryable=False,
                )
            tool_id = function.get("name")
            raw_arguments = function.get("arguments")
            if (
                not isinstance(tool_id, str)
                or not tool_id
                or not isinstance(raw_arguments, str)
            ):
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter tool_calls entry has an invalid function name or arguments",
                    retryable=False,
                )
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as error:
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter tool_calls arguments are not valid JSON",
                    retryable=False,
                ) from error
            if not isinstance(arguments, Mapping):
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter tool_calls arguments must be an object",
                    retryable=False,
                )
            calls.append(NativeToolCall(call_id=call_id, tool_id=tool_id, arguments=arguments))
        return tuple(calls)

    @staticmethod
    def _route_preferences(request: ProviderRequest) -> tuple[dict[str, Any], str, str]:
        """Validate the sealed OpenRouter route pin, shared by both dialects
        (§6): the response format differs by mode, the pinned backend does
        not."""
        metadata = request.provider_metadata
        if not isinstance(metadata, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter adapter requires sealed provider metadata",
                retryable=False,
            )
        required_metadata = {
            "route_provider",
            "quantization",
            "canonical_model",
            "max_prompt_price_per_million",
            "max_completion_price_per_million",
        }
        if set(metadata) != required_metadata:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter provider metadata fields are incomplete or unexpected",
                retryable=False,
            )
        route_provider = metadata["route_provider"]
        quantization = metadata["quantization"]
        canonical_model = metadata["canonical_model"]
        if not all(
            isinstance(value, str) and value
            for value in (route_provider, quantization, canonical_model)
        ):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter route identity must contain non-empty strings",
                retryable=False,
            )
        if request.revision != canonical_model:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter canonical model does not match the sealed revision",
                retryable=False,
            )
        if request.seed is None:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter diagnostic runs require a declared seed",
                retryable=False,
            )
        provider_preferences = {
            "only": [route_provider],
            "order": [route_provider],
            "allow_fallbacks": False,
            "require_parameters": True,
            "quantizations": [quantization],
            "max_price": {
                "prompt": metadata["max_prompt_price_per_million"],
                "completion": metadata["max_completion_price_per_million"],
            },
        }
        return provider_preferences, canonical_model, route_provider

    async def _create(self, **kwargs: Any) -> Any:
        try:
            return await self._client.chat.completions.create(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise OpenAIResponsesClient._classify_error(error) from error

    @staticmethod
    def _parsed_choice(response: Any) -> tuple[Mapping[str, Any], Mapping[str, Any], Any]:
        try:
            raw_response = response.model_dump(mode="json")
        except Exception as error:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response could not be serialized",
                retryable=False,
            ) from error
        if not isinstance(raw_response, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response must be an object",
                retryable=False,
            )
        top_level_error = raw_response.get("error")
        if isinstance(top_level_error, Mapping):
            status_code = top_level_error.get("code")
            message = str(top_level_error.get("message") or "OpenRouter request failed")
            raise OpenRouterChatClient._provider_error(status_code, message)
        choices = raw_response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response must contain exactly one choice",
                retryable=False,
            )
        choice = choices[0]
        choice_error = choice.get("error") if isinstance(choice, Mapping) else None
        if isinstance(choice_error, Mapping):
            status_code = choice_error.get("code")
            message = str(choice_error.get("message") or "OpenRouter choice failed")
            raise OpenRouterChatClient._provider_error(status_code, message)
        if isinstance(choice, Mapping) and choice.get("finish_reason") == "error":
            raise ProviderFailure(
                "provider_rejected",
                "OpenRouter choice finished with an error",
                retryable=False,
            )
        message = choice.get("message") if isinstance(choice, Mapping) else None
        return raw_response, choice, message

    @staticmethod
    def _provider_error(status_code: Any, message: str) -> ProviderFailure:
        resolved_status = status_code if isinstance(status_code, int) else None
        if resolved_status == 429:
            return ProviderFailure(
                "rate_limit", message, retryable=True, status_code=resolved_status
            )
        retryable = resolved_status is not None and resolved_status >= 500
        return ProviderFailure(
            "provider_5xx" if retryable else "provider_rejected",
            message,
            retryable=retryable,
            status_code=resolved_status,
        )

    @staticmethod
    def _usage(raw_response: Mapping[str, Any]) -> tuple[int, int, int, float]:
        usage = raw_response.get("usage")
        if not isinstance(usage, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response omitted token and cost usage",
                retryable=False,
            )

        def nonnegative_integer(source: Mapping[str, Any], field: str) -> int:
            value = source.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProviderFailure(
                    "provider_contract",
                    f"OpenRouter usage field {field!r} is invalid",
                    retryable=False,
                )
            return value

        input_tokens = nonnegative_integer(usage, "prompt_tokens")
        output_tokens = nonnegative_integer(usage, "completion_tokens")
        input_details = usage.get("prompt_tokens_details")
        cached_input_tokens = (
            nonnegative_integer(input_details, "cached_tokens")
            if isinstance(input_details, Mapping)
            else 0
        )
        cost = usage.get("cost")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or cost < 0
        ):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response cost is invalid",
                retryable=False,
            )
        return input_tokens, cached_input_tokens, output_tokens, float(cost)

    @staticmethod
    def _verify_route(
        metadata: Any,
        *,
        requested_model: str,
        canonical_model: str,
        route_provider: str,
    ) -> str:
        if not isinstance(metadata, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter routing metadata is missing",
                retryable=False,
            )
        if metadata.get("requested") != requested_model:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter routing metadata names a different requested model",
                retryable=False,
            )
        if metadata.get("attempt") != 1:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter routing metadata reveals a fallback or repeated route attempt",
                retryable=False,
            )
        endpoints = metadata.get("endpoints")
        available = endpoints.get("available") if isinstance(endpoints, Mapping) else None
        selected = (
            [item for item in available if isinstance(item, Mapping) and item.get("selected")]
            if isinstance(available, list)
            else []
        )
        if len(selected) != 1 or selected[0].get("provider") != route_provider:
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter selected provider does not match {route_provider!r}",
                retryable=False,
            )
        if selected[0].get("model") != canonical_model:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter selected endpoint model does not match the sealed revision",
                retryable=False,
            )
        attempts = metadata.get("attempts")
        if attempts is not None:
            if not isinstance(attempts, list):
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter routing attempts are not an array",
                    retryable=False,
                )
            valid_attempts = [
                item
                for item in attempts
                if isinstance(item, Mapping)
                and item.get("provider") == route_provider
                and item.get("model") == canonical_model
                and item.get("status") == 200
            ]
            if len(attempts) != 1 or len(valid_attempts) != 1:
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter routing attempts reveal a fallback or failed route",
                    retryable=False,
                )
        return canonical_model


CommandRunner = Callable[
    [tuple[str, ...], bytes], Awaitable[tuple[int, bytes, bytes]]
]


async def _run_subprocess(
    arguments: tuple[str, ...], standard_input: bytes
) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate(standard_input)
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    return process.returncode, stdout, stderr


class ClaudeCodePrintClient:
    """Authenticated Claude Code print adapter for diagnostic R4 smokes.

    The adapter deliberately disables tools, session persistence, project
    customizations, and fallback models.  Its executable version and digest are
    sealed into each request so a local CLI update cannot silently change a run.
    """

    def __init__(
        self,
        *,
        executable: str | Path,
        runtime_version: str,
        runtime_sha256: str,
        command_runner: CommandRunner = _run_subprocess,
    ) -> None:
        self._executable = Path(executable).resolve()
        if not self._executable.is_file():
            raise EvidenceIntegrityError(
                f"Claude Code executable does not exist: {self._executable}"
            )
        if not isinstance(runtime_version, str) or not runtime_version:
            raise EvidenceIntegrityError("Claude Code runtime version is required")
        if (
            not isinstance(runtime_sha256, str)
            or len(runtime_sha256) != 64
            or any(character not in "0123456789abcdef" for character in runtime_sha256)
        ):
            raise EvidenceIntegrityError(
                "Claude Code runtime digest must be 64 lowercase hexadecimal characters"
            )
        self.runtime_version = runtime_version
        self.runtime_sha256 = runtime_sha256
        self._command_runner = command_runner

    @classmethod
    async def discover(cls, executable: str = "claude") -> "ClaudeCodePrintClient":
        resolved = shutil.which(executable)
        if resolved is None:
            raise EvidenceIntegrityError(
                f"Claude Code executable is unavailable: {executable!r}"
            )
        executable_path = Path(resolved).resolve()
        digest = _sha256_bytes(executable_path.read_bytes())
        returncode, stdout, stderr = await _run_subprocess(
            (str(executable_path), "--version"), b""
        )
        if returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise EvidenceIntegrityError(
                f"Claude Code version probe failed with exit {returncode}: {message}"
            )
        version_output = stdout.decode("utf-8", errors="strict").strip()
        version = version_output.split(maxsplit=1)[0] if version_output else ""
        if not version:
            raise EvidenceIntegrityError("Claude Code version probe returned no version")
        return cls(
            executable=executable_path,
            runtime_version=version,
            runtime_sha256=digest,
        )

    @property
    def runtime_metadata(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "runtime_version": self.runtime_version,
                "runtime_sha256": self.runtime_sha256,
            }
        )

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.messages is not None:
            raise ProviderFailure(
                "provider_contract",
                "Claude Code adapter does not support native chat messages",
                retryable=False,
            )
        if request.provider != "claude_code":
            raise ProviderFailure(
                "provider_contract",
                f"Claude Code adapter received provider {request.provider!r}",
                retryable=False,
            )
        if request.base_url is not None:
            raise ProviderFailure(
                "provider_contract",
                "Claude Code adapter does not accept a base URL",
                retryable=False,
            )
        if request.revision != request.model:
            raise ProviderFailure(
                "provider_contract",
                "Claude Code diagnostic runs require an exact model snapshot",
                retryable=False,
            )
        if (
            request.max_cost_usd is None
            or isinstance(request.max_cost_usd, bool)
            or request.max_cost_usd <= 0
        ):
            raise ProviderFailure(
                "provider_contract",
                "Claude Code adapter requires a positive per-profile cost ceiling",
                retryable=False,
            )
        if not isinstance(request.output_schema, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "Claude Code adapter requires a structured output schema",
                retryable=False,
            )
        declared_runtime = request.provider_metadata
        expected_runtime = dict(self.runtime_metadata)
        if not isinstance(declared_runtime, Mapping) or dict(declared_runtime) != expected_runtime:
            raise ProviderFailure(
                "provider_contract",
                "sealed Claude Code runtime metadata does not match the adapter",
                retryable=False,
            )
        actual_digest = _sha256_bytes(self._executable.read_bytes())
        if actual_digest != self.runtime_sha256:
            raise ProviderFailure(
                "provider_contract",
                "Claude Code runtime digest changed after plan resolution",
                retryable=False,
            )
        arguments = (
            str(self._executable),
            "--safe-mode",
            "--print",
            "--model",
            request.model,
            "--effort",
            request.reasoning_effort or "medium",
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--max-budget-usd",
            format(request.max_cost_usd, ".12g"),
            "--output-format",
            "json",
            "--system-prompt",
            request.instructions,
            "--json-schema",
            canonical_json_bytes(request.output_schema).decode("utf-8"),
        )
        try:
            returncode, stdout, stderr = await asyncio.wait_for(
                self._command_runner(arguments, request.input_text.encode("utf-8")),
                timeout=request.timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            raise ProviderFailure(
                "timeout", "Claude Code invocation timed out", retryable=True
            ) from error
        if returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise ProviderFailure(
                "provider_rejected",
                f"Claude Code exited with {returncode}: {message}",
                retryable=False,
            )
        try:
            payload = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderFailure(
                "provider_contract",
                "Claude Code did not return one valid JSON result",
                retryable=False,
            ) from error
        if not isinstance(payload, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "Claude Code result must be an object",
                retryable=False,
            )
        if payload.get("is_error") is not False:
            raise ProviderFailure(
                "provider_rejected",
                str(payload.get("result") or "Claude Code reported an error"),
                retryable=False,
            )
        model_usage = payload.get("modelUsage")
        if not isinstance(model_usage, Mapping) or len(model_usage) != 1:
            raise ProviderFailure(
                "provider_contract",
                "Claude Code run must report exactly one resolved model",
                retryable=False,
            )
        resolved_model, usage = next(iter(model_usage.items()))
        if not isinstance(resolved_model, str) or not isinstance(usage, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "Claude Code model usage is malformed",
                retryable=False,
            )

        def nonnegative_integer(field: str) -> int:
            value = usage.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProviderFailure(
                    "provider_contract",
                    f"Claude Code usage field {field!r} is invalid",
                    retryable=False,
                )
            return value

        cost = payload.get("total_cost_usd")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or cost < 0
        ):
            raise ProviderFailure(
                "provider_contract",
                "Claude Code total_cost_usd is invalid",
                retryable=False,
            )
        structured_output = payload.get("structured_output")
        if structured_output is None:
            raise ProviderFailure(
                "provider_contract",
                "Claude Code omitted the requested structured output",
                retryable=False,
            )
        return ProviderResult(
            response_id=str(payload.get("uuid") or payload.get("session_id") or ""),
            requested_model=request.model,
            resolved_model=resolved_model,
            output_text=canonical_json_bytes(structured_output).decode("utf-8"),
            finish_reason=str(
                payload.get("stop_reason") or payload.get("terminal_reason") or "unknown"
            ),
            input_tokens=nonnegative_integer("inputTokens"),
            cached_input_tokens=nonnegative_integer("cacheReadInputTokens"),
            output_tokens=nonnegative_integer("outputTokens"),
            cost_usd=float(cost),
            raw_response=payload,
        )


class MinimalChatExecutor:
    """R3 response source for one-call, no-tools, no-memory agent profiles."""

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        profiles: Sequence[AgentProfile],
        prompt_sources: Mapping[str, str | bytes],
        providers: Mapping[str, ProviderClient],
        pricing: Mapping[str, TokenPricing],
        request_seed_by_profile: Mapping[str, int] | None = None,
    ) -> None:
        if not isinstance(evidence, EvidenceStore):
            raise EvidenceIntegrityError("evidence must be an EvidenceStore")
        self.evidence = evidence
        self._providers = dict(providers)
        self._pricing = dict(pricing)
        self._profiles: dict[str, AgentProfile] = {}
        self._prompt_text: dict[str, str] = {}
        self._executions: dict[str, LogicalActionExecution] = {}
        self._logical_actions_by_profile: dict[str, int] = {}
        self._cost_by_profile: dict[str, float] = {}
        self._request_seed_by_profile = dict(request_seed_by_profile or {})
        self.total_cost_usd = 0.0
        for profile in profiles:
            if not isinstance(profile, AgentProfile):
                raise EvidenceIntegrityError("profiles must contain AgentProfile records")
            if profile.profile_id in self._profiles:
                raise EvidenceIntegrityError(f"duplicate profile: {profile.profile_id}")
            self._validate_profile(profile, prompt_sources)
            source = prompt_sources[profile.prompt.prompt_id]
            self._prompt_text[profile.profile_id] = (
                source.decode("utf-8") if isinstance(source, bytes) else source
            )
            self._profiles[profile.profile_id] = profile
        unknown_seed_profiles = set(self._request_seed_by_profile) - set(
            self._profiles
        )
        if unknown_seed_profiles:
            raise EvidenceIntegrityError(
                "request seeds reference unknown profiles: "
                f"{sorted(unknown_seed_profiles)}"
            )

    def _validate_harness_profile(self, profile: AgentProfile) -> None:
        """Checks that belong to THIS executor's harness, not to every harness.

        Split out so a subclass driving other harnesses inherits the universal
        checks below -- providers, pricing, prompts, sdk_retries -- without
        also inheriting minimal_chat/1.0's own guarantee that it accepts no
        tools and no memory. Before the split, an AttemptExecutor bound to a
        tool-using harness was refused here as "not minimal_chat/1.0", so no
        tool harness could reach the production entry point at all.
        """

        if profile.harness.id != "minimal_chat" or profile.harness.version != "1.0":
            raise EvidenceIntegrityError(
                f"profile {profile.profile_id!r} is not minimal_chat/1.0"
            )
        if profile.tools:
            raise EvidenceIntegrityError("minimal_chat/1.0 does not permit tools")
        if profile.memory.mode != "disabled":
            raise EvidenceIntegrityError("minimal_chat/1.0 requires disabled memory")

    def _validate_profile(
        self, profile: AgentProfile, prompt_sources: Mapping[str, str | bytes]
    ) -> None:
        self._validate_harness_profile(profile)
        if profile.retry_policy.sdk_retries != 0:
            raise EvidenceIntegrityError("SDK retries must be zero")
        if profile.model.provider not in self._providers:
            raise EvidenceIntegrityError(
                f"no provider client registered for {profile.model.provider!r}"
            )
        if profile.model.model not in self._pricing:
            raise EvidenceIntegrityError(
                f"no token pricing registered for model {profile.model.model!r}"
            )
        model_pricing = self._pricing[profile.model.model]
        declared_pricing_id = profile.harness.config.get("pricing_id")
        declared_pricing_sha256 = profile.harness.config.get("pricing_sha256")
        if declared_pricing_id != model_pricing.pricing_id:
            raise EvidenceIntegrityError(
                f"pricing id mismatch for model {profile.model.model!r}: "
                f"declared={declared_pricing_id!r}, "
                f"resolved={model_pricing.pricing_id!r}"
            )
        computed_pricing_sha256 = model_pricing.content_sha256()
        if declared_pricing_sha256 != computed_pricing_sha256:
            raise EvidenceIntegrityError(
                f"pricing hash mismatch for model {profile.model.model!r}: "
                f"declared={declared_pricing_sha256!r}, "
                f"computed={computed_pricing_sha256!r}"
            )
        source = prompt_sources.get(profile.prompt.prompt_id)
        if source is None:
            raise EvidenceIntegrityError(
                f"missing prompt source {profile.prompt.prompt_id!r}"
            )
        payload = source if isinstance(source, bytes) else source.encode("utf-8")
        digest = _sha256_bytes(payload)
        if digest != profile.prompt.sha256:
            raise EvidenceIntegrityError(
                f"prompt hash mismatch for {profile.prompt.prompt_id!r}: "
                f"declared={profile.prompt.sha256}, computed={digest}"
            )

    async def _obtain_result(
        self,
        *,
        provider: ProviderClient,
        request: ProviderRequest,
        profile: AgentProfile,
        decision: DecisionRequest,
        action_attempt_id: str,
    ) -> ProviderResult:
        """Obtain one provider result for this attempt.

        Extracted so a harness-driven executor can substitute the model loop
        without duplicating the surrounding attempt lifecycle, whose event
        order existing receipts depend on.  The default is the single direct
        call this executor has always made.
        """

        return await asyncio.wait_for(
            provider.complete(request), timeout=profile.budgets.timeout_seconds
        )

    def _harness_action(self, action_attempt_id: str) -> Mapping[str, Any] | None:
        """The opaque action a harness produced for this attempt, if any.

        Extracted alongside `_obtain_result` so a harness-driven executor can
        carry `HarnessOutput.action` onto the `CanonicalResponse` it builds
        without this executor knowing a harness exists.  Text families have
        no action of their own, so the default is always None.
        """

        return None

    def _harness_tool_invocation_ids(self, action_attempt_id: str) -> tuple[str, ...]:
        """The tool invocations a harness made during this attempt.

        A single-call executor makes none, so the default is empty. Without the
        hook the CanonicalResponse claimed zero tool calls even when the
        evidence stream recorded two, leaving the attempt record and the
        evidence disagreeing about the same attempt.
        """

        return ()

    def _request_for(
        self,
        decision: DecisionRequest,
        profile: AgentProfile,
        *,
        action_attempt_id: str,
        max_output_tokens: int,
    ) -> ProviderRequest:
        provider_call_id = _stable_id(
            "provider_call",
            {"action_attempt_id": action_attempt_id, "ordinal": 0},
        )
        input_text = canonical_json_bytes(
            {
                "phase_id": decision.phase_id,
                "seat_id": decision.seat_id,
                "role": decision.role,
                "observation_schema": decision.observation_schema,
                "action_schema": decision.action_schema,
                "observation": decision.observation,
            }
        ).decode("utf-8")
        sampling_controls = profile.harness.config.get("sampling_controls")
        temperature = profile.sampling.temperature
        if (
            isinstance(sampling_controls, Mapping)
            and sampling_controls.get("temperature") == "unavailable"
        ):
            temperature = None
        output_schema = profile.harness.config.get("output_schema")
        schemas_by_action = profile.harness.config.get(
            "output_schema_by_action_schema"
        )
        if schemas_by_action is not None:
            if output_schema is not None:
                raise EvidenceIntegrityError(
                    "a profile cannot declare both output_schema and "
                    "output_schema_by_action_schema"
                )
            if not isinstance(schemas_by_action, Mapping):
                raise EvidenceIntegrityError(
                    "output_schema_by_action_schema must be a mapping"
                )
            output_schema = schemas_by_action.get(decision.action_schema)
            if not isinstance(output_schema, Mapping):
                raise EvidenceIntegrityError(
                    "no structured output schema declared for action schema "
                    f"{decision.action_schema!r}"
                )
        return ProviderRequest(
            provider_call_id=provider_call_id,
            provider=profile.model.provider,
            base_url=profile.model.base_url,
            model=profile.model.model,
            revision=profile.model.revision,
            instructions=self._prompt_text[profile.profile_id],
            input_text=input_text,
            temperature=temperature,
            top_p=profile.sampling.top_p,
            max_output_tokens=max_output_tokens,
            reasoning_effort=profile.reasoning.effort,
            reasoning_token_budget=profile.reasoning.token_budget,
            timeout_seconds=profile.budgets.timeout_seconds,
            request_sha256="",
            max_cost_usd=profile.budgets.max_cost_usd,
            output_schema=output_schema,
            provider_metadata=(
                profile.harness.config.get("provider_metadata")
                or profile.harness.config.get("provider_runtime")
            ),
            seed=self._request_seed_by_profile.get(
                profile.profile_id, profile.sampling.seed
            ),
        ).with_computed_hash()

    async def __call__(self, decision: DecisionRequest) -> CanonicalResponse:
        if not isinstance(decision, DecisionRequest):
            raise EvidenceIntegrityError("minimal chat input must be DecisionRequest")
        context_mismatches = {
            "cell_id": (decision.cell_id, self.evidence.cell_id),
            "episode_id": (decision.episode_id, self.evidence.episode_id),
        }
        context_mismatches = {
            key: values
            for key, values in context_mismatches.items()
            if values[0] != values[1]
        }
        if context_mismatches:
            raise EvidenceIntegrityError(
                f"decision and evidence context mismatch: {context_mismatches}"
            )
        if decision.logical_action_id in self._executions:
            raise EvidenceIntegrityError(
                f"logical action already started: {decision.logical_action_id}"
            )
        profile = self._profiles.get(decision.profile_id)
        if profile is None:
            raise EvidenceIntegrityError(
                f"unknown agent profile: {decision.profile_id!r}"
            )
        profile_count = self._logical_actions_by_profile.get(profile.profile_id, 0) + 1
        if profile_count > profile.budgets.max_logical_actions:
            raise EvidenceIntegrityError(
                f"profile logical-action budget exceeded for {profile.profile_id!r}"
            )
        self._logical_actions_by_profile[profile.profile_id] = profile_count
        self.evidence.append_event(
            "logical_action_started",
            {"profile_id": profile.profile_id, "request": decision},
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
            visibility=f"seat:{decision.seat_id}",
        )
        attempts: list[ActionAttemptRecord] = []
        self._executions[decision.logical_action_id] = LogicalActionExecution(
            logical_action_id=decision.logical_action_id,
            profile_id=profile.profile_id,
            status="started",
            attempts=(),
            failure_code=None,
        )
        retry_reason: str | None = None
        max_output_tokens = profile.sampling.max_output_tokens

        for ordinal in range(profile.retry_policy.max_action_attempts):
            action_attempt_id = _stable_id(
                "action_attempt",
                {"logical_action_id": decision.logical_action_id, "ordinal": ordinal},
            )
            self.evidence.append_event(
                "action_attempt_started",
                {
                    "ordinal": ordinal,
                    "retry_reason": retry_reason,
                    "session_mode": profile.retry_policy.session_mode,
                    "max_output_tokens": max_output_tokens,
                },
                phase_instance_id=decision.phase_instance_id,
                logical_action_id=decision.logical_action_id,
                action_attempt_id=action_attempt_id,
                visibility=f"seat:{decision.seat_id}",
            )
            request = self._request_for(
                decision,
                profile,
                action_attempt_id=action_attempt_id,
                max_output_tokens=max_output_tokens,
            )
            self.evidence.append_event(
                "provider_call_started",
                {"request": request},
                phase_instance_id=decision.phase_instance_id,
                logical_action_id=decision.logical_action_id,
                action_attempt_id=action_attempt_id,
                provider_call_id=request.provider_call_id,
                visibility=f"seat:{decision.seat_id}",
            )
            provider = self._providers[profile.model.provider]
            try:
                result = await self._obtain_result(
                    provider=provider,
                    request=request,
                    profile=profile,
                    decision=decision,
                    action_attempt_id=action_attempt_id,
                )
            except asyncio.TimeoutError as error:
                failure = ProviderFailure("timeout", str(error), retryable=True)
                should_retry = self._record_provider_failure(
                    decision,
                    profile,
                    request,
                    action_attempt_id,
                    ordinal,
                    retry_reason,
                    attempts,
                    failure,
                )
                if should_retry:
                    await self._wait_before_provider_retry(
                        decision=decision,
                        request=request,
                        profile=profile,
                        condition=failure.condition,
                        ordinal=ordinal,
                    )
                    retry_reason = failure.condition
                    continue
                raise failure from error
            except ProviderFailure as failure:
                should_retry = self._record_provider_failure(
                    decision,
                    profile,
                    request,
                    action_attempt_id,
                    ordinal,
                    retry_reason,
                    attempts,
                    failure,
                )
                if should_retry:
                    await self._wait_before_provider_retry(
                        decision=decision,
                        request=request,
                        profile=profile,
                        condition=failure.condition,
                        ordinal=ordinal,
                    )
                    retry_reason = failure.condition
                    continue
                raise
            except asyncio.CancelledError:
                self._record_unknown(
                    decision, request.provider_call_id, action_attempt_id, attempts
                )
                raise
            except BaseException:
                self._record_unknown(
                    decision, request.provider_call_id, action_attempt_id, attempts
                )
                raise

            if not isinstance(result, ProviderResult):
                failure = ProviderFailure(
                    "provider_contract",
                    "provider client did not return ProviderResult",
                    retryable=False,
                )
                self._record_provider_failure(
                    decision,
                    profile,
                    request,
                    action_attempt_id,
                    ordinal,
                    retry_reason,
                    attempts,
                    failure,
                )
                raise failure
            pricing = self._pricing[profile.model.model]
            cost = (
                result.cost_usd
                if result.cost_usd is not None
                else pricing.cost(
                    input_tokens=result.input_tokens,
                    cached_input_tokens=result.cached_input_tokens,
                    output_tokens=result.output_tokens,
                )
            )
            profile_cost = self._cost_by_profile.get(profile.profile_id, 0.0) + cost
            self._cost_by_profile[profile.profile_id] = profile_cost
            self.total_cost_usd += cost
            provider_record = ProviderCallRecord(
                provider_call_id=request.provider_call_id,
                action_attempt_id=action_attempt_id,
                status="succeeded",
                request_sha256=request.request_sha256,
                requested_model=result.requested_model,
                resolved_model=result.resolved_model,
                response_id=result.response_id,
                finish_reason=result.finish_reason,
                input_tokens=result.input_tokens,
                cached_input_tokens=result.cached_input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=cost,
                failure_condition=None,
            )
            self.evidence.append_event(
                "provider_call_succeeded",
                {
                    "provider_result": result,
                    "request_sha256": request.request_sha256,
                    "pricing_id": pricing.pricing_id,
                    "cost_usd": cost,
                },
                phase_instance_id=decision.phase_instance_id,
                logical_action_id=decision.logical_action_id,
                action_attempt_id=action_attempt_id,
                provider_call_id=request.provider_call_id,
                visibility=f"seat:{decision.seat_id}",
            )
            if (
                profile.budgets.max_cost_usd is not None
                and profile_cost > profile.budgets.max_cost_usd
            ):
                attempt = ActionAttemptRecord(
                    action_attempt_id=action_attempt_id,
                    logical_action_id=decision.logical_action_id,
                    ordinal=ordinal,
                    retry_reason=retry_reason,
                    session_mode=profile.retry_policy.session_mode,
                    status="failed",
                    provider_calls=(provider_record,),
                    tool_invocations=(),
                    canonical_response=None,
                )
                attempts.append(attempt)
                self.evidence.append_event(
                    "action_attempt_failed",
                    {"failure_condition": "cost_budget_exceeded"},
                    phase_instance_id=decision.phase_instance_id,
                    logical_action_id=decision.logical_action_id,
                    action_attempt_id=action_attempt_id,
                )
                self._finish_logical_failure(
                    decision, attempts, "cost_budget_exceeded"
                )
                raise EvidenceIntegrityError(
                    f"cost budget exceeded for profile {profile.profile_id!r}: "
                    f"{profile_cost} > {profile.budgets.max_cost_usd}"
                )
            canonical = CanonicalResponse(
                text=result.output_text,
                finish_reason=result.finish_reason,
                empty=not bool(result.output_text.strip()),
                truncated=result.finish_reason in {"length", "max_output_tokens"},
                provider_call_ids=(request.provider_call_id,),
                tool_invocation_ids=self._harness_tool_invocation_ids(
                    action_attempt_id
                ),
                input_tokens=result.input_tokens,
                cached_input_tokens=result.cached_input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=cost,
                action=self._harness_action(action_attempt_id),
            )
            retry_condition = (
                "length"
                if canonical.truncated
                else ("empty_response" if canonical.empty else None)
            )
            can_retry_response = (
                retry_condition is not None
                and retry_condition in profile.retry_policy.retryable_conditions
                and ordinal + 1 < profile.retry_policy.max_action_attempts
            )
            if can_retry_response:
                attempt = ActionAttemptRecord(
                    action_attempt_id=action_attempt_id,
                    logical_action_id=decision.logical_action_id,
                    ordinal=ordinal,
                    retry_reason=retry_reason,
                    session_mode=profile.retry_policy.session_mode,
                    status="failed",
                    provider_calls=(provider_record,),
                    tool_invocations=(),
                    canonical_response=canonical,
                )
                attempts.append(attempt)
                next_limit = max_output_tokens * 2 if retry_condition == "length" else max_output_tokens
                self.evidence.append_event(
                    "action_attempt_failed",
                    {
                        "failure_condition": retry_condition,
                        "prior_max_output_tokens": max_output_tokens,
                        "next_max_output_tokens": next_limit,
                    },
                    phase_instance_id=decision.phase_instance_id,
                    logical_action_id=decision.logical_action_id,
                    action_attempt_id=action_attempt_id,
                )
                retry_reason = retry_condition
                max_output_tokens = next_limit
                continue

            attempt = ActionAttemptRecord(
                action_attempt_id=action_attempt_id,
                logical_action_id=decision.logical_action_id,
                ordinal=ordinal,
                retry_reason=retry_reason,
                session_mode=profile.retry_policy.session_mode,
                status="succeeded",
                provider_calls=(provider_record,),
                tool_invocations=(),
                canonical_response=canonical,
            )
            attempts.append(attempt)
            self.evidence.append_event(
                "action_attempt_succeeded",
                {"canonical_response": canonical},
                phase_instance_id=decision.phase_instance_id,
                logical_action_id=decision.logical_action_id,
                action_attempt_id=action_attempt_id,
                visibility=f"seat:{decision.seat_id}",
            )
            self._executions[decision.logical_action_id] = LogicalActionExecution(
                logical_action_id=decision.logical_action_id,
                profile_id=profile.profile_id,
                status="awaiting_action_result",
                attempts=tuple(attempts),
                failure_code=None,
            )
            return canonical

        raise EvidenceIntegrityError("action attempt loop exhausted without terminal record")

    async def _wait_before_provider_retry(
        self,
        *,
        decision: DecisionRequest,
        request: ProviderRequest,
        profile: AgentProfile,
        condition: str,
        ordinal: int,
    ) -> None:
        policy = profile.harness.config.get("retry_backoff")
        if policy is None:
            return
        if policy != "exponential_jitter_v1":
            raise EvidenceIntegrityError(f"unsupported retry backoff policy: {policy!r}")
        base_seconds = min(30.0, 2.0 * (2**ordinal))
        jitter_seconds = int(request.provider_call_id[-4:], 16) % 1000 / 1000.0
        delay_seconds = base_seconds + jitter_seconds
        self.evidence.append_event(
            "retry_backoff_started",
            {
                "failure_condition": condition,
                "delay_seconds": delay_seconds,
                "attempt_ordinal": ordinal,
            },
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
        )
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            self.evidence.append_event(
                "logical_action_outcome_unknown",
                {"failure_condition": "interrupted_during_retry_backoff"},
                phase_instance_id=decision.phase_instance_id,
                logical_action_id=decision.logical_action_id,
            )
            current = self._executions[decision.logical_action_id]
            self._executions[decision.logical_action_id] = dataclasses.replace(
                current,
                status="outcome_unknown",
                failure_code="interrupted_during_retry_backoff",
            )
            raise
        self.evidence.append_event(
            "retry_backoff_completed",
            {
                "failure_condition": condition,
                "delay_seconds": delay_seconds,
                "attempt_ordinal": ordinal,
            },
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
        )

    def _record_provider_failure(
        self,
        decision: DecisionRequest,
        profile: AgentProfile,
        request: ProviderRequest,
        action_attempt_id: str,
        ordinal: int,
        retry_reason: str | None,
        attempts: list[ActionAttemptRecord],
        failure: ProviderFailure,
    ) -> bool:
        outcome_unknown = failure.condition in {"timeout", "transport"}
        provider_record = ProviderCallRecord(
            provider_call_id=request.provider_call_id,
            action_attempt_id=action_attempt_id,
            status="outcome_unknown" if outcome_unknown else "failed",
            request_sha256=request.request_sha256,
            requested_model=request.model,
            resolved_model=None,
            response_id=None,
            finish_reason=None,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            failure_condition=failure.condition,
        )
        self.evidence.append_event(
            (
                "provider_call_outcome_unknown"
                if outcome_unknown
                else "provider_call_failed"
            ),
            {
                "failure_condition": failure.condition,
                "message": str(failure),
                "retryable": failure.retryable,
                "status_code": failure.status_code,
                "cost_usd": "unknown" if outcome_unknown else 0.0,
            },
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
            action_attempt_id=action_attempt_id,
            provider_call_id=request.provider_call_id,
        )
        attempt = ActionAttemptRecord(
            action_attempt_id=action_attempt_id,
            logical_action_id=decision.logical_action_id,
            ordinal=ordinal,
            retry_reason=retry_reason,
            session_mode=profile.retry_policy.session_mode,
            status="failed",
            provider_calls=(provider_record,),
            tool_invocations=(),
            canonical_response=None,
        )
        attempts.append(attempt)
        self.evidence.append_event(
            "action_attempt_failed",
            {"failure_condition": failure.condition},
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
            action_attempt_id=action_attempt_id,
        )
        should_retry = (
            failure.retryable
            and failure.condition in profile.retry_policy.retryable_conditions
            and ordinal + 1 < profile.retry_policy.max_action_attempts
        )
        if not should_retry:
            self._finish_logical_failure(decision, attempts, failure.condition)
        else:
            self._executions[decision.logical_action_id] = LogicalActionExecution(
                logical_action_id=decision.logical_action_id,
                profile_id=profile.profile_id,
                status="retrying",
                attempts=tuple(attempts),
                failure_code=failure.condition,
            )
        return should_retry

    def _record_unknown(
        self,
        decision: DecisionRequest,
        provider_call_id: str,
        action_attempt_id: str,
        attempts: list[ActionAttemptRecord],
    ) -> None:
        self.evidence.append_event(
            "provider_call_outcome_unknown",
            {"failure_condition": "interrupted_during_provider_call"},
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
            action_attempt_id=action_attempt_id,
            provider_call_id=provider_call_id,
        )
        self.evidence.append_event(
            "action_attempt_outcome_unknown",
            {"failure_condition": "child_provider_outcome_unknown"},
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
            action_attempt_id=action_attempt_id,
        )
        self.evidence.append_event(
            "logical_action_outcome_unknown",
            {"failure_condition": "action_attempt_outcome_unknown"},
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
        )
        current = self._executions[decision.logical_action_id]
        self._executions[decision.logical_action_id] = dataclasses.replace(
            current,
            status="outcome_unknown",
            attempts=tuple(attempts),
            failure_code="outcome_unknown",
        )

    def _finish_logical_failure(
        self,
        decision: DecisionRequest,
        attempts: Sequence[ActionAttemptRecord],
        failure_code: str,
    ) -> None:
        self.evidence.append_event(
            "logical_action_failed",
            {"failure_condition": failure_code},
            phase_instance_id=decision.phase_instance_id,
            logical_action_id=decision.logical_action_id,
        )
        current = self._executions[decision.logical_action_id]
        self._executions[decision.logical_action_id] = dataclasses.replace(
            current,
            status="failed",
            attempts=tuple(attempts),
            failure_code=failure_code,
        )

    def finalize_logical_action(
        self,
        logical_action_id: str,
        *,
        valid: bool,
        failure_code: str | None,
    ) -> None:
        execution = self._executions.get(logical_action_id)
        if execution is None:
            raise EvidenceIntegrityError(f"logical action was never started: {logical_action_id}")
        if execution.status != "awaiting_action_result":
            raise EvidenceIntegrityError(
                f"logical action cannot be finalized from status {execution.status!r}"
            )
        event_type = (
            "logical_action_succeeded" if valid else "logical_action_agent_action_failure"
        )
        self.evidence.append_event(
            event_type,
            {"valid": valid, "failure_code": failure_code},
            logical_action_id=logical_action_id,
        )
        self._executions[logical_action_id] = dataclasses.replace(
            execution,
            status="succeeded" if valid else "agent_action_failure",
            failure_code=failure_code,
        )

    def finalize_action(self, record: Any) -> None:
        """R3 callback after parsing and legality have produced an envelope."""
        envelope = getattr(record, "envelope", None)
        if envelope is None:
            raise EvidenceIntegrityError("finalize_action requires a logical action record")
        failure_code = None
        if not envelope.valid:
            failure_code = (
                envelope.parse.error_code
                if not envelope.parse.ok
                else envelope.legality.reason
            )
        self.evidence.append_event(
            "action_parsed",
            {"parse_result": envelope.parse},
            phase_instance_id=record.request.phase_instance_id,
            logical_action_id=record.logical_action_id,
            visibility=f"seat:{record.seat_id}",
        )
        if envelope.legality is not None:
            self.evidence.append_event(
                "action_legality_checked",
                {"legality_result": envelope.legality},
                phase_instance_id=record.request.phase_instance_id,
                logical_action_id=record.logical_action_id,
            )
        self.finalize_logical_action(
            record.logical_action_id,
            valid=envelope.valid,
            failure_code=failure_code,
        )

    def fail_logical_action(
        self, logical_action_id: str, *, failure_code: str
    ) -> None:
        """R3 callback when parser or legality execution itself fails."""
        execution = self._executions.get(logical_action_id)
        if execution is None:
            raise EvidenceIntegrityError(f"logical action was never started: {logical_action_id}")
        if execution.status != "awaiting_action_result":
            raise EvidenceIntegrityError(
                f"logical action cannot fail from status {execution.status!r}"
            )
        self.evidence.append_event(
            "logical_action_failed",
            {"failure_condition": failure_code},
            logical_action_id=logical_action_id,
        )
        self._executions[logical_action_id] = dataclasses.replace(
            execution, status="failed", failure_code=failure_code
        )

    def phase_started(
        self,
        *,
        phase_instance_id: str,
        phase: PhaseSpec,
        eligible_actors: tuple[str, ...],
        pre_state_sha256: str,
    ) -> None:
        self.evidence.append_event(
            "phase_instance_started",
            {
                "phase": phase,
                "eligible_actors": eligible_actors,
                "pre_state_sha256": pre_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def transition_applied(
        self,
        *,
        phase_instance_id: str,
        phase: PhaseSpec,
        transition: TransitionResult,
        post_state_sha256: str,
    ) -> None:
        self.evidence.append_event(
            "transition_applied",
            {
                "phase_id": phase.phase_id,
                "transition": transition,
                "post_state_sha256": post_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def phase_completed(self, *, phase_instance: PhaseInstance) -> None:
        self.evidence.append_event(
            "phase_instance_succeeded",
            {
                "phase_id": phase_instance.phase_id,
                "post_state_sha256": phase_instance.post_state_sha256,
                "logical_action_ids": tuple(
                    action.logical_action_id for action in phase_instance.actions
                ),
            },
            phase_instance_id=phase_instance.phase_instance_id,
        )

    def episode_completed(self, *, episode_result: EpisodeResult) -> None:
        self.evidence.append_event(
            "episode_terminated",
            {
                "terminal": episode_result.terminal,
                "logical_action_count": episode_result.logical_action_count,
            },
        )
        self.evidence.append_event(
            "family_outcome_recorded",
            {"outcome": episode_result.outcome},
        )

    def execution_for(self, logical_action_id: str) -> LogicalActionExecution:
        try:
            return self._executions[logical_action_id]
        except KeyError as error:
            raise EvidenceIntegrityError(
                f"unknown logical action: {logical_action_id}"
            ) from error

    def executions(self) -> tuple[LogicalActionExecution, ...]:
        return tuple(self._executions.values())


class ToolExecutor:
    """Evidence-first wrapper for harness-owned tool side effects."""

    def __init__(self, evidence: EvidenceStore) -> None:
        self.evidence = evidence
        self._ordinal = 0

    async def _snapshot_state(
        self, state_reader: Callable[[], Any]
    ) -> tuple[Any, ArtifactRef]:
        value = state_reader()
        if inspect.isawaitable(value):
            value = await value
        try:
            snapshot = json.loads(canonical_json_bytes(value))
        except Exception as error:
            raise EvidenceIntegrityError(
                "state_reader must return canonically serializable state"
            ) from error
        return snapshot, self.evidence.put_artifact(
            snapshot, media_type="application/vnd.aeread.state+json"
        )

    def _state_change(
        self,
        before: tuple[Any, ArtifactRef] | None,
        after: tuple[Any, ArtifactRef] | None,
    ) -> tuple[bool | None, ArtifactRef | None]:
        if before is None or after is None:
            return None, None
        changed = before[1].sha256 != after[1].sha256
        if not changed:
            return False, None
        return True, self.evidence.put_artifact(
            {
                "before_sha256": before[1].sha256,
                "after_sha256": after[1].sha256,
                "before": before[0],
                "after": after[0],
            },
            media_type="application/vnd.aeread.state-diff+json",
        )

    def _record(
        self,
        *,
        tool_invocation_id: str,
        action_attempt_id: str,
        tool_id: str,
        tool_version: str,
        tool_schema_sha256: str,
        input_sha256: str,
        idempotency_supported: bool,
        effect: str,
        status: str,
        result_sha256: str | None,
        failure_condition: str | None,
        before: tuple[Any, ArtifactRef] | None,
        after: tuple[Any, ArtifactRef] | None,
        state_changed: bool | None,
        state_diff_ref: ArtifactRef | None,
        outcome_known: bool,
    ) -> ToolInvocationRecord:
        return ToolInvocationRecord(
            tool_invocation_id=tool_invocation_id,
            action_attempt_id=action_attempt_id,
            tool_id=tool_id,
            tool_version=tool_version,
            tool_schema_sha256=tool_schema_sha256,
            input_sha256=input_sha256,
            idempotency_supported=idempotency_supported,
            status=status,
            result_sha256=result_sha256,
            failure_condition=failure_condition,
            effect=effect,
            state_before_sha256=None if before is None else before[1].sha256,
            state_after_sha256=None if after is None else after[1].sha256,
            state_diff_sha256=(
                None if state_diff_ref is None else state_diff_ref.sha256
            ),
            state_changed=state_changed,
            outcome_known=outcome_known,
        )

    async def _observed_after(
        self, state_reader: Callable[[], Any] | None
    ) -> tuple[Any, ArtifactRef] | None:
        return None if state_reader is None else await self._snapshot_state(state_reader)

    async def _observed_after_or_mark_unknown(
        self,
        *,
        state_reader: Callable[[], Any] | None,
        action_attempt_id: str,
        tool_invocation_id: str,
        effect: str,
        before: tuple[Any, ArtifactRef] | None,
        original_error: BaseException,
    ) -> tuple[Any, ArtifactRef] | None:
        """Observe post-effect state, or record the failure as evidence and re-raise
        *original_error* — never the bookkeeping error — with the bookkeeping error
        chained as its ``__context__``.  A debit may have posted and gone unobserved;
        the evidence must say "unknown", never "never attempted"."""
        try:
            return await self._observed_after(state_reader)
        except BaseException as bookkeeping_error:
            # BaseException, not Exception: asyncio.CancelledError is a direct
            # BaseException subclass, and cancellation is exactly when a
            # mutating call is most likely to have posted unobserved.
            self.evidence.append_event(
                "tool_invocation_outcome_unknown",
                {
                    "failure_condition": "bookkeeping_failed",
                    "effect": effect,
                    "outcome_known": False,
                    "state_before_sha256": (
                        None if before is None else before[1].sha256
                    ),
                },
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
            )
            # Implicit exception chaining sets original_error.__context__ to
            # bookkeeping_error here, since bookkeeping_error is the exception
            # currently being handled.
            raise original_error

    async def invoke(
        self,
        *,
        action_attempt_id: str,
        tool_id: str,
        tool_version: str,
        arguments: Mapping[str, Any],
        implementation: Callable[[Mapping[str, Any]], Awaitable[Any]],
        idempotency_supported: bool,
        effect: str,
        tool_schema_sha256: str,
        state_reader: Callable[[], Any] | None = None,
        tool_invocation_id: str | None = None,
    ) -> tuple[Any, ToolInvocationRecord]:
        if effect not in {"read_only", "mutating"}:
            raise EvidenceIntegrityError("tool effect must be read_only or mutating")
        if state_reader is not None and not callable(state_reader):
            raise EvidenceIntegrityError("state_reader must be callable")
        if effect == "mutating" and state_reader is None:
            raise EvidenceIntegrityError(
                "mutating tool invocation requires a state_reader"
            )
        if (
            not isinstance(tool_schema_sha256, str)
            or len(tool_schema_sha256) != 64
            or any(character not in "0123456789abcdef" for character in tool_schema_sha256)
        ):
            raise EvidenceIntegrityError(
                "tool_schema_sha256 must be 64 lowercase hexadecimal characters"
            )
        if tool_invocation_id is not None and (
            not isinstance(tool_invocation_id, str) or not tool_invocation_id
        ):
            raise EvidenceIntegrityError(
                "tool_invocation_id must be a non-empty string when provided"
            )
        before = await self._observed_after(state_reader)
        if tool_invocation_id is None:
            ordinal = self._ordinal
            self._ordinal += 1
            tool_invocation_id = _stable_id(
                "tool_invocation",
                {
                    "action_attempt_id": action_attempt_id,
                    "tool_id": tool_id,
                    "ordinal": ordinal,
                },
            )
        input_sha256 = _sha256_bytes(canonical_json_bytes(arguments))
        self.evidence.append_event(
            "tool_invocation_started",
            {
                "tool_id": tool_id,
                "tool_version": tool_version,
                "tool_schema_sha256": tool_schema_sha256,
                "arguments": arguments,
                "input_sha256": input_sha256,
                "idempotency_supported": idempotency_supported,
                "effect": effect,
                "state_before_sha256": (
                    None if before is None else before[1].sha256
                ),
            },
            action_attempt_id=action_attempt_id,
            tool_invocation_id=tool_invocation_id,
        )
        try:
            pending = implementation(arguments)
            if not inspect.isawaitable(pending):
                raise TypeError("tool implementation must return an awaitable")
            result = await pending
        except ToolFailure as error:
            after = await self._observed_after_or_mark_unknown(
                state_reader=state_reader,
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
                effect=effect,
                before=before,
                original_error=error,
            )
            state_changed, state_diff_ref = self._state_change(before, after)
            self.evidence.append_event(
                "tool_invocation_failed",
                {
                    "failure_condition": error.condition,
                    "message": str(error),
                    "retryable": error.retryable,
                    "effect": effect,
                    "outcome_known": True,
                    "state_before_sha256": (
                        None if before is None else before[1].sha256
                    ),
                    "state_after_sha256": None if after is None else after[1].sha256,
                    "state_changed": state_changed,
                    "state_diff_sha256": (
                        None if state_diff_ref is None else state_diff_ref.sha256
                    ),
                },
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
            )
            error.record = self._record(
                tool_invocation_id=tool_invocation_id,
                action_attempt_id=action_attempt_id,
                tool_id=tool_id,
                tool_version=tool_version,
                tool_schema_sha256=tool_schema_sha256,
                input_sha256=input_sha256,
                idempotency_supported=idempotency_supported,
                effect=effect,
                status="failed",
                result_sha256=None,
                failure_condition=error.condition,
                before=before,
                after=after,
                state_changed=state_changed,
                state_diff_ref=state_diff_ref,
                outcome_known=True,
            )
            raise
        except asyncio.CancelledError as cancelled_error:
            after = await self._observed_after_or_mark_unknown(
                state_reader=state_reader,
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
                effect=effect,
                before=before,
                original_error=cancelled_error,
            )
            state_changed, state_diff_ref = self._state_change(before, after)
            self.evidence.append_event(
                "tool_invocation_outcome_unknown",
                {
                    "failure_condition": "interrupted_during_tool",
                    "effect": effect,
                    "outcome_known": False,
                    "state_before_sha256": (
                        None if before is None else before[1].sha256
                    ),
                    "state_observed_after_sha256": (
                        None if after is None else after[1].sha256
                    ),
                    "state_observed_changed": state_changed,
                    "state_diff_sha256": (
                        None if state_diff_ref is None else state_diff_ref.sha256
                    ),
                },
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
            )
            raise
        except BaseException as unexpected_error:
            after = await self._observed_after_or_mark_unknown(
                state_reader=state_reader,
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
                effect=effect,
                before=before,
                original_error=unexpected_error,
            )
            state_changed, state_diff_ref = self._state_change(before, after)
            self.evidence.append_event(
                "tool_invocation_outcome_unknown",
                {
                    "failure_condition": "unexpected_tool_interruption",
                    "effect": effect,
                    "outcome_known": False,
                    "state_before_sha256": (
                        None if before is None else before[1].sha256
                    ),
                    "state_observed_after_sha256": (
                        None if after is None else after[1].sha256
                    ),
                    "state_observed_changed": state_changed,
                    "state_diff_sha256": (
                        None if state_diff_ref is None else state_diff_ref.sha256
                    ),
                },
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
            )
            raise
        result_ref = self.evidence.put_artifact(result)
        after = await self._observed_after(state_reader)
        state_changed, state_diff_ref = self._state_change(before, after)
        if effect == "read_only" and state_changed:
            failure = ToolFailure(
                "tool_effect_violation",
                f"read_only tool {tool_id!r} changed observed state",
                retryable=False,
            )
            self.evidence.append_event(
                "tool_invocation_failed",
                {
                    "failure_condition": failure.condition,
                    "message": str(failure),
                    "retryable": False,
                    "effect": effect,
                    "outcome_known": True,
                    "result_sha256": result_ref.sha256,
                    "state_before_sha256": before[1].sha256,
                    "state_after_sha256": after[1].sha256,
                    "state_changed": True,
                    "state_diff_sha256": state_diff_ref.sha256,
                },
                action_attempt_id=action_attempt_id,
                tool_invocation_id=tool_invocation_id,
            )
            failure.record = self._record(
                tool_invocation_id=tool_invocation_id,
                action_attempt_id=action_attempt_id,
                tool_id=tool_id,
                tool_version=tool_version,
                tool_schema_sha256=tool_schema_sha256,
                input_sha256=input_sha256,
                idempotency_supported=idempotency_supported,
                effect=effect,
                status="failed",
                result_sha256=result_ref.sha256,
                failure_condition=failure.condition,
                before=before,
                after=after,
                state_changed=True,
                state_diff_ref=state_diff_ref,
                outcome_known=True,
            )
            raise failure
        self.evidence.append_event(
            "tool_invocation_succeeded",
            {
                "result": result,
                "result_sha256": result_ref.sha256,
                "effect": effect,
                "outcome_known": True,
                "state_before_sha256": (
                    None if before is None else before[1].sha256
                ),
                "state_after_sha256": None if after is None else after[1].sha256,
                "state_changed": state_changed,
                "state_diff_sha256": (
                    None if state_diff_ref is None else state_diff_ref.sha256
                ),
            },
            action_attempt_id=action_attempt_id,
            tool_invocation_id=tool_invocation_id,
        )
        return result, self._record(
            tool_invocation_id=tool_invocation_id,
            action_attempt_id=action_attempt_id,
            tool_id=tool_id,
            tool_version=tool_version,
            tool_schema_sha256=tool_schema_sha256,
            input_sha256=input_sha256,
            idempotency_supported=idempotency_supported,
            effect=effect,
            status="succeeded",
            result_sha256=result_ref.sha256,
            failure_condition=None,
            before=before,
            after=after,
            state_changed=state_changed,
            state_diff_ref=state_diff_ref,
            outcome_known=True,
        )


def _paired_cell_request_seed(
    *, base_seed: int, world_seed: int, replicate_index: int
) -> int:
    payload = ":".join(
        (
            "paired_cell_request_seed_v1",
            str(base_seed),
            str(world_seed),
            str(replicate_index),
        )
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFF_FFFF


async def execute_plan_cell(
    *,
    plan: RunPlan,
    cell_id: str,
    registry: PluginRegistry,
    evidence_root: str | Path,
    prompt_sources: Mapping[str, str | bytes],
    providers: Mapping[str, ProviderClient],
    pricing: Mapping[str, TokenPricing],
    episode_attempt_ordinal: int = 0,
    harnesses: Mapping[str, "Harness"] | None = None,
) -> CellExecution:
    """Execute one sealed R2 cell through the R3 scheduler and R4 adapter."""
    from ..run.layout import RunLayout

    verify_run_plan(plan)
    layout = RunLayout(Path(evidence_root), plan.run_plan_id)
    plan_path = layout.plan_path
    expected_plan_bytes = canonical_json_bytes(plan)
    if plan_path.exists():
        if plan_path.read_bytes() != expected_plan_bytes:
            raise EvidenceIntegrityError(
                f"existing RunPlan bytes differ from {plan.run_plan_id}: {plan_path}"
            )
    else:
        write_run_plan(plan, plan_path)
    if not isinstance(registry, PluginRegistry):
        raise EvidenceIntegrityError("registry must be a PluginRegistry")
    if isinstance(episode_attempt_ordinal, bool) or not isinstance(
        episode_attempt_ordinal, int
    ):
        raise EvidenceIntegrityError("episode_attempt_ordinal must be an integer")
    if episode_attempt_ordinal < 0:
        raise EvidenceIntegrityError("episode_attempt_ordinal cannot be negative")
    cell = next((item for item in plan.cells if item.cell_id == cell_id), None)
    if cell is None:
        raise EvidenceIntegrityError(f"RunPlan contains no cell {cell_id!r}")
    case = next((item for item in plan.cases if item.case_id == cell.case_id), None)
    family = next(
        (
            item
            for item in plan.families
            if item.family.id == cell.family_id
            and item.family.version == cell.family_version
        ),
        None,
    )
    if case is None or family is None:
        raise EvidenceIntegrityError(
            f"sealed plan cannot resolve case/family for cell {cell.cell_id!r}"
        )
    try:
        plugin = registry.resolve_manifest(family)
    except PluginRegistryError as error:
        raise EvidenceIntegrityError(
            f"cannot resolve plugin for cell {cell.cell_id!r}: {error}"
        ) from error
    profile_by_id = {profile.profile_id: profile for profile in plan.agent_profiles}
    missing_profiles = sorted(set(cell.profile_by_seat.values()) - set(profile_by_id))
    if missing_profiles:
        raise EvidenceIntegrityError(
            f"cell references missing profiles: {missing_profiles}"
        )
    selected_profiles = tuple(
        profile_by_id[profile_id]
        for profile_id in sorted(set(cell.profile_by_seat.values()))
    )
    request_seed_by_profile: dict[str, int] = {}
    for profile in selected_profiles:
        seed_source = profile.harness.config.get("request_seed_source")
        if seed_source is None:
            continue
        if seed_source != "paired_cell_v1":
            raise EvidenceIntegrityError(
                f"unsupported request seed source for {profile.profile_id!r}: "
                f"{seed_source!r}"
            )
        base_seed = profile.harness.config.get("request_seed_base")
        if (
            isinstance(base_seed, bool)
            or not isinstance(base_seed, int)
            or base_seed < 0
        ):
            raise EvidenceIntegrityError(
                "paired_cell_v1 requires a non-negative request_seed_base for "
                f"{profile.profile_id!r}"
            )
        request_seed_by_profile[profile.profile_id] = _paired_cell_request_seed(
            base_seed=base_seed,
            world_seed=cell.world_seed,
            replicate_index=cell.replicate_index,
        )
    episode_id = episode_id_for_cell(cell)
    episode_attempt_id = _stable_id(
        "episode_attempt",
        {"episode_id": episode_id, "ordinal": episode_attempt_ordinal},
    )
    destination = layout.attempt_dir(cell.cell_id, episode_attempt_id)
    evidence = EvidenceStore(
        destination,
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=episode_id,
        episode_attempt_id=episode_attempt_id,
    )
    from ..model_call.harness import AttemptExecutor, default_harnesses

    executor = AttemptExecutor(
        evidence=evidence,
        profiles=selected_profiles,
        prompt_sources=prompt_sources,
        providers=providers,
        pricing=pricing,
        harnesses=default_harnesses() if harnesses is None else harnesses,
        request_seed_by_profile=request_seed_by_profile,
    )
    result = await run_episode(
        cell=cell,
        case=case,
        plugin=plugin,
        response_source=executor,
    )
    evidence.audit_reconciliation()
    return CellExecution(
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id=episode_attempt_id,
        episode_result=result,
        evidence=evidence,
        action_executions=executor.executions(),
        total_cost_usd=executor.total_cost_usd,
    )


__all__ = [
    "ActionAttemptRecord",
    "ArtifactRef",
    "CanonicalResponse",
    "ClaudeCodePrintClient",
    "ConcurrentEvidenceWriterError",
    "CellExecution",
    "EvidenceIntegrityError",
    "EvidenceSeal",
    "EvidenceSealedError",
    "EvidenceStore",
    "Event",
    "LogicalActionExecution",
    "MinimalChatExecutor",
    "OpenAIResponsesClient",
    "OpenRouterChatClient",
    "ProviderCallRecord",
    "ProviderClient",
    "ProviderFailure",
    "ProviderRequest",
    "ProviderResult",
    "TokenPricing",
    "ToolExecutor",
    "ToolFailure",
    "ToolInvocationRecord",
    "execute_plan_cell",
]
