"""Kernel family plugin for the pinned upstream negarena games.

Mode B (spec section 3): two single-actor phases, strict alternation, no
environment seat. ``red_turn``/``blue_turn`` are shared across both
``buy_sell`` and ``ultimatum`` splits -- both upstream games use identical
seat labels (``AGENT_ONE = "Player RED"``, ``AGENT_TWO = "Player BLUE"``;
RED always moves first) even though their settlement math differs.

Only ``step`` changes canonical family state. ``parse_action``/``legal``
delegate to upstream's own parser classes and trade/resource admission-gate
methods through :class:`~aeread_families.negarena.negarena_bridge.NegarenaBridge`
-- never reimplementing the tag grammar or the legality arithmetic (spec
section 3). ``terminal``/``outcome`` report only structural facts
(termination reason, iteration count, last trade/answer), never a payoff:
settlement (``after_game_ends()``, delegated to the bridge) and the two
declared verifier leaves live in ``measurement.py``, reached through
``build_scorer`` (spec section 2).
"""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    ActionEnvelope,
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from . import measurement
from .cases import FAMILY_ID, FAMILY_VERSION, RED, BLUE, UPSTREAM_COMMIT, UPSTREAM_REPO
from .negarena_bridge import NegarenaBridge

PLUGIN_ID = "negarena_environment"
SCORER_ID = "negarena_scorer"
RED_PHASE = "red_turn"
BLUE_PHASE = "blue_turn"
SEATS = (RED, BLUE)

# Upstream's own literal tag values (negotiationarena/constants.py):
# ACCEPTING_TAG, REJECTION_TAG. Compared verbatim, never re-derived.
ACCEPT_ANSWER = "ACCEPT"
REJECT_ANSWER = "REJECT"

_BUY_SELL_SEAT_KEYS = {"goal_kind", "starting_resources", "valuation"}
_ULTIMATUM_SEAT_KEYS = {"starting_resources"}


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _measurement_reference_provider_ids() -> list[str]:
    """Every implementation id either declared leaf actually references.

    Derived from ``measurement.py``'s own leaf builders (never a duplicated
    literal here) so this list can never drift from what the leaves really
    declare. Required so ``resolve_run_plan`` reserves and admits an
    ``ImplementationPin`` for each one: without this,
    ``EvaluationReceipt``'s own pin/implementation cross-check
    (``receipts.py``'s ``_validate_and_freeze_plan_pins``) rejects every
    negarena receipt outright, since none of these ids were ever declared
    anywhere a plan's required pins are computed from
    (docs/negarena_codex_triage.md Finding 1's regression test is the first
    thing in this repo to actually seal a negarena
    ``EvaluationReceipt`` and is what surfaced this gap).
    """
    seat_leaf = measurement.build_seat_outcome_leaf()
    agreement_leaf = measurement.build_agreement_reached_leaf()
    return sorted(
        {
            seat_leaf.estimand.validity_domain.predicate.implementation_id,
            seat_leaf.verifier.reference.implementation.implementation_id,
            seat_leaf.scorer.implementation_id,
            agreement_leaf.verifier.reference.implementation.implementation_id,
            agreement_leaf.scorer.implementation_id,
        }
    )


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
                "topology": "alternating_negotiation",
                "phase_specs": [RED_PHASE, BLUE_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                RED: {"testable": True, "scripted_policies": ["scripted"]},
                BLUE: {"testable": True, "scripted_policies": ["scripted"]},
            },
            "measurement": {
                # Leaf 1 (primary), spec section 2: opponent-dependent, no
                # fixed target -- deliberately no optimum bounds declared.
                "primary_estimand": "negarena_seat_outcome",
                "measurement_kind": "comparative_or_human_judged",
                "direction": "maximize",
                # kernel_scoring_contract_spec.md section 3 (migration
                # milestone 2 of 3): every leaf this family publishes at
                # finalize time, exactly one primary, and precisely the
                # leaves that gate admission -- declared here, the one
                # source of truth, never inferred from `build_scorer` or a
                # test fixture. Both leaves are `scope="finalize_time"`:
                # every scorer in measurement.py is
                # `evaluation_class="deterministic"` with no judge, rater,
                # or other not-yet-existing artifact dependency (spec
                # section 4), so neither is `deferred`. Leaf 1
                # (`negarena_seat_outcome`) is inherently per seat --
                # "what did THIS seat realize" -- so it is declared
                # `seat_scope="subject_seat"` (ruling R12); leaf 2 (the
                # whole-episode agreement predicate) is not a function of
                # which seat is the tested subject and stays the default
                # `seat_scope="cell"`. See docs/negarena_adapter_status.md's
                # "Leaf policy" section for why `negarena_seat_outcome` is
                # primary and why it alone gates admission.
                "leaves": [
                    {
                        "leaf_id": measurement.SEAT_OUTCOME_LEAF_ID,
                        "scope": "finalize_time",
                        "seat_scope": "subject_seat",
                    },
                    {"leaf_id": measurement.AGREEMENT_LEAF_ID, "scope": "finalize_time"},
                ],
                "primary_leaf_id": measurement.SEAT_OUTCOME_LEAF_ID,
                "admission_leaf_ids": [measurement.SEAT_OUTCOME_LEAF_ID],
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "reference_provider_ids": _measurement_reference_provider_ids(),
            },
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "NegarenaPlugin | None" = None,
    upstream_root: Path | str | None = None,
    bridge: NegarenaBridge | None = None,
) -> "NegarenaPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if upstream_root is None:
            raise ValueError("upstream_root is required when plugin is not supplied")
        plugin = NegarenaPlugin(upstream_root=upstream_root, bridge=bridge)
    registry.register_trusted(family_manifest(), plugin)
    return plugin


