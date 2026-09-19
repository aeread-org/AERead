"""Phase 2 identity: admit walk-away markets, remove the hidden-yield checker.

The legacy economics and reference solver remain byte-for-byte unchanged.
"""

from __future__ import annotations
import json
from aeread.shared_runner.run.resolver import canonical_json_bytes

from dataclasses import dataclass, replace
import hashlib
import math
from pathlib import Path

from aeread.shared_runner.measurement import ImplementationRef, MetricValue
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import ParseResult, LegalityResult
from . import environment as legacy

FAMILY_ID = "procurement_allocation_phase2_v1"
PLUGIN_ID = "procurement_allocation_phase2_environment"
SCORER_ID = "procurement_allocation_phase2_scorer_v1"


def measurement_leaf(case):
    leaf = legacy.procurement_allocation_measurement_leaf(case)
    scorer = ImplementationRef(
        SCORER_ID, "1.0.0", hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
    domain = replace(
        leaf.estimand.validity_domain,
        domain_id="procurement_phase2_terminal_domain",
        predicate=scorer,
    )
    return replace(
        leaf,
        leaf_id="procurement_phase2_contribution_margin",
        scorer=scorer,
        estimand=replace(leaf.estimand, validity_domain=domain),
        verifier=replace(
            leaf.verifier,
            objective_scope=replace(
                leaf.verifier.objective_scope, validity_domain=domain
            ),
        ),
    )


@dataclass(frozen=True)
class Scorer:
    family_case: dict

    def __call__(self, scoring_input, *, evidence_refs=()):
        result = legacy.ProcurementAllocationMeasurementScorer(self.family_case)(
            scoring_input, evidence_refs=evidence_refs
        )
        metrics = dict(result.metrics)
        if result.status == "ok":
            metrics["feasible_award"] = MetricValue(
                float(bool(scoring_input.outcome["feasible_award"])), "indicator"
            )
        return replace(result, leaf=measurement_leaf(self.family_case), metrics=metrics)


def family_manifest():
    raw = json.loads(canonical_json_bytes(legacy.family_manifest()))
    raw["family"].update(id=FAMILY_ID, plugin_id=PLUGIN_ID)
    raw["scoring"]["scorer_id"] = SCORER_ID
    return FamilyManifest.from_dict(raw)


class Phase2Plugin(legacy.ProcurementAllocationPlugin):
    def validate_payload(self, payload):
        case = legacy._validate_payload(payload)
        if len(case["suppliers"]) != 8 or case["interaction"]["max_actions"] != 10:
            raise ValueError("Phase 2 requires eight suppliers and ten actions")
        if case["interaction"].get("sample_noise", {}).get("model") != "binomial":
            raise ValueError("Phase 2 requires binomial samples")
        market = case["policy"].get("market_constraints", {})
        if set(market) != {"minimum_delivery_days", "minimum_unit_price_usd", "status"}:
            raise ValueError("Phase 2 requires explicit market constraint provenance")
        if market["status"] != "certified_market_floor_not_supplier_claim":
            raise ValueError("market floors must be certified")
        for key in ("minimum_delivery_days", "minimum_unit_price_usd"):
            value = market[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("invalid market floor")
        for supplier in case["suppliers"]:
            terms = supplier["private_terms"]
            if (
                terms["lead_time_days"] < market["minimum_delivery_days"]
                or terms["negotiation"]["floor_unit_price_usd"]
                < market["minimum_unit_price_usd"]
            ):
                raise ValueError(
                    "market certificate contradicts reachable private terms"
                )
            # Keep this version's public reference arithmetic exactly scoped.
            if (
                terms["return_policy"]["claim_acceptance_probability"] != 0
                or terms["duty_rate"] != 0
                or case["objective"]["annual_financing_rate"] != 0
            ):
                raise ValueError("Phase 2 v1 excludes refunds, duty and financing")
        legacy.solve_full_information_upper_bound(
            case
        )  # finite, action-constrained certificate, including zero
        return case

    def phases(self, family_case):
        return tuple(
            replace(
                p,
                observation_schema_by_role={
                    "buyer": "procurement_phase2_observation_v1"
                },
                action_schema_by_role={"buyer": "procurement_phase2_action_v1"},
            )
            for p in super().phases(family_case)
        )

    def observe(self, family_case, state, seat, phase):
        observation = super().observe(family_case, state, seat, phase)
        observation.pop("award_checks")
        # Canonical offers, claims and samples retain all decision evidence.
        observation.pop("conversation")
        observation["research_terms"] = {
            k: v
            for k, v in family_case["interaction"].items()
            if k not in {"sample_noise", "counter_feedback"}
        }
        observation["formal_offers"] = list(observation["formal_offers"].values())
        observation["verified_samples"] = list(observation["verified_samples"].values())
        observation["inquiry_results"] = [
            json.dumps({"supplier_id": sid, "claims": claims}, sort_keys=True)
            for sid, claims in observation.pop("verbal_claims").items()
        ]
        variants = observation["policy"].pop("required_variant_by_component")
        observation["objective"]["bom"] = [
            dict(component=c, units=n, required_variant=variants[c])
            for c, n in observation["objective"]["bom"].items()
        ]
        return observation

    def parse_action(self, family_case, state, seat, phase, response):
        result = super().parse_action(family_case, state, seat, phase, response)
        if result.ok and result.action["action"] == "check_award":
            return ParseResult.failure("check_award_disabled_phase2")
        return result

    def legal(self, family_case, state, seat, phase, action):
        if action.get("action") == "check_award":
            return LegalityResult.illegal("check_award_disabled_phase2")
        return super().legal(family_case, state, seat, phase, action)

    def step(self, family_case, state, phase, actions):
        # Also fail closed when a caller constructs a valid envelope directly.
        if any(
            e.valid and e.action.get("action") == "check_award"
            for e in actions.values()
        ):
            raise ValueError("check_award_disabled_phase2")
        return super().step(family_case, state, phase, actions)

    def build_scorer(self, family_case):
        return Scorer(family_case)
