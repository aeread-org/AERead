"""Pay or test, version 2: the best informed policy when newcomers of one kind may share a source.

Version 1's newcomers were independent, and a buyer who compared each untested
newcomer with paying, one test ahead, reached the best policy to within six
cents a world (the family QC profile, section 8). Here new listings of the same
seller kind share a source with a probability the case states. If they share
one they are all of one type, drawn with the cohort's shares; if not, each is
drawn on its own with those shares. Each newcomer's own odds are still exactly
the cohort's shares, so nothing on one listing changes; what changes is that
testing one newcomer says something about the others of its kind, and a test
can be worth taking for what it tells about another listing rather than for
its own award.

The best informed policy is still computed exactly, by the same backward
induction as version 1 (``pay_or_test_reference.Reference``, subclassed here,
not edited), over a state that also keeps which way a bad newcomer failed: a
late one and a poor one say different things about the rest of its kind. The
chance of each outcome of a request is read from the joint prior over the
newcomers' types, conditioned on everything the buyer has seen. The reference
never reads a supplier's type.

``one_step_value`` is the strongest rule that looks one test ahead: at every
point it prices, for each newcomer not yet settled, finishing a test of that
newcomer and then stopping the best way, exactly under the same posterior, and
takes the best of those or stops. It sees how one result moves its beliefs; it
does not see that a test can pay for itself through the test it makes worth
taking next. Admission (``pay_or_test_v2_case_matrix.admit``) requires that it,
every fixed rule and one kind-blind shortcut fall short of the best policy by a
declared margin in every world. Three more rules are diagnostics, reported and
not screened: a two-test lookahead, the one-step rule free to start a test with
the sample, and a habit that writes the inference down (sample the cheapest of
a kind that has a dearer one first).
"""

from __future__ import annotations

import itertools
from typing import Any, Callable, Mapping, Sequence

from .environment import evaluate_award
from .pay_or_test_reference import BAD as _INDEPENDENT_BAD
from .pay_or_test_reference import one_step_value as _independent_one_step
from .pay_or_test_reference import (
    BAD_BELOW, GOOD, LATE, POOR, QUALIFIED, QUOTED, SAMPLED, UNTOUCHED,
    Reference as _IndependentReference, _complete, _describe, _step, final_margin, run,
)

#: Two ways a newcomer is found bad. They say different things about the rest of its kind.
SHOWN_LATE, SHOWN_POOR = "shown_late", "shown_poor"
BAD_STATES = frozenset({SHOWN_LATE, SHOWN_POOR})
TYPES = (GOOD, LATE, POOR)
#: Which types a status leaves possible.
_ALLOWS = {
    UNTOUCHED: frozenset(TYPES), QUOTED: frozenset({GOOD, POOR}), SAMPLED: frozenset({GOOD, LATE}),
    QUALIFIED: frozenset({GOOD}), SHOWN_LATE: frozenset({LATE}), SHOWN_POOR: frozenset({POOR}),
}
SOURCING_FIELD = "newcomer_sourcing"

Rule = Callable[["Reference", tuple[str, ...], int, int], tuple[Any, ...]]


def same_source_probability(payload_or_case: Mapping[str, Any]) -> float:
    return float(payload_or_case["policy"][SOURCING_FIELD]["same_source_probability"])


