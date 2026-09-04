"""The registry-driven family scoring-contract protocol test (spec section 6).

``test_every_registered_family_obeys_the_scoring_contract`` is the one test
this module exists to run. Every registered family must supply a contract
fixture (closed-world enrollment); per family and per fixture, the produced
leaf set, primary, admission, and evidence provenance must match what the
manifest declares; and any family with a trajectory-scoped leaf must supply
two fixtures with a byte-identical terminal outcome and a differing
trajectory, so a scorer that secretly reads only the outcome fails.

This registry is local to this test, not a production one: the five families
already migrated to the ``FamilyScoringInput`` contract (housing,
datacenter_development, procurement_allocation, procurement_grounding,
commercial_state_calibration) do not yet declare a leaf policy on their
production manifests -- that declaration is per-family migration work
(section 5, item 2) this kernel change does not perform, and doing it on the
production manifest builders would perturb already-published
plan_sha256/artifact_sha256 digests (ruling R1). This test therefore attaches
each family's real, already-produced leaf set to a *copy* of its resolved
manifest (``_with_declared_leaf_policy``) purely so the protocol test can
assert the scorer's output against it; the production manifest builders are
untouched.

``datacenter_development_v1`` is deliberately not enrolled here. Its one
trajectory-scoped leaf (``negotiation_temporal_compliance``) is real, but
that family's environment accumulates its full ordered public history
directly into the terminal outcome (see ``environment.py``'s
``public_history``/``temporal_violations`` state fields, both copied
verbatim into ``outcome``), so outcome is itself a function of the full
trajectory: two runs cannot honestly produce a byte-identical outcome from
differing trajectories, and ``_replay_family_trajectory`` correctly refuses
any fabricated evidence where they disagree. There is no real family among
the five already migrated for which the paired-history requirement can be
honestly exercised today, so this module supplies one purpose-built,
provider-free, kernel-owned fixture family (``kernel_contract_reference_v1``)
solely to give the protocol test a genuine trajectory-scoped leaf it can
pair honestly. See ``TRUSTED_BUILTIN_PLUGIN_KEYS`` in ``registry.py`` for the
same note where that family is enrolled as trusted.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.measurement import (
    EstimandSpec,
    FamilyScoreSet,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
    normalize_family_score_set,
)
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    RunPlan,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    LeafPolicyDeclaration,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.evaluation import (
    FamilyScoringInput,
    replay_family_scoring_input,
)
from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    EvidenceStore,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from aeread_families.commercial_state_calibration import build_offline_setup as _build_commercial_state_setup
from aeread_families.commercial_state_calibration import (
    commercial_state_measurement_leaf,
)
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
)
from aeread_families.procurement_allocation import (
    procurement_allocation_measurement_leaf,
    run_fixture_script,
)
from aeread_families.procurement_grounding import (
    build_offline_setup as _build_procurement_grounding_setup,
)
from aeread_families.procurement_grounding import procurement_measurement_leaf
from aeread_families.single_offer.runner import FixedResponseProvider


ROOT = Path(__file__).resolve().parents[1]
_PROCUREMENT_GROUNDING_STRONG = (
    ROOT / "tests" / "fixtures" / "procurement_grounding" / "strong.json"
).read_text(encoding="utf-8")
_COMMERCIAL_STATE_STRONG = (
    ROOT / "tests" / "fixtures" / "commercial_state_calibration" / "strong.json"
).read_text(encoding="utf-8")

# Housing's one leaf id is pinned by name in test_shared_runner_housing.py's
# own assertions; there is no exported leaf-builder function to read it from,
# unlike the other three families below.
_HOUSING_LEAF_ID = "housing_social_welfare_leaf"


# ---------------------------------------------------------------------------
# kernel_contract_reference_v1: a minimal, purpose-built, provider-free
# family. Two single-actor rounds; the terminal outcome is an
# order-insensitive tally of the two rounds' choices, but one declared leaf
# is genuinely trajectory-scoped (it reads which round chose "x" first).
# ---------------------------------------------------------------------------

_REFERENCE_FAMILY_ID = "kernel_contract_reference_v1"
_REFERENCE_FAMILY_VERSION = "1.0.0"
_REFERENCE_PLUGIN_ID = "kernel_contract_reference_plugin"
_REFERENCE_SCORER_ID = "kernel_contract_reference_scorer_v1"
_REFERENCE_RUNTIME_ID = "tests.test_shared_runner_scoring_contract.kernel_contract_reference"
_REFERENCE_PROVIDER_ID = "kernel_contract_scripted_participant"
_REFERENCE_BALANCE_LEAF_ID = "label_balance"
_REFERENCE_TRAJECTORY_LEAF_ID = "first_round_choice_is_x"

_REFERENCE_MODULE_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_REFERENCE_EXECUTION_DIGEST = hashlib.sha256(
    Path(execution_module.__file__).read_bytes()
).hexdigest()


def _reference_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": _REFERENCE_FAMILY_ID,
                "version": _REFERENCE_FAMILY_VERSION,
                "plugin_id": _REFERENCE_PLUGIN_ID,
            },
            "environment": {
                "topology": "two_round_label_choice",
                "phase_specs": ["round_one", "round_two"],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "participant": {
                    "testable": True,
                    "scripted_policies": ["kernel_contract_scripted_participant_v1"],
                },
            },
            "measurement": {
                "primary_estimand": _REFERENCE_BALANCE_LEAF_ID,
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "leaves": [
                    {"leaf_id": _REFERENCE_BALANCE_LEAF_ID, "scope": "finalize_time"},
                    {"leaf_id": _REFERENCE_TRAJECTORY_LEAF_ID, "scope": "finalize_time"},
                ],
                "primary_leaf_id": _REFERENCE_BALANCE_LEAF_ID,
                "admission_leaf_ids": [_REFERENCE_BALANCE_LEAF_ID],
            },
            "scoring": {
                "scorer_id": _REFERENCE_SCORER_ID,
                "reference_provider_ids": [],
            },
        }
    )


class _ReferencePlugin:
    """Two single-actor rounds; outcome tallies choices order-insensitively."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if set(payload) != {"scenario_id"} or not isinstance(payload["scenario_id"], str):
            raise ValueError("payload must contain only a string scenario_id")
        return {"scenario_id": payload["scenario_id"]}

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        del family_case, run
        return {"labels": ()}

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del family_case
        observation_schemas = {"participant": "kernel_contract_observation_v1"}
        action_schemas = {"participant": "kernel_contract_choice_v1"}
        return (
            PhaseSpec(
                "round_one", "participant", "single",
                observation_schemas, action_schemas, 1, "reject", ("round_two",),
            ),
            PhaseSpec(
                "round_two", "participant", "single",
                observation_schemas, action_schemas, 1, "reject", (),
            ),
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state, phase
        return ("participant_0",)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del family_case, seat
        return {"round": len(state["labels"]) + 1, "phase_id": phase.phase_id}

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del family_case, state, seat, phase
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, ValueError):
            return ParseResult.failure("malformed_json")
        if not isinstance(value, dict) or value.get("label") not in {"x", "y"}:
            return ParseResult.failure("malformed_choice")
        return ParseResult.success({"label": value["label"]})

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del family_case, state, seat, phase, action
        return LegalityResult.legal_action()

    def step(self, family_case, state, phase, actions) -> TransitionResult:
        del family_case
        label = actions["participant_0"].action["label"]
        next_state = {"labels": tuple(state["labels"]) + (label,)}
        next_phase = "round_two" if phase.phase_id == "round_one" else None
        return TransitionResult(state=next_state, next_phase_id=next_phase)

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        labels = tuple(state["labels"])
        return {"labels": labels} if len(labels) == 2 else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        del family_case
        labels = terminal["labels"]
        # Deliberately order-insensitive: two differently-ordered trajectories
        # that choose the same multiset of labels produce the same outcome.
        return {"x_count": labels.count("x"), "y_count": labels.count("y")}

    def build_scorer(self, family_case: Mapping[str, Any]) -> "_ReferenceScorer":
        del family_case
        return _ReferenceScorer()

    def build_reference_providers(self, family_case) -> tuple[str, ...]:
        del family_case
        return ()

    def generator(self):
        return lambda *args, **kwargs: None


