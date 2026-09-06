"""The registry-driven family scoring-contract protocol test (spec section 6).

``test_every_registered_family_obeys_the_scoring_contract`` is the one test
this module exists to run. Every registered family must supply a contract
fixture (closed-world enrollment); per family and per fixture, the produced
leaf set, primary, admission, and evidence provenance must match what the
manifest declares; and any family with a trajectory-scoped leaf must supply
two fixtures with a byte-identical terminal outcome and a differing
trajectory, so a scorer that secretly reads only the outcome fails.

Ruling R7 adds the contrapositive: wherever such a pair exists, every leaf
declared ``input_scope="terminal_state"`` must score IDENTICALLY across it --
a leaf that varies is secretly trajectory-dependent and mislabelled. A
determinism pre-check (invoke the scorer twice on the SAME input) runs first,
so a nondeterministic scorer is reported as nondeterministic rather than as
mislabelled. The stated limit: one counterexample pair cannot prove
non-dependence, only refute it when it fires (see
``docs/kernel_contract_design_critique.md``).

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
import itertools
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

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
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
    TRUSTED_BUILTIN_PLUGIN_KEYS,
)
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
    PhaseInstance,
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


# ---------------------------------------------------------------------------
# kernel_contract_gap_review.md finding 4's exact adversary: a scorer whose
# output alternates strictly by a GLOBAL call counter -- never by
# ``scoring_input`` -- so fresh ``build_scorer(...)`` instances (as every
# real family constructs) still share state across invocations, unlike a
# scorer that merely stashes state on ``self``.
# ---------------------------------------------------------------------------

_CALL_PARITY_ADVERSARY_STATE: dict[str, int] = {"calls": 0}


class _CallParityAdversarialScorer:
    """Alternates its one terminal-state leaf's value by global call parity."""

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        del scoring_input
        _CALL_PARITY_ADVERSARY_STATE["calls"] += 1
        parity_value = 1.0 if _CALL_PARITY_ADVERSARY_STATE["calls"] % 2 == 1 else 0.0
        leaf = _reference_leaf(leaf_id=_REFERENCE_BALANCE_LEAF_ID, input_scope="terminal_state")
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(parity_value, "count"),
            metrics={},
            reference_values={},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )


class _CallParityAdversarialPlugin(_ReferencePlugin):
    """``_ReferencePlugin`` with its scorer swapped for the adversary above."""

    def build_scorer(self, family_case: Mapping[str, Any]) -> "_CallParityAdversarialScorer":
        del family_case
        return _CallParityAdversarialScorer()


# ---------------------------------------------------------------------------
# Ruling R9/R10 (round 3): a family whose OUTCOME embeds its own trajectory,
# the exact shape that makes R7's byte-identical-outcome precondition
# unsatisfiable by construction (collusion's ``history``,
# datacenter_development's ``public_history``). ``_ReferencePlugin``'s
# outcome is deliberately order-insensitive so it does NOT need this
# mechanism; this subclass adds one field that DOES carry the trajectory, so
# the (x, y)/(y, x) fixture pair below can no longer produce a byte-identical
# outcome -- proving R9's projection is what recovers the pairing, not a
# coincidence of the existing fixtures.
# ---------------------------------------------------------------------------

_EMBEDDING_BALANCE_LEAF_ID = "embedding_label_balance"
_EMBEDDING_TRAJECTORY_LEAF_ID = "embedding_first_round_choice_is_x"


class _TrajectoryEmbeddingPlugin(_ReferencePlugin):
    """``_ReferencePlugin`` whose outcome also embeds the full trajectory.

    Everything else (``phases``, ``step``, ``terminal``, ...) is inherited
    unchanged -- only ``outcome`` gains a ``labels`` field that is the
    ordered pair of round choices, at the SAME key ``state`` already carries
    it under (``_ReferencePlugin.step`` builds ``{"labels": ...}``), which is
    exactly what lets ``_final_replayed_state`` recover it generically for
    ruling R10 without this test module knowing anything domain-specific.
    """

    def outcome(self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]) -> dict[str, Any]:
        base = super().outcome(family_case, terminal)
        return {**base, "labels": list(terminal["labels"])}

    def build_scorer(self, family_case: Mapping[str, Any]) -> "_TrajectoryEmbeddingScorer":
        del family_case
        return _TrajectoryEmbeddingScorer()


class _TrajectoryCorruptingEmbeddingPlugin(_TrajectoryEmbeddingPlugin):
    """kernel_r9r10_review.md finding 5 mutation fixture: seals a REVERSED
    copy of the trajectory in ``outcome["labels"]`` -- disagreeing with
    ``phase_instances`` at the same declared pointer, exactly the
    corruption ruling R10 exists to catch, produced by a REAL sealed
    episode (through a genuinely buggy ``outcome()``) rather than
    hand-tampered after the fact.
    """

    def outcome(self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]) -> dict[str, Any]:
        base = super().outcome(family_case, terminal)
        return {**base, "labels": list(reversed(terminal["labels"]))}


class _TrajectoryIgnoringEmbeddingPlugin(_TrajectoryEmbeddingPlugin):
    """Same embedding, but its ``trajectory`` leaf ignores the trajectory.

    Ruling R9(b) mutation fixture: a scorer that always returns the same
    value for a leaf declared ``input_scope="trajectory"`` regardless of
    ``scoring_input`` must fail the sensitivity witness.
    """

    def build_scorer(self, family_case: Mapping[str, Any]) -> "_TrajectoryIgnoringScorer":
        del family_case
        return _TrajectoryIgnoringScorer()


class _TrajectoryEmbeddingScorer:
    """Reads the trajectory leaf from ``phase_instances``, never ``outcome``."""

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        outcome = scoring_input.outcome
        balance_leaf = _reference_leaf(
            leaf_id=_EMBEDDING_BALANCE_LEAF_ID, input_scope="terminal_state"
        )
        trajectory_leaf = _reference_leaf(
            leaf_id=_EMBEDDING_TRAJECTORY_LEAF_ID, input_scope="trajectory"
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
            primary_leaf_id=_EMBEDDING_BALANCE_LEAF_ID,
            scores=(balance_score, trajectory_score),
            admission_leaf_ids=(_EMBEDDING_BALANCE_LEAF_ID,),
        )


class _TrajectoryIgnoringScorer(_TrajectoryEmbeddingScorer):
    """Mutation fixture: its ``trajectory`` leaf is constant regardless of input."""

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        score_set = super().__call__(scoring_input, evidence_refs=evidence_refs)
        ignoring_leaf = _reference_leaf(
            leaf_id=_EMBEDDING_TRAJECTORY_LEAF_ID, input_scope="trajectory"
        )
        scores = tuple(
            score
            if score.leaf.leaf_id != _EMBEDDING_TRAJECTORY_LEAF_ID
            else dataclasses.replace(
                score, leaf=ignoring_leaf, primary=MetricValue(0.0, "indicator")
            )
            for score in score_set.scores
        )
        return dataclasses.replace(score_set, scores=scores)


_OVER_BROAD_TRAJECTORY_LEAF_ID = "over_broad_first_round_choice_is_x"


class _OverBroadTrajectoryEmbeddingPlugin(_TrajectoryEmbeddingPlugin):
    """kernel_r9r10_review.md finding 1 (guard a) mutation fixture, redriven
    through the real protocol path by the second-pass review's finding R3:
    outcome consists ENTIRELY of the per-step ``labels`` sequence -- a
    genuine list (satisfying finding 1's guard b), at the SAME state key
    ``_ReferencePlugin.step`` already uses (satisfying ruling R10's
    same-pointer consistency check) -- but the ONLY field in the outcome.
    Declaring ``"/labels"`` as the sole trajectory_outcome_path therefore
    covers the WHOLE outcome, not just a trajectory subtree: projecting it
    away erases every terminal fact too (there are none left) and would
    make the paired-history check vacuous. This family has no
    ``terminal_state``-scoped leaf at all -- its one leaf reads
    ``phase_instances``, never ``outcome`` -- so nothing before the vacuous
    guard has any other reason to fail it.
    """

    def outcome(self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]) -> dict[str, Any]:
        del family_case
        return {"labels": list(terminal["labels"])}

    def build_scorer(self, family_case: Mapping[str, Any]) -> "_OverBroadTrajectoryScorer":
        del family_case
        return _OverBroadTrajectoryScorer()


