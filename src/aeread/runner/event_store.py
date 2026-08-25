"""Durable append-only evidence and episode-scoped artifact storage."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import TypeVar
import uuid

from pydantic import BaseModel, ValidationError

from aeread.sdk.v1 import (
    ArtifactRef,
    EpisodeEvent,
    EventIdentity,
    SealedEvidenceView,
    canonical_json_bytes,
    content_sha256,
)


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SEAT_AUDIENCE_RE = re.compile(r"^seat:[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_META_SUFFIX = ".meta.json"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class EvidenceStoreError(Exception):
    """Base class for durable evidence failures."""


class EventIntegrityError(EvidenceStoreError):
    """The event log or its durable anchor cannot be verified exactly."""


class ArtifactIntegrityError(EvidenceStoreError):
    """An artifact, generation anchor, or metadata cannot be verified exactly."""


class ConcurrentWriterError(EvidenceStoreError):
    """Another writer already owns this event log."""


class EvidenceSealedError(EvidenceStoreError):
    """The event or artifact generation has permanently stopped accepting writes."""


class InvalidEvidenceInput(EvidenceStoreError, ValueError):
    """Caller input cannot cross the durable evidence boundary."""


def _safe_model(value: object, model_type: type[_ModelT], label: str) -> _ModelT:
    """Revalidate even unsafe ``model_copy`` values and translate all boundary errors."""

    try:
        materialized = (
            value.model_dump(mode="json", warnings="error")
            if isinstance(value, BaseModel)
            else value
        )
        return model_type.model_validate(materialized)
    except Exception as exc:
        raise InvalidEvidenceInput(f"{label} is invalid") from exc


def _domain_digest(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + b"\0" + canonical_json_bytes(value)).hexdigest()


def _event_id(identity: EventIdentity, sequence: int) -> str:
    return _domain_digest(
        b"aeread.event_id/1",
        {"identity": identity.model_dump(mode="json"), "sequence": sequence},
    )


def _event_hash_basis(event: EpisodeEvent) -> dict[str, object]:
    return {
        "spec_version": event.spec_version,
        "event_id": event.event_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "identity": event.identity.model_dump(mode="json"),
        "visibility": event.visibility,
        "payload_sha256": event.payload_sha256,
        "prior_event_hash": event.prior_event_hash,
    }


def recompute_event_hash(event: EpisodeEvent) -> str:
    """Recompute the v1 event hash shared by verify, projection, and replay."""

    checked = _safe_model(event, EpisodeEvent, "event")
    try:
        return _domain_digest(b"aeread.event/1", _event_hash_basis(checked))
    except Exception as exc:
        raise InvalidEvidenceInput("event cannot be canonically hashed") from exc


def _artifact_sort_key(ref: ArtifactRef) -> tuple[str, str, int]:
    return ref.sha256, ref.media_type, ref.size_bytes


def _artifact_metadata(ref: ArtifactRef) -> dict[str, object]:
    return {
        "spec_version": "aeread.artifact_meta/1",
        "sha256": ref.sha256,
        "media_type": ref.media_type,
        "size_bytes": ref.size_bytes,
    }


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EvidenceStoreError(f"cannot inspect {path.name}") from exc


def _require_regular(
    path: Path, *, label: str, error_type: type[EvidenceStoreError]
) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise error_type(f"{label} is missing or unreadable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise error_type(f"{label} must be a non-symlink regular file")
    return info


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(f"not a directory: {path}")
        os.fsync(fd)
    finally:
        os.close(fd)


def _ensure_real_directory(path: Path, *, error_type: type[EvidenceStoreError]) -> None:
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW
    try:
        directory_fd = os.open(absolute.anchor, flags)
    except OSError as exc:
        raise error_type("cannot anchor managed directory traversal") from exc
    try:
        for component in absolute.parts[1:]:
            try:
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                    child_fd = os.open(component, flags, dir_fd=directory_fd)
                except OSError as exc:
                    raise error_type(
                        f"cannot durably create managed directory component {component!r}"
                    ) from exc
            except OSError as exc:
                raise error_type(
                    f"managed directory ancestor {component!r} is not a real directory"
                ) from exc
            os.close(directory_fd)
            directory_fd = child_fd
    finally:
        os.close(directory_fd)


def _exclusive_temp_write(directory: Path, data: bytes) -> Path:
    temp = directory / f".tmp-{uuid.uuid4().hex}"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    try:
        try:
            view = memoryview(data)
            written = 0
            while written < len(view):
                count = os.write(fd, view[written:])
                if count <= 0:
                    raise OSError("incomplete temporary write")
                written += count
            os.fsync(fd)
        except Exception:
            temp.unlink(missing_ok=True)
            _fsync_directory(directory)
            raise
    finally:
        os.close(fd)
    return temp


def _publish_without_overwrite(temp: Path, target: Path) -> None:
    if _lstat(target) is not None:
        raise FileExistsError(target)
    os.link(temp, target, follow_symlinks=False)


def _atomic_replace(path: Path, value: object) -> None:
    existing = _lstat(path)
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise EvidenceStoreError(f"{path.name} must be a regular file")
    try:
        encoded = canonical_json_bytes(value)
    except Exception as exc:
        raise InvalidEvidenceInput(f"{path.name} cannot be canonicalized") from exc
    temp = _exclusive_temp_write(path.parent, encoded)
    replaced = False
    try:
        current = _lstat(path)
        if current is not None and not stat.S_ISREG(current.st_mode):
            raise EvidenceStoreError(f"{path.name} must be a regular file")
        os.replace(temp, path)
        replaced = True
        _fsync_directory(path.parent)
    finally:
        if not replaced:
            temp.unlink(missing_ok=True)
            _fsync_directory(path.parent)


def _canonical_object(
    path: Path, *, label: str, error_type: type[EvidenceStoreError]
) -> dict[str, object]:
    _require_regular(path, label=label, error_type=error_type)
    flags = os.O_RDONLY | _NOFOLLOW
    try:
        fd = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise error_type(f"{label} must be a regular file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
        value = json.loads(raw)
    except error_type:
        raise
    except Exception as exc:
        raise error_type(f"{label} is malformed") from exc
    if type(value) is not dict or raw != canonical_json_bytes(value):
        raise error_type(f"{label} must be canonical JSON object")
    return value


class ArtifactStore:
    """Content-addressed artifacts in one sealable episode generation."""

    _GENERATION_VERSION = "aeread.artifact_generation/1"

    def __init__(self, root: Path, identity: EventIdentity) -> None:
        self.root = root
        self.identity = identity
        self.artifact_dir = root / "artifacts"
        self.object_dir = self.artifact_dir / "sha256"
        self._lock_path = self.artifact_dir / "generation.lock"
        self._state_path = self.artifact_dir / "generation.json"
        self._thread_lock = threading.RLock()
        self._poisoned = False

    @classmethod
    def open(
        cls, root: Path, *, identity: EventIdentity | None = None
    ) -> "ArtifactStore":
        if not isinstance(root, Path):
            raise InvalidEvidenceInput("artifact root must be a pathlib.Path")
        if identity is None:
            raise InvalidEvidenceInput(
                "ArtifactStore.open requires identity before creating a generation"
            )
        checked_identity = _safe_model(identity, EventIdentity, "artifact identity")
        for directory in (root, root / "artifacts", root / "artifacts" / "sha256"):
            _ensure_real_directory(directory, error_type=ArtifactIntegrityError)
        store = cls(root, checked_identity)
        for managed_file, label in (
            (store._lock_path, "artifact generation lock"),
            (store._state_path, "artifact generation anchor"),
        ):
            info = _lstat(managed_file)
            if info is not None and not stat.S_ISREG(info.st_mode):
                raise ArtifactIntegrityError(f"{label} must be a regular file")
        with store._guard():
            if _lstat(store._state_path) is None:
                if any(store.object_dir.iterdir()):
                    raise ArtifactIntegrityError(
                        "artifact objects exist without a generation anchor"
                    )
                store._write_generation_unlocked(
                    {
                        "spec_version": cls._GENERATION_VERSION,
                        "identity": checked_identity.model_dump(mode="json"),
                        "status": "open",
                        "artifact_count": 0,
                        "artifact_root_sha256": None,
                    }
                )
            else:
                store._read_generation_unlocked()
        return store

    @contextmanager
    def _guard(self) -> Iterator[None]:
        with self._thread_lock:
            info = _lstat(self._lock_path)
            created = info is None
            if info is not None and not stat.S_ISREG(info.st_mode):
                raise ArtifactIntegrityError("artifact generation lock is not regular")
            flags = os.O_RDWR | _NOFOLLOW
            if created:
                flags |= os.O_CREAT | os.O_EXCL
            fd = os.open(self._lock_path, flags, 0o600)
            try:
                if created:
                    os.fsync(fd)
                    _fsync_directory(self.artifact_dir)
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _read_generation_unlocked(self) -> dict[str, object]:
        value = _canonical_object(
            self._state_path,
            label="artifact generation anchor",
            error_type=ArtifactIntegrityError,
        )
        if (
            set(value)
            != {
                "spec_version",
                "identity",
                "status",
                "artifact_count",
                "artifact_root_sha256",
            }
            or value.get("spec_version") != self._GENERATION_VERSION
        ):
            raise ArtifactIntegrityError(
                "artifact generation anchor has unexpected fields"
            )
        status = value.get("status")
        count = value.get("artifact_count")
        root = value.get("artifact_root_sha256")
        try:
            owner = EventIdentity.model_validate(value.get("identity"))
        except Exception as exc:
            raise ArtifactIntegrityError(
                "artifact generation owner identity is invalid"
            ) from exc
        if owner != self.identity:
            raise InvalidEvidenceInput(
                "artifact generation belongs to a different event identity"
            )
        if status not in {"open", "sealed"} or type(count) is not int or count < 0:
            raise ArtifactIntegrityError("artifact generation anchor is invalid")
        if status == "open" and (count != 0 or root is not None):
            raise ArtifactIntegrityError(
                "open artifact generation cannot claim a final root"
            )
        if status == "sealed" and (
            type(root) is not str or not _DIGEST_RE.fullmatch(root)
        ):
            raise ArtifactIntegrityError(
                "sealed artifact generation needs a valid root"
            )
        return value

    def _write_generation_unlocked(self, value: Mapping[str, object]) -> None:
        try:
            _atomic_replace(self._state_path, dict(value))
        except Exception as exc:
            self._poisoned = True
            if isinstance(exc, InvalidEvidenceInput):
                raise
            raise ArtifactIntegrityError(
                "artifact generation anchor update failed"
            ) from exc

    def _paths(self, digest: str) -> tuple[Path, Path]:
        if type(digest) is not str or not _DIGEST_RE.fullmatch(digest):
            raise InvalidEvidenceInput("artifact digest must be lower-case SHA-256")
        return self.object_dir / digest, self.object_dir / f"{digest}{_META_SUFFIX}"

    def _read_metadata(self, path: Path) -> ArtifactRef:
        value = _canonical_object(
            path, label="artifact metadata", error_type=ArtifactIntegrityError
        )
        if set(value) != {"spec_version", "sha256", "media_type", "size_bytes"}:
            raise ArtifactIntegrityError("artifact metadata has unexpected fields")
        if value.get("spec_version") != "aeread.artifact_meta/1":
            raise ArtifactIntegrityError("artifact metadata version is unsupported")
        try:
            return ArtifactRef(
                sha256=value["sha256"],
                media_type=value["media_type"],
                size_bytes=value["size_bytes"],
            )
        except Exception as exc:
            raise ArtifactIntegrityError("artifact metadata is invalid") from exc

    def _verify_unlocked(self, ref: ArtifactRef) -> None:
        content_path, metadata_path = self._paths(ref.sha256)
        info = _require_regular(
            content_path, label="artifact content", error_type=ArtifactIntegrityError
        )
        stored_ref = self._read_metadata(metadata_path)
        if stored_ref != ref or info.st_size != ref.size_bytes:
            raise ArtifactIntegrityError(
                "artifact metadata does not match requested ref"
            )
        fd = os.open(content_path, os.O_RDONLY | _NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ArtifactIntegrityError("artifact content must be regular")
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
        finally:
            os.close(fd)
        if total != ref.size_bytes or digest.hexdigest() != ref.sha256:
            raise ArtifactIntegrityError(
                "artifact content does not match its reference"
            )

    def _list_refs_unlocked(self) -> tuple[ArtifactRef, ...]:
        try:
            entries = tuple(self.object_dir.iterdir())
        except OSError as exc:
            raise ArtifactIntegrityError("artifact directory is unreadable") from exc
        names = {entry.name for entry in entries}
        for name in names:
            digest = name[: -len(_META_SUFFIX)] if name.endswith(_META_SUFFIX) else name
            if not _DIGEST_RE.fullmatch(digest):
                raise ArtifactIntegrityError(f"unexpected artifact entry: {name}")
        digests = {name for name in names if _DIGEST_RE.fullmatch(name)}
        expected = digests | {f"{digest}{_META_SUFFIX}" for digest in digests}
        if names != expected:
            raise ArtifactIntegrityError("artifact content and metadata are incomplete")
        refs: list[ArtifactRef] = []
        for digest in sorted(digests):
            ref = self._read_metadata(self._paths(digest)[1])
            if ref.sha256 != digest:
                raise ArtifactIntegrityError("artifact metadata digest mismatches path")
            self._verify_unlocked(ref)
            refs.append(ref)
        return tuple(sorted(refs, key=_artifact_sort_key))

    def put(self, data: bytes, media_type: str) -> ArtifactRef:
        if type(data) is not bytes:
            raise InvalidEvidenceInput("artifact data must be exact bytes")
        if type(media_type) is not str or not media_type:
            raise InvalidEvidenceInput(
                "artifact media_type must be a non-empty exact string"
            )
        with self._guard():
            if self._poisoned:
                raise ArtifactIntegrityError("artifact store is poisoned")
            generation = self._read_generation_unlocked()
            if generation["status"] == "sealed":
                raise EvidenceSealedError("artifact generation has been sealed")
            ref = ArtifactRef(
                sha256=hashlib.sha256(data).hexdigest(),
                media_type=media_type,
                size_bytes=len(data),
            )
            content_path, metadata_path = self._paths(ref.sha256)
            content_temp: Path | None = None
            metadata_temp: Path | None = None
            try:
                content_temp = _exclusive_temp_write(self.object_dir, data)
                metadata_temp = _exclusive_temp_write(
                    self.object_dir, canonical_json_bytes(_artifact_metadata(ref))
                )
                try:
                    _publish_without_overwrite(content_temp, content_path)
                except FileExistsError:
                    pass
                try:
                    _publish_without_overwrite(metadata_temp, metadata_path)
                except FileExistsError:
                    pass
            finally:
                for temp in (content_temp, metadata_temp):
                    if temp is not None:
                        temp.unlink(missing_ok=True)
                _fsync_directory(self.object_dir)
            self._verify_unlocked(ref)
            return ref

    def verify(self, ref: ArtifactRef) -> None:
        checked = _safe_model(ref, ArtifactRef, "artifact ref")
        with self._guard():
            self._read_generation_unlocked()
            self._verify_unlocked(checked)

    def get(self, ref: ArtifactRef) -> bytes:
        checked = _safe_model(ref, ArtifactRef, "artifact ref")
        with self._guard():
            self._read_generation_unlocked()
            self._verify_unlocked(checked)
            fd = os.open(self._paths(checked.sha256)[0], os.O_RDONLY | _NOFOLLOW)
            try:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                os.close(fd)

    def list_refs(self) -> tuple[ArtifactRef, ...]:
        with self._guard():
            generation = self._read_generation_unlocked()
            refs = self._list_refs_unlocked()
            if generation["status"] == "sealed":
                if generation["artifact_count"] != len(refs) or generation[
                    "artifact_root_sha256"
                ] != _artifact_root(refs):
                    raise ArtifactIntegrityError(
                        "sealed artifact generation root mismatch"
                    )
            return refs

    def _freeze_unlocked(self) -> tuple[ArtifactRef, ...]:
        generation = self._read_generation_unlocked()
        refs = self._list_refs_unlocked()
        root = _artifact_root(refs)
        if generation["status"] == "sealed":
            if (
                generation["artifact_count"] != len(refs)
                or generation["artifact_root_sha256"] != root
            ):
                raise ArtifactIntegrityError("sealed artifact generation root mismatch")
            return refs
        self._write_generation_unlocked(
            {
                "spec_version": self._GENERATION_VERSION,
                "identity": self.identity.model_dump(mode="json"),
                "status": "sealed",
                "artifact_count": len(refs),
                "artifact_root_sha256": root,
            }
        )
        return refs

    def _is_frozen_unlocked(self) -> bool:
        return self._read_generation_unlocked()["status"] == "sealed"


def _validate_visibility(value: object, *, allow_full: bool = False) -> str:
    allowed = {"public", "evaluator_only"}
    if allow_full:
        allowed |= {"full", "evaluator"}
    if type(value) is not str or (
        value not in allowed and not _SEAT_AUDIENCE_RE.fullmatch(value)
    ):
        raise InvalidEvidenceInput("invalid evidence visibility or audience")
    return value


def _utc_timestamp(clock: Callable[[], datetime]) -> str:
    try:
        value = clock()
    except Exception as exc:
        raise InvalidEvidenceInput("evidence clock failed") from exc
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != timezone.utc.utcoffset(value)
    ):
        raise InvalidEvidenceInput("evidence clock must return an aware UTC datetime")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _discover_artifact_refs(value: object) -> tuple[ArtifactRef, ...]:
    found: dict[tuple[str, str, int], ArtifactRef] = {}

    def visit(item: object) -> None:
        try:
            if isinstance(item, Mapping):
                materialized = dict(item.items())
                if (
                    set(materialized)
                    == {
                        "spec_version",
                        "sha256",
                        "media_type",
                        "size_bytes",
                    }
                    and materialized.get("spec_version") == "aeread.sdk_record/1"
                ):
                    ref = ArtifactRef.model_validate(materialized)
                    found[_artifact_sort_key(ref)] = ref
                    return
                for nested in materialized.values():
                    visit(nested)
            elif isinstance(item, (list, tuple)):
                for nested in item:
                    visit(nested)
        except Exception as exc:
            raise InvalidEvidenceInput(
                "payload contains an invalid artifact ref"
            ) from exc

    visit(value)
    return tuple(found[key] for key in sorted(found))


def _event_root(
    events: tuple[EpisodeEvent, ...], identity: EventIdentity | None = None
) -> str:
    bound_identity = identity or (events[0].identity if events else None)
    return _domain_digest(
        b"aeread.event_root/1",
        {
            "identity": (
                bound_identity.model_dump(mode="json") if bound_identity else None
            ),
            "event_count": len(events),
            "event_hashes": [event.event_hash for event in events],
        },
    )


def _artifact_root(refs: tuple[ArtifactRef, ...]) -> str:
    return _domain_digest(
        b"aeread.artifact_root/1",
        [ref.model_dump(mode="json") for ref in sorted(refs, key=_artifact_sort_key)],
    )


def _verify_referenced_artifacts_unlocked(
    artifacts: ArtifactStore,
    events: tuple[EpisodeEvent, ...],
    refs: tuple[ArtifactRef, ...],
) -> None:
    """Bind event references to one locked artifact-generation snapshot."""

    committed = {_artifact_sort_key(ref): ref for ref in refs}
    for event in events:
        for ref in _discover_artifact_refs(event.payload):
            if _artifact_sort_key(ref) not in committed:
                raise ArtifactIntegrityError(
                    "event references artifact absent from the generation"
                )
            artifacts._verify_unlocked(ref)


def _validate_joint_chain(
    events: tuple[EpisodeEvent, ...],
    *,
    expected_identity: EventIdentity | None,
    require_visible: bool,
) -> EventIdentity | None:
    identity = expected_identity
    prior_hash: str | None = None
    for sequence, event in enumerate(events):
        if require_visible and (not event.payload_visible or event.payload is None):
            raise EventIntegrityError("on-disk/full events must have visible payloads")
        if event.sequence != sequence:
            raise EventIntegrityError("event sequence is not contiguous from zero")
        if identity is None:
            identity = event.identity
        elif event.identity != identity:
            raise EventIntegrityError("joint event log contains multiple identities")
        if event.event_id != _event_id(event.identity, event.sequence):
            raise EventIntegrityError("event ID does not match identity and sequence")
        if event.prior_event_hash != prior_hash:
            raise EventIntegrityError("event prior hash does not match predecessor")
        try:
            actual_hash = recompute_event_hash(event)
        except InvalidEvidenceInput as exc:
            raise EventIntegrityError("event cannot be revalidated") from exc
        if actual_hash != event.event_hash:
            raise EventIntegrityError("event hash does not match event content")
        prior_hash = event.event_hash
    return identity


_EVENT_STATE_VERSION = "aeread.event_state/1"


def _event_state_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.state.json")


def _seal_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.sealed.json")


def _event_state(
    *,
    identity: EventIdentity | None,
    events: tuple[EpisodeEvent, ...],
    status: str,
    artifact_root_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "spec_version": _EVENT_STATE_VERSION,
        "status": status,
        "identity": identity.model_dump(mode="json") if identity else None,
        "event_count": len(events),
        "last_event_hash": events[-1].event_hash if events else None,
        "event_root_sha256": _event_root(events, identity),
        "artifact_root_sha256": artifact_root_sha256,
    }


def _read_event_state(path: Path) -> dict[str, object]:
    value = _canonical_object(
        _event_state_path(path),
        label="event high-water anchor",
        error_type=EventIntegrityError,
    )
    expected = {
        "spec_version",
        "status",
        "identity",
        "event_count",
        "last_event_hash",
        "event_root_sha256",
        "artifact_root_sha256",
    }
    if set(value) != expected or value.get("spec_version") != _EVENT_STATE_VERSION:
        raise EventIntegrityError("event high-water anchor has unexpected fields")
    if value.get("status") not in {"open", "sealing", "sealed", "poisoned"}:
        raise EventIntegrityError("event high-water anchor status is invalid")
    if type(value.get("event_count")) is not int or value["event_count"] < 0:
        raise EventIntegrityError("event high-water count is invalid")
    try:
        identity = (
            None
            if value["identity"] is None
            else EventIdentity.model_validate(value["identity"])
        )
    except Exception as exc:
        raise EventIntegrityError("event high-water identity is invalid") from exc
    if identity is None:
        raise EventIntegrityError("event high-water anchor must bind an identity")
    value["identity"] = identity
    for field in ("last_event_hash", "event_root_sha256", "artifact_root_sha256"):
        item = value[field]
        if item is not None and (
            type(item) is not str or not _DIGEST_RE.fullmatch(item)
        ):
            raise EventIntegrityError(f"event high-water {field} is invalid")
    if value["event_root_sha256"] is None:
        raise EventIntegrityError("event high-water anchor must bind an event root")
    return value


def _read_event_rows(path: Path) -> tuple[EpisodeEvent, ...]:
    _require_regular(path, label="event log", error_type=EventIntegrityError)
    fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise EventIntegrityError("event log must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    if raw and not raw.endswith(b"\n"):
        raise EventIntegrityError("event log has a partial final row")
    events: list[EpisodeEvent] = []
    for line in raw.splitlines(keepends=True):
        row = line[:-1]
        if not row:
            raise EventIntegrityError("event log contains a blank row")
        try:
            decoded = json.loads(row)
            event = EpisodeEvent.model_validate(decoded)
            canonical = canonical_json_bytes(event)
        except Exception as exc:
            raise EventIntegrityError("event row is malformed") from exc
        if row != canonical:
            raise EventIntegrityError("event row is not canonical JSON")
        events.append(event)
    return tuple(events)


def _verify_anchor(
    path: Path, events: tuple[EpisodeEvent, ...]
) -> tuple[dict[str, object], EventIdentity | None]:
    state = _read_event_state(path)
    identity = state["identity"]
    assert identity is None or isinstance(identity, EventIdentity)
    chain_identity = _validate_joint_chain(
        events, expected_identity=identity, require_visible=True
    )
    if (
        state["event_count"] != len(events)
        or state["last_event_hash"] != (events[-1].event_hash if events else None)
        or state["event_root_sha256"] != _event_root(events, chain_identity)
    ):
        raise EventIntegrityError(
            "event log does not match its durable high-water anchor"
        )
    if state["status"] in {"sealing", "poisoned"}:
        raise EventIntegrityError(
            "event log is fail-closed after interrupted evidence I/O"
        )
    return state, chain_identity


def _seal_marker(path: Path) -> dict[str, object]:
    marker = _canonical_object(
        _seal_path(path), label="event seal marker", error_type=EventIntegrityError
    )
    if (
        set(marker)
        != {
            "spec_version",
            "event_count",
            "event_root_sha256",
            "artifact_root_sha256",
        }
        or marker.get("spec_version") != "aeread.event_seal/1"
    ):
        raise EventIntegrityError("event seal marker has unexpected fields")
    if type(marker["event_count"]) is not int or marker["event_count"] < 0:
        raise EventIntegrityError("event seal count is invalid")
    for field in ("event_root_sha256", "artifact_root_sha256"):
        if type(marker[field]) is not str or not _DIGEST_RE.fullmatch(marker[field]):
            raise EventIntegrityError("event seal root is invalid")
    return marker


class EventStore:
    """Single-writer log with durable high-water and finalization anchors."""

    OPEN = "open"
    POISONED = "poisoned"
    SEALED = "sealed"
    CLOSED = "closed"

    def __init__(
        self,
        path: Path,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime],
        fd: int | None,
        events: tuple[EpisodeEvent, ...],
        identity: EventIdentity | None,
        lifecycle: str,
    ) -> None:
        self.path = path
        self.artifacts = artifacts
        self._clock = clock
        self._fd = fd
        self._events = events
        self._identity = identity
        self._lifecycle = lifecycle
        self._thread_lock = threading.RLock()

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        identity: EventIdentity | None = None,
    ) -> "EventStore":
        if (
            not isinstance(path, Path)
            or not isinstance(artifacts, ArtifactStore)
            or not callable(clock)
        ):
            raise InvalidEvidenceInput("invalid EventStore.open input")
        if identity is None:
            raise InvalidEvidenceInput(
                "EventStore.open requires identity to bind the empty evidence root"
            )
        checked_identity = _safe_model(identity, EventIdentity, "identity")
        artifact_identity = _safe_model(
            artifacts.identity, EventIdentity, "artifact identity"
        )
        if artifact_identity != checked_identity:
            raise InvalidEvidenceInput(
                "event and artifact stores must share one identity"
            )
        with artifacts._guard():
            artifacts._read_generation_unlocked()
        _ensure_real_directory(path.parent, error_type=EventIntegrityError)
        path_info = _lstat(path)
        state_info = _lstat(_event_state_path(path))
        marker_info = _lstat(_seal_path(path))
        if path_info is not None and not stat.S_ISREG(path_info.st_mode):
            raise EventIntegrityError("event log must be a non-symlink regular file")
        if state_info is not None and not stat.S_ISREG(state_info.st_mode):
            raise EventIntegrityError("event state must be a non-symlink regular file")
        if marker_info is not None and not stat.S_ISREG(marker_info.st_mode):
            raise EventIntegrityError("event seal marker must be a regular file")
        created = path_info is None
        if created and (state_info is not None or marker_info is not None):
            raise EventIntegrityError("event anchors exist without an event log")
        if not created and state_info is None:
            raise EventIntegrityError("event log is missing its durable state anchor")
        flags = os.O_RDWR | os.O_APPEND | _NOFOLLOW
        if created:
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise EventIntegrityError("event log must be regular")
            if created:
                os.fsync(fd)
                _fsync_directory(path.parent)
                try:
                    _atomic_replace(
                        _event_state_path(path),
                        _event_state(
                            identity=checked_identity,
                            events=(),
                            status="open",
                        ),
                    )
                except Exception:
                    os.close(fd)
                    fd = -1
                    path.unlink(missing_ok=True)
                    _event_state_path(path).unlink(missing_ok=True)
                    _fsync_directory(path.parent)
                    raise
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise ConcurrentWriterError(
                        "event log already has a writer"
                    ) from exc
                raise
            events = _read_event_rows(path)
            state, anchored_identity = _verify_anchor(path, events)
            if checked_identity is not None:
                if (
                    anchored_identity is None
                    and not events
                    and state["status"] == "open"
                ):
                    _atomic_replace(
                        _event_state_path(path),
                        _event_state(
                            identity=checked_identity,
                            events=(),
                            status="open",
                        ),
                    )
                    anchored_identity = checked_identity
                elif anchored_identity != checked_identity:
                    raise InvalidEvidenceInput(
                        "opened identity does not match event anchor"
                    )
            if state["status"] == "sealed":
                cls._verify_final(path, artifacts, events, anchored_identity, state)
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                fd = -1
                return cls(
                    path,
                    artifacts,
                    clock,
                    None,
                    events,
                    anchored_identity,
                    cls.SEALED,
                )
            if marker_info is not None:
                raise EventIntegrityError("open event state conflicts with seal marker")
            with artifacts._guard():
                if artifacts._is_frozen_unlocked():
                    raise EventIntegrityError(
                        "open event log has a frozen artifact generation"
                    )
            return cls(
                path,
                artifacts,
                clock,
                fd,
                events,
                anchored_identity,
                cls.OPEN,
            )
        except Exception:
            if fd >= 0:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            raise

    @classmethod
    def _verify_final(
        cls,
        path: Path,
        artifacts: ArtifactStore,
        events: tuple[EpisodeEvent, ...],
        identity: EventIdentity | None,
        state: Mapping[str, object],
    ) -> SealedEvidenceView:
        if identity is None:
            raise EventIntegrityError("final evidence is missing its bound identity")
        if artifacts.identity != identity:
            raise EventIntegrityError(
                "event and artifact evidence have different identities"
            )
        marker = _seal_marker(path)
        with artifacts._guard():
            generation = artifacts._read_generation_unlocked()
            if generation["status"] != "sealed":
                raise ArtifactIntegrityError("final evidence requires frozen artifacts")
            refs = artifacts._list_refs_unlocked()
            _verify_referenced_artifacts_unlocked(artifacts, events, refs)
            artifact_root = _artifact_root(refs)
            if (
                generation["artifact_count"] != len(refs)
                or generation["artifact_root_sha256"] != artifact_root
            ):
                raise ArtifactIntegrityError("artifact generation final root mismatch")
        event_root = _event_root(events, identity)
        if (
            marker["event_count"] != len(events)
            or marker["event_root_sha256"] != event_root
            or marker["artifact_root_sha256"] != artifact_root
            or state["event_root_sha256"] != event_root
            or state["artifact_root_sha256"] != artifact_root
        ):
            raise EventIntegrityError("final evidence anchors disagree")
        return SealedEvidenceView(
            identity=identity,
            audience="full",
            events=events,
            artifacts=refs,
            event_root_sha256=event_root,
            artifact_root_sha256=artifact_root,
            is_final=True,
        )

    @classmethod
    def verify(
        cls, path: Path, *, artifacts: ArtifactStore
    ) -> tuple[EpisodeEvent, ...]:
        if not isinstance(path, Path) or not isinstance(artifacts, ArtifactStore):
            raise InvalidEvidenceInput("invalid EventStore.verify input")
        events = _read_event_rows(path)
        state, identity = _verify_anchor(path, events)
        if identity is None or artifacts.identity != identity:
            raise EventIntegrityError(
                "event and artifact evidence have different identities"
            )
        marker_info = _lstat(_seal_path(path))
        if state["status"] == "sealed":
            if marker_info is None:
                raise EventIntegrityError("sealed event log is missing final marker")
            cls._verify_final(path, artifacts, events, identity, state)
        elif marker_info is not None:
            raise EventIntegrityError("unsealed event log has a final marker")
        else:
            with artifacts._guard():
                generation = artifacts._read_generation_unlocked()
                if generation["status"] != "open":
                    raise EventIntegrityError(
                        "open event log has a frozen artifact generation"
                    )
                refs = artifacts._list_refs_unlocked()
                _verify_referenced_artifacts_unlocked(artifacts, events, refs)
        return events

    def _release_fd(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def _poison(self) -> None:
        self._lifecycle = self.POISONED
        self._release_fd()

    def _require_appendable(self) -> int:
        if self._lifecycle == self.SEALED:
            raise EvidenceSealedError("event log has been sealed")
        if self._lifecycle == self.POISONED:
            raise EventIntegrityError(
                "event store is poisoned after evidence I/O failure"
            )
        if self._lifecycle == self.CLOSED or self._fd is None:
            raise EvidenceStoreError("event store is closed")
        return self._fd

    def append(
        self,
        event_type: str,
        identity: EventIdentity,
        visibility: str,
        payload: Mapping[str, object],
    ) -> EpisodeEvent:
        with self._thread_lock:
            fd = self._require_appendable()
            if type(event_type) is not str or not event_type:
                raise InvalidEvidenceInput(
                    "event_type must be a non-empty exact string"
                )
            checked_visibility = _validate_visibility(visibility)
            checked_identity = _safe_model(identity, EventIdentity, "identity")
            if self._identity is not None and checked_identity != self._identity:
                raise InvalidEvidenceInput(
                    "one event log can contain only one identity"
                )
            sequence = len(self._events)
            occurred_at = _utc_timestamp(self._clock)
            prior_hash = self._events[-1].event_hash if self._events else None
            try:
                payload_hash = content_sha256(payload)
                basis = EpisodeEvent(
                    event_id=_event_id(checked_identity, sequence),
                    sequence=sequence,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    identity=checked_identity,
                    visibility=checked_visibility,
                    payload=payload,
                    payload_visible=True,
                    payload_sha256=payload_hash,
                    prior_event_hash=prior_hash,
                    event_hash="0" * 64,
                )
                event = basis.model_copy(
                    update={"event_hash": recompute_event_hash(basis)}
                )
                event = _safe_model(event, EpisodeEvent, "event")
                encoded = canonical_json_bytes(event) + b"\n"
            except Exception as exc:
                if isinstance(exc, InvalidEvidenceInput):
                    raise
                raise InvalidEvidenceInput(
                    "payload cannot be stored as a canonical event"
                ) from exc
            new_events = (*self._events, event)
            try:
                _atomic_replace(
                    _event_state_path(self.path),
                    _event_state(
                        identity=checked_identity,
                        events=self._events,
                        status="poisoned",
                    ),
                )
            except Exception as exc:
                self._poison()
                raise EventIntegrityError(
                    "event write intent could not be made durable"
                ) from exc
            write_started = False
            try:
                written = 0
                while written < len(encoded):
                    write_started = True
                    count = os.write(fd, encoded[written:])
                    if count <= 0:
                        raise OSError("event append was incomplete")
                    written += count
                os.fsync(fd)
                _atomic_replace(
                    _event_state_path(self.path),
                    _event_state(
                        identity=checked_identity,
                        events=new_events,
                        status="open",
                    ),
                )
            except Exception as exc:
                if write_started:
                    try:
                        _atomic_replace(
                            _event_state_path(self.path),
                            _event_state(
                                identity=checked_identity,
                                events=self._events,
                                status="poisoned",
                            ),
                        )
                    except Exception:
                        pass
                    self._poison()
                    raise EventIntegrityError(
                        "event append durability failed; store poisoned"
                    ) from exc
                raise
            self._events = new_events
            self._identity = checked_identity
            return event

    def _open_view(self) -> SealedEvidenceView:
        events = _read_event_rows(self.path)
        state, identity = _verify_anchor(self.path, events)
        if identity is None or self.artifacts.identity != identity:
            raise EventIntegrityError(
                "event and artifact evidence have different identities"
            )
        if state["status"] != "open" or _lstat(_seal_path(self.path)) is not None:
            raise EventIntegrityError("open snapshot conflicts with final evidence")
        with self.artifacts._guard():
            generation = self.artifacts._read_generation_unlocked()
            if generation["status"] != "open":
                raise EventIntegrityError(
                    "open event log has a frozen artifact generation"
                )
            refs = self.artifacts._list_refs_unlocked()
            _verify_referenced_artifacts_unlocked(self.artifacts, events, refs)
            artifact_root = _artifact_root(refs)
        return SealedEvidenceView(
            identity=identity,
            audience="full",
            events=events,
            artifacts=refs,
            event_root_sha256=_event_root(events, identity),
            artifact_root_sha256=artifact_root,
            is_final=False,
        )

    def snapshot(self) -> SealedEvidenceView:
        with self._thread_lock:
            if self._lifecycle == self.POISONED:
                raise EventIntegrityError("event store is poisoned")
            if self._lifecycle == self.CLOSED:
                raise EvidenceStoreError("event store is closed")
            if self._lifecycle == self.SEALED:
                events = _read_event_rows(self.path)
                state, identity = _verify_anchor(self.path, events)
                return self._verify_final(
                    self.path, self.artifacts, events, identity, state
                )
            return self._open_view()

    def seal(self) -> SealedEvidenceView:
        with self._thread_lock:
            if self._lifecycle == self.POISONED:
                raise EventIntegrityError("event store is poisoned")
            if self._lifecycle == self.CLOSED:
                raise EvidenceStoreError("event store is closed")
            if self._lifecycle == self.SEALED:
                return self.snapshot()
            fd = self._require_appendable()
            if _lstat(_seal_path(self.path)) is not None:
                self._poison()
                raise EventIntegrityError("unexpected pre-existing seal marker")
            try:
                os.fsync(fd)
                events = _read_event_rows(self.path)
                _validate_joint_chain(
                    events, expected_identity=self._identity, require_visible=True
                )
                _atomic_replace(
                    _event_state_path(self.path),
                    _event_state(
                        identity=self._identity,
                        events=events,
                        status="sealing",
                    ),
                )
                with self.artifacts._guard():
                    refs = self.artifacts._freeze_unlocked()
                    artifact_root = _artifact_root(refs)
                    event_root = _event_root(events, self._identity)
                    marker = {
                        "spec_version": "aeread.event_seal/1",
                        "event_count": len(events),
                        "event_root_sha256": event_root,
                        "artifact_root_sha256": artifact_root,
                    }
                    temp = _exclusive_temp_write(
                        self.path.parent, canonical_json_bytes(marker)
                    )
                    published = False
                    try:
                        _publish_without_overwrite(temp, _seal_path(self.path))
                        published = True
                        _fsync_directory(self.path.parent)
                    finally:
                        temp.unlink(missing_ok=True)
                        _fsync_directory(self.path.parent)
                    if not published:
                        raise EventIntegrityError("seal marker publication failed")
                    _atomic_replace(
                        _event_state_path(self.path),
                        _event_state(
                            identity=self._identity,
                            events=events,
                            status="sealed",
                            artifact_root_sha256=artifact_root,
                        ),
                    )
            except Exception as exc:
                self._poison()
                if isinstance(exc, EventIntegrityError):
                    raise
                raise EventIntegrityError("evidence sealing failed closed") from exc
            self._lifecycle = self.SEALED
            self._release_fd()
            state = _read_event_state(self.path)
            return self._verify_final(
                self.path, self.artifacts, events, self._identity, state
            )

    def project(self, view: SealedEvidenceView, audience: str) -> SealedEvidenceView:
        checked_audience = _validate_visibility(audience, allow_full=True)
        if checked_audience == "evaluator_only":
            raise InvalidEvidenceInput(
                "projection audience is evaluator, not evaluator_only"
            )
        checked_view = _safe_model(view, SealedEvidenceView, "evidence view")
        if checked_view.audience not in {"full", "evaluator"}:
            raise InvalidEvidenceInput("projection source must be a full evidence view")
        if checked_view.identity != self.artifacts.identity or (
            self._identity is not None and checked_view.identity != self._identity
        ):
            raise InvalidEvidenceInput(
                "projection source belongs to a different evidence identity"
            )
        _validate_joint_chain(
            checked_view.events,
            expected_identity=checked_view.identity,
            require_visible=True,
        )
        if (
            _event_root(checked_view.events, checked_view.identity)
            != checked_view.event_root_sha256
        ):
            raise EventIntegrityError("source view event root is invalid")
        if _artifact_root(checked_view.artifacts) != checked_view.artifact_root_sha256:
            raise ArtifactIntegrityError("source view artifact root is invalid")
        if checked_view.is_final:
            events = _read_event_rows(self.path)
            state, durable_identity = _verify_anchor(self.path, events)
            durable = self._verify_final(
                self.path, self.artifacts, events, durable_identity, state
            )
            if (
                checked_view.identity != durable.identity
                or checked_view.events != durable.events
                or checked_view.artifacts != durable.artifacts
                or checked_view.event_root_sha256 != durable.event_root_sha256
                or checked_view.artifact_root_sha256 != durable.artifact_root_sha256
            ):
                raise EventIntegrityError("claimed final view is not durably sealed")
        committed = {_artifact_sort_key(ref): ref for ref in checked_view.artifacts}
        for ref in checked_view.artifacts:
            self.artifacts.verify(ref)
        for event in checked_view.events:
            for ref in _discover_artifact_refs(event.payload):
                if _artifact_sort_key(ref) not in committed:
                    raise ArtifactIntegrityError(
                        "source event references artifact absent from full root"
                    )

        projected_events: list[EpisodeEvent] = []
        visible_refs: dict[tuple[str, str, int], ArtifactRef] = {}
        for event in checked_view.events:
            visible = (
                checked_audience in {"full", "evaluator"}
                or event.visibility == "public"
                or event.visibility == checked_audience
            )
            if visible:
                projected = event
                for ref in _discover_artifact_refs(event.payload):
                    self.artifacts.verify(ref)
                    visible_refs[_artifact_sort_key(ref)] = ref
            else:
                projected = _safe_model(
                    event.model_copy(
                        update={"payload": None, "payload_visible": False}
                    ),
                    EpisodeEvent,
                    "projected event",
                )
            projected_events.append(projected)
        projected_artifacts = (
            checked_view.artifacts
            if checked_audience in {"full", "evaluator"}
            else tuple(visible_refs[key] for key in sorted(visible_refs))
        )
        try:
            return SealedEvidenceView(
                identity=checked_view.identity,
                audience=checked_audience,
                events=tuple(projected_events),
                artifacts=projected_artifacts,
                event_root_sha256=checked_view.event_root_sha256,
                artifact_root_sha256=checked_view.artifact_root_sha256,
                is_final=checked_view.is_final,
            )
        except Exception as exc:
            raise InvalidEvidenceInput("projected evidence view is invalid") from exc

    def close(self) -> None:
        with self._thread_lock:
            if self._lifecycle != self.POISONED:
                self._lifecycle = self.CLOSED
            self._release_fd()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
