#!/usr/bin/env python
"""Subprocess driver for tau3_retail's ``Tau2Bridge`` (see ``tau2_bridge.py``).

This script runs under a SEPARATE, already-provisioned Python interpreter
(>=3.12) that has the pinned upstream tau2-bench package (commit
``fc0055dc4e0a316c3f83133267fbd6faaa770992``) importable -- never under
AERead's own interpreter, and never installed or fetched by this script
itself (no network calls; see docs/tau3_retail_adapter_spec.md rule 2).

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

  Anything else (bad op, malformed request, import failure, ...)
      -> {"ok": false, "error_type": str, "message": str}, exit code 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _make_upstream_importable(upstream_root: str | None) -> None:
    """Ensure ``import tau2`` resolves to the pinned checkout.

    If the target interpreter already has the pinned package installed
    (e.g. ``pip install -e <checkout>``), ``import tau2`` already works and
    this is a no-op. Otherwise, fall back to the same ``sys.path`` injection
    ``cases.py`` uses so the bridge works against a checkout-only
    environment too.
    """
    try:
        import tau2  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if not upstream_root:
        raise
    src_dir = str(Path(upstream_root) / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    import tau2  # noqa: F401


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
        "db": environment.tools.db.model_dump(),
        "db_hash": environment.get_db_hash(),
    }


def _op_normalize(request: dict[str, Any]) -> dict[str, Any]:
    from tau2.domains.retail.data_model import RetailDB

    db = RetailDB.model_validate(request["db"])
    return {"ok": True, "db": db.model_dump()}


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "schema":
        return _op_schema()
    if op == "call":
        return _op_call(request)
    if op == "normalize":
        return _op_normalize(request)
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
        help="path to the pinned tau2-bench checkout, used only as a "
        "sys.path fallback if `tau2` is not already installed",
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
