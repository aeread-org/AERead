"""Repeated sourcing: the award as a period transition, and the T-period bound.

The single-period family ends at ``submit_award``. Under a declared
``interaction.periods`` block the same buyer sources the same BOM again, and
what it did last period changes what suppliers offer this period. A supplier
awarded in consecutive periods discounts its whole price schedule (quote and
floor) and reserves extra capacity for its incumbent customer; a supplier that
was quoted and then dropped raises its schedule for one period. Realized
delivery, drawn from the declared seed, is written to a history the next
period's observation shows, so the buyer's reputation over supplier traits is
whatever it forms from its own outcomes. There is no reputation field.

Everything here is world data declared in the case and applied by the
environment; the harness never judges a move. The reference is a finite-horizon
dynamic programme over the relationship standing, exact for the declared
action model, and it charges every quote, sample and counter the way the
single-period bound does. Two references sit under it: ``myopic`` optimizes
each period on its own, and ``loyal`` re-awards its first choice every period.
A world earns admission only when the T-period optimum beats both by a
declared margin; otherwise the periods add nothing a single-period buyer could
not already do.

Design record: ``docs/research/economic_primitives_extension_design.md`` §4
proposed the mechanics; the choices made here that it left open are listed in
``docs/families/procurement-allocation/relationship_design.md``.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Sequence

#: Fields of ``interaction.periods``. ``count`` and ``delivery_seed`` are
#: required; ``overrides`` lets the objective vary by period (a demand plan).
PERIOD_FIELDS = frozenset({"count", "delivery_seed", "overrides"})
PERIOD_OVERRIDE_FIELDS = frozenset(
    {
        "target_kits",
        "minimum_service_kits",
        "cash_budget_usd",
        "revenue_per_completed_kit_usd",
        "shortfall_penalty_per_kit_usd",
        "deadline_days",
    }
)
#: Fields of ``private_terms.relationship``. All four are required when the
#: block is present, so a world cannot half-declare a schedule.
RELATIONSHIP_FIELDS = frozenset(
    {
        "loyalty_discount_per_award",
        "loyalty_discount_cap",
        "incumbent_capacity_bonus",
        "retaliation_markup",
    }
)
MINIMUM_PERIODS = 2
MAXIMUM_PERIODS = 8

#: The dynamic programme memoizes one value per reachable relationship
#: standing per period. A world with many suppliers reaches too many to finish;
#: the generator gets an error naming the fix instead of an unbounded wait.
STANDING_LIMIT = 20_000

#: Period-level decisions recorded in ``period_results``.
PERIOD_DECISIONS = frozenset({"award", "defer", "failed", "unplayed"})


def _env() -> Any:
    # ``environment`` imports this module at load; the economics helpers are
    # resolved at call time so neither module needs the other to be finished.
    from . import environment

    return environment


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _count(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path} must be a non-negative integer")
    return value


def _fraction(value: Any, path: str, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0.0 or result > maximum:
        raise ValueError(f"{path} must be between 0 and {maximum}")
    return result


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------


def periods_declared(family_case: Mapping[str, Any]) -> bool:
    return family_case["interaction"].get("periods") is not None


def period_count(family_case: Mapping[str, Any]) -> int:
    periods = family_case["interaction"].get("periods")
    return int(periods["count"]) if periods is not None else 1


def validate_periods(
    interaction: Mapping[str, Any],
    objective: Mapping[str, Any],
    suppliers: Sequence[Mapping[str, Any]],
) -> None:
    """Validate ``interaction.periods`` against the objective and suppliers.

    A case that omits the block is the single-period family, unchanged. A
    supplier may declare ``relationship`` terms only under a periods block,
    because a schedule that can never advance is a term nobody can read.
    """
    periods = interaction.get("periods")
    declares_relationship = any(
        isinstance(supplier.get("private_terms"), Mapping)
        and supplier["private_terms"].get("relationship") is not None
        for supplier in suppliers
    )
    if periods is None:
        if declares_relationship:
            raise ValueError(
                "private_terms.relationship requires interaction.periods"
            )
        return
    if not isinstance(periods, Mapping):
        raise ValueError("interaction.periods must be an object")
    keys = set(periods)
    if not {"count", "delivery_seed"} <= keys or not keys <= PERIOD_FIELDS:
        raise ValueError(
            "interaction.periods requires 'count' and 'delivery_seed' and "
            "permits only 'overrides' besides"
        )
    count = _positive_int(periods["count"], "interaction.periods.count")
    if not MINIMUM_PERIODS <= count <= MAXIMUM_PERIODS:
        raise ValueError(
            f"interaction.periods.count must be between {MINIMUM_PERIODS} and "
            f"{MAXIMUM_PERIODS}"
        )
    _positive_int(periods["delivery_seed"], "interaction.periods.delivery_seed")
    overrides = periods.get("overrides")
    if overrides is None:
        return
    if not isinstance(overrides, list) or len(overrides) != count:
        raise ValueError(
            "interaction.periods.overrides must list one object per period"
        )
    for index, override in enumerate(overrides):
        path = f"interaction.periods.overrides[{index}]"
        if not isinstance(override, Mapping):
            raise ValueError(f"{path} must be an object")
        unknown = set(override) - PERIOD_OVERRIDE_FIELDS
        if unknown:
            raise ValueError(f"{path} names unsupported fields: {sorted(unknown)}")
        merged = {**objective, **override}
        for field in ("target_kits", "minimum_service_kits", "deadline_days"):
            if field in override:
                _positive_int(override[field], f"{path}.{field}")
        for field in (
            "cash_budget_usd",
            "revenue_per_completed_kit_usd",
            "shortfall_penalty_per_kit_usd",
        ):
            if field in override:
                _fraction(override[field], f"{path}.{field}", maximum=math.inf)
        if merged["minimum_service_kits"] > merged["target_kits"]:
            raise ValueError(f"{path} leaves minimum_service_kits above target_kits")


def validate_relationship(terms: Mapping[str, Any], path: str) -> None:
    relationship = terms.get("relationship")
    if relationship is None:
        return
    if not isinstance(relationship, Mapping) or set(relationship) != RELATIONSHIP_FIELDS:
        raise ValueError(
            f"{path}.relationship must declare exactly {sorted(RELATIONSHIP_FIELDS)}"
        )
    _fraction(
        relationship["loyalty_discount_per_award"],
        f"{path}.relationship.loyalty_discount_per_award",
        maximum=0.9,
    )
    _fraction(
        relationship["loyalty_discount_cap"],
        f"{path}.relationship.loyalty_discount_cap",
        maximum=0.9,
    )
    _count(
        relationship["incumbent_capacity_bonus"],
        f"{path}.relationship.incumbent_capacity_bonus",
    )
    _fraction(
        relationship["retaliation_markup"],
        f"{path}.relationship.retaliation_markup",
        maximum=2.0,
    )


def period_objective(family_case: Mapping[str, Any], period: int) -> dict[str, Any]:
    """The objective in force for ``period`` (1-based), overrides applied."""
    objective = _plain(family_case["objective"])
    periods = family_case["interaction"].get("periods")
    if periods is None:
        return objective
    overrides = periods.get("overrides")
    if overrides:
        objective.update(_plain(overrides[period - 1]))
    return objective


def period_schedule(family_case: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every period's effective objective, the buyer's demand plan."""
    return [
        period_objective(family_case, period)
        for period in range(1, period_count(family_case) + 1)
    ]


