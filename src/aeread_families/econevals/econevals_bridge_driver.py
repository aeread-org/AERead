#!/usr/bin/env python
"""Subprocess driver for the ``econevals`` family's ``EconevalsBridge``.

This script runs under a SEPARATE, already-provisioned Python interpreter
(>=3.12, per ``tools/econevals_bridge/provision.sh``) with the pinned
upstream ``econ-evals-paper`` checkout importable as ``econ_evals`` (wired in
by that provisioning script via a ``.pth`` file in the venv's own
site-packages -- never ``pip install -e`` on the read-only upstream checkout;
see ``tools/econevals_bridge/README.md``).

It exists so ``cases.py``/``environment.py`` -- which run inside AERead's own
Python 3.11 interpreter and deliberately do not carry upstream's runtime
dependencies (``numpy``, ``scipy``, ``pandas``, ``pydantic``, ``inflect``,
``gurobipy``) -- can delegate every instance generation and scoring-primitive
call to the real upstream implementation instead of reimplementing any of
it. Every function below either reads static data or calls straight into
upstream code (``generate_instance``, ``compute_opt``, ``evaluate_alloc``,
``generate_preferences``, ``is_valid_matching``, ``get_blocking_pairs``,
``get_monopoly_prices``, ``get_profits``); none of it reimplements a
generator, a solver, or a scoring rule.

Governing fact (see ``docs/econevals_adapter_spec.md`` "Governing facts" and
``tools/econevals_bridge/README.md``): procurement's ``generate_instance``
draws its ``budget`` field from the *global* ``numpy.random`` state instead
of the ``my_random: RandomState`` argument every other draw in that function
uses. This driver is invoked ONCE PER OPERATION, in a fresh subprocess, and
every ``generate_*`` op below reseeds the global RNG (``np.random.seed``)
immediately before calling upstream's generator -- so a same-seed instance
is byte-reproducible regardless of what any other code in this process
already drew from the global RNG. Do not call an upstream generator twice in
one process invocation of this driver and expect both calls to reproduce;
the bridge wrapper (``econevals_bridge.py``) enforces one op per subprocess.

This file must not import anything from the ``aeread`` package: it is
invoked as a standalone script under a *different* Python interpreter that
does not have ``aeread`` on its path.

Protocol -- exactly one JSON object read from stdin, exactly one JSON object
written to stdout:

  {"op": "generate_procurement", "seed": int, "num_inputs": int,
   "num_alternatives_per_input": int, "num_entries": int,
   "NUM_ITEMS_PER_ENTRY_P": float, "QUANTITY_PER_ITEM_P": float,
   "OFFER_QTY_IN_SAMPLE_BUNDLE_P": float, "MIN_EFFECTIVENESS": int,
   "MAX_EFFECTIVENESS": int}
      -> {"ok": true, "instance": {"menu": <Menu.to_dict()>, "budget": float,
          "item_groups": [[str,...],...], "start_alloc": {str: int},
          "item_to_effectiveness": {str: int}}}
      -- delegates to
         econ_evals.experiments.procurement.generate_instance.generate_instance.

  {"op": "procurement_reference", "instance": <as above>,
   "group_weights": [float,...], "agg_type": "min"|"prod"}
      -> {"ok": true, "gold_optimum": {"opt_alloc": {str: int},
          "opt_cost": float, "opt_utility": float, "opt_value": float,
          "is_feasible": true, "invalid_reason": ""}}
      -- delegates to
         econ_evals.experiments.procurement.opt_solver.compute_opt (MILP via
         gurobipy) then .evaluate_alloc on the returned allocation. A Gurobi
         license-size rejection surfaces as gurobipy's own ``GurobiError``,
         which this op does not catch: it propagates to ``main``'s outer
         handler as {"ok": false, "error_type": "GurobiError", ...} so the
         caller can log a typed "gurobi_license_size" exclusion (spec
         section 1) instead of silently dropping the candidate.

  {"op": "procurement_evaluate", "instance": <as above>, "alloc": {str: int},
   "group_weights": [float,...], "agg_type": "min"|"prod"}
      -> {"ok": true, "is_feasible": bool, "invalid_reason": str,
          "cost": float, "utility": float}
      -- delegates to
         econ_evals.experiments.procurement.opt_solver.evaluate_alloc for an
         ARBITRARY submitted allocation (used for per-period environment
         feedback and for golden fixtures). ``Menu.__getitem__`` asserts
         offer-id membership (see spec's "Governing facts"); the adapter
         boundary (spec section 3) assigns pre-validating submitted offer
         ids to AERead's own environment code, not to this driver, so an
         unknown offer id here still surfaces as an uncaught
         ``AssertionError`` -> {"ok": false, "error_type": "AssertionError",
         ...}, exactly like any other unhandled upstream exception.

  {"op": "generate_scheduling", "seed": int, "num_workers": int,
   "score_gap_worker": float | null, "score_gap_task": float | null}
      -> {"ok": true, "instance": {"worker_ids": [str,...],
          "task_ids": [str,...], "worker_prefs": {str: [str,...]},
          "task_prefs": {str: [str,...]}}}
      -- delegates to
         econ_evals.experiments.scheduling.generate_preferences.generate_preferences.
         Needs no RNG workaround (upstream draws only from the supplied
         ``my_random``; verified in recon), but is still run one call per
         subprocess for uniformity with procurement's non-negotiable
         convention (spec section 1/3).

  {"op": "scheduling_validate", "matching": {str: str}, "worker_ids": [str,...],
   "task_ids": [str,...]}
      -> {"ok": true, "valid": bool, "reason": str}
      -- delegates to
         econ_evals.experiments.scheduling.stable_matching_environment.is_valid_matching.

  {"op": "scheduling_blocking_pairs", "matching": {str: str},
   "worker_prefs": {str: [str,...]}, "task_prefs": {str: [str,...]}}
      -> {"ok": true, "blocking_pairs": [[worker, task], ...]}
      -- delegates to
         econ_evals.experiments.scheduling.stable_matching_environment.get_blocking_pairs.
         Scheduling has no upstream optimum solver (spec's "Governing
         facts"): the reference is the analytic Gale-Shapley existence
         claim (0 blocking pairs always attainable), never computed by this
         op -- this op only scores a SUBMITTED matching, exactly as
         upstream's own per-period feedback loop does.

  {"op": "generate_pricing", "seed": int, "num_products": int,
   "noise_param": float, "sigma": float, "mu": float,
   "start_multiplier": float, "group_idx_p": float,
   "group_idx_cutoff_proportion": float, "num_attempts": int,
   "product_ids": [str,...], "env_type": "linear_shifts"|"periodic_shifts"}
      -> {"ok": true, "instance": <PricingArgs.model_dump(mode="json")>}
      -- reproduces run_pricing_batch.py's own draw order verbatim (a single
         ``np.random.RandomState(seed)`` draws ``starting_alphas``,
         ``cost_list``, ``a_list``, and ``period_length`` BEFORE
         econ_evals.experiments.pricing.generate_instance.generate_instance
         consumes further draws from that same object) -- never
         reimplemented, only re-sequenced exactly as upstream's own batch
         script does it. Needs no RNG workaround: every draw here comes from
         the supplied ``my_random`` (verified in recon).

  {"op": "pricing_reference", "instance": <as above>}
      -> {"ok": true, "gold_optimum": {"prices_by_period": [[float,...],...],
          "profits_by_period": [[float,...],...]}}
      -- for every period 0..num_attempts-1, delegates to
         econ_evals.experiments.pricing.pricing_market_logic_multiproduct's
         .get_monopoly_prices (a bit-exact call for that period's own
         ``alpha``/``multiplier``, never upstream's own
         ``get_monopoly_prices_varying_alphas`` interpolation, which trades
         exactness for speed) then .get_profits on those prices. This is a
         numerical, not closed-form, optimum (scipy `minimize`) -- see spec
         section 2 and 6.

  {"op": "pricing_profits", "instance": <as above>, "period": int,
   "prices": {product_id: float}}
      -> {"ok": true, "profits": {product_id: float},
          "quantities": {product_id: float}}
      -- delegates to the same .get_profits for an ARBITRARY submitted price
         vector at a given period (per-period environment feedback and
         golden fixtures); upstream's own ``set_prices`` tool already
         validates product-id membership before this call would ever be
         reached (spec's "Governing facts": pricing, unlike procurement, has
         no assertion-crash risk here), so no defensive pre-check is needed
         on this op's input shape beyond what upstream's own dict lookup
         does.

  {"op": "runtime_info"}
      -> {"ok": true, "python_version": str, "econ_evals_package_file": str,
          "gurobipy_version": str}

  Anything else (bad op, malformed request, import failure, upstream
  exception of any kind including GurobiError/AssertionError) ->
      {"ok": false, "error_type": str, "message": str}, exit code 1.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _entry_kwargs(fields: dict[str, Any]) -> dict[str, Any]:
    """Reverse ``opt_solver.Menu.to_dict()``'s per-entry shape into ``Entry`` kwargs."""
    kwargs = {"contents": fields["contents"]}
    for key in ("cost", "fixed_cost", "variable_cost", "min_quantity"):
        if key in fields:
            kwargs[key] = fields[key]
    return kwargs


