"""Shared Arena adapter campaign primitives: a sealed, multi-limit route probe.

A family campaign must prove, before spending a paid six-plus-six panel, that
its pinned Arena route/model/revision genuinely accepts every token limit the
profile will request and that usage/cost are provider-reported rather than
invented. ``run_adapter_canary`` is that one unscored probe. It charges the
same aggregate cost ceiling across every limit it tries, never treats a
truncated response as admitted even when its partial content happens to
parse, and seals its result as a write-once, content-hashed checkpoint so a
retried run resumes instead of re-spending money.

Only ``run_adapter_canary``, the canary constants, and the two write-once
helpers (``_write_once``, ``_digest``) are a stable surface for family
campaign modules. Everything else here is private.

The aggregate cost ceiling is enforced twice. Pre-call, every probe request
carries ``max_cost_usd`` set to the remaining budget (``total_max_cost_usd``
minus whatever has already been charged), so a well-behaved provider refuses
the call itself rather than this module discovering the overage afterward.
Post-call, any response whose reported cost -- added to the running total --
would exceed the ceiling is rejected here regardless of what the provider
allowed, and it is charged before that rejection, never coerced to zero.
Actual spend can still exceed the ceiling only if the provider ignores
``max_cost_usd`` and reports a cost that alone blows through the remainder
in one call; that response is rejected as ``cost_ceiling_exceeded``, and the
checkpoint's ``cumulative_cost_usd`` records the full amount actually
charged, not the ceiling, so an over-charge is visible rather than silently
truncated.
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import math
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Mapping

from .resolver import canonical_json_bytes
from ..task.execution import ArenaChatClient, ProviderFailure, ProviderRequest

# Pinned canary route identity. A family campaign compares its own profile's
# provider/model/revision against these constants rather than trusting an
# adapter-private capability field (spec 2026-09-07-issue-135-repair-design
# section 8.5): a mismatch is a configuration error caught before any paid
# call, not something this module infers.
PROVIDER = "arena"
MODEL = "glm-5p2"
REVISION = "glm-5p2"
BASE_URL = "https://api.preview.arena.ai/v1"
ROUTE_PROVIDER = "Arena"
CANARY_MAX_OUTPUT_TOKENS = 512
CANARY_MAX_COST_USD = 0.01

SCHEMA_VERSION = "aeread.adapter_campaign_canary/1.0"

# A finish reason that means the provider stopped for lack of room, not
# because the answer was complete. Global invariant 5: any response carrying
# one of these is a failed attempt and is never parsed, scored, or admitted,
# even when its partial content happens to be well-formed JSON.
_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_output_tokens"})

# A closed allowlist of ``ProviderFailure.condition`` values safe to persist
# verbatim. ``ProviderFailure`` carries provider-authored text; a condition
# outside this set is folded into the generic ``provider_error`` label so an
# unexpected provider string can never reach a public checkpoint.
_SAFE_PROVIDER_FAILURE_CONDITIONS = frozenset(
    {
        "auth",
        "empty_response",
        "length",
        "provider_5xx",
        "provider_contract",
        "provider_rejected",
        "rate_limit",
        "timeout",
        "transport",
    }
)

_CANARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["ok"]}},
    "required": ["status"],
    "additionalProperties": False,
}

# The probe's instruction text as a named constant, not an inline literal, so
# a resumed campaign can prove it was sealed against *this* prompt: identity
# checks rebuild the probe request from this constant and compare hashes,
# which only works if the constant -- not a copy of the string -- is what
# ``_build_probe_request`` actually sends.
_CANARY_INSTRUCTIONS = "Return only the requested JSON object."

# A closed allowlist of persistable ``failure_type`` labels. Never the raw
# exception class name: a class name is an implementation detail, not a
# stable contract, and persisting one risks leaking internals into a public
# checkpoint as Python renames or refactors them.
_PROVIDER_FAILURE = "provider_failure"
_CANARY_REJECTED = "canary_rejected"

# A closed allowlist of ``finish_reason`` values safe to persist verbatim.
# Arena (OpenAI-compatible) responses may carry an arbitrary provider string
# here; one outside this set is folded into a sentinel so unexpected
# provider text can never reach a public checkpoint.
_ALLOWED_FINISH_REASONS = frozenset(
    {"stop", "length", "max_output_tokens", "tool_calls", "content_filter", "unknown"}
)
_UNEXPECTED_FINISH_REASON = "unexpected_finish_reason"

# ``resolved_model`` is only ever persisted as the requested ``MODEL`` or
# this sentinel -- never the raw provider string -- so a provider that
# resolves to (or impersonates) an unexpected model never leaks that string
# into a public checkpoint.
_UNEXPECTED_MODEL = "unexpected_model"

# The exact set of top-level keys a sealed checkpoint may carry. ``_resume``
# rejects any record whose key set differs from this, even when its digest
# is internally consistent: a digest only proves a record is self-coherent,
# not that it is shaped the way this schema promises.
_RECORD_SCHEMA_KEYS = frozenset(
    {
        "schema_version",
        "route_provider",
        "scored",
        "first_request_sha256",
        "family_id",
        "provider",
        "model",
        "revision",
        "base_url",
        "requested_limits",
        "total_max_cost_usd",
        "require_reported_accounting",
        "status",
        "probes",
        "cumulative_cost_usd",
        "cost_usd",
        "cost_accounting_state",
        "failure_type",
        "failure_condition",
        "record_sha256",
    }
)

# The exact set of keys a single sealed probe entry may carry. A probe
# missing one of these or carrying an extra one is rejected on resume even
# when the record's own digest is internally consistent, for the same
# reason ``_RECORD_SCHEMA_KEYS`` exists: a digest only proves self-
# coherence, not the shape this schema promises.
_PROBE_RECORD_KEYS = frozenset(
    {
        "request_sha256",
        "max_output_tokens",
        "resolved_model",
        "finish_reason",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "cost_usd",
    }
)

# Closed vocabularies a resumed record's status-linked fields must belong
# to -- the same ones enforced at write time. A tampered-but-internally-
# consistent checkpoint (digest recomputed correctly after the edit) is
# only caught by checking values against these sets, not by the digest.
_RESUMABLE_RESOLVED_MODELS = frozenset({MODEL, _UNEXPECTED_MODEL})
_RESUMABLE_FINISH_REASONS = _ALLOWED_FINISH_REASONS | frozenset({_UNEXPECTED_FINISH_REASON})
_RESUMABLE_PROVIDER_FAILURE_CONDITIONS = _SAFE_PROVIDER_FAILURE_CONDITIONS | frozenset(
    {"provider_error"}
)
_CANARY_REJECTED_CONDITIONS = frozenset(
    {
        "cost_budget_exceeded",
        "accounting_unavailable",
        "cost_ceiling_exceeded",
        "invalid_token_accounting",
        "length",
        "invalid_json_response",
        "invalid_response",
    }
)

# The two statuses a sealed checkpoint may carry. Anything else is rejected
# on resume even when the record is internally self-consistent.
_RESUMABLE_STATUSES = frozenset({"admitted", "rejected"})

# ``cost_usd``/``cost_accounting_state`` are a matched pair: ``None`` iff
# ``"unknown"``, a validated finite non-negative number iff ``"known"``. No
# third combination is ever sealed, so none is ever resumable.
_RESUMABLE_COST_ACCOUNTING_STATES = frozenset({"known", "unknown"})

# ``failure_condition`` values for which the *last* probe's outcome is
# determinable from the condition alone, because the write path only ever
# reaches that condition after appending the probe that triggered it. Only
# these are cross-checked against the last probe on resume; conditions
# reached before a probe is appended (``cost_budget_exceeded``,
# ``accounting_unavailable``, ``invalid_token_accounting``) legitimately
# carry zero probes and are not held to this check.
_LAST_PROBE_DETERMINABLE_CONDITIONS = frozenset(
    {"length", "cost_ceiling_exceeded", "invalid_json_response", "invalid_response"}
)


def _sanitized_finish_reason(value: Any) -> str:
    """Return ``value`` if it is on the closed allowlist, else a sentinel."""
    if isinstance(value, str) and value in _ALLOWED_FINISH_REASONS:
        return value
    return _UNEXPECTED_FINISH_REASON


def _sanitized_resolved_model(value: Any) -> str:
    """Return the requested ``MODEL`` if it matches, else a sentinel.

    The raw provider string is never persisted when it disagrees with the
    pinned ``MODEL``: an unexpected resolved model is a configuration or
    impersonation signal, not content safe to echo into a checkpoint.
    """
    return MODEL if value == MODEL else _UNEXPECTED_MODEL


def _digest(value: Any) -> str:
    """Return the sha256 of ``value``'s canonical JSON encoding."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    """Durably and atomically persist ``value`` without ever overwriting
    different content.

    The payload is written in full to a uniquely-named temp file in the
    same directory and fsynced there -- under a name nothing else is
    looking at -- before it is ever linked onto the final path. Publishing
    is a single ``os.link(temp, path)`` call: an atomic filesystem
    operation, so a concurrent reader can never observe a partially-written
    final file, and a write that fails before that link leaves no final
    file at all (only a temp file, which the outer ``finally`` always
    removes, whatever happens).

    ``os.link`` raises ``FileExistsError`` when the final path already
    exists, which is how a losing racer discovers it lost: it opens the
    winner's file with ``O_NOFOLLOW`` so a racer that published a symlink
    is rejected rather than followed, then compares bytes through that
    descriptor. Byte-identical content is idempotent and returns normally;
    different content is a genuine conflict and is raised. The symlink
    check happens only at this point -- informed by the filesystem's own
    discovery that the path exists -- never as an earlier stat performed
    before the link is attempted, which would have a race window of its
    own: another process could swap a symlink into place after the check
    and before the link.

    If ``os.link`` fails for a reason other than the path already existing
    -- some filesystems (notably certain network or overlay mounts) do not
    support hard links at all and raise ``EPERM``/``EOPNOTSUPP`` -- this
    falls back to a direct ``O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW``
    create-and-write of the final path, fsynced before return. This
    fallback is documented as non-atomic with respect to visibility: unlike
    the link-based publish, a concurrent reader can observe the destination
    mid-write for the brief window between create and the payload actually
    landing. It exists anyway because the alternative is worse: a paid
    canary probe must never be left with no checkpoint at all just because
    its filesystem lacks hard-link support.
    """
    payload = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    try:
        temp_fd = os.open(
            temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(temp_fd, view)
                if written <= 0:
                    raise OSError("short write while persisting adapter campaign checkpoint")
                view = view[written:]
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)

        try:
            os.link(temp_path, path)
        except FileExistsError:
            try:
                existing_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise ValueError(
                        "checkpoint destination must not be a symlink"
                    ) from error
                raise
            try:
                if stat.S_ISLNK(os.fstat(existing_fd).st_mode):
                    raise ValueError("checkpoint destination must not be a symlink")
                chunks = []
                while True:
                    chunk = os.read(existing_fd, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                existing = b"".join(chunks)
            finally:
                os.close(existing_fd)
            if existing != payload:
                raise ValueError(
                    f"refusing to overwrite a different adapter campaign checkpoint: {path}"
                )
            return
        except OSError as error:
            if error.errno not in (
                errno.EPERM,
                errno.EOPNOTSUPP,
                getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
            ):
                raise
            # The filesystem backing ``path`` does not support hard links.
            # Fall back to a direct, non-atomic-visibility create-exclusive
            # write of the final path itself, documented on the function.
            fallback_fd = os.open(
                path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fallback_fd, view)
                    if written <= 0:
                        raise OSError(
                            "short write while persisting adapter campaign checkpoint"
                        )
                    view = view[written:]
                os.fsync(fallback_fd)
            finally:
                os.close(fallback_fd)

        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def _validate_limits(limits: tuple[int, ...]) -> None:
    if not limits:
        raise ValueError("max_output_tokens must request at least one limit")
    previous: int | None = None
    for limit in limits:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("every max_output_tokens limit must be a positive integer")
        if previous is not None and limit <= previous:
            raise ValueError("max_output_tokens limits must be strictly increasing")
        previous = limit


def _validate_budget(total_max_cost_usd: float) -> float:
    if (
        isinstance(total_max_cost_usd, bool)
        or not isinstance(total_max_cost_usd, (int, float))
        or not math.isfinite(total_max_cost_usd)
        or total_max_cost_usd < 0
    ):
        raise ValueError("total_max_cost_usd must be a finite, non-negative number")
    return float(total_max_cost_usd)


def _campaign_identity(
    *,
    family_id: str,
    limits: tuple[int, ...],
    total_max_cost_usd: float,
    require_reported_accounting: bool,
) -> dict[str, Any]:
    return {
        "family_id": family_id,
        "provider": PROVIDER,
        "model": MODEL,
        "revision": REVISION,
        "base_url": BASE_URL,
        "requested_limits": list(limits),
        "total_max_cost_usd": total_max_cost_usd,
        "require_reported_accounting": bool(require_reported_accounting),
    }


def _verify_resumed_record(
    record: Mapping[str, Any],
    *,
    family_id: str,
    limits: tuple[int, ...],
    total_max_cost_usd: float,
) -> None:
    """Reject a checkpoint whose sealed contents disagree with today's
    request construction, drift outside the closed schema it was sealed
    against, or are internally inconsistent with each other.

    A digest only proves a record is internally self-consistent with
    whatever an attacker wrote into it -- it says nothing about whether
    each field's *value* is one this schema ever actually seals. So every
    field with a constrained value is checked here, not merely required to
    be present: ``status`` against a closed enum, ``schema_version``
    against the module constant, ``scored`` against ``False``,
    ``route_provider``/``provider``/``model``/``revision`` against their
    pinned constants, and ``cost_usd``/``cost_accounting_state`` against
    each other (``None`` iff ``"unknown"``, else a validated finite
    non-negative number iff ``"known"``).

    Every probe's ``request_sha256`` is not merely compared to itself: it
    is recomputed from the *current* prompt, schema, limits, model,
    revision and seed by rebuilding the same probe request this call would
    send, so a prompt or schema edit invalidates every earlier checkpoint
    instead of letting it resume unchanged. A ``ProviderFailure`` checkpoint
    carries no probes at all, so it is re-validated the same way against a
    sealed ``first_request_sha256`` -- the hash of the very first probe
    this campaign ever intended to send -- rather than being exempted for
    having nothing else to check.

    Every probe's key set must equal the closed probe schema, its token
    fields must be validated non-negative ints and its cost either ``None``
    or a validated finite non-negative number, and its
    ``resolved_model``/``finish_reason`` -- along with the record's own
    ``failure_type``/``failure_condition`` -- must fall inside the same
    closed vocabularies enforced at write time.

    Status and probes must agree with each other too: an admitted record's
    probes must all report ``finish_reason == "stop"`` and must number
    exactly the requested limits; a rejected record whose
    ``failure_condition`` is one the write path only ever reaches *after*
    appending the probe that triggered it (truncation, the cost ceiling, or
    an unparsable/wrong-shaped response) must carry that probe, and that
    probe's own outcome must be the one the condition claims. Conditions
    the write path can reach with zero probes (an exhausted budget before
    any call, or an accounting probe that failed before it was recorded)
    are not held to that probe-presence check, since a legitimately sealed
    record from that path has none to check.
    """
    status = record.get("status")
    if status not in _RESUMABLE_STATUSES:
        raise ValueError("canary checkpoint has an unexpected status")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("canary checkpoint has an unexpected schema_version")
    if record.get("scored") is not False:
        raise ValueError("canary checkpoint has an unexpected scored flag")
    if record.get("route_provider") != ROUTE_PROVIDER:
        raise ValueError("canary checkpoint has an unexpected route_provider")
    if record.get("provider") != PROVIDER:
        raise ValueError("canary checkpoint has an unexpected provider")
    if record.get("model") != MODEL:
        raise ValueError("canary checkpoint has an unexpected model")
    if record.get("revision") != REVISION:
        raise ValueError("canary checkpoint has an unexpected revision")

    cost_usd = record.get("cost_usd")
    cost_accounting_state = record.get("cost_accounting_state")
    if cost_usd is None:
        if cost_accounting_state != "unknown":
            raise ValueError("canary checkpoint cost accounting state is inconsistent")
    else:
        if cost_accounting_state != "known":
            raise ValueError("canary checkpoint cost accounting state is inconsistent")
        if _numeric(cost_usd) is None:
            raise ValueError("canary checkpoint has an invalid cost_usd")

    failure_type = record.get("failure_type")
    failure_condition = record.get("failure_condition")
    if status == "admitted":
        if failure_type is not None or failure_condition is not None:
            raise ValueError("canary checkpoint admitted record has unexpected failure fields")
    else:
        if failure_type not in (_PROVIDER_FAILURE, _CANARY_REJECTED):
            raise ValueError("canary checkpoint has an unexpected failure_type")
        if failure_type == _PROVIDER_FAILURE:
            if failure_condition not in _RESUMABLE_PROVIDER_FAILURE_CONDITIONS:
                raise ValueError("canary checkpoint has an unexpected failure_condition")
        else:
            if failure_condition not in _CANARY_REJECTED_CONDITIONS:
                raise ValueError("canary checkpoint has an unexpected failure_condition")

    first_request = _build_probe_request(
        family_id=family_id, ordinal=0, limit=limits[0], remaining_budget=total_max_cost_usd
    )
    if record.get("first_request_sha256") != first_request.request_sha256:
        raise ValueError("canary checkpoint request hash mismatch")

    probes = record.get("probes")
    if not isinstance(probes, list):
        raise ValueError("canary checkpoint probes must be a list")
    if len(probes) > len(limits):
        raise ValueError("canary checkpoint probe count exceeds requested limits")
    if status == "admitted" and len(probes) != len(limits):
        raise ValueError("canary checkpoint probe count does not match requested limits")

    cumulative = 0.0
    for ordinal, probe in enumerate(probes):
        if not isinstance(probe, Mapping):
            raise ValueError("canary checkpoint probe is not an object")
        if set(probe.keys()) != _PROBE_RECORD_KEYS:
            raise ValueError("canary checkpoint probe has an unexpected key set")
        if probe.get("max_output_tokens") != limits[ordinal]:
            raise ValueError("canary checkpoint probe limit does not match requested limits")
        if probe.get("resolved_model") not in _RESUMABLE_RESOLVED_MODELS:
            raise ValueError("canary checkpoint probe has an unexpected resolved_model")
        probe_finish_reason = probe.get("finish_reason")
        if probe_finish_reason not in _RESUMABLE_FINISH_REASONS:
            raise ValueError("canary checkpoint probe has an unexpected finish_reason")
        if status == "admitted" and probe_finish_reason != "stop":
            raise ValueError("canary checkpoint admitted record has a non-stop probe")
        if _validated_token_count(probe.get("input_tokens")) is None:
            raise ValueError("canary checkpoint probe has an invalid input_tokens")
        if _validated_token_count(probe.get("cached_input_tokens")) is None:
            raise ValueError("canary checkpoint probe has an invalid cached_input_tokens")
        if _validated_token_count(probe.get("output_tokens")) is None:
            raise ValueError("canary checkpoint probe has an invalid output_tokens")
        remaining = total_max_cost_usd - cumulative
        expected = _build_probe_request(
            family_id=family_id,
            ordinal=ordinal,
            limit=limits[ordinal],
            remaining_budget=remaining,
        ).request_sha256
        if probe.get("request_sha256") != expected:
            raise ValueError("canary checkpoint request hash mismatch")
        probe_cost = probe.get("cost_usd")
        if probe_cost is not None:
            validated_probe_cost = _numeric(probe_cost)
            if validated_probe_cost is None:
                raise ValueError("canary checkpoint probe has an invalid cost_usd")
            cumulative += validated_probe_cost

    if status == "rejected" and failure_type == _CANARY_REJECTED:
        if failure_condition in _LAST_PROBE_DETERMINABLE_CONDITIONS:
            if not probes:
                raise ValueError("canary checkpoint rejected record has no probes")
            last_finish_reason = probes[-1].get("finish_reason")
            if failure_condition == "length":
                if last_finish_reason not in _TRUNCATED_FINISH_REASONS:
                    raise ValueError(
                        "canary checkpoint failure_condition is inconsistent with its last probe"
                    )
            elif failure_condition == "cost_ceiling_exceeded":
                if not cumulative > total_max_cost_usd:
                    raise ValueError(
                        "canary checkpoint failure_condition is inconsistent with its last probe"
                    )
            else:  # "invalid_json_response" or "invalid_response"
                if last_finish_reason != "stop":
                    raise ValueError(
                        "canary checkpoint failure_condition is inconsistent with its last probe"
                    )


def _resume(
    checkpoint_path: Path,
    identity: Mapping[str, Any],
    *,
    family_id: str,
    limits: tuple[int, ...],
    total_max_cost_usd: float,
) -> dict[str, Any]:
    """Validate and return an existing checkpoint, never calling the provider.

    Every sealed identity input must match the current call's arguments: a
    caller resuming with a different family, route, limit set, budget, or
    accounting requirement gets a typed ``ValueError`` rather than a stale
    admission for work it never actually requested. The record's key set,
    every probe's key set and request hash against the *current* request
    construction, and every status-linked field's closed vocabulary are
    checked too, so a record that is internally consistent but schema-
    extended, prompt-stale, or tampered-within-vocabulary is rejected all
    the same.

    The checkpoint is never read by name through ``Path.read_text``: the
    caller already ``lstat``-checked the destination before calling this
    function, but that check and this read are two separate filesystem
    calls, so a concurrent writer could swap a symlink into place in
    between. This opens the path exactly once, with ``O_NOFOLLOW``, so that
    exact race is caught here too -- a symlink discovered at open time
    raises ``ELOOP``, which is turned into the same typed rejection as a
    symlink discovered by the earlier ``lstat`` -- rather than trusting the
    name to still mean what the ``lstat`` saw.
    """
    try:
        checkpoint_fd = os.open(checkpoint_path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError("canary checkpoint destination must not be a symlink") from error
        raise
    try:
        chunks = []
        while True:
            chunk = os.read(checkpoint_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(checkpoint_fd)
    try:
        record = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("canary checkpoint is not valid JSON") from error
    if not isinstance(record, dict):
        raise ValueError("canary checkpoint is not an object")
    stored_digest = record.get("record_sha256")
    payload = {key: value for key, value in record.items() if key != "record_sha256"}
    if stored_digest != _digest(payload):
        raise ValueError("canary checkpoint digest mismatch")
    if set(record.keys()) != _RECORD_SCHEMA_KEYS:
        raise ValueError("canary checkpoint has an unexpected key set")
    for key, expected in identity.items():
        if record.get(key) != expected:
            raise ValueError("canary checkpoint input mismatch")
    _verify_resumed_record(
        record, family_id=family_id, limits=limits, total_max_cost_usd=total_max_cost_usd
    )
    return record


def _build_probe_request(
    *, family_id: str, ordinal: int, limit: int, remaining_budget: float
) -> ProviderRequest:
    return ProviderRequest(
        provider_call_id=f"{family_id}_arena_canary_{ordinal}_{limit}",
        provider=PROVIDER,
        base_url=BASE_URL,
        model=MODEL,
        revision=REVISION,
        instructions=_CANARY_INSTRUCTIONS,
        input_text=(
            f"This is unscored route-admission probe {ordinal} for {family_id} "
            f'at a {limit}-token limit. Return {{"status":"ok"}}.'
        ),
        temperature=0.0,
        top_p=None,
        max_output_tokens=limit,
        reasoning_effort="none",
        timeout_seconds=180.0,
        request_sha256="",
        max_cost_usd=remaining_budget,
        output_schema=_CANARY_SCHEMA,
        provider_metadata={
            "catalog_model_id": MODEL,
            "provider_cost_status": "response_reported",
        },
        seed=300,
    ).with_computed_hash()


def _numeric(value: Any) -> float | None:
    """Return ``value`` as a finite, non-negative float, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _validated_token_count(value: Any) -> int | None:
    """Return ``value`` as a validated non-negative ``int``, or ``None``.

    A provider-reported token field that is anything other than a plain
    non-negative int -- a string, for instance -- is never persisted
    verbatim: an unvalidated numeric-looking field could otherwise smuggle
    arbitrary provider text into a public checkpoint under a key that
    looks like a count.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _raw_usage_agrees(result: Any) -> bool:
    """Cross-check the Arena ``raw_response["usage"]`` against ``result``.

    Validated in memory only; the raw payload itself is never returned or
    persisted by this function or its caller.
    """
    raw = getattr(result, "raw_response", None)
    if not isinstance(raw, Mapping):
        return False
    if str(raw.get("id") or "") != result.response_id:
        return False
    usage = raw.get("usage")
    if not isinstance(usage, Mapping):
        return False
    prompt_tokens = usage.get("prompt_tokens")
    if (
        isinstance(prompt_tokens, bool)
        or not isinstance(prompt_tokens, int)
        or prompt_tokens < 0
        or prompt_tokens != result.input_tokens
    ):
        return False
    completion_tokens = usage.get("completion_tokens")
    if (
        isinstance(completion_tokens, bool)
        or not isinstance(completion_tokens, int)
        or completion_tokens < 0
        or completion_tokens != result.output_tokens
    ):
        return False
    cached_tokens = 0
    details = usage.get("prompt_tokens_details")
    if isinstance(details, Mapping):
        candidate = details.get("cached_tokens", 0)
        if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
            return False
        cached_tokens = candidate
    if cached_tokens != result.cached_input_tokens:
        return False
    raw_cost = _numeric(usage.get("cost"))
    if raw_cost is None:
        return False
    reported_cost = result.cost_usd
    if reported_cost is None or abs(raw_cost - float(reported_cost)) > 1e-9:
        return False
    return True


def _resolve_probe_cost(result: Any, *, require_reported_accounting: bool) -> float | None:
    """Return the provider-reported cost of a completed probe, or ``None``.

    ``None`` means the cost is unknown or unproven. It is the caller's
    signal to reject the probe as ``accounting_unavailable`` -- an unknown
    cost is never charged as zero, because that would let a genuinely
    unbounded call bypass the aggregate cost ceiling.
    """
    cost = _numeric(getattr(result, "cost_usd", None))
    if cost is None:
        return None
    if require_reported_accounting and not _raw_usage_agrees(result):
        return None
    return cost


def canary_schema() -> dict[str, Any]:
    """Return the JSON schema every canary probe's structured output must match."""
    return dict(_CANARY_SCHEMA)


