"""Kernel family plugin for the pinned Alympics Water Allocation Challenge.

Mirrors ``tau3_retail``'s ``environment.py`` shape (family manifest, plugin
registration, phase graph, scheduler hooks) but wraps a 5-seat simultaneous
sealed-bid repeated allocation instead of an alternating conversation. See
``docs/alympics_adapter_spec.md`` section 3 for the governing adapter
boundary.

Upstream's own game loop (``waterAllocation.run_single_round``) is a
monolithic call: it applies salary, collects each seat's bid via
``myPlayer.execute_bidding`` (which calls that seat's ``LLM.call``), parses
the freeform bidding text into a per-seat integer via
``waterAllocation._parse_result`` (which calls the *game's own* ``LLM.call``),
computes winners, settles balances/HP, and checks for total elimination --
all inside one Python call. The kernel's phase-graph model needs those steps
split across two boundaries it owns (``observe``/``parse_action`` before an
action is submitted, ``step`` after every seat's action for the round is
collected), which upstream's own method signature does not expose.

This module resolves that mismatch the same way spec section 3 describes:
every seat's bid is already known (parsed and legality-checked by the
scheduler) before ``step`` ever runs for a round, so ``step`` rebinds each
living seat's ``player.llm.call`` and the shared ``waterAllocation`` instance's
``llm.call`` to closures that echo back those already-decided bids -- never
sniffing or reconstructing them from prompt text -- and then calls upstream's
own ``run_single_round`` exactly once per round, unmodified. ``_get_salary``
and ``_check_winner`` are further wrapped *per scratch instance* (never on
the class) purely to *observe* their real, delegated results (the post-salary
balance and the winners list), which upstream's own method signatures do not
return to a caller; the wrapped code always calls straight through to the
original method before doing anything else, so the actual settlement
mechanics are still upstream's, executed exactly once, never reimplemented.
"""
from __future__ import annotations

import copy
import json
import logging
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .cases import (
    FAMILY_ID,
    FAMILY_VERSION,
    MAXIMUM_HEALTH,
    PERSONAS,
    POLICY_IDS,
    SEAT_ORDER,
    STARTING_BALANCE,
    STARTING_HP,
    STARTING_NO_DRINK,
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
)

PLUGIN_ID = "alympics_wac_environment"
SCORER_ID = "alympics_wac_scorer"
SEAT_ROLE = "player"
BID_PHASE = "bid"

SEAT_NAME_BY_ID: Mapping[str, str] = {
    seat: PERSONAS[seat]["upstream_name"] for seat in SEAT_ORDER
}
SEAT_ID_BY_NAME: Mapping[str, str] = {name: seat for seat, name in SEAT_NAME_BY_ID.items()}


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    Mirrors ``tau3_retail.environment._set_termination``: the declared
    ``TERMINATION_REASONS`` vocabulary and the reasons this module can
    actually produce must never drift apart.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


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
                "topology": "sealed_bid_repeated_allocation",
                "phase_specs": [BID_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                SEAT_ROLE: {"testable": True, "scripted_policies": list(POLICY_IDS)},
            },
            "measurement": {
                # Per docs/alympics_adapter_spec.md section 2 leaf 1
                # (primary, comparative): P01's audit verdict is
                # `baseline_only` -- never equate survival/wealth here with a
                # solved policy optimum. The full leaf vector (terminal
                # wealth, survival, bid legality, settlement exactness) is
                # built in milestone 2's measurement.py, not here.
                "primary_estimand": "alympics_wac_terminal_wealth",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "comparison_baseline": "proportional_all_seats",
                "bound_status": "baseline_only",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "AlympicsWacPlugin | None" = None,
    upstream_root: Path | str | None = None,
) -> "AlympicsWacPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if upstream_root is None:
            raise ValueError("upstream_root is required when plugin is not supplied")
        plugin = AlympicsWacPlugin(upstream_root=upstream_root)
    registry.register(family_manifest(), plugin)
    return plugin


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


# --------------------------------------------------------------------------
# Direct, unmodified import of the pinned upstream checkout (spec section 1:
# "No bridge" -- a plain sys.path-prefixed import, never copied, never
# written to).
# --------------------------------------------------------------------------

