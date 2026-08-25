from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from aeread.runner import (
    ArtifactIntegrityError,
    ArtifactStore,
    ConcurrentWriterError,
    EventIntegrityError,
    EventStore,
    EvidenceSealedError,
    InvalidEvidenceInput,
    recompute_event_hash,
)
from aeread.sdk.v1 import ArtifactRef, EpisodeEvent, EventIdentity, canonical_json_bytes


IDENTITY = EventIdentity(
    run_plan_id="plan-1",
    cell_id="cell-1",
    episode_id="episode-1",
    episode_attempt_id="attempt-1",
)
FIXED_TIME = datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def artifact_store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore.open(tmp_path / "evidence")


def event_store(tmp_path: Path, *, clock=fixed_clock) -> EventStore:
    return EventStore.open(
        tmp_path / "events.jsonl", artifacts=artifact_store(tmp_path), clock=clock
    )


def rewrite_rows(path: Path, mutation) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutation(rows)
    path.write_bytes(b"".join(canonical_json_bytes(row) + b"\n" for row in rows))


def test_artifact_put_uses_raw_sha_and_survives_reopen(tmp_path: Path) -> None:
    store = artifact_store(tmp_path)
    data = b"\x00raw artifact\n"

    first = store.put(data, "application/octet-stream")
    second = ArtifactStore.open(tmp_path / "evidence").put(
        data, "application/octet-stream"
    )

    assert first == second
    assert first.sha256 == hashlib.sha256(data).hexdigest()
    assert store.get(first) == data
    assert store.list_refs() == (first,)


def test_artifact_rejects_different_metadata_for_existing_digest(
    tmp_path: Path,
) -> None:
    store = artifact_store(tmp_path)
    store.put(b"same", "text/plain")

    with pytest.raises(ArtifactIntegrityError):
        store.put(b"same", "application/octet-stream")


@pytest.mark.parametrize("target", ["content", "sidecar"])
def test_artifact_rejects_corruption_and_symlinks(tmp_path: Path, target: str) -> None:
    store = artifact_store(tmp_path)
    ref = store.put(b"original", "text/plain")
    object_dir = tmp_path / "evidence" / "artifacts" / "sha256"
    path = object_dir / ref.sha256
    if target == "sidecar":
        path = object_dir / f"{ref.sha256}.meta.json"
    path.unlink()
    path.symlink_to(tmp_path / "missing")

    with pytest.raises(ArtifactIntegrityError):
        store.list_refs()


