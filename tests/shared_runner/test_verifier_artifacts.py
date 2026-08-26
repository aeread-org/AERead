from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket

import pytest

from aeread.runner import ArtifactStore, EvidenceStoreError, EventStore
from aeread.runner.verifier_artifacts import (
    ConflictingReferenceArtifactDeclaration,
    InvalidReferenceArtifactInput,
    ReferenceArtifactUnavailable,
    ReferenceArtifactView,
    UndeclaredReferenceArtifact,
    build_reference_artifact_view,
)
from aeread.sdk.v1 import ArtifactRef, EventIdentity, canonical_json_bytes

from .fakes import (
    fake_measurement_leaf_with_artifacts,
    fake_measurement_leaves_by_family,
)


IDENTITY = EventIdentity(
    run_plan_id="artifact-view-plan",
    cell_id="artifact-view-cell",
    episode_id="artifact-view-episode",
    episode_attempt_id="artifact-view-attempt",
)


def _store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore.open(
        tmp_path / "evidence",
        identity=IDENTITY,
        trusted_root=tmp_path,
    )


def _artifact(data: bytes, media_type: str = "application/octet-stream") -> ArtifactRef:
    return ArtifactRef(
        sha256=hashlib.sha256(data).hexdigest(),
        media_type=media_type,
        size_bytes=len(data),
    )


class _GetOnlyStore:
    def __init__(
        self,
        content: dict[tuple[str, str, int], bytes] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.content = content or {}
        self.error = error
        self.calls: list[ArtifactRef] = []

    def get(self, ref: ArtifactRef) -> bytes:
        self.calls.append(ref)
        if self.error is not None:
            raise self.error
        return self.content[(ref.sha256, ref.media_type, ref.size_bytes)]


def test_build_eagerly_materializes_each_unique_declared_ref_in_canonical_order(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    refs = (
        store.put(b"second", "text/plain"),
        store.put(b"first", "application/octet-stream"),
    )
    leaf = fake_measurement_leaf_with_artifacts(refs)
    content = {
        (refs[0].sha256, refs[0].media_type, refs[0].size_bytes): b"second",
        (refs[1].sha256, refs[1].media_type, refs[1].size_bytes): b"first",
    }

    view = build_reference_artifact_view(leaf, artifacts=store)

    expected = tuple(
        sorted(refs, key=lambda ref: (ref.sha256, ref.media_type, ref.size_bytes))
    )
    assert tuple(view.read(ref) for ref in expected) == tuple(
        content[(ref.sha256, ref.media_type, ref.size_bytes)] for ref in expected
    )
    store.close()
    assert tuple(view.read(ref) for ref in expected) == tuple(
        content[(ref.sha256, ref.media_type, ref.size_bytes)] for ref in expected
    )


def test_build_deduplicates_repeated_typed_declarations_before_store_access() -> None:
    data = b"one"
    ref = _artifact(data)
    store = _GetOnlyStore({(ref.sha256, ref.media_type, ref.size_bytes): data})
    leaf = fake_measurement_leaf_with_artifacts(
        (ref,),
        domain_artifacts=(ref,),
    )

    view = build_reference_artifact_view(leaf, artifacts=store)  # type: ignore[arg-type]

    assert store.calls == [ref]
    assert view.read(ref) == data


def test_all_five_verifier_families_materialize_every_typed_artifact_position() -> None:
    content = tuple(f"artifact-{index}".encode() for index in range(4))
    refs = tuple(_artifact(data) for data in content)
    store_content = {
        (ref.sha256, ref.media_type, ref.size_bytes): data
        for ref, data in zip(refs, content)
    }
    expected_counts = {
        "canonical_reference": 2,
        "rule_constraint": 2,
        "objective_reference": 2,
        "comparative": 2,
        "rater_judge": 4,
    }

    for leaf in fake_measurement_leaves_by_family(refs):
        store = _GetOnlyStore(store_content)
        view = build_reference_artifact_view(leaf, artifacts=store)  # type: ignore[arg-type]

        assert len(store.calls) == expected_counts[leaf.verifier.verifier_family]
        assert store.calls == sorted(
            store.calls,
            key=lambda ref: (ref.sha256, ref.media_type, ref.size_bytes),
        )
        assert all(
            view.read(ref)
            == store_content[(ref.sha256, ref.media_type, ref.size_bytes)]
            for ref in store.calls
        )


def test_build_accepts_a_sealed_caller_owned_store_and_does_not_close_it(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    ref = store.put(b"sealed", "text/plain")
    events = EventStore.open(
        tmp_path / "events.jsonl",
        artifacts=store,
        identity=IDENTITY,
    )
    events.seal()

    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((ref,)),
        artifacts=store,
    )

    assert store.get(ref) == b"sealed"
    events.close()
    assert view.read(ref) == b"sealed"


def test_closed_artifact_store_is_reported_as_unavailable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ref = store.put(b"closed", "text/plain")
    store.close()

    with pytest.raises(ReferenceArtifactUnavailable) as exc_info:
        build_reference_artifact_view(
            fake_measurement_leaf_with_artifacts((ref,)), artifacts=store
        )

    assert isinstance(exc_info.value.__cause__, EvidenceStoreError)


def test_view_is_a_minimal_immutable_snapshot_without_store_or_listing_surface(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    ref = store.put(b"declared", "text/plain")
    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((ref,)), artifacts=store
    )
    public_methods = {
        name
        for name, value in vars(ReferenceArtifactView).items()
        if not name.startswith("_") and callable(value)
    }

    assert public_methods == {"read"}
    assert not hasattr(view, "__dict__")
    for name in (
        "contains",
        "refs",
        "list_refs",
        "write",
        "close",
        "store",
        "path",
        "identity",
    ):
        assert not hasattr(view, name)
    with pytest.raises(TypeError):
        ReferenceArtifactView({})  # type: ignore[call-arg]
    with pytest.raises((AttributeError, TypeError)):
        setattr(view, "extra", object())
    with pytest.raises(AttributeError):
        setattr(view, "_ReferenceArtifactView__content", {})
    with pytest.raises(AttributeError):
        delattr(view, "_ReferenceArtifactView__content")


def test_view_freezes_declared_set_and_rejects_later_store_artifacts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    declared = store.put(b"declared", "text/plain")
    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((declared,)), artifacts=store
    )
    late = store.put(b"late", "text/plain")
    store.close()

    with pytest.raises(UndeclaredReferenceArtifact):
        view.read(late)


def test_undeclared_read_does_not_touch_the_store() -> None:
    data = b"declared"
    ref = _artifact(data)
    store = _GetOnlyStore({(ref.sha256, ref.media_type, ref.size_bytes): data})
    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((ref,)),
        artifacts=store,  # type: ignore[arg-type]
    )
    call_count = len(store.calls)

    with pytest.raises(UndeclaredReferenceArtifact):
        view.read(_artifact(b"other"))

    assert len(store.calls) == call_count