class Reference(_IndependentReference):
    """Values and best actions for one world, with newcomers of one kind possibly sharing a source."""

    def __init__(self, payload: Mapping[str, Any]):
        super().__init__(payload)
        rho = same_source_probability(self.case)
        if not 0.0 <= rho <= 1.0:
            raise ValueError("same_source_probability must lie in [0, 1]")
        sourcing = self.case["policy"][SOURCING_FIELD]
        if sourcing.get("grouped_by") != "seller_kind":
            raise ValueError("version 2 groups newcomers by seller kind")
        self.rho = rho
        kinds = {s["supplier_id"]: s["listing"]["seller_kind"] for s in self.case["suppliers"]}
        groups: dict[str, list[int]] = {}
        for i in self.newcomers:
            groups.setdefault(kinds[self.ids[i]], []).append(i)
        self.groups = tuple(tuple(members) for _, members in sorted(groups.items()))
        for members in self.groups:
            shares = {self.prior[i] for i in members}
            if len(shares) != 1:
                raise ValueError("newcomers of one kind must carry one cohort's shares")
        self.profiles = self._joint_prior()
        self._belief: dict[tuple[str, ...], tuple[float, ...]] = {}
        self._odds: dict[tuple[tuple[str, ...], int], tuple[float, float, float]] = {}
        self._outcomes: dict[tuple[tuple[str, ...], str, int], tuple[tuple[float, tuple[str, ...]], ...]] = {}

    # --- the joint prior and what the buyer has learned --------------------------

    def _joint_prior(self) -> tuple[tuple[dict[int, str], float], ...]:
        """Every assignment of types to the newcomers, with its prior probability."""
        by_group = []
        for members in self.groups:
            good, late, poor = self.prior[members[0]]
            share = {GOOD: good, LATE: late, POOR: poor}
            rows = []
            for types in itertools.product(TYPES, repeat=len(members)):
                independent = 1.0
                for t in types:
                    independent *= share[t]
                shared = share[types[0]] if len(set(types)) == 1 else 0.0
                weight = independent if len(members) == 1 else self.rho * shared + (1.0 - self.rho) * independent
                if weight > 0.0:
                    rows.append((dict(zip(members, types)), weight))
            by_group.append(rows)
        joint = []
        for combo in itertools.product(*by_group):
            assignment: dict[int, str] = {}
            weight = 1.0
            for part, w in combo:
                assignment.update(part)
                weight *= w
            joint.append((assignment, weight))
        return tuple(joint)

    def joint_prior(self) -> tuple[tuple[tuple[str, ...], float], ...]:
        """(types of the newcomers in ``self.newcomers`` order, probability) for every profile."""
        return tuple((tuple(a[i] for i in self.newcomers), w) for a, w in self.profiles)

    def belief(self, status: tuple[str, ...]) -> tuple[float, ...]:
        """Posterior weight of each profile given what the buyer has seen; all zeros if nothing fits."""
        key = tuple(status[i] for i in self.newcomers)  # the recorded supplier's state says nothing about types
        if key not in self._belief:
            weights = []
            for assignment, weight in self.profiles:
                fits = all(assignment[i] in _ALLOWS[s] for i, s in zip(self.newcomers, key))
                weights.append(weight if fits else 0.0)
            total = sum(weights)
            self._belief[key] = tuple(w / total for w in weights) if total > 0 else tuple(weights)
        return self._belief[key]

    def type_odds(self, status: tuple[str, ...], supplier: int) -> tuple[float, float, float]:
        """(good, late, poor) for ``supplier`` given everything seen so far."""
        if supplier not in self.newcomers:
            return (1.0, 0.0, 0.0)
        key = (tuple(status[i] for i in self.newcomers), supplier)
        if key not in self._odds:
            odds = {t: 0.0 for t in TYPES}
            for (assignment, _), w in zip(self.profiles, self.belief(status)):
                odds[assignment[supplier]] += w
            self._odds[key] = (odds[GOOD], odds[LATE], odds[POOR])
        return self._odds[key]

    # --- what a request can show ------------------------------------------------

    def outcomes(self, status: Sequence[str], kind: str, supplier: int) -> tuple[tuple[float, tuple[str, ...]], ...]:
        status = tuple(status)
        key = (status, kind, supplier)
        if key not in self._outcomes:
            self._outcomes[key] = self._outcomes_of(status, kind, supplier)
        return self._outcomes[key]

    def _outcomes_of(self, status: tuple[str, ...], kind: str, supplier: int) -> tuple[tuple[float, tuple[str, ...]], ...]:
        good, late, poor = self.type_odds(status, supplier)
        now = status[supplier]

        def to(state: str) -> tuple[str, ...]:
            return tuple(state if i == supplier else s for i, s in enumerate(status))

        if kind == "request_quote" and now == UNTOUCHED:
            pairs = [(late, SHOWN_LATE), (good + poor, QUOTED)]
        elif kind == "request_quote" and now == SAMPLED:
            pairs = [(late, SHOWN_LATE), (good, QUALIFIED)]
        elif kind == "request_sample" and now == UNTOUCHED:
            pairs = [(poor, SHOWN_POOR), (good + late, SAMPLED)]
        elif kind == "request_sample" and now == QUOTED:
            pairs = [(poor, SHOWN_POOR), (good, QUALIFIED)]
        else:
            pairs = [(1.0, now)]
        return tuple((p, to(state)) for p, state in pairs if p > 1e-15)

    def status_of(self, state: Mapping[str, Any]) -> tuple[str, ...]:
        offers, samples = state["offers"], state["quality_evidence"]
        latest = state["latest_offer_by_supplier"]
        status = []
        for sid in self.ids:
            quoted, sampled = sid in latest, sid in samples
            late = quoted and float(offers[latest[sid]]["on_time_probability"]) < BAD_BELOW
            poor = sampled and float(samples[sid]["verified_yield_rate"]) < BAD_BELOW
            status.append(SHOWN_LATE if late else SHOWN_POOR if poor else QUALIFIED if quoted and sampled
                          else QUOTED if quoted else SAMPLED if sampled else UNTOUCHED)
        return tuple(status)

    # --- stopping, as the one-step rule sees it ------------------------------------

    def stop_value(self, status: tuple[str, ...], day: int) -> float:
        """The best way to stop testing newcomers: award a qualified supplier, qualify the recorded one, or walk away."""
        best = max(self.defer_value, self.best_award(status, day)[0])
        for base in self.established:
            state = status[base]
            if state == QUALIFIED:
                continue
            fee = (self.quote[0] if state in (UNTOUCHED, SAMPLED) else 0.0) + (self.sample[base][0] if state in (UNTOUCHED, QUOTED) else 0.0)
            best = max(best, -fee + self.award(base, day + days_to_qualify(self, status, base))[0])
        return best

    def test_then_stop(self, status: tuple[str, ...], day: int, supplier: int) -> float:
        """Finish testing ``supplier`` (quote, then sample, as still needed), then stop the best way."""
        state = status[supplier]
        if state in BAD_STATES or state == QUALIFIED:
            return self.stop_value(status, day)
        kind = "request_quote" if state in (UNTOUCHED, SAMPLED) else "request_sample"
        fee, days = self.cost(kind, supplier)
        total = -fee
        for p, nxt in self.outcomes(status, kind, supplier):
            total += p * self.test_then_stop(nxt, day + days, supplier)
        return total


