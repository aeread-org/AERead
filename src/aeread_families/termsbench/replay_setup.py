"""The evaluation setup a published TERMS-Bench receipt was sealed under, for `aeread verify-replay`.

    aeread verify-replay evidence/<bundle> --run-root runs/termsbench/<campaign>/attempt_001 \\
        --setup aeread_families.termsbench.replay_setup:setup_for_receipt

A receipt names its case and its run-plan digest but not its campaign. Each candidate campaign's
setup is rebuilt from current source for the receipt's case, and the one whose plan digest equals
the receipt's is returned. When none matches, the plan cannot be rebuilt from current source
(TB-D-04) and the check reports the row as `differs` with the digests it tried.

Candidates are the registered campaigns plus pilot v2, which left the registry when v3 changed its
reasoning condition. v2's controls are read from its sealed campaign plan: the suppressing
reasoning declaration, the 4,000-token output ceiling and $0.05 per trajectory ($1.51 planned over
30 cases and the canary).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .campaign import CAMPAIGNS, SEED
from .live import (
    GLM53_FLASH_PARASAIL,
    MAX_OUTPUT_TOKENS,
    REASONING_SUPPRESSED_V1,
    build_live_setup,
)

_PILOT_V2 = {
    "route": GLM53_FLASH_PARASAIL,
    "reasoning": REASONING_SUPPRESSED_V1,
    "max_output_tokens": MAX_OUTPUT_TOKENS,
    "max_trajectory_cost_usd": 0.05,
}


def _candidates() -> list[tuple[str, dict[str, Any]]]:
    registered = [
        (
            spec.campaign_id,
            {
                "route": spec.route,
                "reasoning": spec.reasoning,
                "max_output_tokens": spec.max_output_tokens,
                "max_trajectory_cost_usd": spec.max_trajectory_cost_usd,
            },
        )
        for spec in CAMPAIGNS.values()
    ]
    return [*registered, ("termsbench_glm53_flash_parasail_pilot_v2", _PILOT_V2)]


def setup_for_receipt(receipt: Mapping[str, Any]):
    case_id = receipt["case_id"]
    expected = receipt["run_plan_sha256"]
    tried = {}
    for campaign_id, controls in _candidates():
        setup = build_live_setup(case_id=case_id, seed=SEED, **controls)
        if setup.plan.plan_sha256 == expected:
            return setup
        tried[campaign_id] = setup.plan.plan_sha256[:12]
    raise ValueError(
        f"no campaign rebuilds the plan {expected[:12]} for {case_id} from current source; tried {tried}"
    )
