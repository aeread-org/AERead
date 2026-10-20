"""Invocation-scoped campaign admission and completion-order operational halts.

Reserves govern admission, never accounting. A halt drains started work. The
caller persists each actual result before its reserve is released or another
cell can be admitted. There is deliberately no resume or provider-dollar cap.
"""
from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .halt import CellOutcome, OperationalHaltGuard
from ..task.spend import AttemptSpend, total_spend


@dataclass(frozen=True, slots=True)
class PlannedCell:
    cell_key: str
    arm_key: str

    def __post_init__(self) -> None:
        for value in (self.cell_key, self.arm_key):
            if not isinstance(value, str) or not value:
                raise ValueError('cell and arm keys must be non-empty strings')


@dataclass(frozen=True, slots=True)
class CampaignControls:
    cost_limit_usd: float
    per_cell_reserve_usd: float
    concurrency: int
    max_consecutive_operational_failures: int

    def __post_init__(self) -> None:
        for value in (self.cost_limit_usd, self.per_cell_reserve_usd):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError('campaign dollar controls must be finite and positive')
        for value in (self.concurrency, self.max_consecutive_operational_failures):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError('campaign concurrency and streak limit must be positive integers')


@dataclass(frozen=True, slots=True)
class CriticalStop:
    condition: str

    def __post_init__(self) -> None:
        if self.condition not in {'critical_route_or_replay_failure', 'critical_execution_failure'}:
            raise ValueError('unsupported family critical stop')


@dataclass(frozen=True, slots=True)
class CellResult:
    status: str
    payload: Mapping[str, Any]
    spend: AttemptSpend
    outcome: CellOutcome
    critical_stop: CriticalStop | None = None

    def __post_init__(self) -> None:
        if self.status not in {'completed', 'attempted_failure'}:
            raise ValueError('invalid attempted cell status')
        if not isinstance(self.outcome, CellOutcome) or not self.outcome.attempted_now:
            raise ValueError('controlled campaigns require a fresh CellOutcome')
        if self.outcome.operational_failure != (self.status == 'attempted_failure'):
            raise ValueError('cell status and outcome differ')
        if not isinstance(self.spend, AttemptSpend):
            raise TypeError('cell spending must be canonical AttemptSpend')
        if (not math.isfinite(self.spend.cost_usd) or self.spend.cost_usd < 0
                or self.spend.cost_accounting not in {'exact', 'lower_bound'}):
            raise ValueError('invalid attempt spending')
        if not isinstance(self.payload, Mapping) or not self.payload.get('receipt_sha256'):
            raise ValueError('attempted cell must identify its real receipt')


@dataclass(frozen=True, slots=True)
class ControlledRun:
    results: tuple[tuple[PlannedCell, CellResult], ...]
    not_attempted: tuple[PlannedCell, ...]
    spend: AttemptSpend
    halt: Mapping[str, Any] | None


async def run_controlled_cells(
    planned: Sequence[PlannedCell],
    execute: Callable[[PlannedCell], Awaitable[CellResult]],
    *,
    controls: CampaignControls,
    persist: Callable[[PlannedCell, CellResult], Any],
) -> ControlledRun:
    """Execute only admitted cells; retain and persist in-flight work on halt.

    Unexpected errors propagate after draining. The caller must report an
    incomplete invocation instead of publishing a completed summary then.
    """
    cells = tuple(planned)
    if not all(isinstance(cell, PlannedCell) for cell in cells):
        raise TypeError('planned cells must be typed')
    if len({cell.cell_key for cell in cells}) != len(cells):
        raise ValueError('planned cell keys must be unique')
    guard = OperationalHaltGuard(controls.max_consecutive_operational_failures)
    active: dict[str, asyncio.Task[None]] = {}
    finished: asyncio.Queue[tuple[PlannedCell, CellResult | None, BaseException | None]] = asyncio.Queue()
    results: list[tuple[PlannedCell, CellResult]] = []
    next_index = 0
    halt: dict[str, Any] | None = None
    error: BaseException | None = None

    def spending() -> AttemptSpend:
        return total_spend(result.spend for _, result in results)

    def stop(condition: str, after_cell: str | None) -> None:
        nonlocal halt
        if halt is None:
            halt = {
                'condition': condition, 'after_cell': after_cell,
                'scope': 'campaign_invocation',
                'in_flight_at_trigger': [key for key in active if key != after_cell],
                'known_spend_at_trigger': spending().as_dict(),
                'consecutive_operational_failures': guard.streak,
            }

    async def invoke(cell: PlannedCell) -> None:
        try:
            value = await execute(cell)
            if not isinstance(value, CellResult):
                raise TypeError('execute must return a CellResult')
        except BaseException as caught:
            finished.put_nowait((cell, None, caught))
        else:
            finished.put_nowait((cell, value, None))

    async def observe() -> None:
        nonlocal error
        cell, result, caught = await finished.get()
        if caught is None:
            try:
                assert result is not None
                persisted = persist(cell, result)
                if inspect.isawaitable(persisted):
                    await persisted
                results.append((cell, result))
                guard.observe(cell.cell_key, operational_failure=result.outcome.operational_failure,
                              failure_condition=result.outcome.failure_condition)
                if guard.halted:
                    stop(str(guard.halt_record()['condition']), cell.cell_key)
                elif result.critical_stop:
                    stop(result.critical_stop.condition, cell.cell_key)
                elif spending().cost_usd > controls.cost_limit_usd:
                    stop('campaign_known_cost_limit_exceeded', cell.cell_key)
            except BaseException as persist_error:
                caught = persist_error
        if caught is not None:
            if error is None:
                error = caught
            stop('incomplete_execution', cell.cell_key)
        task = active.pop(cell.cell_key)
        await task

    async def drain() -> None:
        while active:
            await observe()

    try:
        while next_index < len(cells) or active:
            # Observe every completion already available before considering
            # replacement dispatch. A returned fault must not sit behind
            # newly admitted work in the completion queue.
            while not finished.empty():
                await observe()
            while halt is None and next_index < len(cells) and len(active) < controls.concurrency:
                reserved = len(active) * controls.per_cell_reserve_usd
                if spending().cost_usd + reserved + controls.per_cell_reserve_usd > controls.cost_limit_usd:
                    # An active cell may spend less than its reserve. Wait for
                    # settlement before concluding that queued work cannot fit.
                    if active:
                        break
                    stop('campaign_cost_reserve_reached', None)
                    break
                cell = cells[next_index]
                next_index += 1
                active[cell.cell_key] = asyncio.create_task(invoke(cell))
            if active:
                await observe()
            elif halt is not None:
                break
    except BaseException as caught:
        error = caught
        stop('incomplete_execution', None)
        # Shield started work from cancellation of the controller. Never
        # turn cancellation into a retry, a zero charge or a completed run.
        await asyncio.shield(drain())
    if error is not None:
        raise error
    not_attempted = cells[next_index:]
    if halt is not None:
        halt['not_started_keys'] = [cell.cell_key for cell in not_attempted]
        halt['final_spend'] = spending().as_dict()
    return ControlledRun(tuple(results), tuple(not_attempted), spending(), halt)
