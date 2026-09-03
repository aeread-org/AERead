"""ToolDefinition/ToolBinding surface for the 16 tau2-bench retail tools.

Every binding here delegates to the pinned upstream implementation through
``Tau2Bridge`` (``tau2_bridge.py``) -- no tool body, database mutation, or
schema derivation is reimplemented (``docs/tau3_retail_adapter_spec.md``
rule 2 and section 5). ``effect`` (mutating vs read_only) and
``input_schema`` are read straight off upstream's own
``mutates_state``/``openai_schema``, fetched live through the bridge each
time ``build_tool_definitions``/``build_tool_bindings`` is called; nothing
about tool classification is hand-copied here except as a cross-check
assertion in the test suite (``EXPECTED_MUTATING_TOOL_NAMES`` below).

Spec section 5, reflected 1:1 in this module:

- ``tool_id`` = upstream tool name (already grammar-valid, e.g.
  ``cancel_pending_order``).
- ``tool_version`` = ``"0.1.0"`` for all 16; the upstream commit lives in
  ``payload.pins`` (see ``cases.py``), not in this version string.
- ``effect`` = ``"mutating"`` for exactly the 7 WRITE tools, ``"read_only"``
  for the 7 READ + 2 GENERIC tools -- equal to upstream's own
  ``mutates_state`` exactly, because it *is* upstream's own
  ``mutates_state``, fetched via the bridge.
- ``input_schema`` = upstream ``Tool.openai_schema["function"]["parameters"]``.
- ``idempotency_supported`` = ``False`` for all 16 (upstream tools are not
  idempotent -- e.g. a gift-card balance mutation would double).
- ``implementation`` = an async wrapper delegating to
  ``Tau2Bridge.call_tool``, which itself delegates to upstream's
  ``Environment.get_response`` -- so success payloads *and* error strings
  match upstream byte-for-byte, and upstream's own
  ``modify_pending_order_items`` bug (a stale ``variant`` reused across the
  method's second loop on multi-item calls) is reproduced by construction
  rather than by re-derivation.
- ``state_reader`` -- one shared reader for all seven mutating tools,
  ``session.get_db``, returning the complete ``RetailDB`` dump. Per-tool
  narrower readers are deliberately not used: ``cancel_pending_order``, for
  example, mutates both ``orders`` and ``users`` (gift-card balances) in one
  call, so only the whole-DB snapshot captures every mutation. Read/generic
  tools have no ``state_reader`` at all (``None``), matching the spec's
  "required for every mutating tool" -- not for the other nine.
"""
from __future__ import annotations

from typing import Any, Mapping

from aeread.shared_runner.task.tools import ToolBinding, ToolDefinition

from .tau2_bridge import Tau2Bridge

TOOL_VERSION = "0.1.0"

# Cross-check only -- see tests/test_tau3_retail_tools.py. The *live*,
# bridge-delegated answer to "which tools mutate state" is what actually
# drives ToolDefinition.effect in build_tool_definitions below; this tuple
# exists purely so a test can assert that live answer still matches spec
# section 5's declared 7 WRITE tools, rather than silently drifting if
# upstream's tool classification ever changes.
EXPECTED_MUTATING_TOOL_NAMES = frozenset(
    {
        "cancel_pending_order",
        "exchange_delivered_order_items",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_user_address",
        "return_delivered_order_items",
    }
)


class RetailToolSession:
    """Holds the one mutable piece of state every retail tool call needs.

    Mirrors spec section 5's ``lambda: harness_env.get_db().model_dump()``:
    a single shared reader over the *whole* ``RetailDB`` dump. A session is
    intentionally dumb -- it does not call the bridge itself; ``tools.py``'s
    tool implementations read the current db, call the bridge, and write the
    bridge's returned db back in.
    """

    def __init__(self, db: Mapping[str, Any]) -> None:
        self._db: dict[str, Any] = dict(db)

    def get_db(self) -> dict[str, Any]:
        return self._db

    def set_db(self, db: Mapping[str, Any]) -> None:
        self._db = dict(db)


def fetch_tool_schema(bridge: Tau2Bridge) -> dict[str, Any]:
    """One bridge call: every tool's OpenAI schema plus upstream's own effect."""
    return bridge.fetch_tool_schema()


def build_tool_definitions(bridge: Tau2Bridge) -> dict[str, ToolDefinition]:
    """Build all 16 ``ToolDefinition``s from one delegated schema fetch."""
    schema = fetch_tool_schema(bridge)
    definitions: dict[str, ToolDefinition] = {}
    for name, info in schema["tools"].items():
        input_schema = info["openai_schema"]["function"]["parameters"]
        effect = "mutating" if info["mutates_state"] else "read_only"
        definitions[name] = ToolDefinition(
            tool_id=name,
            tool_version=TOOL_VERSION,
            effect=effect,
            input_schema=input_schema,
            idempotency_supported=False,
        )
    return definitions


async def _implementation(
    bridge: Tau2Bridge,
    session: RetailToolSession,
    tool_name: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    response = bridge.call_tool(
        db=session.get_db(), tool_name=tool_name, arguments=arguments
    )
    session.set_db(response["db"])
    return {"content": response["content"], "error": response["error"]}


def build_tool_bindings(
    bridge: Tau2Bridge, session: RetailToolSession
) -> tuple[ToolBinding, ...]:
    """Build the 16 ``ToolBinding``s, all delegating through ``bridge`` and
    sharing one live ``session``.

    Every ``implementation`` here calls ``bridge.call_tool`` -- the same
    upstream ``Environment.get_response`` path that produces success
    payloads *and* error strings byte-for-byte, including upstream's real
    ``modify_pending_order_items`` bug (see
    ``docs/tau3_retail_adapter_spec.md`` and
    ``tests/test_tau3_retail_tools.py``). Mutating tools share exactly one
    ``state_reader`` (``session.get_db``); read/generic tools have none, per
    spec section 5.
    """
    definitions = build_tool_definitions(bridge)
    bindings: list[ToolBinding] = []
    for name, definition in definitions.items():

        async def implementation(
            arguments: Mapping[str, Any], *, _name: str = name
        ) -> dict[str, Any]:
            return await _implementation(bridge, session, _name, arguments)

        state_reader = session.get_db if definition.effect == "mutating" else None
        bindings.append(
            ToolBinding(
                definition=definition,
                implementation=implementation,
                state_reader=state_reader,
            )
        )
    return tuple(bindings)


__all__ = [
    "EXPECTED_MUTATING_TOOL_NAMES",
    "RetailToolSession",
    "TOOL_VERSION",
    "build_tool_bindings",
    "build_tool_definitions",
    "fetch_tool_schema",
]
