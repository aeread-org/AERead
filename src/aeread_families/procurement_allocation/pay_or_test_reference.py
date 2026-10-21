"""Pay the premium or test the cheaper unknown: the best informed policy, computed exactly.

The pack this serves has one supplier with a record and several without. A
supplier without a record is good, late or poor-yield with shares the listing
states; a formal quote shows whether it is late and a verified sample shows
whether its yield is poor. Every request costs money and days, and an order
that would land after the deadline delivers nothing.

That is a search problem with a known answer. A buyer who knows the stated
shares and nothing else about a listing has, at every point, a best next
request, and ``Reference`` computes it by backward induction over what the
buyer has learned so far. Three things follow from having it:

- the generator can place worlds on both sides of the line between paying and
  testing, and say how much the wrong side costs before anything is played;
- a scripted rule has an exact expected value, not one draw;
- a player's trajectory can be priced one action at a time, as the dollars
  each action gave up against the best action available with what the player
  knew then. Whether a tested supplier turned out good is a draw, and this
  measure does not move with it.

The reference knows the pack's world model: suppliers differ in price, lead
time, sample fee and type, a type changes only the on-time rate and the yield,
and a qualified supplier is a good one. It never reads which type a supplier
is. Award values come from the environment's own ``evaluate_award``.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.task.scheduler import ActionEnvelope

from .environment import ProcurementAllocationPlugin, _base_offer, _quantity_values, _validate_payload, evaluate_award

GOOD, LATE, POOR = "good", "late", "poor"
#: What a good supplier's quote and sample show. A rate below ``BAD_BELOW`` is a bad one.
GOOD_ON_TIME, GOOD_YIELD = 0.97, 0.97
LATE_ON_TIME, POOR_YIELD = 0.55, 0.55
BAD_BELOW = 0.9

#: What the buyer has learned about one supplier.
UNTOUCHED, QUOTED, SAMPLED, QUALIFIED, BAD = "untouched", "quoted", "sampled", "qualified", "bad"

Rule = Callable[["Reference", tuple[str, ...], int, int], tuple[Any, ...]]


def prior_from_listing(listing: Mapping[str, Any]) -> tuple[float, float, float]:
    """Shares (good, late, poor) a buyer reads off a listing.

    A listing with reported orders of its own is taken as known: the pack's one
    recorded supplier is its good one, and its record says so. A new listing
    carries what the marketplace found for new sellers of its kind, and those
    counts are the shares.
    """
    record = listing["marketplace_record"]
    if record["orders_reported"] > 0:
        return (1.0, 0.0, 0.0)
    cohort = listing["cohort_record"]
    tracked = cohort["sellers_tracked"]
    late = cohort["unreliable_on_delivery"] / tracked
    poor = cohort["failed_inspection"] / tracked
    return (round(1.0 - late - poor, 12), late, poor)


class Reference:
    """Values and best actions for one world, from the buyer's side of the table."""

    def __init__(self, payload: Mapping[str, Any]):
        self.plugin = ProcurementAllocationPlugin()
        # The plugin's own validation also solves the full-information bound, which the reference
        # does not need and a screen over thousands of seeds cannot afford.
        self.case = _validate_payload(payload)
        self.phase = self.plugin.phases(self.case)[0]
        interaction, objective = self.case["interaction"], self.case["objective"]
        if "sample_noise" in interaction:
            raise ValueError("the reference assumes a sample settles a supplier's yield")
        self.max_actions = int(interaction["max_actions"])
        self.deadline = int(objective["deadline_days"])
        self.defer_value = float(objective["defer_value_usd"])
        self.wasted = {
            "inquire": (float(interaction["inquiry_cost_usd"]), int(interaction["inquiry_days"])),
            "counter_offer": (float(interaction["counter_cost_usd"]), int(interaction["counter_days"])),
            "check_award": (0.0, 0),
        }
        self.quote = (float(interaction["quote_cost_usd"]), int(interaction["quote_days"]))
        suppliers = sorted(self.case["suppliers"], key=lambda s: s["supplier_id"])
        self.ids = tuple(s["supplier_id"] for s in suppliers)
        self.index = {sid: i for i, sid in enumerate(self.ids)}
        self.prior = tuple(prior_from_listing(s["listing"]) for s in suppliers)
        self.price = tuple(float(s["listing"]["displayed_unit_price_usd"]) for s in suppliers)
        self.lead = tuple(int(s["private_terms"]["lead_time_days"]) for s in suppliers)
        self.sample = tuple(
            (float(s["private_terms"]["quality"]["sample_cost_usd"]), int(s["private_terms"]["quality"]["sample_lead_time_days"]))
            for s in suppliers
        )
        self.established = tuple(i for i, p in enumerate(self.prior) if p[0] == 1.0)
        self.newcomers = tuple(i for i, p in enumerate(self.prior) if p[0] < 1.0)
        # Every supplier as it would be if good: what an award on a qualified one is worth.
        good_case = copy.deepcopy(self.case)
        for supplier in good_case["suppliers"]:
            supplier["private_terms"]["on_time_probability"] = GOOD_ON_TIME
            supplier["private_terms"]["quality"]["verified_yield_rate"] = GOOD_YIELD
        self._good = {s["supplier_id"]: s for s in good_case["suppliers"]}
        self._good_case = good_case
        self._award: dict[tuple[int, bool], tuple[float, int]] = {}
        self._value: dict[tuple[tuple[str, ...], int, int], float] = {}
        self._rule_value: dict[tuple[str, tuple[str, ...], int, int], float] = {}
        # Past this day nothing can arrive, so every later day is the same state.
        self.day_cap = self.deadline - min(self.lead) + 1
        budget = float(objective["cash_budget_usd"])
        dearest = max(self.price) * max(int(s["private_terms"]["capacity"]) for s in suppliers) * 1.2
        every_request = sum(fee for fee, _ in self.sample) + self.quote[0] * len(self.ids) + 20.0
        if budget < dearest + every_request:
            raise ValueError("cash budget could bind; the reference treats information cost as additive")

    # --- what an award is worth -------------------------------------------------

    def award(self, supplier: int, day: int) -> tuple[float, int]:
        """Best single-supplier award on a qualified supplier at ``day``: value before information cost, and quantity."""
        timely = day + self.lead[supplier] <= self.deadline
        key = (supplier, timely)
        if key not in self._award:
            sid = self.ids[supplier]
            good = self._good[sid]
            offer = _base_offer(good, version=1, issued_day=0)
            evidence = {sid: {**good["private_terms"]["quality"], "supplier_id": sid,
                              "variant_id": good["private_terms"]["variant_id"], "evidence_status": "verified_sample"}}
            best = (self.defer_value, 0)
            for quantity in _quantity_values(offer):
                result = evaluate_award(
                    self._good_case, award_lines=[{"offer_id": offer["offer_id"], "quantity": quantity}],
                    offers={offer["offer_id"]: offer}, quality_evidence=evidence,
                    elapsed_days=day if timely else self.deadline + 1, information_cost_usd=0.0,
                )
                if result["feasible"] and result["contribution_margin_usd"] > best[0] + 1e-9:
                    best = (float(result["contribution_margin_usd"]), quantity)
            self._award[key] = best
        return self._award[key]

    def best_award(self, status: Sequence[str], day: int) -> tuple[float, int | None, int]:
        """(value, supplier, quantity) of the best award among qualified suppliers; supplier ``None`` if none pays."""
        best: tuple[float, int | None, int] = (self.defer_value, None, 0)
        for i, state in enumerate(status):
            if state == QUALIFIED:
                value, quantity = self.award(i, day)
                if value > best[0] + 1e-9:
                    best = (value, i, quantity)
        return best

    # --- what a request can show ------------------------------------------------

    def outcomes(self, status: Sequence[str], kind: str, supplier: int) -> tuple[tuple[float, tuple[str, ...]], ...]:
        """Chance outcomes of a quote or a sample: (probability, what the buyer then knows)."""
        good, late, poor = self.prior[supplier]
        now = status[supplier]

        def to(state: str) -> tuple[str, ...]:
            return tuple(state if i == supplier else s for i, s in enumerate(status))

        if kind == "request_quote" and now == UNTOUCHED:
            pairs = [(late, BAD), (1.0 - late, QUOTED)]
        elif kind == "request_quote" and now == SAMPLED:
            pairs = [(late / (good + late), BAD), (good / (good + late), QUALIFIED)]
        elif kind == "request_sample" and now == UNTOUCHED:
            pairs = [(poor, BAD), (1.0 - poor, SAMPLED)]
        elif kind == "request_sample" and now == QUOTED:
            pairs = [(poor / (good + poor), BAD), (good / (good + poor), QUALIFIED)]
        else:  # a repeat, or a request on a supplier already known bad: nothing new
            pairs = [(1.0, now)]
        return tuple((p, to(state)) for p, state in pairs if p > 0.0)

    def cost(self, kind: str, supplier: int | None) -> tuple[float, int]:
        if kind == "request_quote":
            return self.quote
        if kind == "request_sample":
            return self.sample[supplier]
        return self.wasted[kind]

    def requests(self, status: Sequence[str]) -> tuple[tuple[str, int], ...]:
        """Requests that can still show something."""
        found = []
        for i, state in enumerate(status):
            if state in (UNTOUCHED, SAMPLED):
                found.append(("request_quote", i))
            if state in (UNTOUCHED, QUOTED):
                found.append(("request_sample", i))
        return tuple(found)

    # --- the best informed policy -----------------------------------------------

    def value(self, status: tuple[str, ...], actions_left: int, day: int) -> float:
        """Expected dollars from here under the best policy, before information cost already paid."""
        if actions_left <= 0:
            return self.defer_value
        day = min(day, self.day_cap)
        key = (status, actions_left, day)
        if key not in self._value:
            best = max(self.defer_value, self.best_award(status, day)[0])
            if actions_left > 1 and day < self.day_cap:
                for kind, supplier in self.requests(status):
                    best = max(best, self.request_value(status, actions_left, day, kind, supplier))
            self._value[key] = best
        return self._value[key]

    def request_value(self, status: tuple[str, ...], actions_left: int, day: int, kind: str, supplier: int | None) -> float:
        """Expected dollars from taking one non-terminal action now and playing best afterwards."""
        fee, days = self.cost(kind, supplier)
        if kind in ("request_quote", "request_sample"):
            return -fee + sum(p * self.value(nxt, actions_left - 1, day + days) for p, nxt in self.outcomes(status, kind, supplier))
        return -fee + self.value(status, actions_left - 1, day + days)

    def best_action(self, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
        """One best action: ("request_quote"|"request_sample", supplier), ("submit_award", supplier, quantity) or ("defer",)."""
        target = self.value(status, actions_left, day)
        award_value, supplier, quantity = self.best_award(status, day)
        # Ties go to ending the episode: an award before a request, a request before walking away.
        if supplier is not None and award_value >= target - 1e-9:
            return ("submit_award", supplier, quantity)
        if actions_left > 1:
            for kind, who in self.requests(status):
                if self.request_value(status, actions_left, day, kind, who) >= target - 1e-9:
                    return (kind, who)
        return ("defer",)

    # --- scripted rules, valued exactly ------------------------------------------

    def rule_value(self, name: str, rule: Rule, status: tuple[str, ...], actions_left: int, day: int) -> float:
        """Expected dollars from following ``rule`` from here, over what its requests may show."""
        if actions_left <= 0:
            return self.defer_value
        day = min(day, self.day_cap)
        key = (name, status, actions_left, day)
        if key not in self._rule_value:
            action = rule(self, status, actions_left, day)
            if action[0] == "defer":
                value = self.defer_value
            elif action[0] == "submit_award":
                value = self.award(action[1], day)[0] if status[action[1]] == QUALIFIED else self.defer_value
            else:
                fee, days = self.cost(action[0], action[1])
                value = -fee + sum(p * self.rule_value(name, rule, nxt, actions_left - 1, day + days)
                                   for p, nxt in self.outcomes(status, action[0], action[1]))
            self._rule_value[key] = value
        return self._rule_value[key]

    def start(self) -> tuple[tuple[str, ...], int, int]:
        return (tuple(UNTOUCHED for _ in self.ids), self.max_actions, 0)

    # --- reading the environment's state ----------------------------------------

    def status_of(self, state: Mapping[str, Any]) -> tuple[str, ...]:
        """What the buyer has learned, from the offers and samples in an environment state."""
        offers, samples = state["offers"], state["quality_evidence"]
        latest = state["latest_offer_by_supplier"]
        status = []
        for sid in self.ids:
            quoted, sampled = sid in latest, sid in samples
            late = quoted and float(offers[latest[sid]]["on_time_probability"]) < BAD_BELOW
            poor = sampled and float(samples[sid]["verified_yield_rate"]) < BAD_BELOW
            status.append(BAD if late or poor else QUALIFIED if quoted and sampled else QUOTED if quoted
                          else SAMPLED if sampled else UNTOUCHED)
        return tuple(status)

    def wire(self, action: tuple[Any, ...], state: Mapping[str, Any]) -> dict[str, Any]:
        """A reference action as the environment's wire action."""
        if action[0] in ("request_quote", "request_sample"):
            return {"action": action[0], "supplier_id": self.ids[action[1]], "message": "Please proceed."}
        if action[0] == "submit_award":
            offer_id = state["latest_offer_by_supplier"][self.ids[action[1]]]
            return {"action": "submit_award", "award_lines": [{"offer_id": offer_id, "quantity": int(action[2])}]}
        return {"action": "defer", "reason": "No award is worth making."}


# --- rules a buyer might follow ---------------------------------------------------


def days_to_qualify(ref: Reference, status: Sequence[str], supplier: int) -> int:
    """Days still needed before ``supplier`` could be awarded."""
    state = status[supplier]
    return (ref.quote[1] if state in (UNTOUCHED, SAMPLED) else 0) + (ref.sample[supplier][1] if state in (UNTOUCHED, QUOTED) else 0)


def _qualify(ref: Reference, status: Sequence[str], supplier: int, day: int) -> tuple[Any, ...] | None:
    """The next step toward an award on ``supplier``; ``None`` once it is known bad or can no longer deliver in time."""
    state = status[supplier]
    if state == BAD or day + days_to_qualify(ref, status, supplier) + ref.lead[supplier] > ref.deadline:
        return None
    if state == QUALIFIED:
        value, quantity = ref.award(supplier, day)
        return ("submit_award", supplier, quantity) if quantity else None
    return ("request_quote", supplier) if state in (UNTOUCHED, SAMPLED) else ("request_sample", supplier)


def _fall_back(ref: Reference, status: Sequence[str], day: int) -> tuple[Any, ...]:
    for supplier in ref.established:
        step = _qualify(ref, status, supplier, day)
        if step is not None:
            return step
    return ("defer",)


def pay_premium(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """Never look at a supplier without a record."""
    return _fall_back(ref, status, day)


def test_once(target: Callable[[Reference], int]) -> Rule:
    """Test one chosen newcomer, award it if it qualifies, otherwise go to the recorded supplier."""
    def rule(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
        return _qualify(ref, status, target(ref), day) or _fall_back(ref, status, day)
    return rule


def cheapest_newcomer(ref: Reference) -> int:
    return min(ref.newcomers, key=lambda i: (ref.price[i], ref.ids[i]))


def best_odds_newcomer(ref: Reference) -> int:
    return max(ref.newcomers, key=lambda i: (ref.prior[i][0], -ref.price[i]))


def cheapest_until_found(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """Work up the price list until one qualifies; the recorded supplier only when every cheaper one has failed."""
    for supplier in sorted(ref.newcomers, key=lambda i: (ref.price[i], ref.ids[i])):
        step = _qualify(ref, status, supplier, day)
        if step is not None:
            return step
    return _fall_back(ref, status, day)


def one_step_value(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """Compare each untested newcomer with paying, one test ahead, and keep the recorded supplier reachable.

    The gain from testing newcomer ``i`` before falling back is the chance it
    is good times what it saves (its better award, and the recorded supplier's
    own quote and sample), less the quote and the sample fee when the quote
    does not already rule it out. A test is taken only if the recorded
    supplier could still be qualified and deliver after it fails.
    """
    for supplier in ref.newcomers:  # finish a test already begun, or use its result
        if status[supplier] in (QUOTED, SAMPLED, QUALIFIED):
            return _qualify(ref, status, supplier, day)
    base = ref.established[0]
    reserve = days_to_qualify(ref, status, base)
    pay_cost = (ref.quote[0] if status[base] in (UNTOUCHED, SAMPLED) else 0.0) + (ref.sample[base][0] if status[base] in (UNTOUCHED, QUOTED) else 0.0)
    best: tuple[float, int | None] = (0.0, None)
    for supplier in ref.newcomers:
        if status[supplier] != UNTOUCHED:
            continue
        good, late, _poor = ref.prior[supplier]
        after = day + ref.quote[1] + ref.sample[supplier][1]
        if after + reserve + ref.lead[base] > ref.deadline or after + ref.lead[supplier] > ref.deadline:
            continue
        saving = ref.award(supplier, after)[0] - ref.award(base, after + reserve)[0]
        gain = good * (saving + pay_cost) - ref.quote[0] - (1.0 - late) * ref.sample[supplier][0]
        if gain > best[0]:
            best = (gain, supplier)
    if best[1] is not None:
        return ("request_quote", best[1])
    return _fall_back(ref, status, day)


RULES: dict[str, Rule] = {
    "pay_premium": pay_premium,
    "cheapest_first_once": test_once(cheapest_newcomer),
    "best_odds_first_once": test_once(best_odds_newcomer),
    "cheapest_until_found": cheapest_until_found,
    "one_step_value": one_step_value,
}


# --- playing and pricing a trajectory ------------------------------------------------


def _step(ref: Reference, state: Mapping[str, Any], action: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    parsed = ref.plugin.parse_action(ref.case, state, "buyer", ref.phase, dict(action))
    if not parsed.ok:
        envelope = ActionEnvelope(seat_id="buyer", valid=False, action=None, parse=parsed, legality=None)
        return ref.plugin.step(ref.case, state, ref.phase, {"buyer": envelope}).state, False
    legality = ref.plugin.legal(ref.case, state, "buyer", ref.phase, parsed.action)
    envelope = ActionEnvelope(seat_id="buyer", valid=legality.legal, action=parsed.action, parse=parsed, legality=legality)
    return ref.plugin.step(ref.case, state, ref.phase, {"buyer": envelope}).state, bool(legality.legal)


def _complete(ref: Reference, action: Mapping[str, Any]) -> dict[str, Any]:
    """A public trace row as a full wire action: the trace drops messages, inquiry fields and reasons."""
    kind = action.get("action")
    full = {k: v for k, v in action.items()
            if k in ("action", "supplier_id", "offer_id", "proposal", "award_lines", "fields", "message", "reason") and v is not None}
    if kind in ("request_quote", "request_sample", "inquire", "counter_offer"):
        full.setdefault("message", "(replayed)")
    if kind == "inquire":
        full.setdefault("fields", [ref.case["policy"]["inquiry_fields"][0]])
    if kind == "defer":
        full.setdefault("reason", "(replayed)")
    return full


def score_actions(payload: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Replay a trajectory and price each action against the best one available at that point.

    ``decision_loss_usd`` is the sum over actions of the best policy's value
    less the value of the action taken, both given only what the buyer had
    learned. It is split by what the action was: ``requests`` (a quote or a
    sample that was not the best next step), ``strays`` (an inquiry, a counter
    or a pre-award check, none of which can change anything in this pack),
    ``walk_away`` (a defer or a rejected action), ``award_timing`` (awarding
    when a further request was worth more) and ``award_terms`` (the supplier
    and quantity of the award itself).
    """
    ref = Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    steps: list[dict[str, Any]] = []
    loss = {"requests": 0.0, "strays": 0.0, "walk_away": 0.0, "award_timing": 0.0, "award_terms": 0.0}
    for raw in actions:
        if state["done"]:
            break
        status = ref.status_of(state)
        left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
        best = ref.value(status, left, day)
        action = _complete(ref, raw)
        kind = action.get("action")
        nxt, valid = _step(ref, state, action)
        row: dict[str, Any] = {"action": kind, "supplier_id": action.get("supplier_id"), "day": day, "actions_left": left,
                               "best_value_usd": round(best, 4), "best_action": _describe(ref, ref.best_action(status, left, day))}
        if not valid or kind == "defer":
            taken, part = ref.defer_value, "walk_away"
        elif kind == "submit_award":
            result = evaluate_award(ref.case, award_lines=action["award_lines"], offers=state["offers"],
                                    quality_evidence=state["quality_evidence"], elapsed_days=day,
                                    information_cost_usd=0.0)
            taken = float(result["contribution_margin_usd"]) if result["feasible"] else ref.defer_value
            best_now = ref.best_award(status, day)[0]
            loss["award_timing"] += max(0.0, best - best_now)
            loss["award_terms"] += best_now - taken
            part = None
        else:
            supplier = ref.index.get(action.get("supplier_id")) if kind in ("request_quote", "request_sample") else None
            taken = ref.request_value(status, left, day, kind, supplier)
            part = "requests" if kind in ("request_quote", "request_sample") else "strays"
        if part:
            loss[part] += best - taken
        row["value_taken_usd"], row["loss_usd"], row["valid"] = round(taken, 4), round(best - taken, 4), valid
        steps.append(row)
        state = nxt
    terminal = ref.plugin.terminal(ref.case, state)
    outcome = ref.plugin.outcome(ref.case, terminal) if terminal is not None else None
    start = ref.start()
    return {
        "steps": steps,
        "decision_loss_usd": round(sum(loss.values()), 4),
        "loss_by_part_usd": {k: round(v, 4) for k, v in loss.items()},
        "best_policy_value_usd": round(ref.value(*start), 4),
        "first_target": steps[0]["supplier_id"] if steps else None,
        "requests": sum(s["action"] in ("request_quote", "request_sample") for s in steps),
        "newcomers_touched": len({s["supplier_id"] for s in steps if s["supplier_id"] in {ref.ids[i] for i in ref.newcomers}}),
        "outcome": outcome,
    }


def final_margin(ref: Reference, state: Mapping[str, Any]) -> float:
    """Contribution margin of a finished episode, as the environment's outcome computes it, without solving its bound."""
    if state["termination_reason"] == "submitted":
        result = evaluate_award(ref.case, award_lines=state["award_lines"], offers=state["offers"],
                                quality_evidence=state["quality_evidence"], elapsed_days=state["elapsed_days"],
                                information_cost_usd=state["information_cost_usd"])
        return float(result["contribution_margin_usd"])
    return ref.defer_value - float(state["information_cost_usd"])


def run(payload: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Play wire actions through the environment and return its final state."""
    ref = Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    for action in actions:
        if state["done"]:
            break
        state, _ = _step(ref, state, _complete(ref, action))
    return state


def _describe(ref: Reference, action: tuple[Any, ...]) -> str:
    if action[0] in ("request_quote", "request_sample"):
        return f"{action[0]} {ref.ids[action[1]]}"
    if action[0] == "submit_award":
        return f"submit_award {ref.ids[action[1]]} x{action[2]}"
    return "defer"


def play(payload: Mapping[str, Any], rule: Rule | None = None) -> list[dict[str, Any]]:
    """The wire actions a rule (default: the best policy) takes on a world as it really is."""
    ref = Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    actions: list[dict[str, Any]] = []
    while not state["done"]:
        status = ref.status_of(state)
        left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
        choice = ref.best_action(status, left, day) if rule is None else rule(ref, status, left, day)
        if choice[0] == "submit_award" and status[choice[1]] != QUALIFIED:
            choice = ("defer",)
        action = ref.wire(choice, state)
        actions.append(action)
        state, _ = _step(ref, state, action)
    return actions


__all__ = [
    "BAD", "BAD_BELOW", "GOOD", "GOOD_ON_TIME", "GOOD_YIELD", "LATE", "LATE_ON_TIME", "POOR", "POOR_YIELD",
    "QUALIFIED", "QUOTED", "RULES", "Reference", "SAMPLED", "UNTOUCHED", "best_odds_newcomer", "cheapest_newcomer",
    "cheapest_until_found", "days_to_qualify", "final_margin", "one_step_value", "run", "pay_premium", "play", "prior_from_listing", "score_actions", "test_once",
]
