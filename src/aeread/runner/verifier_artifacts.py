"""Eager artifact snapshots for one validated measurement leaf."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import hashlib
from types import MappingProxyType

from pydantic import BaseModel, ValidationError

from aeread.runner.event_store import ArtifactStore, EvidenceStoreError
from aeread.sdk.v1 import ArtifactRef, MeasurementLeafSpec


class ReferenceArtifactError(Exception):
    """Base error for declared verifier-reference artifact materialization."""


class InvalidReferenceArtifactInput(ReferenceArtifactError):
    """The measurement leaf or requested artifact reference is malformed."""


class ConflictingReferenceArtifactDeclaration(ReferenceArtifactError):
    """One digest was declared with conflicting media type or size metadata."""


class ReferenceArtifactUnavailable(ReferenceArtifactError):
    """A declared reference artifact cannot be materialized exactly."""


class UndeclaredReferenceArtifact(ReferenceArtifactError):
    """An artifact was not declared by the measurement leaf."""


class ReferenceArtifactView:
    """A minimal immutable snapshot of one leaf's declared artifact bytes."""

    __slots__ = ("__content",)

    def __init__(
        self,
        content: Mapping[tuple[str, str, int], bytes],
        *,
        _private_token: object,
    ) -> None:
        if _private_token is not _VIEW_TOKEN:
            raise TypeError("ReferenceArtifactView must be built by its factory")
        self.__content = MappingProxyType(dict(content))

    def read(self, ref: ArtifactRef) -> bytes:
        checked = _validated_artifact_ref(ref)
        identity = _artifact_identity(checked)
        try:
            return self.__content[identity]
        except KeyError as exc:
            raise UndeclaredReferenceArtifact(
                "artifact is not declared by this measurement leaf"
            ) from exc


_VIEW_TOKEN = object()


def _deep_raw_value(value: object) -> object:
    """Materialize raw Pydantic state without trusting unchecked model copies."""

    if isinstance(value, BaseModel):
        raw = dict(vars(value))
        pydantic_extra = getattr(value, "__pydantic_extra__", None)
        if pydantic_extra:
            raw.update(pydantic_extra)
        return {key: _deep_raw_value(item) for key, item in raw.items()}
    if type(value) is tuple:
        return tuple(_deep_raw_value(item) for item in value)
    if isinstance(value, Mapping):
        return {
            _deep_raw_value(key): _deep_raw_value(item) for key, item in value.items()
        }
    return value


def _validated_leaf(value: object) -> MeasurementLeafSpec:
    if not isinstance(value, MeasurementLeafSpec):
        raise InvalidReferenceArtifactInput(
            "artifact view requires a MeasurementLeafSpec"
        )
    try:
        raw = _deep_raw_value(value)
        return MeasurementLeafSpec.model_validate(raw)
    except (TypeError, ValueError, ValidationError) as exc:
        raise InvalidReferenceArtifactInput(
            "measurement leaf contains malformed unchecked state"
        ) from exc
    except Exception as exc:
        raise InvalidReferenceArtifactInput(
            "measurement leaf state could not be inspected"
        ) from exc


def _validated_artifact_ref(value: object) -> ArtifactRef:
    if not isinstance(value, ArtifactRef):
        raise InvalidReferenceArtifactInput("artifact reference must be an ArtifactRef")
    try:
        raw = _deep_raw_value(value)
        checked = ArtifactRef.model_validate(raw)
    except (TypeError, ValueError, ValidationError) as exc:
        raise InvalidReferenceArtifactInput(
            "artifact reference contains malformed unchecked state"
        ) from exc
    except Exception as exc:
        raise InvalidReferenceArtifactInput(
            "artifact reference state could not be inspected"
        ) from exc
    if not checked.media_type.strip():
        raise InvalidReferenceArtifactInput(
            "artifact reference media type must be non-empty"
        )
    return checked


def _collect_declared_refs(value: object, output: list[ArtifactRef]) -> None:
    if isinstance(value, ArtifactRef):
        output.append(value)
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            _collect_declared_refs(getattr(value, field_name), output)
        return
    if type(value) is tuple:
        for item in value:
            _collect_declared_refs(item, output)
        return
    if isinstance(value, Mapping) and not isinstance(value, MutableMapping):
        for item in value.values():
            _collect_declared_refs(item, output)


def _artifact_identity(ref: ArtifactRef) -> tuple[str, str, int]:
    return ref.sha256, ref.media_type, ref.size_bytes


def _declared_artifact_refs(leaf: MeasurementLeafSpec) -> tuple[ArtifactRef, ...]:
    collected: list[ArtifactRef] = []
    _collect_declared_refs(leaf, collected)
    identity_by_digest: dict[str, tuple[str, str, int]] = {}
    by_identity: dict[tuple[str, str, int], ArtifactRef] = {}
    for ref in collected:
        identity = _artifact_identity(ref)
        previous = identity_by_digest.get(ref.sha256)
        if previous is not None and previous != identity:
            raise ConflictingReferenceArtifactDeclaration(
                "one artifact digest has conflicting declared metadata"
            )
        identity_by_digest[ref.sha256] = identity
        by_identity[identity] = ref
    return tuple(by_identity[key] for key in sorted(by_identity))


def build_reference_artifact_view(
    leaf: MeasurementLeafSpec,
    *,
    artifacts: ArtifactStore,
) -> ReferenceArtifactView:
    checked_leaf = _validated_leaf(leaf)
    refs = _declared_artifact_refs(checked_leaf)
    loaded: dict[tuple[str, str, int], bytes] = {}
    for ref in refs:
        try:
            data = artifacts.get(ref)
        except (EvidenceStoreError, OSError) as exc:
            raise ReferenceArtifactUnavailable(
                "declared reference artifact is unavailable"
            ) from exc
        if (
            type(data) is not bytes
            or len(data) != ref.size_bytes
            or hashlib.sha256(data).hexdigest() != ref.sha256
        ):
            raise ReferenceArtifactUnavailable(
                "declared reference artifact content does not match its pin"
            )
        loaded[_artifact_identity(ref)] = data
    return ReferenceArtifactView(loaded, _private_token=_VIEW_TOKEN)


__all__ = [
    "ConflictingReferenceArtifactDeclaration",
    "InvalidReferenceArtifactInput",
    "ReferenceArtifactError",
    "ReferenceArtifactUnavailable",
    "ReferenceArtifactView",
    "UndeclaredReferenceArtifact",
    "build_reference_artifact_view",
]
