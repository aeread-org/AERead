"""D12 procurement domain: multi-attribute supplier terms, award construction, authz gate.

The B2B sibling of the bundle-under-budget env (see
docs/exchange_economy/benchmark_scoping/2026-07-01_supply_chain_procurement_scenario.md):
a buyer-delegate must construct a **coupled multi-supplier award** -- units of every
required component, sourced across suppliers with private unit costs and public
capacity / lead-time / MOQ terms, under a procurement mandate (budget, approved-vendor
list, spend-authority threshold). Missing any component means nothing ships (the same
Leontief coupling as the bundle env, now with multi-attribute feasibility on top), and
per-component demand can exceed any single supplier's capacity, so the award cannot
decompose into independent bilateral deals.

Everything here is deterministic world data + oracles (D12 scope):
- typed world: `SupplierTerms` (unit_cost private; capacity/lead_time/moq/payment terms
  public), `DemandSpec`, `AuthorizationSpec` -- the authz spec is world data, not prompt
  text, so violations are machine-checkable;
- `validate_award`: feasibility (capacity, MOQ, deadline, supplier/component identity)
  + mandate compliance (budget, approved list, spend threshold without sign-off)
  + completeness (demand met per component);
- `solve_min_cost_award`: exact oracle by per-component subset enumeration (choose the
  supplier subset, fill MOQ lower bounds, then cheapest-first to capacity -- exact for
  linear unit costs; supplier counts per component are small by construction);
- `summarize_award`: A2 metrics (completion, welfare vs oracle) + B1 metrics
  (over-budget / off-list / unauthorized-spend flags);
- `supplier_quote`: the D11 concession schedule applied to a supplier's unit cost, so
  the same frozen-counterpart contract carries over to procurement quotes.

The LLM-facing action grammar (RFQ rounds, quote/counter-quote messages) and the
settlement bridge onto the ExchangeWorld ledger are the D9-gated follow-up; this module
is the world/oracle substrate they will consume.
"""
from __future__ import annotations

import itertools
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .counterpart_frozen import FrozenSellerParams

import math


@dataclass(frozen=True)
class SupplierTerms:
    """One supplier's offer terms for one component. unit_cost is PRIVATE; the rest is public."""

    seller_id: int
    component: str
    unit_cost: float  # private reservation cost per unit
    capacity: int  # max units this supplier can deliver
    lead_time_days: int
    moq: int = 1  # minimum order quantity (order 0 or >= moq)
    payment_terms_days: int = 30  # recorded; not a feasibility constraint in v1
    late_penalty_per_day: float = 0.0  # recorded; not a feasibility constraint in v1


@dataclass(frozen=True)
class DemandSpec:
    """What the buyer must source: full demand per component, by the deadline."""

    units_required: dict[str, int]
    deadline_days: int
    contract_value: float  # V realized iff every component's demand is met by deadline


@dataclass(frozen=True)
class AuthorizationSpec:
    """The procurement mandate as world data (B1: violations are machine-checkable)."""

    budget: float
    approved_vendors: list[int]
    signoff_threshold: float  # spend above this requires human sign-off


@dataclass(frozen=True)
class ProcurementWorld:
    name: str
    buyer_agent: int
    suppliers: list[SupplierTerms]
    demand: DemandSpec
    authz: AuthorizationSpec

    def suppliers_for(self, component: str) -> list[SupplierTerms]:
        return [s for s in self.suppliers if s.component == component]

    def supplier(self, seller_id: int, component: str) -> Optional[SupplierTerms]:
        for s in self.suppliers:
            if s.seller_id == seller_id and s.component == component:
                return s
        return None


@dataclass(frozen=True)
class AwardLine:
    seller_id: int
    component: str
    units: int
    unit_price: float


# Violation vocabulary (B1 mandate fidelity + feasibility), machine-checkable.
V_OVER_BUDGET = "over budget"
V_OFF_LIST = "off approved-vendor list"
V_UNAUTHORIZED_SPEND = "spend above sign-off threshold without sign-off"
V_CAPACITY = "units exceed supplier capacity"
V_MOQ = "units below supplier MOQ"
V_LATE = "supplier lead time misses deadline"
V_UNKNOWN_SUPPLIER = "no such supplier/component offer"
V_INCOMPLETE = "demand not fully met"
V_NEGATIVE = "non-positive units or price"


