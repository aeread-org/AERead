"""Tests for the tau3.retail tool surface (tools.py / tau2_bridge.py).

Every retail tool is registered as a kernel ``ToolDefinition``/``ToolBinding``
and every call is delegated, through a cross-process bridge, to the pinned
upstream ``RetailTools`` implementation -- never reimplemented. In
particular ``modify_pending_order_items`` carries a real upstream bug (a
stale ``variant`` reused across its second loop on multi-item calls); the
star test below drives it through the real ``ToolBinding``/``ToolRuntime``
surface and asserts the exact upstream *buggy* post-state, never a
hypothetically corrected one, proving the binding is a delegation layer and
not a reimplementation.

These tests require a SEPARATE, already-provisioned Python interpreter
(>=3.12) with the pinned upstream tau2-bench package (commit
``fc0055dc4e0a316c3f83133267fbd6faaa770992``) importable -- AERead's own
venv deliberately does not carry tau2-bench's runtime dependencies (see
``tau2_bridge.py``'s module docstring). Point ``$AEREAD_TAU2_BRIDGE_PYTHON``
at such an interpreter to run these tests for real; otherwise the whole
module is skipped, mirroring ``tests/test_tau3_retail_cases.py``'s
``AEREAD_TAU2_UPSTREAM_ROOT`` convention -- never faked.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.resolver import canonical_json_bytes
from aeread.shared_runner.tools import ToolRuntime
from aeread_families.tau3_retail import tools as tau3_tools
from aeread_families.tau3_retail.tau2_bridge import (
    Tau2Bridge,
    Tau2BridgeUnavailableError,
    discover_bridge_python,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_TAU2_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-tau2",
    )
    root = Path(candidate)
    marker = root / "data" / "tau2" / "domains" / "retail" / "tasks.json"
    if not marker.is_file():
        pytest.skip(f"pinned upstream tau2-bench checkout not found at {root}")
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except Tau2BridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _SKIP_REASON = str(error)
else:
    _SKIP_REASON = ""

pytestmark = pytest.mark.skipif(
    BRIDGE_PYTHON is None, reason=_SKIP_REASON or "bridge python unavailable"
)


def _bridge() -> Tau2Bridge:
    assert BRIDGE_PYTHON is not None
    return Tau2Bridge(python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT)


def _load_raw_db_json() -> dict:
    db_path = UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json"
    return json.loads(db_path.read_text(encoding="utf-8"))


def _load_initial_db(bridge: Tau2Bridge) -> dict:
    """The pinned db.json, delegate-normalized into RetailDB.model_dump()
    shape (see Tau2Bridge.normalize_db) -- the shape spec section 4.1
    declares for the family state's "db" field, and the shape every
    post-call db already has, so a "before" snapshot taken here is
    comparable byte-for-byte against a post-call db without upstream's own
    Pydantic Optional-field defaulting masquerading as a tool-caused
    mutation."""
    return bridge.normalize_db(_load_raw_db_json())


def _evidence(tmp_path: Path, *, name: str = "evidence") -> EvidenceStore:
    return EvidenceStore(
        tmp_path / name,
        run_plan_id="runplan_tau3_retail_tools",
        cell_id="cell_tau3_retail_tools",
        episode_id="episode_tau3_retail_tools",
        episode_attempt_id="attempt_tau3_retail_tools",
    )


# ---------------------------------------------------------------------------
# Schema / effect delegation.
# ---------------------------------------------------------------------------


def test_tool_schema_hash_is_stable_across_two_processes() -> None:
    """Two independent bridge calls are two independent subprocesses (two
    independent OS processes running the pinned interpreter); their
    delegated schema hashes must agree byte-for-byte."""
    bridge = _bridge()
    first = bridge.fetch_tool_schema()
    second = bridge.fetch_tool_schema()
    first_hash = first["tool_schema_sha256"]
    second_hash = second["tool_schema_sha256"]
    assert first_hash == second_hash
    assert isinstance(first_hash, str)
    assert len(first_hash) == 64
    assert all(character in "0123456789abcdef" for character in first_hash)


def test_sixteen_tools_registered_matching_upstream_get_tools() -> None:
    bridge = _bridge()
    definitions = tau3_tools.build_tool_definitions(bridge)
    schema = bridge.fetch_tool_schema()
    assert len(definitions) == 16
    assert set(definitions) == set(schema["tools"])


def test_effect_matches_upstream_mutates_state_exactly() -> None:
    """effect is read straight from upstream's own mutates_state, not
    hand-copied; EXPECTED_MUTATING_TOOL_NAMES is only a cross-check that the
    live, delegated answer still matches spec section 5's declared set."""
    bridge = _bridge()
    definitions = tau3_tools.build_tool_definitions(bridge)
    mutating = {name for name, d in definitions.items() if d.effect == "mutating"}
    read_only = {name for name, d in definitions.items() if d.effect == "read_only"}

    assert mutating == tau3_tools.EXPECTED_MUTATING_TOOL_NAMES
    assert len(mutating) == 7
    assert len(read_only) == 9
    assert mutating | read_only == set(definitions)
    assert mutating & read_only == set()

    # And independently: effect matches upstream's live mutates_state per tool.
    schema = bridge.fetch_tool_schema()
    for name, definition in definitions.items():
        expected_effect = "mutating" if schema["tools"][name]["mutates_state"] else "read_only"
        assert definition.effect == expected_effect


