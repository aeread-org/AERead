"""Strict ``0.1`` authoring records for the AERead shared runner.

These records represent authored intent only.  They deliberately do not resolve
defaults, schedule phases, call plugins, or perform external work.  R2 turns
validated authoring records into an immutable ``RunPlan``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Mapping


class AuthoringValidationError(ValueError):
    """An authored runner record violates its strict versioned contract."""


_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]*[a-z0-9])?$")
_FOREIGN_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Ruling R9 (kernel_scoring_contract_spec.md, round 3): a JSON pointer (RFC
# 6901) naming one outcome field. Requires at least one non-empty segment --
# "" (the whole document), "/", and a trailing "//" are all rejected -- so
# ``trajectory_outcome_paths`` always names a specific field, never the root.
# kernel_r9r10_review.md finding 4: every segment must additionally name an
# OBJECT field. An RFC 6901 array-index segment (all ASCII digits, e.g.
# "/history/0") satisfies this regex but can never complete the
# scoring-contract protocol test's projection: that projection navigates
# JSON objects only, and raises on a list. ``_json_pointer_tuple`` below
# rejects any segment that is all ASCII digits, and rejects one declared
# path being a strict prefix of another declared path (e.g. "/history"
# together with "/history/x") as redundant overlap.
_JSON_POINTER_RE = re.compile(r"^(?:/[^/]+)+$")
_ARRAY_INDEX_SEGMENT_RE = re.compile(r"^[0-9]+$")


def _as_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthoringValidationError(f"{path} must be an object")
    bad_keys = [key for key in value if not isinstance(key, str)]
    if bad_keys:
        raise AuthoringValidationError(f"{path} keys must be strings: {bad_keys!r}")
    return value


def _fields(
    value: Any,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    path: str,
) -> Mapping[str, Any]:
    data = _as_mapping(value, path)
    missing = sorted(required - set(data))
    if missing:
        raise AuthoringValidationError(f"{path} is missing required fields: {missing}")
    unexpected = sorted(set(data) - required - optional)
    if unexpected:
        raise AuthoringValidationError(f"{path} has unexpected fields: {unexpected}")
    return data


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthoringValidationError(f"{path} must be a non-empty string")
    return value


def is_exportable_id(value: object) -> bool:
    """Return whether *value* is safe in row keys, paths, URLs, and rLLM IDs.

    Exported identifiers are lower-case, start and end with an alphanumeric
    character, and may contain only ``_``, ``-``, and ``.`` internally.  A
    colon is deliberately excluded because rLLM uses it as the separator
    between a task ID and rollout index.
    """

    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def _identifier(value: Any, path: str) -> str:
    result = _string(value, path)
    if not is_exportable_id(result):
        raise AuthoringValidationError(f"{path} is not a valid identifier: {result!r}")
    return result


def _semver(value: Any, path: str) -> str:
    result = _string(value, path)
    if not _SEMVER_RE.fullmatch(result):
        raise AuthoringValidationError(f"{path} must be semantic version x.y.z")
    return result


def _sha256(value: Any, path: str) -> str:
    result = _string(value, path)
    if not _SHA256_RE.fullmatch(result):
        raise AuthoringValidationError(f"{path} must be 64 lowercase hexadecimal characters")
    return result


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise AuthoringValidationError(f"{path} must be a boolean")
    return value


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise AuthoringValidationError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise AuthoringValidationError(f"{path} must be at least {minimum}")
    return value


def _number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuthoringValidationError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise AuthoringValidationError(f"{path} must be a finite number")
    if minimum is not None and result < minimum:
        raise AuthoringValidationError(f"{path} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise AuthoringValidationError(f"{path} must be at most {maximum}")
    return result


def _optional_string(value: Any, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _optional_identifier(value: Any, path: str) -> str | None:
    return None if value is None else _identifier(value, path)


def _foreign_identifier(value: Any, path: str) -> str:
    """Validate an identifier minted by an external benchmark, kept verbatim.

    Deliberately weaker than :func:`_identifier`: this field records an
    upstream id exactly as upstream wrote it, so case and underscores must
    survive — lowercasing it would destroy the traceability the field exists
    for. What it rules out is the row-id hazard class: a colon once collapsed
    rLLM's GRPO grouping into a single group, and whitespace, separators, and
    quoting characters break the same downstream parsing.
    """
    text = _string(value, path)
    if _FOREIGN_ID_RE.fullmatch(text) is None:
        raise AuthoringValidationError(
            f"{path} is not a portable upstream identifier: {text!r} "
            "(allowed: letters, digits, '_', '.', '-'; no colons or whitespace)"
        )
    return text


def _optional_foreign_identifier(value: Any, path: str) -> str | None:
    return None if value is None else _foreign_identifier(value, path)


def _json_pointer(value: Any, path: str) -> str:
    result = _string(value, path)
    if not _JSON_POINTER_RE.fullmatch(result):
        raise AuthoringValidationError(
            f"{path} must be a JSON pointer with at least one non-empty segment "
            f"(e.g. '/history'): got {result!r}"
        )
    return result


def _json_pointer_tuple(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise AuthoringValidationError(f"{path} must be an array")
    result = tuple(
        _json_pointer(item, f"{path}[{index}]") for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise AuthoringValidationError(f"{path} contains duplicate values")
    # kernel_r9r10_review.md finding 4: every segment must name an object
    # field, never an RFC 6901 array-index segment -- the scoring-contract
    # protocol test's projection helper can only navigate JSON objects, so a
    # pointer this far accepted by ``_JSON_POINTER_RE`` alone could still
    # never complete the protocol.
    for index, pointer in enumerate(result):
        segments = pointer.split("/")[1:]
        index_segments = [
            segment for segment in segments if _ARRAY_INDEX_SEGMENT_RE.fullmatch(segment)
        ]
        if index_segments:
            raise AuthoringValidationError(
                f"{path}[{index}] must name an object field, not an array index "
                f"(RFC 6901 index segment(s) {index_segments!r}): got {pointer!r}"
            )
    # A declared path that is a strict prefix of another declared path is
    # redundant overlap -- projecting the shorter path away already drops
    # everything the longer path would have named.
    for left in result:
        for right in result:
            if left != right and right.startswith(f"{left}/"):
                raise AuthoringValidationError(
                    f"{path} contains overlapping pointers: {left!r} is a prefix "
                    f"of {right!r}"
                )
    return result


def _optional_integer(
    value: Any, path: str, *, minimum: int | None = None
) -> int | None:
    return None if value is None else _integer(value, path, minimum=minimum)


def _string_tuple(
    value: Any,
    path: str,
    *,
    allow_empty: bool = False,
    identifiers: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise AuthoringValidationError(f"{path} must be an array")
    if not allow_empty and not value:
        raise AuthoringValidationError(f"{path} must not be empty")
    parser = _identifier if identifiers else _string
    result = tuple(parser(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise AuthoringValidationError(f"{path} contains duplicate values")
    return result


def _enum(value: Any, path: str, allowed: set[str]) -> str:
    result = _string(value, path)
    if result not in allowed:
        raise AuthoringValidationError(
            f"{path} must be one of {sorted(allowed)}, got {result!r}"
        )
    return result


def _freeze_json(value: Any, path: str = "payload") -> Any:
    """Validate and recursively freeze JSON-compatible family extension data."""
    if isinstance(value, Mapping):
        bad_keys = [key for key in value if not isinstance(key, str)]
        if bad_keys:
            raise AuthoringValidationError(f"{path} keys must be strings")
        return MappingProxyType(
            {key: _freeze_json(item, f"{path}.{key}") for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{path}[{index}]") for index, item in enumerate(value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise AuthoringValidationError(f"{path} must contain only finite JSON values")


def _string_mapping(value: Any, path: str) -> Mapping[str, str]:
    data = _as_mapping(value, path)
    return MappingProxyType(
        {
            _identifier(key, f"{path} key"): _identifier(item, f"{path}.{key}")
            for key, item in data.items()
        }
    )


@dataclass(frozen=True, slots=True)
class FamilyIdentity:
    id: str
    version: str
    plugin_id: str

    @classmethod
    def from_dict(cls, value: Any, path: str = "family") -> "FamilyIdentity":
        data = _fields(value, required={"id", "version", "plugin_id"}, path=path)
        return cls(
            id=_identifier(data["id"], f"{path}.id"),
            version=_semver(data["version"], f"{path}.version"),
            plugin_id=_identifier(data["plugin_id"], f"{path}.plugin_id"),
        )


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    topology: str
    phase_specs: tuple[str, ...]
    needs_tools: bool
    needs_sandbox: bool

    @classmethod
    def from_dict(cls, value: Any, path: str = "environment") -> "EnvironmentSpec":
        data = _fields(
            value,
            required={"topology", "phase_specs", "needs_tools", "needs_sandbox"},
            path=path,
        )
        return cls(
            topology=_identifier(data["topology"], f"{path}.topology"),
            phase_specs=_string_tuple(data["phase_specs"], f"{path}.phase_specs"),
            needs_tools=_boolean(data["needs_tools"], f"{path}.needs_tools"),
            needs_sandbox=_boolean(data["needs_sandbox"], f"{path}.needs_sandbox"),
        )


@dataclass(frozen=True, slots=True)
class RoleSpec:
    testable: bool
    scripted_policies: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "RoleSpec":
        data = _fields(
            value,
            required={"testable"},
            optional={"scripted_policies"},
            path=path,
        )
        return cls(
            testable=_boolean(data["testable"], f"{path}.testable"),
            scripted_policies=_string_tuple(
                data.get("scripted_policies", ()),
                f"{path}.scripted_policies",
                allow_empty=True,
            ),
        )


_LEAF_SCOPES = {"finalize_time", "deferred"}
# Ruling R12 (kernel_scoring_contract_spec.md): "cell" (the default) is an
# ordinary, family-wide scalar; "subject_seat" declares that the leaf's
# primary is a reduction over the plan's tested subject seats -- see
# ``subject_reduction`` below and ``task/evaluation.py``'s
# ``_enforce_subject_seat_primaries``.
_SEAT_SCOPES = {"cell", "subject_seat"}


@dataclass(frozen=True, slots=True)
class LeafPolicyDeclaration:
    """One declared measurement leaf's identity and finalize-time scope.

    A ``deferred`` leaf requires an artifact that may not exist yet at
    finalization (a judge verdict, an external rater protocol); it is
    declared here but excluded from the finalize-time returned set rather
    than mislabelled ``invalid_measurement``. A leaf may not be marked
    ``deferred`` merely because computing it is inconvenient --
    ``deferred_artifact`` must name what it waits on.

    Ruling R12: ``seat_scope`` and ``subject_reduction`` are added after
    leaf policy was already sealed into published digests, so both are
    ``_CANONICAL_OMIT_IF_DEFAULT`` on this class -- a leaf that does not use
    them (the ``seat_scope="cell"`` default) hashes exactly as it did before
    this change. ``subject_reduction`` is a family-interpreted identifier
    (e.g. ``"mean"``) naming how the family reduces several subject seats'
    values into one primary; the kernel never interprets it, only requires
    it was declared before a ``subject_seat`` leaf may score a scalar over
    more than one subject seat (task/evaluation.py's
    ``_enforce_subject_seat_primaries``).

    Ruling R13: ``case_conditional`` (default ``False``, also
    ``_CANONICAL_OMIT_IF_DEFAULT`` for the same reason) declares that this
    leaf applies to only some of the family's own cases (agenticpay's
    ``contract_legality``, present for its contract-mode cases and absent
    for its basic ones). Applicability is decided by the plugin's
    ``inapplicable_leaf_ids(family_case)`` hook at finalize/replay/audit
    time (task/evaluation.py), never by data in the manifest itself. A
    ``case_conditional`` leaf may not be ``primary_leaf_id`` and may not be
    in ``admission_leaf_ids`` -- both must exist for every execution
    admitted under one static manifest, which a case-conditional leaf by
    definition does not (``MeasurementDeclaration.__post_init__``/
    ``from_dict`` enforce this, since it is a cross-field invariant against
    fields this class does not itself carry).
    """

    _CANONICAL_OMIT_IF_DEFAULT: ClassVar[frozenset[str]] = frozenset(
        {"seat_scope", "subject_reduction", "case_conditional"}
    )

    leaf_id: str
    scope: str
    deferred_artifact: str | None
    seat_scope: str = "cell"
    subject_reduction: str | None = None
    case_conditional: bool = False

    def __post_init__(self) -> None:
        # kernel_contract_impl_review.md finding 4: these invariants were
        # previously enforced only in ``from_dict``, so a
        # ``dataclasses.replace`` on an already-validated declaration could
        # smuggle an inconsistent leaf policy past parsing entirely. A
        # ``__post_init__`` runs on every construction path, including
        # ``dataclasses.replace``, so there is no bypass.
        if not is_exportable_id(self.leaf_id):
            raise AuthoringValidationError(
                f"leaf policy leaf_id is not a valid identifier: {self.leaf_id!r}"
            )
        if self.scope not in _LEAF_SCOPES:
            raise AuthoringValidationError(
                f"leaf policy scope must be one of {sorted(_LEAF_SCOPES)}, "
                f"got {self.scope!r}"
            )
        if self.scope == "deferred" and self.deferred_artifact is None:
            raise AuthoringValidationError(
                "a deferred leaf requires deferred_artifact"
            )
        if self.scope != "deferred" and self.deferred_artifact is not None:
            raise AuthoringValidationError(
                "deferred_artifact is only valid for a deferred leaf"
            )
        # Ruling R12: same "every construction path" reasoning as the
        # ``scope``/``deferred_artifact`` pair above -- a ``dataclasses.replace``
        # must not be able to smuggle a ``subject_reduction`` onto a
        # ``cell``-scoped leaf either.
        if self.seat_scope not in _SEAT_SCOPES:
            raise AuthoringValidationError(
                f"leaf policy seat_scope must be one of {sorted(_SEAT_SCOPES)}, "
                f"got {self.seat_scope!r}"
            )
        if self.seat_scope != "subject_seat" and self.subject_reduction is not None:
            raise AuthoringValidationError(
                "subject_reduction is only valid for a subject_seat leaf"
            )

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "LeafPolicyDeclaration":
        data = _fields(
            value,
            required={"leaf_id", "scope"},
            optional={
                "deferred_artifact",
                "seat_scope",
                "subject_reduction",
                "case_conditional",
            },
            path=path,
        )
        scope = _enum(data["scope"], f"{path}.scope", _LEAF_SCOPES)
        deferred_artifact = _optional_string(
            data.get("deferred_artifact"), f"{path}.deferred_artifact"
        )
        if scope == "deferred" and deferred_artifact is None:
            raise AuthoringValidationError(
                f"{path}.deferred_artifact is required for a deferred leaf"
            )
        if scope != "deferred" and deferred_artifact is not None:
            raise AuthoringValidationError(
                f"{path}.deferred_artifact is only valid for a deferred leaf"
            )
        seat_scope = _enum(
            data.get("seat_scope", "cell"), f"{path}.seat_scope", _SEAT_SCOPES
        )
        subject_reduction = _optional_string(
            data.get("subject_reduction"), f"{path}.subject_reduction"
        )
        if seat_scope != "subject_seat" and subject_reduction is not None:
            raise AuthoringValidationError(
                f"{path}.subject_reduction is only valid for a subject_seat leaf"
            )
        case_conditional = _boolean(
            data.get("case_conditional", False), f"{path}.case_conditional"
        )
        return cls(
            leaf_id=_identifier(data["leaf_id"], f"{path}.leaf_id"),
            scope=scope,
            deferred_artifact=deferred_artifact,
            seat_scope=seat_scope,
            subject_reduction=subject_reduction,
            case_conditional=case_conditional,
        )


@dataclass(frozen=True, slots=True)
class FinalizeTimeLeafPolicy:
    """The scorer's finalize-time contract, read from the manifest (section 3).

    ``leaf_ids`` and ``admission_leaf_ids`` are in the manifest's one true
    order -- primary first, then lexical ``leaf_id`` -- so they compare
    directly against a ``FamilyScoreSet`` the family's scorer produced:
    ``FamilyScoreSet.__post_init__`` canonicalizes its own ``scores`` and
    ``admission_leaf_ids`` the same way. Ordering never encodes policy; this
    is purely so the two sides of the protocol test's equality assertions
    line up without either side re-sorting the other.
    """

    leaf_ids: tuple[str, ...]
    primary_leaf_id: str
    admission_leaf_ids: tuple[str, ...]


def _canonical_leaf_order(leaf_ids: Any, primary_leaf_id: str) -> tuple[str, ...]:
    return tuple(
        sorted(leaf_ids, key=lambda leaf_id: (leaf_id != primary_leaf_id, leaf_id))
    )


@dataclass(frozen=True, slots=True)
class MeasurementDeclaration:
    # Ruling R1 (kernel_scoring_contract_spec.md): these three fields were added
    # after Housing V8/V11 evidence was published and sealed. An unset field must
    # be ABSENT from canonical JSON, not merely null/empty, or every manifest that
    # predates leaf policy would silently reproduce a different plan_sha256 and
    # cascade into a different artifact_sha256 on already-published evidence.
    # ``_CANONICAL_OMIT_IF_DEFAULT`` tells ``run.resolver._canonical_value`` to
    # drop these keys entirely when they hold their declared default, so a
    # manifest that does not use leaf policy hashes exactly as it did before this
    # schema addition. See ``test_measurement_declaration_without_leaves_is_digest_neutral``.
    # ``trajectory_outcome_paths`` (ruling R9, round 3) is the same story one
    # ruling later: added after leaf policy itself was already sealed into
    # published digests, so it gets the identical digest-neutral treatment --
    # see ``test_measurement_declaration_without_trajectory_paths_is_digest_neutral``.
    _CANONICAL_OMIT_IF_DEFAULT: ClassVar[frozenset[str]] = frozenset(
        {"leaves", "primary_leaf_id", "admission_leaf_ids", "trajectory_outcome_paths"}
    )

    primary_estimand: str
    measurement_kind: str
    direction: str
    optimum_lower_bound: str | None
    comparison_baseline: str | None
    optimum_upper_bound: str | None
    optimum_upper_bound_kind: str | None
    bound_status: str | None
    outcome_support: str | None
    leaves: tuple[LeafPolicyDeclaration, ...] = ()
    primary_leaf_id: str | None = None
    admission_leaf_ids: tuple[str, ...] = ()
    # Ruling R9 (kernel_scoring_contract_spec.md, round 3): an exhaustive list
    # of the outcome fields (JSON pointers) that carry the family's trajectory
    # -- e.g. ``("/history",)`` for collusion. A family whose outcome embeds
    # its trajectory declares these so the scoring-contract protocol test can
    # compare a PROJECTION (outcome minus these paths) instead of the whole
    # outcome for the paired-history check (section 6/ruling R7), whose
    # byte-identical-outcome precondition is otherwise unsatisfiable by
    # construction for such a family. A family that declares none is checked
    # on the whole outcome, exactly as before this ruling.
    trajectory_outcome_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # kernel_contract_impl_review.md finding 4: ``from_dict`` validated
        # these three fields' cross-field invariants, but nothing stopped a
        # ``dataclasses.replace`` on an already-registered manifest from
        # smuggling an inconsistent leaf policy (undeclared primary, a
        # deferred admission leaf, duplicate admission ids, ...) past every
        # check and straight into ``PluginRegistry``. Running the same
        # invariants here means every construction path is guarded, not only
        # ``from_dict``'s.
        leaf_ids = tuple(leaf.leaf_id for leaf in self.leaves)
        if len(set(leaf_ids)) != len(leaf_ids):
            raise AuthoringValidationError(
                "measurement.leaves contains a duplicate leaf_id"
            )
        # Ruling R9: format/uniqueness is independent of whether a leaf policy
        # is declared at all, so it is validated here unconditionally (not
        # only inside the ``self.leaves`` branch below) -- the same reasoning
        # as this method's own docstring note: every construction path,
        # including ``dataclasses.replace``, must be guarded, not only
        # ``from_dict``'s.
        object.__setattr__(
            self,
            "trajectory_outcome_paths",
            _json_pointer_tuple(
                self.trajectory_outcome_paths, "measurement.trajectory_outcome_paths"
            ),
        )
        if not self.leaves:
            if self.primary_leaf_id is not None or self.admission_leaf_ids:
                raise AuthoringValidationError(
                    "measurement.primary_leaf_id and admission_leaf_ids require "
                    "measurement.leaves to be declared"
                )
            return
        finalize_time_ids = {
            leaf.leaf_id for leaf in self.leaves if leaf.scope == "finalize_time"
        }
        if not finalize_time_ids:
            raise AuthoringValidationError(
                "measurement.leaves must declare at least one finalize_time leaf"
            )
        if self.primary_leaf_id is None:
            raise AuthoringValidationError(
                "measurement.primary_leaf_id is required when leaves are declared"
            )
        if self.primary_leaf_id not in leaf_ids:
            raise AuthoringValidationError(
                "measurement.primary_leaf_id must name a declared leaf"
            )
        if self.primary_leaf_id not in finalize_time_ids:
            raise AuthoringValidationError(
                "measurement.primary_leaf_id must be a finalize_time leaf"
            )
        # Ruling R13: a case_conditional leaf may not be primary -- both
        # must exist for every execution admitted under one static
        # manifest, which a case-conditional leaf by definition does not.
        case_conditional_ids = {
            leaf.leaf_id for leaf in self.leaves if leaf.case_conditional
        }
        if self.primary_leaf_id in case_conditional_ids:
            raise AuthoringValidationError(
                "measurement.primary_leaf_id must not be a case_conditional leaf: "
                f"{self.primary_leaf_id!r}"
            )
        admission_leaf_ids = self.admission_leaf_ids or (self.primary_leaf_id,)
        if len(set(admission_leaf_ids)) != len(admission_leaf_ids):
            raise AuthoringValidationError(
                "measurement.admission_leaf_ids must not contain duplicates"
            )
        unknown_admission = sorted(set(admission_leaf_ids) - set(leaf_ids))
        if unknown_admission:
            raise AuthoringValidationError(
                f"measurement.admission_leaf_ids must be declared leaves: "
                f"{unknown_admission}"
            )
        deferred_ids = {leaf.leaf_id for leaf in self.leaves if leaf.scope == "deferred"}
        deferred_admission = sorted(set(admission_leaf_ids) & deferred_ids)
        if deferred_admission:
            raise AuthoringValidationError(
                f"measurement.admission_leaf_ids must not include a deferred leaf: "
                f"{deferred_admission}"
            )
        # Ruling R13: same reasoning as the deferred-admission guard above,
        # for case_conditional leaves.
        case_conditional_admission = sorted(
            set(admission_leaf_ids) & case_conditional_ids
        )
        if case_conditional_admission:
            raise AuthoringValidationError(
                "measurement.admission_leaf_ids must not include a case_conditional "
                f"leaf: {case_conditional_admission}"
            )
        if self.primary_leaf_id not in admission_leaf_ids:
            raise AuthoringValidationError(
                "measurement.primary_leaf_id must be included in admission_leaf_ids"
            )
        object.__setattr__(self, "admission_leaf_ids", admission_leaf_ids)

    @classmethod
    def from_dict(cls, value: Any, path: str = "measurement") -> "MeasurementDeclaration":
        optional = {
            "optimum_lower_bound",
            "comparison_baseline",
            "optimum_upper_bound",
            "optimum_upper_bound_kind",
            "bound_status",
            "outcome_support",
            "leaves",
            "primary_leaf_id",
            "admission_leaf_ids",
            "trajectory_outcome_paths",
        }
        data = _fields(
            value,
            required={"primary_estimand", "measurement_kind", "direction"},
            optional=optional,
            path=path,
        )
        leaves_value = data.get("leaves", ())
        if not isinstance(leaves_value, (list, tuple)):
            raise AuthoringValidationError(f"{path}.leaves must be an array")
        leaves = tuple(
            LeafPolicyDeclaration.from_dict(item, f"{path}.leaves[{index}]")
            for index, item in enumerate(leaves_value)
        )
        leaf_ids = tuple(leaf.leaf_id for leaf in leaves)
        if len(set(leaf_ids)) != len(leaf_ids):
            raise AuthoringValidationError(
                f"{path}.leaves contains a duplicate leaf_id"
            )
        primary_leaf_id = _optional_string(
            data.get("primary_leaf_id"), f"{path}.primary_leaf_id"
        )
        admission_leaf_ids = _string_tuple(
            data.get("admission_leaf_ids", ()),
            f"{path}.admission_leaf_ids",
            allow_empty=True,
        )
        if leaves:
            finalize_time_ids = {
                leaf.leaf_id for leaf in leaves if leaf.scope == "finalize_time"
            }
            if not finalize_time_ids:
                raise AuthoringValidationError(
                    f"{path}.leaves must declare at least one finalize_time leaf"
                )
            if primary_leaf_id is None:
                raise AuthoringValidationError(
                    f"{path}.primary_leaf_id is required when leaves are declared"
                )
            if primary_leaf_id not in leaf_ids:
                raise AuthoringValidationError(
                    f"{path}.primary_leaf_id must name a declared leaf"
                )
            if primary_leaf_id not in finalize_time_ids:
                raise AuthoringValidationError(
                    f"{path}.primary_leaf_id must be a finalize_time leaf"
                )
            # Ruling R13: same cross-field invariant as __post_init__'s --
            # a case_conditional leaf may not be primary.
            case_conditional_ids = {
                leaf.leaf_id for leaf in leaves if leaf.case_conditional
            }
            if primary_leaf_id in case_conditional_ids:
                raise AuthoringValidationError(
                    f"{path}.primary_leaf_id must not be a case_conditional leaf: "
                    f"{primary_leaf_id!r}"
                )
            admission_leaf_ids = admission_leaf_ids or (primary_leaf_id,)
            unknown_admission = sorted(set(admission_leaf_ids) - set(leaf_ids))
            if unknown_admission:
                raise AuthoringValidationError(
                    f"{path}.admission_leaf_ids must be declared leaves: "
                    f"{unknown_admission}"
                )
            deferred_ids = {leaf.leaf_id for leaf in leaves if leaf.scope == "deferred"}
            deferred_admission = sorted(set(admission_leaf_ids) & deferred_ids)
            if deferred_admission:
                raise AuthoringValidationError(
                    f"{path}.admission_leaf_ids must not include a deferred leaf: "
                    f"{deferred_admission}"
                )
            # Ruling R13: same reasoning as the deferred-admission guard
            # above, for case_conditional leaves.
            case_conditional_admission = sorted(
                set(admission_leaf_ids) & case_conditional_ids
            )
            if case_conditional_admission:
                raise AuthoringValidationError(
                    f"{path}.admission_leaf_ids must not include a case_conditional "
                    f"leaf: {case_conditional_admission}"
                )
            if primary_leaf_id not in admission_leaf_ids:
                raise AuthoringValidationError(
                    f"{path}.primary_leaf_id must be included in admission_leaf_ids"
                )
        elif primary_leaf_id is not None or admission_leaf_ids:
            raise AuthoringValidationError(
                f"{path}.primary_leaf_id and admission_leaf_ids require "
                f"{path}.leaves to be declared"
            )
        trajectory_outcome_paths = _json_pointer_tuple(
            data.get("trajectory_outcome_paths", ()),
            f"{path}.trajectory_outcome_paths",
        )
        return cls(
            primary_estimand=_identifier(data["primary_estimand"], f"{path}.primary_estimand"),
            measurement_kind=_enum(
                data["measurement_kind"],
                f"{path}.measurement_kind",
                {"property_or_answer", "optimizable_outcome", "comparative_or_human_judged"},
            ),
            direction=_enum(data["direction"], f"{path}.direction", {"maximize", "minimize", "none"}),
            optimum_lower_bound=_optional_string(data.get("optimum_lower_bound"), f"{path}.optimum_lower_bound"),
            comparison_baseline=_optional_string(data.get("comparison_baseline"), f"{path}.comparison_baseline"),
            optimum_upper_bound=_optional_string(data.get("optimum_upper_bound"), f"{path}.optimum_upper_bound"),
            optimum_upper_bound_kind=_optional_string(data.get("optimum_upper_bound_kind"), f"{path}.optimum_upper_bound_kind"),
            bound_status=_optional_string(data.get("bound_status"), f"{path}.bound_status"),
            outcome_support=_optional_string(data.get("outcome_support"), f"{path}.outcome_support"),
            leaves=leaves,
            primary_leaf_id=primary_leaf_id,
            admission_leaf_ids=admission_leaf_ids,
            trajectory_outcome_paths=trajectory_outcome_paths,
        )

    def finalize_time_leaf_policy(self) -> FinalizeTimeLeafPolicy:
        """The manifest's finalize-time leaf contract (section 3 of the spec).

        Raises if no leaf policy is declared: section 3 requires the
        manifest, not a scorer or a test fixture, to be the source of the
        leaf set, the primary, and admission membership, so a family with no
        declared policy must fail loudly here rather than let the protocol
        test invent one.
        """
        if not self.leaves or self.primary_leaf_id is None:
            raise AuthoringValidationError(
                "measurement.leaves and measurement.primary_leaf_id must be "
                "declared before a finalize-time leaf policy can be read"
            )
        finalize_time_ids = tuple(
            leaf.leaf_id for leaf in self.leaves if leaf.scope == "finalize_time"
        )
        return FinalizeTimeLeafPolicy(
            leaf_ids=_canonical_leaf_order(finalize_time_ids, self.primary_leaf_id),
            primary_leaf_id=self.primary_leaf_id,
            admission_leaf_ids=_canonical_leaf_order(
                self.admission_leaf_ids, self.primary_leaf_id
            ),
        )


@dataclass(frozen=True, slots=True)
class ScoringSpec:
    scorer_id: str
    oracle_id: str | None
    reference_provider_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any, path: str = "scoring") -> "ScoringSpec":
        data = _fields(
            value,
            required={"scorer_id"},
            optional={"oracle_id", "reference_provider_ids"},
            path=path,
        )
        return cls(
            scorer_id=_identifier(data["scorer_id"], f"{path}.scorer_id"),
            oracle_id=(
                None
                if data.get("oracle_id") is None
                else _identifier(data["oracle_id"], f"{path}.oracle_id")
            ),
            reference_provider_ids=_string_tuple(
                data.get("reference_provider_ids", ()),
                f"{path}.reference_provider_ids",
                allow_empty=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class GeneratorSpec:
    generator_id: str
    difficulty_knobs: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any, path: str = "generator") -> "GeneratorSpec":
        data = _fields(
            value,
            required={"generator_id"},
            optional={"difficulty_knobs"},
            path=path,
        )
        return cls(
            generator_id=_identifier(data["generator_id"], f"{path}.generator_id"),
            difficulty_knobs=_string_tuple(
                data.get("difficulty_knobs", ()),
                f"{path}.difficulty_knobs",
                allow_empty=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class FamilyManifest:
    SPEC_VERSION: ClassVar[str] = "aeread.family/0.1"

    spec_version: str
    family: FamilyIdentity
    environment: EnvironmentSpec
    roles: Mapping[str, RoleSpec]
    measurement: MeasurementDeclaration
    scoring: ScoringSpec
    generator: GeneratorSpec | None

    @classmethod
    def from_dict(cls, value: Any) -> "FamilyManifest":
        data = _fields(
            value,
            required={"spec_version", "family", "environment", "roles", "measurement", "scoring"},
            optional={"generator"},
            path="FamilyManifest",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "FamilyManifest")
        role_data = _as_mapping(data["roles"], "FamilyManifest.roles")
        if not role_data:
            raise AuthoringValidationError("FamilyManifest.roles must not be empty")
        roles = MappingProxyType(
            {
                _identifier(role_id, "FamilyManifest.roles key"): RoleSpec.from_dict(
                    role, f"FamilyManifest.roles.{role_id}"
                )
                for role_id, role in role_data.items()
            }
        )
        if not any(role.testable for role in roles.values()):
            raise AuthoringValidationError("FamilyManifest.roles needs at least one testable role")
        return cls(
            spec_version=cls.SPEC_VERSION,
            family=FamilyIdentity.from_dict(data["family"], "FamilyManifest.family"),
            environment=EnvironmentSpec.from_dict(data["environment"], "FamilyManifest.environment"),
            roles=roles,
            measurement=MeasurementDeclaration.from_dict(data["measurement"], "FamilyManifest.measurement"),
            scoring=ScoringSpec.from_dict(data["scoring"], "FamilyManifest.scoring"),
            generator=(
                None
                if data.get("generator") is None
                else GeneratorSpec.from_dict(data["generator"], "FamilyManifest.generator")
            ),
        )

    def finalize_time_leaf_policy(self) -> FinalizeTimeLeafPolicy:
        """The family's finalize-time leaf contract; see ``MeasurementDeclaration``."""
        return self.measurement.finalize_time_leaf_policy()


