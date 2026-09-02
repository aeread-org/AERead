"""Cross-process delegate to the pinned upstream govsim ``ConcurrentEnv``.

AERead's own environment runs on the project venv, which deliberately does
not carry govsim's runtime dependencies (``pettingzoo``, ``pandas``,
``omegaconf``; see ``cases.py``'s module docstring). Rather than reimplement
the regeneration formula, the collapse test, or ``_assign_stochastic`` /
``_assign_proportional`` -- forbidden outright by
``docs/govsim_adapter_spec.md`` section 3 -- this module shells out, once per
call, to a small self-contained driver script (``govsim_bridge_driver.py``)
run under a SEPARATE, already-provisioned Python interpreter
(``bridges/govsim-venv``, ``tools/govsim_bridge/provision.sh``) that has
those runtime dependencies installed. The driver always imports govsim
source from the caller-supplied pinned checkout, even if the interpreter has
another govsim distribution installed.

Unlike tau2-bench's ``RetailDB`` (a plain dict that fully describes the
domain's state between calls), upstream's ``ConcurrentEnv`` holds state that
is not JSON-safe -- ``datetime`` values in ``internal_global_state["next_time"]``
and ``PersonaAction`` instances in ``internal_global_state["action"]`` -- so
there is no dict this bridge can pass in and get back as-is the way
``tau2_bridge.py`` passes ``db``. Each call instead carries the complete
ordered action history for the episode; the driver replays
``reset(seed=...)`` followed by every recorded action, in order, inside one
subprocess, and returns a plain-JSON projection of the resulting state (see
``govsim_bridge_driver.py``'s module docstring for the exact protocol and
why replay is deterministic here). This keeps the same per-call, no-daemon
subprocess discipline as ``tau2_bridge.py`` -- one subprocess, one call, full
state passed in and out -- at the cost of O(n) upstream ``step()`` calls
replayed per bridge call instead of O(1); those calls are pure arithmetic
(no model, no I/O) and the replayed episodes are short (at most
``(2*num_agents+1) * max_num_rounds`` actions), so the added CPU cost is
negligible next to the subprocess's own interpreter-and-import overhead.

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
from typing import Any, Mapping, Sequence

BRIDGE_PYTHON_ENV_VAR = "AEREAD_GOVSIM_BRIDGE_PYTHON"

_DRIVER_SCRIPT = Path(__file__).with_name("govsim_bridge_driver.py")
_DEFAULT_TIMEOUT_SECONDS = 60.0


class GovsimBridgeUnavailableError(RuntimeError):
    """No usable pinned-upstream Python interpreter could be located.

    Raised only at discovery/construction time. Never caught silently with a
    fabricated result -- callers decide whether an unavailable bridge is
    acceptable for their purpose, mirroring ``tau2_bridge.py``'s identical
    convention.
    """


class GovsimBridgeError(RuntimeError):
    """The bridge subprocess ran but reported an infrastructure failure.

    Distinct from an upstream *assertion* raised by a deliberately malformed
    action (spec section 4's "malformed-operational" golden): that failure
    still arrives as a structured ``{"ok": false, "failed_action_index": ...}``
    response and is reported through :class:`GovsimActionError`, never this
    class. ``GovsimBridgeError`` is reserved for a broken subprocess itself
    (bad JSON on stdout, a timeout, an unrecognized op).
    """


class GovsimActionError(RuntimeError):
    """Upstream itself raised while replaying one action in the sequence.

    Carries ``error_type``/``failed_action_index`` so a caller can tell a
    deliberately malformed action (the golden this exists to support) from
    an adapter bug, rather than re-parsing a generic message string.
    """

    def __init__(self, *, error_type: str, message: str, failed_action_index: int) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.failed_action_index = failed_action_index


def discover_bridge_python(*, upstream_root: Path | str | None = None) -> Path:
    """Locate a Python interpreter with govsim's bridge dependencies installed.

    Resolution order (first match wins), mirroring ``tau2_bridge.py``'s
    ``AEREAD_TAU2_BRIDGE_PYTHON`` convention:

    1. ``$AEREAD_GOVSIM_BRIDGE_PYTHON`` -- an explicit path to a python
       executable, set up through whatever offline/approved channel
       provisioned it (``tools/govsim_bridge/provision.sh``). Never
       installed or downloaded by this function.
    2. ``<upstream_root>/.venv/bin/python`` -- a venv colocated with the
       pinned upstream checkout, if one happens to exist there.

    Raises ``GovsimBridgeUnavailableError`` if neither resolves to an
    existing file. Deliberately never falls back to ``sys.executable``:
    unlike tau2-bench, govsim needs no different Python *version* -- only
    different site-packages -- but running the driver under AERead's own
    (dependency-less) interpreter would still fail with a confusing
    ``ModuleNotFoundError`` instead of this clear, actionable error.
    """
    candidate = os.environ.get(BRIDGE_PYTHON_ENV_VAR)
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
        raise GovsimBridgeUnavailableError(
            f"${BRIDGE_PYTHON_ENV_VAR} is set to {candidate!r} but that path "
            "does not exist"
        )
    if upstream_root is not None:
        colocated = Path(upstream_root) / ".venv" / "bin" / "python"
        if colocated.is_file():
            return colocated
    raise GovsimBridgeUnavailableError(
        "no pinned upstream govsim Python interpreter found: set "
        f"${BRIDGE_PYTHON_ENV_VAR} to a Python executable with numpy/pandas/"
        "omegaconf/pettingzoo installed (tools/govsim_bridge/provision.sh), "
        "e.g. bridges/govsim-venv/bin/python. AERead's own venv "
        "intentionally does not carry those -- see "
        "docs/govsim_adapter_spec.md section 3.2."
    )


class GovsimBridge:
    """One provider-free delegate to the pinned upstream ``ConcurrentEnv``.

    Every method spawns a fresh, short-lived subprocess running
    ``govsim_bridge_driver.py`` under ``python_executable``. Nothing is
    cached across calls beyond ordinary OS-level caching: ``run_actions``
    always replays the full action history it is given (see this module's
    docstring for why).
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
    ) -> "GovsimBridge":
        root = Path(upstream_root)
        python_executable = discover_bridge_python(upstream_root=root)
        return cls(
            python_executable=python_executable,
            upstream_root=root,
            timeout_seconds=timeout_seconds,
        )

    def _run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
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
                env=environment,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise GovsimBridgeError(
                f"bridge subprocess timed out after {self.timeout_seconds}s "
                f"for op={request.get('op')!r}"
            ) from error
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GovsimBridgeError(
                "bridge subprocess did not return one JSON object on stdout "
                f"(exit={completed.returncode}) for op={request.get('op')!r}; "
                f"stderr:\n{completed.stderr.decode('utf-8', errors='replace')}"
            ) from error
        if not isinstance(response, dict):
            raise GovsimBridgeError(
                f"bridge subprocess response was not a JSON object for "
                f"op={request.get('op')!r}: {response!r}"
            )
        return response

    def run_actions(
        self,
        *,
        scenario: str,
        env_cfg: Mapping[str, Any],
        seed: int,
        actions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Replay ``actions`` from ``reset(seed=seed)`` and return the new state.

        Raises :class:`GovsimActionError` when upstream itself raised while
        applying one of ``actions`` (see that class's docstring); raises
        :class:`GovsimBridgeError` for any other infrastructure failure.
        """
        response = self._run(
            {
                "op": "run_actions",
                "scenario": scenario,
                "env_cfg": dict(env_cfg),
                "seed": int(seed),
                "actions": [dict(action) for action in actions],
            }
        )
        if not response.get("ok"):
            if "failed_action_index" in response and response["failed_action_index"] is not None:
                raise GovsimActionError(
                    error_type=response.get("error_type", "UnknownError"),
                    message=response.get("message", ""),
                    failed_action_index=response["failed_action_index"],
                )
            raise GovsimBridgeError(
                f"bridge subprocess reported an infrastructure failure for "
                f"run_actions: {response!r}"
            )
        return response

    def runtime_info(self) -> dict[str, str]:
        """Report the exact interpreter/package provenance used by the driver."""
        response = self._run({"op": "runtime_info"})
        if not response.get("ok"):
            raise GovsimBridgeError(
                f"bridge subprocess reported an infrastructure failure for "
                f"runtime_info: {response!r}"
            )
        return {
            "python_version": response["python_version"],
            "numpy_version": response["numpy_version"],
            "pandas_version": response["pandas_version"],
            "omegaconf_version": response["omegaconf_version"],
            "pettingzoo_version": response["pettingzoo_version"],
        }


__all__ = [
    "BRIDGE_PYTHON_ENV_VAR",
    "GovsimActionError",
    "GovsimBridge",
    "GovsimBridgeError",
    "GovsimBridgeUnavailableError",
    "discover_bridge_python",
]
