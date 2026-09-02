"""Cross-process delegate to pandas for flattening the pinned STEER corpus.

AERead's own environment (Python 3.11) deliberately does not carry pandas --
unpickling any ``elements/<name>/*.pkl`` file in the pinned upstream
checkout (``narunraman/STEER`` @ ``d66673c8277b9112fc5e39751524ccda6d852446``)
requires it (docs/steer_adapter_spec.md's Governing facts: "a missing-package
gap, not a Python-version gap").

Rather than installing pandas into the project venv, this module shells out,
once per declared element, to a small self-contained driver script
(``steer_bridge_driver.py``) run under a SEPARATE, already-provisioned Python
interpreter that has pandas installed. The driver always reads pinned source
from the caller-supplied upstream checkout and cache directory; nothing about
the corpus's schema-drift or admission classification is ever hand-derived
here -- see ``steer_bridge_driver.py``'s own module docstring for the exact
flatten algorithm.

No network call is made by this module or by the driver's ``flatten`` op:
the target interpreter is a pre-existing local environment, located by an
explicit, documented environment variable or a fixed sibling path -- never
invented, downloaded, or installed on the fly. The driver's separate
``fetch`` op does reach the network, but this module never invokes it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

BRIDGE_PYTHON_ENV_VAR = "AEREAD_STEER_BRIDGE_PYTHON"

_DRIVER_SCRIPT = Path(__file__).with_name("steer_bridge_driver.py")
_DEFAULT_TIMEOUT_SECONDS = 120.0


class SteerBridgeUnavailableError(RuntimeError):
    """No usable pandas-capable Python interpreter could be located.

    Raised only at discovery/construction time. Never caught silently with a
    fabricated result -- callers decide whether an unavailable bridge is
    acceptable for their purpose, mirroring
    ``aeread_families.tau3_retail.tau2_bridge``'s identical convention for
    its own upstream interpreter.
    """


class SteerBridgeError(RuntimeError):
    """The bridge subprocess ran but reported an infrastructure failure.

    Includes a malformed/missing cache, a git-lfs sha256 mismatch, and an
    unrecognized ``Answers`` schema -- every one of these is a hard failure
    reported through this exception, never a fabricated or partial result.
    """


def _default_bridge_python() -> Path | None:
    """``bridges/steer-venv/bin/python``, a sibling of the AERead repo.

    Walks up from this file's location looking for a directory literally
    named ``AERead`` (the repo may be checked out directly or, as in this
    session, opened from a git worktree nested under it) and returns the
    conventional venv path next to it. Returns ``None`` if no such ancestor
    exists; callers fall back to requiring the environment variable.
    """
    for parent in Path(__file__).resolve().parents:
        if parent.name == "AERead":
            return parent.parent / "bridges" / "steer-venv" / "bin" / "python"
    return None


def discover_bridge_python() -> Path:
    """Locate a Python interpreter with pandas installed for the bridge.

    Resolution order (first match wins):

    1. ``$AEREAD_STEER_BRIDGE_PYTHON`` -- an explicit path to a python
       executable, set up through whatever offline/approved channel
       provisioned it (``tools/steer_bridge/provision.sh``). Never installed
       or downloaded by this function.
    2. ``<sibling-of-AERead>/bridges/steer-venv/bin/python`` -- the
       conventional colocated venv this session provisioned.

    Raises ``SteerBridgeUnavailableError`` if neither resolves to an
    existing file. Deliberately never falls back to ``sys.executable``:
    silently running the driver under AERead's own (pandas-less) interpreter
    would fail with a confusing ``ModuleNotFoundError`` deep inside the
    driver instead of this clear, actionable error raised here.
    """
    candidate = os.environ.get(BRIDGE_PYTHON_ENV_VAR)
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
        raise SteerBridgeUnavailableError(
            f"${BRIDGE_PYTHON_ENV_VAR} is set to {candidate!r} but that path "
            "does not exist"
        )
    default = _default_bridge_python()
    if default is not None and default.is_file():
        return default
    raise SteerBridgeUnavailableError(
        "no pandas-capable Python interpreter found for the steer bridge: "
        f"set ${BRIDGE_PYTHON_ENV_VAR} to one, e.g. a venv built by "
        "tools/steer_bridge/provision.sh. AERead's own venv intentionally "
        "does not carry pandas -- see docs/steer_adapter_spec.md."
    )


class SteerBridge:
    """One provider-free, network-free delegate to pandas for Gate 1.

    Every call spawns a fresh, short-lived subprocess running
    ``steer_bridge_driver.py`` under ``python_executable``. Nothing is
    cached across calls in this process; the driver itself reads and
    verifies bytes already cached at ``cache_root`` (see
    ``flatten_element``'s docstring for the no-network guarantee).
    """

    def __init__(
        self,
        *,
        python_executable: Path | str,
        upstream_root: Path | str,
        cache_root: Path | str,
        expected_commit: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.python_executable = Path(python_executable)
        self.upstream_root = Path(upstream_root)
        self.cache_root = Path(cache_root)
        self.expected_commit = expected_commit
        self.timeout_seconds = timeout_seconds

    @classmethod
    def discover(
        cls,
        *,
        upstream_root: Path | str,
        cache_root: Path | str,
        expected_commit: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> "SteerBridge":
        return cls(
            python_executable=discover_bridge_python(),
            upstream_root=upstream_root,
            cache_root=cache_root,
            expected_commit=expected_commit,
            timeout_seconds=timeout_seconds,
        )

    def _run(self, request: dict[str, Any]) -> dict[str, Any]:
        command = [
            str(self.python_executable),
            str(_DRIVER_SCRIPT),
            "--upstream-root",
            str(self.upstream_root),
            "--cache-root",
            str(self.cache_root),
        ]
        if self.expected_commit is not None:
            command.extend(["--expected-commit", self.expected_commit])
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(request).encode("utf-8"),
                capture_output=True,
                env=dict(os.environ),
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise SteerBridgeError(
                f"bridge subprocess timed out after {self.timeout_seconds}s "
                f"for op={request.get('op')!r}"
            ) from error
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SteerBridgeError(
                "bridge subprocess did not return one JSON object on stdout "
                f"(exit={completed.returncode}) for op={request.get('op')!r}; "
                f"stderr:\n{completed.stderr.decode('utf-8', errors='replace')}"
            ) from error
        if not isinstance(response, dict) or not response.get("ok"):
            raise SteerBridgeError(
                f"bridge subprocess reported an infrastructure failure for "
                f"op={request.get('op')!r}: {response!r}"
            )
        return response

    def flatten_element(self, element: str, *, head_n: int = 200) -> dict[str, Any]:
        """Unpickle, join, classify, and admit one declared element.

        Reads only bytes already cached at ``cache_root/<element>/*.pkl``
        (never fetches over the network); verifies each file's sha256
        against the git-lfs ``oid`` recorded in the pinned upstream
        checkout before touching pandas. Returns
        ``{"element": str, "file_hashes": {...}, "counts": {"total",
        "exactly_one_correct", "zero_correct", "multi_correct"},
        "admitted": [...], "zero_correct_sample_question_id": str | None}``;
        see ``steer_bridge_driver.py``'s module docstring for the exact
        per-field shape of an admitted row.
        """
        response = self._run({"op": "flatten", "element": element, "head_n": head_n})
        return {
            "element": response["element"],
            "file_hashes": response["file_hashes"],
            "counts": response["counts"],
            "admitted": response["admitted"],
            "zero_correct_sample_question_id": response["zero_correct_sample_question_id"],
        }

    def fetch_element(self, element: str) -> list[str]:
        """Download any of ``element``'s 4 files missing from the cache.

        The only network-touching operation this bridge exposes. Never
        invoked by ``cases.py``'s import routine, the environment plugin, or
        any test -- callers who need to (re)populate the cache invoke this
        explicitly, once, outside the test suite.
        """
        response = self._run({"op": "fetch", "element": element})
        return list(response["fetched"])

    def raw_answer_rows(self, element: str, question_id: str) -> list[dict[str, Any]]:
        """One question_id's RAW ``answers`` frame rows, unclassified.

        Never reuses ``flatten_element``'s own admission classification --
        exists so a caller can independently re-derive ground truth from a
        genuinely different code path (docs/steer_codex_triage.md finding
        4). Returns ``[{"option_id": int, "correct_repr": str}, ...]``,
        sorted by ``option_id``; ``correct_repr`` is ``repr()`` of the raw
        cell value, left for the caller to interpret.
        """
        response = self._run(
            {"op": "raw_answer_rows", "element": element, "question_id": question_id}
        )
        return list(response["rows"])


__all__ = [
    "BRIDGE_PYTHON_ENV_VAR",
    "SteerBridge",
    "SteerBridgeError",
    "SteerBridgeUnavailableError",
    "discover_bridge_python",
]