@dataclass(frozen=True, slots=True)
class SeatSpec:
    id: str
    role: str

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "SeatSpec":
        data = _fields(value, required={"id", "role"}, path=path)
        return cls(
            id=_identifier(data["id"], f"{path}.id"),
            role=_identifier(data["role"], f"{path}.role"),
        )


@dataclass(frozen=True, slots=True)
class EpisodeSpec:
    max_logical_actions: int
    termination: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any, path: str = "episode") -> "EpisodeSpec":
        data = _fields(value, required={"max_logical_actions", "termination"}, path=path)
        return cls(
            max_logical_actions=_integer(
                data["max_logical_actions"], f"{path}.max_logical_actions", minimum=1
            ),
            termination=_string_tuple(data["termination"], f"{path}.termination"),
        )


@dataclass(frozen=True, slots=True)
class ProvenanceSpec:
    generator_id: str
    generator_version: str
    review_status: str

    @classmethod
    def from_dict(cls, value: Any, path: str = "provenance") -> "ProvenanceSpec":
        data = _fields(
            value,
            required={"generator_id", "generator_version", "review_status"},
            path=path,
        )
        return cls(
            generator_id=_identifier(data["generator_id"], f"{path}.generator_id"),
            generator_version=_semver(data["generator_version"], f"{path}.generator_version"),
            review_status=_enum(
                data["review_status"],
                f"{path}.review_status",
                {"generated", "reviewed", "curated", "upstream_pinned"},
            ),
        )


