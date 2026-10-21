"""Pay or test, version 3: the best informed policy with unanswered quotes and a source lookup.

Version 2's reference (``pay_or_test_v2_reference.Reference``, subclassed here, not edited) values every world exactly
by backward induction over what the buyer has learned. Version 3's environment (``pay_or_test_v3_environment``) adds
two things the buyer can meet, and the reference adds them as chance nodes:

- **An unanswered quote.** A quote request to a newcomer is answered with the stated probability; if not, the buyer
  has spent the fee, a day and an action, and knows nothing more. The recorded supplier always answers.
- **A source lookup.** Looking up one newcomer's registered factory says nothing by itself. Looking up a second of the
  same kind settles whether the kind shares a source: the same factory if it does, different ones if not. Its chance
  is read from the joint prior conditioned on everything seen, so a lookup is worth taking only for what it says
  about other listings.

What the buyer knows is a ``Seen``: version 2's per-supplier states as a tuple (so every inherited method reads it
unchanged), plus which listings it has looked up and, per kind, whether a shared source is settled. The joint prior
keeps each kind's sharing as its own variable, so a lookup and a test result condition the same posterior.

The rules a world must defeat are version 2's, rewritten where they look ahead so that each retry of an unanswered
quote spends an action (the inherited one-step rule would otherwise retry forever). Version 1's one-step comparison,
which ignores the shared source, is not carried over: in version 3 it reads a state it was not written for.
"""

from __future__ import annotations

import itertools
from typing import Any, Callable, Mapping, Sequence

from .environment import evaluate_award
from .pay_or_test_reference import QUALIFIED, QUOTED, SAMPLED, UNTOUCHED, _complete, _step
from .pay_or_test_v2_reference import (
    BAD_STATES, SHOWN_LATE, SHOWN_POOR, TYPES, _ALLOWS, _fall_back, _qualify, best_odds_newcomer, cheapest_newcomer,
    cheapest_until_found, days_to_qualify, is_bad, pay_premium, test_once,
)
from .pay_or_test_v2_reference import Reference as _V2Reference
from .pay_or_test_v3_environment import PayOrTestV3Plugin, SOURCE_FIELD, validate_v3_payload, version1_view

LOOKUP = "look_up_source"
REQUESTS = ("request_quote", "request_sample", LOOKUP)
UNKNOWN, SHARED, SEPARATE, SINGLE = "unknown", "shared", "separate", "single"

Rule = Callable[["Reference", "Seen", int, int], tuple[Any, ...]]


class Seen(tuple):
    """Per-supplier states (a tuple, as version 2 reads them), the listings looked up, and each kind's settled sharing."""

    def __new__(cls, statuses: Sequence[str], looked: frozenset[int] = frozenset(), sharing: Sequence[str] = ()):
        seen = super().__new__(cls, statuses)
        seen.looked = frozenset(looked)
        seen.sharing = tuple(sharing)
        seen._key = (tuple(statuses), seen.looked, seen.sharing)
        seen._hash = hash(seen._key)
        return seen

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Seen) and self._key == other._key

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __reduce__(self):
        return (Seen, (tuple(self), self.looked, self.sharing))

    def with_state(self, supplier: int, state: str) -> "Seen":
        return Seen(tuple(state if i == supplier else s for i, s in enumerate(self)), self.looked, self.sharing)

    def with_lookup(self, supplier: int, group: int | None = None, settled: str | None = None) -> "Seen":
        sharing = list(self.sharing)
        if group is not None and settled is not None:
            sharing[group] = settled
        return Seen(tuple(self), self.looked | {supplier}, sharing)


