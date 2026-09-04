"""Campaign-level completion-to-next-start provider cooldown with a ledger."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Awaitable, Callable, Mapping

from aeread.shared_runner.task.execution import EvidenceIntegrityError


class CooldownProviderClient:
    """Apply a frozen completion-to-next-start cooldown to each pinned route.

    The V12 start-to-start scheduler let a slow call be followed immediately by
    the next one because the interval was measured from the previous start.
    This wrapper measures from the previous call's completion (success or
    failure) and serialises calls per provider, so no two calls to one route
    overlap and every call begins at least ``cooldown_seconds`` after the last
    one ended. It owns no retry policy: it schedules exactly the one call the
    shared runner requested and delegates it unchanged.
    """

    def __init__(
        self,
        delegate: Any,
        *,
        cooldown_seconds_by_provider: Mapping[str, float],
        first_call_delay_seconds: float,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        cooldowns = dict(cooldown_seconds_by_provider)
        if not cooldowns or any(
            not isinstance(provider, str)
            or not provider
            or isinstance(cooldown, bool)
            or not isinstance(cooldown, (int, float))
            or not math.isfinite(float(cooldown))
            or cooldown < 0
            for provider, cooldown in cooldowns.items()
        ):
            raise ValueError("provider cooldowns must be finite non-negative values")
        if (
            isinstance(first_call_delay_seconds, bool)
            or not isinstance(first_call_delay_seconds, (int, float))
            or not math.isfinite(float(first_call_delay_seconds))
            or first_call_delay_seconds < 0
        ):
            raise ValueError("first-call cooldown delay must be finite and non-negative")
        self._delegate = delegate
        self._cooldowns = {
            provider: float(cooldown) for provider, cooldown in cooldowns.items()
        }
        self._first_call_delay_seconds = float(first_call_delay_seconds)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        self._last_completion_by_provider: dict[str, float] = {}
        self._locks = {provider: asyncio.Lock() for provider in self._cooldowns}
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
        if provider not in self._cooldowns:
            raise EvidenceIntegrityError(
                "cooldown campaign call does not resolve to a frozen provider route"
            )
        async with self._locks[provider]:
            now = self._clock()
            previous_completion = self._last_completion_by_provider.get(provider)
            required_wait = (
                self._first_call_delay_seconds
                if previous_completion is None
                else max(
                    0.0, self._cooldowns[provider] - (now - previous_completion)
                )
            )
            if required_wait > 0:
                await self._sleeper(required_wait)
            self._observations.append(
                {
                    "provider": provider,
                    "pacing_wait_seconds": required_wait,
                }
            )
            try:
                return await self._delegate.complete(request)
            finally:
                self._last_completion_by_provider[provider] = self._clock()
