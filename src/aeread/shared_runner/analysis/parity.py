"""Field-level analysis for external and legacy case parity."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from ..run.resolver import canonical_json_bytes
from ..schemas import is_exportable_id


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


_MISSING = object()


def _lookup(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    """Follow *path* into *value*, returning ``_MISSING`` instead of raising.

    A missing field is a parity finding for that one field, never grounds to
    destroy every other field's verdict."""
    current: Any = value
    for component in path:
        if not isinstance(current, Mapping) or component not in current:
            return _MISSING
        current = current[component]
    return current


@dataclass(frozen=True, slots=True)
class ExternalParityCriterion:
    """The original external claim that an adapted environment must reproduce."""

    task_id: str
    treatment_id: str
    metric_id: str
    source_reference: str
    original_conclusion: str
    tolerance_kind: str
    tolerance: float

    def __post_init__(self) -> None:
        for label, value in (
            ("task_id", self.task_id),
            ("treatment_id", self.treatment_id),
            ("metric_id", self.metric_id),
        ):
            if not is_exportable_id(value):
                raise ParityContractError(
                    f"{label} must be an exportable identifier"
                )
        if (
            not isinstance(self.source_reference, str)
            or not self.source_reference.strip()
        ):
            raise ParityContractError(
                "source_reference must be a non-empty string"
            )
        if (
            not isinstance(self.original_conclusion, str)
            or not self.original_conclusion.strip()
        ):
            raise ParityContractError(
                "original_conclusion must be a non-empty string"
            )
        if self.tolerance_kind not in {"absolute", "exact"}:
            raise ParityContractError(
                "tolerance_kind must be absolute or exact"
            )
        if (
            isinstance(self.tolerance, bool)
            or not isinstance(self.tolerance, (int, float))
            or not math.isfinite(float(self.tolerance))
            or self.tolerance < 0
        ):
            raise ParityContractError(
                "tolerance must be a finite non-negative number"
            )
        if self.tolerance_kind == "exact" and self.tolerance != 0:
            raise ParityContractError("exact tolerance must be zero")


@dataclass(frozen=True, slots=True)
class ParityField:
    field_id: str
    upstream_path: tuple[str, ...]
    adapted_path: tuple[str, ...]
    comparison: str = "exact"
    absolute_tolerance: float = 0.0
    derived_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not is_exportable_id(self.field_id):
            raise ParityContractError("field_id must be an exportable identifier")
        _path(self.upstream_path, "upstream_path")
        _path(self.adapted_path, "adapted_path")
        if not isinstance(self.derived_from, tuple) or any(
            not is_exportable_id(source) for source in self.derived_from
        ):
            raise ParityContractError(
                "derived_from must be a tuple of exportable field identifiers"
            )
        if len(self.derived_from) != len(set(self.derived_from)):
            raise ParityContractError("derived_from entries must be unique")
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
    criterion: ExternalParityCriterion
    fields: tuple[ParityField, ...]

    def __post_init__(self) -> None:
        if not is_exportable_id(self.parity_id):
            raise ParityContractError("parity_id must be an exportable identifier")
        if not isinstance(self.parity_version, str) or _SEMVER_RE.fullmatch(self.parity_version) is None:
            raise ParityContractError("parity_version must be an exact semantic version")
        if not isinstance(self.criterion, ExternalParityCriterion):
            raise ParityContractError(
                "criterion must be an ExternalParityCriterion"
            )
        if not isinstance(self.fields, tuple) or not self.fields:
            raise ParityContractError("parity spec requires at least one field")
        if any(not isinstance(field, ParityField) for field in self.fields):
            raise ParityContractError("fields must contain only ParityField records")
        field_ids = tuple(field.field_id for field in self.fields)
        if len(field_ids) != len(set(field_ids)):
            raise ParityContractError("parity field IDs must be unique")
        declared = set(field_ids)
        for field in self.fields:
            for source in field.derived_from:
                if source == field.field_id or source not in declared:
                    raise ParityContractError(
                        f"field {field.field_id!r} derived_from must reference other "
                        f"declared fields, got {source!r}"
                    )
        graph = {field.field_id: field.derived_from for field in self.fields}
        for start, sources in graph.items():
            stack = list(sources)
            seen: set[str] = set()
            while stack:
                node = stack.pop()
                if node == start:
                    raise ParityContractError(
                        f"derived_from cycle involving field {start!r}: a cycle "
                        "leaves no independent field to confirm"
                    )
                if node in seen:
                    continue
                seen.add(node)
                stack.extend(graph[node])
        field_by_id = {field.field_id: field for field in self.fields}
        criterion_field = field_by_id.get(self.criterion.metric_id)
        if criterion_field is None:
            raise ParityContractError(
                "criterion metric_id must name one declared parity field"
            )
        expected_comparison = (
            "exact"
            if self.criterion.tolerance_kind == "exact"
            else "numeric_tolerance"
        )
        if criterion_field.comparison != expected_comparison:
            raise ParityContractError(
                "criterion tolerance_kind does not match its parity field comparison"
            )
        if criterion_field.absolute_tolerance != self.criterion.tolerance:
            raise ParityContractError(
                "criterion tolerance does not match its parity field tolerance"
            )