def test_input_schema_is_exactly_upstream_openai_function_parameters() -> None:
    bridge = _bridge()
    schema = bridge.fetch_tool_schema()
    definitions = tau3_tools.build_tool_definitions(bridge)
    for name, definition in definitions.items():
        expected = schema["tools"][name]["openai_schema"]["function"]["parameters"]
        assert canonical_json_bytes(definition.input_schema) == canonical_json_bytes(expected)


def test_idempotency_supported_is_false_for_all_sixteen() -> None:
    bridge = _bridge()
    definitions = tau3_tools.build_tool_definitions(bridge)
    assert all(d.idempotency_supported is False for d in definitions.values())


def test_tool_version_is_010_for_all_sixteen() -> None:
    bridge = _bridge()
    definitions = tau3_tools.build_tool_definitions(bridge)
    assert all(d.tool_version == "0.1.0" for d in definitions.values())


# ---------------------------------------------------------------------------
# Mutating vs read-only behavior through the actual ToolBinding surface.
# ---------------------------------------------------------------------------


def test_mutating_call_through_binding_changes_the_db_the_state_reader_returns() -> None:
    bridge = _bridge()
    session = tau3_tools.RetailToolSession(_load_initial_db(bridge))
    bindings = tau3_tools.build_tool_bindings(bridge, session)
    binding_by_id = {binding.definition.tool_id: binding for binding in bindings}
    binding = binding_by_id["modify_user_address"]

    assert binding.definition.effect == "mutating"
    assert binding.state_reader is not None
    assert binding.state_reader() is session.get_db()

    before_snapshot = copy.deepcopy(session.get_db())
    result = asyncio.run(
        binding.implementation(
            {
                "user_id": "sofia_rossi_8776",
                "address1": "1 Bug Reproduction Way",
                "address2": "",
                "city": "Testville",
                "state": "TX",
                "country": "USA",
                "zip": "00000",
            }
        )
    )

    assert result["error"] is False
    after_snapshot = binding.state_reader()
    assert after_snapshot != before_snapshot
    assert after_snapshot["users"]["sofia_rossi_8776"]["address"]["address1"] == (
        "1 Bug Reproduction Way"
    )
    # The reader always reflects the session's *current* db, not a frozen copy.
    assert binding.state_reader() is session.get_db()


def test_read_only_call_through_binding_does_not_change_the_db() -> None:
    bridge = _bridge()
    session = tau3_tools.RetailToolSession(_load_initial_db(bridge))
    bindings = tau3_tools.build_tool_bindings(bridge, session)
    binding_by_id = {binding.definition.tool_id: binding for binding in bindings}
    binding = binding_by_id["get_order_details"]

    assert binding.definition.effect == "read_only"
    assert binding.state_reader is None

    before_snapshot = copy.deepcopy(session.get_db())
    result = asyncio.run(binding.implementation({"order_id": "#W5918442"}))

    assert result["error"] is False
    assert json.loads(result["content"])["order_id"] == "#W5918442"
    assert session.get_db() == before_snapshot


