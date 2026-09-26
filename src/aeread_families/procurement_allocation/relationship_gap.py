"""Why Gemini 3.8 Flash and GLM 5.3 Flash differ on the repeated-sourcing worlds:
an exact split of the gap by economic term, and a typed count of the decisions
behind it.

A derived analysis in the Tier 1 sense. It reads only published bundles under
``evidence/procurement_allocation/`` (``reports/plan.json``, ``tables/cells.jsonl``,
``tables/periods.jsonl``, ``trajectories/sanitized.jsonl``) and the committed
world cases their plans name, re-sealed per seed by the campaign's own
``episode_case`` and checked against every cell's ``case_content_sha256``. It
regenerates byte-identical output (``--check``).

**Endpoint.** Minus regret to the T-period bound: ``contribution_margin_usd -
upper_bound_usd``, higher is better. The bound is one number per world, the
same on every seed and both sides (checked), so the paired gap equals the
margin gap exactly; the bound's own plan for each period is the baseline every
part is measured against, which makes a part read as a shortfall against the
optimum and puts a lost period in one place.

**Replay.** Every cell's published trajectory is re-driven through
``ProcurementAllocationPlugin``. At each period close the award is evaluated by
``evaluate_award`` on ``relationship.period_case``, the family's own period
evaluation, and the replay must reproduce every published period margin.
Periods are scored on expected units: the delivery draw only feeds the history
the buyer reads next, and a sample's noise only what the buyer believes; the
score reads the supplier's true yield and on-time rate. So there is no luck
part, and the report counts the periods whose realized delivery differed from
the scored kits to show it.

**Parts**, each per period against the bound's plan for that period, summed
over the four periods:

- ``service``: expected kits times revenue per kit, less the shortfall penalty;
- ``list_price``: minus quantity times each awarded supplier's declared list
  price (which suppliers, how many units);
- ``relationship_price``: minus quantity times the shift the standing puts on
  the list price: a loyalty discount lowers it, a retaliation markup raises it;
- ``negotiated_price``: minus quantity times the concession an accepted
  counter-offer won below the quoted price;
- ``logistics``: minus shipping, duty, working-capital and refund financing and
  return freight, plus the expected defect recovery;
- ``information``: minus inquiries, quotes, samples and counters;
- ``periods_lost``: a period that ended without a feasible award (a rejected
  award, a malformed action, a period never played) scores its outside option;
  this part carries the bound's whole pre-information margin for that period
  against it, so the loss is not spread across the other parts.

**Unit.** The world. Each seed re-seals the world's delivery draws and sample
noise, so the buyer reads different samples on each seed and the routes run at
temperature 1.0; even so one route's decisions often repeat across seeds
(``unit_check`` counts distinct decision sequences per world). Worlds are the
independent unit and every interval is a world-clustered percentile bootstrap.

**Classes** are diagnostic and may overlap: malformed actions and the periods
they left unplayed, rejected awards by cause, awards above the supplier's
floor, rejected counters, loyalty discounts and retaliation markups paid,
supplier switches and inquiries, each located at its step.

**References.** The myopic, loyal and shopping references every cell publishes
are reconstructed period by period from the family's solver on the same world,
checked against the published values, and split into the same parts.

The report follows ``aeread.gap_decomposition/0.1``.

    python -m aeread_families.procurement_allocation.relationship_gap --write
    python -m aeread_families.procurement_allocation.relationship_gap --check
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.task.scheduler import ActionEnvelope, ParseResult

from . import environment as env
from . import relationship as rel
from .relationship_campaign import episode_case

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence" / "procurement_allocation"
OUT = EVIDENCE / "procurement_allocation_relationship_gap"
BOOTSTRAP_SEED = 20260925
BOOTSTRAP_DRAWS = 10000
TOLERANCE = 1e-6


@dataclass(frozen=True)
class Comparison:
    suffix: str
    left: str
    right: str
    claim_status: str
    scope: str


COMPARISONS: tuple[Comparison, ...] = (
    Comparison(
        "holdout",
        "procurement_allocation_relationship_holdout_gemini38_flash_confirmatory_v1",
        "procurement_allocation_relationship_holdout_glm53_flash_confirmatory_v1",
        "descriptive_post_hoc",
        "the confirmatory holdout pack (relationship_holdout_v1); the decomposition was not pre-registered, so it "
        "explains the published gap and adds no confirmatory claim",
    ),
    Comparison(
        "dev2",
        "procurement_allocation_relationship_dev2_gemini38_flash_variance_v2",
        "procurement_allocation_relationship_dev2_glm53_flash_variance_v2",
        "development_qualification",
        "the development pack (relationship_dev_v2), read to see whether the parts hold on another set of worlds",
    ),
)

ECONOMIC = ("service", "list_price", "relationship_price", "negotiated_price", "logistics")
COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("service", "kits sold, less the shortfall penalty", "outcome",
     "Expected completed kits times revenue per kit, less the shortfall penalty on the target, against the bound's plan for the same period."),
    ("list_price", "suppliers and quantities at list price", "decision",
     "Minus quantity times each awarded supplier's declared list price: which suppliers were awarded and how many units."),
    ("relationship_price", "loyalty discounts and retaliation markups", "decision",
     "Minus quantity times the shift the relationship standing puts on the list price: a loyalty streak lowers it, a supplier quoted and dropped last period raises it."),
    ("negotiated_price", "counter-offer concessions", "decision",
     "Minus quantity times the concession an accepted counter-offer won below the quoted price."),
    ("logistics", "shipping, duty, financing and returns", "cost",
     "Minus shipping, duty, working-capital cost, return freight and refund financing, plus the expected defect recovery."),
    ("information", "inquiries, quotes, samples and counters", "cost",
     "Minus what the buyer paid to inquire, quote, sample and counter, against what the bound's plan pays in the same period."),
    ("periods_lost", "periods lost to a rejected award, a malformed action or never played", "procedure",
     "A period that ends without a feasible award scores its outside option less its information; this part is that outside option less the bound's whole pre-information margin for the period."),
)
KEYS = tuple(key for key, *_ in COMPONENTS)

CLASSES: dict[str, dict[str, str]] = {
    "malformed_action": {
        "group": "format", "label": "an action the environment could not parse ended the episode",
        "amount": "USD, margin sign: the periods_lost part of the failed period and every period after it"},
    "unplayed_period": {
        "group": "procedure", "label": "a period never played because the episode had ended",
        "amount": "USD, margin sign: that period's periods_lost part"},
    "below_minimum_service": {
        "group": "outcome", "label": "an award rejected because its expected kits fell below the period's minimum service",
        "amount": "USD, margin sign: that period's periods_lost part"},
    "late_award": {
        "group": "decision", "label": "an award placed on a day when one of its lines could no longer arrive by the deadline",
        "amount": "USD, margin sign: the period's periods_lost part when the award was rejected, else its service part"},
    "unverified_sample": {
        "group": "procedure", "label": "an award rejected for a supplier with no verified sample",
        "amount": "USD, margin sign: that period's periods_lost part"},
    "over_capacity": {
        "group": "procedure", "label": "an award rejected for ordering above a supplier's capacity",
        "amount": "USD, margin sign: that period's periods_lost part"},
    "awarded_above_floor": {
        "group": "decision", "label": "a feasible award priced above the supplier's floor on at least one line",
        "amount": "USD, margin sign: minus quantity times (awarded price minus the floor at that standing), summed over the award's lines"},
    "counter_rejected": {
        "group": "decision", "label": "a counter-offer the supplier refused",
        "amount": "USD, margin sign: minus the counter's cost"},
    "loyalty_discount": {
        "group": "decision", "label": "a feasible award priced under a loyalty discount (a gain, not a failure)",
        "amount": "USD, margin sign (positive): quantity times the discount below list, summed over the award's lines"},
    "retaliation_markup": {
        "group": "decision", "label": "a feasible award priced under a retaliation markup from a supplier quoted and dropped the period before",
        "amount": "USD, margin sign: minus quantity times the markup above list, summed over the award's lines"},
    "supplier_switch": {
        "group": "decision", "label": "a feasible award whose supplier set differs from the previous feasible award's (as the family counts switches)",
        "amount": "none: counted, not priced here; its price shows in the loyalty and retaliation classes"},
    "inquiry": {
        "group": "procedure", "label": "a verbal inquiry: it never authorizes an award",
        "amount": "USD, margin sign: minus the inquiry fee"},
}
INFORMATION_ACTIONS = frozenset({"inquire", "request_quote", "request_sample", "counter_offer"})


# --------------------------------------------------------------------------
# Published inputs
# --------------------------------------------------------------------------


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _plan(bundle: str) -> dict[str, Any]:
    return json.loads((EVIDENCE / bundle / "reports" / "plan.json").read_text(encoding="utf-8"))


def _cells(bundle: str) -> list[dict[str, Any]]:
    return _jsonl(EVIDENCE / bundle / "tables" / "cells.jsonl")


def _period_rows(bundle: str) -> dict[tuple[str, int], dict[int, dict[str, Any]]]:
    out: dict[tuple[str, int], dict[int, dict[str, Any]]] = collections.defaultdict(dict)
    for row in _jsonl(EVIDENCE / bundle / "tables" / "periods.jsonl"):
        out[(row["case_id"], int(row["seed"]))][int(row["period"])] = row
    return out


def _steps(bundle: str) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in _jsonl(EVIDENCE / bundle / "trajectories" / "sanitized.jsonl"):
        by[row["source_receipt_sha256"]].append(row)
    for rows in by.values():
        rows.sort(key=lambda r: r["step_index"])
        if [r["step_index"] for r in rows] != list(range(len(rows))):
            raise ValueError("a published trajectory skips a step index")
        # The Examiner's round: how many times the episode's first phase has started up to this step.
        first, seen, count = rows[0]["phase_id"], set(), -1
        for r in rows:
            if r["phase_id"] == first and r["phase_instance_id"] not in seen:
                count += 1
            seen.add(r["phase_instance_id"])
            r["_round_index"] = count
    return by


def _worlds(bundle: str) -> dict[str, dict[str, Any]]:
    """The committed world case files the plan names, checked against the plan's digests."""
    out = {}
    for row in _plan(bundle)["worlds"]:
        raw = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
        if raw["content_sha256"] != row["content_sha256"] or raw["case_id"] != row["case_id"]:
            raise ValueError(f"world {row['case_id']} differs from the plan that ran it")
        out[row["case_id"]] = raw
    return out


