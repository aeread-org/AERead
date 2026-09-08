"""Vendored, provenance-headed excerpts from ``jiangjiechen/auction-arena``.

Upstream's ``Auctioneer`` (``src/auctioneer_base.py``) and ``Bidder``
(``src/bidder_base.py``) classes import ``langchain``, ``vertexai``,
``torch``, and ``transformers`` at module level (see
``docs/aucarena_adapter_spec.md``, "Governing facts") -- there is no way to
import either class, even to reach the handful of pure bookkeeping methods
below, without paying that whole dependency cost. Every function in this
module is a hand-transcribed, dependency-free free function over explicit
arguments, one per upstream method, each carrying its own provenance
docstring (source repo, exact pinned commit, upstream file:line range,
license, and exactly what changed in the transcription -- never a
re-derivation of the auction *policy* itself, per Apache-2.0 SS4(b)).

Pin: ``jiangjiechen/auction-arena`` @
``d0f3bc851eb376d4ea5e69ae5fe52ec5be987bb3``, license Apache-2.0.

Deliberately not vendored (out of this spec's rule-bidder scope, see
``docs/aucarena_adapter_spec.md`` SS7): ``Item.lower_price``/``reset_price``
(the ``enable_discount`` price-cut path -- scenarios in this spec fix
``enable_discount=False``), and ``Auctioneer.parse_bid`` (its own body calls
``ChatOpenAI`` to normalize free text before applying the ``-1``/regex
extraction rule below; that extraction rule is reproduced directly in
``environment.py``'s ``parse_action``, not here, because the upstream method
itself is not a pure function -- see that module's docstring).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

UPSTREAM_REPO = "jiangjiechen/auction-arena"
UPSTREAM_COMMIT = "d0f3bc851eb376d4ea5e69ae5fe52ec5be987bb3"
UPSTREAM_LICENSE = "Apache-2.0"

# Mirrors upstream's own extraction rule (auctioneer_base.py:194: the
# ``re.findall(r'\$?\d+', ...)`` call inside ``parse_bid``), reproduced here
# only as a shared constant so ``environment.py`` and any test never
# hand-copy the pattern twice.
BID_NUMBER_RE = re.compile(r"\$?\d+")


@dataclass(frozen=True, slots=True)
class Item:
    """Vendored from ``src/item_base.py:6-13`` (class ``Item``).

    Changes: converted from a plain mutable class to a frozen dataclass.
    ``lower_price``/``reset_price`` (``src/item_base.py:27-32``, the
    ``enable_discount`` price-cut path) are not reproduced -- out of this
    spec's fixed-``enable_discount=False`` scope.
    """

    id: int
    name: str
    price: int
    desc: str
    true_value: int

    def get_desc(self) -> str:
        """Vendored from ``src/item_base.py:15-16`` (``Item.get_desc``).

        No logic changed.
        """
        return f"{self.name}, starting at ${int(self.price)}."


def bid_rule(
    *,
    cur_bid: int,
    cur_item_price: int,
    budget: int,
    rule_bid_cnt: int,
    max_bid_cnt: int,
    min_markup_pct: float = 0.1,
) -> tuple[int, int]:
    """Vendored from ``src/bidder_base.py:384-410`` (``Bidder.bid_rule``).

    Changes: extracted to a free function over explicit arguments
    (``self.budget``, ``self.rule_bid_cnt``, ``self.max_bid_cnt``, and
    ``self._get_cur_item().price`` become ``budget``, ``rule_bid_cnt``,
    ``max_bid_cnt``, and ``cur_item_price``); returns ``(bid_price,
    updated_rule_bid_cnt)`` instead of mutating ``self``. The free-text
    ``dialogue_history`` side effect (presentation-only, unused by any
    declared ``MeasurementLeafSpec``) is not reproduced. No arithmetic or
    branching changed.
    """
    if cur_bid <= 0:
        next_bid = cur_item_price
    else:
        next_bid = cur_bid + min_markup_pct * cur_item_price

    if budget - next_bid >= 0 and rule_bid_cnt < max_bid_cnt:
        bid_price = int(next_bid)
        rule_bid_cnt = rule_bid_cnt + 1
    else:
        bid_price = -1
    return bid_price, rule_bid_cnt


def bid_sanity_check(
    bid_price: int,
    prev_round_max_bid: int,
    cur_item_price: int,
    budget: int,
    min_markup_pct: float,
) -> str | None:
    """Vendored from ``src/bidder_base.py:623-637`` (``Bidder.bid_sanity_check``).

    Changes: extracted to a free function over explicit arguments; no logic
    changed (including the upstream grammar as written).
    """
    if bid_price < 0:
        msg = None
    else:
        min_bid_increase = int(min_markup_pct * cur_item_price)
        if bid_price > budget:
            msg = f"you don't have insufficient budget (${budget} left)"
        elif bid_price < cur_item_price:
            msg = f"your bid is lower than the starting bid (${cur_item_price})"
        elif bid_price < prev_round_max_bid + min_bid_increase:
            msg = (
                f"you must advance previous highest bid (${prev_round_max_bid}) "
                f"by at least ${min_bid_increase} ({int(100 * min_markup_pct)}%)."
            )
        else:
            msg = None
    return msg


def win_bid(
    *, budget: int, profit: int, items_won: Sequence[tuple[int, int]], item: Item, bid: int
) -> tuple[int, int, tuple[tuple[int, int], ...]]:
    """Vendored from ``src/bidder_base.py:789-794`` (``Bidder.win_bid``).

    Changes: extracted to a free function over explicit arguments, returning
    ``(new_budget, new_profit, new_items_won)`` instead of mutating ``self``;
    ``items_won`` entries are ``(item.id, bid)`` tuples rather than
    ``[item, bid]`` lists (AERead's canonical state must stay JSON-shaped).
    The congratulatory message string (presentation-only) is not reproduced.
    """
    new_budget = budget - bid
    new_profit = profit + item.true_value - bid
    new_items_won = tuple(items_won) + ((item.id, bid),)
    return new_budget, new_profit, new_items_won


def lose_bid(item: Item) -> str:
    """Vendored from ``src/bidder_base.py:796-797`` (``Bidder.lose_bid``).

    Changes: extracted to a free function; no state change upstream either
    (kept only for provenance completeness -- the message is not scored).
    """
    return f"You lost {item.name}."


def set_withdraw(bid: int) -> bool:
    """Vendored from ``src/bidder_base.py:803-809`` (``Bidder.set_withdraw``).

    Changes: extracted to a free function returning the new ``withdraw``
    boolean instead of mutating ``self``. The ``engagement_count``/
    ``engagement_history`` side effects (belief-tracking diagnostics for the
    unvendored LLM-bidder path) are not reproduced. No branching changed.
    """
    if bid < 0:  # withdraw
        return True
    return False  # bid == 0 (discount re-entry) or a normal positive bid


def record_bid(
    round_bids: Sequence[Mapping[str, Any]],
    highest_bid: int,
    highest_bidder: Any,
    *,
    rng: random.Random,
) -> tuple[int, Any]:
    """Vendored from ``src/auctioneer_base.py:63-80`` (``Auctioneer.record_bid``).

    Changes: extracted the highest-bid/highest-bidder update rule into a
    pure function over an explicit, already-appended round history list and
    an injected ``random.Random`` (for reproducible tie-breaking) instead of
    the module-level ``random.choice``. ``bidding_history``/``auction_logs``
    bookkeeping is environment-owned trajectory recording, not vendored
    here. Faithfully reproduces upstream's full per-call rescan of
    ``round_bids`` (including its harmless re-draw of the tie-break RNG for
    entries that already equal the running highest bid) -- no logic changed.
    """
    for hist in round_bids:
        if hist["bid"] > 0:
            if highest_bid < hist["bid"]:
                highest_bid = hist["bid"]
                highest_bidder = hist["bidder"]
            elif highest_bid == hist["bid"]:
                highest_bidder = rng.choice([highest_bidder, hist["bidder"]])
    return highest_bid, highest_bidder


def _num_bids_in_round(round_bids: Sequence[Mapping[str, Any]]) -> int:
    """Vendored from ``src/auctioneer_base.py:154-160`` (``Auctioneer._num_bids_in_round``).

    Changes: takes the round's bid list directly instead of indexing
    ``self.bidding_history[bid_round]``; no logic changed.
    """
    cnt = 0
    for hist in round_bids:
        if hist["bid"] > 0:
            cnt += 1
    return cnt


def check_hammer(
    *,
    highest_bidder_is_none: bool,
    num_bid_this_round: int,
    bid_round: int,
    enable_discount: bool,
    prev_round_max_bid: int,
    highest_bid: int,
) -> dict[str, Any]:
    """Vendored from ``src/auctioneer_base.py:125-152`` (``Auctioneer.check_hammer``).

    Changes: extracted to a free function over explicit state (``self.highest_bidder
    is None`` becomes ``highest_bidder_is_none``; ``self._num_bids_in_round(bid_round)``
    becomes the pre-computed ``num_bid_this_round``); returns a dict of the
    fields the method mutated (``is_sold``, ``fail_to_sell``, ``apply_discount``,
    ``prev_round_max_bid``) instead of mutating ``self`` and ``self.cur_item``.
    No branching or arithmetic changed, including the upstream "won't happen"
    invariant, which still raises.
    """
    fail_to_sell = False
    apply_discount = False
    new_prev_round_max_bid = prev_round_max_bid

    if highest_bidder_is_none:
        if num_bid_this_round == 0:
            # failed to sell, as there is no highest bidder
            fail_to_sell = True
            if enable_discount and bid_round < 3:
                apply_discount = True
                is_sold = False
            else:
                is_sold = True
        else:
            # won't happen
            raise ValueError(
                f"highest_bidder is None but num_bid is {num_bid_this_round}"
            )
    else:
        if prev_round_max_bid < 0 and num_bid_this_round == 1:
            is_sold = True
        else:
            new_prev_round_max_bid = highest_bid
            is_sold = num_bid_this_round == 0

    return {
        "is_sold": is_sold,
        "fail_to_sell": fail_to_sell,
        "apply_discount": apply_discount,
        "prev_round_max_bid": new_prev_round_max_bid,
    }


def hammer_fall() -> dict[str, Any]:
    """Vendored from ``src/auctioneer_base.py:162-173`` (``Auctioneer.hammer_fall``).

    Changes: returns the reset auctioneer-state fields instead of mutating
    ``self``; the ``print()`` call and ``auction_logs`` bookkeeping
    (presentation-only, superseded by AERead's own canonical trajectory
    recording) are not reproduced.
    """
    return {
        "cur_item": None,
        "highest_bidder": None,
        "highest_bid": -1,
        "prev_round_max_bid": -1,
        "fail_to_sell": False,
    }


def gather_all_status(bidders: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Vendored from ``src/auctioneer_base.py:178-185`` (``Auctioneer.gather_all_status``).

    Changes: takes bidder summaries as plain mappings (``{'name', 'profit',
    'items_won'}``) instead of ``Bidder`` objects; no logic changed.
    """
    status: dict[str, dict[str, Any]] = {}
    for bidder in bidders:
        status[bidder["name"]] = {
            "profit": bidder["profit"],
            "items_won": bidder["items_won"],
        }
    return status


__all__ = [
    "BID_NUMBER_RE",
    "Item",
    "UPSTREAM_COMMIT",
    "UPSTREAM_LICENSE",
    "UPSTREAM_REPO",
    "bid_rule",
    "bid_sanity_check",
    "check_hammer",
    "gather_all_status",
    "hammer_fall",
    "lose_bid",
    "record_bid",
    "set_withdraw",
    "win_bid",
]
