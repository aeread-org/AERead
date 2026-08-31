"""Field-level compatibility checks for external and legacy case adapters."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .resolver import canonical_json_bytes
from .schemas import is_exportable_id


_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$"
)


class ParityContractError(ValueError):
    """A parity specification or projection is incomplete or ambiguous."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _path(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ParityContractError(f"{label} must be a non-empty tuple path")
    if any(not isinstance(component, str) or not component for component in value):
        raise ParityContractError(f"{label} components must be non-empty strings")
    return value


def _extract(value: Mapping[str, Any], path: tuple[str, ...], label: str) -> Any:
    current: Any = value
    for component in path:
        if not isinstance(current, Mapping) or component not in current:
            dotted = ".".join(path)
            raise ParityContractError(f"{label} projection is missing {dotted!r}")
        current = current[component]
    return current


@dataclass(frozen=True, slots=True)
class ParityField:
    field_id: str
    upstream_path: tuple[str, ...]
    adapted_path: tuple[str, ...]
    comparison: str = "exact"
    absolute_tolerance: float = 0.0

    def __post_init__(self) -> None:
        if not is_exportable_id(self.field_id):
            raise ParityContractError("field_id must be an exportable identifier")
        _path(self.upstream_path, "upstream_path")
        _path(self.adapted_path, "adapted_path")
        if self.comparison not in {"exact", "numeric_tolerance"}:
            raise ParityContractError("comparison must be exact or numeric_tolerance")
        if (
            isinstance(self.absolute_tolerance, bool)
            or not isinstance(self.absolute_tolerance, (int, float))
            or not math.isfinite(float(self.absolute_tolerance))
            or self.absolute_tolerance < 0
        ):
            raise ParityContractError("absolute_tolerance must be a finite non-negative number")
        if self.comparison == "exact" and self.absolute_tolerance != 0:
            raise ParityContractError("exact comparison cannot declare a tolerance")


@dataclass(frozen=True, slots=True)
class ParitySpec:
    parity_id: str
    parity_version: str
    fields: tuple[ParityField, ...]

    def __post_init__(self) -> None:
        if not is_exportable_id(self.parity_id):
            raise ParityContractError("parity_id must be an exportable identifier")
        if not isinstance(self.parity_version, str) or _SEMVER_RE.fullmatch(self.parity_version) is None:
            raise ParityContractError("parity_version must be an exact semantic version")
        if not isinstance(self.fields, tuple) or not self.fields:
            raise ParityContractError("parity spec requires at least one field")
        if any(not isinstance(field, ParityField) for field in self.fields):
            raise ParityContractError("fields must contain only ParityField records")
        field_ids = tuple(field.field_id for field in self.fields)
        if len(field_ids) != len(set(field_ids)):
            raise ParityContractError("parity field IDs must be unique")


@dataclass(frozen=True, slots=True)
class ParityFieldResult:
    field_id: str
    matched: bool
    comparison: str
    upstream_sha256: str
    adapted_sha256: str
    absolute_error: float | None


@dataclass(frozen=True, slots=True)
class ParityReport:
    parity_id: str
    parity_version: str
    status: str
    field_results: tuple[ParityFieldResult, ...]
    mismatched_fields: tuple[str, ...]
    upstream_projection_sha256: str
    adapted_projection_sha256: str
    report_sha256: str


def compare_projections(
    upstream: Mapping[str, Any],
    adapted: Mapping[str, Any],
    spec: ParitySpec,
) -> ParityReport:
    """Compare canonicalized fields and return a content-addressed report.

    Adapters normalize provider- or benchmark-specific representations before
    this boundary.  The shared runner then compares every declared component,
    preserving the distinction between deterministic exact checks and a
    predeclared numeric tolerance.
    """

    if not isinstance(upstream, Mapping) or not isinstance(adapted, Mapping):
        raise ParityContractError("parity projections must be mappings")
    if not isinstance(spec, ParitySpec):
        raise ParityContractError("spec must be a ParitySpec")
    results: list[ParityFieldResult] = []
    upstream_projection: dict[str, Any] = {}
    adapted_projection: dict[str, Any] = {}
    for field in spec.fields:
        source = _extract(upstream, field.upstream_path, "upstream")
        target = _extract(adapted, field.adapted_path, "adapted")
        upstream_projection[field.field_id] = source
        adapted_projection[field.field_id] = target
        source_digest = _digest(source)
        target_digest = _digest(target)
        absolute_error: float | None = None
        if field.comparison == "exact":
            matched = canonical_json_bytes(source) == canonical_json_bytes(target)
        else:
            if (
                isinstance(source, bool)
                or isinstance(target, bool)
                or not isinstance(source, (int, float))
                or not isinstance(target, (int, float))
                or not math.isfinite(float(source))
                or not math.isfinite(float(target))
            ):
                raise ParityContractError(
                    f"numeric_tolerance field {field.field_id!r} requires finite numbers"
                )
            absolute_error = abs(float(source) - float(target))
            matched = absolute_error <= field.absolute_tolerance
        results.append(
            ParityFieldResult(
                field_id=field.field_id,
                matched=matched,
                comparison=field.comparison,
                upstream_sha256=source_digest,
                adapted_sha256=target_digest,
                absolute_error=absolute_error,
            )
        )
    mismatches = tuple(result.field_id for result in results if not result.matched)
    basis = {
        "parity_id": spec.parity_id,
        "parity_version": spec.parity_version,
        "status": "match" if not mismatches else "mismatch",
        "field_results": tuple(results),
        "mismatched_fields": mismatches,
        "upstream_projection_sha256": _digest(upstream_projection),
        "adapted_projection_sha256": _digest(adapted_projection),
    }
    return ParityReport(
        **basis,
        report_sha256=_digest(basis),
    )


__all__ = [
    "ParityContractError",
    "ParityField",
    "ParityFieldResult",
    "ParityReport",
    "ParitySpec",
    "compare_projections",
]
