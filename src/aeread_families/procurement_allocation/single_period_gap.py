"""Why a prompt treatment changes regret on the single-period procurement worlds.

A derived analysis in the Tier 1 sense: it reads only published bundles under
``evidence/`` and the cases committed under ``cases/procurement_allocation_v1``,
re-drives every published action trace through the deterministic environment
(each replay must reproduce the published margin, regret, feasibility and kit
count), and regenerates byte-identical output (``--check``).

**Comparisons.** Both are one model (GLM 5.3 Flash on Parasail) under two
prompts, paired cell by cell on the same world and the same inference seed:

- the primary report: the strategy scaffold (treatment) against the
  unscaffolded prompt (control) in
  ``procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2``,
  12 worlds x 2 presentation surfaces (labeled, opaque) x 3 seeds, 72 cells a
  side. Step locators come from the trajectory grain published for that bundle
  in ``procurement_allocation_trajectory_grains_v1``.
- ``_pre_award_check``: the pre-award check worksheet (treatment) against the
  strategy scaffold (control) in
  ``procurement_allocation_unified_regret_recovery_v2``, 6 worlds x 3 noisy
  sample seeds, 18 cells a side. No step-level log is published for it, so its
  contribution rows carry null step fields and name the action's ordinal in the
  published action trace instead.

**Endpoint.** Minus ``regret_to_upper_bound_usd`` (higher is better): the
cell's contribution margin less the world's full-information bound, both
published per row. It splits exactly into six parts:

- ``infeasible_award``: the whole endpoint of a submitted award that broke a
  gate (cash budget, minimum service, order step, MOQ, unverified sample). The
  scorer replaces such an award with the defer value less the information
  already bought, so the cell loses nearly the whole bound;
- ``no_award``: the whole endpoint of a cell that ended without an award (an
  explicit defer, the action budget running out, or an unparseable action);
- for feasible awards, the ten additive term gaps of
  ``regret_decomposition.decompose_feasible_award`` against the
  full-information plan, signed as endpoint and grouped four ways:
  ``kits_short`` (revenue and shortfall penalty), ``landed_cost`` (purchase,
  shipping, duty), ``terms_and_returns`` (working capital, return freight,
  refund financing, lost refund recovery) and ``information_spend``.

**Unit.** In the confirmatory worlds the environment never reads the inference
seed: the three seeds of a world and surface replay one case digest, and only
the model's sampling differs. The world is the unit and no interval is
reported. In the recovery worlds each seed also binds the sample-noise draw,
so seeds are different cases of one world, and a world-clustered bootstrap is
reported.

A treatment that turns a rejected award into a feasible one moves that cell's
loss from ``infeasible_award`` into the feasible-award parts, so each report
also groups the pairs by how each side ended (``transitions``); those groups
add up to the realized gap net of what a converted cell still loses.

**Classes** (diagnostic, overlapping, not parts of the sum) are the published
per-row violation types and an explicit defer, plus the reason a
minimum-service violation happened, recovered from the replay: a
bill-of-materials component left unbought, a line that could no longer arrive
by the deadline (located at the step that used up the slack), or every line in
place but too few expected good units.

    python -m aeread_families.procurement_allocation.single_period_gap --write
    python -m aeread_families.procurement_allocation.single_period_gap --check
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.task.scheduler import ActionEnvelope, ParseResult

from . import regret_decomposition as rd
from .environment import ProcurementAllocationPlugin, evaluate_award
from .runner import load_case

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence"
OUT = EVIDENCE / "procurement_allocation" / "procurement_allocation_single_period_gap"
CONFIRMATORY = "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2"
GRAINS = "procurement_allocation/procurement_allocation_trajectory_grains_v1"
DECOMPOSITION = "procurement_allocation_glm_regret_decomposition_v1"
RECOVERY = "procurement_allocation/procurement_allocation_unified_regret_recovery_v2"
RECOVERY_CASES = ROOT / "cases" / "procurement_allocation_v1" / "continuous_candidates_v2" / "opaque"
MODEL = "z-ai/glm-5.3-flash"
BOOTSTRAP_SEED = 20260925
BOOTSTRAP_DRAWS = 10000
TOLERANCE = 1e-6

COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("infeasible_award", "award rejected at a gate", "procedure",
     "A submitted award that broke a gate (cash budget, minimum service, order step, MOQ, unverified sample) is scored "
     "at the defer value less the information already bought; the cell's whole distance to the bound lands here."),
    ("no_award", "no award: deferred, out of actions, or unparseable", "procedure",
     "The episode ended without an award: an explicit defer, the action budget running out, or an action the "
     "environment could not parse. Scored at the defer value less the information bought."),
    ("kits_short", "kits short of the full-information plan", "outcome",
     "Feasible awards: revenue lost and shortfall penalty added by completing fewer expected kits than the plan."),
    ("landed_cost", "landed price above the plan", "cost",
     "Feasible awards: purchase, shipping and duty above the plan's."),
    ("terms_and_returns", "payment terms and returns", "cost",
     "Feasible awards: working capital, return freight and refund financing above the plan's, and expected refund "
     "recovery below it."),
    ("information_spend", "information bought beyond the plan's", "cost",
     "Feasible awards: quotes, samples, counter-offers and inquiries above what the plan itself buys."),
)
KEYS = tuple(key for key, *_ in COMPONENTS)
TERM_GROUPS: dict[str, tuple[str, ...]] = {
    "kits_short": ("revenue_shortfall", "shortfall_penalty_excess"),
    "landed_cost": ("purchase_cost_excess", "shipping_cost_excess", "duty_cost_excess"),
    "terms_and_returns": ("working_capital_cost_excess", "return_freight_cost_excess",
                          "refund_financing_cost_excess", "recovery_shortfall"),
    "information_spend": ("information_cost_excess",),
}
if sorted(t for terms in TERM_GROUPS.values() for t in terms) != sorted(rd.REGRET_TERMS):
    raise ValueError("the term groups must cover every regret term exactly once")

_VIOLATION = "published violation"
_CAUSE = "why minimum service failed"
_AMOUNT = "regret to the bound of the cells carrying it, USD per world (overlapping; not parts of the sum)"
CLASSES: dict[str, dict[str, str]] = {
    "cash_budget_exceeded": {"group": _VIOLATION, "label": "the award's cash spend (goods, freight, duty, information) exceeds the budget"},
    "minimum_service_not_met": {"group": _VIOLATION, "label": "the award completes fewer expected kits than the minimum service level"},
    "sample_not_verified": {"group": _VIOLATION, "label": "an awarded supplier's sample was never verified, so its units count for nothing"},
    "invalid_order_step": {"group": _VIOLATION, "label": "an awarded quantity is off the supplier's order step"},
    "below_moq": {"group": _VIOLATION, "label": "an awarded quantity is below the supplier's minimum order"},
    "over_capacity": {"group": _VIOLATION, "label": "an awarded quantity is above the supplier's capacity"},
    "wrong_variant": {"group": _VIOLATION, "label": "an awarded offer is not the required variant"},
    "expired_offer": {"group": _VIOLATION, "label": "an awarded offer had expired"},
    "interaction_budget_exhausted": {"group": _VIOLATION, "label": "the action budget ran out with no award or defer"},
    "unparseable_action": {"group": _VIOLATION, "label": "an action could not be parsed, which ends the episode"},
    "deferred": {"group": "ending", "label": "deferred instead of awarding, forgoing the bound (a choice, not a violation)"},
    "component_not_awarded": {"group": _CAUSE, "label": "the award leaves a bill-of-materials component with no supplier"},
    "arrives_after_deadline": {"group": _CAUSE, "label": "an awarded line can no longer arrive by the deadline (located at the step that used up the slack)"},
    "quantity_short": {"group": _CAUSE, "label": "every component awarded, verified and on time, but too few expected good units"},
}
_GATE = {"cash_budget_exceeded": "the cash budget", "minimum_service_not_met": "minimum service",
         "sample_not_verified": "sample verification", "invalid_order_step": "an order step", "below_moq": "a minimum order",
         "over_capacity": "a supplier's capacity", "wrong_variant": "the required variant", "expired_offer": "an offer's expiry"}
_ADDRESSED = ("inquire", "request_quote", "request_sample", "counter_offer")
_VERB = {"inquire": "an inquiry to", "request_quote": "a quote from", "request_sample": "a sample from",
         "counter_offer": "a counter-offer to", "check_award": "a pre-award check", "submit_award": "the award",
         "defer": "the defer", "unparseable": "an unparseable action"}


@dataclass(frozen=True)
class Comparison:
    suffix: str
    title: str
    campaign_id: str
    left_label: str
    right_label: str
    left_prompt: str
    right_prompt: str
    world_kind: str


PRIMARY = Comparison(
    suffix="", title="Why the strategy scaffold changes regret", campaign_id=CONFIRMATORY,
    left_label="strategy scaffold", right_label="unscaffolded",
    left_prompt="procurement_allocation_strategy_scaffold_v3", right_prompt="procurement_allocation_prompt_v1",
    world_kind="single_period_curated_confirmatory")
PRE_AWARD = Comparison(
    suffix="pre_award_check", title="Why the pre-award check changes regret on noisy-sample worlds",
    campaign_id="procurement_allocation_unified_regret_recovery_v2",
    left_label="pre-award check", right_label="strategy scaffold",
    left_prompt="procurement_allocation_pre_award_check_v1 + binomial sample notice",
    right_prompt="procurement_allocation_strategy_scaffold_v3 + binomial sample notice",
    world_kind="single_period_noisy_sample_confirmatory")


# --- replay -------------------------------------------------------------------------------------------------------

def replay_steps(family_case: Mapping[str, Any], action_trace: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``regret_decomposition.replay_action_trace``, keeping the clock and the information bill after every action."""
    plugin = ProcurementAllocationPlugin()
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)
    steps: list[dict[str, Any]] = []
    for entry in action_trace:
        if state["done"]:
            raise rd.ReplayMismatchError("action trace continues after termination")
        if entry.get("status") != "succeeded":
            envelope = ActionEnvelope(seat_id="buyer", valid=False, action=None,
                                      parse=ParseResult.failure("replayed_agent_action_failure"), legality=None)
            name = "unparseable"
        else:
            action = rd._trace_action(family_case, entry)
            legality = plugin.legal(family_case, state, "buyer", phase, action)
            envelope = ActionEnvelope(seat_id="buyer", valid=legality.legal, action=action,
                                      parse=ParseResult.success(action), legality=legality)
            name = entry["action"]
        before = state
        state = plugin.step(family_case, state, phase, {"buyer": envelope}).state
        # a supplier is part of the decision only for the actions addressed to one (a stray field on an award is ignored)
        supplier = entry.get("supplier_id") if name in _ADDRESSED else None
        steps.append({"ordinal": int(entry["ordinal"]), "action": name, "supplier_id": supplier,
                      "days": int(state["elapsed_days"]), "days_added": int(state["elapsed_days"]) - int(before["elapsed_days"]),
                      "cost_added": float(state["information_cost_usd"]) - float(before["information_cost_usd"])})
    if [s["ordinal"] for s in steps] != list(range(1, len(steps) + 1)):
        raise rd.ReplayMismatchError("action trace ordinals are not 1..n")
    terminal = plugin.terminal(family_case, state)
    if terminal is None:
        raise rd.ReplayMismatchError("action trace did not reach a terminal state")
    outcome = plugin.outcome(family_case, terminal)
    evaluation = None
    if terminal["reason"] == "submitted":
        evaluation = evaluate_award(family_case, award_lines=terminal["award_lines"], offers=terminal["offers"],
                                       quality_evidence=terminal["quality_evidence"], elapsed_days=terminal["elapsed_days"],
                                       information_cost_usd=terminal["information_cost_usd"])
    return {"terminal": terminal, "outcome": outcome, "evaluation": evaluation, "steps": steps}