def _model(bundle: str) -> str:
    return str(_plan(bundle)["route"]["model"])


# --------------------------------------------------------------------------
# Economic terms of one award
# --------------------------------------------------------------------------


def _standing(entry: Any) -> dict[str, int]:
    if isinstance(entry, Mapping):
        return {"consecutive_awards": int(entry["consecutive_awards"]), "retaliation_periods_left": int(entry["retaliation_periods_left"])}
    return {"consecutive_awards": int(entry[0]), "retaliation_periods_left": int(entry[1])}


def award_terms(
    view: Mapping[str, Any],
    award_lines: Sequence[Mapping[str, Any]],
    offers: Mapping[str, Mapping[str, Any]],
    standing: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """A feasible award's margin split into the economic parts, and its lines priced three ways.

    Purchase cost is quantity times the awarded price, and the awarded price is
    the declared list price, shifted by the relationship standing (the quote),
    then lowered by any accepted counter. The three pieces sum to the purchase.
    """
    objective = view["objective"]
    suppliers = {str(s["supplier_id"]): s for s in view["suppliers"]}
    terms = {key: 0.0 for key in ECONOMIC}
    lines = []
    for line in award_lines:
        offer = offers[line["offer_id"]]
        supplier_id = str(offer["supplier_id"])
        quantity = int(line["quantity"])
        supplier = suppliers[supplier_id]
        entry = _standing(standing[supplier_id])
        effective = rel.effective_supplier(supplier, entry)
        applied = rel.relationship_applied(supplier, entry) or {"loyalty_discount": 0.0, "retaliation_markup": 0.0}
        listed = float(supplier["private_terms"]["base_unit_price_usd"])
        quoted = float(effective["private_terms"]["base_unit_price_usd"])
        floor = float(effective["private_terms"]["negotiation"]["floor_unit_price_usd"])
        paid = float(offer["unit_price_usd"])
        if applied["loyalty_discount"] and applied["retaliation_markup"]:
            raise ValueError("a standing carries a loyalty discount and a retaliation markup at once")
        terms["list_price"] -= quantity * listed
        terms["relationship_price"] -= quantity * (quoted - listed)
        terms["negotiated_price"] -= quantity * (paid - quoted)
        lines.append({"supplier_id": supplier_id, "quantity": quantity, "listed": listed, "quoted": quoted,
                      "floor": floor, "paid": paid, "loyalty_discount": float(applied["loyalty_discount"]),
                      "retaliation_markup": float(applied["retaliation_markup"]),
                      "lead_time_days": int(offer["lead_time_days"])})
    terms["service"] = (int(evaluation["completed_kits"]) * float(objective["revenue_per_completed_kit_usd"])
                        - float(evaluation["shortfall_penalty_usd"]))
    terms["logistics"] = -(float(evaluation["shipping_cost_usd"]) + float(evaluation["duty_cost_usd"])
                           + float(evaluation["working_capital_cost_usd"]) + float(evaluation["return_freight_cost_usd"])
                           + float(evaluation["refund_financing_cost_usd"]) - float(evaluation["expected_recovery_usd"]))
    purchase = -(terms["list_price"] + terms["relationship_price"] + terms["negotiated_price"])
    if abs(purchase - float(evaluation["purchase_cost_usd"])) > TOLERANCE:
        raise ValueError("the priced lines do not sum to the evaluated purchase cost")
    rebuilt = sum(terms.values()) - float(evaluation["information_cost_usd"])
    if abs(rebuilt - float(evaluation["raw_contribution_margin_usd"])) > TOLERANCE:
        raise ValueError("the economic terms do not rebuild the award's margin")
    return terms, lines


def period_parts(model: Mapping[str, Any], bound: Mapping[str, Any]) -> dict[str, float]:
    """One period's parts: the side's period against the bound's plan for the same period.

    A period without a feasible award has no economic terms; the bound's whole
    pre-information margin for it goes to ``periods_lost``, so the loss sits in
    one part. The parts sum to the side's period margin minus the bound's.
    """
    parts = {key: 0.0 for key in KEYS}
    parts["information"] = -(float(model["information"]) - float(bound["information"]))
    bound_terms = bound["terms"] or {key: 0.0 for key in ECONOMIC}
    if model["terms"] is None:
        parts["periods_lost"] = float(model["outside"]) - float(bound["outside"]) - sum(bound_terms.values())
    else:
        for key in ECONOMIC:
            parts[key] = float(model["terms"][key]) - float(bound_terms[key])
        parts["periods_lost"] = -float(bound["outside"])
    return parts


# --------------------------------------------------------------------------
# The side: replay every published trajectory
# --------------------------------------------------------------------------


def replay_cell(family_case: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Re-drive a published trajectory; one record per period, with the steps that made it.

    Each record carries the period's margin, information spend, outside option,
    economic terms (feasible awards only), priced lines, violations, the step
    that closed it and every step that bought information.
    """
    plugin = env.ProcurementAllocationPlugin()
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)
    records: list[dict[str, Any]] = []
    buying: list[dict[str, Any]] = []
    counters: list[dict[str, Any]] = []
    last_step = None
    for step in steps:
        if state["done"]:
            raise ValueError("a published trajectory continues after the episode ended")
        action = step["action"]
        valid = bool((step.get("outcome") or {}).get("valid"))
        if valid:
            legality = plugin.legal(family_case, state, "buyer", phase, action)
            if not legality.legal:
                raise ValueError(f"step {step['step_index']} was published valid but replays illegal")
            envelope = ActionEnvelope(seat_id="buyer", valid=True, action=action, parse=ParseResult.success(action), legality=legality)
        else:
            code = (step.get("parse") or {}).get("error_code") or (step.get("outcome") or {}).get("failure_code")
            envelope = ActionEnvelope(seat_id="buyer", valid=False, action=None, parse=ParseResult.failure(str(code)), legality=None)
        before = state
        transition = plugin.step(family_case, state, phase, {"buyer": envelope})
        state = transition.state
        last_step = step
        period = int(before["period"])
        closed = len(state["period_results"]) > len(before["period_results"])
        spent_after = (float(state["period_results"][-1]["information_cost_usd"]) if closed
                       else float(state["information_cost_usd"]))
        cost = round(spent_after - float(before["information_cost_usd"]), 8) if valid else 0.0
        kind = action.get("action") if isinstance(action, Mapping) else None
        if cost:
            if kind not in INFORMATION_ACTIONS:
                raise ValueError(f"step {step['step_index']} ({kind}) spent on information")
            buying.append({"step": step, "action": kind, "cost": cost, "period": period})
        if kind == "counter_offer":
            counters.append({"step": step, "accepted": bool(transition.consequences.get("accepted")), "cost": cost, "period": period})
        if closed:
            result = state["period_results"][-1]
            view = rel.period_case(family_case, period)
            record = {"period": period, "margin": float(result["contribution_margin_usd"]),
                      "information": float(result["information_cost_usd"]), "terms": None, "lines": [],
                      "outside": float(view["objective"]["defer_value_usd"]), "violations": list(result["violations"]),
                      "close_step": step, "decision": result["decision"], "reason": result["termination_reason"],
                      "elapsed_days": int(before["elapsed_days"]), "completed_kits": int(result["completed_kits"])}
            if result["termination_reason"] == "submitted":
                evaluation = env.evaluate_award(view, award_lines=action["award_lines"], offers=before["offers"],
                                                quality_evidence=before["quality_evidence"], elapsed_days=int(before["elapsed_days"]),
                                                information_cost_usd=float(before["information_cost_usd"]))
                if abs(float(evaluation["contribution_margin_usd"]) - record["margin"]) > TOLERANCE:
                    raise ValueError("the period evaluation does not reproduce the environment's period margin")
                deadline = int(view["objective"]["deadline_days"])
                record["late_lines"] = sorted(
                    str(before["offers"][line["offer_id"]]["supplier_id"]) for line in action["award_lines"]
                    if line["offer_id"] in before["offers"]
                    and int(before["elapsed_days"]) + int(before["offers"][line["offer_id"]]["lead_time_days"]) > deadline)
                if evaluation["feasible"]:
                    record["terms"], record["lines"] = award_terms(view, action["award_lines"], before["offers"],
                                                                   before["relationship"], evaluation)
                    record["outside"] = 0.0
                    record["awarded"] = sorted({line["supplier_id"] for line in record["lines"]})
                else:
                    record["status"] = "rejected"
            record.setdefault("status", "award" if record["terms"] is not None else record["decision"])
            record["buying"] = [b for b in buying if b["period"] == period]
            record["counters"] = [c for c in counters if c["period"] == period]
            records.append(record)
    terminal = plugin.terminal(family_case, state)
    if terminal is None:
        raise ValueError("a published trajectory did not reach a terminal state")
    results = rel.complete_period_results(family_case, terminal)
    for result in results[len(records):]:
        period = int(result["period"])
        view = rel.period_case(family_case, period)
        records.append({"period": period, "margin": float(result["contribution_margin_usd"]),
                        "information": float(result["information_cost_usd"]), "terms": None, "lines": [],
                        "outside": float(view["objective"]["defer_value_usd"]), "violations": list(result["violations"]),
                        "close_step": last_step, "decision": result["decision"], "status": result["decision"],
                        "reason": terminal["reason"], "failure_code": terminal["failure_code"],
                        "buying": [b for b in buying if b["period"] == period],
                        "counters": [c for c in counters if c["period"] == period],
                        "elapsed_days": int(result["elapsed_days"]), "completed_kits": 0, "late_lines": []})
    for record, result in zip(records, results):
        if abs(record["margin"] - float(result["contribution_margin_usd"])) > TOLERANCE:
            raise ValueError("replayed period margins differ from the environment's period results")
        if abs(sum(b["cost"] for b in record["buying"]) - record["information"]) > TOLERANCE:
            raise ValueError("the information steps of a period do not sum to its information cost")
    return records


# --------------------------------------------------------------------------
# The bound and the published references, period by period
# --------------------------------------------------------------------------


def _signature_extras(signature: Sequence[Any]) -> tuple[tuple[str, ...], int]:
    prequalified, extra_quotes = [], 0
    for item in signature[1]:
        if str(item).startswith("extra_quotes:"):
            extra_quotes = int(str(item).split(":", 1)[1])
        else:
            prequalified.append(str(item))
    return tuple(prequalified), extra_quotes


def _reference_period(solver: Any, family_case: Mapping[str, Any], period: int, standing: tuple, plan: Sequence[Mapping[str, Any]],
                      signature: Sequence[Any], margin: float) -> dict[str, Any]:
    """One period of a solver path, evaluated term by term exactly as the solver scored it."""
    interaction = family_case["interaction"]
    view = rel.period_case(family_case, period)
    index = {str(s["supplier_id"]): i for i, s in enumerate(family_case["suppliers"])}
    prequalified, extra_quotes = _signature_extras(signature)
    information = sum(solver._sample_terms(index[s])[1] for s in prequalified) + extra_quotes * float(interaction["quote_cost_usd"])
    elapsed = sum(solver._sample_terms(index[s])[0] for s in prequalified) + extra_quotes * int(interaction["quote_days"])
    record = {"period": period, "margin": float(margin), "terms": None, "lines": [], "outside": 0.0,
              "prequalified": list(prequalified), "extra_quotes": extra_quotes, "plan": [dict(row) for row in plan]}
    if not plan:
        record["information"] = round(information, 8)
        record["outside"] = float(view["objective"]["defer_value_usd"])
        if abs(record["outside"] - record["information"] - record["margin"]) > TOLERANCE:
            raise ValueError("a reference's deferred period does not reproduce its margin")
        return record
    offers, qualities, lines = {}, {}, []
    for row in plan:
        i = index[row["supplier_id"]]
        entry = standing[i]
        option = next(o for o in solver.options(i, entry[0], entry[1]) if o["mode"] == row["mode"] and o["quantity"] == row["quantity"])
        offer = option["offer"]
        offers[offer["offer_id"]] = offer
        lines.append({"offer_id": offer["offer_id"], "quantity": int(row["quantity"])})
        sample_days, sample_cost = solver._sample_terms(i)
        negotiated = row["mode"] == "negotiated"
        information += float(interaction["quote_cost_usd"]) + (0.0 if entry[2] else sample_cost) + (float(interaction["counter_cost_usd"]) if negotiated else 0.0)
        elapsed += int(interaction["quote_days"]) + (0 if entry[2] else sample_days) + (int(interaction["counter_days"]) if negotiated else 0)
        supplier = family_case["suppliers"][i]
        qualities[row["supplier_id"]] = {**supplier["private_terms"]["quality"], "supplier_id": row["supplier_id"],
                                         "variant_id": supplier["private_terms"]["variant_id"], "evidence_status": "verified_sample"}
    evaluation = env.evaluate_award(view, award_lines=lines, offers=offers, quality_evidence=qualities,
                                    elapsed_days=elapsed, information_cost_usd=round(information, 8))
    if not evaluation["feasible"] or abs(float(evaluation["contribution_margin_usd"]) - float(margin)) > TOLERANCE:
        raise ValueError("a reference period does not reproduce the solver's margin")
    record["information"] = float(evaluation["information_cost_usd"])
    record["terms"], record["lines"] = award_terms(view, lines, offers, {str(s["supplier_id"]): standing[k]
                                                                        for k, s in enumerate(family_case["suppliers"])}, evaluation)
    return record


REFERENCES: tuple[tuple[str, str, str, str], ...] = (
    ("myopic", "myopic_reference_usd", "scripted myopic reference",
     "Each period optimized on its own under full information: the relationship standing is used, never invested in."),
    ("loyal", "loyal_reference_usd", "scripted loyal reference",
     "The first period's full-information optimum, re-awarded every period after."),
    ("shopping", "shopping_reference_usd", "scripted shopping reference",
     "Myopic, and quoting every supplier every period: each supplier it drops retaliates the next period."),
)


@lru_cache(maxsize=32)
def _solved(payload_bytes: bytes) -> dict[str, list[dict[str, Any]]]:
    """The bound and the three references on one world, each as per-period records."""
    family_case = json.loads(payload_bytes)
    solver = rel._Solver(family_case)
    count = rel.period_count(family_case)
    out: dict[str, list[dict[str, Any]]] = {}

    standing = solver.initial()
    path = solver.value(1, standing)
    records = []
    index = {str(s["supplier_id"]): i for i, s in enumerate(family_case["suppliers"])}
    for period in range(1, count + 1):
        plan, margin, signature = path.plans[period - 1], path.margins[period - 1], path.signature[period - 1]
        records.append(_reference_period(solver, family_case, period, standing, plan, signature, margin))
        awarded = tuple(sorted(index[row["supplier_id"]] for row in plan))
        prequalified = tuple(sorted(index[s] for s in _signature_extras(signature)[0]))
        standing = solver._next(standing, awarded, prequalified)
    out["bound"] = records

    def walk(heads_and_sets, quoted_everyone=False):
        standing, records = solver.initial(), []
        for period, (head, awarded) in enumerate(heads_and_sets(), start=1):
            records.append(_reference_period(solver, family_case, period, standing, head.plans[0], head.signature[0], head.margin))
            standing = solver._next(standing, awarded, (), quoted_everyone=quoted_everyone)
        return records

    def myopic():
        standing = solver.initial()
        for period in range(1, count + 1):
            head, awarded = solver._best_now(period, standing)
            yield head, awarded
            standing = solver._next(standing, awarded, ())

    def shopping():
        standing = solver.initial()
        for period in range(1, count + 1):
            head, awarded = solver._best_now(period, standing, shopping=True)
            yield head, awarded
            standing = solver._next(standing, awarded, (), quoted_everyone=True)

    def loyal():
        standing = solver.initial()
        first, chosen = solver._best_now(1, standing)
        yield first, chosen
        standing = solver._next(standing, chosen, ())
        for period in range(2, count + 1):
            head = solver.best_for_set(period, chosen, tuple(standing[i] for i in chosen), ()) if chosen else None
            if head is None:
                head = solver.defer_path(period, ())
                yield head, ()
                standing = solver._next(standing, (), ())
            else:
                yield head, chosen
                standing = solver._next(standing, chosen, ())

    out["myopic"] = walk(myopic)
    out["loyal"] = walk(loyal)
    out["shopping"] = walk(shopping, quoted_everyone=True)
    # Each total is checked against the value every published cell carries (``_side``); each period against
    # the solver path it came from (``_reference_period``).
    return out


def world_references(world: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return _solved(env.canonical_json_bytes(world["payload"]))


# --------------------------------------------------------------------------
# One cell
# --------------------------------------------------------------------------


def _money(value: float) -> str:
    if abs(value) < 0.005:
        return "$0.00"
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def _plan_text(record: Mapping[str, Any]) -> str:
    if not record.get("plan") and not record.get("lines"):
        return "no award"
    rows = record.get("plan") or [{"supplier_id": l["supplier_id"], "quantity": l["quantity"]} for l in record["lines"]]
    return ", ".join(f"{r['supplier_id']} x{r['quantity']}" + (f" ({r['mode']})" if r.get("mode") else "") for r in rows)


def _at(step: Mapping[str, Any]) -> dict[str, Any]:
    action = step["action"]
    return {"step_index": int(step["step_index"]), "round_index": int(step["_round_index"]),
            "phase_id": step["phase_id"], "seat_id": step["seat_id"],
            "action": action.get("action") if isinstance(action, Mapping) else "unparseable"}


def _row(record: Mapping[str, Any], step: Mapping[str, Any], component: str, amount: float, note: str) -> dict[str, Any]:
    return {**_at(step), "period": int(record["period"]), "component": component, "amount": amount, "note": note}


def analyse_cell(records: Sequence[Mapping[str, Any]], bound: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Parts, contribution rows and class instances of one replayed cell against its world's bound."""
    parts = {key: 0.0 for key in KEYS}
    rows: list[dict[str, Any]] = []
    found: list[dict[str, Any]] = []
    previous: set[str] | None = None
    for record, target in zip(records, bound):
        if int(record["period"]) != int(target["period"]):
            raise ValueError("period order differs between the cell and the bound")
        p = period_parts(record, target)
        for key in KEYS:
            parts[key] += p[key]
        period, close = int(record["period"]), record["close_step"]
        # information: every step that bought it, and the bound's spend for the period at the step that closed it
        for bought in record["buying"]:
            what = {"inquire": "inquiry", "request_quote": "quote", "request_sample": "sample", "counter_offer": "counter"}[bought["action"]]
            supplier = (bought["step"]["action"] or {}).get("supplier_id")
            rows.append(_row(record, bought["step"], "information", -bought["cost"],
                             f"period {period}: {what} to {supplier} for {_money(bought['cost'])}"))
        if target["information"]:
            rows.append(_row(record, close, "information", float(target["information"]),
                             f"period {period}: the bound's plan spends {_money(target['information'])} on information in this period"))
        if record["terms"] is not None:
            for key in ECONOMIC:
                if p[key]:
                    rows.append(_row(record, close, key, p[key], _economic_note(key, period, record, target)))
        if p["periods_lost"]:
            if record["status"] == "unplayed":
                note = (f"period {period} was never played after the malformed action; it scores its outside option "
                        f"{_money(record['outside'])} against the bound's {_money(target['margin'] + target['information'])} before information")
            elif record["status"] == "failed":
                note = (f"period {period} ended on a malformed action and scores its outside option {_money(record['outside'])} "
                        f"less information, against the bound's {_money(target['margin'] + target['information'])} before information")
            else:
                note = (f"period {period} award rejected ({', '.join(record['violations'])}); it scores its outside option "
                        f"against the bound's {_money(target['margin'] + target['information'])} before information")
            rows.append(_row(record, close, "periods_lost", p["periods_lost"], note))
        # classes
        cls = lambda key, step, amount, note: found.append({**_at(step), "period": period, "class": key, "amount": amount, "note": note})
        for bought in record["buying"]:
            if bought["action"] == "inquire":
                supplier = (bought["step"]["action"] or {}).get("supplier_id")
                cls("inquiry", bought["step"], -bought["cost"], f"period {period}: asked {supplier} for verbal terms")
        for counter in record["counters"]:
            if not counter["accepted"]:
                a = counter["step"]["action"]
                cls("counter_rejected", counter["step"], -counter["cost"],
                    f"period {period}: {a['supplier_id']} refused a counter at {a['proposal'].get('unit_price_usd')} per unit")
        if record["status"] == "rejected":
            violations = " ".join(record["violations"])
            amount = p["periods_lost"]
            if "minimum_service_not_met" in violations:
                cls("below_minimum_service", close, amount,
                    f"period {period}: the award's expected kits ({record['completed_kits']}) fell below minimum service")
            if "sample_not_verified" in violations:
                cls("unverified_sample", close, amount, f"period {period}: awarded a supplier with no verified sample ({violations})")
            if "over_capacity" in violations:
                cls("over_capacity", close, amount, f"period {period}: ordered above a supplier's capacity ({violations})")
            if record.get("late_lines"):
                cls("late_award", close, amount, f"period {period}: awarded on day {record['elapsed_days']}, too late for "
                                                 f"{', '.join(record['late_lines'])} to arrive by the deadline")
            if not any(k in violations for k in ("minimum_service_not_met", "sample_not_verified", "over_capacity")):
                raise ValueError(f"a rejected award with no declared class: {violations}")
        elif record["status"] == "failed":
            if record.get("failure_code") != "malformed_procurement_action":
                raise ValueError(f"an episode ended on {record.get('failure_code')}, which no class declares")
            lost = sum(period_parts(r, t)["periods_lost"] for r, t in zip(records, bound) if int(r["period"]) >= period)
            later = sum(1 for r in records if r["status"] == "unplayed")
            cls("malformed_action", close, lost, f"period {period}: the buyer's action could not be parsed; the episode ended "
                                                 f"with {later} period{'s' if later != 1 else ''} unplayed")
        elif record["status"] == "unplayed":
            cls("unplayed_period", close, p["periods_lost"], f"period {period} was never played")
        elif record["status"] != "award":
            raise ValueError(f"a period ended as {record['status']}, which no class declares")
        if record["terms"] is not None:
            above = sum(l["quantity"] * (l["paid"] - l["floor"]) for l in record["lines"] if l["paid"] > l["floor"] + 1e-9)
            if above > 1e-9:
                over = [f"{l['supplier_id']} at {l['paid']:.4f} (floor {l['floor']:.4f})" for l in record["lines"] if l["paid"] > l["floor"] + 1e-9]
                cls("awarded_above_floor", close, -above, f"period {period}: awarded {'; '.join(over)}")
            discount = sum(-l["quantity"] * (l["quoted"] - l["listed"]) for l in record["lines"] if l["loyalty_discount"] > 0)
            if discount:
                names = ", ".join(f"{l['supplier_id']} {100 * l['loyalty_discount']:.2f}%" for l in record["lines"] if l["loyalty_discount"] > 0)
                cls("loyalty_discount", close, discount, f"period {period}: loyalty discount below list from {names}")
            markup = sum(-l["quantity"] * (l["quoted"] - l["listed"]) for l in record["lines"] if l["retaliation_markup"] > 0)
            if markup:
                names = ", ".join(f"{l['supplier_id']} {100 * l['retaliation_markup']:.2f}%" for l in record["lines"] if l["retaliation_markup"] > 0)
                cls("retaliation_markup", close, markup, f"period {period}: paid a retaliation markup above list to {names}")
            if record.get("late_lines"):
                cls("late_award", close, p["service"], f"period {period}: awarded on day {record['elapsed_days']}, too late for "
                                                       f"{', '.join(record['late_lines'])} to arrive by the deadline")
            current = set(record["awarded"])
            if previous and current != previous:
                cls("supplier_switch", close, 0.0, f"period {period}: awarded {', '.join(sorted(current))} after "
                                                   f"{', '.join(sorted(previous))}")
            previous = current
    return {"parts": parts, "contributions": rows, "instances": found}


def _economic_note(key: str, period: int, record: Mapping[str, Any], target: Mapping[str, Any]) -> str:
    mine, theirs = record["terms"][key], target["terms"][key] if target["terms"] else 0.0
    plan = _plan_text(record)
    if key == "service":
        return (f"period {period}: {plan} completes {record['completed_kits']} expected kits, {_money(mine)} net of the shortfall "
                f"penalty, against {_money(theirs)} on the bound's plan ({_plan_text(target)})")
    label = {"list_price": "list price", "relationship_price": "loyalty and retaliation shift", "negotiated_price": "counter concessions",
             "logistics": "shipping, duty, financing and returns"}[key]
    return f"period {period}: {plan}, {label} {_money(mine)} against {_money(theirs)} on the bound's plan ({_plan_text(target)})"


# --------------------------------------------------------------------------
# A side of one comparison
# --------------------------------------------------------------------------


def _decision(action: Any) -> Any:
    """An action without its free text: what the buyer decided, not how it phrased it."""
    if not isinstance(action, Mapping):
        return None
    return {key: value for key, value in action.items() if key not in ("message", "reason")}


def _side(side: str, bundle: str, keep: set[tuple[str, int]]) -> dict[str, Any]:
    worlds = _worlds(bundle)
    steps = _steps(bundle)
    period_rows = _period_rows(bundle)
    cells, rows, instances, residuals, row_residuals, traces = [], [], [], [], [], collections.defaultdict(set)
    replayed_periods = drawn_differs = awarded_periods = miscounted = 0
    statuses: collections.Counter = collections.Counter()
    for cell in _cells(bundle):
        if cell.get("status") != "completed" or (cell["world_case_id"], int(cell["seed"])) not in keep:
            continue
        world = worlds[cell["world_case_id"]]
        episode = episode_case(world, int(cell["seed"]))
        if episode["content_sha256"] != cell["case_content_sha256"] or episode["case_id"] != cell["case_id"]:
            raise ValueError(f"{cell['case_id']} does not re-seal to its published content")
        family_case = episode["payload"]
        trajectory = steps[cell["receipt_sha256"]]
        if len(trajectory) != int(cell["action_count"]):
            raise ValueError(f"{cell['case_id']}: trajectory length differs from the published action count")
        records = replay_cell(family_case, trajectory)
        published = [float(m) for m in cell["period_margins"]]
        if len(records) != len(published) or any(abs(r["margin"] - m) > TOLERANCE for r, m in zip(records, published)):
            raise ValueError(f"{cell['case_id']}: the replay does not reproduce the published period margins")
        for record in records:
            row = period_rows[(cell["case_id"], int(cell["seed"]))].get(int(record["period"]))
            if row is not None:
                if abs(float(row["contribution_margin_usd"]) - record["margin"]) > TOLERANCE:
                    raise ValueError(f"{cell['case_id']}: a published period row differs from the replay")
                if record["terms"] is not None:
                    awarded_periods += 1
                    drawn_differs += int(row["realized_completed_kits"]) != int(row["completed_kits"])
            replayed_periods += 1
        references = world_references(world)
        bound = references["bound"]
        if abs(sum(r["margin"] for r in bound) - float(cell["upper_bound_usd"])) > TOLERANCE:
            raise ValueError(f"{cell['case_id']}: the bound differs from the published upper bound")
        for key, field, *_ in REFERENCES:
            if abs(sum(r["margin"] for r in references[key]) - float(cell[field])) > TOLERANCE:
                raise ValueError(f"{cell['case_id']}: the {key} reference differs from the published {field}")
        statuses.update(r["status"] for r in records)
        result = analyse_cell(records, bound)
        endpoint = float(cell["contribution_margin_usd"]) - float(cell["upper_bound_usd"])
        if abs(endpoint + float(cell["regret_to_upper_bound_usd"])) > TOLERANCE:
            raise ValueError(f"{cell['case_id']}: regret is not the bound minus the margin")
        residuals.append(endpoint - sum(result["parts"].values()))
        counts = collections.Counter(i["class"] for i in result["instances"])
        if counts["supplier_switch"] != int(cell["switches"]):
            raise ValueError(f"{cell['case_id']}: switch count differs from the published cell")
        # The published action counts also count a malformed action as the type it attempted (P-T-11), so an
        # executed count may fall short of the published one by at most the cell's unparseable steps.
        executed = collections.Counter(s["action"]["action"] for s in trajectory if (s.get("outcome") or {}).get("valid"))
        unparsed = sum(1 for s in trajectory if not (s.get("outcome") or {}).get("valid"))
        published_counts = collections.Counter({k: int(v) for k, v in cell["action_counts"].items()})
        excess = {k: published_counts[k] - executed[k] for k in set(published_counts) | set(executed)}
        if any(v < 0 for v in excess.values()) or sum(excess.values()) != unparsed:
            raise ValueError(f"{cell['case_id']}: executed actions do not reconcile with the published action counts")
        if counts["inquiry"] != executed["inquire"] or sum(len(r["counters"]) for r in records) != executed["counter_offer"]:
            raise ValueError(f"{cell['case_id']}: replayed inquiries or counters differ from the trajectory")
        miscounted += unparsed
        where = {"side": side, "campaign_id": bundle, "receipt_sha256": cell["receipt_sha256"],
                 "world_seed": int(world["world_seed"]), "replicate_index": int(cell["seed"]), "unit": cell["slug"]}
        sums: collections.Counter = collections.Counter()
        for item in result["contributions"]:
            sums[item["component"]] += item["amount"]
            rows.append({**where, **item, "amount": round(item["amount"], 6)})
        row_residuals.extend(result["parts"][key] - sums[key] for key in KEYS)
        for item in result["instances"]:
            instances.append({**where, **item, "amount": round(item["amount"], 6)})
        traces[cell["slug"]].add(json.dumps([_decision(s["action"]) for s in trajectory], sort_keys=True))
        cells.append({**where, "stratum": cell["slug"].rsplit("_", 1)[0], "parts": result["parts"],
                      "classes": counts,
                      "amounts": collections.Counter({k: sum(i["amount"] for i in result["instances"] if i["class"] == k) for k in CLASSES}),
                      "seed": int(cell["seed"]), "world_case_id": cell["world_case_id"], "references": references})
    return {"cells": cells, "rows": rows, "instances": instances, "residuals": residuals, "row_residuals": row_residuals,
            "traces": {slug: len(v) for slug, v in sorted(traces.items())},
            "luck": {"awarded_periods": awarded_periods, "drawn_differs": drawn_differs, "periods": replayed_periods},
            "unparseable_steps_counted_as_attempted_type": miscounted,
            "period_status": {k: statuses[k] for k in ("award", "rejected", "failed", "unplayed", "defer")}}


def _paired_keys(comparison: Comparison) -> tuple[set[tuple[str, int]], list[dict[str, Any]]]:
    completed = {}
    excluded = []
    for bundle in (comparison.left, comparison.right):
        rows = _cells(bundle)
        completed[bundle] = {(r["world_case_id"], int(r["seed"])) for r in rows if r.get("status") == "completed"}
        for r in rows:
            if r.get("status") != "completed":
                excluded.append({"campaign_id": bundle, "world_case_id": r["world_case_id"], "seed": int(r["seed"]),
                                 "status": r.get("status"), "reason": "not completed; typed missingness, excluded with its pair"})
    keep = completed[comparison.left] & completed[comparison.right]
    for bundle in (comparison.left, comparison.right):
        for world, seed in sorted(completed[bundle] - keep):
            excluded.append({"campaign_id": bundle, "world_case_id": world, "seed": seed, "status": "completed",
                             "reason": "its pair did not complete; excluded so both sides cover the same cells"})
    return keep, sorted(excluded, key=lambda e: (e["campaign_id"], e["world_case_id"], e["seed"]))


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def _boot(values: Sequence[float], rng: random.Random) -> list[float] | None:
    if len(values) < 2:
        return None
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(BOOTSTRAP_DRAWS))
    return [round(means[int(0.025 * BOOTSTRAP_DRAWS)], 6), round(means[min(BOOTSTRAP_DRAWS - 1, int(0.975 * BOOTSTRAP_DRAWS))], 6)]


def _reference_parts(records: Sequence[Mapping[str, Any]], bound: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    parts = {key: 0.0 for key in KEYS}
    for record, target in zip(records, bound):
        for key, value in period_parts(record, target).items():
            parts[key] += value
    return parts


def analyse(comparison: Comparison) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    keep, excluded = _paired_keys(comparison)
    sides = {"left": _side("left", comparison.left, keep), "right": _side("right", comparison.right, keep)}
    by_world: dict[str, dict[str, list[dict[str, Any]]]] = {s: collections.defaultdict(list) for s in sides}
    for side, data in sides.items():
        for cell in data["cells"]:
            by_world[side][cell["unit"]].append(cell)
    paired = sorted(set(by_world["left"]) & set(by_world["right"]))
    if set(by_world["left"]) != set(by_world["right"]):
        raise ValueError("the two sides do not cover the same worlds")

    def world_mean(side: str, world: str, pick) -> float:
        cells = by_world[side][world]
        return sum(pick(c) for c in cells) / len(cells)

    rng = random.Random(BOOTSTRAP_SEED)

    def block(pick) -> dict[str, Any]:
        left = [world_mean("left", w, pick) for w in paired]
        right = [world_mean("right", w, pick) for w in paired]
        diffs = [a - b for a, b in zip(left, right)]
        return {"left": round(sum(left) / len(left), 6), "right": round(sum(right) / len(right), 6),
                "difference": round(sum(diffs) / len(diffs), 6), "difference_ci": _boot(diffs, rng)}

    per_world = []
    for w in paired:
        mean = lambda side, pick: world_mean(side, w, pick)
        total = lambda c: sum(c["parts"].values())
        per_world.append({"unit": w, "world_seed": int(by_world["left"][w][0]["world_seed"]),
                          "cells": {s: len(by_world[s][w]) for s in sides},
                          "left": round(mean("left", total), 6), "right": round(mean("right", total), 6),
                          "difference": round(mean("left", total) - mean("right", total), 6),
                          "components": {k: round(mean("left", lambda c, k=k: c["parts"][k]) - mean("right", lambda c, k=k: c["parts"][k]), 6)
                                         for k in KEYS}})
    realized = block(lambda c: sum(c["parts"].values()))
    components = [{"key": key, "label": label, "group": group, "description": description,
                   **block(lambda c, key=key: c["parts"][key])} for key, label, group, description in COMPONENTS]
    classes = []
    for key, meta in CLASSES.items():
        amounts = block(lambda c, key=key: c["amounts"][key])
        classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": meta["amount"],
                        "left_count": sum(c["classes"][key] for c in sides["left"]["cells"]),
                        "right_count": sum(c["classes"][key] for c in sides["right"]["cells"]),
                        "left_amount_per_market": amounts["left"], "right_amount_per_market": amounts["right"],
                        "amount_difference": amounts["difference"], "amount_difference_ci": amounts["difference_ci"]})

    # references, per world, against the same bound
    reference_world: dict[str, dict[str, dict[str, float]]] = {}
    replay_mismatches = 0
    for world in paired:
        refs = by_world["left"][world][0]["references"]
        if any(by_world[s][world][0]["references"] is not refs for s in sides):
            raise ValueError("the two sides' cells of a world did not share one reconstructed bound")
        reference_world[world] = {key: _reference_parts(refs[key], refs["bound"]) for key, *_ in REFERENCES}
    baselines = []
    for key, field, label, description in REFERENCES:
        vs = {}
        for side in sides:
            def pair(pick_model, pick_ref) -> dict[str, Any]:
                diffs = [world_mean(side, w, pick_model) - pick_ref(w) for w in paired]
                return {"model": round(sum(world_mean(side, w, pick_model) for w in paired) / len(paired), 6),
                        "reference": round(sum(pick_ref(w) for w in paired) / len(paired), 6),
                        "difference": round(sum(diffs) / len(diffs), 6), "difference_ci": _boot(diffs, rng)}
            vs[side] = {"realized": pair(lambda c: sum(c["parts"].values()), lambda w, key=key: sum(reference_world[w][key].values())),
                        "components": [{"key": k, "label": lab, "group": grp, "description": desc,
                                        **pair(lambda c, k=k: c["parts"][k], lambda w, k=k, key=key: reference_world[w][key][k])}
                                       for k, lab, grp, desc in COMPONENTS]}
        baselines.append({
            "key": key, "label": label, "description": description + " Scored against the same T-period bound, so its parts read like a model's.",
            "source": f"`{field}` in tables/cells.jsonl (one value per world, identical on every seed and both sides); "
                      "periods reconstructed from relationship._Solver on the committed world",
            "replay_check": {"worlds": len(paired), "mismatches": replay_mismatches,
                             "statement": "the reconstructed periods reproduce the family solver's period margins and the published reference value on every cell"},
            "vs": vs,
            "reference_parts": [{"world_seed": int(by_world["left"][w][0]["world_seed"]), "unit": w,
                                 "parts": {k: round(v, 6) for k, v in reference_world[w][key].items()}} for w in paired],
        })

    residuals = sides["left"]["residuals"] + sides["right"]["residuals"]
    row_residuals = sides["left"]["row_residuals"] + sides["right"]["row_residuals"]
    if max(abs(r) for r in residuals) > TOLERANCE or max(abs(r) for r in row_residuals) > TOLERANCE:
        raise ValueError("a cell's parts or contribution rows do not add up")
    sources = {bundle: hashlib.sha256((EVIDENCE / bundle / "publication_manifest.json").read_bytes()).hexdigest()
               for bundle in (comparison.left, comparison.right)}
    table = sorted(sides["left"]["rows"] + sides["right"]["rows"],
                   key=lambda r: (r["side"], r["unit"], r["replicate_index"], r["step_index"], KEYS.index(r["component"]), r["amount"]))
    cell_parts = [{k: c[k] for k in ("side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit", "stratum")}
                  | {"parts": {k: round(v, 6) for k, v in c["parts"].items()}}
                  for side in sides for c in sides[side]["cells"]]
    luck = {side: sides[side]["luck"] for side in sides}
    report = {
        "schema_version": "aeread.gap_decomposition/0.1",
        "family": "procurement_allocation", "world_kind": "repeated_sourcing",
        "title": "Why they differ",
        "left": comparison.left, "right": comparison.right,
        "left_model": _model(comparison.left), "right_model": _model(comparison.right), "right_label": "GLM",
        "endpoint": ("minus regret to the T-period bound: contribution_margin_usd minus upper_bound_usd (tables/cells.jsonl), "
                     "higher is better; the bound is one number per world on every seed and both sides, so the gap equals "
                     "the margin gap, and each part is measured against the bound's own plan for the same period"),
        "unit": "USD per world: cells averaged within their world, then worlds averaged",
        "unit_label": "world", "per_label": "world", "amount_label": "USD/world",
        "class_heading": "decision class (diagnostic, overlapping; amounts in margin dollars per world)",
        "direction": "higher", "claim_status": comparison.claim_status, "scope": comparison.scope,
        "winner_claim_allowed": False, "inferential_model_ranking_allowed": False,
        "paired_worlds": len(paired), "cells": {"left": len(sides["left"]["cells"]), "right": len(sides["right"]["cells"])},
        "excluded_cells": excluded,
        "bootstrap": {"seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS, "interval": "percentile_95", "unit": "world",
                      "stream": "one random.Random(seed): realized, then components in declared order, then class amounts in "
                                "declared order, then each baseline in declared order, left then right, realized then components"},
        "intervals": f"95% percentile intervals from a world-clustered bootstrap over the {len(paired)} paired worlds",
        "realized": realized,
        "components": components,
        "per_world": per_world,
        "accounting_check": {
            "max_abs_residual_per_cell": max(abs(r) for r in residuals),
            "statement": "each cell's parts sum to its published contribution_margin_usd minus upper_bound_usd (minus its published regret)",
            "max_abs_contribution_residual": max(abs(r) for r in row_residuals),
            "contribution_statement": "per cell, the contribution rows of each part sum to that cell's part"},
        "replay_check": {
            "periods": luck["left"]["periods"] + luck["right"]["periods"],
            "unparseable_steps_counted_as_attempted_type": {s: sides[s]["unparseable_steps_counted_as_attempted_type"] for s in sides},
            "counts_note": "published action_counts, counters and inquiries also count a malformed action as the type it attempted "
                           "(incident P-T-11); classes here count executed actions from the trajectory",
            "statement": "every published trajectory re-driven through the plugin reproduces every published period margin "
                         "(tables/cells.jsonl period_margins and tables/periods.jsonl), the bound and all three references"},
        "luck_check": {
            "left": luck["left"], "right": luck["right"],
            "statement": "no luck part: each award is scored on expected units at the supplier's true yield and on-time rate; "
                         "the delivery draw differed from the scored kits in drawn_differs of awarded_periods awarded periods "
                         "and entered no margin"},
        "unit_check": {
            "seeds_per_world": sorted({len(v) for s in sides for v in by_world[s].values()}),
            "statement": "each seed re-seals the world's delivery draws and its binomial sample noise (every world declares it), "
                         "so seeds change what the buyer reads; distinct_traces counts the distinct decision sequences (actions "
                         "without their free text) among a world's paired cells. The world is the unit either way.",
            "distinct_traces": {"left": sides["left"]["traces"], "right": sides["right"]["traces"]}},
        "outcome_view": {"left": sides["left"]["period_status"], "right": sides["right"]["period_status"],
                         "statement": "periods over all paired cells by how they ended: a feasible award, an award the "
                                      "environment rejected, a malformed action, never played, or an explicit defer"},
        "classes": classes,
        "baselines": baselines,
        "instances": sorted(sides["left"]["instances"] + sides["right"]["instances"],
                            key=lambda i: (i["class"], i["side"], i["unit"], i["replicate_index"], i["step_index"])),
        "cell_parts": sorted(cell_parts, key=lambda c: (c["side"], c["unit"], c["replicate_index"])),
        "contributions": {"table": f"tables/contributions_{comparison.suffix}.jsonl", "rows": len(table),
                          "fields": ["side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit", "step_index",
                                     "round_index", "phase_id", "seat_id", "action", "period", "component", "amount", "note"]},
        "source_manifest_sha256": sources,
    }
    return report, table


