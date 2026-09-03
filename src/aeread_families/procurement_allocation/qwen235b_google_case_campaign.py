"""Provider-route diagnostic for Qwen3 235B-A22B procurement actions."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.task.execution import OpenRouterChatClient
from aeread_families.procurement_grounding.bakeoff import (
    OPEN_WEIGHT_CANDIDATES,
    preflight_candidate,
)

from .qwen_case_campaign import (
    CandidateCaseCampaignSpec,
    build_plan as build_candidate_plan,
    run_admission_canary as run_candidate_admission_canary,
    run_campaign as run_candidate_campaign,
)


CAMPAIGN_ID = "procurement_allocation_qwen3_235b_google_case_variance_v1"
QWEN235B_GOOGLE_CANDIDATE = next(
    candidate
    for candidate in OPEN_WEIGHT_CANDIDATES
    if candidate.candidate_id == "qwen3_235b_a22b_instruct_2507_google"
)
PARENT_EVIDENCE_PATH = (
    "evidence/procurement_allocation_qwen3_235b_atlascloud_case_variance_v1/"
    "publication_manifest.json"
)
PARENT_EVIDENCE_FILE_SHA256 = (
    "56a5f027a99cbc418bfd035bb94fec458f6ac24fb31005d203021815e61d3ad2"
)
MAX_TRAJECTORY_COST_USD = 0.03
MAX_CANARY_COST_USD = 0.03
HARD_TOTAL_COST_CEILING_USD = 0.57
SPEC = CandidateCaseCampaignSpec(
    campaign_id=CAMPAIGN_ID,
    candidate=QWEN235B_GOOGLE_CANDIDATE,
    lineage={
        "selection_status": "adaptive_provider_route_diagnostic",
        "selection_basis": (
            "the AtlasCloud route completed all 18 matched rows but returned a "
            "semantically plausible action in the wrong top-level envelope every "
            "time; change only the provider route to test structured-output handling"
        ),
        "parent_evidence_path": PARENT_EVIDENCE_PATH,
        "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
        "scientific_contract": (
            "checkpoint, cases, seeds, prompt, harness, action budget, objective "
            "verifier, checkpointing, retries, and eligibility match the AtlasCloud "
            "panel; only the pinned provider route and its declared quantization change"
        ),
    },
    max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
    max_canary_cost_usd=MAX_CANARY_COST_USD,
    hard_total_cost_ceiling_usd=HARD_TOTAL_COST_CEILING_USD,
    claim_scope=(
        "provider-route structured-output diagnostic on six curated procurement "
        "worlds; seeds are within-world replicates and results must not be pooled "
        "into a model-only estimate"
    ),
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
    "QWEN235B_GOOGLE_CANDIDATE",
    "SPEC",
    "build_plan",
    "run_admission_canary",
    "run_campaign",
]