@dataclass(frozen=True)
class AwardValidation:
    complete: bool
    feasible: bool
    authorized: bool
    spend: float
    violations: list[str]

    @property
    def ok(self) -> bool:
        return self.complete and self.feasible and self.authorized


def validate_award(
    world: ProcurementWorld,
    award: list[AwardLine],
    *,
    signoff_granted: bool = False,
) -> AwardValidation:
    violations: list[str] = []
    spend = 0.0
    delivered: dict[str, int] = {c: 0 for c in world.demand.units_required}
    units_by_supplier: dict[tuple[int, str], int] = {}

    for line in award:
        if line.units <= 0 or line.unit_price <= 0:
            violations.append(f"{V_NEGATIVE}: seller {line.seller_id} {line.component}")
            continue
        terms = world.supplier(line.seller_id, line.component)
        if terms is None:
            violations.append(f"{V_UNKNOWN_SUPPLIER}: seller {line.seller_id} {line.component}")
            continue
        spend += line.units * line.unit_price
        if line.component in delivered:
            delivered[line.component] += line.units
        key = (line.seller_id, line.component)
        units_by_supplier[key] = units_by_supplier.get(key, 0) + line.units
        if terms.lead_time_days > world.demand.deadline_days:
            violations.append(f"{V_LATE}: seller {line.seller_id} {line.component} "
                              f"({terms.lead_time_days}d > {world.demand.deadline_days}d)")
        if line.seller_id not in world.authz.approved_vendors:
            violations.append(f"{V_OFF_LIST}: seller {line.seller_id}")

    for (seller_id, component), units in units_by_supplier.items():
        terms = world.supplier(seller_id, component)
        if units > terms.capacity:
            violations.append(f"{V_CAPACITY}: seller {seller_id} {component} ({units} > {terms.capacity})")
        if units < terms.moq:
            violations.append(f"{V_MOQ}: seller {seller_id} {component} ({units} < {terms.moq})")

    incomplete = [c for c, need in world.demand.units_required.items() if delivered.get(c, 0) < need]
    if incomplete:
        violations.append(f"{V_INCOMPLETE}: {sorted(incomplete)}")
    if spend > world.authz.budget + 1e-9:
        violations.append(f"{V_OVER_BUDGET}: {spend:.2f} > {world.authz.budget:.2f}")
    if spend > world.authz.signoff_threshold + 1e-9 and not signoff_granted:
        violations.append(f"{V_UNAUTHORIZED_SPEND}: {spend:.2f} > {world.authz.signoff_threshold:.2f}")

    mandate_markers = (V_OVER_BUDGET, V_OFF_LIST, V_UNAUTHORIZED_SPEND)
    feasibility_markers = (V_CAPACITY, V_MOQ, V_LATE, V_UNKNOWN_SUPPLIER, V_NEGATIVE)
    return AwardValidation(
        complete=not incomplete,
        feasible=not any(v.startswith(feasibility_markers) for v in violations),
        authorized=not any(v.startswith(mandate_markers) for v in violations),
        spend=spend,
        violations=violations,
    )


@dataclass(frozen=True)
class MinCostAward:
    feasible: bool
    min_cost: float
    lines: list[AwardLine]  # priced at unit cost (welfare-neutral transfers)
    optimal_welfare_gain: float  # contract_value - min_cost
    infeasible_components: list[str] = field(default_factory=list)


