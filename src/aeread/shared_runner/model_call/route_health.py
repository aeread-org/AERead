"""Route health shared by the cells of one process (S5, #226 items 1, 3, 4).

A profile that declares ``route_policy: "route_v1"`` shares one `RouteHealth`
per route key with every other cell the process runs: a consecutive-failure
breaker with an escalating cooldown, a provider-requested pause (a 429
``Retry-After``) honoured route-wide and uncapped, and an outage bound
enforced by time. The state lives in one process; nothing here coordinates
across processes.

Every operation is synchronous, so it is atomic on the event loop, and total:
it never raises on a declared policy. An absent deadline (``None``) counts as
negative infinity in every comparison, written as an explicit ``is None``
check, since a deadline of 0.0 is a valid clock reading.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping

from ..schemas import AgentProfile
from ..task.execution import (
    EvidenceIntegrityError,
    RoutePolicy,
    declared_route_policy,
    route_health_key,
)

# Outcomes the breaker counts. Anything else, and every interruption, is ignored.
_TRANSIENT_CONDITIONS = frozenset({"rate_limit", "provider_5xx", "timeout", "transport"})


# The clock and the sleep behind a route wait, as module functions looked up at
# call time so a test can replace both without waiting.
def _route_monotonic() -> float:
    return time.monotonic()


async def _route_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def terminal_ref(
    episode_attempt_id: str, provider_call_id: str, condition: str
) -> dict[str, str]:
    """The terminal a deadline came from, named by episode attempt and call.

    Provider-call ids repeat across the episode attempts of one cell, so the
    episode attempt is part of the name.
    """

    return {
        "episode_attempt_id": episode_attempt_id,
        "provider_call_id": provider_call_id,
        "condition": condition,
    }


class RouteHealth:
    """One route's breaker, pause and outage state."""

    def __init__(self, policy: RoutePolicy) -> None:
        self.policy = policy
        self.outage_start: float | None = None
        self.failures = 0
        self.cooldown = policy.cooldown_seconds
        self.cooldown_until: float | None = None
        self.pause_until: float | None = None
        self.exhausted: str | None = None
        # The terminal that set the deadline now held. Each is replaced only
        # when its own deadline is, so the snapshot never names a terminal that
        # did not set the deadline a cell met.
        self.cooldown_ref: Mapping[str, str] | None = None
        self.pause_ref: Mapping[str, str] | None = None

    def _expire(self, now: float) -> None:
        # Time first: a running call that succeeds after the bound must not
        # revive the route, so every operation starts here.
        if (
            self.exhausted is None
            and self.outage_start is not None
            and now - self.outage_start >= self.policy.max_outage_seconds
        ):
            self.exhausted = "outage_bound_reached"

    def _later_deadline(self) -> float | None:
        if self.cooldown_until is None:
            return self.pause_until
        if self.pause_until is None:
            return self.cooldown_until
        return max(self.cooldown_until, self.pause_until)

    def _pause_is_later(self) -> bool:
        """Whether the pause is the later deadline; ties go to the pause."""

        return self.pause_until is not None and (
            self.cooldown_until is None or self.pause_until >= self.cooldown_until
        )

    def admits(self) -> bool:
        now = _route_monotonic()
        self._expire(now)
        if self.exhausted is not None:
            return False
        later = self._later_deadline()
        return later is None or now >= later

    def route_wait(self) -> float:
        """Seconds until both deadlines have passed; 0 when none is pending."""

        now = _route_monotonic()
        self._expire(now)
        later = self._later_deadline()
        return 0.0 if later is None or later <= now else later - now

    def wake_in(self) -> float:
        """How long a waiter sleeps: to the later deadline, or the outage bound if sooner.

        The bound is what wakes a waiter to fail when no other event arrives.
        """

        now = _route_monotonic()
        self._expire(now)
        wake = self._later_deadline()
        if wake is None:
            return 0.0
        if self.outage_start is not None:
            wake = min(wake, self.outage_start + self.policy.max_outage_seconds)
        return max(wake - now, 0.0)

    def report(
        self,
        *,
        condition: str | None = None,
        success: bool = False,
        retry_after_seconds: float | None = None,
        ref: Mapping[str, str] | None = None,
    ) -> None:
        """Apply one provider terminal as one combined update."""

        now = _route_monotonic()
        self._expire(now)
        if self.exhausted is not None:
            return
        if success:
            self._report_success(now)
        elif condition in _TRANSIENT_CONDITIONS:
            self._report_transient(now, condition, retry_after_seconds, ref)

    def _report_success(self, now: float) -> None:
        self.failures = 0
        self.cooldown_until = None
        self.cooldown_ref = None
        self.cooldown = self.policy.cooldown_seconds
        # A success never shortens a provider-requested pause that is still live.
        if self.pause_until is None or now >= self.pause_until:
            self.pause_until = None
            self.pause_ref = None
            self.outage_start = None

    def _report_transient(
        self,
        now: float,
        condition: str | None,
        retry_after_seconds: float | None,
        ref: Mapping[str, str] | None,
    ) -> None:
        self.failures += 1
        breaker: float | None = None
        pause: float | None = None
        if self.failures >= self.policy.open_after_failures:
            breaker = now + self.cooldown
            # Doubling a value already at most the cap cannot overflow.
            self.cooldown = min(self.cooldown * 2, self.policy.cooldown_cap_seconds)
            self.failures = 0
        # A 429 that also crosses the threshold applies both rules once, so
        # the cooldown doubles once, not twice.
        if (
            condition == "rate_limit"
            and retry_after_seconds is not None
            and retry_after_seconds > 0
        ):
            pause = now + retry_after_seconds
        if breaker is not None and (self.cooldown_until is None or breaker > self.cooldown_until):
            self.cooldown_until = breaker
            self.cooldown_ref = ref
        if pause is not None and (self.pause_until is None or pause > self.pause_until):
            self.pause_until = pause
            self.pause_ref = ref
        if breaker is None and pause is None:
            return
        if self.outage_start is None:
            self.outage_start = now
        later = self._later_deadline()
        if later is not None and later >= self.outage_start + self.policy.max_outage_seconds:
            self.exhausted = (
                "pause_past_outage_bound"
                if self._pause_is_later()
                else "cooldown_past_outage_bound"
            )

    def snapshot(self) -> dict[str, Any]:
        """The state as event evidence; times are seconds relative to now."""

        now = _route_monotonic()
        self._expire(now)
        pause_live = (
            self.pause_until is not None
            and self.pause_until > now
            and (self.cooldown_until is None or self.pause_until >= self.cooldown_until)
        )
        if self.exhausted is not None:
            state = "exhausted"
        elif pause_live:
            state = "paused"
        elif self.cooldown_until is not None and self.cooldown_until > now:
            state = "cooling"
        elif self.outage_start is not None:
            state = "recovering"
        else:
            state = "closed"
        if state == "paused":
            cause_ref = self.pause_ref
        elif state == "cooling":
            cause_ref = self.cooldown_ref
        elif state in {"recovering", "exhausted"}:
            cause_ref = self.pause_ref if self._pause_is_later() else self.cooldown_ref
        else:
            cause_ref = None
        return {
            "state": state,
            "cooldown_until_in": (
                None if self.cooldown_until is None else self.cooldown_until - now
            ),
            "pause_until_in": None if self.pause_until is None else self.pause_until - now,
            "outage_age": None if self.outage_start is None else now - self.outage_start,
            "failures": self.failures,
            "cooldown": self.cooldown,
            "exhausted": self.exhausted,
            "cause_ref": None if cause_ref is None else dict(cause_ref),
        }


class RouteHealthRegistry:
    """The `RouteHealth` of every route key a process has used.

    Created once per process by the caller and handed to ``execute_plan_cell``.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str | None, str, str], RouteHealth] = {}

    def health_for(self, profile: AgentProfile) -> RouteHealth:
        """The route's health, created on first use.

        Profiles on one key must declare the same policy: two policies for one
        route would leave its breaker meaning whichever cell reported last.
        """

        policy = declared_route_policy(profile)
        if policy is None:
            raise EvidenceIntegrityError(
                f"profile {profile.profile_id!r} does not declare route_v1"
            )
        key = route_health_key(profile)
        health = self._by_key.get(key)
        if health is None:
            health = self._by_key[key] = RouteHealth(policy)
        elif health.policy != policy:
            raise EvidenceIntegrityError(
                f"profile {profile.profile_id!r} declares a route policy that differs "
                "from another profile's on the same route"
            )
        return health