@dataclass(frozen=True, slots=True)
class CaseManifest:
    SPEC_VERSION: ClassVar[str] = "aeread.case/0.1"

    spec_version: str
    case_id: str
    family_id: str
    family_version: str
    split: str
    world_seed: int
    seats: tuple[SeatSpec, ...]
    episode: EpisodeSpec
    visibility_policy: str
    payload: Mapping[str, Any]
    provenance: ProvenanceSpec
    content_sha256: str
    upstream_task_id: str | None

    @classmethod
    def from_dict(cls, value: Any) -> "CaseManifest":
        required = {
            "spec_version",
            "case_id",
            "family_id",
            "family_version",
            "split",
            "world_seed",
            "seats",
            "episode",
            "visibility_policy",
            "payload",
            "provenance",
            "content_sha256",
        }
        data = _fields(
            value,
            required=required,
            optional={"upstream_task_id"},
            path="CaseManifest",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "CaseManifest")
        raw_seats = data["seats"]
        if not isinstance(raw_seats, (list, tuple)) or not raw_seats:
            raise AuthoringValidationError("CaseManifest.seats must be a non-empty array")
        seats = tuple(
            SeatSpec.from_dict(seat, f"CaseManifest.seats[{index}]")
            for index, seat in enumerate(raw_seats)
        )
        seat_ids = [seat.id for seat in seats]
        if len(seat_ids) != len(set(seat_ids)):
            raise AuthoringValidationError("CaseManifest.seats contains duplicate seat ids")
        payload = _freeze_json(data["payload"], "CaseManifest.payload")
        if not isinstance(payload, Mapping):
            raise AuthoringValidationError("CaseManifest.payload must be an object")
        return cls(
            spec_version=cls.SPEC_VERSION,
            case_id=_identifier(data["case_id"], "CaseManifest.case_id"),
            family_id=_identifier(data["family_id"], "CaseManifest.family_id"),
            family_version=_semver(data["family_version"], "CaseManifest.family_version"),
            split=_identifier(data["split"], "CaseManifest.split"),
            world_seed=_integer(data["world_seed"], "CaseManifest.world_seed", minimum=0),
            seats=seats,
            episode=EpisodeSpec.from_dict(data["episode"], "CaseManifest.episode"),
            visibility_policy=_identifier(
                data["visibility_policy"], "CaseManifest.visibility_policy"
            ),
            payload=payload,
            provenance=ProvenanceSpec.from_dict(
                data["provenance"], "CaseManifest.provenance"
            ),
            content_sha256=_sha256(data["content_sha256"], "CaseManifest.content_sha256"),
            # External benchmark ids ride into rLLM row ids and GRPO group
            # keys; a colon here once collapsed grouping into one group, so
            # the exportable-identifier grammar applies (adapters normalize
            # foreign ids and keep the raw value in provenance/payload).
            upstream_task_id=_optional_foreign_identifier(
                data.get("upstream_task_id"), "CaseManifest.upstream_task_id"
            ),
        )