class _OverBroadTrajectoryScorer:
    """A single ``trajectory``-scoped leaf, read from ``phase_instances`` --
    never from ``outcome``, since this family's outcome carries nothing
    else."""

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()
    ) -> FamilyScoreSet:
        leaf = _reference_leaf(leaf_id=_OVER_BROAD_TRAJECTORY_LEAF_ID, input_scope="trajectory")
        first_action = scoring_input.phase_instances[0].actions[0]
        first_choice_is_x = first_action.envelope.action["label"] == "x"
        score = ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(1.0 if first_choice_is_x else 0.0, "indicator"),
            metrics={},
            reference_values={},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )
        return FamilyScoreSet(
            primary_leaf_id=_OVER_BROAD_TRAJECTORY_LEAF_ID,
            scores=(score,),
            admission_leaf_ids=(_OVER_BROAD_TRAJECTORY_LEAF_ID,),
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


def _build_reference_setup(*, plugin_factory: Any = _ReferencePlugin) -> _ReferenceSetup:
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
    registry.register_trusted(family, plugin_factory())
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


async def _run_reference_episode(
    labels: Sequence[str], *, evidence_root: Path, plugin_factory: Any = _ReferencePlugin
):
    setup = _build_reference_setup(plugin_factory=plugin_factory)
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
    trajectory_outcome_paths: tuple[str, ...] = (),
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

    kernel_r9r10_review.md finding 5: ``trajectory_outcome_paths`` (ruling
    R9) defaults to empty, unaffected for the four real families this is
    also used for -- the R9/R10 end-to-end fixtures (``_embedding_fixtures``
    below) are the only callers that pass a non-empty value, so their
    manifest carries the SAME declaration the protocol path reads, instead
    of a hand-derived tuple kept alongside a manifest that never carries it.
    """
    measurement = dataclasses.replace(
        manifest.measurement,
        leaves=leaves,
        primary_leaf_id=primary_leaf_id,
        admission_leaf_ids=admission_leaf_ids,
        trajectory_outcome_paths=trajectory_outcome_paths,
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


_EMBEDDING_LEAVES = (
    LeafPolicyDeclaration(_EMBEDDING_BALANCE_LEAF_ID, "finalize_time", None),
    LeafPolicyDeclaration(_EMBEDDING_TRAJECTORY_LEAF_ID, "finalize_time", None),
)


def _embedding_fixtures(
    tmp_path: Path,
    *,
    plugin_factory: Any,
    trajectory_outcome_paths: tuple[str, ...],
    evidence_prefix: str,
    label_permutations: Sequence[Sequence[str]] = (("x", "y"), ("y", "x")),
) -> tuple[FamilyManifest, Any, tuple[FamilyScoringFixture, ...]]:
    """Same shape as ``_reference_fixtures``, but for a family whose outcome
    embeds its trajectory (ruling R9).

    kernel_r9r10_review.md finding 5: ``_TrajectoryEmbeddingPlugin`` and its
    siblings are ``_ReferencePlugin`` subclasses registered under the SAME
    trusted ``kernel_contract_reference_v1`` identity (see
    ``_build_reference_setup``, which always builds ``_reference_family_manifest()``
    regardless of ``plugin_factory``) -- ``_with_declared_leaf_policy``
    attaches THIS family's own two-leaf policy and declared
    ``trajectory_outcome_paths`` onto a copy of that resolved manifest,
    exactly the way the four real families' fixtures attach theirs. The
    manifest the protocol path reads is therefore the one that actually
    carries the declaration, not a hand-derived tuple kept alongside a
    manifest that never does.
    """
    setups_and_executions = [
        asyncio.run(
            _run_reference_episode(
                labels,
                evidence_root=tmp_path / f"{evidence_prefix}_{index}",
                plugin_factory=plugin_factory,
            )
        )
        for index, labels in enumerate(label_permutations)
    ]
    first_setup = setups_and_executions[0][0]
    case = first_setup.plan.cases[0]
    family = first_setup.plan.families[0]
    plugin = first_setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    manifest = _with_declared_leaf_policy(
        family,
        leaves=_EMBEDDING_LEAVES,
        primary_leaf_id=_EMBEDDING_BALANCE_LEAF_ID,
        admission_leaf_ids=(_EMBEDDING_BALANCE_LEAF_ID,),
        trajectory_outcome_paths=trajectory_outcome_paths,
    )
    fixtures = tuple(
        FamilyScoringFixture(family_case=family_case, sealed_evidence=execution.evidence)
        for _setup, execution in setups_and_executions
    )
    return manifest, plugin, fixtures


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


def _metric_value_content(value: MetricValue | None) -> tuple[float, str] | None:
    """A ``MetricValue`` reduced to its measured ``(value, unit)``.

    kernel_contract_gap_review.md finding 6: ``MetricValue.metadata`` is an
    unrestricted mapping that participates in dataclass equality (it is a
    plain field, not ``compare=False``). A genuinely terminal-scoped metric
    could hold a byte-identical ``value``/``unit`` across two fixtures while
    its ``metadata`` records something run-specific (e.g. an outcome-event
    id) -- comparing whole ``MetricValue`` objects would then fail the
    paired-history contrapositive as "mislabelled" for a reason that has
    nothing to do with what the leaf measures. Only ``(value, unit)`` is
    measurement content; ``metadata`` is provenance, exactly like
    ``evidence_refs``.
    """
    return None if value is None else (value.value, value.unit)


def _metric_mapping_content(
    mapping: Mapping[str, MetricValue]
) -> tuple[tuple[str, tuple[float, str] | None], ...]:
    return tuple(sorted((key, _metric_value_content(item)) for key, item in mapping.items()))


def _score_measurement_content(score: ScoreEnvelope) -> tuple[Any, ...]:
    """The part of a ``ScoreEnvelope`` that reflects what was measured.

    Ruling R7: ``evidence_refs`` is provenance, not measurement -- two runs
    whose trajectories differ seal different sealed-event ids even when the
    measurement itself is identical, so comparing whole envelopes would fail
    100% of the time for every terminal-scoped leaf. Compare ``status``,
    ``primary``, ``metrics``, ``reference_values``, and ``validity`` (itself
    only ``status`` + ``reasons``, so safe); ``leaf`` and ``evidence_refs`` on
    ``ScoreEnvelope`` are provenance or identity, not measurement content.

    kernel_contract_gap_review.md finding 5: ``utility_by_seat`` and
    ``capture_by_seat`` are also ``ScoreEnvelope`` measurement fields (a
    per-seat allocation breakdown), not provenance -- a leaf could hold its
    aggregate ``primary`` constant while deriving a per-seat breakdown from
    trajectory order, which is exactly the kind of mislabelling this check
    exists to catch. Both are now included.

    kernel_contract_gap_review.md finding 6: every ``MetricValue`` here
    (``primary`` and each value inside ``metrics``, ``reference_values``,
    ``utility_by_seat``, and ``capture_by_seat``) is reduced by
    ``_metric_value_content``/``_metric_mapping_content`` to its
    ``(value, unit)`` pair, discarding ``metadata`` -- see that function's
    docstring for why.
    """
    return (
        score.status,
        _metric_value_content(score.primary),
        _metric_mapping_content(score.metrics),
        _metric_mapping_content(score.reference_values),
        score.validity,
        _metric_mapping_content(score.utility_by_seat),
        _metric_mapping_content(score.capture_by_seat),
    )


# ---------------------------------------------------------------------------
# Ruling R9/R10 (kernel_scoring_contract_spec.md, round 3): families whose
# outcome embeds its own trajectory (collusion's ``history``,
# datacenter_development's ``public_history``) cannot construct a paired
# fixture with a byte-identical OUTCOME -- R7's precondition -- no matter how
# their trajectories differ. The manifest's declared
# ``trajectory_outcome_paths`` (schemas.py) names exactly the outcome fields
# responsible, so the paired-history check below operates on the PROJECTION
# (outcome minus those paths) instead of the whole outcome. A family that
# declares no paths projects to its own whole outcome, so this is a strict
# generalization: govsim and every terminal-only family are unaffected.
#
# Two duties come with the declaration:
#   R9(b) the sensitivity witness -- each ``trajectory``-scoped leaf must be
#     shown capable of changing on SOME fixture pair the family supplies (not
#     necessarily THE paired-history pair -- R7 already rejected requiring
#     that, since a legitimate trajectory metric may coincide on any one
#     pair).
#   R10 the consistency duty -- for every declared path, the outcome's copy
#     of the trajectory must equal the SAME pointer read from the final
#     replayed state. kernel_r9r10_review.md finding 2: this is NOT a
#     "canonical derivation" of history from actions -- the kernel does not
#     re-derive anything. It only re-reads
#     ``phase_instances[-1].transitions[-1].state`` -- exactly the state
#     ``plugin.terminal()`` was called on to produce the terminal result
#     that ``outcome()`` was built from (scheduler.py's ``run_episode``
#     calls ``_terminal(plugin, family_case, state)`` immediately after each
#     ``_step``) -- at the same declared JSON pointer, and requires it to
#     agree with the outcome's sealed copy. Two limits follow directly: a
#     family whose OWN transition function mis-records history is out of
#     scope (both sides would agree, and agree wrongly); and a family whose
#     outcome stores the trajectory under a DIFFERENT field name than its
#     own state (e.g. outcome ``"/public_history"`` copied from state
#     ``"/history"``) cannot declare that path -- the pointer read below is
#     family-agnostic and has no way to know the field was renamed, so it
#     fails loudly (as a named assertion, not a raw ``KeyError``) rather
#     than silently comparing the wrong thing.
# ---------------------------------------------------------------------------


def _json_pointer_get(document: Any, pointer: str) -> Any:
    """Navigate one RFC 6901 JSON pointer into a mapping/sequence document."""
    node = document
    for raw_segment in pointer.split("/")[1:]:
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping):
            if segment not in node:
                raise KeyError(f"{pointer!r} does not exist in this document")
            node = node[segment]
        elif isinstance(node, (list, tuple)):
            node = node[int(segment)]
        else:
            raise KeyError(f"{pointer!r} does not exist in this document")
    return node


def _drop_json_pointer(document: Any, segments: tuple[str, ...]) -> Any:
    if not isinstance(document, Mapping):
        raise TypeError("a trajectory_outcome_path must navigate through JSON objects")
    key = segments[0].replace("~1", "/").replace("~0", "~")
    if key not in document:
        raise KeyError(f"outcome has no {key!r} field to project away")
    if len(segments) == 1:
        return {k: v for k, v in document.items() if k != key}
    return {
        k: (_drop_json_pointer(v, segments[1:]) if k == key else v)
        for k, v in document.items()
    }


def project_outcome(outcome: Mapping[str, Any], paths: tuple[str, ...]) -> Mapping[str, Any]:
    """``outcome`` with every declared ``trajectory_outcome_path`` removed (R9).

    A family declaring no paths projects to itself -- the paired-history
    check below is then byte-for-byte the pre-R9 whole-outcome comparison.

    kernel_r9r10_review.md finding 1, second-pass review R2(b), accepted
    residual: this function and the guards built on it (non-empty
    projection, sequence-shaped path) are STRUCTURAL checks on shape and
    byte-equality -- they cannot decide which of a family's OWN residual
    (non-projected) outcome fields are genuine terminal facts versus
    incidental bookkeeping. A family that declares a field holding its
    actual terminal result as a ``trajectory_outcome_path`` (a list-shaped
    one, satisfying every structural guard) would have that field projected
    away and pass. That declaration is reviewed by a human exactly like the
    primary-leaf choice (spec section 5); the family's own supplied fixtures
    are the conformance evidence for it, not an adversarial boundary this
    kernel enforces unattended.

    Third-pass review C1: an earlier revision of this module also asserted
    a declared trajectory sequence must be non-empty whenever
    ``phase_instances`` replayed at least one transition. That guard was
    removed: it asserted an assumption the specification does not make (one
    replayed transition implies at least one trajectory record), it could
    misfire on a family whose per-round history is appended only when a
    round completes with a fixture ending mid-round, and -- the decisive
    reason -- it guarded nothing. Under ruling R10, an empty embedded
    trajectory must equal an empty list read from the final replayed state,
    and projecting away an empty list leaves the WHOLE outcome in the
    projection unchanged: the paired-history check becomes the
    whole-outcome check, which is STRONGER, not weaker. An empty embedded
    trajectory is therefore not a hole.
    """
    projected: Any = outcome
    for pointer in paths:
        projected = _drop_json_pointer(projected, tuple(pointer.split("/")[1:]))
    return projected


def _first_differing_top_level_key_hint(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> str:
    """A cheap, human-readable hint naming the first top-level key (by
    sorted order) at which two mappings disagree -- present in one but not
    the other, or a differing value -- for an assertion message.

    Only ever called on the FAILURE path: Python's ``assert x, msg`` short-
    circuits evaluating ``msg`` unless ``x`` is falsy, so this one pass over
    the union of keys is never paid when the two mappings already agree.
    """
    for key in sorted(set(left) | set(right)):
        if key not in left:
            return f" (first differing top-level key: {key!r}, only in the right projection)"
        if key not in right:
            return f" (first differing top-level key: {key!r}, only in the left projection)"
        if canonical_json_bytes(left[key]) != canonical_json_bytes(right[key]):
            return f" (first differing top-level key: {key!r})"
    return ""


def _assert_projection_is_not_vacuous(
    projection: Any, *, family_id: str, trajectory_outcome_paths: tuple[str, ...]
) -> None:
    """kernel_r9r10_review.md finding 1 (guard a): a declared
    ``trajectory_outcome_paths`` that covers an object subtree wider than
    the trajectory itself (e.g. ``"/payload"`` when ``payload`` holds both
    terminal fields and the history) projects EVERY fixture's outcome down
    to ``{}``. The paired-history check below would then compare ``{} ==
    {}``, which trivially passes without ever comparing terminal state --
    exactly the vacuous check ruling R7 exists to prevent. This guard fires
    before that comparison, on each fixture's own projection individually.

    kernel_r9r10_review.md second-pass review R2(b), accepted residual:
    "non-empty" is a STRUCTURAL check -- it catches total erasure, not
    partial erasure. A family whose residual projection still holds SOME
    field (any field) passes, even if the specific terminal fact a leaf
    reads was the one dropped. See ``project_outcome``'s docstring for the
    same residual stated once, in full.
    """
    assert isinstance(projection, Mapping) and projection, (
        f"{family_id}: trajectory_outcome_paths {list(trajectory_outcome_paths)} erased "
        "the entire outcome down to an empty mapping -- the paired-history check "
        "(ruling R7) would be vacuous, comparing {} == {} without ever comparing "
        "terminal state"
    )


def _final_replayed_state(phase_instances: tuple[PhaseInstance, ...]) -> Any:
    """The family state ``plugin.terminal()`` was called on to end replay (R10).

    See this section's banner: this is the LAST ``TransitionResult.state``
    across every phase instance, in order -- exactly the state
    ``_replay_family_trajectory`` held when it made its one successful
    ``plugin.terminal(...)`` call.
    """
    for phase_instance in reversed(phase_instances):
        if phase_instance.transitions:
            return phase_instance.transitions[-1].state
    raise ValueError(
        "phase_instances contain no transitions to derive a terminal state from"
    )


def _assert_trajectory_outcome_paths_are_consistent(
    scoring_input: "FamilyScoringInput", paths: tuple[str, ...]
) -> None:
    """Ruling R10: each declared path's outcome copy must equal the SAME
    pointer read from the final replayed state.

    kernel_r9r10_review.md finding 2: this is precisely what is compared,
    and no more. This does NOT re-derive history from actions -- it re-reads
    ``_final_replayed_state`` (the state ``plugin.terminal()`` was called on,
    the product of replaying the family's own sealed transitions through its
    own transition function) at the same declared JSON pointer, and requires
    the outcome's sealed copy to agree with it. A family that embeds its
    trajectory in ``outcome`` is not a contract violation (ruling R10) --
    ``phase_instances`` remains the authoritative scoring provenance; the
    embedded copy is for inspection. This is the duty that comes with
    embedding it: two copies of the trajectory that disagree must fail,
    whatever the disagreement's cause -- WITHIN this check's limits: a
    family whose own transition function mis-records history is out of
    scope, and a family whose outcome stores the trajectory under a
    different field name than its own state cannot declare that path at all
    (the pointer read below fails loudly instead of silently comparing the
    wrong thing).
    """
    if not paths:
        return
    final_state = _final_replayed_state(scoring_input.phase_instances)
    for pointer in paths:
        outcome_value = _json_pointer_get(scoring_input.outcome, pointer)
        # kernel_r9r10_review.md finding 1 (guard b): a declared path that
        # navigates to an object subtree, not a per-step record sequence,
        # may hide terminal facts behind the projection (``project_outcome``
        # drops the WHOLE subtree, not just a trajectory-shaped part of it).
        # This fires before the equality check below, independent of
        # whether the two copies happen to agree. Second-pass review R2(b),
        # accepted residual: this is a STRUCTURAL shape check -- a sequence
        # is required, but nothing here can tell a genuine per-step
        # trajectory apart from some OTHER list-shaped field the family
        # mistakenly (or deliberately) declared instead; see
        # ``project_outcome``'s docstring. Third-pass review C1: an EMPTY
        # sequence is deliberately not rejected here (a guard doing exactly
        # that was added in the second pass and removed in the third --
        # see this module's docstring banner and kernel_r9r10_review.md for
        # why an empty declared trajectory is not a hole).
        assert isinstance(outcome_value, (list, tuple)), (
            f"outcome{pointer} is a {type(outcome_value).__name__}, not a "
            "sequence -- a declared trajectory_outcome_path must point at a "
            "sequence of per-step records; an object subtree may hide "
            "terminal facts behind the projection"
        )
        try:
            derived_value = _json_pointer_get(final_state, pointer)
        except KeyError as error:
            # kernel_r9r10_review.md finding 2: ruling R10 reads the SAME
            # pointer from both the outcome and the final replayed state --
            # a family whose outcome stores its trajectory under a
            # different field name than its own state (e.g. outcome
            # "/public_history" copied from state "/history") cannot
            # declare this path; this is now a named limitation, not a raw
            # KeyError leaking out of a helper the caller never touched.
            raise AssertionError(
                f"outcome{pointer} does not exist in the final replayed state -- "
                "ruling R10 reads the SAME pointer from both the outcome and the "
                "final replayed state; a family whose outcome stores its "
                "trajectory under a different field name than its own state "
                "cannot declare this path"
            ) from error
        assert canonical_json_bytes(outcome_value) == canonical_json_bytes(
            derived_value
        ), (
            f"outcome{pointer} does not match the same pointer read from the "
            "final replayed state -- ruling R10 requires a declared "
            "trajectory_outcome_path to agree with the verified re-execution, "
            "not merely with whatever the family happened to seal"
        )


def _assert_trajectory_leaves_are_witnessed(
    produced_by_case: Sequence[tuple[Any, "FamilyScoreSet", Any]],
    trajectory_leaf_ids: "set[str]",
    *,
    family_id: str,
) -> Mapping[str, tuple[int, int]]:
    """Ruling R9(b): each trajectory-scoped leaf must change on SOME
    SAME-CASE pair -- a SANITY CHECK, not a proof of trajectory-dependence.

    kernel_r9r10_review.md finding 3, fourth-pass review W1: the second-pass
    review (cf85c02f, 42d9fd60) additionally required a byte-identical
    PROJECTED outcome for a pair to count ("controlled"). A real family
    counterexample shows that requirement makes a legitimate
    trajectory-scoped leaf permanently unwitnessable: govsim's
    ``govsim_no_collapse`` (``score_no_collapse`` in
    ``aeread_families/govsim/measurement.py``) reads
    ``terminal["round_trace"]`` (reconstructed from ``phase_instances`` --
    govsim's own ``outcome()`` never carries ``round_trace`` at all, so its
    projection is the WHOLE outcome, not a subtree of it) and reports
    ``collapse_round``/``rounds_completed``. For ``no_collapse`` to differ
    between two fixtures, one must collapse before the round horizon and
    the other must reach it -- but govsim's environment sets ``num_round``
    to exactly the terminating round, so a collapsing fixture and a
    horizon-reached fixture always disagree on ``num_round``, which is part
    of the (whole) outcome/projection; that pair can therefore never be
    "controlled". Two fixtures that both collapse at the SAME round, by
    contrast, share an identical outcome AND score ``no_collapse``
    identically. No pair the family could honestly supply could ever have
    witnessed this leaf under the identical-projection rule. That rule is
    rejected for this reason.

    What this witness DOES prove, keeping the same-case requirement from
    the second-pass review's R1 (a difference caused by a DIFFERENT case is
    not evidence of anything a scorer measured about one case's
    trajectory): the leaf is not CONSTANT across the family's own
    same-case fixtures -- i.e., not provably ignoring its input entirely.
    What it does NOT prove: trajectory-dependence specifically. A leaf that
    reads a differing OUTCOME field -- never the trajectory -- also passes
    this witness, because the outcome is no longer required to match.
    Ruling R7 states why that is acceptable: over-declaring trajectory
    scope is not the hazardous direction -- a terminal-reading leaf
    mislabelled ``trajectory`` still scores correctly, it is merely
    under-constrained; the check WITH TEETH is R7's own contrapositive,
    which requires every ``terminal_state``-declared leaf to score
    identically across a byte-identical-outcome, differing-trajectory
    pair. This witness is a weaker sanity check layered on top of that: a
    trajectory-declared leaf that is constant across every same-case pair
    the family supplies cannot be told apart from one that ignores its
    input entirely, whatever that input turns out to be. Returns which
    pair witnessed each leaf, so a caller can record it.
    """
    if not trajectory_leaf_ids:
        return {}
    same_case_pairs: list[tuple[int, int]] = []
    for (left_index, (left_input, _, left_case)), (right_index, (right_input, _, right_case)) in (
        itertools.combinations(enumerate(produced_by_case), 2)
    ):
        if (
            canonical_json_bytes(left_case) == canonical_json_bytes(right_case)
            and left_input.phase_instances != right_input.phase_instances
        ):
            same_case_pairs.append((left_index, right_index))
    assert same_case_pairs, (
        f"{family_id}: no same-case pair (byte-identical family_case, differing "
        f"phase_instances) exists among the {len(produced_by_case)} supplied "
        "fixtures -- ruling R9(b)'s sensitivity witness requires the family to "
        "supply at least one same-case pair"
    )

    witness_pair_by_leaf: dict[str, tuple[int, int]] = {}
    for leaf_id in trajectory_leaf_ids:
        for left_index, right_index in same_case_pairs:
            left_score = next(
                score
                for score in produced_by_case[left_index][1].scores
                if score.leaf.leaf_id == leaf_id
            )
            right_score = next(
                score
                for score in produced_by_case[right_index][1].scores
                if score.leaf.leaf_id == leaf_id
            )
            if _score_measurement_content(left_score) != _score_measurement_content(
                right_score
            ):
                witness_pair_by_leaf[leaf_id] = (left_index, right_index)
                break
    missing = sorted(trajectory_leaf_ids - set(witness_pair_by_leaf))
    assert not missing, (
        f"{family_id}: trajectory-scoped leaf(ves) {missing} never changed across "
        f"any of the {len(same_case_pairs)} same-case pair(s) examined among the "
        f"{len(produced_by_case)} supplied fixtures -- ruling R9's sensitivity "
        "witness requires each trajectory leaf to be shown capable of change on "
        "SOME same-case pair; a leaf that is constant on every same-case pair "
        "cannot be told apart from one that ignores its input entirely"
    )
    return witness_pair_by_leaf


# ---------------------------------------------------------------------------
# Ruling R6 (kernel_contract_gap_review.md finding 1): the protocol test's
# closed-world assertion previously compared this test's own locally-built
# registry against fixtures built by that same local construction -- true by
# construction, so a family enrolled in TRUSTED_BUILTIN_PLUGIN_KEYS without a
# fixture could never fail it. TRUSTED_BUILTIN_PLUGIN_KEYS is the real
# enrollment authority; the check below closes over it instead.
# ---------------------------------------------------------------------------


def _trusted_family_versions(
    trusted_keys: "frozenset[tuple[str, str, str]]",
) -> "frozenset[tuple[str, str]]":
    return frozenset((family_id, version) for family_id, version, _module in trusted_keys)


# Every TRUSTED_BUILTIN_PLUGIN_KEYS (family_id, version) pair not named here
# must have a FAMILY_SCORING_FIXTURES-equivalent entry in this module, or
# _assert_trusted_catalog_is_closed fails. These are trusted in-tree
# families that have not yet migrated to the FamilyScoringInput contract
# (spec section 5 -- "eleven migration agents," per-family work this kernel
# change does not perform; see this module's docstring and
# kernel_contract_impl_review.md findings 5/7 for why declaring a fixture for
# an unmigrated family is not honestly possible today). This set is
# deliberately named, not derived: adding a NEW trusted key -- the exact
# attack the review demonstrated -- now requires either enrolling a real
# fixture or explicitly widening this exemption; it can no longer happen
# silently.
_NOT_YET_MIGRATED_TRUSTED_KEYS: "frozenset[tuple[str, str]]" = frozenset(
    {
        ("consent_ir_v1", "1.0.0"),
        ("datacenter_development_v1", "1.0.0"),
        ("datacenter_development_v1", "1.1.0"),
        ("datacenter_development_v1", "2.0.0"),
        ("single_offer_v1", "1.0.0"),
        ("tau3.retail", "0.1.0"),
        ("kernel_contract_sequential_v1", "1.0.0"),
        # External-benchmark adapter families enrolled in
        # TRUSTED_BUILTIN_PLUGIN_KEYS by maintainer ruling on 2026-09-04
        # (PRs #28-#38), landed on main after this branch forked. None of
        # the eleven has a FamilyScoringInput-contract fixture yet; they
        # migrate under the per-adapter follow-ups tracked alongside the
        # other not-yet-migrated families above, not as part of this
        # kernel change.
        ("agenticpay.bilateral", "0.1.0"),
        ("alympics.wac", "0.1.0"),
        ("amazonbarg.bilateral", "0.1.0"),
        ("aucarena", "0.1.0"),
        ("collusion", "0.1.0"),
        ("econagent_v1", "0.1.0"),
        ("econevals", "0.1.0"),
        ("govsim", "0.1.0"),
        ("negarena", "0.1.0"),
        ("steer", "0.1.0"),
        ("termsbench", "0.1.0"),
    }
)


def _assert_trusted_catalog_is_closed(
    *,
    trusted_keys: "frozenset[tuple[str, str, str]]",
    enrolled_family_versions: Any,
    exempt_family_versions: Any,
) -> None:
    """Ruling R6: every trusted key is enrolled here or explicitly exempted.

    A key present in neither ``enrolled_family_versions`` nor
    ``exempt_family_versions`` was added to the trusted catalog without this
    protocol test (or a named, reasoned exemption) ever being told about it --
    the review's exact demonstrated attack.
    """

    trusted = _trusted_family_versions(trusted_keys)
    unenrolled = trusted - set(enrolled_family_versions) - set(exempt_family_versions)
    assert not unenrolled, (
        f"trusted plugin key(s) {sorted(unenrolled)} are neither enrolled in "
        "this test's FAMILY_SCORING_FIXTURES nor named in "
        "_NOT_YET_MIGRATED_TRUSTED_KEYS -- ruling R6 requires every "
        "TRUSTED_BUILTIN_PLUGIN_KEYS entry to be accounted for by one or the other"
    )


def test_trusted_catalog_closure_rejects_an_unenrolled_key() -> None:
    """kernel_contract_gap_review.md finding 1, mutation check.

    Without ``_assert_trusted_catalog_is_closed`` (or with its body neutered),
    a key that is neither enrolled nor exempted passes silently -- the
    review's exact demonstrated attack. Proven here directly, without
    touching the real ``TRUSTED_BUILTIN_PLUGIN_KEYS``.
    """

    trusted = frozenset(
        {
            ("fam_a_v1", "1.0.0", "fam_a_module"),
            ("fam_b_v1", "1.0.0", "fam_b_module"),
        }
    )
    # fam_b is explicitly named as not-yet-migrated: passes.
    _assert_trusted_catalog_is_closed(
        trusted_keys=trusted,
        enrolled_family_versions={("fam_a_v1", "1.0.0")},
        exempt_family_versions={("fam_b_v1", "1.0.0")},
    )
    # fam_b is neither enrolled nor exempted -- must fail.
    with pytest.raises(AssertionError):
        _assert_trusted_catalog_is_closed(
            trusted_keys=trusted,
            enrolled_family_versions={("fam_a_v1", "1.0.0")},
            exempt_family_versions=frozenset(),
        )


# ---------------------------------------------------------------------------
# Ruling R7 (kernel_contract_gap_review.md finding 3): an all-mislabelled
# family (every trajectory-reading leaf declared terminal_state) could
# previously supply exactly one fixture and skip the paired-history
# contrapositive entirely, since the old cardinality guard fired only when
# the scorer's OWN (possibly mislabelled) output already declared a
# trajectory leaf. All four already-migrated real families are, today,
# single-leaf and terminal_state-only -- each is currently exactly the shape
# this gap describes. The guard below is unconditional except for this named
# exemption, so a family can no longer silently escape by mislabelling;
# providing the second, terminal-outcome-identical, trajectory-differing
# fixture is per-family domain work (spec section 5) this kernel change does
# not perform for any of the four.
# ---------------------------------------------------------------------------

_SINGLE_FIXTURE_EXEMPT_FAMILIES: "frozenset[tuple[str, str]]" = frozenset(
    {
        ("housing_v1", "1.0.0"),
        ("procurement_allocation_v1", "1.0.0"),
        ("procurement_grounding_v1", "1.0.0"),
        ("commercial_state_calibration_v1", "1.0.0"),
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class _FamilyContractResult:
    """What ``_assert_family_obeys_the_scoring_contract`` found, for callers
    that need to make their OWN additional assertions on top of it (see the
    R9/R10 end-to-end tests below) -- everything it already verified
    internally is not repeated here, only the data those extra assertions
    need."""

    produced_by_case: tuple[tuple[Any, FamilyScoreSet, Any], ...]
    witness_pair_by_leaf: Mapping[str, tuple[int, int]]


def _assert_family_obeys_the_scoring_contract(
    key: tuple[str, str],
    registration: Any,
    cases: Sequence[FamilyScoringFixture],
) -> _FamilyContractResult:
    """One family's full scoring-contract protocol check (spec section 6).

    kernel_r9r10_review.md finding 5, pure extraction: this is the per-family
    body ``test_every_registered_family_obeys_the_scoring_contract`` used to
    run inline in its own loop. Moving it here, unchanged, lets the R9/R10
    end-to-end tests below drive their synthetic embedding families through
    the SAME protocol path the registered-family test uses, instead of
    calling ``project_outcome``/``_assert_trajectory_*`` directly and
    bypassing everything else this function checks (leaf-set/primary/
    admission conformance, evidence provenance, leaf-identity stability, the
    determinism pre-check, ...).
    """
    declared = registration.manifest.finalize_time_leaf_policy()
    # Ruling R9: an exhaustive, family-declared list of the outcome fields
    # that carry the trajectory (empty for every family that does not embed
    # one -- govsim and the four already-migrated families below).
    trajectory_outcome_paths = registration.manifest.measurement.trajectory_outcome_paths
    produced_by_case: list[tuple[Any, FamilyScoreSet, Any]] = []
    stable_leaf_specs: dict[str, Any] = {}

    for index, case in enumerate(cases):
        scoring_input = replay_family_scoring_input(
            plugin=registration.plugin,
            family_case=case.family_case,
            evidence=case.sealed_evidence,
        )
        # Ruling R10: this fixture's OWN outcome must agree with its OWN
        # phase_instances at every declared path -- independent of any
        # pairing with another fixture, and a no-op when the family
        # declares no paths.
        _assert_trajectory_outcome_paths_are_consistent(
            scoring_input, trajectory_outcome_paths
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

        # kernel_contract_gap_review.md finding 7: a leaf's declared
        # identity -- its estimand (including input_scope), verifier, and
        # scorer ref -- must be stable across fixtures for the same
        # family/version. Nothing previously compared the FULL
        # MeasurementLeafSpec across cases, only leaf_id membership, so a
        # scorer could vary a leaf's input_scope, estimand_version, or
        # scorer implementation between fixtures without any conformance
        # failure.
        for score in produced.scores:
            existing = stable_leaf_specs.setdefault(score.leaf.leaf_id, score.leaf)
            assert score.leaf == existing, (
                f"{key[0]}/{score.leaf.leaf_id} returned a different "
                "MeasurementLeafSpec across fixtures (differing input_scope, "
                "estimand_version, verifier, or scorer ref) -- a leaf's "
                "declared identity must be stable for the family version"
            )

        # Determinism pre-check (ruling R7), made adjacent to the
        # original call for THIS case (kernel_contract_gap_review.md
        # finding 4): the previous structure batched both fixtures'
        # original calls, then both fixtures' repeat calls -- call order
        # original-left, original-right, repeat-left, repeat-right -- so
        # a scorer whose output merely alternates by global call-count
        # parity (independent of scoring_input) could still coincide on
        # both same-input comparisons (calls 1 and 3 share parity, as do
        # 2 and 4) and only disagree on the cross-fixture contrapositive
        # below, misreporting nondeterminism as mislabelling. Calling the
        # repeat immediately -- call 2 right after call 1, for this case,
        # before moving to the next -- closes that specific route: such a
        # scorer now disagrees with itself on the very next call.
        if index < 2:
            case_terminal_leaf_ids = {
                score.leaf.leaf_id
                for score in produced.scores
                if score.leaf.estimand.input_scope == "terminal_state"
            }
            repeat = normalize_family_score_set(
                registration.plugin.build_scorer(case.family_case)(
                    scoring_input, evidence_refs=scoring_input.evidence_refs
                )
            )
            for leaf_id in case_terminal_leaf_ids:
                first_score = next(
                    score for score in produced.scores if score.leaf.leaf_id == leaf_id
                )
                second_score = next(
                    score for score in repeat.scores if score.leaf.leaf_id == leaf_id
                )
                assert _score_measurement_content(
                    first_score
                ) == _score_measurement_content(second_score), (
                    f"{key[0]}/{leaf_id} is nondeterministic: invoking the scorer "
                    "twice on the SAME scoring input produced two different "
                    "measurements, so no conclusion about terminal_state "
                    "mislabelling can be drawn from the paired-fixture comparison "
                    "below"
                )

        produced_by_case.append((scoring_input, produced, case.family_case))

    # kernel_contract_gap_review.md finding 3: the paired-history
    # requirement is now unconditional except for the named exemption
    # above -- it no longer depends on the scorer's OWN (possibly
    # mislabelled) output already declaring a trajectory leaf.
    if key not in _SINGLE_FIXTURE_EXEMPT_FAMILIES:
        assert len(produced_by_case) >= 2, (
            f"{key[0]}@{key[1]} supplies fewer than two contract fixtures and is "
            "not in _SINGLE_FIXTURE_EXEMPT_FAMILIES -- ruling R7's paired-history "
            "contrapositive cannot verify any of its declared terminal_state "
            "leaves without a second, outcome-identical, trajectory-differing "
            "fixture"
        )

    if len(produced_by_case) < 2:
        # No paired fixtures to compare -- nothing further to check for
        # this family. Only the four families named in
        # _SINGLE_FIXTURE_EXEMPT_FAMILIES reach this today.
        return _FamilyContractResult(
            produced_by_case=tuple(produced_by_case), witness_pair_by_leaf={}
        )

    # trajectory_leaf_ids / terminal_leaf_ids are derived from the leaf's
    # declared EstimandSpec.input_scope (ruling R5), not from a
    # hand-maintained list: whichever leaves the scorer actually produced
    # with a given input_scope are the ones the checks below apply to.
    # Safe to derive from case 0 alone: the stability check above already
    # proved every other case's leaves are identical to case 0's.
    first_case_scores = produced_by_case[0][1].scores
    terminal_leaf_ids = {
        score.leaf.leaf_id
        for score in first_case_scores
        if score.leaf.estimand.input_scope == "terminal_state"
    }
    trajectory_leaf_ids = {
        score.leaf.leaf_id
        for score in first_case_scores
        if score.leaf.estimand.input_scope == "trajectory"
    }

    # Ruling R9(b), the sensitivity witness (fourth-pass review W1: a
    # SANITY CHECK, not a proof of trajectory-dependence -- see this
    # helper's docstring for the govsim ``no_collapse`` counterexample):
    # every trajectory-scoped leaf must be shown capable of changing
    # across SOME SAME-CASE pair of this family's supplied fixtures (not
    # necessarily the paired-history pair below specifically).
    witness_pair_by_leaf = _assert_trajectory_leaves_are_witnessed(
        produced_by_case, trajectory_leaf_ids, family_id=key[0]
    )

    (left_input, left_scores, _left_case), (right_input, right_scores, _right_case) = produced_by_case[:2]
    # Ruling R9: the paired-history precondition compares the PROJECTION
    # (outcome minus every declared trajectory_outcome_path), not the
    # whole outcome. A family declaring no paths projects to itself, so
    # this is byte-for-byte the pre-R9 check for govsim and every
    # terminal-only family.
    left_projection = project_outcome(left_input.outcome, trajectory_outcome_paths)
    right_projection = project_outcome(right_input.outcome, trajectory_outcome_paths)
    # kernel_r9r10_review.md finding 1 (guard a): an over-broad declared
    # path (one covering an object subtree wider than the trajectory
    # itself) can project BOTH fixtures down to an empty mapping, which
    # would make the equality check below pass vacuously -- {} == {} --
    # without ever comparing terminal state. Each fixture's own
    # projection is checked individually, before they are compared.
    _assert_projection_is_not_vacuous(
        left_projection, family_id=key[0], trajectory_outcome_paths=trajectory_outcome_paths
    )
    _assert_projection_is_not_vacuous(
        right_projection, family_id=key[0], trajectory_outcome_paths=trajectory_outcome_paths
    )
    assert canonical_json_bytes(left_projection) == canonical_json_bytes(
        right_projection
    ), (
        f"{key[0]}: the two paired-history fixtures' projected outcomes are not "
        "byte-identical -- the paired-history precondition is unmet; if this "
        "family's outcome embeds its trajectory, declare trajectory_outcome_paths "
        "(ruling R9)"
        + _first_differing_top_level_key_hint(left_projection, right_projection)
    )
    assert left_input.phase_instances != right_input.phase_instances

    # Ruling R7: a legitimate trajectory metric may legitimately map two
    # distinct histories to the same value (e.g. "did the actor ever
    # concede" being false on both trajectories), so asserting that
    # trajectory-declared leaves must *differ* here is unsound and has
    # been removed rather than corrected. There is no reverse trap for
    # trajectory-declared leaves; the check with teeth is the
    # contrapositive below, for terminal_state-declared leaves.

    # Ruling R7's contrapositive, and the check with teeth: for every
    # leaf declared input_scope="terminal_state", its score must be
    # IDENTICAL across the two fixtures whose terminal outcomes are
    # byte-identical and whose trajectories differ (asserted above). A
    # leaf that varies here is secretly trajectory-dependent and
    # mislabelled -- this is exactly the leaf the paired-history check
    # previously gave no coverage to, since only trajectory-declared
    # leaves were ever compared across the pair.
    for leaf_id in terminal_leaf_ids:
        left_score = next(
            score for score in left_scores.scores if score.leaf.leaf_id == leaf_id
        )
        right_score = next(
            score for score in right_scores.scores if score.leaf.leaf_id == leaf_id
        )
        assert _score_measurement_content(left_score) == _score_measurement_content(
            right_score
        ), (
            f"{key[0]}/{leaf_id} is declared input_scope=terminal_state but its score "
            "differs between two fixtures with a byte-identical outcome and a differing "
            "trajectory -- it is secretly trajectory-dependent and mislabelled"
        )

    return _FamilyContractResult(
        produced_by_case=tuple(produced_by_case), witness_pair_by_leaf=witness_pair_by_leaf
    )


def test_every_registered_family_obeys_the_scoring_contract(tmp_path: Path) -> None:
    registry, fixtures = _build_protocol_test_registry_and_fixtures(tmp_path)
    registrations = {
        (registration.family_id, registration.family_version): registration
        for registration in registry.registrations()
    }

    # Closed-world enrollment: a family registered without a contract fixture
    # fails here, before any family is exercised. (This is this test's OWN
    # local registry, not TRUSTED_BUILTIN_PLUGIN_KEYS -- see the assertion
    # below for that check.)
    assert set(fixtures) == set(registrations)

    # Ruling R6 (kernel_contract_gap_review.md finding 1): the real closed
    # world is TRUSTED_BUILTIN_PLUGIN_KEYS. The assertion above was true by
    # construction and could never fail; a family enrolled there without a
    # fixture (or an explicit, named "not yet migrated" exemption) now fails
    # here instead.
    _assert_trusted_catalog_is_closed(
        trusted_keys=TRUSTED_BUILTIN_PLUGIN_KEYS,
        enrolled_family_versions=set(fixtures),
        exempt_family_versions=_NOT_YET_MIGRATED_TRUSTED_KEYS,
    )

    for key, registration in registrations.items():
        _assert_family_obeys_the_scoring_contract(key, registration, fixtures[key])


def test_determinism_precheck_adjacency_defeats_call_parity_aliasing(tmp_path: Path) -> None:
    """kernel_contract_gap_review.md finding 4, mutation check.

    Reproduces the review's exact adversary (``_CallParityAdversarialScorer``)
    against two REAL sealed episodes -- byte-identical outcome, differing
    trajectory, built by the same ``_run_reference_episode`` machinery the
    main protocol test uses -- and proves the mechanism the fix relies on:

    Under the OLD batched call order (original-left, original-right,
    repeat-left, repeat-right -- calls 1, 2, 3, 4), calls 1 and 3 share
    parity, as do 2 and 4, so both same-input ("determinism") comparisons
    incorrectly pass and the true defect (nondeterminism) only ever surfaces
    as a cross-fixture contrapositive failure, misreported as "mislabelled".

    Under the NEW adjacent call order (repeat immediately after its own
    fixture's original call, before the other fixture is ever touched), the
    same scorer disagrees with itself on the very next call and is caught as
    nondeterministic, which is what
    ``test_every_registered_family_obeys_the_scoring_contract`` now does for
    every family's first two fixtures.
    """

    _CALL_PARITY_ADVERSARY_STATE["calls"] = 0
    left_setup, left_execution = asyncio.run(
        _run_reference_episode(
            ("x", "y"),
            evidence_root=tmp_path / "adversary_left",
            plugin_factory=_CallParityAdversarialPlugin,
        )
    )
    _right_setup, right_execution = asyncio.run(
        _run_reference_episode(
            ("y", "x"),
            evidence_root=tmp_path / "adversary_right",
            plugin_factory=_CallParityAdversarialPlugin,
        )
    )
    plugin = left_setup.registry.resolve_manifest(left_setup.plan.families[0])
    family_case = plugin.validate_payload(left_setup.plan.cases[0].payload)

    left_scoring_input = replay_family_scoring_input(
        plugin=plugin, family_case=family_case, evidence=left_execution.evidence
    )
    right_scoring_input = replay_family_scoring_input(
        plugin=plugin, family_case=family_case, evidence=right_execution.evidence
    )
    # Sanity: this really is a byte-identical-outcome, differing-trajectory
    # pair, exactly what the main protocol test requires for the pairing.
    assert canonical_json_bytes(left_scoring_input.outcome) == canonical_json_bytes(
        right_scoring_input.outcome
    )
    assert left_scoring_input.phase_instances != right_scoring_input.phase_instances

    # OLD (batched) order: original-left, original-right, repeat-left,
    # repeat-right -- calls 1, 2, 3, 4.
    _CALL_PARITY_ADVERSARY_STATE["calls"] = 0
    old_original_left = plugin.build_scorer(family_case)(left_scoring_input, evidence_refs=())
    old_original_right = plugin.build_scorer(family_case)(right_scoring_input, evidence_refs=())
    old_repeat_left = plugin.build_scorer(family_case)(left_scoring_input, evidence_refs=())
    old_repeat_right = plugin.build_scorer(family_case)(right_scoring_input, evidence_refs=())
    assert _score_measurement_content(old_original_left) == _score_measurement_content(
        old_repeat_left
    ), "the OLD batched order was expected to (incorrectly) call this deterministic"
    assert _score_measurement_content(old_original_right) == _score_measurement_content(
        old_repeat_right
    ), "the OLD batched order was expected to (incorrectly) call this deterministic"
    assert _score_measurement_content(old_original_left) != _score_measurement_content(
        old_original_right
    ), "the true defect was expected to surface only as a cross-fixture disagreement"

    # NEW (adjacent) order: original-left, repeat-left -- calls 1, 2 --
    # immediately, before the right fixture is ever touched.
    _CALL_PARITY_ADVERSARY_STATE["calls"] = 0
    new_original_left = plugin.build_scorer(family_case)(left_scoring_input, evidence_refs=())
    new_repeat_left = plugin.build_scorer(family_case)(left_scoring_input, evidence_refs=())
    assert _score_measurement_content(new_original_left) != _score_measurement_content(
        new_repeat_left
    ), "adjacency should have caught this scorer as nondeterministic, not let it slip through"


# ---------------------------------------------------------------------------
# Ruling R9/R10, end-to-end: the same mechanism the unit tests above exercise
# against hand-built fixtures, now against REAL sealed episodes produced by
# ``_TrajectoryEmbeddingPlugin``/``_TrajectoryIgnoringEmbeddingPlugin`` (both
# defined earlier in this module, alongside ``_ReferencePlugin``). Mirrors
# ``test_determinism_precheck_adjacency_defeats_call_parity_aliasing``'s
# shape: build two real, differently-labelled episodes, replay each, and
# drive the R9/R10 helper functions directly rather than going through
# ``test_every_registered_family_obeys_the_scoring_contract`` (which has no
# family enrolled whose outcome embeds its trajectory -- see this module's
# docstring on why ``kernel_contract_reference_v1``'s outcome is deliberately
# order-insensitive instead).
# ---------------------------------------------------------------------------


def test_r9_projection_pairs_a_trajectory_embedding_outcome_when_the_path_is_declared(
    tmp_path: Path,
) -> None:
    """A REAL family whose outcome embeds its trajectory (mirroring
    collusion's ``history``/datacenter_development's ``public_history``)
    cannot produce a byte-identical raw outcome across two differing
    trajectories -- ``_TrajectoryEmbeddingPlugin.outcome`` carries the full
    ordered ``labels`` alongside the order-insensitive tally
    ``_ReferencePlugin`` already returns. Declaring the embedding path
    (``/labels``) lets the PROJECTION recover the pairing that R7's
    byte-identical-outcome precondition would otherwise make unsatisfiable
    by construction (ruling R9, round 3).

    kernel_r9r10_review.md finding 5: this now drives the fixtures through
    ``_assert_family_obeys_the_scoring_contract`` -- the SAME protocol path
    ``test_every_registered_family_obeys_the_scoring_contract`` uses for the
    four real families -- instead of calling ``project_outcome``/
    ``_assert_trajectory_*`` directly and bypassing everything else that
    function checks.
    """
    manifest, plugin, fixtures = _embedding_fixtures(
        tmp_path,
        plugin_factory=_TrajectoryEmbeddingPlugin,
        trajectory_outcome_paths=("/labels",),
        evidence_prefix="embedding",
    )
    registry = PluginRegistry()
    registry.register_trusted(manifest, plugin)
    registration = registry.resolve_registration(
        manifest.family.id, manifest.family.version, manifest.family.plugin_id
    )
    key = (manifest.family.id, manifest.family.version)

    result = _assert_family_obeys_the_scoring_contract(key, registration, fixtures)

    # Ruling R9(b), the sensitivity witness: the genuinely trajectory-scoped
    # leaf changes across the one controlled pair this family supplies.
    assert result.witness_pair_by_leaf == {_EMBEDDING_TRAJECTORY_LEAF_ID: (0, 1)}

    # Ruling R7's contrapositive: the terminal_state-declared leaf is
    # identical across the pair (both permutations tally the same). Already
    # asserted internally by the helper above; re-asserted here as the
    # specific, named claim this test exists to make.
    (_, left_scores, _), (_, right_scores, _) = result.produced_by_case
    left_balance = next(
        score for score in left_scores.scores if score.leaf.leaf_id == _EMBEDDING_BALANCE_LEAF_ID
    )
    right_balance = next(
        score for score in right_scores.scores if score.leaf.leaf_id == _EMBEDDING_BALANCE_LEAF_ID
    )
    assert _score_measurement_content(left_balance) == _score_measurement_content(
        right_balance
    )


def test_r9_projection_fails_to_pair_when_the_embedded_path_is_not_declared(
    tmp_path: Path,
) -> None:
    """Mutation check, over the SAME real fixture pair as the test above,
    driven through the SAME protocol path: declaring NO paths for a family
    whose outcome genuinely embeds its trajectory must not silently let the
    pairing through by accident -- the one field that actually carries the
    trajectory (``labels``) must remain visible in the projection and keep
    the two outcomes apart, proving the declaration above is doing real
    work rather than coincidentally matching.

    kernel_r9r10_review.md finding 5, fourth-pass review W1: the
    sensitivity witness (which runs first) no longer requires a matching
    projection -- same case and differing phase_instances are enough, which
    this pair still satisfies even with no declared paths -- so the witness
    itself no longer rejects this family. The protocol still fails, at the
    paired-history projection-equality check further down: with no
    declared paths, ``project_outcome`` is the identity, and the one field
    that actually carries the trajectory (``labels``) remains visible and
    keeps the two raw outcomes apart. That check now names the failure
    (root-fix, follow-up to the fourth pass): matching on a fragment of its
    own message, not a bare ``AssertionError``, so this test is sensitive
    to THIS precondition failing specifically, not to any assertion
    anywhere in the protocol path.
    """
    manifest, plugin, fixtures = _embedding_fixtures(
        tmp_path,
        plugin_factory=_TrajectoryEmbeddingPlugin,
        trajectory_outcome_paths=(),
        evidence_prefix="embedding_undeclared",
    )
    registry = PluginRegistry()
    registry.register_trusted(manifest, plugin)
    registration = registry.resolve_registration(
        manifest.family.id, manifest.family.version, manifest.family.plugin_id
    )
    key = (manifest.family.id, manifest.family.version)

    with pytest.raises(AssertionError, match="paired-history precondition is unmet"):
        _assert_family_obeys_the_scoring_contract(key, registration, fixtures)


def test_projection_is_not_vacuous_rejects_a_projection_erased_to_an_empty_mapping() -> None:
    """kernel_r9r10_review.md finding 1 (guard a), unit check."""
    with pytest.raises(AssertionError, match="vacuous"):
        _assert_projection_is_not_vacuous(
            {}, family_id="fixture_family", trajectory_outcome_paths=("/payload",)
        )


def test_projection_is_not_vacuous_accepts_a_non_empty_projection() -> None:
    _assert_projection_is_not_vacuous(
        {"x_count": 1}, family_id="fixture_family", trajectory_outcome_paths=("/history",)
    )


def test_trajectory_outcome_path_consistency_rejects_a_mapping_shaped_path() -> None:
    """kernel_r9r10_review.md finding 1 (guard b), unit check: a declared
    path that navigates to an object subtree, not a per-step record
    sequence, is rejected before the equality check ever runs -- an object
    subtree may hide terminal facts behind the projection."""
    phase_instances = (_phase_instance_ending_in_state({"history": {"round_1": "x"}}),)
    scoring_input = FamilyScoringInput(
        outcome={"history": {"round_1": "x"}}, phase_instances=phase_instances, evidence_refs=()
    )
    with pytest.raises(AssertionError, match="sequence"):
        _assert_trajectory_outcome_paths_are_consistent(scoring_input, ("/history",))


def test_r9_projection_erases_the_entire_outcome_when_the_declared_path_is_over_broad(
    tmp_path: Path,
) -> None:
    """kernel_r9r10_review.md finding 1 (guard a), second-pass review R3:
    a REAL family whose outcome is ENTIRELY the per-step ``labels``
    sequence declares that one field as its trajectory_outcome_path.
    Projecting it away erases the whole outcome, not merely a subtree.

    Driven through ``_assert_family_obeys_the_scoring_contract`` -- the SAME
    protocol path the registered-family test uses -- instead of calling
    ``project_outcome``/``_assert_projection_is_not_vacuous`` directly: the
    original shape of this test (kernel_r9r10_review.md finding 5's own
    residual) would have stayed green even if the protocol path stopped
    calling the vacuous-projection guard at all.
    """
    left_setup, left_execution = asyncio.run(
        _run_reference_episode(
            ("x", "y"),
            evidence_root=tmp_path / "overbroad_left",
            plugin_factory=_OverBroadTrajectoryEmbeddingPlugin,
        )
    )
    _right_setup, right_execution = asyncio.run(
        _run_reference_episode(
            ("y", "x"),
            evidence_root=tmp_path / "overbroad_right",
            plugin_factory=_OverBroadTrajectoryEmbeddingPlugin,
        )
    )
    case = left_setup.plan.cases[0]
    family = left_setup.plan.families[0]
    plugin = left_setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)

    manifest = _with_declared_leaf_policy(
        family,
        leaves=(LeafPolicyDeclaration(_OVER_BROAD_TRAJECTORY_LEAF_ID, "finalize_time", None),),
        primary_leaf_id=_OVER_BROAD_TRAJECTORY_LEAF_ID,
        admission_leaf_ids=(_OVER_BROAD_TRAJECTORY_LEAF_ID,),
        trajectory_outcome_paths=("/labels",),
    )
    registry = PluginRegistry()
    registry.register_trusted(manifest, plugin)
    registration = registry.resolve_registration(
        manifest.family.id, manifest.family.version, manifest.family.plugin_id
    )
    key = (manifest.family.id, manifest.family.version)
    fixtures = (
        FamilyScoringFixture(family_case=family_case, sealed_evidence=left_execution.evidence),
        FamilyScoringFixture(family_case=family_case, sealed_evidence=right_execution.evidence),
    )

    with pytest.raises(AssertionError, match="vacuous"):
        _assert_family_obeys_the_scoring_contract(key, registration, fixtures)


def test_projection_is_not_vacuous_rejects_each_fixtures_projection_independently(
    tmp_path: Path,
) -> None:
    """kernel_r9r10_review.md finding 5, third-pass review C2: the protocol-
    path version of the test above raises on the LEFT fixture's projection
    before the RIGHT fixture's guard call is ever reached -- one raised
    ``AssertionError`` aborts ``_assert_family_obeys_the_scoring_contract``
    immediately, so that test alone no longer demonstrates the guard
    rejecting the right fixture's projection too. This is a separate,
    direct unit test of ``_assert_projection_is_not_vacuous`` restoring
    that independent coverage over the SAME real over-broad fixture pair,
    alongside (not instead of) the protocol-path test.
    """
    left_setup, left_execution = asyncio.run(
        _run_reference_episode(
            ("x", "y"),
            evidence_root=tmp_path / "overbroad_independent_left",
            plugin_factory=_OverBroadTrajectoryEmbeddingPlugin,
        )
    )
    _right_setup, right_execution = asyncio.run(
        _run_reference_episode(
            ("y", "x"),
            evidence_root=tmp_path / "overbroad_independent_right",
            plugin_factory=_OverBroadTrajectoryEmbeddingPlugin,
        )
    )
    plugin = left_setup.registry.resolve_manifest(left_setup.plan.families[0])
    family_case = plugin.validate_payload(left_setup.plan.cases[0].payload)
    left_input = replay_family_scoring_input(
        plugin=plugin, family_case=family_case, evidence=left_execution.evidence
    )
    right_input = replay_family_scoring_input(
        plugin=plugin, family_case=family_case, evidence=right_execution.evidence
    )

    over_broad_paths = ("/labels",)
    left_projection = project_outcome(left_input.outcome, over_broad_paths)
    right_projection = project_outcome(right_input.outcome, over_broad_paths)
    # Sanity: the projection really is empty for both fixtures, not merely
    # small -- otherwise this would not be exercising the vacuous case.
    assert left_projection == {} and right_projection == {}

    with pytest.raises(AssertionError, match="vacuous"):
        _assert_projection_is_not_vacuous(
            left_projection, family_id="over_broad_fixture_family", trajectory_outcome_paths=over_broad_paths
        )
    with pytest.raises(AssertionError, match="vacuous"):
        _assert_projection_is_not_vacuous(
            right_projection, family_id="over_broad_fixture_family", trajectory_outcome_paths=over_broad_paths
        )


def test_sensitivity_witness_rejects_a_trajectory_leaf_that_ignores_the_trajectory(
    tmp_path: Path,
) -> None:
    """Ruling R9(b), mutation check, end-to-end, driven through the SAME
    protocol path as the test above:
    ``_TrajectoryIgnoringEmbeddingPlugin``'s scorer returns a constant value
    for its ``trajectory``-declared leaf regardless of ``scoring_input`` --
    the witness must reject it, over the same real fixture shape the correct
    scorer above is witnessed on."""
    manifest, plugin, fixtures = _embedding_fixtures(
        tmp_path,
        plugin_factory=_TrajectoryIgnoringEmbeddingPlugin,
        trajectory_outcome_paths=("/labels",),
        evidence_prefix="embedding_ignoring",
    )
    registry = PluginRegistry()
    registry.register_trusted(manifest, plugin)
    registration = registry.resolve_registration(
        manifest.family.id, manifest.family.version, manifest.family.plugin_id
    )
    key = (manifest.family.id, manifest.family.version)

    with pytest.raises(AssertionError, match="never changed"):
        _assert_family_obeys_the_scoring_contract(key, registration, fixtures)


def test_r10_rejects_a_corrupted_trajectory_outcome_copy_end_to_end(
    tmp_path: Path,
) -> None:
    """Ruling R10, mutation check, end-to-end, driven through the SAME
    protocol path as the tests above: ``_TrajectoryCorruptingEmbeddingPlugin``
    seals a REVERSED copy of the trajectory in ``outcome["labels"]`` --
    disagreeing with ``phase_instances`` at the same declared pointer -- in a
    REAL sealed episode, not the hand-tampered ``FamilyScoringInput``
    ``test_r10_rejects_a_corrupted_trajectory_outcome_copy`` above uses. A
    single fixture is enough: R10's per-fixture consistency check runs
    inside the protocol path's per-case loop, before the (unreachable, for
    this un-exempted family) ">= 2 fixtures" requirement.
    """
    manifest, plugin, fixtures = _embedding_fixtures(
        tmp_path,
        plugin_factory=_TrajectoryCorruptingEmbeddingPlugin,
        trajectory_outcome_paths=("/labels",),
        evidence_prefix="embedding_corrupted",
        label_permutations=(("x", "y"),),
    )
    registry = PluginRegistry()
    registry.register_trusted(manifest, plugin)
    registration = registry.resolve_registration(
        manifest.family.id, manifest.family.version, manifest.family.plugin_id
    )
    key = (manifest.family.id, manifest.family.version)

    with pytest.raises(AssertionError, match="does not match the same pointer read"):
        _assert_family_obeys_the_scoring_contract(key, registration, fixtures)


def test_score_measurement_content_includes_seat_breakdowns() -> None:
    """kernel_contract_gap_review.md finding 5, mutation check.

    A leaf could hold its aggregate ``primary`` constant while varying its
    per-seat allocation breakdown by trajectory order -- exactly the kind of
    mislabelling ruling R7's contrapositive exists to catch.
    ``_score_measurement_content`` must treat a differing ``utility_by_seat``
    or ``capture_by_seat`` as a genuine measurement difference.
    """
    leaf = _reference_leaf(leaf_id=_REFERENCE_BALANCE_LEAF_ID, input_scope="terminal_state")
    base_kwargs: dict[str, Any] = dict(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "count"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=(),
    )
    left = ScoreEnvelope(
        **base_kwargs, utility_by_seat={"participant_0": MetricValue(1.0, "count")}
    )
    right = ScoreEnvelope(
        **base_kwargs, utility_by_seat={"participant_0": MetricValue(0.0, "count")}
    )
    # Sanity: everything the OLD comparison looked at is identical.
    assert (left.status, left.primary, left.metrics, left.reference_values, left.validity) == (
        right.status,
        right.primary,
        right.metrics,
        right.reference_values,
        right.validity,
    )
    assert _score_measurement_content(left) != _score_measurement_content(right)

    left_capture = ScoreEnvelope(
        **base_kwargs, capture_by_seat={"participant_0": MetricValue(1.0, "count")}
    )
    right_capture = ScoreEnvelope(
        **base_kwargs, capture_by_seat={"participant_0": MetricValue(0.0, "count")}
    )
    assert _score_measurement_content(left_capture) != _score_measurement_content(right_capture)


def test_score_measurement_content_ignores_metric_metadata() -> None:
    """kernel_contract_gap_review.md finding 6, mutation check.

    ``MetricValue.metadata`` is an unrestricted mapping that participates in
    ``MetricValue.__eq__`` -- a scorer could legitimately (or adversarially)
    stash a per-run provenance value there (e.g. an outcome-event id) without
    changing what was actually measured. ``_score_measurement_content`` must
    compare only ``(value, unit)``, not ``metadata``.
    """
    leaf = _reference_leaf(leaf_id=_REFERENCE_BALANCE_LEAF_ID, input_scope="terminal_state")
    left = ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "count", metadata={"outcome_event_id": "event_left"}),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=(),
    )
    right = ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "count", metadata={"outcome_event_id": "event_right"}),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=(),
    )
    # Sanity: the raw MetricValue objects DO differ (metadata participates in
    # dataclass equality) -- proving there is something for the guard to do.
    assert left.primary != right.primary
    assert _score_measurement_content(left) == _score_measurement_content(right)


# ---------------------------------------------------------------------------
# Ruling R9/R10 direct unit tests: each guard exercised in isolation, against
# hand-built fixtures, before the full-episode integration tests further
# below wire the same functions into a real replayed family.
# ---------------------------------------------------------------------------


def test_project_outcome_is_the_identity_when_no_paths_are_declared() -> None:
    outcome = {"termination_reason": "max_periods", "rounds_played": 2, "history": ["x", "y"]}
    assert project_outcome(outcome, ()) == outcome


def test_project_outcome_removes_exactly_the_declared_paths() -> None:
    outcome = {"termination_reason": "max_periods", "rounds_played": 2, "history": ["x", "y"]}
    projected = project_outcome(outcome, ("/history",))
    assert projected == {"termination_reason": "max_periods", "rounds_played": 2}
    # The original is untouched -- projection must not mutate its input.
    assert outcome["history"] == ["x", "y"]


def test_project_outcome_supports_a_nested_path() -> None:
    outcome = {"summary": {"history": ["x", "y"], "rounds": 2}}
    assert project_outcome(outcome, ("/summary/history",)) == {"summary": {"rounds": 2}}


def _phase_instance_ending_in_state(state: Mapping[str, Any]) -> PhaseInstance:
    return PhaseInstance(
        phase_instance_id="phase_instance_0",
        phase_id="round_two",
        ordinal=1,
        mode="single",
        eligible_actors=("participant_0",),
        pre_state_sha256="0" * 64,
        post_state_sha256="1" * 64,
        observations={},
        actions=(),
        transitions=(TransitionResult(state=state, next_phase_id=None),),
    )


def test_final_replayed_state_reads_the_last_transitions_state() -> None:
    phase_instances = (
        _phase_instance_ending_in_state({"labels": ("x",)}),
        dataclasses.replace(
            _phase_instance_ending_in_state({"labels": ("x", "y")}), ordinal=2
        ),
    )
    assert _final_replayed_state(phase_instances) == {"labels": ("x", "y")}


def test_final_replayed_state_skips_a_trailing_phase_instance_with_no_transitions() -> None:
    """A phase instance that never called ``step`` (an edge case the kernel does
    not rule out structurally) must not hide the real final state behind it."""
    phase_instances = (
        _phase_instance_ending_in_state({"labels": ("x", "y")}),
        dataclasses.replace(
            _phase_instance_ending_in_state({"labels": ("x", "y")}),
            ordinal=2,
            transitions=(),
        ),
    )
    assert _final_replayed_state(phase_instances) == {"labels": ("x", "y")}


def test_final_replayed_state_rejects_no_transitions_anywhere() -> None:
    phase_instances = (
        dataclasses.replace(
            _phase_instance_ending_in_state({"labels": ()}), transitions=()
        ),
    )
    with pytest.raises(ValueError, match="no transitions"):
        _final_replayed_state(phase_instances)


def test_r10_accepts_an_outcome_copy_that_matches_its_derivation() -> None:
    phase_instances = (_phase_instance_ending_in_state({"labels": ["x", "y"]}),)
    scoring_input = FamilyScoringInput(
        outcome={"labels": ["x", "y"]}, phase_instances=phase_instances, evidence_refs=()
    )
    # Tolerant of tuple-vs-list encoding, like every other canonical_json_bytes
    # comparison in this module -- the state carries a list here and a tuple
    # in the corrupted case below on purpose, to prove that is not what this
    # guard is sensitive to.
    _assert_trajectory_outcome_paths_are_consistent(scoring_input, ("/labels",))


def test_r10_rejects_a_corrupted_trajectory_outcome_copy() -> None:
    """Ruling R10, mutation check: two disagreeing copies of the trajectory
    must fail, independent of what caused the disagreement."""
    phase_instances = (_phase_instance_ending_in_state({"labels": ("x", "y")}),)
    corrupted = FamilyScoringInput(
        # The outcome's copy has been tampered with (order swapped) relative
        # to what phase_instances actually replayed.
        outcome={"labels": ["y", "x"]},
        phase_instances=phase_instances,
        evidence_refs=(),
    )
    with pytest.raises(AssertionError, match="does not match the same pointer read"):
        _assert_trajectory_outcome_paths_are_consistent(corrupted, ("/labels",))


def test_r10_rejects_a_declared_path_the_final_state_does_not_have() -> None:
    """kernel_r9r10_review.md finding 2, mutation check: ruling R10 reads the
    SAME pointer from both the outcome and the final replayed state. A
    family whose outcome stores its trajectory under a different field name
    than its own state (e.g. "/public_history" copied from state
    "/history") cannot declare that path -- the raw ``KeyError`` this used
    to raise is now a clear, named assertion rather than an opaque crash."""
    phase_instances = (_phase_instance_ending_in_state({"history": ["x", "y"]}),)
    scoring_input = FamilyScoringInput(
        outcome={"public_history": ["x", "y"]},
        phase_instances=phase_instances,
        evidence_refs=(),
    )
    with pytest.raises(
        AssertionError, match="does not exist in the final replayed state"
    ):
        _assert_trajectory_outcome_paths_are_consistent(scoring_input, ("/public_history",))


def test_r10_is_a_no_op_when_no_paths_are_declared() -> None:
    """A family that declares no trajectory_outcome_paths gets no R10 check at
    all -- there is nothing to be consistent about, and (unlike the projection
    check) this must not even require phase_instances to have a transition."""
    scoring_input = FamilyScoringInput(
        outcome={"anything": "at all"}, phase_instances=(), evidence_refs=()
    )
    _assert_trajectory_outcome_paths_are_consistent(scoring_input, ())


def _fake_trajectory_score(leaf_id: str, value: float) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="ok",
        leaf=_reference_leaf(leaf_id=leaf_id, input_scope="trajectory"),
        primary=MetricValue(value, "indicator"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=(),
    )


def _fake_scoring_input(labels: Sequence[str], *, outcome: Mapping[str, Any]) -> FamilyScoringInput:
    """A ``FamilyScoringInput`` stand-in whose only load-bearing content is
    its ``phase_instances`` (for the same-case pair's phase_instances-differ
    check) -- ``outcome`` is carried only because ``FamilyScoringInput``
    requires it, and (fourth-pass review W1) is no longer inspected by the
    sensitivity witness itself; ``labels`` only needs to differ across
    fixtures that must disagree on ``phase_instances``."""
    return FamilyScoringInput(
        outcome=outcome,
        phase_instances=(_phase_instance_ending_in_state({"labels": tuple(labels)}),),
        evidence_refs=(),
    )


_FAKE_CASE = {"case_id": "fixture_case"}


def test_sensitivity_witness_passes_when_a_trajectory_leaf_changes_on_some_pair() -> None:
    """A SAME-CASE pair (kernel_r9r10_review.md finding 3, fourth-pass
    review W1): every fixture below shares the same ``family_case`` and a
    distinct ``phase_instances``, so every pair here qualifies, regardless
    of their (here, identical anyway) outcome."""
    leaf_id = "trajectory_leaf"
    outcome = {"tally": 1}
    fixtures = [
        (
            _fake_scoring_input(("x",), outcome=outcome),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            _FAKE_CASE,
        ),
        (
            _fake_scoring_input(("x", "y"), outcome=outcome),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            _FAKE_CASE,
        ),
        (
            _fake_scoring_input(("y", "x"), outcome=outcome),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 0.0),)),
            _FAKE_CASE,
        ),
    ]
    witnesses = _assert_trajectory_leaves_are_witnessed(fixtures, {leaf_id}, family_id="fixture_family")
    # The leaf is constant across the same-case pair (0, 1); only a pair
    # touching fixture 2 can witness it, and that is exactly what is
    # recorded.
    assert witnesses == {leaf_id: (0, 2)}


def test_sensitivity_witness_fails_when_a_trajectory_leaf_ignores_every_fixture() -> None:
    """Ruling R9(b), mutation check: a leaf that never changes across ANY
    same-case pair cannot be told apart from one that ignores its input
    entirely, and must be rejected as such."""
    leaf_id = "trajectory_leaf"
    outcome = {"tally": 1}
    fixtures = [
        (
            _fake_scoring_input(("x",), outcome=outcome),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            _FAKE_CASE,
        ),
        (
            _fake_scoring_input(("x", "y"), outcome=outcome),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            _FAKE_CASE,
        ),
        (
            _fake_scoring_input(("y", "x"), outcome=outcome),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            _FAKE_CASE,
        ),
    ]
    with pytest.raises(AssertionError, match="never changed"):
        _assert_trajectory_leaves_are_witnessed(fixtures, {leaf_id}, family_id="fixture_family")


def test_sensitivity_witness_passes_a_leaf_that_changes_only_via_a_differing_outcome_field() -> None:
    """kernel_r9r10_review.md finding 3, fourth-pass review W1: this is the
    case the second-pass review's identical-projection rule REJECTED
    (formerly ``test_sensitivity_witness_rejects_a_leaf_that_only_changes_on_an_uncontrolled_pair``)
    -- flipped, because that rule is unsatisfiable for a real family.
    govsim's ``govsim_no_collapse`` leaf (see this module's
    ``_assert_trajectory_leaves_are_witnessed`` docstring for the full
    counterexample) can NEVER be witnessed on a pair with an identical
    outcome: any two fixtures that genuinely differ on ``no_collapse``
    necessarily differ on ``num_round``, part of govsim's (whole) outcome,
    since govsim's ``outcome()`` never separates the trajectory from it at
    all. Fixtures 0 and 1 below share the same case, the same outcome, and
    differing ``phase_instances`` -- the leaf is constant across them, same
    as before. Fixture 2 shares the same case but has a genuinely different
    outcome; the leaf differs there too. Under ruling R7 (over-declaring
    trajectory scope is not the hazardous direction), that IS now a valid
    witness: the leaf is not constant across this family's own same-case
    fixtures, which is all this sanity check claims to show.
    """
    leaf_id = "trajectory_leaf"
    fixtures = [
        (
            _fake_scoring_input(("x",), outcome={"tag": "same"}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            _FAKE_CASE,
        ),
        (
            _fake_scoring_input(("x", "y"), outcome={"tag": "same"}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            _FAKE_CASE,
        ),
        (
            _fake_scoring_input(("y", "x"), outcome={"tag": "different"}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 0.0),)),
            _FAKE_CASE,
        ),
    ]
    witnesses = _assert_trajectory_leaves_are_witnessed(fixtures, {leaf_id}, family_id="fixture_family")
    # The leaf is constant across the same-case pair (0, 1); only a pair
    # touching fixture 2 -- whose outcome differs, not its trajectory --
    # witnesses it, and that is exactly what is recorded.
    assert witnesses == {leaf_id: (0, 2)}


def test_sensitivity_witness_rejects_a_pair_whose_case_differs() -> None:
    """kernel_r9r10_review.md finding 3, second-pass review R1 (kept by the
    fourth-pass review W1, which dropped only the identical-projection
    requirement, not this one): two fixtures from DIFFERENT cases, with
    differing ``phase_instances``, and a leaf that differs between them --
    but a difference caused by a DIFFERENT case is not evidence of
    anything a scorer measured about one case's trajectory, so this pair
    must not count. The family has supplied no other pair, so the witness
    is rejected outright rather than accepting this one.
    """
    leaf_id = "trajectory_leaf"
    fixtures = [
        (
            _fake_scoring_input(("x",), outcome={"tally": 1}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            {"case_id": "case_a"},
        ),
        (
            _fake_scoring_input(("x", "y"), outcome={"tally": 1}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 0.0),)),
            {"case_id": "case_b"},
        ),
    ]
    with pytest.raises(AssertionError, match="no same-case pair"):
        _assert_trajectory_leaves_are_witnessed(fixtures, {leaf_id}, family_id="fixture_family")


def test_sensitivity_witness_counts_a_status_only_flip() -> None:
    """kernel_r9r10_review.md finding 3: ``_score_measurement_content``
    counts a bare status/validity flip as a witnessed difference on a
    same-case pair, not only a differing ``primary`` value -- the compared
    content is unchanged from before the fourth-pass review's W1, which
    only relaxed which PAIRS qualify, never what counts as a difference on
    one."""
    leaf_id = "trajectory_leaf"
    left_score = _fake_trajectory_score(leaf_id, 1.0)
    right_score = dataclasses.replace(
        left_score,
        status="invalid_measurement",
        primary=None,
        validity=ValidityReport("invalid", ("trajectory_flip",)),
    )
    fixtures = [
        (
            _fake_scoring_input(("x",), outcome={"tag": "same"}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(left_score,)),
            _FAKE_CASE,
        ),
        (
            _fake_scoring_input(("x", "y"), outcome={"tag": "same"}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(right_score,)),
            _FAKE_CASE,
        ),
    ]
    witnesses = _assert_trajectory_leaves_are_witnessed(fixtures, {leaf_id}, family_id="fixture_family")
    assert witnesses == {leaf_id: (0, 1)}


def test_sensitivity_witness_is_vacuous_with_no_trajectory_leaves() -> None:
    fixtures = [
        (
            None,
            FamilyScoreSet(primary_leaf_id="anything", scores=(_fake_trajectory_score("anything", 1.0),)),
            None,
        ),
    ]
    assert (
        _assert_trajectory_leaves_are_witnessed(fixtures, set(), family_id="fixture_family") == {}
    )


def test_sensitivity_witness_requires_at_least_one_same_case_pair() -> None:
    """kernel_r9r10_review.md finding 3, fourth-pass review W1: if no
    supplied pair shares a case (with differing phase_instances), the
    family has not given the witness anything sound to check -- rejected
    explicitly, naming the cause, rather than silently accepting a pair
    from two different cases."""
    leaf_id = "trajectory_leaf"
    fixtures = [
        (
            _fake_scoring_input(("x",), outcome={"tag": "left"}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 1.0),)),
            {"case_id": "case_a"},
        ),
        (
            _fake_scoring_input(("y",), outcome={"tag": "right"}),
            FamilyScoreSet(primary_leaf_id=leaf_id, scores=(_fake_trajectory_score(leaf_id, 0.0),)),
            {"case_id": "case_b"},
        ),
    ]
    with pytest.raises(AssertionError, match="no same-case pair"):
        _assert_trajectory_leaves_are_witnessed(fixtures, {leaf_id}, family_id="fixture_family")