def _other_seat(seat_id: str) -> str:
    return BLUE if seat_id == RED else RED


def _validate_resources(value: Any, path: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{path} must be a non-empty object")
    result: dict[str, int] = {}
    for token, amount in value.items():
        if not isinstance(token, str) or not token:
            raise ValueError(f"{path} keys must be non-empty strings")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise ValueError(f"{path}.{token} must be a non-negative integer")
        result[token] = amount
    return result


class NegarenaPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``."""

    def __init__(self, *, upstream_root: Path | str, bridge: NegarenaBridge | None) -> None:
        self.upstream_root = Path(upstream_root)
        self.bridge = bridge

    # -- validation ---------------------------------------------------

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != {"scenario", "pins"}:
            raise ValueError("payload must contain exactly scenario and pins")
        pins = data["pins"]
        scenario = data["scenario"]
        if not isinstance(pins, dict) or not isinstance(scenario, dict):
            raise ValueError("payload.pins and payload.scenario must be objects")
        if pins.get("upstream_repo") != UPSTREAM_REPO:
            raise ValueError("payload pins the wrong upstream repository")
        if pins.get("upstream_commit") != UPSTREAM_COMMIT:
            raise ValueError("payload pins the wrong upstream commit")

        game_kind = scenario.get("game_kind")
        if game_kind not in {"buy_sell", "ultimatum"}:
            raise ValueError(f"payload.scenario.game_kind must be buy_sell or ultimatum, got {game_kind!r}")
        iterations = scenario.get("iterations")
        if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations <= 0:
            raise ValueError("payload.scenario.iterations must be a positive integer")
        if not isinstance(scenario.get("money_token"), str) or not scenario["money_token"]:
            raise ValueError("payload.scenario.money_token must be a non-empty string")

        seats = scenario.get("seats")
        if not isinstance(seats, dict) or set(seats) != {RED, BLUE}:
            raise ValueError("payload.scenario.seats must declare exactly red and blue")
        if game_kind == "buy_sell":
            if not isinstance(scenario.get("resource_token"), str) or not scenario["resource_token"]:
                raise ValueError("buy_sell payload.scenario.resource_token must be a non-empty string")
            for seat_id, seat in seats.items():
                if not isinstance(seat, dict) or set(seat) != _BUY_SELL_SEAT_KEYS:
                    raise ValueError(f"buy_sell seat {seat_id!r} must declare {sorted(_BUY_SELL_SEAT_KEYS)}")
                _validate_resources(seat["starting_resources"], f"seats.{seat_id}.starting_resources")
                _validate_resources(seat["valuation"], f"seats.{seat_id}.valuation")
                if seat.get("goal_kind") not in {"seller", "buyer"}:
                    raise ValueError(f"seats.{seat_id}.goal_kind must be seller or buyer")
        else:
            for seat_id, seat in seats.items():
                if not isinstance(seat, dict) or set(seat) != _ULTIMATUM_SEAT_KEYS:
                    raise ValueError(f"ultimatum seat {seat_id!r} must declare {sorted(_ULTIMATUM_SEAT_KEYS)}")
                _validate_resources(seat["starting_resources"], f"seats.{seat_id}.starting_resources")
            # Upstream's own after_game_ends() (games/ultimatum/game.py) is
            # asymmetric across seats: RED's reported outcome is its
            # absolute final holdings, but BLUE's is a *delta* from BLUE's
            # own starting holdings (see docs/negarena_review_claude.md
            # WARNING-2, ledger_entries/negarena.md). Both leaves in
            # measurement.py treat "own_value" as one comparable number per
            # seat, which only holds if delta == absolute for BLUE, i.e. a
            # zero starting money_token balance. Reject anything else here
            # rather than let a future scenario silently produce two
            # incomparable numbers under the same head_to_head estimand.
            money_token = scenario["money_token"]
            blue_balance = seats[BLUE]["starting_resources"].get(money_token, 0)
            if blue_balance != 0:
                raise ValueError(
                    f"ultimatum seats.{BLUE}.starting_resources.{money_token} must be 0: "
                    "upstream's after_game_ends() reports blue's outcome as a delta from "
                    "its own starting holdings, not an absolute value like red's, so a "
                    "nonzero starting balance would make the two seats' outcomes incomparable"
                )

        self._verify_upstream_checkout()
        return data

    def _verify_upstream_checkout(self) -> None:
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

    # -- phase graph ----------------------------------------------------

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        # Named ``run`` (not ``cell``) to match the shared kernel's own two
        # call conventions for this hook: ``scheduler.run_episode`` calls it
        # positionally (``plugin.initial_state(family_case, cell)``, so the
        # parameter name here is cosmetic), but
        # ``family_evaluation.replay_family_state`` -- the shared replay path
        # every ``finalize_family_execution``/``replay_family_receipt``/
        # ``audit_family_receipt`` call reaches -- calls it by keyword as
        # ``plugin.initial_state(family_case, run=None)`` (mirroring
        # ``HousingV1Plugin.initial_state``'s identical ``run`` parameter).
        # Before this rename, any negarena ``CellExecution`` reaching that
        # shared replay path raised ``TypeError: initial_state() got an
        # unexpected keyword argument 'run'`` before evidence could ever be
        # sealed or scored (docs/negarena_codex_triage.md Finding 1's
        # regression test exercises this call path directly).
        del run
        return {
            "iteration": 0,
            "termination": None,
            "last_trade": {"kind": "none"},
            "last_answer": None,
            "history": [],
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        max_actions = int(family_case["scenario"]["iterations"])
        return (
            PhaseSpec(
                phase_id=RED_PHASE,
                actor_selector=RED,
                mode="single",
                observation_schema_by_role={RED: "negarena_seat_observation_v1"},
                action_schema_by_role={RED: "negarena_seat_action_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="family_defined",
                next_phases=(BLUE_PHASE,),
            ),
            PhaseSpec(
                phase_id=BLUE_PHASE,
                actor_selector=BLUE,
                mode="single",
                observation_schema_by_role={BLUE: "negarena_seat_observation_v1"},
                action_schema_by_role={BLUE: "negarena_seat_action_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="family_defined",
                next_phases=(RED_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del family_case, state
        if phase.phase_id == RED_PHASE:
            return (RED,)
        if phase.phase_id == BLUE_PHASE:
            return (BLUE,)
        raise ValueError(f"unknown phase: {phase.phase_id}")

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        expected = RED if phase.phase_id == RED_PHASE else BLUE
        if seat_id != expected:
            raise ValueError(f"seat {seat_id!r} is not active in phase {phase.phase_id!r}")
        scenario = family_case["scenario"]
        own = scenario["seats"][seat_id]
        history = state["history"]
        last_from_other = next(
            (entry for entry in reversed(history) if entry.get("seat") == _other_seat(seat_id) and entry.get("valid", True)),
            None,
        )
        return {
            "seat": seat_id,
            "game_kind": scenario["game_kind"],
            "iteration": state["iteration"],
            "max_iterations": scenario["iterations"],
            "money_token": scenario["money_token"],
            "resource_token": scenario.get("resource_token"),
            "own_resources": own["starting_resources"],
            "own_valuation": own.get("valuation"),
            "own_goal_kind": own.get("goal_kind"),
            "last_other_message": (
                last_from_other["public"]["message"] if last_from_other else None
            ),
            "last_other_answer": (
                last_from_other["public"]["player answer"] if last_from_other else None
            ),
            "last_trade": state["last_trade"],
        }

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del state
        expected = RED if phase.phase_id == RED_PHASE else BLUE
        if seat_id != expected:
            return ParseResult.failure("seat_phase_mismatch")
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        text = raw.get("response")
        if not isinstance(text, str) or not text.strip():
            return ParseResult.failure("response_missing_text")

        bridge = self._require_bridge()
        game_kind = family_case["scenario"]["game_kind"]
        result = bridge.parse_response(game_kind=game_kind, response=text)
        if not result["parsed"]:
            # Upstream's own write_game_state re-raises on an unparseable
            # response (governing facts); caught here at the seat boundary
            # instead of letting the episode process die (spec section 3).
            return ParseResult.failure("malformed_action")
        public = result["public"]
        if "message" not in public or "player answer" not in public or "newly proposed trade" not in public:
            return ParseResult.failure("malformed_action")
        return ParseResult.success({"seat": seat_id, "public": public, "secret": result["secret"]})

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del state
        expected = RED if phase.phase_id == RED_PHASE else BLUE
        if seat_id != expected:
            return LegalityResult.illegal("seat_phase_mismatch")
        trade = action["public"]["newly proposed trade"]
        if trade.get("kind") != "proposal":
            return LegalityResult.legal_action()

        # Adapter-owned admission gate (spec section 3): upstream itself
        # never checks a trade proposal against either seat's actual
        # holdings before it could be executed. Delegated to upstream's own
        # Trade.can_offer/can_accept, never reimplemented.
        bridge = self._require_bridge()
        seats = family_case["scenario"]["seats"]
        offer_legal = bridge.check_trade(
            direction="offer", give=trade["give"], resources=seats[RED]["starting_resources"]
        )
        accept_legal = bridge.check_trade(
            direction="accept", give=trade["give"], resources=seats[BLUE]["starting_resources"]
        )
        if not offer_legal or not accept_legal:
            return LegalityResult.illegal("invalid_measurement")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, ActionEnvelope],
    ) -> TransitionResult:
        new_state = _plain(state)
        seat_id = RED if phase.phase_id == RED_PHASE else BLUE
        envelope = actions[seat_id]

        if not envelope.valid:
            reason = "malformed_action" if not envelope.parse.ok else "invalid_measurement"
            new_state["termination"] = reason
            new_state["history"].append({"seat": seat_id, "valid": False, "reason": reason})
            return TransitionResult(
                state=new_state,
                next_phase_id=None,
                consequences={"turns": 1, "valid": False},
            )

        # envelope.action was frozen by ParseResult (nested MappingProxyType);
        # plain-ify before it re-enters our own JSON-shaped state.
        action = _plain(envelope.action)
        new_state["history"].append(
            {"seat": seat_id, "valid": True, "public": action["public"], "secret": action["secret"]}
        )
        new_state["iteration"] += 1
        new_state["last_trade"] = action["public"]["newly proposed trade"]
        answer = action["public"]["player answer"]
        new_state["last_answer"] = answer

        game_kind = family_case["scenario"]["game_kind"]
        max_iterations = int(family_case["scenario"]["iterations"])
        if answer == ACCEPT_ANSWER:
            # buy_sell.AlternatingGameEndsOnTag.game_over and
            # ultimatum.MultiTurnUltimatumGame.game_over both end on ACCEPT.
            new_state["termination"] = "accepted"
        elif game_kind == "ultimatum" and answer == REJECT_ANSWER:
            # Only ultimatum's game_over checks REJECT; buy_sell's does not
            # (a REJECT-style answer there simply is not the end tag and the
            # game continues -- upstream's own "TODO: this is pretty buggy").
            new_state["termination"] = "rejected"
        elif new_state["iteration"] >= max_iterations:
            new_state["termination"] = "iteration_cap"

        next_phase_id = None
        if new_state["termination"] is None:
            next_phase_id = BLUE_PHASE if seat_id == RED else RED_PHASE
        return TransitionResult(
            state=new_state,
            next_phase_id=next_phase_id,
            consequences={"turns": 1, "valid": True},
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        # NOTE for the scorer (spec section 2, see measurement.py's
        # ``_accepted_trade_give``): when `reason == "accepted"`,
        # `state["last_trade"]` is the ACCEPTING turn's own trade tag, which
        # upstream's own accept grammar always sets to "NONE" (see the
        # reference transcript). The trade that actually gets executed is
        # the one proposed on the turn *before* the accept (upstream's
        # `after_game_ends()`: `game_state[-2]`, i.e.
        # `state["history"][-2]["public"]["newly proposed trade"]` here) --
        # never this field. This function itself never computes settlement;
        # this field is reported as-is (a structural fact, not a payoff).
        reason = state["termination"]
        if reason is None:
            return None
        return {
            "reason": reason,
            "iteration_count": state["iteration"],
            "last_answer": state["last_answer"],
            "last_trade": state["last_trade"],
            "history_length": len(state["history"]),
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "iteration_count": terminal["iteration_count"],
            "last_answer": terminal["last_answer"],
            "last_trade": terminal["last_trade"],
        }

    def build_scorer(self, family_case: Mapping[str, Any]) -> Any:
        """Build the case's ``NegarenaScorer`` (spec section 2, milestone 2).

        Settlement (``after_game_ends()``, delegated to the bridge) and the
        two declared verifier leaves (``negarena_seat_outcome``,
        ``negarena_agreement_reached``) live in ``measurement.py``; this
        method forwards ``family_case`` and this plugin's own ``bridge`` to
        it, mirroring ``tau3_retail``'s identical
        ``build_scorer`` -> ``measurement.build_scorer`` hand-off
        (``Tau3RetailScorer.bridge``). The returned ``NegarenaScorer`` must
        carry the bridge itself: kernel_scoring_contract_spec.md section 1's
        production call site (``task.evaluation.finalize_family_execution``)
        invokes it as ``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=...)`` -- no bridge parameter reaches ``__call__`` at
        that call site, so the scorer object itself is the only place left
        to carry one.
        """
        return measurement.build_scorer(family_case, bridge=self.bridge)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any] | None = None) -> None:
        del family_case
        return None

    def _require_bridge(self) -> NegarenaBridge:
        if self.bridge is None:
            raise RuntimeError("negarena execution requires a provisioned NegarenaBridge")
        return self.bridge


__all__ = [
    "ACCEPT_ANSWER",
    "BLUE_PHASE",
    "PLUGIN_ID",
    "REJECT_ANSWER",
    "RED_PHASE",
    "SCORER_ID",
    "NegarenaPlugin",
    "family_manifest",
    "register_plugin",
]
