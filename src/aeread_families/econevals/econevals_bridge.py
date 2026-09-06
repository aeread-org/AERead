"""Cross-process delegate to the pinned upstream ``econ-evals-paper`` code.

AERead's own environment runs Python 3.11 and deliberately does not carry
upstream's runtime dependencies (``numpy``, ``scipy``, ``pandas``,
``pydantic``, ``inflect``, ``gurobipy``) or upstream's required >=3.12
interpreter. Rather than reimplement any generator, solver, or scoring
primitive -- forbidden outright by ``docs/econevals_adapter_spec.md``
section 3 -- this module shells out, ONCE PER CALL, to a small
self-contained driver script (``econevals_bridge_driver.py``) run under a
SEPARATE, already-provisioned Python interpreter that has the pinned
upstream checkout importable (wired in by
``tools/econevals_bridge/provision.sh`` via a ``.pth`` file in that venv's
own site-packages).

One subprocess per call is not a style choice: procurement's own generator
draws its ``budget`` field from the *global* numpy RNG rather than the
``my_random`` argument every other draw uses (see
``docs/econevals_adapter_spec.md``'s "Governing facts" and
``tools/econevals_bridge/README.md``). A fresh subprocess has no prior
global-RNG draws to leak into that field, so this is what makes a
same-seed instance byte-reproducible. This convention is applied uniformly
to every op below, including scheduling's and pricing's generators, which do
not strictly need it (both draw only from their own ``my_random`` argument;
verified in recon) -- for one predictable rule rather than a per-track
exception.

No network call is made by this module or the driver it launches: the
target interpreter is a pre-existing local environment, located by an
explicit, documented environment variable or a fixed default path -- never
invented, downloaded, or installed on the fly.
"""
from __future__ import annotations

import json
import re
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

BRIDGE_PYTHON_ENV_VAR = "AEREAD_ECONEVALS_BRIDGE_PYTHON"

# Mirrors tools/econevals_bridge/provision.sh's own default venv path.
DEFAULT_BRIDGE_VENV = Path(
    "/Users/sunzeyu/Documents/econ benchmark/bridges/econevals-venv"
)

_DRIVER_SCRIPT = Path(__file__).with_name("econevals_bridge_driver.py")
_DEFAULT_TIMEOUT_SECONDS = 120.0


_SET_RENDERING = re.compile(r"\{('[^']*'(?:,\s*'[^']*')*)\}")


def _canonicalize_set_rendering(reason: Any) -> Any:
    """Rewrite a ``str(set)`` fragment into sorted order, leaving the rest.

    Only touches a brace-delimited run of single-quoted tokens, which is what
    CPython's set repr produces; any other text passes through untouched.
    """
    if not isinstance(reason, str):
        return reason

    def _sorted(match: "re.Match[str]") -> str:
        items = sorted(
            item.strip()[1:-1] for item in match.group(1).split(",")
        )
        return "{" + ", ".join(f"'{item}'" for item in items) + "}"

    return _SET_RENDERING.sub(_sorted, reason)



class EconevalsBridgeUnavailableError(RuntimeError):
    """No usable pinned-upstream Python interpreter could be located.

    Raised only at discovery/construction time. Never caught silently with a
    fabricated result -- callers decide whether an unavailable bridge is
    acceptable for their purpose (mirroring
    ``tau3_retail.tau2_bridge.Tau2BridgeUnavailableError``'s identical
    convention).
    """


class EconevalsBridgeError(RuntimeError):
    """The bridge subprocess ran but reported an infrastructure failure.

    Carries the driver's own ``error_type``/``message`` verbatim. This is
    distinct from an in-band upstream *result* (e.g. an infeasible
    allocation, ``is_feasible=False`` with a populated reason) -- upstream
    represents those as normal ``ok=true`` responses, never as exceptions.
    """

    def __init__(self, *, error_type: str, message: str, op: str) -> None:
        self.error_type = error_type
        self.op = op
        super().__init__(f"econevals bridge op {op!r} failed ({error_type}): {message}")


