from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading

import pytest
from pydantic import ValidationError

from aeread.runner import (
    ArtifactIntegrityError,
    ArtifactStore,
    ConcurrentWriterError,
    EventIntegrityError,
    EventStore,
    EvidenceSealedError,
    EvidenceStoreError,
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
    tmp_path.mkdir(parents=True, exist_ok=True)
    return ArtifactStore.open(
        tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
    )


def event_store(tmp_path: Path, *, clock=fixed_clock) -> EventStore:
    return EventStore.open(
        tmp_path / "events.jsonl",
        artifacts=artifact_store(tmp_path),
        clock=clock,
        identity=IDENTITY,
    )


def rewrite_rows(path: Path, mutation) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutation(rows)
    path.write_bytes(b"".join(canonical_json_bytes(row) + b"\n" for row in rows))


def test_artifact_put_uses_raw_sha_and_survives_reopen(tmp_path: Path) -> None:
    store = artifact_store(tmp_path)
    data = b"\x00raw artifact\n"

    first = store.put(data, "application/octet-stream")
    second = ArtifactStore.open(
        tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
    ).put(data, "application/octet-stream")

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
        tmp_path / "events.jsonl",
        artifacts=artifacts,
        clock=fixed_clock,
        identity=IDENTITY,
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
        tmp_path / "events.jsonl",
        artifacts=artifacts,
        clock=fixed_clock,
        identity=IDENTITY,
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


def test_failed_seal_publication_is_fail_closed_and_releases_writer(
    tmp_path: Path, monkeypatch
) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    real_fsync_directory = __import__(
        "aeread.runner.event_store", fromlist=["_fsync_directory"]
    )._fsync_directory

    def fail_after_marker_publish(path: Path) -> None:
        real_fsync_directory(path)
        if (tmp_path / "events.jsonl.sealed.json").exists():
            raise OSError("seal directory fsync failed")

    monkeypatch.setattr(
        "aeread.runner.event_store._fsync_directory", fail_after_marker_publish
    )
    with pytest.raises(EventIntegrityError):
        store.seal()
    with pytest.raises(EventIntegrityError):
        store.append("must-not-run", IDENTITY, "public", {})

    monkeypatch.setattr(
        "aeread.runner.event_store._fsync_directory", real_fsync_directory
    )
    with pytest.raises(EventIntegrityError):
        event_store(tmp_path)


def test_sealed_snapshot_and_seal_reverify_instead_of_returning_cache(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    event = store.append("first", IDENTITY, "public", {})
    store.seal()
    (tmp_path / "events.jsonl").write_bytes(
        canonical_json_bytes(event.model_copy(update={"payload": {"tampered": True}}))
        + b"\n"
    )

    with pytest.raises(EventIntegrityError):
        store.snapshot()
    with pytest.raises(EventIntegrityError):
        store.seal()


def test_reopened_sealed_reader_does_not_retain_writer_lock(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    store.seal()

    first_reader = event_store(tmp_path)
    second_reader = event_store(tmp_path)
    assert first_reader.snapshot() == second_reader.snapshot()


def test_existing_seal_marker_must_be_regular_and_never_followed(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    store.seal()
    marker = tmp_path / "events.jsonl.sealed.json"
    marker.unlink()
    external = tmp_path / "external-marker"
    marker.symlink_to(external)

    with pytest.raises(EventIntegrityError):
        event_store(tmp_path)
    assert not external.exists()


def test_artifact_generation_is_frozen_by_final_seal(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.artifacts.put(b"before", "text/plain")
    store.seal()

    with pytest.raises(EvidenceSealedError):
        store.artifacts.put(b"after", "text/plain")
    with pytest.raises(EvidenceSealedError):
        ArtifactStore.open(
            tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
        ).put(b"after", "text/plain")


@pytest.mark.parametrize("failure", ["partial_write", "fsync"])
def test_append_io_failure_poison_closes_writer(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    store = event_store(tmp_path)
    event_inode = (tmp_path / "events.jsonl").stat().st_ino
    if failure == "partial_write":
        real_write = os.write
        calls = 0

        def fail_after_partial(fd: int, data: bytes) -> int:
            nonlocal calls
            if os.fstat(fd).st_ino != event_inode:
                return real_write(fd, data)
            calls += 1
            if calls == 1:
                return real_write(fd, data[: max(1, len(data) // 2)])
            raise OSError("event write interrupted")

        monkeypatch.setattr("aeread.runner.event_store.os.write", fail_after_partial)
    else:
        real_fsync = os.fsync

        def fail_event_fsync(fd: int) -> None:
            if os.fstat(fd).st_ino == event_inode:
                raise OSError("event fsync interrupted")
            real_fsync(fd)

        monkeypatch.setattr("aeread.runner.event_store.os.fsync", fail_event_fsync)

    with pytest.raises(EventIntegrityError):
        store.append("failed", IDENTITY, "public", {})
    with pytest.raises(EventIntegrityError):
        store.append("must-not-run", IDENTITY, "public", {})


def test_high_water_publish_failure_persists_poisoned_state(
    tmp_path: Path, monkeypatch
) -> None:
    store = event_store(tmp_path)
    real_fsync_directory = __import__(
        "aeread.runner.event_store", fromlist=["_fsync_directory"]
    )._fsync_directory

    def fail_after_open_anchor_replace(path: Path) -> None:
        real_fsync_directory(path)
        anchor = tmp_path / "events.jsonl.state.json"
        if anchor.exists():
            state = json.loads(anchor.read_bytes())
            if state["status"] == "open" and state["event_count"] == 1:
                raise OSError("high-water directory fsync failed")

    monkeypatch.setattr(
        "aeread.runner.event_store._fsync_directory", fail_after_open_anchor_replace
    )
    with pytest.raises(EventIntegrityError):
        store.append("uncertain", IDENTITY, "public", {})
    monkeypatch.setattr(
        "aeread.runner.event_store._fsync_directory", real_fsync_directory
    )

    with pytest.raises(EventIntegrityError):
        event_store(tmp_path)


def test_unsealed_high_water_rejects_valid_tail_deletion(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    store.append("second", IDENTITY, "public", {})
    store.close()
    path = tmp_path / "events.jsonl"
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])

    with pytest.raises(EventIntegrityError):
        EventStore.verify(path, artifacts=artifact_store(tmp_path))


def test_deleting_final_marker_never_makes_log_appendable(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    store.seal()
    (tmp_path / "events.jsonl.sealed.json").unlink()

    with pytest.raises(EventIntegrityError):
        event_store(tmp_path)


def test_explicit_empty_identity_changes_empty_event_root(tmp_path: Path) -> None:
    first = EventStore.open(
        tmp_path / "first.jsonl",
        artifacts=ArtifactStore.open(
            tmp_path / "first-evidence", identity=IDENTITY, trusted_root=tmp_path
        ),
        clock=fixed_clock,
        identity=IDENTITY,
    ).snapshot()
    second_identity = IDENTITY.model_copy(update={"episode_attempt_id": "attempt-2"})
    second = EventStore.open(
        tmp_path / "second.jsonl",
        artifacts=ArtifactStore.open(
            tmp_path / "second-evidence",
            identity=second_identity,
            trusted_root=tmp_path,
        ),
        clock=fixed_clock,
        identity=second_identity,
    ).snapshot()

    assert first.event_root_sha256 != second.event_root_sha256


def test_new_event_store_requires_identity_for_empty_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvidenceInput):
        EventStore.open(
            tmp_path / "unbound.jsonl",
            artifacts=ArtifactStore.open(
                tmp_path / "unbound-evidence",
                identity=IDENTITY,
                trusted_root=tmp_path,
            ),
            clock=fixed_clock,
        )


def test_projection_rejects_reordered_joint_chain_even_with_recomputed_root(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    store.append("second", IDENTITY, "public", {})
    full = store.snapshot()
    reversed_events = tuple(reversed(full.events))
    forged_root = hashlib.sha256(
        b"aeread.event_root/2\0"
        + canonical_json_bytes(
            {
                "identity": reversed_events[0].identity.model_dump(mode="json"),
                "evidence_store_id": full.evidence_store_id,
                "event_count": 2,
                "event_hashes": [event.event_hash for event in reversed_events],
            }
        )
    ).hexdigest()
    reordered = full.model_copy(
        update={"events": reversed_events, "event_root_sha256": forged_root}
    )

    with pytest.raises(EventIntegrityError):
        store.project(reordered, "public")


def test_public_view_record_rejects_evaluator_plaintext(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("secret", IDENTITY, "evaluator_only", {"secret": True})
    full = store.snapshot()

    with pytest.raises(ValidationError):
        full.model_copy(update={"audience": "public"}).__class__.model_validate(
            full.model_copy(update={"audience": "public"}).model_dump(mode="json")
        )


def test_project_rejects_forged_final_snapshot(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("first", IDENTITY, "public", {})
    forged = store.snapshot().model_copy(update={"is_final": True})

    with pytest.raises(EventIntegrityError):
        store.project(forged, "public")


def test_event_creation_fsyncs_parent_directory(tmp_path: Path, monkeypatch) -> None:
    artifacts = artifact_store(tmp_path)
    directory_fsyncs = 0
    real_fsync = os.fsync

    def count_directory_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr("aeread.runner.event_store.os.fsync", count_directory_fsync)
    EventStore.open(
        tmp_path / "new-events.jsonl",
        artifacts=artifacts,
        clock=fixed_clock,
        identity=IDENTITY,
    )

    assert directory_fsyncs >= 1


def test_artifact_creation_and_temp_cleanup_are_directory_durable(
    tmp_path: Path, monkeypatch
) -> None:
    directory_fsyncs = 0
    real_fsync = os.fsync

    def count_directory_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr("aeread.runner.event_store.os.fsync", count_directory_fsync)
    store = ArtifactStore.open(
        tmp_path / "new-evidence", identity=IDENTITY, trusted_root=tmp_path
    )
    baseline = directory_fsyncs
    store.put(b"durable", "text/plain")

    assert baseline >= 3
    assert directory_fsyncs >= baseline + 1
    assert not any(path.name.startswith(".tmp-") for path in store.object_dir.iterdir())


def test_hostile_model_copy_is_translated_to_invalid_input(tmp_path: Path) -> None:
    class Hostile:
        def __getattribute__(self, name: str):
            raise RuntimeError("hostile scalar")

    artifacts = artifact_store(tmp_path)
    ref = ArtifactRef(
        sha256="0" * 64, media_type="text/plain", size_bytes=0
    ).model_copy(update={"sha256": Hostile()})

    with pytest.raises(InvalidEvidenceInput):
        artifacts.verify(ref)


def test_dangling_event_symlink_is_rejected_before_target_creation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "outside-target"
    path = tmp_path / "events.jsonl"
    path.symlink_to(target)

    with pytest.raises(EventIntegrityError):
        EventStore.open(
            path,
            artifacts=artifact_store(tmp_path),
            clock=fixed_clock,
            identity=IDENTITY,
        )
    assert not target.exists()


def test_artifact_open_rejects_symlinked_ancestor_before_external_mkdir(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external-artifacts"
    external.mkdir()
    linked = tmp_path / "linked-artifacts"
    linked.symlink_to(external, target_is_directory=True)

    with pytest.raises(ArtifactIntegrityError):
        ArtifactStore.open(
            linked / "missing" / "evidence",
            identity=IDENTITY,
            trusted_root=tmp_path,
        )
    assert not (external / "missing").exists()


def test_event_open_rejects_symlinked_ancestor_before_external_mkdir(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external-events"
    external.mkdir()
    linked = tmp_path / "linked-events"
    linked.symlink_to(external, target_is_directory=True)

    with pytest.raises(EventIntegrityError):
        EventStore.open(
            linked / "missing" / "events.jsonl",
            artifacts=artifact_store(tmp_path),
            clock=fixed_clock,
            identity=IDENTITY,
        )
    assert not (external / "missing").exists()


def test_snapshot_never_returns_view_missing_a_racing_referenced_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    late_data = b"late artifact"
    late_ref = ArtifactRef(
        sha256=hashlib.sha256(late_data).hexdigest(),
        media_type="text/plain",
        size_bytes=len(late_data),
    )
    store = event_store(tmp_path)
    store.append("late-ref", IDENTITY, "public", {"ref": late_ref.model_dump()})
    before_public_verify = threading.Event()
    allow_verify = threading.Event()
    real_verify = store.artifacts.verify

    def gated_verify(ref: ArtifactRef) -> None:
        before_public_verify.set()
        assert allow_verify.wait(timeout=2)
        real_verify(ref)

    monkeypatch.setattr(store.artifacts, "verify", gated_verify)
    outcome: dict[str, object] = {}

    def take_snapshot() -> None:
        try:
            outcome["view"] = store.snapshot()
        except Exception as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=take_snapshot)
    thread.start()
    if before_public_verify.wait(timeout=0.5):
        store.artifacts.put(late_data, "text/plain")
    allow_verify.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    if "view" in outcome:
        assert late_ref in outcome["view"].artifacts
    else:
        assert isinstance(outcome.get("error"), ArtifactIntegrityError)


def test_artifact_generation_is_owned_by_one_event_identity(tmp_path: Path) -> None:
    root = tmp_path / "owned-evidence"
    first = ArtifactStore.open(root, identity=IDENTITY, trusted_root=tmp_path)
    first.put(b"private", "text/plain")
    other = IDENTITY.model_copy(update={"episode_attempt_id": "attempt-2"})

    with pytest.raises(InvalidEvidenceInput):
        ArtifactStore.open(root, identity=other, trusted_root=tmp_path)
    with pytest.raises(InvalidEvidenceInput):
        EventStore.open(
            tmp_path / "other-events.jsonl",
            artifacts=first,
            clock=fixed_clock,
            identity=other,
        )
    assert not (tmp_path / "other-events.jsonl").exists()


def test_artifact_store_requires_identity_before_generation_side_effects(
    tmp_path: Path,
) -> None:
    root = tmp_path / "unowned-evidence"
    with pytest.raises(InvalidEvidenceInput):
        ArtifactStore.open(root, trusted_root=tmp_path)
    assert not root.exists()


def test_empty_evidence_view_and_projection_preserve_bound_identity(
    tmp_path: Path,
) -> None:
    first = event_store(tmp_path / "first-empty")
    other = IDENTITY.model_copy(update={"episode_attempt_id": "attempt-2"})
    second_artifacts = ArtifactStore.open(
        tmp_path / "second-empty" / "evidence",
        identity=other,
        trusted_root=tmp_path,
    )
    second = EventStore.open(
        tmp_path / "second-empty" / "events.jsonl",
        artifacts=second_artifacts,
        clock=fixed_clock,
        identity=other,
    )

    first_view = first.snapshot()
    second_view = second.snapshot()
    first_public = first.project(first_view, "public")
    second_public = second.project(second_view, "public")

    assert first_view.identity == IDENTITY
    assert second_view.identity == other
    assert first_public.identity == IDENTITY
    assert second_public.identity == other
    assert first_public.event_root_sha256 != second_public.event_root_sha256


def test_artifact_open_fails_closed_if_managed_ancestor_is_swapped_after_walk(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "managed-evidence"
    external = tmp_path / "external-artifact-target"
    (external / "artifacts" / "sha256").mkdir(parents=True)
    displaced = tmp_path / "displaced-evidence"
    real_open = os.open
    swapped = False

    def swap_before_first_managed_file(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and Path(path).name == "generation.lock":
            root.rename(displaced)
            root.symlink_to(external, target_is_directory=True)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(
        "aeread.runner.event_store.os.open", swap_before_first_managed_file
    )

    with pytest.raises(ArtifactIntegrityError):
        ArtifactStore.open(root, identity=IDENTITY, trusted_root=tmp_path)
    assert swapped
    assert tuple((external / "artifacts").iterdir()) == (
        external / "artifacts" / "sha256",
    )


def test_event_open_fails_closed_if_managed_ancestor_is_swapped_after_walk(
    tmp_path: Path, monkeypatch
) -> None:
    parent = tmp_path / "managed-events"
    parent.mkdir()
    external = tmp_path / "external-event-target"
    external.mkdir()
    displaced = tmp_path / "displaced-events"
    real_open = os.open
    swapped = False

    def swap_before_event_creation(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and Path(path).name == "events.jsonl":
            parent.rename(displaced)
            parent.symlink_to(external, target_is_directory=True)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("aeread.runner.event_store.os.open", swap_before_event_creation)
    artifacts = ArtifactStore.open(
        tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
    )

    with pytest.raises(EventIntegrityError):
        EventStore.open(
            parent / "events.jsonl",
            artifacts=artifacts,
            clock=fixed_clock,
            identity=IDENTITY,
        )
    assert swapped
    assert tuple(external.iterdir()) == ()


def test_one_artifact_generation_rejects_a_second_event_log(tmp_path: Path) -> None:
    artifacts = artifact_store(tmp_path)
    first = EventStore.open(
        tmp_path / "first.jsonl",
        artifacts=artifacts,
        clock=fixed_clock,
        identity=IDENTITY,
    )
    try:
        with pytest.raises(ConcurrentWriterError):
            EventStore.open(
                tmp_path / "second.jsonl",
                artifacts=ArtifactStore.open(
                    tmp_path / "evidence",
                    identity=IDENTITY,
                    trusted_root=tmp_path,
                ),
                clock=fixed_clock,
                identity=IDENTITY,
            )
        assert not (tmp_path / "second.jsonl").exists()
    finally:
        first.close()


def test_concurrent_distinct_event_logs_have_exactly_one_generation_owner(
    tmp_path: Path,
) -> None:
    first_artifacts = artifact_store(tmp_path)
    second_artifacts = ArtifactStore.open(
        tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
    )
    barrier = threading.Barrier(2)
    outcomes: list[object] = []
    outcome_lock = threading.Lock()

    def compete(path: Path, artifacts: ArtifactStore) -> None:
        barrier.wait(timeout=2)
        try:
            outcome: object = EventStore.open(
                path,
                artifacts=artifacts,
                clock=fixed_clock,
                identity=IDENTITY,
            )
        except Exception as exc:
            outcome = exc
        with outcome_lock:
            outcomes.append(outcome)

    threads = (
        threading.Thread(
            target=compete, args=(tmp_path / "first.jsonl", first_artifacts)
        ),
        threading.Thread(
            target=compete, args=(tmp_path / "second.jsonl", second_artifacts)
        ),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    winners = [outcome for outcome in outcomes if isinstance(outcome, EventStore)]
    losers = [
        outcome for outcome in outcomes if isinstance(outcome, ConcurrentWriterError)
    ]
    assert len(winners) == 1
    assert len(losers) == 1
    assert (
        sum(
            path.exists()
            for path in (tmp_path / "first.jsonl", tmp_path / "second.jsonl")
        )
        == 1
    )
    winners[0].close()


def test_generation_writer_lease_rejects_a_concurrent_same_id_log_clone(
    tmp_path: Path,
) -> None:
    first = event_store(tmp_path)
    clone = tmp_path / "clone.jsonl"
    shutil.copy2(tmp_path / "events.jsonl", clone)
    shutil.copy2(
        tmp_path / "events.jsonl.state.json",
        tmp_path / "clone.jsonl.state.json",
    )

    try:
        with pytest.raises(ConcurrentWriterError):
            EventStore.open(
                clone,
                artifacts=ArtifactStore.open(
                    tmp_path / "evidence",
                    identity=IDENTITY,
                    trusted_root=tmp_path,
                ),
                clock=fixed_clock,
                identity=IDENTITY,
            )
    finally:
        first.close()


def test_append_rejects_an_artifact_generation_frozen_behind_the_writer(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    with store.artifacts._guard():
        store.artifacts._freeze_unlocked()

    with pytest.raises(EvidenceSealedError):
        store.append("must-not-write", IDENTITY, "public", {})
    assert (tmp_path / "events.jsonl").read_bytes() == b""


def test_explicit_trusted_root_resolves_only_its_platform_alias(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical-root"
    canonical.mkdir()
    alias = tmp_path / "trusted-alias"
    alias.symlink_to(canonical, target_is_directory=True)

    store = ArtifactStore.open(
        alias / "evidence", identity=IDENTITY, trusted_root=alias
    )
    assert store.put(b"through alias", "text/plain") in store.list_refs()

    external = tmp_path / "untrusted-target"
    external.mkdir()
    (alias / "descendant-link").symlink_to(external, target_is_directory=True)
    with pytest.raises(ArtifactIntegrityError):
        ArtifactStore.open(
            alias / "descendant-link" / "evidence",
            identity=IDENTITY,
            trusted_root=alias,
        )
    assert tuple(external.iterdir()) == ()


def test_trusted_root_is_required_existing_and_has_no_failure_side_effect(
    tmp_path: Path,
) -> None:
    omitted = tmp_path / "omitted-trusted-root"
    with pytest.raises(InvalidEvidenceInput):
        ArtifactStore.open(omitted, identity=IDENTITY)
    assert not omitted.exists()

    missing = tmp_path / "missing-trusted-root"
    with pytest.raises(InvalidEvidenceInput):
        ArtifactStore.open(
            missing / "evidence", identity=IDENTITY, trusted_root=missing
        )
    assert not missing.exists()


def test_evidence_store_id_and_root_survive_closed_same_generation_relocation(
    tmp_path: Path,
) -> None:
    artifacts = ArtifactStore.open(
        tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
    )
    first = EventStore.open(
        tmp_path / "events.jsonl",
        artifacts=artifacts,
        clock=fixed_clock,
        identity=IDENTITY,
    )
    first_view = first.snapshot()
    first.close()
    relocated_path = tmp_path / "relocated-events.jsonl"
    (tmp_path / "events.jsonl").rename(relocated_path)
    (tmp_path / "events.jsonl.state.json").rename(
        tmp_path / "relocated-events.jsonl.state.json"
    )

    reopened = EventStore.open(
        relocated_path,
        artifacts=ArtifactStore.open(
            tmp_path / "evidence", identity=IDENTITY, trusted_root=tmp_path
        ),
        clock=fixed_clock,
        identity=IDENTITY,
    )
    reopened_view = reopened.snapshot()

    assert len(first_view.evidence_store_id) == 32
    assert reopened_view.evidence_store_id == first_view.evidence_store_id
    assert reopened_view.event_root_sha256 == first_view.event_root_sha256
    assert reopened.project(reopened_view, "public").evidence_store_id == (
        first_view.evidence_store_id
    )


def test_store_close_is_idempotent_and_releases_owned_directory_capabilities(
    tmp_path: Path,
) -> None:
    artifacts = artifact_store(tmp_path)
    store = EventStore.open(
        tmp_path / "events.jsonl",
        artifacts=artifacts,
        clock=fixed_clock,
        identity=IDENTITY,
    )
    event_fds = (
        store._directory.fd,
        store._fd,
        store._owner_lease_fd,
    )
    artifact_fds = (
        artifacts._trusted._fd,
        artifacts._root_anchor.fd,
        artifacts._artifact_anchor.fd,
        artifacts._object_anchor.fd,
    )

    store.close()
    store.close()
    artifacts.close()
    artifacts.close()

    for fd in (*event_fds, *artifact_fds):
        assert fd is not None
        with pytest.raises(OSError):
            os.fstat(fd)
    with pytest.raises(EvidenceStoreError):
        artifacts.list_refs()