class Reference(_V2Reference):
    """Values and best actions for one version 3 world."""

    def __init__(self, payload: Mapping[str, Any]):
        super().__init__(version1_view(payload))
        self.case = validate_v3_payload(payload)
        self.plugin = PayOrTestV3Plugin()
        interaction = self.case["interaction"]
        self.answer = float(self.case["policy"]["newcomer_quote_answer_probability"])
        self.lookup = (float(interaction["source_lookup_cost_usd"]), int(interaction["source_lookup_days"]))
        self.wasted = {"check_award": (0.0, 0)}
        self.group_of = {i: g for g, members in enumerate(self.groups) for i in members}
        self.v3_profiles = self._joint_prior_v3()
        self._belief3: dict[Any, tuple[float, ...]] = {}
        self._odds3: dict[Any, tuple[float, float, float]] = {}
        self._shared3: dict[Any, float] = {}
        self._outcomes3: dict[Any, tuple[tuple[float, Seen], ...]] = {}
        self._test: dict[Any, float] = {}
        self._stop: dict[Any, float] = {}

    # --- the joint prior, with each kind's sharing as its own variable ----------------

    def _joint_prior_v3(self) -> tuple[tuple[dict[int, str], tuple[str, ...], float], ...]:
        by_group = []
        for members in self.groups:
            good, late, poor = self.prior[members[0]]
            share = {"good": good, "late": late, "poor": poor}
            share = {t: share[t] for t in TYPES}
            rows = []
            if len(members) == 1:
                rows = [({members[0]: t}, SINGLE, share[t]) for t in TYPES if share[t] > 0.0]
            else:
                rows += [({i: t for i in members}, SHARED, self.rho * share[t]) for t in TYPES if share[t] > 0.0]
                for types in itertools.product(TYPES, repeat=len(members)):
                    weight = 1.0
                    for t in types:
                        weight *= share[t]
                    if weight > 0.0 and self.rho < 1.0:
                        rows.append((dict(zip(members, types)), SEPARATE, (1.0 - self.rho) * weight))
            by_group.append(rows)
        joint = []
        for combo in itertools.product(*by_group):
            assignment: dict[int, str] = {}
            weight = 1.0
            for part, _, w in combo:
                assignment.update(part)
                weight *= w
            joint.append((assignment, tuple(s for _, s, _ in combo), weight))
        return tuple(joint)

    def start(self) -> tuple[Seen, int, int]:
        sharing = tuple(SINGLE if len(m) == 1 else UNKNOWN for m in self.groups)
        return (Seen(tuple(UNTOUCHED for _ in self.ids), frozenset(), sharing), self.max_actions, 0)

    def _belief_key(self, seen: Seen) -> tuple[Any, ...]:
        return (tuple(seen[i] for i in self.newcomers), seen.sharing)

    def belief(self, seen: Seen) -> tuple[float, ...]:  # type: ignore[override]
        key = self._belief_key(seen)
        if key not in self._belief3:
            weights = []
            for assignment, sharing, weight in self.v3_profiles:
                fits = all(assignment[i] in _ALLOWS[seen[i]] for i in self.newcomers) and all(
                    known in (UNKNOWN, SINGLE) or known == actual for known, actual in zip(seen.sharing, sharing))
                weights.append(weight if fits else 0.0)
            total = sum(weights)
            self._belief3[key] = tuple(w / total for w in weights) if total > 0 else tuple(weights)
        return self._belief3[key]

    def type_odds(self, seen: Seen, supplier: int) -> tuple[float, float, float]:  # type: ignore[override]
        if supplier not in self.newcomers:
            return (1.0, 0.0, 0.0)
        key = (self._belief_key(seen), supplier)
        if key not in self._odds3:
            odds = {t: 0.0 for t in TYPES}
            for (assignment, _, _), w in zip(self.v3_profiles, self.belief(seen)):
                odds[assignment[supplier]] += w
            self._odds3[key] = (odds["good"], odds["late"], odds["poor"])
        return self._odds3[key]

    def shared_odds(self, seen: Seen, group: int) -> float:
        """The chance that kind ``group``'s newcomers share a source, given everything seen."""
        key = (self._belief_key(seen), group)
        if key not in self._shared3:
            self._shared3[key] = sum(w for (_, sharing, _), w in zip(self.v3_profiles, self.belief(seen))
                                     if sharing[group] == SHARED)
        return self._shared3[key]

    # --- what a request can show --------------------------------------------------------

    def outcomes(self, seen: Seen, kind: str, supplier: int) -> tuple[tuple[float, Seen], ...]:  # type: ignore[override]
        key = (seen, kind, supplier)
        if key not in self._outcomes3:
            self._outcomes3[key] = self._outcomes_v3(seen, kind, supplier)
        return self._outcomes3[key]

    def _outcomes_v3(self, seen: Seen, kind: str, supplier: int) -> tuple[tuple[float, Seen], ...]:
        if kind == LOOKUP:
            return self._lookup_outcomes(seen, supplier)
        good, late, poor = self.type_odds(seen, supplier)
        now = seen[supplier]
        if kind == "request_quote" and now == UNTOUCHED:
            pairs = [(late, SHOWN_LATE), (good + poor, QUOTED)]
        elif kind == "request_quote" and now == SAMPLED:
            pairs = [(late, SHOWN_LATE), (good, QUALIFIED)]
        elif kind == "request_sample" and now == UNTOUCHED:
            pairs = [(poor, SHOWN_POOR), (good + late, SAMPLED)]
        elif kind == "request_sample" and now == QUOTED:
            pairs = [(poor, SHOWN_POOR), (good, QUALIFIED)]
        else:
            return ((1.0, seen),)
        answer = self.answer if kind == "request_quote" and supplier in self.newcomers else 1.0
        found = [(answer * p, seen.with_state(supplier, state)) for p, state in pairs if answer * p > 1e-15]
        if answer < 1.0:
            found.append((1.0 - answer, seen))
        return tuple(found)

    def _lookup_outcomes(self, seen: Seen, supplier: int) -> tuple[tuple[float, Seen], ...]:
        group = self.group_of.get(supplier)
        if group is None or supplier in seen.looked or seen.sharing[group] != UNKNOWN:
            return ((1.0, seen),)
        if not any(i in seen.looked for i in self.groups[group]):
            return ((1.0, seen.with_lookup(supplier)),)
        shared = self.shared_odds(seen, group)
        found = [(shared, seen.with_lookup(supplier, group, SHARED)),
                 (1.0 - shared, seen.with_lookup(supplier, group, SEPARATE))]
        return tuple((p, s) for p, s in found if p > 1e-15)

    def cost(self, kind: str, supplier: int | None) -> tuple[float, int]:
        if kind == LOOKUP:
            return self.lookup
        return super().cost(kind, supplier)

    def lookup_informs(self, seen: Seen, supplier: int) -> bool:
        """Whether looking up ``supplier`` can still move a belief: its kind's sharing is open, and not settled by tests."""
        group = self.group_of.get(supplier)
        if group is None or supplier in seen.looked or seen.sharing[group] != UNKNOWN:
            return False
        shared = self.shared_odds(seen, group)
        return 1e-12 < shared < 1.0 - 1e-12

    def requests(self, seen: Seen) -> tuple[tuple[str, int], ...]:  # type: ignore[override]
        found = list(super().requests(seen))
        found += [(LOOKUP, i) for i in self.newcomers if self.lookup_informs(seen, i)]
        return tuple(found)

    def request_value(self, seen: Seen, actions_left: int, day: int, kind: str, supplier: int | None) -> float:  # type: ignore[override]
        fee, days = self.cost(kind, supplier)
        if kind in REQUESTS:
            return -fee + sum(p * self.value(nxt, actions_left - 1, day + days) for p, nxt in self.outcomes(seen, kind, supplier))
        return -fee + self.value(seen, actions_left - 1, day + days)

    # --- reading the environment's state -------------------------------------------------

    def status_of(self, state: Mapping[str, Any]) -> Seen:  # type: ignore[override]
        statuses = super().status_of(state)
        records = state.get("source_records") or {}
        looked = frozenset(self.index[sid] for sid in records if self.index.get(sid) in self.group_of)
        sharing = []
        for g, members in enumerate(self.groups):
            named = {records[self.ids[i]]["source_factory"] for i in members if self.ids[i] in records}
            if len(members) == 1:
                sharing.append(SINGLE)
            elif sum(self.ids[i] in records for i in members) < 2:
                sharing.append(UNKNOWN)
            else:
                sharing.append(SHARED if len(named) == 1 else SEPARATE)
        return Seen(statuses, looked, sharing)

    def wire(self, action: tuple[Any, ...], state: Mapping[str, Any]) -> dict[str, Any]:
        if action[0] == LOOKUP:
            return {"action": LOOKUP, "supplier_id": self.ids[action[1]]}
        return super().wire(action, state)

    # --- stopping and finishing one test, with the action budget counted --------------------

    def stop_value(self, seen: Seen, day: int, actions_left: int | None = None) -> float:  # type: ignore[override]
        """The best way to stop testing newcomers, within the actions left: award, qualify the recorded one, or walk."""
        left = self.max_actions if actions_left is None else actions_left
        key = (seen, min(day, self.day_cap), left)
        if key not in self._stop:
            best = self.defer_value
            if left >= 1:
                best = max(best, self.best_award(seen, day)[0])
            for base in self.established:
                state = seen[base]
                if state == QUALIFIED:
                    continue
                need = (state in (UNTOUCHED, SAMPLED)) + (state in (UNTOUCHED, QUOTED)) + 1
                if left < need:
                    continue
                fee = (self.quote[0] if state in (UNTOUCHED, SAMPLED) else 0.0) + (
                    self.sample[base][0] if state in (UNTOUCHED, QUOTED) else 0.0)
                best = max(best, -fee + self.award(base, day + days_to_qualify(self, seen, base))[0])
            self._stop[key] = best
        return self._stop[key]

    def test_steps(self, seen: Seen, allowed: frozenset[int]) -> tuple[tuple[str, int], ...]:
        """The quote and sample requests that can still show something about the newcomers in ``allowed``."""
        found = []
        for i in sorted(allowed):
            state = seen[i]
            if state in (UNTOUCHED, SAMPLED):
                found.append(("request_quote", i))
            if state in (UNTOUCHED, QUOTED):
                found.append(("request_sample", i))
        return tuple(found)

    def restricted_value(self, seen: Seen, actions_left: int, day: int, allowed: frozenset[int]) -> float:
        """The best policy that may test only the newcomers in ``allowed``, and may stop at any point.

        With one newcomer allowed, this plans that newcomer's whole test: which request first, how often to retry an
        unanswered quote, and when to give up for the recorded supplier. What it cannot see is a test of another
        listing, so it misses exactly what a test is worth for what it says about someone else.
        """
        if actions_left <= 0:
            return self.defer_value
        day = min(day, self.day_cap)
        key = (seen, actions_left, day, allowed)
        if key not in self._test:
            best = self.stop_value(seen, day, actions_left)
            if actions_left > 1 and day < self.day_cap:
                for kind, supplier in self.test_steps(seen, allowed):
                    best = max(best, self.restricted_step_value(seen, actions_left, day, allowed, kind, supplier))
            self._test[key] = best
        return self._test[key]

    def restricted_step_value(self, seen: Seen, actions_left: int, day: int, allowed: frozenset[int], kind: str,
                              supplier: int) -> float:
        fee, days = self.cost(kind, supplier)
        return -fee + sum(p * self.restricted_value(nxt, actions_left - 1, day + days, allowed)
                          for p, nxt in self.outcomes(seen, kind, supplier))


