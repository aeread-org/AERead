"""Versioned synthetic RFQ population with coupled commercial constraints.

The construction guarantees a feasible approved award by design, not by keeping
only seeds on which a model or comparison policy succeeds. Supplier identities,
directory order, quantities, prices, deadlines, and financial slack vary by seed.
The scope remains this synthetic electronics procurement grammar.
"""
from __future__ import annotations

import math
import random
from dataclasses import replace

from aeread import exchange_procurement as procurement


GENERATOR_ID = "procurement_rfq_coupled_worlds_v1"
GENERATOR_VERSION = "1.0.0"


def make_procurement_rfq_world(*, seed: int) -> procurement.ProcurementWorld:
    """Create split-capacity, late, off-list, and incompatible-MOQ decisions."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    rng = random.Random(seed)
    ids = list(range(2, 9))
    rng.shuffle(ids)
    chip_units = rng.choice((40, 60, 80, 100))
    pcb_units = rng.choice((50, 75, 100, 125))
    enclosure_units = rng.choice((50, 75, 100, 125))
    deadline = rng.randint(25, 55)
    chip_costs = [round(rng.uniform(8.0, 12.0), 2), round(rng.uniform(9.0, 14.0), 2)]
    pcb_cost = round(rng.uniform(5.0, 8.0), 2)
    enclosure_cost = round(rng.uniform(3.0, 6.0), 2)
    suppliers = [
        procurement.SupplierTerms(
            seller_id=ids[index], component="chips", unit_cost=chip_costs[index],
            capacity=math.ceil(chip_units * rng.uniform(0.55, 0.70)),
            lead_time_days=deadline - rng.randint(1, 12),
            moq=max(1, chip_units // 10), payment_terms_days=rng.choice((15, 30, 60)),
        )
        for index in range(2)
    ]
    suppliers.extend([
        procurement.SupplierTerms(
            seller_id=ids[2], component="pcb",
            unit_cost=round(pcb_cost * rng.uniform(0.55, 0.75), 2),
            capacity=2 * pcb_units, lead_time_days=deadline + rng.randint(1, 15),
            moq=max(1, pcb_units // 10),
        ),
        procurement.SupplierTerms(
            seller_id=ids[3], component="pcb", unit_cost=pcb_cost,
            capacity=pcb_units + rng.randint(0, pcb_units // 2),
            lead_time_days=deadline - rng.randint(1, 12),
            moq=max(1, pcb_units // 5), payment_terms_days=rng.choice((15, 30, 60)),
        ),
        procurement.SupplierTerms(
            seller_id=ids[4], component="enclosure",
            unit_cost=round(enclosure_cost * rng.uniform(0.55, 0.75), 2),
            capacity=math.ceil(enclosure_units * 0.90),
            lead_time_days=deadline - rng.randint(1, 12),
            moq=math.ceil(enclosure_units * 0.75),
        ),
        procurement.SupplierTerms(
            seller_id=ids[5], component="enclosure", unit_cost=enclosure_cost,
            capacity=enclosure_units + rng.randint(0, enclosure_units // 2),
            lead_time_days=deadline - rng.randint(1, 12),
            moq=math.ceil(enclosure_units * 0.45), payment_terms_days=rng.choice((15, 30, 60)),
        ),
        procurement.SupplierTerms(
            seller_id=ids[6], component="chips",
            unit_cost=round(min(chip_costs) * rng.uniform(0.55, 0.75), 2),
            capacity=chip_units, lead_time_days=deadline - rng.randint(1, 12), moq=1,
        ),
    ])
    rng.shuffle(suppliers)
    world = procurement.ProcurementWorld(
        name=f"procurement_rfq_seed_{seed}", buyer_agent=1, suppliers=suppliers,
        demand=procurement.DemandSpec(
            units_required={"chips": chip_units, "pcb": pcb_units, "enclosure": enclosure_units},
            deadline_days=deadline, contract_value=1.0,
        ),
        authz=procurement.AuthorizationSpec(
            budget=1_000_000.0, approved_vendors=sorted(ids[:6]), signoff_threshold=1_000_000.0,
        ),
    )
    # Economic calibration is based only on the declared world truth. It does
    # not inspect model outcomes, reroll seeds, or select by baseline performance.
    allocation = procurement.solve_min_cost_award(world)
    if not allocation.feasible:
        raise ValueError("coupled RFQ construction produced an infeasible world")
    budget = float(math.ceil(allocation.min_cost * rng.uniform(1.12, 1.24)))
    return replace(
        world,
        demand=replace(world.demand, contract_value=float(math.ceil(allocation.min_cost * rng.uniform(1.30, 1.55)))),
        authz=replace(world.authz, budget=budget, signoff_threshold=math.floor(budget * rng.uniform(0.70, 0.95))),
    )
