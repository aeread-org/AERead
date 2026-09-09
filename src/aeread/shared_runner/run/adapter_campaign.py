"""Shared live-campaign primitives for external adapter first-light runs."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .resolver import canonical_json_bytes
from ..task.execution import ArenaChatClient, ProviderFailure, ProviderRequest

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


@dataclass(frozen=True)
class AdapterCanarySpec:
    """Sealed, adapter-owned controls for one route-admission canary."""

    family_id: str
    provider: str
    model: str
    revision: str
    base_url: str
    route_provider: str
    max_output_tokens: int
    max_cost_usd: float

    def __post_init__(self) -> None:
        for field in (
            "family_id",
            "provider",
            "model",
            "revision",
            "base_url",
            "route_provider",
        ):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise ValueError(f"canary spec {field} must be non-empty")
        if not isinstance(self.max_output_tokens, int) or self.max_output_tokens <= 0:
            raise ValueError("canary spec max_output_tokens must be positive")
        if (
            isinstance(self.max_cost_usd, bool)
            or not math.isfinite(self.max_cost_usd)
            or self.max_cost_usd < 0
        ):
            raise ValueError("canary spec max_cost_usd must be finite and non-negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "provider": self.provider,
            "model": self.model,
            "revision": self.revision,
            "base_url": self.base_url,
            "route_provider": self.route_provider,
            "max_output_tokens": self.max_output_tokens,
            "max_cost_usd": self.max_cost_usd,
        }

    @property
    def spec_sha256(self) -> str:
        return _digest(self.as_dict())


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(f"refusing to replace different checkpoint: {path}")
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def canary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["ok"]}},
        "required": ["status"],
        "additionalProperties": False,
    }


async def run_adapter_canary(
    *,
    spec: AdapterCanarySpec,
    plan_sha256: str,
    checkpoint_path: Path,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run one unscored Arena route-admission probe and seal its result."""
    if not isinstance(plan_sha256, str) or not plan_sha256:
        raise ValueError("plan_sha256 must be a non-empty string")
    request = ProviderRequest(
        provider_call_id=f"{spec.family_id}_{spec.model}_canary",
        provider=spec.provider,
        base_url=spec.base_url,
        model=spec.model,
        revision=spec.revision,
        instructions="Return only the requested JSON object.",
        input_text=(
            f"This is the unscored route-admission canary for {spec.family_id}. "
            'Return {"status":"ok"}.'
        ),
        temperature=0.0,
        top_p=None,
        max_output_tokens=spec.max_output_tokens,
        reasoning_effort="none",
        reasoning_token_budget=None,
        timeout_seconds=180.0,
        request_sha256="",
        max_cost_usd=spec.max_cost_usd,
        output_schema=canary_schema(),
        provider_metadata={
            "catalog_model_id": spec.model,
            "provider_cost_status": "response_reported",
        },
        seed=300,
    ).with_computed_hash()
    resume_binding = {
        "family_id": spec.family_id,
        "plan_sha256": plan_sha256,
        "spec_sha256": spec.spec_sha256,
        "request_sha256": request.request_sha256,
        "provider": spec.provider,
        "model": spec.model,
        "revision": spec.revision,
    }
    if checkpoint_path.exists():
        record = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("canary checkpoint is not an object")
        for field, expected in resume_binding.items():
            if record.get(field) != expected:
                if field == "family_id":
                    raise ValueError("canary checkpoint belongs to a different family")
                raise ValueError(f"canary checkpoint does not match {field}")
        recorded = record.get("record_sha256")
        if recorded != _digest({k: v for k, v in record.items() if k != "record_sha256"}):
            raise ValueError("canary checkpoint digest mismatch")
        return record
    record: dict[str, Any] = {
        "schema_version": "aeread.adapter_route_canary/0.1",
        **resume_binding,
        "scored": False,
        "route_provider": spec.route_provider,
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
        if cost > spec.max_cost_usd:
            raise _CanaryRejected("cost_ceiling_exceeded")
        record.update(
            status="admitted",
            resolved_model=result.resolved_model,
            finish_reason=finish_reason,
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost,
            cost_accounting_state="reported",
        )
    except _CanaryRejected as error:
        record.update(
            status="rejected",
            failure_type="canary_rejected",
            failure_condition=error.condition,
            **_cost_record(result),
        )
    except json.JSONDecodeError:
        record.update(
            status="rejected",
            failure_type="canary_rejected",
            failure_condition="invalid_json_response",
            **_cost_record(result),
        )
    except asyncio.TimeoutError:
        record.update(
            status="rejected",
            failure_type="provider_error",
            failure_condition="timeout",
            **_cost_record(result),
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
            **_cost_record(result),
        )
    record["record_sha256"] = _digest(record)
    _write_once(checkpoint_path, record)
    return record


def _safe_recorded_cost(result: Any | None) -> float | None:
    """Return a provider cost only when it is known and valid."""
    if result is None:
        return None
    try:
        raw = result.cost_usd
        if raw is None or isinstance(raw, bool):
            return None
        value = float(raw)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value >= 0 else None


def _cost_record(result: Any | None) -> dict[str, Any]:
    cost = _safe_recorded_cost(result)
    return {
        "cost_usd": cost,
        "cost_accounting_state": "reported" if cost is not None else "unknown",
    }


def _validated_cost(result: Any) -> float:
    raw = result.cost_usd
    if raw is None or isinstance(raw, bool):
        raise _CanaryRejected("cost_unreported")
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise _CanaryRejected("invalid_provider_cost") from error
    if not math.isfinite(value) or value < 0:
        raise _CanaryRejected("invalid_provider_cost")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--route-provider", required=True)
    parser.add_argument("--max-output-tokens", required=True, type=int)
    parser.add_argument("--max-cost-usd", required=True, type=float)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    args = parser.parse_args(argv)
    spec = AdapterCanarySpec(
        family_id=args.family,
        provider=args.provider,
        model=args.model,
        revision=args.revision,
        base_url=args.base_url,
        route_provider=args.route_provider,
        max_output_tokens=args.max_output_tokens,
        max_cost_usd=args.max_cost_usd,
    )
    record = asyncio.run(
        run_adapter_canary(
            spec=spec,
            plan_sha256=args.plan_sha256,
            checkpoint_path=args.checkpoint,
        )
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "admitted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