def test_read_only_tool_through_runtime_never_trips_the_kernels_own_mutation_guard(
    tmp_path: Path,
) -> None:
    """Belt-and-suspenders: even if a state_reader *were* wired to a
    read-only tool, the kernel's own ToolExecutor would reject a state
    change for a read_only-declared tool (see ToolExecutor.invoke's
    tool_effect_violation guard) -- exercise get_order_details through that
    exact guard to prove there genuinely is none to trip."""
    bridge = _bridge()
    session = tau3_tools.RetailToolSession(_load_initial_db(bridge))
    definitions = tau3_tools.build_tool_definitions(bridge)
    definition = definitions["get_order_details"]
    assert definition.effect == "read_only"

    from aeread.shared_runner.tools import ToolBinding

    async def implementation(arguments):
        return await tau3_tools._implementation(bridge, session, "get_order_details", arguments)

    guarded_binding = ToolBinding(
        definition=definition,
        implementation=implementation,
        state_reader=session.get_db,  # deliberately wired despite read_only
    )
    runtime = ToolRuntime(_evidence(tmp_path), (guarded_binding,))
    _, record = asyncio.run(
        runtime.invoke(
            action_attempt_id="attempt_read_only_guard",
            tool_id="get_order_details",
            arguments={"order_id": "#W5918442"},
        )
    )
    assert record.status == "succeeded"
    assert record.state_changed is False


# ---------------------------------------------------------------------------
# P6 (spec section 8) -- the bug reproduction, through the real binding.
# ---------------------------------------------------------------------------

BUG_ORDER_ID = "#W5918442"
BUG_ITEM_IDS = ["1725100896", "5312063289"]
BUG_NEW_ITEM_IDS = ["9007697085", "6843647669"]
BUG_PAYMENT_METHOD_ID = "credit_card_5051208"