class GurobiLicenseSizeError(EconevalsBridgeError):
    """``compute_opt`` rejected the model under gurobipy's free-license cap.

    Raised only by :meth:`EconevalsBridge.procurement_reference`. The
    caller (``cases.py``) maps this to a typed ``"gurobi_license_size"``
    corpus-admission exclusion (spec section 1) rather than a silent drop or
    an unstructured crash.
    """


def discover_bridge_python(
    *, default_venv: Path | str = DEFAULT_BRIDGE_VENV
) -> Path:
    """Locate a Python interpreter with the pinned upstream package importable.

    Resolution order (first match wins):

    1. ``$AEREAD_ECONEVALS_BRIDGE_PYTHON`` -- an explicit path to a python
       executable, set up through whatever offline/approved channel
       provisioned it. Never installed or downloaded by this function.
    2. ``<default_venv>/bin/python`` -- the venv
       ``tools/econevals_bridge/provision.sh`` creates by default.

    Raises :class:`EconevalsBridgeUnavailableError` if neither resolves to
    an existing file. Deliberately never falls back to ``sys.executable``:
    silently running the driver under AERead's own (dependency-less)
    interpreter would fail with a confusing ``ModuleNotFoundError`` deep
    inside the driver instead of this clear, actionable error raised here.
    """
    candidate = os.environ.get(BRIDGE_PYTHON_ENV_VAR)
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
        raise EconevalsBridgeUnavailableError(
            f"${BRIDGE_PYTHON_ENV_VAR} is set to {candidate!r} but that path "
            "does not exist"
        )
    default_python = Path(default_venv) / "bin" / "python"
    if default_python.is_file():
        return default_python
    raise EconevalsBridgeUnavailableError(
        "no pinned upstream econ-evals Python interpreter found: set "
        f"${BRIDGE_PYTHON_ENV_VAR} to a Python >=3.12 executable with the "
        "pinned upstream package importable (see "
        "tools/econevals_bridge/provision.sh), or provision the default "
        f"venv at {default_python}. AERead's own venv intentionally does "
        "not carry econ-evals' runtime dependencies -- see "
        "docs/econevals_adapter_spec.md."
    )


