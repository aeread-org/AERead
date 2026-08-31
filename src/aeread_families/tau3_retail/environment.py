"""Kernel family plugin for pinned tau2-bench retail conversations.

The kernel schedules one user turn and one assistant turn at a time. An
assistant turn is one logical action containing the complete upstream-style
burst: zero or more assistant tool-call messages, each followed by delegated
tool results, and one final assistant text message. Only ``step`` applies the
burst or changes the canonical family state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
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
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
)
from .measurement import Tau3RetailScorer, build_scorer as build_measurement_scorer
from .tau2_bridge import Tau2Bridge

PLUGIN_ID = "tau3_retail_environment"
SCORER_ID = "tau3_retail_scorer"
USER_PHASE = "user_turn"
ASSISTANT_PHASE = "assistant_turn"
MAX_TOOL_ERRORS = 10
STOP_SIGNALS = ("###STOP###", "###TRANSFER###", "###OUT-OF-SCOPE###")


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    The case manifest publishes ``TERMINATION_REASONS`` as this family's
    termination vocabulary. Nothing in the kernel cross-checks a terminal
    reason against that declaration at runtime, so without this the two drift
    silently -- as they already had: the manifest advertised ``agent_stop``,
    which retail can never emit, and omitted ``too_many_errors``, which it can.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


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
                "topology": "alternating_conversation",
                "phase_specs": [USER_PHASE, ASSISTANT_PHASE],
                "needs_tools": True,
                "needs_sandbox": False,
            },
            "roles": {
                "assistant": {"testable": True, "scripted_policies": ["scripted"]},
                "user": {"testable": True, "scripted_policies": ["scripted"]},
            },
            "measurement": {
                "primary_estimand": "retail_task_reward",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "optimum_lower_bound": "0",
                "optimum_upper_bound": "1",
                "optimum_upper_bound_kind": "known",
                "bound_status": "upstream_defined",
                "outcome_support": "unit_interval",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "Tau3RetailPlugin | None" = None,
    upstream_root: Path | str | None = None,
    bridge: Tau2Bridge | None = None,
) -> "Tau3RetailPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if upstream_root is None:
            raise ValueError("upstream_root is required when plugin is not supplied")
        plugin = Tau3RetailPlugin(upstream_root=upstream_root, bridge=bridge)
    registry.register(family_manifest(), plugin)
    return plugin


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _text_message(role: str, content: str) -> dict[str, Any]:
    return {"role": role, "content": content, "tool_calls": None}


def _tool_call_message(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": tool_calls}


class Tau3RetailPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``."""

    def __init__(
        self,
        *,
        upstream_root: Path | str,
        bridge: Tau2Bridge | None,
    ) -> None:
        self.upstream_root = Path(upstream_root)
        self.bridge = bridge

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != {"task", "pins"}:
            raise ValueError("payload must contain exactly task and pins")
        task = data["task"]
        pins = data["pins"]
        if not isinstance(task, dict) or not isinstance(pins, dict):
            raise ValueError("payload.task and payload.pins must be objects")
        if not isinstance(task.get("id"), str) or not task["id"]:
            raise ValueError("payload.task.id must be a non-empty string")
        if not isinstance(task.get("user_scenario"), dict):
            raise ValueError("payload.task.user_scenario must be an object")
        if task.get("initial_state") is not None:
            raise ValueError("retail/base adapter requires upstream initial_state=null")
        if pins.get("upstream_repo") != UPSTREAM_REPO:
            raise ValueError("payload pins the wrong upstream repository")
        if pins.get("upstream_commit") != UPSTREAM_COMMIT:
            raise ValueError("payload pins the wrong upstream commit")
        if not isinstance(pins.get("max_steps"), int) or pins["max_steps"] <= 0:
            raise ValueError("payload.pins.max_steps must be positive")
        tool_schema_hash = pins.get("tool_schema_sha256")
        if tool_schema_hash is None:
            if not isinstance(pins.get("tool_schema_sha256_unavailable_reason"), str):
                raise ValueError(
                    "a null tool_schema_sha256 requires an explicit derivation gap"
                )
        elif (
            not isinstance(tool_schema_hash, str)
            or len(tool_schema_hash) != 64
            or any(character not in "0123456789abcdef" for character in tool_schema_hash)
        ):
            raise ValueError("payload.pins.tool_schema_sha256 is malformed")

        revision = subprocess.run(
            ["git", "-C", str(self.upstream_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if revision.returncode != 0:
            raise ValueError(
                "upstream_root is not a readable git checkout: "
                f"{revision.stderr.strip()}"
            )
        if revision.stdout.strip() != UPSTREAM_COMMIT:
            raise ValueError(
                "upstream checkout revision mismatch: "
                f"expected {UPSTREAM_COMMIT}, got {revision.stdout.strip()}"
            )
        status = subprocess.run(
            ["git", "-C", str(self.upstream_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout:
            raise ValueError("upstream checkout must be clean at the pinned revision")

        retail = self.upstream_root / "data" / "tau2" / "domains" / "retail"
        db_path = retail / "db.json"
        pin_paths = {
            "db_sha256": db_path,
            "tasks_sha256": retail / "tasks.json",
            "policy_sha256": retail / "policy.md",
            "user_sim_guidelines_sha256": (
                self.upstream_root
                / "data"
                / "tau2"
                / "user_simulator"
                / "simulation_guidelines.md"
            ),
        }
        for pin_name, path in pin_paths.items():
            if not path.is_file():
                raise ValueError(f"pinned upstream file is missing: {path}")
            actual = _sha256_file(path)
            if pins.get(pin_name) != actual:
                raise ValueError(
                    f"payload {pin_name} mismatch: authored {pins.get(pin_name)!r}, "
                    f"actual {actual!r}"
                )
        if pins.get("db_bytes") != db_path.stat().st_size:
            raise ValueError("payload db_bytes does not match pinned db.json")
        upstream_tasks = json.loads(
            (retail / "tasks.json").read_text(encoding="utf-8")
        )
        matching_tasks = [
            record for record in upstream_tasks if record.get("id") == task["id"]
        ]
        if len(matching_tasks) != 1 or matching_tasks[0] != task:
            raise ValueError(
                "payload.task does not exactly match its pinned tasks.json record"
            )
        return data

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        del cell
        bridge = self._require_bridge()
        pins = family_case["pins"]
        schema = bridge.fetch_tool_schema()
        authored_schema_hash = pins.get("tool_schema_sha256")
        if (
            authored_schema_hash is not None
            and authored_schema_hash != schema["tool_schema_sha256"]
        ):
            raise ValueError(
                "payload tool_schema_sha256 does not match delegated upstream schema"
            )

        db_path = (
            self.upstream_root
            / "data"
            / "tau2"
            / "domains"
            / "retail"
            / "db.json"
        )
        db = bridge.normalize_db(json.loads(db_path.read_text(encoding="utf-8")))
        greeting = pins["greeting_message"]
        if not isinstance(greeting, str) or not greeting.strip():
            raise ValueError("payload.pins.greeting_message must be non-empty")
        return {
            "db": db,
            "db_hash": bridge.hash_db(db),
            "messages": bridge.normalize_messages(
                [_text_message("assistant", greeting)]
            ),
            "upstream_step_count": 0,
            "num_tool_errors": 0,
            "termination": None,
            "live_tool_schema_sha256": schema["tool_schema_sha256"],
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        max_actions = int(family_case["pins"]["max_steps"])
        return (
            PhaseSpec(
                phase_id=USER_PHASE,
                actor_selector="user",
                mode="single",
                observation_schema_by_role={"user": "tau3_retail_user_observation_v1"},
                action_schema_by_role={"user": "tau3_retail_user_message_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(ASSISTANT_PHASE,),
            ),
            PhaseSpec(
                phase_id=ASSISTANT_PHASE,
                actor_selector="assistant",
                mode="single",
                observation_schema_by_role={
                    "assistant": "tau3_retail_assistant_observation_v1"
                },
                action_schema_by_role={"assistant": "tau3_retail_assistant_burst_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(USER_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del family_case, state
        if phase.phase_id == USER_PHASE:
            return ("user",)
        if phase.phase_id == ASSISTANT_PHASE:
            return ("assistant",)
        raise ValueError(f"unknown phase: {phase.phase_id}")

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        if phase.phase_id == ASSISTANT_PHASE and seat_id == "assistant":
            policy_path = (
                self.upstream_root
                / "data"
                / "tau2"
                / "domains"
                / "retail"
                / "policy.md"
            )
            return {
                "policy": policy_path.read_text(encoding="utf-8"),
                "policy_sha256": family_case["pins"]["policy_sha256"],
                "tool_schema_sha256": state["live_tool_schema_sha256"],
                "messages": self._assistant_view(state["messages"]),
                "upstream_step_count": state["upstream_step_count"],
                "num_tool_errors": state["num_tool_errors"],
                "max_steps": family_case["pins"]["max_steps"],
            }
        if phase.phase_id == USER_PHASE and seat_id == "user":
            guidelines_path = (
                self.upstream_root
                / "data"
                / "tau2"
                / "user_simulator"
                / "simulation_guidelines.md"
            )
            return {
                "user_scenario": _plain(family_case["task"]["user_scenario"]),
                "simulation_guidelines": guidelines_path.read_text(encoding="utf-8"),
                "simulation_guidelines_sha256": family_case["pins"][
                    "user_sim_guidelines_sha256"
                ],
                "messages": self._user_view(state["messages"]),
                "upstream_step_count": state["upstream_step_count"],
                "max_steps": family_case["pins"]["max_steps"],
            }
        raise ValueError(f"seat {seat_id!r} is not active in phase {phase.phase_id!r}")

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, state
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        if phase.phase_id == USER_PHASE and seat_id == "user":
            content = raw.get("content")
            if not isinstance(content, str) or not content.strip():
                return ParseResult.failure("invalid_user_message")
            message = raw
            message["role"] = "user"
            message["content"] = content
            message["tool_calls"] = None
            return ParseResult.success({"message": message})
        if phase.phase_id != ASSISTANT_PHASE or seat_id != "assistant":
            return ParseResult.failure("seat_phase_mismatch")
        messages = raw.get("messages")
        if not isinstance(messages, list) or not messages:
            return ParseResult.failure("assistant_burst_missing_messages")

        parsed_messages: list[dict[str, Any]] = []
        ordered_calls: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                return ParseResult.failure("invalid_assistant_message")
            content = message.get("content")
            tool_calls = message.get("tool_calls")
            has_text = isinstance(content, str) and bool(content.strip())
            has_tools = isinstance(tool_calls, list) and bool(tool_calls)
            if has_text == has_tools:
                return ParseResult.failure("assistant_message_requires_text_xor_tools")
            if has_text:
                if index != len(messages) - 1:
                    return ParseResult.failure("assistant_text_must_end_burst")
                parsed_message = message
                parsed_message["role"] = "assistant"
                parsed_message["content"] = content
                parsed_message["tool_calls"] = None
                parsed_messages.append(parsed_message)
                continue
            parsed_calls: list[dict[str, Any]] = []
            for tool_call in tool_calls:
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
                parsed_calls.append(
                    {
                        "id": call_id,
                        "name": name,
                        "arguments": arguments,
                        "requestor": "assistant",
                    }
                )
                ordered_calls.append(parsed_calls[-1])
            parsed_message = message
            parsed_message["role"] = "assistant"
            parsed_message["content"] = None
            parsed_message["tool_calls"] = parsed_calls
            parsed_messages.append(parsed_message)
        terminated_after_tools = raw.get("terminated_after_tools", False)
        if not isinstance(terminated_after_tools, bool):
            return ParseResult.failure("invalid_burst_termination_marker")
        if parsed_messages[-1]["content"] is None and not terminated_after_tools:
            return ParseResult.failure("assistant_burst_requires_final_text")
        if parsed_messages[-1]["content"] is not None and terminated_after_tools:
            return ParseResult.failure("invalid_burst_termination_marker")
        raw_executions = raw.get("tool_executions", [])
        if not isinstance(raw_executions, list) or len(raw_executions) != len(
            ordered_calls
        ):
            return ParseResult.failure("tool_execution_count_mismatch")
        executions: list[dict[str, Any]] = []
        for tool_call, execution in zip(ordered_calls, raw_executions):
            if not isinstance(execution, dict):
                return ParseResult.failure("invalid_tool_execution")
            result = execution.get("result")
            if (
                execution.get("tool_call_id") != tool_call["id"]
                or execution.get("name") != tool_call["name"]
                or execution.get("arguments") != tool_call["arguments"]
                or not isinstance(result, dict)
                or set(result) != {"content", "error"}
                or not isinstance(result["content"], str)
                or not isinstance(result["error"], bool)
                or not isinstance(execution.get("post_db_hash"), str)
                or not isinstance(execution.get("invocation_record_id"), str)
            ):
                return ParseResult.failure("tool_execution_mismatch")
            executions.append(
                {
                    "tool_call_id": execution["tool_call_id"],
                    "name": execution["name"],
                    "arguments": execution["arguments"],
                    "result": result,
                    "post_db_hash": execution["post_db_hash"],
                    "invocation_record_id": execution["invocation_record_id"],
                }
            )
        return ParseResult.success(
            {
                "messages": parsed_messages,
                "tool_executions": executions,
                "terminated_after_tools": terminated_after_tools,
            }
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
        expected = "user" if phase.phase_id == USER_PHASE else "assistant"
        if seat_id != expected:
            return LegalityResult.illegal("seat_phase_mismatch")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        new_state = _plain(state)
        if phase.phase_id == USER_PHASE:
            bridge = self._require_bridge()
            action = actions["user"].action
            message = action["message"]
            content = message["content"]
            new_state["messages"].extend(
                bridge.normalize_messages([_plain(message)])
            )
            new_state["upstream_step_count"] += 1
            if any(signal in content for signal in STOP_SIGNALS):
                _set_termination(new_state, "user_stop")
            self._apply_post_delivery_termination(family_case, new_state)
            return TransitionResult(
                state=new_state,
                next_phase_id=(None if new_state["termination"] else ASSISTANT_PHASE),
                consequences={"upstream_steps": 1, "tool_calls": 0},
            )

        if phase.phase_id != ASSISTANT_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        bridge = self._require_bridge()
        action = actions["assistant"].action
        execution_index = 0
        start_count = new_state["upstream_step_count"]
        tool_call_count = 0
        for message in action["messages"]:
            if message["tool_calls"] is None:
                new_state["messages"].extend(
                    bridge.normalize_messages([_plain(message)])
                )
                new_state["upstream_step_count"] += 1
                self._apply_post_delivery_termination(family_case, new_state)
                break

            new_state["messages"].extend(
                bridge.normalize_messages([_plain(message)])
            )
            new_state["upstream_step_count"] += 1
            for tool_call in message["tool_calls"]:
                response = bridge.call_tool(
                    db=new_state["db"],
                    tool_name=tool_call["name"],
                    arguments=tool_call["arguments"],
                    requestor="assistant",
                    tool_call_id=tool_call["id"],
                )
                recorded = action["tool_executions"][execution_index]
                execution_index += 1
                delegated_result = {
                    "content": response["content"],
                    "error": response["error"],
                }
                if recorded["result"] != delegated_result:
                    raise RuntimeError(
                        "tool replay result differs from harness execution for "
                        f"{tool_call['name']!r}"
                    )
                if recorded["post_db_hash"] != response["db_hash"]:
                    raise RuntimeError(
                        "tool replay DB hash differs from harness execution for "
                        f"{tool_call['name']!r}"
                    )
                new_state["db"] = response["db"]
                new_state["db_hash"] = response["db_hash"]
                if response["error"]:
                    new_state["num_tool_errors"] += 1
                new_state["messages"].append(response["tool_message"])
                tool_call_count += 1
            # Upstream executes every call in one assistant->environment hop.
            new_state["upstream_step_count"] += 1
            self._apply_post_delivery_termination(family_case, new_state)
            if new_state["termination"] is not None:
                break

        if action["terminated_after_tools"] and new_state["termination"] is None:
            raise RuntimeError(
                "harness marked a tool-only burst terminal but replay did not terminate"
            )

        return TransitionResult(
            state=new_state,
            next_phase_id=(None if new_state["termination"] else USER_PHASE),
            consequences={
                "upstream_steps": new_state["upstream_step_count"] - start_count,
                "tool_calls": tool_call_count,
            },
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
            "db_hash": state["db_hash"],
            "upstream_step_count": state["upstream_step_count"],
            "num_tool_errors": state["num_tool_errors"],
            "message_count": len(state["messages"]),
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "final_db_sha256": terminal["db_hash"],
            "upstream_step_count": terminal["upstream_step_count"],
            "message_count": terminal["message_count"],
        }

    def build_scorer(self, family_case: Mapping[str, Any]) -> Tau3RetailScorer:
        """Return the two declared measurement leaves plus their scorers.

        See ``measurement.py`` (spec section 7): leaf 1 (deterministic DB
        state) is declared for every case; leaf 2 (judge-dependent NL
        assertions) only when ``family_case["task"]`` actually carries a
        non-empty ``nl_assertions`` list. The current kernel does not yet
        call ``build_scorer`` itself (see ``measurement.py``'s
        ``Tau3RetailScorer`` docstring); this makes the declaration and both
        scorers live the day it does.
        """
        return build_measurement_scorer(family_case["task"], family_case["pins"])

    def build_reference_providers(
        self, family_case: Mapping[str, Any]
    ) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None

    def _require_bridge(self) -> Tau2Bridge:
        if self.bridge is None:
            raise RuntimeError("tau3.retail execution requires a provisioned Tau2Bridge")
        return self.bridge

    @staticmethod
    def _assistant_view(messages: Any) -> list[dict[str, Any]]:
        visible: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role in {"assistant", "user"}:
                visible.append(_plain(message))
            elif role == "tool" and message.get("requestor") == "assistant":
                visible.append(_plain(message))
        return visible

    @staticmethod
    def _user_view(messages: Any) -> list[dict[str, Any]]:
        visible: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role == "assistant" and message.get("tool_calls") is None:
                flipped = _plain(message)
                flipped["role"] = "user"
                visible.append(flipped)
            elif role == "user":
                flipped = _plain(message)
                flipped["role"] = "assistant"
                visible.append(flipped)
            elif role == "tool" and message.get("requestor") == "user":
                visible.append(_plain(message))
        return visible

    @staticmethod
    def _apply_post_delivery_termination(
        family_case: Mapping[str, Any], state: dict[str, Any]
    ) -> None:
        # Ordering matches HalfDuplexOrchestrator._check_termination: max
        # steps overwrites an existing participant stop, then max errors
        # overwrites max steps.
        if state["upstream_step_count"] >= family_case["pins"]["max_steps"]:
            _set_termination(state, "max_steps")
        if state["num_tool_errors"] >= MAX_TOOL_ERRORS:
            _set_termination(state, "too_many_errors")


__all__ = [
    "ASSISTANT_PHASE",
    "MAX_TOOL_ERRORS",
    "PLUGIN_ID",
    "SCORER_ID",
    "STOP_SIGNALS",
    "Tau3RetailPlugin",
    "USER_PHASE",
    "family_manifest",
    "register_plugin",
]
