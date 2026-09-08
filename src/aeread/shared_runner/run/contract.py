"""Family-neutral campaign-contract loading, validation, and artifact sealing.

A campaign contract is the frozen JSON document that declares one experiment:
its schema, panel, controls, seeds, and claim boundary. Every family used to
re-implement the same shape checks and the same ``artifact_sha256`` sealing.
The kernel now owns the generic core; a family passes its own validators for
everything that is genuinely family-specific (route pins, case panels, world
parameters).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .resolver import canonical_json_bytes


class ContractError(ValueError):
    """A campaign contract violates the shared or a family-declared invariant."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(value: Any) -> str:
    """Digest of the canonical JSON encoding, so key order never changes identity."""

    return sha256_bytes(canonical_json_bytes(value))


def sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``value`` with ``artifact_sha256`` recomputed over every other field."""

    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": sha256_json(core)}


def read_sealed(path: Path | str) -> dict[str, Any]:
    """Load a sealed JSON artifact and refuse it when its digest no longer matches."""

    path = Path(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, Mapping) or dict(value) != sealed(value):
        raise ValueError(f"artifact digest mismatch: {path}")
    return dict(value)


ContractValidator = Callable[[Mapping[str, Any]], None]


def load_contract(
    path: Path | str,
    *,
    schema_version: str,
    required_keys: Collection[str],
    validators: Sequence[ContractValidator] = (),
) -> dict[str, Any]:
    """Load one campaign contract and enforce its shape before family checks run.

    The kernel checks that the document is an object with exactly
    ``required_keys`` and the declared ``schema_version``. ``validators`` then
    run in order and may raise any ``ValueError``; they are where a family pins
    routes, panels, controls, and claim boundaries. The raw object is returned
    unchanged so digests computed over it stay comparable with the file.
    """

    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise ContractError("campaign contract must be a JSON object")
    if set(value) != set(required_keys):
        raise ContractError("campaign contract fields are incomplete or unexpected")
    if value.get("schema_version") != schema_version:
        raise ContractError(
            f"unsupported contract schema: {value.get('schema_version')!r}"
        )
    for validator in validators:
        validator(value)
    return value


def _prefix(label: str | None) -> str:
    return f"{label} " if label else ""


def require_seed_panel(
    seeds: Any, *, minimum: int = 1, label: str | None = None
) -> tuple[int, ...]:
    """Require a list of unique, non-negative integer seeds with at least ``minimum``."""

    if (
        not isinstance(seeds, (list, tuple))
        or len(seeds) < minimum
        or len(seeds) != len(set(seeds))
        or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in seeds
        )
    ):
        raise ContractError(
            f"{_prefix(label)}inference seeds must be at least {minimum} unique "
            "non-negative integers"
        )
    return tuple(seeds)


def require_disjoint_seeds(*stages: tuple[str, Iterable[int]]) -> None:
    """Require that no inference seed is shared between any two named stages."""

    panels = [(name, set(seeds)) for name, seeds in stages]
    for index, (name, seeds) in enumerate(panels):
        for other_name, other_seeds in panels[index + 1 :]:
            if seeds & other_seeds:
                raise ContractError(
                    f"{name} and {other_name} inference seeds must be disjoint"
                )


def require_claim_boundary(
    value: Mapping[str, Any],
    *,
    keys: Iterable[str] = ("winner_claim_allowed",),
    label: str | None = None,
) -> None:
    """Require each claim key to be literally ``false``; absent or truthy is a drift."""

    for key in keys:
        if value.get(key) is not False:
            raise ContractError(f"{_prefix(label)}{key} must be exactly false")


def require_positive_number(value: Any, *, label: str) -> int | float:
    """Require a finite positive int or float; booleans never count as numbers."""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ContractError(f"{label} must be a positive finite number")
    return value


__all__ = [
    "ContractError",
    "ContractValidator",
    "load_contract",
    "read_sealed",
    "require_claim_boundary",
    "require_disjoint_seeds",
    "require_positive_number",
    "require_seed_panel",
    "sealed",
    "sha256_bytes",
    "sha256_json",
]