class EconevalsBridge:
    """One provider-free delegate to the pinned upstream econ-evals code.

    Every method spawns a fresh, short-lived subprocess running
    ``econevals_bridge_driver.py`` under ``python_executable``. Nothing is
    cached across calls; each call is independently reproducible from its
    own JSON-shaped arguments, matching the "one fresh subprocess per call"
    convention this module's docstring explains.
    """

    def __init__(
        self,
        *,
        python_executable: Path | str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.python_executable = Path(python_executable)
        self.timeout_seconds = timeout_seconds

    @classmethod
    def discover(
        cls, *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    ) -> "EconevalsBridge":
        return cls(
            python_executable=discover_bridge_python(),
            timeout_seconds=timeout_seconds,
        )

    def _run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for name in tuple(environment):
            if name.endswith("_API_KEY"):
                environment.pop(name)
        op = request.get("op")
        try:
            completed = subprocess.run(
                [str(self.python_executable), str(_DRIVER_SCRIPT)],
                input=json.dumps(request).encode("utf-8"),
                capture_output=True,
                env=environment,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise EconevalsBridgeError(
                error_type="TimeoutExpired",
                message=f"bridge subprocess timed out after {self.timeout_seconds}s",
                op=str(op),
            ) from error
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EconevalsBridgeError(
                error_type="MalformedResponse",
                message=(
                    "bridge subprocess did not return one JSON object on "
                    f"stdout (exit={completed.returncode}); stderr:\n"
                    f"{completed.stderr.decode('utf-8', errors='replace')}"
                ),
                op=str(op),
            ) from error
        if not isinstance(response, dict) or not response.get("ok"):
            error_type = (
                response.get("error_type", "unknown")
                if isinstance(response, dict)
                else "unknown"
            )
            message = (
                response.get("message", repr(response))
                if isinstance(response, dict)
                else repr(response)
            )
            if op == "procurement_reference" and error_type == "GurobiError":
                raise GurobiLicenseSizeError(
                    error_type=error_type, message=message, op=str(op)
                )
            raise EconevalsBridgeError(error_type=error_type, message=message, op=str(op))
        return response

    def generate_procurement_instance(
        self,
        *,
        seed: int,
        num_inputs: int,
        num_alternatives_per_input: int,
        num_entries: int,
        num_items_per_entry_p: float,
        quantity_per_item_p: float,
        offer_qty_in_sample_bundle_p: float,
        min_effectiveness: int,
        max_effectiveness: int,
    ) -> dict[str, Any]:
        """Delegate to upstream's ``generate_instance`` for procurement."""
        response = self._run(
            {
                "op": "generate_procurement",
                "seed": seed,
                "num_inputs": num_inputs,
                "num_alternatives_per_input": num_alternatives_per_input,
                "num_entries": num_entries,
                "NUM_ITEMS_PER_ENTRY_P": num_items_per_entry_p,
                "QUANTITY_PER_ITEM_P": quantity_per_item_p,
                "OFFER_QTY_IN_SAMPLE_BUNDLE_P": offer_qty_in_sample_bundle_p,
                "MIN_EFFECTIVENESS": min_effectiveness,
                "MAX_EFFECTIVENESS": max_effectiveness,
            }
        )
        return response["instance"]

    def procurement_reference(
        self,
        *,
        instance: Mapping[str, Any],
        group_weights: list[float],
        agg_type: str,
    ) -> dict[str, Any]:
        """Delegate to upstream's ``compute_opt`` + ``evaluate_alloc``.

        Raises :class:`GurobiLicenseSizeError` if gurobipy's free-license
        cap rejects the model.
        """
        response = self._run(
            {
                "op": "procurement_reference",
                "instance": dict(instance),
                "group_weights": list(group_weights),
                "agg_type": agg_type,
            }
        )
        return response["gold_optimum"]

    def procurement_evaluate(
        self,
        *,
        instance: Mapping[str, Any],
        alloc: Mapping[str, int],
        group_weights: list[float],
        agg_type: str,
    ) -> dict[str, Any]:
        """Delegate to upstream's ``evaluate_alloc`` for a submitted allocation.

        Callers MUST pre-validate that every key of ``alloc`` is a known
        offer id before calling this (spec section 3): an unknown offer id
        reaches upstream's own ``Menu.__getitem__``, which asserts
        membership, and this method re-raises that as
        :class:`EconevalsBridgeError` with ``error_type="AssertionError"``
        rather than a graceful result.
        """
        response = self._run(
            {
                "op": "procurement_evaluate",
                "instance": dict(instance),
                "alloc": dict(alloc),
                "group_weights": list(group_weights),
                "agg_type": agg_type,
            }
        )
        return {
            "is_feasible": response["is_feasible"],
            "invalid_reason": response["invalid_reason"],
            "cost": response["cost"],
            "utility": response["utility"],
        }

    def generate_scheduling_instance(
        self,
        *,
        seed: int,
        num_workers: int,
        score_gap_worker: float | None,
        score_gap_task: float | None,
    ) -> dict[str, Any]:
        """Delegate to upstream's ``generate_preferences`` for scheduling."""
        response = self._run(
            {
                "op": "generate_scheduling",
                "seed": seed,
                "num_workers": num_workers,
                "score_gap_worker": score_gap_worker,
                "score_gap_task": score_gap_task,
            }
        )
        return response["instance"]

    def scheduling_validate(
        self,
        *,
        matching: Mapping[str, str],
        worker_ids: list[str],
        task_ids: list[str],
    ) -> dict[str, Any]:
        """Delegate to upstream's ``is_valid_matching``."""
        response = self._run(
            {
                "op": "scheduling_validate",
                "matching": dict(matching),
                "worker_ids": list(worker_ids),
                "task_ids": list(task_ids),
            }
        )
        # Upstream renders a Python set straight into this message
        # (`"Assignment doesn't include workers: " + str(unmatched_workers)`,
        # stable_matching_environment.py line 22). Set iteration order is not
        # stable across processes, so the raw string differs run to run and
        # the kernel's tool-replay cross-check reports a spurious divergence
        # -- nondeterministically, which is the worst kind. Upstream is
        # pinned and read-only, so the boundary canonicalizes the rendering
        # here. No information is dropped: the same ids, in sorted order.
        return {
            "valid": response["valid"],
            "reason": _canonicalize_set_rendering(response["reason"]),
        }

    def scheduling_blocking_pairs(
        self,
        *,
        matching: Mapping[str, str],
        worker_prefs: Mapping[str, list[str]],
        task_prefs: Mapping[str, list[str]],
    ) -> list[list[str]]:
        """Delegate to upstream's ``get_blocking_pairs`` for a valid matching."""
        response = self._run(
            {
                "op": "scheduling_blocking_pairs",
                "matching": dict(matching),
                "worker_prefs": {k: list(v) for k, v in worker_prefs.items()},
                "task_prefs": {k: list(v) for k, v in task_prefs.items()},
            }
        )
        return response["blocking_pairs"]

    def generate_pricing_instance(
        self,
        *,
        seed: int,
        num_products: int,
        noise_param: float,
        sigma: float,
        mu: float,
        start_multiplier: float,
        group_idx_p: float,
        group_idx_cutoff_proportion: float,
        num_attempts: int,
        product_ids: list[str],
        env_type: str,
    ) -> dict[str, Any]:
        """Delegate to upstream's ``generate_instance`` for pricing.

        Reproduces ``run_pricing_batch.py``'s own draw order (see the
        driver's docstring): a single ``RandomState(seed)`` draws
        ``starting_alphas``/``cost_list``/``a_list``/``period_length``
        before upstream's ``generate_instance`` consumes further draws from
        the same object.
        """
        response = self._run(
            {
                "op": "generate_pricing",
                "seed": seed,
                "num_products": num_products,
                "noise_param": noise_param,
                "sigma": sigma,
                "mu": mu,
                "start_multiplier": start_multiplier,
                "group_idx_p": group_idx_p,
                "group_idx_cutoff_proportion": group_idx_cutoff_proportion,
                "num_attempts": num_attempts,
                "product_ids": list(product_ids),
                "env_type": env_type,
            }
        )
        return response["instance"]

    def pricing_reference(self, *, instance: Mapping[str, Any]) -> dict[str, Any]:
        """Delegate to upstream's ``get_monopoly_prices``/``get_profits``.

        Computes, for EVERY period baked into ``instance`` (its own
        ``alpha_list``/``multiplier_list``), a bit-exact call to
        ``get_monopoly_prices`` for that period (never upstream's own
        interpolated ``get_monopoly_prices_varying_alphas``), then
        ``get_profits`` at those prices. This is one bridge call performing
        many upstream calls in one subprocess, mirroring how
        ``procurement_reference`` performs both ``compute_opt`` and
        ``evaluate_alloc`` in one call: the "one subprocess per call"
        convention is about isolating RNG state between GENERATION calls,
        not about limiting how many pure (RNG-free) upstream functions one
        call may invoke.
        """
        response = self._run(
            {"op": "pricing_reference", "instance": dict(instance)}
        )
        return response["gold_optimum"]

    def pricing_profits(
        self,
        *,
        instance: Mapping[str, Any],
        period: int,
        prices: Mapping[str, float],
    ) -> dict[str, float]:
        """Delegate to upstream's ``get_profits`` for a submitted price vector."""
        response = self._run(
            {
                "op": "pricing_profits",
                "instance": dict(instance),
                "period": period,
                "prices": dict(prices),
            }
        )
        return response["profits"]

    def runtime_info(self) -> dict[str, str]:
        """Report the exact interpreter/package provenance used by the driver."""
        response = self._run({"op": "runtime_info"})
        return {
            "python_version": response["python_version"],
            "econ_evals_package_file": response["econ_evals_package_file"],
            "gurobipy_version": response["gurobipy_version"],
        }


__all__ = [
    "BRIDGE_PYTHON_ENV_VAR",
    "DEFAULT_BRIDGE_VENV",
    "EconevalsBridge",
    "EconevalsBridgeError",
    "EconevalsBridgeUnavailableError",
    "GurobiLicenseSizeError",
    "discover_bridge_python",
]