# --- rules a buyer might follow ---------------------------------------------------------


def _stop_action(ref: Reference, seen: Seen, actions_left: int, day: int) -> tuple[Any, ...]:
    award_value, supplier, quantity = ref.best_award(seen, day)
    if supplier is not None and award_value >= ref.stop_value(seen, day, actions_left) - 1e-9:
        return ("submit_award", supplier, quantity)
    for base in ref.established:
        step = _qualify(ref, seen, base, day)
        if step is not None and step[0] != "submit_award":
            return step
    return ("defer",)


def _restricted_rule(ref: Reference, seen: Seen, actions_left: int, day: int,
                     candidates: Sequence[frozenset[int]]) -> tuple[Any, ...]:
    """The first step of the best policy restricted to one of ``candidates`` (sets of newcomers), or stop."""
    best: tuple[float, tuple[str, int] | None] = (ref.stop_value(seen, day, actions_left) + 1e-9, None)
    if actions_left > 1 and min(day, ref.day_cap) < ref.day_cap:
        for allowed in candidates:
            for kind, supplier in ref.test_steps(seen, allowed):
                value = ref.restricted_step_value(seen, actions_left, day, allowed, kind, supplier)
                if value > best[0]:
                    best = (value, (kind, supplier))
    if best[1] is not None:
        return best[1]
    return _stop_action(ref, seen, actions_left, day)