@dataclass(frozen=True, slots=True)
class SuiteManifest:
    SPEC_VERSION: ClassVar[str] = "aeread.suite/0.1"

    spec_version: str
    suite_id: str
    version: str
    family_ids: tuple[str, ...]
    case_ids: tuple[str, ...]
    sampling_plan_id: str
    evaluation_block_ids: tuple[str, ...]
    analysis_plan_id: str

    @classmethod
    def from_dict(cls, value: Any) -> "SuiteManifest":
        data = _fields(
            value,
            required={
                "spec_version",
                "suite_id",
                "version",
                "family_ids",
                "case_ids",
                "sampling_plan_id",
                "evaluation_block_ids",
                "analysis_plan_id",
            },
            path="SuiteManifest",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "SuiteManifest")
        return cls(
            spec_version=cls.SPEC_VERSION,
            suite_id=_identifier(data["suite_id"], "SuiteManifest.suite_id"),
            version=_semver(data["version"], "SuiteManifest.version"),
            family_ids=_string_tuple(data["family_ids"], "SuiteManifest.family_ids"),
            case_ids=_string_tuple(data["case_ids"], "SuiteManifest.case_ids"),
            sampling_plan_id=_identifier(
                data["sampling_plan_id"], "SuiteManifest.sampling_plan_id"
            ),
            evaluation_block_ids=_string_tuple(
                data["evaluation_block_ids"], "SuiteManifest.evaluation_block_ids"
            ),
            analysis_plan_id=_identifier(
                data["analysis_plan_id"], "SuiteManifest.analysis_plan_id"
            ),
        )


