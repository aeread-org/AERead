"""Hand-computed-trace unit tests for the vendored auction-arena functions.

Every trace below is asserted against the vendored function's output, drawn
from the upstream source text quoted in each function's provenance docstring
(``src/aeread_families/aucarena/_vendored_upstream.py``) -- a reviewer can
check the vendored body against the citation without running upstream. This
is deliberately a plain pytest unit-test file, not the "hand-computed-trace
parity runner" (``parity.py``) named in ``docs/aucarena_adapter_spec.md``
section 4 -- that module (and its own richer parity report) lands with the
measurement milestone.
"""
from __future__ import annotations

import random

from aeread_families.aucarena import _vendored_upstream as vendored


# ---------------------------------------------------------------------------
# bid_rule (src/bidder_base.py:384-410).
# ---------------------------------------------------------------------------


def test_bid_rule_opening_bid_is_the_item_price() -> None:
    bid_price, rule_bid_cnt = vendored.bid_rule(
        cur_bid=0, cur_item_price=1000, budget=9000, rule_bid_cnt=0, max_bid_cnt=4
    )
    assert (bid_price, rule_bid_cnt) == (1000, 1)


def test_bid_rule_negative_cur_bid_is_also_an_opening_bid() -> None:
    # auctioneer.prev_round_max_bid starts at -1; bid_rule treats any
    # cur_bid <= 0 as "no standing bid yet".
    bid_price, rule_bid_cnt = vendored.bid_rule(
        cur_bid=-1, cur_item_price=1000, budget=9000, rule_bid_cnt=0, max_bid_cnt=4
    )
    assert (bid_price, rule_bid_cnt) == (1000, 1)


def test_bid_rule_increments_by_min_markup_pct_of_price() -> None:
    bid_price, rule_bid_cnt = vendored.bid_rule(
        cur_bid=1000, cur_item_price=1000, budget=9000, rule_bid_cnt=1, max_bid_cnt=4
    )
    assert (bid_price, rule_bid_cnt) == (1100, 2)


def test_bid_rule_withdraws_when_max_bid_cnt_reached() -> None:
    bid_price, rule_bid_cnt = vendored.bid_rule(
        cur_bid=1500, cur_item_price=1000, budget=9000, rule_bid_cnt=4, max_bid_cnt=4
    )
    assert bid_price == -1
    assert rule_bid_cnt == 4  # unchanged: a forced withdrawal never counts as an attempt


def test_bid_rule_withdraws_when_budget_cannot_afford_next_bid() -> None:
    bid_price, rule_bid_cnt = vendored.bid_rule(
        cur_bid=1500, cur_item_price=1000, budget=1550, rule_bid_cnt=1, max_bid_cnt=4
    )
    assert bid_price == -1
    assert rule_bid_cnt == 1


# ---------------------------------------------------------------------------
# bid_sanity_check (src/bidder_base.py:623-637).
# ---------------------------------------------------------------------------


def test_bid_sanity_check_a_negative_bid_always_passes() -> None:
    assert vendored.bid_sanity_check(-1, -1, 1000, 0, 0.1) is None


def test_bid_sanity_check_rejects_a_bid_below_the_starting_price() -> None:
    msg = vendored.bid_sanity_check(150, -1, 1000, 2500, 0.1)
    assert msg == "your bid is lower than the starting bid ($1000)"


def test_bid_sanity_check_rejects_a_bid_over_budget() -> None:
    msg = vendored.bid_sanity_check(2000, -1, 1000, 1500, 0.1)
    assert msg == "you don't have insufficient budget ($1500 left)"


def test_bid_sanity_check_rejects_a_bid_below_the_minimum_markup() -> None:
    msg = vendored.bid_sanity_check(1050, 1000, 1000, 9000, 0.1)
    assert msg == "you must advance previous highest bid ($1000) by at least $100 (10%)."


def test_bid_sanity_check_accepts_a_legal_advance() -> None:
    assert vendored.bid_sanity_check(1100, 1000, 1000, 9000, 0.1) is None


# ---------------------------------------------------------------------------
# record_bid (src/auctioneer_base.py:63-80): tie-breaking with two equal bids.
# ---------------------------------------------------------------------------


def test_record_bid_updates_highest_on_a_strictly_higher_bid() -> None:
    round_bids = [{"bidder": "a", "bid": 1000}]
    highest_bid, highest_bidder = vendored.record_bid(
        round_bids, -1, None, rng=random.Random(0)
    )
    assert (highest_bid, highest_bidder) == (1000, "a")


def test_record_bid_ignores_non_positive_bids() -> None:
    round_bids = [{"bidder": "a", "bid": -1}]
    highest_bid, highest_bidder = vendored.record_bid(
        round_bids, -1, None, rng=random.Random(0)
    )
    assert (highest_bid, highest_bidder) == (-1, None)


def test_record_bid_breaks_a_tie_via_the_injected_rng() -> None:
    round_bids = [{"bidder": "a", "bid": 1000}, {"bidder": "b", "bid": 1000}]
    # random.Random(seed).choice([...]) is deterministic for a fixed seed;
    # this pins that our injected-rng contract behaves like upstream's
    # module-level random.choice would for the same draw.
    highest_bid, highest_bidder = vendored.record_bid(
        round_bids, -1, None, rng=random.Random(1234)
    )
    assert highest_bid == 1000
    assert highest_bidder in {"a", "b"}
    # Same seed -> same tie-break outcome every time (reproducibility, not
    # upstream's own literal RNG stream, since upstream never seeded this).
    replay_bid, replay_bidder = vendored.record_bid(
        round_bids, -1, None, rng=random.Random(1234)
    )
    assert (replay_bid, replay_bidder) == (highest_bid, highest_bidder)