@dataclass(frozen=True, slots=True)
class ParityFieldResult:
    field_id: str
    matched: bool
    comparison: str
    upstream_sha256: str | None
    adapted_sha256: str | None
    absolute_error: float | None
    status: str = "compared"
    unavailable_sides: tuple[str, ...] = ()
    derived: bool = False
    derived_from: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParityReport:
    parity_id: str
    parity_version: str
    criterion: ExternalParityCriterion
    criterion_sha256: str
    criterion_matched: bool
    status: str
    field_results: tuple[ParityFieldResult, ...]
    mismatched_fields: tuple[str, ...]
    upstream_projection_sha256: str
    adapted_projection_sha256: str
    report_sha256: str
    # Trailing with a default so constructions predating the unavailable
    # verdicts (positional included) stay valid.
    unavailable_fields: tuple[str, ...] = ()


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
        source = _lookup(upstream, field.upstream_path)
        target = _lookup(adapted, field.adapted_path)
        unavailable_sides = tuple(
            side
            for side, value in (("upstream", source), ("adapted", target))
            if value is _MISSING
        )
        if unavailable_sides:
            if source is not _MISSING:
                upstream_projection[field.field_id] = source
            if target is not _MISSING:
                adapted_projection[field.field_id] = target
            results.append(
                ParityFieldResult(
                    field_id=field.field_id,
                    matched=False,
                    comparison=field.comparison,
                    upstream_sha256=None if source is _MISSING else _digest(source),
                    adapted_sha256=None if target is _MISSING else _digest(target),
                    absolute_error=None,
                    status="unavailable",
                    unavailable_sides=unavailable_sides,
                    derived=bool(field.derived_from),
                    derived_from=field.derived_from,
                )
            )
            continue
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
            if isinstance(source, int) and isinstance(target, int):
                difference = abs(source - target)
            else:
                difference = abs(float(source) - float(target))
            absolute_error = float(difference)
            if field.absolute_tolerance == 0:
                # Exactness must compare exactly: Python's cross-type numeric
                # equality is exact, while conversion through float silently
                # equates integers differing past 2**53.
                matched = source == target
            else:
                matched = difference <= field.absolute_tolerance
        results.append(
            ParityFieldResult(
                field_id=field.field_id,
                matched=matched,
                comparison=field.comparison,
                upstream_sha256=source_digest,
                adapted_sha256=target_digest,
                absolute_error=absolute_error,
                derived=bool(field.derived_from),
                derived_from=field.derived_from,
            )
        )
    mismatches = tuple(
        result.field_id
        for result in results
        if result.status == "compared" and not result.matched
    )
    unavailable = tuple(
        result.field_id for result in results if result.status == "unavailable"
    )
    if mismatches:
        status = "mismatch"
    elif unavailable:
        status = "unavailable"
    else:
        status = "match"
    criterion_result = next(
        result for result in results if result.field_id == spec.criterion.metric_id
    )
    basis = {
        "parity_id": spec.parity_id,
        "parity_version": spec.parity_version,
        "criterion": spec.criterion,
        "criterion_sha256": _digest(spec.criterion),
        "criterion_matched": criterion_result.status == "compared" and criterion_result.matched,
        "status": status,
        "field_results": tuple(results),
        "mismatched_fields": mismatches,
        "unavailable_fields": unavailable,
        "upstream_projection_sha256": _digest(upstream_projection),
        "adapted_projection_sha256": _digest(adapted_projection),
    }
    return ParityReport(
        **basis,
        report_sha256=_digest(basis),
    )


__all__ = [
    "ExternalParityCriterion",
    "ParityContractError",
    "ParityField",
    "ParityFieldResult",
    "ParityReport",
    "ParitySpec",
    "compare_projections",
]