def _reference_implementation(component_id: str) -> ImplementationRef:
    return ImplementationRef(component_id, "1.0.0", _REFERENCE_MODULE_DIGEST)


def _reference_leaf(*, leaf_id: str, input_scope: str) -> MeasurementLeafSpec:
    units = "count" if input_scope == "terminal_state" else "indicator"
    domain = ValidityDomainSpec(
        domain_id=f"{leaf_id}_domain",
        domain_version="1.0.0",
        schema_ref=f"aeread://kernel_contract_reference/{leaf_id}/v1",
        predicate=_reference_implementation(f"{leaf_id}_validity_v1"),
    )
    estimand = EstimandSpec(
        estimand_id=leaf_id,
        estimand_version="1.0.0",
        input_scope=input_scope,
        direction="maximize",
        units=units,
        validity_domain=domain,
    )
    # "temporal_property" forces input_scope="trajectory" (measurement.py's
    # _REFERENCE_SCOPE); using it here for the trajectory-scoped leaf mirrors
    # how datacenter_development declares negotiation_temporal_compliance.
    reference_kind = (
        "constraint_satisfaction" if input_scope == "terminal_state" else "temporal_property"
    )
    reference = ReferenceSpec(
        reference_id=f"{leaf_id}_reference",
        reference_version="1.0.0",
        reference_kind=reference_kind,
        input_scope=input_scope,
        units=units,
        source_sha256=_REFERENCE_MODULE_DIGEST,
        implementation=_reference_implementation(f"{leaf_id}_reference_v1"),
    )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="rule_constraint",
            evaluation_class="deterministic",
            reference=reference,
        ),
        scorer=_reference_implementation(_REFERENCE_SCORER_ID),
    )


