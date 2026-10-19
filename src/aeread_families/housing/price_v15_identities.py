"""The v15 identities: confirmatory, A/A twin, variance pilot, profile admission and the scripted goldens.

Declared in ``docs/families/housing/price_confirmatory_v15_plan.md`` (Sections 5 to 9, amendments 1 to 3) and
registered into ``price_campaign.IDENTITIES`` by that module. This module is data: the specs, the ceilings and the
analysis block. It reads its worlds from the committed pack (``evidence/housing/housing_lemons_price_pack_v2``) rather
than importing ``price_pack_v2``, whose imports reach ``price_campaign``.

Every identity has v14's route, reasoning tier and sampling for its model, retry policy v2, 8 attempts a move, a
300-second timeout and $0.30 a cell. Notice 5 is the main pack's brief, and the confirmatory holdout reads
``_v5_rate30``. Each total ceiling is twice the estimate from v14's measured spend plus $0.30, the one cell
``price_campaign.run`` reserves before starting another (amendment 3). The goldens identity is scripted. Its route is
GLM's, named but never called live, and its ceiling is $0.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACK = json.loads((Path(__file__).resolve().parents[3] / "evidence/housing/housing_lemons_price_pack_v2/reports/pack.json").read_text())
MAIN = sorted(PACK["streams"]["main"]["world_seeds"])
HOLDOUT = sorted(PACK["streams"]["holdout"]["world_seeds"])
DEVELOPMENT = sorted(PACK["streams"]["development"]["world_seeds"])
PLAN = "docs/families/housing/price_confirmatory_v15_plan.md"

ANALYSIS: dict[str, Any] = {
    "plan": f"{PLAN}, Sections 5 to 9 and amendments 1 to 3",
    "independent_unit": "world_seed",
    "primary_measure": "seat0 net under measure v2 (housing_price_reply_conditioned_v2), mean of the two landlord arms, "
                       "per world; scored in each receipt by housing_lemons_price_seat0_outcome_v1",
    "population": "main pack (260 worlds); the 40 holdout worlds run outside demand at 0.3 with a brief stating 0.3, "
                  "are reported separately and never pooled",
    "contrasts": {
        "P1_P3": "every pair of models; Holm over the three; claimed when Holm rejects 0; larger than $50 only when the "
                 "95% interval clears $50",
        "B1_B3": "each model less inspect_then_sign; beats the baseline when the lower end of its 1 - 0.05/3 interval "
                 "is above $0",
        "G1_G3": "each model less the best-informed tenant; intervals, no test",
        "R1_R3": "each model less inspect_lowball; 95% and 1 - 0.05/3 intervals, no test, beside B1 to B3",
    },
    "interval": "95% Student-t over worlds, a model's cells averaged within a world first",
    "minimum_meaningful_difference_usd_per_world": 50.0,
    "calibration": "the A/A twin's paired interval must lie inside +-$50, or every larger-than-$50 reading is "
                   "reported as uncalibrated",
    "inconclusive": "a contrast that loses more than 10% of its worlds",
    "strata": "favourite_is_lemon and favourite_is_sound reported beside the pooled main pack",
    "selection_note": "the headroom screen refused 119 of 437 main seeds, so the pack is selected toward worlds where "
                      "inspecting pays; said beside any comparison with v14",
    "missingness": "a failed cell is typed missingness and never rerun",
    "model_ranking_allowed": True,
}
PILOT_ANALYSIS: dict[str, Any] = {
    "plan": f"{PLAN}, Section 8 and amendment 1",
    "purpose": "world and replicate variance of each pairwise difference for the sizing record; never analysed with "
               "the confirmatory",
    "independent_unit": "world_seed", "missingness": "report_separately", "model_ranking_allowed": False,
}
ADMISSION_ANALYSIS: dict[str, Any] = {
    "plan": f"{PLAN}, Section 7",
    "purpose": "one full trajectory on a development world in each arm, sealed before the freeze; a profile that "
               "fails is dropped and its pairs leave Section 5",
    "independent_unit": "world_seed", "missingness": "report_separately", "model_ranking_allowed": False,
}
GOLDENS_ANALYSIS: dict[str, Any] = {
    "plan": f"{PLAN}, Section 6 and amendment 1",
    "purpose": "the golden-receipt bundle through build_v15_setup: scripted seat-0 policies, no provider call",
    "independent_unit": "world_seed", "missingness": "report_separately", "model_ranking_allowed": False,
}

MODELS: dict[str, dict[str, Any]] = {
    "glm53_flash_nextbit": {"route_id": "nextbit_glm_53_flash", "profile": "housing_price_glm53_nextbit_tenant_v15",
                            "reasoning_effort": "low", "temperature": 0.0, "top_p": 1.0},
    "gpt6_luna": {"route_id": "openai_gpt_6_luna", "profile": "housing_price_gpt6_luna_tenant_v15",
                  "reasoning_effort": "low", "temperature": "unavailable", "top_p": None},
    "gemini38_flash": {"route_id": "google_gemini_38_flash", "profile": "housing_price_gemini38_tenant_v15",
                       "reasoning_effort": "minimal", "temperature": 0.0, "top_p": 1.0},
}
#: Total ceilings, $ (amendment 3).
CEILINGS: dict[str, float] = {
    "housing_lemons_price_v15_glm53_flash_nextbit": 1.13,
    "housing_lemons_price_v15_gpt6_luna": 1.57,
    "housing_lemons_price_v15_gemini38_flash": 13.11,
    "housing_lemons_price_v15_glm53_flash_nextbit_aa": 1.02,
    "housing_lemons_price_v15_pilot_glm53_flash_nextbit": 0.41,
    "housing_lemons_price_v15_pilot_gpt6_luna": 0.47,
    "housing_lemons_price_v15_pilot_gemini38_flash": 2.01,
    "housing_lemons_price_v15_admission_glm53_flash_nextbit": 0.60,
    "housing_lemons_price_v15_admission_gpt6_luna": 0.60,
    "housing_lemons_price_v15_admission_gemini38_flash": 0.60,
    "housing_lemons_price_goldens_v15": 0.0,
}
BASE: dict[str, Any] = {"outside_demand": True, "notice_version": 5, "retry_policy_version": 2,
                        "max_action_attempts": 8, "timeout_seconds": 300.0}


def _spec(campaign_id: str, model: str, **fields: Any) -> dict[str, Any]:
    return {**BASE, **MODELS[model], "total_cost_ceiling_usd": CEILINGS[campaign_id], **fields}


IDENTITIES: dict[str, dict[str, Any]] = {}
for _model in MODELS:
    IDENTITIES[f"housing_lemons_price_v15_{_model}"] = _spec(
        f"housing_lemons_price_v15_{_model}", _model, world_seeds=MAIN, holdout_world_seeds=HOLDOUT,
        claim_status="confirmatory", analysis=ANALYSIS)
    IDENTITIES[f"housing_lemons_price_v15_pilot_{_model}"] = _spec(
        f"housing_lemons_price_v15_pilot_{_model}", _model, world_seeds=DEVELOPMENT, replicates=2,
        claim_status="development", analysis=PILOT_ANALYSIS)
    IDENTITIES[f"housing_lemons_price_v15_admission_{_model}"] = _spec(
        f"housing_lemons_price_v15_admission_{_model}", _model, world_seeds=DEVELOPMENT[:1],
        claim_status="profile_admission", analysis=ADMISSION_ANALYSIS)
#: The A/A twin: the GLM confirmatory's main pack under another name, nothing else changed.
IDENTITIES["housing_lemons_price_v15_glm53_flash_nextbit_aa"] = _spec(
    "housing_lemons_price_v15_glm53_flash_nextbit_aa", "glm53_flash_nextbit", world_seeds=MAIN,
    claim_status="confirmatory", analysis=ANALYSIS)
IDENTITIES["housing_lemons_price_goldens_v15"] = _spec(
    "housing_lemons_price_goldens_v15", "glm53_flash_nextbit", world_seeds=DEVELOPMENT[:5],
    claim_status="qc_goldens", analysis=GOLDENS_ANALYSIS, scripted_only=True)
if set(IDENTITIES) != set(CEILINGS):
    raise AssertionError("every v15 identity needs exactly one declared ceiling")

__all__ = ["ANALYSIS", "CEILINGS", "DEVELOPMENT", "HOLDOUT", "IDENTITIES", "MAIN", "MODELS"]
