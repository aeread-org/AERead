"""Shared live-campaign primitives for external adapter first-light runs."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .run.resolver import canonical_json_bytes
from .task.execution import ArenaChatClient, ProviderRequest

PROVIDER = "arena"
MODEL = "glm-5p2"
REVISION = "glm-5p2"
BASE_URL = "https://api.preview.arena.ai/v1"
ROUTE_PROVIDER = "Arena"
CANARY_MAX_OUTPUT_TOKENS = 512
CANARY_MAX_COST_USD = 0.01


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
        payload = json.loads(result.output_text)
        if payload != {"status": "ok"}:
            raise ValueError("canary response did not match the sealed admission value")
        cost = float(result.cost_usd or 0.0)
        if cost > CANARY_MAX_COST_USD:
            raise ValueError("canary exceeded its cost ceiling")
        record.update(
            status="admitted",
            resolved_model=result.resolved_model,
            finish_reason=result.finish_reason,
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost,
        )
    except Exception as error:  # typed checkpoint; caller decides whether to stop
        record.update(
            status="rejected",
            failure_type=type(error).__name__,
            failure_condition=getattr(error, "condition", "canary_rejected"),
            cost_usd=float(result.cost_usd or 0.0) if result is not None else 0.0,
        )
    record["record_sha256"] = _digest(record)
    _write_once(checkpoint_path, record)
    return record


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