class _ReferenceScorer:
    """Reads the trajectory leaf from ``phase_instances``, never ``outcome``."""

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        outcome = scoring_input.outcome
        balance_leaf = _reference_leaf(
            leaf_id=_REFERENCE_BALANCE_LEAF_ID, input_scope="terminal_state"
        )
        trajectory_leaf = _reference_leaf(
            leaf_id=_REFERENCE_TRAJECTORY_LEAF_ID, input_scope="trajectory"
        )

        first_action = scoring_input.phase_instances[0].actions[0]
        first_choice_is_x = first_action.envelope.action["label"] == "x"

        balance_score = ScoreEnvelope(
            status="ok",
            leaf=balance_leaf,
            primary=MetricValue(float(outcome["x_count"] - outcome["y_count"]), "count"),
            metrics={},
            reference_values={},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )
        trajectory_score = ScoreEnvelope(
            status="ok",
            leaf=trajectory_leaf,
            primary=MetricValue(1.0 if first_choice_is_x else 0.0, "indicator"),
            metrics={},
            reference_values={},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )
        return FamilyScoreSet(
            primary_leaf_id=_REFERENCE_BALANCE_LEAF_ID,
            scores=(balance_score, trajectory_score),
            admission_leaf_ids=(_REFERENCE_BALANCE_LEAF_ID,),
        )


class _ScriptedChoiceProvider:
    """Serves one scripted label per call, in order, then fails closed."""

    def __init__(self, labels: Sequence[str]) -> None:
        self._labels = list(labels)

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if not self._labels:
            raise ProviderFailure(
                "provider_contract", "no scripted labels remain", retryable=False
            )
        output = {"label": self._labels.pop(0)}
        text = canonical_json_bytes(output).decode("utf-8")
        return ProviderResult(
            response_id=f"scripted_{request.provider_call_id}",
            requested_model=request.model,
            resolved_model=request.revision or request.model,
            output_text=text,
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"fixture": True, "output_text": text},
        )


@dataclasses.dataclass(frozen=True, slots=True)
class _ReferenceSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]


