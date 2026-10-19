"""The v15 identities (``price_v15_identities``, plan amendments 1 to 3) and their wiring in ``price_campaign``.

What has to hold before any v15 cell runs:

1. Every v15 contract file is the one ``v15_contract`` writes, and ``load_contract`` accepts it with the declared
   worlds, replicates and ceiling.
2. A confirmatory identity builds a main plan (notice v5, 260 worlds) and a holdout plan (``_v5_rate30``, 40 worlds),
   both scored by the seat-0 scorer; identities without a holdout refuse one.
3. The goldens identity is scripted only.
4. No earlier identity's contract or plan changes: the notice-5 branches are gated, so a v14 contract still loads and
   builds without a holdout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread_families.housing import price_campaign, price_notice_v5, price_seat0, price_v15_identities as v15

ROOT = Path(__file__).resolve().parents[1]


def _load(campaign_id: str) -> dict:
    return price_campaign.load_contract(ROOT / "configs" / f"{campaign_id}.json")


@pytest.mark.parametrize("campaign_id", sorted(v15.IDENTITIES))
def test_every_v15_contract_is_the_one_its_spec_writes(campaign_id: str) -> None:
    contract = _load(campaign_id)
    assert contract == price_campaign.v15_contract(campaign_id)
    spec = v15.IDENTITIES[campaign_id]
    assert contract["total_cost_ceiling_usd"] == v15.CEILINGS[campaign_id]
    assert contract["world_seeds"] == spec["world_seeds"] and contract["replicates"] == spec.get("replicates", 1)
    assert contract["rivals"]["notice_version"] == 5 and contract["tenant_cost_ceiling_usd_per_cell"] == 0.3
    assert contract["controls"]["max_action_attempts"] == 8 and contract["controls"]["timeout_seconds"] == 300.0


def test_the_declared_ceilings_cover_the_reserved_cell() -> None:
    for campaign_id, ceiling in v15.CEILINGS.items():
        assert ceiling == 0.0 or ceiling >= 0.30 + 0.05, campaign_id


def test_a_confirmatory_identity_has_a_main_and_a_holdout_plan_scored_for_seat_zero() -> None:
    contract = _load("housing_lemons_price_v15_glm53_flash_nextbit")
    main = price_seat0.build_v15_setup(contract, "true_cost", live=True)
    held = price_seat0.build_v15_setup(contract, "true_cost", live=True, holdout_rate=True)
    assert {c.world_seed for c in main.plan.cells} == set(v15.MAIN)
    assert {c.world_seed for c in held.plan.cells} == set(v15.HOLDOUT)
    assert main.prompt_sources[price_notice_v5.PROMPT_ID].endswith(price_notice_v5.DISCLOSURE_V5)
    assert held.prompt_sources[price_notice_v5.PROMPT_ID_HOLDOUT].endswith(price_notice_v5.DISCLOSURE_V5_HOLDOUT)
    assert price_notice_v5.PROMPT_ID not in held.prompt_sources
    for setup in (main, held):
        assert setup.plan.families[0].scoring.scorer_id == price_seat0.SCORER_ID
    assert held.registry.resolve("housing_v1", "1.0.0", "aeread.housing_v1").rate == 0.3


def test_identities_without_a_holdout_refuse_one_and_the_goldens_are_scripted_only() -> None:
    with pytest.raises(ValueError, match="no holdout"):
        price_seat0.build_v15_setup(_load("housing_lemons_price_v15_pilot_gpt6_luna"), "pooled", live=True, holdout_rate=True)
    goldens = _load("housing_lemons_price_goldens_v15")
    with pytest.raises(ValueError, match="scripted only"):
        price_campaign.build_setup(goldens, "true_cost", live=True)
    assert len(price_seat0.build_v15_setup(goldens, "true_cost", live=False).plan.cells) == 5


def test_a_v14_contract_neither_has_nor_accepts_a_holdout() -> None:
    contract = price_campaign.load_contract(ROOT / "configs/housing_lemons_price_confirmatory_v14_glm53_flash_nextbit.json")
    assert "holdout" not in contract
    with pytest.raises(ValueError, match="notice-5"):
        price_campaign.build_setup(contract, "true_cost", live=False, holdout_rate=True)
    assert "price_notice_v5" not in json.dumps(contract)


def test_the_published_golden_bundle_verifies() -> None:
    from aeread_families.housing import price_goldens_v15

    assert price_goldens_v15.verify() == []