def _check_replay(row: Mapping[str, Any], outcome: Mapping[str, Any]) -> None:
    checks = {"feasible": outcome["feasible"] == row["feasible"],
              "contribution_margin_usd": abs(outcome["contribution_margin_usd"] - row["contribution_margin_usd"]) <= TOLERANCE,
              "regret_to_upper_bound_usd": abs(outcome["regret_to_upper_bound_usd"] - row["regret_to_upper_bound_usd"]) <= TOLERANCE,
              "upper_bound_usd": abs(outcome["upper_bound_usd"] - row["upper_bound_usd"]) <= TOLERANCE,
              "completed_kits": outcome["completed_kits"] == row["completed_kits"],
              "termination_reason": outcome["termination_reason"] == row["termination_reason"],
              # a replayed parse failure cannot know the published failure code, so only its count is compared
              "violations": (len(outcome["violations"]) == len(row["violations"]) == 1
                             if row["termination_reason"] == "invalid_action"
                             else list(outcome["violations"]) == list(row["violations"]))}
    if not all(checks.values()):
        raise rd.ReplayMismatchError(f"{row['case_id']}/{row['inference_seed']}: {sorted(k for k, ok in checks.items() if not ok)}")


# --- one cell -----------------------------------------------------------------------------------------------------

def category_of(outcome: Mapping[str, Any]) -> str:
    if outcome["termination_reason"] == "submitted":
        return "feasible_award" if outcome["feasible"] else "infeasible_award"
    return "no_award"


def split_endpoint(category: str, endpoint: float, terms: Mapping[str, float] | None) -> dict[str, float]:
    """The six parts of one cell's minus-regret."""
    parts = {key: 0.0 for key in KEYS}
    if category in ("infeasible_award", "no_award"):
        parts[category] = float(endpoint)
        return parts
    if category != "feasible_award" or terms is None:
        raise ValueError(f"unknown category {category!r} or a feasible award without terms")
    for group, members in TERM_GROUPS.items():
        parts[group] = -math.fsum(float(terms[m]) for m in members)
    return parts


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _named(name: str, supplier: str | None) -> str:
    return f"{_VERB.get(name, name)} {supplier}" if supplier else _VERB.get(name, name)


