#!/usr/bin/env python
"""Subprocess driver for tau3_retail's ``Tau2Bridge`` (see ``tau2_bridge.py``).

This script runs under a SEPARATE, already-provisioned Python interpreter
(>=3.12) with tau2-bench's runtime dependencies installed. Source is always
loaded from the caller-supplied pinned checkout (commit
``fc0055dc4e0a316c3f83133267fbd6faaa770992``), never from an unrelated tau2
distribution installed in that interpreter. Nothing is installed or fetched
by this script (no network calls; see the adapter spec's rule 2).

It exists so ``tools.py`` -- which runs inside AERead's own, older Python
interpreter that deliberately does not carry tau2-bench's runtime
dependencies -- can delegate every retail tool call and schema query to the
real upstream implementation instead of reimplementing any of it. Every
function below either reads static upstream data or calls straight into
upstream code (``Tool.openai_schema``, ``RetailTools`` via
``Environment.get_response``, ``tau2.utils.get_dict_hash``); none of it
reimplements a tool body, a scoring rule, or a database mutation.

This file must not import anything from the ``aeread`` package: it is
invoked as a standalone script under a *different* Python interpreter that
does not have ``aeread`` on its path.

Protocol -- exactly one JSON object read from stdin, exactly one JSON object
written to stdout:

  {"op": "schema"}
      -> {"ok": true, "tools": {name: {"openai_schema": ..., "tool_type":
          "read"|"write"|"generic"|"think", "mutates_state": bool}}},
          "tool_schema_sha256": str}

  {"op": "call", "db": <RetailDB.model_dump()-shaped dict>, "tool_name": str,
   "arguments": dict, "requestor": "assistant"|"user" (default "assistant"),
   "tool_call_id": str (default "")}
      -> {"ok": true, "content": str, "error": bool, "db": dict,
          "db_hash": str}
      -- "content"/"error" are upstream's ToolMessage fields byte-for-byte
         (including upstream's own error strings for a failed tool call --
         that is a normal, in-band, ok=true response, never an exception);
         "db" is the full post-call RetailDB.model_dump(); "db_hash" is
         upstream's own Environment.get_db_hash().

  {"op": "normalize", "db": <any dict RetailDB.model_validate accepts>}
      -> {"ok": true, "db": dict}
      -- no tool call is made; "db" is upstream's own
         ``RetailDB.model_validate(db).model_dump()``. On-disk db.json omits
         Optional fields that are still at their default (e.g. an order that
         has never been cancelled has no "cancel_reason" key at all), while
         every post-call "db" above always carries them explicitly (as
         None) because it went through this same validate/dump round trip.
         Callers that need a stable byte-for-byte "before" baseline to
         compare a live db.json load against (e.g. to prove a read-only
         tool changed nothing) should normalize once, up front, with this
         op -- never by re-deriving the shape difference by hand.

  {"op": "hash_db", "db": <RetailDB.model_dump()-shaped dict>}
      -> {"ok": true, "db_hash": str}

  {"op": "normalize_messages", "messages": [<upstream message dict>, ...]}
      -> {"ok": true, "messages": [<upstream model_dump() dict>, ...]}

  {"op": "evaluate_env", "task": <verbatim upstream task dict>,
   "messages": [<upstream message dict>, ...] (the full episode trajectory,
   starting from task initial state), "strict_replay": bool (default true)}
      -> {"ok": true, "reward": float, "db_check": {"db_match": bool,
          "db_reward": float} | null, "reward_breakdown": {str: float} | null}
      -- delegates entirely to
         tau2.evaluator.evaluator_env.EnvironmentEvaluator.calculate_reward:
         replays the task's gold actions and the given trajectory through
         upstream's own tool layer and compares upstream's own db hashes.
         Never recomputes or reimplements that comparison.

  {"op": "evaluate_nl_assertions_from_verdicts", "task": <verbatim upstream
   task dict>, "verdicts": [{"nl_assertion": str, "met": bool,
   "justification": str}, ...]}
      -> {"ok": true, "reward": float,
          "nl_assertions": [{"nl_assertion": str, "met": bool,
          "justification": str}, ...]}
      -- cross-check only (see the function's docstring): runs upstream's
         real reward reduction over caller-supplied verdicts with the one
         live-model call monkeypatched out for this subprocess's lifetime.
         Never the production leaf-2 scoring path.

  {"op": "nl_assertions_judge_request", "task": <verbatim upstream task
   dict>, "messages": [<upstream message dict>, ...] (the trajectory that
   would be judged)}
      -> {"ok": true, "called": bool, "model": str | null,
          "messages": [{"role": str, "content": str}, ...] | null,
          "call_name": str | null, "args": dict | null}
      -- cross-check/parity only (see the function's docstring): captures
         the exact system/user judge prompt, model, and args that
         NLAssertionsEvaluator.calculate_reward would send to
         tau2.utils.llm_utils.generate, with that one live-model call
         monkeypatched to capture-and-return instead of contacting any
         provider. "called" is false only when upstream's own short-circuit
         (task carries no non-empty nl_assertions) means no judge call would
         ever be made. "messages" reports only role/content -- the two
         fields the judge prompt is actually built from -- never the full
         Message.model_dump(), which carries a wall-clock "timestamp"
         stamped at construction time and would make two otherwise-
         identical captures compare as different. Used to compare "the
         judged component's inputs" across two trajectories without ever
         invoking a real judge.

  {"op": "runtime_info"}
      -> {"ok": true, "python_version": str, "tau2_package_file": str,
          "local_model_cost_map": str}

  Anything else (bad op, malformed request, import failure, ...)
      -> {"ok": false, "error_type": str, "message": str}, exit code 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _make_upstream_importable(upstream_root: str | None) -> None:
    """Ensure ``import tau2`` resolves to the pinned checkout.

    The checkout path always wins over any unrelated ``tau2`` distribution
    already installed in the dependency-bearing interpreter. This is
    deliberate: the bridge interpreter supplies dependencies, while the
    caller-supplied checkout supplies the pinned source.
    """
    if upstream_root:
        src_dir = str((Path(upstream_root) / "src").resolve())
        sys.path[:] = [entry for entry in sys.path if entry != src_dir]
        sys.path.insert(0, src_dir)
    import tau2

    if upstream_root:
        expected_package = (Path(upstream_root) / "src" / "tau2").resolve()
        loaded_file = Path(tau2.__file__).resolve()
        if not loaded_file.is_relative_to(expected_package):
            raise RuntimeError(
                "tau2 import did not resolve under the requested pinned checkout: "
                f"loaded {loaded_file}, expected under {expected_package}"
            )


def _op_schema() -> dict[str, Any]:
    from tau2.domains.retail.environment import get_environment
    from tau2.utils import get_dict_hash

    environment = get_environment()
    tools = environment.get_tools()
    schema_by_name = {tool.name: tool.openai_schema for tool in tools}
    info: dict[str, Any] = {}
    for tool in tools:
        info[tool.name] = {
            "openai_schema": tool.openai_schema,
            "tool_type": environment.tools.tool_type(tool.name).value,
            "mutates_state": environment.tools.tool_mutates_state(tool.name),
        }
    return {
        "ok": True,
        "tools": info,
        "tool_schema_sha256": get_dict_hash(schema_by_name),
    }


def _op_call(request: dict[str, Any]) -> dict[str, Any]:
    from tau2.data_model.message import ToolCall
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.environment import get_environment

    db = RetailDB.model_validate(request["db"])
    environment = get_environment(db=db)
    tool_call = ToolCall(
        id=request.get("tool_call_id") or "",
        name=request["tool_name"],
        arguments=request["arguments"],
        requestor=request.get("requestor", "assistant"),
    )
    tool_message = environment.get_response(tool_call)
    return {
        "ok": True,
        "content": tool_message.content,
        "error": tool_message.error,
        "tool_message": tool_message.model_dump(),
        "db": environment.tools.db.model_dump(),
        "db_hash": environment.get_db_hash(),
    }


def _op_normalize(request: dict[str, Any]) -> dict[str, Any]:
    from tau2.domains.retail.data_model import RetailDB

    db = RetailDB.model_validate(request["db"])
    return {"ok": True, "db": db.model_dump()}


def _op_hash_db(request: dict[str, Any]) -> dict[str, Any]:
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.environment import get_environment

    db = RetailDB.model_validate(request["db"])
    return {"ok": True, "db_hash": get_environment(db=db).get_db_hash()}


def _op_evaluate_env(request: dict[str, Any]) -> dict[str, Any]:
    """Delegate DB-equality scoring to upstream's own EnvironmentEvaluator.

    Never recomputes or reimplements the gold-vs-predicted DB comparison:
    this calls straight into
    ``tau2.evaluator.evaluator_env.EnvironmentEvaluator.calculate_reward``,
    which itself (a) replays ``task.evaluation_criteria.actions`` on a fresh
    gold environment via upstream's own ``Environment.make_tool_call``, (b)
    replays the caller-supplied trajectory on a predicted environment via
    upstream's own ``Environment.set_state``, and (c) compares upstream's own
    ``get_db_hash()`` values. Only the resulting ``RewardInfo`` is
    marshalled to JSON here.
    """
    from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage
    from tau2.data_model.tasks import Task
    from tau2.domains.retail.environment import get_environment
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator

    message_types = {
        "assistant": AssistantMessage,
        "tool": ToolMessage,
        "user": UserMessage,
    }
    trajectory = [
        message_types[message["role"]].model_validate(message)
        for message in request["messages"]
    ]
    task = Task.model_validate(request["task"])
    reward_info = EnvironmentEvaluator.calculate_reward(
        environment_constructor=get_environment,
        task=task,
        full_trajectory=trajectory,
        solo_mode=False,
        env_kwargs={},
        strict_replay=request.get("strict_replay", True),
    )
    db_check = None
    if reward_info.db_check is not None:
        db_check = {
            "db_match": reward_info.db_check.db_match,
            "db_reward": reward_info.db_check.db_reward,
        }
    reward_breakdown = None
    if reward_info.reward_breakdown is not None:
        reward_breakdown = {
            key.value: value for key, value in reward_info.reward_breakdown.items()
        }
    return {
        "ok": True,
        "reward": reward_info.reward,
        "db_check": db_check,
        "reward_breakdown": reward_breakdown,
    }


def _op_evaluate_nl_assertions_from_verdicts(request: dict[str, Any]) -> dict[str, Any]:
    """Cross-check only: run upstream's own NL-assertions reduction offline.

    ``NLAssertionsEvaluator.calculate_reward`` always calls out to a live
    judge model via ``tau2.utils.llm_utils.generate`` -- forbidden here (no
    network calls, ever). This op monkeypatches that one call, for the
    lifetime of this single subprocess only, to return the caller-supplied
    verdicts verbatim instead of contacting any provider, then runs
    upstream's real ``reward = 1.0 if all(check.met ...) else 0.0``
    reduction on top of them. It exists purely so a test can assert the
    adapter's own local reduction (``measurement.score_nl_assertions``,
    which never imports tau2 at all) agrees with upstream's real code, not
    a hand-derived copy of it -- it is never used as the production scoring
    path (see ``measurement.py``'s module docstring).
    """
    import json as _json

    from tau2.data_model.message import AssistantMessage
    from tau2.data_model.tasks import Task
    from tau2.evaluator import evaluator_nl_assertions as nl_module

    verdicts = request["verdicts"]

    def _fake_generate(*_args: Any, **_kwargs: Any) -> AssistantMessage:
        payload = {
            "results": [
                {
                    "expectedOutcome": verdict["nl_assertion"],
                    "reasoning": verdict["justification"],
                    "metExpectation": verdict["met"],
                }
                for verdict in verdicts
            ]
        }
        return AssistantMessage(role="assistant", content=_json.dumps(payload))

    task = Task.model_validate(request["task"])
    original_generate = nl_module.generate
    nl_module.generate = _fake_generate
    try:
        reward_info = nl_module.NLAssertionsEvaluator.calculate_reward(
            task=task, full_trajectory=[]
        )
    finally:
        nl_module.generate = original_generate
    return {
        "ok": True,
        "reward": reward_info.reward,
        "nl_assertions": [
            {
                "nl_assertion": check.nl_assertion,
                "met": check.met,
                "justification": check.justification,
            }
            for check in (reward_info.nl_assertions or [])
        ],
    }


def _op_nl_assertions_judge_request(request: dict[str, Any]) -> dict[str, Any]:
    """Capture the exact judge request upstream's NLAssertionsEvaluator would
    send for one trajectory -- system/user prompt construction, model, and
    args -- without ever calling a model or the network.

    Monkeypatches ``tau2.evaluator.evaluator_nl_assertions.generate`` (the
    one live-model call inside ``NLAssertionsEvaluator.calculate_reward``)
    to capture its keyword arguments and return a syntactically valid,
    empty verdict payload instead of contacting any provider, then lets
    ``calculate_reward`` run to completion so the *exact*, unmodified
    upstream prompt-construction code path executes. This is parity
    tooling only (see ``parity.py``'s "judged component's inputs"
    comparison): it never obtains or reproduces an actual judge verdict.

    Captured messages report only ``role``/``content`` -- the two fields
    that are actually joined into the judge prompt text
    (``NLAssertionsEvaluator`` never reads anything else off a ``Message``)
    -- never the full ``model_dump()``. ``SystemMessage``/``UserMessage``
    stamp a wall-clock ``timestamp`` at construction time via
    ``default_factory``; two otherwise-identical calls captured a few
    seconds apart in separate subprocesses would then compare as "different
    inputs" for a reason that has nothing to do with what was actually sent
    to the judge. Discovered empirically while running the pilot parity
    procedure against task 108 (see ``docs/tau3_retail_adapter_spec.md``
    section 8, P4): the two constructed ``system_prompt``/``user_prompt``
    strings were byte-identical, but the full raw message dumps differed
    only in ``timestamp``.
    """
    import json as _json

    from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage
    from tau2.data_model.tasks import Task
    from tau2.evaluator import evaluator_nl_assertions as nl_module

    message_types = {
        "assistant": AssistantMessage,
        "tool": ToolMessage,
        "user": UserMessage,
    }
    trajectory = [
        message_types[message["role"]].model_validate(message)
        for message in request["messages"]
    ]
    task = Task.model_validate(request["task"])

    captured: dict[str, Any] = {}

    def _capturing_generate(
        *, model: str, messages: list, call_name: str | None = None, **kwargs: Any
    ) -> AssistantMessage:
        captured["model"] = model
        captured["messages"] = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        captured["call_name"] = call_name
        captured["args"] = kwargs
        return AssistantMessage(role="assistant", content=_json.dumps({"results": []}))

    original_generate = nl_module.generate
    nl_module.generate = _capturing_generate
    try:
        nl_module.NLAssertionsEvaluator.calculate_reward(
            task=task, full_trajectory=trajectory
        )
    finally:
        nl_module.generate = original_generate

    if not captured:
        return {
            "ok": True,
            "called": False,
            "model": None,
            "messages": None,
            "call_name": None,
            "args": None,
        }
    return {
        "ok": True,
        "called": True,
        "model": captured["model"],
        "messages": captured["messages"],
        "call_name": captured["call_name"],
        "args": captured["args"],
    }


def _op_normalize_messages(request: dict[str, Any]) -> dict[str, Any]:
    from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage

    message_types = {
        "assistant": AssistantMessage,
        "tool": ToolMessage,
        "user": UserMessage,
    }
    normalized = []
    for message in request["messages"]:
        message_type = message_types[message["role"]]
        normalized.append(message_type.model_validate(message).model_dump())
    return {"ok": True, "messages": normalized}


def _op_runtime_info() -> dict[str, Any]:
    import tau2

    return {
        "ok": True,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "tau2_package_file": str(Path(tau2.__file__).resolve()),
        "local_model_cost_map": os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP", ""),
        "dont_write_bytecode": os.environ.get("PYTHONDONTWRITEBYTECODE", ""),
    }


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "schema":
        return _op_schema()
    if op == "call":
        return _op_call(request)
    if op == "normalize":
        return _op_normalize(request)
    if op == "hash_db":
        return _op_hash_db(request)
    if op == "normalize_messages":
        return _op_normalize_messages(request)
    if op == "evaluate_env":
        return _op_evaluate_env(request)
    if op == "evaluate_nl_assertions_from_verdicts":
        return _op_evaluate_nl_assertions_from_verdicts(request)
    if op == "nl_assertions_judge_request":
        return _op_nl_assertions_judge_request(request)
    if op == "runtime_info":
        return _op_runtime_info()
    return {
        "ok": False,
        "error_type": "bad_request",
        "message": f"unknown op: {op!r}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        default=None,
        help="path to the pinned tau2-bench checkout whose src directory "
        "must supply the imported tau2 package",
    )
    args = parser.parse_args(argv)
    try:
        _make_upstream_importable(args.upstream_root)
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        response = _dispatch(request)
    except Exception as error:  # noqa: BLE001 - reported as a structured infra failure
        response = {
            "ok": False,
            "error_type": type(error).__name__,
            "message": str(error),
        }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
