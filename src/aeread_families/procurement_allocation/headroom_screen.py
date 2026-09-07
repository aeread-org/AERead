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
    if len(set(control_scores)) == 1:
        return DEGENERATE
    measured = [score for score in baseline_scores.values() if score is not None]
    best_control = min(control_scores) if lower_is_better else max(control_scores)
    best_baseline = min(measured) if lower_is_better else max(measured)
    beaten = (
        best_baseline <= best_control if lower_is_better else best_baseline >= best_control
    )
    if beaten:
        return TRIVIAL
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


def screen_baselines(
    payload: Mapping[str, Any], policies: Iterable[str] = SCREEN_BASELINES
) -> dict[str, bool | None]:
    """Replay every deterministic baseline against one world."""
    return {policy: replay_baseline(payload, policy) for policy in policies}


__all__ = [
    "ADMIT",
    "DEGENERATE",
    "FLOORED",
    "MINIMUM_SCREEN_SEEDS",
    "SATURATED",
    "SCREEN_BASELINES",
    "TRIVIAL",
    "UNMEASURED",
    "classify_world",
    "classify_world_continuous",
    "replay_baseline",
    "screen_baselines",
    "within_world_variance",
]