def _open(ref: Reference, seen: Seen) -> tuple[int, ...]:
    return tuple(i for i in ref.newcomers if not is_bad(seen[i]) and seen[i] != QUALIFIED)


def one_step_value(ref: Reference, seen: Seen, actions_left: int, day: int) -> tuple[Any, ...]:
    """Look one newcomer ahead: the best plan that tests only one newcomer, re-chosen after every result.

    Version 2's one-step rule priced finishing a newcomer's test as a fixed sequence. With quotes that may go
    unanswered, that commitment undervalues every test (incident row P-D-28), so here the rule plans the whole of one
    newcomer's test exactly (which request first, how often to retry, when to give up for the recorded supplier) and
    takes the first step of the best such plan if it beats stopping. It updates its odds after every result, so it
    sees what one newcomer's result says about the others when it comes to them; it never takes a test, or a lookup,
    for what it will say about another listing.
    """
    return _restricted_rule(ref, seen, actions_left, day, [frozenset({i}) for i in _open(ref, seen)])


def two_step_value(ref: Reference, seen: Seen, actions_left: int, day: int) -> tuple[Any, ...]:
    """A diagnostic: the best plan that tests at most two newcomers (no lookups), re-chosen after every result."""
    open_ = _open(ref, seen)
    pairs = [frozenset(pair) for pair in itertools.combinations(open_, 2)] or [frozenset({i}) for i in open_]
    return _restricted_rule(ref, seen, actions_left, day, pairs)


