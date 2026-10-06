"""What one episode attempt spent, read from its event log.

A cell that failed after paid calls still spent money. Two families fixed
totals that omitted it, each in its own driver (DC-T-13, E-J-03), and a
third still reports no spend for a case killed after successful turns. The
event log already records every provider call's terminal cost, so the kernel
reads it once here, for completed and failed attempts alike, and says when
the figure is a lower bound instead of silently summing what it found.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .execution import Event, EvidenceIntegrityError, EvidenceStore

EXACT = "exact"
LOWER_BOUND = "lower_bound"

_TERMINAL_EVENTS = frozenset(
    {"provider_call_succeeded", "provider_call_failed", "provider_call_outcome_unknown"}
)


@dataclass(frozen=True, slots=True)
class AttemptSpend:
    """Recorded spend of one attempt, or of several added together.

    ``cost_accounting`` is ``lower_bound`` whenever any provider call has no
    known cost: its outcome is unknown, it never reached a terminal event,
    or its terminal event carries no usable figure. ``unsettled_call_count``
    is how many such calls there are.
    """

    cost_usd: float
    cost_accounting: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    provider_call_count: int
    unsettled_call_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "cost_usd": self.cost_usd,
            "cost_accounting": self.cost_accounting,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "provider_call_count": self.provider_call_count,
            "unsettled_call_count": self.unsettled_call_count,
        }


def _known_cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    cost = float(value)
    return cost if math.isfinite(cost) and cost >= 0 else None


def _token_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


class _EventLog:
    """An attempt directory read as it stands, reconciled or not.

    ``EvidenceStore.audit_existing`` refuses a log in which a started call
    has no terminal event, which is exactly the log an interrupted attempt
    leaves and exactly the one whose spend is being asked for. Each payload
    is still checked against the digest its event records.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._events_path = root / "events.jsonl"
        if root.is_symlink() or not self._events_path.is_file():
            raise EvidenceIntegrityError(f"no event log at {root}")

    def read_events(self) -> tuple[Event, ...]:
        events: list[Event] = []
        lines = self._events_path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            try:
                events.append(Event(**json.loads(line)))
            except Exception as error:
                raise EvidenceIntegrityError(
                    f"invalid event at line {line_number}: {error}"
                ) from error
        return tuple(events)

    def read_event_payload(self, event: Event) -> Any:
        path = self._root / event.payload_ref
        if path.is_symlink() or not path.is_file():
            raise EvidenceIntegrityError(f"unsafe or missing artifact: {event.payload_ref}")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != event.payload_sha256:
            raise EvidenceIntegrityError(
                f"payload artifact hash mismatch for {event.event_id}"
            )
        return json.loads(payload)


def _spend_of(store: "EvidenceStore | _EventLog") -> AttemptSpend:
    started: list[str] = []
    settled: dict[str, float] = {}
    terminal: set[str] = set()
    tokens = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for event in store.read_events():
        call_id = event.provider_call_id
        if call_id is None:
            continue
        if event.event_type == "provider_call_started":
            started.append(call_id)
            continue
        if event.event_type not in _TERMINAL_EVENTS:
            continue
        terminal.add(call_id)
        payload = store.read_event_payload(event)
        if not isinstance(payload, Mapping):
            continue
        cost = (
            None
            if event.event_type == "provider_call_outcome_unknown"
            else _known_cost(payload.get("cost_usd"))
        )
        if cost is not None:
            settled[call_id] = settled.get(call_id, 0.0) + cost
        # A completed call reports usage on its result; a failed call that
        # was billed reports it on the event itself.
        usage = payload.get("provider_result")
        usage = usage if isinstance(usage, Mapping) else payload
        for field in tokens:
            tokens[field] += _token_count(usage.get(field))
    calls = set(started) | terminal
    unsettled = len(calls - set(settled))
    return AttemptSpend(
        cost_usd=math.fsum(settled.values()),
        cost_accounting=EXACT if unsettled == 0 else LOWER_BOUND,
        provider_call_count=len(calls),
        unsettled_call_count=unsettled,
        **tokens,
    )


def attempt_spend(evidence: EvidenceStore | str | Path) -> AttemptSpend:
    """Spend of one episode attempt, from an open store or its directory.

    Works on a failed attempt exactly as on a completed one, sealed or not,
    and on an attempt that was interrupted: it reads the event log, not a
    receipt. A call the log never closed is unsettled.
    """

    if isinstance(evidence, EvidenceStore):
        return _spend_of(evidence)
    return _spend_of(_EventLog(Path(evidence)))


def total_spend(spends: Iterable[AttemptSpend]) -> AttemptSpend:
    """Add attempts together; one lower bound makes the total a lower bound."""

    items = tuple(spends)
    unsettled = sum(item.unsettled_call_count for item in items)
    exact = all(item.cost_accounting == EXACT for item in items)
    return AttemptSpend(
        cost_usd=math.fsum(item.cost_usd for item in items),
        cost_accounting=EXACT if exact and unsettled == 0 else LOWER_BOUND,
        input_tokens=sum(item.input_tokens for item in items),
        cached_input_tokens=sum(item.cached_input_tokens for item in items),
        output_tokens=sum(item.output_tokens for item in items),
        provider_call_count=sum(item.provider_call_count for item in items),
        unsettled_call_count=unsettled,
    )


__all__ = ["EXACT", "LOWER_BOUND", "AttemptSpend", "attempt_spend", "total_spend"]
