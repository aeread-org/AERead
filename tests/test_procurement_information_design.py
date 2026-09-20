"""Checks of offline decision economics, not claims about model performance."""
import copy
from fractions import Fraction
import json

import pytest

from tools.check_procurement_information_design import (
    FIXTURES, action_values, allocation_choices, evaluate, number,
)

CASES = json.loads(FIXTURES.read_text())["cases"]
BY_ID = {c["id"]: c for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_authored_action_and_value_are_verified(case):
    row = evaluate([case])[0]
    assert row["advantage_over_next_action_usd"] > 0


def test_each_pair_changes_the_best_action():
    assert len(CASES) == 12
    for left, right in zip(CASES[::2], CASES[1::2]):
        assert left["mechanism"] == right["mechanism"]
        assert left["expected_best_actions"] != right["expected_best_actions"]


def test_noisy_information_is_not_a_clairvoyant_lookup():
    qs = action_values(BY_ID["resample_uncertain"])
    # Independently calculated: P(pass)=1/2, posterior=4/5; fail -> incumbent.
    assert qs["resample_candidate"] == Fraction(1, 2) * 28 + Fraction(1, 2) * 12 - 2
    clairvoyant_value = Fraction(1, 2) * 40 + Fraction(1, 2) * 12
    assert max(qs.values()) == 18 < clairvoyant_value
    assert qs["award_candidate"] == 10


def test_reference_can_value_a_two_step_information_plan():
    case = dict(
        prior=[".5", ".5"], research_actions_left=2,
        terminal_choices=[
            dict(id="safe", payoffs_usd=["10", "10"]),
            dict(id="risky", payoffs_usd=["30", "-30"]),
        ],
        research_actions=[dict(id="test", cost_usd=".1", days=1, max_uses=2,
                               outcomes={"pass": [".6", ".4"], "fail": [".4", ".6"]})],
    )
    assert action_values(case)["test"] == Fraction(41, 4)
    case["research_actions_left"] = 1
    assert action_values(case)["test"] == Fraction(99, 10)
    # A purely myopic information rule stops; a two-step plan is worth pursuing.
    assert max(action_values(case).values()) == 10


def test_time_cost_can_remove_the_existing_deal():
    tight = action_values(BY_ID["deadline_tight"])
    slack = action_values(BY_ID["deadline_slack"])
    assert tight["quote_alternative"] == -1
    assert slack["quote_alternative"] == 23
    assert tight["award_incumbent"] == slack["award_incumbent"] == 16


def test_unqualified_purchase_and_free_research_are_not_available():
    qs = action_values(BY_ID["walkaway_shared_downturn"])
    assert "award_remaining" not in qs
    assert qs["quote_remaining"] == Fraction(1, 10) * 30 - 4 == -1
    assert qs["defer"] == 0
    evidence = BY_ID["walkaway_shared_downturn"]["belief_provenance"]
    p = number(evidence["prior_favorable_market"])
    a = number(evidence["bad_quote_likelihood_given_favorable"]) ** 2
    b = number(evidence["bad_quote_likelihood_given_unfavorable"]) ** 2
    assert p * a / (p * a + (1 - p) * b) == Fraction(1, 10)


def test_allocation_accounts_for_lot_sizes_fixed_freight_and_bom():
    first = allocation_choices(BY_ID["allocation_cheap_second_shipment"]["allocation_market"])
    best = max(first, key=lambda c: number(c["payoffs_usd"][0]))
    assert best["quantities"] == {"A": 12, "B": 8}
    assert number(best["cost_usd"]) == 12 * 2 + 8 * Fraction(12, 5)
    for name, kits, cost in [("bom_cash_60", 20, 58), ("bom_cash_50", 10, 18)]:
        market = BY_ID[name]["allocation_market"]
        choices = allocation_choices(market)
        assert all(number(c["cost_usd"]) <= number(market["cash_budget_usd"]) for c in choices)
        best = max(choices, key=lambda c: number(c["payoffs_usd"][0]))
        assert (best["completed_kits"], number(best["cost_usd"])) == (kits, cost)


def test_state_order_cannot_change_reference_values():
    case = copy.deepcopy(BY_ID["prioritize_low_contact_cost"])
    original = action_values(case)
    case["prior"].reverse()
    for choice in case["terminal_choices"]:
        choice["payoffs_usd"].reverse()
    for action in case["research_actions"]:
        for likelihood in action["outcomes"].values():
            likelihood.reverse()
    assert action_values(case) == original


def test_malformed_likelihood_is_not_silently_normalized():
    case = copy.deepcopy(BY_ID["resample_uncertain"])
    case["research_actions"][0]["outcomes"]["pass"][0] = ".9"
    with pytest.raises(AssertionError):
        action_values(case)
