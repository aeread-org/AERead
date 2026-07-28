"""Hidden-utility exchange economy for self-interested LLM agents.

Fresh-build experiment:
  - Agents start with different resource endowments.
  - Resource types have agent-specific private marginal utilities.
  - Agents observe allocations and their own preferences, but not others' utilities.
  - A controller set (default agents 1,3,5) gets proposal turns.
  - Agents communicate and finalize through a neutral PUBLIC ACTION envelope.
  - A separate compiler/verifier pair translates free-form transcripts into generic
    ledger effects: concrete transfers plus optional open-text public-state updates.
  - The harness enforces deterministic feasibility/consent for transfers, preserves
    public institutional memory, and records welfare/fairness ex post.

The old structured named-action path is archived in
sprint/archive/exchange_economy_legacy_named_actions_20260615.py. The active path
keeps prompt-facing mechanism substance free-form and envelope-based.

Example Gemini pilot:
  set -a; source .env; set +a
  python sprint/exchange_economy.py --model google/gemini-3.5-flash --rounds 300
"""
from __future__ import annotations

import argparse
from itertools import combinations
from copy import deepcopy
import json
import math
import os
import random
import re
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]

_envf = Path.cwd() / ".env"
if _envf.exists():
    for _line in _envf.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
os.environ.setdefault("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

try:
    from aeread.llm_agent import call_llm, call_llm_batch  # noqa: E402
except Exception:  # pragma: no cover
    call_llm = None  # type: ignore
    call_llm_batch = None  # type: ignore


Quantity = int | float
Vector = list[int]
Matrix = list[list[Quantity]]
FloatMatrix = list[list[float]]
_CACHEABLE_CONTEXT_MARKER = "Viewer-specific contact context:"


@dataclass(frozen=True)
class Transfer:
    from_agent: int
    to_agent: int
    resource: int
    quantity: Quantity


@dataclass(frozen=True)
class CompiledMechanism:
    """Executable ledger form produced from a free-form transcript.

    The deterministic executor only enforces final resource transfers plus debit
    consent. Institutional updates are open public memory records, not privileged
    Python actions or future-transfer authority.
    """

    proposer_id: int
    label: str
    summary: str
    transfers: list[Transfer]
    consenting_agents: list[int]
    confidence: float
    institutional_updates: list[dict[str, Any]] = field(default_factory=list)
    verifier_ok: bool = True
    verifier_reason: str = ""


@dataclass(frozen=True)
class RoundTranscript:
    round_index: int
    controller_id: int
    proposal_text: str
    response_texts: dict[int, str]
    final_text: str
    communication_texts: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProtocolConfig:
    """Reusable interaction protocol, separate from environment settings."""

    name: str = "universal_public_action"
    information_reveal_profile: str = "legacy"
    visibility_mode: str = "full_public"
    visible_agents_per_agent: Optional[int] = None
    visibility_seed: int = 0
    public_broadcast: bool = True
    communication_scope: str = "all"
    show_full_allocation: bool = True
    show_resource_totals: bool = True
    direct_contact_scope: str = "unrestricted"
    response_scope: str = "all"
    settlement_row_limit: Optional[int] = None
    strict_self_interest: bool = False
    require_final_public_state_update_for_institutions: bool = True
    private_acceptance_check: bool = False
    private_acceptance_mode: str = "llm_structured"
    private_acceptance_context: str = "minimal"
    atomic_commit: bool = False
    ir_enforce: bool = False
    partial_clearing: bool = False
    anti_anchor_mechanism_example: str = ""
    defection_rate: float = 0.0  # fraction of counterparties that decline/reject (adversarial)
    defection_seed: int = 0  # seed for the deterministic defector sample
    reveal_all_private_values: bool = False  # full-information: disclose every agent's utility table to all agents (W_full ceiling arm)


@dataclass(frozen=True)
class InformationRevealAudit:
    """Validation result for agent-facing environment disclosures."""

    profile: str
    ok: bool
    violations: list[str]
    checked_texts: list[str] = field(default_factory=list)

    def format(self) -> str:
        if self.ok:
            return f"information reveal audit ok profile={self.profile} checked={len(self.checked_texts)}"
        return (
            f"information reveal audit failed profile={self.profile} checked={len(self.checked_texts)}:\n"
            + "\n".join(f"- {item}" for item in self.violations)
        )


@dataclass(frozen=True)
class InstitutionPressureConfig:
    """Environment pressure that can make reusable public state privately useful."""

    search_cost_per_public_round: float = 0.0
    search_cost_per_contacted_agent: float = 0.0
    contact_expansion_cost: float = 0.0
    standing_rule_bonus_or_cost_saving: float = 0.0
    preference_shock_frequency: int = 0
    recurring_demand_mode: str = "none"


@dataclass(frozen=True)
class BundleUtilitySpec:
    """Bundle-under-budget buyer objective: Leontief over the required set + quasi-linear money.

    The buyer realizes ``bundle_value`` iff it holds >= 1 unit of EVERY required
    component; otherwise the components contribute ~0. Money is a linear
    numeraire, and the buyer's money endowment IS the budget (the principal's
    mandate), so overspending one leg strands the rest of the bundle.
    """

    buyer_agent: int
    money_resource: int
    required_components: list[int]
    bundle_value: float
    budget: float


@dataclass(frozen=True)
class SellerLayoutConfig:
    """Which seller holds which component, plus the private reservation-cost range."""

    component_by_seller: dict[int, int]
    seller_cost_range: tuple[float, float]


@dataclass(frozen=True)
class ExchangeExperimentConfig:
    """Environment setup loaded from JSON so protocol code stays reusable."""

    name: str
    description: str
    num_agents: int
    num_resources: int
    units_per_home_resource: int
    seed: int
    rounds: int
    controllers: list[int]
    protocol: ProtocolConfig
    utility_mode: str = "linear"
    institution_pressure: InstitutionPressureConfig = field(default_factory=InstitutionPressureConfig)
    world_type: str = "procedural"  # "procedural" | "ring_cycle" | "bundle_under_budget"
    cycle_length: Optional[int] = None  # required-cycle length k for world_type="ring_cycle"
    with_money: bool = False  # append a transferable numeraire good (money) valued 1.0 by all
    bundle_spec: Optional[BundleUtilitySpec] = None  # world_type="bundle_under_budget"
    seller_layout: Optional[SellerLayoutConfig] = None  # world_type="bundle_under_budget"


@dataclass(frozen=True)
class PrivateAcceptanceAudit:
    agent_id: int
    approve: bool
    actual_delta: float
    actual_delta_sign: str
    claimed_delta_sign: str
    sign_match: bool
    debit_rows_match: bool
    credit_rows_match: bool
    quantity_match: bool
    counterpart_transfers_present: bool
    same_bundle_authorized: bool
    approval_correct: bool
    error_family: str
    reason: str = ""


# ===============================================================
# Economy and metrics
# ===============================================================


@dataclass
class ExchangeWorld:
    allocation: Matrix
    preferences: FloatMatrix
    resource_names: list[str] = field(default_factory=list)
    agent_names: list[str] = field(default_factory=list)
    institutions: list[dict[str, Any]] = field(default_factory=list)
    utility_mode: str = "linear"
    institution_pressure: InstitutionPressureConfig = field(default_factory=InstitutionPressureConfig)
    money_good_index: Optional[int] = None
    bundle_utility: Optional[BundleUtilitySpec] = None  # buyer's Leontief objective (bundle worlds)

    def __post_init__(self) -> None:
        if not self.allocation:
            raise ValueError("allocation must contain at least one agent")
        n_resources = len(self.allocation[0])
        if n_resources == 0:
            raise ValueError("allocation must contain at least one resource")
        if any(len(row) != n_resources for row in self.allocation):
            raise ValueError("allocation rows must have equal length")
        if len(self.preferences) != len(self.allocation):
            raise ValueError("preferences must have one row per agent")
        if any(len(row) != n_resources for row in self.preferences):
            raise ValueError("preference rows must match allocation width")
        if any(x < 0 for row in self.allocation for x in row):
            raise ValueError("initial allocations cannot be negative")
        if not self.resource_names:
            self.resource_names = [f"r{i + 1}" for i in range(n_resources)]
        if not self.agent_names:
            self.agent_names = [f"a{i + 1}" for i in range(len(self.allocation))]

    @property
    def num_agents(self) -> int:
        return len(self.allocation)

    @property
    def num_resources(self) -> int:
        return len(self.allocation[0])

    def copy_allocation(self) -> Matrix:
        return [row[:] for row in self.allocation]

    def utility(self, agent_id: int, allocation: Optional[Matrix] = None) -> float:
        alloc = self.allocation if allocation is None else allocation
        i = _idx(agent_id, self.num_agents, "agent")
        return agent_utility_for_bundle_row(self, i, alloc[i])

    def public_state(self, agent_id: int) -> dict[str, Any]:
        i = _idx(agent_id, self.num_agents, "agent")
        return {
            "agent_id": agent_id,
            "agent_name": self.agent_names[i],
            "resource_names": self.resource_names[:],
            "allocation": [row[:] for row in self.allocation],
            "own_allocation": self.allocation[i][:],
            "own_preferences": self.preferences[i][:],
            "own_utility": self.utility(agent_id),
            "resource_totals": resource_totals(self.allocation),
            "institutions": active_institutions(self),
        }


def _utility_component(value: float, quantity: Quantity, utility_mode: str) -> float:
    q = float(quantity)
    if q <= 0:
        return 0.0
    if utility_mode == "linear":
        return value * q
    if utility_mode == "concave_separable":
        return value * math.sqrt(q)
    if utility_mode == "complementary_bundle":
        return value * math.sqrt(q)
    raise ValueError(f"unknown utility_mode: {utility_mode}")


def utility_for_bundle(preferences: list[float], bundle: list[Quantity], utility_mode: str = "linear",
                       money_good_index: Optional[int] = None) -> float:
    total = 0.0
    for idx, (q, v) in enumerate(zip(bundle, preferences)):
        if money_good_index is not None and idx == money_good_index:
            total += float(v) * max(0.0, float(q))   # money is a linear numeraire (no diminishing returns)
        else:
            total += _utility_component(v, q, utility_mode)
    if utility_mode == "complementary_bundle":
        positive_goods = sum(1 for q in bundle if float(q) > 0)
        if positive_goods >= 2:
            total += 0.05 * positive_goods * sum(preferences) / max(1, len(preferences))
    return total


def bundle_buyer_utility(spec: BundleUtilitySpec, bundle_row: list[Quantity]) -> float:
    """Leontief + quasi-linear buyer objective (bundle-under-budget worlds).

    bundle_value iff the row holds >= 1 unit of every required component,
    else the components contribute 0; money contributes linearly.
    """
    complete = all(float(bundle_row[c - 1]) >= 1.0 - 1e-9 for c in spec.required_components)
    money = max(0.0, float(bundle_row[spec.money_resource - 1]))
    return (spec.bundle_value if complete else 0.0) + money


def agent_utility_for_bundle_row(world: "ExchangeWorld", agent_index: int, bundle_row: list[Quantity]) -> float:
    """Utility of one agent's bundle row, honoring the buyer's Leontief objective on bundle worlds."""
    spec = world.bundle_utility
    if spec is not None and agent_index == spec.buyer_agent - 1:
        return bundle_buyer_utility(spec, bundle_row)
    return utility_for_bundle(world.preferences[agent_index], bundle_row, world.utility_mode, world.money_good_index)


def make_exchange_world(
    num_agents: int = 10,
    num_resources: int = 10,
    units_per_home_resource: int = 10,
    seed: int = 0,
    utility_mode: str = "linear",
    institution_pressure: Optional[InstitutionPressureConfig] = None,
    with_money: bool = False,
    money_units_per_agent: int = 20,
) -> ExchangeWorld:
    """Create a reproducible 10x10 hidden-preference endowment economy.

    Agent i initially owns only resource i mod R. Preferences are private and
    heterogeneous, with enough variation to create gains from exchange.

    If ``with_money`` is set, one extra good ("money") is appended: a transferable
    numeraire owned by every agent (``money_units_per_agent`` each) and valued linearly
    at 1.0 by everyone, so money transfers are pure side-payments.
    """
    if num_agents <= 0 or num_resources <= 0:
        raise ValueError("num_agents and num_resources must be positive")
    rng = random.Random(seed)
    allocation = [[0 for _ in range(num_resources)] for _ in range(num_agents)]
    for i in range(num_agents):
        allocation[i][i % num_resources] = units_per_home_resource

    preferences: FloatMatrix = []
    for i in range(num_agents):
        row = []
        for r in range(num_resources):
            base = 0.5 + 4.5 * rng.random()
            # Give each agent a distinct taste peak away from its endowment often
            # enough that mutually beneficial swaps exist.
            peak = (i * 3 + 2) % num_resources
            if r == peak:
                base += 3.0
            row.append(round(base, 3))
        preferences.append(row)

    money_good_index: Optional[int] = None
    resource_names: list[str] = [f"r{i + 1}" for i in range(num_resources)]
    if with_money:
        money_good_index = num_resources
        resource_names.append("money")
        for i in range(num_agents):
            allocation[i].append(money_units_per_agent)
            preferences[i].append(1.0)

    return ExchangeWorld(
        allocation=allocation,
        preferences=preferences,
        resource_names=resource_names,
        utility_mode=utility_mode,
        institution_pressure=institution_pressure or InstitutionPressureConfig(),
        money_good_index=money_good_index,
    )


def make_ring_cycle_world(
    num_agents: int = 12,
    cycle_length: int = 3,
    *,
    units_per_home_resource: int = 10,
    wanted_value: float = 1.0,
    own_value: float = 0.5,
    other_value: float = 0.01,
    utility_mode: str = "linear",
    institution_pressure: Optional[InstitutionPressureConfig] = None,
    seed: int = 0,  # accepted for interface parity; the world is deterministic
) -> ExchangeWorld:
    """Disjoint directed k-cycles where trade surplus REQUIRES a k-party cycle.

    Agents are partitioned into ``num_agents / cycle_length`` disjoint directed cycles.
    Agent ``i`` owns good ``i`` and wants only the *next* good in its cycle. Values are
    calibrated so that giving up one's own good (``own_value``) for a non-wanted good
    (``other_value``) is strictly IR-negative, while receiving one's wanted good
    (``wanted_value``) is IR-positive. Consequences (verify with the provider-free
    oracles):

    - ``cycle_length == 2``: pairwise swaps are individually rational (bilateral suffices).
    - ``cycle_length >= 3``: NO bilateral swap is IR (every pair leaves someone worse
      off); only the full k-cycle clears, so bilateral IR surplus is zero.

    ``num_agents`` must be divisible by ``cycle_length`` (so market size can be held
    fixed while ``cycle_length`` varies). Requires ``wanted_value > own_value > other_value``.
    """
    if num_agents <= 0 or cycle_length < 2:
        raise ValueError("num_agents must be > 0 and cycle_length must be >= 2")
    if num_agents % cycle_length != 0:
        raise ValueError(
            f"num_agents ({num_agents}) must be divisible by cycle_length ({cycle_length})"
        )
    if not (wanted_value > own_value > other_value >= 0):
        raise ValueError("require wanted_value > own_value > other_value >= 0")
    num_resources = num_agents
    allocation = [[0 for _ in range(num_resources)] for _ in range(num_agents)]
    preferences: FloatMatrix = []
    for i in range(num_agents):
        allocation[i][i] = units_per_home_resource  # agent i owns good i
    for i in range(num_agents):
        cycle_base = (i // cycle_length) * cycle_length
        pos = i % cycle_length
        wanted = cycle_base + ((pos + 1) % cycle_length)  # next good in this cycle
        row = [other_value] * num_resources
        row[i] = own_value          # one's own good is worth more than a random good
        row[wanted] = wanted_value  # ... but the next good in the cycle is worth most
        preferences.append([round(v, 4) for v in row])
    return ExchangeWorld(
        allocation=allocation,
        preferences=preferences,
        resource_names=[f"r{i + 1}" for i in range(num_resources)],
        utility_mode=utility_mode,
        institution_pressure=institution_pressure or InstitutionPressureConfig(),
    )


@dataclass(frozen=True)
class BundleMinCostSolution:
    """Full-information min-cost bundle assignment (the bundle world's welfare ceiling)."""

    min_cost: float
    assignment: dict[int, int]  # required component -> cheapest seller agent id
    feasible_within_budget: bool
    optimal_welfare_gain: float  # bundle_value - min_cost (prices are welfare-neutral transfers)


def solve_bundle_min_cost(world: ExchangeWorld) -> BundleMinCostSolution:
    spec = world.bundle_utility
    if spec is None:
        raise ValueError("solve_bundle_min_cost requires a bundle-under-budget world")
    assignment: dict[int, int] = {}
    min_cost = 0.0
    for component in spec.required_components:
        candidates = [
            (world.preferences[i][component - 1], i + 1)
            for i in range(world.num_agents)
            if i + 1 != spec.buyer_agent and world.allocation[i][component - 1] >= 1
        ]
        if not candidates:
            raise ValueError(f"no seller holds required component {component}")
        cost, seller_id = min(candidates)
        assignment[component] = seller_id
        min_cost += float(cost)
    return BundleMinCostSolution(
        min_cost=min_cost,
        assignment=assignment,
        feasible_within_budget=min_cost <= spec.budget,
        optimal_welfare_gain=spec.bundle_value - min_cost,
    )


@dataclass(frozen=True)
class BundleEpisodeMetrics:
    """A2 construction + B1 mandate-fidelity outcomes for one bundle episode."""

    bundle_completed: bool
    spend: float
    over_budget: bool  # B1 mandate violation
    stranded_spend: float  # money spent while the bundle stayed incomplete
    welfare_gain: float
    optimal_welfare_gain: float
    welfare_ratio: float


def summarize_bundle_episode(initial_allocation: Matrix, world: ExchangeWorld) -> BundleEpisodeMetrics:
    spec = world.bundle_utility
    if spec is None:
        raise ValueError("summarize_bundle_episode requires a bundle-under-budget world")
    buyer = spec.buyer_agent - 1
    money = spec.money_resource - 1
    completed = all(float(world.allocation[buyer][c - 1]) >= 1.0 - 1e-9 for c in spec.required_components)
    spend = float(initial_allocation[buyer][money]) - float(world.allocation[buyer][money])
    initial_welfare = sum(
        agent_utility_for_bundle_row(world, i, initial_allocation[i]) for i in range(world.num_agents)
    )
    welfare_gain = total_welfare(world) - initial_welfare
    oracle = solve_bundle_min_cost(world)
    ratio = welfare_gain / oracle.optimal_welfare_gain if oracle.optimal_welfare_gain > 1e-9 else 0.0
    return BundleEpisodeMetrics(
        bundle_completed=completed,
        spend=spend,
        over_budget=spend > spec.budget + 1e-9,
        stranded_spend=spend if (spend > 1e-9 and not completed) else 0.0,
        welfare_gain=welfare_gain,
        optimal_welfare_gain=oracle.optimal_welfare_gain,
        welfare_ratio=ratio,
    )


def make_bundle_under_budget_world(config: ExchangeExperimentConfig) -> ExchangeWorld:
    """Buyer-with-budget vs component-holding sellers (see the 2026-07-01 bundle spec).

    The buyer is endowed with exactly ``budget`` units of money and no components;
    each seller holds ``units_per_home_resource`` of one required component and
    values it at a private reservation cost drawn from ``seller_cost_range``.
    """
    spec = config.bundle_spec
    layout = config.seller_layout
    if spec is None or layout is None:
        raise ValueError("world_type='bundle_under_budget' requires bundle_spec and seller_layout")
    n, r = config.num_agents, config.num_resources
    _idx(spec.buyer_agent, n, "bundle buyer")
    _idx(spec.money_resource, r, "bundle money resource")
    for component in spec.required_components:
        _idx(component, r, "bundle required component")
        if component == spec.money_resource:
            raise ValueError("money_resource cannot be a required component")
    if spec.bundle_value <= spec.budget:
        raise ValueError(
            f"bundle_value ({spec.bundle_value}) must exceed budget ({spec.budget}) "
            "or completing the bundle can never be worth the mandate"
        )
    sellers_by_component: dict[int, list[int]] = {c: [] for c in spec.required_components}
    for seller_id, component in sorted(layout.component_by_seller.items()):
        _idx(seller_id, n, "seller")
        if seller_id == spec.buyer_agent:
            raise ValueError("the buyer cannot also be a seller")
        if component not in sellers_by_component:
            raise ValueError(f"seller {seller_id} holds component {component} which is not required")
        sellers_by_component[component].append(seller_id)
    missing = [c for c, holders in sellers_by_component.items() if not holders]
    if missing:
        raise ValueError(f"required components without any seller: {missing}")

    rng = random.Random(config.seed)
    low, high = layout.seller_cost_range
    allocation: Matrix = [[0 for _ in range(r)] for _ in range(n)]
    preferences: FloatMatrix = [[0.0 for _ in range(r)] for _ in range(n)]
    buyer = spec.buyer_agent - 1
    money = spec.money_resource - 1
    allocation[buyer][money] = int(spec.budget) if float(spec.budget).is_integer() else float(spec.budget)
    for i in range(n):
        preferences[i][money] = 1.0
    for seller_id, component in sorted(layout.component_by_seller.items()):
        i = seller_id - 1
        allocation[i][component - 1] = config.units_per_home_resource
        preferences[i][component - 1] = round(low + (high - low) * rng.random(), 3)

    resource_names = [f"r{i + 1}" for i in range(r)]
    resource_names[money] = "money"
    world = ExchangeWorld(
        allocation=allocation,
        preferences=preferences,
        resource_names=resource_names,
        utility_mode="linear",  # sellers are quasi-linear; the buyer routes through bundle_utility
        institution_pressure=config.institution_pressure,
        money_good_index=money,
        bundle_utility=spec,
    )
    oracle = solve_bundle_min_cost(world)
    if oracle.min_cost >= spec.budget:
        raise ValueError(
            f"budget ({spec.budget}) must exceed the min-cost bundle ({oracle.min_cost}) "
            "or no within-budget complete bundle exists"
        )
    return world


def _optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    return int(value)


def _protocol_config_from_dict(raw: dict[str, Any] | None) -> ProtocolConfig:
    data = raw or {}
    return ProtocolConfig(
        name=str(data.get("name", "universal_public_action")),
        information_reveal_profile=str(data.get("information_reveal_profile", "legacy")),
        visibility_mode=str(data.get("visibility_mode", "full_public")),
        visible_agents_per_agent=_optional_int(data.get("visible_agents_per_agent")),
        visibility_seed=int(data.get("visibility_seed", 0)),
        public_broadcast=bool(data.get("public_broadcast", True)),
        communication_scope=str(data.get("communication_scope", "all")),
        show_full_allocation=bool(data.get("show_full_allocation", True)),
        show_resource_totals=bool(data.get("show_resource_totals", True)),
        direct_contact_scope=str(data.get("direct_contact_scope", "unrestricted")),
        response_scope=str(data.get("response_scope", "all")),
        settlement_row_limit=_optional_int(data.get("settlement_row_limit")),
        strict_self_interest=bool(data.get("strict_self_interest", False)),
        require_final_public_state_update_for_institutions=bool(
            data.get("require_final_public_state_update_for_institutions", True)
        ),
        private_acceptance_check=bool(data.get("private_acceptance_check", False)),
        private_acceptance_mode=str(data.get("private_acceptance_mode", "llm_structured")),
        private_acceptance_context=str(data.get("private_acceptance_context", "minimal")),
        atomic_commit=bool(data.get("atomic_commit", False)),
        ir_enforce=bool(data.get("ir_enforce", False)),
        partial_clearing=bool(data.get("partial_clearing", False)),
        anti_anchor_mechanism_example=str(data.get("anti_anchor_mechanism_example", "")),
        defection_rate=float(data.get("defection_rate", 0.0)),
        defection_seed=int(data.get("defection_seed", 0)),
        reveal_all_private_values=bool(data.get("reveal_all_private_values", False)),
    )


def _institution_pressure_from_dict(raw: dict[str, Any] | None) -> InstitutionPressureConfig:
    data = raw or {}
    return InstitutionPressureConfig(
        search_cost_per_public_round=float(data.get("search_cost_per_public_round", 0.0)),
        search_cost_per_contacted_agent=float(data.get("search_cost_per_contacted_agent", 0.0)),
        contact_expansion_cost=float(data.get("contact_expansion_cost", 0.0)),
        standing_rule_bonus_or_cost_saving=float(data.get("standing_rule_bonus_or_cost_saving", 0.0)),
        preference_shock_frequency=int(data.get("preference_shock_frequency", 0)),
        recurring_demand_mode=str(data.get("recurring_demand_mode", "none")),
    )


def _bundle_spec_from_dict(raw: dict[str, Any] | None) -> Optional[BundleUtilitySpec]:
    if not raw:
        return None
    required = raw.get("required_components")
    if not isinstance(required, list) or not required:
        raise ValueError("bundle_spec.required_components must be a non-empty list")
    return BundleUtilitySpec(
        buyer_agent=int(raw["buyer_agent"]),
        money_resource=int(raw["money_resource"]),
        required_components=[int(c) for c in required],
        bundle_value=float(raw["bundle_value"]),
        budget=float(raw["budget"]),
    )


def _seller_layout_from_dict(raw: dict[str, Any] | None) -> Optional[SellerLayoutConfig]:
    if not raw:
        return None
    mapping = raw.get("component_by_seller")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("seller_layout.component_by_seller must be a non-empty mapping")
    cost_range = raw.get("seller_cost_range")
    if not isinstance(cost_range, (list, tuple)) or len(cost_range) != 2:
        raise ValueError("seller_layout.seller_cost_range must be [low, high]")
    low, high = float(cost_range[0]), float(cost_range[1])
    if not (0 < low <= high):
        raise ValueError("seller_layout.seller_cost_range must satisfy 0 < low <= high")
    return SellerLayoutConfig(
        component_by_seller={int(k): int(v) for k, v in mapping.items()},
        seller_cost_range=(low, high),
    )


def _experiment_config_from_dict(raw: dict[str, Any]) -> ExchangeExperimentConfig:
    controllers = raw.get("controllers", [1, 3, 5])
    if not isinstance(controllers, list):
        raise ValueError("controllers must be a list")
    return ExchangeExperimentConfig(
        name=str(raw.get("name", "exchange_experiment")),
        description=str(raw.get("description", "")),
        num_agents=int(raw.get("num_agents", 10)),
        num_resources=int(raw.get("num_resources", 10)),
        units_per_home_resource=int(raw.get("units_per_home_resource", 10)),
        seed=int(raw.get("seed", 23)),
        rounds=int(raw.get("rounds", 300)),
        controllers=[int(x) for x in controllers],
        protocol=_protocol_config_from_dict(raw.get("protocol")),
        utility_mode=str(raw.get("utility_mode", "linear")),
        institution_pressure=_institution_pressure_from_dict(raw.get("institution_pressure")),
        world_type=str(raw.get("world_type", "procedural")),
        cycle_length=_optional_int(raw.get("cycle_length")),
        with_money=bool(raw.get("with_money", False)),
        bundle_spec=_bundle_spec_from_dict(raw.get("bundle_spec")),
        seller_layout=_seller_layout_from_dict(raw.get("seller_layout")),
    )


def load_experiment_config(path: str | Path) -> ExchangeExperimentConfig:
    """Load an experiment config from JSON."""
    config_path = Path(path)
    raw = json.loads(config_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("experiment config must be a JSON object")
    return _experiment_config_from_dict(raw)


def override_experiment_config_runtime(
    config: ExchangeExperimentConfig,
    *,
    rounds: Optional[int] = None,
    controllers: Optional[list[int]] = None,
) -> ExchangeExperimentConfig:
    """Return a runtime-only config variant for probe runs.

    Experiment configs remain the source of truth for formal runs. This helper is
    explicit so shortened diagnostics do not silently mutate a named treatment.
    """
    updates: dict[str, Any] = {}
    if rounds is not None:
        if rounds < 1:
            raise ValueError("rounds override must be positive")
        updates["rounds"] = int(rounds)
    if controllers is not None:
        if not controllers:
            raise ValueError("controllers override must not be empty")
        updates["controllers"] = [int(x) for x in controllers]
    return replace(config, **updates) if updates else config


def make_world_from_config(config: ExchangeExperimentConfig) -> ExchangeWorld:
    if config.world_type == "bundle_under_budget":
        return make_bundle_under_budget_world(config)
    if config.world_type == "ring_cycle":
        return make_ring_cycle_world(
            num_agents=config.num_agents,
            cycle_length=config.cycle_length or 2,
            units_per_home_resource=config.units_per_home_resource,
            utility_mode=config.utility_mode,
            institution_pressure=config.institution_pressure,
            seed=config.seed,
        )
    return make_exchange_world(
        num_agents=config.num_agents,
        num_resources=config.num_resources,
        units_per_home_resource=config.units_per_home_resource,
        seed=config.seed,
        utility_mode=config.utility_mode,
        institution_pressure=config.institution_pressure,
        with_money=config.with_money,
    )


def visible_agents_for(
    protocol: ProtocolConfig,
    world: ExchangeWorld,
    agent_id: int,
) -> list[int]:
    """Return deterministic contact visibility for the current protocol."""
    _idx(agent_id, world.num_agents, "agent")
    candidates = [aid for aid in range(1, world.num_agents + 1) if aid != agent_id]
    if protocol.visibility_mode != "limited_contact":
        return candidates
    k = protocol.visible_agents_per_agent
    if k is None:
        return candidates
    if k <= 0:
        return []
    rng = random.Random(protocol.visibility_seed + agent_id * 7919 + world.num_agents * 101 + world.num_resources)
    shuffled = candidates[:]
    rng.shuffle(shuffled)
    return sorted(shuffled[: min(k, len(shuffled))])


def _communication_agent_ids_for(
    protocol: ProtocolConfig,
    world: ExchangeWorld,
    controller_id: int,
) -> list[int]:
    if protocol.communication_scope in {"controller_contacts", "visible_only"}:
        return sorted({controller_id, *visible_agents_for(protocol, world, controller_id)})
    if protocol.public_broadcast:
        return list(range(1, world.num_agents + 1))
    return sorted({controller_id, *visible_agents_for(protocol, world, controller_id)})


def _response_agent_ids_for(
    protocol: ProtocolConfig,
    world: ExchangeWorld,
    controller_id: int,
    proposal_text: str = "",
    communication_texts: Optional[dict[int, str]] = None,
) -> list[int]:
    if protocol.response_scope == "visible_only":
        return visible_agents_for(protocol, world, controller_id)
    if protocol.response_scope == "solicited_public":
        if protocol.public_broadcast:
            controller_texts = [
                str((communication_texts or {}).get(controller_id, "")),
                str((communication_texts or {}).get(str(controller_id), "")),
                proposal_text,
            ]
            targeted_set: set[int] = set()
            for text in controller_texts:
                targeted = _targeted_public_response_agent_ids(
                    text,
                    num_agents=world.num_agents,
                    controller_id=controller_id,
                )
                targeted_set.update(targeted)
            if targeted_set:
                return sorted(targeted_set)
            if _has_functional_public_solicitation(
                communication_texts or {},
                controller_id=controller_id,
                proposal_text=proposal_text,
            ):
                return [aid for aid in range(1, world.num_agents + 1) if aid != controller_id]
        return visible_agents_for(protocol, world, controller_id)
    return [aid for aid in range(1, world.num_agents + 1) if aid != controller_id]


def resource_totals(allocation: Matrix) -> list[Quantity]:
    if not allocation:
        return []
    return [sum(row[r] for row in allocation) for r in range(len(allocation[0]))]


def _normalize_institutional_updates(raw: Any) -> list[dict[str, Any]]:
    """Preserve arbitrary public institution records without a mechanism taxonomy."""
    if raw in (None, ""):
        return []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if not isinstance(raw, list):
        raw = [raw]
    updates: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            updates.append({"text": item})
        elif isinstance(item, dict):
            updates.append(deepcopy(item))
        else:
            updates.append({"text": str(item)})
    return updates


def _institution_identifier(record: dict[str, Any]) -> Optional[str]:
    for key in ("id", "rule_id", "institution_id", "name", "label"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _institution_op(record: dict[str, Any]) -> str:
    value = record.get("op", record.get("operation", record.get("action", record.get("status", "active"))))
    return str(value).strip().lower().replace("-", "_")


def active_institutions(world: ExchangeWorld, round_index: Optional[int] = None) -> list[dict[str, Any]]:
    inactive = {"inactive", "retired", "removed", "deleted", "expired", "superseded", "rejected"}
    out: list[dict[str, Any]] = []
    for record in world.institutions:
        status = str(record.get("status", "active")).strip().lower().replace("-", "_")
        if status in inactive:
            continue
        expires = record.get("expires_after_round", record.get("expires_round"))
        if round_index is not None and expires not in (None, ""):
            try:
                if int(expires) < round_index:
                    continue
            except (TypeError, ValueError):
                pass
        out.append(deepcopy(record))
    return out


def apply_institutional_updates(
    world: ExchangeWorld,
    updates: list[dict[str, Any]],
    round_index: int,
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    retire_ops = {"retire", "remove", "delete", "expire", "inactive", "retired", "removed", "deleted", "expired"}
    replace_ops = {"amend", "update", "replace", "supersede"}
    for raw in updates:
        record = deepcopy(raw)
        record.setdefault("source_round", round_index)
        op = _institution_op(record)
        ident = _institution_identifier(record)
        if ident and op in retire_ops:
            for existing in world.institutions:
                if _institution_identifier(existing) == ident:
                    existing["status"] = "retired"
                    existing["retired_round"] = round_index
            record["status"] = "retired"
        elif ident and op in replace_ops:
            for existing in world.institutions:
                if _institution_identifier(existing) == ident:
                    existing["status"] = "superseded"
                    existing["superseded_round"] = round_index
            record.setdefault("status", "active")
        else:
            record.setdefault("status", "active")
        world.institutions.append(record)
        applied.append(deepcopy(record))
    return applied


def apply_institutional_costs(
    world: ExchangeWorld,
    pressure: InstitutionPressureConfig,
    round_index: int,
    contacted_agent_count: Optional[int] = None,
) -> dict[str, Any]:
    active = active_institutions(world, round_index)
    if pressure.search_cost_per_contacted_agent:
        contact_count = world.num_agents if contacted_agent_count is None else max(0, int(contacted_agent_count))
        search_cost_total = pressure.search_cost_per_contacted_agent * contact_count
        standing_saving = 0.0
        search_cost_basis = "prompted_responders"
    else:
        contact_count = world.num_agents
        search_cost_total = pressure.search_cost_per_public_round * world.num_agents
        standing_saving = pressure.standing_rule_bonus_or_cost_saving * len(active)
        search_cost_basis = "flat_public_round"
    net_cost = max(0.0, search_cost_total - standing_saving)
    return {
        "round": round_index,
        "search_cost_total": search_cost_total,
        "search_cost_basis": search_cost_basis,
        "contacted_agent_count": contact_count,
        "standing_rule_saving": standing_saving,
        "net_coordination_cost": net_cost,
        "active_institutions": len(active),
    }


_PUBLIC_ACTION_SECTIONS = (
    "ADDRESSEES",
    "MESSAGE",
    "RESPONSE REQUEST",
    "SETTLEMENT",
    "CONSENT CONDITIONS",
    "PUBLIC STATE UPDATE",
    "NO-TRANSFER FALLBACK",
)


def _public_action_section(text: str, section: str) -> str:
    """Extract a PUBLIC ACTION envelope section by heading."""
    headings = "|".join(re.escape(name) + ":" for name in _PUBLIC_ACTION_SECTIONS if name != section)
    pattern = re.compile(rf"{re.escape(section)}:\s*(.*?)(?=\n(?:{headings})|\Z)", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _has_public_action_section(text: str, section: str) -> bool:
    return bool(re.search(rf"(?im)^\s*{re.escape(section)}\s*:", text or ""))


def _section_is_none(text: str) -> bool:
    normalized = re.sub(r"[`\s.]+", " ", text or "").strip().lower()
    return normalized in {
        "",
        "none",
        "no public state update",
        "no update",
        "no response request",
        "no response requested",
        "no request",
        "not requested",
        "n/a",
    }


def _final_public_state_update_text(transcript: RoundTranscript) -> str:
    return _public_action_section(transcript.final_text, "PUBLIC STATE UPDATE")


def _atomic_commit_final_text(proposal_text: str) -> str:
    settlement = _public_action_section(proposal_text, "SETTLEMENT")
    public_state = _public_action_section(proposal_text, "PUBLIC STATE UPDATE")
    if _section_is_none(settlement):
        settlement = "none"
    if _section_is_none(public_state):
        public_state = "none"
    return (
        "PUBLIC ACTION\n"
        "ADDRESSEES:\n"
        "agents whose exact proposal consent is required\n"
        "MESSAGE:\n"
        "Atomic commit: no controller amendment phase. Execute only the exact proposal rows that received explicit consent.\n"
        "RESPONSE REQUEST:\n"
        "none\n"
        "SETTLEMENT:\n"
        f"{settlement}\n"
        "CONSENT CONDITIONS:\n"
        "Every debited agent must have explicitly consented to the exact proposal terms in the response phase.\n"
        "PUBLIC STATE UPDATE:\n"
        f"{public_state}\n"
        "NO-TRANSFER FALLBACK:\n"
        "If any required exact consent is missing, no transfer or public-state update is finalized."
    )


def enforce_transcript_support(
    world: ExchangeWorld,
    transcript: RoundTranscript,
    mechanism: CompiledMechanism,
    protocol: Optional[ProtocolConfig] = None,
) -> CompiledMechanism:
    """Apply deterministic support checks that should not depend on verifier laxness."""
    del world  # reserved for future deterministic support checks
    protocol = protocol or ProtocolConfig()
    updates = mechanism.institutional_updates
    if protocol.require_final_public_state_update_for_institutions:
        final_state_update = _final_public_state_update_text(transcript)
        if _section_is_none(final_state_update):
            updates = []
    if updates is mechanism.institutional_updates:
        return mechanism
    return replace(mechanism, institutional_updates=updates)


def _debited_agent_ids(mechanism: CompiledMechanism) -> list[int]:
    return sorted({tr.from_agent for tr in mechanism.transfers})


def _private_acceptance_approved(text: str) -> bool:
    try:
        obj = _extract_json(text)
    except Exception:
        return False
    value = obj.get("approve", obj.get("approved", obj.get("accept", obj.get("accepted"))))
    return value is True


def _delta_sign(value: float, eps: float = 1e-9) -> str:
    if value > eps:
        return "positive"
    if value < -eps:
        return "negative"
    return "zero"


def _agent_transfer_rows(mechanism: CompiledMechanism, agent_id: int, direction: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tr in mechanism.transfers:
        if direction == "debit" and tr.from_agent == agent_id:
            rows.append({"resource": f"r{tr.resource}", "quantity": tr.quantity})
        elif direction == "credit" and tr.to_agent == agent_id:
            rows.append({"resource": f"r{tr.resource}", "quantity": tr.quantity})
    return rows


def _normalized_private_rows(raw: Any) -> list[tuple[int, float]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        return []
    rows: list[tuple[int, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        resource = item.get("resource", item.get("r"))
        quantity = item.get("quantity", item.get("q"))
        if resource is None or quantity is None:
            continue
        rid = int(str(resource).strip().lower().removeprefix("r"))
        rows.append((rid, float(_quantity_value(quantity))))
    return sorted(rows)


def _actual_private_rows(mechanism: CompiledMechanism, agent_id: int, direction: str) -> list[tuple[int, float]]:
    return sorted(
        (int(str(row["resource"]).removeprefix("r")), float(row["quantity"]))
        for row in _agent_transfer_rows(mechanism, agent_id, direction)
    )


def _rows_match(actual: list[tuple[int, float]], claimed: list[tuple[int, float]]) -> bool:
    if len(actual) != len(claimed):
        return False
    return all(ar == cr and math.isclose(aq, cq, rel_tol=1e-9, abs_tol=1e-9) for (ar, aq), (cr, cq) in zip(actual, claimed))


def audit_private_acceptance_decision(
    world: ExchangeWorld,
    mechanism: CompiledMechanism,
    agent_id: int,
    decision_text: str,
    *,
    force_oracle: bool = False,
) -> PrivateAcceptanceAudit:
    actual_delta = utility_delta_for_mechanism(world, mechanism, agent_id)
    actual_sign = _delta_sign(actual_delta)
    parsed = True
    try:
        obj = _extract_json(decision_text) if not force_oracle else {}
        if not isinstance(obj, dict):
            obj = {}
            parsed = False
    except Exception:
        obj = {}
        parsed = False

    if force_oracle:
        approve = actual_sign == "positive"
        claimed_sign = actual_sign
        counterpart_present = True
        same_bundle = True
        claimed_debits = _actual_private_rows(mechanism, agent_id, "debit")
        claimed_credits = _actual_private_rows(mechanism, agent_id, "credit")
        reason = "deterministic oracle approval" if approve else "deterministic oracle rejection"
    else:
        approve = _private_acceptance_approved(decision_text)
        claimed_sign = str(obj.get("claimed_delta_sign", "")).strip().lower()
        counterpart_present = bool(obj.get("counterpart_transfers_present", False))
        same_bundle = bool(obj.get("same_bundle_authorized", False))
        reason = str(obj.get("reason", ""))
        try:
            claimed_debits = _normalized_private_rows(obj.get("own_debits_seen"))
            claimed_credits = _normalized_private_rows(obj.get("own_credits_seen"))
        except (TypeError, ValueError):
            parsed = False
            approve = False
            claimed_sign = ""
            counterpart_present = False
            same_bundle = False
            claimed_debits = []
            claimed_credits = []
            reason = reason or "malformed private acceptance quantity rows"

    actual_debits = _actual_private_rows(mechanism, agent_id, "debit")
    actual_credits = _actual_private_rows(mechanism, agent_id, "credit")
    debit_rows_match = _rows_match(actual_debits, claimed_debits)
    credit_rows_match = _rows_match(actual_credits, claimed_credits)
    quantity_match = debit_rows_match and credit_rows_match
    sign_match = claimed_sign == actual_sign
    should_approve = actual_sign == "positive" and counterpart_present and same_bundle
    approval_correct = approve == should_approve

    if not parsed:
        error_family = "malformed_private_acceptance"
    elif approval_correct and sign_match and quantity_match:
        error_family = "none"
    elif approve and actual_sign == "negative":
        error_family = "wrong_sign_positive_approval"
    elif approve and actual_sign == "zero":
        error_family = "zero_delta_positive_approval"
    elif not quantity_match:
        error_family = "bundle_row_or_quantity_mismatch"
    elif not sign_match:
        error_family = "claimed_delta_sign_mismatch"
    elif not counterpart_present or not same_bundle:
        error_family = "counterpart_or_authorization_mismatch"
    else:
        error_family = "approval_policy_mismatch"

    return PrivateAcceptanceAudit(
        agent_id=agent_id,
        approve=approve,
        actual_delta=actual_delta,
        actual_delta_sign=actual_sign,
        claimed_delta_sign=claimed_sign,
        sign_match=sign_match,
        debit_rows_match=debit_rows_match,
        credit_rows_match=credit_rows_match,
        quantity_match=quantity_match,
        counterpart_transfers_present=counterpart_present,
        same_bundle_authorized=same_bundle,
        approval_correct=approval_correct,
        error_family=error_family,
        reason=reason,
    )


def _private_acceptance_rejection(
    mechanism: CompiledMechanism,
    rejected: list[int],
) -> CompiledMechanism:
    names = ", ".join(f"a{aid}" for aid in rejected)
    return replace(
        mechanism,
        label="private_acceptance_rejected",
        summary=f"private acceptance rejected by {names}; no transfers executed",
        transfers=[],
        consenting_agents=[],
        institutional_updates=[],
        confidence=0.0,
    )


def enforce_private_acceptance(
    mechanism: CompiledMechanism,
    acceptance_texts: dict[int, str],
    *,
    world: Optional[ExchangeWorld] = None,
    mode: str = "llm_structured",
) -> CompiledMechanism | tuple[CompiledMechanism, list[PrivateAcceptanceAudit]]:
    """Apply the private acceptance audit.

    Default LLM modes are fail-open for malformed audit text: malformed output is
    still recorded in the audit, but it is not treated as an automatic rejection.
    Use llm_structured_strict when the experiment intentionally wants fail-closed
    parsing.
    """
    debited_agents = _debited_agent_ids(mechanism)
    if world is not None:
        audits = [
            audit_private_acceptance_decision(
                world,
                mechanism,
                aid,
                acceptance_texts.get(aid, ""),
                force_oracle=(mode == "deterministic_oracle"),
            )
            for aid in debited_agents
        ]
        if mode == "deterministic_oracle":
            rejected = [audit.agent_id for audit in audits if not audit.approve]
        elif mode == "hybrid_block_bad":
            rejected = [
                audit.agent_id
                for audit in audits
                if (not audit.approve) or audit.actual_delta <= 1e-9 or not audit.counterpart_transfers_present
            ]
        elif mode in {"llm_structured", "llm"}:
            rejected = [
                audit.agent_id
                for audit in audits
                if (not audit.approve) and audit.error_family != "malformed_private_acceptance"
            ]
        elif mode in {"llm_structured_strict", "llm_strict"}:
            rejected = [audit.agent_id for audit in audits if not audit.approve]
        elif mode == "off":
            rejected = []
        else:
            raise ValueError(f"unknown private_acceptance_mode: {mode}")
        if rejected:
            return _private_acceptance_rejection(mechanism, rejected), audits
        return mechanism, audits

    rejected = [
        aid
        for aid in debited_agents
        if not _private_acceptance_approved(acceptance_texts.get(aid, ""))
    ]
    if not rejected:
        return mechanism
    return _private_acceptance_rejection(mechanism, rejected)


def utility_vector(world: ExchangeWorld, allocation: Optional[Matrix] = None) -> list[float]:
    return [world.utility(i + 1, allocation) for i in range(world.num_agents)]


def total_welfare(world: ExchangeWorld, allocation: Optional[Matrix] = None) -> float:
    return sum(utility_vector(world, allocation))


def gini(values: list[float]) -> float:
    if not values:
        return 0.0
    vals = sorted(max(v, 0.0) for v in values)
    total = sum(vals)
    if total <= 0:
        return 0.0
    n = len(vals)
    weighted = sum((i + 1) * v for i, v in enumerate(vals))
    return (2 * weighted) / (n * total) - (n + 1) / n


def nash_welfare(world: ExchangeWorld, allocation: Optional[Matrix] = None) -> float:
    vals = [max(v, 1e-9) for v in utility_vector(world, allocation)]
    return sum(math.log(v) for v in vals)


def greedy_social_optimum(world: ExchangeWorld) -> Matrix:
    """Utilitarian upper benchmark: each unit goes to the agent valuing it most."""
    if world.bundle_utility is not None:
        return social_optimum(world)  # Leontief buyer invisible to per-resource values
    totals = resource_totals(world.allocation)
    out = [[0 for _ in range(world.num_resources)] for _ in range(world.num_agents)]
    for r, supply in enumerate(totals):
        best_i = max(range(world.num_agents), key=lambda i: world.preferences[i][r])
        out[best_i][r] = supply
    return out


def _marginal_gain_for_resource(
    world: ExchangeWorld,
    allocation: Matrix,
    agent_index: int,
    resource_index: int,
    quantity: float,
) -> float:
    before = allocation[agent_index][:]
    after = before[:]
    after[resource_index] += quantity
    return agent_utility_for_bundle_row(world, agent_index, after) - agent_utility_for_bundle_row(
        world, agent_index, before
    )


def social_optimum(world: ExchangeWorld, granularity: float = 1.0) -> Matrix:
    """Deterministic utilitarian benchmark compatible with linear and concave modes."""
    if world.bundle_utility is not None:
        # Leontief buyer: the per-resource greedy allocator sees zero marginal gain
        # until the LAST component, so allocate directly from the min-cost oracle --
        # buyer takes one unit of each required component from its cheapest seller;
        # money stays put (valued 1.0 by everyone, so its allocation is welfare-neutral).
        spec = world.bundle_utility
        out = world.copy_allocation()
        for component, seller_id in solve_bundle_min_cost(world).assignment.items():
            out[seller_id - 1][component - 1] -= 1
            out[spec.buyer_agent - 1][component - 1] += 1
        return out
    if world.utility_mode == "linear":
        return greedy_social_optimum(world)
    if granularity <= 0:
        raise ValueError("granularity must be positive")
    totals = [float(x) for x in resource_totals(world.allocation)]
    out: Matrix = [[0.0 for _ in range(world.num_resources)] for _ in range(world.num_agents)]
    for r, supply in enumerate(totals):
        remaining = supply
        while remaining > 1e-12:
            q = min(granularity, remaining)
            best_i = max(
                range(world.num_agents),
                key=lambda i: (_marginal_gain_for_resource(world, out, i, r, q), -i),
            )
            out[best_i][r] += q
            remaining -= q
    return out


def welfare_ratio(world: ExchangeWorld, allocation: Matrix, optimum: Matrix) -> float:
    initial = total_welfare(world, world.allocation)
    opt = total_welfare(world, optimum)
    cur = total_welfare(world, allocation)
    if opt <= initial + 1e-12:
        return 1.0
    return max(0.0, min(1.0, (cur - initial) / (opt - initial)))


TransferEdge = tuple[int, int, int]


@dataclass(frozen=True)
class OracleSolution:
    name: str
    objective: str
    participants: list[int]
    controller_id: Optional[int]
    allocation: Matrix
    mechanism: CompiledMechanism
    initial_welfare: float
    oracle_welfare: float
    welfare_gain: float
    utility_deltas: dict[int, float]
    row_limit: Optional[int] = None
    success: bool = True
    solver_message: str = ""

    @property
    def individually_rational(self) -> bool:
        return all(delta >= -1e-7 for delta in self.utility_deltas.values())


@dataclass(frozen=True)
class InstitutionOracleSolution:
    name: str
    horizon_rounds: int
    creation_round: int
    active_rounds: int
    per_round_search_cost_total: float
    per_round_standing_rule_saving: float
    standing_rule_saving_total: float
    first_round_bilateral_gain: float
    first_round_protocol_gain: float
    repeated_bilateral_gain: float
    repeated_protocol_gain: float
    exclusive_net_value: float
    parallel_net_value: float
    exclusive_should_create: bool
    parallel_should_create: bool
    institutional_updates: list[dict[str, Any]]


@dataclass(frozen=True)
class PublicSolicitationEnvelope:
    name: str = "bounded_truthful_public_opt_in"
    response_model: str = "truthful_revealed_surplus"
    candidate_scope: str = "public_response_scope"
    max_participants: int = 3
    respondent_limit: Optional[int] = 6
    settlement_row_limit: Optional[int] = None
    solicitation_cost: Optional[float] = None


@dataclass(frozen=True)
class BoundedPublicSolicitationSolution:
    name: str
    controller_id: int
    envelope: PublicSolicitationEnvelope
    visible_baseline: OracleSolution
    solicited_solution: OracleSolution
    candidate_agents: list[int]
    respondent_agents: list[int]
    selected_participants: list[int]
    solicitation_cost: float
    gross_discovery_gain: float
    net_discovery_gain: float
    should_solicit: bool
    solver_message: str = ""


@dataclass(frozen=True)
class L4InferenceConstrainedSolution:
    name: str
    controller_id: int
    observed_agents: list[int]
    inferred_wants: dict[int, list[int]]
    inferred_offers: dict[int, list[int]]
    inferred_edges: list[TransferEdge]
    solution: OracleSolution
    information_basis: str = "public_text_signals_only"


@dataclass(frozen=True)
class BayesianProtocolFrontierSolution:
    name: str
    controller_id: int
    participants: list[int]
    sample_count: int
    candidate_count: int
    selected_mechanism: CompiledMechanism
    expected_gain: float
    realized_gain: float
    realized_individually_rational: bool
    utility_deltas: dict[int, float]
    exact_preference_agent_ids: list[int]
    conditioning_summary: dict[str, Any]
    seed: int

    def information_constrained_ratio(self, denominator_gain: float) -> float:
        if denominator_gain <= 1e-12:
            return 1.0 if self.realized_gain <= 1e-12 else 0.0
        return max(0.0, min(1.0, self.realized_gain / denominator_gain))


@dataclass(frozen=True)
class GreedyBilateralRoundResult:
    round_index: int
    controller_id: int
    participants: list[int]
    applied: bool
    welfare_gain: float
    transfer_rows: int


@dataclass(frozen=True)
class GreedyBilateralFloorResult:
    rounds: list[GreedyBilateralRoundResult]
    initial_welfare: float
    final_welfare: float
    total_welfare_gain: float
    applied_rounds: int


@dataclass(frozen=True)
class ActionRegretComponent:
    step: str
    agent_id: Optional[int]
    oracle_gain: float
    actual_gain: float
    regret: float
    label: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoundRegretDecomposition:
    round_index: int
    controller_id: int
    observed_gain: float
    components: list[ActionRegretComponent]
    protocol_oracle_gain: float
    public_solicitation_gain: float
    public_solicitation_net_lift: float

    def components_by_step(self, step: str) -> list[ActionRegretComponent]:
        return [component for component in self.components if component.step == step]

    @property
    def by_step(self) -> dict[str, ActionRegretComponent]:
        grouped: dict[str, list[ActionRegretComponent]] = {}
        for component in self.components:
            grouped.setdefault(component.step, []).append(component)
        out: dict[str, ActionRegretComponent] = {}
        for step, components in grouped.items():
            regret = sum(component.regret for component in components)
            if step == "acceptance" and regret > 1e-9:
                label = "private_acceptance_errors"
            else:
                label = components[0].label if len(components) == 1 else f"{len(components)}_{step}_components"
            out[step] = ActionRegretComponent(
                step=step,
                agent_id=components[0].agent_id if len(components) == 1 else None,
                oracle_gain=sum(component.oracle_gain for component in components),
                actual_gain=sum(component.actual_gain for component in components),
                regret=regret,
                label=label,
                details={"component_count": len(components)},
            )
        return out

    @property
    def discovery_regret(self) -> float:
        return self.by_step.get("communication", _zero_regret_component("communication")).regret

    @property
    def proposal_regret(self) -> float:
        return self.by_step.get("proposal", _zero_regret_component("proposal")).regret

    @property
    def acceptance_regret(self) -> float:
        return self.by_step.get("acceptance", _zero_regret_component("acceptance")).regret

    @property
    def finalization_regret(self) -> float:
        return self.by_step.get("finalization", _zero_regret_component("finalization")).regret


def _candidate_transfer_edges(world: ExchangeWorld, participants: list[int]) -> list[TransferEdge]:
    pset = set(participants)
    edges: list[TransferEdge] = []
    for from_agent in participants:
        for r in range(1, world.num_resources + 1):
            if float(world.allocation[from_agent - 1][r - 1]) <= 1e-12:
                continue
            for to_agent in participants:
                if to_agent != from_agent and to_agent in pset:
                    edges.append((from_agent, to_agent, r))
    return edges


def _allocation_after_edge_quantities(
    world: ExchangeWorld,
    edges: list[TransferEdge],
    quantities: list[float],
) -> Matrix:
    allocation: Matrix = [[float(x) for x in row] for row in world.copy_allocation()]
    for (from_agent, to_agent, resource), quantity in zip(edges, quantities):
        q = float(quantity)
        if q <= 0:
            continue
        allocation[from_agent - 1][resource - 1] -= q
        allocation[to_agent - 1][resource - 1] += q
    return allocation


def _mechanism_from_edge_quantities(
    proposer_id: int,
    label: str,
    summary: str,
    edges: list[TransferEdge],
    quantities: list[float],
    *,
    eps: float = 1e-6,
) -> CompiledMechanism:
    transfers = [
        Transfer(from_agent=from_agent, to_agent=to_agent, resource=resource, quantity=float(quantity))
        for (from_agent, to_agent, resource), quantity in zip(edges, quantities)
        if float(quantity) > eps
    ]
    consenting_agents = sorted({tr.from_agent for tr in transfers})
    return CompiledMechanism(
        proposer_id=proposer_id,
        label=label,
        summary=summary,
        transfers=transfers,
        consenting_agents=consenting_agents,
        confidence=1.0,
        verifier_ok=True,
    )


def _no_op_oracle_solution(
    world: ExchangeWorld,
    *,
    name: str,
    objective: str,
    participants: list[int],
    controller_id: Optional[int],
    row_limit: Optional[int],
    solver_message: str = "no welfare-improving IR transfer found",
) -> OracleSolution:
    proposer_id = controller_id or (participants[0] if participants else 1)
    allocation = world.copy_allocation()
    welfare = total_welfare(world, allocation)
    mechanism = CompiledMechanism(
        proposer_id=proposer_id,
        label=f"{name}_noop",
        summary=solver_message,
        transfers=[],
        consenting_agents=[],
        confidence=1.0,
        verifier_ok=True,
    )
    return OracleSolution(
        name=name,
        objective=objective,
        participants=participants[:],
        controller_id=controller_id,
        allocation=allocation,
        mechanism=mechanism,
        initial_welfare=welfare,
        oracle_welfare=welfare,
        welfare_gain=0.0,
        utility_deltas={aid: 0.0 for aid in participants},
        row_limit=row_limit,
        success=True,
        solver_message=solver_message,
    )


def _solve_edge_subset_ir_oracle(
    world: ExchangeWorld,
    edges: list[TransferEdge],
    *,
    name: str,
    participants: list[int],
    controller_id: Optional[int],
    row_limit: Optional[int],
    objective: str,
) -> OracleSolution:
    try:
        from scipy.optimize import minimize
    except Exception as exc:  # pragma: no cover - exercised only when scipy is unavailable
        raise RuntimeError("solve_fractional_ir_oracle requires scipy for continuous optimization") from exc

    initial_welfare = total_welfare(world)
    base_utilities = {aid: world.utility(aid) for aid in participants}
    proposer_id = controller_id or (participants[0] if participants else 1)
    if not edges:
        return _no_op_oracle_solution(
            world,
            name=name,
            objective=objective,
            participants=participants,
            controller_id=controller_id,
            row_limit=row_limit,
            solver_message="no candidate transfer edges",
        )

    bounds = [
        (0.0, max(0.0, float(world.allocation[from_agent - 1][resource - 1])))
        for from_agent, _to_agent, resource in edges
    ]

    def allocation_for(x: Any) -> Matrix:
        return _allocation_after_edge_quantities(world, edges, [float(v) for v in x])

    def objective_value(x: Any) -> float:
        allocation = allocation_for(x)
        if objective == "welfare":
            return total_welfare(world, allocation)
        if objective == "controller_utility" and controller_id is not None:
            return world.utility(controller_id, allocation)
        raise ValueError(f"unknown oracle objective: {objective}")

    def loss(x: Any) -> float:
        return -objective_value(x)

    constraints: list[dict[str, Any]] = []
    debit_groups: dict[tuple[int, int], list[int]] = {}
    for idx, (from_agent, _to_agent, resource) in enumerate(edges):
        debit_groups.setdefault((from_agent, resource), []).append(idx)
    for (from_agent, resource), indices in debit_groups.items():
        available = float(world.allocation[from_agent - 1][resource - 1])

        def debit_constraint(x: Any, available: float = available, indices: list[int] = indices) -> float:
            return available - sum(float(x[i]) for i in indices)

        constraints.append({"type": "ineq", "fun": debit_constraint})

    for aid in participants:
        base = base_utilities[aid]

        def ir_constraint(x: Any, aid: int = aid, base: float = base) -> float:
            return world.utility(aid, allocation_for(x)) - base

        constraints.append({"type": "ineq", "fun": ir_constraint})

    result = minimize(
        loss,
        x0=[0.0 for _ in edges],
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-9, "maxiter": 1000, "disp": False},
    )
    x = [0.0 if abs(float(v)) < 1e-8 else float(v) for v in result.x]
    allocation = allocation_for(x)
    deltas = {aid: world.utility(aid, allocation) - base_utilities[aid] for aid in participants}
    oracle_welfare = total_welfare(world, allocation)
    success = bool(result.success) and all(delta >= -1e-6 for delta in deltas.values())
    if not success:
        return _no_op_oracle_solution(
            world,
            name=name,
            objective=objective,
            participants=participants,
            controller_id=controller_id,
            row_limit=row_limit,
            solver_message=f"solver failed: {result.message}",
        )
    if oracle_welfare <= initial_welfare + 1e-7:
        return _no_op_oracle_solution(
            world,
            name=name,
            objective=objective,
            participants=participants,
            controller_id=controller_id,
            row_limit=row_limit,
        )
    mechanism = _mechanism_from_edge_quantities(
        proposer_id,
        name,
        f"{name}: maximize {objective} subject to feasibility and participant IR",
        edges,
        x,
    )
    return OracleSolution(
        name=name,
        objective=objective,
        participants=participants[:],
        controller_id=controller_id,
        allocation=allocation,
        mechanism=mechanism,
        initial_welfare=initial_welfare,
        oracle_welfare=oracle_welfare,
        welfare_gain=oracle_welfare - initial_welfare,
        utility_deltas=deltas,
        row_limit=row_limit,
        success=True,
        solver_message=str(result.message),
    )


def _better_oracle_solution(candidate: OracleSolution, incumbent: Optional[OracleSolution]) -> OracleSolution:
    if incumbent is None:
        return candidate
    if candidate.welfare_gain > incumbent.welfare_gain + 1e-7:
        return candidate
    if abs(candidate.welfare_gain - incumbent.welfare_gain) <= 1e-7:
        if len(candidate.mechanism.transfers) < len(incumbent.mechanism.transfers):
            return candidate
    return incumbent


def solve_fractional_ir_oracle(
    world: ExchangeWorld,
    *,
    participants: Optional[list[int]] = None,
    controller_id: Optional[int] = None,
    row_limit: Optional[int] = None,
    objective: str = "welfare",
    name: str = "fractional_ir_oracle",
    max_exact_edge_subsets: int = 20000,
) -> OracleSolution:
    """Full-information fractional oracle subject to feasibility and participant IR.

    Without a row limit it solves one continuous transfer problem over all
    participant-to-participant transfer edges. With a row limit it exactly
    enumerates transfer-edge subsets up to that limit, which is tractable for the
    current contact-constrained setting where the controller observes two agents.
    """
    participants = sorted(participants or list(range(1, world.num_agents + 1)))
    for aid in participants:
        _idx(aid, world.num_agents, "participant")
    edges = _candidate_transfer_edges(world, participants)
    if row_limit is None or len(edges) <= row_limit:
        return _solve_edge_subset_ir_oracle(
            world,
            edges,
            name=name,
            participants=participants,
            controller_id=controller_id,
            row_limit=row_limit,
            objective=objective,
        )
    if row_limit < 0:
        raise ValueError("row_limit must be non-negative")
    subset_count = sum(math.comb(len(edges), k) for k in range(0, row_limit + 1))
    if subset_count > max_exact_edge_subsets:
        raise ValueError(
            f"exact row-limited oracle would require {subset_count} edge subsets; "
            "increase max_exact_edge_subsets or reduce participants"
        )
    best: Optional[OracleSolution] = None
    for k in range(0, row_limit + 1):
        for edge_subset in combinations(edges, k):
            candidate = _solve_edge_subset_ir_oracle(
                world,
                list(edge_subset),
                name=name,
                participants=participants,
                controller_id=controller_id,
                row_limit=row_limit,
                objective=objective,
            )
            best = _better_oracle_solution(candidate, best)
    return best or _no_op_oracle_solution(
        world,
        name=name,
        objective=objective,
        participants=participants,
        controller_id=controller_id,
        row_limit=row_limit,
    )


def solve_protocol_constrained_ir_oracle(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    *,
    controller_id: int,
    objective: str = "welfare",
) -> OracleSolution:
    participants = _communication_agent_ids_for(protocol, world, controller_id)
    return solve_fractional_ir_oracle(
        world,
        participants=participants,
        controller_id=controller_id,
        row_limit=protocol.settlement_row_limit,
        objective=objective,
        name="protocol_constrained_ir_oracle",
    )


def solve_bilateral_ir_oracle(
    world: ExchangeWorld,
    *,
    participants: Optional[list[int]] = None,
    controller_id: Optional[int] = None,
    row_limit: Optional[int] = None,
    objective: str = "welfare",
) -> OracleSolution:
    """Best pairwise full-information IR settlement inside a participant set."""
    participants = sorted(participants or list(range(1, world.num_agents + 1)))
    for aid in participants:
        _idx(aid, world.num_agents, "participant")
    if len(participants) < 2:
        return _no_op_oracle_solution(
            world,
            name="bilateral_ir_oracle",
            objective=objective,
            participants=participants,
            controller_id=controller_id,
            row_limit=row_limit,
            solver_message="fewer than two participants",
        )

    best: Optional[OracleSolution] = None
    for pair in combinations(participants, 2):
        candidate = solve_fractional_ir_oracle(
            world,
            participants=list(pair),
            controller_id=controller_id or pair[0],
            row_limit=row_limit,
            objective=objective,
            name="bilateral_ir_oracle",
        )
        best = _better_oracle_solution(candidate, best)
    return best or _no_op_oracle_solution(
        world,
        name="bilateral_ir_oracle",
        objective=objective,
        participants=participants,
        controller_id=controller_id,
        row_limit=row_limit,
    )


def simulate_greedy_bilateral_floor(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    *,
    controllers: list[int],
    rounds: int,
) -> GreedyBilateralFloorResult:
    """Memoryless deterministic floor: apply the best visible IR-positive pair."""
    if rounds < 0:
        raise ValueError("rounds must be non-negative")
    if not controllers:
        raise ValueError("controllers must not be empty")
    for controller_id in controllers:
        _idx(controller_id, world.num_agents, "controller")
    work = deepcopy(world)
    initial_welfare = total_welfare(work)
    rows: list[GreedyBilateralRoundResult] = []
    for round_index in range(1, rounds + 1):
        controller_id = controllers[(round_index - 1) % len(controllers)]
        visible_participants = _communication_agent_ids_for(protocol, work, controller_id)
        solution = solve_bilateral_ir_oracle(
            work,
            participants=visible_participants,
            controller_id=controller_id,
            row_limit=protocol.settlement_row_limit,
        )
        applied = solution.welfare_gain > 1e-9 and bool(solution.mechanism.transfers)
        if applied:
            apply_compiled_mechanism(work, solution.mechanism, round_index=round_index, controller_id=controller_id)
        rows.append(
            GreedyBilateralRoundResult(
                round_index=round_index,
                controller_id=controller_id,
                participants=solution.participants,
                applied=applied,
                welfare_gain=solution.welfare_gain if applied else 0.0,
                transfer_rows=len(solution.mechanism.transfers) if applied else 0,
            )
        )
    final_welfare = total_welfare(work)
    return GreedyBilateralFloorResult(
        rounds=rows,
        initial_welfare=initial_welfare,
        final_welfare=final_welfare,
        total_welfare_gain=final_welfare - initial_welfare,
        applied_rounds=sum(1 for row in rows if row.applied),
    )


def evaluate_finite_horizon_institution_oracle(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    pressure: InstitutionPressureConfig,
    *,
    controllers: list[int],
    rounds: int,
    creation_round: int = 1,
) -> InstitutionOracleSolution:
    """Value a reusable public-state rule against one-shot settlement opportunities.

    This diagnostic intentionally does not assume a named institutional form. It
    measures the maximum direct value of one generic standing public-state update
    under the environment's search-cost pressure, then compares it with the best
    myopic settlement opportunity it would displace if creation were exclusive.
    """
    if rounds < 0:
        raise ValueError("rounds must be non-negative")
    if creation_round < 1:
        raise ValueError("creation_round must be at least 1")
    if not controllers:
        raise ValueError("controllers must not be empty")
    for controller_id in controllers:
        _idx(controller_id, world.num_agents, "controller")

    active_rounds = max(0, rounds - creation_round)
    per_round_search_cost_total = max(0.0, float(pressure.search_cost_per_public_round)) * world.num_agents
    per_round_standing_rule_saving = min(
        per_round_search_cost_total,
        max(0.0, float(pressure.standing_rule_bonus_or_cost_saving)),
    )
    standing_rule_saving_total = active_rounds * per_round_standing_rule_saving

    repeated_bilateral_gain = 0.0
    repeated_protocol_gain = 0.0
    first_round_bilateral_gain = 0.0
    first_round_protocol_gain = 0.0
    for round_offset in range(rounds):
        controller_id = controllers[round_offset % len(controllers)]
        participants = _communication_agent_ids_for(protocol, world, controller_id)
        bilateral = solve_bilateral_ir_oracle(
            world,
            participants=participants,
            controller_id=controller_id,
            row_limit=protocol.settlement_row_limit,
        )
        protocol_solution = solve_protocol_constrained_ir_oracle(
            world,
            protocol,
            controller_id=controller_id,
        )
        if round_offset == 0:
            first_round_bilateral_gain = bilateral.welfare_gain
            first_round_protocol_gain = protocol_solution.welfare_gain
        repeated_bilateral_gain += bilateral.welfare_gain
        repeated_protocol_gain += protocol_solution.welfare_gain

    exclusive_net_value = standing_rule_saving_total - first_round_protocol_gain
    parallel_net_value = standing_rule_saving_total
    return InstitutionOracleSolution(
        name="finite_horizon_institution_oracle",
        horizon_rounds=rounds,
        creation_round=creation_round,
        active_rounds=active_rounds,
        per_round_search_cost_total=per_round_search_cost_total,
        per_round_standing_rule_saving=per_round_standing_rule_saving,
        standing_rule_saving_total=standing_rule_saving_total,
        first_round_bilateral_gain=first_round_bilateral_gain,
        first_round_protocol_gain=first_round_protocol_gain,
        repeated_bilateral_gain=repeated_bilateral_gain,
        repeated_protocol_gain=repeated_protocol_gain,
        exclusive_net_value=exclusive_net_value,
        parallel_net_value=parallel_net_value,
        exclusive_should_create=exclusive_net_value > 1e-9,
        parallel_should_create=parallel_net_value > 1e-9,
        institutional_updates=[
            {
                "type": "standing_public_rule_value",
                "summary": "Generic reusable public-state rule valued by search-cost savings.",
                "active_rounds": active_rounds,
                "per_round_saving": per_round_standing_rule_saving,
            }
        ],
    )


def _public_solicitation_candidate_agents(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    controller_id: int,
    envelope: PublicSolicitationEnvelope,
) -> list[int]:
    if envelope.candidate_scope == "visible_only":
        return _communication_agent_ids_for(protocol, world, controller_id)
    if envelope.candidate_scope not in {"public_response_scope", "all_agents"}:
        raise ValueError(f"unknown public solicitation candidate_scope: {envelope.candidate_scope}")
    if not protocol.public_broadcast:
        return _communication_agent_ids_for(protocol, world, controller_id)
    if envelope.candidate_scope == "all_agents":
        return list(range(1, world.num_agents + 1))
    if protocol.response_scope == "solicited_public":
        return list(range(1, world.num_agents + 1))
    return sorted({controller_id, *_response_agent_ids_for(protocol, world, controller_id)})


def _rank_public_solicitation_respondents(
    world: ExchangeWorld,
    controller_id: int,
    respondents: list[int],
    *,
    row_limit: Optional[int],
    respondent_limit: Optional[int],
) -> list[int]:
    if respondent_limit is None or respondent_limit >= len(respondents):
        return respondents[:]
    scored: list[tuple[float, int]] = []
    for aid in respondents:
        pair = solve_fractional_ir_oracle(
            world,
            participants=[controller_id, aid],
            controller_id=controller_id,
            row_limit=row_limit,
            name="public_solicitation_pair_response_score",
        )
        scored.append((pair.welfare_gain, aid))
    return [aid for _score, aid in sorted(scored, key=lambda item: (-item[0], item[1]))[: max(0, respondent_limit)]]


def _public_solicitation_cost(
    world: ExchangeWorld,
    pressure: Optional[InstitutionPressureConfig],
    envelope: PublicSolicitationEnvelope,
    *,
    has_public_path: bool,
) -> float:
    if envelope.solicitation_cost is not None:
        return max(0.0, float(envelope.solicitation_cost))
    if not has_public_path or pressure is None:
        return 0.0
    return max(0.0, float(pressure.search_cost_per_public_round)) * world.num_agents


def solve_bounded_public_solicitation_oracle(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    *,
    controller_id: int,
    envelope: Optional[PublicSolicitationEnvelope] = None,
    pressure: Optional[InstitutionPressureConfig] = None,
    objective: str = "welfare",
) -> BoundedPublicSolicitationSolution:
    """Best truthful public opt-in discovery policy within a fixed envelope.

    The envelope is deliberately narrow: potential respondents truthfully reveal
    enough surplus/authorization information to be considered for one row-limited
    settlement. The solver chooses the best participant subset inside that
    response class; it does not optimize over arbitrary language or institutions.
    """
    _idx(controller_id, world.num_agents, "controller")
    envelope = envelope or PublicSolicitationEnvelope()
    if envelope.max_participants < 1:
        raise ValueError("max_participants must be at least 1")
    if envelope.respondent_limit is not None and envelope.respondent_limit < 0:
        raise ValueError("respondent_limit must be non-negative")

    row_limit = envelope.settlement_row_limit
    if row_limit is None:
        row_limit = protocol.settlement_row_limit

    visible_baseline = solve_protocol_constrained_ir_oracle(
        world,
        protocol,
        controller_id=controller_id,
        objective=objective,
    )
    candidate_agents = _public_solicitation_candidate_agents(world, protocol, controller_id, envelope)
    candidate_agents = sorted({controller_id, *candidate_agents})
    raw_respondents = [aid for aid in candidate_agents if aid != controller_id]
    respondent_agents = _rank_public_solicitation_respondents(
        world,
        controller_id,
        raw_respondents,
        row_limit=row_limit,
        respondent_limit=envelope.respondent_limit,
    )

    best: Optional[OracleSolution] = None
    max_participants = min(envelope.max_participants, 1 + len(respondent_agents))
    for participant_count in range(2, max_participants + 1):
        for subset in combinations(respondent_agents, participant_count - 1):
            participants = sorted({controller_id, *subset})
            candidate = solve_fractional_ir_oracle(
                world,
                participants=participants,
                controller_id=controller_id,
                row_limit=row_limit,
                objective=objective,
                name="bounded_public_solicitation_oracle",
            )
            best = _better_oracle_solution(candidate, best)

    if best is None:
        best = _no_op_oracle_solution(
            world,
            name="bounded_public_solicitation_oracle",
            objective=objective,
            participants=[controller_id],
            controller_id=controller_id,
            row_limit=row_limit,
            solver_message="no public respondents available inside bounded envelope",
        )

    has_public_path = protocol.public_broadcast and len(raw_respondents) > 0
    solicitation_cost = _public_solicitation_cost(world, pressure, envelope, has_public_path=has_public_path)
    gross_discovery_gain = best.welfare_gain - visible_baseline.welfare_gain
    net_discovery_gain = gross_discovery_gain - solicitation_cost
    return BoundedPublicSolicitationSolution(
        name="bounded_public_solicitation_oracle",
        controller_id=controller_id,
        envelope=envelope,
        visible_baseline=visible_baseline,
        solicited_solution=best,
        candidate_agents=candidate_agents,
        respondent_agents=respondent_agents,
        selected_participants=best.participants,
        solicitation_cost=solicitation_cost,
        gross_discovery_gain=gross_discovery_gain,
        net_discovery_gain=net_discovery_gain,
        should_solicit=net_discovery_gain > 1e-9,
        solver_message=best.solver_message,
    )


def _sample_generator_prior_preferences(
    world: ExchangeWorld,
    rng: random.Random,
    *,
    exact_preference_agent_ids: set[int],
    want_constraints: Optional[dict[int, set[int]]] = None,
    max_condition_attempts: int = 200,
) -> FloatMatrix:
    """Sample utilities from the exchange generator prior, conditioned lightly.

    This mirrors ``make_exchange_world``'s utility generator. Exact known agents
    are copied from the realized world. Public "want rX" constraints are handled
    by rejection sampling until wanted resources are above the row mean. This is
    intentionally a first offline posterior approximation, not a likelihood model
    over arbitrary natural language.
    """
    want_constraints = want_constraints or {}

    def draw_row(agent_index: int) -> list[float]:
        row = []
        for r in range(world.num_resources):
            if world.money_good_index is not None and r == world.money_good_index:
                row.append(1.0)
                continue
            base = 0.5 + 4.5 * rng.random()
            peak = (agent_index * 3 + 2) % world.num_resources
            if r == peak:
                base += 3.0
            row.append(round(base, 3))
        return row

    preferences: FloatMatrix = []
    for agent_index in range(world.num_agents):
        agent_id = agent_index + 1
        if agent_id in exact_preference_agent_ids:
            preferences.append(world.preferences[agent_index][:])
            continue
        wanted = want_constraints.get(agent_id, set())
        accepted: Optional[list[float]] = None
        for _attempt in range(max_condition_attempts):
            row = draw_row(agent_index)
            if not wanted:
                accepted = row
                break
            row_mean = sum(row) / max(1, len(row))
            if all(row[rid - 1] >= row_mean for rid in wanted if 1 <= rid <= world.num_resources):
                accepted = row
                break
        preferences.append(accepted if accepted is not None else draw_row(agent_index))
    return preferences


def _mechanism_signature(mechanism: CompiledMechanism) -> tuple[tuple[int, int, int, float], ...]:
    return tuple(
        sorted(
            (
                tr.from_agent,
                tr.to_agent,
                tr.resource,
                round(float(tr.quantity), 6),
            )
            for tr in mechanism.transfers
            if float(tr.quantity) > 1e-8
        )
    )


def _mechanism_ir_deltas(world: ExchangeWorld, mechanism: CompiledMechanism) -> dict[int, float]:
    affected = sorted({tr.from_agent for tr in mechanism.transfers} | {tr.to_agent for tr in mechanism.transfers})
    return {aid: utility_delta_for_mechanism(world, mechanism, aid) for aid in affected}


def _mechanism_gain_if_realized_ir(world: ExchangeWorld, mechanism: CompiledMechanism) -> tuple[float, bool, dict[int, float]]:
    if not mechanism.transfers:
        return 0.0, True, {}
    if not compiled_mechanism_feasible(world, mechanism):
        return 0.0, False, {}
    deltas = _mechanism_ir_deltas(world, mechanism)
    ir_ok = all(delta >= -1e-7 for delta in deltas.values())
    if not ir_ok:
        return 0.0, False, deltas
    return sum(utility_delta_for_mechanism(world, mechanism, aid) for aid in range(1, world.num_agents + 1)), True, deltas


def _public_signal_want_constraints(
    communication_texts: Optional[dict[int, str] | dict[str, str]],
    *,
    num_resources: int,
) -> dict[int, set[int]]:
    wants: dict[int, set[int]] = {}
    for key, text in (communication_texts or {}).items():
        aid = _agent_id_from_text_key(key)
        if aid is None:
            continue
        agent_wants, _agent_offers = _infer_public_wants_offers_from_text(str(text), num_resources=num_resources)
        if agent_wants:
            wants.setdefault(aid, set()).update(agent_wants)
    return wants


def solve_bayesian_protocol_frontier(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    *,
    controller_id: int,
    exact_preference_agent_ids: Optional[list[int]] = None,
    communication_texts: Optional[dict[int, str] | dict[str, str]] = None,
    sample_count: int = 32,
    seed: int = 0,
) -> BayesianProtocolFrontierSolution:
    """Approximate non-full-info frontier for one controller state.

    Candidate mechanisms are generated from posterior-sampled utility tables
    and must obey the same protocol participant set and row limit. The selected
    mechanism maximizes posterior expected gain after simulated consent/IR
    filtering, then is evaluated once on the realized hidden economy. This is a
    practical first Bayesian score, not an exact optimizer over arbitrary NL
    policies.
    """
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    _idx(controller_id, world.num_agents, "controller")
    participants = _communication_agent_ids_for(protocol, world, controller_id)
    exact_ids = set(exact_preference_agent_ids or [controller_id])
    exact_ids.add(controller_id)
    for aid in exact_ids:
        _idx(aid, world.num_agents, "exact_preference_agent")

    want_constraints = _public_signal_want_constraints(
        communication_texts,
        num_resources=world.num_resources,
    )
    rng = random.Random(seed)
    posterior_worlds: list[ExchangeWorld] = []
    candidates: dict[tuple[tuple[int, int, int, float], ...], CompiledMechanism] = {}
    candidates[()] = CompiledMechanism(
        proposer_id=controller_id,
        label="bayesian_protocol_frontier_noop",
        summary="No-op candidate in Bayesian frontier set.",
        transfers=[],
        consenting_agents=[],
        confidence=1.0,
        verifier_ok=True,
    )

    for _sample_index in range(sample_count):
        sample_world = replace(
            world,
            preferences=_sample_generator_prior_preferences(
                world,
                rng,
                exact_preference_agent_ids=exact_ids,
                want_constraints=want_constraints,
            ),
        )
        posterior_worlds.append(sample_world)
        solution = solve_protocol_constrained_ir_oracle(
            sample_world,
            protocol,
            controller_id=controller_id,
        )
        candidates.setdefault(_mechanism_signature(solution.mechanism), solution.mechanism)

    best_mechanism: Optional[CompiledMechanism] = None
    best_expected_gain = -float("inf")
    for mechanism in candidates.values():
        gains = [_mechanism_gain_if_realized_ir(sample_world, mechanism)[0] for sample_world in posterior_worlds]
        expected_gain = sum(gains) / sample_count
        if expected_gain > best_expected_gain + 1e-9:
            best_expected_gain = expected_gain
            best_mechanism = mechanism
        elif best_mechanism is not None and abs(expected_gain - best_expected_gain) <= 1e-9:
            if len(mechanism.transfers) < len(best_mechanism.transfers):
                best_mechanism = mechanism

    selected = best_mechanism or candidates[()]
    realized_gain, realized_ir, realized_deltas = _mechanism_gain_if_realized_ir(world, selected)
    return BayesianProtocolFrontierSolution(
        name="bayesian_protocol_frontier",
        controller_id=controller_id,
        participants=participants,
        sample_count=sample_count,
        candidate_count=len(candidates),
        selected_mechanism=selected,
        expected_gain=max(0.0, best_expected_gain),
        realized_gain=realized_gain,
        realized_individually_rational=realized_ir,
        utility_deltas=realized_deltas,
        exact_preference_agent_ids=sorted(exact_ids),
        conditioning_summary={
            "want_constraints": {aid: sorted(values) for aid, values in sorted(want_constraints.items())},
            "basis": "generator_prior_plus_exact_known_preferences_plus_parsed_public_wants",
        },
        seed=seed,
    )


def _agent_id_from_text_key(value: Any) -> Optional[int]:
    try:
        aid = int(str(value).strip().lower().removeprefix("a"))
    except Exception:
        return None
    return aid if aid >= 1 else None


def _resources_in_text(text: str, num_resources: int) -> list[int]:
    resources = sorted({int(match.group(1)) for match in re.finditer(r"\br\s*(\d+)\b", text.lower())})
    return [rid for rid in resources if 1 <= rid <= num_resources]


def _infer_public_wants_offers_from_text(
    text: str,
    *,
    num_resources: int,
) -> tuple[set[int], set[int]]:
    wants: set[int] = set()
    offers: set[int] = set()
    desire_markers = (
        "want",
        "need",
        "interested",
        "acquir",
        "looking for",
        "looking to get",
        "prefer",
        "value",
        "receive",
        "in exchange for",
    )
    offer_markers = (
        "offer",
        "give",
        "trade my",
        "trade some of my",
        "trade ",
        "currently hold",
        "currently have",
        "hold ",
        "have ",
        "my r",
        "willing to trade",
    )
    for sentence in re.split(r"[\n.;]+", text.lower()):
        resources = _resources_in_text(sentence, num_resources)
        if not resources:
            continue
        if any(marker in sentence for marker in desire_markers):
            wants.update(resources)
        if any(marker in sentence for marker in offer_markers):
            offers.update(resources)
        offers.update(
            int(match.group(1))
            for match in re.finditer(r"\bmy\s+r\s*(\d+)\b", sentence)
            if 1 <= int(match.group(1)) <= num_resources
        )
    return wants, offers


def _controller_current_offer_resources(world: ExchangeWorld, controller_id: int) -> list[int]:
    return [
        rid
        for rid, quantity in enumerate(world.allocation[controller_id - 1], start=1)
        if float(quantity) > 1e-12
    ]


def _solve_inferred_edge_oracle(
    world: ExchangeWorld,
    edges: list[TransferEdge],
    *,
    participants: list[int],
    controller_id: int,
    row_limit: Optional[int],
    objective: str,
    name: str,
    max_exact_edge_subsets: int = 20000,
) -> OracleSolution:
    participants = sorted(participants)
    if not edges:
        return _no_op_oracle_solution(
            world,
            name=name,
            objective=objective,
            participants=participants,
            controller_id=controller_id,
            row_limit=row_limit,
            solver_message="no transfer edges inferred from public signals",
        )
    if row_limit is None or len(edges) <= row_limit:
        return _solve_edge_subset_ir_oracle(
            world,
            edges,
            name=name,
            participants=participants,
            controller_id=controller_id,
            row_limit=row_limit,
            objective=objective,
        )
    if row_limit < 0:
        raise ValueError("row_limit must be non-negative")
    subset_count = sum(math.comb(len(edges), k) for k in range(0, row_limit + 1))
    if subset_count > max_exact_edge_subsets:
        raise ValueError(
            f"exact inferred-edge oracle would require {subset_count} edge subsets; "
            "increase max_exact_edge_subsets or reduce inferred edges"
        )
    best: Optional[OracleSolution] = None
    for k in range(0, row_limit + 1):
        for edge_subset in combinations(edges, k):
            edge_list = list(edge_subset)
            participant_subset = sorted(
                {controller_id}
                | {from_agent for from_agent, _to_agent, _resource in edge_list}
                | {to_agent for _from_agent, to_agent, _resource in edge_list}
            )
            candidate = _solve_edge_subset_ir_oracle(
                world,
                edge_list,
                name=name,
                participants=participant_subset,
                controller_id=controller_id,
                row_limit=row_limit,
                objective=objective,
            )
            best = _better_oracle_solution(candidate, best)
    return best or _no_op_oracle_solution(
        world,
        name=name,
        objective=objective,
        participants=participants,
        controller_id=controller_id,
        row_limit=row_limit,
    )


def solve_l4_inference_constrained_oracle(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    *,
    controller_id: int,
    communication_texts: Optional[dict[int, str] | dict[str, str]] = None,
    objective: str = "welfare",
) -> L4InferenceConstrainedSolution:
    """L4 public-signal oracle constrained by what the controller could infer.

    This oracle builds a transfer-edge graph only from public want/offer text
    observed before proposal. It uses true utilities only for ex post scoring and
    participant IR on the inferred edge graph; it does not search hidden utility
    edges that were never publicly signaled.
    """
    _idx(controller_id, world.num_agents, "controller")
    wants: dict[int, set[int]] = {}
    offers: dict[int, set[int]] = {}
    observed_agents: set[int] = set()
    for key, text in (communication_texts or {}).items():
        aid = _agent_id_from_text_key(key)
        if aid is None or aid > world.num_agents:
            continue
        observed_agents.add(aid)
        agent_wants, agent_offers = _infer_public_wants_offers_from_text(str(text), num_resources=world.num_resources)
        if agent_wants:
            wants.setdefault(aid, set()).update(agent_wants)
        if agent_offers:
            offers.setdefault(aid, set()).update(agent_offers)
    observed_agents.add(controller_id)
    offers.setdefault(controller_id, set()).update(_controller_current_offer_resources(world, controller_id))

    edges: list[TransferEdge] = []
    for from_agent, offered_resources in offers.items():
        if from_agent not in observed_agents:
            continue
        for resource in sorted(offered_resources):
            if float(world.allocation[from_agent - 1][resource - 1]) <= 1e-12:
                continue
            for to_agent, wanted_resources in wants.items():
                if to_agent == from_agent or to_agent not in observed_agents:
                    continue
                if resource in wanted_resources:
                    edges.append((from_agent, to_agent, resource))
    edges = sorted(set(edges))
    participants = sorted(
        {controller_id}
        | {from_agent for from_agent, _to_agent, _resource in edges}
        | {to_agent for _from_agent, to_agent, _resource in edges}
    )
    solution = _solve_inferred_edge_oracle(
        world,
        edges,
        participants=participants,
        controller_id=controller_id,
        row_limit=protocol.settlement_row_limit,
        objective=objective,
        name="l4_inference_constrained_oracle",
    )
    return L4InferenceConstrainedSolution(
        name="l4_inference_constrained_oracle",
        controller_id=controller_id,
        observed_agents=sorted(observed_agents),
        inferred_wants={aid: sorted(values) for aid, values in sorted(wants.items())},
        inferred_offers={aid: sorted(values) for aid, values in sorted(offers.items())},
        inferred_edges=edges,
        solution=solution,
    )


def _zero_regret_component(step: str) -> ActionRegretComponent:
    return ActionRegretComponent(
        step=step,
        agent_id=None,
        oracle_gain=0.0,
        actual_gain=0.0,
        regret=0.0,
        label="not_applicable",
    )


def _mechanism_welfare_gain(world: ExchangeWorld, mechanism: Optional[CompiledMechanism]) -> float:
    if mechanism is None:
        return 0.0
    return sum(utility_delta_for_mechanism(world, mechanism, aid) for aid in range(1, world.num_agents + 1))


def _viable_ir_mechanism_welfare_gain(world: ExchangeWorld, mechanism: Optional[CompiledMechanism]) -> float:
    if mechanism is None or not mechanism.transfers:
        return 0.0
    if not compiled_mechanism_feasible(world, mechanism):
        return 0.0
    affected = sorted({tr.from_agent for tr in mechanism.transfers} | {tr.to_agent for tr in mechanism.transfers})
    deltas = [utility_delta_for_mechanism(world, mechanism, aid) for aid in affected]
    if any(delta < -1e-7 for delta in deltas):
        return 0.0
    return max(0.0, sum(deltas))


_BROAD_PUBLIC_SCOPE_MARKERS = (
    "all agents",
    "any agent",
    "anyone",
    "everyone",
    "public broadcast",
    "whoever",
)

_PUBLIC_RESPONSE_REQUEST_MARKERS = (
    "accept",
    "opt in",
    "consent",
    "counter",
    "counter-propose",
    "counterproposal",
    "counter-offer",
    "propose",
    "respond",
    "reply",
    "state",
    "reveal",
    "reject",
    "authorize",
    "authorization",
    "willing",
    "offer",
    "constraints",
    "preference",
    "preferences",
    "share",
)


def _contains_broad_public_scope(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BROAD_PUBLIC_SCOPE_MARKERS)


def _contains_public_response_request(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _PUBLIC_RESPONSE_REQUEST_MARKERS)


def _targeted_public_response_agent_ids(
    text: str,
    *,
    num_agents: int,
    controller_id: int,
) -> list[int]:
    if not _has_public_action_section(text, "ADDRESSEES"):
        return []
    if not _has_public_action_section(text, "RESPONSE REQUEST"):
        return []
    addressees = _public_action_section(text, "ADDRESSEES")
    response_request = _public_action_section(text, "RESPONSE REQUEST")
    if _section_is_none(addressees) or _section_is_none(response_request):
        return []
    if _contains_broad_public_scope(addressees):
        return []
    if not _contains_public_response_request(response_request):
        return []

    ids: set[int] = set()
    for pattern in [r"\ba\s*(\d+)\b", r"\bagent\s+(\d+)\b"]:
        for match in re.finditer(pattern, addressees, flags=re.IGNORECASE):
            aid = int(match.group(1))
            if 1 <= aid <= num_agents and aid != controller_id:
                ids.add(aid)
    return sorted(ids)


def _free_text_for_solicitation_detection(text: str) -> str:
    """Strip envelope headings so labels like PUBLIC STATE UPDATE do not trigger solicitation."""
    if not text:
        return ""
    if _has_public_action_section(text, "MESSAGE"):
        return "\n".join(
            part
            for part in [
                _public_action_section(text, "MESSAGE"),
                _public_action_section(text, "CONSENT CONDITIONS"),
            ]
            if part
        )
    return text


def _structured_public_solicitation(text: str) -> Optional[bool]:
    has_addressees = _has_public_action_section(text, "ADDRESSEES")
    has_response_request = _has_public_action_section(text, "RESPONSE REQUEST")
    if not has_addressees and not has_response_request:
        return None

    addressees = _public_action_section(text, "ADDRESSEES")
    response_request = _public_action_section(text, "RESPONSE REQUEST")
    message = _public_action_section(text, "MESSAGE")

    if has_addressees and not _section_is_none(addressees):
        broad_scope = _contains_broad_public_scope(addressees)
    else:
        broad_scope = _contains_broad_public_scope(message)

    if has_response_request:
        requests_response = (
            not _section_is_none(response_request)
            and _contains_public_response_request(response_request)
        )
    else:
        requests_response = _contains_public_response_request(message)

    return broad_scope and requests_response


def _has_functional_public_solicitation(
    communication_texts: Optional[dict[int, str]],
    *,
    controller_id: int,
    proposal_text: str = "",
    final_text: str = "",
) -> bool:
    texts = [
        str((communication_texts or {}).get(controller_id, "")),
        str((communication_texts or {}).get(str(controller_id), "")),
        proposal_text or "",
        final_text or "",
    ]
    fallback_texts = []
    for text in texts:
        structured = _structured_public_solicitation(text)
        if structured is True:
            return True
        if structured is None:
            fallback_texts.append(_free_text_for_solicitation_detection(text))

    fallback_text = "\n".join(fallback_texts)
    return (
        _contains_broad_public_scope(fallback_text)
        and _contains_public_response_request(fallback_text)
    )


def _acceptance_regret_component(audit: PrivateAcceptanceAudit) -> ActionRegretComponent:
    if audit.approval_correct:
        if audit.approve and audit.actual_delta > 0:
            oracle_gain = audit.actual_delta
            actual_gain = audit.actual_delta
        else:
            oracle_gain = 0.0
            actual_gain = 0.0
        label = "correct_private_acceptance"
        regret = 0.0
    elif audit.actual_delta > 1e-9 and not audit.approve:
        oracle_gain = audit.actual_delta
        actual_gain = 0.0
        regret = audit.actual_delta
        label = "wrong_reject_positive_bundle"
    elif audit.approve and audit.actual_delta <= 1e-9:
        oracle_gain = 0.0
        actual_gain = audit.actual_delta
        regret = max(0.0, -audit.actual_delta)
        label = "wrong_approve_nonpositive_bundle"
    else:
        oracle_gain = max(0.0, audit.actual_delta)
        actual_gain = oracle_gain
        regret = 0.0
        label = "non_payoff_acceptance_error"
    return ActionRegretComponent(
        step="acceptance",
        agent_id=audit.agent_id,
        oracle_gain=oracle_gain,
        actual_gain=actual_gain,
        regret=regret,
        label=label,
        details={
            "error_family": audit.error_family,
            "actual_delta": audit.actual_delta,
            "actual_delta_sign": audit.actual_delta_sign,
            "claimed_delta_sign": audit.claimed_delta_sign,
            "approve": audit.approve,
            "approval_correct": audit.approval_correct,
        },
    )


def decompose_round_regret(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    *,
    round_index: int,
    controller_id: int,
    communication_texts: Optional[dict[int, str] | dict[str, str]] = None,
    proposal_text: str = "",
    final_text: str = "",
    verified_before_private_acceptance: Optional[CompiledMechanism] = None,
    executed_mechanism: Optional[CompiledMechanism] = None,
    private_acceptance_audits: Optional[list[PrivateAcceptanceAudit]] = None,
    event: Optional[RoundEvent] = None,
    observed_gain: Optional[float] = None,
    pressure: Optional[InstitutionPressureConfig] = None,
    solicitation_envelope: Optional[PublicSolicitationEnvelope] = None,
    protocol_solution: Optional[OracleSolution] = None,
    solicitation_solution: Optional[BoundedPublicSolicitationSolution] = None,
) -> RoundRegretDecomposition:
    """Decompose one free-form round into typed local regret components.

    Components are diagnostic, not a proof of global language-action regret. The
    communication component evaluates the bounded public opt-in envelope; the
    proposal component evaluates the verified finalized bundle before private
    acceptance; acceptance components evaluate each audited private decision;
    finalization captures residual loss from a viable finalized bundle not being
    executed when that loss is not already attributed to wrong private rejection.
    """
    _idx(controller_id, world.num_agents, "controller")
    protocol_solution = protocol_solution or solve_protocol_constrained_ir_oracle(
        world,
        protocol,
        controller_id=controller_id,
    )
    solicitation_solution = solicitation_solution or solve_bounded_public_solicitation_oracle(
        world,
        protocol,
        controller_id=controller_id,
        envelope=solicitation_envelope,
        pressure=pressure,
    )
    if private_acceptance_audits is None and event is not None:
        private_acceptance_audits = event.private_acceptance_audits
    private_acceptance_audits = private_acceptance_audits or []

    if observed_gain is None:
        observed_gain = 0.0
        if event is not None:
            observed_gain = event.welfare_after - total_welfare(world)
        elif executed_mechanism is not None:
            observed_gain = _mechanism_welfare_gain(world, executed_mechanism)
    observed_gain = float(observed_gain)

    components: list[ActionRegretComponent] = []
    solicitation_detected = _has_functional_public_solicitation(
        communication_texts,
        controller_id=controller_id,
        proposal_text=proposal_text,
        final_text=final_text,
    )
    discovery_oracle = max(0.0, solicitation_solution.net_discovery_gain)
    discovery_actual = discovery_oracle if solicitation_detected else 0.0
    components.append(
        ActionRegretComponent(
            step="communication",
            agent_id=controller_id,
            oracle_gain=discovery_oracle,
            actual_gain=discovery_actual,
            regret=max(0.0, discovery_oracle - discovery_actual),
            label=(
                "functional_bounded_public_solicitation"
                if solicitation_detected
                else "missed_bounded_public_solicitation"
            ),
            details={
                "solicitation_detected": solicitation_detected,
                "selected_participants": solicitation_solution.selected_participants,
                "candidate_agents": solicitation_solution.candidate_agents,
            },
        )
    )

    proposed_gain = _viable_ir_mechanism_welfare_gain(world, verified_before_private_acceptance)
    components.append(
        ActionRegretComponent(
            step="proposal",
            agent_id=controller_id,
            oracle_gain=protocol_solution.welfare_gain,
            actual_gain=proposed_gain,
            regret=max(0.0, protocol_solution.welfare_gain - proposed_gain),
            label="viable_ir_proposal" if proposed_gain > 1e-9 else "no_viable_ir_proposal",
            details={
                "protocol_participants": protocol_solution.participants,
                "pre_acceptance_transfer_rows": (
                    len(verified_before_private_acceptance.transfers)
                    if verified_before_private_acceptance is not None
                    else 0
                ),
            },
        )
    )

    components.extend(_acceptance_regret_component(audit) for audit in private_acceptance_audits)

    executed_gain = max(0.0, _mechanism_welfare_gain(world, executed_mechanism))
    wrong_positive_rejection = any(
        audit.actual_delta > 1e-9 and not audit.approve and not audit.approval_correct
        for audit in private_acceptance_audits
    )
    if wrong_positive_rejection:
        finalization_regret = 0.0
        finalization_label = "execution_blocked_by_private_acceptance"
    else:
        finalization_regret = max(0.0, proposed_gain - executed_gain)
        finalization_label = "execution_lost_viable_bundle" if finalization_regret > 1e-9 else "executed_or_no_viable_bundle"
    components.append(
        ActionRegretComponent(
            step="finalization",
            agent_id=controller_id,
            oracle_gain=proposed_gain,
            actual_gain=executed_gain,
            regret=finalization_regret,
            label=finalization_label,
            details={
                "pre_acceptance_gain": proposed_gain,
                "executed_gain": executed_gain,
                "wrong_positive_rejection": wrong_positive_rejection,
            },
        )
    )

    return RoundRegretDecomposition(
        round_index=round_index,
        controller_id=controller_id,
        observed_gain=observed_gain,
        components=components,
        protocol_oracle_gain=protocol_solution.welfare_gain,
        public_solicitation_gain=solicitation_solution.solicited_solution.welfare_gain,
        public_solicitation_net_lift=solicitation_solution.net_discovery_gain,
    )


# ===============================================================
# Events
# ===============================================================


@dataclass
class RoundEvent:
    round_index: int
    controller_id: int
    kind: str
    proposer_id: int
    receiver_id: Optional[int] = None
    accepted: bool = False
    applied: bool = False
    feasible: bool = True
    individually_rational: Optional[bool] = None
    ir_blocked: bool = False
    proposer_delta: float = 0.0
    receiver_delta: float = 0.0
    agent_deltas: dict[int, float] = field(default_factory=dict)
    welfare_after: float = 0.0
    message: str = ""
    institutional_updates: list[dict[str, Any]] = field(default_factory=list)
    private_acceptance_audits: list[PrivateAcceptanceAudit] = field(default_factory=list)
    coordination_cost: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    initial_allocation: Matrix
    final_allocation: Matrix
    history: list[RoundEvent]
    initial_welfare: float
    final_welfare: float
    optimum_welfare: float
    initial_welfare_ratio: float
    final_welfare_ratio: float
    initial_gini: float
    final_gini: float
    final_institutions: list[dict[str, Any]] = field(default_factory=list)
    coordination_cost_total: float = 0.0
    final_net_welfare: Optional[float] = None

    @property
    def applied_mechanisms(self) -> int:
        return sum(1 for e in self.history if e.applied)

    @property
    def ir_violations(self) -> int:
        return sum(1 for e in self.history if e.applied and e.individually_rational is False)


def _inc(counter: dict[str, int], key: str, amount: int = 1) -> None:
    counter[key] = counter.get(key, 0) + amount


def private_acceptance_audit_dict(audit: PrivateAcceptanceAudit) -> dict[str, Any]:
    return {
        "agent_id": audit.agent_id,
        "approve": audit.approve,
        "actual_delta": audit.actual_delta,
        "actual_delta_sign": audit.actual_delta_sign,
        "claimed_delta_sign": audit.claimed_delta_sign,
        "sign_match": audit.sign_match,
        "debit_rows_match": audit.debit_rows_match,
        "credit_rows_match": audit.credit_rows_match,
        "quantity_match": audit.quantity_match,
        "counterpart_transfers_present": audit.counterpart_transfers_present,
        "same_bundle_authorized": audit.same_bundle_authorized,
        "approval_correct": audit.approval_correct,
        "error_family": audit.error_family,
        "reason": audit.reason,
    }


def compiled_mechanism_dict(mechanism: CompiledMechanism) -> dict[str, Any]:
    return {
        "mechanism_label": mechanism.label,
        "summary": mechanism.summary,
        "transfers": [
            {
                "from": tr.from_agent,
                "to": tr.to_agent,
                "resource": f"r{tr.resource}",
                "quantity": tr.quantity,
            }
            for tr in mechanism.transfers
        ],
        "institutional_updates": deepcopy(mechanism.institutional_updates),
        "consenting_agents": list(mechanism.consenting_agents),
        "confidence": mechanism.confidence,
        "verifier_ok": mechanism.verifier_ok,
        "verifier_reason": mechanism.verifier_reason,
    }


def round_event_dict(event: RoundEvent) -> dict[str, Any]:
    return {
        "round_index": event.round_index,
        "controller_id": event.controller_id,
        "kind": event.kind,
        "proposer_id": event.proposer_id,
        "receiver_id": event.receiver_id,
        "accepted": event.accepted,
        "applied": event.applied,
        "feasible": event.feasible,
        "individually_rational": event.individually_rational,
        "ir_blocked": event.ir_blocked,
        "proposer_delta": event.proposer_delta,
        "receiver_delta": event.receiver_delta,
        "agent_deltas": dict(event.agent_deltas),
        "welfare_after": event.welfare_after,
        "message": event.message,
        "institutional_updates": deepcopy(event.institutional_updates),
        "private_acceptance_audits": [
            private_acceptance_audit_dict(audit) for audit in event.private_acceptance_audits
        ],
        "coordination_cost": dict(event.coordination_cost),
    }


def summarize_run_errors(result: RunResult) -> dict[str, Any]:
    audits = [audit for event in result.history for audit in event.private_acceptance_audits]
    error_families: dict[str, int] = {}
    for audit in audits:
        _inc(error_families, audit.error_family)
    bad_positive_approvals = sum(
        1
        for audit in audits
        if audit.approve and audit.actual_delta <= 1e-9
    )
    protocol_errors = sum(
        1
        for event in result.history
        if not event.applied and event.feasible and not event.private_acceptance_audits
    )
    private_rejected_rounds = sum(
        1
        for event in result.history
        if event.private_acceptance_audits and not event.applied
    )
    return {
        "applied_resource_ir_true": sum(1 for e in result.history if e.applied and e.individually_rational is True),
        "applied_resource_ir_false": sum(1 for e in result.history if e.applied and e.individually_rational is False),
        "protocol_errors": protocol_errors,
        "agent_decision_errors": sum(1 for audit in audits if audit.error_family != "none"),
        "private_acceptance": {
            "agent_checks": len(audits),
            "approved": sum(1 for audit in audits if audit.approve),
            "rejected_or_invalid": sum(1 for audit in audits if not audit.approve),
            "blocked_rounds": private_rejected_rounds,
            "bad_positive_approvals": bad_positive_approvals,
            "error_families": error_families,
            "audits": [private_acceptance_audit_dict(audit) for audit in audits],
        },
    }


def render_error_decomposition_report(summary: dict[str, Any]) -> str:
    private = summary.get("private_acceptance", {})
    families = private.get("error_families", {})
    family_lines = "\n".join(
        f"- {name}: `{count}`" for name, count in sorted(families.items())
    ) or "- none: `0`"
    return (
        "## Error Decomposition\n\n"
        f"- Applied resource IR true/false: `{summary.get('applied_resource_ir_true', 0)} / "
        f"{summary.get('applied_resource_ir_false', 0)}`\n"
        f"- Protocol errors: `{summary.get('protocol_errors', 0)}`\n"
        f"- Agent Decision Errors: `{summary.get('agent_decision_errors', 0)}`\n\n"
        "### Private Acceptance\n\n"
        f"- Agent checks: `{private.get('agent_checks', 0)}`\n"
        f"- Approved: `{private.get('approved', 0)}`\n"
        f"- Rejected or invalid: `{private.get('rejected_or_invalid', 0)}`\n"
        f"- Blocked rounds: `{private.get('blocked_rounds', 0)}`\n"
        f"- Bad positive approvals: `{private.get('bad_positive_approvals', 0)}`\n\n"
        "### Error Families\n\n"
        f"{family_lines}\n"
    )


def build_run_summary_payload(
    result: RunResult,
    *,
    config: Optional[ExchangeExperimentConfig] = None,
    usage: Optional[dict[str, Any]] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    protocol = config.protocol if config else ProtocolConfig()
    return {
        "config_name": config.name if config else "cli_defaults",
        "model": model,
        "agents": len(result.final_allocation),
        "resources": len(result.final_allocation[0]) if result.final_allocation else 0,
        "rounds": len(result.history),
        "controllers": [event.controller_id for event in result.history],
        "utility_mode": config.utility_mode if config else "linear",
        "protocol": asdict(protocol),
        "institution_pressure": asdict(config.institution_pressure) if config else asdict(InstitutionPressureConfig()),
        "initial_welfare": result.initial_welfare,
        "final_welfare": result.final_welfare,
        "final_net_welfare": (
            result.final_net_welfare if result.final_net_welfare is not None else result.final_welfare
        ),
        "optimum_welfare": result.optimum_welfare,
        "welfare_ratio": result.final_welfare_ratio,
        "coordination_cost_total": result.coordination_cost_total,
        "applied_mechanisms": result.applied_mechanisms,
        "ir_violations": result.ir_violations,
        "gini_initial": result.initial_gini,
        "gini_final": result.final_gini,
        "final_institutions": deepcopy(result.final_institutions),
        "usage": usage or {},
        "error_decomposition": summarize_run_errors(result),
    }


def _idx(one_based: int, n: int, label: str) -> int:
    if one_based < 1 or one_based > n:
        raise ValueError(f"{label}_id must be in 1..{n}, got {one_based}")
    return one_based - 1



def utility_delta_for_mechanism(
    world: ExchangeWorld,
    mechanism: CompiledMechanism,
    agent_id: int,
) -> float:
    i = _idx(agent_id, world.num_agents, "agent")
    before = world.allocation[i][:]
    after = before[:]
    for tr in mechanism.transfers:
        _validate_transfer_ids(tr, world.num_agents, world.num_resources)
        if tr.from_agent == agent_id:
            after[tr.resource - 1] -= tr.quantity
        if tr.to_agent == agent_id:
            after[tr.resource - 1] += tr.quantity
    return agent_utility_for_bundle_row(world, i, after) - agent_utility_for_bundle_row(world, i, before)


def _validate_transfer_ids(tr: Transfer, num_agents: int, num_resources: int) -> None:
    _idx(tr.from_agent, num_agents, "from_agent")
    _idx(tr.to_agent, num_agents, "to_agent")
    _idx(tr.resource, num_resources, "resource")
    if tr.from_agent == tr.to_agent:
        raise ValueError("transfer from_agent and to_agent must differ")
    if (
        isinstance(tr.quantity, bool)
        or not isinstance(tr.quantity, (int, float))
        or not math.isfinite(float(tr.quantity))
        or float(tr.quantity) <= 0
    ):
        raise ValueError("transfer quantity must be a finite positive number")


def _quantity_value(value: Any) -> Quantity:
    if isinstance(value, bool):
        raise ValueError("quantity must be a finite positive number")
    if isinstance(value, int):
        q: Quantity = value
    elif isinstance(value, float):
        q = value
    else:
        q = float(str(value))
        if q.is_integer():
            q = int(q)
    if not math.isfinite(float(q)) or float(q) <= 0:
        raise ValueError("quantity must be a finite positive number")
    return q


def compiled_mechanism_feasible(world: ExchangeWorld, mechanism: CompiledMechanism) -> bool:
    _idx(mechanism.proposer_id, world.num_agents, "proposer")
    if not mechanism.verifier_ok or mechanism.confidence < 0.5:
        return False
    debits = [[0 for _ in range(world.num_resources)] for _ in range(world.num_agents)]
    debited_agents: set[int] = set()
    consenting = set(mechanism.consenting_agents)
    for aid in consenting:
        _idx(aid, world.num_agents, "consenting_agent")
    for tr in mechanism.transfers:
        _validate_transfer_ids(tr, world.num_agents, world.num_resources)
        fi = tr.from_agent - 1
        debits[fi][tr.resource - 1] += tr.quantity
        debited_agents.add(tr.from_agent)
    if not debited_agents.issubset(consenting):
        return False
    return all(
        world.allocation[i][r] >= debits[i][r]
        for i in range(world.num_agents)
        for r in range(world.num_resources)
    )


def apply_compiled_mechanism(
    world: ExchangeWorld,
    mechanism: CompiledMechanism,
    round_index: int = 0,
    controller_id: Optional[int] = None,
    ir_enforce: bool = False,
) -> RoundEvent:
    feasible = compiled_mechanism_feasible(world, mechanism)
    affected = sorted(
        {tr.from_agent for tr in mechanism.transfers} | {tr.to_agent for tr in mechanism.transfers}
    )
    deltas = {
        aid: utility_delta_for_mechanism(world, mechanism, aid)
        for aid in affected
    }
    event = RoundEvent(
        round_index=round_index,
        controller_id=controller_id if controller_id is not None else mechanism.proposer_id,
        kind=mechanism.label or "compiled_mechanism",
        proposer_id=mechanism.proposer_id,
        accepted=feasible,
        feasible=feasible,
        applied=False,
        individually_rational=None,
        proposer_delta=deltas.get(mechanism.proposer_id, 0.0),
        agent_deltas=deltas,
        welfare_after=total_welfare(world),
        message=mechanism.summary,
        institutional_updates=deepcopy(mechanism.institutional_updates),
    )
    receivers = [aid for aid in affected if aid != mechanism.proposer_id]
    if len(receivers) == 1:
        event.receiver_id = receivers[0]
        event.receiver_delta = deltas[receivers[0]]
    has_effect = bool(mechanism.transfers or mechanism.institutional_updates)
    if not has_effect:
        event.accepted = False
        event.applied = False
        event.individually_rational = None
        return event
    if not feasible:
        return event

    # IR as a control arm (diagnostic, default off): consent + feasibility still gate,
    # but when ir_enforce is on we additionally block trades that would leave any
    # participant worse off than not trading. Off (default), the violation is only
    # tagged via individually_rational, never blocked.
    if ir_enforce and affected and any(delta < -1e-9 for delta in deltas.values()):
        event.individually_rational = False
        event.ir_blocked = True
        event.applied = False
        return event

    for tr in mechanism.transfers:
        world.allocation[tr.from_agent - 1][tr.resource - 1] -= tr.quantity
        world.allocation[tr.to_agent - 1][tr.resource - 1] += tr.quantity

    if mechanism.institutional_updates:
        event.institutional_updates = apply_institutional_updates(
            world,
            mechanism.institutional_updates,
            round_index,
        )

    event.accepted = True
    event.applied = True
    event.individually_rational = all(delta >= -1e-9 for delta in deltas.values()) if affected else None
    event.welfare_after = total_welfare(world)
    return event



# ===============================================================
# Parsing helpers
# ===============================================================


def _extract_json(text: str) -> dict[str, Any]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    depth = 0
    start = -1
    for i, c in enumerate(text):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except Exception:
                    start = -1
                    continue
                if isinstance(obj, dict):
                    return obj
    raise ValueError("no JSON object found")


def _resource_id(value: Any, num_resources: int) -> int:
    if isinstance(value, int):
        rid = value
    else:
        m = re.search(r"(\d+)", str(value))
        if not m:
            raise ValueError(f"resource must be an integer or rN string, got {value!r}")
        rid = int(m.group(1))
    _idx(rid, num_resources, "resource")
    return rid


def _agent_id(value: Any, num_agents: int, label: str = "agent") -> int:
    if isinstance(value, int):
        aid = value
    else:
        m = re.search(r"(\d+)", str(value))
        if not m:
            raise ValueError(f"{label} must be an integer or aN string, got {value!r}")
        aid = int(m.group(1))
    _idx(aid, num_agents, label)
    return aid



def parse_compiled_mechanism(
    text: str,
    proposer_id: int,
    num_agents: int,
    num_resources: int,
) -> CompiledMechanism:
    obj = _extract_json(text)
    _idx(proposer_id, num_agents, "proposer")
    raw_transfers = obj.get("transfers", [])
    if not isinstance(raw_transfers, list):
        raise ValueError("transfers must be a list")
    transfers = []
    for raw in raw_transfers:
        if not isinstance(raw, dict):
            raise ValueError("each transfer must be an object")
        tr = Transfer(
            from_agent=_agent_id(raw.get("from", raw.get("from_agent")), num_agents, "from_agent"),
            to_agent=_agent_id(raw.get("to", raw.get("to_agent")), num_agents, "to_agent"),
            resource=_resource_id(raw.get("resource"), num_resources),
            quantity=_quantity_value(raw.get("quantity", raw.get("qty", 1))),
        )
        _validate_transfer_ids(tr, num_agents, num_resources)
        transfers.append(tr)
    consenting_raw = obj.get("consenting_agents", obj.get("consents", [proposer_id]))
    if not isinstance(consenting_raw, list):
        raise ValueError("consenting_agents must be a list")
    consenting = sorted({_agent_id(aid, num_agents, "consenting_agent") for aid in consenting_raw})
    for aid in consenting:
        _idx(aid, num_agents, "consenting_agent")
    institutional_updates = _normalize_institutional_updates(
        obj.get("institutional_updates", obj.get("institutions", obj.get("public_memory_updates", [])))
    )
    return CompiledMechanism(
        proposer_id=proposer_id,
        label=str(obj.get("mechanism_label", obj.get("label", "compiled_mechanism"))),
        summary=str(obj.get("summary", "")),
        transfers=transfers,
        consenting_agents=consenting,
        confidence=float(obj.get("confidence", 0.0)),
        institutional_updates=institutional_updates,
        verifier_ok=bool(obj.get("verifier_ok", True)),
        verifier_reason=str(obj.get("verifier_reason", "")),
    )



# ===============================================================
# Policies
# ===============================================================



def _is_gemini_model(model: Optional[str]) -> bool:
    return bool(model) and str(model).split("/")[-1].startswith("gemini")


def _configure_gemini_context_cache_defaults(*models: Optional[str]) -> bool:
    if not any(_is_gemini_model(model) for model in models):
        return False
    os.environ.setdefault("GEMINI_CONTEXT_CACHE", "1")
    os.environ.setdefault("GEMINI_CONTEXT_CACHE_MARKER", _CACHEABLE_CONTEXT_MARKER)
    os.environ.setdefault("GEMINI_CONTEXT_CACHE_MIN_CHARS", "2000")
    return os.environ.get("GEMINI_CONTEXT_CACHE", "").strip().lower() not in {"0", "false", "no", "off"}


class LLMCompilerVerifierPolicy:
    """Free-form multi-agent round policy with compiler/verifier execution.

    The proposer, responders, and finalizer are economic agents. The compiler and
    verifier are separate LLM roles that convert the transcript to the generic
    `CompiledMechanism` ledger schema and check semantic faithfulness.
    """

    def __init__(
        self,
        model: str = "google/gemini-3.5-flash",
        compiler_model: Optional[str] = None,
        verifier_model: Optional[str] = None,
        max_tokens: int = 1200,
        protocol: Optional[ProtocolConfig] = None,
        batch_enabled: bool = False,
        temperature: float = 0.0,
        sample: int = 0,
    ):
        if call_llm is None:
            raise RuntimeError("llm_agent unavailable")
        self.model = model
        self.compiler_model = compiler_model or model
        self.verifier_model = verifier_model or self.compiler_model
        _configure_gemini_context_cache_defaults(self.model, self.compiler_model, self.verifier_model)
        self.max_tokens = max_tokens
        self.protocol = protocol or ProtocolConfig()
        self.batch_enabled = batch_enabled
        self.temperature = float(temperature)
        self.sample = int(sample)
        self.call_records: list[dict[str, Any]] = []

    def _role_sampling(self, role: str) -> tuple[float, int]:
        # Sample the public economic-agent roles only. Keep compiler/verifier
        # deterministic so execution differences come from agent behavior.
        if role in {"communication", "proposal", "response", "finalization"}:
            return self.temperature, self.sample
        return 0.0, 0

    def _record_call(
        self,
        role: str,
        response: Any,
        model: str,
        agent_id: Optional[int] = None,
        round_index: Optional[int] = None,
        batched: bool = False,
    ) -> None:
        usage = getattr(response, "usage", None) or {}
        self.call_records.append(
            {
                "role": role,
                "agent_id": agent_id,
                "round_index": round_index,
                "model": getattr(response, "model", model),
                "cached": bool(getattr(response, "cached", False)),
                "batched": batched,
                "input_tokens": int(usage.get("input_tokens") or 0),
                "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
                "reasoning_tokens": int(usage.get("reasoning_tokens") or 0),
                "estimated_cost_usd": getattr(response, "estimated_cost_usd", None),
                "cost_note": getattr(response, "cost_note", ""),
            }
        )

    def _call(
        self,
        role: str,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        agent_id: Optional[int] = None,
        round_index: Optional[int] = None,
    ) -> Any:
        temperature, sample = self._role_sampling(role)
        response = call_llm(
            system,
            prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            sample=sample,
        )
        self._record_call(role, response, model, agent_id=agent_id, round_index=round_index)
        return response

    def _batch_call(
        self,
        role: str,
        calls: list[dict[str, Any]],
        model: str,
    ) -> list[Any]:
        if not calls:
            return []
        if not self.batch_enabled or call_llm_batch is None:
            return [
                self._call(
                    role,
                    call["system"],
                    call["prompt"],
                    model=model,
                    max_tokens=call["max_tokens"],
                    agent_id=call.get("agent_id"),
                    round_index=call.get("round_index"),
                )
                for call in calls
            ]
        responses = call_llm_batch(
            [
                {
                    "system": call["system"],
                    "user": call["prompt"],
                    "max_tokens": call["max_tokens"],
                    "temperature": self._role_sampling(role)[0],
                    "sample": self._role_sampling(role)[1],
                }
                for call in calls
            ],
            model=model,
        )
        if len(responses) != len(calls):
            raise RuntimeError(f"batch returned {len(responses)} responses for {len(calls)} calls")
        for call, response in zip(calls, responses):
            self._record_call(
                role,
                response,
                model,
                agent_id=call.get("agent_id"),
                round_index=call.get("round_index"),
                batched=True,
            )
        return responses

    def usage_summary(self) -> dict[str, Any]:
        by_role: dict[str, dict[str, Any]] = {}
        for record in self.call_records:
            role = record["role"]
            bucket = by_role.setdefault(
                role,
                {
                    "calls": 0,
                    "fresh_calls": 0,
                    "cached_calls": 0,
                    "batched_calls": 0,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "reasoning_tokens": 0,
                    "provider_cache_hit_rate": None,
                    "estimated_cost_usd": 0.0,
                    "unknown_cost_calls": 0,
                },
            )
            bucket["calls"] += 1
            bucket["cached_calls" if record["cached"] else "fresh_calls"] += 1
            if record.get("batched"):
                bucket["batched_calls"] += 1
            for key in ["input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "reasoning_tokens"]:
                bucket[key] += record[key]
            if record["estimated_cost_usd"] is None:
                if not record["cached"]:
                    bucket["unknown_cost_calls"] += 1
            else:
                bucket["estimated_cost_usd"] += float(record["estimated_cost_usd"])

        total = {
            "calls": len(self.call_records),
            "fresh_calls": sum(1 for r in self.call_records if not r["cached"]),
            "cached_calls": sum(1 for r in self.call_records if r["cached"]),
            "batched_calls": sum(1 for r in self.call_records if r.get("batched")),
            "input_tokens": sum(r["input_tokens"] for r in self.call_records),
            "cached_input_tokens": sum(r["cached_input_tokens"] for r in self.call_records),
            "output_tokens": sum(r["output_tokens"] for r in self.call_records),
            "total_tokens": sum(r["total_tokens"] for r in self.call_records),
            "reasoning_tokens": sum(r["reasoning_tokens"] for r in self.call_records),
            "provider_cache_hit_rate": None,
            "estimated_cost_usd": round(
                sum(float(r["estimated_cost_usd"]) for r in self.call_records if r["estimated_cost_usd"] is not None),
                10,
            ),
            "unknown_cost_calls": sum(
                1 for r in self.call_records if r["estimated_cost_usd"] is None and not r["cached"]
            ),
            "by_role": by_role,
        }
        if total["input_tokens"]:
            total["provider_cache_hit_rate"] = round(total["cached_input_tokens"] / total["input_tokens"], 6)
        for bucket in by_role.values():
            bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"], 10)
            if bucket["input_tokens"]:
                bucket["provider_cache_hit_rate"] = round(bucket["cached_input_tokens"] / bucket["input_tokens"], 6)
        return total

    def propose_text(
        self,
        world: ExchangeWorld,
        agent_id: int,
        round_index: int,
        history: list[RoundEvent],
        communication_texts: Optional[dict[int, str]] = None,
    ) -> str:
        prompt = _freeform_proposal_prompt(
            world,
            agent_id,
            round_index,
            history,
            communication_texts,
            protocol=self.protocol,
        )
        return self._call(
            "proposal",
            _FREEFORM_SYSTEM,
            prompt,
            model=self.model,
            max_tokens=self.max_tokens,
            agent_id=agent_id,
            round_index=round_index,
        ).text.strip()

    def communication_text(
        self,
        world: ExchangeWorld,
        agent_id: int,
        round_index: int,
        history: list[RoundEvent],
    ) -> str:
        prompt = _freeform_communication_prompt(world, agent_id, round_index, history, protocol=self.protocol)
        return self._call(
            "communication",
            _FREEFORM_SYSTEM,
            prompt,
            model=self.model,
            max_tokens=self.max_tokens,
            agent_id=agent_id,
            round_index=round_index,
        ).text.strip()

    def communication_texts(
        self,
        world: ExchangeWorld,
        agent_ids: list[int],
        round_index: int,
        history: list[RoundEvent],
    ) -> dict[int, str]:
        calls = [
            {
                "system": _FREEFORM_SYSTEM,
                "prompt": _freeform_communication_prompt(world, aid, round_index, history, protocol=self.protocol),
                "max_tokens": self.max_tokens,
                "agent_id": aid,
                "round_index": round_index,
            }
            for aid in agent_ids
        ]
        responses = self._batch_call("communication", calls, self.model)
        return {aid: response.text.strip() for aid, response in zip(agent_ids, responses)}

    def respond_text(
        self,
        world: ExchangeWorld,
        agent_id: int,
        transcript: RoundTranscript,
        history: list[RoundEvent],
    ) -> str:
        prompt = _freeform_response_prompt(world, agent_id, transcript, history, protocol=self.protocol)
        return self._call(
            "response",
            _FREEFORM_SYSTEM,
            prompt,
            model=self.model,
            max_tokens=self.max_tokens,
            agent_id=agent_id,
            round_index=transcript.round_index,
        ).text.strip()

    def response_texts(
        self,
        world: ExchangeWorld,
        agent_ids: list[int],
        transcript: RoundTranscript,
        history: list[RoundEvent],
    ) -> dict[int, str]:
        calls = [
            {
                "system": _FREEFORM_SYSTEM,
                "prompt": _freeform_response_prompt(world, aid, transcript, history, protocol=self.protocol),
                "max_tokens": self.max_tokens,
                "agent_id": aid,
                "round_index": transcript.round_index,
            }
            for aid in agent_ids
        ]
        responses = self._batch_call("response", calls, self.model)
        return {aid: response.text.strip() for aid, response in zip(agent_ids, responses)}

    def finalize_text(
        self,
        world: ExchangeWorld,
        agent_id: int,
        transcript: RoundTranscript,
        history: list[RoundEvent],
    ) -> str:
        prompt = _freeform_finalize_prompt(world, agent_id, transcript, history, protocol=self.protocol)
        return self._call(
            "finalization",
            _FREEFORM_SYSTEM,
            prompt,
            model=self.model,
            max_tokens=self.max_tokens,
            agent_id=agent_id,
            round_index=transcript.round_index,
        ).text.strip()

    def private_acceptance_text(
        self,
        world: ExchangeWorld,
        agent_id: int,
        transcript: RoundTranscript,
        mechanism: CompiledMechanism,
        history: list[RoundEvent],
    ) -> str:
        prompt = _private_acceptance_prompt(
            world,
            agent_id,
            transcript,
            mechanism,
            history,
            protocol=self.protocol,
        )
        return self._call(
            "private_acceptance",
            _PRIVATE_ACCEPTANCE_SYSTEM,
            prompt,
            model=self.model,
            max_tokens=min(self.max_tokens, 800),
            agent_id=agent_id,
            round_index=transcript.round_index,
        ).text.strip()

    def private_acceptance_texts(
        self,
        world: ExchangeWorld,
        agent_ids: list[int],
        transcript: RoundTranscript,
        mechanism: CompiledMechanism,
        history: list[RoundEvent],
    ) -> dict[int, str]:
        calls = [
            {
                "system": _PRIVATE_ACCEPTANCE_SYSTEM,
                "prompt": _private_acceptance_prompt(
                    world,
                    aid,
                    transcript,
                    mechanism,
                    history,
                    protocol=self.protocol,
                ),
                "max_tokens": min(self.max_tokens, 800),
                "agent_id": aid,
                "round_index": transcript.round_index,
            }
            for aid in agent_ids
        ]
        responses = self._batch_call("private_acceptance", calls, self.model)
        return {aid: response.text.strip() for aid, response in zip(agent_ids, responses)}

    def compile_transcript(self, world: ExchangeWorld, transcript: RoundTranscript) -> CompiledMechanism:
        prompt = _compile_transcript_prompt(world, transcript, protocol=self.protocol)
        text = self._call(
            "compiler",
            _COMPILER_SYSTEM,
            prompt,
            model=self.compiler_model,
            max_tokens=max(self.max_tokens, 4000),
        ).text
        try:
            mechanism = parse_compiled_mechanism(
                text,
                proposer_id=transcript.controller_id,
                num_agents=world.num_agents,
                num_resources=world.num_resources,
            )
            return enforce_transcript_support(world, transcript, mechanism, self.protocol)
        except Exception as e:
            return CompiledMechanism(
                proposer_id=transcript.controller_id,
                label="compile_failure",
                summary=f"compile failure: {e}",
                transfers=[],
                consenting_agents=[transcript.controller_id],
                confidence=0.0,
                verifier_ok=False,
                verifier_reason=str(e),
            )

    def verify_compilation(
        self,
        world: ExchangeWorld,
        transcript: RoundTranscript,
        mechanism: CompiledMechanism,
    ) -> CompiledMechanism:
        prompt = _verify_compilation_prompt(world, transcript, mechanism, protocol=self.protocol)
        text = self._call(
            "verifier",
            _VERIFIER_SYSTEM,
            prompt,
            model=self.verifier_model,
            max_tokens=max(self.max_tokens, 4000),
        ).text
        try:
            obj = _extract_json(text)
            ok = bool(obj.get("verifier_ok", obj.get("ok", False)))
            confidence = min(float(obj.get("confidence", mechanism.confidence)), mechanism.confidence)
            reason = str(obj.get("reason", obj.get("verifier_reason", "")))
            verified = replace(
                mechanism,
                verifier_ok=ok,
                confidence=confidence,
                verifier_reason=reason,
            )
            return enforce_transcript_support(world, transcript, verified, self.protocol)
        except Exception as e:
            return replace(
                mechanism,
                verifier_ok=False,
                verifier_reason=f"verifier parse failure: {e}",
            )


_SYSTEM = (
    "You are a self-interested agent in a hidden-utility exchange economy. "
    "Maximize your own private utility. Other agents do not know your utility, "
    "and you do not know theirs. Return valid JSON only."
)

_FREEFORM_SYSTEM = (
    "You are a self-interested agent in a hidden-utility exchange economy. "
    "Maximize your own private utility. Other agents do not know your utility, "
    "and you do not know theirs. You may write natural language, but be concrete "
    "about public messages, settlement rows, consent conditions, public state updates, "
    "or rejections. "
    "Do not output private calculations, scratchpad, hidden reasoning, or analysis. "
    "Only output the public message or public action that other agents should see."
)

_PRIVATE_ACCEPTANCE_SYSTEM = (
    "You are a self-interested agent privately checking whether to approve finalized "
    "debits from your own resource bundle. Maximize your own private utility. Work through "
    "your own utility before and after the settlement, then end with the decision as JSON."
)

_COMPILER_SYSTEM = (
    "You are a mechanism compiler. Convert a free-form multi-agent transcript into "
    "minimal ledger effects: concrete transfers plus optional public institutional memory. "
    "Do not invent consent, transfers, or institutional terms. "
    "If the transcript does not clearly authorize a transfer, omit it. Return complete "
    "JSON only, with no markdown fences or prose. Do not truncate the JSON."
)

_VERIFIER_SYSTEM = (
    "You are a semantic verifier. Check whether a compiled ledger transfer bundle is "
    "faithful to the transcript, including any public institutional memory updates. "
    "You do not judge whether the deal is good, fair, or individually rational. "
    "You only check semantic support and consent. Return JSON only."
)


_PUBLIC_ACTION_ENVELOPE = (
    "Use this universal public-action envelope exactly:\n"
    "PUBLIC ACTION\n"
    "ADDRESSEES:\n"
    "<one agent, multiple named agents, all agents, or any agent; or `none`>\n"
    "MESSAGE:\n"
    "<public message only>\n"
    "RESPONSE REQUEST:\n"
    "<who should respond, opt in, reveal offers, authorize, counter, or `none`>\n"
    "SETTLEMENT:\n"
    "from | to | resource | quantity | condition-or-consent\n"
    "<one row per proposed or finalized transfer; multiple rows may involve different agents; or `none`>\n"
    "CONSENT CONDITIONS:\n"
    "<whose explicit consent is required for each debit, or `none`>\n"
    "PUBLIC STATE UPDATE:\n"
    "<any public rule, memory, commitment, convention, institution, amendment, or retirement to persist, or `none`>\n"
    "NO-TRANSFER FALLBACK:\n"
    "<what happens if settlement conditions or consent are missing>\n"
)


def _strict_self_interest_instruction(protocol: Optional[ProtocolConfig]) -> str:
    protocol = protocol or ProtocolConfig()
    if not protocol.strict_self_interest:
        return ""
    return (
        "Strict self-interest rule: Privately compute your own utility delta before proposing, "
        "accepting, authorizing, or finalizing any settlement row that affects your bundle. "
        "If a proposed debit/credit bundle is negative, zero, ambiguous, or depends on missing "
        "counterparty consent, Reject or counter instead of consenting. Do not quote numeric "
        "private marginal utilities, total utility numbers, or your full private utility table; "
        "use qualitative public language and exact settlement quantities only.\n\n"
    )


def _institution_support_instruction(protocol: Optional[ProtocolConfig]) -> str:
    protocol = protocol or ProtocolConfig()
    if not protocol.require_final_public_state_update_for_institutions:
        return ""
    return (
        "Public-state strictness: persistent public memory exists only when the controller's "
        "final PUBLIC STATE UPDATE section explicitly creates, amends, or retires it. Do not "
        "treat rejected proposals, no-transfer fallbacks, or round summaries as institutions.\n\n"
    )


def _anti_anchor_example_instruction(protocol: Optional[ProtocolConfig]) -> str:
    protocol = protocol or ProtocolConfig()
    example = protocol.anti_anchor_mechanism_example.strip()
    if not example:
        return ""
    return (
        "Anti-anchor example, not a recommendation: the following is a deliberately bad-fit, "
        "non-transfer example that is against this environment's incentive because it increases "
        "search/contact burden instead of reducing it. Do not copy it, do not lock in to it, "
        "and do not treat it as a named template. Use it only to remind yourself that mechanism "
        "space includes procedures, information rules, state updates, amendment rules, and bad "
        "ideas that self-interested agents should reject or redesign.\n"
        f"Example to evaluate critically:\n{example}\n\n"
    )


def _atomic_commit_instruction(protocol: Optional[ProtocolConfig]) -> str:
    protocol = protocol or ProtocolConfig()
    if not protocol.atomic_commit:
        return ""
    return (
        "Protocol simplification arm: one-step atomic commit is active. The controller proposes "
        "exact executable terms once. Responders may accept or reject those exact terms; amendments "
        "and counteroffers are non-executable cheap talk for later rounds. There is no controller "
        "amendment/finalization phase and no post-finalization private acceptance check.\n\n"
    )


def _partial_clearing_instruction(protocol: Optional[ProtocolConfig]) -> str:
    protocol = protocol or ProtocolConfig()
    if not protocol.partial_clearing:
        return ""
    return (
        "Consent-subset finalization rule: if a proposal, response set, or public arrangement contains "
        "multiple settlement rows or sub-bundles, the controller may finalize any independent consented "
        "subset that is feasible and supported by explicit debit consent. A rejection or missing consent "
        "for one independent leg does not by itself block other independent rows. Respect any explicit "
        "all-or-nothing condition, package dependency, minimum-fill condition, or counterpart-transfer "
        "condition; dependent rows clear together or not at all. The controller finalization must list "
        "exactly the selected rows and consent evidence, and the compiler/verifier should execute only "
        "those selected supported rows.\n\n"
    )


def _information_reveal_profile(protocol: Optional[ProtocolConfig]) -> str:
    protocol = protocol or ProtocolConfig()
    profile = (protocol.information_reveal_profile or "legacy").strip()
    return profile or "legacy"


def _uses_structured_information_reveal(protocol: Optional[ProtocolConfig]) -> bool:
    return _information_reveal_profile(protocol) != "legacy"


def _information_reveal_instruction(protocol: Optional[ProtocolConfig]) -> str:
    protocol = protocol or ProtocolConfig()
    profile = _information_reveal_profile(protocol)
    if profile == "legacy":
        return ""

    lines = [
        f"Information reveal protocol: {profile}.",
        (
            "Agents receive the environment rules below; hidden private utility tables and "
            "non-visible allocation rows stay hidden unless an agent chooses to reveal them."
        ),
    ]
    if protocol.visibility_mode == "limited_contact":
        lines.append(
            "Visibility/contact rule: observation is contact-limited; each agent sees only its "
            "own bundle plus directly visible/contactable agents."
        )
    elif protocol.show_full_allocation:
        lines.append("Visibility/contact rule: the full public allocation matrix is visible.")

    if protocol.public_broadcast:
        lines.append("Broadcast visibility rule: controller PUBLIC ACTION messages can be seen by all agents.")
    if not protocol.public_broadcast:
        lines.append(
            "Public response rule: no public response expansion is available in this condition; "
            "after a proposal, only visible/contactable agents are prompted to respond."
        )
    elif protocol.response_scope == "solicited_public":
        lines.append(
            "Public response affordance: if a controller's PUBLIC ACTION uses ADDRESSEES to ask "
            "all agents, any agent, or anyone and uses RESPONSE REQUEST to ask for responses, "
            "opt-ins, revealed offers, counters, or authorizations, then non-contact agents may "
            "be prompted to respond. If the controller does not make such a public request, only "
            "visible/contactable agents respond."
        )
    elif protocol.response_scope == "all":
        lines.append(
            "Public response rule: all non-controller agents are prompted to respond after every controller proposal."
        )
    elif protocol.response_scope == "visible_only":
        lines.append("Public response rule: only visible/contactable agents respond after a proposal.")
    return "\n".join(lines) + "\n\n"


def _coordination_pressure_text(pressure: InstitutionPressureConfig) -> str:
    parts = []
    if pressure.recurring_demand_mode != "none":
        parts.append("repeated demand conditions are stable across rounds")
    if pressure.search_cost_per_public_round:
        parts.append(
            f"public search and contact frictions reduce your private payoff: search_cost_per_agent="
            f"{pressure.search_cost_per_public_round}"
        )
    if pressure.search_cost_per_contacted_agent:
        parts.append(
            "public response/search cost is charged per prompted responder: "
            f"search_cost_per_contacted_agent={pressure.search_cost_per_contacted_agent}; "
            "targeted requests to fewer agents cost less than broad requests"
        )
    if pressure.contact_expansion_cost:
        parts.append(f"expanded contact costs {pressure.contact_expansion_cost} per use")
    if pressure.standing_rule_bonus_or_cost_saving:
        parts.append(
            "active reusable public rules can save later coordination cost by "
            f"{pressure.standing_rule_bonus_or_cost_saving} total per round"
        )
    if not parts:
        return ""
    return "Coordination pressure: " + "; ".join(parts) + "."


def _legacy_coordination_pressure_text(pressure: InstitutionPressureConfig) -> str:
    if (
        not pressure.search_cost_per_public_round
        and not pressure.search_cost_per_contacted_agent
        and not pressure.contact_expansion_cost
        and not pressure.standing_rule_bonus_or_cost_saving
    ):
        return ""
    return (
        "Coordination pressure: public search and contact frictions reduce your private payoff. "
        f"Each public round has search_cost_per_agent={pressure.search_cost_per_public_round}; "
        f"search_cost_per_contacted_agent={pressure.search_cost_per_contacted_agent}; "
        f"contact_expansion_cost={pressure.contact_expansion_cost}; "
        f"each active reusable public rule can save total coordination cost by "
        f"{pressure.standing_rule_bonus_or_cost_saving} in later rounds."
    )


def _information_reveal_expected_fragments(
    protocol: ProtocolConfig,
    world: Optional[ExchangeWorld] = None,
) -> tuple[list[str], list[str]]:
    required = [
        f"Information reveal protocol: {_information_reveal_profile(protocol)}",
        "Resource names:",
        "Resource quantities are divisible",
        "Public institutions / standing rules / public commitments",
        "Recent public history:",
        "Use this universal public-action envelope exactly",
        "ADDRESSEES:",
        "RESPONSE REQUEST:",
    ]
    forbidden = [
        "response_scope",
        "solicited_public",
        "public_broadcast=",
        "visible_agents_per_agent",
        "Public broadcast path is available",
        "anti-anchor example",
        "rotating unanimity committee",
    ]

    if protocol.visibility_mode == "limited_contact":
        required.extend(
            [
                "Visibility/contact rule: observation is contact-limited",
                "Visible/contactable agents this round",
                "Visible allocation rows",
            ]
        )
    elif protocol.show_full_allocation:
        required.append("Public allocation matrix rows are agents")
    if protocol.show_resource_totals:
        required.append("Resource totals:")
    if protocol.settlement_row_limit is not None:
        required.append("Final settlement row limit:")
    if protocol.direct_contact_scope == "visible_only":
        required.append("Direct targeted contact should use visible/contactable agents")
    if protocol.strict_self_interest:
        required.append("Strict self-interest rule")
    if protocol.atomic_commit:
        required.append("one-step atomic commit is active")
    if protocol.partial_clearing:
        required.extend(
            [
                "Consent-subset finalization rule",
                "independent consented subset",
                "all-or-nothing",
            ]
        )
    else:
        forbidden.append("Consent-subset finalization rule")
    if protocol.anti_anchor_mechanism_example:
        forbidden.append(protocol.anti_anchor_mechanism_example.strip())
    if not protocol.show_full_allocation:
        forbidden.append("Public allocation matrix rows are agents")

    if not protocol.public_broadcast:
        required.append("Public response rule: no public response expansion is available")
        required.append("only visible/contactable agents are prompted to respond")
        forbidden.append("Public response affordance")
    elif protocol.response_scope == "solicited_public":
        required.extend(
            [
                "Broadcast visibility rule: controller PUBLIC ACTION messages can be seen by all agents",
                "Public response affordance:",
                "uses ADDRESSEES to ask",
                "uses RESPONSE REQUEST to ask",
                "non-contact agents may be prompted to respond",
                "only visible/contactable agents respond",
            ]
        )
    elif protocol.response_scope == "all":
        required.append("all non-controller agents are prompted to respond")
    elif protocol.response_scope == "visible_only":
        required.append("only visible/contactable agents respond after a proposal")

    if world is not None:
        pressure = world.institution_pressure
        has_pressure = bool(
            pressure.search_cost_per_public_round
            or pressure.search_cost_per_contacted_agent
            or pressure.contact_expansion_cost
            or pressure.standing_rule_bonus_or_cost_saving
            or pressure.recurring_demand_mode != "none"
        )
        if has_pressure:
            required.append("Coordination pressure:")
            if pressure.recurring_demand_mode != "none":
                required.append("repeated demand conditions are stable across rounds")
            if pressure.search_cost_per_public_round:
                required.append("search_cost_per_agent")
            if pressure.search_cost_per_contacted_agent:
                required.append("search_cost_per_contacted_agent")
                required.append("targeted requests to fewer agents cost less than broad requests")
            if pressure.contact_expansion_cost:
                required.append("expanded contact costs")
            if pressure.standing_rule_bonus_or_cost_saving:
                required.append("active reusable public rules can save")
        else:
            forbidden.extend(
                [
                    "Coordination pressure:",
                    "repeated demand conditions are stable across rounds",
                    "search_cost_per_agent",
                    "search_cost_per_contacted_agent",
                    "contact_expansion_cost",
                    "standing_rule_bonus",
                    "active reusable public rules can save",
                ]
            )
        if pressure.recurring_demand_mode == "none":
            forbidden.append("repeated demand conditions are stable across rounds")
        if not pressure.search_cost_per_contacted_agent:
            forbidden.append("search_cost_per_contacted_agent")
            forbidden.append("targeted requests to fewer agents cost less than broad requests")
        if not pressure.contact_expansion_cost:
            forbidden.append("expanded contact costs")
        if not pressure.standing_rule_bonus_or_cost_saving:
            forbidden.append("active reusable public rules can save")
    return required, forbidden


def validate_information_reveal_texts(
    protocol: ProtocolConfig,
    texts: dict[str, str],
    *,
    world: Optional[ExchangeWorld] = None,
) -> InformationRevealAudit:
    profile = _information_reveal_profile(protocol)
    if profile == "legacy":
        return InformationRevealAudit(profile=profile, ok=True, violations=[], checked_texts=list(texts))
    violations: list[str] = []
    if profile != "clean_market_v1":
        violations.append(f"unknown information reveal profile: {profile}")

    required, forbidden = _information_reveal_expected_fragments(protocol, world)
    for label, text in texts.items():
        lowered = text.lower()
        for fragment in required:
            if fragment.lower() not in lowered:
                violations.append(f"{label}: missing required disclosure: {fragment}")
        for fragment in forbidden:
            fragment = fragment.strip()
            if fragment and fragment.lower() in lowered:
                violations.append(f"{label}: found forbidden disclosure: {fragment}")
    return InformationRevealAudit(
        profile=profile,
        ok=not violations,
        violations=violations,
        checked_texts=list(texts),
    )


def validate_information_reveal_protocol(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    *,
    history: Optional[list[RoundEvent]] = None,
    agent_ids: Optional[list[int]] = None,
    controller_id: int = 1,
) -> InformationRevealAudit:
    history = history or []
    agent_ids = agent_ids or list(range(1, world.num_agents + 1))
    texts: dict[str, str] = {}
    for aid in agent_ids:
        _idx(aid, world.num_agents, "information reveal audit agent")
        texts[f"communication:a{aid}"] = _freeform_communication_prompt(
            world,
            agent_id=aid,
            round_index=1,
            history=history,
            protocol=protocol,
        )
    _idx(controller_id, world.num_agents, "information reveal audit controller")
    texts[f"proposal:a{controller_id}"] = _freeform_proposal_prompt(
        world,
        agent_id=controller_id,
        round_index=1,
        history=history,
        communication_texts={},
        protocol=protocol,
    )
    dummy_transcript = RoundTranscript(
        round_index=1,
        controller_id=controller_id,
        proposal_text=(
            "PUBLIC ACTION\n"
            "ADDRESSEES:\n"
            "none\n"
            "MESSAGE:\n"
            "Audit placeholder proposal.\n"
            "RESPONSE REQUEST:\n"
            "none\n"
            "SETTLEMENT:\n"
            "none\n"
            "CONSENT CONDITIONS:\n"
            "none\n"
            "PUBLIC STATE UPDATE:\n"
            "none\n"
            "NO-TRANSFER FALLBACK:\n"
            "No transfer."
        ),
        response_texts={},
        final_text="",
        communication_texts={},
    )
    for aid in agent_ids:
        if aid == controller_id:
            continue
        texts[f"response:a{aid}"] = _freeform_response_prompt(
            world,
            agent_id=aid,
            transcript=dummy_transcript,
            history=history,
            protocol=protocol,
        )
    if not protocol.atomic_commit:
        texts[f"finalize:a{controller_id}"] = _freeform_finalize_prompt(
            world,
            agent_id=controller_id,
            transcript=dummy_transcript,
            history=history,
            protocol=protocol,
        )
    return validate_information_reveal_texts(protocol, texts, world=world)


def _ensure_information_reveal_protocol(
    world: ExchangeWorld,
    protocol: ProtocolConfig,
    history: list[RoundEvent],
    *,
    controller_id: int,
) -> None:
    if not _uses_structured_information_reveal(protocol):
        return
    audit = validate_information_reveal_protocol(
        world,
        protocol,
        history=history,
        agent_ids=list(range(1, world.num_agents + 1)),
        controller_id=controller_id,
    )
    if not audit.ok:
        raise ValueError(audit.format())


def _cacheable_protocol_context_text(protocol: Optional[ProtocolConfig]) -> str:
    sections = []
    info = _information_reveal_instruction(protocol).strip()
    if info:
        sections.append(f"Environment information reveal contract:\n{info}")
    atomic = _atomic_commit_instruction(protocol).strip()
    if atomic:
        sections.append(f"Atomic commit protocol:\n{atomic}")
    partial = _partial_clearing_instruction(protocol).strip()
    if partial:
        sections.append(f"Settlement finalization protocol:\n{partial}")
    strict = _strict_self_interest_instruction(protocol).strip()
    if strict:
        sections.append(f"Shared self-interest discipline:\n{strict}")
    anti_anchor = _anti_anchor_example_instruction(protocol).strip()
    if anti_anchor:
        sections.append(f"Mechanism-space anti-anchor guidance:\n{anti_anchor}")
    sections.append(f"Shared output interface:\n{_PUBLIC_ACTION_ENVELOPE.rstrip()}")
    return "\n\n".join(sections)


def _communication_summary(communication_texts: Optional[dict[int, str]]) -> str:
    if not communication_texts:
        return "No public observation / cheap-talk messages yet."
    return "\n".join(
        f"a{aid}: {text}" for aid, text in sorted(communication_texts.items())
    )


def _history_outcome_label(event: RoundEvent) -> str:
    if event.applied and event.institutional_updates:
        return "applied_resource_and_public_state_update"
    if event.applied:
        return "applied_resource_transfer"
    if event.accepted and event.institutional_updates:
        return "accepted_public_state_update"
    if event.accepted:
        return "accepted_no_resource_transfer"
    return "no_transfer"


def _history_summary(history: list[RoundEvent], limit: int = 8) -> str:
    if not history:
        return "No previous rounds."
    rows = []
    for e in history[-limit:]:
        inst = f" institution_updates={len(e.institutional_updates)}" if e.institutional_updates else ""
        rows.append(
            f"round {e.round_index}: controller a{e.controller_id} outcome={_history_outcome_label(e)} "
            f"accepted={e.accepted} applied={e.applied}{inst} welfare={e.welfare_after:.2f}"
        )
    return "\n".join(rows)


def _shared_public_context_text(
    world: ExchangeWorld,
    history: list[RoundEvent],
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    protocol = protocol or ProtocolConfig()
    institutions = active_institutions(world)
    lines = [
        f"Resource names: {world.resource_names}",
        "Resource quantities are divisible: transfers may use finite positive fractional amounts.",
    ]
    if world.money_good_index is not None:
        mname = world.resource_names[world.money_good_index]
        lines.append(
            f"'{mname}' is a transferable numeraire: every agent values each unit of {mname} equally and "
            f"linearly (value 1 per unit, no diminishing returns). {mname} transfers are pure side-payments: "
            f"include {mname} in a settlement to compensate a counterparty and make an otherwise-unequal "
            f"trade mutually acceptable to both sides."
        )
    if protocol.visibility_mode == "limited_contact" and not _uses_structured_information_reveal(protocol):
        if protocol.public_broadcast:
            lines.append(
                "Public broadcast path is available: your PUBLIC ACTION message can be seen by all agents in the observation phase."
            )
        if protocol.communication_scope in {"controller_contacts", "visible_only"}:
            lines.append(
                "Observation is contact-limited: only the controller and directly visible/contactable agents are prompted before the proposal."
            )
    elif protocol.show_full_allocation:
        lines.extend(
            [
                f"Public allocation matrix rows are agents a1..a{world.num_agents}:",
                json.dumps(world.copy_allocation()),
            ]
        )
    if protocol.show_resource_totals:
        lines.append(f"Resource totals: {resource_totals(world.allocation)}")
    if protocol.settlement_row_limit is not None:
        lines.append(
            f"Final settlement row limit: at most {protocol.settlement_row_limit} rows unless no transfer is finalized."
        )
    pressure = world.institution_pressure
    if _uses_structured_information_reveal(protocol):
        coordination_pressure = _coordination_pressure_text(pressure)
    else:
        coordination_pressure = _legacy_coordination_pressure_text(pressure)
    if coordination_pressure:
        lines.append(coordination_pressure)
    if institutions:
        lines.extend(
            [
                "Public institutions / standing rules / public commitments from prior rounds:",
                json.dumps(institutions, ensure_ascii=False),
            ]
        )
    else:
        lines.append("Public institutions / standing rules / public commitments from prior rounds: none.")
    lines.extend(["Recent public history:", _history_summary(history)])
    lines.extend(["Cacheable shared protocol instructions:", _cacheable_protocol_context_text(protocol)])
    return "\n".join(lines)


def _viewer_specific_context_text(
    world: ExchangeWorld,
    protocol: Optional[ProtocolConfig] = None,
    viewer_id: Optional[int] = None,
) -> str:
    protocol = protocol or ProtocolConfig()
    if protocol.visibility_mode != "limited_contact" or viewer_id is None:
        return "none."
    visible = visible_agents_for(protocol, world, viewer_id)
    visible_rows = {f"a{aid}": world.allocation[aid - 1][:] for aid in visible}
    lines = [
        f"Visible/contactable agents this round for a{viewer_id}: {[f'a{aid}' for aid in visible]}",
        f"Visible allocation rows: {json.dumps(visible_rows)}",
    ]
    if protocol.direct_contact_scope == "visible_only":
        lines.append(
            "Direct targeted contact should use visible/contactable agents unless a non-visible agent publicly responds or explicitly consents."
        )
    return "\n".join(lines)


def _public_context_text(
    world: ExchangeWorld,
    history: list[RoundEvent],
    protocol: Optional[ProtocolConfig] = None,
    viewer_id: Optional[int] = None,
) -> str:
    return "\n\n".join(
        [
            _shared_public_context_text(world, history, protocol),
            _CACHEABLE_CONTEXT_MARKER,
            _viewer_specific_context_text(world, protocol, viewer_id),
        ]
    )


def _private_context_text(
    world: ExchangeWorld,
    agent_id: int,
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    st = world.public_state(agent_id)
    lines = [
        f"You are agent a{agent_id}.",
        f"Your private marginal utilities for resources r1..r{world.num_resources}:",
        json.dumps(st["own_preferences"]),
        f"Your current bundle: {st['own_allocation']}; utility={st['own_utility']:.3f}",
    ]
    if protocol is not None and protocol.reveal_all_private_values:
        # Full-information condition (W_full ceiling arm): disclose every agent's
        # private utility table to every viewer. Rendered in the PER-VIEWER block
        # (after the cacheable shared prefix) so the shared-prefix invariant holds.
        lines.append(
            f"Full information is in effect: every agent's private marginal utilities "
            f"for r1..r{world.num_resources} are disclosed below."
        )
        for j in range(world.num_agents):
            lines.append(f"  a{j + 1}: {json.dumps(world.preferences[j])}")
    return "\n".join(lines)


def _freeform_communication_prompt(
    world: ExchangeWorld,
    agent_id: int,
    round_index: int,
    history: list[RoundEvent],
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    return (
        f"Round {round_index}. Public observation / cheap-talk phase before any controller proposal.\n"
        f"Shared public context:\n{_public_context_text(world, history, protocol, viewer_id=agent_id)}\n\n"
        f"Private agent context:\n{_private_context_text(world, agent_id, protocol)}\n\n"
        "Send any public action that serves YOUR private utility before proposals are chosen. "
        "You may reveal, partially reveal, conceal, misrepresent, request information, invite "
        "coordination, propose public norms, propose persistent public state, or stay vague. "
        "This phase is nonbinding unless your public action explicitly states a commitment and "
        "later agents treat it as such; resource movements still require explicit consent and finalization. "
        "Do not reveal your full utility table unless strategically useful.\n\n"
        "First line must be exactly `PUBLIC ACTION`. No scratchpad, no private calculations, "
        "and no reasoning before PUBLIC ACTION. For observation-only messages, write `none` "
        "in SETTLEMENT and PUBLIC STATE UPDATE, and make clear that no transfer occurs from "
        "this message alone. Use the universal public-action envelope from the shared protocol "
        "context exactly.\n"
    )


def _state_text(world: ExchangeWorld, agent_id: int) -> str:
    st = world.public_state(agent_id)
    lines = [
        f"You are agent a{agent_id}.",
        f"Resource names: {st['resource_names']}",
        f"Public allocation matrix rows are agents a1..a{world.num_agents}:",
        json.dumps(st["allocation"]),
        f"Your private marginal utilities for resources r1..r{world.num_resources}:",
        json.dumps(st["own_preferences"]),
        f"Your current bundle: {st['own_allocation']}; utility={st['own_utility']:.3f}",
    ]
    institutions = st.get("institutions") or []
    if institutions:
        lines.extend(
            [
                "Public institutions / standing rules / public commitments from prior rounds:",
                json.dumps(institutions, ensure_ascii=False),
            ]
        )
    else:
        lines.append("Public institutions / standing rules / public commitments from prior rounds: none.")
    return "\n".join(lines)


def _freeform_proposal_prompt(
    world: ExchangeWorld,
    agent_id: int,
    round_index: int,
    history: list[RoundEvent],
    communication_texts: Optional[dict[int, str]] = None,
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    return (
        f"Round {round_index}. You are the controller/proposer for this round.\n"
        f"Shared public context:\n{_public_context_text(world, history, protocol, viewer_id=agent_id)}\n\n"
        f"Public observation / cheap-talk messages before proposal:\n"
        f"{_communication_summary(communication_texts)}\n\n"
        f"Private agent context:\n{_private_context_text(world, agent_id, protocol)}\n\n"
        f"{_atomic_commit_instruction(protocol)}"
        "Your goal is YOUR private utility. Other agents will reply from their own private utilities. "
        "First consider whether a broader or future-contingent public arrangement could improve your expected "
        "utility over future rounds. Do not start from named mechanism templates. Design from universal elements: "
        "participants, information to reveal or hide, allowed messages, timing, decision rule, settlement "
        "rule, consent or commitment standard, verification or enforcement, state update, and amendment or "
        "exit rule. You may propose immediate settlement if that is best for you, but do not treat any particular "
        "mechanism name as the default. Future resource movements still require explicit future consent. Be "
        "specific enough that a compiler can later infer any final resource transfers and any public state updates "
        "that everyone relevant agreed to. Do not reveal your full utility table.\n\n"
        "First line must be exactly `PUBLIC ACTION`. No scratchpad, no private calculations, and no reasoning "
        "before PUBLIC ACTION. SETTLEMENT rows may use fractional finite positive quantities. If you propose "
        "only communication or persistent public state, write `none` in SETTLEMENT. The envelope constrains "
        "only the interface, not the substance of the mechanism you design. ADDRESSEES may name one agent, "
        "multiple agents, all agents, or any agent. RESPONSE REQUEST is for asking who should respond, opt in, "
        "reveal offers, authorize, or counter. Use the universal public-action envelope from the shared protocol "
        "context exactly.\n"
    )


def _freeform_response_prompt(
    world: ExchangeWorld,
    agent_id: int,
    transcript: RoundTranscript,
    history: list[RoundEvent],
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    return (
        f"Round {transcript.round_index}. Agent a{transcript.controller_id} proposed:\n"
        f"{transcript.proposal_text}\n\n"
        f"Shared public context:\n{_public_context_text(world, history, protocol, viewer_id=agent_id)}\n\n"
        f"Public observation / cheap-talk messages before proposal:\n"
        f"{_communication_summary(transcript.communication_texts)}\n\n"
        f"Private agent context:\n{_private_context_text(world, agent_id, protocol)}\n\n"
        f"{_atomic_commit_instruction(protocol)}"
        "Respond as a self-interested agent. Evaluate whether the public action on the table is useful for "
        "your future private utility. You may accept, reject, condition, amend, join, refuse, propose a "
        "different procedure, or state what public state should persist. If your response authorizes giving "
        "any of your resources away, say so explicitly in SETTLEMENT and CONSENT CONDITIONS. Do not reveal "
        "your full utility table.\n\n"
        "First line must be exactly `PUBLIC ACTION`. No scratchpad, no private calculations, and no reasoning "
        "before PUBLIC ACTION. If you reject without authorizing any resource movement, write `none` in "
        "SETTLEMENT. If you authorize a debit of your resources, name the exact row and condition. Use the "
        "universal public-action envelope from the shared protocol context exactly.\n"
    )


def _freeform_finalize_prompt(
    world: ExchangeWorld,
    agent_id: int,
    transcript: RoundTranscript,
    history: list[RoundEvent],
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    responses = "\n".join(
        f"a{aid}: {text}" for aid, text in sorted(transcript.response_texts.items())
    )
    return (
        f"Round {transcript.round_index}. You proposed:\n{transcript.proposal_text}\n\n"
        f"Shared public context:\n{_public_context_text(world, history, protocol, viewer_id=agent_id)}\n\n"
        f"Public observation / cheap-talk messages before proposal:\n"
        f"{_communication_summary(transcript.communication_texts)}\n\n"
        f"Other agents responded:\n{responses}\n\n"
        f"Private agent context:\n{_private_context_text(world, agent_id, protocol)}\n\n"
        f"{_institution_support_instruction(protocol)}"
        "Finalize the round from YOUR private utility. First decide whether a public arrangement should be "
        "created, amended, used, or retired among consenting agents. You may accept supported response terms, "
        "create/amend/retire persistent public state, reject all, or clarify that no transfer should happen. "
        "Be explicit about which resource units move between which agents, if any, and about any public state "
        "that should persist into future rounds.\n\n"
        "First line must be exactly `PUBLIC ACTION`. Start with PUBLIC ACTION before any explanation. "
        "Do not put reasoning before PUBLIC ACTION. No scratchpad, no private calculations, and no hidden "
        "analysis. Use this natural-language table format inside SETTLEMENT, not JSON:\n"
        "from | to | resource | quantity | consent evidence\n"
        "aX | aY | rZ | <finite positive number> | <who explicitly accepted/authorized this debit>\n"
        "If no transfer is finalized, write `none` in SETTLEMENT. Only include a transfer if the debited "
        "agent explicitly accepted, offered, authorized, or finalized that exact debit; otherwise omit that "
        "transfer. Preserve fractional quantities exactly; do not round. Put any persistent public rule, "
        "memory, commitment, convention, institution, amendment, or retirement under PUBLIC STATE UPDATE, "
        "or write `none`. Use the universal public-action envelope from the shared protocol context exactly.\n"
    )


def _transcript_text(transcript: RoundTranscript) -> str:
    responses = "\n".join(
        f"a{aid}: {text}" for aid, text in sorted(transcript.response_texts.items())
    )
    return (
        f"round: {transcript.round_index}\n"
        f"controller: a{transcript.controller_id}\n"
        f"public_communication:\n{_communication_summary(transcript.communication_texts)}\n\n"
        f"proposal:\n{transcript.proposal_text}\n\n"
        f"responses:\n{responses or 'none'}\n\n"
        f"controller_finalization:\n{transcript.final_text}"
    )


def _compile_transcript_prompt(
    world: ExchangeWorld,
    transcript: RoundTranscript,
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    protocol = protocol or ProtocolConfig()
    partial_instruction = _partial_clearing_instruction(protocol).strip()
    return (
        "Compile the transcript into executable resource/state effects for this round.\n"
        f"Agents are a1..a{world.num_agents}. Resources are r1..r{world.num_resources}.\n"
        "Agent public actions are expected to use this neutral envelope: PUBLIC ACTION, ADDRESSEES, "
        "MESSAGE, RESPONSE REQUEST, SETTLEMENT, CONSENT CONDITIONS, PUBLIC STATE UPDATE, "
        "NO-TRANSFER FALLBACK. Treat ADDRESSEES and RESPONSE REQUEST as public communication/routing "
        "fields, not as executable resource transfers by themselves. Treat the "
        "controller finalization as the only executable settlement source, but use the full transcript "
        "to verify consent and public state support.\n"
        "Resource quantities may be fractional finite positive numbers, not only integers. "
        f"{partial_instruction + chr(10) if partial_instruction else ''}"
        "Only include transfers that are clearly authorized by the transcript and finalization. "
        "If no transfer is clearly finalized, return an empty transfers list. "
        "consenting_agents must include every agent whose resources are debited, and only include "
        "an agent if the transcript shows that agent accepted, offered, authorized, or finalized that debit.\n"
        "institutional_updates is intentionally open-ended: use strings or arbitrary JSON objects "
        "to preserve any public rule, public memory, convention, commitment, state update, amendment, "
        "or retirement that the transcript clearly creates for future rounds. Do not force institutional "
        "updates into a fixed taxonomy, and do not treat them as automatic authorization for future transfers. "
        "Only include institutional_updates when the controller finalization's PUBLIC STATE UPDATE section "
        "contains a non-none persistent update. Never convert rejected proposals, no-transfer fallbacks, "
        "or round summaries into institutional_updates.\n\n"
        f"Transcript:\n{_transcript_text(transcript)}\n\n"
        "Return exactly one JSON object:\n"
        "{\n"
        '  "mechanism_label": "<free label chosen from the transcript wording>",\n'
        '  "summary": "<one sentence>",\n'
        '  "transfers": [\n'
        '    {"from": <agent id>, "to": <agent id>, "resource": "r<id>", "quantity": <finite positive number>}\n'
        "  ],\n"
        '  "institutional_updates": [<strings or arbitrary JSON objects for persistent public memory>],\n'
        '  "consenting_agents": [<agent ids>],\n'
        '  "confidence": <0 to 1>\n'
        "}"
    )


def _compiled_to_json(mechanism: CompiledMechanism) -> str:
    return json.dumps(
        {
            "mechanism_label": mechanism.label,
            "summary": mechanism.summary,
            "transfers": [
                {
                    "from": tr.from_agent,
                    "to": tr.to_agent,
                    "resource": f"r{tr.resource}",
                    "quantity": tr.quantity,
                }
                for tr in mechanism.transfers
            ],
            "institutional_updates": deepcopy(mechanism.institutional_updates),
            "consenting_agents": mechanism.consenting_agents,
            "confidence": mechanism.confidence,
        },
        indent=2,
    )


def _agent_debit_bundle_text(mechanism: CompiledMechanism, agent_id: int) -> str:
    rows = [
        f"a{tr.from_agent} -> a{tr.to_agent} r{tr.resource} quantity {tr.quantity}"
        for tr in mechanism.transfers
        if tr.from_agent == agent_id
    ]
    return "\n".join(rows) if rows else "none"


def _agent_credit_bundle_text(mechanism: CompiledMechanism, agent_id: int) -> str:
    rows = [
        f"a{tr.from_agent} -> a{tr.to_agent} r{tr.resource} quantity {tr.quantity}"
        for tr in mechanism.transfers
        if tr.to_agent == agent_id
    ]
    return "\n".join(rows) if rows else "none"


def _append_trace_jsonl(
    trace_jsonl_path: Optional[Path],
    *,
    transcript: RoundTranscript,
    compiled: CompiledMechanism,
    verified_before_private_acceptance: CompiledMechanism,
    executed: CompiledMechanism,
    event: RoundEvent,
) -> None:
    if trace_jsonl_path is None:
        return
    trace_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "round_index": transcript.round_index,
        "controller_id": transcript.controller_id,
        "communication_texts": dict(transcript.communication_texts),
        "proposal_text": transcript.proposal_text,
        "response_texts": dict(transcript.response_texts),
        "final_text": transcript.final_text,
        "compiled_mechanism": compiled_mechanism_dict(compiled),
        "verified_before_private_acceptance": compiled_mechanism_dict(verified_before_private_acceptance),
        "verified_mechanism": compiled_mechanism_dict(executed),
        "event": round_event_dict(event),
    }
    with trace_jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _utility_rule_text(world: ExchangeWorld) -> str:
    """The agent-facing description of the utility rule, matching the world's utility_mode (so the
    elicited computation is correct). Mentions the linear money numeraire when present."""
    if world.bundle_utility is not None:
        rule = (
            "your utility for holding quantity x of a resource you value at v is v*x; "
            "if you are the buyer agent, your bundle value is realized ONLY when you hold at least "
            "1 unit of EVERY required component of your bundle (a partial bundle contributes nothing)"
        )
    elif world.utility_mode == "linear":
        rule = "your utility for holding quantity x of a resource you value at v is v*x"
    else:  # concave_separable / complementary_bundle
        rule = "your utility for holding quantity x of a resource you value at v is v*sqrt(x)"
    if world.money_good_index is not None:
        rule += f" (the resource '{world.resource_names[world.money_good_index]}' is linear: value*quantity)"
    return rule


def _private_acceptance_prompt(
    world: ExchangeWorld,
    agent_id: int,
    transcript: RoundTranscript,
    mechanism: CompiledMechanism,
    history: list[RoundEvent],
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    protocol = protocol or ProtocolConfig()
    public_context = ""
    if protocol.private_acceptance_context != "minimal":
        public_context = f"Shared public context:\n{_shared_public_context_text(world, history, protocol)}\n\n"
    return (
        f"Round {transcript.round_index}. Private post-finalization acceptance check.\n"
        f"{public_context}"
        f"Compiled finalized mechanism:\n{_compiled_to_json(mechanism)}\n\n"
        "Decide by working through your own utility step by step (you MAY write out your own utility "
        f"numbers here): using the rule that {_utility_rule_text(world)}, compute your total utility for "
        "your CURRENT holdings, then your total utility AFTER this settlement (subtract the resources you "
        "give, add the resources you receive), and say which is larger. Approve only if your after-utility "
        "is strictly larger than before AND all required counterpart transfers are present. Reject if it is "
        "not strictly larger, is ambiguous, is missing a linked counterpart transfer, or is not the same "
        "bundle you meant to authorize.\n\n"
        "Write your reasoning first, then return the decision as JSON:\n"
        "{\n"
        '  "own_debits_seen": [{"resource": "r<id>", "quantity": <number>}],\n'
        '  "own_credits_seen": [{"resource": "r<id>", "quantity": <number>}],\n'
        '  "claimed_delta_sign": "positive|zero|negative|ambiguous",\n'
        '  "counterpart_transfers_present": true/false,\n'
        '  "same_bundle_authorized": true/false,\n'
        '  "approve": true/false,\n'
        '  "reason": "<brief qualitative reason without private utility numbers>"\n'
        "}\n\n"
        f"{_CACHEABLE_CONTEXT_MARKER}\n"
        f"Private acceptance target: agent a{agent_id}.\n"
        f"Private agent context:\n{_private_context_text(world, agent_id, protocol)}\n\n"
        f"Your debits in this mechanism:\n{_agent_debit_bundle_text(mechanism, agent_id)}\n\n"
        f"Your credits in this mechanism:\n{_agent_credit_bundle_text(mechanism, agent_id)}"
    )


def _verify_compilation_prompt(
    world: ExchangeWorld,
    transcript: RoundTranscript,
    mechanism: CompiledMechanism,
    protocol: Optional[ProtocolConfig] = None,
) -> str:
    protocol = protocol or ProtocolConfig()
    partial_instruction = _partial_clearing_instruction(protocol).strip()
    return (
        "Verify whether the compiled mechanism is semantically faithful to the transcript.\n"
        "The transcript may use a PUBLIC ACTION envelope with ADDRESSEES, MESSAGE, RESPONSE REQUEST, "
        "SETTLEMENT, CONSENT CONDITIONS, PUBLIC STATE UPDATE, and NO-TRANSFER FALLBACK sections. "
        "Use those sections when present. ADDRESSEES and RESPONSE REQUEST are communication/routing "
        "fields, not executable resource transfers by themselves.\n"
        f"{partial_instruction + chr(10) if partial_instruction else ''}"
        "Check only these questions: Are the listed transfers supported by the transcript and "
        "controller finalization? Did every debited agent explicitly accept, offer, authorize, or finalize "
        "the debit? Are institutional updates clearly created, amended, retired, or agreed as public "
        "memory in the controller finalization's PUBLIC STATE UPDATE section? Are there invented terms not "
        "present in the transcript? Do not judge "
        "welfare or fairness.\n\n"
        f"Agents are a1..a{world.num_agents}. Resources are r1..r{world.num_resources}.\n\n"
        f"Transcript:\n{_transcript_text(transcript)}\n\n"
        f"Compiled mechanism:\n{_compiled_to_json(mechanism)}\n\n"
        "Return exactly one JSON object:\n"
        '{"verifier_ok": true/false, "confidence": <0 to 1>, "reason": "<short reason>"}'
    )


# ===============================================================
# Runner
# ===============================================================


def run_one_round(
    world: ExchangeWorld,
    round_index: int,
    controller_id: int,
    history: list[RoundEvent],
    policy: "LLMCompilerVerifierPolicy",
    protocol: ProtocolConfig,
    response_agent_ids: Optional[list[int]] = None,
    trace_jsonl_path: Optional[Path] = None,
) -> tuple[RoundEvent, float]:
    """Run ONE round from a given world state + cached history.

    Returns (event, net_coordination_cost); the caller appends the event to
    history. This is the unit shared by run_exchange_transcript and by
    checkpoint-rollout tests that reconstruct (world, history) for any failing
    round and re-sample only that one step forward.
    """
    t = round_index
    _ensure_information_reveal_protocol(world, protocol, history, controller_id=controller_id)
    communication_ids = _communication_agent_ids_for(protocol, world, controller_id)
    if hasattr(policy, "communication_texts"):
        communication_texts = policy.communication_texts(world, communication_ids, t, history)
    else:
        communication_texts = {
            aid: policy.communication_text(world, aid, t, history)
            for aid in communication_ids
        }
    proposal_text = policy.propose_text(world, controller_id, t, history, communication_texts)
    responders = response_agent_ids or _response_agent_ids_for(
        protocol,
        world,
        controller_id,
        proposal_text=proposal_text,
        communication_texts=communication_texts,
    )
    blank = RoundTranscript(t, controller_id, proposal_text, {}, "", communication_texts)
    responder_ids = []
    for aid in responders:
        _idx(aid, world.num_agents, "responder")
        if aid == controller_id:
            continue
        responder_ids.append(aid)
    coordination_cost = apply_institutional_costs(
        world,
        world.institution_pressure,
        t,
        contacted_agent_count=len(responder_ids),
    )
    if hasattr(policy, "response_texts"):
        response_texts = policy.response_texts(world, responder_ids, blank, history)
    else:
        response_texts = {
            aid: policy.respond_text(world, aid, blank, history)
            for aid in responder_ids
        }
    draft = RoundTranscript(t, controller_id, proposal_text, response_texts, "", communication_texts)
    if protocol.atomic_commit:
        final_text = _atomic_commit_final_text(proposal_text)
    else:
        final_text = policy.finalize_text(world, controller_id, draft, history)
    transcript = RoundTranscript(t, controller_id, proposal_text, response_texts, final_text, communication_texts)
    compiled = policy.compile_transcript(world, transcript)
    verified_before_private_acceptance = policy.verify_compilation(world, transcript, compiled)
    verified = verified_before_private_acceptance
    private_acceptance_audits: list[PrivateAcceptanceAudit] = []
    if protocol.private_acceptance_check and not protocol.atomic_commit and verified.transfers:
        debited_agents = _debited_agent_ids(verified)
        if protocol.private_acceptance_mode == "deterministic_oracle":
            acceptance_texts = {}
        elif hasattr(policy, "private_acceptance_texts"):
            acceptance_texts = policy.private_acceptance_texts(
                world,
                debited_agents,
                transcript,
                verified,
                history,
            )
        else:
            acceptance_texts = {}
        verified, private_acceptance_audits = enforce_private_acceptance(
            verified,
            acceptance_texts,
            world=world,
            mode=protocol.private_acceptance_mode,
        )
    event = apply_compiled_mechanism(
        world, verified, round_index=t, controller_id=controller_id,
        ir_enforce=protocol.ir_enforce,
    )
    event.private_acceptance_audits = private_acceptance_audits
    event.coordination_cost = coordination_cost
    _append_trace_jsonl(
        trace_jsonl_path,
        transcript=transcript,
        compiled=compiled,
        verified_before_private_acceptance=verified_before_private_acceptance,
        executed=verified,
        event=event,
    )
    return event, float(coordination_cost.get("net_coordination_cost") or 0.0)


def run_exchange_transcript(
    world: ExchangeWorld,
    rounds: int = 300,
    controllers: list[int] | None = None,
    policy: LLMCompilerVerifierPolicy | None = None,
    response_agent_ids: Optional[list[int]] = None,
    protocol: Optional[ProtocolConfig] = None,
    trace_jsonl_path: Optional[Path] = None,
) -> RunResult:
    protocol = protocol or ProtocolConfig()
    if trace_jsonl_path is not None:
        trace_jsonl_path = Path(trace_jsonl_path)
        trace_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        trace_jsonl_path.write_text("")
    controllers = [1, 3, 5] if controllers is None else controllers
    for c in controllers:
        _idx(c, world.num_agents, "controller")
    if policy is None:
        policy = LLMCompilerVerifierPolicy(protocol=protocol)
    elif hasattr(policy, "protocol"):
        policy.protocol = protocol

    initial_allocation = world.copy_allocation()
    initial_welfare = total_welfare(world)
    initial_gini = gini(utility_vector(world))
    optimum = social_optimum(world)
    optimum_welfare = total_welfare(world, optimum)
    history: list[RoundEvent] = []
    coordination_cost_total = 0.0

    for t in range(1, rounds + 1):
        controller_id = controllers[(t - 1) % len(controllers)]
        event, net_cost = run_one_round(
            world, t, controller_id, history, policy, protocol,
            response_agent_ids=response_agent_ids, trace_jsonl_path=trace_jsonl_path,
        )
        coordination_cost_total += net_cost
        history.append(event)

    final_welfare = total_welfare(world)
    return RunResult(
        initial_allocation=initial_allocation,
        final_allocation=world.copy_allocation(),
        history=history,
        initial_welfare=initial_welfare,
        final_welfare=final_welfare,
        optimum_welfare=optimum_welfare,
        initial_welfare_ratio=0.0,
        final_welfare_ratio=(
            1.0 if optimum_welfare <= initial_welfare + 1e-12
            else max(0.0, min(1.0, (final_welfare - initial_welfare) / (optimum_welfare - initial_welfare)))
        ),
        initial_gini=initial_gini,
        final_gini=gini(utility_vector(world)),
        final_institutions=active_institutions(world, rounds + 1),
        coordination_cost_total=coordination_cost_total,
        final_net_welfare=final_welfare - coordination_cost_total,
    )


def _parse_int_list(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.environ.get("POC_CONFIG"))
    ap.add_argument("--agents", type=int, default=int(os.environ.get("POC_AGENTS", "10")))
    ap.add_argument("--resources", type=int, default=int(os.environ.get("POC_RESOURCES", "10")))
    ap.add_argument("--rounds", type=int, default=int(os.environ.get("POC_ROUNDS", "300")))
    ap.add_argument(
        "--rounds-override",
        type=int,
        default=None,
        help="explicit runtime-only round override for a loaded config",
    )
    ap.add_argument("--seed", type=int, default=int(os.environ.get("POC_SEED", "23")))
    ap.add_argument("--controllers", default=os.environ.get("POC_CONTROLLERS", "1,3,5"))
    ap.add_argument(
        "--controllers-override",
        default=None,
        help="explicit runtime-only comma-separated controller override for a loaded config",
    )
    ap.add_argument("--model", default=os.environ.get("POC_MODEL", "google/gemini-3.5-flash"))
    ap.add_argument("--compiler-model", default=os.environ.get("POC_COMPILER_MODEL"))
    ap.add_argument("--verifier-model", default=os.environ.get("POC_VERIFIER_MODEL"))
    ap.add_argument("--max-tokens", type=int, default=int(os.environ.get("POC_MT", "1200")))
    ap.add_argument("--temperature", type=float, default=float(os.environ.get("POC_TEMPERATURE", "0.0")))
    ap.add_argument("--sample", type=int, default=int(os.environ.get("POC_SAMPLE", "0")))
    ap.add_argument("--trace-jsonl", default=os.environ.get("POC_TRACE_JSONL"))
    ap.add_argument(
        "--batch",
        action="store_true",
        default=os.environ.get("POC_BATCH", "").strip().lower() in {"1", "true", "yes", "on"},
        help="use provider batch API for independent communication/response phases",
    )
    ap.add_argument("--no-batch", action="store_true", help="disable batch mode even when POC_BATCH is set")
    ap.add_argument("--offline", action="store_true", help="legacy named-action mode is archived and no longer active")
    args = ap.parse_args()
    if args.no_batch:
        args.batch = False

    config = load_experiment_config(args.config) if args.config else None
    if config is not None:
        config = override_experiment_config_runtime(
            config,
            rounds=args.rounds_override,
            controllers=_parse_int_list(args.controllers_override) if args.controllers_override else None,
        )
        world = make_world_from_config(config)
        controllers = config.controllers
        rounds = config.rounds
        protocol = config.protocol
        config_label = config.name
    else:
        world = make_exchange_world(args.agents, args.resources, seed=args.seed)
        controllers = _parse_int_list(args.controllers_override or args.controllers)
        rounds = args.rounds_override or args.rounds
        protocol = ProtocolConfig()
        config_label = "cli_defaults"
    if args.offline:
        raise SystemExit(
            "--offline used the archived structured named-action runner. "
            "Use sprint/archive/exchange_economy_legacy_named_actions_20260615.py if you need it."
        )
    policy_kwargs = dict(
        model=args.model,
        compiler_model=args.compiler_model,
        verifier_model=args.verifier_model,
        max_tokens=args.max_tokens,
        protocol=protocol,
        batch_enabled=args.batch,
        temperature=args.temperature,
        sample=args.sample,
    )
    if getattr(protocol, "defection_rate", 0.0) > 0.0:
        from aeread.exchange_economy_adversarial import AdversarialCounterpartyPolicy

        policy = AdversarialCounterpartyPolicy(
            defection_rate=protocol.defection_rate,
            defection_seed=protocol.defection_seed,
            **policy_kwargs,
        )
    else:
        policy = LLMCompilerVerifierPolicy(**policy_kwargs)
    trace_jsonl_path = Path(args.trace_jsonl) if args.trace_jsonl else None
    result = run_exchange_transcript(
        world,
        rounds=rounds,
        controllers=controllers,
        policy=policy,
        protocol=protocol,
        trace_jsonl_path=trace_jsonl_path,
    )
    policy_label = (
        f"{args.model} agents | compiler={args.compiler_model or args.model} "
        f"| verifier={args.verifier_model or args.compiler_model or args.model} "
        f"| batch_phases={args.batch} | temperature={args.temperature} | sample={args.sample}"
    )
    utilities = utility_vector(world)
    print("=" * 88)
    print(
        f"EXCHANGE ECONOMY {world.num_agents} agents x {world.num_resources} resources | "
        f"config={config_label} | rounds={rounds} | controllers={controllers} | "
        f"protocol={protocol.name} | policy={policy_label}"
    )
    print("=" * 88)
    print(f"initial welfare: {result.initial_welfare:.3f}")
    print(f"final welfare:   {result.final_welfare:.3f}")
    if result.coordination_cost_total:
        print(f"final net welfare after coordination costs: {result.final_net_welfare:.3f}")
    print(f"optimum welfare: {result.optimum_welfare:.3f}")
    print(f"welfare ratio:   {result.final_welfare_ratio:.3f}")
    print(f"utility mode:    {config.utility_mode if config else world.utility_mode}")
    if config and (
        config.institution_pressure.search_cost_per_public_round
        or config.institution_pressure.search_cost_per_contacted_agent
    ):
        cost_preview = apply_institutional_costs(world, config.institution_pressure, round_index=rounds + 1)
        print(
            "institution pressure: "
            f"search_cost_per_public_round={config.institution_pressure.search_cost_per_public_round:.3f} "
            f"search_cost_per_contacted_agent={config.institution_pressure.search_cost_per_contacted_agent:.3f} "
            f"search_cost_basis={cost_preview['search_cost_basis']} "
            f"active_institutions={cost_preview['active_institutions']} "
            f"net_coordination_cost={cost_preview['net_coordination_cost']:.3f}"
        )
    print(f"accepted/applied mechanisms: {result.applied_mechanisms}/{len(result.history)}")
    print(f"active codified public rules: {len(result.final_institutions)}")
    print(f"IR violations among applied mechanisms: {result.ir_violations}")
    print(f"gini utility: {result.initial_gini:.3f} -> {result.final_gini:.3f}")
    print(f"final utilities: {[round(u, 3) for u in utilities]}")
    usage = policy.usage_summary()
    if usage["calls"]:
        cost_text = (
            f"${usage['estimated_cost_usd']:.6f}"
            if usage["unknown_cost_calls"] == 0
            else f"${usage['estimated_cost_usd']:.6f} + {usage['unknown_cost_calls']} unpriced fresh call(s)"
        )
        print(
            f"llm calls: {usage['calls']} "
            f"({usage['fresh_calls']} fresh, {usage['cached_calls']} cached, "
            f"{usage.get('batched_calls', 0)} batched)"
        )
        print(
            "llm tokens: "
            f"input={usage['input_tokens']} cached_input={usage['cached_input_tokens']} "
            f"provider_cache_hit_rate={usage['provider_cache_hit_rate'] or 0:.3f} "
            f"output={usage['output_tokens']} "
            f"reasoning={usage['reasoning_tokens']} total={usage['total_tokens']}"
        )
        print(f"estimated API cost: {cost_text}")
    if trace_jsonl_path is not None:
        print(f"trace jsonl: {trace_jsonl_path}")
    print()
    print(render_error_decomposition_report(summarize_run_errors(result)).rstrip())
    print("\nlast 10 events:")
    for e in result.history[-10:]:
        print(
            f"  r{e.round_index:03d} c=a{e.controller_id} {e.kind:<7} "
            f"accepted={e.accepted} applied={e.applied} "
            f"IR={e.individually_rational} dP={e.proposer_delta:+.2f} "
            f"dR={e.receiver_delta:+.2f} inst={len(e.institutional_updates)} "
            f"welfare={e.welfare_after:.2f}"
        )
    if result.final_institutions:
        print("\nactive codified public rules:")
        for item in result.final_institutions:
            print(f"  {json.dumps(item, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