async def run_adapter_canary(
    *,
    family_id: str,
    checkpoint_path: Path,
    max_output_tokens: tuple[int, ...] = (CANARY_MAX_OUTPUT_TOKENS,),
    total_max_cost_usd: float = CANARY_MAX_COST_USD,
    require_reported_accounting: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run one unscored, multi-limit Arena route-admission probe.

    Tries each requested ``max_output_tokens`` limit in order against the
    pinned Arena route, in one resumable campaign bounded by a single
    aggregate ``total_max_cost_usd`` reserve shared across every limit. A
    truncated response is never admitted, even when its partial content
    happens to parse as the expected canary JSON. The result is sealed as a
    write-once, content-hashed checkpoint: resuming with the same campaign
    identity returns that checkpoint without another provider call, and
    resuming with a different identity raises ``ValueError`` instead of
    returning a stale admission.
    """
    if not isinstance(family_id, str) or not family_id:
        raise ValueError("family_id must be a non-empty string")
    limits = tuple(max_output_tokens)
    _validate_limits(limits)
    budget = _validate_budget(total_max_cost_usd)
    identity = _campaign_identity(
        family_id=family_id,
        limits=limits,
        total_max_cost_usd=budget,
        require_reported_accounting=require_reported_accounting,
    )

    # ``lstat``, not ``exists``/``is_file``: a symlink at the checkpoint
    # destination is rejected outright, before any provider call, whether
    # it points at a real checkpoint or nowhere at all. ``exists()`` follows
    # the link and would happily resume through it.
    try:
        checkpoint_lstat = os.lstat(checkpoint_path)
    except FileNotFoundError:
        checkpoint_lstat = None
    if checkpoint_lstat is not None:
        if stat.S_ISLNK(checkpoint_lstat.st_mode):
            raise ValueError("canary checkpoint destination must not be a symlink")
        return _resume(
            checkpoint_path,
            identity,
            family_id=family_id,
            limits=limits,
            total_max_cost_usd=budget,
        )

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "route_provider": ROUTE_PROVIDER,
        "scored": False,
        "first_request_sha256": _build_probe_request(
            family_id=family_id, ordinal=0, limit=limits[0], remaining_budget=budget
        ).request_sha256,
        **identity,
    }
    probes: list[dict[str, Any]] = []
    cumulative = 0.0
    active_client = client or ArenaChatClient()

    def finalize(
        *,
        status: str,
        failure_type: str | None = None,
        failure_condition: str | None = None,
        cost_unknown: bool = False,
    ) -> dict[str, Any]:
        final = dict(record)
        final["status"] = status
        final["probes"] = probes
        final["cumulative_cost_usd"] = cumulative
        if cost_unknown:
            final["cost_usd"] = None
            final["cost_accounting_state"] = "unknown"
        else:
            final["cost_usd"] = cumulative
            final["cost_accounting_state"] = "known"
        # Always present, even as None on the admitted path: a checkpoint's
        # key set must be the same shape regardless of status so ``_resume``
        # can reject any record whose keys differ from the schema's,
        # without tolerating an "absent means admitted" special case.
        final["failure_type"] = failure_type
        final["failure_condition"] = failure_condition
        final["record_sha256"] = _digest(
            {key: value for key, value in final.items() if key != "record_sha256"}
        )
        _write_once(checkpoint_path, final)
        return final

    for ordinal, limit in enumerate(limits):
        remaining = budget - cumulative
        if remaining <= 0:
            return finalize(status="rejected", failure_type=_CANARY_REJECTED,
                             failure_condition="cost_budget_exceeded")
        request = _build_probe_request(
            family_id=family_id, ordinal=ordinal, limit=limit, remaining_budget=remaining
        )
        try:
            result = await active_client.complete(request)
        except ProviderFailure as error:
            condition = (
                error.condition
                if error.condition in _SAFE_PROVIDER_FAILURE_CONDITIONS
                else "provider_error"
            )
            # A billed call that raised before returning any accounting
            # never proves it cost nothing: the failure is charged as
            # unknown, not coerced to the already-known cumulative, and it
            # is terminal -- no further probe is attempted.
            return finalize(status="rejected", failure_type=_PROVIDER_FAILURE,
                             failure_condition=condition, cost_unknown=True)

        cost = _resolve_probe_cost(result, require_reported_accounting=require_reported_accounting)
        if cost is None:
            return finalize(status="rejected", failure_type=_CANARY_REJECTED,
                             failure_condition="accounting_unavailable", cost_unknown=True)
        cumulative += cost
        # Validated before it ever reaches the probe dict, never after: a
        # provider-reported token field that is not a plain non-negative
        # int (a string, say) must not be persisted verbatim, because by
        # the time it was in the probe dict it would already be in the
        # checkpoint bytes this rejection is trying to keep it out of.
        input_tokens = _validated_token_count(result.input_tokens)
        cached_input_tokens = _validated_token_count(result.cached_input_tokens)
        output_tokens = _validated_token_count(result.output_tokens)
        if input_tokens is None or cached_input_tokens is None or output_tokens is None:
            return finalize(status="rejected", failure_type=_CANARY_REJECTED,
                             failure_condition="invalid_token_accounting")
        probes.append(
            {
                "request_sha256": request.request_sha256,
                "max_output_tokens": limit,
                "resolved_model": _sanitized_resolved_model(result.resolved_model),
                "finish_reason": _sanitized_finish_reason(result.finish_reason),
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            }
        )
        # Charged before any content check: a response whose reported cost
        # alone breaches the aggregate ceiling is rejected here even if its
        # content would otherwise have been admitted.
        if cumulative > budget:
            return finalize(status="rejected", failure_type=_CANARY_REJECTED,
                             failure_condition="cost_ceiling_exceeded")
        if result.finish_reason in _TRUNCATED_FINISH_REASONS:
            return finalize(status="rejected", failure_type=_CANARY_REJECTED,
                             failure_condition="length")
        try:
            payload = json.loads(result.output_text)
        except json.JSONDecodeError:
            return finalize(status="rejected", failure_type=_CANARY_REJECTED,
                             failure_condition="invalid_json_response")
        if payload != {"status": "ok"}:
            return finalize(status="rejected", failure_type=_CANARY_REJECTED,
                             failure_condition="invalid_response")

    return finalize(status="admitted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--max-output-tokens", type=int, action="append", default=None)
    parser.add_argument("--total-max-cost-usd", type=float, default=CANARY_MAX_COST_USD)
    parser.add_argument("--require-reported-accounting", action="store_true")
    args = parser.parse_args(argv)
    limits = tuple(args.max_output_tokens) if args.max_output_tokens else (CANARY_MAX_OUTPUT_TOKENS,)
    record = asyncio.run(
        run_adapter_canary(
            family_id=args.family,
            checkpoint_path=args.checkpoint,
            max_output_tokens=limits,
            total_max_cost_usd=args.total_max_cost_usd,
            require_reported_accounting=args.require_reported_accounting,
        )
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "admitted" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROVIDER",
    "MODEL",
    "REVISION",
    "BASE_URL",
    "ROUTE_PROVIDER",
    "CANARY_MAX_OUTPUT_TOKENS",
    "CANARY_MAX_COST_USD",
    "SCHEMA_VERSION",
    "canary_schema",
    "run_adapter_canary",
    "main",
]
