"""Strict records and canonical content hashing."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import hashlib
import json
import math
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    WithJsonSchema,
)

from .errors import CanonicalizationError


T = TypeVar("T")


class _FrozenMapping(Mapping[str, T], Generic[T]):
    """A copied mapping with no mutation surface."""

    __slots__ = ("__data",)

    def __init__(self, value: Mapping[str, T]) -> None:
        self.__data = dict(value)

    def __getitem__(self, key: str) -> T:
        return self.__data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.__data)

    def __len__(self) -> int:
        return len(self.__data)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.__data!r})"

    def __deepcopy__(self, memo: dict[int, object]) -> "_FrozenMapping[T]":
        return self


class FrozenJSONDict(_FrozenMapping[object]):
    """Recursively immutable, string-keyed JSON object."""


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON floats must be finite")
        return value
    if isinstance(value, FrozenJSONDict):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return FrozenJSONDict(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError(f"unsupported JSON value type: {type(value).__name__}")


def _thaw_json(value: object) -> object:
    if isinstance(value, _FrozenMapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _validate_json_object(value: object) -> dict[str, object]:
    frozen = _freeze_json(value)
    if not isinstance(frozen, FrozenJSONDict):
        raise ValueError("expected a JSON object")
    return dict(frozen.items())


def _require_string_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError("object keys must be strings")
    return value


def _freeze_mapping(value: dict[str, T]) -> _FrozenMapping[T]:
    return _FrozenMapping(value)


def _dump_mapping(value: Mapping[str, T]) -> dict[str, T]:
    return dict(value.items())


_JSON_VALUE_SCHEMA: dict[str, object] = {
    "anyOf": [
        {"type": "null"},
        {"type": "boolean"},
        {"type": "integer"},
        {"type": "number"},
        {"type": "string"},
        {"type": "array", "items": {}},
        {"type": "object", "additionalProperties": {}},
    ]
}

JSONValue = Annotated[
    object,
    BeforeValidator(_freeze_json),
    PlainSerializer(_thaw_json, return_type=object),
    WithJsonSchema(_JSON_VALUE_SCHEMA),
]

JSONObject = Annotated[
    dict[str, JSONValue],
    BeforeValidator(_validate_json_object),
    AfterValidator(FrozenJSONDict),
    PlainSerializer(_thaw_json, return_type=dict[str, object]),
    WithJsonSchema({"type": "object", "additionalProperties": _JSON_VALUE_SCHEMA}),
]

ImmutableMapping = Annotated[
    dict[str, T],
    BeforeValidator(_require_string_mapping),
    AfterValidator(_freeze_mapping),
    PlainSerializer(_dump_mapping, return_type=dict[str, T]),
]


class StrictModel(BaseModel):
    """Immutable public record that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    spec_version: Literal["aeread.sdk_record/1"] = "aeread.sdk_record/1"


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a value with the AERead canonical JSON v1 rules."""

    try:
        normalized = (
            value.model_dump(mode="python")
            if isinstance(value, BaseModel)
            else value
        )
        normalized = _thaw_json(_freeze_json(normalized))
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(str(exc)) from exc


def content_sha256(value: object) -> str:
    """Hash canonical content under the versioned AERead domain separator."""

    return hashlib.sha256(
        b"aeread.cjson/1\0" + canonical_json_bytes(value)
    ).hexdigest()
