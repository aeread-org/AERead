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
_STORE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
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


def _leaf_name(name: str) -> str:
    if (
        type(name) is not str
        or not name
        or name in {".", ".."}
        or os.sep in name
        or (os.altsep is not None and os.altsep in name)
    ):
        raise InvalidEvidenceInput("managed file name must be one path component")
    return name


class _ManagedRoot:
    """Retained trusted-root inode; only admission may resolve platform aliases.

    Descendant operations remain anchored to this inode even if a same-user or
    administrator concurrently rewrites the surrounding namespace. Lexical path
    checks below are admission and diagnostics, not post-open containment.
    """

    def __init__(self, lexical_path: Path, canonical_path: Path, fd: int) -> None:
        self.lexical_path = lexical_path
        self.canonical_path = canonical_path
        self._fd = fd
        self._closed = False

    @classmethod
    def open(cls, trusted_root: Path) -> "_ManagedRoot":
        if not isinstance(trusted_root, Path):
            raise InvalidEvidenceInput("trusted_root must be a pathlib.Path")
        lexical = Path(os.path.abspath(trusted_root))
        try:
            canonical = trusted_root.resolve(strict=True)
            fd = os.open(canonical, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("trusted_root is not a directory")
        except Exception as exc:
            raise InvalidEvidenceInput(
                "trusted_root must name an existing trusted directory"
            ) from exc
        return cls(lexical, canonical, fd)

    def close(self) -> None:
        if not self._closed:
            os.close(self._fd)
            self._closed = True

    def directory(
        self,
        path: Path,
        *,
        create: bool,
        error_type: type[EvidenceStoreError],
    ) -> "_ManagedDirectory":
        if self._closed:
            raise EvidenceStoreError("trusted root anchor is closed")
        lexical, relative = self.relative_path(path)
        fd = os.dup(self._fd)
        consumed: list[str] = []
        try:
            for component in relative:
                try:
                    child_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
                        dir_fd=fd,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(component, mode=0o755, dir_fd=fd)
                        os.fsync(fd)
                        child_fd = os.open(
                            component,
                            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
                            dir_fd=fd,
                        )
                    except OSError as exc:
                        raise error_type(
                            f"cannot durably create managed directory {component!r}"
                        ) from exc
                except OSError as exc:
                    raise error_type(
                        f"managed descendant {component!r} is not a real directory"
                    ) from exc
                os.close(fd)
                fd = child_fd
                consumed.append(component)
            return _ManagedDirectory(self, tuple(consumed), fd, lexical)
        except Exception:
            os.close(fd)
            raise

    def relative_path(self, path: Path) -> tuple[Path, tuple[str, ...]]:
        """Return the normalized lexical path admitted beneath this root."""

        if self._closed:
            raise EvidenceStoreError("trusted root anchor is closed")
        if not isinstance(path, Path):
            raise InvalidEvidenceInput("managed path must be a pathlib.Path")
        lexical = Path(os.path.abspath(path))
        try:
            relative = lexical.relative_to(self.lexical_path)
        except ValueError as exc:
            raise InvalidEvidenceInput(
                "managed path must be lexically beneath trusted_root at admission"
            ) from exc
        parts = tuple(_leaf_name(component) for component in relative.parts)
        return lexical, parts


class _ManagedDirectory:
    """Retained directory capability for all descendant leaf operations."""

    def __init__(
        self,
        root: _ManagedRoot,
        relative: tuple[str, ...],
        fd: int,
        display_path: Path,
    ) -> None:
        self.root = root
        self.relative = relative
        self.fd = fd
        self.display_path = display_path
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            os.close(self.fd)
            self._closed = True

    def assert_bound(self, error_type: type[EvidenceStoreError]) -> None:
        if self._closed:
            raise error_type("managed directory capability is closed")
        try:
            current = self.root.directory(
                self.root.lexical_path.joinpath(*self.relative),
                create=False,
                error_type=error_type,
            )
        except FileNotFoundError as exc:
            raise error_type("managed directory binding disappeared") from exc
        try:
            expected = os.fstat(self.fd)
            actual = os.fstat(current.fd)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
                raise error_type("managed directory binding changed during operation")
        finally:
            current.close()


def _lstat(
    directory: _ManagedDirectory,
    name: str,
    *,
    error_type: type[EvidenceStoreError] = EvidenceStoreError,
) -> os.stat_result | None:
    checked = _leaf_name(name)
    try:
        return os.stat(checked, dir_fd=directory.fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise error_type(f"cannot inspect {checked}") from exc


def _require_regular(
    directory: _ManagedDirectory,
    name: str,
    *,
    label: str,
    error_type: type[EvidenceStoreError],
) -> os.stat_result:
    info = _lstat(directory, name, error_type=error_type)
    if info is None:
        raise error_type(f"{label} is missing or unreadable")
    if not stat.S_ISREG(info.st_mode):
        raise error_type(f"{label} must be a non-symlink regular file")
    return info


def _fsync_directory(directory: _ManagedDirectory) -> None:
    os.fsync(directory.fd)


def _exclusive_temp_write(directory: _ManagedDirectory, data: bytes) -> str:
    temp = f".tmp-{uuid.uuid4().hex}"
    fd = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
        0o600,
        dir_fd=directory.fd,
    )
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
            try:
                os.unlink(temp, dir_fd=directory.fd)
            except FileNotFoundError:
                pass
            _fsync_directory(directory)
            raise
    finally:
        os.close(fd)
    return temp


def _publish_without_overwrite(
    directory: _ManagedDirectory, temp: str, target: str
) -> None:
    if _lstat(directory, target) is not None:
        raise FileExistsError(target)
    os.link(
        temp,
        target,
        src_dir_fd=directory.fd,
        dst_dir_fd=directory.fd,
        follow_symlinks=False,
    )


def _atomic_replace(
    directory: _ManagedDirectory,
    name: str,
    value: object,
    *,
    error_type: type[EvidenceStoreError] = EvidenceStoreError,
) -> None:
    checked = _leaf_name(name)
    existing = _lstat(directory, checked, error_type=error_type)
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise error_type(f"{checked} must be a regular file")
    try:
        encoded = canonical_json_bytes(value)
    except Exception as exc:
        raise InvalidEvidenceInput(f"{checked} cannot be canonicalized") from exc
    temp = _exclusive_temp_write(directory, encoded)
    replaced = False
    try:
        current = _lstat(directory, checked, error_type=error_type)
        if current is not None and not stat.S_ISREG(current.st_mode):
            raise error_type(f"{checked} must be a regular file")
        os.replace(
            temp,
            checked,
            src_dir_fd=directory.fd,
            dst_dir_fd=directory.fd,
        )
        replaced = True
        _fsync_directory(directory)
    finally:
        if not replaced:
            try:
                os.unlink(temp, dir_fd=directory.fd)
            except FileNotFoundError:
                pass
            _fsync_directory(directory)


def _canonical_object(
    directory: _ManagedDirectory,
    name: str,
    *,
    label: str,
    error_type: type[EvidenceStoreError],
) -> dict[str, object]:
    checked = _leaf_name(name)
    _require_regular(directory, checked, label=label, error_type=error_type)
    flags = os.O_RDONLY | _NOFOLLOW
    try:
        fd = os.open(checked, flags, dir_fd=directory.fd)
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
    """Content-addressed artifacts beneath one explicit trusted filesystem root.

    ``trusted_root`` is an existing caller-controlled inode boundary. Its platform
    aliases may be resolved once; descendants are then no-follow and dir-fd anchored.
    A same-user/admin rename may move that retained inode, so lexical binding checks
    are diagnostics rather than portable namespace-containment guarantees. This
    object owns the anchor descriptors until :meth:`close`.
    """

    _GENERATION_VERSION = "aeread.artifact_generation/3"
    _LOCK_NAME = "generation.lock"
    _STATE_NAME = "generation.json"
    _OWNER_LOCK_NAME = "event-owner.lock"

    def __init__(
        self,
        root: Path,
        identity: EventIdentity,
        trusted: _ManagedRoot,
        root_anchor: _ManagedDirectory,
        artifact_anchor: _ManagedDirectory,
        object_anchor: _ManagedDirectory,
    ) -> None:
        self.root = root
        self.identity = identity
        self.trusted_root = trusted.lexical_path
        self.artifact_dir = root / "artifacts"
        self.object_dir = self.artifact_dir / "sha256"
        self._trusted = trusted
        self._root_anchor = root_anchor
        self._artifact_anchor = artifact_anchor
        self._object_anchor = object_anchor
        self._thread_lock = threading.RLock()
        self._poisoned = False
        self._closed = False

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        identity: EventIdentity | None = None,
        trusted_root: Path | None = None,
    ) -> "ArtifactStore":
        """Open one identity-bound generation below ``trusted_root``.

        ``root`` must use the same lexical trusted-root prefix. The root path is
        display metadata only and is never persisted as generation identity.
        """
        if not isinstance(root, Path):
            raise InvalidEvidenceInput("artifact root must be a pathlib.Path")
        if identity is None:
            raise InvalidEvidenceInput(
                "ArtifactStore.open requires identity before creating a generation"
            )
        if trusted_root is None:
            raise InvalidEvidenceInput(
                "ArtifactStore.open requires an explicit existing trusted_root"
            )
        checked_identity = _safe_model(identity, EventIdentity, "artifact identity")
        trusted = _ManagedRoot.open(trusted_root)
        root_anchor: _ManagedDirectory | None = None
        artifact_anchor: _ManagedDirectory | None = None
        object_anchor: _ManagedDirectory | None = None
        store: ArtifactStore | None = None
        try:
            root_anchor = trusted.directory(
                root, create=True, error_type=ArtifactIntegrityError
            )
            artifact_anchor = trusted.directory(
                root / "artifacts", create=True, error_type=ArtifactIntegrityError
            )
            object_anchor = trusted.directory(
                root / "artifacts" / "sha256",
                create=True,
                error_type=ArtifactIntegrityError,
            )
            store = cls(
                root,
                checked_identity,
                trusted,
                root_anchor,
                artifact_anchor,
                object_anchor,
            )
            for name, label in (
                (cls._LOCK_NAME, "artifact generation lock"),
                (cls._STATE_NAME, "artifact generation anchor"),
                (cls._OWNER_LOCK_NAME, "artifact event-owner lock"),
            ):
                info = _lstat(artifact_anchor, name, error_type=ArtifactIntegrityError)
                if info is not None and not stat.S_ISREG(info.st_mode):
                    raise ArtifactIntegrityError(f"{label} must be a regular file")
            with store._guard():
                if (
                    _lstat(
                        artifact_anchor,
                        cls._STATE_NAME,
                        error_type=ArtifactIntegrityError,
                    )
                    is None
                ):
                    if os.listdir(object_anchor.fd):
                        raise ArtifactIntegrityError(
                            "artifact objects exist without a generation anchor"
                        )
                    store._write_generation_unlocked(
                        {
                            "spec_version": cls._GENERATION_VERSION,
                            "identity": checked_identity.model_dump(mode="json"),
                            "evidence_store_id": None,
                            "event_log_relpath": None,
                            "event_store_state": "unclaimed",
                            "status": "open",
                            "artifact_count": 0,
                            "artifact_root_sha256": None,
                        }
                    )
                else:
                    store._read_generation_unlocked()
            store._assert_bindings()
            return store
        except Exception:
            if store is not None:
                store.close()
            else:
                for anchor in (object_anchor, artifact_anchor, root_anchor):
                    if anchor is not None:
                        anchor.close()
                trusted.close()
            raise

    def _require_open(self) -> None:
        if self._closed:
            raise EvidenceStoreError("artifact store is closed")

    def _assert_bindings(self) -> None:
        self._require_open()
        for anchor in (
            self._root_anchor,
            self._artifact_anchor,
            self._object_anchor,
        ):
            anchor.assert_bound(ArtifactIntegrityError)

    def _directory_for(
        self,
        path: Path,
        *,
        create: bool,
        error_type: type[EvidenceStoreError],
    ) -> _ManagedDirectory:
        self._require_open()
        return self._trusted.directory(path, create=create, error_type=error_type)

    @contextmanager
    def _guard(self) -> Iterator[None]:
        self._require_open()
        with self._thread_lock:
            self._assert_bindings()
            info = _lstat(
                self._artifact_anchor,
                self._LOCK_NAME,
                error_type=ArtifactIntegrityError,
            )
            created = info is None
            if info is not None and not stat.S_ISREG(info.st_mode):
                raise ArtifactIntegrityError("artifact generation lock is not regular")
            flags = os.O_RDWR | _NOFOLLOW
            if created:
                flags |= os.O_CREAT | os.O_EXCL
            try:
                fd = os.open(
                    self._LOCK_NAME,
                    flags,
                    0o600,
                    dir_fd=self._artifact_anchor.fd,
                )
            except FileExistsError:
                created = False
                info = _require_regular(
                    self._artifact_anchor,
                    self._LOCK_NAME,
                    label="artifact generation lock",
                    error_type=ArtifactIntegrityError,
                )
                fd = os.open(
                    self._LOCK_NAME,
                    os.O_RDWR | _NOFOLLOW,
                    dir_fd=self._artifact_anchor.fd,
                )
            except OSError as exc:
                raise ArtifactIntegrityError(
                    "artifact generation lock cannot be opened"
                ) from exc
            try:
                if created:
                    os.fsync(fd)
                    _fsync_directory(self._artifact_anchor)
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
                self._assert_bindings()
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _read_generation_unlocked(self) -> dict[str, object]:
        value = _canonical_object(
            self._artifact_anchor,
            self._STATE_NAME,
            label="artifact generation anchor",
            error_type=ArtifactIntegrityError,
        )
        if (
            set(value)
            != {
                "spec_version",
                "identity",
                "evidence_store_id",
                "event_log_relpath",
                "event_store_state",
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
        store_id = value.get("evidence_store_id")
        event_log_relpath = value.get("event_log_relpath")
        event_store_state = value.get("event_store_state")
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
        if store_id is not None and (
            type(store_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", store_id)
        ):
            raise ArtifactIntegrityError(
                "artifact generation evidence_store_id is invalid"
            )
        if event_store_state not in {"unclaimed", "pending", "bound"}:
            raise ArtifactIntegrityError(
                "artifact generation event-store state is invalid"
            )
        if event_store_state == "unclaimed":
            if store_id is not None or event_log_relpath is not None:
                raise ArtifactIntegrityError(
                    "unclaimed artifact generation cannot name an event store"
                )
        elif (
            store_id is None
            or type(event_log_relpath) is not str
            or not self._is_canonical_event_relpath(event_log_relpath)
        ):
            raise ArtifactIntegrityError(
                "claimed artifact generation has an invalid event-log path"
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
        if status == "sealed" and event_store_state != "bound":
            raise ArtifactIntegrityError(
                "sealed artifact generation requires a bound event store"
            )
        return value

    @staticmethod
    def _is_canonical_event_relpath(value: str) -> bool:
        if not value or value.startswith("/") or value.endswith("/"):
            return False
        parts = value.split("/")
        try:
            return all(_leaf_name(part) == part for part in parts)
        except InvalidEvidenceInput:
            return False

    def _event_log_relpath(self, path: Path) -> str:
        self._require_open()
        _, parts = self._trusted.relative_path(path)
        if not parts:
            raise InvalidEvidenceInput("event log must be below trusted_root")
        reserved = self._artifact_anchor.relative
        if len(parts) >= len(reserved):
            candidate_prefix = parts[: len(reserved)]
            aliases_artifacts = candidate_prefix == reserved
            candidate_parent: _ManagedDirectory | None = None
            if not aliases_artifacts:
                try:
                    candidate_parent = self._trusted.directory(
                        self._trusted.lexical_path.joinpath(*candidate_prefix[:-1]),
                        create=False,
                        error_type=ArtifactIntegrityError,
                    )
                except (FileNotFoundError, ArtifactIntegrityError):
                    candidate_parent = None
                if candidate_parent is not None:
                    try:
                        candidate_info = _lstat(
                            candidate_parent,
                            candidate_prefix[-1],
                            error_type=ArtifactIntegrityError,
                        )
                        artifact_info = os.fstat(self._artifact_anchor.fd)
                        aliases_artifacts = candidate_info is not None and (
                            candidate_info.st_dev,
                            candidate_info.st_ino,
                        ) == (artifact_info.st_dev, artifact_info.st_ino)
                    except OSError as exc:
                        raise ArtifactIntegrityError(
                            "artifact namespace identity cannot be verified"
                        ) from exc
                    finally:
                        candidate_parent.close()
            if aliases_artifacts:
                raise InvalidEvidenceInput(
                    "event log cannot occupy the reserved artifact namespace"
                )
        value = "/".join(parts)
        if not self._is_canonical_event_relpath(value):
            raise InvalidEvidenceInput(
                "event log path cannot be represented canonically"
            )
        return value

    def _write_generation_unlocked(self, value: Mapping[str, object]) -> None:
        try:
            _atomic_replace(
                self._artifact_anchor,
                self._STATE_NAME,
                dict(value),
                error_type=ArtifactIntegrityError,
            )
        except Exception as exc:
            self._poisoned = True
            if isinstance(exc, InvalidEvidenceInput):
                raise
            raise ArtifactIntegrityError(
                "artifact generation anchor update failed"
            ) from exc

    def _paths(self, digest: str) -> tuple[str, str]:
        if type(digest) is not str or not _DIGEST_RE.fullmatch(digest):
            raise InvalidEvidenceInput("artifact digest must be lower-case SHA-256")
        return digest, f"{digest}{_META_SUFFIX}"

    def _read_metadata(self, name: str) -> ArtifactRef:
        value = _canonical_object(
            self._object_anchor,
            name,
            label="artifact metadata",
            error_type=ArtifactIntegrityError,
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
            self._object_anchor,
            content_path,
            label="artifact content",
            error_type=ArtifactIntegrityError,
        )
        stored_ref = self._read_metadata(metadata_path)
        if stored_ref != ref or info.st_size != ref.size_bytes:
            raise ArtifactIntegrityError(
                "artifact metadata does not match requested ref"
            )
        fd = os.open(
            content_path,
            os.O_RDONLY | _NOFOLLOW,
            dir_fd=self._object_anchor.fd,
        )
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
            names = set(os.listdir(self._object_anchor.fd))
        except OSError as exc:
            raise ArtifactIntegrityError("artifact directory is unreadable") from exc
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
            content_temp: str | None = None
            metadata_temp: str | None = None
            try:
                content_temp = _exclusive_temp_write(self._object_anchor, data)
                metadata_temp = _exclusive_temp_write(
                    self._object_anchor,
                    canonical_json_bytes(_artifact_metadata(ref)),
                )
                try:
                    _publish_without_overwrite(
                        self._object_anchor, content_temp, content_path
                    )
                except FileExistsError:
                    pass
                try:
                    _publish_without_overwrite(
                        self._object_anchor, metadata_temp, metadata_path
                    )
                except FileExistsError:
                    pass
            finally:
                for temp in (content_temp, metadata_temp):
                    if temp is not None:
                        try:
                            os.unlink(temp, dir_fd=self._object_anchor.fd)
                        except FileNotFoundError:
                            pass
                _fsync_directory(self._object_anchor)
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
            fd = os.open(
                self._paths(checked.sha256)[0],
                os.O_RDONLY | _NOFOLLOW,
                dir_fd=self._object_anchor.fd,
            )
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
        if generation["event_store_state"] != "bound":
            raise ArtifactIntegrityError(
                "artifact generation must bind its event log before final freeze"
            )
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
                "evidence_store_id": generation["evidence_store_id"],
                "event_log_relpath": generation["event_log_relpath"],
                "event_store_state": generation["event_store_state"],
                "status": "sealed",
                "artifact_count": len(refs),
                "artifact_root_sha256": root,
            }
        )
        return refs

    def _prepare_event_store_unlocked(
        self, event_log_relpath: str, existing_store_id: str | None
    ) -> tuple[str, dict[str, object]]:
        """Claim or recover one pending path before any event-path side effect."""

        if not self._is_canonical_event_relpath(event_log_relpath):
            raise InvalidEvidenceInput("event log relative path is invalid")
        if existing_store_id is not None and (
            type(existing_store_id) is not str
            or not _STORE_ID_RE.fullmatch(existing_store_id)
        ):
            raise InvalidEvidenceInput("evidence_store_id must be 32 lower-case hex")
        generation = self._read_generation_unlocked()
        claim_state = generation["event_store_state"]
        claimed_path = generation["event_log_relpath"]
        claimed_id = generation["evidence_store_id"]
        if claim_state == "unclaimed":
            if existing_store_id is not None:
                raise ArtifactIntegrityError(
                    "event anchors exist without an artifact-generation claim"
                )
            if generation["status"] != "open":
                raise EvidenceSealedError(
                    "sealed artifact generation has no event-store claim"
                )
            claimed_id = uuid.uuid4().hex
            updated = dict(generation)
            updated["identity"] = self.identity.model_dump(mode="json")
            updated["evidence_store_id"] = claimed_id
            updated["event_log_relpath"] = event_log_relpath
            updated["event_store_state"] = "pending"
            self._write_generation_unlocked(updated)
            generation = self._read_generation_unlocked()
            return claimed_id, generation
        assert isinstance(claimed_id, str)
        if claimed_path != event_log_relpath:
            raise ConcurrentWriterError(
                "artifact generation is bound to another event-log path"
            )
        if claim_state == "pending":
            if existing_store_id is not None and existing_store_id != claimed_id:
                raise EventIntegrityError(
                    "pending event state has the wrong evidence_store_id"
                )
            return claimed_id, generation
        if existing_store_id is None:
            raise EventIntegrityError(
                "bound event log or state is missing at its claimed path"
            )
        if existing_store_id != claimed_id:
            raise EventIntegrityError(
                "event state has the wrong generation evidence_store_id"
            )
        return claimed_id, generation

    def _bind_event_store_unlocked(
        self, evidence_store_id: str, event_log_relpath: str
    ) -> dict[str, object]:
        generation = self._validate_event_store_unlocked(
            evidence_store_id,
            event_log_relpath,
            require_open=False,
            allow_pending=True,
        )
        if generation["event_store_state"] == "pending":
            if generation["status"] != "open":
                raise ArtifactIntegrityError(
                    "pending event-store claim cannot be bound after freeze"
                )
            updated = dict(generation)
            updated["event_store_state"] = "bound"
            self._write_generation_unlocked(updated)
            generation = self._read_generation_unlocked()
        return generation

    def _validate_event_store_unlocked(
        self,
        evidence_store_id: str,
        event_log_relpath: str,
        *,
        require_open: bool,
        allow_pending: bool = False,
    ) -> dict[str, object]:
        if type(evidence_store_id) is not str or not _STORE_ID_RE.fullmatch(
            evidence_store_id
        ):
            raise InvalidEvidenceInput("evidence_store_id must be 32 lower-case hex")
        if not self._is_canonical_event_relpath(event_log_relpath):
            raise InvalidEvidenceInput("event log relative path is invalid")
        generation = self._read_generation_unlocked()
        if generation["evidence_store_id"] != evidence_store_id:
            raise ConcurrentWriterError(
                "artifact generation is claimed by another event store"
            )
        if generation["event_log_relpath"] != event_log_relpath:
            raise ConcurrentWriterError(
                "artifact generation is bound to another event-log path"
            )
        if generation["event_store_state"] != "bound" and not (
            allow_pending and generation["event_store_state"] == "pending"
        ):
            raise ArtifactIntegrityError("artifact generation event log is not bound")
        if require_open and generation["status"] != "open":
            raise EvidenceSealedError("artifact generation has been sealed")
        return generation

    def _acquire_owner_lease_unlocked(self) -> int:
        info = _lstat(
            self._artifact_anchor,
            self._OWNER_LOCK_NAME,
            error_type=ArtifactIntegrityError,
        )
        created = info is None
        flags = os.O_RDWR | _NOFOLLOW
        if created:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(
                self._OWNER_LOCK_NAME,
                flags,
                0o600,
                dir_fd=self._artifact_anchor.fd,
            )
        except FileExistsError:
            created = False
            _require_regular(
                self._artifact_anchor,
                self._OWNER_LOCK_NAME,
                label="artifact event-owner lock",
                error_type=ArtifactIntegrityError,
            )
            fd = os.open(
                self._OWNER_LOCK_NAME,
                os.O_RDWR | _NOFOLLOW,
                dir_fd=self._artifact_anchor.fd,
            )
        try:
            if created:
                os.fsync(fd)
                _fsync_directory(self._artifact_anchor)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError as exc:
            os.close(fd)
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise ConcurrentWriterError(
                    "artifact generation already has an event writer"
                ) from exc
            raise ArtifactIntegrityError(
                "artifact event-owner lease cannot be acquired"
            ) from exc

    def close(self) -> None:
        with self._thread_lock:
            if self._closed:
                return
            self._closed = True
            for anchor in (
                self._object_anchor,
                self._artifact_anchor,
                self._root_anchor,
            ):
                anchor.close()
            self._trusted.close()

    def __enter__(self) -> "ArtifactStore":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


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
    events: tuple[EpisodeEvent, ...],
    identity: EventIdentity,
    evidence_store_id: str,
) -> str:
    if not _STORE_ID_RE.fullmatch(evidence_store_id):
        raise InvalidEvidenceInput("evidence_store_id must be 32 lower-case hex")
    return _domain_digest(
        b"aeread.event_root/2",
        {
            "identity": identity.model_dump(mode="json"),
            "evidence_store_id": evidence_store_id,
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


_EVENT_STATE_VERSION = "aeread.event_state/2"


def _event_state_name(log_name: str) -> str:
    return f"{_leaf_name(log_name)}.state.json"


def _seal_name(log_name: str) -> str:
    return f"{_leaf_name(log_name)}.sealed.json"


def _event_state(
    *,
    identity: EventIdentity | None,
    evidence_store_id: str,
    events: tuple[EpisodeEvent, ...],
    status: str,
    artifact_root_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "spec_version": _EVENT_STATE_VERSION,
        "status": status,
        "identity": identity.model_dump(mode="json") if identity else None,
        "evidence_store_id": evidence_store_id,
        "event_count": len(events),
        "last_event_hash": events[-1].event_hash if events else None,
        "event_root_sha256": _event_root(events, identity, evidence_store_id)
        if identity is not None
        else None,
        "artifact_root_sha256": artifact_root_sha256,
    }


def _read_event_state(directory: _ManagedDirectory, log_name: str) -> dict[str, object]:
    value = _canonical_object(
        directory,
        _event_state_name(log_name),
        label="event high-water anchor",
        error_type=EventIntegrityError,
    )
    expected = {
        "spec_version",
        "status",
        "identity",
        "evidence_store_id",
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
    store_id = value["evidence_store_id"]
    if type(store_id) is not str or not _STORE_ID_RE.fullmatch(store_id):
        raise EventIntegrityError("event high-water evidence_store_id is invalid")
    for field in ("last_event_hash", "event_root_sha256", "artifact_root_sha256"):
        item = value[field]
        if item is not None and (
            type(item) is not str or not _DIGEST_RE.fullmatch(item)
        ):
            raise EventIntegrityError(f"event high-water {field} is invalid")
    if value["event_root_sha256"] is None:
        raise EventIntegrityError("event high-water anchor must bind an event root")
    return value


def _read_event_rows(
    directory: _ManagedDirectory, log_name: str
) -> tuple[EpisodeEvent, ...]:
    checked = _leaf_name(log_name)
    _require_regular(
        directory, checked, label="event log", error_type=EventIntegrityError
    )
    fd = os.open(checked, os.O_RDONLY | _NOFOLLOW, dir_fd=directory.fd)
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
    directory: _ManagedDirectory,
    log_name: str,
    events: tuple[EpisodeEvent, ...],
) -> tuple[dict[str, object], EventIdentity | None]:
    state = _read_event_state(directory, log_name)
    identity = state["identity"]
    assert identity is None or isinstance(identity, EventIdentity)
    chain_identity = _validate_joint_chain(
        events, expected_identity=identity, require_visible=True
    )
    if (
        state["event_count"] != len(events)
        or state["last_event_hash"] != (events[-1].event_hash if events else None)
        or state["event_root_sha256"]
        != _event_root(events, chain_identity, state["evidence_store_id"])
    ):
        raise EventIntegrityError(
            "event log does not match its durable high-water anchor"
        )
    if state["status"] in {"sealing", "poisoned"}:
        raise EventIntegrityError(
            "event log is fail-closed after interrupted evidence I/O"
        )
    return state, chain_identity


def _seal_marker(directory: _ManagedDirectory, log_name: str) -> dict[str, object]:
    marker = _canonical_object(
        directory,
        _seal_name(log_name),
        label="event seal marker",
        error_type=EventIntegrityError,
    )
    if (
        set(marker)
        != {
            "spec_version",
            "evidence_store_id",
            "event_count",
            "event_root_sha256",
            "artifact_root_sha256",
        }
        or marker.get("spec_version") != "aeread.event_seal/2"
    ):
        raise EventIntegrityError("event seal marker has unexpected fields")
    if type(marker["event_count"]) is not int or marker["event_count"] < 0:
        raise EventIntegrityError("event seal count is invalid")
    if type(marker["evidence_store_id"]) is not str or not _STORE_ID_RE.fullmatch(
        marker["evidence_store_id"]
    ):
        raise EventIntegrityError("event seal evidence_store_id is invalid")
    for field in ("event_root_sha256", "artifact_root_sha256"):
        if type(marker[field]) is not str or not _DIGEST_RE.fullmatch(marker[field]):
            raise EventIntegrityError("event seal root is invalid")
    return marker


class EventStore:
    """Single-writer log durably claimed by ID and trusted-root-relative path.

    The retained parent capability and generation-wide writer lease are owned by
    this instance. V0 permits whole-tree relocation while closed because the
    relative path remains stable; renaming/rebinding the log within a generation
    is unsupported. A same-user/admin namespace rewrite may move the retained
    parent inode, but operations never follow its replacement symlink target.
    """

    OPEN = "open"
    POISONED = "poisoned"
    SEALED = "sealed"
    CLOSED = "closed"

    def __init__(
        self,
        path: Path,
        directory: _ManagedDirectory,
        log_name: str,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime],
        fd: int | None,
        owner_lease_fd: int | None,
        events: tuple[EpisodeEvent, ...],
        identity: EventIdentity | None,
        evidence_store_id: str,
        event_log_relpath: str,
        lifecycle: str,
    ) -> None:
        self.path = path
        self._directory = directory
        self._log_name = log_name
        self.artifacts = artifacts
        self._clock = clock
        self._fd = fd
        self._owner_lease_fd = owner_lease_fd
        self._events = events
        self._identity = identity
        self._evidence_store_id = evidence_store_id
        self._event_log_relpath = event_log_relpath
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
        log_name = _leaf_name(path.name)
        event_log_relpath = artifacts._event_log_relpath(path)
        directory: _ManagedDirectory | None
        try:
            directory = artifacts._directory_for(
                path.parent, create=False, error_type=EventIntegrityError
            )
        except FileNotFoundError:
            directory = None
        existing_state: dict[str, object] | None = None
        if directory is not None:
            path_info = _lstat(directory, log_name, error_type=EventIntegrityError)
            state_info = _lstat(
                directory,
                _event_state_name(log_name),
                error_type=EventIntegrityError,
            )
            marker_info = _lstat(
                directory, _seal_name(log_name), error_type=EventIntegrityError
            )
            if path_info is not None and not stat.S_ISREG(path_info.st_mode):
                directory.close()
                raise EventIntegrityError(
                    "event log must be a non-symlink regular file"
                )
            if state_info is not None and not stat.S_ISREG(state_info.st_mode):
                directory.close()
                raise EventIntegrityError(
                    "event state must be a non-symlink regular file"
                )
            if marker_info is not None and not stat.S_ISREG(marker_info.st_mode):
                directory.close()
                raise EventIntegrityError("event seal marker must be a regular file")
            if path_info is None and (
                state_info is not None or marker_info is not None
            ):
                directory.close()
                raise EventIntegrityError("event anchors exist without an event log")
            if path_info is not None and state_info is None:
                directory.close()
                raise EventIntegrityError(
                    "event log is missing its durable state anchor"
                )
            if state_info is not None:
                existing_state = _read_event_state(directory, log_name)
        existing_store_id = (
            existing_state["evidence_store_id"] if existing_state is not None else None
        )
        assert existing_store_id is None or isinstance(existing_store_id, str)
        owner_lease_fd: int | None = None
        try:
            with artifacts._guard():
                evidence_store_id, generation = artifacts._prepare_event_store_unlocked(
                    event_log_relpath, existing_store_id
                )
                if generation["status"] == "open":
                    owner_lease_fd = artifacts._acquire_owner_lease_unlocked()
                elif existing_state is None or existing_state["status"] != "sealed":
                    if existing_state is not None:
                        raise EventIntegrityError(
                            "event state conflicts with sealed artifact generation"
                        )
                    raise EvidenceSealedError(
                        "sealed artifact generation rejects a new event log"
                    )
            if directory is None:
                directory = artifacts._directory_for(
                    path.parent, create=True, error_type=EventIntegrityError
                )
            path_info = _lstat(directory, log_name, error_type=EventIntegrityError)
            state_info = _lstat(
                directory,
                _event_state_name(log_name),
                error_type=EventIntegrityError,
            )
            marker_info = _lstat(
                directory, _seal_name(log_name), error_type=EventIntegrityError
            )
            created = path_info is None
            if created and (state_info is not None or marker_info is not None):
                raise EventIntegrityError("event anchors exist without an event log")
            if not created and state_info is None:
                raise EventIntegrityError(
                    "event log is missing its durable state anchor"
                )
            flags = os.O_RDWR | os.O_APPEND | _NOFOLLOW
            if created:
                flags |= os.O_CREAT | os.O_EXCL
            fd = os.open(log_name, flags, 0o600, dir_fd=directory.fd)
        except Exception:
            if owner_lease_fd is not None:
                try:
                    fcntl.flock(owner_lease_fd, fcntl.LOCK_UN)
                finally:
                    os.close(owner_lease_fd)
            if directory is not None:
                directory.close()
            raise
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise EventIntegrityError("event log must be regular")
            if created:
                os.fsync(fd)
                _fsync_directory(directory)
                try:
                    _atomic_replace(
                        directory,
                        _event_state_name(log_name),
                        _event_state(
                            identity=checked_identity,
                            evidence_store_id=evidence_store_id,
                            events=(),
                            status="open",
                        ),
                        error_type=EventIntegrityError,
                    )
                except Exception:
                    os.close(fd)
                    fd = -1
                    for name in (log_name, _event_state_name(log_name)):
                        try:
                            os.unlink(name, dir_fd=directory.fd)
                        except FileNotFoundError:
                            pass
                    _fsync_directory(directory)
                    raise
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise ConcurrentWriterError(
                        "event log already has a writer"
                    ) from exc
                raise
            events = _read_event_rows(directory, log_name)
            state, anchored_identity = _verify_anchor(directory, log_name, events)
            if state["evidence_store_id"] != evidence_store_id:
                raise EventIntegrityError(
                    "event state changed its evidence_store_id during open"
                )
            if checked_identity is not None:
                if anchored_identity != checked_identity:
                    raise InvalidEvidenceInput(
                        "opened identity does not match event anchor"
                    )
            if state["status"] == "sealed":
                cls._verify_final(
                    directory,
                    log_name,
                    artifacts,
                    events,
                    anchored_identity,
                    evidence_store_id,
                    event_log_relpath,
                    state,
                )
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                fd = -1
                directory.assert_bound(EventIntegrityError)
                return cls(
                    path,
                    directory,
                    log_name,
                    artifacts,
                    clock,
                    None,
                    None,
                    events,
                    anchored_identity,
                    evidence_store_id,
                    event_log_relpath,
                    cls.SEALED,
                )
            if marker_info is not None:
                raise EventIntegrityError("open event state conflicts with seal marker")
            with artifacts._guard():
                artifacts._bind_event_store_unlocked(
                    evidence_store_id, event_log_relpath
                )
                artifacts._validate_event_store_unlocked(
                    evidence_store_id,
                    event_log_relpath,
                    require_open=True,
                )
            directory.assert_bound(EventIntegrityError)
            return cls(
                path,
                directory,
                log_name,
                artifacts,
                clock,
                fd,
                owner_lease_fd,
                events,
                anchored_identity,
                evidence_store_id,
                event_log_relpath,
                cls.OPEN,
            )
        except Exception:
            if fd >= 0:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            if owner_lease_fd is not None:
                try:
                    fcntl.flock(owner_lease_fd, fcntl.LOCK_UN)
                finally:
                    os.close(owner_lease_fd)
            directory.close()
            raise

    @classmethod
    def _verify_final(
        cls,
        directory: _ManagedDirectory,
        log_name: str,
        artifacts: ArtifactStore,
        events: tuple[EpisodeEvent, ...],
        identity: EventIdentity | None,
        evidence_store_id: str,
        event_log_relpath: str,
        state: Mapping[str, object],
    ) -> SealedEvidenceView:
        if identity is None:
            raise EventIntegrityError("final evidence is missing its bound identity")
        if artifacts.identity != identity:
            raise EventIntegrityError(
                "event and artifact evidence have different identities"
            )
        if state.get("evidence_store_id") != evidence_store_id:
            raise EventIntegrityError("event state has the wrong evidence_store_id")
        marker = _seal_marker(directory, log_name)
        with artifacts._guard():
            generation = artifacts._validate_event_store_unlocked(
                evidence_store_id,
                event_log_relpath,
                require_open=False,
            )
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
        event_root = _event_root(events, identity, evidence_store_id)
        if (
            marker["evidence_store_id"] != evidence_store_id
            or marker["event_count"] != len(events)
            or marker["event_root_sha256"] != event_root
            or marker["artifact_root_sha256"] != artifact_root
            or state["event_root_sha256"] != event_root
            or state["artifact_root_sha256"] != artifact_root
        ):
            raise EventIntegrityError("final evidence anchors disagree")
        return SealedEvidenceView(
            identity=identity,
            evidence_store_id=evidence_store_id,
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
        event_log_relpath = artifacts._event_log_relpath(path)
        directory = artifacts._directory_for(
            path.parent, create=False, error_type=EventIntegrityError
        )
        try:
            log_name = _leaf_name(path.name)
            events = _read_event_rows(directory, log_name)
            state, identity = _verify_anchor(directory, log_name, events)
            if identity is None or artifacts.identity != identity:
                raise EventIntegrityError(
                    "event and artifact evidence have different identities"
                )
            store_id = state["evidence_store_id"]
            assert isinstance(store_id, str)
            marker_info = _lstat(
                directory, _seal_name(log_name), error_type=EventIntegrityError
            )
            if state["status"] == "sealed":
                if marker_info is None:
                    raise EventIntegrityError(
                        "sealed event log is missing final marker"
                    )
                cls._verify_final(
                    directory,
                    log_name,
                    artifacts,
                    events,
                    identity,
                    store_id,
                    event_log_relpath,
                    state,
                )
            elif marker_info is not None:
                raise EventIntegrityError("unsealed event log has a final marker")
            else:
                with artifacts._guard():
                    artifacts._validate_event_store_unlocked(
                        store_id,
                        event_log_relpath,
                        require_open=True,
                    )
                    refs = artifacts._list_refs_unlocked()
                    _verify_referenced_artifacts_unlocked(artifacts, events, refs)
            directory.assert_bound(EventIntegrityError)
            return events
        finally:
            directory.close()

    def _release_fd(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def _release_owner_lease(self) -> None:
        if self._owner_lease_fd is not None:
            try:
                fcntl.flock(self._owner_lease_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._owner_lease_fd)
                self._owner_lease_fd = None

    def _poison(self) -> None:
        self._lifecycle = self.POISONED
        self._release_fd()
        self._release_owner_lease()

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
            self._directory.assert_bound(EventIntegrityError)
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
            try:
                with self.artifacts._guard():
                    self.artifacts._validate_event_store_unlocked(
                        self._evidence_store_id,
                        self._event_log_relpath,
                        require_open=True,
                    )
            except EvidenceSealedError:
                self._poison()
                raise
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
                    self._directory,
                    _event_state_name(self._log_name),
                    _event_state(
                        identity=checked_identity,
                        evidence_store_id=self._evidence_store_id,
                        events=self._events,
                        status="poisoned",
                    ),
                    error_type=EventIntegrityError,
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
                    self._directory,
                    _event_state_name(self._log_name),
                    _event_state(
                        identity=checked_identity,
                        evidence_store_id=self._evidence_store_id,
                        events=new_events,
                        status="open",
                    ),
                    error_type=EventIntegrityError,
                )
            except Exception as exc:
                if write_started:
                    try:
                        _atomic_replace(
                            self._directory,
                            _event_state_name(self._log_name),
                            _event_state(
                                identity=checked_identity,
                                evidence_store_id=self._evidence_store_id,
                                events=self._events,
                                status="poisoned",
                            ),
                            error_type=EventIntegrityError,
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
            try:
                self._directory.assert_bound(EventIntegrityError)
            except EventIntegrityError:
                self._poison()
                raise
            return event

    def _open_view(self) -> SealedEvidenceView:
        self._directory.assert_bound(EventIntegrityError)
        events = _read_event_rows(self._directory, self._log_name)
        state, identity = _verify_anchor(self._directory, self._log_name, events)
        if identity is None or self.artifacts.identity != identity:
            raise EventIntegrityError(
                "event and artifact evidence have different identities"
            )
        if state["evidence_store_id"] != self._evidence_store_id:
            raise EventIntegrityError("event evidence_store_id changed")
        if (
            state["status"] != "open"
            or _lstat(
                self._directory,
                _seal_name(self._log_name),
                error_type=EventIntegrityError,
            )
            is not None
        ):
            raise EventIntegrityError("open snapshot conflicts with final evidence")
        with self.artifacts._guard():
            self.artifacts._validate_event_store_unlocked(
                self._evidence_store_id,
                self._event_log_relpath,
                require_open=True,
            )
            refs = self.artifacts._list_refs_unlocked()
            _verify_referenced_artifacts_unlocked(self.artifacts, events, refs)
            artifact_root = _artifact_root(refs)
        self._directory.assert_bound(EventIntegrityError)
        return SealedEvidenceView(
            identity=identity,
            evidence_store_id=self._evidence_store_id,
            audience="full",
            events=events,
            artifacts=refs,
            event_root_sha256=_event_root(events, identity, self._evidence_store_id),
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
                events = _read_event_rows(self._directory, self._log_name)
                state, identity = _verify_anchor(
                    self._directory, self._log_name, events
                )
                return self._verify_final(
                    self._directory,
                    self._log_name,
                    self.artifacts,
                    events,
                    identity,
                    self._evidence_store_id,
                    self._event_log_relpath,
                    state,
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
            if (
                _lstat(
                    self._directory,
                    _seal_name(self._log_name),
                    error_type=EventIntegrityError,
                )
                is not None
            ):
                self._poison()
                raise EventIntegrityError("unexpected pre-existing seal marker")
            try:
                os.fsync(fd)
                events = _read_event_rows(self._directory, self._log_name)
                _validate_joint_chain(
                    events, expected_identity=self._identity, require_visible=True
                )
                _atomic_replace(
                    self._directory,
                    _event_state_name(self._log_name),
                    _event_state(
                        identity=self._identity,
                        evidence_store_id=self._evidence_store_id,
                        events=events,
                        status="sealing",
                    ),
                    error_type=EventIntegrityError,
                )
                with self.artifacts._guard():
                    self.artifacts._validate_event_store_unlocked(
                        self._evidence_store_id,
                        self._event_log_relpath,
                        require_open=True,
                    )
                    refs = self.artifacts._freeze_unlocked()
                    artifact_root = _artifact_root(refs)
                    event_root = _event_root(
                        events, self._identity, self._evidence_store_id
                    )
                    marker = {
                        "spec_version": "aeread.event_seal/2",
                        "evidence_store_id": self._evidence_store_id,
                        "event_count": len(events),
                        "event_root_sha256": event_root,
                        "artifact_root_sha256": artifact_root,
                    }
                    temp = _exclusive_temp_write(
                        self._directory, canonical_json_bytes(marker)
                    )
                    published = False
                    try:
                        _publish_without_overwrite(
                            self._directory,
                            temp,
                            _seal_name(self._log_name),
                        )
                        published = True
                        _fsync_directory(self._directory)
                    finally:
                        try:
                            os.unlink(temp, dir_fd=self._directory.fd)
                        except FileNotFoundError:
                            pass
                        _fsync_directory(self._directory)
                    if not published:
                        raise EventIntegrityError("seal marker publication failed")
                    _atomic_replace(
                        self._directory,
                        _event_state_name(self._log_name),
                        _event_state(
                            identity=self._identity,
                            evidence_store_id=self._evidence_store_id,
                            events=events,
                            status="sealed",
                            artifact_root_sha256=artifact_root,
                        ),
                        error_type=EventIntegrityError,
                    )
                self._directory.assert_bound(EventIntegrityError)
            except Exception as exc:
                self._poison()
                if isinstance(exc, EventIntegrityError):
                    raise
                raise EventIntegrityError("evidence sealing failed closed") from exc
            self._lifecycle = self.SEALED
            self._release_fd()
            self._release_owner_lease()
            state = _read_event_state(self._directory, self._log_name)
            return self._verify_final(
                self._directory,
                self._log_name,
                self.artifacts,
                events,
                self._identity,
                self._evidence_store_id,
                self._event_log_relpath,
                state,
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
        if checked_view.evidence_store_id != self._evidence_store_id:
            raise InvalidEvidenceInput(
                "projection source belongs to a different evidence store"
            )
        _validate_joint_chain(
            checked_view.events,
            expected_identity=checked_view.identity,
            require_visible=True,
        )
        if (
            _event_root(
                checked_view.events,
                checked_view.identity,
                checked_view.evidence_store_id,
            )
            != checked_view.event_root_sha256
        ):
            raise EventIntegrityError("source view event root is invalid")
        if _artifact_root(checked_view.artifacts) != checked_view.artifact_root_sha256:
            raise ArtifactIntegrityError("source view artifact root is invalid")
        if checked_view.is_final:
            events = _read_event_rows(self._directory, self._log_name)
            state, durable_identity = _verify_anchor(
                self._directory, self._log_name, events
            )
            durable = self._verify_final(
                self._directory,
                self._log_name,
                self.artifacts,
                events,
                durable_identity,
                self._evidence_store_id,
                self._event_log_relpath,
                state,
            )
            if (
                checked_view.identity != durable.identity
                or checked_view.evidence_store_id != durable.evidence_store_id
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
                evidence_store_id=checked_view.evidence_store_id,
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
            self._release_owner_lease()
            self._directory.close()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
