"""Offline buyer policies whose decisions receive only public observations."""

from __future__ import annotations
import copy
import itertools
import math
from aeread.shared_runner.task.scheduler import ActionEnvelope
from .phase2_environment import Phase2Plugin


def market_impossibility(observation):
    o = observation["objective"]
    floors = observation["policy"]["market_constraints"]
    if floors["minimum_delivery_days"] > o["deadline_days"]:
        return "certified market delivery floor exceeds the deadline"
    # Even perfect yield, zero shipping and free research cannot meet the budget.
    if (
        floors["minimum_unit_price_usd"]
        * o["minimum_service_kits"]
        * sum(o["bom"].values())
        > o["cash_budget_usd"]
    ):
        return "certified market price floor exceeds the service cash budget"
    return None


def best_public_award(observation, *, prospective=None):
    """Enumerate acquired offers, using sample estimates rather than hidden truth.

    Prospect estimates use a declared 25% listing-price contingency, a two-day
    lead buffer and $0.05/unit shipping prior, not the generator pricing formula.
    This intentionally shares neither the terminal evaluator nor private terms.
    v1 has no duty, refunds, or financing (enforced by the plugin).
    """
    o = observation["objective"]
    choices = []
    for offer in observation["formal_offers"].values():
        sample = observation["verified_samples"].get(offer["supplier_id"])
        if (
            sample is None
            or sample["variant_id"] != offer["variant_id"]
            or offer["variant_id"]
            != observation["policy"]["required_variant_by_component"][
                offer["component"]
            ]
            or offer["expires_day"] < observation["elapsed_days"]
        ):
            continue
        choices.append((offer, float(sample["observed_yield_rate"])))
    if prospective is not None:
        s = prospective
        l = s["listing"]
        offer = dict(
            offer_id="prospect",
            supplier_id=s["supplier_id"],
            component=s["component"],
            unit_price_usd=l["displayed_unit_price_usd"] * 1.25,
            shipping_per_unit_usd=0.05,
            moq=l["advertised_moq"],
            capacity=l["advertised_capacity"],
            order_step=l["advertised_capacity"],
            lead_time_days=l["claimed_lead_time_days"] + 2,
            on_time_probability=1.0,
        )
        choices.append((offer, float(l["historical_yield_estimate"])))
    best, lines = float(o["defer_value_usd"]) - observation["information_cost_usd"], []
    for mask in itertools.product((False, True), repeat=len(choices)):
        selected = [item for item, take in zip(choices, mask) if take]
        if not selected or len({a["supplier_id"] for a, _ in selected}) != len(
            selected
        ):
            continue
        units = {c: 0.0 for c in o["bom"]}
        cost = float(observation["information_cost_usd"])
        elapsed = observation["elapsed_days"] + (2 if prospective is not None else 0)
        for offer, quality in selected:
            quantity = offer["capacity"]
            units[offer["component"]] += (
                quantity * quality * offer["on_time_probability"]
                if elapsed + offer["lead_time_days"] <= o["deadline_days"]
                else 0.0
            )
            cost += quantity * (
                offer["unit_price_usd"] + offer["shipping_per_unit_usd"]
            )
        kits = min(
            o["target_kits"],
            math.floor(min(units[c] / n for c, n in o["bom"].items()) + 1e-12),
        )
        if kits < o["minimum_service_kits"] or cost > o["cash_budget_usd"]:
            continue
        value = (
            kits * o["revenue_per_completed_kit_usd"]
            - cost
            - (o["target_kits"] - kits) * o["shortfall_penalty_per_kit_usd"]
        )
        if value > best + 1e-9:
            best, lines = value, [
                {"offer_id": a["offer_id"], "quantity": a["capacity"]}
                for a, _ in selected
            ]
    return best, lines


def normalize_observation(observation):
    observation = copy.deepcopy(observation)
    if isinstance(observation["formal_offers"], list):
        observation["formal_offers"] = {
            o["offer_id"]: o for o in observation["formal_offers"]
        }
        observation["verified_samples"] = {
            s["supplier_id"]: s for s in observation["verified_samples"]
        }
        bom = observation["objective"]["bom"]
        observation["policy"]["required_variant_by_component"] = {
            r["component"]: r["required_variant"] for r in bom
        }
        observation["objective"]["bom"] = {r["component"]: r["units"] for r in bom}
    return observation