_UPSTREAM_ROOT_BY_MODULE: dict[str, str] = {}


def _install_openai_stub() -> None:
    """Install a safe placeholder before importing upstream, if needed.

    ``Alympics.py`` does a module-level ``import openai`` but touches no
    attribute on it at import time; ``LLM.__init__`` only ever *sets*
    attributes on it, and ``LLM.call`` (the only method that reads
    ``openai.ChatCompletion``) is always replaced per-instance below before
    it can ever run. Safe on any object, including a bare
    ``types.ModuleType`` placeholder -- installed only if nothing has
    already imported the real package in this process (harmless either way,
    since no code path here ever calls anything on it).
    """
    if "openai" not in sys.modules:
        sys.modules["openai"] = types.ModuleType("openai")


def _load_upstream(upstream_root: Path) -> Any:
    """Import the pinned upstream ``waterAllocation``/``Alympics`` modules.

    Read-only: ``sys.dont_write_bytecode`` is forced during the import so
    nothing is ever written into the pinned checkout's ``src/`` directory
    (not even a derived ``__pycache__`` entry).
    """
    root_key = str(Path(upstream_root).resolve())
    module_key = "waterAllocation"
    bound_root = _UPSTREAM_ROOT_BY_MODULE.get(module_key)
    if bound_root is not None and bound_root != root_key:
        raise RuntimeError(
            "alympics.wac already imported upstream from a different root; "
            f"expected {bound_root!r}, got {root_key!r}"
        )
    if bound_root == root_key and module_key in sys.modules:
        return sys.modules[module_key]

    _install_openai_stub()
    src_dir = str(Path(upstream_root) / "src")
    previous_flag = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        import waterAllocation as wa_module  # noqa: F401 (also imports Alympics)
    finally:
        sys.dont_write_bytecode = previous_flag

    # Python's own `import waterAllocation`, when the name is already in
    # `sys.modules`, returns the cached object without re-resolving against
    # `sys.path` -- if anything else in this process (an unrelated package,
    # a stray script, a leaked global from a prior test) had already bound
    # `sys.modules["waterAllocation"]` to a module from some other path,
    # the `import` statement above would silently hand back *that* module
    # instead. `_UPSTREAM_ROOT_BY_MODULE` only ever guarded this function's
    # own prior calls, never this; verify the resolved module's real file
    # actually lives under this exact pinned checkout before ever trusting
    # it -- the adapter's whole provenance claim ("direct, unmodified
    # import of the pinned upstream checkout... never a bridge, never
    # reimplemented", this module's own docstring) depends on it.
    resolved_file = Path(getattr(wa_module, "__file__", "") or "").resolve()
    expected_file = (Path(upstream_root) / "src" / "waterAllocation.py").resolve()
    if resolved_file != expected_file:
        raise RuntimeError(
            "waterAllocation resolved to an unexpected module -- expected "
            f"{expected_file!r}, got {resolved_file!r}; something else in "
            "this process may have already imported a module literally "
            "named 'waterAllocation' from a different path"
        )

    # Upstream logs every prompt/response at INFO level via its own
    # ``logging.basicConfig`` call; this adapter never reads or depends on
    # that output, so it is quieted purely for legible test/CI logs.
    logging.getLogger("waterAllocation").setLevel(logging.WARNING)
    _UPSTREAM_ROOT_BY_MODULE[module_key] = root_key
    return wa_module


class RoundOutcome(NamedTuple):
    """The result of delegating exactly one round to upstream's own code."""

    status: str  # "settled" | "all_seats_eliminated" | "malformed_action"
    players: Mapping[str, Mapping[str, int]] | None
    eliminated_this_round: tuple[str, ...]
    winners: tuple[str, ...]
    bid_legal: Mapping[str, bool]
    error: str | None


