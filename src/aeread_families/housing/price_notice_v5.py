"""Notice v5 for the v15 tenant: notice v4 followed by notice v3's pricing paragraph, both unchanged.

The v15 plan (``docs/families/housing/price_confirmatory_v15_plan.md``, Section 3) declares the text:
``price_outside_demand.DISCLOSURE_V4`` (departure rule, horizon, round order, reply history) then
``price_outside_demand.PRICING_RULE`` (a sound landlord accepts at or above its cost plus $25, or the ask if lower, and
otherwise counters there; a rent more than $55 under the ask proves a lemon). The v14 tenants were not told the
pricing rule, so part of their gap to the best-informed tenant was information rather than judgment.

As in v4, the notice goes in the sealed tenant prompt after the price prompt (``tenant_prompt``), so the plan hashes
the text the tenant reads; nothing is appended by the seat router.

The holdout plays outside demand at 0.3 a round (``price_outside_demand_holdout``), but notice v4 states the rate as
0.5. ``DISCLOSURE_V5_HOLDOUT`` is the same text with only that number changed, so a holdout brief states the rule its
environment runs. The plan does not say which notice the holdout's tenants read; that choice is the campaign's, and
both texts are here so it can be declared. Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import hashlib
from typing import Any

from aeread_families.housing import price_outside_demand as od
from aeread_families.housing import price_outside_demand_holdout as holdout
from aeread_families.housing.runner import HOUSING_TENANT_LEMONS_PRICE_PROMPT

NOTICE_VERSION = 5
DISCLOSURE_V5 = od.DISCLOSURE_V4 + od.PRICING_RULE
DISCLOSURE_V5_SHA256 = hashlib.sha256(DISCLOSURE_V5.encode("utf-8")).hexdigest()
PROMPT_ID = "housing_tenant_lemons_price_outside_v5"

RATE_SENTENCE = f"with probability {od.RATE}, independently"
if DISCLOSURE_V5.count(RATE_SENTENCE) != 1:
    raise AssertionError("notice v4's departure sentence moved; the holdout notice cannot be derived from it")
DISCLOSURE_V5_HOLDOUT = DISCLOSURE_V5.replace(RATE_SENTENCE, f"with probability {holdout.RATE}, independently")
DISCLOSURE_V5_HOLDOUT_SHA256 = hashlib.sha256(DISCLOSURE_V5_HOLDOUT.encode("utf-8")).hexdigest()
PROMPT_ID_HOLDOUT = "housing_tenant_lemons_price_outside_v5_rate30"


def tenant_prompt(holdout_rate: bool = False) -> tuple[str, str]:
    """(prompt id, text) for the sealed tenant prompt: the price prompt, then notice v5."""
    if holdout_rate:
        return PROMPT_ID_HOLDOUT, HOUSING_TENANT_LEMONS_PRICE_PROMPT + DISCLOSURE_V5_HOLDOUT
    return PROMPT_ID, HOUSING_TENANT_LEMONS_PRICE_PROMPT + DISCLOSURE_V5


def block_v5(holdout_rate: bool = False) -> dict[str, Any]:
    """The outside-demand block of a contract whose tenant reads notice v5."""
    prompt_id, _ = tenant_prompt(holdout_rate)
    text, digest = (DISCLOSURE_V5_HOLDOUT, DISCLOSURE_V5_HOLDOUT_SHA256) if holdout_rate else (DISCLOSURE_V5, DISCLOSURE_V5_SHA256)
    block = {
        **od.block_v4(), "notice_version": NOTICE_VERSION,
        "focal_notice": text, "focal_notice_sha256": digest,
        "focal_notice_delivery": f"in the sealed tenant prompt (prompt id {prompt_id}), after the price prompt; "
                                 "nothing is appended by the seat router",
        "pricing_rule_stated": od.PRICING_RULE.strip(),
    }
    if holdout_rate:
        block.update({k: v for k, v in holdout.block().items() if k in {"model", "revision", "rate_per_round", "draw"}})
    return block


__all__ = ["DISCLOSURE_V5", "DISCLOSURE_V5_HOLDOUT", "DISCLOSURE_V5_HOLDOUT_SHA256", "DISCLOSURE_V5_SHA256", "NOTICE_VERSION",
           "PROMPT_ID", "PROMPT_ID_HOLDOUT", "block_v5", "tenant_prompt"]
