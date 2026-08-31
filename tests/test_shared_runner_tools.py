from __future__ import annotations

import asyncio

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.tools import (
    ToolBinding,
    ToolContractError,
    ToolDefinition,
    ToolRuntime,
)


def _evidence(tmp_path) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_tool_fixture",
        cell_id="cell_tool_fixture",
        episode_id="episode_tool_fixture",
        episode_attempt_id="attempt_tool_fixture",
    )


def test_refund_and_supply_chain_tools_share_one_runtime_contract(tmp_path) -> None:
    refund_db = {"order_1": {"status": "paid"}}
    supply_db = {"inventory": 10, "purchase_orders": []}

    async def refund(arguments):
        refund_db[arguments["order_id"]]["status"] = "refunded"
        return {"status": "refunded"}

    async def place_order(arguments):
        supply_db["purchase_orders"].append(arguments["po_id"])
        return {"status": "accepted"}

    runtime = ToolRuntime(
        _evidence(tmp_path),
        (
            ToolBinding(
                ToolDefinition(
                    tool_id="refund_order",
                    tool_version="1.0.0",
                    effect="mutating",
                    input_schema={
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                    },
                    idempotency_supported=True,
                ),
                implementation=refund,
                state_reader=lambda: refund_db,
            ),
            ToolBinding(
                ToolDefinition(
                    tool_id="place_purchase_order",
                    tool_version="1.0.0",
                    effect="mutating",
                    input_schema={
                        "type": "object",
                        "properties": {"po_id": {"type": "string"}},
                        "required": ["po_id"],
                    },
                    idempotency_supported=False,
                ),
                implementation=place_order,
                state_reader=lambda: supply_db,
            ),
        ),
    )

    _, refund_record = asyncio.run(
        runtime.invoke(
            action_attempt_id="attempt_refund",
            tool_id="refund_order",
            arguments={"order_id": "order_1"},
        )
    )
    _, supply_record = asyncio.run(
        runtime.invoke(
            action_attempt_id="attempt_supply",
            tool_id="place_purchase_order",
            arguments={"po_id": "po_7"},
        )
    )

    assert refund_record.tool_schema_sha256 == runtime.definition("refund_order").schema_sha256
    assert supply_record.tool_schema_sha256 == runtime.definition(
        "place_purchase_order"
    ).schema_sha256
    assert refund_record.state_changed is True
    assert supply_record.state_changed is True
    assert len(runtime.manifest_sha256) == 64


def test_mutating_tool_binding_requires_a_state_reader(tmp_path) -> None:
    async def mutate(_arguments):
        return {"ok": True}

    with pytest.raises(ToolContractError, match="state_reader"):
        ToolRuntime(
            _evidence(tmp_path),
            (
                ToolBinding(
                    ToolDefinition(
                        tool_id="mutate",
                        tool_version="1.0.0",
                        effect="mutating",
                        input_schema={"type": "object"},
                        idempotency_supported=False,
                    ),
                    implementation=mutate,
                ),
            ),
        )


def test_undeclared_tool_is_rejected_before_an_invocation_event(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    runtime = ToolRuntime(evidence, ())

    with pytest.raises(ToolContractError, match="undeclared tool"):
        asyncio.run(
            runtime.invoke(
                action_attempt_id="attempt_unknown",
                tool_id="delete_everything",
                arguments={},
            )
        )

    assert evidence.read_events() == ()


def test_tool_manifest_hash_is_order_independent(tmp_path) -> None:
    async def read(_arguments):
        return {"ok": True}

    a = ToolBinding(
        ToolDefinition("alpha", "1.0.0", "read_only", {"type": "object"}, True),
        read,
    )
    b = ToolBinding(
        ToolDefinition("beta", "1.0.0", "read_only", {"type": "object"}, True),
        read,
    )
    first = ToolRuntime(_evidence(tmp_path / "first"), (a, b))
    second = ToolRuntime(_evidence(tmp_path / "second"), (b, a))

    assert first.manifest_sha256 == second.manifest_sha256
