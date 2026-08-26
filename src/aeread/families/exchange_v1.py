"""Compatibility plugin for the ten-phase exchange engine.

The exchange engine predates the kernel and drives every seat through one
policy object, calling it several times inside a round. The kernel works the
other way round: it collects each seat's action and then applies one batch. The
two models do not meet in the middle without restructuring the engine, and
restructuring the engine is how a compatibility wrapper stops being one.

So this plugin keeps the engine intact and wraps it. One phase, no decision
slots, and `step` runs the transcript the engine has always run. What the
kernel gains is everything around it: a hashed case identity, an append-only
event log, a typed outcome, a score envelope, and a receipt. What it does not
yet gain is slot-mediated decisions for exchange seats, which is why this path
is exercised provider-free — the scripted policy decides, exactly as it does on
the legacy path.

The point of the wrapper is the parity test beside it. Old path and new path
run the same case at the same seed and must agree field by field on the
allocation, the welfare numbers, the applied-mechanism count, and the score.
Until they do, nothing built on the kernel can be trusted to mean what the
legacy numbers meant.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .. import exchange_economy as ex
from ..exchange_v1_runner import ScriptedBilateralIRPolicy
from ..sdk.v1 import (
    ActionBundle,
    CanonicalResponse,
    DecisionSlot,
    FamilyOutcome,
    LegalityResult,
    ObservationEnvelope,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    PluginManifest,
    TerminalResult,
    TransitionResult,
    content_sha256,
)


class ExchangeCompatibilityError(RuntimeError):
    """The wrapper was asked for something the legacy path cannot mean."""


EPISODE_PHASE = "exchange_transcript"


@dataclasses.dataclass(frozen=True)
class ExchangeV1Case:
    """A validated exchange case: the legacy config plus its digest."""

    case_id: str
    config: Any
    config_sha256: str
    seed: int


class ExchangeV1EnvironmentPlugin:
    """Runs the legacy transcript under the kernel's identity and evidence."""

    manifest = PluginManifest(
        plugin_id="aeread.exchange_v1",
        plugin_version="0.1.0",
        sdk_api="aeread.sdk/v1",
    )

    def validate_case(self, payload: Mapping[str, object]) -> ExchangeV1Case:
        case_id = payload.get("case_id")
        config_path = payload.get("config_path")
        if not isinstance(case_id, str) or not isinstance(config_path, str):
            raise ExchangeCompatibilityError(
                "an exchange case needs a case_id and a config_path"
            )
        path = Path(config_path)
        if not path.is_file():
            raise ExchangeCompatibilityError(f"config not found: {path}")
        seed = payload.get("seed")
        config = ex.load_experiment_config(path)
        if isinstance(seed, int) and not isinstance(seed, bool):
            config = dataclasses.replace(config, seed=seed)
        resolved_seed = int(config.seed)
        return ExchangeV1Case(
            case_id=case_id,
            config=config,
            # The digest is over the resolved config, not the file: an override
            # that changes the seed changes the case.
            config_sha256=content_sha256(
                json.loads(json.dumps(dataclasses.asdict(config), default=str))
            ),
            seed=resolved_seed,
        )

    def initial_state(
        self, case: ExchangeV1Case, cell: Any
    ) -> dict[str, object]:
        return {
            "config_sha256": case.config_sha256,
            "seed": case.seed,
            "ran": False,
            "result": None,
        }

    def phase_graph(self, case: ExchangeV1Case) -> PhaseGraph:
        return PhaseGraph(
            initial_phase_id=EPISODE_PHASE,
            phases=(
                PhaseSpec(
                    phase_id=EPISODE_PHASE,
                    actor_selector="none",
                    mode="single",
                    observation_schema_by_role={},
                    action_schema_by_role={},
                    max_logical_actions=1,
                    invalid_action_policy="pass",
                    next_phases=(),
                ),
            ),
        )

    def decision_slots(
        self,
        case: ExchangeV1Case,
        state: Mapping[str, object],
        phase: PhaseSpec,
    ) -> Sequence[DecisionSlot]:
        # The engine asks its own policy for every utterance inside the round,
        # so there is no kernel-visible decision to offer. Making exchange
        # seats slot-mediated means restructuring the engine, not the wrapper.
        return ()

    def observe(
        self,
        case: ExchangeV1Case,
        state: Mapping[str, object],
        phase: PhaseSpec,
        slot: DecisionSlot,
    ) -> ObservationEnvelope:
        raise ExchangeCompatibilityError(
            "the exchange compatibility path offers no decision slots"
        )

    def parse_action(
        self,
        case: ExchangeV1Case,
        state: Mapping[str, object],
        phase: PhaseSpec,
        slot: DecisionSlot,
        response: CanonicalResponse,
    ) -> ParseResult:
        raise ExchangeCompatibilityError(
            "the exchange compatibility path offers no decision slots"
        )

    def legal(
        self,
        case: ExchangeV1Case,
        state: Mapping[str, object],
        phase: PhaseSpec,
        bundle: ActionBundle,
    ) -> LegalityResult:
        raise ExchangeCompatibilityError(
            "the exchange compatibility path offers no decision slots"
        )

    def step(
        self,
        case: ExchangeV1Case,
        state: Mapping[str, object],
        phase: PhaseSpec,
        bundles: Mapping[str, ActionBundle],
    ) -> TransitionResult:
        if bundles:
            raise ExchangeCompatibilityError(
                "the exchange compatibility path accepts no seat actions"
            )
        if state.get("ran"):
            raise ExchangeCompatibilityError("the transcript already ran")

        world = ex.make_world_from_config(case.config)
        result = ex.run_exchange_transcript(
            world,
            rounds=case.config.rounds,
            controllers=case.config.controllers,
            policy=ScriptedBilateralIRPolicy(),
            protocol=case.config.protocol,
        )
        return TransitionResult(
            state={
                "config_sha256": case.config_sha256,
                "seed": case.seed,
                "ran": True,
                "result": _result_record(result),
            },
            next_phase_id=None,
            evidence={"rounds": case.config.rounds},
        )

    def terminal(
        self, case: ExchangeV1Case, state: Mapping[str, object]
    ) -> TerminalResult | None:
        if not state.get("ran"):
            return None
        return TerminalResult(
            status="terminal",
            reason="transcript_complete",
            final_state=dict(state),
        )

    def outcome(
        self, case: ExchangeV1Case, terminal: TerminalResult
    ) -> FamilyOutcome:
        record = terminal.final_state.get("result")
        if not isinstance(record, Mapping):
            raise ExchangeCompatibilityError("terminal state carries no result")
        return FamilyOutcome(
            terminal_reason=terminal.reason,
            payload=dict(record),
            # Exchange scores the world, not a seat: per-seat utility here would
            # invent an attribution the legacy path never made.
            utility_by_seat={},
        )


def _result_record(result: ex.RunResult) -> dict[str, object]:
    """The legacy numbers a scorer reads, in a JSON-safe shape.

    These are exactly the fields `exchange_v1_scoring.score_run` consumes plus
    the allocation and the diagnostics the summary reports, so parity can be
    checked field by field rather than through a single ratio.
    """

    return {
        "initial_allocation": [list(row) for row in result.initial_allocation],
        "final_allocation": [list(row) for row in result.final_allocation],
        "initial_welfare": result.initial_welfare,
        "final_welfare": result.final_welfare,
        "optimum_welfare": result.optimum_welfare,
        "final_net_welfare": result.final_net_welfare,
        "coordination_cost_total": result.coordination_cost_total,
        "applied_mechanisms": result.applied_mechanisms,
        "rounds": len(result.history),
        "initial_gini": result.initial_gini,
        "final_gini": result.final_gini,
    }


__all__ = [
    "EPISODE_PHASE",
    "ExchangeCompatibilityError",
    "ExchangeV1Case",
    "ExchangeV1EnvironmentPlugin",
]
