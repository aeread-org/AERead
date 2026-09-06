"""Bounded-concurrency provider pacing with an auditable treatment ledger."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Awaitable, Callable, Mapping

from aeread.shared_runner.task.execution import EvidenceIntegrityError


class BoundedConcurrencyProviderClient:
    """Pace a pinned route by start spacing while allowing bounded overlap.

    The completion-to-start cooldown holds one lock for the whole call, so no
    two calls to a provider ever overlap and campaign throughput is capped at
    one call per response. When both models share a provider that single lock
    serialises the entire campaign, which projected to days of wall time for
    the designed panel.

    This policy keeps the two protections that matter and drops the one that
    only cost time. Consecutive call *starts* are spaced, so a burst can never
    be issued back to back, and the number of calls in flight on a route is
    capped, so the offered rate has a hard ceiling. Unlike the start-to-start
    scheduler that V12 rejected, spacing here is enforced even when the
    previous call is still running, so a slow call cannot be followed
    instantly by the next one.

    The wrapper owns no retry policy. It schedules the one call the shared
    runner requested and delegates it unchanged.
    """

    def __init__(
        self,
        delegate: Any,
        *,
        minimum_start_interval_seconds_by_provider: Mapping[str, float],
        maximum_concurrent_calls_by_provider: Mapping[str, int],
        first_call_delay_seconds: float,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        intervals = dict(minimum_start_interval_seconds_by_provider)
        limits = dict(maximum_concurrent_calls_by_provider)
        if not intervals or any(
            not isinstance(provider, str)
            or not provider
            or isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not math.isfinite(float(interval))
            or interval < 0
            for provider, interval in intervals.items()
        ):
            raise ValueError("start intervals must be finite non-negative values")
        if set(limits) != set(intervals) or any(
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
            for limit in limits.values()
        ):
            raise ValueError(
                "every paced provider needs a positive concurrent-call limit"
            )
        if (
            isinstance(first_call_delay_seconds, bool)
            or not isinstance(first_call_delay_seconds, (int, float))
            or not math.isfinite(float(first_call_delay_seconds))
            or first_call_delay_seconds < 0
        ):
            raise ValueError("first-call delay must be finite and non-negative")
        self._delegate = delegate
        self._intervals = {
            provider: float(interval) for provider, interval in intervals.items()
        }
        self._limits = {provider: int(limit) for provider, limit in limits.items()}
        self._first_call_delay_seconds = float(first_call_delay_seconds)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        self._last_start_by_provider: dict[str, float] = {}
        self._start_locks = {provider: asyncio.Lock() for provider in self._intervals}
        self._slots = {
            provider: asyncio.Semaphore(limit)
            for provider, limit in self._limits.items()
        }
        self._observations: list[dict[str, Any]] = []
        self._peak_in_flight: dict[str, int] = {}
        self._in_flight: dict[str, int] = {}

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
        for provider, aggregate in by_provider.items():
            aggregate["pacing_wait_seconds"] = round(
                aggregate["pacing_wait_seconds"], 9
            )
            aggregate["peak_in_flight"] = self._peak_in_flight.get(provider, 0)
        return {
            "provider_calls": len(rows),
            "paced_call_count": sum(row["pacing_wait_seconds"] > 0 for row in rows),
            "pacing_wait_seconds": round(
                sum(row["pacing_wait_seconds"] for row in rows), 9
            ),
            "by_provider": dict(sorted(by_provider.items())),
        }

    async def complete(self, request: Any) -> Any:
        metadata = request.provider_metadata
        provider = (
            metadata.get("route_provider") if isinstance(metadata, Mapping) else None
        )
        if provider not in self._intervals:
            raise EvidenceIntegrityError(
                "paced campaign call does not resolve to a frozen provider route"
            )
        async with self._slots[provider]:
            async with self._start_locks[provider]:
                now = self._clock()
                previous_start = self._last_start_by_provider.get(provider)
                required_wait = (
                    self._first_call_delay_seconds
                    if previous_start is None
                    else max(
                        0.0, self._intervals[provider] - (now - previous_start)
                    )
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
            in_flight = self._in_flight.get(provider, 0) + 1
            self._in_flight[provider] = in_flight
            self._peak_in_flight[provider] = max(
                self._peak_in_flight.get(provider, 0), in_flight
            )
            try:
                return await self._delegate.complete(request)
            finally:
                self._in_flight[provider] = self._in_flight.get(provider, 1) - 1
