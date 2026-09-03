"""Run a GPT-OSS add-on linked to the public data-center terms panel."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development.objective_openrouter import (
    CLIENT_IMPLEMENTATION_ID,
    ParameterCompatibleOpenRouterClient,
)

from .campaign import _atomic_write, _call_usage, _read_sealed, _route, _sealed, _sha256
from .public_campaign import (
    DEFAULT_CONTRACT_PATH as BRIDGE_CONTRACT_PATH,
    _cases_by_slug,
    _group_summary,
    _setup as _bridge_setup,
    load_contract as load_bridge_contract,
    run_provider_free_gate as run_bridge_provider_free_gate,
)
from .public_cases import PACK_ID, public_pack_sha256
from .runner import (
    finalize_datacenter_terms_execution,
    finalize_datacenter_terms_failure,
    replay_datacenter_terms_receipt,
    run_openrouter,
)


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_terms_public_gptoss_contract/0.1"
CAMPAIGN_ID = "datacenter_development_terms_public_gptoss_v1"
MODEL_ID = "gptoss120b_coreweave"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
BRIDGE_PUBLICATION_ROOT = (
    REPOSITORY_ROOT / "evidence" / "datacenter_development_terms_public_v1"
)


def _bridge_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = load_bridge_contract(BRIDGE_CONTRACT_PATH)
    manifest = _read_sealed(BRIDGE_PUBLICATION_ROOT / "publication_manifest.json")
    summary = _read_sealed(BRIDGE_PUBLICATION_ROOT / "reports" / "summary.json")
    return contract, manifest, summary


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "pack_id": PACK_ID,
        "pack_sha256": public_pack_sha256(),
        "claim_status": (
            "public_source_gptoss_addon_exploratory_five_filing_clusters"
        ),
    }
    if not isinstance(contract, dict) or any(
        contract.get(key) != value for key, value in frozen.items()
    ):
        raise ValueError("public GPT-OSS campaign identity differs")
    if set(contract) != {
        *frozen,
        "route_catalog_snapshot",
        "bridge",
        "case_slugs",
        "inference_seeds",
        "model",
        "execution",
        "analysis",
    }:
        raise ValueError("public GPT-OSS campaign fields differ")

    snapshot = contract["route_catalog_snapshot"]
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != {"verified_at", "source", "selection_rule"}
        or snapshot["source"]
        != "https://openrouter.ai/api/v1/models/openai/gpt-oss-120b/endpoints"
        or not str(snapshot["verified_at"]).endswith("Z")
    ):
        raise ValueError("public GPT-OSS route snapshot differs")

    cases = _cases_by_slug()
    if contract["case_slugs"] != sorted(cases) or len(cases) != 5:
        raise ValueError("public GPT-OSS case panel differs")
    if contract["inference_seeds"] != [314001, 314002, 314003]:
        raise ValueError("public GPT-OSS inference seeds differ")

    model = contract["model"]
    expected_model = {
        "model_id": MODEL_ID,
        "profile_id": "datacenter_terms_public_gptoss120b_coreweave_v1",
        "requested_model": "openai/gpt-oss-120b",
        "canonical_model": "openai/gpt-oss-120b",
        "provider": "CoreWeave",
        "quantization": "fp4",
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "reasoning_effort": "low",
        "temperature_supported": True,
        "pricing": {
            "input_per_million": 0.03,
            "cached_input_per_million": 0.03,
            "output_per_million": 0.17,
            "pricing_id": (
                "openrouter_2026-09-03_gptoss120b_coreweave_terms_public_v1"
            ),
        },
        "max_prompt_price_per_million": "0.03",
        "max_completion_price_per_million": "0.17",
    }
    if model != expected_model:
        raise ValueError("public GPT-OSS route differs")

    controls = contract["execution"]
    required_controls = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_output_tokens": 1400,
        "timeout_seconds": 180.0,
        "max_cost_usd_per_cell": 0.02,
        "campaign_max_cost_usd": 0.3,
        "concurrency": 1,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if controls != required_controls:
        raise ValueError("public GPT-OSS execution controls differ")
    if len(cases) * len(contract["inference_seeds"]) * 0.02 > 0.3:
        raise ValueError("public GPT-OSS campaign exceeds its cost ceiling")

    required_analysis = {
        "case_count": 5,
        "independent_cluster_count": 5,
        "resampling_unit": "public_filing_cluster",
        "paired_by_bridge": ["case_slug", "inference_seed"],
        "missingness": "report_separately_no_selective_retry",
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }
    if contract["analysis"] != required_analysis:
        raise ValueError("public GPT-OSS analysis contract differs")

    bridge_contract, bridge_manifest, bridge_summary = _bridge_artifacts()
    expected_bridge = {
        "campaign_id": bridge_contract["campaign_id"],
        "contract_sha256": _sha256(bridge_contract),
        "design_sha256": bridge_summary["source_design_sha256"],
        "live_summary_sha256": bridge_summary["source_summary_sha256"],
        "public_manifest_sha256": bridge_manifest["artifact_sha256"],
        "comparison_scope": (
            "same_case_hash_prompt_schema_harness_and_inference_seed_descriptive_only"
        ),
    }
    if contract["bridge"] != expected_bridge:
        raise ValueError("public GPT-OSS bridge artifacts differ")
    if bridge_summary["planned_cells"] != 30:
        raise ValueError("public GPT-OSS bridge panel cell set differs")
    return contract


def _panel_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {**dict(contract), "models": {MODEL_ID: contract["model"]}}


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    cases = _cases_by_slug()
    return tuple(
        {
            "cell_key": f"{slug}__{MODEL_ID}__seed_{seed}",
            "pair_key": f"{slug}__seed_{seed}",
            "case_slug": slug,
            "source_cluster_id": cases[slug].payload["public_case"][
                "independence_cluster_id"
            ],
            "model_id": MODEL_ID,
            "inference_seed": seed,
        }
        for slug in contract["case_slugs"]
        for seed in contract["inference_seeds"]
    )


def _setup(
    contract: Mapping[str, Any],
    cell: Mapping[str, Any],
    cases: Mapping[str, Any],
) -> Any:
    return _bridge_setup(_panel_contract(contract), cell, cases)


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = (
        "environment.py",
        "runner.py",
        "public_cases.py",
        "public_campaign.py",
        "public_gptoss_campaign.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    }


def _assert_bridge_setup(
    contract: Mapping[str, Any],
    cell: Mapping[str, Any],
    setup: Any,
) -> None:
    bridge_contract = load_bridge_contract(BRIDGE_CONTRACT_PATH)
    cases = _cases_by_slug()
    prior = _bridge_setup(
        bridge_contract,
        {**dict(cell), "model_id": "qwen3_235b_novita"},
        cases,
    )
    current_profile = setup.plan.agent_profiles[0]
    prior_profile = prior.plan.agent_profiles[0]
    if (
        setup.case.case_id != prior.case.case_id
        or setup.case.content_sha256 != prior.case.content_sha256
        or current_profile.prompt != prior_profile.prompt
        or current_profile.harness.id != prior_profile.harness.id
        or current_profile.harness.version != prior_profile.harness.version
        or current_profile.harness.config["output_schema"]
        != prior_profile.harness.config["output_schema"]
        or current_profile.sampling.seed != prior_profile.sampling.seed
        or current_profile.sampling.max_output_tokens
        != prior_profile.sampling.max_output_tokens
        or current_profile.budgets.timeout_seconds
        != prior_profile.budgets.timeout_seconds
        or current_profile.budgets.max_cost_usd != prior_profile.budgets.max_cost_usd
        or current_profile.retry_policy != prior_profile.retry_policy
    ):
        raise ValueError("public GPT-OSS setup is not bridge-compatible")


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    cases = _cases_by_slug()
    cells = []
    for cell in _cells(contract):
        setup = _setup(contract, cell, cases)
        _assert_bridge_setup(contract, cell, setup)
        plan_cell = setup.plan.cells[0]
        cells.append(
            {
                **cell,
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "cell_id": plan_cell.cell_id,
                "case_id": plan_cell.case_id,
                "case_sha256": plan_cell.case_sha256,
                "profile_id": setup.plan.agent_profiles[0].profile_id,
                "live_profile_count": 1,
                "declared_cell_max_cost_usd": 0.02,
            }
        )
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_gptoss_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": public_pack_sha256(),
            "bridge": contract["bridge"],
            "campaign_driver_sha256": hashes["public_gptoss_campaign.py"],
            "implementation_source_sha256s": hashes,
            "case_count": 5,
            "independent_cluster_count": 5,
            "planned_cells": len(cells),
            "worst_case_declared_cost_usd": len(cells) * 0.02,
            "campaign_max_cost_usd": 0.3,
            "cells": cells,
        }
    )


async def run_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path
) -> dict[str, Any]:
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    bridge_contract = load_bridge_contract(BRIDGE_CONTRACT_PATH)
    source = await run_bridge_provider_free_gate(
        bridge_contract,
        run_root=run_root / "inherited_source_gate",
    )
    if source["status"] != "passed" or len(source["cases"]) != 5:
        raise ValueError("public provider-free gate is not reusable")
    result = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_gptoss_provider_free_gate/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "mode": "reexecuted_same_pack_environment_scorer_and_cases",
            "source_campaign_id": contract["bridge"]["campaign_id"],
            "source_gate_sha256": source["artifact_sha256"],
            "case_count": 5,
        }
    )
    _atomic_write(path, result)
    return result


def run_profile_admission_gate(
    contract: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    run_root: Path,
) -> dict[str, Any]:
    path = run_root / "profile_admission" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    cases = _cases_by_slug()
    expected = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted = []
    for cell in _cells(contract):
        setup = _setup(contract, cell, cases)
        target = expected[cell["cell_key"]]
        if (
            setup.plan.plan_sha256 != target["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != target["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError(f"GPT-OSS profile admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_gptoss_profile_gate/0.1",
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
    cell_root = run_root / "live" / str(cell["cell_key"])
    path = cell_root / "result.json"
    if path.exists():
        result = _read_sealed(path)
        if result["run_plan_sha256"] != cell["run_plan_sha256"]:
            raise ValueError(f"resumed result drift for {cell['cell_key']}")
        return result
    if cell_root.exists():
        raise ValueError(f"refusing to replace incomplete GPT-OSS cell {cell['cell_key']}")

    cases = _cases_by_slug()
    case = cases[str(cell["case_slug"])]
    setup = _setup(contract, cell, cases)
    route = _route(contract["model"])
    controls = contract["execution"]
    started = time.perf_counter()
    try:
        returned_setup, execution = await run_openrouter(
            route,
            evidence_root=cell_root / "evidence",
            seed=int(cell["inference_seed"]),
            case_slug=str(cell["case_slug"]),
            case_manifest=case,
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
            provider=provider,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("GPT-OSS live setup differs from sealed design")
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_public_gptoss_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
                "status": "completed",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": _call_usage(execution),
                "metrics": dict(execution.episode_result.outcome),
                "parsed_output": execution.episode_result.terminal.get("report"),
                "failure": None,
            }
        )
    except Exception as error:
        receipt = finalize_datacenter_terms_failure(
            setup=setup,
            cell_id=setup.plan.cells[0].cell_id,
            evidence_root=cell_root / "evidence",
            error=error,
        )
        verify_evaluation_receipt(receipt)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_public_gptoss_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
                "status": "operational_failure",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": False,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": None,
                "metrics": None,
                "parsed_output": None,
                "failure": {
                    "failure_class": receipt.failure.failure_class,
                    "failure_condition": receipt.failure.condition,
                    "error_type": type(error).__name__,
                },
            }
        )
    _atomic_write(path, result)
    return result


def _bridge_source_rows() -> tuple[dict[str, Any], ...]:
    path = BRIDGE_PUBLICATION_ROOT / "trajectories" / "sanitized.jsonl"
    rows = tuple(json.loads(line) for line in path.read_text().splitlines() if line)
    if len(rows) != 30:
        raise ValueError("public GPT-OSS bridge trajectory set differs")
    return rows


def _bridge_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prior = {
        (row["case_slug"], row["inference_seed"], row["model_id"]): row
        for row in _bridge_source_rows()
    }
    current = {(row["case_slug"], row["inference_seed"]): row for row in rows}
    result = []
    for case_slug, seed in sorted(current):
        addon = current[(case_slug, seed)]
        models = {
            model_id: prior[(case_slug, seed, model_id)]
            for model_id in ("mistral32_deepinfra", "qwen3_235b_novita")
        }
        usable = addon["status"] == "completed" and all(
            row["status"] == "completed" for row in models.values()
        )
        result.append(
            {
                "pair_key": f"{case_slug}__seed_{seed}",
                "case_slug": case_slug,
                "source_cluster_id": addon["source_cluster_id"],
                "inference_seed": seed,
                "bridge_reportable": usable,
                "scores": (
                    {
                        "mistral32_deepinfra": models["mistral32_deepinfra"][
                            "metrics"
                        ]["score"],
                        "qwen3_235b_novita": models["qwen3_235b_novita"]["metrics"][
                            "score"
                        ],
                        MODEL_ID: addon["metrics"]["score"],
                    }
                    if usable
                    else None
                ),
                "hard_gate_pass": (
                    {
                        "mistral32_deepinfra": models["mistral32_deepinfra"][
                            "metrics"
                        ]["hard_gate_pass"],
                        "qwen3_235b_novita": models["qwen3_235b_novita"]["metrics"][
                            "hard_gate_pass"
                        ],
                        MODEL_ID: addon["metrics"]["hard_gate_pass"],
                    }
                    if usable
                    else None
                ),
            }
        )
    return result


def _campaign_summary(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    bridge = _bridge_rows(rows)
    cost = math.fsum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_gptoss_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "claim_status": contract["claim_status"],
            "bridge": contract["bridge"],
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(row["inclusion_status"] == "included" for row in rows),
            "operational_failure_cells": len(failures),
            "failure_fraction": len(failures) / len(rows),
            "failure_conditions": sorted(
                row["failure"]["failure_condition"] for row in failures
            ),
            "reported_cost_usd": cost,
            "provider_cost_complete": not failures,
            "cost_qualifier": "exact" if not failures else "lower_bound",
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "within_declared_campaign_cost_ceiling": (
                cost <= contract["execution"]["campaign_max_cost_usd"]
            ),
            "all_completed_receipts_replayed": all(
                row["replay_verified"] for row in completed
            ),
            "case_count": 5,
            "independent_cluster_count": 5,
            "model_summary": _group_summary("model_id", MODEL_ID, rows),
            "case_summaries": [
                _group_summary("case_slug", slug, rows)
                for slug in contract["case_slugs"]
            ],
            "bridge_rows": bridge,
            "bridge_reportable_count": sum(row["bridge_reportable"] for row in bridge),
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "project_generalization_allowed": False,
            "population_causal_effect_allowed": False,
        }
    )


async def run_live_panel(
    contract: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    run_root: Path,
    provider_factory: Callable[[], Any] = ParameterCompatibleOpenRouterClient,
) -> dict[str, Any]:
    path = run_root / "live" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    provider_free = _read_sealed(run_root / "provider_free_validation" / "summary.json")
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    if provider_free["status"] != "passed" or admission["status"] != "passed":
        raise ValueError("public GPT-OSS gates must pass before live dispatch")
    provider = provider_factory()
    rows = []
    for cell in design["cells"]:
        rows.append(
            await _run_live_cell(
                contract,
                cell,
                run_root=run_root,
                provider=provider,
            )
        )
    summary = _campaign_summary(contract, rows)
    _atomic_write(path, summary)
    return summary


async def run_campaign(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = ParameterCompatibleOpenRouterClient,
) -> dict[str, Any]:
    if stop_after not in {"design", "provider_free", "profile_admission", "live"}:
        raise ValueError("unsupported public GPT-OSS campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public GPT-OSS design differs")
    else:
        design = build_design(contract)
        _atomic_write(design_path, design)
    if stop_after == "design":
        return design
    provider_free = await run_provider_free_gate(contract, run_root=root)
    if stop_after == "provider_free":
        return provider_free
    admission = run_profile_admission_gate(contract, design=design, run_root=root)
    if stop_after == "profile_admission":
        return admission
    return await run_live_panel(
        contract,
        design=design,
        run_root=root,
        provider_factory=provider_factory,
    )


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
    "CONTRACT_SCHEMA_VERSION",
    "DEFAULT_CONTRACT_PATH",
    "DEFAULT_RUN_ROOT",
    "MODEL_ID",
    "build_design",
    "load_contract",
    "main",
    "run_campaign",
    "run_live_panel",
]