def _table_bytes(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _report_bytes(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------
# README
# --------------------------------------------------------------------------


def _ci(b: Mapping[str, Any], key: str = "difference") -> str:
    ci = b.get("difference_ci") if key == "difference" else b.get("amount_difference_ci")
    value = b[key]
    return f"{value:+.2f} ({ci[0]:+.2f} to {ci[1]:+.2f})" if ci else f"{value:+.2f}"


def _readme(reports: Mapping[str, tuple[dict[str, Any], list]]) -> str:
    name = lambda m: str(m).split("/")[-1]
    lines = [
        f"# {OUT.name}",
        "",
        "Why Gemini 3.8 Flash and GLM 5.3 Flash differ on the procurement repeated-sourcing worlds (four periods, "
        "loyalty discounts, retaliation markups, `interaction.periods`). Derived from the published bundles and the "
        "committed worlds re-sealed per seed, by `python -m aeread_families.procurement_allocation.relationship_gap`; "
        "`--check` regenerates these bytes. Descriptive: no winner, no ranking, and nothing here adds to the "
        "pre-registered confirmatory claims.",
        "",
        "The endpoint is minus regret to the T-period bound (`contribution_margin_usd - upper_bound_usd`), higher is "
        "better. The bound is one number per world, identical on every seed and both sides, so the gap is the margin "
        "gap; measuring each part against the bound's own plan for the same period makes a part read as a shortfall "
        "against the optimum and puts a lost period in one part instead of spreading it over revenue and cost. Every "
        "published trajectory is re-driven through the plugin, each period scored by `evaluate_award` on "
        "`relationship.period_case`, and the replay reproduces every published period margin, the bound and the three "
        "references. There is no luck part: awards are scored on expected units at true yield and on-time rates, and "
        "the delivery draw never enters a margin. The unit is the world; intervals are a world-clustered bootstrap.",
        "",
    ]
    for suffix, (report, _) in reports.items():
        left, right = name(report["left_model"]), name(report["right_model"])
        r = report["realized"]
        top = sorted(report["components"], key=lambda c: -abs(c["difference"]))[:2]
        view = report["outcome_view"]
        traces = {s: sum(report["unit_check"]["distinct_traces"][s].values()) for s in ("left", "right")}
        lines += [
            f"## {suffix}: `{report['left']}` against `{report['right']}`",
            "",
            f"Of the {r['difference']:+.2f} USD/world gap ({left} minus {right}), {top[0]['label']} carry "
            f"{top[0]['difference']:+.2f} and {top[1]['label']} {top[1]['difference']:+.2f}. Of {sum(view['right'].values())} "
            f"periods, {right} lost {view['right']['rejected']} to rejected awards and {view['right']['failed']} to malformed "
            f"actions, leaving {view['right']['unplayed']} unplayed; {left} lost {view['left']['rejected']}, "
            f"{view['left']['failed']} and {view['left']['unplayed']}.",
            "",
            f"{report['paired_worlds']} worlds, {report['cells']['left']} paired cells per side; claim status "
            f"`{report['claim_status']}`: {report['scope']}."
            + (f" Excluded: {len(report['excluded_cells'])} cell(s), listed in the report." if report["excluded_cells"] else ""),
            "",
            f"| part (USD per world, against the bound) | {left} | {right} | {left} minus {right} (95% world bootstrap) |",
            "|---|---|---|---|",
            f"| **minus regret (realized)** | {r['left']:.2f} | {r['right']:.2f} | {_ci(r)} |",
            *(f"| {c['label']} ({c['group']}) | {c['left']:.2f} | {c['right']:.2f} | {_ci(c)} |" for c in report["components"]),
            "",
            f"Largest per-cell residual {report['accounting_check']['max_abs_residual_per_cell']:.2g}; contribution rows "
            f"({report['contributions']['rows']}, `{report['contributions']['table']}`) sum to their cell's part within "
            f"{report['accounting_check']['max_abs_contribution_residual']:.2g}.",
            "",
            f"| class | {left} count | {right} count | {left} USD/world | {right} USD/world |",
            "|---|---|---|---|---|",
            *(f"| `{c['key']}`: {c['label']} | {c['left_count']} | {c['right_count']} | {c['left_amount_per_market']:.2f} | "
              f"{c['right_amount_per_market']:.2f} |" for c in report["classes"]),
            "",
            "Against the published references (each reconstructed period by period and split into the same parts), "
            "model minus reference, USD per world:",
            "",
            f"| part | {left} minus myopic | {right} minus myopic | {left} minus loyal | {right} minus loyal | {left} minus shopping | {right} minus shopping |",
            "|---|---|---|---|---|---|---|",
        ]
        by_key = {b["key"]: b for b in report["baselines"]}
        order = ("myopic", "loyal", "shopping")
        lines.append("| minus regret (realized) | " + " | ".join(f"{by_key[k]['vs'][s]['realized']['difference']:+.2f}" for k in order for s in ("left", "right")) + " |")
        for i, c in enumerate(report["components"]):
            lines.append(f"| {c['label']} | " + " | ".join(f"{by_key[k]['vs'][s]['components'][i]['difference']:+.2f}" for k in order for s in ("left", "right")) + " |")
        luck = report["luck_check"]
        lines += [
            "",
            f"Seeds: each re-seals the world's delivery draws and sample noise, so the buyer reads different samples, but "
            f"{left}'s decisions mostly repeat across them ({traces['left']} distinct decision sequences in "
            f"{report['cells']['left']} cells) where {right}'s rarely do ({traces['right']} in {report['cells']['right']}); "
            "the world is the unit either way.",
            "",
            f"Delivery draws differed from the scored kits in {luck['left']['drawn_differs']} of {luck['left']['awarded_periods']} "
            f"awarded {left} periods and {luck['right']['drawn_differs']} of {luck['right']['awarded_periods']} {right} periods, "
            "and moved no margin.",
            "",
        ]
    lines += [
        "The published `action_counts`, `counters` and `inquiries` of the source bundles also count a malformed action as "
        "the type it attempted (P-T-11); the classes here count executed actions from the trajectory. Two sentences of the "
        "source READMEs do not hold for these packs (P-T-12): the seeds reach the buyer from period one through the sample "
        "noise, and both packs are 12 rule-selected worlds.",
        "",
        "Every class instance and every cell's parts are in `reports/gap_decomposition_<pack>.json`; each contribution "
        "row names the step (`step_index`, `round_index`, `phase_id`, `seat_id`, and the `action` published there) that "
        "made it. Rows at a period's closing step also carry the bound's plan for that period, so the part is the "
        "buyer's decision against the optimum's.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def analyse_all() -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    return {c.suffix: analyse(c) for c in COMPARISONS}


def write() -> None:
    reports = analyse_all()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    for suffix, (report, table) in reports.items():
        (OUT / "reports" / f"gap_decomposition_{suffix}.json").write_text(_report_bytes(report), encoding="utf-8")
        (OUT / "tables" / f"contributions_{suffix}.jsonl").write_text(_table_bytes(table), encoding="utf-8")
    (OUT / "README.md").write_text(_readme(reports), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


def check() -> bool:
    reports = analyse_all()
    readme = OUT / "README.md"
    ok = readme.exists() and readme.read_text(encoding="utf-8") == _readme(reports)
    for suffix, (report, table) in reports.items():
        rp, tp = OUT / "reports" / f"gap_decomposition_{suffix}.json", OUT / "tables" / f"contributions_{suffix}.jsonl"
        ok = ok and rp.exists() and rp.read_text(encoding="utf-8") == _report_bytes(report)
        ok = ok and tp.exists() and tp.read_text(encoding="utf-8") == _table_bytes(table)
    print("relationship gap analysis regenerates to the committed bytes" if ok else "relationship gap analysis differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    if args.check:
        return 0 if check() else 1
    for suffix, (report, _) in analyse_all().items():
        print(suffix, json.dumps({"realized": report["realized"], "components": {c["key"]: c["difference"] for c in report["components"]}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
