"""ToolDefinition/ToolBinding surface for econevals's per-track tool set.

Mirrors ``tau3_retail.tools``'s role, but for a family whose tool bodies
are AERead's OWN logic rather than a delegated upstream implementation
(spec section 3: "AERead owns ... tool declarations for
get_*/write_notes/read_notes/submit_*"). Every binding declared here
delegates to ``EconevalsPlugin.dispatch_read_only``/``dispatch_submit`` --
the SAME two methods ``environment.py``'s own ``step`` calls to
independently re-derive a period's results -- so no tool body is ever
written twice; this module only supplies the kernel-facing
``ToolDefinition``/``ToolBinding`` wiring and the mutable per-episode
``EconevalsToolSession`` a scripted harness drives them against.

Unlike tau3.retail (whose tool schemas/effects are fetched live from
upstream's own ``Tool.openai_schema``/``mutates_state``, spec section 5 of
``tau3_retail_adapter_spec.md``), econevals has no upstream tool schema to
delegate to at all -- the read-only info/notes tools and the one
terminating submit tool per track are this adapter's own declared surface
(spec section 3). Input schemas below are therefore AERead's own, written
once here, not fetched from anywhere.

- ``tool_id`` = the track's own tool name (``environment.TRACK_TOOLS``),
  already grammar-valid (e.g. ``get_budget``, ``submit_purchase_plan``).
- ``tool_version`` = ``"0.1.0"`` for every tool.
- ``effect`` = ``"mutating"`` for exactly the one terminating submit tool
  per track, ``"read_only"`` for every ``get_*``/``write_notes``/
  ``read_notes`` tool -- equal to ``environment.py``'s own dispatch split
  (``dispatch_submit`` vs. ``dispatch_read_only``), because it *is* that
  split.
- ``idempotency_supported`` = ``False`` for every tool (a submit call
  advances the period and records an attempt; re-submitting the same
  arguments would record a second attempt, not a no-op).
- ``state_reader`` -- the one mutating submit tool per track reads
  ``EconevalsToolSession.attempts`` (spec section 3: "state_reader = the
  running attempt-history list"); read-only/notes tools have no
  ``state_reader`` at all, matching the spec's "required for every
  mutating tool" -- not for the other tools.
"""
from __future__ import annotations

from typing import Any, Mapping

from aeread.shared_runner.tools import ToolBinding, ToolDefinition

from .environment import EconevalsPlugin, TRACK_TOOLS, advance_period

TOOL_VERSION = "0.1.0"

_EMPTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

_WRITE_NOTES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"notes": {"type": "string"}},
    "required": ["notes"],
    "additionalProperties": False,
}

_READ_NOTES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"attempt_number": {"type": "integer"}},
    "required": ["attempt_number"],
    "additionalProperties": False,
}

# Per-tool-name override for the read-only/notes tools' input schema;
# every other declared read-only tool (the track's own ``get_*`` info
# tools) takes no arguments at all (``_EMPTY_SCHEMA``).
_READ_ONLY_SCHEMA_OVERRIDES: Mapping[str, Mapping[str, Any]] = {
    "write_notes": _WRITE_NOTES_SCHEMA,
    "read_notes": _READ_NOTES_SCHEMA,
}


def _submit_schema(arg_name: str) -> dict[str, Any]:
    """The one terminating submit tool's argument: exactly one named field,
    whose own value has no fixed shape (``environment._parse_dict`` accepts
    either an already-parsed object or a string an LLM produced -- upstream's
    own ``parse_dict`` 3-strategy fallback, spec's "Governing facts")."""
    return {
        "type": "object",
        "properties": {arg_name: {}},
        "required": [arg_name],
        "additionalProperties": False,
    }


def build_tool_definitions(track: str) -> dict[str, ToolDefinition]:
    """Build every declared ``ToolDefinition`` for one track (read-only info/
    notes tools plus the one terminating submit tool)."""
    tools = TRACK_TOOLS[track]
    definitions: dict[str, ToolDefinition] = {}
    for name in tools["read_only"]:
        schema = _READ_ONLY_SCHEMA_OVERRIDES.get(name, _EMPTY_SCHEMA)
        definitions[name] = ToolDefinition(
            tool_id=name,
            tool_version=TOOL_VERSION,
            effect="read_only",
            input_schema=schema,
            idempotency_supported=False,
        )
    submit_name = tools["submit_tool"]
    definitions[submit_name] = ToolDefinition(
        tool_id=submit_name,
        tool_version=TOOL_VERSION,
        effect="mutating",
        input_schema=_submit_schema(tools["submit_arg"]),
        idempotency_supported=False,
    )
    return definitions


class EconevalsToolSession:
    """Holds the one mutable in-episode state dict every econevals tool
    call needs (``period``/``termination``/``notes``/``attempts`` --
    ``EconevalsPlugin.initial_state``'s own shape).

    A session is intentionally dumb -- it never calls the bridge itself;
    ``build_tool_bindings``'s implementations read/mutate this same dict
    through ``EconevalsPlugin.dispatch_read_only``/``dispatch_submit``, and
    :meth:`advance_period` delegates to ``environment.advance_period`` --
    the SAME per-period bookkeeping ``step`` itself applies to its own FSM
    state -- so this mirror never diverges from what a live run would
    independently compute.
    """

    def __init__(self, state: Mapping[str, Any]) -> None:
        self._state: dict[str, Any] = {
            "track": state["track"],
            "period": state["period"],
            "termination": state["termination"],
            "notes": list(state["notes"]),
            "attempts": list(state["attempts"]),
        }

    def get_state(self) -> dict[str, Any]:
        return self._state

    def attempts(self) -> list[Any]:
        """The running attempt-history list -- this session's one
        ``state_reader`` (spec section 3), read before/after every mutating
        submit call so ``ToolRuntime`` can hash the state change into
        sealed evidence."""
        return self._state["attempts"]

    def advance_period(self, family_case: Mapping[str, Any]) -> None:
        advance_period(family_case, self._state)


def build_tool_bindings(
    plugin: EconevalsPlugin,
    family_case: Mapping[str, Any],
    session: EconevalsToolSession,
) -> tuple[ToolBinding, ...]:
    """Build every ``ToolBinding`` for one case's track, all delegating
    through ``plugin.dispatch_read_only``/``dispatch_submit`` against one
    live, shared ``session``.

    Every ``implementation`` here returns exactly the ``{"content",
    "error"}`` shape ``dispatch_read_only``/``dispatch_submit`` already
    produce -- the same shape ``environment.py``'s ``parse_action`` requires
    of every recorded ``tool_executions`` entry.
    """
    track = family_case["track"]
    definitions = build_tool_definitions(track)
    bindings: list[ToolBinding] = []
    for name, definition in definitions.items():

        async def implementation(
            arguments: Mapping[str, Any],
            *,
            _name: str = name,
            _mutating: bool = definition.effect == "mutating",
        ) -> dict[str, Any]:
            if _mutating:
                return plugin.dispatch_submit(
                    track, family_case, session.get_state(), _name, arguments
                )
            return plugin.dispatch_read_only(
                track, family_case, session.get_state(), _name, arguments
            )

        state_reader = session.attempts if definition.effect == "mutating" else None
        bindings.append(
            ToolBinding(
                definition=definition,
                implementation=implementation,
                state_reader=state_reader,
            )
        )
    return tuple(bindings)


__all__ = [
    "TOOL_VERSION",
    "EconevalsToolSession",
    "build_tool_bindings",
    "build_tool_definitions",
]
