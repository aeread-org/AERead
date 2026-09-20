"""Phase 2 per-request reservations; interrupted dispatch requires an audit."""

from __future__ import annotations
import math
import hashlib
import asyncio
from aeread.shared_runner.task.execution import ProviderFailure
from aeread.shared_runner.run.resolver import canonical_json_bytes
from .continuous_execution import CampaignBudgetExceeded
from .model_campaign import _write_once_json
from .strategy_scaffold import GLM_PARASAIL_CANDIDATE
from .phase2_campaign import HARD_COST_CEILING_USD
from .phase2_controls import PROVIDER_TIMEOUT_SECONDS


class Phase2BudgetedProvider:
    """Reserve before every request; allow one identical 429/timeout retry.

    The runner owns action retries. Raising a typed failure with a floor of 60s
    makes its sealed backoff event carry the actual required delay. A second
    rejection, an excessive Retry-After, or any other error stops all dispatch.
    Interrupted runs cannot be restarted automatically, even after a 429.
    """

    def __init__(self, provider, root, *, baseline=0.0, ceiling=HARD_COST_CEILING_USD):
        if not (
            math.isfinite(baseline)
            and math.isfinite(ceiling)
            and 0 <= baseline < ceiling <= HARD_COST_CEILING_USD
        ):
            raise ValueError("invalid combined campaign budget")
        if list((root / "billing").glob("*.json")):
            raise RuntimeError(
                "existing billing requires audit; Phase 2 cannot be dispatched twice"
            )
        self.provider, self.root, self.ceiling = provider, root, ceiling
        self.spent, self.calls, self.stopped = baseline, [], False
        self.retry_request = None

    async def complete(self, request):
        if self.stopped:
            raise CampaignBudgetExceeded("campaign dispatch stopped")
        route = GLM_PARASAIL_CANDIDATE.route
        if (
            request.model != route.model
            or request.revision != route.revision
            or (request.provider_metadata or {}).get("route_provider")
            != route.route_provider
        ):
            self.stopped = True
            raise ValueError("request differs from frozen route")
        retrying = self.retry_request is not None
        if retrying and request.request_sha256 != self.retry_request:
            self.stopped = True
            raise ValueError("retry changed the logical action request")
        input_ceiling = (
            len(
                canonical_json_bytes(
                    {
                        "instructions": request.instructions,
                        "input": request.input_text,
                        "schema": request.output_schema,
                        "messages": request.messages,
                        "tools": request.tools,
                    }
                )
            )
            + 2048
        )
        reserve = (
            input_ceiling * route.pricing.input_per_million
            + request.max_output_tokens * route.pricing.output_per_million
        ) / 1_000_000
        if self.spent + reserve > self.ceiling:
            self.stopped = True
            raise CampaignBudgetExceeded(
                "next request cannot fit combined hard ceiling"
            )
        ordinal = len(self.calls)
        pending = {
            "request_sha256": request.request_sha256,
            "provider_call_id": request.provider_call_id,
            "reserved_cost_usd": reserve,
            "retry_of_previous_request": retrying,
        }
        _write_once_json(self.root / "billing" / f"pending_{ordinal:05d}.json", pending)
        path = self.root / "billing" / f"call_{ordinal:05d}.json"
        self.spent += reserve
        self.calls.append(path)
        try:
            try:
                result = await asyncio.wait_for(
                    self.provider.complete(request), timeout=PROVIDER_TIMEOUT_SECONDS
                )
            except (asyncio.TimeoutError, TimeoutError) as error:
                # Finish inside the harness deadline so its declared retry
                # owner receives a typed error. External cancellation is not
                # converted and still stops dispatch in the outer handler.
                raise ProviderFailure(
                    "timeout", f"provider request timed out (limit {PROVIDER_TIMEOUT_SECONDS}s): {error}",
                    retryable=True,
                ) from error
        except BaseException as error:
            # Billing is private run evidence. Public exports retain the digest,
            # not the message, which may contain account or request details.
            original_message = str(error)
            provider_failure = {
                "exception_type": type(error).__name__,
                "message": original_message,
                "message_sha256": hashlib.sha256(original_message.encode()).hexdigest(),
                "condition": getattr(error, "condition", None),
                "status_code": getattr(error, "status_code", None),
                "retryable": getattr(error, "retryable", None),
            }
            explicit_429 = (
                isinstance(error, ProviderFailure)
                and error.condition == "rate_limit"
                and error.status_code == 429
            )
            timeout = isinstance(error, ProviderFailure) and error.condition == "timeout"
            delay = (
                max(60.0, error.retry_after_seconds or 0.0) if explicit_429 or timeout else None
            )
            allowed = (
                (explicit_429 or timeout) and error.retryable and not retrying and delay <= 180.0
            )
            self.stopped = not allowed
            self.retry_request = request.request_sha256 if allowed else None
            _write_once_json(
                path,
                {
                    **pending,
                    "status": (
                        "rejected_429_billing_unknown"
                        if explicit_429
                        else "unknown_provider_outcome"
                    ),
                    "cost_usd": None,
                    "provider_failure": provider_failure,
                    "retry_permitted": allowed,
                    "required_retry_delay_seconds": delay,
                    "provider_retry_after_seconds": (
                        error.retry_after_seconds if explicit_429 else None
                    ),
                },
            )
            if explicit_429 or timeout:
                raise ProviderFailure(
                    error.condition,
                    original_message,
                    retryable=allowed,
                    status_code=error.status_code,
                    retry_after_seconds=delay,
                ) from error
            raise
        cost = result.cost_usd
        valid = (
            isinstance(cost, (float, int))
            and not isinstance(cost, bool)
            and math.isfinite(cost)
            and cost >= 0
        )
        _write_once_json(
            path,
            {
                **pending,
                "status": "settled" if valid else "unknown_provider_cost",
                "cost_usd": cost if valid else None,
                "resolved_model": result.resolved_model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
        if not valid:
            self.stopped = True
            raise RuntimeError("provider omitted valid billing")
        self.spent += cost - reserve
        self.retry_request = None
        if (
            cost > reserve + 1e-10
            or self.spent > self.ceiling + 1e-10
            or result.resolved_model != route.revision
        ):
            self.stopped = True
            raise RuntimeError(
                "charge or resolved revision violated the frozen contract"
            )
        return result