def cell_contributions(cell: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per decision per part: ``ordinal`` is the action's 1-based place in the published action trace."""
    category, parts, steps = cell["category"], cell["parts"], cell["steps"]
    last = steps[-1]
    info = math.fsum(s["cost_added"] for s in steps)
    if category == "infeasible_award":
        return [{"ordinal": last["ordinal"], "action": last["action"], "component": "infeasible_award", "amount": parts["infeasible_award"],
                 "note": (f"submitted an award that broke the gate on {' and '.join(cell['violation_keys'])}; it is scored at the defer value less "
                          f"{_money(info)} of information, {_money(-parts['infeasible_award'])} below the bound")}]
    if category == "no_award":
        reason = cell["termination_reason"]
        if reason == "deferred":
            what = "deferred instead of awarding"
        elif reason == "interaction_budget_exhausted":
            what = f"spent the last of {cell['max_actions']} actions on {_named(last['action'], last['supplier_id'])} with no award"
        else:
            what = f"sent an action that could not be parsed ({cell['failure_code']}), which ends the episode"
        return [{"ordinal": last["ordinal"], "action": last["action"], "component": "no_award", "amount": parts["no_award"],
                 "note": f"{what}; scored at the defer value less {_money(info)} of information, {_money(-parts['no_award'])} below the bound"}]
    award = last
    if award["action"] != "submit_award":
        raise ValueError("a feasible award must end on submit_award")
    model, plan = cell["evaluation"], cell["plan_evaluation"]
    rows = []
    if abs(parts["kits_short"]) > 1e-9:
        rows.append({"component": "kits_short", "amount": parts["kits_short"],
                     "note": f"the award completes {model['completed_kits']} expected kits against the plan's {plan['completed_kits']}"})
    if abs(parts["landed_cost"]) > 1e-9:
        landed = lambda e: math.fsum(float(e[f]) for f in ("purchase_cost_usd", "shipping_cost_usd", "duty_cost_usd"))
        rows.append({"component": "landed_cost", "amount": parts["landed_cost"],
                     "note": f"purchase, shipping and duty {_money(landed(model))} against the plan's {_money(landed(plan))}"})
    if abs(parts["terms_and_returns"]) > 1e-9:
        net = lambda e: (float(e["working_capital_cost_usd"]) + float(e["return_freight_cost_usd"])
                         + float(e["refund_financing_cost_usd"]) - float(e["expected_recovery_usd"]))
        rows.append({"component": "terms_and_returns", "amount": parts["terms_and_returns"],
                     "note": (f"working capital, return freight and refund financing net of expected refunds "
                              f"{_money(net(model))} against the plan's {_money(net(plan))}")})
    rows = [{"ordinal": award["ordinal"], "action": "submit_award", **r} for r in rows]
    for step in steps:
        if step["cost_added"] > 1e-12:
            rows.append({"ordinal": step["ordinal"], "action": step["action"], "component": "information_spend", "amount": -step["cost_added"],
                         "note": f"{_named(step['action'], step['supplier_id'])} cost {_money(step['cost_added'])}"})
    plan_info = float(plan["information_cost_usd"])
    if plan_info > 1e-12:
        rows.append({"ordinal": award["ordinal"], "action": "submit_award", "component": "information_spend", "amount": plan_info,
                     "note": f"the plan itself buys {_money(plan_info)} of quotes, samples and counters; only spend above that counts"})
    return rows


def _violation_key(violation: str) -> tuple[str, str | None]:
    supplier, _, kind = violation.rpartition(".")
    return (kind, supplier or None)


def classify(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Diagnostic classes of one cell, each at the step that decided it (``ordinal``)."""
    found: list[dict[str, Any]] = []
    award, last = facts.get("award_ordinal"), facts["last_ordinal"]
    lines = facts.get("lines") or []
    by_supplier = {line["supplier_id"]: line for line in lines}
    grouped: dict[str, list[str | None]] = collections.defaultdict(list)
    for violation in facts["violations"]:
        kind, supplier = _violation_key(violation)
        if facts["category"] == "no_award":
            kind = "interaction_budget_exhausted" if facts["termination_reason"] == "interaction_budget_exhausted" else "unparseable_action"
        if kind not in CLASSES or CLASSES[kind]["group"] != _VIOLATION:
            raise ValueError(f"unclassified violation {violation!r}")
        grouped[kind].append(supplier)
    for kind, suppliers in grouped.items():
        if kind == "cash_budget_exceeded":
            note = f"the award's cash spend {_money(facts['cash_spend'])} exceeds the {_money(facts['cash_budget'])} budget"
        elif kind == "minimum_service_not_met":
            note = f"the award completes {facts['completed_kits']} expected kits, under the minimum of {facts['minimum_service_kits']}"
        elif kind == "interaction_budget_exhausted":
            note = f"spent the last of {facts['max_actions']} actions on {_named(facts['last_action'], facts['last_supplier'])} with no award or defer"
        elif kind == "unparseable_action":
            note = f"the action could not be parsed ({facts['failure_code']}), which ends the episode with no award"
        else:
            described = []
            for supplier in suppliers:
                line = by_supplier[supplier]
                if kind == "sample_not_verified":
                    described.append(f"{line['quantity']} units from {supplier} without a verified sample")
                elif kind == "invalid_order_step":
                    described.append(f"{line['quantity']} from {supplier}, which sells {line['moq']} and up in steps of {line['order_step']}")
                elif kind == "below_moq":
                    described.append(f"{line['quantity']} from {supplier}, below its minimum order of {line['moq']}")
                elif kind == "over_capacity":
                    described.append(f"{line['quantity']} from {supplier}, above its capacity of {line['capacity']}")
                else:
                    described.append(f"{supplier}'s offer ({kind.replace('_', ' ')})")
            note = "awarded " + "; ".join(described)
        found.append({"class": kind, "ordinal": last if facts["category"] == "no_award" else award, "note": note})
    if facts["termination_reason"] == "deferred":
        found.append({"class": "deferred", "ordinal": last, "note": "deferred instead of awarding, so the cell earns the defer value less the information bought"})
    if "minimum_service_not_met" in grouped:
        missing = [c for c in facts["bom"] if c not in {line["component"] for line in lines}]
        late = [line for line in lines if line["late"]]
        if missing:
            found.append({"class": "component_not_awarded", "ordinal": award,
                          "note": f"the award buys no {', '.join(missing)}, so no kit can be completed"})
        if late:
            first = min(late, key=lambda line: line["deciding_ordinal"])
            step = facts["steps"][first["deciding_ordinal"] - 1]
            if first["deciding_ordinal"] == award:
                note = (f"awarded {first['supplier_id']}, whose {first['lead_time_days']}-day lead time cannot meet the "
                        f"day-{facts['deadline_days']} deadline from day {facts['elapsed_days']}")
            else:
                note = (f"{_named(step['action'], step['supplier_id'])} took the clock to day {step['days']}; "
                        f"{first['supplier_id']}'s {first['lead_time_days']}-day lead time then misses the "
                        f"day-{facts['deadline_days']} deadline, and the award still used it")
            found.append({"class": "arrives_after_deadline", "ordinal": first["deciding_ordinal"], "note": note})
        if not missing and not late and not any(not line["verified"] for line in lines):
            bought = ", ".join(f"{line['quantity']} {line['component']}" for line in lines)
            found.append({"class": "quantity_short", "ordinal": award,
                          "note": (f"bought {bought}, all verified and on time, for {facts['completed_kits']} expected good kits "
                                   f"against the minimum of {facts['minimum_service_kits']}")})
    return found


def _facts(family_case: Mapping[str, Any], replay: Mapping[str, Any], category: str, violations: Sequence[str]) -> dict[str, Any]:
    terminal, outcome, steps = replay["terminal"], replay["outcome"], replay["steps"]
    objective = family_case["objective"]
    facts: dict[str, Any] = {
        "category": category, "termination_reason": outcome["termination_reason"],
        "failure_code": violations[0] if outcome["termination_reason"] == "invalid_action" else None,
        "violations": list(violations), "steps": steps, "last_ordinal": steps[-1]["ordinal"],
        "last_action": steps[-1]["action"], "last_supplier": steps[-1]["supplier_id"],
        "max_actions": int(family_case["interaction"]["max_actions"]), "bom": list(objective["bom"]),
        "deadline_days": int(objective["deadline_days"]), "elapsed_days": int(terminal["elapsed_days"]),
        "completed_kits": int(outcome["completed_kits"]), "minimum_service_kits": int(objective["minimum_service_kits"]),
        "cash_spend": float(outcome["cash_spend_usd"]), "cash_budget": float(objective["cash_budget_usd"]),
    }
    if terminal["reason"] != "submitted":
        return facts
    facts["award_ordinal"] = steps[-1]["ordinal"]
    lines = []
    for line in terminal["award_lines"]:
        offer = terminal["offers"][line["offer_id"]]
        evidence = terminal["quality_evidence"].get(offer["supplier_id"]) or {}
        slack = int(objective["deadline_days"]) - int(offer["lead_time_days"])
        late = int(terminal["elapsed_days"]) > slack
        deciding = None
        if late:
            deciding = facts["award_ordinal"] if slack < 0 else next(s["ordinal"] for s in steps if s["days"] > slack)
        lines.append({"supplier_id": offer["supplier_id"], "component": offer["component"], "quantity": int(line["quantity"]),
                      "moq": offer["moq"], "order_step": offer["order_step"], "capacity": offer["capacity"],
                      "lead_time_days": int(offer["lead_time_days"]), "late": late, "deciding_ordinal": deciding,
                      "verified": evidence.get("evidence_status") == "verified_sample"
                      and evidence.get("variant_id") == offer["variant_id"]})
    facts["lines"] = lines
    return facts


def analyse_cell(family_case: Mapping[str, Any], row: Mapping[str, Any], oracle: Mapping[str, Any] | None) -> dict[str, Any]:
    """Replay one published row, split its endpoint, trace every part to its steps, and type its failures."""
    replay = replay_steps(family_case, row["action_trace"])
    _check_replay(row, replay["outcome"])
    category = category_of(replay["outcome"])
    terms = None
    if category == "feasible_award":
        decomposed = rd.decompose_feasible_award(family_case, replay, oracle=oracle)
        if abs(decomposed["identity_residual_usd"]) > TOLERANCE:
            raise ValueError(f"regret identity failed for {row['case_id']}/{row['inference_seed']}")
        terms = decomposed["terms"]
    endpoint = -float(row["regret_to_upper_bound_usd"])
    parts = split_endpoint(category, endpoint, terms)
    context = {"category": category, "parts": parts, "steps": replay["steps"], "evaluation": replay["evaluation"],
               "plan_evaluation": (oracle or {}).get("evaluation"), "termination_reason": replay["outcome"]["termination_reason"],
               "failure_code": row["violations"][0] if row["termination_reason"] == "invalid_action" else None,
               "max_actions": int(family_case["interaction"]["max_actions"]),
               "violation_keys": [_GATE.get(k, k) for k in dict.fromkeys(_violation_key(v)[0] for v in row["violations"])]}
    contributions = cell_contributions(context)
    sums = collections.Counter()
    for item in contributions:
        sums[item["component"]] += item["amount"]
    return {"category": category, "terms": terms, "parts": parts, "endpoint": endpoint,
            "residual": endpoint - math.fsum(parts.values()),
            "unexplained": max(abs(parts[k] - sums[k]) for k in KEYS),
            "contributions": contributions, "classes": classify(_facts(family_case, replay, category, row["violations"])),
            "steps": replay["steps"]}


# --- published sources --------------------------------------------------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _grain(bundle: str) -> dict[str, list[dict[str, Any]]]:
    """Per receipt, its published steps with ``round_index`` = 0-based count of first-phase starts up to the step."""
    path = EVIDENCE / GRAINS / "trajectories" / f"{bundle}.jsonl"
    by: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by[row["source_receipt_sha256"]].append(row)
    out = {}
    for receipt, steps in by.items():
        steps.sort(key=lambda r: r["step_index"])
        first, current, seen = steps[0]["phase_id"], -1, set()
        located = []
        for row in steps:
            if row["phase_id"] == first and row["phase_instance_id"] not in seen:
                current += 1
            seen.add(row["phase_instance_id"])
            action = row["action"] if isinstance(row["action"], dict) else {"action": "unparseable"}
            located.append({"step_index": int(row["step_index"]), "round_index": current, "phase_id": row["phase_id"],
                            "seat_id": row["seat_id"], "action": action["action"], "supplier_id": action.get("supplier_id"),
                            "valid": (row.get("outcome") or {}).get("valid")})
        out[receipt] = located
    return out


def _confirmatory_cells() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = EVIDENCE / CONFIRMATORY
    plan = json.loads((root / "tables" / "frozen_plan.json").read_text(encoding="utf-8"))
    world_seed = {pair["slug"]: int(pair["world_seed"]) for pair in plan["world_pairs"]}
    seeds = [int(s) for s in plan["inference_seeds"]]
    grain = _grain(CONFIRMATORY)
    published = json.loads((EVIDENCE / DECOMPOSITION / "reports" / "regret_decomposition.json").read_text(encoding="utf-8"))
    published_terms = {r["result_sha256"]: r for r in published["rows"]}
    oracles: dict[str, dict[str, Any]] = {}
    cells, matched, stray = [], 0, 0
    arms = {"labeled_treatment": "left", "opaque_treatment": "left", "labeled_control": "right", "opaque_control": "right"}
    for arm, side in arms.items():
        report, _ = rd.verified_bundle_report(root / "reports" / f"{arm}.json")
        if report["campaign_id"] != f"{CONFIRMATORY}.{arm}":
            raise ValueError(f"campaign identity mismatch for {arm}")
        for row in report["rows"]:
            if row["status"] != "completed":
                raise ValueError(f"{arm}: a row that did not complete")
            case_path = rd.case_path_for_id(row["case_id"], repository_root=ROOT)
            if load_case(case_path).content_sha256 != row["case_content_sha256"]:
                raise ValueError(f"case digest drift for {row['case_id']}")
            family_case = json.loads(case_path.read_text(encoding="utf-8"))["payload"]
            slug = row["case_id"].split(".")[-1]
            stray += sum(1 for e in row["action_trace"] if e["action"] not in _ADDRESSED and "supplier_id" in e)
            if slug not in oracles:
                oracles[slug] = rd.oracle_evaluation(family_case)
            result = analyse_cell(family_case, row, oracles[slug])
            reference = published_terms.get(row["result_sha256"])
            if reference is None or reference["regret_category"] != _published_category(row):
                raise ValueError(f"{row['case_id']}: not in the published regret decomposition")
            if result["category"] == "feasible_award":
                if reference["terms"] != result["terms"]:
                    raise ValueError(f"{row['case_id']}: replayed terms differ from the published decomposition")
                matched += 1
            cells.append({"side": side, "campaign_id": CONFIRMATORY, "arm": arm, "receipt_sha256": row["receipt_sha256"],
                          "world_seed": world_seed[slug], "unit": slug, "stratum": arm.split("_")[0],
                          "replicate_index": seeds.index(int(row["inference_seed"])), "inference_seed": int(row["inference_seed"]),
                          "case_content_sha256": row["case_content_sha256"], "regret": float(row["regret_to_upper_bound_usd"]),
                          "termination_reason": row["termination_reason"], "grain": grain[row["receipt_sha256"]], **result})
    effects = json.loads((root / "reports" / "confirmatory_effects.json").read_text(encoding="utf-8"))
    checks = {"published_decomposition_terms_matched": matched, "published_effects": effects["effects"],
              "stray_supplier_ids": stray}
    return cells, checks


def _published_category(row: Mapping[str, Any]) -> str:
    if row["feasible"] and row["decision"] == "award":
        return "feasible_award"
    if row["feasible"] and row["decision"] == "defer":
        return "feasible_defer"
    return "infeasible_award" if row["termination_reason"] == "submitted" else str(row["termination_reason"])


def _recovery_cells() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from .continuous_campaign import _digest, economic_world_id
    from .continuous_recovery import episode_case

    root = EVIDENCE / RECOVERY
    manifest = json.loads((root / "publication_manifest.json").read_text(encoding="utf-8"))
    if manifest["manifest_sha256"] != _digest({k: v for k, v in manifest.items() if k != "manifest_sha256"}):
        raise ValueError("recovery manifest digest mismatch")
    if manifest["artifacts"]["reports/confirmatory.json"] != _sha(root / "reports" / "confirmatory.json"):
        raise ValueError("recovery report bytes differ from the manifest")
    report = json.loads((root / "reports" / "confirmatory.json").read_text(encoding="utf-8"))
    if report["artifact_sha256"] != _digest({k: v for k, v in report.items() if k != "artifact_sha256"}):
        raise ValueError("recovery report digest mismatch")
    contract = json.loads((root / "tables" / "execution_contract.json").read_text(encoding="utf-8"))
    seeds = [int(s) for s in contract["environment_and_inference_seeds"]]
    worlds = {}
    for path in sorted(RECOVERY_CASES.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        worlds[economic_world_id(case)] = case
    if set(worlds) != set(contract["world_ids"]):
        raise ValueError("the committed continuous worlds are not the recovery contract's worlds")
    oracles: dict[tuple[str, int], dict[str, Any]] = {}
    cells = []
    for row in report["rows"]:
        if row["status"] != "completed" or row["environment_seed"] != row["inference_seed"]:
            raise ValueError("a recovery row did not complete or its seeds differ")
        world = worlds[row["world_id"]]
        case = episode_case(world, int(row["environment_seed"]))
        if case["content_sha256"] != row["case_content_sha256"]:
            raise ValueError(f"episode case digest drift for {row['case_id']}")
        key = (row["world_id"], int(row["environment_seed"]))
        if key not in oracles:
            oracles[key] = rd.oracle_evaluation(case["payload"])
        result = analyse_cell(case["payload"], row, oracles[key])
        cells.append({"side": "left" if row["arm"] == "treatment" else "right", "campaign_id": PRE_AWARD.campaign_id,
                      "arm": row["arm"], "receipt_sha256": row["receipt_sha256"], "world_seed": int(world["world_seed"]),
                      "unit": world["case_id"].split(".")[-1], "stratum": None,
                      "replicate_index": seeds.index(int(row["environment_seed"])), "inference_seed": int(row["inference_seed"]),
                      "environment_seed": int(row["environment_seed"]), "case_content_sha256": row["case_content_sha256"],
                      "world_id": row["world_id"], "regret": float(row["regret_to_upper_bound_usd"]),
                      "termination_reason": row["termination_reason"], "grain": None, **result})
    return cells, {"published_summary": report["summary"]}


# --- aggregation --------------------------------------------------------------------------------------------------

def _boot(values: Sequence[float], rng: random.Random) -> list[float] | None:
    if len(values) < 2:
        return None
    means = sorted(math.fsum(rng.choice(values) for _ in values) / len(values) for _ in range(BOOTSTRAP_DRAWS))
    return [means[int(0.025 * BOOTSTRAP_DRAWS)], means[min(BOOTSTRAP_DRAWS - 1, int(0.975 * BOOTSTRAP_DRAWS))]]


def _locate(cell: Mapping[str, Any], ordinal: int) -> dict[str, Any]:
    """The published step behind an action ordinal, checked to hold the same action on the same supplier; step fields
    are null when no step log is published."""
    ours = cell["steps"][ordinal - 1]
    what = {"action": ours["action"], "supplier_id": ours["supplier_id"]}
    if cell["grain"] is None:
        return {"step_index": None, "round_index": None, "phase_id": None, "seat_id": None, "action_ordinal": ordinal, **what}
    step = cell["grain"][ordinal - 1]
    if step["step_index"] != ordinal - 1 or (step["action"], step["supplier_id"]) != (ours["action"], ours["supplier_id"]):
        raise ValueError(f"{cell['receipt_sha256']}: step {ordinal - 1} is {step['action']} {step['supplier_id']}, not {what}")
    return {"step_index": step["step_index"], "round_index": step["round_index"], "phase_id": step["phase_id"],
            "seat_id": step["seat_id"], **what}


def _pairing(cells: Sequence[Mapping[str, Any]], seeds_repeat: bool) -> None:
    keys = {side: sorted((c["unit"], c["stratum"] or "", c["inference_seed"]) for c in cells if c["side"] == side) for side in ("left", "right")}
    if keys["left"] != keys["right"] or len(set(keys["left"])) != len(keys["left"]):
        raise ValueError("the two sides are not paired one to one on world, stratum and seed")
    digests: dict[tuple, set[str]] = collections.defaultdict(set)
    for c in cells:
        digests[(c["unit"], c["stratum"])].add(c["case_content_sha256"])
    repeats = all(len(d) == 1 for d in digests.values())
    if repeats != seeds_repeat:
        raise ValueError(f"seed-repeat check: expected repeats={seeds_repeat}, found {repeats}")


def _report(spec: Comparison, cells: list[dict[str, Any]], checks: Mapping[str, Any], seeds_repeat: bool,
            sources: Mapping[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _pairing(cells, seeds_repeat)
    units = sorted({c["unit"] for c in cells})
    by: dict[tuple[str, str], list[Mapping[str, Any]]] = collections.defaultdict(list)
    for c in cells:
        by[(c["side"], c["unit"])].append(c)
    rng = random.Random(BOOTSTRAP_SEED)

    def world_mean(side: str, unit: str, pick, stratum: str | None = None) -> float:
        chosen = [c for c in by[(side, unit)] if stratum is None or c["stratum"] == stratum]
        return math.fsum(pick(c) for c in chosen) / len(chosen)

    def block(pick, stratum: str | None = None) -> dict[str, Any]:
        left = [world_mean("left", u, pick, stratum) for u in units]
        right = [world_mean("right", u, pick, stratum) for u in units]
        diffs = [a - b for a, b in zip(left, right)]
        return {"left": math.fsum(left) / len(units), "right": math.fsum(right) / len(units), "difference": math.fsum(diffs) / len(units),
                "difference_ci": None if seeds_repeat else _boot(diffs, rng)}

    realized = block(lambda c: c["endpoint"])
    components = [{"key": k, "label": lab, "group": g, "description": d, **block(lambda c, k=k: c["parts"][k])}
                  for k, lab, g, d in COMPONENTS]
    has = lambda c, key: any(i["class"] == key for i in c["classes"])
    classes = []
    for key, meta in CLASSES.items():
        amounts = block(lambda c, key=key: c["regret"] if has(c, key) else 0.0)
        classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": _AMOUNT,
                        "left_count": sum(has(c, key) for c in cells if c["side"] == "left"),
                        "right_count": sum(has(c, key) for c in cells if c["side"] == "right"),
                        "left_amount_per_market": amounts["left"], "right_amount_per_market": amounts["right"],
                        "amount_difference": amounts["difference"], "amount_difference_ci": amounts["difference_ci"]})
    instances, table = [], []
    for c in cells:
        where = {"side": c["side"], "campaign_id": c["campaign_id"], "receipt_sha256": c["receipt_sha256"],
                 "world_seed": c["world_seed"], "replicate_index": c["replicate_index"], "unit": c["unit"], "arm": c["arm"]}
        for item in c["contributions"]:
            located = _locate(c, item["ordinal"])
            if located["action"] != item["action"]:
                raise ValueError(f"{c['receipt_sha256']}: a {item['component']} row names {item['action']} at a {located['action']} step")
            table.append({**where, **located, "component": item["component"], "amount": round(item["amount"], 6), "note": item["note"]})
        for item in c["classes"]:
            instances.append({**where, **_locate(c, item["ordinal"]), "class": item["class"],
                              "amount": round(c["regret"], 4), "note": item["note"]})
    categories = {side: dict(sorted(collections.Counter(
        c["category"] if c["category"] != "no_award" else c["termination_reason"] for c in cells if c["side"] == side).items()))
        for side in ("left", "right")}
    strata = []
    for stratum in sorted({c["stratum"] for c in cells if c["stratum"]}):
        s_realized = block(lambda c: c["endpoint"], stratum)
        strata.append({"stratum": stratum, "cells": {s: sum(1 for c in cells if c["side"] == s and c["stratum"] == stratum) for s in ("left", "right")},
                       "realized": {k: s_realized[k] for k in ("left", "right", "difference")},
                       "components": {k: block(lambda c, k=k: c["parts"][k], stratum)["difference"] for k in KEYS}})
    pairs: dict[tuple, dict[str, Mapping[str, Any]]] = collections.defaultdict(dict)
    for c in cells:
        pairs[(c["unit"], c["stratum"], c["inference_seed"])][c["side"]] = c
    moves: dict[tuple[str, str], list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = collections.defaultdict(list)
    for pair in pairs.values():
        moves[(pair["right"]["category"], pair["left"]["category"])].append((pair["left"], pair["right"]))
    carried = lambda group, side: dict(sorted(collections.Counter(i["class"] for p in group for i in p[side]["classes"]).items()))
    transitions = [{"right_ending": r, "left_ending": l, "pairs": len(group),
                    "contribution": math.fsum(a["endpoint"] - b["endpoint"] for a, b in group) / len(pairs),
                    "components": {k: math.fsum(a["parts"][k] - b["parts"][k] for a, b in group) / len(pairs) for k in KEYS},
                    "left_classes": carried(group, 0), "right_classes": carried(group, 1)}
                   for (r, l), group in sorted(moves.items())]
    if abs(math.fsum(t["contribution"] for t in transitions) - realized["difference"]) > TOLERANCE:
        raise ValueError("pair transitions do not add up to the realized gap")
    grained = cells[0]["grain"] is not None
    report = {
        "schema_version": "aeread.gap_decomposition/0.1",
        "family": "procurement_allocation", "world_kind": spec.world_kind, "title": spec.title,
        "left": spec.campaign_id, "right": spec.campaign_id,
        "left_arms": sorted({c["arm"] for c in cells if c["side"] == "left"}),
        "right_arms": sorted({c["arm"] for c in cells if c["side"] == "right"}),
        "left_model": f"{MODEL} ({spec.left_label})", "right_model": f"{MODEL} ({spec.right_label})",
        "left_label": spec.left_label, "right_label": spec.right_label,
        "left_prompt": spec.left_prompt, "right_prompt": spec.right_prompt,
        "endpoint": "minus regret to the full-information bound (published regret_to_upper_bound_usd, negated): contribution margin less the world's bound",
        "unit": "USD per world: cells averaged within a world, then worlds averaged",
        "unit_label": "world", "per_label": "world", "amount_label": "USD/world",
        "class_heading": "failure class (published violations, and why minimum service failed)",
        "direction": "higher", "claim_status": "descriptive_fixed_panel",
        "winner_claim_allowed": False, "inferential_model_ranking_allowed": False,
        "paired_worlds": len(units), "cells": {s: sum(1 for c in cells if c["side"] == s) for s in ("left", "right")},
        "bootstrap": None if seeds_repeat else {
            "seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS, "interval": "percentile_95", "unit": "world",
            "stream": "one random.Random(seed): realized, then components in declared order, then class amounts in declared order"},
        "intervals": (("none: the environment never reads the inference seed, so the three seeds of a world and surface replay "
                       "one case digest and only the model's sampling differs; the unit is the world, and the twelve worlds "
                       "are a fixed curated panel") if seeds_repeat else None),
        "realized": realized,
        "components": components,
        "accounting_check": {
            "max_abs_residual_per_cell": max(abs(c["residual"]) for c in cells),
            "statement": "each cell's parts sum to minus its published regret_to_upper_bound_usd",
            "max_abs_contribution_residual": max(c["unexplained"] for c in cells),
            "contribution_statement": "per cell, the contribution rows of each part sum to that cell's part"},
        "categories": categories,
        "transitions": {"rows": transitions,
                        "statement": ("paired cells grouped by how each side ended (feasible award, infeasible award, no award); "
                                      "each group's contribution is its summed pair differences over all pairs, so the groups "
                                      "add up to the realized gap net of what a converted cell still loses")},
        "strata": strata,
        "cross_checks": _cross_checks(spec, checks, realized, strata),
        "classes": classes,
        "instances": sorted(instances, key=lambda i: (i["class"], i["side"], i["unit"], i["arm"], i["replicate_index"])),
        "cell_parts": [{**{k: c[k] for k in ("side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit", "stratum", "arm")},
                        "parts": c["parts"]} for c in sorted(cells, key=lambda c: (c["side"], c["unit"], c["arm"], c["replicate_index"]))],
        "contributions": {"table": f"tables/contributions{'_' + spec.suffix if spec.suffix else ''}.jsonl", "rows": len(table),
                          "fields": ["side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit", "arm",
                                     "step_index", "round_index", "phase_id", "seat_id", "action", "supplier_id", "component", "amount", "note"]
                          + ([] if grained else ["action_ordinal"])},
        "step_log": ("trajectories/procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2.jsonl in "
                     "procurement_allocation_trajectory_grains_v1; every row's step holds the action it names" if grained else
                     "none published: step_index, round_index, phase_id and seat_id are null; action_ordinal is the action's "
                     "1-based place in the published action_trace"),
        "source_manifest_sha256": dict(sources),
    }
    table.sort(key=lambda r: (r["side"], r["unit"], r["arm"], r["replicate_index"], r["action_ordinal"] if r["step_index"] is None else r["step_index"], r["component"]))
    return report, table


def _cross_checks(spec: Comparison, checks: Mapping[str, Any], realized: Mapping[str, Any], strata: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if spec is PRIMARY:
        effects = checks["published_effects"]
        published = effects["overall_treatment_minus_control"]["contribution_margin_usd"]["world_cluster_mean"]
        by_surface = {s: effects["by_surface"][s]["treatment_minus_control"]["contribution_margin_usd"]["world_cluster_mean"]
                      for s in ("labeled", "opaque")}
        if abs(realized["difference"] - published) > TOLERANCE or any(
                abs(s["realized"]["difference"] - by_surface[s["stratum"]]) > TOLERANCE for s in strata):
            raise ValueError("the realized gap does not reproduce the published confirmatory effect")
        return {"published_margin_effect_overall": published, "published_margin_effect_by_surface": by_surface,
                "published_interval_overall": effects["overall_treatment_minus_control"]["contribution_margin_usd"]["world_cluster_bootstrap_95_interval"],
                "published_decomposition_terms_matched": checks["published_decomposition_terms_matched"],
                "action_trace_entries_with_a_stray_supplier_id": checks["stray_supplier_ids"],
                "statement": ("the realized gap equals the confirmatory's published treatment-minus-control margin effect, overall "
                              "and per surface (margin and minus regret differ by the world's bound, which cancels in a pair); "
                              "every feasible award's replayed terms equal procurement_allocation_glm_regret_decomposition_v1's")}
    summary = checks["published_summary"]
    if abs(realized["difference"] + summary["mean_regret_delta_usd"]) > TOLERANCE:
        raise ValueError("the realized gap does not reproduce the published recovery effect")
    return {"published_mean_regret_delta_usd": summary["mean_regret_delta_usd"],
            "published_interval_regret": summary["world_cluster_bootstrap_95_interval"],
            "statement": "the realized gap equals minus the recovery confirmatory's published mean regret delta"}


def analyse() -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    primary, primary_checks = _confirmatory_cells()
    sources = {CONFIRMATORY: _sha(EVIDENCE / CONFIRMATORY / "publication_manifest.json"),
               GRAINS.split("/")[-1]: _sha(EVIDENCE / GRAINS / "publication_manifest.json"),
               DECOMPOSITION: _sha(EVIDENCE / DECOMPOSITION / "publication_manifest.json")}
    recovery, recovery_checks = _recovery_cells()
    return {
        PRIMARY.suffix: _report(PRIMARY, primary, primary_checks, True, sources),
        PRE_AWARD.suffix: _report(PRE_AWARD, recovery, recovery_checks, False,
                                  {RECOVERY.split("/")[-1]: _sha(EVIDENCE / RECOVERY / "publication_manifest.json")}),
    }


# --- output -------------------------------------------------------------------------------------------------------

def _table_bytes(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _report_bytes(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _paths(suffix: str) -> tuple[Path, Path]:
    tail = f"_{suffix}" if suffix else ""
    return OUT / "reports" / f"gap_decomposition{tail}.json", OUT / "tables" / f"contributions{tail}.jsonl"


def _readme(reports: Mapping[str, tuple[dict[str, Any], list]]) -> str:
    primary, secondary = reports[PRIMARY.suffix][0], reports[PRE_AWARD.suffix][0]
    ending = {"feasible_award": "feasible award", "infeasible_award": "award rejected at a gate", "no_award": "no award"}

    def parts_table(r: Mapping[str, Any]) -> list[str]:
        ci = lambda b: "" if b["difference_ci"] is None else f" ({b['difference_ci'][0]:.1f} to {b['difference_ci'][1]:.1f})"
        L, R = r["left_label"], r["right_label"]
        head = f"| part | {L} | {R} | {L} minus {R}{'' if r['bootstrap'] is None else ' (95% world bootstrap)'} |"
        rows = [head, "|---|---:|---:|---:|",
                f"| **minus regret (realized)** | **{r['realized']['left']:.1f}** | **{r['realized']['right']:.1f}** | **{r['realized']['difference']:.1f}**{ci(r['realized'])} |"]
        rows += [f"| {c['label']} ({c['group']}) | {c['left']:.1f} | {c['right']:.1f} | {c['difference']:.1f}{ci(c)} |" for c in r["components"]]
        return rows

    def transition_table(r: Mapping[str, Any]) -> list[str]:
        L, R = r["left_label"], r["right_label"]
        rows = [f"| {R} ended | {L} ended | pairs | contribution to the gap, USD/world | {R} classes in these pairs |", "|---|---|---:|---:|---|"]
        rows += [f"| {ending[t['right_ending']]} | {ending[t['left_ending']]} | {t['pairs']} | {t['contribution']:.2f} | "
                 + (", ".join(f"{k} {v}" for k, v in t["right_classes"].items()) or "none") + " |"
                 for t in sorted(r["transitions"]["rows"], key=lambda t: -abs(t["contribution"]))]
        return rows

    def class_table(r: Mapping[str, Any]) -> list[str]:
        L, R = r["left_label"], r["right_label"]
        rows = [f"| class | {L} cells | {R} cells | {L} regret/world | {R} regret/world |", "|---|---:|---:|---:|---:|"]
        rows += [f"| `{c['key']}`: {c['label']} | {c['left_count']} | {c['right_count']} | {c['left_amount_per_market']:.1f} | {c['right_amount_per_market']:.1f} |"
                 for c in r["classes"] if c["left_count"] or c["right_count"]]
        return rows

    def move(r: Mapping[str, Any], right: str, left: str) -> Mapping[str, Any]:
        return next((t for t in r["transitions"]["rows"] if t["right_ending"] == right and t["left_ending"] == left),
                    {"pairs": 0, "contribution": 0.0, "right_classes": {}, "left_classes": {}})

    count = lambda r, key, side: next(c[f"{side}_count"] for c in r["classes"] if c["key"] == key)
    x = primary["cross_checks"]
    gained, lost = move(primary, "infeasible_award", "feasible_award"), move(primary, "feasible_award", "infeasible_award")
    both = move(primary, "feasible_award", "feasible_award")
    strata = ["| surface | realized | " + " | ".join(c["key"] for c in primary["components"]) + " |",
              "|---|" + "---:|" * (len(primary["components"]) + 1)]
    strata += [f"| {s['stratum']} | {s['realized']['difference']:.1f} | " + " | ".join(f"{s['components'][c['key']]:.1f}" for c in primary["components"]) + " |"
               for s in primary["strata"]]
    rescued = move(secondary, "no_award", "feasible_award")
    steady = move(secondary, "feasible_award", "feasible_award")
    label = {c["key"]: c["label"] for c in secondary["components"]}
    ranked = sorted(steady["components"].items(), key=lambda kv: -abs(kv[1]))
    steady_parts = ", ".join(f"{label[k]} {v:+.2f}" for k, v in ranked if abs(v) >= 0.005)
    return "\n".join([
        f"# {OUT.name}",
        "",
        "Why a prompt treatment changes regret on the single-period procurement worlds. One model, GLM 5.3 Flash on "
        "Parasail, under two prompts, paired cell by cell on the same world and inference seed; treatment against "
        "control, not model against model. Derived from published bundles and the committed cases by "
        "`python -m aeread_families.procurement_allocation.single_period_gap`, which replays every published action "
        "trace (all 144 + 36 rows reproduce their published margin, regret, bound, feasibility, kits, termination and "
        "violations); `--check` regenerates these bytes. Descriptive: no winner, no ranking.",
        "",
        "The endpoint is minus `regret_to_upper_bound_usd` (higher is better), in USD per world. A submitted award that "
        "breaks a gate is scored at the defer value less the information already bought, so it loses nearly the whole "
        "bound; that cell's endpoint is one part, and a cell that ends with no award is another. A feasible award's "
        "regret is the ten additive term gaps against the full-information plan "
        "(`regret_decomposition.decompose_feasible_award`), grouped into four parts. When a treatment turns a rejected "
        "award into a feasible one, the gain shows up in the gate part and whatever the new award still loses shows up in "
        "the feasible-award parts, so read the parts together with the pair transitions, which net the two.",
        "",
        f"## {primary['title']}",
        "",
        f"`{CONFIRMATORY}`: strategy scaffold (`{PRIMARY.left_prompt}`) against the unscaffolded prompt "
        f"(`{PRIMARY.right_prompt}`), {primary['paired_worlds']} worlds x labeled and opaque surfaces x 3 seeds, "
        f"{primary['cells']['left']} cells a side.",
        "",
        f"The scaffold's {primary['realized']['difference']:+.1f} per world comes from fewer awards rejected at a gate. "
        f"In {gained['pairs']} pairs the unscaffolded award broke a gate and the scaffolded one was feasible "
        f"({gained['contribution']:+.1f} per world, net of what the new awards still lose); in "
        f"{gained['right_classes'].get('component_not_awarded', 0)} of those the unscaffolded award left a bill-of-materials "
        f"component with no supplier at all. That failure is {count(primary, 'component_not_awarded', 'right')} unscaffolded "
        f"cells and {count(primary, 'component_not_awarded', 'left')} scaffolded ones. {lost['pairs']} pairs went the other "
        f"way ({lost['contribution']:+.1f}), and where both awards were feasible ({both['pairs']} pairs) the scaffold moved "
        f"the economics by only {both['contribution']:+.1f}. The scaffold's own rejected awards fail differently: "
        f"{count(primary, 'sample_not_verified', 'left')} carry an unverified sample (against "
        f"{count(primary, 'sample_not_verified', 'right')}), {count(primary, 'arrives_after_deadline', 'left')} a line "
        f"that could no longer arrive in time (against {count(primary, 'arrives_after_deadline', 'right')}), and "
        f"{count(primary, 'quantity_short', 'left')} too few units with every component in place (against "
        f"{count(primary, 'quantity_short', 'right')}).",
        "",
        *transition_table(primary),
        "",
        *parts_table(primary),
        "",
        "The environment never reads the inference seed: the three seeds of a world and surface replay one case digest "
        "and only the model's sampling differs, so the world is the unit and no interval is given. The confirmatory's own "
        f"frozen analysis published a 12-world bootstrap for the headline, {x['published_interval_overall'][0]:.1f} to "
        f"{x['published_interval_overall'][1]:.1f}. The realized gap equals that published treatment-minus-control margin "
        f"effect ({x['published_margin_effect_overall']:.4f}) and its per-surface values "
        f"({x['published_margin_effect_by_surface']['labeled']:.4f} labeled, {x['published_margin_effect_by_surface']['opaque']:.4f} "
        f"opaque); the replayed terms of all {x['published_decomposition_terms_matched']} feasible awards equal "
        f"`{DECOMPOSITION}`'s. Largest per-cell residual {primary['accounting_check']['max_abs_residual_per_cell']:.2g}.",
        "",
        *strata,
        "",
        "Failure classes (diagnostic, overlapping, not parts of the sum). Counts are cells; amounts are the regret of the "
        "cells carrying the class, per world. The last three split `minimum_service_not_met` by what the replay shows:",
        "",
        *class_table(primary),
        "",
        "Steps are located in the trajectory grain published for this bundle in "
        "`procurement_allocation_trajectory_grains_v1`: one logical action per step, step index = action ordinal - 1, "
        "each step its own instance of the only phase, so the round index equals the step index. Every contribution row "
        "and instance names the action and supplier at its step, and a test checks both against the grain. A late line "
        "is located at the step whose days used up its slack; every other class at the award, defer, or ending step. "
        f"{x['action_trace_entries_with_a_stray_supplier_id']} published `action_trace` entries for an award or defer carry "
        "a `supplier_id` that the parser discards (the grain's parsed action has none), so rows name a supplier only for "
        "actions addressed to one.",
        "",
        f"## {secondary['title']}",
        "",
        f"`{RECOVERY.split('/')[-1]}`: the pre-award check worksheet against the strategy scaffold, both with the binomial "
        f"sample notice, {secondary['paired_worlds']} worlds x 3 seeds, {secondary['cells']['left']} cells a side. Each "
        "seed binds that episode's sample-noise draw, so seeds are distinct cases of a world, and intervals are a "
        f"world-clustered bootstrap (seed {BOOTSTRAP_SEED}, {BOOTSTRAP_DRAWS} draws) over only "
        f"{secondary['paired_worlds']} worlds.",
        "",
        f"The worksheet's {secondary['realized']['difference']:+.1f} per world involves no award rejected at a gate on "
        f"either side. {rescued['contribution']:.1f} of it is the {rescued['pairs']} pair where the scaffold deferred and "
        f"the worksheet awarded: the defer forgoes the whole bound ({rescued['components']['no_award']:+.1f} in the no-award "
        f"part), and the worksheet's award there gives back {rescued['contribution'] - rescued['components']['no_award']:+.1f} "
        f"in the feasible-award parts. The other {steady['contribution']:.1f} comes from the {steady['pairs']} pairs where "
        f"both sides awarded: {steady_parts}. The realized gap equals minus the published mean regret delta "
        f"({secondary['cross_checks']['published_mean_regret_delta_usd']:.4f}); largest per-cell residual "
        f"{secondary['accounting_check']['max_abs_residual_per_cell']:.2g}.",
        "",
        *transition_table(secondary),
        "",
        *parts_table(secondary),
        "",
        *class_table(secondary),
        "",
        "No step-level log is published for this bundle, so its contribution rows and instances carry null step fields "
        "and name the action by `action_ordinal`, its place in the published `action_trace`.",
        "",
        "Reports: `reports/gap_decomposition.json` and `reports/gap_decomposition_pre_award_check.json`, each with every "
        "cell's parts, the pair transitions, and every class instance at its step. Tables: `tables/contributions.jsonl` "
        f"({primary['contributions']['rows']} rows) and `tables/contributions_pre_award_check.jsonl` "
        f"({secondary['contributions']['rows']} rows), one row per decision per part; per cell a part's rows sum to that "
        f"cell's part (largest difference {max(primary['accounting_check']['max_abs_contribution_residual'], secondary['accounting_check']['max_abs_contribution_residual']):.2g}).",
        "",
    ])


def write() -> None:
    reports = analyse()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    for suffix, (report, table) in reports.items():
        report_path, table_path = _paths(suffix)
        report_path.write_text(_report_bytes(report), encoding="utf-8")
        table_path.write_text(_table_bytes(table), encoding="utf-8")
    (OUT / "README.md").write_text(_readme(reports), encoding="utf-8")


def check() -> bool:
    reports = analyse()
    readme = OUT / "README.md"
    ok = readme.exists() and readme.read_text(encoding="utf-8") == _readme(reports)
    for suffix, (report, table) in reports.items():
        report_path, table_path = _paths(suffix)
        ok = ok and report_path.exists() and report_path.read_text(encoding="utf-8") == _report_bytes(report)
        ok = ok and table_path.exists() and table_path.read_text(encoding="utf-8") == _table_bytes(table)
    print("single-period gap analysis regenerates to the committed bytes" if ok
          else "single-period gap analysis differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        print(f"wrote {OUT.relative_to(ROOT)}")
        return 0
    if args.check:
        return 0 if check() else 1
    for suffix, (report, _) in analyse().items():
        print(suffix or "primary", round(report["realized"]["difference"], 4),
              {c["key"]: round(c["difference"], 2) for c in report["components"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
