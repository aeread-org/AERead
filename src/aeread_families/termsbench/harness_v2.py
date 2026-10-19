"""Harness 2.0: the paper's agent interface (Appendix H.1.5 and Table 11) for the reproduction.

One model call per agent turn. The user message is the observation alone, as one JSON object with the paper's five
top-level keys (:meth:`environment_v2.TermsBenchPluginV2.observe`); the paper's user message "contains no additional
natural-language instructions", so the phase id, seat and schemas that harness 1.1 wraps around it are not sent. The
system prompt is the profile's (:mod:`.prompts_v2`, one profile per agent role).

The model answers in free text and the move is found by balanced-brace scanning (Table 11, "free text, balanced-brace
JSON extraction"): the first ``{...}`` span, with braces inside JSON strings ignored, that parses as a JSON object.
If none does, the family receives ``{"raw_text": text}``, which it does not parse, and the plugin plays the paper's
fallback. As in harness 1.1 the harness never judges a move (TB-D-02); only an empty response is a route fault.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from aeread.shared_runner.model_call.harness import AttemptContext, CanonicalMessage, HarnessOutput
from aeread.shared_runner.registry import HarnessRequirements
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ProviderFailure

from .live import AGENT_SEAT, TermsBenchJsonHarness
from .environment import AGENT_PHASE


def balanced_json_object(text: str) -> dict[str, Any] | None:
    """The first balanced ``{...}`` span of ``text`` that parses as a JSON object, ignoring braces in strings."""
    start = text.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(value, Mapping):
                        return dict(value)
                    break
        start = text.find("{", start + 1)
    return None


class TermsBenchPaperHarness(TermsBenchJsonHarness):
    id = "termsbench_paper"
    version = "2.0"
    requires = HarnessRequirements(
        provider=frozenset(), tools="none", memory=frozenset({"disabled"}), owns_retries=False, owns_tools=True,
        replayable=True, blocking=False, spawns_subagents=False,
    )

    @staticmethod
    def _request_message(request: Any) -> CanonicalMessage:
        return CanonicalMessage(role="user", content=canonical_json_bytes(request.observation).decode("utf-8"))

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        if request.phase_id != AGENT_PHASE or request.seat_id != AGENT_SEAT:
            raise ProviderFailure("harness_contract", f"termsbench harness asked for {request.seat_id!r} in phase "
                                  f"{request.phase_id!r}; only the agent seat is a model", retryable=False)
        turn = await ctx.model.complete(messages=(self._request_message(request),), response_mode="text")
        text = (turn.text or "").strip()
        if not text:
            raise ProviderFailure("empty_response", "termsbench agent turn returned an empty response", retryable=True)
        value = balanced_json_object(text)
        return HarnessOutput(action=value if value is not None else {"raw_text": text}, claimed_tool_calls=(),
                             rounds_used=1, notes={})


__all__ = ["TermsBenchPaperHarness", "balanced_json_object"]
