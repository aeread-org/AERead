"""Durable append-only evidence and content-addressed artifact storage."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
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


class EvidenceStoreError(Exception):
    """Base class for durable evidence failures."""


class EventIntegrityError(EvidenceStoreError):
    """The event log cannot be verified exactly."""


class ArtifactIntegrityError(EvidenceStoreError):
    """An artifact or its metadata cannot be verified exactly."""


class ConcurrentWriterError(EvidenceStoreError):
    """Another writer already owns this event log."""


class EvidenceSealedError(EvidenceStoreError):
    """The event log has been permanently sealed."""


class InvalidEvidenceInput(EvidenceStoreError, ValueError):
    """Caller input cannot cross the durable evidence boundary."""


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
    """Recompute the versioned hash shared by verify, projection, and replay."""

    try:
        checked = EpisodeEvent.model_validate(event.model_dump(mode="json"))
    except (AttributeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceInput("event is not a valid EpisodeEvent") from exc
    return _domain_digest(b"aeread.event/1", _event_hash_basis(checked))


def _artifact_sort_key(ref: ArtifactRef) -> tuple[str, str, int]:
    return ref.sha256, ref.media_type, ref.size_bytes


def _artifact_metadata(ref: ArtifactRef) -> dict[str, object]:
    return {
        "spec_version": "aeread.artifact_meta/1",
        "sha256": ref.sha256,
        "media_type": ref.media_type,
        "size_bytes": ref.size_bytes,
    }


def _regular_file(
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
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _exclusive_temp_write(directory: Path, data: bytes) -> Path:
    temp = directory / f".tmp-{uuid.uuid4().hex}"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            view = memoryview(data)
            written = 0
            while written < len(view):
                count = os.write(fd, view[written:])
                if count <= 0:
                    raise OSError("incomplete artifact write")
                written += count
            os.fsync(fd)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    finally:
        os.close(fd)
    return temp


def _publish_without_overwrite(temp: Path, target: Path) -> None:
    try:
        os.link(temp, target, follow_symlinks=False)
    except FileExistsError:
        pass


class ArtifactStore:
    """Content-addressed, no-overwrite storage for exact raw bytes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.object_dir = root / "artifacts" / "sha256"

    @classmethod
    def open(cls, root: Path) -> "ArtifactStore":
        if not isinstance(root, Path):
            raise InvalidEvidenceInput("artifact root must be a pathlib.Path")
        object_dir = root / "artifacts" / "sha256"
        object_dir.mkdir(parents=True, exist_ok=True)
        if not object_dir.is_dir() or object_dir.is_symlink():
            raise ArtifactIntegrityError(
                "artifact object directory must be a real directory"
            )
        return cls(root)

    def _paths(self, digest: str) -> tuple[Path, Path]:
        if not _DIGEST_RE.fullmatch(digest):
            raise InvalidEvidenceInput("artifact digest must be lower-case SHA-256")
        return self.object_dir / digest, self.object_dir / f"{digest}{_META_SUFFIX}"

    def put(self, data: bytes, media_type: str) -> ArtifactRef:
        if type(data) is not bytes:
            raise InvalidEvidenceInput("artifact data must be exact bytes")
        if type(media_type) is not str or not media_type:
            raise InvalidEvidenceInput(
                "artifact media_type must be a non-empty exact string"
            )
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
            _publish_without_overwrite(content_temp, content_path)
            _publish_without_overwrite(metadata_temp, metadata_path)
            _fsync_directory(self.object_dir)
        finally:
            for temp in (content_temp, metadata_temp):
                if temp is None:
                    continue
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
        self.verify(ref)
        return ref

    def _read_metadata(self, metadata_path: Path) -> ArtifactRef:
        _regular_file(
            metadata_path, label="artifact metadata", error_type=ArtifactIntegrityError
        )
        try:
            raw = metadata_path.read_bytes()
            value = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError("artifact metadata is malformed") from exc
        if type(value) is not dict or set(value) != {
            "spec_version",
            "sha256",
            "media_type",
            "size_bytes",
        }:
            raise ArtifactIntegrityError("artifact metadata has unexpected fields")
        if value.get("spec_version") != "aeread.artifact_meta/1":
            raise ArtifactIntegrityError("artifact metadata version is unsupported")
        if raw != canonical_json_bytes(value):
            raise ArtifactIntegrityError("artifact metadata is not canonical JSON")
        try:
            return ArtifactRef(
                sha256=value["sha256"],
                media_type=value["media_type"],
                size_bytes=value["size_bytes"],
            )
        except ValidationError as exc:
            raise ArtifactIntegrityError("artifact metadata is invalid") from exc

    def verify(self, ref: ArtifactRef) -> None:
        try:
            checked = ArtifactRef.model_validate(ref.model_dump(mode="json"))
        except (AttributeError, ValidationError) as exc:
            raise InvalidEvidenceInput("ref must be a valid ArtifactRef") from exc
        content_path, metadata_path = self._paths(checked.sha256)
        info = _regular_file(
            content_path, label="artifact content", error_type=ArtifactIntegrityError
        )
        stored_ref = self._read_metadata(metadata_path)
        if stored_ref != checked or info.st_size != checked.size_bytes:
            raise ArtifactIntegrityError(
                "artifact metadata does not match requested ref"
            )
        try:
            data = content_path.read_bytes()
        except OSError as exc:
            raise ArtifactIntegrityError("artifact content is unreadable") from exc
        if hashlib.sha256(data).hexdigest() != checked.sha256:
            raise ArtifactIntegrityError(
                "artifact content digest does not match its path"
            )

    def get(self, ref: ArtifactRef) -> bytes:
        self.verify(ref)
        return self._paths(ref.sha256)[0].read_bytes()

    def list_refs(self) -> tuple[ArtifactRef, ...]:
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
        expected_names = digests | {f"{digest}{_META_SUFFIX}" for digest in digests}
        if names != expected_names:
            raise ArtifactIntegrityError(
                "artifact content and metadata entries are incomplete"
            )
        refs: list[ArtifactRef] = []
        for digest in sorted(digests):
            ref = self._read_metadata(self._paths(digest)[1])
            if ref.sha256 != digest:
                raise ArtifactIntegrityError(
                    "artifact metadata digest does not match its path"
                )
            self.verify(ref)
            refs.append(ref)
        return tuple(sorted(refs, key=_artifact_sort_key))


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
        if isinstance(item, Mapping):
            materialized = dict(item.items())
            if (
                set(materialized)
                == {"spec_version", "sha256", "media_type", "size_bytes"}
                and materialized.get("spec_version") == "aeread.sdk_record/1"
            ):
                try:
                    ref = ArtifactRef.model_validate(materialized)
                except ValidationError as exc:
                    raise ArtifactIntegrityError(
                        "visible artifact reference is malformed"
                    ) from exc
                found[_artifact_sort_key(ref)] = ref
                return
            for nested in materialized.values():
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(found[key] for key in sorted(found))