def _delegate_round(
    wa_module: Any,
    *,
    round_id: int,
    supply: int,
    alive_seats: tuple[str, ...],
    players_state: Mapping[str, Mapping[str, int]],
    bids: Mapping[str, int],
    force_malformed: str | None = None,
) -> RoundOutcome:
    """Delegate exactly one round of play to a fresh, scratch upstream instance.

    ``force_malformed`` is a test-only hook (``"missing_key"`` /
    ``"unparseable"``) that reproduces spec section 4's malformed-parse
    golden by breaking only the *scripted stand-in* for
    ``waterAllocation.llm.call`` -- never upstream's own parsing code, which
    is never touched. It must never be set by ``step``'s own production call.
    """
    game_setting = "alympics.wac scripted scratch instance (text content unused)"
    wa = wa_module.waterAllocation(game_setting)
    by_name = {player.name: player for player in wa.players}

    survivors = []
    for seat_id in alive_seats:
        name = SEAT_NAME_BY_ID[seat_id]
        player = by_name[name]
        snapshot = players_state[seat_id]
        player.balance = snapshot["balance"]
        player.hp = snapshot["hp"]
        player.no_drink = snapshot["no_drink"]
        player.bidding = bids[seat_id]
        survivors.append(player)
    wa.survival_players = survivors

    captured: dict[str, Any] = {
        "balance_after_salary": None,
        "bid_legal": None,
        "winners": None,
    }

    # Per-instance wraps (never class-level): each always calls straight
    # through to upstream's own unbound method first, then only *observes*
    # the real, delegated result for bookkeeping this method's own signature
    # does not return to a caller.
    original_get_salary = type(wa)._get_salary

    def _get_salary_wrapper(_orig=original_get_salary, _wa=wa, _captured=captured) -> None:
        _orig(_wa)
        _captured["balance_after_salary"] = {p.name: p.balance for p in _wa.survival_players}

    wa._get_salary = _get_salary_wrapper

    original_check_winner = type(wa)._check_winner

    def _check_winner_wrapper(
        supply_arg: int, _orig=original_check_winner, _wa=wa, _captured=captured
    ) -> list[str]:
        # Leaf 3's bid-legality gate (spec section 2/3): computed from the
        # real, just-captured post-salary balance, checked before
        # delegating to the real `_check_winner` -- never after.
        _captured["bid_legal"] = {
            player.name: player.bidding <= _captured["balance_after_salary"][player.name]
            for player in _wa.survival_players
        }
        result = _orig(_wa, supply_arg)
        _captured["winners"] = list(result)
        return result

    wa._check_winner = _check_winner_wrapper

    for player in survivors:
        this_bid = player.bidding
        player.llm.call = lambda message, _bid=this_bid: str(_bid)  # noqa: ARG005

    if force_malformed == "missing_key":
        omitted = survivors[0].name
        payload = {p.name: p.bidding for p in survivors if p.name != omitted}
        wa.llm.call = lambda message, _payload=payload: json.dumps(_payload)  # noqa: ARG005
    elif force_malformed == "unparseable":
        wa.llm.call = lambda message: "not-json-and-never-will-be"  # noqa: ARG005
    elif force_malformed is not None:
        raise ValueError(f"unknown force_malformed value: {force_malformed!r}")
    else:
        payload = {p.name: p.bidding for p in survivors}
        wa.llm.call = lambda message, _payload=payload: json.dumps(_payload)  # noqa: ARG005

    try:
        wa.run_single_round(round_id, supply)
    except SystemExit:
        status = "all_seats_eliminated"
    except (KeyError, TypeError) as error:
        # Settlement never ran, so nobody is actually known to be
        # eliminated or to have won this round -- `step` discards this
        # round entirely rather than guessing from a partial trace.
        return RoundOutcome(
            status="malformed_action",
            players=None,
            eliminated_this_round=(),
            winners=(),
            bid_legal=dict(captured["bid_legal"] or {}),
            error=f"{type(error).__name__}: {error}",
        )
    else:
        status = "settled"

    still_alive_names = {p.name for p in wa.survival_players}
    new_players: dict[str, dict[str, int]] = {}
    eliminated_this_round: list[str] = []
    for seat_id in alive_seats:
        name = SEAT_NAME_BY_ID[seat_id]
        player = by_name[name]
        new_players[seat_id] = {
            "balance": player.balance,
            "hp": player.hp,
            "no_drink": player.no_drink,
        }
        if name not in still_alive_names:
            eliminated_this_round.append(seat_id)

    winner_names = captured["winners"] or []
    winners = tuple(seat_id for seat_id in alive_seats if SEAT_NAME_BY_ID[seat_id] in winner_names)
    bid_legal = {
        seat_id: captured["bid_legal"][SEAT_NAME_BY_ID[seat_id]] for seat_id in alive_seats
    }

    return RoundOutcome(
        status=status,
        players=new_players,
        eliminated_this_round=tuple(eliminated_this_round),
        winners=winners,
        bid_legal=bid_legal,
        error=None,
    )


class AlympicsWacPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``."""

    def __init__(self, *, upstream_root: Path | str) -> None:
        self.upstream_root = Path(upstream_root)
        self._upstream_module: Any = None

    def _require_upstream(self) -> Any:
        if self._upstream_module is None:
            self._upstream_module = _load_upstream(self.upstream_root)
        return self._upstream_module

    # -- validation ---------------------------------------------------

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        expected_keys = {
            "grid_cell",
            "supply_schedule",
            "personas",
            "seat_order",
            "starting_state",
            "upstream_pin",
        }
        if set(data) != expected_keys:
            raise ValueError(f"payload must contain exactly {sorted(expected_keys)}")

        grid_cell = data["grid_cell"]
        if not isinstance(grid_cell, dict):
            raise ValueError("payload.grid_cell must be an object")
        rounds = grid_cell.get("rounds")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds <= 0:
            raise ValueError("payload.grid_cell.rounds must be a positive integer")

        supply_schedule = data["supply_schedule"]
        if not isinstance(supply_schedule, list) or len(supply_schedule) != rounds:
            raise ValueError(
                "payload.supply_schedule must be a list of length payload.grid_cell.rounds"
            )
        if any(not isinstance(value, int) or value < 0 for value in supply_schedule):
            raise ValueError("payload.supply_schedule must contain non-negative integers")

        if data["personas"] != _plain(PERSONAS):
            raise ValueError("payload.personas does not match the upstream-fixed roster")
        if tuple(data["seat_order"]) != SEAT_ORDER:
            raise ValueError("payload.seat_order does not match the declared seat order")
        if data["starting_state"] != {
            "balance": STARTING_BALANCE,
            "hp": STARTING_HP,
            "no_drink": STARTING_NO_DRINK,
            "maximum_health": MAXIMUM_HEALTH,
        }:
            raise ValueError("payload.starting_state does not match upstream's myPlayer defaults")

        pin = data["upstream_pin"]
        if pin.get("repo") != UPSTREAM_REPO or pin.get("commit") != UPSTREAM_COMMIT:
            raise ValueError("payload.upstream_pin does not match the pinned upstream commit")

        revision = subprocess.run(
            ["git", "-C", str(self.upstream_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if revision.returncode != 0:
            raise ValueError(
                "upstream_root is not a readable git checkout: "
                f"{revision.stderr.strip()}"
            )
        if revision.stdout.strip() != UPSTREAM_COMMIT:
            raise ValueError(
                "upstream checkout revision mismatch: "
                f"expected {UPSTREAM_COMMIT}, got {revision.stdout.strip()}"
            )
        status = subprocess.run(
            ["git", "-C", str(self.upstream_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout:
            raise ValueError("upstream checkout must be clean at the pinned revision")

        return data

    # -- phase graph and initial state ---------------------------------

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        del cell
        grid_cell = family_case["grid_cell"]
        players = {
            seat: {
                "balance": STARTING_BALANCE,
                "hp": STARTING_HP,
                "no_drink": STARTING_NO_DRINK,
                "alive": True,
            }
            for seat in SEAT_ORDER
        }
        return {
            "round_id": 1,
            "rounds_total": grid_cell["rounds"],
            "supply_schedule": list(family_case["supply_schedule"]),
            "players": players,
            "eliminated_order": [],
            "round_log": [],
            "termination": None,
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        rounds_total = family_case["grid_cell"]["rounds"]
        max_actions = len(SEAT_ORDER) * rounds_total
        return (
            PhaseSpec(
                phase_id=BID_PHASE,
                actor_selector="survival_players",
                mode="simultaneous",
                observation_schema_by_role={SEAT_ROLE: "alympics_wac_bid_observation_v1"},
                action_schema_by_role={SEAT_ROLE: "alympics_wac_bid_action_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(BID_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del family_case, phase
        return tuple(seat for seat in SEAT_ORDER if state["players"][seat]["alive"])

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        del phase
        if seat_id not in SEAT_ORDER:
            raise ValueError(f"unknown seat: {seat_id!r}")
        player_state = state["players"][seat_id]
        if not player_state["alive"]:
            raise ValueError(f"seat {seat_id!r} is already eliminated")
        persona = PERSONAS[seat_id]
        round_id = state["round_id"]
        # Upstream's own `run_single_round` (`waterAllocation.py:150-171`)
        # calls `_get_salary()` (step 1) before `execute_bidding()` (step 2,
        # which embeds `get_status()` -- the post-salary balance -- into the
        # very prompt the agent bids from): every round, including round 1,
        # a real upstream agent already sees this round's salary credited
        # before deciding its bid. `player_state["balance"]` here is the
        # figure carried over from the *previous* round's settlement (never
        # mutated until `_delegate_round` actually runs, later, for this
        # round) -- one salary payment short of what upstream would show --
        # so the observed balance projects that credit forward the same way
        # upstream's own `get_status()` already would.
        balance_after_salary = player_state["balance"] + persona["daily_salary"]
        return {
            "seat_id": seat_id,
            "requirement": persona["requirement"],
            "daily_salary": persona["daily_salary"],
            # This seat's own status only -- never another seat's balance,
            # HP, no-drink streak, or (this round's) bid; leakage-audit
            # prerequisite for leaf 4 (spec section 2).
            "balance": balance_after_salary,
            "hp": player_state["hp"],
            "no_drink": player_state["no_drink"],
            "maximum_health": MAXIMUM_HEALTH,
            "round_id": round_id,
            "rounds_total": state["rounds_total"],
            "supply": state["supply_schedule"][round_id - 1],
            # Prior rounds' *public* settlement only -- round id, supply,
            # and who won (already public via upstream's own broadcast
            # winner announcement) -- mirroring upstream's own
            # `round_results_prompt`, which every surviving player's own
            # `history` accumulates each round. Deliberately never any
            # seat's balance/hp/no_drink (upstream's broadcast includes
            # every survivor's full status; this adapter's own leakage-audit
            # boundary -- spec section 2 leaf 4 -- does not permit that, a
            # documented, intentional narrowing of upstream's fuller
            # broadcast; see docs/alympics_adapter_spec.md section 6).
            "public_round_history": [
                {
                    "round_id": entry["round_id"],
                    "supply": entry["supply"],
                    "winners": list(entry["winners"]),
                    # Codex triage finding 1's still-open sub-claim
                    # (docs/alympics_fix_verification.md): upstream's own
                    # `round_results_prompt` broadcasts every survivor's bid
                    # for a round it has already settled (`bidding_details`)
                    # to every surviving player's own history -- fully
                    # public the instant a round completes, never a leak of
                    # a not-yet-revealed bid (only rounds already appended
                    # to `state["round_log"]` are ever included here; this
                    # round's own, not-yet-collected bids never are).
                    "bids": dict(entry["bids"]),
                }
                for entry in state["round_log"]
            ],
        }

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, state, seat_id, phase
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        if set(raw) != {"bid"}:
            return ParseResult.failure("bid_action_must_contain_exactly_bid")
        bid = raw["bid"]
        if isinstance(bid, bool) or not isinstance(bid, int) or bid < 0:
            return ParseResult.failure("bid_must_be_a_nonnegative_integer")
        return ParseResult.success({"bid": bid})

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, state, seat_id, phase
        bid = action["bid"]
        if isinstance(bid, bool) or not isinstance(bid, int) or bid < 0:
            return LegalityResult.illegal("bid_must_be_a_nonnegative_integer")
        # A bid that exceeds this seat's balance is deliberately NOT
        # rejected here. Upstream's own `_check_winner` never rejects it
        # either -- it just silently excludes it from winning, with no
        # error and no distinguishing flag (governing facts). Rejecting the
        # *action* here (`invalid_action_policy="reject"`) would abort the
        # whole episode, which is neither upstream's behavior nor what leaf
        # 3 asks for (spec section 2/4 golden 3): the round -- and the
        # other seats -- continue normally, and `step` records a per-seat,
        # per-round `bid_legal` flag in the round log for the measurement
        # layer to consume, never a hard scheduler-level rejection.
        return LegalityResult.legal_action()

    # -- transition -----------------------------------------------------

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        del phase
        new_state = _plain(state)
        round_id = new_state["round_id"]
        supply = new_state["supply_schedule"][round_id - 1]
        alive_seats = tuple(
            seat for seat in SEAT_ORDER if new_state["players"][seat]["alive"]
        )
        bids = {seat: actions[seat].action["bid"] for seat in alive_seats}
        # Sealed pre-round snapshot (spec section 2 leaf 4 / section 5's
        # Gate 2 requirement 2: "reconstruct transitions from sealed
        # observations ... and pre-state"). Captured here, before
        # `_delegate_round` runs, so milestone 2's `measurement.py` can
        # shadow-recompute this exact round from evidence alone, never by
        # reading back through the mutated live state.
        players_before = {
            seat: dict(new_state["players"][seat]) for seat in alive_seats
        }
        for snapshot in players_before.values():
            snapshot.pop("alive", None)

        upstream = self._require_upstream()
        outcome = _delegate_round(
            upstream,
            round_id=round_id,
            supply=supply,
            alive_seats=alive_seats,
            players_state=new_state["players"],
            bids=bids,
        )

        if outcome.status == "malformed_action":
            new_state["round_log"].append(
                {
                    "round_id": round_id,
                    "supply": supply,
                    "bids": bids,
                    "status": "malformed_action",
                    "error": outcome.error,
                    "players_before": players_before,
                    "players_after": None,
                }
            )
            _set_termination(new_state, "malformed_action")
            return TransitionResult(
                state=new_state,
                next_phase_id=None,
                consequences={"round": round_id, "status": "malformed_action"},
            )

        for seat in alive_seats:
            new_state["players"][seat].update(outcome.players[seat])
        for seat in outcome.eliminated_this_round:
            new_state["players"][seat]["alive"] = False
        new_state["eliminated_order"].extend(outcome.eliminated_this_round)
        new_state["round_log"].append(
            {
                "round_id": round_id,
                "supply": supply,
                "bids": bids,
                "bid_legal": dict(outcome.bid_legal),
                "winners": list(outcome.winners),
                "eliminated_this_round": list(outcome.eliminated_this_round),
                "status": outcome.status,
                "players_before": players_before,
                "players_after": dict(outcome.players),
            }
        )

        if outcome.status == "all_seats_eliminated":
            _set_termination(new_state, "all_seats_eliminated")
        elif round_id >= new_state["rounds_total"]:
            _set_termination(new_state, "rounds_exhausted")
        else:
            new_state["round_id"] = round_id + 1

        return TransitionResult(
            state=new_state,
            next_phase_id=(None if new_state["termination"] else BID_PHASE),
            consequences={"round": round_id, "supply": supply},
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        return {
            "reason": reason,
            "round_id": state["round_id"],
            "players": state["players"],
            "eliminated_order": state["eliminated_order"],
            "round_log": state["round_log"],
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "final_round_id": terminal["round_id"],
            "final_players": terminal["players"],
            "eliminated_order": terminal["eliminated_order"],
        }

    # -- scoring (spec section 2; leaves built in measurement.py) --

    def build_scorer(self, family_case: Mapping[str, Any]) -> Any:
        # Deferred import: measurement.py imports `_delegate_round` from
        # this module at its own top level (leaf 4's shadow-recompute needs
        # it), so importing measurement.py back at *this* module's top
        # level would be circular. By the time anything actually calls
        # `build_scorer`, this module has already finished importing, so
        # the deferred import here resolves cleanly (mirrors
        # ``tau3_retail``'s top-level import, which has no such cycle to
        # avoid because its measurement.py never imports its
        # environment.py).
        from .measurement import build_scorer as build_measurement_scorer

        return build_measurement_scorer(family_case)

    def build_reference_providers(
        self, family_case: Mapping[str, Any]
    ) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None


__all__ = [
    "BID_PHASE",
    "PLUGIN_ID",
    "SCORER_ID",
    "SEAT_ID_BY_NAME",
    "SEAT_NAME_BY_ID",
    "SEAT_ROLE",
    "AlympicsWacPlugin",
    "RoundOutcome",
    "family_manifest",
    "register_plugin",
]
