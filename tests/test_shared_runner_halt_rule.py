"""The kernel halt rule: declared in the contract, enforced by the guard.

The scenarios are the ones that cost cells: a run against an exhausted
balance (DC-O-15) and a run through a network outage (DC-T-08).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from aeread.shared_runner import (
    ACCOUNT_FAULT,
    HALT_EXIT_CODE,
    HALT_RULE_FIELD,
    HALTED_AFTER_CONSECUTIVE_FAILURES,
    HALTED_ON_ACCOUNT_FAULT,
    NOT_ATTEMPTED,
    CellOutcome,
    ContractError,
    OperationalHaltGuard,
    require_halt_rule,
    run_cells_under_halt_rule,
)
from aeread.shared_runner.run.adapter_campaign import (
    _SAFE_PROVIDER_FAILURE_CONDITIONS,
)
from aeread.shared_runner.task.execution import (
    OpenAIResponsesClient,
    OpenRouterChatClient,
)


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code


def test_require_halt_rule_reads_a_positive_integer_limit() -> None:
    assert require_halt_rule({HALT_RULE_FIELD: 3}) == 3
    assert require_halt_rule({HALT_RULE_FIELD: 1, "other": "x"}) == 1


@pytest.mark.parametrize("value", [0, -1, True, 2.0, "3", None])
def test_require_halt_rule_rejects_anything_but_a_positive_integer(value: Any) -> None:
    with pytest.raises(ContractError, match="must be a positive integer"):
        require_halt_rule({HALT_RULE_FIELD: value})
    with pytest.raises(ContractError, match="must be a positive integer"):
        require_halt_rule({HALT_RULE_FIELD: value}, required=False)


def test_require_halt_rule_is_required_unless_the_schema_predates_it() -> None:
    with pytest.raises(ContractError, match="is required"):
        require_halt_rule({})
    with pytest.raises(ContractError, match="pilot execution block must be an object"):
        require_halt_rule([], label="pilot")
    # A sealed contract that never declared the control does not acquire one.
    assert require_halt_rule({}, required=False) is None


def test_guard_halts_at_the_declared_streak_and_a_success_resets_it() -> None:
    guard = OperationalHaltGuard(3)
    assert not guard.observe("c1", operational_failure=True, failure_condition="transport")
    assert not guard.observe("c2", operational_failure=True, failure_condition="transport")
    assert not guard.observe("c3", operational_failure=False)
    assert guard.streak == 0
    assert not guard.observe("c4", operational_failure=True, failure_condition="timeout")
    assert not guard.observe("c5", operational_failure=True, failure_condition="timeout")
    assert guard.observe("c6", operational_failure=True, failure_condition="transport")
    assert guard.halted
    assert guard.halt_record() == {
        "condition": HALTED_AFTER_CONSECUTIVE_FAILURES,
        "limit": 3,
        "consecutive_operational_failures": 3,
        "after_cell": "c6",
        "cells_not_attempted": 0,
    }


def test_an_account_fault_halts_on_the_first_cell_whatever_the_limit() -> None:
    guard = OperationalHaltGuard(10)
    assert guard.observe("c1", operational_failure=True, failure_condition=ACCOUNT_FAULT)
    record = guard.halt_record()
    assert record is not None
    assert record["condition"] == HALTED_ON_ACCOUNT_FAULT
    assert record["after_cell"] == "c1"
    assert record["consecutive_operational_failures"] == 1


def test_a_resumed_result_neither_extends_nor_resets_the_streak() -> None:
    guard = OperationalHaltGuard(2)
    guard.observe("c1", operational_failure=True, failure_condition="transport")
    # Resumed records describe an earlier run, not the provider as it is now.
    guard.observe("c2", operational_failure=False, attempted_now=False)
    guard.observe("c3", operational_failure=True, attempted_now=False)
    assert guard.streak == 1 and not guard.halted
    assert guard.observe("c4", operational_failure=True, failure_condition="transport")


def test_an_undeclared_rule_never_halts() -> None:
    guard = OperationalHaltGuard(None)
    for index in range(50):
        assert not guard.observe(
            f"c{index}", operational_failure=True, failure_condition=ACCOUNT_FAULT
        )
    assert guard.halt_record() is None


def test_guard_rejects_bad_limits_keys_and_premature_missingness() -> None:
    for limit in (0, -2, True, 1.5, "2"):
        with pytest.raises(ValueError, match="positive integer or None"):
            OperationalHaltGuard(limit)  # type: ignore[arg-type]
    guard = OperationalHaltGuard(1)
    with pytest.raises(ValueError, match="cell_key"):
        guard.observe("", operational_failure=True)
    with pytest.raises(ValueError, match="before the run has halted"):
        guard.not_attempted_failure("c9")


def test_unreached_cells_are_typed_not_attempted_and_counted_once() -> None:
    guard = OperationalHaltGuard(1)
    guard.observe("c1", operational_failure=True, failure_condition="transport")
    failure = guard.not_attempted_failure("c2")
    assert failure == {
        "receipt_status": NOT_ATTEMPTED,
        "failure_class": "operational",
        "failure_condition": HALTED_AFTER_CONSECUTIVE_FAILURES,
        "halted_after_cell": "c1",
    }
    guard.not_attempted_failure("c2")
    guard.not_attempted_failure("c3")
    record = guard.halt_record()
    assert record is not None and record["cells_not_attempted"] == 2


def _run(cells: list[str], failing: dict[str, str], limit: int | None):
    attempted: list[str] = []

    async def execute(cell_key: str) -> dict[str, Any]:
        attempted.append(cell_key)
        return {"cell": cell_key, "condition": failing.get(cell_key)}

    run = asyncio.run(
        run_cells_under_halt_rule(
            cells,
            execute,
            guard=OperationalHaltGuard(limit),
            outcome=lambda result: CellOutcome(
                operational_failure=result["condition"] is not None,
                failure_condition=result["condition"],
            ),
        )
    )
    return run, attempted


def test_an_exhausted_balance_leaves_the_rest_of_the_design_unattempted() -> None:
    """DC-O-15: 214 of 348 cells were sealed as failures on HTTP 402."""

    cells = [f"cell_{index:03d}" for index in range(348)]
    failing = {cell: ACCOUNT_FAULT for cell in cells[134:]}
    run, attempted = _run(cells, failing, limit=5)
    assert attempted == cells[:135]
    assert [key for key, _ in run.results] == cells[:135]
    assert [key for key, _ in run.not_attempted] == cells[135:]
    assert len(run.not_attempted) == 213
    assert all(
        failure["receipt_status"] == NOT_ATTEMPTED
        and failure["failure_condition"] == HALTED_ON_ACCOUNT_FAULT
        and failure["halted_after_cell"] == "cell_134"
        for _, failure in run.not_attempted
    )
    assert run.halt is not None and run.halt["cells_not_attempted"] == 213
    assert run.exit_code == HALT_EXIT_CODE


def test_a_network_outage_stops_at_the_limit_instead_of_exhausting_the_design() -> None:
    """DC-T-08: 14 cells in a row each failed in 0 s as transport."""

    cells = [f"cell_{index:02d}" for index in range(48)]
    failing = {cell: "transport" for cell in cells[34:]}
    run, attempted = _run(cells, failing, limit=2)
    assert attempted == cells[:36]
    assert len(run.not_attempted) == 12
    assert run.halt == {
        "condition": HALTED_AFTER_CONSECUTIVE_FAILURES,
        "limit": 2,
        "consecutive_operational_failures": 2,
        "after_cell": "cell_35",
        "cells_not_attempted": 12,
    }


def test_an_undeclared_rule_runs_every_cell_as_before() -> None:
    cells = [f"cell_{index:02d}" for index in range(48)]
    failing = {cell: "transport" for cell in cells[34:]}
    run, attempted = _run(cells, failing, limit=None)
    assert attempted == cells
    assert run.not_attempted == () and run.halt is None and run.exit_code == 0


def test_isolated_failures_below_the_limit_do_not_halt() -> None:
    cells = [f"cell_{index:02d}" for index in range(12)]
    failing = {cell: "timeout" for cell in cells[::2]}
    run, attempted = _run(cells, failing, limit=2)
    assert attempted == cells and run.halt is None


def test_driver_refuses_duplicate_cells_and_untyped_outcomes() -> None:
    guard = OperationalHaltGuard(2)
    with pytest.raises(ValueError, match="unique"):
        asyncio.run(
            run_cells_under_halt_rule(
                ["a", "a"], lambda key: key, guard=guard, outcome=lambda _: CellOutcome(False)
            )
        )
    with pytest.raises(TypeError, match="CellOutcome"):
        asyncio.run(
            run_cells_under_halt_rule(
                ["a"], lambda key: key, guard=guard, outcome=lambda _: False  # type: ignore[arg-type,return-value]
            )
        )


def test_http_402_is_typed_account_fault_on_both_client_paths() -> None:
    raised = OpenAIResponsesClient._classify_error(_StatusError(402))
    assert raised.condition == ACCOUNT_FAULT
    assert raised.retryable is False and raised.status_code == 402
    in_body = OpenRouterChatClient._provider_error(402, "Insufficient credits")
    assert in_body.condition == ACCOUNT_FAULT
    assert in_body.retryable is False and in_body.status_code == 402
    assert ACCOUNT_FAULT in _SAFE_PROVIDER_FAILURE_CONDITIONS


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_other_rejections_keep_their_typing(status: int) -> None:
    assert OpenAIResponsesClient._classify_error(_StatusError(status)).condition == (
        "provider_rejected"
    )
    assert OpenRouterChatClient._provider_error(status, "rejected").condition == (
        "provider_rejected"
    )
    assert OpenRouterChatClient._provider_error(503, "down").condition == "provider_5xx"
