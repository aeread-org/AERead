"""Strict records and canonical content hashing."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict

from .errors import CanonicalizationError


class StrictModel(BaseModel):
    """Immutable public record that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a value with the AERead canonical JSON v1 rules."""

    try:
        normalized = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )
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
