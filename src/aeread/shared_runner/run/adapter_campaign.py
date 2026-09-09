"""Shared live-campaign primitives for external adapter first-light runs."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .resolver import canonical_json_bytes
from ..task.execution import ArenaChatClient, ProviderFailure, ProviderRequest

PROVIDER = "arena"
MODEL = "glm-5p2"
REVISION = "glm-5p2"
BASE_URL = "https://api.preview.arena.ai/v1"
ROUTE_PROVIDER = "Arena"
CANARY_MAX_OUTPUT_TOKENS = 512
CANARY_MAX_COST_USD = 0.01
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


class _CanaryRejected(ValueError):
    """A public, sanitized rejection produced by canary validation."""

    def __init__(self, condition: str) -> None:
        super().__init__(condition)
        self.condition = condition


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"refusing to replace different checkpoint: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def canary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["ok"]}},
        "required": ["status"],
        "additionalProperties": False,
    }


async def run_adapter_canary(
    *, family_id: str, checkpoint_path: Path, client: Any | None = None
) -> dict[str, Any]:
    """Run one unscored Arena route-admission probe and seal its result."""
    if checkpoint_path.exists():
        record = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("canary checkpoint is not an object")
        if record.get("family_id") != family_id:
            raise ValueError("canary checkpoint belongs to a different family")
        recorded = record.get("record_sha256")
        if recorded != _digest({k: v for k, v in record.items() if k != "record_sha256"}):
            raise ValueError("canary checkpoint digest mismatch")
        return record

    request = ProviderRequest(
        provider_call_id=f"{family_id}_glm5p2_arena_canary",
        provider=PROVIDER,
        base_url=BASE_URL,
        model=MODEL,
        revision=REVISION,
        instructions="Return only the requested JSON object.",
        input_text=(
            f"This is the unscored route-admission canary for {family_id}. "
            'Return {"status":"ok"}.'
        ),
        temperature=0.0,
        top_p=None,
        max_output_tokens=CANARY_MAX_OUTPUT_TOKENS,
        reasoning_effort="none",
        reasoning_token_budget=None,
        timeout_seconds=180.0,
        request_sha256="",
        max_cost_usd=CANARY_MAX_COST_USD,
        output_schema=canary_schema(),
        provider_metadata={
            "catalog_model_id": MODEL,
            "provider_cost_status": "response_reported",
        },
        seed=300,
    ).with_computed_hash()
    record: dict[str, Any] = {
        "schema_version": "aeread.adapter_route_canary/0.1",
        "family_id": family_id,
        "scored": False,
        "provider": PROVIDER,
        "model": MODEL,
        "revision": REVISION,
        "route_provider": ROUTE_PROVIDER,
        "request_sha256": request.request_sha256,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    result = None
    try:
        result = await (client or ArenaChatClient()).complete(request)
        finish_reason = result.finish_reason
        if finish_reason == "length":
            raise _CanaryRejected("truncated_response")
        if finish_reason != "stop":
            raise _CanaryRejected("unexpected_finish_reason")
        payload = json.loads(result.output_text)
        if payload != {"status": "ok"}:
            raise _CanaryRejected("invalid_response")
        cost = _validated_cost(result)
        if cost > CANARY_MAX_COST_USD:
            raise _CanaryRejected("cost_ceiling_exceeded")
        record.update(
            status="admitted",
            resolved_model=result.resolved_model,
            finish_reason=finish_reason,
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost,
        )
    except _CanaryRejected as error:
        record.update(
            status="rejected",
            failure_type="canary_rejected",
            failure_condition=error.condition,
            cost_usd=_safe_recorded_cost(result),
        )
    except json.JSONDecodeError:
        record.update(
            status="rejected",
            failure_type="canary_rejected",
            failure_condition="invalid_json_response",
            cost_usd=_safe_recorded_cost(result),
        )
    except TypeError:
        record.update(
            status="rejected",
            failure_type="canary_rejected",
            failure_condition="invalid_response",
            cost_usd=_safe_recorded_cost(result),
        )
    except ProviderFailure as error:
        condition = error.condition
        record.update(
            status="rejected",
            failure_type="provider_error",
            failure_condition=(
                condition
                if condition in _SAFE_PROVIDER_FAILURE_CONDITIONS
                else "provider_error"
            ),
            cost_usd=_safe_recorded_cost(result),
        )
    record["record_sha256"] = _digest(record)
    _write_once(checkpoint_path, record)
    return record


def _safe_recorded_cost(result: Any | None) -> float:
    """Return only a finite, non-negative provider cost for public records."""
    if result is None:
        return 0.0
    try:
        value = float(result.cost_usd or 0.0)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value >= 0 else 0.0


def _validated_cost(result: Any) -> float:
    try:
        value = float(result.cost_usd or 0.0)
    except (TypeError, ValueError) as error:
        raise _CanaryRejected("invalid_provider_cost") from error
    if not math.isfinite(value) or value < 0:
        raise _CanaryRejected("invalid_provider_cost")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    args = parser.parse_args(argv)
    record = asyncio.run(
        run_adapter_canary(family_id=args.family, checkpoint_path=args.checkpoint)
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "admitted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
