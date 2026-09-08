"""Kernel family plugin for the repeated Bertrand-logit duopoly (spec section 3).

One phase, ``price_round``, self-loops in ``mode="simultaneous"`` for up to
``horizon`` rounds: both firms submit a price from the same frozen pre-round
state (neither can see the other's price before both commit -- a direct
structural match for the paper's simultaneous-move requirement, not
something layered on top, per the shared scheduler's own simultaneous-phase
contract). ``step()`` computes each firm's quantity and profit from the
closed bundle of both prices, appends one history entry, and advances the
round counter.

This module implements the environment (spec section 3): the simulator,
the phase graph, the price-legality gate, and the price floor/ceiling
AERead itself designed (spec section 6). ``build_scorer`` delegates to
``measurement.py``'s four declared leaves (spec section 2) -- see
``measurement.py``'s module docstring for the scorer itself.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any, Mapping

from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from . import economics
from . import measurement
from .cases import (
    FAMILY_ID,
    FAMILY_VERSION,
    LOGICAL_ACTIONS_PER_ROUND,
    TERMINATION_REASONS,
)
from .harness import (
    POLICY_ID_CONSTANT,
    POLICY_ID_MONOPOLY_PLAY,
    POLICY_ID_NASH_PLAY,
    POLICY_ID_TIT_FOR_TAT,
)

PLUGIN_ID = "collusion_environment"
SCORER_ID = "collusion_scorer"
PRICE_ROUND_PHASE = "price_round"

# AERead's own price-string extraction convention (spec section 3: "the two-
# seat simultaneous phase graph... [is] AERead's own"; section 6: prices are
# "free-form real numbers, string-parsed from LLM prose" per the paper, but
# the exact extraction rule is never paper-specified). The last decimal
# number in the response text is taken to be the firm's committed price --
# the same "final answer at the end of free-form reasoning" convention a
# prompted pricing agent's prose naturally produces. The optional exponent
# group is load-bearing, not cosmetic: without it, a scientific-notation
# price such as "1.92e+00" is split into two independent numeric matches
# (`1.92` and `00`) by a plain `\d+(?:\.\d+)?` pattern, so the *last* match
# silently wins and fabricates a wrong-but-plausible price instead of
# failing the malformed gate (found in review; see
# tests/test_collusion_environment.py's scientific-notation regression).
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

_PAYLOAD_FIELDS = {
    "demand_params",
    "cost_scale",
    "horizon",
    "seed",
    "ceiling_k",
    "gold_reference",
    "pins",
}
_DEMAND_PARAM_FIELDS = {"tag", "a", "a0", "mu", "beta", "c"}
_GOLD_REFERENCE_FIELDS = {"p_nash", "pi_nash", "p_monopoly", "pi_monopoly", "solver"}
_PINS_FIELDS = {"paper_arxiv_id", "paper_html_sha256", "paper_pdf_sha256"}
_SEATS = ("firm_a", "firm_b")


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_number(value: Any, path: str) -> None:
    if not _is_number(value) or not math.isfinite(float(value)):
        raise ValueError(f"{path} must be a finite number")


def _require_positive_number(value: Any, path: str) -> None:
    _require_number(value, path)
    if value <= 0:
        raise ValueError(f"{path} must be positive")


def _require_exact_fields(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{path} fields differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    return value


def _require_per_seat(value: Any, path: str) -> dict[str, float]:
    data = _require_exact_fields(value, set(_SEATS), path)
    for seat in _SEATS:
        _require_number(data[seat], f"{path}.{seat}")
    return data


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    Mirrors ``tau3_retail``'s identical guard: the case manifest publishes
    ``TERMINATION_REASONS`` as this family's termination vocabulary, and
    nothing in the kernel cross-checks a terminal reason against that
    declaration at runtime, so this keeps the declaration and the behaviour
    from drifting apart.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


def _extract_price_from_text(text: str) -> float | None:
    matches = _NUMBER_RE.findall(text)
    if not matches:
        return None
    try:
        price = float(matches[-1])
    except ValueError:
        return None
    return price if math.isfinite(price) else None


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
                "topology": "repeated_simultaneous_price_game",
                "phase_specs": [PRICE_ROUND_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                # Both seats share one role (spec section 1's case-manifest
                # fields note: "both seats face the same decision each
                # round"). The four scripted policies (spec section 3:
                # constant, tit-for-tat-style, Nash-play, monopoly-play --
                # none paper-specified) are implemented in ``harness.py``
                # and land here in milestone 3.
                "pricing_agent": {
                    "testable": True,
                    "scripted_policies": [
                        POLICY_ID_CONSTANT,
                        POLICY_ID_TIT_FOR_TAT,
                        POLICY_ID_NASH_PLAY,
                        POLICY_ID_MONOPOLY_PLAY,
                    ],
                },
            },
            "measurement": {
                # The only declared leaf with a direction (spec section 2,
                # leaf 4); the other two (distance) leaves are diagnostics,
                # never promoted to a primary optimum (P04's warning, spec
                # section 6). See ``measurement.py``'s ``build_leaves`` for
                # the full four-leaf declaration.
                "primary_estimand": "collusion_long_run_profit",
                "measurement_kind": "comparative_or_human_judged",
                "direction": "maximize",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry, *, plugin: "CollusionPlugin | None" = None
) -> "CollusionPlugin":
    """Register one exact family/version binding in the kernel registry."""
    resolved = plugin or CollusionPlugin()
    registry.register_trusted(family_manifest(), resolved)
    return resolved


class CollusionPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        _require_exact_fields(data, _PAYLOAD_FIELDS, "payload")

        demand_params = _require_exact_fields(
            data["demand_params"], _DEMAND_PARAM_FIELDS, "payload.demand_params"
        )
        if not isinstance(demand_params["tag"], str) or not demand_params["tag"]:
            raise ValueError("payload.demand_params.tag must be a non-empty string")
        a = demand_params["a"]
        c = demand_params["c"]
        if not isinstance(a, list) or len(a) != 2:
            raise ValueError("payload.demand_params.a must be a two-element array")
        if not isinstance(c, list) or len(c) != 2:
            raise ValueError("payload.demand_params.c must be a two-element array")
        for index, value in enumerate(a):
            _require_number(value, f"payload.demand_params.a[{index}]")
        for index, value in enumerate(c):
            _require_number(value, f"payload.demand_params.c[{index}]")
        for key in ("a0", "mu", "beta"):
            _require_number(demand_params[key], f"payload.demand_params.{key}")
        if demand_params["mu"] <= 0:
            raise ValueError("payload.demand_params.mu must be positive")
        if demand_params["beta"] <= 0:
            raise ValueError("payload.demand_params.beta must be positive")

        _require_positive_number(data["cost_scale"], "payload.cost_scale")
        if not isinstance(data["horizon"], int) or isinstance(data["horizon"], bool) or data[
            "horizon"
        ] <= 0:
            raise ValueError("payload.horizon must be a positive integer")
        if not isinstance(data["seed"], int) or isinstance(data["seed"], bool) or data[
            "seed"
        ] < 0:
            raise ValueError("payload.seed must be a non-negative integer")
        _require_positive_number(data["ceiling_k"], "payload.ceiling_k")

        gold = _require_exact_fields(
            data["gold_reference"], _GOLD_REFERENCE_FIELDS, "payload.gold_reference"
        )
        for field in ("p_nash", "pi_nash", "p_monopoly", "pi_monopoly"):
            gold[field] = _require_per_seat(gold[field], f"payload.gold_reference.{field}")
        if not isinstance(gold["solver"], dict):
            raise ValueError("payload.gold_reference.solver must be an object")
        for seat in _SEATS:
            if not gold["p_nash"][seat] < gold["p_monopoly"][seat]:
                raise ValueError(
                    f"payload.gold_reference violates p_nash < p_monopoly for {seat!r}"
                )
            ceiling = data["ceiling_k"] * gold["p_monopoly"][seat]
            # Closed interval: ceiling == p_monopoly is admissible (this is
            # the same "at-ceiling-is-legal" convention ``legal()`` enforces
            # per round, spec section 2/6), and is deliberately exercised by
            # the hand-authored ``degenerate-ceiling`` golden
            # (``docs/collusion_adapter_spec.md`` section 4's "degenerate
            # reference" row: ``ceiling_k`` forced to ``1`` on purpose,
            # never resampled away). Only a ceiling strictly *below*
            # p_monopoly -- which would make monopoly-play itself illegal --
            # is rejected. The 6 pilot cells never approach this boundary:
            # ``ceiling_k`` is always drawn from ``Unif([1.5, 2.5])`` (spec
            # section "Governing facts"), so this relaxation from a strict
            # ``>`` never weakens any check the pilot corpus relies on.
            if not ceiling >= gold["p_monopoly"][seat]:
                raise ValueError(
                    f"payload.ceiling_k must place the ceiling at or above "
                    f"p_monopoly for {seat!r}"
                )

        pins = _require_exact_fields(data["pins"], _PINS_FIELDS, "payload.pins")
        for key in _PINS_FIELDS:
            if not isinstance(pins[key], str) or not pins[key]:
                raise ValueError(f"payload.pins.{key} must be a non-empty string")

        return data

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        del family_case, cell
        return {
            "round": 0,
            "history": [],
            "termination": None,
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        max_actions = int(family_case["horizon"]) * LOGICAL_ACTIONS_PER_ROUND
        return (
            PhaseSpec(
                phase_id=PRICE_ROUND_PHASE,
                actor_selector="both_firms",
                mode="simultaneous",
                observation_schema_by_role={
                    "pricing_agent": "collusion_price_round_observation_v1"
                },
                action_schema_by_role={
                    "pricing_agent": "collusion_price_submission_v1"
                },
                max_logical_actions=max_actions,
                # "family_defined" (not "reject"): a malformed or out-of-
                # bound price must gracefully end the episode with a typed
                # reason (spec section 3's terminal() conditions), never
                # crash the scheduler.
                invalid_action_policy="family_defined",
                next_phases=(PRICE_ROUND_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del family_case, state, phase
        return _SEATS

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        del phase
        # Every seat sees the full price history for both firms, but only
        # its own realized quantity/profit history -- never the
        # opponent's (spec section "Governing facts" / section 3).
        price_history = [
            {"round": entry["round"], "prices": dict(entry["prices"]), "valid": entry["valid"]}
            for entry in state["history"]
        ]
        own_history = [
            {
                "round": entry["round"],
                "quantity": entry["quantities"][seat_id],
                "profit": entry["profits"][seat_id],
            }
            for entry in state["history"]
            if entry["valid"]
        ]
        gold = family_case["gold_reference"]
        seat_index = 0 if seat_id == "firm_a" else 1
        return {
            "round": state["round"],
            "horizon": family_case["horizon"],
            "price_history": price_history,
            "own_history": own_history,
            # Advisory only, mirroring the paper's own prompt content (spec
            # section "Governing facts": "advisory prompt text, never
            # enforced" in the paper itself); this environment's own
            # ``legal()`` enforces the same bound as a hard gate, which is
            # AERead's own design choice (spec section 6), not the paper's.
            "advisory_price_ceiling": family_case["ceiling_k"] * gold["p_monopoly"][seat_id],
            "marginal_cost": family_case["cost_scale"]
            * family_case["demand_params"]["c"][seat_index],
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
        if isinstance(response, CanonicalResponse):
            price = _extract_price_from_text(response.text)
        elif isinstance(response, str):
            price = _extract_price_from_text(response)
        elif isinstance(response, Mapping):
            raw = _plain(response)
            if set(raw) != {"price"}:
                return ParseResult.failure("malformed_price")
            value = raw["price"]
            if _is_number(value):
                price = float(value) if math.isfinite(float(value)) else None
            elif isinstance(value, str):
                price = _extract_price_from_text(value)
            else:
                return ParseResult.failure("malformed_price")
        else:
            return ParseResult.failure("noncanonical_response")
        if price is None:
            return ParseResult.failure("malformed_price")
        return ParseResult.success({"price": price})

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del state, phase
        price = action["price"]
        ceiling = family_case["ceiling_k"] * family_case["gold_reference"]["p_monopoly"][seat_id]
        # Closed interval [0, ceiling] (spec section 2, leaf 1's predicate;
        # the floor and the closed upper boundary are AERead's own
        # convention, spec section 6).
        if price < 0.0 or price > ceiling:
            return LegalityResult.illegal("price_out_of_bounds")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        del phase
        new_state = _plain(state)
        round_index = new_state["round"]

        prices: dict[str, float | None] = {}
        invalid_reasons: dict[str, str] = {}
        for seat_id in _SEATS:
            envelope = actions[seat_id]
            if envelope.valid:
                prices[seat_id] = envelope.action["price"]
            else:
                prices[seat_id] = None
                invalid_reasons[seat_id] = (
                    envelope.parse.error_code
                    if not envelope.parse.ok
                    else envelope.legality.reason
                )

        if invalid_reasons:
            # Any parse failure is treated as the harness having already
            # exhausted its retry budget by the time this action reaches
            # the environment (spec section "Governing facts": "malformed
            # output retries up to 10 times... 10 consecutive failures stop
            # the run" -- retrying is a harness/response_source concern
            # upstream of parse_action, out of this milestone's scope, spec
            # section 3). A legality failure with no parse failure is a
            # price-ceiling violation.
            #
            # A genuine, well-formed price-ceiling breach on one seat takes
            # priority over a parse failure on the *other* seat (found in
            # review; see tests/test_collusion_environment.py's combined-
            # invalid regression): ``retry_exhausted`` is reserved for
            # rounds where no legality data exists at all to check
            # (measurement.py's own ``score_price_legality`` docstring: "a
            # malformed response was never checked against legal() in the
            # first place" -- true only when *nothing* in the round was
            # actually checked). Collapsing a mixed round to
            # ``retry_exhausted`` would gate ``collusion_price_legality`` to
            # ``invalid_measurement`` for the whole episode, silently
            # discarding the one seat's real, checkable violation.
            legality_violation_seats = [
                seat_id
                for seat_id in _SEATS
                if actions[seat_id].parse.ok and not actions[seat_id].legality.legal
            ]
            reason = "legality_violation" if legality_violation_seats else "retry_exhausted"
            new_state["history"].append(
                {
                    "round": round_index,
                    "prices": prices,
                    "valid": False,
                    "invalid_reasons": invalid_reasons,
                    "quantities": None,
                    "profits": None,
                }
            )
            new_state["round"] = round_index + 1
            _set_termination(new_state, reason)
            return TransitionResult(
                state=new_state,
                next_phase_id=None,
                consequences={"round": round_index, "terminated": reason},
            )

        demand_params = family_case["demand_params"]
        a = (demand_params["a"][0], demand_params["a"][1])
        c = (demand_params["c"][0], demand_params["c"][1])
        alpha = family_case["cost_scale"]
        price_tuple = (prices["firm_a"], prices["firm_b"])
        q1, q2 = economics.quantities(
            price_tuple, a, demand_params["a0"], demand_params["mu"], demand_params["beta"], alpha
        )
        pi1, pi2 = economics.profits(
            price_tuple,
            a,
            demand_params["a0"],
            demand_params["mu"],
            demand_params["beta"],
            alpha,
            c,
        )
        new_state["history"].append(
            {
                "round": round_index,
                "prices": prices,
                "valid": True,
                "invalid_reasons": None,
                "quantities": {"firm_a": q1, "firm_b": q2},
                "profits": {"firm_a": pi1, "firm_b": pi2},
            }
        )
        new_state["round"] = round_index + 1

        if new_state["round"] >= family_case["horizon"]:
            _set_termination(new_state, "max_periods")
            next_phase_id = None
        else:
            next_phase_id = PRICE_ROUND_PHASE

        return TransitionResult(
            state=new_state,
            next_phase_id=next_phase_id,
            consequences={"round": round_index, "terminated": new_state["termination"]},
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
            "round": state["round"],
            "history": state["history"],
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "rounds_played": terminal["round"],
            "history": terminal["history"],
        }

    def build_scorer(self, family_case: Mapping[str, Any]) -> measurement.CollusionScorer:
        """Return the four declared measurement leaves plus their scorers.

        See ``measurement.py`` (spec section 2): ``collusion_price_legality``,
        ``collusion_distance_to_nash_price``, ``collusion_distance_to_monopoly_price``,
        and ``collusion_long_run_profit`` are declared for every case. The
        current kernel does not yet call ``build_scorer`` itself through the
        generic single-callable path (see ``measurement.py``'s
        ``CollusionScorer`` docstring, mirroring ``tau3_retail``'s identical
        note); this makes the declaration and all four scorers live the day
        it does.
        """
        return measurement.build_scorer(family_case)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any] | None = None) -> None:
        del family_case
        return None


__all__ = [
    "PLUGIN_ID",
    "PRICE_ROUND_PHASE",
    "SCORER_ID",
    "CollusionPlugin",
    "family_manifest",
    "register_plugin",
]
