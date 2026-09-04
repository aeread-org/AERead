"""Frozen paired campaign for counteroffer acceptance affordance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from .affordance_environment import CONDITIONS
from .affordance_runner import (
    build_affordance_setup,
    finalize_affordance_execution,
    finalize_affordance_failure,
    load_affordance_case,
    replay_affordance_receipt,
    run_affordance_offline,
    run_affordance_openrouter,
)
from .objective_campaign import (
    _atomic_write,
    _call_usage,
    _plain,
    _read_sealed,
    _route,
    _score_projection,
    _sealed,
    _sha256,
)
from .objective_openrouter import (
    CLIENT_IMPLEMENTATION_ID,
    ParameterCompatibleOpenRouterClient,
)
from .objective_runner import OBJECTIVE_CASE_PATH
from .stack_runner import load_stack_case


CAMPAIGN_ID = "datacenter_counteroffer_affordance_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = __import__("json").loads(Path(path).read_text(encoding="utf-8"))
    frozen = {
        "schema_version": "aeread.datacenter_counteroffer_affordance_campaign_contract/0.1",
        "campaign_id": CAMPAIGN_ID,
        "family_id": CAMPAIGN_ID,
        "family_version": "1.0.0",
        "claim_status": "single_curated_project_paired_action_affordance_diagnostic_only",
    }
    if not isinstance(contract, dict) or any(
        contract.get(key) != value for key, value in frozen.items()
    ):
        raise ValueError("affordance identity or claim boundary differs")
    if tuple(contract["analysis"]["condition_order"]) != CONDITIONS or set(
        contract["conditions"]
    ) != set(CONDITIONS):
        raise ValueError("affordance condition panel differs")
    for condition in CONDITIONS:
        if set(contract["conditions"][condition]) != {
            "case_id",
            "expected_case_sha256",
        }:
            raise ValueError(f"{condition}: case pin fields differ")
    seeds = contract["inference_seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) != 5
        or len(set(seeds)) != 5
        or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in seeds
        )
    ):
        raise ValueError("affordance campaign requires five unique seeds")
    expected = {
        "mistral32_deepinfra": (
            "mistralai/mistral-small-3.2-24b-instruct",
            "mistralai/mistral-small-3.2-24b-instruct-2506",
            "DeepInfra",
        ),
        "qwen3_235b_novita": (
            "qwen/qwen3-235b-a22b-2507",
            "qwen/qwen3-235b-a22b-07-25",
            "Novita",
        ),
    }
    if set(contract["models"]) != set(expected):
        raise ValueError("affordance model panel differs")
    for model_id, route in expected.items():
        model = contract["models"][model_id]
        if (
            (model["requested_model"], model["canonical_model"], model["provider"])
            != route
            or model["access_class"] != "open_source"
            or model["license_id"] != "Apache-2.0"
            or model["reasoning_effort"] is not None
        ):
            raise ValueError(f"{model_id}: route differs")
    controls = contract["execution"]
    required = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if any(controls.get(key) != value for key, value in required.items()):
        raise ValueError("affordance execution controls differ")
    worst = (
        len(CONDITIONS)
        * len(seeds)
        * len(expected)
        * float(controls["max_cost_usd_per_live_profile"])
    )
    if worst > float(controls["campaign_max_cost_usd"]):
        raise ValueError("affordance campaign exceeds cost ceiling")
    analysis = contract["analysis"]
    if (
        analysis.get("independent_project_clusters") != 1
        or analysis.get("missingness")
        != "report_separately_and_require_both_conditions_for_pair"
        or analysis.get("primary_estimand") != "counteroffer_adoption_rate"
        or analysis.get("mechanism_outcome") != "reference_acceptance_used"
        or analysis.get("paired_transition_counts") is not True
    ):
        raise ValueError("affordance analysis differs")
    for field in (
        "winner_claim_allowed",
        "population_generalization_allowed",
        "population_causal_effect_allowed",
    ):
        if analysis.get(field) is not False:
            raise ValueError(f"analysis.{field} must be false")
    return contract


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"{condition}__{model_id}__seed_{seed}",
            "condition": condition,
            "model_id": model_id,
            "inference_seed": seed,
            "pair_key": f"{model_id}__seed_{seed}",
        }
        for seed in contract["inference_seeds"]
        for model_id in sorted(contract["models"])
        for condition in CONDITIONS
    )


def _setup(contract: Mapping[str, Any], cell: Mapping[str, Any]):
    controls = contract["execution"]
    return build_affordance_setup(
        str(cell["condition"]),
        route=_route(contract["models"][cell["model_id"]]),
        seed=int(cell["inference_seed"]),
        max_output_tokens=int(controls["max_output_tokens_per_action"]),
        timeout_seconds=float(controls["timeout_seconds_per_action"]),
        max_cost_usd=float(controls["max_cost_usd_per_live_profile"]),
    )


def _implementation_hashes() -> dict[str, str]:
    names = (
        "contracts.py",
        "stack_environment.py",
        "stack_runner.py",
        "adoption_environment.py",
        "adoption_measurement.py",
        "adoption_runner.py",
        "adoption_environment_v2.py",
        "adoption_runner_v2.py",
        "adoption_environment_v3.py",
        "adoption_runner_v3.py",
        "affordance_environment.py",
        "affordance_runner.py",
        "affordance_campaign.py",
    )
    root = Path(__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    }


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    base = load_stack_case("v2", OBJECTIVE_CASE_PATH)
    if (
        base.case_id != contract["base_case"]["case_id"]
        or base.content_sha256 != contract["base_case"]["expected_case_sha256"]
    ):
        raise ValueError("affordance base case differs")
    for condition, spec in contract["conditions"].items():
        case = load_affordance_case(condition)
        if (
            case.case_id != spec["case_id"]
            or case.content_sha256 != spec["expected_case_sha256"]
        ):
            raise ValueError(f"{condition}: case differs")
    cells = []
    per_cell = float(contract["execution"]["max_cost_usd_per_live_profile"])
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        plan_cell = setup.plan.cells[0]
        if (
            sum(
                profile.model.provider == "openrouter"
                for profile in setup.plan.agent_profiles
            )
            != 1
            or setup.plan.evaluation_blocks[0].kind != "controlled"
        ):
            raise ValueError("affordance topology differs")
        cells.append(
            {
                **cell,
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "cell_id": plan_cell.cell_id,
                "case_id": plan_cell.case_id,
                "case_sha256": plan_cell.case_sha256,
                "evaluation_block_kind": "controlled",
                "live_profile_count": 1,
                "declared_cell_max_cost_usd": per_cell,
            }
        )
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_affordance_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashes["affordance_campaign.py"],
            "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "base_case_id": base.case_id,
            "base_case_sha256": base.content_sha256,
            "independent_project_clusters": 1,
            "planned_cells": len(cells),
            "paired_seed_count": len(contract["inference_seeds"]),
            "planned_pair_count": len(contract["inference_seeds"])
            * len(contract["models"]),
            "worst_case_declared_cost_usd": sum(
                cell["declared_cell_max_cost_usd"] for cell in cells
            ),
            "campaign_max_cost_usd": contract["execution"][
                "campaign_max_cost_usd"
            ],
            "cells": cells,
        }
    )


async def run_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path
) -> dict[str, Any]:
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    rows = []
    for condition in CONDITIONS:
        evidence = run_root / "provider_free_validation" / condition / "evidence"
        setup, execution = await run_affordance_offline(
            condition, evidence_root=evidence
        )
        receipt = finalize_affordance_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_affordance_receipt(
            setup=setup, receipt=receipt, evidence_root=evidence
        )
        outcome = execution.episode_result.outcome
        score = next(
            item
            for item in receipt.scores
            if item.leaf.leaf_id == "counteroffer_adoption_rate"
        )
        expected_reference_count = int(condition == "accept_by_reference")
        passed = (
            score.primary.value == 1
            and outcome["affordance_condition"] == condition
            and outcome["counteroffer_opportunity_count"] == 1
            and outcome["reference_acceptance_count"]
            == expected_reference_count
            and replayed == receipt
        )
        rows.append(
            {
                "condition": condition,
                "status": "passed" if passed else "failed",
                "case_sha256": setup.case.content_sha256,
                "primary_score": score.primary.value,
                "reference_acceptance_count": outcome[
                    "reference_acceptance_count"
                ],
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
            }
        )
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_affordance_provider_free_gate/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": (
                "passed" if all(row["status"] == "passed" for row in rows) else "failed"
            ),
            "conditions": rows,
        }
    )
    _atomic_write(path, result)
    return result


def run_profile_admission_gate(
    contract: Mapping[str, Any], *, design: Mapping[str, Any], run_root: Path
) -> dict[str, Any]:
    path = run_root / "profile_admission" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    expected = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        target = expected[cell["cell_key"]]
        if (
            setup.plan.plan_sha256 != target["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != target["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError("affordance profile admission drift")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_affordance_profile_gate/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "admitted_cells": admitted,
        }
    )
    _atomic_write(path, result)
    return result


async def _run_live_cell(
    contract: Mapping[str, Any],
    cell: Mapping[str, Any],
    *,
    run_root: Path,
    provider: Any,
) -> dict[str, Any]:
    root = run_root / "live" / str(cell["cell_key"])
    path = root / "result.json"
    if path.exists():
        return _read_sealed(path)
    if root.exists():
        raise ValueError(
            f"refusing to replace incomplete affordance cell {cell['cell_key']}"
        )
    setup = _setup(contract, cell)
    controls = contract["execution"]
    started = time.perf_counter()
    try:
        _, execution = await run_affordance_openrouter(
            str(cell["condition"]),
            _route(contract["models"][cell["model_id"]]),
            evidence_root=root / "evidence",
            seed=int(cell["inference_seed"]),
            max_output_tokens=int(controls["max_output_tokens_per_action"]),
            timeout_seconds=float(controls["timeout_seconds_per_action"]),
            max_cost_usd=float(controls["max_cost_usd_per_live_profile"]),
            provider=provider,
        )
        receipt = finalize_affordance_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_affordance_receipt(
            setup=setup, receipt=receipt, evidence_root=root / "evidence"
        )
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_counteroffer_affordance_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
                "status": "completed",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": _call_usage(execution),
                "outcome": _plain(execution.episode_result.outcome),
                "scores": _score_projection(receipt),
                "failure": None,
            }
        )
    except Exception as error:
        receipt = finalize_affordance_failure(
            setup=setup,
            cell_id=setup.plan.cells[0].cell_id,
            evidence_root=root / "evidence",
            error=error,
        )
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_counteroffer_affordance_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
                "status": "operational_failure",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": False,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": None,
                "outcome": None,
                "scores": None,
                "failure": {
                    "failure_class": receipt.failure.failure_class,
                    "failure_condition": receipt.failure.condition,
                    "error_type": type(error).__name__,
                },
            }
        )
    _atomic_write(path, result)
    return result


def _group_summary(
    key: str, value: str, rows: list[Mapping[str, Any]]
) -> dict[str, Any]:
    selected = [row for row in rows if row[key] == value]
    completed = [row for row in selected if row["status"] == "completed"]
    included = [row for row in completed if row["inclusion_status"] == "included"]

    def mean(leaf: str) -> float | None:
        values = [float(row["scores"][leaf]["value"]) for row in included]
        return statistics.fmean(values) if values else None

    return {
        key: value,
        "planned_cells": len(selected),
        "completed_cells": len(completed),
        "included_cells": len(included),
        "operational_failure_cells": len(selected) - len(completed),
        "completion_rate": len(completed) / len(selected),
        "mean_counteroffer_adoption_rate": mean("counteroffer_adoption_rate"),
        "mean_prefix_completion": mean("prefix_completion"),
        "mean_temporal_compliance": mean("negotiation_temporal_compliance"),
        "reference_acceptance_count": sum(
            int(row["outcome"]["reference_acceptance_count"]) for row in included
        ),
        "termination_counts": dict(
            sorted(
                Counter(
                    str(row["outcome"]["termination_reason"]) for row in included
                ).items()
            )
        ),
        "reported_cost_usd": sum(
            float(row["usage"]["reported_cost_usd"])
            for row in completed
            if row["usage"] is not None
        ),
    }


def _paired_transitions(
    contract: Mapping[str, Any], rows: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    indexed = {
        (row["model_id"], row["inference_seed"], row["condition"]): row
        for row in rows
    }
    result = []
    for model_id in sorted(contract["models"]):
        counts = Counter()
        usable = 0
        for seed in contract["inference_seeds"]:
            baseline = indexed[(model_id, seed, "reemit_package")]
            treatment = indexed[(model_id, seed, "accept_by_reference")]
            if any(
                row["status"] != "completed"
                or row["inclusion_status"] != "included"
                for row in (baseline, treatment)
            ):
                counts["missing_pair"] += 1
                continue
            baseline_score = int(
                float(
                    baseline["scores"]["counteroffer_adoption_rate"]["value"]
                )
                == 1
            )
            treatment_score = int(
                float(
                    treatment["scores"]["counteroffer_adoption_rate"]["value"]
                )
                == 1
            )
            counts[f"{baseline_score}_to_{treatment_score}"] += 1
            usable += 1
        result.append(
            {
                "model_id": model_id,
                "planned_pairs": len(contract["inference_seeds"]),
                "usable_pairs": usable,
                "missing_pairs": counts["missing_pair"],
                "neither_adopted": counts["0_to_0"],
                "reference_only_adopted": counts["0_to_1"],
                "reemit_only_adopted": counts["1_to_0"],
                "both_adopted": counts["1_to_1"],
            }
        )
    return result


def summarize(
    contract: Mapping[str, Any],
    design: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    operational = [row for row in rows if row["status"] != "completed"]
    cost = sum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_affordance_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "design_sha256": design["artifact_sha256"],
            "campaign_driver_sha256": design["campaign_driver_sha256"],
            "implementation_source_sha256s": design[
                "implementation_source_sha256s"
            ],
            "claim_status": contract["claim_status"],
            "independent_project_clusters": 1,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(
                row["inclusion_status"] == "included" for row in completed
            ),
            "operational_failure_cells": len(operational),
            "failure_conditions": [
                row["failure"]["failure_condition"] for row in operational
            ],
            "reported_cost_usd": cost,
            "cost_qualifier": "exact" if not operational else "lower_bound",
            "provider_cost_complete": not operational,
            "within_declared_campaign_cost_ceiling": cost
            <= float(contract["execution"]["campaign_max_cost_usd"]),
            "condition_summaries": [
                _group_summary("condition", condition, rows)
                for condition in CONDITIONS
            ],
            "model_summaries": [
                _group_summary("model_id", model_id, rows)
                for model_id in sorted(contract["models"])
            ],
            "paired_transitions": _paired_transitions(contract, rows),
            "winner_claim_allowed": False,
            "population_generalization_allowed": False,
            "population_causal_effect_allowed": False,
        }
    )


async def run_campaign(
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    run_root: Path = DEFAULT_RUN_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = ParameterCompatibleOpenRouterClient,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    root = Path(run_root)
    design = build_design(contract)
    _atomic_write(root / "design.json", design)
    if stop_after == "design":
        return design
    gate = await run_provider_free_gate(contract, run_root=root)
    if gate["status"] != "passed":
        raise ValueError("affordance provider-free gate failed")
    if stop_after == "provider_free":
        return gate
    admission = run_profile_admission_gate(contract, design=design, run_root=root)
    if stop_after == "profile_admission":
        return admission
    semaphore = asyncio.Semaphore(int(contract["execution"]["concurrency"]))
    locks = {
        str(model["provider"]): asyncio.Semaphore(1)
        for model in contract["models"].values()
    }

    async def execute(cell: Mapping[str, Any]) -> dict[str, Any]:
        provider_name = str(contract["models"][cell["model_id"]]["provider"])
        async with semaphore, locks[provider_name]:
            return await _run_live_cell(
                contract,
                cell,
                run_root=root,
                provider=provider_factory(),
            )

    rows = list(await asyncio.gather(*(execute(cell) for cell in design["cells"])))
    summary = summarize(contract, design, rows)
    _atomic_write(root / "live" / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument(
        "--stop-after",
        choices=("design", "provider_free", "profile_admission", "live"),
        default="live",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(
        run_campaign(
            contract_path=args.contract,
            run_root=args.run_root,
            stop_after=args.stop_after,
        )
    )
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "DEFAULT_CONTRACT_PATH",
    "DEFAULT_RUN_ROOT",
    "build_design",
    "load_contract",
    "run_campaign",
    "summarize",
]
