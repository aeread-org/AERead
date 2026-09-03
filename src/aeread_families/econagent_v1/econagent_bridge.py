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
import select
import subprocess
import time
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
    JSON output), or an exception raised by the driver's own dispatch. Never
    a *fabricated* result -- but see
    :class:`EconAgentBridgeMutationOutcomeUnknownError` for the one case
    where this class's own guarantee ("the caller can tell whether the step
    actually happened") does not hold.
    """


class EconAgentBridgeMutationOutcomeUnknownError(EconAgentBridgeError):
    """A ``step_month`` request's outcome could not be confirmed.

    The driver runs the real, mutating ``env.step(actions)`` (inside
    ``_op_step_month``) BEFORE it writes and flushes its response
    (``econagent_bridge_driver.py``'s ``main()`` loop only serializes and
    writes a response after ``_dispatch`` returns). If the subprocess or the
    pipe fails in that window -- after the month executed upstream, before
    the response reached this caller -- the month may already have run even
    though no result was ever observed here. This is never safe to treat the
    same as "the month was never attempted": a caller retrying the same
    ``step_month`` request against a fresh session could double-apply it,
    and a caller assuming it never happened could silently lose that
    month's real state. The only safe response is to abandon this episode's
    session for good -- never resumed, never retried on the same or a new
    session -- which is exactly what ``EconAgentV1Plugin.step()`` already
    does for any bridge failure (one ``EconAgentBridge``/subprocess serves
    exactly one episode; see ``environment.py``). This distinct exception
    type makes that "abandon, never retry" contract explicit and machine-
    checkable, rather than an accident of no retry logic existing today.

    Raised only for ``step_month`` -- the one request that is genuinely
    mutating and stateful in a way that cannot be safely repeated
    (``recompute_tax``/``resolve_env_config`` are pure functions of their
    inputs and safe to retry; a lost ``reset``/``start_episode`` response
    means the episode never meaningfully began from this caller's
    perspective, not an ambiguous partial mutation).
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

    def recompute_tax(self, incomes: Mapping[str, float]) -> dict[str, dict[str, float]]:
        """One-shot, stateless re-invocation of upstream's own bracket method.

        Mirrors ``resolve_env_config``: spawns a short-lived subprocess,
        sends one request, and closes the pipe -- never requires
        ``start_episode`` and is safe to call on any instance regardless of
        episode state (including after the episode's own session has been
        closed), because the pinned tax model's bracket schedule is a pure
        function of the config, not of any particular episode (see
        ``econagent_bridge_driver.py``'s ``_op_recompute_tax`` docstring).
        Used by ``measurement.py``'s ``econagent_tax_bracket_arithmetic``
        leaf -- never a reimplemented piecewise tax formula.
        """
        process = self._spawn()
        try:
            stdout, stderr = process.communicate(
                input=json.dumps({"op": "recompute_tax", "incomes": dict(incomes)}) + "\n",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate(timeout=self.timeout_seconds)
            raise EconAgentBridgeError(
                f"bridge subprocess timed out after {self.timeout_seconds}s "
                "for op='recompute_tax'"
            ) from error
        response = self._parse_response_line(stdout, stderr, op="recompute_tax")
        return response["results"]

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
        """Return the full, JSON-safe ``env.dense_log`` accumulated so far.

        Per-component logs (e.g. ``"PeriodicTax"``) are only backfilled by
        upstream's own ``_finalize_logs()`` once the episode's LAST
        ``step_month`` completes -- callers that need the complete,
        per-component dense log (measurement.py's leaves) must call this
        exactly once, right after the terminal ``step_month`` response and
        before ``close()``.
        """
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
        line = self._readline_with_timeout(process, op=str(request.get("op")))
        if not line:
            stderr_tail = process.stderr.read() if process.stderr else ""
            message = (
                f"bridge subprocess produced no response for "
                f"op={request.get('op')!r} (exit={process.poll()}); "
                f"stderr:\n{stderr_tail}"
            )
            if request.get("op") == "step_month":
                raise EconAgentBridgeMutationOutcomeUnknownError(
                    "step_month's outcome could not be confirmed -- the month "
                    f"may have already executed upstream even though no "
                    f"response was ever received: {message}"
                )
            raise EconAgentBridgeError(message)
        return self._parse_response_line(line, None, op=str(request.get("op")))

    def _readline_with_timeout(self, process: "subprocess.Popen[str]", *, op: str) -> str:
        """Read one line from ``process.stdout``, enforcing ``self.timeout_seconds``.

        Plain ``process.stdout.readline()`` blocks forever if the subprocess's
        stdout stays open but produces nothing -- exactly what a hung real
        ``complex_actions``/``env.step`` inside ``_op_step_month`` would do
        (both run *inside* the persistent subprocess, so a hang there never
        closes the pipe the way a crash does), silently ignoring even a
        bridge configured with a one-second ``timeout_seconds``
        (docs/econagent_codex_triage.md finding 7). ``select.select`` polls
        stdout's own file descriptor for readability against a wall-clock
        deadline first; only once something is actually available does this
        call the real, blocking ``readline()`` (every response in this
        protocol is one small JSON line, so once readable there is always a
        complete line to read). If the deadline passes with nothing ever
        readable, the subprocess is killed and this raises the same typed
        errors ``_request``'s own "no response at all" branch raises for a
        closed pipe -- a timeout is just another way no response ever
        arrives, including the same step_month-vs-everything-else
        distinction (a timed-out mutating step_month leaves its own outcome
        just as unconfirmed as a lost response does).

        Falls back to a direct, unbounded ``readline()`` -- this method's
        pre-fix behavior -- when ``process.stdout`` is not backed by a real
        OS file descriptor (``select`` cannot poll it): only ever true for a
        test double standing in for a subprocess, never for a real bridge
        subprocess's stdout, which is always a genuine pipe.
        """
        stdout = process.stdout
        assert stdout is not None
        try:
            stdout.fileno()
        except (AttributeError, OSError, ValueError):
            return stdout.readline()

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                try:
                    process.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    pass
                stderr_tail = process.stderr.read() if process.stderr else ""
                message = (
                    f"bridge subprocess timed out after {self.timeout_seconds}s "
                    f"waiting for a response to op={op!r}; stderr:\n{stderr_tail}"
                )
                if op == "step_month":
                    raise EconAgentBridgeMutationOutcomeUnknownError(
                        "step_month's outcome could not be confirmed -- the "
                        "month may have already executed upstream even "
                        f"though no response arrived before the timeout: "
                        f"{message}"
                    )
                raise EconAgentBridgeError(message)
            ready, _, _ = select.select([stdout], [], [], remaining)
            if ready:
                return stdout.readline()

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
    "EconAgentBridgeMutationOutcomeUnknownError",
    "EconAgentBridgeUnavailableError",
    "discover_bridge_python",
]
