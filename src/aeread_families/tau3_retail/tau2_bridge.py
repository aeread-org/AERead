"""Cross-process delegate to the pinned upstream tau2-bench retail tools.

AERead's own environment runs Python 3.11 and deliberately does not carry
tau2-bench's runtime dependencies (``docstring_parser``, ``loguru``,
``deepdiff``, ``python-dotenv``, ``addict``) or a >=3.12 interpreter --
upstream declares ``requires-python = ">=3.12,<3.14"`` and imports
``docstring_parser``/``loguru`` at module import time in the very modules
(``tau2.environment.tool``, ``tau2.environment.environment``) that any real
tool execution needs (see ``cases.py``'s module docstring for the same wall
hit at import time in the foundation stage).

Rather than reimplement any tool body, database mutation, or schema
derivation -- forbidden outright by
``docs/tau3_retail_adapter_spec.md`` -- this module shells out, once per
call, to a small self-contained driver script (``tau2_bridge_driver.py``)
run under a SEPARATE, already-provisioned Python interpreter that has the
pinned upstream package importable. Every retail tool call and every schema
query in ``tools.py`` goes through this bridge; nothing about tool behavior
is ever hand-derived here.

No network call is made by this module or the driver it launches: the
target interpreter is a pre-existing local environment, located by an
explicit, documented environment variable -- never invented, downloaded, or
installed on the fly.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

BRIDGE_PYTHON_ENV_VAR = "AEREAD_TAU2_BRIDGE_PYTHON"

_DRIVER_SCRIPT = Path(__file__).with_name("tau2_bridge_driver.py")
_DEFAULT_TIMEOUT_SECONDS = 120.0


class Tau2BridgeUnavailableError(RuntimeError):
    """No usable pinned-upstream Python interpreter could be located.

    Raised only at discovery/construction time. Never caught silently with a
    fabricated result -- callers decide whether an unavailable bridge is
    acceptable for their purpose, mirroring ``cases.py``'s identical
    convention for ``tool_schema_sha256`` in the foundation stage.
    """


class Tau2BridgeError(RuntimeError):
    """The bridge subprocess ran but reported an infrastructure failure.

    This is distinct from an upstream *tool*-level error (e.g. "Order not
    found"), which upstream represents as an in-band
    ``ToolMessage(error=True)`` and which this bridge reports as a normal
    ``ok=True`` response with ``error=True`` -- never as an exception (see
    ``tools.py``'s ``_implementation``).
    """


def discover_bridge_python(*, upstream_root: Path | str | None = None) -> Path:
    """Locate a Python interpreter with the pinned upstream package importable.

    Resolution order (first match wins), mirroring ``cases.py``'s
    ``AEREAD_TAU2_UPSTREAM_ROOT`` convention:

    1. ``$AEREAD_TAU2_BRIDGE_PYTHON`` -- an explicit path to a python
       executable, set up through whatever offline/approved channel
       provisioned it. Never installed or downloaded by this function.
    2. ``<upstream_root>/.venv/bin/python`` -- a venv colocated with the
       pinned upstream checkout, if one happens to exist there.

    Raises ``Tau2BridgeUnavailableError`` if neither resolves to an existing
    file. Deliberately never falls back to ``sys.executable``: silently
    running the driver under AERead's own (dependency-less) interpreter
    would fail with a confusing ``ModuleNotFoundError`` deep inside the
    driver instead of this clear, actionable error raised here.
    """
    candidate = os.environ.get(BRIDGE_PYTHON_ENV_VAR)
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
        raise Tau2BridgeUnavailableError(
            f"${BRIDGE_PYTHON_ENV_VAR} is set to {candidate!r} but that path "
            "does not exist"
        )
    if upstream_root is not None:
        colocated = Path(upstream_root) / ".venv" / "bin" / "python"
        if colocated.is_file():
            return colocated
    raise Tau2BridgeUnavailableError(
        "no pinned upstream tau2-bench Python interpreter found: set "
        f"${BRIDGE_PYTHON_ENV_VAR} to a python executable that has the "
        "pinned upstream package (commit "
        "fc0055dc4e0a316c3f83133267fbd6faaa770992) importable, e.g. "
        "`pip install -e <checkout>` into a Python >=3.12 venv with "
        "docstring_parser/loguru/deepdiff/python-dotenv/addict installed. "
        "AERead's own venv intentionally does not carry tau2-bench's "
        "runtime dependencies -- see docs/tau3_retail_adapter_spec.md."
    )


class Tau2Bridge:
    """One provider-free delegate to the pinned upstream retail tool layer.

    Every method spawns a fresh, short-lived subprocess running
    ``tau2_bridge_driver.py`` under ``python_executable``. Nothing is cached
    across calls beyond ordinary OS-level caching; all retail state lives in
    the ``db`` dict callers pass in and get back (see ``RetailToolSession``
    in ``tools.py``), matching the retail domain's own state model where the
    whole ``RetailDB`` dump is the only thing that changes between calls.
    """

    def __init__(
        self,
        *,
        python_executable: Path | str,
        upstream_root: Path | str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.python_executable = Path(python_executable)
        self.upstream_root = Path(upstream_root)
        self.timeout_seconds = timeout_seconds

    @classmethod
    def discover(
        cls,
        upstream_root: Path | str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> "Tau2Bridge":
        root = Path(upstream_root)
        python_executable = discover_bridge_python(upstream_root=root)
        return cls(
            python_executable=python_executable,
            upstream_root=root,
            timeout_seconds=timeout_seconds,
        )

    def _run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [
                    str(self.python_executable),
                    str(_DRIVER_SCRIPT),
                    "--upstream-root",
                    str(self.upstream_root),
                ],
                input=json.dumps(request).encode("utf-8"),
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise Tau2BridgeError(
                f"bridge subprocess timed out after {self.timeout_seconds}s "
                f"for op={request.get('op')!r}"
            ) from error
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise Tau2BridgeError(
                "bridge subprocess did not return one JSON object on stdout "
                f"(exit={completed.returncode}) for op={request.get('op')!r}; "
                f"stderr:\n{completed.stderr.decode('utf-8', errors='replace')}"
            ) from error
        if not isinstance(response, dict) or not response.get("ok"):
            raise Tau2BridgeError(
                f"bridge subprocess reported an infrastructure failure for "
                f"op={request.get('op')!r}: {response!r}"
            )
        return response

    def fetch_tool_schema(self) -> dict[str, Any]:
        """Delegate to upstream for every tool's OpenAI schema and effect.

        Returns ``{"tools": {name: {"openai_schema": ..., "tool_type": ...,
        "mutates_state": bool}}, "tool_schema_sha256": str}``. The hash is
        upstream's own ``get_dict_hash({name: tool.openai_schema for tool in
        env.get_tools()})``, computed by the driver -- never recomputed
        here.
        """
        response = self._run({"op": "schema"})
        return {
            "tools": response["tools"],
            "tool_schema_sha256": response["tool_schema_sha256"],
        }

    def call_tool(
        self,
        *,
        db: Mapping[str, Any],
        tool_name: str,
        arguments: Mapping[str, Any],
        requestor: str = "assistant",
        tool_call_id: str = "",
    ) -> dict[str, Any]:
        """Delegate one tool call to upstream's ``Environment.get_response``.

        Returns ``{"content": str, "error": bool, "db": dict, "db_hash":
        str}``. ``content``/``error`` are upstream's ``ToolMessage`` fields
        byte-for-byte (including upstream's own error strings -- a tool-
        level error is a normal, in-band result here, never an exception);
        ``db`` is the full post-call ``RetailDB.model_dump()``; ``db_hash``
        is upstream's own ``Environment.get_db_hash()``.
        """
        response = self._run(
            {
                "op": "call",
                "db": db,
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "requestor": requestor,
                "tool_call_id": tool_call_id,
            }
        )
        return {
            "content": response["content"],
            "error": response["error"],
            "db": response["db"],
            "db_hash": response["db_hash"],
        }

    def normalize_db(self, db: Mapping[str, Any]) -> dict[str, Any]:
        """Delegate a plain ``RetailDB.model_validate(db).model_dump()``.

        No tool call is made. On-disk ``db.json`` omits Optional fields that
        are still at their default (e.g. an order that was never cancelled
        has no ``cancel_reason`` key at all), while every post-``call_tool``
        db always carries them explicitly because it went through this same
        validate/dump round trip. Callers that need a stable "before"
        baseline comparable to a post-call db (e.g. to prove a read-only
        tool changed nothing) should normalize a freshly loaded db.json once
        with this method rather than compare the raw file against a
        post-call db and mistake upstream's own Pydantic defaulting for a
        tool-caused mutation.
        """
        response = self._run({"op": "normalize", "db": db})
        return response["db"]


__all__ = [
    "BRIDGE_PYTHON_ENV_VAR",
    "Tau2Bridge",
    "Tau2BridgeError",
    "Tau2BridgeUnavailableError",
    "discover_bridge_python",
]