@dataclass(frozen=True, slots=True)
class SamplingPlan:
    SPEC_VERSION: ClassVar[str] = "aeread.sampling/0.1"

    spec_version: str
    sampling_plan_id: str
    estimand: str
    target: str
    selection: str
    seeds: tuple[int, ...]
    replicates: int
    cluster_level: str
    cluster_id_fields: tuple[str, ...]
    paired_fields: tuple[str, ...]
    replicate_level: str
    panel_mode: str

    @classmethod
    def from_dict(cls, value: Any) -> "SamplingPlan":
        data = _fields(
            value,
            required={
                "spec_version",
                "sampling_plan_id",
                "estimand",
                "target",
                "selection",
                "seeds",
                "replicates",
                "cluster_level",
                "cluster_id_fields",
                "paired_fields",
                "replicate_level",
                "panel_mode",
            },
            path="SamplingPlan",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "SamplingPlan")
        raw_seeds = data["seeds"]
        if not isinstance(raw_seeds, (list, tuple)) or not raw_seeds:
            raise AuthoringValidationError("SamplingPlan.seeds must be a non-empty array")
        seeds = tuple(
            _integer(seed, f"SamplingPlan.seeds[{index}]", minimum=0)
            for index, seed in enumerate(raw_seeds)
        )
        if len(seeds) != len(set(seeds)):
            raise AuthoringValidationError("SamplingPlan.seeds contains duplicate values")
        return cls(
            spec_version=cls.SPEC_VERSION,
            sampling_plan_id=_identifier(
                data["sampling_plan_id"], "SamplingPlan.sampling_plan_id"
            ),
            estimand=_identifier(data["estimand"], "SamplingPlan.estimand"),
            target=_identifier(data["target"], "SamplingPlan.target"),
            selection=_identifier(data["selection"], "SamplingPlan.selection"),
            seeds=seeds,
            replicates=_integer(data["replicates"], "SamplingPlan.replicates", minimum=1),
            cluster_level=_identifier(
                data["cluster_level"], "SamplingPlan.cluster_level"
            ),
            cluster_id_fields=_string_tuple(
                data["cluster_id_fields"], "SamplingPlan.cluster_id_fields"
            ),
            paired_fields=_string_tuple(
                data["paired_fields"], "SamplingPlan.paired_fields", allow_empty=True
            ),
            replicate_level=_identifier(
                data["replicate_level"], "SamplingPlan.replicate_level"
            ),
            panel_mode=_enum(
                data["panel_mode"],
                "SamplingPlan.panel_mode",
                {"sampled_panel", "fixed_panel"},
            ),
        )