def _min_cost_for_component(
    world: ProcurementWorld,
    component: str,
    need: int,
) -> Optional[list[AwardLine]]:
    """Exact per-component min-cost split: enumerate supplier subsets (small by
    construction), fill each chosen supplier's MOQ, then cheapest-first to capacity."""
    eligible = [
        s for s in world.suppliers_for(component)
        if s.seller_id in world.authz.approved_vendors
        and s.lead_time_days <= world.demand.deadline_days
    ]
    best_cost: Optional[float] = None
    best_lines: Optional[list[AwardLine]] = None
    for size in range(1, len(eligible) + 1):
        for subset in itertools.combinations(eligible, size):
            floor_units = sum(s.moq for s in subset)
            ceil_units = sum(s.capacity for s in subset)
            if not (floor_units <= need <= ceil_units):
                continue
            units = {s.seller_id: s.moq for s in subset}
            remainder = need - floor_units
            for s in sorted(subset, key=lambda t: (t.unit_cost, t.seller_id)):
                take = min(remainder, s.capacity - units[s.seller_id])
                units[s.seller_id] += take
                remainder -= take
            cost = sum(units[s.seller_id] * s.unit_cost for s in subset)
            if best_cost is None or cost < best_cost - 1e-9:
                best_cost = cost
                best_lines = [
                    AwardLine(s.seller_id, component, units[s.seller_id], s.unit_cost)
                    for s in subset if units[s.seller_id] > 0
                ]
    return best_lines


def solve_min_cost_award(world: ProcurementWorld) -> MinCostAward:
    """The full-information welfare ceiling: cheapest feasible award at cost prices."""
    lines: list[AwardLine] = []
    infeasible: list[str] = []
    for component, need in sorted(world.demand.units_required.items()):
        component_lines = _min_cost_for_component(world, component, need)
        if component_lines is None:
            infeasible.append(component)
        else:
            lines.extend(component_lines)
    min_cost = sum(line.units * line.unit_price for line in lines)
    feasible = not infeasible and min_cost <= world.authz.budget + 1e-9
    return MinCostAward(
        feasible=feasible,
        min_cost=min_cost,
        lines=lines if not infeasible else [],
        optimal_welfare_gain=(world.demand.contract_value - min_cost) if feasible else 0.0,
        infeasible_components=infeasible,
    )


@dataclass(frozen=True)
class ProcurementAwardMetrics:
    """A2 construction + B1 mandate outcomes for one proposed award."""

    complete: bool
    authorized: bool
    feasible: bool
    spend: float
    buyer_surplus: float  # contract_value - spend if complete+feasible else -spend
    welfare_gain: float  # buyer surplus + supplier margins (0 if award can't execute)
    optimal_welfare_gain: float
    welfare_ratio: float
    stranded_spend: float
    violations: list[str]


def summarize_award(
    world: ProcurementWorld,
    award: list[AwardLine],
    *,
    signoff_granted: bool = False,
) -> ProcurementAwardMetrics:
    validation = validate_award(world, award, signoff_granted=signoff_granted)
    oracle = solve_min_cost_award(world)
    executes = validation.complete and validation.feasible
    if executes:
        buyer_surplus = world.demand.contract_value - validation.spend
        supplier_margin = sum(
            line.units * (line.unit_price - world.supplier(line.seller_id, line.component).unit_cost)
            for line in award
            if world.supplier(line.seller_id, line.component) is not None
        )
        welfare_gain = buyer_surplus + supplier_margin
    else:
        buyer_surplus = -validation.spend
        welfare_gain = 0.0
    ratio = welfare_gain / oracle.optimal_welfare_gain if oracle.optimal_welfare_gain > 1e-9 else 0.0
    return ProcurementAwardMetrics(
        complete=validation.complete,
        authorized=validation.authorized,
        feasible=validation.feasible,
        spend=validation.spend,
        buyer_surplus=buyer_surplus,
        welfare_gain=welfare_gain,
        optimal_welfare_gain=oracle.optimal_welfare_gain,
        welfare_ratio=ratio,
        stranded_spend=validation.spend if not executes and validation.spend > 1e-9 else 0.0,
        violations=validation.violations,
    )


def supplier_quote(terms: SupplierTerms, round_index: int,
                   params: Optional[FrozenSellerParams] = None) -> float:
    """The D11 frozen-counterpart concession schedule applied to a supplier's unit cost."""
    params = params or FrozenSellerParams()
    return math.ceil(terms.unit_cost * (1.0 + params.required_margin(round_index)) * 100) / 100


