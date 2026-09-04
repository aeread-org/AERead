"""Campaign-level provider-call pacing with an auditable treatment ledger."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Awaitable, Callable, Mapping

from aeread.shared_runner.task.execution import EvidenceIntegrityError


class PacedProviderClient:
    """Apply a frozen start-to-start cadence to each pinned provider route.

    The wrapper deliberately owns no retry policy. It schedules the one call
    requested by the shared runner and then delegates it unchanged, preserving
    the campaign's single-attempt and typed-missingness contracts.
    """

    def __init__(
        self,
        delegate: Any,
        *,
        minimum_interval_seconds_by_provider: Mapping[str, float],
        first_call_delay_seconds: float,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        intervals = dict(minimum_interval_seconds_by_provider)
        if not intervals or any(
            not isinstance(provider, str)
            or not provider
            or isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not math.isfinite(float(interval))
            or interval < 0
            for provider, interval in intervals.items()
        ):
            raise ValueError("provider pacing intervals must be finite non-negative values")
        if (
            isinstance(first_call_delay_seconds, bool)
            or not isinstance(first_call_delay_seconds, (int, float))
            or not math.isfinite(float(first_call_delay_seconds))
            or first_call_delay_seconds < 0
        ):
            raise ValueError("first-call pacing delay must be finite and non-negative")
        self._delegate = delegate
        self._intervals = {
            provider: float(interval) for provider, interval in intervals.items()
        }
        self._first_call_delay_seconds = float(first_call_delay_seconds)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        self._last_start_by_provider: dict[str, float] = {}
        self._locks = {provider: asyncio.Lock() for provider in self._intervals}
        self._observations: list[dict[str, Any]] = []

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    def pacing_summary_since(self, observation_index: int) -> dict[str, Any]:
        if not isinstance(observation_index, int) or not (
            0 <= observation_index <= len(self._observations)
        ):
            raise ValueError("pacing observation index is invalid")
        rows = self._observations[observation_index:]
        by_provider: dict[str, dict[str, Any]] = {}
        for row in rows:
            provider = row["provider"]
            aggregate = by_provider.setdefault(
                provider,
                {"provider_calls": 0, "pacing_wait_seconds": 0.0},
            )
            aggregate["provider_calls"] += 1
            aggregate["pacing_wait_seconds"] += row["pacing_wait_seconds"]
        for aggregate in by_provider.values():
            aggregate["pacing_wait_seconds"] = round(
                aggregate["pacing_wait_seconds"], 9
            )
        return {
            "provider_calls": len(rows),
            "paced_call_count": sum(
                row["pacing_wait_seconds"] > 0 for row in rows
            ),
            "pacing_wait_seconds": round(
                sum(row["pacing_wait_seconds"] for row in rows), 9
            ),
            "by_provider": dict(sorted(by_provider.items())),
        }

    async def complete(self, request: Any) -> Any:
        metadata = request.provider_metadata
        provider = (
            metadata.get("route_provider")
            if isinstance(metadata, Mapping)
            else None
        )
        if provider not in self._intervals:
            raise EvidenceIntegrityError(
                "paced campaign call does not resolve to a frozen provider route"
            )
        async with self._locks[provider]:
            now = self._clock()
            previous_start = self._last_start_by_provider.get(provider)
            required_wait = (
                self._first_call_delay_seconds
                if previous_start is None
                else max(0.0, self._intervals[provider] - (now - previous_start))
            )
            if required_wait > 0:
                await self._sleeper(required_wait)
            self._last_start_by_provider[provider] = self._clock()
            self._observations.append(
                {
                    "provider": provider,
                    "pacing_wait_seconds": required_wait,
                }
            )
        return await self._delegate.complete(request)
