"""Cross-process delegate to the pinned upstream AgenticPay bilateral environment.

AERead's own environment runs Python 3.11 and deliberately does not carry
``agenticpay``'s runtime dependencies: importing the package at all
unconditionally imports ``agents.buyer_agent``/``agents.seller_agent``
(``agenticpay/__init__.py`` -> ``agenticpay/agents/__init__.py``), both of
which do ``from loguru import logger`` -- a dependency upstream's own
``requirements.txt`` never declares and which is not present in this
project's venv (reproduced from this worktree: ``ModuleNotFoundError: No
module named 'loguru'``). ``agenticpay.models.base_vlm`` additionally
requires ``numpy``. See ``docs/agenticpay_adapter_spec.md``'s governing
facts.

Rather than reimplement any price/contract extraction, legality check, or
scoring formula -- forbidden outright by the spec's adapter-boundary section
-- this module shells out, once per call, to a small self-contained driver
script (``agenticpay_bridge_driver.py``) run under a SEPARATE,
already-provisioned Python interpreter that has ``loguru``/``numpy``
installed. The driver always imports ``agenticpay`` source from the
caller-supplied pinned checkout, even if the interpreter has another
``agenticpay`` distribution installed.

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

BRIDGE_PYTHON_ENV_VAR = "AEREAD_AGENTICPAY_BRIDGE_PYTHON"

_DRIVER_SCRIPT = Path(__file__).with_name("agenticpay_bridge_driver.py")
_DEFAULT_TIMEOUT_SECONDS = 60.0


class AgenticpayBridgeUnavailableError(RuntimeError):
    """No usable pinned-upstream Python interpreter could be located.

    Raised only at discovery/construction time. Never caught silently with a
    fabricated result -- callers decide whether an unavailable bridge is
    acceptable for their purpose, mirroring ``tau3_retail.tau2_bridge``'s
    identical convention.
    """


class AgenticpayBridgeError(RuntimeError):
    """The bridge subprocess ran but reported an infrastructure failure."""


def discover_bridge_python(*, upstream_root: Path | str | None = None) -> Path:
    """Locate a Python interpreter with the pinned upstream package importable.

    Resolution order (first match wins), mirroring
    ``tau3_retail.tau2_bridge.discover_bridge_python``:

    1. ``$AEREAD_AGENTICPAY_BRIDGE_PYTHON`` -- an explicit path to a python
       executable, set up through whatever offline/approved channel
       provisioned it (``tools/agenticpay_bridge/provision.sh``). Never
       installed or downloaded by this function.
    2. ``<upstream_root>/.venv/bin/python`` -- a venv colocated with the
       pinned upstream checkout, if one happens to exist there.

    Raises ``AgenticpayBridgeUnavailableError`` if neither resolves to an
    existing file. Deliberately never falls back to ``sys.executable``.
    """
    candidate = os.environ.get(BRIDGE_PYTHON_ENV_VAR)
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
        raise AgenticpayBridgeUnavailableError(
            f"${BRIDGE_PYTHON_ENV_VAR} is set to {candidate!r} but that path does not exist"
        )
    if upstream_root is not None:
        colocated = Path(upstream_root) / ".venv" / "bin" / "python"
        if colocated.is_file():
            return colocated
    raise AgenticpayBridgeUnavailableError(
        "no pinned upstream AgenticPay Python interpreter found: set "
        f"${BRIDGE_PYTHON_ENV_VAR} to a Python executable with loguru/numpy "
        "installed, e.g. a pre-provisioned venv (tools/agenticpay_bridge/"
        "provision.sh). AERead's own venv intentionally does not carry "
        "AgenticPay's runtime dependencies -- see "
        "docs/agenticpay_adapter_spec.md."
    )


class AgenticpayBridge:
    """One provider-free delegate to the pinned upstream bilateral environment.

    Every method spawns a fresh, short-lived subprocess running
    ``agenticpay_bridge_driver.py`` under ``python_executable``. Nothing is
    cached across calls: unlike tau2-bench's ``RetailDB`` (a plain dict the
    caller passes in and gets back), upstream's negotiation environment is
    not JSON-serializable, so ``replay_round`` reconstructs it from scratch
    and replays the ordered ``history`` of completed rounds every time --
    see ``agenticpay_bridge_driver.py``'s module docstring.
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
        cls, upstream_root: Path | str, *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    ) -> "AgenticpayBridge":
        root = Path(upstream_root)
        python_executable = discover_bridge_python(upstream_root=root)
        return cls(python_executable=python_executable, upstream_root=root, timeout_seconds=timeout_seconds)

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
                input=json.dumps(request).encode("utf-8"),
                capture_output=True,
                env=environment,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise AgenticpayBridgeError(
                f"bridge subprocess timed out after {self.timeout_seconds}s for op={request.get('op')!r}"
            ) from error
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgenticpayBridgeError(
                "bridge subprocess did not return one JSON object on stdout "
                f"(exit={completed.returncode}) for op={request.get('op')!r}; "
                f"stderr:\n{completed.stderr.decode('utf-8', errors='replace')}"
            ) from error
        if not isinstance(response, dict) or not response.get("ok"):
            raise AgenticpayBridgeError(
                f"bridge subprocess reported an infrastructure failure for op={request.get('op')!r}: {response!r}"
            )
        return response

    def reset(
        self,
        *,
        env_module: str,
        env_class: str,
        constructor_kwargs: Mapping[str, Any],
        reset_kwargs: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Construct the environment and call ``reset()`` only; no round is applied."""
        response = self._run(
            {
                "op": "reset",
                "env_module": env_module,
                "env_class": env_class,
                "constructor_kwargs": dict(constructor_kwargs),
                "reset_kwargs": dict(reset_kwargs),
            }
        )
        return {"observation": response["observation"], "info": response["info"]}

    def replay_round(
        self,
        *,
        env_module: str,
        env_class: str,
        constructor_kwargs: Mapping[str, Any],
        reset_kwargs: Mapping[str, Any],
        history: Sequence[Mapping[str, Any]],
        buyer_action: str | None,
        seller_action: str | None,
    ) -> dict[str, Any]:
        """Replay every completed round then apply the requested new round.

        Returns ``{"observation": ..., "reward": float, "terminated": bool,
        "truncated": bool, "info": ...}`` -- upstream's own ``step()``
        result verbatim (after JSON-safe conversion), for the newly applied
        round only.
        """
        response = self._run(
            {
                "op": "replay_round",
                "env_module": env_module,
                "env_class": env_class,
                "constructor_kwargs": dict(constructor_kwargs),
                "reset_kwargs": dict(reset_kwargs),
                "history": [dict(item) for item in history],
                "buyer_action": buyer_action,
                "seller_action": seller_action,
            }
        )
        return {
            "observation": response["observation"],
            "reward": response["reward"],
            "terminated": response["terminated"],
            "truncated": response["truncated"],
            "info": response["info"],
        }

    def runtime_info(self) -> dict[str, str]:
        """Report the exact interpreter/package provenance used by the driver."""
        response = self._run({"op": "runtime_info"})
        return {
            "python_version": response["python_version"],
            "agenticpay_package_file": response["agenticpay_package_file"],
        }


__all__ = [
    "AgenticpayBridge",
    "AgenticpayBridgeError",
    "AgenticpayBridgeUnavailableError",
    "BRIDGE_PYTHON_ENV_VAR",
    "discover_bridge_python",
]
