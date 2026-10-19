"""The v15 receipts score the deciding tenant: seat 0's net under measure v2, against its own references (HL-D-09).

v14's scorer (``runner._score_housing_lemons_outcome``) sums the net payoff of all six tenants, outside-demand seats
included, and brackets it with six-tenant policies in a market without outside demand. Nothing in a v14 receipt
scores seat 0, and the bundle scored it outside the kernel. The v15 plan (Section 4, amendment 1) asks for a scorer
under a new id whose primary leaf is seat 0's net under measure v2 (``price_reply_posterior``) and whose references
are the best-informed tenant and the full-information ceiling for the same world and arm. This module supplies it
without editing ``runner.py``, which sealed plans hash:

- ``Seat0PricePlugin`` is ``runner.HousingV1Plugin`` with three additions: it records the round of each of seat 0's
  inspections in its state (the market keeps which listings were inspected, not when), it adds seat 0's decisions and
  replies to the terminal outcome, and it scores with ``score_seat0``. Every transition and every other rule is the
  parent's code.
- ``build_v15_setup(contract, arm, *, live, holdout_rate)`` takes the setup ``price_campaign.build_setup`` resolves for
  a contract and resolves it again with this scorer: the family's scoring block names :data:`SCORER_ID` and its
  references, the scorer and reference pins carry this module's digest, and the registry holds ``Seat0PricePlugin``
  under Housing's trusted key, which ``register_trusted`` checks by key alone. Everything else in the plan is
  ``build_setup``'s.
- The references are computed offline in the scorer from the case's own world and arm, at the outside-demand rate
  the builder was given: seat 0 passing everything ($0), ``inspect_then_sign``, ``inspect_lowball``, the best-informed
  tenant (knowledge ``pricing``), each under measure v2, and the ceiling (``price_reference.ceiling``).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.measurement import (
    EstimandSpec,
    ImplementationRef as MeasurementImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import MeasurementDeclaration, ScoringSpec
from aeread.shared_runner.run.resolver import ImplementationPin, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.task.evaluation import FamilyScoringInput

from aeread_families.housing import lemons, price_controls, price_outside_demand, price_reference
from aeread_families.housing import price_outside_demand_holdout as holdout
from aeread_families.housing import price_pack_v2
from aeread_families.housing import price_reply_posterior as posterior
from aeread_families.housing import runner

SCORER_ID = "housing_lemons_price_seat0_outcome_v1"
LEAF_ID = "housing_seat0_net_v2_leaf"
ESTIMAND_ID = "seat0_net_reply_conditioned"
FLOOR_REF = "housing_feasible_zero_v1"
INSPECT_THEN_SIGN_REF = "housing_seat0_inspect_then_sign_v1"
INSPECT_LOWBALL_REF = "housing_seat0_inspect_lowball_v1"
BEST_INFORMED_REF = "housing_seat0_best_informed_v1"
CEILING_REF = "housing_seat0_ceiling_v1"
REFERENCE_IDS = (FLOOR_REF, INSPECT_THEN_SIGN_REF, INSPECT_LOWBALL_REF, BEST_INFORMED_REF)
SEAT = price_reference.FOCAL_SEAT
ROUNDS_KEY = "seat0_inspection_rounds"
UNITS = "utility_points"


def implementation_digest() -> str:
    """This scorer's bytes and those of every module it computes with, after the sealed lemons sources."""
    sources = [runner._housing_lemons_source_digests(price=True)[2]]
    for module in (posterior, price_pack_v2, holdout, price_reference, price_controls):
        sources.append(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
    sources.append(hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return hashlib.sha256("".join(sources).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The leaf.


def seat0_leaf(case: Mapping[str, Any]) -> MeasurementLeafSpec:
    digest = implementation_digest()
    validity_domain = ValidityDomainSpec(
        domain_id="housing_seat0_terminal_domain",
        domain_version="1.0.0",
        schema_ref="housing_v1/lemons_seat0_outcome/1",
        predicate=MeasurementImplementationRef(SCORER_ID, "1.0.0", digest),
    )
    estimand = EstimandSpec(
        estimand_id=ESTIMAND_ID,
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units=UNITS,
        validity_domain=validity_domain,
    )
    source_sha256 = hashlib.sha256(canonical_json_bytes({
        "world_seed": case["world_seed"], "arm": case.get("lemon_landlord", "true_cost")})).hexdigest()
    return MeasurementLeafSpec(
        leaf_id=LEAF_ID,
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id=CEILING_REF,
                reference_version="1.0.0",
                reference_kind="objective_upper_bound",
                input_scope="terminal_state",
                units=UNITS,
                source_sha256=source_sha256,
                implementation=MeasurementImplementationRef(CEILING_REF, "1.0.0", digest),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id=ESTIMAND_ID,
                objective_version="1.0.0",
                direction="maximize",
                units=UNITS,
                feasible_set="at most one lease for seat 0, at a binding rent its landlord offered",
                information_set=(
                    "seat 0's own values if sound, the declared lemon count, its paid inspections, the landlords' "
                    "replies and the stated pricing rule; true quality and landlord cost private"
                ),
                horizon="one pinned housing episode",
                environment_condition="pinned lemons world, landlord arm and outside-demand rate",
                opponent_condition="price landlords and scripted outside demand declared in the RunPlan",
                validity_domain=validity_domain,
            ),
        ),
        scorer=MeasurementImplementationRef(SCORER_ID, "1.0.0", digest),
    )


# ---------------------------------------------------------------------------
# Seat 0's trajectory from the state, and its score.


def seat0_trajectory(state: Mapping[str, Any]) -> posterior.Trajectory:
    """The rounds of seat 0's inspections and every landlord reply to it, from the plugin's state."""
    history = state.get("history", ())
    offers = {(e["round_index"], e["listing_id"]): float(e["rent"]) for e in history
              if e["tenant_id"] == SEAT and e["event"] == "offer"}
    replies = [posterior.Reply(int(e["round_index"]), int(e["listing_id"]), offers[(e["round_index"], e["listing_id"])],
                               float(e["binding_rent"]))
               for e in history if e["tenant_id"] == SEAT and e["event"] == "hold"]
    rounds = {int(listing): int(r) for listing, r in state.get(ROUNDS_KEY, {}).items()}
    return posterior.Trajectory(inspections=rounds, replies=replies)


def references(seed: int, arm: str, rate: float) -> dict[str, float]:
    """Seat 0's references in one world and arm, each played offline at ``rate`` and scored under measure v2."""
    return {
        INSPECT_THEN_SIGN_REF: price_pack_v2.play(seed, arm, "inspect_then_sign", rate)["primary_v2"],
        INSPECT_LOWBALL_REF: price_pack_v2.play(seed, arm, "inspect_lowball", rate)["primary_v2"],
        BEST_INFORMED_REF: price_pack_v2.play(seed, arm, "best_informed", rate)["primary_v2"],
        CEILING_REF: price_reference.ceiling(seed, arm),
    }


def score_seat0(case: Mapping[str, Any], outcome: Mapping[str, Any], rate: float, *,
                evidence_refs: Sequence[str] = ()) -> ScoreEnvelope:
    leaf = seat0_leaf(case)
    reasons: list[str] = []
    seat0 = outcome.get("seat0") if isinstance(outcome, Mapping) else None
    if outcome.get("valid") is not True:
        reasons.append("family outcome is not marked valid")
    if not isinstance(seat0, Mapping):
        reasons.append("the outcome carries no seat-0 block")
    scored: dict[str, Any] = {}
    if not reasons:
        try:
            trajectory = posterior.Trajectory.from_row(seat0["trajectory"])
            scored = posterior.score_seat(case["world"], seat0["commit_decisions"], trajectory, float(seat0["inspection_spend"]), seat=SEAT)
        except (KeyError, TypeError, ValueError) as error:
            reasons.append(f"measure v2 cannot score seat 0: {error}")
    if not reasons and not math.isclose(scored["net_realized"], float(seat0["net_realized"]), abs_tol=0.005):
        reasons.append("measure v2's realized net differs from the market's seat-0 net")
    if reasons:
        return ScoreEnvelope(status="invalid_measurement", leaf=leaf, primary=None, metrics={}, reference_values={},
                             validity=ValidityReport("invalid", tuple(dict.fromkeys(reasons))), evidence_refs=tuple(evidence_refs))
    refs = references(int(case["world_seed"]), case.get("lemon_landlord", "true_cost"), rate)
    primary = float(scored["primary_v2"])
    ceiling = refs[CEILING_REF]
    metrics = {
        ESTIMAND_ID: MetricValue(primary, UNITS),
        "seat0_net_realized": MetricValue(float(scored["net_realized"]), UNITS),
        "seat0_net_v1": MetricValue(float(scored["primary_v1"]), UNITS),
        "best_informed_gap": MetricValue(refs[BEST_INFORMED_REF] - primary, UNITS),
        "inspect_then_sign_gap": MetricValue(primary - refs[INSPECT_THEN_SIGN_REF], UNITS),
        "inspect_lowball_gap": MetricValue(primary - refs[INSPECT_LOWBALL_REF], UNITS),
        "upper_bound_gap": MetricValue(ceiling - primary, UNITS),
        "blind_signings": MetricValue(float(len(scored["blind_signings"])), "count"),
        "informative_replies": MetricValue(float(scored["informative_replies"]), "count"),
        "invalid_actions": MetricValue(float(sum(seat0.get("invalid_actions", {}).values())), "count"),
    }
    if ceiling > 0.005:
        metrics["share_of_ceiling"] = MetricValue(primary / ceiling, "ratio")
    reference_values = {
        "optimum_lower_bound": MetricValue(0.0, UNITS, {"reference_kind": "objective_lower_bound", "policy": "pass"}),
        "comparison_baseline": MetricValue(refs[INSPECT_THEN_SIGN_REF], UNITS,
                                           {"reference_kind": "comparison_baseline", "policy": "inspect_then_sign"}),
        "scripted_reference": MetricValue(refs[INSPECT_LOWBALL_REF], UNITS,
                                          {"reference_kind": "scripted_reference", "policy": "inspect_lowball"}),
        "best_informed": MetricValue(refs[BEST_INFORMED_REF], UNITS,
                                     {"reference_kind": "scripted_reference", "policy": "best_informed_pricing"}),
        "optimum_upper_bound": MetricValue(ceiling, UNITS, {"reference_kind": "objective_upper_bound",
                                                            "semantics": "full_information_seat0_ceiling"}),
    }
    return ScoreEnvelope(status="ok", leaf=leaf, primary=metrics[ESTIMAND_ID], metrics=metrics, reference_values=reference_values,
                         validity=ValidityReport("valid"), evidence_refs=tuple(evidence_refs))


# ---------------------------------------------------------------------------
# The plugin.


class Seat0PricePlugin(runner.HousingV1Plugin):
    """``HousingV1Plugin`` whose receipts score seat 0 under measure v2. Transitions are the parent's."""

    def __init__(self, rate: float = price_outside_demand.RATE) -> None:
        if rate not in (price_outside_demand.RATE, holdout.RATE):
            raise ValueError("the outside-demand rate must be v14's or the holdout's")
        self.rate = rate

    def initial_state(self, case, run):
        return {**super().initial_state(case, run), ROUNDS_KEY: {}}

    def step(self, case, state, phase, actions):
        result = super().step(case, state, phase, actions)
        if phase.phase_id != "inspect":
            return result
        before = _inspected(state)
        rounds = {**state.get(ROUNDS_KEY, {})}
        for listing in sorted(_inspected(result.state) - before):
            rounds[str(listing)] = int(state["round_index"])
        return dataclasses.replace(result, state={**result.state, ROUNDS_KEY: rounds})

    def terminal(self, case, state):
        terminal = super().terminal(case, state)
        if terminal is None:
            return None
        spend = {int(row["tenant_id"]): float(row["spend"]) for row in state["inspection_spend"]}
        return {**terminal, "seat0": {
            "commit_decisions": [d for d in state["commit_decisions"] if int(d["tenant_id"]) == SEAT],
            "trajectory": seat0_trajectory(state).to_row(),
            "inspection_spend": spend.get(SEAT, 0.0),
            "net_realized": float(terminal["tenant_net_payoffs"][f"tenant_{SEAT}"]),
        }}

    def build_scorer(self, case):
        rate = self.rate

        def score(scoring_input: FamilyScoringInput, *, evidence_refs: Sequence[str] = ()) -> ScoreEnvelope:
            return score_seat0(case, scoring_input.outcome, rate, evidence_refs=evidence_refs)

        return score

    def build_reference_providers(self, case):
        return (*REFERENCE_IDS, CEILING_REF)


def _inspected(state: Mapping[str, Any]) -> set[int]:
    return {int(item["listing_id"]) for row in state.get("inspected", ()) if int(row["tenant_id"]) == SEAT for item in row["items"]}


# ---------------------------------------------------------------------------
# The builder: build_setup's plan, resolved again with this scorer.


def rescore(setup: Any, rate: float) -> Any:
    """``setup`` (a ``runner.HousingSmokeSetup``) with its plan resolved again under the seat-0 scorer."""
    plan = setup.plan
    digest = implementation_digest()
    families = [dataclasses.replace(
        family,
        measurement=MeasurementDeclaration.from_dict({
            "primary_estimand": ESTIMAND_ID, "measurement_kind": "optimizable_outcome", "direction": "maximize",
            "optimum_lower_bound": FLOOR_REF, "comparison_baseline": INSPECT_THEN_SIGN_REF,
            "optimum_upper_bound": CEILING_REF, "optimum_upper_bound_kind": "full_information_relaxation",
            "bound_status": "bracketed", "outcome_support": "case_specific"}),
        scoring=ScoringSpec.from_dict({"scorer_id": SCORER_ID, "oracle_id": CEILING_REF,
                                       "reference_provider_ids": list(REFERENCE_IDS)}),
    ) for family in plan.families]
    old_ids = {"housing_lemons_price_outcome_v1", "housing_exact_assignment_v1", "housing_feasible_zero_v1",
               "housing_price_sign_anything_v1", "housing_price_inspect_then_sign_v1"}
    pins = [p for p in plan.implementation_pins if p.component_id not in old_ids]
    pins += [dataclasses.replace(_template(plan, "scorer"), component_id=SCORER_ID, sha256=digest)]
    for ref in (*REFERENCE_IDS, CEILING_REF):
        pins.append(dataclasses.replace(_template(plan, "reference"), component_id=ref, sha256=digest))
    plugin = Seat0PricePlugin(rate)
    registry = PluginRegistry()
    for family in families:
        registry.register_trusted(family, plugin)
    new_plan = resolve_run_plan(
        families=tuple(families), cases=plan.cases, suite=plan.suite, sampling=plan.sampling,
        evaluation_blocks=plan.evaluation_blocks,
        analysis=dataclasses.replace(plan.analysis, estimands=(ESTIMAND_ID, *[e for e in plan.analysis.estimands if e != ESTIMAND_ID])),
        agent_profiles=plan.agent_profiles,
        run_spec=plan.run_spec, registry=registry, implementation_pins=tuple(pins),
        harness_registry=_harness_registry(setup), provider_capabilities=_capabilities(plan),
    )
    return dataclasses.replace(setup, plan=new_plan, registry=registry)


def build_v15_setup(contract: Mapping[str, Any], arm: str, *, live: bool, holdout_rate: bool = False) -> Any:
    """The v15 setup for one contract and arm: ``price_campaign.build_setup``'s, scored for seat 0 at the stream's rate."""
    from aeread_families.housing import price_campaign  # the campaign module imports this one's callers, not this one

    return rescore(price_campaign.build_setup(contract, arm, live=live), holdout.RATE if holdout_rate else price_outside_demand.RATE)


def _template(plan: Any, kind: str) -> ImplementationPin:
    for pin in plan.implementation_pins:
        if pin.kind == kind:
            return pin
    raise ValueError(f"the plan has no {kind} pin to model the new one on")


def _harness_registry(setup: Any):
    from aeread.shared_runner.registry import HarnessRegistry

    registry = HarnessRegistry()
    seen = set()
    for harness in setup.harnesses.values():
        key = (harness.id, harness.version)
        if key not in seen:
            registry.register(harness)
            seen.add(key)
    return registry


def _capabilities(plan: Any):
    from aeread.shared_runner.registry import ProviderCapabilities

    return {
        profile.model.provider: ProviderCapabilities(
            native_tools=profile.model.provider == "openrouter", structured_output=True,
            seed=profile.model.provider == "openrouter", system_prompt=True,
            reasoning_budget=profile.model.provider == "openrouter",
            reasoning_token_report=profile.model.provider == "openrouter", max_context_tokens=None,
        )
        for profile in plan.agent_profiles
    }


__all__ = ["BEST_INFORMED_REF", "CEILING_REF", "REFERENCE_IDS", "SCORER_ID", "Seat0PricePlugin", "build_v15_setup",
           "implementation_digest", "references", "rescore", "score_seat0", "seat0_leaf", "seat0_trajectory"]