def _menu_from_dict(menu_dict: dict[str, Any]):
    from econ_evals.experiments.procurement.opt_solver import Entry, Menu

    entries = [
        Entry(id=entry_id, type=fields["type"], **_entry_kwargs(fields))
        for entry_id, fields in menu_dict.items()
    ]
    return Menu(entries=entries)


def _op_generate_procurement(request: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    from econ_evals.experiments.procurement.generate_instance import generate_instance

    seed = request["seed"]
    # Reseed the GLOBAL numpy RNG immediately before generating: procurement's
    # own budget draw uses it instead of the my_random argument below (see
    # this module's docstring and docs/econevals_adapter_spec.md).
    np.random.seed(seed)
    my_random = np.random.RandomState(seed)
    menu, budget, item_groups, start_alloc, item_to_effectiveness = generate_instance(
        num_inputs=request["num_inputs"],
        num_alternatives_per_input=request["num_alternatives_per_input"],
        num_entries=request["num_entries"],
        my_random=my_random,
        NUM_ITEMS_PER_ENTRY_P=request["NUM_ITEMS_PER_ENTRY_P"],
        QUANTITY_PER_ITEM_P=request["QUANTITY_PER_ITEM_P"],
        OFFER_QTY_IN_SAMPLE_BUNDLE_P=request["OFFER_QTY_IN_SAMPLE_BUNDLE_P"],
        MIN_EFFECTIVENESS=request["MIN_EFFECTIVENESS"],
        MAX_EFFECTIVENESS=request["MAX_EFFECTIVENESS"],
    )
    return {
        "ok": True,
        "instance": {
            "menu": menu.to_dict(),
            "budget": budget,
            "item_groups": item_groups,
            "start_alloc": start_alloc,
            "item_to_effectiveness": item_to_effectiveness,
        },
    }


def _op_procurement_reference(request: dict[str, Any]) -> dict[str, Any]:
    from econ_evals.experiments.procurement.opt_solver import compute_opt, evaluate_alloc

    instance = request["instance"]
    menu = _menu_from_dict(instance["menu"])
    group_weights = request["group_weights"]
    agg_type = request["agg_type"]
    # gurobipy.GurobiError deliberately propagates uncaught: main()'s outer
    # handler turns it into {"ok": false, "error_type": "GurobiError", ...},
    # which the caller (cases.py) maps to a typed "gurobi_license_size"
    # exclusion (spec section 1) rather than a silent drop or a crash.
    opt_alloc, opt_alloc_log = compute_opt(
        menu,
        instance["budget"],
        instance["item_groups"],
        instance["item_to_effectiveness"],
        group_weights=group_weights,
        agg_type=agg_type,
        start_alloc=instance["start_alloc"],
    )
    is_feasible, invalid_reason, opt_cost, opt_utility = evaluate_alloc(
        menu=menu,
        alloc=opt_alloc,
        item_groups=instance["item_groups"],
        item_to_effectiveness=instance["item_to_effectiveness"],
        budget=instance["budget"],
        agg_type=agg_type,
        group_weights=group_weights,
    )
    return {
        "ok": True,
        "gold_optimum": {
            "opt_alloc": opt_alloc,
            "opt_cost": opt_cost,
            "opt_utility": opt_utility,
            "opt_value": opt_alloc_log.get("opt_value"),
            "is_feasible": is_feasible,
            "invalid_reason": invalid_reason,
        },
    }


def _op_procurement_evaluate(request: dict[str, Any]) -> dict[str, Any]:
    from econ_evals.experiments.procurement.opt_solver import evaluate_alloc

    instance = request["instance"]
    menu = _menu_from_dict(instance["menu"])
    is_feasible, invalid_reason, cost, utility = evaluate_alloc(
        menu=menu,
        alloc=request["alloc"],
        item_groups=instance["item_groups"],
        item_to_effectiveness=instance["item_to_effectiveness"],
        budget=instance["budget"],
        agg_type=request["agg_type"],
        group_weights=request["group_weights"],
    )
    return {
        "ok": True,
        "is_feasible": is_feasible,
        "invalid_reason": invalid_reason,
        "cost": cost,
        "utility": utility,
    }


def _op_generate_scheduling(request: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    from econ_evals.experiments.scheduling.generate_preferences import (
        generate_preferences,
    )

    num_workers = request["num_workers"]
    worker_ids = [f"W{i}" for i in range(1, num_workers + 1)]
    task_ids = [f"T{i}" for i in range(1, num_workers + 1)]
    my_random = np.random.RandomState(request["seed"])
    worker_prefs, task_prefs = generate_preferences(
        worker_ids=worker_ids,
        task_ids=task_ids,
        my_random=my_random,
        score_gap_worker=request["score_gap_worker"],
        score_gap_task=request["score_gap_task"],
    )
    return {
        "ok": True,
        "instance": {
            "worker_ids": worker_ids,
            "task_ids": task_ids,
            "worker_prefs": worker_prefs,
            "task_prefs": task_prefs,
        },
    }


def _op_scheduling_validate(request: dict[str, Any]) -> dict[str, Any]:
    from econ_evals.experiments.scheduling.stable_matching_environment import (
        is_valid_matching,
    )

    valid, reason = is_valid_matching(
        request["matching"], request["worker_ids"], request["task_ids"]
    )
    return {"ok": True, "valid": valid, "reason": reason}


def _op_scheduling_blocking_pairs(request: dict[str, Any]) -> dict[str, Any]:
    from econ_evals.experiments.scheduling.stable_matching_environment import (
        get_blocking_pairs,
    )

    blocking_pairs = get_blocking_pairs(
        request["matching"], request["worker_prefs"], request["task_prefs"]
    )
    return {
        "ok": True,
        "blocking_pairs": [[worker, task] for worker, task in blocking_pairs],
    }


def _op_generate_pricing(request: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    from econ_evals.experiments.pricing.generate_instance import generate_instance

    seed = request["seed"]
    num_products = request["num_products"]
    product_ids = request["product_ids"]
    # One RandomState draws EVERYTHING below, in exactly the order upstream's
    # own run_pricing_batch.py draws it: starting_alphas, cost_list, a_list,
    # period_length, THEN generate_instance's own further draws. Never
    # reimplemented -- only re-sequenced, because upstream's own batch script
    # (not generate_instance alone) is what actually owns this draw order.
    my_random = np.random.RandomState(seed)
    starting_alphas = my_random.uniform(1, 10, size=num_products).tolist()
    cost_list = my_random.uniform(1, 2, size=num_products).tolist()
    a_list = my_random.uniform(2, 3, size=num_products).tolist()
    costs = dict(zip(product_ids, cost_list))
    a_tuple = tuple(a_list)
    period_length = int(my_random.randint(10, 20))

    args = generate_instance(
        num_attempts=request["num_attempts"],
        prompt_type="econevals_importer",
        seed=seed,
        model="econevals_importer",
        env_type=request["env_type"],
        num_products=num_products,
        noise_param=request["noise_param"],
        sigma=request["sigma"],
        mu=request["mu"],
        start_multiplier=request["start_multiplier"],
        group_idx_p=request["group_idx_p"],
        group_idx_cutoff_proportion=request["group_idx_cutoff_proportion"],
        product_ids=product_ids,
        costs=costs,
        a_tuple=a_tuple,
        starting_alphas=starting_alphas,
        period_length=period_length,
        my_random=my_random,
    )
    return {"ok": True, "instance": args.model_dump(mode="json")}


def _op_pricing_reference(request: dict[str, Any]) -> dict[str, Any]:
    from econ_evals.experiments.pricing.pricing_market_logic_multiproduct import (
        get_monopoly_prices,
        get_profits,
    )

    instance = request["instance"]
    product_ids = instance["product_ids"]
    c_tuple = tuple(instance["costs"][product_id] for product_id in product_ids)
    a_tuple = tuple(instance["a_tuple"])
    group_idxs = tuple(instance["group_idxs"])
    prices_by_period: list[list[float]] = []
    profits_by_period: list[list[float]] = []
    for alpha, multiplier in zip(instance["alpha_list"], instance["multiplier_list"]):
        alpha_tuple = tuple(alpha)
        prices = get_monopoly_prices(
            a0=instance["a0"],
            a=a_tuple,
            mu=instance["mu"],
            alpha=alpha_tuple,
            c=c_tuple,
            multiplier=multiplier,
            sigma=instance["sigma"],
            group_idxs=group_idxs,
        )
        profits = get_profits(
            p=tuple(prices),
            c=c_tuple,
            a0=instance["a0"],
            a=a_tuple,
            mu=instance["mu"],
            alpha=alpha_tuple,
            multiplier=multiplier,
            sigma=instance["sigma"],
            group_idxs=group_idxs,
        )
        prices_by_period.append(prices)
        profits_by_period.append(list(profits))
    return {
        "ok": True,
        "gold_optimum": {
            "prices_by_period": prices_by_period,
            "profits_by_period": profits_by_period,
        },
    }


def _op_pricing_profits(request: dict[str, Any]) -> dict[str, Any]:
    from econ_evals.experiments.pricing.pricing_market_logic_multiproduct import (
        get_profits,
    )

    instance = request["instance"]
    period = request["period"]
    product_ids = instance["product_ids"]
    prices = request["prices"]
    p_tuple = tuple(prices[product_id] for product_id in product_ids)
    c_tuple = tuple(instance["costs"][product_id] for product_id in product_ids)
    profits = get_profits(
        p=p_tuple,
        c=c_tuple,
        a0=instance["a0"],
        a=tuple(instance["a_tuple"]),
        mu=instance["mu"],
        alpha=tuple(instance["alpha_list"][period]),
        multiplier=instance["multiplier_list"][period],
        sigma=instance["sigma"],
        group_idxs=tuple(instance["group_idxs"]),
    )
    return {
        "ok": True,
        "profits": dict(zip(product_ids, profits)),
    }


def _op_runtime_info() -> dict[str, Any]:
    import econ_evals
    import gurobipy

    return {
        "ok": True,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "econ_evals_package_file": str(econ_evals.__file__),
        "gurobipy_version": str(getattr(gurobipy, "__version__", "")),
    }


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "generate_procurement":
        return _op_generate_procurement(request)
    if op == "procurement_reference":
        return _op_procurement_reference(request)
    if op == "procurement_evaluate":
        return _op_procurement_evaluate(request)
    if op == "generate_scheduling":
        return _op_generate_scheduling(request)
    if op == "scheduling_validate":
        return _op_scheduling_validate(request)
    if op == "scheduling_blocking_pairs":
        return _op_scheduling_blocking_pairs(request)
    if op == "generate_pricing":
        return _op_generate_pricing(request)
    if op == "pricing_reference":
        return _op_pricing_reference(request)
    if op == "pricing_profits":
        return _op_pricing_profits(request)
    if op == "runtime_info":
        return _op_runtime_info()
    return {"ok": False, "error_type": "bad_request", "message": f"unknown op: {op!r}"}


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
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
