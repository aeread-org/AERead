"""Kernel family plugin for the ``econevals`` objective-reference tracks.

Each pilot case is a single-agent, single-seat task: an agent submits one
decision per period (up to ``pins.max_steps`` periods) against a
deterministically generated instance, with feedback on each submission
delegated to the pinned upstream scoring primitive for its track. There is
no user turn, opponent, or hidden information (spec section
"visibility_policy": full observability) -- unlike tau3.retail's two-seat
alternating conversation, one phase ("period") self-loops once per period.

One logical action IS one period (spec section 1's case-manifest field
table): the agent's response for a period is a short burst of read-only
info/notes tool calls followed by exactly one terminating, mutating
submit-tool call (``submit_purchase_plan``/``submit_assignment``/
``set_prices``, one per track). Mirroring tau3.retail's
``ASSISTANT_PHASE`` burst design, the harness that produced this action
already executed every tool call against a live mirror of this same state
and recorded each result in ``tool_executions``; ``step`` independently
re-derives every result from its own state/bridge and hard-fails
(``RuntimeError``) on any divergence, exactly like
``Tau3RetailPlugin.step``'s tool-replay cross-check.

Read-only info/notes tools (``get_*``, ``write_notes``, ``read_notes``) are
pure, deterministic projections of already-generated case data and
in-episode state -- AERead's own logic, never delegated (there is nothing
upstream to delegate to: these are this adapter's own tool surface, spec
section 3). The one mutating submit tool per track calls the bridge for the
track's scoring primitive (``evaluate_alloc`` / ``is_valid_matching`` +
``get_blocking_pairs`` / ``get_profits``) to produce this period's feedback,
per spec section 3's adapter boundary ("Upstream owns ... scoring
primitives ... all invoked through the bridge, never reimplemented").

Scope note (this is milestone 2 of 3 -- see
``docs/econevals_adapter_spec.md``): this module implements the live
period-loop only. It deliberately does NOT implement upstream's exact
per-track retry-until-structurally-valid submission loop (e.g. scheduling's
``use_tool`` returns ``RETRY_ERROR`` and lets the SAME period continue until
a bijection is submitted) -- here, the terminating submit call always ends
the period, and a structurally invalid submission (a non-bijective
matching, an over-budget allocation) is recorded as an invalid attempt
rather than retried in-period. This is a deliberate, documented
simplification of a harness-level retry policy, analogous to how
tau3.retail's environment does not itself retry a malformed tool call --
matching structural retries are a harness concern to revisit if exact
per-period retry-count parity with upstream is ever required. Offline
replay without a live bridge (spec section 5's "no bridge subprocess
spawned") lands in a later milestone; the two ``MeasurementLeafSpec``s per
track (spec section 2) are declared in ``measurement.py`` and wired in
through ``build_scorer`` below, as of this milestone.

Milestone 3 of 3 adds the scripted harness that actually produces the
``tool_executions`` this module's own ``step`` cross-checks
(``harness.ScriptedEconevalsHarness``, driving the kernel ``ToolRuntime``
through tool bindings declared in ``tools.py`` -- both delegate to this
module's own ``dispatch_read_only``/``dispatch_submit`` and
``advance_period``, never a second tool-body implementation) and the
offline replayer (``replay.py``) that reproduces a recorded episode's
final state and both measurement leaves with zero further model calls.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .cases import (
    FAMILY_ID,
    FAMILY_VERSION,
    MAX_LLM_QUERIES_PER_PERIOD,
    TERMINATION_REASONS,
    TRACKS,
)
from .econevals_bridge import EconevalsBridge
from .measurement import EconevalsScorer
from .measurement import build_scorer as _build_measurement_scorer

PLUGIN_ID = "econevals_environment"
SCORER_ID = "econevals_scorer"
PERIOD_PHASE = "period"
SEAT_ID = "agent"
ROLE_ID = "assistant"

# Track -> (read-only tool names, submit tool name, submit argument name).
TRACK_TOOLS: Mapping[str, Mapping[str, Any]] = {
    "procurement": {
        "read_only": (
            "get_previous_purchase_data",
            "get_equipment_information",
            "get_budget",
            "get_attempt_number",
            "write_notes",
            "read_notes",
        ),
        "submit_tool": "submit_purchase_plan",
        "submit_arg": "purchase_plan",
    },
    "scheduling": {
        "read_only": (
            "get_previous_attempts_data",
            "get_worker_ids",
            "get_task_ids",
            "get_attempt_number",
            "write_notes",
            "read_notes",
        ),
        "submit_tool": "submit_assignment",
        "submit_arg": "assignment",
    },
    "pricing": {
        "read_only": (
            "get_previous_pricing_data",
            "get_product_ids",
            "get_attempt_number",
            "write_notes",
            "read_notes",
        ),
        "submit_tool": "set_prices",
        "submit_arg": "prices_dict_str",
    },
}


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    Mirrors ``tau3_retail.environment._set_termination``'s identical
    discipline: the case manifest publishes ``TERMINATION_REASONS`` as this
    family's termination vocabulary, and nothing in the kernel cross-checks
    a terminal reason against that declaration at runtime without this.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


def advance_period(family_case: Mapping[str, Any], state: dict[str, Any]) -> None:
    """Apply one period's completion bookkeeping: increment the period
    counter, and set ``"max_periods"`` termination once the case's own
    pinned ``pins.max_steps`` is reached.

    Public (milestone 3): this is the ONE place this bookkeeping is ever
    written. ``step`` calls it as the FSM's own authoritative per-period
    advance; ``tools.EconevalsToolSession.advance_period`` (the scripted
    harness's mirror state, ``harness.py``) calls the SAME function after
    executing a period's tool-call burst, so the harness's mirror never
    diverges from what a live FSM would independently compute for the next
    period's read-only responses (``get_attempt_number``,
    ``get_previous_*``).
    """
    state["period"] += 1
    if state["period"] >= family_case["pins"]["max_steps"]:
        _set_termination(state, "max_periods")


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _parse_dict(raw: Any) -> dict[str, Any]:
    """Parse an LLM's attempt at a dict, mirroring upstream's own 3-strategy fallback.

    Reproduces ``econ_evals.utils.helper_functions.parse_dict``'s documented
    contract (``literal_eval`` -> unicode-escape + ``literal_eval`` -> plain
    ``json.loads``) without importing upstream's dependency-bearing package
    into AERead's own Python 3.11 interpreter: this is a 20-line, dependency-
    free parsing helper, not a scoring primitive or a tool body (spec
    section 3 reserves those, not string parsing, for the bridge). Raises
    ``ValueError`` on total failure, exactly like upstream's own function.
    """
    if isinstance(raw, Mapping):
        # A parsed action's arguments are frozen (``ParseResult`` freezes
        # every nested container into ``MappingProxyType``/tuples), so a
        # well-formed dict argument arrives here as a ``Mapping``, not a
        # plain ``dict`` -- accept any mapping, matching the rest of this
        # codebase's own freeze convention (e.g. ``schemas._as_mapping``).
        return dict(raw)
    if not isinstance(raw, str):
        raise ValueError(f"could not parse input {raw!r}")
    from ast import literal_eval

    try:
        output = literal_eval(raw)
        if isinstance(output, dict):
            return output
    except (ValueError, SyntaxError):
        pass
    try:
        output = literal_eval(raw.encode("utf-8").decode("unicode_escape"))
        if isinstance(output, dict):
            return output
    except (ValueError, SyntaxError, UnicodeDecodeError):
        pass
    import json

    try:
        output = json.loads(raw)
        if isinstance(output, dict):
            return output
    except json.JSONDecodeError:
        pass
    raise ValueError(f"could not parse input {raw!r}")


def family_manifest() -> FamilyManifest:
    """Return the strict family declaration used by the trusted registry."""
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "single_agent_period_loop",
                "phase_specs": [PERIOD_PHASE],
                "needs_tools": True,
                "needs_sandbox": False,
            },
            "roles": {
                ROLE_ID: {"testable": True, "scripted_policies": ["scripted"]},
            },
            "measurement": {
                # Each of the three tracks declares its own two-leaf
                # (legality gate + objective) verifier (spec section 2);
                # this family-level declaration is a coarse descriptor, not
                # a literal stand-in for any one track's units/direction,
                # which differ (procurement maximizes workers_supported,
                # scheduling minimizes blocking_pairs, pricing maximizes
                # profit_usd). Bound fields are deliberately omitted here:
                # verifier_taxonomy.md section 5.3 explicitly warns
                # headroom-capture-style statistics are not automatically a
                # score in [0, 1].
                "primary_estimand": "econevals_headroom_capture",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "EconevalsPlugin | None" = None,
    bridge: EconevalsBridge | None = None,
) -> "EconevalsPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        plugin = EconevalsPlugin(bridge=bridge)
    registry.register(family_manifest(), plugin)
    return plugin


class EconevalsPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``."""

    def __init__(self, *, bridge: EconevalsBridge | None) -> None:
        self.bridge = bridge

    # -- validation / initial state -----------------------------------

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        required = {"track", "difficulty", "seed", "generated_instance", "gold_optimum", "pins"}
        if set(data) != required:
            raise ValueError(f"payload must contain exactly {sorted(required)}")
        if data["track"] not in TRACKS:
            raise ValueError(f"payload.track must be one of {TRACKS}")
        if data["difficulty"] != "Basic":
            raise ValueError("this milestone only admits Basic-difficulty payloads")
        if not isinstance(data["seed"], int) or isinstance(data["seed"], bool):
            raise ValueError("payload.seed must be an integer")
        if not isinstance(data["generated_instance"], dict):
            raise ValueError("payload.generated_instance must be an object")
        if not isinstance(data["gold_optimum"], dict):
            raise ValueError("payload.gold_optimum must be an object")
        pins = data["pins"]
        if not isinstance(pins, dict):
            raise ValueError("payload.pins must be an object")
        if not isinstance(pins.get("max_steps"), int) or pins["max_steps"] <= 0:
            raise ValueError("payload.pins.max_steps must be positive")
        return data

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        del cell
        return {
            "track": family_case["track"],
            "period": 0,
            "termination": None,
            "notes": [""],
            "attempts": [],
        }

    # -- phase graph ----------------------------------------------------

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        max_actions = int(family_case["pins"]["max_steps"])
        return (
            PhaseSpec(
                phase_id=PERIOD_PHASE,
                actor_selector=SEAT_ID,
                mode="single",
                # Keyed by ROLE (``role_by_seat[actor]``, scheduler.py's own
                # ``_eligible_actors`` contract), not by seat id -- the case
                # manifest's one seat is ``SeatSpec(id="agent",
                # role="assistant")`` (spec section 1), so ``ROLE_ID`` and
                # ``SEAT_ID`` are deliberately different strings here (unlike
                # tau3.retail, whose seat ids and roles happen to coincide).
                # Milestone 3 build note: this was keyed by ``SEAT_ID``
                # through milestone 2, undetected because no test drove a
                # real episode through the kernel scheduler
                # (``run_episode``/``_eligible_actors``) until this
                # milestone's harness did; fixed here as part of this
                # family's own code, not filed to the ledger.
                observation_schema_by_role={ROLE_ID: "econevals_period_observation_v1"},
                action_schema_by_role={ROLE_ID: "econevals_period_action_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(PERIOD_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del family_case, state
        if phase.phase_id != PERIOD_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        return (SEAT_ID,)

    # -- observation ------------------------------------------------------

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        if phase.phase_id != PERIOD_PHASE or seat_id != SEAT_ID:
            raise ValueError(f"seat {seat_id!r} is not active in phase {phase.phase_id!r}")
        track = family_case["track"]
        tools = TRACK_TOOLS[track]
        return {
            "track": track,
            "period": state["period"],
            "max_steps": family_case["pins"]["max_steps"],
            "max_llm_queries_per_period": MAX_LLM_QUERIES_PER_PERIOD,
            "num_attempts_so_far": len(state["attempts"]),
            "read_only_tools": list(tools["read_only"]),
            "submit_tool": tools["submit_tool"],
            "submit_arg": tools["submit_arg"],
        }

    # -- action parsing ----------------------------------------------

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del state
        if phase.phase_id != PERIOD_PHASE or seat_id != SEAT_ID:
            return ParseResult.failure("seat_phase_mismatch")
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        tool_calls = raw.get("tool_calls")
        tool_executions = raw.get("tool_executions")
        if not isinstance(tool_calls, list) or not tool_calls:
            return ParseResult.failure("period_action_missing_tool_calls")
        if len(tool_calls) > MAX_LLM_QUERIES_PER_PERIOD + 1:
            return ParseResult.failure("period_action_exceeds_query_budget")
        if not isinstance(tool_executions, list) or len(tool_executions) != len(tool_calls):
            return ParseResult.failure("tool_execution_count_mismatch")

        track = family_case["track"]
        submit_tool = TRACK_TOOLS[track]["submit_tool"]
        parsed_calls: list[dict[str, Any]] = []
        for index, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                return ParseResult.failure("invalid_tool_call")
            call_id = tool_call.get("id", "")
            name = tool_call.get("name")
            arguments = tool_call.get("arguments")
            if not isinstance(call_id, str):
                return ParseResult.failure("invalid_tool_call_id")
            if not isinstance(name, str) or not name.strip():
                return ParseResult.failure("invalid_tool_name")
            if not isinstance(arguments, dict):
                return ParseResult.failure("invalid_tool_arguments")
            is_last = index == len(tool_calls) - 1
            if is_last != (name == submit_tool):
                return ParseResult.failure("submit_tool_must_be_the_final_call")
            parsed_calls.append({"id": call_id, "name": name, "arguments": arguments})

        parsed_executions: list[dict[str, Any]] = []
        for tool_call, execution in zip(parsed_calls, tool_executions):
            if not isinstance(execution, dict):
                return ParseResult.failure("invalid_tool_execution")
            result = execution.get("result")
            if (
                execution.get("tool_call_id") != tool_call["id"]
                or execution.get("name") != tool_call["name"]
                or execution.get("arguments") != tool_call["arguments"]
                or not isinstance(result, dict)
                or set(result) != {"content", "error"}
                or not isinstance(result["error"], bool)
            ):
                return ParseResult.failure("tool_execution_mismatch")
            parsed_executions.append(
                {
                    "tool_call_id": execution["tool_call_id"],
                    "name": execution["name"],
                    "arguments": execution["arguments"],
                    "result": {"content": result["content"], "error": result["error"]},
                }
            )
        return ParseResult.success(
            {"tool_calls": parsed_calls, "tool_executions": parsed_executions}
        )

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, state, action
        if phase.phase_id != PERIOD_PHASE or seat_id != SEAT_ID:
            return LegalityResult.illegal("seat_phase_mismatch")
        return LegalityResult.legal_action()

    # -- transition -------------------------------------------------------

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        if phase.phase_id != PERIOD_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        new_state = _plain(state)
        track = family_case["track"]
        action = actions[SEAT_ID].action
        tool_calls = action["tool_calls"]
        tool_executions = action["tool_executions"]

        for index, tool_call in enumerate(tool_calls):
            name = tool_call["name"]
            arguments = tool_call["arguments"]
            is_last = index == len(tool_calls) - 1
            if is_last:
                computed = self.dispatch_submit(track, family_case, new_state, name, arguments)
            else:
                computed = self.dispatch_read_only(track, family_case, new_state, name, arguments)
            recorded = tool_executions[index]["result"]
            # Compare through the same plain (unfrozen) shape on both sides:
            # ``recorded`` came out of ``ParseResult``'s freeze (nested
            # lists became tuples, nested dicts became ``MappingProxyType``),
            # while ``computed`` is a fresh, unfrozen dict -- structurally
            # identical values would otherwise compare unequal purely
            # because one side is tuples and the other is lists.
            if _plain(recorded) != _plain(computed):
                raise RuntimeError(
                    "tool replay result differs from harness execution for "
                    f"{name!r}: recorded {recorded!r}, computed {computed!r}"
                )

        advance_period(family_case, new_state)

        return TransitionResult(
            state=new_state,
            next_phase_id=(None if new_state["termination"] else PERIOD_PHASE),
            consequences={"tool_calls": len(tool_calls)},
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        return {
            "reason": reason,
            "period": state["period"],
            "num_attempts": len(state["attempts"]),
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "period_count": terminal["period"],
            "num_attempts": terminal["num_attempts"],
        }

    def build_scorer(self, family_case: Mapping[str, Any]) -> EconevalsScorer:
        """Build this case's two-leaf verifier declarations (spec section 2).

        Delegates entirely to ``measurement.build_scorer``: this hook is
        just the ``PluginRegistry``-facing entry point, never a second
        place that declares or computes a leaf.
        """
        return _build_measurement_scorer(family_case)

    def build_reference_providers(
        self, family_case: Mapping[str, Any]
    ) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None

    # -- tool dispatch (AERead-owned; spec section 3) --------------------
    #
    # Public (milestone 3): ``dispatch_read_only``/``dispatch_submit`` are
    # this adapter's ONE tool-body implementation -- ``step`` calls them to
    # independently re-derive a period's results from its own FSM state, and
    # ``tools.build_tool_bindings`` (``harness.py``'s scripted harness)
    # calls the SAME two methods, on its own live mirror state, to actually
    # produce a period's tool results in the first place. No tool body is
    # ever written twice.

    def _require_bridge(self) -> EconevalsBridge:
        if self.bridge is None:
            raise RuntimeError("econevals execution requires a provisioned EconevalsBridge")
        return self.bridge

    def dispatch_read_only(
        self,
        track: str,
        family_case: Mapping[str, Any],
        state: dict[str, Any],
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        content = self._read_only_content(track, family_case, state, name, arguments)
        error = isinstance(content, dict) and "error" in content
        return {"content": content, "error": error}

    def _read_only_content(
        self,
        track: str,
        family_case: Mapping[str, Any],
        state: dict[str, Any],
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if name not in TRACK_TOOLS[track]["read_only"]:
            return {"error": "invalid_tool", "message": f"invalid tool {name!r} for track {track!r}"}
        if name == "get_attempt_number":
            return {"attempt_number": len(state["attempts"])}
        if name == "write_notes":
            notes = arguments.get("notes")
            if not isinstance(notes, str):
                return {"error": "malformed_input", "message": "expected a string 'notes' argument"}
            state["notes"][-1] += notes
            return {"status": "ok"}
        if name == "read_notes":
            attempt_number = arguments.get("attempt_number")
            if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
                return {
                    "error": "malformed_input",
                    "message": "expected an integer 'attempt_number' argument",
                }
            if 0 <= attempt_number < len(state["notes"]):
                return {"notes": state["notes"][attempt_number]}
            return {"error": "not_found", "message": f"no notes for attempt number {attempt_number}"}

        instance = family_case["generated_instance"]
        if track == "procurement":
            if name == "get_equipment_information":
                return {"menu": instance["menu"]}
            if name == "get_budget":
                return {"budget": instance["budget"]}
            if name == "get_previous_purchase_data":
                return {"previous_attempts": state["attempts"]}
        elif track == "scheduling":
            if name == "get_worker_ids":
                return {"worker_ids": instance["worker_ids"]}
            if name == "get_task_ids":
                return {"task_ids": instance["task_ids"]}
            if name == "get_previous_attempts_data":
                return {"previous_attempts": state["attempts"]}
        elif track == "pricing":
            if name == "get_product_ids":
                return {"product_ids": instance["product_ids"]}
            if name == "get_previous_pricing_data":
                return {"previous_attempts": state["attempts"]}
        raise AssertionError(f"declared read-only tool {name!r} has no dispatch for {track!r}")

    def dispatch_submit(
        self,
        track: str,
        family_case: Mapping[str, Any],
        state: dict[str, Any],
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected = TRACK_TOOLS[track]["submit_tool"]
        if name != expected:
            content = {"error": "invalid_tool", "message": f"expected {expected!r}, got {name!r}"}
            return {"content": content, "error": True}
        if track == "procurement":
            content = self._submit_procurement(family_case, state, arguments)
        elif track == "scheduling":
            content = self._submit_scheduling(family_case, state, arguments)
        elif track == "pricing":
            content = self._submit_pricing(family_case, state, arguments)
        else:
            raise ValueError(f"unknown track: {track!r}")
        error = bool(content.get("error"))
        return {"content": content, "error": error}

    def _record_attempt(self, state: dict[str, Any], attempt: Mapping[str, Any]) -> None:
        state["attempts"].append(dict(attempt))
        state["notes"].append("")

    def _submit_procurement(
        self, family_case: Mapping[str, Any], state: dict[str, Any], arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        instance = family_case["generated_instance"]
        arg_name = TRACK_TOOLS["procurement"]["submit_arg"]
        raw = arguments.get(arg_name)
        try:
            submitted = _parse_dict(raw)
        except ValueError:
            attempt = {
                "period": state["period"],
                "error": "malformed_input",
                "error_message": f"could not parse {arg_name} as a dict",
            }
            self._record_attempt(state, attempt)
            return dict(attempt)

        menu_ids = set(instance["menu"])
        unknown_ids = set(submitted) - menu_ids
        if unknown_ids:
            # Defensive pre-validation (spec section 3): never let an
            # unknown offer id reach upstream's Menu.__getitem__, which
            # asserts membership and would otherwise surface as an
            # uncaught AssertionError instead of a graceful is_feasible=False.
            attempt = {
                "period": state["period"],
                "error": "illegal_action",
                "error_message": f"unknown offer ids: {sorted(unknown_ids)}",
            }
            self._record_attempt(state, attempt)
            return dict(attempt)

        alloc = {entry_id: 0 for entry_id in menu_ids}
        for entry_id, quantity in submitted.items():
            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
                attempt = {
                    "period": state["period"],
                    "error": "malformed_input",
                    "error_message": f"non-numeric quantity for {entry_id!r}: {quantity!r}",
                }
                self._record_attempt(state, attempt)
                return dict(attempt)
            alloc[entry_id] = int(quantity)

        bridge = self._require_bridge()
        result = bridge.procurement_evaluate(
            instance=instance,
            alloc=alloc,
            group_weights=instance["group_weights"],
            agg_type=instance["agg_type"],
        )
        attempt = {
            "period": state["period"],
            "error": False,
            "alloc": alloc,
            "is_feasible": result["is_feasible"],
            "invalid_reason": result["invalid_reason"],
            "cost": result["cost"],
            "utility": result["utility"],
        }
        self._record_attempt(state, attempt)
        return dict(attempt)

    def _submit_scheduling(
        self, family_case: Mapping[str, Any], state: dict[str, Any], arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        instance = family_case["generated_instance"]
        arg_name = TRACK_TOOLS["scheduling"]["submit_arg"]
        raw = arguments.get(arg_name)
        try:
            matching = _parse_dict(raw)
        except ValueError:
            attempt = {
                "period": state["period"],
                "error": "malformed_input",
                "error_message": f"could not parse {arg_name} as a dict",
            }
            self._record_attempt(state, attempt)
            return dict(attempt)
        matching = {str(worker): str(task) for worker, task in matching.items()}

        bridge = self._require_bridge()
        validity = bridge.scheduling_validate(
            matching=matching, worker_ids=instance["worker_ids"], task_ids=instance["task_ids"]
        )
        if not validity["valid"]:
            attempt = {
                "period": state["period"],
                "error": False,
                "matching": matching,
                "valid": False,
                "reason": validity["reason"],
                "blocking_pairs": None,
            }
            self._record_attempt(state, attempt)
            return dict(attempt)

        blocking_pairs = bridge.scheduling_blocking_pairs(
            matching=matching,
            worker_prefs=instance["worker_prefs"],
            task_prefs=instance["task_prefs"],
        )
        attempt = {
            "period": state["period"],
            "error": False,
            "matching": matching,
            "valid": True,
            "reason": "",
            "blocking_pairs": blocking_pairs,
        }
        self._record_attempt(state, attempt)
        return dict(attempt)

    def _submit_pricing(
        self, family_case: Mapping[str, Any], state: dict[str, Any], arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        instance = family_case["generated_instance"]
        arg_name = TRACK_TOOLS["pricing"]["submit_arg"]
        raw = arguments.get(arg_name)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            attempt = {
                "period": state["period"],
                "error": "malformed_input",
                "error_message": f"{arg_name} must be a dict, not a bare number",
            }
            self._record_attempt(state, attempt)
            return dict(attempt)
        try:
            prices = _parse_dict(raw)
        except ValueError:
            attempt = {
                "period": state["period"],
                "error": "malformed_input",
                "error_message": f"could not parse {arg_name} as a dict",
            }
            self._record_attempt(state, attempt)
            return dict(attempt)

        product_ids = set(instance["product_ids"])
        missing = product_ids - set(prices)
        extra = set(prices) - product_ids
        if missing or extra:
            attempt = {
                "period": state["period"],
                "error": "illegal_action",
                "error_message": f"missing prices for {sorted(missing)}, unknown products {sorted(extra)}",
            }
            self._record_attempt(state, attempt)
            return dict(attempt)
        for product_id, price in prices.items():
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                attempt = {
                    "period": state["period"],
                    "error": "malformed_input",
                    "error_message": f"non-numeric price for {product_id!r}: {price!r}",
                }
                self._record_attempt(state, attempt)
                return dict(attempt)

        bridge = self._require_bridge()
        profits = bridge.pricing_profits(
            instance=instance, period=state["period"], prices=prices
        )
        attempt = {
            "period": state["period"],
            "error": False,
            "prices": {product_id: float(price) for product_id, price in prices.items()},
            "profits": profits,
        }
        self._record_attempt(state, attempt)
        return dict(attempt)


__all__ = [
    "PERIOD_PHASE",
    "PLUGIN_ID",
    "ROLE_ID",
    "SCORER_ID",
    "SEAT_ID",
    "TRACK_TOOLS",
    "EconevalsPlugin",
    "advance_period",
    "family_manifest",
    "register_plugin",
]