def _reference_case() -> CaseManifest:
    raw = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": "kernel_contract_reference_case_v1",
        "family_id": _REFERENCE_FAMILY_ID,
        "family_version": _REFERENCE_FAMILY_VERSION,
        "split": "dev",
        "world_seed": 1,
        "seats": [{"id": "participant_0", "role": "participant"}],
        "episode": {"max_logical_actions": 2, "termination": ["both_rounds_recorded"]},
        "visibility_policy": "kernel_contract_reference_full_visibility_v1",
        "payload": {"scenario_id": "kernel_contract_reference_case_v1"},
        "provenance": {
            "generator_id": "kernel_contract_reference_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _build_reference_setup() -> _ReferenceSetup:
    case = _reference_case()
    family = _reference_family_manifest()
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": "kernel_contract_reference_sample_v1",
            "estimand": "fixed_two_round_label_choice_case",
            "target": "kernel_contract_reference_case_v1",
            "selection": "fixed_curated",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": "kernel_contract_reference_self_play_v1",
            "kind": "self_play",
            "subject_seats": ["participant_0"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "kernel_contract_reference_analysis_v1",
            "estimands": [_REFERENCE_BALANCE_LEAF_ID],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "world_seed",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": "kernel_contract_reference_suite_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    pricing = TokenPricing(0.0, 0.0, 0.0, "kernel_contract_reference_zero_cost_v1")
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": "kernel_contract_reference_participant_v1",
            "model": {
                "provider": _REFERENCE_PROVIDER_ID,
                "model": "kernel_contract_scripted_participant_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": pricing.pricing_id,
                    "pricing_sha256": pricing.content_sha256(),
                },
            },
            "prompt": {
                "prompt_id": "kernel_contract_reference_prompt_v1",
                "sha256": hashlib.sha256(b"choose x or y each round").hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _REFERENCE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "scripted_no_reasoning_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 64,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 2,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.0,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": "kernel_contract_reference_run_spec_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"participant_0": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, _ReferencePlugin())
    harness_registry = HarnessRegistry()
    harnesses = default_harnesses()
    for harness in harnesses.values():
        harness_registry.register(harness)
    pins = (
        ImplementationPin.from_dict(
            {
                "component_id": _REFERENCE_PLUGIN_ID,
                "kind": "family_plugin",
                "version": "1.0.0",
                "sha256": _REFERENCE_MODULE_DIGEST,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": _REFERENCE_SCORER_ID,
                "kind": "scorer",
                "version": "1.0.0",
                "sha256": _REFERENCE_MODULE_DIGEST,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": "minimal_chat",
                "kind": "harness",
                "version": "1.0",
                "sha256": _REFERENCE_EXECUTION_DIGEST,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": _REFERENCE_RUNTIME_ID,
                "kind": "runtime",
                "version": "0.1.0",
                "sha256": _REFERENCE_MODULE_DIGEST,
            }
        ),
    )
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            _REFERENCE_PROVIDER_ID: ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
    )
    return _ReferenceSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            "kernel_contract_reference_prompt_v1": "choose x or y each round"
        },
        pricing={profile.model.model: pricing},
        case=case,
        harnesses=harnesses,
    )


async def _run_reference_episode(labels: Sequence[str], *, evidence_root: Path):
    setup = _build_reference_setup()
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=evidence_root,
        prompt_sources=setup.prompt_sources,
        providers={_REFERENCE_PROVIDER_ID: _ScriptedChoiceProvider(labels)},
        pricing=setup.pricing,
        harnesses=setup.harnesses,
    )
    return setup, execution


# ---------------------------------------------------------------------------
# Fixture wiring for the protocol test's own registry.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class FamilyScoringFixture:
    family_case: Mapping[str, Any]
    sealed_evidence: EvidenceStore


def _with_declared_leaf_policy(
    manifest: FamilyManifest,
    *,
    leaves: tuple[LeafPolicyDeclaration, ...],
    primary_leaf_id: str,
    admission_leaf_ids: tuple[str, ...],
) -> FamilyManifest:
    """Attach a finalize-time leaf policy to a copy of a resolved manifest.

    See this module's docstring: the five already-migrated families do not
    yet declare a leaf policy on their production manifest builders (that is
    per-family migration work this kernel change does not perform, and
    doing it there would perturb already-published plan_sha256 digests --
    ruling R1). This helper attaches the family's real, already-produced
    leaf set to a manifest object used only by this test's own registry, so
    the protocol test can assert against it without touching production
    manifest builders or any frozen digest.
    """
    measurement = dataclasses.replace(
        manifest.measurement,
        leaves=leaves,
        primary_leaf_id=primary_leaf_id,
        admission_leaf_ids=admission_leaf_ids,
    )
    return dataclasses.replace(manifest, measurement=measurement)