def _event_root(events: tuple[EpisodeEvent, ...]) -> str:
    identity = events[0].identity.model_dump(mode="json") if events else None
    return _domain_digest(
        b"aeread.event_root/1",
        {
            "identity": identity,
            "event_count": len(events),
            "event_hashes": [event.event_hash for event in events],
        },
    )


def _artifact_root(refs: tuple[ArtifactRef, ...]) -> str:
    return _domain_digest(
        b"aeread.artifact_root/1",
        [ref.model_dump(mode="json") for ref in sorted(refs, key=_artifact_sort_key)],
    )


def _load_seal_view(
    path: Path,
    events: tuple[EpisodeEvent, ...],
    refs: tuple[ArtifactRef, ...],
) -> SealedEvidenceView:
    seal_path = path.with_name(f"{path.name}.sealed.json")
    _regular_file(seal_path, label="event seal marker", error_type=EventIntegrityError)
    try:
        raw = seal_path.read_bytes()
        marker = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventIntegrityError("event seal marker is malformed") from exc
    if type(marker) is not dict or set(marker) != {
        "spec_version",
        "event_count",
        "event_root_sha256",
        "artifact_root_sha256",
    }:
        raise EventIntegrityError("event seal marker has unexpected fields")
    if marker.get(
        "spec_version"
    ) != "aeread.event_seal/1" or raw != canonical_json_bytes(marker):
        raise EventIntegrityError("event seal marker is invalid or noncanonical")
    actual = SealedEvidenceView(
        audience="full",
        events=events,
        artifacts=refs,
        event_root_sha256=_event_root(events),
        artifact_root_sha256=_artifact_root(refs),
        is_final=True,
    )
    if (
        type(marker["event_count"]) is not int
        or marker["event_count"] != len(events)
        or marker["event_root_sha256"] != actual.event_root_sha256
        or marker["artifact_root_sha256"] != actual.artifact_root_sha256
    ):
        raise EventIntegrityError("event seal marker does not match durable evidence")
    return actual


