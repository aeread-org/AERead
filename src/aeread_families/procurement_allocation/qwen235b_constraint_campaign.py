"""Matched constraint-ledger treatment for Qwen3 235B procurement allocation."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.task.execution import OpenRouterChatClient
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

from .qwen_case_campaign import (
    CandidateCaseCampaignSpec,
    build_plan as build_candidate_plan,
    run_admission_canary as run_candidate_admission_canary,
    run_campaign as run_candidate_campaign,
)
from .qwen235b_google_case_campaign import QWEN235B_GOOGLE_CANDIDATE
from .strategy_scaffold import STRATEGY_PROMPT


CAMPAIGN_ID = "procurement_allocation_qwen3_235b_google_constraint_ledger_v1"
PROMPT_ID = "procurement_allocation_constraint_ledger_v1"
TREATMENT_ID = "public_evidence_constraint_ledger_v1"
PARENT_EVIDENCE_PATH = (
    "evidence/procurement_allocation_qwen3_235b_google_case_variance_v1/"
    "publication_manifest.json"
)
PARENT_EVIDENCE_FILE_SHA256 = (
    "97e02bec840f75506995bfb0cccf891ce1c1e597451955dc7f50aa08bb86ebe4"
)
MAX_TRAJECTORY_COST_USD = 0.03
MAX_CANARY_COST_USD = 0.03
HARD_TOTAL_COST_CEILING_USD = 0.57
SPEC = CandidateCaseCampaignSpec(
    campaign_id=CAMPAIGN_ID,
    candidate=QWEN235B_GOOGLE_CANDIDATE,
    lineage={
        "selection_status": "adaptive_constraint_treatment",
        "selection_basis": (
            "the qualified unscaffolded Google route achieved 3/18 feasible "
            "allocations but retained capacity, minimum-service, malformed-action, "
            "and interaction-budget failures; test an explicit public-evidence "
            "feasibility procedure before any broad factorial"
        ),
        "parent_evidence_path": PARENT_EVIDENCE_PATH,
        "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
        "scientific_contract": (
            "checkpoint, provider route, quantization declaration, cases, seeds, "
            "harness, action schema, action budget, objective verifier, checkpointing, "
            "retries, and eligibility match the unscaffolded control; only the public "
            "buyer decision procedure changes"
        ),
    },
    max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
    max_canary_cost_usd=MAX_CANARY_COST_USD,
    hard_total_cost_ceiling_usd=HARD_TOTAL_COST_CEILING_USD,
    claim_scope=(
        "adaptive matched prompt-treatment diagnostic on six curated procurement "
        "worlds; seeds are within-world replicates and this is not a population-level "
        "mechanism claim"
    ),
    prompt=STRATEGY_PROMPT,
    prompt_id=PROMPT_ID,
    treatment_id=TREATMENT_ID,
)


def build_plan() -> dict[str, Any]:
    return build_candidate_plan(spec=SPEC)


async def run_admission_canary(
    *,
    path: Path,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    return await run_candidate_admission_canary(
        path=path, spec=SPEC, provider_factory=provider_factory
    )


async def run_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = HARD_TOTAL_COST_CEILING_USD,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    return await run_candidate_campaign(
        run_root=run_root,
        max_spend_usd=max_spend_usd,
        resume=resume,
        spec=SPEC,
        provider_factory=provider_factory,
        preflight_fn=preflight_fn,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument(
        "--max-spend-usd", type=float, default=HARD_TOTAL_COST_CEILING_USD
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.execute:
        print(json.dumps(build_plan(), indent=2, sort_keys=True))
        return 0
    status = asyncio.run(
        run_campaign(
            run_root=arguments.run_root,
            max_spend_usd=arguments.max_spend_usd,
            resume=arguments.resume,
        )
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    if status["summary"]["execution_qualified"]:
        return 0
    if status["summary"]["operational_failure_count"]:
        return 2
    if not status["summary"]["failure_free_checkpoint"]:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "HARD_TOTAL_COST_CEILING_USD",
    "PROMPT_ID",
    "SPEC",
    "TREATMENT_ID",
    "build_plan",
    "run_admission_canary",
    "run_campaign",
]