def choose_action(observation, policy="best_qualified"):
    observation = normalize_observation(observation)
    if policy == "defer":
        return dict(action="defer", reason="immediate defer negative control")
    if policy == "always_buy":
        return dict(
            action="submit_award",
            award_lines=[dict(offer_id="unverified", quantity=20)],
        )
    if policy not in {"best_qualified", "greedy"}:
        raise ValueError("unknown public policy")
    suppliers = observation["supplier_listings"]
    offers = observation["formal_offers"]
    samples = observation["verified_samples"]
    if policy == "best_qualified":
        reason = market_impossibility(observation)
        if reason:
            return dict(action="defer", reason=reason)
    # Complete a chosen qualification before considering another prospect.
    for offer in offers.values():
        sid = offer["supplier_id"]
        if sid not in samples and observation["actions_left"] >= 2:
            return dict(
                action="request_sample",
                supplier_id=sid,
                message="Inspect the exact variant.",
            )
    value, lines = best_public_award(observation)
    known = {offer["supplier_id"] for offer in offers.values()}
    remaining = [s for s in suppliers if s["supplier_id"] not in known]
    if policy == "greedy":
        required = math.ceil(
            observation["objective"]["target_kits"]
            / min(s["listing"]["advertised_capacity"] for s in suppliers)
        )
        if len(known) >= required or observation["actions_left"] < 3:
            # This negative control buys its first advertised-capacity allocation.
            return dict(
                action="submit_award",
                award_lines=[
                    dict(offer_id=o["offer_id"], quantity=o["capacity"])
                    for o in offers.values()
                ],
            )
        next_supplier = min(
            remaining,
            key=lambda s: (s["listing"]["displayed_unit_price_usd"], s["supplier_id"]),
        )
    else:
        if not remaining or observation["actions_left"] < 3:
            return (
                dict(action="submit_award", award_lines=lines)
                if lines
                else dict(
                    action="defer", reason="no profitable qualified feasible allocation"
                )
            )
        ranked = []
        for s in remaining:
            estimate, prospective_lines = best_public_award(observation, prospective=s)
            research = (
                observation["research_terms"]["quote_cost_usd"]
                + s["listing"]["sample_cost_usd"]
            )
            # Incomplete split allocations have no current feasible award. Rank
            # initial prospects by uncapped expected batch contribution instead.
            partial = s["listing"]["historical_yield_estimate"] * s["listing"][
                "advertised_capacity"
            ] * observation["objective"]["revenue_per_completed_kit_usd"] - s[
                "listing"
            ][
                "advertised_capacity"
            ] * (
                s["listing"]["displayed_unit_price_usd"] * 1.25 + 0.05
            )
            score = estimate - research if prospective_lines else (-1e4 + partial)
            ranked.append((score, s["supplier_id"], s))
        potential, _, next_supplier = max(ranked, key=lambda x: (x[0], x[1]))
        if lines and potential <= value + 1e-9:
            return dict(action="submit_award", award_lines=lines)
    return dict(
        action="request_quote",
        supplier_id=next_supplier["supplier_id"],
        message="Issue a binding complete formal quote.",
    )


def replay_policy(payload, policy="best_qualified", *, supplier_order=None):
    payload = copy.deepcopy(payload)
    if supplier_order is not None:
        payload["suppliers"] = [payload["suppliers"][i] for i in supplier_order]
    plugin = Phase2Plugin()
    case = plugin.validate_payload(payload)
    phase = plugin.phases(case)[0]
    state = plugin.initial_state(case, None)
    trace = []
    while not state["done"]:
        observation = plugin.observe(case, state, "buyer", phase)
        action = choose_action(observation, policy)
        parsed = plugin.parse_action(case, state, "buyer", phase, action)
        if not parsed.ok:
            raise AssertionError(parsed)
        legal = plugin.legal(case, state, "buyer", phase, parsed.action)
        trace.append({"action": action, "observation": observation})
        state = plugin.step(
            case,
            state,
            phase,
            {
                "buyer": ActionEnvelope(
                    "buyer", legal.legal, parsed.action, parsed, legal
                )
            },
        ).state
    terminal = plugin.terminal(case, state)
    return {
        "outcome": plugin.outcome(case, terminal),
        "trace": trace,
        "terminal": terminal,
    }


def replay_best_qualified(payload):
    return replay_policy(payload)["outcome"]


def behavior_diagnostics(payload, actions):
    """Replay actions to attach observed samples to the next visible decision."""
    plugin = Phase2Plugin()
    phase = plugin.phases(payload)[0]
    state = plugin.initial_state(payload, None)
    initial = plugin.observe(payload, state, "buyer", phase)
    reference_first = choose_action(initial)
    parsed_actions = []
    observations = []
    for action in actions:
        parsed = plugin.parse_action(payload, state, "buyer", phase, action)
        if not parsed.ok or state["done"]:
            break
        legal = plugin.legal(payload, state, "buyer", phase, parsed.action)
        if not legal.legal:
            break
        parsed_actions.append(parsed.action)
        state = plugin.step(
            payload,
            state,
            phase,
            {"buyer": ActionEnvelope("buyer", True, parsed.action, parsed, legal)},
        ).state
        observations.append(plugin.observe(payload, state, "buyer", phase))
    events = []
    for i, (a, o) in enumerate(zip(parsed_actions, observations)):
        if a["action"] != "request_sample":
            continue
        sample = next(
            s for s in o["verified_samples"] if s["supplier_id"] == a["supplier_id"]
        )
        following = parsed_actions[i + 1] if i + 1 < len(parsed_actions) else {}
        events.append(
            dict(
                supplier_id=a["supplier_id"],
                observed_yield_rate=sample["observed_yield_rate"],
                inspected_units=sample["sample_size"],
                draws=sample["draws"],
                actions_left=o["actions_left"],
                next_action=following.get("action"),
                next_supplier_id=following.get("supplier_id"),
            )
        )
    first = next(
        (a["supplier_id"] for a in parsed_actions if a["action"] == "request_quote"),
        None,
    )
    reason = market_impossibility(normalize_observation(initial))
    return dict(
        first_quoted_supplier=first,
        public_reference_first_supplier=reference_first.get("supplier_id"),
        first_quote_matches_public_reference=(
            first == reference_first.get("supplier_id") if first else None
        ),
        sample_decision_events=events,
        market_impossibility_certificate=reason,
        explicit_defer_reason=state["defer_reason"],
        deferral_supported_by_market_certificate=bool(
            state["termination_reason"] == "deferred" and reason
        ),
    )