def _leaf_policy_for(leaf_id: str) -> dict[str, Any]:
    return {
        "leaves": (LeafPolicyDeclaration(leaf_id, "finalize_time", None),),
        "primary_leaf_id": leaf_id,
        "admission_leaf_ids": (leaf_id,),
    }


def _housing_fixture(tmp_path: Path) -> tuple[FamilyManifest, Any, FamilyScoringFixture]:
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "housing",
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    case = setup.plan.cases[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    manifest = _with_declared_leaf_policy(family, **_leaf_policy_for(_HOUSING_LEAF_ID))
    return (
        manifest,
        plugin,
        FamilyScoringFixture(family_case=family_case, sealed_evidence=execution.evidence),
    )


def _procurement_allocation_script() -> list[str]:
    """A deterministic, fully-negotiated award, mirroring the optimal script
    in test_procurement_allocation_case.py's own fixture suite."""

    negotiated_terms = {
        "switch_reliable": (0.082, 30),
        "oled_reliable": (1.72, 45),
        "charger_reliable": (0.55, 45),
    }
    actions: list[dict[str, Any]] = []
    for supplier_id, (unit_price, refund_window) in negotiated_terms.items():
        actions.extend(
            [
                {
                    "action": "request_quote",
                    "supplier_id": supplier_id,
                    "message": "Please issue a formal quote with full commercial terms.",
                },
                {
                    "action": "counter_offer",
                    "supplier_id": supplier_id,
                    "offer_id": f"offer_{supplier_id}_v1",
                    "proposal": {
                        "unit_price_usd": unit_price,
                        "moq": 10,
                        "payment_terms_days": 60,
                        "refund_window_days": refund_window,
                        "return_freight_payer": "supplier",
                    },
                    "message": "Please formalize these price, payment, and return terms.",
                },
                {
                    "action": "request_sample",
                    "supplier_id": supplier_id,
                    "message": "Please provide the exact-variant qualification sample.",
                },
            ]
        )
    actions.append(
        {
            "action": "submit_award",
            "award_lines": [
                {"offer_id": f"offer_{supplier_id}_v2", "quantity": 20}
                for supplier_id in negotiated_terms
            ],
        }
    )
    return [json.dumps(action, sort_keys=True) for action in actions]


def _procurement_allocation_fixture(
    tmp_path: Path,
) -> tuple[FamilyManifest, Any, FamilyScoringFixture]:
    setup, execution, provider = asyncio.run(
        run_fixture_script(
            _procurement_allocation_script(),
            evidence_root=tmp_path / "procurement_allocation",
        )
    )
    assert provider.exhausted
    case = setup.plan.cases[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    leaf_id = procurement_allocation_measurement_leaf(family_case).leaf_id
    manifest = _with_declared_leaf_policy(family, **_leaf_policy_for(leaf_id))
    return (
        manifest,
        plugin,
        FamilyScoringFixture(family_case=family_case, sealed_evidence=execution.evidence),
    )


def _procurement_grounding_fixture(
    tmp_path: Path,
) -> tuple[FamilyManifest, Any, FamilyScoringFixture]:
    setup = _build_procurement_grounding_setup()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "procurement_grounding",
            prompt_sources=setup.prompt_sources,
            providers={"fake": FixedResponseProvider(_PROCUREMENT_GROUNDING_STRONG)},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    )
    case = setup.plan.cases[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    leaf_id = procurement_measurement_leaf(family_case).leaf_id
    manifest = _with_declared_leaf_policy(family, **_leaf_policy_for(leaf_id))
    return (
        manifest,
        plugin,
        FamilyScoringFixture(family_case=family_case, sealed_evidence=execution.evidence),
    )


def _commercial_state_fixture(
    tmp_path: Path,
) -> tuple[FamilyManifest, Any, FamilyScoringFixture]:
    setup = _build_commercial_state_setup()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "commercial_state_calibration",
            prompt_sources=setup.prompt_sources,
            providers={"fake": FixedResponseProvider(_COMMERCIAL_STATE_STRONG)},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    )
    case = setup.plan.cases[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    leaf_id = commercial_state_measurement_leaf(family_case).leaf_id
    manifest = _with_declared_leaf_policy(family, **_leaf_policy_for(leaf_id))
    return (
        manifest,
        plugin,
        FamilyScoringFixture(family_case=family_case, sealed_evidence=execution.evidence),
    )


def _reference_fixtures(
    tmp_path: Path,
) -> tuple[FamilyManifest, Any, tuple[FamilyScoringFixture, FamilyScoringFixture]]:
    left_setup, left_execution = asyncio.run(
        _run_reference_episode(("x", "y"), evidence_root=tmp_path / "reference_left")
    )
    _right_setup, right_execution = asyncio.run(
        _run_reference_episode(("y", "x"), evidence_root=tmp_path / "reference_right")
    )
    case = left_setup.plan.cases[0]
    family = left_setup.plan.families[0]
    plugin = left_setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    return (
        family,
        plugin,
        (
            FamilyScoringFixture(
                family_case=family_case, sealed_evidence=left_execution.evidence
            ),
            FamilyScoringFixture(
                family_case=family_case, sealed_evidence=right_execution.evidence
            ),
        ),
    )


def _build_protocol_test_registry_and_fixtures(
    tmp_path: Path,
) -> tuple[PluginRegistry, dict[tuple[str, str], tuple[FamilyScoringFixture, ...]]]:
    registry = PluginRegistry()
    fixtures: dict[tuple[str, str], tuple[FamilyScoringFixture, ...]] = {}

    for build in (
        _housing_fixture,
        _procurement_allocation_fixture,
        _procurement_grounding_fixture,
        _commercial_state_fixture,
    ):
        manifest, plugin, fixture = build(tmp_path)
        registry.register_trusted(manifest, plugin)
        fixtures[(manifest.family.id, manifest.family.version)] = (fixture,)

    reference_manifest, reference_plugin, reference_fixtures = _reference_fixtures(tmp_path)
    registry.register_trusted(reference_manifest, reference_plugin)
    fixtures[(reference_manifest.family.id, reference_manifest.family.version)] = (
        reference_fixtures
    )

    return registry, fixtures


def test_every_registered_family_obeys_the_scoring_contract(tmp_path: Path) -> None:
    registry, fixtures = _build_protocol_test_registry_and_fixtures(tmp_path)
    registrations = {
        (registration.family_id, registration.family_version): registration
        for registration in registry.registrations()
    }

    # Closed-world enrollment: a family registered without a contract fixture
    # fails here, before any family is exercised.
    assert set(fixtures) == set(registrations)

    for key, registration in registrations.items():
        declared = registration.manifest.finalize_time_leaf_policy()
        produced_by_case = []
        for case in fixtures[key]:
            scoring_input = replay_family_scoring_input(
                plugin=registration.plugin,
                family_case=case.family_case,
                evidence=case.sealed_evidence,
            )
            produced = normalize_family_score_set(
                registration.plugin.build_scorer(case.family_case)(
                    scoring_input, evidence_refs=scoring_input.evidence_refs
                )
            )
            assert {score.leaf.leaf_id for score in produced.scores} == set(declared.leaf_ids)
            assert produced.primary_leaf_id == declared.primary_leaf_id
            assert produced.admission_leaf_ids == declared.admission_leaf_ids
            assert all(
                score.evidence_refs == scoring_input.evidence_refs
                for score in produced.scores
            )
            produced_by_case.append((scoring_input, produced))

        # trajectory_leaf_ids is derived from the leaf's declared
        # EstimandSpec.input_scope (ruling R5), not from a hand-maintained
        # list: whichever leaves the scorer actually produced as
        # input_scope="trajectory" are the ones the paired-history
        # requirement below applies to.
        trajectory_leaf_ids = {
            score.leaf.leaf_id
            for score in produced_by_case[0][1].scores
            if score.leaf.estimand.input_scope == "trajectory"
        }
        if not trajectory_leaf_ids:
            continue

        assert len(produced_by_case) >= 2
        (left_input, left_scores), (right_input, right_scores) = produced_by_case[:2]
        assert canonical_json_bytes(left_input.outcome) == canonical_json_bytes(
            right_input.outcome
        )
        assert left_input.phase_instances != right_input.phase_instances
        for leaf_id in trajectory_leaf_ids:
            left_value = next(
                score for score in left_scores.scores if score.leaf.leaf_id == leaf_id
            ).primary
            right_value = next(
                score for score in right_scores.scores if score.leaf.leaf_id == leaf_id
            ).primary
            assert left_value != right_value
