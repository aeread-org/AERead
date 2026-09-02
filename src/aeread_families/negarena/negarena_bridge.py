"""Cross-process delegate to the pinned upstream NegotiationArena checkout.

AERead's own project venv deliberately does not carry ``openai``/``anthropic``
(ground rule: never install them into the project venv). Every upstream
negarena module -- including the "pure" game-object arithmetic -- imports
both at module scope (see ``cases.py``'s module docstring for the same
"AERead authors the corpus; upstream owns only the mechanics" split, and
``docs/negarena_adapter_spec.md``'s governing facts for the poisoned-import
chain).

Rather than reimplement any parser, tag grammar, or admission-gate check --
forbidden outright by ``docs/negarena_adapter_spec.md`` section 3 -- this
module shells out, once per call, to a small self-contained driver script
(``negarena_bridge_driver.py``) run under a SEPARATE, already-provisioned
Python interpreter that has ``openai``/``anthropic`` installed
(``tools/negarena_bridge/provision.sh``). The driver always imports negarena
source from the caller-supplied pinned checkout, even if the interpreter has
another negotiationarena distribution installed.

No network call is made by this module or the driver it launches: the
target interpreter is a pre-existing local environment, located by an
explicit, documented environment variable -- never invented, downloaded, or
installed on the fly.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

BRIDGE_PYTHON_ENV_VAR = "AEREAD_NEGARENA_BRIDGE_PYTHON"


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Callers may pass in kernel-frozen values (e.g. an already-parsed,
    ``ParseResult``-frozen ``MappingProxyType``); ``json.dumps`` cannot
    serialize those directly.
    """
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)

_DRIVER_SCRIPT = Path(__file__).with_name("negarena_bridge_driver.py")
_DEFAULT_TIMEOUT_SECONDS = 60.0


class NegarenaBridgeUnavailableError(RuntimeError):
    """No usable pinned-upstream Python interpreter could be located.

    Raised only at discovery/construction time. Never caught silently with a
    fabricated result -- callers decide whether an unavailable bridge is
    acceptable for their purpose, mirroring
    ``tau3_retail/tau2_bridge.py``'s identical convention.
    """


class NegarenaBridgeError(RuntimeError):
    """The bridge subprocess ran but reported an infrastructure failure.

    Distinct from an upstream *parse*-level failure (a scripted response
    upstream's own parser rejects), which this bridge reports as a normal
    ``ok=True, parsed=False`` response, never as an exception -- mirroring
    ``tau2_bridge.py``'s "a tool-level error is not an infra failure"
    convention.
    """


def discover_bridge_python(*, upstream_root: Path | str | None = None) -> Path:
    """Locate a Python interpreter with the pinned upstream package importable.

    Resolution order (first match wins), mirroring ``tau2_bridge.py``'s
    ``AEREAD_TAU2_BRIDGE_PYTHON`` convention:

    1. ``$AEREAD_NEGARENA_BRIDGE_PYTHON`` -- an explicit path to a python
       executable, set up through whatever offline/approved channel
       provisioned it (``tools/negarena_bridge/provision.sh``). Never
       installed or downloaded by this function.
    2. ``<upstream_root>/.venv/bin/python`` -- a venv colocated with the
       pinned upstream checkout, if one happens to exist there.

    Raises ``NegarenaBridgeUnavailableError`` if neither resolves to an
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
        raise NegarenaBridgeUnavailableError(
            f"${BRIDGE_PYTHON_ENV_VAR} is set to {candidate!r} but that path "
            "does not exist"
        )
    if upstream_root is not None:
        colocated = Path(upstream_root) / ".venv" / "bin" / "python"
        if colocated.is_file():
            return colocated
    raise NegarenaBridgeUnavailableError(
        "no pinned upstream NegotiationArena Python interpreter found: set "
        f"${BRIDGE_PYTHON_ENV_VAR} to a Python executable with the pinned "
        "upstream checkout's runtime dependencies installed, e.g. a "
        "pre-provisioned venv with openai/anthropic installed. AERead's own "
        "venv intentionally does not carry them -- see "
        "docs/negarena_adapter_spec.md and tools/negarena_bridge/provision.sh."
    )


class NegarenaBridge:
    """One provider-free delegate to the pinned upstream negarena parser and
    admission-gate logic.

    Every method spawns a fresh, short-lived subprocess running
    ``negarena_bridge_driver.py`` under ``python_executable``. Nothing is
    cached across calls; all game state lives in the caller's own kernel
    state (see ``environment.py``).
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
    ) -> "NegarenaBridge":
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
        for name in tuple(environment):
            if name.endswith("_API_KEY"):
                environment.pop(name)
        try:
            completed = subprocess.run(
                [
                    str(self.python_executable),
                    str(_DRIVER_SCRIPT),
                    "--upstream-root",
                    str(self.upstream_root),
                ],
                input=json.dumps(_plain(request)).encode("utf-8"),
                capture_output=True,
                env=environment,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise NegarenaBridgeError(
                f"bridge subprocess timed out after {self.timeout_seconds}s "
                f"for op={request.get('op')!r}"
            ) from error
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NegarenaBridgeError(
                "bridge subprocess did not return one JSON object on stdout "
                f"(exit={completed.returncode}) for op={request.get('op')!r}; "
                f"stderr:\n{completed.stderr.decode('utf-8', errors='replace')}"
            ) from error
        if not isinstance(response, dict) or not response.get("ok"):
            raise NegarenaBridgeError(
                f"bridge subprocess reported an infrastructure failure for "
                f"op={request.get('op')!r}: {response!r}"
            )
        return response

    def parse_response(self, *, game_kind: str, response: str) -> dict[str, Any]:
        """Delegate a scripted response to upstream's own parser class.

        Returns ``{"parsed": True, "public": {...}, "secret": {...}}`` on a
        clean parse, or ``{"parsed": False, "parse_error_type": str,
        "parse_error_message": str}`` when upstream's own parser raised --
        a normal, in-band result, never an exception (see
        ``negarena_bridge_driver.py``'s protocol docstring).
        """
        result = self._run({"op": "parse_response", "game_kind": game_kind, "response": response})
        if result["parsed"]:
            return {"parsed": True, "public": result["public"], "secret": result["secret"]}
        return {
            "parsed": False,
            "parse_error_type": result["parse_error_type"],
            "parse_error_message": result["parse_error_message"],
        }

    def check_trade(
        self,
        *,
        direction: str,
        give: Mapping[str, Mapping[str, int]],
        resources: Mapping[str, int],
    ) -> bool:
        """Delegate the trade-legality admission gate to upstream's own
        ``Trade.can_offer``/``Trade.can_accept`` (spec section 3: an
        adapter-owned gate upstream itself never applies, but delegated to
        upstream's own ``Resources.check_transaction_legal`` arithmetic,
        never reimplemented).
        """
        result = self._run(
            {
                "op": "check_trade",
                "direction": direction,
                "give": dict(give),
                "resources": dict(resources),
            }
        )
        return bool(result["legal"])

    def runtime_info(self) -> dict[str, Any]:
        return self._run({"op": "runtime_info"})