# ---------------------------------------------------------------------------
# check_hammer (src/auctioneer_base.py:125-152): 0/1/2-bidder sequences.
# ---------------------------------------------------------------------------


def test_check_hammer_no_bidders_ever_fails_to_sell_without_discount() -> None:
    result = vendored.check_hammer(
        highest_bidder_is_none=True,
        num_bid_this_round=0,
        bid_round=0,
        enable_discount=False,
        prev_round_max_bid=-1,
        highest_bid=-1,
    )
    assert result == {
        "is_sold": True,
        "fail_to_sell": True,
        "apply_discount": False,
        "prev_round_max_bid": -1,
    }


def test_check_hammer_single_uncontested_bid_in_round_0_sells_immediately() -> None:
    result = vendored.check_hammer(
        highest_bidder_is_none=False,
        num_bid_this_round=1,
        bid_round=0,
        enable_discount=False,
        prev_round_max_bid=-1,
        highest_bid=1000,
    )
    assert result["is_sold"] is True
    assert result["prev_round_max_bid"] == -1  # uncontested branch never updates it


def test_check_hammer_two_bidders_in_round_0_continues_to_round_1() -> None:
    result = vendored.check_hammer(
        highest_bidder_is_none=False,
        num_bid_this_round=2,
        bid_round=0,
        enable_discount=False,
        prev_round_max_bid=-1,
        highest_bid=1000,
    )
    assert result["is_sold"] is False
    assert result["prev_round_max_bid"] == 1000


def test_check_hammer_no_counter_bid_sells_to_the_standing_highest_bidder() -> None:
    result = vendored.check_hammer(
        highest_bidder_is_none=False,
        num_bid_this_round=0,
        bid_round=1,
        enable_discount=False,
        prev_round_max_bid=1000,
        highest_bid=1000,
    )
    assert result["is_sold"] is True
    assert result["prev_round_max_bid"] == 1000


def test_check_hammer_raises_on_the_impossible_state() -> None:
    # Upstream's own "won't happen" invariant: highest_bidder is None but a
    # positive bid was recorded. Preserved verbatim, not smoothed over.
    try:
        vendored.check_hammer(
            highest_bidder_is_none=True,
            num_bid_this_round=1,
            bid_round=0,
            enable_discount=False,
            prev_round_max_bid=-1,
            highest_bid=1000,
        )
    except ValueError as error:
        assert "highest_bidder is None but num_bid is 1" in str(error)
    else:
        raise AssertionError("expected ValueError")


# ---------------------------------------------------------------------------
# _num_bids_in_round, hammer_fall, set_withdraw, win_bid, lose_bid, gather_all_status.
# ---------------------------------------------------------------------------


def test_num_bids_in_round_counts_only_positive_bids() -> None:
    round_bids = [
        {"bidder": "a", "bid": -1},
        {"bidder": "b", "bid": 1000},
        {"bidder": "c", "bid": 1100},
    ]
    assert vendored._num_bids_in_round(round_bids) == 2


def test_hammer_fall_returns_the_reset_fields() -> None:
    assert vendored.hammer_fall() == {
        "cur_item": None,
        "highest_bidder": None,
        "highest_bid": -1,
        "prev_round_max_bid": -1,
        "fail_to_sell": False,
    }


def test_set_withdraw_true_only_for_a_negative_bid() -> None:
    assert vendored.set_withdraw(-1) is True
    assert vendored.set_withdraw(0) is False
    assert vendored.set_withdraw(1200) is False


def test_win_bid_updates_budget_profit_and_items_won() -> None:
    item = vendored.Item(id=1, name="Widget A", price=1000, desc="d", true_value=2000)
    new_budget, new_profit, new_items_won = vendored.win_bid(
        budget=3200, profit=0, items_won=(), item=item, bid=1600
    )
    assert new_budget == 1600
    assert new_profit == 400
    assert new_items_won == ((1, 1600),)


def test_lose_bid_and_gather_all_status_are_pure_reporting_helpers() -> None:
    item = vendored.Item(id=1, name="Widget A", price=1000, desc="d", true_value=2000)
    assert vendored.lose_bid(item) == "You lost Widget A."

    status = vendored.gather_all_status(
        [
            {"name": "agent", "profit": 800, "items_won": [[1, 1600], [2, 1600]]},
            {"name": "field_high", "profit": 2000, "items_won": [[3, 1000], [4, 1000]]},
        ]
    )
    assert status == {
        "agent": {"profit": 800, "items_won": [[1, 1600], [2, 1600]]},
        "field_high": {"profit": 2000, "items_won": [[3, 1000], [4, 1000]]},
    }


def test_bid_number_re_matches_upstreams_own_extraction_pattern() -> None:
    assert vendored.BID_NUMBER_RE.findall("I bid $1,200! (Rule generated)".replace(",", "")) == [
        "$1200"
    ]
