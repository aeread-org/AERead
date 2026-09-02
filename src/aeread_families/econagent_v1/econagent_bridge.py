"""Cross-process delegate to the pinned upstream EconAgent engine.

AERead's own venv deliberately does not carry ``ai_economist.foundation``'s
or ``simulate.py``'s runtime dependencies (``lz4``, `pyyaml``, `fire``,
``pandas``, ``seaborn``, ``matplotlib``, ``python-dateutil`` -- see
``cases.py``'s module docstring for the same wall hit at import time).
Rather than reimplement any engine mechanic or scripted-policy formula --
forbidden outright by ``docs/econagent_adapter_spec.md`` -- this module
shells out to a small, self-contained driver script
(``econagent_bridge_driver.py``) run under a SEPARATE, already-provisioned
Python interpreter that has the upstream runtime dependencies installed. The
driver always imports source from the caller-supplied pinned checkout, even
if the interpreter has an unrelated distribution installed.

Unlike ``tau3_retail``'s ``Tau2Bridge`` (one fresh subprocess per call, all
state in the JSON payload), this bridge is **stateful across a whole
episode**: ``complex_actions`` needs the live upstream ``env`` object's
mutable per-agent state and shared numpy RNG stream, neither of which is a
clean JSON round-trip target (see ``docs/econagent_adapter_spec.md``'s
milestone-1 correction 3). ``start_episode`` spawns one persistent
subprocess; ``step_month``/``agent_snapshot``/``dense_log`` send further
requests to that same process; ``close`` shuts it down. Exactly one episode
may be run per ``EconAgentBridge`` instance.

No network call is made by this module or the driver it launches: the
target interpreter is a pre-existing local environment, located by an
explicit, documented environment variable or a fixed default path -- never
invented, downloaded, or installed on the fly.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

BRIDGE_PYTHON_ENV_VAR = "AEREAD_ECONAGENT_BRIDGE_PYTHON"

# Ground rules pin this exact path for the provisioned venv (see
# tools/econagent_bridge/provision.sh); checked after the env var and after a
# venv colocated with the upstream checkout, mirroring tau2_bridge's
# resolution order plus this one fixed fallback.
DEFAULT_VENV_PYTHON = Path(
    "/Users/sunzeyu/Documents/econ benchmark/bridges/econagent-venv/bin/python"
)

_DRIVER_SCRIPT = Path(__file__).with_name("econagent_bridge_driver.py")
_DEFAULT_TIMEOUT_SECONDS = 120.0


class EconAgentBridgeUnavailableError(RuntimeError):
    """No usable pinned-upstream Python interpreter could be located.

    Raised only at discovery/construction time. Never caught silently with a
    fabricated result -- callers decide whether an unavailable bridge is
    acceptable for their purpose, mirroring ``cases.py``'s identical
    convention for the resolved-env digest.
    """


class EconAgentBridgeError(RuntimeError):
    """The bridge subprocess ran but reported an infrastructure failure.

    This covers a malformed request, a protocol violation (closed pipe, non-
    JSON output), or an exception raised by the driver's own dispatch --
    never a silent, partially-applied episode step.
    """


def discover_bridge_python(*, upstream_root: Path | str | None = None) -> Path:
    """Locate a Python interpreter with the pinned upstream package importable.

    Resolution order (first match wins):

    1. ``$AEREAD_ECONAGENT_BRIDGE_PYTHON`` -- an explicit path to a python
       executable, set up through whatever offline/approved channel
       provisioned it. Never installed or downloaded by this function.
    2. ``<upstream_root>/.venv/bin/python`` -- a venv colocated with the
       pinned upstream checkout, if one happens to exist there.
    3. The fixed, ground-rule-pinned default venv
       (``/Users/sunzeyu/Documents/econ benchmark/bridges/econagent-venv``),
       if present.

    Raises ``EconAgentBridgeUnavailableError`` if none resolves to an
    existing file. Deliberately never falls back to ``sys.executable``:
    silently running the driver under AERead's own (dependency-less)
    interpreter would fail with a confusing ``ModuleNotFoundError`` deep
    inside the driver instead of this clear, actionable error raised here.
    """
    candidate = os.environ.get(BRIDGE_PYTHON_ENV_VAR)
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
        raise EconAgentBridgeUnavailableError(
            f"${BRIDGE_PYTHON_ENV_VAR} is set to {candidate!r} but that path "
            "does not exist"
        )
    if upstream_root is not None:
        colocated = Path(upstream_root) / ".venv" / "bin" / "python"
        if colocated.is_file():
            return colocated
    if DEFAULT_VENV_PYTHON.is_file():
        return DEFAULT_VENV_PYTHON
    raise EconAgentBridgeUnavailableError(
        "no pinned upstream EconAgent Python interpreter found: set "
        f"${BRIDGE_PYTHON_ENV_VAR} to a Python >=3.11 executable with the "
        "pinned upstream package's runtime dependencies installed, or run "
        "tools/econagent_bridge/provision.sh, which provisions the default "
        f"path {DEFAULT_VENV_PYTHON}. AERead's own venv intentionally does "
        "not carry ai_economist/simulate.py's runtime dependencies -- see "
        "docs/econagent_adapter_spec.md."
    )


class EconAgentBridge:
    """One provider-free delegate to the pinned upstream EconAgent engine.

    ``resolve_env_config`` is a one-off, stateless call: it spawns a
    short-lived subprocess, sends one request, and closes the pipe. Every
    other method operates on **one persistent episode session**:
    ``start_episode`` spawns the subprocess and must be called first;
    ``step_month``/``agent_snapshot``/``dense_log`` reuse it;  ``close``
    shuts it down. Calling any of the episode methods before
    ``start_episode``, or ``start_episode`` twice on the same instance, is a
    programming error (``EconAgentBridgeError``).
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
        self._process: subprocess.Popen[str] | None = None

    @classmethod
    def discover(
        cls,
        upstream_root: Path | str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> "EconAgentBridge":
        root = Path(upstream_root)
        python_executable = discover_bridge_python(upstream_root=root)
        return cls(
            python_executable=python_executable,
            upstream_root=root,
            timeout_seconds=timeout_seconds,
        )

    def _subprocess_env(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for name in tuple(environment):
            if name.endswith("_API_KEY"):
                environment.pop(name)
        return environment

    def _spawn(self) -> "subprocess.Popen[str]":
        return subprocess.Popen(
            [
                str(self.python_executable),
                str(_DRIVER_SCRIPT),
                "--upstream-root",
                str(self.upstream_root),
            ],
            cwd=str(self.upstream_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._subprocess_env(),
            text=True,
            bufsize=1,
        )

    def resolve_env_config(self) -> dict[str, Any]:
        """One-shot, stateless delegate for the pinned ``config.yaml``'s ``env`` block.

        Never starts or requires an episode session. Used by ``cases.py`` at
        import time; safe to call any number of times, including before,
        between, or after episode sessions on other instances.
        """
        process = self._spawn()
        try:
            stdout, stderr = process.communicate(
                input=json.dumps({"op": "resolve_env_config"}) + "\n",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate(timeout=self.timeout_seconds)
            raise EconAgentBridgeError(
                f"bridge subprocess timed out after {self.timeout_seconds}s "
                "for op='resolve_env_config'"
            ) from error
        response = self._parse_response_line(stdout, stderr, op="resolve_env_config")
        return response["env_config"]

    def start_episode(
        self,
        *,
        n_agents: int,
        episode_length: int,
        world_seed: int,
        beta: float = 0.1,
        gamma: float = 0.1,
        h: float = 1.0,
    ) -> dict[str, Any]:
        """Spawn the persistent subprocess and run upstream's ``reset``."""
        if self._process is not None:
            raise EconAgentBridgeError(
                "start_episode was already called on this bridge instance; "
                "one EconAgentBridge instance serves exactly one episode"
            )
        self._process = self._spawn()
        return self._request(
            {
                "op": "reset",
                "n_agents": n_agents,
                "episode_length": episode_length,
                "world_seed": world_seed,
                "beta": beta,
                "gamma": gamma,
                "h": h,
            }
        )

    def step_month(self) -> dict[str, Any]:
        """Run one month: real upstream ``complex_actions`` then ``env.step``.

        Returns ``{"timestep": int, "done": bool, "actions": {agent_idx:
        [labor, consumption], "p": [0]}}``. ``actions`` is upstream's own
        computed decision, reported for kernel-side bookkeeping (spec
        milestone-1 correction 4) -- never recomputed or second-guessed here.
        """
        response = self._request({"op": "step_month"})
        return {
            "timestep": response["timestep"],
            "done": response["done"],
            "actions": response["actions"],
        }

    def agent_snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe read of live per-agent/world state.

        No upstream computation happens here; this only reads already-
        computed attributes off the live ``env``/agent objects for
        ``observe()``/``terminal()``/``outcome()``.
        """
        response = self._request({"op": "agent_snapshot"})
        return {"agents": response["agents"], "world": response["world"]}

    def dense_log(self) -> dict[str, Any]:
        """Return the full, JSON-safe ``env.dense_log`` accumulated so far."""
        response = self._request({"op": "dense_log"})
        return response["dense_log"]

    def close(self) -> None:
        """Send ``shutdown`` and wait for the subprocess to exit.

        Safe to call more than once, and safe to call when no episode was
        ever started.
        """
        if self._process is None:
            return
        try:
            self._request({"op": "shutdown"}, allow_process_closed=True)
        finally:
            process = self._process
            self._process = None
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            try:
                process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self.timeout_seconds)

    def _request(
        self, request: Mapping[str, Any], *, allow_process_closed: bool = False
    ) -> dict[str, Any]:
        if self._process is None:
            raise EconAgentBridgeError(
                "no active episode session on this bridge instance; call "
                "start_episode first"
            )
        process = self._process
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(json.dumps(dict(request)) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, ValueError) as error:
            if allow_process_closed:
                return {"ok": True}
            raise EconAgentBridgeError(
                f"bridge subprocess pipe closed unexpectedly for "
                f"op={request.get('op')!r}: {error}"
            ) from error
        line = process.stdout.readline()
        if not line:
            stderr_tail = process.stderr.read() if process.stderr else ""
            raise EconAgentBridgeError(
                f"bridge subprocess produced no response for "
                f"op={request.get('op')!r} (exit={process.poll()}); "
                f"stderr:\n{stderr_tail}"
            )
        return self._parse_response_line(line, None, op=str(request.get("op")))

    def _parse_response_line(
        self, stdout: str, stderr: str | None, *, op: str
    ) -> dict[str, Any]:
        line = stdout.strip().splitlines()[0] if stdout.strip() else ""
        try:
            response = json.loads(line) if line else None
        except json.JSONDecodeError as error:
            raise EconAgentBridgeError(
                f"bridge subprocess did not return one JSON object on stdout "
                f"for op={op!r}; stderr:\n{stderr or ''}"
            ) from error
        if not isinstance(response, dict) or not response.get("ok"):
            raise EconAgentBridgeError(
                f"bridge subprocess reported an infrastructure failure for "
                f"op={op!r}: {response!r}"
            )
        return response


__all__ = [
    "BRIDGE_PYTHON_ENV_VAR",
    "DEFAULT_VENV_PYTHON",
    "EconAgentBridge",
    "EconAgentBridgeError",
    "EconAgentBridgeUnavailableError",
    "discover_bridge_python",
]
