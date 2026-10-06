"""The run-level halt rule: stop on a fault the next cell cannot recover from.

A campaign driver executes its cells one after another. When the provider
account is exhausted or the network is gone, every remaining cell fails the
same way in a fraction of a second, and a driver with no stop rule seals each
of them as that cell's operational failure. The design is then spent on a
fault that had nothing to do with the cells: 214 of 348 cells were sealed as
failures against an empty balance (DC-O-15), and 14 cells in a row failed in
0 s as ``transport`` after a network drop (DC-T-08).

Three family drivers each rebuilt a stop rule for this. The kernel now owns
it, in three parts:

* the control is declared in the contract's execution block
  (:func:`require_halt_rule`), because a limit that can end a run and lives
  only in code is invisible to anyone reading the experiment definition;
* :class:`OperationalHaltGuard` counts consecutive operational failures and
  trips at the declared limit, or at once on an account fault, which no
  number of further cells can outlast;
* a cell the run never reached is typed ``not_attempted``
  (:meth:`OperationalHaltGuard.not_attempted_failure`): it carries no
  receipt, because nothing was attempted, and it is not a failure of the
  cell.

A halted run is not a finished one, so its driver exits with
:data:`HALT_EXIT_CODE` and reports :meth:`OperationalHaltGuard.halt_record`.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..task.execution import ACCOUNT_FAULT
from .contract import ContractError

#: The contract's execution-block key that declares the limit.
HALT_RULE_FIELD = "max_consecutive_operational_failures"

#: Why a run halted. These name the halt, not any one cell's failure.
HALTED_AFTER_CONSECUTIVE_FAILURES = "halted_after_consecutive_operational_failures"
HALTED_ON_ACCOUNT_FAULT = "halted_on_account_fault"
HALT_CONDITIONS = frozenset(
    {HALTED_AFTER_CONSECUTIVE_FAILURES, HALTED_ON_ACCOUNT_FAULT}
)

#: The receipt status of a cell a halted run never reached.
NOT_ATTEMPTED = "not_attempted"

#: Process exit status of a driver whose run halted.
HALT_EXIT_CODE = 2


def require_halt_rule(
    execution: Any, *, required: bool = True, label: str | None = None
) -> int | None:
    """Return the declared consecutive-failure limit of an execution block.

    ``required=False`` is for a contract schema that predates the control: it
    returns ``None`` when the field is absent, so a sealed contract never
    acquires a stop rule it did not declare. A present value must be a
    positive integer under either setting.
    """

    prefix = f"{label} " if label else ""
    if not isinstance(execution, Mapping):
        raise ContractError(f"{prefix}execution block must be an object")
    if HALT_RULE_FIELD not in execution:
        if required:
            raise ContractError(f"{prefix}execution.{HALT_RULE_FIELD} is required")
        return None
    limit = execution[HALT_RULE_FIELD]
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ContractError(
            f"{prefix}execution.{HALT_RULE_FIELD} must be a positive integer"
        )
    return limit


class OperationalHaltGuard:
    """Counts consecutive operational failures and says when to stop.

    ``limit=None`` is the undeclared rule: the guard observes and never
    halts, so a driver can hold one guard for every contract schema it reads.
    """

    def __init__(self, limit: int | None) -> None:
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise ValueError(f"{HALT_RULE_FIELD} must be a positive integer or None")
        self._limit = limit
        self._streak = 0
        self._condition: str | None = None
        self._after_cell: str | None = None
        self._not_attempted: list[str] = []

    @property
    def limit(self) -> int | None:
        return self._limit

    @property
    def streak(self) -> int:
        """Operational failures in a row since the last completed cell."""

        return self._streak

    @property
    def halted(self) -> bool:
        return self._condition is not None

    def observe(
        self,
        cell_key: str,
        *,
        operational_failure: bool,
        failure_condition: str | None = None,
        attempted_now: bool = True,
    ) -> bool:
        """Record one cell's outcome; return whether the run is now halted.

        ``attempted_now=False`` is a result resumed from an earlier run. It
        says nothing about the provider as it is now, so it neither extends
        nor resets the streak.
        """

        if not isinstance(cell_key, str) or not cell_key:
            raise ValueError("cell_key must be a non-empty string")
        if self._limit is None or self.halted or not attempted_now:
            return self.halted
        if not operational_failure:
            self._streak = 0
            return False
        self._streak += 1
        if failure_condition == ACCOUNT_FAULT:
            self._condition = HALTED_ON_ACCOUNT_FAULT
        elif self._streak >= self._limit:
            self._condition = HALTED_AFTER_CONSECUTIVE_FAILURES
        if self.halted:
            self._after_cell = cell_key
        return self.halted

    def not_attempted_failure(self, cell_key: str) -> dict[str, Any]:
        """The typed missingness of one cell the halted run never reached."""

        if not self.halted:
            raise ValueError("no cell is unattempted before the run has halted")
        if not isinstance(cell_key, str) or not cell_key:
            raise ValueError("cell_key must be a non-empty string")
        if cell_key not in self._not_attempted:
            self._not_attempted.append(cell_key)
        return {
            "receipt_status": NOT_ATTEMPTED,
            "failure_class": "operational",
            "failure_condition": self._condition,
            "halted_after_cell": self._after_cell,
        }

    def halt_record(self) -> dict[str, Any] | None:
        """What a halted run reports in its summary; ``None`` if it did not halt."""

        if not self.halted:
            return None
        return {
            "condition": self._condition,
            "limit": self._limit,
            "consecutive_operational_failures": self._streak,
            "after_cell": self._after_cell,
            "cells_not_attempted": len(self._not_attempted),
        }


@dataclass(frozen=True, slots=True)
class CellOutcome:
    """What the halt rule needs to know about one executed cell."""

    operational_failure: bool
    failure_condition: str | None = None
    attempted_now: bool = True


@dataclass(frozen=True, slots=True)
class HaltedRun:
    """The cells a run executed, the cells it never reached, and why."""

    results: tuple[tuple[str, Any], ...]
    not_attempted: tuple[tuple[str, Mapping[str, Any]], ...]
    halt: Mapping[str, Any] | None

    @property
    def exit_code(self) -> int:
        return HALT_EXIT_CODE if self.halt is not None else 0


async def run_cells_under_halt_rule(
    cell_keys: Sequence[str],
    execute: Callable[[str], Awaitable[Any] | Any],
    *,
    guard: OperationalHaltGuard,
    outcome: Callable[[Any], CellOutcome],
) -> HaltedRun:
    """Execute cells in order and stop attempting once the guard halts.

    ``execute`` runs one cell and returns the family's own result;
    ``outcome`` reads from that result what the guard needs. A driver that
    interleaves cells across routes holds the guard directly instead.
    """

    if len(set(cell_keys)) != len(cell_keys):
        raise ValueError("cell_keys must be unique")
    results: list[tuple[str, Any]] = []
    not_attempted: list[tuple[str, Mapping[str, Any]]] = []
    for cell_key in cell_keys:
        if guard.halted:
            not_attempted.append((cell_key, guard.not_attempted_failure(cell_key)))
            continue
        result = execute(cell_key)
        if inspect.isawaitable(result):
            result = await result
        observed = outcome(result)
        if not isinstance(observed, CellOutcome):
            raise TypeError("outcome must return a CellOutcome")
        guard.observe(
            cell_key,
            operational_failure=observed.operational_failure,
            failure_condition=observed.failure_condition,
            attempted_now=observed.attempted_now,
        )
        results.append((cell_key, result))
    return HaltedRun(
        results=tuple(results),
        not_attempted=tuple(not_attempted),
        halt=guard.halt_record(),
    )


__all__ = [
    "CellOutcome",
    "HALTED_AFTER_CONSECUTIVE_FAILURES",
    "HALTED_ON_ACCOUNT_FAULT",
    "HALT_CONDITIONS",
    "HALT_EXIT_CODE",
    "HALT_RULE_FIELD",
    "HaltedRun",
    "NOT_ATTEMPTED",
    "OperationalHaltGuard",
    "require_halt_rule",
    "run_cells_under_halt_rule",
]