def test_conflicting_metadata_for_one_digest_fails_before_store_access() -> None:
    data = b"conflict"
    source_ref = _artifact(data, "text/plain")
    domain_ref = source_ref.model_copy(
        update={"media_type": "application/octet-stream"}
    )
    store = _GetOnlyStore()
    leaf = fake_measurement_leaf_with_artifacts(
        (source_ref,), domain_artifacts=(domain_ref,)
    )

    with pytest.raises(ConflictingReferenceArtifactDeclaration):
        build_reference_artifact_view(leaf, artifacts=store)  # type: ignore[arg-type]

    assert store.calls == []


@pytest.mark.parametrize(
    "leaf_mutator",
    (
        lambda leaf: leaf.model_copy(update={"undeclared": "smuggled"}),
        lambda leaf: leaf.model_copy(
            update={
                "estimand": leaf.estimand.model_copy(
                    update={
                        "validity_domain": leaf.estimand.validity_domain.model_copy(
                            update={
                                "parameters": (
                                    leaf.estimand.validity_domain.parameters[
                                        0
                                    ].model_copy(update={"undeclared": "smuggled"}),
                                )
                            }
                        )
                    }
                )
            }
        ),
    ),
)
def test_build_deeply_revalidates_unchecked_leaf_state(leaf_mutator) -> None:
    data = b"declared"
    ref = _artifact(data)
    leaf = leaf_mutator(fake_measurement_leaf_with_artifacts((ref,)))
    store = _GetOnlyStore({(ref.sha256, ref.media_type, ref.size_bytes): data})

    with pytest.raises(InvalidReferenceArtifactInput):
        build_reference_artifact_view(leaf, artifacts=store)  # type: ignore[arg-type]

    assert store.calls == []


@pytest.mark.parametrize("invalid", ("../../secret", {"sha256": "0" * 64}))
def test_read_has_no_path_or_artifact_shaped_mapping_lookup(invalid: object) -> None:
    data = b"declared"
    ref = _artifact(data)
    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((ref,)),
        artifacts=_GetOnlyStore(
            {(ref.sha256, ref.media_type, ref.size_bytes): data}
        ),  # type: ignore[arg-type]
    )

    with pytest.raises(InvalidReferenceArtifactInput):
        view.read(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_ref",
    (
        _artifact(b"declared").model_copy(update={"media_type": " "}),
        _artifact(b"declared").model_copy(update={"unexpected": True}),
        ArtifactRef.model_construct(),
    ),
)
def test_read_revalidates_raw_ref_before_exact_lookup(bad_ref: ArtifactRef) -> None:
    data = b"declared"
    ref = _artifact(data)
    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((ref,)),
        artifacts=_GetOnlyStore(
            {(ref.sha256, ref.media_type, ref.size_bytes): data}
        ),  # type: ignore[arg-type]
    )

    with pytest.raises(InvalidReferenceArtifactInput):
        view.read(bad_ref)


def test_read_requires_the_full_declared_artifact_identity() -> None:
    data = b"declared"
    ref = _artifact(data, "text/plain")
    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((ref,)),
        artifacts=_GetOnlyStore(
            {(ref.sha256, ref.media_type, ref.size_bytes): data}
        ),  # type: ignore[arg-type]
    )

    with pytest.raises(UndeclaredReferenceArtifact):
        view.read(ref.model_copy(update={"media_type": "application/octet-stream"}))


