"""Adaptive action-contract repair for the Qwen3 235B constraint treatment."""

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


CAMPAIGN_ID = "procurement_allocation_qwen3_235b_google_constraint_ledger_v2"
PROMPT_ID = "procurement_allocation_constraint_ledger_v2"
TREATMENT_ID = "public_evidence_constraint_ledger_v2_message_contract"
MESSAGE_CONTRACT = """

Action-field contract: for `inquire`, `request_quote`, `request_sample`, and
`counter_offer`, always provide a non-empty `message` string describing the
confirmation or proposal. Never set a field required by the selected action to null.
Fields belonging only to other actions may remain null in the provider's strict
superset schema. For `submit_award`, provide non-empty `award_lines`; for `defer`,
provide a non-empty `reason`.
"""
V2_PROMPT = STRATEGY_PROMPT + MESSAGE_CONTRACT
PARENT_EVIDENCE_PATH = (
    "evidence/procurement_allocation_qwen3_235b_google_constraint_ledger_v1/"
    "publication_manifest.json"
)
PARENT_EVIDENCE_FILE_SHA256 = (
    "cb1167e752104a1cbfe314730ad684f56362f7dd21da9426e4e5033177b01e78"
)
MAX_TRAJECTORY_COST_USD = 0.03
MAX_CANARY_COST_USD = 0.03
HARD_TOTAL_COST_CEILING_USD = 0.57
SPEC = CandidateCaseCampaignSpec(
    campaign_id=CAMPAIGN_ID,
    candidate=QWEN235B_GOOGLE_CANDIDATE,
    lineage={
        "selection_status": "adaptive_action_contract_repair",
        "selection_basis": (
            "constraint-ledger V1 produced 13 malformed actions because the selected "
            "quote or sample action carried a null required message; append only an "
            "explicit non-empty selected-action field reminder"
        ),
        "parent_evidence_path": PARENT_EVIDENCE_PATH,
        "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
        "scientific_contract": (
            "checkpoint, provider route, quantization declaration, cases, seeds, "
            "harness, action schema, action budget, objective verifier, decision "
            "procedure, checkpointing, retries, and eligibility match V1; only the "
            "selected-action field reminder is appended"
        ),
    },
    max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
    max_canary_cost_usd=MAX_CANARY_COST_USD,
    hard_total_cost_ceiling_usd=HARD_TOTAL_COST_CEILING_USD,
    claim_scope=(
        "adaptive output-contract recovery diagnostic on six curated procurement "
        "worlds; economic outcomes are development evidence and not a confirmatory "
        "mechanism effect"
    ),
    prompt=V2_PROMPT,
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
    "MESSAGE_CONTRACT",
    "PROMPT_ID",
    "SPEC",
    "TREATMENT_ID",
    "V2_PROMPT",
    "build_plan",
    "run_admission_canary",
    "run_campaign",
]
