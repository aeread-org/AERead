"""Kernel family plugin for AERead-authored ``aucarena`` scenarios.

One phase, self-looping per bidding round (``docs/aucarena_adapter_spec.md``
section 3, "Phase graph"): every eligible seat (the roster minus the current
highest bidder minus any seat withdrawn on this item) submits one bid
decision per round; ``step`` applies the vendored bid-legality, bid-
recording, and hammer-determination rules from ``_vendored_upstream.py`` and
either continues the round, advances to the next item, or ends the episode.
The Auctioneer is environment-owned bookkeeping, not a seat.

A ``"rule"`` seat's bid is computed internally from the vendored
``bid_rule`` -- its raw response is accepted but never inspected, mirroring
upstream's own ``Bidder.bid`` short-circuit (returns ``''`` for
``model_name == "rule"``; ``auction_workflow.py`` calls ``bid_rule``
directly instead of parsing that return value). A ``"scripted"`` seat's raw
text response is parsed with upstream's own non-LLM signal rule (a literal
``-1`` sentinel, else the last ``\\$?\\d+`` match, else malformed) -- the
same rule ``Auctioneer.parse_bid`` applies after its own (unvendored, LLM-
backed) text-normalization step; see ``_vendored_upstream.py``'s module
docstring for why that upstream method itself is not vendored.
"""
from __future__ import annotations

import random
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from . import _vendored_upstream as vendored
from .cases import (
    FAMILY_ID,
    FAMILY_VERSION,
    ITEM_POOL_SHA256,
    MAX_LOGICAL_ACTIONS,
    TERMINATION_REASONS,
)
from .measurement import AucArenaScorer, build_scorer as build_measurement_scorer

PLUGIN_ID = "aucarena_environment"
SCORER_ID = "aucarena_scorer"
BID_ROUND_PHASE = "bid_round"
MODEL_NAMES = ("rule", "scripted")
_REQUIRED_PAYLOAD_KEYS = {
    "item_ids",
    "item_pool_sha256",
    "items",
    "roster",
    "min_markup_pct",
    "enable_discount",
}
_REQUIRED_ITEM_KEYS = {"id", "name", "price", "desc", "true_value"}
_REQUIRED_ROSTER_KEYS = {"seat_id", "model_name", "budget", "max_bid_cnt"}


def family_manifest() -> FamilyManifest:
    """Return the strict family declaration used by the trusted registry."""
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "sequential_ascending_auction",
                "phase_specs": [BID_ROUND_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "bidder": {"testable": True, "scripted_policies": ["scripted", "rule"]},
            },
            "measurement": {
                # No objective_reference leaf is declared (spec section 2):
                # profit and TrueSkill do not solve the auction policy game.
                # The estimand of primary interest is the comparative one;
                # the three rule_constraint leaves are declared and scored
                # alongside it, never scalar-collapsed into this field.
                "primary_estimand": "aucarena_profit_vs_field",
                "measurement_kind": "comparative_or_human_judged",
                "direction": "maximize",
                "outcome_support": "case_specific",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry, *, plugin: "AucArenaPlugin | None" = None
) -> "AucArenaPlugin":
    """Register one exact family/version binding in the kernel registry."""
    resolved = plugin if plugin is not None else AucArenaPlugin()
    registry.register(family_manifest(), resolved)
    return resolved


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _item_from_dict(item: Mapping[str, Any]) -> vendored.Item:
    return vendored.Item(
        id=item["id"],
        name=item["name"],
        price=item["price"],
        desc=item["desc"],
        true_value=item["true_value"],
    )


class AucArenaPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``.

    Fully self-contained: unlike ``tau3_retail``, no upstream checkout, git
    root, or bridge is required at runtime -- the pinned item data is
    materialized into the case payload at import time (``cases.py``), and
    every rule this plugin applies is a vendored pure function
    (``_vendored_upstream.py``). Replaying an episode therefore never
    imports upstream code and never touches the network.
    """

    # ---------------------------------------------------------------- #
    # Payload validation and initial state.
    # ---------------------------------------------------------------- #

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != _REQUIRED_PAYLOAD_KEYS:
            raise ValueError(
                f"payload must contain exactly {sorted(_REQUIRED_PAYLOAD_KEYS)}, "
                f"got {sorted(data)}"
            )
        if data["item_pool_sha256"] != ITEM_POOL_SHA256:
            raise ValueError(
                "payload item_pool_sha256 does not match the pinned item pool"
            )
        item_ids = data["item_ids"]
        if not isinstance(item_ids, list) or not item_ids:
            raise ValueError("payload.item_ids must be a non-empty array")
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("payload.item_ids must not repeat an item id")

        items = data["items"]
        if not isinstance(items, list) or len(items) != len(item_ids):
            raise ValueError("payload.items must have exactly one entry per item_ids")
        for index, (item_id, item) in enumerate(zip(item_ids, items)):
            if not isinstance(item, dict) or set(item) != _REQUIRED_ITEM_KEYS:
                raise ValueError(f"payload.items[{index}] has the wrong shape")
            if item["id"] != item_id:
                raise ValueError(
                    f"payload.items[{index}].id {item['id']!r} does not match "
                    f"payload.item_ids[{index}] {item_id!r}"
                )

        roster = data["roster"]
        if not isinstance(roster, list) or not roster:
            raise ValueError("payload.roster must be a non-empty array")
        seat_ids = [seat.get("seat_id") for seat in roster]
        if len(set(seat_ids)) != len(seat_ids):
            raise ValueError("payload.roster must not repeat a seat_id")
        for index, seat in enumerate(roster):
            if not isinstance(seat, dict) or set(seat) != _REQUIRED_ROSTER_KEYS:
                raise ValueError(f"payload.roster[{index}] has the wrong shape")
            if seat["model_name"] not in MODEL_NAMES:
                raise ValueError(
                    f"payload.roster[{index}].model_name must be one of "
                    f"{MODEL_NAMES}, got {seat['model_name']!r}"
                )
            if not isinstance(seat["budget"], int) or seat["budget"] < 0:
                raise ValueError(f"payload.roster[{index}].budget must be a non-negative int")
            if not isinstance(seat["max_bid_cnt"], int) or seat["max_bid_cnt"] < 0:
                raise ValueError(
                    f"payload.roster[{index}].max_bid_cnt must be a non-negative int"
                )

        min_markup_pct = data["min_markup_pct"]
        if not isinstance(min_markup_pct, (int, float)) or not (0 < min_markup_pct <= 1):
            raise ValueError("payload.min_markup_pct must be in (0, 1]")
        if data["enable_discount"] is not False:
            raise ValueError(
                "enable_discount must be False -- the price-cut path is out of "
                "this adapter's scope (docs/aucarena_adapter_spec.md section 7)"
            )
        return data

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        seat_order = [seat["seat_id"] for seat in family_case["roster"]]
        seats = {
            seat["seat_id"]: {
                "model_name": seat["model_name"],
                "max_bid_cnt": seat["max_bid_cnt"],
                "budget": seat["budget"],
                "rule_bid_cnt": 0,
                "withdraw": False,
                "profit": 0,
                "items_won": [],
            }
            for seat in family_case["roster"]
        }
        return {
            "world_seed": int(cell.world_seed),
            "items": [dict(item) for item in family_case["items"]],
            "min_markup_pct": family_case["min_markup_pct"],
            "enable_discount": family_case["enable_discount"],
            "cur_item_index": 0,
            "bid_round": 0,
            "highest_bidder": None,
            "highest_bid": -1,
            "prev_round_max_bid": -1,
            "seat_order": seat_order,
            "seats": seats,
            "termination": None,
            "sold_log": [],
        }

    # ---------------------------------------------------------------- #
    # Phase graph.
    # ---------------------------------------------------------------- #

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del family_case
        return (
            PhaseSpec(
                phase_id=BID_ROUND_PHASE,
                actor_selector="eligible_bidders",
                mode="simultaneous",
                observation_schema_by_role={"bidder": "aucarena_bid_observation_v1"},
                action_schema_by_role={"bidder": "aucarena_bid_response_v1"},
                max_logical_actions=MAX_LOGICAL_ACTIONS,
                invalid_action_policy="family_defined",
                next_phases=(BID_ROUND_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del family_case
        if phase.phase_id != BID_ROUND_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        return tuple(
            seat_id
            for seat_id in state["seat_order"]
            if seat_id != state["highest_bidder"] and not state["seats"][seat_id]["withdraw"]
        )

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        del family_case
        if phase.phase_id != BID_ROUND_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        cur_item = state["items"][state["cur_item_index"]]
        seat = state["seats"][seat_id]
        min_bid_increase = int(state["min_markup_pct"] * cur_item["price"])
        if state["highest_bidder"] is None:
            minimum_next_bid = cur_item["price"]
        else:
            minimum_next_bid = max(cur_item["price"], state["highest_bid"] + min_bid_increase)
        return {
            "cur_item": dict(cur_item),
            "bid_round": state["bid_round"],
            "highest_bid": state["highest_bid"],
            "highest_bidder": state["highest_bidder"],
            "minimum_next_bid": minimum_next_bid,
            "min_markup_pct": state["min_markup_pct"],
            "own_seat_id": seat_id,
            "own_model_name": seat["model_name"],
            "own_budget": seat["budget"],
            "own_items_won": list(seat["items_won"]),
            "items_remaining": len(state["items"]) - state["cur_item_index"],
        }

    # ---------------------------------------------------------------- #
    # Parse / legality / step.
    # ---------------------------------------------------------------- #

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, phase
        seat = state["seats"][seat_id]
        if seat["model_name"] == "rule":
            # Mirrors auction_workflow.py:123-124: for a rule bidder the bid
            # price is computed by calling bid_rule directly; the raw
            # response (upstream's Bidder.bid() == '' for this model_name)
            # is accepted but never inspected.
            cur_item = state["items"][state["cur_item_index"]]
            bid_price, rule_bid_cnt = vendored.bid_rule(
                cur_bid=state["prev_round_max_bid"],
                cur_item_price=cur_item["price"],
                budget=seat["budget"],
                rule_bid_cnt=seat["rule_bid_cnt"],
                max_bid_cnt=seat["max_bid_cnt"],
                min_markup_pct=state["min_markup_pct"],
            )
            return ParseResult.success({"bid_price": bid_price, "rule_bid_cnt": rule_bid_cnt})

        if not isinstance(response, str):
            return ParseResult.failure("response_not_text")
        if "-1" in response:
            bid_price = -1
        else:
            matches = vendored.BID_NUMBER_RE.findall(response.replace(",", ""))
            if not matches:
                return ParseResult.failure("malformed_operational")
            bid_price = int(matches[-1].replace("$", ""))
        return ParseResult.success({"bid_price": bid_price, "rule_bid_cnt": seat["rule_bid_cnt"]})

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, phase
        seat = state["seats"][seat_id]
        cur_item = state["items"][state["cur_item_index"]]
        fail_msg = vendored.bid_sanity_check(
            action["bid_price"],
            state["prev_round_max_bid"],
            cur_item["price"],
            seat["budget"],
            state["min_markup_pct"],
        )
        if fail_msg is None:
            return LegalityResult.legal_action()
        return LegalityResult.illegal(fail_msg)

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        del family_case
        if phase.phase_id != BID_ROUND_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        new_state = _plain(state)
        seats = new_state["seats"]
        cur_item = new_state["items"][new_state["cur_item_index"]]
        world_seed = new_state["world_seed"]
        bid_round = new_state["bid_round"]

        highest_bid = new_state["highest_bid"]
        highest_bidder = new_state["highest_bidder"]
        round_bids: list[dict[str, Any]] = []
        call_index = 0

        # Roster order (not dict-iteration order), matching upstream's
        # bidder_list processing order in auction_workflow.py -- record_bid's
        # tie-break is order-sensitive.
        for seat_id in new_state["seat_order"]:
            envelope = actions.get(seat_id)
            if envelope is None:
                continue  # not eligible this round (excluded or withdrawn)
            if not envelope.valid:
                continue  # illegal or malformed: zero mutation (spec goldens 3/4)
            action = envelope.action
            seat = seats[seat_id]
            bid_price = action["bid_price"]
            if seat["model_name"] == "rule":
                seat["rule_bid_cnt"] = action["rule_bid_cnt"]
            seat["withdraw"] = vendored.set_withdraw(bid_price)
            round_bids.append({"bidder": seat_id, "bid": bid_price})
            rng = random.Random(f"{world_seed}_{cur_item['id']}_{bid_round}_{call_index}")
            call_index += 1
            highest_bid, highest_bidder = vendored.record_bid(
                round_bids, highest_bid, highest_bidder, rng=rng
            )

        num_bid_this_round = vendored._num_bids_in_round(round_bids)
        hammer = vendored.check_hammer(
            highest_bidder_is_none=highest_bidder is None,
            num_bid_this_round=num_bid_this_round,
            bid_round=bid_round,
            enable_discount=new_state["enable_discount"],
            prev_round_max_bid=new_state["prev_round_max_bid"],
            highest_bid=highest_bid,
        )
        if hammer["apply_discount"]:
            # enable_discount is validated False for every case this family
            # admits (validate_payload); unreachable given that invariant.
            raise RuntimeError(
                "enable_discount price-cut path is out of this adapter's scope "
                "(docs/aucarena_adapter_spec.md section 7)"
            )

        new_state["highest_bid"] = highest_bid
        new_state["highest_bidder"] = highest_bidder
        new_state["prev_round_max_bid"] = hammer["prev_round_max_bid"]

        if not hammer["is_sold"]:
            new_state["bid_round"] = bid_round + 1
            return TransitionResult(
                state=new_state,
                next_phase_id=BID_ROUND_PHASE,
                consequences={"item_id": cur_item["id"], "bid_round": bid_round, "sold": False},
            )

        winner = highest_bidder
        hammer_price = highest_bid if winner is not None else None
        if winner is not None:
            winner_seat = seats[winner]
            new_budget, new_profit, new_items_won = vendored.win_bid(
                budget=winner_seat["budget"],
                profit=winner_seat["profit"],
                items_won=[tuple(pair) for pair in winner_seat["items_won"]],
                item=_item_from_dict(cur_item),
                bid=hammer_price,
            )
            winner_seat["budget"] = new_budget
            winner_seat["profit"] = new_profit
            winner_seat["items_won"] = [list(pair) for pair in new_items_won]
        for seat_id, seat in seats.items():
            if seat_id != winner:
                vendored.lose_bid(_item_from_dict(cur_item))  # message only; no state effect

        new_state["sold_log"].append(
            {
                "item_id": cur_item["id"],
                "sold": winner is not None,
                "winner": winner,
                "hammer_price": hammer_price,
            }
        )

        reset = vendored.hammer_fall()
        new_state["highest_bid"] = reset["highest_bid"]
        new_state["highest_bidder"] = reset["highest_bidder"]
        new_state["prev_round_max_bid"] = reset["prev_round_max_bid"]
        new_state["bid_round"] = 0
        new_state["cur_item_index"] = new_state["cur_item_index"] + 1
        for seat in seats.values():
            seat["rule_bid_cnt"] = 0
            seat["withdraw"] = False

        if new_state["cur_item_index"] >= len(new_state["items"]):
            new_state["termination"] = "auction_complete"
            next_phase_id = None
        else:
            next_phase_id = BID_ROUND_PHASE

        return TransitionResult(
            state=new_state,
            next_phase_id=next_phase_id,
            consequences={
                "item_id": cur_item["id"],
                "bid_round": bid_round,
                "sold": winner is not None,
                "winner": winner,
                "hammer_price": hammer_price,
            },
        )

    # ---------------------------------------------------------------- #
    # Terminal / outcome.
    # ---------------------------------------------------------------- #

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        if reason not in TERMINATION_REASONS:
            raise ValueError(
                f"termination reason {reason!r} is not declared by this family; "
                f"declared reasons are {list(TERMINATION_REASONS)}"
            )
        return {
            "reason": reason,
            "sold_log": [dict(entry) for entry in state["sold_log"]],
            "seats": {
                seat_id: dict(seat) for seat_id, seat in state["seats"].items()
            },
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "items": [dict(entry) for entry in terminal["sold_log"]],
            "seats": {
                seat_id: {
                    "profit": seat["profit"],
                    "budget": seat["budget"],
                    "items_won": [list(pair) for pair in seat["items_won"]],
                    "model_name": seat["model_name"],
                }
                for seat_id, seat in terminal["seats"].items()
            },
        }

    # ---------------------------------------------------------------- #
    # Measurement (docs/aucarena_adapter_spec.md section 2).
    # ---------------------------------------------------------------- #

    def build_scorer(self, family_case: Mapping[str, Any]) -> AucArenaScorer:
        """Return the four declared measurement leaves plus their scorers.

        See ``measurement.py`` (spec section 2): ``aucarena_budget_invariant``,
        ``aucarena_bid_legality``, ``aucarena_hammer_rule``, and
        ``aucarena_profit_vs_field`` are declared for every case -- no
        ``objective_reference`` leaf, no scalar collapse. The current kernel
        does not yet call ``build_scorer`` itself (mirrors
        ``tau3_retail.Tau3RetailPlugin.build_scorer``'s own docstring); this
        makes the declaration and all four scorers live the day it does.
        """
        return build_measurement_scorer(family_case)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None


__all__ = [
    "AucArenaPlugin",
    "BID_ROUND_PHASE",
    "PLUGIN_ID",
    "SCORER_ID",
    "family_manifest",
    "register_plugin",
]