def period_case(family_case: Mapping[str, Any], period: int) -> dict[str, Any]:
    """The case as a single-period evaluator sees it in ``period``."""
    view = dict(family_case)
    view["objective"] = period_objective(family_case, period)
    return view


# --------------------------------------------------------------------------
# Standing and effective terms
# --------------------------------------------------------------------------


def initial_standing(family_case: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    return {
        str(supplier["supplier_id"]): {
            "consecutive_awards": 0,
            "retaliation_periods_left": 0,
        }
        for supplier in family_case["suppliers"]
    }


def advance_entry(
    entry: Mapping[str, int], *, awarded: bool, quoted: bool
) -> dict[str, int]:
    """One supplier's standing after a period closes.

    Awarded: the streak grows and any grievance is forgotten. Quoted and then
    dropped: the streak resets and the supplier retaliates for exactly one
    period. Not approached: the streak resets and a standing grievance lapses.
    """
    if awarded:
        return {
            "consecutive_awards": int(entry["consecutive_awards"]) + 1,
            "retaliation_periods_left": 0,
        }
    if quoted:
        return {"consecutive_awards": 0, "retaliation_periods_left": 1}
    return {
        "consecutive_awards": 0,
        "retaliation_periods_left": max(0, int(entry["retaliation_periods_left"]) - 1),
    }


def relationship_applied(
    supplier: Mapping[str, Any], entry: Mapping[str, int]
) -> dict[str, Any] | None:
    """What the standing does to this supplier's terms right now."""
    schedule = supplier["private_terms"].get("relationship")
    if not schedule:
        return None
    consecutive = int(entry["consecutive_awards"])
    discount = min(
        float(schedule["loyalty_discount_cap"]),
        float(schedule["loyalty_discount_per_award"]) * consecutive,
    )
    markup = (
        float(schedule["retaliation_markup"])
        if int(entry["retaliation_periods_left"]) > 0
        else 0.0
    )
    bonus = int(schedule["incumbent_capacity_bonus"]) if consecutive >= 1 else 0
    return {
        "consecutive_awards": consecutive,
        "loyalty_discount": round(discount, 6),
        "retaliation_markup": round(markup, 6),
        "capacity_bonus": bonus,
        "schedule": _plain(schedule),
    }


def effective_supplier(
    supplier: Mapping[str, Any], entry: Mapping[str, int]
) -> dict[str, Any]:
    """The supplier as it trades this period, its schedule shifted by standing.

    The loyalty discount and the retaliation markup move the quote and the
    floor together, so the relationship is legible in the formal offer rather
    than hidden behind a counter the buyer would have to guess at. Verbal bias
    is left as declared: a supplier that overstates keeps overstating.
    """
    resolved = _plain(supplier)
    applied = relationship_applied(supplier, entry)
    if applied is None:
        return resolved
    multiplier = (1.0 - applied["loyalty_discount"]) * (
        1.0 + applied["retaliation_markup"]
    )
    terms = resolved["private_terms"]
    terms["base_unit_price_usd"] = round(
        float(terms["base_unit_price_usd"]) * multiplier, 6
    )
    terms["negotiation"]["floor_unit_price_usd"] = round(
        float(terms["negotiation"]["floor_unit_price_usd"]) * multiplier, 6
    )
    terms["capacity"] = int(terms["capacity"]) + applied["capacity_bonus"]
    resolved["relationship_applied"] = applied
    return resolved


# --------------------------------------------------------------------------
# Realized delivery
# --------------------------------------------------------------------------


def _uniform(seed: int, label: str) -> float:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2.0**64


def realize_delivery(
    family_case: Mapping[str, Any],
    *,
    period: int,
    award_lines: Sequence[Mapping[str, Any]],
    offers: Mapping[str, Mapping[str, Any]],
    elapsed_days: int,
) -> tuple[list[dict[str, Any]], int]:
    """Draw what actually arrived, deterministically from the declared seed.

    Informational only: the period is scored on expected units exactly as the
    single-period family scores an award, so the score of a plan never depends
    on a draw. What the draw changes is what the buyer knows next period.
    """
    env = _env()
    objective = period_objective(family_case, period)
    seed = int(family_case["interaction"]["periods"]["delivery_seed"])
    suppliers = env._supplier_by_id(family_case)
    good_units = {component: 0 for component in objective["bom"]}
    records: list[dict[str, Any]] = []
    for line in award_lines:
        offer = offers[line["offer_id"]]
        supplier_id = str(offer["supplier_id"])
        quantity = int(line["quantity"])
        arrives = elapsed_days + int(offer["lead_time_days"]) <= int(objective["deadline_days"])
        on_time = arrives and _uniform(
            seed, f"on_time:{period}:{supplier_id}"
        ) < float(offer["on_time_probability"])
        yield_rate = float(
            suppliers[supplier_id]["private_terms"]["quality"]["verified_yield_rate"]
        )
        defects = env._binomial_defects(
            seed=seed,
            supplier_id=f"delivery:{period}:{supplier_id}",
            draw_index=0,
            sample_size=quantity,
            defect_rate=1.0 - yield_rate,
        )
        delivered = quantity - defects if on_time else 0
        good_units[offer["component"]] += delivered
        records.append(
            {
                "supplier_id": supplier_id,
                "component": offer["component"],
                "offer_id": str(line["offer_id"]),
                "quantity": quantity,
                "on_time": bool(on_time),
                "defective_units": int(defects) if on_time else None,
                "good_units_delivered": int(delivered),
            }
        )
    realized_kits = min(
        good_units[component] // int(units_per_kit)
        for component, units_per_kit in objective["bom"].items()
    )
    return records, min(realized_kits, int(objective["target_kits"]))


# --------------------------------------------------------------------------
# Period close (environment side)
# --------------------------------------------------------------------------


def period_state_fields(family_case: Mapping[str, Any]) -> dict[str, Any]:
    """State the single-period family does not carry."""
    return {
        "period": 1,
        "total_actions_used": 0,
        "relationship": initial_standing(family_case),
        "history": [],
        "period_results": [],
        "cumulative_contribution_margin_usd": 0.0,
        "cumulative_information_cost_usd": 0.0,
        "cumulative_cash_spend_usd": 0.0,
        "cumulative_completed_kits": 0,
        "cumulative_elapsed_days": 0,
    }


def _fallback_evaluation(objective: Mapping[str, Any], information_cost: float, *, violations: list[str]) -> dict[str, Any]:
    value = round(float(objective["defer_value_usd"]) - information_cost, 8)
    return {
        "feasible": not violations,
        "contribution_margin_usd": value,
        "raw_contribution_margin_usd": value,
        "completed_kits": 0,
        "cash_spend_usd": round(information_cost, 8),
        "information_cost_usd": round(information_cost, 8),
        "expected_recovery_usd": 0.0,
        "total_cost_usd": round(information_cost, 8),
        "violations": violations,
    }


def close_period(
    family_case: Mapping[str, Any],
    state: dict[str, Any],
    consequences: dict[str, Any],
) -> None:
    """Score the period, realize delivery, move standing, open the next period.

    Called by the environment once a period has ended by award, by defer or by
    an exhausted action budget. Mutates ``state`` in place. When the closed
    period was the last one the episode stays done with the reason the period
    ended on; otherwise the period-local state is reset and ``done`` is cleared.
    """
    env = _env()
    period = int(state["period"])
    count = period_count(family_case)
    reason = state["termination_reason"]
    view = period_case(family_case, period)
    objective = view["objective"]
    information_cost = float(state["information_cost_usd"])
    if reason == "submitted":
        evaluation = env.evaluate_award(
            view,
            award_lines=state["award_lines"],
            offers=state["offers"],
            quality_evidence=state["quality_evidence"],
            elapsed_days=int(state["elapsed_days"]),
            information_cost_usd=information_cost,
        )
        decision = "award"
    elif reason == "deferred":
        evaluation = _fallback_evaluation(objective, information_cost, violations=[])
        decision = "defer"
    else:
        evaluation = _fallback_evaluation(
            objective, information_cost, violations=[str(reason)]
        )
        decision = "failed"

    awarded: list[dict[str, Any]] = []
    if decision == "award" and evaluation["feasible"]:
        for line in state["award_lines"]:
            offer = state["offers"][line["offer_id"]]
            awarded.append(
                {
                    "supplier_id": str(offer["supplier_id"]),
                    "component": str(offer["component"]),
                    "offer_id": str(line["offer_id"]),
                    "quantity": int(line["quantity"]),
                    "unit_price_usd": float(offer["unit_price_usd"]),
                }
            )
    awarded_ids = {row["supplier_id"] for row in awarded}
    quoted_ids = {str(offer["supplier_id"]) for offer in state["offers"].values()}
    delivery, realized_kits = (
        realize_delivery(
            family_case,
            period=period,
            award_lines=state["award_lines"],
            offers=state["offers"],
            elapsed_days=int(state["elapsed_days"]),
        )
        if awarded
        else ([], 0)
    )

    public = {
        "period": period,
        "decision": decision,
        "feasible": bool(evaluation["feasible"]),
        "violations": list(evaluation["violations"]),
        "awarded": awarded,
        "delivery": delivery,
        "realized_completed_kits": realized_kits,
        "information_cost_usd": round(information_cost, 8),
        "cash_spend_usd": float(evaluation["cash_spend_usd"]),
        "elapsed_days": int(state["elapsed_days"]),
        "actions_used": int(state["actions_used"]),
    }
    private = {
        **public,
        "termination_reason": reason,
        "award_lines": _plain(state["award_lines"]),
        "awarded_supplier_ids": sorted(awarded_ids),
        "quoted_supplier_ids": sorted(quoted_ids),
        "contribution_margin_usd": float(evaluation["contribution_margin_usd"]),
        "raw_contribution_margin_usd": float(evaluation["raw_contribution_margin_usd"]),
        "completed_kits": int(evaluation["completed_kits"]),
        "expected_recovery_usd": float(evaluation.get("expected_recovery_usd", 0.0)),
        "total_cost_usd": float(evaluation["total_cost_usd"]),
        "defer_reason": state["defer_reason"],
    }
    state["history"].append(public)
    state["period_results"].append(private)
    state["relationship"] = {
        supplier_id: advance_entry(
            entry,
            awarded=supplier_id in awarded_ids,
            quoted=supplier_id in quoted_ids,
        )
        for supplier_id, entry in state["relationship"].items()
    }
    state["cumulative_contribution_margin_usd"] = round(
        state["cumulative_contribution_margin_usd"] + private["contribution_margin_usd"], 8
    )
    state["cumulative_information_cost_usd"] = round(
        state["cumulative_information_cost_usd"] + information_cost, 8
    )
    state["cumulative_cash_spend_usd"] = round(
        state["cumulative_cash_spend_usd"] + private["cash_spend_usd"], 8
    )
    state["cumulative_completed_kits"] += private["completed_kits"]
    state["cumulative_elapsed_days"] += int(state["elapsed_days"])

    summary = [f"Period {period} of {count} closed: {decision}"]
    if decision == "award" and not evaluation["feasible"]:
        summary.append(f"award rejected ({', '.join(evaluation['violations'])})")
    for row in delivery:
        if row["on_time"]:
            summary.append(
                f"{row['supplier_id']} delivered {row['quantity']} on time with "
                f"{row['defective_units']} defective"
            )
        else:
            summary.append(f"{row['supplier_id']} missed the deadline")
    if awarded:
        summary.append(f"{realized_kits} kits completed from delivered units")
    consequences["period_closed"] = period
    consequences["period_decision"] = decision
    consequences["period_feasible"] = bool(evaluation["feasible"])

    if period >= count:
        state["conversation"].append(
            {"role": "system", "content": "; ".join(summary) + ". Final period."}
        )
        return
    summary.append(
        f"Period {period + 1} begins; formal offers from period {period} have lapsed"
    )
    state["conversation"].append({"role": "system", "content": "; ".join(summary) + "."})
    state["period"] = period + 1
    state["actions_used"] = 0
    state["elapsed_days"] = 0
    state["information_cost_usd"] = 0.0
    state["offers"] = {}
    state["latest_offer_by_supplier"] = {}
    state["award_lines"] = []
    state["defer_reason"] = None
    state["done"] = False
    state["termination_reason"] = None


def complete_period_results(
    family_case: Mapping[str, Any], terminal: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Every period's result, including the ones an invalid action forfeited.

    An invalid action ends the episode where it stands. The interrupted period
    scores like an exhausted budget, information sunk and nothing ordered, and
    each period never reached scores at its outside option. This is the same
    floor the single-period family applies, once per period.
    """
    results = [dict(row) for row in terminal["period_results"]]
    count = period_count(family_case)
    if terminal["reason"] == "invalid_action":
        current = int(terminal["period"])
        objective = period_objective(family_case, current)
        information_cost = float(terminal["information_cost_usd"])
        results.append(
            {
                "period": current,
                "decision": "failed",
                "feasible": False,
                "violations": [terminal["failure_code"] or "invalid_action"],
                "awarded": [],
                "awarded_supplier_ids": [],
                "delivery": [],
                "contribution_margin_usd": round(
                    float(objective["defer_value_usd"]) - information_cost, 8
                ),
                "completed_kits": 0,
                "cash_spend_usd": round(information_cost, 8),
                "information_cost_usd": round(information_cost, 8),
                "expected_recovery_usd": 0.0,
                "total_cost_usd": round(information_cost, 8),
                "elapsed_days": int(terminal["elapsed_days"]),
                "actions_used": int(terminal["actions_used"]),
            }
        )
        for period in range(current + 1, count + 1):
            objective = period_objective(family_case, period)
            results.append(
                {
                    "period": period,
                    "decision": "unplayed",
                    "feasible": False,
                    "violations": ["episode_ended_before_period"],
                    "awarded": [],
                    "awarded_supplier_ids": [],
                    "delivery": [],
                    "contribution_margin_usd": float(objective["defer_value_usd"]),
                    "completed_kits": 0,
                    "cash_spend_usd": 0.0,
                    "information_cost_usd": 0.0,
                    "expected_recovery_usd": 0.0,
                    "total_cost_usd": 0.0,
                    "elapsed_days": 0,
                    "actions_used": 0,
                }
            )
    return results


def count_switches(results: Sequence[Mapping[str, Any]]) -> int:
    """Periods whose awarded supplier set differs from the previous period's.

    Both sets must be non-empty: moving from a deferred period to an award is
    a start, not a switch, and a defer after an award is an exit.
    """
    switches = 0
    previous: set[str] | None = None
    for row in results:
        current = set(row.get("awarded_supplier_ids") or ())
        if previous and current and current != previous:
            switches += 1
        if current:
            previous = current
    return switches


# --------------------------------------------------------------------------
# The T-period bound and its two references
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelationshipBound:
    contribution_margin_usd: float
    period_margins: tuple[float, ...]
    period_plans: tuple[tuple[Mapping[str, Any], ...], ...]
    completed_kits: int
    cash_spend_usd: float
    actions_required: int
    elapsed_days: int
    switches: int


@dataclass(frozen=True, slots=True)
class _Path:
    """A partial plan from some period to the horizon, with its tie-break key."""

    margin: float
    actions: int
    cash: float
    elapsed: int
    kits: int
    plans: tuple[tuple[Mapping[str, Any], ...], ...]
    margins: tuple[float, ...]
    signature: tuple[Any, ...]

    @property
    def key(self) -> tuple[Any, ...]:
        return (round(self.margin, 8), -self.actions, -self.cash, self.signature)

    def prepend(self, head: "_Path") -> "_Path":
        return _Path(
            margin=round(head.margin + self.margin, 8),
            actions=head.actions + self.actions,
            cash=round(head.cash + self.cash, 8),
            elapsed=head.elapsed + self.elapsed,
            kits=head.kits + self.kits,
            plans=head.plans + self.plans,
            margins=head.margins + self.margins,
            signature=head.signature + self.signature,
        )


_EMPTY = _Path(0.0, 0, 0.0, 0, 0, (), (), ())

#: One supplier's standing inside the solver: (consecutive awards,
#: retaliation periods left, qualified by a verified sample).
_Entry = tuple[int, int, bool]


def _advance_tuple(entry: _Entry, *, awarded: bool, quoted: bool) -> _Entry:
    moved = advance_entry(
        {"consecutive_awards": entry[0], "retaliation_periods_left": entry[1]},
        awarded=awarded,
        quoted=quoted,
    )
    return (
        moved["consecutive_awards"],
        moved["retaliation_periods_left"],
        entry[2] or awarded,
    )


class _Solver:
    def __init__(self, family_case: Mapping[str, Any]) -> None:
        self.case = family_case
        self.env = _env()
        self.suppliers = list(family_case["suppliers"])
        self.count = period_count(family_case)
        self.interaction = family_case["interaction"]
        self._options: dict[tuple[int, int, int], tuple[dict[str, Any], ...]] = {}
        self._sets: dict[tuple[Any, ...], _Path | None] = {}
        self._values: dict[tuple[int, tuple[_Entry, ...]], _Path] = {}

    # -- per-supplier options -------------------------------------------------

    def options(self, index: int, consecutive: int, retaliation: int) -> tuple[dict[str, Any], ...]:
        key = (index, consecutive, retaliation)
        cached = self._options.get(key)
        if cached is not None:
            return cached
        supplier = effective_supplier(
            self.suppliers[index],
            {"consecutive_awards": consecutive, "retaliation_periods_left": retaliation},
        )
        options: list[dict[str, Any]] = []
        for mode, offer in (
            ("base", self.env._base_offer(supplier, version=1, issued_day=0)),
            ("negotiated", self.env._best_offer(supplier, version=2, issued_day=0)),
        ):
            for quantity in self.env._quantity_values(offer):
                options.append(
                    {
                        "index": index,
                        "supplier_id": str(supplier["supplier_id"]),
                        "component": str(supplier["component"]),
                        "mode": mode,
                        "offer": offer,
                        "quantity": int(quantity),
                    }
                )
        self._options[key] = tuple(options)
        return self._options[key]

    def _sample_terms(self, index: int) -> tuple[int, float]:
        quality = self.suppliers[index]["private_terms"]["quality"]
        return int(quality["sample_lead_time_days"]), float(quality["sample_cost_usd"])

    # -- best plan awarding exactly one supplier set ----------------------------

    def _candidates(
        self, period: int, awarded: tuple[int, ...], entries: tuple[_Entry, ...]
    ) -> tuple[dict[str, Any], ...]:
        """Every feasible plan awarding exactly ``awarded``, evaluated once.

        Prequalifying other suppliers in the same period only adds actions,
        days and sample cost to a plan. Information cost enters the margin and
        the cash spend linearly, and extra days change nothing until a line
        misses its deadline, so each plan is scored once here and its
        prequalified variants are derived, re-scored exactly only when a
        deadline would move.
        """
        key = (period, awarded, entries)
        cached = self._sets.get(key)
        if cached is not None:
            return cached
        view = period_case(self.case, period)
        objective = view["objective"]
        max_actions = int(self.interaction["max_actions"])
        per_supplier = [
            self.options(index, entry[0], entry[1])
            for index, entry in zip(awarded, entries)
        ]
        combinations = 1
        for options in per_supplier:
            combinations *= len(options)
            if combinations > self.env.UPPER_BOUND_ENUMERATION_LIMIT:
                raise ValueError(
                    "relationship enumeration exceeds "
                    f"{self.env.UPPER_BOUND_ENUMERATION_LIMIT} combinations in one "
                    "period; coarsen an order step or lower a capacity so the "
                    "bound stays computable"
                )
        candidates: list[dict[str, Any]] = []
        for combination in itertools.product(*per_supplier):
            actions = 1
            elapsed = 0
            information = 0.0
            for option, entry in zip(combination, entries):
                qualified = entry[2]
                negotiated = option["mode"] == "negotiated"
                sample_days, sample_cost = self._sample_terms(option["index"])
                actions += 1 + (0 if qualified else 1) + (1 if negotiated else 0)
                elapsed += (
                    int(self.interaction["quote_days"])
                    + (0 if qualified else sample_days)
                    + (int(self.interaction["counter_days"]) if negotiated else 0)
                )
                information += (
                    float(self.interaction["quote_cost_usd"])
                    + (0.0 if qualified else sample_cost)
                    + (float(self.interaction["counter_cost_usd"]) if negotiated else 0.0)
                )
            if actions > max_actions:
                continue
            offers = {option["offer"]["offer_id"]: option["offer"] for option in combination}
            qualities = {
                option["supplier_id"]: {
                    **_plain(self.suppliers[option["index"]]["private_terms"]["quality"]),
                    "supplier_id": option["supplier_id"],
                    "variant_id": self.suppliers[option["index"]]["private_terms"]["variant_id"],
                    "evidence_status": "verified_sample",
                }
                for option in combination
            }
            lines = [
                {"offer_id": option["offer"]["offer_id"], "quantity": option["quantity"]}
                for option in combination
            ]
            result = self.env.evaluate_award(
                view,
                award_lines=lines,
                offers=offers,
                quality_evidence=qualities,
                elapsed_days=elapsed,
                information_cost_usd=round(information, 8),
            )
            if not result["feasible"]:
                continue
            plan = tuple(
                {
                    "period": period,
                    "supplier_id": option["supplier_id"],
                    "component": option["component"],
                    "mode": option["mode"],
                    "quantity": option["quantity"],
                    "unit_price_usd": float(option["offer"]["unit_price_usd"]),
                }
                for option in combination
            )
            candidates.append(
                {
                    "actions": actions,
                    "elapsed": elapsed,
                    "information": round(information, 8),
                    "margin": float(result["contribution_margin_usd"]),
                    "cash": float(result["cash_spend_usd"]),
                    "kits": int(result["completed_kits"]),
                    "deadline_slack": min(
                        int(objective["deadline_days"])
                        - elapsed
                        - int(option["offer"]["lead_time_days"])
                        for option in combination
                    ),
                    "cash_budget": float(objective["cash_budget_usd"]),
                    "plan": plan,
                    "lines": lines,
                    "offers": offers,
                    "qualities": qualities,
                    "view": view,
                }
            )
        self._sets[key] = tuple(candidates)
        return self._sets[key]

    def best_for_set(
        self,
        period: int,
        awarded: tuple[int, ...],
        entries: tuple[_Entry, ...],
        prequalify: tuple[int, ...],
        extra_quotes: int = 0,
    ) -> _Path | None:
        """Best feasible period plan awarding exactly ``awarded``.

        ``prequalify`` names suppliers sampled this period without an award, so
        a later period with a tight action budget, deadline or cash budget
        finds them already qualified. ``extra_quotes`` are quotes taken from
        suppliers that will not be awarded, which only the shopping reference
        pays for. Both are charged here, where they fall.
        """
        extra_actions = len(prequalify) + int(extra_quotes)
        extra_days = sum(self._sample_terms(index)[0] for index in prequalify) + int(
            extra_quotes
        ) * int(self.interaction["quote_days"])
        extra_cost = round(
            sum(self._sample_terms(index)[1] for index in prequalify)
            + int(extra_quotes) * float(self.interaction["quote_cost_usd"]),
            8,
        )
        max_actions = int(self.interaction["max_actions"])
        prequalified_ids = tuple(str(self.suppliers[index]["supplier_id"]) for index in prequalify) + (
            (f"extra_quotes:{int(extra_quotes)}",) if extra_quotes else ()
        )
        best: _Path | None = None
        for candidate in self._candidates(period, awarded, entries):
            actions = candidate["actions"] + extra_actions
            if actions > max_actions:
                continue
            elapsed = candidate["elapsed"] + extra_days
            if extra_days <= candidate["deadline_slack"]:
                cash = round(candidate["cash"] + extra_cost, 8)
                if cash > candidate["cash_budget"] + 1e-9:
                    continue
                margin = round(candidate["margin"] - extra_cost, 8)
                kits = candidate["kits"]
            else:
                # A prequalification sample pushes a line past its deadline;
                # score the variant exactly rather than guess at the shortfall.
                result = self.env.evaluate_award(
                    candidate["view"],
                    award_lines=candidate["lines"],
                    offers=candidate["offers"],
                    quality_evidence=candidate["qualities"],
                    elapsed_days=elapsed,
                    information_cost_usd=round(candidate["information"] + extra_cost, 8),
                )
                if not result["feasible"]:
                    continue
                margin = float(result["contribution_margin_usd"])
                cash = float(result["cash_spend_usd"])
                kits = int(result["completed_kits"])
            signature = (
                tuple((row["supplier_id"], row["mode"], row["quantity"]) for row in candidate["plan"]),
                prequalified_ids,
            )
            path = _Path(
                margin=margin,
                actions=actions,
                cash=cash,
                elapsed=elapsed,
                kits=kits,
                plans=(candidate["plan"],),
                margins=(margin,),
                signature=(signature,),
            )
            if best is None or path.key > best.key:
                best = path
        return best

    def defer_path(
        self, period: int, prequalify: tuple[int, ...], extra_quotes: int = 0
    ) -> _Path:
        objective = period_objective(self.case, period)
        cost = round(
            sum(self._sample_terms(index)[1] for index in prequalify)
            + int(extra_quotes) * float(self.interaction["quote_cost_usd"]),
            8,
        )
        days = sum(self._sample_terms(index)[0] for index in prequalify) + int(
            extra_quotes
        ) * int(self.interaction["quote_days"])
        signature = (
            (),
            tuple(str(self.suppliers[index]["supplier_id"]) for index in prequalify)
            + ((f"extra_quotes:{int(extra_quotes)}",) if extra_quotes else ()),
        )
        margin = round(float(objective["defer_value_usd"]) - cost, 8)
        return _Path(
            margin=margin,
            actions=1 + len(prequalify) + int(extra_quotes),
            cash=cost,
            elapsed=days,
            kits=0,
            plans=((),),
            margins=(margin,),
            signature=(signature,),
        )

    # -- the dynamic programme --------------------------------------------------

    def _next(
        self,
        standing: tuple[_Entry, ...],
        awarded: tuple[int, ...],
        prequalify: tuple[int, ...],
        *,
        quoted_everyone: bool = False,
    ) -> tuple[_Entry, ...]:
        # A full-information solver quotes only what it awards, so nothing on
        # its path is ever quoted and dropped; the transition rule is still the
        # environment's, applied with quoted == awarded. The shopping reference
        # quotes everyone, so every supplier it drops retaliates next period.
        awarded_set = set(awarded)
        moved: list[_Entry] = []
        for index, entry in enumerate(standing):
            consecutive, retaliation, qualified = _advance_tuple(
                entry,
                awarded=index in awarded_set,
                quoted=quoted_everyone or index in awarded_set,
            )
            moved.append((consecutive, retaliation, qualified or index in prequalify))
        return tuple(moved)

    def value(self, period: int, standing: tuple[_Entry, ...]) -> _Path:
        if period > self.count:
            return _EMPTY
        key = (period, standing)
        cached = self._values.get(key)
        if cached is not None:
            return cached
        if len(self._values) >= STANDING_LIMIT:
            raise ValueError(
                f"relationship bound reaches more than {STANDING_LIMIT} standings; "
                "declare fewer suppliers or periods so the bound stays computable"
            )
        indices = tuple(range(len(self.suppliers)))
        max_actions = int(self.interaction["max_actions"])
        best: _Path | None = None
        for awarded_size in range(0, len(indices) + 1):
            for awarded in itertools.combinations(indices, awarded_size):
                rest = tuple(index for index in indices if index not in awarded)
                unqualified = tuple(index for index in rest if not standing[index][2])
                for prequalify_size in range(0, len(unqualified) + 1):
                    for prequalify in itertools.combinations(unqualified, prequalify_size):
                        if 1 + len(prequalify) > max_actions:
                            continue
                        if awarded:
                            head = self.best_for_set(
                                period,
                                awarded,
                                tuple(standing[index] for index in awarded),
                                prequalify,
                            )
                            if head is None:
                                continue
                        else:
                            head = self.defer_path(period, prequalify)
                        tail = self.value(period + 1, self._next(standing, awarded, prequalify))
                        candidate = tail.prepend(head)
                        if best is None or candidate.key > best.key:
                            best = candidate
        assert best is not None  # deferring every period is always feasible
        self._values[key] = best
        return best

    def initial(self) -> tuple[_Entry, ...]:
        return tuple((0, 0, False) for _ in self.suppliers)

    def solve(self) -> RelationshipBound:
        return _bound(self.value(1, self.initial()))

    # -- references ---------------------------------------------------------------

    def _best_now(
        self, period: int, standing: tuple[_Entry, ...], *, shopping: bool = False
    ) -> tuple[_Path, tuple[int, ...]]:
        """The period-optimal plan, the future ignored. Never prequalifies.

        With ``shopping`` the buyer quotes every supplier before choosing, and
        pays for every quote it does not award.
        """
        indices = tuple(range(len(self.suppliers)))
        count = len(indices)
        best = self.defer_path(period, (), extra_quotes=count if shopping else 0)
        best_set: tuple[int, ...] = ()
        for size in range(1, count + 1):
            for awarded in itertools.combinations(indices, size):
                head = self.best_for_set(
                    period,
                    awarded,
                    tuple(standing[index] for index in awarded),
                    (),
                    extra_quotes=(count - size) if shopping else 0,
                )
                if head is not None and head.key > best.key:
                    best, best_set = head, awarded
        return best, best_set

    def myopic(self) -> RelationshipBound:
        standing = self.initial()
        path = _EMPTY
        heads: list[_Path] = []
        for period in range(1, self.count + 1):
            head, awarded = self._best_now(period, standing)
            heads.append(head)
            standing = self._next(standing, awarded, ())
        for head in reversed(heads):
            path = path.prepend(head)
        return _bound(path)

    def shopping(self) -> RelationshipBound:
        """Myopic and shopping: quote everyone each period, award the best, pay for it.

        The naive anchor the retaliation worlds are built for. A dropped
        supplier raises its schedule next period, so the shopper's later
        choices are made among suppliers it has already offended.
        """
        standing = self.initial()
        heads: list[_Path] = []
        for period in range(1, self.count + 1):
            head, awarded = self._best_now(period, standing, shopping=True)
            heads.append(head)
            standing = self._next(standing, awarded, (), quoted_everyone=True)
        path = _EMPTY
        for head in reversed(heads):
            path = path.prepend(head)
        return _bound(path)

    def loyal(self) -> RelationshipBound:
        standing = self.initial()
        first, chosen = self._best_now(1, standing)
        heads = [first]
        standing = self._next(standing, chosen, ())
        for period in range(2, self.count + 1):
            head = (
                self.best_for_set(
                    period, chosen, tuple(standing[index] for index in chosen), ()
                )
                if chosen
                else None
            )
            if head is None:
                head = self.defer_path(period, ())
                standing = self._next(standing, (), ())
            else:
                standing = self._next(standing, chosen, ())
            heads.append(head)
        path = _EMPTY
        for head in reversed(heads):
            path = path.prepend(head)
        return _bound(path)


def _bound(path: _Path) -> RelationshipBound:
    results = [
        {"awarded_supplier_ids": sorted({row["supplier_id"] for row in plan})}
        for plan in path.plans
    ]
    return RelationshipBound(
        contribution_margin_usd=round(path.margin, 8),
        period_margins=tuple(round(value, 8) for value in path.margins),
        period_plans=path.plans,
        completed_kits=path.kits,
        cash_spend_usd=round(path.cash, 8),
        actions_required=path.actions,
        elapsed_days=path.elapsed,
        switches=count_switches(results),
    )


def _economic_payload(family_case: Mapping[str, Any]) -> bytes:
    economic = _plain(family_case)
    economic["interaction"].pop("sample_noise", None)
    economic["interaction"].pop("counter_feedback", None)
    return _env().canonical_json_bytes(economic)


@lru_cache(maxsize=64)
def _cached_references(
    payload: bytes,
) -> tuple[RelationshipBound, RelationshipBound, RelationshipBound, RelationshipBound]:
    solver = _Solver(json.loads(payload))
    return solver.solve(), solver.myopic(), solver.loyal(), solver.shopping()


def solve_relationship_upper_bound(family_case: Mapping[str, Any]) -> RelationshipBound:
    """The exact T-period optimum under full information."""
    return copy.deepcopy(_cached_references(_economic_payload(family_case))[0])


def solve_myopic_reference(family_case: Mapping[str, Any]) -> RelationshipBound:
    """Each period optimized on its own; standing is used, never invested in."""
    return copy.deepcopy(_cached_references(_economic_payload(family_case))[1])


def solve_loyal_reference(family_case: Mapping[str, Any]) -> RelationshipBound:
    """The first period's optimum, re-awarded every period after."""
    return copy.deepcopy(_cached_references(_economic_payload(family_case))[2])


def solve_shopping_reference(family_case: Mapping[str, Any]) -> RelationshipBound:
    """Myopic, and quoting every supplier every period: the naive anchor."""
    return copy.deepcopy(_cached_references(_economic_payload(family_case))[3])


__all__ = [
    "MAXIMUM_PERIODS",
    "MINIMUM_PERIODS",
    "PERIOD_DECISIONS",
    "PERIOD_FIELDS",
    "PERIOD_OVERRIDE_FIELDS",
    "RELATIONSHIP_FIELDS",
    "STANDING_LIMIT",
    "RelationshipBound",
    "advance_entry",
    "close_period",
    "complete_period_results",
    "count_switches",
    "effective_supplier",
    "initial_standing",
    "period_case",
    "period_count",
    "period_objective",
    "period_schedule",
    "period_state_fields",
    "periods_declared",
    "realize_delivery",
    "relationship_applied",
    "solve_loyal_reference",
    "solve_myopic_reference",
    "solve_relationship_upper_bound",
    "solve_shopping_reference",
    "validate_periods",
    "validate_relationship",
]