@pytest.mark.parametrize(
    "error",
    (EvidenceStoreError("missing"), OSError("unreadable")),
)
def test_expected_store_failures_are_translated_without_leaking_cause_details(
    error: Exception,
) -> None:
    ref = _artifact(b"declared")
    store = _GetOnlyStore(error=error)

    with pytest.raises(ReferenceArtifactUnavailable) as exc_info:
        build_reference_artifact_view(
            fake_measurement_leaf_with_artifacts((ref,)),
            artifacts=store,  # type: ignore[arg-type]
        )

    assert exc_info.value.__cause__ is error
    assert "missing" not in str(exc_info.value)
    assert "unreadable" not in str(exc_info.value)


def test_unexpected_store_runtime_error_propagates_unchanged() -> None:
    ref = _artifact(b"declared")
    error = RuntimeError("unexpected store defect")

    with pytest.raises(RuntimeError, match="unexpected store defect") as exc_info:
        build_reference_artifact_view(
            fake_measurement_leaf_with_artifacts((ref,)),
            artifacts=_GetOnlyStore(error=error),  # type: ignore[arg-type]
        )

    assert exc_info.value is error


@pytest.mark.parametrize("returned", (b"wrong bytes", b"declare"))
def test_build_independently_checks_digest_and_size(returned: bytes) -> None:
    ref = _artifact(b"declared")

    with pytest.raises(ReferenceArtifactUnavailable):
        build_reference_artifact_view(
            fake_measurement_leaf_with_artifacts((ref,)),
            artifacts=_GetOnlyStore(
                {(ref.sha256, ref.media_type, ref.size_bytes): returned}
            ),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "corruption",
    ("missing", "content", "media_type", "size_bytes", "sha256"),
)
def test_real_artifact_store_absence_and_corruption_fail_closed(
    tmp_path: Path, corruption: str
) -> None:
    store = _store(tmp_path)
    ref = store.put(b"declared", "text/plain")
    object_path = store.object_dir / ref.sha256
    metadata_path = store.object_dir / f"{ref.sha256}.meta.json"
    if corruption == "missing":
        object_path.unlink()
    elif corruption == "content":
        object_path.write_bytes(b"tampered")
    else:
        metadata = json.loads(metadata_path.read_bytes())
        if corruption == "media_type":
            metadata["media_type"] = "application/octet-stream"
        elif corruption == "size_bytes":
            metadata["size_bytes"] += 1
        else:
            metadata["sha256"] = "f" * 64
        metadata_path.write_bytes(canonical_json_bytes(metadata))

    with pytest.raises(ReferenceArtifactUnavailable):
        build_reference_artifact_view(
            fake_measurement_leaf_with_artifacts((ref,)), artifacts=store
        )


def test_build_never_returns_a_partial_view_when_a_later_ref_fails() -> None:
    first_data = b"first"
    first = _artifact(first_data)
    second_data = b"second"
    second = _artifact(second_data)
    content = {
        (first.sha256, first.media_type, first.size_bytes): first_data,
        (second.sha256, second.media_type, second.size_bytes): second_data,
    }

    class PartialStore(_GetOnlyStore):
        def get(self, ref: ArtifactRef) -> bytes:
            self.calls.append(ref)
            if len(self.calls) == 2:
                raise EvidenceStoreError("missing")
            return content[(ref.sha256, ref.media_type, ref.size_bytes)]

    store = PartialStore()

    with pytest.raises(ReferenceArtifactUnavailable):
        build_reference_artifact_view(
            fake_measurement_leaf_with_artifacts((first, second)),
            artifacts=store,  # type: ignore[arg-type]
        )

    assert len(store.calls) == 2


def test_build_and_read_use_only_artifact_store_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    ref = store.put(b"declared", "text/plain")

    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("non-get store authority was used")

    with monkeypatch.context() as patcher:
        for name in ("list_refs", "put", "verify", "close"):
            patcher.setattr(store, name, explode)
        patcher.setattr(store, "seal", explode, raising=False)
        view = build_reference_artifact_view(
            fake_measurement_leaf_with_artifacts((ref,)), artifacts=store
        )
        assert view.read(ref) == b"declared"
    store.close()


def test_build_and_read_do_not_touch_network_provider_or_entry_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    ref = store.put(b"declared", "text/plain")

    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("ambient discovery or network was used")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr("importlib.metadata.entry_points", explode)
    view = build_reference_artifact_view(
        fake_measurement_leaf_with_artifacts((ref,)), artifacts=store
    )

    assert view.read(ref) == b"declared"


def test_registry_and_artifact_modules_have_no_benchmark_family_branches() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "aeread" / "runner"
    source = "\n".join(
        (source_root / name).read_text(encoding="utf-8")
        for name in ("registry.py", "verifier_artifacts.py")
    )

    for forbidden in (
        "exchange_economy",
        "Housing",
        "tau-bench",
        "STATE",
        "EconEvals",
        "terms",
        "GDPval",
    ):
        assert forbidden not in source