class EventStore:
    """Single-writer canonical JSONL log whose append is durable on return."""

    def __init__(
        self,
        path: Path,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime],
        fd: int,
        events: tuple[EpisodeEvent, ...],
        sealed: bool,
    ) -> None:
        self.path = path
        self.artifacts = artifacts
        self._clock = clock
        self._fd: int | None = fd
        self._events = events
        self._identity = events[0].identity if events else None
        self._sealed = sealed
        self._sealed_view: SealedEvidenceView | None = None

    @property
    def _seal_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.sealed.json")

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> "EventStore":
        if (
            not isinstance(path, Path)
            or not isinstance(artifacts, ArtifactStore)
            or not callable(clock)
        ):
            raise InvalidEvidenceInput("invalid EventStore.open input")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_symlink():
            raise EventIntegrityError("event log must not be a symlink")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise EventIntegrityError("event log must be a regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise ConcurrentWriterError(
                        "event log already has a writer"
                    ) from exc
                raise
            events = cls.verify(path, artifacts=artifacts)
            sealed = path.with_name(f"{path.name}.sealed.json").exists()
            store = cls(path, artifacts, clock, fd, events, sealed)
            if sealed:
                store._sealed_view = store._verify_seal_marker()
            return store
        except Exception:
            os.close(fd)
            raise

    @classmethod
    def verify(
        cls, path: Path, *, artifacts: ArtifactStore
    ) -> tuple[EpisodeEvent, ...]:
        if not isinstance(path, Path) or not isinstance(artifacts, ArtifactStore):
            raise InvalidEvidenceInput("invalid EventStore.verify input")
        _regular_file(path, label="event log", error_type=EventIntegrityError)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise EventIntegrityError("event log is unreadable") from exc
        if raw and not raw.endswith(b"\n"):
            raise EventIntegrityError("event log has a partial final row")
        events: list[EpisodeEvent] = []
        expected_identity: EventIdentity | None = None
        prior_hash: str | None = None
        for expected_sequence, line in enumerate(raw.splitlines(keepends=True)):
            row = line[:-1]
            if not row:
                raise EventIntegrityError("event log contains a blank row")
            try:
                decoded = json.loads(row)
                event = EpisodeEvent.model_validate(decoded)
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ) as exc:
                raise EventIntegrityError("event row is malformed") from exc
            if row != canonical_json_bytes(event):
                raise EventIntegrityError("event row is not canonical JSON")
            if not event.payload_visible or event.payload is None:
                raise EventIntegrityError("on-disk event payloads must be visible")
            if event.sequence != expected_sequence:
                raise EventIntegrityError("event sequence is not contiguous from zero")
            if expected_identity is None:
                expected_identity = event.identity
            elif event.identity != expected_identity:
                raise EventIntegrityError("event log contains multiple identities")
            if event.event_id != _event_id(event.identity, event.sequence):
                raise EventIntegrityError(
                    "event ID does not match identity and sequence"
                )
            if event.prior_event_hash != prior_hash:
                raise EventIntegrityError(
                    "event prior hash does not match its predecessor"
                )
            if recompute_event_hash(event) != event.event_hash:
                raise EventIntegrityError("event hash does not match event content")
            prior_hash = event.event_hash
            events.append(event)
        refs = artifacts.list_refs()
        result = tuple(events)
        seal_path = path.with_name(f"{path.name}.sealed.json")
        if seal_path.exists() or seal_path.is_symlink():
            _load_seal_view(path, result, refs)
        return result

    def append(
        self,
        event_type: str,
        identity: EventIdentity,
        visibility: str,
        payload: Mapping[str, object],
    ) -> EpisodeEvent:
        if self._sealed:
            raise EvidenceSealedError("event log has been sealed")
        if self._fd is None:
            raise EvidenceStoreError("event store is closed")
        if type(event_type) is not str or not event_type:
            raise InvalidEvidenceInput("event_type must be a non-empty exact string")
        checked_visibility = _validate_visibility(visibility)
        try:
            identity_value = (
                identity.model_dump(mode="json")
                if isinstance(identity, BaseModel)
                else identity
            )
            checked_identity = EventIdentity.model_validate(identity_value)
        except (ValidationError, ValueError, AttributeError) as exc:
            raise InvalidEvidenceInput(
                "identity must be a valid EventIdentity"
            ) from exc
        if self._identity is not None and checked_identity != self._identity:
            raise InvalidEvidenceInput("one event log can contain only one identity")
        sequence = len(self._events)
        occurred_at = _utc_timestamp(self._clock)
        prior_hash = self._events[-1].event_hash if self._events else None
        try:
            payload_hash = content_sha256(payload)
            basis_event = EpisodeEvent(
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
            event = basis_event.model_copy(
                update={"event_hash": recompute_event_hash(basis_event)}
            )
            event = EpisodeEvent.model_validate(event.model_dump(mode="json"))
        except (ValidationError, ValueError) as exc:
            raise InvalidEvidenceInput(
                "payload cannot be stored as a canonical event"
            ) from exc
        encoded = canonical_json_bytes(event) + b"\n"
        written = 0
        while written < len(encoded):
            count = os.write(self._fd, encoded[written:])
            if count <= 0:
                raise EventIntegrityError("event append was incomplete")
            written += count
        os.fsync(self._fd)
        self._events = (*self._events, event)
        self._identity = checked_identity
        return event

    def _make_view(self, *, is_final: bool) -> SealedEvidenceView:
        events = self.verify(self.path, artifacts=self.artifacts)
        all_refs = self.artifacts.list_refs()
        for event in events:
            for ref in _discover_artifact_refs(event.payload):
                self.artifacts.verify(ref)
        return SealedEvidenceView(
            audience="full",
            events=events,
            artifacts=all_refs,
            event_root_sha256=_event_root(events),
            artifact_root_sha256=_artifact_root(all_refs),
            is_final=is_final,
        )

    def snapshot(self) -> SealedEvidenceView:
        if self._fd is None and self._sealed_view is None:
            raise EvidenceStoreError("event store is closed")
        if self._sealed and self._sealed_view is not None:
            return self._sealed_view
        return self._make_view(is_final=False)

    def _verify_seal_marker(self) -> SealedEvidenceView:
        return _load_seal_view(self.path, self._events, self.artifacts.list_refs())

    def seal(self) -> SealedEvidenceView:
        if self._sealed_view is not None:
            return self._sealed_view
        if self._fd is None:
            raise EvidenceStoreError("event store is closed")
        view = self._make_view(is_final=True)
        marker = canonical_json_bytes(
            {
                "spec_version": "aeread.event_seal/1",
                "event_count": len(view.events),
                "event_root_sha256": view.event_root_sha256,
                "artifact_root_sha256": view.artifact_root_sha256,
            }
        )
        if self._seal_path.exists():
            existing = self._seal_path.read_bytes()
            if existing != marker:
                raise EventIntegrityError("pre-existing seal marker disagrees")
        else:
            temp = _exclusive_temp_write(self.path.parent, marker)
            try:
                _publish_without_overwrite(temp, self._seal_path)
                _fsync_directory(self.path.parent)
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
            if self._seal_path.read_bytes() != marker:
                raise EventIntegrityError("concurrent seal marker disagrees")
        os.fsync(self._fd)
        self._sealed = True
        self._sealed_view = view
        self.close()
        return view

    def project(self, view: SealedEvidenceView, audience: str) -> SealedEvidenceView:
        checked_audience = _validate_visibility(audience, allow_full=True)
        if checked_audience == "evaluator_only":
            raise InvalidEvidenceInput(
                "projection audience is evaluator, not evaluator_only"
            )
        try:
            checked_view = SealedEvidenceView.model_validate(
                view.model_dump(mode="json")
            )
        except (AttributeError, ValidationError) as exc:
            raise InvalidEvidenceInput(
                "view must be a valid SealedEvidenceView"
            ) from exc
        if checked_view.audience not in {"full", "evaluator"}:
            raise InvalidEvidenceInput("projection source must be a full evidence view")
        if _event_root(checked_view.events) != checked_view.event_root_sha256:
            raise EventIntegrityError("source view event root is invalid")
        if _artifact_root(checked_view.artifacts) != checked_view.artifact_root_sha256:
            raise ArtifactIntegrityError("source view artifact root is invalid")
        committed_artifacts = {
            _artifact_sort_key(ref): ref for ref in checked_view.artifacts
        }
        for ref in checked_view.artifacts:
            self.artifacts.verify(ref)
        for event in checked_view.events:
            if not event.payload_visible or event.payload is None:
                raise EventIntegrityError(
                    "full projection source contains redacted events"
                )
            if recompute_event_hash(event) != event.event_hash:
                raise EventIntegrityError("source view contains an invalid event hash")
            for ref in _discover_artifact_refs(event.payload):
                if _artifact_sort_key(ref) not in committed_artifacts:
                    raise ArtifactIntegrityError(
                        "source event references an artifact absent from its full root"
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
                projected = event.model_copy(
                    update={"payload": None, "payload_visible": False}
                )
                projected = EpisodeEvent.model_validate(
                    projected.model_dump(mode="json")
                )
            projected_events.append(projected)
        if checked_audience in {"full", "evaluator"}:
            projected_artifacts = checked_view.artifacts
        else:
            projected_artifacts = tuple(
                visible_refs[key] for key in sorted(visible_refs)
            )
        return SealedEvidenceView(
            audience=checked_audience,
            events=tuple(projected_events),
            artifacts=projected_artifacts,
            event_root_sha256=checked_view.event_root_sha256,
            artifact_root_sha256=checked_view.artifact_root_sha256,
            is_final=checked_view.is_final,
        )

    def close(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