def cheapest_sample_first(ref: Reference, seen: Seen, actions_left: int, day: int) -> tuple[Any, ...]:
    """Version 2's kind-blind shortcut: sample the cheapest sample before anything else, then look one test ahead."""
    if all(seen[i] == UNTOUCHED for i in ref.newcomers):
        cheapest = min(ref.newcomers, key=lambda i: (ref.sample[i][0], ref.price[i], ref.ids[i]))
        if day + days_to_qualify(ref, seen, cheapest) + ref.lead[cheapest] <= ref.deadline:
            return ("request_sample", cheapest)
    return one_step_value(ref, seen, actions_left, day)


def look_up_first(ref: Reference, seen: Seen, actions_left: int, day: int) -> tuple[Any, ...]:
    """A diagnostic habit: look up every newcomer of a kind with two or more until each kind's sharing is settled, then
    look one test ahead. If it matched the best policy, the lookup would be a habit, not an inference."""
    for supplier in ref.newcomers:
        if ref.lookup_informs(seen, supplier):
            return (LOOKUP, supplier)
    return one_step_value(ref, seen, actions_left, day)


def probe_same_kind_first(ref: Reference, seen: Seen, actions_left: int, day: int) -> tuple[Any, ...]:
    """Version 2's diagnostic habit: sample the cheapest sample of a kind that has a dearer one, then one test ahead."""
    if all(seen[i] == UNTOUCHED for i in ref.newcomers):
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
    return one_step_value(ref, seen, actions_left, day)


RULES: dict[str, Rule] = {
    "pay_premium": pay_premium,
    "cheapest_first_once": test_once(cheapest_newcomer),
    "best_odds_first_once": test_once(best_odds_newcomer),
    "cheapest_until_found": cheapest_until_found,
    "one_step_value": one_step_value,
    "cheapest_sample_first": cheapest_sample_first,
    "two_step_value": two_step_value,
    "probe_same_kind_first": probe_same_kind_first,
    "look_up_first": look_up_first,
}
FIXED_RULES = ("pay_premium", "cheapest_first_once", "best_odds_first_once", "cheapest_until_found")
LOOKAHEAD_RULES = ("one_step_value",)
SHORTCUT_RULES = ("cheapest_sample_first",)
DIAGNOSTIC_RULES = ("two_step_value", "probe_same_kind_first", "look_up_first")


# --- playing and pricing a trajectory -----------------------------------------------------


def describe(ref: Reference, action: tuple[Any, ...]) -> str:
    if action[0] in REQUESTS:
        return f"{action[0]} {ref.ids[action[1]]}"
    if action[0] == "submit_award":
        return f"submit_award {ref.ids[action[1]]} x{action[2]}"
    return "defer"


