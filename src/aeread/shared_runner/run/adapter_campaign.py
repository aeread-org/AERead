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
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
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


def _digest(value: Any) -> str:
    """Return the sha256 of ``value``'s canonical JSON encoding."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    """Durably persist ``value`` without ever overwriting different content.

    Mirrors ``task.receipts.write_evaluation_receipt``: the final path is
    created with ``O_CREAT | O_EXCL`` so two processes racing to seal the
    same checkpoint cannot corrupt each other's write. A process that loses
    the race either finds byte-identical content (idempotent, returns
    normally) or finds different content (a genuine conflict, raised).
    """
    payload = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("checkpoint destination must not be a symlink")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != payload:
            raise ValueError(
                f"refusing to overwrite a different adapter campaign checkpoint: {path}"
            )
        return
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while persisting adapter campaign checkpoint")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


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


def _resume(checkpoint_path: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return an existing checkpoint, never calling the provider.

    Every sealed identity input must match the current call's arguments: a
    caller resuming with a different family, route, limit set, budget, or
    accounting requirement gets a typed ``ValueError`` rather than a stale
    admission for work it never actually requested.
    """
    try:
        record = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("canary checkpoint is not valid JSON") from error
    if not isinstance(record, dict):
        raise ValueError("canary checkpoint is not an object")
    stored_digest = record.get("record_sha256")
    payload = {key: value for key, value in record.items() if key != "record_sha256"}
    if stored_digest != _digest(payload):
        raise ValueError("canary checkpoint digest mismatch")
    for key, expected in identity.items():
        if record.get(key) != expected:
            raise ValueError("canary checkpoint input mismatch")
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
        instructions="Return only the requested JSON object.",
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

    if checkpoint_path.exists():
        return _resume(checkpoint_path, identity)

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "route_provider": ROUTE_PROVIDER,
        "scored": False,
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
        if failure_type is not None:
            final["failure_type"] = failure_type
        if failure_condition is not None:
            final["failure_condition"] = failure_condition
        final["record_sha256"] = _digest(
            {key: value for key, value in final.items() if key != "record_sha256"}
        )
        _write_once(checkpoint_path, final)
        return final

    for ordinal, limit in enumerate(limits):
        remaining = budget - cumulative
        if remaining <= 0:
            return finalize(status="rejected", failure_type="canary_rejected",
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
            return finalize(status="rejected", failure_type="ProviderFailure",
                             failure_condition=condition)

        cost = _resolve_probe_cost(result, require_reported_accounting=require_reported_accounting)
        if cost is None:
            return finalize(status="rejected", failure_type="canary_rejected",
                             failure_condition="accounting_unavailable", cost_unknown=True)
        cumulative += cost
        probes.append(
            {
                "request_sha256": request.request_sha256,
                "max_output_tokens": limit,
                "resolved_model": result.resolved_model,
                "finish_reason": result.finish_reason,
                "input_tokens": result.input_tokens,
                "cached_input_tokens": result.cached_input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": cost,
            }
        )
        if result.finish_reason in _TRUNCATED_FINISH_REASONS:
            return finalize(status="rejected", failure_type="canary_rejected",
                             failure_condition="length")
        try:
            payload = json.loads(result.output_text)
        except json.JSONDecodeError:
            return finalize(status="rejected", failure_type="canary_rejected",
                             failure_condition="invalid_json_response")
        if payload != {"status": "ok"}:
            return finalize(status="rejected", failure_type="canary_rejected",
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