def test_artifact_rejects_unexpected_and_malformed_entries(tmp_path: Path) -> None:
    store = artifact_store(tmp_path)
    ref = store.put(b"original", "text/plain")
    object_dir = tmp_path / "evidence" / "artifacts" / "sha256"
    (object_dir / f"{ref.sha256}.meta.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError):
        store.verify(ref)

    (object_dir / f"{ref.sha256}.meta.json").unlink()
    (object_dir / "unexpected").write_bytes(b"junk")
    with pytest.raises(ArtifactIntegrityError):
        store.list_refs()


def test_failed_artifact_write_cleans_exclusive_temporary_file(
    tmp_path: Path, monkeypatch
) -> None:
    store = artifact_store(tmp_path)

    def failing_write(fd: int, data: bytes) -> int:
        raise OSError("simulated interrupted write")

    monkeypatch.setattr("aeread.runner.event_store.os.write", failing_write)
    with pytest.raises(OSError, match="simulated interrupted write"):
        store.put(b"never published", "text/plain")

    assert tuple(store.object_dir.iterdir()) == ()


def test_failed_metadata_temp_write_also_cleans_content_temp(
    tmp_path: Path, monkeypatch
) -> None:
    store = artifact_store(tmp_path)
    real_write = os.write
    writes = 0

    def fail_second_temp(fd: int, data: bytes) -> int:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated metadata write failure")
        return real_write(fd, data)

    monkeypatch.setattr("aeread.runner.event_store.os.write", fail_second_temp)
    with pytest.raises(OSError, match="simulated metadata write failure"):
        store.put(b"content temp", "text/plain")

    assert tuple(store.object_dir.iterdir()) == ()


def test_append_is_canonical_and_durable_before_return(
    tmp_path: Path, monkeypatch
) -> None:
    store = event_store(tmp_path)
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr("aeread.runner.event_store.os.fsync", recording_fsync)
    event = store.append("episode_started", IDENTITY, "public", {"value": 3})

    raw = (tmp_path / "events.jsonl").read_bytes()
    assert raw == canonical_json_bytes(event) + b"\n"
    assert json.loads(raw)["event_id"] == event.event_id
    assert fsync_calls


def test_writer_lock_is_process_visible_and_released_on_close(tmp_path: Path) -> None:
    first = event_store(tmp_path)
    with pytest.raises(ConcurrentWriterError):
        event_store(tmp_path)

    first.close()
    second = event_store(tmp_path)
    second.append("continued", IDENTITY, "public", {})
    second.close()


def test_snapshot_is_immutable_prefix_and_does_not_close_writer(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    first = store.append("first", IDENTITY, "public", {})
    snapshot = store.snapshot()
    second = store.append("second", IDENTITY, "public", {})

    assert snapshot.is_final is False
    assert snapshot.audience == "full"
    assert snapshot.events == (first,)
    assert store.snapshot().events == (first, second)


def test_seal_is_persistent_idempotent_and_rejects_append(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    sealed = store.seal()

    assert sealed.is_final is True
    assert store.seal() == sealed
    with pytest.raises(EvidenceSealedError):
        store.append("late", IDENTITY, "public", {})
    store.close()

    reopened = event_store(tmp_path)
    with pytest.raises(EvidenceSealedError):
        reopened.append("later", IDENTITY, "public", {})
    assert reopened.seal() == sealed


def test_seal_marker_commits_roots_without_copying_private_payload(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    store.append(
        "private",
        IDENTITY,
        "evaluator_only",
        {"secret": "must-remain-only-in-events-log"},
    )
    sealed = store.seal()
    marker = json.loads((tmp_path / "events.jsonl.sealed.json").read_bytes())

    assert "must-remain-only-in-events-log" not in json.dumps(marker)
    assert marker["event_root_sha256"] == sealed.event_root_sha256
    assert marker["artifact_root_sha256"] == sealed.artifact_root_sha256
    assert marker["event_count"] == 1


def test_identity_sequence_time_and_hashes_are_bound(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    first = store.append("first", IDENTITY, "public", {"x": 1})
    second = store.append("second", IDENTITY, "seat:buyer-1", {"x": 2})

    assert first.sequence == 0
    assert second.sequence == 1
    assert first.event_id != second.event_id
    assert first.occurred_at == "2026-08-24T12:30:00.000000Z"
    assert second.prior_event_hash == first.event_hash
    assert recompute_event_hash(first) == first.event_hash
    with pytest.raises(InvalidEvidenceInput):
        store.append(
            "wrong", IDENTITY.model_copy(update={"cell_id": "other"}), "public", {}
        )


def test_timestamp_changes_event_hash_but_not_event_id(tmp_path: Path) -> None:
    first = event_store(tmp_path / "first", clock=fixed_clock).append(
        "same", IDENTITY, "public", {}
    )
    later = lambda: FIXED_TIME + timedelta(seconds=1)
    second = event_store(tmp_path / "second", clock=later).append(
        "same", IDENTITY, "public", {}
    )

    assert first.event_id == second.event_id
    assert first.event_hash != second.event_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("payload", {"x": 2}),
        ("payload_sha256", "0" * 64),
        ("event_hash", "0" * 64),
        ("prior_event_hash", "0" * 64),
        ("sequence", 7),
        (
            "identity",
            {
                "run_plan_id": "other",
                "cell_id": "cell-1",
                "episode_id": "episode-1",
                "episode_attempt_id": "attempt-1",
                "spec_version": "aeread.sdk_record/1",
            },
        ),
        ("event_id", "wrong"),
    ],
)
def test_verify_rejects_tampered_event_fields(
    tmp_path: Path, field: str, value
) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {"x": 1})
    store.close()
    rewrite_rows(
        tmp_path / "events.jsonl", lambda rows: rows[0].__setitem__(field, value)
    )

    with pytest.raises(EventIntegrityError):
        EventStore.verify(tmp_path / "events.jsonl", artifacts=artifact_store(tmp_path))


def test_verify_rejects_reorder_deletion_noncanonical_and_partial_rows(
    tmp_path: Path,
) -> None:
    for case in ("reorder", "delete", "noncanonical", "partial"):
        case_root = tmp_path / case
        store = event_store(case_root)
        store.append("first", IDENTITY, "public", {})
        store.append("second", IDENTITY, "public", {})
        store.close()
        path = case_root / "events.jsonl"
        lines = path.read_bytes().splitlines(keepends=True)
        if case == "reorder":
            path.write_bytes(lines[1] + lines[0])
        elif case == "delete":
            path.write_bytes(lines[1])
        elif case == "noncanonical":
            path.write_bytes(
                json.dumps(json.loads(lines[0]), indent=2).encode() + b"\n" + lines[1]
            )
        else:
            path.write_bytes(b"".join(lines) + b'{"partial"')

        with pytest.raises(EventIntegrityError):
            EventStore.verify(path, artifacts=artifact_store(case_root))


def test_verify_uses_seal_root_to_reject_tail_deletion(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    store.append("second", IDENTITY, "public", {})
    store.seal()
    path = tmp_path / "events.jsonl"
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])

    with pytest.raises(EventIntegrityError):
        EventStore.verify(path, artifacts=artifact_store(tmp_path))


def test_snapshot_and_seal_roots_cover_empty_and_nonempty_evidence(
    tmp_path: Path,
) -> None:
    empty = event_store(tmp_path / "empty")
    empty_view = empty.snapshot()
    assert len(empty_view.event_root_sha256) == 64
    assert len(empty_view.artifact_root_sha256) == 64

    nonempty = event_store(tmp_path / "nonempty")
    nonempty.append("first", IDENTITY, "public", {})
    nonempty.artifacts.put(b"blob", "application/octet-stream")
    final = nonempty.seal()
    assert final.event_root_sha256 != empty_view.event_root_sha256
    assert final.artifact_root_sha256 != empty_view.artifact_root_sha256


def test_projection_preserves_rows_hashes_and_nested_artifact_privacy(
    tmp_path: Path,
) -> None:
    artifacts = artifact_store(tmp_path)
    public_ref = artifacts.put(b"public", "text/plain")
    private_ref = artifacts.put(b"private", "text/plain")
    store = EventStore.open(
        tmp_path / "events.jsonl", artifacts=artifacts, clock=fixed_clock
    )
    public_event = store.append(
        "public", IDENTITY, "public", {"nested": [public_ref.model_dump()]}
    )
    private_event = store.append(
        "private", IDENTITY, "seat:buyer-1", {"ref": private_ref.model_dump()}
    )
    evaluator_event = store.append("audit", IDENTITY, "evaluator_only", {"secret": 1})
    full = store.snapshot()

    public = store.project(full, "public")
    buyer = store.project(full, "seat:buyer-1")
    evaluator = store.project(full, "evaluator")

    assert [event.event_id for event in public.events] == [
        event.event_id for event in full.events
    ]
    assert public.events[0].payload == public_event.payload
    assert public.events[1].payload is None and not public.events[1].payload_visible
    assert public.events[1].event_hash == private_event.event_hash
    assert public.events[2].payload is None and evaluator_event.payload is not None
    assert public.artifacts == (public_ref,)
    assert buyer.artifacts == tuple(
        sorted(
            (private_ref, public_ref),
            key=lambda ref: (ref.sha256, ref.media_type, ref.size_bytes),
        )
    )
    assert evaluator.events == full.events
    assert evaluator.artifacts == full.artifacts
    assert public.event_root_sha256 == full.event_root_sha256
    assert public.artifact_root_sha256 == full.artifact_root_sha256


def test_visible_missing_artifact_reference_invalidates_snapshot(
    tmp_path: Path,
) -> None:
    missing = ArtifactRef(sha256="f" * 64, media_type="text/plain", size_bytes=1)
    store = event_store(tmp_path)
    store.append("bad-ref", IDENTITY, "public", {"ref": missing.model_dump()})

    with pytest.raises(ArtifactIntegrityError):
        store.snapshot()


def test_projection_verifies_hidden_artifacts_that_full_root_commits_to(
    tmp_path: Path,
) -> None:
    artifacts = artifact_store(tmp_path)
    hidden_ref = artifacts.put(b"private", "text/plain")
    store = EventStore.open(
        tmp_path / "events.jsonl", artifacts=artifacts, clock=fixed_clock
    )
    store.append(
        "private",
        IDENTITY,
        "seat:buyer-1",
        {"ref": hidden_ref.model_dump()},
    )
    full = store.snapshot()
    (artifacts.object_dir / hidden_ref.sha256).write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        store.project(full, "public")


@pytest.mark.parametrize(
    "visibility", ["seat:", "seat:bad space", "private", "evaluator"]
)
def test_malformed_visibility_is_a_typed_input_error(
    tmp_path: Path, visibility: str
) -> None:
    store = event_store(tmp_path)
    with pytest.raises(InvalidEvidenceInput):
        store.append("bad", IDENTITY, visibility, {})


def test_malformed_payload_identity_and_clock_are_typed(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    with pytest.raises(InvalidEvidenceInput):
        store.append("bad", {"cell_id": "missing"}, "public", {})
    with pytest.raises(InvalidEvidenceInput):
        store.append("bad", IDENTITY, "public", {"bad": object()})

    bad_clock = event_store(tmp_path / "clock", clock=lambda: datetime.now())
    with pytest.raises(InvalidEvidenceInput):
        bad_clock.append("bad", IDENTITY, "public", {})


def test_event_records_are_strict_deeply_immutable_and_schema_serializable() -> None:
    schema = EpisodeEvent.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "payload_sha256" in schema["properties"]
    with pytest.raises(ValidationError):
        EpisodeEvent(
            event_id="event",
            sequence=0,
            event_type="test",
            occurred_at="2026-08-24T12:30:00.000000Z",
            identity=IDENTITY,
            visibility="public",
            payload={"nested": []},
            payload_visible=True,
            payload_sha256="0" * 64,
            prior_event_hash=None,
            event_hash="0" * 64,
            unknown=True,
        )