@dataclass(frozen=True, slots=True)
class EvaluationBlock:
    SPEC_VERSION: ClassVar[str] = "aeread.evaluation_block/0.1"

    spec_version: str
    block_id: str
    kind: str
    subject_seats: tuple[str, ...]
    controlled_profiles: Mapping[str, str]
    repetitions: int
    seed_policy: str

    @classmethod
    def from_dict(cls, value: Any) -> "EvaluationBlock":
        data = _fields(
            value,
            required={
                "spec_version",
                "block_id",
                "kind",
                "subject_seats",
                "controlled_profiles",
                "repetitions",
                "seed_policy",
            },
            path="EvaluationBlock",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "EvaluationBlock")
        kind = _enum(
            data["kind"],
            "EvaluationBlock.kind",
            {"controlled", "cross_play", "self_play", "reference", "human_comparison"},
        )
        controlled = _string_mapping(
            data["controlled_profiles"], "EvaluationBlock.controlled_profiles"
        )
        if kind == "controlled" and not controlled:
            raise AuthoringValidationError(
                "EvaluationBlock.controlled_profiles must not be empty for controlled blocks"
            )
        return cls(
            spec_version=cls.SPEC_VERSION,
            block_id=_identifier(data["block_id"], "EvaluationBlock.block_id"),
            kind=kind,
            subject_seats=_string_tuple(
                data["subject_seats"], "EvaluationBlock.subject_seats"
            ),
            controlled_profiles=controlled,
            repetitions=_integer(
                data["repetitions"], "EvaluationBlock.repetitions", minimum=1
            ),
            seed_policy=_enum(
                data["seed_policy"],
                "EvaluationBlock.seed_policy",
                {"paired", "independent", "fixed"},
            ),
        )