def test_modify_pending_order_items_multi_item_reproduces_upstream_stale_variant_bug(
    tmp_path: Path,
) -> None:
    """Drive a real multi-item modify_pending_order_items call through the
    actual ToolBinding/ToolRuntime surface and assert the exact upstream
    *buggy* post-state: both exchanged items end up with the price and
    options of the *last* item's new variant, because upstream's own
    RetailTools.modify_pending_order_items reuses the loop variable
    `variant` -- which after its first (diff-price) loop holds only the
    last iteration's variant -- when writing `item.price`/`item.options` in
    its second loop. This is only observable because ``implementation``
    delegates to upstream's real tool body; a corrected reimplementation
    could not reproduce it.

    Order #W5918442 (user sofia_rossi_8776), and the two target item/variant
    ids below, are read verbatim from the pinned db.json: a pending order
    with >=2 items whose replacement variants have different prices *and*
    different options, so the bug is unambiguous either way it could leak.
    """
    bridge = _bridge()
    initial_db = _load_initial_db(bridge)
    order = initial_db["orders"][BUG_ORDER_ID]
    assert order["status"] == "pending"
    assert [item["item_id"] for item in order["items"][:2]] == BUG_ITEM_IDS

    # Upstream's own computed values for what each item's replacement
    # variant *should* look like in isolation -- fetched via delegated
    # read-only tool calls, never hand-typed -- so every assertion below is
    # against real upstream output, not an invented constant.
    item0_variant = json.loads(
        bridge.call_tool(
            db=initial_db,
            tool_name="get_item_details",
            arguments={"item_id": BUG_NEW_ITEM_IDS[0]},
        )["content"]
    )
    item1_variant = json.loads(
        bridge.call_tool(
            db=initial_db,
            tool_name="get_item_details",
            arguments={"item_id": BUG_NEW_ITEM_IDS[1]},
        )["content"]
    )
    # Sanity: the two variants must actually differ, or the bug would be
    # unobservable from price/options alone.
    assert item0_variant["price"] != item1_variant["price"]
    assert item0_variant["options"] != item1_variant["options"]

    session = tau3_tools.RetailToolSession(initial_db)
    bindings = tau3_tools.build_tool_bindings(bridge, session)
    evidence = _evidence(tmp_path, name="evidence_bug")
    runtime = ToolRuntime(evidence, bindings)

    result, record = asyncio.run(
        runtime.invoke(
            action_attempt_id="attempt_modify_multi_item",
            tool_id="modify_pending_order_items",
            arguments={
                "order_id": BUG_ORDER_ID,
                "item_ids": BUG_ITEM_IDS,
                "new_item_ids": BUG_NEW_ITEM_IDS,
                "payment_method_id": BUG_PAYMENT_METHOD_ID,
            },
        )
    )

    assert result["error"] is False
    assert record.status == "succeeded"
    assert record.effect == "mutating"
    assert record.state_changed is True

    updated_order = session.get_db()["orders"][BUG_ORDER_ID]
    updated_by_new_id = {item["item_id"]: item for item in updated_order["items"]}
    updated_item0 = updated_by_new_id[BUG_NEW_ITEM_IDS[0]]
    updated_item1 = updated_by_new_id[BUG_NEW_ITEM_IDS[1]]

    # THE BUG: both items carry the *second* (last-iterated) item's variant
    # price and options -- item 0's own (correct) variant is discarded.
    assert updated_item0["price"] == item1_variant["price"]
    assert updated_item1["price"] == item1_variant["price"]
    assert updated_item0["options"] == item1_variant["options"]
    assert updated_item1["options"] == item1_variant["options"]

    # NOT the corrected behavior: item 0 never receives its own variant's
    # price or options, even though its item_id was renamed correctly.
    assert updated_item0["price"] != item0_variant["price"]
    assert updated_item0["options"] != item0_variant["options"]

    # item_id bookkeeping itself is per-item and correct -- only price and
    # options leak from the stale `variant`, exactly matching the spec's
    # description of the bug. The other two (untouched) items in the same
    # order are unaffected, and the two old item ids are gone.
    assert {BUG_NEW_ITEM_IDS[0], BUG_NEW_ITEM_IDS[1]} <= set(updated_by_new_id)
    assert BUG_ITEM_IDS[0] not in updated_by_new_id
    assert BUG_ITEM_IDS[1] not in updated_by_new_id
    assert len(updated_order["items"]) == len(order["items"])
    assert updated_order["status"] == "pending (item modified)"


def test_single_item_modify_pending_order_items_is_not_affected_by_the_bug(
    tmp_path: Path,
) -> None:
    """Control: a single-item call has only one loop iteration, so `variant`
    is never stale -- the item receives its own correct variant."""
    bridge = _bridge()
    initial_db = _load_initial_db(bridge)
    single_item_id, single_new_item_id = BUG_ITEM_IDS[0], BUG_NEW_ITEM_IDS[0]
    expected_variant = json.loads(
        bridge.call_tool(
            db=initial_db,
            tool_name="get_item_details",
            arguments={"item_id": single_new_item_id},
        )["content"]
    )

    session = tau3_tools.RetailToolSession(initial_db)
    bindings = tau3_tools.build_tool_bindings(bridge, session)
    runtime = ToolRuntime(_evidence(tmp_path, name="evidence_control"), bindings)

    result, record = asyncio.run(
        runtime.invoke(
            action_attempt_id="attempt_modify_single_item",
            tool_id="modify_pending_order_items",
            arguments={
                "order_id": BUG_ORDER_ID,
                "item_ids": [single_item_id],
                "new_item_ids": [single_new_item_id],
                "payment_method_id": BUG_PAYMENT_METHOD_ID,
            },
        )
    )

    assert result["error"] is False
    assert record.state_changed is True
    updated_order = session.get_db()["orders"][BUG_ORDER_ID]
    updated_item = next(
        item for item in updated_order["items"] if item["item_id"] == single_new_item_id
    )
    assert updated_item["price"] == expected_variant["price"]
    assert updated_item["options"] == expected_variant["options"]