# --- rules a buyer might follow ---------------------------------------------------


def is_bad(state: str) -> bool:
    return state in BAD_STATES


def days_to_qualify(ref: Reference, status: Sequence[str], supplier: int) -> int:
    state = status[supplier]
    return (ref.quote[1] if state in (UNTOUCHED, SAMPLED) else 0) + (ref.sample[supplier][1] if state in (UNTOUCHED, QUOTED) else 0)


def _qualify(ref: Reference, status: Sequence[str], supplier: int, day: int) -> tuple[Any, ...] | None:
    state = status[supplier]
    if is_bad(state) or day + days_to_qualify(ref, status, supplier) + ref.lead[supplier] > ref.deadline:
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


def _stop_action(ref: Reference, status: tuple[str, ...], day: int) -> tuple[Any, ...]:
    """The first action of the best way to stop."""
    award_value, supplier, quantity = ref.best_award(status, day)
    target = ref.stop_value(status, day)
    if supplier is not None and award_value >= target - 1e-9:
        return ("submit_award", supplier, quantity)
    for base in ref.established:
        step = _qualify(ref, status, base, day)
        if step is not None and step[0] != "submit_award":
            return step
    return ("defer",)


def one_step_value(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """Look one test ahead with the posterior: finish testing one newcomer and stop, or stop now.

    For each newcomer not yet settled, the value of finishing its test (a quote
    and a sample, as still needed) and then stopping the best way, priced
    exactly with what everything seen so far says about its type; the rule
    takes the first step of the best such test if it beats stopping now, and
    otherwise stops: awards the best qualified supplier or qualifies the
    recorded one. It updates its beliefs after every result, so it sees what
    one newcomer's result says about the others when it comes to them.
    """
    stop = ref.stop_value(status, day)
    best: tuple[float, int | None] = (stop + 1e-9, None)
    for supplier in ref.newcomers:
        state = status[supplier]
        if is_bad(state) or state == QUALIFIED:
            continue
        value = ref.test_then_stop(status, day, supplier)
        if value > best[0]:
            best = (value, supplier)
    if best[1] is not None:
        state = status[best[1]]
        return ("request_quote", best[1]) if state in (UNTOUCHED, SAMPLED) else ("request_sample", best[1])
    return _stop_action(ref, status, day)


def one_step_marginal(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """Version 1's one-step comparison, which reads each newcomer's stated shares and ignores the shared source."""
    shadow = tuple(_INDEPENDENT_BAD if is_bad(s) else s for s in status)
    return _independent_one_step(ref, shadow, actions_left, day) or _fall_back(ref, status, day)


def cheapest_sample_first(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """A shortcut that ignores kinds: sample the newcomer whose sample is cheapest before anything else, then look one test ahead.

    In a world admitted because a cheap sample is worth taking for what it says
    about another listing, the cheapest sample is often that probe. If this rule
    matched the best policy the pack would reward a habit, not the inference.
    """
    if all(status[i] == UNTOUCHED for i in ref.newcomers):
        cheapest = min(ref.newcomers, key=lambda i: (ref.sample[i][0], ref.price[i], ref.ids[i]))
        if day + days_to_qualify(ref, status, cheapest) + ref.lead[cheapest] <= ref.deadline:
            return ("request_sample", cheapest)
    return one_step_value(ref, status, actions_left, day)


def two_step_value(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """A diagnostic, not an admission rule: look two newcomer tests ahead, then stop the best way."""

    def finish(st: tuple[str, ...], d: int, i: int, used: int) -> float:
        state = st[i]
        if is_bad(state) or state == QUALIFIED:
            return after(st, d, used)
        kind = "request_quote" if state in (UNTOUCHED, SAMPLED) else "request_sample"
        fee, days = ref.cost(kind, i)
        return -fee + sum(p * finish(nxt, d + days, i, used) for p, nxt in ref.outcomes(st, kind, i))

    def after(st: tuple[str, ...], d: int, used: int) -> float:
        best = ref.stop_value(st, d)
        if used < 2:
            for j in ref.newcomers:
                if not is_bad(st[j]) and st[j] != QUALIFIED:
                    best = max(best, finish(st, d, j, used + 1))
        return best

    stop = ref.stop_value(status, day)
    best: tuple[float, int | None] = (stop + 1e-9, None)
    for supplier in ref.newcomers:
        if is_bad(status[supplier]) or status[supplier] == QUALIFIED:
            continue
        value = finish(status, day, supplier, 1)
        if value > best[0]:
            best = (value, supplier)
    if best[1] is not None:
        state = status[best[1]]
        return ("request_quote", best[1]) if state in (UNTOUCHED, SAMPLED) else ("request_sample", best[1])
    return _stop_action(ref, status, day)


def one_step_any_order(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """A diagnostic: ``one_step_value`` free to start a test with the sample rather than the quote."""

    def finish(st: tuple[str, ...], d: int, i: int, first: str) -> float:
        state = st[i]
        if is_bad(state) or state == QUALIFIED:
            return ref.stop_value(st, d)
        kind = first if state == UNTOUCHED else "request_quote" if state == SAMPLED else "request_sample"
        fee, days = ref.cost(kind, i)
        return -fee + sum(p * finish(nxt, d + days, i, first) for p, nxt in ref.outcomes(st, kind, i))

    best: tuple[float, tuple[Any, ...] | None] = (ref.stop_value(status, day) + 1e-9, None)
    for supplier in ref.newcomers:
        state = status[supplier]
        if is_bad(state) or state == QUALIFIED:
            continue
        for first in ("request_quote", "request_sample"):
            value = finish(status, day, supplier, first)
            if value > best[0]:
                kind = first if state == UNTOUCHED else "request_quote" if state == SAMPLED else "request_sample"
                best = (value, (kind, supplier))
    return best[1] if best[1] is not None else _stop_action(ref, status, day)


def probe_same_kind_first(ref: Reference, status: tuple[str, ...], actions_left: int, day: int) -> tuple[Any, ...]:
    """A diagnostic that writes the inference down as a habit: before anything else, sample the newcomer
    with the cheapest sample among those of a kind that has a dearer one, then look one test ahead."""
    if all(status[i] == UNTOUCHED for i in ref.newcomers):
        probes = []
        for members in ref.groups:
            if len(members) < 2:
                continue
            cheapest = min(members, key=lambda i: (ref.sample[i][0], ref.price[i], ref.ids[i]))
            if any(ref.sample[i][0] > ref.sample[cheapest][0] for i in members if i != cheapest):
                probes.append(cheapest)
        if probes:
            probe = min(probes, key=lambda i: (ref.sample[i][0], ref.price[i], ref.ids[i]))
            if day + ref.sample[probe][1] <= ref.deadline:
                return ("request_sample", probe)
    return one_step_value(ref, status, actions_left, day)


RULES: dict[str, Rule] = {
    "pay_premium": pay_premium,
    "cheapest_first_once": test_once(cheapest_newcomer),
    "best_odds_first_once": test_once(best_odds_newcomer),
    "cheapest_until_found": cheapest_until_found,
    "one_step_value": one_step_value,
    "one_step_marginal": one_step_marginal,
    "cheapest_sample_first": cheapest_sample_first,
    "two_step_value": two_step_value,
    "one_step_any_order": one_step_any_order,
    "probe_same_kind_first": probe_same_kind_first,
}
#: The rules a world must defeat by the admission margin: every fixed rule and both one-step rules.
FIXED_RULES = ("pay_premium", "cheapest_first_once", "best_odds_first_once", "cheapest_until_found")
LOOKAHEAD_RULES = ("one_step_value", "one_step_marginal")
#: A shortcut the admission also screens against: it reads the generator, not the shared source.
SHORTCUT_RULES = ("cheapest_sample_first",)
#: Reported, not screened: how far ahead a buyer has to look, whether the order inside a test explains the
#: one-step rule's shortfall, and how far a habit that writes the inference down gets.
DIAGNOSTIC_RULES = ("two_step_value", "one_step_any_order", "probe_same_kind_first")


# --- playing and pricing a trajectory ------------------------------------------------


def score_actions(payload: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Version 1's ``score_actions`` with the version 2 reference: each action priced against the best one available."""
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
    "BAD_STATES", "DIAGNOSTIC_RULES", "FIXED_RULES", "LOOKAHEAD_RULES", "RULES", "Reference", "SHORTCUT_RULES",
    "SHOWN_LATE", "SHOWN_POOR", "SOURCING_FIELD", "best_odds_newcomer", "cheapest_newcomer", "cheapest_sample_first",
    "cheapest_until_found", "days_to_qualify", "final_margin", "is_bad", "one_step_any_order", "one_step_marginal",
    "one_step_value", "pay_premium", "play", "probe_same_kind_first", "run", "same_source_probability",
    "score_actions", "test_once", "two_step_value",
]