@dataclass(frozen=True, slots=True)
class AnalysisPlan:
    SPEC_VERSION: ClassVar[str] = "aeread.analysis/0.1"

    spec_version: str
    analysis_plan_id: str
    estimands: tuple[str, ...]
    group_by: tuple[str, ...]
    missingness: str
    resampling_unit: str
    uncertainty: str
    multiplicity: str
    sensitivity: tuple[str, ...]
    cross_family_scalar: str

    @classmethod
    def from_dict(cls, value: Any) -> "AnalysisPlan":
        data = _fields(
            value,
            required={
                "spec_version",
                "analysis_plan_id",
                "estimands",
                "group_by",
                "missingness",
                "resampling_unit",
                "uncertainty",
                "multiplicity",
                "sensitivity",
                "cross_family_scalar",
            },
            path="AnalysisPlan",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "AnalysisPlan")
        return cls(
            spec_version=cls.SPEC_VERSION,
            analysis_plan_id=_identifier(
                data["analysis_plan_id"], "AnalysisPlan.analysis_plan_id"
            ),
            estimands=_string_tuple(data["estimands"], "AnalysisPlan.estimands"),
            group_by=_string_tuple(data["group_by"], "AnalysisPlan.group_by"),
            missingness=_identifier(data["missingness"], "AnalysisPlan.missingness"),
            resampling_unit=_identifier(
                data["resampling_unit"], "AnalysisPlan.resampling_unit"
            ),
            uncertainty=_identifier(data["uncertainty"], "AnalysisPlan.uncertainty"),
            multiplicity=_identifier(
                data["multiplicity"], "AnalysisPlan.multiplicity"
            ),
            sensitivity=_string_tuple(
                data["sensitivity"], "AnalysisPlan.sensitivity", allow_empty=True
            ),
            cross_family_scalar=_enum(
                data["cross_family_scalar"],
                "AnalysisPlan.cross_family_scalar",
                {"disabled", "declared"},
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model: str
    revision: str | None
    base_url: str | None

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "ModelSpec":
        data = _fields(
            value,
            required={"provider", "model"},
            optional={"revision", "base_url"},
            path=path,
        )
        return cls(
            provider=_identifier(data["provider"], f"{path}.provider"),
            model=_string(data["model"], f"{path}.model"),
            revision=_optional_string(data.get("revision"), f"{path}.revision"),
            base_url=_optional_string(data.get("base_url"), f"{path}.base_url"),
        )


@dataclass(frozen=True, slots=True)
class HarnessSpec:
    id: str
    version: str
    config: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "HarnessSpec":
        data = _fields(value, required={"id", "version", "config"}, path=path)
        config = _freeze_json(data["config"], f"{path}.config")
        if not isinstance(config, Mapping):
            raise AuthoringValidationError(f"{path}.config must be an object")
        return cls(
            id=_identifier(data["id"], f"{path}.id"),
            version=_string(data["version"], f"{path}.version"),
            config=config,
        )


@dataclass(frozen=True, slots=True)
class PromptSpec:
    prompt_id: str
    sha256: str

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "PromptSpec":
        data = _fields(value, required={"prompt_id", "sha256"}, path=path)
        return cls(
            prompt_id=_identifier(data["prompt_id"], f"{path}.prompt_id"),
            sha256=_sha256(data["sha256"], f"{path}.sha256"),
        )


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    kind: str
    implementation: str
    version: str

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "RuntimeSpec":
        data = _fields(value, required={"kind", "implementation", "version"}, path=path)
        return cls(
            kind=_identifier(data["kind"], f"{path}.kind"),
            implementation=_identifier(data["implementation"], f"{path}.implementation"),
            version=_string(data["version"], f"{path}.version"),
        )


@dataclass(frozen=True, slots=True)
class MemorySpec:
    mode: str
    implementation: str | None

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "MemorySpec":
        data = _fields(value, required={"mode"}, optional={"implementation"}, path=path)
        return cls(
            mode=_enum(
                data["mode"], f"{path}.mode", {"disabled", "ephemeral", "persistent"}
            ),
            implementation=_optional_string(
                data.get("implementation"), f"{path}.implementation"
            ),
        )


@dataclass(frozen=True, slots=True)
class ReasoningSpec:
    condition_id: str
    effort: str | None
    token_budget: int | None
    rationale_visibility: str

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "ReasoningSpec":
        data = _fields(
            value,
            required={"condition_id", "effort", "token_budget", "rationale_visibility"},
            path=path,
        )
        return cls(
            condition_id=_identifier(data["condition_id"], f"{path}.condition_id"),
            effort=_optional_string(data["effort"], f"{path}.effort"),
            token_budget=_optional_integer(
                data["token_budget"], f"{path}.token_budget", minimum=0
            ),
            rationale_visibility=_enum(
                data["rationale_visibility"],
                f"{path}.rationale_visibility",
                {"hidden", "private", "public", "unavailable"},
            ),
        )


@dataclass(frozen=True, slots=True)
class SamplingSpec:
    temperature: float
    max_output_tokens: int
    seed: int | None
    top_p: float | None

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "SamplingSpec":
        data = _fields(
            value,
            required={"temperature", "max_output_tokens"},
            optional={"seed", "top_p"},
            path=path,
        )
        top_p = data.get("top_p")
        return cls(
            temperature=_number(
                data["temperature"], f"{path}.temperature", minimum=0.0, maximum=2.0
            ),
            max_output_tokens=_integer(
                data["max_output_tokens"], f"{path}.max_output_tokens", minimum=1
            ),
            seed=_optional_integer(data.get("seed"), f"{path}.seed", minimum=0),
            top_p=(
                None
                if top_p is None
                else _number(top_p, f"{path}.top_p", minimum=0.0, maximum=1.0)
            ),
        )


@dataclass(frozen=True, slots=True)
class BudgetSpec:
    max_logical_actions: int
    timeout_seconds: float
    max_cost_usd: float | None

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "BudgetSpec":
        data = _fields(
            value,
            required={"max_logical_actions", "timeout_seconds"},
            optional={"max_cost_usd"},
            path=path,
        )
        return cls(
            max_logical_actions=_integer(
                data["max_logical_actions"], f"{path}.max_logical_actions", minimum=1
            ),
            timeout_seconds=_number(
                data["timeout_seconds"], f"{path}.timeout_seconds", minimum=0.001
            ),
            max_cost_usd=(
                None
                if data.get("max_cost_usd") is None
                else _number(data["max_cost_usd"], f"{path}.max_cost_usd", minimum=0.0)
            ),
        )


@dataclass(frozen=True, slots=True)
class BudgetOverrides:
    max_logical_actions: int | None
    timeout_seconds: float | None
    max_cost_usd: float | None

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "BudgetOverrides":
        allowed = {"max_logical_actions", "timeout_seconds", "max_cost_usd"}
        data = _fields(value, required=set(), optional=allowed, path=path)
        if not data:
            raise AuthoringValidationError(f"{path} must contain at least one override")
        return cls(
            max_logical_actions=(
                None
                if data.get("max_logical_actions") is None
                else _integer(
                    data["max_logical_actions"], f"{path}.max_logical_actions", minimum=1
                )
            ),
            timeout_seconds=(
                None
                if data.get("timeout_seconds") is None
                else _number(
                    data["timeout_seconds"], f"{path}.timeout_seconds", minimum=0.001
                )
            ),
            max_cost_usd=(
                None
                if data.get("max_cost_usd") is None
                else _number(data["max_cost_usd"], f"{path}.max_cost_usd", minimum=0.0)
            ),
        )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_action_attempts: int
    retryable_conditions: tuple[str, ...]
    session_mode: str
    sdk_retries: int

    @classmethod
    def from_dict(cls, value: Any, path: str) -> "RetryPolicy":
        data = _fields(
            value,
            required={
                "max_action_attempts",
                "retryable_conditions",
                "session_mode",
                "sdk_retries",
            },
            path=path,
        )
        sdk_retries = _integer(data["sdk_retries"], f"{path}.sdk_retries", minimum=0)
        if sdk_retries != 0:
            raise AuthoringValidationError(
                f"{path}.sdk_retries must be 0 so provider attempts cannot be hidden"
            )
        return cls(
            max_action_attempts=_integer(
                data["max_action_attempts"], f"{path}.max_action_attempts", minimum=1
            ),
            retryable_conditions=_string_tuple(
                data["retryable_conditions"],
                f"{path}.retryable_conditions",
                allow_empty=True,
            ),
            session_mode=_enum(
                data["session_mode"], f"{path}.session_mode", {"continue", "restart"}
            ),
            sdk_retries=sdk_retries,
        )


@dataclass(frozen=True, slots=True)
class AgentProfile:
    SPEC_VERSION: ClassVar[str] = "aeread.agent_profile/0.1"

    spec_version: str
    profile_id: str
    model: ModelSpec
    harness: HarnessSpec
    prompt: PromptSpec
    runtime: RuntimeSpec
    tools: tuple[str, ...]
    memory: MemorySpec
    reasoning: ReasoningSpec
    sampling: SamplingSpec
    budgets: BudgetSpec
    retry_policy: RetryPolicy

    @classmethod
    def from_dict(cls, value: Any) -> "AgentProfile":
        data = _fields(
            value,
            required={
                "spec_version",
                "profile_id",
                "model",
                "harness",
                "prompt",
                "runtime",
                "tools",
                "memory",
                "reasoning",
                "sampling",
                "budgets",
                "retry_policy",
            },
            path="AgentProfile",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "AgentProfile")
        return cls(
            spec_version=cls.SPEC_VERSION,
            profile_id=_identifier(data["profile_id"], "AgentProfile.profile_id"),
            model=ModelSpec.from_dict(data["model"], "AgentProfile.model"),
            harness=HarnessSpec.from_dict(data["harness"], "AgentProfile.harness"),
            prompt=PromptSpec.from_dict(data["prompt"], "AgentProfile.prompt"),
            runtime=RuntimeSpec.from_dict(data["runtime"], "AgentProfile.runtime"),
            tools=_string_tuple(data["tools"], "AgentProfile.tools", allow_empty=True),
            memory=MemorySpec.from_dict(data["memory"], "AgentProfile.memory"),
            reasoning=ReasoningSpec.from_dict(
                data["reasoning"], "AgentProfile.reasoning"
            ),
            sampling=SamplingSpec.from_dict(data["sampling"], "AgentProfile.sampling"),
            budgets=BudgetSpec.from_dict(data["budgets"], "AgentProfile.budgets"),
            retry_policy=RetryPolicy.from_dict(
                data["retry_policy"], "AgentProfile.retry_policy"
            ),
        )


@dataclass(frozen=True, slots=True)
class RunSpec:
    SPEC_VERSION: ClassVar[str] = "aeread.run_spec/0.1"

    spec_version: str
    run_spec_id: str
    suite_id: str
    evaluation_block_ids: tuple[str, ...]
    agent_profile_ids: tuple[str, ...]
    seat_assignments: Mapping[str, str]
    execution_mode: str
    replicate_override: int | None
    budget_overrides: BudgetOverrides | None

    @classmethod
    def from_dict(cls, value: Any) -> "RunSpec":
        data = _fields(
            value,
            required={
                "spec_version",
                "run_spec_id",
                "suite_id",
                "evaluation_block_ids",
                "agent_profile_ids",
                "seat_assignments",
                "execution_mode",
                "replicate_override",
                "budget_overrides",
            },
            path="RunSpec",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "RunSpec")
        profiles = _string_tuple(data["agent_profile_ids"], "RunSpec.agent_profile_ids")
        assignments = _string_mapping(data["seat_assignments"], "RunSpec.seat_assignments")
        unknown_profiles = sorted(set(assignments.values()) - set(profiles))
        if unknown_profiles:
            raise AuthoringValidationError(
                f"RunSpec.seat_assignments references undeclared profiles: {unknown_profiles}"
            )
        raw_overrides = data["budget_overrides"]
        return cls(
            spec_version=cls.SPEC_VERSION,
            run_spec_id=_identifier(data["run_spec_id"], "RunSpec.run_spec_id"),
            suite_id=_identifier(data["suite_id"], "RunSpec.suite_id"),
            evaluation_block_ids=_string_tuple(
                data["evaluation_block_ids"], "RunSpec.evaluation_block_ids"
            ),
            agent_profile_ids=profiles,
            seat_assignments=assignments,
            execution_mode=_enum(
                data["execution_mode"],
                "RunSpec.execution_mode",
                {"evaluate", "train", "offline", "live", "replay"},
            ),
            replicate_override=_optional_integer(
                data["replicate_override"], "RunSpec.replicate_override", minimum=1
            ),
            budget_overrides=(
                None
                if raw_overrides is None
                else BudgetOverrides.from_dict(raw_overrides, "RunSpec.budget_overrides")
            ),
        )


AuthoringRecord = (
    FamilyManifest
    | CaseManifest
    | SuiteManifest
    | SamplingPlan
    | EvaluationBlock
    | AnalysisPlan
    | AgentProfile
    | RunSpec
)


_RECORD_TYPES = {
    record_type.SPEC_VERSION: record_type
    for record_type in (
        FamilyManifest,
        CaseManifest,
        SuiteManifest,
        SamplingPlan,
        EvaluationBlock,
        AnalysisPlan,
        AgentProfile,
        RunSpec,
    )
}


def _require_spec_version(value: Any, expected: str, path: str) -> None:
    actual = _string(value, f"{path}.spec_version")
    if actual != expected:
        raise AuthoringValidationError(
            f"{path}.spec_version must be {expected!r}, got {actual!r}"
        )


def parse_authoring_record(value: Any) -> AuthoringRecord:
    """Parse one strict R1 record by its exact ``spec_version`` discriminator."""
    data = _as_mapping(value, "authoring record")
    if "spec_version" not in data:
        raise AuthoringValidationError("authoring record is missing spec_version")
    spec_version = _string(data["spec_version"], "authoring record.spec_version")
    record_type = _RECORD_TYPES.get(spec_version)
    if record_type is None:
        raise AuthoringValidationError(
            f"unsupported authoring record spec_version: {spec_version!r}"
        )
    return record_type.from_dict(data)


__all__ = [
    "AgentProfile",
    "AnalysisPlan",
    "AuthoringRecord",
    "AuthoringValidationError",
    "CaseManifest",
    "EvaluationBlock",
    "FamilyManifest",
    "RunSpec",
    "SamplingPlan",
    "SuiteManifest",
    "parse_authoring_record",
]
