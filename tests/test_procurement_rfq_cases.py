"""Population contract: seeded, coupled procurement decisions, not fixture copies."""
from dataclasses import replace

import pytest

from aeread import exchange_procurement as procurement
from aeread import procurement_rfq_env as rfq
from aeread.procurement_rfq_cases import make_procurement_rfq_world


def test_generator_is_reproducible_and_varies_economic_worlds() -> None:
    worlds = [make_procurement_rfq_world(seed=seed) for seed in range(12)]
    assert rfq.world_to_payload(worlds[3]) == rfq.world_to_payload(
        make_procurement_rfq_world(seed=3)
    )
    assert len({procurement.world_to_json(world) for world in worlds}) == 12
    assert len({world.authz.budget for world in worlds}) > 5
    assert len({tuple(world.demand.units_required.values()) for world in worlds}) > 5
    assert len({tuple(s.seller_id for s in world.suppliers) for world in worlds}) > 5


@pytest.mark.parametrize("seed", range(12))
def test_generated_world_preserves_policy_deadline_split_and_moq_traps(seed) -> None:
    world = make_procurement_rfq_world(seed=seed)
    approved = set(world.authz.approved_vendors)
    eligible = [s for s in world.suppliers if s.seller_id in approved and s.lead_time_days <= world.demand.deadline_days]
    assert len(world.suppliers) == 7
    assert len(eligible) == 5
    assert len({s.seller_id for s in world.suppliers}) == 7
    assert any(s.seller_id not in approved and s.component == "chips" for s in world.suppliers)
    assert any(s.seller_id in approved and s.lead_time_days > world.demand.deadline_days for s in world.suppliers)
    chips = [s for s in eligible if s.component == "chips"]
    need = world.demand.units_required["chips"]
    assert all(s.capacity < need for s in chips)
    assert sum(s.capacity for s in chips) >= need
    enclosures = [s for s in eligible if s.component == "enclosure"]
    need = world.demand.units_required["enclosure"]
    assert sum(s.moq for s in enclosures) > need
    cheap = min(enclosures, key=lambda s: s.unit_cost)
    assert cheap.capacity < need
    assert world.authz.signoff_threshold < world.authz.budget < world.demand.contract_value
    assert procurement.solve_min_cost_award(world).feasible
    baseline = rfq.run_scripted_rfq_baseline(
        world, max_contacts=5, contact_cost=5.0, disclosure_anchor=0.95
    )
    assert baseline.executed and baseline.approval_granted
    assert not baseline.violations and baseline.disclosed_rfq_count == 0
    assert 0 < baseline.buyer_surplus <= baseline.buyer_surplus_upper_bound
    assert baseline.buyer_surplus_score <= 1.0
    market = rfq.ProcurementRFQMarket(world, max_contacts=5, contact_cost=5.0, disclosure_anchor=0.95)
    assert "unit_cost" not in str(market.buyer_observation())


def test_bound_is_invariant_to_vendor_identity_and_order() -> None:
    world = make_procurement_rfq_world(seed=29)
    renamed = replace(
        world,
        suppliers=[replace(s, seller_id=s.seller_id + 100) for s in reversed(world.suppliers)],
        authz=replace(world.authz, approved_vendors=[s + 100 for s in world.authz.approved_vendors]),
    )
    assert rfq.buyer_surplus_upper_bound(world, max_contacts=5, contact_cost=5.0) == pytest.approx(
        rfq.buyer_surplus_upper_bound(renamed, max_contacts=5, contact_cost=5.0)
    )


@pytest.mark.parametrize("seed", [-1, True, 1.5, "0"])
def test_generator_rejects_invalid_seed(seed) -> None:
    with pytest.raises(ValueError, match="seed"):
        make_procurement_rfq_world(seed=seed)
