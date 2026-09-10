"""Gate 1 headroom screening: decide whether a world can express a difference.

A panel is admitted world by world, and a world earns its place only by failing
to be any of three things. It is **trivial** when a deterministic policy reading
only public observations already succeeds, so verification buys nothing and the
family's subject is not under test. It is **floored** when the control never
succeeds. It is **saturated** when the control always succeeds.

The three are stated separately on purpose. An earlier version of this screen
used the shorter rule "admit when the control and the baseline disagree", which
sounds equivalent and is not: it admits a saturated world whenever a baseline
happens to lose there, which is how the defect this screen exists to catch got
rebuilt inside its own fix. See defects 14, 16 and 17 of the design review, and
J-05 through J-07 in the incident log.

Nothing here catches exceptions from a policy. A policy that cannot run and a
policy that runs and loses must not produce the same value; conflating them once
produced a fabricated unanimous admission across a whole panel.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from aeread.shared_runner.task.scheduler import ActionEnvelope

from .environment import ProcurementAllocationPlugin
from .policy_baselines import choose_public_policy_action

#: Deterministic public-observation policies. These replay offline and free, so
#: the triviality test costs nothing and can be run on every candidate world.
SCREEN_BASELINES: tuple[str, ...] = (
    "displayed_price_greedy",
    "listing_claim_fit",
    "semantic_hint",
)

#: One seed cannot distinguish a ceiling from a lucky draw, and both the floored
#: and saturated tests are claims about a rate.
MINIMUM_SCREEN_SEEDS = 3

#: A world must let a better decision exist, which is a claim about two policies
#: and not about one. Dispersion alone admits a coin flip: where suppliers are
#: indistinguishable before verification, outcomes vary with which ones you
#: happened to check, and no policy can beat any other.
COIN_FLIP = "reject: no policy separation"

#: Dispersion must be material, not merely non-zero, as a fraction of the scale
#: the world is played on. Two worlds were admitted on a $0.25 spread and a $0.35
#: margin against a $269 baseline: the control failed at every seed and differed
#: only in what it spent on information. "Not all identical" is not headroom.
MINIMUM_RELATIVE_SPREAD = 0.05

#: Continuous-metric verdict: the control scores identically at every seed, so
#: the world cannot express a difference however large its scores are.
DEGENERATE = "reject: degenerate"
TRIVIAL = "reject: trivial"
FLOORED = "reject: floored"
SATURATED = "reject: saturated"
UNMEASURED = "reject: unmeasured"
ADMIT = "admit"


def classify_world(
    control_outcomes: Sequence[bool],
    baseline_outcomes: Mapping[str, bool | None],
) -> str:
    """Return the admission verdict for one world.

    ``control_outcomes`` is one boolean per screened seed. ``baseline_outcomes``
    maps each deterministic policy to its outcome, or to ``None`` where the
    policy reached no terminal state within the budget.
    """
    if not control_outcomes or len(control_outcomes) < MINIMUM_SCREEN_SEEDS:
        return UNMEASURED
    if not baseline_outcomes or all(
        outcome is None for outcome in baseline_outcomes.values()
    ):
        # No baseline reached a terminal state, so triviality is untested. A
        # screen that cannot run its own test must reject, never admit.
        return UNMEASURED
    if any(outcome is True for outcome in baseline_outcomes.values()):
        return TRIVIAL
    rate = sum(bool(outcome) for outcome in control_outcomes) / len(control_outcomes)
    if rate == 0.0:
        return FLOORED
    if rate == 1.0:
        return SATURATED
    return ADMIT


def classify_world_continuous(
    control_scores: Sequence[float],
    baseline_scores: Mapping[str, float | None],
    *,
    lower_is_better: bool = True,
    minimum_relative_spread: float = MINIMUM_RELATIVE_SPREAD,
) -> str:
    """Admission verdict for a world scored on a continuous metric.

    `classify_world` decides on a binary success, which for this family is a
    threshold on a continuous quantity, and a threshold discards exactly the
    information a panel needs. Measured on the noisy candidate panel, award
    feasibility was 100% at every seed of every world with zero variance, while
    regret to the full-information bound ranged from $8.04 to $64.82 and varied
    within four of six worlds. The same rows were uninformative read one way and
    informative read the other.

    So the grounds are restated for a continuous score. A world is *degenerate*
    when the control scores identically at every seed, which subsumes both
    floored and saturated: there is no dispersion for a treatment to move. It is
    *trivial* when a deterministic public-observation policy already matches the
    control's best score, since verification then buys nothing.
    """
    if not control_scores or len(control_scores) < MINIMUM_SCREEN_SEEDS:
        return UNMEASURED
    if not baseline_scores or all(
        score is None for score in baseline_scores.values()
    ):
        return UNMEASURED
    measured = [score for score in baseline_scores.values() if score is not None]
    best_control = min(control_scores) if lower_is_better else max(control_scores)
    best_baseline = min(measured) if lower_is_better else max(measured)

    # Both remaining tests are comparisons of a difference against a scale, so
    # the scale is derived once from the magnitudes actually in play.
    scale = max(abs(best_baseline), abs(best_control), 1.0)
    material = minimum_relative_spread * scale

    if max(control_scores) - min(control_scores) < material:
        return DEGENERATE
    margin = (
        best_baseline - best_control if lower_is_better else best_control - best_baseline
    )
    if margin < material:
        return TRIVIAL
    return ADMIT


def classify_world_by_policy_separation(
    policy_scores: Mapping[str, Sequence[float]],
    *,
    lower_is_better: bool = True,
    minimum_relative_spread: float = MINIMUM_RELATIVE_SPREAD,
) -> str:
    """Admit a world only when two policies differ in *expectation*.

    The rule the other classifiers were missing. A world can show wide dispersion
    and still be unmeasurable, because the dispersion belongs to luck rather than
    to judgment: when every supplier looks identical before verification, which
    ones a policy happens to check decides the outcome, and every policy draws
    from the same urn. Twelve procurement panels failed this way, and a screen
    that tested only the control's spread would have admitted the coin flips
    among them.

    ``policy_scores`` maps at least two structurally different policies to their
    scores on this world. A world is admitted when the best and worst policy
    means differ by a material fraction of the scale in play, which is the
    property that says a better decision exists to be made.
    """
    measured = {
        name: [float(score) for score in scores]
        for name, scores in policy_scores.items()
        if scores
    }
    if len(measured) < 2:
        return UNMEASURED
    means = {name: sum(scores) / len(scores) for name, scores in measured.items()}
    best = min(means.values()) if lower_is_better else max(means.values())
    worst = max(means.values()) if lower_is_better else min(means.values())
    scale = max(abs(best), abs(worst), 1.0)
    if abs(best - worst) < minimum_relative_spread * scale:
        return COIN_FLIP
    return ADMIT


def within_world_variance(control_outcomes: Sequence[float]) -> float:
    """Sample variance of a world's control outcomes.

    Reported rather than thresholded. Zero is a finding: it means the seeds are
    repeats and not replicates, so the effective sample size of a panel is its
    world count and an interval computed across rows is too narrow.
    """
    count = len(control_outcomes)
    if count < 2:
        return 0.0
    values = [float(outcome) for outcome in control_outcomes]
    mean = sum(values) / count
    return sum((value - mean) ** 2 for value in values) / (count - 1)


def replay_baseline(payload: Mapping[str, Any], policy_id: str) -> bool | None:
    """Play one deterministic policy offline. ``None`` if it reaches no terminal.

    Deliberately does not guard the policy call. A ``TypeError`` here means the
    screen is broken, not that the policy lost.
    """
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)
    for _ in range(int(family_case["interaction"]["max_actions"])):
        if state["done"]:
            break
        observation = plugin.observe(family_case, state, "buyer", phase)
        action = choose_public_policy_action(observation, policy_id=policy_id)
        if action is None:
            return None
        parsed = plugin.parse_action(family_case, state, "buyer", phase, action)
        if not parsed.ok:
            return None
        legality = plugin.legal(family_case, state, "buyer", phase, parsed.action)
        state = plugin.step(
            family_case,
            state,
            phase,
            {
                "buyer": ActionEnvelope(
                    seat_id="buyer",
                    valid=legality.legal,
                    action=parsed.action,
                    parse=parsed,
                    legality=legality,
                )
            },
        ).state
    terminal = plugin.terminal(family_case, state)
    if terminal is None:
        return None
    return bool(plugin.outcome(family_case, terminal)["feasible_award"])


def replay_best_qualified(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """A stronger screening reference: qualify what fits, then award the best of it.

    The declared policy baselines defer when they cannot qualify another
    supplier, so on a panel where covering the target needs more qualifications
    than the action budget allows, they lose without ever placing an award. A
    subject that beats *that* has beaten a stopping rule, not a market.

    This reference removes the excuse. It qualifies the cheapest listing in each
    component, spends any spare actions on the component whose evidence looks
    worst, and then awards the best supplier it has rather than deferring. It is
    screen-only and deliberately not added to ``POLICY_IDS``: that tuple is
    pinned by a published plan, and extending it would re-date sealed campaign
    identities for the second time (defect 19).
    """
    plugin = ProcurementAllocationPlugin()
    case = plugin.validate_payload(payload)
    phase = plugin.phases(case)[0]
    state = plugin.initial_state(case, None)
    budget = int(case["interaction"]["max_actions"])

    def play(action: Mapping[str, Any]) -> bool:
        nonlocal state
        parsed = plugin.parse_action(case, state, "buyer", phase, dict(action))
        if not parsed.ok:
            return False
        legality = plugin.legal(case, state, "buyer", phase, parsed.action)
        state = plugin.step(
            case, state, phase,
            {"buyer": ActionEnvelope("buyer", legality.legal, parsed.action, parsed, legality)},
        ).state
        return True

    by_component: dict[str, list[Mapping[str, Any]]] = {}
    for supplier in case["suppliers"]:
        by_component.setdefault(supplier["component"], []).append(supplier)
    for suppliers in by_component.values():
        suppliers.sort(key=lambda s: float(s["private_terms"]["base_unit_price_usd"]))

    def evidenced(supplier_id: str) -> float:
        record = state["quality_evidence"].get(supplier_id) or {}
        if "verified_yield_rate" in record:
            return float(record["verified_yield_rate"])
        return float(record.get("observed_yield_rate", 0.0))

    def qualify(supplier: Mapping[str, Any]) -> bool:
        supplier_id = str(supplier["supplier_id"])
        for action in ("request_quote", "request_sample"):
            if state["done"] or not play(
                {"action": action, "supplier_id": supplier_id, "message": action}
            ):
                return False
        return True

    # Cheapest in each component first, because that is the cheapest way to have
    # something awardable everywhere.
    qualified: dict[str, list[str]] = {component: [] for component in by_component}
    for component, suppliers in by_component.items():
        if qualify(suppliers[0]):
            qualified[component].append(str(suppliers[0]["supplier_id"]))

    # Then spend spare actions where the evidence is worst, not by index order.
    # Choosing by position instead would make a world look hard whenever the
    # trap happened to sit in the component this loop reached second.
    while (int(case["interaction"]["max_actions"]) - state["actions_used"]) >= 3:
        worst = min(
            by_component,
            key=lambda component: max(
                (evidenced(s) for s in qualified[component]), default=0.0
            ),
        )
        remaining = [
            supplier
            for supplier in by_component[worst]
            if str(supplier["supplier_id"]) not in qualified[worst]
        ]
        if not remaining or not qualify(remaining[0]):
            break
        qualified[worst].append(str(remaining[0]["supplier_id"]))

    lines = []
    for component, suppliers in by_component.items():
        offers = [
            offer for offer in state["offers"].values()
            if offer["component"] == component
            and str(offer["supplier_id"]) in state["quality_evidence"]
        ]
        if not offers:
            continue
        best = max(offers, key=lambda o: evidenced(str(o["supplier_id"])))
        lines.append({"offer_id": best["offer_id"], "quantity": int(best["capacity"])})

    if len(lines) == len(by_component):
        play({"action": "submit_award", "award_lines": lines, "reason": None})
    elif not state["done"]:
        play({"action": "defer", "reason": "no qualified supplier for every component"})

    terminal = plugin.terminal(case, state)
    return plugin.outcome(case, terminal) if terminal is not None else None


def screen_baselines(
    payload: Mapping[str, Any], policies: Iterable[str] = SCREEN_BASELINES
) -> dict[str, bool | None]:
    """Replay every deterministic baseline against one world."""
    return {policy: replay_baseline(payload, policy) for policy in policies}


__all__ = [
    "ADMIT",
    "COIN_FLIP",
    "DEGENERATE",
    "FLOORED",
    "MINIMUM_RELATIVE_SPREAD",
    "MINIMUM_SCREEN_SEEDS",
    "SATURATED",
    "SCREEN_BASELINES",
    "TRIVIAL",
    "UNMEASURED",
    "classify_world",
    "classify_world_by_policy_separation",
    "classify_world_continuous",
    "replay_baseline",
    "replay_best_qualified",
    "screen_baselines",
    "within_world_variance",
]
