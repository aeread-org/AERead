"""RFC 6901 JSON Pointers, restricted to JSON *object* navigation.

Issue #122: the projection and navigation that `MeasurementDeclaration.
trajectory_outcome_paths` (ruling R9) and its replay-time consistency check
(ruling R10) both need existed only as duplicated test helpers. This is the
one production implementation both `schemas.py` validation and
`task/evaluation.py`'s R10 replay check consume.

Deliberately does not support: the root pointer (the empty string), any
empty intermediate segment, or navigating through a list at any point --
every declared `trajectory_outcome_paths` entry names a chain of JSON
*object* fields, never an array index (schemas.py enforces that as its own,
narrower business rule on top of this module's plain RFC 6901 syntax check;
this module stays a generic pointer reader).
"""
from __future__ import annotations

import re
from typing import Any, Mapping

# Codex review R1 finding 4: the only valid RFC 6901 escapes are "~0" (a
# literal "~") and "~1" (a literal "/"). This matches a "~" NOT immediately
# followed by "0" or "1" -- a dangling "~" at the end of a segment (nothing
# follows it) and an unrecognized escape such as "~2" both match, and are
# rejected.
_INVALID_ESCAPE_RE = re.compile(r"~(?![01])")


class JsonPointerError(ValueError):
    """A JSON pointer string is malformed, or navigation hit a non-object."""


def parse(pointer: str) -> tuple[str, ...]:
    """Parse an RFC 6901 pointer into its decoded (~1->'/', ~0->'~') segments.

    Requires at least one non-empty segment: the empty string (root), "/"
    alone, and any pointer with an empty segment (a leading, trailing, or
    doubled "/") are all rejected. Every "~" must be followed by exactly "0"
    or "1"; a dangling "~" or an unrecognized escape (e.g. "~2") is rejected.
    """
    if not isinstance(pointer, str) or not pointer or pointer[0] != "/":
        raise JsonPointerError(
            f"{pointer!r} is not a JSON pointer with at least one segment"
        )
    raw_segments = pointer.split("/")[1:]
    if any(segment == "" for segment in raw_segments):
        raise JsonPointerError(f"{pointer!r} contains an empty segment")
    if any(_INVALID_ESCAPE_RE.search(segment) for segment in raw_segments):
        raise JsonPointerError(
            f"{pointer!r} contains an invalid escape -- every '~' must be "
            "followed by exactly '0' or '1'"
        )
    return tuple(
        segment.replace("~1", "/").replace("~0", "~") for segment in raw_segments
    )


def get(document: Any, pointer: str) -> Any:
    """Read `pointer` out of `document`, navigating JSON objects only."""
    node = document
    for segment in parse(pointer):
        if not isinstance(node, Mapping):
            raise JsonPointerError(f"{pointer!r} does not navigate a JSON object")
        if segment not in node:
            raise JsonPointerError(f"{pointer!r} does not exist in this document")
        node = node[segment]
    return node


def drop(document: Mapping[str, Any], pointer: str) -> Mapping[str, Any]:
    """Return `document` with the field named by `pointer` removed."""
    return _drop(document, parse(pointer), pointer)


def _drop(document: Any, segments: tuple[str, ...], pointer: str) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise JsonPointerError(f"{pointer!r} does not navigate a JSON object")
    key = segments[0]
    if key not in document:
        raise JsonPointerError(f"{pointer!r} does not exist in this document")
    if len(segments) == 1:
        return {k: v for k, v in document.items() if k != key}
    return {
        k: (_drop(v, segments[1:], pointer) if k == key else v)
        for k, v in document.items()
    }