def score_actions(payload: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Each action priced against the best one available at its state (version 2's ``score_actions`` for version 3)."""
    ref = Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    steps: list[dict[str, Any]] = []
    loss = {"requests": 0.0, "strays": 0.0, "walk_away": 0.0, "award_timing": 0.0, "award_terms": 0.0}
    for raw in actions:
        if state["done"]:
            break
        seen = ref.status_of(state)
        left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
        best = ref.value(seen, left, day)
        action = _complete(ref, raw)
        kind = action.get("action")
        nxt, valid = _step(ref, state, action)
        row: dict[str, Any] = {"action": kind, "supplier_id": action.get("supplier_id"), "day": day, "actions_left": left,
                               "best_value_usd": round(best, 4), "best_action": describe(ref, ref.best_action(seen, left, day))}
        if kind == "request_quote" and valid:
            row["answered"] = ref.ids.index(action["supplier_id"]) in ref.established or action["supplier_id"] in nxt["latest_offer_by_supplier"]
        if not valid or kind == "defer":
            taken, part = ref.defer_value, "walk_away"
        elif kind == "submit_award":
            result = evaluate_award(ref.case, award_lines=action["award_lines"], offers=state["offers"],
                                    quality_evidence=state["quality_evidence"], elapsed_days=day, information_cost_usd=0.0)
            taken = float(result["contribution_margin_usd"]) if result["feasible"] else ref.defer_value
            best_now = ref.best_award(seen, day)[0]
            loss["award_timing"] += max(0.0, best - best_now)
            loss["award_terms"] += best_now - taken
            part = None
        else:
            supplier = ref.index.get(action.get("supplier_id")) if kind in REQUESTS else None
            taken = ref.request_value(seen, left, day, kind, supplier)
            part = "requests" if kind in REQUESTS else "strays"
        if part:
            loss[part] += best - taken
        row["value_taken_usd"], row["loss_usd"], row["valid"] = round(taken, 4), round(best - taken, 4), valid
        steps.append(row)
        state = nxt
    terminal = ref.plugin.terminal(ref.case, state)
    outcome = ref.plugin.outcome(ref.case, terminal) if terminal is not None else None
    newcomer_ids = {ref.ids[i] for i in ref.newcomers}
    return {
        "steps": steps,
        "decision_loss_usd": round(sum(loss.values()), 4),
        "loss_by_part_usd": {k: round(v, 4) for k, v in loss.items()},
        "best_policy_value_usd": round(ref.value(*ref.start()), 4),
        "first_target": steps[0]["supplier_id"] if steps else None,
        "requests": sum(s["action"] in REQUESTS for s in steps),
        "lookups": sum(s["action"] == LOOKUP for s in steps),
        "newcomers_touched": len({s["supplier_id"] for s in steps if s["supplier_id"] in newcomer_ids}),
        "outcome": outcome,
    }


def play(payload: Mapping[str, Any], rule: Rule | None = None) -> list[dict[str, Any]]:
    """The wire actions a rule (default: the best policy) takes on a world as it really is."""
    ref = Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    actions: list[dict[str, Any]] = []
    while not state["done"]:
        seen = ref.status_of(state)
        left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
        choice = ref.best_action(seen, left, day) if rule is None else rule(ref, seen, left, day)
        if choice[0] == "submit_award" and seen[choice[1]] != QUALIFIED:
            choice = ("defer",)
        action = ref.wire(choice, state)
        actions.append(action)
        state, _ = _step(ref, state, action)
    return actions


def run(payload: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Play wire actions through the version 3 environment and return its final state."""
    ref = Reference(payload)
    state = ref.plugin.initial_state(ref.case, None)
    for action in actions:
        if state["done"]:
            break
        state, _ = _step(ref, state, _complete(ref, action))
    return state


__all__ = [
    "DIAGNOSTIC_RULES", "FIXED_RULES", "LOOKAHEAD_RULES", "LOOKUP", "REQUESTS", "RULES", "Reference", "SHORTCUT_RULES",
    "SOURCE_FIELD", "Seen", "cheapest_sample_first", "describe", "look_up_first", "one_step_value", "play",
    "probe_same_kind_first", "run", "score_actions", "two_step_value",
]