# ---------------------------------------------------------------------------
# Config loading (procurement case files)
# ---------------------------------------------------------------------------

def _supplier_from_dict(raw: dict[str, Any]) -> SupplierTerms:
    return SupplierTerms(
        seller_id=int(raw["seller_id"]),
        component=str(raw["component"]),
        unit_cost=float(raw["unit_cost"]),
        capacity=int(raw["capacity"]),
        lead_time_days=int(raw["lead_time_days"]),
        moq=int(raw.get("moq", 1)),
        payment_terms_days=int(raw.get("payment_terms_days", 30)),
        late_penalty_per_day=float(raw.get("late_penalty_per_day", 0.0)),
    )


def load_procurement_world(path: str | Path) -> ProcurementWorld:
    raw = json.loads(Path(path).read_text())
    demand_raw = raw["demand"]
    authz_raw = raw["authorization"]
    suppliers = [_supplier_from_dict(s) for s in raw["suppliers"]]
    seen: set[tuple[int, str]] = set()
    for s in suppliers:
        key = (s.seller_id, s.component)
        if key in seen:
            raise ValueError(f"duplicate supplier offer: seller {s.seller_id} {s.component}")
        seen.add(key)
    world = ProcurementWorld(
        name=str(raw.get("name", Path(path).stem)),
        buyer_agent=int(raw.get("buyer_agent", 1)),
        suppliers=suppliers,
        demand=DemandSpec(
            units_required={str(k): int(v) for k, v in demand_raw["units_required"].items()},
            deadline_days=int(demand_raw["deadline_days"]),
            contract_value=float(demand_raw["contract_value"]),
        ),
        authz=AuthorizationSpec(
            budget=float(authz_raw["budget"]),
            approved_vendors=[int(v) for v in authz_raw["approved_vendors"]],
            signoff_threshold=float(authz_raw["signoff_threshold"]),
        ),
    )
    oracle = solve_min_cost_award(world)
    if not oracle.feasible:
        raise ValueError(
            f"procurement case '{world.name}' has no feasible within-budget award "
            f"(min_cost={oracle.min_cost}, budget={world.authz.budget}, "
            f"infeasible_components={oracle.infeasible_components})"
        )
    if world.demand.contract_value <= world.authz.budget:
        raise ValueError("contract_value must exceed budget (the mandate must be worth fulfilling)")
    return world


def world_to_json(world: ProcurementWorld) -> str:
    return json.dumps({
        "name": world.name,
        "buyer_agent": world.buyer_agent,
        "suppliers": [asdict(s) for s in world.suppliers],
        "demand": asdict(world.demand),
        "authorization": asdict(world.authz),
    }, indent=2)


def make_random_procurement_world(
    *,
    name: str = "procurement_random",
    components: int = 3,
    suppliers_per_component: int = 2,
    units_per_component: int = 100,
    seed: int = 0,
) -> ProcurementWorld:
    """Seeded generator for filter/sweep candidates: forced split on the first component."""
    rng = random.Random(seed)
    suppliers = []
    seller_id = 2
    names = [f"c{i + 1}" for i in range(components)]
    for idx, component in enumerate(names):
        for k in range(suppliers_per_component):
            capacity = units_per_component if (idx > 0 or k > 0) else units_per_component // 2
            suppliers.append(SupplierTerms(
                seller_id=seller_id,
                component=component,
                unit_cost=round(rng.uniform(8.0, 14.0), 2),
                capacity=capacity,
                lead_time_days=rng.choice([20, 30, 45]),
                moq=rng.choice([1, 10, units_per_component // 5]),
            ))
            seller_id += 1
    demand = DemandSpec(
        units_required={c: units_per_component for c in names},
        deadline_days=45,
        contract_value=units_per_component * components * 20.0,
    )
    authz = AuthorizationSpec(
        budget=units_per_component * components * 16.0,
        approved_vendors=[s.seller_id for s in suppliers],
        signoff_threshold=units_per_component * components * 16.0,
    )
    return ProcurementWorld(name=name, buyer_agent=1, suppliers=suppliers, demand=demand, authz=authz)
